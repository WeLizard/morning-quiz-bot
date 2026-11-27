"""Night Case presence: when each player last had the case open («в сети», «был недавно»)."""
from alembic import op
import sqlalchemy as sa


revision = '20261127_0055'
down_revision = '20261126_0054'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'night_presence',
        sa.Column('game_id', sa.String(64), sa.ForeignKey('games.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('account_id', sa.Uuid(), sa.ForeignKey('accounts.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('seen_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table('night_presence')
