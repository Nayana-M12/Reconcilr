from __future__ import annotations

from datetime import date
from decimal import Decimal
from itertools import combinations
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.similarity import compare_text
from app.models import (
    AISuggestion,
    ExceptionCase,
    Invoice,
    Match,
    Payment,
    PurchaseOrder,
    Vendor,
    VendorAlias,
)


def vendor_candidate_ids(db: Session, vendor_id: str) -> set[str]:
    ids = {vendor_id}
    aliases = db.scalars(
        select(VendorAlias).where(
            (VendorAlias.vendor_id == vendor_id) | (VendorAlias.alias_vendor_id == vendor_id)
        )
    )
    for alias in aliases:
        ids.add(alias.vendor_id)
        ids.add(alias.alias_vendor_id)
    return ids


def suggest_vendor_aliases(db: Session, threshold: float = 0.78) -> list[dict[str, Any]]:
    vendors = list(db.scalars(select(Vendor).order_by(Vendor.id)))
    suggestions: list[dict[str, Any]] = []
    for left, right in combinations(vendors, 2):
        result = compare_text(left.name, right.name, "vendor")
        if result.score < threshold:
            continue
        suggestions.append({
            "kind": "vendor_alias",
            "action": "accept_vendor_alias",
            "record_ids": [left.id, right.id],
            "left_id": left.id,
            "right_id": right.id,
            "left_name": left.name,
            "right_name": right.name,
            "score": result.score,
            "reason": f"Discrepancy in vendor name: '{left.name}' and '{right.name}' appear to be the same entity.",
            "source": result.source,
        })
    return suggestions


def _date_similarity(left: date, right: date) -> float:
    days = abs((left - right).days)
    return max(0.0, 1.0 - days / 30)


def suggest_near_duplicates(db: Session, threshold: float = 0.78) -> list[dict[str, Any]]:
    invoices = list(db.scalars(select(Invoice).order_by(Invoice.id)))
    by_vendor: dict[str, set[str]] = {}
    for invoice in invoices:
        by_vendor.setdefault(invoice.vendor_id, set()).add(invoice.vendor_id)
        by_vendor[invoice.vendor_id].update(vendor_candidate_ids(db, invoice.vendor_id))
    suggestions: list[dict[str, Any]] = []
    for left, right in combinations(invoices, 2):
        if left.dedupe_hash == right.dedupe_hash or left.amount != right.amount:
            continue
        if right.vendor_id not in by_vendor.get(left.vendor_id, {left.vendor_id}):
            continue
        number_result = compare_text(left.invoice_number, right.invoice_number, "invoice")
        date_score = _date_similarity(left.invoice_date, right.invoice_date)
        score = round(number_result.score * 0.8 + date_score * 0.2, 4)
        if score < threshold:
            continue
        suggestions.append({
            "kind": "near_duplicate",
            "action": "flag_duplicate",
            "record_ids": [left.id, right.id],
            "left_id": left.id,
            "right_id": right.id,
            "score": score,
            "reason": (
                f"Potential duplicate invoice detected: #{left.invoice_number} and #{right.invoice_number} "
                f"have identical amount (${left.amount}) and dates {abs((left.invoice_date - right.invoice_date).days)} day(s) apart."
            ),
            "source": number_result.source,
        })
    return suggestions


