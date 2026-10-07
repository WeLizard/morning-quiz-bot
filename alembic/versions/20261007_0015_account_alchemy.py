"""Account-owned Alchemy progress, preserving existing Telegram rewards.

Revision ID: 20261007_0015
Revises: 20261007_0014
"""
from uuid import uuid4
from alembic import op
import sqlalchemy as sa

revision = '20261007_0015'
down_revision = '20261007_0014'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    # Users created after 0014 by the bot may still have a nullable account_id.
    accounts = sa.table('accounts', sa.column('id', sa.Uuid()), sa.column('display_name'),
        sa.column('archived'), sa.column('bot_blocked'), sa.column('moderation_revision'),
        sa.column('moderation_reason'), sa.column('created_at'), sa.column('updated_at'))
    users = sa.table('users', sa.column('id', sa.BigInteger()), sa.column('account_id', sa.Uuid()))
    rows = connection.execute(sa.text('SELECT u.* FROM users u JOIN alchemy_progress p ON p.user_id = u.id WHERE u.account_id IS NULL')).mappings()
    fields = ('display_name', 'archived', 'bot_blocked', 'moderation_revision', 'moderation_reason', 'created_at', 'updated_at')
    for row in rows:
        account_id = uuid4()
        connection.execute(accounts.insert().values(id=account_id, **{key: row[key] for key in fields}))
        connection.execute(users.update().where(users.c.id == row['id']).values(account_id=account_id))
    op.add_column('alchemy_progress', sa.Column('account_id', sa.Uuid(), nullable=True))
    op.add_column('alchemy_progress', sa.Column('attempts', sa.Integer(), server_default='0', nullable=False))
    connection.execute(sa.text('UPDATE alchemy_progress p SET account_id = u.account_id FROM users u WHERE p.user_id = u.id'))
    op.alter_column('alchemy_progress', 'account_id', nullable=False)
    op.create_foreign_key('fk_alchemy_progress_account_id', 'alchemy_progress', 'accounts', ['account_id'], ['id'], ondelete='CASCADE')
    op.drop_constraint('alchemy_progress_pkey', 'alchemy_progress', type_='primary')
    op.alter_column('alchemy_progress', 'user_id', nullable=True)
    op.create_primary_key('alchemy_progress_pkey', 'alchemy_progress', ['account_id'])
    op.create_unique_constraint('uq_alchemy_progress_user_id', 'alchemy_progress', ['user_id'])


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT EXISTS (SELECT 1 FROM alchemy_progress WHERE user_id IS NULL)')):
        raise RuntimeError('Cannot downgrade: guest Alchemy progress exists; export or explicitly resolve guest data first')
    op.drop_constraint('alchemy_progress_pkey', 'alchemy_progress', type_='primary')
    op.drop_constraint('uq_alchemy_progress_user_id', 'alchemy_progress', type_='unique')
    op.alter_column('alchemy_progress', 'user_id', nullable=False)
    op.create_primary_key('alchemy_progress_pkey', 'alchemy_progress', ['user_id'])
    op.drop_constraint('fk_alchemy_progress_account_id', 'alchemy_progress', type_='foreignkey')
    op.drop_column('alchemy_progress', 'account_id')
    op.drop_column('alchemy_progress', 'attempts')
