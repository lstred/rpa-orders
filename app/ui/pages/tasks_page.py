"""Tasks page: define tasks, their fields & validation rules, and learned matches."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.local_store import LocalStore
from app.ui.widgets import card, label, page_header, row

DATA_TYPES = ["text", "number", "date", "money"]
VALIDATIONS = ["none", "exact", "fuzzy"]

FIELD_COLUMNS = [
    "Field key",
    "Display name",
    "Required",
    "Type",
    "Validation",
    "SQL table",
    "Value col",
    "Match cols",
    "Guidance",
]


def _example_tasks() -> list[dict[str, Any]]:
    return [
        {
            "name": "Customer Orders",
            "description": "Inbound purchase orders to be keyed into the ERP.",
            "fields": [
                {"field_key": "customer_number", "display_name": "Customer Number",
                 "required": True, "data_type": "text", "validation_type": "exact",
                 "sql_table": "BILLTO", "sql_value_col": "BACCT#",
                 "sql_match_cols": ["BACCT#", "BBANK2"],
                 "description": "Account number (resolves old BBANK2 and new BACCT#)."},
                {"field_key": "customer_po", "display_name": "Customer PO #",
                 "required": True, "data_type": "text", "validation_type": "none",
                 "description": "The customer's own PO number."},
                {"field_key": "sku", "display_name": "Item / SKU",
                 "required": True, "data_type": "text", "validation_type": "fuzzy",
                 "sql_table": "ITEM", "sql_value_col": "ItemNumber",
                 "sql_match_cols": ["ItemNumber", "INAME"],
                 "description": "Their description fuzzy-matched to our ItemNumber."},
                {"field_key": "quantity", "display_name": "Quantity",
                 "required": True, "data_type": "number", "validation_type": "none",
                 "description": "Quantity ordered in their unit of measure."},
                {"field_key": "ship_date", "display_name": "Requested Ship Date",
                 "required": False, "data_type": "date", "validation_type": "none",
                 "description": "Requested ship date if present."},
            ],
        },
        {
            "name": "Receiving",
            "description": "Inbound receiving slips against open purchase orders.",
            "fields": [
                {"field_key": "po_number", "display_name": "PO Number",
                 "required": True, "data_type": "text", "validation_type": "none",
                 "description": "Our purchase order number on the packing slip."},
                {"field_key": "sku", "display_name": "Item / SKU",
                 "required": True, "data_type": "text", "validation_type": "fuzzy",
                 "sql_table": "ITEM", "sql_value_col": "ItemNumber",
                 "sql_match_cols": ["ItemNumber", "INAME"],
                 "description": "Received item matched to our ItemNumber."},
                {"field_key": "qty_received", "display_name": "Qty Received",
                 "required": True, "data_type": "number", "validation_type": "none",
                 "description": "Quantity physically received."},
                {"field_key": "received_date", "display_name": "Received Date",
                 "required": False, "data_type": "date", "validation_type": "none",
                 "description": "Date goods were received."},
            ],
        },
    ]


class TasksPage(QWidget):
    def __init__(self, on_tasks_changed=None) -> None:
        super().__init__()
        self.store = LocalStore.instance()
        self.on_tasks_changed = on_tasks_changed
        self.current_task_id: int | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)
        outer.addWidget(
            page_header("Tasks", "Define each RPA workflow, its fields, and how to validate them.")
        )

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._left_panel())
        splitter.addWidget(self._right_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 760])
        outer.addWidget(splitter, 1)

        self.refresh_tasks()

    # ---------------- left: task list ----------------
    def _left_panel(self) -> QWidget:
        self.task_list = QTableWidget(0, 1)
        self.task_list.setHorizontalHeaderLabels(["Task"])
        self.task_list.horizontalHeader().setStretchLastSection(True)
        self.task_list.verticalHeader().setVisible(False)
        self.task_list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.task_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.task_list.itemSelectionChanged.connect(self._on_select_task)

        new_btn = QPushButton("New task")
        new_btn.setObjectName("primary")
        new_btn.clicked.connect(self._new_task)
        seed_btn = QPushButton("Add examples")
        seed_btn.clicked.connect(self._seed_examples)
        del_btn = QPushButton("Delete")
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(self._delete_task)

        return card(
            label("Tasks", "cardTitle"),
            self.task_list,
            row(new_btn, seed_btn, del_btn),
        )

    # ---------------- right: editor ----------------
    def _right_panel(self) -> QWidget:
        self.tabs = QTabWidget()
        self.tabs.addTab(self._fields_tab(), "Fields")
        self.tabs.addTab(self._learned_tab(), "Learned matches")
        return self.tabs

    def _fields_tab(self) -> QWidget:
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Task name")
        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("What does this task hand off to the robot?")
        self.desc_edit.setMaximumHeight(70)

        self.fields_table = QTableWidget(0, len(FIELD_COLUMNS))
        self.fields_table.setHorizontalHeaderLabels(FIELD_COLUMNS)
        self.fields_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Interactive
        )
        self.fields_table.horizontalHeader().setStretchLastSection(True)
        self.fields_table.verticalHeader().setVisible(False)

        add_row = QPushButton("Add field")
        add_row.clicked.connect(lambda: self._add_field_row({}))
        rm_row = QPushButton("Remove selected")
        rm_row.setObjectName("danger")
        rm_row.clicked.connect(self._remove_field_row)
        save = QPushButton("Save task")
        save.setObjectName("primary")
        save.clicked.connect(self._save_task)

        c = card(
            label("Task details", "cardTitle"),
            self.name_edit,
            self.desc_edit,
            label("Fields", "cardTitle"),
            self.fields_table,
            row(add_row, rm_row, save),
        )
        return c

    def _learned_tab(self) -> QWidget:
        self.learned_table = QTableWidget(0, 4)
        self.learned_table.setHorizontalHeaderLabels(
            ["Field", "Their value", "Resolves to", "Confidence"]
        )
        self.learned_table.horizontalHeader().setStretchLastSection(True)
        self.learned_table.verticalHeader().setVisible(False)
        self.learned_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        forget = QPushButton("Forget selected")
        forget.setObjectName("danger")
        forget.clicked.connect(self._forget_learned)
        return card(
            label("Learned nomenclature", "cardTitle"),
            label(
                "Confirmed fuzzy matches the app remembers for this task. Forgetting one "
                "makes the app ask again next time.",
                "muted",
            ),
            self.learned_table,
            row(forget),
        )

    # ---------------- data binding ----------------
    def refresh_tasks(self) -> None:
        tasks = self.store.list_tasks()
        self.task_list.setRowCount(0)
        for t in tasks:
            r = self.task_list.rowCount()
            self.task_list.insertRow(r)
            item = QTableWidgetItem(t["name"])
            item.setData(Qt.UserRole, t["id"])
            self.task_list.setItem(r, 0, item)
        if self.on_tasks_changed:
            self.on_tasks_changed()

    def _on_select_task(self) -> None:
        items = self.task_list.selectedItems()
        if not items:
            return
        task_id = items[0].data(Qt.UserRole)
        self._load_task(task_id)

    def _load_task(self, task_id: int) -> None:
        self.current_task_id = task_id
        task = self.store.get_task(task_id)
        if not task:
            return
        self.name_edit.setText(task["name"])
        self.desc_edit.setPlainText(task["description"])
        self.fields_table.setRowCount(0)
        for f in self.store.get_task_fields(task_id):
            self._add_field_row(f)
        self._load_learned(task_id)

    def _load_learned(self, task_id: int) -> None:
        self.learned_table.setRowCount(0)
        for m in self.store.list_learned(task_id):
            r = self.learned_table.rowCount()
            self.learned_table.insertRow(r)
            key_item = QTableWidgetItem(m["field_key"])
            key_item.setData(Qt.UserRole, m["id"])
            self.learned_table.setItem(r, 0, key_item)
            self.learned_table.setItem(r, 1, QTableWidgetItem(m["source_value"]))
            lbl = m["resolved_value"] + (
                f"  ({m['resolved_label']})" if m.get("resolved_label") else ""
            )
            self.learned_table.setItem(r, 2, QTableWidgetItem(lbl))
            self.learned_table.setItem(
                r, 3, QTableWidgetItem(f"{float(m.get('confidence', 0)):.0f}")
            )

    def _add_field_row(self, f: dict[str, Any]) -> None:
        t = self.fields_table
        r = t.rowCount()
        t.insertRow(r)
        t.setItem(r, 0, QTableWidgetItem(f.get("field_key", "")))
        t.setItem(r, 1, QTableWidgetItem(f.get("display_name", "")))

        req = QComboBox()
        req.addItems(["Yes", "No"])
        req.setCurrentText("Yes" if f.get("required", True) else "No")
        t.setCellWidget(r, 2, req)

        dtype = QComboBox()
        dtype.addItems(DATA_TYPES)
        dtype.setCurrentText(f.get("data_type", "text"))
        t.setCellWidget(r, 3, dtype)

        valid = QComboBox()
        valid.addItems(VALIDATIONS)
        valid.setCurrentText(f.get("validation_type", "none"))
        t.setCellWidget(r, 4, valid)

        t.setItem(r, 5, QTableWidgetItem(f.get("sql_table", "")))
        t.setItem(r, 6, QTableWidgetItem(f.get("sql_value_col", "")))
        t.setItem(r, 7, QTableWidgetItem(", ".join(f.get("sql_match_cols", []))))
        t.setItem(r, 8, QTableWidgetItem(f.get("description", "")))

    def _remove_field_row(self) -> None:
        r = self.fields_table.currentRow()
        if r >= 0:
            self.fields_table.removeRow(r)

    def _collect_fields(self) -> list[dict[str, Any]]:
        t = self.fields_table
        out: list[dict[str, Any]] = []
        for r in range(t.rowCount()):
            key = (t.item(r, 0).text() if t.item(r, 0) else "").strip()
            if not key:
                continue
            match_cols = [
                c.strip()
                for c in (t.item(r, 7).text() if t.item(r, 7) else "").split(",")
                if c.strip()
            ]
            out.append(
                {
                    "field_key": key,
                    "display_name": (t.item(r, 1).text() if t.item(r, 1) else key).strip()
                    or key,
                    "required": t.cellWidget(r, 2).currentText() == "Yes",
                    "data_type": t.cellWidget(r, 3).currentText(),
                    "validation_type": t.cellWidget(r, 4).currentText(),
                    "sql_table": (t.item(r, 5).text() if t.item(r, 5) else "").strip(),
                    "sql_value_col": (t.item(r, 6).text() if t.item(r, 6) else "").strip(),
                    "sql_match_cols": match_cols,
                    "description": (t.item(r, 8).text() if t.item(r, 8) else "").strip(),
                }
            )
        return out

    # ---------------- actions ----------------
    def _new_task(self) -> None:
        name, ok = QInputDialog.getText(self, "New task", "Task name:")
        if not ok or not name.strip():
            return
        try:
            tid = self.store.create_task(name.strip())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Error", f"Could not create task: {exc}")
            return
        self.refresh_tasks()
        self._select_task_in_list(tid)

    def _seed_examples(self) -> None:
        existing = {t["name"] for t in self.store.list_tasks()}
        created = 0
        for tpl in _example_tasks():
            if tpl["name"] in existing:
                continue
            tid = self.store.create_task(tpl["name"], tpl["description"])
            self.store.set_task_fields(tid, tpl["fields"])
            created += 1
        self.refresh_tasks()
        QMessageBox.information(
            self, "Examples", f"Added {created} example task(s)."
        )

    def _delete_task(self) -> None:
        if self.current_task_id is None:
            return
        if (
            QMessageBox.question(
                self, "Delete task", "Delete this task and all its fields/templates?"
            )
            != QMessageBox.Yes
        ):
            return
        self.store.delete_task(self.current_task_id)
        self.current_task_id = None
        self.name_edit.clear()
        self.desc_edit.clear()
        self.fields_table.setRowCount(0)
        self.refresh_tasks()

    def _save_task(self) -> None:
        if self.current_task_id is None:
            QMessageBox.information(self, "No task", "Create or select a task first.")
            return
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing name", "Task name is required.")
            return
        try:
            self.store.update_task(
                self.current_task_id, name, self.desc_edit.toPlainText().strip()
            )
            self.store.set_task_fields(self.current_task_id, self._collect_fields())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Error", f"Save failed: {exc}")
            return
        self.refresh_tasks()
        self._select_task_in_list(self.current_task_id)
        QMessageBox.information(self, "Saved", "Task saved.")

    def _forget_learned(self) -> None:
        r = self.learned_table.currentRow()
        if r < 0:
            return
        match_id = self.learned_table.item(r, 0).data(Qt.UserRole)
        self.store.forget_match(int(match_id))
        if self.current_task_id is not None:
            self._load_learned(self.current_task_id)

    def _select_task_in_list(self, task_id: int) -> None:
        for r in range(self.task_list.rowCount()):
            if self.task_list.item(r, 0).data(Qt.UserRole) == task_id:
                self.task_list.selectRow(r)
                return
