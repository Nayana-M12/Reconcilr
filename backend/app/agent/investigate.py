from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS
from app.agent.verifier import (
    InvestigationResult,
    VerificationFailure,
    as_json,
    parse_result,
    verify_and_render,
)
from app.models import AgentRun
from app.services.audit import write_audit

SYSTEM_PROMPT = """You investigate one reconciliation exception using only the supplied tools.
Never invent records, IDs, amounts, dates, or conclusions. Every claim must cite record_ids and
tool_call_refs. Do not write literal numbers or currency amounts in text. For an amount, use a
placeholder such as {difference:tool_call_3}; code will insert the verified tool value.
Return only JSON matching the requested schema. An unresolved verdict is valid."""


def call_llm(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL")
    if not api_key or not model:
        raise RuntimeError("LLM_API_KEY and LLM_MODEL are required for LLM investigations")
    endpoint = os.getenv("LLM_API_URL", "https://api.openai.com/v1/chat/completions")
    payload = json.dumps({"model": model, "messages": messages, "tools": tools, "temperature": 0}).encode()
    request = urllib.request.Request(
        endpoint, data=payload, headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


@dataclass
class ToolRecorder:
    db: Session
    calls: list[dict[str, Any]]

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in TOOL_FUNCTIONS:
            result = {"found": False, "records": [], "error": f"Unknown tool: {name}"}
        else:
            try:
                result = TOOL_FUNCTIONS[name](self.db, **arguments)
            except (TypeError, ValueError) as exc:
                result = {"found": False, "records": [], "error": str(exc)}
        ref = f"tool_call_{len(self.calls) + 1}"
        call = {"ref": ref, "name": name, "arguments": arguments, "result": result}
        self.calls.append(call)
        write_audit(
            self.db, actor="agent", action="agent_tool_call", entity_type="AgentTool",
            entity_id=ref, inputs={"name": name, "arguments": arguments},
            formula="Read-only grounded tool execution",
            output={"found": result.get("found", False), "record_ids": _ids(result)},
        )
        return result


def _ids(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"id", "record_id", "invoice_id", "payment_id", "po_id"} and isinstance(item, str):
                result.append(item)
            result.extend(_ids(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(_ids(item))
    return sorted(set(result))


def _message(response: dict[str, Any]) -> dict[str, Any]:
    if "choices" in response:
        return response["choices"][0]["message"]
    return response.get("message", response)


def _template(recorder: ToolRecorder, exception_id: str) -> InvestigationResult:
    exception_result = recorder.call("get_exception", {"record_id": exception_id})
    record = exception_result.get("record") or {}
    evidence = record.get("evidence", [])
    record_ids = [item["record_id"] for item in evidence if item.get("record_id")]
    refs = ["tool_call_1"]
    for item in evidence:
        record_type = item.get("record_type")
        if record_type in {"invoice", "payment", "purchase_order"}:
            recorder.call(f"get_{'purchase_order' if record_type == 'purchase_order' else record_type}",
                          {"record_id": item["record_id"]})
            refs.append(f"tool_call_{len(recorder.calls)}")

    difference_ref = None
    if record.get("type") in {"PARTIAL_PAYMENT", "OVERPAYMENT"}:
        invoice_id = record.get("invoice_id")
        payment_id = record.get("payment_id")
        if invoice_id and payment_id:
            recorder.call("calculate_difference", {"a_id": invoice_id, "b_id": payment_id})
            difference_ref = f"tool_call_{len(recorder.calls)}"

    exception_type = record.get("type")
    if exception_type == "MISSING_PAYMENT":
        text = "No payment record was returned for the invoice; the investigation is unresolved."
        verdict = "unresolved"
        action = "request_info"
    elif exception_type in {"PARTIAL_PAYMENT", "OVERPAYMENT"} and difference_ref:
        text = f"The linked invoice and payment differ by {{difference:{difference_ref}}}; the difference is grounded in returned records."
        verdict = "explained"
        action = "propose_adjustment" if exception_type == "PARTIAL_PAYMENT" else "request_info"
    elif exception_type in {"DUPLICATE_INVOICE", "DUPLICATE_PAYMENT"}:
        for record_id in record_ids:
            recorder.call("find_duplicates", {"record_id": record_id})
            refs.append(f"tool_call_{len(recorder.calls)}")
        text = "A duplicate record was returned by the duplicate search; the exception is explained."
        verdict = "explained"
        action = "mark_duplicate"
    else:
        text = "The persisted evidence was inspected, but the exception remains unresolved."
        verdict = "unresolved"
        action = "escalate"
    return InvestigationResult(
        exception_id=exception_id, verdict=verdict, claims=[
            {"text": text, "record_ids": record_ids, "tool_call_refs": sorted(set(refs))},
        ], proposed_action=action, draft_note="Template investigation grounded in persisted tool outputs.",
    )


def _llm_result(recorder: ToolRecorder, exception_id: str, errors: list[str]) -> InvestigationResult:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Investigate exception {exception_id}. Use tools before returning the JSON result."},
    ]
    for retry in range(2):
        try:
            for _ in range(6):
                response = _message(call_llm(messages, TOOL_SCHEMAS))
                calls = response.get("tool_calls", [])
                if not calls:
                    if response.get("content") is None:
                        raise VerificationFailure("LLM returned neither tool calls nor a final result")
                    candidate = parse_result(response["content"].replace("```json", "").replace("```", "").strip())
                    if candidate.exception_id != exception_id:
                        raise VerificationFailure("LLM returned a different exception_id")
                    return verify_and_render(recorder.db, candidate, recorder.calls, source="llm")
                messages.append({"role": "assistant", "content": response.get("content"), "tool_calls": calls})
                for requested in calls:
                    function = requested.get("function", {})
                    name = function.get("name", "")
                    arguments = json.loads(function.get("arguments", "{}"))
                    result = recorder.call(name, arguments)
                    messages.append({
                        "role": "tool", "tool_call_id": requested.get("id", ""), "content": json.dumps(result),
                    })
            raise VerificationFailure("LLM exceeded the six-step tool-calling limit")
        except (VerificationFailure, KeyError, TypeError, ValueError) as exc:
            errors.append(str(exc))
            if retry == 0:
                messages.append({"role": "user", "content": "The previous result failed verification. Errors: " + "; ".join(errors)})
    raise VerificationFailure("LLM did not produce a verified result")


def investigate_exception(db: Session, exception_id: str) -> AgentRun:
    errors: list[str] = []
    recorder = ToolRecorder(db, [])
    if os.getenv("LLM_API_KEY") and os.getenv("LLM_MODEL"):
        try:
            result = _llm_result(recorder, exception_id, errors)
            source = "llm"
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            errors.append(str(exc))
            write_audit(
                db, actor="agent", action="agent_verification_failure", entity_type="ExceptionCase",
                entity_id=exception_id, inputs={"errors": errors}, formula="Post-hoc grounded verification",
                output={"fallback": "template"},
            )
            result = _template(recorder, exception_id)
            result = verify_and_render(db, result, recorder.calls, source="template")
            source = "template"
    else:
        result = _template(recorder, exception_id)
        result = verify_and_render(db, result, recorder.calls, source="template")
        source = "template"

    run = AgentRun(
        exception_id=exception_id, verdict=result.verdict, explanation=as_json(result),
        claims=[claim.model_dump() for claim in result.claims], tool_calls=recorder.calls,
        source=source, verification_status="verified", errors=errors, status="pending",
    )
    db.add(run)
    db.flush()
    write_audit(
        db, actor="agent", action="agent_investigation", entity_type="AgentRun",
        entity_id=run.id, inputs={"exception_id": exception_id, "source": source},
        formula="Grounded investigation with verified tool citations",
        output={"verdict": result.verdict, "verification_status": run.verification_status},
    )
    db.commit()
    return run
