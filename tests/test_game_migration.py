"""Destructive migration rehearsal against a disposable PostgreSQL database."""

import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from storage.database import Database, DatabaseSettings
from storage.models import (
    Game, GameDeadline, GameDelivery, GameEvent, GamePlayer, PollAnswer,
    QuizSession, SystemState, User,
)


def test_0008_moves_legacy_mafia_without_losing_private_state():
    source_url = os.getenv('TEST_DATABASE_URL')
    if not source_url or not shutil.which('createdb') or not shutil.which('dropdb'):
        pytest.skip('Disposable PostgreSQL CLI test is available in the dev image')
    parsed = urlsplit(source_url)
    if parsed.hostname not in {'postgres', '127.0.0.1'} or parsed.username != 'mqb_dev':
        raise RuntimeError('Migration rehearsal requires the local mqb_dev PostgreSQL')
    database_name = 'mqb_migration_' + uuid4().hex
    assert re.fullmatch(r'mqb_migration_[a-f0-9]{32}', database_name)
    netloc = parsed.netloc
    migration_url = urlunsplit((parsed.scheme, netloc, '/' + database_name, '', ''))
    pg_env = os.environ.copy()
    pg_env['PGPASSWORD'] = parsed.password or ''
    alembic_env = {**pg_env, 'DATABASE_URL': migration_url, 'STORAGE_BACKEND': 'postgres'}
    pg = ['-h', parsed.hostname, '-p', str(parsed.port or 5432), '-U', parsed.username]
    subprocess.run(['createdb', *pg, database_name], check=True, capture_output=True, env=pg_env)
    payload = {
        'mode': 'mafia_lobby', 'chat_id': -777123, 'host_id': 701,
        'status': 'night', 'revision': 9, 'round': 2,
        'players': [
            {'user_id': 701, 'name': 'Host', 'ready': True},
            {'user_id': 702, 'name': 'Two', 'ready': True},
            {'user_id': 703, 'name': 'Three', 'ready': True},
            {'user_id': 704, 'name': 'Four', 'ready': True},
        ],
        'assignments': {'701': 'mafia', '702': 'citizen', '703': 'citizen', '704': 'citizen'},
        'alive': [701, 702, 703, 704], 'night_actions': {'mafia': {'701': 702}},
        'votes': {}, 'investigations': {}, 'winner': None,
        'history': [{'type': 'started', 'round': 1}],
        'phase_deadline': 1788541200,
    }
    try:
        subprocess.run(
            [sys.executable, '-m', 'alembic', 'upgrade', '20260831_0007'],
            cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True,
            text=True, env=alembic_env,
        )

        async def seed():
            database = Database(DatabaseSettings(url=migration_url))
            try:
                async with database.transaction() as session:
                    session.add(SystemState(key='mafia_lobby:-777123', payload=payload))
            finally:
                await database.dispose()
        asyncio.run(seed())
        subprocess.run(
            [sys.executable, '-m', 'alembic', 'upgrade', 'head'],
            cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True,
            text=True, env=alembic_env,
        )

        async def verify():
            database = Database(DatabaseSettings(url=migration_url))
            try:
                async with database.transaction() as session:
                    game = await session.scalar(select(Game).where(Game.chat_id == -777123))
                    assert game and game.revision == 9
                    assert game.state['state_version'] == 2
                    assert game.state['room_id'] == f'telegram:{game.chat_id}'
                    host = await session.get(User, 701)
                    assert game.state['host_account_id'] == str(host.account_id)
                    assert [player['account_id'] for player in game.state['players']] == [
                        str((await session.get(User, user_id)).account_id)
                        for user_id in (701, 702, 703, 704)
                    ]
                    assert game.state['assignments'][str(host.account_id)] == 'mafia'
                    assert game.state['night_actions']['mafia'][str(host.account_id)] == str(
                        (await session.get(User, 702)).account_id
                    )
                    assert not {'chat_id', 'host_id', 'scope'} & game.state.keys()
                    assert all('user_id' not in player for player in game.state['players'])
                    assert await session.get(SystemState, 'mafia_lobby:-777123') is None
                    assert await session.scalar(select(func.count()).select_from(GamePlayer)) == 4
                    mafia = await session.scalar(select(GamePlayer).where(
                        GamePlayer.game_id == game.id, GamePlayer.user_id == 701))
                    assert mafia.private_state == {'role': 'mafia'}
                    assert await session.scalar(select(func.count()).select_from(GameEvent)) == 1
                    deadline = await session.scalar(select(GameDeadline))
                    assert deadline and int(deadline.due_at.timestamp()) == payload['phase_deadline']
            finally:
                await database.dispose()
        asyncio.run(verify())
    finally:
        subprocess.run(['dropdb', *pg, '--force', database_name], check=True,
                       capture_output=True, env=pg_env)


