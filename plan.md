# Hades Mirage — implementation plan

## 1. Delivery principle

Build one end-to-end path, prove it is enforced, then broaden it. Do not start with many agents, enterprise connectors or dynamic infrastructure. This is a proposed schedule; adjust after the first working slice. No coding, deployment or real attack execution has been performed by preparing this package.

Owner A: backend, policy, integrations and event pipeline. Owner B: UI, synthetic application, decoys and evaluation. Both review security boundaries. Roles are proposed, not assigned to named people.

## 2. Dependency map

| Milestone | Depends on | Deliverable |
| --- | --- | --- |
| M0 Scope and source baseline | None | Frozen demo boundary, source pins and threat model |
| M1 Protected vertical slice | M0 | Identity → tool authorization → mock backend → audit |
| M2 Event and incident pipeline | M1 | Validated events, deterministic correlations and cases |
| M3 Isolated deception slice | M1, M2 | Eligible session diverted to an isolated decoy |
| M4 Hades and gateway integration | M1; parallel with M2/M3 | Evidence adapter and separately verified destination enforcement |
| M5 AI investigation and dashboard | M2, M3 | Cited AI summaries and observable incident lifecycle |
| M6 Evaluation and cloud demo | M3, M4, M5 | Repeatable demonstration and security evidence |
| M7 Enterprise pilot | M6 | Dedicated isolation, SSO, operations and controlled pilot |

## 3. M0 — scope and foundation (0.5 day)

- [ ] Create a new implementation repository; keep this blueprint in `blueprint/` or `docs/design/`.
- [ ] Record source commit refs, licenses and all reused files. Do not copy uploaded Git history or private configuration.
- [ ] Define the protected app as a procurement assistant with supplier lookup, invoice comparison and payment-change request tools.
- [ ] Define production-like mock and decoy namespaces; all records are synthetic.
- [ ] Decide profile: local prototype first; cloud application demo second; full gateway enforcement separately.
- [ ] Review FR-01–FR-14, actor roles, threat boundaries and excluded threats.
- [ ] Freeze event/schema v1, operation names and route modes.
- [ ] Configure formatting, dependency lockfiles, schema checks, secret scanning and CI.

Exit: scope document approved by project owner; no unresolved ambiguity about what the demo enforces. Backlog: HM-001–HM-003.

## 4. M1 — protected vertical slice (1–2 days)

### Owner A

1. Implement a transport-authentication adapter returning a verified `PrincipalContext`; discard client-supplied identity and tenant headers.
2. Implement a deterministic policy evaluator with deny-by-default and exact matching on resource scope.
3. Implement request canonicalization and SHA-256 action digest for approvals.
4. Add the tool dispatcher: authorize → validate arguments → check approval → execute → record result.
5. Store approval consumption and mutation idempotency in a transaction. Define partial backend failure semantics.
6. Build one-time approval tied to principal, tool, action, resource, digest, policy version and expiry.
7. Enforce child-scope subset and expiry checks before issuing delegated identity.
8. Close direct tool/backend ingress paths; add server-owned service credentials only at execution time.

### Owner B

1. Implement synthetic supplier and invoice mock services with backend-side mutation counters.
2. Implement a basic UI for legitimate lookup and an explicitly restricted payment-change request.
3. Add developer fixtures for two identities with different scopes.
4. Display authorization outcomes without exposing secrets.

Exit tests: benign read works; other-tenant read fails; unapproved mutation fails before backend; altered/replayed approval fails; same request retry does not duplicate mutation; self-reported administrator header changes nothing. Backlog: HM-004–HM-009.

## 5. M2 — events and cases (1 day)

- [ ] Add authenticated event ingestion, size bounds, JSON schema validation, rate limiting and event idempotency.
- [ ] Separate trusted producer metadata from attacker-controlled request content.
- [ ] Record received time and observed time; use received time for online correlation.
- [ ] Implement rules D-001–D-006 with event references and configurable windows.
- [ ] Persist incidents, observations and deterministic verdicts; distinguish model recommendations.
- [ ] Add per-tenant/session sequencing and concurrency control.
- [ ] Test late, duplicate, out-of-order and forged events.

Exit: fixed event replay yields reproducible incidents; one textual injection marker alone cannot divert a normal session; protected denials do not depend on the model. Backlog: HM-010–HM-012.

## 6. M3 — isolated deception (1–2 days)

### Preparation

- [ ] Build a fixed supplier-portal template: fake tool catalogue, synthetic invoices, simulated payment-change results.
- [ ] Start a warm decoy pool with no production secret mounts and no outbound network access.
- [ ] Keep model access outside the decoy runtime: a control-plane broker sends sanitized text only and returns validated wording.
- [ ] Verify deny paths to production services, management APIs, DNS/external networks and metadata endpoints before marking ready.

### Routing

- [ ] Implement `PRODUCTION`, `RESTRICTED`, `DECOY_PENDING`, `DECOY`, `TERMINATED` with compare-and-swap route versions.
- [ ] Evaluate eligibility: supported endpoint, eligible caller class, corroborated rule, ready template, active budget and tenant isolation.
- [ ] Atomically restrict production dispatch, provision synthetic state, confirm readiness, then pin the session to a decoy.
- [ ] Revalidate route immediately before production side effects; cancellation cannot undo an already committed action.
- [ ] Mark every event with route mode and decoy ID. Never copy authentication tokens or real records into the decoy.
- [ ] If isolation, provisioning or routing fails, remain restricted and return denial; never fallback to production.
- [ ] Add session termination, request budgets, TTL and state purge.

