"""Line item extractor for repeating-block documents.

Automatically detects and parses the repeating order-item pattern found in
carpet/rug order PDFs (and similar trade documents):

    QT26-27-000324                              ← order / quote number
    1 POSH BIO-45 - 1 1896 Na 3.66 SYD 200.0437 808178   ← item header
    CARAMEL ae                                  ← color / style name
    26260347/03A 3.66 45.70 SYD 200.0437 808178 ← roll detail line(s)
    2 POSH BIO-45 - 1 1573. NA 3.66 SYD 196.9796 808178
    ...

Returns a list of dicts, one per item:
    {
        order_num, item_num, sku, color,
        qty, price, unit, extended_price, account,
        roll_count, total_yards,
        rolls: [{roll_id, price, yards, extended, account}]
    }
"""
from __future__ import annotations

import re
from typing import Any


# ── Pattern helpers ────────────────────────────────────────────────────────

_ORDER_RE = re.compile(r'^(QT[\w-]+)$', re.IGNORECASE)

_EM_DASHES = {"—", "–", "-"}

# Colour cleanup: strip trailing 1-2 char OCR artefacts like "ae", "as", "Sa"
_COLOR_TRAILING = re.compile(r'\s+\b\w{1,2}\b\s*$')


# ── Public API ─────────────────────────────────────────────────────────────

def extract_line_items(text: str) -> list[dict[str, Any]]:
    """Parse repeating item blocks from document text.

    Tolerant of minor OCR noise: European decimal commas, stray em-dashes,
    trailing artefact chars on colour names, and blank lines between blocks.

    Returns an empty list when no recognisable item pattern is found.
    """
    if not text:
        return []

    lines = [ln.strip() for ln in text.splitlines()]
    items: list[dict] = []
    current_order = ""
    i = 0

    while i < len(lines):
        line = lines[i]
        if not line:
            i += 1
            continue

        # Order / quote number (e.g. QT26-27-000324)
        if _is_order_line(line):
            current_order = line
            i += 1
            continue

        # Item header line
        item_data = _parse_item_line(line)
        if item_data is not None:
            item_data["order_num"] = current_order

            # Advance past the item line; skip any blanks
            j = i + 1
            while j < len(lines) and not lines[j]:
                j += 1

            # Next non-empty line that looks like a colour name
            if j < len(lines) and _is_color_line(lines[j]):
                item_data["color"] = _clean_color(lines[j])
                j += 1
                # Skip blanks before roll lines
                while j < len(lines) and not lines[j]:
                    j += 1
            else:
                item_data["color"] = ""

            # Collect roll detail lines
            rolls: list[dict] = []
            while j < len(lines):
                if not lines[j]:
                    j += 1
                    continue
                roll = _parse_roll_line(lines[j])
                if roll is not None:
                    rolls.append(roll)
                    j += 1
                else:
                    break  # Next item or non-roll line

            item_data["rolls"] = rolls
            item_data["roll_count"] = len(rolls)
            item_data["total_yards"] = _sum_yards(rolls)
            items.append(item_data)
            i = j
            continue

        i += 1

    return items


def items_detected(text: str) -> bool:
    """Quick check — True if the text contains at least one parseable item block."""
    if not text:
        return False
    for line in text.splitlines():
        if _parse_item_line(line.strip()) is not None:
            return True
    return False


# ── Line classifiers ───────────────────────────────────────────────────────

def _is_order_line(line: str) -> bool:
    """Quote/order number on its own line, e.g. QT26-27-000324."""
    return bool(_ORDER_RE.match(line))


def _is_color_line(line: str) -> bool:
    """Color/style names start with a letter and have no leading digits or slashes."""
    if not line or not line[0].isalpha():
        return False
    if "/" in line[:10]:          # Roll IDs contain a slash early
        return False
    if _is_order_line(line):      # Don't misclassify order numbers
        return False
    return True


# ── Line parsers ───────────────────────────────────────────────────────────

