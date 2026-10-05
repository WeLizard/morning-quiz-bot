"""SQLAlchemy models for the authoritative mutable platform state."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ModerationMixin:
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false', nullable=False)
    bot_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    moderation_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    moderation_reason: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)


class Chat(ModerationMixin, TimestampMixin, Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    type: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255))
    username: Mapped[Optional[str]] = mapped_column(String(64))
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    settings_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    statistics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    category_statistics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class User(ModerationMixin, TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    display_name: Mapped[str] = mapped_column(String(255), default="Unknown", nullable=False)
    global_score: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), default=Decimal("0"), nullable=False
    )
    total_answered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_answer_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_answer_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class ChatMember(TimestampMixin, Base):
    __tablename__ = "chat_members"

    chat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    score: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"), nullable=False)
    answered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct_answers_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consecutive_correct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_consecutive_correct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_answer_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_answer_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_daily_reset: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    answered_poll_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    daily_answered_poll_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    milestone_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    streak_achievement_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (Index("ix_chat_members_score", "chat_id", "score"),)


class DailySchedule(TimestampMixin, Base):
    __tablename__ = "daily_schedules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow", nullable=False)
    run_times: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (UniqueConstraint("chat_id", "kind", name="uq_daily_schedule_chat_kind"),)


class QuizSession(TimestampMixin, Base):
    __tablename__ = "quiz_sessions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    chat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), default="classic", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_quiz_sessions_chat_status", "chat_id", "status"),)


class Game(TimestampMixin, Base):
    """Authoritative state envelope shared by every long-running game mode."""
    __tablename__ = 'games'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    chat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('chats.id', ondelete='CASCADE'), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default='0', nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default='true', nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index('ix_games_chat_mode_history', 'chat_id', 'mode', 'created_at'),
        Index(
            'uq_games_current_chat_mode', 'chat_id', 'mode', unique=True,
            postgresql_where=text('is_current'),
        ),
    )


class GamePlayer(Base):
    __tablename__ = 'game_players'

    game_id: Mapped[str] = mapped_column(
        String(64), ForeignKey('games.id', ondelete='CASCADE'), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('users.id', ondelete='RESTRICT'), primary_key=True
    )
    seat: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default='active', server_default='active', nullable=False)
    public_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    private_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint('game_id', 'seat', name='uq_game_player_seat'),)


class GameCommand(Base):
    """Idempotency receipt for commands submitted by any client adapter."""
    __tablename__ = 'game_commands'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    game_id: Mapped[str] = mapped_column(
        String(64), ForeignKey('games.id', ondelete='CASCADE'), nullable=False
    )
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey('users.id', ondelete='SET NULL')
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_revision: Mapped[Optional[int]] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default='accepted', server_default='accepted', nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index('ix_game_commands_game_created', 'game_id', 'created_at'),)


class GameEvent(Base):
    """Append-only game history; private events must never enter public projections."""
    __tablename__ = 'game_events'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(
        String(64), ForeignKey('games.id', ondelete='CASCADE'), nullable=False
    )
    event_index: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    visibility: Mapped[str] = mapped_column(String(24), default='public', server_default='public', nullable=False)
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey('users.id', ondelete='SET NULL')
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint('game_id', 'event_index', name='uq_game_event_index'),
        Index('ix_game_events_game_created', 'game_id', 'created_at'),
    )


class GameDeadline(Base):
    __tablename__ = 'game_deadlines'

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    game_id: Mapped[str] = mapped_column(
        String(64), ForeignKey('games.id', ondelete='CASCADE'), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default='pending', server_default='pending', nullable=False)
    claimed_by: Mapped[Optional[str]] = mapped_column(String(96))
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint('game_id', 'kind', name='uq_game_deadline_kind'),
        Index('ix_game_deadlines_pending_due', 'status', 'due_at'),
    )


class GameDelivery(TimestampMixin, Base):
    """Binding between an internal game effect and one transport acknowledgement."""

    __tablename__ = 'game_deliveries'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    game_id: Mapped[str] = mapped_column(
        String(64), ForeignKey('games.id', ondelete='CASCADE'), nullable=False
    )
    round_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[Optional[str]] = mapped_column(String(255))
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            'game_id', 'round_id', 'channel', 'kind',
            name='uq_game_delivery_effect',
        ),
        UniqueConstraint('channel', 'external_id', name='uq_game_delivery_external'),
        Index('ix_game_deliveries_game_created', 'game_id', 'created_at'),
    )


class NotificationOutbox(Base):
    __tablename__ = 'notification_outbox'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    game_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey('games.id', ondelete='CASCADE')
    )
    chat_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(24), default='pending', server_default='pending', nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default='0', nullable=False)
    claimed_by: Mapped[Optional[str]] = mapped_column(String(96))
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (Index('ix_notification_outbox_ready', 'status', 'available_at'),)


class PollAnswer(Base):
    __tablename__ = "poll_answers"

    poll_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    chat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    selected_option: Mapped[Optional[int]] = mapped_column(Integer)
    is_correct: Mapped[Optional[bool]] = mapped_column(Boolean)
    points_delta: Mapped[Decimal] = mapped_column(
        Numeric(10, 3), default=Decimal("0"), nullable=False
    )
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    game_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey('games.id', ondelete='SET NULL')
    )
    round_id: Mapped[Optional[str]] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_poll_answers_chat_answered", "chat_id", "answered_at"),
        Index("ix_poll_answers_user_answered", "user_id", "answered_at", "poll_id"),
        Index(
            "uq_poll_answers_game_round_user", "game_id", "round_id", "user_id",
            unique=True, postgresql_where=text("game_id IS NOT NULL"),
        ),
    )


class AchievementGrant(Base):
    __tablename__ = "achievement_grants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    code: Mapped[str] = mapped_column(String(255), nullable=False)
    awarded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "chat_id", "code", name="uq_achievement_grant"),
    )


class MessageCleanupItem(Base):
    __tablename__ = "message_cleanup_queue"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    delete_after: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PhotoQuizItem(TimestampMixin, Base):
    __tablename__ = "photo_quiz_items"

    media_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    correct_answer: Mapped[str] = mapped_column(Text, nullable=False)
    hints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class QuestionCategory(TimestampMixin, Base):
    __tablename__ = 'question_categories'

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default='0', nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false', nullable=False)


class QuestionCategoryRevision(Base):
    __tablename__ = 'question_category_revisions'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category_name: Mapped[str] = mapped_column(String(100), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint('category_name', 'revision', name='uq_question_category_revision'),
        Index('ix_question_category_history', 'category_name', 'created_at'),
    )


class SystemState(TimestampMixin, Base):
    __tablename__ = "system_states"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    payload: Mapped[Any] = mapped_column(JSON, default=dict, nullable=False)


class ImportRun(Base):
    __tablename__ = "import_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class AdminAction(Base):
    """Append-only receipts; no cascade when an operational entity is removed."""
    __tablename__ = "admin_actions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    request: Mapped[dict] = mapped_column(JSON, nullable=False)
    before: Mapped[dict] = mapped_column(JSON, nullable=False)
    after: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (Index("ix_admin_actions_target", "scope", "target_id", "created_at"),)


class MiniAppSession(Base):
    """Opaque, short-lived user sessions. Raw credentials are never stored."""
    __tablename__ = 'mini_app_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    bot_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    init_data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    user_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    auth_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false', nullable=False)
    __table_args__ = (
        UniqueConstraint('bot_key_id', 'init_data_hash', name='uq_mini_app_init_data'),
        Index('ix_mini_app_sessions_user_expiry', 'user_id', 'expires_at'),
        Index('ix_mini_app_sessions_expiry', 'expires_at'),
    )


class AlchemyProgress(Base):
    """Прогресс «Алхимии»: элементы, главы, достижения и очки за эту игру."""

    __tablename__ = 'alchemy_progress'

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('users.id', ondelete='CASCADE'),
        primary_key=True, autoincrement=False,
    )
    discovered: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    crafted: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    chapters: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    achievements: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    points_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), default=Decimal('0'), nullable=False
    )
    points_today: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), default=Decimal('0'), nullable=False
    )
    points_day: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Серия дней с закрытой целью дня: считается по московским суткам.
    goal_streak: Mapped[int] = mapped_column(Integer, default=0, server_default='0', nullable=False)
    last_goal_day: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
