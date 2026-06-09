"""Process page — end-to-end document pipeline.

Layout (after processing):
  ┌─ Controls ─────────────────────────────────────────────────────────────────┐
  │  Task ▾  |  📄 filename  |  [Browse]  [Process]   AI: Claude Sonnet 4 ✓  │
  └────────────────────────────────────────────────────────────────────────────┘
  ┌─ Pipeline ──────────────────────────────────────────────────────────────────┐
  │  ① Load  ›  ② Extract  ›  ③ Validate  ›  ④ Review  ›  ⑤ Export           │
  └────────────────────────────────────────────────────────────────────────────┘
  ┌─ Document text (left) ──────┐  ┌─ Field results (right) ──────────────────┐
  │                              │  │  Field | Found | Status | Resolved |     │
  │  [Find-mode banner]          │  │  ...                                     │
  │                              │  │  [Save template] [Confirm] [Export]      │
  │  Extracted text              │  │  Summary                                 │
  └──────────────────────────────┘  └──────────────────────────────────────────┘

"Find" works inline: clicking 🔍 Find for a row activates the doc viewer, which
highlights the current value and shows a banner.  User selects text in the viewer,
clicks "Use selection", the value is applied to the row.  An optional anchor-save
dialog follows so the app finds it automatically next time.
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
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.config import Config
from app.core.local_store import LocalStore
from app.export import exporter
from app.extraction.ai_extractor import ai_enabled
from app.extraction.field_extractor import extract_fields
from app.extraction.template_matcher import best_template
from app.ingestion.document_loader import load_document
from app.ui.widgets import hline, label, page_header, row, status_pill
from app.validation import validator
from app.validation.validator import STATUS_MISSING, STATUS_OK, STATUS_REVIEW, STATUS_UNMATCHED

# ──────────────────────────────────────────────────────────────────────────
# Pipeline steps bar
# ──────────────────────────────────────────────────────────────────────────

_STEP_NAMES = ["① Load", "② Extract", "③ Validate", "④ Review", "⑤ Export"]
_STEP_COLORS = {
    "pending": ("#2a3340", "#8b949e"),
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
                arr = QLabel("›")
                arr.setStyleSheet("color:#4a5568; font-size:18px; font-weight:900; padding:0 2px;")
                arr.setFixedWidth(18)
                h.addWidget(arr)
        self.reset()

    def _apply(self, idx: int, state: str) -> None:
        bg, fg = _STEP_COLORS.get(state, _STEP_COLORS["pending"])
        self._btns[idx].setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:8px;"
            f"padding:4px 8px; font-size:12px;"
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
# Document viewer (left panel) — with inline "Find mode"
# ──────────────────────────────────────────────────────────────────────────

class DocumentViewer(QWidget):
    """Shows extracted document text with search + an optional Find-mode banner.

    Find mode: caller activates by calling ``start_find_mode()``.  A blue banner
    appears above the text.  When the user selects text and clicks "Use selection",
    ``field_value_selected(selected_text, context_before)`` is emitted.  The
    caller applies the value and then calls ``exit_find_mode()``.
    """

    field_value_selected = Signal(str, str)  # (selected_text, 300-char context before)

    def __init__(self) -> None:
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        # Header row
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
        clear_btn.setToolTip("Clear highlights")
        clear_btn.clicked.connect(self._clear_search)
        self._hit_lbl = QLabel("")
        self._hit_lbl.setObjectName("muted")
        self._hit_lbl.setStyleSheet("font-size:11px; min-width:60px;")
        srch_row.addWidget(self._search, 1)
        srch_row.addWidget(find_btn)
        srch_row.addWidget(clear_btn)
        srch_row.addWidget(self._hit_lbl)
        v.addLayout(srch_row)

        # ── Find-mode banner (hidden until start_find_mode()) ──
        self._find_banner = QFrame()
        self._find_banner.setObjectName("findBanner")
        bl = QHBoxLayout(self._find_banner)
        bl.setContentsMargins(10, 8, 10, 8)
        self._find_lbl = QLabel("")
        self._find_lbl.setWordWrap(True)
        self._find_lbl.setTextFormat(Qt.RichText)
        self._use_sel_btn = QPushButton("✔  Use selection")
        self._use_sel_btn.setObjectName("primary")
        self._use_sel_btn.setFixedHeight(30)
        self._use_sel_btn.clicked.connect(self._emit_selection)
        self._cancel_find_btn = QPushButton("✕  Cancel")
        self._cancel_find_btn.setFixedHeight(30)
        self._cancel_find_btn.clicked.connect(self.exit_find_mode)
        bl.addWidget(self._find_lbl, 1)
        bl.addWidget(self._use_sel_btn)
        bl.addWidget(self._cancel_find_btn)
        self._find_banner.hide()
        v.addWidget(self._find_banner)

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
        self._find_mode = False

    # ── Public API ──────────────────────────────────────────────────
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

    def start_find_mode(self, field_name: str, current_value: str = "") -> None:
        """Activate the find banner for a specific field."""
        self._find_mode = True
        self._find_lbl.setText(
            f"🔍 <b>Finding: {field_name}</b>"
            f"&nbsp;&nbsp;—&nbsp;&nbsp;"
            "click and drag to select the value in the text below, then click "
            "<b>Use selection</b>."
        )
        self._find_banner.show()
        # Highlight the currently known value to orient the user
        if current_value.strip():
            self._clear_search()
            self.highlight_text(current_value.strip(), color="#1a3a60")
            first = self._viewer.document().find(current_value.strip())
            if not first.isNull():
                self._viewer.setTextCursor(first)
                self._viewer.ensureCursorVisible()

    def exit_find_mode(self) -> None:
        self._find_mode = False
        self._find_banner.hide()
        self._clear_search()

    def highlight_text(self, text: str, color: str = "#2f4f1f") -> int:
        """Highlight all occurrences; return count."""
        doc = self._viewer.document()
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(color))
        cursor = QTextCursor(doc)
        count = 0
        while True:
            cursor = doc.find(text, cursor)
            if cursor.isNull():
                break
            cursor.mergeCharFormat(fmt)
            count += 1
        return count

    # ── Internals ────────────────────────────────────────────────────
    def _do_search(self) -> None:
        term = self._search.text().strip()
        if not term:
            return
        self._clear_search()
        count = self.highlight_text(term)
        self._hit_lbl.setText(f"{count} found" if count else "not found")
        first = self._viewer.document().find(term)
        if not first.isNull():
            self._viewer.setTextCursor(first)
            self._viewer.ensureCursorVisible()

    def _clear_search(self) -> None:
        cursor = QTextCursor(self._viewer.document())
        cursor.select(QTextCursor.Document)
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("transparent"))
        cursor.mergeCharFormat(fmt)
        self._hit_lbl.setText("")

    def _emit_selection(self) -> None:
        sel = self._viewer.textCursor().selectedText().strip()
        if not sel:
            orig = self._find_lbl.text()
            self._find_lbl.setText(
                "⚠  <b>No text selected.</b>  Click and drag over the value first."
            )
            # Restore after a moment — use a one-shot timer
            from PySide6.QtCore import QTimer
            QTimer.singleShot(2500, lambda: self._find_lbl.setText(orig))
            return
        # Include ~300 chars before the selection for anchor auto-detection
        idx = self._doc_text.find(sel)
        context_before = self._doc_text[max(0, idx - 300): idx] if idx != -1 else ""
        self.field_value_selected.emit(sel, context_before)


# ──────────────────────────────────────────────────────────────────────────
# Anchor save dialog — minimal, shown after a selection is applied
# ──────────────────────────────────────────────────────────────────────────

class AnchorSaveDialog(QDialog):
    """Ask if the user wants to save an anchor so this field is found automatically next time."""

    def __init__(
        self, parent, field_name: str, selected_value: str, detected_anchor: str
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Remember how to find this field?")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        info = QLabel(
            f'Value  <b>"{selected_value[:70]}"</b>  applied to  <b>{field_name}</b>.\n\n'
            "Do you want the app to find this field automatically in future documents "
            "with the same layout?  It will look for the label (anchor) text that "
            "appears just before the value."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._save_check = QCheckBox("Yes — save anchor pattern for this layout")
        self._save_check.setChecked(bool(detected_anchor))
        self._save_check.toggled.connect(self._toggle_fields)
        layout.addWidget(self._save_check)

        anchor_row = QHBoxLayout()
        anchor_row.addWidget(QLabel("Label before value:"))
        self._anchor_edit = QLineEdit(detected_anchor)
        self._anchor_edit.setPlaceholderText("e.g.  'PO Number:'  or  'Purchase Order'")
        anchor_row.addWidget(self._anchor_edit, 1)
        layout.addLayout(anchor_row)

        self._hint = QLabel(
            f"Detected anchor: <i>\"{detected_anchor}\"</i>"
            if detected_anchor
            else "No anchor auto-detected — type the label text that appears before the value."
        )
        self._hint.setWordWrap(True)
        self._hint.setObjectName("muted")
        layout.addWidget(self._hint)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("Save anchor")
        btns.button(QDialogButtonBox.Cancel).setText("Skip (keep value, no anchor)")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._toggle_fields(bool(detected_anchor))

    def _toggle_fields(self, checked: bool) -> None:
        self._anchor_edit.setEnabled(checked)
        self._hint.setEnabled(checked)

    @property
    def should_save(self) -> bool:
        return self._save_check.isChecked()

    @property
    def anchor(self) -> str:
        return self._anchor_edit.text().strip()


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
    step = Signal(int)  # 0=Load, 1=Extract, 2=Validate

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

RESULT_COLS = ["Field  ★=required", "Extracted", "Status", "Resolved value", "Candidates", ""]


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

        # Active find-mode state
        self._find_key: str | None = None
        self._find_le: QLineEdit | None = None
        self._last_export_json: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(14)
        outer.addWidget(
            page_header(
                "Process Document",
                "Load a document, extract fields, validate against the warehouse, then export for Power Automate.",
            )
        )
        outer.addWidget(self._controls_card())
        outer.addWidget(self._steps_bar_card())
        outer.addWidget(self._main_splitter(), 1)

        self.refresh_tasks()
        self._set_step("idle")
        self._update_ai_badge()

    # ──────────────────────────────────────────────────────────────
    # Controls card
    # ──────────────────────────────────────────────────────────────
    def _controls_card(self) -> QWidget:
        w = QFrame()
        w.setObjectName("card")
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(8)

        # Row 1: task + file + buttons + AI badge
        self.task_combo = QComboBox()
        self.task_combo.setMinimumWidth(220)
        self.task_combo.setToolTip(
            "Select the task (RPA workflow) that matches this document.\n"
            "Set up tasks and their fields in Tasks & Fields."
        )

        browse_btn = QPushButton("Browse…")
        browse_btn.setToolTip("Choose a PDF, Word, Excel or image file")
        browse_btn.clicked.connect(self._browse)

        self.process_btn = QPushButton("▶  Process")
        self.process_btn.setObjectName("primary")
        self.process_btn.setFixedHeight(36)
        self.process_btn.setMinimumWidth(120)
        self.process_btn.setToolTip(
            "Load and extract the document, then validate each field against the warehouse."
        )
        self.process_btn.clicked.connect(self._process)

        self._ai_badge = QLabel()
        self._ai_badge.setObjectName("muted")
        self._ai_badge.setStyleSheet("font-size:12px; padding:4px 8px; border-radius:6px;")
        self._ai_badge.setCursor(Qt.PointingHandCursor)
        self._ai_badge.setToolTip("Click to go to AI settings")
        self._ai_badge.mousePressEvent = lambda _: self._go_to_settings()

        r1 = QHBoxLayout()
        r1.setSpacing(8)
        r1.addWidget(QLabel("Task:"))
        r1.addWidget(self.task_combo, 1)
        r1.addWidget(browse_btn)
        r1.addWidget(self.process_btn)
        r1.addSpacing(12)
        r1.addWidget(self._ai_badge)
        v.addLayout(r1)

        # Row 2: file path / drop zone
        self.file_label = QLabel("Drop a document onto this window, or click Browse…")
        self.file_label.setObjectName("muted")
        self.file_label.setWordWrap(True)
        v.addWidget(self.file_label)

        return w

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
        self.status_label.setWordWrap(True)

        w = QFrame()
        w.setObjectName("card")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)
        layout.addWidget(self.steps_bar)
        layout.addWidget(self.progress)
        layout.addWidget(self.status_label)
        return w

    # ──────────────────────────────────────────────────────────────
    # Main splitter: document viewer + results
    # ──────────────────────────────────────────────────────────────
    def _main_splitter(self) -> QWidget:
        self.main_splitter = QSplitter(Qt.Horizontal)

        # Left: document viewer
        self.doc_viewer = DocumentViewer()
        self.doc_viewer.field_value_selected.connect(self._on_field_value_selected)
        self.doc_viewer_frame = QFrame()
        self.doc_viewer_frame.setObjectName("card")
        dv_layout = QVBoxLayout(self.doc_viewer_frame)
        dv_layout.setContentsMargins(12, 12, 12, 12)
        dv_layout.addWidget(self.doc_viewer)
        self.main_splitter.addWidget(self.doc_viewer_frame)

        # Right: results
        self.main_splitter.addWidget(self._results_panel())
        self.main_splitter.setSizes([400, 760])
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)

        self.doc_viewer_frame.hide()  # shown after first successful process
        return self.main_splitter

    def _results_panel(self) -> QWidget:
        w = QFrame()
        w.setObjectName("card")
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)

        # Empty state (shown before any processing)
        self._empty_state = self._make_empty_state()
        v.addWidget(self._empty_state)

        # Results area (hidden until results arrive)
        self._results_wrap = QWidget()
        rv = QVBoxLayout(self._results_wrap)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)

        hdr_row = QHBoxLayout()
        self.results_hdr = QLabel("Validation results")
        self.results_hdr.setObjectName("cardTitle")
        self._method_lbl = QLabel("")
        self._method_lbl.setObjectName("muted")
        self._method_lbl.setStyleSheet("font-size:11px;")
        hdr_row.addWidget(self.results_hdr)
        hdr_row.addStretch(1)
        hdr_row.addWidget(self._method_lbl)
        rv.addLayout(hdr_row)

        # Hint bar — explains the Review/Find workflow
        self._hint_bar = QLabel(
            "💡  Fields marked  <b style='color:#d29922;'>REVIEW</b>  have a fuzzy warehouse match — "
            "pick from Candidates or click  🔍 Find  to select from the document.  "
            "Fields marked  <b style='color:#f85149;'>UNMATCHED / MISSING</b>  need a value before you can export."
        )
        self._hint_bar.setWordWrap(True)
        self._hint_bar.setTextFormat(Qt.RichText)
        self._hint_bar.setStyleSheet(
            "background:#141e2b; border-left:3px solid #2f81f7; "
            "padding:8px 12px; border-radius:6px; color:#c9d1d9; font-size:12px;"
        )
        rv.addWidget(self._hint_bar)

        # Results table
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
        hdr.resizeSection(1, 160)
        hdr.resizeSection(2, 100)
        hdr.resizeSection(4, 200)
        hdr.resizeSection(5, 80)
        rv.addWidget(self.table, 1)

        rv.addWidget(hline())

        # Action buttons with tooltips
        self.save_tpl_btn = QPushButton("💾  Save layout")
        self.save_tpl_btn.setToolTip(
            "Save this document's layout so the app applies field mappings\n"
            "automatically the next time a document from the same source arrives."
        )
        self.learn_btn = QPushButton("✔  Confirm & learn")
        self.learn_btn.setToolTip(
            "Apply all edits and save any fuzzy matches to memory.\n"
            "Next time the same descriptions appear they resolve automatically."
        )
        self.export_btn = QPushButton("📤  Export for RPA")
        self.export_btn.setObjectName("primary")
        self.export_btn.setFixedHeight(36)
        self.export_btn.setToolTip(
            "Write JSON + CSV hand-off files for Power Automate.\n"
            "All required ★ fields must be OK before export is allowed."
        )
        for b in (self.save_tpl_btn, self.learn_btn, self.export_btn):
            b.setEnabled(False)
        self.save_tpl_btn.clicked.connect(self._save_template)
        self.learn_btn.clicked.connect(self._confirm_and_learn)
        self.export_btn.clicked.connect(self._export)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addWidget(self.save_tpl_btn)
        btn_row.addWidget(self.learn_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.export_btn)
        rv.addLayout(btn_row)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        rv.addWidget(self.summary)

        # Post-export quick-access row — hidden until export succeeds
        self._post_export_row = QWidget()
        per = QHBoxLayout(self._post_export_row)
        per.setContentsMargins(0, 4, 0, 0)
        per.setSpacing(8)
        self._open_folder_btn = QPushButton("📂  Open exports folder")
        self._open_folder_btn.setToolTip("Open the folder in Explorer")
        self._open_folder_btn.clicked.connect(self._open_exports_folder)
        self._view_export_btn = QPushButton("👁  View in Exports")
        self._view_export_btn.setToolTip("Go to the Exports page to preview this file")
        self._view_export_btn.clicked.connect(self._go_to_exports)
        per.addWidget(self._open_folder_btn)
        per.addWidget(self._view_export_btn)
        per.addStretch(1)
        self._post_export_row.hide()
        rv.addWidget(self._post_export_row)

        self._results_wrap.hide()
        v.addWidget(self._results_wrap, 1)
        return w

    def _make_empty_state(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(20)

        ico = QLabel("📄")
        ico.setAlignment(Qt.AlignCenter)
        ico.setStyleSheet("font-size:48px;")

        heading = QLabel("Ready to process a document")
        heading.setAlignment(Qt.AlignCenter)
        heading.setObjectName("cardTitle")

        steps_html = """
        <div style='color:#8b949e; line-height:2; font-size:13px; max-width:520px;'>
          <p><b style='color:#e6edf3;'>① Select a task</b> — the RPA workflow this
          document belongs to (Customer Orders, Receiving, etc.).<br>
          &nbsp;&nbsp;No tasks yet? Go to <i>Tasks &amp; Fields</i> to set one up.</p>

          <p><b style='color:#e6edf3;'>② Drop a document</b> onto this window or click Browse
          — PDF, Word, Excel, or image.</p>

          <p><b style='color:#2f81f7;'>③ Click Process</b> — the app extracts text, matches
          the layout, and validates each field against the warehouse.</p>

          <p><b style='color:#e6edf3;'>④ Review</b> — fix any field the app couldn't resolve
          automatically using <b>🔍 Find</b> or by typing directly.</p>

          <p><b style='color:#e6edf3;'>⑤ Export</b> — write the JSON + CSV hand-off files
          for Power Automate.</p>
        </div>
        """
        steps = QLabel(steps_html)
        steps.setWordWrap(True)
        steps.setTextFormat(Qt.RichText)
        steps.setAlignment(Qt.AlignLeft)
        steps.setMaximumWidth(580)

        v.addWidget(ico)
        v.addWidget(heading)
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
    # Data helpers
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

    def _update_ai_badge(self) -> None:
        if ai_enabled():
            provider = Config.get("ai.provider", "anthropic")
            model = Config.get("ai.model", "claude-sonnet-4-20250514")
            short = model.split("-")[0].capitalize() if model else provider.capitalize()
            self._ai_badge.setText(f"🤖  AI: {provider.capitalize()} {short} ✓")
            self._ai_badge.setStyleSheet(
                "font-size:12px; padding:4px 10px; border-radius:6px; "
                "background:#0f2318; color:#3fb950; border:1px solid #1a3a24;"
            )
            self._ai_badge.setToolTip(
                f"AI extraction is enabled ({provider} / {model}).\n"
                "AI fills fields with no template mapping.\n"
                "Click to open Settings."
            )
        else:
            self._ai_badge.setText("🤖  AI: Off")
            self._ai_badge.setStyleSheet(
                "font-size:12px; padding:4px 10px; border-radius:6px; "
                "background:#1a212b; color:#8b949e; border:1px solid #2a3340;"
            )
            self._ai_badge.setToolTip(
                "AI extraction is disabled.\n"
                "Only saved templates and anchor patterns are used.\n"
                "Click to open Settings and enable AI."
            )

    def _go_to_settings(self) -> None:
        win = self.window()
        if hasattr(win, "navigate"):
            win.navigate("settings")

    def _open_exports_folder(self) -> None:
        _paths.ensure_dirs()
        subprocess.Popen(["explorer.exe", str(_paths.EXPORTS_DIR)])

    def _go_to_exports(self) -> None:
        win = self.window()
        if hasattr(win, "navigate"):
            win.navigate("exports")

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
        import os
        self.file_path = path
        self.file_label.setText(f"📄  {os.path.basename(path)}   —   {path}")
        self.file_label.setStyleSheet("color:#e6edf3;")

    # ──────────────────────────────────────────────────────────────
    # Processing
    # ──────────────────────────────────────────────────────────────
    def _set_step(self, state: str, text: str = "") -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet("color:#8b949e;")
        mapping = {
            "loading": 0, "extracting": 1, "validating": 2, "review": 3, "done": 4,
        }
        if state in mapping:
            self.steps_bar.set_active(mapping[state])
        elif state == "done":
            for i in range(5):
                self.steps_bar.set_done(i)
        elif state == "error":
            self.steps_bar.set_error(0)
            self.status_label.setStyleSheet("color:#f85149;")
        else:
            self.steps_bar.reset()

    def _process(self) -> None:
        self._update_ai_badge()

        if self.task_combo.count() == 0:
            QMessageBox.information(
                self,
                "No tasks configured",
                "You haven't created any tasks yet.\n\n"
                "Go to  Tasks & Fields  in the sidebar to create a task and "
                "define the fields you want to extract (Customer Number, PO#, SKU, etc.).",
            )
            return

        if not self.file_path:
            QMessageBox.information(
                self,
                "No document selected",
                "Drop a document onto this window, or click  Browse…  to choose a file.\n\n"
                "Supported formats: PDF, Word (.docx), Excel (.xlsx/.csv), images (.png/.jpg).",
            )
            return

        task_id = self.task_combo.currentData()
        task_fields = self.store.get_task_fields(task_id)
        if not task_fields:
            QMessageBox.warning(
                self,
                "Task has no fields",
                "This task has no fields configured — there's nothing to extract.\n\n"
                "Go to  Tasks & Fields, select this task, and add the fields "
                "you want to extract (e.g. PO Number, SKU, Customer Number).\n\n"
                "Then come back and click  Process.",
            )
            return

        # Reset UI
        self.process_btn.setEnabled(False)
        self.progress.setVisible(True)
        self._empty_state.hide()
        self._results_wrap.hide()
        self.doc_viewer.exit_find_mode()
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
        states = ["loading", "extracting", "validating"]
        self._set_step(states[idx], msgs[idx])

    def _on_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self.process_btn.setEnabled(True)
        self._set_step("error", f"Error: {message}")
        self._empty_state.show()
        QMessageBox.critical(
            self,
            "Processing failed",
            f"An error occurred while processing the document:\n\n{message}\n\n"
            "Check that the file is not password-protected or corrupted.\n"
            "For scanned PDFs, make sure Tesseract OCR is configured in Settings.",
        )

    def _on_finished(self, result: PipelineResult) -> None:
        self.result = result
        self.progress.setVisible(False)
        self.process_btn.setEnabled(True)
        self._post_export_row.hide()  # reset for new run

        doc = result.loaded_doc
        parts = [f"{doc.file_type.upper()}  ·  {doc.char_count:,} chars"]
        if doc.used_ocr:
            parts.append("OCR")
        if result.matched_template:
            parts.append(
                f"template: \"{result.matched_template['name']}\" ({result.match_score:.0f}% match)"
            )
        if result.extraction.ai_used:
            ai_fields = [k for k, ef in result.extraction.fields.items() if ef.method == "ai" and ef.value]
            parts.append(f"AI filled {len(ai_fields)} field(s)")
            # Update AI badge to show it actually did something
            self._ai_badge.setText(f"🤖 AI: filled {len(ai_fields)} field(s)")
            self._ai_badge.setStyleSheet(
                "font-size:12px; padding:4px 10px; border-radius:6px; "
                "background:#1a3a10; color:#3fb950; border:1px solid #2a5a18;"
            )
            self._ai_badge.setToolTip(
                f"AI extracted values for {len(ai_fields)} field(s) this run.\n"
                f"Fields: {', '.join(ai_fields)}\n"
                "Hover over the Extracted column to see which fields used AI."
            )
        elif ai_enabled():
            # AI is on but wasn't needed
            self._ai_badge.setText("🤖 AI: standby")
            self._ai_badge.setStyleSheet(
                "font-size:12px; padding:4px 10px; border-radius:6px; "
                "background:#1a2230; color:#5a8abf; border:1px solid #2a3a50;"
            )
            self._ai_badge.setToolTip(
                "AI is configured and ready, but wasn't needed this time.\n"
                "A saved template or anchor pattern handled all the fields.\n"
                "AI only runs when there's no other way to find a field's value."
            )
        elif result.extraction.ai_message:
            msg = result.extraction.ai_message
            if "disabled" not in msg.lower():
                parts.append(f"AI: {msg}")

        method_text = "  ·  ".join(parts)
        self._method_lbl.setText(method_text)

        # Show document viewer
        self.doc_viewer.load(doc)
        self.doc_viewer_frame.show()
        self.main_splitter.setSizes([380, 780])

        if not result.report.fields:
            self._set_step("idle")
            self._empty_state.show()
            return

        self._set_step("review", "Review each field below. Use 🔍 Find to locate any missing values in the document.")
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

            # ── Col 0: field name ──
            req = "  ★" if fv.required else ""
            name_item = QTableWidgetItem(f"{fv.display_name}{req}")
            name_item.setData(Qt.UserRole, fv.field_key)
            if fv.required:
                name_item.setForeground(QColor("#e6edf3"))
            name_item.setToolTip(
                f"Key: {fv.field_key}\n"
                f"Validation: {fv.validation_type}\n"
                f"Required: {'Yes ★' if fv.required else 'No'}"
            )
            self.table.setItem(r, 0, name_item)

            # ── Col 1: extracted value ── (tooltip shows HOW it was found)
            raw = fv.raw_value or ""
            raw_item = QTableWidgetItem(raw)
            raw_item.setForeground(QColor("#8b949e"))
            ef = self.result.extraction.fields.get(fv.field_key) if self.result else None
            _method_labels = {
                "ai":     "🤖 AI extracted",
                "anchor": "🔗 Anchor pattern (auto)",
                "regex":  "📐 Regex pattern",
                "cell":   "📊 Spreadsheet cell",
                "fixed":  "📌 Fixed / constant",
                "none":   "— No mapping (not found)",
            }
            method_lbl = _method_labels.get(ef.method if ef else "none", ef.method if ef else "none")
            conf_str = f"{ef.confidence:.0f}% confidence" if ef and ef.confidence > 0 else ""
            raw_item.setToolTip(
                f"Extracted:  {raw!r}\n"
                f"Source:  {method_lbl}"
                + (f"\nConfidence:  {conf_str}" if conf_str else "")
            )
            self.table.setItem(r, 1, raw_item)

            # ── Col 2: status ──
            self.table.setCellWidget(r, 2, self._pill_cell(fv.status))

            # ── Col 3: resolved value (editable via cell widget) ──
            resolved_le = QLineEdit(fv.resolved_value or fv.raw_value or "")
            resolved_le.setPlaceholderText("Type a value, or use Find / Candidates →")
            resolved_le.setStyleSheet("background:transparent; border:none; padding:2px 6px;")
            resolved_le.textChanged.connect(lambda _txt, rr=r: self._on_resolved_changed(rr))
            self.table.setCellWidget(r, 3, resolved_le)

            # ── Col 4: candidates ──
            combo = QComboBox()
            combo.addItem("— warehouse matches —", "")
            for cand in fv.candidates:
                combo.addItem(
                    f"{cand.value}  ·  {cand.label[:35]}  ({cand.score:.0f}%)",
                    cand.value,
                )
            if fv.candidates:
                combo.currentIndexChanged.connect(
                    lambda _i, le=resolved_le, cb=combo: (
                        le.setText(cb.currentData()) if cb.currentData() else None
                    )
                )
                combo.setToolTip(
                    "Fuzzy warehouse matches ranked by similarity.\n"
                    "Select one to copy it to Resolved value."
                )
            else:
                combo.setEnabled(False)
                combo.setToolTip(
                    "No fuzzy candidates.\n"
                    "This field has no fuzzy validation, or no warehouse matches were found."
                )
            self.table.setCellWidget(r, 4, combo)

            # ── Col 5: Find button (for fields needing attention) ──
            if fv.status != STATUS_OK:
                find_btn = QPushButton("🔍 Find")
                find_btn.setToolTip(
                    "Activate the document viewer on the left.\n"
                    "Select the correct text, then click  'Use selection'."
                )
                find_btn.setStyleSheet(
                    "font-size:11px; padding:3px 8px;"
                    "background:#1a2e4a; border:1px solid #2f81f7;"
                    "color:#2f81f7; border-radius:6px;"
                )
                find_btn.clicked.connect(
                    lambda _c=False, fk=fv.field_key, fn=fv.display_name, le=resolved_le: (
                        self._start_inline_find(fk, fn, le)
                    )
                )
                self.table.setCellWidget(r, 5, find_btn)

            self._row_meta[r] = {
                "field_key": fv.field_key,
                "resolved": resolved_le,
                "status": fv.status,
                "required": fv.required,
                "raw": raw,
                "validation_type": fv.validation_type,
                "confidence": fv.confidence,
            }
            self.table.setRowHeight(r, 40)

            # Tint rows that are blocking
            if fv.is_blocking:
                for col in range(self.table.columnCount()):
                    item = self.table.item(r, col)
                    if item:
                        item.setBackground(QColor("#250c0c"))

        self.table.resizeRowsToContents()

    def _on_resolved_changed(self, table_row: int) -> None:
        """Live status update when user edits the resolved value field."""
        meta = self._row_meta.get(table_row)
        if not meta or not self.result:
            return
        val = meta["resolved"].text().strip()
        fv = self.result.report.fields.get(meta["field_key"])
        if fv and val:
            fv.resolved_value = val
            if fv.status in (STATUS_REVIEW, STATUS_UNMATCHED, STATUS_MISSING):
                fv.status = STATUS_OK
            meta["status"] = fv.status
            self._refresh_status_pills()
            self._update_summary()

    def _pill_cell(self, status: str) -> QWidget:
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
            self.summary.setText("✓  All required fields are resolved — ready to export.")
            self.summary.setStyleSheet("color:#3fb950; font-weight:600;")
            self.steps_bar.set_done(3)
        else:
            names = ", ".join(f.display_name for f in blocking[:4])
            extra = f" …+{len(blocking)-4} more" if len(blocking) > 4 else ""
            self.summary.setText(
                f"⚠  Resolve these required ★ fields before export:  {names}{extra}"
            )
            self.summary.setStyleSheet("color:#d29922; font-weight:600;")

    # ──────────────────────────────────────────────────────────────
    # Inline Find mode
    # ──────────────────────────────────────────────────────────────
    def _start_inline_find(self, field_key: str, field_name: str, line_edit: QLineEdit) -> None:
        """Activate the doc viewer's find banner for a specific field."""
        self._find_key = field_key
        self._find_le = line_edit

        # Make sure the doc viewer is visible
        if not self.doc_viewer_frame.isVisible() and self.result:
            self.doc_viewer_frame.show()
            self.main_splitter.setSizes([380, 780])

        self.doc_viewer.start_find_mode(field_name, current_value=line_edit.text().strip())

    def _on_field_value_selected(self, selected_text: str, context_before: str) -> None:
        """Called when user clicks 'Use selection' in the doc viewer banner."""
        if not self._find_key or self._find_le is None:
            return

        field_key = self._find_key
        field_name = ""
        fv = self.result.report.fields.get(field_key) if self.result else None
        if fv:
            field_name = fv.display_name

        # Apply the selected value immediately
        self._find_le.setText(selected_text)
        if fv:
            fv.resolved_value = selected_text
            fv.status = STATUS_OK
        self._refresh_status_pills()
        self._update_summary()

        # Exit find mode
        self.doc_viewer.exit_find_mode()
        self._find_key = None
        self._find_le = None

        # Ask if they want to save an anchor
        detected_anchor = _auto_detect_anchor(selected_text, context_before)
        dlg = AnchorSaveDialog(self, field_name, selected_text, detected_anchor)
        if dlg.exec() == QDialog.Accepted and dlg.should_save and dlg.anchor:
            self._save_anchor(
                field_key,
                "anchor",
                {"anchor": dlg.anchor, "regex": r"[:\s]*([^\n\r]+)"},
            )

    def _save_anchor(self, field_key: str, method: str, locator: dict) -> None:
        """Persist an anchor locator to the current (or auto-created) template."""
        if not self.result:
            return
        doc = self.result.loaded_doc
        task_id = self.task_combo.currentData()
        tpl = self.result.matched_template
        if not tpl:
            # Auto-create a template for this document layout
            name = f"{doc.file_name} (auto)"
            tpl_id = self.store.upsert_template(
                task_id, name, doc.file_type, doc.fingerprint, doc.full_text[:4000]
            )
            for t in self.store.list_templates(task_id):
                if t["id"] == tpl_id:
                    self.result.matched_template = t
                    break
        else:
            tpl_id = tpl["id"]

        existing = self.store.get_field_mappings(tpl_id)
        existing = [m for m in existing if m["field_key"] != field_key]
        existing.append({"field_key": field_key, "method": method, "locator": locator})
        self.store.set_field_mappings(tpl_id, existing)
        self.status_label.setText(
            f"Anchor saved for '{field_key}' — will be found automatically next time."
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
                if fv.status in (STATUS_REVIEW, STATUS_UNMATCHED, STATUS_MISSING):
                    fv.status = STATUS_OK
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

        msg = f"All edits confirmed."
        if learned:
            msg += (
                f"\n\nLearned {learned} new nomenclature mapping(s).\n"
                "These descriptions will resolve automatically next time."
            )
        QMessageBox.information(self, "Confirmed", msg)

    def _save_template(self) -> None:
        if not self.result:
            return
        from PySide6.QtWidgets import QInputDialog
        task_id = self.task_combo.currentData()
        suggested = self.result.loaded_doc.file_name
        name, ok = QInputDialog.getText(
            self,
            "Save document layout",
            "Give this layout a name — usually the source system or vendor name\n"
            "(e.g. 'MX Vendor', 'Customer XYZ Orders').\n\n"
            "Future documents with the same structure will be recognized automatically:",
            text=suggested,
        )
        if not ok or not name.strip():
            return
        doc = self.result.loaded_doc
        tpl_id = self.store.upsert_template(
            task_id, name.strip(), doc.file_type, doc.fingerprint, doc.full_text[:4000]
        )
        if self.result.matched_template:
            existing = self.store.get_field_mappings(self.result.matched_template["id"])
            self.store.set_field_mappings(tpl_id, existing)
        self.store.audit("save_template", f"task={task_id} name={name.strip()}")
        QMessageBox.information(
            self,
            "Layout saved",
            f"Layout saved as \"{name.strip()}\".\n\n"
            "Next time a document with this structure arrives, the app will\n"
            "apply all saved anchor patterns automatically — no manual mapping needed.",
        )

    def _export(self) -> None:
        if not self.result:
            return

        # Sync all edits from the table into the report before checking
        for meta in self._row_meta.values():
            resolved = meta["resolved"].text().strip()
            fv = self.result.report.fields.get(meta["field_key"])
            if fv and resolved:
                fv.resolved_value = resolved
                if fv.status in (STATUS_REVIEW, STATUS_UNMATCHED, STATUS_MISSING):
                    fv.status = STATUS_OK

        self._refresh_status_pills()
        self._update_summary()

        report = self.result.report
        if not report.ready_to_export:
            blocking = report.blocking_fields()
            names = "\n• ".join(f.display_name for f in blocking)
            QMessageBox.warning(
                self,
                "Required fields not resolved",
                f"These required ★ fields still need a value before export:\n\n• {names}\n\n"
                "Options:\n"
                "  • Click  🔍 Find  next to a field and select the value from the document.\n"
                "  • Type a value directly in the  Resolved value  column.\n"
                "  • Pick from  Candidates  (fuzzy matches) if the field has them.\n\n"
                "If a field is truly not present, mark it as optional in Tasks & Fields.",
            )
            return

        # Export
        try:
            task_name = self.task_combo.currentText()
            payload = exporter.build_payload(
                task_name, self.result.loaded_doc.file_name, report
            )
            json_path = exporter.export_json(payload)
            csv_path = exporter.export_csv(payload)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "Export failed",
                f"An error occurred while writing the export files:\n\n{exc}\n\n"
                "Check that the exports folder is accessible (Settings shows the path).",
            )
            return

        # Record & audit (non-fatal if these fail)
        try:
            self.store.record_document(
                self.task_combo.currentData(),
                None,
                self.result.loaded_doc.file_name,
                self.result.loaded_doc.file_hash,
                "exported",
            )
            self.store.audit("export", json_path)
        except Exception:  # noqa: BLE001
            pass

        self.steps_bar.set_done(4)
        self._last_export_json = json_path
        self._post_export_row.show()
        self._set_step("done", f"✓  Export complete — saved to {_paths.EXPORTS_DIR}")
        self.status_label.setStyleSheet("color:#3fb950; font-weight:600;")
        import os.path
        fname = os.path.basename(json_path)
        QMessageBox.information(
            self,
            "Exported successfully",
            f"Files written for Power Automate:\n\n"
            f"  {fname}\n"
            f"  {os.path.basename(csv_path)}\n\n"
            f"Saved in:\n  {_paths.EXPORTS_DIR}\n\n"
            "Click  📂 Open exports folder  to see the files in Explorer.\n"
            "Click  👁 View in Exports  to preview the contents inside this app.",
        )


# ──────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────

def _auto_detect_anchor(selected_value: str, context_before: str) -> str:
    """Heuristic: find the label that appears just before the selected value."""
    if not context_before:
        return ""
    # Prefer "Label:" patterns at end of context
    m = re.search(r"([A-Za-z][A-Za-z0-9 #/\-\.\(\)]+[:])\s*$", context_before.rstrip())
    if m:
        return m.group(1).strip()
    # Fallback: last non-empty line
    lines = [ln.strip() for ln in context_before.split("\n") if ln.strip()]
    return lines[-1][:60] if lines else ""
