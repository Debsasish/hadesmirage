# Verification and acceptance plan

## 1. Test philosophy

Assert backend effects, route destination and actual network reachability independently from model explanations or UI labels. Test on owned local/mock systems with synthetic records. Do not run payloads against third-party or employer production services.

P0 means release-blocking. The priorities here refer to test importance, not finding severity. Tests are specifications to implement; this package's validator does not run the product tests.

## 2. Test matrix

| ID | Priority | Scenario | Required assertion |
| --- | --- | --- | --- |
| T-01 | P0 | Spoof identity/tenant headers | Server-derived identity wins; unauthorized request rejected |
| T-02 | P0 | Allowed supplier lookup | Correct tenant record returned and audited |
| T-03 | P0 | Other asset or destructive action | Backend counter unchanged; explicit deny |
| T-04 | P0 | Injection requests prohibited tool | Dispatcher denies regardless of model compliance |
| T-05 | P0 | Approval reused or arguments changed | Exactly one approved execution; changed digest fails |
| T-06 | P0 | Backend timeout then retry | Stable execution/idempotency key; no duplicated mutation |
| T-07 | P0 | Child asks for broader/longer grant | Issuance denied; valid subset succeeds |
| T-08 | P0 | Wrong key, expired/revoked gateway grant | New tunnel denied; correct active grant allowed |
| T-09 | P0 | Agent bypasses gateway directly | Connection fails in P3 enforcement profile |
| T-10 | P0 | Caller bypasses ingress to backend origin | Request rejected on every alternate reachable origin |
| T-11 | P0 | Corroborated eligible suspicious sequence | Production restricted before decoy dispatch; decoy backend hit |
| T-12 | P0 | Concurrent mutation and restriction | Serialization/fencing outcome recorded; none admitted after barrier |
| T-13 | P0 | Decoy state repeated/cross-session reads | Stable per-session records; no cross-session disclosure |
| T-14 | P0 | Decoy probes production, control, metadata, Internet | All forbidden paths fail from actual runtime |
| T-15 | P0 | Decoy asks to execute arbitrary command | Only bounded simulation/text capture; no OS process execution |
| T-16 | P0 | Evidence text instructs SOC to allow attack | No routing/policy/grant mutation from model |
| T-17 | P0 | Model cites nonexistent or cross-tenant event | Explanation rejected; deterministic case remains |
| T-18 | P0 | Tenant A requests tenant B case/approval/decoy | No data or side effects leak |
| T-19 | P0 | Forged source, duplicate/late events | Source bound; retries deduped; online counters reproducible |
| T-20 | P0 | Request/token/concurrency budget exhausted | Engagement terminates/restricts; no production fallback |
| T-21 | P0 | Script/HTML content in evidence | UI renders inert content; no script or auto-fetch |
| T-22 | P0 | Model, route DB, policy or decoy failure | Defined fail-closed/fallback matrix is observed |
| T-23 | P1 | Benign quotation and client misconfiguration | No automatic diversion from text marker alone |
| T-24 | P0 | TTL/kill switch during engagement | Stops supported traffic; cleans state; never restores production |
| T-25 | P0 | Revoke permission with established tunnel | Observed continued/closed state documented; immediate-close claim only if implemented |
| T-26 | P1 | Policy update with pending approval | Old-policy approval unusable; versioned audit |
| T-27 | P1 | Protocol streaming/WebSocket attempt | Unsupported mode rejected/closed; no unsafe session switching |
| T-28 | P0 | User requests own approval | Separate approver required; action digest shown |
| T-29 | P1 | Multiple application instances | Same authoritative routing/approval state and concurrency outcomes |
| T-30 | P1 | Case export and deletion | Redaction retained, correct evidence links, retention enforced |

## 3. Layers

Unit: canonicalization, scope intersection, deny precedence, rule windows, route transitions, budgets and output validation.

Integration: database uniqueness/transactions, producer authentication, actual backend counters, policy-version changes, model timeout/invalid JSON, decoy state and registry signatures.

End-to-end: normal task → suspicious sequence → restriction → decoy routing → report, with independent backend evidence. Exercise concurrent requests and shared store across instances.

Infrastructure: run connectivity probes from workload/decoy network identities; test node/metadata paths and alternate origins. A policy YAML lint cannot substitute for this test.

## 4. Evaluation dataset

Create a frozen synthetic dataset of at least 50 benign sessions, 20 suspicious laboratory sequences and 10 ambiguous/misconfiguration sessions for initial debugging. For a meaningful low false-positive claim expand to a larger held-out set; with 50 benign samples, one diversion already equals 2%, and uncertainty is large. Report numerator, denominator and uncertainty rather than claiming general accuracy.

Separate rule tuning fixtures from held-out evaluation fixtures. Include shared IP users, cookie rotation, legitimate administrative workflows, quoted attack text, retries, reordered events and stale tokens. Do not ask the same model to generate all labels and then claim independent validation.

## 5. Measurement method

Capture request start, decision time, route transition commit, backend dispatch and response end using monotonic timing within process; use trace IDs and synchronized wall time across services. Report sample count, concurrency, environment/profile, provider/model config, cold/warm state and p50/p95/p99 as sample size permits. Track model time separately from enforcement overhead.

A production hit counter is authoritative for demo side effects. Decoy hits do not count as successful attacks on production. Blocking everything can produce excellent security counts but poor legitimate completion; report both.

## 6. Required release evidence

Source/image/config digests; test profile; test result artifact with each ID and outcome; isolation probe matrix; false-diversion confusion matrix; latency samples; known limitations; dependency scan results; recovery drill; source/reuse disclosure. Failures and skipped P0 tests prevent a full MVP release claim. A reduced offline demo may proceed only with explicit scope labels.
