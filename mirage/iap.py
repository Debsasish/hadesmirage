"""Google Workspace sign-in through Identity-Aware Proxy (IAP) for the P2-cloud demo profile.

Only the signed ``x-goog-iap-jwt-assertion`` header is trusted. The unsigned
``x-goog-authenticated-user-*`` headers are never read: they can be forged if IAP is bypassed.
Roles come from operator configuration (``MIRAGE_IAP_ROLE_MAP``), never from the model.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from google.auth import exceptions as google_exceptions
from google.auth import transport
from google.oauth2 import id_token
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from mirage import db
from mirage.auth import PrincipalContext, verify_lineage
from mirage.common import DomainError, after, now
from mirage.config import Settings

IAP_HEADER = "x-goog-iap-jwt-assertion"
IAP_ISSUER = "https://cloud.google.com/iap"
IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key"
IAP_SIGN_OUT_PATH = "/?gcp-iap-mode=CLEAR_LOGIN_COOKIE"
KEY_CACHE_SECONDS = 300
KEY_REFRESH_FLOOR_SECONDS = 30
CLOCK_SKEW_SECONDS = 30
PRINCIPAL_TTL_SECONDS = 30 * 86400
MAX_ASSERTION_BYTES = 8192


class CachedKeyRequest(transport.Request):
    """google-auth transport that fetches only the IAP key document and caches it briefly."""

    def __init__(self) -> None:
        self.transport: Any = None
        self._lock = threading.Lock()
        self._response: Any = None
        self._expires = 0.0
        self._fetched = 0.0

    def clear(self) -> None:
        with self._lock:
            self._response, self._expires, self._fetched = None, 0.0, 0.0

    def refresh_if_unknown(self, key_id: str) -> None:
        response = self(IAP_CERTS_URL)
        try:
            known = key_id in json.loads(response.data.decode("utf-8"))
        except (AttributeError, ValueError, TypeError):
            known = False
        with self._lock:
            if not known and time.monotonic() - self._fetched >= KEY_REFRESH_FLOOR_SECONDS:
                self._response, self._expires = None, 0.0

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: Any = None,
        headers: Any = None,
        timeout: Any = None,
        **kwargs: Any,
    ) -> Any:
        if url != IAP_CERTS_URL or method != "GET" or body is not None:
            raise google_exceptions.TransportError("Only the IAP public-key document is fetched")
        with self._lock:
            if self._response is not None and time.monotonic() < self._expires:
                return self._response
        if self.transport is None:
            from google.auth.transport.requests import Request

            self.transport = Request()
        response = self.transport(IAP_CERTS_URL, method="GET", timeout=timeout or 5)
        if response.status == 200:
            with self._lock:
                self._response = response
                self._fetched = time.monotonic()
                self._expires = self._fetched + KEY_CACHE_SECONDS
        return response


KEYS = CachedKeyRequest()


def _invalid(message: str = "The IAP identity assertion could not be verified") -> DomainError:
    return DomainError(401, "IAP_ASSERTION_INVALID", message)


def _header(assertion: str) -> dict[str, Any]:
    try:
        segment = assertion.split(".")[0]
        value = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
    except (ValueError, TypeError, IndexError) as error:
        raise _invalid() from error
    if not isinstance(value, dict):
        raise _invalid()
    return value


def verify_assertion(settings: Settings, assertion: str) -> dict[str, Any]:
    """Verify an IAP JWT (ES256, issuer, audience, expiry) and the Workspace domain."""
    if settings.auth_mode != "iap" or not settings.iap_audience:
        raise DomainError(503, "IAP_NOT_CONFIGURED", "IAP sign-in is not configured; access denied")
    if not assertion:
        raise DomainError(
            401, "AUTHENTICATION_REQUIRED", "Sign in through Google Identity-Aware Proxy"
        )
    if len(assertion) > MAX_ASSERTION_BYTES or assertion.count(".") != 2:
        raise _invalid()
    header = _header(assertion)
    if header.get("alg") != "ES256" or not isinstance(header.get("kid"), str):
        raise _invalid("The IAP identity assertion must be ES256-signed with a key id")
    try:
        KEYS.refresh_if_unknown(header["kid"])
        claims = id_token.verify_token(
            assertion,
            KEYS,
            audience=settings.iap_audience,
            certs_url=IAP_CERTS_URL,
            clock_skew_in_seconds=CLOCK_SKEW_SECONDS,
        )
    except google_exceptions.TransportError as error:
        raise DomainError(
            503, "IAP_KEYS_UNAVAILABLE", "IAP verification keys are unavailable; access denied"
        ) from error
    except (google_exceptions.GoogleAuthError, ValueError, TypeError, KeyError) as error:
        raise _invalid() from error
    if claims.get("iss") != IAP_ISSUER or claims.get("aud") != settings.iap_audience:
        raise _invalid()
    email = claims.get("email")
    if not isinstance(email, str) or len(email) > 254 or email.count("@") != 1:
        raise _invalid("The IAP identity assertion has no usable email claim")
    email = email.strip().lower()
    domain = settings.iap_allowed_domain
    if domain and (claims.get("hd") != domain or email.rsplit("@", 1)[1] != domain):
        raise DomainError(
            403, "IAP_DOMAIN_DENIED", "Your Google account is not in the allowed Workspace domain"
        )
    return {**claims, "email": email}


def principal_id(email: str) -> str:
    return "iap-" + hashlib.sha256(email.encode()).hexdigest()[:16]


def roles_for(settings: Settings, email: str) -> list[str]:
    mapping = {key.strip().lower(): value for key, value in settings.iap_role_map.items()}
    if email in mapping:
        roles = sorted(set(mapping[email]))
    elif settings.iap_default_role == "analyst":
        roles = ["analyst"]
    else:
        roles = []
    if not roles:
        raise DomainError(
            403,
            "IAP_ROLE_UNMAPPED",
            "Your Google account has no Hades Mirage role; ask a security administrator",
        )
    return roles


def _current(current: dict[str, Any] | None, email: str, roles: list[str]) -> bool:
    return (
        current is not None
        and current["kind"] == "human"
        and current["name"] == email
        and sorted(current["roles"]) == roles
        and current["expires_at"] > after(86400)
    )


def ensure_principal(service: Any, settings: Settings, email: str) -> dict[str, Any]:
    """Create or refresh the human principal row so lineage, audit and approvals apply."""
    tenant, identifier = settings.iap_tenant, principal_id(email)
    roles = roles_for(settings, email)
    # Read-only fast path: the write transaction serializes the store, so take it only on change.
    with service.db.engine.connect() as connection:
        current = db.row(connection, db.principals, tenant, identifier)
        if _current(current, email, roles):
            verify_lineage(connection, current)
            return current
    actor = PrincipalContext(tenant, identifier, tuple(roles), "human", credential_kind="iap")
    for _attempt in range(2):
        try:
            with service.db.transaction() as connection:
                if not connection.execute(
                    select(db.tenants.c.id).where(db.tenants.c.id == tenant)
                ).first():
                    raise DomainError(503, "IAP_TENANT_UNAVAILABLE", "Configured tenant missing")
                current = db.row(connection, db.principals, tenant, identifier)
                if current is None:
                    connection.execute(
                        insert(db.principals).values(
                            tenant_id=tenant,
                            id=identifier,
                            name=email,
                            kind="human",
                            roles=roles,
                            status="active",
                            scopes=[],
                            parent_id=None,
                            root_id=identifier,
                            depth=0,
                            expires_at=after(PRINCIPAL_TTL_SECONDS),
                            identity_epoch=1,
                            owner="Google Identity-Aware Proxy",
                            created_at=now(),
                        )
                    )
                    service.audit(
                        connection,
                        actor,
                        "auth.iap_principal_created",
                        identifier,
                        {"roles": roles},
                    )
                elif current["kind"] != "human" or current["name"] != email:
                    raise DomainError(403, "IAP_IDENTITY_CONFLICT", "Identity mapping conflict")
                elif sorted(current["roles"]) != roles or current["expires_at"] <= after(86400):
                    changed = sorted(current["roles"]) != roles
                    connection.execute(
                        update(db.principals)
                        .where(
                            db.principals.c.tenant_id == tenant,
                            db.principals.c.id == identifier,
                        )
                        .values(
                            roles=roles,
                            expires_at=after(PRINCIPAL_TTL_SECONDS),
                            identity_epoch=current["identity_epoch"] + int(changed),
                        )
                    )
                    if changed:
                        service.audit(
                            connection,
                            actor,
                            "auth.iap_roles_updated",
                            identifier,
                            {"roles": roles},
                        )
                principal = db.row(connection, db.principals, tenant, identifier)
                verify_lineage(connection, principal)
                return principal
        except IntegrityError:
            continue
    raise DomainError(503, "IAP_PRINCIPAL_UNAVAILABLE", "Identity record could not be stored")


def _csrf(settings: Settings, tenant_id: str, identifier: str, day: str) -> str:
    key = hmac.new(settings.backend_secret.encode(), b"hades-mirage/iap-csrf/v1", "sha256").digest()
    return hmac.new(key, f"{tenant_id}|{identifier}|{day}".encode(), "sha256").hexdigest()


def csrf_token(settings: Settings, context: PrincipalContext, day: str | None = None) -> str:
    day = day or datetime.now(UTC).date().isoformat()
    return _csrf(settings, context.tenant_id, context.principal_id, day)


def csrf_valid(settings: Settings, context: PrincipalContext, supplied: str) -> bool:
    today = datetime.now(UTC).date()
    return any(
        hmac.compare_digest(
            csrf_token(settings, context, day.isoformat()).encode(), supplied.encode()
        )
        for day in (today, today - timedelta(days=1))
    )


def authenticate(service: Any, assertion: str) -> PrincipalContext:
    settings: Settings = service.settings
    claims = verify_assertion(settings, assertion)
    principal = ensure_principal(service, settings, claims["email"])
    context = PrincipalContext(
        tenant_id=principal["tenant_id"],
        principal_id=principal["id"],
        roles=tuple(principal["roles"]),
        kind=principal["kind"],
        credential_kind="iap",
    )
    return replace(context, csrf=csrf_token(settings, context))
