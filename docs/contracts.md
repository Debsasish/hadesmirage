# APIs, events and persistent data

## 1. Contract status

The files under `contracts/` are initial implementation contracts, not running endpoints. JSON Schema uses draft 2020-12. OpenAPI is 3.1. Every endpoint must enforce identity, tenant ownership and role checks on the server. Schema conformance is necessary but cannot prove authorization.

## 2. Actor permissions

| Role | Allowed actions |
| --- | --- |
| event_producer | Ingest events only for its configured tenant and source |
| workload | Invoke approved tools using transport-derived identity |
| analyst | Read scoped incidents, request restricted responses and terminate engagements |
| approver | Approve/reject exact pending actions; cannot approve own requests |
| security_admin | Propose/activate reviewed policy and enable templates |
| orchestrator | Restrict/pin eligible sessions through service-only API with current route version |
| signer | Issue approved structured grants; never reachable by model or decoy |

## 3. API semantics

All `/v1/` endpoints require authenticated service/user identity. `Authorization: Bearer` in OpenAPI denotes the application transport, not gateway mTLS. Verify signature, issuer, audience, expiry and intended service. Strip spoofable identity headers at the edge.

- `POST /v1/events`: validate schema and producer binding; return 202 with receipt status; identical event ID/content is duplicate, same ID/different content is conflict.
- `POST /v1/tools/invoke`: server derives principal, tenant and policy; returns decision, execution state and result. Deny/approval required cause no backend side effect.
- `POST /v1/approvals`: workload requests review of exact normalized action; server computes digest.
- `POST /v1/approvals/{id}/decision`: authorized separate reviewer approves/rejects; no request-body principal authority.
- `GET /v1/incidents` and `GET /v1/incidents/{id}`: tenant-scoped pagination/detail with redaction.
- `POST /v1/sessions/{id}/restrict`: authorized service/operator transition with expected route version; success never implies existing side effects were undone.
- `POST /v1/sessions/{id}/engage`: orchestrator-only; restrict first, validate eligibility, assign ready template and CAS route version; asynchronous provisioning may return pending.
- `POST /v1/sessions/{id}/terminate`: deny future production and decoy dispatch, close supported sessions and schedule cleanup.

HTTP errors: 400 invalid syntax; 401 unauthenticated; 403 unauthorized; 404 absent or intentionally concealed cross-tenant resource; 409 stale version/idempotency conflict; 413 oversized; 422 schema/semantic failure; 429 budget/rate limit; 428 exact action approval required; 503 unsafe dependency unavailable. Use a standard error body with `code`, `message`, `request_id`; never return secrets or raw SQL.

Mutations require `Idempotency-Key`, scoped to caller, tenant, route and canonical request digest. Same key/different body returns 409. Preserve durable execution status for response-loss retries. `expected_route_version` is a concurrency precondition, not caller control of route state.

## 4. Persistent model

| Table | Key and key fields | Constraints |
| --- | --- | --- |
| tenants | tenant_id | Server-managed tenant identity |
| principals | tenant_id, principal_id, kind, status, identity_epoch | Unique verified identity binding |
| delegations | tenant_id, grant_id, parent_grant_id, child_id, scopes, expires_at | No cycles; scope subset and depth checks |
| policy_versions | tenant_id, version_id, digest, status, approved_by | Activated versions immutable |
| sessions | tenant_id, session_id, route_mode, route_version, identity_epoch, decoy_id | CAS transitions; tenant-bound references |
| events | tenant_id, event_id, source, type, occurred_at, received_at, body_digest, body | Unique tenant/event ID; immutable event content |
| incidents | tenant_id, incident_id, severity, status, rule_version | Evidence refs must be same tenant |
| incident_events | tenant_id, incident_id, event_id | Composite foreign keys |
| approvals | tenant_id, approval_id, requester, digest, policy_version, status, expiry, approver | One consumption; requester ≠ approver |
| executions | tenant_id, execution_id, idempotency_key, digest, state, backend_key | Unique scoped idempotency; unknown outcomes retained |
| decoys | tenant_id, decoy_id, template_version, session_id, state, expires_at, isolation_attestation | Never assigned across tenants |
| synthetic_records | tenant_id, decoy_id, record_id, content | Separate credentials/store in hardened profile |
| audit_log | tenant_id, audit_id, actor, action, object_id, receipt_time, integrity_digest | Append-only app role; protected retention |

All cross-table references include tenant_id. Use DB row-level security where available plus application checks; neither replaces the other. The native gateway authorization tables live separately and keep their original schema.

## 5. Event lifecycle

Producer emits stable UUID → authenticated ingress derives source/tenant → validate/bound/redact → store event with server receipt time and digest → durable outbox → correlation → incident update → optional AI explanation → audited response. Process consumers idempotently. Queue retries cannot inflate rule counters. Dead-letter invalid events with bounded metadata; never feed raw invalid payloads to an investigator.

## 6. Transaction boundaries

Approval consumption and execution reservation are atomic locally. Backend idempotency makes retries safe across the network boundary. Route transition and dispatch fencing serialize at the authoritative state layer. Model requests are outside database locks; their output is discarded if the case/version changed incompatibly.

## 7. Retention defaults for synthetic demo

Proposed defaults: session route state 24 hours after termination, synthetic decoy state purged on cleanup, redacted event metadata 7 days, reports retained until manual reset. These are configurable demonstration defaults, not enterprise retention decisions. Pilot must approve evidence, privacy and deletion requirements before real data capture.

Manual restriction/termination creates a trusted control event first and cites that event in the transition request. The evidence array must not force an operator to fabricate an attacker event. Approvals requested through POST /v1/approvals must not include an approval_id; reject that field for this endpoint even though the shared invocation schema permits it for actual execution.
