# Night City runtime contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Подготовить проверяемые контракты ведущего и действий, затем один исполнимый путь «Усадьбы» к первым тестам в rehearsal.

**Architecture:** Сервер принимает правила и последствия, AI получает заранее разрешённую адресную проекцию. Чистые решения — данные для будущей транзакции, а не подмена PostgreSQL. Валидация достижимости использует тот же доменный переход, что живая игра.

**Tech Stack:** Python 3.13, dataclasses/stdlib, JSON Schema 2020-12; PostgreSQL/application и существующий web shell подключаются последующими срезами.

**Spec:** [NIGHT_CITY_RUNTIME_CONTRACT](../NIGHT_CITY_RUNTIME_CONTRACT.md), согласован 2026-11-15; [MQB-010](../MQB-010-night-city-weekly-stages.md), [WEEKLY_DESIGN](../NIGHT_CITY_WEEKLY_DESIGN.md), поздние решения.

## Global Constraints

- Окна 09–19 и 19–09, тихие часы 23–08, 3 хода без накопления; раннее закрытие не раньше 30 минут.
- `Account`/`Room`/`Game` — ядро; Telegram — адаптер. Домен не импортирует БД/HTTP/Telegram.
- Чужие изменения сохраняются. Production не разрешён. JSON не подменяет общее изменяемое PG-состояние.
- Не выдавать чистую функцию за сохранение, очередь, защиту гонок или готовую игру.
- Импровизация не меняет прошлое дела; типизированное предложение не равно применённому событию.

## Review Focus

- Чужой адресат или скрытая canary-строка не попадают в provider payload: тест whitelist-проекции.
- Устаревшая цена/окно/ресурс требуют нового предложения: тест подтверждения после изменения.
- Повтор оговорки не перебрасывает шанс и не списывает бюджет снова: тест codec+reuse.
- AI-кандидат сюжета не становится опубликованным автоматически: тест статуса draft и неизвестных полей.
- Структурно корректная проза не объявляется семантически доказанной: тест отсутствия такого флага/эффекта.

## Task 1 — Read-only формат и структурный валидатор

**Files:** `domain/night_case_format.py`, `domain/night_case_validator.py`, `scripts/validate_night_case.py`, `tests/test_night_case_format.py`, `tests/test_night_case_validator.py`, requirements/lock.

- [x] Строгий bounded UTF-8 JSON; duplicate/nonfinite/unknown schema/external refs fail closed.
- [x] SHA-256 канонического JSON, схема и типизированные ссылки/плейсхолдеры.
- [x] Поля-диапазоны проверяются отдельно от неупорядоченных наборов окон.
- [x] `not_checked` для полных V/U без реализации, `publishable=false`, CLI exit 1.
- [x] 32 unittest, отдельное окружение с pinned dependencies; независимое ревью.

## Task 2 — Чистые контракты ведущего, подтверждения и оговорок

**Create:** `domain/night_case_narrative.py`, `tests/test_night_case_narrative.py`.

**Interfaces:** frozen `NarrationView`, `NarrativeJob`, `LegalAction`, `ActionContext`, `ActionProposal`, `SlipRule`, `SlipScope`, `SlipDecision`, `EpisodeCandidateDraft`.

- Граница доверия: view/legal actions/rule/budget предоставляет доверенный caller;
  модуль не умеет распознать секрет внутри уже разрешённой ему строки и не заменяет
  реальную авторизацию. Snapshot глубоко неизменяем: изменение исходного dict/list
  после создания предложения не меняет команду, цену или разрешённые ссылки.
- `NarrativeJob` хранит внутренние audience/knowledge_revision/window/case_hash/
  ruleset_version; payload провайдеру строится отдельно. Ответ привязан к job/kind.
  Единый UTC-контракт; `now == expires_at` уже истечение срока.
