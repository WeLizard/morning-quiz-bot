"""Add the shared game substrate and move legacy Mafia state out of system_states."""

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert


revision = '20260904_0008'
down_revision = '20260831_0007'
branch_labels = None
depends_on = None

NOW = sa.text('CURRENT_TIMESTAMP')
EMPTY_OBJECT = sa.text("'{}'::json")


def upgrade():
    op.create_table(
        'games',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('mode', sa.String(32), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('phase', sa.String(32), nullable=False),
        sa.Column('revision', sa.Integer(), server_default='0', nullable=False),
        sa.Column('state', sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column('is_current', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('ended_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_games_chat_mode_history', 'games', ['chat_id', 'mode', 'created_at'])
    op.create_index(
        'uq_games_current_chat_mode', 'games', ['chat_id', 'mode'], unique=True,
        postgresql_where=sa.text('is_current'),
    )
    op.create_table(
        'game_players',
        sa.Column('game_id', sa.String(64), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('seat', sa.String(32), nullable=False),
        sa.Column('status', sa.String(32), server_default='active', nullable=False),
        sa.Column('public_state', sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column('private_state', sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column('joined_at', sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('game_id', 'user_id'),
        sa.UniqueConstraint('game_id', 'seat', name='uq_game_player_seat'),
    )
    op.create_table(
        'game_commands',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('game_id', sa.String(64), nullable=False),
        sa.Column('actor_user_id', sa.BigInteger()),
        sa.Column('kind', sa.String(64), nullable=False),
        sa.Column('expected_revision', sa.Integer()),
        sa.Column('payload', sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column('status', sa.String(24), server_default='accepted', nullable=False),
        sa.Column('result', sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column('error', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_game_commands_game_created', 'game_commands', ['game_id', 'created_at'])
    op.create_table(
        'game_events',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('game_id', sa.String(64), nullable=False),
        sa.Column('event_index', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(64), nullable=False),
        sa.Column('visibility', sa.String(24), server_default='public', nullable=False),
        sa.Column('actor_user_id', sa.BigInteger()),
        sa.Column('payload', sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('game_id', 'event_index', name='uq_game_event_index'),
    )
    op.create_index('ix_game_events_game_created', 'game_events', ['game_id', 'created_at'])
    op.create_table(
        'game_deadlines',
        sa.Column('id', sa.String(96), nullable=False),
        sa.Column('game_id', sa.String(64), nullable=False),
        sa.Column('kind', sa.String(64), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(24), server_default='pending', nullable=False),
        sa.Column('claimed_by', sa.String(96)),
        sa.Column('claimed_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('game_id', 'kind', name='uq_game_deadline_kind'),
    )
    op.create_index('ix_game_deadlines_pending_due', 'game_deadlines', ['status', 'due_at'])
    op.create_table(
        'notification_outbox',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('game_id', sa.String(64)),
        sa.Column('chat_id', sa.BigInteger()),
        sa.Column('user_id', sa.BigInteger()),
        sa.Column('kind', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column('dedupe_key', sa.String(160), nullable=False),
        sa.Column('status', sa.String(24), server_default='pending', nullable=False),
        sa.Column('available_at', sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('claimed_by', sa.String(96)),
        sa.Column('claimed_at', sa.DateTime(timezone=True)),
        sa.Column('delivered_at', sa.DateTime(timezone=True)),
        sa.Column('last_error', sa.Text()),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dedupe_key'),
    )
    op.create_index('ix_notification_outbox_ready', 'notification_outbox', ['status', 'available_at'])
    _move_legacy_mafia()


def _move_legacy_mafia():
    bind = op.get_bind()
    meta = sa.MetaData()
    states = sa.Table('system_states', meta, autoload_with=bind)
    chats = sa.Table('chats', meta, autoload_with=bind)
    users = sa.Table('users', meta, autoload_with=bind)
    games = sa.Table('games', meta, autoload_with=bind)
    players_table = sa.Table('game_players', meta, autoload_with=bind)
    events = sa.Table('game_events', meta, autoload_with=bind)
    deadlines = sa.Table('game_deadlines', meta, autoload_with=bind)
    rows = bind.execute(sa.select(states).where(states.c.key.like('mafia_lobby:%'))).mappings().all()
    for row in rows:
        payload = row['payload']
        if not isinstance(payload, dict):
            raise RuntimeError(f"Cannot migrate malformed Mafia state {row['key']}")
        try:
            chat_id = int(row['key'].split(':', 1)[1])
        except (IndexError, ValueError) as exc:
            raise RuntimeError(f"Cannot migrate malformed Mafia key {row['key']}") from exc
        if payload.get('chat_id') != chat_id or not isinstance(payload.get('players'), list):
            raise RuntimeError(f"Cannot migrate inconsistent Mafia state {row['key']}")
        game_id = str(uuid5(NAMESPACE_URL, f'morning-quiz:{row["key"]}'))
        status = str(payload.get('status') or 'lobby')
        bind.execute(pg_insert(chats).values(
            id=chat_id, type='unknown', title='Ночной город', settings={}, statistics={},
            category_statistics={}, is_active=True,
        ).on_conflict_do_nothing(index_elements=[chats.c.id]))
        bind.execute(games.insert().values(
            id=game_id, chat_id=chat_id, mode='mafia', status=status, phase=status,
            revision=int(payload.get('revision') or 0), state=payload, is_current=True,
            started_at=row['created_at'], ended_at=row['updated_at'] if status == 'finished' else None,
            created_at=row['created_at'], updated_at=row['updated_at'],
        ))
        assignments = payload.get('assignments') if isinstance(payload.get('assignments'), dict) else {}
        alive = set(payload.get('alive') or [])
        for index, player in enumerate(payload['players'], 1):
            if not isinstance(player, dict) or type(player.get('user_id')) is not int:
                raise RuntimeError(f"Cannot migrate malformed player in {row['key']}")
            user_id = player['user_id']
            bind.execute(pg_insert(users).values(
                id=user_id, display_name=str(player.get('name') or f'User {user_id}')[:255],
                global_score=0, total_answered=0, metadata_json={},
            ).on_conflict_do_nothing(index_elements=[users.c.id]))
            bind.execute(players_table.insert().values(
                game_id=game_id, user_id=user_id, seat=f'p{index}',
                status='active' if not alive or user_id in alive else 'eliminated',
                public_state={'name': str(player.get('name') or '')[:120],
                              'ready': bool(player.get('ready'))},
                private_state={'role': assignments[str(user_id)]}
                if str(user_id) in assignments else {},
                joined_at=row['created_at'],
            ))
        history = payload.get('history') if isinstance(payload.get('history'), list) else []
        for index, event in enumerate(history, 1):
            bind.execute(events.insert().values(
                game_id=game_id, event_index=index,
                kind=str(event.get('type') if isinstance(event, dict) else 'legacy_event'),
                visibility='public', actor_user_id=None,
                payload=event if isinstance(event, dict) else {'legacy_value': event},
                created_at=row['updated_at'],
            ))
        deadline = payload.get('phase_deadline')
        if type(deadline) in {int, float}:
            bind.execute(deadlines.insert().values(
                id=f'{game_id}:phase', game_id=game_id, kind='phase',
                due_at=datetime.fromtimestamp(deadline, tz=timezone.utc), status='pending',
                revision=int(payload.get('revision') or 0),
            ))
        bind.execute(states.delete().where(states.c.key == row['key']))


def downgrade():
    bind = op.get_bind()
    noncurrent = bind.scalar(sa.text("SELECT count(*) FROM games WHERE mode = 'mafia' AND NOT is_current"))
    if noncurrent:
        raise RuntimeError('Refusing downgrade: archived Mafia games cannot fit in legacy system_states')
    bind.execute(sa.text("""
        INSERT INTO system_states (key, payload, created_at, updated_at)
        SELECT 'mafia_lobby:' || chat_id::text, state, created_at, updated_at
        FROM games WHERE mode = 'mafia' AND is_current
        ON CONFLICT (key) DO UPDATE SET payload = EXCLUDED.payload, updated_at = EXCLUDED.updated_at
    """))
    op.drop_index('ix_notification_outbox_ready', table_name='notification_outbox')
    op.drop_table('notification_outbox')
    op.drop_index('ix_game_deadlines_pending_due', table_name='game_deadlines')
    op.drop_table('game_deadlines')
    op.drop_index('ix_game_events_game_created', table_name='game_events')
    op.drop_table('game_events')
    op.drop_index('ix_game_commands_game_created', table_name='game_commands')
    op.drop_table('game_commands')
    op.drop_table('game_players')
    op.drop_index('uq_games_current_chat_mode', table_name='games')
    op.drop_index('ix_games_chat_mode_history', table_name='games')
    op.drop_table('games')
