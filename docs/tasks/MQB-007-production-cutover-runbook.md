# MQB-007 — Runbook выкладки PostgreSQL на production

- **Статус:** `ready_for_review`
- **Создана:** 2026-10-05
- **Связанные:** [MQB-006](MQB-006-platform-postgresql-cutover.md), ADR-001, [POSTGRESQL_MIGRATION.md](../POSTGRESQL_MIGRATION.md), [POSTGRESQL_ADMIN.md](../POSTGRESQL_ADMIN.md)
- **Сервер:** `ssh serverold` (192.168.0.33), каталог `/home/lizard/morning-quiz-bot`, юзер `lizard`, Python 3.13
- **Задача документа:** дать пошаговую, проверяемую процедуру перехода боевого бота с JSON на PostgreSQL и такой же проверяемый путь назад.

## 0. Что уже подтверждено репетицией

Репетиция проведена 2026-10-05 в изолированной песочнице `/home/lizard/mqb-rehearsal` на копии боевых данных, боевой бот при этом не останавливался.

| Проверка | Результат |
|---|---|
| Миграции на пустой БД | 11 ревизий, head `20260904_0011`, `alembic check` — расхождений нет |
| Импорт боевых JSON (31 МБ, 126 файлов) | `status: completed`, `errors: 0`, 10/10 fingerprints matched |
| Перенесённые данные | 11 чатов, 16 пользователей, 24 участника, 184 ачивки, 18 расписаний, 198 фото, 63 категории, 6698 вопросов, 7 system_states |
| Тестовый гейт на чистой мигрированной БД | 441 passed, 3 skipped (нужны `pg_dump`/`createdb` на хосте) |
| Бот в PG-режиме (контейнер) | стартует, читает вопросы/state из PG, планировщик PG-джобов, `data/` и `config/` не пишутся |
| Админка на PG | логин, аналитика, чаты, пользователи, фото (отдача webp), банк вопросов (чтение/запись/архивация), CSRF |
| Mini App на PG | `/healthz`, сессия по initData, профиль, чаты, прогресс, категории, лидерборд |
| Живая игра из Telegram | фото-викторина (3 вопроса) полностью отработана ботом и записана в `games`/`game_events` |

Найденные и уже исправленные на `main` дефекты, без которых cutover упал бы: отсутствие `flush` в импортёре, киллер дублей, изоляция схемы в тестах, f-string под Python 3.11, healthcheck контейнера.

## 1. Предусловия (gate) — без них не начинать

- [ ] Закрыты открытые пункты [MQB-006](MQB-006-platform-postgresql-cutover.md): Этап 2 (media catalog), Этап 4 (удаление bridge), Этап 5 (Mini App, матрица Telegram).
- [ ] Свежий бэкап: `.env`, `data/`, `config/`, systemd-юниты, nginx-конфиги; отдельно — копия `.git` (в нём лежат локальные правки prod).
- [ ] Понятно, что делать с Mini App: включаем в этом же окне или отдельным этапом (нужен публичный HTTPS + кнопка в BotFather).
- [ ] В `.env` подготовлены все ключи, которые нужны новому коду (в `env.example` их 28: `STORAGE_BACKEND`, `DATABASE_URL`, `POSTGRES_*`, `ADMIN_ACCESS_TOKEN`, `ADMIN_ALLOWED_HOSTS`, `PHOTO_IMAGES_DIR`, `MINI_APP_*`).
- [ ] Зафиксирован тег релиза: `git tag -a vX.Y.Z <commit> && git push origin vX.Y.Z`.
- [ ] Проверено свободное место: PG-том + бэкап + dump (в репетиции хватило 58 ГБ).

## 2. Окно и режим

- Дневная викторина стартует в **07:00 МСК** (`config/quiz_config.json`). Окно cutover — не 06:30–09:00 МСК.
- Оптимально: после дневной викторины, при отсутствии активных игр. Старые снимки без poll ID восстанавливаются как `interrupted`, а не продолжаются.
- Простой: на репетиции импорт занял ~2 с, миграции — секунды; основной бюджет — бэкап и приёмка. Закладывать 30–40 минут.
- На время окна доступна заглушка `maintenance-fallback.service` (переключение через `bot_control.sh`).

## 3. Фаза A — подготовка PostgreSQL (бот продолжает работать на JSON)

