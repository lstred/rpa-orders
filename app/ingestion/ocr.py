"""OCR bridge over Tesseract. Optional — only used when a page has no usable
embedded text (i.e. scanned documents / image-only PDFs)."""
from __future__ import annotations

from app.core.config import Config
from app.core.logging_config import get_logger

log = get_logger(__name__)


def tesseract_available() -> bool:
    try:
        import pytesseract  # noqa: F401
    except Exception:
        return False
    _apply_cmd_path()
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _apply_cmd_path() -> None:
    cmd = Config.get("ocr.tesseract_cmd", "")
    if cmd:
        try:
            import pytesseract

            pytesseract.pytesseract.tesseract_cmd = cmd
        except Exception:
            pass


def ocr_image(image) -> str:
    """Run OCR on a PIL.Image and return recognized text."""
    try:
        import pytesseract
    except Exception:
        log.warning("pytesseract not installed; cannot OCR.")
        return ""
    _apply_cmd_path()
    lang = Config.get("ocr.language", "eng")
    try:
        return pytesseract.image_to_string(image, lang=lang)
    except Exception as exc:  # noqa: BLE001
        log.warning("OCR failed: %s", exc)
        return ""
