from decimal import Decimal

from rapidfuzz.fuzz import ratio

from app.models import Invoice, Payment, PurchaseOrder
from app.services.matching.common import MatchDecision


def _vendor_score(invoice: Invoice, counterpart: PurchaseOrder | Payment) -> float:
    invoice_name = invoice.vendor.name if invoice.vendor else invoice.vendor_id
    counterpart_name = counterpart.vendor.name if counterpart.vendor else counterpart.vendor_id
    return ratio(invoice_name, counterpart_name)


def _decision(invoice: Invoice, counterpart: PurchaseOrder | Payment, score: float, rule: str) -> MatchDecision:
    return MatchDecision(invoice, counterpart, "payment" if isinstance(counterpart, Payment) else "purchase_order",
                         "fuzzy", Decimal(str(round(score / 100, 4))),
                         min(invoice.amount, counterpart.amount), rule)


def fuzzy_purchase_order(invoice: Invoice, orders: list[PurchaseOrder], minimum_score: int) -> list[MatchDecision]:
    if not invoice.po_number:
        return []
    scored = [
        (order, (_vendor_score(invoice, order) + ratio(invoice.po_number, order.po_number)) / 2)
        for order in orders if order.vendor_id == invoice.vendor_id
    ]
    eligible = [(order, score) for order, score in scored if score >= minimum_score]
    if not eligible:
        return []
    best_score = max(score for _, score in eligible)
    best = [(order, score) for order, score in eligible if score == best_score]
    if len(best) != 1:
        return []
    order, score = best[0]
    return [_decision(invoice, order, score, "RapidFuzz vendor and PO reference score above minimum")]


def fuzzy_payment(invoice: Invoice, payments: list[Payment], minimum_score: int) -> list[MatchDecision]:
    scored = [
        (payment, (_vendor_score(invoice, payment) + ratio(invoice.invoice_number, payment.reference)) / 2)
        for payment in payments if payment.vendor_id == invoice.vendor_id
    ]
    eligible = [(payment, score) for payment, score in scored if score >= minimum_score]
    if not eligible:
        return []
    best_score = max(score for _, score in eligible)
    best = [(payment, score) for payment, score in eligible if score == best_score]
    if len(best) != 1:
        return []
    payment, score = best[0]
    return [_decision(invoice, payment, score, "RapidFuzz vendor and payment reference score above minimum")]
