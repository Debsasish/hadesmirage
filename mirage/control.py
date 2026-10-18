from __future__ import annotations

import html
import json
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, func, insert, select, update

from mirage import __version__, db
from mirage.auth import PrincipalContext
from mirage.common import DomainError, digest, now, redact, uid
from mirage.detection import RULE_VERSION, RULES
from mirage.models import EventInput, Invocation, Policy, PolicyTransition
from mirage.policy import evaluate

if TYPE_CHECKING:
    from mirage.service import Service


def provenance() -> dict[str, Any]:
    return json.loads(files("mirage.resources").joinpath("provenance.json").read_text())


def ingest(service: Service, context: PrincipalContext, request: EventInput) -> dict[str, Any]:
    context.require("event_producer")
    if request.tenant_id != context.tenant_id or request.source != context.source:
        raise DomainError(
            403, "PRODUCER_BINDING_MISMATCH", "Producer is not bound to this tenant and source"
        )
    if request.source != "gateway" or request.event_type != "gateway.decided":
        raise DomainError(
            403,
            "PRODUCER_EVENT_TYPE_DENIED",
            "This producer may submit structured gateway observations only",
        )
    body = request.model_dump(exclude_none=True)
    if set(body["attributes"]) - {"destination", "reason_code", "snippet"}:
        raise DomainError(
            422,
            "GATEWAY_ATTRIBUTE_SCOPE",
            "Gateway telemetry cannot assert application tool decisions",
        )
    original_digest = digest(body)
    with service.db.transaction() as connection:
        existing = db.row(connection, db.events, context.tenant_id, request.event_id)
        if existing is not None:
            if existing["body_digest"] != original_digest:
                raise DomainError(
                    409, "EVENT_ID_CONFLICT", "Event ID already has different content"
                )
            return {
                "event_id": request.event_id,
                "status": "duplicate",
                "received_at": existing["received_at"],
            }
        session = service.required(connection, db.sessions, context.tenant_id, request.session_id)
        if (
            request.principal_id != session["principal_id"]
            or request.route_mode != session["route_mode"]
        ):
            raise DomainError(
                422,
                "EVENT_CONTEXT_MISMATCH",
                "Claimed context differs from authoritative session state",
            )
        rate = db.row(connection, db.rate_limits, context.tenant_id, context.principal_id)
        window = int(time.time()) // 60
        if rate and rate["window"] == window and rate["count"] >= 240:
            raise DomainError(429, "PRODUCER_RATE_LIMIT", "Event producer budget exhausted")
        count = rate["count"] + 1 if rate and rate["window"] == window else 1
        if rate:
            connection.execute(
                update(db.rate_limits)
                .where(
                    db.rate_limits.c.tenant_id == context.tenant_id,
                    db.rate_limits.c.id == context.principal_id,
                )
                .values(window=window, count=count)
            )
        else:
            connection.execute(
                insert(db.rate_limits).values(
                    tenant_id=context.tenant_id,
                    id=context.principal_id,
                    window=window,
                    count=count,
                )
            )
        if "snippet" in body["attributes"]:
            body["attributes"]["snippet"] = redact(body["attributes"]["snippet"])
        accepted = service.store_event(connection, body, session["origin"], True, original_digest)
        persisted = service.required(connection, db.events, context.tenant_id, request.event_id)
        return {
            "event_id": request.event_id,
            "status": "accepted" if accepted else "duplicate",
            "received_at": persisted["received_at"],
        }


