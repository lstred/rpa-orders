"""Rotating file + console logging."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.core import paths

_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    paths.ensure_dirs()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        paths.LOGS_DIR / "app.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
