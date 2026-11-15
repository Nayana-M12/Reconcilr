from __future__ import annotations

from datetime import date
from itertools import combinations
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.similarity import compare_text
from app.models import Invoice, Vendor, VendorAlias


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
            "record_ids": [left.id, right.id],
            "left_id": left.id,
            "right_id": right.id,
            "left_name": left.name,
            "right_name": right.name,
            "score": result.score,
            "reason": result.reason,
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
            "record_ids": [left.id, right.id],
            "left_id": left.id,
            "right_id": right.id,
            "score": score,
            "reason": (
                f"Same vendor/amount; invoice numbers are {number_result.reason.lower()} "
                f"and dates are {abs((left.invoice_date - right.invoice_date).days)} day(s) apart."
            ),
            "source": number_result.source,
        })
    return suggestions


def verify_record_ids(db: Session, record_ids: list[str]) -> bool:
    for record_id in record_ids:
        if db.get(Invoice, record_id) is None and db.get(Vendor, record_id) is None:
            return False
    return True