```bash
cd /home/lizard/morning-quiz-bot          # в будущем — в каталоге нового релиза
cp .env .env.before-cutover
# ключи PostgreSQL (пароль — свой, не из примера)
cat >> .env <<'ENV'
STORAGE_BACKEND=postgres
DATABASE_URL=postgresql+asyncpg://morning_quiz:СВОЙ_ПАРОЛЬ@127.0.0.1:5432/morning_quiz
POSTGRES_DB=morning_quiz
POSTGRES_USER=morning_quiz
POSTGRES_PASSWORD=СВОЙ_ПАРОЛЬ
POSTGRES_PORT=5432
ENV
docker compose --profile postgres up -d postgres
until docker inspect --format '{{.State.Health.Status}}' morning-quiz-postgres | grep -q healthy; do sleep 3; done
./venv/bin/python -m alembic upgrade head
./venv/bin/python -m alembic current      # ожидаем 20260904_0011 (head)
```

Порт `5432` публикуется только на `127.0.0.1` — чужие БД на сервере не затрагиваются. Если на хосте уже занят 5432, задать `POSTGRES_PORT` и тот же порт в `DATABASE_URL`.

**Прогон на копии (обязательно):** импорт выполнять только в пустые операционные таблицы; для тренировки использовать отдельную БД (`morning_quiz_rehearsal`) и копию `data/`. Именно так репетиция нашла дефект импортёра.

## 4. Фаза B — заморозка и финальный снимок

```bash
sudo systemctl stop quiz-bot quiz-bot-web
cd /home/lizard/morning-quiz-bot
STAMP=$(date +%F_%H%M); BK=/home/lizard/backups/cutover-$STAMP; mkdir -p "$BK"
cp -a .env data config "$BK"/
cp -a *.service nginx*.conf bot_control.sh menu.sh run_bot.bat "$BK"/ 2>/dev/null
tar czf "$BK/json-snapshot.tar.gz" data config
sha256sum "$BK/json-snapshot.tar.gz" | tee "$BK/json-snapshot.sha256"
```

Снимок JSON — единственный источник правды для импорта и единственная страховка откатa. До подтверждённой приёмки его не удалять.

## 5. Фаза C — импорт и сверка

```bash
set -a; . ./.env; set +a
./venv/bin/python -m storage.json_importer --dry-run            # манифест, классификация, ошибки
mkdir -p migration-reports
./venv/bin/python -m storage.json_importer --report migration-reports/postgres-import.json
```

Успех — только если в отчёте одновременно: `status: completed`, пустой `errors`, совпадающие счётчики `source` и `database`, и **все** `normalized_fingerprints[*].matched == true`. Любое расхождение откатывает транзакцию — БД остаётся пустой, бот можно вернуть на JSON.

Ожидаемые счётчики для текущих боевых данных (репетиция): chats 11, users 16, chat_members 24, achievement_grants 184, daily_schedules 18, photo_quiz_items 198, question_categories 63, system_states 7.

## 6. Фаза D — выкладка кода

На проде рабочая копия «грязная»: 110 изменённых tracked-файлов (часть — CRLF-шум при `core.autocrlf=true`), 16 новых путей и 3 симлинка (`bot_control.sh`, `menu.sh`, `maintenance_fallback.py` → `sys/`). Поэтому — **чистый клон, а не `git pull` на месте**.

```bash
sudo -u lizard git clone https://github.com/WeLizard/morning-quiz-bot.git /home/lizard/mqb-new
cd /home/lizard/mqb-new
git config user.name WeLizard && git config user.email WeLizard@users.noreply.github.com
cp /home/lizard/morning-quiz-bot/.env .
cp -a /home/lizard/morning-quiz-bot/{data,logs,backups} .
# симлинки на sys/ НЕ перезаписывать обычными файлами:
for f in bot_control.sh menu.sh maintenance_fallback.py; do ln -sf "sys/$f" "$f"; done
cp -a /home/lizard/morning-quiz-bot/{nginx.conf,nginx-quiz-web-8888.conf,quiz-bot.service,quiz-bot-web.service,maintenance-fallback.service} .
python3.13 -m venv venv && ./venv/bin/pip install -U pip && ./venv/bin/pip install -r requirements.txt
mv /home/lizard/morning-quiz-bot /home/lizard/morning-quiz-bot.before-cutover
mv /home/lizard/mqb-new /home/lizard/morning-quiz-bot
```

systemd-юниты менять не нужно: `WorkingDirectory` и пути те же. `run_web.py` слушает `0.0.0.0:8000` — порт жёстко в коде, при конфликте запускать админку через `uvicorn web.main:app --port <другой>`.

## 7. Фаза E — запуск и приёмка

```bash
sudo systemctl start quiz-bot quiz-bot-web
docker compose --profile postgres up -d postgres     # если PG не поднят
systemctl is-active quiz-bot quiz-bot-web
tail -n 100 logs/bot.log | grep -E "PostgreSQL state|Вопросы загружены|готов принимать обновления|ERROR|Traceback"
```

