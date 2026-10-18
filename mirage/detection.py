from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection

from mirage import db, deception
from mirage.common import now, uid

if TYPE_CHECKING:
    from mirage.service import Service

RULE_VERSION = "rules-1.0.0"
RULES = [
    {
        "id": "D-001",
        "name": "Distinct-resource access denials",
        "threshold": "5 distinct resources / 60s",
        "response": "restrict",
        "severity": "medium",
    },
    {
        "id": "D-002",
        "name": "Corroborated resource probing",
        "threshold": "Prohibited tool + 3 denied lookups / 60s",
        "response": "eligible deception",
        "severity": "high",
    },
    {
        "id": "D-003",
        "name": "Approval verification failure",
        "threshold": "1 invalid action-bound approval",
        "response": "review",
        "severity": "medium",
    },
    {
        "id": "D-004",
        "name": "Delegation escalation",
        "threshold": "1 attempt exceeding ancestor authority",
        "response": "review",
        "severity": "medium",
    },
    {
        "id": "D-005",
        "name": "Verified decoy interaction",
        "threshold": "1 observation from the isolated template",
        "response": "observe",
        "severity": "medium",
    },
    {
        "id": "D-006",
        "name": "Instruction override with prohibited tool",
        "threshold": "Injection-like text + prohibited action / 60s",
        "response": "eligible deception",
        "severity": "high",
    },
]


def matches(events: list[dict[str, Any]]) -> set[str]:
    output: set[str] = set()
    application_decisions = [
        item
        for item in events
        if item["source"] in {"edge", "dispatcher"}
        and item["event_type"] == "authorization.decided"
    ]
    denials = [item for item in application_decisions if item["outcome"] == "deny"]
    resources = {item["body"]["attributes"].get("resource") for item in denials}
    resources.discard(None)
    prohibited = any(
        item["body"]["attributes"].get("tool") in {"customer.export", "infrastructure.delete"}
        for item in denials
    )
    enumerations = {
        item["body"]["attributes"].get("resource")
        for item in denials
        if item["body"]["attributes"].get("tool") in {"supplier.lookup", "invoice.compare"}
    }
    enumerations.discard(None)
    reasons = {item["body"]["attributes"].get("reason_code") for item in application_decisions}
    snippets = " ".join(
        item["body"]["attributes"].get("snippet", "")
        for item in events
        if item["source"] in {"edge", "dispatcher"}
    ).lower()
    injection = any(
        marker in snippets
        for marker in (
            "ignore policy",
            "ignore previous",
            "system prompt",
            "override instructions",
        )
    )
    if len(resources) >= 5:
        output.add("D-001")
    if prohibited and len(enumerations) >= 3:
        output.add("D-002")
    if "APPROVAL_VERIFICATION_FAILED" in reasons:
        output.add("D-003")
    if "DELEGATION_ESCALATION" in reasons:
        output.add("D-004")
    if any(
        item["event_type"] == "decoy.observed"
        and item["source"] == "decoy_router"
        and item["body"]["attributes"].get("reason_code") == "VERIFIED_SYNTHETIC_INTERACTION"
        for item in events
    ):
        output.add("D-005")
    if injection and prohibited:
        output.add("D-006")
    return output


def correlate(service: Service, connection: Connection, event: dict[str, Any]) -> None:
    if not event["trusted"]:
        return
    start = (
        (
            datetime.fromisoformat(event["received_at"].replace("Z", "+00:00"))
            - timedelta(seconds=60)
        )
        .astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    recent = db.rows(
        connection,
        select(db.events)
        .where(
            db.events.c.tenant_id == event["tenant_id"],
            db.events.c.session_id == event["session_id"],
            db.events.c.received_at >= start,
            db.events.c.received_at <= event["received_at"],
            db.events.c.trusted.is_(True),
        )
        .order_by(db.events.c.sequence)
        .limit(100),
    )
    found = matches(recent)
    existing = (
        connection.execute(
            select(db.incidents).where(
                db.incidents.c.tenant_id == event["tenant_id"],
                db.incidents.c.session_id == event["session_id"],
            )
        )
        .mappings()
        .first()
    )
    if not found and existing is None:
        return
    session = service.required(connection, db.sessions, event["tenant_id"], event["session_id"])
    rules = sorted(found | (set(existing["rules"]) if existing else set()))
    primary = next(
        (item for item in ("D-002", "D-006", "D-004", "D-003", "D-001", "D-005") if item in rules),
        "D-001",
    )
    rule = next(item for item in RULES if item["id"] == primary)
    identifier = existing["id"] if existing else uid()
    evidence = {item["id"] for item in recent}
    already = (
        set(
            connection.execute(
                select(db.incident_events.c.event_id).where(
                    db.incident_events.c.tenant_id == event["tenant_id"],
                    db.incident_events.c.incident_id == identifier,
                )
            ).scalars()
        )
        if existing
        else set()
    )
    new_evidence = evidence - already
    if not new_evidence and existing and existing["rules"] == rules:
        return
    if existing is None:
        number = db.next_sequence(connection, event["tenant_id"], "incidents")
        connection.execute(
            insert(db.incidents).values(
                tenant_id=event["tenant_id"],
                id=identifier,
                number=f"HM-{number:04d}",
                session_id=session["id"],
                principal_id=session["principal_id"],
                title=rule["name"],
                summary="Deterministic rules matched a bounded sequence. Prohibited operations were denied; "
                "the rule is not proof of malicious intent or production compromise.",
                severity=rule["severity"],
                confidence="high" if primary in {"D-002", "D-005"} else "medium",
                status="open",
                version=1,
                rules=rules,
                source=event["source"],
                origin=session["origin"],
                investigation=None,
                model_error=None,
                model_calls=0,
                created_at=now(),
                updated_at=now(),
            )
        )
    else:
        connection.execute(
            update(db.incidents)
            .where(db.incidents.c.tenant_id == event["tenant_id"], db.incidents.c.id == identifier)
            .values(
                version=existing["version"] + 1,
                rules=rules,
                severity=rule["severity"],
                title=rule["name"],
                updated_at=now(),
                investigation=None,
            )
        )
    for event_id in new_evidence:
        connection.execute(
            insert(db.incident_events).values(
                tenant_id=event["tenant_id"],
                incident_id=identifier,
                event_id=event_id,
            )
        )
    context = deception.controller(event["tenant_id"])
    if found.intersection({"D-001", "D-002", "D-006"}):
        session = deception.restrict(
            service, connection, context, session, primary + ":" + RULE_VERSION
        )
    if found.intersection({"D-002", "D-006"}):
        deception.engage(service, connection, context, session)


def drain(service: Service, limit: int = 200) -> int:
    processed = 0
    for _ in range(limit):
        with service.db.transaction() as connection:
            item = (
                connection.execute(
                    select(db.outbox)
                    .where(db.outbox.c.processed_at.is_(None))
                    .order_by(db.outbox.c.created_at)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if item is None:
                break
            event = service.required(connection, db.events, item["tenant_id"], item["event_id"])
            correlate(service, connection, event)
            connection.execute(
                update(db.outbox)
                .where(db.outbox.c.tenant_id == item["tenant_id"], db.outbox.c.id == item["id"])
                .values(processed_at=now())
            )
            processed += 1
    return processed
