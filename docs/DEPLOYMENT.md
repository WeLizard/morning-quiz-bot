# Развёртывание Morning Quiz Bot

Документ описывает реальную схему проекта: локальный dev-контур и production на
сервере. Боевая выкладка перехода на PostgreSQL — в
[tasks/MQB-007](tasks/MQB-007-production-cutover-runbook.md), здесь — общая
эксплуатация.

## Где что живёт

| | Dev-контур | Production |
|---|---|---|
| Каталог | `C:\Users\Lizard\Projects\morning-quiz-bot` | `/home/lizard/morning-quiz-bot` = `\\192.168.0.33\FullDisk\home\lizard\morning-quiz-bot` |
| Пользователь | Windows-сессия | `lizard` |
| Python | 3.13 | 3.13 (`venv/` в каталоге проекта) |
| Хранилище | PostgreSQL (`morning_quiz_dev`, порт 55433) + JSON как вход миграции | JSON (до cutover), PostgreSQL (после) |
| Запуск | вручную | systemd: `quiz-bot`, `quiz-bot-web`, `maintenance-fallback` |

Сервер: `ssh serverold` (192.168.0.33). Внешний адрес — 185.237.236.5 за NAT.

## Требования

- Python 3.13 (в проекте используются возможности f-string из 3.12+).
- PostgreSQL 17 — проще всего контейнером (`docker compose --profile postgres`).
- Docker 20.10+ (на сервере есть), nginx для веб-панели и Mini App.
- Для БД-тестов дополнительно `pg_dump`/`createdb`/`psql` на хосте (иначе часть
  тестов пропускается).

## Локальный запуск

```powershell
cd C:\Users\Lizard\Projects\morning-quiz-bot
python -m venv .venv-local
.\.venv-local\Scripts\pip install -r requirements.txt

# PostgreSQL
docker compose --profile postgres up -d postgres

# .env рядом с проектом: BOT_TOKEN, STORAGE_BACKEND, DATABASE_URL, ...
$env:STORAGE_BACKEND = 'postgres'
$env:DATABASE_URL = 'postgresql+asyncpg://morning_quiz:ПАРОЛЬ@127.0.0.1:5432/morning_quiz'
python -m alembic upgrade head
python -m alembic current          # ожидаем единственный head

# данные: либо импорт боевого снимка, либо дев-сид
python -m storage.json_importer --dry-run
python -m storage.json_importer --report migration-reports\postgres-import.json

python bot.py                      # бот (в PG-режиме JSON не пишется)
python web/run_web.py              # админка на 0.0.0.0:8000
```

Тесты:

```powershell
python -m pytest -q                                    # без БД: часть тестов пропускается
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://mqb_dev:ПАРОЛЬ@127.0.0.1:55433/morning_quiz_test'
DATABASE_URL=$env:TEST_DATABASE_URL python -m alembic upgrade head   # БД тестов тоже нужно мигрировать
python -m pytest -q                                    # полный гейт
```

## Production

### Переменные окружения

`.env` в корне проекта, в git не попадает. Минимум для бота:

```
BOT_TOKEN=...
MODE=production
LOG_LEVEL=INFO
STORAGE_BACKEND=postgres
DATABASE_URL=postgresql+asyncpg://morning_quiz:ПАРОЛЬ@127.0.0.1:5432/morning_quiz
POSTGRES_DB=morning_quiz
POSTGRES_USER=morning_quiz
POSTGRES_PASSWORD=ПАРОЛЬ
POSTGRES_PORT=5432
TELEGRAM_PROXY_URL=socks5://127.0.0.1:9050     # на сервере Telegram доступен только через прокси
```

Для панели администратора дополнительно: `ADMIN_ACCESS_TOKEN` (32–512 символов,
иначе закрытые маршруты отдают 503), `ADMIN_ALLOWED_HOSTS`, `PHOTO_IMAGES_DIR`.
Для Mini App: `MINI_APP_DATABASE_URL`, `MINI_APP_BOT_TOKEN` (токен того же бота),
`MINI_APP_ORIGIN` (точный HTTPS-origin), `MINI_APP_URL`, `MINI_APP_BOT_USERNAME`.

### Хранилище и миграции

```bash
cd /home/lizard/morning-quiz-bot
docker compose --profile postgres up -d postgres
until docker inspect --format '{{.State.Health.Status}}' morning-quiz-postgres | grep -q healthy; do sleep 3; done
./venv/bin/python -m alembic upgrade head
./venv/bin/python -m alembic current
```

Порт публикуется только на `127.0.0.1` — база не торчит в сеть.

### Сервисы

```bash
sudo systemctl status quiz-bot quiz-bot-web
sudo systemctl restart quiz-bot quiz-bot-web
sudo journalctl -u quiz-bot -n 100 --no-pager
tail -f logs/bot.log                # файловый лог с суточной ротацией
systemctl show quiz-bot -p NRestarts
```

Юниты запускают `venv/bin/python bot.py` и `venv/bin/python web/run_web.py` из
`/home/lizard/morning-quiz-bot`; `maintenance-fallback.service` показывает
заглушку, пока бот перезапускается (переключение — через `bot_control.sh`).
Веб-панель слушает `0.0.0.0:8000`, наружу её отдаёт nginx на порту `8888`
(`nginx-quiz-web-8888.conf`).

### Обновление кода

