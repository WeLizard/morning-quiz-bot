"""Farm: who invited whom (one reward per invited farm).

Additive only: a new table. The coins themselves are ordinary farm balance/ledger entries.

Revision ID: 20261010_0028
Revises: 20261010_0027
"""
from alembic import op
import sqlalchemy as sa


revision = "20261010_0028"
down_revision = "20261010_0027"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "farm_invites",
        sa.Column("invitee_farm_id", sa.Uuid(), sa.ForeignKey("farm_states.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("inviter_farm_id", sa.Uuid(), sa.ForeignKey("farm_states.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("rewarded_at", sa.Float(), nullable=True),
        sa.CheckConstraint("inviter_farm_id <> invitee_farm_id", name="ck_farm_invites_not_self"),
    )
    op.create_index("ix_farm_invites_inviter", "farm_invites", ["inviter_farm_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM farm_invites)")):
        raise RuntimeError("Farm invitations exist. Disable the feature; do not delete them by downgrading.")
    op.drop_table("farm_invites")
