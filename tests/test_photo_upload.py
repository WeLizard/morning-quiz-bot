import asyncio
from contextlib import asynccontextmanager
from io import BytesIO
from uuid import uuid4

from fastapi import FastAPI
import httpx
from PIL import Image
import pytest
from sqlalchemy import delete

from storage.models import PhotoQuizItem
from storage.photo_media import (InvalidPhoto, UploadConflict, create_photo, normalize_image,
                                 publish_image, MANAGED_PREFIX)
from storage.photos import PhotoCatalog, metadata_version
from tests.test_admin_auth import TOKEN, login
from tests.test_postgres_members import pg_env, scenario
from tests.test_postgres_photos import manager
from web.admin_auth import AdminAuth, install_admin_auth
from web.postgres_admin import install_postgres_admin


def picture(fmt='PNG', size=(80, 60), color='green', **kwargs):
    output = BytesIO()
    Image.new('RGB', size, color).save(output, format=fmt, **kwargs)
    return output.getvalue()


@pytest.mark.parametrize('fmt', ['PNG', 'JPEG', 'WEBP'])
def test_reencodes_supported_formats_without_embedded_metadata(fmt):
    exif = Image.Exif()
    exif[270] = 'private description'
    result, size = normalize_image(picture(fmt, exif=exif))
    with Image.open(BytesIO(result)) as image:
        assert image.format == 'WEBP' and image.size == size == (80, 60)
        assert not image.getexif() and 'icc_profile' not in image.info


def test_rotates_exif_and_bounds_output():
    exif = Image.Exif()
    exif[274] = 6
    _, size = normalize_image(picture('JPEG', (2400, 1200), exif=exif))
    assert size == (1024, 2048)


@pytest.mark.parametrize('raw', [b'', b'<svg><script/></svg>', b'not an image', b'GIF89a'])
def test_rejects_invalid_file_bytes(raw):
    with pytest.raises(InvalidPhoto):
        normalize_image(raw)


def test_rejects_truncated_pixels_animation_and_dimensions(monkeypatch):
    with pytest.raises(InvalidPhoto):
        normalize_image(picture()[:50])
    output = BytesIO()
    Image.new('RGB', (10, 10), 'red').save(output, format='WEBP', save_all=True,
        append_images=[Image.new('RGB', (10, 10), 'blue')], duration=100, loop=0)
    with pytest.raises(InvalidPhoto, match='Анимация'):
        normalize_image(output.getvalue())
    with pytest.raises(InvalidPhoto, match='20:1'):
        normalize_image(picture(size=(50, 1)))
    monkeypatch.setattr('storage.photo_media.MAX_PIXELS', 100)
    with pytest.raises(InvalidPhoto, match='мегапикселей'):
        normalize_image(picture())


def test_publish_is_immutable_and_cleans_staging(tmp_path):
    publish_image(tmp_path, 'fixture', b'first')
    publish_image(tmp_path, 'fixture', b'first')
    with pytest.raises(UploadConflict):
        publish_image(tmp_path, 'fixture', b'second')
    assert (tmp_path / 'fixture.webp').read_bytes() == b'first'
    assert not list(tmp_path.glob('*.part'))


def test_concurrent_upload_retry_keeps_edits_and_bot_uses_catalog(pg_env, tmp_path):
    async def run():
        async with scenario(pg_env) as db:
            upload_id = uuid4().hex
            key = f'{MANAGED_PREFIX}{upload_id}-photo'
            try:
                raw = picture()
                results = await asyncio.gather(*[create_photo(db, upload_id, raw, 'Сова', True, root=tmp_path) for _ in range(3)])
                assert sum(result[2] for result in results) == 1
                assert len(list(tmp_path.glob('*.webp'))) == 1
                catalog = PhotoCatalog(db)
                current = (await catalog.load())[key]
                await catalog.patch(key, {'correct_answer': 'Филин', 'enabled': False}, expected_version=metadata_version(current))
                repeated = await create_photo(db, upload_id, raw, 'Сова', True, root=tmp_path)
                assert repeated[1]['correct_answer'] == 'Филин' and not repeated[1]['enabled']
                with pytest.raises(UploadConflict):
                    await create_photo(db, upload_id, picture(color='blue'), 'Сова', True, root=tmp_path)
                bot = manager(db, tmp_path)
                bot.images_metadata = await catalog.load()
                assert await bot._prepare_question() is None
                current = bot.images_metadata[key]
                await catalog.patch(key, {'enabled': True}, expected_version=metadata_version(current))
                bot.images_metadata = await catalog.load()
                question = await bot._prepare_question()
                assert question['display_answer'] == 'Филин'
                storage = bot.images_metadata[key]['storage_name']
                assert question['image_path'].endswith(f'{storage}.webp')
                # A current game keeps its existing question object after an edit.
                current = bot.images_metadata[key]
                await catalog.patch(key, {'correct_answer': 'Другой ответ'}, expected_version=metadata_version(current))
                assert question['display_answer'] == 'Филин'
                (tmp_path / f'{storage}.webp').unlink()
                repaired = await create_photo(db, upload_id, raw, 'Сова', True, root=tmp_path)
                assert not repaired[2] and repaired[1]['correct_answer'] == 'Другой ответ'
                assert (tmp_path / f'{storage}.webp').exists()
            finally:
                async with db.transaction() as session:
                    await session.execute(delete(PhotoQuizItem).where(PhotoQuizItem.media_key == key))
    asyncio.run(run())


