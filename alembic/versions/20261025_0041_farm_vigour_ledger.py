"""Record M2 pool rewards independently from XP."""
from alembic import op
import sqlalchemy as sa

revision = '20261025_0041'
down_revision = '20261023_0040'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('farm_ledger', sa.Column('vigour_delta', sa.BigInteger(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('farm_ledger', 'vigour_delta')
