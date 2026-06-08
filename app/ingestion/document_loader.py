"""Unified document loader.

Dispatches a file to the right extractor based on extension and returns a
``LoadedDocument`` with plain text, page-level text, detected tables, a content
hash, and a structural *fingerprint* used to recognize the same layout again.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.logging_config import get_logger

log = get_logger(__name__)

PDF_EXT = {".pdf"}
WORD_EXT = {".docx", ".doc"}
EXCEL_EXT = {".xlsx", ".xlsm", ".xls", ".csv"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"}

SUPPORTED_EXT = PDF_EXT | WORD_EXT | EXCEL_EXT | IMAGE_EXT


@dataclass
class LoadedDocument:
    file_path: str
    file_name: str
    file_type: str           # pdf|word|excel|image
    full_text: str = ""
    pages: list[str] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)  # [table][row][cell]
    used_ocr: bool = False
    file_hash: str = ""
    fingerprint: str = ""

    @property
    def char_count(self) -> int:
        return len(self.full_text)


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_fingerprint(text: str) -> str:
    """Structural signature of a document: a stable hash of its 'shape'.

    We strip out digits and volatile values, keep the skeleton of labels/words,
    and hash the most frequent tokens. Two documents from the same source/layout
    produce the same (or near-identical) fingerprint even when values differ.
    """
    if not text:
        return ""
    lowered = text.lower()
    # remove numbers, dates, currency — keep structural words/labels
    skeleton = re.sub(r"[0-9$.,:/\\#%@()\-]+", " ", lowered)
    tokens = [t for t in re.findall(r"[a-z]{3,}", skeleton)]
    if not tokens:
        return ""
    # top tokens by frequency form the layout signature
    from collections import Counter

    common = sorted(t for t, _ in Counter(tokens).most_common(40))
    signature = "|".join(common)
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()


def classify_extension(ext: str) -> str | None:
    ext = ext.lower()
    if ext in PDF_EXT:
        return "pdf"
    if ext in WORD_EXT:
        return "word"
    if ext in EXCEL_EXT:
        return "excel"
    if ext in IMAGE_EXT:
        return "image"
    return None


def load_document(file_path: str) -> LoadedDocument:
    """Load any supported document into a uniform structure."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)

    file_type = classify_extension(path.suffix)
    if file_type is None:
        raise ValueError(f"Unsupported file type: {path.suffix}")

    doc = LoadedDocument(
        file_path=str(path),
        file_name=path.name,
        file_type=file_type,
        file_hash=_hash_file(path),
    )

    if file_type == "pdf":
        from app.ingestion.pdf_extractor import extract_pdf

        extract_pdf(path, doc)
    elif file_type == "word":
        from app.ingestion.docx_extractor import extract_docx

        extract_docx(path, doc)
    elif file_type == "excel":
        from app.ingestion.excel_extractor import extract_excel

        extract_excel(path, doc)
    elif file_type == "image":
        from app.ingestion.image_extractor import extract_image

        extract_image(path, doc)

    doc.fingerprint = compute_fingerprint(doc.full_text)
    log.info(
        "Loaded %s (%s): %d chars, %d tables, ocr=%s",
        doc.file_name,
        file_type,
        doc.char_count,
        len(doc.tables),
        doc.used_ocr,
    )
    return doc
