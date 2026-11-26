from __future__ import annotations

import csv
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.services.audit import write_audit
from app.services.importer import import_records

ALLOWED_TABULAR_EXTENSIONS = {".csv", ".xlsx", ".xls"}

RECORD_FIELD_SPECS: dict[str, dict[str, list[str]]] = {
    "invoice": {
        "required": ["vendor_name", "invoice_number", "amount", "currency", "invoice_date"],
        "optional": ["po_number", "due_date", "id", "vendor_id"],
    },
    "purchase_order": {
        "required": ["vendor_name", "po_number", "amount", "currency", "order_date"],
        "optional": ["id", "vendor_id"],
    },
    "payment": {
        "required": ["vendor_name", "reference", "amount", "currency", "payment_date"],
        "optional": ["id", "vendor_id"],
    },
    "vendor": {
        "required": ["name"],
        "optional": ["id", "normalized_name"],
    },
}

FIELD_SYNONYMS: dict[str, set[str]] = {
    "vendor_name": {"vendorname", "vendor", "supplier", "suppliername", "payee", "merchant", "company", "party"},
    "vendor_id": {"vendorid", "supplierid"},
    "name": {"name", "vendorname", "vendor", "supplier", "suppliername", "company"},
    "normalized_name": {"normalizedname", "normname"},
    "invoice_number": {"invoicenumber", "invoiceno", "invno", "invnum", "invnumber", "docnumber", "documentnumber", "billnumber"},
    "po_number": {"ponumber", "pono", "ponum", "purchaseorder", "purchaseordernumber", "poref", "poreference"},
    "reference": {"reference", "paymentreference", "paymentref", "payref", "ref", "transactionid", "txnid", "paymentnumber"},
    "amount": {"amount", "totalamount", "total", "invoicetotal", "paymentamount", "orderamount", "netamount", "grossamount", "value"},
    "currency": {"currency", "curr", "ccy", "currencycode"},
    "invoice_date": {"invoicedate", "invdate", "billdate", "docdate", "documentdate", "issuedate", "date"},
    "order_date": {"orderdate", "podate", "purchasedate", "docdate", "documentdate", "date"},
    "payment_date": {"paymentdate", "paydate", "paiddate", "valuedate", "settlementdate", "docdate", "date"},
    "due_date": {"duedate", "paymentdue", "maturitydate"},
    "id": {"id", "recordid"},
}

DATE_FORMAT_MAP = {
    "YYYY-MM-DD": "%Y-%m-%d",
    "DD/MM/YYYY": "%d/%m/%Y",
    "MM/DD/YYYY": "%m/%d/%Y",
}


