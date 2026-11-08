from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.models import Invoice, Match, Payment, PurchaseOrder
from app.services.audit import write_audit
from app.services.matching.common import MatchDecision
from app.services.matching.exact import exact_payment, exact_purchase_order
from app.services.matching.fuzzy import fuzzy_payment, fuzzy_purchase_order
from app.services.matching.tolerance import tolerance_payment, tolerance_purchase_order


@dataclass(frozen=True)
class MatchResult:
    created: int
    existing: int
    unmatched_invoice_ids: list[str]
    tier_counts: dict[str, int]


def _duplicate_invoice_ids(invoices: list[Invoice]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for invoice in sorted(invoices, key=lambda item: item.id):
        if invoice.dedupe_hash in seen:
            duplicates.add(invoice.id)
        else:
            seen.add(invoice.dedupe_hash)
    return duplicates


def _existing_match(db: Session, decision: MatchDecision) -> Match | None:
    filters: list[Any] = [Match.invoice_id == decision.invoice.id]
    if decision.counterpart_type == "purchase_order":
        filters.append(Match.po_id == decision.counterpart.id)
    else:
        filters.append(Match.payment_id == decision.counterpart.id)
    return db.scalar(select(Match).where(*filters))


def _audit_decision(db: Session, decision: MatchDecision | None, invoice: Invoice, output: dict[str, Any]) -> None:
    inputs: dict[str, Any] = {
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "vendor_id": invoice.vendor_id,
        "amount": str(invoice.amount),
    }
    if decision is not None:
        inputs["counterpart_id"] = decision.counterpart.id
        inputs["counterpart_type"] = decision.counterpart_type
        formula = decision.rule
    else:
        formula = "Ordered tiers evaluated; no unambiguous counterpart selected"
    write_audit(
        db, actor=get_settings().audit_actor, action="match_decision", entity_type="Invoice",
        entity_id=invoice.id, inputs=inputs, formula=formula, output=output,
    )


def _choose(
    invoice: Invoice,
    counterpart_type: str,
    candidates: list[PurchaseOrder] | list[Payment],
    settings: Any,
) -> MatchDecision | None:
    if counterpart_type == "purchase_order":
        tiers = (
            exact_purchase_order(invoice, candidates),
            tolerance_purchase_order(invoice, candidates, settings.matching_amount_tolerance_absolute,
                                     settings.matching_amount_tolerance_percentage, settings.matching_date_tolerance_days),
            fuzzy_purchase_order(invoice, candidates, settings.matching_fuzzy_minimum_score),
        )
    else:
        tiers = (
            exact_payment(invoice, candidates),
            tolerance_payment(invoice, candidates, settings.matching_amount_tolerance_absolute,
                              settings.matching_amount_tolerance_percentage, settings.matching_date_tolerance_days),
            fuzzy_payment(invoice, candidates, settings.matching_fuzzy_minimum_score),
        )
    for tier in tiers:
        if tier:
            return tier[0]
    return None


def run_matching(db: Session) -> MatchResult:
    settings = get_settings()
    invoices = list(db.scalars(select(Invoice).options(joinedload(Invoice.vendor)).order_by(Invoice.id)))
    orders = list(db.scalars(select(PurchaseOrder).options(joinedload(PurchaseOrder.vendor)).order_by(PurchaseOrder.id)))
    payments = list(db.scalars(select(Payment).options(joinedload(Payment.vendor)).order_by(Payment.id)))
    duplicate_ids = _duplicate_invoice_ids(invoices)
    used_orders: set[str] = set()
    used_payments: set[str] = set()
    created = 0
    existing = 0
    unmatched: list[str] = []
    tier_counts = {"exact": 0, "tolerance": 0, "fuzzy": 0}

    for invoice in invoices:
        if invoice.id in duplicate_ids:
            unmatched.append(invoice.id)
            _audit_decision(db, None, invoice, {"status": "unmatched", "reason": "duplicate_invoice"})
            continue
        decisions: list[MatchDecision] = []
        order = _choose(invoice, "purchase_order", [item for item in orders if item.id not in used_orders], settings)
        if order is not None:
            used_orders.add(order.counterpart.id)
            decisions.append(order)
        payment = _choose(invoice, "payment", [item for item in payments if item.id not in used_payments], settings)
        if payment is not None:
            used_payments.add(payment.counterpart.id)
            decisions.append(payment)
        if not decisions:
            unmatched.append(invoice.id)
            _audit_decision(db, None, invoice, {"status": "unmatched"})
            continue
        for decision in decisions:
            match = _existing_match(db, decision)
            if match is None:
                db.add(Match(
                    invoice_id=decision.invoice.id,
                    po_id=decision.counterpart.id if decision.counterpart_type == "purchase_order" else None,
                    payment_id=decision.counterpart.id if decision.counterpart_type == "payment" else None,
                    tier=decision.tier,
                    confidence=decision.confidence,
                    matched_amount=decision.matched_amount,
                ))
                created += 1
            else:
                existing += 1
            tier_counts[decision.tier] += 1
            _audit_decision(db, decision, invoice, {
                "status": "matched", "tier": decision.tier, "confidence": str(decision.confidence),
                "matched_amount": str(decision.matched_amount),
            })
    db.commit()
    return MatchResult(created, existing, unmatched, tier_counts)


def list_matches(db: Session) -> list[dict[str, Any]]:
    matches = list(db.scalars(select(Match).order_by(Match.created_at, Match.id)))
    return [
        {
            "id": match.id,
            "invoice_id": match.invoice_id,
            "po_id": match.po_id,
            "payment_id": match.payment_id,
            "tier": match.tier,
            "confidence": float(Decimal(match.confidence)),
            "matched_amount": str(match.matched_amount),
        }
        for match in matches
    ]
