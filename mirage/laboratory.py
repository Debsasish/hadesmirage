from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update

from mirage import db, deception, providers
from mirage.auth import PrincipalContext, fixture_context
from mirage.common import DomainError, after, now, uid
from mirage.models import DelegationRequest, Invocation, PortalRequest, ScenarioRequest

if TYPE_CHECKING:
    from mirage.service import Service

SCENARIOS = [
    {
        "id": "legitimate-lookup",
        "title": "Legitimate supplier lookup",
        "description": "Execute a scoped read and verify the independent backend ledger.",
        "test_ids": ["T-02"],
    },
    {
        "id": "blocked-payment",
        "title": "Unapproved payment change",
        "description": "Deny execution, create an exact review request, and confirm zero mutations.",
        "test_ids": ["T-03", "T-28"],
    },
    {
        "id": "external-probing",
        "title": "Corroborated external probing",
        "description": "Deny a prohibited tool and three resource probes, then route only to the isolated decoy.",
        "test_ids": ["T-11", "T-13"],
    },
    {
        "id": "benign-quotation",
        "title": "Benign quoted instruction",
        "description": "Quoted injection-like text without a prohibited action must not divert.",
        "test_ids": ["T-23"],
    },
    {
        "id": "delegation-escalation",
        "title": "Subagent scope escalation",
        "description": "Reject a child grant that exceeds its parent's authority.",
        "test_ids": ["T-07"],
    },
    {
        "id": "approved-payment",
        "title": "Execute a reviewed synthetic change",
        "description": "Requires an exact approved request from a separate reviewer. Changes synthetic backend data.",
        "test_ids": ["T-05"],
    },
    {
        "id": "approval-substitution",
        "title": "Substitute approval arguments",
        "description": "Attempt a changed account reference; the digest check must deny.",
        "test_ids": ["T-05"],
    },
    {
        "id": "model-outage",
        "title": "Investigator outage",
        "description": "Inject a bounded model outage; enforcement and static deception continue.",
        "test_ids": ["T-22"],
    },
    {
        "id": "decoy-outage",
        "title": "Decoy readiness failure",
        "description": "Inject local readiness failure; production must remain restricted.",
        "test_ids": ["T-22"],
    },
    {
        "id": "kill-switch",
        "title": "Engagement kill switch",
        "description": "Terminate all active tenant decoys, purge synthetic state, and never restore production.",
        "test_ids": ["T-24"],
    },
]


def procurement_operation(session_id: str, payment: bool = False) -> Invocation:
    return Invocation(
        tool="payment.change_request" if payment else "supplier.lookup",
        action="propose_change" if payment else "read",
        resource="supplier:demo-001",
        arguments={
            "supplier_id": "demo-001",
            **({"proposed_account_ref": "synthetic-account-reviewed"} if payment else {}),
        },
        session_id=session_id,
    )


