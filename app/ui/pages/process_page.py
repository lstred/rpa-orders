"""Process page: end-to-end document pipeline.

Layout:
  ① Controls bar  — task selector + file picker + Process button
  ② Pipeline steps — visual progress: Load → Extract → Validate → Review → Export
  ③ Two-panel splitter (shown after processing):
      Left  — DocumentViewer: searchable extracted text
      Right — Field results table + action buttons + summary
  ④ Empty / no-fields state — clear guidance when task is not configured
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.local_store import LocalStore
from app.export import exporter
from app.extraction.field_extractor import extract_fields
from app.extraction.template_matcher import best_template
from app.ingestion.document_loader import load_document
from app.ui.widgets import card, hline, label, page_header, row, status_pill
from app.validation import validator
from app.validation.validator import STATUS_OK, STATUS_REVIEW, STATUS_UNMATCHED

# ──────────────────────────────────────────────────────────────────────────
# Pipeline steps bar
# ──────────────────────────────────────────────────────────────────────────

_STEP_NAMES = ["① Load", "② Extract", "③ Validate", "④ Review", "⑤ Export"]
_STEP_COLORS = {
    "pending": ("#2a3340", "#8b949e"),   # bg, fg
    "active":  ("#1f4fa3", "#ffffff"),
    "done":    ("#1a3a24", "#3fb950"),
    "warning": ("#3a2e10", "#d29922"),
    "error":   ("#3a1010", "#f85149"),
}


class PipelineStepsBar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(44)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self._btns: list[QLabel] = []
        for i, name in enumerate(_STEP_NAMES):
            lbl = QLabel(name)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedHeight(34)
            lbl.setMinimumWidth(110)
            self._btns.append(lbl)
            h.addWidget(lbl, 1)
            if i < len(_STEP_NAMES) - 1:
                arr = QLabel(" ›")
                arr.setStyleSheet("color:#2a3340; font-size:20px; font-weight:900;")
                arr.setFixedWidth(14)
                h.addWidget(arr)
        self.reset()

    def _apply(self, idx: int, state: str) -> None:
        bg, fg = _STEP_COLORS.get(state, _STEP_COLORS["pending"])
        self._btns[idx].setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:8px; "
            f"padding:4px 8px; font-size:12px; "
            f"font-weight:{'700' if state in ('active','done') else '400'};"
        )

    def reset(self) -> None:
        for i in range(len(_STEP_NAMES)):
            self._apply(i, "pending")

    def set_active(self, idx: int) -> None:
        for i in range(idx):
            self._apply(i, "done")
        self._apply(idx, "active")
        for i in range(idx + 1, len(_STEP_NAMES)):
            self._apply(i, "pending")

    def set_done(self, idx: int) -> None:
        self._apply(idx, "done")

    def set_error(self, idx: int) -> None:
        self._apply(idx, "error")


# ──────────────────────────────────────────────────────────────────────────
# Document viewer (left panel)
# ──────────────────────────────────────────────────────────────────────────

class DocumentViewer(QWidget):
    def __init__(self) -> None:
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        hdr = QHBoxLayout()
        title = QLabel("Document Text")
        title.setObjectName("cardTitle")
        self._char_lbl = QLabel("")
        self._char_lbl.setObjectName("muted")
        self._char_lbl.setStyleSheet("font-size:11px;")
        hdr.addWidget(title)
        hdr.addStretch(1)
        hdr.addWidget(self._char_lbl)
        v.addLayout(hdr)

        # Search bar
        srch_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search document text…")
        self._search.returnPressed.connect(self._do_search)
        self._search.setMaximumHeight(30)
        find_btn = QPushButton("Find")
        find_btn.setFixedHeight(30)
        find_btn.clicked.connect(self._do_search)
        clear_btn = QPushButton("✕")
        clear_btn.setFixedSize(30, 30)
        clear_btn.setToolTip("Clear search highlights")
        clear_btn.clicked.connect(self._clear_search)
        self._hit_lbl = QLabel("")
        self._hit_lbl.setObjectName("muted")
        self._hit_lbl.setStyleSheet("font-size:11px; min-width:60px;")
        srch_row.addWidget(self._search, 1)
        srch_row.addWidget(find_btn)
        srch_row.addWidget(clear_btn)
        srch_row.addWidget(self._hit_lbl)
        v.addLayout(srch_row)

        # Text viewer
        self._viewer = QTextEdit()
        self._viewer.setReadOnly(True)
        self._viewer.setFont(QFont("Consolas", 10))
        self._viewer.setLineWrapMode(QTextEdit.WidgetWidth)
        self._viewer.setPlaceholderText(
            "Extracted document text will appear here after processing."
        )
        v.addWidget(self._viewer, 1)

        self._doc_text = ""

    def load(self, doc) -> None:
        self._doc_text = doc.full_text or ""
        self._viewer.setPlainText(self._doc_text)
        chars = len(self._doc_text)
        ocr = " · OCR" if doc.used_ocr else ""
        self._char_lbl.setText(f"{chars:,} chars{ocr}")

    def clear(self) -> None:
        self._doc_text = ""
        self._viewer.clear()
        self._char_lbl.setText("")
        self._hit_lbl.setText("")

    def get_selection(self) -> str:
        return self._viewer.textCursor().selectedText().strip()

    def highlight_text(self, text: str) -> int:
        """Highlight all occurrences of text; return count."""
        doc = self._viewer.document()
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#2f4f1f"))

        cursor = QTextCursor(doc)
        count = 0
        while True:
            cursor = doc.find(text, cursor)
            if cursor.isNull():
                break
            cursor.mergeCharFormat(fmt)
            count += 1
        return count

    def _do_search(self) -> None:
        term = self._search.text().strip()
        if not term:
            return
        self._clear_search()
        count = self.highlight_text(term)
        self._hit_lbl.setText(f"{count} found" if count else "not found")
        # Scroll to first occurrence
        cursor = QTextCursor(self._viewer.document())
        found = self._viewer.document().find(term, cursor)
        if not found.isNull():
            self._viewer.setTextCursor(found)
            self._viewer.ensureCursorVisible()

    def _clear_search(self) -> None:
        cursor = QTextCursor(self._viewer.document())
        cursor.select(QTextCursor.Document)
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("transparent"))
        cursor.mergeCharFormat(fmt)
        self._hit_lbl.setText("")


# ──────────────────────────────────────────────────────────────────────────
# Field mapping dialog
# ──────────────────────────────────────────────────────────────────────────

class FieldMappingDialog(QDialog):
    """Interactive dialog: user searches/selects text from the document and
    assigns it as the value for a specific field. Optionally saves an anchor
    pattern so the app finds this field automatically in future documents.
    """

    def __init__(self, parent, field_name: str, doc_text: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Find value for:  {field_name}")
        self.setMinimumSize(860, 640)
        self.resize(920, 680)
        self._doc_text = doc_text
        self._field_name = field_name

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Instructions
        info = QLabel(
            f"<b>Finding: {field_name}</b><br>"
            "Search for the field value in the document text below. "
            "Select the exact value text, then click  <b>Use selected text</b>. "
            "Optionally save an anchor so the app finds it automatically next time."
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            "background:#10192e; border-left:3px solid #2f81f7; "
            "padding:10px 14px; border-radius:6px; color:#c9d1d9;"
        )
        layout.addWidget(info)

        # Search bar
        srch = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search document… (Enter to find)")
        self._search.returnPressed.connect(self._do_search)
        find_btn = QPushButton("Find")
        find_btn.clicked.connect(self._do_search)
        self._srch_lbl = QLabel("")
        self._srch_lbl.setObjectName("muted")
        srch.addWidget(self._search, 1)
        srch.addWidget(find_btn)
        srch.addWidget(self._srch_lbl)
        layout.addLayout(srch)

        # Document viewer
        self._viewer = QTextEdit()
        self._viewer.setReadOnly(True)
        self._viewer.setPlainText(doc_text)
        self._viewer.setFont(QFont("Consolas", 10))
        self._viewer.setLineWrapMode(QTextEdit.WidgetWidth)
        self._viewer.selectionChanged.connect(self._on_selection)
        layout.addWidget(self._viewer, 1)

        layout.addWidget(hline())

        # Selection row
        sel_row = QHBoxLayout()
        self._sel_lbl = QLabel("No text selected")
        self._sel_lbl.setObjectName("muted")
        use_sel_btn = QPushButton("Use selected text ↑")
        use_sel_btn.clicked.connect(self._use_selection)
        sel_row.addWidget(self._sel_lbl, 1)
        sel_row.addWidget(use_sel_btn)
        layout.addLayout(sel_row)

        # Value input
        val_row = QHBoxLayout()
        val_row.addWidget(QLabel(f"Value for \"{field_name}\":"))
        self._value_edit = QLineEdit()
        self._value_edit.setPlaceholderText("Paste or type the value if text selection is not available")
        self._value_edit.textChanged.connect(self._update_ok)
        val_row.addWidget(self._value_edit, 1)
        layout.addLayout(val_row)

        # Anchor / save-for-future section
        self._anchor_check = QCheckBox(
            "Save anchor pattern — so the app finds this field automatically in future documents of this type"
        )
        self._anchor_check.toggled.connect(self._toggle_anchor)
        layout.addWidget(self._anchor_check)

        self._anchor_group = QGroupBox("Anchor pattern (finds the value after this label)")
        anch_v = QVBoxLayout(self._anchor_group)
        anch_form = QFormLayout()
        self._anchor_edit = QLineEdit()
        self._anchor_edit.setPlaceholderText(
            "Text that appears before this value in the doc  (e.g. 'Purchase Order:' or 'PO#')"
        )
        self._anchor_preview = QLabel("")
        self._anchor_preview.setObjectName("muted")
        self._anchor_preview.setWordWrap(True)
        anch_form.addRow("Label before value:", self._anchor_edit)
        anch_form.addRow("Effect:", self._anchor_preview)
        anch_w = QWidget()
        anch_w.setLayout(anch_form)
        anch_v.addWidget(anch_w)
        anch_v.addWidget(
            label(
                "Tip: the anchor is the label/header that precedes the value on the same line. "
                "It's auto-detected when you click 'Use selected text' — review and adjust.",
                "muted",
            )
        )
        self._anchor_group.hide()
        layout.addWidget(self._anchor_group)

        # Buttons
        self._ok_btn = QPushButton(f'OK — use this value')
        self._ok_btn.setObjectName("primary")
        self._ok_btn.setEnabled(False)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self._ok_btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(cancel)
        btn_row.addWidget(self._ok_btn)
        layout.addLayout(btn_row)

    # ── Properties (read after accept) ──────────────────────────────
    @property
    def value(self) -> str:
        return self._value_edit.text().strip()

    @property
    def method(self) -> str:
        if self._anchor_check.isChecked() and self._anchor_edit.text().strip():
            return "anchor"
        return "manual"

    @property
    def locator(self) -> dict:
        if self.method == "anchor":
            return {
                "anchor": self._anchor_edit.text().strip(),
                "regex": r"[:\s]*([^\n\r]+)",
            }
        return {}

    # ── Internals ────────────────────────────────────────────────────
    def _do_search(self) -> None:
        term = self._search.text().strip()
        if not term:
            return
        # Clear old highlights
        cursor = QTextCursor(self._viewer.document())
        cursor.select(QTextCursor.Document)
        cursor.mergeCharFormat(QTextCharFormat())

        # Highlight all occurrences
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#2f4f1f"))
        c = QTextCursor(self._viewer.document())
        count = 0
        while True:
            c = self._viewer.document().find(term, c)
            if c.isNull():
                break
            c.mergeCharFormat(fmt)
            count += 1

        self._srch_lbl.setText(f"{count} found" if count else "not found")
        # Scroll to first
        first = self._viewer.document().find(term)
        if not first.isNull():
            self._viewer.setTextCursor(first)
            self._viewer.ensureCursorVisible()

    def _on_selection(self) -> None:
        sel = self._viewer.textCursor().selectedText().strip()
        if sel:
            display = sel[:80] + ("…" if len(sel) > 80 else "")
            self._sel_lbl.setText(f'Selected: "{display}"')
        else:
            self._sel_lbl.setText("No text selected")

    def _use_selection(self) -> None:
        sel = self._viewer.textCursor().selectedText().strip()
        if not sel:
            return
        self._value_edit.setText(sel)
        # Auto-detect anchor
        anchor = self._auto_anchor(sel)
        if anchor:
            self._anchor_edit.setText(anchor)
            self._anchor_check.setChecked(True)
            self._anchor_preview.setText(
                f"Will search for text after  '{anchor}'  on the same line."
            )

    def _auto_anchor(self, selected_value: str) -> str:
        """Look backwards from the selected value for a label pattern."""
        idx = self._doc_text.find(selected_value)
        if idx == -1:
            return ""
        before = self._doc_text[max(0, idx - 300) : idx]
        # Match trailing "Label:" or "Label" at end of text segment
        m = re.search(
            r"([A-Za-z][A-Za-z0-9 #/\-\.\(\)]+[:])[ \t]*$", before.rstrip()
        )
        if m:
            return m.group(1).strip()
        # Fallback: last non-empty line fragment
        lines = [ln.strip() for ln in before.split("\n") if ln.strip()]
        return lines[-1][:60] if lines else ""

    def _toggle_anchor(self, checked: bool) -> None:
        self._anchor_group.setVisible(checked)

    def _update_ok(self, text: str) -> None:
        v = text.strip()
        self._ok_btn.setEnabled(bool(v))
        self._ok_btn.setText(f'OK — use "{v[:40]}"' if v else "OK — use this value")


# ──────────────────────────────────────────────────────────────────────────
# Pipeline worker (background thread)
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    loaded_doc: Any
    extraction: Any
    report: Any
    matched_template: dict | None
    match_score: float


class PipelineWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    step = Signal(int)  # emits step index as it progresses

    def __init__(self, file_path: str, task_id: int) -> None:
        super().__init__()
        self.file_path = file_path
        self.task_id = task_id

    def run(self) -> None:
        try:
            store = LocalStore.instance()
            task_fields = store.get_task_fields(self.task_id)

            self.step.emit(0)  # Load
            doc = load_document(self.file_path)

            self.step.emit(1)  # Extract
            templates = store.list_templates(self.task_id)
            match = best_template(doc, templates)
            mappings: list[dict] = []
            matched_tpl, score = None, 0.0
            if match and match.score >= 80:
                matched_tpl = match.template
                score = match.score
                mappings = store.get_field_mappings(match.template["id"])
            extraction = extract_fields(doc, task_fields, mappings)

            self.step.emit(2)  # Validate
            report = validator.validate_extraction(
                self.task_id, task_fields, extraction.fields
            )

            self.finished.emit(
                PipelineResult(doc, extraction, report, matched_tpl, score)
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


# ──────────────────────────────────────────────────────────────────────────
# Process page
# ──────────────────────────────────────────────────────────────────────────

RESULT_COLS = ["Field", "Extracted value", "Status", "Resolved value", "Candidates / options", ""]

class ProcessPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.store = LocalStore.instance()
        self.setAcceptDrops(True)
        self.file_path: str | None = None
        self.result: PipelineResult | None = None
        self._thread: QThread | None = None
        self._worker: PipelineWorker | None = None
        self._row_meta: dict[int, dict] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(14)
        outer.addWidget(
            page_header(
                "Process Document",
                "Extract → Validate → Resolve → Export for Power Automate.",
            )
        )

        outer.addWidget(self._controls_card())
        outer.addWidget(self._steps_bar_card())
        outer.addWidget(self._main_splitter(), 1)

        self.refresh_tasks()
        self._set_step("idle")

    # ──────────────────────────────────────────────────────────────
    # Controls card
    # ──────────────────────────────────────────────────────────────
    def _controls_card(self) -> QWidget:
        self.task_combo = QComboBox()
        self.task_combo.setMinimumWidth(240)

        self.file_label = QLabel("Drop a document here, or click Browse…")
        self.file_label.setObjectName("muted")
        self.file_label.setWordWrap(True)

        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)

        self.process_btn = QPushButton("Process")
        self.process_btn.setObjectName("primary")
        self.process_btn.setFixedHeight(36)
        self.process_btn.setMinimumWidth(110)
        self.process_btn.clicked.connect(self._process)

        return card(
            row(label("Task:", "muted"), self.task_combo, browse, self.process_btn),
            self.file_label,
            spacing=8,
        )

    # ──────────────────────────────────────────────────────────────
    # Steps bar
    # ──────────────────────────────────────────────────────────────
    def _steps_bar_card(self) -> QWidget:
        self.steps_bar = PipelineStepsBar()
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(4)
        self.progress.setVisible(False)
        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")

        w = QFrame()
        w.setObjectName("card")
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(4)
        v.addWidget(self.steps_bar)
        v.addWidget(self.progress)
        v.addWidget(self.status_label)
        return w

    # ──────────────────────────────────────────────────────────────
    # Main splitter: document viewer + results
    # ──────────────────────────────────────────────────────────────
    def _main_splitter(self) -> QWidget:
        self.main_splitter = QSplitter(Qt.Horizontal)

        # Left: document viewer
        self.doc_viewer = DocumentViewer()
        self.doc_viewer_frame = QFrame()
        self.doc_viewer_frame.setObjectName("card")
        v = QVBoxLayout(self.doc_viewer_frame)
        v.setContentsMargins(12, 12, 12, 12)
        v.addWidget(self.doc_viewer)
        self.main_splitter.addWidget(self.doc_viewer_frame)

        # Right: results
        self.main_splitter.addWidget(self._results_panel())
        self.main_splitter.setSizes([400, 760])
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)

        # Initially collapse doc viewer until something is processed
        self.doc_viewer_frame.hide()
        return self.main_splitter

    def _results_panel(self) -> QWidget:
        w = QFrame()
        w.setObjectName("card")
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)

        # Empty state
        self._empty_state = self._make_empty_state()
        v.addWidget(self._empty_state)

        # Results table
        self._results_wrap = QWidget()
        rv = QVBoxLayout(self._results_wrap)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)

        self.results_hdr = QLabel("Validation results")
        self.results_hdr.setObjectName("cardTitle")
        rv.addWidget(self.results_hdr)

        self.table = QTableWidget(0, len(RESULT_COLS))
        self.table.setHorizontalHeaderLabels(RESULT_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.setTextElideMode(Qt.ElideNone)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.Interactive)
        hdr.setSectionResizeMode(5, QHeaderView.Fixed)
        hdr.resizeSection(1, 170)
        hdr.resizeSection(2, 100)
        hdr.resizeSection(4, 210)
        hdr.resizeSection(5, 90)
        rv.addWidget(self.table, 1)

        rv.addWidget(hline())

        # Action buttons
        self.save_tpl_btn = QPushButton("Save as template")
        self.learn_btn = QPushButton("Confirm & learn matches")
        self.export_btn = QPushButton("Export for RPA")
        self.export_btn.setObjectName("primary")
        self.export_btn.setFixedHeight(36)
        for b in (self.save_tpl_btn, self.learn_btn, self.export_btn):
            b.setEnabled(False)
        self.save_tpl_btn.clicked.connect(self._save_template)
        self.learn_btn.clicked.connect(self._confirm_and_learn)
        self.export_btn.clicked.connect(self._export)
        rv.addWidget(row(self.save_tpl_btn, self.learn_btn, self.export_btn))

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        rv.addWidget(self.summary)

        self._results_wrap.hide()
        v.addWidget(self._results_wrap, 1)
        return w

    def _make_empty_state(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(16)

        ico = QLabel("📄")
        ico.setAlignment(Qt.AlignCenter)
        ico.setStyleSheet("font-size:48px;")

        steps_html = """
        <ol style='color:#8b949e; line-height:1.8; font-size:13px;'>
          <li>Select a <b style='color:#e6edf3;'>Task</b> from the dropdown above
              (or go to <i>Tasks &amp; Fields</i> to set one up first).</li>
          <li><b style='color:#e6edf3;'>Drop a document</b> onto this window or click Browse —
              PDF, Word, Excel, or image.</li>
          <li>Click <b style='color:#2f81f7;'>Process</b>. The app extracts text, matches
              the layout, and validates each field against the warehouse.</li>
          <li>Review the results. Use <b style='color:#e6edf3;'>Find in document</b>
              on any field the app couldn't find automatically.</li>
          <li>Click <b style='color:#e6edf3;'>Confirm &amp; learn matches</b>, then
              <b style='color:#2f81f7;'>Export for RPA</b>.</li>
        </ol>
        """
        steps = QLabel(steps_html)
        steps.setWordWrap(True)
        steps.setTextFormat(Qt.RichText)
        steps.setAlignment(Qt.AlignLeft)
        steps.setMaximumWidth(560)

        v.addWidget(ico)
        v.addWidget(steps)
        return w

    # ──────────────────────────────────────────────────────────────
    # Drag & drop
    # ──────────────────────────────────────────────────────────────
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if urls:
            self._set_file(urls[0].toLocalFile())

    # ──────────────────────────────────────────────────────────────
    # Data
    # ──────────────────────────────────────────────────────────────
    def refresh_tasks(self) -> None:
        current = self.task_combo.currentData()
        self.task_combo.clear()
        for t in self.store.list_tasks():
            self.task_combo.addItem(t["name"], t["id"])
        if current is not None:
            idx = self.task_combo.findData(current)
            if idx >= 0:
                self.task_combo.setCurrentIndex(idx)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a document",
            "",
            "Documents (*.pdf *.docx *.doc *.xlsx *.xls *.csv *.png *.jpg *.jpeg *.tif *.tiff);;All files (*.*)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str) -> None:
        self.file_path = path
        import os
        self.file_label.setText(f"📄  {os.path.basename(path)}   ({path})")
        self.file_label.setStyleSheet("color:#e6edf3;")

    # ──────────────────────────────────────────────────────────────
    # Processing
    # ──────────────────────────────────────────────────────────────
    def _set_step(self, state: str, text: str = "") -> None:
        """Update pipeline step indicator. state: idle|loading|extracting|validating|review|done|error"""
        self.status_label.setText(text)
        mapping = {
            "idle": -1, "loading": 0, "extracting": 1,
            "validating": 2, "review": 3, "done": 4, "error": -1,
        }
        idx = mapping.get(state, -1)
        if idx >= 0:
            self.steps_bar.set_active(idx)
        elif state == "done":
            for i in range(5):
                self.steps_bar.set_done(i)
        else:
            self.steps_bar.reset()

    def _process(self) -> None:
        if self.task_combo.count() == 0:
            QMessageBox.information(
                self,
                "No tasks configured",
                "You haven't created any tasks yet.\n\n"
                "Go to  Tasks & Fields  to create a task and define the fields you want to extract.",
            )
            return
        if not self.file_path:
            QMessageBox.information(self, "No document", "Drop a document or click Browse first.")
            return
        task_id = self.task_combo.currentData()
        task_fields = self.store.get_task_fields(task_id)
        if not task_fields:
            QMessageBox.warning(
                self,
                "Task has no fields",
                "This task has no fields configured.\n\n"
                "Go to  Tasks & Fields, select this task, and add the fields "
                "you want to extract (e.g. PO Number, SKU, Quantity).\n\n"
                "Then come back and process the document.",
            )
            return

        self.process_btn.setEnabled(False)
        self.progress.setVisible(True)
        self._empty_state.hide()
        self._results_wrap.hide()
        self._set_step("loading", "Loading document…")

        self._thread = QThread()
        self._worker = PipelineWorker(self.file_path, task_id)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.step.connect(self._on_worker_step)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_worker_step(self, idx: int) -> None:
        msgs = ["Loading document…", "Extracting fields…", "Validating against warehouse…"]
        self._set_step(
            ["loading", "extracting", "validating"][idx],
            msgs[idx] if idx < len(msgs) else "",
        )

    def _on_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self.process_btn.setEnabled(True)
        self.steps_bar.set_error(0)
        self.status_label.setText(f"✗ {message}")
        self.status_label.setStyleSheet("color:#f85149;")
        self._empty_state.show()

    def _on_finished(self, result: PipelineResult) -> None:
        self.result = result
        self.progress.setVisible(False)
        self.process_btn.setEnabled(True)
        self.status_label.setStyleSheet("color:#8b949e;")

        doc = result.loaded_doc
        parts = [f"{doc.file_type.upper()} · {doc.char_count:,} chars"]
        if doc.used_ocr:
            parts.append("OCR used")
        if result.matched_template:
            parts.append(f"template matched: {result.matched_template['name']} ({result.match_score:.0f}%)")
        elif result.extraction.ai_used:
            parts.append("AI extraction")
        elif result.extraction.ai_message and "disabled" not in result.extraction.ai_message:
            parts.append(f"AI: {result.extraction.ai_message}")
        self.status_label.setText("  ·  ".join(parts))

        # Show document viewer
        self.doc_viewer.load(doc)
        self.doc_viewer_frame.show()
        self.main_splitter.setSizes([380, 780])

        if not result.report.fields:
            self._set_step("idle")
            self._empty_state.show()
            self.status_label.setText(
                "No fields to validate — this task has no fields configured. "
                "Go to Tasks & Fields to add them."
            )
            return

        self._set_step("review", "Review each field. Fix any marked Review or Unmatched.")
        self._populate_table(result.report)
        self._results_wrap.show()
        for b in (self.save_tpl_btn, self.learn_btn, self.export_btn):
            b.setEnabled(True)
        self._update_summary()

    # ──────────────────────────────────────────────────────────────
    # Results table
    # ──────────────────────────────────────────────────────────────
    def _populate_table(self, report) -> None:
        self.table.setRowCount(0)
        self._row_meta = {}

        for fv in report.fields.values():
            r = self.table.rowCount()
            self.table.insertRow(r)

            # Col 0: field name
            req = "  ★" if fv.required else ""
            name_item = QTableWidgetItem(f"{fv.display_name}{req}")
            name_item.setData(Qt.UserRole, fv.field_key)
            if fv.required:
                name_item.setForeground(QColor("#e6edf3"))
            name_item.setToolTip(
                f"Field key: {fv.field_key}\n"
                f"Validation: {fv.validation_type}\n"
                f"Required: {'Yes' if fv.required else 'No'}"
            )
            self.table.setItem(r, 0, name_item)

            # Col 1: extracted value (raw)
            raw = fv.raw_value or ""
            raw_item = QTableWidgetItem(raw)
            raw_item.setForeground(QColor("#8b949e"))
            raw_item.setToolTip(raw)
            self.table.setItem(r, 1, raw_item)

            # Col 2: status pill
            self.table.setCellWidget(r, 2, self._pill_cell(fv.status))

            # Col 3: resolved value (editable)
            resolved = QLineEdit(fv.resolved_value or fv.raw_value or "")
            resolved.setPlaceholderText("Enter or select a value…")
            resolved.setStyleSheet("background:transparent; border:none; padding:2px 6px;")
            self.table.setCellWidget(r, 3, resolved)

            # Col 4: candidates dropdown
            combo = QComboBox()
            combo.addItem("— keep above —", "")
            for cand in fv.candidates:
                combo.addItem(
                    f"{cand.value}  ·  {cand.label[:35]}  ({cand.score:.0f}%)",
                    cand.value,
                )
            if fv.candidates:
                combo.currentIndexChanged.connect(
                    lambda _i, le=resolved, cb=combo: (
                        le.setText(cb.currentData()) if cb.currentData() else None
                    )
                )
            else:
                combo.setEnabled(False)
                combo.setToolTip("No fuzzy candidates — no validation configured or no matches found.")
            self.table.setCellWidget(r, 4, combo)

            # Col 5: Find in doc button (for fields needing attention)
            if fv.status not in (STATUS_OK,):
                find_btn = QPushButton("🔍 Find")
                find_btn.setToolTip(
                    "Open the document text and select the value for this field manually."
                )
                find_btn.setStyleSheet(
                    "font-size:11px; padding:3px 8px; background:#1a2e4a; border:1px solid #2f81f7; color:#2f81f7; border-radius:6px;"
                )
                find_btn.clicked.connect(
                    lambda _c=False, rr=r, fk=fv.field_key, fn=fv.display_name, le=resolved: (
                        self._open_mapping_dialog(rr, fk, fn, le)
                    )
                )
                self.table.setCellWidget(r, 5, find_btn)

            self._row_meta[r] = {
                "field_key": fv.field_key,
                "resolved": resolved,
                "status": fv.status,
                "required": fv.required,
                "raw": raw,
                "validation_type": fv.validation_type,
                "confidence": fv.confidence,
            }
            self.table.setRowHeight(r, 40)

        self.table.resizeRowsToContents()

    def _pill_cell(self, status: str) -> QWidget:
        """Wrap a status pill in a centered container."""
        holder = QWidget()
        h = QHBoxLayout(holder)
        h.setContentsMargins(6, 4, 6, 4)
        h.addWidget(status_pill(status))
        return holder

    def _refresh_status_pills(self) -> None:
        for r, meta in self._row_meta.items():
            fv = self.result.report.fields.get(meta["field_key"])
            if fv:
                self.table.setCellWidget(r, 2, self._pill_cell(fv.status))

    def _update_summary(self) -> None:
        if not self.result:
            return
        report = self.result.report
        blocking = report.blocking_fields()
        if not blocking:
            self.summary.setText("✓  All required fields resolved — ready to export.")
            self.summary.setStyleSheet("color:#3fb950; font-weight:600;")
            self.steps_bar.set_done(3)
        else:
            names = ", ".join(f.display_name for f in blocking[:5])
            self.summary.setText(
                f"⚠  Resolve before export: {names}"
                + (" …and more" if len(blocking) > 5 else "")
            )
            self.summary.setStyleSheet("color:#d29922; font-weight:600;")

    # ──────────────────────────────────────────────────────────────
    # Field mapping dialog
    # ──────────────────────────────────────────────────────────────
    def _open_mapping_dialog(
        self, row: int, field_key: str, field_name: str, line_edit: QLineEdit
    ) -> None:
        if not self.result:
            return
        dlg = FieldMappingDialog(self, field_name, self.result.loaded_doc.full_text)
        # Pre-fill if there's already a value
        if line_edit.text().strip():
            dlg._value_edit.setText(line_edit.text().strip())
        if dlg.exec() != QDialog.Accepted:
            return

        value = dlg.value
        if not value:
            return

        # Update the resolved value widget
        line_edit.setText(value)

        # Update the report
        fv = self.result.report.fields.get(field_key)
        if fv:
            fv.resolved_value = value
            fv.status = STATUS_OK
        self._refresh_status_pills()
        self._update_summary()

        # Save anchor to template if requested
        if dlg.method == "anchor" and dlg.locator:
            self._save_anchor(field_key, dlg.method, dlg.locator)

    def _save_anchor(self, field_key: str, method: str, locator: dict) -> None:
        """Persist an anchor locator to the current (or auto-created) template."""
        if not self.result:
            return
        doc = self.result.loaded_doc
        task_id = self.task_combo.currentData()
        tpl = self.result.matched_template
        if not tpl:
            name = f"{doc.file_name} (auto)"
            tpl_id = self.store.upsert_template(
                task_id, name, doc.file_type, doc.fingerprint, doc.full_text[:4000]
            )
            # Update matched_template so subsequent saves in the same session work
            for t in self.store.list_templates(task_id):
                if t["id"] == tpl_id:
                    self.result.matched_template = t
                    break
        else:
            tpl_id = tpl["id"]

        existing = self.store.get_field_mappings(tpl_id)
        new_mapping = {"field_key": field_key, "method": method, "locator": locator}
        existing = [m for m in existing if m["field_key"] != field_key]
        existing.append(new_mapping)
        self.store.set_field_mappings(tpl_id, existing)

        task_name = self.task_combo.currentText()
        self.status_label.setText(
            f"Anchor saved — the app will find '{field_key}' automatically next time."
        )

    # ──────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────
    def _confirm_and_learn(self) -> None:
        if not self.result:
            return
        task_id = self.task_combo.currentData()
        learned = 0
        for meta in self._row_meta.values():
            resolved = meta["resolved"].text().strip()
            raw = meta["raw"].strip()
            fv = self.result.report.fields.get(meta["field_key"])
            if not fv:
                continue
            if resolved:
                fv.resolved_value = resolved
                fv.status = STATUS_OK
            # Learn fuzzy: raw description → resolved warehouse value
            if meta["validation_type"] == "fuzzy" and raw and resolved and resolved != raw:
                self.store.remember_match(
                    task_id,
                    meta["field_key"],
                    raw,
                    resolved,
                    confidence=float(meta["confidence"] or 95.0),
                )
                learned += 1
        self.store.audit("confirm_learn", f"task={task_id} learned={learned}")
        self._refresh_status_pills()
        self._update_summary()
        QMessageBox.information(
            self,
            "Confirmed",
            f"Changes confirmed.\nLearned {learned} new nomenclature mapping(s).\n\n"
            "Next time these values appear, they'll resolve automatically.",
        )

    def _save_template(self) -> None:
        if not self.result:
            return
        from PySide6.QtWidgets import QInputDialog
        task_id = self.task_combo.currentData()
        name, ok = QInputDialog.getText(
            self,
            "Save template",
            "Template name (use the document source, e.g. the vendor or system name):",
        )
        if not ok or not name.strip():
            return
        doc = self.result.loaded_doc
        tpl_id = self.store.upsert_template(
            task_id, name.strip(), doc.file_type, doc.fingerprint, doc.full_text[:4000]
        )
        # Save any anchors already in the result
        if self.result.matched_template:
            existing = self.store.get_field_mappings(self.result.matched_template["id"])
            self.store.set_field_mappings(tpl_id, existing)
        self.store.audit("save_template", f"task={task_id} name={name}")
        QMessageBox.information(
            self,
            "Template saved",
            f"Layout saved as '{name.strip()}'.\n\n"
            "Next time a document with the same structure arrives, "
            "the app will apply this mapping automatically.",
        )

    def _export(self) -> None:
        if not self.result:
            return
        # Pull latest edits into the report
        for meta in self._row_meta.values():
            resolved = meta["resolved"].text().strip()
            fv = self.result.report.fields.get(meta["field_key"])
            if fv and resolved:
                fv.resolved_value = resolved
                if fv.status in (STATUS_REVIEW, STATUS_UNMATCHED):
                    fv.status = STATUS_OK
        self._refresh_status_pills()
        self._update_summary()

        report = self.result.report
        if not report.ready_to_export:
            blocking = "\n• ".join(f.display_name for f in report.blocking_fields())
            QMessageBox.warning(
                self,
                "Not ready to export",
                f"These required fields still need values:\n\n• {blocking}\n\n"
                "Use  Find in document  or type a value in the Resolved value column, "
                "then click  Confirm & learn matches.",
            )
            return

        task_name = self.task_combo.currentText()
        payload = exporter.build_payload(
            task_name, self.result.loaded_doc.file_name, report
        )
        json_path = exporter.export_json(payload)
        csv_path = exporter.export_csv(payload)
        self.store.record_document(
            self.task_combo.currentData(),
            None,
            self.result.loaded_doc.file_name,
            self.result.loaded_doc.file_hash,
            "exported",
        )
        self.store.audit("export", json_path)
        self.steps_bar.set_done(4)
        self._set_step("done")
        QMessageBox.information(
            self,
            "Exported",
            f"Hand-off files written for Power Automate:\n\n{json_path}\n{csv_path}",
        )
