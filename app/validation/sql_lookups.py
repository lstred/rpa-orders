"""Concrete NRF_REPORTS lookups + a safe generic exact/fuzzy engine.

Security model:
  * Values are ALWAYS bound via parameterized :name placeholders.
  * Table / column *identifiers* cannot be parameterized in SQL, so they are
    strictly whitelisted with ``_safe_ident`` (alnum + the few special chars the
    warehouse actually uses: # @ $ _) and wrapped in [brackets]. Any identifier
    that fails the whitelist raises — no dynamic SQL ever reaches the server with
    an unvetted identifier.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz, process

from app.core.database import read_dataframe
from app.core.logging_config import get_logger

log = get_logger(__name__)

_IDENT_RE = re.compile(r"^[A-Za-z0-9_#@$]+$")


def _safe_ident(name: str) -> str:
    name = (name or "").strip()
    if not _IDENT_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return f"[{name}]"


# --------------------------------------------------------------------------
# Customer number validation (exact, resolving OLD vs NEW account numbers)
# --------------------------------------------------------------------------
@dataclass
class CustomerMatch:
    found: bool
    new_account: str = ""        # BACCT# (warehouse key)
    old_account: str = ""        # BBANK2 (number reps actually type)
    name: str = ""
    is_closed: bool = False
    message: str = ""


def validate_customer(value: str) -> CustomerMatch:
    """Resolve a typed account number against BOTH the new key (BACCT#) and the
    legacy number (BBANK2). Reps type the old number; the warehouse stores the new.
    """
    value = (value or "").strip()
    if not value:
        return CustomerMatch(False, message="No customer number provided.")

    sql = """
        SELECT TOP 5
               LTRIM(RTRIM([BACCT#]))  AS new_account,
               LTRIM(RTRIM([BBANK2]))  AS old_account,
               LTRIM(RTRIM([BNAME]))   AS account_name
        FROM dbo.BILLTO
        WHERE LTRIM(RTRIM([BACCT#]))  = :v
           OR LTRIM(RTRIM([BBANK2]))  = :v
    """
    try:
        df = read_dataframe(sql, {"v": value})
    except Exception as exc:  # noqa: BLE001
        return CustomerMatch(False, message=f"SQL error: {exc}")

    if df.empty:
        return CustomerMatch(False, message="No matching customer account.")

    row = df.iloc[0]
    name = str(row["account_name"] or "")
    return CustomerMatch(
        found=True,
        new_account=str(row["new_account"] or ""),
        old_account=str(row["old_account"] or ""),
        name=name.lstrip("*").strip(),
        is_closed=name.startswith("*"),
    )


# --------------------------------------------------------------------------
# SKU lookup (exact) + fuzzy candidates from the ITEM master
# --------------------------------------------------------------------------
class _Cache:
    """Tiny TTL cache of candidate lists keyed by (table, value_col, label_cols)."""

    def __init__(self, ttl_seconds: int = 600):
        self.ttl = ttl_seconds
        self._data: dict[str, tuple[float, list[dict[str, str]]]] = {}
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            hit = self._data.get(key)
            if hit and (time.time() - hit[0]) < self.ttl:
                return hit[1]
            return None

    def put(self, key: str, rows: list[dict[str, str]]):
        with self._lock:
            self._data[key] = (time.time(), rows)

    def clear(self):
        with self._lock:
            self._data.clear()


_candidate_cache = _Cache()


def clear_caches() -> None:
    _candidate_cache.clear()


@dataclass
class FuzzyCandidate:
    value: str           # canonical value (e.g. our SKU / ItemNumber)
    label: str           # human label (e.g. item description)
    score: float


def _load_candidates(
    table: str, value_col: str, label_cols: list[str], active_filter: str = ""
) -> list[dict[str, str]]:
    cache_key = f"{table}|{value_col}|{','.join(label_cols)}|{active_filter}"
    cached = _candidate_cache.get(cache_key)
    if cached is not None:
        return cached

    safe_table = table if table.startswith("dbo.") else f"dbo.{table}"
    # validate the bare table name (strip schema for the check)
    _safe_ident(safe_table.split(".", 1)[-1])
    v = _safe_ident(value_col)
    label_select = ", ".join(_safe_ident(c) for c in label_cols) if label_cols else v
    label_expr = (
        " + ' ' + ".join(
            f"ISNULL(LTRIM(RTRIM(CAST({_safe_ident(c)} AS NVARCHAR(200)))), '')"
            for c in label_cols
        )
        if label_cols
        else f"LTRIM(RTRIM(CAST({v} AS NVARCHAR(200))))"
    )
    where = f"WHERE {active_filter}" if active_filter else ""
    sql = (
        f"SELECT DISTINCT LTRIM(RTRIM(CAST({v} AS NVARCHAR(200)))) AS value, "
        f"{label_expr} AS label FROM dbo.{safe_table.split('.', 1)[-1]} {where}"
    )
    try:
        df = read_dataframe(sql)
    except Exception as exc:  # noqa: BLE001
        log.warning("Candidate load failed for %s: %s", table, exc)
        return []
    rows = [
        {"value": str(r["value"] or ""), "label": str(r["label"] or "")}
        for _, r in df.iterrows()
        if str(r["value"] or "").strip()
    ]
    _candidate_cache.put(cache_key, rows)
    return rows


def fuzzy_lookup(
    query: str,
    table: str,
    value_col: str,
    label_cols: list[str],
    active_filter: str = "",
    limit: int = 8,
) -> list[FuzzyCandidate]:
    """Return ranked fuzzy candidates for a free-text query (e.g. a SKU description)."""
    query = (query or "").strip()
    if not query:
        return []
    rows = _load_candidates(table, value_col, label_cols, active_filter)
    if not rows:
        return []
    # match against the combined "value label" haystack
    haystacks = [f"{r['value']} {r['label']}".strip() for r in rows]
    results = process.extract(
        query, haystacks, scorer=fuzz.token_set_ratio, limit=limit
    )
    out: list[FuzzyCandidate] = []
    for _matched, score, idx in results:
        r = rows[idx]
        out.append(FuzzyCandidate(value=r["value"], label=r["label"], score=float(score)))
    return out


def exact_lookup(
    value: str, table: str, value_col: str, match_cols: list[str]
) -> dict[str, Any] | None:
    """Exact match: return the canonical row when ``value`` equals any match column."""
    value = (value or "").strip()
    if not value or not match_cols:
        return None
    safe_table = table.split(".", 1)[-1]
    _safe_ident(safe_table)
    v = _safe_ident(value_col)
    conditions = " OR ".join(
        f"LTRIM(RTRIM(CAST({_safe_ident(c)} AS NVARCHAR(200)))) = :v"
        for c in match_cols
    )
    sql = (
        f"SELECT TOP 1 LTRIM(RTRIM(CAST({v} AS NVARCHAR(200)))) AS value "
        f"FROM dbo.{safe_table} WHERE {conditions}"
    )
    try:
        df = read_dataframe(sql, {"v": value})
    except Exception as exc:  # noqa: BLE001
        log.warning("Exact lookup failed for %s: %s", table, exc)
        return None
    if df.empty:
        return None
    return {"value": str(df.iloc[0]["value"] or "")}
