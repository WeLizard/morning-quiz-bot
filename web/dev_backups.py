"""Admin-only dev archives; restore-in-place is deliberately offline CLI only."""
import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from storage import dev_backups


class Confirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmation: str


async def invoke(operation):
    try:
        return await operation
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception:
        raise HTTPException(503, 'Локальная операция архива недоступна. Проверьте Docker и место на диске.') from None


def make_backups_router():
    router = APIRouter(prefix='/api/dev-backups')
    operations = asyncio.Lock()

    @router.get('')
    async def backups():
        return {'items': await asyncio.to_thread(dev_backups.listing), 'restore_method': 'offline PowerShell; services must be stopped'}

    @router.post('')
    async def create(request: Request):
        async with operations:
            result = await invoke(dev_backups.create(request.app.state.admin_database))
        return {'id': result['id'], 'created_at': result['created_at'], 'files': len(result['files'])}

    @router.post('/{backup_id}/verify')
    async def verify(request: Request, backup_id: Annotated[str, Path(pattern=r'^[a-f0-9]{32}$')]):
        async with operations:
            return await invoke(dev_backups.verify_restore(request.app.state.admin_database, backup_id))

    @router.get('/{backup_id}/download')
    async def download(backup_id: Annotated[str, Path(pattern=r'^[a-f0-9]{32}$')]):
        await invoke(asyncio.to_thread(dev_backups.read_verified, backup_id))
        return FileResponse(dev_backups.path_for(backup_id), filename=f'dev-backup-{backup_id}.zip')

    @router.post('/{backup_id}/trash')
    async def trash(backup_id: Annotated[str, Path(pattern=r'^[a-f0-9]{32}$')], data: Confirmation):
        if data.confirmation != backup_id:
            raise HTTPException(422, 'Введите ID архива целиком')
        async with operations:
            return await invoke(asyncio.to_thread(dev_backups.trash, backup_id))

    return router
