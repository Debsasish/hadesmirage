# Implemented architecture: P1-native

This document describes authored and exercised code, not the full target deployment in the original [architecture](architecture.md). The editable/rendered diagram set is [indexed here](diagrams/README.md).

## Three planes

| Plane | Implemented components | Authority |
| --- | --- | --- |
| Enforcement | FastAPI verified bearer/cookie context, strict Pydantic operation models, deterministic policy, approval/delegation, shared dispatch fence, fixed signed HTTP backend | Decides and executes only authorized typed operations |
| SOC control | Authenticated source/tenant-bound events, transactional outbox/worker, D-001–D-006, case/evidence store, reviewed policies, notes/export, fixture/Gemini interface | Deterministic response controller and separately authenticated human roles |
| Deception | Trusted router and a reviewed no-import Wasmtime supplier module with per-session synthetic state | Only bounded emulation; no host callbacks, provider credentials, filesystem or network capabilities |

The console is React/TypeScript with Radix modal/focus primitives, local Inter fonts, typed API data, persisted filters, bounded pages, accessible status labels and complete dark/light themes. It never renders attacker/model HTML, runs report instructions, embeds external evidence, or turns prose into grants.

The 18 October SOC replacement retires the earlier glass skin. A global product/search bar, compact navigation, recorded activity/severity analytics and a selectable case table share one dark/light theme system. A persistent investigation pane progressively reveals Summary, Evidence or Route. Plain case/event search uses existing tenant-bound API filters; it is not an SPL interpreter, arbitrary query executor or a live SIEM connector. Incoming search links reset unrelated saved filters, while ordinary navigation and subsequent edits retain their saved state.

The case-bound route-history lens filters already authorized evidence by its recorded route mode and shares its selected version with a focus dialog. It never dispatches an operation or changes session state. Historical inspection and the latest received authoritative route are explicitly distinct. Data surfaces remain opaque; an optional toolbar material is an appearance preference, not an isolation or authorization boundary. The topology's labels are kept clear of nodes, and its selectable SVG connections use the same percentage-coordinate system as those nodes; this improves presentation without turning proposed paths into observed network evidence.

## Identity and authorization

The server derives tenant, principal, roles and producer binding from verified stored credentials. A session belongs to that verified principal. Policies are deny-by-default with explicit deny precedence. Workload grants use exact resource sets; the policy prefix cannot broaden that scope. Child scope is checked against current ancestor scope, status, expiry and maximum depth on subsequent authentication.

Approval digests include versioned NFC/compact/sorted JSON, verified tenant/principal, typed action, exact arguments, session and active policy. The requester cannot approve their own operation. The approval endpoint rejects the presence of an `approval_id`, including an explicit null.

Approval consumption and execution reservation are serialized with the session route fence. The bounded backend call occurs while that fence is held. Work already admitted and committed before restriction is reported honestly. No new protected mutation is admitted after the acknowledged barrier.

The backend independently records actual synthetic effects. Its service HMAC covers method, path, timestamp and canonical request bytes. Application bearer tokens and forged administrator headers do not authenticate the backend origin. This loopback protocol is not a claim of mTLS or general OS egress enforcement.

## Durable evidence

Every accepted event has a server receipt time, producer/source binding, tenant/session, immutable body digest and unique ID. Identical retries are duplicates, including after route changes; changed content conflicts. A durable outbox is written with the event and consumed transactionally. Received time drives correlation. Rule matches and event references are distinct from model inferences and analyst notes.

Schema revision 2 adds tenant-scoped monotonic counters so case numbers and event sequence do not get reused after retention/purge. Hash-chained audit records are application integrity evidence, not externally anchored tamper-proof storage.

## Deception boundary

The reviewed module in `mirage\resources\supplier.wat` has zero imports, no WASI context, a single 64 KiB maximum linear memory, bounded fuel and fixed synthetic response records. The broker passes only an allowlisted numeric operation, a deterministic synthetic variant and synthetic counters. A fresh module instance handles each request; the authoritative router persists only the tenant/session's synthetic counters.

