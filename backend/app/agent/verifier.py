from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.models import (
    Adjustment,
    ExceptionCase,
    Invoice,
    Payment,
    PurchaseOrder,
    Vendor,
)

WorkflowAction = Literal[
    "propose_adjustment",
    "request_info",
    "escalate",
    "mark_duplicate",
    "no_action",
]


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    record_ids: list[str] = Field(default_factory=list)
    tool_call_refs: list[str] = Field(default_factory=list)


class ResolutionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    possible_cause: str
    action: str
    resolution: str
    workflow_action: WorkflowAction = "request_info"


class ResolutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_identification: str
    possible_causes: list[str] = Field(default_factory=list)
    possible_solutions: list[ResolutionOption] = Field(default_factory=list)
    recommended_solution_id: str | None = None
    recommended_solution: str
    required_actions: list[str] = Field(default_factory=list)
    required_documents: list[str] = Field(default_factory=list)
    expected_outcome: str
    confidence_level: Literal["low", "medium", "high"]
    confidence_rationale: str = ""
    insufficient_evidence: bool = False


class InvestigationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exception_id: str
    verdict: Literal["explained", "unresolved"]
    claims: list[Claim]
    proposed_action: WorkflowAction
    draft_note: str
    resolution_plan: ResolutionPlan | None = None


class VerificationFailure(ValueError):
    pass


_PLACEHOLDER = re.compile(r"\{(?P<key>[a-zA-Z_]+):(?P<ref>[a-zA-Z0-9_-]+)\}")
_ID_PATTERN = re.compile(r"\b(?:inv|pay|po|exc|vendor|match|adj)-[A-Za-z0-9_-]+\b", re.IGNORECASE)
_NUMBER_PATTERN = re.compile(r"(?<![\w-])\d+(?:\.\d+)?(?![\w-])")


def _exists(db: Session, record_id: str) -> bool:
    return any(
        db.get(model, record_id) is not None
        for model in (
            Invoice,
            Payment,
            PurchaseOrder,
            Vendor,
            ExceptionCase,
            Adjustment,
        )
    )


def _returned_ids(tool_calls: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"id", "record_id", "invoice_id", "payment_id", "po_id"} and isinstance(item, str):
                    found.add(item)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for call in tool_calls:
        visit(call.get("result", {}))
    return found


def _numeric_values(tool_calls: list[dict[str, Any]]) -> set[str]:
    values: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, (int, float, str)):
            values.update(_NUMBER_PATTERN.findall(str(value)))

    for call in tool_calls:
        visit(call.get("result", {}))
    return values


def _lookup_placeholder(tool_calls: list[dict[str, Any]], ref: str, key: str) -> str:
    call = next((item for item in tool_calls if item.get("ref") == ref), None)
    if call is None:
        raise VerificationFailure(f"placeholder references unknown tool call {ref}")
    result = call.get("result", {})
    value = result.get(key)
    if value is None and isinstance(result.get("record"), dict):
        value = result["record"].get(key)
    if not isinstance(value, (str, int, float)):
        raise VerificationFailure(f"placeholder {{{key}:{ref}}} has no scalar tool value")
    return str(value)


def render_text(text: str, tool_calls: list[dict[str, Any]]) -> str:
    return _PLACEHOLDER.sub(
        lambda match: _lookup_placeholder(tool_calls, match.group("ref"), match.group("key")),
        text,
    )


def _collect_plan_texts(plan: ResolutionPlan) -> list[str]:
    texts = [
        plan.problem_identification,
        *plan.possible_causes,
        plan.recommended_solution,
        *plan.required_actions,
        *plan.required_documents,
        plan.expected_outcome,
        plan.confidence_rationale,
    ]
    for option in plan.possible_solutions:
        texts.extend([option.title, option.possible_cause, option.action, option.resolution])
    return texts


