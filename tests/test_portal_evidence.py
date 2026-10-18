from sqlalchemy import select

from mirage import control, db, deception
from mirage.common import uid
from mirage.models import PortalRequest


def test_authorized_portal_read_before_restriction_remains_visible_in_case_outcomes(lab):
    actor = lab.context("external-lab")
    session = lab.service.create_session(actor)
    allowed = deception.portal(lab.service, actor, PortalRequest(session_id=session["id"]), uid())
    assert allowed[0] == 200 and allowed[1]["execution_state"] == "succeeded"
    for tool, resource in (
        ("customer.export", "customer:all"),
        ("supplier.lookup", "supplier:unknown-1"),
        ("supplier.lookup", "supplier:unknown-2"),
        ("supplier.lookup", "supplier:unknown-3"),
    ):
        deception.portal(
            lab.service,
            actor,
            PortalRequest(session_id=session["id"], tool=tool, resource=resource),
            uid(),
        )
        lab.service.drain_outbox()
    with lab.service.db.engine.connect() as connection:
        case = (
            connection.execute(
                select(db.incidents).where(
                    db.incidents.c.tenant_id == actor.tenant_id,
                    db.incidents.c.session_id == session["id"],
                )
            )
            .mappings()
            .one()
        )
    detail = control.case_detail(lab.service, lab.context("analyst"), case["id"])
    assert len(detail["backend_outcomes"]) == 1
    assert detail["backend_outcomes"][0]["id"] == allowed[1]["execution_id"]
    assert detail["session"]["route_mode"] == "DECOY"
    assert lab.backend.snapshot("tenant-demo")["production_reads"] == 1
