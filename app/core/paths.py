"""Centralized filesystem paths. All app data lives under a per-user app-data
directory so the installed program never writes inside Program Files."""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "OrdersRpaBridge"


def _base_data_dir() -> Path:
    """Return the per-user writable data directory."""
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if root:
        return Path(root) / APP_DIR_NAME
    return Path.home() / f".{APP_DIR_NAME.lower()}"


# Repository root (where this source tree lives) — used to find bundled config.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = _base_data_dir()
LOGS_DIR = DATA_DIR / "logs"
EXPORTS_DIR = DATA_DIR / "exports"
INBOX_DIR = DATA_DIR / "inbox"
PROCESSED_DIR = DATA_DIR / "processed"
TEMPLATES_PREVIEW_DIR = DATA_DIR / "previews"

LOCAL_DB_PATH = DATA_DIR / "app_store.sqlite3"
CONFIG_PATH = DATA_DIR / "settings.json"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.example.json"


def ensure_dirs() -> None:
    """Create all required writable directories if missing."""
    for d in (
        DATA_DIR,
        LOGS_DIR,
        EXPORTS_DIR,
        INBOX_DIR,
        PROCESSED_DIR,
        TEMPLATES_PREVIEW_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)
