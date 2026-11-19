# Night City witness validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Получить воспроизводимые свидетельства прохождения core mini-case во всех поддержанных вариантах и составах перед работой над «Усадьбой».

**Architecture:** Симулятор вызывает только общий `_initialize`/`step`; не применяет эффекты сам и не редактирует KernelState. Валидатор повторяет сохранённые команды через тот же переход. Бюджет без найденного пути означает inconclusive, а не доказанную невозможность.

**Tech Stack:** Python stdlib, уже проверенные v2 compiler/state/time/engine; unittest без БД/модели/реальных ожиданий.

**Spec:** [EXECUTABLE_FORMAT_V2](EXECUTABLE_FORMAT_V2.md) §10 и [core plan](2026-11-15-core-plan.md), Task D.

## Global Constraints

- Production не импортирует tests; tests импортируют production API. `_initialize` — общий внутренний путь реального validator, не debug HTTP API.
- Case/rules/hash/build/seed/roster закреплены; witness содержит синтетических участников и приватную правду, не является публичным DTO.
- Никакой иной логики расхода AP, знаний, слушания, времени или финала в симуляторе.
- `found` требует успешного replay и solved; отсутствие результата в ограниченной политике не доказывает unsolvable.
- V4/V11 не заменяют остальные V/U, человеческую проверку сюжета, PG или живую приёмку.

## Review Focus

- Подмена case/rules/variant/commands/receipt/state_hash делает replay неуспешным.
- Запрещённое/недоступное действие не обходится прямой записью knowledge/AP/flags.
- Исчерпание бюджета и неудачная эвристика явно возвращают inconclusive/not_checked.
- NPC вместо PC, приватные находки и pin не подменяются глобальным объединением inventories.
- Passive и absent policies различаются: первая доходит до финального слушания, вторая freeze→forgotten.

## Task D — Witness, ограниченный поиск и smoke policies

**Ownership:** `domain/night_case_simulation.py`, `tests/test_night_case_simulation.py`, `scripts/validate_night_case_v2.py`.

**Consumes:** `CompiledCase`, `RulesSnapshot`, `_initialize(...,composition_id,selected_variant_id)`, `step`, `project`, `available_actions`, `encode_state`. Roster shape `{players:[{account_id,display_name}],npc_name_pool:[string]}`. Transition state/events/receipt/due — defensive snapshots.

**Produces:** frozen/defensive `SearchBudget`, `SearchResult`, `Witness`; `find_witness(case,rules,composition_id,variant_id,*,seed,budget)->SearchResult`; `replay_witness(case,rules,witness)->ReplayResult`; `validate_matrix(case,rules,*,seed,budget)->MatrixReport`; `run_smoke_policy(...,policy,seed,budget)->PolicyResult`.

Уточнения независимого архитектурного review перед реализацией:

- Генератор конечный: concrete choices из меню, формы через `quote_action`.
  Нет произвольных free claims; seen один раз за окно, pin не повторяется.
  При `min_key>5` citations распределяются между иском и разными голосами, а не
  одинаковыми первыми пятью у всех.
- Assumptions отчёта: `oracle-guided cooperative reachability`; все люди,
  включая Тень, сотрудничают. Planner знает culprit/key_proofs, но только kernel
  решает доступность и последствия. Это не доказательство догадки реальных игроков.
- Witness имеет `trace_hash` по header и всем steps, включая timestamps, без elapsed.
  Replay проверяет неубывание now от start_at и terminal/solved. Хеш не является подписью
  против автора, который пересчитал всю запись; само прохождение всё равно проверяется.
- Порядок поиска детерминирован, остановка wall-budget зависит от машины.
  Стабильность trace проверяется при достаточном времени и одинаковом step/state budget.
  Виртуальное продвижение использует `max(current_now,due.at)`.
- Перебираются все пары из `variant.composition_ids`, не hardcoded восемь. Бюджет
  применяется к каждой паре/политике; scope_passed требует всех ячеек. Kernel exception —
  явная ошибка, не маскируется как inconclusive. Exhausted не реализуется без полного поиска.
- Для полного детерминизма start_at передаётся явно либо имеет фиксированный UTC default
  `2000-01-03T08:00:00Z`; `datetime.now()` не выбирает игровое начало. Optional start_at
  добавляется ко всем generator API и закрепляется в witness, включая DST-сценарии.

