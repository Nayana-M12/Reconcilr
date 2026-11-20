from __future__ import annotations

import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pdfplumber

SUPPORTED_TEXT_EXTENSIONS = {".txt", ".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}


@dataclass(frozen=True)
class PageText:
    page: int
    text: str


class DocumentReadError(ValueError):
    def __init__(self, message: str, code: str = "unsupported") -> None:
        self.code = code
        super().__init__(message)


def _ocr_enabled() -> bool:
    return os.getenv("EXTRACTION_OCR", "0").strip() == "1"


def _try_ocr_image_bytes(content: bytes) -> str:
    if not _ocr_enabled():
        raise DocumentReadError(
            "OCR not enabled. Set EXTRACTION_OCR=1 with pytesseract installed to process images or scanned PDFs.",
            code="ocr_disabled",
        )
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise DocumentReadError(
            "OCR not enabled. Optional dependency pytesseract is not installed.",
            code="ocr_disabled",
        ) from exc
    with Image.open(BytesIO(content)) as image:
        return pytesseract.image_to_string(image)


def _try_ocr_pdf(pdf: pdfplumber.PDF) -> list[PageText]:
    if not _ocr_enabled():
        raise DocumentReadError(
            "OCR not enabled. PDF contains no extractable text; set EXTRACTION_OCR=1 with pytesseract installed for scanned PDFs.",
            code="ocr_disabled",
        )
    try:
        import pytesseract
    except ImportError as exc:
        raise DocumentReadError(
            "OCR not enabled. Optional dependency pytesseract is not installed.",
            code="ocr_disabled",
        ) from exc
    pages: list[PageText] = []
    for index, page in enumerate(pdf.pages, start=1):
        rendered = page.to_image(resolution=200).original
        text = pytesseract.image_to_string(rendered)
        if text.strip():
            pages.append(PageText(page=index, text=text))
    if not pages:
        raise DocumentReadError("No readable text found in scanned PDF.", code="empty_document")
    return pages


def read_document_text(filename: str, content: bytes) -> list[PageText]:
    suffix = Path(filename).suffix.casefold()
    if suffix == ".txt":
        text = content.decode("utf-8", errors="replace")
        if not text.strip():
            raise DocumentReadError("Text document is empty.", code="empty_document")
        return [PageText(page=1, text=text)]

    if suffix == ".pdf":
        try:
            with pdfplumber.open(BytesIO(content)) as pdf:
                pages: list[PageText] = []
                for index, page in enumerate(pdf.pages, start=1):
                    extracted = page.extract_text() or ""
                    if extracted.strip():
                        pages.append(PageText(page=index, text=extracted))
                if not pages:
                    return _try_ocr_pdf(pdf)
                return pages
        except DocumentReadError:
            raise
        except Exception as exc:
            raise DocumentReadError(f"Unable to read PDF document: {exc}", code="invalid_pdf") from exc

    if suffix in IMAGE_EXTENSIONS:
        text = _try_ocr_image_bytes(content)
        if not text.strip():
            raise DocumentReadError("No readable text extracted from image.", code="empty_document")
        return [PageText(page=1, text=text)]

    raise DocumentReadError(
        f"Unsupported file type '{suffix or 'unknown'}'. Supported document types: .pdf, .txt (use /imports or /import/mapped for .csv, .xlsx, .xls).",
        code="unsupported",
    )
