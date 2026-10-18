"""Optional Telegram bot: access requests, plain-text alerts and one-time approval buttons.

Telegram is an untrusted transport. Sender identity, approval status, role, token expiry and
approval digest are checked here, outside any model, and every operation decision still goes
through ``Service.decide_approval``. The bot token is never stored in the database, returned by
the API or written to logs.
"""

import asyncio
import hmac
import json
import logging
import re
import secrets
import ssl
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Self

import httpx
from fastapi import FastAPI, Request
from pydantic import model_validator
from sqlalchemy import (
    BigInteger,
    Column,
    String,
    UniqueConstraint,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Connection

from mirage import db
from mirage.auth import PrincipalContext, token_hash, verify_lineage
from mirage.common import DomainError, after, now, uid
from mirage.config import Settings
from mirage.models import ApprovalDecision, StrictModel
from mirage.service import Service

LOGGER = logging.getLogger("mirage.telegram")

# Tests replace this with ``httpx.MockTransport``; ``None`` means the real network transport.
TRANSPORT: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None
_TLS_CONTEXT: ssl.SSLContext | None = None


def _trust_store() -> ssl.SSLContext:
    """Verify TLS with the operating-system trust store (corporate roots included)."""
    global _TLS_CONTEXT
    if _TLS_CONTEXT is None:
        _TLS_CONTEXT = ssl.create_default_context()
    return _TLS_CONTEXT


ROLES: dict[str, list[str]] = {
    "viewer": ["viewer"],
    "analyst": ["analyst"],
    "approver": ["approver"],
}
ROLE_WORDS = {
    "viewer": "viewer (alerts only)",
    "analyst": "analyst (alerts and the open issue list)",
    "approver": "approver (alerts, open issues and operation approvals)",
}
BOT_OWNER = "telegram-bot-access"
MAX_PENDING_REQUESTS = 50
REQUEST_COOLDOWN_SECONDS = 3600
MESSAGES_PER_MINUTE = 20
ACTION_TTL_SECONDS = 30 * 60
PRINCIPAL_TTL_SECONDS = 90 * 86400
NOTIFY_MAX_AGE_SECONDS = 86400
POLL_TIMEOUT_SECONDS = 20
TICK_SECONDS = 3
MAX_UPDATE_BYTES = 32768
TEXT_LIMIT = 3500
CALLBACK = re.compile(r"a:([A-Za-z0-9_-]{20,43}):([yn])")
STATE_ID = "bot"

telegram_users = db.tenant_table(
    "telegram_users",
    Column("telegram_user_id", String(40), nullable=False),
    Column("username", String(100)),
    Column("display_name", String(200)),
    Column("chat_id", String(40), nullable=False),
    Column("status", String(20), nullable=False),
    Column("role", String(20)),
    Column("principal_id", String(200)),
    Column("requested_at", String(40), nullable=False),
    Column("decided_at", String(40)),
    Column("decided_by", String(200)),
    Column("approved_at", String(40)),
    Column("last_notified_at", String(40)),
    UniqueConstraint("tenant_id", "telegram_user_id"),
)
telegram_actions = db.tenant_table(
    "telegram_actions",
    Column("approval_id", String(200), nullable=False),
    Column("approval_digest", String(64), nullable=False),
    Column("telegram_user_id", String(40), nullable=False),
    Column("chat_id", String(40), nullable=False),
    Column("message_id", String(40)),
    Column("created_at", String(40), nullable=False),
    Column("expires_at", String(40), nullable=False),
    Column("used_at", String(40)),
    Column("outcome", String(60)),
)
telegram_deliveries = db.tenant_table(
    "telegram_deliveries",
    Column("kind", String(30), nullable=False),
    Column("object_id", String(200), nullable=False),
    Column("telegram_user_id", String(40), nullable=False),
    Column("status", String(20), nullable=False),
    Column("created_at", String(40), nullable=False),
    UniqueConstraint("tenant_id", "kind", "object_id", "telegram_user_id"),
)
telegram_state = db.tenant_table(
    "telegram_state",
    Column("update_offset", BigInteger, nullable=False, default=0),
    Column("bot_username", String(100)),
    Column("last_poll_at", String(40)),
    Column("last_error", String(300)),
    Column("enabled_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
)


class AccessDecision(StrictModel):
    decision: Literal["approve", "reject"]
    role: Literal["viewer", "analyst", "approver"] | None = None

    @model_validator(mode="after")
    def role_for_approval(self) -> Self:
        if self.decision == "approve" and self.role is None:
            raise ValueError("Choose a role when approving Telegram access")
        return self


class RoleChange(StrictModel):
    role: Literal["viewer", "analyst", "approver"]


class EmptyBody(StrictModel):
    pass


class _RedactBotPath(logging.Filter):
    """httpx logs request URLs, and Telegram puts the bot token in the URL path."""

    pattern = re.compile(r"/bot[^/\s'\"]*")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        if "/bot" in message:
            record.msg = self.pattern.sub("/bot[redacted]", message)
            record.args = ()
        return True


for _name in ("httpx", "httpcore"):
    _logger = logging.getLogger(_name)
    if not any(isinstance(item, _RedactBotPath) for item in _logger.filters):
        _logger.addFilter(_RedactBotPath())


class TelegramError(Exception):
    def __init__(self, method: str, reason: str) -> None:
        self.method = method
        self.reason = reason
        super().__init__(f"{method}: {reason}")


def configured(settings: Settings) -> bool:
    return settings.telegram_mode in {"polling", "webhook"} and bool(settings.telegram_bot_token)


def clean_error(message: str, token: str = "") -> str:
    text = message.replace(token, "[redacted]") if token else message
    text = re.sub(r"[0-9]{3,20}:[A-Za-z0-9_-]{20,}", "[redacted]", text)
    text = re.sub(r"[^A-Za-z0-9 .,:;()_'/\[\]-]", "", text)
    return text[:200]


def plain(value: Any, limit: int = 120) -> str:
    """Collapse untrusted text to one bounded plain line (messages never use parse_mode)."""
    text = re.sub(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069]", " ", str(value))
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _ago(seconds: int) -> str:
    return (
        (datetime.now(UTC) - timedelta(seconds=seconds))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _when(value: Any) -> str:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return plain(value, 40)
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _identifier(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or abs(value) > 10**15:
        return None
    return str(value)


class BotApi:
    """Minimal Bot API client. Logs and errors name the method only, never the URL."""

    def __init__(self, settings: Settings) -> None:
        self._token = settings.telegram_bot_token
        self._base = settings.telegram_api_base.rstrip("/")

    def _url(self, method: str) -> str:
        if not re.fullmatch(r"[A-Za-z]{3,40}", method):
            raise ValueError("Unsupported Telegram method")
        return f"{self._base}/bot{self._token}/{method}"

    @staticmethod
    def _timeout(read: float) -> httpx.Timeout:
        return httpx.Timeout(connect=5.0, read=min(read, 30.0), write=10.0, pool=5.0)

    def _result(self, method: str, response: httpx.Response) -> Any:
        if 300 <= response.status_code < 400:
            raise TelegramError(
                method,
                "network security gateway redirected api.telegram.org (Telegram is blocked on "
                "this network; use an allowed network or the cloud deployment)",
            )
        try:
            body = response.json()
        except ValueError:
            raise TelegramError(method, f"HTTP {response.status_code}") from None
        if not isinstance(body, dict) or body.get("ok") is not True:
            description = body.get("description", "") if isinstance(body, dict) else ""
            reason = clean_error(f"HTTP {response.status_code} {description}", self._token)
            raise TelegramError(method, reason) from None
        return body.get("result")

    def call(self, method: str, payload: dict[str, Any], read: float = 10.0) -> Any:
        url = self._url(method)
        try:
            with httpx.Client(
                transport=TRANSPORT,  # type: ignore[arg-type]
                timeout=self._timeout(read),
                trust_env=True,
                verify=_trust_store(),
                follow_redirects=False,
            ) as client:
                response = client.post(url, json=payload)
        except httpx.HTTPError as error:
            raise TelegramError(method, type(error).__name__) from None
        return self._result(method, response)

    async def acall(self, method: str, payload: dict[str, Any], read: float = 10.0) -> Any:
        url = self._url(method)
        try:
            async with httpx.AsyncClient(
                transport=TRANSPORT,  # type: ignore[arg-type]
                timeout=self._timeout(read),
                trust_env=True,
                verify=_trust_store(),
                follow_redirects=False,
            ) as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as error:
            raise TelegramError(method, type(error).__name__) from None
        return self._result(method, response)


def _ensure_state(connection: Connection, tenant: str) -> dict[str, Any]:
    current = db.row(connection, telegram_state, tenant, STATE_ID)
    if current is not None:
        return current
    value = {
        "tenant_id": tenant,
        "id": STATE_ID,
        "update_offset": 0,
        "bot_username": None,
        "last_poll_at": None,
        "last_error": None,
        "enabled_at": now(),
        "updated_at": now(),
    }
    connection.execute(insert(telegram_state).values(**value))
    return value


def _set_state(service: Service, **values: Any) -> None:
    tenant = service.settings.telegram_tenant
    with service.db.transaction() as connection:
        _ensure_state(connection, tenant)
        connection.execute(
            update(telegram_state)
            .where(telegram_state.c.tenant_id == tenant, telegram_state.c.id == STATE_ID)
            .values(**values, updated_at=now())
        )


def _record_error(service: Service, error: TelegramError) -> None:
    LOGGER.warning("Telegram %s failed: %s", error.method, error.reason)
    reason = clean_error(f"{error.method}: {error.reason}", service.settings.telegram_bot_token)
    _set_state(service, last_error=reason)


def _chat(chat_id: str) -> int | str:
    return int(chat_id) if re.fullmatch(r"-?[0-9]{1,16}", chat_id) else chat_id


def _safe_call(service: Service, method: str, payload: dict[str, Any]) -> tuple[bool, Any]:
    """Best-effort Bot API call; failures are recorded token-free and never raised."""
    if not configured(service.settings):
        return False, None
    try:
        return True, BotApi(service.settings).call(method, payload)
    except TelegramError as error:
        _record_error(service, error)
        return False, None


def _send(
    service: Service, chat_id: str, text: str, markup: dict[str, Any] | None = None
) -> tuple[bool, int | None]:
    payload: dict[str, Any] = {
        "chat_id": _chat(chat_id),
        "text": text[:TEXT_LIMIT],
        "link_preview_options": {"is_disabled": True},
    }
    if markup is not None:
        payload["reply_markup"] = markup
    ok, result = _safe_call(service, "sendMessage", payload)
    message_id = result.get("message_id") if isinstance(result, dict) else None
    return ok, message_id if isinstance(message_id, int) else None


def _answer(service: Service, query_id: str, text: str) -> None:
    _safe_call(service, "answerCallbackQuery", {"callback_query_id": query_id, "text": text[:190]})


def _edit(service: Service, chat_id: str | None, message_id: int | None, text: str) -> None:
    if chat_id is None or message_id is None:
        return
    _safe_call(
        service,
        "editMessageText",
        {"chat_id": _chat(chat_id), "message_id": message_id, "text": text[:TEXT_LIMIT]},
    )


def _user_by_telegram_id(
    connection: Connection, tenant: str, telegram_user_id: str
) -> dict[str, Any] | None:
    found = (
        connection.execute(
            select(telegram_users).where(
                telegram_users.c.tenant_id == tenant,
                telegram_users.c.telegram_user_id == telegram_user_id,
            )
        )
        .mappings()
        .first()
    )
    return dict(found) if found else None


def _active(connection: Connection, user: dict[str, Any] | None) -> bool:
    """An approved Telegram user whose bot principal is active, unexpired and untampered."""
    if user is None or user["status"] != "approved" or not user["principal_id"]:
        return False
    principal = db.row(connection, db.principals, user["tenant_id"], user["principal_id"])
    if principal is None or principal["owner"] != BOT_OWNER:
        return False
    try:
        verify_lineage(connection, principal)
    except DomainError:
        return False
    return principal["roles"] == ROLES.get(user["role"] or "")


def _member(connection: Connection, tenant: str, telegram_user_id: str) -> dict[str, Any] | None:
    user = _user_by_telegram_id(connection, tenant, telegram_user_id)
    return user if _active(connection, user) else None


def _window() -> int:
    return int(time.time()) // 60


def _admit(connection: Connection, tenant: str, telegram_user_id: str) -> bool:
    identifier = f"telegram-user:{telegram_user_id}"
    window = _window()
    current = db.row(connection, db.rate_limits, tenant, identifier)
    if current is None:
        connection.execute(
            insert(db.rate_limits).values(tenant_id=tenant, id=identifier, window=window, count=1)
        )
        return True
    if current["window"] == window and current["count"] >= MESSAGES_PER_MINUTE:
        return False
    count = current["count"] + 1 if current["window"] == window else 1
    connection.execute(
        update(db.rate_limits)
        .where(db.rate_limits.c.tenant_id == tenant, db.rate_limits.c.id == identifier)
        .values(window=window, count=count)
    )
    return True


def _requester(tenant: str, telegram_user_id: str) -> PrincipalContext:
    """Audit attribution for a not-yet-approved Telegram sender. Grants nothing."""
    return PrincipalContext(tenant, f"telegram-user-{telegram_user_id}", (), "telegram")


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        key: user[key]
        for key in (
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
        )
    }


ACTIONS = {
    "payment.change_request": "change supplier payment details",
    "supplier.lookup": "look up supplier details",
    "invoice.compare": "compare invoices",
    "customer.export": "export customer data",
    "infrastructure.delete": "delete infrastructure",
}


def _request_summary(approval: dict[str, Any]) -> str:
    invocation = approval["invocation"] if isinstance(approval["invocation"], dict) else {}
    tool = invocation.get("tool", "")
    what = ACTIONS.get(tool, "run " + plain(tool, 60))
    resource = plain(invocation.get("resource", "an unknown resource"), 80)
    return f"{plain(approval['principal_id'], 64)} wants to {what} for {resource} (synthetic)"


def approval_text(approval: dict[str, Any]) -> str:
    invocation = approval["invocation"] if isinstance(approval["invocation"], dict) else {}
    arguments = invocation.get("arguments")
    lines = [f"Approval needed: {_request_summary(approval)}."]
    if isinstance(arguments, dict) and arguments.get("proposed_account_ref"):
        lines.append(f"Proposed account: {plain(arguments['proposed_account_ref'], 80)}.")
    lines += [
        f"Requested by {plain(approval['requester_id'], 64)}.",
        f"Expires {_when(approval['expires_at'])}.",
        f"Check code: {str(approval['digest'])[:8]}.",
        "Approve only if you expected this change. Each button works once.",
    ]
    return "\n".join(lines)


def _keyboard(token: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "Approve", "callback_data": f"a:{token}:y"},
                {"text": "Reject", "callback_data": f"a:{token}:n"},
            ]
        ]
    }


