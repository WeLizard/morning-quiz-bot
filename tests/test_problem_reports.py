"""Problem reports: input hygiene, screenshots, limits, outbox delivery and the admin routes.

Pure checks run anywhere. Storage-level checks use the disposable PostgreSQL (TEST_DATABASE_URL, like the
neighbouring acceptance tests); without it they fall back to an in-memory SQLite when ``aiosqlite`` is
installed (the PostgreSQL-only advisory locks are then skipped) and are skipped otherwise. The checks that go
through the real guest/Telegram principals need PostgreSQL.
"""
import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import io
import json
import os
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
import httpx
import pytest
from sqlalchemy import func, select
from telegram.error import RetryAfter, TelegramError

from handlers import problem_report_delivery as delivery
from storage import problem_reports as reports
from storage.mini_app import MiniAppError
from storage.models import Account, NotificationOutbox, ProblemReport, ProblemReportImage
from storage.notifications import NotificationQueue
from tests.test_admin_auth import TOKEN as ADMIN_TOKEN, login as admin_login
from tests.test_guest_accounts import HEADERS, ORIGIN
from tests.test_mini_app import TOKEN
from web.admin_auth import AdminAuth, install_admin_auth
from web.mini_app import MiniAppSettings, create_app
from web.principal import Principal
from web.problem_reports_admin import make_problem_reports_router

PNG_MODES = ('RGB', 'RGBA')


def png(size=(8, 8), mode='RGBA', color=(200, 30, 30, 128)):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new(mode, size, color).save(buffer, 'PNG')
    return buffer.getvalue()


def b64(data):
    return base64.b64encode(data).decode()


def jpeg_with_exif(size=(40, 20), orientation=6):
    from PIL import Image
    exif = Image.Exif()
    exif[0x0112] = orientation
    exif[0x8825] = {1: 'N', 2: (55.0, 45.0, 0.0), 3: 'E', 4: (37.0, 37.0, 0.0)}  # GPS IFD
    exif[0x010F] = 'PrivateCam'
    image = Image.new('RGB', size, (10, 120, 200))
    buffer = io.BytesIO()
    image.save(buffer, 'JPEG', exif=exif)
    return buffer.getvalue()


# ---------------------------------------------------------------- pure checks

def test_meta_and_build_commit_are_sanitised(monkeypatch):
    monkeypatch.delenv('MQB_BUILD_COMMIT', raising=False)
    assert reports.meta() == {'build': 'unknown', 'text_max': 2000, 'images_max': 3,
                              'image_bytes_max': 1572864, 'image_side_max': 1600}
    monkeypatch.setenv('MQB_BUILD_COMMIT', ' 50b2b94;rm -rf /\n')
    assert reports.build_commit() == '50b2b94rm-rf'
    monkeypatch.setenv('MQB_BUILD_COMMIT', 'a' * 100)
    assert reports.build_commit() == 'a' * 40


def test_report_chat_id_is_optional_and_validated(monkeypatch):
    for value, expected in (('621817842', 621817842), (' -100123 ', -100123), ('', None), ('abc', None),
                            ('0', None), ('12 3', None)):
        monkeypatch.setenv('MQB_PROBLEM_REPORT_CHAT_ID', value)
        assert reports.report_chat_id() == expected
    monkeypatch.delenv('MQB_PROBLEM_REPORT_CHAT_ID')
    assert reports.report_chat_id() is None


def test_ip_hash_is_keyed_stable_and_not_the_ip():
    first = reports.ip_hash('token-a', '203.0.113.7')
    assert first == reports.ip_hash('token-a', '203.0.113.7')
    assert first != reports.ip_hash('token-b', '203.0.113.7') and first != reports.ip_hash('token-a', '203.0.113.8')
    assert len(first) == 64 and '203.0.113.7' not in first


def test_context_keeps_known_keys_only_and_strips_query_hash_and_initdata():
    context = reports.sanitize_context({
        'screen': 'farm', 'title': 'Ферма', 'path': '/app/farm?tgWebAppData=hash%3Dabc&user=1#frag',
        'user_agent': 'U' * 999, 'platform': 'android', 'telegram': True, 'tg_version': '8.0', 'tg_platform': 'android',
        'fullscreen': False, 'safe_area': {'top': 0, 'bottom': 3.5, 'left': 'x', 'right': None, 'evil': 1},
        'content_safe_area': {'top': -5, 'bottom': 99999}, 'css_safe': {'top': 28, 'bottom': 48},
        'inset_fallback': {'top': False, 'bottom': True}, 'viewport': {'width': 412, 'height': 915},
        'screen_size': {'width': 412, 'height': 915}, 'dpr': 2.625, 'client_time': '2026-10-16T07:40:00.000+03:00',
        'language': 'ru-RU', 'init_data': 'query_id=AA&hash=deadbeef', 'initData': 'x', 'cookie': 'mqb_guest=1',
        'token': 'secret', 'nested': {'initData': 'y'}})
    assert set(context) == {'screen', 'title', 'path', 'user_agent', 'platform', 'telegram', 'tg_version',
                            'tg_platform', 'fullscreen', 'safe_area', 'content_safe_area', 'css_safe',
                            'inset_fallback', 'viewport', 'screen_size', 'dpr', 'client_time', 'language'}
    assert context['path'] == '/app/farm' and len(context['user_agent']) == 400
    assert context['safe_area'] == {'top': 0, 'bottom': 3.5}
    assert context['content_safe_area'] == {'top': 0, 'bottom': 10000}
    assert context['dpr'] == 2.625
    dump = json.dumps(context)
    for leaked in ('tgWebAppData', 'deadbeef', 'secret', 'mqb_guest', 'initData', 'frag'):
        assert leaked not in dump


