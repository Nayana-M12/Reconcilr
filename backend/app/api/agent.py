from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.investigate import investigate_exception
from app.agent.verifier import InvestigationResult
from app.auth import AuthenticatedUser, require_roles
from app.database import get_db
from app.models import AgentRun, ExceptionCase
from app.services.adjustments import propose_adjustments
from app.services.audit import write_audit

router = APIRouter(prefix="/agent", tags=["agent"])


class InvestigateRequest(BaseModel):
    exception_id: str | None = None


class DecisionRequest(BaseModel):
    note: str | None = None


def _serialize(run: AgentRun) -> dict[str, Any]:
    return {
        "id": run.id, "exception_id": run.exception_id, "verdict": run.verdict,
        "explanation": run.explanation, "claims": run.claims, "tool_calls": run.tool_calls,
        "source": run.source, "verification_status": run.verification_status,
        "errors": run.errors, "status": run.status, "created_at": run.created_at,
    }


@router.post("/investigate")
def investigate(
    request: InvestigateRequest,
    db: Session = Depends(get_db),  # noqa: B008
    user: AuthenticatedUser = Depends(require_roles("analyst", "admin")),  # noqa: B008
) -> list[dict[str, Any]]:
    if request.exception_id:
        exception = db.get(ExceptionCase, request.exception_id)
        if exception is None:
            raise HTTPException(status_code=404, detail="Exception not found")
        exception_ids = [request.exception_id]
    else:
        exception_ids = list(db.scalars(select(ExceptionCase.id).where(ExceptionCase.status == "open")))
    return [_serialize(investigate_exception(db, exception_id)) for exception_id in exception_ids]


@router.get("/runs")
def list_runs(db: Session = Depends(get_db)) -> list[dict[str, Any]]:  # noqa: B008
    runs = db.scalars(select(AgentRun).order_by(AgentRun.created_at.desc(), AgentRun.id.desc()))
    return [_serialize(run) for run in runs]


@router.post("/runs/{run_id}/accept")
def accept_run(
    run_id: str,
    request: DecisionRequest,
    db: Session = Depends(get_db),  # noqa: B008
    user: AuthenticatedUser = Depends(require_roles("approver", "admin")),  # noqa: B008
) -> dict[str, Any]:
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if run.status != "pending":
        raise HTTPException(status_code=409, detail=f"Run is already {run.status}")
    result = InvestigationResult.model_validate_json(run.explanation)
    if result.proposed_action == "propose_adjustment":
        propose_adjustments(db, exception_ids=[run.exception_id])
    run.status = "accepted"
    write_audit(
        db, actor=user.username, action="agent_accept", entity_type="AgentRun", entity_id=run.id,
        inputs={"note": request.note}, formula="Human accepted verified agent recommendation",
        output={"status": run.status, "proposed_action": result.proposed_action},
    )
    db.commit()
    return _serialize(run)


@router.post("/runs/{run_id}/override")
def override_run(
    run_id: str,
    request: DecisionRequest,
    db: Session = Depends(get_db),  # noqa: B008
    user: AuthenticatedUser = Depends(require_roles("approver", "admin")),  # noqa: B008
) -> dict[str, Any]:
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if run.status != "pending":
        raise HTTPException(status_code=409, detail=f"Run is already {run.status}")
    run.status = "overridden"
    write_audit(
        db, actor=user.username, action="agent_override", entity_type="AgentRun", entity_id=run.id,
        inputs={"note": request.note}, formula="Human override of agent recommendation",
        output={"status": run.status},
    )
    db.commit()
    return _serialize(run)
