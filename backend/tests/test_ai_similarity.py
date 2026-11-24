from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.ai import similarity
from app.ai.suggestions import suggest_vendor_aliases
from app.api.ai import DecisionRequest, _persist_suggestions, accept_suggestion
from app.models import AISuggestion, Invoice, Match, Vendor


def _vendors(db) -> tuple[Vendor, Vendor]:
    left = Vendor(id="ven-left", name="Acme Corp", normalized_name="acmecorp")
    right = Vendor(id="ven-right", name="ACME Corporation Pvt Ltd", normalized_name="acmecorporationpvtltd")
    db.add_all([left, right])
    db.commit()
    return left, right


def test_offline_similarity_normalizes_company_suffixes(db, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    result = similarity.compare_text("Acme Corp", "ACME Corporation Pvt Ltd")
    assert result.score == 1
    assert result.source == "rapidfuzz"


def test_mocked_model_similarity_is_used(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test")
    monkeypatch.setenv("LLM_MODEL", "test")
    monkeypatch.setattr(
        similarity,
        "_model_similarity",
        lambda left, right, kind: similarity.SimilarityResult(0.91, "mocked", "llm"),
    )
    result = similarity.compare_text("one", "two")
    assert result == similarity.SimilarityResult(0.91, "mocked", "llm")


def test_fake_record_id_is_rejected(db, analyst_user):
    suggestion = AISuggestion(
        kind="vendor_alias",
        record_ids=["fake-vendor", "real-vendor"],
        payload={"record_ids": ["fake-vendor", "real-vendor"]},
        score=Decimal("0.9000"),
        reason="test",
        source="rapidfuzz",
    )
    db.add(suggestion)
    db.commit()
    with pytest.raises(HTTPException) as error:
        accept_suggestion(suggestion.id, DecisionRequest(), db, user=analyst_user)
    assert error.value.status_code == 400


def test_accepting_vendor_alias_twice_returns_conflict(db, analyst_user):
    _vendors(db)
    suggestions = _persist_suggestions(db, suggest_vendor_aliases(db))
    assert suggestions
    suggestion_id = suggestions[0]["id"]
    accept_suggestion(suggestion_id, DecisionRequest(), db, user=analyst_user)
    with pytest.raises(HTTPException) as error:
        accept_suggestion(suggestion_id, DecisionRequest(), db, user=analyst_user)
    assert error.value.status_code == 409


def test_suggestions_do_not_change_existing_matches(db):
    vendor, _ = _vendors(db)
    invoice = Invoice(
        id="inv-1", vendor_id=vendor.id, invoice_number="INV-1", po_number=None,
        amount=Decimal("10.00"), currency="USD", invoice_date=date(2026, 1, 1),
        source_file="test.csv", raw_row={}, dedupe_hash="hash-1",
    )
    db.add(invoice)
    db.add(Match(
        invoice_id=invoice.id, tier="exact", confidence=Decimal("1.0000"),
        matched_amount=Decimal("10.00"),
    ))
    db.commit()
    before = [(item.invoice_id, item.po_id, item.payment_id, item.tier)
              for item in db.scalars(select(Match))]
    suggest_vendor_aliases(db)
    after = [(item.invoice_id, item.po_id, item.payment_id, item.tier)
             for item in db.scalars(select(Match))]
    assert after == before
