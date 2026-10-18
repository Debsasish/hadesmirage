# Integration specification

## 1. Reviewed baseline

Hades-Blackwatch README describes a Codex skill with specialist roles, review modes, scanner ingest, scripts and reporting. The inspected MCP manifest auditor classifies risk using keywords and sensitive parameter names. It is not a running continuous SOC, an authenticated authorization service or a verified exploit detector.

The uploaded agent-gateway README and Rust proxy source describe HTTP/2 CONNECT with mTLS and authorization against a signed PostgreSQL registry. Proxy code evaluates policy, opens a destination TCP connection and copies bytes bidirectionally. It does not parse MCP operations or inspect the destination TLS payload. The ZIP also includes a Python teaching evaluator with P-256 certificates and SQLite; it must not be presented as the real Rust network proxy.

These are selected-file observations, not a full repository audit or runtime verification.

## 2. Hades adapter

Proposed module: `adapters/hades.py`.

Inputs: controlled application source/configuration, tool manifests and imported findings. Allowed initial scripts: surface mapper, manifest auditor, finding normalizer and report generator, after pinned-source review. Do not execute scripts from untrusted scanner output or accept arbitrary file paths from external callers.

Outputs: normalized observations with source, source_version, evidence references, tool name, confidence and recommended review action. Store raw scanner text as untrusted evidence with size limits.

Example flow: manifest audit flags `customer.export` → create onboarding observation → engineer reviews actual handler/auth checks → propose a restrictive policy → approval workflow activates version → regression verifies denial. A keyword finding alone cannot authorize or revoke production permissions.

The specialist role files describe workflows. A running service requires orchestration code, scoped model access, timeouts and validated outputs. Start with one bounded investigator rather than instantiate every documented specialist.

## 3. Gateway adapter

Proposed module: `adapters/gateway.py`.

Keep gateway registry migrations and signature verification authoritative. A product-side service may propose grants, but grants are signed only through separate authorized tooling. Runtime gateway DB role is read-only for authorization tables. Product read models should not repurpose gateway tables or invent signatures.

Required mapping: product workload identity → certificate extension identity plus exact leaf public key → normalized destination → active signed permission. Product tool names map to service destinations on the server; external callers cannot pick the mapping.

Required real tests: valid grant, unknown identity, wrong key, absent destination, expired permission, revoked signer, insufficient signer delegation, direct egress bypass and established tunnel after revocation.

Log adapter captures structured timestamp, identity, normalized destination, allow/deny, reason and optional trace context. Hash high-cardinality identifiers before external analytics. A caller-supplied trace ID links observations only; it grants no authority and is never the sole trust key.

## 4. Immediate revocation gap

The inspected proxy checks policy before creating a tunnel. Do not claim it reauthorizes every byte. Add a connection registry and termination API/manager if immediate close is required; restrict access to it. Product tool dispatcher still rechecks per operation. Expiring or revoking a grant and closing an established session are different operations.

## 5. Inbound/application integration

Build a reverse proxy or application middleware for known routes. It authenticates/derives session context, consults route state and dispatches to fixed upstreams. It strips inbound routing, principal and internal authentication headers. Production credentials are never forwarded to a decoy.

For HTTP MCP, the adapter must understand protocol lifecycle, tool listing/calling and resource access before claiming compatibility. Token audience validation and separate upstream credentials are mandatory. Do not pass a client's bearer token through as universal backend authorization. Streaming handling is deferred until tested.

## 6. Provider/model integration

Use an interface `investigate(case)` and `render_decoy(template_context)` with schema validation. Implement deterministic fixture provider first and Gemini provider second. Model ID, region and budget are configuration; select an available supported model during implementation and pin deployment settings. No version, throughput or cost is assumed by this blueprint.

Use workload credentials for provider access, not embedded API secrets. The decoy runtime has no provider identity. Provider failure returns a static template response or unavailable summary without relaxing access controls.

## 7. Provenance and licenses

Pin commits and dependency versions before implementation. Uploaded gateway README references `securitylevel5/agent-gateway-demo` and the gateway MIT license; record original authors and notices. Hades README displays Apache 2.0; verify the actual license file before redistribution. This pack does not copy either project's source. New integration work needs explicit ownership and third-party disclosure.
