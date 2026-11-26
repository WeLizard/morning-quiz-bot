"""SQLAlchemy models for the authoritative mutable platform state."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy import text as sql_text  # `text` is a column name inside ProblemReport
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB


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


class Account(ModerationMixin, TimestampMixin, Base):
    """App identity independent of Telegram. Linking is an explicit future flow."""
    __tablename__ = "accounts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    display_name: Mapped[str] = mapped_column(String(255), default="Гость", nullable=False)
    # Form of address for game texts: 'm' | 'f' | 'n'. NULL = not asked yet (reads as neutral);
    # Telegram does not report gender, so it is never inferred.
    address_form: Mapped[Optional[str]] = mapped_column(String(1))
    # Set once when this account was merged into another; it is then archived, never deleted.
    merged_into_id: Mapped[Optional[UUID]] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"))
    merged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # "Don't show me in the rating": the player still sees their own place.
    rating_hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    # Accessibility «Контрастный режим» (Профиль → Настройки): one switch for the hub and every game,
    # applied as <html data-qw-contrast="1"> by the shell (docs/design/UI_RULES.md §16).
    contrast_mode: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    # Optional IANA timezone selected in the account profile; NULL keeps the device-derived default.
    timezone: Mapped[Optional[str]] = mapped_column(String(64))
    # Sparse account-wide sound and motion preferences; absent keys defer to each game's legacy setting.
    game_preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False)

    __table_args__ = (
        CheckConstraint("merged_into_id IS NULL OR merged_into_id <> id",
                        name="ck_accounts_not_merged_into_self"),
    )


class AccountMerge(Base):
    """Audit record of one merge: what moved from ``merged_account_id`` into the main account."""
    __tablename__ = "account_merges"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    main_account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    merged_account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    initiated_via: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("merged_account_id", name="uq_account_merges_merged"),
        Index("ix_account_merges_main", "main_account_id"),
    )


class TelegramLoginRequest(Base):
    """Browser-started Telegram login: the bot approves it, only the starting browser completes it."""
    __tablename__ = "telegram_login_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    start_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    browser_secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending", nullable=False)
    client_hint: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    telegram_display_name: Mapped[Optional[str]] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'cancelled', 'consumed')",
                        name="ck_telegram_login_requests_status"),
        UniqueConstraint("start_token_hash", name="uq_telegram_login_requests_start"),
        UniqueConstraint("browser_secret_hash", name="uq_telegram_login_requests_browser"),
        Index("ix_telegram_login_requests_expires", "expires_at"),
    )


class AccountIdentity(Base):
    """Verified external identity linked explicitly to one platform account."""
    __tablename__ = "account_identities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "uq_account_identities_active_subject", "provider", "provider_subject",
            unique=True, postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_account_identities_account_provider", "account_id", "provider"),
    )


class AccountCredential(Base):
    """Password verifier for the ``password`` identity. No email is required;
    a future ``email`` identity can sit next to it on the same account."""
    __tablename__ = "account_credentials"

    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Room(TimestampMixin, Base):
    """A game space that can outlive any one transport such as Telegram."""
    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    owner_account_id: Mapped[Optional[UUID]] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # «Открытая комната»: listed for strangers while open_activity_at is fresh (see application/rooms.py).
    is_open: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false', nullable=False)
    open_activity_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # «Ночной город»: the story (world pack) of the room; ids are checked on the server (domain/night_worlds.py).
    world: Mapped[str] = mapped_column(String(32), default="manor_lake", server_default="manor_lake", nullable=False)

    __table_args__ = (Index("ix_rooms_open_activity", "is_open", "open_activity_at"),)


class RoomMembership(TimestampMixin, Base):
    __tablename__ = "room_memberships"

    room_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", server_default="active", nullable=False)


class RoomInvite(Base):
    """Hashed, expiring capability for joining an account-owned room."""
    __tablename__ = "room_invites"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    room_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False
    )
    created_by_account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Hash of the short typed code (K7Q4-MD2X); NULL for invites created before the short code existed.
    short_hash: Mapped[Optional[str]] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False)
    uses: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("max_uses BETWEEN 1 AND 100", name="ck_room_invites_max_uses"),
        CheckConstraint("uses BETWEEN 0 AND max_uses", name="ck_room_invites_uses"),
        UniqueConstraint("token_hash", name="uq_room_invites_token_hash"),
        UniqueConstraint("short_hash", name="uq_room_invites_short_hash"),
        Index("ix_room_invites_room_created", "room_id", "created_at"),
    )


class RoomJoinAttempt(Base):
    """Rate-limit ledger: room membership changes and failed short-code entries per account."""
    __tablename__ = "room_join_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Keyed hash of the client network address (failed short-code entries only; never the raw address).
    client_hash: Mapped[Optional[str]] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_room_join_attempts_account", "account_id", "kind", "created_at"),
        Index("ix_room_join_attempts_client", "kind", "client_hash", "created_at"),
    )


class RoomTransport(TimestampMixin, Base):
    """Maps an external chat/group to a room without inferring account identity."""
    __tablename__ = "room_transports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint("kind", "external_id", name="uq_room_transport_external"),
        Index("ix_room_transports_room_id", "room_id"),
    )


class AccountSession(Base):
    """Both login channels share storage, with separate credential namespaces."""
    __tablename__ = 'account_sessions'

    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    account_id: Mapped[Optional[UUID]] = mapped_column(Uuid, ForeignKey('accounts.id', ondelete='CASCADE'))
    account_revision: Mapped[Optional[int]] = mapped_column(Integer)
    created_via: Mapped[Optional[str]] = mapped_column(String(16))
    user_agent: Mapped[Optional[str]] = mapped_column(String(120))
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'))
    user_revision: Mapped[Optional[int]] = mapped_column(Integer)
    bot_key_id: Mapped[Optional[str]] = mapped_column(String(64))
    init_data_hash: Mapped[Optional[str]] = mapped_column(String(64))
    auth_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    __mapper_args__ = {'polymorphic_on': kind, 'polymorphic_abstract': True}
    __table_args__ = (
        CheckConstraint(
            "(kind = 'browser' AND account_id IS NOT NULL AND account_revision IS NOT NULL "
            "AND user_id IS NULL AND user_revision IS NULL AND bot_key_id IS NULL "
            "AND init_data_hash IS NULL AND auth_date IS NULL) OR "
            "(kind = 'mini' AND account_id IS NULL AND account_revision IS NULL "
            "AND created_via IS NULL AND user_agent IS NULL AND user_id IS NOT NULL "
            "AND user_revision IS NOT NULL AND bot_key_id IS NOT NULL "
            "AND init_data_hash IS NOT NULL AND auth_date IS NOT NULL)",
            name='ck_account_sessions_kind_fields',
        ),
        Index('ix_account_sessions_account_id', 'account_id', postgresql_where=sql_text("kind = 'browser'")),
        Index('ix_account_sessions_browser_expiry', 'expires_at', postgresql_where=sql_text("kind = 'browser'")),
        Index('ix_account_sessions_mini_user_expiry', 'user_id', 'expires_at', postgresql_where=sql_text("kind = 'mini'")),
        Index('ix_account_sessions_mini_expiry', 'expires_at', postgresql_where=sql_text("kind = 'mini'")),
        Index('uq_account_sessions_mini_init_data', 'bot_key_id', 'init_data_hash', unique=True,
              postgresql_where=sql_text("kind = 'mini'")),
    )

    @classmethod
    def key(cls, digest):
        return cls.__mapper__.polymorphic_identity, digest


class GuestSession(AccountSession):
    """Browser sessions, including password and linked Telegram browser access."""
    __mapper_args__ = {'polymorphic_identity': 'browser'}


class MiniAppSession(AccountSession):
    """Telegram WebView sessions with an initData replay record."""
    __mapper_args__ = {'polymorphic_identity': 'mini'}


class User(ModerationMixin, TimestampMixin, Base):
    __tablename__ = "users"

    account_id: Mapped[Optional[UUID]] = mapped_column(Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), unique=True)

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
    room_id: Mapped[str] = mapped_column(
        String(64), ForeignKey('rooms.id', ondelete='RESTRICT'), nullable=False, index=True
    )
    chat_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey('chats.id', ondelete='CASCADE')
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
        Index('ix_games_room_mode_history', 'room_id', 'mode', 'created_at'),
        Index('ix_games_chat_mode_history', 'chat_id', 'mode', 'created_at'),
        Index('uq_games_current_night_family', 'room_id', unique=True,
              postgresql_where=text("is_current AND ((mode='night_case' AND status NOT IN ('finished','stopped')) OR (mode='mafia' AND status NOT IN ('finished','stopped','interrupted')))")),
        Index(
            'uq_games_current_chat_mode', 'chat_id', 'mode', unique=True,
            postgresql_where=text('is_current'),
        ),
        Index(
            'uq_games_current_room_mode', 'room_id', 'mode', unique=True,
            postgresql_where=text('is_current'),
        ),
    )


class GamePlayer(Base):
    __tablename__ = 'game_players'

    game_id: Mapped[str] = mapped_column(
        String(64), ForeignKey('games.id', ondelete='CASCADE'), primary_key=True
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey('accounts.id', ondelete='RESTRICT'), primary_key=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey('users.id', ondelete='RESTRICT')
    )
    seat: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default='active', server_default='active', nullable=False)
    public_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    private_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Account is the stable platform principal. Telegram user_id remains a
        # nullable identity projection for legacy Bot-facing game adapters.
        # The database PK follows account identity so web-only guests are first-class.
        UniqueConstraint('game_id', 'seat', name='uq_game_player_seat'),
        Index(
            'uq_game_player_user', 'game_id', 'user_id', unique=True,
            postgresql_where=text('user_id IS NOT NULL'),
        ),
        Index('ix_game_players_account_id', 'account_id'),
    )


class ClassicAccountAnswer(Base):
    """One immutable answer per platform actor and Classic round."""
    __tablename__ = 'classic_account_answers'

    game_id: Mapped[str] = mapped_column(String(64), ForeignKey('games.id', ondelete='CASCADE'), primary_key=True)
    round_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey('accounts.id', ondelete='RESTRICT'), primary_key=True)
    selected_option: Mapped[int] = mapped_column(Integer, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    points_delta: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (CheckConstraint('selected_option BETWEEN 0 AND 9', name='ck_classic_account_answer_option'),)


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
    actor_account_id: Mapped[Optional[UUID]] = mapped_column(
        Uuid, ForeignKey('accounts.id', ondelete='SET NULL'), index=True
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
    actor_account_id: Mapped[Optional[UUID]] = mapped_column(
        Uuid, ForeignKey('accounts.id', ondelete='SET NULL'), index=True
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
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default='0', nullable=False)
    last_error_code: Mapped[Optional[str]] = mapped_column(String(64))
    retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    quarantined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

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
    version: Mapped[int] = mapped_column(Integer, default=0, server_default='0', nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index('ix_notification_outbox_ready', 'status', 'available_at'),)


class NotificationResolution(Base):
    """Atomic operator receipt; independent of game/poll delivery bindings."""
    __tablename__ = 'notification_resolutions'

    action_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    item_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True,
    )
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    operator_id: Mapped[str] = mapped_column(String(96), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    previous_version: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        CheckConstraint("decision IN ('confirmed_delivered', 'closed_without_resend')",
                        name='ck_notification_resolution_decision'),
    )


class NotificationQuarantineReceipt(Base):
    """Nonterminal offline quarantine audit, independent of terminal resolutions."""
    __tablename__ = 'notification_quarantine_receipts'

    action_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    operator_id: Mapped[str] = mapped_column(String(96), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    previous_version: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_version: Mapped[int] = mapped_column(Integer, nullable=False)
    claimed_by: Mapped[Optional[str]] = mapped_column(String(96))
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


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
    target_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    target_account_id: Mapped[Optional[UUID]] = mapped_column(Uuid, ForeignKey('accounts.id', ondelete='RESTRICT'))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    request: Mapped[dict] = mapped_column(JSON, nullable=False)
    before: Mapped[dict] = mapped_column(JSON, nullable=False)
    after: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        Index("ix_admin_actions_target", "scope", "target_id", "created_at"),
        Index("ix_admin_actions_account_target", "target_account_id", "created_at"),
        CheckConstraint("(scope = 'accounts' AND target_id IS NULL AND target_account_id IS NOT NULL) OR (scope <> 'accounts' AND target_id IS NOT NULL AND target_account_id IS NULL)", name="ck_admin_actions_typed_target"),
    )


class AlchemyProgress(Base):
    """Прогресс «Алхимии»: элементы, главы, достижения и очки за эту игру."""

    __tablename__ = 'alchemy_progress'

    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey('accounts.id', ondelete='CASCADE'), primary_key=True,
    )
    # Transitional Telegram mapping; account_id alone owns the progress.
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default='0', nullable=False)
    discovered: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    crafted: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # Claims imported from offline/local saves remain visible but never drive rating.
    verified_discovered: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    verified_crafted: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    verified_chapters: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    verified_achievements: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
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


class AlchemyCraftCommand(Base):
    """Idempotent server-validated craft command and its immutable result."""
    __tablename__ = 'alchemy_craft_commands'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False, index=True,
    )
    ingredient_a: Mapped[str] = mapped_column(String(64), nullable=False)
    ingredient_b: Mapped[str] = mapped_column(String(64), nullable=False)
    result_element: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # A failed verification can later be retried after a legitimate craft chain.
    # Command id, rather than ingredient pair, identifies the immutable receipt.


class AlchemyStageClaim(Base):
    __tablename__ = 'alchemy_stage_claims'
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey('accounts.id', ondelete='CASCADE'), primary_key=True)
    stage_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(String(64), nullable=False)
    catalog_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    reward: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AlchemyClaimCommand(Base):
    __tablename__ = 'alchemy_claim_commands'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProblemReport(Base):
    """A player-submitted problem report; delivered to the owner through the notification outbox."""
    __tablename__ = 'problem_reports'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    account_id: Mapped[Optional[UUID]] = mapped_column(Uuid, ForeignKey('accounts.id', ondelete='SET NULL'))
    request_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    display_name: Mapped[str] = mapped_column(String(120), default='', nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    build: Mapped[str] = mapped_column(String(40), default='unknown', nullable=False)
    ip_hash: Mapped[str] = mapped_column(String(64), default='', nullable=False)
    status: Mapped[str] = mapped_column(String(16), default='new', server_default='new', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Automatic client errors (kind='auto_error') are deduplicated by fingerprint into one row.
    kind: Mapped[str] = mapped_column(String(16), default='manual', server_default='manual', nullable=False)
    fingerprint: Mapped[Optional[str]] = mapped_column(String(64))
    occurrences: Mapped[int] = mapped_column(Integer, default=1, server_default='1', nullable=False)
    affected_accounts: Mapped[int] = mapped_column(Integer, default=1, server_default='1', nullable=False)
    last_account_id: Mapped[Optional[UUID]] = mapped_column(Uuid)  # no FK: a hint, not an ownership link
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint('account_id', 'request_id', name='uq_problem_reports_account_request'),
        CheckConstraint("status IN ('new', 'in_progress', 'done')", name='ck_problem_reports_status'),
        CheckConstraint("kind IN ('manual', 'auto_error')", name='ck_problem_reports_kind'),
        Index('uq_problem_reports_auto_fingerprint', 'fingerprint', unique=True,
              postgresql_where=sql_text("kind = 'auto_error'"), sqlite_where=sql_text("kind = 'auto_error'")),
        Index('ix_problem_reports_kind_status_seen', 'kind', 'status', 'last_seen_at'),
        Index('ix_problem_reports_account_created', 'account_id', 'created_at'),
        Index('ix_problem_reports_ip_created', 'ip_hash', 'created_at'),
        Index('ix_problem_reports_status_created', 'status', 'created_at'),
    )


class ProblemReportImage(Base):
    """Sanitised JPEG screenshot (EXIF stripped, <=1600 px) stored in the shared database."""
    __tablename__ = 'problem_report_images'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('problem_reports.id', ondelete='CASCADE'), nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), default='image/jpeg', nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    __table_args__ = (UniqueConstraint('report_id', 'position', name='uq_problem_report_images_position'),)


class ProblemErrorHit(Base):
    """One accepted automatic-error call; the rate limits count these, not the deduplicated rows."""
    __tablename__ = 'problem_error_hits'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    account_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    ip_hash: Mapped[str] = mapped_column(String(64), default='', nullable=False)
    report_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('problem_reports.id', ondelete='CASCADE'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('ix_problem_error_hits_account_created', 'account_id', 'created_at'),
        Index('ix_problem_error_hits_ip_created', 'ip_hash', 'created_at'),
    )


class ScoreEvent(Base):
    """Append-only journal of every point change of an account, whatever the channel or game.

    Written only through ``storage.score_ledger.RewardLedger.award``; ``(account_id, source, key)``
    makes a repeated command a no-op. Negative amounts are admin corrections."""
    __tablename__ = 'score_events'

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    account_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey('accounts.id', ondelete='RESTRICT'), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    key: Mapped[str] = mapped_column(String(300), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    game_id: Mapped[Optional[str]] = mapped_column(String(64))
    room_id: Mapped[Optional[str]] = mapped_column(String(64))
    chat_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('account_id', 'source', 'key', name='uq_score_events_key'),
        Index('ix_score_events_created', 'created_at'),
        Index('ix_score_events_source_created', 'source', 'created_at'),
        Index('ix_score_events_room', 'room_id', 'created_at', postgresql_where=text('room_id IS NOT NULL')),
        Index('ix_score_events_chat', 'chat_id', 'created_at', postgresql_where=text('chat_id IS NOT NULL')),
    )


class ScoreTotal(Base):
    """Per-source running total of ``score_events``; rebuilt from the journal at any time."""
    __tablename__ = 'score_totals'

    account_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey('accounts.id', ondelete='RESTRICT'), primary_key=True)
    source: Mapped[str] = mapped_column(String(24), primary_key=True)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal('0'), server_default='0', nullable=False)
    events: Mapped[int] = mapped_column(Integer, default=0, server_default='0', nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index('ix_score_totals_source_total', 'source', 'total'),)


# Night Case storage is intentionally absent from generic game serializers.
class NightCase(Base):
    __tablename__ = 'night_cases'
    case_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    compiler_version: Mapped[str] = mapped_column(String(96), nullable=False)
    engine_build: Mapped[str] = mapped_column(String(96), nullable=False)
    validation_report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    registered_by: Mapped[Optional[UUID]] = mapped_column(Uuid, ForeignKey('accounts.id', ondelete='RESTRICT'))
    registered_operator_id: Mapped[Optional[str]] = mapped_column(String(128))
    admission: Mapped[str] = mapped_column(String(16), nullable=False, server_default='registered')
    __table_args__ = (
        CheckConstraint('version > 0', name='ck_night_case_version'),
        CheckConstraint('registered_by IS NOT NULL OR registered_operator_id IS NOT NULL', name='ck_night_case_registration_principal'),
        CheckConstraint("registered_operator_id IS NULL OR (registered_operator_id LIKE 'operator:%' AND length(registered_operator_id) > 9)", name='ck_night_case_operator_namespace'),
        CheckConstraint("admission IN ('registered','rehearsal','retired')", name='ck_night_case_admission'),
        UniqueConstraint('case_id', 'version', 'content_hash', name='uq_night_case_pinned'),
    )


class NightGameSealed(Base):
    __tablename__ = 'night_game_sealed'
    game_id: Mapped[str] = mapped_column(String(64), ForeignKey('games.id', ondelete='RESTRICT'), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(96), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rules_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_build: Mapped[str] = mapped_column(String(96), nullable=False)
    compiler_version: Mapped[str] = mapped_column(String(96), nullable=False)
    storage_version: Mapped[int] = mapped_column(Integer, server_default='1', nullable=False)
    kernel: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB(none_as_null=True))
    lobby: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB(none_as_null=True))
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_revision: Mapped[int] = mapped_column(BigInteger, server_default='0', nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(16), nullable=False)
    interruption: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB(none_as_null=True))
    __table_args__ = (
        ForeignKeyConstraint(['case_id','version','content_hash'], ['night_cases.case_id','night_cases.version','night_cases.content_hash'], ondelete='RESTRICT'),
        CheckConstraint('storage_version = 1 AND storage_revision >= 0', name='ck_night_sealed_version'),
        CheckConstraint("lifecycle IN ('lobby','running','finished','interrupted','stopped')", name='ck_night_sealed_lifecycle'),
    )


class NightLobbyCommand(Base):
    __tablename__ = 'night_lobby_commands'
    room_id: Mapped[str] = mapped_column(String(64), ForeignKey('rooms.id', ondelete='RESTRICT'), primary_key=True)
    original_actor_account_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey('accounts.id', ondelete='RESTRICT'), primary_key=True)
    client_command_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), server_default='create_lobby', nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    game_id: Mapped[str] = mapped_column(String(64), ForeignKey('games.id', ondelete='RESTRICT'), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (CheckConstraint("kind = 'create_lobby'", name='ck_night_lobby_kind'),)


class NightLobbyMessage(Base):
    """A line of the lobby talk («Обсуждение»): players at the table before the case starts.

    The sender's table name and seat (hero and character) are kept as they were when the line was written."""
    __tablename__ = 'night_lobby_messages'
    game_id: Mapped[str] = mapped_column(String(64), ForeignKey('games.id', ondelete='RESTRICT'), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)   # order at the table, given under the game row lock
    command_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sender_account_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey('accounts.id', ondelete='RESTRICT'), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    character_id: Mapped[Optional[str]] = mapped_column(String(96))
    look_id: Mapped[Optional[str]] = mapped_column(String(96))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint('game_id','sender_account_id','command_id', name='uq_night_lobby_message_command'),
        UniqueConstraint('game_id','seq', name='uq_night_lobby_message_seq'),
        CheckConstraint('seq >= 1', name='ck_night_lobby_message_seq'),
        CheckConstraint('length(text) BETWEEN 1 AND 500 AND octet_length(text) <= 2048', name='ck_night_lobby_message_text'),
        Index('ix_night_lobby_messages_game_time', 'game_id', 'created_at'),
    )


