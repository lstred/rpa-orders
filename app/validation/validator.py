"""Validation engine.

For each extracted field, decide its status by combining three sources in order:
  1. Learned matches  — a value the user previously confirmed for this task/field
                         (the app's memory of customer/SKU nomenclature).
  2. Exact lookup     — the value must equal a real key in the warehouse
                         (customer numbers, real SKUs, etc.).
  3. Fuzzy lookup     — free-text (e.g. a vendor's own description) ranked against
                         the ITEM master with a confidence score for user review.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.config import Config
from app.core.local_store import LocalStore
from app.validation import sql_lookups
from app.validation.sql_lookups import FuzzyCandidate

STATUS_OK = "ok"               # confirmed / exact / learned
STATUS_REVIEW = "review"       # fuzzy — user must confirm/choose
STATUS_UNMATCHED = "unmatched" # nothing found
STATUS_MISSING = "missing"     # required but no value extracted
STATUS_SKIPPED = "skipped"     # no validation configured


@dataclass
class FieldValidation:
    field_key: str
    display_name: str
    raw_value: str | None
    status: str
    validation_type: str
    resolved_value: str = ""
    resolved_label: str = ""
    confidence: float = 0.0
    candidates: list[FuzzyCandidate] = field(default_factory=list)
    message: str = ""
    required: bool = True

    @property
    def is_blocking(self) -> bool:
        """A field blocks export when it's required and not OK."""
        return self.required and self.status != STATUS_OK


@dataclass
class ValidationReport:
    task_id: int
    fields: dict[str, FieldValidation] = field(default_factory=dict)

    @property
    def ready_to_export(self) -> bool:
        return not any(f.is_blocking for f in self.fields.values())

    def blocking_fields(self) -> list[FieldValidation]:
        return [f for f in self.fields.values() if f.is_blocking]


def validate_extraction(
    task_id: int,
    task_fields: list[dict[str, Any]],
    extracted: dict[str, Any],
) -> ValidationReport:
    """``extracted`` maps field_key -> object with a ``value`` attribute/key."""
    store = LocalStore.instance()
    auto_accept = float(Config.get("fuzzy.auto_accept_score", 95))
    review_floor = float(Config.get("fuzzy.review_floor_score", 70))

    report = ValidationReport(task_id=task_id)

    for spec in task_fields:
        key = spec["field_key"]
        ef = extracted.get(key)
        raw = _value_of(ef)
        required = bool(spec.get("required", True))
        vtype = spec.get("validation_type", "none")

        fv = FieldValidation(
            field_key=key,
            display_name=spec.get("display_name", key),
            raw_value=raw,
            status=STATUS_SKIPPED,
            validation_type=vtype,
            required=required,
        )

        if not raw or not raw.strip():
            fv.status = STATUS_MISSING if required else STATUS_SKIPPED
            fv.message = "No value extracted." if required else "Optional, not present."
            report.fields[key] = fv
            continue

        # 1) Learned memory wins immediately.
        learned = store.recall_match(task_id, key, raw)
        if learned:
            fv.status = STATUS_OK
            fv.resolved_value = learned["resolved_value"]
            fv.resolved_label = learned.get("resolved_label", "")
            fv.confidence = float(learned.get("confidence", 100.0))
            fv.message = "Resolved from learned memory."
            report.fields[key] = fv
            continue

        if vtype == "none":
            fv.status = STATUS_OK
            fv.resolved_value = raw
            fv.message = "Accepted (no warehouse validation configured)."
            report.fields[key] = fv
            continue

        if vtype == "exact":
            _run_exact(fv, spec, raw)
        elif vtype == "fuzzy":
            _run_fuzzy(fv, spec, raw, auto_accept, review_floor)

        report.fields[key] = fv

    return report


def _value_of(ef: Any) -> str | None:
    if ef is None:
        return None
    if hasattr(ef, "value"):
        return ef.value
    if isinstance(ef, dict):
        return ef.get("value")
    return str(ef)


def _run_exact(fv: FieldValidation, spec: dict[str, Any], raw: str) -> None:
    table = spec.get("sql_table", "")
    value_col = spec.get("sql_value_col", "")
    match_cols = spec.get("sql_match_cols", []) or []

    # Customers get the dedicated old/new resolver.
    if table.upper() == "BILLTO":
        cm = sql_lookups.validate_customer(raw)
        if cm.found:
            fv.status = STATUS_OK
            fv.resolved_value = cm.new_account
            label = cm.name + (" [CLOSED]" if cm.is_closed else "")
            if cm.old_account:
                label += f" (old #{cm.old_account})"
            fv.resolved_label = label.strip()
            fv.confidence = 100.0
            fv.message = "Customer matched (old/new account resolved)."
        else:
            fv.status = STATUS_UNMATCHED
            fv.message = cm.message
        return

    if not table or not value_col or not match_cols:
        fv.status = STATUS_UNMATCHED
        fv.message = "Exact validation not fully configured for this field."
        return

    hit = sql_lookups.exact_lookup(raw, table, value_col, match_cols)
    if hit:
        fv.status = STATUS_OK
        fv.resolved_value = hit["value"]
        fv.confidence = 100.0
        fv.message = "Exact match in warehouse."
    else:
        fv.status = STATUS_UNMATCHED
        fv.message = f"No exact match in {table}."


def _run_fuzzy(
    fv: FieldValidation,
    spec: dict[str, Any],
    raw: str,
    auto_accept: float,
    review_floor: float,
) -> None:
    table = spec.get("sql_table", "ITEM") or "ITEM"
    value_col = spec.get("sql_value_col", "ItemNumber") or "ItemNumber"
    match_cols = spec.get("sql_match_cols", []) or ["INAME"]
    active_filter = "ISNULL([IINVEN], '') = 'Y'" if table.upper() == "ITEM" else ""

    candidates = sql_lookups.fuzzy_lookup(
        raw, table, value_col, match_cols, active_filter=active_filter, limit=8
    )
    fv.candidates = candidates
    if not candidates:
        fv.status = STATUS_UNMATCHED
        fv.message = "No fuzzy candidates found."
        return

    top = candidates[0]
    fv.confidence = top.score
    if top.score >= auto_accept:
        fv.status = STATUS_OK
        fv.resolved_value = top.value
        fv.resolved_label = top.label
        fv.message = f"High-confidence fuzzy match ({top.score:.0f})."
    elif top.score >= review_floor:
        fv.status = STATUS_REVIEW
        fv.resolved_value = top.value
        fv.resolved_label = top.label
        fv.message = f"Needs review — best {top.score:.0f}. Confirm or choose."
    else:
        fv.status = STATUS_UNMATCHED
        fv.message = f"Low confidence ({top.score:.0f}). Manual selection required."
