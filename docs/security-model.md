# Security model and threat boundaries

## 1. Assets and adversaries

Assets: production records, credentials, agent authority, user delegation, signing keys, routing state, policy integrity, incident evidence, tenant separation and availability.

Adversaries: anonymous callers, authenticated users exceeding scope, compromised internal agents, malicious retrieved documents/tool outputs, stolen session or workload credentials, hostile MCP metadata, compromised dependencies and abuse of model resources. Administrator or host compromise requires separate infrastructure controls and is not solved by this product.

## 2. Threat and control matrix

| ID | Threat | Required control | Test |
| --- | --- | --- | --- |
| TH-01 | Agent changes unrelated asset | Resource/action authorization outside model | T-02, T-03 |
| TH-02 | Prompt injection triggers tool misuse | Untrusted context isolation and deterministic dispatcher | T-04 |
| TH-03 | Parent delegates broader access | Scope intersection, lineage, expiry and child key binding | T-07 |
| TH-04 | Direct connection bypasses proxy | Backend ingress restrictions and enforced outbound paths | T-09, T-10 |
| TH-05 | Decoy pivots into production | Separate credentials and network; no executable attacker actions | T-14, T-15 |
| TH-06 | External user spoofs agent/tenant | Verified identity, header stripping and tenant scoping | T-01, T-18 |
| TH-07 | Approval replay or argument substitution | One-time digest-bound approvals and execution idempotency | T-05, T-06 |
| TH-08 | Attacker poisons investigator or evidence | Data-only prompts, source trust labels, output schema and evidence checks | T-16, T-17 |
| TH-09 | Concurrent requests cross diversion boundary | Atomic route state and side-effect dispatch barrier | T-12 |
| TH-10 | Resource exhaustion through engagement | Global/tenant/session budgets, limits and static fallback | T-20 |
| TH-11 | Stored XSS in analyst UI | Inert rendering, CSP, no automatic outbound link fetching | T-21 |
| TH-12 | Forged events induce containment | Authenticated producers, schema, tenant/source attribution | T-19 |
| TH-13 | Key theft impersonates agent | Short credentials, key protection, revocation and connection termination | T-08, T-25 |
| TH-14 | Cross-session fake data leaks | Tenant/session synthetic namespaces and cleanup | T-13, T-18 |

## 3. Authentication model

Certificate possession proves possession of a private key, not benevolence. A stolen key can impersonate the holder until mitigated. Production deployment must define certificate trust, issuance, expiry, revocation and rotation. Identity strings alone are never authentication. At an HTTP TLS-terminating edge use a separately verified token/service identity; do not treat forwarded certificate text as equivalent to the gateway's TLS proof of possession.

Human authority and workload identity are distinct. Effective scope is the intersection of service permission, human delegated scope and application policy. Missing or unverifiable delegation means no access to user-scoped assets. Tenant selection is server derived and cannot be altered by request JSON.

## 4. Isolation guarantees to verify

A decoy has no live data copy, no production token, no signer, no service account with cloud roles, no host filesystem/Docker socket, no host networking and no production route. It exposes only bounded emulated operations. Run non-root, read-only filesystem, resource limits and dropped capabilities. Namespace separation alone is insufficient; Kubernetes policies require an enforcing network plugin, and host/metadata exceptions require additional controls.

For MVP use low-interaction emulation only. Any later high-interaction runtime handling attacker binaries requires stronger isolation, dedicated infrastructure and independent review; ordinary containers are not claimed to contain arbitrary native-code exploitation.

A compromised decoy may return hostile text. The collector and UI must remain robust against it. The model broker uses bounded data, no tool calling and strict output validation.

## 5. Limits of diversion

- Only instrumented ingress/dispatch boundaries can divert traffic.
- Do not hijack third-party services or redirect traffic outside owned/authorized environments.
- Do not divert legitimate signed financial transactions into fake successful responses.
- Unauthenticated sessions may be re-created by attackers; session deception is not an identity guarantee.
- HTTP request routing can change between requests; established TCP/TLS streams cannot be safely moved to a different backend without protocol-specific handling.
- For WebSocket, SSE and streaming MCP, reject or close on restriction until a protocol-aware adapter exists.
- Production data disclosed before detection remains disclosed; incident response is still required.
- No reliable claim that a caller is an AI model, a particular vendor or a malicious human based on text style alone.

## 6. Privileged changes

Policy activation, permission signing, adding a backend and enabling deception require an authorized administrator, a versioned change and audit trail. The investigator may propose but cannot execute these changes. A preapproved deterministic rule may restrict a session without human approval; it cannot broaden permissions.

Registry signing keys and runtime authorization DB credentials must never be available to the decoy, investigator or agent. Grant mutation uses separate credentials and audited signer tooling. Permissions derived from Hades findings remain proposals until reviewed.

## 7. Evidence and privacy

Default capture uses metadata, redacted argument summaries, hashes and bounded snippets. Do not log full Authorization headers, cookies, private keys or real financial details. Diagnostic payload capture is separately enabled, encrypted, access controlled and short-lived. Raw evidence access is audited. Deletion and retention must follow the approved pilot policy; local fixtures use synthetic data.

Evidence authenticity means a record can be traced to an authenticated producer, not that attacker-supplied content is true. Store observation, inference and confirmed outcome separately. Hash chains detect certain alterations but are not tamper-proof without protected anchoring and storage controls.

## 8. Release blockers

Any decoy-to-production route, forged identity acceptance, cross-tenant access, approval replay success, direct backend bypass, model ability to grant access, or production request after the enforced route barrier blocks release. Unknown isolation status means no engagement. Undocumented security failures are not acceptable demo shortcuts.