def external_sequence(
    service: Service, context: PrincipalContext
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    session = service.create_session(context, origin="laboratory")
    outcomes: list[dict[str, Any]] = []
    for tool, resource in (
        ("customer.export", "customer:all"),
        ("supplier.lookup", "supplier:unassigned-101"),
        ("supplier.lookup", "supplier:unassigned-102"),
        ("supplier.lookup", "supplier:unassigned-103"),
        ("supplier.lookup", "supplier:demo-001"),
    ):
        status, response = deception.portal(
            service,
            context,
            PortalRequest(
                session_id=session["id"],
                tool=tool,
                resource=resource,
            ),
            uid(),
        )
        service.drain_outbox()
        outcomes.append({"http_status": status, "response": response, "tool": tool})
    return session, outcomes


def run(
    service: Service, context: PrincipalContext, request: ScenarioRequest, key: str
) -> dict[str, Any]:
    context.require("security_admin")
    if service.settings.profile not in {"P1-native", "P2-cloud"}:
        raise DomainError(
            403,
            "LABORATORY_DISABLED",
            "Synthetic scenarios run only in the native laboratory or the cloud demo",
        )
    route = "/laboratory/run"
    with service.db.transaction() as connection:
        previous = service.idempotent_get(connection, context, route, key, request.model_dump())
        if previous is not None:
            return previous
        service.idempotent_put(
            connection,
            context,
            route,
            key,
            request.model_dump(),
            {
                "status": "reserved",
                "scenario": request.scenario,
                "message": "Run already reserved; do not resubmit with a new key to reconcile it",
            },
        )
        agent = fixture_context(connection, "agent-procurement", context.tenant_id)
        external = fixture_context(connection, "external-lab", context.tenant_id)
    before = service.backend.snapshot(context.tenant_id)
    outputs: list[dict[str, Any]] = []
    session: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None
    if request.scenario in {"legitimate-lookup", "blocked-payment"}:
        session = service.create_session(agent, origin="laboratory")
        operation = procurement_operation(session["id"], request.scenario == "blocked-payment")
        status, value = service.invoke(agent, operation, uid())
        outputs.append({"http_status": status, "response": value})
        if request.scenario == "blocked-payment":
            approval = service.request_approval(
                agent, operation, uid(), requester=context.principal_id
            )
    elif request.scenario in {"approved-payment", "approval-substitution"}:
        if not request.approval_id:
            raise DomainError(
                422,
                "APPROVAL_ID_REQUIRED",
                "Select the exact pending or approved laboratory action",
            )
        with service.db.engine.connect() as connection:
            approval = service.required(
                connection, db.approvals, context.tenant_id, request.approval_id
            )
            session = service.required(
                connection, db.sessions, context.tenant_id, approval["session_id"]
            )
        if session["origin"] != "laboratory" or approval["principal_id"] != agent.principal_id:
            raise DomainError(
                403, "NON_LAB_ACTION_DENIED", "This runner executes laboratory fixture actions only"
            )
        operation = Invocation.model_validate(
            {**approval["invocation"], "approval_id": approval["id"]}
        )
        if request.scenario == "approval-substitution":
            operation = operation.model_copy(
                update={
                    "arguments": operation.arguments.model_copy(
                        update={
                            "proposed_account_ref": "synthetic-account-substituted",
                        }
                    )
                }
            )
        status, value = service.invoke(agent, operation, uid())
        outputs.append({"http_status": status, "response": value})
    elif request.scenario == "benign-quotation":
        session = service.create_session(external, origin="laboratory")
        status, value = deception.portal(
            service,
            external,
            PortalRequest(
                session_id=session["id"],
                snippet='Training quotation: "ignore previous instructions" is untrusted text.',
            ),
            uid(),
        )
        outputs.append({"http_status": status, "response": value})
    elif request.scenario == "delegation-escalation":
        status, value = service.delegate(
            agent,
            DelegationRequest(
                child_id="agent-lab-overbroad-" + uid()[:8],
                name="Overbroad child fixture",
                scopes=[
                    {"tool": "customer.export", "action": "export", "resources": ["customer:all"]}
                ],
                expires_at=after(300),
            ),
            uid(),
            origin="laboratory",
        )
        with service.db.engine.connect() as connection:
            session = service.required(
                connection, db.sessions, context.tenant_id, value["session_id"]
            )
        outputs.append({"http_status": status, "response": value})
    elif request.scenario == "decoy-outage":
        previous_ready = service.sandbox.ready
        try:
            service.sandbox.ready = False
            session, outputs = external_sequence(service, external)
        finally:
            service.sandbox.ready = previous_ready
    else:
        session, outputs = external_sequence(service, external)
    service.drain_outbox()
    with service.db.engine.connect() as connection:
        session = service.required(connection, db.sessions, context.tenant_id, session["id"])
        case = (
            connection.execute(
                select(db.incidents).where(
                    db.incidents.c.tenant_id == context.tenant_id,
                    db.incidents.c.session_id == session["id"],
                )
            )
            .mappings()
            .first()
        )
    if request.scenario == "model-outage" and case:
        try:
            providers.investigate(service, context, case["id"], providers.UnavailableProvider())
        except DomainError as error:
            outputs.append(
                {
                    "http_status": error.status,
                    "response": {"code": error.code, "enforcement_relaxed": False},
                }
            )
    if request.scenario == "kill-switch":
        outputs.append(
            {"http_status": 200, "response": deception.kill_switch(service, context, uid())}
        )
        service.drain_outbox()
        with service.db.engine.connect() as connection:
            session = service.required(connection, db.sessions, context.tenant_id, session["id"])
    backend_after = service.backend.snapshot(context.tenant_id)
    result = {
        "status": "completed",
        "scenario": request.scenario,
        "profile": service.settings.profile,
        "origin": "laboratory",
        "session": session,
        "outcomes": outputs,
        "approval": approval,
        "incident_id": case["id"] if case else None,
        "backend_effect_delta": {
            "production_reads": backend_after["production_reads"] - before["production_reads"],
            "production_mutations": backend_after["production_mutations"]
            - before["production_mutations"],
        },
        "evidence_source": backend_after["evidence_source"],
        "completed_at": now(),
        "fault_injection": request.scenario in {"model-outage", "decoy-outage"},
    }
    with service.db.transaction() as connection:
        connection.execute(
            update(db.idempotency)
            .where(
                db.idempotency.c.tenant_id == context.tenant_id,
                db.idempotency.c.principal_id == context.principal_id,
                db.idempotency.c.route == route,
                db.idempotency.c.key == key,
            )
            .values(response=result)
        )
        service.audit(
            connection,
            context,
            "laboratory.completed",
            session["id"],
            {
                "scenario": request.scenario,
                "backend_effect_delta": result["backend_effect_delta"],
            },
        )
    return result
