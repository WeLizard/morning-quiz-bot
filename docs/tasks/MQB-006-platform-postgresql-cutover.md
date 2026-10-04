# MQB-006 — PostgreSQL-only игровая платформа

- **Статус:** `in_progress`
- **Приоритет:** critical
- **Создана:** 2026-09-04
- **Обновлена:** 2026-09-04
- **Связанные ADR:** ADR-001, ADR-008, ADR-010, ADR-011, ADR-012, ADR-013, ADR-014
- **Среда:** только локальная dev-копия; production без отдельного разрешения не изменяется

## Цель

Эволюционно превратить Morning Quiz в серверную игровую платформу: PostgreSQL
является единственным источником изменяемого состояния, domain/application слой
владеет правилами, а Telegram Bot и Mini App являются равноправными адаптерами.
Async Mafia становится первым дополнительным режимом общего расширяемого game
substrate, а не отдельной подсистемой.

## Проверенное состояние на старте

### Что сохраняем

- SQLAlchemy-модели, Alembic 0001–0007 и транзакционные repositories.
- `MemberService`, ledger ответов и чистые scoring policies.
- Classic current/answer projection и Photo current/image projection.
- Чистую Mafia state machine и `MafiaApplicationService`, уже используемый двумя
  адаптерами.
- Telegram initData/session security и whitelisted Mini App projections.
- Визуальный shell Mini App, Telegram theme/safe-area integration и игровые UI.
- Идемпотентный JSON importer как основу, усилив preflight и сверку результата.

### Главный технический долг

- PTB conversation state раньше писал `ptb_persistence.postgres-ui.pickle`;
  теперь он явно ephemeral, но этот контракт ещё предстоит проверить полным
  runtime-аудитом.
- Importer теперь классифицирует JSON и охватывает operational-источники, однако
  полная content fingerprint-сверка ещё не завершена.
- Legacy-классы ещё сохраняют JSON-ветки для импорта/старых тестов,
  но основной bot entrypoint теперь fail-closed отклоняет JSON runtime.
- Редактируемый question bank перенесён в PostgreSQL; исходные JSON теперь только
  одноразовый migration/dev seed. Media catalog ещё не является полностью
  авторитетным относительно файлов.
- Classic start/advance/finish и Photo start/answer/hints/advance живут в PTB
  handlers/managers. Mini App вызывает их через искусственные `telegram.Update`.
- Общий substrate и миграция Mafia добавлены в 0008; deadline-переходы уже
  публикуются через транзакционный outbox, перенос остальных режимов не завершён.
- Mini App не имеет полноценной истории, развитых достижений и устойчивого
  session/reconnect; частый polling способен упереться в собственный rate limit.

## Workstreams и зависимости

1. **Воспроизводимый dev-контур** — Docker image, один Compose, один PostgreSQL,
   admin, Mini App, Telegram profile, test profile, migrations, seed, healthchecks.
2. **Migration safety и cutover gate** — строгий manifest/digest, schema validation,
   normalized fingerprints, maintenance source, запрет operational JSON writes.
3. **PostgreSQL runtime completeness** — убрать pickle, завершить авторитетный
   media catalog и устранить stale settings cache. Question bank уже перенесён.
4. **Общий game substrate** — games, players, commands, events, deadlines, outbox;
   сначала мигрировать Mafia без изменения её public application API.
5. **Classic vertical slice** — prepare/start/current/answer/advance/finish/restore
   как application commands; оба адаптера; затем удалить classic bridge.
6. **Photo vertical slice** — start/current/image/hint/answer/advance/finish/restore;
   оба адаптера; затем удалить photo bridge.
7. **Полноценный Mini App** — active games по чатам, история, статистика,
   achievement catalog/progress, reconnect/session renewal, versioned updates.
8. **Cutover audit** — миграционный rehearsal на свежем snapshot, запрет JSON
   backend, сквозная Bot ↔ Mini App ↔ restart проверка. Production остаётся вне
   задачи до отдельного решения.

