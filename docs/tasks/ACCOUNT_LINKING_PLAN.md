# План: сквозной аккаунт и связывание с Telegram

Статус (2026-10-15): сквозной цикл реализован локально и не закоммичен — вход через
Telegram в браузере (подтверждение ботом), привязка с любого устройства, полное
слияние двух Account, логин/пароль для любого аккаунта, смена и восстановление пароля,
список устройств. Подробности — раздел «Сквозной цикл (2026-10-15)» ниже. Выложено в
песочницу `mqb-rehearsal` 2026-10-15 (миграция 0031, trial-бот `mqb-trial-bot:20261015-schema31`,
бэкап `backups/auth-cycle-0031-20261015-1529`); нажатие «Войти» в настоящем Telegram ещё требует
проверки игроком. Production не менялась.

## Решения владельца

- Прогресс с обеих сторон: открытия и предметы объединяются; очки и рейтинг берутся
  с профиля, который игрок выбирает главным. Если прогресс только с одной стороны —
  слияние без вопросов.
- Вход вне Telegram: упрощённый, без почты, с заделом на почту позже.
- 2026-10-15: QuizzyWizzy — самостоятельное приложение; Telegram — один из способов
  входа. Один сквозной Account на приложение, все игры читают данные по нему.
  Вход через Telegram должен связывать аккаунты.
- 2026-10-15: ферма у обоих профилей при слиянии — ферма главного целиком (поля,
  постройки, уровень/XP, соседи) плюс склад и монеты второй фермы; вторая ферма
  остаётся в архиве на слитом аккаунте.
- 2026-10-15: проверка пока локальная; выкладка в песочницу и пересборка trial-бота —
  отдельным решением. Перенос гостевых сессий со старого `quizzywizzy.duckdns.org`
  нужен, но отдельной задачей.

## Что уже есть

- `Account` — платформенный аккаунт; `AccountIdentity(provider, provider_subject)` —
  привязанные внешние входы, уникальны среди активных.
- Telegram: `telegram_account(..., provision=True)` при входе создаёт `Account` и
  identity `telegram`, `User.account_id` указывает на него.
- Гость: `GuestSession` → `Account` без identity.
- Владение по `account_id`: `AlchemyProgress` и команды Алхимии, `GamePlayer`,
  `ClassicAccountAnswer`, `RoomMembership`, `Room.owner_account_id`, `GameCommand/Event`.
- Чатовая статистика (`ChatMember`, `PollAnswer`, `AchievementGrant`) привязана к
  Telegram `User.id`, не к аккаунту.

## Этапы

### Этап 1. Логин и пароль без почты

- Новая identity `provider='password'`, `provider_subject` = нормализованный логин.
- Отдельная таблица `account_credentials(account_id, password_hash, updated_at)`:
  хэш argon2id (или scrypt из stdlib, если не хотим новую зависимость).
- API: `POST /api/account/register`, `POST /api/account/login`, `POST /api/account/logout`.
  Сессия — существующий механизм `GuestSession` (переименовать смысл в «сессия аккаунта»).
- Защита: лимит попыток входа по логину и IP, одинаковый ответ для «нет логина» и
  «неверный пароль».
- Без почты пароль не восстановить. Связанный Telegram даёт дополнительный вход
  в аккаунт; сброс пароля из мини-аппа пока не реализован.
- Задел на почту: поле `email` + `email_verified_at` в будущей миграции; identity
  `provider='email'` ляжет в ту же схему.

### Этап 2. Связывание

- Реализован только путь из текущего гостевого/парольного профиля внутри Telegram:
  «Связать с Telegram» → серверная сводка → отдельное согласие → подтверждение.
  В том же WebView нужны действующая `mqb_guest` и подписанная `initData` не старше
  300 секунд. Для аккаунта из внешнего браузера нужно сначала войти по логину и
  паролю внутри WebView. Код/ссылка переноса между браузерами пока не реализованы.
  Новый WebView без сессии показывает компактный первый старт с явным «Начать
  играть» и вариантом входа по существующему логину. Для известной Telegram identity
  клиент использует `POST /api/mini/session/resume` с подписанной `init_data`; этот
  маршрут возобновляет сессию без provisioning User/Account. Для нового Telegram
  пользователя provisioning происходит только после явного «Начать играть».
  Действующая guest/password cookie-сессия также возобновляется. Явный logout
  устанавливает клиентский marker, блокирующий весь автоматический bootstrap Mini
  App и Farm invite до ручного входа; Farm invite не обходит marker. После ручного
  входа guest/password в тот же Account Farm не показывает chooser профиля.
- API: `POST /api/account/telegram-link/preview` и `/confirm`; guest cookie,
  точный Origin и `X-Guest-CSRF: 1` обязательны. `User`, verified Telegram identity
  и `User.account_id` создаются/дополняются только в одной транзакции подтверждения.
  Preview ничего не создаёт; Mini App session при связывании не выдаётся.
