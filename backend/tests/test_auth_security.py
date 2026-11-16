import secrets
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import create_access_token, hash_password
from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models import Adjustment, ApprovalStep, AuditLog, ExceptionCase, User


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", secrets.token_urlsafe(32))
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _user(db, username: str, role: str) -> User:
    user = User(username=username, password_hash=hash_password("password-12345"), role=role)
    db.add(user)
    db.commit()
    return user


def _token(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def test_missing_token_returns_401(client):
    response = client.get("/summary")
    assert response.status_code == 401
    assert response.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("origin", ["http://127.0.0.1:5173", "http://localhost:5173"])
def test_allowed_cors_preflight_returns_origin(client, origin):
    response = client.options(
        "/summary",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == origin


def test_disallowed_cors_preflight_returns_400(client):
    response = client.options(
        "/summary",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    assert response.status_code == 400


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_require_authentication_in_production(client, monkeypatch, path):
    monkeypatch.setenv("APP_ENV", "production")
    assert client.get(path).status_code == 401


def test_docs_load_without_authentication_in_development(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger-ui" in response.text


@pytest.mark.parametrize("app_env", ["production", "development"])
def test_data_endpoints_require_authentication_in_all_environments(client, monkeypatch, app_env):
    monkeypatch.setenv("APP_ENV", app_env)
    assert client.get("/summary").status_code == 401


def test_openapi_declares_authentication_for_protected_endpoints(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    schema = client.get("/openapi.json").json()
    scheme = schema["components"]["securitySchemes"]["OAuth2PasswordBearer"]
    assert scheme == {
        "type": "oauth2",
        "flows": {"password": {"scopes": {}, "tokenUrl": "/login"}},
    }
    assert schema["paths"]["/summary"]["get"]["security"] == [{"OAuth2PasswordBearer": []}]


def test_analyst_cannot_approve_and_approver_ignores_body_role(client, db):
    analyst = _user(db, "analyst", "analyst")
    approver = _user(db, "approver", "approver")
    case = ExceptionCase(type="PARTIAL_PAYMENT", severity="low", description="test")
    db.add(case)
    db.flush()
    adjustment = Adjustment(
        exception_id=case.id,
        proposed_amount=Decimal("10.00"),
        calculation_json={},
        status="pending",
    )
    db.add(adjustment)
    db.flush()
    db.add(ApprovalStep(
        adjustment_id=adjustment.id,
        approver_role="analyst",
        decision="pending",
    ))
    db.commit()

    denied = client.post(
        f"/adjustments/{adjustment.id}/decision",
        headers=_token(analyst),
        json={"role": "approver", "decision": "approved"},
    )
    assert denied.status_code == 403

    approved = client.post(
        f"/adjustments/{adjustment.id}/decision",
        headers=_token(approver),
        json={"role": "analyst", "decision": "approved"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert db.query(AuditLog).filter(AuditLog.action == "approval_decision").one().actor == "approver (approver)"


def test_login_returns_signed_token(client, db):
    user = User(username="login-user", password_hash=hash_password("password-12345"), role="auditor")
    db.add(user)
    db.commit()
    response = client.post("/login", json={"username": "login-user", "password": "password-12345"})
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    form_response = client.post(
        "/login",
        data={"username": "login-user", "password": "password-12345"},
    )
    assert form_response.status_code == 200
    assert form_response.json()["token_type"] == "bearer"


def test_upload_type_and_size_limits(client, db, monkeypatch):
    analyst = _user(db, "upload-analyst", "analyst")
    headers = _token(analyst)
    wrong_type = client.post(
        "/imports/vendor",
        headers=headers,
        files={"file": ("payload.exe", b"not an executable", "application/octet-stream")},
    )
    assert wrong_type.status_code == 400

    monkeypatch.setenv("UPLOAD_MAX_BYTES", "10")
    get_settings.cache_clear()
    oversized = client.post(
        "/imports/vendor",
        headers=headers,
        files={"file": ("payload.csv", b"01234567890", "text/csv")},
    )
    assert oversized.status_code == 413
    get_settings.cache_clear()


def test_audit_log_has_no_update_or_delete_api(client, db):
    auditor = _user(db, "auditor", "auditor")
    headers = _token(auditor)
    assert client.put("/audit/anything", headers=headers, json={}).status_code in {404, 405}
    assert client.delete("/audit/anything", headers=headers).status_code in {404, 405}


def test_repo_does_not_contain_real_secret_values():
    root = Path(__file__).parents[2]
    excluded = {".git", ".venv", "node_modules", "__pycache__"}
    for path in root.rglob("*"):
        if not path.is_file() or any(part in excluded for part in path.parts):
            continue
        if path.suffix.casefold() not in {".py", ".ts", ".tsx", ".js", ".jsx", ".env"}:
            continue
        if path.name in {".env.example", "package.json", "package-lock.json"}:
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        assert ("s" + "k-") not in content
        assert ("-----BEGIN " + "PRIVATE KEY-----") not in content
