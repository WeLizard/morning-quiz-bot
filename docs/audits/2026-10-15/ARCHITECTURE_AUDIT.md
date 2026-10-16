# Архитектурный аудит QuizzyWizzy — 2026-10-15

Ревизия: `fce2b60` (origin/main, песочница). Код не менялся. Читалась чистая копия `git archive fce2b60`; чужие незакоммиченные правки рабочего дерева в выводы не входят, кроме явно отмеченных мест.
Статусы: **[чтение]** — проверено по коду; **[запуск]** — воспроизведено тестом; **[предп.]** — предположение, не проверено.
Независимая перепроверка пунктов 3–9 топ-10 выполнена отдельным агентом; итоги и поправки — в §6. Формулировки топ-10 ниже уже исправлены по её результатам.

---

## 1. Коротко для Ильи

### Карта «ядро → модули»

| Компонент ядра | Реально общий? | Кто обходит |
|---|---|---|
| PostgreSQL + одна цепочка alembic | да | ферма описывает таблицы в своём модуле, `alembic/env.py:12` импортирует qw_farm |
| `games / game_commands / game_events / game_deadlines` | да для Classic, Photo, Mafia (и Room-вариантов) | ферма и Алхимия не используют |
| Outbox уведомлений | да для Mafia, Classic, Photo | диспетчер живёт в `handlers/mafia_handlers.py`; Wisdom и объявления шлются напрямую |
| Проверка initData (`web/mini_auth`) | да, одна функция | — |
| Principal / авторизация | номинально: 2 потребителя из ~80 маршрутов | комнаты и Алхимия на guest-cookie, `/api/mini/*` на Telegram user_id |
| Квитанции идемпотентности | нет: 4 хранилища | Алхимия ×2, ферма |
| Леджер очков и наград | нет | Алхимия пишет `users.global_score` напрямую |
| Origin/CSRF, rate limit | дублируются | ферма ставит свою middleware |
| Telegram-адаптер | не единственный | Mini App сам ходит в Bot API (`getChatMember`) |
| Mini App shell (SDK, safe-area, fullscreen, тема, навигация) | нет | у фермы свой мост, у Алхимии моста нет вовсе |
| Контракт модуля | отсутствует | ферма монтируется хаком с перестановкой маршрутов |

### Поправки к исходным тезисам
- У фермы **нет своих серверных сессий и разбора initData**: `qw_farm/integration.py:108-130` вызывает ядровой `web.principal.resolve_principal`. Дублированы клиентское восстановление сессии, origin/CSRF, rate limit, приглашения и квитанции.
- Synthetic `telegram.Update` в Mini App **нет** (ADR-010 выполняется). Он остался в Telegram-адаптере: `modules/telegram_menu.py:21-31`.
- Общий rate limit фермы с пустым секретом не опасен: при включении без секрета ≥32 байт `qw_farm/rate_limits.py:66-67` падает сразу.
- Worker дедлайнов на песочнице есть (`mqb-game-worker`), но его юнит не лежит в репо: в репо он описан только в `compose.dev.yml:95-97`.

### Топ-10 костылей по риску

