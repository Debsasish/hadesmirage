from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from mirage import db
from mirage.common import DomainError, now
from mirage.policy import subset


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class PrincipalContext:
    tenant_id: str
    principal_id: str
    roles: tuple[str, ...]
    kind: str
    source: str | None = None
    csrf: str | None = None
    credential_kind: str = "bearer"

    def require(self, *roles: str) -> None:
        if not set(roles).intersection(self.roles):
            raise DomainError(
                403, "ROLE_REQUIRED", "Your verified role cannot perform this operation"
            )


def verify_lineage(connection: Connection, principal: dict[str, Any]) -> None:
    seen: set[str] = set()
    current = principal
    while True:
        if current["id"] in seen or len(seen) > 3:
            raise DomainError(403, "INVALID_LINEAGE", "Delegation lineage is invalid")
        seen.add(current["id"])
        if current["status"] != "active" or current["expires_at"] <= now():
            raise DomainError(
                403, "IDENTITY_INACTIVE", "Identity or ancestor is expired or suspended"
            )
        if current["parent_id"] is None:
            return
        parent = db.row(connection, db.principals, principal["tenant_id"], current["parent_id"])
        if parent is None:
            raise DomainError(403, "MISSING_ANCESTOR", "Delegation ancestor unavailable")
        if (
            not subset(current["scopes"], parent["scopes"])
            or current["expires_at"] > parent["expires_at"]
        ):
            raise DomainError(
                403, "ANCESTOR_SCOPE_CHANGED", "Delegation exceeds its current ancestor scope"
            )
        current = parent


def authenticate(database: db.Database, token: str) -> PrincipalContext:
    with database.engine.connect() as connection:
        credential = (
            connection.execute(
                select(db.credentials).where(db.credentials.c.token_hash == token_hash(token))
            )
            .mappings()
            .first()
        )
        if not credential or credential["expires_at"] <= now():
            raise DomainError(
                401, "AUTHENTICATION_REQUIRED", "Sign in with a valid local credential"
            )
        principal = db.row(
            connection, db.principals, credential["tenant_id"], credential["principal_id"]
        )
        if principal is None:
            raise DomainError(401, "AUTHENTICATION_REQUIRED", "Identity unavailable")
        verify_lineage(connection, principal)
        return PrincipalContext(
            tenant_id=principal["tenant_id"],
            principal_id=principal["id"],
            roles=tuple(principal["roles"]),
            kind=principal["kind"],
            source=credential["source"],
            csrf=credential["csrf"],
            credential_kind=credential["kind"],
        )


def fixture_context(
    connection: Connection, identifier: str, tenant: str = "tenant-demo"
) -> PrincipalContext:
    principal = db.row(connection, db.principals, tenant, identifier)
    if principal is None:
        raise DomainError(404, "FIXTURE_UNAVAILABLE", "Laboratory identity not found")
    verify_lineage(connection, principal)
    return PrincipalContext(tenant, identifier, tuple(principal["roles"]), principal["kind"])
