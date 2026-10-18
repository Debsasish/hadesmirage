from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection

from mirage import db
from mirage.auth import PrincipalContext, token_hash, verify_lineage
from mirage.backend import Backend
from mirage.common import DomainError, after, digest, now, redact, uid
from mirage.config import Settings
from mirage.models import ApprovalDecision, DelegationRequest, Invocation, Policy
from mirage.policy import action_digest, evaluate, subset
from mirage.providers import provider
from mirage.sandbox import Sandbox


class Service:
    def __init__(self, database: db.Database, settings: Settings, backend: Backend) -> None:
        self.db = database
        self.settings = settings
        self.backend = backend
        self.sandbox = Sandbox()
        self.provider = provider(settings)

    def required(
        self, connection: Connection, table: Any, tenant: str, identifier: str
    ) -> dict[str, Any]:
        found = db.row(connection, table, tenant, identifier)
        if found is None:
            raise DomainError(404, "NOT_FOUND", "Record not found in your authorized scope")
        return found

    def audit(
        self,
        connection: Connection,
        context: PrincipalContext,
        action: str,
        object_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        latest = (
            connection.execute(
                select(db.audit_log)
                .where(db.audit_log.c.tenant_id == context.tenant_id)
                .order_by(db.audit_log.c.sequence.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        value = {
            "tenant_id": context.tenant_id,
            "id": uid(),
            "sequence": latest["sequence"] + 1 if latest else 1,
            "actor_id": context.principal_id,
            "action": action,
            "object_id": object_id,
            "details": details or {},
            "created_at": now(),
            "previous_digest": latest["integrity_digest"] if latest else "0" * 64,
        }
        connection.execute(insert(db.audit_log).values(**value, integrity_digest=digest(value)))

    def active_policy(self, connection: Connection, tenant: str) -> Policy:
        state = (
            connection.execute(select(db.runtime).where(db.runtime.c.tenant_id == tenant))
            .mappings()
            .first()
        )
        if state is None:
            raise DomainError(
                503, "POLICY_UNAVAILABLE", "Authoritative policy unavailable; dispatch denied"
            )
        policy = db.row(connection, db.policy_versions, tenant, state["active_policy_id"])
        if policy is None or policy["status"] != "active":
            raise DomainError(503, "POLICY_UNAVAILABLE", "No active policy; dispatch denied")
        return Policy.model_validate(policy["document"])

    def admit(
        self, connection: Connection, context: PrincipalContext, bucket: str, limit: int = 240
    ) -> None:
        principal = self.required(
            connection, db.principals, context.tenant_id, context.principal_id
        )
        identifier = principal["root_id"] + ":" + bucket
        window = int(time.time()) // 60
        current = db.row(connection, db.rate_limits, context.tenant_id, identifier)
        if current and current["window"] == window and current["count"] >= limit:
            raise DomainError(
                429, "REQUEST_BUDGET_EXHAUSTED", "The per-identity request budget is exhausted"
            )
        count = current["count"] + 1 if current and current["window"] == window else 1
        if current:
            connection.execute(
                update(db.rate_limits)
                .where(
                    db.rate_limits.c.tenant_id == context.tenant_id,
                    db.rate_limits.c.id == identifier,
                )
                .values(window=window, count=count)
            )
        else:
            connection.execute(
                insert(db.rate_limits).values(
                    tenant_id=context.tenant_id,
                    id=identifier,
                    window=window,
                    count=count,
                )
            )

    def create_session(
        self, context: PrincipalContext, origin: str = "live", key: str | None = None
    ) -> dict[str, Any]:
        context.require("workload", "external")
        with self.db.transaction() as connection:
            if key:
                previous = self.idempotent_get(
                    connection, context, "/sessions", key, {"origin": origin}
                )
                if previous is not None:
                    return previous
            principal = self.required(
                connection, db.principals, context.tenant_id, context.principal_id
            )
            verify_lineage(connection, principal)
            self.admit(connection, context, "sessions")
            value = {
                "tenant_id": context.tenant_id,
                "id": uid(),
                "principal_id": context.principal_id,
                "caller_class": "external" if context.kind == "external" else "internal",
                "route_mode": "PRODUCTION",
                "route_version": 1,
                "decoy_id": None,
                "origin": origin,
                "created_at": now(),
                "expires_at": after(self.settings.session_ttl_seconds),
                "history": [
                    {"mode": "PRODUCTION", "version": 1, "at": now(), "reason": "SESSION_CREATED"}
                ],
            }
            connection.execute(insert(db.sessions).values(**value))
            self.audit(connection, context, "session.created", value["id"], {"origin": origin})
            if key:
                self.idempotent_put(
                    connection, context, "/sessions", key, {"origin": origin}, value
                )
            return value

    def owned_session(
        self, connection: Connection, context: PrincipalContext, session_id: str
    ) -> dict[str, Any]:
        session = self.required(connection, db.sessions, context.tenant_id, session_id)
        if session["principal_id"] != context.principal_id:
            raise DomainError(404, "NOT_FOUND", "Session not found in your authorized scope")
        return session

    def emit(
        self,
        connection: Connection,
        context: PrincipalContext,
        session: dict[str, Any],
        source: str,
        event_type: str,
        outcome: str,
        attributes: dict[str, Any],
    ) -> str:
        event_id = uid()
        attributes = {key: value for key, value in attributes.items() if value is not None}
        if "snippet" in attributes:
            attributes["snippet"] = redact(attributes["snippet"])
        body = {
            "schema_version": "1.0",
            "event_id": event_id,
            "tenant_id": context.tenant_id,
            "session_id": session["id"],
            "source": source,
            "event_type": event_type,
            "occurred_at": now(),
            "route_mode": session["route_mode"],
            "outcome": outcome,
            "principal_id": session["principal_id"],
            "attributes": attributes,
        }
        self.store_event(connection, body, session["origin"], trusted=True)
        return event_id

    def store_event(
        self,
        connection: Connection,
        body: dict[str, Any],
        origin: str,
        trusted: bool,
        original_digest: str | None = None,
    ) -> bool:
        tenant, event_id = body["tenant_id"], body["event_id"]
        body_digest = original_digest or digest(body)
        existing = db.row(connection, db.events, tenant, event_id)
        if existing:
            if existing["body_digest"] != body_digest:
                raise DomainError(
                    409, "EVENT_ID_CONFLICT", "Event ID already has different content"
                )
            return False
        sequence = db.next_sequence(connection, tenant, "events")
        received = now()
        connection.execute(
            insert(db.events).values(
                tenant_id=tenant,
                id=event_id,
                sequence=sequence,
                session_id=body["session_id"],
                source=body["source"],
                event_type=body["event_type"],
                outcome=body["outcome"],
                received_at=received,
                occurred_at=body["occurred_at"],
                body_digest=body_digest,
                body=body,
                trusted=trusted,
                origin=origin,
            )
        )
        connection.execute(
            insert(db.outbox).values(
                tenant_id=tenant,
                id=uid(),
                event_id=event_id,
                processed_at=None,
                created_at=received,
            )
        )
        return True

    def drain_outbox(self) -> int:
        from mirage.detection import drain

        return drain(self)

    def _decision(
        self,
        policy: Policy,
        decision: str,
        reason: str,
        state: str = "not_started",
        execution_id: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        value: dict[str, Any] = {
            "decision_id": uid(),
            "decision": decision,
            "reason_code": reason,
            "policy_version": policy.version,
            "evaluated_at": now(),
            "execution_state": state,
        }
        if execution_id is not None:
            value["execution_id"] = execution_id
        if result is not None:
            value["result"] = result
        return value

    def invoke(
        self, context: PrincipalContext, operation: Invocation, key: str
    ) -> tuple[int, dict[str, Any]]:
        context.require("workload")
        with self.db.transaction() as connection:
            self.admit(connection, context, "invocations")
            session = self.owned_session(connection, context, operation.session_id)
            principal = self.required(
                connection, db.principals, context.tenant_id, context.principal_id
            )
            verify_lineage(connection, principal)
            policy = self.active_policy(connection, context.tenant_id)
            if session["route_mode"] != "PRODUCTION" or session["expires_at"] <= now():
                decision, reason = "deny", "ROUTE_BLOCKED"
            else:
                decision, reason = evaluate(policy, principal, operation)
            attrs = {
                "tool": operation.tool,
                "action": operation.action,
                "resource": operation.resource,
                "policy_version": policy.version,
                "reason_code": reason,
            }
            if decision == "deny":
                self.emit(
                    connection,
                    context,
                    session,
                    "dispatcher",
                    "authorization.decided",
                    decision,
                    attrs,
                )
                self.audit(connection, context, "tool.denied", operation.session_id, attrs)
                return 403, self._decision(policy, decision, reason)
            action_hash = action_digest(
                context.tenant_id, context.principal_id, operation, policy.version
            )
            previous = (
                connection.execute(
                    select(db.executions).where(
                        db.executions.c.tenant_id == context.tenant_id,
                        db.executions.c.principal_id == context.principal_id,
                        db.executions.c.session_id == session["id"],
                        db.executions.c.idempotency_key == key,
                    )
                )
                .mappings()
                .first()
            )
            if previous:
                if previous["digest"] != action_hash:
                    raise DomainError(
                        409,
                        "IDEMPOTENCY_CONFLICT",
                        "Idempotency key is bound to a different action",
                    )
                return 200, previous["decision"]
            pending = connection.execute(
                select(func.count())
                .select_from(db.outbox)
                .where(
                    db.outbox.c.tenant_id == context.tenant_id, db.outbox.c.processed_at.is_(None)
                )
            ).scalar_one()
            if pending >= self.settings.audit_backpressure:
                raise DomainError(
                    503, "AUDIT_BACKPRESSURE", "Evidence backlog prevents new executions"
                )
            approval: dict[str, Any] | None = None
            if decision == "require_approval":
                if operation.approval_id:
                    approval = db.row(
                        connection, db.approvals, context.tenant_id, operation.approval_id
                    )
                    if (
                        approval is None
                        or approval["digest"] != action_hash
                        or approval["principal_id"] != context.principal_id
                        or approval["policy_version"] != policy.version
                        or approval["status"] != "approved"
                        or approval["expires_at"] <= now()
                    ):
                        attrs["reason_code"] = "APPROVAL_VERIFICATION_FAILED"
                        self.emit(
                            connection,
                            context,
                            session,
                            "dispatcher",
                            "authorization.decided",
                            "deny",
                            attrs,
                        )
                        self.audit(
                            connection,
                            context,
                            "approval.verification_failed",
                            operation.approval_id,
                        )
                        return 403, self._decision(policy, "deny", "APPROVAL_VERIFICATION_FAILED")
                else:
                    self.emit(
                        connection,
                        context,
                        session,
                        "dispatcher",
                        "authorization.decided",
                        decision,
                        attrs,
                    )
                    return 428, self._decision(policy, decision, reason)
            backend_binding = (
                f"approval:{approval['id']}"
                if approval
                else f"request:{context.principal_id}:{session['id']}:{key}"
            )
            execution_id = str(
                uuid5(NAMESPACE_URL, f"hades-mirage:{context.tenant_id}:{backend_binding}")
            )
            if approval:
                connection.execute(
                    update(db.approvals)
                    .where(
                        db.approvals.c.tenant_id == context.tenant_id,
                        db.approvals.c.id == approval["id"],
                        db.approvals.c.status == "approved",
                    )
                    .values(status="consumed")
                )
            final = self.execute_fenced(
                connection,
                context,
                session,
                operation,
                key,
                policy,
                "APPROVED_ACTION" if approval else reason,
                execution_id,
                attrs,
                "dispatcher",
            )
            return 200, final

    def execute_fenced(
        self,
        connection: Connection,
        context: PrincipalContext,
        session: dict[str, Any],
        operation: Invocation,
        key: str,
        policy: Policy,
        reason: str,
        execution_id: str,
        attributes: dict[str, Any],
        source: str,
    ) -> dict[str, Any]:
        current = self.required(connection, db.sessions, context.tenant_id, session["id"])
        if (
            current["route_mode"] != "PRODUCTION"
            or current["route_version"] != session["route_version"]
        ):
            raise DomainError(403, "DISPATCH_FENCED", "Route changed before backend admission")
        reserved = self._decision(policy, "allow", reason, "reserved", execution_id)
        connection.execute(
            insert(db.executions).values(
                tenant_id=context.tenant_id,
                id=execution_id,
                principal_id=context.principal_id,
                session_id=session["id"],
                idempotency_key=key,
                digest=action_digest(
                    context.tenant_id, context.principal_id, operation, policy.version
                ),
                state="reserved",
                decision=reserved,
                created_at=now(),
            )
        )
        self.emit(
            connection, context, session, source, "authorization.decided", "allow", attributes
        )
        envelope = {
            "tenant_id": context.tenant_id,
            "principal_id": context.principal_id,
            "execution_id": execution_id,
            "invocation": operation.model_dump(exclude_none=True, exclude={"approval_id"}),
            "policy_version": policy.version,
            "route_version": session["route_version"],
        }
        # The shared database fence remains held through bounded backend admission.
        try:
            result = self.backend.execute(envelope)
            final = self._decision(policy, "allow", reason, "succeeded", execution_id, result)
            outcome = "success"
        except (httpx.HTTPError, DomainError) as error:
            final = self._decision(
                policy, "allow", "BACKEND_OUTCOME_UNKNOWN", "unknown", execution_id
            )
            outcome = "failure"
            self.audit(
                connection,
                context,
                "execution.unknown",
                execution_id,
                {"error_type": type(error).__name__},
            )
        connection.execute(
            update(db.executions)
            .where(
                db.executions.c.tenant_id == context.tenant_id,
                db.executions.c.id == execution_id,
            )
            .values(state=final["execution_state"], decision=final)
        )
        self.emit(
            connection,
            context,
            session,
            source,
            "tool.completed",
            outcome,
            {
                **attributes,
                "reason_code": final["reason_code"],
            },
        )
        self.audit(
            connection,
            context,
            "tool.executed",
            execution_id,
            {
                "state": final["execution_state"],
                "tool": operation.tool,
                "route_version": session["route_version"],
            },
        )
        return final

    def request_approval(
        self,
        context: PrincipalContext,
        operation: Invocation,
        key: str,
        requester: str | None = None,
    ) -> dict[str, Any]:
        context.require("workload")
        if "approval_id" in operation.model_fields_set:
            raise DomainError(
                422, "APPROVAL_ID_FORBIDDEN", "New approval requests cannot contain an approval ID"
            )
        with self.db.transaction() as connection:
            session = self.owned_session(connection, context, operation.session_id)
            if session["route_mode"] != "PRODUCTION" or session["expires_at"] <= now():
                raise DomainError(
                    403, "ROUTE_BLOCKED", "Approval cannot be requested for a blocked session"
                )
            principal = self.required(
                connection, db.principals, context.tenant_id, context.principal_id
            )
            verify_lineage(connection, principal)
            policy = self.active_policy(connection, context.tenant_id)
            decision, _ = evaluate(policy, principal, operation)
            if decision != "require_approval":
                raise DomainError(
                    403, "APPROVAL_INELIGIBLE", "Only an allowed sensitive action is reviewable"
                )
            body = operation.model_dump(exclude_none=True)
            previous = self.idempotent_get(connection, context, "/approvals", key, body)
            if previous is not None:
                return previous
            value = {
                "tenant_id": context.tenant_id,
                "id": uid(),
                "requester_id": requester or context.principal_id,
                "principal_id": context.principal_id,
                "session_id": session["id"],
                "digest": action_digest(
                    context.tenant_id, context.principal_id, operation, policy.version
                ),
                "policy_version": policy.version,
                "invocation": body,
                "status": "pending",
                "approver_id": None,
                "expires_at": min(after(600), session["expires_at"]),
                "created_at": now(),
            }
            connection.execute(insert(db.approvals).values(**value))
            self.audit(
                connection, context, "approval.requested", value["id"], {"digest": value["digest"]}
            )
            self.idempotent_put(connection, context, "/approvals", key, body, value)
            return value

    def decide_approval(
        self, context: PrincipalContext, identifier: str, request: ApprovalDecision, key: str
    ) -> dict[str, Any]:
        context.require("approver")
        with self.db.transaction() as connection:
            body = request.model_dump()
            route = f"/approvals/{identifier}/decision"
            previous = self.idempotent_get(connection, context, route, key, body)
            if previous is not None:
                return previous
            approval = self.required(connection, db.approvals, context.tenant_id, identifier)
            if context.principal_id in {approval["requester_id"], approval["principal_id"]}:
                raise DomainError(
                    403, "SELF_APPROVAL_DENIED", "A separate reviewer must decide this action"
                )
            policy = self.active_policy(connection, context.tenant_id)
            if (
                approval["status"] != "pending"
                or approval["expires_at"] <= now()
                or approval["digest"] != request.expected_digest
                or approval["policy_version"] != policy.version
            ):
                raise DomainError(
                    409, "APPROVAL_STALE", "Approval is stale, expired or has a different digest"
                )
            status = "approved" if request.decision == "approve" else "rejected"
            connection.execute(
                update(db.approvals)
                .where(
                    db.approvals.c.tenant_id == context.tenant_id, db.approvals.c.id == identifier
                )
                .values(status=status, approver_id=context.principal_id)
            )
            value = {**approval, "status": status, "approver_id": context.principal_id}
            self.audit(
                connection,
                context,
                "approval." + status,
                identifier,
                {"digest": approval["digest"]},
            )
            self.idempotent_put(connection, context, route, key, body, value)
            return value

    def idempotent_get(
        self,
        connection: Connection,
        context: PrincipalContext,
        route: str,
        key: str,
        body: Any,
    ) -> dict[str, Any] | None:
        previous = (
            connection.execute(
                select(db.idempotency).where(
                    db.idempotency.c.tenant_id == context.tenant_id,
                    db.idempotency.c.principal_id == context.principal_id,
                    db.idempotency.c.route == route,
                    db.idempotency.c.key == key,
                )
            )
            .mappings()
            .first()
        )
        if previous:
            if previous["digest"] != digest(body):
                raise DomainError(
                    409, "IDEMPOTENCY_CONFLICT", "Retry body differs from the original operation"
                )
            return previous["response"]
        return None

    def idempotent_put(
        self,
        connection: Connection,
        context: PrincipalContext,
        route: str,
        key: str,
        body: Any,
        response: dict[str, Any],
    ) -> None:
        connection.execute(
            insert(db.idempotency).values(
                tenant_id=context.tenant_id,
                id=uid(),
                principal_id=context.principal_id,
                route=route,
                key=key,
                digest=digest(body),
                response=response,
            )
        )

    def delegate(
        self, context: PrincipalContext, request: DelegationRequest, key: str, origin: str = "live"
    ) -> tuple[int, dict[str, Any]]:
        context.require("workload")
        try:
            parsed = datetime.fromisoformat(request.expires_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Timezone required")
        except ValueError as error:
            raise DomainError(
                422, "INVALID_EXPIRY", "Delegation expiry must be timezone-aware"
            ) from error
        expiry = parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        with self.db.transaction() as connection:
            previous = self.idempotent_get(
                connection, context, "/delegations", key, request.model_dump()
            )
            if previous is not None:
                return 200, previous
            parent = self.required(
                connection, db.principals, context.tenant_id, context.principal_id
            )
            verify_lineage(connection, parent)
            self.admit(connection, context, "delegations", limit=30)
            children = connection.execute(
                select(func.count())
                .select_from(db.principals)
                .where(
                    db.principals.c.tenant_id == context.tenant_id,
                    db.principals.c.parent_id == parent["id"],
                    db.principals.c.status == "active",
                    db.principals.c.expires_at > now(),
                )
            ).scalar_one()
            if children >= 10:
                raise DomainError(
                    429, "DELEGATION_BUDGET_EXHAUSTED", "Active child identity budget exhausted"
                )
            scopes = [item.model_dump() for item in request.scopes]
            if (
                not subset(scopes, parent["scopes"])
                or parent["depth"] >= 2
                or expiry > parent["expires_at"]
                or expiry <= now()
            ):
                session = self.create_delegation_event_session(connection, context, origin)
                self.emit(
                    connection,
                    context,
                    session,
                    "dispatcher",
                    "authorization.decided",
                    "deny",
                    {
                        "reason_code": "DELEGATION_ESCALATION",
                        "resource": request.child_id,
                    },
                )
                self.audit(connection, context, "delegation.denied", request.child_id)
                return 403, {
                    "code": "DELEGATION_ESCALATION",
                    "message": "Child scope or lifetime exceeds its parent",
                    "session_id": session["id"],
                }
            if db.row(connection, db.principals, context.tenant_id, request.child_id):
                raise DomainError(409, "IDENTITY_EXISTS", "Child identity already exists")
            token = secrets.token_urlsafe(40)
            child = {
                "tenant_id": context.tenant_id,
                "id": request.child_id,
                "name": request.name,
                "kind": "workload",
                "roles": ["workload"],
                "status": "active",
                "scopes": scopes,
                "parent_id": parent["id"],
                "root_id": parent["root_id"],
                "depth": parent["depth"] + 1,
                "expires_at": expiry,
                "identity_epoch": 1,
                "owner": parent["owner"],
                "created_at": now(),
            }
            connection.execute(insert(db.principals).values(**child))
            connection.execute(
                insert(db.credentials).values(
                    token_hash=token_hash(token),
                    tenant_id=context.tenant_id,
                    principal_id=child["id"],
                    source=None,
                    expires_at=expiry,
                    csrf=None,
                    kind="bearer",
                )
            )
            self.audit(
                connection, context, "delegation.issued", child["id"], {"parent_id": parent["id"]}
            )
            self.idempotent_put(
                connection,
                context,
                "/delegations",
                key,
                request.model_dump(),
                {
                    "principal": child,
                    "credential": None,
                    "credential_display": "credential was returned only on first issuance",
                },
            )
            return 201, {
                "principal": child,
                "credential": token,
                "credential_display": "returned once; not stored in plaintext",
            }

    def create_delegation_event_session(
        self, connection: Connection, context: PrincipalContext, origin: str = "live"
    ) -> dict[str, Any]:
        value = {
            "tenant_id": context.tenant_id,
            "id": uid(),
            "principal_id": context.principal_id,
            "caller_class": "internal",
            "route_mode": "PRODUCTION",
            "route_version": 1,
            "decoy_id": None,
            "origin": origin,
            "created_at": now(),
            "expires_at": after(600),
            "history": [
                {"mode": "PRODUCTION", "version": 1, "at": now(), "reason": "DELEGATION_CHECK"}
            ],
        }
        connection.execute(insert(db.sessions).values(**value))
        return value

    def reconcile(self, context: PrincipalContext, execution_id: str) -> dict[str, Any]:
        context.require("analyst")
        with self.db.transaction() as connection:
            execution = self.required(connection, db.executions, context.tenant_id, execution_id)
            if execution["state"] != "unknown":
                return execution["decision"]
            result = self.backend.result(execution_id)
            if result is None:
                self.audit(connection, context, "execution.still_unknown", execution_id)
                return execution["decision"]
            final = {
                **execution["decision"],
                "execution_state": "succeeded",
                "result": result,
                "reason_code": "BACKEND_RECONCILED",
            }
            connection.execute(
                update(db.executions)
                .where(
                    db.executions.c.tenant_id == context.tenant_id,
                    db.executions.c.id == execution_id,
                )
                .values(state="succeeded", decision=final)
            )
            self.audit(connection, context, "execution.reconciled", execution_id)
            return final
