from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.matching.engine import list_matches, run_matching

router = APIRouter(prefix="/matching", tags=["matching"])


@router.post("/run")
def run(db: Session = Depends(get_db)) -> dict[str, object]:  # noqa: B008
    result = run_matching(db)
    return {
        "created": result.created,
        "existing": result.existing,
        "unmatched_invoice_ids": result.unmatched_invoice_ids,
        "tier_counts": result.tier_counts,
    }


@router.get("/results")
def results(db: Session = Depends(get_db)) -> list[dict[str, object]]:  # noqa: B008
    return list_matches(db)
