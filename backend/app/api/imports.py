from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser, require_roles
from app.config import get_settings
from app.database import get_db
from app.schemas.imports import ImportResponse
from app.services.importer import import_records

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("/{record_type}", response_model=ImportResponse)
async def import_file(
    record_type: str,
    file: UploadFile = File(...),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
    user: AuthenticatedUser = Depends(require_roles("analyst", "admin")),  # noqa: B008
) -> ImportResponse:
    filename = file.filename or "upload"
    extension = Path(filename).suffix.casefold()
    allowed_extensions = {".csv", ".xlsx", ".xls"}
    if extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Only .csv, .xlsx, and .xls uploads are supported")
    content = await file.read(get_settings().upload_max_bytes + 1)
    if len(content) > get_settings().upload_max_bytes:
        limit_mb = get_settings().upload_max_bytes / (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"Uploaded file exceeds the {limit_mb:g} MB limit")
    try:
        result = import_records(db, record_type, filename, content, actor=user.username, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ImportResponse(**result)
