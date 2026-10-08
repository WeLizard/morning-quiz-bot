"""Make legacy game participants and receipts account-addressable.

Revision ID: 20261008_0018
Revises: 20261008_0017
"""
from uuid import uuid4

from alembic import context, op
import sqlalchemy as sa


revision = "20261008_0018"
down_revision = "20261008_0017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "account_identities",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_subject", sa.String(255), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("linked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_account_identities_account_id", "account_identities", ["account_id"])
    op.create_index(
        "ix_account_identities_account_provider", "account_identities", ["account_id", "provider"]
    )
    op.create_index(
        "uq_account_identities_active_subject", "account_identities",
        ["provider", "provider_subject"], unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.add_column("game_players", sa.Column("account_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_game_players_account_id_accounts", "game_players", "accounts",
        ["account_id"], ["id"], ondelete="RESTRICT",
    )
    op.add_column("game_commands", sa.Column("actor_account_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_game_commands_actor_account_id_accounts", "game_commands", "accounts",
        ["actor_account_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_game_commands_actor_account_id", "game_commands", ["actor_account_id"])
    op.add_column("game_events", sa.Column("actor_account_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_game_events_actor_account_id_accounts", "game_events", "accounts",
        ["actor_account_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_game_events_actor_account_id", "game_events", ["actor_account_id"])

    connection = op.get_bind()
    rows = connection.execute(sa.text(
        "SELECT id, display_name FROM users WHERE account_id IS NULL ORDER BY id FOR UPDATE"
    )).mappings().all()
    for row in rows:
        account_id = uuid4()
        connection.execute(sa.text(
            "INSERT INTO accounts (id, display_name) VALUES (:id, :name)"
        ), {"id": account_id, "name": row["display_name"] or "Игрок"})
        connection.execute(sa.text(
            "UPDATE users SET account_id = :account_id WHERE id = :user_id"
        ), {"account_id": account_id, "user_id": row["id"]})

    connection.execute(sa.text("""
        INSERT INTO account_identities
            (account_id, provider, provider_subject, verified_at, linked_at)
        SELECT account_id, 'telegram', id::text, now(), now()
        FROM users WHERE account_id IS NOT NULL
    """))
    connection.execute(sa.text("""
        UPDATE game_players gp SET account_id = u.account_id
        FROM users u WHERE u.id = gp.user_id
    """))
    connection.execute(sa.text("""
        UPDATE game_commands gc SET actor_account_id = u.account_id
        FROM users u WHERE u.id = gc.actor_user_id
    """))
    connection.execute(sa.text("""
        UPDATE game_events ge SET actor_account_id = u.account_id
        FROM users u WHERE u.id = ge.actor_user_id
    """))
    if connection.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM game_players WHERE account_id IS NULL)")):
        raise RuntimeError("Cannot map every legacy game player to a platform account")

    op.alter_column("game_players", "account_id", nullable=False)
    op.create_unique_constraint("uq_game_player_account", "game_players", ["game_id", "account_id"])
    op.create_index("ix_game_players_account_id", "game_players", ["account_id"])


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError(
            "Cannot generate an offline downgrade: account identity mappings must be checked against live data"
        )
    connection = op.get_bind()
    unsafe = connection.scalar(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM account_identities ai
            WHERE ai.revoked_at IS NOT NULL OR ai.provider <> 'telegram'
               OR NOT EXISTS (
                   SELECT 1 FROM users u
                   WHERE u.id::text = ai.provider_subject AND u.account_id = ai.account_id
               )
        ) OR EXISTS (
            SELECT 1 FROM users u
            WHERE u.account_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM account_identities ai
                WHERE ai.provider = 'telegram' AND ai.provider_subject = u.id::text
                  AND ai.account_id = u.account_id AND ai.revoked_at IS NULL
            )
        ) OR EXISTS (
            SELECT 1 FROM game_players gp JOIN users u ON u.id = gp.user_id
            WHERE gp.account_id <> u.account_id
        ) OR EXISTS (
            SELECT 1 FROM game_commands gc JOIN users u ON u.id = gc.actor_user_id
            WHERE gc.actor_account_id IS DISTINCT FROM u.account_id
        ) OR EXISTS (
            SELECT 1 FROM game_events ge JOIN users u ON u.id = ge.actor_user_id
            WHERE ge.actor_account_id IS DISTINCT FROM u.account_id
        )
    """))
    if unsafe:
        raise RuntimeError("Cannot downgrade: account identity or game actor data has changed")

    op.drop_index("ix_game_players_account_id", table_name="game_players")
    op.drop_constraint("uq_game_player_account", "game_players", type_="unique")
    op.drop_constraint("fk_game_players_account_id_accounts", "game_players", type_="foreignkey")
    op.drop_column("game_players", "account_id")
    op.drop_index("ix_game_commands_actor_account_id", table_name="game_commands")
    op.drop_constraint(
        "fk_game_commands_actor_account_id_accounts", "game_commands", type_="foreignkey"
    )
    op.drop_column("game_commands", "actor_account_id")
    op.drop_index("ix_game_events_actor_account_id", table_name="game_events")
    op.drop_constraint(
        "fk_game_events_actor_account_id_accounts", "game_events", type_="foreignkey"
    )
    op.drop_column("game_events", "actor_account_id")
    op.drop_index("uq_account_identities_active_subject", table_name="account_identities")
    op.drop_index("ix_account_identities_account_provider", table_name="account_identities")
    op.drop_index("ix_account_identities_account_id", table_name="account_identities")
    op.drop_table("account_identities")