class NightEvent(Base):
    __tablename__ = 'night_events'
    game_id: Mapped[str] = mapped_column(String(64), ForeignKey('games.id', ondelete='RESTRICT'), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    audience_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    window_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint('game_id','scope','audience_seq', name='uq_night_event_audience'),
        CheckConstraint("scope = 'public' OR scope ~ '^account:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'", name='ck_night_event_scope'),
        CheckConstraint('audience_seq >= 0', name='ck_night_event_seq'),
    )


class NightMessage(Base):
    __tablename__ = 'night_messages'
    game_id: Mapped[str] = mapped_column(String(64), ForeignKey('games.id', ondelete='RESTRICT'), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    command_id: Mapped[str] = mapped_column(String(128), nullable=False)
    thread_key: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_account_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey('accounts.id', ondelete='RESTRICT'), nullable=False)
    recipients: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    window_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint('game_id','sender_account_id','command_id', name='uq_night_message_command'),
        CheckConstraint("channel IN ('square','whisper','ghost')", name='ck_night_message_channel'),
        CheckConstraint("jsonb_typeof(recipients) = 'array' AND jsonb_array_length(recipients) BETWEEN 1 AND 12", name='ck_night_message_recipients'),
        CheckConstraint('length(text) BETWEEN 1 AND 1000 AND octet_length(text) <= 4096', name='ck_night_message_text'),
    )


