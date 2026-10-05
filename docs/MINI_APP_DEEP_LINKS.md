# Deep links Mini App

Ссылки открывают Mini App сразу на нужном экране. Формат — официальный механизм
Telegram:

```
https://t.me/<bot_username>?startapp=<param>
```

## Поддерживаемые параметры

| Параметр | Куда ведёт |
|---|---|
| `home` | главная (по умолчанию) |
| `chats` | список чатов |
| `rating` | рейтинг |
| `profile` | профиль |
| `achievements` | экран достижений |
| `history` | история игр и ответов |
| `chat_n<id>` | экран конкретного чата (`id` — модуль id группы) |
| `mafia_n<id>` | лобби мафии в группе (совместимость) |

Групповые ссылки несут модуль id: реальный id группы отрицательный, поэтому
`chat_n1002123346533` открывает чат `-1002123346533`.

## Как это работает в клиенте

`web/mini_client/app.js`:

- параметр берётся из `Telegram.WebApp.initDataUnsafe.start_param`, а если его
  нет — из `?tgWebAppStartParam=` в адресе страницы;
- список страниц ограничен белым списком `LAUNCH_PAGES`; неизвестный параметр
  молча приводит на главную, ошибок не возникает;
- если чат из ссылки недоступен (игрок вышел из чата или ссылка устарела),
  приложение **не подменяет чат молча**: показывает «Чат из ссылки недоступен» и
  работает с первым доступным чатом.

## Серверный помощник

```python
from modules.mini_app_launch import deep_link, direct_mafia_link, launch_button

deep_link('quizbot', 'achievements')            # https://t.me/quizbot?startapp=achievements
deep_link('quizbot', 'chat', -1002123346533)    # https://t.me/quizbot?startapp=chat_n1002123346533
direct_mafia_link('quizbot', -1002123346533)    # то же для мафии
launch_button('private')                        # inline-кнопка web_app, если задан MINI_APP_URL
```

`deep_link` возвращает `None`, если `MINI_APP_URL` не настроен, и поднимает
`ValueError` при неизвестной странице, неположительном id группы (ноль, плюс,
дробное, `bool`) или некорректном имени бота.

## Что нужно, чтобы ссылки работали

1. `MINI_APP_URL` — публичный HTTPS-адрес на порту 443 (проверяется
   `configured_url()`, локальные и приватные адреса отклоняются).
2. **Main Mini App, зарегистрированный в BotFather**: без него Telegram
   игнорирует `?startapp=` и просто открывает чат с ботом. Кнопка меню и
   inline-кнопки `web_app` работают и без регистрации Main Mini App.

## Зарегистрировано у пробного бота (2026-10-05)

Main Mini App оформлен в BotFather для `@Quizywizzy_bot`, поэтому `?startapp=`
теперь работает (до регистрации Telegram его игнорировал). Ссылки вида:

```
https://t.me/Quizywizzy_bot/app                      — главная
https://t.me/Quizywizzy_bot/app?startapp=achievements — экран достижений
https://t.me/Quizywizzy_bot/app?startapp=history      — история игр и ответов
https://t.me/Quizywizzy_bot/app?startapp=rating       — рейтинг
https://t.me/Quizywizzy_bot/app?startapp=profile      — профиль
https://t.me/Quizywizzy_bot/app?startapp=chats        — список чатов
https://t.me/Quizywizzy_bot/app?startapp=chat_n1002123346533  — конкретный чат (id группы без минуса)
https://t.me/Quizywizzy_bot/app?startapp=mafia_n1002123346533 — лобби мафии
```

Проверено снаружи: `https://t.me/Quizywizzy_bot/app` отдаёт страницу с кнопкой
**Open App** (`tg://resolve?domain=Quizywizzy_bot&appname=app`). Ссылка на чат
работает только у того, кто в этом чате состоит: иначе приложение честно скажет
«Чат из ссылки недоступен».

На боевом боте ту же регистрацию нужно сделать в момент выкладки.
