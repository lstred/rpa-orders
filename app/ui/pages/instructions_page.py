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
Required ★ fields with unresolved status <b>block</b> the export.</p>

<h3>Three ways to resolve a field</h3>
<ol>
  <li><b>🔍 Find (inline)</b> — click the blue <b>Find</b> button next to the field.
      A banner appears above the document text on the left:
      <i>"Finding: [Field] — select the value below, then click Use selection."</i><br>
      Click and drag over the value in the document, click <b>✔ Use selection</b>.
      You're then asked whether to save an anchor so the app finds it automatically
      next time — this is how you teach the app new document layouts.</li>
  <li><b>Type directly</b> in the <i>Resolved value</i> column — the status updates live.</li>
  <li><b>Pick from Candidates</b> — fuzzy warehouse matches ranked by similarity;
      selecting one copies it to the Resolved value column.</li>
</ol>

<div class="tip"><b>Semi-structured documents</b> (e.g. items with a heading then
details below it): use <b>Find</b> for each field, select the value, and save the
anchor (the label/heading just before the value). Once all anchors are saved, future
documents from the same source are handled automatically.</div>

<h3>Teaching the app</h3>
<p>Click <b>✔ Confirm &amp; learn</b>:</p>
<ul>
  <li>Applies all edits (everything becomes OK)</li>
  <li>Saves fuzzy-match confirmations to memory — next time the same vendor
      description appears, it resolves instantly</li>
</ul>

<h3>Saving a layout template</h3>
<p>Click <b>💾 Save layout</b> after processing a new source for the first time.
Next time a document with the same structure arrives, all saved anchors and field
patterns are applied automatically — no manual work.</p>
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

<h3>How to know if AI is helping</h3>
<p>Look at the <b>AI badge</b> in the top-right of the Process Document page:</p>
<table>
<tr><td><b>🤖 AI: Anthropic Claude ✓</b> (green)</td>
    <td>AI is configured and ready — key is saved, model is set.</td></tr>
<tr><td><b>🤖 AI: standby</b> (blue)</td>
    <td>AI is on but wasn't needed this run — a saved template or anchor handled all fields.
        This is the best outcome: fast, free, and private.</td></tr>
<tr><td><b>🤖 AI: filled 3 field(s)</b> (bright green)</td>
    <td>AI actively found values for those fields this run. Hover over cells in the
        <i>Extracted</i> column to see which ones used AI vs. template.</td></tr>
<tr><td><b>🤖 AI: Off</b> (grey)</td>
    <td>AI is disabled. Only saved templates and anchor patterns are used.</td></tr>
</table>

<div class="tip"><b>AI is a fallback, not the primary tool.</b>
The order of preference is:<br>
<b>① Saved anchor/template</b> (free, instant, private) →
<b>② Learned match memory</b> (free, instant) →
<b>③ AI</b> (costs API credits, but finds things templates haven't learned yet).<br>
Once you teach the app a layout by saving anchors, AI won't be needed for that document source again.</div>

<h3>How to enable AI</h3>
<ol>
  <li>Go to <b>Settings</b>.</li>
  <li>Choose a provider: <b>Anthropic</b> (Claude) or <b>OpenAI</b> (GPT).</li>
  <li>Enter your API key — stored in Windows Credential Manager, never in source files.</li>
  <li>Check <b>Enable AI extraction</b> and click <b>Save AI settings</b>.</li>
</ol>

<table>
<tr><th>Model</th><th>Best for</th><th>Approx. cost (per 1M tokens)</th></tr>
<tr><td><b>Claude Sonnet 4</b> ⭐ recommended</td>
    <td>Best accuracy-to-cost; understands complex document layouts</td>
    <td>~$3 in / $15 out</td></tr>
<tr><td>Claude Opus 4</td><td>Hardest or messiest documents</td><td>~$15 in / $75 out</td></tr>
<tr><td>Claude Haiku</td><td>Simple, clean documents — cheapest Claude</td><td>Very low</td></tr>
<tr><td>GPT-4o</td><td>Strong alternative; also handles images</td><td>~$2.50 in / $10 out</td></tr>
<tr><td>GPT-4o-mini</td><td>Simple structured docs, lowest cost</td><td>~$0.15 in / $0.60 out</td></tr>
</table>

<div class="warn">Enabling AI sends document text to the provider's API.
For confidential documents, use saved templates and anchors instead — they are free and private.</div>

<h2>Finding your exported files</h2>
<p>All exported files are saved to:</p>
<p><code>Documents\Orders RPA Bridge\Exports</code></p>
<p>This is your normal Windows Documents folder — open it in Explorer any time.
You can also:</p>
<ul>
  <li>After export: click <b>📂 Open exports folder</b> or <b>👁 View in Exports</b>
      (shown in the Process page after a successful export).</li>
  <li>Go to the <b>Exports</b> page (sidebar) to browse and preview all past exports.</li>
  <li>The <b>Dashboard</b> shows the exports folder path and a quick-open button.</li>
</ul>

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
    <td>All AI values still pass warehouse validation. Use Find to correct a value,
        then click Confirm &amp; learn — the correction is remembered forever.</td></tr>
<tr><td>Field always shows REVIEW / low confidence</td>
    <td>The fuzzy threshold may be too high. Lower it in Settings → Fuzzy thresholds.
        Or confirm the match once — it becomes a Learned Match and resolves instantly next time.</td></tr>
<tr><td>"Task has no fields" warning on Process page</td>
    <td>Go to Tasks &amp; Fields, select the task, add at least one field, and click Save task.</td></tr>
<tr><td>Can't find exported files</td>
    <td>Go to Exports in the sidebar, or click the
        <b>📂 Open exports folder</b> button on the Dashboard.
        Files are in Documents\Orders RPA Bridge\Exports.</td></tr>
<tr><td>AI badge shows "standby" even though AI is enabled</td>
    <td>This is correct — a saved template or anchor handled all fields this time.
        AI only runs when there's no other way to find a value. This saves API costs.</td></tr>
</table>

<hr>

<h2>Best practices</h2>
<ul>
  <li><b>Set up templates early.</b> Process each document source once, map any
      unresolved fields using Find, and save as a template. Future
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
