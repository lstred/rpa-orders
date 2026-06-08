"""Image extraction: pure OCR via Tesseract."""
from __future__ import annotations

from pathlib import Path

from app.core.logging_config import get_logger
from app.ingestion.ocr import ocr_image

log = get_logger(__name__)


def extract_image(path: Path, doc) -> None:
    try:
        from PIL import Image
    except Exception as exc:  # noqa: BLE001
        log.warning("Pillow not available: %s", exc)
        return
    try:
        with Image.open(path) as img:
            text = ocr_image(img)
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to OCR image %s: %s", path.name, exc)
        return
    doc.used_ocr = bool(text.strip())
    doc.pages = [text]
    doc.full_text = text.strip()
