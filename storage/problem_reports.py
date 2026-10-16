"""Player problem reports: strict input handling, screenshot sanitising, limits and storage.

Everything the client sends is untrusted. Only a whitelist of context keys survives, screenshots
are re-encoded (no EXIF/ICC/XMP, <=1600 px) and the owner notification goes through the outbox.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import io
import ipaddress
import json
import math
import os
import re
import weakref
from uuid import UUID

from sqlalchemy import func, select, text

from .mini_app import MiniAppError
from .models import ProblemReport, ProblemReportImage
from .notifications import NotificationQueue

TEXT_MAX = 2000
IMAGES_MAX = 3
IMAGE_BYTES_MAX = 1_572_864
IMAGE_SIDE_MAX = 1600
IMAGE_PIXELS_MAX = 16_000_000
IMAGE_SIDE_INPUT_MAX = 4096
IMAGE_RATIO_MAX = 20
DECODE_CONCURRENCY = 2
GLOBAL_PER_HOUR = 60
BODY_BYTES_MAX = 6_500_000
ACCOUNT_PER_HOUR = 5
ACCOUNT_PER_DAY = 20
IP_PER_DAY = 30
IMAGES_DELAY_SECONDS = 2
KIND_TEXT = 'problem_report.text'
KIND_IMAGES = 'problem_report.images'
STATUSES = ('new', 'in_progress', 'done')

_CONTROL = re.compile('[\x00-\x08\x0b-\x1f\x7f\u200e\u200f\u202a-\u202e\u2066-\u2069]')
_BUILD = re.compile(r'[^0-9A-Za-z._-]')


def build_commit() -> str:
    value = _BUILD.sub('', (os.getenv('MQB_BUILD_COMMIT') or '').strip())[:40]
    return value or 'unknown'


def meta() -> dict:
    return {'build': build_commit(), 'text_max': TEXT_MAX, 'images_max': IMAGES_MAX,
            'image_bytes_max': IMAGE_BYTES_MAX, 'image_side_max': IMAGE_SIDE_MAX}


def report_chat_id() -> int | None:
    raw = (os.getenv('MQB_PROBLEM_REPORT_CHAT_ID') or '').strip()
    if not re.fullmatch(r'-?[0-9]{1,18}', raw):
        return None
    return int(raw) or None


_PROCESS_KEY = os.urandom(32)


def client_key(ip: str) -> str:
    """Normalise an address for limiting: IPv6 collapses to its /64 so one host cannot rotate suffixes."""
    try:
        address = ipaddress.ip_address((ip or '').strip())
    except ValueError:
        return ip or ''
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f'{address}/64', strict=False).network_address) + '/64'
    return str(address)


def _ip_key(bot_token: str) -> bytes:
    secret = (os.getenv('MQB_PROBLEM_REPORT_IP_SECRET') or '').encode()
    if len(secret) >= 32:
        return hashlib.sha256(b'problem-report-ip-secret:' + secret).digest()
    if bot_token:
        return hashlib.sha256(b'problem-report-ip:' + bot_token.encode()).digest()
    return _PROCESS_KEY  # offline/no token: never a public constant


def ip_hash(bot_token: str, ip: str) -> str:
    return hmac.new(_ip_key(bot_token), client_key(ip).encode(), hashlib.sha256).hexdigest()[:64]


# ---------------------------------------------------------------- context

def _string(value, limit):
    if not isinstance(value, str):
        return None
    return _CONTROL.sub('', value).strip()[:limit]


def _number(value, low=0, high=10000):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if not math.isfinite(value):
            return None
        value = min(max(value, low), high)
        return int(value) if float(value).is_integer() else round(float(value), 3)
    except OverflowError:
        return None


def _flag(value):
    return value if isinstance(value, bool) else None


def _group(value, keys, convert):
    if not isinstance(value, dict):
        return None
    result = {}
    for key in keys:
        item = convert(value.get(key))
        if item is not None:
            result[key] = item
    return result or None


def sanitize_context(raw) -> dict:
    """Keep only known keys with normalised types; anything else (initData, cookies, ...) is dropped."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, limit in (('screen', 64), ('title', 80), ('user_agent', 400), ('platform', 32),
                       ('tg_version', 16), ('tg_platform', 32), ('client_time', 40), ('language', 16)):
        item = _string(raw.get(key), limit)
        if item is not None:
            out[key] = item
    path = _string(raw.get('path'), 2000)
    if path is not None:
        out['path'] = path.split('?', 1)[0].split('#', 1)[0][:200]
    for key in ('telegram', 'fullscreen'):
        if _flag(raw.get(key)) is not None:
            out[key] = raw[key]
    sides = ('top', 'bottom', 'left', 'right')
    for key, names, convert in (
            ('safe_area', sides, _number), ('content_safe_area', sides, _number),
            ('css_safe', ('top', 'bottom'), _number), ('inset_fallback', ('top', 'bottom'), _flag),
            ('viewport', ('width', 'height'), _number), ('screen_size', ('width', 'height'), _number)):
        group = _group(raw.get(key), names, convert)
        if group:
            out[key] = group
    dpr = _number(raw.get('dpr'))
    if dpr is not None:
        out['dpr'] = dpr
    return out


