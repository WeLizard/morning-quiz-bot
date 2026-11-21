# Индекс документации Morning Quiz

Этот файл — единая точка входа в документацию проекта. Если документ не указан
здесь или в реестре задач, его актуальность необходимо проверить по коду перед
использованием.

## Роли документов

| Роль | Канонический источник | Что там искать |
|---|---|---|
| Правила | [AGENTS.md](../AGENTS.md), [DEVELOPMENT](engineering/DEVELOPMENT.md) | Что обязательно, как вести работу |
| Карта | этот файл | Куда идти за тем или иным знанием |
| Статус | [STATUS.md](STATUS.md) | Что проверено, что нет, блокеры, delete-zone |
| Задачи | [tasks/README.md](tasks/README.md) | Планируемая и текущая работа, статусы задач |
| История | [decisions/README.md](decisions/README.md), [CHANGELOG.md](CHANGELOG.md) | Принятые решения и выпущенные изменения |

Статус задачи не считается закрытым по обзорному документу: проверяй критерии,
код, git и свежие тесты. `STATUS.md` не меняет статусы задач.

## Куда идти

| Нужно | Куда |
|---|---|
| Узнать текущее состояние и блокеры | [STATUS.md](STATUS.md) |
| Начать или проверить задачу | [tasks/README.md](tasks/README.md) |
| Понять архитектуру и долг | [аудит 2026-10-15](audits/2026-10-15/ARCHITECTURE_AUDIT.md) |
| Найти написанное, но не подключённое | [аудит 2026-11-21](audits/2026-11-21/UNWIRED_CODE_AUDIT.md) |
| Проверить критерии выпуска | [RELEASE_CRITERIA](engineering/RELEASE_CRITERIA.md) |
| Заняться фермой | [FARM_FEEDBACK_2026-10-21](tasks/FARM_FEEDBACK_2026-10-21.md), [FARM_GROWTH_PLAN](tasks/FARM_GROWTH_PLAN.md), [FARM_ECONOMY_AUDIT](tasks/FARM_ECONOMY_AUDIT.md) |
| Заняться «Ночным городом» | [MQB-010](tasks/MQB-010-night-city-weekly-stages.md), [дизайн](tasks/NIGHT_CITY_WEEKLY_DESIGN.md), [черновики дел](tasks/night_city/drafts/README.md), [обкатка «Усадьбы»](tasks/night_city/NIGHT_CASE_REHEARSAL_RUNBOOK.md), [AI-доступ](tasks/night_city/NIGHT_CASE_AI_ACCESS.md), [транспорт T](tasks/night_city/NIGHT_CASE_TRANSPORT_DRAFT.md), [рассказчик N](tasks/night_city/NIGHT_CASE_DIRECTOR_DRAFT.md) |
| Понять UI-правила | [UI_RULES](design/UI_RULES.md) |

## Быстрый вход