1. **Тестовый контур не воспроизводим.** Результат зависит от интерпретатора, от грязного дерева и от того, кто последним мигрировал общую тестовую БД (см. §3.5). Пока это так, любой вынос в ядро нечем проверить.
2. **Репо не самодостаточно.** `data/system/streak_achievements.json` под `.gitignore:74`, но его читает `web/mini_app.py:246`. Из чистого checkout ачивки серий молча пустые [запуск: `test_mini_app::test_achievements_projection…`]. То же у `modules/openrouter_client.py` (`.gitignore:115`, тихий `ImportError` в `handlers/wisdom_scheduler.py:29`) и у юнитов деплоя.
3. **Shell не владеет Telegram-окружением** *(перепроверено, уточнено)*. CSP фермы SDK разрешает (`qw_farm/api.py:14`), но загрузка закрыта условием и проверяется один раз: SDK грузится только при `identity=telegram` или `tgWebApp` в URL (`qw_farm/static/telegram.js:50-51`, `app.js:1163`). Если `mode` приходит позже из ответа `/start` (`app.js:340`), SDK уже не загрузится. Переход идёт через `location.assign`, поэтому в fullscreen шапка уходит под системную строку. Алхимия SDK не грузит вовсе: её CSP `script-src 'unsafe-inline'` (`web/mini_app.py:398-401`) запрещает даже `'self'`. Сессию `mqb_mini` она не продлевает, и через 900 с показывает «Сессия истекла» (`alchemy.html:32277`).
4. **Одна политика origin, проверенная дважды, и ровно один допустимый origin** *(перепроверено, подтверждено)*: `web/mini_app.py:333-357` и `qw_farm/api.py:121-126`; три разных CSRF-заголовка. Исключение для loopback и контейнера есть только в ядре. На своём стенде запрос через docker-прокси без `MQB_DEV_CONTAINER=1` получил 400 «Недопустимый адрес сервиса» [запуск]. Это блокер для второго домена и для переездов.
5. **Principal номинален** *(перепроверено, уточнено)*. Principal используют 9 маршрутов из 110: 8 маршрутов фермы и `POST /api/account/address-form`. Остальные выбирают авторизацию по каналу: комнаты — `guest_store.authorized`, Алхимия — свой `GuestAccounts`, `/api/mini/*` — Telegram `credential`. Привязка и слияние аккаунтов не доходят до комнат и Алхимии.
6. **У очков нет общего леджера; Алхимия пишет `users.global_score` без событий** *(перепроверено, уточнено)*. Обходить нечего: общего леджера очков нет. Алхимия ведёт свой агрегат и прибавляет очки к `users.global_score` (`storage/alchemy.py:377-381`). Гостю и привязанной браузерной сессии награда 0 (`:345-353`). Уже сейчас админский сброс обнуляет `global_score`, но не трогает `alchemy_progress.points_total` (`storage/admin_actions.py:314-319`). Скрытый риск: `recompute_user_totals` сотрёт очки Алхимии. `chat_id=0` — штатное соглашение, не костыль.
7. **Нет контракта модуля.** Все игры объявлены в одном `create_app` (`web/mini_app.py:223-2101`, около 2100 строк). Ферма переставляет маршруты ядра (`qw_farm/integration.py:149-154`). Outbox-kinds и дедлайны — жёсткие switch'и (`handlers/mafia_handlers.py:383-385`, `application/game_deadlines.py:7-74`).
8. **Четыре хранилища идемпотентности** с разным скоупом ключа *(перепроверено, подтверждено)*. `game_commands.id` и обе таблицы Алхимии используют глобальный `String(64)` PK, только `farm_receipts` скоупится по аккаунту. Префикс ставится условно: `guest:` при длине ≤58 (`web/mini_app.py:797-799`), `mini:` при ≤59 (`:1864-1866`). У ключей Classic/Photo префикса нет совсем, а символ `:` разрешён. Пересечение даёт ложный 409, но не утечку чужого результата.
9. **Навигация не единая.** В Алхимии нет выхода в меню и нет BackButton. В «Ночном городе» кнопка внизу, у гостя их две. На ферме BackButton может обойти подтверждение выхода из мини-игры [чтение, NAV-6].
10. **Мёртвый легаси-контур выглядит живым**: `handlers/quiz/`, PG-ветка `handlers/quiz_manager.py:147-148` делает легаси-путь недостижимым, `modules/photo_quiz_manager.py` (1130 строк), JSON-роуты `web/main.py` за 501. CLAUDE.md называет эти пути активными, и правки уходят в код, который не запускается.

### Что чинить первым
1. Герметичный gate (задача T1): своя БД или схема на прогон, зафиксированный интерпретатор, обязательные файлы в git.
2. Единый Telegram-мост и launcher модулей в shell (T3), затем единое меню настроек (T4). Это даст видимый пользователю эффект.
3. Одна граница периметра: список origin, один CSRF, квоты в PG (T5).
4. Principal как единственная зависимость (T6), затем леджер и квитанции (T7), затем контракт модуля (T8).

---

## 2. Реестр находок

### 2.1 Дублирование функций ядра в модулях

**FE-1. Условная загрузка SDK на ферме** [чтение; механизм подтверждён исходниками SDK]
- Доказательства: `qw_farm/static/telegram.js:50-51` — `seemsTelegram = …includes('tgWebApp') || window.Telegram?.WebApp?.initData`. На странице фермы нет `<script>` SDK (`qw_farm/static/index.html:8`), поэтому `initData` на этой проверке всегда ложно.
- `force = mode==='telegram'` (`qw_farm/static/app.js:1163`), а `mode` берётся из `?identity=` (`app.js:39`).
- Кто строит URL фермы:
  - `web/mini_client/app.js:849` — `?identity=guest`, в том числе для Telegram-пользователя, выбравшего гостя (`app.js:686, 704-718`);
  - `app.js:957` — `?identity=telegram`;
  - `app.js:93` — приглашение;
  - `qw_farm/sharing.py:33` — ссылка без `identity`.
- SDK умеет восстанавливать initParams из `sessionStorage` (`__telegram__initParams`), но гейт не даёт ему загрузиться. Вместе с SDK не вызываются `--safe-top=0` (`style.css:27`), `expand`, `disableVerticalSwipes` и BackButton.
- В рабочем дереве уже лежит второй костыль: `storedTelegramParams()` и жёстко заданные отступы 47/28 px.
- Риск: высокий. Правильное место: shell всегда грузит SDK на всех страницах (`/app`, `/app/farm`, `/app/alchemy`) и отдаёт общий модуль `tg-bridge`.

**FE-2. Три разные реализации Telegram-моста** [чтение]
- Shell: `web/mini_client/telegram-ui.js:5-48` (события safeArea, contentSafeArea, viewport, themeChanged), CSS-переменные `--tg-safe-area-inset-*`. SDK сам выставляет такие же переменные, т.е. shell дублирует SDK.
- Ферма: `qw_farm/static/telegram.js:57-74` — свои переменные `--tg-safe-top`, `--app-height`, фиксированные цвета, своя кнопка fullscreen (`app.js:1080-1087`).
- Алхимия: только `env(safe-area-inset-top)` до 760 px (`minigames/alchemia-1.0/style.css:16`).
- Риск: средний. Правильное место: `tg-bridge` — `boot({onBack,onResize})`, `isTelegram()`, `fullscreen()`, тема и общие токены `--safe-*`.

