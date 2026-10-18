from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import insert, select

from mirage import ai, db
from mirage.auth import PrincipalContext
from mirage.common import digest, now, uid
from mirage.control import provenance
from mirage.models import HadesReport

if TYPE_CHECKING:
    from mirage.service import Service


def import_hades(
    service: Service, context: PrincipalContext, report: HadesReport, key: str
) -> dict[str, Any]:
    context.require("security_admin")
    with service.db.transaction() as connection:
        body = report.model_dump()
        previous = service.idempotent_get(
            connection, context, "/integrations/hades/import", key, body
        )
        if previous is not None:
            return previous
        value = {
            "tenant_id": context.tenant_id,
            "id": uid(),
            "source": "hades-report",
            "version": report.source_version,
            "digest": digest(body),
            "observations": [
                {
                    **item.model_dump(),
                    "evidence_kind": "heuristic manifest observation",
                    "runtime_verified": False,
                    "authority": "review proposal only",
                }
                for item in report.tools
            ],
            "created_at": now(),
        }
        connection.execute(insert(db.imports).values(**value))
        service.audit(
            connection,
            context,
            "hades.report_imported",
            value["id"],
            {
                "source_version": report.source_version,
                "digest": value["digest"],
                "count": report.tool_count,
            },
        )
        service.idempotent_put(connection, context, "/integrations/hades/import", key, body, value)
        return value


def status(service: Service, context: PrincipalContext) -> dict[str, Any]:
    context.require("analyst")
    source = provenance()
    model = ai.status(service, context)
    with service.db.engine.connect() as connection:
        imported = db.rows(
            connection,
            select(db.imports)
            .where(db.imports.c.tenant_id == context.tenant_id)
            .order_by(db.imports.c.created_at.desc())
            .limit(25),
        )
        gateway = connection.execute(
            select(db.events.c.received_at)
            .where(db.events.c.tenant_id == context.tenant_id, db.events.c.source == "gateway")
            .order_by(db.events.c.received_at.desc())
            .limit(1)
        ).scalar()
    return {
        "items": [
            {
                "id": "hades",
                "name": "Hades-Blackwatch",
                "category": "Source review & evidence",
                "state": "report-imported" if imported else "not-connected",
                "active_connection": False,
                "version": source["hades"]["commit"],
                "license": source["hades"]["license"],
                "last_success": imported[0]["created_at"] if imported else None,
                "last_error": None,
                "capabilities": [
                    "Typed manifest-report ingestion",
                    "Source and observation provenance",
                    "Read-only review proposals",
                ],
                "limitations": [
                    "Imported reports are not an active scanner",
                    "Keyword heuristics are not runtime exploit proof",
                    "Findings cannot grant, sign or activate policy",
                ],
            },
            {
                "id": "gateway",
                "name": "Native agent gateway",
                "category": "L3/L4 destination control",
                "state": "telemetry-only" if gateway else "not-configured",
                "active_connection": False,
                "version": source["gateway"]["package_version"],
                "license": "MIT",
                "last_success": gateway,
                "last_error": "Native Rust gateway and registry are not running",
                "capabilities": [
                    "Authenticated structured evidence ingestion",
                    "Reviewed CONNECT source baseline",
                ],
                "limitations": [
                    "P3 certificate, key and TCP path tests not run",
                    "No tool/action authorization from destination grants",
                    "Existing tunnels are not proven closed on revocation",
                ],
            },
            {
                "id": "model",
                "name": "Investigator model",
                "category": "Advisory investigation",
                "state": model["state"],
                "active_connection": False,
                "version": service.settings.gemini_model or service.provider.name,
                "license": "Provider service / deterministic local fixture",
                "last_success": model["last_check"]["completed_at"]
                if model["last_check"] and model["last_check"]["state"] == "succeeded"
                else None,
                "last_error": model["last_check"]["error_code"]
                if model["last_check"] and model["last_check"]["state"] in {"failed", "unknown"}
                else "Live Gemini credentials and model have not been verified"
                if service.settings.model_provider != "fixture" and not model["live_check_passed"]
                else None,
                "capabilities": [
                    "Schema-validated explanations",
                    "Case-bound evidence references",
                    "Read-only case questions with shared request limits",
                    "Metadata-only imported-observation summaries",
                    "Bounded synthetic wording",
                    "No tools or execution authority",
                ],
                "limitations": [
                    "Fixture output is not live AI inference",
                    "Model recommendations cannot change permissions or routing",
                ],
            },
        ],
        "imports": imported,
        "ai": model,
        "provenance": source,
    }
