# ADR 0001 — Separate analysis, authorization and deception authority

Status: accepted for blueprint v1.0. Date: 17 October 2026.

## Context

Hades-Blackwatch is a security-review skill foundation. The supplied Rust gateway authorizes destination connections using certificate/key-bound signed permissions. Neither alone provides per-tool authorization, continuous SOC correlation or inbound session diversion. A model can be manipulated by the very evidence it is investigating.

## Decision

Use distinct logical components for investigation, deterministic authorization, connection enforcement, session routing and decoy orchestration. Models receive bounded data and cannot grant production access. Keep native gateway TLS verification on a suitable endpoint. Use an application-aware ingress/dispatcher for tool/data/route checks. Restrict production access before activating a decoy. Decoy runtime receives synthetic state only and no production credentials or outbound privileges.

## Consequences

More integration work and separate test profiles are required. There is no single 'AI firewall' component that can be assumed to enforce every layer. The separation makes decisions auditable and limits model/deception compromise. Cloud Run hosts the application demonstration, not an unchanged claim of native gateway mTLS semantics.

## Alternatives rejected

Model decides allow/deny directly: vulnerable to injected evidence and unbounded authority. Network allowlist alone: cannot distinguish legitimate reads from destructive operations on the same service. Generate and run vulnerable apps on demand: difficult to bound and unnecessary for MVP. Redirect all strange requests: harms legitimate users and conflates anomaly with malice.
