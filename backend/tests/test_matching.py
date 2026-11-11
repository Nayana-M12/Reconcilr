import json
from pathlib import Path

from sqlalchemy import select

from app.models import AuditLog, Match
from app.services.importer import import_records
from app.services.matching.engine import run_matching


def _import_fixture(db) -> dict:
    data = Path(__file__).parents[1] / "data"
    counts = {}
    for record_type, filename in (
        ("vendor", "vendors.csv"),
        ("purchase_order", "purchase_orders.csv"),
        ("invoice", "invoices.csv"),
        ("payment", "payments.csv"),
    ):
        result = import_records(db, record_type, filename, (data / filename).read_bytes())
        counts[record_type] = result["imported"]
    return counts


def test_synthetic_matching_precision_recall_and_duplicate_protection(db):
    counts = _import_fixture(db)
    result = run_matching(db)
    matches = list(db.scalars(select(Match)))
    truth = json.loads((Path(__file__).parents[1] / "data" / "ground_truth.json").read_text())

    expected = {
        *((f"inv-{index:06d}", f"po-{index:06d}") for index in range(20) if index != 3),
        *((f"inv-{index:06d}", f"pay-{index:06d}") for index in range(20) if index not in {1, 2, 4, 6}),
    }
    actual = {
        (match.invoice_id, match.po_id or match.payment_id)
        for match in matches
    }
    true_positives = len(actual & expected)
    precision = true_positives / len(actual)
    recall = true_positives / len(expected)

    assert counts == {"vendor": 5, "purchase_order": 20, "invoice": 21, "payment": 19}
    assert len(matches) == len(expected) == 35
    assert precision >= 0.95
    assert recall >= 0.95
    assert len({match.invoice_id for match in matches}) == 20
    assert result.unmatched_invoice_ids == ["inv-000020"]
    assert truth["errors"][0]["type"] == "DUPLICATE_INVOICE"
    assert not any(match.invoice_id == "inv-000020" for match in matches)


def test_matching_tier_ordering_and_idempotency(db):
    _import_fixture(db)
    first = run_matching(db)
    second = run_matching(db)

    assert first.tier_counts == {"exact": 19, "tolerance": 16, "fuzzy": 0}
    assert second.created == 0
    assert second.existing == 35
    assert db.query(Match).count() == 35
    assert db.query(AuditLog).filter(AuditLog.action == "match_decision").count() == 72
