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

Authentication requires `JWT_SECRET`; copy `.env.example` to `.env` and set a
long random value before starting the API. Seed demo users only from password
environment variables:

```powershell
alembic upgrade head
python scripts\seed_users.py
```

`POST /login` returns a short-lived bearer token. All other API endpoints
require that token. Roles are `admin`, `analyst`, `approver`, and `auditor`;
approval roles are taken from the token, never from request JSON. Admins manage
users through `GET/POST /users`.

When `APP_ENV=development`, open `/docs`, click **Authorize**, enter a seeded
demo user's username and password in the OAuth2 form, and click **Authorize**.
You can then try protected endpoints directly from the interactive
documentation. The default `APP_ENV=production` keeps the documentation
protected behind the same bearer-token requirement.

Set `CORS_ORIGINS` to a comma-separated list of trusted frontend origins. In
development, the default allows both `http://localhost:5173` and
`http://127.0.0.1:5173`. Credentials are enabled, so `*` is not a valid
origin value.

## Import order

Import vendors first so source records can reference existing `vendor_id` values.
The required order is:

1. `vendor`
2. `purchase_order`
3. `invoice`
4. `payment`

Use `POST /imports/{record_type}` for each import. CSV and Excel files are
supported up to the configured 10 MB limit; invalid rows are reported
individually and re-imported rows are reported as duplicates. Other extensions
are rejected. XLSX formulas are read as literal text and are never evaluated.
Uploads are processed from memory and are not retained as temporary files.

Audit logs are append-only through the API. `GET /audit` is the only audit
route; every write records the authenticated username and role. Set
`LLM_REDACT=1` to mask vendor and bank-like fields with stable placeholders in
audit data and before any LLM call.

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
