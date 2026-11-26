"""
Document extraction service.

Extracts structured financial fields from PDFs and images using:
- PyMuPDF  for digital/text PDFs  (no network required)
- pytesseract + Pillow for scanned images / image-only PDFs (optional; falls
  back gracefully when Tesseract is not installed)

All parsing is done with deterministic regex rules — no LLM involved.
The caller receives a dict of extracted fields plus a confidence score and a
list of warnings for fields that look uncertain or are missing.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Optional OCR imports
# ---------------------------------------------------------------------------
try:
    import pytesseract  # type: ignore
    from PIL import Image  # type: ignore
    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False

try:
    import pymupdf as fitz  # pymupdf ≥ 2.x
except ImportError:
    import fitz  # type: ignore  # pymupdf < 2.x (installed as 'fitz')


# ---------------------------------------------------------------------------
# Field patterns
# ---------------------------------------------------------------------------

_DATE_PATTERNS = [
    r"\b(\d{4}[-/]\d{2}[-/]\d{2})\b",           # 2026-01-15
    r"\b(\d{2}[-/]\d{2}[-/]\d{4})\b",           # 15/01/2026
    r"\b(\d{1,2}\s+\w{3,9}\s+\d{4})\b",         # 15 January 2026
]

_AMOUNT_PATTERN = r"[\$£€₹]?\s*(\d{1,3}(?:[,\s]\d{3})*(?:\.\d{2})?)\b"

_FIELD_PATTERNS: dict[str, list[str]] = {
    "invoice_number": [
        r"invoice\s*(?:no|number|#)[:\s#]*([A-Z0-9][-A-Z0-9/]{2,30})",
        r"\bINV[-/#]?([A-Z0-9]{3,20})\b",
    ],
    "po_number": [
        r"(?:purchase\s*order|p\.?o\.?)\s*(?:no|number|#)?[:\s#]*([A-Z0-9][-A-Z0-9/]{2,30})",
        r"\bPO[-/#]?([A-Z0-9]{3,20})\b",
    ],
    "vendor_name": [
        r"(?:vendor|supplier|from|billed\s*by|seller)[:\s]+([A-Za-z][\w\s&,.'-]{2,60}?)(?:\n|$|,)",
        r"^([A-Za-z][\w\s&,.'-]{2,60}?)\s*\n",
    ],
    "reference": [
        r"(?:transaction|payment|ref(?:erence)?)\s*(?:no|number|#|id)?[:\s#]*([A-Z0-9][-A-Z0-9/]{2,30})",
        r"\bTXN[-/#]?([A-Z0-9]{3,20})\b",
        r"\bPAY[-/#]?([A-Z0-9]{3,20})\b",
    ],
    "invoice_reference": [
        r"(?:for\s*invoice|inv(?:oice)?\s*ref(?:erence)?|against\s*inv(?:oice)?)[:\s#]*([A-Z0-9][-A-Z0-9/]{2,30})",
        r"\bINV[-/#]?([A-Z0-9]{3,20})\b",
    ],
    "description": [
        r"(?:description|particulars|details|memo|item|item\s*description)[:\s]+(.{3,120}?)(?:\n|$)",
    ],
    "payment_method": [
        r"(?:payment\s*method|paid\s*via|payment\s*type|method)[:\s]+(ACH|Wire\s*Transfer|Wire|Credit\s*Card|Debit\s*Card|Check|Cheque|Bank\s*Transfer|Online|Card)\b",
        r"\b(ACH|Wire Transfer|Wire|Credit Card|Check|Cheque|Bank Transfer)\b",
    ],
    "payment_status": [
        r"(?:payment\s*status|status)[:\s]+(Paid|Completed|Cleared|Settled|Pending|Processing|Unpaid|Partially\s*Paid)\b",
        r"\b(PAID|COMPLETED|CLEARED|SETTLED|PENDING|UNPAID)\b",
    ],
    "currency": [
        r"\b(USD|EUR|GBP|INR|CAD|AUD|JPY)\b",
    ],
    "quantity": [
        r"(?:qty|quantity|units)[:\s]+(\d+(?:\.\d+)?)\b",
    ],
    "unit_price": [
        r"(?:unit\s*price|rate|price/unit)[:\s]*[\$£€₹]?\s*(\d+(?:\.\d{2})?)\b",
    ],
}

_AMOUNT_FIELD_PATTERNS: dict[str, list[str]] = {
    "invoice_amount": [
        r"(?:invoice\s*amount|total\s*(?:amount|due|payable)|amount\s*due)[:\s]*" + _AMOUNT_PATTERN,
        r"(?:grand\s*total|net\s*total|subtotal)[:\s]*" + _AMOUNT_PATTERN,
    ],
    "tax_amount": [
        r"(?:tax|vat|gst|hst)[:\s]*" + _AMOUNT_PATTERN,
    ],
    "payment_amount": [
        r"(?:payment\s*amount|amount\s*paid|paid\s*amount)[:\s]*" + _AMOUNT_PATTERN,
        r"(?:total\s*payment)[:\s]*" + _AMOUNT_PATTERN,
    ],
    "total_amount": [
        r"(?:total\s*amount|order\s*total|po\s*total|total)[:\s]*" + _AMOUNT_PATTERN,
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _try_parse_date(value: str) -> date | None:
    import datetime
    formats = ["%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y",
               "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"]
    cleaned = re.sub(r"\s+", " ", value.replace(",", "")).strip()
    for fmt in formats:
        try:
            return datetime.datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _extract_dates(text: str) -> list[str]:
    found = []
    for pat in _DATE_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            found.append(m.group(1))
    return list(dict.fromkeys(found))  # deduplicate, preserve order


def _extract_amounts(text: str) -> list[str]:
    found = []
    for m in re.finditer(_AMOUNT_PATTERN, text):
        raw = m.group(1).replace(",", "").replace(" ", "")
        try:
            Decimal(raw)
            found.append(raw)
        except InvalidOperation:
            pass
    return list(dict.fromkeys(found))


def _first_match(patterns: list[str], text: str, flags: int = re.IGNORECASE) -> str | None:
    for pat in patterns:
        m = re.search(pat, text, flags | re.MULTILINE)
        if m:
            return _clean(m.group(1))
    return None


def _first_amount_match(patterns: list[str], text: str) -> str | None:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(",", "").replace(" ", "")
            try:
                return str(Decimal(raw))
            except InvalidOperation:
                pass
    return None


# ---------------------------------------------------------------------------
# Text extraction from document bytes
# ---------------------------------------------------------------------------

def _pdf_to_text(content: bytes) -> str:
    doc = fitz.open(stream=content, filetype="pdf")
    pages: list[str] = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()
    return "\n".join(pages)


def _image_to_text(content: bytes, suffix: str) -> str:
    if not _OCR_AVAILABLE:
        return ""
    image = Image.open(io.BytesIO(content))
    return pytesseract.image_to_string(image)


def _pdf_has_text(content: bytes) -> bool:
    doc = fitz.open(stream=content, filetype="pdf")
    for page in doc:
        if page.get_text().strip():
            doc.close()
            return True
    doc.close()
    return False


def extract_text(filename: str, content: bytes) -> tuple[str, str]:
    """Return (text, method) where method is 'pdf', 'ocr_pdf', 'ocr_image', or 'unsupported'."""
    suffix = Path(filename).suffix.casefold()
    if suffix == ".pdf":
        if _pdf_has_text(content):
            return _pdf_to_text(content), "pdf"
        # image-only PDF — try OCR page by page
        if _OCR_AVAILABLE:
            doc = fitz.open(stream=content, filetype="pdf")
            pages: list[str] = []
            for page in doc:
                pix = page.get_pixmap(dpi=200)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                pages.append(pytesseract.image_to_string(img))
            doc.close()
            return "\n".join(pages), "ocr_pdf"
        return "", "unsupported"
    if suffix in {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}:
        return _image_to_text(content, suffix), "ocr_image"
    return "", "unsupported"


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

@dataclass
class ExtractionResult:
    filename: str
    method: str
    fields: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)
    raw_text: str = ""


def _score_fields(fields: dict[str, Any]) -> float:
    """Return a 0–1 confidence based on how many key fields were found."""
    key_fields = ["vendor_name", "invoice_number", "invoice_amount", "invoice_date"]
    found = sum(1 for k in key_fields if fields.get(k))
    return round(found / len(key_fields), 2)


def extract_fields(filename: str, content: bytes) -> ExtractionResult:
    text, method = extract_text(filename, content)
    result = ExtractionResult(filename=filename, method=method, raw_text=text)

    if not text.strip():
        result.warnings.append("Could not extract text from document. "
                                "Install Tesseract and pytesseract for OCR support.")
        result.confidence = 0.0
        return result

    fields: dict[str, Any] = {}

    # Text fields
    for field_name, patterns in _FIELD_PATTERNS.items():
        value = _first_match(patterns, text)
        if value:
            fields[field_name] = value

    # Amount fields
    for field_name, patterns in _AMOUNT_FIELD_PATTERNS.items():
        value = _first_amount_match(patterns, text)
        if value:
            fields[field_name] = value

    # Dates — assign heuristically by context
    # Try labelled patterns first
    date_labels = {
        "invoice_date": [
            r"invoice\s*date[:\s]+(" + "|".join(p.lstrip(r"\b(").rstrip(r")\b") for p in _DATE_PATTERNS) + ")",
            r"date\s*of\s*invoice[:\s]+([\d/\- A-Za-z]+)",
        ],
        "due_date": [
            r"(?:due|payment\s*due)\s*date[:\s]+([\d/\- A-Za-z]+)",
        ],
        "payment_date": [
            r"(?:payment|paid)\s*(?:on|date)[:\s]+([\d/\- A-Za-z]+)",
        ],
        "order_date": [
            r"(?:order|po|purchase\s*order)\s*date[:\s]+([\d/\- A-Za-z]+)",
        ],
        "delivery_date": [
            r"(?:delivery|expected|shipping|ship)\s*date[:\s]+([\d/\- A-Za-z]+)",
        ],
    }
    for field_name, patterns in date_labels.items():
        value = _first_match(patterns, text)
        if value:
            parsed = _try_parse_date(value)
            fields[field_name] = parsed.isoformat() if parsed else value

    # Fallback: assign first two unlabelled dates to invoice_date / due_date
    if "invoice_date" not in fields or "due_date" not in fields:
        all_dates = _extract_dates(text)
        if all_dates and "invoice_date" not in fields:
            parsed = _try_parse_date(all_dates[0])
            fields["invoice_date"] = parsed.isoformat() if parsed else all_dates[0]
        if len(all_dates) > 1 and "due_date" not in fields:
            parsed = _try_parse_date(all_dates[1])
            fields["due_date"] = parsed.isoformat() if parsed else all_dates[1]

    # Fallback: assign largest amount to invoice_amount if not already found
    if "invoice_amount" not in fields:
        all_amounts = _extract_amounts(text)
        if all_amounts:
            largest = str(max(Decimal(a) for a in all_amounts))
            fields["invoice_amount"] = largest
    if "total_amount" not in fields and "invoice_amount" in fields:
        fields["total_amount"] = fields["invoice_amount"]
    elif "invoice_amount" not in fields and "total_amount" in fields:
        fields["invoice_amount"] = fields["total_amount"]
    if "payment_amount" not in fields and "total_amount" in fields:
        fields["payment_amount"] = fields["total_amount"]

    result.fields = fields
    result.confidence = _score_fields(fields)

    # Warnings for missing or low-confidence fields
    required = ["vendor_name", "invoice_number", "invoice_amount", "invoice_date"]
    for f in required:
        if not fields.get(f):
            result.warnings.append(f"Could not extract '{f}' — please fill in manually.")
    if result.confidence < 0.5:
        result.warnings.append("Low extraction confidence. Please verify all fields before saving.")

    return result


def classify_document_type(text: str, filename: str) -> str:
    """Classify document category as 'invoice', 'purchase_order', or 'payment'."""
    lower_text = text.casefold()
    lower_fname = filename.casefold()

    if (
        "purchase order" in lower_text
        or "purchase order" in lower_fname
        or "po-" in lower_fname
        or "order date" in lower_text
        or "delivery date" in lower_text
        or "po number" in lower_text
        or "p.o." in lower_text
    ):
        return "purchase_order"

    if (
        "remittance advice" in lower_text
        or "payment receipt" in lower_text
        or "payment confirmation" in lower_text
        or "payment voucher" in lower_text
        or "payment" in lower_fname
        or "txn-" in lower_fname
        or "pay-" in lower_fname
        or "payment method" in lower_text
        or "amount paid" in lower_text
    ):
        return "payment"

    return "invoice"


def process_and_save_document(
    db: Any,
    filename: str,
    content: bytes,
    document_type: str | None = None,
    user_id: str | None = None,
    actor: str = "system",
) -> tuple[Any, dict[str, Any]]:
    """Extract fields from document bytes, save UploadedDocument, and create corresponding entity."""
    from app.models import Invoice, Payment, PurchaseOrder, UploadedDocument, Vendor
    from app.services.audit import write_audit
    from app.services.importer import compute_dedupe_hash, normalize_vendor_name
    from sqlalchemy import select

    extraction = extract_fields(filename, content)
    doc_type = (document_type or classify_document_type(extraction.raw_text, filename)).casefold()
    if doc_type not in {"invoice", "purchase_order", "payment"}:
        doc_type = "invoice"

    fields = dict(extraction.fields)
    vendor_name = fields.get("vendor_name") or "Extracted Vendor"
    normalized_v = normalize_vendor_name(vendor_name) or "extractedvendor"

    # Resolve or create vendor
    vendor = db.scalar(select(Vendor).where(Vendor.normalized_name == normalized_v))
    if vendor is None:
        vendor = Vendor(name=vendor_name, normalized_name=normalized_v)
        db.add(vendor)
        db.flush()

    # Create UploadedDocument
    doc = UploadedDocument(
        user_id=user_id,
        filename=filename,
        document_type=doc_type,
        file_size=len(content),
        extraction_method=extraction.method,
        confidence=Decimal(str(extraction.confidence)),
        extracted_data=fields,
        raw_text=extraction.raw_text[:2000] if extraction.raw_text else None,
        status="processed",
    )
    db.add(doc)
    db.flush()

    raw_row_data = {**fields, "source_file": filename, "uploaded_document_id": doc.id}

    if doc_type == "invoice":
        inv_num = fields.get("invoice_number") or f"INV-{doc.id[:8].upper()}"
        inv_amt = Decimal(fields.get("invoice_amount") or fields.get("total_amount") or "100.00")
        currency = fields.get("currency") or "USD"
        inv_date = _try_parse_date(fields.get("invoice_date") or "") or date.today()
        due_d = _try_parse_date(fields.get("due_date") or "")

        dedupe_hash = compute_dedupe_hash(vendor.name, inv_num, inv_amt, inv_date)
        existing = db.scalar(select(Invoice).where(Invoice.dedupe_hash == dedupe_hash))
        if existing is None:
            entity = Invoice(
                user_id=user_id,
                vendor_id=vendor.id,
                invoice_number=inv_num,
                po_number=fields.get("po_number"),
                amount=inv_amt,
                currency=currency,
                invoice_date=inv_date,
                due_date=due_d,
                source_file=filename,
                raw_row=raw_row_data,
                dedupe_hash=dedupe_hash,
            )
            db.add(entity)
            db.flush()
        else:
            entity = existing

    elif doc_type == "purchase_order":
        po_num = fields.get("po_number") or f"PO-{doc.id[:8].upper()}"
        po_amt = Decimal(fields.get("total_amount") or fields.get("invoice_amount") or "100.00")
        currency = fields.get("currency") or "USD"
        ord_date = _try_parse_date(fields.get("order_date") or fields.get("invoice_date") or "") or date.today()

        existing_po = db.scalar(
            select(PurchaseOrder).where(
                PurchaseOrder.vendor_id == vendor.id, PurchaseOrder.po_number == po_num
            )
        )
        if existing_po is None:
            entity = PurchaseOrder(
                user_id=user_id,
                vendor_id=vendor.id,
                po_number=po_num,
                amount=po_amt,
                currency=currency,
                order_date=ord_date,
                source_file=filename,
                raw_row=raw_row_data,
            )
            db.add(entity)
            db.flush()
        else:
            entity = existing_po

    else:  # payment
        ref = fields.get("reference") or f"PAY-{doc.id[:8].upper()}"
        pay_amt = Decimal(fields.get("payment_amount") or fields.get("total_amount") or "100.00")
        currency = fields.get("currency") or "USD"
        pay_date = _try_parse_date(fields.get("payment_date") or fields.get("invoice_date") or "") or date.today()

        existing_pay = db.scalar(
            select(Payment).where(
                Payment.vendor_id == vendor.id, Payment.reference == ref
            )
        )
        if existing_pay is None:
            entity = Payment(
                user_id=user_id,
                vendor_id=vendor.id,
                reference=ref,
                amount=pay_amt,
                currency=currency,
                payment_date=pay_date,
                source_file=filename,
                raw_row=raw_row_data,
            )
            db.add(entity)
            db.flush()
        else:
            entity = existing_pay

    write_audit(
        db,
        actor=actor,
        action="document_extracted_and_persisted",
        entity_type="UploadedDocument",
        entity_id=doc.id,
        inputs={"filename": filename, "document_type": doc_type, "confidence": float(extraction.confidence)},
        formula="Regex document extraction and entity persistence",
        output={"document_id": doc.id, "fields": fields},
    )
    db.commit()

    return doc, {
        "document_id": doc.id,
        "filename": doc.filename,
        "document_type": doc.document_type,
        "confidence": float(doc.confidence),
        "fields": doc.extracted_data,
        "warnings": extraction.warnings,
        "status": doc.status,
    }
