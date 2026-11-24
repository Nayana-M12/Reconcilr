"""GET /insights — real AI/reconciliation statistics from the database."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    AgentRun,
    AISuggestion,
    Adjustment,
    AuditLog,
    ExceptionCase,
    Invoice,
    Match,
    Payment,
    PurchaseOrder,
)

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("")
def insights(db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    # ---- volume ----
    total_invoices = db.scalar(select(func.count()).select_from(Invoice)) or 0
    total_pos = db.scalar(select(func.count()).select_from(PurchaseOrder)) or 0
    total_payments = db.scalar(select(func.count()).select_from(Payment)) or 0
    total_transactions = total_invoices + total_pos + total_payments

    total_matches = db.scalar(select(func.count()).select_from(Match)) or 0
    matched_invoices = db.scalar(
        select(func.count(func.distinct(Match.invoice_id))).select_from(Match)
    ) or 0
    unmatched_invoices = total_invoices - matched_invoices

    # ---- exceptions ----
    total_exceptions = db.scalar(select(func.count()).select_from(ExceptionCase)) or 0
    open_exceptions = db.scalar(
        select(func.count()).select_from(ExceptionCase).where(ExceptionCase.status == "open")
    ) or 0
    resolved_exceptions = db.scalar(
        select(func.count()).select_from(ExceptionCase).where(ExceptionCase.status == "resolved")
    ) or 0

    # exceptions by category
    rows = db.execute(
        select(ExceptionCase.type, func.count().label("n"))
        .group_by(ExceptionCase.type)
        .order_by(func.count().desc())
    ).all()
    exceptions_by_type = {row.type: row.n for row in rows}

    # high-risk (high + critical severity)
    high_risk = db.scalar(
        select(func.count()).select_from(ExceptionCase).where(
            ExceptionCase.severity.in_(["high", "critical"]),
            ExceptionCase.status == "open",
        )
    ) or 0

    # ---- agent / AI ----
    agent_runs = db.scalar(select(func.count()).select_from(AgentRun)) or 0
    agent_explained = db.scalar(
        select(func.count()).select_from(AgentRun).where(AgentRun.verdict == "explained")
    ) or 0
    agent_pending = db.scalar(
        select(func.count()).select_from(AgentRun).where(AgentRun.status == "pending")
    ) or 0

    ai_suggestions = db.scalar(select(func.count()).select_from(AISuggestion)) or 0
    ai_accepted = db.scalar(
        select(func.count()).select_from(AISuggestion).where(AISuggestion.status == "accepted")
    ) or 0

    # ---- adjustments ----
    pending_adjustments = db.scalar(
        select(func.count()).select_from(Adjustment).where(Adjustment.status == "pending")
    ) or 0
    approved_adjustments = db.scalar(
        select(func.count()).select_from(Adjustment).where(Adjustment.status == "approved")
    ) or 0
    rejected_adjustments = db.scalar(
        select(func.count()).select_from(Adjustment).where(Adjustment.status == "rejected")
    ) or 0

    # ---- matching tier breakdown ----
    tier_rows = db.execute(
        select(Match.tier, func.count().label("n")).group_by(Match.tier)
    ).all()
    matches_by_tier = {row.tier: row.n for row in tier_rows}

    # ---- most recent agent activity ----
    recent_runs = db.execute(
        select(AgentRun.exception_id, AgentRun.verdict, AgentRun.status, AgentRun.created_at)
        .order_by(AgentRun.created_at.desc())
        .limit(5)
    ).all()
    recent_investigations = [
        {
            "exception_id": r.exception_id,
            "verdict": r.verdict,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in recent_runs
    ]

    # ---- recurring exception types (top 3) ----
    recurring = sorted(exceptions_by_type.items(), key=lambda kv: kv[1], reverse=True)[:3]

    return {
        "volume": {
            "total_transactions": total_transactions,
            "invoices": total_invoices,
            "purchase_orders": total_pos,
            "payments": total_payments,
        },
        "matching": {
            "total_matches": total_matches,
            "matched_invoices": matched_invoices,
            "unmatched_invoices": unmatched_invoices,
            "by_tier": matches_by_tier,
            "match_rate_pct": round(matched_invoices / total_invoices * 100, 1) if total_invoices else 0,
        },
        "exceptions": {
            "total": total_exceptions,
            "open": open_exceptions,
            "resolved": resolved_exceptions,
            "high_risk_open": high_risk,
            "by_type": exceptions_by_type,
            "recurring_types": [{"type": t, "count": n} for t, n in recurring],
        },
        "ai": {
            "agent_runs": agent_runs,
            "agent_explained": agent_explained,
            "agent_pending_review": agent_pending,
            "ai_suggestions": ai_suggestions,
            "ai_suggestions_accepted": ai_accepted,
        },
        "adjustments": {
            "pending": pending_adjustments,
            "approved": approved_adjustments,
            "rejected": rejected_adjustments,
        },
        "recent_investigations": recent_investigations,
    }
