from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ImportRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str | None = None
    vendor_id: str | None = None
    vendor_name: str | None = Field(default=None, min_length=1)
    amount: Decimal = Field(gt=Decimal(0))
    currency: str = Field(min_length=3, max_length=3)
    invoice_number: str | None = None
    po_number: str | None = None
    reference: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    order_date: date | None = None
    payment_date: date | None = None

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()


class VendorImportRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str | None = None
    name: str = Field(min_length=1)
    normalized_name: str | None = None


class ImportResponse(BaseModel):
    record_type: str
    source_file: str
    imported: int
    rejected: int
    duplicates: int
    errors: list[dict[str, object]]
    ids: list[str]