**FE-3. Алхимия не знает о Telegram** [чтение]
- Открывается через `location.assign('/app/alchemy?mode=…')` (`web/mini_client/app.js:825, 849`). Нет `ready`, `expand`, BackButton, нет ссылки назад.
- CSP `script-src 'unsafe-inline'` (`web/mini_app.py:398-402`) не пускает SDK.
- Риск: высокий.

**FE-4/5. Стык shell → модуль теряет контекст** [чтение]
- Переход — полная навигация (`app.js:93-100, 825, 849, 957`), назад тоже полная (`qw_farm/static/app.js:1163` → `/app`).
- Теряются выбор входа (`mqb-auth-choice`), тема (`mqb-ui-preferences`) и SDK.
- Параметр называется по-разному: `?identity=` у фермы, `?mode=` у Алхимии (`web/mini_app.py:476-479`).
- Правильное место: launcher модулей в shell с одним контрактом (`return_to`). Активную идентичность решает сервер.

**FE-6. Ферма дублирует клиентские сессии** [чтение; последствие — предп.]
- `qw_farm/static/app.js:195-225`: свой renew/resume, проверка `auth_date ≤ 300 с`, гонка SDK 1500 мс, `RENEW_AFTER` 8 мин (`:1164`).
- Маркер выхода shell `mqb-telegram-logged-out` ферма не читает (grep — 0 совпадений). Возможен тихий повторный вход после logout [предп.].

**FE-7. Ключи localStorage без реестра** [чтение]
- Неявный контракт `qw-farm.launch-consumed`: читает shell (`web/mini_client/app.js:93-100`), пишет ферма (`qw_farm/static/app.js:343`).
- id гостя Алхимии подставляется в HTML заменой маркера (`web/mini_app.py:479-486`).

**BE-5. Origin и CSRF дважды** [чтение; порядок middleware — предп.]
- `web/mini_app.py:333-357` — `origin == settings.origin`, заголовки `x-guest-csrf` и `x-mini-csrf`.
- `qw_farm/api.py:121-126` — та же проверка и заголовок `x-qw-farm`.
- `MiniAppSettings.origin` — одна строка (`web/mini_app.py:31, 41-47`). Исключение для loopback есть только в ядре.
- Риск: высокий. Правильное место: `web/boundary.py` — `OriginPolicy(frozenset)` и одна middleware.

**BE-6. Три rate limiter'а, ядро знает префикс фермы** [чтение]
- `RequestLimits` и `startswith('/api/farm/')` — `web/mini_app.py:153-180, 360-363`.
- Локальный лимит фермы — `qw_farm/api.py:12, 127-144`.
- Общий лимит в PG — `qw_farm/rate_limits.py:43-158`, только у фермы. Остальные лимиты, включая попытки пароля (`storage/account_passwords.py:75-107`), живут в памяти процесса и умножаются на число воркеров (LG-15).
- Правильное место: `Quota.consume(scope, subject)` на общей таблице.

**BE-11. Ферма дублирует гостевой гейт и расходится с ядром**: `web/mini_app.py:509-511` против `qw_farm/integration.py:112-113`; флаг `dev_guest_access` в ферму не передаётся (`web/mini_app.py:2103`). [чтение]

**BE-12. Свои приглашения фермы.** Код приглашения равен `farm_id` (`qw_farm/service.py:46-62`). Нет отзыва и срока, ID публичных ферм видны списком (`qw_farm/persistence.py:215-222`). Deep-link собирает модуль (`qw_farm/sharing.py:30-49`). [чтение; злоупотребление — предп.]

**BE-2. Алхимия: две API-ветки и свой резолвер Telegram → Account** [чтение; сценарий — предп.]
- `web/mini_app.py:1193-1327`.
- `storage/alchemy.py:485-499` создаёт `Account` без `AccountIdentity` в обход `storage/telegram_accounts.py:13-59`.

### 2.2 Обходы ядра

**BE-3. Алхимия пишет общий счёт напрямую** — `storage/alchemy.py:345-353, 377-381, 589-598`. `recompute_user_totals` (`storage/repositories.py:257-270`) этих очков не знает. [чтение]

**BE-7. Mini App сам ходит в Bot API** — `web/mini_app.py:98-150` (httpx `getChatMember`, своя классификация ошибок). Деактивирует чат (`:411-420`), свой токен `MINI_APP_BOT_TOKEN`. [чтение]

**BE-10. Ферма читает банк вопросов Classic сырым SQL** — `qw_farm/integration.py:22-80`. [чтение]

**BE-9. Таблицы фермы вне `storage/models.py`** — `qw_farm/persistence.py:16-62`, регистрация на лету в `integration.py:83-86`.
- Миграции ядра зависят от импорта модуля (`alembic/env.py:12`), ревизии `qw_farm_010/011` вставлены в основную цепочку.
- Ферма угадывает схему: `if 'archived' in accounts.c` (`persistence.py:95-97`). [чтение]

