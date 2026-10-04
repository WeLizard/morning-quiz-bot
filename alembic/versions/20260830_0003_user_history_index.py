"""Index per-user event history; no changes to stored answers or scores."""
from alembic import op

revision = '20260830_0003'
down_revision = '20260830_0002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_poll_answers_user_answered', 'poll_answers', ['user_id', 'answered_at', 'poll_id'])


def downgrade():
    op.drop_index('ix_poll_answers_user_answered', table_name='poll_answers')
