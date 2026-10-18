from __future__ import annotations

import json
import os
import socket
import threading
import time
from importlib.metadata import version
from pathlib import Path

import httpx
import pytest
import uvicorn
from sqlalchemy import select

from mirage import ai, db, deception, providers
from mirage.backend import HttpBackend, create_backend_app, signature
from mirage.common import DomainError, canonical, now, uid
from mirage.config import Settings
from mirage.models import CaseQuestion, PortalRequest
from tests.test_guardrails import operation
from tests.test_soc_deception import external


@pytest.fixture
def http_backend(lab):
    app = create_backend_app(lab.settings)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    settings = lab.settings.model_copy(update={"backend_url": f"http://127.0.0.1:{port}"})
    backend = HttpBackend(settings)
    for _ in range(50):
        if backend.healthy():
            break
        time.sleep(0.05)
    else:
        raise AssertionError("Actual loopback backend did not become ready")
    original = lab.service.backend
    lab.service.backend = backend
    try:
        yield backend, app.state.ledger, port
    finally:
        lab.service.backend = original
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        assert not thread.is_alive()


def test_t10_actual_backend_origin_rejects_application_tokens_and_spoofed_service_headers(
    lab, http_backend
):
    backend, ledger, port = http_backend
    session = lab.session()
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
        denied = client.post(
            "/execute",
            json={"tenant_id": "tenant-demo"},
            headers=lab.headers(**{"X-Admin": "true"}),
        )
        assert denied.status_code == 403
        assert client.post("/snapshot", json={"tenant_id": "tenant-demo"}).status_code == 403
        assert client.get("/results/" + uid()).status_code == 403
    assert lab.service.invoke(lab.context(), operation(session["id"]), uid())[0] == 200
    assert ledger.snapshot("tenant-demo")["production_reads"] == 1
    assert (
        lab.client.post("/internal/backend/execute", headers=lab.headers(), json={}).status_code
        == 405
    )
    assert ledger.snapshot("tenant-demo")["production_reads"] == 1


def test_hmac_expiry_body_substitution_and_duplicate_json_fail_on_the_actual_socket(
    lab, http_backend
):
    _, ledger, port = http_backend
    timestamp = "1"
    body = canonical({"tenant_id": "tenant-demo"})
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
        response = client.post(
            "/snapshot",
            content=body,
            headers={
                "X-Mirage-Time": timestamp,
                "X-Mirage-Signature": signature(
                    lab.settings.backend_secret, "POST", "/snapshot", timestamp, body
                ),
            },
        )
        assert response.status_code == 403
        timestamp = str(int(time.time()))
        response = client.post(
            "/snapshot",
            content=canonical({"tenant_id": "tenant-other"}),
            headers={
                "X-Mirage-Time": timestamp,
                "X-Mirage-Signature": signature(
                    lab.settings.backend_secret, "POST", "/snapshot", timestamp, body
                ),
            },
        )
        assert response.status_code == 403
        assert (
            client.post(
                "/execute", content='{"a":1,"a":2}', headers={"Content-Type": "application/json"}
            ).status_code
            == 400
        )
        assert client.post("/execute", content=b"x" * 70000).status_code == 413
    assert ledger.snapshot("tenant-demo")["effects"] == []


def test_signed_backend_idempotency_is_independent_of_dispatcher(lab, http_backend):
    backend, ledger, _ = http_backend
    envelope = {
        "tenant_id": "tenant-demo",
        "principal_id": "agent-procurement",
        "execution_id": uid(),
        "invocation": operation(uid(), "payment.change_request").model_dump(exclude_none=True),
        "policy_version": "policy-demo-v1",
        "route_version": 1,
    }
    first = backend.execute(envelope)
    assert backend.execute(envelope) == first
    changed = json.loads(json.dumps(envelope))
    changed["invocation"]["arguments"]["proposed_account_ref"] = "synthetic-account-changed"
    with pytest.raises(DomainError):
        backend.execute(changed)
    assert ledger.snapshot("tenant-demo")["production_mutations"] == 1


def test_native_diversion_never_hits_the_real_http_backend_after_the_fence(lab, http_backend):
    _, ledger, _ = http_backend
    session, _, outcomes = external(lab)
    assert session["route_mode"] == "DECOY"
    assert outcomes[-1]["response"]["simulated"]
    assert ledger.snapshot("tenant-demo")["effects"] == []


