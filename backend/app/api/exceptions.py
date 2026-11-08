from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.exceptions.engine import (
    get_exception,
    list_exceptions,
    run_exceptions,
)

router = APIRouter(prefix="/exceptions", tags=["exceptions"])


@router.post("/run")
def run(db: Session = Depends(get_db)) -> dict[str, object]:  # noqa: B008
    result = run_exceptions(db)
    return {"created": result.created, "existing": result.existing, "by_type": result.by_type}


@router.get("")
def list_all(
    type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    db: Session = Depends(get_db),  # noqa: B008
) -> list[dict[str, object]]:
    return list_exceptions(db, type, status, severity)


@router.get("/{exception_id}")
def get_one(exception_id: str, db: Session = Depends(get_db)) -> dict[str, object]:  # noqa: B008
    result = get_exception(db, exception_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Exception not found")
    return result
