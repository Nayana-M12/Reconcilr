from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.extraction.text_reader import PageText

REQUIRED_FIELDS = ("document_type", "document_number", "vendor", "date", "currency", "total_amount")

CURRENCY_SYMBOLS = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
}

DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
)


@dataclass(frozen=True)
class FieldProvenance:
    value: str
    page: int
    snippet: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "page": self.page,
            "snippet": self.snippet,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ExtractedDocument:
    document_type: str | None
    document_number: str | None
    vendor: str | None
    document_date: date | None
    currency: str | None
    total_amount: Decimal | None
    po_reference: str | None
    provenance: dict[str, FieldProvenance]
    fields_missing: list[str]

    @property
    def is_complete(self) -> bool:
        return not self.fields_missing

    def fields_found_dict(self) -> dict[str, str]:
        found: dict[str, str] = {}
        if self.document_type is not None:
            found["document_type"] = self.document_type
        if self.document_number is not None:
            found["document_number"] = self.document_number
        if self.vendor is not None:
            found["vendor"] = self.vendor
        if self.document_date is not None:
            found["date"] = self.document_date.isoformat()
        if self.currency is not None:
            found["currency"] = self.currency
        if self.total_amount is not None:
            found["total_amount"] = str(self.total_amount)
        if self.po_reference is not None:
            found["po_reference"] = self.po_reference
        return found

    def provenance_dict(self) -> dict[str, dict[str, Any]]:
        return {key: item.to_dict() for key, item in self.provenance.items()}


def _iter_lines(pages: list[PageText]) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for page in pages:
        for raw_line in page.text.splitlines():
            cleaned = " ".join(raw_line.split()).strip()
            if cleaned:
                lines.append((page.page, cleaned))
    return lines


def _classify(lines: list[tuple[int, str]]) -> tuple[str | None, FieldProvenance | None]:
    rules: tuple[tuple[str, re.Pattern[str], float], ...] = (
        ("purchase_order", re.compile(r"\b(purchase\s+order|po\s+number|po\s*#)\b", re.IGNORECASE), 0.96),
        ("payment", re.compile(r"\b(payment\s+advice|remittance\s+advice|payment\s+reference|payment\s+receipt)\b", re.IGNORECASE), 0.96),
        ("invoice", re.compile(r"\b(tax\s+invoice|invoice\s+number|invoice\s*#|invoice)\b", re.IGNORECASE), 0.95),
    )
    for doc_type, pattern, confidence in rules:
        for page, line in lines:
            if pattern.search(line):
                return doc_type, FieldProvenance(value=doc_type, page=page, snippet=line, confidence=confidence)
    return None, None


def _extract_document_number(
    doc_type: str | None,
    lines: list[tuple[int, str]],
) -> tuple[str | None, FieldProvenance | None]:
    patterns_by_type: dict[str, list[tuple[re.Pattern[str], float]]] = {
        "invoice": [
            (re.compile(r"\binvoice\s*(?:number|no\.?|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})\b", re.IGNORECASE), 0.96),
        ],
        "purchase_order": [
            (re.compile(r"\b(?:purchase\s+order|po)\s*(?:number|no\.?|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})\b", re.IGNORECASE), 0.96),
        ],
        "payment": [
            (re.compile(r"\b(?:payment\s+reference|reference|payment\s*(?:number|no\.?|#))\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})\b", re.IGNORECASE), 0.96),
        ],
    }
    patterns = patterns_by_type.get(doc_type or "", [])
    patterns.append((re.compile(r"\b(?:document\s*(?:number|no\.?|#)|ref(?:erence)?)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})\b", re.IGNORECASE), 0.85))
    for pattern, confidence in patterns:
        for page, line in lines:
            match = pattern.search(line)
            if match:
                val = match.group(1).strip()
                return val, FieldProvenance(value=val, page=page, snippet=line, confidence=confidence)
    return None, None


def _extract_vendor(lines: list[tuple[int, str]]) -> tuple[str | None, FieldProvenance | None]:
    patterns = (
        (re.compile(r"^(?:vendor|supplier|from|payee|beneficiary|billed\s+by)\s*[:\-]\s*(.+)$", re.IGNORECASE), 0.95),
        (re.compile(r"\b(?:vendor|supplier)\s+name\s*[:\-]\s*(.+)$", re.IGNORECASE), 0.95),
    )
    for pattern, confidence in patterns:
        for page, line in lines:
            match = pattern.search(line)
            if match:
                val = match.group(1).strip()
                if val:
                    return val, FieldProvenance(value=val, page=page, snippet=line, confidence=confidence)
    return None, None


def _parse_iso_date(raw: str) -> date | None:
    cleaned = raw.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _extract_date(lines: list[tuple[int, str]]) -> tuple[date | None, FieldProvenance | None]:
    date_token = r"(\d{4}[-/]\d{2}[-/]\d{2}|[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})"
    patterns = (
        (re.compile(rf"\b(?:invoice|order|payment|document|issue)\s+date\s*[:\-]?\s*{date_token}\b", re.IGNORECASE), 0.96),
        (re.compile(rf"^date\s*[:\-]?\s*{date_token}\b", re.IGNORECASE), 0.92),
    )
    for pattern, confidence in patterns:
        for page, line in lines:
            match = pattern.search(line)
            if match:
                parsed = _parse_iso_date(match.group(1))
                if parsed is not None:
                    return parsed, FieldProvenance(
                        value=parsed.isoformat(),
                        page=page,
                        snippet=line,
                        confidence=confidence,
                    )
    return None, None


