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
        r"(?:vendor|supplier|from|billed\s*by)[:\s]+([A-Za-z][\w\s&,.'-]{2,60}?)(?:\n|$|,)",
        r"^([A-Za-z][\w\s&,.'-]{2,60}?)\s*\n",
    ],
    "reference": [
        r"(?:transaction|payment|ref(?:erence)?)\s*(?:no|number|#|id)?[:\s#]*([A-Z0-9][-A-Z0-9/]{2,30})",
        r"\bTXN[-/#]?([A-Z0-9]{3,20})\b",
    ],
    "description": [
        r"(?:description|particulars|details|memo)[:\s]+(.{5,120}?)(?:\n|$)",
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
