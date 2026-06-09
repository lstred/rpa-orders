"""Tasks page: define RPA tasks, their required fields, and warehouse validation rules.

Layout:
  Left panel  – list of tasks
  Right panel – task name/description at top; horizontal splitter below:
      Left  – ordered field list (add/remove/reorder)
      Right – field editor form (SQL table/column dropdowns, match-column checkboxes)
  Tabs: Fields | Learned Matches
"""
from __future__ import annotations

import re
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core import schema_cache
from app.core.local_store import LocalStore
from app.ui.widgets import card, hline, label, page_header, row

DATA_TYPES = ["text", "number", "date", "money"]
VALIDATION_TYPES = ["none", "exact", "fuzzy"]
VALIDATION_LABELS = {
    "none": "None — accept whatever is extracted",
    "exact": "Exact match — must equal a real warehouse key",
    "fuzzy": "Fuzzy match — free text matched by similarity score",
}

NO_TABLE = "— select table —"
NO_COL = "— select column —"

EXAMPLE_TASKS = [
    {
        "name": "Customer Orders",
        "description": "Inbound purchase orders to be keyed into the ERP.",
        "fields": [
            {
                "field_key": "customer_number",
                "display_name": "Customer Number",
                "required": True,
                "data_type": "text",
                "validation_type": "exact",
                "sql_table": "BILLTO",
                "sql_value_col": "BACCT#",
                "sql_match_cols": ["BACCT#", "BBANK2"],
                "description": "Resolves both the old (BBANK2) and new (BACCT#) account numbers. Flags closed accounts.",
            },
            {
                "field_key": "customer_po",
                "display_name": "Customer PO #",
                "required": True,
                "data_type": "text",
                "validation_type": "none",
                "sql_table": "",
                "sql_value_col": "",
                "sql_match_cols": [],
                "description": "The customer's own purchase order number.",
            },
            {
                "field_key": "sku",
                "display_name": "Item / SKU",
                "required": True,
                "data_type": "text",
                "validation_type": "fuzzy",
                "sql_table": "ITEM",
                "sql_value_col": "ItemNumber",
                "sql_match_cols": ["ItemNumber", "INAME"],
                "description": "Their item description fuzzy-matched to our ItemNumber (INAME is the description haystack).",
            },
            {
                "field_key": "quantity",
                "display_name": "Quantity",
                "required": True,
                "data_type": "number",
                "validation_type": "none",
                "sql_table": "",
                "sql_value_col": "",
                "sql_match_cols": [],
                "description": "Quantity ordered in their unit of measure.",
            },
            {
                "field_key": "ship_date",
                "display_name": "Requested Ship Date",
                "required": False,
                "data_type": "date",
                "validation_type": "none",
                "sql_table": "",
                "sql_value_col": "",
                "sql_match_cols": [],
                "description": "Requested ship date if stated on the document.",
            },
        ],
    },
    {
        "name": "Receiving",
        "description": "Inbound receiving slips / packing slips against open purchase orders.",
        "fields": [
            {
                "field_key": "po_number",
                "display_name": "PO Number",
                "required": True,
                "data_type": "text",
                "validation_type": "none",
                "sql_table": "",
                "sql_value_col": "",
                "sql_match_cols": [],
                "description": "Our purchase order number as printed on the packing slip.",
            },
            {
                "field_key": "sku",
                "display_name": "Item / SKU",
                "required": True,
                "data_type": "text",
                "validation_type": "fuzzy",
                "sql_table": "ITEM",
                "sql_value_col": "ItemNumber",
                "sql_match_cols": ["ItemNumber", "INAME"],
                "description": "Received item description matched to our ItemNumber.",
            },
            {
                "field_key": "qty_received",
                "display_name": "Qty Received",
                "required": True,
                "data_type": "number",
                "validation_type": "none",
                "sql_table": "",
                "sql_value_col": "",
                "sql_match_cols": [],
                "description": "Quantity physically received.",
            },
            {
                "field_key": "roll_number",
                "display_name": "Roll / Lot Number",
                "required": False,
                "data_type": "text",
                "validation_type": "none",
                "sql_table": "",
                "sql_value_col": "",
                "sql_match_cols": [],
                "description": "Roll or lot number if present.",
            },
            {
                "field_key": "shade",
                "display_name": "Shade / Color",
                "required": False,
                "data_type": "text",
                "validation_type": "none",
                "sql_table": "",
                "sql_value_col": "",
                "sql_match_cols": [],
                "description": "Shade or color designation if present.",
            },
            {
                "field_key": "received_date",
                "display_name": "Received Date",
                "required": False,
                "data_type": "date",
                "validation_type": "none",
                "sql_table": "",
                "sql_value_col": "",
                "sql_match_cols": [],
                "description": "Date goods were received.",
            },
        ],
    },
]


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# ======================================================================== #
# Field editor panel
# ======================================================================== #

