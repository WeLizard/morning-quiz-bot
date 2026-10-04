# Разбор расхождений production-копии с dev

Дата проверки: 2026-10-04, 23:48 (+03:00)
Проверялось: `C:\Users\Lizard\Projects\morning-quiz-bot` (dev) и `\\192.168.0.33\FullDisk\home\lizard\morning-quiz-bot` (prod, на сервере это `/home/lizard/morning-quiz-bot`).

## 1. Короткий вывод

Production-копия **не является нетронутой**. Это снимок *части* dev-работы, сделанный 2026-08-30 в 02:38–03:20: тогда на сервер попала обвязка PostgreSQL (bot.py/data_manager/score_manager/category_manager, `alembic/`, `storage/`, `scripts/`, `tests/`, `docs/`, `requirements.txt`, `env.example`).

При этом:

- **Mafia и Mini App в prod действительно отсутствуют** (`application/`, `domain/`, `web/mini_app.py`, `handlers/mafia_handlers.py`) — эта часть твоих слов подтверждается.
- **PostgreSQL-обвязка в prod есть, но спящая**: в `prod/.env` нет `STORAGE_BACKEND` и `DATABASE_URL`, поэтому `AppConfig` берёт дефолт `json` (`app_config.py:124`). Бот на сервере работает в JSON-режиме.
- **Уникального production-кода нет.** Все строки, которые есть в prod и отсутствуют в dev, — это более ранние версии той же логики, которую в dev переписали или перенесли (см. §4). Терять при синхронизации нечего.

## 2. Git-состояние (после правки remote)

| | dev | prod |
|---|---|---|
| branch | `main` | `main` |
| HEAD | `e4ed2b9` | `e4ed2b9` |
| origin/main (реально на GitHub) | `b838845` | `b838845` |
| расхождение | ahead 2, behind 0 | ahead 2, behind 0 |
| remote | `https://github.com/WeLizard/morning-quiz-bot.git` | то же |
| user.name / email | `WeLizard` / `WeLizard@users.noreply.github.com` | то же |
| изменённых tracked-файлов | 35 (+2459/−1410) | 14 (+485/−59) |
| новых (untracked) путей | ~130 | 16 |
| индекс (staged) | пусто | пусто |
| commits не пушились с | 26.02.2026 | 26.02.2026 |

Секретов в git нет: `.env` не отслеживается, среди tracked-файлов нет ничего похожего на токены/пароли.

## 3. Расхождения по файлам

### Tracked (изменённые) — prod это более старая версия

| файл | prodAdd | devAdd | только у prod | идентичны |
|---|---|---|---|---|
| `.gitignore` | 2 | 10 | 0 | нет |
| `app_config.py` | 19 | 19 | 0 | **да** |
| `bot.py` | 84 | 140 | 3 | нет |
| `config/quiz_config.json` | 8 | 8 | 0 | **да** |
| `data/questions/Головоломки и логические задачи.json` | 1 | 1 | 0 | **да** |
| `data_manager.py` | 147 | 228 | 68 | нет |
| `docker-compose.yml` | 29 | 29 | 0 | **да** |
| `docs/README.md` | 12 | 14 | 0 | нет |
| `env.example` | 21 | 50 | 0 | нет |
| `modules/bot_commands_setup.py` | 49 | 59 | 0 | нет |
| `modules/category_manager.py` | 26 | 53 | 5 | нет |
| `modules/score_manager.py` | 73 | 186 | 44 | нет |
| `requirements.txt` | 5 | 7 | 2 | нет |
| `setup.py` | 9 | 10 | 1 | нет |

mtime у совпадающих файлов одинаковый (напр. `app_config.py`, `docker-compose.yml` — 2026-08-30 02:56), у prod-версий расходящихся файлов — 2026-08-30 02:38…03:19, у dev — 2026-08-30…2026-09-04. То есть prod остановился 30.08, dev поехал дальше.

