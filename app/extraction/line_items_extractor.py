"""Line item extractor for repeating-block documents.

Strategy (in priority order):
  1. pdfplumber table data (``doc.tables``) — preferred; much more reliable
     than text parsing for PDFs with embedded table structure.
  2. Text parsing — fallback for scanned/image PDFs or when tables are absent.

Expected document structure (carpet/rug trade orders):
    QT26-27-000324                              ← order / quote number
    2   POSH BIO-60 -   5   2345   NA   4.60   SYD   661.8369   808178
    GINGERBREAD                                 ← color / style name
        22260427/03   4.60  24.00  SYD  132.0373  808178      ← roll detail
        22260427/03A  4.60  24.20  SYD  133.1376  808178

Each item in the returned list:
    order_num, item_num, sku, color, full_name (sku+color combined),
    qty, price, unit, extended_price, account,
    roll_count, total_yards, source ("table"|"text"),
    rolls: [{roll_id, price, yards, extended, account}]
"""
from __future__ import annotations

import re
from typing import Any


# ── Constants ──────────────────────────────────────────────────────────────

_ORDER_RE = re.compile(r'^(QT[\w\-]+)$', re.IGNORECASE)
_ROLL_ID_RE = re.compile(r'^\d{5,}\/\w+$')     # e.g. 22260427/03A
_COLOR_TRAILING = re.compile(r'\s+\b\w{1,2}\b\s*$')  # strip OCR artefacts

# SKU must contain 2+ consecutive uppercase letters (POSH, BIO, etc.)
_PRODUCT_CODE_RE = re.compile(r'[A-Z]{2,}')


# ── Public API ─────────────────────────────────────────────────────────────

def extract_line_items(
    text: str,
    tables: list[list[list[str]]] | None = None,
) -> list[dict[str, Any]]:
    """Parse repeating item blocks from a document.

    Tries pdfplumber table data first (most reliable), falls back to text.
    Deduplicates by (order_num, item_num) so items appearing on multiple
    sections/pages of the same PDF are counted only once.
    Returns an empty list when no recognisable item pattern is found.
    """
    if tables:
        items = _from_tables(tables)
        if items:
            return _deduplicate(items)
    return _deduplicate(_from_text(text))


def items_detected(text: str, tables: list | None = None) -> bool:
    """Quick check — True if the document contains at least one parseable item."""
    return bool(extract_line_items(text, tables))


# ── Table-based extraction (primary) ───────────────────────────────────────

def _from_tables(tables: list) -> list[dict]:
    all_items: list[dict] = []
    for table in tables:
        items = _parse_one_table(table)
        all_items.extend(items)
    # Post-process
    for it in all_items:
        it["full_name"] = (it["sku"] + " " + it.get("color", "")).strip()
        it["total_yards"] = _sum_yards(it.get("rolls", []))
        it["roll_count"] = len(it.get("rolls", []))
    return all_items


def _parse_one_table(table: list) -> list[dict]:
    """Heuristic table parser — flexible about column positions."""
    if not table or len(table) < 2:
        return []

    # Normalise to strings
    rows = [[c.strip() if c else "" for c in row] for row in table]

    # Find which column most commonly holds "SYD" — this anchors everything else
    syd_col = _find_syd_col(rows)
    if syd_col is None:
        return []  # This table doesn't look like an order table

    items: list[dict] = []
    pending: dict | None = None
    current_order = ""

    for row in rows:
        if not any(row):
            continue

        # Detect order numbers anywhere in the row
        for cell in row:
            if _ORDER_RE.match(cell):
                current_order = cell
                break

        cell0 = row[0]
        cell1 = row[1] if len(row) > 1 else ""

        # ── Item header row: first cell is a small positive integer ──
        if cell0.isdigit() and 1 <= int(cell0) <= 999:
            if pending:
                items.append(pending)
            pending = _parse_item_row(row, syd_col, current_order)
            continue

        # ── Color/style row: first cell empty, second cell is plain text ──
        if (
            not cell0
            and cell1
            and "/" not in cell1
            and not cell1[0].isdigit()
            and re.match(r'[A-Za-z]', cell1)
            and pending is not None
            and not pending.get("color")
        ):
            pending["color"] = _clean_color(cell1)
            continue

        # ── Roll detail row: contains a roll ID (digits/letters with /) ──
        if pending is not None:
            roll = _parse_roll_row(row, syd_col)
            if roll:
                pending.setdefault("rolls", []).append(roll)

    if pending:
        items.append(pending)
    return items


