"""Account score journal (score_events) with per-source totals.

Revision ID: 20261016_0034
Revises: 20261016_0033

Creates the journal and imports every pre-journal score once (see storage/score_backfill.py);
``users.global_score`` becomes a cache of the common part of the journal. Run with the bot and
web stopped: the old code wrote ``global_score`` without the journal.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261016_0034"
down_revision = "20261016_0033"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "score_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("key", sa.String(300), nullable=False),
        sa.Column("amount", sa.Numeric(14, 3), nullable=False),
        sa.Column("game_id", sa.String(64), nullable=True),
        sa.Column("room_id", sa.String(64), nullable=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "source", "key", name="uq_score_events_key"),
    )
    op.create_index("ix_score_events_created", "score_events", ["created_at"])
    op.create_index("ix_score_events_source_created", "score_events", ["source", "created_at"])
    op.create_index("ix_score_events_room", "score_events", ["room_id", "created_at"],
                    postgresql_where=sa.text("room_id IS NOT NULL"))
    op.create_index("ix_score_events_chat", "score_events", ["chat_id", "created_at"],
                    postgresql_where=sa.text("chat_id IS NOT NULL"))
    op.create_table(
        "score_totals",
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("source", sa.String(24), primary_key=True),
        sa.Column("total", sa.Numeric(14, 3), nullable=False, server_default="0"),
        sa.Column("events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_score_totals_source_total", "score_totals", ["source", "total"])

    from storage.score_backfill import STATEMENTS
    for statement in STATEMENTS:
        op.execute(sa.text(statement))


def downgrade():
    # users.global_score keeps the common part only; Alchemy points live in alchemy_progress.
    op.drop_index("ix_score_totals_source_total", table_name="score_totals")
    op.drop_table("score_totals")
    op.drop_index("ix_score_events_chat", table_name="score_events")
    op.drop_index("ix_score_events_room", table_name="score_events")
    op.drop_index("ix_score_events_source_created", table_name="score_events")
    op.drop_index("ix_score_events_created", table_name="score_events")
    op.drop_table("score_events")