def _render_plan(plan: ResolutionPlan, tool_calls: list[dict[str, Any]]) -> ResolutionPlan:
    return plan.model_copy(
        update={
            "problem_identification": render_text(plan.problem_identification, tool_calls),
            "possible_causes": [render_text(item, tool_calls) for item in plan.possible_causes],
            "possible_solutions": [
                option.model_copy(
                    update={
                        "title": render_text(option.title, tool_calls),
                        "possible_cause": render_text(option.possible_cause, tool_calls),
                        "action": render_text(option.action, tool_calls),
                        "resolution": render_text(option.resolution, tool_calls),
                    }
                )
                for option in plan.possible_solutions
            ],
            "recommended_solution": render_text(plan.recommended_solution, tool_calls),
            "required_actions": [render_text(item, tool_calls) for item in plan.required_actions],
            "required_documents": [render_text(item, tool_calls) for item in plan.required_documents],
            "expected_outcome": render_text(plan.expected_outcome, tool_calls),
            "confidence_rationale": render_text(plan.confidence_rationale, tool_calls),
        }
    )


def verify_and_render(
    db: Session,
    result: InvestigationResult,
    tool_calls: list[dict[str, Any]],
    *,
    source: Literal["llm", "template"],
) -> InvestigationResult:
    if db.get(ExceptionCase, result.exception_id) is None:
        raise VerificationFailure("exception_id does not exist")
    refs = {str(call.get("ref")) for call in tool_calls}
    returned = _returned_ids(tool_calls)
    cited = {record_id for claim in result.claims for record_id in claim.record_ids}
    for claim in result.claims:
        unknown_refs = set(claim.tool_call_refs) - refs
        if unknown_refs:
            raise VerificationFailure(f"claim cites unknown tool calls: {sorted(unknown_refs)}")
        for record_id in claim.record_ids:
            if not _exists(db, record_id):
                raise VerificationFailure(f"claim cites nonexistent record {record_id}")
            if record_id not in returned:
                raise VerificationFailure(f"claim cites record not returned by a tool {record_id}")

    if result.resolution_plan is not None:
        option_ids = {option.id for option in result.resolution_plan.possible_solutions}
        if (
            result.resolution_plan.recommended_solution_id is not None
            and result.resolution_plan.recommended_solution_id not in option_ids
        ):
            raise VerificationFailure(
                f"recommended_solution_id '{result.resolution_plan.recommended_solution_id}' "
                "is not in possible_solutions"
            )

    text_fields = [claim.text for claim in result.claims] + [result.draft_note]
    if result.resolution_plan is not None:
        text_fields.extend(_collect_plan_texts(result.resolution_plan))

    raw_text = "\n".join(text_fields)
    if source == "llm":
        raw_without_placeholders = _PLACEHOLDER.sub("", raw_text)
        if re.search(r"[$€£₹]\s*\d", raw_without_placeholders) or _NUMBER_PATTERN.search(raw_without_placeholders):
            raise VerificationFailure("LLM supplied a literal number or amount; use a tool placeholder")

    rendered = [render_text(text, tool_calls) for text in text_fields]
    rendered_text = "\n".join(rendered)
    for record_id in _ID_PATTERN.findall(rendered_text):
        if record_id not in cited or record_id not in returned or not _exists(db, record_id):
            raise VerificationFailure(f"text contains uncited or unverified record ID {record_id}")
    allowed_numbers = _numeric_values(tool_calls)
    for number in _NUMBER_PATTERN.findall(rendered_text):
        if number not in allowed_numbers:
            raise VerificationFailure(f"text contains number not returned by a tool: {number}")

    rendered_claims = [
        claim.model_copy(update={"text": rendered[index]})
        for index, claim in enumerate(result.claims)
    ]
    rendered_plan = (
        _render_plan(result.resolution_plan, tool_calls)
        if result.resolution_plan is not None
        else None
    )
    return result.model_copy(
        update={
            "claims": rendered_claims,
            "draft_note": rendered[len(result.claims)],
            "resolution_plan": rendered_plan,
        }
    )


def parse_result(value: str | dict[str, Any]) -> InvestigationResult:
    try:
        return (
            InvestigationResult.model_validate_json(value)
            if isinstance(value, str)
            else InvestigationResult.model_validate(value)
        )
    except (ValidationError, TypeError, ValueError) as exc:
        raise VerificationFailure(f"invalid investigation JSON: {exc}") from exc


def as_json(result: InvestigationResult) -> str:
    return json.dumps(result.model_dump(), separators=(",", ":"), sort_keys=True)
