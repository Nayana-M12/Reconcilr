# Reconcilr backend (Phase 1)

Phase 1 provides the persistence and ingestion foundation for financial reconciliation:

- SQLAlchemy 2.x models for vendors, invoices, purchase orders, payments, matches, exceptions, evidence, adjustments, approvals, and append-only audit logs.
- Alembic migration `0001_initial`.
- Deterministic synthetic CSV fixtures with reproducible injected errors and `ground_truth.json`.
- CSV/Excel imports through `POST /imports/{record_type}` (`vendor`, `purchase_order`, `invoice`, or `payment`). Invalid rows are reported individually.
- Re-imported rows are skipped and reported as duplicates with the existing record ID; the response includes a `duplicates` count.
- Decimal money handling and invoice dedupe hashes based on normalized vendor, invoice number, amount, and invoice date.

Import vendors first so source records can reference existing `vendor_id` values:

1. `POST /imports/vendor`
2. `POST /imports/purchase_order`
3. `POST /imports/invoice`
4. `POST /imports/payment`

## Setup

```powershell
cd backend
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
```

Set `DATABASE_URL` to use another SQLAlchemy-supported database. SQLite is the default.

## Run

```powershell
uvicorn app.main:app --reload
python -m app.synthetic.generator --seed 42 --output-dir synthetic_data
pytest
```

Phase 2 should add deterministic matching tiers, exception detectors/classification, evidence and adjustment services, approval routing, and their audit coverage.
