# Native setup and operations

## Prerequisites and start

Windows, Python 3.12+ and a Node.js version supported by the locked tooling (22.13+ or a supported newer release). No Docker, Kubernetes, cloud account, gateway process or model credentials are needed for P1-native.

From the project root:

```powershell
.\setup.cmd
.\start.cmd
```

`setup.cmd` creates a project-local virtual environment, installs the exact Python lock and npm lock, builds the console, and runs schema migrations. It does not install global packages. On machines where PowerShell blocks `npm.ps1`, use `npm.cmd`.

The launcher starts only two owned child processes: the API/console on `127.0.0.1:8787` and the signed synthetic backend on `127.0.0.1:8788`. It verifies both before reporting readiness and refuses occupied ports instead of stopping another process. Ctrl+C stops only those children.

The console is served by FastAPI from the built assets. Choose a fixture identity at sign-in:

| Identity | Authority |
| --- | --- |
| admin / Alex Morgan | Analyst actions, policy drafts/activation, laboratory scenarios, engagement configuration |
| analyst / Jordan Lee | Tenant-scoped cases, notes, investigation, export, restriction and termination |
| approver / Sam Rivera | Analyst access plus separate approval and policy-review decisions |

The generated access code is printed by the launcher and retained in `.local\runtime-secrets.json`. Native workload and producer credentials are generated in `.local\fixture-credentials.json`. These files are ignored by source control. Do not publish them, use these fixture identities with real records, or expose the native profile publicly.

Browser authentication uses an HttpOnly, SameSite=Strict cookie plus a session-bound CSRF header and allowed-Origin checks for mutation. The cookie is intentionally non-Secure on loopback HTTP; this is not an Internet-ready authentication deployment. Workload bearer tokens are hashed in the authoritative store. Client-supplied administrator, tenant, identity and route headers do not grant authority.

## Development

```powershell
.\.venv\Scripts\python.exe -m mirage run --empty
```

In another terminal:

```powershell
Set-Location apps\dashboard
npm.cmd run dev
```

Vite proxies only the known API/auth routes to the native API. The separate backend is not a generic URL proxy. For a production asset build, run `npm.cmd run build` and restart the native launcher when backend source changes.

The launcher normally seeds recorded laboratory scenarios once. These are real local HTTP requests over synthetic records, not invented incident rows or fabricated metrics. To add a fresh sequence after TTL expiry:

```powershell
.\.venv\Scripts\python.exe -m mirage demo
```

## Workspace and appearance

The overview is a search-led SOC workspace. Search **Cases** by reference, signal or identity, or select **Events** to search stored event IDs/types. These are bounded text filters, not an SPL parser, shell or live SIEM connection. Search and severity drill-down links clear unrelated saved filters; ordinary navigation preserves saved filters, and subsequent filter edits survive reload.

The analyst queue supports Up/Down, Home and End selection. Its persistent investigation pane separates **Summary**, **Evidence** and **Route**. In Route, **Focus route lens** opens a larger read-only view of the selected session history. Its slider and checkpoint buttons inspect recorded states; the latest received route is shown separately. Inspecting an earlier production state never restores access or replays an operation. Only existing authorized response controls can change routing.

Use the workspace bar to collapse navigation and the product header to switch themes or open workspace search. Data and evidence surfaces are opaque in both themes. **Settings → Appearance → Translucent surfaces** controls an optional toolbar material only; the preference stays in this browser and does not update enforcement configuration. Unsupported backdrop filtering and reduced-transparency preferences retain solid readable surfaces. Overview refresh and pause/resume remain available on desktop, tablet and phone. Pausing auto refresh pauses display queries only, not enforcement, collection or the durable worker.

## Live attack map

**Attack map** opens with a live, left-to-right traffic map built only from recorded events, cases, approvals, route history and the independent backend ledger (`GET /v1/attack-map?hours=1|24|168|720&origin=all|live|laboratory`, analyst role):

