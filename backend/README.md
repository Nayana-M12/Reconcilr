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

## Verified results

- 35 matches
- 7 exceptions
- 17 tests passing
