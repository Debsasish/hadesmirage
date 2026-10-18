"""Measure frozen fixtures through actual native HTTP API and backend sockets."""

from __future__ import annotations

import json
import math
import platform
import socket
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn

from mirage import control, db
from mirage.api import create_app
from mirage.backend import HttpBackend, create_backend_app
from mirage.common import digest, now, uid
from mirage.config import Settings
from mirage.models import Invocation
from mirage.policy import evaluate

ROOT = Path(__file__).resolve().parents[1]


def server(app: Any) -> tuple[uvicorn.Server, threading.Thread, socket.socket, int]:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    runtime = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=runtime.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    return runtime, thread, listener, port


def percentiles(samples: list[float]) -> dict[str, Any]:
    ordered = sorted(samples)
    return {
        "sample_count": len(ordered),
        **{
            f"p{value}_ms": round(
                ordered[min(len(ordered) - 1, math.ceil(value / 100 * len(ordered)) - 1)], 4
            )
            for value in (50, 95, 99)
        },
    }


def main() -> None:
    dataset = json.loads((ROOT / "tests" / "fixtures" / "evaluation-v1.json").read_text())
    directory = ROOT / ".local" / "evaluation-runs" / uid()
    directory.mkdir(parents=True)
    settings = Settings(
        _env_file=None,
        data_dir=directory,
        profile="P1-native",
        local_login=True,
        database_url="",
        backend_url="",
        backend_secret="",
        access_code="",
        model_provider="fixture",
        model_egress_approved=False,
        decoy_model_wording=False,
        gemini_project="",
        gemini_model="",
        gemini_location="global",
    )
    settings.prepare()
    running = []
    outcomes = []
    policy_samples = []
    request_samples = []
    try:
        backend_runtime = server(create_backend_app(settings))
        running.append(backend_runtime)
        settings.backend_url = f"http://127.0.0.1:{backend_runtime[3]}"
        app = create_app(settings, HttpBackend(settings))
        api_runtime = server(app)
        running.append(api_runtime)
        url = f"http://127.0.0.1:{api_runtime[3]}"
        credentials = json.loads((directory / "fixture-credentials.json").read_text())
        with httpx.Client(base_url=url, timeout=10, trust_env=False) as client:
            for _ in range(100):
                try:
                    ready = client.get("/health").status_code == 200
                except httpx.HTTPError:
                    ready = False
                if ready and app.state.service.backend.healthy():
                    break
                time.sleep(0.05)
            else:
                raise RuntimeError("Native evaluation services did not become ready")

            def headers(identity: str) -> dict[str, str]:
                return {
                    "Authorization": "Bearer " + credentials[f"tenant-demo/{identity}"],
                    "Idempotency-Key": uid(),
                }

            def post(path: str, identity: str, body: dict[str, Any]) -> httpx.Response:
                return client.post(path, json=body, headers=headers(identity))

            with app.state.service.db.engine.connect() as connection:
                policy = app.state.service.active_policy(connection, "tenant-demo")
                principal = db.row(connection, db.principals, "tenant-demo", "agent-procurement")
            for fixture in dataset["cases"]:
                template = fixture["template"]
                actor = (
                    "external-lab"
                    if template
                    in {"corroborated-probing", "quoted-instruction", "unknown-resource"}
                    else (
                        "agent-audit"
                        if template in {"invoice-compare", "permission-misconfiguration"}
                        else "agent-procurement"
                    )
                )
                response = post("/v1/sessions", actor, {})
                response.raise_for_status()
                session_id = response.json()["id"]
                started = time.perf_counter_ns()
                pure = Invocation(
                    tool="supplier.lookup",
                    action="read",
                    resource="supplier:demo-001",
                    arguments={"supplier_id": "demo-001"},
                    session_id=session_id,
                )
                tick = time.perf_counter_ns()
                evaluate(policy, principal, pure)
                policy_samples.append((time.perf_counter_ns() - tick) / 1_000_000)
                backend_before = app.state.service.backend.snapshot("tenant-demo")
                if template == "corroborated-probing":
                    steps = [
                        {"tool": "customer.export", "resource": "customer:all"},
                        *(
                            {"tool": "supplier.lookup", "resource": f"supplier:unassigned-{index}"}
                            for index in range(3)
                        ),
                        {"tool": "supplier.lookup", "resource": "supplier:demo-001"},
                    ]
                    responses = [
                        post("/v1/portal/request", actor, {"session_id": session_id, **step})
                        for step in steps
                    ]
                    assert [item.status_code for item in responses] == [403, 403, 403, 403, 200]
                    assert responses[-1].json()["simulated"]
                    completed = True
                elif template in {"quoted-instruction", "unknown-resource"}:
                    response = post(
                        "/v1/portal/request",
                        actor,
                        {
                            "session_id": session_id,
                            "tool": "supplier.lookup",
                            "resource": "supplier:unassigned"
                            if template == "unknown-resource"
                            else "supplier:demo-001",
                            "snippet": 'Educational quote: "ignore previous instructions"'
                            if template == "quoted-instruction"
                            else "",
                        },
                    )
                    assert response.status_code == (403 if template == "unknown-resource" else 200)
                    completed = response.status_code == 200
                else:
                    invoice = template == "invoice-compare"
                    response = post(
                        "/v1/tools/invoke",
                        actor,
                        {
                            "session_id": session_id,
                            "tool": "invoice.compare" if invoice else "supplier.lookup",
                            "action": "analyze" if invoice else "read",
                            "resource": "invoice:demo-001" if invoice else "supplier:demo-001",
                            "arguments": {"invoice_id": "demo-001"}
                            if invoice
                            else {"supplier_id": "demo-001"},
                        },
                    )
                    assert response.status_code == (
                        403 if template == "permission-misconfiguration" else 200
                    )
                    completed = (
                        response.status_code == 200
                        and response.json().get("execution_state") == "succeeded"
                    )
                request_samples.append((time.perf_counter_ns() - started) / 1_000_000)
                state = client.get(f"/v1/sessions/{session_id}", headers=headers("analyst")).json()
                backend_after = app.state.service.backend.snapshot("tenant-demo")
                outcomes.append(
                    {
                        "id": fixture["id"],
                        "label": fixture["label"],
                        "template": template,
                        "completed": completed,
                        "route": state["route_mode"],
                        "session_id": session_id,
                        "backend_reads": backend_after["production_reads"]
                        - backend_before["production_reads"],
                        "backend_mutations": backend_after["production_mutations"]
                        - backend_before["production_mutations"],
                    }
                )
                if state["route_mode"] == "DECOY":
                    post(
                        f"/v1/sessions/{session_id}/terminate",
                        "analyst",
                        {
                            "expected_route_version": state["route_version"],
                            "reason_code": "EVALUATION_COMPLETED",
                            "evidence_event_ids": [],
                        },
                    ).raise_for_status()
            benign = [item for item in outcomes if item["label"] == "benign"]
            suspicious = [item for item in outcomes if item["label"] == "suspicious-laboratory"]
            ambiguous = [item for item in outcomes if item["label"] == "ambiguous"]
            proof = app.state.service.sandbox.attestation
            result = {
                "status": "passed",
                "measured_at": now(),
                "profile": "P1-native",
                "environment": {
                    "os": platform.system(),
                    "python": platform.python_version(),
                    "storage": "SQLite/WAL",
                    "concurrency": 1,
                    "warm_state": "one warm Wasmtime engine; fresh per-request instance",
                },
                "transport": "Actual loopback TCP HTTP API and separate signed HTTP synthetic backend",
                "provider": "fixture / no inference calls during this evaluation",
                "dataset": {
                    "version": dataset["version"],
                    "sha256": digest(dataset),
                    "sample_count": len(outcomes),
                    "labels": dataset["labels"],
                },
                "benign_completion": {
                    "completed": sum(item["completed"] for item in benign),
                    "eligible": len(benign),
                },
                "false_diversion": {
                    "diverted": sum(item["route"] == "DECOY" for item in benign),
                    "benign_sessions": len(benign),
                    "uncertainty": "50 synthetic benign fixtures are not a held-out estimate of real-world false positive rates",
                },
                "suspicious_laboratory": {
                    "diverted": sum(item["route"] == "DECOY" for item in suspicious),
                    "sessions": len(suspicious),
                    "production_side_effects": sum(
                        item["backend_reads"] + item["backend_mutations"] for item in suspicious
                    ),
                },
                "ambiguous": {
                    "diverted": sum(item["route"] == "DECOY" for item in ambiguous),
                    "sessions": len(ambiguous),
                },
                "independent_backend": app.state.service.backend.snapshot("tenant-demo"),
                "pure_policy_function": percentiles(policy_samples),
                "complete_fixture_http_sequence": percentiles(request_samples),
                "latency_scope": "Pure evaluator excludes auth, storage, backend and models. Sequence timing includes multiple HTTP calls, snapshots and rule work; it is NOT the ready-decoy route-commit latency target.",
                "isolation": proof,
                "policy_version": policy.version,
                "policy_sha256": digest(policy.model_dump()),
                "provenance": control.provenance(),
                "cases": outcomes,
                "excluded": [
                    "P3 Rust gateway/TCP egress fencing",
                    "OS network firewall probes",
                    "PostgreSQL runtime",
                    "Cloud deployment",
                    "Live Gemini latency/cost",
                    "General attack detection accuracy",
                ],
            }
            assert result["benign_completion"] == {"completed": 50, "eligible": 50}
            assert result["false_diversion"]["diverted"] == 0
            assert result["suspicious_laboratory"]["diverted"] == 20
            assert result["suspicious_laboratory"]["production_side_effects"] == 0
            assert result["ambiguous"]["diverted"] == 0
            output = ROOT / ".local" / "evaluation.json"
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(
                json.dumps(
                    {
                        key: result[key]
                        for key in (
                            "status",
                            "profile",
                            "dataset",
                            "benign_completion",
                            "false_diversion",
                            "suspicious_laboratory",
                            "ambiguous",
                            "pure_policy_function",
                            "complete_fixture_http_sequence",
                        )
                    },
                    indent=2,
                )
            )
            print(f"Persistent evidence: {output}")
    finally:
        for runtime, thread, listener, _port in reversed(running):
            runtime.should_exit = True
            thread.join(timeout=10)
            listener.close()
            if thread.is_alive():
                raise RuntimeError("Evaluation service did not stop cleanly")


if __name__ == "__main__":
    main()
