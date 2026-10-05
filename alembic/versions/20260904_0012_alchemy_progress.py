"""Хранилище прогресса «Алхимии»; очки идут в общий профиль пользователя.

Revision ID: 20260904_0012
Revises: 20260904_0011
"""
from alembic import op
import sqlalchemy as sa


revision = '20260904_0012'
down_revision = '20260904_0011'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('alchemy_progress',
        sa.Column('user_id', sa.BigInteger(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'),
                  primary_key=True, autoincrement=False),
        sa.Column('discovered', sa.JSON(), nullable=False),
        sa.Column('crafted', sa.JSON(), nullable=False),
        sa.Column('chapters', sa.JSON(), nullable=False),
        sa.Column('achievements', sa.JSON(), nullable=False),
        sa.Column('points_total', sa.Numeric(14, 3), nullable=False),
        sa.Column('points_today', sa.Numeric(14, 3), nullable=False),
        sa.Column('points_day', sa.Date(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False))


def downgrade():
    # Данные игры расходные: общий профиль живёт в users и не затрагивается.
    op.drop_table('alchemy_progress')
