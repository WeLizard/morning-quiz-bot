"""Allow room-owned games and account-only participants.

Revision ID: 20261008_0020
Revises: 20261008_0019
"""
from alembic import context, op
import sqlalchemy as sa


revision = "20261008_0020"
down_revision = "20261008_0019"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    duplicate_room_games = connection.scalar(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM games
            WHERE is_current
            GROUP BY room_id, mode HAVING count(*) > 1
        )
    """))
    if duplicate_room_games:
        raise RuntimeError("Cannot make rooms authoritative: duplicate current games exist in one room")

    op.alter_column("games", "chat_id", existing_type=sa.BigInteger(), nullable=True)
    op.alter_column("games", "room_id", existing_type=sa.String(64), nullable=False)
    op.create_index("ix_games_room_mode_history", "games", ["room_id", "mode", "created_at"])
    op.create_index(
        "uq_games_current_room_mode", "games", ["room_id", "mode"], unique=True,
        postgresql_where=sa.text("is_current"),
    )

    # Every existing row was assigned a Telegram-derived account in 0018.
    # Promote that transport-neutral principal to the PK and retain Telegram's
    # optional ID as a unique lookup for the legacy Bot adapter.
    op.drop_constraint("game_players_pkey", "game_players", type_="primary")
    op.drop_constraint("uq_game_player_account", "game_players", type_="unique")
    op.alter_column("game_players", "user_id", existing_type=sa.BigInteger(), nullable=True)
    op.create_primary_key("game_players_pkey", "game_players", ["game_id", "account_id"])
    op.create_index(
        "uq_game_player_user", "game_players", ["game_id", "user_id"], unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError("Cannot generate an offline downgrade: room-scoped game data must be inspected")
    connection = op.get_bind()
    unsafe = connection.scalar(sa.text("""
        SELECT EXISTS (SELECT 1 FROM games WHERE chat_id IS NULL)
            OR EXISTS (SELECT 1 FROM game_players WHERE user_id IS NULL)
            OR EXISTS (
                SELECT 1 FROM games
                WHERE room_id <> 'telegram:' || chat_id::text
            )
    """))
    if unsafe:
        raise RuntimeError("Cannot downgrade: standalone room game data would be lost")

    op.drop_index("uq_game_player_user", table_name="game_players")
    op.drop_constraint("game_players_pkey", "game_players", type_="primary")
    op.alter_column("game_players", "user_id", existing_type=sa.BigInteger(), nullable=False)
    op.create_primary_key("game_players_pkey", "game_players", ["game_id", "user_id"])
    op.create_unique_constraint("uq_game_player_account", "game_players", ["game_id", "account_id"])

    op.drop_index("uq_games_current_room_mode", table_name="games")
    op.drop_index("ix_games_room_mode_history", table_name="games")
    op.alter_column("games", "room_id", existing_type=sa.String(64), nullable=True)
    op.alter_column("games", "chat_id", existing_type=sa.BigInteger(), nullable=False)
