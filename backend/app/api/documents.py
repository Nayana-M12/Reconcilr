"""Documents and Dashboard Category endpoints."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser, get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import (
    Invoice,
    Match,
    Payment,
    PurchaseOrder,
    UploadedDocument,
    Vendor,
)
from app.services.extractor import classify_document_type, process_and_save_document
from app.services.importer import import_records

router = APIRouter(prefix="/documents", tags=["documents"])

_ALLOWED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp",
    ".csv", ".xlsx", ".xls",
}


def _calculate_invoice_payment_status(db: Session, invoice: Invoice) -> str:
    """Calculate invoice payment status based on matched payments or payment records."""
    matches = list(db.scalars(select(Match).where(Match.invoice_id == invoice.id)))
    payment_matches = [m for m in matches if m.payment_id]
    if payment_matches:
        pay = db.get(Payment, payment_matches[0].payment_id)
        if pay:
            if pay.amount == invoice.amount:
                return "Paid"
            elif pay.amount < invoice.amount:
                return "Partially Paid"
            else:
                return "Overpaid"

    # Check unlinked payment reference
    target_ref = invoice.invoice_number.casefold()
    candidate = db.scalar(
        select(Payment).where(
            Payment.vendor_id == invoice.vendor_id,
            Payment.reference.ilike(f"%{target_ref}%"),
        )
    )
    if candidate:
        if candidate.amount >= invoice.amount:
            return "Paid"
        else:
            return "Partially Paid"

    if invoice.due_date and invoice.due_date < date.today():
        return "Overdue"

    return "Pending"


@router.get("/categories/{category}")
def get_category_documents(
    category: str,
    file_filter: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    cat = category.casefold().strip()
    if cat in {"po", "purchase-order", "purchase_orders"}:
        cat = "purchase_order"
    elif cat in {"payments"}:
        cat = "payment"
    elif cat in {"invoices"}:
        cat = "invoice"

    if cat not in {"invoice", "purchase_order", "payment"}:
        raise HTTPException(
            status_code=400,
            detail="Category must be 'invoice', 'purchase_order', or 'payment'",
        )

    # User isolation: admin/auditor sees all, analyst/approver sees their own or unassigned
    def apply_user_filter(query, model):
        if user.role not in {"admin", "auditor"}:
            return query.where((model.user_id == user.id) | (model.user_id.is_(None)))
        return query

    files_set: set[str] = set()
    records: list[dict[str, Any]] = []

    if cat == "invoice":
        q = select(Invoice).order_by(Invoice.invoice_date.desc())
        q = apply_user_filter(q, Invoice)
        invoices = list(db.scalars(q))

        for inv in invoices:
            src = inv.source_file or "Document Upload"
            files_set.add(src)
            if file_filter and file_filter != "all" and src != file_filter:
                continue

            pay_status = _calculate_invoice_payment_status(db, inv)
            raw = inv.raw_row or {}
            tax = raw.get("tax_amount") or raw.get("tax") or raw.get("vat") or raw.get("gst")

            records.append({
                "id": inv.id,
                "document_id": raw.get("uploaded_document_id"),
                "invoice_number": inv.invoice_number,
                "vendor_name": inv.vendor.name if inv.vendor else "Unknown Vendor",
                "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
                "due_date": inv.due_date.isoformat() if inv.due_date else None,
                "total_amount": f"{inv.amount:.2f}",
                "currency": inv.currency,
                "tax_amount": f"{Decimal(str(tax)):.2f}" if tax else None,
                "payment_status": pay_status,
                "po_number": inv.po_number,
                "source_file": src,
                "user_id": inv.user_id,
            })

    elif cat == "purchase_order":
        q = select(PurchaseOrder).order_by(PurchaseOrder.order_date.desc())
        q = apply_user_filter(q, PurchaseOrder)
        pos = list(db.scalars(q))

        for po in pos:
            src = po.source_file or "PO Source Feed"
            files_set.add(src)
            if file_filter and file_filter != "all" and src != file_filter:
                continue

            raw = po.raw_row or {}
            records.append({
                "id": po.id,
                "document_id": raw.get("uploaded_document_id"),
                "po_number": po.po_number,
                "vendor_name": po.vendor.name if po.vendor else "Unknown Vendor",
                "order_date": po.order_date.isoformat() if po.order_date else None,
                "delivery_date": raw.get("delivery_date") or raw.get("expected_delivery") or None,
                "item_description": raw.get("description") or raw.get("item_description") or raw.get("items") or "Standard Materials & Services",
                "quantity": raw.get("quantity") or raw.get("qty") or "1",
                "unit_price": f"{Decimal(str(raw.get('unit_price') or po.amount)):.2f}" if raw.get("unit_price") else f"{po.amount:.2f}",
                "total_amount": f"{po.amount:.2f}",
                "currency": po.currency,
                "source_file": src,
                "user_id": po.user_id,
            })

    else:  # payment
        q = select(Payment).order_by(Payment.payment_date.desc())
        q = apply_user_filter(q, Payment)
        payments = list(db.scalars(q))

        for pay in payments:
            src = pay.source_file or "Payment Settlement Feed"
            files_set.add(src)
            if file_filter and file_filter != "all" and src != file_filter:
                continue

            raw = pay.raw_row or {}
            inv_ref = raw.get("invoice_reference") or raw.get("invoice_number")
            if not inv_ref and "pay-" in pay.reference.lower():
                inv_ref = pay.reference.replace("pay-", "INV-", 1).replace("PAY-", "INV-", 1)

            method = raw.get("payment_method") or raw.get("method") or "Bank Wire / ACH"
            status = raw.get("payment_status") or raw.get("status") or ("Completed" if pay.amount > 0 else "Pending")

            records.append({
                "id": pay.id,
                "document_id": raw.get("uploaded_document_id"),
                "payment_reference": pay.reference,
                "invoice_reference": inv_ref,
                "vendor_name": pay.vendor.name if pay.vendor else "Unknown Vendor",
                "payment_date": pay.payment_date.isoformat() if pay.payment_date else None,
                "payment_amount": f"{pay.amount:.2f}",
                "currency": pay.currency,
                "payment_method": method,
                "payment_status": status,
                "source_file": src,
                "user_id": pay.user_id,
            })

    # Also list uploaded_documents for this category
    doc_q = select(UploadedDocument).where(UploadedDocument.document_type == cat)
    if user.role not in {"admin", "auditor"}:
        doc_q = doc_q.where((UploadedDocument.user_id == user.id) | (UploadedDocument.user_id.is_(None)))
    for doc in db.scalars(doc_q):
        files_set.add(doc.filename)

    # Compute category statistics
    stats: dict[str, Any] = {}
    if cat == "invoice":
        paid_cnt = sum(1 for r in records if r.get("payment_status") == "Paid")
        unpaid_cnt = len(records) - paid_cnt
        total_amt = sum(Decimal(str(r["total_amount"])) for r in records if r.get("total_amount"))
        stats = {
            "paid_count": paid_cnt,
            "unpaid_count": unpaid_cnt,
            "total_amount": float(total_amt),
        }
    elif cat == "purchase_order":
        vendors_cnt = len({r["vendor_name"] for r in records})
        total_amt = sum(Decimal(str(r["total_amount"])) for r in records if r.get("total_amount"))
        stats = {
            "unique_vendors": vendors_cnt,
            "total_amount": float(total_amt),
        }
    elif cat == "payment":
        completed_cnt = sum(1 for r in records if (r.get("payment_status") or "").lower() == "completed")
        pending_cnt = len(records) - completed_cnt
        total_amt = sum(Decimal(str(r["payment_amount"])) for r in records if r.get("payment_amount"))
        stats = {
            "completed_count": completed_cnt,
            "pending_count": pending_cnt,
            "total_amount": float(total_amt),
        }

    sorted_files = sorted(files_set)
    return {
        "category": cat,
        "files": sorted_files,
        "source_files": sorted_files,
        "total_records": len(records),
        "total_count": len(records),
        "records": records,
        "stats": stats,
    }


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    category: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    filename = file.filename or "upload.pdf"
    suffix = Path(filename).suffix.casefold()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{suffix}'. Allowed: PDF, PNG, JPG, JPEG, TIFF, BMP, WEBP, CSV, XLSX, XLS",
        )

    settings = get_settings()
    content = await file.read(settings.upload_max_bytes + 1)
    if len(content) > settings.upload_max_bytes:
        limit_mb = settings.upload_max_bytes / (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"File exceeds {limit_mb:g} MB limit")

    cat = (category or "").casefold().strip()
    if cat in {"po", "purchase-order", "purchase_orders"}:
        cat = "purchase_order"
    elif cat in {"payments"}:
        cat = "payment"
    elif cat in {"invoices"}:
        cat = "invoice"
    elif not cat:
        cat = None

    if suffix in {".csv", ".xlsx", ".xls"}:
        record_type = cat or "invoice"
        res = import_records(
            db,
            record_type=record_type,
            filename=filename,
            content=content,
            actor=user.username,
            user_id=user.id,
        )
        return {
            "status": "success",
            "filename": filename,
            "document_type": record_type,
            "imported_count": res.get("imported", 0),
            "errors": res.get("errors", []),
            "message": f"Successfully imported {res.get('imported', 0)} {record_type} records from {filename}",
        }

    # PDF / Image extraction pipeline
    doc, result = process_and_save_document(
        db=db,
        filename=filename,
        content=content,
        document_type=cat,
        user_id=user.id,
        actor=user.username,
    )
    return {
        "status": "success",
        "document_id": doc.id,
        "filename": doc.filename,
        "document_type": doc.document_type,
        "confidence": float(doc.confidence),
        "fields": doc.extracted_data,
        "warnings": result.get("warnings", []),
        "message": f"Extracted and saved {doc.document_type} from {filename}",
    }


@router.get("")
def list_documents(
    document_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    q = select(UploadedDocument).order_by(UploadedDocument.created_at.desc())
    if user.role not in {"admin", "auditor"}:
        q = q.where((UploadedDocument.user_id == user.id) | (UploadedDocument.user_id.is_(None)))
    if document_type:
        q = q.where(UploadedDocument.document_type == document_type.casefold())

    docs = list(db.scalars(q))
    return [
        {
            "id": doc.id,
            "filename": doc.filename,
            "document_type": doc.document_type,
            "file_size": doc.file_size,
            "confidence": float(doc.confidence),
            "extraction_method": doc.extraction_method,
            "extracted_data": doc.extracted_data,
            "status": doc.status,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "user_id": doc.user_id,
        }
        for doc in docs
    ]
