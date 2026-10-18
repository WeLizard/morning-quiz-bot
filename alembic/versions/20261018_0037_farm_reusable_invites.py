"""Reusable farm invite links: one link per farm accepted up to max_uses times.

The token is recomputed as HMAC(secret, farm_id, nonce), so only its digest is stored, as before.
Legacy one-use rows keep working: max_uses=1, and an accepted row becomes uses=1 plus an
acceptance row in farm_share_invite_uses.

Revision ID: 20261018_0037
Revises: 20261016_0036
"""
from alembic import context, op
import sqlalchemy as sa

revision = "20261018_0037"
down_revision = "20261016_0036"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("farm_share_invites", sa.Column("nonce", sa.String(32), nullable=True))
    op.add_column("farm_share_invites", sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("farm_share_invites", sa.Column("uses", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint("ck_farm_share_invites_uses", "farm_share_invites",
                               "max_uses >= 1 AND uses >= 0 AND uses <= max_uses")
    op.create_table(
        "farm_share_invite_uses",
        sa.Column("token_hash", sa.String(64), sa.ForeignKey("farm_share_invites.token_hash", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("farm_id", sa.Uuid(), sa.ForeignKey("farm_states.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("accepted_at", sa.Float(), nullable=False),
    )
    op.execute("UPDATE farm_share_invites SET uses = 1 WHERE accepted_by_farm_id IS NOT NULL")
    op.execute("INSERT INTO farm_share_invite_uses (token_hash, farm_id, accepted_at) "
               "SELECT token_hash, accepted_by_farm_id, accepted_at FROM farm_share_invites "
               "WHERE accepted_by_farm_id IS NOT NULL")


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError("Cannot generate an offline downgrade: reusable invitations must be checked first")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM farm_share_invites WHERE uses > 1)")):
        raise RuntimeError("Cannot downgrade: a farm invite link was accepted more than once")
    # Back to one-use rows: the single acceptance returns to accepted_by_farm_id; reusable rows become one-use.
    op.execute("UPDATE farm_share_invites i SET accepted_by_farm_id = u.farm_id, accepted_at = u.accepted_at "
               "FROM farm_share_invite_uses u WHERE u.token_hash = i.token_hash AND i.accepted_by_farm_id IS NULL")
    op.drop_table("farm_share_invite_uses")
    op.drop_constraint("ck_farm_share_invites_uses", "farm_share_invites", type_="check")
    op.drop_column("farm_share_invites", "uses")
    op.drop_column("farm_share_invites", "max_uses")
    op.drop_column("farm_share_invites", "nonce")
