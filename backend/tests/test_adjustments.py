from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import (
    Adjustment,
    AuditLog,
    Evidence,
    ExceptionCase,
    Invoice,
    Payment,
    PurchaseOrder,
    Vendor,
)
from app.services.adjustments import propose_adjustments
from app.services.approvals import ApprovalConflict, decide, required_roles
from app.services.exceptions.engine import run_exceptions


def _prepare(db) -> None:
    from tests.test_exceptions import _import_and_match

    _import_and_match(db)
    run_exceptions(db)


def test_calculations_and_ids_are_decimal_safe(db):
    _prepare(db)
    adjustments = propose_adjustments(db)
    by_type = {
        db.get(ExceptionCase, adjustment.exception_id).type: adjustment
        for adjustment in adjustments
    }

    assert by_type["PARTIAL_PAYMENT"].proposed_amount == Decimal("10.00")
    assert by_type["OVERPAYMENT"].proposed_amount == Decimal("12.00")
    assert by_type["DUPLICATE_INVOICE"].proposed_amount == Decimal("28.24")
    assert by_type["MISSING_PO"].proposed_amount == Decimal("0.00")
    assert by_type["DATE_GAP"].calculation_json["note"] == "review required"
    valid_ids = {
        *db.scalars(select(Vendor.id)),
        *db.scalars(select(Invoice.id)),
        *db.scalars(select(PurchaseOrder.id)),
        *db.scalars(select(Payment.id)),
    }
    assert all(
        record_id in valid_ids
        for adjustment in adjustments
        for record_id in adjustment.calculation_json["record_ids"]
    )


def test_routing_and_multi_step_order(db):
    _prepare(db)
    adjustments = propose_adjustments(db)
    by_amount = {adjustment.proposed_amount: adjustment for adjustment in adjustments}
    assert required_roles(Decimal(0)) == ["analyst"]
    assert required_roles(Decimal(10)) == ["analyst"]
    assert required_roles(Decimal(12)) == ["analyst"]
    assert required_roles(Decimal("100.01")) == ["manager"]
    assert required_roles(Decimal("1000.01")) == ["manager", "finance_director"]
    large = by_amount[Decimal("0.00")]
    assert len(large.calculation_json["record_ids"]) >= 1


def test_invalid_transitions_and_resolution_are_rejected_or_applied(db):
    _prepare(db)
    adjustments = propose_adjustments(db)
    partial = next(
        adjustment for adjustment in adjustments
        if db.get(ExceptionCase, adjustment.exception_id).type == "PARTIAL_PAYMENT"
    )
    with pytest.raises(ApprovalConflict, match="required role is analyst"):
        decide(db, partial.id, "manager", "approved", None)
    decide(db, partial.id, "analyst", "approved", "confirmed")
    assert partial.status == "approved"
    assert db.get(ExceptionCase, partial.exception_id).status == "resolved"
    with pytest.raises(ApprovalConflict, match="approved state"):
        decide(db, partial.id, "analyst", "rejected", None)


def test_large_approval_requires_manager_then_finance_director(db):
    vendor = Vendor(id="v", name="Vendor", normalized_name="vendor")
    invoice = Invoice(
        id="i", vendor_id="v", invoice_number="I", amount=Decimal(1500),
        currency="USD", invoice_date=__import__("datetime").date(2026, 1, 1),
        source_file="test", raw_row={}, dedupe_hash="hash",
    )
    case = ExceptionCase(
        id="e", type="AMOUNT_MISMATCH", severity="high", invoice_id="i",
        description="difference",
    )
    po = PurchaseOrder(
        id="p", vendor_id="v", po_number="P", amount=Decimal(0),
        currency="USD", order_date=__import__("datetime").date(2026, 1, 1), raw_row={},
    )
    db.add_all([vendor, invoice, case, po])
    db.add(Evidence(exception_id="e", record_type="invoice", record_id="i", note="invoice"))
    db.add(Evidence(exception_id="e", record_type="purchase_order", record_id="p", note="po"))
    db.commit()
    adjustment = propose_adjustments(db)[0]
    assert required_roles(adjustment.proposed_amount) == ["manager", "finance_director"]
    with pytest.raises(ApprovalConflict, match="required role is manager"):
        decide(db, adjustment.id, "finance_director", "approved", None)
    decide(db, adjustment.id, "manager", "approved", "approved")
    assert adjustment.status == "pending"
    decide(db, adjustment.id, "finance_director", "approved", "approved")
    assert adjustment.status == "approved"


def test_propose_is_idempotent_and_transitions_are_audited(db):
    _prepare(db)
    first = propose_adjustments(db)
    second = propose_adjustments(db)
    assert len(first) == len(second) == 7
    assert db.query(Adjustment).count() == 7
    partial = next(
        adjustment for adjustment in first
        if db.get(ExceptionCase, adjustment.exception_id).type == "PARTIAL_PAYMENT"
    )
    decide(db, partial.id, "analyst", "rejected", "not approved")
    assert partial.status == "rejected"
    assert db.query(AuditLog).filter(AuditLog.action == "adjustment_proposed").count() == 7
    assert db.query(AuditLog).filter(AuditLog.action == "approval_decision").count() == 1
