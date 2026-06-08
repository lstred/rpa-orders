"""Application configuration. Loads JSON settings from the per-user data dir,
seeding from the bundled example on first run. Secrets are NEVER stored here."""
from __future__ import annotations

import json
import threading
from copy import deepcopy
from typing import Any

from app.core import paths


class Config:
    """Thread-safe accessor for application settings."""

    _lock = threading.RLock()
    _data: dict[str, Any] | None = None

    @classmethod
    def load(cls) -> dict[str, Any]:
        with cls._lock:
            if cls._data is not None:
                return cls._data
            paths.ensure_dirs()
            if paths.CONFIG_PATH.exists():
                cls._data = json.loads(paths.CONFIG_PATH.read_text(encoding="utf-8"))
            elif paths.EXAMPLE_CONFIG_PATH.exists():
                cls._data = json.loads(
                    paths.EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8")
                )
                cls.save()
            else:
                cls._data = {}
            return cls._data

    @classmethod
    def save(cls) -> None:
        with cls._lock:
            if cls._data is None:
                return
            paths.ensure_dirs()
            paths.CONFIG_PATH.write_text(
                json.dumps(cls._data, indent=2), encoding="utf-8"
            )

    @classmethod
    def get(cls, dotted_key: str, default: Any = None) -> Any:
        data = cls.load()
        node: Any = data
        for part in dotted_key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return deepcopy(node)

    @classmethod
    def set(cls, dotted_key: str, value: Any) -> None:
        with cls._lock:
            data = cls.load()
            node = data
            parts = dotted_key.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value
            cls.save()
