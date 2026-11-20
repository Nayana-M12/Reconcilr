from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth.security import actor_from_user, require_roles
from app.config import get_settings
from app.database import get_db
from app.models import User
from app.schemas.imports import ImportResponse
from app.services.importer import import_records

router = APIRouter(prefix="/imports", tags=["imports"])
ALLOWED_TABULAR_EXTENSIONS = {".csv", ".xlsx", ".xls"}


def validate_upload(filename: str, content: bytes, allowed_extensions: set[str]) -> None:
    max_bytes = get_settings().max_upload_size_bytes
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum allowed size of {max_bytes} bytes.",
        )
    suffix = Path(filename).suffix.casefold()
    if suffix not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix or 'unknown'}'. Allowed: {allowed}.",
        )


@router.post("/{record_type}", response_model=ImportResponse)
async def import_file(
    record_type: str,
    file: UploadFile = File(...),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(require_roles("analyst", "admin")),  # noqa: B008
) -> ImportResponse:
    filename = file.filename or "upload"
    content = await file.read()
    validate_upload(filename, content, ALLOWED_TABULAR_EXTENSIONS)
    try:
        result = import_records(
            db,
            record_type,
            filename,
            content,
            actor=actor_from_user(current_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ImportResponse(**result)