def _base_url(settings: Settings) -> str:
    return settings.public_url.rstrip("/")


def incident_text(incident: dict[str, Any], settings: Settings) -> str:
    return (
        f"New security issue {plain(incident['number'], 20)}: {plain(incident['title'], 120)}. "
        f"Severity {plain(incident['severity'], 20)}. "
        f"Open: {_base_url(settings)}/incidents/{plain(incident['id'], 80)}"
    )


def honeypot_text(session: dict[str, Any], settings: Settings) -> str:
    who = "An outside agent" if session["caller_class"] == "external" else "An agent"
    return (
        f"{who} ({plain(session['principal_id'], 64)}) was moved into the honeypot "
        "(fake environment). Real systems were not touched by it after the move. "
        f"Review: {_base_url(settings)}"
    )


def _decoy_time(session: dict[str, Any]) -> str | None:
    history = session["history"] if isinstance(session["history"], list) else []
    for entry in history:
        if isinstance(entry, dict) and entry.get("mode") == "DECOY" and entry.get("at"):
            return str(entry["at"])
    return None


START_SENT = "Request sent. A Hades Mirage administrator must approve you."
START_WAITING = "Your request is already waiting. A Hades Mirage administrator must approve you."
START_CLOSED = "Hades Mirage is not taking new access requests right now. Please try again later."
START_COOLDOWN = "Your last request was not approved. You can ask again later."
NOT_ALLOWED = (
    "Sorry, you cannot use that command. Send /start to ask for access or /status to check it."
)
UNKNOWN = "Hello. This is the Hades Mirage alert bot. Send /help to see what I can do."
HELP = (
    "Hades Mirage alert bot. Commands:\n"
    "/start - ask an administrator for access\n"
    "/status - see your access and role\n"
    "/issues - latest open security issues (analysts and approvers)\n"
    "/pending - operations waiting for approval (approvers)\n"
    "/help - this list\n"
    "Approvals made here are checked by Hades Mirage, recorded in the audit log and expire."
)
REFUSED = {
    "invalid": "This button is not valid for you. Nothing was changed.",
    "not_allowed": "You are not allowed to approve operations. Nothing was changed.",
    "used": "This button was already used. Nothing was changed.",
    "expired": "This button has expired. Send /pending for fresh buttons. Nothing was changed.",
}
DECISION_ERRORS = {
    "APPROVAL_STALE": "Not changed: this request was already decided, expired or no longer "
    "matches what you were shown.",
    "SELF_APPROVAL_DENIED": "Not changed: a separate reviewer must decide this request.",
    "NOT_FOUND": "Not changed: this request no longer exists.",
    "ROLE_REQUIRED": "Not changed: your role cannot approve operations.",
}


