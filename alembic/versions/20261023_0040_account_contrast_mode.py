"""Account flag «Контрастный режим» (accessibility; one switch for the hub and every game).

Revision ID: 20261023_0040
Revises: 20261023_village_build
"""
from alembic import op
import sqlalchemy as sa

revision = "20261023_0040"
down_revision = "20261023_village_build"
branch_labels = None
depends_on = None


def upgrade():
    # Additive with a server default: existing accounts keep the default style.
    op.add_column("accounts", sa.Column("contrast_mode", sa.Boolean(), nullable=False, server_default="false"))


def downgrade():
    op.drop_column("accounts", "contrast_mode")
