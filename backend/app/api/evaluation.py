from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.auth.security import get_current_user

router = APIRouter(prefix="/evaluation", tags=["evaluation"], dependencies=[Depends(get_current_user)])

REPORT_PATH = Path(__file__).parents[2] / "evals" / "report.json"


@router.get("/report")
def get_evaluation_report() -> dict[str, Any]:
    if not REPORT_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="Evaluation report not found. Run backend/evals/run_eval.py first.",
        )
    try:
        return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Evaluation report JSON is invalid.") from exc
