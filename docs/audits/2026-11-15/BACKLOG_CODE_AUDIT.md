# Задачи: сверка с кодом и приоритеты

Дата: 2026-11-15. Запрос владельца: проверить, что уже реализовано, что действительно
осталось и в каком порядке этим заниматься.

Проверенная копия: `C:\Users\Lizard\Projects\morning-quiz-bot`, фактический Git root
`F:\Projects\Quizywizzy`, ветка `main`, HEAD `bde8342` плюс существующие локальные
изменения. В частности, новое ядро `night_case`, его тесты и часть планов находятся
в untracked-файлах. Выводы относятся к прочитанному
рабочему срезу, а не только к HEAD или сборке песочницы.

Проверены ключевые цепочки кода и связанные тесты. Это не полная приёмка продукта:
PostgreSQL-тесты, миграция/restore, реальные Telegram-клиенты и визуальные сценарии
в этом аудите не запускались. Код, исходные задачи и их статусы не менялись;
добавлен только этот отчёт.

## Главное

- Реестр сильно отстаёт от кода. MQB-001/002/003/005/006 частично описывают одни
  и те же работы; заново реализовывать PostgreSQL, аккаунты, linking/recovery,
  отдельный worker и прямые игровые API не требуется.
- Реальный функциональный разрыв платформы — групповое Photo по принятой
  политике AUD-019. Нынешнее поведение по-прежнему основано на одном победителе.
- Недельный «Ночной город» уже имеет чистое доменное ядро, формат/компилятор,
  проекции и симулятор. До работающей игры не хватает интеграции с хранилищем,
  application-сервисом, worker, API/клиентом и законченного игрового дела.
- В ферме большинство перечисленных механизмов уже реализованы. Остались
  конкретные расширения и stub-эффекты, баланс и пользовательская приёмка.
- Подтверждённого аварийного P0 в проверенном срезе не найдено. Приёмочные ворота
  ниже обязательны перед соответствующим выпуском, но не являются новым кодом.

## Основной реестр

