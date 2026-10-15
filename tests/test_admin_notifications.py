"""Protected operator HTTP workflow, using isolated local PostgreSQL schemas."""
import asyncio
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, func, select

from storage.models import NotificationOutbox, NotificationResolution
from storage.notifications import NotificationQueue
from tests.local_database import isolated_database
from tests.test_admin_auth import TOKEN, login
from tests.test_notification_resolution import uncertain_item
from tests.test_postgres_members import pg_env
from web.admin_auth import AdminAuth, install_admin_auth
from web.postgres_admin import install_postgres_admin


def application(database):
    app = FastAPI()
    install_postgres_admin(app)
    app.state.admin_database = database
    install_admin_auth(app, auth=AdminAuth(TOKEN))
    return app


def resolution(**changes):
    return dict(action_id=str(uuid4()), expected_version=2, decision='confirmed_delivered',
                reason='private-reason-marker', verification_method='private-evidence-marker',
                chat_id=-100, message_id=42, **changes)


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1')


def assert_private(response):
    for secret in ('never-export', 'private-error-marker', 'constant-worker',
                   'private-reason-marker', 'private-evidence-marker',
                   'payload', 'dedupe_key', 'claimed_by', 'last_error', 'reason', 'evidence'):
        assert secret not in response.text


def test_auth_validation_and_allowlisted_reads(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            item = await uncertain_item(database, key='private-dedupe-marker')
            async with database.transaction() as session:
                (await session.get(NotificationOutbox, item)).last_error = 'private-error-marker'
            async with client(application(database)) as browser:
                path = f'/api/notifications/{item}'
                for target in ('/api/notifications', path):
                    assert (await browser.get(target)).status_code == 401
                assert (await browser.post(path + '/resolve', json=resolution())).status_code == 401
                csrf = await login(browser)
                headers = {'X-CSRF-Token': csrf}
                assert (await browser.post(path + '/resolve', json=resolution())).status_code == 403
                for other in ({'X-CSRF-Token': 'wrong'}, {**headers, 'Origin': 'https://other.invalid'}):
                    assert (await browser.post(path + '/resolve', json=resolution(), headers=other)).status_code == 403
                for target in ('/api/notifications', path):
                    response = await browser.get(target)
                    assert response.status_code == 200, response.text
                    assert_private(response)
                    assert response.headers['cache-control'] == 'no-store'
                record = (await browser.get(path)).json()
                assert record['chat_id'] == '-100' and record['has_error'] is True and record['version'] == 2
                for suffix in ('?limit=51', '?limit=0', '?offset=-1', '?status=pending', '?limit=private-error-marker'):
                    response = await browser.get('/api/notifications' + suffix)
                    assert response.status_code == 422
                    assert_private(response)
                bad_inputs = [dict(resolution(), expected_version=True), dict(resolution(), expected_version='2'),
                              dict(resolution(), action_id='private-error-marker'), dict(resolution(), decision='resend'),
                              dict(resolution(), chat_id=None), dict(resolution(), message_id=False),
                              dict(resolution(), reason=' '), dict(resolution(), verification_method=' '),
                              dict(resolution(), actor='private-error-marker'), dict(resolution(), evidence={'private-error-marker': 1}),
                              dict(resolution(), chat_id=-101)]
                for body in bad_inputs:
                    response = await browser.post(path + '/resolve', json=body, headers=headers)
                    assert response.status_code == 422, response.text
                    assert_private(response)
                response = await browser.post(path + '/resolve', content='{"private-error-marker":', headers={**headers, 'Content-Type': 'application/json'})
                assert response.status_code == 422
                assert_private(response)
                async with database.transaction() as session:
                    assert (await session.get(NotificationOutbox, item)).status == 'uncertain'
                    assert await session.scalar(select(func.count()).select_from(NotificationResolution)) == 0
    asyncio.run(run())


@pytest.mark.parametrize('decision', ['confirmed_delivered', 'closed_without_resend'])
def test_resolve_relogin_replay_deleted_outbox_and_conflicts(pg_env, decision):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            item = await uncertain_item(database)
            body = dict(resolution(), decision=decision)
            if decision == 'closed_without_resend':
                body.pop('chat_id'); body.pop('message_id')
            async with client(application(database)) as browser:
                csrf = await login(browser)
                path = f'/api/notifications/{item}/resolve'
                response = await browser.post(path, json=body, headers={'X-CSRF-Token': csrf})
                assert response.status_code == 200, response.text
                assert_private(response)
                assert response.json()['operator_id'] == 'local-admin'
                assert response.json()['decision'] == decision and response.json()['version'] == 3
                detail = await browser.get(f'/api/notifications/{item}')
                assert_private(detail)
                assert detail.json()['resolution']['decision'] == decision
                for changed in (dict(body, action_id=str(uuid4())), dict(body, reason='changed')):
                    conflict = await browser.post(path, json=changed, headers={'X-CSRF-Token': csrf})
                    assert conflict.status_code == 409
                    assert_private(conflict)
                assert (await browser.post('/auth/logout', headers={'X-CSRF-Token': csrf})).status_code == 200
                csrf = await login(browser)
                async with database.transaction() as session:
                    receipt = await session.get(NotificationResolution, body['action_id'])
                    assert receipt.operator_id == 'local-admin' and receipt.reason == body['reason']
                    assert receipt.evidence == {key: body[key] for key in ('verification_method', 'chat_id', 'message_id') if key in body}
                    await session.execute(delete(NotificationOutbox).where(NotificationOutbox.id == item))
                replay = await browser.post(path, json=body, headers={'X-CSRF-Token': csrf})
                assert replay.status_code == 200 and replay.json() == response.json()
                assert_private(replay)
                assert (await browser.get(f'/api/notifications/{item}')).status_code == 404
    asyncio.run(run())


def test_concurrent_admins_and_sending_cannot_resolve(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            item = await uncertain_item(database)
            queue = NotificationQueue(database)
            async with database.transaction() as session:
                await queue.enqueue_in(session, kind='test', dedupe_key='sending', payload={'secret': 'never-export'})
            sending = await queue.claim('constant-worker')
            app = application(database)
            async with client(app) as a, client(app) as b:
                ah, bh = {'X-CSRF-Token': await login(a)}, {'X-CSRF-Token': await login(b)}
                bodies = [resolution(), resolution()]
                responses = await asyncio.gather(a.post(f'/api/notifications/{item}/resolve', json=bodies[0], headers=ah),
                                                 b.post(f'/api/notifications/{item}/resolve', json=bodies[1], headers=bh))
                assert sorted(response.status_code for response in responses) == [200, 409]
                winner = 0 if responses[0].status_code == 200 else 1
                repeated = await asyncio.gather(a.post(f'/api/notifications/{item}/resolve', json=bodies[winner], headers=ah),
                                                b.post(f'/api/notifications/{item}/resolve', json=bodies[winner], headers=bh))
                assert [r.json() for r in repeated] == [responses[winner].json()] * 2
                conflict = await a.post(f'/api/notifications/{sending["id"]}/resolve', json=dict(resolution(), expected_version=1), headers=ah)
                assert conflict.status_code == 409
                assert_private(conflict)
                listing = await a.get('/api/notifications?status=sending&limit=1&offset=0')
                assert listing.status_code == 200 and len(listing.json()['items']) == 1
                assert_private(listing)
                async with database.transaction() as session:
                    assert (await session.get(NotificationOutbox, sending['id'])).status == 'sending'
                    assert (await session.get(NotificationOutbox, item)).status == 'resolved'
                    assert await session.scalar(select(func.count()).select_from(NotificationResolution)) == 1
                assert await queue.claim('constant-worker') is None
    asyncio.run(run())