def _command(text: str) -> str:
    words = text.strip().split(maxsplit=1)
    if not words or not words[0].startswith("/"):
        return ""
    name = words[0].split("@", 1)[0].lower()
    return name if re.fullmatch(r"/[a-z_]{1,32}", name) else ""


def process_update(service: Service, incoming: Any) -> None:
    """Handle one Telegram update (from polling or the webhook). Replays are ignored."""
    if not configured(service.settings) or not isinstance(incoming, dict):
        return
    update_id = incoming.get("update_id")
    if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id < 0:
        return
    tenant = service.settings.telegram_tenant
    with service.db.transaction() as connection:
        state = _ensure_state(connection, tenant)
        if update_id < state["update_offset"]:
            return
        connection.execute(
            update(telegram_state)
            .where(telegram_state.c.tenant_id == tenant, telegram_state.c.id == STATE_ID)
            .values(update_offset=update_id + 1, updated_at=now())
        )
    if isinstance(incoming.get("callback_query"), dict):
        _handle_callback(service, incoming["callback_query"])
    elif isinstance(incoming.get("message"), dict):
        _handle_message(service, incoming["message"])


def _handle_message(service: Service, message: dict[str, Any]) -> None:
    sender, chat = message.get("from"), message.get("chat")
    if not isinstance(sender, dict) or not isinstance(chat, dict) or sender.get("is_bot") is True:
        return
    user_id, chat_id = _identifier(sender.get("id")), _identifier(chat.get("id"))
    if user_id is None or chat_id is None:
        return
    text = message.get("text")
    command = _command(text[:300] if isinstance(text, str) else "")
    tenant = service.settings.telegram_tenant
    with service.db.transaction() as connection:
        if not _admit(connection, tenant, user_id):
            return
    if chat.get("type") != "private":
        # Alerts go only to private chats so other group members never see them.
        if command:
            _send(service, chat_id, "Please talk to me in a private chat.")
        return
    if command == "/start":
        reply = _request_access(service, user_id, chat_id, sender)
    elif command == "/help":
        reply = HELP
    elif command == "/status":
        reply = _status_text(service, user_id)
    elif command == "/issues":
        reply = _issues_text(service, user_id)
    elif command == "/pending":
        reply = _send_pending(service, user_id)
    else:
        reply = UNKNOWN
    if reply:
        _send(service, chat_id, reply)


