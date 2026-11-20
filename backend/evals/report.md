# Reconcilr evaluation

| Metric | Value |
| --- | --- |
| Matching precision | 1.0 |
| Matching recall | 1.0 |
| Duplicate detection rate | 1.0 |
| Duplicate false positives | 0.0 |
| Hallucination rate | 0.0 |
| Unresolved correctness | 1.0 |
| Extraction accuracy | 1.0 (evaluated) |

## Exception detection by type

| Type | Expected | Detected | Precision | Recall |
| --- | ---: | ---: | ---: | ---: |
| DATE_GAP | 1 | 1 | 1.0 | 1.0 |
| DUPLICATE_INVOICE | 1 | 1 | 1.0 | 1.0 |
| MISSING_PAYMENT | 1 | 1 | 1.0 | 1.0 |
| MISSING_PO | 1 | 1 | 1.0 | 1.0 |
| OVERPAYMENT | 1 | 1 | 1.0 | 1.0 |
| PARTIAL_PAYMENT | 1 | 1 | 1.0 | 1.0 |
| VENDOR_MISMATCH | 1 | 1 | 1.0 | 1.0 |

## AI similarity suggestions

| Suggestion type | Precision | Recall | Expected | Detected |
| --- | ---: | ---: | ---: | ---: |
| vendor_aliases | 1.0 | 1.0 | 1 | 1 |
| near_duplicates | 1.0 | 1.0 | 1 | 1 |

Label source: expected values come from the generated `ground_truth.json` labels. Clean invoice/PO and invoice/payment identity pairs are included; labeled partial-payment, overpayment, date-gap, missing-payment, missing-PO, and duplicate-copy records are excluded. Matcher output is used only as actual output.

## Document extraction accuracy by field

| Field | Correct | Total | Accuracy |
| --- | ---: | ---: | ---: |
| currency | 4 | 4 | 1.0 |
| date | 4 | 4 | 1.0 |
| document_number | 4 | 4 | 1.0 |
| document_type | 4 | 4 | 1.0 |
| po_reference | 1 | 1 | 1.0 |
| total_amount | 4 | 4 | 1.0 |
| vendor | 4 | 4 | 1.0 |

Extraction labels come from `backend/tests/fixtures/documents/labels.json`, never from parser output.
