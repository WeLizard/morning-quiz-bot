# QuizzyWizzy — компактное задание координатору Codex

**Основа:** `QuizzyWizzy_AUDIT_SPEC_2026-10-08.md` — основной строгий контракт (обязательно прочесть!).
**Baseline:** `main` / `aeeab2b358014934521d401d7a113a4769b41e46` по состоянию на 2026-10-08.
**Рабочая копия:** `C:\Users\Lizard\Projects\morning-quiz-bot`.
**Production:** не трогать; любые действия с боевыми данными/ботом/уведомлениями только после нового явного разрешения владельца.

## Общая инструкция

Ты — координатор реализации по строгой спецификации. Сначала изучи локальные `AGENTS.md`, `docs/engineering/DEVELOPMENT.md`, `docs/engineering/RELEASE_CRITERIA.md`, полный файл аудита и **фактический git status + HEAD**. Отметь изменения после `aeeab2b`, не переписывай чужие правки. Используй существующие domain/application/storage сервисы. Не начинай с общей переписи, не добавляй fake Telegram updates и новые MiniBridge. Веди один актуальный tracker задач. Каждая карточка ниже — отдельный исполнимый вертикальный пакет с тестами и демонстрируемым результатом; при необходимости дели на минимальные PR. Для каждого пакета привлекай агента по риску, сохраняй результаты независимого ревью.

Не заявляй, что тесты запущены, если у тебя нет вывода и окружения. Нет PG/Telegram/браузера — помечай `NOT VERIFIED` и продвигай только те части, которые реально проверить. Ничего не деплой и не пушь в production, не удаляй старые PG/JSON/фото данные.

## Очерёдность пакетов

### QW-00 — Новый baseline и повторение критических дефектов [P0]

**Цель:** актуализировать аудит относительно живой dev-копии, составить матрицу `AUD-001…AUD-028` со статусами и доказательствами, воспроизвести минимум AUD-001, AUD-002, AUD-007 и AUD-008 тестами/изолированными сценариями.
**Файлы:** документы, `storage/alchemy.py`, `storage/games.py`, `domain/mafia.py`, `docker-compose.yml`, tests.
**Готово:** отчёт `git HEAD/diff`, версия PG схемы, результаты реально запущенных тестов, ни один продовый файл не изменён. Не исправляй функциональность в этом пакете, кроме тестовых fixtures.

### QW-01 — Убрать рейтинг из недоверенного Alchemy sync [P0]

**Цель:** сервер более не начисляет `2/3/5` за произвольно присланные ID, появляется подтверждённый server-side craft, verified/unverified ledger и безопасная migration existing progress. Не уничтожать коллекции игроков, не списывать исторические очки без отдельного решения.
**Файлы:** `storage/alchemy.py`, `storage/models.py`, новая Alembic миграция, `web/mini_app.py`, `minigames/alchemia-1.0/{game.js,sync.js}`, related tests.
**Тесты:** `TA-01…TA-10`; особенно «все 431 ID» → **ноль новых подтверждённых очков**; 10 parallel craft commands → один award. Внеси ADR к offline/import политике.
**Готово:** old clients безопасно деградируют, доступны verified events и прогресс, без token exposure/cheat.

### QW-02 — Security/dependency/Compose исправления [P0]

**Цель:** синхронизировать production/default конфигурацию с PostgreSQL-only, обновить уязвимый `python-multipart`, lockfiles, Docker runtime, безопасный guest/token handoff. Не отключай защиту Origin, CSRF и Telegram HMAC.
**Файлы:** `docker-compose.yml`, `Dockerfile*`, `env.example`, `requirements*`, `setup.py`, `web/mini_client/app.js`, `minigames/alchemia-1.0/sync.js`, `web/mini_app.py`, security tests.
**Тесты:** clean PG bootstrap, all auth/CSP/CSRF flows, SBOM/vuln, install CLI smoke, migration upgrade, retry Alchemy sync; нет bearer в URL/hash/localStorage.
**Готово:** воспроизводимый безопасный deployment artifact, explicit failing config, runtime matches prod/dev.

