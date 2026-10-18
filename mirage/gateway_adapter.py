"""Narrow structured gateway observation adapter; no registry writes or permission signing."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, field_validator

from mirage import db
from mirage.auth import PrincipalContext
from mirage.common import DomainError, digest
from mirage.control import ingest
from mirage.models import EventInput, StrictModel

if TYPE_CHECKING:
    from mirage.service import Service


class GatewayFields(StrictModel):
    source_identity: str = Field(min_length=1, max_length=200)
    dest_authority: str = Field(min_length=1, max_length=200)
    policy_decision: Literal["allow", "deny"]
    deny_reason: str | None = Field(default=None, max_length=500)


class GatewayObservation(StrictModel):
    timestamp: str
    target: Literal["agent_gateway::proxy"]
    fields: GatewayFields
    session_id: str

    @field_validator("timestamp")
    @classmethod
    def timestamp_has_timezone(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Timezone is required")
        return value


def accept(
    service: Service, context: PrincipalContext, record: GatewayObservation
) -> dict[str, str]:
    context.require("event_producer")
    if context.source != "gateway":
        raise DomainError(
            403,
            "GATEWAY_PRODUCER_REQUIRED",
            "Only a source-bound gateway producer can submit this record",
        )
    with service.db.engine.connect() as connection:
        session = service.required(connection, db.sessions, context.tenant_id, record.session_id)
    if session["principal_id"] != record.fields.source_identity:
        raise DomainError(
            422,
            "GATEWAY_IDENTITY_MISMATCH",
            "Gateway observation differs from the bound session identity",
        )
    identifier = str(
        uuid5(NAMESPACE_URL, f"mirage-gateway:{context.tenant_id}:{digest(record.model_dump())}")
    )
    record_digest = digest(record.model_dump())
    with service.db.engine.connect() as connection:
        existing = db.row(connection, db.events, context.tenant_id, identifier)
        if existing is not None and existing["body"].get("trace_id") == record_digest:
            return {
                "event_id": identifier,
                "status": "duplicate",
                "received_at": existing["received_at"],
            }
    return ingest(
        service,
        context,
        EventInput(
            event_id=identifier,
            tenant_id=context.tenant_id,
            session_id=record.session_id,
            source="gateway",
            event_type="gateway.decided",
            occurred_at=record.timestamp,
            route_mode=session["route_mode"],
            outcome=record.fields.policy_decision,
            principal_id=record.fields.source_identity,
            trace_id=record_digest,
            attributes={
                "destination": record.fields.dest_authority,
                "reason_code": "GATEWAY_" + record.fields.policy_decision.upper(),
                "snippet": record.fields.deny_reason or "Structured gateway observation",
            },
        ),
    )
