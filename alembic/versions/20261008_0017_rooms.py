"""Introduce transport-neutral rooms and preserve existing Telegram games.

Revision ID: 20261008_0017
Revises: 20261008_0016
"""
from alembic import context, op
import sqlalchemy as sa


revision = "20261008_0017"
down_revision = "20261008_0016"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rooms",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("title", sa.String(255), server_default="", nullable=False),
        sa.Column("owner_account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="RESTRICT")),
        sa.Column("state", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rooms_owner_account_id", "rooms", ["owner_account_id"])
    op.create_table(
        "room_memberships",
        sa.Column("room_id", sa.String(64), sa.ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_room_memberships_account_id", "room_memberships", ["account_id"])
    op.create_table(
        "room_transports",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("room_id", sa.String(64), sa.ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("metadata_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("kind", "external_id", name="uq_room_transport_external"),
    )
    op.create_index("ix_room_transports_room_id", "room_transports", ["room_id"])

    # Telegram chat IDs are stable legacy room IDs. No account owner/member is
    # inferred: existing Telegram membership data is not identity proof.
    op.execute(sa.text("""
        INSERT INTO rooms (id, kind, title, state, created_at, updated_at)
        SELECT 'telegram:' || id::text, 'telegram', COALESCE(title, ''), '{}', now(), now()
        FROM chats
    """))
    op.execute(sa.text("""
        INSERT INTO room_transports (room_id, kind, external_id, metadata_json)
        SELECT 'telegram:' || id::text, 'telegram', id::text,
               json_build_object('chat_type', type, 'username', username)
        FROM chats
    """))

    op.add_column("games", sa.Column("room_id", sa.String(64), nullable=True))
    op.execute(sa.text("""
        UPDATE games SET room_id = 'telegram:' || chat_id::text
    """))
    op.create_foreign_key(
        "fk_games_room_id_rooms", "games", "rooms", ["room_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_games_room_id", "games", ["room_id"])


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError(
            "Cannot generate an offline downgrade: room data must be checked first; "
            "run this downgrade against the database so its data-loss guard can execute"
        )
    connection = op.get_bind()
    if connection.scalar(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM rooms
            WHERE kind <> 'telegram' OR owner_account_id IS NOT NULL
               OR state::jsonb <> '{}'::jsonb
        ) OR EXISTS (SELECT 1 FROM room_memberships)
          OR (SELECT count(*) FROM rooms) <> (SELECT count(*) FROM chats)
          OR (SELECT count(*) FROM room_transports) <> (SELECT count(*) FROM chats)
          OR EXISTS (
              SELECT 1 FROM chats c
              LEFT JOIN rooms r ON r.id = 'telegram:' || c.id::text
              LEFT JOIN room_transports t
                ON t.kind = 'telegram' AND t.external_id = c.id::text
              WHERE r.id IS NULL OR r.title <> COALESCE(c.title, '')
                 OR t.id IS NULL OR t.room_id <> r.id
                 OR t.metadata_json::jsonb <> json_build_object(
                     'chat_type', c.type, 'username', c.username)::jsonb
          )
    """)):
        raise RuntimeError("Cannot downgrade: account-owned or changed room data exists")
    op.drop_index("ix_games_room_id", table_name="games")
    op.drop_constraint("fk_games_room_id_rooms", "games", type_="foreignkey")
    op.drop_column("games", "room_id")
    op.drop_index("ix_room_transports_room_id", table_name="room_transports")
    op.drop_table("room_transports")
    op.drop_index("ix_room_memberships_account_id", table_name="room_memberships")
    op.drop_table("room_memberships")
    op.drop_index("ix_rooms_owner_account_id", table_name="rooms")
    op.drop_table("rooms")
