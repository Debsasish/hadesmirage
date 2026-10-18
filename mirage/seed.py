from __future__ import annotations

import json
import os
import secrets
from typing import Any

from sqlalchemy import insert, select

from mirage import db
from mirage.auth import token_hash
from mirage.common import after, digest, now
from mirage.config import Settings


def default_policy() -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    for identifier, tool, action, prefix, approved, identities in (
        (
            "supplier-read",
            "supplier.lookup",
            "read",
            "supplier:demo-",
            False,
            ["agent-procurement", "agent-audit", "external-lab"],
        ),
        (
            "invoice-compare",
            "invoice.compare",
            "analyze",
            "invoice:demo-",
            False,
            ["agent-procurement", "agent-audit", "external-lab"],
        ),
        (
            "payment-change",
            "payment.change_request",
            "propose_change",
            "supplier:demo-",
            True,
            ["agent-procurement"],
        ),
        (
            "export-deny",
            "customer.export",
            "export",
            "customer:",
            False,
            ["agent-procurement", "agent-audit", "external-lab"],
        ),
        (
            "delete-deny",
            "infrastructure.delete",
            "delete",
            "infrastructure:",
            False,
            ["agent-procurement", "agent-audit", "external-lab"],
        ),
    ):
        rules.append(
            {
                "id": identifier,
                "effect": "deny" if identifier.endswith("-deny") else "allow",
                "principal_ids": identities,
                "tool": tool,
                "actions": [action],
                "resource_prefix": prefix,
                "approval_required": approved,
            }
        )
    return {
        "schema_version": "1.0",
        "policy_id": "procurement-demo",
        "version": "policy-demo-v1",
        "default_effect": "deny",
        "rules": rules,
    }


def seed(database: db.Database, settings: Settings) -> None:
    path = settings.data_dir / "fixture-credentials.json"
    tokens = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    expiry = after(30 * 86400)
    read_scope = [
        {
            "tool": "supplier.lookup",
            "action": "read",
            "resources": ["supplier:demo-001", "supplier:demo-002"],
        },
        {
            "tool": "invoice.compare",
            "action": "analyze",
            "resources": ["invoice:demo-001", "invoice:demo-002"],
        },
    ]
    with database.transaction() as connection:
        for tenant, name in (
            ("tenant-demo", "Meridian Labs"),
            ("tenant-other", "Isolation test tenant"),
        ):
            if connection.execute(select(db.tenants).where(db.tenants.c.id == tenant)).first():
                continue
            connection.execute(insert(db.tenants).values(id=tenant, name=name))
            definitions = [
                ("analyst", "Jordan Lee", "human", ["analyst"], []),
                ("admin", "Alex Morgan", "human", ["analyst", "security_admin"], []),
                ("approver", "Sam Rivera", "human", ["analyst", "approver"], []),
                (
                    "agent-procurement",
                    "Procurement assistant",
                    "workload",
                    ["workload"],
                    read_scope
                    + [
                        {
                            "tool": "payment.change_request",
                            "action": "propose_change",
                            "resources": ["supplier:demo-001"],
                        }
                    ],
                ),
                ("agent-audit", "Invoice review agent", "workload", ["workload"], read_scope[1:]),
                (
                    "external-lab",
                    "External laboratory client",
                    "external",
                    ["external"],
                    read_scope[:1],
                ),
                (
                    "producer-gateway",
                    "Gateway evidence producer",
                    "service",
                    ["event_producer"],
                    [],
                ),
            ]
            for identifier, label, kind, roles, scopes in definitions:
                connection.execute(
                    insert(db.principals).values(
                        tenant_id=tenant,
                        id=identifier,
                        name=label,
                        kind=kind,
                        roles=roles,
                        status="active",
                        scopes=scopes,
                        parent_id=None,
                        root_id=identifier,
                        depth=0,
                        expires_at=expiry,
                        identity_epoch=1,
                        owner="Platform security",
                        created_at=now(),
                    )
                )
                token = secrets.token_urlsafe(40)
                tokens[f"{tenant}/{identifier}"] = token
                connection.execute(
                    insert(db.credentials).values(
                        token_hash=token_hash(token),
                        tenant_id=tenant,
                        principal_id=identifier,
                        source="gateway" if identifier == "producer-gateway" else None,
                        expires_at=expiry,
                        csrf=None,
                        kind="bearer",
                    )
                )
            policy = default_policy()
            connection.execute(
                insert(db.policy_versions).values(
                    tenant_id=tenant,
                    id=policy["version"],
                    version=policy["version"],
                    digest=digest(policy),
                    status="active",
                    document=policy,
                    created_by="bootstrap-engineer",
                    reviewed_by="bootstrap-reviewer",
                    tested=True,
                    created_at=now(),
                )
            )
            connection.execute(
                insert(db.runtime).values(
                    tenant_id=tenant,
                    active_policy_id=policy["version"],
                    engagements_enabled=True,
                    model_calls=0,
                    model_tokens=0,
                )
            )
    path.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
    os.chmod(path, 0o600)
