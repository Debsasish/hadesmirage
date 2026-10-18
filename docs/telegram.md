# Telegram bot (optional)

Hades Mirage can send alerts to Telegram and let approved people approve or reject pending
operations with buttons. It is **off by default**. This page explains how to switch it on, what it
does, and what it does not do.

Status: implemented and tested with a fake Telegram server (`tests/test_telegram.py`, mocked with
`httpx.MockTransport`). It has **not** been run against the real Telegram service in this
repository, because no bot token was available.

## What people can do in Telegram

| Command | Who | What happens |
|---|---|---|
| `/start` | anyone | Sends an access request. Reply: "Request sent. A Hades Mirage administrator must approve you." |
| `/status` | anyone | Shows whether the request is waiting, approved, rejected or removed, and the role. |
| `/help` | anyone | Lists the commands. |
| `/issues` | analyst, approver | Latest 5 open (not resolved) security issues with links. |
| `/pending` | approver | Operations waiting for approval, each with **Approve** / **Reject** buttons. |

People who are not approved only get short, polite, generic replies. The bot answers only in
private chats, so alerts never land in a group.

Alerts the bot sends by itself (each one only once per person):

- **Approval needed** (approvers only): who wants to do what, on which synthetic resource, who
  asked, when it expires, and the first 8 characters of the approval check code. Buttons:
  Approve / Reject.
- **New security issue** (all approved users): number, title, severity and a link
  (`<public_url>/incidents/<id>`).
- **Honeypot** (all approved users): an agent was moved into the honeypot (fake environment);
  real systems were not touched by it after the move.
- **Access decisions** go to the person who asked.

Only items created after the integration was first used **and** after the person was approved are
sent, and nothing older than 24 hours, so switching the bot on does not flood people with old
items.

## Roles

Administrators pick one role when approving a request:

| Telegram role | Hades Mirage roles given | Can |
|---|---|---|
| viewer | `viewer` | receive alerts |
| analyst | `analyst` | alerts + `/issues` |
| approver | `approver` | alerts + `/issues` + `/pending` + approval buttons |

Telegram can never give `security_admin`. Each approved person gets a bot-only identity called
`telegram-<telegram user id>`. It has no password, no API token and cannot sign in to the console.

## Switch it on (about 5 minutes)

1. In Telegram, talk to **@BotFather**, send `/newbot`, and copy the token it gives you.
2. Put these lines in your `.env` file (never commit this file):

   ```
   MIRAGE_TELEGRAM_MODE=polling
   MIRAGE_TELEGRAM_BOT_TOKEN=<token from BotFather>
   MIRAGE_PUBLIC_URL=http://127.0.0.1:8787
   ```

3. Restart Hades Mirage (`python -m mirage run`).
4. In Telegram, open your bot and send `/start`.
5. As an administrator (a user with `security_admin`), approve the request:

   ```
   GET  /v1/telegram/users                      -> find the request "id"
   POST /v1/telegram/users/<id>/decision         {"decision": "approve", "role": "approver"}
   ```

   (Send an `Idempotency-Key` header with every POST.) The person gets a Telegram message with
   their role.
6. Optional check: `POST /v1/telegram/test` with body `{}` sends a test message to every approved
   person and returns `{"sent": n, "failed": n}`.

**Polling mode** works from a laptop or private network: Hades Mirage asks Telegram for new
messages (long poll of 20 seconds), and needs outbound HTTPS to `api.telegram.org`. Corporate
proxy settings from the environment (`HTTPS_PROXY`) are honoured. Polling mode removes any old
webhook so polling can work.

**Webhook mode** is for a public HTTPS deployment:

```
MIRAGE_TELEGRAM_MODE=webhook
MIRAGE_TELEGRAM_BOT_TOKEN=<token>
MIRAGE_TELEGRAM_WEBHOOK_SECRET=<24+ random characters: A-Z a-z 0-9 _ ->
MIRAGE_PUBLIC_URL=https://your-host.example
```

Hades Mirage registers `<public_url>/telegram/webhook` with Telegram when `public_url` starts with
`https://`. Every webhook call must carry the header `X-Telegram-Bot-Api-Secret-Token` with the
secret; otherwise it gets `401`. The public host must also be allowed by the deployment's host
checks.

## Admin API

All routes need a normal Hades Mirage sign-in. Changes need `security_admin` and an
`Idempotency-Key` header, and are written to the audit log.

