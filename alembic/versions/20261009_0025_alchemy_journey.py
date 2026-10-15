"""Verified expedition claims; allow craft re-verification by new command id."""
from alembic import op
import sqlalchemy as sa

revision = '20261009_0025'
down_revision = 'qw_farm_011'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('uq_alchemy_craft_account_recipe', 'alchemy_craft_commands', type_='unique')
    op.create_table('alchemy_stage_claims',
        sa.Column('account_id', sa.Uuid(), sa.ForeignKey('accounts.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('stage_id', sa.String(64), primary_key=True),
        sa.Column('campaign_id', sa.String(64), nullable=False),
        sa.Column('catalog_revision', sa.String(64), nullable=False),
        sa.Column('reward', sa.JSON(), nullable=False),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('alchemy_claim_commands',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('account_id', sa.Uuid(), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_alchemy_claim_commands_account_id', 'alchemy_claim_commands', ['account_id'])


def downgrade():
    connection = op.get_bind()
    if (connection.scalar(sa.text('SELECT EXISTS (SELECT 1 FROM alchemy_stage_claims)'))
            or connection.scalar(sa.text('SELECT EXISTS (SELECT 1 FROM alchemy_claim_commands)'))
            or connection.scalar(sa.text('SELECT EXISTS (SELECT 1 FROM alchemy_craft_commands GROUP BY account_id, ingredient_a, ingredient_b HAVING count(*) > 1)'))):
        raise RuntimeError('Preserve expedition receipts and repeated craft commands before downgrade')
    op.drop_index('ix_alchemy_claim_commands_account_id', table_name='alchemy_claim_commands')
    op.drop_table('alchemy_claim_commands')
    op.drop_table('alchemy_stage_claims')
    op.create_unique_constraint('uq_alchemy_craft_account_recipe', 'alchemy_craft_commands',
                                ['account_id', 'ingredient_a', 'ingredient_b'])
