from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User

ROLES = {"admin", "analyst", "approver", "auditor"}
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    username: str
    role: str


def _secret() -> str:
    secret = get_settings().jwt_secret
    if not secret:
        if get_settings().app_env.casefold() == "development":
            return "reconcilr-dev-fallback-secret-key-32-chars-ok"
        raise HTTPException(status_code=503, detail="JWT_SECRET is not configured")
    return secret


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must not be empty")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def create_access_token(user: User) -> str:
    expires_at = datetime.now(UTC) + timedelta(minutes=get_settings().jwt_expiry_minutes)
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "exp": expires_at,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid access token") from exc
    if claims.get("role") not in ROLES or not claims.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid access token claims")
    return claims


def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),  # noqa: B008
) -> AuthenticatedUser:
    claims = getattr(request.state, "auth_claims", None)
    if claims is None:
        claims = decode_access_token(token)
    user = db.scalar(select(User).where(User.id == claims["sub"], User.is_active.is_(True)))
    if user is None or user.role != claims["role"]:
        raise HTTPException(status_code=401, detail="User is inactive or token is stale")
    request.state.authenticated_user = AuthenticatedUser(user.id, user.username, user.role)
    return request.state.authenticated_user


def require_roles(*allowed_roles: str) -> Callable[..., AuthenticatedUser]:
    if not set(allowed_roles).issubset(ROLES):
        raise ValueError("unknown authorization role")

    def dependency(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:  # noqa: B008
        if user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return dependency
