"""Queue one approved gift on an existing dev or rehearsal farm."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
from uuid import UUID

from sqlalchemy import cast, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qw_farm import farm_rewards
from qw_farm.domain import FarmError, need
from qw_farm.integration import register_models
from qw_farm.persistence import Unit
from scripts.quarantine_notification_outbox import validate_dev_database_url
from storage.admin_actions import operation_fence
from storage.database import Database, DatabaseSettings, normalize_database_url


def target_url(raw, environment):
    if environment == 'dev':
        return validate_dev_database_url(raw)
    url = normalize_database_url(raw or '')
    target = make_url(url)
    if (ROOT != Path('/home/lizard/mqb-rehearsal') or target.database != 'morning_quiz_rehearsal'
            or target.host not in ('127.0.0.1', 'localhost') or target.port not in (None, 5432)
            or target.query):
        raise ValueError('Ожидается локальное подключение к БД песочницы из её каталога.')
    return url


async def queue_in(session, farm_id, reward_id, fields, now):
    await operation_fence(session)
    unit = Unit(session, register_models())
    farm = await unit.get(str(farm_id))
    need(farm is not None, 'not_found', 'Активная ферма не найдена.', 404)
    # Serialize operator retries even when a different recipient is supplied.
    await unit.lock('reward:' + reward_id)
    table = unit.t['states']
    existing = set((await session.scalars(select(table.c.id).where(
        cast(table.c.payload[farm_rewards.KEY], JSONB).has_key(reward_id)
    ))).all())
    need(not existing or farm_id in existing, 'farm_reward_already_queued',
         'Этот номер награды уже закреплён за другой фермой.')
    account_id = await unit.owner_account(str(farm_id))
    return await farm_rewards.enqueue_for(unit, account_id, reward_id, now, **fields)


async def run(url, farm_id, reward_id, fields, *, apply=False):
    db = Database(DatabaseSettings(url=url))
    try:
        async with db.transaction() as session:
            database = await session.scalar(text('SELECT current_database()'))
            if database != make_url(url).database:
                raise ValueError('Подключение ведёт к другой БД.')
            queued = await queue_in(session, farm_id, reward_id, fields, time.time())
            if not apply:
                await session.rollback()
            return queued
    finally:
        await db.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment', required=True, choices=('dev', 'rehearsal'))
    parser.add_argument('--database-url-env', required=True, help='Имя переменной с URL БД.')
    parser.add_argument('--farm-id', required=True, type=UUID)
    parser.add_argument('--reward-id', required=True, help='Постоянный номер операции.')
    parser.add_argument('--spec', type=Path, required=True, help='Локальный JSON подарка.')
    parser.add_argument('--apply', action='store_true', help='Без флага транзакция откатывается.')
    args = parser.parse_args(argv)
    try:
        url = target_url(os.environ.get(args.database_url_env), args.environment)
        if args.spec.stat().st_size > 4096:
            raise ValueError('Файл подарка слишком большой.')
        fields = json.loads(args.spec.read_text(encoding='utf-8-sig'))
        if (not isinstance(fields, dict) or 'title' not in fields
                or fields.keys() - {'title', 'message', 'coins', 'items', 'decor'}):
            raise ValueError('Проверь поля JSON подарка.')
        if not farm_rewards.ID_PATTERN.fullmatch(args.reward_id):
            raise ValueError('Некорректный номер награды.')
        queued = asyncio.run(run(url, args.farm_id, args.reward_id, fields, apply=args.apply))
    except FarmError as error:
        print(error.message, file=sys.stderr)
        return 1
    except (OSError, ValueError):
        # A malformed connection URL may contain a password.
        print('Проверь адрес БД, каталог и JSON награды.', file=sys.stderr)
        return 1
    except Exception:
        print('БД не подтвердила операцию. Проверь контур и попробуй с тем же номером.', file=sys.stderr)
        return 1
    print(json.dumps({'applied': args.apply, 'new': queued, 'reward_id': args.reward_id}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
