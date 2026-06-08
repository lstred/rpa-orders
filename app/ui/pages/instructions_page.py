"""Instructions / onboarding page — a detailed first-run guide."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.ui.widgets import page_header

GUIDE_HTML = """
<style>
  h2 { color:#2f81f7; margin-top:22px; }
  h3 { color:#e6edf3; margin-top:16px; }
  p, li { color:#c9d1d9; line-height:1.55; }
  code { background:#161b22; padding:2px 6px; border-radius:4px; color:#79c0ff; }
  .tip { background:#10261a; border-left:3px solid #3fb950; padding:10px 14px;
         border-radius:6px; margin:10px 0; }
  .warn { background:#2a2113; border-left:3px solid #d29922; padding:10px 14px;
          border-radius:6px; margin:10px 0; }
  table { border-collapse:collapse; margin:8px 0; }
  td, th { border:1px solid #2a3340; padding:6px 10px; color:#c9d1d9; }
  th { background:#1a212b; }
</style>

<h2>What this app does</h2>
<p>This is a hand-off bridge between <b>documents</b> (purchase orders, receiving
slips, invoices — as PDF, Word, Excel, or scanned images) and your <b>ERP</b>,
driven by Power Automate RPA. It reads a document, extracts the fields you care
about, validates each one against the <code>NRF_REPORTS</code> warehouse, lets you
fix anything uncertain, and exports a clean dataset for the robot to key in.</p>

<h2>The five-step flow</h2>
<ol>
  <li><b>Pick a Task</b> — e.g. <i>Customer Orders</i> or <i>Receiving</i>. Each
      task defines its own required fields and validation rules.</li>
  <li><b>Drop a document</b> — the app extracts text/tables, using OCR automatically
      for scans, and AI (if enabled) for unfamiliar layouts.</li>
  <li><b>Review extraction</b> — confirm the app found every required field. If a
      layout is new, you teach it once; it remembers next time as a Template.</li>
  <li><b>Validate</b> — exact fields (like customer number) must match a real
      warehouse record; fuzzy fields (like a vendor's own item description) get a
      confidence score and candidate list you confirm.</li>
  <li><b>Export</b> — produces JSON + CSV in your exports folder for Power Automate.</li>
</ol>

<h2>Tasks — keep workflows separate</h2>
<p>Everything is scoped to a <b>Task</b>. A task is a single thing you hand to a
robot. Define a task's fields on the <b>Tasks</b> page: for each field set whether
it is required, its data type, and how to validate it:</p>
<table>
  <tr><th>Validation</th><th>Meaning</th><th>Example</th></tr>
  <tr><td><b>None</b></td><td>Accept whatever is extracted.</td><td>PO date, notes</td></tr>
  <tr><td><b>Exact</b></td><td>Must equal a real key in the warehouse.</td>
      <td>Customer number, real SKU</td></tr>
  <tr><td><b>Fuzzy</b></td><td>Free text matched to a warehouse value with a score
      you confirm.</td><td>Vendor's item description &rarr; our SKU</td></tr>
</table>

<div class="tip"><b>Customer numbers:</b> reps type the <b>old</b> account number
(BBANK2). The warehouse keys sales under the <b>new</b> number (BACCT#). Point a
customer field at table <code>BILLTO</code> and the app resolves both automatically,
and flags closed accounts (names starting with <code>*</code>).</div>

<h2>Templates — teach a layout once</h2>
<p>Documents from the same source share a structural fingerprint. The first time
you process a new layout, map its fields and save it as a <b>Template</b> for that
task. When a matching document arrives again, the app applies the saved mapping
automatically — no AI call needed.</p>

<h2>Learning — nomenclature memory</h2>
<p>When you confirm a fuzzy match (their description &rarr; our SKU), the app
remembers it for that task and field. Next time that exact description appears, it
resolves instantly with full confidence. Manage these on the Tasks page.</p>

<h2>AI extraction (optional)</h2>
<p>AI is only used as a fallback for fields with no deterministic mapping. It is
<b>off by default</b>. Enable it on Settings and store your API key — the key lives
in Windows Credential Manager, never in a file. See the Settings page for model
recommendations, costs, and trade-offs.</p>

<h2>Security &amp; best practices</h2>
<ul>
  <li>The warehouse connection is <b>read-only</b> and uses Windows authentication;
      no passwords are stored anywhere.</li>
  <li>All SQL uses parameterized queries — your document values can never inject SQL.</li>
  <li>API keys are stored in the OS secret vault, not in config or source.</li>
  <li>Be on the NRF network/VPN before validating.</li>
  <li>Always review fields marked <span style="color:#d29922">REVIEW</span> or
      <span style="color:#f85149">UNMATCHED</span> before exporting — required ones
      block export until resolved.</li>
</ul>

<h2>Power Automate hand-off</h2>
<p>Each export is a JSON file with a stable schema: <code>task</code>,
<code>ready_to_export</code>, and a <code>fields</code> object containing the
<code>resolved_value</code>, <code>status</code>, and <code>confidence</code> for
every field. Point your flow at the exports folder and branch on
<code>ready_to_export</code>.</p>

<div class="warn"><b>First run:</b> Tesseract OCR must be installed at OS level for
scanned documents. Set its path on the Settings page. Without it, native PDFs and
Office files still work fully.</div>
"""


class InstructionsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        layout.addWidget(
            page_header(
                "Instructions",
                "How the Orders RPA Bridge works — read this before your first run.",
            )
        )

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(GUIDE_HTML)
        browser.setStyleSheet(
            "QTextBrowser { background:#1a212b; border:1px solid #2a3340;"
            "border-radius:12px; padding:18px; }"
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(browser)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(scroll, 1)
