"""Templates page: review and remove saved document layouts per task."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.local_store import LocalStore
from app.ui.widgets import card, label, page_header, row


class TemplatesPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.store = LocalStore.instance()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)
        outer.addWidget(
            page_header(
                "Templates",
                "Saved document layouts. A matching document reuses its mapping automatically.",
            )
        )

        self.task_combo = QComboBox()
        self.task_combo.setMinimumWidth(240)
        self.task_combo.currentIndexChanged.connect(self._load)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_tasks)
        delete = QPushButton("Delete selected")
        delete.setObjectName("danger")
        delete.clicked.connect(self._delete)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Template", "File type", "Created", "Updated"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)

        outer.addWidget(
            card(
                row(label("Task:"), self.task_combo, refresh, delete),
                self.table,
            ),
            1,
        )
        self.refresh_tasks()

    def refresh_tasks(self) -> None:
        current = self.task_combo.currentData()
        self.task_combo.blockSignals(True)
        self.task_combo.clear()
        for t in self.store.list_tasks():
            self.task_combo.addItem(t["name"], t["id"])
        self.task_combo.blockSignals(False)
        if current is not None:
            idx = self.task_combo.findData(current)
            if idx >= 0:
                self.task_combo.setCurrentIndex(idx)
        self._load()

    def _load(self) -> None:
        self.table.setRowCount(0)
        task_id = self.task_combo.currentData()
        if task_id is None:
            return
        for tpl in self.store.list_templates(task_id):
            r = self.table.rowCount()
            self.table.insertRow(r)
            name_item = QTableWidgetItem(tpl["name"])
            name_item.setData(Qt.UserRole, tpl["id"])
            self.table.setItem(r, 0, name_item)
            self.table.setItem(r, 1, QTableWidgetItem(tpl["file_type"]))
            self.table.setItem(r, 2, QTableWidgetItem(tpl["created_at"]))
            self.table.setItem(r, 3, QTableWidgetItem(tpl["updated_at"]))

    def _delete(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            return
        tpl_id = self.table.item(r, 0).data(Qt.UserRole)
        if (
            QMessageBox.question(self, "Delete template", "Remove this saved layout?")
            == QMessageBox.Yes
        ):
            self.store.delete_template(int(tpl_id))
            self._load()
