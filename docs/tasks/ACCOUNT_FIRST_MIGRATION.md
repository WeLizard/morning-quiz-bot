# План: приложение «сначала аккаунт» (Telegram — один из каналов)

Статус: план на согласование (2026-10-10). Анализ кода — wl-architect (Opus), код не менялся.

Принцип владельца: QuizzyWizzy — самостоятельное приложение вокруг аккаунта игрока.
Telegram (бот и Mini App) — канал доступа наравне с браузером ПК и телефона. Все игры —
в каждом канале, с одним интерфейсом, прогрессом и статистикой.

## Что есть сейчас (проверено по коду)

- Две сессии: `MiniAppSession` (Telegram `user_id`, 15 мин + renew, защита от повторного
  initData) и `GuestSession` (`account_id`, 30 дней; вход по паролю пишет туда же).
- `User.account_id` — уникальный FK; `telegram_account()` создаёт `Account` + identity.
  Пробел: бот (`OperationalRepository.ensure_user`) аккаунт не создаёт — у игроков,
  игравших только в группах после миграции 0018, `account_id = NULL`.
- «Контекст» уже есть — `Room`: `Game.room_id` NOT NULL, Telegram-чат = `Room(kind='telegram')`
  + `RoomTransport` (`storage/games.py::ensure_telegram_room`).
- Соло гостя — комната «Моя игра» по названию (`app.js::openSoloGame`), упрощённый UI
  `openGuestClassic/Photo`. Соло Telegram — приватный чат `Chat(id=user.id)`.
- Статистика: Telegram — `ChatMember`/`PollAnswer`/`User.global_score`; в комнатах сводной
  статистики по аккаунту нет.
- Прототип единого принципала — `qw_farm/integration.py::authenticated()`.
- Ручки play-ui (`/api/mini/.../chats/{id}`) и комнат (`/api/guest/rooms/{id}`) различаются:
  `command_id` в теле vs `Idempotency-Key`, `/sync` vs `GET /current`, параметры старта.
- Модерация есть только для `users`/`chats`, не для `Account`.

## Целевая модель

- **Одна сессия** `account_sessions` (расширение `guest_sessions`): `account_id`, `channel`
  (telegram|password|guest), `telegram_user_id?`, ревизии модерации, срок по каналу.
  Одна cookie `qw_session` + Bearer.
- **Контекст = Room**: `personal` (один на аккаунт), `standalone` (приглашения),
  `telegram` (группа; доступ — Telegram identity + проверка членства). Диспетчер по `kind`.
- **Статистика**: по контексту (telegram → `ChatMember`; остальные → новая
  `context_member_stats`), по аккаунту — агрегат всего (+ Алхимия, ферма).
- **API**: единый `/api/app/...` (сессия, контексты, игры classic/photo с `Idempotency-Key`,
  рейтинги, профиль); `/api/mini/*` и `/api/guest/*` — шимы до этапа 7.
- **Клиент**: один `app.js`, `QuizPlay.mount({api})` вместо `chatId`; Telegram-специфика
  только в `telegram-ui.js`.
- **Бот** не меняется: групповые игры = telegram-контекст.

## Этапы

0. **Общий принципал** (бэкенд): `web/principal.py::resolve_principal`; ферма на нём.
1. **Полный экран игры для соло в вебе** (клиент): адаптеры `chatApi`/`roomApi` в
   `play-ui.js`; `openSoloGame` → `QuizPlay.mount({api: roomApi})`. Первый видимый результат.
2. **Личный контекст + `/api/app/contexts`** для classic/photo: `Room.kind='personal'`,
   `application/contexts.py`, флаг `MQB_APP_API_ENABLED`.
3. **Единая сессия**: `guest_sessions` → `account_sessions`; проверить cookie в WebView
   Telegram (иначе Bearer).
4. **Один клиент**: слить `home`/`guestHome`, `request`/`guestRequest`.
5. **Статистика по аккаунту**: заполнить пустые `User.account_id`, создавать аккаунт на пути
   бота, `context_member_stats`, `/api/app/profile/stats`.
6. **Связывание и слияние** — по `ACCOUNT_LINKING_PLAN.md`.
7. **Удалить шимы**, обновить `MINI_APP_API.md`, ADR-010, `STANDALONE_FOUNDATION.md`.

Каждый этап: свои тесты, миграции только добавляют, откат — revert/флаг.

## Где какие игры (владелец, 2026-10-10)

- **Чат-бот Telegram** (не Mini App): classic и photo запускаются в личном чате с ботом и в
  группе. В группе отвечают все участники, очки — угадавшему.
- **Mini App и браузер (ПК/телефон)**: игра личная, на аккаунт игрока. Групповых игр в
  Mini App нет; из групп там только «Рейтинг канала» (только в Telegram).
- Следствие для плана: telegram-группа — контекст только для бота; в `/api/app` для
  classic/photo достаточно личного контекста (+ комнат с друзьями для мафии).

## Решения владельца (2026-10-10)

1. Квизы доступны и в личном чате с ботом, и в общем канале/группе для всех. Личный контекст
   аккаунта: для Telegram-игрока — его приватный чат с ботом; для аккаунта без Telegram —
   `personal`-комната. Статистика личного контекста — одна на аккаунт.
2. Три рейтинга: **Мировой** и **Личный** — доступны во всех каналах; **Рейтинг канала** —
   только в Telegram (групповой чат). Гостевые (без логина и Telegram) очки в Мировой не
   идут — защита от накрутки (уточнить у владельца при реализации этапа 5).
3. Срок сессии одинаковый для всех каналов — 30 дней. Да.
4. Существующие «Моя игра» → `personal`. Да.
5. Модерация на уровне `Account` — делать.
6. Слияние аккаунтов с двумя разными Telegram identity — запрещено.
7. Групповая политика Photo (AUD-019): в группе/общей комнате отгадывать могут **все**,
   очки получает тот, кто угадал. В личном контексте — только сам игрок.
   История: оригинальный бот (до `7487a42`, 2026-10-05) принимал ответы всех, но ошибочно
   начислял очки запустившему; `7487a42` «починил» это запретом ответов не-владельца — это
   неверно. Нужно: `modules/photo_quiz_manager.py::check_answer` и `application/photo.py`
   (сейчас ответ только от `creator_id`) — принимать ответы участников группы и начислять
   отвечающему; тесты на обе ветки (группа / личный).
   **Реализовано (2026-10-10), Telegram-бот:** активный путь — `handlers/photo_quiz_handlers.py`
   → `application/photo.py::PhotoApplicationService` (`modules/photo_quiz_manager.py::check_answer`
   в `bot.py` не подключён, не менялся). Адаптер передаёт `shared=True` для `group`/`supergroup`:
   `settle_due`/`current`/`answer` не ограничивают отвечающего создателем, очки и статистика
   идут `user_id` отвечающего, первый верный ответ закрывает вопрос (строка игры под
   `FOR UPDATE`), доступ (`require_access`) проверяется для отвечающего, боты игнорируются;
   в итоговом сообщении указан угадавший. Личный чат и Mini App/комнаты — `shared=False`
   (только создатель). Остановка серии по-прежнему за создателем/админом. Тест:
   `tests/test_postgres_photos.py::test_telegram_photo_group_any_member_answers_private_only_player`.
