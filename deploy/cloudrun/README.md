# Cloud Run application demonstration: preparation, not deployment

> **Update:** an executable, IAP-protected Cloud Run demo procedure (profile `P2-cloud`, buildpacks source deploy, no Docker) now lives in [`deploy/gcp/README.md`](../gcp/README.md). It addresses items 1 (IAP-verified Workspace identity, fixture login disabled), 3 (buildpacks, no Docker) and 5 (Vertex AI through the service account) for a single-instance synthetic demo. Items 2 (PostgreSQL runtime validation), 4, 6, 7 and the P3 note below still apply, and that procedure has not been deployed or verified in a live project.

No Google Cloud resource was created, no service was published and no spend was authorized during implementation. The current validated application is P1-native. A `P2-prepared` setting is not proof that a secure Cloud Run deployment exists.

Before preparing executable deployment infrastructure:

1. Replace local fixture login/bootstrap with approved issuer/audience-verified identity and tenant onboarding. Disable fixture seeding and local login outside the laboratory.
2. Provision and test PostgreSQL authoritative state, backups, shared dispatch fencing and least-privilege application credentials.
3. Package API, worker/model broker and fixed synthetic backend for the managed platform, using approved source build tooling if local Docker is prohibited. Do not carry `.local`, test credentials, Git history or provider keys into build context.
4. Keep the decoy module's zero-import capability boundary. If a network-attached decoy is added, separately prove its IAM, metadata, network and origin isolation before eligibility.
5. Give only the model broker/investigator approved Vertex model access. Configure an available model, explicit time/token/call budgets and region; validate real citations and failures.
6. Restrict backend origins to the dispatcher identity. Verify alternate/default hostnames, management authentication and actual cloud paths.
7. Run P2 identity, tenancy, availability, origin, retention and cost gates before changing dashboard claims.

The native gateway must not be deployed unchanged behind ordinary Cloud Run TLS termination and represented as preserving client-certificate proof. Host P3 on a compatible TLS-preserving endpoint, such as a controlled VM, and test the complete path.

An attractive but unverified public manifest would weaken the blueprint's boundary. This directory intentionally records the required design work instead of providing an insecure auto-deploy shortcut.
