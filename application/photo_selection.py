"""Transport-independent, verified Photo catalog selection."""
import random

from sqlalchemy import select

from storage.models import PhotoQuizItem
from storage.photo_media import images_root, verified_image_path
from storage.photos import metadata


async def available_photo_questions(session):
    rows = (await session.scalars(select(PhotoQuizItem).where(
        PhotoQuizItem.enabled.is_(True)).order_by(PhotoQuizItem.media_key))).all()
    available = []
    root = images_root()
    for row in rows:
        value = metadata(row)
        if value.get('archived'):
            continue
        path = verified_image_path(root, row.media_key, value)
        answer = str(value.get('display_answer') or value.get('correct_answer') or '').strip()
        if path is not None and answer:
            available.append({'display_answer': answer, 'media': {
                'media_key': row.media_key, 'storage_name': value.get('storage_name'),
                'image_sha256': value.get('image_sha256')}})
    if not available:
        raise LookupError('В каталоге нет доступных фото-загадок.')
    return available


async def select_photo_questions(session, count):
    available = await available_photo_questions(session)
    random.SystemRandom().shuffle(available)
    if count <= len(available):
        return available[:count]
    return [available[index % len(available)] for index in range(count)]
