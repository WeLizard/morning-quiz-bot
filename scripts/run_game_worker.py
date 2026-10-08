"""Run game deadlines independently from the Telegram polling process."""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from application.game_deadlines import GameDeadlineProcessor
from storage.database import Database, DatabaseSettings


def _interval() -> float:
    raw = os.getenv('GAME_WORKER_INTERVAL_SECONDS', '2')
    try:
        value = float(raw)
    except ValueError as error:
        raise SystemExit('GAME_WORKER_INTERVAL_SECONDS must be between 0.25 and 30') from error
    if not 0.25 <= value <= 30:
        raise SystemExit('GAME_WORKER_INTERVAL_SECONDS must be between 0.25 and 30')
    return value


async def main() -> None:
    logging.basicConfig(
        level=os.getenv('LOG_LEVEL', 'INFO').upper(),
        format='%(asctime)s %(levelname)s %(name)s %(message)s',
    )
    logger = logging.getLogger('mqb.game_worker')
    interval = _interval()
    database = Database(DatabaseSettings.from_env())
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stopping.set)
        except NotImplementedError:
            pass

    try:
        await database.check_connection()
        logger.info('Game deadline worker started; interval=%.2fs', interval)
        processor = GameDeadlineProcessor(database)
        while not stopping.is_set():
            try:
                await processor.run_once()
            except Exception:
                logger.exception('Deadline pass failed; will retry after the interval')
            try:
                await asyncio.wait_for(stopping.wait(), timeout=interval)
            except TimeoutError:
                pass
    finally:
        await database.dispose()
        logger.info('Game deadline worker stopped')


if __name__ == '__main__':
    asyncio.run(main())