def test_context_rejects_wrong_types_and_junk():
    assert reports.sanitize_context(None) == {} and reports.sanitize_context([1]) == {}
    assert reports.sanitize_context({'screen': 5, 'telegram': 'yes', 'dpr': float('nan'), 'viewport': 'x',
                                     'safe_area': {'top': True}, 'title': '  \x00Ферма\x07 '}) == {'title': 'Ферма'}


def test_image_is_reencoded_without_exif_gps_and_rotated():
    data, width, height = reports.sanitize_image(b64(jpeg_with_exif((40, 20), orientation=6)))
    from PIL import Image
    with Image.open(io.BytesIO(data)) as clean:
        assert clean.format == 'JPEG' and (clean.width, clean.height) == (width, height) == (20, 40)
        assert not clean.getexif() and 'exif' not in clean.info and 'icc_profile' not in clean.info
    assert b'PrivateCam' not in data and b'Exif' not in data


def test_image_is_downscaled_flattened_and_stays_small():
    data, width, height = reports.sanitize_image(b64(png((3200, 1600), 'RGBA', (255, 0, 0, 0))))
    assert (width, height) == (1600, 800) and len(data) <= reports.IMAGE_BYTES_MAX
    from PIL import Image
    with Image.open(io.BytesIO(data)) as flat:
        assert flat.mode == 'RGB' and flat.getpixel((5, 5))[0] > 240 and flat.getpixel((5, 5))[1] > 240  # white, not black


def test_image_metadata_comments_do_not_survive():
    from PIL import Image, PngImagePlugin
    jpeg = io.BytesIO()
    Image.new('RGB', (30, 30), (1, 2, 3)).save(jpeg, 'JPEG', comment=b'SECRET-JPEG')
    assert b'SECRET-JPEG' in jpeg.getvalue()
    info = PngImagePlugin.PngInfo()
    info.add_text('comment', 'SECRET-PNG')
    info.add_text('Author', 'SECRET-AUTHOR')
    image = io.BytesIO()
    Image.new('RGB', (30, 30), (1, 2, 3)).save(image, 'PNG', pnginfo=info)
    assert b'SECRET-PNG' in image.getvalue()
    for source in (jpeg.getvalue(), image.getvalue()):
        data, _, _ = reports.sanitize_image(b64(source))
        assert b'SECRET' not in data
        with Image.open(io.BytesIO(data)) as clean:
            assert not clean.info.get('comment')


def test_png_with_trns_is_flattened_on_white_and_odd_shapes_are_refused():
    from PIL import Image
    for mode, color, trns in (('RGB', (0, 0, 0), (0, 0, 0)), ('L', 0, 0)):
        buffer = io.BytesIO()
        Image.new(mode, (16, 16), color).save(buffer, 'PNG', transparency=trns)
        data, _, _ = reports.sanitize_image(b64(buffer.getvalue()))
        with Image.open(io.BytesIO(data)) as flat:
            assert min(flat.convert('RGB').getpixel((4, 4))) > 240, mode
    for size, code in (((2100, 100), 'image_ratio'), ((100, 2100), 'image_ratio'), ((5000, 4000), 'image_pixels'),
                       ((4097, 100), 'image_pixels')):
        with pytest.raises(MiniAppError) as error:
            reports.sanitize_image(b64(png(size, 'RGB', (1, 2, 3))))
        assert (error.value.status, error.value.code) == (415, code), size
    assert reports.sanitize_image(b64(png((2000, 100), 'RGB', (1, 2, 3))))[1:] == (1600, 80)


def test_huge_numbers_in_context_do_not_crash_and_bidi_marks_are_removed():
    context = reports.sanitize_context({'dpr': 10 ** 400, 'viewport': {'width': 10 ** 400, 'height': 5},
                                        'safe_area': {'top': -10 ** 400}, 'title': 'a\u202eb\u2066c\u200fd'})
    assert context == {'title': 'abcd', 'viewport': {'height': 5}}
    parsed = reports.parse_body(json.dumps({'request_id': str(uuid4()), 'text': '\u202eevil\u200e',
                                            'context': {'dpr': 10 ** 400}}).encode())
    assert parsed[1] == 'evil' and parsed[2] == {}


