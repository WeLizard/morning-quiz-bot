"""Move classic runtime envelopes to games and add transport delivery bindings."""

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision = '20260904_0010'
down_revision = '20260904_0009'
branch_labels = None
depends_on = None

NOW = sa.text('CURRENT_TIMESTAMP')
EMPTY_OBJECT = sa.text("'{}'::json")


def _round_id(poll_id: str) -> str:
    return poll_id if len(poll_id) <= 64 else 'legacy-' + sha256(poll_id.encode()).hexdigest()[:48]


def _deadline_id(game_id: str, kind: str) -> str:
    value = f'{game_id}:{kind}'
    return value if len(value) <= 96 else f'{game_id}:{sha256(kind.encode()).hexdigest()[:24]}'


def upgrade():
    op.create_table(
        'game_deliveries',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('game_id', sa.String(64), nullable=False),
        sa.Column('round_id', sa.String(64), nullable=False),
        sa.Column('channel', sa.String(24), nullable=False),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('external_id', sa.String(255)),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('message_id', sa.BigInteger()),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('metadata_json', sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'game_id', 'round_id', 'channel', 'kind', name='uq_game_delivery_effect'
        ),
        sa.UniqueConstraint('channel', 'external_id', name='uq_game_delivery_external'),
    )
    op.create_index(
        'ix_game_deliveries_game_created', 'game_deliveries', ['game_id', 'created_at']
    )
    op.add_column('poll_answers', sa.Column('game_id', sa.String(64)))
    op.add_column('poll_answers', sa.Column('round_id', sa.String(64)))
    op.create_foreign_key(
        'fk_poll_answers_game_id_games', 'poll_answers', 'games', ['game_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'uq_poll_answers_game_round_user', 'poll_answers',
        ['game_id', 'round_id', 'user_id'], unique=True,
        postgresql_where=sa.text('game_id IS NOT NULL'),
    )
    _move_classic_sessions()


def _move_classic_sessions():
    bind = op.get_bind()
    meta = sa.MetaData()
    sessions = sa.Table('quiz_sessions', meta, autoload_with=bind)
    games = sa.Table('games', meta, autoload_with=bind)
    events = sa.Table('game_events', meta, autoload_with=bind)
    deadlines = sa.Table('game_deadlines', meta, autoload_with=bind)
    deliveries = sa.Table('game_deliveries', meta, autoload_with=bind)
    answers = sa.Table('poll_answers', meta, autoload_with=bind)
    rows = bind.execute(
        sa.select(sessions).where(sessions.c.kind != 'photo')
        .order_by(sessions.c.chat_id, sessions.c.updated_at.desc(), sessions.c.id)
    ).mappings().all()
    current_by_chat: set[int] = set()
    for row in rows:
        state = deepcopy(row['state'])
        if not isinstance(state, dict):
            raise RuntimeError(f'Cannot migrate malformed classic session {row["id"]}')
        chat_id = row['chat_id']
        game_id = str(uuid5(
            NAMESPACE_URL,
            f'morning-quiz:classic:{chat_id}:{row["id"]}:{row["created_at"].isoformat()}',
        ))
        status = str(row['status'] or 'interrupted')
        phase = str(state.get('storage_phase') or ('finished' if status != 'active' else 'between'))
        is_current = chat_id not in current_by_chat
        current_by_chat.add(chat_id)
        bind.execute(games.insert().values(
            id=game_id,
            chat_id=chat_id,
            mode='classic',
            status=status,
            phase=phase,
            revision=int(state.get('revision') or 0),
            state=state,
            is_current=is_current,
            started_at=row['started_at'],
            ended_at=row['updated_at'] if status != 'active' else None,
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        ))
        bind.execute(events.insert().values(
            game_id=game_id,
            event_index=1,
            kind='legacy_classic_migrated',
            visibility='private',
            actor_user_id=None,
            payload={'legacy_session_id': row['id'], 'revision': int(state.get('revision') or 0)},
            created_at=row['updated_at'],
        ))
        polls = state.get('polls') if isinstance(state.get('polls'), dict) else {}
        active = set(state.get('active_poll_ids_in_session') or [])
        for poll_id, poll in polls.items():
            if not isinstance(poll_id, str) or not isinstance(poll, dict):
                continue
            round_id = _round_id(poll_id)
            message_id = poll.get('message_id')
            bind.execute(deliveries.insert().values(
                id=str(uuid5(NAMESPACE_URL, f'morning-quiz:delivery:{game_id}:{poll_id}')),
                game_id=game_id,
                round_id=round_id,
                channel='telegram',
                kind='quiz_poll',
                external_id=poll_id,
                chat_id=chat_id,
                message_id=message_id if type(message_id) is int else None,
                status='sent',
                metadata_json={
                    'legacy': True,
                    'legacy_poll_id': poll_id,
                    'option_persistent_ids': poll.get('option_persistent_ids') or [],
                },
                created_at=row['created_at'],
                updated_at=row['updated_at'],
            ))
            deadline = poll.get('end_timestamp')
            if poll_id in active and type(deadline) in {int, float}:
                kind = 'legacy-close:' + sha256(poll_id.encode()).hexdigest()[:24]
                bind.execute(deadlines.insert().values(
                    id=_deadline_id(game_id, kind),
                    game_id=game_id,
                    kind=kind,
                    due_at=datetime.fromtimestamp(deadline, tz=timezone.utc),
                    status='pending',
                    revision=int(state.get('revision') or 0),
                ))
            bind.execute(
                answers.update().where(answers.c.poll_id == poll_id).values(
                    game_id=game_id, round_id=round_id
                )
            )
        next_at = state.get('next_question_at')
        if status == 'active' and isinstance(next_at, str):
            try:
                due_at = datetime.fromisoformat(next_at)
                if due_at.tzinfo is None:
                    due_at = due_at.replace(tzinfo=timezone.utc)
            except ValueError as exc:
                raise RuntimeError(
                    f'Cannot migrate invalid classic deadline in {row["id"]}'
                ) from exc
            kind = 'legacy-advance'
            bind.execute(deadlines.insert().values(
                id=_deadline_id(game_id, kind), game_id=game_id, kind=kind,
                due_at=due_at, status='pending',
                revision=int(state.get('revision') or 0),
            ))
        bind.execute(sessions.delete().where(sessions.c.id == row['id']))


def downgrade():
    bind = op.get_bind()
    count = bind.scalar(sa.text("SELECT count(*) FROM games WHERE mode = 'classic'"))
    current = bind.scalar(sa.text(
        "SELECT count(DISTINCT chat_id) FROM games WHERE mode = 'classic' AND is_current"
    ))
    if count != current:
        raise RuntimeError(
            'Refusing downgrade: classic game history cannot fit in addressed quiz_sessions'
        )
    bind.execute(sa.text("""
        INSERT INTO quiz_sessions
            (id, chat_id, kind, status, state, started_at, ends_at, created_at, updated_at)
        SELECT
            'classic:' || chat_id::text, chat_id, 'classic', status, state,
            started_at, ended_at, created_at, updated_at
        FROM games WHERE mode = 'classic' AND is_current
        ON CONFLICT (id) DO UPDATE SET
            status = EXCLUDED.status,
            state = EXCLUDED.state,
            started_at = EXCLUDED.started_at,
            ends_at = EXCLUDED.ends_at,
            updated_at = EXCLUDED.updated_at
    """))
    bind.execute(sa.text("DELETE FROM games WHERE mode = 'classic'"))
    op.drop_index('uq_poll_answers_game_round_user', table_name='poll_answers')
    op.drop_constraint(
        'fk_poll_answers_game_id_games', 'poll_answers', type_='foreignkey'
    )
    op.drop_column('poll_answers', 'round_id')
    op.drop_column('poll_answers', 'game_id')
    op.drop_index('ix_game_deliveries_game_created', table_name='game_deliveries')
    op.drop_table('game_deliveries')
