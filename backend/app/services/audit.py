from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog
from app.services.privacy import redact
from app.services.request_context import current_audit_actor


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
        actor=current_audit_actor() or actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        inputs=redact(dict(inputs)),
        formula=formula,
        output=redact(dict(output)),
    )
    db.add(entry)
    return entry
