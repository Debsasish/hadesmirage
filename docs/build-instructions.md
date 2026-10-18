# Implementation guide for a developer or coding agent

## 1. Proposed repository layout

```text
hades-mirage/
  README.md
  AGENTS.md
  blueprint/
  apps/dashboard/
  services/edge/
  services/control_api/
  services/dispatcher/
  services/investigator/
  services/decoy_router/
  services/decoy_emulator/
  packages/contracts/
  packages/policy/
  packages/events/
  packages/identity/
  adapters/hades/
  adapters/gateway/
  migrations/
  deploy/local/
  deploy/cloudrun/
  deploy/gateway/
  tests/unit/
  tests/integration/
  tests/e2e/
  tests/isolation/
  tests/fixtures/
  tools/
```

This is a proposed implementation tree; the blueprint ZIP does not contain these services. Prefer a modular Python application initially rather than many independently deployed microservices. Keep logical authority boundaries explicit even if modules share a process in P1. Stronger profiles separate processes and credentials.

## 2. Suggested technology choices

Python/FastAPI with typed models for control API and dispatcher; PostgreSQL for authoritative state; a durable outbox/worker before adding an external queue; a small React/TypeScript dashboard if the team already knows it; Gemini on Vertex AI behind a provider interface; original Rust gateway unchanged until adapter tests establish baseline. These are recommendations, not installed dependencies. Verify supported versions and official APIs during implementation, then lock them.

A lightweight Python synthetic assistant/client is sufficient for demo orchestration. An agent framework is optional; do not add one solely for branding. MCP support requires a proper protocol adapter and tests, not naming ordinary HTTP functions 'MCP tools'.

## 3. Coding order

1. Import contracts and implement schema-validation tests.
2. Implement pure policy logic and canonicalization with negative tests.
3. Add principal context adapter and isolated synthetic backends.
4. Add dispatcher, approvals and idempotent execution state.
5. Add event ingestion/correlation and incident views.
6. Add route-state barrier and prestarted decoy.
7. Prove isolation and diversion with backend counters.
8. Integrate Hades fixtures and real native gateway tests.
9. Add model provider, evidence validation and safe UI.
10. Deploy only after profile-specific acceptance checks pass.

## 4. First implementation prompt

> Build M0 and M1 from this blueprint only. Read project.md, plan.md, docs/security-model.md, docs/guardrails.md and docs/contracts.md. Create a minimal modular implementation with synthetic local services. Enforce verified principal context, deny-by-default tool authorization, one-time request-bound approvals and backend idempotency. Do not implement a fake allow decision based on tool descriptions. Write meaningful tests T-01 through T-07 and T-28. Show backend side-effect evidence. Do not deploy externally, execute real attacks or modify either upstream repository. Report implemented capabilities, tests and remaining gaps.

## 5. Next implementation prompt

> Continue with M2 and M3 after the existing acceptance tests pass. Implement authenticated event ingestion, deterministic correlation and versioned session routing. Restrict production dispatch before activating a decoy; never fallback to production on failure. Use a fixed synthetic supplier-service template with no production data or credentials. Add T-11 through T-20, T-22 and T-24. Demonstrate actual route/backend outcomes and failed forbidden network paths. Keep model recommendations out of authorization.

## 6. Integration prompt

> Implement M4 using pinned copies of Hades-Blackwatch and the supplied gateway. Review source licenses and preserve notices. Keep Hades findings as evidence/proposals, never signed permissions. Run native gateway tests for identity/key/destination binding and enforce direct-egress denial in P3. Record established-tunnel revocation limitations. Do not claim Python teaching scenarios prove Rust proxy enforcement. Update source pins, adapter docs and measured tests.

## 7. AI/UI/deployment prompt

> Implement M5/M6 without weakening completed controls. Add a Gemini provider with bounded, schema-validated evidence explanations and synthetic decoy wording. Reject forged evidence refs. Render all external content inertly. Deploy the application demo on Cloud Run only after cloud identity/origin checks; keep the native mTLS gateway on an appropriate endpoint. Publish measured outcomes, active profile and limitations, not invented metrics.

## 8. Review checklist for generated code

No trusting principal/tenant headers, no arbitrary upstream URL, no broad agent credential, no model tool rights, no decoy production mounts, no unsigned grant insertion, no approval replay, no in-memory routing in multi-instance profile, no automatic restoration of diverted session, no unauthenticated admin endpoint, no raw HTML evidence rendering and no real data in fixtures. Check failure paths before adding features.