- [x] Написать тесты canary/адресата/unknown fields, stale/changed-price/changed-actor, slip replay/budget, episode draft; увидеть красный прогон.
- [x] `build_narrative_job(view, *, job_id, cause_id, kind, expires_at, fallback) -> NarrativeJob`: вход — только уже отобранная проекция, не полное дело/state. Provider payload содержит только перечисленные поля проекции/задания и opaque request_token, не account/game IDs.
- [x] `validate_narrative_result(job, result, *, now) -> RenderingDecision`: точный JSON-контракт, bounded text, допустимые ссылки и catalog IDs; fallback при ошибке/expiry. Свободный текст не получает признака semantic proof. Кандидат эпизода остаётся draft без apply.
- [x] `propose_action(selection_id, legal_actions, context, *, proposal_id, expires_at) -> ActionProposal`: AI выбирает существующий ID; неизменяемый снимок команды/цены/окна/ресурса. Неизвестный ID/несколько совпадений — отказ без расхода.
- [x] `confirm_action(proposal, context, legal_actions, *, now) -> AuthorizedCommand`: actor/game/window/resource/цена/цель/параметры должны совпасть; стабильный command_id для повтора; никакого исполнения внутри функции. Истечение/подмена цели/params покрыты негативными тестами.
- [x] `decide_slip(rule, scope, *, previous, remaining_budget, draw) -> SlipResolution(decision,reused,budget_delta)`: draw целое 0..9999, вероятность в basis points; прежний результат переиспользуется без нового расхода, ключ включает game/npc/topic/window/rule version. Чужой scope отклоняется; 0 никогда не раскрывает, 10000 раскрывает при допустимых условиях и бюджете (`draw < probability_bp`). Codec round-trip содержит все поля решения, включая probability snapshot; transactional reserve/persist остаётся application.
- `EpisodeCandidateDraft` содержит provenance задания, но не его закрытый контекст.
  Формальная допустимость каталога не означает исполнения/публикации; реальное
  сохранение, очистка содержимого и публикация остаются последующим срезом.
- [x] Проверить unittest без pytest conftest/БД; независимое ревью. Не подключать провайдер/сервис на этом шаге.

Свидетельства Task 2: 39 `test_night_case*.py` прошли локально и в отдельном uv
окружении с lock-версиями зависимостей. Независимое ревью нашло и закрыло три
дефекта: изменение вероятности при replay, повреждённые slip decisions и слишком
короткий лимит авторских фактов. Исправления повторно приняты отдельным ревьюером.
Проверка семантики свободной прозы, авторизация на настоящем состоянии и PG ещё
не заявляются.

## Статусы срезов MQB-010

3. **Исполнимый формат v2 и переход — принят.** Отдельная версия, строгие узлы диалогов с ID,
   conditions/effects из конечного каталога, разделение публичной доступности действия
   и скрытого исхода. `step(case,rules,state,command,now_utc)` возвращает state/events/receipt/due;
   `project` и `available_actions` используют те же проверки. v1 не запускается как игра.
   Сначала мини-дело и тесты повтора/фенса/времени/проекций. Детальный контракт и план прошли независимое ревью перед реализацией.
4. **Симулятор — принят; «Усадьба» и модули — открыты.** V4/V11 через `step`, свидетельства пути для вариантов
   и составов; отсутствие бюджета = not_checked. Затем три версии manor как игровые
   данные, опровержения, ранние/обычные финалы, поддержанные модули. Владелец проекта подтвердил
   тайный проход библиотека → погреб: доступ открывается по двум независимым зацепкам.
5. **PG/application/worker — открыто.** Снимки контента, запечатанная правда, права,
   идемпотентность, receipts/outbox, сохранение решений и истории. Миграции, гонки,
   рестарт, отдельные проекции и восстановление проверяются настоящей test PostgreSQL.
6. **Клиент и ведущий — открыто.** API/экраны/каналы людей; authored fallback, затем провайдер
   по разрешённой конфигурации. Story candidates → обезличенные черновики библиотеки →
   публикация владельцем → совместимый отбор для новых партий.
7. **Первые игровые тесты — открыто.** Полный dev gate, UI/визуальная матрица; выкладка готового
   среза в rehearsal с сохранением данных, ускоренный цикл, затем живая неделя 4–5 человек.

Task 3 (чистый v2 core) и simulation часть Task 4 приняты по целевым независимым проверкам. Повторный pinned isolated suite прошёл: 119 тестов за 40.105 s (exit 0). «Усадьба»/modules, PG/application/worker, UI/provider и первые игровые тесты остаются открытыми. Чистое ядро не является подключённым игровым ведущим.