| Задача | Реализовано по коду | Реальный остаток |
|---|---|---|
| MQB-001 — PostgreSQL и Mini App | Бот и админка требуют PG и актуальную схему; импорт транзакционный, с advisory lock и сверкой counts/fingerprints; игровые API и настройки есть. | Свежая миграция конкретных данных, проверка media, backup/restore и сквозной Bot ↔ Mini App ↔ restart. Это приёмка существующей реализации. |
| MQB-002 — dev parity | В PG-админке подключены банк/media, профили, аналитика, обслуживание, backup, уведомления/outbox, feedback и другие подсистемы. | Текущая матрица пользовательских сценариев; не все внутренние административные функции подробно проверены в этом проходе. |
| MQB-003 — Telegram UX | Общая навигация, прямые игровые экраны, guest/account UI, SDK-адаптер, session recovery. | Настоящие Telegram Desktop/Android/iOS, вход/возврат, safe areas, группы и cross-channel. Старый пункт «добавить bridge» следует заменить прямым сценарием, MiniBridge возвращать нельзя. |
| MQB-004 — короткая Мафия | Действующая legacy-игра, application-сервис, worker, лобби/очередь/комнаты и клиент. | По текущему MQB-010 короткая игра — переходная заглушка: сохранять совместимость и безопасное завершение старых партий. Не развивать её как второй будущий режим без нового решения. |
| MQB-005 — общее ядро | HTTP и Telegram вызывают Classic/Photo application services, есть receipts/commands и серверный ledger. | Групповое Photo и приёмка паритета; небольшой остаток fake Update в адаптере Telegram-меню, а не Mini App bridge. |
| MQB-006 — PG-only платформа | Отдельный deadline worker для Mafia, Classic/Photo в чатах и комнатах; durable outbox, skip-locked claims, fencing, retry/uncertain и orphan quarantine. | Свежая PG/multi-process/restart/delivery/restore приёмка. Room Classic/Photo по умолчанию выключены флагами: наличие кода не означает доступность игрокам. |
| QW-2026-10-08 | Канонические Account/Room/Game, linking, merge, login/recovery/devices, verified Alchemy уже существуют. | AUD-019 group Photo; свежая приёмка сложных account/merge/race сценариев. Исторические AUD-005/009/010 нельзя переносить в backlog как факты отсутствия этих функций. |
| MQB-007 — Farm integration | `install_farm`, общий FarmService и feature flag подключены; HTTP/journey/cross-mode тесты существуют. | Сквозной standalone + Telegram/WebView цикл, приглашения, возврат, restart и device-приёмка. |
| MQB-009 — эпик | Часть A во многом реализована перечисленной платформой; часть B уже начата в локальном домене. | Эпик лучше использовать для объединения проверяемых результатов A/B, а не как ещё один независимый список переписывания платформы. Сам эпик не закрыт. |
| MQB-010 — недельный Night City | Формат v2/компиляция, строгий state codec, правила, окна/тихие часы, переходы, приватные проекции, action quote, narration/action boundary, bounded simulator и CLI. | Зарегистрировать режим в общем runtime; PG persistence/transactions/receipts/events, worker/restart, API/клиент/Telegram; дальнейшая семантическая валидация и полноценное дело с живой приёмкой. |
| NC-OPEN — открытые комнаты | Уже есть и сервер, и клиент: список столов, join-open, переключатель открытости, короткие коды/ожидание. | Свежая приёмка и сверка выложенной версии. Документ «клиент в очереди» устарел. Это пока комнаты короткой Mafia, не готовое подключение будущего night_case. |
| MQB-011 — форма обращения | Account setting, общий endpoint, сохранение и UI, Telegram storage adapter, формы текстов фермы. | В Alchemy и Mafia остались мужские/гибридные тексты; Telegram-приёмка. Шаблоны достижений явно отложены решением владельца — не переписывать автоматически. |

Опорные места кода (пути от корня репозитория):

- PG/startup/import: `bot.py:361`, `storage/startup.py:14`,
  `web/postgres_admin.py:461`, `storage/json_importer.py:472`, `:785`.
- Admin wiring/settings: `web/postgres_admin.py:503`, `storage/settings.py:100`.
- Прямые адаптеры: `handlers/poll_answer_handler.py:43`,
  `handlers/photo_quiz_handlers.py:137`, `web/mini_app.py:2018`, `:2179`;
  receipts — `storage/games.py:544`.
- Worker/outbox: `scripts/run_game_worker.py:34`, `application/game_deadlines.py:20`,
  `storage/notifications.py:51`, `:175`; flags — `web/mini_app.py:335`,
  `compose.dev.yml:141`.
- Account linking/merge/recovery: `application/account_linking.py:23`,
  `application/account_merge_flow.py:75`, `application/account_merge.py:45`,
  `application/account_security.py:90`, `web/account_security_routes.py:28`,
  `web/mini_client/app.js:613`, `:939`.
- Alchemy: sync даёт 0 наград — `storage/alchemy.py:222`; craft проверяет рецепты,
  verified ingredients и replay — `:289`; серверный расчёт награды — `:337`;
  expedition claim — `application/alchemy_journey.py:31`.
- Остаточный fake Update: `modules/telegram_menu.py:21`. Это преобразование
  callback в команду меню, не старый runtime bridge Mini App.
- NC-OPEN: `application/rooms.py:354`, `application/mafia.py:903`,
  `web/mini_app.py:1074`, `web/mini_client/night-city-ui.js:988`, `:1160`, `:1483`.
- Night kernel: `domain/night_case_v2_format.py:100`, `:173`,
  `domain/night_case_engine.py:198`, `:474`, `domain/night_case_projection.py:205`,
  `domain/night_case_simulation.py:329`, `:403`,
  `domain/night_case_narrative.py:127`, `:259`.