**BE-15. Логика Алхимии в storage, вызовы приватных методов между слоями** — `application/alchemy_journey.py:9, 39`, `storage/mini_app.py:479`, storage импортирует `MiniAppError`. [чтение]

**BE-16/LG-12. Synthetic Update в Telegram-адаптере** [чтение]
- `modules/telegram_menu.py:21-31` (`as_command`), используется в `handlers/config_handlers.py:1589` и `handlers/quiz_manager.py:2163`.
- Dev-копия всей сборки бота: `modules/dev_runtime.py:100-175, 268`.

**LG-13. Побочные эффекты мимо outbox** [чтение]
- Объявление старта Classic (`handlers/quiz_manager.py` ~391-404) уходит после коммита.
- Wisdom: `handlers/wisdom_scheduler.py:164`, без идемпотентности.
- Fire-and-forget запись `data_manager.py:64-87`.
- Poll из outbox отправляется без `TelegramRateLimiter` (`handlers/mafia_handlers.py:513`).

**BE-13/LG-2. Outbox и дедлайны — switch'и в файле Мафии** [чтение]
- `handlers/mafia_handlers.py:372-424`, kinds в `:383-385`, `run_repeating` в `:618`.
- `application/game_deadlines.py:7-74`.
- Забытый kind навсегда остаётся `pending`.

**LG-6. Ачивки и стрики не доходят в Telegram-пути v2** — `handlers/poll_answer_handler.py:88` возвращается до легаси-рассылки; kind для milestone нет. [чтение]

**LG-14. Один экземпляр бота держится на kill по командной строке** — `bot.py:190-285`, рядом флаг `MQB_SKIP_DUPLICATE_KILL` (`bot.py:152`). Правильное место: lease в БД. [чтение]

### 2.3 Двойные источники истины

**LG-3. Мёртвый легаси-контур** [чтение]
- `handlers/quiz/` (6 файлов, нигде не импортируется).
- `handlers/quiz_manager.py:147-148` делает ниже лежащий путь недостижимым.
- `modules/quiz_engine.py` (вызывается только из мёртвого кода), `modules/photo_quiz_manager.py` (снаружи используются 3 члена).
- `web/main.py` (около 4500 строк JSON-роутов за 501, `web/postgres_admin.py:520-530`).
- `utils.py:385, 422` нигде не вызываются.
- `STORAGE_BACKEND=json` разбирается в `app_config.py:124-126`, но `storage/startup.py:16` его отвергает.

**LG-4. DataManager: тихие no-op при PG** — `save_user_data`, `save_chat_settings` и др. молча возвращаются; `get_*_statistics` (`data_manager.py:1490-1520`) читают JSON безусловно. [чтение]

**LG-5. Конфиг правил игры читают 4 загрузчика** [чтение; расхождение — предп.]
- `modules/score_manager.py:43`, `web/mini_app.py:241-269`, `application/room_classic.py:23-43` (без бонусов), `web/postgres_admin.py:97`.
- Слияние настроек чата: deep (`data_manager.py:1332`) и shallow (`application/classic_selection.py:75`, `web/mini_app.py:1555-1557`, запасное значение 5 против 10).

**LG-7. Две модели активной сессии** (`quiz_sessions` и `games`): `storage/category_statistics.py:25-34`, `storage/admin_actions.py:112`. [чтение]

**LG-8/9. Кэши BotState грузятся один раз**: меню категорий из `state.quiz_data` (`bot.py:386`), выбор вопросов из БД; прогрев всех чатов в `storage/runtime.py:109-168`. [чтение]

**LG-10. Статистика категорий в двух местах** — блоб `system_states` и `chats.category_statistics` (`storage/category_statistics.py:78-99`), читатели расходятся; общий `FOR UPDATE` на один блоб. [чтение]

**LG-11. Расписания** [чтение]
- Источник — БД, исполнение — память бота, два движка: JobQueue и `AsyncIOScheduler` (`handlers/wisdom_scheduler.py:47`).
- `daily_schedules` пишется, но не читается (`storage/settings.py:123-131`).
- Нет журнала запусков.

**LG-18. Два реестра очков**: `chat_members` против game state и `ClassicAccountAnswer`. [чтение]

**BE-14. Чатовые и комнатные копии сервисов**: `application/room_classic.py`, `application/room_photo.py` рядом с `classic.py`/`photo.py`. Правила домена общие, application-слой дублирован. [чтение]

**BE-4. Квитанции** — `storage/models.py:354-379` (`game_commands`), `:724-762` (Алхимия ×2), `qw_farm/persistence.py:30-34`. [чтение]

**BE-17. ADR-011 устарел.** `docs/decisions/ADR-011-game-substrate.md:44-47` говорит, что Classic и Photo не на outbox, хотя `application/classic.py:89-103` и `application/photo.py:82-110` уже на нём. [чтение]

