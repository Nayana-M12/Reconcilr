from __future__ import annotations

import csv
from io import StringIO
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth.security import actor_from_user, require_roles
from app.config import get_settings
from app.database import get_db
from app.extraction import (
    DocumentReadError,
    ExtractedDocument,
    parse_document,
    read_document_text,
)
from app.models import User
from app.services.audit import write_audit
from app.services.importer import import_records

router = APIRouter(prefix="/import", tags=["import"])


def _to_csv_bytes(extracted: ExtractedDocument) -> bytes:
    assert extracted.document_type and extracted.document_number and extracted.vendor
    assert extracted.document_date and extracted.currency and extracted.total_amount is not None
    row: dict[str, str] = {
        "vendor_name": extracted.vendor,
        "amount": str(extracted.total_amount),
        "currency": extracted.currency,
    }
    if extracted.document_type == "invoice":
        row["invoice_number"] = extracted.document_number
        row["invoice_date"] = extracted.document_date.isoformat()
        if extracted.po_reference:
            row["po_number"] = extracted.po_reference
    elif extracted.document_type == "purchase_order":
        row["po_number"] = extracted.document_number
        row["order_date"] = extracted.document_date.isoformat()
    else:
        row["reference"] = extracted.document_number
        row["payment_date"] = extracted.document_date.isoformat()

    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(row.keys()))
    writer.writeheader()
    writer.writerow(row)
    return buf.getvalue().encode("utf-8")


@router.post("/document")
async def import_documents(
    files: list[UploadFile] = File(...),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(require_roles("analyst", "admin")),  # noqa: B008
) -> dict[str, list[dict[str, Any]]]:
    max_bytes = get_settings().max_upload_size_bytes
    actor = actor_from_user(current_user)
    imported: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    needs_review: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []

    for upload in files:
        filename = upload.filename or "document"
        content = await upload.read()
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File '{filename}' exceeds maximum allowed size of {max_bytes} bytes.",
            )
        try:
            pages = read_document_text(filename, content)
        except DocumentReadError as exc:
            entry = {"filename": filename, "code": exc.code, "message": str(exc)}
            unsupported.append(entry)
            write_audit(
                db,
                actor=actor,
                action="document_import",
                entity_type="DocumentImport",
                entity_id=filename,
                inputs={"filename": filename},
                formula="Attempt deterministic text extraction",
                output={"outcome": "unsupported", "code": exc.code, "message": str(exc)},
            )
            db.commit()
            continue

        extracted = parse_document(pages)
        fields_found = extracted.fields_found_dict()
        provenance = extracted.provenance_dict()

        if not extracted.is_complete:
            review_item = {
                "filename": filename,
                "document_type": extracted.document_type,
                "fields_found": fields_found,
                "fields_missing": extracted.fields_missing,
                "provenance": provenance,
            }
            needs_review.append(review_item)
            write_audit(
                db,
                actor=actor,
                action="document_import",
                entity_type="DocumentImport",
                entity_id=filename,
                inputs={"filename": filename, "document_type": extracted.document_type},
                formula="Deterministic extraction; missing required fields sent to needs_review without guessing",
                output={
                    "outcome": "needs_review",
                    "fields_found": fields_found,
                    "fields_missing": extracted.fields_missing,
                    "provenance": provenance,
                },
            )
            db.commit()
            continue

        assert extracted.document_type is not None
        csv_bytes = _to_csv_bytes(extracted)
        import_result = import_records(
            db,
            extracted.document_type,
            f"{filename}.csv",
            csv_bytes,
            actor=actor,
        )
        if import_result["duplicates"] > 0:
            dup_item = {
                "filename": filename,
                "document_type": extracted.document_type,
                "fields_found": fields_found,
                "provenance": provenance,
                "detail": import_result["errors"][0]["errors"][0] if import_result["errors"] else "duplicate",
            }
            duplicates.append(dup_item)
            outcome = "duplicate"
            record_id = None
        elif import_result["imported"] > 0:
            record_id = import_result["ids"][0]
            imported.append(
                {
                    "filename": filename,
                    "record_type": extracted.document_type,
                    "record_id": record_id,
                    "fields_found": fields_found,
                    "provenance": provenance,
                }
            )
            outcome = "imported"
        else:
            review_item = {
                "filename": filename,
                "document_type": extracted.document_type,
                "fields_found": fields_found,
                "fields_missing": extracted.fields_missing,
                "provenance": provenance,
                "errors": import_result["errors"],
            }
            needs_review.append(review_item)
            outcome = "needs_review"
            record_id = None

        write_audit(
            db,
            actor=actor,
            action="document_import",
            entity_type="DocumentImport",
            entity_id=record_id or filename,
            inputs={"filename": filename, "document_type": extracted.document_type},
            formula="Deterministic extraction passed into import_records with full provenance",
            output={
                "outcome": outcome,
                "record_id": record_id,
                "provenance": provenance,
            },
        )
        db.commit()

    return {
        "imported": imported,
        "duplicates": duplicates,
        "needs_review": needs_review,
        "unsupported": unsupported,
    }
