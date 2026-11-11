from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Adjustment,
    Evidence,
    ExceptionCase,
    Invoice,
    Payment,
    PurchaseOrder,
)
from app.services.approvals import ensure_approval_steps
from app.services.audit import write_audit


def _amount(record_type: str, record_id: str, db: Session) -> Decimal:
    model = {"invoice": Invoice, "purchase_order": PurchaseOrder, "payment": Payment}[record_type]
    record = db.get(model, record_id)
    if record is None:
        raise ValueError(f"{record_type} record {record_id} does not exist")
    return record.amount


def _calculation(db: Session, case: ExceptionCase) -> tuple[Decimal, dict[str, Any], str]:
    evidence = list(db.scalars(select(Evidence).where(Evidence.exception_id == case.id)))
    inputs: dict[str, str] = {}
    for item in evidence:
        if item.record_type in {"invoice", "purchase_order", "payment"}:
            inputs[item.record_id] = str(_amount(item.record_type, item.record_id, db))

    def first(record_type: str) -> tuple[str, Decimal]:
        for item in evidence:
            if item.record_type == record_type:
                return item.record_id, _amount(record_type, item.record_id, db)
        raise ValueError(f"{case.type} requires a {record_type} evidence record")

    if case.type == "PARTIAL_PAYMENT":
        invoice_id, invoice_amount = first("invoice")
        payment_id, payment_amount = first("payment")
        result = invoice_amount - payment_amount
        formula = "remaining balance = invoice amount - payment amount"
        inputs = {invoice_id: str(invoice_amount), payment_id: str(payment_amount)}
    elif case.type == "OVERPAYMENT":
        invoice_id, invoice_amount = first("invoice")
        payment_id, payment_amount = first("payment")
        result = payment_amount - invoice_amount
        formula = "refund/credit = payment amount - invoice amount"
        inputs = {invoice_id: str(invoice_amount), payment_id: str(payment_amount)}
    elif case.type == "DUPLICATE_INVOICE":
        invoice_items = [item for item in evidence if item.record_type == "invoice"]
        if len(invoice_items) < 2:
            raise ValueError("DUPLICATE_INVOICE requires canonical and duplicate invoice evidence")
        duplicate = invoice_items[-1]
        result = _amount("invoice", duplicate.record_id, db)
        formula = "void amount = duplicate invoice amount"
        inputs = {item.record_id: str(_amount("invoice", item.record_id, db)) for item in invoice_items}
    elif case.type == "AMOUNT_MISMATCH":
        invoice_id, invoice_amount = first("invoice")
        po_id, po_amount = first("purchase_order")
        result = abs(invoice_amount - po_amount)
        formula = "difference = absolute(invoice amount - purchase order amount)"
        inputs = {invoice_id: str(invoice_amount), po_id: str(po_amount)}
    else:
        result = Decimal("0.00")
        formula = "review required; no deterministic monetary adjustment"
    calculation = {
        "record_ids": list(inputs),
        "amounts": inputs,
        "formula": formula,
        "result": str(result),
        "note": "review required" if result == 0 else None,
    }
    return result, calculation, formula


def propose_adjustments(db: Session) -> list[Adjustment]:
    settings = get_settings()
    adjustments: list[Adjustment] = []
    cases = list(db.scalars(select(ExceptionCase).where(ExceptionCase.status == "open")))
    for case in cases:
        existing = db.scalar(select(Adjustment).where(Adjustment.exception_id == case.id,
                                                       Adjustment.status == "pending"))
        if existing is not None:
            adjustments.append(existing)
            continue
        amount, calculation, formula = _calculation(db, case)
        adjustment = Adjustment(
            exception_id=case.id,
            proposed_amount=amount,
            calculation_json=calculation,
            status="pending",
        )
        db.add(adjustment)
        db.flush()
        ensure_approval_steps(db, adjustment)
        write_audit(
            db,
            actor=settings.audit_actor,
            action="adjustment_proposed",
            entity_type="Adjustment",
            entity_id=adjustment.id,
            inputs=calculation,
            formula=formula,
            output={"proposed_amount": str(amount), "status": "pending"},
        )
        adjustments.append(adjustment)
    db.commit()
    return adjustments


def list_adjustments(db: Session) -> list[Adjustment]:
    return list(db.scalars(select(Adjustment).order_by(Adjustment.created_at, Adjustment.id)))


def get_adjustment(db: Session, adjustment_id: str) -> Adjustment | None:
    return db.get(Adjustment, adjustment_id)
