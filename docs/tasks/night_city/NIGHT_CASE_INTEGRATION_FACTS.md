# Night Case: факты интеграции по текущему коду

**Срез:** 2026-11-15, dev-копия, ветка `main`. Read-only исследование исходников и
конфигурации; БД, `.env`, секреты и тесты не открывались/не запускались.

Этот документ фиксирует наблюдения для следующего среза. Это не принятый план,
не новое требование и не свидетельство готовности режима. Новый режим в БД
называется строго `night_case`; `night_city` здесь не используется как mode id.

## Существующая игровая основа

1. **Транзакция и principal.** `storage/database.py:78-82` —
   `Database.transaction()` выдаёт `AsyncSession` внутри `session.begin()`.
   `web/mini_app.py:933-945` — `room_principal` разрешает account и передаёт
   session в обработчик. Room API использует общий principal для guest/Telegram.

2. **Account и room.** `storage/models.py:68-85,176-207` — Account имеет UUID,
   Room хранит owner UUID и состояние комнаты, RoomMembership ссылается на UUID
   и имеет role/status. `:259-274` — RoomTransport отображает внешнюю группу/чат
   на room и не выводит из этого account identity.

3. **Game envelope / roster.** `storage/models.py:365-429` — Game уже содержит
   `room_id`, nullable `chat_id`, `mode`, `status/phase/revision/state`, а
   уникальность текущей игры задаётся парой room+mode. GamePlayer имеет PK
   `(game_id, account_id)`, nullable Telegram `user_id`, public/private state.
   Эти таблицы mode-neutral по форме; mode-specific содержимое state — нет.

4. **Repository и транзакционные примитивы.** `storage/games.py:96-108` —
   `current_in_room` блокирует logical room+mode key через advisory lock.
   `:163-199` — `create_room_current` создаёт game только для standalone Room,
   без Telegram id; `:234-249` — `sync_state` атомарно синхронизирует state,
   проекции и дедлайны; `:295-316` — `append_event`.
   `storage/database.py:78-82` задаёт внешнюю транзакцию.

5. **Commands, events, deadlines.** `storage/models.py:447-472` —
   GameCommand хранит idempotency receipt и actor Account UUID;
   `:475-500` — GameEvent append-only с `public/private` visibility и уникальным
   `(game_id,event_index)`; `:503-521` — GameDeadline с kind, due time, status,
   revision и unique `(game_id,kind)`. `storage/games.py:302-315` присваивает
   общий следующий event index по максимуму всех событий игры. Индекс/счётчик
   нельзя показывать как частную статистику: private events тоже сдвигают его.

6. **Текущие room command образцы.** `application/mafia.py:531-569` — создание
   room lobby с owner membership, GameRepository, receipt и viewer projection;
   `:573-627` — join/readiness; `:663-724` — room discussion. Это примеры
   использования общих примитивов, но они фиксируют mode `mafia`, не
   реализуют `night_case`.

7. **Room access и leave.** `application/rooms.py:106-132` — list/get требуют
   активное membership. `:134-180` — leave сериализует только modes
   `classic`, `mafia`, `photo`, запрещает уход владельцу, проверяет
   membership_version; незавершённые не-mafia игры блокируют выход, Mafia
   вызывает `leave_table`, затем membership становится inactive. Этот список
   не включает `night_case`; его поведение выхода текущим кодом не определено.

8. **Web boundary и CSRF.** `web/mini_app.py:456-493` — middleware проверяет
   origin/CSRF и ограничивает room traffic; `:918-945` — выбор identity и
   общий principal; `:957-1163` — room CRUD/join/open/leave/get. Примеры
   room mode endpoints — Classic `:1186-1242`, Mafia discussion
   `:1429-1459`. Room writes через guest/mini channel требуют соответствующий
   CSRF header по middleware `:472-480`.

9. **Deadline worker.** `application/game_deadlines.py:16-42` собирает due
   candidates явно через Mafia, Classic и Photo services; `:62-85` отдельно
   settle room Classic/Photo и изолирует каждую операцию транзакцией.
   `scripts/run_game_worker.py:43-56` запускает polling worker. Наличие
   GameDeadline само по себе не подключает новый mode к сбору и исполнению.

10. **PostgreSQL и миграции.** `alembic/versions/20260904_0008_game_substrate.py:20-106`
    создаёт games/commands/events/deadlines; `20261008_0017_rooms.py` добавляет
    rooms/memberships/transports; `20261008_0020_room_scoped_games.py:16-43`
    разрешает room-owned games и account-only roster; `20261008_0021_canonical_mafia_state.py`
    преобразует Mafia state и проверяет roster. PG fixture
    `tests/conftest.py:39-99` пересоздаёт только разрешённую тестовую БД и
    выполняет `alembic upgrade head`; `compose.dev.yml:52-79,95-100` описывает
    PostgreSQL 17, migrate и worker. Это карта проверок, не результат их запуска.

