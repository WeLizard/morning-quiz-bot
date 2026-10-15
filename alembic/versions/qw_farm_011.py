"""Add shared ephemeral ingress/account quotas; no player state changes."""
from alembic import op
import sqlalchemy as sa

revision = 'qw_farm_011'
down_revision = '20261009_0024'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('farm_rate_buckets',
        sa.Column('scope', sa.String(16), primary_key=True),
        sa.Column('subject', sa.String(64), primary_key=True),
        sa.Column('timestamps', sa.JSON(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scope IN ('ip_read','ip_write','account_read','account_write')",
                           name='ck_farm_rate_scope'))
    op.create_index('ix_farm_rate_expiry', 'farm_rate_buckets', ['expires_at'])


def downgrade():
    raise RuntimeError('Disable QW_FARM_SHARED_RATE_ENABLED; retain the additive quota table.')
