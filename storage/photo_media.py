"""Immutable managed photo uploads. Legacy media is never replaced or deleted."""
import asyncio
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import tempfile

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select, text

from .models import PhotoQuizItem
from .photos import metadata, metadata_version

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000
MANAGED_PREFIX = 'mqb-upload-'
CONTENT_PREFIX = 'sha256-'


class InvalidPhoto(ValueError):
    pass


class UploadConflict(ValueError):
    pass


def images_root():
    default = Path(__file__).resolve().parents[1] / 'data' / 'images'
    return Path(os.getenv('PHOTO_IMAGES_DIR') or default).resolve()


def storage_name(media_key, value):
    """Resolve a code-owned basename; legacy rows keep their historical key."""
    name = (value or {}).get('storage_name') or media_key
    if (not isinstance(name, str) or not 1 <= len(name) <= 512
            or name in {'.', '..'} or Path(name).name != name
            or '/' in name or '\\' in name
            or any(ord(char) < 32 for char in name)):
        raise InvalidPhoto('Некорректная ссылка на изображение в каталоге.')
    return name


def verified_image_path(root, media_key, value):
    root = Path(root).resolve()
    path = (root / f'{storage_name(media_key, value)}.webp').resolve()
    if path.parent != root or path.is_symlink() or not path.is_file():
        return None
    expected = (value or {}).get('image_sha256')
    if expected and (not re.fullmatch(r'[a-f0-9]{64}', expected)
                     or sha256(path.read_bytes()).hexdigest() != expected):
        return None
    return path


def normalize_image(raw):
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise InvalidPhoto('Выберите изображение размером до 10 МиБ.')
    try:
        with Image.open(BytesIO(raw), formats=['JPEG', 'PNG', 'WEBP']) as source:
            width, height = source.size
            if width * height > MAX_PIXELS or max(width, height) > min(width, height) * 20:
                raise InvalidPhoto('Максимум 20 мегапикселей и соотношение сторон 20:1.')
            if getattr(source, 'n_frames', 1) != 1:
                raise InvalidPhoto('Анимация не поддерживается. Выберите одно изображение.')
            source.load()  # Actually decode; a valid header is insufficient.
            oriented = ImageOps.exif_transpose(source)
            oriented.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            pixels = oriented.convert('RGBA')
            # New object carries no EXIF/GPS, comments or ICC metadata.
            clean = Image.frombytes('RGBA', pixels.size, pixels.tobytes())
            output = BytesIO()
            clean.save(output, format='WEBP', quality=90, method=4)
            return output.getvalue(), clean.size
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise InvalidPhoto('Файл повреждён или не является JPEG, PNG или WebP.') from exc


def publish_image(root, key, content):
    """Publish completely written bytes without overwriting an existing pathname."""
    root.mkdir(parents=True, exist_ok=True)
    target = root / f'{key}.webp'
    if target.is_symlink():
        raise UploadConflict('Путь изображения уже занят.')
    if target.exists():
        if sha256(target.read_bytes()).digest() != sha256(content).digest():
            raise UploadConflict('Этот идентификатор уже связан с другим изображением.')
        return
    fd, temporary = tempfile.mkstemp(prefix='.upload-', suffix='.part', dir=root)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic create, unlike replace() it cannot clobber another file.
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink() or target.read_bytes() != content:
                raise UploadConflict('Путь изображения уже занят.')
        if os.name != 'nt':
            directory = os.open(root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


async def create_photo(database, upload_id, raw, answer, enabled, *, root=None, replace_key=None, expected_version=None):
    if not re.fullmatch(r'[a-f0-9]{32}', upload_id):
        raise InvalidPhoto('Недопустимый идентификатор загрузки.')
    answer = answer.strip()
    if not 1 <= len(answer) <= 300 or not isinstance(enabled, bool):
        raise InvalidPhoto('Укажите ответ длиной от 1 до 300 символов.')
    content, (width, height) = await asyncio.to_thread(normalize_image, raw)
    fingerprint = sha256(json.dumps([sha256(raw).hexdigest(), answer, enabled], ensure_ascii=False).encode()).hexdigest()
    if replace_key is not None:
        fingerprint = sha256(json.dumps([fingerprint, replace_key, expected_version]).encode()).hexdigest()
    key = f'{MANAGED_PREFIX}{upload_id}-photo'  # Stable idempotency receipt for this form.
    content_digest = sha256(content).hexdigest()
    content_name = f'{CONTENT_PREFIX}{content_digest}'
    root = (root or images_root()).resolve()
    async with database.transaction() as session:
        lock_id = int.from_bytes(sha256(key.encode()).digest()[:8], 'big', signed=True)
        await session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock_id})
        item = await session.scalar(select(PhotoQuizItem).where(PhotoQuizItem.media_key == key).with_for_update())
        if item and (item.metadata_json or {}).get('upload_fingerprint') != fingerprint:
            raise UploadConflict('Загрузка уже сохранена с другими данными. Откройте новую форму.')
        previous = None
        if replace_key is not None and item is None:
            previous = await session.scalar(select(PhotoQuizItem).where(PhotoQuizItem.media_key == replace_key).with_for_update())
            if previous is None or metadata_version(metadata(previous)) != expected_version or (previous.metadata_json or {}).get('archived'):
                raise UploadConflict('Заменяемое фото изменилось или удалено. Обновите каталог.')
        # A crash/uncertain commit may leave an unreferenced immutable file.
        # Keep it for retry; managed files absent from the catalog are not played.
        await asyncio.to_thread(publish_image, root, content_name, content)
        created = item is None
        if created:
            item = PhotoQuizItem(media_key=key, correct_answer=answer, enabled=enabled, hints={},
                metadata_json={'display_answer': answer, 'upload_fingerprint': fingerprint,
                               'image_sha256': content_digest, 'storage_name': content_name,
                               'width': width, 'height': height})
            session.add(item)
            if previous is not None:
                # New immutable pathname: active games keep their original pixels.
                item.hints = previous.hints
                item.metadata_json = {**item.metadata_json, 'replaces': replace_key}
                previous.metadata_json = {**(previous.metadata_json or {}), 'archived': True,
                    'enabled_before_archive': previous.enabled, 'replaced_by': key}
                previous.enabled = False
            await session.flush()
        result = metadata(item)
    return key, result, created