def test_ip_hash_normalises_ipv6_and_never_uses_a_public_constant(monkeypatch):
    import hashlib
    import hmac
    monkeypatch.delenv('MQB_PROBLEM_REPORT_IP_SECRET', raising=False)
    token = 't:' + 'a' * 30
    assert reports.ip_hash(token, '2001:db8:1:2:aaaa::1') == reports.ip_hash(token, '2001:db8:1:2:bbbb::9')
    assert reports.ip_hash(token, '2001:db8:1:3::1') != reports.ip_hash(token, '2001:db8:1:2::1')
    assert reports.ip_hash(token, '::ffff:203.0.113.7') == reports.ip_hash(token, '203.0.113.7')
    offline = reports.ip_hash('', '203.0.113.7')
    assert offline == reports.ip_hash('', '203.0.113.7')
    for known in (b'', b'problem-report-ip:'):
        assert offline != hmac.new(hashlib.sha256(known).digest(), b'203.0.113.7', hashlib.sha256).hexdigest()[:64]
    token_based = reports.ip_hash(token, '203.0.113.7')
    monkeypatch.setenv('MQB_PROBLEM_REPORT_IP_SECRET', 'short')
    assert reports.ip_hash(token, '203.0.113.7') == token_based  # shorter than 32 bytes is ignored
    monkeypatch.setenv('MQB_PROBLEM_REPORT_IP_SECRET', 'k' * 40)
    assert reports.ip_hash(token, '203.0.113.7') != token_based


def _animated(fmt):
    from PIL import Image
    frames = [Image.new('RGB', (10, 10), color) for color in ((255, 0, 0), (0, 255, 0))]
    buffer = io.BytesIO()
    frames[0].save(buffer, fmt, save_all=True, append_images=frames[1:], duration=50, loop=0)
    return buffer.getvalue()


@pytest.mark.parametrize('payload, status', [
    (b'just text', 415), (b'<html><script>alert(1)</script></html>', 415),
    (b'<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>', 415),
    (b'GIF89a\x01\x00\x01\x00\x00\x00\x00;', 415), (_animated('GIF'), 415), (_animated('WEBP'), 415),
    (png()[:30], 415), (b'', 415)])
def test_image_rejects_non_images_animations_and_truncated_files(payload, status):
    with pytest.raises(MiniAppError) as error:
        reports.sanitize_image(b64(payload))
    assert error.value.status == status


def test_image_rejects_bad_base64_oversize_and_pixel_bombs(monkeypatch):
    for bad in ('***not base64***', 'abc', 'data:image/png;base64,' + b64(png()), 5, None):
        with pytest.raises(MiniAppError) as error:
            reports.sanitize_image(bad)
        assert error.value.status == 400
    with pytest.raises(MiniAppError) as error:
        reports.sanitize_image(b64(b'\x00' * (reports.IMAGE_BYTES_MAX + 1)))
    assert error.value.status == 413
    with pytest.raises(MiniAppError) as error:
        reports.sanitize_image('A' * (reports.IMAGE_BYTES_MAX * 2))
    assert error.value.status == 413
    monkeypatch.setattr(reports, 'IMAGE_PIXELS_MAX', 50)
    with pytest.raises(MiniAppError) as error:
        reports.sanitize_image(b64(png((10, 10))))
    assert error.value.status == 415


def test_body_parser_validates_shape_text_and_image_count():
    rid = str(uuid4())
    request_id, text, context, images = reports.parse_body(json.dumps(
        {'request_id': rid, 'text': '  не работает  ', 'context': {'screen': 'farm', 'x': 1}}).encode())
    assert (str(request_id), text, context, images) == (rid, 'не работает', {'screen': 'farm'}, [])
    for body, status in (
            (b'not json', 400), (b'[]', 400), (json.dumps({'text': 'a'}).encode(), 400),
            (json.dumps({'request_id': 'nope', 'text': 'a'}).encode(), 400),
            (json.dumps({'request_id': rid, 'text': '   '}).encode(), 400),
            (json.dumps({'request_id': rid, 'text': 'x' * 2001}).encode(), 400),
            (json.dumps({'request_id': rid, 'text': 5}).encode(), 400),
            (json.dumps({'request_id': rid, 'text': 'a', 'extra': 1}).encode(), 400),
            (json.dumps({'request_id': rid, 'text': 'a', 'images': 'x'}).encode(), 400),
            (json.dumps({'request_id': rid, 'text': 'a', 'images': ['a'] * 4}).encode(), 413),
            (b'{"request_id": "%s", "text": "a", "text": "b"}' % rid.encode(), 400)):
        with pytest.raises(MiniAppError) as error:
            reports.parse_body(body)
        assert error.value.status == status, body
    assert reports.parse_body(json.dumps({'request_id': rid, 'text': 'x' * 2000}).encode())[1] == 'x' * 2000


def _stored(**overrides):
    values = dict(
        id=12, display_name='Ирина', channel='telegram', telegram_user_id=123, text='сломалось *_[<b>',
        build='50b2b94', account_id='acc-1', created_at=datetime(2026, 10, 16, 4, 40, tzinfo=timezone.utc),
        context={'screen': 'farm', 'title': 'Ферма', 'path': '/app/farm', 'telegram': True, 'tg_version': '8.0',
                 'tg_platform': 'android', 'fullscreen': False, 'viewport': {'width': 412, 'height': 915},
                 'screen_size': {'width': 412, 'height': 915}, 'dpr': 2.625, 'safe_area': {'top': 0, 'bottom': 0},
                 'content_safe_area': {'top': 0, 'bottom': 0}, 'css_safe': {'top': 28, 'bottom': 48},
                 'inset_fallback': {'top': False, 'bottom': True}, 'user_agent': 'UA <i>'})
    values.update(overrides)
    return SimpleNamespace(**values)


