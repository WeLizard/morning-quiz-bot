# QuizzyWizzy / Morning Quiz Bot
## Глубокий статический аудит и обязательная спецификация доработки

**Дата:** 2026-10-08
**Версия отчёта:** 1.0 / baseline для Codex
**Исходная ревизия:** [`aeeab2b358014934521d401d7a113a4769b41e46`](https://github.com/WeLizard/morning-quiz-bot/commit/aeeab2b358014934521d401d7a113a4769b41e46), ветка `main`
**Репозиторий:** https://github.com/WeLizard/morning-quiz-bot
**Целевая dev-копия:** `C:\Users\Lizard\Projects\morning-quiz-bot`
**Production:** не изменять; зафиксированные ранее расхождения со старым JSON-контуром требуют отдельной повторной проверки.

> **Статус доказательств.** Проведён глубокий **read-only аудит доступного GitHub HEAD**: дерево исходников, серверные и клиентские точки входа, игровые домены, модели, миграции, обработчики, очереди, сборка, скрипты, тесты, документы, все 63 исходных JSON-каталога вопросов. Проверялись конкретные участки кода и некоторые контрактные тесты. **Ни развертывание, ни PostgreSQL, ни запущенные API, ни реальные Telegram-клиенты, ни полный локальный pytest/browser suite в этом аудите не запускались.** Поэтому утверждение «реализовано в коде» не равнозначно «успешно принято в эксплуатации». Документ не выдаёт выборочное ревью каждого файла за полную строчную проверку всех 1064 файлов, включая графические ассеты. При обновлении `main` сначала выполнить rebaseline и сверить каждый критический пункт.

**Статус требований:** `[MUST]` — обязательно для описанного этапа; `[MUST NOT]` — запрещено; `[SHOULD]` — предпочтительно, отклонение фиксировать ADR; `[PROPOSED]` — продуктовый вариант, требующий явного утверждения до реализации.

**Уровни доказательств:** `CONFIRMED` — непосредственно проверяется в ревизии; `RISK` — следствие архитектуры без проведённого динамического воспроизведения; `GAP` — отсутствует функциональная реализация, заявленная в целевой модели; `DECISION` — несогласованное бизнес-правило; `LEGACY` — исторические документы/контур могут расходиться с HEAD.

**Шкала приоритета:** `P0` — блокирует безопасную публикацию или целостность наград/данных; `P1` — блокирует целевую платформу/приёмку игры; `P2` — обязателен для качественного публичного запуска или требуемого игрового направления; `P3` — развитие после устойчивого релиза. P0/P1 не означает подтверждённую эксплуатацию уязвимости.

---

# 1. Решение по результатам аудита

## 1.1 Краткий вывод

1. **Хорошая основа уже существует:** доменные `domain/`, сценарии `application/`, PostgreSQL `storage/`, `games/game_commands/game_events/game_deadlines/notification_outbox`, отдельный Mini App, проверка `initData`, вход с отдельным токеном, idempotency ledger квизов, фотокаталог, независимый сборочный контур Алхимии. Сохранять и развивать, **не переписывать с нуля**.
2. **Нельзя считать пять игр готовой веб-платформой:** классический и фото-квизы уже играются, Мафия — прототип полного цикла с короткими фазами, Алхимия — контентно насыщенный режим с небезопасным для наград «доверенным импортом открытий», «Весёлый фермер» — только концепция без движка/экрана.
3. **Переход на standalone сделан только частично:** появились `accounts`, `guest_sessions` и гостевой cloud save Алхимии. `games`, участники и Мафия всё ещё привязаны к Telegram `chat_id`/`user_id`. В гостевом интерфейсе доступна только Алхимия.
4. **Публикация новой редакции должна быть остановлена до закрытия P0:** начисление рейтинговых очков Алхимии по непроверенной клиентской сводке; несогласованная production-конфигурация хранилища; известные уязвимые зависимости. Существующий production **не трогать** без конкретного разрешения.
5. **Ближайшая архитектурная цель:** независимые `Account/Room/Game` и отдельный серверный deadline-worker, Telegram — адаптер доставки, а не центр правил/жизненного цикла.
6. **Главное правило разработки:** выпускать вертикальные пользовательские сценарии, а не «слои на будущее». Для каждой задачи — контекст, API/DB-контракт, тесты, реальный ручной smoke, наблюдаемость, ограниченный diff и откат.

## 1.2 Инвентаризация пяти режимов на HEAD

| Режим | Фактические источники | Состояние | Отдельные ограничения |
|---|---|---|---|
| 01 Классический квиз | `domain/classic.py`, `application/classic.py`, `handlers/`, `data/questions/`, `web/mini_client/play-ui.js` | Полный серверный цикл и прямые API; часть legacy UI всё ещё в bridge | Общая авторизация через Telegram, неполная standalone-проекция, приёмка клиентов |
| 02 Фото-загадки | `domain/photo.py`, `application/photo.py`, `storage/photo_media.py`, `web/mini_app.py` | Серверный цикл, фото, таймеры, подсказки, оценка, медиа | Зафиксировать личный/групповой контракт; один лишь создатель серии может отвечать по текущему `application/photo.py` |
| 03 «Ночной город» / Мафия | `domain/mafia.py`, `application/mafia.py`, `handlers/mafia_handlers.py` | Лобби, роли, ночь/день/голосование, дедлайны, победа и реванш | **Не полноценно async:** 90/180/90 секунд, глобальная ревизия, Telegram-группа обязательна; нет AFK/пауз/обсуждения внутри standalone |
| 04 «Атлас маленьких чудес» / Alchemy | `minigames/alchemia-1.0/`, `storage/alchemy.py`, `web/mini_client/alchemy.html`, `sync.js` | 431 элемент, 1035 рецептов, 33 главы, 42 достижения; гость/Telegram, cloud save | Сервер доверяет сообщённым ID открытий для наград Telegram; нет полноценной доверенной offline-аттестации, привязки аккаунтов |
| 05 «Весёлый фермер» | `docs/engineering/FARM_CONCEPT.md` | **Концепт** | Нет БД/игрового сервиса/API/UI/тестов/иконки; scope первого выпуска требует отдельного решения владельца |

**Вне текущих пяти игр:** AI-ведущий/нарратив и интерактивное расследование — идеи будущих этапов; `modules/admin_ai.py` обслуживает AI-функции админки, **не** является готовым AI-ведущим партии.

## 1.3 Фактическая топология и долг

```text
ТЕКУЩЕЕ
Telegram Bot -- PTB handlers, callbacks, job_queue -----+
                                                      |  v
Mini App Web (FastAPI + JS) -- direct app services ----+-- domain/ + application/
      |                         |                       |           |
      +---- legacy MiniBridge --+                       +------ PostgreSQL
      +---- гостевой вход и Alchemy save ----------------------+

ЦЕЛЬ
Standalone Browser / Telegram Mini App / Telegram Bot (адаптеры)
                     |
          единая идентичность Account / Identity
                     |
            Room / Membership / Game
                     |
             application commands
                     |
        domain (Classic, Photo, Mafia, Alchemy, Farm)
                     |
               PostgreSQL + outbox
                    ^   |
          независимый worker -> notification adapters
```

**Архитектурные инварианты:** одна транзакционная запись эффекта; роли и ответы секретны по адресату; все награды только из проверенного события; повтор команды не удваивает результат; альтернативный клиент не создаёт вторую игру; сервер не зависит от присутствия Telegram-процесса; история/сохранения сохраняются после рестарта.

---

# 2. Реестр результатов — с исходниками и критериями исправления

**Точная ссылка** строится от исходного commit: `https://github.com/WeLizard/morning-quiz-bot/blob/aeeab2b358014934521d401d7a113a4769b41e46/<PATH>#L<START>-L<END>`. Эти пути — доказательство по HEAD, не указание слепо править строки на будущих ревизиях.

| ID | Приор. | Тип | Обнаружено / последствия | Источник | Контроль исправления |
|---|---|---|---|---|---|
| AUD-001 | **P0** | CONFIRMED | `AlchemyService.sync` начисляет очки за множество валидных известных `discovered`, **не** за серверно исполненные рецепты. Список ID можно отправить напрямую, не проходя игру. Суточный лимит 30 ограничивает, но не устраняет некорректное начисление | `storage/alchemy.py:192–264`, `web/mini_app.py:416–462`, `tests/test_alchemy_mechanics.py:77–101` | Фальшивый список элементов не создаёт проверенные открытия и не изменяет `global_score`; проверенное `craft` выдаёт награду однократно |
| AUD-002 | **P0** | CONFIRMED | Старый `docker-compose.yml` использует `STORAGE_BACKEND=${STORAGE_BACKEND:-json}`, а новый bot runtime требует `postgres`. Старый `env.example` тоже выставляет JSON | `docker-compose.yml:30–43`, `env.example`, `storage/startup.py:13–18`, `bot.py:359–361` | Развёртывание с документированными production settings либо поднимает PG стек с миграциями, либо **явно** fail-closed до приёма трафика; нет молчаливого JSON fallback |
| AUD-003 | **P0** | CONFIRMED | `python-multipart==0.0.6` в production manifest и `==0.0.20` в dev manifest попадают под известные DoS advisory для парсинга форм/заголовков | `requirements.txt`, `requirements-local-test.txt`, `requirements-local-lock.txt` | Подтверждённая безопасная совместимая версия (`>=0.0.31` как нижняя цель по рассмотренным advisory либо актуальная security-approved), lock/SBOM/аудит/контрактные тесты загрузки |
| AUD-004 | **P1** | CONFIRMED | Telegram bearer сохраняется в `localStorage` и `sessionStorage`, передаётся в `#t=...` на странице Алхимии; при XSS/злонамеренном скрипте это долговременный секрет | `web/mini_client/app.js:120–130,237–249`, `minigames/alchemia-1.0/sync.js:17–30` | Ни один long/short-lived auth-secret не появляется в URL/hash/localStorage; безопасный одноразовый handoff/HttpOnly session, автообновление сохраняется |
| AUD-005 | **P1** | CONFIRMED | Основной `games` и `game_players` зависят от `chats` и Telegram `users`, ключ игры — `chat_id + mode`; standalone комнаты отсутствуют | `storage/models.py:157–225`, `storage/games.py:28–75`, `application/mafia.py:37–46` | Browser-only Account создаёт комнату и многопользовательскую игру без Telegram ID; старые TG-чаты сохраняют историю |
| AUD-006 | **P1** | CONFIRMED | Дедлайны Mafia/Classic/Photo и выгрузка outbox выполняются внутри `MafiaHandlers.deadline_job`, установленного через PTB job queue каждые 5 секунд | `handlers/mafia_handlers.py:372–452,637–643`, `bot.py:609` | Остановленный Telegram не влияет на завершение фазы/финала/сохранение; отдельный worker с рестартом/lease и журналом |
| AUD-007 | **P1** | CONFIRMED | Два **разных** участника Mafia, совершившие независимые действия на одной глобальной `revision`, получают конфликт для второго действия | `domain/mafia.py:306–347,416–430`, `application/mafia.py:162–180,241–259` | Конкурентные действия различных разрешённых участников одной фазы оба принимаются; конфликт только при действительной смене фазы/собственного действия |
| AUD-008 | **P1** | CONFIRMED | `GameRepository.reserve_command` для повторного `command_id` сравнивает actor/kind/revision/payload, но **не сверяет `existing.game_id`**. Теоретически возврат чужого ранее завершённого результата при повторном ID другого матча | `storage/games.py:248–285` | Один ID разных матчей отклоняется без выдачи чужого `result` и без изменения состояния; idempotency scoped к `game_id` |
| AUD-009 | **P1** | GAP | Гостевой `Account` нельзя восстановить после удаления cookie, нельзя связать с Telegram; срок cookie 30 дней не равен гарантии возврата аккаунта | `storage/guest_accounts.py`, `docs/engineering/STANDALONE_FOUNDATION.md` | Verified identity-link + recovery flow без silent merge/угонов; после восстановления виден тот же прогресс |
| AUD-010 | **P1** | GAP | Гостевой интерфейс `guestHome()` предоставляет только Alchemy, прочие игры требуют Telegram-вход | `web/mini_client/app.js:60–83,113–175`, `web/mini_app.py:317–360` | Главная capability-aware по идентичности; объявленные standalone игры запускаются без Telegram |
| AUD-011 | **P1** | CONFIRMED | Сохранились адаптер `MiniBridge`, synthetic `Update.de_json`/`process_update` и мост `runtime/actions` | `modules/mini_bridge_worker.py:17–78`, `web/mini_app.py:1172–1205`, `web/mini_client/play-ui.js:41,70–94` | Все необходимые use cases переведены на прямые application commands с паритетом UI, только затем удалён bridge; регрессий classic/photo нет |
| AUD-012 | **P1** | CONFIRMED | Mafia имеет фиксированную ночь 90 с, день 180 с, голосование 90 с — не модель участия в разное время | `domain/mafia.py:10–12`, `:225–229`, `:396–457` | Настраиваемые длительности, timezone/quiet hours, таймеры сохраняются через рестарт, неактивность имеет предел |
| AUD-013 | **P1** | GAP | Нет полного lifecycle async Mafia: выход/AFK/замена, пауза/восстановление, передача host, чат обсуждения в приложении, настройки фазы | `domain/mafia.py`, `application/mafia.py`, `docs/engineering/RELEASE_CRITERIA.md` | Матрица нормальных/краевых переходов; партия завершается при пропаже ведущего, секреты сохраняются |
| AUD-014 | **P1** | RISK | Outbox сознательно переводит неопределённые отправки в `uncertain`/`sending` без автоматического повтора; но нет подтверждённого операционного способа разбора накопленных состояний | `storage/notifications.py:36–103`, `handlers/mafia_handlers.py:404–452` | Dashboard backlog+age+error; операторское безопасное согласование; никогда не отправлять неизвестно принятую Telegram операцию вслепую |
| AUD-015 | **P1** | CONFIRMED | User/App баланс и результаты смешивают исторические рейтинговые и недоверенные offline сведения без явного поля `verification_status` для каждой Alchemy-награды | `storage/alchemy.py`, `storage/models.py:484+`, `minigames/alchemia-1.0/sync.js` | Награды только за validated server events; существующий прогресс мигрирует со статусами без уничтожения коллекции |
| AUD-016 | **P1** | LEGACY | Старый production-контур по сохранённому аудиту был JSON и содержал другую версию кода, миграция PG сделана лишь в rehearsal; текущее production состояние не перепроверялось | `docs/tasks/PROD-DIVERGENCE-REVIEW.md`, `docs/tasks/MQB-007-production-cutover-runbook.md` | Fresh read-only prod fingerprint+diff, preflight snapshot, проверенный restore, explicit owner go/no-go; не делать reset/checkout на prod |
| AUD-017 | **P1** | RISK | Процессные лимиты Mini App хранятся в RAM и привязаны к `request.client.host`; при масштабировании/неверной proxy цепочке лимиты либо обходятся, либо становятся общими | `web/mini_app.py:101–124,201–230` | Edge rate limit по реальному проверенному IP+account, лимиты распределены; proxy trust строгий, тесты multiple workers |
| AUD-018 | **P2** | CONFIRMED | Каталог вопросов: 5 некорректных record и 14 intra-category повторов; один дубль вопроса имеет противоречащие ответы | `data/questions/*.json`; точный реестр в §5 | Валидация всех 6706 seed-строк и активного PG банка; ноль invalid/конфликтующих дублей, сохранён журнал правок |
| AUD-019 | **P2** | RISK | Текущий `application/photo.py` принимает ответ только от `creator_id`; исторический фото-квиз опирался на ответы пользователей в групповом чате | `application/photo.py:171–182,323–327`; legacy `modules/photo_quiz_manager.py` | Product decision private-vs-group + тесты обеих реальных веток, не менять поведение молча |
| AUD-020 | **P2** | CONFIRMED | В `HOME_GAME_CARDS` есть 4 карточки; пятая игра отсутствует, нет декларативного feature/capability каталога | `web/mini_client/app.js:217–256`, `docs/engineering/FARM_CONCEPT.md` | Режимы подключаются единым manifest/API; Farmer отображается только при готовности или явно помечен «в разработке» без ложной кнопки |
| AUD-021 | **P2** | GAP | Farmer не имеет state machine, БД, inventory/ledger, API, UI, economy/конкурентных тестов | `docs/engineering/FARM_CONCEPT.md` и отсутствие модулей по дереву HEAD | Вертикальный MVP из §9: посадка → созревание без клиента → сбор → заказ → расширение, persist/restart/idempotency |
| AUD-022 | **P2** | CONFIRMED | Runtime версии и dependency-манифесты разъехались: prod Docker 3.11 vs dev Docker 3.13; `setup.py` placeholder URL, неподтверждённая лицензия и `console_scripts` на `async def main` | `Dockerfile`, `Dockerfile.dev`, `requirements*.txt`, `setup.py:24,78`, `bot.py:339` | Один проверенный supported runtime, reproducible lock, packaging smoke с корректным синхронным CLI launcher, законная лицензия или «не указана» |
| AUD-023 | **P2** | GAP | Нет подтверждённой server-side CI в дереве HEAD; локальные opt-in Git/Codex hooks не заменяют обязательный pipeline | `.githooks/`, `.codex/hooks.json`, `scripts/Test-LocalMilestone.ps1`, отсутствие `.github/workflows` в дереве | PR gate: DB migrations/pytest/JS E2E/security/asset hash; отчёт SHA, skipped, артефакты, запрет merge при fail |
| AUD-024 | **P2** | RISK | Большие legacy модули и веб-монолит повышают вероятность «двух источников истины» и пропусков авторизации | `web/main.py` (~4500 строк), `data_manager.py`, `modules/photo_quiz_manager.py` | Не переписывать сразу; покрыть boundaries, затем выделять use cases по вертикалям и удалить dead branches |
| AUD-025 | **P3** | GAP | AI-ведущий, расследование, narrative rules ещё отсутствуют как игровая система; админский AI не заменяет игровой | `docs/engineering/RELEASE_CRITERIA.md`, `modules/admin_ai.py` | Опциональный контракт §10; только server-validated typed narrative events; секретные роли не в публичном prompt |
| AUD-026 | **P2** | CONFIRMED | UI брендинг пока `Morning Quiz`; стартовый meta-text говорит только про квиз+фото; нет единой карты standalone/Telegram возможностей | `web/mini_client/index.html:7–24`, `web/mini_client/app.js` | Согласованный нейминг QuizzyWizzy, пять режимов в каталоге, гостю ясно, что доступно, адаптивность и a11y |
| AUD-027 | **P2** | RISK | Встроенная сборка Alchemy и контентно-ресурсный граф проверяются скриптами, но при ручной правке HTML можно рассинхронизировать source/artifact/hash | `minigames/alchemia-1.0/build.py`, `verify_content.py`, `web/mini_client/alchemy.html` | Build в CI воспроизводит byte-identical артефакт; проверяет hash/catalog/art, нельзя коммитить только HTML |
| AUD-028 | **P2** | GAP | Нет единого политического/технического договора на восстановление аккаунта, удаление данных, активные игры, экспорт и retention | `storage/models.py`, `web/mini_app.py`, документы | Account lifecycle, explicit delete/export, linked identities/ban propagation, backups/retention, аудит административных событий |

**Примечание к AUD-003:** известные advisories: [GHSA-2jv5-9r88-3w3p](https://github.com/advisories/GHSA-2jv5-9r88-3w3p) (затрагивает `<=0.0.6`), [GHSA-pp6c-gr5w-3c5g](https://github.com/advisories/GHSA-pp6c-gr5w-3c5g) (затрагивает `<0.0.27`), [GHSA-v9pg-7xvm-68hf](https://github.com/advisories/GHSA-v9pg-7xvm-68hf) (затрагивает `<0.0.31`, контекст `parse_form` может быть неиспользуемым — проверять достижимость). **Не все перечисленные advisory автоматически эксплуатируемы через конкретные маршруты проекта**; наличие затронутых версий достоверно, достижимость требует теста.

---

# 3. Обязательные нефункциональные контракты платформы

## NFR-01. Архитектурное владение состоянием [MUST]
- `domain/` — чистые правила и детерминированные переходы (`state, command, now → new_state, events`), без FastAPI/PTB/ORM/side effects.
- `application/` — авторизация, атомарные команды, идемпотентность, конкурентность, очки, запись событий, outbox.
- `storage/` — DB/repositories/migration и транзакции, без решений по правилам игры из HTTP-обработчика.
- `adapters` (Telegram/Web) — input validation, auth, projection, delivery, **не** собственное состояние игры.
- PostgreSQL — единственный authoritative mutable state; статичные JSON используются как **версионированный контент/seed**. Клиентский cache никогда не является авторитетом для наград/платежей/случайных итогов.
- **MUST NOT** создавать новые фальшивые Telegram `Update`, `MiniBridge`, делать rules через JavaScript-only или копировать legacy `StateManager` ради удобства.

## NFR-02. Идентичность/права [MUST]
- Внутренний `account_id` не равен Telegram `user_id`; `room_id` не равен Telegram `chat_id`, `game_id` не зависит от какого-либо провайдера.
- Верифицированные Telegram identities привязываются только через доказательство контроля **обоих** аккаунтов; имена/аватары/совпадение браузера не дают автоматического связывания.
- Отдельные роли: `room_owner`, `moderator`, `player`, `spectator` (если разрешены), с явными permissions. Read-операции не возвращают чужих секретов.
- `401`: нет/истекла identity; `403`: известный actor без права; `404`: ресурс не существует **или скрыт**; `409`: конфликт фазы/версии/idempotency; `422`: неверное тело; `429`: throttling; `503`: временно недоступны DB/проверка identity. Коды и сообщения согласовать для всех адаптеров.
- Отозванные/заблокированные identities немедленно теряют доступ к новым игровым операциям; moderator-решения и причины логируются без раскрытия лишних данных игрокам.

## NFR-03. Идемпотентность и конкурентность [MUST]
- Каждый мутирующий запрос несёт устойчивый `command_id` (UUID или равноценный 128-битный ID), уникальный в контексте `game_id`/`account_id` + kind + actor + payload fingerprint. Сервер хранит receipt/result транзакционно.
- Повтор с **полностью совпадающим** `game_id`, actor, kind, canonical payload возвращает тот же результат. Другой `game_id` или payload с тем же ID → 409, ничего не раскрывает.
- Два независимых действия разных игроков в той же фазе не требуют последовательного refresh всей партии; сериализация/row-lock допустима, отказ по уже неактуальной global revision — нет.
- Для одного участка/урожая/партии/вопроса ровно одно успешное начисление. БД-ограничения служат последним барьером, транзакция включает изменения inventory, ledger, events и outbox.
- Отсутствие `Idempotency-Key` в новых v1 write API: 422/400 (зафиксировать единый код), а не best-effort fallback. Устаревший API закрывать после миграции клиентов.

## NFR-04. Таймеры и независимый worker [MUST]
- Время — серверный UTC; UI показывает timezone пользователя; БД хранит абсолютные сроки и версию фазы. Уход в background/выключенный браузер ничего не отменяет.
- Выделенный процесс `game-worker`, выбирает due tasks через `FOR UPDATE SKIP LOCKED`, rechecks current state under lock, атомарно завершает переход, пишет событие и intent.
- Обработка каждого дедлайна exactly-once **внутри БД** в смысле однократного игрового эффекта; доставка во внешний Telegram не объявляется exactly-once.
- При двух workers один переход выполняется один раз; после падения/restart работа восстанавливается; stop Telegram не влияет на таймеры.
- Не выполнять тысячи пропущенных «тиков»: рассчитывать итог на основе timestamps с ограничением шагов. Для мгновенных длительных игр это особенно важно.

## NFR-05. Безопасность/API [MUST]
- Перестать сохранять bearer в LocalStorage/URL/hash. Варианты: короткий server-side одноразовый обмен при открытии отдельной страницы или first-party HttpOnly `Secure;SameSite` cookie с CSRF и ограничением пути/контекста.
- Не ослаблять HMAC Telegram `initData`, валидировать freshness/replay, проверять Origin/Host и доверенную proxy chain; доступ к фото/сессиям строго по владельцу/участнику.
- Ограничение размеров HTTP тел, парсер multipart, частота и количество запросов, таймауты, backpressure; secret stripping в логах/исключениях; prod ключи из секретов, не committed env.
- Проверять сценарии XSS в названии комнаты, имени пользователя, custom вопросах/описаниях, ответах, AI-тексте; CSP и HTML escaping/DOM `textContent` для пользовательских строк.
- Минимальные DB privileges для API/worker/migrator и readonly аналитики; не использовать админскую роль/токен в Mini App.

## NFR-06. SLO и эксплуатация [PROPOSED, закрепить нагрузочным профилем]
- Начальные цели на эталонном dev/staging стенде: `GET p95 <= 300 мс`, mutating API `p95 <= 750 мс`, обработка просроченного дедлайна `<= 10 с` от наступления срока при здоровом worker, **без учёта внешней доставки Telegram**.
- Под нагрузочным профилем не менее 100 одновременно активных игр, 1000 учётных записей и 20 одновременных команд на одну игровую фазу; зафиксировать стенд, генератор, seed и прогоны.
- Метрики: API error ratio/latency, worker lag, due queue, outbox pending/sending/uncertain, idempotency conflicts, session login/reauth, orphan media, failed migrations, verified vs unverified Alchemy changes, FARM inventory invariant violations.
- Структурные логи с `request_id`, `game_id`, `account_id` в обезличенном виде; **ни токенов, ни тайных ролей, ни полных JSON игровых payloads**. Health/readiness разделить; readiness 503 при недоступной БД/несовместимой схеме.

## NFR-07. Изменение данных/совместимость [MUST]
- Alembic *expand → backfill → validate → switch → contract*. До снятия старых колонок — отдельная проверка всех работающих adapters.
- Миграция из JSON production проходит только с консистентным снимком, count+fingerprint validation и отдельной PG контрольной базой.
- Все активные партии, ревизии, очки, фото-ссылки, привязки и достижения сохраняются или переводятся в законный `interrupted` по заранее подписанной миграционной политике; молча прекращать/обнулять запрещено.
- Backup = согласованный `pg_dump` **плюс** фото/медиа/конфиги/схема/ключи восстановления вне репозитория. Пробный restore обязателен, отдельно продумать откат **после** появления новых PG-записей.

---

# 4. Целевая платформа: точная спецификация и контракты

## 4.1 Целевая модель данных [MUST]

Это **логическая целевая схема**, не команда немедленно создать весь набор таблиц; Codex выбирает минимальную безопасную миграцию через действующий `storage/models.py` и Alembic.

| Сущность | Минимальные поля | Инварианты/индексы |
|---|---|---|
| `accounts` | `id UUID PK`, display_name, moderation flags/revision, timestamps, account_version | Один аккаунт может существовать вообще без Telegram; определён владелец прогресса |
| `account_identities` (новая) | `account_id FK`, provider (`telegram`, later verified-provider), provider_subject, verified_at, linked_at, revoked_at | Уникальная активная (`provider`, `provider_subject`); linking proof обоих субъектов; логи привязки |
| `guest_sessions` (существует) | hashed token, account_id FK, TTL, revoked, account_revision | Хэш, а не plaintext; unique lookup; отозванный/expired не валиден |
| `account_recovery` (вариант) | account_id, одноразовый verification challenge digest, expires_at, consumed_at | Нельзя восстановить по никнейму; решение UX/провайдера согласовать |
| `rooms` (новая) | `room_id UUID PK`, owner_account_id, visibility, invite_version, settings JSON, revision, timestamps | Комната не зависит от Telegram; room invite нельзя угадать; тип доступа однозначен |
| `room_members` | room_id, account_id, role, status, joined_at, left_at | UNIQUE(room_id, account_id active), серверные permissions и ban |
| `room_transports` | room_id, provider, external_chat_id, attached_at | Telegram group может быть связан с room после проверки администраторских полномочий; уникальность активной связи |
| `games` (существует) | id, room_id nullable во время миграции, legacy chat_id nullable, mode, phase, status, phase_version, state_version, current, timestamps | Ровно одна активная по `(room_id, mode)` для соответствующих режимов; history не теряется |
| `game_players` | game_id, account_id (после миграции), seat, alive/status, public_state, private_state | Нет нужды в Telegram User; private_state не экспортируется в general projection |
| `game_commands` | command_id, game_id, actor_account_id, kind, canonical_payload_digest, phase/version fence, status, result/error, timestamps | Unique key и полное сравнение game/actor/kind/payload, body limits; replay — тот же ответ |
| `game_events` | game_id, index, kind, actor_account_id, visibility, schema_version, payload, created_at | Append-only; `(game_id,index)` уникален; GDPR-политика псевдонимизации отдельно |
| `game_deadlines` | game_id, deadline_kind, due_at, revision, status, claimed_by/at | Серверное время, повторный claim без второго transition, overdue допустим |
| `notification_outbox` | id, event_id/dedupe_key, adapter, target, status, attempt, reason, available_at | Терминальные/uncertain статусы, audit, отсутствие повторной игровой награды при доставке |
| `score_ledger` (нормализовать) | event ID, account_id, game_id, source, amount DECIMAL, verified, day_utc, created_at | Сумма определяется из ledger, тип источника обязателен, `unique(event_id, beneficiary)` |
| `alchemy_progress` (существует) | account_id PK, verified discoveries, imported discoveries, recipes, catalog_version, goals, achievements, timestamps | Различать подтверждённые и клиентские открытия, migration без обнуления коллекции |
| `alchemy_actions` (новая) | account_id, command_id, catalog_version, operand ids, output, result, created_at | Рецепт подтверждён сервером, уникальный receipt, без двойного начисления |
| `farms`, `farm_plots`, `farm_inventory`, `farm_orders`, `farm_ledger` | см. §9 | Транзакционный ресурсный учёт, единый account_id, timestamps; редактирование только командами |

### Миграции и backfill

**DB-01.** Добавить независимые `rooms`, membership и external-chat mapping; создать mapping для существующих Telegram-чats, затем `games.room_id` и `game_players.account_id`, оставив старые колонки совместимости.

**DB-02.** Для каждого уже существующего `users.id` определить/создать `accounts.id`, все `chat_members` и старые `games` отобразить в новую комнату и участника. Сохранить `game_id` и историю; проверить counts/FK/unique и **семантику private roles**.

**DB-03.** Все внешние команды на старом API во время dual-write используют **тот же application service** и транзакцию; двух авторитетов PG/JSON или `games/chat_sessions` не возникает.

**DB-04.** Миграции, затрагивающие `alchemy_progress` после `20261007_0015`, должны работать и для Telegram-строк, и для гостевых `user_id IS NULL`. Нельзя назначать чужую колонку `user_id` ради выполнения старого ограничения.

**DB-05.** До удаления legacy колонок/индексов: выгрузить число комнат, матчей, участников, команд, прогрессов/очков по источникам, проверить равенство и deterministic hash выборочных игровых snapshot. Проверить backfill дважды (idempotence).

**DB-06.** На выходе должна быть одна source-of-truth таблица для каждой роли сущности, явные deprecated endpoints, миграционный план клиентских версий и checkpoint rollback. Держать версионирование событий: неизвестное событие не должно приводить к молчаливой порче state.

## 4.2 Предлагаемые HTTP-контракты v1 [MUST после утверждения контрактов]

**Это новые целевые маршруты, они НЕ существуют в текущем HEAD.** Названия допустимо скорректировать под существующую структуру с записью ADR. Не выпускать два конкурирующих независимых API.

### Идентичность

```http
POST /api/v1/auth/guest
GET  /api/v1/accounts/me
POST /api/v1/auth/telegram/link/start
POST /api/v1/auth/telegram/link/confirm
DELETE /api/v1/accounts/me/sessions/{session_id}
GET  /api/v1/accounts/me/export
```

- `POST /guest` создаёт account/session или безопасно возобновляет; никогда не создаёт новый аккаунт от одного и того же действующего cookie случайным refresh.
- `link/start` порождает short-lived одноразовый challenge, привязанный к session/account и nonce; `confirm` валидирует Telegram signed proof/telegram identity. Конфликт provider_subject → 409, без автоматического merge.
- Продуктовое решение при двух непустых аккаунтах: **не объединять молча**; предоставить preview diff + ручной подтверждённый merge с конфликтной политикой по наградам, истории и room ownership.
- Cookie flags при HTTPS: `HttpOnly`, `Secure`, `SameSite=Lax/Strict` в зависимости от реального Telegram WebView с документированной угрозомоделью; CSRF token на mutating API, ограничение сроков, logout/revoke.

### Комнаты

```http
POST /api/v1/rooms
GET  /api/v1/rooms?scope=mine
GET  /api/v1/rooms/{room_id}
POST /api/v1/rooms/{room_id}/invites
POST /api/v1/rooms/{room_id}/join
POST /api/v1/rooms/{room_id}/leave
POST /api/v1/rooms/{room_id}/members/{account_id}/moderate
```

- Создать приватную комнату может авторизованный Account; максимальное число участников и invite TTL — серверный settings с валидацией.
- Приглашение — криптостойкий token **в хранении только digest**, TTL, max_uses, revoke/version. Нельзя читать чужие комнаты перебором ID.
- При удалении/бане комнаты активная партия получает разрешённое состояние `paused/interrupted` по договору режима, но не orphan.
- Telegram-chat mapping создаёт адаптер только после проверки прав и согласия создателя. Уход бота из Telegram-группы **не удаляет** standalone room/game.

### Игровой каталог/команды

```http
GET  /api/v1/games/catalog
GET  /api/v1/rooms/{room_id}/games
POST /api/v1/rooms/{room_id}/games
GET  /api/v1/games/{game_id}
GET  /api/v1/games/{game_id}/events?after={cursor}
POST /api/v1/games/{game_id}/commands
```

Команда (пример, не готовый код):

```json
{
  "command_id": "58cf8d8c-047b-49ee-a959-2bf19695a272",
  "kind": "mafia.cast_vote",
  "phase_id": "round-2-voting",
  "payload": {"target_seat": "p3"}
}
```

- Actor берётся **из проверенной сессии**, не из JSON. Доступные `kind` — whitelist per mode/phase/role.
- `POST` возвращает `{game_id, command_id, applied, phase, phase_version, projection}`; ответ адресный. Секретные роли/целевые действия **никогда** не попадают в `GET game` и general events.
- Прежние `expected_revision` использовать только для команд, действительно требующих эксклюзивного изменения configuration/phase; vote/craft/harvest используют иные актуальные fences.
- Если входные данные устарели, 409 содержит **публичный** phase summary и `retryable` без ответов/секретных данных. Retry того же id с тем же телом сначала проверяется по сохранённому receipt.
- `GET /events`: cursor pagination, whitelist видимости public/self/team при разрешённом режиме, retention и pagination hard limit; больше нельзя имитировать Telegram message feed.

## 4.3 Двухсторонний паритет каналов

| Действие | Standalone Browser | Telegram Mini App | Telegram Bot |
|---|---|---|---|
| Вход/профиль | Самостоятельная identity | Проверенный Telegram proof + link account | Telegram provider adapter + account |
| Classic/Photo в личной игре | Да, когда реализован browser-slice | Да | Да |
| Mafia создать комнату/игру | Да, без Telegram | Да | Да, в привязанной комнате/чате |
| Mafia личная роль/действие | Собственный адресный UI | Собственный адресный UI | ЛС/callback, без раскрытия в группе |
| Mafia обсуждение | Внутри комнаты | Внутри комнаты | Опциональный мост сообщений при согласии/контракте |
| Alchemy craft/save | Да | Да | Deep-link/уведомления, полноценный gameplay может оставаться Web |
| Farm grow/harvest/orders | Да | Да | Опциональные уведомления + deep-link, не второй engine |
| История/прогресс/достижения | Из той же PG | Из той же PG | В рамках возможностей Bot UI |

[MUST] Сформировать `docs/engineering/FEATURE_PARITY_MATRIX.md`: режим × сценарий × канал × реализовано × тест × последний принятый commit; обновлять при каждом изменении. Не обещать отсутствующие режимы на публичной главной.

---

# 5. Классический квиз: банк, scoring, расписания

## 5.1 Реальный аудит `data/questions/*.json`

Метод: считаны **все 63 JSON-файла**, всего **6706 записей**; для каждого проверена форма JSON, присутствие правильного ответа в списке `options`, повтор вариантов ответа, а также совпадение текста вопроса внутри той же категории. Проверки не доказывают историческую/научную правильность всех вопросов и **не сверяют live PostgreSQL question_bank с seed JSON**.

### Пять записей с ошибками

| Категория | Индекс (с 1) | Содержание ошибки | Необходимая правка |
|---|---:|---|---|
| `Мода и стиль.json` | 38 | `correct = «Оба варианты верны»`, option = «Оба варианта верны» | Исправить на существующий точный вариант; содержательную трактовку Мэри Куант / Андре Курреж проверить редакторски |
| `Сериалы и телевидение.json` | 69 | Два одинаковых варианта «Прослушка» | Заменить лишний вариант альтернативой, сохранить один правильный вариант |
| `Теории заговора.json` | 60 | `correct = «Тунгусский меорит»` вместо «Тунгусский метеорит» | Исправить опечатку в `correct` |
| `Фольклор и сказки народов мира.json` | 42 | `correct = «Льюсис Кэрролл»` вместо «Льюис Кэрролл» | Исправить опечатку |
| `Фольклор и сказки народов мира.json` | 62 | `correct = «Избушка на курьih ножках»` вместо «Избушка на курьих ножках» | Удалить смешанные латинские символы |

### Четырнадцать повторяющихся формулировок внутри категорий

- **`Искусство.json`: 3 дубля.** Вопрос про «Девушку с жемчужной серёжкой» (#26/#97), «Ночной дозор» (#29/#99), «Опять двойка» (#32/#102). **В последней паре ответы конфликтуют:** «Перов» vs «Фёдор Решетников»; фактически верен Фёдор Решетников. Не удалять запись без осмотра вариантов/пояснений.
- **`Новый год и Рождество.json`: 8 дублей:** индексы пар #29/#53, #33/#57, #34/#58, #38/#62, #44/#72, #83/#99, #85/#101, #75/#103.
- **`Этикет и манеры.json`: 3 дубля:** #4/#58, #18/#63, #31/#64.

**QB-01 [MUST].** Автоматический audit script для JSON и **текущего авторитетного PG question_bank**: schema, 2–10 непустых уникальных `options`, ровно один `correct` после предписанной нормализации, лимиты Bot API, запрещённые control chars, стабильная категория, решения/пояснения. Вывод JSON+Markdown отчёта без автоматического «исправления» фактов.

**QB-02 [MUST].** Разделить `fatal` (пустой текст, нет правильного ответа, повтор опций) и `warning` (дубликаты вопросов, устаревшая информация, похожие темы), затем редакторский review. Каждый устранённый record проходит review источника факта, а не только опечатки.

**QB-03 [MUST].** На import/API хранить category revision/optimistic editing и audit trail: правильный ответ, массив опций и текст решения изменяются согласованно; concurrent editors не теряют данные.

**QB-04 [MUST].** Банк в PG — источник runtime; JSON seed не должен по рестарту перезаписывать живые правки и историю. Проверить dev seed/no-op, export/import dry run, восстановление из snapshot.

**QB-05 [SHOULD].** Добавить дедуп по нормализованному тексту внутри и между категориями, но auto-delete только после human review; учитывать разные формулировки, правильные ответы/пояснения.

## 5.2 Игровые контракты Classic

- Сервер формирует `question_id`, `round_id`, snapshot перемешанных option IDs, дедлайн; correct ID хранится в серверном checkpoint и не утекает до сдачи или закрытия вопроса.
- Ответ одного участника на раунд **один раз** меняет ledger; повтор из Telegram/Mini App получает сохранённый результат. Конкурентные независимые ответы разных участников не конфликтуют.
- Поддержать конфигурации number/time/interval/categories/announce/daily schedule по сохранённым правилам; не переписывать существующую формулу очков без ADR, migration и решения владельца.
- Вопрос отправлен в Telegram poll: веб-ответ фиксируется в общем ledger, **не создаёт фиктивного голоса от пользователя**. Показать честное состояние в UI («ответ принят здесь»; poll может не показать вашу отметку).
- Дедлайн выполняет отдельный worker; при offline клиенте результат приходит после reconnect, без двойного счёта.
- Групповые/личные права: кто может запускать/останавливать, предел параллельных викторин и исключение забаненных аккаунтов — явный policy тест.
- Регрессионная проверка всех режимов выбора категорий, длинных вариантов и объяснений (включая Markdown/HTML edge), восстановление после падения/повторов Telegram.

## 5.3 Фото-квиз: обязательное продуктовое решение

`application/photo.py:171–182` проверяет, что текстовые ответы принимает только `creator_id`; старый групповой photo handler допускает другую пользовательскую модель. **Это не автоматически баг, а риск регрессии**.

**PHOTO-01 [DECISION].** Утвердить два режима: `solo_owner_answer` и, при необходимости, `group_competition`; второй требует раздельных попыток/баллов участников, прозрачного победителя, политики подсказок и дедлайнов. Пока контракт не утверждён, **не изменять** текущую авторизацию ответов наугад.

**PHOTO-02 [MUST].** Прогнать реальный сценарий `/photo_quiz` в группе, где два участника пытаются ответить; сравнить с действующим production контрактом и обсудить с владельцем, что сохраняется.

**PHOTO-03 [MUST].** Медиа: клиент получает только разрешённый файл через защищённый маршрут, hash+format/dimension validation, ни traversal, ни открытого каталога, immutable storage, backup/restore photo catalog + blobs.

**PHOTO-04 [MUST].** Подсказки по серверному времени, попытки с антиспамом, при потере сети не списывать две попытки за один request ID. Ускорение + штрафы сверить с legacy тестами.

**PHOTO-05 [SHOULD].** Качество коллекции: подписи/alt, транслитерация/ё/дефис/регистр, корректное tolerance для почти правильных ответов, поддержка мобильных картинок без лишнего раскрытия правильного ответа.

---

# 6. Alchemy — проверяемые открытия, офлайн, прогресс и безопасность очков

## 6.1 Источники и сохраняемые свойства

Канон `minigames/alchemia-1.0/data.json`, исходники `game.js`, `journey.js`, `style.css`, `sync.js`, SVG `art.svg` и `illustrations/`. `build.py` собирает единую страницу `web/mini_client/alchemy.html`. Исходное содержимое: **431 элемент, 1035 рецептов, 10 категорий, 33 главы, 42 достижения, экспедиции**. Сохранить ID элементов и legacy import. Гостевой прогресс по `account_id`; Telegram по связанному Account/старому `User` в переходный период.

## 6.2 Главный дефект и миграционная политика [P0]

Сейчас `POST /api/mini/alchemy/sync` принимает **сводку** и делает `catalog.known_elements`, а `AlchemyService.sync` выдаёт награды за каждый впервые присланный известный элемент (и главы/achievements). Не требуется доказать рецепт. Тест `test_first_sync_awards_two_three_five...` прямо фиксирует текущую семантику начислений; менять её **с обновлением тестов**, а не обходить тест.

**ALC-01 [MUST].** Разделить виды прогресса:
- `verified`: добыт серверным применением допустимых рецептов / неизменяемой подтверждённой истории;
- `imported_unverified`: поднят из offline/browser legacy JSON, отображается в коллекции, **не даёт** рейтинговых очков, наград и подтверждённых мест;
- `legacy_rewarded`: ранее начисленная историческая награда; при миграции **не пересчитывать/не списывать автоматически**. Решение о корректировке ранее начисленных очков — отдельное письменное согласование владельца.

**ALC-02 [MUST].** Новая подтверждённая операция:

```http
POST /api/v1/alchemy/craft
Content-Type: application/json
Idempotency-Key: <command_id>
```

```json
{
  "catalog_version": "content-hash-or-semver",
  "operand_a": "water",
  "operand_b": "earth"
}
```

Проверки **в одной транзакции**: account status/identity, version catalog, оба verified-доступных операнда или четыре стартовые стихии, рецепт действительно существует, ответ определяется **только на сервере**, already-discovered → нет второй награды, событие/effect/score ledger/achievement идут атомарно. Возвращать `{output_id, first_verified_discovery, awarded, authoritative_progress_version}`.

**ALC-03 [MUST].** Старый `/api/mini/alchemy/sync` временно принимает сводку только для **не рейтингового импорта**/merge; не разрешать повторным `sync` переводить `unverified` → `verified` без проверяемой операции. Когда мобильный клиент обновлён, старый маршрут закрывается/версионируется и тестируется.

**ALC-04 [MUST].** Флаг/ledger provenance: `source=alchemy`, `source_event_id`, `verified=true`, `catalog_version`, `award_kind`. Инварианты: повтор команды → `awarded=0`/cached receipt; один результат из разных клиентов → одна запись; суточный потолок 30 по Москве *для ранее утверждённой Telegram наградной политики*, 2/3/5 за элемент/главу/достижение, цель дня 10 — сохранить без продуктового решения о смене.

**ALC-05 [MUST].** Offline-first: локальная игра работает без сети, хранит очередь `pending_craft_operations` с device command IDs, ordinal и content/catalog version. При появлении сети сервер **валидирует события**, отклоняет impossible chain с объяснением, при этом пользовательский локальный атлас не уничтожается. Конфликты каталога/удалённых ID — явный resolver, не молчаливый merge.

**ALC-06 [MUST].** На новом устройстве после подтверждённого входа восстановить все *verified* открытия и допущенные импортные открытия по account_id; права на рейтинг сохранять отдельно. Отключённая cookie/guest/relink не должна подменять одно сохранение чужим.

**ALC-07 [MUST].** Заменить использование bearer из `localStorage`/`#t=` server-side безопасным handoff; no-login standalone HTML допускается, но не имеет скрытого доступа к наградам. CSP должен поддерживать самодостаточную сборку, исключая внешние скрипты.

**ALC-08 [MUST].** Версии контента: `catalog_version`, deterministically hashed `data.json`, migration alias/renames если когда-либо меняются IDs, режим чтения старого сохранения. `build.py` и `verify_content.py` в CI проверяют граф достижимости, отсутствие дублей рецептов, корректные SVG ids, сохранность marker и source/artifact.

**ALC-09 [SHOULD].** UX «Путь алхимика», цели/серии, категории, длинное нажатие 260 мс на телефонах, wheel/drag категорий мышью, reset/restore с подтверждением и синхростатус: локально / ожидает / синхронизировано / не подтверждено для рейтинга.

### Тесты Alchemy — обязательный минимум

| ID | Сценарий | Ожидаемо |
|---|---|---|
| TA-01 | Authenticated клиент сразу присылает все 431 известных ID в старый sync | 0 новых *verified* открытий; +0 баллов; никакого rank boost |
| TA-02 | Новый аккаунт выполняет корректный первый рецепт двух базовых стихий | Только разрешённый server output; событие/прогресс/награда за первое подтверждение |
| TA-03 | Несуществующая пара/неоткрытые операнды | Отклонение (422/409 по контракту), 0 побочных эффектов |
| TA-04 | 100 повторов одного command ID, включая 10 параллельных | 1 effect, 1 award, одинаковый результат |
| TA-05 | Два клиента одновременно открывают один новый элемент разными рецептами | Одно впервые подтверждённое открытие и одна награда |
| TA-06 | Offline импорт старого локального набора | Коллекция не исчезает; награды не начисляются без verified events |
| TA-07 | Удаление/устаревание контентного ID | Совместимый migration/alias; no silent deletion и no invalid reward |
| TA-08 | Несколько устройств/два аккаунта/гость+Telegram | Изоляция, явное linking, отсутствие передачи чужого прогресса |
| TA-09 | День МСК 23:59 → 00:01 и достижение цели 10 | Потолок и серия дней детерминированы, нет повторов |
| TA-10 | Локальный артефакт пересобран на Linux/Windows | Equal content hash, 431/1035/33/42, нет битых SVG и внешних скриптов |

---

# 7. Async Mafia — полноценная независимая от одновременного присутствия игра

## 7.1 Из текущего прототипа в продукт

Сохранять существующие правила ролей до обсуждения изменений: 4–12 участников; мафия в зависимости от размера, детектив с 5, доктор с 7; лобби/готовность/случайная роль/ночь/день/голосование/финал/реванш. Роли строго адресные. Требуется **новая временная/комнатная и конкурентная модель**, а не просто заменить `90` на `86400`.

## 7.2 Нормативное состояние партии [MUST]

```text
DRAFT -> LOBBY -> STARTING -> NIGHT -> DAY_DISCUSSION -> VOTING ->
                                    |            ^              |
                                    +------------|-- NEXT NIGHT+
                                                  |
                                  FINISHED / PAUSED / INTERRUPTED / EXPIRED
```

Обязательные поля: `room_id`, `game_id`, `host_account_id`, participants/membership snapshot, private role assignments, alive/status, round number, phase_id (уникален за раунд), phase_ends_at UTC, settings snapshot, quiet hours/timezone, AFK policy, vote/action receipts, winning condition, immutable event history, revision per affected domain.

- Настройки стола вводятся **до** старта и копируются в snapshot. Изменить настройки после старта возможно только через отдельную policy/голосование, если это вообще будет разрешено.
- **MAF-01 [MUST].** Продолжительность фаз настраивается и документирована. `[PROPOSED]` пресеты «быстро» (90/180/90 с для обратной совместимости), «вечер» (5/15/5 минут), «асинхронно» (8/12/4 часов), но окончательные диапазоны и quiet hours утверждаются владельцем; никакой пресет не становится implicit default при миграции старой партии.
- **MAF-02 [MUST].** При наступлении дедлайна независимый worker завершает фазу по правилам неполных голосований и отсутствующих действий. Два workers/автопереход + host callback не могут завершить фазу дважды.
- **MAF-03 [MUST].** Ночные действия/дневные голоса принадлежат actor+phase_id; раздельные актёры не конфликтуют из-за общего `lobby.revision`. Повтор актёра: если изменение своего выбора разрешено, последнее подтверждённое до cutoff считается один раз; policy и receipt заданы явно.
- **MAF-04 [MUST].** Решение majority/ties/отсутствующие голоса, doctor, detective и мафии детерминированно тестируется при 4/5/7/10/12 игроках и всех комбинациях AFK; seed random только для теста распределения ролей, production random криптостойкий.
- **MAF-05 [MUST].** Role leakage: general lobby/history/group message логируют только public metadata, личная роль только self, результат детектива только детективу, мафия знает других мафиози только если принято механикой; скрытые события не доходят до публичного SSE/outbox/AI prompt.
- **MAF-06 [MUST].** Discussion внутри приложения: хранение сообщений с правами только активных room members, ограниченные длина/темп, sanitization/escape, moderation, pagination. Решить, могут ли eliminated читать/писать и когда раскрывать роли. Telegram chat может быть optional adapter, не source-of-truth.
- **MAF-07 [MUST].** Lifecycle membership: ready/unready, leave до/после старта, kicked/blocked, host disconnect/reassign, pause/resume limit, AFK strikes, game abandonment/expiry. Решение о замене после раскрытия роли — строгая policy для избегания некорректного преимущества.
- **MAF-08 [MUST].** Game completion and reconnect: все таймеры серверные; вход после закрытой вкладки/смены клиента показывает верные round, role, private actions, election result, финал, историю и реванш без повторной выдачи и утечки.
- **MAF-09 [MUST].** Public UI: лобби, роль, выбор цели, отчёт ночи, список живых, обсуждение, голосование, итог, настройки quiet hours, история/реванш. Telegram callback быстро подтверждается, обработка долгая — отдельная нотификация/refresh.
- **MAF-10 [MUST].** Один game/room, но несколько комнат разных сообществ допустимы. При переходе Telegram→standalone нет изменения места/роли/срока.

### Формальный контракт независимого голосования

Пусть `phase_id=R2-VOTE` и два участника A/B прочитали одну и ту же публичную `state_version=21`. Команды A→p3 и B→p4 **должны обе закоммититься**, если сервер всё ещё находится в `R2-VOTE` и actors имеют право. Последующее изменение состояния не делает выбор B устаревшим. Третья команда после `phase_id=R3-NIGHT` → 409 `phase_changed` без наград/изменений. Один и тот же `command_id` → прежний receipt.

### Тесты Mafia

| ID | Сценарий | Ожидаемо |
|---|---|---|
| TM-01 | 4..12 игроков, случайная роль, ready, старт | Правильная численность ролей, нет чужой роли в общем API |
| TM-02 | Два разных игрока одновременно голосуют с одним старым global revision | Обе команды принимаются при том же `phase_id` |
| TM-03 | Два мафиози, doctor, detective действуют параллельно | Все валидные действия сохранены, итог по deterministic правилу |
| TM-04 | Telegram stop посреди ночи, browser всё ещё открыт | Deadline завершается worker без Telegram, роль/голос не исчезает |
| TM-05 | 2 workers одновременно обрабатывают deadline | Одна phase transition, один outbox intent, нет двойного устранения |
| TM-06 | 1 игрок отсутствует, host AFK, остальные ждут | По политике дедлайнов партия продолжается/закрывается, не зависает бесконечно |
| TM-07 | Вход по старой личной callback-карточке | Нет чужой роли/действия; 409 refresh или безопасный resume |
| TM-08 | Изменение состава, выход/бан/смена host, pause/resume | Права, баланс и таймеры соответствуют утверждённой политике |
| TM-09 | 3 разных комнаты одновременно играют | Независимая история/таймеры/роли, отсутствие cross-room access |
| TM-10 | Обсуждение и night report | Экранирование user input, private/public projections без утечек |
| TM-11 | Рестарт Postgres API/worker и браузера в середине фазы | Та же игра/роль/phase_deadline по сохранённой записи |
| TM-12 | Достижение победы и реванш | Старая история не затирается, новая игра получает новый ID |

---

# 8. UI/UX, каталог из пяти режимов и общий профиль

## UX-01. Истинная модель продуктов [MUST]

Главный экран, общий путь к профилю и навигация должны опираться на один `GameModeCatalog` со стабильными `mode_id`, локализованными заголовками/описаниями, supported channel, capabilities, feature gate/статусом, ссылкой на asset, маршрутом, контекстом room/solo и требованиями к auth. Удалить hardcoded зависимость количества режимов и позиционного layout от четырёх карточек **после** введения tested manifest. Не привязывать игровые правила к цвету карточки.

| mode_id | Название в UI | Тип | Статус публикации |
|---|---|---|---|
| `classic` | «Классический квиз» | Вопросы и ответы | По фактически поддерживаемому каналу |
| `photo` | «Фото-загадки» | Фото и текст | По фактически поддерживаемому каналу |
| `mafia` | «Ночной город» | Социальная скрытая роль | Не показывать как production-ready до TM-01..12 |
| `alchemy` | «Атлас маленьких чудес» | Solo/offline crafting | С разметкой verified/unverified progress |
| `farm` | «Весёлый фермер» | Solo idle/управление ресурсами | Только `coming_soon` до приёмки Farm MVP, кнопка не лжёт о запуске |

**UX-02 [MUST].** Сохранить текущий характер и композицию карточек: первые две **зелёные** (classic/photo), следующие две **коричневые** (mafia/alchemy), широкие иллюстрации с плавной боковой тенью под текст, зеркальные отступы и выравнивание. Для пятой карточки **[PROPOSED]** отдельная природная палитра с мотивом лета/урожая; точную визуальную композицию/asset утвердить, не генерировать placeholder за логотип.

**UX-03 [MUST].** Совы Филиныча достаточно как общего ведущего/маскота: один визуальный/текстовый tone-of-voice, но режимы не должны зависеть от генеративного ИИ для запуска. Убрать устаревший meta/title «только квиз и фото», при этом миграция бренда с `Morning Quiz` на `QuizzyWizzy` должна быть согласована по публичным каналам, deep-links, Telegram display name, URL и assets, **не ломая старые ссылки**.

**UX-04 [MUST].** Три состояния модулей в каталоге: `available`, `coming_soon`, `unavailable/requires_login`. Гость видит явно, какой режим работает без Telegram, как сохранить профиль и что будет при выходе. Запрещены карточки с кнопкой «Играть», которая всегда возвращает 403/404.

**UX-05 [MUST].** Единый профиль: nickname, validated score (по источнику), история и достижения, последние игры, комната, явные привязки, devices/sessions, экспорт, настройка уведомлений и quiet hours, отдельный прогресс Alchemy/Farm. Не смешивать soft currency Farm и очки квиза.

**UX-06 [MUST].** Responsive тесты ширин 320, 360, 390, 430, 768, 1024+; Telegram WebView (Desktop/Android/iOS) и обычный браузер. Проверить safe-area, уменьшение motion, dark/light, озвучивание screen reader, accessibility клавиатуры, фокус, `aria-live`, контраст текста на фотографии, крупные touch-target и зависание loader.

**UX-07 [MUST].** Отображать серверный таймер с учётом clock skew; при offline и background переходе повторно запрашивать state, никогда не трактовать локальный countdown как подтверждение фазы.

**UX-08 [SHOULD].** Analytics ограничить privacy-preserving событиями навигации, старта/финиша/ошибки; по умолчанию не отправлять секретные игровые payload, фото пользователей, bearer и содержимое чатового обсуждения сторонним analytics.

---

# 9. «Весёлый фермер»: обязательная спецификация первого вертикального игрового среза

## 9.1 Scope и продуктовые границы

**Статус:** концепт `docs/engineering/FARM_CONCEPT.md`. Ни один пункт ниже нельзя описывать как уже работающий. Цель MVP: игрок **без Telegram** заводит ферму, сажает культуру, закрывает браузер, возвращается за готовым урожаем, выполняет заказ, получает валюту, улучшает участок; другой вход в связанный аккаунт видит тот же прогресс. Игровой цикл не зависит от периодического клиентского heartbeat.

**[PROPOSED] Базовый product contract — утвердить до реализации:**
- 3 культуры с различными положительными таймерами созревания, стоимостью семян, урожайностью и валовой выручкой (баланс из data-driven конфига); стартовый seed заранее фиксируется тестом.
- 4 стартовых участка, одно доступное расширение; статусы `locked`, `empty`, `growing`, `ready`.
- Инвентарь: `seeds`, `raw_harvest`, `products` с целочисленными неотрицательными остатками.
- Одна **отдельная** игровая валюта, нет покупки за реальные деньги/платного ускорения/случайного pay-to-win.
- Заказы фиксируются сервером с requirements и reward; одновременно ограниченное число активных заказов (значение в настройках).
- Переработка — `[DECISION]` включить как **один** простой рецепт только если будет подтверждена её необходимость для первых заказов. Иначе отложить, чтобы не растягивать первый игровой цикл.
- Одиночная ферма на Account; обмен/соседи, животные, гильдии, конкурсы — **не входят** в MVP.

Не утверждать выдуманные числа роста/стоимости. **FARM-DEC-01:** владелец продукта выбирает на тестовом симуляторе баланс (рост/доход/частота возврата/первое расширение) до `farm_catalog_v1`. После freeze значения живут в данных каталога с версией и test fixtures. Для реализации механизма точные числа не должны быть hardcoded в UI.

## 9.2 Доменная модель / state machine

```text
farm(plot[EMPTY]) + plant(seed_id)
  -> plot[GROWING, planted_at, ready_at, crop_id, harvest_qty]
  -- server_now >= ready_at --> plot[READY]
  -- harvest --> plot[EMPTY] + inventory[produce]+=yield

inventory + deliver(order_id) -> inventory -= requirements;
                                  currency += fixed_reward;
                                  order -> COMPLETED

currency + expand(plot_id) -> currency -= cost;
                              plot LOCKED -> EMPTY
```

- Проверка `READY` производится вычислением `server_now >= ready_at`, а не изменением всех строк ежесекундным таймером. Сервер может отдавать вычисляемую проекцию готовности.
- `harvest` требует текущего владения участком, достаточного времени, неизменного harvested-cycle идентификатора; не выдавать второй урожай даже при повторе из другого устройства.
- `plant` проверяет доступность культуры, `seeds>=1`, состояние `EMPTY`, стоимость, ограничение типа участка. Трата seeds и посадка — атомарны.
- `deliver` проверяет инвентарь и order ACTIVE, расходует материалы один раз, награда фиксирована server-side; недостаток ресурсов → безопасный отказ **без частичного списания**.
- `expand` проверяет целевой locked plot, стоимость, лимит земли. Нельзя использовать клиентский параметр currency/reward/harvest_qty, все расчёты из server catalog и state.
- Отсутствие игрока никогда не уничтожает посаженную культуру в первом MVP; offline recovery без penalty. Возможная порча урожая — отдельная будущая гипотеза, не добавлять незаметно.

## 9.3 DB и API (целевые; в HEAD отсутствуют)

| Компонент | Контракт |
|---|---|
| `farms` | `farm_id UUID`, owner account FK UNIQUE (одна ферма/account для MVP), `catalog_version`, `revision`, `created_at` |
| `farm_plots` | `plot_id`, farm_id, grid_position UNIQUE, `status`, `crop_id`, `planted_at`, `ready_at`, `cycle_id`, expansion stage |
| `farm_inventory` | `(farm_id,item_id) PK`, `qty INTEGER CHECK(qty>=0)`, revision |
| `farm_wallet` / ledger | Виртуальный баланс `INTEGER >= 0`, журнал каждой транзакции `transaction_id UNIQUE`, type, linked command, delta, balance_after |
| `farm_orders` | order UUID, farm ID, requirements/reward snapshot, status, expires_at nullable, completed_at, generation seed/version |
| `farm_actions` | command receipt, farm ID, actor, plot/order/cycle reference, type, result, created_at |
| `farm_catalog` | Seed/crop recipes/timers/yields/prices, checksum/version, safe migration of active plantings |

```http
GET  /api/v1/farms/me
GET  /api/v1/farms/me/catalog
POST /api/v1/farms/me/commands  (Idempotency-Key required)
GET  /api/v1/farms/me/ledger?after={cursor}
```

Допустимые `kind`: `farm.plant`, `farm.harvest`, `farm.order_deliver`, `farm.expand` и `farm.process` только если утверждён. Actor всегда из identity. Для всех ошибок поддерживать единый v1 error contract. Read projection может указывать `{server_now, ready_at}`; клиент вычисляет countdown, но не применяет награду самостоятельно.

## 9.4 Экономика и anti-cheat

**FARM-01 [MUST].** Все балансы серверные и нет отрицательных значений. В конце каждой транзакции invariant `initial + sum(ledger deltas) = current`, `qty>=0` по каждой позиции.

**FARM-02 [MUST].** Тестовый in-memory simulation или deterministic PG integration с 1000 игровых циклов и двумя параллельными устройствами: баланс/семена/урожай не создаются из воздуха, duplicate harvest невозможен.

**FARM-03 [MUST].** Offline readiness: переместить server time на несколько часов/дней, restart API/worker, вернуться; готовность и инвентарь идентичны без background tick.

**FARM-04 [MUST].** Разные игроки полностью изолированы; использование чужого `plot_id`, `order_id`, `farm_id` возвращает 404/403 без разглашения инвентаря.

**FARM-05 [MUST].** Корректная версия игрового каталога: если культура меняет таймер в v2, уже растущие посадки сохраняют `ready_at` и исходный `yield` (snapshot). Уже выполненные заказы не меняют стоимость задним числом.

**FARM-06 [MUST].** Отдельная soft currency и журнал источников/списаний; никакого неутверждённого обмена soft currency на рейтинговые очки/Alchemy achievements.

**FARM-07 [MUST].** UI: удобная сетка 4+ plots, drag/click/touch посадки без обязательной drag-механики, каталог растений, видимый таймер, уведомление о завершении, инвентарь, заказы, расширение, история изменений, понятная ошибка при повторном действии.

**FARM-08 [SHOULD].** Опциональные Telegram-уведомления о готовности только после opt-in, батчированно не чаще установленного лимита и с quiet hours. Отсутствие уведомления не блокирует сбор.

### Приёмочные сценарии Farmer

| ID | Given / When | Then |
|---|---|---|
| TF-01 | Гость первый раз открыл Farm | Созданы account/farm/plots/inventory по каталогу, нет Telegram requirements |
| TF-02 | Plant на `EMPTY` с семенами | Seeds -1, plot `GROWING`, `ready_at` рассчитан сервером |
| TF-03 | Harvest раньше срока | 409/422, без изменения inventory/plot |
| TF-04 | Браузер закрыт на 24 часа и запущен снова | Зрелые участки доступны, без server tick/потери crop |
| TF-05 | Два параллельных harvest одного cycle | Только один прирост inventory, второй idempotent/409 |
| TF-06 | Plant с недостаточными seeds | Ясная ошибка, ни одна запись не изменилась |
| TF-07 | Order исполнен с полным inventory | Списание ровно один раз, wallet+=reward, order `COMPLETED` |
| TF-08 | Одновременно два заказа на одни товары | Только допустимый по остаткам succeeds, нет отрицательного qty |
| TF-09 | Expand locked plot | Сервер списывает цену и открывает ровно один участок |
| TF-10 | 2 аккаунта и guest↔linked Telegram на двух устройствах | Другой аккаунт изолирован, linked аккаунт продолжает одну ферму |
| TF-11 | Catalog v1→v2 при активных посевах | Исходные сроки/yield/заказы сохраняются |
| TF-12 | Потеря HTTP ответа с уже применённой командой | Retry того же ID возвращает первый результат без второго списания |

---

# 10. AI-ведущий и расследование — отдельный, не блокирующий базу слой

**AI-01 [P3].** AI-ведущий сначала только **описательно комментирует** уже подтверждённые события. Текст генерируется из `public event projection`; роль/цель детектива/личные действия мафии никогда не попадут в context постороннего адресата.

**AI-02 [P3].** Если нужна интерактивность, модель предлагает `typed_action` из server-owned каталога: `{kind, actor, phase_id, target, rationale, suggestion_id}`. Сервер проверяет phase/role/rule/limits/nonce; **LLM не исполняет SQL, не назначает победителя и не выбирает скрытую роль**.

**AI-03 [P3].** При timeout/provider failure/invalid proposal работает шаблонный ведущий; gameplay и дедлайн продолжаются. Cost/token/latency budget, tracing без private prompts/PII, prompt-injection тесты.

**AI-04 [P3].** Оригинальное расследование — отдельное ТЗ: один законченный сценарий со стартом, уликами, локациями, угрозой, развилками, разрешёнными действиями и однозначными условиями финала. Не включать в текущие 5 режимов без решения владельца.

---

# 11. Инфраструктура, воспроизводимость, security и выпуск

## INF-01. Single supported runtime [P1]

- Сверить Python 3.11 vs 3.13; после smoke выбрать один основной Python минор (например, 3.13 при совместимости всех компонентов), затем использовать один базовый family/tag и явно поддерживаемые вариации для dev/prod.
- Убрать расхождение `requirements.txt`, `requirements-local-test.txt`, `requirements-local-lock.txt`, `setup.py`: определить один source-of-truth constraints/lock для runtime и test extras; **никакого silent install разных бинарных версий** в production.
- Зафиксировать hash/SBOM dependencies+images; `pip-audit`/OSV, base-image CVE, проверка лицензий. Закрыть GHSA python-multipart и проверить multipart upload/http tests.
- Для CLI-entrypoint запуск `morning-quiz-bot` действительно должен выполнять async main через синхронную функцию-обёртку `asyncio.run`, а не возвращать coroutine (подтвердить smoke в installed wheel).
- `setup.py` не должен содержать ложной лицензии, placeholder репозитория или version string, не отражающую выпущенный артефакт. Проверить, существует ли лицензия; не присваивать MIT без корректного лицензирования.

## INF-02. Compose и default config [P0]

- Production Compose не должен требовать скрытых ручных переключений и не должен предоставлять слабый `POSTGRES_PASSWORD` как допустимый публичный default.
- `postgres` → Alembic migration (one-shot) → `api` + `game-worker` + `telegram` (опциональный) + `admin` (изолирован) + `media backup job` (по расписанию). `depends_on/healthcheck` не заменяет проверку версии схемы.
- Запуск бота с `STORAGE_BACKEND=json` должен отказать **с явной понятной ошибкой** и валидируемым конфигом. В продовом `.env.example` показывать только placeholders и обязательные переменные без ложного JSON режима.
- nginx/HTTPS надо оформить в воспроизводимой конфигурации деплоя или вынести во внешний обязательный reverse proxy с документацией. Не ссылаться на локально неотслеживаемый `nginx.conf` как на существующий source.
- Прописывать bind/dev ports только loopback; production-админка отдельная сеть/домен/VPN и явное разрешение; подтверждение CSP/origin/forwarded headers.

## INF-03. CI и тестовый контур [P1]

Требуемый обязательный PR pipeline:

1. `lint/typecheck`: синтаксис Python, formatting, import boundaries, `node --check` для всех JS; static check проектных hooks.
2. `unit`: domain state machines Classic/Photo/Mafia/Alchemy/Farm; deterministic clock/seed, pure policy tests.
3. `integration`: реальная изолированная PostgreSQL тестовая база (не `morning_quiz_dev` и тем более не prod), Alembic from empty **и** from previous populated revision, `pytest` с `TEST_DATABASE_URL`, concurrency/retry/rollback.
4. `contract`: standalone/Telegram adapter API, authorization, wrong-room, private projections, headers/CSP/CSRF/rate limits, shadow old API if needed.
5. `frontend`: `node --test tests/js/...`, браузерный smoke Playwright/аналоги 320/390/desktop, screenshot diff по заранее утверждённым эталонам. JS syntax-only не закрывает UI.
6. `data`: JSON question QA+PG parity, Alchemy deterministic build/content hash, Farmer catalog validation.
7. `security`: dependency/SBOM, basic malicious inputs, forbidden code patterns, secret scanner, auth fuzz no PII leaks.
8. `backup`: PG dump+media+restore и сравнение count/checksum на disposable DB.
9. `release-evidence`: отчёт SHA, версия БД, команд, timestamps, failed/skipped, ссылки на test artifacts.

**INF-04 [MUST].** При недоступной PostgreSQL тестовой базе runner **падает или явно ставит gate = NOT VERIFIED**; нельзя считать пропущенные PG тесты успешной приёмкой. PR merge blocked при P0/P1 regression/failing mandatory gate.

**INF-05 [MUST].** Git/Codex hooks `scripts/project_checks.py`, `.agents/skills/` полезны и сохраняются, но являются developer feedback и **не заменяют независимую CI**. Нельзя давать им право менять production, стирать файлы, обходить trust.

## INF-06. Миграция production и регламент разрешений [P0]

**В текущем аудите production не читался и не изменялся**; отчёт `PROD-DIVERGENCE-REVIEW.md` и репетиция MQB-007 — исторические, не свидетельствуют о текущем содержимом сервера. Следовательно:

- Сначала **read-only** собрать `git status`, tracked/untracked fingerprints, Python/runtime versions, storage settings (без вывода секретов), текущее состояние сервиса и тестовую статистику; отдельно показать drift.
- Подготовить и **проверить** полный snapshot JSON+media+config/env/service units и исходной PG staging; сохранить секреты в защищённом хранилище, не Git.
- Отключить writers в окне cutover; подготовить upgrade новых миграций до `20261007_0015` и последующих; dry run и проверки fingerprints/counts/active games.
- Rehearsal на **свежем** снимке, затем exact release artifact по SHA. Health/readiness/auth/Classic/Photo/Alchemy/Mafia/Farm по утверждённому scope + Telegram notifications, backup restore/rollback drill.
- Живое переключение production и рассылки **только после отдельного явного разрешения владельца**. Откат после первых PG-записей **не сводится к возврату JSON backup**: нужен план сохранения последующих очков/событий.
- Нельзя выполнять на production `git reset --hard`, `git clean -xfd`, `docker compose down -v`, перезапись боевой БД и `rm -rf` ради скорости устранения дрейфа.

## INF-07. Наблюдаемость и эксплуатационные инциденты

- Dashboard: активные комнаты по режимам, lag worker, просроченные дедлайны, outbox `pending/sending/uncertain`, принятые/отклонённые команды, 409 vs 500, неизвестный итог Telegram, auth anomalies, выгрузка score ledger.
- Alert на зависший game deadline, рост uncertain, `alchemy.unverified_to_verified` попытки, неожиданные изменения баланса, повторные расходы/выдачи, неудачный backup, schema mismatch.
- Runbook разбора каждой тревоги. `uncertain` нельзя blind resend из-за отсутствия idempotency key Telegram; операторы получают status/outbox ID/error type и процедуры ручной сверки.
- Для каждого релиза Canary/staging перед общедоступным запуском, rollback trigger и семантика maintenance.

---

# 12. План поставки: фазы, зависимости и запрет «большого взрыва»

Статус работ в этом разделе — **`NOT STARTED` с точки зрения новой спецификации**, а не отрицание уже существующего кода. Выполнять по dependency graph; параллельны только независимые безопасные worktree/DB/schema. Каждая фаза — отдельный PR/серия PR с наблюдаемой конечной возможностью.

| Этап | Критичные задачи | Пользовательский результат | Exit Gate |
|---|---|---|---|
| **S0 — Rebaseline/противоречия** | Актуальный `git status`, git diff, schema, inventory, тесты, риск-модель, новые ADR; regression snapshot | Упорядоченная единая точка входа для команды | Комплект evidence по текущему SHA; прод не тронут |
| **S1 — Stop-the-line P0** | AUD-001/002/003 + секьюрные токены AUD-004; закрытие rating cheats, dependency drift, deploy defaults | Нет подарочных очков из произвольного `sync`; безопасные config/secrets | TA-01..05, `pip-audit`, Compose clean boot, fresh PG gate |
| **S2 — Независимая identity** | AUD-005/009/010/012; Account↔Telegram verified link; Room/identity migration | Гость создаёт комнату и может восстановить/привязать прогресс | Browser room without Telegram, 2 accounts linked/unlinked, no data loss |
| **S3 — Общий game runtime/worker** | AUD-006/007/008/011/014; isolated worker, idempotency, phase-specific concurrency, bridge removal | Партии не зависят от Telegram и выдерживают параллельность | TM-02/04/05/09, classic/photo parity, TG process stop test |
| **S4 — Alchemy hardening и Classic/Photo parity** | ALC-03..10, QB-01..05, PHOTO-01..05, UI навигация | Единый проверенный прогресс и настоящая игра из браузера | TA-01..10, question QA, фото и квиз end-to-end |
| **S5 — Async Mafia product** | MAF-01..10 + mobile discussion/AFK/quiet hours | Человек может играть не синхронно с остальными | TM-01..12 + 24-hour virtual clock/reconnect tests |
| **S6 — «Весёлый фермер» MVP** | FARM-DEC-01, FARM-01..08, five-card catalog | Законченная одиночная ферма с offline grow | TF-01..12 + UX mobile matrix |
| **S7 — Сведение пяти режимов и pre-release** | Полный профиль, privacy, performance, migration rehearsal/restore, CI, a11y | Пользователь видит согласованный продукт на всех разрешённых каналах | §13 release gates, signed scope, все MUST тесты |
| **S8 — Production cutover** | Отдельное разрешение, свежий backup/import, эксплуатация, мониторинг | Контролируемый запуск заданного scope | Явное GO владельца, зафиксированный SHA, rollback evidence |
| **S9 — AI/сценарные расширения (опционально)** | AI host, расследование, sociale features Farm | Дополнительный качественный контент | Не блокирует S7/S8, отдельный бюджет/тесты |

### Зависимости

```text
S0 → S1 → S2 → S3 → { S4, S5, S6 } → S7 → S8
                              S4 ─┐
                              S5 ─┼─> S7
                              S6 ─┘
S9: только после стабильной базы; не должен создавать скрытых требований к S7.
```

**Важное уточнение объёма:** если владелец захочет **ранний релиз без Farmer**, S7/S8 могут иметь versioned scope из четырёх игр, но карточка Farm обязана показывать честное `coming_soon`; текущая задача по охвату пяти режимов не становится «завершённой», пока TF-01..12 не приняты. Изменение объёма фиксировать в issue/ADR, а не молча выкидывать пятую игру.

---

# 13. Строгий релизный gate и матрица доказательств

## 13.1 Что считается DONE для каждой задачи

- [ ] Source baseline (`commit`, branch, clean/dirty diff) указан.
- [ ] Зафиксированы поведение до/после, область изменения, affected files, rules/API/DB миграции, риск для production.
- [ ] Unit + integration для позитивных, негативных, конкурентных и retry сценариев есть и запускаются в новом изолированном окружении.
- [ ] Состояние/приватность проверены через **все** каналы, которые задача заявляет поддерживаемыми.
- [ ] Миграция проверена на populated snapshot (если есть), backup+restore без потерь, downgrade ограничен/описан.
- [ ] Нет новых fake Telegram updates, JSON runtime writes и дублей наград, token leakage и несогласованной версионности.
- [ ] Документы `docs/INDEX.md`, `docs/engineering/*`, активные `docs/tasks/`, ADR и changelog обновлены без ложного `passed`.
- [ ] Записаны реально исполненные команды и полные результаты тестов (`passed/failed/skipped`), ссылки на JUnit/browser/metrics. Пропущенное и не пройденное остаётся `NOT VERIFIED`.
- [ ] Независимое ревью и устранение P0/P1 замечаний выполнены; owner sign-off нужен для продуктового scope, public launch, массовых изменений данных.

## 13.2 Сквозные acceptance сценарии

| ID | Условие | Проверка | Release blocker |
|---|---|---|---|
| E2E-01 | Чистая dev-копия | `docker compose`/script поднял DB,migrations,API,worker с **нулём секретов в логах** | Да |
| E2E-02 | Гость без Telegram | Регистрация Account, игра в Alchemy, restart API, тот же account/progress | Да |
| E2E-03 | Recovery | Новый браузер/устройство с verified linking/recovery получает прежний Account | Да standalone |
| E2E-04 | Room only browser | 4 browser accounts создают независимую room/Mafia game | Да Async Mafia |
| E2E-05 | Кросс-клиент | Сменить Telegram Mini App ↔ браузер при активной Mafia фазе | Да для заявленного паритета |
| E2E-06 | Telegram выключен | Worker завершает Classic/Photo/Mafia deadline, сохраняет state | Да |
| E2E-07 | Две конкурентные команды | 2 разных участника Mafia голосуют в одну phase, оба приняты | Да |
| E2E-08 | Duplicate same command | 100 повторов и 10 параллельных идентичных команд не удваивают эффект | Да |
| E2E-09 | Collision different game | Повтор command ID у другого game ID → 409, нет чужого cached result | Да |
| E2E-10 | Alchemy cheat | Клиент прислал полный список известных IDs напрямую → нет verified rewards | Да |
| E2E-11 | Alchemy offline+merge | 2 устройства, очередь операций, серверная validation, без потери открытий | Да |
| E2E-12 | Farm no-client grow | Закрыть клиент, увеличить серверное время, вернуться, урожай созрел | Да для Farmer scope |
| E2E-13 | Farm race/ledger | 2 harvest и 2 conflicting orders, balances valid | Да для Farmer scope |
| E2E-14 | Role privacy | Случайный участник и spectator не видят роли/цели/детективный результат | Да |
| E2E-15 | Classic ×2 clients | Одному игроку нельзя дважды начислить за вопрос; другому можно | Да |
| E2E-16 | Photo image permissions | Без адресной авторизации нельзя получить бинарное фото | Да |
| E2E-17 | Question QA | Нет invalid correct/options и утверждённых конфликтующих дублей в seed+PG | Да |
| E2E-18 | Telegram lost response | Unknown outcome помечен uncertain и не дублируется вслепую | Да |
| E2E-19 | User abuse/security | Forged initData, expired guest cookie, wrong Origin, CSRF, XSS, huge multipart, SQL invalid | Да |
| E2E-20 | Release migration | Populate-old-DB → migrations → fingerprints, stats, media links, restore, no data loss | Да |
| E2E-21 | Real clients | Chrome desktop + Android Telegram + iOS Telegram + Telegram Desktop, safe areas/focus/role cards | Да если эти каналы заявлены |
| E2E-22 | Backup + operational | PG/media snapshot restored, game scheduler backlog observed and alarmed | Да |

## 13.3 Результаты аудита и ограничения

**Проверено:** исходники/HEAD; явная архитектурная структура; схемы 0014/0015; код auth/хранения/игр; состав 63 JSON; exact issues банка. **Не проверено:** фактические версии на production, production git/diff/data, запускаемые Docker/PG миграции, собственные API для продовых токенов, результаты `pytest` на данном HEAD, безопасность на живом сервисе, Playwright и Telegram devices, ферма/AI (отсутствуют). Следовательно, нет основания присваивать всей системе `production_ready` или процент готовности.

## 13.4 Источники, откуда начинать работу

- [Правила проекта: AGENTS.md](https://github.com/WeLizard/morning-quiz-bot/blob/main/AGENTS.md)
- [Разработка: DEVELOPMENT.md](https://github.com/WeLizard/morning-quiz-bot/blob/main/docs/engineering/DEVELOPMENT.md)
- [Критерии релиза: RELEASE_CRITERIA.md](https://github.com/WeLizard/morning-quiz-bot/blob/main/docs/engineering/RELEASE_CRITERIA.md)
- [Standalone foundation](https://github.com/WeLizard/morning-quiz-bot/blob/main/docs/engineering/STANDALONE_FOUNDATION.md)
- [Farmer concept](https://github.com/WeLizard/morning-quiz-bot/blob/main/docs/engineering/FARM_CONCEPT.md)
- [Игровые режимы Mini App](https://github.com/WeLizard/morning-quiz-bot/blob/main/docs/MINI_APP_GAMEPLAY.md)
- [Alchemy API/progress](https://github.com/WeLizard/morning-quiz-bot/blob/main/docs/MINI_APP_ALCHEMY.md)
- [PostgreSQL cutover runbook](https://github.com/WeLizard/morning-quiz-bot/blob/main/docs/tasks/MQB-007-production-cutover-runbook.md)
- [Документированное отличие production от dev — ИСТОРИЧЕСКОЕ](https://github.com/WeLizard/morning-quiz-bot/blob/main/docs/tasks/PROD-DIVERGENCE-REVIEW.md)
- [Mafia domain source](https://github.com/WeLizard/morning-quiz-bot/blob/main/domain/mafia.py)
- [Game repository](https://github.com/WeLizard/morning-quiz-bot/blob/main/storage/games.py)
- [Alchemy service](https://github.com/WeLizard/morning-quiz-bot/blob/main/storage/alchemy.py)
- [Public Mini App server](https://github.com/WeLizard/morning-quiz-bot/blob/main/web/mini_app.py)
- [Mini App UI](https://github.com/WeLizard/morning-quiz-bot/blob/main/web/mini_client/app.js)
- [CI/dev compose](https://github.com/WeLizard/morning-quiz-bot/blob/main/compose.dev.yml)
- [Production compose — требует исправления](https://github.com/WeLizard/morning-quiz-bot/blob/main/docker-compose.yml)
- [GitHub Security Advisory: GHSA-2jv5-9r88-3w3p](https://github.com/advisories/GHSA-2jv5-9r88-3w3p)
- [GitHub Security Advisory: GHSA-pp6c-gr5w-3c5g](https://github.com/advisories/GHSA-pp6c-gr5w-3c5g)
- [GitHub Security Advisory: GHSA-v9pg-7xvm-68hf](https://github.com/advisories/GHSA-v9pg-7xvm-68hf)

---

# 14. Codex: инструкция исполнения по задачам

**Не запускать одним единственным огромным промптом реализацию S0–S9.** Координатор сначала читает `AGENTS.md`, `docs/engineering/DEVELOPMENT.md`, `RELEASE_CRITERIA.md`, настоящий `git diff` и этот аудит. Далее берёт **одну законченную пользовательскую вертикаль**, готовит PR + evidence. При изменившемся HEAD пересчитывает риски и проставляет статус каждой находки `open / confirmed fixed / not reproducible / deferred with ADR`.

### Жёсткий контракт для исполнителя

1. **Source:** работать только в явной dev-копии/worktree, не на `Z:` или NAS production. Начинать с `git status -sb`, branch, commit SHA, worktree ownership. Не перетирать чужие изменения.
2. **Scope:** перечислить requirement IDs и затрагиваемые файлы, не добавлять соседние функции «заодно».
3. **Proof first:** перед кодом воспроизвести баг тестом, когда возможно (например AUD-001/AUD-007/AUD-008), и показать ожидаемое падение по контракту; после фикса тест проходит.
4. **Layering:** вся игровая логика — в домене/application, adapters — thin. Новые API только как facade; PG authoritative, Telegram optional.
5. **Safety:** никаких destructive prod команд, конфигов/токенов/внутренних ID игроков в коммитах, массовых уведомлений, real bot calls без разрешения.
6. **Regression:** перед merge выполнить соответствующие тесты, а для релиза полный контейнерный gate + браузер/Telegram acceptance; не выдавать skipped за passed.
7. **Docs:** зафиксировать ADR при смене score policy, API identity, миграции, duration default, social rules. Обновить `docs/INDEX.md`/tasks/report по фактам.
8. **Review:** независимое ревью changed code/authorization/DB transactions/tests. После ревью — обновлённый diff и итог pass/fail/skips.
9. **Done:** deliver report по шаблону ниже, ссылки на код и тесты, оставить незакрытые риски.

**Формат handoff после каждого PR:**

```text
Требования: AUD-/ALC-/MAF-/FARM-/... IDs
Baseline: commit + branch + original git status
Новые коммиты / diffstat:
Поведeние до / после и reproduction:
Архитектурное решение / migration:
Тесты: команда → фактический результат passed/failed/skipped
Сценарии человека/Telegram: что подтверждено, что не проверялось
Безопасность/конкурентность/данные: доказательства
Rollback и совместимость клиента:
Риски/открытые решения:
Следующий допустимый этап:
```

**Рекомендуемая маршрутизация агентов в рамках принятой проектной инструкции:** координатор Sol/medium; ограниченное исследование/механические правки — Luna; реализация и ревью — Sol; высокорисковая миграция идентичности/критический security/concurrency bug — Astra для решения и независимого ревью, затем выполнение обратно Sol. 1–3 исполнителя, без рекурсивной делегации; не делать agent ceremony ради мелких исправлений.

---

# 15. Принципиальные вопросы, требующие owner decision

| ID | Вопрос | Почему нельзя решить только кодом | Предлагаемое действие |
|---|---|---|---|
| DEC-01 | Релиз должен содержать Farmer как работающую пятую игру или допускается early launch 4+`coming_soon`? | Scope, календарь и gate | Зафиксировать в roadmap/ADR; при заявлении «пять готовы» TF-01..12 обязательны |
| DEC-02 | Временные пресеты Mafia, quiet hours, auto-advance, AFK/host policy | Баланс и человеческое ожидание | Утвердить тестовый игровой цикл; async default не наследует 90/180/90 |
| DEC-03 | Групповой photo режим: все отвечают или только создатель | Контракт очков, конкуренции и приватности | Сверить действующий production пользовательский опыт до миграции |
| DEC-04 | Гостевой Account: восстанавливать email/passkey/Telegram link? | Нужно подтвердить владение, предотвратить lost account | Рекомендация: Telegram verified link + recovery mechanism, независимый browser passkey позже |
| DEC-05 | Как поступить с уже выданными очками Алхимии до fix? | Исторические награды могли начисляться по клиентской сводке | **Не отбирать молча**; пометить historical/legacy, решить пересчёт/публичный рейтинг отдельно |
| DEC-06 | Алхимия offline: импортированные открытия учитывать в атласе, но не в рейтинге? | Честность и пользовательский UX | Предложенный раздельный verified/unverified слой, явная маркировка |
| DEC-07 | Базовый баланс Farmer: 3 культуры, длительности, стартовые seeds/plots, цены, заказ, переработка | Геймдизайн, а не технический факт | Freeze `farm_catalog_v1` после короткого симулятора и human playtest |
| DEC-08 | Общие очки: какие режимы на них влияют, а какие изолированы? | Farm currency и Mafia должны не ломать quiz leaderboard | Сохранить Mafia без quiz points; Alchemy по старой политике только verified; Farm soft currency отдельно |
| DEC-09 | Когда включать игровой AI-ведущий | Token cost/privacy/задержки/геймдизайн | После стабилизации core, opt-in, narration-first |
| DEC-10 | Название и внешние ссылки: QuizzyWizzy vs Morning Quiz Bot | Юзернеймы Telegram/URL/SEO/логотип | Одно бренд-решение, миграционная карта deep-links/aliases |

---

# 16. Итоговый критерий завершения всего проекта

**Проект соответствует этой спецификации только когда одновременно верно:**

1. Пять режимов реализованы и имеют по крайней мере один законченный проверенный пользовательский цикл в объявленном канале; Farmer не остаётся карточкой без игры.
2. Standalone браузер имеет Account/Room/Game без Telegram ID, аккаунт восстанавливается/привязывается без потери прогресса; Telegram — дополнительный канал того же сервиса.
3. Состояние и дедлайны живут независимо от Telegram и браузера, любое mutating действие защищено auth, транзакцией и idempotency.
4. Рейтинговые награды происходят только из проверенных серверных событий, исходные клиентские сводки и offline import не позволяют их накрутить; история игроков не стёрта.
5. Async Mafia позволяет играть в разные моменты времени, переживает AFK/host disconnect/restart, сохраняет секретность и однозначно завершается; не требует постоянного присутствия всех участников.
6. Classic/Photo имеют сохранённый функциональный паритет, вопросы/медиа прошли QA; 5 ошибок исходных вопросов и 14 повторов обработаны с revision/audit trail.
7. Farm имеет точный учет семян/урожая/валюты/заказов, доказанный offline growth, двойной сбор и отрицательные балансы невозможны.
8. UI согласован для 5 режимов, отображает capabilities, не вводит гостей в заблуждение, работает на мобильных/десктопных устройствах и доступен с клавиатуры.
9. Security/PG/CI/backup/restore/телеметрия покрыты свежими test artifacts; все P0/P1 закрыты, нет критических skipped.
10. Production переход — исключительно отдельный подписанный release decision после rehearsal и готового rollback, без копирования dev/data поверх работающего сервера.

**Вердикт данного аудита:** `NOT RELEASE READY AS A FIVE-GAME STANDALONE PLATFORM`. Это не оценка качества личности разработчиков и не заявление о текущем старом production. Это строгое обозначение несоответствия кода `aeeab2b...` заявленной целевой спецификации. Основа для поэтапной реализации имеется; основные риски и проверяемые выходы перечислены выше.