- **Who → Front door checks → Decision → What happened → Response.** Outside and internal agents send requests through the Layer 7 checks; lines split into *Allowed*, *Needs approval* and *Blocked*. Blocked traffic that matches a fixed rule becomes *Attack spotted*, then *Access limited* and *Honeypot*. A separate purple line counts requests answered by the honeypot. Line thickness follows the amount of traffic; numbers on lines are requests (left of *Attack spotted*) or agents/sessions (after it).
- **Business systems** counts actions in the independent synthetic backend ledger, not Mirage's own claims. Its badge shows how many actions happened after an agent was contained; this must be zero. If the ledger is unreachable the map says so instead of guessing.
- **AI explanation** is drawn off to the side on purpose: AI can explain a case but has no line into blocking or the honeypot.
- Select any step for a plain or technical explanation, counts, top reasons/rules/tools and the attackers that passed through it. In **Who is attacking**, **Show path** dims everything else and replays that agent's route step by step; **Open issue** opens the issue drawer. **What just happened** is a live feed (auto-refresh every 10 seconds; **Live/Paused** also stops the flow animation). Reduced-motion settings disable animation.
- The **Plain view / Technical view** switch changes every label (for example *Blocked* ↔ `deny`, *Honeypot* ↔ `DECOY · Wasm`).

Attacker-supplied text (snippets, resources, payloads) is never copied into the map. The proposed mTLS gateway is not drawn as live traffic; it remains a dashed proposal in **System architecture** further down the same page.

## AI workflows and live provider setup

### Plain view, attack graphs and Ask Mirage AI

Use **Plain view / Technical view** in the top bar (or inside any issue) to switch every investigation between everyday language and exact technical records. Open **Boards** for open issues by severity, average issue age, attackers contained, AI coverage, top issues and the 30-day trend. Select a top issue or **Preview** in **Issues** to open the Wiz-style drawer: banner, plain story, attack chain, suggested AI questions, an interactive **attack path visualization**, a step-by-step "What happened" timeline, AI analysis and raw evidence. Graph nodes and steps are generated from recorded events, route history and backend links; they never invent traffic.

**Ask Mirage AI** (bottom-left) answers workspace questions with links to real issues, or issue questions with cited evidence. Workspace chat history is private to the signed-in user; issue questions are shared case records. Fixture/demo answers are labelled as such.

### Configure the AI in the portal

A security administrator can choose **Demo mode**, **Google Gemini** (shown as *Vertex AI*, or *server API key* when one is configured) or **AI off** in **Settings → AI provider & safeguards**, then set the project ID, region and model (`gemini-3.8-flash`, `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-2.5-flash-lite` suggestions, or **Discover available models** for a live Vertex list when Gemini is approved). Sending evidence to Gemini requires a separate explicit acknowledgement. **Let AI automatically review every new issue** runs a bounded advisory investigation for issues created after it is enabled. Saved settings are versioned and audited, apply without restart and override environment defaults. Credentials are never entered in the browser. The server uses either its Google workload identity (Application Default Credentials locally, the Cloud Run service account in Google Cloud) with a project ID, or a server-side **Gemini API (Google AI Studio) key** from the ignored `.env` (`MIRAGE_GEMINI_API_KEY`). With a key, the project ID is optional and Settings shows *Credential: Server API key (hidden) · Gemini API (AI Studio)*. **Discover available models** then lists the models that key can use. The key is never returned by the API, written to logs or placed in model context.

Behaviour detection and honeypot diversion stay deterministic: rules block forbidden requests, recognise repeated probing and move eligible outside agents into the honeypot automatically. AI auto-review explains those cases but cannot block, approve, route or restore access.

### Telegram and Google Cloud

[Telegram approvals](telegram.md) explains bot setup, access requests, administrator role assignment (viewer, analyst, approver) and one-time Approve/Reject buttons. **Connect → Telegram approvals & alerts** shows waiting and approved people. [Google Cloud deployment](../deploy/gcp/README.md) covers Cloud Run source deployment with buildpacks (no Dockerfile/local Docker), Vertex AI service identity, Secret Manager and Google Workspace sign-in through IAP.

### Fixture mode and the live gate

**Live Gemini is verified on this machine through the server API key path; Vertex AI workload identity is not yet exercised.** Two server-side credential paths exist: Vertex AI with workload identity (the blueprint default) or a Gemini API key kept only in the ignored `.env` or Secret Manager. Neither is a browser-stored key or an arbitrary provider URL. Demo mode remains available and is always labelled.

