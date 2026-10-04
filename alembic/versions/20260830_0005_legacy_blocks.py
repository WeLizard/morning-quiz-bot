"""Promote preserved blacklist entries; no deletion of source or profile history."""
from alembic import op
import sqlalchemy as sa

revision = '20260830_0005'
down_revision = '20260830_0004'
branch_labels = None
depends_on = None


def upgrade():
    # Additive backfill for already imported local stores. Importer also covers
    # future empty-store imports performed after all migrations have run.
    from storage.legacy_moderation import legacy_block_statements
    from storage.models import SystemState
    bind = op.get_bind()
    row = bind.execute(sa.select(SystemState.payload).where(SystemState.key == 'blacklist')).first()
    if row is not None:
        for statement in legacy_block_statements(row[0]):
            bind.execute(statement)


def downgrade():
    # Never silently unblock people or erase newer moderation decisions.
    pass