def _request_access(service: Service, user_id: str, chat_id: str, sender: dict[str, Any]) -> str:
    tenant = service.settings.telegram_tenant
    username = plain(sender.get("username") or "", 64) or None
    names = [sender.get("first_name"), sender.get("last_name")]
    display = plain(" ".join(str(item) for item in names if isinstance(item, str)), 128) or None
    profile = {"username": username, "display_name": display, "chat_id": chat_id}
    with service.db.transaction() as connection:
        user = _user_by_telegram_id(connection, tenant, user_id)
        if user is not None and user["status"] == "approved":
            return f"You already have access. Your role is {ROLE_WORDS.get(user['role'], 'none')}."
        if user is not None and user["status"] == "pending":
            connection.execute(
                update(telegram_users)
                .where(telegram_users.c.tenant_id == tenant, telegram_users.c.id == user["id"])
                .values(**profile)
            )
            return START_WAITING
        if user is not None and (user["decided_at"] or "") > _ago(REQUEST_COOLDOWN_SECONDS):
            return START_COOLDOWN
        pending = connection.execute(
            select(func.count()).where(
                telegram_users.c.tenant_id == tenant, telegram_users.c.status == "pending"
            )
        ).scalar_one()
        if pending >= MAX_PENDING_REQUESTS:
            return START_CLOSED
        values = {
            **profile,
            "status": "pending",
            "role": None,
            "requested_at": now(),
            "decided_at": None,
            "decided_by": None,
            "approved_at": None,
        }
        if user is None:
            identifier = uid()
            connection.execute(
                insert(telegram_users).values(
                    tenant_id=tenant,
                    id=identifier,
                    telegram_user_id=user_id,
                    principal_id=None,
                    last_notified_at=None,
                    **values,
                )
            )
        else:
            identifier = user["id"]
            connection.execute(
                update(telegram_users)
                .where(telegram_users.c.tenant_id == tenant, telegram_users.c.id == identifier)
                .values(**values)
            )
        service.audit(
            connection,
            _requester(tenant, user_id),
            "telegram.access_requested",
            identifier,
            {"telegram_user_id": user_id, "username": username},
        )
    return START_SENT


def _status_text(service: Service, user_id: str) -> str:
    tenant = service.settings.telegram_tenant
    with service.db.engine.connect() as connection:
        user = _user_by_telegram_id(connection, tenant, user_id)
        active = _active(connection, user)
    if user is None:
        return "You have not asked for access yet. Send /start to ask."
    if active:
        return f"You have access. Your role is {ROLE_WORDS.get(user['role'], 'none')}."
    return {
        "pending": "Your request is waiting for a Hades Mirage administrator.",
        "rejected": "Your request was not approved.",
        "revoked": "Your access was removed by an administrator.",
    }.get(user["status"], "You do not have access right now.")


def _issues_text(service: Service, user_id: str) -> str:
    tenant = service.settings.telegram_tenant
    with service.db.engine.connect() as connection:
        member = _member(connection, tenant, user_id)
        if member is None or member["role"] not in {"analyst", "approver"}:
            return NOT_ALLOWED
        items = db.rows(
            connection,
            select(db.incidents)
            .where(db.incidents.c.tenant_id == tenant, db.incidents.c.status != "resolved")
            .order_by(db.incidents.c.created_at.desc())
            .limit(5),
        )
    if not items:
        return "There are no open security issues right now."
    lines = ["Latest open security issues:"]
    for number, item in enumerate(items, 1):
        lines.append(
            f"{number}. {plain(item['number'], 20)}: {plain(item['title'], 100)}. "
            f"Severity {plain(item['severity'], 20)}, status {plain(item['status'], 20)}. "
            f"{_base_url(service.settings)}/incidents/{plain(item['id'], 80)}"
        )
    return "\n".join(lines)


def _create_action(
    connection: Connection, tenant: str, approval: dict[str, Any], user: dict[str, Any]
) -> str:
    token = secrets.token_urlsafe(24)
    # Older unused buttons for the same approval and user stop working.
    connection.execute(
        update(telegram_actions)
        .where(
            telegram_actions.c.tenant_id == tenant,
            telegram_actions.c.approval_id == approval["id"],
            telegram_actions.c.telegram_user_id == user["telegram_user_id"],
            telegram_actions.c.used_at.is_(None),
        )
        .values(used_at=now(), outcome="superseded")
    )
    connection.execute(
        insert(telegram_actions).values(
            tenant_id=tenant,
            id=token_hash(token),
            approval_id=approval["id"],
            approval_digest=approval["digest"],
            telegram_user_id=user["telegram_user_id"],
            chat_id=user["chat_id"],
            message_id=None,
            created_at=now(),
            expires_at=min(after(ACTION_TTL_SECONDS), approval["expires_at"]),
            used_at=None,
            outcome=None,
        )
    )
    return token


