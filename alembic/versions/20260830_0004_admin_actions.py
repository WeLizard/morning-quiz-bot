"""Effective moderation and immutable reset receipts; preserve all history."""
from alembic import op
import sqlalchemy as sa

revision = '20260830_0004'
down_revision = '20260830_0003'
branch_labels = None
depends_on = None


def upgrade():
    for table in ('users', 'chats'):
        op.add_column(table, sa.Column('bot_blocked', sa.Boolean(), server_default=sa.false(), nullable=False))
        op.add_column(table, sa.Column('moderation_revision', sa.Integer(), server_default='0', nullable=False))
        op.add_column(table, sa.Column('moderation_reason', sa.Text(), server_default='', nullable=False))
    op.create_table('admin_actions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('scope', sa.String(16), nullable=False),
        sa.Column('target_id', sa.BigInteger(), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('request', sa.JSON(), nullable=False),
        sa.Column('before', sa.JSON(), nullable=False),
        sa.Column('after', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_admin_actions_target', 'admin_actions', ['scope', 'target_id', 'created_at'])


def downgrade():
    op.drop_table('admin_actions')
    for table in ('users', 'chats'):
        for column in ('moderation_reason', 'moderation_revision', 'bot_blocked'):
            op.drop_column(table, column)
