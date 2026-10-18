# Reproducible local demonstration

Start with `setup.cmd`, then `start.cmd`. Open the printed loopback URL and use the generated local code. This is a synthetic P1-native demonstration, not a public deployment.

1. **Normal work:** as admin, Overview → Run lab scenario → Legitimate supplier lookup. Show the actual backend-read delta, then Audit & reports → Backend ledger.
2. **Prevent a prohibited mutation:** run Unapproved payment change. The outcome is approval-required and the backend mutation delta is zero. Open its exact approval.
3. **Separate review:** sign out and sign in as approver. Review the identity, resource, synthetic account reference, expiry, policy version and full request digest. Approve one execution with explicit confirmation.
4. **Execute once:** sign back in as admin. In the approval queue, execute the reviewed laboratory action. The backend mutation counter advances once; replay and altered arguments do not authorize another effect.
5. **Bound child authority:** run Subagent scope escalation. Show the denied issuance and D-004 case; no broad child token is issued.
6. **Restrict and observe:** run Corroborated external probing. The first four requests are denied; the next supported read goes to the Wasm decoy. Open the case and show PRODUCTION → RESTRICTED → DECOY_PENDING → DECOY, route versions, cited observations and the independent zero production-effect delta.
7. **Explain without granting:** generate an investigation. Fixture output is visibly deterministic; click an evidence reference. The model has no signer, router, shell or backend credential.
8. **Avoid a false inference:** run Benign quoted instruction. The normal read completes and no diversion occurs from the quoted phrase alone.
9. **Failure posture:** run Model outage and Decoy readiness failure. These are explicitly labeled local fault injections. Static emulation continues without AI; missing readiness leaves production restricted.
10. **Stop:** in Deception Centre, confirm the kill switch. Engagement state is purged, new engagement is disabled and terminated sessions never return to production.

The Architecture view distinguishes configured native edges from the proposed P3 gateway path. The Integrations view distinguishes an imported Hades report from a live scanner and fixture output from configured/unverified Gemini.

Exports include the active profile and limitations. The separate [verification report](implementation-results.md) records sample counts; the supplied engineering targets are not represented as measured production guarantees.
