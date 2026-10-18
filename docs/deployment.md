# Deployment profiles and boundary verification

## 1. Profile definitions

| Profile | What runs | Valid claims | Excluded claims |
| --- | --- | --- | --- |
| P0 offline replay | Fixtures, policy evaluation, static UI | Reproducible analysis and schema validation | Live protection, real gateway enforcement |
| P1 local integrated | Mock app, ingress, dispatcher, shared DB, isolated emulator, model broker | Real local HTTP authorization/diversion within tested paths | Hardened arbitrary-code containment or enterprise readiness |
| P2 Google Cloud application demo | Cloud Run UI/API, Gemini, shared managed state, isolated decoy backend | Deployed AI investigation and application routing after cloud checks | Unmodified native gateway mTLS termination inside Cloud Run |
| P3 gateway enforcement | Rust gateway on suitable VM/cluster TLS endpoint, registry, restricted workload egress | Certificate/key/destination enforcement and tested bypass prevention | Tool-level authorization without dispatcher |
| P4 enterprise pilot | Approved SSO/PKI, dedicated decoy infrastructure, SIEM integrations, operations | Only independently validated pilot scope | Universal SOC replacement |

Display active profile(s) in dashboard and report. A combined demonstration may run P2 application services and P3 gateway on separate infrastructure; tests must verify the actual path between them.

## 2. Why native gateway is separate

The inspected gateway expects to inspect client certificates from its own Rust TLS connection. Cloud Run's HTTP frontend terminates TLS and forwards application traffic, including h2c for configured HTTP/2. Therefore do not deploy the native gateway unchanged as a normal Cloud Run HTTP service and claim equivalent client-certificate proof. Use a suitable TLS-preserving endpoint on a controlled VM or Kubernetes deployment, and validate the entire network path.

The application/control plane and Gemini-backed demonstration can still use Cloud Run. Managed transport identity at that layer is distinct from native gateway mTLS.

## 3. Local implementation topology

Planned Compose services: edge, application, dispatcher, control-api/worker, PostgreSQL, decoy-router, decoy-emulator and optional gateway plus its registry. Use separate networks for protected backends, control plane and decoy runtime. Do not attach decoy to production/control networks. A narrow router connects to the emulator; a separate outbound model broker receives sanitized synthetic context.

Only edge and dashboard bind localhost ports by default. Never mount Docker socket into application services. Runtime images run non-root with read-only root filesystem, temporary scratch limits and no capabilities. Compose isolation is a development aid; verify host firewall/routing explicitly.

## 4. Google Cloud application demo steps

1. Select a dedicated project and approved region; enable needed services through authorized account.
2. Create separate service identities for API, worker, model broker and decoy service. Decoy gets no production data/secret permissions.
3. Build and scan application images; pin digests and dependencies.
4. Provision shared state and secrets; do not use local Cloud Run filesystem as authoritative session storage.
5. Deploy authenticated management API and dashboard. Keep demonstration ingress narrowly exposed and rate limited.
6. Deploy isolated decoy emulation with explicit ingress identity restrictions. Verify metadata, network and cloud IAM paths before using it for engagement.
7. Configure Gemini access only for the broker/investigator identity and enforce application budgets.
8. Configure origin access so public clients cannot bypass edge to call real tool services directly. Test every alternate hostname/default URL.
9. Run cloud-specific identity, routing, tenancy, rate-limit and isolation checks.
10. Record active profile and all excluded capabilities in demo output.

Cloud Run service accounts and network configuration require careful review; absence of application secrets alone is not isolation. Do not claim production decoy safety just because a service has a different name/project.

## 5. Kubernetes hardening reference

Separate namespaces are a minimum organizational boundary. Use an enforcing CNI, default-deny ingress/egress, explicit router ingress and no egress for the decoy emulator. Do not allow DNS by default if the emulator does not need it. Block metadata and node/host access with platform-specific controls; ordinary NetworkPolicy has known scope limits.

Dedicated node pools/clusters/projects and stronger sandbox runtimes are enterprise options depending on threat model. Disable service-account token automount, hostPID/hostIPC/hostNetwork, privileged containers, hostPath and runtime socket mounts. Apply pod security, seccomp, CPU/memory/PID limits and immutable image policy. Check the real deployment, not only manifests.

## 6. Environment configuration to implement

Use typed settings: environment/profile; issuer/audience; DB secret ref; active policy version; fixed upstream map; model project/region/model ID; session TTL; decoy template allowlist; engagement concurrency; inference budget; payload size; audit backpressure threshold; shutdown and restriction timeouts. Secrets are references, never committed values.

No deployment manifests in this blueprint are represented as tested. Build actual IaC only after choosing profile and validating provider constraints. This avoids giving an attractive but insecure deployment a false production-ready label.

## 7. Release checklist

No direct public origins; no model signer permissions; no decoy production route; no broadly privileged decoy service account; all P0 test IDs pass; shared state works across instances; rollback and kill switch tested; image/source/config versions recorded; cloud cost and rate limits active; operator can retrieve evidence without exposing credentials.
