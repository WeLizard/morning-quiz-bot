"""Player problem reports with sanitised screenshots (additive).

Revision ID: 20261016_0033
Revises: 20261015_0032
"""
from alembic import context, op
import sqlalchemy as sa

revision = "20261016_0033"
down_revision = "20261015_0032"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "problem_reports",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("display_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("build", sa.String(40), nullable=False, server_default="unknown"),
        sa.Column("ip_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("account_id", "request_id", name="uq_problem_reports_account_request"),
        sa.CheckConstraint("status IN ('new', 'in_progress', 'done')", name="ck_problem_reports_status"),
    )
    op.create_index("ix_problem_reports_account_created", "problem_reports", ["account_id", "created_at"])
    op.create_index("ix_problem_reports_ip_created", "problem_reports", ["ip_hash", "created_at"])
    op.create_index("ix_problem_reports_status_created", "problem_reports", ["status", "created_at"])
    op.create_table(
        "problem_report_images",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.BigInteger(), sa.ForeignKey("problem_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False, server_default="image/jpeg"),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.UniqueConstraint("report_id", "position", name="uq_problem_report_images_position"),
    )


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError("Cannot generate an offline downgrade: stored reports must be checked first")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM problem_reports)")):
        raise RuntimeError("Cannot downgrade: problem reports exist")
    op.drop_table("problem_report_images")
    op.drop_index("ix_problem_reports_status_created", table_name="problem_reports")
    op.drop_index("ix_problem_reports_ip_created", table_name="problem_reports")
    op.drop_index("ix_problem_reports_account_created", table_name="problem_reports")
    op.drop_table("problem_reports")
