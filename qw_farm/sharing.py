"""Public invite links only. Never resolves an account from a Telegram username.

An invite hint requests no permissions by itself. Recipient must sign in and
explicitly request/accept neighbor membership through existing server commands.
"""
import base64
import hmac
import ipaddress
import os
import re
import secrets
from hashlib import sha256
from urllib.parse import urlsplit, urlencode
from uuid import UUID
from .domain import need

MAX_ACTIVE_SHARE_INVITES_PER_FARM = 20
# One reusable link per farm (owner decision 18.10.2026): up to 10 neighbors join through it,
# it lives 30 days; a full or expired link is replaced automatically, «Сменить ссылку» replaces it at once.
SHARE_INVITE_MAX_USES = 10
SHARE_INVITE_TTL = 30 * 24 * 60 * 60
# Used only when QW_FARM_INVITE_SECRET is not configured: links stay valid by digest,
# but after a restart the server cannot recompute them and simply issues a new one.
_PROCESS_SECRET = secrets.token_bytes(32)


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


def new_invite_nonce():
    return secrets.token_hex(16)


def invite_secret(value=None):
    """Bytes of the configured secret (at least 32 characters) or the per-process fallback."""
    value = value if value is not None else os.getenv('QW_FARM_INVITE_SECRET', '')
    return value.encode('utf-8') if len(value) >= 32 else _PROCESS_SECRET


def link_token(secret, farm_id, nonce):
    """Recomputable 43-char URL-safe token: HMAC-SHA256(secret, farm id + random per-link nonce)."""
    mac = hmac.new(secret, f'farm-invite:{UUID(str(farm_id))}:{nonce}'.encode('ascii'), sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b'=').decode('ascii')


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
