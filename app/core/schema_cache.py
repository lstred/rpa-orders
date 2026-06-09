"""NRF_REPORTS schema cache — provides table/column lists for the field editor.

Primary source: hardcoded ground-truth schema (always available offline).
Optional live refresh: queries INFORMATION_SCHEMA when connected to the warehouse.
Column info is used to populate SQL table/column dropdowns in the Task field editor.
"""
from __future__ import annotations

import threading

from app.core.logging_config import get_logger

log = get_logger(__name__)

# Verified NRF_REPORTS columns per table (ground truth from CLAUDE.md).
KNOWN_SCHEMA: dict[str, list[str]] = {
    "_ORDERS": [
        "ITEM_MFGR_COLOR_PAT", "QUANTITY_ORDERED", "UNIT_OF_MEASURE",
        "ORDER_SHIP_DATE", "INVOICE_SHIP_DATE", "ORDER#", "LINE#I",
        "ACCOUNT#I", "BANK_NAME2", "CUSTOMER_PO#", "ENTENDED_PRICE_NO_FUNDS",
        "LINE_GPD_WITHOUT_FUNDS", "LINE_GPP_WITH_FUNDS", "N_NOT_INVENTORY",
        "ORDER_ENTRY_DATE_YYYYMMDD", "INVOICE_DATE_YYYYMMDD", "INVOICE#",
        "DETAIL_LINE_STATUS", "PO_ETA_DATE", "SUPPLIER#", "SALESPERSON_DESC",
        "ITEM_WIDTH_INCHES_IF_R", "CREDIT_TYPE_CODE", "ITEM_DESC_1",
        "PRICE_PER_UM", "COST_PER_UM",
    ],
    "ITEM": [
        "ItemNumber", "IPRCCD", "ICCTR", "IPRODL", "IMFGR", "INAME",
        "ISUPP#", "IDELIV", "IWIDTH", "IINVEN", "IIXREF", "IDISCD",
        "IPOL1", "IPOL2", "IPOL3",
    ],
    "BILLTO": ["BACCT#", "BNAME", "BBANK2", "BADDR1"],
    "BILLSLMN": ["BSACCT", "BSSLMN", "BSCODE", "BSDEL"],
    "SALESMAN": ["YSLMN#", "YNAME"],
    "ROLLS": ["ItemNumber", "Available", "RUM", "RROLL#", "RLOC1", "RCODE@", "RLRCTD"],
    "PRICE": ["$PRCCD", "$LIST#", "$DESC"],
    "CLASSES": ["CLCAT", "CLCODE", "CLDESC"],
    "BILL_CD": ["BCACCT", "BCCODE", "BCCAT", "DateFormatted"],
    "OPENPO_D": ["D@MFGR", "D@COLO", "D@PATT", "D@QTYO", "D@QTYP",
                 "D@ACCT", "D@DEL8", "D@SUPP", "D@REF#"],
    "OPENPO_M": ["M@REF#", "M@GL#", "M@MISP", "M@MSG"],
    "OPENIV": ["NREFTY", "NDATE", "NPO#", "NRECEI", "NMFGR", "NCOLOR", "NPAT"],
    "PRODLINE": ["LPROD#", "LMFGR#", "LNAME", "LDELIV"],
    "ITEMSTK": ["ItemNumber", "JSTOCK"],
    "_INVENTORY": ["Item", "TotalCost"],
    "ClydeMarketingHistory": [
        "CustomerNumber", "MarketingCode", "FiscalYear",
        "TotalSales", "TotalCost", "Profit",
    ],
}

_lock = threading.Lock()
_schema: dict[str, list[str]] = dict(KNOWN_SCHEMA)
_refreshed = False


def get_tables() -> list[str]:
    """Return sorted list of all known table names."""
    with _lock:
        return sorted(_schema.keys())


def get_columns(table: str) -> list[str]:
    """Return column names for a given table (empty list if unknown)."""
    with _lock:
        return list(_schema.get(table, []))


def is_refreshed() -> bool:
    return _refreshed


def refresh_from_db() -> tuple[bool, str]:
    """Query INFORMATION_SCHEMA to update the live schema.
    Returns (success, message). Safe to call when offline — falls back silently.
    """
    global _refreshed
    try:
        from app.core.database import read_dataframe

        df = read_dataframe(
            "SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = 'dbo' "
            "ORDER BY TABLE_NAME, ORDINAL_POSITION"
        )
        with _lock:
            live: dict[str, list[str]] = {}
            for _, row in df.iterrows():
                tbl = str(row["TABLE_NAME"])
                col = str(row["COLUMN_NAME"])
                live.setdefault(tbl, []).append(col)
            _schema.update(live)
            _refreshed = True
        msg = f"Loaded {len(_schema)} tables from NRF_REPORTS."
        log.info("Schema refreshed: %s", msg)
        return True, msg
    except Exception as exc:  # noqa: BLE001
        msg = f"Using built-in schema (offline or not connected): {exc}"
        log.debug("Schema refresh failed: %s", exc)
        return False, msg