**ENV-1. Dev-окружение рассинхронизировано** [запуск]
- `morning_quiz_dev` на 0029, `morning_quiz_test` на 0031 (незакоммиченная миграция рабочего дерева), fce2b60 ждёт 0030.
- Локальный mini-app в restart loop (schema gate). Наблюдение на 15.10; БД не трогала.

### 2.4 Стыки ядро ↔ модули
FE-1, FE-3, FE-4, FE-5 (см. выше), плюс BE-8: ассеты модуля прописаны путями в ядре (`web/mini_app.py:324-326, 378, 500`), флаги читаются в двух местах (`QW_FARM_ENABLED`: `qw_farm/integration.py:91` и `application/game_catalog.py:49`).

### 2.5 Навигация между модулями (по запросу Ильи)

Сводка по коду; скриншоты в `screens/` сняты на локальном dev с рабочим деревом.

| Модуль | Назад / в меню | BackButton | Своё меню настроек |
|---|---|---|---|
| `/app` | вкладки снизу, бренд → home (`web/mini_client/app.js:1881`) | показывается вне home (`app.js:1849`); обработчик `:655` прыгает в home, минуя родителя (NAV-4) | страница «Настройки» (`app.js:1605`) — админские настройки чата; SettingsButton ведёт туда (`telegram-ui.js:28`) |
| Гость `/app` | нет | не работает: условие `state.authenticated` (`app.js:655`) (NAV-5) | нет |
| Classic / Photo | «К играм» сверху (`play-ui.js:88`); «Завершить раунд» внизу (`:312-335`) | дублирует «К играм» | «Настройки квиза» отдельной кнопкой (`play-ui.js:141`) |
| Мафия / «Ночной город» | «К играм» **внизу** (`app.js:1526`); у гостя ещё «К комнатам» сверху (`:1287`), обе ведут в одно место (NAV-2) | в home | нет |
| Ферма | выход только во вкладке «Настройки»: «На главную» и «В профиль» — дубль (`qw_farm/static/app.js:763, 1050-1064`) (NAV-3) | всегда виден; не учитывает мини-игры и обходит их подтверждение выхода (`app.js:1163` против `tractor_game.js:300-302`) (NAV-6, высокий) | вкладка рельса (`app.js:759`); ⛶ и ☷ в шапке дублируют пункты |
| Алхимия | **выхода в меню нет** (NAV-1, высокий) | нет SDK | шестерёнка в шапке (`shell.html:43`): звук, анимации, экспорт, сброс (`game.js:461-464`) |

Скриншоты *(пересняты вечером 15.10 на изолированном стенде чистого fce2b60: своя сеть, свой PostgreSQL, миграции с нуля до 0030, гость; общий dev не трогали)*:

| Файл | Что видно |
|---|---|
| `nav-home-390.png`, `nav-home-1280.png` | Меню гостя. В шапке нет навигации; карточки Classic и Photo со «Скоро» (комнатные режимы выключены флагами) |
| `nav-farm-390.png` | Реальная сцена фермы. На экране нет ни «назад», ни «на главную»; сверху монеты, уровень, ⛶ и ☷ |
| `nav-farm-1280.png` | Левый рельс из 13 вкладок, «Настройки» среди них. Выход в меню только внутри «Настроек» |
| `nav-farm-settings-390.png` | «Ещё» → «Настройки» (нижний лист): пункт «На главную QuizzyWizzy» — сейчас единственный путь из фермы в браузере |
| `nav-mafia-390.png`, `nav-mafia-1280.png` | Лобби «Ночного города» гостя: «К комнатам» сверху на всю ширину, «К играм» внизу за пределами экрана — подтверждает NAV-2 (две кнопки в разных местах) |
| `nav-alchemy-390.png`, `nav-alchemy-1280.png` | Шестерёнка есть, пункта «в главное меню» нет (NAV-1); сняты днём на dev, код Алхимии в рабочем дереве не менялся |
| `nav-classic-390.png`, `nav-photo-390.png` | Старые кадры с dev (рабочее дерево), экран загрузки — **не доказательство**. Комнатные Classic и Photo на стенде выключены (`MQB_ROOM_*_ENABLED=0`) |

Консоль на стенде: ожидаемые 401 до входа; 404 на `/api/dev/info`; предупреждения SDK «not supported in version 6.0» вне Telegram (shell грузит SDK и в браузере). Поведение внутри Telegram и в fullscreen скриншотами не проверено — нужна ручная проверка на устройстве.

### 2.6 Мёртвый код, заглушки, флаги [чтение]
- TODO/FIXME в продовом коде: 0.
- Временные решения: `web/main.py:4351` (метрики из лог-файла), `state.py:314`, `app_config.py:19-21` (заглушка `load_dotenv`), `modules/dev_runtime.py:91`.
- Неимпортируемые модули:
  - `handlers/quiz/*` ×5;
  - `modules/developer_notifier.py` (документация `docs/DEVELOPER_NOTIFICATIONS.md:109,115` вызывает несуществующий `set_developer_notifier`);
  - `sys/maintenance_fallback.py` (побайтная копия корневого);
  - `create_full_backup.py`;
  - `main.py` (альтернативная точка входа, только `compose.dev.yml:44`).
