"""Docker-only fixture app for building_effects_smoke.py; never a deployment entrypoint."""
from datetime import datetime, timezone
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import HTTPException, Request


def create_qa_app():
    url = os.environ.get('MINI_APP_DATABASE_URL', '')
    parsed = urlsplit(url)
    if (os.environ.get('MQB_BUILDING_QA') != '1' or not Path('/.dockerenv').is_file()
            or parsed.hostname != 'postgres' or parsed.port != 5432
            or parsed.username != 'mqb_dev' or parsed.path != '/morning_quiz_dev'):
        raise RuntimeError('Building fixtures require their dedicated Docker database')

    from web.mini_app import MiniAppSettings, create_app
    from qw_farm.integration import register_models
    from qw_farm.persistence import Unit
    from qw_farm.service import FarmService, Principal
    from qw_farm.catalog import ITEMS, LEVELS
    from qw_farm.domain import apply, validate_state
    from storage.models import Account

    origin = 'http://127.0.0.1:4185'
    now = [int(datetime(2026, 11, 25, 20, 30, tzinfo=timezone.utc).timestamp())]
    app = create_app(settings=MiniAppSettings('123456:LOCAL_TEST_ONLY_012345678901234567890', origin, offline=True),
                     clock=lambda: now[0], runtime_enabled=False)
    schema = register_models()
    database = app.state.mini_store.database

    async def bounded(request):
        if request.headers.get('X-Building-QA') != 'docker-only':
            raise HTTPException(403)
        return await request.json()

    @app.post('/__qa/building-effects/setup')
    async def setup(request: Request):
        data = await bounded(request)
        async with database.transaction() as session:
            unit = Unit(session, schema)
            farm = await unit.get(data['farm_id'])
            if farm is None:
                raise HTTPException(404)
            aid = await unit.owner_account(farm['id'])
            await unit.lock('farm:' + farm['id'])
            farm.update(name='Ферма тестировщицы', coins=500_000, starter_credit=0, xp=LEVELS[11])
            farm['inventory'].update({k: 100 for k in ITEMS})
            farm['settings']['visibility'] = 'public'
            if not any(o['type'] == 'bakery' for o in farm['objects']):
                apply(farm, farm, 'build', {'type': 'bakery', 'x': 6, 'y': 3}, now[0], str(uuid4()))
            validate_state(farm)
            await unit.save(farm)
            (await session.get(Account, UUID(aid))).display_name = 'Тестировщица'
            projects, contribs = schema['projects'], schema['contribs']
            await unit.execute(projects.update().values(status='done', stage=2, opened_at=now[0] - 86400))
            for pid in ('stalls', 'tavern', 'greenhouse', 'fairground'):
                await unit.execute(contribs.insert().values(project_id=pid, account_id=UUID(aid),
                    farm_id=UUID(farm['id']), value=100_000, share_bp=10_000, tier=3, updated_at=now[0]))
            service = FarmService(unit, Principal(aid, 'Тестировщица'), clock=lambda: now[0])
            result = await service.view()
            return dict(farm_id=farm['id'], server_time=now[0], farm=result['farm'])

    @app.post('/__qa/building-effects/advance')
    async def advance(request: Request):
        data = await bounded(request)
        seconds = data.get('seconds')
        if type(seconds) is not int or not 0 <= seconds <= 7 * 86400:
            raise HTTPException(422)
        now[0] += seconds
        return {'server_time': now[0]}

    @app.post('/__qa/building-effects/budget')
    async def budget(request: Request):
        from qw_farm import daily_bonus
        data = await bounded(request)
        remaining = data.get('remaining')
        if type(remaining) is not int or remaining not in (0, 1):
            raise HTTPException(422)
        async with database.transaction() as session:
            unit = Unit(session, schema)
            await unit.lock('farm:' + data['farm_id'])
            farm = await unit.get(data['farm_id'])
            if farm is None:
                raise HTTPException(404)
            value = daily_bonus.blank(farm, now[0])
            value.update(paid=value['cap'] - remaining,
                         by_source={'house': value['cap'] - remaining})
            farm[daily_bonus.KEY] = value
            validate_state(farm)
            await unit.save(farm)
            return daily_bonus.public(farm, now[0])

    return app