**Live status, 18 October:** after prepaid credits were added to the Google AI Studio project, the opt-in five-workflow gate (`MIRAGE_LIVE_AI_CALL_LIMIT=5`, `pytest tests\test_native_http.py -k approved-live-gemini --live-ai`) passed for `gemini-2.5-flash` (calls took 2.7–5.6 s) and `gemini-3.8-flash` (3.5–8.3 s). It showed zero backend business reads/mutations and an unchanged case route. Evidence is written to `.local\live-ai-*.json` without credentials. The running console then passed **Check configured AI**, answered Ask Mirage AI and case questions, and automatically reviewed a new honeypot issue with `gemini-2.5-flash`. `gemini-2.5-pro` is not offered to new users of this key (HTTP 404), and `gemini-3.1-pro-preview` exceeded Google's deadline (HTTP 504) during probing; prefer a Flash model with the 12-second request limit.

Gemini counts hidden reasoning against the output limit. The provider therefore caps it per model family: Gemini 2.5 Flash runs with thinking off, Gemini 2.5 Pro uses its minimum 128-token budget, and Gemini 3.x/`-latest` models use low thinking. A separate reasoning reserve (0, 1,024 or 2,048 tokens) is added to the provider cap, while the visible-answer limit is still enforced from usage metadata. Truncated answers are rejected.

In a case, **Investigate evidence** creates a structured explanation, while **Ask this case** accepts a bounded, read-only question with cited observations. Investigations and questions share the per-case budget. Questions/responses are visible to authorized workspace analysts, not private chat. Only up to twenty current case-linked observations are supplied; prior model answers are not reused as evidence. Historical answers retain their case version. New evidence or revoked identity during generation rejects the response.

In **Integrations → Imported evidence → Inspect**, the advisory summary receives opaque local references, declared tiers and issue counts only. Raw scanner descriptions, tool names and source code stay local. Selecting `obs-N` focuses the corresponding local observation; a heuristic report is never promoted to exploit proof or an active scanner connection.

Optional decoy wording is display-only text around an unchanged deterministic emulator result. It cannot select tools, change identifiers/status, grant access or restore production. Invalid output, unavailable AI or exhausted budgets produce an explicit, audited static-template fallback. Stopped/expired sessions receive denial, not a fallback that resumes engagement.

For live use, first configure an approved Google application-default/workload identity outside source control. Select an available, approved model and region. Then fill these values in the ignored `.env`; replace every placeholder:

```text
MIRAGE_MODEL_PROVIDER=gemini
MIRAGE_GEMINI_PROJECT=<approved-project>
MIRAGE_GEMINI_LOCATION=global
MIRAGE_GEMINI_MODEL=<approved-available-model>
MIRAGE_MODEL_EGRESS_APPROVED=true
MIRAGE_MODEL_CALL_BUDGET=<approved-total-ceiling>
MIRAGE_MODEL_CASE_CALL_BUDGET=3
```

To use a Gemini API (AI Studio) key instead of workload identity, omit the project and add `MIRAGE_GEMINI_API_KEY=<key>` (keep `MIRAGE_GEMINI_ENDPOINT=auto`). Rotate any key that has been pasted into chat, tickets or source control.

Budgets are persisted tenant request reservations, including fixture and failed model attempts. Changing provider does not reset them. If nine reservations are already used and three more are approved, the total ceiling is twelve, not three. The Settings setup example calculates a small additional allowance; it is not permission to incur charges. Do not reset existing case/evidence data just to clear a budget.

Restart the owned native launcher. A security administrator can then use **Settings → AI provider & safeguards → Check configured AI** and explicitly confirm one synthetic request. Configuration presence is not connection proof, and a successful check is one request at a recorded time, not continuous health monitoring. Case generation is separately user-triggered. Startup/demo seeding never automatically invokes Gemini.

For the complete five-workflow live gate, an operator must separately approve up to five generation calls. The regular tenant cap must permit at least five reservations and the per-case cap at least two. The gate uses a fresh synthetic store and an actual signed loopback backend, not the user's existing cases or business records:

```powershell
$env:MIRAGE_LIVE_AI_CALL_LIMIT = "5"
.\.venv\Scripts\python.exe -m pytest -q tests\test_native_http.py --live-ai -k approved-live-gemini --junitxml=.local\live-ai-tests.xml
Remove-Item Env:\MIRAGE_LIVE_AI_CALL_LIMIT
```

This gate makes real provider requests and may incur charges: investigation, case Q&A, provider check, report-metadata summary and synthetic wording. It requires all five to succeed, validates references, checks unchanged authoritative routing and compares actual independent backend effects. On success it writes credential-free `.local\live-ai-<id>.json` evidence. It does not prove model accuracy, general prevention, cloud deployment or P3 network controls. **It remains unrun/blocked in this delivery.**

Default pytest and Playwright runs do not opt into live AI. They pin fixture mode, separate test stores/keys, and disabled egress even when the operator has configured AI environment variables. Browser runs use `.local\browser-qa\<run-id>` and ports 8797/8798. Never paste credentials, private source code or production records into case questions.

## Configuration

Use `.env.example` as the secret-free reference; an optional `.env` is ignored. Values are validated by `mirage.config.Settings`.

| Variable | Default / meaning |
| --- | --- |
| `MIRAGE_PROFILE` | `P1-native`; `P2-prepared` is not a validated deployment |
| `MIRAGE_DATA_DIR` | `.local`, containing only this application's generated data |
| `MIRAGE_API_PORT`, `MIRAGE_BACKEND_PORT` | 8787 / 8788, loopback listeners |
| `MIRAGE_DATABASE_URL` | Empty selects project-local SQLite/WAL; PostgreSQL uses `postgresql+psycopg://...` |
| `MIRAGE_ALLOWED_ORIGINS` | JSON list; include the exact custom local console origin if changing ports |
| `MIRAGE_LOCAL_LOGIN` | true only for P1-native; fixture login is forbidden outside it |
| `MIRAGE_MODEL_PROVIDER` | `fixture`, `gemini`, or `unavailable` |
| `MIRAGE_GEMINI_PROJECT`, `MIRAGE_GEMINI_LOCATION`, `MIRAGE_GEMINI_MODEL` | Explicit approved project, region and currently available model; no model availability is assumed |
| `MIRAGE_GEMINI_API_KEY` | Empty. Optional server-side Gemini API (AI Studio) key; never returned, logged or sent to the model |
| `MIRAGE_GEMINI_ENDPOINT` | `auto` (key → Gemini API, otherwise Vertex AI), `developer` or `vertex` |
| `MIRAGE_MODEL_EGRESS_APPROVED` | false; a separate operator data/cost approval gate, not model-controlled |
| `MIRAGE_DECOY_MODEL_WORDING` | false; optional bounded wording stays outside the Wasm runtime |
| `MIRAGE_SESSION_TTL_SECONDS` | 900; termination never restores production |
| `MIRAGE_DECOY_REQUEST_BUDGET` | 100 |
| `MIRAGE_MAX_ENGAGEMENTS` | 10 globally across the shared store |
| `MIRAGE_MODEL_CALL_BUDGET` | 100 persisted tenant reservations across fixture/live attempts; no automatic refund/reset |
| `MIRAGE_MODEL_CASE_CALL_BUDGET` | 3 shared investigation/question requests per case; same separate cap per imported report |
| `MIRAGE_MODEL_MAX_PENDING` | 4 active pending reservations per tenant |
| `MIRAGE_MODEL_INPUT_BYTES` | 65536 maximum context bytes; SDK check also includes schema/system text |
| `MIRAGE_MODEL_TIMEOUT_SECONDS` | 12; bounded provider call, one SDK attempt |
| `MIRAGE_EVENT_RETENTION_DAYS` | 7 for processed, unreferenced event metadata |

Native provider/dispatcher credentials are not exposed to the model or Wasm module. SDK requests have one candidate, no tools, automatic function calling disabled, one HTTP attempt, explicit timeout and output caps. Missing usage is recorded as unknown, not a measured zero or complete billing total. Reservation expiry discards late results and never automatically resends or refunds; it does not claim cancellation of an already admitted provider request.