- Флаги:
  - `MINI_APP_RUNTIME_ENABLED` (`web/mini_app.py:230`) нигде не задаётся — мёртвый;
  - `QW_FARM_SHARED_RATE_ENABLED` (`qw_farm/integration.py:97`) — переходный;
  - `MQB_DEV_GUEST_ENABLED`, `MQB_DEV_RUNTIME` — dev-флаги в продовых пакетах;
  - `TELEGRAM_PROXY_URL` и `TELEGRAM_PROXY` — два имени одной настройки (`app_config.py:115-116`);
  - `STORAGE_BACKEND=json` — фактически мёртвая ветка.
- `address.js` побайтно продублирован в `web/mini_client` и `qw_farm/static` (намеренное зеркало, но это тоже дубль shell).

---

## 3.5 Расхождение тестов (23 против 51)

| Прогон | Среда | Итог |
|---|---|---|
| main-сессия | docker `morning-quiz-dev:local`, чистый HEAD, `Test-LocalMilestone` (пересоздаёт `morning_quiz_test`) | 1378 passed / 23 failed |
| сессия авторизации | **системный** Python 3.13: PTB 21.7 без `[job-queue]`, нет `apscheduler` (`requirements.txt:1` требует `[job-queue,socks]==22.8`); грязное рабочее дерево | 108 failed / 1311 passed; перезапуск этих 108 → **51** failed / 57 passed (зависимость от порядка); те же 51 на чистом HEAD тем же Python → 51 failed |
| этот аудит, без БД | `.venv-local` (PTB 22.8), чистый fce2b60 | 21 failed / 980 passed / 400 skipped |
| этот аудит, docker + БД | чистый fce2b60, общий `morning_quiz_test` на 0031 | 1367 passed / 33 failed / 1 skipped |

«51» — это не полный прогон, а перезапуск 108 упавших, сделанный не тем интерпретатором [запуск: `test_classic_recovery` падает с `RuntimeError: To use JobQueue, PTB must be installed via "python-telegram-bot[job-queue]"`].

Разбор 33 падений docker-прогона:
- **20 — тесты фермы устарели относительно каталога или фикстур** [запуск]:
  - `test_farm_crops_r9` ×8: каталог изменился, например `KeyError 'zucchini'`;
  - `test_farm_chains_r5` ×4: `28 <= 24`, `436 <= 400`;
  - `test_farm_minigames` ×4: фикстура `{'coins':0,'inventory':{}}` без `xp`, а `qw_farm/minigames.py:29` его требует; реальные фермы `xp` имеют;
  - `test_farm_home_projects` ×2: версия `3 == 2`;
  - `test_farm_fields_r9`: 1 в docker, 2 без БД — `manual_finish…` нестабилен;
  - `test_farm_queue_r9` ×1.
  - Нужна ревизия владельцем фермы: обновить ожидания или откатить каталог.
- **10 — окружение, не код** [запуск]: `PostgreSQL schema revision mismatch: current=0031, expected=0030`. Изолированная схема тестов использует `search_path "<schema>",public` (`tests/local_database.py`), а schema gate видит `public.alembic_version`, который поднят до 0031 чужой незакоммиченной миграцией. Падают: `admin_actions`, `admin_profiles`, `dev_parity`, `photo_upload`, `postgres_admin_ui` ×2, `postgres_members`, `postgres_reads_settings`, `schedule_sync::admin_schedule_patch`, `startup_contract`.
- **1 — репо не самодостаточно** [запуск]: `test_mini_app::test_achievements_projection…` — нет `data/system/streak_achievements.json` в git.
- **1 — тест миграции фермы 0028**: `farm_states does not exist` при создании `farm_invites` в изолированной схеме. По заметке main-сессии зависит от порядка; здесь падает и отдельно, на загрязнённой БД. Причина не выяснена.
- **1 — `test_schedule_sync::test_inactive_or_deleted_chats_lose_jobs`**: `_known_chats` после удаления CHAT содержит `{900000000004, 900000000005}`. Это другие чаты из `seed`; код (`modules/schedule_sync.py:26-40`) их законно помнит. Вероятно, устарело ожидание `assert not sync._known_chats` [предп.].

Локальный Windows-прогон с БД оборвался на 1400/1401 при перезапуске сессии; около 37 падений восстановлены только по позиции символов, поэтому как доказательство не используются.

JS (`node --test tests/js/*.test.cjs`, Node 24.5): 235 pass / 17 fail [запуск].
- Все 17 — vm-slice тесты, которые режут `app.js` по строковым маркерам; заглушки отстали от кода.
- `farm_rate_limits` ×10: логика восстановления после 429 фактически не покрыта.
- `farm_sharing` ×2 (`:27, :75`): маркер среза уехал в `syncUITimers`; после правки маркера всё равно падают, причина до конца не ясна.

---

## 4. План выноса общего в ядро (независимые задачи)

