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
    if not configured_url():
        return None
    if not isinstance(bot_username, str) or not re.fullmatch(r'[A-Za-z0-9_]{5,32}', bot_username):
        raise ValueError('Telegram bot username is unavailable')
    if not isinstance(chat_id, int) or not -(2**52) < chat_id < 0:
        raise ValueError('Mafia direct links require a Telegram group ID')
    return f'https://t.me/{bot_username}?startapp=mafia_n{abs(chat_id)}'