- [ ] RED: воспроизводимый solved witness для двух вариантов × составов 4/5/8/12 из учебной fixture; одинаковые входы дают одинаковые trace hashes. Ни одна служебная операция не изменяет переданный case/rules.
- [ ] Реализовать Witness schema `night-city-witness/1`: case/rules/compiler/engine IDs и хеши, состав/вариант, seed, синтетический roster/game_id, start_at, steps `{actor,command,now_utc,expected_receipt,state_hash}`, final_code. Все изменения — только через engine. Serializers/import отклоняют unknown/duplicate fields, нечисловые лимиты и несовместимые версии.
- [ ] RED: изменение команд/времени/hash/variant/receipt/state_hash отвергается replay; неизменённый witness снова даёт solved и тот же hash.
- [ ] Реализовать ограниченную кооперативную политику: поиск разрешённых путей к ключевым observations через общие меню и predicates; реальные move/act/talk/pin, присутствие, голосование и system.tick. Игроки публикуют свои находки явно. Проверка доступности — исключительно kernel. Допустимы guided search и bounded exploration, но assumptions записываются в отчёт; не обещать оптимальную стратегию против Тени.
- [ ] Бюджет по числу команд/состояний и elapsed: defaults 2000 commands, 5000 states, 10 секунд. Игровое время виртуальное UTC; resource timer не заменяет его. У исчерпания явная причина. Если исчерпывающий поиск не реализован, status exhausted не выдаётся.
- [ ] RED: budget1 и недостижимая для данной политики ключевая улика → inconclusive/not_checked, не found и не fabricated failure proof.
- [ ] Реализовать passive_presence (посещают окна без расследования → unresolved), absent (не посещают → freeze6→forgotten) и seeded random smoke с ограничением шагов. Не spam free seen/pin/vote бесконечно; сохранять реальные receipts.
- [x] RED/GREEN: witness всей матрицы + smoke до terminal без exceptions, повтор seed стабилен; отсутствие поддержанного модуля блокирует компиляцию/симуляцию.
- [ ] CLI `validate_night_case_v2.py CASE --scope structure|witness|smoke`: JSON с явными scope/scope_passed, неполными checks и `publishable=false`. Exit0 означает только успех выбранного scope; не разрешение публикации. Не изменять v1 CLI и ничего не записывать/отправлять без явного output аргумента. Синтетические witness могут быть результатом инструмента, не данными настоящих игроков.
- [x] Целевые unittest, полный набор `test_night_case*.py`, независимое review algorithm/replay/status честности. Зафиксировать elapsed без выдачи benchmark за игровой баланс.

Автор ранее сообщил: полный набор из 119 тестов, 8/8 witness и 24 smoke прошли. Независимое ревью D принято Sol после проверки case_format; последние 4 целевых simulation tests прошли за 37.601 s (exit 0). Координатор повторно запустил pinned isolated suite: 119 тестов прошли за 40.105 s (exit 0), включая последнее closure prerequisite. Это не V4 и не подтверждение проходимости «Усадьбы».

После D — отдельный проверенный контракт модулей manor и перенос сюжета в v2.
Публикация через владельца и первые тесты людей в rehearsal остаются следующими этапами.

## Продолжение witness после runtime/Communication (2026-11-15)

Внутренний валидатор принимает `find_witness(case, rules, composition_id, variant_id, *,
seed, budget=None, start_at=DEFAULT_START, prefix_steps=(), roster=None, game_id=None)`.
`prefix_steps` — упорядоченные записи **ровно** `{actor,command,now_utc}`. Actor —
`{kind:"player",account_id}` или `{kind:"system"}`, command — полный исходный envelope,
`now_utc` — UTC RFC3339 `Z`, не убывает от `start_at`. `roster` и `game_id` передают
закреплённую идентичность ранее начатого дела; по умолчанию остаются прежние synthetic
roster/game_id. Каждая prefix-команда повторяется только через общий `step`, её реальные
receipt/state hash/messages вычисляются заново и входят в те же command/state/wall budgets.
Отклонённая корректная команда тоже остаётся в истории; структурно неверная команда или
обратное время дают ошибку. Пустой prefix сохраняет прежнюю трассу core/1.

Дело с capability `communication` использует `night-city-witness/2`: каждый шаг дополнительно
содержит `expected_messages` — точный массив immutable `Transition.messages`, включая
text, hash и закреплённых получателей. Replay сверяет сообщение, state hash, receipt,
его сохранённый result_ref, порядок времени и case/profile/build. Дело без capability
сохраняет `night-city-witness/1` и прежний shape/hash; подмена версий отклоняется.
Witness — приватный артефакт доверенной проверки, не публичный DTO или HTTP-команда.
Этот поиск доказывает путь в ограниченной кооперативной политике, а не сюжетную догадку,
справедливость всех альтернатив или разрешение публикации.

`SearchBudget.max_seconds` — мягкий wall-clock предел поиска, проверяемый **между**
командами. Успешный путь затем обязательно повторяется через kernel; replay имеет отдельную
стоимость и не останавливается посередине по бюджету поиска. Отчёт различает
`search_elapsed_seconds`, `replay_elapsed_seconds` и полный `elapsed_seconds`, помечает
`budget_scope="between_commands"`. Поэтому `found` может иметь полный elapsed выше
`max_seconds`; это не заявление о скорости игры или сервиса.