### QW-03 — Командная идемпотентность / конкурентность [P1]

**Цель:** `GameRepository.reserve_command` сравнивает `game_id`; actor-specific actions Mafia не конфликтуют из-за не относящейся к ним общей ревизии.
**Файлы:** `storage/games.py`, `domain/mafia.py`, `application/mafia.py`, `web/mini_app.py`, `handlers/mafia_handlers.py`, model/migration если нужно.
**Тесты:** `TM-02`, `TM-03`, `E2E-07/08/09`, stale phase returns 409, duplicate receipt no award.
**Готово:** две независимые команды в одну фазу обе сохраняются, одинаковый `command_id` для другого game отклонён.

### QW-04 — Независимый game worker [P1]

**Цель:** вынести сроки Classic/Photo/Mafia и транзакционный outbox из `handlers/mafia_handlers.py`/PTB `job_queue` в самостоятельный процесс. Telegram оставить только доставщиком своих уведомлений.
**Файлы:** `handlers/mafia_handlers.py`, `application/*`, `storage/games.py`, `storage/notifications.py`, Compose/dev scripts, worker entrypoint, metrics/tests.
**Тесты:** `TM-04/05/11`, `E2E-06/18`, 2 workers, restart, 429 vs unknown outcome.
**Готово:** Telegram выключен, browser-only клиенты видят корректные завершения по дедлайну.

### QW-05 — Account/Identity/Room и паритет каналов [P1]

**Цель:** Account и Room существуют без Telegram ID. Безопасно связать identity без silent merge; мигрировать `games.chat_id`, игроков, history с сохранением совместимости; guest recovery.
**Файлы:** `storage/models.py`, Alembic, `storage/guest_accounts.py`, новые application services/adapters, `web/mini_app.py`, related UI/tests.
**Тесты:** `E2E-02/03/04/05/14/20`; без Telegram можно создать комнату, гость не получает чужой профиль.
**Готово:** отдельные аккаунты и комнаты, единственная игра через web/TG, миграция старых партий доказана.

### QW-06 — Отказ от MiniBridge и Classic/Photo regression [P1]

**Цель:** из UI убрать необходимое использование synthetic PTB update, заменив прямыми командами общего ядра; сохранить меню/настройки, групповые права, удаление уведомлений, scoring.
**Файлы:** `modules/mini_bridge_worker.py`, `modules/mini_offline_runtime.py`, `storage/mini_bridge.py`, `web/mini_client/play-ui.js`, `web/mini_app.py`, `application/classic.py`, `application/photo.py`, tests.
**Тесты:** `E2E-15/16`, Telegram ↔ Mini App resume, фото-группа **по утверждённой** policy, duplicate scoring.

### QW-07 — Банк вопросов, UI каталог и бренд [P2]

**Цель:** исправить 5 malformed записей, ревью 14 дублей (включая «Опять двойка»), audit PG-банка; сделать единый `GameModeCatalog` с пятью IDs и согласованным status/capabilities; сохранить две зелёные + две коричневые карточки.
**Файлы:** `data/questions/*.json`, `storage/question_bank.py`, import validation/tests, `web/mini_client/{app.js,index.html,styles.css}`, UI tests.
**Готово:** QA отчёт, редакторская история, Farm `coming_soon` без обманного «Играть», 320/390/430/mobile a11y.

### QW-08 — Async Mafia как завершённая игра [P1]

**Цель:** configurable real asynchronous phases, quiet hours, AFK, host transfer, pause/resume, in-app discussion, endgame/rollback/reconnect.
**Файлы:** `domain/mafia.py`, `application/mafia.py`, rooms/worker, UI, Telegram adapter, game tests.
**Тесты:** `TM-01…TM-12` и полное прохождение двумя группами без общего одновременного присутствия. Не менять роли без отдельного ADR.

