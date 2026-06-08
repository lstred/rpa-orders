# Orders RPA Bridge

A **native Windows desktop application** that turns inbound business documents —
purchase orders, receiving slips, invoices (PDF, Word, Excel, or scanned images) —
into a clean, **validated** dataset for **Power Automate RPA** to key into the ERP.

It reads a document, extracts the fields you care about, validates each one against
the `NRF_REPORTS` SQL warehouse, lets you fix anything uncertain, learns your
nomenclature, and exports a structured JSON/CSV hand-off for the robot.

Built with **Python + PySide6 (Qt)** — not a browser app, not Streamlit.

---

## Highlights

- **Multi-format ingestion** — PDF (text + tables), Word, Excel/CSV, images; automatic
  **OCR fallback** (Tesseract) for scans.
- **Flexible extraction** — deterministic templates per layout, with optional **AI**
  (Anthropic Claude / OpenAI) as a fallback for brand-new documents.
- **Warehouse validation** — *exact* matching for keys (customer numbers, real SKUs)
  and *fuzzy* matching with confidence scores for free text (e.g. a vendor's own item
  description → your SKU).
- **Learns over time** — confirm a fuzzy match once and it's remembered forever for
  that task/field. Recognize a document layout once and its mapping is reused.
- **Task-scoped** — keep *Customer Orders*, *Receiving*, etc. completely separate.
- **Secure by design** — read-only warehouse access over Windows auth, parameterized
  SQL everywhere, API keys in the OS secret vault (never in files).

---

## Quick start

```powershell
# 1. Create an environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run
python run.py
```

> **Prerequisites:** Windows, Python 3.11+, the `ODBC Driver 18 for SQL Server`, and
> access to the NRF network/VPN for warehouse validation. For scanned documents,
> install **Tesseract OCR** (OS-level) and set its path on the Settings page.

### First run

1. Open **Tasks & Fields → Add examples** to create *Customer Orders* and *Receiving*,
   or build your own task and define its fields.
2. (Optional) On **Settings**, test the warehouse connection, configure OCR, and — if
   you want AI fallback — enable it and store an API key.
3. Go to **Process Document**, pick a task, drop a file, and click **Process**.
4. Resolve any fields marked *review*/*unmatched*, click **Confirm & learn**, then
   **Export for RPA**.

---

## How it works

```
Document ──► Ingest (text/tables/OCR) ──► Recognize layout (template/fingerprint)
        ──► Extract fields (mapping or AI) ──► Validate vs NRF_REPORTS (exact/fuzzy)
        ──► You resolve & confirm ──► Learn ──► Export JSON + CSV ──► Power Automate
```

The export JSON is a stable contract:

```jsonc
{
  "schema_version": "1.0",
  "task": "Customer Orders",
  "ready_to_export": true,
  "blocking_fields": [],
  "fields": {
    "customer_number": { "resolved_value": "PROHAR", "status": "ok", "confidence": 100.0 },
    "sku":             { "resolved_value": "ABC123",  "status": "ok", "confidence": 96.0 }
  }
}
```

Point your Power Automate flow at the exports folder and branch on `ready_to_export`.

---

## AI models (optional)

AI is **off by default** and only fills fields with no saved mapping. Recommended:

| Model | Use it for | Approx. cost (per 1M tok) |
|---|---|---|
| **Claude Sonnet 4** *(default)* | best accuracy-to-cost; structured extraction | ~$3 in / $15 out |
| Claude Opus 4 | hardest / messiest layouts | ~$15 in / $75 out |
| Claude Haiku | clean, simple docs, cheapest Claude | low |
| OpenAI GPT-4o | strong alternative, vision capable | ~$2.50 in / $10 out |
| OpenAI GPT-4o-mini | very cheap, simple structured docs | ~$0.15 in / $0.60 out |

**Pros:** handles new layouts with zero setup; understands synonyms/abbreviations.
**Cons:** per-call cost, network dependency, occasional hallucination — which is why
every AI value still passes warehouse validation and your confirmation before export.
Costs are approximate and change; verify with the provider. Enabling AI sends document
text to the provider — for sensitive documents prefer deterministic templates.

---

## Security

- Warehouse access is **read-only** and uses **Windows Trusted Connection** (no stored
  passwords).
- **All** SQL uses parameterized queries; dynamic identifiers are strictly whitelisted.
- API keys are stored in **Windows Credential Manager** (via `keyring`), never in
  config or source.
- Local app data (tasks, templates, learned matches) lives under
  `%LOCALAPPDATA%/OrdersRpaBridge/`.

---

## Project layout

```
app/
  core/         config, paths, logging, security, local SQLite store, NRF connection
  ingestion/    document loader + PDF/Word/Excel/image extractors + OCR
  extraction/   AI extractor, template matcher, field extractor
  validation/   SQL lookups (exact/fuzzy), validation engine
  export/       JSON/CSV exporter (Power Automate contract)
  ui/           theme, widgets, main window, pages
run.py          launcher
CLAUDE.md       guidance for AI agents / contributors
```

See **CLAUDE.md** for architecture details and the non-negotiable rules.
