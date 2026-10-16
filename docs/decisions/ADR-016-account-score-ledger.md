# ADR-016 — Журнал очков по аккаунтам

- **Статус:** `accepted`
- **Дата:** 2026-10-16
- **Связанные задачи:** T7 (docs/audits/2026-10-15/ARCHITECTURE_AUDIT.md), глобальный рейтинг по аккаунтам
- **Заменяет:** прямые записи в `users.global_score`

## Контекст

Очки жили в четырёх несвязанных местах: `users.global_score` (ключ — Telegram id), `chat_members.score`,
`alchemy_progress.points_total` и `classic_account_answers.points_delta` (комнаты, нигде не суммировались).
`recompute_user_totals` затирал очки Алхимии, слияние аккаунтов не переносило счёт, гость не мог попасть в рейтинг.

## Решение

* `score_events(account_id, source, key, amount, game_id, room_id, chat_id, created_at)`, `UNIQUE(account_id, source, key)` —
  единственный источник истины. `score_totals(account_id, source)` — агрегат, `users.global_score` — кэш общей части.
* Запись только через `RewardLedger.award` (`storage/score_ledger.py`): вставка события и обновление агрегата и кэша в одной
  транзакции; повтор того же ключа ничего не делает (возвращает `False`). Порядок блокировок: User → Account (FOR SHARE) →
  события → агрегат → кэш; Алхимия блокировки User/Account не берёт (её сериализует `AlchemyProgress`).
* Источники: `classic`, `photo`, `mafia` (резерв), `admin`, `legacy_import` — **общая часть** (рейтинг, `global_score`);
  `alchemy` — отдельный разрез. Ферма в журнал не пишется: её разрез читает `farm_states.xp` и `farm_ledger.xp_delta`.
* Ключи: `classic:<id>`/`photo:<id>` (чат), `room:<game>:<round>`, `craft:<command>`, `admin:set:<uuid>`,
  `admin:reset:<action>:<chat>:<user>`, `legacy:chat:<chat>`, `legacy:residual`, `legacy:alchemy`.
* Миграция 0034 переносит старые очки без потерь (`storage/score_backfill.py`, идемпотентно): события `legacy_import` по чатам
  (`chat_id` сохранён, срез чата строится из журнала), остаток `legacy:residual = global_score − Σ чатов − кредит Алхимии`,
  Алхимия — `legacy:alchemy`, очки комнат — по `classic_account_answers`. Все legacy-события датированы 2000-01-01, чтобы не
  попадать в окна «неделя/месяц». Telegram-профили без аккаунта получают технический аккаунт (флаги блокировки копируются,
  identity не создаётся); профили с чужой/отозванной identity остаются на ручной разбор.
* Слияние: события переезжают к основному аккаунту (`move_no_conflict`: раунд, на который ответили оба аккаунта, считается один
  раз; импортные `legacy:*` не конфликтуют — ключ вторичного получает суффикс `@<id>`); агрегаты пересобираются,
  `alchemy_progress.points_total` = разрез Алхимии. Очки обоих профилей **суммируются** (раньше «остаются от основного»).

## Рейтинг (этап 2)

* Одно ядро `application/rating.py: rank(scope, period, game, ...)`; читают его `/api/account/rating` (гость, пароль и Telegram через `resolve_principal`),
  `/top`, `/globaltop`, `/mystats` бота. Разрезы: `global`, `room`, `chat`, `friends`, `farm`, `alchemy`; период `all`/`month`/`week` —
  скользящие 30 и 7 суток по `created_at` событий (без сбросов и сезонов); игра `all`/`classic`/`photo`.
* В строке нет идентификаторов: `{rank, display_name, score, is_me}`; `me` — своё место даже у скрытого или безымянного гостя.
* В списке: не архивные, не слитые, без `accounts.rating_hidden`; в публичных разрезах (`global`, `farm`, `alchemy`) ещё нужен ник, отличный
  от заглушки «Гость». `bot_blocked` в рейтинге остаётся (решение владельца; в коде это административная блокировка).
* Друзья = игроки, с кем есть общая активная комната, плюс взаимные соседи фермы (`farm_neighbor_pairs`), плюс сам игрок.
* Ферма читается из `farm_states.xp` (всё время) и `farm_ledger.xp_delta` (периоды); приватные фермы в списке не показываются.
* UI: `web/mini_client/rating-ui.js`, флаг `rating_hidden` — `POST /api/account/rating-visibility`.

## Последствия

* `users.global_score` больше не включает очки Алхимии (раньше включал для Telegram-игроков) и включает очки комнат.
* Сверка: `python scripts/reconcile_scores.py [--repair]` (totals, кэш, чаты, Алхимия, непривязанные профили).
* Миграцию выполнять при остановленных боте и вебе: старый код писал `global_score` мимо журнала.
* Пересчёт `recompute_user_totals` больше не выводит очки из `chat_members`.
