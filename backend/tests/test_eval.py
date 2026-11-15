from datetime import date
from decimal import Decimal

from app.models import Invoice, Match, Payment, PurchaseOrder, Vendor
from evals.run_eval import _matching_metrics


def test_matching_expected_set_does_not_derive_from_matcher_output(db):
    vendor = Vendor(id="ven-1", name="Vendor", normalized_name="vendor")
    invoice = Invoice(
        id="inv-1", vendor_id="ven-1", invoice_number="INV-1", po_number="PO-1",
        amount=Decimal("10.00"), currency="USD", invoice_date=date(2026, 1, 1),
        source_file="invoices.csv", raw_row={}, dedupe_hash="hash-1",
    )
    order = PurchaseOrder(
        id="po-1", vendor_id="ven-1", po_number="PO-1", amount=Decimal("10.00"),
        currency="USD", order_date=date(2026, 1, 1), raw_row={},
    )
    payment = Payment(
        id="pay-1", vendor_id="ven-1", reference="PAY-1", amount=Decimal("10.00"),
        currency="USD", payment_date=date(2026, 1, 2), raw_row={},
    )
    db.add_all([vendor, invoice, order, payment])
    db.add(Match(
        invoice_id="inv-1", po_id="po-from-matcher", tier="fuzzy",
        confidence=Decimal("0.5"), matched_amount=Decimal("1.00"),
    ))
    db.commit()

    metrics = _matching_metrics(db, {"errors": []})

    assert metrics["expected_count"] == 2
    assert metrics["actual_count"] == 1
    assert metrics["precision"] == 0
    assert metrics["recall"] == 0