### Untracked (новые пути)

| путь | prod | dev | комментарий |
|---|---|---|---|
| `alembic.ini`, `pytest.ini`, `scripts/import_json_to_postgres.py`, `scripts/New-JsonMigrationSnapshot.ps1` | есть | есть | идентичны |
| `alembic/versions/` | 1 миграция (`0001_operational_storage`) | 11 миграций (0001…0011, до `20260904_0011_photo_game_runtime`) | prod не сможет накатить актуальную схему |
| `storage/` | 6 модулей (`database`, `json_importer`, `models`, `repositories`, `runtime`, `__init__`) | 31 модуль (+`admin_*`, `members`, `classic_sessions`, `mini_app`, `question_bank`, `games`, `photos`, …) | 4 общих модуля расходятся по содержимому |
| `tests/test_postgres_storage.py`, `tests/test_json_importer.py` | есть | есть | расходятся |
| `docs/POSTGRESQL_MIGRATION.md`, `docs/INDEX.md`, `docs/CODE_VERIFIED_FEATURE_MAP.md` | есть | есть | расходятся |
| `docs/DOCUMENTATION_RULES.md` | есть | есть | идентичны |
| `docs/tasks/` | 3 файла | 8 файлов | у dev MQB-002…MQB-006 |
| `docs/decisions/` | 3 ADR | 17 ADR | у dev ADR-002…ADR-015 |
| `web/prototypes/` | 5 файлов | 11 файлов | dev добрал `host-photo*.webp` |
| `data/global/` | есть (`categories.json`, `users.json` расходятся) | есть | это runtime-данные, синхронизировать нельзя |

## 4. Куда в dev ушли «prod-only» строки

Функциональность не потеряна, изменилась реализация:

| prod | dev |
|---|---|
| `data_manager._postgres_write_tasks` / `_schedule_postgres_write(...)` (старая очередь записи) | те же имена + `flush_postgres_writes()`, `_patch_postgres_settings()` (`data_manager.py:64,89,1232`) |
| `score_manager._score_delta()`, `apply_classic_answer()`, Decimal-бонусы за серии | `domain/scoring.py` (`streak_bonuses`, `consecutive_correct`, `apply_classic_score`), вызовы из `score_manager.py:94` и `domain/classic.py` |
| `category_manager` → `postgres_storage.save_category_statistics(snapshot)` | `storage/runtime.py:237` метод сохранён, вызовы переписаны (`storage/category_statistics.py`), в dev есть DB-aware загрузка (`session.get(SystemState, "category_usage_stats")`) |
| `postgres_storage.apply_classic_answer(...)` | `storage/members.py:39 apply_answer()`, `storage/classic_sessions.py`, `storage/repositories.py:174 record_answer_and_add_score()` |
| `requirements.txt`: `python-telegram-bot[job-queue,socks]>=22.4`, комментарий «Python 3.9+» | `==22.8`, добавлены `aiofiles==23.2.1`, `openai==2.21.0` |
| `setup.py`: `python_requires=">=3.9"` | `>=3.10` |
| `.gitignore`: только `migration-reports/` | ещё `.env.telegram-test`, `.venv/`, `.pytest_cache/`, `.local/`, `.venv-local/`, `*.postgres-ui.pickle`, `data/questions/.history/`, `data/questions/.admin.lock`; и снят игнор `.dockerignore` |

Всё, что prod «добавлял» в `bot.py` (комментарий про статический JSON-банк вопросов и `data_manager.load_questions()`), в dev заменено работой с банком вопросов в PostgreSQL (`alembic/versions/20260904_0009_question_bank.py`).

## 5. Состояние production прямо сейчас

