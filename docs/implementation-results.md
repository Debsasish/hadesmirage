# Implementation and verification results

Core implementation verified 17 October 2026; SOC console and AI fixture/offline integration checks verified 18 October 2026; live Gemini (server API key path) verified the evening of 18 October 2026. **Delivered scope: a runnable P1-native Windows laboratory, not a full P2/P3 deployment or a production-ready SOC.** No Docker was used to build or run the implementation.

## Live Gemini verification — 18 October, evening

**Measured:** after prepaid credits were added to the Google AI Studio project, the same server-side API key generated content (HTTP 200 instead of 402). A first live probe exposed a real defect: `gemini-2.5-flash` spent 58 of the 64-token provider-check budget on hidden reasoning, so the answer was cut off (`MAX_TOKENS`, text `Here is`) and would have been rejected. The provider now caps reasoning per model family: 2.5 Flash thinking off, 2.5 Pro minimum 128-token budget, Gemini 3.x/`-latest` low thinking. It adds a separate reasoning reserve (0/1,024/2,048 tokens) to the provider cap and still enforces the visible-answer limit from usage metadata. Upstream 400 and 504 responses and client timeouts now map to `MODEL_REQUEST_UNSUPPORTED` / `MODEL_TIMEOUT`. Decoy-wording admission counts the reserve.

**Live gate passed:** the opt-in five-workflow gate (`--live-ai`, `MIRAGE_LIVE_AI_CALL_LIMIT=5`) passed twice over the actual signed backend HTTP path. With `gemini-2.5-flash`, investigation, case question, provider check, report summary and decoy wording took 5.6/5.5/2.7/5.0/2.8 s (provider-reported totals 2,650/2,419/64/618/148 tokens). With `gemini-3.8-flash` they took 8.3/7.8/3.6/6.4/3.5 s. Both runs showed zero backend business reads/mutations and an unchanged case route. Evidence is in `.local\live-ai-*.json`, which contains no credentials. Probing also found `gemini-2.5-pro` unavailable to new users of this key (404) and `gemini-3.1-pro-preview` timing out at Google (504).

**Running application (P1-native, `http://127.0.0.1:8787`):** the portal was switched from Demo mode to Gemini (`gemini-2.5-flash`, server API key, egress acknowledged, auto-review on; settings version 5). **Check configured AI** passed live in 3.1 s. Ask Mirage AI answered with 7 cited references in 4.5 s. A fresh external-probing run was diverted to the honeypot with 0 production reads/mutations. Gemini auto-reviewed the new issue HM-0014 within about 12 s and answered a plain-language case question in 7.9 s. The attack map still reported 0 real-data changes after containment.

**Verified locally:** full native suite **164 passed / 6 explicit skips** (the skipped live gate was run separately above), including 10 new offline tests for reasoning caps, truncated/oversized answers, timeouts, new error mappings and wording admission. Ruff check/format passed. No frontend source changed in this checkpoint. **Not claimed:** Vertex AI workload identity, model accuracy or detection quality, latency under load, billing totals, real Telegram delivery and any Cloud Run deployment.

## Live attack map and supplied-credential checkpoint — 18 October

**Implemented:** a live attack map (`GET /v1/attack-map`, analyst role, 1 h/24 h/7 d/30 d windows, all/live/laboratory origin). It shows who sent requests, what the rules decided and where attackers ended up, with plain/technical labels, node and session inspectors, attacker path replay and a live feed. Counts come from recorded decisions. Business effects are attributed from the independent synthetic backend ledger, and "real data touched after catch" must be zero. Gemini also accepts a server-side API key (`MIRAGE_GEMINI_API_KEY`, Developer API endpoint) in addition to Vertex workload credentials. Provider failures now map to actionable codes (`MODEL_BILLING_REQUIRED`, `MODEL_KEY_REJECTED`, `MODEL_NOT_AVAILABLE`, `MODEL_RATE_LIMITED`). Telegram uses the OS trust store and reports a redirecting network gateway as blocked.

**Verified locally:** native suite **154 passed / 6 explicit skips** and the complete browser suite **29 of 29**, including the attack-map workflow with axe scans in both themes. Ruff, ESLint, Prettier, TypeScript, the production build and the 200 blueprint/document checks passed. The supplied key and token appear only in the ignored `.env`; tests pin both to empty values.

