from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook

from app.models import AuditLog, Invoice, Payment, PurchaseOrder, Vendor
from app.services.importer import _read_file, compute_dedupe_hash, import_records


def test_importer_rejects_bad_rows_and_audits_valid_rows(db):
    content = (
        b"vendor_name,invoice_number,amount,currency,invoice_date,due_date\n"
        b"Acme Ltd,INV-1,12.50,usd,2026-01-01,2026-01-31\n"
        b"Broken,INV-2,-1,USD,not-a-date,2026-01-31\n"
    )
    result = import_records(db, "invoice", "invoices.csv", content, actor="tester")
    assert result["imported"] == 1
    assert result["rejected"] == 1
    assert db.query(Invoice).count() == 1
    assert db.query(Vendor).one().normalized_name == "acmeltd"
    assert db.query(AuditLog).count() == 2


def test_dedupe_hash_is_normalized_and_deterministic():
    first = compute_dedupe_hash("Acme Ltd", " INV-1 ", Decimal("12.50"), __import__("datetime").date(2026, 1, 1))
    second = compute_dedupe_hash("ACME-LTD", "INV-1", Decimal("12.50"), __import__("datetime").date(2026, 1, 1))
    assert first == second


def test_vendor_import_then_related_records_succeed_and_is_idempotent(db):
    vendors = b"id,name\nven-000000,Acme Ltd\nven-000001,Bravo Inc\n"
    vendor_result = import_records(db, "vendor", "vendors.csv", vendors, actor="tester")
    duplicate_result = import_records(db, "vendor", "vendors.csv", vendors, actor="tester")

    assert vendor_result["imported"] == 2
    assert vendor_result["rejected"] == 0
    assert duplicate_result["imported"] == 0
    assert duplicate_result["rejected"] == 2
    assert duplicate_result["duplicates"] == 2
    assert [error["errors"][0] for error in duplicate_result["errors"]] == [
        "duplicate of ven-000000",
        "duplicate of ven-000001",
    ]
    assert db.query(Vendor).count() == 2

    purchase_orders = (
        b"id,vendor_id,po_number,amount,currency,order_date\n"
        b"po-1,ven-000000,PO-1,12.50,USD,2026-01-01\n"
    )
    invoices = (
        b"id,vendor_id,invoice_number,po_number,amount,currency,invoice_date\n"
        b"inv-1,ven-000000,INV-1,PO-1,12.50,USD,2026-01-02\n"
    )
    payments = (
        b"id,vendor_id,reference,amount,currency,payment_date\n"
        b"pay-1,ven-000000,PAY-1,12.50,USD,2026-01-03\n"
    )
    assert import_records(db, "purchase_order", "purchase_orders.csv", purchase_orders)["rejected"] == 0
    assert import_records(db, "invoice", "invoices.csv", invoices)["rejected"] == 0
    assert import_records(db, "payment", "payments.csv", payments)["rejected"] == 0
    assert db.query(PurchaseOrder).count() == 1
    assert db.query(Invoice).count() == 1
    assert db.query(Payment).count() == 1


def test_purchase_order_before_vendor_is_rejected(db):
    content = b"vendor_id,po_number,amount,currency,order_date\nven-000000,PO-1,12.50,USD,2026-01-01\n"
    result = import_records(db, "purchase_order", "purchase_orders.csv", content)
    assert result["imported"] == 0
    assert result["rejected"] == 1
    assert "unknown vendor_id: ven-000000" in result["errors"][0]["errors"][0]


def test_reimporting_clean_file_reports_duplicates_without_new_rows(db):
    vendors = b"id,name\nven-000000,Acme Ltd\n"
    purchase_orders = b"id,vendor_id,po_number,amount,currency,order_date\npo-1,ven-000000,PO-1,12.50,USD,2026-01-01\n"
    import_records(db, "vendor", "vendors.csv", vendors)
    first = import_records(db, "purchase_order", "purchase_orders.csv", purchase_orders)
    second = import_records(db, "purchase_order", "purchase_orders.csv", purchase_orders)

    assert first["imported"] == 1
    assert second["imported"] == 0
    assert second["rejected"] == 1
    assert second["duplicates"] == 1
    assert second["errors"] == [{"row": 2, "errors": ["duplicate of po-1"]}]
    assert db.query(PurchaseOrder).count() == 1


def test_bad_rows_are_isolated_from_valid_rows(db):
    import_records(db, "vendor", "vendors.csv", b"id,name\nven-000000,Acme Ltd\n")
    content = (
        b"id,vendor_id,po_number,amount,currency,order_date\n"
        b"po-bad-amount,ven-000000,PO-BAD-AMOUNT,abc,USD,2026-01-01\n"
        b"po-missing-field,ven-000000,,12.50,USD,2026-01-01\n"
        b"po-bad-date,ven-000000,PO-BAD-DATE,12.50,USD,not-a-date\n"
        b"po-valid-1,ven-000000,PO-VALID-1,12.50,USD,2026-01-01\n"
        b"po-valid-2,ven-000000,PO-VALID-2,15.00,USD,2026-01-02\n"
    )
    result = import_records(db, "purchase_order", "purchase_orders.csv", content)

    assert result["imported"] == 2
    assert result["rejected"] == 3
    assert result["duplicates"] == 0
    assert [error["row"] for error in result["errors"]] == [2, 3, 4]
    assert db.query(PurchaseOrder).count() == 2


def test_xlsx_formulas_are_imported_as_text():
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["value"])
    worksheet.append(["=1+1"])
    content = BytesIO()
    workbook.save(content)

    frame = _read_file("values.xlsx", content.getvalue())

    assert frame.iloc[0, 0] == "=1+1"
