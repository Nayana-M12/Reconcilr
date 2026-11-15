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

## Run the server and tests

Start the development server from `backend`:

```powershell
uvicorn app.main:app --reload
```

Run the test suite from `backend`:

```powershell
pytest
```

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