- Бот **работает**: `logs/bot.log` пишется (последняя запись 2026-10-04 23:47), `bot.pid` = 1596, лог пишет путь `/home/lizard/morning-quiz-bot/data/active_quizzes.json` (это и есть эта шара). Ротация логов: 27.09…04.10.
- Режим — **JSON**: в `prod/.env` есть `BOT_TOKEN`, `OPENROUTER_API_KEY`, `MODE=production`, `LOG_LEVEL=DEBUG`, `TELEGRAM_PROXY_URL=socks5://127.0.0.1:9050`; **нет** `STORAGE_BACKEND`/`DATABASE_URL`/`SENTRY_DSN`. В логах нет ни одного упоминания postgres/asyncpg/sqlalchemy.
- Ошибки в логах — только сетевые (`Bad Gateway`, `Server disconnected without sending a response`), 6–38 строк в день, к расхождениям отношения не имеют.
- `dev/.env` (для сравнения): `MODE=testing`, **другой** `BOT_TOKEN` (не совпадает с prod — параллельный запуск не конфликтует), `STORAGE_BACKEND=json`, `DATABASE_URL` задан, `SENTRY_DSN` пуст.
- venv на prod — `python3.13`.
- Deployment-артефакты (gitignored, но есть в обеих копиях): `nginx.conf`, `nginx-quiz-web-8888.conf`, `quiz-bot.service`, `quiz-bot-web.service`, `maintenance-fallback.service`, `bot_control.sh`, `menu.sh`, `run_bot.bat`. В dev дополнительно `.dockerignore`, `Dockerfile.dev`, `compose.dev.yml`.

## 6. Риски и правила

1. **Не включать `STORAGE_BACKEND=postgres` на prod** до синхронизации кода: там 1 миграция из 11, `storage/` из 6 модулей из 31, `bot.py`/`data_manager.py` старее. Включение почти наверняка сломает запуск.
2. **Не делать на prod `git checkout .`, `git reset --hard`, `git clean -xfd`.** Gitignored и существуют только локально: `.env` (production-значения и socks-прокси), `bot.pid`, `nginx*.conf`, `*.service`, `bot_control.sh`, `menu.sh`, `run_bot.bat`, `backups/`, `logs/`, `data/`. Большинство продублировано в dev, но `.env` восстановить нечем.
3. **Данные не синхронизировать**: `data/global/categories.json`, `data/global/users.json`, `data/chats/`, `data/questions/.admin.lock` у dev и prod разные (разные боты и чаты).
4. **Не делать prod «снимком» dev через копирование каталога.** Правильный путь — позже осознанный деплой: код из git (после коммитов в dev), без `data/`, `.env` и системных файлов.
5. Пока в dev ~130 новых путей и 35 изменённых файлов не закоммичены — это единственная копия полугодовой работы. Коммиты — следующий шаг (см. §7).

## 7. Следующие шаги

1. Закоммитить накопленное в dev логическими группами (PostgreSQL/хранилище, Mini App, Mafia/game substrate, админка и модерация, dev-tooling и документация), затем push `main` → после проверки.
2. Отдельно решить судьбу prod-расхождений: либо оставить как есть (postgres там выключен и не мешает), либо после деплоя нового кода привести рабочую копию к версии dev.
3. Опционально: перенести deployment-артефакты (`*.service`, `nginx*.conf`, `bot_control.sh`, `menu.sh`) в репозиторий как templates в `deploy/`, чтобы они не жили только на сервере.

## 8. Как воспроизвести проверку

```powershell
$dev='C:\Users\Lizard\Projects\morning-quiz-bot'
$prod='\\192.168.0.33\FullDisk\home\lizard\morning-quiz-bot'

git -C $prod status -sb
git -c core.quotePath=false -C $prod diff --name-only
git -c core.quotePath=false -C $prod diff --numstat          # против того же в $dev
git --no-pager diff --no-index -- "$prod\requirements.txt" "$dev\requirements.txt"
Get-FileHash (Join-Path $dev 'bot.py'), (Join-Path $prod 'bot.py') -Algorithm MD5
Get-Content (Join-Path $prod 'logs\bot.log') -Tail 20
```
