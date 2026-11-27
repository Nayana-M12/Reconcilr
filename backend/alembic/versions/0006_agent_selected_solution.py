"""add selected solution columns to agent_runs"""

import sqlalchemy as sa

from alembic import op

revision = "0006_agent_selected_solution"
down_revision = "0005_user_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("selected_solution_id", sa.String(100), nullable=True))
    op.add_column("agent_runs", sa.Column("selected_solution_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "selected_solution_note")
    op.drop_column("agent_runs", "selected_solution_id")
