"""Open rooms, short invite codes and the room join rate-limit ledger.

Revision ID: 20261028_0042
Revises: 20261025_0041
"""
from alembic import op
import sqlalchemy as sa

revision = "20261028_0042"
down_revision = "20261025_0041"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("rooms", sa.Column("is_open", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("rooms", sa.Column("open_activity_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("room_invites", sa.Column("short_hash", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_room_invites_short_hash", "room_invites", ["short_hash"])
    op.create_table(
        "room_join_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("client_hash", sa.String(64), nullable=True),
    )
    op.create_index("ix_room_join_attempts_account", "room_join_attempts", ["account_id", "kind", "created_at"])
    op.create_index("ix_room_join_attempts_client", "room_join_attempts", ["kind", "client_hash", "created_at"])
    # Public list of open rooms: filter by is_open, newest activity first.
    op.create_index("ix_rooms_open_activity", "rooms", ["is_open", "open_activity_at"])


def downgrade():
    op.drop_index("ix_rooms_open_activity", table_name="rooms")
    op.drop_table("room_join_attempts")
    op.drop_constraint("uq_room_invites_short_hash", "room_invites", type_="unique")
    op.drop_column("room_invites", "short_hash")
    op.drop_column("rooms", "open_activity_at")
    op.drop_column("rooms", "is_open")
