import argparse
import csv
import json
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from faker import Faker


def _id(prefix: str, number: int) -> str:
    return f"{prefix}-{number:06d}"


def generate(output_dir: str | Path, seed: int = 0, vendor_count: int = 5, invoice_count: int = 20) -> dict:
    rng = random.Random(seed)
    fake = Faker()
    Faker.seed(seed)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    vendors = [{"id": _id("ven", index), "name": fake.company(), "normalized_name": ""} for index in range(vendor_count)]
    for vendor in vendors:
        vendor["normalized_name"] = "".join(c for c in vendor["name"].lower() if c.isalnum())
    purchase_orders: list[dict] = []
    invoices: list[dict] = []
    payments: list[dict] = []
    ground_truth: list[dict] = []
    base_date = date(2026, 1, 1)
    for index in range(invoice_count):
        vendor = vendors[index % vendor_count]
        amount = Decimal(rng.randrange(1000, 10000)) / 100
        invoice_date = base_date + timedelta(days=index)
        po_id, invoice_id, payment_id = _id("po", index), _id("inv", index), _id("pay", index)
        po_number = f"PO-{index + 1:05d}"
        invoice_number = f"INV-{index + 1:05d}"
        purchase_orders.append(
            {
                "id": po_id, "vendor_id": vendor["id"], "vendor_name": vendor["name"],
                "po_number": po_number, "amount": str(amount), "currency": "USD",
                "order_date": invoice_date.isoformat(),
            }
        )
        invoices.append(
            {
                "id": invoice_id, "vendor_id": vendor["id"], "vendor_name": vendor["name"],
                "invoice_number": invoice_number, "po_number": po_number, "amount": str(amount),
                "currency": "USD", "invoice_date": invoice_date.isoformat(),
                "due_date": (invoice_date + timedelta(days=30)).isoformat(),
            }
        )
        payments.append(
            {
                "id": payment_id, "vendor_id": vendor["id"], "vendor_name": vendor["name"],
                "reference": f"PAY-{index + 1:05d}", "amount": str(amount), "currency": "USD",
                "payment_date": (invoice_date + timedelta(days=7)).isoformat(),
            }
        )
    def inject(index: int, error_type: str, **values: str) -> None:
        ground_truth.append({"type": error_type, "record_ids": values})

    duplicate = dict(invoices[0])
    duplicate["id"] = _id("inv", invoice_count)
    invoices.append(duplicate)
    inject(0, "DUPLICATE_INVOICE", invoice_id=invoices[0]["id"], duplicate_invoice_id=duplicate["id"])
    short_index = 1
    payments[short_index]["amount"] = str(Decimal(payments[short_index]["amount"]) - Decimal("10.00"))
    inject(short_index, "PARTIAL_PAYMENT", invoice_id=invoices[short_index]["id"], payment_id=payments[short_index]["id"])
    over_index = 2
    payments[over_index]["amount"] = str(Decimal(payments[over_index]["amount"]) + Decimal("12.00"))
    inject(over_index, "OVERPAYMENT", invoice_id=invoices[over_index]["id"], payment_id=payments[over_index]["id"])
    missing_po = 3
    invoices[missing_po]["po_number"] = ""
    inject(missing_po, "MISSING_PO", invoice_id=invoices[missing_po]["id"])
    missing_payment = 4
    payments.pop(missing_payment)
    inject(missing_payment, "MISSING_PAYMENT", invoice_id=invoices[missing_payment]["id"])
    typo = 5
    invoices[typo]["vendor_name"] = invoices[typo]["vendor_name"].replace(" ", "x", 1)
    inject(typo, "VENDOR_NAME_TYPO", invoice_id=invoices[typo]["id"], vendor_id=invoices[typo]["vendor_id"])
    date_gap = 6
    date_gap_payment = next(payment for payment in payments if payment["id"] == f"pay-{date_gap:06d}")
    date_gap_payment["payment_date"] = (base_date + timedelta(days=90)).isoformat()
    inject(date_gap, "DATE_GAP", invoice_id=invoices[date_gap]["id"], payment_id=date_gap_payment["id"])
    _write_csv(output / "vendors.csv", vendors)
    _write_csv(output / "purchase_orders.csv", purchase_orders)
    _write_csv(output / "invoices.csv", invoices)
    _write_csv(output / "payments.csv", payments)
    ground_truth_path = output / "ground_truth.json"
    ground_truth_path.write_text(json.dumps({"seed": seed, "errors": ground_truth}, indent=2), encoding="utf-8")
    return {"output_dir": str(output), "ground_truth": ground_truth}


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic reconciliation fixtures")
    parser.add_argument("--output-dir", default="synthetic_data")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    generate(args.output_dir, args.seed)


if __name__ == "__main__":
    main()
