"""Add sparse account-wide game preferences."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '20261124_0053'
down_revision = '20261124_0052'
branch_labels = None
depends_on = None


def upgrade():
    # Existing accounts start with no overrides and keep each game's legacy setting.
    op.add_column('accounts', sa.Column(
        'game_preferences', postgresql.JSONB(), nullable=False,
        server_default=sa.text("'{}'::jsonb")))


def downgrade():
    op.drop_column('accounts', 'game_preferences')