class NightRenderJob(Base):
    __tablename__ = 'night_render_jobs'
    job_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    game_id: Mapped[str] = mapped_column(String(64), ForeignKey('games.id', ondelete='RESTRICT'), nullable=False)
    cause_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    audience_key: Mapped[str] = mapped_column(String(64), nullable=False)
    knowledge_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    template_version: Mapped[str] = mapped_column(String(64), nullable=False)
    frozen_view: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fallback: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default='pending')
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0')
    lease_owner: Mapped[Optional[str]] = mapped_column(String(96))
    lease_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sanitized_error: Mapped[Optional[str]] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint('game_id','cause_id','kind','audience_key','knowledge_revision','template_version', name='uq_night_render_cause'),)


class NightRendering(Base):
    __tablename__ = 'night_renderings'
    job_id: Mapped[str] = mapped_column(String(96), ForeignKey('night_render_jobs.job_id', ondelete='RESTRICT'), primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    references: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    catalog_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_shown_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("source IN ('authored','ai') AND length(text) <= 4000", name='ck_night_rendering_source'),)


class NightIntentProposal(Base):
    __tablename__ = 'night_intent_proposals'
    proposal_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    game_id: Mapped[str] = mapped_column(String(64), ForeignKey('games.id', ondelete='RESTRICT'), nullable=False)
    original_actor_account_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey('accounts.id', ondelete='RESTRICT'), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    proposal: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_command_id: Mapped[Optional[str]] = mapped_column(String(128))
    __table_args__ = (UniqueConstraint('game_id','original_actor_account_id','request_id', name='uq_night_proposal_request'),)


