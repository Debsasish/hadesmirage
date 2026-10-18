from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import ValidationError
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection

from mirage import db
from mirage.auth import PrincipalContext, verify_lineage
from mirage.common import DomainError, after, canonical, digest, now, redact, uid
from mirage.models import (
    CaseAnswer,
    CaseQuestion,
    Investigation,
    ProviderCheck,
    ReportSummary,
    SyntheticWording,
)
from mirage.providers import (
    PROVIDER_ACTIONABLE,
    REPORT_INSTRUCTION,
    SYSTEM_INSTRUCTION,
    WORDING_INSTRUCTION,
    Provider,
    case_payload,
    thinking_limits,
)

if TYPE_CHECKING:
    from mirage.service import Service

logger = logging.getLogger("mirage.ai")
POLICY_VERSION = "advisory-v2"


def configuration(service: Service, active: Provider | None = None) -> dict[str, Any]:
    settings = service.settings
    active = active or service.provider
    public = {
        "provider": active.name,
        "mode": settings.model_provider,
        "model": settings.gemini_model or None,
        "region": settings.gemini_location,
        "project_configured": bool(settings.gemini_project),
        "api_key_configured": bool(settings.gemini_api_key),
        "credential": "api-key"
        if settings.gemini_api_key
        else ("workload-identity" if settings.gemini_project else "none"),
        "endpoint": "Gemini API (AI Studio)"
        if settings.gemini_api_key and settings.gemini_endpoint != "vertex"
        else "Vertex AI",
        "egress_approved": settings.model_egress_approved,
        "policy_version": POLICY_VERSION,
        "timeout_seconds": settings.model_timeout_seconds,
        "input_bytes": settings.model_input_bytes,
        "max_output_tokens": 1800,
        "case_call_budget": settings.model_case_call_budget,
        "tenant_call_budget": settings.model_call_budget,
        "max_pending": settings.model_max_pending,
        "decoy_wording_enabled": settings.decoy_model_wording,
        "advisory_only": True,
        "tools_enabled": False,
    }
    return {
        **public,
        "config_digest": digest(
            {
                **public,
                "project": settings.gemini_project,
                "prompts": [SYSTEM_INSTRUCTION, REPORT_INSTRUCTION, WORDING_INSTRUCTION],
            }
        ),
    }


def public_request(item: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "id",
        "purpose",
        "resource_version",
        "provider",
        "state",
        "question",
        "output",
        "error_code",
        "tokens",
        "started_at",
        "deadline_at",
        "completed_at",
        "duration_ms",
    )
    value = {key: item[key] for key in fields}
    if item["state"] == "pending" and item["deadline_at"] <= now():
        value["state"] = "unknown"
    return value


def status(service: Service, context: PrincipalContext) -> dict[str, Any]:
    context.require("analyst")
    runtime_row = apply_runtime(service)
    config = configuration(service)
    with service.db.engine.connect() as connection:
        runtime = dict(
            connection.execute(
                select(db.runtime).where(db.runtime.c.tenant_id == context.tenant_id)
            )
            .mappings()
            .one()
        )
        checks = db.rows(
            connection,
            select(db.ai_requests)
            .where(
                db.ai_requests.c.tenant_id == context.tenant_id,
                db.ai_requests.c.purpose == "provider-check",
                db.ai_requests.c.config_digest == config["config_digest"],
            )
            .order_by(db.ai_requests.c.started_at.desc())
            .limit(1),
        )
        pending = connection.execute(
            select(func.count())
            .select_from(db.ai_requests)
            .where(
                db.ai_requests.c.tenant_id == context.tenant_id,
                db.ai_requests.c.state == "pending",
                db.ai_requests.c.deadline_at > now(),
            )
        ).scalar_one()
        unknown_usage = connection.execute(
            select(func.count())
            .select_from(db.ai_requests)
            .where(
                db.ai_requests.c.tenant_id == context.tenant_id,
                db.ai_requests.c.state != "pending",
                db.ai_requests.c.tokens.is_(None),
            )
        ).scalar_one()
    configured = bool(
        (config["project_configured"] or config["api_key_configured"]) and config["model"]
    )
    last = public_request(checks[0]) if checks else None
    if config["mode"] == "fixture":
        state = "fixture"
    elif config["mode"] == "unavailable":
        state = "unavailable"
    elif not configured:
        state = "not-configured"
    elif not config["egress_approved"]:
        state = "egress-disabled"
    elif last is None:
        state = "configured-unverified"
    elif last["state"] == "succeeded":
        state = "check-passed"
    elif last["state"] in {"failed", "unknown"}:
        state = "check-failed"
    elif last["state"] == "pending":
        state = "checking"
    else:
        raise DomainError(
            503, "MODEL_CHECK_STATE_INVALID", "Stored provider check state is invalid"
        )
    return {
        **config,
        "state": state,
        "can_generate": config["mode"] == "fixture"
        or (config["mode"] == "gemini" and configured and config["egress_approved"]),
        "live_check_passed": config["mode"] == "gemini" and state == "check-passed",
        "last_check": last,
        "call_reservations_used": runtime["model_calls"],
        "calls_remaining": max(0, config["tenant_call_budget"] - runtime["model_calls"]),
        "reported_tokens": runtime["model_tokens"],
        "requests_without_reported_usage": unknown_usage,
        "pending_requests": pending,
        "credentials": "Workload credentials stay outside model context and the browser",
        "check_scope": "A successful check is one bounded request, not continuous provider health",
        "project": service.settings.gemini_project or None,
        "auto_triage": bool(runtime_row and runtime_row["auto_triage"]),
        "settings_version": runtime_row["version"] if runtime_row else 0,
        "settings_updated_by": runtime_row["updated_by"] if runtime_row else None,
        "settings_updated_at": runtime_row["updated_at"] if runtime_row else None,
        "settings_source": "portal" if runtime_row else "environment",
    }


