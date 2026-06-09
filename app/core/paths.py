"""Centralized filesystem paths. All app data lives under a per-user app-data
directory so the installed program never writes inside Program Files.

IMPORTANT: Exports are placed in Documents\\Orders RPA Bridge\\Exports so users
can always find them easily in Explorer. Internal data (DB, logs, etc.) stays in
LOCALAPPDATA which Python always resolves correctly even under Windows Store
Python sandbox virtualization.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

APP_DIR_NAME = "OrdersRpaBridge"


def _base_data_dir() -> Path:
    """Return the per-user writable data directory (internal app data)."""
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if root:
        return Path(root) / APP_DIR_NAME
    return Path.home() / f".{APP_DIR_NAME.lower()}"


# Repository root (where this source tree lives) — used to find bundled config.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = _base_data_dir()
LOGS_DIR = DATA_DIR / "logs"
INBOX_DIR = DATA_DIR / "inbox"
PROCESSED_DIR = DATA_DIR / "processed"
TEMPLATES_PREVIEW_DIR = DATA_DIR / "previews"

LOCAL_DB_PATH = DATA_DIR / "app_store.sqlite3"
CONFIG_PATH = DATA_DIR / "settings.json"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.example.json"

# User-visible exports — in Documents so they're always easy to find in Explorer.
# NOT under LOCALAPPDATA which can be sandboxed by the Windows Store Python runtime.
EXPORTS_DIR = Path.home() / "Documents" / "Orders RPA Bridge" / "Exports"


def ensure_dirs() -> None:
    """Create all required writable directories if missing, then migrate old exports."""
    for d in (
        DATA_DIR,
        LOGS_DIR,
        EXPORTS_DIR,
        INBOX_DIR,
        PROCESSED_DIR,
        TEMPLATES_PREVIEW_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)
    _migrate_old_exports()


def _migrate_old_exports() -> None:
    """Move any existing exports from the old LOCALAPPDATA/exports location to Documents."""
    old = DATA_DIR / "exports"
    if not old.exists():
        return
    for f in list(old.glob("*.json")) + list(old.glob("*.csv")):
        dest = EXPORTS_DIR / f.name
        if not dest.exists():
            try:
                shutil.copy2(f, dest)
            except Exception:  # noqa: BLE001
                pass