def _normalize_col(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def read_tabular_frame(filename: str, content: bytes) -> pd.DataFrame:
    suffix = Path(filename).suffix.casefold()
    if suffix == ".csv":
        return pd.read_csv(BytesIO(content), dtype=str, keep_default_na=False)
    if suffix in {".xlsx", ".xls"}:
        # Read cells as strings without evaluating spreadsheet formulas.
        return pd.read_excel(BytesIO(content), dtype=str).fillna("")
    raise ValueError("Only CSV and Excel (.xlsx/.xls) files are supported.")


def preview_tabular_file(
    filename: str,
    content: bytes,
    record_type: str = "invoice",
) -> dict[str, Any]:
    if record_type not in RECORD_FIELD_SPECS:
        raise ValueError("record_type must be vendor, purchase_order, invoice, or payment")
    frame = read_tabular_frame(filename, content)
    columns = [str(col) for col in frame.columns]
    spec = RECORD_FIELD_SPECS[record_type]
    all_fields = spec["required"] + spec["optional"]

    norm_to_col: dict[str, str] = {}
    for col in columns:
        norm = _normalize_col(col)
        if norm not in norm_to_col:
            norm_to_col[norm] = col

    suggested: dict[str, str] = {}
    used_cols: set[str] = set()
    for field in all_fields:
        synonyms = FIELD_SYNONYMS.get(field, {field.replace("_", "")})
        for col in columns:
            if col in used_cols:
                continue
            if _normalize_col(col) in synonyms:
                suggested[field] = col
                used_cols.add(col)
                break

    missing_required = [field for field in spec["required"] if field not in suggested]
    preview_rows = [
        {str(k): ("" if pd.isna(v) else str(v)) for k, v in row.items()}
        for row in frame.head(10).to_dict(orient="records")
    ]
    return {
        "filename": filename,
        "record_type": record_type,
        "columns": columns,
        "total_rows": len(frame),
        "preview_rows": preview_rows,
        "required_fields": spec["required"],
        "optional_fields": spec["optional"],
        "suggested_mapping": suggested,
        "missing_required_fields": missing_required,
    }


def parse_decimal_amount(raw: str) -> Decimal:
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("Amount is missing")
    cleaned = re.sub(r"^[$€£₹]\s*", "", cleaned)
    cleaned = cleaned.replace(",", "").replace(" ", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid amount '{raw}'") from exc
    if value <= Decimal(0):
        raise ValueError(f"Amount must be greater than zero ('{raw}')")
    return value.quantize(Decimal("0.01"))


def parse_date_strict(raw: str, date_format: str = "auto") -> date:
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("Date is missing")

    if date_format != "auto":
        fmt = DATE_FORMAT_MAP.get(date_format)
        if fmt is None:
            raise ValueError(f"Unsupported date_format '{date_format}'. Use auto, YYYY-MM-DD, DD/MM/YYYY, or MM/DD/YYYY.")
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError as exc:
            raise ValueError(f"Date '{raw}' does not match format {date_format}") from exc

    iso_match = re.fullmatch(r"(\d{4})[-/](\d{2})[-/](\d{2})", cleaned)
    if iso_match:
        try:
            return date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
        except ValueError as exc:
            raise ValueError(f"Invalid ISO date '{raw}'") from exc

    slash_match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", cleaned)
    if slash_match:
        first, second, year = int(slash_match.group(1)), int(slash_match.group(2)), int(slash_match.group(3))
        if first <= 12 and second <= 12:
            raise ValueError(
                f"Ambiguous date '{raw}'; specify date_format as DD/MM/YYYY or MM/DD/YYYY."
            )
        if first > 12 and second <= 12:
            try:
                return date(year, second, first)
            except ValueError as exc:
                raise ValueError(f"Invalid DD/MM/YYYY date '{raw}'") from exc
        if second > 12 and first <= 12:
            try:
                return date(year, first, second)
            except ValueError as exc:
                raise ValueError(f"Invalid MM/DD/YYYY date '{raw}'") from exc
        raise ValueError(f"Invalid slash date '{raw}'")

    raise ValueError(f"Unrecognized date format '{raw}'; use YYYY-MM-DD, DD/MM/YYYY, or MM/DD/YYYY.")


def import_mapped_file(
    db: Session,
    *,
    filename: str,
    content: bytes,
    record_type: str,
    mapping: dict[str, str],
    date_format: str = "auto",
    actor: str = "system",
) -> dict[str, Any]:
    if record_type not in RECORD_FIELD_SPECS:
        raise ValueError("record_type must be vendor, purchase_order, invoice, or payment")
    if date_format != "auto" and date_format not in DATE_FORMAT_MAP:
        raise ValueError("date_format must be auto, YYYY-MM-DD, DD/MM/YYYY, or MM/DD/YYYY")

    spec = RECORD_FIELD_SPECS[record_type]
    missing_fields = [field for field in spec["required"] if not mapping.get(field)]
    if missing_fields:
        raise ValueError(f"Missing required field mappings: {', '.join(missing_fields)}")

    frame = read_tabular_frame(filename, content)
    columns = {str(c) for c in frame.columns}
    unknown_cols = [col for col in mapping.values() if col and col not in columns]
    if unknown_cols:
        raise ValueError(f"Mapped columns not found in file: {', '.join(unknown_cols)}")

    allowed_fields = set(spec["required"]) | set(spec["optional"])
    active_mapping = {
        field: col for field, col in mapping.items() if field in allowed_fields and col
    }

    date_fields = {"invoice_date", "order_date", "payment_date", "due_date"}
    valid_rows: list[tuple[int, dict[str, str]]] = []
    rejected_rows: list[dict[str, Any]] = []

    for row_number, raw_series in enumerate(frame.to_dict(orient="records"), start=2):
        normalized_row: dict[str, str] = {}
        row_errors: list[str] = []
        for field, source_col in active_mapping.items():
            raw_val = "" if pd.isna(raw_series.get(source_col)) else str(raw_series.get(source_col)).strip()
            if not raw_val:
                if field in spec["required"]:
                    row_errors.append(f"Missing required field '{field}'")
                continue
            if field == "amount":
                try:
                    normalized_row[field] = str(parse_decimal_amount(raw_val))
                except ValueError as exc:
                    row_errors.append(str(exc))
            elif field in date_fields:
                try:
                    normalized_row[field] = parse_date_strict(raw_val, date_format=date_format).isoformat()
                except ValueError as exc:
                    row_errors.append(str(exc))
            elif field == "currency":
                cur = raw_val.upper()
                if len(cur) != 3 or not cur.isalpha():
                    row_errors.append(f"Invalid currency '{raw_val}'")
                else:
                    normalized_row[field] = cur
            else:
                normalized_row[field] = raw_val

        if row_errors:
            rejected_rows.append({"row": row_number, "reason": "; ".join(row_errors)})
        else:
            valid_rows.append((row_number, normalized_row))

    imported_count = 0
    duplicate_count = 0
    imported_ids: list[str] = []

    if valid_rows:
        fieldnames = list(active_mapping.keys())
        buf = StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for _, row_dict in valid_rows:
            writer.writerow({key: row_dict.get(key, "") for key in fieldnames})
        import_res = import_records(
            db,
            record_type,
            f"mapped_{Path(filename).stem}.csv",
            buf.getvalue().encode("utf-8"),
            actor=actor,
        )
        imported_count = import_res["imported"]
        duplicate_count = import_res["duplicates"]
        imported_ids = import_res["ids"]
        for err in import_res["errors"]:
            err_index = int(err["row"]) - 2
            orig_row = valid_rows[err_index][0] if 0 <= err_index < len(valid_rows) else err["row"]
            msg = "; ".join(err["errors"])
            if not msg.startswith("duplicate of "):
                rejected_rows.append({"row": orig_row, "reason": msg})

    rejected_rows.sort(key=lambda item: int(item["row"]))
    write_audit(
        db,
        actor=actor,
        action="mapped_import",
        entity_type="MappedImport",
        entity_id=filename,
        inputs={
            "filename": filename,
            "record_type": record_type,
            "mapping": active_mapping,
            "date_format": date_format,
        },
        formula="Mapped columns validated to Decimal/ISO and routed through import_records",
        output={
            "imported": imported_count,
            "duplicates": duplicate_count,
            "rejected": len(rejected_rows),
        },
    )
    db.commit()
    return {
        "record_type": record_type,
        "source_file": filename,
        "imported": imported_count,
        "duplicates": duplicate_count,
        "rejected": len(rejected_rows),
        "rejected_rows": rejected_rows,
        "ids": imported_ids,
    }
