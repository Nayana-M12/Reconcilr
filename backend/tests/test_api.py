from app.api.audit import audit
from app.api.summary import summary
from app.models import AuditLog, ExceptionCase, Match


def test_summary_counts(db):
    db.add_all([
        Match(invoice_id="invoice", tier="exact", confidence="1", matched_amount="10"),
        ExceptionCase(type="MISSING_PO", status="open", severity="low", description="missing"),
        ExceptionCase(type="MISSING_PO", status="resolved", severity="low", description="resolved"),
    ])
    db.commit()
    assert summary(db) == {
        "matches": 1,
        "open_exceptions": 1,
        "resolved_exceptions": 1,
        "pending_adjustments": 0,
    }


def test_audit_filters_and_limits(db):
    db.add_all([
        AuditLog(actor="system", action="one", entity_type="Invoice", entity_id="1",
                 inputs={}, formula="f", output={}),
        AuditLog(actor="system", action="two", entity_type="Adjustment", entity_id="2",
                 inputs={}, formula="f", output={}),
    ])
    db.commit()
    result = audit(entity_type="Adjustment", limit=1, db=db)
    assert len(result) == 1
    assert result[0]["action"] == "two"
