from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[1]))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.investigate import investigate_exception
from app.ai.suggestions import suggest_near_duplicates, suggest_vendor_aliases
from app.database import Base
from app.extraction import parse_document, read_document_text
from app.models import Evidence, ExceptionCase, Invoice, Match, Payment, PurchaseOrder
from app.services.exceptions.engine import run_exceptions
from app.services.importer import import_records
from app.services.matching.engine import run_matching
from app.synthetic.generator import generate


def build_report() -> dict[str, Any]:
    with TemporaryDirectory() as temporary_directory:
        data = Path(temporary_directory)
        generate(data, seed=42, vendor_count=5, invoice_count=20)
        truth = json.loads((data / "ground_truth.json").read_text(encoding="utf-8"))
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            for record_type, filename in (
                ("vendor", "vendors.csv"),
                ("purchase_order", "purchase_orders.csv"),
                ("invoice", "invoices.csv"),
                ("payment", "payments.csv"),
            ):
                import_records(db, record_type, filename, (data / filename).read_bytes())
            run_matching(db)
            run_exceptions(db)
            matching = _matching_metrics(db, truth)
            duplicates = _duplicate_metrics(db, truth)
            exceptions = _exception_metrics(db, truth)
            similarity = _similarity_metrics(db, truth)
            agent = _agent_metrics(db)
    extraction = _extraction_metrics()
    return {
        "matching": matching,
        "duplicates": duplicates,
        "exceptions": exceptions,
        "similarity": similarity,
        "hallucination_rate": agent["hallucination_rate"],
        "unresolved_correctness": agent["unresolved_correctness"],
        "extraction_accuracy": extraction["overall_accuracy"],
        "extraction_by_field": extraction["by_field"],
        "extraction_status": extraction["status"],
    }


def _extraction_metrics() -> dict[str, Any]:
    fixtures_dir = Path(__file__).parents[1] / "tests" / "fixtures" / "documents"
    labels_path = fixtures_dir / "labels.json"
    if not labels_path.exists():
        return {"overall_accuracy": None, "by_field": {}, "status": "fixtures not found"}
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    field_totals: dict[str, int] = {}
    field_correct: dict[str, int] = {}
    for spec in labels.get("documents", []):
        doc_path = fixtures_dir / spec["filename"]
        pages = read_document_text(spec["filename"], doc_path.read_bytes())
        extracted = parse_document(pages)
        found = extracted.fields_found_dict()
        for field_name, expected_val in spec.get("expected", {}).items():
            field_totals[field_name] = field_totals.get(field_name, 0) + 1
            if found.get(field_name) == expected_val:
                field_correct[field_name] = field_correct.get(field_name, 0) + 1
        for missing_field in spec.get("expected_missing", []):
            field_totals[missing_field] = field_totals.get(missing_field, 0) + 1
            if missing_field in extracted.fields_missing and missing_field not in found:
                field_correct[missing_field] = field_correct.get(missing_field, 0) + 1
    by_field: dict[str, dict[str, float | int]] = {}
    total_checks = 0
    total_correct = 0
    for field_name in sorted(field_totals):
        total = field_totals[field_name]
        correct = field_correct.get(field_name, 0)
        total_checks += total
        total_correct += correct
        by_field[field_name] = {
            "correct": correct,
            "total": total,
            "accuracy": correct / total if total else 1.0,
        }
    return {
        "overall_accuracy": total_correct / total_checks if total_checks else None,
        "by_field": by_field,
        "status": "evaluated",
    }


def _similarity_metrics(db: Session, truth: dict[str, Any]) -> dict[str, Any]:
    expected_aliases = {
        frozenset(label["record_ids"].values())
        for label in truth.get("vendor_aliases", [])
    }
    actual_aliases = {
        frozenset(candidate["record_ids"])
        for candidate in suggest_vendor_aliases(db)
    }
    expected_duplicates = {
        frozenset(label["record_ids"].values())
        for label in truth.get("near_duplicates", [])
    }
    actual_duplicates = {
        frozenset(candidate["record_ids"])
        for candidate in suggest_near_duplicates(db)
    }

    def metrics(expected: set[frozenset[str]], actual: set[frozenset[str]]) -> dict[str, Any]:
        true_positive = len(expected & actual)
        return {
            "precision": true_positive / len(actual) if actual else 1.0,
            "recall": true_positive / len(expected) if expected else 1.0,
            "expected_count": len(expected),
            "actual_count": len(actual),
            "false_positives": sorted([sorted(pair) for pair in actual - expected]),
            "false_negatives": sorted([sorted(pair) for pair in expected - actual]),
        }

    return {
        "vendor_aliases": metrics(expected_aliases, actual_aliases),
        "near_duplicates": metrics(expected_duplicates, actual_duplicates),
    }


