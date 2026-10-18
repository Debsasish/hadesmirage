# Detection and SOC investigation

## 1. Inputs and trust

Authenticated producer events include edge request metadata, application authorization decisions, tool execution outcomes, gateway connectivity decisions and decoy observations. Optional scanner findings enrich context but are not live proof of attack.

Trusted metadata: producer identity verified at ingestion, server receipt time, tenant binding, route state and policy version written by trusted services. Untrusted data: request strings, document contents, agent outputs, MCP descriptions and claimed intent. Retain this distinction in storage and prompts.

## 2. Initial rules

| ID | Signal/window | Deterministic response | False-positive considerations |
| --- | --- | --- | --- |
| D-001 | ≥5 denied distinct resources within 60 seconds in the same tenant/session | Open investigation; restriction candidate | Misconfigured client or stale integration |
| D-002 | Prohibited tool call plus ≥3 denied enumeration requests within 60 seconds | Restrict; eligible external sessions may enter deception | Authorized tester must use explicit laboratory identity |
| D-003 | Any cryptographic approval verification failure | Deny the action; open case; investigate repetition | Corrupted client request is possible; do not assert malicious intent |
| D-004 | Any ancestor-scope escalation attempt | Deny issuance; notify security | Developer misconfiguration |
| D-005 | Any verified decoy-only resource interaction | High-confidence deception observation | A decoy interaction proves interaction with a lure, not identity attribution |
| D-006 | Injection-like text plus prohibited tool attempt in same workflow | Deny prohibited action; create investigation | Quoted educational text without a tool attempt remains monitor-only |

Thresholds are illustrative defaults and require tuning. Distinct resources count normalized server-parsed resource identifiers, not raw query strings. A failed authorization is always denied even if no detection threshold fires.

## 3. Correlation

Use authoritative tenant/session keys, optionally workload identity and verified user. Do not combine every caller on an IP into one hostile actor. IP, user agent and network fingerprint are supporting evidence only. Anonymous cookie rotation is expected evasion; apply independent edge rate limits and bounded investigation, not blanket identity claims.

Store a rolling window by server receipt time. Observed times are useful context but untrusted or skewed producers cannot control online decisions. Idempotent event insertion avoids count inflation from retries. Version rules and persist rule ID, event IDs, window bounds and matching features for reproducibility.

High event rate needs bounded buffers and backpressure. Edge volumetric controls act before expensive inference. Never invoke a model on every Internet request.

## 4. AI responsibilities

The investigator receives a case with bounded event summaries and sanitized snippets. It returns:

- A concise explanation and candidate intent, explicitly an inference.
- Evidence event IDs for each material claim.
- Alternative explanations and missing evidence.
- Recommended response from `monitor`, `review`, `restrict`, `consider_deception`.
- Confidence label `low`, `medium`, `high`, not an uncalibrated probability.

It has no network tools, shell, signer, direct policy write or routing authority. Parse against the supplied schema. Reject nonexistent/cross-tenant evidence refs, unsupported enum values or oversized responses. If output fails validation, retain deterministic case and display 'AI explanation unavailable'. A model recommendation alone never activates deception in MVP.

## 5. Deception eligibility

All must hold: explicit enabled policy; external/laboratory caller class; supported nontransactional endpoint; corroborated rule such as D-002 or D-006; production restricted; decoy isolation verified; approved template ready; budget available; route-store transaction succeeds.

Authenticated employee sessions and genuine payment submission endpoints are ineligible by default. Unknown/corrupt identity is denied rather than silently admitted to a production-looking workflow. Denial responses must avoid leaking protected resource existence.

## 6. Learning and tuning

Begin with frozen rules and replay fixtures. Analyst labels can inform future reviewed rule changes, but do not train or automatically deploy policy from attacker interactions. Separate benign, malicious-laboratory and uncertain labels. Evaluate on held-out fixtures, including benign quotations and permission misconfiguration. Report confusion matrix and denominators, not selected screenshots.

## 7. Initial alert severity

Severity reflects attempted impact, confirmed side effects and affected asset, separately from confidence. A blocked attempt does not automatically mean critical compromise. Store `attempted_impact`, `observed_outcome`, `confidence` and `severity_rationale`. Escalate proven production access or control failure immediately. Normal decoy interaction is evidence to review, not proof that production was compromised.
