"""Diagnostic: does a basic Qt window become visible on this machine?"""
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel

app = QApplication(sys.argv)
w = QLabel("If you can read this, Qt windows work.")
w.resize(420, 160)
w.show()

def report():
    print("PLATFORM:", app.platformName(), flush=True)
    print("isVisible:", w.isVisible(), "winId:", int(w.winId()), flush=True)
    print("geometry:", w.geometry().getRect(), flush=True)
    print("screens:", [s.name() for s in app.screens()], flush=True)

QTimer.singleShot(800, report)
QTimer.singleShot(6000, app.quit)
sys.exit(app.exec())
