from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Adjustment, ExceptionCase, Match

router = APIRouter(tags=["summary"])


@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> dict[str, int]:  # noqa: B008
    return {
        "matches": db.scalar(select(func.count()).select_from(Match)) or 0,
        "open_exceptions": db.scalar(
            select(func.count()).select_from(ExceptionCase).where(ExceptionCase.status == "open")
        ) or 0,
        "resolved_exceptions": db.scalar(
            select(func.count()).select_from(ExceptionCase).where(ExceptionCase.status == "resolved")
        ) or 0,
        "pending_adjustments": db.scalar(
            select(func.count()).select_from(Adjustment).where(Adjustment.status == "pending")
        ) or 0,
    }
