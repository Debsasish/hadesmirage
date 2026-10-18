# Engineering backlog

Owner A: backend/policy/integration. Owner B: UI/decoy/evaluation. Both: review and acceptance. Effort is a relative planning estimate, not a completion guarantee.

| ID | Priority | Work item | Owner | Dependencies | Acceptance |
| --- | --- | --- | --- | --- | --- |
| HM-001 | P0 | Scope, fixture application and provenance register | Both | None | FR list and selected-file source pins recorded |
| HM-002 | P0 | Repository, CI, formatting and secret checks | A | HM-001 | Clean checks on initial code |
| HM-003 | P0 | Contract models and fixture validation | A | HM-001 | Valid examples pass; malformed examples fail |
| HM-004 | P0 | Verified principal and tenant context | A | HM-003 | T-01, T-18 |
| HM-005 | P0 | Tool/action/resource policy evaluator | A | HM-004 | T-02, T-03 |
| HM-006 | P0 | Synthetic backends with mutation evidence | B | HM-003 | Independent hit/side-effect counters |
| HM-007 | P0 | Approval digest and separate reviewer | A | HM-005 | T-05, T-28 |
| HM-008 | P0 | Execution idempotency and reconciliation | A | HM-006, HM-007 | T-06 |
| HM-009 | P0 | Delegation lineage and scope intersection | A | HM-005 | T-07 |
| HM-010 | P0 | Authenticated event ingest and durable outbox | A | HM-004 | T-19 |
| HM-011 | P0 | Versioned detection rules | A | HM-010 | Reproducible D-001–D-006 matches |
| HM-012 | P0 | Incidents and evidence reference store | A | HM-011 | Tenant-scoped evidence refs |
| HM-013 | P0 | Atomic route state and dispatch barrier | A | HM-008, HM-012 | T-11, T-12 |
| HM-014 | P0 | Fixed decoy template and synthetic state | B | HM-006 | T-13, T-15 |
| HM-015 | P0 | Isolation deployment and probe runner | Both | HM-014 | T-14 |
| HM-016 | P0 | Eligibility and warm-decoy assignment | A | HM-013, HM-015 | No production fallback |
| HM-017 | P0 | TTL, budgets, cleanup and kill switch | B | HM-016 | T-20, T-24 |
| HM-018 | P1 | Hades findings adapter and provenance | A | HM-012 | Heuristic observations clearly labelled |
| HM-019 | P0 for P3 | Native gateway registry/certificate tests | A | HM-004 | T-08, T-25 |
| HM-020 | P0 for P3 | Egress restriction and gateway telemetry | A | HM-019 | T-09 |
| HM-021 | P0 | Investigator schema/provider interface | A | HM-012 | T-16, T-17, T-22 |
| HM-022 | P1 | Constrained Gemini decoy wording | B | HM-014, HM-021 | Static fallback, no runtime provider secrets |
| HM-023 | P0 | Analyst dashboard and inert evidence renderer | B | HM-012, HM-017 | T-21 |
| HM-024 | P0 | Role-gated actions and audit export | A | HM-023, HM-007 | T-18, T-28 |
| HM-025 | P0 | Isolation/race/failure evaluation | Both | HM-017, HM-021 | All relevant P0 tests |
| HM-026 | P1 | Cloud Run application demo | Both | HM-025 | Cloud identity/origin checks |
| HM-027 | P1 | Frozen benchmark and measured results | B | HM-025 | Legitimate completion and false-diversion denominators |
| HM-028 | P1 | Demo video, report and reuse disclosure | Both | HM-026, HM-027 | Claims match actual implemented profile |

## Deferred work

Streaming MCP adapter; dedicated enterprise SSO and PKI; live SIEM connectors; signed template distribution; advanced behaviour baselines; policy recommendation UI; hardened high-interaction deception research; immediate native-tunnel close manager if absent; multi-region recovery. Each requires its own acceptance evidence before claims expand.