def test_rendered_message_matches_the_contract_and_escapes_everything():
    text = delivery.render_report(_stored(display_name='<b>Ира</b> & *_'), 2)
    lines = text.split('\n')
    assert lines[0] == '🐞 <b>Отчёт №12</b> · &lt;b&gt;Ира&lt;/b&gt; &amp; *_ (telegram, tg 123)'
    assert lines[1] == 'сломалось *_[&lt;b&gt;'
    assert '<b>Контекст</b>' in lines
    for expected in ('Экран: Ферма (farm) · /app/farm', 'Версия: 50b2b94', 'Telegram 8.0 · android · полный экран: нет',
                     'Окно 412×915 · экран 412×915 · dpr 2.63',
                     'Safe-area: tg ↑0 ↓0 · content ↑0 ↓0 · css ↑28 ↓48 (запасной низ)', 'UA: UA &lt;i&gt;',
                     'Аккаунт: acc-1 · время: 16.10 07:40 МСК', 'Картинок: 2'):
        assert expected in lines, expected
    assert '<i>' not in text


def test_rendered_message_counts_utf16_units_for_astral_text():
    import html
    import re

    def units(markup):
        return len(html.unescape(re.sub(r'</?b>', '', markup)).encode('utf-16-le')) // 2

    mixed = delivery.render_report(_stored(text='😀' * 1000 + 'x' * 1000, context={'user_agent': '😀' * 200}), 3)
    assert units(mixed) <= 4096 and mixed.count('<b>') == mixed.count('</b>') == 2
    emoji = delivery.render_report(_stored(text='😀' * 2100, context={}), 0)
    assert units(emoji) <= 4096 and '😀…' in emoji and emoji.count('<b>') == 2


def test_rendered_message_stays_within_telegram_limit_after_parsing():
    text = delivery.render_report(_stored(text='<' * 2000, context={'user_agent': 'U' * 400, 'screen': 'x' * 64,
                                                                    'title': 't' * 80, 'path': '/' * 200}), 3)
    import html
    import re
    plain = html.unescape(re.sub(r'</?b>', '', text))
    assert len(plain) <= 4096
    assert delivery.render_report(_stored(text='a' * 2000, context={}), 0)


# ---------------------------------------------------------------- database fixtures

