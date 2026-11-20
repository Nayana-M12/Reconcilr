"""AI similarity suggestions"""

import sqlalchemy as sa

from alembic import op

revision = "0003_ai_suggestions"
down_revision = "0002_agent_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendor_aliases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vendor_id", sa.String(36), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("alias_vendor_id", sa.String(36), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("score", sa.Numeric(5, 4), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_vendor_aliases_vendor_id", "vendor_aliases", ["vendor_id"])
    op.create_index("ix_vendor_aliases_alias_vendor_id", "vendor_aliases", ["alias_vendor_id"])
    op.create_table(
        "ai_suggestions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("record_ids", sa.JSON, nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("score", sa.Numeric(5, 4), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ai_suggestions")
    op.drop_index("ix_vendor_aliases_alias_vendor_id", table_name="vendor_aliases")
    op.drop_index("ix_vendor_aliases_vendor_id", table_name="vendor_aliases")
    op.drop_table("vendor_aliases")
