"""AI-powered Line Items Setup Dialog.

Lets the user describe the document structure in plain English.  The AI re-parses
the document and shows a live preview.  The result can be applied immediately or
saved so the same description is reused whenever this document layout is processed.

Usage:
    dlg = LineItemsSetupDialog(
        parent=self,
        document_text=doc.full_text,
        current_items=self._line_items,
        template_id=matched_template_id,   # None if no template saved yet
    )
    if dlg.exec() == QDialog.Accepted:
        self._line_items = dlg.accepted_items
        self._populate_line_items(dlg.accepted_items)
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
    QHeaderView,
    QProgressBar,
    QSizePolicy,
)

from app.core.local_store import LocalStore
from app.extraction.ai_extractor import analyze_line_items_with_ai, ai_enabled


# ──────────────────────────────────────────────────────────────────────────────
# Background AI worker
# ──────────────────────────────────────────────────────────────────────────────

class _AIWorker(QObject):
    finished = Signal(list, str)   # (items, ai_text)
    failed   = Signal(str)

    def __init__(self, document_text: str, instruction: str, conversation: list) -> None:
        super().__init__()
        self.document_text = document_text
        self.instruction = instruction
        self.conversation = conversation

    def run(self) -> None:
        try:
            items, reply = analyze_line_items_with_ai(
                self.document_text, self.instruction, self.conversation
            )
            self.finished.emit(items, reply)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


# ──────────────────────────────────────────────────────────────────────────────
# Dialog
# ──────────────────────────────────────────────────────────────────────────────

_PREVIEW_COLS = ["#", "Order #", "Full Description (SKU + Color)", "Qty", "Price/SYD",
                 "Extended ($)", "Account #", "Rolls"]


class LineItemsSetupDialog(QDialog):
    """Iterative AI chat for refining line-item extraction."""

    def __init__(
        self,
        parent: QWidget,
        document_text: str,
        current_items: list[dict[str, Any]],
        template_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.document_text = document_text
        self.template_id = template_id
        self.accepted_items: list[dict] = list(current_items)
        self._pending_items: list[dict] = []
        self._conversation: list[dict] = []   # multi-turn history
        self._thread: QThread | None = None
        self._worker: _AIWorker | None = None

        self.setWindowTitle("🤖  AI Line Items Setup")
        self.setMinimumSize(1050, 680)
        self.resize(1150, 720)
        self._build_ui(current_items)

        # Load any previously-saved hint
        if template_id:
            hint = LocalStore.instance().get_line_items_hint(template_id)
            if hint:
                self._instruction.setPlainText(hint)
                self._chat_append("system", f"📌  Saved instruction loaded:\n\n{hint}")

        # Show current items in preview
        self._show_preview(current_items, source_label=f"Auto-detected: {len(current_items)} items")

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self, current_items: list) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Title
        title = QLabel(
            "Describe how line items look in this document — the AI will re-parse "
            "and show a preview.  Once it looks right, click  <b>Apply</b>."
        )
        title.setWordWrap(True)
        title.setTextFormat(Qt.RichText)
        title.setStyleSheet("color:#8b949e; font-size:12px; padding-bottom:4px;")
        root.addWidget(title)

        # Main splitter: doc text | right panel
        splitter = QSplitter(Qt.Horizontal)

        # Left: document text
        left = QFrame()
        left.setObjectName("card")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(10, 10, 10, 10)
        lv.setSpacing(6)
        doc_lbl = QLabel("Document text  (read-only excerpt)")
        doc_lbl.setObjectName("cardTitle")
        lv.addWidget(doc_lbl)
        self._doc_view = QPlainTextEdit()
        self._doc_view.setReadOnly(True)
        self._doc_view.setPlainText(self.document_text[:15000])
        self._doc_view.setFont(QFont("Consolas", 10))
        self._doc_view.setStyleSheet(
            "background:#0d1117; border:1px solid #2a3340; border-radius:6px;"
            "color:#8b949e; padding:6px;"
        )
        lv.addWidget(self._doc_view)
        splitter.addWidget(left)

        # Right: chat + instruction + preview
        right = QFrame()
        right.setObjectName("card")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(10, 10, 10, 10)
        rv.setSpacing(8)

        # Chat history
        chat_lbl = QLabel("AI conversation")
        chat_lbl.setObjectName("cardTitle")
        rv.addWidget(chat_lbl)
        self._chat = QTextEdit()
        self._chat.setReadOnly(True)
        self._chat.setMinimumHeight(120)
        self._chat.setMaximumHeight(180)
        self._chat.setStyleSheet(
            "background:#0d1117; border:1px solid #2a3340; border-radius:6px;"
            "color:#c9d1d9; padding:8px;"
        )
        rv.addWidget(self._chat)

        # Instruction input
        inst_lbl = QLabel(
            "Describe the structure or give a correction  "
            "<span style='color:#8b949e;'>(or leave blank to auto-analyze)</span>"
        )
        inst_lbl.setTextFormat(Qt.RichText)
        rv.addWidget(inst_lbl)
        self._instruction = QPlainTextEdit()
        self._instruction.setPlaceholderText(
            "Examples:\n"
            "  • Items always start with a number then a SKU like POSH BIO-XX\n"
            "  • The color appears on the line below the item number\n"
            "  • This PDF has both an invoice and a packing list — de-duplicate\n"
            "  • Ignore rows where the account number is 808999\n\n"
            "Leave blank for automatic analysis."
        )
        self._instruction.setFixedHeight(100)
        rv.addWidget(self._instruction)

        # Analyze button + progress
        btn_row = QHBoxLayout()
        self._analyze_btn = QPushButton("🤖  Analyze with AI")
        self._analyze_btn.setObjectName("primary")
        self._analyze_btn.setFixedHeight(34)
        self._analyze_btn.clicked.connect(self._run_analysis)
        if not ai_enabled():
            self._analyze_btn.setEnabled(False)
            self._analyze_btn.setToolTip(
                "AI is not configured. Go to Settings to enable it and add an API key."
            )
        self._clear_chat_btn = QPushButton("Clear conversation")
        self._clear_chat_btn.setFixedHeight(34)
        self._clear_chat_btn.clicked.connect(self._clear_conversation)
        btn_row.addWidget(self._analyze_btn)
        btn_row.addWidget(self._clear_chat_btn)
        btn_row.addStretch(1)
        rv.addLayout(btn_row)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(6)
        self._progress.setVisible(False)
        rv.addWidget(self._progress)

        # Preview table
        preview_row = QHBoxLayout()
        self._preview_lbl = QLabel("Preview")
        self._preview_lbl.setObjectName("cardTitle")
        self._apply_preview_btn = QPushButton("✔  Apply this result")
        self._apply_preview_btn.setFixedHeight(30)
        self._apply_preview_btn.setEnabled(False)
        self._apply_preview_btn.clicked.connect(self._apply_pending)
        self._save_and_apply_btn = QPushButton("💾  Save description + Apply")
        self._save_and_apply_btn.setFixedHeight(30)
        self._save_and_apply_btn.setEnabled(False)
        self._save_and_apply_btn.setToolTip(
            "Save this description as part of the document layout so it is reused\n"
            "automatically whenever a document with the same layout is processed."
        )
        self._save_and_apply_btn.clicked.connect(self._save_and_apply)
        preview_row.addWidget(self._preview_lbl)
        preview_row.addStretch(1)
        preview_row.addWidget(self._apply_preview_btn)
        preview_row.addWidget(self._save_and_apply_btn)
        rv.addLayout(preview_row)

        self._preview_table = QTableWidget(0, len(_PREVIEW_COLS))
        self._preview_table.setHorizontalHeaderLabels(_PREVIEW_COLS)
        self._preview_table.verticalHeader().setVisible(False)
        self._preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._preview_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        ph = self._preview_table.horizontalHeader()
        ph.setSectionResizeMode(QHeaderView.ResizeToContents)
        ph.setSectionResizeMode(2, QHeaderView.Stretch)
        rv.addWidget(self._preview_table, 1)

        splitter.addWidget(right)
        splitter.setSizes([380, 660])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        # Bottom buttons
        btn_box = QDialogButtonBox(QDialogButtonBox.Cancel)
        btn_box.rejected.connect(self.reject)
        root.addWidget(btn_box)

        if not ai_enabled():
            self._chat_append(
                "system",
                "⚠️  AI is not enabled.\n\n"
                "Go to  Settings → AI Provider  and enable AI + add your API key.\n"
                "Then re-open this dialog to use AI analysis.",
            )

    # ── Chat helpers ───────────────────────────────────────────────────────────

    def _chat_append(self, role: str, text: str) -> None:
        colors = {"user": "#2f81f7", "ai": "#3fb950", "system": "#d29922"}
        labels = {"user": "You", "ai": "AI", "system": "System"}
        color = colors.get(role, "#8b949e")
        label = labels.get(role, role)
        html = (
            f'<p style="margin:4px 0;">'
            f'<b style="color:{color};">{label}:</b>&nbsp;'
            f'<span style="color:#c9d1d9;">{text.replace(chr(10), "<br>")}</span>'
            f"</p>"
        )
        self._chat.append(html)
        self._chat.verticalScrollBar().setValue(
            self._chat.verticalScrollBar().maximum()
        )

    def _clear_conversation(self) -> None:
        self._conversation = []
        self._chat.clear()
        self._chat_append("system", "Conversation cleared.  Type a new description and click Analyze.")

    # ── Analysis ───────────────────────────────────────────────────────────────

    def _run_analysis(self) -> None:
        instruction = self._instruction.toPlainText().strip()
        self._chat_append("user", instruction or "(auto-analyze — no specific instruction)")

        self._analyze_btn.setEnabled(False)
        self._progress.setVisible(True)
        # Store instruction so _on_ai_done can record it correctly
        self._last_instruction = instruction

        self._thread = QThread()
        self._worker = _AIWorker(self.document_text, instruction, self._conversation)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_ai_done)
        self._worker.failed.connect(self._on_ai_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_ai_done(self, items: list, ai_text: str) -> None:
        self._progress.setVisible(False)
        self._analyze_btn.setEnabled(True)

        # Record the turn for multi-turn context
        instruction = getattr(self, "_last_instruction", "")
        self._conversation.append({"role": "user", "content": instruction or "(auto-analyze)"})
        self._conversation.append({"role": "assistant", "content": ai_text})

        n = len(items)
        if n > 0:
            preview = ", ".join(it.get("full_name", "") for it in items[:3])
            extra = f" …+{n-3} more" if n > 3 else ""
            ai_reply = f"Found {n} item{'s' if n != 1 else ''}: {preview}{extra}"
        else:
            # Show a truncated excerpt of what the AI actually returned so the user
            # knows what happened and can correct their instruction.
            excerpt = ai_text[:600].replace("<", "&lt;").replace(">", "&gt;")
            if len(ai_text) > 600:
                excerpt += " …"
            ai_reply = (
                f"⚠️  Found 0 items — could not parse the response into line items.\n\n"
                f"The AI replied:\n{excerpt}\n\n"
                "Try rephrasing your description and clicking Analyze again, or clear the "
                "conversation and start fresh."
            )
        self._chat_append("ai", ai_reply)

        self._pending_items = items
        self._show_preview(items, f"AI result: {n} item{'s' if n != 1 else ''}")
        self._apply_preview_btn.setEnabled(bool(items))
        self._save_and_apply_btn.setEnabled(bool(items) and self.template_id is not None)

    def _on_ai_failed(self, msg: str) -> None:
        self._progress.setVisible(False)
        self._analyze_btn.setEnabled(True)
        self._chat_append("system", f"❌ Error: {msg}")

    # ── Preview ────────────────────────────────────────────────────────────────

    def _show_preview(self, items: list, source_label: str) -> None:
        self._preview_lbl.setText(f"Preview — {source_label}")
        self._preview_table.setRowCount(0)
        for item in items:
            r = self._preview_table.rowCount()
            self._preview_table.insertRow(r)
            full_name = item.get("full_name") or (
                item.get("sku", "") + " " + item.get("color", "")
            ).strip()
            values = [
                item.get("item_num", ""),
                item.get("order_num", ""),
                full_name,
                item.get("qty", ""),
                item.get("price", ""),
                item.get("extended_price", ""),
                item.get("account", ""),
                str(item.get("roll_count", len(item.get("rolls", [])))),
            ]
            for col, val in enumerate(values):
                cell = QTableWidgetItem(str(val))
                cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self._preview_table.setItem(r, col, cell)

    # ── Apply / Save ───────────────────────────────────────────────────────────

    def _apply_pending(self) -> None:
        self.accepted_items = list(self._pending_items)
        self.accept()

    def _save_and_apply(self) -> None:
        if not self.template_id:
            QMessageBox.information(
                self,
                "No template to save to",
                "Save the document layout first (click  💾 Save layout  on the Process page),\n"
                "then re-open this dialog to save the AI description.",
            )
            return
        hint = self._instruction.toPlainText().strip()
        LocalStore.instance().save_line_items_hint(self.template_id, hint)
        self.accepted_items = list(self._pending_items)
        self._chat_append("system", "✅  Description saved to this document layout.")
        self.accept()
