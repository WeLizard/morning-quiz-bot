"""Add separate nonterminal offline quarantine receipts; preserve outbox data."""
from alembic import op
import sqlalchemy as sa

revision = '20261009_0023'
down_revision = '20261009_0022'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'notification_quarantine_receipts',
        sa.Column('action_id', sa.String(96), primary_key=True),
        sa.Column('item_id', sa.String(64), nullable=False),
        sa.Column('request_fingerprint', sa.String(64), nullable=False),
        sa.Column('operator_id', sa.String(96), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.Column('previous_version', sa.Integer(), nullable=False),
        sa.Column('resulting_version', sa.Integer(), nullable=False),
        sa.Column('claimed_by', sa.String(96)),
        sa.Column('claimed_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    raise RuntimeError('Quarantine receipts require an explicit archival migration.')
