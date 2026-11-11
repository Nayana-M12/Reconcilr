import json

from app.synthetic.generator import generate


def test_generator_is_reproducible(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    generate(first, seed=42, vendor_count=3, invoice_count=8)
    generate(second, seed=42, vendor_count=3, invoice_count=8)
    assert (first / "invoices.csv").read_bytes() == (second / "invoices.csv").read_bytes()
    assert json.loads((first / "ground_truth.json").read_text()) == json.loads((second / "ground_truth.json").read_text())
