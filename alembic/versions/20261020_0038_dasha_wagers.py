"""Persist secret Dasha wager rounds outside farm payloads and receipts.

Revision ID: 20261020_0038
Revises: 20261018_0037
"""
from alembic import op
import sqlalchemy as sa

revision = '20261020_0038'
down_revision = '20261018_0037'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('farm_wager_rounds',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('account_id', sa.Uuid(), sa.ForeignKey('accounts.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('farm_id', sa.Uuid(), sa.ForeignKey('farm_states.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('stake', sa.Integer(), nullable=False), sa.Column('payout', sa.Integer(), nullable=False),
        sa.Column('rules_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False), sa.Column('expires_at', sa.Float(), nullable=False),
        sa.Column('winning_cup', sa.SmallInteger(), nullable=False), sa.Column('default_cup', sa.SmallInteger(), nullable=False),
        sa.Column('chosen_cup', sa.SmallInteger()), sa.Column('settled_at', sa.Float()), sa.Column('won', sa.Boolean()),
        sa.Column('pending_payout', sa.Integer(), nullable=False, server_default='0'),
        sa.CheckConstraint('(stake=10 AND payout=27) OR (stake=20 AND payout=54) OR (stake=50 AND payout=135)', name='ck_farm_wager_amounts'),
        sa.CheckConstraint('rules_version > 0 AND expires_at > created_at', name='ck_farm_wager_timing'),
        sa.CheckConstraint('winning_cup BETWEEN 0 AND 2 AND default_cup BETWEEN 0 AND 2 AND (chosen_cup IS NULL OR chosen_cup BETWEEN 0 AND 2)', name='ck_farm_wager_cups'),
        sa.CheckConstraint('(chosen_cup IS NULL AND settled_at IS NULL AND won IS NULL) OR (chosen_cup IS NOT NULL AND settled_at IS NOT NULL AND won IS NOT NULL AND won = (chosen_cup = winning_cup))', name='ck_farm_wager_phase'),
        sa.CheckConstraint('pending_payout BETWEEN 0 AND 135 AND (pending_payout=0 OR (settled_at IS NOT NULL AND won IS TRUE))', name='ck_farm_wager_pending_payout'))
    op.create_index('uq_farm_wager_active_account', 'farm_wager_rounds', ['account_id'], unique=True,
                    postgresql_where=sa.text('settled_at IS NULL'))
    op.create_index('ix_farm_wager_daily', 'farm_wager_rounds', ['account_id', 'created_at'])


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT EXISTS (SELECT 1 FROM farm_wager_rounds)')):
        raise RuntimeError('Dasha wager history exists; refusing to delete it by downgrading')
    op.drop_index('ix_farm_wager_daily', table_name='farm_wager_rounds')
    op.drop_index('uq_farm_wager_active_account', table_name='farm_wager_rounds')
    op.drop_table('farm_wager_rounds')
