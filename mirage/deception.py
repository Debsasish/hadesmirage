from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

import wasmtime
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection

from mirage import db
from mirage.auth import PrincipalContext
from mirage.common import DomainError, after, now, uid
from mirage.models import Invocation, PortalRequest, Transition
from mirage.policy import evaluate

if TYPE_CHECKING:
    from mirage.service import Service

TEMPLATE_ID = "supplier-portal-v1"
TEMPLATE_VERSION = "1.0.1-wasm"


def controller(tenant: str) -> PrincipalContext:
    return PrincipalContext(tenant, "deterministic-controller", ("orchestrator",), "service")


def change_route(
    service: Service,
    connection: Connection,
    context: PrincipalContext,
    session: dict[str, Any],
    mode: str,
    reason: str,
    decoy_id: str | None = None,
) -> dict[str, Any]:
    allowed = {
        "PRODUCTION": {"RESTRICTED", "TERMINATED"},
        "RESTRICTED": {"DECOY_PENDING", "TERMINATED"},
        "DECOY_PENDING": {"DECOY", "TERMINATED"},
        "DECOY": {"TERMINATED"},
        "TERMINATED": set(),
    }
    if mode not in allowed[session["route_mode"]]:
        raise DomainError(
            409, "INVALID_ROUTE_TRANSITION", "Route state cannot move in that direction"
        )
    version = session["route_version"] + 1
    history = session["history"] + [
        {"mode": mode, "version": version, "at": now(), "reason": reason}
    ]
    values: dict[str, Any] = {"route_mode": mode, "route_version": version, "history": history}
    if decoy_id is not None:
        values["decoy_id"] = decoy_id
    changed = connection.execute(
        update(db.sessions)
        .where(
            db.sessions.c.tenant_id == context.tenant_id,
            db.sessions.c.id == session["id"],
            db.sessions.c.route_version == session["route_version"],
        )
        .values(**values)
    )
    if changed.rowcount != 1:
        raise DomainError(409, "ROUTE_VERSION_CONFLICT", "Route changed; refresh before responding")
    current = {**session, **values}
    service.emit(
        connection,
        context,
        current,
        "control",
        "session.transitioned",
        "success",
        {"reason_code": reason},
    )
    service.audit(
        connection,
        context,
        "route." + mode.lower(),
        session["id"],
        {
            "route_version": version,
            "reason": reason,
        },
    )
    return current


