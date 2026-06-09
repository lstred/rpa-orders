"""Settings page: warehouse connection, AI provider + key vault, OCR, thresholds."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.core import database
from app.core import schema_cache
from app.core.config import Config
from app.core.security import delete_secret, get_secret, has_secret, set_secret
from app.extraction.ai_extractor import ANTHROPIC_KEY, OPENAI_KEY
from app.ui.widgets import card, label, page_header

MODEL_GUIDANCE = """
<style> p,li{color:#c9d1d9;line-height:1.5;} b{color:#e6edf3;}
 code{background:#161b22;padding:1px 5px;border-radius:4px;color:#79c0ff;}
 .g{color:#3fb950;} .a{color:#d29922;}</style>
<p><b>AI is optional</b> and only fills fields with no saved mapping. Costs below are
approximate per 1M tokens and change often — verify with the provider.</p>
<ul>
<li><b>Claude Sonnet 4</b> <code>claude-sonnet-4</code> — <span class="g">recommended
default</span>. Excellent at structured extraction &amp; document reasoning, vision
capable. ~$3 in / $15 out. Great accuracy-to-cost balance.</li>
<li><b>Claude Opus 4</b> — highest accuracy for messy/complex layouts. ~$15 in /
$75 out. Use when Sonnet struggles.</li>
<li><b>Claude Haiku</b> — cheapest Claude, fast, good for clean/simple docs.
Lower accuracy on noisy scans.</li>
<li><b>OpenAI GPT-4o</b> <code>gpt-4o</code> — strong, vision capable, broad
ecosystem. ~$2.50 in / $10 out. Comparable to Sonnet.</li>
<li><b>OpenAI GPT-4o-mini</b> — very cheap (~$0.15 in / $0.60 out), fine for
simple structured docs; weaker on ambiguous layouts.</li>
</ul>
<p><b>Pros of AI:</b> handles brand-new layouts with no setup; understands synonyms
&amp; abbreviations. <b>Cons:</b> per-call cost, network dependency, occasional
hallucination — which is exactly why every AI value still passes through warehouse
validation and your confirmation before export.</p>
<p><b>Privacy:</b> enabling AI sends document text to the chosen provider. For
sensitive documents prefer deterministic templates, or keep AI disabled.</p>
"""


class SettingsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)
        outer.addWidget(
            page_header("Settings", "Connection, AI, OCR, and matching thresholds.")
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 6, 0)
        body.setSpacing(16)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        body.addWidget(self._connection_card())
        body.addWidget(self._ai_card())
        body.addWidget(self._ocr_card())
        body.addWidget(self._fuzzy_card())
        body.addStretch(1)

    # ---------------- warehouse ----------------
    def _connection_card(self) -> QWidget:
        title = label("NRF_REPORTS Warehouse (read-only)", "cardTitle")
        self.server_edit = QLineEdit(Config.get("nrf_sql.server", "NRFVMSSQL04"))
        self.db_edit = QLineEdit(Config.get("nrf_sql.database", "NRF_REPORTS"))
        self.driver_edit = QLineEdit(
            Config.get("nrf_sql.driver", "ODBC Driver 18 for SQL Server")
        )

        form = QFormLayout()
        form.addRow("Server", self.server_edit)
        form.addRow("Database", self.db_edit)
        form.addRow("ODBC Driver", self.driver_edit)
        form_w = QWidget()
        form_w.setLayout(form)

        self.conn_status = label(
            "Windows Trusted Connection — no password stored.", "muted"
        )
        test_btn = QPushButton("Test connection")
        test_btn.setObjectName("primary")
        test_btn.clicked.connect(self._test_connection)
        save_btn = QPushButton("Save connection")
        save_btn.clicked.connect(self._save_connection)
        refresh_schema_btn = QPushButton("Refresh schema (columns)")
        refresh_schema_btn.setToolTip("Update the SQL table/column lists used in the field editor dropdowns.")
        refresh_schema_btn.clicked.connect(self._refresh_schema)

        btns = QWidget()
        h = QHBoxLayout(btns)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(test_btn)
        h.addWidget(save_btn)
        h.addWidget(refresh_schema_btn)
        h.addStretch(1)

        return card(title, form_w, btns, self.conn_status)

    def _save_connection(self) -> None:
        Config.set("nrf_sql.server", self.server_edit.text().strip())
        Config.set("nrf_sql.database", self.db_edit.text().strip())
        Config.set("nrf_sql.driver", self.driver_edit.text().strip())
        database.reset_engine()
        self.conn_status.setText("Saved. Connection settings updated.")

    def _refresh_schema(self) -> None:
        self._save_connection()
        ok, msg = schema_cache.refresh_from_db()
        self.conn_status.setText(("✓ " if ok else "ℹ ") + msg)
        self.conn_status.setStyleSheet(f"color: {'#3fb950' if ok else '#d29922'};")

    def _test_connection(self) -> None:
        self._save_connection()
        ok, msg = database.test_connection()
        self.conn_status.setText(("✓ " if ok else "✗ ") + msg)
        self.conn_status.setStyleSheet(
            f"color: {'#3fb950' if ok else '#f85149'};"
        )

    # ---------------- AI ----------------
    def _ai_card(self) -> QWidget:
        title = label("AI Extraction (optional fallback)", "cardTitle")
        self.ai_enabled = QCheckBox("Enable AI extraction")
        self.ai_enabled.setChecked(bool(Config.get("ai.enabled", False)))

        self.provider = QComboBox()
        self.provider.addItems(["anthropic", "openai"])
        self.provider.setCurrentText(Config.get("ai.provider", "anthropic"))

        self.model = QLineEdit(Config.get("ai.model", "claude-sonnet-4-20250514"))

        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText(
            "Stored in Windows Credential Manager — set already"
            if (has_secret(ANTHROPIC_KEY) or has_secret(OPENAI_KEY))
            else "Paste API key (stored securely, never in files)"
        )

        save_key = QPushButton("Save key")
        save_key.setObjectName("primary")
        save_key.clicked.connect(self._save_key)
        clear_key = QPushButton("Remove key")
        clear_key.setObjectName("danger")
        clear_key.clicked.connect(self._clear_key)
        save_ai = QPushButton("Save AI settings")
        save_ai.clicked.connect(self._save_ai)

        form = QFormLayout()
        form.addRow(self.ai_enabled)
        form.addRow("Provider", self.provider)
        form.addRow("Model", self.model)
        key_row = QWidget()
        kh = QHBoxLayout(key_row)
        kh.setContentsMargins(0, 0, 0, 0)
        kh.addWidget(self.api_key, 1)
        kh.addWidget(save_key)
        kh.addWidget(clear_key)
        form.addRow("API key", key_row)
        form.addRow(save_ai)
        form_w = QWidget()
        form_w.setLayout(form)

        guidance = QTextBrowser()
        guidance.setHtml(MODEL_GUIDANCE)
        guidance.setOpenExternalLinks(True)
        guidance.setMinimumHeight(260)
        guidance.setStyleSheet(
            "QTextBrowser{background:#161b22;border:1px solid #2a3340;"
            "border-radius:8px;padding:12px;}"
        )

        self.ai_status = label("", "muted")
        return card(title, form_w, self.ai_status, label("Model guidance", "cardTitle"), guidance)

    def _current_key_name(self) -> str:
        return ANTHROPIC_KEY if self.provider.currentText() == "anthropic" else OPENAI_KEY

    def _save_key(self) -> None:
        val = self.api_key.text().strip()
        if not val:
            self.ai_status.setText("Enter a key first.")
            return
        set_secret(self._current_key_name(), val)
        self.api_key.clear()
        self.ai_status.setText("✓ API key saved to the OS secret vault.")
        self.ai_status.setStyleSheet("color:#3fb950;")

    def _clear_key(self) -> None:
        delete_secret(self._current_key_name())
        self.ai_status.setText("API key removed from the vault.")
        self.ai_status.setStyleSheet("color:#d29922;")

    def _save_ai(self) -> None:
        Config.set("ai.enabled", self.ai_enabled.isChecked())
        Config.set("ai.provider", self.provider.currentText())
        Config.set("ai.model", self.model.text().strip())
        self.ai_status.setText("✓ AI settings saved.")
        self.ai_status.setStyleSheet("color:#3fb950;")

    # ---------------- OCR ----------------
    def _ocr_card(self) -> QWidget:
        title = label("OCR (scanned documents)", "cardTitle")
        self.tess = QLineEdit(Config.get("ocr.tesseract_cmd", ""))
        self.tess.setPlaceholderText(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        self.ocr_lang = QLineEdit(Config.get("ocr.language", "eng"))
        save = QPushButton("Save OCR settings")
        save.clicked.connect(self._save_ocr)
        form = QFormLayout()
        form.addRow("Tesseract path", self.tess)
        form.addRow("Language", self.ocr_lang)
        form.addRow(save)
        w = QWidget()
        w.setLayout(form)
        self.ocr_status = label("", "muted")
        return card(title, w, self.ocr_status)

    def _save_ocr(self) -> None:
        Config.set("ocr.tesseract_cmd", self.tess.text().strip())
        Config.set("ocr.language", self.ocr_lang.text().strip() or "eng")
        from app.ingestion.ocr import tesseract_available

        ok = tesseract_available()
        self.ocr_status.setText(
            "✓ Tesseract detected." if ok else "Saved, but Tesseract not detected at that path."
        )
        self.ocr_status.setStyleSheet("color:" + ("#3fb950;" if ok else "#d29922;"))

    # ---------------- fuzzy thresholds ----------------
    def _fuzzy_card(self) -> QWidget:
        title = label("Fuzzy matching thresholds", "cardTitle")
        self.auto = QSpinBox()
        self.auto.setRange(50, 100)
        self.auto.setValue(int(Config.get("fuzzy.auto_accept_score", 95)))
        self.floor = QSpinBox()
        self.floor.setRange(0, 100)
        self.floor.setValue(int(Config.get("fuzzy.review_floor_score", 70)))
        save = QPushButton("Save thresholds")
        save.clicked.connect(self._save_fuzzy)
        form = QFormLayout()
        form.addRow("Auto-accept score (≥)", self.auto)
        form.addRow("Review floor (≥)", self.floor)
        form.addRow(save)
        w = QWidget()
        w.setLayout(form)
        return card(
            title,
            label(
                "Scores at or above auto-accept are confirmed automatically. Between "
                "the floor and auto-accept require review. Below the floor are flagged.",
                "muted",
            ),
            w,
        )

    def _save_fuzzy(self) -> None:
        if self.floor.value() > self.auto.value():
            QMessageBox.warning(self, "Invalid", "Review floor must be ≤ auto-accept.")
            return
        Config.set("fuzzy.auto_accept_score", self.auto.value())
        Config.set("fuzzy.review_floor_score", self.floor.value())
        QMessageBox.information(self, "Saved", "Thresholds updated.")
