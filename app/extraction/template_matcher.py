"""Template matching: recognize a document's layout from previously saved
templates so the right field mappings are applied automatically."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz


@dataclass
class TemplateMatch:
    template: dict[str, Any]
    score: float


def _fingerprint_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 100.0
    # fingerprints are hashes; identical layouts hash identically. As a softer
    # signal we also compare against stored sample text elsewhere.
    return 100.0 if a == b else 0.0


def best_template(
    loaded_doc, candidate_templates: list[dict[str, Any]]
) -> TemplateMatch | None:
    """Pick the best-matching saved template for a loaded document.

    Primary signal: exact fingerprint match. Secondary: fuzzy similarity of the
    stored sample text against the new document text (handles minor drift).
    """
    if not candidate_templates:
        return None

    best: TemplateMatch | None = None
    doc_fp = loaded_doc.fingerprint
    doc_text = (loaded_doc.full_text or "")[:6000]

    for tpl in candidate_templates:
        if tpl.get("file_type") and tpl["file_type"] != loaded_doc.file_type:
            continue
        score = _fingerprint_similarity(doc_fp, tpl.get("fingerprint", ""))
        if score < 100.0 and tpl.get("sample_text"):
            score = max(
                score,
                float(fuzz.token_set_ratio(doc_text, tpl["sample_text"][:6000])),
            )
        if best is None or score > best.score:
            best = TemplateMatch(template=tpl, score=score)

    return best
