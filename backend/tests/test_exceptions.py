import json
from pathlib import Path

from sqlalchemy import select

from app.models import (
    AuditLog,
    Evidence,
    ExceptionCase,
    Invoice,
    Payment,
    PurchaseOrder,
    Vendor,
)
from app.services.exceptions.engine import list_exceptions, run_exceptions
from app.services.importer import import_records
from app.services.matching.engine import run_matching


def _import_and_match(db) -> None:
    data = Path(__file__).parents[1] / "data"
    for record_type, filename in (
        ("vendor", "vendors.csv"),
        ("purchase_order", "purchase_orders.csv"),
        ("invoice", "invoices.csv"),
        ("payment", "payments.csv"),
    ):
        import_records(db, record_type, filename, (data / filename).read_bytes())
    run_matching(db)


def test_detected_exceptions_match_ground_truth_without_false_positives(db):
    _import_and_match(db)
    run_exceptions(db)
    truth = json.loads((Path(__file__).parents[1] / "data" / "ground_truth.json").read_text())

    actual = {
        (
            case.type,
            frozenset(item.record_id for item in db.scalars(
                select(Evidence).where(Evidence.exception_id == case.id)
            )),
        )
        for case in db.scalars(select(ExceptionCase))
    }
    expected = {
        (
            "VENDOR_MISMATCH" if error["type"] == "VENDOR_NAME_TYPO" else error["type"],
            frozenset(error["record_ids"].values()),
        )
        for error in truth["errors"]
    }

    assert actual == expected
    assert not expected - actual
    assert not actual - expected


def test_every_evidence_record_id_exists_in_database(db):
    _import_and_match(db)
    run_exceptions(db)
    valid_ids = {
        *db.scalars(select(Vendor.id)),
        *db.scalars(select(Invoice.id)),
        *db.scalars(select(PurchaseOrder.id)),
        *db.scalars(select(Payment.id)),
    }

    assert db.query(ExceptionCase).count() == 9
    assert db.query(AuditLog).filter(AuditLog.action == "exception_created").count() == 9
    assert db.query(Evidence).count() >= db.query(ExceptionCase).count()
    assert all(item.record_id in valid_ids for item in db.scalars(select(Evidence)))


def test_exception_list_includes_related_records(db):
    _import_and_match(db)
    run_exceptions(db)
    results = list_exceptions(db)
    assert results, "expected at least one exception"
    for item in results:
        assert "related" in item, f"missing 'related' key on exception {item['id']}"
        related = item["related"]
        assert "invoice" in related
        assert "purchase_order" in related
        assert "payment" in related
    # find the PARTIAL_PAYMENT exception and verify its related fields are populated
    partial = next((item for item in results if item["type"] == "PARTIAL_PAYMENT"), None)
    assert partial is not None
    assert partial["related"]["invoice"] is not None
    assert partial["related"]["invoice"]["invoice_number"]
    assert partial["related"]["invoice"]["vendor_name"]
    assert partial["related"]["invoice"]["amount"]
    assert partial["related"]["payment"] is not None
    assert partial["related"]["payment"]["amount"]
    assert partial["related"]["payment"]["payment_date"]
    # MISSING_PO has no payment on ExceptionCase FK, so payment related should be None
    missing_po = next((item for item in results if item["type"] == "MISSING_PO"), None)
    assert missing_po is not None
    assert missing_po["related"]["payment"] is None


def test_exception_run_is_idempotent(db):
    _import_and_match(db)

    first = run_exceptions(db)
    second = run_exceptions(db)

    assert first.created == 9
    assert second.created == 0
    assert second.existing == 9
    assert db.query(ExceptionCase).count() == 9
    assert db.query(Evidence).count() == 14