**T1. Герметичный и воспроизводимый gate** (первым)
- Каждый прогон на своей БД/схеме, без `public` в `search_path`; schema gate в тестах проверяет изолированную схему.
- Интерпретатор фиксирован: только образ или venv из lock; на старте `conftest` проверяет версию PTB.
- Устаревшие тесты фермы обновлены владельцем или явно помечены.
- Приёмка: два прогона подряд из чистого `git archive HEAD` дают одинаковый результат вне зависимости от состояния `morning_quiz_test`; 0 падений из-за окружения.

**T2. Самодостаточность репо**
- `data/system/streak_achievements.json` и `modules/openrouter_client.py` в git (секреты — в env) или явный fallback с предупреждением.
- Юниты деплоя (`mqb-mini-app`, `mqb-game-worker`, trial-bot) версионированы в репо.
- Приёмка: `git archive HEAD` поднимается по документации без ручных файлов; `test_mini_app` зелёный из чистого checkout.

**T3. Telegram-мост и launcher модулей в shell**
- Общий ES-модуль `tg-bridge`: SDK, ready/expand, безопасные отступы, fullscreen, тема, BackButton. Единые токены `--safe-*`.
- SDK грузится на `/app`, `/app/farm`, `/app/alchemy`; CSP разрешает только его.
- Launcher: один параметр `return_to`, идентичность решает сервер; `identity`/`mode` из URL убраны.
- Удаляются `qw_farm/static/telegram.js` и хардкод 47/28 px.
- Приёмка: в Telegram fullscreen (iOS и Android) шапка не уходит под системную строку ни в одном модуле; переход `/app` → модуль → назад сохраняет тему и сессию; ручная проверка на устройстве и скриншоты 390/1280.

**T4. Единое меню настроек и навигация (компонент ядра)** — требование Ильи
- Компонент shell: одна иконка ⚙ (или ⋮) в фиксированном месте шапки, справа, с учётом `--safe-*` и fullscreen. Одинаковый вид во всех играх.
- Пункты ядра: «Главное меню», «Выйти из аккаунта», общие тема/haptics/анимации. Игра добавляет свои пункты через API `menu.register(items)`.
- На игровом экране нет отдельной кнопки выхода.
- Внутри Telegram: BackButton ведёт по экранам игры через стек `navigation.push/pop` (модуль сообщает свой стек; при открытой мини-игре сначала её подтверждение); SettingsButton (⋮ Telegram) открывает это же меню. Вне Telegram — та же шестерёнка; кнопка «назад» показывается, только если в игре есть вложенный экран.
- Что объединить:
  - Алхимия — `game.js:461` + пункт «Главное меню»;
  - ферма — `app.js:759-764, 1046-1066` без дубля «На главную»/«В профиль», ⛶ и ☷ уходят в меню;
  - Classic/Photo — «К играм», «Настройки квиза», «Завершить раунд» (`play-ui.js:88, 141, 312-335`);
  - Мафия — `app.js:1287, 1526` в один пункт;
  - выходы из аккаунта `app.js:617, 1707` и фермы `app.js:762` — в один пункт.
- Приёмка: в каждой игре ровно одна точка входа в меню и ровно один путь в главное меню; BackButton работает у гостя и в Алхимии; в мини-играх фермы BackButton не обходит подтверждение; скриншоты 390 и 1280 по всем модулям; нет кнопок, перекрытых системной строкой.

**T5. Граница периметра**
- `OriginPolicy(allowed_origins)` из env-списка; одна middleware и один CSRF-заголовок на `/api/*`; квоты в общей PG-таблице (включая логин).
- Ферма удаляет свою boundary и `LOCAL_LIMITS`.
- Приёмка: два origin (`quiz.mr-lizard.ru` и старый) проходят, чужой — 403; ASGI-тест с двумя хостами; лимит логина не зависит от числа воркеров.

**T6. Principal как единственная зависимость**
- `application/principal.py` и `require_principal` для всех `/api/*`, включая комнаты и Алхимию; удалить `_locked_progress` (BE-2).
- Приёмка: аккаунт, вошедший через Telegram, видит свои комнаты; гость после привязки видит тот же прогресс во всех играх; grep `guest_store.authorized(` в маршрутах = 0.

**T7. Леджер наград и квитанции**
- `RewardLedger.award(account_id, source, amount, key)` и `CommandReceipts` с ключом `(actor_account_id, command_id)`.
- Алхимия и ферма переведены; прямой записи в `users.global_score` нет.
- Приёмка: повтор команды из любого канала не удваивает награду; пересчёт рейтинга совпадает до и после.

**T8. Контракт модуля**
- `GameModule(id, router, assets, traffic_classes, deadline_handler, notification_kinds, flag)`.
- Ядро регистрирует модули циклом; outbox и дедлайны работают через реестры.
- Таблицы фермы в общем metadata; `alembic/env.py` не импортирует модуль.
- Приёмка: ядро не содержит строк `/api/farm/` и `mafia`; «Ночной город» подключается без правки `mafia_handlers.py`/`game_deadlines.py`.

**T9. Telegram-адаптер единственный**
- `getChatMember` через порт адаптера (BE-7); кнопки меню вызывают use case вместо synthetic Update (LG-12).
- Объявления и Wisdom через outbox с идемпотентностью; lease вместо kill (LG-14).
- Приёмка: grep `api.telegram.org` вне адаптера = 0; повтор планового запуска не дублирует сообщение.

