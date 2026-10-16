# Перенос гостевых сессий со старого адреса (quizzywizzy.duckdns.org → quiz.mr-lizard.ru)

Статус: **отклонено для песочницы** (решение Ильи 2026-10-15). Пострадали 4 гостевых аккаунта с небольшим
прогрессом (фермы xp 55/91/166, алхимия у одного 10 элементов). Их не переносим: Илья предупредит игроков, что
профиль сбросился. Старый `/app` остаётся на 302. Схема ниже — заготовка на случай такого же переезда домена в проде.
Код не написан, ничего не выкатывалось.

## Как сейчас (serverold, только чтение)

- nginx `/etc/nginx/sites-enabled/mqb-domain` (старый домен): `location ^~ /app { return 302 https://quiz.mr-lizard.ru$request_uri; }`.
  `/api/guest`, `/api/account`, `/api/mini`, `/api/farm`, `/healthz` старого домена по-прежнему проксируются
  в тот же бэкенд `127.0.0.1:8081` (песочница mqb-rehearsal), но приложение принимает только
  `MINI_APP_ORIGIN=https://quiz.mr-lizard.ru` и отвечает старому Host `400 Недопустимый адрес сервиса`.
  Остальное на старом домене — Библия КошкиМышки (`192.168.0.51:8765`), её не трогаем.
- `mqb-quiz-mr-lizard` (новый домен) — тот же бэкенд 8081.
- Оба домена пишут в `/var/log/nginx/mqb-domain.log` формата combined: **строка запроса и Referer попадают в лог**,
  фрагмент `#…` и тело POST — нет.
- Cookie `mqb_guest`: HttpOnly, Secure, `SameSite=Strict`, 30 дней, path `/`. Из-за Strict она **не уходит**
  на первом переходе на старый домен по ссылке с другого сайта/из Telegram — только на same-origin `fetch`
  со страницы самого старого домена. Значит, перенос на чистом серверном 302 работает не всегда; нужна страница с JS.
- Масштаб: на песочнице живых гостевых сессий 4 (4 аккаунта, все `created_via IS NULL`, т. е. до 0031).

## Схема

```
Браузер              старый домен (тот же бэкенд, Host=duckdns)        новый домен
GET /app/…  ───────► страница переноса (no-store, no-referrer, CSP)
  JS: POST /api/guest/transfer/start  (same-origin → cookie mqb_guest уходит)
             ◄────── {token} (43 симв., хэш в БД, 5 мин) или 401
  location.replace(NEW/app/transfer#t=<token>&next=<путь>&h=<исходный #>)
                                                     ─────────────────►  GET /app/transfer (статичная страница)
                                                     JS: history.replaceState (фрагмент стёрт)
                                                     POST /api/guest/transfer/redeem {token, mode}
                                                     ◄──── Set-Cookie mqb_guest (новая GuestSession того же Account)
                                                     location.replace(next + h)
```
Без cookie/при ошибке старая страница делает `location.replace(NEW + путь + query + исходный #)` — то же, что 302 сейчас
(включая `#tgWebAppData` для Telegram WebView).

### Бэкенд

- Новая переменная `MINI_APP_LEGACY_ORIGIN` (точный https-origin, ≠ `MINI_APP_ORIGIN`). Не задана → всё как сейчас.
- Middleware `boundary` для Host старого origin пропускает **только**:
  - `GET/HEAD /app` и `/app/*` при `Sec-Fetch-Dest: document` (или без заголовка) → страница переноса;
    прочие подзапросы `/app/*` → `302` на новый домен, как сейчас;
  - `POST /api/guest/transfer/start` с `Origin` = старый origin и `X-Guest-CSRF: 1`, лимит auth-корзины (10/мин на IP).
  Всё остальное на старом Host → прежний `400`.
- Таблица `guest_transfer_tokens` (миграция 0032): `token_hash` PK (sha256), `account_id` FK accounts CASCADE,
  `source_session_hash` FK guest_sessions CASCADE, `account_revision`, `status` pending|consumed|superseded,
  `client_hint`, `created_at`, `expires_at` (+300 с), `consumed_at`. Индексы по `expires_at`, `source_session_hash`.
  Downgrade — просто удаление таблицы (токены одноразовые и короткие).
- `start` (старый домен): fence → `GuestSession` FOR UPDATE по хэшу cookie → проверки как в `_authorized`
  (не отозвана, не истекла; Account не archived/bot_blocked, `merged_into_id IS NULL`, ревизия совпадает) →
  не больше 5 токенов на исходную сессию за час (иначе 429) → прежние pending этой сессии → superseded → новый токен.
  Сырой токен только в теле ответа (`Cache-Control: no-store`).