def suggest_unmatched_invoice_po(db: Session) -> list[dict[str, Any]]:
    """Identify invoices without matching POs and suggest matching when possible."""
    matched_inv_ids = {m.invoice_id for m in db.scalars(select(Match))}
    matched_po_ids = {m.po_id for m in db.scalars(select(Match)) if m.po_id}

    invoices = list(db.scalars(select(Invoice).where(Invoice.id.not_in(matched_inv_ids))))
    purchase_orders = list(db.scalars(select(PurchaseOrder).where(PurchaseOrder.id.not_in(matched_po_ids))))

    suggestions: list[dict[str, Any]] = []
    for inv in invoices:
        for po in purchase_orders:
            # Check vendor match
            if inv.vendor_id == po.vendor_id or (inv.po_number and inv.po_number.casefold() == po.po_number.casefold()):
                diff = abs(inv.amount - po.amount)
                if diff == Decimal(0):
                    suggestions.append({
                        "kind": "match_invoice_po",
                        "action": "execute_match",
                        "record_ids": [inv.id, po.id],
                        "invoice_id": inv.id,
                        "po_id": po.id,
                        "invoice_number": inv.invoice_number,
                        "po_number": po.po_number,
                        "vendor_name": inv.vendor.name if inv.vendor else "Vendor",
                        "amount": str(inv.amount),
                        "score": 0.96,
                        "reason": f"Suggest matching Invoice #{inv.invoice_number} with PO #{po.po_number} (Vendor: {inv.vendor.name if inv.vendor else 'Vendor'}, Amount: ${inv.amount}).",
                        "source": "reconciliation_rules",
                    })
                    break
                elif diff <= Decimal("5.00"):
                    suggestions.append({
                        "kind": "match_invoice_po",
                        "action": "execute_match",
                        "record_ids": [inv.id, po.id],
                        "invoice_id": inv.id,
                        "po_id": po.id,
                        "invoice_number": inv.invoice_number,
                        "po_number": po.po_number,
                        "vendor_name": inv.vendor.name if inv.vendor else "Vendor",
                        "amount": str(inv.amount),
                        "score": 0.88,
                        "reason": f"Invoice #{inv.invoice_number} matches PO #{po.po_number} within tolerance (Diff: ${diff}). Suggest confirming match.",
                        "source": "tolerance_rules",
                    })
                    break
    return suggestions


def suggest_amount_discrepancies(db: Session) -> list[dict[str, Any]]:
    """Identify discrepancies between invoice amounts and PO amounts."""
    invoices = list(db.scalars(select(Invoice).where(Invoice.po_number.is_not(None))))
    po_map = {po.po_number.casefold(): po for po in db.scalars(select(PurchaseOrder))}

    suggestions: list[dict[str, Any]] = []
    for inv in invoices:
        if not inv.po_number:
            continue
        po = po_map.get(inv.po_number.casefold())
        if po and inv.amount != po.amount:
            diff = abs(inv.amount - po.amount)
            suggestions.append({
                "kind": "amount_discrepancy",
                "action": "review_discrepancy",
                "record_ids": [inv.id, po.id],
                "invoice_id": inv.id,
                "po_id": po.id,
                "invoice_number": inv.invoice_number,
                "po_number": po.po_number,
                "invoice_amount": str(inv.amount),
                "po_amount": str(po.amount),
                "difference": str(diff),
                "score": 0.91,
                "reason": f"Amount discrepancy: Invoice #{inv.invoice_number} (${inv.amount}) differs from PO #{po.po_number} (${po.amount}) by ${diff}. Suggest initiating review.",
                "source": "discrepancy_detector",
            })
    return suggestions


def suggest_overdue_payments(db: Session) -> list[dict[str, Any]]:
    """Identify overdue invoices without completed payments."""
    today = date.today()
    invoices = list(db.scalars(select(Invoice).where(Invoice.due_date.is_not(None))))

    # Find matched or paid invoice IDs
    matched_inv_ids = {m.invoice_id for m in db.scalars(select(Match)) if m.payment_id}

    suggestions: list[dict[str, Any]] = []
    for inv in invoices:
        if inv.id not in matched_inv_ids and inv.due_date and inv.due_date < today:
            days = (today - inv.due_date).days
            suggestions.append({
                "kind": "overdue_payment",
                "action": "flag_overdue",
                "record_ids": [inv.id],
                "invoice_id": inv.id,
                "invoice_number": inv.invoice_number,
                "vendor_name": inv.vendor.name if inv.vendor else "Vendor",
                "due_date": inv.due_date.isoformat(),
                "days_overdue": days,
                "amount": str(inv.amount),
                "score": 0.89,
                "reason": f"Invoice #{inv.invoice_number} is {days} days overdue (Due: {inv.due_date}, Amount: ${inv.amount}). Suggest following up on payment.",
                "source": "sla_tracker",
            })
    return suggestions