def test_failed_commit_leaves_unplayed_file_and_retry_recovers(pg_env, tmp_path):
    async def run():
        async with scenario(pg_env) as db:
            upload_id = uuid4().hex
            key = f'{MANAGED_PREFIX}{upload_id}-photo'
            class FailingDatabase:
                @asynccontextmanager
                async def transaction(self):
                    async with db.transaction() as session:
                        yield session
                        raise RuntimeError('simulated commit failure')
            try:
                with pytest.raises(RuntimeError, match='simulated'):
                    await create_photo(FailingDatabase(), upload_id, picture(), 'Сова', True, root=tmp_path)
                assert len(list(tmp_path.glob('sha256-*.webp'))) == 1
                assert key not in await PhotoCatalog(db).load()
                bot = manager(db, tmp_path)
                bot.images_metadata = await PhotoCatalog(db).load()
                assert bot._get_image_groups() == {}
                assert (await create_photo(db, upload_id, picture(), 'Сова', True, root=tmp_path))[2]
            finally:
                async with db.transaction() as session:
                    await session.execute(delete(PhotoQuizItem).where(PhotoQuizItem.media_key == key))
    asyncio.run(run())


def test_upload_api_auth_csrf_validation_idempotence_and_serving(pg_env, tmp_path, monkeypatch):
    monkeypatch.setenv('PHOTO_IMAGES_DIR', str(tmp_path))
    async def run():
        async with scenario(pg_env) as db:
            upload_id = uuid4().hex
            key = f'{MANAGED_PREFIX}{upload_id}-photo'
            app = FastAPI()
            install_postgres_admin(app)
            install_admin_auth(app, auth=AdminAuth(TOKEN))
            try:
                async with app.router.lifespan_context(app):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1') as client:
                        path = f'/api/photo-quiz/uploads/{upload_id}'
                        params = {'correct_answer': 'Тест <без разметки>', 'enabled': 'false'}
                        assert (await client.post(path, params=params, content=picture())).status_code == 401
                        csrf = await login(client)
                        assert (await client.post(path, params=params, content=picture())).status_code == 403
                        client.headers['X-CSRF-Token'] = csrf
                        for bad in [b'', b'<svg/>']:
                            assert (await client.post(path, params=params, content=bad)).status_code == 422
                        assert not list(tmp_path.iterdir())
                        response = await client.post(path, params=params, content=picture())
                        assert response.status_code == 201
                        item = response.json()
                        assert item['name'] == key and not item['enabled']
                        assert (await client.post(path, params=params, content=picture())).status_code == 200
                        assert (await client.post(path, params=params, content=picture(color='red'))).status_code == 409
                        assert (await client.post(path, params={'correct_answer': '  '}, content=picture())).status_code == 422
                        served = await client.get(item['image_url'])
                        assert served.status_code == 200 and served.headers['content-type'] == 'image/webp'
                        assert served.content == (tmp_path / f"{item['storage_name']}.webp").read_bytes()
                        listed = (await client.get('/api/photo-quiz')).json()['photos']
                        assert next(p for p in listed if p['name'] == key)['has_image']
                        monkeypatch.setattr('web.photo_upload.MAX_UPLOAD_BYTES', 4)
                        async def chunks():
                            yield b'123'
                            yield b'456'
                        assert (await client.post(path, params=params, content=chunks())).status_code == 413
                        assert (await client.post('/api/upload-image', content=picture())).status_code == 501
            finally:
                async with db.transaction() as session:
                    await session.execute(delete(PhotoQuizItem).where(PhotoQuizItem.media_key == key))
    asyncio.run(run())
