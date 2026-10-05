# Локальный запуск и проверка Mini App

Практическая памятка: что где крутится в песочнице, как это поднять заново и как
убедиться, что всё живо. Все команды выполняются из каталога песочницы
(`/home/lizard/mqb-rehearsal`), production при этом не затрагивается.

## Что где работает

| Порт | Что | Код |
|---|---|---|
| 4185 | демо Mini App (`web.dev_mini_app:create_dev_app`), синтетический игрок, отдельная dev-БД | `main` (включая Алхимию) |
| 8081 | публичный Mini App под туннельный origin | `main` |
| 8010 | админка (`web.main:app`) | `main` |

С рабочей машины всё доступно через ssh-туннель:

```bash
ssh -N -L 4185:127.0.0.1:4185 -L 8010:127.0.0.1:8010 serverold
```

Дальше: <http://127.0.0.1:4185/app> (демо, там же плитка «Атлас маленьких чудес»
и <http://127.0.0.1:4185/app/alchemy>), <http://127.0.0.1:8010/login> (админка).

## Запуск инстансов

Демо-инстанс (единственный, который строго требует loopback-БД и синтетический ключ):

```bash
cd /home/lizard/mqb-rehearsal
setsid nohup env \
  MINI_APP_DATABASE_URL="postgresql+asyncpg://mqb_dev:<пароль>@127.0.0.1:55433/morning_quiz_dev" \
  MINI_APP_ORIGIN="http://127.0.0.1:4185" MINI_APP_OFFLINE=1 \
  MINI_APP_BOT_TOKEN="123456:LOCAL_TEST_ONLY_012345678901234567890" \
  PHOTO_IMAGES_DIR=/home/lizard/mqb-rehearsal/data/images MODE=testing LOG_LEVEL=INFO \
  ./venv/bin/python -m uvicorn web.dev_mini_app:create_dev_app --factory \
  --host 127.0.0.1 --port 4185 > /tmp/mini-4185.log 2>&1 < /dev/null &
```

Публичный инстанс и админка — готовыми хелперами:

```bash
bash /tmp/mqb-mini-public.sh https://<публичный-origin>   # порт 8081
bash /tmp/mqb-admin.sh                                    # порт 8010
```

Важно: хост запроса должен совпадать с `MINI_APP_ORIGIN` (сравнивается схема и
хост). Поэтому локальный запрос к инстансу, настроенному на публичный https-origin,
получает 400 — это работа защиты, а не поломка.

## Проверка одной командой

```bash
# 16 проверок: healthz, страница и клиент, вход, me/config/progress/achievements/
# history/categories/leaderboard/chats, детали личного чата, продление сессии,
# выход и отказ старого токена.
MINI_APP_BOT_TOKEN=<токен тестового бота> ./venv/bin/python scripts/smoke_mini_app.py \
    --base-url http://127.0.0.1:8081 --user-id <telegram-id>

# то же для демо-инстанса (вход синтетическим игроком, без initData)
./venv/bin/python scripts/smoke_mini_app.py --dev --base-url http://127.0.0.1:4185

# сверка каталога фото с файлами: код 1, если фото нельзя показать
./venv/bin/python scripts/verify_media_catalog.py
```

## Тесты

```bash
# Python: вся сюита, тесты с PostgreSQL выполняются, а не пропускаются
export TEST_DATABASE_URL="postgresql+asyncpg://mqb_dev:<пароль>@127.0.0.1:55433/morning_quiz_test"
./venv/bin/python -m pytest -q

# Клиент: 15 тестов навигации, ссылок, сессии и экранов.
# На сервере node не установлен, поэтому гонять локально из каталога проекта:
node --test tests/js/mini_navigation.test.cjs
```

Тестовая БД должна быть на актуальной ревизии схемы: `require_current_schema`
сверяет `alembic_version` с единственным head, иначе приложение не стартует.

## Документы по Mini App

- `docs/MINI_APP_DEEP_LINKS.md` — формат `?startapp=`, белый список параметров.
- `docs/MINI_APP_RATE_LIMITS.md` — бюджет запросов и интервалы опроса.
- `docs/MINI_APP_GAMEPLAY.md` — навигация и игровые состояния клиента.
- `docs/tasks/MQB-007-production-cutover-runbook.md` — выкладка и откат.
- `docs/tasks/MQB-008-alchemy-merge-readiness.md` — готовность ветки Алхимии.