# ---------------------------------------------------------------- images

def sanitize_image(encoded) -> tuple[bytes, int, int]:
    """Decode a base64 screenshot and return clean JPEG bytes with their size."""
    if not isinstance(encoded, str):
        raise MiniAppError(400, 'Некорректная картинка', code='image_invalid')
    if len(encoded) > IMAGE_BYTES_MAX * 4 // 3 + 16:
        raise MiniAppError(413, 'Картинка слишком большая', code='image_too_large')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise MiniAppError(400, 'Некорректная кодировка картинки', code='image_base64') from None
    if len(raw) > IMAGE_BYTES_MAX:
        raise MiniAppError(413, 'Картинка слишком большая', code='image_too_large')
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(raw), formats=['JPEG', 'PNG', 'WEBP']) as image:
            if getattr(image, 'is_animated', False) or getattr(image, 'n_frames', 1) > 1:
                raise MiniAppError(415, 'Анимированные картинки не поддерживаются', code='image_animated')
            width, height = image.size
            if (width * height > IMAGE_PIXELS_MAX or max(width, height) > IMAGE_SIDE_INPUT_MAX
                    or min(width, height) < 1):
                raise MiniAppError(415, 'Картинка слишком большая по размеру', code='image_pixels')
            if max(width, height) > IMAGE_RATIO_MAX * min(width, height):
                raise MiniAppError(415, 'Слишком вытянутая картинка: соотношение сторон больше 20:1',
                                   code='image_ratio')
            if image.format == 'JPEG':
                image.draft('RGB', (IMAGE_SIDE_MAX, IMAGE_SIDE_MAX))  # cheap DCT downscale before decoding
            image.load()
            image = ImageOps.exif_transpose(image)
            if image.mode in ('RGBA', 'LA', 'PA') or 'transparency' in image.info:
                rgba = image.convert('RGBA')
                flat = Image.new('RGB', rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.getchannel('A'))
                image = flat
            else:
                image = image.convert('RGB')
            # Drop every metadata chunk (JPEG COM, PNG tEXt, XMP...) so nothing is carried over.
            image.info.clear()
            image.thumbnail((IMAGE_SIDE_MAX, IMAGE_SIDE_MAX))
            for quality in (85, 70, 55):
                buffer = io.BytesIO()
                image.save(buffer, 'JPEG', quality=quality, optimize=True, comment=b'')
                if buffer.tell() <= IMAGE_BYTES_MAX:
                    return buffer.getvalue(), image.width, image.height
    except MiniAppError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError,
            MemoryError, EOFError, OverflowError):
        raise MiniAppError(415, 'Нужна картинка JPEG, PNG или WebP', code='image_type') from None
    raise MiniAppError(413, 'Картинка слишком большая', code='image_too_large')


_semaphores = weakref.WeakKeyDictionary()


async def prepare_images(encoded_images) -> list[tuple[bytes, int, int]]:
    """Sanitise screenshots off the event loop, at most DECODE_CONCURRENCY decodes at a time.

    Runs before authentication/DB work so no pooled connection is held while Pillow works.
    """
    if not encoded_images:
        return []
    loop = asyncio.get_running_loop()
    semaphore = _semaphores.get(loop)
    if semaphore is None:
        semaphore = _semaphores[loop] = asyncio.Semaphore(DECODE_CONCURRENCY)
    result = []
    for encoded in encoded_images:
        async with semaphore:
            result.append(await asyncio.to_thread(sanitize_image, encoded))
    return result


# ---------------------------------------------------------------- request