def _sqlite_database():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool
    engine = create_async_engine('sqlite+aiosqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    database = SimpleNamespace(engine=engine)
    database.session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    @asynccontextmanager
    async def transaction():
        async with database.session_factory() as session:
            async with session.begin():
                yield session
    database.transaction = transaction
    return database


@asynccontextmanager
async def report_database():
    url = os.getenv('TEST_DATABASE_URL')
    if url:
        from storage.database import normalize_database_url
        from tests.local_database import isolated_database
        async with isolated_database(normalize_database_url(url)) as (db, _):
            yield db
        return
    pytest.importorskip('aiosqlite', reason='needs TEST_DATABASE_URL or aiosqlite')
    from storage.models import Base
    database = _sqlite_database()
    tables = [Base.metadata.tables[name] for name in
              ('accounts', 'problem_reports', 'problem_report_images', 'problem_error_hits', 'notification_outbox')]
    async with database.engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    try:
        yield database
    finally:
        await database.engine.dispose()


async def make_who(db, channel='guest', name='Ира', telegram_user_id=None):
    account_id = uuid4()
    async with db.transaction() as session:
        session.add(Account(id=account_id, display_name=name))
    return Principal(str(account_id), name, channel, telegram_user_id)


async def submit(db, who, *, text='Не работает кнопка', images=(), ip='ip-1', rid=None, now=None, context=None):
    prepared = await reports.prepare_images([b64(item) for item in images])
    async with db.transaction() as session:
        return await reports.create_report(
            session, who, request_id=rid or uuid4(), body=text, context=context or {'screen': 'farm'},
            images=prepared, client_ip_hash=ip, now=now)


async def outbox(db):
    async with db.transaction() as session:
        rows = (await session.execute(select(NotificationOutbox).order_by(NotificationOutbox.kind))).scalars().all()
        return [(row.kind, row.chat_id, row.payload, row.dedupe_key, row.available_at) for row in rows]


# ---------------------------------------------------------------- storage

def test_report_is_stored_idempotent_and_queues_text_then_images(monkeypatch):
    monkeypatch.setenv('MQB_PROBLEM_REPORT_CHAT_ID', '621817842')
    monkeypatch.setenv('MQB_BUILD_COMMIT', '50b2b94')

    async def run():
        async with report_database() as db:
            who = await make_who(db, 'telegram', 'Ирина', 123)
            rid = uuid4()
            report_id, created = await submit(db, who, images=[jpeg_with_exif(), png()], rid=rid)
            assert created
            assert await submit(db, who, images=[], rid=rid) == (report_id, False)
            async with db.transaction() as session:
                row = await session.get(ProblemReport, report_id)
                assert (row.status, row.channel, row.telegram_user_id, row.build, row.display_name) == (
                    'new', 'telegram', 123, '50b2b94', 'Ирина')
                assert row.ip_hash == 'ip-1' and row.context == {'screen': 'farm'}
                stored = (await session.execute(select(ProblemReportImage).where(
                    ProblemReportImage.report_id == report_id).order_by(ProblemReportImage.position))).scalars().all()
                assert [(item.position, item.content_type) for item in stored] == [(0, 'image/jpeg'), (1, 'image/jpeg')]
                assert stored[0].data[:3] == b'\xff\xd8\xff' and (stored[0].width, stored[0].height) == (20, 40)
                assert b'PrivateCam' not in bytes(stored[0].data)
            queued = await outbox(db)
            assert [(kind, chat, payload, key) for kind, chat, payload, key, _ in queued] == [
                ('problem_report.images', 621817842, {'report_id': report_id}, f'problem_report:{report_id}:images'),
                ('problem_report.text', 621817842, {'report_id': report_id}, f'problem_report:{report_id}:text')]
            by_kind = {kind: available for kind, *_, available in queued}
            assert (by_kind['problem_report.images'] - by_kind['problem_report.text']).total_seconds() == pytest.approx(2, abs=0.1)
            text_only, _ = await submit(db, who, text='ещё одно')
            assert [kind for kind, *_ in await outbox(db)].count('problem_report.images') == 1
            assert text_only != report_id
    asyncio.run(run())


def test_without_chat_id_the_report_is_saved_but_no_outbox(monkeypatch):
    monkeypatch.delenv('MQB_PROBLEM_REPORT_CHAT_ID', raising=False)

    async def run():
        async with report_database() as db:
            who = await make_who(db)
            report_id, created = await submit(db, who, images=[png()])
            assert created and report_id
            assert await outbox(db) == []
            monkeypatch.setenv('MQB_PROBLEM_REPORT_CHAT_ID', 'garbage')
            await submit(db, who)
            assert await outbox(db) == []
    asyncio.run(run())


def test_account_limit_is_five_per_hour_and_twenty_per_day(monkeypatch):
    monkeypatch.delenv('MQB_PROBLEM_REPORT_CHAT_ID', raising=False)

    async def run():
        async with report_database() as db:
            who = await make_who(db)
            now = datetime.now(timezone.utc)
            for index in range(5):
                await submit(db, who, ip=f'ip-{index}', now=now)
            with pytest.raises(MiniAppError) as error:
                await submit(db, who, ip='ip-x', now=now)
            assert error.value.status == 429
            async with db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(ProblemReport)) == 5
            other = await make_who(db, name='Другая')
            assert (await submit(db, other, ip='ip-y'))[1]
            # Spread over 22 hours the hourly window stays free, but 20 per 24h still cap the day.
            busy = await make_who(db, name='Много')
            for index in range(20):
                await submit(db, busy, ip=f'ip-b{index}', now=now - timedelta(minutes=70 * (19 - index)))
            with pytest.raises(MiniAppError) as error:
                await submit(db, busy, ip='ip-z', now=now)
            assert error.value.status == 429
            # A replay of an already stored request is not a new report and never hits the limit.
            rid = uuid4()
            fresh = await make_who(db, name='Повтор')
            first, _ = await submit(db, fresh, rid=rid, ip='ip-r', now=now)
            for index in range(4):
                await submit(db, fresh, ip=f'ip-r{index}', now=now)
            assert await submit(db, fresh, rid=rid, ip='ip-r', now=now) == (first, False)
    asyncio.run(run())


def test_global_limit_is_sixty_reports_per_hour(monkeypatch):
    monkeypatch.delenv('MQB_PROBLEM_REPORT_CHAT_ID', raising=False)

    async def run():
        async with report_database() as db:
            now = datetime.now(timezone.utc)
            for index in range(60):
                await submit(db, await make_who(db, name=f'G{index}'), ip=f'ip-g{index}', now=now)
            with pytest.raises(MiniAppError) as error:
                await submit(db, await make_who(db, name='G61'), ip='ip-g61', now=now)
            assert error.value.status == 429
            assert (await submit(db, await make_who(db, name='later'), ip='ip-later', now=now + timedelta(hours=2)))[1]
    asyncio.run(run())


def test_ip_limit_is_thirty_per_day_across_accounts(monkeypatch):
    monkeypatch.delenv('MQB_PROBLEM_REPORT_CHAT_ID', raising=False)

    async def run():
        async with report_database() as db:
            now = datetime.now(timezone.utc)
            for index in range(30):
                who = await make_who(db, name=f'U{index}')
                await submit(db, who, ip='shared-nat', now=now)
            with pytest.raises(MiniAppError) as error:
                await submit(db, await make_who(db, name='31'), ip='shared-nat', now=now)
            assert error.value.status == 429
            assert (await submit(db, await make_who(db, name='other-ip'), ip='another-nat', now=now))[1]
            assert (await submit(db, await make_who(db, name='yesterday'), ip='shared-nat',
                                 now=now + timedelta(hours=25)))[1]
    asyncio.run(run())


# ---------------------------------------------------------------- delivery

