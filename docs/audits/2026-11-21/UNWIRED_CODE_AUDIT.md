# Написано, но не подключено — аудит 2026-11-21

Аудит только на чтение: граф импортов от точек входа и поиск по отслеживаемым файлам.
Тесты, `scripts/`, `handlers/quiz/` и документы не считались. Состояние серверов
(песочница, прод) не проверялось — выводы о выкладке сделаны только по файлам репозитория.

Повод: маршруты ведущего-ИИ Night Case написаны и покрыты тестами, но приложение их не
регистрирует. Правило «написанный код должен быть подключён» записано в `AGENTS.md`.

## Точки входа

| Процесс | Где задан | Замечание |
|---|---|---|
| Бот | `bot.py` (через `main.py`) | Единственный процесс в `docker-compose.yml`, `Dockerfile`, `quiz-bot.service`, `sys/deploy.sh` |
| Админка | `web/run_web.py` → `web.main:app`, порт 8000 | `quiz-bot-web.service`; `install_postgres_admin(app)` монтирует 12 роутеров |
| Превью админки, 4184 | `scripts/run_admin_preview.py` | Только `compose.dev.yml` |
| Мини-приложение, 4185 | `web.dev_mini_app:create_dev_app` → `web.mini_app.create_app` | Только `compose.dev.yml` и `Dockerfile.dev` |
| Игровой воркер | `scripts/run_game_worker.py` | Только `compose.dev.yml` |

**Пробел в выкладке по файлам репозитория:** продовые файлы запускают только бота и
админку. Мини-приложение и игровой воркер (дедлайны партий Мафии и Night Case) в них не
запускаются. Если прод и песочница собраны другими файлами вне репозитория — это нужно
записать в `docs/DEPLOYMENT.md`.

## 1. Игроку недоступно

| Что | Где | Почему не работает | Что нужно |
|---|---|---|---|
| API ведущего-ИИ для игрока (`ai`, `ai/byok`, `ai/request`, `ai/off`, `ai/presets`) | `web/night_case_ai_routes.py:104` | `register_night_case_ai_routes` нигде не вызывается; в UI нет вызовов `/ai/` | Вызвать в `mini_app.create_app` рядом с `register_night_case_routes`, сделать UI. Делается в отдельной сессии |
| `NightCaseOrchestrator`, `NightCaseAIDispatcher` | `application/night_case_orchestrator.py`, `application/night_case_ai_dispatch.py:133` | `create_app(night_case_orchestrator=None)`; вне тестов не создаются. Поле свободного намерения в `night-case-ui.js:544` поэтому не показывается | Собрать оркестратор в фабрике мини-приложения и передать в `create_app` |
| Задачи ИИ, озвучка описаний, уведомления, восстановление после сбоев | `night_case_ai_dispatch.py:611 expire_due`, `storage/night_cases.py:326/342/372/406`, `application/night_case.py:1242 resume_outage` | Вызываются только в тестах; воркеры их не вызывают | Запланировать в `run_game_worker.py` / `NightCaseDeadlineWorker.run_once` |
| Кнопка «Прочитать описание» | `web/mini_client/night-case-ui.js` (~714) | Появляется только при `job_id`, а задачи озвучки никто не создаёт | Вместе с пунктом выше |
| Карточка `/farm` в боте | `handlers/farm_widget_handlers.py:43`, `bot.py:544` | Включается `QW_FARM_ENABLED=1`, а флага нет в окружении бота | Добавить флаг боту и в `env.example` |
| Команды `adddailyquiz`, `removedailyquiz`, `listdailyquizzes`, `reloadcfg`, `daily_wisdom` | `config/quiz_config.json:96-100` | Обработчиков нет | Удалить из конфига или сделать обработчики |

Сюда же: передача ведущему обликов, предметов и мест (правило П9, коммит b3d3b65) работает
только при включённом ведущем-ИИ, поэтому игрокам пока не видна.

## 2. Владельцу (админке) недоступно

| Что | Где | Почему | Что нужно |
|---|---|---|---|
| Админ-роутер ведущего-ИИ (12 маршрутов `/api/admin/night-case/ai/*`) | `web/night_case_ai_admin.py:29` | Нет в `include_router` в `web/postgres_admin.py:503-525`; `config/night_case_ai_runtime.py` никто не импортирует | Подключить в `install_postgres_admin`, собрать конфиг, сделать экран. Делается в отдельной сессии |
| 70 старых маршрутов админки JSON-эпохи | `web/main.py` (334–4385) | В режиме PostgreSQL `prevent_json_fallback` отвечает 501 на всё, чего нет в PG-роутерах | Удалить или перенести в `make_*_router` |
| Старый UI админки, который зовёт эти маршруты | `web/static/js/app.js` (режим системы, перезапуск бота, логи, рассылка, чёрный список, метрики, экспорт) | Все вызовы получают 501. Кнопки экспорта видны и не работают (`app.js:3368,3613-3619`, `index.html:224,464,483`) | Удалить или перенести; экспорт — решить отдельно |
| `GET /api/analytics/chats`, `/api/analytics/chats/{chat_id}` | `web/postgres_admin.py:384,394` | Ни один экран их не зовёт | Добавить экран или удалить |

## 3. Выключено флагом, который нигде не выставлен

Ни один из флагов ниже не записан в `env.example`, `docker-compose.yml`, `compose.dev.yml` или `.service`.

