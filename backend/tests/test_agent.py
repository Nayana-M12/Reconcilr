import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agent import investigate
from app.agent.investigate import investigate_exception
from app.agent.verifier import (
    InvestigationResult,
    VerificationFailure,
    verify_and_render,
)
from app.api.agent import DecisionRequest, accept_run
from app.models import ExceptionCase
from app.services.exceptions.engine import run_exceptions
from app.services.importer import import_records
from app.services.matching.engine import run_matching


def _prepare(db) -> None:
    data = Path(__file__).parents[1] / "data"
    for record_type, filename in (
        ("vendor", "vendors.csv"),
        ("purchase_order", "purchase_orders.csv"),
        ("invoice", "invoices.csv"),
        ("payment", "payments.csv"),
    ):
        import_records(db, record_type, filename, (data / filename).read_bytes())
    run_matching(db)
    run_exceptions(db)


def test_template_path_works_without_key_and_uses_decimal(db, monkeypatch):
    _prepare(db)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    case = db.scalar(select(ExceptionCase).where(ExceptionCase.type == "PARTIAL_PAYMENT"))
    run = investigate_exception(db, case.id)
    assert run.source == "template"
    assert run.verification_status == "verified"
    difference = next(call["result"]["difference"] for call in run.tool_calls if call["name"] == "calculate_difference")
    assert Decimal(difference) == Decimal("10.00")


def test_invoice_without_payment_is_unresolved(db, monkeypatch):
    _prepare(db)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    case = db.scalar(select(ExceptionCase).where(ExceptionCase.type == "MISSING_PAYMENT"))
    run = investigate_exception(db, case.id)
    result = json.loads(run.explanation)
    assert result["verdict"] == "unresolved"
    assert result["proposed_action"] == "request_info"


def test_hallucinated_record_falls_back_to_template(db, monkeypatch):
    _prepare(db)
    case = db.scalar(select(ExceptionCase).where(ExceptionCase.type == "MISSING_PAYMENT"))
    monkeypatch.setenv("LLM_API_KEY", "test")
    monkeypatch.setenv("LLM_MODEL", "test")
    response = {
        "choices": [{"message": {"content": json.dumps({
            "exception_id": case.id, "verdict": "explained",
            "claims": [{"text": "Payment pay-008821 was found.", "record_ids": ["pay-008821"],
                        "tool_call_refs": []}],
            "proposed_action": "no_action", "draft_note": "invented",
        })}}]
    }
    monkeypatch.setattr(investigate, "call_llm", lambda messages, tools: response)
    run = investigate_exception(db, case.id)
    assert run.source == "template"
    assert any("record" in error for error in run.errors)


def test_number_not_in_tool_output_is_rejected(db):
    case = ExceptionCase(type="MISSING_PAYMENT", severity="low", description="missing")
    db.add(case)
    db.commit()
    result = InvestigationResult(
        exception_id=case.id, verdict="unresolved",
        claims=[{"text": "There are 999 unmatched records.", "record_ids": [], "tool_call_refs": []}],
        proposed_action="no_action", draft_note="",
    )
    with pytest.raises(VerificationFailure, match="number not returned"):
        verify_and_render(db, result, [{"ref": "tool_call_1", "result": {"records": []}}], source="template")


def test_llm_cannot_supply_a_literal_amount(db):
    case = ExceptionCase(type="MISSING_PAYMENT", severity="low", description="missing")
    db.add(case)
    db.commit()
    result = InvestigationResult(
        exception_id=case.id, verdict="unresolved",
        claims=[{"text": "The amount is $999.00.", "record_ids": [], "tool_call_refs": []}],
        proposed_action="no_action", draft_note="",
    )
    with pytest.raises(VerificationFailure, match="literal number or amount"):
        verify_and_render(db, result, [{"ref": "tool_call_1", "result": {"records": []}}], source="llm")


def test_accepting_run_twice_returns_conflict(db, monkeypatch, analyst_user):
    _prepare(db)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    case = db.scalar(select(ExceptionCase).where(ExceptionCase.type == "PARTIAL_PAYMENT"))
    run = investigate_exception(db, case.id)
    accept_run(run.id, DecisionRequest(), db, user=analyst_user)
    with pytest.raises(Exception) as error:
        accept_run(run.id, DecisionRequest(), db, user=analyst_user)
    assert getattr(error.value, "status_code", None) == 409
