from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Adjustment, ApprovalStep, ExceptionCase
from app.services.audit import write_audit


class ApprovalConflict(ValueError):
    pass


def required_roles(amount: Decimal) -> list[str]:
    settings = get_settings()
    if amount <= settings.approval_small_amount_threshold:
        return ["analyst"]
    if amount <= settings.approval_medium_amount_threshold:
        return ["manager"]
    return ["manager", "finance_director"]


def ensure_approval_steps(db: Session, adjustment: Adjustment) -> list[ApprovalStep]:
    steps = list(db.scalars(select(ApprovalStep).where(ApprovalStep.adjustment_id == adjustment.id)))
    if steps:
        return steps
    steps = [
        ApprovalStep(adjustment_id=adjustment.id, approver_role=role, decision="pending")
        for role in required_roles(adjustment.proposed_amount)
    ]
    db.add_all(steps)
    db.flush()
    return steps


def _ordered_steps(adjustment: Adjustment, steps: list[ApprovalStep]) -> list[ApprovalStep]:
    order = {role: index for index, role in enumerate(required_roles(adjustment.proposed_amount))}
    return sorted(steps, key=lambda step: order.get(step.approver_role, len(order)))


def decide(
    db: Session,
    adjustment_id: str,
    role: str,
    decision: str,
    comment: str | None,
    actor_username: str | None = None,
) -> Adjustment:
    adjustment = db.get(Adjustment, adjustment_id)
    if adjustment is None:
        raise ApprovalConflict("Adjustment not found")
    if adjustment.status != "pending":
        raise ApprovalConflict(f"Cannot decide adjustment in {adjustment.status} state")
    if decision not in {"approved", "rejected"}:
        raise ApprovalConflict("Decision must be approved or rejected")
    steps = _ordered_steps(adjustment, ensure_approval_steps(db, adjustment))
    pending = next((step for step in steps if step.decision == "pending"), None)
    if pending is None:
        raise ApprovalConflict("No pending approval step remains")
    if pending.approver_role != role:
        raise ApprovalConflict(f"Approval is out of order; required role is {pending.approver_role}")

    now = datetime.now(UTC)
    pending.decision = decision
    pending.comment = comment
    pending.decided_at = now
    previous_status = adjustment.status
    if decision == "rejected":
        adjustment.status = "rejected"
    elif all(step.decision == "approved" for step in steps):
        adjustment.status = "approved"
        case = db.get(ExceptionCase, adjustment.exception_id)
        if case is not None:
            case.status = "resolved"

    write_audit(
        db,
        actor=actor_username or role,
        action="approval_decision",
        entity_type="Adjustment",
        entity_id=adjustment.id,
        inputs={"approver_role": role, "decision": decision, "comment": comment},
        formula="pending -> approved/rejected; all required steps must approve",
        output={
            "previous_status": previous_status,
            "status": adjustment.status,
            "step_id": pending.id,
            "step_decision": pending.decision,
        },
    )
    db.commit()
    return adjustment


def approval_steps(db: Session, adjustment_id: str) -> list[ApprovalStep]:
    steps = list(db.scalars(select(ApprovalStep).where(
        ApprovalStep.adjustment_id == adjustment_id,
    )))
    adjustment = db.get(Adjustment, adjustment_id)
    return _ordered_steps(adjustment, steps) if adjustment is not None else steps
