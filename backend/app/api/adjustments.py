from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser, require_roles
from app.database import get_db
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

router = APIRouter(prefix="/adjustments", tags=["adjustments"])


class DecisionRequest(BaseModel):
    role: str
    decision: str
    comment: str | None = None


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


@router.post("/propose")
def propose(
    db: Session = Depends(get_db),  # noqa: B008
    user: AuthenticatedUser = Depends(require_roles("analyst", "admin")),  # noqa: B008
) -> list[dict[str, object]]:
    return [_serialize(db, adjustment) for adjustment in propose_adjustments(db)]


@router.get("")
def list_all(db: Session = Depends(get_db)) -> list[dict[str, object]]:  # noqa: B008
    return [_serialize(db, adjustment) for adjustment in list_adjustments(db)]


@router.get("/{adjustment_id}")
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
    user: AuthenticatedUser = Depends(require_roles("approver", "admin")),  # noqa: B008
) -> dict[str, object]:
    try:
        steps = approval_steps(db, adjustment_id)
        pending = next((step for step in steps if step.decision == "pending"), None)
        decision_role = pending.approver_role if pending is not None else user.role
        adjustment = decide(db, adjustment_id, decision_role, request.decision, request.comment, actor_username=user.username)
    except ApprovalConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _serialize(db, adjustment)