def _matching_metrics(db: Session, truth: dict[str, Any]) -> dict[str, Any]:
    invoices = list(db.scalars(select(Invoice)))
    orders = list(db.scalars(select(PurchaseOrder)))
    payments = list(db.scalars(select(Payment)))
    errors = truth["errors"]
    duplicate_copy_ids = {
        error["record_ids"]["duplicate_invoice_id"]
        for error in errors if error["type"] == "DUPLICATE_INVOICE"
    }
    missing_po_ids = {
        error["record_ids"]["invoice_id"]
        for error in errors if error["type"] == "MISSING_PO"
    }
    excluded_payment_pairs = {
        (error["record_ids"]["invoice_id"], error["record_ids"].get("payment_id"))
        for error in errors
        if error["type"] in {"PARTIAL_PAYMENT", "OVERPAYMENT", "DATE_GAP", "MISSING_PAYMENT"}
    }
    expected: set[tuple[str, str, str]] = set()
    for invoice in invoices:
        if invoice.id in duplicate_copy_ids:
            continue
        if invoice.id not in missing_po_ids and invoice.po_number:
            order = next((item for item in orders if item.vendor_id == invoice.vendor_id
                          and item.po_number == invoice.po_number), None)
        else:
            order = None
        if order is not None:
            expected.add((invoice.id, order.id, "purchase_order"))
        payment_ref = invoice.invoice_number.casefold().replace("inv", "pay", 1)
        payment = next((item for item in payments if item.vendor_id == invoice.vendor_id
                        and item.reference.casefold() == payment_ref), None)
        if payment is not None and (invoice.id, payment.id) not in excluded_payment_pairs:
            expected.add((invoice.id, payment.id, "payment"))
    actual_rows = list(db.scalars(select(Match)))
    actual = {
        (item.invoice_id, item.po_id or item.payment_id or "", "purchase_order" if item.po_id else "payment")
        for item in actual_rows
    }
    true_positive = len(actual & expected)
    return {
        "precision": true_positive / len(actual) if actual else 1.0,
        "recall": true_positive / len(expected) if expected else 1.0,
        "expected_count": len(expected),
        "actual_count": len(actual),
        "false_positives": [
            {"invoice_id": invoice_id, "counterpart_id": counterpart_id, "record_type": record_type,
             "tier": next((item.tier for item in actual_rows
                           if item.invoice_id == invoice_id
                           and (item.po_id or item.payment_id) == counterpart_id), None)}
            for invoice_id, counterpart_id, record_type in sorted(actual - expected)
        ],
        "false_negatives": [
            {"invoice_id": invoice_id, "counterpart_id": counterpart_id, "record_type": record_type}
            for invoice_id, counterpart_id, record_type in sorted(expected - actual)
        ],
    }


def _exception_metrics(db: Session, truth: dict[str, Any]) -> dict[str, Any]:
    expected: dict[str, int] = {}
    for error in truth["errors"]:
        exception_type = "VENDOR_MISMATCH" if error["type"] == "VENDOR_NAME_TYPO" else error["type"]
        expected[exception_type] = expected.get(exception_type, 0) + 1
    detected: dict[str, int] = {}
    suggestion_invoice_ids = {
        label["record_ids"]["near_duplicate_invoice_id"]
        for label in truth.get("near_duplicates", [])
    }
    for case in db.scalars(select(ExceptionCase)):
        if case.invoice_id in suggestion_invoice_ids:
            continue
        detected[case.type] = detected.get(case.type, 0) + 1
    by_type: dict[str, dict[str, float | int]] = {}
    for exception_type in sorted(set(expected) | set(detected)):
        expected_count = expected.get(exception_type, 0)
        detected_count = detected.get(exception_type, 0)
        true_positive = min(expected_count, detected_count)
        by_type[exception_type] = {
            "expected": expected_count,
            "detected": detected_count,
            "precision": true_positive / detected_count if detected_count else 1.0 if expected_count == 0 else 0.0,
            "recall": true_positive / expected_count if expected_count else 1.0,
        }
    return {"by_type": by_type}


