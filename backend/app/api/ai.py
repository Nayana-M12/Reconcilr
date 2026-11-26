from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.suggestions import (
    generate_all_actionable_suggestions,
    suggest_near_duplicates,
    suggest_vendor_aliases,
)
from app.auth import AuthenticatedUser, get_current_user, require_roles
from app.database import get_db
from app.models import (
    AISuggestion,
    Evidence,
    ExceptionCase,
    Invoice,
    Match,
    Payment,
    PurchaseOrder,
    Vendor,
    VendorAlias,
)
from app.services.adjustments import propose_adjustments
from app.services.audit import write_audit

router = APIRouter(prefix="/ai", tags=["ai"])


class DecisionRequest(BaseModel):
    note: str | None = None


def _serialize(suggestion: AISuggestion) -> dict[str, Any]:
    payload = suggestion.payload or {}
    action = suggestion.action or payload.get("action")
    is_actionable = bool(action and action != "none")
    return {
        "id": suggestion.id,
        "kind": suggestion.kind,
        "action": action,
        "is_actionable": is_actionable,
        "record_ids": suggestion.record_ids,
        "score": float(suggestion.score),
        "reason": suggestion.reason,
        "source": suggestion.source,
        "status": suggestion.status,
        "created_at": suggestion.created_at.isoformat() if suggestion.created_at else None,
        "user_id": suggestion.user_id,
        **payload,
    }


def _record_exists(db: Session, record_id: str) -> bool:
    for model in (Vendor, Invoice, PurchaseOrder, Payment):
        if db.get(model, record_id) is not None:
            return True
    return False


def _persist_suggestions(db: Session, suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    # Fetch existing pending fingerprints to avoid duplicate pending suggestions
    existing_pending = {
        (s.kind, tuple(sorted(s.record_ids)))
        for s in db.scalars(select(AISuggestion).where(AISuggestion.status == "pending"))
    }

    for candidate in suggestions:
        record_ids = list(candidate["record_ids"])
        key = (candidate["kind"], tuple(sorted(record_ids)))
        if key in existing_pending:
            continue

        if any(not _record_exists(db, record_id) for record_id in record_ids):
            continue

        suggestion = AISuggestion(
            kind=candidate["kind"],
            record_ids=record_ids,
            payload=candidate,
            score=candidate["score"],
            reason=candidate["reason"],
            source=candidate["source"],
            status="pending",
        )
        db.add(suggestion)
        db.flush()
        existing_pending.add(key)

        write_audit(
            db,
            actor="ai_engine",
            action="ai_suggestion",
            entity_type="AISuggestion",
            entity_id=suggestion.id,
            inputs={"kind": suggestion.kind, "record_ids": record_ids},
            formula="AI contextual and similarity recommendation",
            output={"score": candidate["score"], "source": candidate["source"]},
        )
        output.append(_serialize(suggestion))

    db.commit()
    return output


@router.get("/suggestions")
def get_suggestions(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    # If no pending suggestions exist, auto-generate from current data
    pending_count = db.scalar(
        select(func.count(AISuggestion.id)).where(AISuggestion.status == "pending")
    ) or 0
    if pending_count == 0:
        candidates = generate_all_actionable_suggestions(db)
        if candidates:
            _persist_suggestions(db, candidates)

    q = select(AISuggestion).order_by(AISuggestion.created_at.desc())
    if status:
        q = q.where(AISuggestion.status == status)

    if user.role not in {"admin", "auditor"}:
        q = q.where((AISuggestion.user_id == user.id) | (AISuggestion.user_id.is_(None)))

    suggestions = list(db.scalars(q))
    return [_serialize(s) for s in suggestions]


@router.post("/generate")
def generate_suggestions(
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_roles("analyst", "approver", "admin")),
) -> list[dict[str, Any]]:
    candidates = generate_all_actionable_suggestions(db)
    return _persist_suggestions(db, candidates)


@router.post("/vendor-suggestions")
def vendor_suggestions(
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_roles("analyst", "admin")),
) -> list[dict[str, Any]]:
    return _persist_suggestions(db, suggest_vendor_aliases(db))


