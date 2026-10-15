"""Farm: pairs of farms that already got the first-neighbourhood reward (once per unordered pair, for good).

Additive only: a new table. The coins themselves are ordinary farm balance/ledger entries.

Revision ID: 20261011_0029
Revises: 20261010_0028
"""
from alembic import op
import sqlalchemy as sa


revision = "20261011_0029"
down_revision = "20261010_0028"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "farm_neighbor_pairs",
        sa.Column("farm_low_id", sa.Uuid(), sa.ForeignKey("farm_states.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("farm_high_id", sa.Uuid(), sa.ForeignKey("farm_states.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.CheckConstraint("farm_low_id <> farm_high_id", name="ck_farm_neighbor_pairs_distinct"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM farm_neighbor_pairs)")):
        raise RuntimeError("Farm neighbour rewards exist. Disable the feature; do not delete them by downgrading.")
    op.drop_table("farm_neighbor_pairs")
