"""Diagnostic: build the real MainWindow, show it, and report its position."""
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.core import paths
from app.core.config import Config
from app.ui.main_window import MainWindow
from app.ui.theme import stylesheet

paths.ensure_dirs()
Config.load()

app = QApplication(sys.argv)
app.setStyleSheet(stylesheet())
w = MainWindow()
w.show()
w.center_on_primary()
w.bring_to_front()

def report():
    g = w.geometry().getRect()
    print("PLATFORM:", app.platformName(), flush=True)
    print("isVisible:", w.isVisible(), "isActive:", w.isActiveWindow(), flush=True)
    print("geometry(x,y,w,h):", g, flush=True)
    print("primary:", (app.primaryScreen().name(), app.primaryScreen().availableGeometry().getRect()), flush=True)
    print("RESULT:", "ON_SCREEN" if g[0] >= 0 and g[1] >= 0 else "OFFSCREEN", flush=True)

QTimer.singleShot(800, report)
QTimer.singleShot(5000, app.quit)
sys.exit(app.exec())
