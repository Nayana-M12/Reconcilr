from app.config import Settings
from app.services.exceptions.detectors import ExceptionFinding


def classify(finding: ExceptionFinding, settings: Settings) -> str:
    base = {
        "DUPLICATE_INVOICE": "high",
        "DUPLICATE_PAYMENT": "high",
        "MISSING_PO": "high",
        "MISSING_PAYMENT": "high",
        "PARTIAL_PAYMENT": "medium",
        "OVERPAYMENT": "medium",
        "AMOUNT_MISMATCH": "medium",
        "DATE_GAP": "medium",
        "VENDOR_MISMATCH": "medium",
    }.get(finding.type, "low")
    amount = finding.amount_difference
    if amount >= settings.exception_critical_amount_threshold:
        return "critical"
    if amount >= settings.exception_high_amount_threshold:
        return "high"
    if amount >= settings.exception_medium_amount_threshold and base == "low":
        return "medium"
    return base
