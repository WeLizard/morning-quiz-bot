"""Version chat settings without changing existing values or scores."""
from alembic import op
import sqlalchemy as sa

revision = "20260830_0002"
down_revision = "20260830_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chats", sa.Column("settings_revision", sa.Integer(), server_default="0", nullable=False))


def downgrade():
    op.drop_column("chats", "settings_revision")
