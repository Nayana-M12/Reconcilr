from __future__ import annotations

import os
import re
import time
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import (
    VALID_ROLES,
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.models import User
from app.services.audit import write_audit

router = APIRouter(prefix="/auth", tags=["auth"])

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_REQUEST_ACCESS_WINDOW_SECONDS = 3600
_REQUEST_ACCESS_HITS: dict[str, list[float]] = defaultdict(list)


def reset_request_access_rate_limit() -> None:
    _REQUEST_ACCESS_HITS.clear()


def _check_rate_limit(client_ip: str) -> None:
    limit = int(os.getenv("REQUEST_ACCESS_RATE_LIMIT", "5"))
    now = time.monotonic()
    cutoff = now - _REQUEST_ACCESS_WINDOW_SECONDS
    hits = [ts for ts in _REQUEST_ACCESS_HITS[client_ip] if ts > cutoff]
    if len(hits) >= limit:
        _REQUEST_ACCESS_HITS[client_ip] = hits
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many access requests. Please try again later.",
        )
    hits.append(now)
    _REQUEST_ACCESS_HITS[client_ip] = hits


class AccessRequestPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    username: str
    email: str
    password: str
    note: str | None = None


async def _extract_credentials(request: Request) -> tuple[str, str]:
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON login payload") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Invalid login payload")
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        return username, password
    form = await request.form()
    username = str(form.get("username") or "").strip()
    password = str(form.get("password") or "")
    return username, password


@router.post("/login")
async def login(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    username, password = await _extract_credentials(request)
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(password, user.password_hash):
        write_audit(
            db,
            actor=username,
            action="login_failed",
            entity_type="User",
            entity_id=user.id if user else "unknown",
            inputs={"username": username},
            formula="Verify credentials against stored bcrypt hash",
            output={"authenticated": False},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    user_status = getattr(user, "status", "active")
    is_active = getattr(user, "is_active", True)
    if user_status == "pending":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is awaiting approval",
        )
    if not is_active or user_status != "active" or user.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is inactive",
        )
    token = create_access_token(user)
    write_audit(
        db,
        actor=f"{user.username} ({user.role})",
        action="login",
        entity_type="User",
        entity_id=user.id,
        inputs={"username": user.username},
        formula="Issued signed JWT access token",
        output={"authenticated": True, "role": user.role},
    )
    db.commit()
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
        },
    }


@router.post("/request-access", status_code=status.HTTP_202_ACCEPTED)
def request_access(
    payload: AccessRequestPayload,
    request: Request,
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, str]:
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    username = payload.username.strip()
    email = payload.email.strip()
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(
            status_code=400,
            detail="Username must be 3-50 characters (letters, numbers, _, ., -).",
        )
    if not EMAIL_RE.fullmatch(email):
        raise HTTPException(status_code=400, detail="Valid email address is required.")
    if len(payload.password) < 12:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 12 characters long.",
        )

    existing = db.scalar(select(User).where(User.username == username))
    if existing is None:
        user = User(
            username=username,
            email=email,
            password_hash=hash_password(payload.password),
            role=None,
            status="pending",
            is_active=False,
            created_via="request_access",
            request_note=(payload.note or "").strip() or None,
        )
        db.add(user)
        db.flush()
        write_audit(
            db,
            actor="public_request",
            action="access_requested",
            entity_type="User",
            entity_id=user.id,
            inputs={"username": username, "email": email},
            formula="Created inactive pending user with no role; requires admin approval",
            output={"status": "pending", "is_active": False, "role": None},
        )
        db.commit()
    else:
        write_audit(
            db,
            actor="public_request",
            action="access_request_duplicate_ignored",
            entity_type="User",
            entity_id=existing.id,
            inputs={"username": username},
            formula="Ignored duplicate access request without disclosing account existence",
            output={"disclosed": False},
        )
        db.commit()

    return {"message": "Request received. An administrator will review it."}


@router.get("/me")
def me(current_user: User = Depends(get_current_user)) -> dict[str, Any]:  # noqa: B008
    return {
        "id": current_user.id,
        "username": current_user.username,
        "role": current_user.role,
    }
