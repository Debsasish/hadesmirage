# Hades Mirage — product definition

## 1. Product statement

An AI-assisted SOC and agent security platform that keeps internal agents within authorized boundaries and contains eligible suspicious external interactions in isolated, adaptive decoys. It turns security signals into evidence-backed cases, enforceable decisions and observable response outcomes.

Working tagline: **Bound agent authority. Protect production. Investigate through deception.**

## 2. The two problems

### Internal agent risk

An internal agent can make mistakes, receive injected instructions, misuse a broad credential, delegate too much authority or attempt a damaging operation on an unrelated asset. Trust in the agent's prompt is insufficient. Authorization must be enforced outside the model, at the network and application boundaries.

### External hostile interaction

A user, bot or external agent may enumerate interfaces, probe permissions, manipulate prompts or request sensitive tools. The platform should detect and investigate the pattern, deny prohibited access and, where eligible, serve an isolated simulation that collects additional behaviour evidence. It cannot reliably infer that an anonymous caller is an AI; enforcement is based on behaviour and verified identity.

## 3. Target users and jobs

| User | Job | Outcome |
| --- | --- | --- |
| SOC analyst | Investigate a suspicious sequence | Timeline, evidence, policy decisions and response actions in one case |
| Security engineer | Configure enforcement and decoy eligibility | Versioned, testable rules and bounded permissions |
| Agent developer | Onboard an application and its tools | Explicit capabilities, constraints and regression tests |
| Application owner | Keep normal work functioning | Measured legitimate task completion and an appeal path |
| Incident commander | Stop or isolate a session | Audited termination, revocation and recovery controls |
| Reviewer/judge | Evaluate a reproducible prototype | Clear distinction between implemented controls, simulations and future work |

## 4. User stories and requirements

| ID | Requirement | MVP acceptance |
| --- | --- | --- |
| FR-01 | Register protected applications and agent identities | One application, two internal identities, approved tools and asset scopes |
| FR-02 | Enforce action authorization | Every tool call is checked for identity, tenant, action, resource, arguments and approval |
| FR-03 | Restrict destinations | Allowed destination succeeds; unauthorized destination and direct bypass fail in the enforcement profile |
| FR-04 | Constrain sensitive changes | One-time, request-bound approval is required; replay and changed arguments fail |
| FR-05 | Bound delegation | Child scope is a subset of parent scope; child expiry cannot exceed parent expiry |
| FR-06 | Ingest security events | Authenticated producers submit validated, deduplicated events with server timestamps |
| FR-07 | Correlate suspicious behaviour | At least three deterministic scenarios plus benign lookalikes |
| FR-08 | Explain incidents using AI | Structured summary cites event IDs; invalid or unsupported output is rejected |
| FR-09 | Divert eligible sessions | Server-owned route state selects a ready decoy before the next production dispatch |
| FR-10 | Run isolated adaptive decoys | Approved templates, synthetic data, per-session state and no production reachability |
| FR-11 | Track evidence and audit | Analyst can reconstruct a decision and its policy version from the case |
| FR-12 | Stop engagement | Kill switch stops decoy sessions without releasing them to production |
| FR-13 | Report outcomes | Export structured case JSON and Markdown/HTML report with measured results |
| FR-14 | Separate simulated and enforced outcomes | Every demonstration labels the active deployment/enforcement profile |

## 5. Explicit scope

MVP: HTTP/JSON application requests; a controlled AI assistant; three server-side tools; destination restrictions through the supplied gateway in a separate enforcement profile; bounded detection rules; a simulated supplier API decoy; analyst dashboard; synthetic data; Gemini-based investigation and constrained decoy wording.

Later: streaming MCP adapters, enterprise SSO, multi-application onboarding, stronger tenancy isolation, approved SIEM connectors, automated policy recommendations, dedicated decoy clusters, production PKI and retention integrations.

Out of scope: Internet-wide interception, autonomous hack-back, arbitrary shell execution in honeypots, detection of every attack, guaranteed AI-attribution, DDoS absorption, replacing EDR/WAF/SIEM, recovery of assets already compromised outside the boundary, silently copying production sessions or data into decoys.

## 6. Product behaviour

**Normal internal task:** authenticate → authorize tool/action/resource → enforce destination → execute → audit.

**Internal prohibited task:** deny before side effect → record evidence → correlate → revoke or suspend if policy warrants. Internal identities use explicit denial; silent deception for employees is disabled by default.

**External suspicious session:** collect evidence → deny prohibited request → correlate sequence → check deception eligibility → atomically pin future eligible requests to isolated synthetic state → observe → report → expire.

**Uncertain signal:** monitor or request additional verification; do not silently divert a legitimate business transaction based only on model suspicion.

## 7. Differentiation hypothesis

The proposed product joins behaviour evidence, agent permission enforcement and session-specific deception into a traceable incident lifecycle. AI supports investigation and realistic synthetic responses; cryptographic identity, schemas and deterministic policy decide authority. Market novelty is a hypothesis, not established by this blueprint.

## 8. Engineering targets

| Target | Initial laboratory objective | Measurement |
| --- | --- | --- |
| Unauthorized protected side effects | Zero across defined scenarios | Independent backend counters and audit records |
| Legitimate task completion | At least 95% on the frozen benign fixture set | Completed tasks / eligible tasks |
| False diversion | At most 2% on the frozen benign fixture set | Diverted benign sessions / benign sessions; report denominator |
| Policy authorization latency | p95 under 100 ms in local test, excluding backend and model | Timed decision spans under stated load |
| Ready-decoy routing transition | p95 under 500 ms after policy decision | Route commit to first decoy response |
| Incident summary | p95 under 15 s with chosen model and load | Report observed latency, timeout rate and model configuration |
| Isolation | All enumerated forbidden network paths fail | Probe matrix from actual decoy runtime |

These are goals. Publish actual measured values and fixture coverage; do not claim universal attack prevention.

## 9. Constraints and delivery choices

Two-person hackathon team. Prefer a narrow vertical slice before integrations. Use Gemini on Vertex AI and a Cloud Run application for the Builder Cup demonstration. Preserve the original gateway's client-certificate verification on a suitable separate TLS endpoint rather than claiming it works unchanged behind Cloud Run TLS termination. See deployment profile definitions.

CyberForge's supplied rules prohibit pre-existing solutions. Disclose Hades-Blackwatch, gateway provenance, third-party dependencies and newly authored integration work. Eligibility of reuse requires organizer clarification; this package does not establish submission eligibility.

## 10. Definition of the MVP

A live normal task succeeds. A damaging unauthorized operation never reaches its mock backend. An eligible suspicious session is diverted at the controlled ingress to a synthetic decoy. The analyst sees a correlated case with actual decision and route evidence. Isolation and failure tests pass. Reports state the limits of what was tested.