def suggest_missing_po(db: Session) -> list[dict[str, Any]]:
    """Identify invoices that do not have matching purchase orders or PO numbers."""
    matched_inv_ids = {m.invoice_id for m in db.scalars(select(Match)) if m.po_id}
    invoices = list(db.scalars(select(Invoice).where(Invoice.id.not_in(matched_inv_ids))))

    suggestions: list[dict[str, Any]] = []
    for inv in invoices:
        if not inv.po_number:
            suggestions.append({
                "kind": "missing_po",
                "action": "initiate_po_exception",
                "record_ids": [inv.id],
                "invoice_id": inv.id,
                "invoice_number": inv.invoice_number,
                "vendor_name": inv.vendor.name if inv.vendor else "Vendor",
                "amount": str(inv.amount),
                "score": 0.85,
                "reason": f"Invoice #{inv.invoice_number} from {inv.vendor.name if inv.vendor else 'Vendor'} (${inv.amount}) is missing a Purchase Order reference.",
                "source": "compliance_rules",
            })
    return suggestions


def suggest_mark_payment_completed(db: Session) -> list[dict[str, Any]]:
    """Suggest marking verified payments as completed when matched with invoice."""
    matches = list(db.scalars(select(Match).where(Match.payment_id.is_not(None))))
    suggestions: list[dict[str, Any]] = []

    for m in matches:
        if not m.payment_id:
            continue
        pay = db.get(Payment, m.payment_id)
        inv = db.get(Invoice, m.invoice_id)
        if pay and inv:
            raw = pay.raw_row or {}
            curr_status = (raw.get("payment_status") or raw.get("status") or "").casefold()
            if curr_status in {"pending", "unverified", "processing", ""}:
                suggestions.append({
                    "kind": "mark_payment_completed",
                    "action": "mark_payment_completed",
                    "record_ids": [pay.id, inv.id],
                    "payment_id": pay.id,
                    "invoice_id": inv.id,
                    "reference": pay.reference,
                    "invoice_number": inv.invoice_number,
                    "amount": str(pay.amount),
                    "score": 0.95,
                    "reason": f"Payment {pay.reference} (${pay.amount}) is verified against Invoice #{inv.invoice_number}. Suggest marking payment as Completed.",
                    "source": "verification_rules",
                })
    return suggestions


def suggest_high_value_approvals(db: Session, threshold: Decimal = Decimal("5000.00")) -> list[dict[str, Any]]:
    """Identify high-value invoices that require manager or director approval."""
    invoices = list(db.scalars(select(Invoice).where(Invoice.amount >= threshold)))
    suggestions: list[dict[str, Any]] = []
    for inv in invoices:
        suggestions.append({
            "kind": "high_value_approval",
            "action": "route_approval",
            "record_ids": [inv.id],
            "invoice_id": inv.id,
            "invoice_number": inv.invoice_number,
            "amount": str(inv.amount),
            "vendor_name": inv.vendor.name if inv.vendor else "Vendor",
            "score": 0.90,
            "reason": f"High-value invoice #{inv.invoice_number} (${inv.amount}) exceeds ${threshold} threshold. Suggest routing for formal approval.",
            "source": "governance_policy",
        })
    return suggestions


def generate_all_actionable_suggestions(db: Session) -> list[dict[str, Any]]:
    """Generate all contextual, actionable suggestions across the database."""
    all_candidates: list[dict[str, Any]] = []
    all_candidates.extend(suggest_unmatched_invoice_po(db))
    all_candidates.extend(suggest_amount_discrepancies(db))
    all_candidates.extend(suggest_overdue_payments(db))
    all_candidates.extend(suggest_missing_po(db))
    all_candidates.extend(suggest_mark_payment_completed(db))
    all_candidates.extend(suggest_high_value_approvals(db))
    all_candidates.extend(suggest_vendor_aliases(db))
    all_candidates.extend(suggest_near_duplicates(db))
    return all_candidates


def verify_record_ids(db: Session, record_ids: list[str]) -> bool:
    for record_id in record_ids:
        if (
            db.get(Invoice, record_id) is None
            and db.get(Vendor, record_id) is None
            and db.get(PurchaseOrder, record_id) is None
            and db.get(Payment, record_id) is None
        ):
            return False
    return True
