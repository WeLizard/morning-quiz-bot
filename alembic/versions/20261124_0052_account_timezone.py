"""Store an optional IANA timezone preference on each account."""
from alembic import op
import sqlalchemy as sa


revision = '20261124_0052'
down_revision = '20261124_0051'
branch_labels = None
depends_on = None


def upgrade():
    # Existing accounts remain unset and keep their current device-derived default.
    op.add_column('accounts', sa.Column('timezone', sa.String(64), nullable=True))


def downgrade():
    op.drop_column('accounts', 'timezone')
