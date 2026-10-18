# Example fixtures

All records, accounts and identities are synthetic. Files illustrate contracts and tests; they do not enforce anything by themselves.

| Fixture | Schema/purpose |
| --- | --- |
| [event.json](event.json) | [Event schema](../contracts/event.schema.json); one denied operation |
| [tool-invocation.json](tool-invocation.json) | [Invocation schema](../contracts/tool-invocation.schema.json); ordinary allowed read request |
| [decision.json](decision.json) | [Decision schema](../contracts/decision.schema.json); denial fixture, separate from the allowed-read request |
| [investigation.json](investigation.json) | [Investigation schema](../contracts/investigation.schema.json); cites the event and does not infer malice from one denial |
| [policy.json](policy.json) | [Policy schema](../contracts/policy.schema.json); illustrative rules only |
| [route-transition.json](route-transition.json) | [Transition schema](../contracts/route-transition.schema.json); request shape only, not sufficient evidence to engage |
| [decoy-template.json](decoy-template.json) | Proposed template configuration and limits |
| [scenarios.json](scenarios.json) | Behaviour specifications; not executed test results |

The transition fixture references the available example event to demonstrate linkage. That single event does not satisfy D-002; an implementation must reject engagement unless all required corroborating evidence and eligibility checks exist. The validator verifies references and schemas, not detection eligibility.

Policy resource_prefix matching is a simplified fixture language. Effective identity/tenant scope, approval semantics, current route state and backend checks are still mandatory. Per-tool argument constraints must be implemented in typed handlers. The generic request schema cannot verify every tool/action/resource combination.

No example file contains certificate private keys, signed grants, live credentials or real customer data. Provider keys and production endpoint URLs must never be added here.
