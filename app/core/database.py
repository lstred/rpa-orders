"""Read-only connection to the NRF_REPORTS warehouse.

Connection facts (verified ground truth):
  - Server: NRFVMSSQL04 / Database: NRF_REPORTS
  - Windows Trusted Connection only (no SQL logins, no passwords)
  - ODBC Driver 18 for SQL Server (OS-level install)
  - Encrypt=no; must be on NRF network/VPN

Every query goes through parameterized SQLAlchemy text() — never f-strings.
"""
from __future__ import annotations

import threading
from typing import Any

from app.core.config import Config
from app.core.logging_config import get_logger

log = get_logger(__name__)

_engine = None
_engine_lock = threading.Lock()


def _build_odbc_string() -> str:
    driver = Config.get("nrf_sql.driver", "ODBC Driver 18 for SQL Server")
    server = Config.get("nrf_sql.server", "NRFVMSSQL04")
    database = Config.get("nrf_sql.database", "NRF_REPORTS")
    trusted = Config.get("nrf_sql.trusted_connection", True)
    encrypt = Config.get("nrf_sql.encrypt", False)
    parts = [
        f"Driver={{{driver}}}",
        f"Server={server}",
        f"Database={database}",
        f"Trusted_Connection={'Yes' if trusted else 'No'}",
        f"Encrypt={'yes' if encrypt else 'no'}",
    ]
    return ";".join(parts) + ";"


def get_engine():
    """Lazily create (and cache) the SQLAlchemy engine."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        from sqlalchemy import create_engine
        from urllib.parse import quote_plus

        odbc = _build_odbc_string()
        _engine = create_engine(
            f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc)}",
            fast_executemany=True,
            pool_pre_ping=True,
        )
        return _engine


def reset_engine() -> None:
    """Dispose the cached engine (call after changing connection settings)."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None


def read_dataframe(sql: str, params: dict[str, Any] | None = None):
    """Run a parameterized query and return a pandas DataFrame.

    ALWAYS pass user values via ``params`` (:name syntax) — never interpolate.
    """
    import pandas as pd
    from sqlalchemy import text

    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql_query(text(sql), conn, params=params or {})


def test_connection() -> tuple[bool, str]:
    """Return (ok, message). Used by the Settings page to verify connectivity."""
    try:
        from sqlalchemy import text

        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "Connected to NRF_REPORTS on NRFVMSSQL04."
    except Exception as exc:  # noqa: BLE001 - surface any driver/network error
        log.warning("NRF connection test failed: %s", exc)
        return False, str(exc)
