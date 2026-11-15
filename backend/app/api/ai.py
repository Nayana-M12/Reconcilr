from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.suggestions import suggest_near_duplicates, suggest_vendor_aliases
from app.database import get_db
from app.models import (
    AISuggestion,
    Evidence,
    ExceptionCase,
    Invoice,
    Vendor,
    VendorAlias,
)
from app.services.adjustments import propose_adjustments
from app.services.audit import write_audit

router = APIRouter(prefix="/ai", tags=["ai"])


class DecisionRequest(BaseModel):
    role: str = "human"
    note: str | None = None


def _serialize(suggestion: AISuggestion) -> dict[str, Any]:
    return {
        "id": suggestion.id,
        "kind": suggestion.kind,
        "record_ids": suggestion.record_ids,
        "score": float(suggestion.score),
        "reason": suggestion.reason,
        "source": suggestion.source,
        "status": suggestion.status,
        "created_at": suggestion.created_at,
        **suggestion.payload,
    }


def _persist_suggestions(db: Session, suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for candidate in suggestions:
        record_ids = list(candidate["record_ids"])
        models = (Vendor, Vendor) if candidate["kind"] == "vendor_alias" else (Invoice, Invoice)
        if any(db.get(model, record_id) is None for model, record_id in zip(models, record_ids)):
            raise HTTPException(status_code=500, detail="Suggestion referenced a missing record")
        suggestion = AISuggestion(
            kind=candidate["kind"],
            record_ids=record_ids,
            payload=candidate,
            score=candidate["score"],
            reason=candidate["reason"],
            source=candidate["source"],
        )
        db.add(suggestion)
        db.flush()
        write_audit(
            db, actor="agent", action="ai_suggestion", entity_type="AISuggestion", entity_id=suggestion.id,
            inputs={"kind": suggestion.kind, "record_ids": record_ids},
            formula="AI similarity suggestion; no reconciliation decision",
            output={"score": candidate["score"], "source": candidate["source"]},
        )
        output.append(_serialize(suggestion))
    db.commit()
    return output


@router.post("/vendor-suggestions")
def vendor_suggestions(db: Session = Depends(get_db)) -> list[dict[str, Any]]:  # noqa: B008
    return _persist_suggestions(db, suggest_vendor_aliases(db))


@router.post("/duplicate-suggestions")
def duplicate_suggestions(db: Session = Depends(get_db)) -> list[dict[str, Any]]:  # noqa: B008
    return _persist_suggestions(db, suggest_near_duplicates(db))


def _validate_records(db: Session, suggestion: AISuggestion) -> None:
    model = Vendor if suggestion.kind == "vendor_alias" else Invoice
    if any(db.get(model, record_id) is None for record_id in suggestion.record_ids):
        raise HTTPException(status_code=400, detail="Suggestion contains a missing record ID")


def _accept_near_duplicate(db: Session, suggestion: AISuggestion) -> str:
    left_id, right_id = suggestion.record_ids
    case = db.scalar(select(ExceptionCase).where(
        ExceptionCase.type == "DUPLICATE_INVOICE",
        ExceptionCase.invoice_id == right_id,
    ))
    if case is None:
        case = ExceptionCase(
            type="DUPLICATE_INVOICE",
            severity="high",
            invoice_id=right_id,
            description="Human accepted an AI near-duplicate suggestion.",
        )
        db.add(case)
        db.flush()
        db.add_all([
            Evidence(
                exception_id=case.id,
                record_type="invoice",
                record_id=left_id,
                note="Canonical invoice cited by accepted near-duplicate suggestion.",
            ),
            Evidence(
                exception_id=case.id,
                record_type="invoice",
                record_id=right_id,
                note="Candidate invoice cited by accepted near-duplicate suggestion.",
            ),
        ])
    propose_adjustments(db)
    return case.id


@router.post("/suggestions/{suggestion_id}/accept")
def accept_suggestion(
    suggestion_id: str, request: DecisionRequest, db: Session = Depends(get_db)  # noqa: B008
) -> dict[str, Any]:
    suggestion = db.get(AISuggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if suggestion.status != "pending":
        raise HTTPException(status_code=409, detail=f"Suggestion is already {suggestion.status}")
    _validate_records(db, suggestion)
    output: dict[str, Any] = {"status": "accepted"}
    if suggestion.kind == "vendor_alias":
        left_id, right_id = suggestion.record_ids
        existing = db.scalar(select(VendorAlias).where(
            VendorAlias.vendor_id == left_id,
            VendorAlias.alias_vendor_id == right_id,
        ))
        if existing is None:
            db.add(VendorAlias(
                vendor_id=left_id,
                alias_vendor_id=right_id,
                score=suggestion.score,
                reason=suggestion.reason,
                source=suggestion.source,
            ))
    else:
        output["exception_id"] = _accept_near_duplicate(db, suggestion)
    suggestion.status = "accepted"
    write_audit(
        db, actor=request.role, action="ai_suggestion_accept", entity_type="AISuggestion",
        entity_id=suggestion.id, inputs={"role": request.role, "note": request.note},
        formula="Human accepted an AI suggestion; deterministic reconciliation remains unchanged",
        output=output,
    )
    db.commit()
    return {**_serialize(suggestion), **output}


@router.post("/suggestions/{suggestion_id}/reject")
def reject_suggestion(
    suggestion_id: str, request: DecisionRequest, db: Session = Depends(get_db)  # noqa: B008
) -> dict[str, Any]:
    suggestion = db.get(AISuggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if suggestion.status != "pending":
        raise HTTPException(status_code=409, detail=f"Suggestion is already {suggestion.status}")
    suggestion.status = "rejected"
    write_audit(
        db, actor=request.role, action="ai_suggestion_reject", entity_type="AISuggestion",
        entity_id=suggestion.id, inputs={"role": request.role, "note": request.note},
        formula="Human rejected an AI similarity suggestion",
        output={"status": suggestion.status},
    )
    db.commit()
    return _serialize(suggestion)
