"""Main application window: sidebar navigation + stacked pages."""
from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui.pages.dashboard_page import DashboardPage
from app.ui.pages.exports_page import ExportsPage
from app.ui.pages.instructions_page import InstructionsPage
from app.ui.pages.process_page import ProcessPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.tasks_page import TasksPage
from app.ui.pages.templates_page import TemplatesPage

NAV = [
    ("dashboard",     "  Dashboard"),
    ("process",       "  Process Document"),
    ("tasks",         "  Tasks & Fields"),
    ("templates",     "  Templates"),
    ("exports",       "  Exports"),
    ("settings",      "  Settings"),
    ("instructions",  "  Instructions"),
]


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle("Orders RPA Bridge")
        self.resize(1280, 820)
        self.setMinimumSize(1080, 700)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.stack = QStackedWidget()
        self._keys: list[str] = []
        self._pages: dict[str, QWidget] = {}

        # Build pages (with cross-page refresh hooks).
        self.dashboard = DashboardPage(go_to=self.navigate)
        self.process = ProcessPage()
        self.tasks = TasksPage(on_tasks_changed=self._on_tasks_changed)
        self.templates = TemplatesPage()
        self.exports = ExportsPage()
        self.settings = SettingsPage()
        self.instructions = InstructionsPage()

        page_map = {
            "dashboard": self.dashboard,
            "process": self.process,
            "tasks": self.tasks,
            "templates": self.templates,
            "exports": self.exports,
            "settings": self.settings,
            "instructions": self.instructions,
        }
        for key, page in page_map.items():
            self._pages[key] = page
            self._keys.append(key)
            self.stack.addWidget(page)

        root.addWidget(self._sidebar())
        root.addWidget(self.stack, 1)

        self.navigate("dashboard")
        self.center_on_primary()

    def center_on_primary(self) -> None:
        """Place the window centered on the primary screen and bring it to front.

        Multi-monitor setups can otherwise open the window off-screen (e.g. on a
        monitor with negative coordinates), making it look like nothing launched.
        """
        screen = QGuiApplication.primaryScreen() or (
            QGuiApplication.screens()[0] if QGuiApplication.screens() else None
        )
        if screen is None:
            return
        available = screen.availableGeometry()
        size = self.frameGeometry()
        x = available.x() + (available.width() - size.width()) // 2
        y = available.y() + (available.height() - size.height()) // 2
        # Keep within the screen bounds (never negative relative to this screen).
        x = max(available.x(), x)
        y = max(available.y(), y)
        self.move(x, y)

    def bring_to_front(self) -> None:
        """Restore, raise, and activate the window so it is visible to the user."""
        self.showNormal()
        self.raise_()
        self.activateWindow()
        QApplication.processEvents()

    def _sidebar(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("sidebar")
        frame.setFixedWidth(232)
        v = QVBoxLayout(frame)
        v.setContentsMargins(0, 0, 0, 12)
        v.setSpacing(0)

        brand = QLabel("Orders RPA Bridge")
        brand.setObjectName("brand")
        sub = QLabel("Document → Validation → ERP")
        sub.setObjectName("brandSub")
        v.addWidget(brand)
        v.addWidget(sub)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self._nav_buttons: dict[str, QPushButton] = {}
        for key, text in NAV:
            btn = QPushButton(text)
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, k=key: self.navigate(k))
            self.nav_group.addButton(btn)
            self._nav_buttons[key] = btn
            v.addWidget(btn)

        v.addStretch(1)
        version = QLabel("v0.1.0")
        version.setObjectName("brandSub")
        v.addWidget(version)
        return frame

    def navigate(self, key: str) -> None:
        if key not in self._pages:
            return
        self.stack.setCurrentWidget(self._pages[key])
        if key in self._nav_buttons:
            self._nav_buttons[key].setChecked(True)
        # refresh dynamic pages on entry
        if key == "dashboard":
            self.dashboard.refresh()
        elif key == "process":
            self.process.refresh_tasks()
        elif key == "templates":
            self.templates.refresh_tasks()
        elif key == "exports":
            self.exports.refresh()

    def _on_tasks_changed(self) -> None:
        # Guard: this can fire during initial page construction before every
        # page attribute exists.
        if hasattr(self, "process"):
            self.process.refresh_tasks()
        if hasattr(self, "templates"):
            self.templates.refresh_tasks()
        if hasattr(self, "dashboard"):
            self.dashboard.refresh()
