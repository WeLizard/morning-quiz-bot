"""Add standalone Classic answer ledger without rewriting Telegram data."""
from alembic import op
import sqlalchemy as sa

revision = '20261009_0024'
down_revision = '20261009_0023'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'classic_account_answers',
        sa.Column('game_id', sa.String(64), sa.ForeignKey('games.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('round_id', sa.String(64), primary_key=True),
        sa.Column('account_id', sa.Uuid(), sa.ForeignKey('accounts.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('selected_option', sa.Integer(), nullable=False),
        sa.Column('is_correct', sa.Boolean(), nullable=False),
        sa.Column('points_delta', sa.Numeric(18, 6), nullable=False),
        sa.Column('answered_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('selected_option BETWEEN 0 AND 9', name='ck_classic_account_answer_option'),
    )


def downgrade():
    raise RuntimeError('Classic answers require an explicit archival migration.')
