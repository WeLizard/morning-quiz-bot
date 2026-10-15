"""Farm r9 stage 14: the shared village-fund counter (one row per 28-day season).

Additive only: a new table, no change to farm_states / farm_receipts / farm_ledger.
Each farm's own fund state lives in its JSON payload (``economy``); this table holds only the shared counter that the
service increments atomically (``total = total + :v``) without locking any farm.

Revision ID: 20261010_0027
Revises: 20261009_0026
"""
from alembic import op
import sqlalchemy as sa


revision = "20261010_0027"
down_revision = "20261009_0026"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "farm_village",
        sa.Column("season", sa.Integer(), primary_key=True),
        sa.Column("total", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("goal", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.CheckConstraint("total >= 0 AND goal > 0", name="ck_farm_village_amounts"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM farm_village)")):
        raise RuntimeError("Village fund counters exist. Disable the feature; do not delete them by downgrading.")
    op.drop_table("farm_village")
