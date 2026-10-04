# Временный Mini App в Telegram · dev

## Открыть

Обновление игрового этапа: теперь внутри Mini App можно настраивать классический
и фото-квиз и отвечать на вопросы. Для них пока используется переходный PTB
bridge с общей PostgreSQL и защищённой очередью действий. Новая игровая логика
туда не добавляется: «Ночной город» уже использует общий application-service.
[Полнота функций и текущие ограничения](MINI_APP_GAMEPLAY.md).

В личке отдельного тестового бота нажать **«🦉 Открыть Mini App»** в свежем
сообщении `/start` либо **Morning Quiz** рядом с полем ввода. Только такой запуск
передаёт проверяемую Telegram initData. Открытие HTTPS-страницы обычной браузерной
вкладкой не авторизует пользователя.

2026-08-31 пользователь разрешил временную HTTPS-публикацию. Адрес текущего запуска:
<https://lets-consortium-orders-clear.trycloudflare.com/app>.
Это случайный адрес [Cloudflare Quick Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/),
не постоянный хостинг; нужен включённый ПК и оба запущенных процесса.

## Границы

- Tunnel ведёт исключительно на `http://127.0.0.1:4187`.
- Там отдельная публичная фабрика Mini App: Telegram HMAC, короткие bearer-сессии,
  allowlist одного согласованного аккаунта, личный чат. Групповой доступ закрыт.
- Общедоступны оболочка/ресурсы приложения, публичная конфигурация и health.
  Персональные API требуют входа; синтетического dev-login нет.
- Админка 4184, локальный dev-preview 4185, статус бота 4186, метрики 4190 и PG
  не опубликованы. Production не используется.
- Cloudflare выступает HTTPS-прокси; это временный тест, не production ingress.
  Origin/Host должны совпадать с выданным адресом, proxy trust — только loopback.

## Повторный запуск (PowerShell)

Из `C:\Users\Lizard\Projects\morning-quiz-bot`, в отдельных окнах.
Бинарник `cloudflared` 2026.8.2 скачан из официального GitHub release, SHA-256
сверен с digest release asset:
`c29eee2b121f5436a642eed69fd9767da7e7b8c510fa50aaa130337f931357b5`.
Установка службы, автозапуска, DNS и изменение firewall не выполнялись.

1. Запустить временный tunnel только на выделенный порт:

   ```powershell
   .\.local\tools\cloudflared-2026.8.2\cloudflared.exe tunnel --no-autoupdate --url http://127.0.0.1:4187 --metrics 127.0.0.1:4190 --loglevel info
   ```

2. Взять новый HTTPS origin из вывода (без `/app`). Подставить ранее согласованные
   ID пользователя и тестового бота, не production token:

   ```powershell
   .\scripts\Start-LocalTelegramMiniApp.ps1 -UserId <ID_пользователя> -ExpectedBotId <ID_тестового_бота> -TokenFile '.env' -PublicOrigin 'https://<новый-host>.trycloudflare.com'
   ```

3. Проверить `/app` (200), `/api/mini/me` без credentials (401), `/login` и
   `/api/dev/session` (404). При отказе origin не ослаблять проверку: сопоставить URL.
4. Мягко остановить уже запущенный private runner через
   `Stop-LocalTelegramTest.ps1`, дождаться освобождения 4186. Затем:

   ```powershell
   .\scripts\Start-LocalTelegramTest.ps1 -ChatId <ID_пользователя> -ExpectedBotId <ID_тестового_бота> -TokenFile '.env' -MiniAppUrl 'https://<новый-host>.trycloudflare.com/app' -ShowMenu
   ```

Меню устанавливается только для согласованной лички и проверяется обратным
`getChatMenuButton`. Глобальное меню бота не меняется. Ключ читается внутри
процесса из игнорируемого `.env`, не передаётся аргументом и не копируется в отчёт.

## Групповой запуск «Ночного города»

Команда `/mafia` и кнопки группы работают без Mini App и показывают роль только
нажавшему игроку через персональный callback-alert. Если в BotFather настроен
Main Mini App, карточка также содержит официальный direct link вида
`https://t.me/<bot>?startapp=mafia_n<chat-id>`; Mini App выбирает тот же стол.
Обычная `web_app` inline-кнопка для группы не применяется: Bot API разрешает её
только в личном чате. Живой групповой тест выполняется только после отдельного
разрешения на тестовую группу; текущий private runner сам группу не расширяет.

## Остановка

```powershell
.\scripts\Stop-LocalTelegramMiniApp.ps1
```

Сначала проверяет путь, аргументы и PID владельцев 4190/4187; прекращает tunnel
и отдельный публичный backend. Не останавливает бот, preview, PG и не удаляет
данные. Незнакомый процесс останавливать отказывается. Альтернатива — Ctrl+C
в двух соответствующих PowerShell-окнах.

Чтобы убрать уже неработающую кнопку в Telegram, мягко перезапустить private bot
**без** `-MiniAppUrl`: runner явно возвращает меню команд для этой лички.
Старые сообщения с кнопкой могут оставаться в истории; их URL больше не обслуживается.

## Проверка 2026-08-31

- Внешний HTTPS: `/app` и все его локальные ресурсы, health/config — 200.
- Без авторизации профиль — 401; заведомо неверная initData — 401;
  чужой Origin — 403; `/login`, `/api/dev/info`, `/api/dev/session`, `/.env`,
  `/openapi.json` — 404. Ответы `Cache-Control: no-store`.
- Telegram: setChatMenuButton/getChatMenuButton/sendMessage — 200,
  `chat_menu_verified: mini_app=true`, `operator_menu_refresh`.
- **394 passed, 30 warnings** в отдельной тестовой БД. JUnit:
  `.local/acceptance/telegram-https-mini-app.xml`.
- Настоящий вход пользователя и отображение на Telegram-устройствах требуют
  пользовательского запуска. На момент публикации подтверждения ещё нет;
  серверные тесты не считать мобильной приёмкой.

Основная задача: [MQB-003](tasks/MQB-003-telegram-experience.md).
