# Demonstration and hackathon narrative

## 1. Product pitch

Hades Mirage keeps internal AI agents within explicit permissions and diverts eligible suspicious external sessions into isolated synthetic services. Its SOC agent correlates behaviour, explains evidence and reports what the enforcement layer actually did.

## 2. Three-minute demonstration

| Time | On-screen action | Evidence |
| --- | --- | --- |
| 0:00–0:20 | Explain two risks: overpowered internal agent and external probing | Architecture and active profile labels |
| 0:20–0:50 | Internal procurement agent looks up an allowed supplier | Authorized backend hit and decision |
| 0:50–1:15 | Same agent attempts unapproved payment change/unrelated export | Deny/approval required and unchanged backend counter |
| 1:15–1:55 | Laboratory external client performs a corroborated prohibited sequence | Rule matches, restriction and route transition |
| 1:55–2:25 | Client continues in decoy; reads fake supplier records and simulated tool results | Decoy hit count, synthetic state and no new production hit |
| 2:25–2:50 | Analyst opens incident timeline and AI explanation | Referenced evidence, limits and response outcome |
| 2:50–3:00 | Terminate engagement and show isolation/test results | Kill switch and measured summary |

Use a scripted client labelled as a laboratory attack simulation; do not imply a fixture transcript was captured from a real attacker. If gateway runs separately, show real certificate-bound connectivity outcomes in a distinct panel.

## 3. What AI adds

Correlating and explaining heterogeneous evidence, identifying alternative explanations and producing context-consistent decoy wording from fixed synthetic state. It does not make cryptographic decisions, grant permissions or perform arbitrary attacker operations. Demonstrate model outage to show enforcement remains intact.

## 4. Theme alignment

CyberForge: AI security, threat detection, assisted SOC and adaptive deception. Show functional containment and evidence, not only a dashboard.

AI Builder Cup: Future of Work & Enterprise Productivity. Show reduced investigation effort and controlled enterprise AI operation using Google AI and a deployed Cloud Run application. The native gateway can be separate compatible infrastructure; do not hide platform limitations.

## 5. Submission package to assemble after implementation

Working prototype URL with controlled demo access; architecture diagram; source repository; setup and test instructions; three-minute video; measured evaluation; dependency/provenance statement; implemented-vs-planned feature table; known limitations. No invented accuracy, incident counts or customer claims.

## 6. Originality and reuse

The supplied CyberForge rules require original work created specifically for that hackathon and prohibit pre-existing solutions. Existing Hades and gateway code must be disclosed. Do not assume a rebrand, new UI or integration automatically satisfies eligibility. Ask the organizer whether the proposed reuse/new-work boundary is allowed before representing it as eligible. This document does not send any message or establish approval.

The supplied Builder Cup dashboard and public pages have different team-formation dates; use the current authenticated dashboard/organizer clarification for deadlines. Official requirements and rules can change; verify before submitting. The blueprint schedule is not a deadline guarantee.

## 7. Claims to avoid

'Prevents all attacks'; 'knows which model attacked us'; 'unbreakable honeypot'; 'automatically detects every malicious agent'; 'Cloud Run preserves native gateway client TLS certificates'; 'model-generated policy is inherently safe'; 'a blocked attempt proves compromise'; 'a decoy success means the real operation succeeded'.
