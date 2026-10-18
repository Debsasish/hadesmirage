from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mirage.api import create_app
from mirage.auth import PrincipalContext, authenticate
from mirage.backend import Ledger
from mirage.config import Settings
from mirage.service import Service


def pytest_addoption(parser):
    parser.addoption(
        "--live-ai",
        action="store_true",
        default=False,
        help="Explicitly opt into the separately budgeted five-call synthetic Gemini gate",
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--live-ai"):
        skip = pytest.mark.skip(
            reason="Live Gemini unverified: use --live-ai only with approved credentials, model and MIRAGE_LIVE_AI_CALL_LIMIT>=5"
        )
        for item in items:
            if item.get_closest_marker("live_ai"):
                item.add_marker(skip)


@dataclass
class Lab:
    settings: Settings
    service: Service
    backend: Ledger
    client: TestClient
    tokens: dict[str, str] = field(repr=False)

    def context(
        self, name: str = "agent-procurement", tenant: str = "tenant-demo"
    ) -> PrincipalContext:
        return authenticate(self.service.db, self.tokens[f"{tenant}/{name}"])

    def headers(
        self, name: str = "agent-procurement", tenant: str = "tenant-demo", **extra: Any
    ) -> dict[str, str]:
        return {
            "Authorization": "Bearer " + self.tokens[f"{tenant}/{name}"],
            "Idempotency-Key": "test-key-0001",
            **extra,
        }

    def session(
        self, name: str = "agent-procurement", tenant: str = "tenant-demo"
    ) -> dict[str, Any]:
        return self.service.create_session(self.context(name, tenant))


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        profile="P1-native",
        local_login=True,
        database_url="",
        backend_url="",
        access_code="test-local-access-code",
        backend_secret="test-backend-secret-with-at-least-32-characters",
        model_provider="fixture",
        model_egress_approved=False,
        gemini_project="",
        gemini_api_key="",
        gemini_endpoint="auto",
        gemini_model="",
        gemini_location="global",
        decoy_model_wording=False,
        model_call_budget=100,
        model_case_call_budget=3,
        model_max_pending=4,
        model_input_bytes=65536,
        model_timeout_seconds=12,
        session_ttl_seconds=900,
        max_engagements=10,
        decoy_request_budget=100,
    )
    settings.prepare()
    backend = Ledger(tmp_path / "backend.sqlite3")
    app = create_app(settings, backend)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        yield Lab(
            settings,
            app.state.service,
            backend,
            client,
            json.loads((tmp_path / "fixture-credentials.json").read_text()),
        )
    app.state.service.db.close()
