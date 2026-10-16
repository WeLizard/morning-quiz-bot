"""Opaque, expiring, one-use farm share invitations.

Revision ID: 20261015_0032
Revises: 20261015_0031
"""
from alembic import context, op
import sqlalchemy as sa

revision = "20261015_0032"
down_revision = "20261015_0031"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "farm_share_invites",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("farm_id", sa.Uuid(), sa.ForeignKey("farm_states.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column("accepted_by_farm_id", sa.Uuid(), sa.ForeignKey("farm_states.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("accepted_at", sa.Float(), nullable=True),
        sa.CheckConstraint("(accepted_by_farm_id IS NULL) = (accepted_at IS NULL)",
                           name="ck_farm_share_invites_accept_pair"),
        sa.CheckConstraint("accepted_by_farm_id IS NULL OR accepted_by_farm_id <> farm_id",
                           name="ck_farm_share_invites_not_self"),
    )
    op.create_index("ix_farm_share_invites_farm", "farm_share_invites", ["farm_id"])
    op.create_index("ix_farm_share_invites_expires", "farm_share_invites", ["expires_at"])


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError("Cannot generate an offline downgrade: accepted invitations must be checked first")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM farm_share_invites WHERE accepted_by_farm_id IS NOT NULL)")):
        raise RuntimeError("Cannot downgrade: accepted farm share invitations exist")
    op.drop_index("ix_farm_share_invites_expires", table_name="farm_share_invites")
    op.drop_index("ix_farm_share_invites_farm", table_name="farm_share_invites")
    op.drop_table("farm_share_invites")
