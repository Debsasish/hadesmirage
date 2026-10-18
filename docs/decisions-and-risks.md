# Decisions, defaults and risks

## 1. Working defaults

| Decision | Default | Reason |
| --- | --- | --- |
| First use case | Procurement assistant with synthetic services | Clear normal workflow and prohibited actions |
| First protocol | Bounded HTTP/JSON requests | Testable request boundaries |
| Internal suspicious identity | Deny/suspend and alert | Avoid fake business outcomes for employees |
| External deception eligibility | Corroborated policy-triggered, nontransactional sessions | Reduce false diversion harm |
| Decoy provisioning | Warm fixed template plus per-session state | Fast, bounded and reproducible |
| Investigator | One bounded model call per qualifying case | Cost and authority control |
| Policy | Deterministic explicit allow/deny and approval | Outside model influence |
| Authoritative store | Shared PostgreSQL | Transactions, fencing and tenant constraints |
| Real gateway host | Suitable VM/cluster endpoint | Preserve certificate verification |
| Model | Configurable supported Gemini on Vertex AI | Builder Cup deployment fit |

These choices are adopted for planning, not user approvals for deployment or spending.

## 2. Decisions needed before enterprise pilot

Identity provider and tenant model; approved certificate issuer/key protection; tool/backend authorization semantics; allowed monitored endpoints; legal/privacy/retention requirements; cloud region and project; production/deception network isolation; SIEM/ticket/email integration; operator staffing; alert thresholds; service-level objectives; backup/recovery requirements; approval ownership; source reuse permission.

Proceed with synthetic local development using documented defaults; do not block the blueprint on enterprise procurement decisions. Resolve these before real environment integration.

## 3. Risk register

| Risk | Consequence | Mitigation/exit criterion |
| --- | --- | --- |
| False diversion | Legitimate workflow receives synthetic answers | Eligibility exclusions, corroboration, shadow mode, fresh-session recovery |
| Decoy escape or pivot | Production/control compromise | Low-interaction templates, strict isolation and live connectivity tests |
| Broad allowed destination | Malicious action within an allowed service | Tool/action/data checks at dispatcher and backend |
| Model injection | Fabricated analysis or malicious wording | Data-only bounded prompts, schema/evidence validation, no authority |
| Route races | Production dispatch after restriction | Shared authoritative state and fencing tests |
| Key theft | Workload impersonation | Key protection, short credentials, revocation and session close |
| Direct bypass | Controls never see operation | Network/origin restrictions and negative route tests |
| Unclear transaction outcome | Duplicate financial-like mutation | Idempotent backend and reconciliation |
| Model resource abuse | Cost/availability incident | Pre-inference limits, quotas and static fallback |
| Existing-source eligibility | Hackathon disqualification | Disclose and obtain organizer clarification |
| Scope expansion | Nonfunctional demo | Complete one tested vertical slice before extra connectors |
| Misleading demo | Reviewers overestimate protection | Active profile labels and actual evidence |

## 4. Product boundary

Hades Mirage supplements existing security controls. It does not prevent every compromise, prove an actor's identity from behaviour, reverse completed actions or guarantee engagement. Its defensible claim is bounded enforcement and evidence collection at tested controlled interfaces.
