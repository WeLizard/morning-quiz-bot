import asyncio
import importlib

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select

from tests.test_admin_auth import TOKEN, login
from tests.test_postgres_members import CHAT, pg_env, scenario
from storage.models import PhotoQuizItem, Chat
from storage.photos import PhotoCatalog, PhotoMetadataConflict, metadata_version
from storage.settings import SettingsService
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
