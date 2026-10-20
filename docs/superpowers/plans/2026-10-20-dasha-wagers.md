# Dasha Wagers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Implement through the assigned inexpensive workers; do not delegate again.

**Goal:** Внедрить принятую игру Даши в деревню с серверными ставками и обкатать на песочнице, затем показать макет Олега.

**Architecture:** Существующий FarmService и его PG-транзакция владеют монетами и командами. Секреты раунда — отдельная таблица, безопасная проекция добавляется сервисом. UI — вложенная сцена фермы с SVG.

**Tech Stack:** Python, PostgreSQL/SQLAlchemy/Alembic, JS modules, CSS, SVG.

**Spec:** `docs/tasks/FARM_DASHA_GAME.md`.

## Global Constraints

- Одна рабочая копия F:/Projects/Quizywizzy, без PR и новых worktrees; чужие правки сохраняются.
- Реализация Luna, независимое содержательное ревью Sol. Без PNG-заплаток и новых зависимостей.
- Stake 10/20/50; payout 27/54/135; level ≥3; daily stakes ≤200 (Moscow); expiry 600 s.
- Один active/account, earned coins only, нет XP/бонусов; шанс 1/3 неизменный.
- Общие shell tokens/navigation; owner-only safe state; секреты вне payload/receipt.
- Docker существующий на D разрешён; новые temp/cache/логи только F. Production не трогать.

## Review Focus

- Hidden winning/default не появляются в owner/guest state, replay receipt или ошибках.
- Разные request_id и две вкладки не обходят active, квоту или единственность выплаты.
- Lazy expiry не вызывает economy.bill и не зависит от открытого клиента.
- Merge не теряет active ставку и не сбрасывает сумму ставок за день.
- Refresh/Back/reconnect не создают дополнительный раунд и не показывают морковку раньше выбора.

### Task 1: Backend and persistence (Luna)

Files: new `qw_farm/wagers.py`, relevant `qw_farm/persistence.py`, `service.py`,
`api.py` asset allowlist, new Alembic revision, `application/account_merge.py`,
new wager PG/unit tests and merge tests. No UI edits.

Interfaces: commands `wager_start {stake}` / `wager_choose {round_id,cup}`;
owner `response.farm.wager` exactly as spec, no secret fields in farm payload.

- [x] Add meaningful tests covering spec + Review Focus (real PostgreSQL).
- [x] Implement table, migration, state transitions, safe projection, receipts/ledger and merge policy.
- [x] Run related tests with migration/check in existing Docker; report exact result.
- [x] Independent Sol review of contracts, all diff and regressions; fix findings.

### Task 2: Accepted game UI (Luna)

Files: `qw_farm/static/app.js`, `style.css`, `index.html`, new
`dasha-game.js`, `dasha-game.css`, `dasha-scene.svg`, related JS tests.

Consumes: `S.me.wager`, `S.me.coins`, common `command(kind,data)` and refresh.
Produces: Dasha card action and nested game view with existing Back/nav.

- [x] Move accepted SVG art/layout into isolated module without demo economy, iframe or client RNG.
- [x] Bind start/choose to common idempotent commands; restore active and render only server results.
- [x] Verify no numbers/different cups; carrot hidden throughout shuffle/pick; responsive and keyboard flow.
- [x] Run related JS/UI rules tests; independent Sol review, fix findings.

### Task 3: Integration acceptance and sandbox

- [x] Run scoped PG/HTTP/JS, project checks and required complete dev gate; distinguish foreign pre-existing failures.
- [x] Review full diff independently; stage only own files, preserve original foreign hashes.
- [x] Deploy pinned code + migration only to sandbox with code/data backups and explicit rollback constraints.
- [x] Verify real browser start/choose/reload/back, console, UI gaps and public service health.
- [x] Record actual results in canonical spec; commit feature and acceptance without PR.

### Task 4: Next game preview

- [x] Build a separate vector mock of Oleg's musical sequence with inexpensive worker.
- [x] Show skill gameplay and animations; do not silently promise casino edge for learnable skill.
- [x] Inspect desktop/390/320 and present mock, distinguish from server integration.

## Rulings / ledger

2026-10-20: Илья явно поручил внедрение после принятия макета и просит дешёвые модели.
Повторное согласование реализации не требуется. Выбраны ограниченные стартовые лимиты из spec.
До плана Sol проверила транзакции, проекции, receipts и account merge; выбран отдельный SQL state.
Project Context Hub не регистрирует корень этого репозитория; другие project_id не используются.

Ruling: переполнение максимального баланса сохраняется SQL pending_payout и
автоматически погашается после расхода; UI показывает остаток, новые ставки/merge
до погашения запрещены. Причина: сохранить полный выигрыш, не зависнуть на expiry
и не менять все пути дохода фермы. Цена — редкий дополнительный state/UI edge.
Исторический farm_ledger при merge остаётся append-only; переносится только wager history.
Partial unique index задаётся для PostgreSQL и SQLite (иначе второй demo-раунд невозможен).