def _find_syd_col(rows: list) -> int | None:
    """Column most frequently containing 'SYD' (case-insensitive)."""
    counts: dict[int, int] = {}
    for row in rows:
        for i, cell in enumerate(row):
            if cell.upper() == "SYD":
                counts[i] = counts.get(i, 0) + 1
    return max(counts, key=counts.get) if counts else None


def _parse_item_row(row: list, syd_col: int, order_num: str) -> dict:
    n = len(row)
    # Price: last numeric cell to the LEFT of syd_col
    price = ""
    for i in range(syd_col - 1, 0, -1):
        val = row[i].replace(",", ".")
        if _is_numeric_str(val):
            price = val
            break
    # Extended + account: first two non-empty cells to the RIGHT of syd_col
    after = [c for c in row[syd_col + 1:] if c.strip()]
    extended = after[0] if after else ""
    account = after[-1] if len(after) > 1 else after[0] if after else ""
    return {
        "order_num": order_num,
        "item_num": row[0],
        "sku": row[1].rstrip(" -").strip() if n > 1 else "",
        "qty": row[2] if n > 2 else "",
        "style_code": row[3] if n > 3 else "",
        "price": price,
        "unit": "SYD",
        "extended_price": extended,
        "account": account,
        "color": "",
        "rolls": [],
        "source": "table",
    }


def _parse_roll_row(row: list, syd_col: int) -> dict | None:
    """Parse a roll detail row identified by a roll ID cell."""
    roll_id = ""
    for cell in row:
        if re.match(r'^\d{5,}/', cell):
            roll_id = cell
            break
    if not roll_id:
        return None

    # Yards: last numeric cell to the LEFT of syd_col
    yards = ""
    if syd_col > 0:
        yards = row[syd_col - 1].replace(",", ".")
    if not _is_numeric_str(yards):
        yards = ""

    # Price: numeric cell left of yards
    price = ""
    for i in range(syd_col - 2, 0, -1):
        val = row[i].replace(",", ".")
        if _is_numeric_str(val):
            price = val
            break

    after = [c for c in row[syd_col + 1:] if c.strip()]
    extended = after[0] if after else ""
    account = after[-1] if len(after) > 1 else after[0] if after else ""

    try:
        float(yards)
    except (ValueError, TypeError):
        return None  # Not a real roll row

    return {
        "roll_id": roll_id,
        "price": price,
        "yards": yards,
        "extended": extended,
        "account": account,
    }


# ── Text-based extraction (fallback) ───────────────────────────────────────

def _from_text(text: str) -> list[dict]:
    """Parse repeating blocks from plain text (e.g. PyMuPDF output or OCR)."""
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

        if _ORDER_RE.match(line):
            current_order = line
            i += 1
            continue

        item_data = _parse_text_item_line(line)
        if item_data is not None:
            item_data["order_num"] = current_order
            j = i + 1

            # Skip blanks
            while j < len(lines) and not lines[j]:
                j += 1

            # Color on next line
            if j < len(lines) and _is_color_line(lines[j]):
                item_data["color"] = _clean_color(lines[j])
                j += 1
                while j < len(lines) and not lines[j]:
                    j += 1

            # Roll detail lines
            rolls: list[dict] = []
            while j < len(lines):
                if not lines[j]:
                    j += 1
                    continue
                roll = _parse_text_roll_line(lines[j])
                if roll is not None:
                    rolls.append(roll)
                    j += 1
                else:
                    break

            item_data["rolls"] = rolls
            item_data["roll_count"] = len(rolls)
            item_data["total_yards"] = _sum_yards(rolls)
            item_data["full_name"] = (item_data["sku"] + " " + item_data.get("color", "")).strip()
            item_data["source"] = "text"
            items.append(item_data)
            i = j
            continue

        i += 1

    return items