Wording has a separate 8,000-unit conservative admission budget per engagement, based on UTF-8 context/system bytes, output cap and protocol allowance. These units are not billed tokens. The legacy `model_tokens_per_session` response key remains a compatibility alias; use `wording_budget_units_per_session` and its definition. Actual reported provider tokens are tracked separately.

## Database and effects

```powershell
.\.venv\Scripts\python.exe -m mirage migrate
```

The migration runner serializes schema updates, records revision 1 (initial tables), revision 2 (retention-safe monotonic counters), and revision 3 (tenant-bound advisory AI request/history records). It preserves existing cases and rejects unknown newer revisions before creating additional metadata. [Generated DDL references](../migrations/README.md) are not gateway registry migrations.

SQLite/WAL uses `BEGIN IMMEDIATE`; PostgreSQL uses a shared transaction advisory lock. This deliberately serializes native dispatch rather than pretending to offer high-throughput row-level scheduling. Two application instances sharing SQLite were tested. The PostgreSQL runtime path remains a separate, unrun gate.

The separate synthetic backend has its own SQLite ledger and independently checks the fixed operation catalogue, tenant records, HMAC request binding, expiry and execution idempotency. Local approval consumption and remote effects are not one ACID transaction. Approval-derived stable backend execution IDs prevent duplication after a lost response or a local rollback after backend commit. Unknown outcomes remain unknown until the analyst reconciliation endpoint retrieves the existing backend result; no blind resend is performed.

## Stop, retention and reset

Disable new engagements in Settings or Deception Centre. This does not remove authorization or terminate existing sessions. Use the explicitly confirmed kill switch to terminate tenant decoys and purge their synthetic state. There is no decoy-to-production transition.

The native worker drains the durable outbox, expires sessions, and prunes old processed metadata once per minute. Case-referenced evidence is retained until explicit case purge; the independent backend ledger and audit trail remain until reset. Case purge is administrator-only, requires a terminated session, resolved/exported case, current version and exact confirmation, and preserves the route tombstone and backend ledger. Pending bounded AI requests block purge. Purge removes case AI history and case-bound response caches as well as notes; separately downloaded exports are not removed.

Stop the launcher before resetting:

```powershell
.\.venv\Scripts\python.exe -m mirage reset --confirm SYNTHETIC-LOCAL-DATA
```

Reset removes only individually named synthetic database/fixture files in the configured data directory, not the directory or unrelated files. It preserves the generated launch code. It does not reset PostgreSQL or an arbitrary external SQLite database.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Console not built | Run setup, or `npm.cmd run build` in `apps\dashboard` |
| Port occupied | Stop only your known launcher or choose unused local ports and exact allowed origin |
| No active decoys after a while | TTL expired; this is expected. Run a fresh bounded scenario |
| Missing readiness / probe expiry | Reverify in Deception Centre; requests stay restricted when readiness is unavailable |
| Model unavailable | Deterministic controls and static decoy responses continue |
| `MODEL_BILLING_REQUIRED` | The Gemini key works but its AI Studio project has no prepaid credits/billing (HTTP 402). Add credits, then **Check configured AI** |
| `MODEL_KEY_REJECTED` / `MODEL_NOT_AVAILABLE` / `MODEL_RATE_LIMITED` | Fix or rotate the key, pick a model from **Discover available models**, or retry later |
| `MODEL_TIMEOUT` | Gemini did not answer within the request limit (HTTP 504 or client timeout). Retry, or pick a faster Flash model |
| `MODEL_REQUEST_UNSUPPORTED` | The selected model rejected structured JSON output or the thinking limits (HTTP 400), e.g. an image or speech model. Pick a Flash text model |
| Telegram: "blocked on this network" | A secure web gateway redirected `api.telegram.org`. Use an allowed network or the Cloud Run deployment; do not bypass the policy |
| Unknown backend outcome | Reconcile the durable execution ID; do not issue an unreviewed replacement |
| Local code rejected | Use the code for this data directory, not a code from browser QA/evaluation |
| Browser download certificate error | Use the Windows CA trust store, not `NODE_TLS_REJECT_UNAUTHORIZED=0` |
| API/store/backend failure | Inspect project-local `api.log` / `backend.log`; the console displays explicit errors |