def test_0010_moves_classic_session_delivery_deadline_and_answer():
    source_url = os.getenv('TEST_DATABASE_URL')
    if not source_url or not shutil.which('createdb') or not shutil.which('dropdb'):
        pytest.skip('Disposable PostgreSQL CLI test is available in the dev image')
    parsed = urlsplit(source_url)
    if parsed.hostname not in {'postgres', '127.0.0.1'} or parsed.username != 'mqb_dev':
        raise RuntimeError('Migration rehearsal requires the local mqb_dev PostgreSQL')
    database_name = 'mqb_migration_' + uuid4().hex
    assert re.fullmatch(r'mqb_migration_[a-f0-9]{32}', database_name)
    migration_url = urlunsplit((parsed.scheme, parsed.netloc, '/' + database_name, '', ''))
    pg_env = os.environ.copy()
    pg_env['PGPASSWORD'] = parsed.password or ''
    alembic_env = {**pg_env, 'DATABASE_URL': migration_url, 'STORAGE_BACKEND': 'postgres'}
    pg = ['-h', parsed.hostname, '-p', str(parsed.port or 5432), '-U', parsed.username]
    subprocess.run(['createdb', *pg, database_name], check=True, capture_output=True, env=pg_env)
    chat_id, user_id, poll_id = -778123, 778123, 'legacy-poll-0010'
    deadline = 1788542200
    state = {
        'storage_version': 1, 'session_id': 'legacy-classic-session',
        'revision': 7, 'chat_id': chat_id, 'storage_phase': 'active',
        'current_question_index': 1, 'num_questions_to_ask': 1,
        'active_poll_ids_in_session': [poll_id], 'latest_poll_id_sent': poll_id,
        'polls': {poll_id: {
            'message_id': 42, 'display_question': 'Вопрос 1/1\nДва плюс два?',
            'question_text': 'Два плюс два?', 'options': ['3', '4'],
            'correct_option_index': 1, 'end_timestamp': deadline,
        }},
    }
    try:
        subprocess.run(
            [sys.executable, '-m', 'alembic', 'upgrade', '20260904_0009'],
            cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True,
            text=True, env=alembic_env,
        )

        async def seed():
            database = Database(DatabaseSettings(url=migration_url))
            try:
                async with database.transaction() as session:
                    await session.execute(text(
                        "INSERT INTO chats (id, type) VALUES (:chat_id, 'supergroup')"
                    ), {'chat_id': chat_id})
                    await session.execute(text(
                        "INSERT INTO users (id, display_name) VALUES (:user_id, 'Игрок')"
                    ), {'user_id': user_id})
                    await session.execute(text(
                        "INSERT INTO quiz_sessions (id, chat_id, kind, status, state) "
                        "VALUES (:id, :chat_id, 'classic', 'active', CAST(:state AS json))"
                    ), {'id': f'classic:{chat_id}', 'chat_id': chat_id,
                        'state': json.dumps(state, ensure_ascii=False)})
                    await session.execute(text(
                        "INSERT INTO poll_answers "
                        "(poll_id, user_id, chat_id, selected_option, is_correct, points_delta) "
                        "VALUES (:poll_id, :user_id, :chat_id, 1, true, 2.5)"
                    ), {'poll_id': poll_id, 'user_id': user_id, 'chat_id': chat_id})
            finally:
                await database.dispose()
        asyncio.run(seed())
        subprocess.run(
            [sys.executable, '-m', 'alembic', 'upgrade', 'head'],
            cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True,
            text=True, env=alembic_env,
        )

        async def verify():
            database = Database(DatabaseSettings(url=migration_url))
            try:
                async with database.transaction() as session:
                    game = await session.scalar(select(Game).where(
                        Game.chat_id == chat_id, Game.mode == 'classic'
                    ))
                    assert game and game.state == state and game.revision == 7
                    assert await session.get(QuizSession, f'classic:{chat_id}') is None
                    delivery = await session.scalar(select(GameDelivery).where(
                        GameDelivery.game_id == game.id
                    ))
                    assert delivery.external_id == poll_id
                    assert delivery.message_id == 42 and delivery.status == 'sent'
                    answer = await session.get(PollAnswer, (poll_id, user_id))
                    assert answer.game_id == game.id and answer.round_id == poll_id
                    deadline_row = await session.scalar(select(GameDeadline).where(
                        GameDeadline.game_id == game.id
                    ))
                    assert int(deadline_row.due_at.timestamp()) == deadline
            finally:
                await database.dispose()
        asyncio.run(verify())
    finally:
        subprocess.run(['dropdb', *pg, '--force', database_name], check=True,
                       capture_output=True, env=pg_env)
