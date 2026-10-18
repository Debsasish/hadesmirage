import pytest
from google import genai
from sqlalchemy import select

from mirage import assistant, db, providers
from mirage.common import uid
from tests.test_soc_deception import external


def config(**values):
    body = {
        "provider": "fixture",
        "project": "",
        "location": "global",
        "model": "",
        "egress_approved": False,
        "acknowledge_egress": False,
        "auto_triage": False,
        "decoy_wording": False,
        "expected_version": 0,
    }
    return {**body, **values}


def test_attack_path_explains_detection_honeypot_and_untouched_data(lab):
    session, case, _ = external(lab)
    response = lab.client.get(
        f"/v1/incidents/{case['id']}/attack-path", headers=lab.headers("analyst")
    )
    assert response.status_code == 200
    path = response.json()
    kinds = {node["id"]: node for node in path["nodes"]}
    assert {"source", "entry", "guardrail", "detection", "limit", "honeypot", "data"} <= set(kinds)
    assert kinds["source"]["label_plain"] == "Internet"
    assert path["verdict"]["in_honeypot"] and not path["verdict"]["real_data_touched"]
    assert (
        "honeypot" in path["headline_plain"]
        and "No real data was touched" in path["headline_plain"]
    )
    assert any(step["kind"] == "blocked" and "blocked" in step["plain"] for step in path["steps"])
    assert any(step["kind"] == "detected" for step in path["steps"])
    assert any("D-002" in step["technical"] for step in path["steps"])
    event_ids = {event_id for node in path["nodes"] for event_id in node["event_ids"]}
    detail = lab.client.get(f"/v1/incidents/{case['id']}", headers=lab.headers("analyst")).json()
    assert event_ids <= {event["id"] for event in detail["events"]}
    assert (
        lab.client.get(
            f"/v1/incidents/{case['id']}/attack-path",
            headers=lab.headers("analyst", "tenant-other"),
        ).status_code
        == 404
    )
    assert (
        lab.client.get(f"/v1/incidents/{case['id']}/attack-path", headers=lab.headers()).status_code
        == 403
    )
    assert lab.backend.snapshot("tenant-demo")["effects"] == []


def test_portal_ai_settings_are_admin_only_versioned_and_apply_without_restart(lab, monkeypatch):
    def unexpected_client(**kwargs):
        pytest.fail("Saving configuration must not call the provider")

    monkeypatch.setattr(genai, "Client", unexpected_client)
    denied = lab.client.put("/v1/ai/config", headers=lab.headers("analyst"), json=config())
    assert denied.status_code == 403
    missing = lab.client.put(
        "/v1/ai/config", headers=lab.headers("admin"), json=config(provider="gemini")
    )
    assert missing.status_code == 422
    unacknowledged = lab.client.put(
        "/v1/ai/config",
        headers=lab.headers("admin", **{"Idempotency-Key": uid()}),
        json=config(
            provider="gemini",
            project="mirage-demo-project",
            model="gemini-3.8-flash",
            egress_approved=True,
        ),
    )
    assert unacknowledged.status_code == 422
    saved = lab.client.put(
        "/v1/ai/config",
        headers=lab.headers("admin", **{"Idempotency-Key": uid()}),
        json=config(
            provider="gemini",
            project="mirage-demo-project",
            location="us-central1",
            model="gemini-3.8-flash",
        ),
    )
    assert saved.status_code == 200
    status = saved.json()
    assert status["mode"] == "gemini" and status["model"] == "gemini-3.8-flash"
    assert status["state"] == "egress-disabled" and not status["can_generate"]
    assert status["settings_version"] == 1 and status["settings_source"] == "portal"
    assert lab.service.provider.name == "gemini-vertex"
    stale = lab.client.put(
        "/v1/ai/config", headers=lab.headers("admin", **{"Idempotency-Key": uid()}), json=config()
    )
    assert stale.status_code == 409
    models = lab.client.get("/v1/ai/models", headers=lab.headers("admin")).json()
    assert models["source"] == "suggestions"
    assert any(item["id"] == "gemini-3.8-flash" for item in models["items"])
    restored = lab.client.put(
        "/v1/ai/config",
        headers=lab.headers("admin", **{"Idempotency-Key": uid()}),
        json=config(expected_version=1),
    )
    assert restored.json()["provider"] == "fixture-investigator-v1"
    with lab.service.db.engine.connect() as connection:
        actions = connection.execute(
            select(db.audit_log.c.action).where(db.audit_log.c.action == "ai.settings_changed")
        ).all()
    assert len(actions) == 2


