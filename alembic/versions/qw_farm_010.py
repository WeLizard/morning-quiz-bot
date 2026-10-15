"""Add the original Farm aggregate tables to the QuizzyWizzy platform.

Farm 0.2.0 only extends the versioned JSON payload, so it needs no second
table migration. Never downgrade a database that contains player farms.
"""
from alembic import op
import sqlalchemy as sa

revision = 'qw_farm_010'
down_revision = '20261008_0021'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('farm_states',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('account_id', sa.Uuid(), sa.ForeignKey('accounts.id', ondelete='RESTRICT'), nullable=False, unique=True),
        sa.Column('name', sa.String(28), nullable=False),
        sa.Column('coins', sa.BigInteger(), nullable=False),
        sa.Column('xp', sa.BigInteger(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('visibility', sa.String(10), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.CheckConstraint('coins >= 0 AND coins <= 1000000000000', name='ck_farm_coins'),
        sa.CheckConstraint('xp >= 0', name='ck_farm_xp'),
        sa.CheckConstraint('revision >= 0', name='ck_farm_revision'),
        sa.CheckConstraint("visibility IN ('private','friends','public')", name='ck_farm_visibility'))
    op.create_index('ix_farm_states_public', 'farm_states', ['visibility', 'name'])
    op.create_table('farm_receipts',
        sa.Column('account_id', sa.Uuid(), sa.ForeignKey('accounts.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('command_id', sa.String(64), primary_key=True),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False))
    op.create_table('farm_ledger',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('farm_id', sa.Uuid(), sa.ForeignKey('farm_states.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('actor_account_id', sa.Uuid(), sa.ForeignKey('accounts.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('command_id', sa.String(64), nullable=False),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('coins_delta', sa.BigInteger(), nullable=False),
        sa.Column('coins_after', sa.BigInteger(), nullable=False),
        sa.Column('inventory_delta', sa.JSON(), nullable=False),
        sa.Column('xp_delta', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('farm_id', 'actor_account_id', 'command_id', name='uq_farm_ledger_command'))
    op.create_index('ix_farm_ledger_history', 'farm_ledger', ['farm_id', 'created_at'])


def downgrade():
    conn = op.get_bind()
    if conn.scalar(sa.text('SELECT EXISTS(SELECT 1 FROM farm_states)')):
        raise RuntimeError('Farm data exists. Disable the feature; do not delete player farms by downgrading.')
    op.drop_index('ix_farm_ledger_history', table_name='farm_ledger')
    op.drop_table('farm_ledger')
    op.drop_table('farm_receipts')
    op.drop_index('ix_farm_states_public', table_name='farm_states')
    op.drop_table('farm_states')
