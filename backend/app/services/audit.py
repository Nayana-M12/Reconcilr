from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def write_audit(
    db: Session,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    inputs: Mapping[str, Any],
    formula: str,
    output: Mapping[str, Any],
) -> AuditLog:
    entry = AuditLog(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        inputs=dict(inputs),
        formula=formula,
        output=dict(output),
    )
    db.add(entry)
    return entry
