from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from sqlalchemy import update

from mirage import db
from mirage.auth import authenticate
from mirage.common import DomainError, after, canonical, uid
from mirage.models import ApprovalDecision, DelegationRequest, Invocation, Policy, Scope
from mirage.policy import evaluate
from mirage.seed import default_policy


def operation(session: str, tool: str = "supplier.lookup", **overrides: object) -> Invocation:
    value = {
        "tool": tool,
        "action": "read",
        "resource": "supplier:demo-001",
        "arguments": {"supplier_id": "demo-001"},
        "session_id": session,
    }
    if tool == "payment.change_request":
        value.update(
            action="propose_change",
            arguments={
                "supplier_id": "demo-001",
                "proposed_account_ref": "synthetic-account-updated",
            },
        )
    if tool == "customer.export":
        value.update(action="export", resource="customer:all", arguments={})
    value.update(overrides)
    return Invocation.model_validate(value)


def approved(lab):
    actor = lab.context()
    session = lab.session()
    op = operation(session["id"], "payment.change_request")
    approval = lab.service.request_approval(actor, op, uid())
    lab.service.decide_approval(
        lab.context("approver"),
        approval["id"],
        ApprovalDecision(decision="approve", expected_digest=approval["digest"]),
        uid(),
    )
    return actor, op.model_copy(update={"approval_id": approval["id"]}), approval


def test_t01_spoofed_headers_do_not_change_verified_identity(lab):
    session = lab.session("agent-audit")
    response = lab.client.post(
        "/v1/tools/invoke",
        json=operation(session["id"]).model_dump(exclude_none=True),
        headers=lab.headers(
            "agent-audit",
            **{
                "X-Tenant-ID": "tenant-other",
                "X-Principal-ID": "agent-procurement",
                "X-Admin": "true",
            },
        ),
    )
    assert response.status_code == 403
    assert lab.backend.snapshot("tenant-demo")["production_reads"] == 0
    assert lab.client.get("/v1/agents", headers={"X-Admin": "true"}).status_code == 401


def test_t02_allowed_lookup_has_independent_backend_effect(lab):
    session = lab.session()
    response = lab.client.post(
        "/v1/tools/invoke",
        json=operation(session["id"]).model_dump(exclude_none=True),
        headers=lab.headers(),
    )
    assert response.status_code == 200
    assert response.json()["result"]["name"] == "Northstar Components"
    assert lab.backend.snapshot("tenant-demo")["production_reads"] == 1
    assert lab.backend.snapshot("tenant-demo")["production_mutations"] == 0


def test_t03_prohibited_action_and_cross_tenant_session_have_no_effect(lab):
    session = lab.session()
    status, result = lab.service.invoke(
        lab.context(), operation(session["id"], "customer.export"), uid()
    )
    assert status == 403 and result["decision"] == "deny"
    foreign = lab.session(tenant="tenant-other")
    with pytest.raises(DomainError, match="not found"):
        lab.service.invoke(lab.context(), operation(foreign["id"]), uid())
    assert lab.backend.snapshot("tenant-demo")["effects"] == []
    assert lab.backend.snapshot("tenant-other")["effects"] == []


def test_deny_precedence_even_with_a_broad_allow(lab):
    document = default_policy()
    deny = copy.deepcopy(document["rules"][0])
    deny.update(id="explicit-read-deny", effect="deny")
    document["rules"].append(deny)
    with lab.service.db.engine.connect() as connection:
        principal = db.row(connection, db.principals, "tenant-demo", "agent-procurement")
    decision, reason = evaluate(Policy.model_validate(document), principal, operation(uid()))
    assert (decision, reason) == ("deny", "EXPLICIT_DENY")


def test_argument_validation_and_duplicate_json_reject_before_execution(lab):
    session = lab.session()
    value = operation(session["id"]).model_dump(exclude_none=True)
    value["arguments"]["url"] = "https://example.invalid"
    assert lab.client.post("/v1/tools/invoke", json=value, headers=lab.headers()).status_code == 422
    value = operation(session["id"]).model_dump(exclude_none=True)
    value["arguments"]["supplier_id"] = "demo-002"
    assert lab.client.post("/v1/tools/invoke", json=value, headers=lab.headers()).status_code == 422
    assert (
        lab.client.post(
            "/v1/tools/invoke",
            content='{"tool":"a","tool":"b"}',
            headers={**lab.headers(), "Content-Type": "application/json"},
        ).status_code
        == 400
    )
    assert lab.backend.snapshot("tenant-demo")["effects"] == []


