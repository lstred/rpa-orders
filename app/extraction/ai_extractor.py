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
import re
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


# ──────────────────────────────────────────────────────────────────────────────
# Line-item AI analysis
# ──────────────────────────────────────────────────────────────────────────────

_LINE_ITEMS_SCHEMA = """\
Return a JSON array where each element is one order line item:
{
  "order_num":      "QT26-27-000324",
  "item_num":       "1",
  "sku":            "POSH BIO-45",
  "color":          "CARAMEL",
  "full_name":      "POSH BIO-45 CARAMEL",
  "qty":            "1",
  "price":          "3.66",
  "unit":           "SYD",
  "extended_price": "200.0437",
  "account":        "808178",
  "roll_count":     1,
  "total_yards":    "45.70"
}
Rules:
- De-duplicate: if the same item (same order_num + item_num) appears more than once
  in the document (e.g., on an invoice page and again on a packing slip), include it
  ONLY ONCE.
- Do NOT include totals, sub-totals, freight lines, or header rows.
- item_num must be a small positive integer (1-999) as a string.
- roll_count and total_yards summarise the roll detail lines below each item header.
- Use "" for any field you cannot find; never invent values.
- Return ONLY the JSON array — no prose, no code fences."""


def analyze_line_items_with_ai(
    document_text: str,
    user_instruction: str = "",
    conversation: list[dict] | None = None,
) -> tuple[list[dict], str]:
    """Ask the configured AI to identify and structure line items in a document.

    Args:
        document_text: Full text of the loaded document.
        user_instruction: Natural-language description / correction from the user.
        conversation: Prior turns as [{role, content}] for multi-turn refinement.

    Returns:
        (items, ai_reply_text) — items is an empty list on failure, ai_reply_text
        is the raw text the AI returned (or an error message).
    """
    if not ai_enabled():
        return [], "AI is not enabled. Go to Settings → enable AI and add an API key."

    provider = (Config.get("ai.provider", "anthropic") or "anthropic").lower()
    model = Config.get("ai.model", "")

    system_msg = (
        "You are a precise document-parsing assistant. "
        "The user will show you business document text and describe how line items "
        "are structured. You extract the items and return strict JSON only."
    )

    # Build the user turn
    user_turn_parts = []
    if user_instruction:
        user_turn_parts.append(f"INSTRUCTION:\n{user_instruction}\n")
    user_turn_parts.append(
        f"DOCUMENT TEXT (first 20 000 chars):\n\"\"\"\n"
        f"{document_text[:20000]}\n\"\"\"\n"
    )
    user_turn_parts.append(_LINE_ITEMS_SCHEMA)
    user_content = "\n".join(user_turn_parts)

    # Build message list (support multi-turn)
    messages: list[dict] = []
    if conversation:
        messages.extend(conversation)
    messages.append({"role": "user", "content": user_content})

    try:
        if provider == "anthropic":
            raw = _call_anthropic_chat(messages, model, system_msg)
        elif provider == "openai":
            raw = _call_openai_chat(messages, model, system_msg)
        else:
            return [], f"Unknown AI provider '{provider}'."
    except Exception as exc:  # noqa: BLE001
        log.warning("analyze_line_items_with_ai failed: %s", exc)
        return [], str(exc)

    items = _parse_items_json(raw)
    return items, raw


def _parse_items_json(raw: str) -> list[dict]:
    """Parse a JSON array of line items from AI output."""
    raw = (raw or "").strip()
    # Strip code fences
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
        raw = raw.replace("```", "").strip()
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        # Maybe AI returned an object with an items key
        oc, oe = raw.find("{"), raw.rfind("}")
        if oc != -1 and oe != -1:
            try:
                obj = json.loads(raw[oc : oe + 1])
                for v in obj.values():
                    if isinstance(v, list):
                        return _normalise_items(v)
            except json.JSONDecodeError:
                pass
        return []
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return []
    return _normalise_items(data) if isinstance(data, list) else []


def _normalise_items(raw_list: list) -> list[dict]:
    """Ensure every item has the expected keys and correct types."""
    import re as _re
    result = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        item_num = str(item.get("item_num", "")).strip()
        if not item_num or not item_num.isdigit() or int(item_num) > 999:
            continue
        sku = str(item.get("sku", "")).strip()
        color = str(item.get("color", "")).strip()
        result.append({
            "order_num":      str(item.get("order_num", "")).strip(),
            "item_num":       item_num,
            "sku":            sku,
            "color":          color,
            "full_name":      str(item.get("full_name", "") or f"{sku} {color}").strip(),
            "qty":            str(item.get("qty", "")).strip(),
            "price":          str(item.get("price", "")).strip(),
            "unit":           "SYD",
            "extended_price": str(item.get("extended_price", "")).strip(),
            "account":        str(item.get("account", "")).strip(),
            "roll_count":     int(item.get("roll_count", 0) or 0),
            "total_yards":    str(item.get("total_yards", "")).strip(),
            "source":         "ai",
            "rolls":          [],
        })
    return result


def _call_anthropic_chat(messages: list[dict], model: str, system_msg: str) -> str:
    import anthropic
    key = get_secret(ANTHROPIC_KEY)
    if not key:
        raise RuntimeError("Anthropic API key not set (Settings page).")
    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(
        model=model or "claude-sonnet-4-20250514",
        max_tokens=int(Config.get("ai.max_output_tokens", 4096)),
        temperature=float(Config.get("ai.temperature", 0.0)),
        system=system_msg,
        messages=messages,
    )
    return "".join(
        block.text for block in resp.content if getattr(block, "type", "") == "text"
    )


def _call_openai_chat(messages: list[dict], model: str, system_msg: str) -> str:
    from openai import OpenAI
    key = get_secret(OPENAI_KEY)
    if not key:
        raise RuntimeError("OpenAI API key not set (Settings page).")
    client = OpenAI(api_key=key)
    all_msgs = [{"role": "system", "content": system_msg}] + messages
    resp = client.chat.completions.create(
        model=model or "gpt-4o",
        temperature=float(Config.get("ai.temperature", 0.0)),
        max_tokens=int(Config.get("ai.max_output_tokens", 4096)),
        messages=all_msgs,
    )
    return resp.choices[0].message.content or ""
