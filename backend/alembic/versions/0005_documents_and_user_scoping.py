"""documents and user scoping

Revision ID: 0005_documents_and_user_scoping
Revises: 0004_users
Create Date: 2026-11-25 23:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "0005_documents_and_user_scoping"
down_revision = "0004_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create uploaded_documents table
    op.create_table(
        "uploaded_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("document_type", sa.String(50), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extraction_method", sa.String(50), nullable=False, server_default="regex"),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="1.0"),
        sa.Column("extracted_data", sa.JSON(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="processed"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_uploaded_documents_user_id", "uploaded_documents", ["user_id"])

    # 2. Add user_id and source_file columns if not present
    with op.batch_alter_table("invoices") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True))
        batch_op.create_index("ix_invoices_user_id", ["user_id"])

    with op.batch_alter_table("purchase_orders") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True))
        batch_op.add_column(sa.Column("source_file", sa.String(255), nullable=True))
        batch_op.create_index("ix_purchase_orders_user_id", ["user_id"])

    with op.batch_alter_table("payments") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True))
        batch_op.add_column(sa.Column("source_file", sa.String(255), nullable=True))
        batch_op.create_index("ix_payments_user_id", ["user_id"])

    with op.batch_alter_table("ai_suggestions") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True))
        batch_op.create_index("ix_ai_suggestions_user_id", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_uploaded_documents_user_id", table_name="uploaded_documents")
    op.drop_table("uploaded_documents")

    with op.batch_alter_table("ai_suggestions") as batch_op:
        batch_op.drop_index("ix_ai_suggestions_user_id")
        batch_op.drop_column("user_id")

    with op.batch_alter_table("payments") as batch_op:
        batch_op.drop_index("ix_payments_user_id")
        batch_op.drop_column("source_file")
        batch_op.drop_column("user_id")

    with op.batch_alter_table("purchase_orders") as batch_op:
        batch_op.drop_index("ix_purchase_orders_user_id")
        batch_op.drop_column("source_file")
        batch_op.drop_column("user_id")

    with op.batch_alter_table("invoices") as batch_op:
        batch_op.drop_index("ix_invoices_user_id")
        batch_op.drop_column("user_id")
