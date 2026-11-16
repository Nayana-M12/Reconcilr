from __future__ import annotations

import json
import math
import os
import re
import urllib.request
from dataclasses import dataclass

from rapidfuzz.fuzz import token_set_ratio

from app.services.privacy import redaction_enabled

_COMPANY_SUFFIXES = {
    "corp", "corporation", "inc", "incorporated", "llc", "ltd", "limited",
    "co", "company", "pvt", "private",
}


@dataclass(frozen=True)
class SimilarityResult:
    score: float
    reason: str
    source: str


def normalize_company_name(value: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", value.casefold())
    return " ".join(token for token in tokens if token not in _COMPANY_SUFFIXES)


def _rapidfuzz_similarity(left: str, right: str, kind: str) -> SimilarityResult:
    left_normalized = normalize_company_name(left) if kind == "vendor" else left.casefold().strip()
    right_normalized = normalize_company_name(right) if kind == "vendor" else right.casefold().strip()
    score = token_set_ratio(left_normalized, right_normalized) / 100
    reason = (
        "Normalized vendor names have the same core tokens."
        if kind == "vendor" and left_normalized == right_normalized
        else f"Offline RapidFuzz similarity of normalized {kind} text."
    )
    return SimilarityResult(round(score, 4), reason, "rapidfuzz")


def _embedding_similarity(left: str, right: str, model: str, key: str, kind: str) -> SimilarityResult:
    payload = json.dumps({"model": model, "input": [left, right]}).encode("utf-8")
    request = urllib.request.Request(
        os.getenv("EMBEDDING_API_URL", "https://api.openai.com/v1/embeddings"),
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = json.loads(response.read().decode("utf-8"))
    vectors = [item["embedding"] for item in sorted(body["data"], key=lambda item: item["index"])]
    numerator = sum(left_value * right_value for left_value, right_value in zip(*vectors))
    left_norm = math.sqrt(sum(value * value for value in vectors[0]))
    right_norm = math.sqrt(sum(value * value for value in vectors[1]))
    score = numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0
    return SimilarityResult(round(max(0.0, min(1.0, score)), 4), f"Embedding similarity for {kind} text.", "embedding")


def _model_similarity(left: str, right: str, kind: str) -> SimilarityResult:
    key = os.getenv("LLM_API_KEY")
    llm_model = os.getenv("LLM_MODEL")
    embedding_model = os.getenv("EMBEDDING_MODEL")
    if not key or not llm_model and not embedding_model:
        return _rapidfuzz_similarity(left, right, kind)
    if embedding_model and not llm_model:
        try:
            return _embedding_similarity(left, right, embedding_model, key, kind)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, ZeroDivisionError):
            return _rapidfuzz_similarity(left, right, kind)
    model = llm_model
    assert model is not None
    payload = json.dumps({
        "model": model,
        "messages": [{
            "role": "user",
            "content": (
                "Compare these two pieces of text for likely same-entity identity. "
                "Return JSON only with score (0 to 1) and a short reason. "
                f"Kind: {kind}. Left: {left}. Right: {right}."
            ),
        }],
        "temperature": 0,
    }).encode("utf-8")
    request = urllib.request.Request(
        os.getenv("LLM_API_URL", "https://api.openai.com/v1/chat/completions"),
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        result = json.loads(content)
        score = float(result["score"])
        reason = str(result["reason"]).strip()
        if not 0 <= score <= 1 or not reason:
            raise ValueError("model returned an invalid similarity result")
        return SimilarityResult(round(score, 4), reason, "llm")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return _rapidfuzz_similarity(left, right, kind)


def compare_text(left: str, right: str, kind: str = "vendor") -> SimilarityResult:
    if kind not in {"vendor", "invoice"}:
        raise ValueError("kind must be vendor or invoice")
    if not left.strip() or not right.strip():
        return SimilarityResult(0.0, "One or both values are empty.", "rapidfuzz")
    if redaction_enabled():
        return _rapidfuzz_similarity(left, right, kind)
    return _model_similarity(left, right, kind)