- Отсутствие night_case в общем runtime проверено поиском по application/storage/
  web/handlers/alembic: `application/rooms.py:146` перечисляет classic/mafia/photo,
  `storage/games.py:270` специализирует mafia, `application/game_deadlines.py:20`
  обслуживает только существующие режимы. Pure kernel пока не вызывается этими слоями.
- V1-валидатор не обещает полную V/U-проверку: `domain/night_case_format.py:133`,
  `:156`, `:188`. Новый v2 CLI честно разделяет scope и выставляет
  `publishable=false`: `scripts/validate_night_case_v2.py:29`.
- Форма обращения: `storage/address_form.py:13`, `web/mini_app.py:800`,
  `web/mini_client/app.js:346`; оставшиеся тексты — `handlers/mafia_handlers.py:124`,
  `:161`, `:575`, `handlers/config_handlers.py:585`,
  `minigames/alchemia-1.0/game.js:494`, `:568`.

## Конкретный разрыв: групповое Photo

Принятая политика AUD-019: приватный ответ каждого игрока, очки каждому правильно
ответившему, закрытие раунда по определённому правилу/дедлайну.

Сейчас `application/photo.py:237–247` после первого правильного ответа вызывает
`complete_round` и публикует одного winner; `domain/photo.py:267–280` завершает
вопрос и открывает следующий. Telegram передаёт `shared=True`, а Mini App current/
answer этого не делают (`web/mini_app.py:2239`, `:2289`), поэтому остальные участники
не получают равноправный приватный путь. Room Photo тоже creator-only:
`application/room_photo.py:86`, `:148`, `:191`.

Нужен законченный срез: состояние ответов по участнику/раунду → приватные проекции
→ однократные начисления каждому → закрытие worker → Telegram/private UI →
гонки ответов с дедлайном. Одной приёмкой существующего поведения это не закрыть.

## Ферма: реализация и остатки

| Направление | Реально есть | Реально осталось |
|---|---|---|
| Плантации | 6 га, уровни открытия, виноград/чай, buy/plant/uproot/auto, UI/арт и переработка. `qw_farm/plantations.py:10`, `:30`, `:110`; `static/app.js:2585`. | Ручная мини-игра сбора, обрезка и её бонус, кофе/хлопок. Сейчас кнопка сбора вызывает auto (`app.js:2598`). Волна 2 — отдельное расширение; сначала баланс окупаемости. |
| Просьбы соседям | Escrow, лимиты, SQL locking, условные переходы, expiry/block/merge, приватная проекция и outbox; UI подключён. `friend_requests.py:108`, `:199`, `:223`, `:357`; `service.py:483`. | Свежая PG race/replay/expiry и сквозная приёмка с уведомлениями. Тесты гонок уже существуют (`tests/test_farm_friend_requests.py:78`, `:195`, `:420`), поэтому «тестов нет» неверно. |
| Плодовый сад | 7 видов, цикл, уход/прививки, harvest/help/automation, миграция/компенсация; арт уже есть. `catalog.py:1346`; `orchard.py:206`, `:303`; `static/scene_orchard.js`. | Баланс/приёмка; задания Олега/Даши и праздничные заказы не подтверждены. Зимний рисунок предусмотрен, но выключен условием `s.orchardWinter===true` (`scene_orchard.js:164`). |
| Текстиль | Прядильня/ткацкая, сырьё/изделия, уроки Сони, красители. `catalog.py:1058`, `:1110`; `textile.py:36`; `static/app.js:1206`. | Фабрика и узорные рецепты прямо TODO/NOT defined (`catalog.py:1102`, `:1109`); домашний «Уголок Сони» не найден в projects. |
| Стройка и лавки | Стадии/взносы, SQL locking/CAS, perks/лоты/аренда/комиссия, арты; трактир уже имеет заказы/поднос/тост. `construction.py:26`, `:182`, `:217`, `:293`; `tavern.py:65`; `static/construction.js:222`. | Stub-эффекты оранжереи/ярмарки, часть обещанных личных бонусов трактира, ларёк Игоря и третий визит Сороки (`construction.py:49–51`, `:564`; `construction.js:358`). Следует отдельно согласовать, какие из них входят в текущую доступную игрокам версию. |
| Поле: этапы 1/2A/2B/2C | Поворот/per-cell, опрыскивание, повреждение/ремонт, частичная выгрузка, протокол rules=3 и совместимость старых заходов. `fields.py:39`, `:371`, `:549`; `static/tractor_game.js:108`; `static/app.js:8`. | Текущая пользовательская/Telegram-приёмка и баланс. Это уже реализованные механики; chain bonus не добавлять без согласованных правил. |
| Feedback 05.11 | F1 null-cost filter, F2 отдельный compost upgrade/8 ч, F3 boot-order исправление, F4 все 6 workshop goals. `static/farm_nav.js:194`; `catalog.py:68`, `:94`; `static/app.js:81`, `:654`, `:808`; `domain.py:529`. | Полный игровой цикл целей, restart/cross-tab и принятие игроками. F1–F4 не нужно создавать заново. |
| Feedback 21.10 / UI | Большие механики из старой таблицы теперь есть в коде. | E32 — отдельная претензия владельца к виду всех 11 жителей (`docs/tasks/FARM_FEEDBACK_2026-10-21.md:112`). E29/E30 и общая UI-приёмка не закрываются наличием арта или старых скриншотов. |

