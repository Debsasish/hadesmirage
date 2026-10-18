"""Offline checks for API-key Gemini access and blocked-network Telegram diagnostics."""

import json
import re

import httpx
import pytest
from google import genai
from sqlalchemy import select

from mirage import ai, db, deception, providers, telegram
from mirage.common import uid
from mirage.models import PortalRequest
from tests.test_soc_deception import external

KEY = "synthetic-offline-api-key-0000000000000"
TOKEN = "123456789:TEST-fake-bot-token-0123456789abcdef"
CHECK = '{"status":"mirage-provider-check-v1"}'


def _api_key_lab(lab, monkeypatch, respond, model="test-model-not-a-live-availability-claim"):
    lab.settings.model_provider = "gemini"
    lab.settings.gemini_project = ""
    lab.settings.gemini_api_key = KEY
    lab.settings.gemini_model = model
    lab.settings.model_egress_approved = True
    lab.service.provider = providers.GeminiProvider(lab.settings)
    original = genai.Client
    wire = httpx.Client(transport=httpx.MockTransport(respond), trust_env=False)

    def client(**kwargs):
        options = kwargs.pop("http_options")
        return original(**kwargs, http_options=options.model_copy(update={"httpx_client": wire}))

    monkeypatch.setattr(genai, "Client", client)
    return wire


def _reply(text=CHECK, finish="STOP", visible=None):
    usage = {"totalTokenCount": 9}
    if visible is not None:
        usage["candidatesTokenCount"] = visible
    return httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish}
            ],
            "usageMetadata": usage,
        },
    )


def _check(lab):
    return lab.client.post(
        "/v1/ai/check",
        headers=lab.headers("admin", **{"Idempotency-Key": uid()}),
        json={"allow_live": True},
    )


@pytest.mark.parametrize(
    "model,thinking,reserve",
    [
        ("gemini-2.5-flash", {"thinking_budget": 0}, 0),
        ("gemini-2.5-pro", {"thinking_budget": 128}, 1024),
        ("gemini-3.8-flash", {"thinking_level": "LOW"}, 2048),
        ("gemini-flash-latest", {"thinking_level": "LOW"}, 2048),
        ("test-model-not-a-live-availability-claim", None, 2048),
    ],
)
def test_hidden_reasoning_is_capped_so_it_cannot_consume_the_answer_budget(
    lab, monkeypatch, model, thinking, reserve
):
    seen = []

    def respond(request):
        seen.append(json.loads(request.content)["generationConfig"])
        return _reply()

    with _api_key_lab(lab, monkeypatch, respond, model):
        response = _check(lab)
    assert response.status_code == 200, response.text
    wire = seen[0].get("thinkingConfig")
    # Google accepts either JSON field spelling; compare the values, not SDK casing.
    assert (
        None
        if wire is None
        else {re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower(): value for key, value in wire.items()}
    ) == thinking
    assert seen[0]["maxOutputTokens"] == 64 + reserve
    assert lab.backend.snapshot("tenant-demo")["effects"] == []


def test_truncated_or_oversized_answers_are_rejected_despite_the_reasoning_reserve(
    lab, monkeypatch
):
    replies = iter([_reply("Here is", finish="MAX_TOKENS"), _reply(visible=65)])

    with _api_key_lab(lab, monkeypatch, lambda request: next(replies), "gemini-3.8-flash"):
        truncated = _check(lab)
        oversized = _check(lab)
    assert truncated.status_code == 502
    assert truncated.json()["code"] == "MODEL_OUTPUT_INCOMPLETE"
    assert oversized.status_code == 502
    assert oversized.json()["code"] == "MODEL_OUTPUT_TOO_LARGE"
    assert not ai.status(lab.service, lab.context("analyst"))["live_check_passed"]
    assert lab.backend.snapshot("tenant-demo")["effects"] == []


def test_client_timeout_is_actionable_and_changes_nothing(lab, monkeypatch):
    def respond(request):
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    with _api_key_lab(lab, monkeypatch, respond, "gemini-3.8-flash"):
        response = _check(lab)
    assert response.status_code == 503
    assert response.json()["code"] == "MODEL_TIMEOUT"
    assert "time limit" in response.json()["message"]
    assert lab.backend.snapshot("tenant-demo")["effects"] == []


def test_wording_admission_counts_the_reasoning_reserve(lab, monkeypatch):
    session, _, _ = external(lab)
    lab.settings.decoy_model_wording = True
    wording = json.dumps({"text": "This synthetic workspace recorded a simulated result."})

    with _api_key_lab(lab, monkeypatch, lambda request: _reply(wording), "gemini-2.5-flash"):
        actor = lab.context("external-lab")
        result = deception.portal(
            lab.service, actor, PortalRequest(session_id=session["id"]), uid()
        )[1]
        first = providers.with_wording(lab.service, actor, session["id"], result, uid())
        lab.settings.gemini_model = "gemini-3.8-flash"
        second = providers.with_wording(lab.service, actor, session["id"], result, uid())
    assert first["wording_provider"] == second["wording_provider"] == "gemini-vertex"
    with lab.service.db.engine.connect() as connection:
        units = sorted(
            connection.execute(
                select(db.ai_requests.c.budget_units).where(
                    db.ai_requests.c.purpose == "decoy-wording"
                )
            ).scalars()
        )
    assert units[1] - units[0] == 2048
    assert lab.backend.snapshot("tenant-demo")["effects"] == []