- `POST /api/mini/session/resume` принимает подписанную `init_data` и выдаёт
  короткую Mini App session только для уже существующей Telegram identity. Он не
  создаёт User/Account/identity; новый Telegram вход с provisioning начинается
  только после явного действия «Начать играть». Logout marker хранится на клиенте
  и подавляет автоматическое восстановление Mini App и Farm, включая приглашение,
  пока игрок вручную не выберет вход.
- Текущий `Account.id`, ферма, комнаты, пароль и прогресс сохраняются. Сессия гостя
  остаётся активной; выбор Telegram для следующего входа — отдельное действие.
  Telegram имя само по себе не подтверждает владение и не связывает аккаунты.
- Чужой `User.account_id`, Telegram identity другого Account, отозванная либо
  неподтверждённая identity и несовместимый legacy Alchemy progress дают явный 409
  `telegram_link_conflict`, даже если второй Account выглядит пустым. Откат
  транзакции сохраняет оба профиля. Заблокированные/архивные профили отклоняются.
  Другая Telegram связь текущего Account тоже запрещена (`User.account_id` unique).
- Повтор для той же пары идемпотентен. Подтверждение перепроверяет account ID и
  Telegram ID из preview, сессию и moderation revision; устаревший выбор даёт 409.
  Связывание сериализуется общим operation fence, `mini-login:<uid>` advisory lock
  и блокировками User/identity/guest session/Account/Alchemy progress.
- Alchemy остаётся одной строкой по Account: transitional `user_id` дополняется,
  offline claims не превращаются в verified, награды/очки и receipts не сбрасываются.
  Гостевой канал продолжает играть без Telegram рейтинговых начислений; рейтинговый
  канал использует тот же прогресс и награждает лишь новые проверенные открытия.
  Чтение Telegram прогресса и рейтинга использует canonical `User.account_id`;
  guest-создание строки после связывания не берёт обратную User FK блокировку.
- Для этой реализации новой схемы БД не требуется. `tests/test_account_linking.py`:
  10 passed, 0 skipped на отдельной `morning_quiz_test` в UUID-схемах; проверены
  сохранение фермы/прогресса, конфликт, повтор, откат после flush, гонки и
  отсутствие повторных наград. `tests/js/mini_navigation.test.cjs`: 66 passed,
  включая выбор входа и UI подтверждения. Sandbox: свежий `pg_dump` в
  `/home/lizard/mqb-rehearsal/backups/telegram-link-20261011-195753/pre-link.dump`
  перед выкладкой, пять runtime-файлов перенесены с совпавшими SHA-256, сервис active,
  публичные `/healthz` и `/app/app.js` вернули 200. Реальный Telegram WebView
  ещё требует приёмки. Production не менялась.
- Исправление первого входа после жалобы на экран выбора выложено в `mqb-rehearsal`
  2026-10-11: известная Telegram identity входит автоматически без provisioning,
  новая видит компактный первый старт. Адресный PostgreSQL onboarding:
  `23 passed`, JS-навигация: `73 passed`; независимое ревью дало GO для sandbox.
  Перед выкладкой сохранён дамп
  `/home/lizard/mqb-rehearsal/backups/telegram-entry-20261011-202005/pre-entry.dump`
  и копии трёх файлов. SHA-256 dev/sandbox совпали, сервис active, публичные
  `/healthz` и `/app/app.js` вернули 200; неподписанный resume вернул 401.
  Ручная приёмка в Telegram WebView остаётся открытой. Production не менялась.
- Добавление пароля из Telegram-профиля и сброс забытого пароля пока не реализованы.
  Если у Telegram уже другой Account, нужен отдельно реализованный этап 3.

### Этап 3. Слияние двух аккаунтов

Одна транзакция, advisory lock на оба `account_id`, запись в `AdminAction`/журнал.

- Алхимия: объединение открытых элементов, глав, наград (по множествам, без дублей).
- Ферма: объединение склада и предметов; поля и постройки — с главного профиля
  (уточнить модель фермы перед реализацией).
- Игры и комнаты: перенос `GamePlayer`, `RoomMembership`, `ClassicAccountAnswer`
  на главный аккаунт; конфликт уникальности → остаётся запись главного.
- Очки и рейтинг: с главного профиля, второй не суммируется.
- Identity второго аккаунта переносятся; второй `Account` помечается слитым
  (`merged_into`), не удаляется — для аудита и отката.
- Перед выполнением показываем игроку сводку «что получится».

### Этап 4. Единая статистика

- Профиль собирает данные по `account_id`: Алхимия, ферма, комнаты, плюс чатовая
  статистика через все привязанные Telegram `User`.
- Рейтинги групп остаются по Telegram (членство в группе — свойство Telegram).

## Риски

- Слияние необратимо по смыслу: нужен журнал и отдельные тесты его правил на
  PostgreSQL перед реализацией этапа 3.
- Для будущего переноса между браузерами: код с коротким сроком, одноразовостью
  и привязкой к исходной сессии. Текущий путь в одном WebView коды не использует.
- Пароли без почты: забытый пароль без привязанного Telegram = потерянный профиль;
  предупреждать при регистрации.

## Порядок

