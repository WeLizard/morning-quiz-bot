"""Independent accounts and opaque guest sessions.

Revision ID: 20261007_0014
Revises: 20260904_0013
"""
from uuid import uuid4
from alembic import op
import sqlalchemy as sa

revision = '20261007_0014'
down_revision = '20260904_0013'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('accounts',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('archived', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('bot_blocked', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('moderation_revision', sa.Integer(), server_default='0', nullable=False),
        sa.Column('moderation_reason', sa.Text(), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column('users', sa.Column('account_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_users_account_id', 'users', 'accounts', ['account_id'], ['id'], ondelete='RESTRICT')
    op.create_unique_constraint('uq_users_account_id', 'users', ['account_id'])
    # Python UUID avoids requiring pgcrypto or a particular PostgreSQL version.
    connection = op.get_bind()
    users = sa.table('users', sa.column('id', sa.BigInteger()), sa.column('account_id', sa.Uuid()))
    accounts = sa.table('accounts', sa.column('id', sa.Uuid()), sa.column('display_name'),
        sa.column('archived'), sa.column('bot_blocked'), sa.column('moderation_revision'),
        sa.column('moderation_reason'), sa.column('created_at'), sa.column('updated_at'))
    rows = connection.execute(sa.text('SELECT id, display_name, archived, bot_blocked, moderation_revision, moderation_reason, created_at, updated_at FROM users')).mappings()
    for row in rows:
        account_id = uuid4()
        connection.execute(accounts.insert().values(id=account_id, **{k: v for k, v in row.items() if k != 'id'}))
        connection.execute(users.update().where(users.c.id == row['id']).values(account_id=account_id))
    op.create_table('guest_sessions',
        sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('account_id', sa.Uuid(), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('account_revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked', sa.Boolean(), server_default='false', nullable=False))
    op.create_index('ix_guest_sessions_account_id', 'guest_sessions', ['account_id'])
    op.create_index('ix_guest_sessions_expires_at', 'guest_sessions', ['expires_at'])


def downgrade():
    if op.get_bind().scalar(sa.text(
            'SELECT EXISTS (SELECT 1 FROM accounts a LEFT JOIN users u ON u.account_id = a.id WHERE u.id IS NULL)')):
        raise RuntimeError('Cannot downgrade: independent accounts exist; export or explicitly resolve guest data first')
    op.drop_table('guest_sessions')
    op.drop_constraint('uq_users_account_id', 'users', type_='unique')
    op.drop_constraint('fk_users_account_id', 'users', type_='foreignkey')
    op.drop_column('users', 'account_id')
    op.drop_table('accounts')
