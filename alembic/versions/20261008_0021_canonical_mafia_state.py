"""Canonicalize persisted Mafia identities to room/account IDs.

Revision ID: 20261008_0021
Revises: 20261008_0020
"""
from copy import deepcopy
import json

from alembic import context, op
import sqlalchemy as sa

from domain.mafia_state import canonicalize_mafia_state, restore_legacy_mafia_state


revision = "20261008_0021"
down_revision = "20261008_0020"
branch_labels = None
depends_on = None


def _read_games(connection):
    return connection.execute(sa.text("""
        SELECT g.id, g.room_id, g.chat_id, g.state, r.kind AS room_kind
        FROM games g JOIN rooms r ON r.id = g.room_id
        WHERE g.mode = 'mafia' ORDER BY g.id
    """)).mappings().all()


def upgrade():
    if context.is_offline_mode():
        raise RuntimeError("Mafia state migration requires a live DB preflight")
    connection = op.get_bind()
    prepared = []
    failures = []
    for game in _read_games(connection):
        try:
            mapping = None
            if game["room_kind"] == "telegram":
                player_rows = connection.execute(sa.text("""
                    SELECT gp.user_id, gp.account_id, u.account_id AS user_account_id,
                           ai.account_id AS verified_account_id
                    FROM game_players gp
                    LEFT JOIN users u ON u.id = gp.user_id
                    LEFT JOIN account_identities ai
                      ON ai.provider = 'telegram' AND ai.provider_subject = gp.user_id::text
                     AND ai.revoked_at IS NULL
                     AND ai.verified_at IS NOT NULL
                    WHERE gp.game_id = :game_id
                """), {"game_id": game["id"]}).mappings().all()
                mapping = {}
                for player in player_rows:
                    user_id = player["user_id"]
                    account_id = player["account_id"]
                    if (user_id is None or account_id is None
                            or player["user_account_id"] != account_id
                            or player["verified_account_id"] != account_id):
                        raise ValueError("player account/verified Telegram mapping mismatch")
                    mapping[user_id] = str(account_id)
            elif game["room_kind"] != "standalone":
                raise ValueError(f"unsupported room kind {game['room_kind']!r}")

            state = canonicalize_mafia_state(
                game["state"], game["room_id"], mapping,
                game["chat_id"] if game["room_kind"] == "telegram" else None,
            )
            roster = {player["account_id"] for player in state["players"]}
            stored_accounts = {str(row["account_id"]) for row in connection.execute(sa.text(
                "SELECT account_id FROM game_players WHERE game_id = :game_id"
            ), {"game_id": game["id"]}).mappings()}
            if roster != stored_accounts:
                raise ValueError("state roster does not match game_players accounts")
            prepared.append((game["id"], state))
        except (TypeError, ValueError) as error:
            failures.append(f"{game['id']}: {error}")
    if failures:
        raise RuntimeError("Cannot canonicalize Mafia state; no rows changed: " + "; ".join(failures))

    for game_id, state in prepared:
        connection.execute(sa.text(
            "UPDATE games SET state = CAST(:state AS json) WHERE id = :game_id"
        ), {"game_id": game_id, "state": json.dumps(state, ensure_ascii=False)})


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError("Mafia state downgrade requires a live DB preflight")
    connection = op.get_bind()
    prepared = []
    failures = []
    for game in _read_games(connection):
        try:
            mapping = None
            if game["room_kind"] == "telegram":
                rows = connection.execute(sa.text("""
                    SELECT gp.account_id, gp.user_id, u.account_id AS user_account_id,
                           ai.account_id AS verified_account_id
                    FROM game_players gp
                    LEFT JOIN users u ON u.id = gp.user_id
                    LEFT JOIN account_identities ai
                      ON ai.provider = 'telegram' AND ai.provider_subject = gp.user_id::text
                     AND ai.revoked_at IS NULL
                     AND ai.verified_at IS NOT NULL
                    WHERE gp.game_id = :game_id
                """), {"game_id": game["id"]}).mappings().all()
                mapping = {}
                for row in rows:
                    if (row["user_id"] is None or row["user_account_id"] != row["account_id"]
                            or row["verified_account_id"] != row["account_id"]):
                        raise ValueError("account has no unambiguous verified Telegram identity")
                    mapping[str(row["account_id"])] = row["user_id"]
                state = restore_legacy_mafia_state(
                    deepcopy(game["state"]), "telegram", game["chat_id"], mapping,
                )
            elif game["room_kind"] == "standalone":
                state = restore_legacy_mafia_state(deepcopy(game["state"]), "standalone")
            else:
                raise ValueError(f"unsupported room kind {game['room_kind']!r}")
            prepared.append((game["id"], state))
        except (TypeError, ValueError) as error:
            failures.append(f"{game['id']}: {error}")
    if failures:
        raise RuntimeError("Cannot downgrade Mafia state; no rows changed: " + "; ".join(failures))
    for game_id, state in prepared:
        connection.execute(sa.text(
            "UPDATE games SET state = CAST(:state AS json) WHERE id = :game_id"
        ), {"game_id": game_id, "state": json.dumps(state, ensure_ascii=False)})
