from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.models import Evidence, ExceptionCase, Invoice, Match, Payment, PurchaseOrder
from app.services.audit import write_audit
from app.services.exceptions.classifier import classify
from app.services.exceptions.detectors import ExceptionFinding, detect_exceptions
from app.services.exceptions.evidence import attach_evidence


@dataclass(frozen=True)
class ExceptionRunResult:
    created: int
    existing: int
    by_type: dict[str, int]


def _existing(db: Session, finding: ExceptionFinding) -> ExceptionCase | None:
    query = select(ExceptionCase).where(ExceptionCase.type == finding.type)
    for field in ("invoice_id", "po_id", "payment_id"):
        value = getattr(finding, field)
        query = query.where(getattr(ExceptionCase, field).is_(None) if value is None
                            else getattr(ExceptionCase, field) == value)
    return db.scalar(query)


def run_exceptions(db: Session) -> ExceptionRunResult:
    settings = get_settings()
    findings = detect_exceptions(
        list(db.scalars(select(Invoice))),
        list(db.scalars(select(PurchaseOrder))),
        list(db.scalars(select(Payment))),
        list(db.scalars(select(Match))),
        settings,
    )
    created = 0
    existing = 0
    by_type: dict[str, int] = {}
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    for finding in findings:
        key = (finding.type, finding.invoice_id, finding.po_id, finding.payment_id)
        if key in seen:
            continue
        seen.add(key)
        case = _existing(db, finding)
        severity = classify(finding, settings)
        if case is None:
            case = ExceptionCase(
                type=finding.type, severity=severity, invoice_id=finding.invoice_id,
                po_id=finding.po_id, payment_id=finding.payment_id,
                description=finding.description,
            )
            db.add(case)
            db.flush()
            attach_evidence(db, case.id, finding)
            write_audit(
                db, actor=settings.audit_actor, action="exception_created",
                entity_type="ExceptionCase", entity_id=case.id,
                inputs={"type": finding.type, "invoice_id": finding.invoice_id,
                        "po_id": finding.po_id, "payment_id": finding.payment_id,
                        "evidence": [record_id for _, record_id, _ in finding.evidence]},
                formula="Deterministic exception detector and severity classifier",
                output={"exception_id": case.id, "severity": severity},
            )
            created += 1
        else:
            existing += 1
        by_type[finding.type] = by_type.get(finding.type, 0) + 1
    db.commit()
    return ExceptionRunResult(created, existing, by_type)


def _related(invoice: Invoice | None, po: PurchaseOrder | None, payment: Payment | None) -> dict[str, Any]:
    return {
        "invoice": {
            "invoice_number": invoice.invoice_number,
            "vendor_name": invoice.vendor.name,
            "amount": str(invoice.amount),
            "currency": invoice.currency,
        } if invoice else None,
        "purchase_order": {
            "po_number": po.po_number,
            "amount": str(po.amount),
            "currency": po.currency,
        } if po else None,
        "payment": {
            "amount": str(payment.amount),
            "currency": payment.currency,
            "payment_date": payment.payment_date.isoformat(),
        } if payment else None,
    }


def _serialize_case(db: Session, case: ExceptionCase) -> dict[str, Any]:
    evidence = list(db.scalars(select(Evidence).where(Evidence.exception_id == case.id).order_by(Evidence.id)))
    invoice = db.scalar(select(Invoice).options(joinedload(Invoice.vendor)).where(Invoice.id == case.invoice_id)) if case.invoice_id else None
    po = db.get(PurchaseOrder, case.po_id) if case.po_id else None
    payment = db.get(Payment, case.payment_id) if case.payment_id else None
    return {
        "id": case.id, "type": case.type, "status": case.status, "severity": case.severity,
        "invoice_id": case.invoice_id, "po_id": case.po_id, "payment_id": case.payment_id,
        "description": case.description,
        "evidence": [{"id": item.id, "record_type": item.record_type, "record_id": item.record_id, "note": item.note}
                     for item in evidence],
        "related": _related(invoice, po, payment),
    }


def list_exceptions(db: Session, exception_type: str | None = None, status: str | None = None,
                    severity: str | None = None) -> list[dict[str, Any]]:
    query = (
        select(ExceptionCase)
        .options(
            joinedload(ExceptionCase.invoice).joinedload(Invoice.vendor),
            joinedload(ExceptionCase.purchase_order),
            joinedload(ExceptionCase.payment),
        )
        .order_by(ExceptionCase.created_at, ExceptionCase.id)
    )
    if exception_type:
        query = query.where(ExceptionCase.type == exception_type)
    if status:
        query = query.where(ExceptionCase.status == status)
    if severity:
        query = query.where(ExceptionCase.severity == severity)
    cases = list(db.scalars(query))
    # load evidence for all cases in one query, then distribute
    all_evidence = list(db.scalars(
        select(Evidence).where(Evidence.exception_id.in_([c.id for c in cases])).order_by(Evidence.id)
    )) if cases else []
    evidence_by_case: dict[str, list[Evidence]] = {}
    for item in all_evidence:
        evidence_by_case.setdefault(item.exception_id, []).append(item)

    result = []
    for case in cases:
        evidence = evidence_by_case.get(case.id, [])
        invoice: Invoice | None = case.invoice
        po: PurchaseOrder | None = case.purchase_order
        payment: Payment | None = case.payment
        result.append({
            "id": case.id, "type": case.type, "status": case.status, "severity": case.severity,
            "invoice_id": case.invoice_id, "po_id": case.po_id, "payment_id": case.payment_id,
            "description": case.description,
            "evidence": [{"id": item.id, "record_type": item.record_type, "record_id": item.record_id, "note": item.note}
                         for item in evidence],
            "related": _related(invoice, po, payment),
        })
    return result


def get_exception(db: Session, exception_id: str) -> dict[str, Any] | None:
    case = db.get(ExceptionCase, exception_id)
    return _serialize_case(db, case) if case else None