class FieldEditorPanel(QWidget):
    """Right-side form for editing one field definition."""

    field_saved = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self._current_index: int | None = None
        self._building = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._empty = self._make_empty()
        self._form_scroll = QScrollArea()
        self._form_scroll.setWidgetResizable(True)
        self._form_scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        self._form_v = QVBoxLayout(content)
        self._form_v.setContentsMargins(14, 10, 14, 14)
        self._form_v.setSpacing(12)
        self._form_scroll.setWidget(content)

        self._build_form()
        outer.addWidget(self._empty)
        outer.addWidget(self._form_scroll)
        self._form_scroll.hide()

    def _make_empty(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        ico = QLabel("📋")
        ico.setAlignment(Qt.AlignCenter)
        ico.setStyleSheet("font-size:38px; margin-bottom:8px;")
        txt = QLabel(
            "Select a field from the list on the left,\nor click  + Add field  to create one."
        )
        txt.setObjectName("muted")
        txt.setAlignment(Qt.AlignCenter)
        txt.setWordWrap(True)
        v.addWidget(ico)
        v.addWidget(txt)
        return w

    def _build_form(self) -> None:
        v = self._form_v

        # ── Display & extraction ───────────────────────────────────────────
        self._disp_name = QLineEdit()
        self._disp_name.setPlaceholderText("e.g. Customer Number")
        self._disp_name.textChanged.connect(self._on_display_name_change)

        self._field_key = QLineEdit()
        self._field_key.setPlaceholderText("auto-generated from display name")
        self._field_key.setStyleSheet("color:#8b949e;")

        self._required = QCheckBox("Required — blocks export until resolved")

        self._dtype = QComboBox()
        self._dtype.addItems(DATA_TYPES)

        self._guidance = QTextEdit()
        self._guidance.setPlaceholderText(
            "Describe where to find this value in the document, "
            "any quirks, abbreviations, or aliases. "
            "This is shown to the user during review and passed to AI."
        )
        self._guidance.setMinimumHeight(72)
        self._guidance.setMaximumHeight(110)
        self._guidance.setAcceptRichText(False)

        f1 = QFormLayout()
        f1.setLabelAlignment(Qt.AlignRight)
        f1.setSpacing(8)
        f1.addRow("Display name:", self._disp_name)
        f1.addRow("Field key:", self._field_key)
        f1.addRow("", self._required)
        f1.addRow("Data type:", self._dtype)
        f1.addRow("Guidance:", self._guidance)
        fw1 = QWidget()
        fw1.setLayout(f1)

        v.addWidget(self._section("EXTRACTION & DISPLAY"))
        v.addWidget(fw1)
        v.addWidget(hline())

        # ── Warehouse validation ──────────────────────────────────────────
        v.addWidget(self._section("WAREHOUSE VALIDATION"))

        self._vtype = QComboBox()
        for vt in VALIDATION_TYPES:
            self._vtype.addItem(VALIDATION_LABELS[vt], vt)
        self._vtype.currentIndexChanged.connect(self._on_vtype_change)
        v.addWidget(self._vtype)

        # SQL sub-panel
        self._sql_group = QGroupBox("NRF_REPORTS SQL Lookup Configuration")
        sql_v = QVBoxLayout(self._sql_group)
        sql_v.setSpacing(10)

        f2 = QFormLayout()
        f2.setLabelAlignment(Qt.AlignRight)
        f2.setSpacing(8)

        self._sql_table = QComboBox()
        self._sql_table.addItem(NO_TABLE, "")
        for t in schema_cache.get_tables():
            self._sql_table.addItem(t, t)
        self._sql_table.currentIndexChanged.connect(self._on_table_change)
        f2.addRow("SQL Table:", self._sql_table)

        self._val_col = QComboBox()
        self._val_col.addItem(NO_COL, "")
        f2.addRow("Value column\n(returned to RPA):", self._val_col)

        fw2 = QWidget()
        fw2.setLayout(f2)
        sql_v.addWidget(fw2)

        match_hdr = QLabel(
            "Match columns — the columns searched for the user's value "
            "(check all relevant columns):"
        )
        match_hdr.setWordWrap(True)
        match_hdr.setObjectName("muted")
        sql_v.addWidget(match_hdr)

        self._match_area = QWidget()
        self._match_layout = QGridLayout(self._match_area)
        self._match_layout.setContentsMargins(0, 0, 0, 0)
        self._match_layout.setSpacing(4)
        sql_v.addWidget(self._match_area)

        self._billto_hint = QLabel(
            "💡 For BILLTO customer numbers: check both BACCT# (new system key) "
            "and BBANK2 (the old number reps actually type). "
            "The app resolves both automatically and flags closed accounts."
        )
        self._billto_hint.setWordWrap(True)
        self._billto_hint.setStyleSheet(
            "background:#10261a; border-left:3px solid #3fb950; "
            "padding:8px 12px; border-radius:4px; color:#c9d1d9; margin-top:4px;"
        )
        self._billto_hint.hide()
        sql_v.addWidget(self._billto_hint)

        refresh_btn = QPushButton("↺  Refresh columns from warehouse")
        refresh_btn.setStyleSheet("font-size:11px; padding:3px 10px;")
        refresh_btn.clicked.connect(self._refresh_schema)
        sql_v.addWidget(refresh_btn)

        v.addWidget(self._sql_group)
        self._sql_group.hide()

        v.addStretch(1)

        # ── Action buttons ──────────────────────────────────────────────
        save_btn = QPushButton("Save field changes")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._save)
        del_btn = QPushButton("Delete this field")
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(self._delete)
        btn_w = row(save_btn, del_btn)
        btn_w.setContentsMargins(14, 0, 14, 8)
        self._form_scroll.widget().layout().addWidget(btn_w)

    @staticmethod
    def _section(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("muted")
        lbl.setStyleSheet("font-weight:600; font-size:11px; letter-spacing:0.5px;")
        return lbl

    # ── Public API ─────────────────────────────────────────────────────
    def load(self, field: dict, index: int) -> None:
        self._building = True
        self._current_index = index
        self._empty.hide()
        self._form_scroll.show()

        self._disp_name.setText(field.get("display_name", ""))
        self._field_key.setText(field.get("field_key", ""))
        self._required.setChecked(bool(field.get("required", True)))
        self._dtype.setCurrentText(field.get("data_type", "text"))
        self._guidance.setPlainText(field.get("description", ""))

        vt = field.get("validation_type", "none")
        idx = self._vtype.findData(vt)
        self._vtype.setCurrentIndex(idx if idx >= 0 else 0)
        self._sql_group.setVisible(vt != "none")

        tbl = field.get("sql_table", "")
        ti = self._sql_table.findData(tbl)
        self._sql_table.setCurrentIndex(ti if ti >= 0 else 0)
        self._populate_columns(
            tbl,
            field.get("sql_value_col", ""),
            field.get("sql_match_cols", []),
        )
        self._billto_hint.setVisible(tbl == "BILLTO")
        self._building = False

    def clear(self) -> None:
        self._current_index = None
        self._empty.show()
        self._form_scroll.hide()

    def get_field(self) -> dict | None:
        name = self._disp_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing name", "Display name is required.")
            return None
        key = self._field_key.text().strip() or _slugify(name)
        vt = self._vtype.currentData() or "none"
        return {
            "field_key": key,
            "display_name": name,
            "required": self._required.isChecked(),
            "data_type": self._dtype.currentText(),
            "validation_type": vt,
            "sql_table": (self._sql_table.currentData() or "") if vt != "none" else "",
            "sql_value_col": (self._val_col.currentData() or "") if vt != "none" else "",
            "sql_match_cols": self._get_checked_cols() if vt != "none" else [],
            "description": self._guidance.toPlainText().strip(),
        }

    # ── Internals ─────────────────────────────────────────────────────
    def _on_display_name_change(self, text: str) -> None:
        if not self._building:
            self._field_key.setText(_slugify(text))

    def _on_vtype_change(self) -> None:
        vt = self._vtype.currentData()
        self._sql_group.setVisible(vt != "none")

    def _on_table_change(self) -> None:
        if self._building:
            return
        tbl = self._sql_table.currentData() or ""
        self._populate_columns(tbl, "", [])
        self._billto_hint.setVisible(tbl == "BILLTO")

    def _populate_columns(self, table: str, value_col: str, match_cols: list[str]) -> None:
        cols = schema_cache.get_columns(table) if table else []

        # Value column
        self._val_col.blockSignals(True)
        self._val_col.clear()
        self._val_col.addItem(NO_COL, "")
        for c in cols:
            self._val_col.addItem(c, c)
        vi = self._val_col.findData(value_col)
        self._val_col.setCurrentIndex(vi if vi >= 0 else 0)
        self._val_col.blockSignals(False)

        # Match column checkboxes in 2-column grid
        for i in reversed(range(self._match_layout.count())):
            item = self._match_layout.itemAt(i)
            if item and item.widget():
                item.widget().setParent(None)

        if not cols:
            placeholder = QLabel("Select a SQL table above to see its columns.")
            placeholder.setObjectName("muted")
            self._match_layout.addWidget(placeholder, 0, 0)
            return

        for i, col in enumerate(cols):
            cb = QCheckBox(col)
            cb.setChecked(col in match_cols)
            self._match_layout.addWidget(cb, i // 2, i % 2)

    def _get_checked_cols(self) -> list[str]:
        cols: list[str] = []
        for i in range(self._match_layout.count()):
            item = self._match_layout.itemAt(i)
            if item and isinstance(item.widget(), QCheckBox):
                cb = item.widget()
                if cb.isChecked():
                    cols.append(cb.text())
        return cols

    def _refresh_schema(self) -> None:
        ok, msg = schema_cache.refresh_from_db()
        QMessageBox.information(self, "Schema refresh", msg)
        if ok:
            tbl = self._sql_table.currentData() or ""
            self._sql_table.clear()
            self._sql_table.addItem(NO_TABLE, "")
            for t in schema_cache.get_tables():
                self._sql_table.addItem(t, t)
            ti = self._sql_table.findData(tbl)
            if ti >= 0:
                self._sql_table.setCurrentIndex(ti)

    def _save(self) -> None:
        f = self.get_field()
        if f is not None and self._current_index is not None:
            f["_index"] = self._current_index
            self.field_saved.emit(f)

    def _delete(self) -> None:
        if self._current_index is not None:
            self.field_saved.emit({"_index": self._current_index, "_delete": True})


# ======================================================================== #
# TasksPage
# ======================================================================== #

class TasksPage(QWidget):
    def __init__(self, on_tasks_changed=None) -> None:
        super().__init__()
        self.store = LocalStore.instance()
        self.on_tasks_changed = on_tasks_changed
        self.current_task_id: int | None = None
        self._fields: list[dict] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)
        outer.addWidget(
            page_header(
                "Tasks & Fields",
                "Define each RPA workflow, its required fields, and how to validate them against the warehouse.",
            )
        )

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._left_panel())
        splitter.addWidget(self._right_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 920])
        outer.addWidget(splitter, 1)

        self.refresh_tasks()

    # ── Left: task list ───────────────────────────────────────────────
    def _left_panel(self) -> QWidget:
        self.task_list = QListWidget()
        self.task_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.task_list.itemSelectionChanged.connect(self._on_select_task)

        new_btn = QPushButton("New task")
        new_btn.setObjectName("primary")
        new_btn.clicked.connect(self._new_task)
        ex_btn = QPushButton("Add examples")
        ex_btn.clicked.connect(self._seed_examples)
        del_btn = QPushButton("Delete task")
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(self._delete_task)

        return card(
            label("Tasks", "cardTitle"),
            label(
                "Each task is one RPA workflow.\nExamples: Customer Orders, Receiving.",
                "muted",
            ),
            self.task_list,
            row(new_btn, ex_btn),
            del_btn,
            spacing=10,
        )

    # ── Right: tabs ───────────────────────────────────────────────────
    def _right_panel(self) -> QWidget:
        self.tabs = QTabWidget()
        self.tabs.addTab(self._fields_tab(), "  Fields  ")
        self.tabs.addTab(self._learned_tab(), "  Learned Matches  ")
        return self.tabs

    def _fields_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(12)

        # Task metadata header
        self.task_name_edit = QLineEdit()
        self.task_name_edit.setPlaceholderText("Task name (e.g. Customer Orders)")
        self.task_name_edit.setStyleSheet("font-size:15px; font-weight:600; padding:8px;")

        self.task_desc_edit = QTextEdit()
        self.task_desc_edit.setPlaceholderText(
            "Describe this task: what document types does it handle? "
            "What data does the robot need? What ERP action does it perform?"
        )
        self.task_desc_edit.setMinimumHeight(64)
        self.task_desc_edit.setMaximumHeight(88)
        self.task_desc_edit.setAcceptRichText(False)

        meta_form = QFormLayout()
        meta_form.setLabelAlignment(Qt.AlignRight)
        meta_form.setSpacing(8)
        meta_form.addRow("Task name:", self.task_name_edit)
        meta_form.addRow("Description:", self.task_desc_edit)
        meta_w = QWidget()
        meta_w.setLayout(meta_form)
        v.addWidget(label("TASK DETAILS", "muted"))
        v.addWidget(meta_w)
        v.addWidget(hline())

        # Field list + editor
        v.addWidget(label("FIELDS", "muted"))
        v.addWidget(
            label(
                "Each field is one piece of data to extract (e.g. Customer Number, SKU, Quantity). "
                "Drag to reorder. Select a field to configure it on the right.",
                "muted",
            )
        )

        hsplit = QSplitter(Qt.Horizontal)

        # Field list (left of hsplit)
        fl_w = QWidget()
        fl = QVBoxLayout(fl_w)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(6)

        self.field_list = QListWidget()
        self.field_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.field_list.setDefaultDropAction(Qt.MoveAction)
        self.field_list.itemSelectionChanged.connect(self._on_select_field)
        fl.addWidget(self.field_list)

        add_btn = QPushButton("+ Add field")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self._add_field)
        fl.addWidget(add_btn)

        hsplit.addWidget(fl_w)

        # Field editor (right of hsplit)
        self.field_editor = FieldEditorPanel()
        self.field_editor.field_saved.connect(self._on_field_saved)
        hsplit.addWidget(self.field_editor)

        hsplit.setSizes([230, 650])
        hsplit.setStretchFactor(0, 0)
        hsplit.setStretchFactor(1, 1)
        v.addWidget(hsplit, 1)

        v.addWidget(hline())

        save_btn = QPushButton("Save task")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._save_task)
        save_btn.setFixedHeight(38)
        v.addWidget(save_btn)

        return w

    def _learned_tab(self) -> QWidget:
        self.learned_table = QTableWidget(0, 5)
        self.learned_table.setHorizontalHeaderLabels(
            ["Field", "Their value (from doc)", "Resolves to", "Label", "Conf."]
        )
        hdr = self.learned_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.learned_table.verticalHeader().setVisible(False)
        self.learned_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.learned_table.setWordWrap(True)
        self.learned_table.setTextElideMode(Qt.ElideNone)

        forget = QPushButton("Forget selected match")
        forget.setObjectName("danger")
        forget.clicked.connect(self._forget_learned)

        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(12)
        v.addWidget(label("Learned Nomenclature", "cardTitle"))
        v.addWidget(
            label(
                "When you confirm a fuzzy match — e.g. their item description → our SKU — "
                "the app stores it here. Next time that exact text appears it resolves instantly "
                "without asking. Forgetting an entry makes the app ask again next time.",
                "muted",
            )
        )
        v.addWidget(self.learned_table, 1)
        v.addWidget(row(forget))
        return w

    # ── Data ─────────────────────────────────────────────────────────
    def refresh_tasks(self) -> None:
        self.task_list.clear()
        for t in self.store.list_tasks():
            item = QListWidgetItem(t["name"])
            item.setData(Qt.UserRole, t["id"])
            self.task_list.addItem(item)
        if self.on_tasks_changed:
            self.on_tasks_changed()

    def _on_select_task(self) -> None:
        items = self.task_list.selectedItems()
        if items:
            self._load_task(items[0].data(Qt.UserRole))

    def _load_task(self, task_id: int) -> None:
        self.current_task_id = task_id
        task = self.store.get_task(task_id)
        if not task:
            return
        self.task_name_edit.setText(task["name"])
        self.task_desc_edit.setPlainText(task["description"])
        self._fields = self.store.get_task_fields(task_id)
        self._rebuild_field_list()
        self.field_editor.clear()
        self._load_learned(task_id)

    def _rebuild_field_list(self) -> None:
        self.field_list.clear()
        for f in self._fields:
            req = "★ " if f.get("required") else "○ "
            vt = f.get("validation_type", "none")
            badge = {"exact": " [exact]", "fuzzy": " [fuzzy]"}.get(vt, "")
            item = QListWidgetItem(f"{req}{f.get('display_name', f.get('field_key', '?'))}{badge}")
            item.setToolTip(f.get("description", "No guidance set."))
            self.field_list.addItem(item)

    def _on_select_field(self) -> None:
        idx = self.field_list.currentRow()
        if 0 <= idx < len(self._fields):
            self.field_editor.load(self._fields[idx], idx)

    def _on_field_saved(self, f: dict) -> None:
        idx = f.get("_index")
        if idx is None:
            return
        if f.get("_delete"):
            if 0 <= idx < len(self._fields):
                self._fields.pop(idx)
        else:
            clean = {k: v for k, v in f.items() if not k.startswith("_")}
            if 0 <= idx < len(self._fields):
                self._fields[idx] = clean
        self._rebuild_field_list()
        self.field_editor.clear()

    def _load_learned(self, task_id: int) -> None:
        self.learned_table.setRowCount(0)
        for m in self.store.list_learned(task_id):
            r = self.learned_table.rowCount()
            self.learned_table.insertRow(r)
            key_item = QTableWidgetItem(m["field_key"])
            key_item.setData(Qt.UserRole, m["id"])
            self.learned_table.setItem(r, 0, key_item)
            self.learned_table.setItem(r, 1, QTableWidgetItem(m["source_value"]))
            self.learned_table.setItem(r, 2, QTableWidgetItem(m["resolved_value"]))
            self.learned_table.setItem(r, 3, QTableWidgetItem(m.get("resolved_label", "")))
            self.learned_table.setItem(
                r, 4, QTableWidgetItem(f"{float(m.get('confidence', 100)):.0f}")
            )
        self.learned_table.resizeRowsToContents()

    # ── Actions ──────────────────────────────────────────────────────
    def _add_field(self) -> None:
        name, ok = QInputDialog.getText(self, "Add field", "Display name for this field:")
        if not ok or not name.strip():
            return
        new_f = {
            "field_key": _slugify(name.strip()),
            "display_name": name.strip(),
            "required": True,
            "data_type": "text",
            "validation_type": "none",
            "sql_table": "",
            "sql_value_col": "",
            "sql_match_cols": [],
            "description": "",
        }
        self._fields.append(new_f)
        self._rebuild_field_list()
        self.field_list.setCurrentRow(len(self._fields) - 1)
        self.field_editor.load(new_f, len(self._fields) - 1)

    def _new_task(self) -> None:
        name, ok = QInputDialog.getText(self, "New task", "Task name:")
        if not ok or not name.strip():
            return
        try:
            tid = self.store.create_task(name.strip())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Error", str(exc))
            return
        self.refresh_tasks()
        self._select_task_by_id(tid)

    def _seed_examples(self) -> None:
        existing = {t["name"] for t in self.store.list_tasks()}
        created, last_id = 0, None
        for tpl in EXAMPLE_TASKS:
            if tpl["name"] not in existing:
                tid = self.store.create_task(tpl["name"], tpl["description"])
                self.store.set_task_fields(tid, tpl["fields"])
                last_id = tid
                created += 1
        self.refresh_tasks()
        if last_id:
            self._select_task_by_id(last_id)
        QMessageBox.information(self, "Examples added", f"Added {created} example task(s).")

    def _delete_task(self) -> None:
        if self.current_task_id is None:
            QMessageBox.information(self, "No selection", "Select a task first.")
            return
        if (
            QMessageBox.question(
                self,
                "Delete task",
                "Delete this task and ALL its fields, templates, and learned matches?\n\nThis cannot be undone.",
            )
            != QMessageBox.Yes
        ):
            return
        self.store.delete_task(self.current_task_id)
        self.current_task_id = None
        self._fields = []
        self.task_name_edit.clear()
        self.task_desc_edit.clear()
        self.field_list.clear()
        self.field_editor.clear()
        self.refresh_tasks()

    def _save_task(self) -> None:
        if self.current_task_id is None:
            QMessageBox.information(self, "No task selected", "Create or select a task first.")
            return
        name = self.task_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing name", "Task name is required.")
            return
        try:
            self.store.update_task(
                self.current_task_id, name, self.task_desc_edit.toPlainText().strip()
            )
            self.store.set_task_fields(self.current_task_id, self._fields)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Save failed", str(exc))
            return
        self.refresh_tasks()
        self._select_task_by_id(self.current_task_id)
        QMessageBox.information(
            self, "Saved", f"Task '{name}' saved with {len(self._fields)} field(s)."
        )

    def _forget_learned(self) -> None:
        r = self.learned_table.currentRow()
        if r < 0:
            return
        match_id = self.learned_table.item(r, 0).data(Qt.UserRole)
        self.store.forget_match(int(match_id))
        if self.current_task_id is not None:
            self._load_learned(self.current_task_id)

    def _select_task_by_id(self, task_id: int) -> None:
        for i in range(self.task_list.count()):
            if self.task_list.item(i).data(Qt.UserRole) == task_id:
                self.task_list.setCurrentRow(i)
                return
