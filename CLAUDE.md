# CLAUDE.md

Guidance for Claude / AI agents working in this repository.

## What this project is

**Orders RPA Bridge** — a native Windows desktop application (Python + PySide6) that
turns inbound business documents (PDF, Word, Excel, scanned images) into a clean,
validated dataset for **Power Automate RPA** to key into the ERP.

Pipeline: **load document → recognize layout → extract fields → validate against the
`NRF_REPORTS` SQL warehouse → user resolves anything uncertain → learn → export JSON/CSV.**

Everything is scoped to a **Task** (e.g. *Customer Orders*, *Receiving*) so unrelated
RPA workflows stay separate.

## Hard rules (do not break)

1. **Never put user/document values into SQL via f-strings.** Always use SQLAlchemy
   `text()` with `:name` parameters. SQL *identifiers* (table/column names) that are
   dynamic must go through `app/validation/sql_lookups._safe_ident` (whitelist only).
2. **Secrets never touch source, config, or the DB.** API keys live in the OS vault
   via `app/core/security.py` (keyring → Windows Credential Manager).
3. **The warehouse is read-only.** This app only SELECTs from `NRF_REPORTS`. Never
   write to it.
4. **Not Streamlit, not a browser app.** UI is PySide6 (native Qt). Keep it that way.
5. **Do not block the UI thread.** Long work (I/O, SQL, AI) runs in a `QThread`
   worker — see `app/ui/pages/process_page.py::PipelineWorker`.

## NRF_REPORTS warehouse — verified ground truth

- Server `NRFVMSSQL04`, DB `NRF_REPORTS`, **Windows Trusted Connection only**,
  `ODBC Driver 18 for SQL Server`, `Encrypt=no`. Must be on NRF network/VPN.
- Connection lives in `app/core/database.py` (`read_dataframe`, `test_connection`).

Key field facts the validation layer relies on:

| Concept | Column / Table | Gotcha |
|---|---|---|
| Customer (new key) | `BILLTO.BACCT#` | warehouse keys sales here |
| Customer (old #) | `BILLTO.BBANK2` | **reps type THIS**; resolve both |
| Closed account | `BILLTO.BNAME` starts with `*` | flag, don't re-engage |
| SKU | `ITEM.ItemNumber` | fuzzy-match descriptions to this |
| SKU description | `ITEM.INAME` | fuzzy haystack |
| Active item | `ITEM.IINVEN = 'Y'` | filter for fuzzy candidates |
| Revenue | `_ORDERS.ENTENDED_PRICE_NO_FUNDS` | **permanent typo: ENTENDED** |
| Inventory flag | `_ORDERS.N_NOT_INVENTORY = 'Y'` | **backwards: 'Y' = IS inventory** |
| Customer sales | `_ORDERS.ACCOUNT#I > 1` | `=1` is a warehouse PO |
| Invoiced | `_ORDERS.INVOICE# > 0` | column is VARCHAR — `TRY_CONVERT` |
| Dates | `*_YYYYMMDD` | integer YYYYMMDD, parse in Python |

Always `LEFT JOIN dbo.ITEM` (never INNER) so custom/direct-ship items aren't dropped.
The full warehouse reference is stored in the agent's repo memory (`nrf_reports_db.md`).

## Architecture map

```
app/
  core/         config, paths, logging, security (keyring), local_store (SQLite), database (NRF)
  ingestion/    document_loader (dispatch) + pdf/docx/excel/image extractors + ocr
  extraction/   ai_extractor (Anthropic/OpenAI), template_matcher, field_extractor
  validation/   sql_lookups (exact/fuzzy, safe idents), validator (status engine)
  export/       exporter (JSON + CSV hand-off contract)
  ui/           theme, widgets, main_window, pages/*
```

- **Local app state** (tasks, fields, templates, mappings, learned matches, doc log)
  is SQLite under `%LOCALAPPDATA%/OrdersRpaBridge/` — see `app/core/local_store.py`.
  This is separate from `NRF_REPORTS`.
- **Learning:** confirmed fuzzy matches are stored in `learned_matches` and short-circuit
  future validation (`validator.validate_extraction` checks `recall_match` first).
- **Templates:** `document_loader.compute_fingerprint` produces a structural signature;
  `template_matcher.best_template` reuses saved field mappings for known layouts.

## Validation status model (`app/validation/validator.py`)

`ok` (confirmed/exact/learned) · `review` (fuzzy, needs confirm) · `unmatched` ·
`missing` (required, no value) · `skipped`. A field is **blocking** when it is
required and not `ok`; export is refused while any blocking field remains.

## Export contract (`app/export/exporter.py`)

JSON with `schema_version`, `task`, `ready_to_export`, `blocking_fields`, and a
`fields` object of `{resolved_value, status, confidence, ...}` per field. Power
Automate branches on `ready_to_export`. Keep this schema stable; bump
`schema_version` on breaking changes.

## Running

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

Tesseract OCR is an OS-level install (only needed for scanned/image docs); set its
path on the Settings page.

## Conventions

- Optional heavy libs (fitz, pdfplumber, docx, openpyxl, pytesseract, anthropic,
  openai) are imported lazily inside functions so the app still starts if one is
  missing. Keep this pattern.
- Prefer deterministic extraction (template mappings) over AI; AI is a fallback and
  is off by default.
- Every AI-extracted value must still pass warehouse validation + user confirmation
  before it can be exported.
