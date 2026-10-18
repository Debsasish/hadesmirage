# Source register and provenance

Prepared 17 October 2026. These sources informed architecture decisions; they are not evidence that the proposed product has been implemented or independently assessed.

## Reviewed project artifacts

- Hades-Blackwatch: https://github.com/DebasishTripathy13/Hades-Blackwatch
- Reviewed README blob SHA: `6dca36193efecf5ffa8ecccf2c9a059e4f016dfb`.
- Reviewed `scripts/mcp_manifest_audit.py` blob SHA: `aed637957cbb1b669a3e4e9d990ef90bb84b755e`.
- README describes review roles, report generation and scanner integration; inspected auditor uses keyword/schema heuristics. No full-source or runtime audit was performed for this blueprint.
- Supplied `agent-gateway.zip`: reviewed `README.md`, `src/proxy.rs` and `python_demo/README.md`, plus archive inventory. Source shows a CONNECT authorization boundary and bidirectional TCP tunnel; Python README explicitly describes a teaching evaluator. Full archive SHA-256 is recorded in package metadata.
- User-supplied event brief: `Pasted text(20261017-142425).txt`; includes both hackathon descriptions and CyberForge originality rules.

## Official references checked for design

1. Cloud Run HTTP/2: https://docs.cloud.google.com/run/docs/configuring/http2
   - TLS terminates at the frontend; configured HTTP/2 applications receive h2c. This motivates a separate native gateway endpoint.
2. Kubernetes Network Policies: https://kubernetes.io/docs/concepts/services-networking/network-policies/
   - Default-deny networking and plugin enforcement; inspect documented scope/limitations when implementing.
3. MCP authorization (explicit version reference): https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
   - Resource-scoped authorization and audience validation. Verify chosen SDK/spec compatibility before implementing.
4. MITRE Engage: https://www.mitre.org/news-insights/impact-story/mitre-engage-framework-and-community-cyber-deception
5. MITRE engagement guide: https://engage.mitre.org/wp-content/uploads/2022/04/EngageHandbook-v1.0.pdf
   - Deception/adversary engagement and controlled engagement environments are established concepts; no claim of inventing honeypots.
6. AI Builder Cup themes/requirements: https://aibuildercup.com/themes.html
7. AI Builder Cup overview: https://aibuildercup.com/
   - Public deployment/theme information; authenticated dashboard updates and current organizer rules may differ.

## Interpretation boundaries

Recommendations about component boundaries, warm decoys, scope intersection, routing barriers and test targets are this project's engineering design. They are not quotations or certifications from the sources. Model availability, SDK APIs, cloud services and competition rules can change; validate during implementation and submission. License declarations in READMEs require checking authoritative license files before reuse.
