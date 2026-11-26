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


def test_evaluation_report_endpoint_requires_auth_and_returns_metrics(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.auth.security import hash_password
    from app.config import get_settings
    from app.database import Base, get_db
    from app.main import create_app
    from app.models import User

    monkeypatch.setenv("JWT_SECRET", "test-only-eval-endpoint-secret-32b")
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
        db.add(User(username="eval_auditor", password_hash=hash_password("EvalAuditorPass123!"), role="auditor"))
        db.commit()

    client = TestClient(app)
    assert client.get("/evaluation/report").status_code == 401

    token = client.post(
        "/auth/login",
        json={"username": "eval_auditor", "password": "EvalAuditorPass123!"},
    ).json()["access_token"]
    res = client.get("/evaluation/report", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    body = res.json()
    assert body["matching"]["precision"] == 1.0
    assert body["hallucination_rate"] == 0.0
    assert body["extraction_accuracy"] == 1.0
    assert "total_amount" in body["extraction_by_field"]
    app.dependency_overrides.clear()
    get_settings.cache_clear()
