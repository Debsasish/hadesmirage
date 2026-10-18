from __future__ import annotations

import asyncio
import itertools
import json
import logging
from typing import Any

import httpx
import pytest
from sqlalchemy import func, insert, select, update

from mirage import db, telegram
from mirage.auth import token_hash
from mirage.common import after, now, uid
from mirage.config import Settings
from mirage.models import Invocation

TOKEN = "123456789:TEST-fake-bot-token-0123456789abcdef"
SECRET = "webhook-secret-for-tests-0123456789"
APPROVER = 5001
VIEWER = 5002
_ids = itertools.count(1)


class FakeTelegram:
    """In-process Bot API double; no network is used."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.updates: list[dict[str, Any]] = []
        self.fail: set[str] = set()
        self.next_id = 100

    def __call__(self, request: httpx.Request) -> httpx.Response:
        prefix, _, method = request.url.path.rpartition("/")
        assert prefix == f"/bot{TOKEN}"
        payload = json.loads(request.content or b"{}")
        self.calls.append((method, payload))
        if method in self.fail:
            body = {"ok": False, "error_code": 400, "description": f"Bad Request {TOKEN} <b>x</b>"}
            return httpx.Response(400, json=body)
        if method == "getUpdates":
            result: Any = self.updates
            self.updates = []
        elif method == "sendMessage":
            self.next_id += 1
            result = {"message_id": self.next_id, "chat": {"id": payload["chat_id"]}}
        elif method == "getMe":
            result = {"id": 1, "is_bot": True, "username": "hades_mirage_test_bot"}
        else:
            result = True
        return httpx.Response(200, json={"ok": True, "result": result})

    def of(self, method: str) -> list[dict[str, Any]]:
        return [payload for name, payload in self.calls if name == method]

    def messages(self, chat: int) -> list[dict[str, Any]]:
        return [item for item in self.of("sendMessage") if item["chat_id"] == chat]


@pytest.fixture
def bot(lab, monkeypatch) -> FakeTelegram:
    fake = FakeTelegram()
    monkeypatch.setattr(telegram, "TRANSPORT", httpx.MockTransport(fake))
    monkeypatch.setattr(lab.settings, "telegram_mode", "polling")
    monkeypatch.setattr(lab.settings, "telegram_bot_token", TOKEN)
    return fake


def message(user: int, text: str, chat_type: str = "private") -> dict[str, Any]:
    return {
        "update_id": next(_ids),
        "message": {
            "message_id": 1,
            "from": {"id": user, "is_bot": False, "first_name": "Test", "username": f"u{user}"},
            "chat": {"id": user if chat_type == "private" else -100, "type": chat_type},
            "text": text,
        },
    }


def press(user: int, data: str, message_id: int = 101) -> dict[str, Any]:
    return {
        "update_id": next(_ids),
        "callback_query": {
            "id": f"cb-{uid()}",
            "from": {"id": user, "is_bot": False, "first_name": "Test"},
            "message": {"message_id": message_id, "chat": {"id": user, "type": "private"}},
            "data": data,
        },
    }


def send(lab, incoming: dict[str, Any]) -> None:
    telegram.process_update(lab.service, incoming)


def admin(lab, name: str = "admin") -> dict[str, str]:
    return lab.headers(name, **{"Idempotency-Key": uid()})


def user_row(lab, telegram_user_id: int) -> dict[str, Any] | None:
    with lab.service.db.engine.connect() as connection:
        return telegram._user_by_telegram_id(connection, "tenant-demo", str(telegram_user_id))


def audits(lab, action: str) -> int:
    with lab.service.db.engine.connect() as connection:
        return connection.execute(
            select(func.count()).where(
                db.audit_log.c.tenant_id == "tenant-demo", db.audit_log.c.action == action
            )
        ).scalar_one()


def approval_row(lab, identifier: str) -> dict[str, Any]:
    with lab.service.db.engine.connect() as connection:
        return db.row(connection, db.approvals, "tenant-demo", identifier)


def admit(lab, telegram_user_id: int, role: str) -> dict[str, Any]:
    send(lab, message(telegram_user_id, "/start"))
    identifier = user_row(lab, telegram_user_id)["id"]
    response = lab.client.post(
        f"/v1/telegram/users/{identifier}/decision",
        json={"decision": "approve", "role": role},
        headers=admin(lab),
    )
    assert response.status_code == 200, response.text
    return response.json()


def payment_change(lab) -> tuple[Invocation, dict[str, Any]]:
    session = lab.session()
    operation = Invocation.model_validate(
        {
            "tool": "payment.change_request",
            "action": "propose_change",
            "resource": "supplier:demo-001",
            "arguments": {
                "supplier_id": "demo-001",
                "proposed_account_ref": "synthetic-account-updated",
            },
            "session_id": session["id"],
        }
    )
    return operation, lab.service.request_approval(lab.context(), operation, uid())


def buttons(bot: FakeTelegram, chat: int) -> tuple[str, str, int]:
    sent = [item for item in bot.messages(chat) if "reply_markup" in item]
    row = sent[-1]["reply_markup"]["inline_keyboard"][0]
    return row[0]["callback_data"], row[1]["callback_data"], bot.next_id


def test_start_creates_pending_request_and_is_rate_limited(lab, bot, monkeypatch):
    monkeypatch.setattr(telegram, "_window", lambda: 42)
    send(lab, message(APPROVER, "/start"))
    assert bot.messages(APPROVER)[-1]["text"] == telegram.START_SENT
    assert "parse_mode" not in bot.messages(APPROVER)[-1]
    send(lab, message(APPROVER, "/start"))
    assert bot.messages(APPROVER)[-1]["text"] == telegram.START_WAITING
    row = user_row(lab, APPROVER)
    assert (row["status"], row["role"], row["principal_id"]) == ("pending", None, None)
    assert audits(lab, "telegram.access_requested") == 1
    send(lab, message(APPROVER, "/issues"))
    assert bot.messages(APPROVER)[-1]["text"] == telegram.NOT_ALLOWED
    send(lab, message(APPROVER, "/pending"))
    assert bot.messages(APPROVER)[-1]["text"] == telegram.NOT_ALLOWED

    with lab.service.db.transaction() as connection:
        for number in range(telegram.MAX_PENDING_REQUESTS - 1):
            connection.execute(
                insert(telegram.telegram_users).values(
                    tenant_id="tenant-demo",
                    id=uid(),
                    telegram_user_id=str(9000 + number),
                    chat_id=str(9000 + number),
                    status="pending",
                    requested_at=now(),
                )
            )
    send(lab, message(7777, "/start"))
    assert bot.messages(7777)[-1]["text"] == telegram.START_CLOSED
    assert user_row(lab, 7777) is None

    for _ in range(telegram.MESSAGES_PER_MINUTE + 5):
        send(lab, message(7778, "/help"))
    assert len(bot.messages(7778)) == telegram.MESSAGES_PER_MINUTE


def test_admin_approval_creates_bot_principal_and_notifies(lab, bot):
    send(lab, message(APPROVER, "/start"))
    listing = lab.client.get("/v1/telegram/users", headers=lab.headers("admin"))
    assert listing.status_code == 200
    item = listing.json()["items"][0]
    assert item["status"] == "pending" and item["telegram_user_id"] == str(APPROVER)
    assert set(item) == {
        "id",
        "telegram_user_id",
        "username",
        "display_name",
        "status",
        "role",
        "requested_at",
        "decided_at",
        "decided_by",
        "last_notified_at",
    }
    route = f"/v1/telegram/users/{item['id']}/decision"
    for invalid in (
        {"decision": "approve"},
        {"decision": "approve", "role": "security_admin"},
        {"decision": "approve", "role": "approver", "extra": True},
    ):
        assert lab.client.post(route, json=invalid, headers=admin(lab)).status_code == 422
    headers = admin(lab)
    response = lab.client.post(
        route, json={"decision": "approve", "role": "approver"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved" and response.json()["role"] == "approver"
    with lab.service.db.engine.connect() as connection:
        principal = db.row(connection, db.principals, "tenant-demo", f"telegram-{APPROVER}")
        credentials = connection.execute(
            select(func.count()).where(db.credentials.c.principal_id == f"telegram-{APPROVER}")
        ).scalar_one()
    assert principal["roles"] == ["approver"] and principal["kind"] == "human"
    assert principal["status"] == "active" and credentials == 0
    assert "approver" in bot.messages(APPROVER)[-1]["text"]
    assert audits(lab, "telegram.user_approved") == 1
    sent = len(bot.of("sendMessage"))
    retry = lab.client.post(
        route, json={"decision": "approve", "role": "approver"}, headers=headers
    )
    assert retry.json() == response.json() and len(bot.of("sendMessage")) == sent
    again = lab.client.post(route, json={"decision": "reject"}, headers=admin(lab))
    assert again.status_code == 409


def test_only_security_admin_can_manage_telegram_access(lab, bot):
    send(lab, message(APPROVER, "/start"))
    identifier = user_row(lab, APPROVER)["id"]
    for name in ("analyst", "approver", "agent-procurement"):
        assert lab.client.get("/v1/telegram/users", headers=admin(lab, name)).status_code == 403
        for path, body in (
            (
                f"/v1/telegram/users/{identifier}/decision",
                {"decision": "approve", "role": "approver"},
            ),
            (f"/v1/telegram/users/{identifier}/role", {"role": "approver"}),
            (f"/v1/telegram/users/{identifier}/revoke", {}),
            ("/v1/telegram/test", {}),
        ):
            assert lab.client.post(path, json=body, headers=admin(lab, name)).status_code == 403
    assert lab.client.get("/v1/telegram", headers=lab.headers("analyst")).status_code == 200
    assert lab.client.get("/v1/telegram", headers=lab.headers()).status_code == 403
    assert lab.client.get("/v1/telegram").status_code == 401
    assert user_row(lab, APPROVER)["status"] == "pending"
    with lab.service.db.engine.connect() as connection:
        assert db.row(connection, db.principals, "tenant-demo", f"telegram-{APPROVER}") is None


def test_approval_button_approves_exact_digest_once(lab, bot):
    admit(lab, APPROVER, "approver")
    operation, approval = payment_change(lab)
    assert telegram.tick(lab.service) == 1
    alert = bot.messages(APPROVER)[-1]
    assert "change supplier payment details" in alert["text"]
    assert "supplier:demo-001" in alert["text"] and "agent-procurement" in alert["text"]
    assert approval["digest"] not in alert["text"] and approval["digest"][:8] in alert["text"]
    assert "parse_mode" not in alert
    approve, reject, message_id = buttons(bot, APPROVER)
    assert approve.endswith(":y") and reject.endswith(":n") and len(approve.encode()) <= 64
    assert telegram.tick(lab.service) == 0
    assert len(bot.messages(APPROVER)) == 3  # request sent, access approved, one alert

    send(lab, press(APPROVER, approve, message_id))
    stored = approval_row(lab, approval["id"])
    assert stored["status"] == "approved" and stored["approver_id"] == f"telegram-{APPROVER}"
    assert stored["digest"] == approval["digest"]
    assert bot.of("editMessageText")[-1]["message_id"] == message_id
    assert bot.of("editMessageText")[-1]["text"].startswith("Approved by you")
    assert audits(lab, "telegram.approval_decision") == 1

    send(lab, press(APPROVER, approve, message_id))
    send(lab, press(APPROVER, reject, message_id))
    assert bot.of("answerCallbackQuery")[-1]["text"] == telegram.REFUSED["used"]
    assert approval_row(lab, approval["id"]) == stored
    assert audits(lab, "approval.approved") == 1 and audits(lab, "approval.rejected") == 0

    approved_operation = operation.model_copy(update={"approval_id": approval["id"]})
    status, result = lab.service.invoke(lab.context(), approved_operation, uid())
    assert status == 200 and result["execution_state"] == "succeeded"
    assert lab.service.invoke(lab.context(), approved_operation, uid())[0] == 403
    assert lab.backend.snapshot("tenant-demo")["production_mutations"] == 1


def test_viewer_forged_and_demoted_buttons_cannot_approve(lab, bot):
    approver = admit(lab, APPROVER, "approver")
    admit(lab, VIEWER, "viewer")
    _, approval = payment_change(lab)
    assert telegram.tick(lab.service) == 1
    assert not any("reply_markup" in item for item in bot.messages(VIEWER))
    approve, _, message_id = buttons(bot, APPROVER)

    send(lab, press(VIEWER, approve, message_id))
    assert bot.of("answerCallbackQuery")[-1]["text"] == telegram.REFUSED["invalid"]
    send(lab, press(APPROVER, "a:" + "A" * 32 + ":y"))
    assert bot.of("answerCallbackQuery")[-1]["text"] == telegram.REFUSED["invalid"]
    token = "B" * 32
    with lab.service.db.transaction() as connection:
        connection.execute(
            insert(telegram.telegram_actions).values(
                tenant_id="tenant-demo",
                id=token_hash(token),
                approval_id=approval["id"],
                approval_digest=approval["digest"],
                telegram_user_id=str(VIEWER),
                chat_id=str(VIEWER),
                created_at=now(),
                expires_at=after(600),
            )
        )
    send(lab, press(VIEWER, f"a:{token}:y"))
    assert bot.of("answerCallbackQuery")[-1]["text"] == telegram.REFUSED["not_allowed"]

    demoted = lab.client.post(
        f"/v1/telegram/users/{approver['id']}/role", json={"role": "viewer"}, headers=admin(lab)
    )
    assert demoted.status_code == 200 and demoted.json()["role"] == "viewer"
    send(lab, press(APPROVER, approve, message_id))
    assert bot.of("answerCallbackQuery")[-1]["text"] == telegram.REFUSED["not_allowed"]
    stored = approval_row(lab, approval["id"])
    assert stored["status"] == "pending" and stored["approver_id"] is None
    assert audits(lab, "approval.approved") == 0 and audits(lab, "telegram.user_role_changed") == 1


def test_revoked_user_buttons_and_commands_stop_working(lab, bot):
    approver = admit(lab, APPROVER, "approver")
    _, approval = payment_change(lab)
    telegram.tick(lab.service)
    approve, _, message_id = buttons(bot, APPROVER)
    revoked = lab.client.post(
        f"/v1/telegram/users/{approver['id']}/revoke", json={}, headers=admin(lab)
    )
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    assert "removed" in bot.messages(APPROVER)[-1]["text"]
    with lab.service.db.engine.connect() as connection:
        principal = db.row(connection, db.principals, "tenant-demo", f"telegram-{APPROVER}")
    assert principal["status"] == "suspended"
    send(lab, press(APPROVER, approve, message_id))
    assert bot.of("answerCallbackQuery")[-1]["text"] == telegram.REFUSED["not_allowed"]
    assert approval_row(lab, approval["id"])["status"] == "pending"
    send(lab, message(APPROVER, "/pending"))
    assert bot.messages(APPROVER)[-1]["text"] == telegram.NOT_ALLOWED
    assert audits(lab, "telegram.user_revoked") == 1


def test_webhook_requires_the_secret_header(lab, bot, monkeypatch):
    monkeypatch.setattr(lab.settings, "telegram_mode", "webhook")
    monkeypatch.setattr(lab.settings, "telegram_webhook_secret", SECRET)
    incoming = message(6001, "/start")
    assert lab.client.post("/telegram/webhook", json=incoming).status_code == 401
    wrong = {"X-Telegram-Bot-Api-Secret-Token": SECRET[:-1] + "x"}
    assert lab.client.post("/telegram/webhook", json=incoming, headers=wrong).status_code == 401
    assert user_row(lab, 6001) is None
    good = {"X-Telegram-Bot-Api-Secret-Token": SECRET}
    response = lab.client.post("/telegram/webhook", json=incoming, headers=good)
    assert response.status_code == 200 and response.json() == {"ok": True}
    assert user_row(lab, 6001)["status"] == "pending"
    assert lab.client.post("/telegram/webhook", json=incoming, headers=good).status_code == 200
    assert audits(lab, "telegram.access_requested") == 1
    monkeypatch.setattr(lab.settings, "telegram_mode", "polling")
    assert lab.client.post("/telegram/webhook", json=incoming, headers=good).status_code == 404


def test_polling_advances_offset_and_ignores_replayed_updates(lab, bot):
    first = message(6101, "/start")
    bot.updates = [first]
    assert asyncio.run(telegram.poll_once(lab.service, timeout=0)) == 1
    assert user_row(lab, 6101)["status"] == "pending"
    assert asyncio.run(telegram.poll_once(lab.service, timeout=0)) == 0
    polls = bot.of("getUpdates")
    assert polls[0]["timeout"] == 0 and polls[1]["offset"] == first["update_id"] + 1
    assert polls[0]["allowed_updates"] == ["message", "callback_query"]
    send(lab, first)
    assert audits(lab, "telegram.access_requested") == 1
    assert lab.client.get("/v1/telegram", headers=lab.headers("analyst")).json()["last_poll_at"]


def test_issue_and_honeypot_alerts_reach_approved_users_once(lab, bot):
    admit(lab, APPROVER, "approver")
    admit(lab, VIEWER, "viewer")
    session = lab.session()
    incident_id = uid()
    with lab.service.db.transaction() as connection:
        connection.execute(
            insert(db.incidents).values(
                tenant_id="tenant-demo",
                id=incident_id,
                number="HM-0999",
                session_id=session["id"],
                principal_id="agent-procurement",
                title="Repeated prohibited export attempts",
                summary="Synthetic test incident",
                severity="high",
                confidence="medium",
                status="open",
                version=1,
                rules=["D-001"],
                source="dispatcher",
                origin="live",
                model_calls=0,
                created_at=now(),
                updated_at=now(),
            )
        )
        moved = session["history"] + [{"mode": "DECOY", "version": 2, "at": now(), "reason": "T"}]
        connection.execute(
            update(db.sessions)
            .where(db.sessions.c.tenant_id == "tenant-demo", db.sessions.c.id == session["id"])
            .values(route_mode="DECOY", history=moved)
        )
    assert telegram.tick(lab.service) == 4
    assert telegram.tick(lab.service) == 0
    texts = [item["text"] for item in bot.messages(VIEWER)]
    assert any(
        text.startswith("New security issue HM-0999") and f"/incidents/{incident_id}" in text
        for text in texts
    )
    assert any("honeypot (fake environment)" in text for text in texts)
    send(lab, message(APPROVER, "/issues"))
    assert "HM-0999" in bot.messages(APPROVER)[-1]["text"]
    send(lab, message(VIEWER, "/issues"))
    assert bot.messages(VIEWER)[-1]["text"] == telegram.NOT_ALLOWED


def test_token_never_appears_in_responses_state_or_logs(lab, bot, caplog):
    caplog.set_level(logging.DEBUG)
    admit(lab, APPROVER, "approver")
    bot.fail = {"sendMessage"}
    send(lab, message(APPROVER, "/help"))
    status = lab.client.get("/v1/telegram", headers=lab.headers("analyst"))
    assert status.status_code == 200
    body = status.json()
    assert body["configured"] is True and body["mode"] == "polling"
    assert body["counts"] == {"pending": 0, "approved": 1}
    assert body["last_error"] and "sendMessage" in body["last_error"]
    assert "<" not in body["last_error"]
    users = lab.client.get("/v1/telegram/users", headers=lab.headers("admin"))
    with lab.service.db.engine.connect() as connection:
        state = db.row(connection, telegram.telegram_state, "tenant-demo", "bot")
    for text in (status.text, users.text, str(state), caplog.text, repr(lab.settings)):
        assert TOKEN not in text and TOKEN.split(":")[1] not in text
    assert "bot[redacted]" in caplog.text


def test_settings_reject_unsafe_telegram_configuration():
    with pytest.raises(ValueError):
        Settings(_env_file=None, telegram_mode="webhook", telegram_bot_token=TOKEN)
    with pytest.raises(ValueError):
        Settings(_env_file=None, telegram_api_base="http://api.telegram.org")
    with pytest.raises(ValueError):
        Settings(_env_file=None, telegram_bot_token="123456:short/../../evil")
    settings = Settings(
        _env_file=None,
        telegram_mode="webhook",
        telegram_bot_token=TOKEN,
        telegram_webhook_secret=SECRET,
    )
    assert TOKEN not in repr(settings) and SECRET not in repr(settings)


def test_background_worker_polls_and_stops_cleanly(tmp_path, monkeypatch):
    import time

    from fastapi.testclient import TestClient

    from mirage.api import create_app
    from mirage.backend import Ledger

    fake = FakeTelegram()
    fake.updates = [message(6201, "/start")]
    monkeypatch.setattr(telegram, "TRANSPORT", httpx.MockTransport(fake))
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        database_url="",
        backend_url="",
        access_code="test-local-access-code",
        backend_secret="test-backend-secret-with-at-least-32-characters",
        model_provider="fixture",
        telegram_mode="polling",
        telegram_bot_token=TOKEN,
    )
    app = create_app(settings, Ledger(tmp_path / "backend.sqlite3"))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)):
        deadline = time.monotonic() + 15

        def ready() -> bool:
            return bool(fake.messages(6201) and fake.of("getMe") and fake.of("deleteWebhook"))

        while time.monotonic() < deadline and not ready():
            time.sleep(0.05)
        assert ready()
        assert fake.messages(6201)[0]["text"] == telegram.START_SENT
        stopping = time.monotonic()
    assert time.monotonic() - stopping < 5
    app.state.service.db.close()
