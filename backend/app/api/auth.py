from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import (
    VALID_ROLES,
    create_access_token,
    get_current_user,
    verify_password,
)
from app.database import get_db
from app.models import User
from app.services.audit import write_audit

router = APIRouter(prefix="/auth", tags=["auth"])


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


@router.get("/me")
def me(current_user: User = Depends(get_current_user)) -> dict[str, Any]:  # noqa: B008
    return {
        "id": current_user.id,
        "username": current_user.username,
        "role": current_user.role,
    }
