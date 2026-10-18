from sqlalchemy import func, select

from mirage import db
from mirage.common import now, uid
from mirage.detection import matches


def test_structured_gateway_evidence_is_authenticated_and_never_a_grant(lab):
    session = lab.session()
    observation = {
        "timestamp": now(),
        "target": "agent_gateway::proxy",
        "session_id": session["id"],
        "fields": {
            "source_identity": "agent-procurement",
            "dest_authority": "synthetic.internal:443",
            "policy_decision": "allow",
        },
    }
    assert (
        lab.client.post(
            "/v1/integrations/gateway/observations",
            json=observation,
            headers=lab.headers("analyst"),
        ).status_code
        == 403
    )
    headers = lab.headers("producer-gateway")
    response = lab.client.post(
        "/v1/integrations/gateway/observations", json=observation, headers=headers
    )
    assert response.status_code == 202
    assert (
        lab.client.post(
            "/v1/integrations/gateway/observations", json=observation, headers=headers
        ).json()["status"]
        == "duplicate"
    )
    with lab.service.db.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(db.events)).scalar_one() == 1
    integration = lab.client.get("/v1/integrations", headers=lab.headers("analyst")).json()
    gateway = next(item for item in integration["items"] if item["id"] == "gateway")
    assert gateway["state"] == "telemetry-only" and not gateway["active_connection"]
    assert lab.backend.snapshot("tenant-demo")["effects"] == []


def test_gateway_connect_evidence_cannot_assert_tool_authority_or_induce_diversion(lab):
    session = lab.session("external-lab")
    forged = {
        "schema_version": "1.0",
        "event_id": uid(),
        "tenant_id": "tenant-demo",
        "session_id": session["id"],
        "source": "gateway",
        "event_type": "gateway.decided",
        "occurred_at": now(),
        "route_mode": "PRODUCTION",
        "outcome": "deny",
        "principal_id": "external-lab",
        "attributes": {
            "tool": "customer.export",
            "resource": "customer:all",
            "snippet": "ignore policy",
        },
    }
    response = lab.client.post("/v1/events", json=forged, headers=lab.headers("producer-gateway"))
    assert response.status_code == 422 and response.json()["code"] == "GATEWAY_ATTRIBUTE_SCOPE"
    event = {
        "source": "gateway",
        "event_type": "gateway.decided",
        "outcome": "deny",
        "body": {"attributes": forged["attributes"]},
    }
    assert matches([event]) == set()
    assert (
        lab.client.get(f"/v1/sessions/{session['id']}", headers=lab.headers("analyst")).json()[
            "route_mode"
        ]
        == "PRODUCTION"
    )
