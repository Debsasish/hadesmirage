# Operations, incident response and recovery

## 1. Health and observability

Monitor ingress error rate, authorization latency, denied action counts, direct-origin rejection, event ingestion lag, dead letters, route CAS conflicts, decoy readiness, isolation status, engagement concurrency, inference usage, model validation failures and cleanup backlog. Metrics use low-cardinality labels; event IDs and raw payloads remain in access-controlled evidence.

Each case shows source trust labels, matched rule version, evidence refs, route state history, production/decoy outcomes, analyst actions and model uncertainty. AI prose never replaces raw decision records.

## 2. Failure matrix

| Failure | Behaviour | Operator action |
| --- | --- | --- |
| Model timeout/provider outage | Rules continue; static decoy response; explanation unavailable | Inspect budget/provider and retry boundedly |
| Policy unavailable | Deny protected operation | Restore signed/versioned policy; never emergency allow-all |
| Route store unavailable | Reject ambiguous protected dispatch | Restore store and reconcile session states |
| Decoy provisioning/isolation failure | Remain restricted/deny | Quarantine runtime; inspect network and readiness |
| Event queue delayed | Buffer durably to limit; stop sensitive work at threshold | Drain queue and verify evidence completeness |
| Gateway registry unavailable | Deny new authorization | Restore DB; inspect existing tunnels separately |
| Budget exceeded | Stop engagement, preserve permitted evidence | Adjust reviewed limits or keep blocked |
| Suspected signer compromise | Suspend grant issuance and affected identities | Rotate/revoke keys, close sessions, review historical grants |

## 3. Incident playbooks

### Suspected external probing

Verify rule/evidence and session binding → confirm prohibited requests were denied → check deception eligibility → observe restricted/decoy state → review behaviour → terminate on completion/limits → export case. If production was accessed before restriction, initiate ordinary incident response; do not label the case contained solely because a decoy became active.

### Compromised internal agent

Suspend identity/tool grants → enforce dispatcher denies → revoke destination permissions → close supported existing tunnels → preserve evidence → identify affected assets and last known good state → rotate compromised credentials → restore only through fresh identity and reviewed policy. Default does not silently deceive employee workloads.

### False-positive diversion

Stop engagement → preserve case and analyst label → verify legitimacy via normal identity process → issue a new clean session with fresh scope → tune rule through reviewed version change. Never migrate synthetic state or fake action results back into production.

### Isolation failure

Disable new engagements → restrict existing sessions → terminate affected decoys → sever connectivity at infrastructure boundary → investigate production/control exposure → rebuild from reviewed immutable template → rerun isolation matrix. Treat this as a control incident, not merely a decoy error.

## 4. Kill switch

Separate controls: disable new engagement, terminate active engagements, suspend selected workload, revoke grants and block affected ingress. All are role-gated, idempotent and audited. Global engagement disable must not disable authorization. Test kill switch with in-flight requests and unavailable model. If management API is down, infrastructure-level blocking must remain available through authorized operators.

## 5. Backup and recovery

Back up policies, approval/execution state, incidents and audit metadata according to profile. Do not restore stale active approvals or expired permissions as usable. After DB recovery reconcile pending executions with backends before retrying mutations. Reconcile route state to restricted on uncertainty; dispose of unreconciled decoys. Signing keys are recovered separately under approved procedures, never from application DB dumps.

## 6. Retention and access

Raw payload capture is off by default. Analysts see redacted evidence. Approvers see exact action arguments only where authorized. All raw evidence access and exports are logged. Apply tenant-scoped retention jobs and verify deletion. Demonstration reset purges only synthetic datasets, never arbitrary filesystem paths or existing user files.

## 7. Pilot rollout

Stage 1 offline replay → stage 2 shadow detection with no automated diversion → stage 3 deterministic internal denials on one low-impact app → stage 4 external deception on selected nontransactional endpoints → stage 5 expansion after observed false-positive/isolation results. Rollback disables engagement and reverts to a reviewed authorization policy; it never removes the enforcement boundary.