class NightEpisodeDraft(Base):
    __tablename__ = 'night_episode_drafts'
    draft_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    candidate: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    world_id: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_job_id: Mapped[Optional[str]] = mapped_column(String(96), ForeignKey('night_render_jobs.job_id', ondelete='RESTRICT'))
    owner_review: Mapped[str] = mapped_column(String(16), server_default='draft', nullable=False)
    reviewed_by: Mapped[Optional[UUID]] = mapped_column(Uuid, ForeignKey('accounts.id', ondelete='RESTRICT'))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("owner_review IN ('draft','rejected','approved')", name='ck_night_draft_review'),)


class NightRewardClaim(Base):
    __tablename__ = 'night_reward_claims'
    game_id: Mapped[str] = mapped_column(String(64), ForeignKey('games.id', ondelete='RESTRICT'), primary_key=True)
    original_account_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey('accounts.id', ondelete='RESTRICT'), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    reward_facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    seen_observation_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    formula_version: Mapped[int] = mapped_column(Integer, server_default='1', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (CheckConstraint("kind = 'case_result' AND formula_version = 1", name='ck_night_reward_kind'),)


class NightRuntimeOutage(Base):
    __tablename__ = 'night_runtime_outages'
    outage_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), unique=True, nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    detected_by: Mapped[str] = mapped_column(String(16), nullable=False)
    __table_args__ = (
        CheckConstraint("detected_by IN ('api','worker','operator')", name='ck_night_outage_detector'),
        CheckConstraint('ended_at IS NULL OR ended_at > started_at', name='ck_night_outage_interval'),
    )


class NightRuntimeHealth(Base):
    __tablename__ = 'night_runtime_health'
    runtime_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    api_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    worker_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    active_outage_id: Mapped[Optional[str]] = mapped_column(String(96), ForeignKey('night_runtime_outages.outage_id', ondelete='RESTRICT'))


class NightNarratorLimit(Base):
    __tablename__ = 'night_narrator_limits'
    scope: Mapped[str] = mapped_column(String(128), primary_key=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    reserved_requests: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0')
    reserved_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default='0')
    failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0')
    circuit_open_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint('reserved_requests >= 0 AND reserved_tokens >= 0 AND failures >= 0', name='ck_night_limits_nonnegative'),)


# Register the owning AI module on this same Base; no parallel metadata/backend.
# Module import (rather than symbol imports) also supports explicit AI-first import.
from storage import night_ai_models as _night_ai_models  # noqa: E402,F401
