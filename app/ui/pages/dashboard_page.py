"""Dashboard: at-a-glance status and recent activity."""
from __future__ import annotations

import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core import paths
from app.core.config import Config
from app.core.local_store import LocalStore
from app.core.security import has_secret
from app.extraction.ai_extractor import ANTHROPIC_KEY, OPENAI_KEY
from app.ui.widgets import card, label, page_header


class DashboardPage(QWidget):
    def __init__(self, go_to=None) -> None:
        super().__init__()
        self.store = LocalStore.instance()
        self.go_to = go_to

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)

        header = QHBoxLayout()
        header.addWidget(
            page_header("Dashboard", "Orders RPA Bridge — document-to-ERP hand-off.")
        )
        header.addStretch(1)
        start = QPushButton("Process a document")
        start.setObjectName("primary")
        if self.go_to:
            start.clicked.connect(lambda: self.go_to("process"))
        header.addWidget(start, 0, Qt.AlignTop)
        hw = QWidget()
        hw.setLayout(header)
        outer.addWidget(hw)

        self.stats_grid = QGridLayout()
        self.stats_grid.setSpacing(14)
        grid_w = QWidget()
        grid_w.setLayout(self.stats_grid)
        outer.addWidget(grid_w)

        outer.addWidget(self._recent_card(), 1)
        self.refresh()

    def _stat(self, title: str, value: str, accent: str = "#e6edf3") -> QFrame:
        v = QLabel(value)
        v.setObjectName("statBig")
        v.setStyleSheet(f"color:{accent};")
        t = QLabel(title)
        t.setObjectName("muted")
        return card(v, t, spacing=2)

    def _recent_card(self) -> QWidget:
        self.recent = QTableWidget(0, 4)
        self.recent.setHorizontalHeaderLabels(["Document", "Task", "Status", "When"])
        self.recent.horizontalHeader().setStretchLastSection(True)
        self.recent.verticalHeader().setVisible(False)
        self.recent.setEditTriggers(QAbstractItemView.NoEditTriggers)

        # Exports folder quick access
        paths.ensure_dirs()
        exports_count = len(list(paths.EXPORTS_DIR.glob("*.json")))
        exports_label = QLabel(
            f"📁  Exports saved to:  {paths.EXPORTS_DIR}"
            + (f"  ({exports_count} file{'s' if exports_count != 1 else ''})" if exports_count else "  (empty)")
        )
        exports_label.setObjectName("muted")
        exports_label.setWordWrap(True)
        exports_label.setStyleSheet("font-size:12px; padding:2px 0;")

        open_btn = QPushButton("📂  Open exports folder")
        open_btn.setToolTip(str(paths.EXPORTS_DIR))
        open_btn.clicked.connect(lambda: subprocess.Popen(["explorer.exe", str(paths.EXPORTS_DIR)]))

        exports_row = QHBoxLayout()
        exports_row.addWidget(exports_label, 1)
        exports_row.addWidget(open_btn)
        exports_w = QWidget()
        exports_w.setLayout(exports_row)

        return card(
            label("Recent documents", "cardTitle"),
            exports_w,
            self.recent,
        )

    def refresh(self) -> None:
        # stats
        for i in reversed(range(self.stats_grid.count())):
            w = self.stats_grid.itemAt(i).widget()
            if w:
                w.setParent(None)

        tasks = self.store.list_tasks()
        templates = self.store.all_templates()
        learned_total = sum(len(self.store.list_learned(t["id"])) for t in tasks)
        paths.ensure_dirs()
        exports_total = len(list(paths.EXPORTS_DIR.glob("*.json")))
        ai_on = bool(Config.get("ai.enabled", False)) and (
            has_secret(ANTHROPIC_KEY) or has_secret(OPENAI_KEY)
        )

        self.stats_grid.addWidget(self._stat("Tasks", str(len(tasks)), "#2f81f7"), 0, 0)
        self.stats_grid.addWidget(self._stat("Templates", str(len(templates))), 0, 1)
        self.stats_grid.addWidget(
            self._stat("Learned matches", str(learned_total), "#3fb950"), 0, 2
        )
        self.stats_grid.addWidget(
            self._stat("Exports", str(exports_total), "#3fb950" if exports_total else "#8b949e"), 0, 3
        )
        self.stats_grid.addWidget(
            self._stat(
                "AI extraction",
                "On" if ai_on else "Off",
                "#3fb950" if ai_on else "#8b949e",
            ),
            0,
            4,
        )

        # recent docs
        self.recent.setRowCount(0)
        task_names = {t["id"]: t["name"] for t in tasks}
        for d in self.store.recent_documents(30):
            r = self.recent.rowCount()
            self.recent.insertRow(r)
            self.recent.setItem(r, 0, QTableWidgetItem(d["file_name"]))
            self.recent.setItem(r, 1, QTableWidgetItem(task_names.get(d["task_id"], "—")))
            self.recent.setItem(r, 2, QTableWidgetItem(d["status"]))
            self.recent.setItem(r, 3, QTableWidgetItem(d["created_at"]))
