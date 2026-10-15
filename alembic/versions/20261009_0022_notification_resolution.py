"""Add operator resolution receipts; never reinterpret existing outbox rows."""
from alembic import op
import sqlalchemy as sa

revision = '20261009_0022'
down_revision = 'qw_farm_010'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('notification_outbox', sa.Column('version', sa.Integer(), server_default='0', nullable=False))
    op.add_column('notification_outbox', sa.Column('resolved_at', sa.DateTime(timezone=True)))
    op.create_table(
        'notification_resolutions',
        sa.Column('action_id', sa.String(96), primary_key=True),
        sa.Column('item_id', sa.String(64), nullable=False, unique=True),
        sa.Column('request_fingerprint', sa.String(64), nullable=False),
        sa.Column('operator_id', sa.String(96), nullable=False),
        sa.Column('decision', sa.String(32), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.Column('previous_version', sa.Integer(), nullable=False),
        sa.Column('resulting_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("decision IN ('confirmed_delivered', 'closed_without_resend')", name='ck_notification_resolution_decision'),
    )


def downgrade():
    # Removing receipts would erase the operator's audit trail.
    raise RuntimeError('Notification resolution receipts require an explicit archival migration.')
