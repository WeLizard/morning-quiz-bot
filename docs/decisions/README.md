# Архитектурные решения (ADR)

ADR фиксирует значимое техническое решение вместе с контекстом и последствиями.
Принятый ADR не переписывается задним числом: новое решение создаёт новый ADR и
помечает предыдущий как `superseded`.

## Статусы

- `proposed` — решение обсуждается;
- `accepted` — решение принято и действует;
- `rejected` — вариант рассмотрен и отклонён;
- `superseded` — заменено более новым ADR.

## Реестр

| ID | Решение | Статус | Дата |
| --- | --- | --- | --- |
| ADR-001 | [PostgreSQL как основное хранилище](ADR-001-postgresql-primary-store.md) | `accepted` | 2026-08-30 |
| ADR-002 | [Адресное сохранение игр и очередь очистки](ADR-002-runtime-checkpoints.md) | `accepted` | 2026-08-30 |
| ADR-003 | [Отдельная сессия локального администратора](ADR-003-local-admin-sessions.md) | `accepted` | 2026-08-30 |
| ADR-004 | [Версионированный файловый банк вопросов](ADR-004-local-question-bank.md) | `superseded` | 2026-08-30 |
| ADR-005 | [Блокировки и сброс без удаления истории](ADR-005-moderation-and-reset.md) | `accepted` | 2026-08-30 |
| ADR-006 | [Отправка Telegram без слепых повторов](ADR-006-telegram-delivery-contract.md) | `accepted` | 2026-08-30 |
| ADR-007 | [Отдельный пользовательский контур Mini App](ADR-007-mini-app-user-api.md) | `accepted` | 2026-08-30 |
| ADR-008 | [Постоянный dev-контур и безопасные эксплуатационные операции](ADR-008-persistent-dev-parity.md) | `accepted` | 2026-08-31 |
| ADR-009 | [Бот и Mini App — два интерфейса одной игры](ADR-009-shared-game-interfaces.md) | `superseded` | 2026-08-31 |
| ADR-010 | [Morning Quiz — приложение с внешними адаптерами](ADR-010-application-core-and-adapters.md) | `accepted` | 2026-09-01 |
| ADR-011 | [Общее хранилище долгоживущих игр](ADR-011-game-substrate.md) | `accepted` | 2026-09-04 |
| ADR-012 | [Транзакционный PostgreSQL-банк вопросов](ADR-012-postgresql-question-bank.md) | `accepted` | 2026-09-04 |
| ADR-013 | [PostgreSQL-каталог и content-addressed photo media](ADR-013-authoritative-photo-media.md) | `accepted` | 2026-09-04 |
| ADR-014 | [Classic как серверный lifecycle с независимой доставкой](ADR-014-classic-shared-lifecycle.md) | `accepted` | 2026-09-04 |
| ADR-015 | [Photo как общий серверный lifecycle](ADR-015-photo-shared-lifecycle.md) | `accepted` | 2026-09-04 |

Новый документ создаётся по [шаблону](ADR_TEMPLATE.md) и добавляется в этот
реестр.
