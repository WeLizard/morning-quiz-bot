import asyncio
import importlib
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select

from tests.test_admin_auth import TOKEN, login
from tests.test_postgres_members import CHAT, pg_env, scenario
from storage.models import PhotoQuizItem, Chat
from storage.models import AdminAction, SystemState
from storage.photos import PhotoCatalog, PhotoMetadataConflict, metadata_version
from storage.settings import SettingsService
from storage.farm_upkeep import FarmUpkeepSettings
from storage.admin_actions import AdminConflict
from qw_farm.upkeep_config import defaults, moscow_day
from web.admin_auth import AdminAuth, install_admin_auth
from web.postgres_admin import install_postgres_admin, image_path

KEY = "unit-test-admin-photo"


def test_photo_admin_preserves_other_metadata_and_detects_concurrent_edit(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            try:
                async with db.transaction() as session:
                    session.add(PhotoQuizItem(media_key=KEY, correct_answer="old", hints={"first_letter": "o"},
                        metadata_json={"display_answer": "old", "extra_from_import": "keep"}))
                catalog = PhotoCatalog(db)
                original = (await catalog.load())[KEY]
                version = metadata_version(original)
                results = await asyncio.gather(
                    catalog.patch(KEY, {"correct_answer": "new"}, expected_version=version),
                    catalog.patch(KEY, {"enabled": False}, expected_version=version), return_exceptions=True)
                assert sum(isinstance(result, PhotoMetadataConflict) for result in results) == 1
                current = (await catalog.load())[KEY]
                assert current["extra_from_import"] == "keep" and current["hints"] == original["hints"]
                if current["correct_answer"] == "new":
                    assert current["display_answer"] == "new"
                await catalog.patch(KEY, {"enabled": False}, expected_version=metadata_version(current))
                assert (await catalog.load())[KEY]["enabled"] is False
            finally:
                async with db.transaction() as session:
                    await session.execute(delete(PhotoQuizItem).where(PhotoQuizItem.media_key == KEY))
    asyncio.run(run())


def test_authenticated_pg_api_versions_and_no_legacy_fallback(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            await SettingsService(db).patch_paths(CHAT, [(('auto_delete_bot_messages',), True)])
            try:
                await PhotoCatalog(db).get_or_create(KEY)
                app = FastAPI()
                install_postgres_admin(app)
                @app.post("/api/system/restart-bot")
                async def unsafe_legacy():
                    pytest.fail("Legacy bot control must not be called")
                install_admin_auth(app, auth=AdminAuth(TOKEN))
                async with app.router.lifespan_context(app):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
                        assert (await client.get('/api/photo-quiz')).status_code == 401
                        csrf = await login(client)
                        client.headers['X-CSRF-Token'] = csrf
                        response = await client.get(f'/api/chats/{CHAT}/settings')
                        rev = response.headers['x-settings-revision']
                        url = f'/api/chats/{CHAT}/settings?expected_revision={rev}'
                        assert (await client.put(url, json={'auto_delete_bot_messages': False})).status_code == 200
                        assert (await client.put(url, json={'auto_delete_bot_messages': True})).status_code == 409
                        item = next(p for p in (await client.get('/api/photo-quiz')).json()['photos'] if p['name'] == KEY)
                        assert not item['has_image'] and item['image_url'] is None
                        assert (await client.put(f'/api/photo-quiz/{KEY}', json={'enabled': False})).status_code == 428
                        url = f'/api/photo-quiz/{KEY}?expected_version={item["version"]}'
                        assert (await client.put(url, json={'correct_answer': 'New answer'})).status_code == 200
                        assert (await client.put(url, json={'enabled': False})).status_code == 409
                        assert (await client.put(url, json={'unknown': 'field'})).status_code == 422
                        assert (await client.put(url, json={'hints': {'nested': {'bad': True}}})).status_code == 422
                        assert (await client.put(f'/api/photo-quiz/missing?expected_version={item["version"]}', json={'enabled': False})).status_code == 404
                        assert (await client.post('/api/system/restart-bot')).status_code == 501
                        assert (await client.delete(f'/api/photo-quiz/{KEY}')).status_code == 501
                        assert (await client.get('/api/images/missing.webp')).status_code == 404
            finally:
                async with db.transaction() as session:
                    await session.execute(delete(PhotoQuizItem).where(PhotoQuizItem.media_key == KEY))
    asyncio.run(run())


def test_farm_upkeep_admin_is_authenticated_scheduled_versioned_and_idempotent(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            action_id = 'f31f0b83-cdb8-43c4-91a8-78ac2f7c4a40'
            app = FastAPI()
            install_postgres_admin(app)
            install_admin_auth(app, auth=AdminAuth(TOKEN))
            try:
                async with app.router.lifespan_context(app):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1') as client:
                        endpoint = '/api/control/farm-upkeep'
                        assert (await client.get(endpoint)).status_code == 401
                        csrf = await login(client)
                        payload = {**defaults(), 'expected_revision': 0, 'action_id': action_id}
                        assert (await client.put(endpoint, json=payload)).status_code == 403
                        client.headers['X-CSRF-Token'] = csrf
                        initial = await client.get(endpoint)
                        assert initial.status_code == 200
                        assert initial.json()['revision'] == 0
                        assert initial.json()['active'] == defaults()
                        assert (await client.put(endpoint, json={**payload, 'building_rate_pct': 101})).status_code == 422
                        assert (await client.put(endpoint, json={**payload, 'surprise': 1})).status_code == 422

                        desired = {**defaults(), 'upkeep_level': 12, 'land_rate_pct': 125,
                                   'building_rate_pct': 3, 'field_per_hectare': 2100,
                                   'tree_rate_per_extra_tree': 180}
                        request = {**desired, 'expected_revision': 0, 'action_id': action_id}
                        saved = await client.put(endpoint, json=request)
                        assert saved.status_code == 200
                        receipt = saved.json()
                        assert receipt['kind'] == 'farm_upkeep'
                        state = await client.get(endpoint)
                        assert state.status_code == 200
                        assert state.json()['revision'] == 1
                        assert state.json()['active'] == defaults()
                        assert state.json()['values'] == desired
                        expected_day = moscow_day(datetime.now(timezone.utc).timestamp()) + 1
                        assert state.json()['pending']['effective_from_moscow_day'] == expected_day

                        # A lost response can be retried without creating a second audit event.
                        assert (await client.put(endpoint, json=request)).json() == receipt
                        stale_request = {**desired, 'expected_revision': 0,
                                         'action_id': '5f5277a7-745d-41f7-8eb8-87d506cc938f'}
                        assert (await client.put(endpoint, json=stale_request)).status_code == 409
                        async with db.transaction() as session:
                            actions = list((await session.scalars(select(AdminAction).where(AdminAction.id == action_id))).all())
                            row = await session.get(SystemState, 'farm_upkeep_config')
                            assert len(actions) == 1
                            assert row.payload['revision'] == 1

                # The gameplay Unit reads the exact persisted active values, while the pending update waits.
                from qw_farm.persistence import Unit
                async with db.transaction() as session:
                    from qw_farm.upkeep_config import effective_values
                    row = await session.get(SystemState, 'farm_upkeep_config')
                    at = 1_800_000_000
                    assert await Unit(session, None).farm_upkeep_config(at) == effective_values(row.payload, at)
            finally:
                async with db.transaction() as session:
                    await session.execute(delete(AdminAction).where(AdminAction.id == action_id))
                    await session.execute(delete(SystemState).where(SystemState.key == 'farm_upkeep_config'))
    asyncio.run(run())


def test_farm_upkeep_concurrent_updates_conflict_on_revision_and_retry_receipt(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            action_ids = (
                'bf56432b-39c9-4883-ae97-45f51c16ae02',
                'f1637407-50d9-4df4-9efb-c14154d89140',
            )
            desired = (
                {**defaults(), 'field_per_hectare': 1900},
                {**defaults(), 'field_per_hectare': 2300},
            )
            settings = FarmUpkeepSettings(db)
            try:
                results = await asyncio.gather(*(
                    settings.update(values=values, expected_revision=0, action_id=action_id)
                    for values, action_id in zip(desired, action_ids)
                ), return_exceptions=True)
                receipts = [result for result in results if isinstance(result, dict)]
                conflicts = [result for result in results if isinstance(result, AdminConflict)]
                assert len(receipts) == 1
                assert len(conflicts) == 1

                winner = receipts[0]
                winner_index = action_ids.index(winner['id'])
                retry = await settings.update(
                    values=desired[winner_index], expected_revision=0,
                    action_id=action_ids[winner_index],
                )
                assert retry == winner
                async with db.transaction() as session:
                    actions = list((await session.scalars(select(AdminAction).where(
                        AdminAction.id.in_(action_ids),
                    ))).all())
                    row = await session.get(SystemState, 'farm_upkeep_config')
                    assert [action.id for action in actions] == [winner['id']]
                    assert row.payload['revision'] == 1
            finally:
                async with db.transaction() as session:
                    await session.execute(delete(AdminAction).where(AdminAction.id.in_(action_ids)))
                    await session.execute(delete(SystemState).where(SystemState.key == 'farm_upkeep_config'))
    asyncio.run(run())


@pytest.mark.parametrize('name', ['../private.webp', '..\\private.webp', 'C:private.webp', 'bad.png', '.', ''])
def test_pg_image_paths_are_confined(name):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        image_path(name)


def test_real_app_requires_login_and_pg_html_has_no_remote_scripts(pg_env, monkeypatch):
    async def run():
        monkeypatch.setenv('ADMIN_ACCESS_TOKEN', TOKEN)
        module = importlib.import_module('web.main')
        async with module.app.router.lifespan_context(module.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(module.app), base_url='http://127.0.0.1') as client:
                assert (await client.get('/api/users')).status_code == 401
                await login(client)
                response = await client.get('/')
                assert response.status_code == 200
                assert '/static/js/admin-auth.js' in response.text
                assert '/static/js/postgres-admin.js' in response.text
                assert '<html lang="ru" data-admin-theme="night">' in response.text
                assert '<body class="pg-admin">' in response.text
                assert '/static/css/quiz-brand.css' in response.text
                assert '<script src="https://' not in response.text
                assert 'onclick=' not in response.text
                assert "script-src 'self'" in response.headers['content-security-policy']
                assert (await client.get('/api/storage/status')).status_code == 200
                assert (await client.get('/openapi.json')).status_code == 200
    asyncio.run(run())


def test_login_uses_local_shared_theme_before_authentication(monkeypatch):
    async def run():
        monkeypatch.setenv('ADMIN_ACCESS_TOKEN', TOKEN)
        module = importlib.import_module('web.main')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(module.app), base_url='http://127.0.0.1') as client:
            response = await client.get('/login')
            assert response.status_code == 200
            assert '<html lang="ru" data-admin-theme="night">' in response.text
            assert '/static/css/quiz-brand.css' in response.text
            assert 'class="mq-mark" aria-hidden="true"' in response.text
            assert '<script src="https://' not in response.text
            stylesheet = await client.get('/static/css/quiz-brand.css')
            assert stylesheet.status_code == 200
            assert 'prefers-reduced-motion' in stylesheet.text
    asyncio.run(run())