11. **Night City UI текущего клиента.** `web/mini_client/index.html:13-20,28`
    подключает shell, Night City UI и приложение с навигацией. UI — обычный
    deferred script, global API `window.NightCity` (`night-city-ui.js:1,1822`);
    room entry/list есть в `:988,1101-1232`, Mafia API base в `:1262`.
    `web/mini_client/app.js:714-845` открывает Night City для выбранной room.
    Это текущая Mafia UI-интеграция; отдельного клиента `night_case` этим не
    подтверждено.

## AI, сообщения и приватные проекции

- `modules/admin_ai.py:7-23,26-74` — ограниченный текстовый wrapper для
  Anthropic/OpenRouter/Puter. Он использует env flag и provider-specific
  KEY/MODEL; наружу отдаёт только `key_configured` и model, требует
  `confirmed_external`, ограничивает запрос/ответ, `max_tokens=1200`, timeout
  45 s и не повторяет запрос автоматически.
- `web/admin_ai.py:10-44`, подключение в `web/postgres_admin.py:520-521` —
  административный endpoint с одним in-process lock; `web/admin_auth.py:182-198`
  защищает admin routes session/CSRF. `web/static/js/postgres-admin.js:639-663`
  показывает явное согласие пользователя и историю только в памяти страницы.
  Это не player-facing narrator API.
- Старый `modules/openrouter_client.py:15-60,62-120` — отдельный клиент для
  fun fact: `OPENROUTER_API_KEY`, Qwen, timeout 20 s/connect 5 s,
  `max_tokens=200`, возвращает `None` при ошибке. Это отдельный механизм.
- В текущих storage/domain/application источниках не обнаружены narrator
  service, episode-draft store или persistent rendering queue. Дизайн-наблюдение,
  а не реализация: `docs/tasks/NIGHT_CITY_WEEKLY_DESIGN.md:634-642,761-770`
  описывает `night_renderings`, first-write-wins и authored fallback при первом
  чтении; там же указаны отдельные бюджеты/circuit breaker/выключатели и отдельные
  ключи, не `MQB_ADMIN_AI_ENABLED` (`:765-770`).
- Общая room discussion реализована только для текущего Mafia: `application/mafia.py:663-724`
  читает/пишет публичные GameEvent с `kind='discussion_message'`, проверяет
  участие/фазу и использует command receipt; routes в `web/mini_app.py:1429-1459`.
  Приватные игровые данные выдаются account-scoped `own_role` в
  `application/mafia.py:657-661`; GamePlayer также имеет `private_state`
  (`storage/models.py:399-429`). Отдельных private1/private2/private3 chat
  paths/models в обследованных server directories не найдено.

## Account merge, linking и moderation

- `storage/admin_actions.py:32-35` — общий advisory operation fence:
  shared для обычных/merge операций, exclusive для admin block/archive.
  Merge flow `application/account_merge_flow.py:64-71` и linking
  `application/account_linking.py:32-38` берут shared fence; room/game write
  примеры тоже его берут. Fence сериализует только пути, которые его вызывают;
  он сам не обходит state или roster.
- `application/account_merge.py:41-78` — `game_players.account_id` имеет
  `move_no_conflict`, но `game_commands.actor_account_id` и
  `game_events.actor_account_id` — `history`. `:441-456` переносит игрока на
  main UUID только если у main нет той же game-player PK; конфликтный ряд
  остается на secondary. `_merge_games` не переписывает `Game.state`.
  Поэтому mode, дублирующий roster UUID в JSON state, требует mode-specific
  учёта при merge, иначе SQL roster и runtime state могут разойтись.
- `application/account_merge.py:411-439` объединяет memberships: при уже
  существующем membership main строка secondary удаляется; статус main обычно
  остается. Ветка owner может повысить роль main и скопировать статус secondary.
  Access проверяется active membership (например
  `application/mafia.py:437+`, `application/rooms.py:106-132`).
- `application/account_linking.py:98-115` связывает Telegram User с текущим
  Account UUID, не заменяя UUID; конфликт другого account направляется в merge
  (`:119-125`). GamePlayer `user_id` поэтому остаётся nullable внешней
  идентичностью, а account UUID — roster principal.
- `storage/admin_actions.py:57-88` выбирает только current unfinished игры.
  Для chat scope отбор по `Game.chat_id`; для user scope — addressed chat IDs
  плюс специальный `mode='photo'` по state creator/user. Block прерывает только
  найденные игры (`:172-243`); archive требует предварительный block
  (`:245-262`). Standalone room games (`chat_id IS NULL`) не выбираются по
  GamePlayer Account UUID. Текущая moderation selection не покрывает account
  roster нового режима.

