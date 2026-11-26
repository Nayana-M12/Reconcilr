from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def new_id() -> str:
    return str(uuid4())


class Vendor(Base):
    __tablename__ = "vendors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="vendor")
    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="vendor")
    payments: Mapped[list["Payment"]] = relationship(back_populates="vendor")


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False)
    po_number: Mapped[str | None] = mapped_column(String(100))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    source_file: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_row: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    dedupe_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    vendor: Mapped[Vendor] = relationship(back_populates="invoices")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    po_number: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_row: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    vendor: Mapped[Vendor] = relationship(back_populates="purchase_orders")


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    reference: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_row: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    vendor: Mapped[Vendor] = relationship(back_populates="payments")


class Match(Base):
    __tablename__ = "matches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id"), nullable=False)
    po_id: Mapped[str | None] = mapped_column(ForeignKey("purchase_orders.id"))
    payment_id: Mapped[str | None] = mapped_column(ForeignKey("payments.id"))
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    matched_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class ExceptionCase(Base):
    __tablename__ = "exception_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    invoice_id: Mapped[str | None] = mapped_column(ForeignKey("invoices.id"))
    po_id: Mapped[str | None] = mapped_column(ForeignKey("purchase_orders.id"))
    payment_id: Mapped[str | None] = mapped_column(ForeignKey("payments.id"))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    invoice: Mapped["Invoice | None"] = relationship("Invoice", foreign_keys=[invoice_id])
    purchase_order: Mapped["PurchaseOrder | None"] = relationship("PurchaseOrder", foreign_keys=[po_id])
    payment: Mapped["Payment | None"] = relationship("Payment", foreign_keys=[payment_id])


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    exception_id: Mapped[str] = mapped_column(ForeignKey("exception_cases.id"), nullable=False)
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    record_id: Mapped[str] = mapped_column(String(36), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)


class Adjustment(Base):
    __tablename__ = "adjustments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    exception_id: Mapped[str] = mapped_column(ForeignKey("exception_cases.id"), nullable=False)
    proposed_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    calculation_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class ApprovalStep(Base):
    __tablename__ = "approval_steps"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    adjustment_id: Mapped[str] = mapped_column(ForeignKey("adjustments.id"), nullable=False)
    approver_role: Mapped[str] = mapped_column(String(100), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    exception_id: Mapped[str] = mapped_column(ForeignKey("exception_cases.id"), nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    claims: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False)
    errors: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class VendorAlias(Base):
    __tablename__ = "vendor_aliases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    alias_vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class AISuggestion(Base):
    __tablename__ = "ai_suggestions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    record_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class UploadedDocument(Base):
    __tablename__ = "uploaded_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "invoice", "purchase_order", "payment"
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size: Mapped[int] = mapped_column(nullable=False, default=0)
    extraction_method: Mapped[str] = mapped_column(String(50), nullable=False, default="regex")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("1.0"))
    extracted_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="processed")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
