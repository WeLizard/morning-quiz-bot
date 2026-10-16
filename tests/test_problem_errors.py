"""Automatic client errors: scrubbing, noise, fingerprint dedup, limits, owner messages and the admin view.

Same fixtures as test_problem_reports: PostgreSQL when TEST_DATABASE_URL is set, otherwise an in-memory
SQLite fallback when ``aiosqlite`` is installed. The concurrency check needs PostgreSQL.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, update

from storage import problem_errors as errors
from storage import problem_reports as reports
from storage.mini_app import MiniAppError
from storage.models import NotificationOutbox, ProblemErrorHit, ProblemReport
from tests.test_admin_auth import login as admin_login
from tests.test_guest_accounts import HEADERS, ORIGIN
from tests.test_problem_reports import (StubBot, URL, admin_client, body, http_client, make_who, outbox,
                                        report_database, run_dispatcher, submit)

ERRORS_URL = URL + '/errors'
CHAT = '621817842'


def payload(message='TypeError: x is undefined', source='/app/farm/assets/app.js', line=123, **extra):
    error = {'type': 'error', 'message': message, 'source': source, 'line': line, 'column': 45,
             'stack': f'TypeError: x\n    at go ({source}:{line}:45)'}
    error.update(extra.pop('error', {}))
    value = {'request_id': str(uuid4()), 'error': error,
             'breadcrumbs': [{'t': 1200, 'kind': 'tap', 'target': 'qw-report'}], 'context': {'screen': 'farm'}}
    value.update(extra)
    return value


async def ingest(db, who, value=None, *, ip='ip-1', now=None, host=None):
    value = value or payload()
    request_id, error, crumbs, context = errors.parse_body(json.dumps(value).encode(), host)
    if error is None:
        return None
    async with db.transaction() as session:
        return await errors.ingest(session, who, request_id=request_id, error=error, breadcrumbs=crumbs,
                                   context=context, client_ip_hash=ip, now=now)


async def rows(db):
    async with db.transaction() as session:
        return (await session.execute(select(ProblemReport).order_by(ProblemReport.id))).scalars().all()


async def messages(db):
    bot = StubBot()
    await run_dispatcher(db, bot)
    return [kwargs['text'] for name, _, kwargs in bot.calls if name == 'send_message']


# ---------------------------------------------------------------- scrubbing and parsing

SECRETS = ('deadbeefcafe1234', '1788120000', 'AAH12345', '%7B', 'A' * 40, 'abc.def.ghi', 'ira@example.com',
           '916 123', '89161234567', 'zzz-token', 'frag-secret', 'tgWebAppData', 'secretq')


def test_secrets_are_scrubbed_from_message_stack_and_source():
    dirty = ('Failed https://evil.example/path?token=zzz-token#frag-secret tgWebAppData=query_id%3DAAH12345&hash=deadbeefcafe1234 '
             'auth_date=1788120000 query_id=AAH12345 user=%7B%22id%22%3A5%7D ' + 'A' * 40 + ' Bearer abc.def.ghi '
             'ira@example.com +7 916 123-45-67 89161234567 /app/x.js?v=secretq#frag-secret')
    request_id, error, crumbs, _ = errors.parse_body(json.dumps(payload(
        message=dirty, source='https://evil.example/a.js?auth_date=1788120000#frag-secret',
        error={'stack': 'Error\n    at f (' + dirty + ')\n' + 'x\n' * 40})).encode(), 'app.example')
    blob = json.dumps(error, ensure_ascii=False)
    for secret in SECRETS:
        assert secret not in blob, secret
    assert error['source'] == 'evil.example/a.js'
    assert 'https://evil.example/path' in error['message'] and errors.REDACTED in error['message']
    assert len(error['stack'].splitlines()) <= 20 and len(error['stack']) <= 2000 and len(error['message']) <= 300


def test_own_origin_is_dropped_from_source_and_limits_are_applied():
    _, error, _, _ = errors.parse_body(json.dumps(payload(source='https://app.example/app/farm/app.js?x=1#y', line=10 ** 9,
                                                          message='m ' * 500)).encode(), 'app.example')
    assert (error['source'], error['line'], len(error['message'])) == ('/app/farm/app.js', 10_000_000, 300)


@pytest.mark.parametrize('error', [
    {'message': 'ResizeObserver loop completed with undelivered notifications.'},
    {'message': 'Script error.', 'source': '', 'line': 0},
    {'message': 'boom', 'source': 'chrome-extension://abc/content.js'},
    {'message': 'boom', 'source': 'moz-extension://abc/content.js'},
    {'message': 'boom', 'source': 'safari-extension://abc/content.js'}])
def test_noise_is_ignored(error):
    assert errors.parse_body(json.dumps(payload(error=error)).encode())[1] is None


def test_extension_frames_in_the_stack_alone_are_not_noise():
    value = payload(error={'stack': 'Error\n at chrome-extension://abc/x.js:1:1\n at go (/app/a.js:1:1)'})
    assert errors.parse_body(json.dumps(value).encode())[1] is not None


def test_stack_keeps_line_and_column_when_the_url_has_query_or_hash():
    cleaned = errors.redact('at fn (https://h/app/x.js?v=1:10:5)\nat g (https://h/y.js#frag:3:4)\n'
                            'at h (https://h/z.js:7:8)\nat k (https://h/q.js?a=1&b=2)', 400)
    assert cleaned == 'at fn (https://h/app/x.js:10:5)\nat g (https://h/y.js:3:4)\nat h (https://h/z.js:7:8)\nat k (https://h/q.js)'


def test_json_shaped_secrets_are_redacted():
    dirty = ('payload {"query_id":"AAH12345","hash":"deadbeefcafe1234","auth_date":1788120000,'
             '"user":{"id":5,"first_name":"Ira"},"signature":"sig-secret","ok":1} '
             'escaped {\\"hash\\":\\"deadbeefcafe5678\\"}')
    cleaned = errors.redact(dirty, 400)
    for secret in ('AAH12345', 'deadbeefcafe1234', '1788120000', 'first_name', 'sig-secret', 'deadbeefcafe5678'):
        assert secret not in cleaned, secret
    assert '"ok":1' in cleaned and errors.REDACTED in cleaned


def test_last_error_timestamp_must_be_iso():
    good = reports.sanitize_context({'last_error': {'message': 'm', 'at': '2026-10-16T10:00:00.123+03:00'}})
    assert good['last_error']['at'] == '2026-10-16T10:00:00.123+03:00'
    for bad in ('yesterday ira@example.com', '2026-10-16T10:00:00Z; drop', 'x' * 40, 5):
        assert reports.sanitize_context({'last_error': {'message': 'm', 'at': bad}})['last_error']['at'] == ''


def test_script_error_with_a_real_source_is_kept():
    assert errors.parse_body(json.dumps(payload(message='Script error.')).encode())[1] is not None


def test_breadcrumbs_are_filtered_to_whitelisted_kinds_and_safe_targets():
    crumbs = [{'t': 1, 'kind': 'tap', 'target': 'ok.item:1/2#3'}, {'t': 2, 'kind': 'click', 'target': 'x'},
              {'t': 3, 'kind': 'tap', 'target': 'Купить за 5 монет'}, {'t': 4, 'kind': 'nav', 'target': 'a b'},
              {'t': 5, 'kind': 'tap', 'target': 'x' * 61}, {'t': 6, 'kind': 'tap', 'target': 'A' * 40},
              {'t': -1, 'kind': 'tap', 'target': 'neg'}, {'t': 10 ** 10, 'kind': 'tap', 'target': 'big'},
              {'t': True, 'kind': 'tap', 'target': 'bool'}, {'t': 7, 'kind': 'menu', 'target': 'open'}]
    kept = errors.parse_body(json.dumps(payload(breadcrumbs=crumbs)).encode())[2]
    assert kept == [{'t': 1, 'kind': 'tap', 'target': 'ok.item:1/2#3'}, {'t': 7, 'kind': 'menu', 'target': 'open'}]
    many = [{'t': index, 'kind': 'tap', 'target': f'b{index}'} for index in range(25)]
    assert [item['t'] for item in errors.parse_body(json.dumps(payload(breadcrumbs=many)).encode())[2]] == list(range(15, 25))


@pytest.mark.parametrize('value', [
    {'request_id': 'nope', 'error': {'type': 'error', 'message': 'm'}}, {'request_id': str(uuid4())},
    {'request_id': str(uuid4()), 'error': {'type': 'weird', 'message': 'm'}},
    {'request_id': str(uuid4()), 'error': {'type': 'error', 'message': '   '}},
    {'request_id': str(uuid4()), 'error': {'type': 'error', 'message': 'm'}, 'extra': 1},
    {'request_id': str(uuid4()), 'error': {'type': 'error', 'message': 'm'}, 'breadcrumbs': 'x'}])
def test_invalid_bodies_are_400(value):
    with pytest.raises(MiniAppError) as failure:
        errors.parse_body(json.dumps(value).encode())
    assert failure.value.status == 400


def test_fingerprint_ignores_long_digit_runs_only():
    one = errors.fingerprint('Cannot read id 12345', '/a.js', 3)
    assert one == errors.fingerprint('Cannot read id 987654', '/a.js', 3)
    assert one != errors.fingerprint('Cannot read id 12', '/a.js', 3)
    assert one != errors.fingerprint('Cannot read id 12345', '/a.js', 4)
    assert one != errors.fingerprint('Cannot read id 12345', '/b.js', 3)


def test_manual_report_last_error_is_sanitised():
    context = reports.sanitize_context({'screen': 'farm', 'last_error': {
        'report_id': 7, 'message': 'boom https://x.example/a?token=zzz-token ira@example.com', 'source': '/a.js?x=1',
        'line': 9, 'at': '2026-10-16T10:00:00Z', 'evil': 1}})
    assert context['last_error'] == {'report_id': 7, 'message': 'boom https://x.example/a ' + errors.REDACTED,
                                     'source': '/a.js', 'line': 9, 'at': '2026-10-16T10:00:00Z'}
    assert 'last_error' not in reports.sanitize_context({'last_error': {'message': ''}})
    assert 'last_error' not in reports.sanitize_context({'last_error': 'text'})


# ---------------------------------------------------------------- storage

def test_identical_errors_fold_into_one_row_and_one_message(monkeypatch):
    monkeypatch.setenv('MQB_PROBLEM_REPORT_CHAT_ID', CHAT)

    async def run():
        async with report_database() as db:
            first, second = await make_who(db, name='А'), await make_who(db, 'telegram', 'Б', 5)
            one = await ingest(db, first, payload(message='Cannot read id 12345'))
            again = await ingest(db, first, payload(message='Cannot read id 987654'))
            other = await ingest(db, second, payload(message='Cannot read id 555555'))
            assert one[1] and not again[1] and not other[1] and one[0] == again[0] == other[0]
            (row,) = await rows(db)
            assert (row.kind, row.occurrences, row.affected_accounts, row.status) == ('auto_error', 3, 2, 'new')
            assert row.last_account_id == second_account(second) and row.notified_at is not None
            assert row.context['error']['source'] == '/app/farm/assets/app.js' and row.context['breadcrumbs']
            sent = await messages(db)
            assert len(sent) == 1 and sent[0].startswith('⚠️ <b>Автоошибка №')
            async with db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(ProblemErrorHit)) == 3
            await ingest(db, first, payload(message='A different failure'))
            assert len(await rows(db)) == 2
    asyncio.run(run())


def second_account(who):
    from uuid import UUID
    return UUID(who.account_id)


def test_auto_error_message_has_stack_crumbs_context_and_is_escaped(monkeypatch):
    monkeypatch.setenv('MQB_PROBLEM_REPORT_CHAT_ID', CHAT)

    async def run():
        async with report_database() as db:
            who = await make_who(db)
            await ingest(db, who, payload(message='<b>*_[x', error={'stack': 'Err\n' + '    at f (/a.js:1:1)\n' * 30}))
            (text,) = await messages(db)
            assert '&lt;b&gt;*_[x' in text and '<b>*_' not in text
            assert '/app/farm/assets/app.js:123:45' in text and '<pre>' in text and text.count('at f') <= 12
            assert 'Шаги: tap:qw-report' in text and '<b>Контекст</b>' in text and 'Повторы видны в админке' in text
    asyncio.run(run())


def test_without_chat_id_errors_are_stored_without_outbox(monkeypatch):
    monkeypatch.delenv('MQB_PROBLEM_REPORT_CHAT_ID', raising=False)

    async def run():
        async with report_database() as db:
            who = await make_who(db)
            await ingest(db, who)
            await ingest(db, who)
            (row,) = await rows(db)
            assert row.occurrences == 2 and row.notified_at is None and await outbox(db) == []
    asyncio.run(run())


def test_done_error_that_returns_reopens_and_reports_once_per_cooldown(monkeypatch):
    monkeypatch.setenv('MQB_PROBLEM_REPORT_CHAT_ID', CHAT)

    async def run():
        async with report_database() as db:
            who = await make_who(db)
            start = datetime.now(timezone.utc) - timedelta(hours=40)  # every event stays in the past
            await ingest(db, who, now=start)
            await messages(db)

            async def close():
                async with db.transaction() as session:
                    await session.execute(update(ProblemReport).values(status='done'))

            await close()
            await ingest(db, who, now=start + timedelta(hours=1))  # still inside the 6 h cooldown: silent
            assert (await rows(db))[0].status == 'new' and await messages(db) == []
            await close()
            await ingest(db, who, now=start + timedelta(hours=7))
            (text,) = await messages(db)
            assert text.startswith('🔁 <b>Ошибка №') and 'вернулась' in text and 'повторов: 3' in text
            assert (await rows(db))[0].status == 'new'
            await close()
            await ingest(db, who, now=start + timedelta(hours=8))  # cooldown restarted by the last message
            assert await messages(db) == []
            # in_progress is not reopened and never announced again
            async with db.transaction() as session:
                await session.execute(update(ProblemReport).values(status='in_progress'))
            await ingest(db, who, now=start + timedelta(hours=30))
            assert (await rows(db))[0].status == 'in_progress' and await messages(db) == []
    asyncio.run(run())


def test_milestones_are_announced_once(monkeypatch):
    monkeypatch.setenv('MQB_PROBLEM_REPORT_CHAT_ID', CHAT)

    async def run():
        async with report_database() as db:
            who = await make_who(db)
            now = datetime.now(timezone.utc)
            await ingest(db, who, now=now)
            await messages(db)
            for _ in range(8):
                await ingest(db, who, now=now)
            assert await messages(db) == []
            await ingest(db, who, now=now)  # the 10th occurrence
            (text,) = await messages(db)
            assert text.startswith('📈 <b>Ошибка №') and 'уже 10 повторов у 1 аккаунтов' in text
            await ingest(db, who, now=now)
            assert await messages(db) == []
            async with db.transaction() as session:
                await session.execute(update(ProblemReport).values(occurrences=99))
            await ingest(db, who, now=now)
            (text,) = await messages(db)
            assert 'уже 100 повторов' in text
            keys = [key for _, _, _, key, _ in await outbox(db)]
            assert len(keys) == len(set(keys)) == 3
    asyncio.run(run())


def test_new_error_messages_are_capped_per_hour_and_summed_up_in_one_digest(monkeypatch):
    monkeypatch.setenv('MQB_PROBLEM_REPORT_CHAT_ID', CHAT)

    async def run():
        async with report_database() as db:
            now = datetime.now(timezone.utc) - timedelta(hours=3)
            start = now.replace(minute=0, second=0, microsecond=0)
            for index in range(12):
                await ingest(db, await make_who(db, name=f'N{index}'), payload(message=f'failure {index}x'),
                             ip=f'ip-{index}', now=now)
            queued = await outbox(db)
            digests = [item for item in queued if item[3].startswith('problem_errors:digest:')]
            assert [item[3] for item in digests] == [f'problem_errors:digest:{start:%Y%m%d%H}']
            assert digests[0][4].replace(tzinfo=timezone.utc) == start + timedelta(hours=1)
            sent = await messages(db)
            assert len([text for text in sent if text.startswith('⚠️')]) == 10
            assert sent[-1] == '📊 +2 новых автоошибок за час — см. админку' or '📊 +2 ' in ' '.join(sent)
            async with db.transaction() as session:
                silent = (await session.execute(select(func.count()).select_from(ProblemReport).where(
                    ProblemReport.notified_at.is_(None)))).scalar_one()
            assert silent == 2
            # Over budget a milestone or a return is dropped without a trace.
            async with db.transaction() as session:
                await session.execute(update(ProblemReport).where(ProblemReport.text == 'failure 0x').values(occurrences=9))
            await ingest(db, await make_who(db, name='again'), payload(message='failure 0x'), ip='ip-again', now=now)
            assert await messages(db) == []
    asyncio.run(run())


def test_one_account_gets_three_new_error_messages_per_day(monkeypatch):
    monkeypatch.setenv('MQB_PROBLEM_REPORT_CHAT_ID', CHAT)

    async def run():
        async with report_database() as db:
            who = await make_who(db)
            now = datetime.now(timezone.utc) - timedelta(hours=3)
            for index in range(5):
                await ingest(db, who, payload(message=f'solo {index}x'), now=now)
            sent = await messages(db)
            assert len([text for text in sent if text.startswith('⚠️')]) == 3
            assert any(text.startswith('📊 +2 новых автоошибок') for text in sent)
            other = await make_who(db, name='Другой')
            await ingest(db, other, payload(message='fresh failure'), ip='ip-other', now=now + timedelta(minutes=1))
            assert [text for text in await messages(db) if text.startswith('⚠️')]
    asyncio.run(run())


def test_digest_is_not_sent_when_nothing_is_left_unannounced(monkeypatch):
    monkeypatch.setenv('MQB_PROBLEM_REPORT_CHAT_ID', CHAT)

    async def run():
        async with report_database() as db:
            who = await make_who(db)
            now = datetime.now(timezone.utc) - timedelta(hours=3)
            for index in range(4):
                await ingest(db, who, payload(message=f'solo {index}x'), now=now)
            async with db.transaction() as session:
                await session.execute(update(ProblemReport).values(notified_at=now))
            sent = await messages(db)
            assert len(sent) == 3 and not any('📊' in text for text in sent)
    asyncio.run(run())


def test_error_limits_account_ip_and_global(monkeypatch):
    monkeypatch.delenv('MQB_PROBLEM_REPORT_CHAT_ID', raising=False)

    async def run():
        async with report_database() as db:
            now = datetime.now(timezone.utc)
            who = await make_who(db)
            for index in range(30):
                await ingest(db, who, payload(message=f'failure {index}x'), ip=f'ip-{index}', now=now)
            with pytest.raises(MiniAppError) as failure:
                await ingest(db, who, payload(message='one more'), ip='ip-new', now=now)
            assert failure.value.status == 429
            await ingest(db, who, payload(message='one more'), ip='ip-new', now=now + timedelta(hours=2))
            # IP: 120 calls per hour across accounts
            for index in range(120):
                await ingest(db, await make_who(db, name=f'U{index}'), payload(message='shared'), ip='nat', now=now)
            with pytest.raises(MiniAppError) as failure:
                await ingest(db, await make_who(db, name='U120'), payload(message='shared'), ip='nat', now=now)
            assert failure.value.status == 429
            # Global: 600 hits per hour
            async with db.transaction() as session:
                report_id = (await session.execute(select(ProblemReport.id).limit(1))).scalar_one()
                have = await session.scalar(select(func.count()).select_from(ProblemErrorHit))
                session.add_all([ProblemErrorHit(account_id=uuid4(), ip_hash=f'bulk-{i}', report_id=report_id, created_at=now)
                                 for i in range(600 - have)])
            with pytest.raises(MiniAppError) as failure:
                await ingest(db, await make_who(db, name='late'), payload(message='x1'), ip='fresh', now=now)
            assert failure.value.status == 429
    asyncio.run(run())


def test_manual_limits_do_not_count_auto_errors_and_vice_versa(monkeypatch):
    monkeypatch.delenv('MQB_PROBLEM_REPORT_CHAT_ID', raising=False)

    async def run():
        async with report_database() as db:
            who = await make_who(db)
            now = datetime.now(timezone.utc)
            for index in range(8):
                await ingest(db, who, payload(message=f'e{index}x'), now=now)
            for index in range(5):
                await submit(db, who, ip=f'm{index}', now=now)
            with pytest.raises(MiniAppError):
                await submit(db, who, ip='m-over', now=now)
            await ingest(db, who, payload(message='still fine'), now=now)
    asyncio.run(run())


def test_manual_report_with_last_error_is_stored_and_shown(monkeypatch):
    monkeypatch.setenv('MQB_PROBLEM_REPORT_CHAT_ID', CHAT)

    async def run():
        async with report_database() as db:
            who = await make_who(db)
            await submit(db, who, text='сломалось', context=reports.sanitize_context({'screen': 'farm', 'last_error': {
                'report_id': 7, 'message': 'TypeError <x>', 'source': '/app/farm/app.js', 'line': 12,
                'at': '2026-10-16T10:00:00Z'}}))
            (row,) = await rows(db)
            assert row.kind == 'manual' and row.context['last_error']['report_id'] == 7
            (text,) = await messages(db)
            assert ('Последняя ошибка: TypeError &lt;x&gt; (/app/farm/app.js:12) (автоошибка №7)') in text
    asyncio.run(run())


@pytest.fixture
def pg_url():
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL is not configured; no production fallback')
    from storage.database import normalize_database_url
    return normalize_database_url(url)


def test_concurrent_identical_errors_make_one_row(pg_url, monkeypatch):
    monkeypatch.setenv('MQB_PROBLEM_REPORT_CHAT_ID', CHAT)
    from tests.local_database import isolated_database

    async def run():
        async with isolated_database(pg_url) as (db, _):
            people = [await make_who(db, name=f'P{index}') for index in range(6)]
            results = await asyncio.gather(*(ingest(db, who, payload(), ip=f'ip-{n}') for n, who in enumerate(people)),
                                           return_exceptions=True)
            assert not [item for item in results if isinstance(item, Exception)], results
            (row,) = await rows(db)
            assert row.occurrences == 6 and sum(1 for _, new in results if new) == 1
            assert len(await messages(db)) == 1
    asyncio.run(run())


# ---------------------------------------------------------------- HTTP

def test_endpoint_accepts_errors_deduplicates_and_ignores_noise(monkeypatch):
    monkeypatch.setenv('MQB_PROBLEM_REPORT_CHAT_ID', CHAT)

    async def run():
        async with report_database() as db:
            who = await make_who(db)
            as_who = {**HEADERS, 'X-Test-Account': who.account_id}
            async with http_client(db, monkeypatch) as client:
                first = await client.post(ERRORS_URL + '?identity=guest', json=payload(), headers=as_who)
                assert first.status_code == 202 and first.json()['new'] is True and first.json()['accepted'] is True
                second = await client.post(ERRORS_URL + '?identity=telegram', json=payload(), headers=as_who)
                assert second.status_code == 202 and second.json() == {
                    'accepted': True, 'report_id': first.json()['report_id'], 'new': False}
                noise = await client.post(ERRORS_URL, json=payload(message='ResizeObserver loop limit exceeded'),
                                          headers=as_who)
                assert noise.status_code == 202 and noise.json()['report_id'] is None
                assert len(await rows(db)) == 1
                assert (await client.post(ERRORS_URL, json={'request_id': 'x'}, headers=as_who)).status_code == 400
                assert (await client.post(ERRORS_URL, content=b'{}', headers={
                    **as_who, 'Content-Type': 'text/plain'})).status_code == 415
                assert (await client.post(ERRORS_URL, content=b'{"a": "' + b'a' * 17000 + b'"}', headers={
                    **as_who, 'Content-Type': 'application/json'})).status_code == 413
                assert (await client.post(ERRORS_URL, json=payload(), headers=HEADERS)).status_code == 401
                assert (await client.post(ERRORS_URL, json=payload(), headers={
                    'Origin': ORIGIN, 'X-Test-Account': who.account_id})).status_code == 403
                assert (await client.post(ERRORS_URL, json=payload(), headers={
                    'X-Guest-CSRF': '1', 'X-Test-Account': who.account_id})).status_code == 403
                manual = await client.post(URL, json=body(context={'screen': 'farm', 'last_error': {
                    'report_id': first.json()['report_id'], 'message': 'TypeError', 'source': '/a.js', 'line': 3,
                    'at': '2026-10-16T10:00:00Z', 'x': 1}}), headers=as_who)
                assert manual.status_code == 201
    asyncio.run(run())


def test_endpoint_429_when_the_account_is_over_the_limit(monkeypatch):
    monkeypatch.delenv('MQB_PROBLEM_REPORT_CHAT_ID', raising=False)

    async def run():
        async with report_database() as db:
            who = await make_who(db)
            as_who = {**HEADERS, 'X-Test-Account': who.account_id}
            async with http_client(db, monkeypatch) as client:
                for index in range(30):
                    assert (await client.post(ERRORS_URL, json=payload(message=f'e{index}x'), headers=as_who)).status_code == 202
                limited = await client.post(ERRORS_URL, json=payload(message='over'), headers=as_who)
                assert limited.status_code == 429 and limited.headers['retry-after']
    asyncio.run(run())


def test_real_guest_and_telegram_principals_accept_errors(pg_url, monkeypatch):
    monkeypatch.delenv('MQB_PROBLEM_REPORT_CHAT_ID', raising=False)
    from tests.local_database import isolated_database
    from tests.test_mini_app import NOW, TOKEN, signed
    from web.mini_app import MiniAppSettings, create_app

    async def run():
        async with isolated_database(pg_url) as (db, _):
            app = create_app(database=db, settings=MiniAppSettings(TOKEN, ORIGIN, offline=True), clock=lambda: NOW)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as guest:
                assert (await guest.post(ERRORS_URL + '?identity=guest', json=payload(), headers=HEADERS)).status_code == 401
                assert (await guest.post('/api/guest/start', headers=HEADERS)).status_code == 200
                accepted = await guest.post(ERRORS_URL + '?identity=guest', json=payload(), headers=HEADERS)
                assert accepted.status_code == 202 and accepted.json()['new'] is True
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as telegram:
                login = await telegram.post('/api/mini/session', json={'init_data': signed(981020000556, date=NOW)})
                assert login.status_code == 200, login.text
                again = await telegram.post(ERRORS_URL + '?identity=telegram', json=payload(), headers=HEADERS)
                assert again.status_code == 202 and again.json()['new'] is False
            (row,) = await rows(db)
            assert row.occurrences == 2 and row.affected_accounts == 2
    asyncio.run(run())


# ---------------------------------------------------------------- admin

def test_admin_filters_by_kind_and_shows_occurrences(monkeypatch):
    monkeypatch.delenv('MQB_PROBLEM_REPORT_CHAT_ID', raising=False)

    async def run():
        async with report_database() as db:
            who = await make_who(db)
            other = await make_who(db, name='Б')
            now = datetime.now(timezone.utc)
            manual_id, _ = await submit(db, who, text='ручной', now=now - timedelta(minutes=5))
            old_id, _ = await ingest(db, who, payload(message='old failure'), now=now - timedelta(minutes=4))
            hot_id, _ = await ingest(db, who, payload(message='hot failure'), now=now - timedelta(minutes=3))
            await ingest(db, other, payload(message='hot failure'), now=now - timedelta(minutes=2))
            await ingest(db, who, payload(message='old failure'), now=now - timedelta(minutes=1))
            async with admin_client(db) as client:
                await admin_login(client)
                everything = (await client.get('/api/admin/problem-reports')).json()['items']
                assert {item['id'] for item in everything} == {manual_id, old_id, hot_id}
                manual = (await client.get('/api/admin/problem-reports?kind=manual')).json()['items']
                assert [item['id'] for item in manual] == [manual_id] and manual[0]['kind'] == 'manual'
                auto = (await client.get('/api/admin/problem-reports?kind=auto_error')).json()['items']
                assert [item['id'] for item in auto] == [old_id, hot_id]  # by last_seen_at, newest first
                assert (auto[0]['occurrences'], auto[0]['affected_accounts']) == (2, 1)
                assert (auto[1]['occurrences'], auto[1]['affected_accounts']) == (2, 2)
                assert len(auto[0]['fingerprint']) == 8 and auto[0]['last_seen_at']
                assert (await client.get('/api/admin/problem-reports?kind=other')).status_code == 422
                card = (await client.get(f'/api/admin/problem-reports/{old_id}')).json()
                assert card['kind'] == 'auto_error' and card['occurrences'] == 2 and len(card['fingerprint']) == 64
                assert card['context']['error']['stack'] and card['context']['breadcrumbs'][0]['target'] == 'qw-report'
    asyncio.run(run())