def case_detail(service: Service, context: PrincipalContext, identifier: str) -> dict[str, Any]:
    from mirage.ai import history

    context.require("analyst")
    with service.db.engine.connect() as connection:
        case = service.required(connection, db.incidents, context.tenant_id, identifier)
        events = db.rows(
            connection,
            select(db.events)
            .join(
                db.incident_events,
                and_(
                    db.events.c.tenant_id == db.incident_events.c.tenant_id,
                    db.events.c.id == db.incident_events.c.event_id,
                ),
            )
            .where(
                db.incident_events.c.tenant_id == context.tenant_id,
                db.incident_events.c.incident_id == identifier,
            )
            .order_by(db.events.c.sequence)
            .limit(500),
        )
        session = service.required(connection, db.sessions, context.tenant_id, case["session_id"])
        notes = db.rows(
            connection,
            select(db.notes)
            .where(db.notes.c.tenant_id == context.tenant_id, db.notes.c.incident_id == identifier)
            .order_by(db.notes.c.created_at)
            .limit(100),
        )
    snapshot = service.backend.snapshot(context.tenant_id)
    event_executions = {record["execution_id"] for record in snapshot["effects"]}
    # Backend effects are joined by durable execution/session records, never inferred from model text.
    with service.db.engine.connect() as connection:
        executions = db.rows(
            connection,
            select(db.executions)
            .where(
                db.executions.c.tenant_id == context.tenant_id,
                db.executions.c.session_id == session["id"],
            )
            .limit(100),
        )
    outcomes = [execution for execution in executions if execution["id"] in event_executions]
    return {
        "incident": case,
        "events": events,
        "session": session,
        "notes": notes,
        "rules": [
            dict(rule, version=RULE_VERSION) for rule in RULES if rule["id"] in case["rules"]
        ],
        "backend_outcomes": outcomes,
        "backend_evidence": snapshot,
        "investigation": case["investigation"],
        "assistant": history(service, context, case_id=identifier),
        "model_budget": {
            "limit": service.settings.model_case_call_budget,
            "used": case["model_calls"],
            "remaining": max(0, service.settings.model_case_call_budget - case["model_calls"]),
        },
        "application": "Procurement Workspace",
    }