- `redeem` (новый домен, JSON `{token, mode: auto|switch}`): fence → токен FOR UPDATE → GuestSession (исходная и
  текущая браузерная) FOR UPDATE по порядку token_hash → Account FOR UPDATE (key share). Отказы:
  `transfer_used` 409, `transfer_expired` 410, исходная сессия отозвана/истекла 410 `transfer_source_gone`,
  аккаунт archived/bot_blocked/слит (`merged_into_id`)/сменилась ревизия/`account_id` токена ≠ сессии → 403.
  Слияние переносит гостевые сессии на основной аккаунт, поэтому за `merged_into_id` не идём: пользователь
  открывает старый адрес ещё раз и получает токен уже основного аккаунта.
  - текущая cookie нового домена — тот же аккаунт → `already`, токен погашен, новая сессия не создаётся;
  - другой живой профиль и `mode=auto` → `switch_required` (имена обоих профилей), токен **не** гасится;
  - `mode=switch` → текущая сессия отзывается (как в Telegram-входе), выдаётся новая;
  - иначе → новая `GuestSession(created_via='transfer')`, `Set-Cookie mqb_guest`.
  Старая сессия старого домена **не отзывается**: если ответ redeem потеряется, пользователь просто откроет старый
  адрес ещё раз. Повторные визиты по закладке дают `already` и не плодят сессии.
  `created_via='transfer'` не даёт права «свежего Telegram-входа» на смену пароля (там проверяется `== 'telegram'`).
- Только `mqb_guest` (гостевые и парольные браузерные сессии). Telegram Mini App (`mqb_mini`) не переносится:
  он и так входит заново по initData на новом домене.
- `guest_access()` (private test) действует на оба эндпоинта. `MERGE_POLICY` получает
  `('guest_transfer_tokens', 'account_id')` (токены при слиянии не переносятся — `special`/удаление).

### Утечки

Токен никогда не в query: в логах nginx/uvicorn только путь. Во фрагменте он не уходит на сервер и в Referer;
новая страница стирает фрагмент `history.replaceState` до первого запроса, обе страницы
`Referrer-Policy: no-referrer`, `Cache-Control: no-store`, CSP без сторонних источников, `location.replace`
(старая страница не остаётся в истории). Токен одноразовый, 5 минут, перебор 256 бит нереален.
`next` проверяется на новом домене: только `/app…` из безопасных символов, без `//`; `h` — до 4 КБ, начинается с `#`.

### UI (новый домен, /app/transfer)

Без лишнего: «Переносим профиль…» → редирект. `switch_required`: «На этом устройстве уже открыт профиль «X».
Перейти в профиль «Y» со старого адреса?» [Перейти] [Остаться в «X»] + предупреждение, что «X» без логина
потом не открыть. Ошибки: «Ссылка переноса устарела — открой старый адрес ещё раз» + ссылка на /app.
В списке устройств метка `transfer` → «Перенос».

## Тесты (PG + HTTP, в стиле tests/test_telegram_login.py)

Старт и обмен на одном ASGI-приложении с двумя base_url (старый/новый origin); happy path; без cookie → 401 и
страница уходит на новый домен; CSRF/Origin; чужие пути старого Host → 400; повтор токена → 409; истечение (часы) → 410;
отзыв исходной сессии/logout между start и redeem → 410; archived/bot_blocked/слитый аккаунт → 403; лимит 5/ч → 429;
superseded; `already`; `switch_required` + `switch`; `next`/`h` валидация; сырой токен не хранится в БД;
страница переноса отдаёт no-store/no-referrer; фича выключена без `MINI_APP_LEGACY_ORIGIN`.

## Выкладка (только с отдельного разрешения)

1. Бэкап как в прошлых выкладках (files.tar + pg_dump + alembic current).
2. Файлы + `alembic upgrade` 0031→0032, рестарт `mqb-mini-app` (фича спит без env). Trial-бот не затрагивается
   (новый код только в web/, storage/, alembic — но образ бота держит alembic-head; проверить, нужен ли слой).
3. `MINI_APP_LEGACY_ORIGIN=https://quizzywizzy.duckdns.org` в `/etc/mqb/mini-app.env`, рестарт.
4. nginx старого домена: `location ^~ /app` вместо `return 302` → `proxy_pass http://127.0.0.1:8081` с теми же
   заголовками; `nginx -t`, `reload`. Смоук: старый `/app` без cookie → страница → новый домен; с cookie → перенос.

Откат: (а) мгновенно — вернуть строку `return 302` в nginx + reload; (б) убрать env, рестарт; (в) код и
`alembic downgrade 20261015_0031` (таблица токенов удаляется без потерь). Созданные переносом сессии — обычные
GuestSession, остаются рабочими после отката.