1 → 2 → 4 → 3. Слияние делаем последним: пока игроков вне Telegram нет, конфликтов
почти не будет, а этапы 1, 2, 4 дают пользу сразу.

## Сквозной цикл (2026-10-15)

Миграция `20261015_0031_account_auth_cycle`: `telegram_login_requests`,
`accounts.merged_into_id/merged_at`, `account_merges` (аудит), `guest_sessions.created_via/user_agent`.

| Сценарий | Как работает | Код |
|---|---|---|
| Гость в браузере | без изменений, `GuestSession` 30 дней | `storage/guest_accounts.py` |
| Вход в Mini App | без изменений: `initData` → `MiniAppSession` 15 мин + renew | `storage/mini_app.py` |
| Вход через Telegram в браузере | `POST /api/account/telegram-login/start` → ссылка `t.me/<bot>?start=login_<token>` и HttpOnly cookie `mqb_tglogin` (только этот браузер, 10 мин) → бот в личке показывает устройство и время, вход одобряет только кнопка «Войти» → `GET /status` → `POST /complete`. Новый Telegram получает Account (как «Начать играть» в Mini App) | `storage/telegram_login.py`, `application/telegram_login.py`, `web/telegram_login_routes.py`, `handlers/account_login_handlers.py` |
| Привязка без потери прогресса | тот же `/complete` с текущей guest-cookie ничего не меняет молча: возвращает `link_required` (имя профиля и Telegram) или `merge_required`; привязка — только после подтверждения в браузере (`mode=link`), слияние — через `/merge`. В WebView — прежний `telegram-link/preview|confirm` | `application/telegram_login.py`, `application/account_linking.py` |
| Слияние | если у Telegram другой Account: одна сторона пустая — сразу (`merged`), иначе `merge_required` со сводкой и выбором главного → `POST /api/account/telegram-login/merge` (браузер) или `/api/account/telegram-link/merge` (Mini App, `init_data`). Второй Account архивируется (`merged_into_id`), запись в `account_merges`. Два разных Telegram в одном аккаунте — 409 `merge_two_telegram`; профиль с другим Telegram — 409 `telegram_other_linked` и вариант «войти в профиль этого Telegram» (`mode=switch`) | `application/account_merge.py` (`MERGE_POLICY` по всем FK на `accounts.id`), `application/account_merge_flow.py`, `web/account_merge_routes.py` |
| Выход | без изменений; + «Выйти на других устройствах» | `application/account_security.py` |
| Несколько устройств | `GET /api/account/sessions`, `POST …/revoke`, `…/revoke-others` (guest- и Telegram-сессии) | `web/account_security_routes.py` |
| Восстановление | `POST /api/account/credentials` — логин/пароль для любого аккаунта (в т.ч. Telegram); `POST /api/account/password` — смена с текущим паролем или без него после свежего (<15 мин) входа через Telegram; смена отзывает остальные сессии. Без связанного Telegram забытый пароль не восстановить (почта — позже) | `application/account_security.py` |

Правила слияния: открытия/главы/достижения Алхимии — объединение; очки, серия, попытки —
главного; claims этапов — недостающие переносятся; комнаты, приглашения, членства (конфликт →
роль owner сохраняется), игроки и ответы Classic без конфликта PK — на главный; история команд
и событий остаётся; guest-сессии второго аккаунта переходят на главный; пароль второго
отзывается, если у главного уже есть (`lost_login` в сводке); ферма — по решению владельца выше,
с записью `account_merge` в `farm_ledger`; переносятся только заработанные монеты второй фермы (`coins − starter_credit`), стартовый подарок не переносится. «Пустой» профиль: нет логина, нет открытий сверх
базовых/очков/claims, ферма отсутствует или не тронута, нет комнат и игр.

Проверка: PostgreSQL/HTTP — `tests/test_telegram_login.py`, `tests/test_account_merge.py`,
`tests/test_account_merge_flow.py`, `tests/test_account_security.py` и прежние
`tests/test_account_linking.py` (тест конфликта заменён предложением слияния),
`test_account_password.py`, `test_guest_accounts.py`, `test_principal.py`; JS —
`tests/js/mini_navigation.test.cjs`. Ручная проверка в браузере (десктоп и 375 px) на
отдельной схеме локальной БД: вход через Telegram, логин/пароль, выход и вход по паролю,
привязка гостя со слиянием, восстановление пароля, «выйти на других устройствах».
Бот проверен юнит-тестом на фейковых Update; реальный Telegram и песочница — после
отдельного решения о выкладке.

Ревью безопасности (2026-10-15) — исправлено: тихая привязка чужого Telegram (теперь подтверждение в браузере), перенос стартовых монет при слиянии, порядок блокировок слияния, свежесть Telegram для сброса пароля (сессия < 15 мин), одобрение входа только тем, кому бот показал запрос, лимиты для credentials/merge.

Открыто: перенос гостевых сессий со старого домена; единая статистика по аккаунту (этап 4)
и правило гостевых очков в Мировом рейтинге; серверная отмена запроса входа кнопкой «Отмена»
в браузере (сейчас запрос просто истекает за 10 минут).
