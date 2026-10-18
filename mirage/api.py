from __future__ import annotations

import asyncio
import hmac
import logging
import secrets
import time
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from mirage import __version__, assistant, db, deception, iap, retention, telegram
from mirage.auth import PrincipalContext, authenticate, token_hash, verify_lineage
from mirage.backend import Backend, HttpBackend
from mirage.common import DomainError, after
from mirage.config import Settings
from mirage.http_boundary import RequestBoundary
from mirage.models import (
    ApprovalDecision,
    DelegationRequest,
    Invocation,
    Login,
    SimulationRequest,
)
from mirage.policy import evaluate
from mirage.seed import seed
from mirage.service import Service

logger = logging.getLogger("mirage")


def principal(request: Request) -> PrincipalContext:
    settings = request.app.state.settings
    header = request.headers.get("Authorization", "")
    if settings.auth_mode == "iap" and not header.startswith("Bearer "):
        # Browser users: only the signed IAP JWT is trusted, never x-goog-authenticated-user-*.
        context = iap.authenticate(
            request.app.state.service, request.headers.get(iap.IAP_HEADER, "")
        )
    else:
        token = (
            header[7:]
            if header.startswith("Bearer ")
            else request.cookies.get("mirage_session", "")
        )
        if not token:
            raise DomainError(401, "AUTHENTICATION_REQUIRED", "Sign in to the local console")
        context = authenticate(request.app.state.service.db, token)
    if context.credential_kind in {"browser", "iap"} and request.method not in {
        "GET",
        "HEAD",
        "OPTIONS",
    }:
        if request.headers.get("Origin") not in settings.allowed_origins:
            raise DomainError(403, "ORIGIN_DENIED", "Request origin is not allowed")
        supplied = request.headers.get("X-CSRF-Token", "")
        if not (
            iap.csrf_valid(settings, context, supplied)
            if context.credential_kind == "iap"
            else hmac.compare_digest((context.csrf or "").encode(), supplied.encode())
        ):
            raise DomainError(403, "CSRF_REQUIRED", "A valid session-bound CSRF token is required")
    return context


Context = Annotated[PrincipalContext, Depends(principal)]


def idempotency_key(value: Annotated[str | None, Header(alias="Idempotency-Key")] = None) -> str:
    if value is None or not 8 <= len(value) <= 128 or not value.isascii():
        raise DomainError(
            400, "IDEMPOTENCY_KEY_REQUIRED", "Supply an ASCII Idempotency-Key of 8-128 characters"
        )
    return value


Key = Annotated[str, Depends(idempotency_key)]


