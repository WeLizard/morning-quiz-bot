"""Telegram login in the browser, account merge audit and labelled account sessions.

Revision ID: 20261015_0031
Revises: 20261015_0030
"""
from alembic import context, op
import sqlalchemy as sa

revision = "20261015_0031"
down_revision = "20261015_0030"
branch_labels = None
depends_on = None


def upgrade():
    # Browser-started "log in with Telegram": the bot approves, the same browser completes.
    op.create_table(
        "telegram_login_requests",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("start_token_hash", sa.String(64), nullable=False),
        sa.Column("browser_secret_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("client_hint", sa.String(120), nullable=False, server_default=""),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_display_name", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'approved', 'cancelled', 'consumed')",
                           name="ck_telegram_login_requests_status"),
        sa.UniqueConstraint("start_token_hash", name="uq_telegram_login_requests_start"),
        sa.UniqueConstraint("browser_secret_hash", name="uq_telegram_login_requests_browser"),
    )
    op.create_index("ix_telegram_login_requests_expires", "telegram_login_requests", ["expires_at"])

    # A merged account is kept (archived) for audit and manual rollback, never deleted.
    op.add_column("accounts", sa.Column("merged_into_id", sa.Uuid(),
                  sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True))
    op.add_column("accounts", sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint("ck_accounts_not_merged_into_self", "accounts",
                               "merged_into_id IS NULL OR merged_into_id <> id")
    op.create_table(
        "account_merges",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("main_account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("merged_account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("initiated_via", sa.String(16), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("merged_account_id", name="uq_account_merges_merged"),
    )
    op.create_index("ix_account_merges_main", "account_merges", ["main_account_id"])

    # Device list: how a browser session was opened and a short client label.
    op.add_column("guest_sessions", sa.Column("created_via", sa.String(16), nullable=True))
    op.add_column("guest_sessions", sa.Column("user_agent", sa.String(120), nullable=True))


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError("Cannot generate an offline downgrade: account merges must be checked first")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM account_merges)")):
        raise RuntimeError("Cannot downgrade: merged accounts exist")
    op.drop_column("guest_sessions", "user_agent")
    op.drop_column("guest_sessions", "created_via")
    op.drop_index("ix_account_merges_main", table_name="account_merges")
    op.drop_table("account_merges")
    op.drop_constraint("ck_accounts_not_merged_into_self", "accounts", type_="check")
    op.drop_column("accounts", "merged_at")
    op.drop_column("accounts", "merged_into_id")
    op.drop_index("ix_telegram_login_requests_expires", table_name="telegram_login_requests")
    op.drop_table("telegram_login_requests")
