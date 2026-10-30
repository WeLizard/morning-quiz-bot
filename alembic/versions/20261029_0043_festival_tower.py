"""The shared pie tower of a festival fair.

Revision ID: 20261029_0043
Revises: 20261028_0042
"""
from alembic import op
import sqlalchemy as sa

revision = "20261029_0043"
down_revision = "20261028_0042"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('farm_festival_towers',
        sa.Column('key', sa.String(40), primary_key=True),
        sa.Column('total', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('goal', sa.BigInteger(), nullable=False),
        sa.Column('players', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('reached_at', sa.Float(), nullable=True),
        sa.Column('updated_at', sa.Float(), nullable=False),
        sa.CheckConstraint('total >= 0 AND goal > 0 AND players >= 0', name='ck_farm_festival_tower_amounts'))


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text('SELECT EXISTS (SELECT 1 FROM farm_festival_towers)')):
        raise RuntimeError('farm_festival_towers holds shared player history; refusing to delete it by downgrading')
    op.drop_table('farm_festival_towers')
