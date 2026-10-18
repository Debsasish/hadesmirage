from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, exists, select

from mirage import db, deception
from mirage.common import after, now

if TYPE_CHECKING:
    from mirage.service import Service


def prune(service: Service) -> dict[str, int]:
    """Retain case evidence; age out only unreferenced, processed metadata."""
    cutoff = after(-service.settings.event_retention_days * 86400)
    counts = {"events": 0, "expired_browser_credentials": 0}
    with service.db.transaction() as connection:
        candidates = db.rows(
            connection,
            select(db.events.c.tenant_id, db.events.c.id)
            .where(
                db.events.c.received_at < cutoff,
                ~exists(
                    select(db.incident_events.c.event_id).where(
                        db.incident_events.c.tenant_id == db.events.c.tenant_id,
                        db.incident_events.c.event_id == db.events.c.id,
                    )
                ),
                ~exists(
                    select(db.outbox.c.event_id).where(
                        db.outbox.c.tenant_id == db.events.c.tenant_id,
                        db.outbox.c.event_id == db.events.c.id,
                        db.outbox.c.processed_at.is_(None),
                    )
                ),
            )
            .limit(500),
        )
        per_tenant: dict[str, int] = {}
        for candidate in candidates:
            tenant, identifier = candidate["tenant_id"], candidate["id"]
            connection.execute(
                delete(db.outbox).where(
                    db.outbox.c.tenant_id == tenant,
                    db.outbox.c.event_id == identifier,
                )
            )
            connection.execute(
                delete(db.events).where(
                    db.events.c.tenant_id == tenant,
                    db.events.c.id == identifier,
                )
            )
            counts["events"] += 1
            per_tenant[tenant] = per_tenant.get(tenant, 0) + 1
        removed = connection.execute(
            delete(db.credentials).where(
                db.credentials.c.kind == "browser",
                db.credentials.c.expires_at < now(),
            )
        )
        counts["expired_browser_credentials"] = removed.rowcount
        for tenant, count in per_tenant.items():
            service.audit(
                connection,
                deception.controller(tenant),
                "retention.metadata_pruned",
                tenant,
                {
                    "events": count,
                    "retention_days": service.settings.event_retention_days,
                    "case_evidence_retained": True,
                },
            )
    return counts
