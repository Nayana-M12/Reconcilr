# Reconcilr backend

Reconcilr is a financial reconciliation backend. It imports vendor, purchase order,
invoice, and payment data, matches related records, detects and classifies
exceptions, and proposes adjustments that can be reviewed and approved.

## Tech stack

- Python 3.11
- FastAPI and Uvicorn
- SQLAlchemy 2.x and Alembic
- SQLite by default
- Pydantic Settings
- Pandas and OpenPyXL for CSV/Excel imports
- RapidFuzz for fuzzy matching
- Pytest for tests

The default database file is `backend/reconcilr.db`.

## Windows setup

From the repository root:

```powershell
cd backend
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
```

Set `DATABASE_URL` to use another SQLAlchemy-supported database. SQLite is the
default.

## Import order

Import vendors first so source records can reference existing `vendor_id` values.
The required order is:

1. `vendor`
2. `purchase_order`
3. `invoice`
4. `payment`

Use `POST /imports/{record_type}` for each import. CSV and Excel files are
supported; invalid rows are reported individually and re-imported rows are
reported as duplicates.

## Document import

Upload one or more `.pdf` (text-based) or `.txt` invoices, purchase orders, or
payment advices via `POST /import/document` (requires `analyst` or `admin` role):

- Deterministic regex/rule parsers classify the document (`invoice`,
  `purchase_order`, `payment`) and extract document number, vendor, ISO date,
  currency, `Decimal` total amount, and PO reference when present.
- Every extracted field carries provenance (`page`, exact `snippet`, and rule
  `confidence`).
- Required fields are never guessed: any document missing a required field is
  returned under `needs_review` and is **not** imported.
- Complete documents are routed through the existing `import_records` pipeline
  so deduplication and audit logging behave identically to CSV imports.
- Scanned PDFs and images require optional OCR (`EXTRACTION_OCR=1` with
  `pytesseract` installed); otherwise the API returns a clear `"OCR not enabled"`
  message under `unsupported`.

## Run the server and tests

Start the development server from `backend`:

```powershell
uvicorn app.main:app --reload
```

Run the test suite from `backend`:

```powershell
pytest
```

## Authentication, `/docs`, and demo users

All API endpoints except `GET /health` and `POST /auth/login` require a signed
Bearer JWT (`Authorization: Bearer <token>`). Roles are always derived from
the verified token, never from request bodies:

- `admin`: full access including user management
- `analyst`: import data, run reconciliation pipelines, run AI agent/suggestions
- `approver`: approve or reject proposed adjustments
- `auditor`: read-only access to dashboards, exceptions, adjustments, and audit log

Configure secrets and runtime settings via environment variables (never commit
`.env` or real passwords):

- `JWT_SECRET` — signing key for JWT tokens (required in production)
- `APP_ENV` — set to `development` to allow `/docs`, `/redoc`, and `/openapi.json` without a token (default: `production`)
- `CORS_ORIGINS` — comma-separated frontend origins (default: `http://localhost:5173,http://127.0.0.1:5173`)
- `MAX_UPLOAD_SIZE_BYTES` — maximum upload size in bytes (default: `10485760` / 10 MB)

To create demo users, set password environment variables in your shell and run
the seed script from `backend/`:

```powershell
$env:DEMO_ADMIN_PASSWORD = "<choose-a-strong-password>"
$env:DEMO_ANALYST_PASSWORD = "<choose-a-strong-password>"
$env:DEMO_APPROVER_PASSWORD = "<choose-a-strong-password>"
$env:DEMO_AUDITOR_PASSWORD = "<choose-a-strong-password>"
python -m scripts.seed_users
```

This creates (or updates) usernames `admin`, `analyst`, `approver`, and `auditor`.
In development (`APP_ENV=development`), open `http://127.0.0.1:8000/docs`, click
**Authorize**, enter a demo user's credentials, and test protected endpoints.

## Demo flow

After importing the source data, run the reconciliation workflow in this order:

1. `POST /matching/run` — create matches.
2. `POST /exceptions/run` — detect and classify exceptions.
3. `POST /adjustments/propose` — propose adjustments for applicable exceptions.
4. `GET /adjustments` — review proposed adjustments.
5. `POST /adjustments/{id}/decision` — approve or reject an adjustment.

## AI agent and evaluation

The grounded investigation agent is optional and works offline. It uses only the
read-only tools in `app/agent/tools.py`; the LLM may write explanations but
cannot create records or supply amounts. Set `LLM_API_KEY` and `LLM_MODEL` to
enable an OpenAI-compatible chat-completions client. Without those variables,
investigations use a deterministic, verified template.

Apply the agent persistence migration before using the endpoints:

```powershell
alembic upgrade head
```

Agent endpoints:

- `POST /agent/investigate` with `{"exception_id": "..."}`, or an empty body to investigate all open exceptions.
- `GET /agent/runs`
- `POST /agent/runs/{id}/accept`
- `POST /agent/runs/{id}/override`

Every tool call, verification failure, investigation, acceptance, and override
is written to the audit log. Accepting a `propose_adjustment` recommendation
uses the existing adjustment proposal and approval-step services.

### AI similarity suggestions

Similarity is suggestion-only. Offline comparisons use normalized RapidFuzz
scores; optional model-backed comparisons use `LLM_API_KEY` with `LLM_MODEL` (or
`EMBEDDING_MODEL`). Suggestions never create records, alter matching, or decide
financial outcomes.

- `POST /ai/vendor-suggestions` finds likely aliases among existing vendors.
- `POST /ai/duplicate-suggestions` finds reformatted invoice resubmissions.
- `POST /ai/suggestions/{id}/accept` and `/reject` record a human decision.

Accepted vendor aliases are stored for candidate retrieval only. Accepting a
near-duplicate creates a duplicate exception through the existing evidence and
adjustment/approval flow. All suggestions and decisions are audited, and
missing record IDs are rejected.

Run the labeled synthetic-data evaluation with:

```powershell
python evals/run_eval.py --json-out evals/report.json --markdown-out evals/report.md
```

The report includes matching precision/recall, duplicate detection rate and
false positives, exception metrics, AI similarity precision/recall,
grounded-explanation hallucination rate, unresolved correctness, and extraction
accuracy when an extraction module is present.

## Verified results

- 35 matches
- 7 exceptions
- 17 tests passing
