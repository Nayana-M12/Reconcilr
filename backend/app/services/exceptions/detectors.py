from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from app.config import Settings
from app.models import Invoice, Match, Payment, PurchaseOrder

RecordType = Literal["invoice", "purchase_order", "payment", "vendor"]


@dataclass(frozen=True)
class ExceptionFinding:
    type: str
    invoice_id: str | None = None
    po_id: str | None = None
    payment_id: str | None = None
    description: str = ""
    amount_difference: Decimal = Decimal(0)
    evidence: tuple[tuple[RecordType, str, str], ...] = field(default_factory=tuple)


def _duplicate_invoice_findings(invoices: list[Invoice]) -> list[ExceptionFinding]:
    groups: dict[tuple[object, ...], list[Invoice]] = {}
    for invoice in invoices:
        key = (invoice.dedupe_hash, invoice.vendor_id, invoice.invoice_number.casefold(),
               invoice.amount, invoice.invoice_date)
        groups.setdefault(key, []).append(invoice)
    findings = []
    for group in groups.values():
        ordered = sorted(group, key=lambda item: item.id)
        for duplicate in ordered[1:]:
            findings.append(ExceptionFinding(
                "DUPLICATE_INVOICE", invoice_id=duplicate.id,
                description=f"Invoice duplicates {ordered[0].id}",
                evidence=(
                    ("invoice", ordered[0].id, "Canonical invoice with the same dedupe identity"),
                    ("invoice", duplicate.id, "Duplicate invoice with the same dedupe identity"),
                ),
            ))
    return findings


def _duplicate_payment_findings(payments: list[Payment]) -> list[ExceptionFinding]:
    groups: dict[tuple[object, ...], list[Payment]] = {}
    for payment in payments:
        key = (payment.vendor_id, payment.reference.casefold(), payment.amount,
               payment.currency, payment.payment_date)
        groups.setdefault(key, []).append(payment)
    findings = []
    for group in groups.values():
        ordered = sorted(group, key=lambda item: item.id)
        for duplicate in ordered[1:]:
            findings.append(ExceptionFinding(
                "DUPLICATE_PAYMENT", payment_id=duplicate.id,
                description=f"Payment duplicates {ordered[0].id}",
                evidence=(
                    ("payment", ordered[0].id, "Canonical payment with the same payment identity"),
                    ("payment", duplicate.id, "Duplicate payment with the same payment identity"),
                ),
            ))
    return findings


def _payment_for_invoice(invoice: Invoice, payments: list[Payment]) -> Payment | None:
    target = invoice.invoice_number.casefold()
    candidates = [
        payment for payment in payments
        if payment.vendor_id == invoice.vendor_id
        and payment.reference.casefold().replace("pay", "inv", 1) == target
    ]
    return candidates[0] if len(candidates) == 1 else None


def detect_exceptions(
    invoices: list[Invoice],
    orders: list[PurchaseOrder],
    payments: list[Payment],
    matches: list[Match],
    settings: Settings,
) -> list[ExceptionFinding]:
    findings = _duplicate_invoice_findings(invoices)
    duplicate_invoice_ids = {finding.invoice_id for finding in findings}
    findings.extend(_duplicate_payment_findings(payments))
    linked: dict[str, list[Match]] = {}
    for match in matches:
        linked.setdefault(match.invoice_id, []).append(match)
    order_by_id = {order.id: order for order in orders}
    payment_by_id = {payment.id: payment for payment in payments}

    for invoice in invoices:
        if invoice.id in duplicate_invoice_ids:
            continue
        invoice_matches = linked.get(invoice.id, [])
        po_match = next((match for match in invoice_matches if match.po_id), None)
        payment_match = next((match for match in invoice_matches if match.payment_id), None)
        order = order_by_id.get(po_match.po_id) if po_match else None
        payment = payment_by_id.get(payment_match.payment_id) if payment_match else _payment_for_invoice(invoice, payments)

        if not invoice.po_number or order is None:
            evidence = (("invoice", invoice.id, "Invoice requiring a purchase order"),)
            if order:
                evidence += (("purchase_order", order.id, "Candidate purchase order"),)
            findings.append(ExceptionFinding(
                "MISSING_PO", invoice_id=invoice.id, po_id=order.id if order else None,
                description="Invoice has no purchase order match", evidence=evidence,
            ))
        if payment is None:
            evidence = (("invoice", invoice.id, "Invoice without a payment record"),)
            findings.append(ExceptionFinding(
                "MISSING_PAYMENT", invoice_id=invoice.id,
                description="Invoice has no payment record", evidence=evidence,
            ))
        if payment is not None:
            difference = payment.amount - invoice.amount
            if difference != 0:
                exception_type = "PARTIAL_PAYMENT" if difference < 0 else "OVERPAYMENT"
                findings.append(ExceptionFinding(
                    exception_type, invoice_id=invoice.id, payment_id=payment.id,
                    description=f"Payment differs from invoice by {abs(difference)}",
                    amount_difference=abs(difference),
                    evidence=(
                        ("invoice", invoice.id, "Invoice amount used for comparison"),
                        ("payment", payment.id, "Payment amount used for comparison"),
                    ),
                ))
            if invoice.due_date and abs((payment.payment_date - invoice.due_date).days) > settings.exception_date_gap_days:
                findings.append(ExceptionFinding(
                    "DATE_GAP", invoice_id=invoice.id, payment_id=payment.id,
                    description="Payment is outside the configured due-date window",
                    evidence=(
                        ("invoice", invoice.id, "Invoice due date"),
                        ("payment", payment.id, "Payment date"),
                    ),
                ))
        if order is not None:
            difference = abs(invoice.amount - order.amount)
            if difference > max(settings.matching_amount_tolerance_absolute,
                                invoice.amount * settings.matching_amount_tolerance_percentage):
                findings.append(ExceptionFinding(
                    "AMOUNT_MISMATCH", invoice_id=invoice.id, po_id=order.id,
                    description=f"Invoice and purchase order differ by {difference}",
                    amount_difference=difference,
                    evidence=(
                        ("invoice", invoice.id, "Invoice amount"),
                        ("purchase_order", order.id, "Purchase order amount"),
                    ),
                ))
        raw_vendor_name = invoice.raw_row.get("vendor_name")
        if raw_vendor_name and raw_vendor_name.casefold().strip() != invoice.vendor.name.casefold().strip():
            findings.append(ExceptionFinding(
                "VENDOR_MISMATCH", invoice_id=invoice.id,
                description="Invoice source vendor name differs from the vendor record",
                evidence=(
                    ("invoice", invoice.id, "Invoice raw vendor name"),
                    ("vendor", invoice.vendor_id, "Canonical vendor record name"),
                ),
            ))
    return findings