**T10. Удаление легаси и обновление документов**
- Удалить `handlers/quiz/`, мёртвые части `photo_quiz_manager`/`quiz_engine`, JSON-роуты `web/main.py`, ветку `STORAGE_BACKEND=json`, `sys/maintenance_fallback.py`, `developer_notifier`.
- Обновить ADR-011 и CLAUDE.md (сейчас называет мёртвые пути активными); решение владельца — обязаны ли ферма и Алхимия жить на substrate.
- Приёмка: полный gate T1 зелёный; grep по удалённым модулям = 0.

---

## 6. Независимая перепроверка (2026-10-15, вечер)

Отдельный агент (только чтение, fce2b60) пытался опровергнуть пункты 3–9 топ-10. Ни один пункт не снят, три уточнены.

| Пункт | Вердикт | Что изменилось |
|---|---|---|
| 3. Telegram-окружение | **перепроверено, уточнено** | CSP фермы SDK разрешает (`qw_farm/api.py:14`, `web/mini_app.py:392`); проблема в условии загрузки, проверяемом один раз (`app.js:340` меняет `mode` после `bootTelegram`). Без `?identity`, но с cookie `mqb_mini` ферма работает в Telegram-режиме без SDK. CSP Алхимии запрещает даже `'self'`-скрипты. **Новое:** Алхимия не вызывает `session/renew`, после TTL 900 с (`web/mini_app.py:306`) только «Сессия истекла» (`alchemy.html:32277, 32289`). |
| 4. Origin/CSRF | **перепроверено, подтверждено** | `x-mini-csrf` требуется только при cookie без `Authorization` и не для `/session*` (`web/mini_app.py:352-354`). На путях фермы работают обе middleware. Клиент фермы шлёт компенсирующие заголовки сам (`qw_farm/static/app.js:243`). Подтверждено запуском: 400 через docker-прокси без dev-флага. |
| 5. Principal | **перепроверено, уточнено** | Точный счёт — 9 маршрутов из 110 (99 в `web/mini_app.py` и 11 фермы). Не используют Principal: 47 `/api/mini/*`, 6 `/api/guest/*`, 6 `/api/account/*`, 8 комнат, 5 room classic, 6 room photo, 12 room mafia, 4 гостевой Алхимии, 5 публичных. Гостевая Алхимия создаёт свой `GuestAccounts` (`storage/alchemy.py:541, 549, 572, 581`; в `:581` без `clock`). |
| 6. Алхимия и счёт | **перепроверено, уточнено** | «Обход общего леджера» снят: общего леджера очков нет вообще (`farm_ledger` — только экономика фермы, `classic_account_answers.points_delta` — только комнаты). `chat_id=0` — штатное соглашение (`storage/repositories.py:243`). Уже сейчас админский сброс не трогает `alchemy_progress.points_total` (`storage/admin_actions.py:314-319`). `recompute_user_totals` — скрытый риск. |
| 7. Контракт модуля | **перепроверено, уточнено** | `create_app` — `web/mini_app.py:223-2104`. Перестановка маршрутов нужна из-за catch-all `/app/{asset}` (`:490`). Worker `'telegram:mafia-deadlines'` (`handlers/mafia_handlers.py:379`) доставляет и `classic.*`, и `photo.*`. |
| 8. Идемпотентность | **перепроверено, подтверждено** | Глобальный PK `String(64)`: `game_commands` (`storage/models.py:358`), Алхимия (`:728, :757`); per-account только `farm_receipts`. Префиксы условные: `guest:` ≤58 (`web/mini_app.py:797-799`), `mini:` ≤59 (`:1864-1866`); у Classic/Photo префикса нет, `:` разрешён. Последствие — ложный 409 (`storage/games.py:576-584`), утечки чужого результата нет. Решение: составной ключ `(actor, command_id)`. |
| 9. NAV-6 | **перепроверено, подтверждено** | Причина: мини-игры экспортируют только `{close: finishClose}` (`qw_farm/static/tractor_game.js:523`, `trip_game.js:420`), у shell нет пути «закрыть с подтверждением». Escape перехвачен внутри игр (`tractor_game.js:382`, `trip_game.js:248`), BackButton — нет. |

Пункты 1, 2 и 10 подтверждены запуском и чтением в §3.5 и §2.3 и отдельно не перепроверялись.

## 5. Окружение и ограничения аудита
- Для прогонов запускался Docker Desktop (был остановлен). Свои контейнеры шли с `--rm`, чужие не трогались, общие БД не мигрировались.
- Для пересъёмки поднимался изолированный стенд `audit-fce2b60-*` (своя сеть, свой postgres, mini-app из `git archive fce2b60`); после съёмки удалён. Миграции fce2b60 с пустой БД до `20261015_0030` прошли без ошибок [запуск].
- В репо добавлены только этот файл и `screens/`.
- Не проверено: поведение на устройстве в Telegram, прод-юниты вне репо, незакоммиченный код авторизации.
