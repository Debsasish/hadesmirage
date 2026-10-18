from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from google.auth import jwt as google_jwt
from google.auth.crypt import es256
from pydantic import ValidationError
from sqlalchemy import select, update

from mirage import cloud, db, iap
from mirage.api import create_app
from mirage.auth import PrincipalContext
from mirage.backend import Ledger
from mirage.config import Settings

AUDIENCE = "/projects/123456789/locations/us-central1/services/hades-mirage"
HOST = "hades-mirage-123456789.us-central1.run.app"
ORIGIN = f"https://{HOST}"
KID = "iap-test-key"
SECRET = "test-backend-secret-with-at-least-32-characters"


def _key() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


PRIVATE, PUBLIC = _key()
OTHER_PRIVATE, _ = _key()


class FakeResponse:
    def __init__(self, status: int, data: bytes) -> None:
        self.status, self.data, self.headers = status, data, {}


class FakeKeyServer:
    """Stands in for https://www.gstatic.com/iap/verify/public_key (network fetch only)."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.status = 200

    def __call__(self, url: str, method: str = "GET", **_kwargs: Any) -> FakeResponse:
        self.calls.append(url)
        return FakeResponse(self.status, json.dumps({KID: PUBLIC}).encode())


def assertion(private: str = PRIVATE, kid: str = KID, **claims: Any) -> str:
    issued = int(time.time())
    payload = {
        "iss": iap.IAP_ISSUER,
        "aud": AUDIENCE,
        "iat": issued,
        "exp": issued + 600,
        "sub": "accounts.google.com:1001",
        "email": "admin@example.com",
        "hd": "example.com",
    }
    payload.update(claims)
    payload = {key: value for key, value in payload.items() if value is not None}
    signer = es256.ES256Signer.from_string(private, key_id=kid)
    return google_jwt.encode(signer, payload).decode()


def cloud_settings(path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "data_dir": path,
        "profile": "P2-cloud",
        "local_login": False,
        "auth_mode": "iap",
        "iap_audience": AUDIENCE,
        "iap_allowed_domain": "example.com",
        "iap_role_map": {
            "Admin@Example.com": ["analyst", "security_admin"],
            "approver@example.com": ["analyst", "approver"],
            "blocked@example.com": [],
        },
        "iap_default_role": "none",
        "iap_tenant": "tenant-demo",
        "allowed_hosts": [HOST],
        "allowed_origins": [ORIGIN],
        "database_url": "",
        "backend_url": "",
        "backend_secret": SECRET,
        "access_code": "test-local-access-code",
        "model_provider": "fixture",
        "model_egress_approved": False,
        "gemini_project": "",
        "gemini_model": "",
        "gemini_location": "global",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeKeyServer]:
    server = FakeKeyServer()
    iap.KEYS.clear()
    monkeypatch.setattr(iap.KEYS, "transport", server)
    yield server
    iap.KEYS.clear()


@pytest.fixture
def make_client(
    tmp_path: Path, keys: FakeKeyServer
) -> Iterator[Callable[..., tuple[TestClient, Any]]]:
    opened: list[tuple[TestClient, Any]] = []

    def factory(**overrides: Any) -> tuple[TestClient, Any]:
        path = tmp_path / f"instance-{len(opened)}"
        settings = cloud_settings(path, **overrides)
        settings.prepare()
        app = create_app(settings, Ledger(path / "backend.sqlite3"))
        client = TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 50000))
        client.__enter__()
        opened.append((client, app))
        return client, app

    yield factory
    for client, app in opened:
        client.__exit__(None, None, None)
        app.state.service.db.close()


def iap_headers(token: str | None = None, **extra: str) -> dict[str, str]:
    return {iap.IAP_HEADER: token if token is not None else assertion(), **extra}


def test_valid_iap_assertion_creates_principal_with_mapped_roles(make_client, keys):
    client, app = make_client()
    response = client.get("/auth/me", headers=iap_headers())
    assert response.status_code == 200, response.text
    body = response.json()
    identifier = iap.principal_id("admin@example.com")
    assert body["principal"]["id"] == identifier
    assert body["principal"]["name"] == "admin@example.com"
    assert body["principal"]["kind"] == "human"
    assert body["principal"]["roles"] == ["analyst", "security_admin"]
    assert body["profile"] == "P2-cloud"
    assert body["auth_mode"] == "iap"
    assert body["local_fixture_identity"] is False
    assert body["csrf"]
    assert client.get("/auth/me", headers=iap_headers()).status_code == 200
    with app.state.service.db.engine.connect() as connection:
        rows = db.rows(
            connection,
            select(db.principals).where(db.principals.c.id == identifier),
        )
        audit = db.rows(
            connection,
            select(db.audit_log).where(db.audit_log.c.action == "auth.iap_principal_created"),
        )
    assert len(rows) == 1 and rows[0]["tenant_id"] == "tenant-demo"
    assert [item["object_id"] for item in audit] == [identifier]
    assert keys.calls == [iap.IAP_CERTS_URL]


def test_role_map_change_updates_roles_and_identity_epoch(make_client):
    client, app = make_client()
    assert client.get("/auth/me", headers=iap_headers()).status_code == 200
    app.state.settings.iap_role_map = {"admin@example.com": ["analyst"]}
    body = client.get("/auth/me", headers=iap_headers()).json()
    assert body["principal"]["roles"] == ["analyst"]
    assert body["principal"]["identity_epoch"] == 2


def test_suspended_iap_principal_is_never_reactivated_by_sign_in(make_client):
    client, app = make_client()
    assert client.get("/auth/me", headers=iap_headers()).status_code == 200
    identifier = iap.principal_id("admin@example.com")
    with app.state.service.db.transaction() as connection:
        connection.execute(
            update(db.principals).where(db.principals.c.id == identifier).values(status="suspended")
        )
    denied = client.get("/auth/me", headers=iap_headers())
    assert denied.status_code == 403 and denied.json()["code"] == "IDENTITY_INACTIVE"
    app.state.settings.iap_role_map = {"admin@example.com": ["analyst"]}
    assert client.get("/auth/me", headers=iap_headers()).status_code == 403


@pytest.mark.parametrize(
    ("token", "status", "code"),
    [
        (lambda: "", 401, "AUTHENTICATION_REQUIRED"),
        (lambda: "not-a-jwt", 401, "IAP_ASSERTION_INVALID"),
        (lambda: assertion(aud="/projects/1/locations/x/services/other"), 401, None),
        (lambda: assertion(iss="https://accounts.google.com"), 401, None),
        (
            lambda: assertion(iat=int(time.time()) - 1800, exp=int(time.time()) - 900),
            401,
            None,
        ),
        (lambda: assertion(private=OTHER_PRIVATE), 401, None),
        (lambda: assertion(kid="unknown-key"), 401, None),
        (lambda: assertion(email=None), 401, None),
        (lambda: _unsigned(), 401, None),
        (lambda: assertion(email="eve@evil.test", hd="evil.test"), 403, "IAP_DOMAIN_DENIED"),
        (lambda: assertion(hd=None), 403, "IAP_DOMAIN_DENIED"),
        (lambda: assertion(email="admin@evil.test"), 403, "IAP_DOMAIN_DENIED"),
        (lambda: assertion(email="blocked@example.com"), 403, "IAP_ROLE_UNMAPPED"),
        (lambda: assertion(email="nobody@example.com"), 403, "IAP_ROLE_UNMAPPED"),
    ],
)
def test_invalid_or_unauthorized_assertions_are_refused(make_client, token, status, code):
    client, app = make_client()
    response = client.get("/v1/settings", headers=iap_headers(token()))
    assert response.status_code == status, response.text
    if code:
        assert response.json()["code"] == code
    with app.state.service.db.engine.connect() as connection:
        created = db.rows(connection, select(db.principals).where(db.principals.c.id.like("iap-%")))
    assert created == []


def _unsigned() -> str:
    def part(value: dict[str, Any]) -> str:
        import base64

        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    issued = int(time.time())
    claims = {
        "iss": iap.IAP_ISSUER,
        "aud": AUDIENCE,
        "iat": issued,
        "exp": issued + 600,
        "email": "admin@example.com",
        "hd": "example.com",
    }
    return part({"alg": "none", "kid": KID}) + "." + part(claims) + "."


def test_unsigned_identity_headers_are_never_trusted(make_client):
    client, _app = make_client()
    response = client.get(
        "/auth/me",
        headers={
            "x-goog-authenticated-user-email": "accounts.google.com:admin@example.com",
            "x-goog-authenticated-user-id": "accounts.google.com:1001",
        },
    )
    assert response.status_code == 401
    assert client.get("/v1/settings").status_code == 401


def test_unmapped_domain_user_gets_analyst_only_when_default_role_enabled(make_client):
    client, _app = make_client(iap_default_role="analyst")
    body = client.get(
        "/auth/me", headers=iap_headers(assertion(email="new.user@example.com"))
    ).json()
    assert body["principal"]["roles"] == ["analyst"]
    denied = client.post(
        "/v1/laboratory/run",
        json={"scenario": "legitimate-lookup"},
        headers=iap_headers(
            assertion(email="new.user@example.com"),
            Origin=ORIGIN,
            **{"X-CSRF-Token": body["csrf"], "Idempotency-Key": "cloud-test-0001"},
        ),
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "ROLE_REQUIRED"


def test_iap_mutations_require_allowed_origin_and_derived_csrf(make_client):
    client, app = make_client()
    csrf = client.get("/auth/me", headers=iap_headers()).json()["csrf"]
    missing = client.post("/auth/logout", headers=iap_headers(Origin=ORIGIN))
    assert missing.status_code == 403 and missing.json()["code"] == "CSRF_REQUIRED"
    wrong = client.post(
        "/auth/logout", headers=iap_headers(Origin=ORIGIN, **{"X-CSRF-Token": "x" * 64})
    )
    assert wrong.status_code == 403 and wrong.json()["code"] == "CSRF_REQUIRED"
    foreign = client.post(
        "/auth/logout",
        headers=iap_headers(Origin="https://evil.test", **{"X-CSRF-Token": csrf}),
    )
    assert foreign.status_code == 403 and foreign.json()["code"] == "ORIGIN_DENIED"
    other_user_csrf = client.get(
        "/auth/me", headers=iap_headers(assertion(email="approver@example.com"))
    ).json()["csrf"]
    crossed = client.post(
        "/auth/logout", headers=iap_headers(Origin=ORIGIN, **{"X-CSRF-Token": other_user_csrf})
    )
    assert crossed.status_code == 403
    accepted = client.post(
        "/auth/logout", headers=iap_headers(Origin=ORIGIN, **{"X-CSRF-Token": csrf})
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["iap_sign_out_url"] == iap.IAP_SIGN_OUT_PATH


def test_csrf_tokens_are_per_user_and_expire_after_one_day():
    settings = cloud_settings(Path("unused"))
    context = PrincipalContext("tenant-demo", "iap-abc", ("analyst",), "human")
    other = PrincipalContext("tenant-demo", "iap-def", ("analyst",), "human")
    today = iap.csrf_token(settings, context)
    assert iap.csrf_valid(settings, context, today)
    assert not iap.csrf_valid(settings, other, today)
    old = iap.csrf_token(settings, context, "2000-01-01")
    assert not iap.csrf_valid(settings, context, old)


def test_bearer_workload_tokens_keep_working_in_iap_mode(make_client, tmp_path):
    client, _app = make_client()
    tokens = json.loads((tmp_path / "instance-0" / "fixture-credentials.json").read_text())
    me = client.get("/auth/me", headers={"Authorization": "Bearer " + tokens["tenant-demo/admin"]})
    assert me.status_code == 200 and me.json()["principal"]["id"] == "admin"
    created = client.post(
        "/v1/sessions",
        headers={
            "Authorization": "Bearer " + tokens["tenant-demo/agent-procurement"],
            "Idempotency-Key": "cloud-test-0002",
        },
    )
    assert created.status_code == 201, created.text
    invalid = client.get("/auth/me", headers={"Authorization": "Bearer invalid-token"})
    assert invalid.status_code == 401


def test_fixture_login_disabled_in_cloud_profile(make_client):
    client, app = make_client()
    response = client.post(
        "/auth/login",
        json={"username": "admin", "access_code": app.state.settings.access_code},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "LOCAL_LOGIN_DISABLED"
    assert "mirage_session" not in response.cookies


def test_trusted_hosts_follow_configuration(make_client):
    client, _app = make_client()
    assert client.get("/health").status_code == 200
    assert client.get("/health", headers={"Host": "127.0.0.1"}).status_code == 200
    assert client.get("/health", headers={"Host": "attacker.example"}).status_code == 400


def test_key_document_is_cached_and_fetch_failures_fail_closed(make_client, keys):
    client, _app = make_client()
    for _ in range(3):
        assert client.get("/auth/me", headers=iap_headers()).status_code == 200
    assert len(keys.calls) == 1
    iap.KEYS.clear()
    keys.status = 500
    response = client.get("/auth/me", headers=iap_headers())
    assert response.status_code == 503
    assert response.json()["code"] == "IAP_KEYS_UNAVAILABLE"


def test_key_transport_refuses_other_urls():
    with pytest.raises(Exception, match="IAP public-key document"):
        iap.KEYS("https://attacker.example/keys")


@pytest.mark.parametrize(
    "overrides",
    [
        {"local_login": True},
        {"auth_mode": "local"},
        {"iap_audience": ""},
        {"iap_audience": "hades-mirage"},
        {"backend_url": "http://10.0.0.8:8788"},
        {"iap_role_map": {"admin@example.com": ["root"]}},
        {"iap_allowed_domain": "Example.com"},
        {"iap_allowed_domain": "", "iap_default_role": "analyst"},
    ],
)
def test_cloud_settings_validation_fails_closed(tmp_path, overrides):
    with pytest.raises(ValidationError):
        cloud_settings(tmp_path, **overrides)


def test_local_profile_cannot_enable_iap_with_fixture_login(tmp_path):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            data_dir=tmp_path,
            profile="P1-native",
            local_login=True,
            auth_mode="iap",
            iap_audience=AUDIENCE,
        )


def test_cloud_launcher_defaults_and_checks(tmp_path):
    environ = {"MIRAGE_PROFILE": "P2-cloud", "MIRAGE_DATA_DIR": str(tmp_path)}
    cloud.apply_cloud_defaults(environ)
    assert environ["MIRAGE_DATA_DIR"] == str(tmp_path)
    assert environ["MIRAGE_AUTH_MODE"] == "iap"
    assert environ["MIRAGE_LOCAL_LOGIN"] == "false"
    assert cloud.cloud_port({"PORT": "8899"}) == 8899
    assert cloud.cloud_port({}) == 8080
    for value in ("0", "99999", "80; rm", ""):
        with pytest.raises(RuntimeError):
            cloud.cloud_port({"PORT": value})
    settings = cloud_settings(tmp_path)
    cloud.check_cloud_settings(settings, 8899, {"MIRAGE_BACKEND_SECRET": SECRET})
    with pytest.raises(RuntimeError, match="at least 32"):
        cloud.check_cloud_settings(settings, 8899, {"MIRAGE_BACKEND_SECRET": "short"})
    with pytest.raises(RuntimeError, match="must differ"):
        cloud.check_cloud_settings(settings, settings.backend_port, {})
    local = Settings(_env_file=None, data_dir=tmp_path, profile="P1-native", local_login=True)
    with pytest.raises(RuntimeError, match="P2-cloud"):
        cloud.check_cloud_settings(local, 8899, {})