def _parse_item_line(line: str) -> dict[str, Any] | None:
    """
    Parse an item header of the form:
        N [— ] SKU - qty code flag price SYD extended account

    Example:
        1 POSH BIO-45 - 1 1896 Na 3.66 SYD 200.0437 808178
        8 — POSH BIO-30 - 4 1045 NA 4.60 SYD 863.7440 808488
    """
    # Must start with a digit and contain SYD
    if not line or not line[0].isdigit():
        return None
    upper = line.upper()
    if "SYD" not in upper:
        return None

    syd_pos = upper.index("SYD")
    before = line[:syd_pos].strip()
    after  = line[syd_pos + 3:].strip()

    # After SYD: "extended account [extra...]"
    after_tok = after.split()
    if len(after_tok) < 2:
        return None
    extended = after_tok[0]
    account  = after_tok[1]

    # Before SYD: "N [—] SKU - qty code flag price"
    before_tok = before.split()
    if len(before_tok) < 5:
        return None

    # Last token = price per unit
    price_raw = before_tok[-1]
    price = price_raw.replace(",", ".")
    try:
        float(price)
    except ValueError:
        return None

    # Second-to-last token = NA/Na/etc flag — remove it
    # (It's always non-numeric, e.g. "Na", "NA", "sYD" typo)
    remaining_tok = before_tok[:-2]          # drop price + flag
    # "1 POSH BIO-45 - 1 1896"

    # The last remaining token might be a style code (all digits)
    # Remove it so we don't confuse it with qty
    if remaining_tok and _is_numeric(remaining_tok[-1]):
        # Only remove if there's still a " - " separator left after removal
        candidate = remaining_tok[:-1]
        if " - " in " ".join(candidate):
            remaining_tok = candidate

    remaining = " ".join(remaining_tok)

    # Split on LAST " - " to separate "N SKU" from "qty"
    dash_idx = remaining.rfind(" - ")
    if dash_idx < 0:
        return None

    left  = remaining[:dash_idx].strip()   # "1 POSH BIO-45"
    right = remaining[dash_idx + 3:].strip()  # "1" or "1 1896"

    left_tok = left.split()
    if not left_tok:
        return None

    item_num = left_tok[0]
    if not item_num.isdigit():
        return None

    sku_tok = left_tok[1:]
    # Strip optional leading em-dash artefact
    if sku_tok and sku_tok[0] in _EM_DASHES:
        sku_tok = sku_tok[1:]
    sku = " ".join(sku_tok).strip()

    right_tok = right.split()
    qty = right_tok[0] if right_tok else ""

    return {
        "item_num": item_num,
        "sku": sku,
        "qty": qty,
        "price": price,
        "unit": "SYD",
        "extended_price": extended,
        "account": account,
    }


def _parse_roll_line(line: str) -> dict[str, Any] | None:
    """
    Parse a roll detail line of the form:
        roll_id price yards SYD extended account

    Example:
        26260347/03A 3.66 45.70 SYD 200.0437 808178
        22260415/02B 4.60 38,00 SYD 209.0591 808178
    """
    tokens = line.split()
    if not tokens or "/" not in tokens[0]:
        return None
    upper_tokens = [t.upper() for t in tokens]
    if "SYD" not in upper_tokens:
        return None
    syd_idx = upper_tokens.index("SYD")
    if syd_idx < 3:
        return None

    roll_id  = tokens[0]
    price    = tokens[syd_idx - 2].replace(",", ".")
    yards    = tokens[syd_idx - 1].replace(",", ".")
    extended = tokens[syd_idx + 1] if syd_idx + 1 < len(tokens) else ""
    account  = tokens[syd_idx + 2] if syd_idx + 2 < len(tokens) else ""

    # Quick sanity: yards should be numeric-ish
    try:
        float(yards)
    except ValueError:
        return None

    return {
        "roll_id": roll_id,
        "price": price,
        "yards": yards,
        "extended": extended,
        "account": account,
    }


# ── Utilities ──────────────────────────────────────────────────────────────

def _clean_color(line: str) -> str:
    """Remove trailing 1-2 char OCR artefacts: 'CARAMEL ae' → 'CARAMEL'."""
    return _COLOR_TRAILING.sub("", line).strip()


def _is_numeric(s: str) -> bool:
    try:
        float(s.replace(",", ".").rstrip("."))
        return True
    except ValueError:
        return False


def _sum_yards(rolls: list[dict]) -> str:
    """Sum yards across all rolls in a group."""
    try:
        total = sum(float(r["yards"]) for r in rolls if r.get("yards"))
        return f"{total:.2f}"
    except (ValueError, TypeError):
        return ""
