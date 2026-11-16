import hashlib
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Invoice, Payment, PurchaseOrder, Vendor
from app.schemas.imports import ImportRow, VendorImportRow
from app.services.audit import write_audit


def normalize_vendor_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def compute_dedupe_hash(vendor_name: str, invoice_number: str, amount: Decimal, invoice_date: date) -> str:
    payload = "|".join(
        (normalize_vendor_name(vendor_name), invoice_number.strip().casefold(), str(amount), invoice_date.isoformat())
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_file(filename: str, content: bytes) -> pd.DataFrame:
    suffix = Path(filename).suffix.casefold()
    if suffix == ".csv":
        from io import BytesIO

        return pd.read_csv(BytesIO(content), dtype=str, keep_default_na=False)
    if suffix in {".xlsx", ".xls"}:
        from io import BytesIO

        if suffix == ".xlsx":
            from openpyxl import load_workbook

            workbook = load_workbook(BytesIO(content), read_only=True, data_only=False)
            worksheet = workbook.active
            rows = list(worksheet.values)
            workbook.close()
            if not rows:
                return pd.DataFrame()
            headers = [str(value) if value is not None else "" for value in rows[0]]
            return pd.DataFrame(rows[1:], columns=headers).fillna("")
        return pd.read_excel(BytesIO(content), dtype=str).fillna("")
    raise ValueError("Only CSV and Excel (.xlsx/.xls) files are supported")


def _as_dict(row: pd.Series) -> dict[str, Any]:
    return {str(key): (None if pd.isna(value) or value == "" else value) for key, value in row.items()}


def _required(record_type: str, row: ImportRow) -> str | None:
    if not row.vendor_id and not row.vendor_name:
        return "vendor_id or vendor_name is required"
    if record_type == "invoice" and (not row.invoice_number or not row.invoice_date):
        return "invoice_number and invoice_date are required"
    if record_type == "purchase_order" and (not row.po_number or not row.order_date):
        return "po_number and order_date are required"
    if record_type == "payment" and (not row.reference or not row.payment_date):
        return "reference and payment_date are required"
    return None


def import_records(db: Session, record_type: str, filename: str, content: bytes, actor: str | None = None) -> dict[str, Any]:
    valid_record_types = {"vendor", "invoice", "purchase_order", "payment"}
    if record_type not in valid_record_types:
        raise ValueError("record_type must be vendor, purchase_order, invoice, or payment")
    frame = _read_file(filename, content)
    imported_ids: list[str] = []
    errors: list[dict[str, Any]] = []
    duplicate_count = 0
    actor = actor or get_settings().audit_actor
    for row_number, series in enumerate(frame.to_dict(orient="records"), start=2):
        raw = {str(key): (None if pd.isna(value) or value == "" else value) for key, value in series.items()}
        try:
            with db.begin_nested():
                if record_type == "vendor":
                    vendor_row = VendorImportRow.model_validate(raw)
                    existing = _find_existing_vendor(db, vendor_row)
                    if existing:
                        raise DuplicateRow(existing.id)
                    entity = _resolve_or_create_vendor(db, vendor_row)
                else:
                    row = ImportRow.model_validate(raw)
                    error = _required(record_type, row)
                    if error:
                        raise ValueError(error)
                    existing = _find_existing_record(db, record_type, row)
                    if existing:
                        raise DuplicateRow(existing.id)
                    vendor = _resolve_vendor(db, row)
                    entity = _create_record(db, record_type, row, raw, filename, vendor)
                db.flush()
                imported_ids.append(entity.id)
                write_audit(
                    db,
                    actor=actor,
                    action="import",
                    entity_type=type(entity).__name__,
                    entity_id=entity.id,
                    inputs=raw,
                    formula="Validated row and persisted record",
                    output={"record_id": entity.id, "record_type": record_type},
                )
        except DuplicateRow as exc:
            duplicate_count += 1
            errors.append({"row": row_number, "errors": [f"duplicate of {exc.record_id}"]})
        except (ValidationError, ValueError, TypeError, IntegrityError, SQLAlchemyError) as exc:
            errors.append({"row": row_number, "errors": [str(exc)]})
    db.commit()
    write_audit(
        db,
        actor=actor,
        action="import_summary",
        entity_type="Import",
        entity_id=filename,
        inputs={"record_type": record_type, "source_file": filename},
        formula="imported rows + rejected rows = total rows",
        output={
            "imported": len(imported_ids),
            "rejected": len(errors),
            "duplicates": duplicate_count,
            "total": len(frame),
        },
    )
    db.commit()
    return {
        "record_type": record_type,
        "source_file": filename,
        "imported": len(imported_ids),
        "rejected": len(errors),
        "duplicates": duplicate_count,
        "errors": errors,
        "ids": imported_ids,
    }


class DuplicateRow(Exception):
    def __init__(self, record_id: str) -> None:
        self.record_id = record_id
        super().__init__(f"duplicate of {record_id}")


def _find_existing_vendor(db: Session, row: VendorImportRow) -> Vendor | None:
    if row.id:
        existing = db.get(Vendor, row.id)
        if existing:
            return existing
    normalized = normalize_vendor_name(row.name)
    return db.scalar(select(Vendor).where(Vendor.normalized_name == normalized))


def _find_existing_record(db: Session, record_type: str, row: ImportRow) -> Invoice | PurchaseOrder | Payment | None:
    model = {"invoice": Invoice, "purchase_order": PurchaseOrder, "payment": Payment}[record_type]
    if row.id:
        existing = db.get(model, row.id)
        if existing:
            return existing
        if record_type == "invoice":
            return None
    if record_type == "invoice":
        vendor = _resolve_vendor(db, row)
        assert row.invoice_number and row.invoice_date
        dedupe_hash = compute_dedupe_hash(vendor.name, row.invoice_number, row.amount, row.invoice_date)
        return db.scalar(select(Invoice).where(Invoice.dedupe_hash == dedupe_hash))
    return None


def _resolve_vendor(db: Session, row: ImportRow) -> Vendor:
    if row.vendor_id:
        vendor = db.get(Vendor, row.vendor_id)
        if vendor is None:
            raise ValueError(f"unknown vendor_id: {row.vendor_id}")
        return vendor
    assert row.vendor_name is not None
    normalized = normalize_vendor_name(row.vendor_name)
    vendor = db.scalar(select(Vendor).where(Vendor.normalized_name == normalized))
    if vendor is None:
        vendor = Vendor(name=row.vendor_name, normalized_name=normalized)
        db.add(vendor)
        db.flush()
    return vendor


def _resolve_or_create_vendor(db: Session, row: VendorImportRow) -> Vendor:
    normalized = normalize_vendor_name(row.name)
    vendor = db.get(Vendor, row.id) if row.id else None
    if vendor is None:
        vendor = db.scalar(select(Vendor).where(Vendor.normalized_name == normalized))
    if vendor is None:
        vendor = Vendor(
            id=row.id,
            name=row.name,
            normalized_name=row.normalized_name or normalized,
        )
        db.add(vendor)
        db.flush()
    return vendor


def _create_record(
    db: Session, record_type: str, row: ImportRow, raw: dict[str, Any], filename: str, vendor: Vendor
) -> Invoice | PurchaseOrder | Payment:
    if record_type == "invoice":
        assert row.invoice_number and row.invoice_date
        record = Invoice(
            id=row.id,
            vendor_id=vendor.id,
            invoice_number=row.invoice_number,
            po_number=row.po_number,
            amount=row.amount,
            currency=row.currency,
            invoice_date=row.invoice_date,
            due_date=row.due_date,
            source_file=filename,
            raw_row=raw,
            dedupe_hash=compute_dedupe_hash(vendor.name, row.invoice_number, row.amount, row.invoice_date),
        )
    elif record_type == "purchase_order":
        assert row.po_number and row.order_date
        record = PurchaseOrder(
            id=row.id,
            vendor_id=vendor.id,
            po_number=row.po_number,
            amount=row.amount,
            currency=row.currency,
            order_date=row.order_date,
            raw_row=raw,
        )
    else:
        assert row.reference and row.payment_date
        record = Payment(
            id=row.id,
            vendor_id=vendor.id,
            reference=row.reference,
            amount=row.amount,
            currency=row.currency,
            payment_date=row.payment_date,
            raw_row=raw,
        )
    db.add(record)
    return record
