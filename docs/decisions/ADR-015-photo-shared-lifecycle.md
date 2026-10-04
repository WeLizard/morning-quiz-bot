# ADR-015 — Photo как общий серверный lifecycle

- **Статус:** `accepted`
- **Дата:** 2026-09-04
- **Связанные задачи:** MQB-006
- **Следует за:** ADR-014

## Контекст

Фото-загадки уже использовали PostgreSQL-каталог и сохраняли очки, но активная
серия оставалась legacy-снимком в `quiz_sessions`, а переходы выполнял
`PhotoQuizManager` с Telegram context и in-memory timer. Mini App мог безопасно
прочитать картинку, однако запускал игру и отправлял ответы через эмуляцию
Telegram update. Поэтому Telegram оставался фактическим владельцем процесса.

## Решение

Состояние Photo описывает чистая state machine `domain/photo.py`: внутренние
round ID, открытый вопрос, попытки, уровни подсказок, authoritative deadlines,
результат и следующий раунд. `PhotoApplicationService` выполняет start/current/
answer/stop/settle, применяет очки одним PostgreSQL transaction и публикует
Telegram effects через общий outbox.

Mini App вызывает service напрямую. Telegram handlers являются вторым адаптером
того же service; изображения, подсказки и результаты доставляет общий worker.
Клиенты не рассчитывают сходство ответа, штраф, бонус скорости или переходы.

Alembic 0011 переносит сохранённые Photo-серии из `quiz_sessions` в `games`,
включая владельца, прогресс, очки, текущую картинку, подсказки и deadline. Для
неподтверждённой фазы отправки выбирается безопасное `interrupted`: неизвестную
доставку Telegram нельзя повторять вслепую. Legacy `PhotoSessions` временно
сохранён только как адаптер старого manager и также пишет исключительно `games`.

## Последствия

- Фото-серию можно начать, продолжить и завершить независимо от доступности
  Telegram.
- Ответ из Telegram и Mini App применяет одну формулу и один idempotent ledger.
- Сервер восстанавливает подсказки и таймауты по `game_deadlines`; фоновые
  `asyncio.sleep` больше не являются источником истины.
- Кириллические legacy-имена media разрешены как безопасные basename, при этом
  разделители путей, control characters и выход из каталога запрещены.
- Старый manager остаётся переходным кодом для совместимости тестовых сценариев,
  но production/dev startup больше не восстанавливает из него Photo runtime.

## Проверка

- Контейнерный gate: Alembic upgrade/check, **444 passed**, dump/restore и
  JavaScript syntax checks.
- Интеграционные тесты проверяют прямые Mini App start/image/wrong answer/
  idempotent retry/correct answer/restart/stop без MiniBridge.
- Отдельный application test подтверждает два раунда, штраф за ошибку,
  единственное начисление, `games` как источник состояния и отсутствие Photo
  строк в `quiz_sessions`.
