# Реестр задач

Реестр содержит проектные задачи, для которых важны архитектурный контекст,
границы и проверяемые критерии готовности. Мелкие локальные исправления можно не
оформлять отдельным документом.

Актуальные правила разработки и выпуска: [DEVELOPMENT](../engineering/DEVELOPMENT.md), [RELEASE_CRITERIA](../engineering/RELEASE_CRITERIA.md), [FARM_CONCEPT](../engineering/FARM_CONCEPT.md) и [AGENTS.md](../../AGENTS.md). Концепт фермы — предложение для обсуждения, не обязательный scope.

## Текущие задачи

| ID | Задача | Статус | Приоритет | Обновлена |
| --- | --- | --- | --- | --- |
| MQB-001 | [PostgreSQL-хранилище и фундамент Telegram Mini App](MQB-001-postgresql-and-mini-app-foundation.md) | `in_progress` | high | 2026-09-01 |
| MQB-002 | [Полный функциональный dev-комплект](MQB-002-dev-feature-parity.md) | `in_progress` | high | 2026-09-01 |
| MQB-003 | [Mini App, меню и настройки Telegram](MQB-003-telegram-experience.md) | `in_progress` | high | 2026-09-01 |
| MQB-004 | [«Ночной город»: фундамент мафии](MQB-004-night-city-mafia.md) | `in_progress` | high | 2026-09-01 |
| MQB-005 | [Общее ядро Morning Quiz и равноправные интерфейсы](MQB-005-application-core-and-adapters.md) | `in_progress` | high | 2026-09-01 |
| MQB-006 | [PostgreSQL-only игровая платформа](MQB-006-platform-postgresql-cutover.md) | `in_progress` | critical | 2026-09-04 |
| QW-2026-10-08 | [QuizzyWizzy audit remediation](QUIZZYWIZZY-2026-10-08.md) | `in_progress` | critical | 2026-10-09 |
| MQB-007 | [Приёмка и dev-интеграция Farm 0.2.0](MQB-007-farm-020-integration.md) | `in_progress` | high | 2026-10-09 |
| MQB-009 | [Завершение платформы и новый «Ночной город»](MQB-009-platform-and-night-city.md) | `proposed` | critical | 2026-10-12 |
| MQB-010 | [«Ночной город»: недельный режим, этапы](MQB-010-night-city-weekly-stages.md) (дизайн: [NIGHT_CITY_WEEKLY_DESIGN](NIGHT_CITY_WEEKLY_DESIGN.md)) | `proposed` | high | 2026-10-15 |
| MQB-011 | [Форма обращения к игроку (он / она / не указывать)](MQB-011-address-form.md) | `in_progress` | medium | 2026-10-15 |

## Как добавить задачу

1. Скопировать [шаблон](TASK_TEMPLATE.md).
2. Выбрать следующий свободный номер `MQB-NNN`.
3. Заполнить границы, критерии готовности и проверку.
4. Добавить строку в таблицу выше.
5. Если задача принимает долговечное архитектурное решение, создать ADR.

Завершённые и отменённые задачи остаются в каталоге: это сохраняет ссылки и
историю решений. Для них меняется только статус в файле и реестре.