Workstreams 2–3 предшествуют финальному cutover. Game substrate предшествует
переносу полного lifecycle. UI может развиваться параллельно только поверх уже
определённых projections; новая игровая логика в bridge не добавляется.

## Этапы и критерии готовности

### Этап 0 — контейнерный dev

- [x] Один Compose поднимает PostgreSQL, миграции, seed, admin и Mini App.
- [x] Telegram запускается явным profile и ограничен тестовым ботом/личкой.
- [x] Tests используют отдельную `morning_quiz_test` в том же PostgreSQL.
- [x] Healthchecks доступны с хоста, volume переживает restart.
- [x] Dev backup работает внутри контейнера без Docker socket.
- [x] Полная регрессия и dump/restore проходят в dev image: 433 passed.

### Этап 1 — доказуемая миграция

- [x] Каждый известный JSON source классифицирован; operational входит в digest.
- [x] Неверный тип/дата/список останавливает preflight с точным JSON path.
- [x] `config/maintenance_status.json` мигрируется в правильный PG state.
- [x] Source и database fingerprints совпадают; mismatch откатывает импорт.
- [x] CLI завершает работу успешно только после доказанной сверки.

### Этап 2 — PostgreSQL-only runtime

- [ ] В PG-режиме нет mutable JSON/pickle reads или writes.
- [x] PTB UI/conversation state явно ephemeral и не создаёт второй файл state.
- [x] Редактируемый банк вопросов хранится в PostgreSQL.
- [ ] Media catalog авторитетен; файлы immutable/content-addressed.
  Runtime-autodiscovery уже запрещён, новые upload адресуются SHA-256;
  для legacy media ещё нужен отдельный rehearsal/backfill.
- [x] Startup fail-closed при JSON backend основного бота, неверной schema revision или URL.
- [x] Изменение settings/category немедленно влияет на следующий Telegram run.

### Этап 3 — общий game substrate и Mafia

- [x] Есть versioned models/repositories games, players, commands, events,
  deadlines и notification outbox.
- [x] Mafia legacy payload атомарно переносится из `system_states` без второго source.
- [x] Два worker не исполняют один deadline дважды.
- [x] Deadline-переход и публичное Telegram-уведомление связаны через durable
  outbox; 429 откладывается, неизвестный исход не дублируется вслепую.
- [x] Public projection не раскрывает роли и приватные действия.
- [x] Заблокированный или покинувший чат игрок не может действовать.
- [x] Завершённые партии и реванши сохраняют самостоятельную историю.

### Этап 4 — равноправные Classic и Photo

- [x] Classic: начать в Telegram → продолжить/ответить/закончить в Mini App и наоборот.
- [x] Classic: один command/answer ID из двух клиентов изменяет состояние ровно один раз.
- [x] Classic: restart восстанавливает текущий вопрос, phase и deadline.
- [x] Classic: ни один adapter не рассчитывает score или переход самостоятельно.
- [x] Photo переведён на тот же прямой application lifecycle в обоих клиентах.
- [ ] В classic/photo runtime отсутствуют `Update.de_json`, `process_update` и
  MiniBridge; bridge после переноса удалён.

### Этап 5 — продуктовый Mini App и финальный аудит

- [ ] Главная, current games, classic, photo 1:1, Mafia, история, статистика,
  рейтинг, достижения, профиль и настройки используют реальные projections.
- [ ] Есть loading/error/empty/reconnect/session renewal и корректные deep links.
- [ ] Десятиминутная сессия не достигает rate limit собственным polling.
- [ ] Сквозная матрица Telegram Desktop/Android/iOS пройдена на тестовом боте.
- [ ] Runtime contract с запрещёнными operational file reads/writes проходит.
- [ ] Production не изменён; готов отдельный проверяемый cutover/runbook.

## Риски и откат

- Каждый этап оформляется отдельной миграцией и сохраняет старые источники до
  подтверждённой сверки; runtime читает только новый источник после gate.
- Нельзя поддерживать dual-write как длительный режим: он создаёт два источника
  истины. Допустим краткий shadow compare без влияния на результат.