class StubBot:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    async def send_message(self, chat_id, text, **kwargs):
        self._call('send_message', chat_id, text=text, **kwargs)

    async def send_photo(self, chat_id, photo, **kwargs):
        self._call('send_photo', chat_id, photo=photo, **kwargs)

    async def send_media_group(self, chat_id, media, **kwargs):
        self._call('send_media_group', chat_id, media=media, **kwargs)

    def _call(self, name, chat_id, **kwargs):
        if self.fail:
            raise self.fail
        self.calls.append((name, chat_id, kwargs))


async def run_dispatcher(db, bot):
    from handlers.mafia_handlers import MafiaHandlers
    handlers = MafiaHandlers.__new__(MafiaHandlers)
    handlers.database = db
    await handlers._deliver_notifications(SimpleNamespace(bot=bot))
    return handlers


def test_outbox_delivery_sends_text_first_then_photo_or_media_group(monkeypatch):
    monkeypatch.setenv('MQB_PROBLEM_REPORT_CHAT_ID', '621817842')
    monkeypatch.setenv('MQB_BUILD_COMMIT', '50b2b94')

    async def run():
        async with report_database() as db:
            who = await make_who(db, 'telegram', 'Ирина *_[<b>', 123)
            one, _ = await submit(db, who, text='плохо *_[<b>', images=[png()],
                                  context={'screen': 'farm', 'title': 'Ферма *_[<b>'})
            many, _ = await submit(db, who, text='ещё', images=[png(), png((9, 9)), jpeg_with_exif()])
            # Make the image items due now so one dispatcher pass sends everything.
            async with db.transaction() as session:
                for row in (await session.execute(select(NotificationOutbox))).scalars():
                    row.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            bot = StubBot()
            await run_dispatcher(db, bot)
            names = [(name, kwargs.get('text', '')[:30]) for name, _, kwargs in bot.calls]
            assert [name for name, _ in names].count('send_message') == 2
            assert {name for name, _ in names} == {'send_message', 'send_photo', 'send_media_group'}
            for name, chat_id, kwargs in bot.calls:
                assert chat_id == 621817842
                if name == 'send_message':
                    assert kwargs['parse_mode'] == 'HTML' and kwargs['link_preview_options'].is_disabled
            first = next(kwargs for name, _, kwargs in bot.calls if name == 'send_message' and f'№{one}' in kwargs['text'])
            assert '&lt;b&gt;' in first['text'] and '*_[&lt;b&gt;' in first['text'] and '<b>Ирина' not in first['text']
            photo = next(kwargs for name, _, kwargs in bot.calls if name == 'send_photo')
            assert photo['photo'][:3] == b'\xff\xd8\xff' and photo['caption'] == f'Отчёт №{one}'
            assert photo['parse_mode'] == 'HTML'
            group = next(kwargs for name, _, kwargs in bot.calls if name == 'send_media_group')
            assert len(group['media']) == 3 and group['media'][0].caption == f'Отчёт №{many}'
            assert group['media'][1].caption is None
            async with db.transaction() as session:
                statuses = (await session.execute(select(NotificationOutbox.status))).scalars().all()
                assert statuses == ['delivered'] * 4
    asyncio.run(run())


def test_text_message_is_sent_before_the_delayed_images(monkeypatch):
    monkeypatch.setenv('MQB_PROBLEM_REPORT_CHAT_ID', '1')

    async def run():
        async with report_database() as db:
            who = await make_who(db)
            await submit(db, who, images=[png()])
            bot = StubBot()
            await run_dispatcher(db, bot)
            assert [name for name, *_ in bot.calls] == ['send_message']  # the image item is not due for 2 seconds
    asyncio.run(run())


@pytest.mark.parametrize('failure, status, error', [
    (RetryAfter(30), 'pending', 'RetryAfter'), (TelegramError('boom'), 'uncertain', 'TelegramError')])
def test_delivery_errors_follow_the_neighbouring_contract(monkeypatch, failure, status, error):
    monkeypatch.setenv('MQB_PROBLEM_REPORT_CHAT_ID', '1')

    async def run():
        async with report_database() as db:
            await submit(db, await make_who(db))
            await run_dispatcher(db, StubBot(fail=failure))
            async with db.transaction() as session:
                row = (await session.execute(select(NotificationOutbox))).scalar_one()
                assert row.status == status
                assert row.last_error and error in row.last_error
                if status == 'pending':
                    assert row.available_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) + timedelta(seconds=20)
    asyncio.run(run())


# ---------------------------------------------------------------- HTTP

URL = '/api/account/problem-reports'


@asynccontextmanager
async def http_client(db, monkeypatch, bot_token=''):
    """The real Mini App app with the principal swapped for a header-chosen account (any database)."""
    import web.principal as principal_module

    @asynccontextmanager
    async def fake_principal(request, *, database, guest_store, mini_store, lock=False, identity=None, gate=None):
        assert lock, 'the report writes, so the Telegram channel must not use its READ ONLY transaction'
        account = request.headers.get('x-test-account')
        if not account:
            raise principal_module.PrincipalError('authentication', 'Сначала войди через QuizzyWizzy.')
        async with database.transaction() as session:
            yield session, Principal(account, 'Ира', identity or 'guest')

    monkeypatch.setattr(principal_module, 'resolve_principal', fake_principal)
    app = create_app(database=db, settings=MiniAppSettings(bot_token, ORIGIN, offline=True))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        yield client


