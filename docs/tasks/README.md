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
| NC-OPEN | [«Ночной город»: открытые комнаты](NIGHT_CITY_OPEN_ROOMS.md) | `queued` | medium | 2026-10-28 |
| MQB-011 | [Форма обращения к игроку (он / она / не указывать)](MQB-011-address-form.md) | `in_progress` | medium | 2026-10-15 |

## Дополнительные направления (вне MQB-реестра)

Эти работы ведутся отдельными документами. Их статус не обновляется в таблице
MQB автоматически: перед изменением сверяй документ с git, кодом и свежими
проверками.

| Направление | Где смотреть | Что проверить |
|---|---|---|
| **Плантации фермы (`in_progress`)** | [FARM_PLANTATIONS](FARM_PLANTATIONS.md) | Виноград и чай с L32 в песочнице, браузерная проверка от покупки до переработки прошла. Баланс, ручной сбор, обрезка, кофе и хлопок остаются в работе |
| Ферма: обратная связь, рост, экономика | [FARM_FEEDBACK_2026-10-21](FARM_FEEDBACK_2026-10-21.md), [FARM_GROWTH_PLAN](FARM_GROWTH_PLAN.md), [FARM_ECONOMY_AUDIT](FARM_ECONOMY_AUDIT.md) | Какие пункты уже в git/песочнице, какие локальны, какие только дизайн |
| Ферма: feedback 5 ноября | [FARM_FEEDBACK_2026-11-05](FARM_FEEDBACK_2026-11-05.md) | Компостная карточка, объяснение улучшений, проверка старой автоошибки и предложение тестировщицы о заданиях на развитие |
| Ферма: стройка, просьбы, сад, текстиль | [FARM_VILLAGE_CONSTRUCTION](FARM_VILLAGE_CONSTRUCTION.md), [FARM_FRIEND_REQUESTS](FARM_FRIEND_REQUESTS.md), [FARM_ORCHARD](FARM_ORCHARD.md), [FARM_TEXTILE_CHAIN](FARM_TEXTILE_CHAIN.md) | Шапка документа может отставать от git — сверить перед правкой |
| UI-аудит web shell и фермы (2026-10-25) | [UI_AUDIT_2026-10-25](UI_AUDIT_2026-10-25.md) | Публичная песочница обновлена; приёмка Пуха ожидается, фото-маска остаётся P2 |
| Ферма: новый экран поля, этап 1 | [FARM_FIELD_REDESIGN_INTEGRATION](FARM_FIELD_REDESIGN_INTEGRATION.md) | Старый overlay заменён на текущих правилах; проверить фиксированную выгрузку, 1/2/3 га и живую песочницу |
| Ферма: поле, этап 2A | [FARM_FIELD_TURN_PER_CELL](FARM_FIELD_TURN_PER_CELL.md) | Поворот `2×1↔1×2` и per-cell посев; сохраняется для открытых заходов `rules=2` |
| Ферма: поле, этапы 2B/2C | [FARM_FIELD_SPRAY_AND_TRANSFER](FARM_FIELD_SPRAY_AND_TRANSFER.md) | Опрыскиватель, урон/ремонт, экономика 85–125/90, частичная перекачка для новых заходов `rules=3`; chain не включён |
| Привязка и перенос аккаунтов | [ACCOUNT_LINKING_PLAN](ACCOUNT_LINKING_PLAN.md), [ACCOUNT_FIRST_MIGRATION](ACCOUNT_FIRST_MIGRATION.md) | Живая проверка Telegram и миграции на целевых базах |
| «Ночной город»: дизайн и черновики | [MQB-010](MQB-010-night-city-weekly-stages.md), [черновики дел](night_city/drafts/README.md) | Черновики — только документация; кода режима нет |
| Текущий локальный срез | [FARM_FEEDBACK_2026-10-21](FARM_FEEDBACK_2026-10-21.md), [MQB-011](MQB-011-address-form.md) | `git status`: E1/E8/контрастный режим ещё не закоммичены |

## Известные расхождения статусов

Это не новые статусы и не отметки о завершении, а места, где текст документа
может расходиться с git. Перед изменением статуса нужна проверка.

| Документ | Расхождение |
|---|---|
| [MQB-011](MQB-011-address-form.md) | В шапке «не закоммичено», но код в git (`dfb33a1`) |
| [FARM_VILLAGE_CONSTRUCTION](FARM_VILLAGE_CONSTRUCTION.md) | В шапке «без коммита», но `qw_farm/construction.py` отслеживается git |
| [FARM_TEXTILE_CHAIN](FARM_TEXTILE_CHAIN.md) | В одной шапке одновременно «проект» и «реализация» |

Текущая картина и блокеры — в [STATUS](../STATUS.md). Статус `done` ставится
только по выполненным критериям и проверке, а не по обзорному документу.

## Как добавить задачу

1. Скопировать [шаблон](TASK_TEMPLATE.md).
2. Выбрать следующий свободный номер `MQB-NNN`.
3. Заполнить границы, критерии готовности и проверку.
4. Добавить строку в таблицу выше.
5. Если задача принимает долговечное архитектурное решение, создать ADR.

Завершённые и отменённые задачи остаются в каталоге: это сохраняет ссылки и
историю решений. Для них меняется только статус в файле и реестре.
