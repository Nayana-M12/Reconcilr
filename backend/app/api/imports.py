from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.imports import ImportResponse
from app.services.importer import import_records

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("/{record_type}", response_model=ImportResponse)
async def import_file(
    record_type: str,
    file: UploadFile = File(...),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> ImportResponse:
    try:
        result = import_records(db, record_type, file.filename or "upload", await file.read())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ImportResponse(**result)
