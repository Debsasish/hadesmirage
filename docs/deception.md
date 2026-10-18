# Adaptive AI honeypot design

## 1. MVP choice

Use a low-interaction, prestarted supplier-service simulation with isolated session state. 'Creates a honeypot' initially means reserves a ready template instance and creates a session-specific synthetic namespace. It does not mean the model writes and executes a new vulnerable application during an attack.

Later provisioning can create fresh containers from signed, reviewed templates. Dynamic arbitrary AI-generated code is excluded.

## 2. Template anatomy

Each template declares template ID/version, protocol, allowed fake routes/tools, state schema, seed generator, response schema, persona vocabulary, request budget, TTL and resource limits. Only allowlisted template IDs are accepted; no user-supplied image, executable path or URL.

The supplier template includes fictional organization names, fake suppliers and invoices, a fake administrator tool catalogue, nonfunctional credential-shaped strings and simulated action history. All identifiers are isolated from real production identifiers. Synthetic account data cannot be submitted to real banking systems.

## 3. Response generation

1. Parse and bound the inbound request; remove live authentication material.
2. Select a deterministic emulated operation from the template catalogue.
3. Apply a safe synthetic state transition, if any.
4. Request optional wording from a control-plane model broker using only synthetic state and sanitized input.
5. Validate generated text/schema, remove external links and enforce length/format limits.
6. Return protocol-consistent response; on failure use a static response from the same template.
7. Capture input/output hashes, bounded redacted snippets and synthetic operation outcomes.

The model never executes the attacker's commands, accesses a filesystem or chooses a real destination. Fake tool success remains a simulated result. The investigator and dashboard label it accordingly.

## 4. Isolation topology

Inbound edge → decoy router → decoy emulator. Responses travel back on the established inbound connection. Collector runs outside the decoy runtime and records proxy observations/stdout through platform logging; no decoy egress is required for telemetry.

Decoy model broker is outside this runtime. Orchestrator reads synthetic state and uses an approved provider; the emulator does not receive provider credentials. Network and IAM tests must verify this boundary, not infer it from a diagram.

Local Compose is a convenience demonstration only. Hardened profile uses separate cluster/project/VPC as appropriate, deny-by-default networking, blocked metadata access, resource constraints, no service-account token mounts, no privileged containers and no host mounts. An enforcing CNI or equivalent firewall is mandatory.

## 5. Lifecycle

`AVAILABLE → RESERVED → VERIFIED → ACTIVE → DRAINING → DESTROYED`.

Reservation is scoped to tenant/session and idempotent. VERIFIED requires successful isolation/readiness checks for the active template/version. Failures go to a quarantined unavailable state and cannot serve sessions. Active engagement expires after the configured TTL, request limit or budget. Initial defaults: 15 minutes, 100 requests, 8,000 total model output tokens and 10 concurrent sessions per demo deployment; configurable and enforced globally as well as per tenant.

Destroy deletes synthetic state and disposable runtime. Preserve only evidence allowed by retention policy. A watchdog handles abandoned reservations and repeated cleanup failures. Do not recycle a runtime across sessions until reset and isolation checks pass.

## 6. Decoy consistency

Stable seeded records per session, monotonic fake action history, consistent supplier IDs and deterministic tool definitions. Repeated reads return consistent data. Each session gets separate state; caching must include tenant, session and template version. The goal is believable bounded emulation, not indefinite indistinguishability from production.

## 7. Stop conditions

Immediate stop/restriction if isolation probe fails, production credential appears, model or compute budget is exceeded, the protocol leaves supported scope, output validation repeatedly fails, analyst triggers kill switch or telemetry integrity is lost. Stop does not restore production routing.

## 8. Realistic limitations

An attacker may detect the decoy, leave or create another session. Deception does not replace authorization or denial. No guarantee an attack will remain engaged. Unsupported exploit payloads are logged as bounded text and rejected, not executed to learn more. Collect only observations from owned/authorized systems.