def test_api_key_uses_developer_endpoint_and_keeps_the_key_out_of_content(lab, monkeypatch):
    seen = []

    def respond(request):
        seen.append(request)
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.path.endswith(":generateContent")
        assert request.headers["x-goog-api-key"] == KEY
        assert KEY not in str(request.url)
        assert KEY.encode() not in request.content
        payload = json.loads(request.content)
        assert payload.get("tools", []) == []
        assert payload["generationConfig"]["candidateCount"] == 1
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": '{"status":"mirage-provider-check-v1"}'}],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"totalTokenCount": 9},
            },
        )

    with _api_key_lab(lab, monkeypatch, respond):
        response = lab.client.post(
            "/v1/ai/check", headers=lab.headers("admin"), json={"allow_live": True}
        )
        status = lab.client.get("/v1/ai", headers=lab.headers("admin"))
    assert response.status_code == 200, response.text
    assert len(seen) == 1
    assert status.status_code == 200
    body = status.json()
    assert body["credential"] == "api-key" and body["api_key_configured"] is True
    assert body["endpoint"] == "Gemini API (AI Studio)"
    assert KEY not in status.text and KEY not in response.text
    assert lab.backend.snapshot("tenant-demo")["effects"] == []


@pytest.mark.parametrize(
    "code,expected,phrase",
    [
        (402, "MODEL_BILLING_REQUIRED", "prepaid credits"),
        (403, "MODEL_KEY_REJECTED", "rejected"),
        (404, "MODEL_NOT_AVAILABLE", "not available"),
        (429, "MODEL_RATE_LIMITED", "rate limit"),
        (400, "MODEL_REQUEST_UNSUPPORTED", "structured JSON"),
        (504, "MODEL_TIMEOUT", "time limit"),
    ],
)
def test_provider_errors_are_actionable_and_change_nothing(
    lab, monkeypatch, code, expected, phrase
):
    calls = []

    def respond(request):
        calls.append(request.url.host)
        return httpx.Response(
            code,
            json={"error": {"code": code, "status": "SYNTHETIC", "message": f"{KEY} upstream"}},
        )

    with _api_key_lab(lab, monkeypatch, respond):
        response = lab.client.post(
            "/v1/ai/check", headers=lab.headers("admin"), json={"allow_live": True}
        )
    assert response.status_code == 503
    assert response.json()["code"] == expected
    assert phrase in response.json()["message"]
    assert KEY not in response.text
    assert calls == ["generativelanguage.googleapis.com"]
    assert not ai.status(lab.service, lab.context("analyst"))["live_check_passed"]
    assert lab.backend.snapshot("tenant-demo")["effects"] == []


def test_api_key_lets_admins_save_gemini_without_a_project(lab):
    lab.settings.gemini_api_key = KEY
    saved = lab.client.put(
        "/v1/ai/config",
        headers=lab.headers("admin", **{"Idempotency-Key": uid()}),
        json={
            "provider": "gemini",
            "project": "",
            "location": "global",
            "model": "gemini-2.5-flash",
            "egress_approved": False,
            "acknowledge_egress": False,
            "auto_triage": False,
            "decoy_wording": False,
            "expected_version": 0,
        },
    )
    assert saved.status_code == 200, saved.text
    lab.settings.gemini_api_key = ""
    refused = lab.client.put(
        "/v1/ai/config",
        headers=lab.headers("admin", **{"Idempotency-Key": uid()}),
        json={
            "provider": "gemini",
            "project": "",
            "location": "global",
            "model": "gemini-2.5-flash",
            "egress_approved": False,
            "acknowledge_egress": False,
            "auto_triage": False,
            "decoy_wording": False,
            "expected_version": 1,
        },
    )
    assert refused.status_code == 422
    assert refused.json()["code"] == "MODEL_CREDENTIAL_REQUIRED"


def test_telegram_gateway_redirect_is_reported_as_a_blocked_network(lab, monkeypatch):
    seen = []

    def redirect(request):
        seen.append(request.url.host)
        return httpx.Response(303, headers={"Location": "https://block.example.invalid/"})

    monkeypatch.setattr(telegram, "TRANSPORT", httpx.MockTransport(redirect))
    monkeypatch.setattr(lab.settings, "telegram_mode", "polling")
    monkeypatch.setattr(lab.settings, "telegram_bot_token", TOKEN)
    with pytest.raises(telegram.TelegramError) as error:
        telegram.BotApi(lab.settings).call("getMe", {})
    assert "blocked on this network" in error.value.reason
    assert TOKEN not in str(error.value)
    assert seen == ["api.telegram.org"]