def _invalidate_actions(connection: Connection, tenant: str, user_id: str, reason: str) -> None:
    connection.execute(
        update(telegram_actions)
        .where(
            telegram_actions.c.tenant_id == tenant,
            telegram_actions.c.telegram_user_id == user_id,
            telegram_actions.c.used_at.is_(None),
        )
        .values(used_at=now(), outcome=reason)
    )


def _remember_message(service: Service, token: str, message_id: int | None) -> None:
    if message_id is None:
        return
    with service.db.transaction() as connection:
        connection.execute(
            update(telegram_actions)
            .where(
                telegram_actions.c.tenant_id == service.settings.telegram_tenant,
                telegram_actions.c.id == token_hash(token),
            )
            .values(message_id=str(message_id))
        )


def _send_pending(service: Service, user_id: str) -> str:
    tenant = service.settings.telegram_tenant
    prepared: list[tuple[str, str]] = []
    with service.db.transaction() as connection:
        member = _member(connection, tenant, user_id)
        if member is None or member["role"] != "approver":
            return NOT_ALLOWED
        approvals = db.rows(
            connection,
            select(db.approvals)
            .where(
                db.approvals.c.tenant_id == tenant,
                db.approvals.c.status == "pending",
                db.approvals.c.expires_at > now(),
            )
            .order_by(db.approvals.c.created_at.desc())
            .limit(5),
        )
        for approval in approvals:
            prepared.append(
                (_create_action(connection, tenant, approval, member), approval_text(approval))
            )
    if not prepared:
        return "Nothing is waiting for approval right now."
    for token, text in prepared:
        ok, message_id = _send(service, member["chat_id"], text, _keyboard(token))
        if ok:
            _remember_message(service, token, message_id)
    return ""


def _handle_callback(service: Service, query: dict[str, Any]) -> None:
    query_id, sender = query.get("id"), query.get("from")
    if not isinstance(query_id, str) or len(query_id) > 100 or not isinstance(sender, dict):
        return
    user_id = _identifier(sender.get("id"))
    if user_id is None:
        return
    message = query.get("message") if isinstance(query.get("message"), dict) else {}
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    chat_id = _identifier(chat.get("id"))
    raw_message_id = message.get("message_id")
    message_id = int(raw_message_id) if _identifier(raw_message_id) is not None else None
    data = query.get("data")
    match = CALLBACK.fullmatch(data) if isinstance(data, str) else None
    tenant = service.settings.telegram_tenant
    with service.db.transaction() as connection:
        if not _admit(connection, tenant, user_id):
            return
    if match is None:
        _answer(service, query_id, REFUSED["invalid"])
        return
    token, choice = match.groups()
    decision = "approve" if choice == "y" else "reject"
    action_id = token_hash(token)
    with service.db.transaction() as connection:
        action = db.row(connection, telegram_actions, tenant, action_id)
        member = _member(connection, tenant, user_id)
        reason = None
        if action is None or action["telegram_user_id"] != user_id:
            reason = "invalid"
        elif member is None or member["role"] != "approver":
            reason = "not_allowed"
        elif action["used_at"] is not None:
            reason = "used"
        elif action["expires_at"] <= now():
            reason = "expired"
        else:
            # Claim the one-time token before deciding so a retry or replay cannot decide twice.
            claimed = connection.execute(
                update(telegram_actions)
                .where(
                    telegram_actions.c.tenant_id == tenant,
                    telegram_actions.c.id == action_id,
                    telegram_actions.c.used_at.is_(None),
                )
                .values(used_at=now(), outcome="claimed")
            )
            if claimed.rowcount != 1:
                reason = "used"
        if reason is not None:
            actor = (
                PrincipalContext(tenant, member["principal_id"], (), "human")
                if member
                else _requester(tenant, user_id)
            )
            service.audit(
                connection,
                actor,
                "telegram.approval_decision",
                action["approval_id"] if action and reason != "invalid" else "telegram-callback",
                {"telegram_user_id": user_id, "decision": decision, "outcome": "refused_" + reason},
            )
    if reason is not None or action is None or member is None:
        _answer(service, query_id, REFUSED.get(reason or "invalid", REFUSED["invalid"]))
        if reason in {"used", "expired"}:
            _edit(service, chat_id, message_id, REFUSED[reason])
        return
    context = PrincipalContext(tenant, member["principal_id"], ("approver",), "human")
    try:
        result = service.decide_approval(
            context,
            action["approval_id"],
            ApprovalDecision(decision=decision, expected_digest=action["approval_digest"]),
            "telegram-" + action_id,
        )
        outcome = str(result["status"])
    except DomainError as error:
        result, outcome = None, error.code
    with service.db.transaction() as connection:
        connection.execute(
            update(telegram_actions)
            .where(telegram_actions.c.tenant_id == tenant, telegram_actions.c.id == action_id)
            .values(outcome=outcome[:60])
        )
        service.audit(
            connection,
            context,
            "telegram.approval_decision",
            action["approval_id"],
            {"telegram_user_id": user_id, "decision": decision, "outcome": outcome},
        )
    if result is not None:
        verb = "Approved" if outcome == "approved" else "Rejected"
        text = f"{verb} by you. Request: {_request_summary(result)}."
    else:
        text = DECISION_ERRORS.get(
            outcome, "Not changed: the request could not be decided. Open Hades Mirage."
        )
    _answer(service, query_id, text)
    _edit(service, chat_id, message_id, text)


