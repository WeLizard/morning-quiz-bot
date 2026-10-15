"""Account-level form of address ('m' | 'f' | 'n'); NULL means not asked yet.

Revision ID: 20261015_0030
Revises: 20261011_0029
"""
from alembic import op
import sqlalchemy as sa

revision = "20261015_0030"
down_revision = "20261011_0029"
branch_labels = None
depends_on = None


def upgrade():
    # Additive and nullable: existing accounts keep NULL and read as neutral until chosen.
    op.add_column("accounts", sa.Column("address_form", sa.String(1), nullable=True))
    op.create_check_constraint("ck_accounts_address_form", "accounts",
                               "address_form IS NULL OR address_form IN ('m', 'f', 'n')")


def downgrade():
    op.drop_constraint("ck_accounts_address_form", "accounts", type_="check")
    op.drop_column("accounts", "address_form")