def _parse_decimal_amount(raw: str) -> Decimal | None:
    cleaned = raw.replace(",", "").strip()
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if value <= Decimal(0):
        return None
    return value.quantize(Decimal("0.01"))


def _extract_amount_and_currency(
    lines: list[tuple[int, str]],
) -> tuple[Decimal | None, FieldProvenance | None, str | None, FieldProvenance | None]:
    amount_val: Decimal | None = None
    amount_prov: FieldProvenance | None = None
    currency_val: str | None = None
    currency_prov: FieldProvenance | None = None

    currency_line_re = re.compile(r"^currency\s*[:\-]\s*([A-Z]{3})\b", re.IGNORECASE)
    for page, line in lines:
        match = currency_line_re.search(line)
        if match:
            currency_val = match.group(1).upper()
            currency_prov = FieldProvenance(value=currency_val, page=page, snippet=line, confidence=0.98)
            break

    amount_patterns = (
        (
            re.compile(
                r"\b(?:total\s+amount|amount\s+due|amount\s+paid|grand\s+total|order\s+total|total)\s*[:\-]?\s*"
                r"(?:(?P<code1>[A-Z]{3})\s*|(?P<sym>[$€£₹])\s*)?"
                r"(?P<amt>\d{1,3}(?:,\d{3})*(?:\.\d{2})|\d+(?:\.\d{2}))"
                r"(?:\s*(?P<code2>[A-Z]{3}))?\b",
                re.IGNORECASE,
            ),
            0.95,
        ),
        (
            re.compile(
                r"^amount\s*[:\-]?\s*"
                r"(?:(?P<code1>[A-Z]{3})\s*|(?P<sym>[$€£₹])\s*)?"
                r"(?P<amt>\d{1,3}(?:,\d{3})*(?:\.\d{2})|\d+(?:\.\d{2}))"
                r"(?:\s*(?P<code2>[A-Z]{3}))?\b",
                re.IGNORECASE,
            ),
            0.90,
        ),
    )

    for pattern, confidence in amount_patterns:
        for page, line in lines:
            match = pattern.search(line)
            if match:
                parsed = _parse_decimal_amount(match.group("amt"))
                if parsed is None:
                    continue
                amount_val = parsed
                amount_prov = FieldProvenance(value=str(parsed), page=page, snippet=line, confidence=confidence)
                if currency_val is None:
                    inferred = (match.group("code1") or match.group("code2") or "").upper()
                    if not inferred and match.group("sym"):
                        inferred = CURRENCY_SYMBOLS.get(match.group("sym"), "")
                    if inferred:
                        currency_val = inferred
                        currency_prov = FieldProvenance(value=inferred, page=page, snippet=line, confidence=0.92)
                break
        if amount_val is not None:
            break

    return amount_val, amount_prov, currency_val, currency_prov


def _extract_po_reference(
    doc_type: str | None,
    lines: list[tuple[int, str]],
) -> tuple[str | None, FieldProvenance | None]:
    if doc_type == "purchase_order":
        return None, None
    pattern = re.compile(
        r"\b(?:po\s+reference|po\s+ref\.?|purchase\s+order\s*(?:ref|number|no\.?|#)|po\s*(?:number|no\.?|#))\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})\b",
        re.IGNORECASE,
    )
    for page, line in lines:
        match = pattern.search(line)
        if match:
            val = match.group(1).strip()
            return val, FieldProvenance(value=val, page=page, snippet=line, confidence=0.94)
    return None, None


def parse_document(pages: list[PageText]) -> ExtractedDocument:
    lines = _iter_lines(pages)
    provenance: dict[str, FieldProvenance] = {}

    doc_type, doc_type_prov = _classify(lines)
    if doc_type_prov is not None:
        provenance["document_type"] = doc_type_prov

    doc_number, doc_number_prov = _extract_document_number(doc_type, lines)
    if doc_number_prov is not None:
        provenance["document_number"] = doc_number_prov

    vendor, vendor_prov = _extract_vendor(lines)
    if vendor_prov is not None:
        provenance["vendor"] = vendor_prov

    doc_date, doc_date_prov = _extract_date(lines)
    if doc_date_prov is not None:
        provenance["date"] = doc_date_prov

    amount, amount_prov, currency, currency_prov = _extract_amount_and_currency(lines)
    if amount_prov is not None:
        provenance["total_amount"] = amount_prov
    if currency_prov is not None:
        provenance["currency"] = currency_prov

    po_ref, po_ref_prov = _extract_po_reference(doc_type, lines)
    if po_ref_prov is not None:
        provenance["po_reference"] = po_ref_prov

    values: dict[str, Any] = {
        "document_type": doc_type,
        "document_number": doc_number,
        "vendor": vendor,
        "date": doc_date,
        "currency": currency,
        "total_amount": amount,
    }
    fields_missing = [field for field in REQUIRED_FIELDS if values[field] is None]

    return ExtractedDocument(
        document_type=doc_type,
        document_number=doc_number,
        vendor=vendor,
        document_date=doc_date,
        currency=currency,
        total_amount=amount,
        po_reference=po_ref,
        provenance=provenance,
        fields_missing=fields_missing,
    )
