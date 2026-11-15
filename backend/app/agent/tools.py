from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Evidence, ExceptionCase, Invoice, Payment, PurchaseOrder, Vendor
from app.services.adjustments import _amount


def _record(record: Invoice | Payment | PurchaseOrder | Vendor) -> dict[str, Any]:
    if isinstance(record, Invoice):
        return {
            "id": record.id, "record_type": "invoice", "vendor_id": record.vendor_id,
            "invoice_number": record.invoice_number, "po_number": record.po_number,
            "amount": str(record.amount), "currency": record.currency,
            "invoice_date": record.invoice_date.isoformat(), "due_date": record.due_date.isoformat()
            if record.due_date else None,
        }
    if isinstance(record, Payment):
        return {
            "id": record.id, "record_type": "payment", "vendor_id": record.vendor_id,
            "reference": record.reference, "amount": str(record.amount), "currency": record.currency,
            "payment_date": record.payment_date.isoformat(),
        }
    if isinstance(record, PurchaseOrder):
        return {
            "id": record.id, "record_type": "purchase_order", "vendor_id": record.vendor_id,
            "po_number": record.po_number, "amount": str(record.amount), "currency": record.currency,
            "order_date": record.order_date.isoformat(),
        }
    return {"id": record.id, "record_type": "vendor", "name": record.name}


def _empty(key: str) -> dict[str, Any]:
    return {key: None if key == "record" else [], "found": False}


def search_payments(
    db: Session,
    vendor: str | None = None,
    amount: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    query = select(Payment).join(Vendor)
    if vendor:
        query = query.where(Vendor.name.ilike(f"%{vendor}%"))
    if amount:
        try:
            query = query.where(Payment.amount == Decimal(amount))
        except InvalidOperation:
            return {"records": [], "found": False, "error": "amount must be a decimal string"}
    if date_from:
        query = query.where(Payment.payment_date >= date.fromisoformat(date_from))
    if date_to:
        query = query.where(Payment.payment_date <= date.fromisoformat(date_to))
    records = [_record(item) for item in db.scalars(query.order_by(Payment.payment_date, Payment.id))]
    return {"records": records, "found": bool(records)}


def get_invoice(db: Session, record_id: str) -> dict[str, Any]:
    record = db.get(Invoice, record_id)
    return {"record": _record(record), "found": True} if record else _empty("record")


def get_payment(db: Session, record_id: str) -> dict[str, Any]:
    record = db.get(Payment, record_id)
    return {"record": _record(record), "found": True} if record else _empty("record")


def get_purchase_order(db: Session, record_id: str) -> dict[str, Any]:
    record = db.get(PurchaseOrder, record_id)
    return {"record": _record(record), "found": True} if record else _empty("record")


def get_exception(db: Session, record_id: str) -> dict[str, Any]:
    exception = db.get(ExceptionCase, record_id)
    if exception is None:
        return _empty("record")
    evidence = list(db.scalars(select(Evidence).where(Evidence.exception_id == record_id).order_by(Evidence.id)))
    return {
        "record": {
            "id": exception.id, "record_type": "exception", "type": exception.type,
            "status": exception.status, "severity": exception.severity,
            "invoice_id": exception.invoice_id, "po_id": exception.po_id,
            "payment_id": exception.payment_id, "description": exception.description,
            "evidence": [
                {"record_type": item.record_type, "record_id": item.record_id, "note": item.note}
                for item in evidence
            ],
        },
        "found": True,
    }


def _find_amount_record(db: Session, record_id: str) -> tuple[str, Decimal] | None:
    for record_type, model in (("invoice", Invoice), ("payment", Payment), ("purchase_order", PurchaseOrder)):
        if db.get(model, record_id) is not None:
            return record_type, _amount(record_type, record_id, db)
    return None


def calculate_difference(db: Session, a_id: str, b_id: str) -> dict[str, Any]:
    first = _find_amount_record(db, a_id)
    second = _find_amount_record(db, b_id)
    if first is None or second is None:
        return {"found": False, "difference": None, "records": []}
    difference = first[1] - second[1]
    return {
        "found": True, "a_id": a_id, "b_id": b_id,
        "a_type": first[0], "b_type": second[0],
        "a_amount": str(first[1]), "b_amount": str(second[1]),
        "difference": str(difference),
        "records": [a_id, b_id],
    }


def find_duplicates(db: Session, record_id: str) -> dict[str, Any]:
    invoice = db.get(Invoice, record_id)
    if invoice:
        records = db.scalars(select(Invoice).where(
            Invoice.dedupe_hash == invoice.dedupe_hash, Invoice.id != record_id,
        )).all()
        return {"records": [_record(item) for item in records], "found": bool(records)}
    payment = db.get(Payment, record_id)
    if payment:
        records = db.scalars(select(Payment).where(
            Payment.vendor_id == payment.vendor_id,
            Payment.reference == payment.reference,
            Payment.amount == payment.amount,
            Payment.currency == payment.currency,
            Payment.payment_date == payment.payment_date,
            Payment.id != record_id,
        )).all()
        return {"records": [_record(item) for item in records], "found": bool(records)}
    return {"records": [], "found": False}


TOOL_FUNCTIONS = {
    "search_payments": search_payments,
    "get_invoice": get_invoice,
    "get_payment": get_payment,
    "get_purchase_order": get_purchase_order,
    "get_exception": get_exception,
    "calculate_difference": calculate_difference,
    "find_duplicates": find_duplicates,
}

TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "search_payments", "description": "Search persisted payments.",
     "parameters": {"type": "object", "properties": {"vendor": {"type": "string"}, "amount": {"type": "string"},
     "date_from": {"type": "string"}, "date_to": {"type": "string"}}, "additionalProperties": False}}},
    *[
        {"type": "function", "function": {"name": name, "description": description,
         "parameters": {"type": "object", "properties": {"record_id": {"type": "string"}},
                        "required": ["record_id"], "additionalProperties": False}}}
        for name, description in (
            ("get_invoice", "Get one persisted invoice by ID."),
            ("get_payment", "Get one persisted payment by ID."),
            ("get_purchase_order", "Get one persisted purchase order by ID."),
            ("get_exception", "Get one persisted exception and its evidence."),
            ("find_duplicates", "Find persisted duplicates for an invoice or payment ID."),
        )
    ],
    [{"type": "function", "function": {"name": "calculate_difference", "description": "Calculate a Decimal difference between two persisted amount records.",
      "parameters": {"type": "object", "properties": {"a_id": {"type": "string"}, "b_id": {"type": "string"}},
                     "required": ["a_id", "b_id"], "additionalProperties": False}}}],
]
