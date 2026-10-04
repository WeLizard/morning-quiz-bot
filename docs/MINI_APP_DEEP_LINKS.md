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
