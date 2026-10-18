# Internal agent guardrails

## 1. Policy evaluation contract

Input derives from verified identity plus validated request: tenant, workload, acting user, delegation lineage, tool, action, resource, canonical arguments, session route, policy version, time and approval. Never let a caller choose its own principal or active policy.

Decision ordering:

1. Reject invalid identity, expired delegation, unknown tenant or malformed request.
2. Reject terminated/restricted/deception sessions attempting production dispatch.
3. Apply explicit deny policies.
4. Require matching allow policy for tool, action and resource.
5. Intersect workload and acting-user scopes; verify ancestor grants for a child.
6. Validate typed arguments, destination mapping and business constraints.
7. Require and validate action-bound approval for sensitive operations.
8. Enforce quota, idempotency and current route fencing.
9. Execute once through the dispatcher; record outcome.

Policy result values: `allow`, `deny`, `require_approval`. Permission absence is deny. LLM output cannot change this ordering. Deny precedence is mandatory even if a broad allow also matches.

## 2. Proposed tool catalogue

| Tool | Action | Scope | Default |
| --- | --- | --- | --- |
| supplier.lookup | read | supplier:demo-* within verified tenant | Scoped allow |
| invoice.compare | analyze | invoice:demo-* within tenant | Scoped allow; read-only |
| payment.change_request | propose_change | supplier:demo-* | Exact request approval required; mock backend only |
| customer.export | export | No MVP grant | Deny |
| infrastructure.delete | delete | No MVP grant | Deny |

Tool names map to server-owned handlers and fixed service destinations. Reject arbitrary `url`, `command`, `headers` or `script` fields. Schema validation must enforce this, not tool descriptions.

## 3. Approval protocol

Create a pending approval from a validated action. Canonical bytes use an explicitly versioned algorithm: UTF-8 JSON, sorted keys, compact separators, normalized Unicode NFC, no NaN/infinity, no duplicate keys and money represented as integer minor units. Reject ambiguous types before hashing. Exclude the approval token and transport metadata from the digest; include principal, tenant, tool, action, resource, arguments and policy version.

A reviewer sees these exact fields and approves one execution. Store approval ID, digest, issuer, approver, timestamps, expiry and status. Requester cannot approve its own action. Consume approval and reserve execution using a database transaction with uniqueness constraints. Expired, revoked, already consumed, different-policy or digest-mismatched approvals fail.

External execution may return an unknown outcome on timeout. Backend idempotency and reconciliation are required; an approval is not automatically restored because an HTTP response was lost.

## 4. Delegation

Child identity has a distinct key and records its parent grant and lineage. Effective child scope is a subset of the parent's current scope and the issuing authority's allowed delegation. Child expiry ≤ every ancestor expiry. Revoked ancestor invalidates descendants at next authorization check. Prevent cycles and bound depth; proposed MVP max depth is 2. No transitive bearer-token copying.

Destination grants and tool/data grants must both pass independently. The existing gateway supports signer delegation by destination; it does not implement this complete user/agent lineage model. Build this lineage in the product policy service and test the gateway adapter separately.

## 5. Runtime containment

Sensitive actions use short authorization validity and fresh policy lookup. Emergency suspension increments an identity/session epoch so old approvals and cached allows fail. Connection revocation and action revocation are separate: registry changes stop new destination grants, but established tunnels require a connection manager or explicit close.

For an internal compromised agent default to deny/suspend, preserve evidence and alert. Do not silently give fake business results to staff. Controlled simulation for internal agents can be enabled only for designated laboratory identities.

## 6. Policy lifecycle

Draft → validate schema → test fixtures → review → approve → activate immutable version → monitor → rollback to previously approved version if safe. Every decision records active version. An old approval cannot be used after a policy change. Avoid stale authorization caches; default MVP has no cached allow across protected mutations.

## 7. Guardrail acceptance

The mock backend should independently confirm the tenant and permitted operation. UI hiding, prompt rules, manifest words such as 'approval required', network allowlists and successful model refusal are not proof of application authorization. Tests must observe that the backend did not perform a forbidden operation.
