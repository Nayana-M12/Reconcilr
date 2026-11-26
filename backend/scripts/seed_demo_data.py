"""Populate the active Reconcilr database with the deterministic synthetic dataset."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.database import Base, SessionLocal, engine
from app.services.importer import import_records
from app.synthetic.generator import generate


def seed_demo_data() -> dict[str, dict[str, int]]:
    backend_dir = Path(__file__).parents[1]
    data_dir = backend_dir / "data"
    if not (data_dir / "vendors.csv").exists():
        generate(data_dir, seed=42)
        invoices_path = data_dir / "invoices.csv"
        rows = [
            row
            for row in csv.DictReader(invoices_path.open(encoding="utf-8"))
            if row["id"] != "inv-000021"
        ]
        with invoices_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    Base.metadata.create_all(bind=engine)
    summary: dict[str, dict[str, int]] = {}
    with SessionLocal() as db:
        for record_type, filename in (
            ("vendor", "vendors.csv"),
            ("purchase_order", "purchase_orders.csv"),
            ("invoice", "invoices.csv"),
            ("payment", "payments.csv"),
        ):
            res = import_records(
                db,
                record_type,
                filename,
                (data_dir / filename).read_bytes(),
                actor="seed_demo_data",
            )
            summary[record_type] = {
                "imported": res["imported"],
                "duplicates": res["duplicates"],
                "rejected": res["rejected"],
            }
    return summary


if __name__ == "__main__":
    result = seed_demo_data()
    for kind, counts in result.items():
        print(f"{kind}: imported={counts['imported']}, duplicates={counts['duplicates']}, rejected={counts['rejected']}")
