"""Optional Telegram entry point, deliberately absent until a public HTTPS URL is configured."""
import ipaddress
import os
import re
from urllib.parse import urlsplit


def configured_url():
    raw = os.getenv('MINI_APP_URL', '').strip()
    if not raw:
        return None
    url = urlsplit(raw)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('MINI_APP_URL must be an HTTPS page without credentials, query or fragment')
    host = url.hostname.lower()
    if host in {'localhost', 'localhost.localdomain'} or host.endswith(('.local', '.localhost')):
        raise ValueError('Telegram Mini App requires a public HTTPS host')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError('Telegram Mini App requires a public HTTPS host')
    if url.port not in {None, 443}:
        raise ValueError('Telegram Mini App URL must use the default HTTPS port')
    return raw


def launch_button(chat_type):
    if chat_type != 'private':
        return None
    url = configured_url()
    if url:
        from telegram import InlineKeyboardButton, WebAppInfo
        return InlineKeyboardButton('🦉 Открыть Mini App', web_app=WebAppInfo(url), style='success')


def direct_mafia_link(bot_username, chat_id):
    """Build an official Main Mini App deep link for a group lobby."""
    return deep_link(bot_username, 'mafia', chat_id)


# Страницы Mini App, на которые можно вести ссылкой (?startapp=<страница>).
LAUNCH_PAGES = ('home', 'chats', 'rating', 'profile', 'achievements', 'history')


def _bot_username(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_]{5,32}', value):
        raise ValueError('Telegram bot username is unavailable')
    return value


def deep_link(bot_username, target, chat_id=None):
    """Официальная ссылка на Mini App с параметром запуска.

    `target` — страница из белого списка либо 'chat' / 'mafia' вместе с id группы
    (у групп он отрицательный, в ссылку уходит модуль). Требует настроенного
    MINI_APP_URL и зарегистрированного Main Mini App в BotFather.
    """
    if not configured_url():
        return None
    username = _bot_username(bot_username)
    if target in {'chat', 'mafia'}:
        if not isinstance(chat_id, int) or isinstance(chat_id, bool) or not -(2**52) < chat_id < 0:
            raise ValueError('Групповые ссылки Mini App требуют отрицательный id группы')
        return f'https://t.me/{username}?startapp={target}_n{abs(chat_id)}'
    if target not in LAUNCH_PAGES:
        raise ValueError('Неизвестная страница Mini App')
    return f'https://t.me/{username}?startapp={target}'