- [Единый свод: результаты поля, задачи, согласованность и предложения (2026-10-29)](PROJECT_ALIGNMENT_2026-10-29.md)
- [Текущий статус, блокеры и границы проверенного](STATUS.md)
- [Текущий dev-контур: все разделы, тестовый бот, архивы и ограничения](DEV_FEATURES.md)
- [Полный dev-backlog: сохранение всех функций оригинала](tasks/MQB-002-dev-feature-parity.md)
- [Первый локальный комплект: запуск и приёмка одной командой](LOCAL_MILESTONE.md)
- [Быстрый старт](QUICK_START.md)
- [Локальная разработка и перенос на сервер](LOCAL_DEVELOPMENT.md)
- [Обзор проекта](PROJECT_OVERVIEW.md) — исторический, не текущий статус
- [Проверенная по коду карта функций](CODE_VERIFIED_FEATURE_MAP.md) — baseline 2026-08-30, не текущий статус
- [PostgreSQL: локальный запуск и импорт JSON](POSTGRESQL_MIGRATION.md)
- [PostgreSQL: транзакционные баллы, локальная админка и тесты](POSTGRESQL_ADMIN.md)
- [Локальная админка: вход, готовые экраны и безопасный preview](ADMIN_AUTH.md)
- [Профили участников/чатов, история, экспорт и переименование](ADMIN_PROFILES.md)
- [Действующие блокировки и безопасный сброс прогресса](ADMIN_MODERATION.md)
- [PostgreSQL: применение расписаний без перезапуска](POSTGRESQL_SCHEDULES.md)
- [PostgreSQL: фото-квиз и восстановление серии](POSTGRESQL_PHOTO_QUIZ.md)
- [Фото-каталог: загрузка, ограничения и сохранность изображений](PHOTO_CATALOG.md)
- [PostgreSQL: восстановление классического квиза и очистка](POSTGRESQL_RECOVERY.md)
- [Классический бот: локальный PTB 22.8, безопасная отправка и планы новых API](TELEGRAM_QUIZ_ROADMAP.md)
- [Mini App: вход, пользовательский API и локальный запуск](MINI_APP_API.md)
- [Играть в боте или Mini App: функции и незакрытые сценарии](MINI_APP_GAMEPLAY.md)
- [Общее ядро и равноправные интерфейсы](tasks/MQB-005-application-core-and-adapters.md)
- [Главная программа развития: PostgreSQL-only платформа](tasks/MQB-006-platform-postgresql-cutover.md)
- [Аудит и последовательное устранение 28 находок (2026-10-08)](tasks/QUIZZYWIZZY-2026-10-08.md)
- [Farm 0.2.0: dev-интеграция и приёмочные ворота](tasks/MQB-007-farm-020-integration.md)
- [Farm: контракт с платформой и локальная эксплуатация](FARM_INTEGRATION.md)
- [Ферма: отладчик производительности (?debug=perf) и бюджет отрисовки в CI](FARM_PERF_DEBUG.md)
- [Безопасный read-only аудит банка вопросов](engineering/QUESTION_BANK_AUDIT.md)
- [Безопасный read-only аудит очереди уведомлений](engineering/NOTIFICATION_OUTBOX_AUDIT.md)
- [Временный HTTPS-тест Mini App и безопасная остановка](TELEGRAM_MINI_APP_TEST.md)
- [Правила ведения документации](DOCUMENTATION_RULES.md)
- [Активные задачи](tasks/README.md)
- [Архитектурные решения](decisions/README.md)

## Эксплуатация

- [Развёртывание](DEPLOYMENT.md)
- [Настройка администраторов](ADMIN_SETUP.md)
- [Диагностика проблем](TROUBLESHOOTING.md)
- [Логирование](LOGGING_SYSTEM.md)
- [Управление через веб-панель](WEB_PANEL_SYSTEM_CONTROL.md)

## Функциональность и справочники

- [Telegram API: предложения по всем играм и мини-играм (2026-11-16)](audits/2026-11-16/TELEGRAM_API_GAME_PROPOSALS.md) — исследование; внедрение не согласовано.
- [Проверенная по коду карта функций](CODE_VERIFIED_FEATURE_MAP.md) — текущий
  baseline совместимости.
- [Команды Telegram](COMMANDS_REFERENCE.md) — legacy, требуется сверка.
- [Навигация по меню](MENU_NAVIGATION_MAP.md) — legacy, требуется сверка.
- [Структура данных](DATA_STRUCTURE_OVERVIEW.md) — legacy, требуется сверка.
- [Новая структура данных](NEW_DATA_STRUCTURE.md) — legacy, требуется сверка.
- [Карта приложения](APPLICATION_MAP.md) — legacy, требуется сверка.
- [Система достижений](ACHIEVEMENTS_DISPLAY.md)
- [Права бота](BOT_PERMISSIONS.md)

## Планирование изменений

- Новая работа сначала оформляется в [реестре задач](tasks/README.md).
- Существенные архитектурные решения фиксируются как ADR в
  [каталоге решений](decisions/README.md).
- После завершения задачи обновляются связанные руководства и `CHANGELOG.md`.

## Исторические материалы

Каталог `ARCHITECTURE/` содержит старые планы, аудиты и инструкции для агентов.
Они полезны как контекст, но не являются автоматически актуальным источником
истины. При расхождении приоритет имеют:

1. работающий код, тесты, конфигурация и миграции;
2. принятые ADR;
3. активная задача;
4. профильный документ из `docs/`;
5. исторические отчёты и аудиты.

Последняя проверка индекса: 2026-10-23. Текущее состояние и блокеры — в
[STATUS.md](STATUS.md); статусы задач — в [реестре](tasks/README.md).