| Route | Who | Result |
|---|---|---|
| `GET /v1/telegram` | analyst, approver, security_admin | `{configured, mode, bot_username, last_poll_at, last_error, counts: {pending, approved}, public_url}` |
| `GET /v1/telegram/users` | security_admin | `{items: [{id, telegram_user_id, username, display_name, status, role, requested_at, decided_at, decided_by, last_notified_at}]}` |
| `POST /v1/telegram/users/{id}/decision` | security_admin | body `{"decision": "approve"\|"reject", "role": "viewer"\|"analyst"\|"approver"\|null}`; role is required to approve. Returns the user. |
| `POST /v1/telegram/users/{id}/role` | security_admin | body `{"role": ...}`; updates the bot identity and tells the person. |
| `POST /v1/telegram/users/{id}/revoke` | security_admin | body `{}`; status `revoked`, bot identity suspended, unused buttons cancelled, person told. |
| `POST /v1/telegram/test` | security_admin | body `{}`; returns `{sent, failed}`. |
| `POST /telegram/webhook` | Telegram only (secret header) | webhook mode only; returns `{"ok": true}`. |

`telegram_user_id` is returned as a string (Telegram IDs can exceed what JavaScript numbers hold
exactly). `username` and `display_name` come from Telegram and are untrusted: show them as plain
text only.

## How the approval buttons stay safe

- Each button carries a random one-time code (`a:<code>:y` or `a:<code>:n`). Only a hash of the
  code is stored. The code is bound to one approval, its exact check code (digest) and one
  Telegram person, and expires within 30 minutes (or earlier, when the approval expires).
- When a button is pressed, Hades Mirage checks outside any AI model that the sender is the same
  Telegram person, that they are still approved with the approver role, that their bot identity is
  active, and that the code is unused and unexpired. It marks the code used **before** deciding,
  so a replay or retry cannot decide twice.
- The decision itself goes through the normal approval rules (`decide_approval`): separate
  reviewer, still pending, not expired, same digest and same policy version. If anything changed,
  nothing is approved and the person sees a plain explanation.
- Changing a person's role away from approver, or revoking them, cancels their unused buttons.
- Every button press, accepted or refused, is recorded as `telegram.approval_decision` in the audit
  log. Other audit entries: `telegram.access_requested`, `telegram.user_approved`,
  `telegram.user_rejected`, `telegram.user_role_changed`, `telegram.user_revoked`,
  `telegram.test_sent`.

## Other safety rules

- Messages are plain text (no HTML or Markdown parsing). Untrusted text is shortened and control
  characters are removed. Messages never contain secrets, access codes or full digests.
- The bot token is never stored in the database, never returned by the API and never logged. HTTP
  client logs have the `/bot<token>` part of URLs replaced with `/bot[redacted]`. Errors are
  stored as short, token-free text in `last_error`.
- Rate limits: 20 messages or button presses per Telegram person per minute; at most 50 waiting
  access requests in total; a rejected or removed person can ask again after one hour.
- Webhook requests are limited to 32 KB and replayed Telegram updates are ignored.
- Approving in Telegram is a convenience for the existing approval step. It does not prove that
  network-level (TCP) access is authorised, and it does not change how the gateway enforces rules.

## Known limits

- **Live delivery not yet verified.** A real bot token was configured locally on 18 October, but
  this machine's secure web gateway redirects `api.telegram.org` to a block page. **Connect →
  Telegram approvals & alerts** shows "Telegram is blocked on this network". Use an allowed network
  or the Cloud Run deployment, then run `POST /v1/telegram/test`. Do not bypass the policy.
- The bot verifies TLS with the operating-system trust store, so corporate inspection roots
  work, and it never follows redirects. On networks that inspect TLS, the inspecting proxy can still
  see Bot API request paths, which contain the bot token. Rotate the token if that is not
  acceptable, and always rotate a token that was pasted into chat or tickets.
- Alerts are sent at most once. If Telegram is down at that moment the alert is not retried;
  approvers can still use `/pending` or the console.
- One Telegram tenant per installation (`MIRAGE_TELEGRAM_TENANT`, default `tenant-demo`).
- New tables (`telegram_users`, `telegram_actions`, `telegram_deliveries`, `telegram_state`) are
  part of schema revision 4 and are created automatically by `python -m mirage migrate` or at
  start-up.
