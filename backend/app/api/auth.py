from fastapi import APIRouter, Depends, Form, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import create_access_token, verify_password
from app.database import get_db
from app.models import User

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


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
    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "role": user.role,
    }
