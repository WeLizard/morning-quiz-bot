"""Preserve all legacy integer audit scopes alongside UUID Account targets.

Compatibility repair for existing 0047 databases. Unreleased 0046 has the same
canonical predicate so legacy rows also survive a fresh 0044 upgrade. Downgrade
intentionally retains this compatible CHECK rather than reinstalling the known
broken users/chats-only restriction, like the compatible repair in 0047.
"""
from alembic import op

revision = '20261116_0048'
down_revision = '20261116_0047'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('ck_admin_actions_typed_target', 'admin_actions', type_='check')
    op.create_check_constraint('ck_admin_actions_typed_target', 'admin_actions',
        "(scope = 'accounts' AND target_id IS NULL AND target_account_id IS NOT NULL) OR (scope <> 'accounts' AND target_id IS NOT NULL AND target_account_id IS NULL)")


def downgrade():
    # Keep the repaired, backward-compatible predicate on 0047 as well.
    pass
