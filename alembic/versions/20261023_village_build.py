"""Village construction and market-row stall lots (shared, cross-farm state).

Revision ID: 20261023_village_build
Revises: 20261023_0039
"""
from alembic import op
import sqlalchemy as sa

revision = '20261023_village_build'
down_revision = '20261023_0039'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('farm_village_projects',
        sa.Column('id', sa.String(16), primary_key=True),
        sa.Column('status', sa.String(12), nullable=False), sa.Column('stage', sa.SmallInteger(), nullable=False),
        sa.Column('need', sa.JSON(), nullable=False), sa.Column('got', sa.JSON(), nullable=False),
        sa.Column('work_until', sa.BigInteger()), sa.Column('speedup', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('fund_speed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('opened_at', sa.BigInteger()), sa.Column('version', sa.Integer(), nullable=False, server_default='0'),
        sa.CheckConstraint("status IN ('soon','collecting','working','done')", name='ck_village_project_status'),
        sa.CheckConstraint('stage BETWEEN 0 AND 2 AND speedup >= 0 AND fund_speed >= 0', name='ck_village_project_stage'))
    op.create_table('farm_village_contribs',
        sa.Column('project_id', sa.String(16), sa.ForeignKey('farm_village_projects.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('account_id', sa.Uuid(), sa.ForeignKey('accounts.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('farm_id', sa.Uuid(), sa.ForeignKey('farm_states.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('value', sa.BigInteger(), nullable=False), sa.Column('share_bp', sa.BigInteger(), nullable=False),
        sa.Column('tier', sa.SmallInteger(), nullable=False), sa.Column('updated_at', sa.BigInteger(), nullable=False),
        sa.CheckConstraint('value >= 0 AND share_bp >= 0 AND tier BETWEEN 0 AND 3', name='ck_village_contrib'))
    op.create_table('farm_village_stall_lots',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('seller_farm', sa.Uuid(), sa.ForeignKey('farm_states.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('seller_account', sa.Uuid(), sa.ForeignKey('accounts.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('item', sa.String(40), nullable=False), sa.Column('qty', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.Integer(), nullable=False), sa.Column('created_at', sa.BigInteger(), nullable=False),
        sa.Column('rent_paid_until', sa.BigInteger(), nullable=False), sa.Column('status', sa.String(8), nullable=False),
        sa.Column('sold_at', sa.BigInteger()),
        sa.Column('buyer_farm', sa.Uuid(), sa.ForeignKey('farm_states.id', ondelete='RESTRICT')),
        sa.Column('closed_at', sa.BigInteger()),
        sa.CheckConstraint("status IN ('open','sold','closed')", name='ck_village_lot_status'),
        sa.CheckConstraint('qty BETWEEN 1 AND 20 AND unit_price > 0', name='ck_village_lot_amount'))
    op.create_index('ix_village_lots_open', 'farm_village_stall_lots', ['status', 'rent_paid_until'])
    op.create_index('ix_village_lots_seller', 'farm_village_stall_lots', ['seller_account', 'status'])
    op.create_index('ix_village_lots_buyer_day', 'farm_village_stall_lots', ['buyer_farm', 'seller_farm', 'sold_at'])


def downgrade():
    bind = op.get_bind()
    for table in ('farm_village_stall_lots', 'farm_village_contribs'):
        if bind.scalar(sa.text(f'SELECT EXISTS (SELECT 1 FROM {table})')):
            raise RuntimeError(f'{table} holds player history; refusing to delete it by downgrading')
    op.drop_table('farm_village_stall_lots')
    op.drop_table('farm_village_contribs')
    op.drop_table('farm_village_projects')
