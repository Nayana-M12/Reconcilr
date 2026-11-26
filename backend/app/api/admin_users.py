from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.security import VALID_ROLES, actor_from_user, hash_password, require_roles
from app.database import get_db
from app.models import User
from app.services.audit import write_audit

router = APIRouter(
    prefix="/admin/users",
    tags=["admin-users"],
    dependencies=[Depends(require_roles("admin"))],
)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AdminCreateUserRequest(BaseModel):
    username: str
    email: str | None = None
    password: str
    role: str


class ApproveUserRequest(BaseModel):
    role: str


class ChangeRoleRequest(BaseModel):
    role: str


def _serialize(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "status": user.status,
        "is_active": user.is_active,
        "created_via": user.created_via,
        "request_note": user.request_note,
        "approved_by": user.approved_by,
        "approved_at": user.approved_at.isoformat() if user.approved_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _active_admin_count(db: Session) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "admin", User.is_active.is_(True), User.status == "active")
        )
        or 0
    )


@router.get("")
def list_users(
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),  # noqa: B008
) -> list[dict[str, Any]]:
    query = select(User).order_by(User.created_at.desc(), User.id.desc())
    if status_filter:
        query = query.where(User.status == status_filter)
    return [_serialize(user) for user in db.scalars(query)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminCreateUserRequest,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(require_roles("admin")),  # noqa: B008
) -> dict[str, Any]:
    username = payload.username.strip()
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(
            status_code=400,
            detail="Username must be 3-50 characters (letters, numbers, _, ., -).",
        )
    if payload.email and not EMAIL_RE.fullmatch(payload.email.strip()):
        raise HTTPException(status_code=400, detail="Invalid email address.")
    if len(payload.password) < 12:
        raise HTTPException(status_code=400, detail="Password must be at least 12 characters long.")
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Role must be one of: {', '.join(sorted(VALID_ROLES))}")
    if db.scalar(select(User).where(User.username == username)) is not None:
        raise HTTPException(status_code=409, detail="Username already exists.")

    now = datetime.now(UTC)
    user = User(
        username=username,
        email=payload.email.strip() if payload.email else None,
        password_hash=hash_password(payload.password),
        role=payload.role,
        status="active",
        is_active=True,
        created_via="admin",
        approved_by=current_user.username,
        approved_at=now,
    )
    db.add(user)
    db.flush()
    write_audit(
        db,
        actor=actor_from_user(current_user),
        action="admin_user_created",
        entity_type="User",
        entity_id=user.id,
        inputs={"username": user.username, "role": user.role},
        formula="Admin created active user account",
        output={"status": user.status, "role": user.role},
    )
    db.commit()
    return _serialize(user)


@router.post("/{user_id}/approve")
def approve_user(
    user_id: str,
    payload: ApproveUserRequest,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(require_roles("admin")),  # noqa: B008
) -> dict[str, Any]:
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Role must be one of: {', '.join(sorted(VALID_ROLES))}")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.status != "pending":
        raise HTTPException(status_code=409, detail=f"User is already {user.status}")

    user.role = payload.role
    user.status = "active"
    user.is_active = True
    user.approved_by = current_user.username
    user.approved_at = datetime.now(UTC)
    write_audit(
        db,
        actor=actor_from_user(current_user),
        action="admin_user_approved",
        entity_type="User",
        entity_id=user.id,
        inputs={"username": user.username, "assigned_role": payload.role},
        formula="Admin approved pending account and assigned role",
        output={"status": user.status, "is_active": user.is_active, "role": user.role},
    )
    db.commit()
    return _serialize(user)


@router.post("/{user_id}/reject")
def reject_user(
    user_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(require_roles("admin")),  # noqa: B008
) -> dict[str, Any]:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.status != "pending":
        raise HTTPException(status_code=409, detail=f"User is already {user.status}")

    user.role = None
    user.status = "rejected"
    user.is_active = False
    write_audit(
        db,
        actor=actor_from_user(current_user),
        action="admin_user_rejected",
        entity_type="User",
        entity_id=user.id,
        inputs={"username": user.username},
        formula="Admin rejected pending access request",
        output={"status": user.status, "is_active": user.is_active},
    )
    db.commit()
    return _serialize(user)


@router.post("/{user_id}/deactivate")
def deactivate_user(
    user_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(require_roles("admin")),  # noqa: B008
) -> dict[str, Any]:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == "admin" and user.is_active and user.status == "active" and _active_admin_count(db) <= 1:
        raise HTTPException(status_code=409, detail="Cannot deactivate the last remaining active admin.")

    user.status = "deactivated"
    user.is_active = False
    write_audit(
        db,
        actor=actor_from_user(current_user),
        action="admin_user_deactivated",
        entity_type="User",
        entity_id=user.id,
        inputs={"username": user.username},
        formula="Admin deactivated user account",
        output={"status": user.status, "is_active": user.is_active},
    )
    db.commit()
    return _serialize(user)


@router.patch("/{user_id}/role")
def change_user_role(
    user_id: str,
    payload: ChangeRoleRequest,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(require_roles("admin")),  # noqa: B008
) -> dict[str, Any]:
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Role must be one of: {', '.join(sorted(VALID_ROLES))}")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if (
        user.role == "admin"
        and payload.role != "admin"
        and user.is_active
        and user.status == "active"
        and _active_admin_count(db) <= 1
    ):
        raise HTTPException(status_code=409, detail="Cannot demote the last remaining active admin.")

    previous_role = user.role
    user.role = payload.role
    write_audit(
        db,
        actor=actor_from_user(current_user),
        action="admin_user_role_changed",
        entity_type="User",
        entity_id=user.id,
        inputs={"username": user.username, "previous_role": previous_role, "new_role": payload.role},
        formula="Admin updated user role",
        output={"role": user.role},
    )
    db.commit()
    return _serialize(user)
