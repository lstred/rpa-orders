"""Process page: the end-to-end workflow.

Load a document -> recognize layout -> extract fields -> validate against the
warehouse -> let the user resolve anything uncertain -> learn -> export for RPA.
Heavy work (I/O, SQL, AI) runs on a worker thread so the UI never freezes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.local_store import LocalStore
from app.export import exporter
from app.extraction.field_extractor import extract_fields
from app.extraction.template_matcher import best_template
from app.ingestion.document_loader import load_document
from app.ui.widgets import card, label, page_header, row, status_pill
from app.validation import validator
from app.validation.validator import STATUS_OK, STATUS_REVIEW, STATUS_UNMATCHED


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

    def __init__(self, file_path: str, task_id: int) -> None:
        super().__init__()
        self.file_path = file_path
        self.task_id = task_id

    def run(self) -> None:
        try:
            store = LocalStore.instance()
            task_fields = store.get_task_fields(self.task_id)
            doc = load_document(self.file_path)

            templates = store.list_templates(self.task_id)
            match = best_template(doc, templates)
            mappings: list[dict] = []
            matched_tpl, score = None, 0.0
            if match and match.score >= 80:
                matched_tpl = match.template
                score = match.score
                mappings = store.get_field_mappings(match.template["id"])

            extraction = extract_fields(doc, task_fields, mappings)
            report = validator.validate_extraction(
                self.task_id, task_fields, extraction.fields
            )
            self.finished.emit(
                PipelineResult(doc, extraction, report, matched_tpl, score)
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


RESULT_COLS = ["Field", "Extracted value", "Status", "Resolved value", "Candidates", "Conf."]


class ProcessPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.store = LocalStore.instance()
        self.setAcceptDrops(True)
        self.file_path: str | None = None
        self.result: PipelineResult | None = None
        self._thread: QThread | None = None
        self._worker: PipelineWorker | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)
        outer.addWidget(
            page_header("Process Document", "Extract, validate, resolve, and export for Power Automate.")
        )

        outer.addWidget(self._controls_card())
        outer.addWidget(self._results_card(), 1)
        self.refresh_tasks()

    # ---------------- controls ----------------
    def _controls_card(self) -> QWidget:
        self.task_combo = QComboBox()
        self.task_combo.setMinimumWidth(220)

        self.file_label = QLabel("Drag a document here, or browse…")
        self.file_label.setObjectName("muted")

        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        self.process_btn = QPushButton("Process")
        self.process_btn.setObjectName("primary")
        self.process_btn.clicked.connect(self._process)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)

        self.info_label = QLabel("")
        self.info_label.setObjectName("muted")

        return card(
            row(
                label("Task:"),
                self.task_combo,
                browse,
                self.process_btn,
            ),
            self.file_label,
            self.progress,
            self.info_label,
        )

    # ---------------- results ----------------
    def _results_card(self) -> QWidget:
        self.table = QTableWidget(0, len(RESULT_COLS))
        self.table.setHorizontalHeaderLabels(RESULT_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.resizeSection(0, 150)
        hdr.resizeSection(1, 200)
        hdr.resizeSection(2, 110)
        hdr.resizeSection(3, 220)
        hdr.resizeSection(4, 260)

        self.save_tpl_btn = QPushButton("Save as template")
        self.save_tpl_btn.clicked.connect(self._save_template)
        self.learn_btn = QPushButton("Confirm & learn matches")
        self.learn_btn.clicked.connect(self._confirm_and_learn)
        self.export_btn = QPushButton("Export for RPA")
        self.export_btn.setObjectName("primary")
        self.export_btn.clicked.connect(self._export)
        for b in (self.save_tpl_btn, self.learn_btn, self.export_btn):
            b.setEnabled(False)

        self.summary = QLabel("")
        self.summary.setObjectName("muted")

        return card(
            label("Validation results", "cardTitle"),
            self.table,
            row(self.save_tpl_btn, self.learn_btn, self.export_btn),
            self.summary,
        )

    # ---------------- drag & drop ----------------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if urls:
            self._set_file(urls[0].toLocalFile())

    # ---------------- data ----------------
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
        self.file_label.setText(path)
        self.file_label.setObjectName("pageSubtitle")

    # ---------------- processing ----------------
    def _process(self) -> None:
        if self.task_combo.count() == 0:
            QMessageBox.information(self, "No tasks", "Create a task on the Tasks page first.")
            return
        if not self.file_path:
            QMessageBox.information(self, "No file", "Choose or drop a document first.")
            return
        task_id = self.task_combo.currentData()

        self.process_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.info_label.setText("Processing… loading, extracting, and validating.")

        self._thread = QThread()
        self._worker = PipelineWorker(self.file_path, task_id)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self.process_btn.setEnabled(True)
        self.info_label.setText(f"✗ {message}")
        self.info_label.setStyleSheet("color:#f85149;")

    def _on_finished(self, result: PipelineResult) -> None:
        self.result = result
        self.progress.setVisible(False)
        self.process_btn.setEnabled(True)

        doc = result.loaded_doc
        bits = [f"{doc.file_type.upper()} · {doc.char_count} chars"]
        if doc.used_ocr:
            bits.append("OCR used")
        if result.matched_template:
            bits.append(f"template: {result.matched_template['name']} ({result.match_score:.0f}%)")
        elif result.extraction.ai_used:
            bits.append("AI extraction")
        elif result.extraction.ai_message:
            bits.append(result.extraction.ai_message)
        self.info_label.setStyleSheet("color:#8b949e;")
        self.info_label.setText("  ·  ".join(bits))

        self._populate_table(result.report)
        for b in (self.save_tpl_btn, self.learn_btn, self.export_btn):
            b.setEnabled(True)
        self._update_summary()

    def _populate_table(self, report) -> None:
        self.table.setRowCount(0)
        self._row_widgets: dict[int, dict[str, Any]] = {}
        for fv in report.fields.values():
            r = self.table.rowCount()
            self.table.insertRow(r)

            name_item = QTableWidgetItem(fv.display_name + ("  *" if fv.required else ""))
            name_item.setData(Qt.UserRole, fv.field_key)
            self.table.setItem(r, 0, name_item)
            self.table.setItem(r, 1, QTableWidgetItem(fv.raw_value or ""))

            self.table.setCellWidget(r, 2, self._wrap(status_pill(fv.status)))

            resolved = QLineEdit(fv.resolved_value or fv.raw_value or "")
            self.table.setCellWidget(r, 3, resolved)

            combo = QComboBox()
            combo.addItem("— keep above —", "")
            for cand in fv.candidates:
                combo.addItem(f"{cand.value} · {cand.label[:40]} ({cand.score:.0f})", cand.value)
            if fv.candidates:
                combo.currentIndexChanged.connect(
                    lambda _i, rr=r, cc=combo, le=resolved: self._apply_candidate(rr, cc, le)
                )
            else:
                combo.setEnabled(False)
            self.table.setCellWidget(r, 4, combo)

            conf = QTableWidgetItem(f"{fv.confidence:.0f}" if fv.confidence else "")
            conf.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, 5, conf)

            self._row_widgets[r] = {
                "field_key": fv.field_key,
                "resolved": resolved,
                "status": fv.status,
                "required": fv.required,
                "raw": fv.raw_value or "",
                "validation_type": fv.validation_type,
                "confidence": fv.confidence,
            }
            self.table.setRowHeight(r, 38)

    def _wrap(self, widget) -> QWidget:
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.addWidget(widget)
        return holder

    def _apply_candidate(self, r: int, combo: QComboBox, line: QLineEdit) -> None:
        val = combo.currentData()
        if val:
            line.setText(val)

    def _update_summary(self) -> None:
        if not self.result:
            return
        report = self.result.report
        blocking = report.blocking_fields()
        if report.ready_to_export and not blocking:
            self.summary.setText("✓ All required fields resolved — ready to export.")
            self.summary.setStyleSheet("color:#3fb950;")
        else:
            names = ", ".join(f.display_name for f in blocking)
            self.summary.setText(f"⚠ Resolve required fields before export: {names}")
            self.summary.setStyleSheet("color:#d29922;")

    # ---------------- actions ----------------
    def _confirm_and_learn(self) -> None:
        if not self.result:
            return
        task_id = self.task_combo.currentData()
        learned = 0
        for meta in self._row_widgets.values():
            resolved = meta["resolved"].text().strip()
            raw = meta["raw"].strip()
            if not resolved:
                continue
            # update the underlying report so export reflects edits
            fv = self.result.report.fields[meta["field_key"]]
            fv.resolved_value = resolved
            if resolved:
                fv.status = STATUS_OK
            # learn fuzzy nomenclature when the user mapped a description -> value
            if meta["validation_type"] == "fuzzy" and raw and resolved != raw:
                self.store.remember_match(
                    task_id, meta["field_key"], raw, resolved,
                    confidence=float(meta["confidence"] or 100.0),
                )
                learned += 1
        self.store.audit("confirm_learn", f"task={task_id} learned={learned}")
        self._refresh_status_pills()
        self._update_summary()
        QMessageBox.information(
            self, "Confirmed",
            f"Saved your resolutions. Learned {learned} new nomenclature mapping(s).",
        )

    def _refresh_status_pills(self) -> None:
        for r, meta in self._row_widgets.items():
            fv = self.result.report.fields[meta["field_key"]]
            self.table.setCellWidget(r, 2, self._wrap(status_pill(fv.status)))

    def _save_template(self) -> None:
        if not self.result:
            return
        from PySide6.QtWidgets import QInputDialog

        task_id = self.task_combo.currentData()
        name, ok = QInputDialog.getText(
            self, "Save template", "Template name (e.g. the document source):"
        )
        if not ok or not name.strip():
            return
        doc = self.result.loaded_doc
        tpl_id = self.store.upsert_template(
            task_id, name.strip(), doc.file_type, doc.fingerprint, doc.full_text[:4000]
        )
        # persist current deterministic mappings (anchors learned from AI hints)
        mappings = []
        for meta in self._row_widgets.values():
            fv = self.result.report.fields[meta["field_key"]]
            if fv.raw_value:
                mappings.append(
                    {"field_key": meta["field_key"], "method": "ai", "locator": {}}
                )
        self.store.set_field_mappings(tpl_id, mappings)
        self.store.audit("save_template", f"task={task_id} name={name}")
        QMessageBox.information(
            self, "Template saved",
            "This layout is remembered. Matching documents will reuse it automatically.",
        )

    def _export(self) -> None:
        if not self.result:
            return
        # pull latest edited values into the report
        for meta in self._row_widgets.values():
            resolved = meta["resolved"].text().strip()
            fv = self.result.report.fields[meta["field_key"]]
            if resolved:
                fv.resolved_value = resolved
                if fv.status in (STATUS_REVIEW, STATUS_UNMATCHED):
                    fv.status = STATUS_OK
        self._refresh_status_pills()
        self._update_summary()

        report = self.result.report
        if not report.ready_to_export:
            blocking = ", ".join(f.display_name for f in report.blocking_fields())
            QMessageBox.warning(
                self, "Not ready",
                f"These required fields are unresolved:\n\n{blocking}",
            )
            return

        task_name = self.task_combo.currentText()
        payload = exporter.build_payload(task_name, self.result.loaded_doc.file_name, report)
        json_path = exporter.export_json(payload)
        csv_path = exporter.export_csv(payload)
        self.store.audit("export", json_path)
        QMessageBox.information(
            self, "Exported",
            f"Hand-off files written:\n\n{json_path}\n{csv_path}",
        )
