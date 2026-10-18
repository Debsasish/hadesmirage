from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mirage.common import DomainError

Tool = Literal[
    "supplier.lookup",
    "invoice.compare",
    "payment.change_request",
    "customer.export",
    "infrastructure.delete",
]
Action = Literal["read", "analyze", "propose_change", "export", "delete"]
RouteMode = Literal["PRODUCTION", "RESTRICTED", "DECOY_PENDING", "DECOY", "TERMINATED"]
Source = Literal["edge", "dispatcher", "gateway", "decoy_router", "control"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Arguments(StrictModel):
    supplier_id: str | None = Field(default=None, min_length=1, max_length=200)
    invoice_id: str | None = Field(default=None, min_length=1, max_length=200)
    proposed_account_ref: str | None = Field(
        default=None, pattern=r"^synthetic-account-[a-z0-9-]{1,64}$"
    )


class Invocation(StrictModel):
    tool: Tool
    action: Action
    resource: str = Field(min_length=1, max_length=200, pattern=r"^[a-z]+:[a-zA-Z0-9_-]+$")
    arguments: Arguments
    session_id: str
    approval_id: str | None = None

    @field_validator("session_id", "approval_id")
    @classmethod
    def valid_uuid(cls, value: str | None) -> str | None:
        if value is not None:
            return str(UUID(value))
        return value

    @model_validator(mode="after")
    def typed_operation(self) -> Invocation:
        expected = {
            "supplier.lookup": ("read", "supplier"),
            "invoice.compare": ("analyze", "invoice"),
            "payment.change_request": ("propose_change", "supplier"),
            "customer.export": ("export", "customer"),
            "infrastructure.delete": ("delete", "infrastructure"),
        }
        action, kind = expected[self.tool]
        if self.action != action or self.resource.split(":")[0] != kind:
            raise ValueError("Tool, action and resource kind must match")
        args = self.arguments.model_dump(exclude_none=True)
        identifier = self.resource.split(":", 1)[1]
        needed: dict[str, str] = {}
        if self.tool in ("supplier.lookup", "payment.change_request"):
            needed["supplier_id"] = identifier
        if self.tool == "invoice.compare":
            needed["invoice_id"] = identifier
        if self.tool == "payment.change_request":
            if self.arguments.proposed_account_ref is None:
                raise ValueError("A synthetic account reference is required")
            needed["proposed_account_ref"] = self.arguments.proposed_account_ref
        if args != needed:
            raise ValueError("Arguments must exactly match the typed resource and operation")
        return self


class Scope(StrictModel):
    tool: Tool
    action: Action
    resources: list[str] = Field(min_length=1, max_length=20)

    @field_validator("resources")
    @classmethod
    def distinct(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Duplicate scope resource")
        return value


class PolicyRule(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    effect: Literal["allow", "deny"]
    principal_ids: list[str] = Field(min_length=1, max_length=20)
    tool: str = Field(min_length=1, max_length=100)
    actions: list[str] = Field(min_length=1, max_length=10)
    resource_prefix: str = Field(min_length=1, max_length=200)
    approval_required: bool


class Policy(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    policy_id: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=100)
    default_effect: Literal["deny"] = "deny"
    rules: list[PolicyRule] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_ids(self) -> Policy:
        if len({rule.id for rule in self.rules}) != len(self.rules):
            raise ValueError("Rule IDs must be unique")
        return self


class EventAttributes(StrictModel):
    tool: str | None = Field(default=None, min_length=1, max_length=200)
    action: str | None = Field(default=None, min_length=1, max_length=200)
    resource: str | None = Field(default=None, min_length=1, max_length=200)
    destination: str | None = Field(default=None, min_length=1, max_length=200)
    policy_version: str | None = Field(default=None, min_length=1, max_length=200)
    reason_code: str | None = Field(default=None, min_length=1, max_length=200)
    snippet: str | None = Field(default=None, max_length=2048)


class EventInput(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    event_id: str
    tenant_id: str = Field(min_length=1, max_length=200)
    session_id: str
    source: Source
    event_type: Literal[
        "request.observed",
        "authorization.decided",
        "tool.completed",
        "gateway.decided",
        "decoy.observed",
        "session.transitioned",
    ]
    occurred_at: str
    route_mode: RouteMode
    outcome: Literal[
        "observed", "allow", "deny", "require_approval", "success", "failure", "simulated"
    ]
    attributes: EventAttributes
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    trace_id: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("event_id", "session_id")
    @classmethod
    def valid_uuid(cls, value: str) -> str:
        return str(UUID(value))

    @field_validator("occurred_at")
    @classmethod
    def valid_time(cls, value: str) -> str:
        from datetime import datetime

        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Timestamp must include timezone")
        return value


class Claim(StrictModel):
    text: str = Field(min_length=1, max_length=1000)
    evidence_event_ids: list[str] = Field(min_length=1, max_length=20)

    @field_validator("evidence_event_ids")
    @classmethod
    def valid_references(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Duplicate evidence reference")
        return [str(UUID(item)) for item in value]


class CaseEvidence(StrictModel):
    case_id: str
    case_version: int = Field(ge=1)
    confidence: Literal["low", "medium", "high"]
    claims: list[Claim] = Field(min_length=1, max_length=10)

    def verify(self, case_id: str, version: int, event_ids: set[str]) -> None:
        if self.case_id != case_id or self.case_version != version:
            raise DomainError(502, "MODEL_CASE_MISMATCH", "Model cited a different case version")
        for claim in self.claims:
            if not set(claim.evidence_event_ids) <= event_ids:
                raise DomainError(502, "MODEL_EVIDENCE_INVALID", "Model cited unavailable evidence")


class Investigation(CaseEvidence):
    summary: str = Field(min_length=1, max_length=2000)
    alternative_explanations: list[str] = Field(max_length=5)
    recommended_response: Literal["monitor", "review", "restrict", "consider_deception"]

    @field_validator("alternative_explanations")
    @classmethod
    def bound_alternatives(cls, value: list[str]) -> list[str]:
        if any(len(item) > 500 for item in value):
            raise ValueError("Alternative explanation too long")
        return value


class CaseQuestion(StrictModel):
    question: str = Field(min_length=8, max_length=1000)
    expected_version: int = Field(ge=1)

    @field_validator("question")
    @classmethod
    def readable_question(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 8 or any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise ValueError("Enter a bounded, readable case question")
        return value


class CaseAnswer(CaseEvidence):
    answer: str = Field(min_length=1, max_length=2500)
    limitations: list[str] = Field(min_length=1, max_length=5)

    @field_validator("limitations")
    @classmethod
    def bounded_limitations(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 500 for item in value):
            raise ValueError("Limitations must be bounded and nonempty")
        return value


class ReportSummaryRequest(StrictModel):
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class ReportClaim(StrictModel):
    text: str = Field(min_length=1, max_length=1000)
    observation_refs: list[str] = Field(min_length=1, max_length=20)

    @field_validator("observation_refs")
    @classmethod
    def distinct_observations(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Duplicate observation reference")
        if any(not re.fullmatch(r"obs-[1-9][0-9]{0,2}", item) for item in value):
            raise ValueError("Invalid local observation reference")
        return value


class ReportSummary(StrictModel):
    report_id: str
    report_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    summary: str = Field(min_length=1, max_length=2000)
    claims: list[ReportClaim] = Field(min_length=1, max_length=10)
    review_questions: list[str] = Field(min_length=1, max_length=5)
    limitations: list[str] = Field(min_length=1, max_length=5)

    @field_validator("review_questions", "limitations")
    @classmethod
    def bounded_items(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 500 for item in value):
            raise ValueError("Review text must be bounded and nonempty")
        return value

    def verify(self, report_id: str, report_digest: str, refs: set[str]) -> None:
        if self.report_id != report_id or self.report_digest != report_digest:
            raise DomainError(502, "MODEL_REPORT_MISMATCH", "Model cited a different report")
        if any(not set(claim.observation_refs) <= refs for claim in self.claims):
            raise DomainError(502, "MODEL_EVIDENCE_INVALID", "Model cited unavailable observations")


class ProviderCheckRequest(StrictModel):
    allow_live: bool = False


class ProviderCheck(StrictModel):
    status: Literal["mirage-provider-check-v1"]


class SyntheticWording(StrictModel):
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def plain_wording(cls, value: str) -> str:
        value = value.strip()
        if not value or re.search(
            r"\b(?:[a-z][a-z0-9+.-]*://|www\.|mailto:)|[<>`]|[\x00-\x1f\x7f]", value, re.I
        ):
            raise ValueError("Synthetic wording must be bounded plain text without links or code")
        return value


class AIConfigUpdate(StrictModel):
    provider: Literal["fixture", "gemini", "unavailable"]
    project: str = Field(default="", max_length=30, pattern=r"^([a-z][a-z0-9-]{4,28}[a-z0-9])?$")
    location: str = Field(default="global", min_length=2, max_length=50, pattern=r"^[a-z0-9-]+$")
    model: str = Field(default="", max_length=120, pattern=r"^([A-Za-z0-9][A-Za-z0-9._-]*)?$")
    egress_approved: bool = False
    acknowledge_egress: bool = False
    auto_triage: bool = False
    decoy_wording: bool = False
    expected_version: int = Field(ge=0)

    @model_validator(mode="after")
    def complete(self) -> AIConfigUpdate:
        if self.provider == "gemini" and not self.model:
            raise ValueError("Gemini needs a model")
        if self.egress_approved and not self.acknowledge_egress:
            raise ValueError("Confirm that redacted case evidence may be sent to Gemini")
        return self


class WorkspaceQuestion(StrictModel):
    question: str = Field(min_length=3, max_length=1000)

    @field_validator("question")
    @classmethod
    def readable(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3 or any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise ValueError("Enter a bounded, readable question")
        return value


class WorkspaceReference(StrictModel):
    case_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=300)


class WorkspaceAnswer(StrictModel):
    answer: str = Field(min_length=1, max_length=3000)
    confidence: Literal["low", "medium", "high"]
    references: list[WorkspaceReference] = Field(max_length=8)
    limitations: list[str] = Field(min_length=1, max_length=5)

    @field_validator("limitations")
    @classmethod
    def bounded(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 500 for item in value):
            raise ValueError("Limitations must be bounded and nonempty")
        return value

    def verify(self, case_ids: set[str]) -> None:
        if any(item.case_id not in case_ids for item in self.references):
            raise DomainError(502, "MODEL_EVIDENCE_INVALID", "Model cited an unavailable issue")


class Login(StrictModel):
    username: Literal["analyst", "admin", "approver"]
    access_code: str = Field(min_length=1, max_length=200)


class ApprovalDecision(StrictModel):
    decision: Literal["approve", "reject"]
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class Transition(StrictModel):
    expected_route_version: int = Field(ge=1)
    reason_code: str = Field(min_length=1, max_length=200)
    evidence_event_ids: list[str] = Field(default_factory=list, max_length=20)
    template_id: Literal["supplier-portal-v1"] = "supplier-portal-v1"


class PortalRequest(StrictModel):
    session_id: str
    tool: Tool = "supplier.lookup"
    resource: str = Field(
        default="supplier:demo-001",
        min_length=1,
        max_length=200,
        pattern=r"^[a-z]+:[a-zA-Z0-9_-]+$",
    )
    snippet: str = Field(default="", max_length=2048)

    @field_validator("session_id")
    @classmethod
    def valid_uuid(cls, value: str) -> str:
        return str(UUID(value))


class DelegationRequest(StrictModel):
    child_id: str = Field(pattern=r"^agent-[a-z0-9-]{1,50}$")
    name: str = Field(min_length=1, max_length=100)
    scopes: list[Scope] = Field(min_length=1, max_length=10)
    expires_at: str


class NoteRequest(StrictModel):
    text: str = Field(min_length=1, max_length=2000)


class IncidentUpdate(StrictModel):
    status: Literal["open", "investigating", "resolved"]
    expected_version: int = Field(ge=1)


class ScenarioRequest(StrictModel):
    scenario: Literal[
        "legitimate-lookup",
        "blocked-payment",
        "external-probing",
        "benign-quotation",
        "delegation-escalation",
        "approved-payment",
        "approval-substitution",
        "model-outage",
        "decoy-outage",
        "kill-switch",
    ]
    approval_id: str | None = None


class PolicyTransition(StrictModel):
    action: Literal["test", "review", "activate", "rollback"]
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class SettingsUpdate(StrictModel):
    engagements_enabled: bool


class SimulationRequest(StrictModel):
    principal_id: str = Field(min_length=1, max_length=100)
    invocation: Invocation


class KillSwitchRequest(StrictModel):
    confirmation: Literal["TERMINATE ALL DECOY SESSIONS"]


class ImportedObservation(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    risk_tier: Literal["T0", "T1", "T2", "T3", "T4"]
    issues: list[str] = Field(max_length=20)

    @field_validator("issues")
    @classmethod
    def bound_issues(cls, value: list[str]) -> list[str]:
        if any(len(item) > 1000 for item in value):
            raise ValueError("Observation too long")
        return value


class HadesReport(StrictModel):
    source_version: str = Field(pattern=r"^[a-f0-9]{40}$")
    tool_count: int = Field(ge=0, le=100)
    tools: list[ImportedObservation] = Field(max_length=100)

    @model_validator(mode="after")
    def correct_count(self) -> HadesReport:
        if self.tool_count != len(self.tools):
            raise ValueError("Report count differs from its observations")
        return self


class IdentityStatus(StrictModel):
    status: Literal["active", "suspended"]


class PurgeCaseRequest(StrictModel):
    expected_version: int = Field(ge=1)
    confirmation: str = Field(min_length=1, max_length=100)
