from __future__ import annotations

from typing import Any

from mirage.common import digest
from mirage.models import Invocation, Policy

TOOL_CATALOGUE = [
    {
        "tool": "supplier.lookup",
        "action": "read",
        "resource": "supplier:demo-001",
        "risk": "read-only",
    },
    {
        "tool": "invoice.compare",
        "action": "analyze",
        "resource": "invoice:demo-001",
        "risk": "read-only",
    },
    {
        "tool": "payment.change_request",
        "action": "propose_change",
        "resource": "supplier:demo-001",
        "risk": "approval",
    },
    {"tool": "customer.export", "action": "export", "resource": "customer:all", "risk": "denied"},
    {
        "tool": "infrastructure.delete",
        "action": "delete",
        "resource": "infrastructure:cluster",
        "risk": "denied",
    },
]


def action_digest(tenant: str, principal: str, invocation: Invocation, policy_version: str) -> str:
    return digest(
        {
            "canonicalization": "nfc-json-v1",
            "tenant_id": tenant,
            "principal_id": principal,
            "tool": invocation.tool,
            "action": invocation.action,
            "resource": invocation.resource,
            "arguments": invocation.arguments.model_dump(exclude_none=True),
            "session_id": invocation.session_id,
            "policy_version": policy_version,
        }
    )


def scope_contains(scopes: list[dict[str, Any]], invocation: Invocation) -> bool:
    return any(
        item["tool"] == invocation.tool
        and item["action"] == invocation.action
        and invocation.resource in item["resources"]
        for item in scopes
    )


def subset(child: list[dict[str, Any]], parent: list[dict[str, Any]]) -> bool:
    return all(
        any(
            item["tool"] == allowed["tool"]
            and item["action"] == allowed["action"]
            and set(item["resources"]) <= set(allowed["resources"])
            for allowed in parent
        )
        for item in child
    )


def evaluate(policy: Policy, principal: dict[str, Any], invocation: Invocation) -> tuple[str, str]:
    matches = [
        rule
        for rule in policy.rules
        if principal["root_id"] in rule.principal_ids
        and rule.tool == invocation.tool
        and invocation.action in rule.actions
        and invocation.resource.startswith(rule.resource_prefix)
    ]
    if any(rule.effect == "deny" for rule in matches):
        return "deny", "EXPLICIT_DENY"
    allows = [rule for rule in matches if rule.effect == "allow"]
    if not allows:
        return "deny", "NO_ALLOW_RULE"
    if not scope_contains(principal["scopes"], invocation):
        return "deny", "RESOURCE_OUT_OF_SCOPE"
    if any(rule.approval_required for rule in allows):
        return "require_approval", "EXACT_APPROVAL_REQUIRED"
    return "allow", "SCOPED_ALLOW"
