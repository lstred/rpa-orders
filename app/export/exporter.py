"""Exporter.

Produces a clean, RPA-ready payload (JSON + CSV) from a validation report. The
JSON is the canonical hand-off contract for Power Automate: stable keys, resolved
warehouse values, confidence, and a status block so the flow can branch safely.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core import paths
from app.core.logging_config import get_logger

log = get_logger(__name__)


def build_payload(
    task_name: str,
    source_file: str,
    report,
) -> dict[str, Any]:
    """Assemble the canonical hand-off dictionary."""
    fields_out: dict[str, Any] = {}
    for key, fv in report.fields.items():
        fields_out[key] = {
            "display_name": fv.display_name,
            "raw_value": fv.raw_value,
            "resolved_value": fv.resolved_value or fv.raw_value or "",
            "resolved_label": fv.resolved_label,
            "status": fv.status,
            "confidence": round(float(fv.confidence), 1),
            "validation_type": fv.validation_type,
            "required": fv.required,
        }

    return {
        "schema_version": "1.0",
        "task": task_name,
        "source_file": source_file,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ready_to_export": report.ready_to_export,
        "blocking_fields": [f.display_name for f in report.blocking_fields()],
        "fields": fields_out,
    }


def export_json(payload: dict[str, Any], out_path: str | None = None) -> str:
    paths.ensure_dirs()
    if out_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_task = _slug(payload.get("task", "task"))
        out_path = str(paths.EXPORTS_DIR / f"{safe_task}_{stamp}.json")
    Path(out_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.info("Exported JSON -> %s", out_path)
    return out_path


def export_csv(payload: dict[str, Any], out_path: str | None = None) -> str:
    """Flat one-row-per-field CSV — convenient for Power Automate table actions."""
    paths.ensure_dirs()
    if out_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_task = _slug(payload.get("task", "task"))
        out_path = str(paths.EXPORTS_DIR / f"{safe_task}_{stamp}.csv")

    headers = [
        "field_key",
        "display_name",
        "raw_value",
        "resolved_value",
        "status",
        "confidence",
        "required",
    ]
    with Path(out_path).open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for key, f in payload.get("fields", {}).items():
            writer.writerow(
                {
                    "field_key": key,
                    "display_name": f.get("display_name", ""),
                    "raw_value": f.get("raw_value", ""),
                    "resolved_value": f.get("resolved_value", ""),
                    "status": f.get("status", ""),
                    "confidence": f.get("confidence", ""),
                    "required": f.get("required", ""),
                }
            )
    log.info("Exported CSV -> %s", out_path)
    return out_path


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in (text or "task")).strip("_")[:60]