Actual Wasmtime linker probes attempt unavailable socket, DNS, metadata/network interface, filesystem, environment and process imports. They fail because no host capabilities are linked. Additional tests exercise actual fuel exhaustion and denied memory growth. These are capability-boundary results, **not TCP packet probes from a container, OS firewall measurements or evidence for P3**. Wasmtime engine/host compromise is not claimed to be solved.

Restriction precedes eligibility/provisioning and route pinning. The state machine is monotonic. Missing template readiness, expired verification, TTL, budget, runtime failure or a kill switch cannot restore production. Internal employees/workloads do not receive silent fake business results. The external laboratory portal is explicitly nontransactional; genuine payment endpoints are ineligible.

## AI and foundations

Fixture investigation is deterministic and labeled as such. The Gemini adapter uses the pinned Google Gen AI SDK with explicit project/model, timeout, one attempt, token cap, structured schema and no tools. Case/version and evidence references are checked before storage. It gets bounded redacted observations, not signer/router/backend credentials.

The advisory broker in `mirage\ai.py` now handles investigation, case questions, metadata-only imported-report summaries, explicit provider checks and optional synthetic wording. Schema revision 3 adds tenant/principal/resource-bound request records with context/config digests, idempotent responses, pending limits, deadlines, usage/error state and history. Shared case and tenant budgets are reserved before inference, outside long-running provider I/O. Before accepting a result, the broker rechecks current identity/roles, source version and exact references. Failed/stale requests finish explicitly; model inference never invokes the dispatcher or response controller.

Case Q&A gets no conversation memory and at most twenty linked observations. Report summarization sends only opaque observation refs, risk tiers and counts, withholding raw scanner descriptions, code and tool names. All outputs remain untrusted plain text; references establish binding, not semantic truth. Wording cannot replace emulator protocol/state and is rechecked against the current route. Its conservative admission units are separate from reported provider tokens.

Live Gemini needs an operator-controlled egress flag, approved workload credentials/project/model and budget. The console cannot collect keys or change provider configuration. A successful provider check is a timestamped synthetic request, not a persistent connection. The current validated runtime remains fixture-only; actual SDK serialization was exercised with offline transport. A separately opt-in five-call live gate exists but remains blocked/unrun. Native gateway, PostgreSQL and cloud deployment limitations are unchanged.

The Hades adapter imports typed versioned heuristic observations. The reviewed pinned auditor was also executed against the synthetic tool manifest; it is not a continuously running SOC scanner. The structured gateway adapter accepts only authenticated gateway-source observations matching a tenant session, with idempotency and no registry writes.

Gateway telemetry cannot assert application tool/action/resource decisions. Only locally produced edge/dispatcher authorization evidence can satisfy the application containment rules; destination events remain a separate observation source.

The original gateway archive was hash-verified and selected source/license files inspected without extracting history or modifying upstream. No Rust proxy, registry, test PKI, direct-egress restriction or established-tunnel close manager was run.

## OSI placement

| Area | Current claim |
| --- | --- |
| Layer 7 | Primary: HTTP identity, API/tool/action/resource authorization, evidence correlation, session route and bounded synthetic responses |
| Layers 3/4 | Supporting P3 design; general agent destination and bypass controls are unconfigured in this profile |
| TLS | Gateway certificate proof is a separate integration. Native loopback HMAC is not a TLS certificate claim |
| Application session tracking | Not an OSI Layer 5 appliance; no arbitrary TCP/TLS session teleportation |
| SOC plane | An application service, not a new OSI layer |

Traffic outside these instrumented HTTP interfaces is outside the demonstrated boundary. An internal process can still attempt arbitrary OS networking in P1-native; protected backend authentication is tested, but agent OS egress confinement is not.
