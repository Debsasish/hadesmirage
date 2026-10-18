# Native gateway P3 integration gate

The supplied archive is reviewed input, not a bundled runtime. Its SHA and selected-file scope are in [source attribution](../../docs/implementation-attribution.md). The implementation never extracts uploaded `.git`, private settings or credentials.

Prerequisites for P3: original reviewed Rust source and toolchain, compatible native TLS endpoint, isolated PostgreSQL authorization registry, upstream migration, test-only PKI/signer, workload egress fencing and a separately restricted management identity.

Run the original gateway's native build/tests in that authorized environment. Verify certificate proof, exact leaf-key binding, destination normalization, permission/signing-key expiry and revocation, signer delegation, allowed and denied connections, direct bypass prevention and established-tunnel behavior.

Mirage's `POST /v1/integrations/gateway/observations` accepts a narrow typed subset of structured `agent_gateway::proxy` observations from the source-bound gateway producer. A normalized record contains `timestamp`, `target`, `session_id`, and `fields` with `source_identity`, `dest_authority`, `policy_decision`, and optional `deny_reason`. It is telemetry only: no signing, registry write, route instruction or permission grant.

Registry revocation does not imply an established opaque tunnel closes. Do not claim immediate network containment until a real connection manager and actual socket tests establish it. The P1 dispatcher still rechecks application authorization independently.