def _deliver(
    service: Service, kind: str, object_id: str, user: dict[str, Any], item: dict[str, Any]
) -> bool:
    tenant = service.settings.telegram_tenant
    match = (
        telegram_deliveries.c.tenant_id == tenant,
        telegram_deliveries.c.kind == kind,
        telegram_deliveries.c.object_id == object_id,
        telegram_deliveries.c.telegram_user_id == user["telegram_user_id"],
    )
    token = None
    markup = None
    with service.db.transaction() as connection:
        if connection.execute(select(telegram_deliveries.c.id).where(*match)).first():
            return False
        connection.execute(
            insert(telegram_deliveries).values(
                tenant_id=tenant,
                id=uid(),
                kind=kind,
                object_id=object_id,
                telegram_user_id=user["telegram_user_id"],
                status="sending",
                created_at=now(),
            )
        )
        if kind == "approval":
            current = db.row(connection, db.approvals, tenant, object_id)
            if current is None or current["status"] != "pending" or current["expires_at"] <= now():
                connection.execute(
                    update(telegram_deliveries).where(*match).values(status="skipped")
                )
                return False
            token = _create_action(connection, tenant, current, user)
            markup = _keyboard(token)
            text = approval_text(current)
        elif kind == "incident":
            text = incident_text(item, service.settings)
        else:
            text = honeypot_text(item, service.settings)
    ok, message_id = _send(service, user["chat_id"], text, markup)
    with service.db.transaction() as connection:
        connection.execute(
            update(telegram_deliveries).where(*match).values(status="sent" if ok else "failed")
        )
        if ok:
            connection.execute(
                update(telegram_users)
                .where(telegram_users.c.tenant_id == tenant, telegram_users.c.id == user["id"])
                .values(last_notified_at=now())
            )
    if ok and token is not None:
        _remember_message(service, token, message_id)
    return ok


def tick(service: Service) -> int:
    """Send new notifications once per (kind, object, user). Returns the number sent."""
    if not configured(service.settings):
        return 0
    tenant = service.settings.telegram_tenant
    with service.db.transaction() as connection:
        state = _ensure_state(connection, tenant)
    with service.db.engine.connect() as connection:
        users = db.rows(
            connection,
            select(telegram_users)
            .where(telegram_users.c.tenant_id == tenant, telegram_users.c.status == "approved")
            .limit(200),
        )
        members = [user for user in users if _active(connection, user)]
        if not members:
            return 0
        floor = max(state["enabled_at"], _ago(NOTIFY_MAX_AGE_SECONDS))
        since = {
            user["id"]: max(floor, user["approved_at"] or user["decided_at"] or floor)
            for user in members
        }
        earliest = min(since.values())
        approvals = db.rows(
            connection,
            select(db.approvals)
            .where(
                db.approvals.c.tenant_id == tenant,
                db.approvals.c.status == "pending",
                db.approvals.c.expires_at > now(),
                db.approvals.c.created_at > earliest,
            )
            .order_by(db.approvals.c.created_at)
            .limit(50),
        )
        incidents = db.rows(
            connection,
            select(db.incidents)
            .where(db.incidents.c.tenant_id == tenant, db.incidents.c.created_at > earliest)
            .order_by(db.incidents.c.created_at)
            .limit(50),
        )
        sessions = db.rows(
            connection,
            select(db.sessions)
            .where(
                db.sessions.c.tenant_id == tenant,
                db.sessions.c.route_mode.in_(["DECOY", "TERMINATED"]),
            )
            .order_by(db.sessions.c.created_at.desc())
            .limit(100),
        )
    jobs: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
    for user in members:
        for approval in approvals:
            if user["role"] == "approver" and approval["created_at"] > since[user["id"]]:
                jobs.append(("approval", approval["id"], user, approval))
        for incident in incidents:
            if incident["created_at"] > since[user["id"]]:
                jobs.append(("incident", incident["id"], user, incident))
        for session in sessions:
            moved = _decoy_time(session)
            if moved is not None and moved > since[user["id"]]:
                jobs.append(("honeypot", session["id"], user, session))
    return sum(_deliver(service, *job) for job in jobs)


def prune(service: Service) -> None:
    tenant = service.settings.telegram_tenant
    with service.db.transaction() as connection:
        connection.execute(
            delete(telegram_actions).where(
                telegram_actions.c.tenant_id == tenant,
                telegram_actions.c.expires_at < _ago(7 * 86400),
            )
        )
        # Items older than NOTIFY_MAX_AGE are never notified again, so old receipts can go.
        connection.execute(
            delete(telegram_deliveries).where(
                telegram_deliveries.c.tenant_id == tenant,
                telegram_deliveries.c.created_at < _ago(2 * NOTIFY_MAX_AGE_SECONDS),
            )
        )


def _grant(
    service: Service,
    connection: Connection,
    context: PrincipalContext,
    user: dict[str, Any],
    role: str,
) -> str:
    """Create or reactivate the bot-only principal. Telegram never receives security_admin."""
    principal_id = f"telegram-{user['telegram_user_id']}"
    name = plain(user["display_name"] or user["username"] or principal_id, 90)
    existing = db.row(connection, db.principals, context.tenant_id, principal_id)
    values = {
        "name": f"Telegram: {name}",
        "roles": list(ROLES[role]),
        "status": "active",
        "expires_at": after(PRINCIPAL_TTL_SECONDS),
    }
    if existing is None:
        connection.execute(
            insert(db.principals).values(
                tenant_id=context.tenant_id,
                id=principal_id,
                kind="human",
                scopes=[],
                parent_id=None,
                root_id=principal_id,
                depth=0,
                identity_epoch=1,
                owner=BOT_OWNER,
                created_at=now(),
                **values,
            )
        )
    elif (
        existing["kind"] != "human"
        or existing["parent_id"] is not None
        or existing["owner"] != BOT_OWNER
    ):
        raise DomainError(
            409, "TELEGRAM_PRINCIPAL_CONFLICT", "Another identity already uses this principal ID"
        )
    else:
        connection.execute(
            update(db.principals)
            .where(
                db.principals.c.tenant_id == context.tenant_id, db.principals.c.id == principal_id
            )
            .values(**values, identity_epoch=existing["identity_epoch"] + 1)
        )
    # Bot principals act only through verified Telegram callbacks, never with bearer credentials.
    connection.execute(
        delete(db.credentials).where(
            db.credentials.c.tenant_id == context.tenant_id,
            db.credentials.c.principal_id == principal_id,
        )
    )
    return principal_id


