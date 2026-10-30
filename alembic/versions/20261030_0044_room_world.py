"""The story (world pack) of a Night City room.

Revision ID: 20261030_0044
Revises: 20261029_0043
"""
from alembic import op
import sqlalchemy as sa

revision = "20261030_0044"
down_revision = "20261029_0043"
branch_labels = None
depends_on = None


def upgrade():
    # Existing rooms keep the pilot world. The list of valid ids lives in domain/night_worlds.py.
    op.add_column("rooms", sa.Column("world", sa.String(32), nullable=False, server_default="manor_lake"))


def downgrade():
    op.drop_column("rooms", "world")