**Live results, not successes:** the supplied Gemini key listed models on the Developer API, but generation returned **HTTP 402 (prepaid credits depleted)**, and the key is blocked for Vertex. (Superseded for the Developer API later that evening once credits were added; see *Live Gemini verification* above.) Telegram Bot API requests were redirected by the corporate secure web gateway, so no live message was delivered. No Cloud Run deployment was made. For the recorded demonstration, the running app was switched in the portal to labelled **Demo AI (fixture)** with auto-review on. Pre-flight on the running app: the honeypot was verified ready and engagements were enabled. A fresh external-probing run was diverted to the decoy with **0 production reads/mutations**, the new issue received an automatic fixture review, and the attack map showed 0 real-data changes after containment. Profile: **P1-native**. Shared credentials should be rotated.

## Wiz-style investigation, Telegram and Google Cloud checkpoint — 18 October

**Implemented:** Wiz-style console (icon rail with plain names, risk board, Issues drawer, Ask Mirage AI chat, AI chips, "Investigate with the AI agent" card, attack path explanation and interactive attack graph); a global **Plain / Technical** view; deterministic attack stories (`/v1/incidents/{id}/attack-path`) and board metrics (`/v1/board`); workspace AI chat (`/v1/assistant`) with issue-reference validation and private history; portal-managed, versioned Gemini settings (`/v1/ai/config`, `/v1/ai/models`) and opt-in AI auto-review of new issues; schema revision **4**. Telegram bot access requests, administrator approve/reject with viewer/analyst/approver roles, revocation, role-limited alerts and one-time digest-bound Approve/Reject buttons (polling or secret-verified webhook). Google Cloud Run source deployment through buildpacks, `python -m mirage cloud`, Secret Manager, Vertex AI service identity and Google Workspace sign-in through IAP (`P2-cloud`).

**Boundaries kept:** behaviour rules—not AI—block requests and move eligible outside agents into the honeypot. AI explains, answers and recommends only. Telegram cannot grant administrator rights, and its buttons reuse the console approval checks (exact digest, separate reviewer, expiry, replay protection). Graphs, stories and board numbers are derived from stored records; containment rate is defined as detected outside sessions that were limited, moved to the honeypot or disconnected, not a general prevention score.

