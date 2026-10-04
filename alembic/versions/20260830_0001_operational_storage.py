"""Create operational PostgreSQL storage.

Revision ID: 20260830_0001
Revises:
Create Date: 2026-08-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260830_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMPTY_OBJECT = sa.text("'{}'::json")
EMPTY_ARRAY = sa.text("'[]'::json")
NOW = sa.text("CURRENT_TIMESTAMP")


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "chats",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("type", sa.String(32), server_default="unknown", nullable=False),
        sa.Column("title", sa.String(255)),
        sa.Column("username", sa.String(64)),
        sa.Column("settings", sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("statistics", sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("category_statistics", sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("display_name", sa.String(255), server_default="Unknown", nullable=False),
        sa.Column("global_score", sa.Numeric(14, 3), server_default="0", nullable=False),
        sa.Column("total_answered", sa.Integer(), server_default="0", nullable=False),
        sa.Column("first_answer_at", sa.DateTime(timezone=True)),
        sa.Column("last_answer_at", sa.DateTime(timezone=True)),
        sa.Column("metadata_json", sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "chat_members",
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("score", sa.Numeric(14, 3), server_default="0", nullable=False),
        sa.Column("answered_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("correct_answers_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consecutive_correct", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_consecutive_correct", sa.Integer(), server_default="0", nullable=False),
        sa.Column("first_answer_at", sa.DateTime(timezone=True)),
        sa.Column("last_answer_at", sa.DateTime(timezone=True)),
        sa.Column("last_daily_reset", sa.DateTime(timezone=True)),
        sa.Column("answered_poll_ids", sa.JSON(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("daily_answered_poll_ids", sa.JSON(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("milestone_codes", sa.JSON(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("streak_achievement_codes", sa.JSON(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("extra", sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chat_id", "user_id"),
    )
    op.create_index("ix_chat_members_score", "chat_members", ["chat_id", "score"])
    op.create_table(
        "daily_schedules",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("timezone", sa.String(64), server_default="Europe/Moscow", nullable=False),
        sa.Column("run_times", sa.JSON(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("config", sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id", "kind", name="uq_daily_schedule_chat_kind"),
    )
    op.create_table(
        "quiz_sessions",
        sa.Column("id", sa.String(128), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(32), server_default="classic", nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("state", sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quiz_sessions_chat_status", "quiz_sessions", ["chat_id", "status"])
    op.create_table(
        "poll_answers",
        sa.Column("poll_id", sa.String(255), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("selected_option", sa.Integer()),
        sa.Column("is_correct", sa.Boolean()),
        sa.Column("points_delta", sa.Numeric(10, 3), server_default="0", nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("payload", sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("poll_id", "user_id"),
    )
    op.create_index("ix_poll_answers_chat_answered", "poll_answers", ["chat_id", "answered_at"])
    op.create_table(
        "achievement_grants",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("code", sa.String(255), nullable=False),
        sa.Column("awarded_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("metadata_json", sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "chat_id", "code", name="uq_achievement_grant"),
    )
    op.create_table(
        "message_cleanup_queue",
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("delete_after", sa.DateTime(timezone=True)),
        sa.Column("payload", sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("chat_id", "message_id"),
    )
    op.create_table(
        "photo_quiz_items",
        sa.Column("media_key", sa.String(512), nullable=False),
        sa.Column("correct_answer", sa.Text(), nullable=False),
        sa.Column("hints", sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("media_key"),
    )
    op.create_table(
        "system_states",
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "import_runs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("report", sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_runs_source_digest", "import_runs", ["source_digest"])


def downgrade() -> None:
    op.drop_index("ix_import_runs_source_digest", table_name="import_runs")
    op.drop_table("import_runs")
    op.drop_table("system_states")
    op.drop_table("photo_quiz_items")
    op.drop_table("message_cleanup_queue")
    op.drop_table("achievement_grants")
    op.drop_index("ix_poll_answers_chat_answered", table_name="poll_answers")
    op.drop_table("poll_answers")
    op.drop_index("ix_quiz_sessions_chat_status", table_name="quiz_sessions")
    op.drop_table("quiz_sessions")
    op.drop_table("daily_schedules")
    op.drop_index("ix_chat_members_score", table_name="chat_members")
    op.drop_table("chat_members")
    op.drop_table("users")
    op.drop_table("chats")
