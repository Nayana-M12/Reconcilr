"""add account management fields to users"""

import sqlalchemy as sa

from alembic import op

revision = "0005_user_management"
down_revision = "0004_users_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("status", sa.String(20), nullable=False, server_default="active"))
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("users", sa.Column("created_via", sa.String(30), nullable=False, server_default="seed"))
    op.add_column("users", sa.Column("request_note", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("approved_by", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("approved_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "approved_at")
    op.drop_column("users", "approved_by")
    op.drop_column("users", "request_note")
    op.drop_column("users", "created_via")
    op.drop_column("users", "is_active")
    op.drop_column("users", "status")
    op.drop_column("users", "email")