Пути без префикса в этой таблице относятся к `qw_farm/`.

## Рекомендуемые приоритеты

Принцип: закончить обещанные доступные игрокам циклы, проверить сохранность и
приватность общего состояния, затем расширять контент. Это рекомендация по backlog,
не разрешение на production и не смена статусов задач.

1. **P1 — закончить групповое Photo (AUD-019).** Это подтверждённая функциональная
   незавершённость, общая для нескольких старых MQB-задач.
2. **P1 — приёмка существующей платформы и фермы перед выпуском.** Свежие PG-тесты
   конкуренции/merge/restart, миграция/restore, затем сквозные браузерные и реальные
   Telegram-сценарии. Проверить фактические flags и версии контуров. Ворота можно
   выполнять параллельно с разработкой независимых функций, не откладывая до конца.
3. **P1/P2 — обещанные эффекты строек фермы.** Уточнить доступность игрокам
   оранжереи/ярмарки/оставшихся строительных бонусов и закончить выбранный scope.
   Если игрок уже расходует игровую валюту/ресурсы ради обещанного эффекта, это P1;
   если предложение недоступно, это P2 расширение. Реальные денежные платежи этим
   аудитом не подтверждены. Заново строить сад/трактир/просьбы не нужно.
4. **P2 — недельный Night City: следующий шаг — integration foundation.** Сохранение
   состояния/команд/событий в PG, worker и сервис, затем API/клиент и одно полноценное
   дело. Не начинать повторно pure kernel и не развивать короткую Mafia как целевой
   режим. Если ближайшая продуктовая цель — именно Night City, этот поток можно
   поднять выше Photo; безопасность общего состояния всё равно остаётся воротами.
5. **P2 — приёмка арта и небольшой долг.** Согласовать E32 (вид всех 11 жителей)
   с владельцем; MQB-011 оставшиеся тексты; привести два устаревших
   JS-теста к реальным инвариантам; обновить противоречивые задачи по результатам
   приёмки. При включении этих JS-тестов в обязательную проверку выпуска их
   актуализация становится воротами P1: падения нельзя молча исключить.
   Распределённый login limiter обязателен до публичного запуска с несколькими
   API workers: текущий лимит per-process (`storage/account_passwords.py:75`,
   `web/mini_app.py:348`), сбрасывается рестартом. При одной инстанции это известное
   эксплуатационное ограничение, не доказанный инцидент.
