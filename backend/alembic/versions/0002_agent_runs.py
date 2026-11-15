"""agent investigation runs"""
import sqlalchemy as sa

from alembic import op


revision = "0002_agent_runs"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("exception_id", sa.String(36), sa.ForeignKey("exception_cases.id"), nullable=False),
        sa.Column("verdict", sa.String(20), nullable=False),
        sa.Column("explanation", sa.Text, nullable=False),
        sa.Column("claims", sa.JSON, nullable=False),
        sa.Column("tool_calls", sa.JSON, nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("verification_status", sa.String(20), nullable=False),
        sa.Column("errors", sa.JSON, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("agent_runs")