def overview(
    service: Service, context: PrincipalContext, hours: int, origin: str
) -> dict[str, Any]:
    context.require("analyst")
    start = (
        (datetime.now(UTC) - timedelta(hours=hours))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    with service.db.engine.connect() as connection:
        event_filters = [
            db.events.c.tenant_id == context.tenant_id,
            db.events.c.received_at >= start,
        ]
        case_filters = [
            db.incidents.c.tenant_id == context.tenant_id,
            db.incidents.c.updated_at >= start,
        ]
        if origin != "all":
            event_filters.append(db.events.c.origin == origin)
            case_filters.append(db.incidents.c.origin == origin)
        event_items = db.rows(
            connection,
            select(db.events)
            .where(*event_filters)
            .order_by(db.events.c.sequence.desc())
            .limit(5000),
        )
        cases = db.rows(
            connection,
            select(db.incidents)
            .where(*case_filters)
            .order_by(db.incidents.c.updated_at.desc())
            .limit(100),
        )
        session_routes = {
            item["id"]: item
            for item in db.rows(
                connection,
                select(
                    db.sessions.c.id,
                    db.sessions.c.route_mode,
                    db.sessions.c.route_version,
                ).where(
                    db.sessions.c.tenant_id == context.tenant_id,
                    db.sessions.c.id.in_([case["session_id"] for case in cases]),
                ),
            )
        }
        for case in cases:
            route = session_routes[case["session_id"]]
            case["route_mode"] = route["route_mode"]
            case["route_version"] = route["route_version"]
        agents = connection.execute(
            select(func.count())
            .select_from(db.principals)
            .where(
                db.principals.c.tenant_id == context.tenant_id, db.principals.c.kind == "workload"
            )
        ).scalar_one()
        active_decoys = connection.execute(
            select(func.count())
            .select_from(db.decoys)
            .where(db.decoys.c.tenant_id == context.tenant_id, db.decoys.c.state == "ACTIVE")
        ).scalar_one()
        pending = connection.execute(
            select(func.count())
            .select_from(db.approvals)
            .where(
                db.approvals.c.tenant_id == context.tenant_id,
                db.approvals.c.status == "pending",
                db.approvals.c.expires_at > now(),
            )
        ).scalar_one()
        backlog = connection.execute(
            select(func.count())
            .select_from(db.outbox)
            .where(db.outbox.c.tenant_id == context.tenant_id, db.outbox.c.processed_at.is_(None))
        ).scalar_one()
        state = dict(
            connection.execute(
                select(db.runtime).where(db.runtime.c.tenant_id == context.tenant_id)
            )
            .mappings()
            .one()
        )
        policy = service.active_policy(connection, context.tenant_id)
    outcomes = Counter(
        event["outcome"] for event in event_items if event["event_type"] == "authorization.decided"
    )
    buckets: list[dict[str, Any]] = []
    current = datetime.now(UTC)
    width = max(hours / 12, 1 / 12)
    for index in range(12):
        left = current - timedelta(hours=hours) + timedelta(hours=index * width)
        right = left + timedelta(hours=width)
        subset = [
            event
            for event in event_items
            if left <= datetime.fromisoformat(event["received_at"].replace("Z", "+00:00")) < right
        ]
        buckets.append(
            {
                "label": left.strftime("%H:%M"),
                "authorized": sum(item["outcome"] == "allow" for item in subset),
                "denied": sum(item["outcome"] == "deny" for item in subset),
                "deception": sum(item["outcome"] == "simulated" for item in subset),
            }
        )
    return {
        "profile": service.settings.profile,
        "version": __version__,
        "data_scope": origin,
        "protected_applications": 1,
        "registered_agents": agents,
        "authorized_operations": outcomes["allow"],
        "denied_operations": outcomes["deny"],
        "open_incidents": sum(item["status"] != "resolved" for item in cases),
        "incident_severities": dict(
            Counter(item["severity"] for item in cases if item["status"] != "resolved")
        ),
        "active_decoys": active_decoys,
        "pending_approvals": pending,
        "decoy_failures": sum(
            item["body"]["attributes"].get("reason_code") == "DECOY_RUNTIME_FAILURE"
            for item in event_items
        ),
        "event_count": len(event_items),
        "event_count_capped": len(event_items) == 5000,
        "outbox_pending": backlog,
        "last_event_at": event_items[0]["received_at"] if event_items else None,
        "recent_events": event_items[:8],
        "recent_incidents": cases[:5],
        "trend": buckets,
        "policy_version": policy.version,
        "policy_digest": digest(policy.model_dump()),
        "model": {
            "provider": service.provider.name,
            "calls": state["model_calls"],
            "tokens": state["model_tokens"],
            "budget": service.settings.model_call_budget,
            "advisory": True,
        },
        "engagements_enabled": state["engagements_enabled"],
        "isolation": service.sandbox.attestation,
        "backend_ready": service.backend.healthy(),
        "gateway_state": "unconfigured",
        "hours": hours,
    }


def policy_change(
    service: Service,
    context: PrincipalContext,
    identifier: str,
    request: PolicyTransition,
    key: str,
) -> dict[str, Any]:
    context.require("approver" if request.action == "review" else "security_admin")
    with service.db.transaction() as connection:
        route = f"/policies/{identifier}/workflow"
        previous = service.idempotent_get(connection, context, route, key, request.model_dump())
        if previous is not None:
            return previous
        value = service.required(connection, db.policy_versions, context.tenant_id, identifier)
        if value["digest"] != request.expected_digest:
            raise DomainError(
                409, "POLICY_DIGEST_CHANGED", "Policy digest differs from reviewed content"
            )
        policy = Policy.model_validate(value["document"])
        results: list[dict[str, Any]] = []
        if request.action == "test":
            if value["status"] != "draft":
                raise DomainError(
                    409, "POLICY_IMMUTABLE", "Only draft policies can enter fixture testing"
                )
            for principal_id, tool, action, resource, arguments, expected in (
                (
                    "agent-procurement",
                    "supplier.lookup",
                    "read",
                    "supplier:demo-001",
                    {"supplier_id": "demo-001"},
                    "allow",
                ),
                (
                    "agent-procurement",
                    "payment.change_request",
                    "propose_change",
                    "supplier:demo-001",
                    {
                        "supplier_id": "demo-001",
                        "proposed_account_ref": "synthetic-account-fixture",
                    },
                    "require_approval",
                ),
                ("agent-procurement", "customer.export", "export", "customer:all", {}, "deny"),
                (
                    "agent-audit",
                    "supplier.lookup",
                    "read",
                    "supplier:demo-001",
                    {"supplier_id": "demo-001"},
                    "deny",
                ),
            ):
                principal = service.required(
                    connection, db.principals, context.tenant_id, principal_id
                )
                operation = Invocation(
                    tool=tool,
                    action=action,
                    resource=resource,
                    arguments=arguments,
                    session_id=uid(),
                )
                decision, _ = evaluate(policy, principal, operation)
                results.append(
                    {
                        "tool": tool,
                        "principal_id": principal_id,
                        "expected": expected,
                        "actual": decision,
                        "passed": expected == decision,
                    }
                )
            passed = all(item["passed"] for item in results)
            connection.execute(
                update(db.policy_versions)
                .where(
                    db.policy_versions.c.tenant_id == context.tenant_id,
                    db.policy_versions.c.id == identifier,
                )
                .values(tested=passed)
            )
            result = {**value, "tested": passed, "fixture_results": results}
        elif request.action == "review":
            if context.principal_id == value["created_by"]:
                raise DomainError(403, "SELF_REVIEW_DENIED", "A separate reviewer is required")
            if not value["tested"] or value["status"] != "draft":
                raise DomainError(
                    409, "POLICY_NOT_TESTED", "A passing draft is required before review"
                )
            connection.execute(
                update(db.policy_versions)
                .where(
                    db.policy_versions.c.tenant_id == context.tenant_id,
                    db.policy_versions.c.id == identifier,
                )
                .values(status="reviewed", reviewed_by=context.principal_id)
            )
            result = {**value, "status": "reviewed", "reviewed_by": context.principal_id}
        else:
            if value["status"] != "reviewed" or not value["tested"] or not value["reviewed_by"]:
                raise DomainError(
                    409,
                    "POLICY_NOT_REVIEWED",
                    "Only tested, separately reviewed versions can be activated",
                )
            connection.execute(
                update(db.policy_versions)
                .where(
                    db.policy_versions.c.tenant_id == context.tenant_id,
                    db.policy_versions.c.status == "active",
                )
                .values(status="reviewed")
            )
            connection.execute(
                update(db.policy_versions)
                .where(
                    db.policy_versions.c.tenant_id == context.tenant_id,
                    db.policy_versions.c.id == identifier,
                )
                .values(status="active")
            )
            connection.execute(
                update(db.runtime)
                .where(db.runtime.c.tenant_id == context.tenant_id)
                .values(
                    active_policy_id=identifier,
                )
            )
            result = {**value, "status": "active"}
        service.audit(
            connection, context, "policy." + request.action, identifier, {"digest": value["digest"]}
        )
        service.idempotent_put(connection, context, route, key, request.model_dump(), result)
        return result


def export_case(
    service: Service, context: PrincipalContext, identifier: str, format: str
) -> tuple[str, str]:
    detail = case_detail(service, context, identifier)
    detail["profile"] = service.settings.profile
    detail["provenance"] = provenance()
    detail["exported_at"] = now()
    detail["limitations"] = [
        "All application and decoy records are synthetic.",
        "Wasm capability isolation is not a Rust gateway or TCP firewall measurement.",
        "Gemini requires configured workload credentials, an approved egress/call budget and explicit live validation; fixture output is not AI inference.",
        "AI questions and answers are advisory, shared case records. Only the latest ten question requests are included.",
        "Cloud, enterprise SSO and P3 enforcement are not validated by this export.",
    ]
    with service.db.transaction() as connection:
        service.audit(connection, context, "case.exported", identifier, {"format": format})
    if format == "json":
        return json.dumps(detail, indent=2, ensure_ascii=True), "application/json"
    pretty = html.escape(json.dumps(detail, indent=2, ensure_ascii=True))
    if format == "html":
        return (
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
            "<title>Hades Mirage case export</title><style>body{font:15px system-ui;max-width:1100px;"
            "margin:40px auto;padding:20px;background:#101723;color:#dce6f4}pre{white-space:pre-wrap;"
            "overflow-wrap:anywhere}h1{color:#85d7cb}</style><h1>Hades Mirage · synthetic laboratory case</h1>"
            "<p>Recorded evidence, deterministic conclusions and advisory analysis. Not a production-readiness certificate.</p>"
            f"<pre>{pretty}</pre></html>",
            "text/html",
        )
    # A text block prevents attacker-controlled Markdown from becoming executable evidence links.
    return (
        "# Hades Mirage case export\n\nSynthetic laboratory evidence. Active profile: "
        + service.settings.profile
        + "\n\n<pre>"
        + pretty
        + "</pre>\n",
        "text/markdown",
    )
