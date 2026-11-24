"""Store browser and Mini App sessions in a single table."""
from alembic import op
import sqlalchemy as sa


revision = '20261124_0051'
down_revision = '20261116_0050'
branch_labels = None
depends_on = None

_BROWSER_COLUMNS = 'token_hash, account_id, account_revision, created_at, expires_at, revoked, created_via, user_agent'
_MINI_COLUMNS = 'token_hash, bot_key_id, init_data_hash, user_id, user_revision, auth_date, created_at, expires_at, revoked'


def upgrade():
    op.execute('LOCK TABLE guest_sessions, mini_app_sessions IN ACCESS EXCLUSIVE MODE')
    op.create_table(
        'account_sessions',
        sa.Column('kind', sa.String(16), primary_key=True),
        sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('account_id', sa.Uuid(), sa.ForeignKey('accounts.id', ondelete='CASCADE')),
        sa.Column('account_revision', sa.Integer()),
        sa.Column('created_via', sa.String(16)),
        sa.Column('user_agent', sa.String(120)),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE')),
        sa.Column('user_revision', sa.Integer()),
        sa.Column('bot_key_id', sa.String(64)),
        sa.Column('init_data_hash', sa.String(64)),
        sa.Column('auth_date', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked', sa.Boolean(), server_default='false', nullable=False),
        sa.CheckConstraint(
            "(kind = 'browser' AND account_id IS NOT NULL AND account_revision IS NOT NULL "
            "AND user_id IS NULL AND user_revision IS NULL AND bot_key_id IS NULL "
            "AND init_data_hash IS NULL AND auth_date IS NULL) OR "
            "(kind = 'mini' AND account_id IS NULL AND account_revision IS NULL "
            "AND created_via IS NULL AND user_agent IS NULL AND user_id IS NOT NULL "
            "AND user_revision IS NOT NULL AND bot_key_id IS NOT NULL "
            "AND init_data_hash IS NOT NULL AND auth_date IS NOT NULL)",
            name='ck_account_sessions_kind_fields',
        ),
    )
    op.execute(
        f"INSERT INTO account_sessions (kind, {_BROWSER_COLUMNS}) SELECT 'browser', {_BROWSER_COLUMNS} FROM guest_sessions"
    )
    op.execute(
        f"INSERT INTO account_sessions (kind, {_MINI_COLUMNS}) SELECT 'mini', {_MINI_COLUMNS} FROM mini_app_sessions"
    )
    browser = sa.text("kind = 'browser'")
    mini = sa.text("kind = 'mini'")
    op.create_index('ix_account_sessions_account_id', 'account_sessions', ['account_id'], postgresql_where=browser)
    op.create_index('ix_account_sessions_browser_expiry', 'account_sessions', ['expires_at'], postgresql_where=browser)
    op.create_index('ix_account_sessions_mini_user_expiry', 'account_sessions', ['user_id', 'expires_at'],
                    postgresql_where=mini)
    op.create_index('ix_account_sessions_mini_expiry', 'account_sessions', ['expires_at'], postgresql_where=mini)
    op.create_index('uq_account_sessions_mini_init_data', 'account_sessions', ['bot_key_id', 'init_data_hash'],
                    unique=True, postgresql_where=mini)
    op.drop_table('mini_app_sessions')
    op.drop_table('guest_sessions')


def downgrade():
    op.execute('LOCK TABLE account_sessions IN ACCESS EXCLUSIVE MODE')
    op.create_table(
        'guest_sessions',
        sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('account_id', sa.Uuid(), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('account_revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_via', sa.String(16)),
        sa.Column('user_agent', sa.String(120)),
    )
    op.create_index('ix_guest_sessions_account_id', 'guest_sessions', ['account_id'])
    op.create_index('ix_guest_sessions_expires_at', 'guest_sessions', ['expires_at'])
    op.create_table(
        'mini_app_sessions',
        sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('bot_key_id', sa.String(64), nullable=False),
        sa.Column('init_data_hash', sa.String(64), nullable=False),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_revision', sa.Integer(), nullable=False),
        sa.Column('auth_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked', sa.Boolean(), server_default='false', nullable=False),
        sa.UniqueConstraint('bot_key_id', 'init_data_hash', name='uq_mini_app_init_data'),
    )
    op.create_index('ix_mini_app_sessions_user_expiry', 'mini_app_sessions', ['user_id', 'expires_at'])
    op.create_index('ix_mini_app_sessions_expiry', 'mini_app_sessions', ['expires_at'])
    op.execute(
        f"INSERT INTO guest_sessions ({_BROWSER_COLUMNS}) SELECT {_BROWSER_COLUMNS} FROM account_sessions WHERE kind = 'browser'"
    )
    op.execute(
        f"INSERT INTO mini_app_sessions ({_MINI_COLUMNS}) SELECT {_MINI_COLUMNS} FROM account_sessions WHERE kind = 'mini'"
    )
    op.drop_table('account_sessions')