Exit: diversion is observable at the backend; no production request after the route barrier; decoy responses are coherent; no production/external reachability; model outage uses safe static responses. Backlog: HM-013–HM-017.

## 7. M4 — source integrations (1–2 days, may overlap M2/M3)

### Hades-Blackwatch

- [ ] Pin a reviewed commit, rather than depend on a changing default branch.
- [ ] Run selected static scripts only against controlled local fixtures.
- [ ] Parse and validate outputs through a narrow adapter; record provenance and tool version.
- [ ] Label manifest keyword matches as heuristic observations, not runtime proof.
- [ ] Map findings to reviewed policy proposals and regression cases. No direct signing or policy activation from report text.

### Gateway

- [ ] Build the Rust gateway and migrate its authorization DB in a separate test environment.
- [ ] Generate test-only certificates and signed permissions using isolated signer tooling.
- [ ] Verify exact identity/key/destination binding, signer delegation, expiry and revocation for new connections.
- [ ] Force internal agent egress through the gateway and block direct paths.
- [ ] Add a structured gateway-event adapter; do not parse free-form logs as trusted control commands.
- [ ] Test established-tunnel behaviour after revocation; implement separate connection teardown before claiming immediate containment.
- [ ] Keep management DB and gateway registry credentials separate.

Exit: real gateway allow/deny evidence exists, bypass fails and the dashboard clearly labels this profile. Backlog: HM-018–HM-020.

## 8. M5 — AI and analyst experience (1–2 days)

- [ ] Add model interface with deterministic replay mode and a Gemini provider.
- [ ] Give investigator only redacted evidence and approved policy context; no tools, signer or database mutation authority.
- [ ] Validate structured output; require referenced event IDs to exist in the case and tenant.
- [ ] Attach analyst-visible uncertainty and evidence gaps. Model verdict cannot override a deterministic denial.
- [ ] Add decoy wording generation with template vocabulary, token limits and output filtering.
- [ ] Render all attacker/model content as inert text; no raw HTML, automatic link fetch or executable Markdown.
- [ ] Implement dashboard: overview, case timeline, guardrail decisions, active decoys, evidence and configuration versions.
- [ ] Implement role-gated approval, terminate, export and rollback controls with audit.

Exit: normal and suspicious sessions are explainable; forged model evidence is rejected; UI handles malicious strings safely. Backlog: HM-021–HM-024.

## 9. M6 — release and demo (1–2 days)

- [ ] Freeze fixture set and test expected outcomes before measuring.
- [ ] Run all P0 tests, isolation probes, race tests and failure injection.
- [ ] Measure backend side effects independently of proxy claims.
- [ ] Deploy application/control-plane demo to Cloud Run with Gemini and synthetic fixtures.
- [ ] Keep native gateway on a suitable TLS-preserving VM/cluster endpoint; prove connectivity or label it separate.
- [ ] Restrict origin services and cloud IAM; verify application authentication after deployment.
- [ ] Record source versions, config digests, test counts, latency distribution and unresolved failures.
- [ ] Prepare a three-minute demo, architecture slide and reuse disclosure.

Exit: all P0 acceptance tests pass; no undocumented bypass; measured report and rollback runbook exist. Backlog: HM-025–HM-028.

## 10. Emergency 24–36 hour prototype track

This is a reduced demonstration, not the full MVP and not a promise to complete all work before any deadline.

| Hours | Owner A | Owner B | Gate |
| --- | --- | --- | --- |
| 0–3 | Identity stub restricted to local fixtures; tool policy | Mock app and synthetic data | Normal request and explicit denial |
| 3–8 | Event store and two correlation rules | Isolated static decoy template | No production path from decoy |
| 8–14 | Atomic route state and restricted fallback | Timeline and decoy UI | Real request routed to decoy |
| 14–20 | Gemini case explanation with event citations | Benign and suspicious replay scenarios | AI evidence validation |
| 20–28 | Gateway integration if stable; otherwise separate documented test | Cloud Run app demo and video | No simulated gateway claim |
| 28–36 | P0 verification and bug fixes | Reporting and demo rehearsal | Known limits disclosed |

Defer dynamic infrastructure, advanced baselines, enterprise connectors and broad MCP compatibility. If isolation or authorization cannot be proven, demonstrate offline and label enforcement unavailable.

## 11. Enterprise pilot track (following MVP)

Weeks 1–2: approved identity provider, PKI rotation, signing service, separation of administrative duties and read-only monitoring pilot.

Weeks 3–4: tenant isolation, dedicated decoy environment, external review, alert integrations and load/failure testing.

Weeks 5–6: shadow detection, analyst feedback, false-positive tuning and staged enforcement on one low-impact application.

Weeks 7–8: controlled deception rollout, independent isolation assessment, operational drills and pilot exit review.

## 12. Change and release rules

No feature is complete solely because its UI looks correct. Record enforcement evidence and negative tests. If a milestone fails, preserve default-deny behaviour and reduce demo scope. Update project, backlog, contract and tests together. Do not silently weaken a boundary to make a demonstration pass.
