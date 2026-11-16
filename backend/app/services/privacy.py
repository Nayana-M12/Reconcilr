from __future__ import annotations

import os
import re
from contextvars import ContextVar
from typing import Any

_mapping: ContextVar[dict[str, str] | None] = ContextVar("privacy_mapping", default=None)
_reverse_mapping: ContextVar[dict[str, str] | None] = ContextVar("privacy_reverse_mapping", default=None)
_counters: ContextVar[dict[str, int] | None] = ContextVar("privacy_counters", default=None)


def redaction_enabled() -> bool:
    return os.getenv("LLM_REDACT", "0") == "1"


def _placeholder(key: str, value: str) -> str:
    mapping = dict(_mapping.get() or {})
    reverse = dict(_reverse_mapping.get() or {})
    counters = dict(_counters.get() or {})
    if value not in mapping:
        prefix = "BANK" if any(word in key.casefold() for word in ("bank", "iban", "swift", "routing", "account")) else "VENDOR"
        counters[prefix] = counters.get(prefix, 0) + 1
        mapping[value] = f"{prefix}_{counters[prefix]:03d}"
        reverse[mapping[value]] = value
        _mapping.set(mapping)
        _reverse_mapping.set(reverse)
        _counters.set(counters)
    return mapping[value]


def _sensitive_key(key: str) -> bool:
    lowered = key.casefold()
    return (
        lowered in {"name", "vendor", "vendor_name", "company_name", "payee", "beneficiary"}
        or any(word in lowered for word in ("bank", "iban", "swift", "routing", "account"))
    )


def redact(value: Any) -> Any:
    if not redaction_enabled():
        return value
    if isinstance(value, dict):
        return {
            key: _placeholder(str(key), item) if _sensitive_key(str(key)) and isinstance(item, str)
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value


def redact_text(value: str, kind: str = "vendor") -> str:
    if not redaction_enabled():
        return value
    return _placeholder(kind, value)


def restore(value: Any) -> Any:
    if not redaction_enabled():
        return value
    reverse = _reverse_mapping.get() or {}
    if isinstance(value, str):
        return re.sub(r"\b(?:VENDOR|BANK)_\d{3}\b", lambda match: reverse.get(match.group(), match.group()), value)
    if isinstance(value, list):
        return [restore(item) for item in value]
    if isinstance(value, dict):
        return {key: restore(item) for key, item in value.items()}
    return value
