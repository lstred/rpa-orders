"""PDF extraction: embedded text first (PyMuPDF), tables via pdfplumber, with an
automatic OCR fallback for scanned / image-only pages."""
from __future__ import annotations

from pathlib import Path

from app.core.config import Config
from app.core.logging_config import get_logger
from app.ingestion.ocr import ocr_image

log = get_logger(__name__)


def extract_pdf(path: Path, doc) -> None:
    threshold = int(Config.get("ocr.auto_ocr_threshold_chars", 40))
    page_texts: list[str] = []

    # 1) Fast embedded-text pass + OCR fallback per page (PyMuPDF).
    try:
        import fitz  # PyMuPDF

        with fitz.open(path) as pdf:
            for page in pdf:
                text = page.get_text("text") or ""
                if len(text.strip()) < threshold:
                    ocr_text = _ocr_pdf_page(page)
                    if ocr_text.strip():
                        text = ocr_text
                        doc.used_ocr = True
                page_texts.append(text)
    except Exception as exc:  # noqa: BLE001
        log.warning("PyMuPDF failed on %s: %s", path.name, exc)

    # 2) Table extraction (pdfplumber).
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                for tbl in page.extract_tables() or []:
                    cleaned = [
                        [("" if c is None else str(c).strip()) for c in row]
                        for row in tbl
                    ]
                    if cleaned:
                        doc.tables.append(cleaned)
    except Exception as exc:  # noqa: BLE001
        log.warning("pdfplumber failed on %s: %s", path.name, exc)

    doc.pages = page_texts
    doc.full_text = "\n\n".join(page_texts).strip()


def _ocr_pdf_page(page) -> str:
    try:
        from io import BytesIO

        from PIL import Image

        pix = page.get_pixmap(dpi=300)
        img = Image.open(BytesIO(pix.tobytes("png")))
        return ocr_image(img)
    except Exception as exc:  # noqa: BLE001
        log.warning("PDF page OCR failed: %s", exc)
        return ""
