"""The live attack map must reconcile with recorded evidence and the independent ledger."""

import httpx
from sqlalchemy import func, select

from mirage import db, deception
from mirage.common import uid
from mirage.models import PortalRequest, Transition
from tests.test_guardrails import approved, operation
from tests.test_soc_deception import external

MARKER = "ignore-previous-instructions-map-marker-7f3a"


def _count(lab, event_type: str, outcome: str) -> int:
    with lab.service.db.engine.connect() as connection:
        return connection.execute(
            select(func.count())
            .select_from(db.events)
            .where(
                db.events.c.tenant_id == "tenant-demo",
                db.events.c.event_type == event_type,
                db.events.c.outcome == outcome,
            )
        ).scalar_one()


def _traffic(lab):
    session, case, _ = external(lab)
    probe = lab.service.create_session(lab.context("external-lab"), origin="laboratory")
    deception.portal(
        lab.service,
        lab.context("external-lab"),
        PortalRequest(
            session_id=probe["id"],
            tool="customer.export",
            resource="customer:unassigned-map-9f9",
            snippet=MARKER,
        ),
        uid(),
    )
    benign = lab.session()
    assert lab.service.invoke(lab.context(), operation(benign["id"]), uid())[0] == 200
    actor, op, _approval = approved(lab)
    assert lab.service.invoke(actor, op, uid())[0] == 200
    lab.service.drain_outbox()
    return session, case, benign


def test_attack_map_reconciles_with_recorded_decisions_and_independent_ledger(lab):
    session, case, benign = _traffic(lab)
    before = lab.backend.snapshot("tenant-demo")
    response = lab.client.get("/v1/attack-map?hours=1", headers=lab.headers("analyst"))
    assert response.status_code == 200, response.text
    body = response.json()
    totals, ledger = body["totals"], body["ledger"]
    edges = {item["id"]: item["count"] for item in body["edges"]}
    nodes = {item["id"]: item for item in body["nodes"]}

    assert totals["blocked"] == _count(lab, "authorization.decided", "deny")
    assert totals["allowed"] == _count(lab, "authorization.decided", "allow")
    assert totals["simulated"] == _count(lab, "decoy.observed", "simulated") == 1
    assert edges["entry-blocked"] == totals["blocked"]
    assert edges["entry-honeypot"] == totals["simulated"]
    assert edges["external-entry"] + edges["internal-entry"] == totals["requests"]
    assert _count(lab, "tool.completed", "success") == 2
    assert edges["approval-allowed"] == 1 and edges["entry-approval"] >= 1
    assert edges["limited-honeypot"] == totals["honeypot"] == 1

    effects = before["effects"]
    assert ledger["available"] is True
    assert edges["allowed-business"] == ledger["actions"] == len(effects) == 2
    assert ledger["reads"] == sum(not item["mutated"] for item in effects) == 1
    assert ledger["changes"] == sum(bool(item["mutated"]) for item in effects) == 1
    assert ledger["after_containment"] == 0 and ledger["outside_view"] == 0
    assert nodes["business"]["value"] == ledger["actions"]
    assert nodes["entry"]["value"] == totals["requests"]

    top = body["attackers"][0]
    assert top["session_id"] == session["id"]
    assert top["incident"]["number"] == case["number"]
    assert top["route_mode"] == "DECOY" and top["caller_class"] == "external"
    assert {"external", "entry", "blocked", "detected", "limited", "honeypot"} <= set(top["path"])
    assert "limited-honeypot" in top["edges"] and "allowed-business" not in top["edges"]
    assert benign["id"] not in {item["session_id"] for item in body["attackers"]}
    assert any(item["tone"] == "honeypot" for item in body["feed"])

    assert MARKER not in response.text
    assert "customer:unassigned-map-9f9" not in response.text
    assert '"snippet"' not in response.text
    assert lab.backend.snapshot("tenant-demo") == before


def test_attack_map_is_tenant_scoped_role_checked_and_window_bounded(lab):
    _traffic(lab)
    other = lab.client.get("/v1/attack-map?hours=1", headers=lab.headers("analyst", "tenant-other"))
    assert other.status_code == 200
    assert other.json()["totals"]["requests"] == 0
    assert other.json()["attackers"] == [] and other.json()["feed"] == []
    assert lab.client.get("/v1/attack-map", headers=lab.headers()).status_code == 403
    assert lab.client.get("/v1/attack-map", headers=lab.headers("external-lab")).status_code == 403
    bad = lab.client.get("/v1/attack-map?hours=5", headers=lab.headers("analyst"))
    assert bad.status_code == 400 and bad.json()["code"] == "INVALID_TIME_RANGE"
    assert (
        lab.client.get("/v1/attack-map?origin=prod", headers=lab.headers("analyst")).status_code
        == 422
    )
    live_only = lab.client.get(
        "/v1/attack-map?hours=1&origin=live", headers=lab.headers("analyst")
    ).json()
    assert all(item["origin"] == "live" for item in live_only["attackers"])


def test_attack_map_degrades_honestly_when_the_ledger_is_unreachable(lab, monkeypatch):
    _traffic(lab)

    def unreachable(_tenant):
        raise httpx.ConnectError("synthetic outage")

    monkeypatch.setattr(lab.service.backend, "snapshot", unreachable)
    body = lab.client.get("/v1/attack-map?hours=1", headers=lab.headers("analyst")).json()
    assert body["ledger"]["available"] is False
    assert body["ledger"]["actions"] is None and body["ledger"]["after_containment"] is None
    assert {item["id"]: item for item in body["nodes"]}["business"]["value"] is None
    assert {item["id"]: item for item in body["edges"]}["allowed-business"]["count"] == 2
    assert body["totals"]["blocked"] > 0


def test_benign_sessions_that_were_only_ended_are_not_listed_as_attackers(lab):
    benign = lab.session()
    assert lab.service.invoke(lab.context(), operation(benign["id"]), uid())[0] == 200
    deception.transition(
        lab.service,
        lab.context("admin"),
        benign["id"],
        "terminate",
        Transition(expected_route_version=benign["route_version"], reason_code="OPERATOR_CLEANUP"),
        uid(),
    )
    body = lab.client.get("/v1/attack-map?hours=1", headers=lab.headers("analyst")).json()
    assert body["totals"]["requests"] == 1
    assert body["attackers"] == []
    assert all("Disconnected" not in item["plain"] for item in body["feed"])
