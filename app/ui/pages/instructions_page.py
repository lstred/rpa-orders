"""Instructions / onboarding page — comprehensive step-by-step guide."""
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
body { line-height: 1.6; }
h2 { color:#2f81f7; margin-top:24px; margin-bottom:6px; font-size:16px; }
h3 { color:#e6edf3; margin-top:16px; margin-bottom:4px; font-size:14px; }
p, li { color:#c9d1d9; margin:4px 0; }
li { margin-left:16px; }
b { color:#e6edf3; }
code { background:#0d1117; padding:2px 7px; border-radius:4px;
       color:#79c0ff; font-family:Consolas,monospace; font-size:12px; }
.step { background:#161b22; border-left:4px solid #2f81f7; padding:14px 18px;
        border-radius:8px; margin:14px 0; }
.step h3 { color:#2f81f7; margin-top:0; }
.tip  { background:#0f2318; border-left:4px solid #3fb950; padding:10px 14px;
        border-radius:6px; margin:10px 0; }
.warn { background:#251c0c; border-left:4px solid #d29922; padding:10px 14px;
        border-radius:6px; margin:10px 0; }
.danger { background:#200a0a; border-left:4px solid #f85149; padding:10px 14px;
          border-radius:6px; margin:10px 0; }
table { border-collapse:collapse; width:100%; margin:10px 0; }
th, td { border:1px solid #2a3340; padding:7px 12px; color:#c9d1d9; text-align:left; }
th { background:#1a212b; color:#8b949e; font-size:12px; text-transform:uppercase; }
hr { border:none; border-top:1px solid #2a3340; margin:20px 0; }
.pill-ok     { background:#3fb950; color:#0d1117; border-radius:8px; padding:2px 9px; font-size:11px; font-weight:700; }
.pill-review { background:#d29922; color:#0d1117; border-radius:8px; padding:2px 9px; font-size:11px; font-weight:700; }
.pill-bad    { background:#f85149; color:#0d1117; border-radius:8px; padding:2px 9px; font-size:11px; font-weight:700; }
</style>

<h2>What is Orders RPA Bridge?</h2>
<p>A native Windows desktop application that reads inbound business documents
(PDFs, Word files, Excel spreadsheets, scanned images) and turns them into a
clean, validated dataset that Power Automate RPA can use to key data into your ERP.</p>

<p>The pipeline is: <b>Load document → Extract fields → Validate vs. warehouse →
You resolve anything uncertain → App learns → Export JSON/CSV for Power Automate.</b></p>

<hr>

<div class="step">
<h3>Step 1 — Create a Task</h3>
<p>A <b>Task</b> is one RPA workflow (e.g. <i>Customer Orders</i>, <i>Receiving</i>).
Everything — fields, templates, learned matches, exports — is kept separate per task.</p>
<ol>
  <li>Go to <b>Tasks &amp; Fields</b> in the left sidebar.</li>
  <li>Click <b>New task</b> (or <b>Add examples</b> to get started with pre-built Customer
      Orders and Receiving tasks).</li>
  <li>Give it a clear name and description.</li>
</ol>
<div class="tip"><b>Quick start:</b> Click <b>Add examples</b> on the Tasks &amp; Fields page.
It creates fully configured Customer Orders and Receiving tasks with the correct
warehouse validation already set up. You can customise them any time.</div>
</div>

<div class="step">
<h3>Step 2 — Define fields for your task</h3>
<p>Fields are the pieces of data you want to extract (e.g. Customer Number, PO Number, SKU, Quantity).
Select a task, then use the <b>field list</b> on the left and the <b>field editor</b> on the right
to configure each one.</p>

<table>
<tr><th>Setting</th><th>What it does</th></tr>
<tr><td><b>Display name</b></td><td>Label shown during review (e.g. "Customer Number")</td></tr>
<tr><td><b>Field key</b></td><td>Machine-readable ID used in exports (auto-generated)</td></tr>
<tr><td><b>Required</b></td>
    <td>★ = must be resolved before export. Optional fields can be blank.</td></tr>
<tr><td><b>Data type</b></td><td>text, number, date, money — used for formatting/validation hints</td></tr>
<tr><td><b>Validation type</b></td><td>See table below</td></tr>
<tr><td><b>Guidance</b></td>
    <td>Description of what this field is and where to find it.
        Shown during review and passed to AI extraction.</td></tr>
</table>

<h3>Validation types explained</h3>
<table>
<tr><th>Type</th><th>Use it for</th><th>How it works</th></tr>
<tr><td><b>None</b></td>
    <td>Dates, notes, free-text reference numbers</td>
    <td>Whatever is extracted is accepted as-is. No warehouse lookup.</td></tr>
<tr><td><b>Exact</b></td>
    <td>Customer account numbers, real SKUs (when the doc uses your exact code)</td>
    <td>Must match an actual value in the warehouse column you specify.
        Customer numbers resolve both old BBANK2 and new BACCT# automatically.</td></tr>
<tr><td><b>Fuzzy</b></td>
    <td>When the document uses a vendor's description instead of your SKU</td>
    <td>Similarity-scored search against the warehouse.
        Returns ranked candidates for you to confirm. Confirmations are remembered.</td></tr>
</table>

<h3>SQL lookup configuration (for Exact and Fuzzy)</h3>
<p>Select the <b>SQL Table</b> to search (e.g. <code>ITEM</code>, <code>BILLTO</code>),
the <b>Value column</b> that should be returned to Power Automate (e.g. <code>ItemNumber</code>,
<code>BACCT#</code>), and check the <b>Match columns</b> — the columns to search against
the extracted text.</p>

<div class="tip">
  <b>Customer numbers:</b> Table = <code>BILLTO</code>, Value col = <code>BACCT#</code>,
  Match cols = <code>BACCT#</code> + <code>BBANK2</code>.<br>
  Reps always type the <b>old number (BBANK2)</b> — e.g. "51149".
  The warehouse stores the <b>new number (BACCT#)</b> — e.g. "PROHAR".
  Checking both means either one resolves correctly.<br>
  Closed accounts (BNAME starts with *) are flagged automatically.
</div>
<div class="tip">
  <b>SKU / Item:</b> Table = <code>ITEM</code>, Value col = <code>ItemNumber</code>,
  Match cols = <code>ItemNumber</code> + <code>INAME</code> (description).<br>
  Set Validation = <b>Fuzzy</b> when the document uses vendor descriptions
  instead of your item numbers.
</div>

<p>Click <b>Save field changes</b> for each field, then <b>Save task</b> when done.
Drag fields to reorder them.</p>
</div>

<div class="step">
<h3>Step 3 — Process a document</h3>
<ol>
  <li>Go to <b>Process Document</b>.</li>
  <li>Select your <b>Task</b> from the dropdown.</li>
  <li><b>Drop a document</b> onto the window (or click Browse):
      PDF, Word (.docx), Excel (.xlsx/.csv), or image (.png/.jpg/.tif).</li>
  <li>Click <b>Process</b>. The pipeline bar shows you what's happening:
      <br>① Load → ② Extract → ③ Validate → ④ Review → ⑤ Export</li>
</ol>

<h3>What the app does automatically</h3>
<ul>
  <li><b>Template matching:</b> If this document layout has been seen before,
      the saved field locators are applied automatically.</li>
  <li><b>OCR fallback:</b> For scanned pages (image-only PDF or image files),
      Tesseract OCR is used automatically if it's installed (set path in Settings).</li>
  <li><b>AI extraction (optional):</b> If no template matches and AI is enabled,
      the app asks the AI to find field values in the document text.</li>
  <li><b>Learned matches:</b> If you've confirmed a fuzzy match before
      (e.g. "Carpet Berber" → <code>CBBRN</code>), it resolves instantly.</li>
</ul>

<p>After processing, you see the <b>document text on the left</b> and
<b>field results on the right</b>. Each field has a status:</p>
<table>
<tr>
  <td><span class="pill-ok">OK</span></td>
  <td>Confirmed — exact match, high-confidence fuzzy, or learned. Safe to export.</td>
</tr>
<tr>
  <td><span class="pill-review">REVIEW</span></td>
  <td>Fuzzy match found but below the auto-accept threshold. Confirm or choose a different candidate.</td>
</tr>
<tr>
  <td><span class="pill-bad">UNMATCHED</span></td>
  <td>Could not find a warehouse match. You need to manually select the correct value.</td>
</tr>
<tr>
  <td><span class="pill-bad">MISSING</span></td>
  <td>Required field — no value was found in the document at all.</td>
</tr>
<tr>
  <td><span class="pill-ok" style="background:#3a4252;color:#8b949e;">SKIPPED</span></td>
  <td>Optional field not present.</td>
</tr>
</table>
</div>

<div class="step">
<h3>Step 4 — Resolve and teach</h3>
<p>Any field that isn't <span class="pill-ok">OK</span> needs attention before export.
Required fields with unresolved status <b>block</b> the export.</p>

<h3>How to resolve a field</h3>
<ol>
  <li><b>Click "🔍 Find" next to any unresolved field</b> — a dialog opens showing
      the full document text. Use the search box to find the value, select it, and
      click <b>Use selected text</b>. The anchor label is auto-detected.
      Check <i>Save anchor pattern</i> to make the app find it automatically next time.</li>
  <li><b>Type directly</b> in the <i>Resolved value</i> column — for simple corrections.</li>
  <li><b>Pick a candidate</b> from the <i>Candidates / options</i> dropdown for fuzzy fields —
      ranked matches from the warehouse.</li>
</ol>

<h3>Teaching the app</h3>
<p>When you click <b>Confirm &amp; learn matches</b>:</p>
<ul>
  <li>All your edits are confirmed (status → OK).</li>
  <li>Fuzzy match confirmations are saved to <b>Learned Matches</b> — the app will
      resolve that text automatically next time (e.g. "12oz Berber" always maps to
      your SKU code).</li>
  <li>Anchors saved during  Find in document  are stored in the layout's Template.</li>
</ul>

<h3>Saving a template</h3>
<p>Click <b>Save as template</b> after processing a new document layout.
Give it the name of the source (e.g. "MX Vendor", "Customer XYZ Orders").
Next time a document with the same structure arrives, the app automatically
applies all the saved field locators — no mapping needed.</p>
</div>

<div class="step">
<h3>Step 5 — Export for Power Automate</h3>
<p>Click <b>Export for RPA</b> (only enabled when all required fields are OK).</p>
<p>Two files are written to your exports folder:</p>
<ul>
  <li><b>JSON</b> — the canonical hand-off contract. Contains
      <code>ready_to_export</code>, <code>task</code>, and a <code>fields</code> object
      with <code>resolved_value</code>, <code>status</code>, and <code>confidence</code>
      for every field.</li>
  <li><b>CSV</b> — flat one-row-per-field table for Power Automate table actions.</li>
</ul>
<p>In Power Automate, point your flow at the exports folder and
branch on <code>ready_to_export</code>. Use the <code>resolved_value</code> of each
field to key data into the ERP.</p>
</div>

<hr>

<h2>Using AI extraction</h2>
<p>AI is <b>off by default</b> and only used when no template mapping exists for a field.
Enable it on the <b>Settings</b> page:</p>
<ol>
  <li>Choose a provider: <b>Anthropic</b> (Claude) or <b>OpenAI</b> (GPT).</li>
  <li>Enter your API key — it is stored in Windows Credential Manager, never in files.</li>
  <li>Enable the toggle and click Save.</li>
</ol>

<table>
<tr><th>Model</th><th>Best for</th><th>Approx. cost (per 1M tokens)</th></tr>
<tr><td><b>Claude Sonnet 4</b> ⭐ recommended</td>
    <td>Best accuracy-to-cost; understands complex document layouts</td>
    <td>~$3 in / $15 out</td></tr>
<tr><td>Claude Opus 4</td><td>Hardest or messiest documents</td><td>~$15 in / $75 out</td></tr>
<tr><td>Claude Haiku</td><td>Simple, clean documents — cheapest Claude</td><td>Very low</td></tr>
<tr><td>GPT-4o</td><td>Strong alternative, vision capable</td><td>~$2.50 in / $10 out</td></tr>
<tr><td>GPT-4o-mini</td><td>Simple structured docs, lowest cost</td><td>~$0.15 in / $0.60 out</td></tr>
</table>

<div class="warn">Enabling AI sends document text to the provider's API.
For confidential documents, use deterministic templates instead — they are free and private.</div>

<hr>

<h2>Troubleshooting</h2>

<table>
<tr><th>Problem</th><th>Solution</th></tr>
<tr><td>Processing shows no results / empty table</td>
    <td>The task has no fields configured. Go to Tasks &amp; Fields, select the task,
        add fields, and save.</td></tr>
<tr><td>Validation results show UNMATCHED for everything</td>
    <td>The app is not connected to NRF_REPORTS. Confirm you are on the NRF network or VPN,
        then go to Settings and click Test connection.</td></tr>
<tr><td>Scanned PDF extracts no text</td>
    <td>Install Tesseract OCR (OS-level install from github.com/UB-Mannheim/tesseract/wiki),
        then set its path in Settings.</td></tr>
<tr><td>AI extraction returns wrong values</td>
    <td>All AI values still pass warehouse validation. Use Find in document to correct a value,
        then click Confirm &amp; learn — the correction is remembered.</td></tr>
<tr><td>Field always shows REVIEW / low confidence</td>
    <td>The fuzzy threshold may be too high. Lower it in Settings → Fuzzy thresholds.
        Or confirm the match once — it becomes a Learned Match and resolves instantly next time.</td></tr>
<tr><td>"Task has no fields" warning on Process page</td>
    <td>Go to Tasks &amp; Fields, select the task, add at least one field, and click Save task.</td></tr>
</table>

<hr>

<h2>Best practices</h2>
<ul>
  <li><b>Set up templates early.</b> Process each document source once, map any
      unresolved fields using Find in document, and save as a template. Future
      documents from that source need zero manual work.</li>
  <li><b>Use Confirm &amp; learn consistently.</b> Every confirmed fuzzy match makes
      the app smarter. After a few weeks, most documents resolve fully automatically.</li>
  <li><b>One task per robot workflow.</b> Do not mix Customer Orders and Receiving in
      one task — they go to different robots doing different things in the ERP.</li>
  <li><b>Required vs optional.</b> Only mark a field Required if the robot actually
      needs it to proceed. Optional fields don't block export.</li>
  <li><b>Keep AI as a fallback.</b> Deterministic templates (free, fast, private) are
      always preferred. AI fills gaps when no template exists for a field.</li>
  <li><b>Be on the VPN.</b> Warehouse validation requires the NRF network. On Settings,
      test the connection before processing documents remotely.</li>
</ul>
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
                "Complete guide to setting up, processing documents, and exporting for Power Automate.",
            )
        )

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(GUIDE_HTML)
        browser.setStyleSheet(
            "QTextBrowser { background:#1a212b; border:1px solid #2a3340;"
            "border-radius:12px; padding:20px; }"
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(browser)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(scroll, 1)
