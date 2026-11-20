from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.config import get_settings
from app.database import Base, get_db
from app.main import create_app
from app.models import Adjustment, ExceptionCase, Invoice, PurchaseOrder, User, Vendor
from app.services.approvals import ensure_approval_steps
from scripts.seed_users import seed_demo_users

_TEST_HASHES = {
    "admin_u": hash_password("AdminPass123!"),
    "analyst_u": hash_password("AnalystPass123!"),
    "approver_u": hash_password("ApproverPass123!"),
    "auditor_u": hash_password("AuditorPass123!"),
}


@pytest.fixture
def auth_client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-only-signing-secret-for-pytest-32b")
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
            User(username="admin_u", password_hash=_TEST_HASHES["admin_u"], role="admin"),
            User(username="analyst_u", password_hash=_TEST_HASHES["analyst_u"], role="analyst"),
            User(username="approver_u", password_hash=_TEST_HASHES["approver_u"], role="approver"),
            User(username="auditor_u", password_hash=_TEST_HASHES["auditor_u"], role="auditor"),
        ])
        db.commit()

    client = TestClient(app)
    yield client, session_factory
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _token(client: TestClient, username: str, password: str) -> str:
    res = client.post("/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _seed_adjustment(session_factory) -> str:
    from datetime import date

    with session_factory() as db:
        vendor = Vendor(id="v-auth", name="Acme", normalized_name="acme")
        inv = Invoice(
            id="inv-auth", vendor_id="v-auth", invoice_number="INV-A1", po_number="PO-A1",
            amount=Decimal("50.00"), currency="USD", invoice_date=date(2026, 1, 1),
            source_file="test.csv", raw_row={}, dedupe_hash="hash-auth-1",
        )
        po = PurchaseOrder(
            id="po-auth", vendor_id="v-auth", po_number="PO-A1", amount=Decimal("40.00"),
            currency="USD", order_date=date(2026, 1, 1), raw_row={},
        )
        case = ExceptionCase(
            id="exc-auth", type="AMOUNT_MISMATCH", severity="medium",
            invoice_id="inv-auth", po_id="po-auth", description="mismatch",
        )
        adj = Adjustment(
            id="adj-auth", exception_id="exc-auth", proposed_amount=Decimal("10.00"),
            calculation_json={
                "record_ids": ["inv-auth", "po-auth"],
                "amounts": {"inv-auth": "50.00", "po-auth": "40.00"},
                "formula": "invoice - po",
                "result": "10.00",
            },
            status="pending",
        )
        db.add_all([vendor, inv, po, case, adj])
        db.flush()
        ensure_approval_steps(db, adj)
        db.commit()
        return adj.id


def test_unauthenticated_requests_return_401(auth_client):
    client, _ = auth_client
    assert client.get("/health").status_code == 200
    for path in ("/summary", "/matching/results", "/exceptions", "/adjustments", "/audit", "/agent/runs", "/auth/me"):
        assert client.get(path).status_code == 401


def test_login_json_and_form_and_me(auth_client):
    client, _ = auth_client
    bad = client.post("/auth/login", json={"username": "analyst_u", "password": "wrong"})
    assert bad.status_code == 401

    res_json = client.post("/auth/login", json={"username": "analyst_u", "password": "AnalystPass123!"})
    assert res_json.status_code == 200
    body = res_json.json()
    assert body["user"] == {"id": body["user"]["id"], "username": "analyst_u", "role": "analyst"}

    res_form = client.post("/auth/login", data={"username": "approver_u", "password": "ApproverPass123!"})
    assert res_form.status_code == 200

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["role"] == "analyst"


def test_rbac_role_enforcement_and_body_role_ignored(auth_client):
    client, session_factory = auth_client
    adj_id = _seed_adjustment(session_factory)
    analyst_tok = _token(client, "analyst_u", "AnalystPass123!")
    auditor_tok = _token(client, "auditor_u", "AuditorPass123!")
    approver_tok = _token(client, "approver_u", "ApproverPass123!")

    # Analyst cannot approve even if spoofing role="approver" in request body
    res_analyst = client.post(
        f"/adjustments/{adj_id}/decision",
        headers={"Authorization": f"Bearer {analyst_tok}"},
        json={"role": "approver", "decision": "approved", "comment": "spoof attempt"},
    )
    assert res_analyst.status_code == 403

    # Auditor is read-only
    assert client.get("/summary", headers={"Authorization": f"Bearer {auditor_tok}"}).status_code == 200
    assert client.post("/matching/run", headers={"Authorization": f"Bearer {auditor_tok}"}).status_code == 403
    assert client.post(
        f"/adjustments/{adj_id}/decision",
        headers={"Authorization": f"Bearer {auditor_tok}"},
        json={"decision": "approved"},
    ).status_code == 403

    # Approver succeeds (body role ignored), second call returns 409
    res_ok = client.post(
        f"/adjustments/{adj_id}/decision",
        headers={"Authorization": f"Bearer {approver_tok}"},
        json={"role": "bogus_role", "decision": "approved", "comment": "verified"},
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["status"] == "approved"

    res_repeat = client.post(
        f"/adjustments/{adj_id}/decision",
        headers={"Authorization": f"Bearer {approver_tok}"},
        json={"decision": "rejected"},
    )
    assert res_repeat.status_code == 409


def test_upload_limits_and_extension_validation(auth_client, monkeypatch):
    client, _ = auth_client
    analyst_tok = _token(client, "analyst_u", "AnalystPass123!")
    headers = {"Authorization": f"Bearer {analyst_tok}"}

    bad_type = client.post(
        "/imports/vendor",
        headers=headers,
        files={"file": ("malware.exe", b"not-a-csv", "application/octet-stream")},
    )
    assert bad_type.status_code == 400

    monkeypatch.setenv("MAX_UPLOAD_SIZE_BYTES", "16")
    get_settings.cache_clear()
    too_big = client.post(
        "/imports/vendor",
        headers=headers,
        files={"file": ("vendors.csv", b"name\n" + b"A" * 64, "text/csv")},
    )
    assert too_big.status_code == 413
    get_settings.cache_clear()


def test_audit_log_is_append_only(auth_client):
    client, _ = auth_client
    admin_tok = _token(client, "admin_u", "AdminPass123!")
    headers = {"Authorization": f"Bearer {admin_tok}"}
    assert client.put("/audit", headers=headers).status_code == 405
    assert client.patch("/audit", headers=headers).status_code == 405
    assert client.delete("/audit", headers=headers).status_code == 405


def test_docs_protected_in_production_and_open_in_development(auth_client, monkeypatch):
    client, _ = auth_client
    monkeypatch.setenv("APP_ENV", "production")
    assert client.get("/docs").status_code == 401
    assert client.get("/openapi.json").status_code == 401
    assert client.get("/summary").status_code == 401

    monkeypatch.setenv("APP_ENV", "development")
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/summary").status_code == 401


def test_cors_preflight_allows_localhost_and_127_blocks_evil(auth_client):
    client, _ = auth_client
    for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
        res = client.options(
            "/summary",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        assert res.status_code == 200
        assert res.headers.get("access-control-allow-origin") == origin

    evil = client.options(
        "/summary",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert evil.status_code == 400
    assert "access-control-allow-origin" not in evil.headers


def test_seed_script_creates_demo_users_from_env(db):
    env = {
        "DEMO_ADMIN_PASSWORD": "TestAdminPassword123!",
        "DEMO_ANALYST_PASSWORD": "TestAnalystPassword123!",
    }
    first = seed_demo_users(db, env=env)
    assert len(first["created"]) == 2
    assert len(first["skipped"]) == 2
    second = seed_demo_users(db, env=env)
    assert len(second["created"]) == 0
    assert len(second["updated"]) == 2
