"""Workspace AI chat and bounded automatic triage built on the advisory AI broker."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from sqlalchemy import func, insert, select

from mirage import ai, db, story
from mirage.auth import PrincipalContext
from mirage.common import DomainError, after, now, uid
from mirage.models import WorkspaceAnswer, WorkspaceQuestion

if TYPE_CHECKING:
    from mirage.service import Service

logger = logging.getLogger("mirage.assistant")


def snapshot(service: Service, context: PrincipalContext) -> dict[str, Any]:
    since = after(-24 * 3600)
    with service.db.engine.connect() as connection:
        cases = db.rows(
            connection,
            select(db.incidents)
            .where(db.incidents.c.tenant_id == context.tenant_id)
            .order_by(db.incidents.c.updated_at.desc())
            .limit(200),
        )
        sessions = {
            item["id"]: item
            for item in db.rows(
                connection,
                select(
                    db.sessions.c.id,
                    db.sessions.c.route_mode,
                    db.sessions.c.history,
                    db.sessions.c.caller_class,
                ).where(db.sessions.c.tenant_id == context.tenant_id),
            )
        }
        blocked = connection.execute(
            select(func.count())
            .select_from(db.events)
            .where(
                db.events.c.tenant_id == context.tenant_id,
                db.events.c.outcome == "deny",
                db.events.c.received_at >= since,
            )
        ).scalar_one()
        pending = connection.execute(
            select(func.count())
            .select_from(db.approvals)
            .where(
                db.approvals.c.tenant_id == context.tenant_id, db.approvals.c.status == "pending"
            )
        ).scalar_one()
    open_cases = [item for item in cases if item["status"] != "resolved"]
    honeypot = sum(
        any(entry["mode"] == "DECOY" for entry in session["history"])
        for session in sessions.values()
    )
    issues = []
    for case in open_cases[:12]:
        session = sessions.get(case["session_id"])
        route = session["route_mode"] if session else "UNKNOWN"
        first = case["rules"][0] if case["rules"] else ""
        issues.append(
            {
                "case_id": case["id"],
                "number": case["number"],
                "title": case["title"],
                "severity": case["severity"],
                "status": case["status"],
                "agent": case["principal_id"],
                "rules": case["rules"],
                "route": route,
                "story": f"{story.RULES.get(first, case['title'])}. Now: "
                f"{story.ROUTES.get(route, route)}.",
                "updated_at": case["updated_at"],
            }
        )
    return {
        "counts": {
            "open_issues": len(open_cases),
            **{
                level: sum(item["severity"] == level for item in open_cases)
                for level in ("critical", "high", "medium", "low")
            },
            "honeypot_sessions": honeypot,
            "blocked_requests": blocked,
            "pending_approvals": pending,
        },
        "issues": issues,
        "policy": "Advisory only. Deterministic rules control blocking and honeypot routing.",
    }


def chat(
    service: Service, context: PrincipalContext, body: WorkspaceQuestion, key: str
) -> dict[str, Any]:
    context.require("analyst")
    ai.apply_runtime(service)
    route, request_body = "/assistant", body.model_dump()
    ai._expire(service, context)
    data = snapshot(service, context)
    question = ai._sanitize(service, body.question)
    with service.db.transaction() as connection:
        previous = ai._previous(service, connection, context, route, key, request_body)
        if previous is not None:
            return previous
        request = ai._reserve(
            service,
            connection,
            context,
            purpose="workspace-chat",
            resource_id="workspace",
            route=route,
            key=key,
            body=request_body,
            payload={**data, "question": question},
            active=service.provider,
            question=question,
        )
    tokens = None
    try:
        output, reported = service.provider.chat(data, question)
        tokens = ai._usage(reported)
        validated = (
            WorkspaceAnswer.model_validate_json(output)
            if isinstance(output, str)
            else WorkspaceAnswer.model_validate(output)
        )
        validated.verify({item["case_id"] for item in data["issues"]})
        return ai._complete(
            service,
            context,
            request,
            validated.model_dump(),
            tokens,
            {
                "coverage": {
                    "issues_supplied": len(data["issues"]),
                    "conversation_memory": False,
                    "scope": "Bounded workspace summary; ask inside an issue for cited evidence",
                }
            },
        )
    except (ValidationError, ValueError, TypeError, DomainError) as error:
        raise ai._reject(service, context, request, error, tokens) from error


def history(service: Service, context: PrincipalContext) -> list[dict[str, Any]]:
    context.require("analyst")
    with service.db.engine.connect() as connection:
        items = db.rows(
            connection,
            select(db.ai_requests)
            .where(
                db.ai_requests.c.tenant_id == context.tenant_id,
                db.ai_requests.c.principal_id == context.principal_id,
                db.ai_requests.c.purpose == "workspace-chat",
            )
            .order_by(db.ai_requests.c.started_at.desc())
            .limit(20),
        )
    return [ai.public_request(item) for item in items]


def automation_context(service: Service, tenant: str) -> PrincipalContext:
    with service.db.transaction() as connection:
        if db.row(connection, db.principals, tenant, ai.AUTOMATION_PRINCIPAL) is None:
            connection.execute(
                insert(db.principals).values(
                    tenant_id=tenant,
                    id=ai.AUTOMATION_PRINCIPAL,
                    name="AI auto-triage",
                    kind="service",
                    roles=["analyst"],
                    status="active",
                    scopes=[],
                    parent_id=None,
                    root_id=ai.AUTOMATION_PRINCIPAL,
                    depth=0,
                    expires_at=after(365 * 86400),
                    identity_epoch=1,
                    owner="Security administrator (portal setting)",
                    created_at=now(),
                )
            )
    return PrincipalContext(tenant, ai.AUTOMATION_PRINCIPAL, ("analyst",), "service")


def auto_triage_tick(service: Service, limit: int = 2) -> int:
    """Explain new issues automatically when an administrator enabled it. Never routes traffic."""
    row = ai.apply_runtime(service)
    if not row or not row["auto_triage"] or not row["auto_triage_since"]:
        return 0
    if row["provider"] == "unavailable" or (
        row["provider"] == "gemini" and not row["egress_approved"]
    ):
        return 0
    skipped: set[str] = service.__dict__.setdefault("_auto_triage_skipped", set())
    with service.db.engine.connect() as connection:
        cases = db.rows(
            connection,
            select(db.incidents.c.tenant_id, db.incidents.c.id, db.incidents.c.investigation)
            .where(
                db.incidents.c.created_at >= row["auto_triage_since"],
                db.incidents.c.model_calls == 0,
                db.incidents.c.status != "resolved",
            )
            .order_by(db.incidents.c.created_at)
            .limit(20 + len(skipped)),
        )
    completed = 0
    pending = [item for item in cases if item["investigation"] is None]
    for case in [item for item in pending if item["id"] not in skipped][:limit]:
        try:
            ai.case_analysis(
                service,
                automation_context(service, case["tenant_id"]),
                case["id"],
                key=f"auto-triage-{case['id']}",
            )
            completed += 1
        except DomainError as error:
            skipped.add(case["id"])
            logger.warning("Auto-triage skipped: code=%s", error.code)
    return completed


def new_key() -> str:
    return uid()
