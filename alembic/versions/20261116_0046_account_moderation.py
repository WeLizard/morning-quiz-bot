"""Typed Account moderation targets and real operator registration provenance.

Unreleased 0046 repair: preserve every legacy integer audit scope, including
system/broadcast/categories/farm_upkeep. An old integer 'accounts' namespace
cannot be interpreted as a UUID target and is rejected without rewriting rows.
0048 applies the same compatible predicate to databases already on original0047.
"""
from alembic import op
import sqlalchemy as sa

revision = '20261116_0046'
down_revision = '20261115_0045'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM admin_actions WHERE scope='accounts') THEN
          RAISE EXCEPTION 'typed_audit_legacy_accounts_conflict: integer accounts audit requires explicit review';
        END IF;
    END $$""")
    op.alter_column('admin_actions','target_id',existing_type=sa.BigInteger(),nullable=True)
    op.add_column('admin_actions',sa.Column('target_account_id',sa.Uuid(),sa.ForeignKey('accounts.id',ondelete='RESTRICT')))
    op.create_index('ix_admin_actions_account_target','admin_actions',['target_account_id','created_at'])
    op.create_check_constraint('ck_admin_actions_typed_target','admin_actions',
        "(scope = 'accounts' AND target_id IS NULL AND target_account_id IS NOT NULL) OR (scope <> 'accounts' AND target_id IS NOT NULL AND target_account_id IS NULL)")
    op.alter_column('night_cases','registered_by',existing_type=sa.Uuid(),nullable=True)
    op.add_column('night_cases',sa.Column('registered_operator_id',sa.String(128)))
    op.create_check_constraint('ck_night_case_registration_principal','night_cases',
        'registered_by IS NOT NULL OR registered_operator_id IS NOT NULL')
    op.create_check_constraint('ck_night_case_operator_namespace','night_cases',
        "registered_operator_id IS NULL OR (registered_operator_id LIKE 'operator:%' AND length(registered_operator_id) > 9)")


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM admin_actions WHERE target_account_id IS NOT NULL)
           OR EXISTS (SELECT 1 FROM night_cases WHERE registered_operator_id IS NOT NULL OR registered_by IS NULL)
        THEN RAISE EXCEPTION 'typed_audit_retained: account/operator audit cannot be downgraded'; END IF;
    END $$""")
    op.drop_constraint('ck_night_case_operator_namespace','night_cases')
    op.drop_constraint('ck_night_case_registration_principal','night_cases')
    op.drop_column('night_cases','registered_operator_id')
    op.alter_column('night_cases','registered_by',existing_type=sa.Uuid(),nullable=False)
    op.drop_constraint('ck_admin_actions_typed_target','admin_actions')
    op.drop_index('ix_admin_actions_account_target',table_name='admin_actions')
    op.drop_column('admin_actions','target_account_id')
    op.alter_column('admin_actions','target_id',existing_type=sa.BigInteger(),nullable=False)