Приёмка (все пункты обязательны):

- [ ] В логе есть `PostgreSQL state загружен: ... чатов, ... участников` и `Вопросы загружены из PostgreSQL: 63 категорий, ...`.
- [ ] В `logs/` нет `Traceback`, нет упоминаний JSON-фолбэка.
- [ ] За 10 минут работы в `data/` не появилось изменённых `*.json` (PG-режим не пишет mutable JSON).
- [ ] Telegram: `/start`, `/help`, `/categories`, `/top`, `/mystats`, обычная викторина, фото-викторина.
- [ ] Админка: `http://<хост>:8000/login` → вход по `ADMIN_ACCESS_TOKEN`, `/api/analytics/overview` отдаёт реальные числа, банк вопросов открывается, фото отдаётся (`/api/images/<имя>.webp` → 200 `image/webp`).
- [ ] Mini App (если включаем): `/healthz` → 200, кнопка в BotFather открывает приложение, сессия создаётся.
- [ ] `alembic current` = `20260904_0011`, отчёт импорта сохранён в `migration-reports/`.

## 8. Фаза F — наблюдение (48 часов)

- Планировщик: `game_deadlines_and_notifications` (5 с), `postgres_schedule_sync` (15 с), `postgres_cleanup` (15 с) — идут без ошибок.
- Дневная викторина 07:00 МСК прошла, очки начисляются, `/top` совпадает с ожиданиями.
- Нет роста `notification_outbox` с `status != sent`; нет 429-шторма от Telegram.
- Бэкапы из Фазы B и каталог `morning-quiz-bot.before-cutover` не удалять минимум 3 дня.

## 9. Откат

**Случай A — импорт не прошёл или приёмка провалена до записей бота в PG.** Полный откат, потерь нет:

```bash
sudo systemctl stop quiz-bot quiz-bot-web
mv /home/lizard/morning-quiz-bot /home/lizard/morning-quiz-bot.failed
mv /home/lizard/morning-quiz-bot.before-cutover /home/lizard/morning-quiz-bot
sudo systemctl start quiz-bot quiz-bot-web
```

**Случай B — бот уже писал в PostgreSQL.** Обратного экспорта PG→JSON в проекте **нет**, поэтому простой возврат на JSON потеряет всё, что бот записал после cutover (ответы, очки, расписания, игры). Порядок действий:

1. Остановить writers.
2. Снять дамп: `docker exec morning-quiz-postgres pg_dump -U morning_quiz morning_quiz | gzip > pg-dump-$(date +%F_%H%M).sql.gz`.
3. Оценить объём расхождения по таблицам `poll_answers`, `achievement_grants`, `chat_members`, `games`, `game_events`, `question_categories` за время после cutover.
4. Либо согласованно перенести эти записи в JSON вручную (трудозатратно, требует проверки очков и дедупликации ответов), либо продолжить на PG, устранив причину откатa.

Вывод для планирования: окно cutover нужно держать коротким, а откат — решать в первые минуты, пока расхождение мало.

## 10. Известные ограничения и открытые пункты

- `POST /api/mini/classic/.../start` и фото-старт в Mini App отдают 409, пока приложение запущено без `runtime_enabled` (`web/mini_app.py:486`); это конфигурация, не дефект.
- `/api/storage/status` возвращает жёстко зашитые `migration_complete: false` и текст «Локальный dev-контур…» (`web/postgres_admin.py:181-182`) — перед проду активно стоит поправить формулировку.
- В PG-режиме legacy-маршруты и любой несуществующий `/api/*` отдают **501**, а не 404 (`web/postgres_admin.py:505-517`); без сессии сначала 401.
- Тесты, которым нужны `pg_dump`/`createdb`/`psql` на хосте, в контейнерной среде пропускаются (3 шт.) — на сервере при желании доустановить `postgresql-client`.
- Mini App требует публичный HTTPS: HTTP разрешён только для offline+loopback (`web/mini_app.py:40-42`).

## 11. Инцидент-урок (обязательно к соблюдению)

До фикса `bot.py` завершал **все** процессы с `bot.py` в командной строке: запуск второй копии проекта на том же хосте убивал боевого бота (в репетиции это дало ~13 с простоя и восстановление через `Restart=always`). Сейчас дубль определяется по совпадению абсолютного пути к `bot.py`, а проверку можно отключить переменной `MQB_SKIP_DUPLICATE_KILL=1`. Правила:

- Не запускать вторую копию бота на боевом хосте без `MQB_SKIP_DUPLICATE_KILL=1`.
- Для пробных запусков использовать контейнер с отдельным PID namespace (`docker run --network host` сеть, но PID — свой).
