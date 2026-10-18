import pytest
from sqlalchemy import insert

from mirage import db
from mirage.auth import authenticate
from mirage.common import DomainError, after, uid
from mirage.models import DelegationRequest
from tests.test_guardrails import operation


def test_child_cannot_bypass_ancestor_request_budget(lab):
    request = DelegationRequest(
        child_id="agent-budget-child",
        name="Scoped budget child",
        expires_at=after(300),
        scopes=[{"tool": "supplier.lookup", "action": "read", "resources": ["supplier:demo-001"]}],
    )
    _, issued = lab.service.delegate(lab.context(), request, uid())
    child = authenticate(lab.service.db, issued["credential"])
    session = lab.service.create_session(child)
    import time

    with lab.service.db.transaction() as connection:
        connection.execute(
            insert(db.rate_limits).values(
                tenant_id="tenant-demo",
                id="agent-procurement:invocations",
                window=int(time.time()) // 60,
                count=240,
            )
        )
    with pytest.raises(DomainError) as error:
        lab.service.invoke(child, operation(session["id"]), uid())
    assert error.value.status == 429
    assert lab.backend.snapshot("tenant-demo")["effects"] == []


def test_resource_query_noise_is_not_counted_as_distinct_resources(lab):
    session = lab.session("external-lab")
    for invalid in ("supplier:unknown?noise=1", " supplier:unknown", "supplier:unknown/extra"):
        response = lab.client.post(
            "/v1/portal/request",
            json={
                "session_id": session["id"],
                "tool": "supplier.lookup",
                "resource": invalid,
            },
            headers=lab.headers("external-lab", **{"Idempotency-Key": uid()}),
        )
        assert response.status_code == 422
    assert lab.client.get("/v1/incidents", headers=lab.headers("analyst")).json()["items"] == []