def _admin_change(
    service: Service,
    context: PrincipalContext,
    user_id: str,
    route: str,
    body: dict[str, Any],
    key: str,
    change: Any,
) -> dict[str, Any]:
    context.require("security_admin")
    notice = None
    with service.db.transaction() as connection:
        previous = service.idempotent_get(connection, context, route, key, body)
        if previous is not None:
            return previous
        user = service.required(connection, telegram_users, context.tenant_id, user_id)
        values, action, details, notice = change(connection, user)
        connection.execute(
            update(telegram_users)
            .where(telegram_users.c.tenant_id == context.tenant_id, telegram_users.c.id == user_id)
            .values(**values)
        )
        result = public_user({**user, **values})
        service.audit(
            connection,
            context,
            action,
            user_id,
            {"telegram_user_id": user["telegram_user_id"], **details},
        )
        service.idempotent_put(connection, context, route, key, body, result)
    if notice and context.tenant_id == service.settings.telegram_tenant:
        _send(service, user["chat_id"], notice)
    return result


def decide_access(
    service: Service, context: PrincipalContext, user_id: str, body: AccessDecision, key: str
) -> dict[str, Any]:
    def change(connection: Connection, user: dict[str, Any]) -> tuple[Any, ...]:
        if user["status"] != "pending":
            raise DomainError(
                409, "TELEGRAM_REQUEST_NOT_PENDING", "Only a pending access request can be decided"
            )
        stamp = now()
        if body.decision == "reject":
            values = {
                "status": "rejected",
                "role": None,
                "decided_at": stamp,
                "decided_by": context.principal_id,
                "approved_at": None,
            }
            return (
                values,
                "telegram.user_rejected",
                {},
                "Your Hades Mirage access was not approved.",
            )
        role = body.role or "viewer"  # the model already requires a role for approval
        principal_id = _grant(service, connection, context, user, role)
        values = {
            "status": "approved",
            "role": role,
            "principal_id": principal_id,
            "decided_at": stamp,
            "decided_by": context.principal_id,
            "approved_at": stamp,
        }
        notice = (
            f"Access approved. Your role is {ROLE_WORDS[role]}. Send /help to see what you can do."
        )
        return values, "telegram.user_approved", {"role": role}, notice

    route = f"/telegram/users/{user_id}/decision"
    return _admin_change(service, context, user_id, route, body.model_dump(), key, change)


def change_role(
    service: Service, context: PrincipalContext, user_id: str, body: RoleChange, key: str
) -> dict[str, Any]:
    def change(connection: Connection, user: dict[str, Any]) -> tuple[Any, ...]:
        if user["status"] != "approved":
            raise DomainError(
                409, "TELEGRAM_USER_NOT_APPROVED", "Only an approved Telegram user has a role"
            )
        _grant(service, connection, context, user, body.role)
        if body.role != "approver":
            _invalidate_actions(connection, context.tenant_id, user["telegram_user_id"], "role")
        details = {"from": user["role"], "to": body.role}
        notice = f"Your Hades Mirage role is now {ROLE_WORDS[body.role]}."
        return {"role": body.role}, "telegram.user_role_changed", details, notice

    route = f"/telegram/users/{user_id}/role"
    return _admin_change(service, context, user_id, route, body.model_dump(), key, change)


def revoke(service: Service, context: PrincipalContext, user_id: str, key: str) -> dict[str, Any]:
    def change(connection: Connection, user: dict[str, Any]) -> tuple[Any, ...]:
        if user["status"] not in {"approved", "pending"}:
            raise DomainError(
                409, "TELEGRAM_USER_NOT_ACTIVE", "Only a pending or approved user can be revoked"
            )
        if user["principal_id"]:
            connection.execute(
                update(db.principals)
                .where(
                    db.principals.c.tenant_id == context.tenant_id,
                    db.principals.c.id == user["principal_id"],
                    db.principals.c.owner == BOT_OWNER,
                )
                .values(status="suspended", identity_epoch=db.principals.c.identity_epoch + 1)
            )
        _invalidate_actions(connection, context.tenant_id, user["telegram_user_id"], "revoked")
        values = {
            "status": "revoked",
            "role": None,
            "decided_at": now(),
            "decided_by": context.principal_id,
            "approved_at": None,
        }
        notice = "Your access to Hades Mirage alerts was removed by an administrator."
        return values, "telegram.user_revoked", {"previous_status": user["status"]}, notice

    route = f"/telegram/users/{user_id}/revoke"
    return _admin_change(service, context, user_id, route, {}, key, change)


def send_test(service: Service, context: PrincipalContext, key: str) -> dict[str, Any]:
    context.require("security_admin")
    if not configured(service.settings) or context.tenant_id != service.settings.telegram_tenant:
        raise DomainError(
            409, "TELEGRAM_NOT_CONFIGURED", "Configure a Telegram bot token and mode first"
        )
    route = "/telegram/test"
    with service.db.transaction() as connection:
        previous = service.idempotent_get(connection, context, route, key, {})
        if previous is not None:
            return previous
    with service.db.engine.connect() as connection:
        users = db.rows(
            connection,
            select(telegram_users)
            .where(
                telegram_users.c.tenant_id == context.tenant_id,
                telegram_users.c.status == "approved",
            )
            .limit(200),
        )
        members = [user for user in users if _active(connection, user)]
    sent = 0
    for user in members:
        sent += _send(
            service, user["chat_id"], "Test message from Hades Mirage. No action needed."
        )[0]
    result = {"sent": sent, "failed": len(members) - sent}
    with service.db.transaction() as connection:
        previous = service.idempotent_get(connection, context, route, key, {})
        if previous is not None:
            return previous
        service.audit(connection, context, "telegram.test_sent", "telegram", result)
        service.idempotent_put(connection, context, route, key, {}, result)
    return result


def status(service: Service, tenant: str) -> dict[str, Any]:
    settings = service.settings
    with service.db.engine.connect() as connection:
        state = db.row(connection, telegram_state, tenant, STATE_ID) or {}
        counts = dict(
            connection.execute(
                select(telegram_users.c.status, func.count())
                .where(telegram_users.c.tenant_id == tenant)
                .group_by(telegram_users.c.status)
            ).all()
        )
    return {
        "configured": configured(settings),
        "mode": settings.telegram_mode,
        "bot_username": state.get("bot_username"),
        "last_poll_at": state.get("last_poll_at"),
        "last_error": state.get("last_error"),
        "counts": {"pending": counts.get("pending", 0), "approved": counts.get("approved", 0)},
        "public_url": settings.public_url,
    }


