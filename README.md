# Reconcilr

## Financial Reconciliation and Exception Resolution System

Reconcilr reconciles invoices, purchase orders, and payments to identify transaction mismatches. It explains exceptions with supporting evidence and routes proposed adjustments for approval.

## Workflow

Import invoices, POs, and payments → match transactions → detect exceptions → collect evidence → propose adjustments → route approval.

## Key rules

- Matching and calculations are deterministic.
- `Decimal` is used for money.
- Every exception is backed by real record IDs.
- The audit log is append-only.

## Tech stack

Python, FastAPI, SQLAlchemy, Alembic, SQLite, pandas, RapidFuzz, and pytest.

## Verified results

- 35 matches
- 7 exceptions detected: 0 missed, 0 false positives
- 17 tests passing

See the [backend README](backend/README.md) for setup instructions and the demo flow.