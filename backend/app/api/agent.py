from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.investigate import investigate_exception
from app.agent.verifier import InvestigationResult
from app.auth.security import actor_from_user, get_current_user, require_roles
from app.database import get_db
from app.models import Adjustment, AgentRun, Evidence, ExceptionCase, User
from app.services.adjustments import propose_adjustments
from app.services.audit import write_audit

router = APIRouter(prefix="/agent", tags=["agent"])


class InvestigateRequest(BaseModel):
    exception_id: str | None = None


class DecisionRequest(BaseModel):
    role: str = "human"
    note: str | None = None
    selected_solution_id: str | None = None


def _parsed_plan(run: AgentRun) -> dict[str, Any] | None:
    try:
        parsed = InvestigationResult.model_validate_json(run.explanation)
        return parsed.resolution_plan.model_dump() if parsed.resolution_plan else None
    except ValueError:
        return None


def _serialize(run: AgentRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "exception_id": run.exception_id,
        "verdict": run.verdict,
        "explanation": run.explanation,
        "resolution_plan": _parsed_plan(run),
        "claims": run.claims,
        "tool_calls": run.tool_calls,
        "source": run.source,
        "verification_status": run.verification_status,
        "errors": run.errors,
        "status": run.status,
        "selected_solution_id": run.selected_solution_id,
        "selected_solution_note": run.selected_solution_note,
        "created_at": run.created_at,
    }


def _supporting_evidence_ids(db: Session, run: AgentRun, result: InvestigationResult) -> list[str]:
    from_claims = {rid for claim in result.claims for rid in claim.record_ids}
    from_db = set(
        db.scalars(select(Evidence.record_id).where(Evidence.exception_id == run.exception_id))
    )
    return sorted(from_claims | from_db)


@router.post("/investigate", dependencies=[Depends(require_roles("analyst", "approver", "admin"))])
def investigate(
    request: InvestigateRequest | None = None,
    db: Session = Depends(get_db),  # noqa: B008
) -> list[dict[str, Any]]:
    payload = request or InvestigateRequest()
    if payload.exception_id:
        exception = db.get(ExceptionCase, payload.exception_id)
        if exception is None:
            raise HTTPException(status_code=404, detail="Exception not found")
        exception_ids = [payload.exception_id]
    else:
        exception_ids = list(db.scalars(select(ExceptionCase.id).where(ExceptionCase.status == "open")))
    return [_serialize(investigate_exception(db, exception_id)) for exception_id in exception_ids]


@router.get("/runs", dependencies=[Depends(get_current_user)])
def list_runs(db: Session = Depends(get_db)) -> list[dict[str, Any]]:  # noqa: B008
    runs = db.scalars(select(AgentRun).order_by(AgentRun.created_at.desc(), AgentRun.id.desc()))
    return [_serialize(run) for run in runs]


@router.post("/runs/{run_id}/accept")
def accept_run(
    run_id: str,
    request: DecisionRequest,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(require_roles("analyst", "approver", "admin")),  # noqa: B008
) -> dict[str, Any]:
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if run.status != "pending":
        raise HTTPException(status_code=409, detail=f"Run is already {run.status}")

    result = InvestigationResult.model_validate_json(run.explanation)
    plan = result.resolution_plan
    selected_option = None
    if request.selected_solution_id:
        if plan is None:
            raise HTTPException(status_code=400, detail="This agent run has no resolution plan options.")
        selected_option = next(
            (opt for opt in plan.possible_solutions if opt.id == request.selected_solution_id),
            None,
        )
        if selected_option is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown selected_solution_id '{request.selected_solution_id}'.",
            )
    elif plan is not None and plan.recommended_solution_id:
        selected_option = next(
            (opt for opt in plan.possible_solutions if opt.id == plan.recommended_solution_id),
            None,
        )

    effective_action = selected_option.workflow_action if selected_option else result.proposed_action
    routed_adjustment_id: str | None = None
    if effective_action in {"propose_adjustment", "mark_duplicate"}:
        propose_adjustments(db)
        adj = db.scalar(select(Adjustment).where(Adjustment.exception_id == run.exception_id))
        routed_adjustment_id = adj.id if adj is not None else None

    run.status = "accepted"
    run.selected_solution_id = selected_option.id if selected_option else request.selected_solution_id
    run.selected_solution_note = (request.note or "").strip() or None

    actor = actor_from_user(current_user, fallback=request.role)
    role = current_user.role if isinstance(current_user, User) else request.role
    supporting_evidence = _supporting_evidence_ids(db, run, result)
    suggested_solutions = (
        [{"id": opt.id, "title": opt.title, "workflow_action": opt.workflow_action} for opt in plan.possible_solutions]
        if plan
        else []
    )
    write_audit(
        db,
        actor=actor,
        action="agent_accept",
        entity_type="AgentRun",
        entity_id=run.id,
        inputs={
            "role": role,
            "note": request.note,
            "selected_solution_id": run.selected_solution_id,
            "supporting_evidence": supporting_evidence,
        },
        formula="Analyst selected resolution option and routed via existing approval workflow (never auto-applied)",
        output={
            "status": run.status,
            "proposed_action": effective_action,
            "ai_problem_identification": plan.problem_identification if plan else None,
            "suggested_solutions": suggested_solutions,
            "selected_solution": (
                {"id": selected_option.id, "title": selected_option.title, "workflow_action": selected_option.workflow_action}
                if selected_option
                else None
            ),
            "routed_adjustment_id": routed_adjustment_id,
        },
    )
    db.commit()
    return _serialize(run)


@router.post("/runs/{run_id}/override")
def override_run(
    run_id: str,
    request: DecisionRequest,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(require_roles("analyst", "approver", "admin")),  # noqa: B008
) -> dict[str, Any]:
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if run.status != "pending":
        raise HTTPException(status_code=409, detail=f"Run is already {run.status}")
    result = InvestigationResult.model_validate_json(run.explanation)
    plan = result.resolution_plan
    run.status = "overridden"
    run.selected_solution_note = (request.note or "").strip() or None
    actor = actor_from_user(current_user, fallback=request.role)
    role = current_user.role if isinstance(current_user, User) else request.role
    write_audit(
        db,
        actor=actor,
        action="agent_override",
        entity_type="AgentRun",
        entity_id=run.id,
        inputs={
            "role": role,
            "note": request.note,
            "supporting_evidence": _supporting_evidence_ids(db, run, result),
        },
        formula="Human override of AI resolution suggestion",
        output={
            "status": run.status,
            "ai_problem_identification": plan.problem_identification if plan else None,
            "suggested_solutions": (
                [{"id": opt.id, "title": opt.title} for opt in plan.possible_solutions] if plan else []
            ),
        },
    )
    db.commit()
    return _serialize(run)
