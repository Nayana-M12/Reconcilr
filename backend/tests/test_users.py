import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import reset_request_access_rate_limit
from app.auth.security import hash_password
from app.config import get_settings
from app.database import Base, get_db
from app.main import create_app
from app.models import AuditLog, User

_ADMIN_HASH = hash_password("AdminSecret12345!")
_ANALYST_HASH = hash_password("AnalystSecret12345!")


@pytest.fixture
def users_client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-only-users-mgmt-secret-32b")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("REQUEST_ACCESS_RATE_LIMIT", "5")
    get_settings.cache_clear()
    reset_request_access_rate_limit()

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
            User(
                username="boss_admin",
                email="boss@reconcilr.local",
                password_hash=_ADMIN_HASH,
                role="admin",
                status="active",
                is_active=True,
                created_via="seed",
            ),
            User(
                username="staff_analyst",
                email="analyst@reconcilr.local",
                password_hash=_ANALYST_HASH,
                role="analyst",
                status="active",
                is_active=True,
                created_via="seed",
            ),
        ])
        db.commit()

    client = TestClient(app)
    yield client, session_factory
    app.dependency_overrides.clear()
    reset_request_access_rate_limit()
    get_settings.cache_clear()


def _login_headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    res = client.post("/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_request_access_creates_pending_user_ignores_role_and_blocks_login(users_client):
    client, session_factory = users_client
    # Short password rejected
    short_pw = client.post(
        "/auth/request-access",
        json={"username": "new_user", "email": "new@example.com", "password": "short"},
    )
    assert short_pw.status_code == 400

    # Valid request attempting to smuggle role="admin"
    res = client.post(
        "/auth/request-access",
        json={
            "username": "new_user",
            "email": "new@example.com",
            "password": "LongEnoughPassword123!",
            "role": "admin",
            "note": "Need analyst access",
        },
    )
    assert res.status_code == 202
    assert res.json()["message"] == "Request received. An administrator will review it."

    # Duplicate username returns identical generic response
    dup = client.post(
        "/auth/request-access",
        json={
            "username": "new_user",
            "email": "other@example.com",
            "password": "AnotherLongPassword123!",
        },
    )
    assert dup.status_code == 202
    assert dup.json() == res.json()

    # Pending user has hashed password, no role, cannot log in
    with session_factory() as db:
        user = db.scalar(select(User).where(User.username == "new_user"))
        assert user is not None
        assert user.role is None
        assert user.status == "pending"
        assert user.is_active is False
        assert user.password_hash != "LongEnoughPassword123!"
        assert user.password_hash.startswith("$2")

    login_attempt = client.post(
        "/auth/login",
        json={"username": "new_user", "password": "LongEnoughPassword123!"},
    )
    assert login_attempt.status_code == 403
    assert "awaiting approval" in login_attempt.json()["detail"].lower()


def test_non_admin_forbidden_and_admin_approval_enables_login(users_client):
    client, session_factory = users_client
    analyst_headers = _login_headers(client, "staff_analyst", "AnalystSecret12345!")
    admin_headers = _login_headers(client, "boss_admin", "AdminSecret12345!")

    # Non-admin gets 403 on admin endpoints
    assert client.get("/admin/users", headers=analyst_headers).status_code == 403
    assert client.post(
        "/admin/users",
        headers=analyst_headers,
        json={"username": "xuser", "password": "LongEnoughPassword123!", "role": "auditor"},
    ).status_code == 403

    # Request access then approve as analyst
    client.post(
        "/auth/request-access",
        json={
            "username": "pending_u",
            "email": "pending@example.com",
            "password": "PendingPassword123!",
        },
    )
    pending_list = client.get("/admin/users?status=pending", headers=admin_headers).json()
    assert len(pending_list) == 1
    user_id = pending_list[0]["id"]

    assert client.post(
        f"/admin/users/{user_id}/approve",
        headers=analyst_headers,
        json={"role": "analyst"},
    ).status_code == 403

    approved = client.post(
        f"/admin/users/{user_id}/approve",
        headers=admin_headers,
        json={"role": "analyst"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "active"
    assert approved.json()["role"] == "analyst"

    # Now login works with assigned role
    login_ok = client.post(
        "/auth/login",
        json={"username": "pending_u", "password": "PendingPassword123!"},
    )
    assert login_ok.status_code == 200
    assert login_ok.json()["user"]["role"] == "analyst"

    with session_factory() as db:
        actions = [entry.action for entry in db.scalars(select(AuditLog))]
        assert "access_requested" in actions
        assert "admin_user_approved" in actions


def test_last_admin_cannot_be_demoted_or_deactivated(users_client):
    client, _ = users_client
    admin_headers = _login_headers(client, "boss_admin", "AdminSecret12345!")
    users = client.get("/admin/users", headers=admin_headers).json()
    admin_id = next(u["id"] for u in users if u["username"] == "boss_admin")

    demote = client.patch(
        f"/admin/users/{admin_id}/role",
        headers=admin_headers,
        json={"role": "analyst"},
    )
    assert demote.status_code == 409
    assert "last remaining active admin" in demote.json()["detail"].lower()

    deactivate = client.post(f"/admin/users/{admin_id}/deactivate", headers=admin_headers)
    assert deactivate.status_code == 409
    assert "last remaining active admin" in deactivate.json()["detail"].lower()

    # Creating a second admin allows demoting the first
    created = client.post(
        "/admin/users",
        headers=admin_headers,
        json={"username": "second_admin", "password": "SecondAdminPassword123!", "role": "admin"},
    )
    assert created.status_code == 201
    demote_ok = client.patch(
        f"/admin/users/{admin_id}/role",
        headers=admin_headers,
        json={"role": "approver"},
    )
    assert demote_ok.status_code == 200
    assert demote_ok.json()["role"] == "approver"


def test_request_access_rate_limit(users_client):
    client, _ = users_client
    for index in range(5):
        res = client.post(
            "/auth/request-access",
            json={
                "username": f"rate_u_{index}",
                "email": f"u{index}@example.com",
                "password": "RateLimitPassword123!",
            },
        )
        assert res.status_code == 202

    blocked = client.post(
        "/auth/request-access",
        json={
            "username": "rate_u_over",
            "email": "over@example.com",
            "password": "RateLimitPassword123!",
        },
    )
    assert blocked.status_code == 429


def test_direct_signup_creates_analyst_ignores_role_and_issues_token(users_client):
    client, session_factory = users_client
    short = client.post(
        "/auth/signup",
        json={"username": "quick_u", "email": "quick@example.com", "password": "short"},
    )
    assert short.status_code == 400

    res = client.post(
        "/auth/signup",
        json={
            "username": "quick_u",
            "email": "quick@example.com",
            "password": "QuickPassword123!",
            "role": "admin",
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["user"]["username"] == "quick_u"
    assert body["user"]["role"] == "analyst"
    assert body["access_token"]

    # Token works immediately on protected endpoints
    summary = client.get("/summary", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert summary.status_code == 200

    # Duplicate username returns 409
    dup = client.post(
        "/auth/signup",
        json={"username": "quick_u", "email": "other@example.com", "password": "QuickPassword123!"},
    )
    assert dup.status_code == 409

    with session_factory() as db:
        actions = [entry.action for entry in db.scalars(select(AuditLog))]
        assert "user_signup" in actions
