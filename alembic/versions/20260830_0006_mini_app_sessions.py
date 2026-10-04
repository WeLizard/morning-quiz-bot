"""Add isolated Mini App sessions; no changes to scores, games or historical data."""
from alembic import op
import sqlalchemy as sa

revision = '20260830_0006'
down_revision = '20260830_0005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('mini_app_sessions',
        sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('bot_key_id', sa.String(64), nullable=False),
        sa.Column('init_data_hash', sa.String(64), nullable=False),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_revision', sa.Integer(), nullable=False),
        sa.Column('auth_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked', sa.Boolean(), server_default='false', nullable=False),
        sa.UniqueConstraint('bot_key_id', 'init_data_hash', name='uq_mini_app_init_data'))
    op.create_index('ix_mini_app_sessions_user_expiry', 'mini_app_sessions', ['user_id', 'expires_at'])
    op.create_index('ix_mini_app_sessions_expiry', 'mini_app_sessions', ['expires_at'])


def downgrade():
    # Only disposable login sessions; operational data is not part of this table.
    op.drop_table('mini_app_sessions')
