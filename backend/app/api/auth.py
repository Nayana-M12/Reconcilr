import re
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    AuthenticatedUser,
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.models import User
from app.services.audit import write_audit

router = APIRouter(tags=["auth"])

VALID_ROLES = {"admin", "analyst", "approver", "auditor"}


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6)
    role: str = Field(default="analyst")


@router.post("/login")
async def login(
    request: Request,
    username: str | None = Form(default=None),
    password: str | None = Form(default=None),
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, object]:
    if username is None or password is None:
        payload = LoginRequest.model_validate(await request.json())
        username, password = payload.username, payload.password
    user = db.scalar(select(User).where(User.username == username, User.is_active.is_(True)))
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    write_audit(
        db,
        actor=user.username,
        action="user_login",
        entity_type="User",
        entity_id=user.id,
        inputs={"username": user.username, "role": user.role},
        formula="Verified credentials and issued JWT",
        output={"status": "authenticated"},
    )
    db.commit()
    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "role": user.role,
        "username": user.username,
        "user_id": user.id,
    }


@router.post("/register")
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    # Input validation
    clean_username = payload.username.strip()
    if not re.match(r"^[a-zA-Z0-9_\-\.]{3,50}$", clean_username):
        raise HTTPException(
            status_code=400,
            detail="Username must be 3-50 characters and contain only letters, numbers, hyphens, and underscores",
        )
    if payload.role not in VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{payload.role}'. Must be one of: {', '.join(sorted(VALID_ROLES))}",
        )
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    # Check for existing user
    existing = db.scalar(select(User).where(User.username == clean_username))
    if existing:
        raise HTTPException(status_code=409, detail=f"Username '{clean_username}' is already taken")

    # Create new user
    user = User(
        username=clean_username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.flush()

    write_audit(
        db,
        actor=clean_username,
        action="user_register",
        entity_type="User",
        entity_id=user.id,
        inputs={"username": clean_username, "role": payload.role},
        formula="Registered new user with hashed password",
        output={"status": "registered"},
    )
    db.commit()

    token = create_access_token(user)
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "username": user.username,
        "user_id": user.id,
        "message": "User registered successfully",
    }


@router.post("/logout")
def logout(
    user: AuthenticatedUser = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, str]:
    write_audit(
        db,
        actor=user.username,
        action="user_logout",
        entity_type="User",
        entity_id=user.id,
        inputs={"username": user.username},
        formula="User logged out session",
        output={"status": "logged_out"},
    )
    db.commit()
    return {"message": "Logged out successfully"}


@router.get("/me")
def me(
    user: AuthenticatedUser = Depends(get_current_user),  # noqa: B008
) -> dict[str, str]:
    return {"id": user.id, "username": user.username, "role": user.role}
