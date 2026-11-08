from sqlalchemy.orm import Session

from app.models import Evidence
from app.services.exceptions.detectors import ExceptionFinding


def attach_evidence(db: Session, exception_id: str, finding: ExceptionFinding) -> list[Evidence]:
    records = [
        Evidence(exception_id=exception_id, record_type=record_type, record_id=record_id, note=note)
        for record_type, record_id, note in finding.evidence
    ]
    db.add_all(records)
    return records