### QW-09 — «Весёлый фермер»: работающий MVP [P2]

**Цель:** одна Account-owned ферма: 3 культуры, plots/plant/grow offline/harvest/inventory/orders/currency/expand; server-authoritative balance/commands; одна игра из web/TG Mini App, без фальшивой экономики.
**Старт:** согласовать `FARM-DEC-01` (баланс и переработка) и `DEC-01` (обязательность к первому релизу).
**Файлы:** новые `domain/farm.py`, `application/farm.py`, `storage/*`, Alembic, adapters, UI, economy fixtures.
**Тесты:** `TF-01…TF-12` + ресурсы после 1000 сценарных циклов, конкурентные команды.
**Готово:** пользователь закрыл браузер, вернулся за урожаем, выполнил заказ и расширил ферму; вторая копия не дублирует награды.

### QW-10 — Release candidate и эксплуатация [P1]

**Цель:** CI, backup/restore, dependency security, e2e five-game matrix, observability, staging migration rehearsal, story of rollback. **Production release — отдельная задача только с разрешением.**
**Тесты:** `E2E-01…22` по принятому scope, свежий pg_dump/media+restore, GitHub checks, skipped reasons, browser/WebView acceptance.
**Готово:** полный release-evidence package с QA/review, а не «у меня локально запустилось».

## Трассировка всех 28 находок к пакетам

| Пакет | Находки аудита | Контроль |
|---|---|---|
| QW-00 | AUD-001…AUD-028 | Rebaseline, статус каждой находки, доказательство/ADR |
| QW-01 | AUD-001, AUD-015 | Доверенные открытия и рейтинговые награды |
| QW-02 | AUD-002, AUD-003, AUD-004, AUD-017, AUD-022 | Boot, dependencies, token/session/proxy security |
| QW-03 | AUD-007, AUD-008 | Корректная idempotency и независимые действия |
| QW-04 | AUD-006, AUD-014 | Deadline worker и outbox reconciliation |
| QW-05 | AUD-005, AUD-009, AUD-010, AUD-012, AUD-028 | Account/Room/identity/recovery/privacy lifecycle |
| QW-06 | AUD-011, AUD-019, AUD-024 | Удаление bridge и Classic/Photo/legacy parity |
| QW-07 | AUD-018, AUD-020, AUD-026, AUD-027 | Вопросы, меню из пяти режимов, ассеты и брендинг |
| QW-08 | AUD-012, AUD-013 | Реальная асинхронная Мафия |
| QW-09 | AUD-021 | Весёлый фермер как проверенная игра |
| QW-10 | AUD-016, AUD-023, AUD-025 | Release/CI/prod drift; AI отдельный необязательный будущий этап |

**Правило:** AUD-025 (AI-ведущий) не смешивать с production релизом пяти режимов. Он остаётся открытым/отложенным с явным `deferred by scope` и не превращается в обязательный QW-10 deliverable.

## Единый формат отчёта

```text
TASK: QW-XX
REQUIREMENTS: AUD-..., ALC-..., MAF-..., TF-..., E2E-...
BASELINE: commit, branch, original worktree diff
CHANGES: files, migration IDs, backwards compatibility
REPRO: original failing test / before-after behavior
TESTS: actual commands and passed/failed/skipped, runtime & PostgreSQL schema
UI/TELEGRAM: which clients were tested, not tested
SECURITY & DATA: auth, concurrency, private projections, audit logs, backup
INDEPENDENT REVIEW: reviewer, findings, status
RISKS / ADR / QUESTIONS: only decisions requiring owner
ROLLBACK: tested procedure or explicitly not verified
NEXT: next independent slice
```

**Правило выпуска:** no P0/P1, real PG coverage, никакого fake `passed`. Путь к Production — **только через явный GO** владельца после просмотра релизного отчёта.
