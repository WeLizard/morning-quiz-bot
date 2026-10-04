# PostgreSQL: локальный запуск и импорт JSON

Этот документ относится к этапам 1–3 задачи
[MQB-001](tasks/MQB-001-postgresql-and-mini-app-foundation.md). PostgreSQL,
импортёр и PostgreSQL runtime-adapter бота уже доступны. До production cutover
локальный запуск обязан явно выбрать backend; переключение выполняется только
после snapshot и контрольного импорта.

Боевая выкладка описана отдельно — [tasks/MQB-007](tasks/MQB-007-production-cutover-runbook.md)
(предусловия, окно, приёмка, откат). Ниже — как подготовить данные, проверить
импорт и запустить бота на PostgreSQL.

## Что переносится сейчас

- чаты и их настройки;
- пользователи, участие в чатах, очки, серии и списки обработанных poll;
- достижения;
- расписания обычной викторины и мудростей;
- активные викторины;
- метаданные фото-викторины;
- категории и содержимое обычного банка вопросов;
- служебные состояния.

`data/questions/*.json` и `data/global/categories.json` являются входом
одноразовой миграции. После импорта bot, Mini App и admin API читают и изменяют
банк только через PostgreSQL. В чистой dev/test-БД эти файлы могут один раз
использоваться явным seed-процессом; это bootstrap, а не второй runtime source.

## Подготовка в PowerShell

Скопируйте PostgreSQL-параметры из `env.example` в локальный `.env` и обязательно
замените пароль. Для запуска только БД:

```powershell
docker compose --profile postgres up -d postgres
docker compose --profile postgres ps
```

При запуске Python-команд с хоста в `DATABASE_URL` нужен `127.0.0.1`, а не имя
Docker-сервиса `postgres`:

```powershell
$env:DATABASE_URL = 'postgresql+asyncpg://morning_quiz:YOUR_PASSWORD@127.0.0.1:5432/morning_quiz'
```

## Миграция схемы

```powershell
python -m alembic upgrade head
python -m alembic current
python -m alembic check
```

Ожидаемая текущая ревизия: `20260904_0011 (head)`. `0008` добавляет общий game
substrate и переносит legacy Mafia state, `0009` создаёт транзакционный
PostgreSQL-банк вопросов и его журнал ревизий, `0010` переносит classic runtime
в `games`, `0011` делает то же для фото-викторины.

## Snapshot перед финальным импортом

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File '.\scripts\New-JsonMigrationSnapshot.ps1'
```

Скрипт создаёт ZIP с `data/` и `config/`, затем выводит размер и SHA-256. Архив
попадает в игнорируемую Git директорию `backups/postgres-cutover/`.

## Проверка JSON без записи

```powershell
python -m storage.json_importer --dry-run
```

Команда читает текущие файлы, считает сущности, строит manifest с размером,
SHA-256 и классификацией каждого JSON-источника, но не подключается к
PostgreSQL. `operational` входит в импорт и общий source digest, включая банк
вопросов; `static_configuration` не копируется в `system_states`, а
`historical_backup` только фиксируется. Поэтому изменение статического текста
ачивки больше не маскируется под изменение runtime snapshot.

## Импорт

```powershell
New-Item -ItemType Directory -Force -Path '.\migration-reports' | Out-Null
python -m storage.json_importer --report '.\migration-reports\postgres-import.json'
```

Импорт выполняется одной транзакцией **только в пустые операционные таблицы**.
Внутренний upsert не является разрешением повторять импорт: непустая БД
(включая предыдущий импорт) теперь даёт отказ до записи. Импортёры сериализованы
advisory lock, таблицы блокируются от конкурентной записи на время импорта.
Ошибки snapshot запрещают запуск; ошибки нормализации откатывают транзакцию.
Старый JSON нельзя применять поверх нового прогресса. Успешный
результат должен иметь `status: completed`, пустой `errors` и одинаковые
контрольные числа в секциях `source` и `database`. Дополнительно каждый элемент
`normalized_fingerprints` обязан иметь `matched: true`: fingerprints сверяют не
только число строк, но и нормализованное содержимое всех переносимых сущностей.
Любое несовпадение откатывает ту же транзакцию и завершает CLI с ошибкой.

## Проверка тестами

Не направлять интеграционные тесты на `morning_quiz_dev`: они создают и удаляют
тестовые записи. Использовать отдельную `morning_quiz_test` в общем локальном
контейнере по
[инструкции тестового контура](POSTGRESQL_ADMIN.md#воспроизводимые-проверки-на-windows).
Проверяются дубли ответов, параллельные начисления, бонусы серий,
правка администратора, откат и фото-квиз.

Перед прогоном БД-тестов саму `morning_quiz_test` нужно мигрировать
(`DATABASE_URL=.../morning_quiz_test python -m alembic upgrade head`). Без этого
в ней нет схемы и десятки тестов падают с `relation "..." does not exist`.
Изоляцию внутри прогона обеспечивает временная схема на каждый тест; тесты без
`TEST_DATABASE_URL` просто пропускаются.

## Пробный запуск бота на PostgreSQL

После snapshot, `alembic upgrade head` и успешного импорта:

```powershell
$env:STORAGE_BACKEND = 'postgres'
$env:DATABASE_URL = 'postgresql+asyncpg://morning_quiz:YOUR_PASSWORD@127.0.0.1:5432/morning_quiz'
python .\bot.py
```

При этом runtime загружает из PostgreSQL пользователей, очки, серии,
достижения, настройки, расписания, очередь удаления, категорийную статистику и
активные викторины. Telegram menu/conversation cursor в PG-режиме хранится лишь
в памяти и безопасно сбрасывается при restart; `.postgres-ui.pickle` больше не
создаётся. Игровое и пользовательское состояние от этого не теряется.

## Ограничение текущего этапа

В локальном runtime реализованы [восстановление классических опросов и очередь
очистки](POSTGRESQL_RECOVERY.md). Старые снимки игр без poll ID и дедлайнов
сохраняются как interrupted, а не автоматически продолжаются. Рейтинги и
профили сохраняются. До финального импорта следует завершить активные JSON-игры.

Локальная FastAPI-админка работает с БД для банка вопросов, чатов,
пользователей, аналитики, баллов, настроек и расписаний. Оставшиеся
непереведённые legacy-маршруты в PG-режиме возвращают 501 без JSON fallback.
Список готовых маршрутов и открытых проблем приведён в
[руководстве админки](POSTGRESQL_ADMIN.md). Пользовательский Mini App API
остаётся отдельным контуром и не открывает административные endpoints.

Для отката остановите writers и сохраните состояние БД. Если после импорта уже
появились новые записи, сначала потребуется их согласованно перенести: простой
возврат `STORAGE_BACKEND=json` и старого ZIP потеряет новые результаты.