6. **P3 — расширения контента.** Плантации wave2/кофе/хлопок; текстильная фабрика/
   узоры/«Уголок Сони»; сезонные задания сада. Общий баланс сада/полей/плантаций
   проверить до добавления новых источников ресурсов, а не после.

## Свежие проверки

Все проверки выполнены 2026-11-15, TEMP/TMP направлены в `F:\Temp`, без запуска
бота, локальных серверов, миграций и пересоздания БД.

| Команда | Результат и граница |
|---|---|
| `python scripts/project_checks.py --worktree` | exit 0; проверка правил рабочего дерева, не готовность продукта |
| `python -m unittest discover -s tests -p 'test_night_case_*.py'` | 119 passed; чистый домен/формат/проекции/симуляции, без БД |
| `python -m pytest -q -p no:cacheprovider tests/test_mafia_open_rules.py tests/test_address_form.py::test_g_picks_each_form_and_unknown_values_read_as_neutral tests/test_address_form.py::test_parse_accepts_only_the_three_codes tests/test_address_form.py::test_javascript_copies_are_identical_and_agree_with_python` | 21 passed; правила лобби/короткой Mafia и pure формы обращения |
| `node --test --test-isolation=none tests/js/mini_navigation.test.cjs tests/js/alchemy_sync.test.cjs` | 163 passed; client logic, не настоящий WebView/E2E |
| `python -m pytest -q -p no:cacheprovider tests/test_farm_plantations.py tests/test_farm_textile.py tests/test_farm_orchard.py` | 117 passed |
| `python -m pytest -q -p no:cacheprovider tests/test_farm_friend_requests.py tests/test_farm_village_construction.py tests/test_farm_workshop_goals.py -k 'not pg and not postgres'` | 37 passed, 9 deselected; PG намеренно не запускался |
| Команда JS ниже | 69 passed, 2 failed; причины разобраны ниже |

```text
node --test --test-isolation=none tests/js/farm_friend_requests.test.cjs tests/js/farm_orchard.test.cjs tests/js/farm_village_construction.test.cjs tests/js/farm_tractor.test.cjs tests/js/farm_tractor_turn.test.cjs tests/js/farm_tractor_rules3.test.cjs tests/js/farm_field_overlay.test.cjs tests/js/farm_boot_order.test.cjs tests/js/farm_project_materials.test.cjs
```

Обычный Node test runner в песочнице упёрся в `spawn EPERM`; запуск без дочерней
process isolation прошёл до самих тестов.

Два падения не подтверждают пользовательский дефект:

- `farm_village_construction.test.cjs:191` требует три вызова подряд в одной строке;
  живые вызовы есть, но разделены (`qw_farm/static/app.js:2426`, `:2438`).
- `farm_project_materials.test.cjs:18` создаёт недопустимое сочетание stage/reserved/
  legacy_needs. Сервер валидирует его (`qw_farm/projects.py:204`), удаляет legacy
  при release/deliver до смены стадии (`:170`, `:176`), owner projection присылает
  authoritative needs (`:107`), UI берёт их первым (`static/app.js:672`). Нужно
  обновить fixture и сохранить проверку реального перехода старой сметы.

Feedback серверной песочницы прочитан в read-only транзакции через действующий
PostgreSQL-контейнер: `manual done=2`, `auto_error done=2`, незакрытых записей 0.
Статусы не менялись. Отсутствие открытых отчётов не доказывает приёмку функций.

## Чего этот отчёт не подтверждает

- Что локальный код уже выложен в песочницу или production.
- Что прошли PostgreSQL gate, миграция и restore конкретных retained backup.
- Что пройдены реальные Telegram Desktop/Android/iOS и визуальные сценарии.
- Что все исторические задачи можно пометить done: закрытие требует их критериев
  и свежей приёмки, а не только найденных функций или количества unit-тестов.
