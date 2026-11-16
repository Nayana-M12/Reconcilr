from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser, hash_password, require_roles
from app.database import get_db
from app.models import User
from app.services.audit import write_audit

router = APIRouter(prefix="/users", tags=["users"])


class UserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12)
    role: str


def _serialize(user: User) -> dict[str, Any]:
    return {"id": user.id, "username": user.username, "role": user.role, "is_active": user.is_active}


@router.get("")
def list_users(
    db: Session = Depends(get_db),  # noqa: B008
    user: AuthenticatedUser = Depends(require_roles("admin")),  # noqa: B008
) -> list[dict[str, Any]]:
    return [_serialize(item) for item in db.scalars(select(User).order_by(User.username))]


@router.post("")
def create_user(
    request: UserRequest,
    db: Session = Depends(get_db),  # noqa: B008
    user: AuthenticatedUser = Depends(require_roles("admin")),  # noqa: B008
) -> dict[str, Any]:
    if request.role not in {"admin", "analyst", "approver", "auditor"}:
        raise HTTPException(status_code=400, detail="Invalid user role")
    if db.scalar(select(User).where(User.username == request.username)):
        raise HTTPException(status_code=409, detail="Username already exists")
    created = User(username=request.username, password_hash=hash_password(request.password), role=request.role)
    db.add(created)
    db.flush()
    write_audit(
        db, actor=user.username, action="user_created", entity_type="User", entity_id=created.id,
        inputs={"username": created.username, "role": created.role},
        formula="Admin created user with a hashed password",
        output={"user_id": created.id, "role": created.role},
    )
    db.commit()
    return _serialize(created)