SUGGESTED_MODELS = [
    {"id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash", "note": "Newest fast model"},
    {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash", "note": "Fast, low cost"},
    {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro", "note": "Deeper reasoning, higher cost"},
    {"id": "gemini-2.5-flash-lite", "label": "Gemini 2.5 Flash-Lite", "note": "Lowest cost"},
]
AUTOMATION_PRINCIPAL = "ai-autotriage"


def apply_runtime(service: Service) -> dict[str, Any] | None:
    """Apply portal-managed AI settings; credentials stay in server configuration only."""
    with service.db.engine.connect() as connection:
        found = (
            connection.execute(select(db.ai_settings).where(db.ai_settings.c.id == "default"))
            .mappings()
            .first()
        )
    if found is None:
        return None
    row = dict(found)
    marker = (row["version"], row["updated_at"])
    if getattr(service, "_ai_runtime_marker", None) != marker:
        from mirage.providers import provider as build_provider

        settings = service.settings
        settings.model_provider = row["provider"]
        settings.gemini_project = row["project"]
        settings.gemini_location = row["location"]
        settings.gemini_model = row["model"]
        settings.model_egress_approved = row["egress_approved"]
        settings.decoy_model_wording = row["decoy_wording"]
        service.provider = build_provider(settings)
        service._ai_runtime_marker = marker
    return row


def update_runtime(
    service: Service, context: PrincipalContext, body: Any, key: str
) -> dict[str, Any]:
    context.require("security_admin")
    if body.provider == "gemini" and not (body.project or service.settings.gemini_api_key):
        raise DomainError(
            422,
            "MODEL_CREDENTIAL_REQUIRED",
            "Enter a Google Cloud project ID, or configure a Gemini API key on the server",
        )
    payload = body.model_dump(exclude={"acknowledge_egress"})
    with service.db.transaction() as connection:
        previous = service.idempotent_get(connection, context, "/ai/config", key, payload)
        if previous is not None:
            return previous
        current = (
            connection.execute(select(db.ai_settings).where(db.ai_settings.c.id == "default"))
            .mappings()
            .first()
        )
        version = current["version"] if current else 0
        if body.expected_version != version:
            raise DomainError(
                409, "AI_SETTINGS_CHANGED", "AI settings changed; reload before saving"
            )
        since = current["auto_triage_since"] if current else None
        if body.auto_triage and not (current and current["auto_triage"]):
            since = now()
        value = {
            "id": "default",
            "provider": body.provider,
            "project": body.project,
            "location": body.location,
            "model": body.model,
            "egress_approved": body.egress_approved and body.provider == "gemini",
            "auto_triage": body.auto_triage,
            "decoy_wording": body.decoy_wording,
            "auto_triage_since": since if body.auto_triage else None,
            "version": version + 1,
            "updated_by": context.principal_id,
            "updated_at": now(),
        }
        if current:
            connection.execute(
                update(db.ai_settings).where(db.ai_settings.c.id == "default").values(**value)
            )
        else:
            connection.execute(insert(db.ai_settings).values(**value))
        service.audit(
            connection,
            context,
            "ai.settings_changed",
            "ai-settings",
            {key: value[key] for key in value if key not in {"id"}},
        )
        service.idempotent_put(connection, context, "/ai/config", key, payload, value)
    apply_runtime(service)
    return value


def discover_models(service: Service, context: PrincipalContext) -> dict[str, Any]:
    context.require("security_admin")
    apply_runtime(service)
    settings = service.settings
    if not (
        settings.model_provider == "gemini"
        and (settings.gemini_project or settings.gemini_api_key)
        and settings.model_egress_approved
    ):
        return {
            "source": "suggestions",
            "items": SUGGESTED_MODELS,
            "note": "Suggested IDs, not verified for your project. Configure Gemini and approve "
            "model egress to list models available to the service identity.",
        }
    from google import genai
    from google.auth.exceptions import GoogleAuthError
    from google.genai import errors, types

    from mirage.providers import client_arguments, endpoint

    try:
        found: list[dict[str, Any]] = []
        with genai.Client(
            **client_arguments(settings),
            http_options=types.HttpOptions(
                **({"api_version": "v1"} if endpoint(settings) == "vertex" else {}),
                timeout=settings.model_timeout_seconds * 1000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        ) as client:
            for index, model in enumerate(client.models.list(config={"page_size": 50})):
                if index >= 200 or len(found) >= 60:
                    break
                name = (model.name or "").rsplit("/", 1)[-1]
                if name.startswith("gemini"):
                    found.append(
                        {
                            "id": name,
                            "label": model.display_name or name,
                            "note": "Listed by Vertex AI for this project",
                        }
                    )
        return {"source": "live", "items": found or SUGGESTED_MODELS, "note": "Live list"}
    except (errors.APIError, GoogleAuthError, httpx.HTTPError, ValueError) as error:
        logger.warning("Model discovery failed: %s", type(error).__name__)
        return {
            "source": "suggestions",
            "items": SUGGESTED_MODELS,
            "note": "Live model listing failed; showing suggestions.",
            "error": "MODEL_DISCOVERY_UNAVAILABLE",
        }


def _sanitize(service: Service, value: str) -> str:
    for secret in (service.settings.backend_secret, service.settings.access_code):
        if secret:
            value = value.replace(secret, "[redacted]")
    return redact(value)


def _allowed(service: Service, active: Provider) -> None:
    if active.name != "gemini-vertex":
        return
    if not service.settings.gemini_model or not (
        service.settings.gemini_project or service.settings.gemini_api_key
    ):
        raise DomainError(
            503,
            "MODEL_NOT_CONFIGURED",
            "Configure a Gemini model and a project or server API key",
        )
    if not service.settings.model_egress_approved:
        raise DomainError(
            403, "MODEL_EGRESS_NOT_APPROVED", "Live model egress has not been approved"
        )


def _set_idempotent(
    connection: Connection,
    context: PrincipalContext,
    request: dict[str, Any],
    response: dict[str, Any],
) -> None:
    connection.execute(
        update(db.idempotency)
        .where(
            db.idempotency.c.tenant_id == context.tenant_id,
            db.idempotency.c.principal_id == context.principal_id,
            db.idempotency.c.route == request["route"],
            db.idempotency.c.key == request["request_key"],
        )
        .values(response=response)
    )


def _failure(
    service: Service,
    connection: Connection,
    context: PrincipalContext,
    request: dict[str, Any],
    error: DomainError,
    tokens: int | None = None,
) -> None:
    current = db.row(connection, db.ai_requests, context.tenant_id, request["id"])
    if current and current["state"] == "succeeded":
        raise DomainError(
            409, "MODEL_REQUEST_COMPLETED", "The original AI request already completed"
        )
    if current:
        connection.execute(
            update(db.ai_requests)
            .where(
                db.ai_requests.c.tenant_id == context.tenant_id,
                db.ai_requests.c.id == request["id"],
            )
            .values(
                state="failed",
                error_code=error.code,
                http_status=error.status,
                completed_at=now(),
                tokens=tokens if current["tokens"] is None else current["tokens"],
            )
        )
    if tokens is not None and (current is None or current["tokens"] is None):
        connection.execute(
            update(db.runtime)
            .where(db.runtime.c.tenant_id == context.tenant_id)
            .values(model_tokens=db.runtime.c.model_tokens + tokens)
        )
    if request["purpose"] == "investigation":
        connection.execute(
            update(db.incidents)
            .where(
                db.incidents.c.tenant_id == context.tenant_id,
                db.incidents.c.id == request["resource_id"],
            )
            .values(model_error=error.code)
        )
    _set_idempotent(
        connection,
        context,
        request,
        {
            "state": "failed",
            "http_status": error.status,
            "code": error.code,
            "message": error.message,
        },
    )
    service.audit(
        connection,
        context,
        "investigation.rejected"
        if request["purpose"] == "investigation"
        else "ai.request_rejected",
        request["resource_id"],
        {"request_id": request["id"], "purpose": request["purpose"], "code": error.code},
    )


def _expire(service: Service, context: PrincipalContext) -> None:
    with service.db.transaction() as connection:
        expired = db.rows(
            connection,
            select(db.ai_requests).where(
                db.ai_requests.c.tenant_id == context.tenant_id,
                db.ai_requests.c.state == "pending",
                db.ai_requests.c.deadline_at <= now(),
            ),
        )
        for request in expired:
            owner = service.required(
                connection, db.principals, context.tenant_id, request["principal_id"]
            )
            actor = PrincipalContext(
                context.tenant_id, owner["id"], tuple(owner["roles"]), owner["kind"]
            )
            _failure(
                service,
                connection,
                actor,
                request,
                DomainError(
                    504,
                    "MODEL_REQUEST_EXPIRED",
                    "AI request expired; provider outcome is unknown. No automatic resend occurred.",
                ),
            )


def _previous(
    service: Service,
    connection: Connection,
    context: PrincipalContext,
    route: str,
    key: str,
    body: dict[str, Any],
) -> dict[str, Any] | None:
    previous = service.idempotent_get(connection, context, route, key, body)
    if previous is None:
        return None
    if previous.get("state") == "pending":
        raise DomainError(409, "MODEL_REQUEST_PENDING", "This AI request is already reserved")
    if previous.get("state") == "failed":
        raise DomainError(previous["http_status"], previous["code"], previous["message"])
    return previous["value"] if previous.get("state") == "succeeded" else previous


def _reserve(
    service: Service,
    connection: Connection,
    context: PrincipalContext,
    *,
    purpose: str,
    resource_id: str,
    route: str,
    key: str,
    body: dict[str, Any],
    payload: dict[str, Any],
    active: Provider,
    version: int | None = None,
    incident_id: str | None = None,
    import_id: str | None = None,
    decoy_id: str | None = None,
    question: str | None = None,
    budget_units: int = 0,
) -> dict[str, Any]:
    _allowed(service, active)
    if len(canonical(payload)) > service.settings.model_input_bytes:
        raise DomainError(
            413, "MODEL_CONTEXT_TOO_LARGE", "The bounded AI context limit was exceeded"
        )
    runtime = dict(
        connection.execute(select(db.runtime).where(db.runtime.c.tenant_id == context.tenant_id))
        .mappings()
        .one()
    )
    if runtime["model_calls"] >= service.settings.model_call_budget:
        raise DomainError(429, "MODEL_BUDGET_EXHAUSTED", "Tenant AI request budget exhausted")
    pending = connection.execute(
        select(func.count())
        .select_from(db.ai_requests)
        .where(
            db.ai_requests.c.tenant_id == context.tenant_id,
            db.ai_requests.c.state == "pending",
        )
    ).scalar_one()
    if pending >= service.settings.model_max_pending:
        raise DomainError(429, "MODEL_CONCURRENCY_EXHAUSTED", "Too many pending AI reservations")
    service.admit(connection, context, "ai-model", limit=20)
    request = {
        "tenant_id": context.tenant_id,
        "id": uid(),
        "principal_id": context.principal_id,
        "purpose": purpose,
        "resource_id": resource_id,
        "resource_version": version,
        "incident_id": incident_id,
        "import_id": import_id,
        "decoy_id": decoy_id,
        "provider": active.name,
        "config_digest": configuration(service, active)["config_digest"],
        "context_digest": digest(payload),
        "route": route,
        "request_key": key,
        "state": "pending",
        "question": question,
        "output": None,
        "error_code": None,
        "http_status": None,
        "tokens": None,
        "budget_units": budget_units,
        "started_at": now(),
        "deadline_at": after(max(60, service.settings.model_timeout_seconds * 3)),
        "completed_at": None,
        "duration_ms": None,
    }
    connection.execute(insert(db.ai_requests).values(**request))
    connection.execute(
        update(db.runtime)
        .where(db.runtime.c.tenant_id == context.tenant_id)
        .values(model_calls=runtime["model_calls"] + 1)
    )
    service.idempotent_put(
        connection, context, route, key, body, {"state": "pending", "request_id": request["id"]}
    )
    service.audit(
        connection,
        context,
        "ai.request_reserved",
        resource_id,
        {
            "request_id": request["id"],
            "purpose": purpose,
            "provider": active.name,
            "context_digest": request["context_digest"],
            "config_digest": request["config_digest"],
        },
    )
    return request


def _usage(tokens: int | None) -> int | None:
    if tokens is not None and (type(tokens) is not int or not 0 <= tokens <= 100000):
        raise DomainError(502, "MODEL_USAGE_INVALID", "Invalid model usage metadata")
    return tokens


def _verify_actor(
    service: Service, connection: Connection, context: PrincipalContext, purpose: str
) -> None:
    actor = service.required(connection, db.principals, context.tenant_id, context.principal_id)
    verify_lineage(connection, actor)
    refreshed = PrincipalContext(
        context.tenant_id, actor["id"], tuple(actor["roles"]), actor["kind"]
    )
    if purpose == "decoy-wording":
        refreshed.require("workload", "external")
    else:
        refreshed.require("security_admin" if purpose == "provider-check" else "analyst")


def _complete(
    service: Service,
    context: PrincipalContext,
    request: dict[str, Any],
    output: dict[str, Any],
    tokens: int | None,
    extra: dict[str, Any] | None = None,
    cache_value: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with service.db.transaction() as connection:
        current = service.required(connection, db.ai_requests, context.tenant_id, request["id"])
        if current["state"] != "pending" or current["deadline_at"] <= now():
            raise DomainError(
                504, "MODEL_REQUEST_EXPIRED", "AI response arrived after its reservation ended"
            )
        _verify_actor(service, connection, context, request["purpose"])
        if request["incident_id"]:
            case = service.required(
                connection, db.incidents, context.tenant_id, request["incident_id"]
            )
            if case["version"] != request["resource_version"]:
                raise DomainError(
                    409,
                    "CASE_VERSION_CHANGED",
                    "New evidence arrived; request analysis of the current case version",
                )
        if request["purpose"] == "decoy-wording":
            decoy = service.required(connection, db.decoys, context.tenant_id, request["decoy_id"])
            session = service.owned_session(connection, context, decoy["session_id"])
            if (
                session["route_mode"] != "DECOY"
                or session["route_version"] != request["resource_version"]
                or session["expires_at"] <= now()
            ):
                raise DomainError(
                    403, "ENGAGEMENT_STOPPED", "Engagement stopped during wording generation"
                )
        generated = now()
        duration = max(
            0,
            int(
                (
                    datetime.fromisoformat(generated)
                    - datetime.fromisoformat(request["started_at"])
                ).total_seconds()
                * 1000
            ),
        )
        value = {
            **output,
            **(extra or {}),
            "provider": request["provider"],
            "model": service.settings.gemini_model
            if request["provider"] == "gemini-vertex"
            else None,
            "generated_at": generated,
            "tokens": tokens,
            "request_id": request["id"],
            "context_digest": request["context_digest"],
            "ai_config_digest": request["config_digest"],
            "duration_ms": duration,
            "advisory_only": True,
        }
        connection.execute(
            update(db.ai_requests)
            .where(
                db.ai_requests.c.tenant_id == context.tenant_id,
                db.ai_requests.c.id == request["id"],
            )
            .values(
                state="succeeded",
                output=value,
                tokens=tokens,
                completed_at=generated,
                duration_ms=duration,
            )
        )
        if tokens is not None:
            connection.execute(
                update(db.runtime)
                .where(db.runtime.c.tenant_id == context.tenant_id)
                .values(model_tokens=db.runtime.c.model_tokens + tokens)
            )
        if request["purpose"] == "investigation":
            connection.execute(
                update(db.incidents)
                .where(
                    db.incidents.c.tenant_id == context.tenant_id,
                    db.incidents.c.id == request["incident_id"],
                )
                .values(investigation=value, model_error=None)
            )
        _set_idempotent(
            connection,
            context,
            request,
            {"state": "succeeded", "value": value if cache_value is None else cache_value},
        )
        service.audit(
            connection,
            context,
            "investigation.generated"
            if request["purpose"] == "investigation"
            else "ai.response_generated",
            request["resource_id"],
            {
                "request_id": request["id"],
                "purpose": request["purpose"],
                "provider": request["provider"],
                "tokens": tokens,
            },
        )
        return value if cache_value is None else cache_value


def _reject(
    service: Service,
    context: PrincipalContext,
    request: dict[str, Any],
    error: DomainError | ValueError | TypeError,
    tokens: int | None = None,
) -> DomainError:
    failure = DomainError(
        error.status if isinstance(error, DomainError) else 502,
        error.code if isinstance(error, DomainError) else "MODEL_SCHEMA_INVALID",
        error.message
        if isinstance(error, DomainError) and error.code in PROVIDER_ACTIONABLE
        else "AI response unavailable; deterministic evidence and access controls are unchanged",
    )
    with service.db.transaction() as connection:
        _failure(service, connection, context, request, failure, tokens)
    logger.warning(
        "AI request rejected: purpose=%s code=%s request_id=%s",
        request["purpose"],
        failure.code,
        request["id"],
    )
    return failure


def _case_events(
    service: Service, connection: Connection, context: PrincipalContext, case_id: str
) -> list[dict[str, Any]]:
    events = db.rows(
        connection,
        select(db.events)
        .join(
            db.incident_events,
            (db.events.c.tenant_id == db.incident_events.c.tenant_id)
            & (db.events.c.id == db.incident_events.c.event_id),
        )
        .where(
            db.incident_events.c.tenant_id == context.tenant_id,
            db.incident_events.c.incident_id == case_id,
        )
        .order_by(db.events.c.sequence.desc())
        .limit(20),
    )
    if not events:
        raise DomainError(409, "CASE_WITHOUT_EVIDENCE", "No case evidence is available")
    for event in events:
        event["body"] = {
            **event["body"],
            "attributes": {
                key: _sanitize(service, value) if isinstance(value, str) else value
                for key, value in event["body"]["attributes"].items()
            },
        }
    return events


def case_analysis(
    service: Service,
    context: PrincipalContext,
    case_id: str,
    *,
    question: CaseQuestion | None = None,
    active: Provider | None = None,
    key: str | None = None,
) -> dict[str, Any]:
    context.require("analyst")
    apply_runtime(service)
    active = active or service.provider
    key = key or uid()
    purpose = "case-question" if question else "investigation"
    route = f"/incidents/{case_id}/{'assistant' if question else 'investigate'}"
    body = question.model_dump() if question else {}
    _expire(service, context)
    with service.db.transaction() as connection:
        case = service.required(connection, db.incidents, context.tenant_id, case_id)
        previous = _previous(service, connection, context, route, key, body)
        if previous is not None:
            return previous
        if question and question.expected_version != case["version"]:
            raise DomainError(
                409, "CASE_VERSION_CHANGED", "Reload the current case before asking a question"
            )
        if case["model_calls"] >= service.settings.model_case_call_budget:
            raise DomainError(
                429,
                "MODEL_BUDGET_EXHAUSTED",
                "This case's shared analysis/question budget is exhausted",
            )
        events = _case_events(service, connection, context, case_id)
        clean_question = _sanitize(service, question.question) if question else None
        payload = case_payload(case, events, clean_question)
        request = _reserve(
            service,
            connection,
            context,
            purpose=purpose,
            resource_id=case_id,
            version=case["version"],
            incident_id=case_id,
            route=route,
            key=key,
            body=body,
            payload=payload,
            active=active,
            question=clean_question,
        )
        connection.execute(
            update(db.incidents)
            .where(
                db.incidents.c.tenant_id == context.tenant_id,
                db.incidents.c.id == case_id,
            )
            .values(model_calls=case["model_calls"] + 1)
        )
    tokens = None
    try:
        output, reported = (
            active.answer(case, events, clean_question)
            if clean_question is not None
            else active.investigate(case, events)
        )
        tokens = _usage(reported)
        model = CaseAnswer if question else Investigation
        validated = (
            model.model_validate_json(output)
            if isinstance(output, str)
            else model.model_validate(output)
        )
        validated.verify(case_id, case["version"], {event["id"] for event in events})
        return _complete(
            service,
            context,
            request,
            validated.model_dump(),
            tokens,
            {
                "coverage": {
                    "events_supplied": len(events),
                    "event_limit": 20,
                    "conversation_memory": False,
                }
            },
        )
    except (ValidationError, ValueError, TypeError, DomainError) as error:
        raise _reject(service, context, request, error, tokens) from error


def history(
    service: Service,
    context: PrincipalContext,
    *,
    case_id: str | None = None,
    report_id: str | None = None,
) -> list[dict[str, Any]]:
    context.require("analyst")
    if (case_id is None) == (report_id is None):
        raise ValueError("Select exactly one AI history scope")
    with service.db.engine.connect() as connection:
        service.required(
            connection,
            db.incidents if case_id else db.imports,
            context.tenant_id,
            case_id or report_id,
        )
        items = db.rows(
            connection,
            select(db.ai_requests)
            .where(
                db.ai_requests.c.tenant_id == context.tenant_id,
                (db.ai_requests.c.incident_id == case_id)
                if case_id
                else (db.ai_requests.c.import_id == report_id),
                db.ai_requests.c.purpose == ("case-question" if case_id else "report-summary"),
            )
            .order_by(db.ai_requests.c.started_at.desc())
            .limit(10),
        )
    return [public_request(item) for item in items]


def summarize_report(
    service: Service, context: PrincipalContext, report_id: str, expected_digest: str, key: str
) -> dict[str, Any]:
    context.require("analyst")
    apply_runtime(service)
    route, body = f"/integrations/hades/{report_id}/summary", {"expected_digest": expected_digest}
    _expire(service, context)
    with service.db.transaction() as connection:
        report = service.required(connection, db.imports, context.tenant_id, report_id)
        if report["source"] != "hades-report":
            raise DomainError(
                409,
                "REPORT_SOURCE_UNSUPPORTED",
                "Only imported Hades observations can be summarized",
            )
        previous = _previous(service, connection, context, route, key, body)
        if previous is not None:
            return previous
        if report["digest"] != expected_digest:
            raise DomainError(
                409,
                "REPORT_DIGEST_CHANGED",
                "The imported report differs from the requested snapshot",
            )
        if not report["observations"]:
            raise DomainError(
                409,
                "REPORT_WITHOUT_OBSERVATIONS",
                "There are no imported observations to summarize",
            )
        used = connection.execute(
            select(func.count())
            .select_from(db.ai_requests)
            .where(
                db.ai_requests.c.tenant_id == context.tenant_id,
                db.ai_requests.c.import_id == report_id,
                db.ai_requests.c.purpose == "report-summary",
            )
        ).scalar_one()
        if used >= service.settings.model_case_call_budget:
            raise DomainError(
                429, "MODEL_BUDGET_EXHAUSTED", "This report's summary budget is exhausted"
            )
        observations = [
            {
                "ref": f"obs-{index + 1}",
                "risk_tier": item["risk_tier"],
                "issue_count": len(item["issues"]),
            }
            for index, item in enumerate(report["observations"][:20])
        ]
        payload = {
            "report_id": report_id,
            "report_digest": report["digest"],
            "source_version": report["version"],
            "observations": observations,
            "scope": "Opaque local references and declared heuristic metadata only. No raw descriptions, tool names or code.",
        }
        request = _reserve(
            service,
            connection,
            context,
            purpose="report-summary",
            resource_id=report_id,
            import_id=report_id,
            route=route,
            key=key,
            body=body,
            payload=payload,
            active=service.provider,
        )
    tokens = None
    try:
        output, reported = service.provider.summarize(payload)
        tokens = _usage(reported)
        validated = (
            ReportSummary.model_validate_json(output)
            if isinstance(output, str)
            else ReportSummary.model_validate(output)
        )
        validated.verify(report_id, report["digest"], {item["ref"] for item in observations})
        return _complete(
            service,
            context,
            request,
            validated.model_dump(),
            tokens,
            {
                "coverage": {
                    "observations_supplied": len(observations),
                    "total_observations": len(report["observations"]),
                    "raw_text_sent": False,
                    "tool_names_sent": False,
                }
            },
        )
    except (ValidationError, ValueError, TypeError, DomainError) as error:
        raise _reject(service, context, request, error, tokens) from error


def check_provider(
    service: Service, context: PrincipalContext, allow_live: bool, key: str
) -> dict[str, Any]:
    context.require("security_admin")
    apply_runtime(service)
    if service.settings.model_provider == "gemini" and not allow_live:
        raise DomainError(
            400,
            "LIVE_CHECK_CONFIRMATION_REQUIRED",
            "Explicitly confirm one synthetic provider call",
        )
    route, body = "/ai/check", {"allow_live": allow_live}
    _expire(service, context)
    with service.db.transaction() as connection:
        previous = _previous(service, connection, context, route, key, body)
        if previous is not None:
            return previous
        request = _reserve(
            service,
            connection,
            context,
            purpose="provider-check",
            resource_id="provider",
            route=route,
            key=key,
            body=body,
            payload={"purpose": "synthetic provider check"},
            active=service.provider,
        )
    tokens = None
    try:
        output, reported = service.provider.check()
        tokens = _usage(reported)
        validated = (
            ProviderCheck.model_validate_json(output)
            if isinstance(output, str)
            else ProviderCheck.model_validate(output)
        )
        return _complete(
            service,
            context,
            request,
            validated.model_dump(),
            tokens,
            {
                "live": service.settings.model_provider == "gemini",
                "scope": "One synthetic provider request; no case evidence, scanner descriptions or tools",
            },
        )
    except (ValidationError, ValueError, TypeError, DomainError) as error:
        raise _reject(service, context, request, error, tokens) from error


def with_wording(
    service: Service,
    context: PrincipalContext,
    session_id: str,
    result: dict[str, Any],
    key: str | None = None,
) -> dict[str, Any]:
    apply_runtime(service)
    if result.get("route_mode") != "DECOY" or not service.settings.decoy_model_wording:
        return result
    route, key = f"/sessions/{session_id}/wording", key or uid()
    payload = {
        name: value
        for name, value in result.items()
        if name not in {"decoy_id", "wording", "wording_provider"}
    }
    body = {"result_digest": digest(payload)}
    reserve = (
        thinking_limits(service.settings.gemini_model)[1]
        if service.settings.model_provider == "gemini"
        else 0
    )
    units = len(canonical(payload)) + len(WORDING_INSTRUCTION.encode("utf-8")) + 128 + reserve + 512
    _expire(service, context)
    with service.db.transaction() as connection:
        session = service.owned_session(connection, context, session_id)
        if session["route_mode"] != "DECOY" or session["expires_at"] <= now():
            raise DomainError(
                403, "ENGAGEMENT_STOPPED", "Engagement stopped before wording generation"
            )
        previous = _previous(service, connection, context, route, key, body)
        if previous is not None:
            return previous
        decoy = service.required(connection, db.decoys, context.tenant_id, session["decoy_id"])
        if decoy["model_tokens"] + units > 8000:
            service.audit(
                connection,
                context,
                "decoy.wording_fallback",
                session_id,
                {"reason": "wording admission budget exhausted"},
            )
            value = {**result, "wording_fallback": "wording admission budget exhausted"}
            service.idempotent_put(
                connection, context, route, key, body, {"state": "succeeded", "value": value}
            )
            return value
        try:
            request = _reserve(
                service,
                connection,
                context,
                purpose="decoy-wording",
                resource_id=session_id,
                version=session["route_version"],
                decoy_id=decoy["id"],
                route=route,
                key=key,
                body=body,
                payload=payload,
                active=service.provider,
                budget_units=units,
            )
        except DomainError as error:
            if error.code not in {
                "MODEL_BUDGET_EXHAUSTED",
                "MODEL_CONCURRENCY_EXHAUSTED",
                "MODEL_NOT_CONFIGURED",
                "MODEL_EGRESS_NOT_APPROVED",
                "REQUEST_BUDGET_EXHAUSTED",
                "MODEL_CONTEXT_TOO_LARGE",
            }:
                raise
            service.audit(
                connection, context, "decoy.wording_fallback", session_id, {"reason": error.code}
            )
            value = {**result, "wording_fallback": error.code}
            service.idempotent_put(
                connection, context, route, key, body, {"state": "succeeded", "value": value}
            )
            return value
        connection.execute(
            update(db.decoys)
            .where(db.decoys.c.tenant_id == context.tenant_id, db.decoys.c.id == decoy["id"])
            .values(model_tokens=decoy["model_tokens"] + units)
        )
    tokens = None
    try:
        text, reported = service.provider.wording(payload)
        tokens = _usage(reported)
        validated = SyntheticWording(text=text)
        value = {
            **result,
            "wording": validated.text,
            "wording_provider": service.provider.name,
            "wording_request_id": request["id"],
            "wording_authority": "untrusted display-only text",
        }
        return _complete(
            service, context, request, {"text": validated.text}, tokens, cache_value=value
        )
    except (ValidationError, ValueError, TypeError, DomainError) as error:
        failure = _reject(service, context, request, error, tokens)
        value = {**result, "wording_fallback": "provider unavailable or invalid output"}
        with service.db.transaction() as connection:
            _verify_actor(service, connection, context, "decoy-wording")
            current = service.owned_session(connection, context, session_id)
            if (
                current["route_mode"] != "DECOY"
                or current["route_version"] != session["route_version"]
                or current["expires_at"] <= now()
            ):
                raise DomainError(
                    403, "ENGAGEMENT_STOPPED", "Engagement stopped during wording generation"
                ) from error
            service.audit(
                connection, context, "decoy.wording_fallback", session_id, {"reason": failure.code}
            )
            _set_idempotent(connection, context, request, {"state": "succeeded", "value": value})
        return value