def parse_body(raw: bytes):
    """Return ``(request_id, text, context, images)`` from the JSON body (images still base64)."""
    from web.mini_auth import unique_object
    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
        if not isinstance(value, dict) or not {'request_id', 'text'} <= set(value) <= {
                'request_id', 'text', 'context', 'images'}:
            raise ValueError()
        if not isinstance(value['request_id'], str) or not isinstance(value['text'], str):
            raise ValueError()
        request_id = UUID(value['request_id'])
        images = value.get('images') or []
        if not isinstance(images, list):
            raise ValueError()
    except (ValueError, UnicodeError, RecursionError, TypeError):
        raise MiniAppError(400, 'Некорректные параметры отчёта', code='invalid') from None
    body = _CONTROL.sub('', value['text']).strip()
    if not body or len(body) > TEXT_MAX:
        raise MiniAppError(400, f'Опиши проблему (до {TEXT_MAX} символов)', code='text')
    if len(images) > IMAGES_MAX:
        raise MiniAppError(413, f'Не больше {IMAGES_MAX} картинок', code='too_many_images')
    return request_id, body, sanitize_context(value.get('context')), images


def _lock_key(scope: str, value: str) -> int:
    digest = hashlib.sha256(f'problem-report:{scope}:{value}'.encode()).digest()
    return int.from_bytes(digest[:8], 'big', signed=True)


async def _count_since(session, column, value, since):
    return await session.scalar(select(func.count()).select_from(ProblemReport)
                                .where(column == value, ProblemReport.created_at > since))


async def create_report(session, who, *, request_id, body, context, images, client_ip_hash,
                        now=None) -> tuple[int, bool]:
    """Store one report in the caller's transaction. Returns ``(report_id, created)``."""
    now = now or datetime.now(timezone.utc)
    account_id = UUID(who.account_id)
    existing = await session.scalar(select(ProblemReport.id).where(
        ProblemReport.account_id == account_id, ProblemReport.request_id == request_id))
    if existing is not None:
        return existing, False
    if session.bind.dialect.name == 'postgresql':
        for scope, value in (('account', who.account_id), ('ip', client_ip_hash)):
            # Never queue behind a busy lock while holding a pooled connection: busy means too many at once.
            if not await session.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'),
                                        {'key': _lock_key(scope, value)}):
                raise MiniAppError(429, 'Слишком много отчётов, попробуй позже', code='rate_limited')
        # A concurrent twin of this request_id may have committed while we waited for the lock.
        existing = await session.scalar(select(ProblemReport.id).where(
            ProblemReport.account_id == account_id, ProblemReport.request_id == request_id))
        if existing is not None:
            return existing, False
    day = now - timedelta(hours=24)
    if (await _count_since(session, ProblemReport.account_id, account_id, now - timedelta(hours=1)) >= ACCOUNT_PER_HOUR
            or await _count_since(session, ProblemReport.account_id, account_id, day) >= ACCOUNT_PER_DAY
            or await _count_since(session, ProblemReport.ip_hash, client_ip_hash, day) >= IP_PER_DAY
            or await session.scalar(select(func.count()).select_from(ProblemReport).where(
                ProblemReport.created_at > now - timedelta(hours=1))) >= GLOBAL_PER_HOUR):
        raise MiniAppError(429, 'Слишком много отчётов, попробуй позже', code='rate_limited')
    report = ProblemReport(
        account_id=account_id, request_id=request_id, channel=who.channel[:16],
        telegram_user_id=who.telegram_user_id, display_name=(who.display_name or '')[:120], text=body,
        context=context, build=build_commit(), ip_hash=client_ip_hash, created_at=now)
    session.add(report)
    await session.flush()
    for position, (data, width, height) in enumerate(images):
        session.add(ProblemReportImage(report_id=report.id, position=position, content_type='image/jpeg',
                                       width=width, height=height, data=data))
    chat_id = report_chat_id()
    if chat_id is not None:
        await NotificationQueue.enqueue_in(
            session, kind=KIND_TEXT, dedupe_key=f'problem_report:{report.id}:text',
            chat_id=chat_id, payload={'report_id': report.id}, available_at=now)
        if images:
            await NotificationQueue.enqueue_in(
                session, kind=KIND_IMAGES, dedupe_key=f'problem_report:{report.id}:images',
                chat_id=chat_id, payload={'report_id': report.id},
                available_at=now + timedelta(seconds=IMAGES_DELAY_SECONDS))
    return report.id, True
