"""Separate imported Alchemy claims from server-verified progress.

Revision ID: 20261008_0016
Revises: 20261007_0015
"""
from alembic import op
import sqlalchemy as sa


revision = '20261008_0016'
down_revision = '20261007_0015'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('alchemy_progress', sa.Column(
        'verified_discovered', sa.JSON(), server_default='[]', nullable=False))
    op.add_column('alchemy_progress', sa.Column(
        'verified_crafted', sa.JSON(), server_default='[]', nullable=False))
    op.add_column('alchemy_progress', sa.Column(
        'verified_chapters', sa.JSON(), server_default='[]', nullable=False))
    op.add_column('alchemy_progress', sa.Column(
        'verified_achievements', sa.JSON(), server_default='[]', nullable=False))
    # Everyone starts with the same four base elements. No imported discovery,
    # recipe, chapter, achievement, or historical score is marked verified.
    connection = op.get_bind()
    connection.execute(sa.text(
        "UPDATE alchemy_progress SET verified_discovered = "
        "'[\"water\",\"earth\",\"fire\",\"air\"]'::json"
    ))
    op.create_table(
        'alchemy_craft_commands',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('account_id', sa.Uuid(), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ingredient_a', sa.String(64), nullable=False),
        sa.Column('ingredient_b', sa.String(64), nullable=False),
        sa.Column('result_element', sa.String(64), nullable=False),
        sa.Column('result', sa.JSON(), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('account_id', 'ingredient_a', 'ingredient_b',
                            name='uq_alchemy_craft_account_recipe'),
    )
    op.create_index('ix_alchemy_craft_commands_account_id', 'alchemy_craft_commands', ['account_id'])


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text('SELECT EXISTS (SELECT 1 FROM alchemy_craft_commands)')):
        raise RuntimeError('Cannot downgrade: server-verified Alchemy craft events exist')
    op.drop_index('ix_alchemy_craft_commands_account_id', table_name='alchemy_craft_commands')
    op.drop_table('alchemy_craft_commands')
    op.drop_column('alchemy_progress', 'verified_achievements')
    op.drop_column('alchemy_progress', 'verified_chapters')
    op.drop_column('alchemy_progress', 'verified_crafted')
    op.drop_column('alchemy_progress', 'verified_discovered')
