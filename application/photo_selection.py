"""Transport-independent, verified Photo catalog selection."""
import asyncio
import random
import re

from sqlalchemy import select

from storage.models import PhotoQuizItem
from storage.photo_media import images_root, verified_image_path

_VERIFY_BATCH_SIZE = 16
_EMPTY_CATALOG = 'В каталоге нет доступных фото-загадок.'
_IMAGE_DIGEST_ANSWER = re.compile(r'sha256-[0-9a-f]{64}', re.IGNORECASE)


def _candidate(media_key, correct_answer, enabled, metadata_json):
    # Old dev seeds incorrectly used content-addressed image filenames as
    # answers. Do not count or select those legacy rows as playable questions.
    if _IMAGE_DIGEST_ANSWER.fullmatch(str(correct_answer or '').strip()):
        return None
    value = dict(metadata_json or {})
    value['correct_answer'] = correct_answer
    value['enabled'] = enabled
    if value.get('archived'):
        return None
    answer = str(value.get('display_answer') or value.get('correct_answer') or '').strip()
    if not answer:
        return None
    return {'display_answer': answer, 'media': {
        'media_key': media_key, 'storage_name': value.get('storage_name'),
        'image_sha256': value.get('image_sha256')}}


async def available_photo_questions(session):
    """Return metadata-eligible questions without reading or hashing media files."""
    rows = (await session.execute(select(
        PhotoQuizItem.media_key, PhotoQuizItem.correct_answer,
        PhotoQuizItem.enabled, PhotoQuizItem.metadata_json,
    ).where(PhotoQuizItem.enabled.is_(True)).order_by(PhotoQuizItem.media_key))).all()
    available = [item for row in rows if (item := _candidate(*row)) is not None]
    if not available:
        raise LookupError(_EMPTY_CATALOG)
    return available


def _verified_batch(root, candidates):
    """Synchronous filesystem work; called only in a worker thread."""
    return [candidate for candidate in candidates
            if verified_image_path(root, candidate['media']['media_key'], candidate['media']) is not None]


async def select_photo_questions(session, count):
    candidates = await available_photo_questions(session)
    # Shuffle the complete candidate population first so batch boundaries cannot
    # favor catalog order or any particular subset.
    random.SystemRandom().shuffle(candidates)
    root = images_root()
    valid = []
    for offset in range(0, len(candidates), _VERIFY_BATCH_SIZE):
        batch = candidates[offset:offset + _VERIFY_BATCH_SIZE]
        valid.extend(await asyncio.to_thread(_verified_batch, root, batch))
        if len(valid) >= count:
            break
    if not valid:
        raise LookupError(_EMPTY_CATALOG)
    if count <= len(valid):
        return valid[:count]
    return [valid[index % len(valid)] for index in range(count)]
