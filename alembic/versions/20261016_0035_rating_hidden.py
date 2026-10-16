"""Account flag "do not show me in the rating".

Revision ID: 20261016_0035
Revises: 20261016_0034
"""
from alembic import op
import sqlalchemy as sa

revision = "20261016_0035"
down_revision = "20261016_0034"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("accounts", sa.Column("rating_hidden", sa.Boolean(), nullable=False, server_default="false"))


def downgrade():
    op.drop_column("accounts", "rating_hidden")
