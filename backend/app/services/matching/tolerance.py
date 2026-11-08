from decimal import Decimal

from app.models import Invoice, Payment, PurchaseOrder
from app.services.matching.common import (
    MatchDecision,
    within_amount_tolerance,
    within_date_days,
)


def _confidence(invoice_amount: Decimal, counterpart_amount: Decimal) -> Decimal:
    if invoice_amount == counterpart_amount:
        return Decimal("0.98")
    return max(Decimal("0.50"), Decimal(1) - abs(invoice_amount - counterpart_amount) / invoice_amount)


def tolerance_purchase_order(
    invoice: Invoice, orders: list[PurchaseOrder], absolute: Decimal, percentage: Decimal, days: int
) -> list[MatchDecision]:
    if not invoice.po_number:
        return []
    candidates = [
        order for order in orders
        if order.vendor_id == invoice.vendor_id and order.currency == invoice.currency
        and within_amount_tolerance(invoice.amount, order.amount, absolute, percentage)
        and within_date_days(invoice.invoice_date, order.order_date, days)
    ]
    if len(candidates) != 1:
        return []
    order = candidates[0]
    return [MatchDecision(invoice, order, "purchase_order", "tolerance",
                          _confidence(invoice.amount, order.amount), min(invoice.amount, order.amount),
                          "same vendor; amount absolute/percentage tolerance; date tolerance")]


def tolerance_payment(
    invoice: Invoice, payments: list[Payment], absolute: Decimal, percentage: Decimal, days: int
) -> list[MatchDecision]:
    candidates = [
        payment for payment in payments
        if payment.vendor_id == invoice.vendor_id and payment.currency == invoice.currency
        and within_amount_tolerance(invoice.amount, payment.amount, absolute, percentage)
        and within_date_days(invoice.invoice_date, payment.payment_date, days)
    ]
    if len(candidates) != 1:
        return []
    payment = candidates[0]
    return [MatchDecision(invoice, payment, "payment", "tolerance",
                          _confidence(invoice.amount, payment.amount), min(invoice.amount, payment.amount),
                          "same vendor; amount absolute/percentage tolerance; date tolerance")]
