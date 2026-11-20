from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.security import actor_from_user, get_current_user, require_roles
from app.database import get_db
from app.models import User
from app.services.adjustments import (
    get_adjustment,
    list_adjustments,
    propose_adjustments,
)
from app.services.approvals import (
    ApprovalConflict,
    approval_steps,
    decide,
    required_roles,
)
from app.services.audit import write_audit

router = APIRouter(prefix="/adjustments", tags=["adjustments"])


class DecisionRequest(BaseModel):
    decision: str
    comment: str | None = None
    role: str | None = None  # Ignored: role always comes from the verified JWT token.


def _serialize(db: Session, adjustment) -> dict[str, object]:
    return {
        "id": adjustment.id,
        "exception_id": adjustment.exception_id,
        "proposed_amount": str(adjustment.proposed_amount),
        "calculation": adjustment.calculation_json,
        "status": adjustment.status,
        "required_approvers": required_roles(adjustment.proposed_amount),
        "approval_steps": [
            {
                "id": step.id,
                "role": step.approver_role,
                "decision": step.decision,
                "comment": step.comment,
                "decided_at": step.decided_at.isoformat() if step.decided_at else None,
            }
            for step in approval_steps(db, adjustment.id)
        ],
    }


@router.post("/propose", dependencies=[Depends(require_roles("analyst", "admin"))])
def propose(db: Session = Depends(get_db)) -> list[dict[str, object]]:  # noqa: B008
    return [_serialize(db, adjustment) for adjustment in propose_adjustments(db)]


@router.get("", dependencies=[Depends(get_current_user)])
def list_all(db: Session = Depends(get_db)) -> list[dict[str, object]]:  # noqa: B008
    return [_serialize(db, adjustment) for adjustment in list_adjustments(db)]


@router.get("/{adjustment_id}", dependencies=[Depends(get_current_user)])
def get_one(adjustment_id: str, db: Session = Depends(get_db)) -> dict[str, object]:  # noqa: B008
    adjustment = get_adjustment(db, adjustment_id)
    if adjustment is None:
        raise HTTPException(status_code=404, detail="Adjustment not found")
    return _serialize(db, adjustment)


@router.post("/{adjustment_id}/decision")
def decision(
    adjustment_id: str,
    request: DecisionRequest,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(require_roles("approver", "admin")),  # noqa: B008
) -> dict[str, object]:
    # Never trust request.role; authorization comes solely from current_user.role.
    pending = next(
        (step for step in approval_steps(db, adjustment_id) if step.decision == "pending"),
        None,
    )
    step_role = pending.approver_role if pending is not None else (current_user.role or "approver")
    try:
        adjustment = decide(db, adjustment_id, step_role, request.decision, request.comment)
    except ApprovalConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    write_audit(
        db,
        actor=actor_from_user(current_user),
        action="approval_decision_authenticated",
        entity_type="Adjustment",
        entity_id=adjustment.id,
        inputs={
            "username": current_user.username,
            "role": current_user.role,
            "step_role": step_role,
            "decision": request.decision,
            "comment": request.comment,
        },
        formula="Authenticated approver/admin executed approval step from verified token",
        output={"status": adjustment.status},
    )
    db.commit()
    return _serialize(db, adjustment)