@pytest.mark.parametrize(
    "provider_mode",
    ["fixture", pytest.param("gemini", marks=pytest.mark.live_ai, id="approved-live-gemini")],
)
def test_ai_workflows_cannot_dispatch_or_change_routes_on_actual_backend_http_path(
    lab, http_backend, provider_mode
):
    live: Settings | None = None
    if provider_mode == "gemini":
        live = Settings()
        assert (
            live.model_provider == "gemini"
            and live.model_egress_approved
            and (live.gemini_project or live.gemini_api_key)
            and live.gemini_model
        ), (
            "Configure an approved Gemini project (workload identity) or server API key, a model "
            "and egress before live verification"
        )
        assert int(os.environ.get("MIRAGE_LIVE_AI_CALL_LIMIT", "0")) >= 5, (
            "Approve at least five live generation calls for this isolated synthetic gate"
        )
        assert live.model_call_budget >= 5 and live.model_case_call_budget >= 2, (
            "The configured tenant/case budgets must also permit the five-call gate"
        )
        lab.settings.model_provider = "gemini"
        lab.settings.gemini_project = live.gemini_project
        lab.settings.gemini_api_key = live.gemini_api_key
        lab.settings.gemini_endpoint = live.gemini_endpoint
        lab.settings.gemini_model = live.gemini_model
        lab.settings.gemini_location = live.gemini_location
        lab.settings.model_egress_approved = True
        lab.settings.model_call_budget = 5
        lab.settings.model_case_call_budget = 2
        lab.settings.model_timeout_seconds = live.model_timeout_seconds
        lab.settings.model_input_bytes = live.model_input_bytes
        lab.service.provider = providers.GeminiProvider(lab.settings)
    _, ledger, _ = http_backend
    benign = lab.session()
    assert lab.service.invoke(lab.context(), operation(benign["id"]), uid())[0] == 200
    assert ledger.snapshot("tenant-demo")["production_reads"] == 1
    session, case, _ = external(lab)
    actor = lab.context("analyst")
    before = ledger.snapshot("tenant-demo")
    route = lab.client.get(f"/v1/sessions/{session['id']}", headers=lab.headers("analyst")).json()
    assert providers.investigate(lab.service, actor, case["id"])["advisory_only"]
    assert ai.case_analysis(
        lab.service,
        actor,
        case["id"],
        question=CaseQuestion(
            question="Can this recommendation change permissions?", expected_version=case["version"]
        ),
    )["advisory_only"]
    checked = ai.check_provider(lab.service, lab.context("admin"), provider_mode == "gemini", uid())
    assert checked["live"] is (provider_mode == "gemini")
    report = lab.client.post(
        "/v1/integrations/hades/import",
        headers=lab.headers("admin"),
        json={
            "source_version": "a" * 40,
            "tool_count": 1,
            "tools": [
                {"name": "synthetic.lookup", "risk_tier": "T2", "issues": ["Heuristic only"]}
            ],
        },
    ).json()
    assert ai.summarize_report(lab.service, actor, report["id"], report["digest"], uid())[
        "advisory_only"
    ]
    lab.settings.decoy_model_wording = True
    external_actor = lab.context("external-lab")
    result = deception.portal(
        lab.service, external_actor, PortalRequest(session_id=session["id"]), uid()
    )[1]
    wording = providers.with_wording(lab.service, external_actor, session["id"], result, uid())
    assert wording["simulated"] and "wording_fallback" not in wording
    assert wording["wording_provider"] == lab.service.provider.name
    assert ledger.snapshot("tenant-demo") == before
    current = lab.client.get(f"/v1/sessions/{session['id']}", headers=lab.headers("analyst")).json()
    assert (
        current["route_mode"] == route["route_mode"]
        and current["route_version"] == route["route_version"]
    )
    if provider_mode == "gemini":
        assert live is not None
        with lab.service.db.engine.connect() as connection:
            records = db.rows(connection, select(db.ai_requests))
        assert len(records) == 5 and all(record["state"] == "succeeded" for record in records)
        evidence = {
            "verified_at": now(),
            "profile": "P1-native / isolated synthetic test store",
            "provider": "gemini-vertex",
            "model": live.gemini_model,
            "region": live.gemini_location,
            "sdk_version": version("google-genai"),
            "call_ceiling": 5,
            "model_requests": [
                {
                    key: record[key]
                    for key in (
                        "id",
                        "purpose",
                        "state",
                        "tokens",
                        "context_digest",
                        "config_digest",
                        "duration_ms",
                    )
                }
                for record in records
            ],
            "actual_signed_backend_business_effect_delta": {"reads": 0, "mutations": 0},
            "case_route_unchanged": True,
            "scope": "Five actual model requests, schema/reference and no-authority checks; not detection accuracy, P3 or production readiness",
        }
        target = Path(__file__).resolve().parents[1] / ".local" / f"live-ai-{uid()}.json"
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"Live synthetic model evidence: {target}")