def body(**overrides):
    value = {'request_id': str(uuid4()), 'text': 'Кнопка не нажимается',
             'context': {'screen': 'farm', 'path': '/app/farm?x=1#y', 'initData': 'secret'}, 'images': []}
    value.update(overrides)
    return value


def test_endpoint_meta_success_idempotent_retry_and_validation(monkeypatch):
    monkeypatch.setenv('MQB_PROBLEM_REPORT_CHAT_ID', '621817842')
    monkeypatch.setenv('MQB_BUILD_COMMIT', '50b2b94')

    async def run():
        async with report_database() as db:
            who = await make_who(db)
            as_who = {**HEADERS, 'X-Test-Account': who.account_id}
            async with http_client(db, monkeypatch) as client:
                meta = await client.get(URL + '/meta')
                assert meta.status_code == 200 and meta.json()['build'] == '50b2b94' and meta.json()['text_max'] == 2000
                payload = body(images=[b64(jpeg_with_exif())])
                created = await client.post(URL + '?identity=guest', json=payload, headers=as_who)
                assert created.status_code == 201, created.text
                assert created.json()['report_id'] == created.json()['number']
                again = await client.post(URL + '?identity=guest', json=payload, headers=as_who)
                assert again.status_code == 200 and again.json() == created.json()
                async with db.transaction() as session:
                    row = await session.get(ProblemReport, created.json()['report_id'])
                    assert row.context == {'screen': 'farm', 'path': '/app/farm'} and row.build == '50b2b94'
                    assert await session.scalar(select(func.count()).select_from(NotificationOutbox)) == 2
                telegram = await client.post(URL + '?identity=telegram', json=body(), headers=as_who)
                assert telegram.status_code == 201
                for bad, status in ((body(text='  '), 400), (body(text='x' * 2001), 400), (body(request_id='no'), 400),
                                    (body(images=['@@@']), 400), (body(images=[b64(b'hello')]), 415),
                                    (body(images=[b64(png())] * 4), 413)):
                    response = await client.post(URL, json=bad, headers=as_who)
                    assert response.status_code == status, (bad, response.text)
                    assert response.json()['detail']
                text = await client.post(URL, content=b'{}', headers={**as_who, 'Content-Type': 'text/plain'})
                assert text.status_code == 415
                huge = await client.post(URL, content=b'{"text": "' + b'a' * 6_600_000 + b'"}',
                                         headers={**as_who, 'Content-Type': 'application/json'})
                assert huge.status_code == 413
                assert (await client.post(URL, json=body(), headers=HEADERS)).status_code == 401
    asyncio.run(run())


def test_endpoint_requires_origin_and_csrf_header(monkeypatch):
    async def run():
        async with report_database() as db:
            who = await make_who(db)
            async with http_client(db, monkeypatch) as client:
                account = {'X-Test-Account': who.account_id}
                assert (await client.post(URL, json=body(), headers={'Origin': ORIGIN, **account})).status_code == 403
                assert (await client.post(URL, json=body(), headers={'X-Guest-CSRF': '1', **account})).status_code == 403
                assert (await client.post(URL, json=body(), headers={'Origin': 'https://evil.example',
                                                                     'X-Guest-CSRF': '1', **account})).status_code == 403
                assert (await client.post(URL, json=body(), headers={**HEADERS, **account})).status_code == 201
    asyncio.run(run())


def test_endpoint_sixth_report_in_an_hour_is_429_with_retry_after(monkeypatch):
    async def run():
        async with report_database() as db:
            who = await make_who(db)
            as_who = {**HEADERS, 'X-Test-Account': who.account_id}
            async with http_client(db, monkeypatch) as client:
                for _ in range(5):
                    assert (await client.post(URL, json=body(), headers=as_who)).status_code == 201
                limited = await client.post(URL, json=body(), headers=as_who)
                assert limited.status_code == 429 and limited.headers['retry-after']
                assert limited.json()['code'] == 'rate_limited'
    asyncio.run(run())


def test_endpoint_ip_limit_uses_hmac_of_the_client_address(monkeypatch):
    async def run():
        async with report_database() as db:
            async with http_client(db, monkeypatch, bot_token=TOKEN) as client:
                for index in range(30):
                    who = await make_who(db, name=f'ip{index}')
                    response = await client.post(URL, json=body(), headers={**HEADERS, 'X-Test-Account': who.account_id})
                    assert response.status_code == 201
                who = await make_who(db, name='ip-over')
                assert (await client.post(URL, json=body(), headers={
                    **HEADERS, 'X-Test-Account': who.account_id})).status_code == 429
                async with db.transaction() as session:
                    stored = set((await session.execute(select(ProblemReport.ip_hash))).scalars())
                assert stored == {reports.ip_hash(TOKEN, '127.0.0.1')}
                assert all(len(item) == 64 and '.' not in item for item in stored)
    asyncio.run(run())


@pytest.fixture
def pg_url():
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL is not configured; no production fallback')
    from storage.database import normalize_database_url
    return normalize_database_url(url)


