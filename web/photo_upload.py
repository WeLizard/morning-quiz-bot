"""Bounded raw-image upload, protected by the existing admin session and CSRF."""
import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse

from storage.photo_media import MAX_UPLOAD_BYTES, InvalidPhoto, UploadConflict, create_photo
from storage.photos import metadata_version


def make_photo_upload_router():
    router = APIRouter()
    uploads = asyncio.Semaphore(2)

    @router.post('/api/photo-quiz/uploads/{upload_id}')
    async def upload_photo(request: Request,
                           upload_id: Annotated[str, Path(pattern=r'^[a-f0-9]{32}$')],
                           correct_answer: Annotated[str, Query(min_length=1, max_length=300)],
                           enabled: bool = True,
                           replace_key: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
                           expected_version: Annotated[str | None, Query(pattern=r'^[a-f0-9]{64}$')] = None):
        if replace_key is not None and expected_version is None:
            raise HTTPException(428, 'Для замены требуется версия исходного фото')
        try:
            # Bound queued/slow uploads too. No multipart parser/temp spooling.
            async with asyncio.timeout(60):
                async with uploads:
                    raw = bytearray()
                    async for chunk in request.stream():
                        if len(raw) + len(chunk) > MAX_UPLOAD_BYTES:
                            raise HTTPException(413, 'Изображение превышает 10 МиБ.')
                        raw.extend(chunk)
                    key, value, created = await create_photo(request.app.state.admin_database,
                        upload_id, bytes(raw), correct_answer, enabled, replace_key=replace_key, expected_version=expected_version)
        except TimeoutError as exc:
            raise HTTPException(408, 'Загрузка не завершена. Повторите отправку в той же форме.') from exc
        except InvalidPhoto as exc:
            raise HTTPException(422, str(exc)) from exc
        except UploadConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, 'Не удалось сохранить изображение. Проверьте место и доступ к каталогу; повторите в той же форме.') from exc
        return JSONResponse(status_code=201 if created else 200, content={
            'name': key, 'version': metadata_version(value), 'created': created,
            'image_url': f'/api/images/{key}.webp', **value})

    return router