def _duplicate_metrics(db: Session, truth: dict[str, Any]) -> dict[str, float]:
    expected = {
        frozenset(error["record_ids"].values())
        for error in truth["errors"]
        if error["type"] in {"DUPLICATE_INVOICE", "DUPLICATE_PAYMENT"}
    }
    actual = set()
    for case in db.scalars(select(ExceptionCase).where(ExceptionCase.type.like("DUPLICATE_%"))):
        actual.add(frozenset(item.record_id for item in db.scalars(
            select(Evidence).where(Evidence.exception_id == case.id)
        )))
    true_positive = len(actual & expected)
    return {
        "detection_rate": true_positive / len(expected) if expected else 1.0,
        "false_positives": float(len(actual - expected)),
    }


def _agent_metrics(db: Session) -> dict[str, float]:
    cases = list(db.scalars(select(ExceptionCase).where(ExceptionCase.status == "open")))
    runs = [investigate_exception(db, case.id) for case in cases]
    hallucinations = sum(1 for run in runs if run.verification_status != "verified")
    unresolved_types = {"MISSING_PAYMENT", "MISSING_PO"}
    expected_unresolved = {case.id for case in cases if case.type in unresolved_types}
    unresolved_correct = sum(
        1 for run in runs
        if run.exception_id in expected_unresolved and run.verdict == "unresolved"
    )
    return {
        "hallucination_rate": hallucinations / len(runs) if runs else 0.0,
        "unresolved_correctness": unresolved_correct / len(expected_unresolved)
        if expected_unresolved else 1.0,
    }


def markdown(report: dict[str, Any]) -> str:
    return "\n".join([
        "# Reconcilr evaluation",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Matching precision | {report['matching']['precision']} |",
        f"| Matching recall | {report['matching']['recall']} |",
        f"| Duplicate detection rate | {report['duplicates']['detection_rate']} |",
        f"| Duplicate false positives | {report['duplicates']['false_positives']} |",
        f"| Hallucination rate | {report['hallucination_rate']} |",
        f"| Unresolved correctness | {report['unresolved_correctness']} |",
        f"| Extraction accuracy | {report['extraction_accuracy']} ({report['extraction_status']}) |",
        "",
        "## Exception detection by type",
        "",
        "| Type | Expected | Detected | Precision | Recall |",
        "| --- | ---: | ---: | ---: | ---: |",
        *[
            f"| {exception_type} | {metrics['expected']} | {metrics['detected']} | "
            f"{metrics['precision']} | {metrics['recall']} |"
            for exception_type, metrics in report["exceptions"]["by_type"].items()
        ],
        "",
        "## AI similarity suggestions",
        "",
        "| Suggestion type | Precision | Recall | Expected | Detected |",
        "| --- | ---: | ---: | ---: | ---: |",
        *[
            f"| {kind} | {metrics['precision']} | {metrics['recall']} | "
            f"{metrics['expected_count']} | {metrics['actual_count']} |"
            for kind, metrics in report["similarity"].items()
        ],
        "",
        (
            "Label source: expected values come from the generated `ground_truth.json` labels. "
            "Clean invoice/PO and invoice/payment identity pairs are included; labeled "
            "partial-payment, overpayment, date-gap, missing-payment, missing-PO, and "
            "duplicate-copy records are excluded. Matcher output is used only as actual output."
        ),
        "",
        "## Document extraction accuracy by field",
        "",
        "| Field | Correct | Total | Accuracy |",
        "| --- | ---: | ---: | ---: |",
        *[
            f"| {field} | {metrics['correct']} | {metrics['total']} | {metrics['accuracy']} |"
            for field, metrics in report.get("extraction_by_field", {}).items()
        ],
        "",
        "Extraction labels come from `backend/tests/fixtures/documents/labels.json`, never from parser output.",
    ])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--markdown-out", type=Path, default=None)
    args = parser.parse_args()
    report = build_report()
    output = json.dumps(report, indent=2)
    print(output)
    if args.json_out:
        args.json_out.write_text(output + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.write_text(markdown(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