- Секретные Mafia projections тестируются отдельно от публичных.
- `docker compose down -v`, удаление production JSON и server deployment запрещены
  без отдельного подтверждения.

## Журнал

- 2026-09-04 — проведён аудит storage, application/domain, Mini App и Mafia;
  зафиксированы переиспользуемые части и реальные пробелы.
- 2026-09-04 — этап 0 реализован и проверен локально: один dev image/Compose,
  Telegram/test profiles, healthchecks и verified backup/dump-restore. После
  миграций 0008/0009 общий gate расширен до 428 тестов.
- 2026-09-04 — importer получил строгую preflight-проверку, классифицированный
  manifest, operational digest, транзакционную сверку counts и корректный
  maintenance source; статический streak catalog больше не пишется как мёртвый
  `system_state`. PTB UI-state в PostgreSQL-режиме переведён на ephemeral memory.
- 2026-09-04 — Alembic 0008 добавил общий game substrate; Mafia переведена на
  `games/game_players/game_events/game_deadlines`, получила общий command receipt,
  защиту актуального membership и сохранение отдельных партий при реванше.
- 2026-09-04 — Alembic 0009 перенёс категории и содержимое банка вопросов в
  PostgreSQL. Bot и admin используют один транзакционный repository с optimistic
  version и историей ревизий; JSON оставлен только как вход миграции и seed пустой
  dev/test-БД. Миграция legacy Mafia отдельно отрепетирована на схеме 0007.
- 2026-09-04 — полный контейнерный gate после 0008/0009: 433 теста, Alembic
  upgrade/check, dump/restore и JavaScript syntax checks без изменения dev-БД.
- 2026-09-04 — migration gate дополнен нормализованными SHA-256 fingerprints
  по пользователям, чатам, участникам, достижениям, расписаниям, quiz state,
  фото, вопросам, system state и cleanup queue. Любой mismatch откатывает импорт.
- 2026-09-04 — deadline worker Mafia переведён на durable PostgreSQL outbox:
  переход и intent атомарны, конкурентный claim защищён `SKIP LOCKED`, а политика
  `RetryAfter`/`uncertain` сохраняет защиту Telegram от слепых дублей.
- 2026-09-04 — runtime entrypoints проверяют единственный Alembic head
  до приёма запросов; bot отказывается стартовать в JSON-режиме.
  Фальшивая зависимость Telegram runner от `.local/preview/questions` удалена.
- 2026-09-04 — PG-каталог стал авторитетом допуска photo media в игру;
  новые dev/admin uploads публикуют immutable SHA-256-объекты.
- 2026-09-04 — единая dev-сборка поднята: admin и Mini App healthy;
  HTTP smoke прошёл login, analytics, offline runtime, classic answer,
  shared settings и photo image. В dev-БД 63 категории/6706 вопросов
  и 198 content-addressed photo assets. Backup `176a633c61264070a6792379acc452bf`
  сверил 21 таблицу и 200 файлов без изменения dev-БД.
- 2026-09-04 — Classic vertical slice перенесён в `games`: чистая state machine,
  общий application service, внутренние round ID, адресные deadlines, прямые
  Mini App start/sync/answer/stop и Telegram delivery через outbox. Alembic 0010
  мигрирует legacy Classic snapshots, ответы и poll bindings, после чего
  `quiz_sessions` больше не является Classic runtime source.
- 2026-09-04 — обновлённый dev-стек пересобран без сброса `morning_quiz_dev`.
  Alembic head `20260904_0010`, в БД нет Classic-строк в `quiz_sessions`;
  контейнерный gate: 442 passed. Admin/Mini HTTP smoke и автономный Mini Classic
  start/answer/stop прошли, Telegram-запросов в автономном сценарии: 0.
- 2026-09-04 — Photo vertical slice перенесён в `games`: чистая state machine,
  серверные hints/timeouts, общий application service, прямые Mini App
  start/current/image/answer/stop и Telegram effects через outbox. Alembic 0011
  переносит активные legacy Photo snapshots и удаляет их из `quiz_sessions`.
  Контейнерный gate после среза: 444 passed.