@router.post("/duplicate-suggestions")
def duplicate_suggestions(
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_roles("analyst", "admin")),
) -> list[dict[str, Any]]:
    return _persist_suggestions(db, suggest_near_duplicates(db))


def _validate_records(db: Session, suggestion: AISuggestion) -> None:
    for record_id in suggestion.record_ids:
        if not _record_exists(db, record_id):
            raise HTTPException(status_code=400, detail="Suggestion contains a missing record ID")


def _accept_near_duplicate(db: Session, suggestion: AISuggestion) -> str:
    left_id, right_id = suggestion.record_ids
    case = db.scalar(
        select(ExceptionCase).where(
            ExceptionCase.type == "DUPLICATE_INVOICE",
            ExceptionCase.invoice_id == right_id,
        )
    )
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
    propose_adjustments(db, exception_ids=[case.id])
    return case.id


@router.post("/suggestions/{suggestion_id}/accept")
def accept_suggestion(
    suggestion_id: str,
    request: DecisionRequest,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_roles("analyst", "approver", "admin")),
) -> dict[str, Any]:
    suggestion = db.get(AISuggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if suggestion.status != "pending":
        raise HTTPException(status_code=409, detail=f"Suggestion is already {suggestion.status}")
    _validate_records(db, suggestion)

    output: dict[str, Any] = {"status": "accepted"}
    payload = suggestion.payload or {}

    try:
        if suggestion.kind == "vendor_alias":
            left_id, right_id = suggestion.record_ids
            existing = db.scalar(
                select(VendorAlias).where(
                    VendorAlias.vendor_id == left_id,
                    VendorAlias.alias_vendor_id == right_id,
                )
            )
            if existing is None:
                db.add(
                    VendorAlias(
                        vendor_id=left_id,
                        alias_vendor_id=right_id,
                        score=suggestion.score,
                        reason=suggestion.reason,
                        source=suggestion.source,
                    )
                )
            output["action"] = "vendor_alias_created"

        elif suggestion.kind in {"near_duplicate", "duplicate_invoice"}:
            output["exception_id"] = _accept_near_duplicate(db, suggestion)
            output["action"] = "duplicate_exception_created"

        elif suggestion.kind == "match_invoice_po":
            inv_id = payload.get("invoice_id") or suggestion.record_ids[0]
            po_id = payload.get("po_id") or suggestion.record_ids[1]
            inv = db.get(Invoice, inv_id)
            po = db.get(PurchaseOrder, po_id)
            if not inv or not po:
                raise ValueError("Invoice or Purchase Order not found")
            match = Match(
                invoice_id=inv.id,
                po_id=po.id,
                tier="ai_suggested",
                confidence=suggestion.score,
                matched_amount=inv.amount,
            )
            db.add(match)
            output["match_id"] = match.id
            output["action"] = f"Matched invoice #{inv.invoice_number} with PO #{po.po_number}"

        elif suggestion.kind == "mark_payment_completed":
            pay_id = payload.get("payment_id") or suggestion.record_ids[0]
            pay = db.get(Payment, pay_id)
            if not pay:
                raise ValueError("Payment record not found")
            raw = dict(pay.raw_row or {})
            raw["payment_status"] = "Completed"
            raw["status"] = "Completed"
            pay.raw_row = raw
            output["payment_id"] = pay.id
            output["action"] = f"Marked payment {pay.reference} as Completed"

        elif suggestion.kind == "amount_discrepancy":
            inv_id = payload.get("invoice_id") or suggestion.record_ids[0]
            po_id = payload.get("po_id") or (suggestion.record_ids[1] if len(suggestion.record_ids) > 1 else None)
            case = ExceptionCase(
                type="AMOUNT_MISMATCH",
                severity="medium",
                invoice_id=inv_id,
                po_id=po_id,
                description=suggestion.reason,
            )
            db.add(case)
            db.flush()
            db.add(
                Evidence(
                    exception_id=case.id,
                    record_type="invoice",
                    record_id=inv_id,
                    note=f"Amount discrepancy: {suggestion.reason}",
                )
            )
            if po_id:
                db.add(
                    Evidence(
                        exception_id=case.id,
                        record_type="purchase_order",
                        record_id=po_id,
                        note="Corresponding purchase order with amount discrepancy.",
                    )
                )
            propose_adjustments(db, exception_ids=[case.id])
            output["exception_id"] = case.id
            output["action"] = "Initiated amount discrepancy exception and adjustment review"

        elif suggestion.kind == "overdue_payment":
            inv_id = payload.get("invoice_id") or suggestion.record_ids[0]
            case = ExceptionCase(
                type="OVERDUE_PAYMENT",
                severity="medium",
                invoice_id=inv_id,
                description=suggestion.reason,
            )
            db.add(case)
            db.flush()
            db.add(
                Evidence(
                    exception_id=case.id,
                    record_type="invoice",
                    record_id=inv_id,
                    note=f"Overdue payment warning: {suggestion.reason}",
                )
            )
            output["exception_id"] = case.id
            output["action"] = "Flagged invoice as overdue for collections follow-up"

        elif suggestion.kind == "missing_po":
            inv_id = payload.get("invoice_id") or suggestion.record_ids[0]
            case = ExceptionCase(
                type="MISSING_PO",
                severity="high",
                invoice_id=inv_id,
                description=suggestion.reason,
            )
            db.add(case)
            db.flush()
            db.add(
                Evidence(
                    exception_id=case.id,
                    record_type="invoice",
                    record_id=inv_id,
                    note=f"Missing purchase order: {suggestion.reason}",
                )
            )
            output["exception_id"] = case.id
            output["action"] = "Created missing PO exception for procurement resolution"

        elif suggestion.kind == "high_value_approval":
            inv_id = payload.get("invoice_id") or suggestion.record_ids[0]
            case = ExceptionCase(
                type="APPROVAL_REQUIRED",
                severity="high",
                invoice_id=inv_id,
                description=suggestion.reason,
            )
            db.add(case)
            db.flush()
            db.add(
                Evidence(
                    exception_id=case.id,
                    record_type="invoice",
                    record_id=inv_id,
                    note=f"High-value invoice routed for approval: {suggestion.reason}",
                )
            )
            propose_adjustments(db, exception_ids=[case.id])
            output["exception_id"] = case.id
            output["action"] = "Routed high-value invoice to executive approval workflow"

        else:
            output["action"] = "acknowledged_recommendation"

        suggestion.status = "accepted"
        write_audit(
            db,
            actor=user.username,
            action="ai_suggestion_accept",
            entity_type="AISuggestion",
            entity_id=suggestion.id,
            inputs={"note": request.note, "kind": suggestion.kind},
            formula="User accepted AI recommendation; backend executed corresponding operation",
            output=output,
        )
        db.commit()
        return {**_serialize(suggestion), **output}

    except Exception as exc:
        db.rollback()
        suggestion.status = "failed"
        db.add(suggestion)
        db.commit()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute action for suggestion: {str(exc)}",
        ) from exc


@router.post("/suggestions/{suggestion_id}/reject")
def reject_suggestion(
    suggestion_id: str,
    request: DecisionRequest,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_roles("analyst", "approver", "admin")),
) -> dict[str, Any]:
    suggestion = db.get(AISuggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if suggestion.status != "pending":
        raise HTTPException(status_code=409, detail=f"Suggestion is already {suggestion.status}")
    suggestion.status = "rejected"
    write_audit(
        db,
        actor=user.username,
        action="ai_suggestion_reject",
        entity_type="AISuggestion",
        entity_id=suggestion.id,
        inputs={"note": request.note},
        formula="User rejected AI suggestion",
        output={"status": suggestion.status},
    )
    db.commit()
    return _serialize(suggestion)