def restrict(
    service: Service,
    connection: Connection,
    context: PrincipalContext,
    session: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    if session["route_mode"] == "PRODUCTION":
        return change_route(service, connection, context, session, "RESTRICTED", reason)
    return session


def engage(
    service: Service, connection: Connection, context: PrincipalContext, session: dict[str, Any]
) -> dict[str, Any]:
    if session["route_mode"] == "DECOY":
        return session
    state = (
        connection.execute(select(db.runtime).where(db.runtime.c.tenant_id == context.tenant_id))
        .mappings()
        .one()
    )
    case = (
        connection.execute(
            select(db.incidents).where(
                db.incidents.c.tenant_id == context.tenant_id,
                db.incidents.c.session_id == session["id"],
            )
        )
        .mappings()
        .first()
    )
    active = connection.execute(
        select(func.count()).select_from(db.decoys).where(db.decoys.c.state == "ACTIVE")
    ).scalar_one()
    eligible = (
        session["route_mode"] == "RESTRICTED"
        and session["caller_class"] == "external"
        and session["expires_at"] > now()
        and state["engagements_enabled"]
        and case is not None
        and set(case["rules"]).intersection({"D-002", "D-006"})
        and active < service.settings.max_engagements
        and service.sandbox.available()
    )
    if not eligible:
        return session
    session = change_route(
        service, connection, context, session, "DECOY_PENDING", "READY_TEMPLATE_RESERVED"
    )
    decoy_id = uid()
    connection.execute(
        insert(db.decoys).values(
            tenant_id=context.tenant_id,
            id=decoy_id,
            session_id=session["id"],
            template_id=TEMPLATE_ID,
            template_version=TEMPLATE_VERSION,
            state="ACTIVE",
            synthetic_state={"requests": 0, "changes": 0},
            requests=0,
            model_tokens=0,
            expires_at=min(after(service.settings.session_ttl_seconds), session["expires_at"]),
            created_at=now(),
            attestation=service.sandbox.attestation,
            cleanup_state="not_due",
        )
    )
    return change_route(
        service, connection, context, session, "DECOY", "ISOLATED_TEMPLATE_PINNED", decoy_id
    )


def terminate(
    service: Service,
    connection: Connection,
    context: PrincipalContext,
    session: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    if session["route_mode"] != "TERMINATED":
        session = change_route(service, connection, context, session, "TERMINATED", reason)
    if session["decoy_id"]:
        connection.execute(
            update(db.decoys)
            .where(
                db.decoys.c.tenant_id == context.tenant_id,
                db.decoys.c.id == session["decoy_id"],
            )
            .values(state="DESTROYED", synthetic_state={}, cleanup_state="purged")
        )
    return session


def transition(
    service: Service,
    context: PrincipalContext,
    session_id: str,
    action: str,
    request: Transition,
    key: str,
) -> dict[str, Any]:
    context.require("orchestrator" if action == "engage" else "analyst", "security_admin")
    with service.db.transaction() as connection:
        route = f"/sessions/{session_id}/{action}"
        body = request.model_dump()
        previous = service.idempotent_get(connection, context, route, key, body)
        if previous is not None:
            return previous
        session = service.required(connection, db.sessions, context.tenant_id, session_id)
        if session["route_version"] != request.expected_route_version:
            raise DomainError(
                409, "ROUTE_VERSION_CONFLICT", "Session route changed; refresh its evidence"
            )
        for event_id in request.evidence_event_ids:
            event = service.required(connection, db.events, context.tenant_id, event_id)
            if event["session_id"] != session_id:
                raise DomainError(
                    422, "UNRELATED_EVIDENCE", "Response evidence belongs to another session"
                )
        service.emit(
            connection,
            context,
            session,
            "control",
            "request.observed",
            "observed",
            {
                "reason_code": "OPERATOR_" + action.upper(),
                "snippet": request.reason_code,
            },
        )
        if action == "restrict":
            result = restrict(service, connection, context, session, request.reason_code)
        elif action == "terminate":
            result = terminate(service, connection, context, session, request.reason_code)
        else:
            result = engage(service, connection, context, session)
            if result["route_mode"] != "DECOY":
                return {
                    **result,
                    "engagement_error": "Not eligible or no verified template; production remains restricted",
                }
        service.idempotent_put(connection, context, route, key, body, result)
        return result


def portal(
    service: Service, context: PrincipalContext, request: PortalRequest, key: str
) -> tuple[int, dict[str, Any]]:
    context.require("external")
    with service.db.transaction() as connection:
        service.admit(connection, context, "portal")
        session = service.owned_session(connection, context, request.session_id)
        route = "/portal/request"
        if session["route_mode"] == "TERMINATED":
            return 403, {
                "code": "ENGAGEMENT_STOPPED",
                "route_mode": "TERMINATED",
                "production_fallback": False,
            }
        previous = service.idempotent_get(connection, context, route, key, request.model_dump())
        if previous is not None:
            if previous["response"].get("route_mode") != session["route_mode"]:
                return 403, {"code": "RETRY_ROUTE_FENCED", "production_fallback": False}
            return previous["http_status"], previous["response"]
        if session["expires_at"] <= now():
            terminate(
                service, connection, controller(context.tenant_id), session, "SESSION_TTL_EXPIRED"
            )
            return 403, {"code": "SESSION_EXPIRED", "route_mode": "TERMINATED"}
        attrs = {"tool": request.tool, "resource": request.resource, "snippet": request.snippet}
        if session["route_mode"] == "DECOY":
            decoy = service.required(connection, db.decoys, context.tenant_id, session["decoy_id"])
            if (
                not service.sandbox.available()
                or decoy["state"] != "ACTIVE"
                or decoy["expires_at"] <= now()
                or decoy["requests"] >= service.settings.decoy_request_budget
            ):
                terminate(
                    service,
                    connection,
                    controller(context.tenant_id),
                    session,
                    "DECOY_LIMIT_OR_READINESS_FAILURE",
                )
                return 403, {
                    "code": "ENGAGEMENT_STOPPED",
                    "route_mode": "TERMINATED",
                    "production_fallback": False,
                }
            if request.tool == "payment.change_request":
                return 403, {
                    "code": "TRANSACTIONAL_ENDPOINT_INELIGIBLE",
                    "production_fallback": False,
                }
            seed = int(
                hashlib.sha256((context.tenant_id + session["id"]).encode()).hexdigest()[:8], 16
            )
            try:
                result, state = service.sandbox.respond(
                    request.tool, decoy["synthetic_state"], seed
                )
            except (wasmtime.WasmtimeError, wasmtime.Trap, ValueError):
                terminate(
                    service,
                    connection,
                    controller(context.tenant_id),
                    session,
                    "DECOY_RUNTIME_FAILURE",
                )
                service.audit(
                    connection,
                    context,
                    "decoy.failure",
                    decoy["id"],
                    {"production_fallback": False},
                )
                return 503, {"code": "DECOY_UNAVAILABLE", "production_fallback": False}
            connection.execute(
                update(db.decoys)
                .where(db.decoys.c.tenant_id == context.tenant_id, db.decoys.c.id == decoy["id"])
                .values(requests=decoy["requests"] + 1, synthetic_state=state)
            )
            service.emit(
                connection,
                context,
                session,
                "decoy_router",
                "decoy.observed",
                "simulated",
                {
                    **attrs,
                    "reason_code": "VERIFIED_SYNTHETIC_INTERACTION",
                },
            )
            result = {
                **result,
                "route_mode": "DECOY",
                "route_version": session["route_version"],
                "decoy_id": decoy["id"],
                "wording_provider": "static-template",
            }
            service.idempotent_put(
                connection,
                context,
                route,
                key,
                request.model_dump(),
                {
                    "http_status": 200,
                    "response": result,
                },
            )
            return 200, result
        if session["route_mode"] != "PRODUCTION":
            return 403, {
                "code": "ROUTE_BLOCKED",
                "route_mode": session["route_mode"],
                "production_fallback": False,
            }
        service.emit(connection, context, session, "edge", "request.observed", "observed", attrs)
        if request.tool == "supplier.lookup" and request.resource in {
            "supplier:demo-001",
            "supplier:demo-002",
        }:
            identifier = request.resource.split(":")[1]
            operation = Invocation(
                tool="supplier.lookup",
                action="read",
                resource=request.resource,
                arguments={"supplier_id": identifier},
                session_id=session["id"],
            )
            principal = service.required(
                connection, db.principals, context.tenant_id, context.principal_id
            )
            policy = service.active_policy(connection, context.tenant_id)
            decision, reason = evaluate(policy, principal, operation)
            if decision == "allow":
                execution_id = str(
                    uuid5(
                        NAMESPACE_URL,
                        f"hades-mirage:{context.tenant_id}:portal:{session['id']}:{key}",
                    )
                )
                execution = service.execute_fenced(
                    connection,
                    context,
                    session,
                    operation,
                    "portal:" + key,
                    policy,
                    reason,
                    execution_id,
                    {**attrs, "reason_code": reason, "policy_version": policy.version},
                    "edge",
                )
                status = 200 if execution["execution_state"] == "succeeded" else 503
                result = {
                    **(
                        execution["result"]
                        if status == 200
                        else {"code": "BACKEND_OUTCOME_UNKNOWN"}
                    ),
                    "execution_id": execution_id,
                    "execution_state": execution["execution_state"],
                    "route_mode": "PRODUCTION",
                    "route_version": session["route_version"],
                }
                service.idempotent_put(
                    connection,
                    context,
                    route,
                    key,
                    request.model_dump(),
                    {
                        "http_status": status,
                        "response": result,
                    },
                )
                return status, result
        service.emit(
            connection,
            context,
            session,
            "edge",
            "authorization.decided",
            "deny",
            {
                **attrs,
                "reason_code": "PROHIBITED_TOOL"
                if request.tool in {"customer.export", "infrastructure.delete"}
                else "RESOURCE_OUT_OF_SCOPE",
            },
        )
        denial = {
            "code": "PORTAL_ACCESS_DENIED",
            "route_mode": "PRODUCTION",
            "backend_dispatched": False,
        }
        service.idempotent_put(
            connection,
            context,
            route,
            key,
            request.model_dump(),
            {
                "http_status": 403,
                "response": denial,
            },
        )
        return 403, denial


def sweep(service: Service) -> int:
    count = 0
    with service.db.transaction() as connection:
        expired = db.rows(
            connection,
            select(db.sessions)
            .where(db.sessions.c.route_mode != "TERMINATED", db.sessions.c.expires_at <= now())
            .limit(100),
        )
        for session in expired:
            terminate(
                service,
                connection,
                controller(session["tenant_id"]),
                session,
                "SESSION_TTL_EXPIRED",
            )
            count += 1
    return count


def kill_switch(service: Service, context: PrincipalContext, key: str) -> dict[str, Any]:
    context.require("analyst")
    with service.db.transaction() as connection:
        previous = service.idempotent_get(connection, context, "/deception/kill-switch", key, {})
        if previous is not None:
            return previous
        connection.execute(
            update(db.runtime)
            .where(db.runtime.c.tenant_id == context.tenant_id)
            .values(
                engagements_enabled=False,
            )
        )
        active = db.rows(
            connection,
            select(db.sessions).where(
                db.sessions.c.tenant_id == context.tenant_id,
                db.sessions.c.route_mode.in_(["DECOY", "DECOY_PENDING"]),
            ),
        )
        for session in active:
            terminate(service, connection, context, session, "ANALYST_KILL_SWITCH")
        service.audit(
            connection,
            context,
            "deception.kill_switch",
            context.tenant_id,
            {"terminated": len(active)},
        )
        result = {
            "terminated": len(active),
            "new_engagements_enabled": False,
            "production_restored": False,
        }
        service.idempotent_put(connection, context, "/deception/kill-switch", key, {}, result)
        return result
