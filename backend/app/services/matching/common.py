from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.models import Invoice, Payment, PurchaseOrder


@dataclass(frozen=True)
class MatchDecision:
    invoice: Invoice
    counterpart: PurchaseOrder | Payment
    counterpart_type: str
    tier: str
    confidence: Decimal
    matched_amount: Decimal
    rule: str


def within_date_days(first: date, second: date, days: int) -> bool:
    return abs((first - second).days) <= days


def within_amount_tolerance(first: Decimal, second: Decimal, absolute: Decimal, percentage: Decimal) -> bool:
    difference = abs(first - second)
    return difference <= max(absolute, abs(first) * percentage)
