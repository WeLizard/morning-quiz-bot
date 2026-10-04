"""Гейт перед выкладкой: каталог фото должен совпадать с файлами на диске.

Запуск на сервере из каталога проекта:

    ./venv/bin/python scripts/verify_media_catalog.py

Код возврата 1, если есть записи без подтверждённого файла (такие фото нельзя
показать) или файлы, чья подпись не сошлась. Файлы без записи в каталоге — это
ожидаемый след неуверенного коммита, они только перечисляются.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.database import Database, DatabaseSettings  # noqa: E402
from storage.photo_media import catalog_status  # noqa: E402


async def main() -> int:
    database = Database(DatabaseSettings.from_env())
    try:
        await database.check_connection()
        status = await catalog_status(database)
    finally:
        await database.dispose()
    print(json.dumps(status, ensure_ascii=False, indent=2))
    broken = bool(status['missing'] or status['unverified'])
    print('ИТОГ:', 'ЕСТЬ ПРОБЛЕМЫ' if broken else 'каталог согласован', file=sys.stderr)
    return 1 if broken else 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
