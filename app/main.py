"""Application entry point."""
from __future__ import annotations

import sys

from app.core import paths
from app.core.config import Config
from app.core.logging_config import configure_logging, get_logger


def main() -> int:
    configure_logging()
    log = get_logger("app")
    paths.ensure_dirs()
    Config.load()

    from PySide6.QtWidgets import QApplication

    from app.ui.main_window import MainWindow
    from app.ui.theme import stylesheet

    app = QApplication(sys.argv)
    app.setApplicationName("Orders RPA Bridge")
    app.setStyleSheet(stylesheet())

    window = MainWindow()
    window.show()
    log.info("Orders RPA Bridge started.")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