| Флаги | Где читаются | Что выключено | Что нужно |
|---|---|---|---|
| `MQB_NIGHT_CASE_ENABLED`, `MQB_NIGHT_CASE_STARTS_ENABLED`, `MQB_NIGHT_CASE_CURSOR_SECRET` (от 32 байт), `MQB_NIGHT_CASE_CASE_HASHES`, `MQB_NIGHT_CASE_READINESS_URL` | `config/night_case.py:45-50`, `web/mini_app.py:367-385`, `scripts/run_game_worker.py:31-47` | Вся игра Night Case и её воркер | Выставить в мини-приложении и воркере. Адрес готовности по умолчанию `127.0.0.1:8000/healthz` указывает на порт админки, где `/healthz` нет; он есть у мини-приложения (`mini_app.py:665`) |
| `NIGHT_AI_*`, `NIGHT_NARRATOR_ENABLED`, `NIGHT_NARRATOR_EXTERNAL_ALLOWED` | `storage/night_ai.py`, `config/night_case_ai_runtime.py:116` | Ведущий-ИИ и ключи | Вместе с разделом 1 |
| `MINI_APP_RUNTIME_ENABLED` | `web/mini_app.py:373` | Запись ходов в мини-приложении (классика, фото, мафия) | В `env.example` и окружение мини-приложения |
| `MQB_ROOM_CLASSIC_ENABLED`, `MQB_ROOM_PHOTO_ENABLED` | `web/mini_app.py:375-378` | Классика и фото в комнатах и у гостей | Только в `compose.dev.yml` со значением `0`; добавить в `env.example` и окружение |
| `QW_FARM_ENABLED` | `qw_farm/integration.py:91`, `application/game_catalog.py:49`, `handlers/farm_widget_handlers.py:43` | Ферма: маршруты, пункт каталога, `/farm` | Выставлен только dev-мини-приложению; без него в каталоге ферма «скоро» |
| `QW_FARM_INVITE_SECRET`, `QW_FARM_MERCHANT_SECRET`, `QW_FARM_RATE_SECRET`, `QW_FARM_SHARED_RATE_ENABLED` | `qw_farm/*.py` | Приглашения, торговец, общий лимит | Описать; общий лимит миграция `qw_farm_011.py:23` прямо запрещает |
| `MQB_ROOM_CODE_SECRET`, `MINI_APP_SHORT_NAME`, `MINI_APP_BOT_USERNAME` | `application/room_limits.py:94`, `modules/mini_app_launch.py`, `qw_farm/integration.py:170` | Есть запасные значения | Добавить в `env.example` |
| `MQB_ADMIN_AI_ENABLED=0` | `env.example` | ИИ-редактор админки | Выключен намеренно |

## 4. Мёртвые остатки

| Что | Где | Что сделать |
|---|---|---|
| JS админки, который не грузит ни одна страница: `app_crud.js` (дубль `app.js`), `categories.js`, `chats.js`, `questions.js`, `photo-quiz.js` | `web/static/js/` | Удалить |
| `web/templates/index_modern.html` | — | Удалить |
| `web/prototypes/mini-app/{index.html,app.js,styles.css}` | картинки `host-*.webp` оттуда используются | Удалить HTML, JS, CSS; картинки оставить |
| `chatSelect` | `web/mini_client/app.js:1242` | Удалить |
| `GET /api/mini/leaderboard` | `web/mini_app.py:1859` | UI берёт `/api/account/rating`; удалить или подключить |
| `GET /api/night-case/games/{id}/messages/{message_id}` | `web/night_case_routes.py:180` | UI не зовёт; подключить или удалить |
| `POST /api/farm/v1/invite/share/revoke` | `qw_farm/api.py:108` | UI фермы не зовёт; подключить или удалить |
| Команда фермы `restart_all` | `qw_farm/expansion.py:33,764,931` | UI шлёт `repeat_once`; удалить |
| `DeveloperNotifier` | `modules/developer_notifier.py:12` | Никто не импортирует, `set_developer_notifier` не вызывается; удалить или подключить |
| Неиспользуемые методы бота | `config_handlers.py:1717`, `common_handlers.py:753`, `wisdom_scheduler.py:260,288`, `daily_quiz_scheduler.py:418`, `photo_quiz_manager.py:528,1128`, `category_manager.py:736`, `telegram_widgets.py:123`, `telegram_api_ext.py:173` | Удалить |
| Помощники JSON-эпохи | `data_manager.py` (223, 235, 253, 303, 310, 1154, 1177, 1490-1512), `utils.py:136-300`, `storage/runtime.py`, `storage/repositories.py:239` | Удалить |
| Прочие неиспользуемые функции | `qw_farm/merchant.py:410`, `qw_farm/persistence.py:352`, `domain/mafia.py:143`, `domain/night_case_personal.py:35`, `storage/question_bank.py:31,38` | Удалить |

Инструменты для скриптов (`domain/night_case_rules.py`, `domain/night_case_simulation.py`,
`modules/telegram_test_scope.py`, `storage/legacy_sync.py`, `storage/score_reconcile.py`) —
это проверки и CLI, а не фичи; подключать их не нужно.

## Что подключено (проверено)

Все роутеры `make_*_router`, кроме админ-роутера ведущего-ИИ; все `install_*` и
`register_night_case_routes`; все обработчики и планировщики в `bot.py`, кроме перечисленных;
все модули `qw_farm/static/*.js`; все PG-маршруты админки, кроме двух аналитических.
Маршруты `/api/mini/*` и `/api/guest/*` собираются в `app.js` динамически и проверены
менее строго.
