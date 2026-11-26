import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.config import get_settings
from app.database import Base, get_db
from app.main import create_app
from app.models import AuditLog, Invoice, User
from app.services.importer import import_records

_ANALYST_HASH = hash_password("AnalystMapPass123!")
_AUDITOR_HASH = hash_password("AuditorMapPass123!")


@pytest.fixture
def mapped_client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-only-mapped-import-secret-32b")
    monkeypatch.setenv("APP_ENV", "production")
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
            User(username="map_analyst", password_hash=_ANALYST_HASH, role="analyst"),
            User(username="map_auditor", password_hash=_AUDITOR_HASH, role="auditor"),
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


def test_preview_suggests_known_columns_and_reports_unmapped_required(mapped_client):
    client, _ = mapped_client
    headers = _login(client, "map_analyst", "AnalystMapPass123!")
    csv_bytes = (
        b"Supplier Name,Bill Number,Weird Amt Col,CCY,Issue Date,Extra\n"
        b"Acme Corp,INV-9001,\"1,250.50\",USD,2026-03-10,note\n"
    )
    res = client.post(
        "/import/preview",
        headers=headers,
        data={"record_type": "invoice"},
        files={"file": ("custom.csv", csv_bytes, "text/csv")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["columns"] == ["Supplier Name", "Bill Number", "Weird Amt Col", "CCY", "Issue Date", "Extra"]
    assert len(body["preview_rows"]) == 1
    assert body["suggested_mapping"]["vendor_name"] == "Supplier Name"
    assert body["suggested_mapping"]["invoice_number"] == "Bill Number"
    assert body["suggested_mapping"]["currency"] == "CCY"
    assert body["suggested_mapping"]["invoice_date"] == "Issue Date"
    # Never silently guess unrecognized columns
    assert "amount" not in body["suggested_mapping"]
    assert body["missing_required_fields"] == ["amount"]


def test_mapped_import_custom_columns_thousands_separator_and_bad_amount(mapped_client):
    client, session_factory = mapped_client
    headers = _login(client, "map_analyst", "AnalystMapPass123!")
    csv_bytes = (
        b"Supplier Name,Bill Number,Weird Amt Col,CCY,Issue Date,PO Ref\n"
        b"Acme Corp,INV-9001,\"1,250.50\",usd,2026-03-10,PO-9001\n"
        b"Acme Corp,INV-9002,not-a-number,USD,2026-03-11,PO-9002\n"
        b"Acme Corp,INV-9001,\"1,250.50\",USD,2026-03-10,PO-9001\n"
    )
    mapping = {
        "vendor_name": "Supplier Name",
        "invoice_number": "Bill Number",
        "amount": "Weird Amt Col",
        "currency": "CCY",
        "invoice_date": "Issue Date",
        "po_number": "PO Ref",
    }
    res = client.post(
        "/import/mapped",
        headers=headers,
        data={"record_type": "invoice", "mapping": json.dumps(mapping), "date_format": "auto"},
        files={"file": ("real_invoices.csv", csv_bytes, "text/csv")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["imported"] == 1
    assert body["duplicates"] == 1
    assert body["rejected"] == 1
    assert body["rejected_rows"][0]["row"] == 3
    assert "Invalid amount" in body["rejected_rows"][0]["reason"]

    with session_factory() as db:
        inv = db.scalar(select(Invoice))
        assert inv is not None
        assert inv.amount == Decimal("1250.50")
        assert inv.currency == "USD"
        assert inv.invoice_date == date(2026, 3, 10)
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "mapped_import"))
        assert audit is not None
        assert audit.output["imported"] == 1


def test_ambiguous_date_flagged_not_guessed_and_explicit_format_succeeds(mapped_client):
    client, session_factory = mapped_client
    headers = _login(client, "map_analyst", "AnalystMapPass123!")
    csv_bytes = (
        b"Vendor,InvNo,Amt,Curr,Dt\n"
        b"Acme Corp,INV-AMB-1,500.00,USD,03/04/2026\n"
    )
    mapping = {
        "vendor_name": "Vendor",
        "invoice_number": "InvNo",
        "amount": "Amt",
        "currency": "Curr",
        "invoice_date": "Dt",
    }
    res_auto = client.post(
        "/import/mapped",
        headers=headers,
        data={"record_type": "invoice", "mapping": json.dumps(mapping), "date_format": "auto"},
        files={"file": ("amb.csv", csv_bytes, "text/csv")},
    )
    assert res_auto.status_code == 200
    assert res_auto.json()["imported"] == 0
    assert res_auto.json()["rejected"] == 1
    assert "Ambiguous date" in res_auto.json()["rejected_rows"][0]["reason"]

    res_dmy = client.post(
        "/import/mapped",
        headers=headers,
        data={"record_type": "invoice", "mapping": json.dumps(mapping), "date_format": "DD/MM/YYYY"},
        files={"file": ("amb.csv", csv_bytes, "text/csv")},
    )
    assert res_dmy.status_code == 200
    assert res_dmy.json()["imported"] == 1
    with session_factory() as db:
        inv = db.scalar(select(Invoice).where(Invoice.invoice_number == "INV-AMB-1"))
        assert inv is not None
        assert inv.invoice_date == date(2026, 4, 3)


def test_mapped_import_auth_and_existing_csv_unchanged(mapped_client, db):
    client, _ = mapped_client
    csv_bytes = b"vendor_name,invoice_number,amount,currency,invoice_date\nAcme,INV-1,10.00,USD,2026-01-01\n"
    assert client.post(
        "/import/preview",
        data={"record_type": "invoice"},
        files={"file": ("inv.csv", csv_bytes, "text/csv")},
    ).status_code == 401

    auditor_headers = _login(client, "map_auditor", "AuditorMapPass123!")
    assert client.post(
        "/import/preview",
        headers=auditor_headers,
        data={"record_type": "invoice"},
        files={"file": ("inv.csv", csv_bytes, "text/csv")},
    ).status_code == 403

    res = import_records(db, "invoice", "inv.csv", csv_bytes)
    assert res["imported"] == 1
    assert res["rejected"] == 0
