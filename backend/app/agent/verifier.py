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


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    record_ids: list[str] = Field(default_factory=list)
    tool_call_refs: list[str] = Field(default_factory=list)


class InvestigationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exception_id: str
    verdict: Literal["explained", "unresolved"]
    claims: list[Claim]
    proposed_action: Literal[
        "propose_adjustment", "request_info", "escalate", "mark_duplicate", "no_action",
    ]
    draft_note: str


class VerificationFailure(ValueError):
    pass


_PLACEHOLDER = re.compile(r"\{(?P<key>[a-zA-Z_]+):(?P<ref>[a-zA-Z0-9_-]+)\}")
_ID_PATTERN = re.compile(r"\b(?:inv|pay|po|exc|vendor|match|adj)-[A-Za-z0-9_-]+\b", re.IGNORECASE)
_NUMBER_PATTERN = re.compile(r"(?<![\w-])\d+(?:\.\d+)?(?![\w-])")


def _exists(db: Session, record_id: str) -> bool:
    return any(db.get(model, record_id) is not None for model in (
        Invoice, Payment, PurchaseOrder, Vendor, ExceptionCase, Adjustment,
    ))


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
    value = call.get("result", {}).get(key)
    if not isinstance(value, (str, int, float)):
        raise VerificationFailure(f"placeholder {{{key}:{ref}}} has no scalar tool value")
    return str(value)


def render_text(text: str, tool_calls: list[dict[str, Any]]) -> str:
    return _PLACEHOLDER.sub(
        lambda match: _lookup_placeholder(tool_calls, match.group("ref"), match.group("key")),
        text,
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

    text_fields = [claim.text for claim in result.claims] + [result.draft_note]
    raw_text = "\n".join(text_fields)
    if source == "llm":
        raw_without_placeholders = _PLACEHOLDER.sub("", raw_text)
        if re.search(r"[$€£]\s*\d", raw_without_placeholders) or _NUMBER_PATTERN.search(raw_without_placeholders):
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
    return result.model_copy(update={
        "claims": rendered_claims,
        "draft_note": rendered[-1],
    })


def parse_result(value: str | dict[str, Any]) -> InvestigationResult:
    try:
        return InvestigationResult.model_validate_json(value) if isinstance(value, str) else InvestigationResult.model_validate(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise VerificationFailure(f"invalid investigation JSON: {exc}") from exc


def as_json(result: InvestigationResult) -> str:
    return json.dumps(result.model_dump(), separators=(",", ":"), sort_keys=True)
