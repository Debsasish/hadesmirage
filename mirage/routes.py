from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import case as sql_case
from sqlalchemy import delete, func, insert, or_, select, update

from mirage import (
    ai,
    assistant,
    attack_map,
    control,
    db,
    deception,
    integrations,
    laboratory,
    providers,
    story,
)
from mirage.api import Context, Key
from mirage.common import DomainError, digest, now, uid
from mirage.detection import RULE_VERSION, RULES
from mirage.gateway_adapter import GatewayObservation
from mirage.gateway_adapter import accept as accept_gateway_observation
from mirage.models import (
    AIConfigUpdate,
    CaseQuestion,
    EventInput,
    HadesReport,
    IdentityStatus,
    IncidentUpdate,
    KillSwitchRequest,
    NoteRequest,
    Policy,
    PolicyTransition,
    PortalRequest,
    ProviderCheckRequest,
    PurgeCaseRequest,
    ReportSummaryRequest,
    ScenarioRequest,
    SettingsUpdate,
    Transition,
    WorkspaceQuestion,
)
from mirage.service import Service


def offset_from(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        result = int(base64.urlsafe_b64decode(cursor.encode()).decode())
        if not 0 <= result <= 100000:
            raise ValueError("Out of bounds")
        return result
    except (ValueError, UnicodeError) as error:
        raise DomainError(400, "INVALID_CURSOR", "Invalid pagination cursor") from error


def page(items: list[dict[str, Any]], limit: int, offset: int) -> dict[str, Any]:
    return {
        "items": items[:limit],
        "next_cursor": base64.urlsafe_b64encode(str(offset + limit).encode()).decode()
        if len(items) > limit
        else None,
    }


def register_routes(app: FastAPI, service: Service) -> None:
    database, settings = service.db, service.settings

    @app.get("/v1/detection/rules")
    def detection_rules(context: Context) -> dict[str, Any]:
        context.require("analyst")
        return {"items": RULES, "version": RULE_VERSION}

    @app.get("/v1/ai")
    def ai_status(context: Context) -> dict[str, Any]:
        return ai.status(service, context)

    @app.post("/v1/ai/check")
    def ai_check(body: ProviderCheckRequest, context: Context, key: Key) -> dict[str, Any]:
        return ai.check_provider(service, context, body.allow_live, key)

    @app.put("/v1/ai/config")
    def ai_config(body: AIConfigUpdate, context: Context, key: Key) -> dict[str, Any]:
        ai.update_runtime(service, context, body, key)
        return ai.status(service, context)

    @app.get("/v1/ai/models")
    def ai_models(context: Context) -> dict[str, Any]:
        return ai.discover_models(service, context)

    @app.get("/v1/assistant")
    def assistant_history(context: Context) -> dict[str, Any]:
        return {"items": assistant.history(service, context)}

    @app.post("/v1/assistant")
    def assistant_chat(body: WorkspaceQuestion, context: Context, key: Key) -> dict[str, Any]:
        return assistant.chat(service, context, body, key)

    @app.get("/v1/incidents/{incident_id}/attack-path")
    def attack_path(incident_id: str, context: Context) -> dict[str, Any]:
        service.drain_outbox()
        return story.build(control.case_detail(service, context, incident_id))

    @app.get("/v1/attack-map")
    def live_attack_map(
        context: Context,
        hours: Annotated[int, Query(ge=1, le=720)] = 168,
        origin: Literal["all", "live", "laboratory"] = "all",
    ) -> dict[str, Any]:
        context.require("analyst")
        if hours not in attack_map.WINDOWS:
            raise DomainError(400, "INVALID_TIME_RANGE", "Choose 1, 24, 168 or 720 hours")
        service.drain_outbox()
        return attack_map.build(service, context, hours, origin)

    @app.get("/v1/board")
    def board(context: Context) -> dict[str, Any]:
        context.require("analyst")
        current = datetime.now(UTC)
        with database.engine.connect() as connection:
            cases = db.rows(
                connection,
                select(db.incidents)
                .where(db.incidents.c.tenant_id == context.tenant_id)
                .order_by(db.incidents.c.created_at.desc())
                .limit(2000),
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

        def parsed(value: str) -> datetime:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))

        levels = ("critical", "high", "medium", "low")
        open_cases = [item for item in cases if item["status"] != "resolved"]
        week, previous_week = current - timedelta(days=7), current - timedelta(days=14)
        severity = []
        for level in levels:
            recent = sum(
                item["severity"] == level and parsed(item["created_at"]) >= week for item in cases
            )
            before = sum(
                item["severity"] == level and previous_week <= parsed(item["created_at"]) < week
                for item in cases
            )
            ages = [
                (current - parsed(item["created_at"])).total_seconds() / 86400
                for item in open_cases
                if item["severity"] == level
            ]
            severity.append(
                {
                    "level": level,
                    "open": sum(item["severity"] == level for item in open_cases),
                    "opened_7d": recent,
                    "change_percent": None
                    if before == 0
                    else round((recent - before) * 100 / before),
                    "average_age_days": round(sum(ages) / len(ages), 2) if ages else None,
                    "target_days": {"critical": 1, "high": 3, "medium": 7, "low": 30}[level],
                }
            )
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for item in open_cases:
            session = sessions.get(item["session_id"]) or {"history": [], "route_mode": ""}
            group = groups.setdefault(
                (item["title"], item["severity"]),
                {
                    "title": item["title"],
                    "plain": story.RULES.get(item["rules"][0], item["title"])
                    if item["rules"]
                    else item["title"],
                    "severity": item["severity"],
                    "rules": item["rules"],
                    "count": 0,
                    "honeypot": 0,
                    "ai_reviewed": 0,
                    "external": 0,
                    "latest_id": item["id"],
                    "latest_number": item["number"],
                },
            )
            group["count"] += 1
            group["honeypot"] += any(entry["mode"] == "DECOY" for entry in session["history"])
            group["ai_reviewed"] += item["investigation"] is not None
            group["external"] += session.get("caller_class") == "external"
        order = {level: index for index, level in enumerate(levels)}
        top = sorted(groups.values(), key=lambda item: (order[item["severity"]], -item["count"]))
        trend = []
        for offset in range(29, -1, -1):
            day = (current - timedelta(days=offset)).date()
            trend.append(
                {
                    "day": day.isoformat(),
                    "opened": sum(parsed(item["created_at"]).date() == day for item in cases),
                    "resolved": sum(
                        item["status"] == "resolved" and parsed(item["updated_at"]).date() == day
                        for item in cases
                    ),
                }
            )
        detected = {item["session_id"] for item in cases}
        attacked = [
            sessions[identifier]
            for identifier in detected
            if identifier in sessions and sessions[identifier]["caller_class"] == "external"
        ]
        contained = [
            item
            for item in attacked
            if any(
                entry["mode"] in {"RESTRICTED", "DECOY", "TERMINATED"} for entry in item["history"]
            )
        ]
        honeypot = [
            item for item in attacked if any(entry["mode"] == "DECOY" for entry in item["history"])
        ]
        evidence = service.backend.snapshot(context.tenant_id)
        reviewed = sum(item["investigation"] is not None for item in open_cases)
        return {
            "generated_at": now(),
            "severity": severity,
            "top_issues": top[:12],
            "trend": trend,
            "containment": {
                "external_attack_sessions": len(attacked),
                "contained": len(contained),
                "honeypot": len(honeypot),
                "rate": round(len(contained) * 100 / len(attacked)) if attacked else None,
                "real_data_changes": evidence["production_mutations"],
                "definition": "External sessions with a detection that were limited, moved to the "
                "honeypot or disconnected. Not a general prevention score.",
            },
            "ai_coverage": {
                "open_issues": len(open_cases),
                "ai_reviewed": reviewed,
                "rate": round(reviewed * 100 / len(open_cases)) if open_cases else None,
            },
        }

    @app.get("/v1/overview")
    def overview(
        context: Context,
        hours: Annotated[int, Query(ge=1, le=168)] = 24,
        origin: Literal["all", "live", "laboratory"] = "all",
    ) -> dict[str, Any]:
        if hours not in {1, 24, 168}:
            raise DomainError(400, "INVALID_TIME_RANGE", "Choose 1, 24 or 168 hours")
        service.drain_outbox()
        deception.sweep(service)
        return control.overview(service, context, hours, origin)

    @app.post("/v1/events", status_code=202)
    def ingest(body: EventInput, context: Context) -> dict[str, Any]:
        result = control.ingest(service, context, body)
        service.drain_outbox()
        return result

    @app.get("/v1/events")
    def events(
        context: Context,
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        session_id: str | None = None,
        principal_id: str | None = None,
        outcome: str | None = None,
        source: str | None = None,
        q: Annotated[str, Query(max_length=100)] = "",
        origin: Literal["all", "live", "laboratory"] = "all",
    ) -> dict[str, Any]:
        context.require("analyst")
        offset = offset_from(cursor)
        query = select(db.events).where(db.events.c.tenant_id == context.tenant_id)
        for column, value in (
            (db.events.c.session_id, session_id),
            (db.events.c.source, source),
            (db.events.c.outcome, outcome),
        ):
            if value:
                query = query.where(column == value)
        if principal_id:
            query = query.join(
                db.sessions,
                (db.events.c.tenant_id == db.sessions.c.tenant_id)
                & (db.events.c.session_id == db.sessions.c.id),
            ).where(db.sessions.c.principal_id == principal_id)
        if origin != "all":
            query = query.where(db.events.c.origin == origin)
        if q:
            query = query.where(
                or_(
                    db.events.c.id.contains(q, autoescape=True),
                    db.events.c.event_type.contains(q, autoescape=True),
                )
            )
        with database.engine.connect() as connection:
            items = db.rows(
                connection,
                query.order_by(db.events.c.sequence.desc()).offset(offset).limit(limit + 1),
            )
        return page(items, limit, offset)

    @app.get("/v1/incidents")
    def incidents(
        context: Context,
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        q: Annotated[str, Query(max_length=100)] = "",
        severity: str | None = None,
        confidence: str | None = None,
        status: str | None = None,
        source: str | None = None,
        response: str | None = None,
        origin: Literal["all", "live", "laboratory"] = "all",
        sort: Literal["updated", "oldest", "severity"] = "updated",
        application: Literal["procurement"] | None = None,
    ) -> dict[str, Any]:
        context.require("analyst")
        offset = offset_from(cursor)
        query = select(db.incidents).where(db.incidents.c.tenant_id == context.tenant_id)
        for column, value in (
            (db.incidents.c.severity, severity),
            (db.incidents.c.confidence, confidence),
            (db.incidents.c.status, status),
            (db.incidents.c.source, source),
        ):
            if value:
                query = query.where(column == value)
        if origin != "all":
            query = query.where(db.incidents.c.origin == origin)
        if q:
            query = query.where(
                or_(
                    db.incidents.c.title.icontains(q, autoescape=True),
                    db.incidents.c.number.icontains(q, autoescape=True),
                    db.incidents.c.principal_id.icontains(q, autoescape=True),
                )
            )
        query = query.join(
            db.sessions,
            (db.incidents.c.tenant_id == db.sessions.c.tenant_id)
            & (db.incidents.c.session_id == db.sessions.c.id),
        ).add_columns(
            db.sessions.c.route_mode,
            db.sessions.c.route_version,
        )
        if response:
            query = query.where(db.sessions.c.route_mode == response)
        ordering = (
            db.incidents.c.created_at.asc()
            if sort == "oldest"
            else db.incidents.c.updated_at.desc()
        )
        if sort == "severity":
            query = query.order_by(
                sql_case(
                    (db.incidents.c.severity == "critical", 0),
                    (db.incidents.c.severity == "high", 1),
                    (db.incidents.c.severity == "medium", 2),
                    else_=3,
                )
            )
        with database.engine.connect() as connection:
            items = db.rows(connection, query.order_by(ordering).offset(offset).limit(limit + 1))
        return page(items, limit, offset)

    @app.get("/v1/incidents/{incident_id}")
    def incident(incident_id: str, context: Context) -> dict[str, Any]:
        service.drain_outbox()
        return control.case_detail(service, context, incident_id)

    @app.post("/v1/incidents/{incident_id}/investigate")
    def investigate(incident_id: str, context: Context, key: Key) -> dict[str, Any]:
        return providers.investigate(service, context, incident_id, key=key)

    @app.get("/v1/incidents/{incident_id}/assistant")
    def case_questions(incident_id: str, context: Context) -> dict[str, Any]:
        return {
            "items": ai.history(service, context, case_id=incident_id),
            "case_call_budget": settings.model_case_call_budget,
        }

    @app.post("/v1/incidents/{incident_id}/assistant")
    def ask_case(
        incident_id: str, body: CaseQuestion, context: Context, key: Key
    ) -> dict[str, Any]:
        return ai.case_analysis(service, context, incident_id, question=body, key=key)

    @app.post("/v1/incidents/{incident_id}/purge")
    def purge_case(
        incident_id: str, body: PurgeCaseRequest, context: Context, key: Key
    ) -> dict[str, Any]:
        context.require("security_admin")
        if settings.profile != "P1-native":
            raise DomainError(
                403, "LABORATORY_ONLY", "Synthetic case purge is available only in P1-native"
            )
        with database.transaction() as connection:
            route = f"/incidents/{incident_id}/purge"
            previous = service.idempotent_get(connection, context, route, key, body.model_dump())
            if previous is not None:
                return previous
            case = service.required(connection, db.incidents, context.tenant_id, incident_id)
            session = service.required(
                connection, db.sessions, context.tenant_id, case["session_id"]
            )
            exported = connection.execute(
                select(db.audit_log.c.id)
                .where(
                    db.audit_log.c.tenant_id == context.tenant_id,
                    db.audit_log.c.object_id == incident_id,
                    db.audit_log.c.action == "case.exported",
                )
                .limit(1)
            ).first()
            if (
                body.confirmation != f"PURGE SYNTHETIC CASE {case['number']}"
                or body.expected_version != case["version"]
            ):
                raise DomainError(
                    409,
                    "PURGE_CONFIRMATION_MISMATCH",
                    "Confirm the exact case number and current version",
                )
            if (
                case["status"] != "resolved"
                or session["route_mode"] != "TERMINATED"
                or not exported
            ):
                raise DomainError(
                    409,
                    "CASE_NOT_PURGEABLE",
                    "Terminate the session, resolve and export this case before purging",
                )
            pending_ai = connection.execute(
                select(db.ai_requests.c.id)
                .where(
                    db.ai_requests.c.tenant_id == context.tenant_id,
                    db.ai_requests.c.incident_id == incident_id,
                    db.ai_requests.c.state == "pending",
                    db.ai_requests.c.deadline_at > now(),
                )
                .limit(1)
            ).first()
            if pending_ai:
                raise DomainError(
                    409, "CASE_AI_REQUEST_PENDING", "Wait for the bounded AI request before purging"
                )
            case_route = f"/incidents/{incident_id}"
            connection.execute(
                delete(db.idempotency).where(
                    db.idempotency.c.tenant_id == context.tenant_id,
                    or_(
                        db.idempotency.c.route == case_route,
                        db.idempotency.c.route.startswith(case_route + "/", autoescape=True),
                    ),
                    db.idempotency.c.route != route,
                )
            )
            for table in (db.notes, db.incident_events):
                connection.execute(
                    delete(table).where(
                        table.c.tenant_id == context.tenant_id,
                        table.c.incident_id == incident_id,
                    )
                )
            connection.execute(
                delete(db.incidents).where(
                    db.incidents.c.tenant_id == context.tenant_id,
                    db.incidents.c.id == incident_id,
                )
            )
            service.audit(
                connection,
                context,
                "case.purged",
                incident_id,
                {
                    "number": case["number"],
                    "route_preserved": "TERMINATED",
                    "backend_ledger_preserved": True,
                },
            )
            result = {
                "purged": incident_id,
                "route_mode": "TERMINATED",
                "backend_ledger_preserved": True,
            }
            service.idempotent_put(connection, context, route, key, body.model_dump(), result)
            return result

    @app.post("/v1/incidents/{incident_id}/notes", status_code=201)
    def note(incident_id: str, body: NoteRequest, context: Context, key: Key) -> dict[str, Any]:
        context.require("analyst")
        with database.transaction() as connection:
            service.required(connection, db.incidents, context.tenant_id, incident_id)
            route = f"/incidents/{incident_id}/notes"
            previous = service.idempotent_get(connection, context, route, key, body.model_dump())
            if previous is not None:
                return previous
            value = {
                "tenant_id": context.tenant_id,
                "id": uid(),
                "incident_id": incident_id,
                "actor_id": context.principal_id,
                "text": body.text,
                "created_at": now(),
            }
            connection.execute(insert(db.notes).values(**value))
            service.audit(
                connection, context, "case.note_added", incident_id, {"note_id": value["id"]}
            )
            service.idempotent_put(connection, context, route, key, body.model_dump(), value)
            return value

    @app.patch("/v1/incidents/{incident_id}")
    def update_incident(
        incident_id: str, body: IncidentUpdate, context: Context, key: Key
    ) -> dict[str, Any]:
        context.require("analyst")
        with database.transaction() as connection:
            route = f"/incidents/{incident_id}"
            previous = service.idempotent_get(connection, context, route, key, body.model_dump())
            if previous is not None:
                return previous
            case = service.required(connection, db.incidents, context.tenant_id, incident_id)
            if case["version"] != body.expected_version:
                raise DomainError(
                    409, "CASE_VERSION_CHANGED", "Case changed; refresh before updating it"
                )
            values = {
                "status": body.status,
                "version": case["version"] + 1,
                "updated_at": now(),
                "investigation": None,
            }
            connection.execute(
                update(db.incidents)
                .where(
                    db.incidents.c.tenant_id == context.tenant_id,
                    db.incidents.c.id == incident_id,
                )
                .values(**values)
            )
            service.audit(
                connection, context, "case.status_changed", incident_id, {"status": body.status}
            )
            result = {**case, **values}
            service.idempotent_put(connection, context, route, key, body.model_dump(), result)
            return result

    @app.get("/v1/incidents/{incident_id}/export")
    def export(
        incident_id: str, context: Context, format: Literal["json", "html", "md"] = "json"
    ) -> Response:
        output, media = control.export_case(service, context, incident_id, format)
        return Response(
            output,
            media_type=media,
            headers={
                "Content-Disposition": f'attachment; filename="mirage-case-{incident_id}.{format}"',
            },
        )

    @app.get("/v1/sessions")
    def sessions(context: Context) -> dict[str, Any]:
        context.require("analyst")
        deception.sweep(service)
        with database.engine.connect() as connection:
            items = db.rows(
                connection,
                select(db.sessions)
                .where(db.sessions.c.tenant_id == context.tenant_id)
                .order_by(db.sessions.c.created_at.desc())
                .limit(100),
            )
        return {"items": items}

    @app.get("/v1/sessions/{session_id}")
    def session_detail(session_id: str, context: Context) -> dict[str, Any]:
        with database.engine.connect() as connection:
            if "analyst" in context.roles:
                return service.required(connection, db.sessions, context.tenant_id, session_id)
            return service.owned_session(connection, context, session_id)

    @app.post("/v1/sessions/{session_id}/{action}")
    def response_action(
        session_id: str,
        action: Literal["restrict", "engage", "terminate"],
        body: Transition,
        context: Context,
        key: Key,
    ) -> dict[str, Any]:
        result = deception.transition(service, context, session_id, action, body, key)
        service.drain_outbox()
        return result

    @app.post("/v1/portal/request")
    def portal(body: PortalRequest, context: Context, key: Key) -> JSONResponse:
        status, result = deception.portal(service, context, body, key)
        service.drain_outbox()
        result = providers.with_wording(service, context, body.session_id, result, key)
        return JSONResponse(status_code=status, content=result)

    @app.get("/v1/deception")
    def decoys(context: Context) -> dict[str, Any]:
        context.require("analyst")
        deception.sweep(service)
        with database.engine.connect() as connection:
            items = db.rows(
                connection,
                select(db.decoys)
                .where(db.decoys.c.tenant_id == context.tenant_id)
                .order_by(db.decoys.c.created_at.desc())
                .limit(100),
            )
            state = (
                connection.execute(
                    select(db.runtime).where(db.runtime.c.tenant_id == context.tenant_id)
                )
                .mappings()
                .one()
            )
        return {
            "items": items,
            "engagements_enabled": state["engagements_enabled"],
            "templates": [
                {
                    "id": deception.TEMPLATE_ID,
                    "version": deception.TEMPLATE_VERSION,
                    "name": "Supplier portal",
                    "runtime": "Wasmtime · no host imports",
                    "ready": service.sandbox.available(),
                    "isolation": service.sandbox.attestation,
                    "description": "Low-interaction supplier and invoice simulation. Synthetic state only.",
                    "tools": [
                        "supplier.lookup",
                        "invoice.compare",
                        "simulated administrative response",
                    ],
                }
            ],
            "budgets": {
                "requests": settings.decoy_request_budget,
                "ttl_seconds": settings.session_ttl_seconds,
                "concurrent": settings.max_engagements,
                "model_tokens_per_session": 8000,
                "wording_budget_units_per_session": 8000,
                "wording_budget_definition": "Conservative admission units: UTF-8 context/system bytes, output cap, any reserved model-reasoning tokens and protocol allowance; not billed tokens",
                "model_wording_enabled": settings.decoy_model_wording,
            },
        }

    @app.post("/v1/deception/verify")
    def verify_isolation(context: Context, key: Key) -> dict[str, Any]:
        context.require("security_admin")
        service.sandbox.attestation = service.sandbox.verify()
        service.sandbox.ready = service.sandbox.attestation["verified"]
        with database.transaction() as connection:
            service.audit(
                connection,
                context,
                "isolation.verified",
                deception.TEMPLATE_ID,
                {
                    "module_digest": service.sandbox.module_digest,
                    "verified": service.sandbox.ready,
                },
            )
        return service.sandbox.attestation

    @app.post("/v1/deception/kill-switch")
    def kill_switch(body: KillSwitchRequest, context: Context, key: Key) -> dict[str, Any]:
        result = deception.kill_switch(service, context, key)
        service.drain_outbox()
        return result

    @app.get("/v1/agents/{principal_id}")
    def agent_detail(principal_id: str, context: Context) -> dict[str, Any]:
        context.require("analyst")
        with database.engine.connect() as connection:
            principal = service.required(connection, db.principals, context.tenant_id, principal_id)
            cases = db.rows(
                connection,
                select(db.incidents)
                .where(
                    db.incidents.c.tenant_id == context.tenant_id,
                    db.incidents.c.principal_id == principal_id,
                )
                .order_by(db.incidents.c.updated_at.desc())
                .limit(10),
            )
            session_ids = select(db.sessions.c.id).where(
                db.sessions.c.tenant_id == context.tenant_id,
                db.sessions.c.principal_id == principal_id,
            )
            decisions = db.rows(
                connection,
                select(db.events)
                .where(
                    db.events.c.tenant_id == context.tenant_id,
                    db.events.c.session_id.in_(session_ids),
                )
                .order_by(db.events.c.sequence.desc())
                .limit(20),
            )
        return {
            "principal": principal,
            "incidents": cases,
            "decisions": decisions,
            "destination_permissions": [],
            "destination_state": "P3 gateway not configured",
        }

    @app.post("/v1/agents/{principal_id}/status")
    def identity_status(
        principal_id: str, body: IdentityStatus, context: Context, key: Key
    ) -> dict[str, Any]:
        context.require("security_admin")
        with database.transaction() as connection:
            route = f"/agents/{principal_id}/status"
            previous = service.idempotent_get(connection, context, route, key, body.model_dump())
            if previous is not None:
                return previous
            principal = service.required(connection, db.principals, context.tenant_id, principal_id)
            if principal["kind"] != "workload":
                raise DomainError(
                    403, "WORKLOAD_ONLY", "This control changes workload identities only"
                )
            values = {"status": body.status, "identity_epoch": principal["identity_epoch"] + 1}
            connection.execute(
                update(db.principals)
                .where(
                    db.principals.c.tenant_id == context.tenant_id,
                    db.principals.c.id == principal_id,
                )
                .values(**values)
            )
            if body.status == "suspended":
                all_agents = db.rows(
                    connection,
                    select(db.principals).where(db.principals.c.tenant_id == context.tenant_id),
                )
                affected = {principal_id}
                for _ in range(3):
                    affected |= {item["id"] for item in all_agents if item["parent_id"] in affected}
                active = db.rows(
                    connection,
                    select(db.sessions).where(
                        db.sessions.c.tenant_id == context.tenant_id,
                        db.sessions.c.principal_id.in_(affected),
                        db.sessions.c.route_mode != "TERMINATED",
                    ),
                )
                for session in active:
                    deception.terminate(service, connection, context, session, "IDENTITY_SUSPENDED")
                connection.execute(
                    update(db.approvals)
                    .where(
                        db.approvals.c.tenant_id == context.tenant_id,
                        db.approvals.c.principal_id.in_(affected),
                        db.approvals.c.status.in_(["pending", "approved"]),
                    )
                    .values(status="revoked")
                )
            service.audit(connection, context, "identity." + body.status, principal_id)
            result = {**principal, **values}
            service.idempotent_put(connection, context, route, key, body.model_dump(), result)
            return result

    @app.post("/v1/policies", status_code=201)
    def draft_policy(body: Policy, context: Context, key: Key) -> dict[str, Any]:
        context.require("security_admin")
        with database.transaction() as connection:
            previous = service.idempotent_get(
                connection, context, "/policies", key, body.model_dump()
            )
            if previous is not None:
                return previous
            if db.row(connection, db.policy_versions, context.tenant_id, body.version):
                raise DomainError(
                    409,
                    "POLICY_VERSION_EXISTS",
                    "Policy versions are immutable; choose a new version",
                )
            value = {
                "tenant_id": context.tenant_id,
                "id": body.version,
                "version": body.version,
                "digest": digest(body.model_dump()),
                "status": "draft",
                "document": body.model_dump(),
                "created_by": context.principal_id,
                "reviewed_by": None,
                "tested": False,
                "created_at": now(),
            }
            connection.execute(insert(db.policy_versions).values(**value))
            service.audit(
                connection, context, "policy.drafted", value["id"], {"digest": value["digest"]}
            )
            service.idempotent_put(connection, context, "/policies", key, body.model_dump(), value)
            return value

    @app.post("/v1/policies/{policy_id}/workflow")
    def policy_workflow(
        policy_id: str, body: PolicyTransition, context: Context, key: Key
    ) -> dict[str, Any]:
        return control.policy_change(service, context, policy_id, body, key)

    @app.get("/v1/integrations")
    def integration_status(context: Context) -> dict[str, Any]:
        return integrations.status(service, context)

    @app.post("/v1/integrations/hades/import", status_code=201)
    def import_hades(body: HadesReport, context: Context, key: Key) -> dict[str, Any]:
        return integrations.import_hades(service, context, body, key)

    @app.get("/v1/integrations/hades/{report_id}/summary")
    def report_summaries(report_id: str, context: Context) -> dict[str, Any]:
        items = ai.history(service, context, report_id=report_id)
        with database.engine.connect() as connection:
            used = connection.execute(
                select(func.count())
                .select_from(db.ai_requests)
                .where(
                    db.ai_requests.c.tenant_id == context.tenant_id,
                    db.ai_requests.c.import_id == report_id,
                    db.ai_requests.c.purpose == "report-summary",
                )
            ).scalar_one()
        return {
            "items": items,
            "report_call_budget": settings.model_case_call_budget,
            "calls_used": used,
            "calls_remaining": max(0, settings.model_case_call_budget - used),
        }

    @app.post("/v1/integrations/hades/{report_id}/summary")
    def summarize_hades(
        report_id: str, body: ReportSummaryRequest, context: Context, key: Key
    ) -> dict[str, Any]:
        return ai.summarize_report(service, context, report_id, body.expected_digest, key)

    @app.post("/v1/integrations/gateway/observations", status_code=202)
    def gateway_observation(body: GatewayObservation, context: Context) -> dict[str, str]:
        result = accept_gateway_observation(service, context, body)
        service.drain_outbox()
        return result

    @app.get("/v1/audit")
    def audit(
        context: Context,
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        q: str = "",
    ) -> dict[str, Any]:
        context.require("analyst")
        offset = offset_from(cursor)
        query = select(db.audit_log).where(db.audit_log.c.tenant_id == context.tenant_id)
        if q:
            query = query.where(
                or_(
                    db.audit_log.c.action.icontains(q, autoescape=True),
                    db.audit_log.c.actor_id.icontains(q, autoescape=True),
                    db.audit_log.c.object_id.icontains(q, autoescape=True),
                )
            )
        with database.engine.connect() as connection:
            items = db.rows(
                connection,
                query.order_by(db.audit_log.c.sequence.desc()).offset(offset).limit(limit + 1),
            )
        return {
            **page(items, limit, offset),
            "integrity_scope": "Application hash chain; not externally anchored or tamper-proof",
        }

    @app.get("/v1/search")
    def search(
        context: Context, q: Annotated[str, Query(min_length=2, max_length=100)]
    ) -> dict[str, Any]:
        context.require("analyst")
        with database.engine.connect() as connection:
            cases = db.rows(
                connection,
                select(db.incidents)
                .where(
                    db.incidents.c.tenant_id == context.tenant_id,
                    or_(
                        db.incidents.c.number.icontains(q, autoescape=True),
                        db.incidents.c.title.icontains(q, autoescape=True),
                    ),
                )
                .limit(6),
            )
            agents = db.rows(
                connection,
                select(db.principals)
                .where(
                    db.principals.c.tenant_id == context.tenant_id,
                    db.principals.c.kind == "workload",
                    or_(
                        db.principals.c.id.icontains(q, autoescape=True),
                        db.principals.c.name.icontains(q, autoescape=True),
                    ),
                )
                .limit(6),
            )
        return {"incidents": cases, "agents": agents}

    @app.get("/v1/laboratory")
    def scenarios(context: Context) -> dict[str, Any]:
        context.require("analyst")
        return {
            "items": laboratory.SCENARIOS,
            "data": "synthetic only",
            "profile": settings.profile,
        }

    @app.post("/v1/laboratory/run")
    def run_scenario(body: ScenarioRequest, context: Context, key: Key) -> dict[str, Any]:
        return laboratory.run(service, context, body, key)

    @app.get("/v1/settings")
    def configuration(context: Context) -> dict[str, Any]:
        context.require("analyst")
        ai.apply_runtime(service)
        with database.engine.connect() as connection:
            state = dict(
                connection.execute(
                    select(db.runtime).where(db.runtime.c.tenant_id == context.tenant_id)
                )
                .mappings()
                .one()
            )
        public = {
            "profile": settings.profile,
            "storage": database.engine.dialect.name,
            "local_fixture_login": settings.local_login,
            "model_provider": settings.model_provider,
            "gemini_model": settings.gemini_model or None,
            "gemini_region": settings.gemini_location,
            "active_policy_version": state["active_policy_id"],
            "engagements_enabled": state["engagements_enabled"],
            "session_ttl_seconds": settings.session_ttl_seconds,
            "decoy_request_budget": settings.decoy_request_budget,
            "max_engagements": settings.max_engagements,
            "model_call_budget": settings.model_call_budget,
            "model_case_call_budget": settings.model_case_call_budget,
            "model_egress_approved": settings.model_egress_approved,
            "ai_config_digest": ai.configuration(service)["config_digest"],
            "model_calls": state["model_calls"],
            "template_version": deception.TEMPLATE_VERSION,
            "template_sha256": service.sandbox.module_digest,
            "retention_event_days": settings.event_retention_days,
        }
        return {
            **public,
            "config_digest": digest(
                {key: value for key, value in public.items() if key != "model_calls"}
            ),
            "provenance": control.provenance(),
            "ai": ai.status(service, context),
            "gaps": [
                "Native fixture login is not enterprise SSO or workload mTLS.",
                "SQLite serializes writers; PostgreSQL code path needs its own acceptance run.",
                "P3 native gateway, direct agent egress fencing and existing-tunnel revocation are unverified.",
                "P2 cloud services are not deployed; live Gemini requires explicit approved configuration.",
                "Streaming MCP, WebSocket and arbitrary attacker code execution are not supported.",
                "Wasm capability probes are not operating-system TCP reachability measurements.",
            ],
        }

    @app.patch("/v1/settings")
    def update_settings(body: SettingsUpdate, context: Context, key: Key) -> dict[str, Any]:
        context.require("security_admin")
        if body.engagements_enabled and not service.sandbox.available():
            raise DomainError(
                503,
                "ISOLATION_UNVERIFIED",
                "Reverify capability isolation before enabling engagements",
            )
        with database.transaction() as connection:
            previous = service.idempotent_get(
                connection, context, "/settings", key, body.model_dump()
            )
            if previous is not None:
                return previous
            connection.execute(
                update(db.runtime)
                .where(db.runtime.c.tenant_id == context.tenant_id)
                .values(
                    engagements_enabled=body.engagements_enabled,
                )
            )
            service.audit(
                connection,
                context,
                "settings.engagements_changed",
                context.tenant_id,
                body.model_dump(),
            )
            service.idempotent_put(
                connection, context, "/settings", key, body.model_dump(), body.model_dump()
            )
        return body.model_dump()

    @app.get("/v1/architecture")
    def architecture(context: Context) -> dict[str, Any]:
        context.require("analyst")
        live_backend = service.backend.healthy()
        nodes = [
            {
                "id": "external",
                "name": "External clients",
                "plane": "edge",
                "osi": "L7",
                "status": "instrumented",
                "role": "Authenticated laboratory HTTP sessions. Behaviour is evidence, not actor attribution.",
                "identity": "Opaque server-issued bearer session",
                "x": 8,
                "y": 22,
            },
            {
                "id": "ingress",
                "name": "Controlled ingress",
                "plane": "enforcement",
                "osi": "L7",
                "status": "ready",
                "role": "Validates identity, bounded JSON, tenant context and server-owned route state.",
                "identity": "Verified application token; identity/routing headers do not grant authority",
                "x": 32,
                "y": 22,
            },
            {
                "id": "application",
                "name": "Protected application",
                "plane": "production",
                "osi": "L7",
                "status": "ready",
                "role": "Synthetic procurement workflows. All protected tools pass the deterministic dispatcher.",
                "identity": "Tenant and workload scope",
                "x": 57,
                "y": 22,
            },
            {
                "id": "agents",
                "name": "Internal agents",
                "plane": "production",
                "osi": "L7",
                "status": "registered",
                "role": "Two fixture workloads with distinct tool and resource scopes, plus bounded child identities.",
                "identity": "Short-lived native bearer fixture; not native gateway certificates",
                "x": 8,
                "y": 53,
            },
            {
                "id": "dispatcher",
                "name": "Tool enforcement",
                "plane": "enforcement",
                "osi": "L7",
                "status": "ready",
                "role": "Deny precedence, scope intersection, exact approvals, idempotency and the shared dispatch fence.",
                "identity": "Workload + tenant + delegation lineage",
                "x": 32,
                "y": 53,
            },
            {
                "id": "backend",
                "name": "Synthetic backend",
                "plane": "production",
                "osi": "L7",
                "status": "ready" if live_backend else "unavailable",
                "role": "Separate signed loopback HTTP service and independent SQLite effect ledger. No public application token pass-through.",
                "identity": "Request-bound HMAC service proof with fixed handler catalogue",
                "x": 82,
                "y": 53,
            },
            {
                "id": "gateway",
                "name": "Native CONNECT gateway",
                "plane": "proposed",
                "osi": "L7 protocol · L3/L4 destination control",
                "status": "not-configured",
                "role": "Proposed P3 path. Certificate/key/destination authorization is separate from tool authorization. Never shown as live.",
                "identity": "Native mTLS leaf key + signed destination registry (unverified here)",
                "x": 57,
                "y": 53,
            },
            {
                "id": "soc",
                "name": "SOC control plane",
                "plane": "control",
                "osi": "L7",
                "status": "ready",
                "role": "Durable events/outbox, versioned deterministic rules, cases, analyst audit and advisory investigation.",
                "identity": "Scoped human roles / source-bound producer",
                "x": 32,
                "y": 84,
            },
            {
                "id": "router",
                "name": "Fenced decoy router",
                "plane": "deception",
                "osi": "L7",
                "status": "ready",
                "role": "Restrict before diversion, monotonic route versions, eligibility and TTL/request budgets. Never falls back to production.",
                "identity": "Deterministic orchestrator; no model routing authority",
                "x": 57,
                "y": 84,
            },
            {
                "id": "decoy",
                "name": "Wasm supplier decoy",
                "plane": "deception",
                "osi": "L7 emulation · capability sandbox",
                "status": "verified" if service.sandbox.available() else "unverified",
                "role": "No-import Wasmtime module: no WASI, sockets, DNS, filesystem, environment or host callbacks; 64 KiB memory and bounded fuel.",
                "identity": "Tenant/session-specific synthetic state only",
                "x": 82,
                "y": 84,
            },
        ]
        edges = [
            {
                "id": "external-ingress",
                "source": "external",
                "target": "ingress",
                "protocol": "HTTP/JSON on loopback",
                "state": "configured-local",
                "detail": "Only instrumented HTTP endpoints are covered.",
            },
            {
                "id": "ingress-app",
                "source": "ingress",
                "target": "application",
                "protocol": "Authorized application dispatch",
                "state": "configured-local",
                "detail": "Server-owned route and tenant checks precede dispatch.",
            },
            {
                "id": "agents-dispatcher",
                "source": "agents",
                "target": "dispatcher",
                "protocol": "Typed HTTP tools",
                "state": "configured-local",
                "detail": "This is not a streaming MCP implementation.",
            },
            {
                "id": "app-dispatcher",
                "source": "application",
                "target": "dispatcher",
                "protocol": "Typed handler call",
                "state": "configured-local",
                "detail": "Every protected operation passes policy checks.",
            },
            {
                "id": "dispatcher-backend",
                "source": "dispatcher",
                "target": "backend",
                "protocol": "Request-bound signed HTTP",
                "state": "live-local" if live_backend else "unavailable",
                "detail": "Native P1 path bypasses the unconfigured gateway; no P3 egress claim.",
            },
            {
                "id": "dispatcher-gateway",
                "source": "dispatcher",
                "target": "gateway",
                "protocol": "mTLS HTTP/2 CONNECT (proposed)",
                "state": "proposed",
                "detail": "Native TLS endpoint and registry must be deployed and tested separately.",
            },
            {
                "id": "gateway-backend",
                "source": "gateway",
                "target": "backend",
                "protocol": "Opaque TCP tunnel (proposed)",
                "state": "proposed",
                "detail": "An allowed destination does not authorize any particular tool operation.",
            },
            {
                "id": "ingress-soc",
                "source": "ingress",
                "target": "soc",
                "protocol": "Transactional event/outbox",
                "state": "configured-local",
                "detail": "Receipt-time correlation with authenticated metadata; payload text remains untrusted.",
            },
            {
                "id": "soc-router",
                "source": "soc",
                "target": "router",
                "protocol": "Versioned route transaction",
                "state": "configured-local",
                "detail": "Only deterministic corroborated rules or authorized operators can respond.",
            },
            {
                "id": "router-decoy",
                "source": "router",
                "target": "decoy",
                "protocol": "Bounded Wasm call, no network imports",
                "state": "live-local" if service.sandbox.available() else "unavailable",
                "detail": "Capability isolation, not a claim that a network policy was deployed.",
            },
        ]
        with database.engine.connect() as connection:
            count = connection.execute(
                select(func.count())
                .select_from(db.events)
                .where(db.events.c.tenant_id == context.tenant_id)
            ).scalar_one()
        return {
            "nodes": nodes,
            "edges": edges,
            "profile": settings.profile,
            "recorded_events": count,
            "osi_note": "Primary L7 enforcement. L3/L4 network controls support separate P3 deployment. Session tracking is not a Layer 5 appliance; TLS identity is not tool authorization.",
        }

    build = Path(__file__).resolve().parents[1] / "apps" / "dashboard" / "dist"
    if (build / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=build / "assets"), name="assets")

    @app.get("/THIRD-PARTY-NOTICES.txt", include_in_schema=False)
    def third_party_notices() -> Response:
        path = build / "THIRD-PARTY-NOTICES.txt"
        if not path.is_file():
            raise DomainError(
                503, "NOTICES_NOT_BUILT", "Build the console to include dependency notices"
            )
        return FileResponse(path, media_type="text/plain")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> Response:
        allowed = {
            "",
            "login",
            "overview",
            "incidents",
            "agents",
            "guardrails",
            "deception",
            "architecture",
            "integrations",
            "audit",
            "settings",
        }
        if path.split("/")[0] not in allowed:
            raise DomainError(404, "NOT_FOUND", "Endpoint not found")
        if not (build / "index.html").is_file():
            raise DomainError(
                503, "CONSOLE_NOT_BUILT", "Build apps/dashboard before serving the native console"
            )
        return FileResponse(build / "index.html")