Рабочая копия на сервере содержит локальные артефакты, которых нет в git:
`.env`, `data/`, `logs/`, `backups/`, `*.service`, `nginx*.conf`, `bot_control.sh`,
`menu.sh`, `run_bot.bat` и **симлинки** `bot_control.sh`, `menu.sh`,
`maintenance_fallback.py` → `sys/`. Поэтому обновление — чистый клон с переносом
локального, а не `git pull` на месте:

```bash
sudo systemctl stop quiz-bot quiz-bot-web
sudo -u lizard git clone https://github.com/WeLizard/morning-quiz-bot.git /home/lizard/mqb-new
cd /home/lizard/mqb-new
cp /home/lizard/morning-quiz-bot/.env .
cp -a /home/lizard/morning-quiz-bot/{data,logs,backups} .
for f in bot_control.sh menu.sh maintenance_fallback.py; do ln -sf "sys/$f" "$f"; done
cp -a /home/lizard/morning-quiz-bot/{nginx.conf,nginx-quiz-web-8888.conf,*.service} .
python3.13 -m venv venv && ./venv/bin/pip install -r requirements.txt
mv /home/lizard/morning-quiz-bot /home/lizard/morning-quiz-bot.before-update
mv /home/lizard/mqb-new /home/lizard/morning-quiz-bot
sudo systemctl start quiz-bot quiz-bot-web
```

Никогда не выполнять на сервере `git clean -xfd` или `git checkout .`: они
уничтожат `.env`, данные и системные файлы.

### Docker-путь

`docker-compose.yml` поднимает `postgres` (профиль `postgres`) и `quiz-bot`
(образ из `Dockerfile`, Python 3.11-slim, healthcheck по процессу бота).
Важно: **код копируется в образ при сборке**, bind-mount'ятся только `data/` и
`config/`, поэтому после правок кода нужен `docker compose build quiz-bot`;
простого обновления файлов в каталоге недостаточно.

## Mini App

Mini App — отдельный ASGI-сервис (`web/mini_app.py`), его нельзя монтировать в
админку. Публичный запуск:

```bash
MINI_APP_ORIGIN=https://<домен> MINI_APP_URL=https://<домен>/app \
MINI_APP_BOT_TOKEN=<токен бота> MINI_APP_BOT_USERNAME=<bot_username> \
MINI_APP_DATABASE_URL=postgresql+asyncpg://... \
./venv/bin/python -m uvicorn web.mini_app:create_app --factory --host 127.0.0.1 --port 8081
```

Требования Telegram:

- адрес только **HTTPS на 443** с валидным сертификатом; самоподписанный клиент
  не примет, нестандартный порт не поддерживается;
- `MINI_APP_ORIGIN` должен точно совпадать с адресом, по которому открывают
  страницу (схема + хост + порт), иначе сервис отвечает 400;
- вход только по подписанному `initData`; пользователь обязан существовать в БД;
- кнопка меню ставится либо в BotFather, либо через Bot API:
  `setChatMenuButton` с `{"type":"web_app","web_app":{"url":"https://<домен>/app"}}`;
- для тестового контура удобно `MINI_APP_OFFLINE=1`: отключается проверка
  членства в чате (групповые чаты при этом недоступны), криптографическая
  проверка `initData` остаётся.

Один IP может обслуживать несколько приложений: на 443 ставится nginx-прокси и
разводит запросы по именам (SNI). Бесплатные имена вида
`<любой-префикс>.185-237-236-5.sslip.io` резолвятся на этот IP без регистрации;
DuckDNS даёт имя поприятнее. Сертификаты — Let's Encrypt (`certbot --nginx`),
для проверки нужен проброшенный 80 (HTTP-01) либо TLS-ALPN на 443 (`acme.sh`).

Статическая мини-игра «Алхимия» отдаётся тем же сервисом по `/app/alchemy`
(ветка `feature/alchemy-worlds`, в `main` пока не влита). Одиночным играм нужна
отдельная CSP с `'unsafe-inline'` — см.
[minigames/alchemia-1.0/INTEGRATION.md](../minigames/alchemia-1.0/INTEGRATION.md).

## Диагностика

- **Бот не стартует, `RuntimeError: Morning Quiz runtime requires STORAGE_BACKEND=postgres`** —
  основной entrypoint работает только на PostgreSQL; JSON допустим лишь как вход
  миграции.
- **`PostgreSQL schema revision mismatch`** — не накатаны миграции: `alembic upgrade head`.
- **Веб-панель не стартует** — проверь `STORAGE_BACKEND=postgres`, `DATABASE_URL`
  и миграции. JSON-режим теперь fail-closed и не обслуживает старые файловые API.
- **Порт занят** — `web/run_web.py` жёстко слушает `0.0.0.0:8000`; при конфликте
  запускать `uvicorn web.main:app --port <другой>`.
- **Второй экземпляр бота на хосте** — до фикса он убивал все процессы с `bot.py`
  в командной строке. Сейчас дубли определяются по совпадению пути; для второго
  контура использовать `MQB_SKIP_DUPLICATE_KILL=1` и контейнер с отдельным PID
  namespace.
- **`UnicodeDecodeError` или лишние байты при сборке утилит на Windows** — запускать
  Python с `PYTHONUTF8=1`; запись переводов строк в Windows даёт CRLF.
- **Прокси** — Telegram доступен только через `socks5://127.0.0.1:9050`; при
  запуске сервисов без `TELEGRAM_PROXY_URL` сетевые вызовы к Telegram будут
  падать таймаутом.
