"""Tests for Reconcilr Enhancements:
1. Document Navigation & Category Extracted Data
2. AI Actionable Suggestions & Accept Functionality
3. User Registration, Authentication & Security
"""

import io
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient

from app.auth import create_access_token, hash_password
from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models import (
    AISuggestion,
    ExceptionCase,
    Invoice,
    Match,
    Payment,
    PurchaseOrder,
    UploadedDocument,
    User,
    Vendor,
)


@pytest.fixture
def test_client(db, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-32-chars-long-minimum!")
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        get_settings.cache_clear()


def _create_user(db, username="jane_analyst", role="analyst") -> User:
    user = User(
        username=username,
        password_hash=hash_password("securepassword123"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    return user


def _auth_header(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


# =========================================================================
# 1. Authentication & Registration Tests
# =========================================================================

def test_user_registration_success(test_client, db):
    payload = {
        "username": "new_user_1",
        "password": "validpassword123",
        "role": "analyst",
    }
    res = test_client.post("/register", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == "new_user_1"
    assert data["role"] == "analyst"
    assert "access_token" in data
    assert data["token_type"] == "bearer"

    # Verify user in database
    db_user = db.query(User).filter(User.username == "new_user_1").first()
    assert db_user is not None
    assert db_user.role == "analyst"


def test_user_registration_duplicate_rejected(test_client, db):
    _create_user(db, "duplicate_user")
    res = test_client.post(
        "/register",
        json={"username": "duplicate_user", "password": "password123", "role": "analyst"},
    )
    assert res.status_code == 409
    assert "already taken" in res.json()["detail"]


def test_user_registration_validation(test_client):
    # Too short password
    res1 = test_client.post(
        "/register",
        json={"username": "valid_user", "password": "123", "role": "analyst"},
    )
    assert res1.status_code in {400, 422}

    # Invalid role
    res2 = test_client.post(
        "/register",
        json={"username": "valid_user", "password": "validpassword", "role": "superman"},
    )
    assert res2.status_code == 400


def test_login_and_logout_flow(test_client, db):
    user = _create_user(db, "login_test_user")
    login_res = test_client.post(
        "/login",
        json={"username": "login_test_user", "password": "securepassword123"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    # Call /me with token
    me_res = test_client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["username"] == "login_test_user"

    # Logout
    logout_res = test_client.post("/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_res.status_code == 200


# =========================================================================
# 2. Document Navigation & Categories Tests
# =========================================================================

def test_document_categories_retrieval(test_client, db):
    user = _create_user(db, "doc_analyst")
    headers = _auth_header(user)

    # Seed vendor, invoice, PO, payment
    vendor = Vendor(name="Global Supplies Inc", normalized_name="globalsuppliesinc")
    db.add(vendor)
    db.flush()

    inv = Invoice(
        user_id=user.id,
        vendor_id=vendor.id,
        invoice_number="INV-GS-100",
        po_number="PO-GS-200",
        amount=Decimal("1500.00"),
        currency="USD",
        invoice_date=pytest.importorskip("datetime").date(2026, 2, 1),
        due_date=pytest.importorskip("datetime").date(2026, 3, 1),
        source_file="invoice_gs.pdf",
        raw_row={"tax_amount": "150.00"},
        dedupe_hash="hash_inv_gs_100",
    )
    po = PurchaseOrder(
        user_id=user.id,
        vendor_id=vendor.id,
        po_number="PO-GS-200",
        amount=Decimal("1500.00"),
        currency="USD",
        order_date=pytest.importorskip("datetime").date(2026, 1, 15),
        source_file="po_gs.pdf",
        raw_row={"description": "Office IT Equipment", "quantity": "5", "unit_price": "300.00"},
    )
    pay = Payment(
        user_id=user.id,
        vendor_id=vendor.id,
        reference="PAY-GS-300",
        amount=Decimal("1500.00"),
        currency="USD",
        payment_date=pytest.importorskip("datetime").date(2026, 2, 20),
        source_file="bank_feed.csv",
        raw_row={"payment_method": "ACH Transfer", "invoice_reference": "INV-GS-100"},
    )
    db.add_all([inv, po, pay])
    db.commit()

    # 1. Test Invoice Category
    res_inv = test_client.get("/documents/categories/invoice", headers=headers)
    assert res_inv.status_code == 200
    data_inv = res_inv.json()
    assert data_inv["category"] == "invoice"
    assert "invoice_gs.pdf" in data_inv["files"]
    assert len(data_inv["records"]) >= 1
    first_inv = next(r for r in data_inv["records"] if r["invoice_number"] == "INV-GS-100")
    assert first_inv["vendor_name"] == "Global Supplies Inc"
    assert first_inv["total_amount"] == "1500.00"
    assert first_inv["tax_amount"] == "150.00"

    # 2. Test PO Category
    res_po = test_client.get("/documents/categories/purchase_order", headers=headers)
    assert res_po.status_code == 200
    data_po = res_po.json()
    assert data_po["category"] == "purchase_order"
    assert "po_gs.pdf" in data_po["files"]
    first_po = next(r for r in data_po["records"] if r["po_number"] == "PO-GS-200")
    assert first_po["item_description"] == "Office IT Equipment"
    assert first_po["quantity"] == "5"

    # 3. Test Payment Category
    res_pay = test_client.get("/documents/categories/payment", headers=headers)
    assert res_pay.status_code == 200
    data_pay = res_pay.json()
    assert data_pay["category"] == "payment"
    first_pay = next(r for r in data_pay["records"] if r["payment_reference"] == "PAY-GS-300")
    assert first_pay["payment_method"] == "ACH Transfer"
    assert first_pay["invoice_reference"] == "INV-GS-100"


def test_document_upload_csv(test_client, db):
    user = _create_user(db, "upload_user")
    headers = _auth_header(user)

    # Upload vendor first
    vendor_csv = "id,name,normalized_name\nven-upl,Upload Vendor,uploadvendor\n"
    test_client.post(
        "/imports/vendor",
        headers=headers,
        files={"file": ("vendors.csv", io.BytesIO(vendor_csv.encode()), "text/csv")},
    )

    csv_data = (
        "id,vendor_id,invoice_number,po_number,amount,currency,invoice_date,due_date\n"
        "inv-u1,ven-upl,INV-UPL-001,PO-UPL-001,850.00,USD,2026-03-01,2026-03-31\n"
    )
    res = test_client.post(
        "/documents/upload",
        headers=headers,
        data={"category": "invoice"},
        files={"file": ("upload_invoices.csv", io.BytesIO(csv_data.encode()), "text/csv")},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert res.json()["imported_count"] == 1


# =========================================================================
# 3. AI Suggestions & Actionable Accept Tests
# =========================================================================

def test_ai_suggestions_generation_and_accept_match(test_client, db):
    user = _create_user(db, "ai_analyst", role="analyst")
    headers = _auth_header(user)

    vendor = Vendor(name="Delta Services", normalized_name="deltaservices")
    db.add(vendor)
    db.flush()

    # Invoice and PO with identical amounts that are not yet matched
    inv = Invoice(
        user_id=user.id,
        vendor_id=vendor.id,
        invoice_number="INV-DELTA-1",
        amount=Decimal("3200.00"),
        currency="USD",
        invoice_date=pytest.importorskip("datetime").date(2026, 2, 10),
        source_file="delta.csv",
        raw_row={},
        dedupe_hash="hash_delta_1",
    )
    po = PurchaseOrder(
        user_id=user.id,
        vendor_id=vendor.id,
        po_number="PO-DELTA-1",
        amount=Decimal("3200.00"),
        currency="USD",
        order_date=pytest.importorskip("datetime").date(2026, 2, 5),
        source_file="delta_po.csv",
        raw_row={},
    )
    db.add_all([inv, po])
    db.commit()

    # Generate suggestions
    gen_res = test_client.post("/ai/generate", headers=headers)
    assert gen_res.status_code == 200
    suggestions = gen_res.json()
    assert len(suggestions) >= 1

    # Find the match suggestion
    match_sugg = next((s for s in suggestions if s["kind"] == "match_invoice_po"), None)
    assert match_sugg is not None
    assert match_sugg["status"] == "pending"

    # Accept the suggestion
    sugg_id = match_sugg["id"]
    accept_res = test_client.post(
        f"/ai/suggestions/{sugg_id}/accept",
        headers=headers,
        json={"note": "Approved match by analyst"},
    )
    assert accept_res.status_code == 200
    acc_data = accept_res.json()
    assert acc_data["status"] == "accepted"
    assert "match_id" in acc_data

    # Verify Match record exists in database
    match = db.query(Match).filter(Match.invoice_id == inv.id, Match.po_id == po.id).first()
    assert match is not None
    assert match.matched_amount == Decimal("3200.00")

    # Double accept returns 409 Conflict
    conflict_res = test_client.post(
        f"/ai/suggestions/{sugg_id}/accept",
        headers=headers,
        json={},
    )
    assert conflict_res.status_code == 409


def test_ai_suggestion_accept_amount_discrepancy(test_client, db):
    user = _create_user(db, "discrepancy_analyst")
    headers = _auth_header(user)

    vendor = Vendor(name="Apex Parts", normalized_name="apexparts")
    db.add(vendor)
    db.flush()

    inv = Invoice(
        user_id=user.id,
        vendor_id=vendor.id,
        invoice_number="INV-APEX-1",
        po_number="PO-APEX-1",
        amount=Decimal("500.00"),
        currency="USD",
        invoice_date=pytest.importorskip("datetime").date(2026, 2, 12),
        source_file="apex.csv",
        raw_row={},
        dedupe_hash="hash_apex_1",
    )
    po = PurchaseOrder(
        user_id=user.id,
        vendor_id=vendor.id,
        po_number="PO-APEX-1",
        amount=Decimal("450.00"),
        currency="USD",
        order_date=pytest.importorskip("datetime").date(2026, 2, 10),
        source_file="apex_po.csv",
        raw_row={},
    )
    db.add_all([inv, po])
    db.commit()

    test_client.post("/ai/generate", headers=headers)
    get_res = test_client.get("/ai/suggestions", headers=headers)
    assert get_res.status_code == 200
    suggestions = get_res.json()

    disc_sugg = next((s for s in suggestions if s["kind"] == "amount_discrepancy"), None)
    assert disc_sugg is not None

    # Accept the discrepancy review suggestion
    acc_res = test_client.post(
        f"/ai/suggestions/{disc_sugg['id']}/accept",
        headers=headers,
        json={"note": "Initiating price adjustment"},
    )
    assert acc_res.status_code == 200
    assert "exception_id" in acc_res.json()

    # Verify ExceptionCase created
    exc = db.query(ExceptionCase).filter(ExceptionCase.type == "AMOUNT_MISMATCH").first()
    assert exc is not None


def test_ai_suggestion_reject(test_client, db):
    user = _create_user(db, "reject_analyst")
    headers = _auth_header(user)

    sugg = AISuggestion(
        user_id=user.id,
        kind="missing_po",
        record_ids=["fake-1"],
        payload={"action": "test"},
        score=Decimal("0.85"),
        reason="Test missing PO",
        source="test",
        status="pending",
    )
    db.add(sugg)
    db.commit()

    rej_res = test_client.post(f"/ai/suggestions/{sugg.id}/reject", headers=headers, json={})
    assert rej_res.status_code == 200
    assert rej_res.json()["status"] == "rejected"
