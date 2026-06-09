"""Exports page — browse and preview all RPA hand-off files.

Layout:
  ┌─ Header: "Export History" + [Open exports folder] ────────────────┐
  │  📁 Documents\\Orders RPA Bridge\\Exports                          │
  └─────────────────────────────────────────────────────────────────────┘
  ┌─ File list (left 38%) ─────┐  ┌─ Field preview (right 62%) ──────┐
  │  ▶ Receiving_20260609...   │  │  Task: Receiving                  │
  │    Jun 09, 2026  2:32 PM   │  │  Source: MX-3051.pdf              │
  │    ✓ Ready                 │  │  Generated: Jun 09 2026 2:32 PM   │
  │                            │  │  Status: ✓ Ready to export        │
  │  [Refresh]                 │  │  ─────────────────────────────    │
  │                            │  │  Field | Value | Status           │
  │                            │  │  PO    | 80817 | ok               │
  │                            │  │  ...                              │
  │                            │  │  [Open file] [Show in Explorer]   │
  └────────────────────────────┘  └────────────────────────────────────┘
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core import paths
from app.ui.widgets import hline, label, page_header, status_pill


class ExportsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._export_files: list[Path] = []
        self._selected_path: Path | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(14)

        # ── Header ──────────────────────────────────────────────────
        hdr_row = QHBoxLayout()
        hdr_row.addWidget(
            page_header(
                "Export History",
                "All files exported for Power Automate — click any entry to preview its contents.",
            ),
            1,
        )
        open_folder_btn = QPushButton("📂  Open exports folder")
        open_folder_btn.setObjectName("primary")
        open_folder_btn.setFixedHeight(36)
        open_folder_btn.setToolTip(str(paths.EXPORTS_DIR))
        open_folder_btn.clicked.connect(self._open_folder)
        hdr_row.addWidget(open_folder_btn, 0, Qt.AlignTop)
        hdr_w = QWidget()
        hdr_w.setLayout(hdr_row)
        outer.addWidget(hdr_w)

        # Folder path label (so user always knows where files are)
        path_lbl = QLabel(f"📁  {paths.EXPORTS_DIR}")
        path_lbl.setObjectName("muted")
        path_lbl.setStyleSheet(
            "font-size:12px; background:#141e2b; padding:8px 12px; "
            "border-radius:8px; border:1px solid #2a3340;"
        )
        path_lbl.setWordWrap(True)
        outer.addWidget(path_lbl)

        # ── Main splitter ────────────────────────────────────────────
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.addWidget(self._make_list_panel())
        self._splitter.addWidget(self._make_preview_panel())
        self._splitter.setSizes([380, 760])
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        outer.addWidget(self._splitter, 1)

        self.refresh()

    # ── List panel ───────────────────────────────────────────────────
    def _make_list_panel(self) -> QWidget:
        w = QFrame()
        w.setObjectName("card")
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        hd = QHBoxLayout()
        hd.addWidget(QLabel("Exported files"))
        hd.addStretch(1)
        refresh_btn = QPushButton("↺")
        refresh_btn.setFixedSize(28, 28)
        refresh_btn.setToolTip("Refresh file list")
        refresh_btn.clicked.connect(self.refresh)
        hd.addWidget(refresh_btn)
        v.addLayout(hd)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.currentItemChanged.connect(self._on_item_changed)
        v.addWidget(self._list, 1)

        self._count_lbl = QLabel("")
        self._count_lbl.setObjectName("muted")
        self._count_lbl.setStyleSheet("font-size:11px;")
        v.addWidget(self._count_lbl)

        return w

    # ── Preview panel ─────────────────────────────────────────────────
    def _make_preview_panel(self) -> QWidget:
        self._preview_panel = QFrame()
        self._preview_panel.setObjectName("card")
        v = QVBoxLayout(self._preview_panel)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        # Empty state
        self._preview_empty = QLabel(
            "Select an export file on the left to preview its contents here."
        )
        self._preview_empty.setObjectName("muted")
        self._preview_empty.setAlignment(Qt.AlignCenter)
        v.addWidget(self._preview_empty)

        # Content (shown when a file is selected)
        self._preview_content = QWidget()
        pc = QVBoxLayout(self._preview_content)
        pc.setContentsMargins(0, 0, 0, 0)
        pc.setSpacing(10)

        # Meta info row
        self._meta_task = QLabel("")
        self._meta_task.setObjectName("cardTitle")
        self._meta_src = QLabel("")
        self._meta_src.setObjectName("muted")
        self._meta_src.setWordWrap(True)
        self._meta_gen = QLabel("")
        self._meta_gen.setObjectName("muted")
        self._meta_ready = QLabel("")
        self._meta_ready.setWordWrap(True)

        pc.addWidget(self._meta_task)
        pc.addWidget(self._meta_src)
        pc.addWidget(self._meta_gen)
        pc.addWidget(self._meta_ready)
        pc.addWidget(hline())

        # Fields table
        self._field_table = QTableWidget(0, 3)
        self._field_table.setHorizontalHeaderLabels(["Field", "Resolved value", "Status"])
        self._field_table.verticalHeader().setVisible(False)
        self._field_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._field_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._field_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._field_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self._field_table.horizontalHeader().resizeSection(2, 90)
        self._field_table.setWordWrap(True)
        pc.addWidget(self._field_table, 1)

        pc.addWidget(hline())

        # Action buttons
        self._open_file_btn = QPushButton("📄  Open file")
        self._open_file_btn.setToolTip("Open the JSON file in Notepad / default app")
        self._open_file_btn.clicked.connect(self._open_file)
        self._reveal_btn = QPushButton("📂  Show in Explorer")
        self._reveal_btn.setToolTip("Open Explorer and highlight this file")
        self._reveal_btn.clicked.connect(self._reveal_in_explorer)
        self._copy_path_btn = QPushButton("📋  Copy path")
        self._copy_path_btn.setToolTip("Copy the full file path to clipboard")
        self._copy_path_btn.clicked.connect(self._copy_path)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addWidget(self._open_file_btn)
        btn_row.addWidget(self._reveal_btn)
        btn_row.addWidget(self._copy_path_btn)
        btn_row.addStretch(1)
        pc.addLayout(btn_row)

        self._preview_content.hide()
        v.addWidget(self._preview_content, 1)

        return self._preview_panel

    # ── Data ──────────────────────────────────────────────────────────
    def refresh(self) -> None:
        """Re-scan the exports directory and rebuild the file list."""
        paths.ensure_dirs()
        self._list.clear()
        self._export_files = []

        json_files = sorted(
            paths.EXPORTS_DIR.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        if not json_files:
            item = QListWidgetItem("No exports yet.\nProcess a document and click Export for RPA.")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            item.setForeground(Qt.gray)
            self._list.addItem(item)
            self._count_lbl.setText("")
            return

        for f in json_files:
            try:
                payload = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                payload = {}

            task = payload.get("task", "Unknown task")
            ready = payload.get("ready_to_export", False)
            gen_at = payload.get("generated_at", "")

            # Format timestamp
            try:
                dt = datetime.fromisoformat(gen_at.replace("Z", "+00:00"))
                date_str = dt.strftime("%b %d, %Y  %I:%M %p")
            except Exception:  # noqa: BLE001
                date_str = gen_at[:16] if gen_at else "Unknown date"

            status_icon = "✓" if ready else "⚠"
            display = f"{status_icon}  {f.stem}\n   {task}  ·  {date_str}"

            list_item = QListWidgetItem(display)
            list_item.setData(Qt.UserRole, str(f))
            if not ready:
                list_item.setForeground(Qt.yellow)
            self._list.addItem(list_item)
            self._export_files.append(f)

        self._count_lbl.setText(f"{len(json_files)} export{'s' if len(json_files) != 1 else ''}")

        # Re-select the previously selected file if it still exists
        if self._selected_path and self._selected_path.exists():
            for i in range(self._list.count()):
                item = self._list.item(i)
                if item and item.data(Qt.UserRole) == str(self._selected_path):
                    self._list.setCurrentRow(i)
                    break
        elif self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _on_item_changed(self, current: QListWidgetItem, _prev) -> None:
        if current is None:
            self._preview_empty.show()
            self._preview_content.hide()
            return
        path_str = current.data(Qt.UserRole)
        if not path_str:
            return
        self._selected_path = Path(path_str)
        self._load_preview(self._selected_path)

    def _load_preview(self, path: Path) -> None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            self._meta_task.setText(f"Error reading file: {e}")
            self._preview_empty.hide()
            self._preview_content.show()
            return

        task = payload.get("task", "Unknown task")
        source = payload.get("source_file", "Unknown")
        gen_at = payload.get("generated_at", "")
        ready = payload.get("ready_to_export", False)
        fields = payload.get("fields", {})

        try:
            dt = datetime.fromisoformat(gen_at.replace("Z", "+00:00"))
            date_str = dt.strftime("%B %d, %Y  %I:%M %p UTC")
        except Exception:  # noqa: BLE001
            date_str = gen_at

        self._meta_task.setText(f"Task:  {task}")
        self._meta_src.setText(f"Source document:  {source}")
        self._meta_gen.setText(f"Generated:  {date_str}")

        if ready:
            self._meta_ready.setText("✓  Ready to export — all required fields are resolved.")
            self._meta_ready.setStyleSheet("color:#3fb950; font-weight:600; font-size:13px;")
        else:
            blocking = payload.get("blocking_fields", [])
            names = ", ".join(blocking) if blocking else "some fields"
            self._meta_ready.setText(f"⚠  Not fully resolved — {names} needed values.")
            self._meta_ready.setStyleSheet("color:#d29922; font-weight:600; font-size:13px;")

        # Populate fields table
        self._field_table.setRowCount(0)
        for key, fdata in fields.items():
            r = self._field_table.rowCount()
            self._field_table.insertRow(r)

            display_name = fdata.get("display_name", key)
            req = "  ★" if fdata.get("required") else ""
            name_item = QTableWidgetItem(f"{display_name}{req}")
            name_item.setToolTip(
                f"Field key: {key}\n"
                f"Raw extracted: {fdata.get('raw_value', '')}\n"
                f"Validation: {fdata.get('validation_type', 'none')}\n"
                f"Confidence: {fdata.get('confidence', 0):.0f}%"
            )
            self._field_table.setItem(r, 0, name_item)

            resolved = fdata.get("resolved_value", "") or fdata.get("raw_value", "")
            val_item = QTableWidgetItem(str(resolved))
            val_item.setToolTip(str(resolved))
            self._field_table.setItem(r, 1, val_item)

            status = fdata.get("status", "unknown")
            pill_holder = QWidget()
            pill_h = QHBoxLayout(pill_holder)
            pill_h.setContentsMargins(4, 2, 4, 2)
            pill_h.addWidget(status_pill(status))
            self._field_table.setCellWidget(r, 2, pill_holder)
            self._field_table.setRowHeight(r, 36)

        self._field_table.resizeRowsToContents()
        self._preview_empty.hide()
        self._preview_content.show()

    # ── Actions ───────────────────────────────────────────────────────
    def _open_folder(self) -> None:
        paths.ensure_dirs()
        subprocess.Popen(["explorer.exe", str(paths.EXPORTS_DIR)])

    def _open_file(self) -> None:
        if self._selected_path and self._selected_path.exists():
            os.startfile(str(self._selected_path))

    def _reveal_in_explorer(self) -> None:
        if self._selected_path and self._selected_path.exists():
            subprocess.Popen(["explorer.exe", "/select,", str(self._selected_path)])

    def _copy_path(self) -> None:
        if self._selected_path:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(str(self._selected_path))
            self._copy_path_btn.setText("✓  Copied!")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(2000, lambda: self._copy_path_btn.setText("📋  Copy path"))