def list_users(service: Service, tenant: str) -> dict[str, Any]:
    with service.db.engine.connect() as connection:
        items = db.rows(
            connection,
            select(telegram_users)
            .where(telegram_users.c.tenant_id == tenant)
            .order_by(telegram_users.c.requested_at.desc())
            .limit(200),
        )
    return {"items": [public_user(item) for item in items]}


def identify(service: Service) -> None:
    """Read the bot username and, in polling mode, remove any webhook so getUpdates works."""
    api = BotApi(service.settings)
    me = api.call("getMe", {})
    username = me.get("username") if isinstance(me, dict) else None
    if isinstance(username, str) and re.fullmatch(r"[A-Za-z0-9_]{1,64}", username):
        _set_state(service, bot_username=username)
    if service.settings.telegram_mode == "polling":
        api.call("deleteWebhook", {"drop_pending_updates": False})
    elif service.settings.public_url.startswith("https://"):
        api.call(
            "setWebhook",
            {
                "url": _base_url(service.settings) + "/telegram/webhook",
                "secret_token": service.settings.telegram_webhook_secret,
                "allowed_updates": ["message", "callback_query"],
                "max_connections": 5,
            },
        )
    else:
        raise TelegramError("setWebhook", "webhook mode needs an https public_url")


def _offset(service: Service) -> int:
    with service.db.transaction() as connection:
        return int(_ensure_state(connection, service.settings.telegram_tenant)["update_offset"])


async def poll_once(service: Service, timeout: int = POLL_TIMEOUT_SECONDS) -> int:
    """One getUpdates long-poll (<= 25 s). Cancelling the task aborts the request at once."""
    payload = {
        "offset": await asyncio.to_thread(_offset, service),
        "timeout": max(0, min(timeout, 25)),
        "limit": 50,
        "allowed_updates": ["message", "callback_query"],
    }
    result = await BotApi(service.settings).acall("getUpdates", payload, read=timeout + 5)
    updates = result if isinstance(result, list) else []
    for item in updates[:100]:
        await asyncio.to_thread(process_update, service, item)
    await asyncio.to_thread(_set_state, service, last_poll_at=now(), last_error=None)
    return len(updates)


async def _poll_loop(service: Service) -> None:
    delay = 1.0
    while True:
        try:
            if not await poll_once(service):
                await asyncio.sleep(1)
            delay = 1.0
        except TelegramError as error:
            await asyncio.to_thread(_record_error, service, error)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)
        except Exception as error:
            LOGGER.error("Telegram polling unavailable: %s", type(error).__name__)
            await asyncio.sleep(5)


async def _tick_loop(service: Service) -> None:
    rounds = 0
    while True:
        try:
            if rounds % 600 == 0:
                await asyncio.to_thread(identify, service)
        except TelegramError as error:
            await asyncio.to_thread(_record_error, service, error)
        except Exception as error:
            LOGGER.error("Telegram setup unavailable: %s", type(error).__name__)
        try:
            await asyncio.to_thread(tick, service)
            if rounds % 600 == 0:
                await asyncio.to_thread(prune, service)
        except Exception as error:
            LOGGER.error("Telegram notifier unavailable: %s", type(error).__name__)
        rounds += 1
        await asyncio.sleep(TICK_SECONDS)


def enabled(settings: Settings) -> bool:
    return configured(settings)


async def run(service: Service) -> None:
    """Background bot worker; separate from the outbox worker and cancelled on shutdown."""
    tasks = [asyncio.create_task(_tick_loop(service))]
    if service.settings.telegram_mode == "polling":
        tasks.append(asyncio.create_task(_poll_loop(service)))
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def register_telegram_routes(app: FastAPI, service: Service) -> None:
    from mirage.api import Context, Key

    @app.get("/v1/telegram")
    def telegram_status(context: Context) -> dict[str, Any]:
        context.require("analyst", "approver", "security_admin")
        return status(service, context.tenant_id)

    @app.get("/v1/telegram/users")
    def telegram_user_list(context: Context) -> dict[str, Any]:
        context.require("security_admin")
        return list_users(service, context.tenant_id)

    @app.post("/v1/telegram/users/{user_id}/decision")
    def telegram_user_decision(
        user_id: str, body: AccessDecision, context: Context, key: Key
    ) -> dict[str, Any]:
        return decide_access(service, context, user_id, body, key)

    @app.post("/v1/telegram/users/{user_id}/role")
    def telegram_user_role(
        user_id: str, body: RoleChange, context: Context, key: Key
    ) -> dict[str, Any]:
        return change_role(service, context, user_id, body, key)

    @app.post("/v1/telegram/users/{user_id}/revoke")
    def telegram_user_revoke(
        user_id: str, body: EmptyBody, context: Context, key: Key
    ) -> dict[str, Any]:
        return revoke(service, context, user_id, key)

    @app.post("/v1/telegram/test")
    def telegram_test(body: EmptyBody, context: Context, key: Key) -> dict[str, Any]:
        return send_test(service, context, key)

    @app.post("/telegram/webhook")
    async def telegram_webhook(request: Request) -> dict[str, bool]:
        settings = service.settings
        if settings.telegram_mode != "webhook" or not configured(settings):
            raise DomainError(404, "NOT_FOUND", "Telegram webhook is not enabled")
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        expected = settings.telegram_webhook_secret
        if len(expected) < 24 or not hmac.compare_digest(supplied.encode(), expected.encode()):
            raise DomainError(401, "TELEGRAM_SECRET_INVALID", "Webhook secret is missing or wrong")
        raw = await request.body()
        if len(raw) > MAX_UPDATE_BYTES:
            raise DomainError(413, "BODY_TOO_LARGE", "Telegram update exceeds the bounded size")
        try:
            incoming = json.loads(raw)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise DomainError(400, "INVALID_JSON", "Malformed Telegram update") from None
        await asyncio.to_thread(process_update, service, incoming)
        return {"ok": True}
