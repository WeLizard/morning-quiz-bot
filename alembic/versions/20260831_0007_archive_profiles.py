"""Recoverable profile removal; preserve scores, ledger and achievements."""
from alembic import op
import sqlalchemy as sa

revision = '20260831_0007'
down_revision = '20260830_0006'
branch_labels = None
depends_on = None


def upgrade():
    for table in ('users', 'chats'):
        op.add_column(table, sa.Column('archived', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    for table in ('chats', 'users'):
        op.drop_column(table, 'archived')
