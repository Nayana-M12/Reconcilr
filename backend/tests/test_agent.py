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


def test_accepting_run_twice_returns_conflict(db, monkeypatch):
    _prepare(db)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    case = db.scalar(select(ExceptionCase).where(ExceptionCase.type == "PARTIAL_PAYMENT"))
    run = investigate_exception(db, case.id)
    accept_run(run.id, DecisionRequest(role="analyst"), db)
    with pytest.raises(Exception) as error:
        accept_run(run.id, DecisionRequest(role="analyst"), db)
    assert getattr(error.value, "status_code", None) == 409


def test_resolution_plan_covers_all_eight_sections_and_multiple_solutions(db, monkeypatch):
    _prepare(db)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    for exc_type in (
        "PARTIAL_PAYMENT",
        "OVERPAYMENT",
        "DUPLICATE_INVOICE",
        "MISSING_PAYMENT",
        "MISSING_PO",
        "VENDOR_MISMATCH",
        "DATE_GAP",
    ):
        case = db.scalar(select(ExceptionCase).where(ExceptionCase.type == exc_type))
        assert case is not None
        run = investigate_exception(db, case.id)
        payload = json.loads(run.explanation)
        plan = payload["resolution_plan"]
        assert plan["problem_identification"]
        assert len(plan["possible_causes"]) >= 2
        assert len(plan["possible_solutions"]) >= 2
        assert plan["recommended_solution"]
        assert len(plan["required_actions"]) >= 2
        assert len(plan["required_documents"]) >= 2
        assert plan["expected_outcome"]
        assert plan["confidence_level"] in {"low", "medium", "high"}

        if exc_type == "PARTIAL_PAYMENT":
            assert "10.00" in plan["problem_identification"]
            assert len(plan["possible_solutions"]) == 4
            assert plan["insufficient_evidence"] is False
        if exc_type == "MISSING_PAYMENT":
            assert plan["insufficient_evidence"] is True
            assert plan["recommended_solution_id"] is None
            assert plan["confidence_level"] == "low"


def test_verifier_rejects_hallucinated_id_or_literal_amount_inside_resolution_plan(db):
    from app.agent.verifier import ResolutionOption, ResolutionPlan

    case = ExceptionCase(type="PARTIAL_PAYMENT", severity="medium", description="short")
    db.add(case)
    db.commit()
    bad_plan = ResolutionPlan(
        problem_identification="Payment pay-009999 was short by ₹5000.",
        possible_causes=["Cause A"],
        possible_solutions=[
            ResolutionOption(id="s1", title="Opt 1", possible_cause="c1", action="a1", resolution="r1"),
            ResolutionOption(id="s2", title="Opt 2", possible_cause="c2", action="a2", resolution="r2"),
        ],
        recommended_solution_id="s1",
        recommended_solution="Check bank statement.",
        required_actions=["Check"],
        required_documents=["Bank statement"],
        expected_outcome="No automatic change.",
        confidence_level="low",
    )
    result = InvestigationResult(
        exception_id=case.id,
        verdict="unresolved",
        claims=[],
        proposed_action="request_info",
        draft_note="note",
        resolution_plan=bad_plan,
    )
    with pytest.raises(VerificationFailure, match="literal number or amount"):
        verify_and_render(db, result, [{"ref": "tool_call_1", "result": {"records": []}}], source="llm")


def test_analyst_selects_solution_routes_to_pending_approval_and_audits_full_decision(db, monkeypatch):
    from app.models import Adjustment, AuditLog

    _prepare(db)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    case = db.scalar(select(ExceptionCase).where(ExceptionCase.type == "PARTIAL_PAYMENT"))
    run = investigate_exception(db, case.id)

    # Invalid solution ID is rejected with 400
    with pytest.raises(Exception) as bad_err:
        accept_run(run.id, DecisionRequest(role="analyst", selected_solution_id="nonexistent"), db)
    assert getattr(bad_err.value, "status_code", None) == 400

    # Valid solution selection routes to existing pending approval (never auto-applies)
    accepted = accept_run(
        run.id,
        DecisionRequest(
            role="analyst",
            selected_solution_id="credit_note_adjustment",
            note="Checked bank statement; routing credit note adjustment for approver sign-off",
        ),
        db,
    )
    assert accepted["status"] == "accepted"
    assert accepted["selected_solution_id"] == "credit_note_adjustment"

    adj = db.scalar(select(Adjustment).where(Adjustment.exception_id == case.id))
    assert adj is not None
    assert adj.status == "pending"  # Never auto-applied!

    audit_entry = db.scalar(
        select(AuditLog).where(AuditLog.action == "agent_accept", AuditLog.entity_id == run.id)
    )
    assert audit_entry is not None
    assert audit_entry.output["selected_solution"]["id"] == "credit_note_adjustment"
    assert len(audit_entry.output["suggested_solutions"]) == 4
    assert audit_entry.output["ai_problem_identification"]
    assert len(audit_entry.inputs["supporting_evidence"]) >= 2