def _parse_text_item_line(line: str) -> dict | None:
    """
    Parse a text item line:  N [—] SKU - qty [style] [flag] price SYD extended account

    Examples:
        1 POSH BIO-45 - 1 1896 Na 3.66 SYD 200.0437 808178
        8 — POSH BIO-30 - 4 1045 NA 4.60 SYD 863.7440 808488
        2 POSH BIO-60 - 5 2345 NA 4.60 SYD 661.8369 808178
    """
    if not line or not line[0].isdigit():
        return None
    upper = line.upper()
    if "SYD" not in upper:
        return None

    syd_pos = upper.index("SYD")
    before = line[:syd_pos].strip()
    after = line[syd_pos + 3:].strip()

    after_tok = after.split()
    if len(after_tok) < 2:
        return None
    extended = after_tok[0]
    account = after_tok[1]

    before_tok = before.split()
    if len(before_tok) < 5:
        return None

    # Last token = price/SYD
    price_raw = before_tok[-1].replace(",", ".")
    try:
        float(price_raw)
    except ValueError:
        return None

    # Second-to-last = NA/flag — drop both
    remaining_tok = before_tok[:-2]

    # If last remaining token is numeric (style code), remove it — but only if
    # there's still a " - " separator after removal
    if remaining_tok and _is_numeric_str(remaining_tok[-1]):
        candidate = remaining_tok[:-1]
        if " - " in " ".join(candidate):
            remaining_tok = candidate

    remaining = " ".join(remaining_tok)
    dash_idx = remaining.rfind(" - ")
    if dash_idx < 0:
        return None

    left = remaining[:dash_idx].strip()   # e.g. "1 POSH BIO-45"
    right = remaining[dash_idx + 3:].strip()  # e.g. "1"

    left_tok = left.split()
    if not left_tok:
        return None

    item_num = left_tok[0]
    if not item_num.isdigit():
        return None
    if int(item_num) > 999:          # item numbers are never 4+ digits
        return None

    sku_tok = left_tok[1:]
    # Strip optional em-dash artefact after item number
    if sku_tok and sku_tok[0] in ("—", "–", "-"):
        sku_tok = sku_tok[1:]
    sku = " ".join(sku_tok).strip()

    # Reject if SKU doesn't look like a real product code
    if not _looks_like_product_sku(sku):
        return None

    right_tok = right.split()
    qty = right_tok[0] if right_tok else ""

    return {
        "item_num": item_num,
        "sku": sku,
        "qty": qty,
        "price": price_raw,
        "unit": "SYD",
        "extended_price": extended,
        "account": account,
        "color": "",
    }


def _parse_text_roll_line(line: str) -> dict | None:
    """Parse a roll detail line:  roll_id  price  yards  SYD  extended  account"""
    tokens = line.split()
    if not tokens or "/" not in tokens[0]:
        return None
    # Roll ID must look like: digits/alphanumeric
    if not re.match(r'^\d{5,}/', tokens[0]):
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

    try:
        float(yards)
    except ValueError:
        return None

    return {"roll_id": roll_id, "price": price, "yards": yards,
            "extended": extended, "account": account}


# ── Classifiers & utilities ────────────────────────────────────────────────
def _deduplicate(items: list[dict]) -> list[dict]:
    """Remove duplicate items (same order + item number) keeping first occurrence."""
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for item in items:
        key = (item.get("order_num", ""), item.get("item_num", ""))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique
def _is_color_line(line: str) -> bool:
    """Color/style names: start with a letter, no slash, not an order number."""
    if not line or not line[0].isalpha():
        return False
    if "/" in line[:15]:
        return False
    if _ORDER_RE.match(line):
        return False
    return True


def _looks_like_product_sku(sku: str) -> bool:
    """Reject lines where the 'SKU' looks like prose (page refs, totals, etc.)."""
    if not sku or len(sku) < 3:
        return False
    # Must contain 2+ consecutive uppercase letters (product codes are capitalised)
    return bool(_PRODUCT_CODE_RE.search(sku))


def _clean_color(line: str) -> str:
    """Remove trailing 1-2 char OCR artefacts: 'CARAMEL ae' → 'CARAMEL'."""
    return _COLOR_TRAILING.sub("", line).strip()


def _is_numeric_str(s: str) -> bool:
    if not s:
        return False
    try:
        float(s.replace(",", ".").rstrip("."))
        return True
    except ValueError:
        return False


def _sum_yards(rolls: list) -> str:
    try:
        total = sum(float(r["yards"]) for r in rolls if r.get("yards"))
        return f"{total:.2f}"
    except (ValueError, TypeError):
        return ""
