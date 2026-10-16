"""Public invite links only. Never resolves an account from a Telegram username.

An invite hint requests no permissions by itself. Recipient must sign in and
explicitly request/accept neighbor membership through existing server commands.
"""
import ipaddress
import re
import secrets
from hashlib import sha256
from urllib.parse import urlsplit, urlencode
from uuid import UUID
from .domain import need

MAX_ACTIVE_SHARE_INVITES_PER_FARM = 20


def safe_public_origin(origin):
    parsed = urlsplit(origin or '')
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        return None
    if parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        return None
    host = parsed.hostname.lower()
    if host == 'localhost' or host.endswith(('.localhost', '.local')):
        return None
    try:
        if not ipaddress.ip_address(host).is_global:
            return None
    except ValueError:
        pass
    return f'https://{parsed.netloc}'


def new_invite_token():
    """Return a 256-bit opaque URL-safe invite token (43 chars, no padding)."""
    return secrets.token_urlsafe(32)


def invite_digest(token):
    return sha256(token.encode('ascii')).hexdigest()


def invite_info(farm_id, farm_name, *, token=None, origin='', bot_username='', mini_app_short_name='play', recipient=''):
    code = str(UUID(str(farm_id)))
    token = token or code
    public = safe_public_origin(origin)
    web_url = public + '/app/farm?' + urlencode({'invite': token}) if public else None
    bot = (bot_username or '').lstrip('@')
    need(not bot or bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}', bot)),
         'bot_configuration', 'Некорректное имя бота в настройках сервера.', 503)
    short_name = mini_app_short_name or 'play'
    need(bool(re.fullmatch(r'[A-Za-z0-9_]{3,30}', short_name)),
         'bot_configuration', 'Некорректное имя Mini App в настройках сервера.', 503)
    mini_url = 'https://t.me/' + bot + '/' + short_name + '?' + urlencode({'startapp': 'farm_' + token}) if bot else None
    invitation = mini_url or web_url
    text = f'Приглашаю тебя на ферму «{farm_name}» в QuizzyWizzy! 🌱\nОткрой ссылку и подтверди приглашение в игре.'
    draft = text + ('\n' + invitation if invitation else '\nДля локальной сборки нужно подключиться к тому же серверу.')
    username = (recipient or '').strip().lstrip('@')
    need(not username or bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}', username)),
         'invalid_username', 'Укажи Telegram @username: 5–32 латинских символа, цифры и подчёркивание.', 422)
    return dict(code=code, token=token, farm_name=farm_name, web_url=web_url, mini_app_url=mini_url,
                share_url=('https://t.me/share/url?' + urlencode({'url': invitation, 'text': text})) if invitation else None,
                direct_url=('https://t.me/' + username + '?' + urlencode({'text': draft})) if username else None,
                text=draft, local_only=not bool(invitation))
