import json
from types import SimpleNamespace

import httpx
import pytest
import wasmtime
from google import genai
from google.oauth2.credentials import Credentials
from sqlalchemy import select

from mirage import ai, db, deception, providers
from mirage.common import DomainError, uid
from mirage.models import CaseQuestion, PortalRequest
from tests.test_soc_deception import external


def test_actual_wasm_fuel_and_memory_limits(lab):
    sandbox = lab.service.sandbox
    store = wasmtime.Store(sandbox.engine)
    store.set_fuel(10)
    infinite = wasmtime.Module(
        sandbox.engine, '(module (func (export "run") (loop $repeat (br $repeat))))'
    )
    instance = wasmtime.Instance(store, infinite, [])
    with pytest.raises(wasmtime.Trap):
        instance.exports(store)["run"](store)
    bounded = wasmtime.Store(sandbox.engine)
    bounded.set_fuel(100000)
    bounded.set_limits(memory_size=65536, memories=1, instances=1)
    template = wasmtime.Instance(bounded, sandbox.module, [])
    with pytest.raises(wasmtime.WasmtimeError):
        template.exports(bounded)["memory"].grow(bounded, 1)


def test_synthetic_invoice_and_supplier_are_coherent_in_both_variants(lab):
    for variant in (0, 1):
        supplier, state = lab.service.sandbox.respond(
            "supplier.lookup", {"requests": 0, "changes": 0}, variant
        )
        invoice, _state = lab.service.sandbox.respond("invoice.compare", state, variant)
        assert invoice["supplier_id"] == supplier["supplier_id"]
        assert invoice["synthetic"] and invoice["simulated"]


def test_gemini_sdk_request_shape_is_bounded_and_has_no_tools_or_secrets(lab, monkeypatch):
    _, case, _ = external(lab)
    captured = {}

    def generate(**kwargs):
        captured.update(kwargs)
        content = json.loads(kwargs["contents"])
        return SimpleNamespace(
            text=json.dumps(
                {
                    "case_id": content["case_id"],
                    "case_version": content["case_version"],
                    "summary": "A mocked SDK response, not a live provider result.",
                    "confidence": "medium",
                    "claims": [
                        {
                            "text": "Review the recorded denial.",
                            "evidence_event_ids": [content["evidence"][0]["event_id"]],
                        }
                    ],
                    "alternative_explanations": ["Authorized laboratory activity"],
                    "recommended_response": "review",
                }
            ),
            usage_metadata=SimpleNamespace(total_token_count=42),
        )

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.models = SimpleNamespace(generate_content=generate)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(genai, "Client", FakeClient)
    lab.settings.gemini_project = "synthetic-sdk-contract-test"
    lab.settings.gemini_model = "test-model-not-a-live-availability-claim"
    lab.settings.model_egress_approved = True
    result = providers.investigate(
        lab.service, lab.context("analyst"), case["id"], providers.GeminiProvider(lab.settings)
    )
    assert result["tokens"] == 42
    assert captured["config"].tools == []
    assert captured["config"].automatic_function_calling.disable is True
    assert captured["config"].candidate_count == 1
    assert captured["config"].max_output_tokens == 1800 + 2048
    assert captured["config"].thinking_config is None
    assert captured["client"]["enterprise"] is True
    assert captured["client"]["http_options"].retry_options.attempts == 1
    assert lab.settings.backend_secret not in captured["contents"]
    assert lab.settings.access_code not in captured["contents"]
    assert lab.backend.snapshot("tenant-demo")["effects"] == []


def test_unconfigured_gemini_never_attempts_a_provider_request(lab):
    with pytest.raises(DomainError) as error:
        providers.GeminiProvider(lab.settings)._generate("advisory", {}, {"type": "object"}, 128)
    assert error.value.code == "MODEL_NOT_CONFIGURED" and error.value.status == 503