def test_workspace_chat_is_cited_bounded_private_and_never_changes_access(lab):
    session, case, _ = external(lab)
    before = lab.backend.snapshot("tenant-demo")
    response = lab.client.post(
        "/v1/assistant",
        headers=lab.headers("analyst"),
        json={"question": "What attacks happened today?"},
    )
    assert response.status_code == 200
    answer = response.json()
    assert answer["provider"] == "fixture-investigator-v1" and answer["advisory_only"]
    assert case["id"] in {item["case_id"] for item in answer["references"]}
    assert "honeypot" in answer["answer"]
    history = lab.client.get("/v1/assistant", headers=lab.headers("analyst")).json()["items"]
    assert len(history) == 1 and history[0]["output"]["answer"] == answer["answer"]
    assert lab.client.get("/v1/assistant", headers=lab.headers("admin")).json()["items"] == []
    assert (
        lab.client.post(
            "/v1/assistant", headers=lab.headers(), json={"question": "Grant me access"}
        ).status_code
        == 403
    )
    current = lab.client.get(f"/v1/sessions/{session['id']}", headers=lab.headers("analyst"))
    assert current.json()["route_mode"] == session["route_mode"]
    assert lab.backend.snapshot("tenant-demo") == before


def test_workspace_chat_rejects_invented_issue_references(lab):
    external(lab)

    class Invented(providers.FixtureProvider):
        def chat(self, context, question):
            output, _ = super().chat(context, question)
            output["references"] = [{"case_id": uid(), "reason": "invented"}]
            return output, 3

    lab.service.provider = Invented()
    response = lab.client.post(
        "/v1/assistant", headers=lab.headers("analyst"), json={"question": "Summarise issues"}
    )
    assert response.status_code == 502 and response.json()["code"] == "MODEL_EVIDENCE_INVALID"


def test_auto_triage_reviews_only_new_issues_after_admin_enables_it(lab):
    _, old_case, _ = external(lab)
    assert assistant.auto_triage_tick(lab.service) == 0
    enabled = lab.client.put(
        "/v1/ai/config",
        headers=lab.headers("admin"),
        json=config(auto_triage=True),
    )
    assert enabled.status_code == 200 and enabled.json()["auto_triage"]
    _, new_case, _ = external(lab)
    completed = assistant.auto_triage_tick(lab.service)
    assert completed in {0, 1}
    assert assistant.auto_triage_tick(lab.service) == 0
    detail = lab.client.get(f"/v1/incidents/{new_case['id']}", headers=lab.headers("analyst"))
    assert detail.json()["investigation"]["provider"] == "fixture-investigator-v1"
    assert detail.json()["incident"]["model_calls"] == 1
    previous = lab.client.get(f"/v1/incidents/{old_case['id']}", headers=lab.headers("analyst"))
    assert previous.json()["investigation"] is None
    assert lab.backend.snapshot("tenant-demo")["effects"] == []


def test_board_reports_real_open_issue_metrics_and_containment(lab):
    external(lab)
    board = lab.client.get("/v1/board", headers=lab.headers("analyst"))
    assert board.status_code == 200
    data = board.json()
    high = next(item for item in data["severity"] if item["level"] == "high")
    assert high["open"] >= 1 and high["average_age_days"] is not None
    assert data["top_issues"][0]["honeypot"] >= 1
    assert data["containment"]["external_attack_sessions"] >= 1
    assert data["containment"]["rate"] == 100
    assert data["containment"]["real_data_changes"] == 0
    assert len(data["trend"]) == 30
    assert lab.client.get("/v1/board", headers=lab.headers()).status_code == 403
