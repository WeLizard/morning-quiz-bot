"""Night Case lobby talk («Обсуждение»): lines the players at the table write before the case starts."""
from alembic import op
import sqlalchemy as sa


revision = '20261126_0054'
down_revision = '20261124_0053'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'night_lobby_messages',
        sa.Column('game_id', sa.String(64), sa.ForeignKey('games.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('seq', sa.BigInteger(), nullable=False),
        sa.Column('command_id', sa.String(128), nullable=False),
        sa.Column('sender_account_id', sa.Uuid(), sa.ForeignKey('accounts.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('character_id', sa.String(96)),
        sa.Column('look_id', sa.String(96)),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('text_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('game_id', 'sender_account_id', 'command_id', name='uq_night_lobby_message_command'),
        sa.UniqueConstraint('game_id', 'seq', name='uq_night_lobby_message_seq'),
        sa.CheckConstraint('seq >= 1', name='ck_night_lobby_message_seq'),
        sa.CheckConstraint('length(text) BETWEEN 1 AND 500 AND octet_length(text) <= 2048', name='ck_night_lobby_message_text'),
    )
    op.create_index('ix_night_lobby_messages_game_time', 'night_lobby_messages', ['game_id', 'created_at'])


def downgrade():
    op.drop_index('ix_night_lobby_messages_game_time', table_name='night_lobby_messages')
    op.drop_table('night_lobby_messages')
