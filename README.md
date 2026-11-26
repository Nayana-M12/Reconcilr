# Reconcilr

**Financial Reconciliation and Exception Resolution System** with deterministic `Decimal` accounting math, evidence-backed exceptions, a grounded AI investigation agent, document extraction with provenance, and role-based access control.

## Workflow

1. **Import** — Load vendors, purchase orders, invoices, and payments via standard CSV/Excel (`POST /imports/{record_type}`), interactive column-mapped CSV/Excel (`POST /import/preview` + `POST /import/mapped`), or deterministic PDF/TXT document extraction (`POST /import/document`).
2. **Match** — Run ordered deterministic matching tiers (`exact` → `tolerance` → `fuzzy`) via `POST /matching/run`.
3. **Detect exceptions** — Flag 9 exception types (`DUPLICATE_INVOICE`, `DUPLICATE_PAYMENT`, `PARTIAL_PAYMENT`, `OVERPAYMENT`, `MISSING_PO`, `MISSING_PAYMENT`, `DATE_GAP`, `AMOUNT_MISMATCH`, `VENDOR_MISMATCH`) via `POST /exceptions/run`.
4. **Collect evidence** — Attach real database record-ID pointers (`record_type`, `record_id`, `note`) to every exception so no transaction is ever invented.
5. **Propose adjustments** — Calculate adjustment amounts strictly with `Decimal` arithmetic (`POST /adjustments/propose`).
6. **Route approval** — Enforce tiered approvals (`POST /adjustments/{id}/decision`) with `409 Conflict` protection on repeat or out-of-order decisions and an append-only audit log (`GET /audit`).

## Grounded AI Design

- **Numbers never come from the LLM:** All monetary math runs in deterministic Python `Decimal` services. The frontend keeps money values as strings and never converts them to floats.
- **Read-only bounded tools:** The investigation agent (`backend/app/agent/`) runs a bounded tool-calling loop over read-only database tools (`get_exception`, `get_invoice`, `get_payment`, `get_purchase_order`, `search_payments`, `calculate_difference`, `find_duplicates`).
- **Post-hoc verification:** Every claim and cited record ID is verified against the database and the run's tool outputs (`backend/app/agent/verifier.py`). Any unverified ID or literal number fails verification, retries once, and falls back to a verified deterministic template (`source: "template"`). `"unresolved"` is always an accepted verdict when no counterpart exists.
- **Suggestion-only similarity:** Vendor alias and near-duplicate suggestions (`POST /ai/vendor-suggestions`, `POST /ai/duplicate-suggestions`) never create records or modify matching outcomes without human acceptance.
- **Offline-first:** Works completely offline without `LLM_API_KEY`; set `LLM_API_KEY` and `LLM_MODEL` in your environment to enable an OpenAI-compatible model.

## Security Model

- **Authentication:** `bcrypt` password hashing + HS256 signed JWT Bearer tokens (`POST /auth/login`, `GET /auth/me`). Tokens are stored in memory + `sessionStorage` on the frontend (never `localStorage`).
- **Token-derived RBAC:** Every data endpoint requires a valid token; roles (`admin`, `analyst`, `approver`, `auditor`) are always read from the verified token and never from request bodies:
  - `admin` — full access including user management (`/admin/users`)
  - `analyst` — import data, run pipelines, run/review agent investigations
  - `approver` — approve or reject proposed adjustments
  - `auditor` — read-only access across overview, exceptions, adjustments, evaluation, and audit log
- **Safe account onboarding:** Public `POST /auth/request-access` is IP rate-limited, requires a 12+ character password, returns a generic response that never discloses account existence, creates an inactive `pending` account with no role, and requires admin approval before login. The last remaining active admin cannot be demoted or deactivated.
- **Upload & API hardening:** Strict file extension & size limits (`MAX_UPLOAD_SIZE_BYTES`), spreadsheet formulas read as text, explicit `CORS_ORIGINS`, security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`), `/docs` gated to `APP_ENV=development`, and an append-only audit log.

## Running Locally

### 1. Backend

```powershell
cd backend
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
```

Create demo users (set passwords via environment variables; never commit real passwords):

```powershell
$env:DEMO_ADMIN_PASSWORD = "<choose-a-strong-password>"
$env:DEMO_ANALYST_PASSWORD = "<choose-a-strong-password>"
$env:DEMO_APPROVER_PASSWORD = "<choose-a-strong-password>"
$env:DEMO_AUDITOR_PASSWORD = "<choose-a-strong-password>"
python -m scripts.seed_users
```

(Optional) Load the synthetic demo dataset into the database so the UI immediately has records to reconcile:

```powershell
python -m scripts.seed_demo_data
```

Start the API server:

```powershell
$env:APP_ENV = "development"
$env:JWT_SECRET = "<choose-a-32+-char-random-secret>"
python -m uvicorn app.main:app --reload
```

### 2. Frontend

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`, click **Open app**, and sign in at `/login` with one of your seeded demo accounts (e.g. `analyst` to import & run pipelines, `approver` to approve adjustments, `admin` to manage users).

## Tests & Evaluation

```powershell
# Backend tests and lint (from backend/ with venv active)
pytest -q
ruff check .

# Regenerate evaluation report
python evals/run_eval.py --json-out evals/report.json --markdown-out evals/report.md

# Frontend typecheck and production build (from frontend/)
npm run build
```

## Latest Verified Evaluation Results

| Metric | Result |
| --- | ---: |
| Matching precision | `1.0` (35 / 35) |
| Matching recall | `1.0` (35 / 35) |
| Exception detection (all 7 planted types) | `1.0` precision / `1.0` recall |
| Duplicate detection rate | `1.0` (`0.0` false positives) |
| AI similarity (`vendor_aliases`, `near_duplicates`) | `1.0` precision / `1.0` recall |
| Agent hallucination rate | `0.0` |
| Unresolved correctness | `1.0` |
| Document extraction accuracy (all 7 fields) | `1.0` |

## Screenshots

<!-- Replace placeholders below with screenshots from your local session -->
- **Landing & Overview Dashboard:** `docs/screenshots/overview.png` _(placeholder)_
- **Import & Document Extraction Needs Review:** `docs/screenshots/import.png` _(placeholder)_
- **Exceptions Drawer with Grounded AI Agent:** `docs/screenshots/exceptions-agent.png` _(placeholder)_
- **Adjustments Approval & Evaluation Metrics:** `docs/screenshots/evaluation.png` _(placeholder)_
