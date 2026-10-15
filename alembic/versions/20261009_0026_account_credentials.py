"""Password credentials for standalone accounts (login without email).

Revision ID: 20261009_0026
Revises: 20261009_0025
"""
from alembic import context, op
import sqlalchemy as sa


revision = "20261009_0026"
down_revision = "20261009_0025"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "account_credentials",
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError(
            "Cannot generate an offline downgrade: password credentials must be checked first"
        )
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM account_credentials)")):
        raise RuntimeError("Cannot downgrade: password credentials exist")
    op.drop_table("account_credentials")