@pytest.mark.parametrize("workflow", ["investigation", "question", "report", "check", "wording"])
def test_real_sdk_serialization_and_parsing_with_offline_transport(lab, monkeypatch, workflow):
    session, case, _ = external(lab)
    captured = []

    def respond(request):
        payload = json.loads(request.content)
        captured.append(payload)
        assert request.url.host == "aiplatform.googleapis.com"
        assert request.url.path.endswith(":generateContent")
        assert payload["generationConfig"]["candidateCount"] == 1
        assert payload.get("tools", []) == []
        assert payload["generationConfig"]["responseMimeType"] == "application/json"
        data = json.loads(payload["contents"][0]["parts"][0]["text"])
        if workflow == "report":
            result = providers.FixtureProvider().summarize(data)[0]
        elif workflow == "check":
            result = {"status": "mirage-provider-check-v1"}
        elif workflow == "wording":
            result = {"text": "This synthetic workspace recorded a simulated result."}
        else:
            result = {
                "case_id": data["case_id"],
                "case_version": data["case_version"],
                "confidence": "low",
                "claims": [
                    {
                        "text": "Review this recorded observation.",
                        "evidence_event_ids": [data["evidence"][0]["event_id"]],
                    }
                ],
            }
            if workflow == "question":
                result.update(
                    answer="Mocked SDK answer, not a live model result.",
                    limitations=["Offline transport test"],
                )
            else:
                result.update(
                    summary="Mocked SDK analysis, not a live model result.",
                    alternative_explanations=["Synthetic test"],
                    recommended_response="review",
                )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": json.dumps(result)}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"totalTokenCount": 42},
            },
        )

    original_client = genai.Client
    lab.settings.model_provider = "gemini"
    lab.settings.gemini_project = "synthetic-sdk-contract-test"
    lab.settings.gemini_model = "test-model-not-a-live-availability-claim"
    lab.settings.model_egress_approved = True
    lab.service.provider = providers.GeminiProvider(lab.settings)
    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as wire:

        def client(**kwargs):
            options = kwargs.pop("http_options")
            return original_client(
                **kwargs,
                credentials=Credentials(token="synthetic-offline-test-token"),
                http_options=options.model_copy(update={"httpx_client": wire}),
            )

        monkeypatch.setattr(genai, "Client", client)
        actor = lab.context("analyst")
        if workflow == "investigation":
            result = providers.investigate(lab.service, actor, case["id"])
        elif workflow == "question":
            result = ai.case_analysis(
                lab.service,
                actor,
                case["id"],
                question=CaseQuestion(
                    question="What does this evidence establish?", expected_version=case["version"]
                ),
            )
        elif workflow == "report":
            imported = lab.client.post(
                "/v1/integrations/hades/import",
                headers=lab.headers("admin"),
                json={
                    "source_version": "a" * 40,
                    "tool_count": 1,
                    "tools": [
                        {
                            "name": "synthetic.lookup",
                            "risk_tier": "T2",
                            "issues": ["Synthetic heuristic"],
                        }
                    ],
                },
            ).json()
            result = ai.summarize_report(
                lab.service, actor, imported["id"], imported["digest"], uid()
            )
        elif workflow == "check":
            result = ai.check_provider(lab.service, lab.context("admin"), True, uid())
        else:
            lab.settings.decoy_model_wording = True
            actor = lab.context("external-lab")
            synthetic = deception.portal(
                lab.service, actor, PortalRequest(session_id=session["id"]), uid()
            )[1]
            result = providers.with_wording(lab.service, actor, session["id"], synthetic, uid())
            assert result["wording_provider"] == "gemini-vertex"
    assert len(captured) == 1
    assert lab.settings.backend_secret not in json.dumps(captured)
    assert lab.settings.access_code not in json.dumps(captured)
    with lab.service.db.engine.connect() as connection:
        record = db.rows(connection, select(db.ai_requests))[0]
    assert record["state"] == "succeeded" and record["tokens"] == 42
    assert lab.backend.snapshot("tenant-demo")["effects"] == []


@pytest.mark.parametrize(
    "kind,code",
    [
        ("tool", "MODEL_TOOL_OUTPUT_REJECTED"),
        ("blocked", "MODEL_OUTPUT_INCOMPLETE"),
        ("empty", "MODEL_EMPTY_RESPONSE"),
        ("oversized", "MODEL_OUTPUT_TOO_LARGE"),
        ("usage", "MODEL_USAGE_INVALID"),
        ("unavailable", "MODEL_UNAVAILABLE"),
    ],
)
def test_sdk_rejects_unsafe_or_incomplete_responses_without_tools_or_effects(
    lab, monkeypatch, kind, code
):
    calls = []

    def respond(request):
        calls.append(str(request.url))
        if kind == "unavailable":
            return httpx.Response(
                503,
                json={
                    "error": {
                        "code": 503,
                        "status": "UNAVAILABLE",
                        "message": "Synthetic provider outage",
                    }
                },
            )
        parts = [{"text": '{"status":"mirage-provider-check-v1"}'}]
        if kind == "tool":
            parts = [{"functionCall": {"name": "unavailable_test_tool", "args": {}}}]
        if kind == "oversized":
            parts = [{"text": "x" * 40000}]
        return httpx.Response(
            200,
            json={
                "candidates": []
                if kind == "empty"
                else [
                    {
                        "content": {"role": "model", "parts": parts},
                        "finishReason": "SAFETY" if kind == "blocked" else "STOP",
                    }
                ],
                "usageMetadata": {"totalTokenCount": -1 if kind == "usage" else 42},
            },
        )

    original_client = genai.Client
    lab.settings.model_provider = "gemini"
    lab.settings.gemini_project = "synthetic-sdk-contract-test"
    lab.settings.gemini_model = "test-model-not-a-live-availability-claim"
    lab.settings.model_egress_approved = True
    lab.service.provider = providers.GeminiProvider(lab.settings)
    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as wire:

        def client(**kwargs):
            options = kwargs.pop("http_options")
            return original_client(
                **kwargs,
                credentials=Credentials(token="synthetic-offline-test-token"),
                http_options=options.model_copy(update={"httpx_client": wire}),
            )

        monkeypatch.setattr(genai, "Client", client)
        response = lab.client.post(
            "/v1/ai/check", headers=lab.headers("admin"), json={"allow_live": True}
        )
    assert (
        response.status_code == (503 if kind == "unavailable" else 502)
        and response.json()["code"] == code
    )
    assert len(calls) == 1
    assert not ai.status(lab.service, lab.context("analyst"))["live_check_passed"]
    assert lab.backend.snapshot("tenant-demo")["effects"] == []