def test_t05_unapproved_changed_replayed_and_expired_approval(lab):
    actor, op, approval = approved(lab)
    changed = op.model_copy(
        update={
            "arguments": op.arguments.model_copy(
                update={
                    "proposed_account_ref": "synthetic-account-substitution",
                }
            )
        }
    )
    status, _ = lab.service.invoke(actor, changed, uid())
    assert status == 403
    assert lab.backend.snapshot("tenant-demo")["production_mutations"] == 0
    key = uid()
    status, first = lab.service.invoke(actor, op, key)
    assert status == 200 and first["execution_state"] == "succeeded"
    assert lab.service.invoke(actor, op, key)[1] == first
    assert lab.service.invoke(actor, op, uid())[0] == 403
    assert lab.backend.snapshot("tenant-demo")["production_mutations"] == 1
    another = lab.service.request_approval(
        actor, Invocation.model_validate(op.model_dump(exclude={"approval_id"})), uid()
    )
    with lab.service.db.transaction() as connection:
        connection.execute(
            update(db.approvals)
            .where(db.approvals.c.id == another["id"])
            .values(
                status="approved",
                expires_at="2000-01-01T00:00:00.000000Z",
            )
        )
    assert (
        lab.service.invoke(actor, op.model_copy(update={"approval_id": another["id"]}), uid())[0]
        == 403
    )


def test_approval_request_rejects_existing_id_and_reviewer_is_separate(lab):
    actor, op, approval = approved(lab)
    assert (
        lab.client.post(
            "/v1/approvals", json=op.model_dump(exclude_none=True), headers=lab.headers()
        ).status_code
        == 422
    )
    fresh = lab.service.request_approval(
        actor,
        Invocation.model_validate(op.model_dump(exclude={"approval_id"})),
        uid(),
        requester="approver",
    )
    with pytest.raises(DomainError, match="separate reviewer"):
        lab.service.decide_approval(
            lab.context("approver"),
            fresh["id"],
            ApprovalDecision(decision="approve", expected_digest=fresh["digest"]),
            uid(),
        )


def test_t06_response_loss_keeps_unknown_and_reconciles_without_repeat(lab):
    actor, op, approval = approved(lab)
    original = lab.backend.execute

    def timeout_after_commit(envelope):
        original(envelope)
        raise httpx.ReadTimeout("Synthetic lost response")

    lab.backend.execute = timeout_after_commit
    key = uid()
    first = lab.service.invoke(actor, op, key)[1]
    assert first["execution_state"] == "unknown"
    assert lab.service.invoke(actor, op, key)[1]["execution_state"] == "unknown"
    final = lab.service.reconcile(lab.context("analyst"), first["execution_id"])
    assert final["execution_state"] == "succeeded"
    assert lab.backend.snapshot("tenant-demo")["production_mutations"] == 1


def test_t07_delegation_subset_expiry_and_ancestor_revocation(lab):
    actor = lab.context()
    invalid = DelegationRequest(
        child_id="agent-child",
        name="Child",
        expires_at=after(300),
        scopes=[{"tool": "customer.export", "action": "export", "resources": ["customer:all"]}],
    )
    assert lab.service.delegate(actor, invalid, uid())[0] == 403
    valid = invalid.model_copy(
        update={
            "scopes": [
                Scope(
                    tool="supplier.lookup",
                    action="read",
                    resources=["supplier:demo-001"],
                )
            ]
        }
    )
    status, result = lab.service.delegate(actor, valid, uid())
    assert status == 201
    child = authenticate(lab.service.db, result["credential"])
    session = lab.service.create_session(child)
    assert lab.service.invoke(child, operation(session["id"]), uid())[0] == 200
    with lab.service.db.transaction() as connection:
        connection.execute(
            update(db.principals)
            .where(
                db.principals.c.tenant_id == actor.tenant_id,
                db.principals.c.id == actor.principal_id,
            )
            .values(status="suspended")
        )
    with pytest.raises(DomainError, match="ancestor"):
        authenticate(lab.service.db, result["credential"])


def test_concurrent_approval_consumption_is_exactly_once(lab):
    actor, op, approval = approved(lab)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: lab.service.invoke(actor, op, uid())[0], range(4)))
    assert results.count(200) == 1 and results.count(403) == 3
    assert lab.backend.snapshot("tenant-demo")["production_mutations"] == 1


def test_browser_auth_csrf_and_role_gate(lab):
    response = lab.client.post(
        "/auth/login", json={"username": "analyst", "access_code": "test-local-access-code"}
    )
    assert response.status_code == 200
    csrf = response.json()["csrf"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert lab.client.get("/auth/me").json()["principal"]["roles"] == ["analyst"]
    assert lab.client.post("/auth/logout").status_code == 403
    assert (
        lab.client.post(
            "/auth/logout",
            headers={
                "X-CSRF-Token": csrf,
                "Origin": "http://127.0.0.1:8787",
            },
        ).status_code
        == 200
    )


def test_canonicalization_unicode_and_forbidden_numeric_values():
    assert canonical({"b": 1, "a": "e\u0301"}) == canonical({"a": "\u00e9", "b": 1})
    with pytest.raises(ValueError):
        canonical({"amount": float("nan")})