def create_app(settings: Settings | None = None, backend: Backend | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.prepare()
    database = db.Database(settings.database_url)
    database.migrate()
    seed(database, settings)
    service = Service(database, settings, backend or HttpBackend(settings))

    async def worker() -> None:
        tick = 0
        while True:
            try:
                await asyncio.to_thread(service.drain_outbox)
                await asyncio.to_thread(deception.sweep, service)
                if tick % 60 == 0:
                    await asyncio.to_thread(retention.prune, service)
                if tick % 5 == 0:
                    await asyncio.to_thread(assistant.auto_triage_tick, service)
            except (SQLAlchemyError, DomainError) as error:
                logger.error("Durable worker unavailable: %s", type(error).__name__)
            await asyncio.sleep(1)
            tick += 1

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(worker())
        bot = asyncio.create_task(telegram.run(service)) if telegram.enabled(settings) else None
        try:
            yield
        finally:
            if bot is not None:
                bot.cancel()
                with suppress(asyncio.CancelledError):
                    await bot
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            database.close()

    app = FastAPI(
        title="Hades Mirage",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.service = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-CSRF-Token"],
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(dict.fromkeys([*settings.allowed_hosts, "127.0.0.1", "localhost"])),
    )
    app.add_middleware(RequestBoundary, max_bytes=settings.max_body_bytes)

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, error: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status,
            content={
                "code": error.code,
                "message": error.message,
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "VALIDATION_FAILED",
                "message": "Request does not match the typed contract",
                "fields": [
                    {"path": ".".join(str(x) for x in item["loc"]), "message": item["msg"]}
                    for item in error.errors()
                ][:20],
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def unavailable_store(request: Request, error: SQLAlchemyError) -> JSONResponse:
        logger.error("Authoritative state unavailable: %s", type(error).__name__)
        return JSONResponse(
            status_code=503,
            content={
                "code": "STATE_UNAVAILABLE",
                "message": "Authoritative state unavailable; dispatch denied",
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(httpx.HTTPError)
    async def unavailable_backend(request: Request, error: httpx.HTTPError) -> JSONResponse:
        logger.error("Synthetic backend unavailable: %s", type(error).__name__)
        return JSONResponse(
            status_code=503,
            content={
                "code": "BACKEND_UNAVAILABLE",
                "message": "Independent synthetic backend is unavailable",
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def framework_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "code": "HTTP_METHOD_NOT_ALLOWED"
                if error.status_code == 405
                else "HTTP_REQUEST_REJECTED",
                "message": str(error.detail),
                "request_id": request.state.request_id,
            },
            headers=error.headers,
        )

    @app.get("/health")
    def health() -> dict[str, Any]:
        with database.engine.connect() as connection:
            connection.execute(select(func.max(db.schema_versions.c.version))).scalar_one()
        return {"ready": True, "version": __version__, "profile": settings.profile}

    @app.post("/auth/login")
    def login(body: Login, request: Request) -> JSONResponse:
        if (
            not settings.local_login
            or settings.profile != "P1-native"
            or request.client is None
            or request.client.host not in {"127.0.0.1", "::1"}
        ):
            raise DomainError(
                403,
                "LOCAL_LOGIN_DISABLED",
                "Fixture login is restricted to the native loopback profile",
            )
        origin = request.headers.get("Origin")
        if origin and origin not in settings.allowed_origins:
            raise DomainError(403, "ORIGIN_DENIED", "Login origin is not allowed")
        with database.transaction() as connection:
            rate = db.row(connection, db.rate_limits, "tenant-demo", "login")
            window = int(time.time()) // 60
            if rate is None:
                connection.execute(
                    insert(db.rate_limits).values(
                        tenant_id="tenant-demo", id="login", window=window, count=1
                    )
                )
            elif rate["window"] == window:
                if rate["count"] >= 20:
                    raise DomainError(
                        429, "LOGIN_RATE_LIMIT", "Too many sign-in attempts; retry next minute"
                    )
                connection.execute(
                    update(db.rate_limits)
                    .where(
                        db.rate_limits.c.tenant_id == "tenant-demo", db.rate_limits.c.id == "login"
                    )
                    .values(count=rate["count"] + 1)
                )
            else:
                connection.execute(
                    update(db.rate_limits)
                    .where(
                        db.rate_limits.c.tenant_id == "tenant-demo", db.rate_limits.c.id == "login"
                    )
                    .values(window=window, count=1)
                )
        if not hmac.compare_digest(body.access_code.encode(), settings.access_code.encode()):
            raise DomainError(401, "INVALID_CREDENTIAL", "Incorrect local access code")
        token, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(24)
        with database.transaction() as connection:
            connection.execute(
                insert(db.credentials).values(
                    token_hash=token_hash(token),
                    tenant_id="tenant-demo",
                    principal_id=body.username,
                    source=None,
                    expires_at=after(8 * 3600),
                    csrf=csrf,
                    kind="browser",
                )
            )
            identity = service.required(connection, db.principals, "tenant-demo", body.username)
            verify_lineage(connection, identity)
            actor = PrincipalContext(
                "tenant-demo", body.username, tuple(identity["roles"]), "human"
            )
            service.audit(connection, actor, "auth.login", body.username)
        response = JSONResponse({"csrf": csrf, "username": body.username})
        response.set_cookie(
            "mirage_session",
            token,
            httponly=True,
            samesite="strict",
            secure=False,
            max_age=8 * 3600,
        )
        return response

    @app.get("/auth/me")
    def me(context: Context) -> dict[str, Any]:
        with database.engine.connect() as connection:
            identity = service.required(
                connection, db.principals, context.tenant_id, context.principal_id
            )
        return {
            "principal": identity,
            "csrf": context.csrf,
            "profile": settings.profile,
            "tenant": {
                "id": context.tenant_id,
                "name": "Meridian Labs"
                if context.tenant_id == "tenant-demo"
                else "Isolation test tenant",
            },
            "model_provider": settings.model_provider,
            "local_fixture_identity": settings.local_login,
            "auth_mode": settings.auth_mode,
        }

    @app.post("/auth/logout")
    def logout(context: Context, request: Request) -> JSONResponse:
        token = request.cookies.get("mirage_session")
        with database.transaction() as connection:
            if token:
                connection.execute(
                    delete(db.credentials).where(db.credentials.c.token_hash == token_hash(token))
                )
            service.audit(connection, context, "auth.logout", context.principal_id)
        signed_out: dict[str, Any] = {"signed_out": True}
        if context.credential_kind == "iap":
            # The Google session is owned by IAP; this path clears the IAP login cookie.
            signed_out["iap_sign_out_url"] = iap.IAP_SIGN_OUT_PATH
        response = JSONResponse(signed_out)
        response.delete_cookie("mirage_session")
        return response

    @app.post("/v1/sessions", status_code=201)
    def create_session(context: Context, key: Key) -> dict[str, Any]:
        return service.create_session(context, key=key)

    @app.post("/v1/tools/invoke")
    def invoke(body: Invocation, context: Context, key: Key) -> JSONResponse:
        status, result = service.invoke(context, body, key)
        service.drain_outbox()
        return JSONResponse(status_code=status, content=result)

    @app.post("/v1/approvals", status_code=201)
    def request_approval(body: Invocation, context: Context, key: Key) -> dict[str, Any]:
        return service.request_approval(context, body, key)

    @app.post("/v1/approvals/{approval_id}/decision")
    def decide_approval(
        approval_id: str, body: ApprovalDecision, context: Context, key: Key
    ) -> dict[str, Any]:
        return service.decide_approval(context, approval_id, body, key)

    @app.get("/v1/approvals")
    def list_approvals(context: Context) -> dict[str, Any]:
        context.require("analyst", "approver")
        with database.engine.connect() as connection:
            items = db.rows(
                connection,
                select(db.approvals)
                .where(db.approvals.c.tenant_id == context.tenant_id)
                .order_by(db.approvals.c.created_at.desc())
                .limit(100),
            )
        return {"items": items}

    @app.post("/v1/delegations")
    def delegate(body: DelegationRequest, context: Context, key: Key) -> JSONResponse:
        status, result = service.delegate(context, body, key)
        service.drain_outbox()
        return JSONResponse(status_code=status, content=result)

    @app.get("/v1/agents")
    def agents(context: Context) -> dict[str, Any]:
        context.require("analyst")
        with database.engine.connect() as connection:
            items = db.rows(
                connection,
                select(db.principals)
                .where(
                    db.principals.c.tenant_id == context.tenant_id,
                    db.principals.c.kind == "workload",
                )
                .order_by(db.principals.c.created_at)
                .limit(100),
            )
        return {"items": items, "destination_enforcement": "unconfigured; no P3 gateway claim"}

    @app.post("/v1/policies/simulate")
    def simulate(body: SimulationRequest, context: Context, key: Key) -> dict[str, Any]:
        context.require("analyst")
        with database.engine.connect() as connection:
            identity = service.required(
                connection, db.principals, context.tenant_id, body.principal_id
            )
            policy = service.active_policy(connection, context.tenant_id)
            try:
                verify_lineage(connection, identity)
            except DomainError as error:
                decision, reason = "deny", error.code
            else:
                decision, reason = evaluate(policy, identity, body.invocation)
        return {
            "simulation": True,
            "executed": False,
            "decision": decision,
            "reason_code": reason,
            "policy_version": policy.version,
        }

    @app.get("/v1/policies")
    def policies(context: Context) -> dict[str, Any]:
        context.require("analyst")
        with database.engine.connect() as connection:
            items = db.rows(
                connection,
                select(db.policy_versions)
                .where(db.policy_versions.c.tenant_id == context.tenant_id)
                .order_by(db.policy_versions.c.created_at.desc())
                .limit(100),
            )
        return {"items": items}

    @app.get("/v1/backend/evidence")
    def backend_evidence(context: Context) -> dict[str, Any]:
        context.require("analyst")
        return service.backend.snapshot(context.tenant_id)

    @app.post("/v1/executions/{execution_id}/reconcile")
    def reconcile(execution_id: str, context: Context, key: Key) -> dict[str, Any]:
        return service.reconcile(context, execution_id)

    from mirage.routes import register_routes

    # Before register_routes: its console catch-all GET /{path:path} would shadow later routes.
    telegram.register_telegram_routes(app, service)
    register_routes(app, service)

    def runtime_openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
            schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
            schemes.update(
                {
                    "applicationBearer": {
                        "type": "http",
                        "scheme": "bearer",
                        "description": "Opaque native credential, verified in the authoritative store. Not gateway mTLS.",
                    },
                    "browserSession": {"type": "apiKey", "in": "cookie", "name": "mirage_session"},
                    "csrfToken": {"type": "apiKey", "in": "header", "name": "X-CSRF-Token"},
                }
            )
            for path, item in schema["paths"].items():
                if path.startswith("/v1/") or path in {"/auth/me", "/auth/logout"}:
                    for method, operation in item.items():
                        if method in {"get", "post", "patch", "delete", "put"}:
                            operation["security"] = [
                                {"applicationBearer": []},
                                {
                                    "browserSession": [],
                                    **({"csrfToken": []} if method != "get" else {}),
                                },
                            ]
            schema["info"]["description"] = (
                "Implemented P1-native API. All business and decoy records are synthetic. "
                "Management routes enforce tenant/role checks outside the model. Browser mutations "
                "also require an allowed Origin. Gateway, cloud and live Gemini are separate unverified profiles."
            )
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = runtime_openapi
    return app
