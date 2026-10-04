"""Гейт каталога фото: запись без файла — ошибка, файл без записи — информация."""
import asyncio
from hashlib import sha256

from sqlalchemy import delete

from storage.models import PhotoQuizItem
from storage.photo_media import catalog_status, publish_image
from tests.test_postgres_members import pg_env, scenario


def test_media_catalog_gate_detects_missing_and_unverified_rows(pg_env, tmp_path):
    """Каталог общий для всех тестов, поэтому проверяем вхождение, а не общее число."""
    keys = ['good', 'legacy-photo', 'mismatch', 'broken']

    async def run():
        async with scenario(pg_env) as db:
            root = tmp_path / 'images'
            content = b'RIFF-managed-webp-bytes'
            digest = sha256(content).hexdigest()
            async with db.transaction() as session:      # остатки прошлого прогона
                await session.execute(delete(PhotoQuizItem).where(PhotoQuizItem.media_key.in_(keys)))
            # Управляемая загрузка: файл по контент-адресу и подпись в каталоге.
            publish_image(root, f'sha256-{digest}', content)
            # Легаси-запись без подписи: достаточно существования файла.
            publish_image(root, 'legacy-photo', content)
            async with db.transaction() as session:
                session.add(PhotoQuizItem(media_key='good', correct_answer='Сова', enabled=True, hints={},
                    metadata_json={'storage_name': f'sha256-{digest}', 'image_sha256': digest}))
                session.add(PhotoQuizItem(media_key='legacy-photo', correct_answer='Лось', enabled=True,
                    hints={}, metadata_json={}))
                session.add(PhotoQuizItem(media_key='mismatch', correct_answer='Кит', enabled=True, hints={},
                    metadata_json={'storage_name': f'sha256-{digest}', 'image_sha256': '1' * 64}))
                session.add(PhotoQuizItem(media_key='broken', correct_answer='Ёж', enabled=True, hints={},
                    metadata_json={'storage_name': 'sha256-' + '0' * 64, 'image_sha256': '0' * 64}))
            (root / 'sha256-orphan.webp').write_bytes(b'leftover')
            status = await catalog_status(db, root=root)
            assert status['verified'] >= 2                       # good + legacy-photo
            assert {'broken'} <= set(status['missing']) and {'broken'} <= set(status['enabled_missing'])
            assert not {'good', 'legacy-photo', 'mismatch'} & set(status['missing'])
            assert 'mismatch' in status['unverified']            # файл есть, подпись не сошлась
            assert 'sha256-orphan' in status['unreferenced']
            async with db.transaction() as session:
                await session.execute(delete(PhotoQuizItem).where(PhotoQuizItem.media_key.in_(keys)))
    asyncio.run(run())
