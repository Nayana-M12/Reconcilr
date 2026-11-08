"""initial reconciliation schema"""
import sqlalchemy as sa

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("vendors", sa.Column("id", sa.String(36), primary_key=True), sa.Column("name", sa.String(255), nullable=False), sa.Column("normalized_name", sa.String(255), nullable=False))
    op.create_index("ix_vendors_normalized_name", "vendors", ["normalized_name"])
    op.create_table("invoices", sa.Column("id", sa.String(36), primary_key=True), sa.Column("vendor_id", sa.String(36), sa.ForeignKey("vendors.id"), nullable=False), sa.Column("invoice_number", sa.String(100), nullable=False), sa.Column("po_number", sa.String(100)), sa.Column("amount", sa.Numeric(18, 2), nullable=False), sa.Column("currency", sa.String(3), nullable=False), sa.Column("invoice_date", sa.Date, nullable=False), sa.Column("due_date", sa.Date), sa.Column("source_file", sa.String(255), nullable=False), sa.Column("raw_row", sa.JSON, nullable=False), sa.Column("dedupe_hash", sa.String(64), nullable=False))
    op.create_index("ix_invoices_vendor_id", "invoices", ["vendor_id"])
    op.create_index("ix_invoices_dedupe_hash", "invoices", ["dedupe_hash"])
    op.create_table("purchase_orders", sa.Column("id", sa.String(36), primary_key=True), sa.Column("vendor_id", sa.String(36), sa.ForeignKey("vendors.id"), nullable=False), sa.Column("po_number", sa.String(100), nullable=False), sa.Column("amount", sa.Numeric(18, 2), nullable=False), sa.Column("currency", sa.String(3), nullable=False), sa.Column("order_date", sa.Date, nullable=False), sa.Column("raw_row", sa.JSON, nullable=False))
    op.create_index("ix_purchase_orders_vendor_id", "purchase_orders", ["vendor_id"])
    op.create_table("payments", sa.Column("id", sa.String(36), primary_key=True), sa.Column("vendor_id", sa.String(36), sa.ForeignKey("vendors.id"), nullable=False), sa.Column("reference", sa.String(100), nullable=False), sa.Column("amount", sa.Numeric(18, 2), nullable=False), sa.Column("currency", sa.String(3), nullable=False), sa.Column("payment_date", sa.Date, nullable=False), sa.Column("raw_row", sa.JSON, nullable=False))
    op.create_index("ix_payments_vendor_id", "payments", ["vendor_id"])
    op.create_table("matches", sa.Column("id", sa.String(36), primary_key=True), sa.Column("invoice_id", sa.String(36), sa.ForeignKey("invoices.id"), nullable=False), sa.Column("po_id", sa.String(36), sa.ForeignKey("purchase_orders.id")), sa.Column("payment_id", sa.String(36), sa.ForeignKey("payments.id")), sa.Column("tier", sa.String(20), nullable=False), sa.Column("confidence", sa.Numeric(5, 4), nullable=False), sa.Column("matched_amount", sa.Numeric(18, 2), nullable=False), sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False))
    op.create_table("exception_cases", sa.Column("id", sa.String(36), primary_key=True), sa.Column("type", sa.String(30), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("severity", sa.String(20), nullable=False), sa.Column("invoice_id", sa.String(36), sa.ForeignKey("invoices.id")), sa.Column("po_id", sa.String(36), sa.ForeignKey("purchase_orders.id")), sa.Column("payment_id", sa.String(36), sa.ForeignKey("payments.id")), sa.Column("description", sa.Text, nullable=False), sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False))
    op.create_table("evidence", sa.Column("id", sa.String(36), primary_key=True), sa.Column("exception_id", sa.String(36), sa.ForeignKey("exception_cases.id"), nullable=False), sa.Column("record_type", sa.String(30), nullable=False), sa.Column("record_id", sa.String(36), nullable=False), sa.Column("note", sa.Text, nullable=False))
    op.create_table("adjustments", sa.Column("id", sa.String(36), primary_key=True), sa.Column("exception_id", sa.String(36), sa.ForeignKey("exception_cases.id"), nullable=False), sa.Column("proposed_amount", sa.Numeric(18, 2), nullable=False), sa.Column("calculation_json", sa.JSON, nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False))
    op.create_table("approval_steps", sa.Column("id", sa.String(36), primary_key=True), sa.Column("adjustment_id", sa.String(36), sa.ForeignKey("adjustments.id"), nullable=False), sa.Column("approver_role", sa.String(100), nullable=False), sa.Column("decision", sa.String(20), nullable=False), sa.Column("comment", sa.Text), sa.Column("decided_at", sa.DateTime))
    op.create_table("audit_logs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("timestamp", sa.DateTime, server_default=sa.func.now(), nullable=False), sa.Column("actor", sa.String(100), nullable=False), sa.Column("action", sa.String(100), nullable=False), sa.Column("entity_type", sa.String(100), nullable=False), sa.Column("entity_id", sa.String(36), nullable=False), sa.Column("inputs", sa.JSON, nullable=False), sa.Column("formula", sa.Text, nullable=False), sa.Column("output", sa.JSON, nullable=False))


def downgrade() -> None:
    for table in ("audit_logs", "approval_steps", "adjustments", "evidence", "exception_cases", "matches", "payments", "purchase_orders", "invoices", "vendors"):
        op.drop_table(table)