def test_real_guest_principal_end_to_end(pg_url, monkeypatch):
    monkeypatch.setenv('MQB_PROBLEM_REPORT_CHAT_ID', '621817842')
    from tests.local_database import isolated_database

    async def run():
        async with isolated_database(pg_url) as (db, _):
            app = create_app(database=db, settings=MiniAppSettings('', ORIGIN, offline=True))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                assert (await client.post(URL + '?identity=guest', json=body(), headers=HEADERS)).status_code == 401
                started = await client.post('/api/guest/start', headers=HEADERS)
                assert started.status_code == 200
                payload = body(images=[b64(png())])
                created = await client.post(URL + '?identity=guest', json=payload, headers=HEADERS)
                assert created.status_code == 201, created.text
                again = await client.post(URL + '?identity=guest', json=payload, headers=HEADERS)
                assert again.status_code == 200 and again.json() == created.json()
                async with db.transaction() as session:
                    row = await session.get(ProblemReport, created.json()['report_id'])
                    assert row.channel == 'guest' and str(row.account_id) == started.json()['account_id']
    asyncio.run(run())


def test_real_telegram_principal_can_write(pg_url, monkeypatch):
    monkeypatch.delenv('MQB_PROBLEM_REPORT_CHAT_ID', raising=False)
    from tests.local_database import isolated_database
    from tests.test_mini_app import NOW, signed

    async def run():
        async with isolated_database(pg_url) as (db, _):
            app = create_app(database=db, settings=MiniAppSettings(TOKEN, ORIGIN, offline=True), clock=lambda: NOW)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                login = await client.post('/api/mini/session', json={'init_data': signed(981020000555, date=NOW)})
                assert login.status_code == 200, login.text
                created = await client.post(URL + '?identity=telegram', json=body(), headers=HEADERS)
                assert created.status_code == 201, created.text
                async with db.transaction() as session:
                    row = await session.get(ProblemReport, created.json()['report_id'])
                    assert row.channel == 'telegram' and row.telegram_user_id == 981020000555
    asyncio.run(run())


# ---------------------------------------------------------------- admin

@asynccontextmanager
async def admin_client(db):
    app = FastAPI()
    app.state.admin_database = db
    app.include_router(make_problem_reports_router())
    install_admin_auth(app, auth=AdminAuth(ADMIN_TOKEN))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1') as client:
        yield client


def test_admin_list_card_image_and_status(monkeypatch):
    monkeypatch.delenv('MQB_PROBLEM_REPORT_CHAT_ID', raising=False)

    async def run():
        async with report_database() as db:
            who = await make_who(db, name='Ирина')
            report_id, _ = await submit(db, who, text='Текст отчёта ' * 30, images=[jpeg_with_exif()],
                                        context={'screen': 'farm', 'title': 'Ферма'})
            plain_id, _ = await submit(db, who, text='без картинок', ip='ip-2')
            async with admin_client(db) as client:
                for method, path in (('GET', '/api/admin/problem-reports'), ('GET', f'/api/admin/problem-reports/{report_id}'),
                                     ('GET', f'/api/admin/problem-reports/{report_id}/images/0'),
                                     ('PATCH', f'/api/admin/problem-reports/{report_id}')):
                    assert (await client.request(method, path)).status_code == 401
                csrf = await admin_login(client)
                listing = (await client.get('/api/admin/problem-reports')).json()['items']
                assert [item['id'] for item in listing] == [plain_id, report_id]
                item = listing[1]
                assert (item['status'], item['screen'], item['images'], item['display_name']) == ('new', 'farm', 1, 'Ирина')
                assert len(item['text']) <= 200
                card = (await client.get(f'/api/admin/problem-reports/{report_id}')).json()
                assert card['text'].startswith('Текст отчёта') and card['context'] == {'screen': 'farm', 'title': 'Ферма'}
                assert card['images'] == [{'position': 0, 'width': 20, 'height': 40}]
                image = await client.get(f'/api/admin/problem-reports/{report_id}/images/0')
                assert image.status_code == 200 and image.headers['content-type'] == 'image/jpeg'
                assert image.headers['x-content-type-options'] == 'nosniff' and 'no-store' in image.headers['cache-control']
                assert image.content[:3] == b'\xff\xd8\xff'
                assert (await client.get(f'/api/admin/problem-reports/{report_id}/images/1')).status_code == 404
                assert (await client.get('/api/admin/problem-reports/999999')).status_code == 404
                assert (await client.patch(f'/api/admin/problem-reports/{report_id}', json={'status': 'done'})).status_code == 403
                changed = await client.patch(f'/api/admin/problem-reports/{report_id}', json={'status': 'in_progress'},
                                             headers={'X-CSRF-Token': csrf})
                assert changed.status_code == 200 and changed.json()['status'] == 'in_progress' and changed.json()['updated_at']
                for bad in ({'status': 'closed'}, {'status': 'done', 'extra': 1}, {}):
                    assert (await client.patch(f'/api/admin/problem-reports/{report_id}', json=bad,
                                               headers={'X-CSRF-Token': csrf})).status_code == 422
                only = (await client.get('/api/admin/problem-reports?status=in_progress')).json()['items']
                assert [row['id'] for row in only] == [report_id]
                assert (await client.get('/api/admin/problem-reports?status=bogus')).status_code == 422
    asyncio.run(run())
