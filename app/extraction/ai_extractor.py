"""Provider-agnostic AI extraction.

Given document text and a list of field specs, ask an LLM to return a strict JSON
object mapping field_key -> {value, confidence, source_hint}. Supports Anthropic
and OpenAI. The provider and model come from config; the API key comes from the OS
secret vault (never from config or source).

If AI is disabled or no key is present, ``extract_with_ai`` returns an empty result
so the pipeline degrades gracefully to deterministic/manual mapping.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.core.config import Config
from app.core.logging_config import get_logger
from app.core.security import get_secret

log = get_logger(__name__)

ANTHROPIC_KEY = "anthropic_api_key"
OPENAI_KEY = "openai_api_key"

MAX_DOC_CHARS = 24000  # guardrail to control token cost


@dataclass
class AIResult:
    values: dict[str, dict[str, Any]]
    provider: str
    model: str
    ok: bool
    message: str = ""


def ai_enabled() -> bool:
    return bool(Config.get("ai.enabled", False))


def _build_prompt(field_specs: list[dict[str, Any]], document_text: str) -> str:
    lines = [
        "You are a precise data-extraction engine for business documents",
        "(purchase orders, invoices, receiving slips, etc.).",
        "Extract ONLY the requested fields from the document text below.",
        "",
        "Return STRICT JSON: an object whose keys are the field keys, each value an",
        'object: {"value": <string|null>, "confidence": <0-100 int>,',
        '"source_hint": <short snippet you found it in>}.',
        "Use null when a field is genuinely absent. Do not invent values.",
        "",
        "FIELDS TO EXTRACT:",
    ]
    for f in field_specs:
        req = "required" if f.get("required", True) else "optional"
        desc = f.get("description", "") or ""
        lines.append(
            f'- key="{f["field_key"]}" name="{f.get("display_name", f["field_key"])}" '
            f'type={f.get("data_type", "text")} ({req}). {desc}'.strip()
        )
    lines.append("")
    lines.append("DOCUMENT TEXT:")
    lines.append('"""')
    lines.append(document_text[:MAX_DOC_CHARS])
    lines.append('"""')
    lines.append("")
    lines.append("Respond with JSON only. No prose, no code fences.")
    return "\n".join(lines)


def extract_with_ai(
    field_specs: list[dict[str, Any]], document_text: str
) -> AIResult:
    provider = (Config.get("ai.provider", "anthropic") or "anthropic").lower()
    model = Config.get("ai.model", "")
    if not ai_enabled():
        return AIResult({}, provider, model, False, "AI extraction is disabled.")

    prompt = _build_prompt(field_specs, document_text)
    try:
        if provider == "anthropic":
            raw = _call_anthropic(prompt, model)
        elif provider == "openai":
            raw = _call_openai(prompt, model)
        else:
            return AIResult({}, provider, model, False, f"Unknown provider '{provider}'.")
    except Exception as exc:  # noqa: BLE001
        log.warning("AI extraction failed: %s", exc)
        return AIResult({}, provider, model, False, str(exc))

    values = _parse_json(raw)
    return AIResult(values, provider, model, True, "")


def _parse_json(raw: str) -> dict[str, dict[str, Any]]:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[-1] if "\n" in raw else raw
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, val in data.items():
        if isinstance(val, dict):
            out[key] = {
                "value": val.get("value"),
                "confidence": float(val.get("confidence", 0) or 0),
                "source_hint": val.get("source_hint", ""),
            }
        else:
            out[key] = {"value": val, "confidence": 0.0, "source_hint": ""}
    return out


def _call_anthropic(prompt: str, model: str) -> str:
    import anthropic

    key = get_secret(ANTHROPIC_KEY)
    if not key:
        raise RuntimeError("Anthropic API key not set (Settings page).")
    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(
        model=model or "claude-sonnet-4-20250514",
        max_tokens=int(Config.get("ai.max_output_tokens", 4096)),
        temperature=float(Config.get("ai.temperature", 0.0)),
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(
        block.text for block in resp.content if getattr(block, "type", "") == "text"
    )


def _call_openai(prompt: str, model: str) -> str:
    from openai import OpenAI

    key = get_secret(OPENAI_KEY)
    if not key:
        raise RuntimeError("OpenAI API key not set (Settings page).")
    client = OpenAI(api_key=key)
    resp = client.chat.completions.create(
        model=model or "gpt-4o",
        temperature=float(Config.get("ai.temperature", 0.0)),
        max_tokens=int(Config.get("ai.max_output_tokens", 4096)),
        messages=[
            {"role": "system", "content": "You output strict JSON only."},
            {"role": "user", "content": prompt},
        ],
    )
    return resp.choices[0].message.content or ""
