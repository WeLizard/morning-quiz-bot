"""Automatic client errors: deduplicated rows in problem_reports plus accepted-call hits for the limits.

Revision ID: 20261016_0036
Revises: 20261016_0035
"""
from alembic import context, op
import sqlalchemy as sa

revision = "20261016_0036"
down_revision = "20261016_0035"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("problem_reports", sa.Column("kind", sa.String(16), nullable=False, server_default="manual"))
    op.add_column("problem_reports", sa.Column("fingerprint", sa.String(64), nullable=True))
    op.add_column("problem_reports", sa.Column("occurrences", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("problem_reports", sa.Column("affected_accounts", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("problem_reports", sa.Column("last_account_id", sa.Uuid(), nullable=True))
    op.add_column("problem_reports", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("problem_reports", sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint("ck_problem_reports_kind", "problem_reports", "kind IN ('manual', 'auto_error')")
    op.create_index("uq_problem_reports_auto_fingerprint", "problem_reports", ["fingerprint"], unique=True,
                    postgresql_where=sa.text("kind = 'auto_error'"))
    op.create_index("ix_problem_reports_kind_status_seen", "problem_reports", ["kind", "status", "last_seen_at"])
    op.create_table(
        "problem_error_hits",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("ip_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("report_id", sa.BigInteger(), sa.ForeignKey("problem_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_problem_error_hits_account_created", "problem_error_hits", ["account_id", "created_at"])
    op.create_index("ix_problem_error_hits_ip_created", "problem_error_hits", ["ip_hash", "created_at"])


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError("Cannot generate an offline downgrade: stored automatic errors must be checked first")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM problem_reports WHERE kind = 'auto_error')")):
        raise RuntimeError("Cannot downgrade: automatic error reports exist")
    op.drop_index("ix_problem_error_hits_ip_created", table_name="problem_error_hits")
    op.drop_index("ix_problem_error_hits_account_created", table_name="problem_error_hits")
    op.drop_table("problem_error_hits")
    op.drop_index("ix_problem_reports_kind_status_seen", table_name="problem_reports")
    op.drop_index("uq_problem_reports_auto_fingerprint", table_name="problem_reports")
    op.drop_constraint("ck_problem_reports_kind", "problem_reports", type_="check")
    for column in ("notified_at", "last_seen_at", "last_account_id", "affected_accounts", "occurrences",
                   "fingerprint", "kind"):
        op.drop_column("problem_reports", column)
