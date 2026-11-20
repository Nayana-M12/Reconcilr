from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import get_current_user
from app.database import get_db
from app.models import AuditLog

router = APIRouter(tags=["audit"], dependencies=[Depends(get_current_user)])


def _serialize(entry: AuditLog) -> dict[str, Any]:
    return {
        "id": entry.id,
        "timestamp": entry.timestamp.isoformat() if isinstance(entry.timestamp, datetime) else entry.timestamp,
        "actor": entry.actor,
        "action": entry.action,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "inputs": entry.inputs,
        "formula": entry.formula,
        "output": entry.output,
    }


@router.get("/audit")
def audit(
    entity_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),  # noqa: B008
) -> list[dict[str, Any]]:
    query = select(AuditLog).order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(limit)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    return [_serialize(entry) for entry in db.scalars(query)]
