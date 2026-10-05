"""Серия дней с закрытой целью дня в «Алхимии».

Revision ID: 20260904_0013
Revises: 20260904_0012
"""

from alembic import op
import sqlalchemy as sa


revision = '20260904_0013'
down_revision = '20260904_0012'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('alchemy_progress', sa.Column(
        'goal_streak', sa.Integer(), server_default='0', nullable=False))
    op.add_column('alchemy_progress', sa.Column('last_goal_day', sa.Date(), nullable=True))


def downgrade():
    op.drop_column('alchemy_progress', 'last_goal_day')
    op.drop_column('alchemy_progress', 'goal_streak')
