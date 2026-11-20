from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.config import get_settings
from app.database import Base, get_db
from app.extraction import DocumentReadError, parse_document, read_document_text
from app.main import create_app
from app.models import AuditLog, Invoice, Payment, PurchaseOrder, User
from app.services.importer import import_records
from evals.run_eval import _extraction_metrics

FIXTURES = Path(__file__).parent / "fixtures" / "documents"
_ANALYST_HASH = hash_password("AnalystDocPass123!")
_AUDITOR_HASH = hash_password("AuditorDocPass123!")


@pytest.fixture
def doc_client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-only-doc-extraction-secret-32b")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("EXTRACTION_OCR", raising=False)
    get_settings.cache_clear()

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    app = create_app()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with session_factory() as db:
        db.add_all([
            User(username="doc_analyst", password_hash=_ANALYST_HASH, role="analyst"),
            User(username="doc_auditor", password_hash=_AUDITOR_HASH, role="auditor"),
        ])
        db.commit()

    client = TestClient(app)
    yield client, session_factory
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    res = client.post("/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_pdf_and_txt_extraction_produces_exact_decimals_and_provenance():
    pdf_path = FIXTURES / "invoice_acme.pdf"
    pages = read_document_text(pdf_path.name, pdf_path.read_bytes())
    extracted = parse_document(pages)

    assert extracted.is_complete
    assert extracted.document_type == "invoice"
    assert extracted.document_number == "INV-DOC-1001"
    assert extracted.vendor == "Acme Corp"
    assert extracted.document_date.isoformat() == "2026-02-14"
    assert extracted.currency == "USD"
    assert isinstance(extracted.total_amount, Decimal)
    assert extracted.total_amount == Decimal("1250.75")
    assert extracted.po_reference == "PO-DOC-1001"
    for field in ("document_type", "document_number", "vendor", "date", "currency", "total_amount", "po_reference"):
        prov = extracted.provenance[field]
        assert prov.page == 1
        assert prov.snippet
        assert 0 < prov.confidence <= 1.0


def test_missing_amount_goes_to_needs_review_and_is_not_imported(doc_client):
    client, session_factory = doc_client
    headers = _login(client, "doc_analyst", "AnalystDocPass123!")
    missing_path = FIXTURES / "invoice_missing_amount.txt"

    res = client.post(
        "/import/document",
        headers=headers,
        files=[("files", (missing_path.name, missing_path.read_bytes(), "text/plain"))],
    )
    assert res.status_code == 200
    body = res.json()
    assert body["imported"] == []
    assert len(body["needs_review"]) == 1
    review = body["needs_review"][0]
    assert review["fields_missing"] == ["total_amount"]
    assert review["fields_found"]["document_number"] == "INV-DOC-1002"
    assert "vendor" in review["provenance"]

    with session_factory() as db:
        assert db.query(Invoice).count() == 0
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "document_import"))
        assert audit is not None
        assert audit.output["outcome"] == "needs_review"


def test_complete_documents_import_and_duplicate_is_reported(doc_client):
    client, session_factory = doc_client
    headers = _login(client, "doc_analyst", "AnalystDocPass123!")
    files = [
        ("files", ("purchase_order_acme.txt", (FIXTURES / "purchase_order_acme.txt").read_bytes(), "text/plain")),
        ("files", ("invoice_acme.pdf", (FIXTURES / "invoice_acme.pdf").read_bytes(), "application/pdf")),
        ("files", ("invoice_duplicate.pdf", (FIXTURES / "invoice_duplicate.pdf").read_bytes(), "application/pdf")),
        ("files", ("payment_advice_acme.pdf", (FIXTURES / "payment_advice_acme.pdf").read_bytes(), "application/pdf")),
    ]
    res = client.post("/import/document", headers=headers, files=files)
    assert res.status_code == 200
    body = res.json()
    assert len(body["imported"]) == 3
    assert len(body["duplicates"]) == 1
    assert body["duplicates"][0]["filename"] == "invoice_duplicate.pdf"
    assert body["needs_review"] == []
    assert body["unsupported"] == []

    with session_factory() as db:
        assert db.query(PurchaseOrder).count() == 1
        assert db.query(Invoice).count() == 1
        assert db.query(Payment).count() == 1
        assert db.scalar(select(Invoice)).amount == Decimal("1250.75")


def test_scanned_pdf_and_unsupported_files_return_clear_messages(doc_client):
    client, _ = doc_client
    headers = _login(client, "doc_analyst", "AnalystDocPass123!")
    blank_pdf = FIXTURES / "scanned_blank.pdf"
    res = client.post(
        "/import/document",
        headers=headers,
        files=[
            ("files", (blank_pdf.name, blank_pdf.read_bytes(), "application/pdf")),
            ("files", ("photo.png", b"\x89PNG\r\n\x1a\n", "image/png")),
            ("files", ("archive.zip", b"PK\x03\x04", "application/zip")),
        ],
    )
    assert res.status_code == 200
    unsupported = res.json()["unsupported"]
    assert len(unsupported) == 3
    assert "OCR not enabled" in unsupported[0]["message"]
    assert "OCR not enabled" in unsupported[1]["message"]
    assert "Unsupported file type" in unsupported[2]["message"]

    with pytest.raises(DocumentReadError, match="OCR not enabled"):
        read_document_text("scanned_blank.pdf", blank_pdf.read_bytes())


def test_document_import_enforces_auth_and_csv_import_unchanged(doc_client, db):
    client, _ = doc_client
    assert client.post(
        "/import/document",
        files=[("files", ("purchase_order_acme.txt", (FIXTURES / "purchase_order_acme.txt").read_bytes(), "text/plain"))],
    ).status_code == 401

    auditor_headers = _login(client, "doc_auditor", "AuditorDocPass123!")
    assert client.post(
        "/import/document",
        headers=auditor_headers,
        files=[("files", ("purchase_order_acme.txt", (FIXTURES / "purchase_order_acme.txt").read_bytes(), "text/plain"))],
    ).status_code == 403

    csv_content = (
        b"vendor_name,invoice_number,amount,currency,invoice_date\n"
        b"Acme Corp,INV-CSV-1,50.00,USD,2026-02-01\n"
    )
    csv_res = import_records(db, "invoice", "invoices.csv", csv_content)
    assert csv_res["imported"] == 1
    assert csv_res["rejected"] == 0


def test_extraction_evaluation_reports_per_field_accuracy():
    metrics = _extraction_metrics()
    assert metrics["status"] == "evaluated"
    assert metrics["overall_accuracy"] == 1.0
    assert metrics["by_field"]["total_amount"]["accuracy"] == 1.0
    assert metrics["by_field"]["document_number"]["accuracy"] == 1.0