**Verified locally:** full native suite **143 passed / 6 explicit skips**, including 6 Wiz/AI tests, 12 Telegram tests against a fake Telegram API and 36 cloud/IAP tests with locally generated signing keys. The final complete browser run passed **28 of 28 workflows**: the original 24 plus board → issue drawer → plain/technical graph and timeline, floating AI chat, portal model selection, and Telegram request approval/revocation through the secret-verified webhook. (An earlier run exposed a test race with the launcher's scenario seeding; tests now wait for seeding to finish before signing in.) Production build, TypeScript, ESLint, Prettier, Ruff, the 199 blueprint/document checks and the bounded secret scan passed. The cloud launcher started locally with IAP mode: health 200, unauthenticated and forged-identity requests 401, unknown host 400.

**Not verified:** live Gemini calls (no Google credentials/project authorization), real Telegram delivery (no bot token), and any Cloud Build/Cloud Run/IAP/Secret Manager/Vertex deployment (no gcloud or credentials). Cloud Run uses per-instance SQLite in `/tmp` unless PostgreSQL is configured (PostgreSQL remains runtime-unvalidated); deploy with one instance. Telegram webhooks cannot pass IAP, so the cloud script uses polling with an always-on instance. These remain release gates, not completed claims.

## AI integration checkpoint — 18 October: live verification blocked (superseded by *Live Gemini verification* above)

Implemented the blueprint's Gemini-on-Vertex/workload-credential path rather than adding unrequested vendors. The console now exposes evidence-cited investigation and case Q&A, shared bounded answer history, metadata-only imported-Hades summaries, administrator-only provider checks, and optional display-only decoy wording with explicit static fallback. Settings distinguishes fixture mode, missing configuration, disabled egress, a failed check and a timestamped successful check. Model text is inert, never a tool/approval/policy/routing instruction. The existing SOC design and deterministic enforcement remain in place.

The broker enforces current tenant/identity/role, case version/report digest, exact supplied references, a shared case investigation/question cap, separate report caps, tenant request budgets, pending limits, input/output bounds and idempotency. Identity/version changes during inference reject results. Schema revision **3** stores request provenance, context/config digests, usage/error state and history. Case purge waits for active requests and removes case AI records and response caches while retaining the audit/route tombstone and independent backend ledger.

Live egress is separately operator-controlled and **defaults to false**. Case inputs contain at most twenty redacted linked observations, not conversation memory or unrestricted workspace data. Report summaries receive only opaque local refs, risk tiers and counts; scanner descriptions, tool names and source code stay local. SDK requests use one candidate, one attempt, no tools, disabled automatic function calling, explicit timeout and schema/output caps. Missing usage remains unknown; reported-token totals are not a complete billing claim. Wording's conservative 8,000-unit admission limit is not a billed-token estimate.

**Verified:** the complete current native suite passed **89 tests / 6 explicit skips**. Two purge/cache/retention checks passed again after the final privacy cleanup. The real installed SDK serialized and parsed all five request types through an offline authenticated HTTP transport; invalid/tool/blocked/oversized responses and an upstream outage were rejected. The actual signed loopback backend path showed no new business reads/mutations or route changes from AI workflows, with a positive control proving the backend effect ledger worked. A separate operator-environment canary confirmed normal tests do not activate Gemini from inherited settings.

**Browser/runtime evidence:** all **24 browser workflows passed**, including provider-role checks, persistent cited Q&A, local report-reference focus, inert model/scanner markup and explicit failure states. Production build/type-check, ESLint and formatting passed. Final read-only review covered **72 layouts** (nine views, sign-in, recorded case Q&A and report modal; both themes at 1440/768/390) and **24 automated desktop WCAG scans**, with no scoped overflow/runtime or serious/critical accessibility findings. Screenshots were inspected. This is not independent accessibility certification.

The owned native application is responsive at `http://127.0.0.1:8787`, with existing data/access code preserved. Its observed provider is `fixture-investigator-v1`, egress is disabled and `live_check_passed` is false. One explicit native fixture check succeeded with zero observed backend business-effect deltas. **This is not proof of Gemini connectivity or real model reasoning.**

**Remaining real blocker:** no approved live project/model/call authorization was configured for this task, and actual workload credentials were not exercised. The user was unavailable to supply those decisions. A separately opt-in, five-generation synthetic gate now exists (`--live-ai` plus an approved `MIRAGE_LIVE_AI_CALL_LIMIT`); default tests never run it. The gate requires investigation, case Q&A, provider check, report summary and wording all to succeed over the real provider path, with unchanged actual backend effects and credential-free evidence. It remains skipped/unrun. **The objective of fully verified live AI integration is therefore not marked complete.**

Active versions: implementation `0.1.0`, authoritative schema `3`, AI policy `advisory-v2`, locked Google Gen AI SDK `2.31.0`, synthetic template `1.0.1-wasm`. Persistent evidence: `.local\ai-backend-tests.xml`, `.local\ai-environment-isolation.xml`, `.local\ai-purge-tests.xml`, `.local\ai-native-smoke.json`, `.local\ai-visual-review-1792311544038\review.json`, the Playwright report, and updated source/runtime fingerprints. No real-model latency, accuracy or cost is claimed. The build retains a non-fatal Vite 500 kB entry-chunk warning; the Starlette compatibility warning and external-profile gaps remain.

## SOC console replacement — 18 October

The following records the redesign checkpoint before the AI expansion. Current AI/runtime verification is above.

The rejected glass dashboard has been replaced, not given another translucent overlay. The current console has a fixed global product/search bar, compact grouped navigation, a search-led overview, a native selectable case table and a persistent **Summary / Evidence / Route** investigation pane. Locally hosted Inter, neutral graphite/light surfaces and a restrained blue interaction accent are shared across all nine views and the redesigned sign-in. Evidence and data surfaces are opaque. The existing transparency preference now affects an optional toolbar material only. The retired glass/workspace stylesheets and old case-list component were removed; `console.css` owns the theme tokens over the reusable component foundation.

Activity charts use twelve actual server-receipt buckets; severity distribution uses recorded unresolved cases. Record search and severity links open existing tenant-scoped filters, explicitly clearing unrelated saved filters. Ordinary navigation preserves filters, and edits after a drill-down survive reload. This is plain bounded case/event search, **not SPL, arbitrary query execution, a live SIEM connection or broader protection**. The analyst queue supports keyboard selection and real evidence inspection without writes. Route inspection remains read-only and always distinguishes history from the latest received server route.

Phone layouts convert recent-event rows and queue entries into readable records rather than hiding outcomes off-screen. Refresh pause/resume remains available on smaller screens. Narrative overview text has a bounded reading measure. Screenshot review also found topology labels overlapping nodes; the final layout separates them, moves the native-path caption out of the diagram, and aligns SVG connections with node coordinates. Desktop and mobile browser assertions now check label/node collisions.

**Frontend verification:** the complete **20-workflow browser suite passed** during the replacement. After the final reading-measure, mobile-refresh and topology refinements, **eight affected workflows passed again**, including all-nine-view navigation, desktop/mobile topology, actual scoped searches, read-only progressive inspection and route history. TypeScript/build, ESLint and Prettier passed. The unchanged native backend regression is **56 passed / 6 explicitly skipped**.

The final settled-render review covered all nine views plus sign-in in dark/light at 1440, 768 and 390 pixels: **60 layout checks** (54 application, six sign-in) without page overflow or runtime errors, plus six topology collision checks. **22 automated WCAG scans** (18 desktop application views, two desktop sign-in views and two historical route-focus views) had no serious/critical findings. This is scoped automated evidence, not independent accessibility certification. Screenshots and JSON are retained in `.local\soc-release-review-1792304031244`.

**Taste direction and limits:** *Dressed as something else* (`borrowed-category`), seed `674316234`. Mirage's independently recorded decisions and effects become a search-led analyst desk: the live interaction is selecting/searching real cases and inspecting their evidence in place. The borrowed category is precise consumer software, not a vendor clone. Workflow/hierarchy references were [Splunk Enterprise Security](https://www.splunk.com/en_us/products/enterprise-security.html) and [Apple's layout guidance](https://developer.apple.com/design/human-interface-guidelines/layout.md). No Apple/Splunk logos, proprietary fonts, screenshots or source code were copied. No further redraws were made after choosing this direction.

The final **unmodified runtime Taste gate does not pass: seven FAIL categories and one WARN**. The retained categories concern metric/profile labels above values, chrome/data dividers, outlined operational groups, 13px application density, absent photography, absence of a marketing-scale hero and deliberately restrained motion; the warning is absent footage. Scope labels, status legends, readable bounded records and stable investigation context are intentional application requirements. Stock photos, a giant hero and scroll reveals would not improve this analyst workflow. No `data-ui` blanket exemption, rule suppression or hidden-overflow workaround was added. The final report has no overflow, contrast, small-text, font-loading or paragraph-measure finding.

The source-style lint also remains non-passing: **78 raw FAIL occurrences / 53 WARN occurrences**, including literal `box-shadow: none`, functional separators/code fonts, outlined controls and toolbar/fallback blur declarations. These lexical findings are retained separately from measured rendering and passing ESLint/build checks. Raw evidence is in `.taste-skill\soc-release-raw` and `.taste-skill\soc-release-source-lint.txt`. The screenshot self-critique scores design 6.5, usability 8.0, creativity 7.0 and content 8.5 (weighted 7.25), **capped at 6.0/10 by the strict marketing rubric's remaining FAILs**. This is not an external jury score or a claim of a perfect Taste pass. Remaining compromises are dense technical reading, a long stacked phone overview and intentionally familiar SOC interaction patterns.

All displayed people, suppliers and business records remain labeled synthetic fixtures; metrics come from recorded local requests, not invented dashboard figures. No stock/found pictures, footage or externally fetched media were used, so there are no image credits to resolve. Charts and the topology are code-drawn from actual application data/configuration. Fixture identities/data must not substitute for approved identity and operational integrations in a real pilot. Backend authority, approvals, model restrictions and the six external-profile gaps below are unchanged.

## Superseded glass workspace update — 18 October

**Historical record only:** the following intermediate design was rejected and replaced by the SOC console above. Its material, direction and 18-workflow result are not the current release.

The console now uses an intentional glass depth system: a translucent navigation rail and toolbar, lifted case inspection surface, restrained coloured light, and an opaque evidence-reading layer. It includes dark/light themes, an optional **Settings → Appearance → Translucent surfaces** preference, a no-backdrop-filter fallback, and reduced-transparency/reduced-motion styles. Appearance preferences are applied before React's first render to avoid a dark-to-light content flash.

The main overview is case-first rather than a stack of equal cards. A keyboard-operable case queue drives the real case preview. Its **Route lens** lets the analyst select a recorded route version, inspect case-linked observations in that route, and open the same selection in a focused dialog. The latest received server route remains separately visible. The lens is read-only: it does not replay requests, grant access, restore production, or execute a tool. Counts describe case-linked records grouped by their recorded route mode, not a reconstruction of every network packet or an assertion of absent traffic.

Other utility changes include compact navigation, explicit display-refresh pause/resume, correct event-filter deep links despite saved filters, role-specific sign-in guidance, optional access-code visibility, and client-side navigation after confirmed server logout. Server authentication, approvals, model authority, routing and isolation rules were not weakened or replaced.

**Final frontend verification:** 18 browser workflows passed. A separate review covered all nine views in both themes at 1440, 768 and 390 pixels: **54 layout checks without page overflow or runtime errors**. All 18 desktop view/theme combinations and two historical-focus views had **no serious/critical automated WCAG findings** after appearance/fonts settled. Glass and opaque overview contrast, keyboard route scrubbing, unchanged backend counters, role-switch approvals and reduced-motion mobile focus are covered by the browser suite. This remains scoped automated evidence, not a whole-product accessibility certification.

**Taste interpretation:** the selected direction remains *The product performs*, seed `553652260`. Customer-logo and calculator slots were redrawn as actual control evidence and stored operational figures. The user's explicit glass request supersedes the skill's flat-material preference. The unmodified final marketing-page inspector is retained and **does not pass**: it reports eight rule categories concerning labels, gradients, shadows/button effects, outlined surfaces, application text density, missing photography and marketing-scale focal imagery. Six warnings remain, including modest motion and absent footage. Those are documented application/material exceptions, not hidden failures or a claim of a perfect Taste score. The final report has no overflow, unreadably small-text or contrast failure. No stock images, externally fetched media, invented customer proof or fabricated live metrics were added.

Final screenshots, view-review JSON and raw Taste measurements are retained in `.local\glass-verified-review-1792300434468` and `.taste-skill\glass-reviewed-raw`. The internal screenshot critique is an app-specific self-review, not an external award or evidence of a “never seen before” interface. Native backend regression results remain **56 passed / 6 explicitly skipped**; the external-profile gaps below are unchanged.

## What is implemented

React/TypeScript console with all nine requested views, complete dark/light themes, local fonts, keyboard search/focus behavior, persisted filters, bounded tables and explicit loading/empty/error/permission states. Cases distinguish observations, rule conclusions, advisory model explanations, analyst notes, actual backend effects and simulated decoy responses.

FastAPI implements verified local identities, tenant-bound references, strict typed operations, deny precedence, exact resource grants, one-time request-bound approvals, separate reviewer roles, idempotent execution/reconciliation, bounded delegation and ancestor-shared quotas. A separate HMAC-authenticated HTTP backend keeps an independent synthetic supplier/effect ledger.

The authoritative store has versioned SQLite/PostgreSQL-compatible metadata, durable event/outbox processing, received-time correlation for D-001 through D-006, monotonic route fencing, incidents/evidence, reviewed policy activation/rollback, notes, JSON/HTML/Markdown exports, retention, confirmed case purge and audited response controls.

Eligible external laboratory sessions can be restricted and pinned to a reviewed no-import Wasmtime supplier emulator. Synthetic state, coherent supplier/invoice variants, TTL, request/model/concurrency budgets, cleanup and kill switch are implemented. Missing readiness never restores production. Internal workloads receive explicit denial rather than silent simulated business outcomes.

Hades report ingestion and structured gateway telemetry are source/tenant-bound and have no permission-signing or activation authority. The exact pinned Hades auditor was run against five synthetic tool definitions. Gemini is behind a bounded SDK/provider interface; the validated default is the deterministic fixture investigator.

## Final checks

| Check | Observed result | Scope |
| --- | --- | --- |
| Backend acceptance | **89 passed, 6 explicitly skipped; two final purge checks rechecked** | Existing identity/approval/delegation/route/HTTP/effect checks plus all advisory AI workflows, SDK offline transport, byte/usage/reference bounds, budget/race/revocation/expiry handling and schema-3 upgrade/cache purge |
| Browser acceptance | **24 passed** | Original twenty SOC workflows plus provider-role/fixture checks, persistent cited case questions, metadata-only report summaries/local focus, inert AI text and explicit provider errors |
| Layout and accessibility | **72 layout checks / 24 automated scans**, no scoped findings | Nine application views, sign-in, Q&A case and report modal; both themes, three widths; desktop WCAG 2 A/AA and 2.1 A/AA scans; not independent certification |
| TypeScript / production build | Passed | Locked React console, runtime/font license notices retained |
| ESLint / Prettier / Ruff | Passed | Authored console/runtime/test/tool source |
| Python compatibility | `pip check` passed | Exact installed dependency lock |
| Python public advisories | **54 locked packages, no OSV matches** | Public PyPI package names/versions only; not source review or exploit verification |
| Production npm advisories | **0 reported vulnerabilities** | `npm audit --omit=dev`; not a guarantee of vulnerability absence |
| Foundation review | Passed exact source/ZIP hash checks | Five-tool Hades fixture audit; selected gateway source/license review, not native gateway execution |
| Diagrams | **9 Mermaid sources rendered to SVG** | Implemented topology, trust/capability boundary, sequences, state, data, OSI and failure paths |

A Starlette test-client compatibility deprecation warning remains: its `httpx` shim recommends `httpx2`. It did not fail the native tests or affect the running HTTP services.

During initial implementation, browser label/contrast, scroll-container and screenshot-overwrite failures were corrected and the then-complete eleven-test suite passed afterward. Visually hidden table labels are anchored inside their scroll container; page overflow is not hidden to mask clipping. Native runtime/build/workflow gates pass within the stated profile. The current strict Taste marketing gates remain non-passing as documented above; skipped external profiles remain release limitations.

The Windows GitHub Actions workflow is authored and pinned, but was not executed on GitHub: this workspace was not published. The known-key-format source check is a bounded smoke check, not a replacement for a full secrets/SAST assessment.

## Frozen evaluation: actual local HTTP paths

Behavior rechecked 18 October after isolating evaluator configuration from operator AI/database settings. The dataset and synthetic-only scope are unchanged; the previous measurement file is retained as `.local\pre-ai-evaluation.json`. These timings are native fixture behavior, not live-model performance.

Dataset: `tests\fixtures\evaluation-v1.json`, version `evaluation-v1`, SHA-256:

`0d915de694666ef3cc2a684cb3c810a67c320840d8571cc4e781bae761f2c175`

The evaluation starts fresh native HTTP API and signed backend listeners with separate authoritative/effect stores. It sends real requests over loopback sockets and reads the independent backend ledger. Windows / Python 3.13.14 / SQLite-WAL / one evaluation client / warm Wasmtime engine and a fresh per-request module instance. The developer host is shared, not a calibrated performance laboratory.

| Measurement | Result |
| --- | --- |
| Benign eligible task completion | **50 / 50** |
| False diversion in benign fixtures | **0 / 50** |
| Corroborated suspicious laboratory sessions diverted | **20 / 20** |
| Production-like effects from those suspicious sequences | **0 reads and 0 mutations** |
| Ambiguous/misconfiguration sessions diverted | **0 / 10** |
| Independent backend total | **50 reads, 0 mutations** in this evaluation |
| Pure policy function, 80 samples | p50 **0.0134 ms**, p95 **0.0158 ms**, p99 **0.0225 ms** |
| Complete fixture HTTP sequence, 80 samples | p50 **881.2826 ms**, p95 **934.6050 ms**, p99 **1049.8171 ms** |

The pure function timing excludes authentication, storage, backend and model work. Sequence timing includes fixture HTTP requests and ledger observations; it is **not** ready-decoy route-commit latency. It does not prove the blueprint's sub-500 ms transition target. No live model summary latency, throughput or cost was measured.

These are frozen engineering fixtures, not independently labeled or held-out real attack ground truth. Zero diversions among fifty synthetic benign sessions does not establish a general false-positive rate or universal prevention accuracy. The approved-mutation and replay tests are separate from this zero-mutation benchmark and independently verify exactly one permitted synthetic change.

## Isolation evidence

Template `supplier-portal-v1`, version **1.0.1-wasm**. Compiled module SHA-256:

`f80cfc39ac7851af67e84d0088222fae9dab6d256cce23e9d64a8de1faacaf26`

**Eight actual Wasmtime linker probes denied unavailable capabilities:** production/control-plane socket operations, metadata/network interfaces, external networking, DNS, filesystem, process execution and environment access. The module has **zero host imports, no WASI, 64 KiB maximum memory and 100,000 fuel units per request**. Separate tests exercised actual fuel exhaustion and denied memory growth.

This is a genuine capability-isolated, low-interaction synthetic runtime. It is **not an operating-system TCP reachability matrix, container/CNI isolation result or Rust gateway test**. Host/Wasmtime-engine compromise and arbitrary attacker binaries are outside the demonstrated scope.

## Explicitly skipped / blocked profiles

| Gate | Why it remains unverified |
| --- | --- |
| T-08 native gateway certificate/key/expiry/revocation | No Rust toolchain, original running proxy, test PKI or signed registry provisioned |
| T-09 direct internal-agent OS egress bypass | P1-native does not confine arbitrary host networking through P3 |
| T-25 established CONNECT tunnel revocation | No native tunnel/close manager; new-grant revocation must not be represented as closing old tunnels |
| Live Gemini on Vertex AI workload identity | The five-workflow gate **passed** through the Gemini Developer API key path (`gemini-2.5-flash`, `gemini-3.8-flash`). The Vertex/Cloud Run service-account path is unexercised: no Google Cloud project authorization, and the supplied key is blocked for Vertex |
| Live Telegram delivery | Bot token configured, but the corporate secure web gateway redirects Bot API requests; webhook/polling were tested only against a fake Telegram API |
| PostgreSQL runtime acceptance | DDL/configuration are present; the exercised shared-state path is SQLite, not a running PostgreSQL server |
| Cloud IAM/origin/network paths | No cloud deployment, public publishing or spend was performed |

The original T-10 origin gate is exercised against the real signed local backend HTTP listener. The original T-14 network requirement has a clearly labeled Wasm-capability variant, not a fabricated TCP test. Skipped P3/P2 gates prevent a full gateway/cloud MVP release claim.

## Requirement traceability

| Requirement | Current status |
| --- | --- |
| FR-01, FR-02 | One synthetic procurement application, two internal fixture workloads and deterministic tool/resource checks |
| FR-03 | **Blocked for P3**; destination connectivity is not tool authorization |
| FR-04, FR-05 | Exact one-time approvals and bounded application-level delegation; not native certificate delegation |
| FR-06, FR-07 | Authenticated bounded events, durable outbox and six reproducible rules |
| FR-08 | Evidence-cited investigation, case Q&A, metadata-only report summaries and bounded wording; the five-workflow live Gemini gate passed via the server API key; Vertex workload identity remains unexercised |
| FR-09, FR-10 | Fenced application diversion and capability-isolated synthetic emulation |
| FR-11, FR-12, FR-13, FR-14 | Evidence/audit, termination/kill switch, exports and explicit profile/provenance labels |

## Persistent evidence and reproduction

Use [native setup](native-setup.md), [the demo walkthrough](demo-walkthrough.md) and the root verification commands. Generated evidence is intentionally ignored by source control:

- `.local\backend-tests.xml` and the Playwright report.
- `.local\browser-artifacts\<run-id>`: inspected dark/light, case, architecture, responsive and failure-state screenshots.
- `.local\evaluation.json` and `.local\evaluation-runs`: final measured results and independent stores.
- `.local\isolation-evidence.json`, `.local\foundation-evidence.json`, `.local\hades-report.json`.
- `.local\python-dependency-audit.json`: OSV source, time, package count and scope.
- `.local\source-manifest.json` and `.local\handover-runtime.json`: exact source digests and the active public configuration fingerprint, without credentials.

Source/policy/template pins are available in Settings, exports and `mirage\resources\provenance.json`. The historical blueprint's `package-metadata.json` and `file-manifest.json` describe the original design package, not the new runtime release inventory.

## What remains before a real pilot

Replace shared-code fixture identity selection with approved independent human/workload identities, issuer/audience checks, rotation and actual user-on-behalf-of scope intersection. The local approval actors are separate fixture IDs, not independently authenticated employees.

Run PostgreSQL, real gateway/PKI/egress/tunnel-close and cloud-origin/IAM gates in their authorized environments. Add the protocol-specific public/anonymous ingress and streaming MCP adapters only after testing them; current external sessions are authenticated laboratory sessions. Public deception needs a reviewed protocol/visibility design rather than copying the openly labeled synthetic demo responses.

Complete independent security/accessibility review, load/recovery tests, externally protected audit retention, privacy/legal approval, source-reuse/licensing review and operational staffing. The serialized writer fence and measured native sequence timings are prototype behavior, not an enterprise performance claim.
