"""Field extraction orchestrator.

Combines deterministic locators (saved in a template mapping) with an AI fallback
to produce a value for every field a task requires. Deterministic methods are
preferred (free, repeatable); AI fills the gaps when no mapping exists.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.logging_config import get_logger
from app.extraction.ai_extractor import AIResult, ai_enabled, extract_with_ai

log = get_logger(__name__)


@dataclass
class ExtractedField:
    field_key: str
    display_name: str
    value: str | None
    method: str            # regex|anchor|cell|fixed|ai|none
    confidence: float
    source_hint: str = ""
    required: bool = True


@dataclass
class ExtractionResult:
    fields: dict[str, ExtractedField] = field(default_factory=dict)
    ai_used: bool = False
    ai_message: str = ""

    def missing_required(self) -> list[str]:
        return [
            f.display_name
            for f in self.fields.values()
            if f.required and not (f.value or "").strip()
        ]


def extract_fields(
    loaded_doc,
    task_fields: list[dict[str, Any]],
    mappings: list[dict[str, Any]] | None = None,
) -> ExtractionResult:
    mappings = mappings or []
    mapping_by_key = {m["field_key"]: m for m in mappings}
    result = ExtractionResult()

    unresolved_specs: list[dict[str, Any]] = []

    for spec in task_fields:
        key = spec["field_key"]
        mapping = mapping_by_key.get(key)
        value, method, conf, hint = None, "none", 0.0, ""

        if mapping:
            value, conf, hint = _apply_locator(
                mapping.get("method", "ai"), mapping.get("locator", {}), loaded_doc
            )
            method = mapping.get("method", "ai")

        if (value is None or not str(value).strip()) and method != "ai":
            # deterministic mapping missed -> defer to AI
            unresolved_specs.append(spec)
            method = "none"

        if not mapping:
            unresolved_specs.append(spec)

        result.fields[key] = ExtractedField(
            field_key=key,
            display_name=spec.get("display_name", key),
            value=(str(value).strip() if value is not None else None),
            method=method,
            confidence=conf,
            source_hint=hint,
            required=bool(spec.get("required", True)),
        )

    # AI fallback for everything still unresolved.
    if unresolved_specs and ai_enabled():
        ai: AIResult = extract_with_ai(unresolved_specs, loaded_doc.full_text)
        result.ai_used = ai.ok
        result.ai_message = ai.message
        for spec in unresolved_specs:
            key = spec["field_key"]
            got = ai.values.get(key)
            if got and got.get("value"):
                ef = result.fields[key]
                ef.value = str(got["value"]).strip()
                ef.method = "ai"
                ef.confidence = float(got.get("confidence", 0) or 0)
                ef.source_hint = got.get("source_hint", "")

    return result


def _apply_locator(
    method: str, locator: dict[str, Any], loaded_doc
) -> tuple[str | None, float, str]:
    try:
        if method == "fixed":
            return str(locator.get("value", "")), 100.0, "fixed"
        if method == "regex":
            return _regex_locator(locator, loaded_doc)
        if method == "anchor":
            return _anchor_locator(locator, loaded_doc)
        if method == "cell":
            return _cell_locator(locator, loaded_doc)
    except Exception as exc:  # noqa: BLE001
        log.warning("Locator (%s) failed: %s", method, exc)
    return None, 0.0, ""


def _regex_locator(locator, loaded_doc) -> tuple[str | None, float, str]:
    pattern = locator.get("pattern", "")
    group = int(locator.get("group", 1))
    if not pattern:
        return None, 0.0, ""
    m = re.search(pattern, loaded_doc.full_text, re.IGNORECASE | re.MULTILINE)
    if not m:
        return None, 0.0, ""
    try:
        val = m.group(group)
    except (IndexError, re.error):
        val = m.group(0)
    return val, 92.0, m.group(0)[:80]


def _anchor_locator(locator, loaded_doc) -> tuple[str | None, float, str]:
    anchor = locator.get("anchor", "")
    if not anchor:
        return None, 0.0, ""
    text = loaded_doc.full_text
    idx = text.lower().find(anchor.lower())
    if idx == -1:
        return None, 0.0, ""
    after = text[idx + len(anchor):]
    value_re = locator.get("regex", r"[:\s]*([^\n\r]+)")
    m = re.search(value_re, after)
    if not m:
        return None, 0.0, ""
    val = (m.group(1) if m.groups() else m.group(0)).strip(" :\t")
    return val, 85.0, f"{anchor} -> {val[:60]}"


def _cell_locator(locator, loaded_doc) -> tuple[str | None, float, str]:
    t = int(locator.get("table", 0))
    r = int(locator.get("row", 0))
    c = int(locator.get("col", 0))
    if t < len(loaded_doc.tables):
        table = loaded_doc.tables[t]
        if r < len(table) and c < len(table[r]):
            val = table[r][c]
            return val, 95.0, f"table{t}[{r},{c}]"
    return None, 0.0, ""
