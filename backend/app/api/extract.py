"""POST /extract — upload a document, receive extracted financial fields."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser, require_roles
from app.config import get_settings
from app.database import get_db
from app.services.extractor import extract_fields

router = APIRouter(prefix="/extract", tags=["extract"])

_ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}


@router.post("")
async def extract(
    file: UploadFile = File(...),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
    user: AuthenticatedUser = Depends(require_roles("analyst", "admin")),  # noqa: B008
) -> dict[str, Any]:
    filename = file.filename or "upload"
    if Path(filename).suffix.casefold() not in _ALLOWED:
        raise HTTPException(
            status_code=400,
            detail="Supported formats: PDF, PNG, JPG, JPEG, TIFF, BMP, WEBP",
        )
    settings = get_settings()
    content = await file.read(settings.upload_max_bytes + 1)
    if len(content) > settings.upload_max_bytes:
        limit_mb = settings.upload_max_bytes / (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"File exceeds {limit_mb:g} MB limit")

    result = extract_fields(filename, content)
    return {
        "filename": result.filename,
        "method": result.method,
        "fields": result.fields,
        "confidence": result.confidence,
        "warnings": result.warnings,
    }
