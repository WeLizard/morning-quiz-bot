"""Hashed, expiring invitations for standalone rooms.

Revision ID: 20261008_0019
Revises: 20261008_0018
"""
from alembic import context, op
import sqlalchemy as sa


revision = "20261008_0019"
down_revision = "20261008_0018"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "room_invites",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("room_id", sa.String(64), sa.ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("uses", sa.Integer(), server_default="0", nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_room_invites_token_hash"),
        sa.CheckConstraint("max_uses BETWEEN 1 AND 100", name="ck_room_invites_max_uses"),
        sa.CheckConstraint("uses BETWEEN 0 AND max_uses", name="ck_room_invites_uses"),
    )
    op.create_index("ix_room_invites_room_created", "room_invites", ["room_id", "created_at"])


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError(
            "Cannot generate an offline downgrade: invitation data must be checked first"
        )
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM room_invites)")):
        raise RuntimeError("Cannot downgrade: room invitation records exist")
    op.drop_index("ix_room_invites_room_created", table_name="room_invites")
    op.drop_table("room_invites")
