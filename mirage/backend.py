from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from mirage.common import DomainError, canonical, digest, now
from mirage.config import Settings
from mirage.http_boundary import RequestBoundary
from mirage.models import Invocation


class Backend(Protocol):
    def execute(self, envelope: dict[str, Any]) -> dict[str, Any]: ...
    def result(self, execution_id: str) -> dict[str, Any] | None: ...
    def snapshot(self, tenant_id: str) -> dict[str, Any]: ...
    def healthy(self) -> bool: ...


class Ledger:
    """Independent synthetic backend ledger, never exposed by the control API."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS effects (
                    execution_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                    request_digest TEXT NOT NULL, tool TEXT NOT NULL,
                    result TEXT NOT NULL, mutated INTEGER NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS suppliers (
                    tenant_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL,
                    category TEXT NOT NULL, account_ref TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, id)
                );
            """)
            for tenant, label in (
                ("tenant-demo", "Northstar Components"),
                ("tenant-other", "Other Tenant Supply"),
            ):
                connection.execute(
                    "INSERT OR IGNORE INTO suppliers VALUES (?, ?, ?, ?, ?)",
                    (
                        tenant,
                        "demo-001",
                        label,
                        "Industrial components",
                        "synthetic-account-original",
                    ),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO suppliers VALUES (?, ?, ?, ?, ?)",
                    (
                        tenant,
                        "demo-002",
                        "Aurora Logistics",
                        "Logistics",
                        "synthetic-account-secondary",
                    ),
                )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def execute(self, envelope: dict[str, Any]) -> dict[str, Any]:
        operation = Invocation.model_validate(envelope["invocation"])
        tenant = envelope["tenant_id"]
        if tenant not in {"tenant-demo", "tenant-other"}:
            raise DomainError(403, "BACKEND_TENANT_DENIED", "Unknown backend tenant")
        if operation.tool not in {"supplier.lookup", "invoice.compare", "payment.change_request"}:
            raise DomainError(403, "BACKEND_TOOL_DENIED", "Backend operation is prohibited")
        execution_id = envelope["execution_id"]
        request_digest = digest(envelope)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT * FROM effects WHERE execution_id=?", (execution_id,)
            ).fetchone()
            if previous:
                if previous["tenant_id"] != tenant or previous["request_digest"] != request_digest:
                    raise DomainError(
                        409, "BACKEND_IDEMPOTENCY_CONFLICT", "Execution binding changed"
                    )
                return json.loads(previous["result"])
            identifier = operation.resource.split(":", 1)[1]
            if operation.tool == "invoice.compare":
                if identifier not in {"demo-001", "demo-002"}:
                    raise DomainError(404, "BACKEND_NOT_FOUND", "Synthetic record not found")
                result = {
                    "invoice_id": identifier,
                    "supplier_id": "demo-001",
                    "invoice_total_minor": 124500,
                    "purchase_order_total_minor": 124500,
                    "currency": "USD",
                    "comparison": "matched",
                    "synthetic": True,
                }
            else:
                supplier = connection.execute(
                    "SELECT id,name,category,account_ref FROM suppliers WHERE tenant_id=? AND id=?",
                    (tenant, identifier),
                ).fetchone()
                if not supplier:
                    raise DomainError(404, "BACKEND_NOT_FOUND", "Synthetic record not found")
                result = dict(supplier)
                result["synthetic"] = True
                if operation.tool == "payment.change_request":
                    connection.execute(
                        "UPDATE suppliers SET account_ref=? WHERE tenant_id=? AND id=?",
                        (operation.arguments.proposed_account_ref, tenant, identifier),
                    )
                    result["account_ref"] = operation.arguments.proposed_account_ref
                    result["change_recorded"] = True
            connection.execute(
                "INSERT INTO effects VALUES (?,?,?,?,?,?,?)",
                (
                    execution_id,
                    tenant,
                    request_digest,
                    operation.tool,
                    json.dumps(result),
                    int(operation.tool == "payment.change_request"),
                    now(),
                ),
            )
            return result

    def result(self, execution_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            result = connection.execute(
                "SELECT result FROM effects WHERE execution_id=?", (execution_id,)
            ).fetchone()
            return json.loads(result["result"]) if result else None

    def snapshot(self, tenant_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            records = connection.execute(
                "SELECT execution_id,tool,mutated,created_at FROM effects WHERE tenant_id=? ORDER BY created_at",
                (tenant_id,),
            ).fetchall()
            return {
                "production_reads": sum(not item["mutated"] for item in records),
                "production_mutations": sum(item["mutated"] for item in records),
                "effects": [dict(item) for item in records],
                "evidence_source": "independent synthetic backend ledger",
            }

    def healthy(self) -> bool:
        with self.connect() as connection:
            return connection.execute("SELECT 1").fetchone()[0] == 1


def signature(secret: str, method: str, path: str, timestamp: str, body: bytes) -> str:
    signed = method.encode() + b"\n" + path.encode() + b"\n" + timestamp.encode() + b"\n" + body
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


class HttpBackend:
    def __init__(self, settings: Settings) -> None:
        self.url = settings.backend_url
        self.secret = settings.backend_secret

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        raw = canonical(body) if body is not None else b""
        timestamp = str(int(time.time()))
        with httpx.Client(timeout=3, trust_env=False, follow_redirects=False) as client:
            response = client.request(
                method,
                self.url + path,
                content=raw,
                headers={
                    "Content-Type": "application/json",
                    "X-Mirage-Time": timestamp,
                    "X-Mirage-Signature": signature(self.secret, method, path, timestamp, raw),
                },
            )
        if response.status_code == 404 and path.startswith("/results/"):
            return None
        if response.status_code >= 400:
            raise DomainError(
                503, "BACKEND_REJECTED", "Synthetic backend rejected the signed operation"
            )
        return response.json()

    def execute(self, envelope: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/execute", envelope)

    def result(self, execution_id: str) -> dict[str, Any] | None:
        return self._request("GET", f"/results/{execution_id}")

    def snapshot(self, tenant_id: str) -> dict[str, Any]:
        return self._request("POST", "/snapshot", {"tenant_id": tenant_id})

    def healthy(self) -> bool:
        try:
            return bool(self._request("GET", "/health")["ready"])
        except (httpx.HTTPError, DomainError):
            return False


def create_backend_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.prepare()
    ledger = Ledger(settings.data_dir / "backend.sqlite3")
    app = FastAPI(title="Mirage synthetic backend", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ledger = ledger

    @app.middleware("http")
    async def service_auth(request: Request, call_next: Any) -> Any:
        timestamp = request.headers.get("X-Mirage-Time", "")
        try:
            valid_time = abs(time.time() - int(timestamp)) <= 15
        except ValueError:
            valid_time = False
        raw = await request.body()
        expected = signature(
            settings.backend_secret, request.method, request.url.path, timestamp, raw
        )
        supplied = request.headers.get("X-Mirage-Signature", "")
        if (
            not valid_time
            or len(raw) > settings.max_body_bytes
            or not re.fullmatch(r"[a-f0-9]{64}", supplied)
            or not hmac.compare_digest(expected, supplied)
        ):
            return JSONResponse(status_code=403, content={"code": "BACKEND_SERVICE_AUTH_REQUIRED"})
        return await call_next(request)

    @app.exception_handler(DomainError)
    async def backend_error(_request: Request, error: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status, content={"code": error.code, "message": error.message}
        )

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ready": ledger.healthy()}

    @app.post("/execute")
    def execute(envelope: dict[str, Any]) -> dict[str, Any]:
        required = {
            "tenant_id",
            "principal_id",
            "execution_id",
            "invocation",
            "policy_version",
            "route_version",
        }
        if set(envelope) != required:
            raise DomainError(422, "BACKEND_INVALID_ENVELOPE", "Invalid signed execution envelope")
        try:
            return ledger.execute(envelope)
        except (ValidationError, KeyError, TypeError) as error:
            raise DomainError(
                422, "BACKEND_INVALID_OPERATION", "Invalid backend operation"
            ) from error

    @app.get("/results/{execution_id}")
    def result(execution_id: str) -> dict[str, Any]:
        found = ledger.result(execution_id)
        if found is None:
            raise DomainError(404, "BACKEND_RESULT_ABSENT", "No recorded result")
        return found

    @app.post("/snapshot")
    def snapshot(body: dict[str, str]) -> dict[str, Any]:
        if set(body) != {"tenant_id"} or body["tenant_id"] not in {"tenant-demo", "tenant-other"}:
            raise DomainError(403, "BACKEND_TENANT_DENIED", "Invalid tenant")
        return ledger.snapshot(body["tenant_id"])

    app.add_middleware(RequestBoundary, max_bytes=settings.max_body_bytes)
    return app
