from decimal import Decimal

from app.models import Invoice, Payment, PurchaseOrder
from app.services.matching.common import MatchDecision


def exact_purchase_order(invoice: Invoice, orders: list[PurchaseOrder]) -> list[MatchDecision]:
    if not invoice.po_number:
        return []
    candidates = [
        order
        for order in orders
        if order.vendor_id == invoice.vendor_id
        and order.po_number.casefold() == invoice.po_number.casefold()
        and order.amount == invoice.amount
        and order.currency == invoice.currency
    ]
    if len(candidates) != 1:
        return []
    order = candidates[0]
    return [MatchDecision(invoice, order, "purchase_order", "exact", Decimal(1), invoice.amount,
                          "invoice.po_number + vendor_id + amount + currency exact")]


def exact_payment(invoice: Invoice, payments: list[Payment]) -> list[MatchDecision]:
    candidates = [
        payment
        for payment in payments
        if payment.vendor_id == invoice.vendor_id
        and payment.reference.casefold() == invoice.invoice_number.casefold()
        and payment.amount == invoice.amount
        and payment.currency == invoice.currency
    ]
    if len(candidates) != 1:
        return []
    payment = candidates[0]
    return [MatchDecision(invoice, payment, "payment", "exact", Decimal(1),
                          min(invoice.amount, payment.amount),
                          "invoice_number + vendor_id + amount + currency exact")]
