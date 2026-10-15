"""Adapter for QuizzyWizzy c937c277. No independent login or database.

Install inside web.mini_app:create_app BEFORE serving requests. Migration is
separate and must have completed. The module never calls create_all/migrations.
"""
from contextlib import asynccontextmanager
import asyncio
import json
import os
import random
import time
from .persistence import Unit, tables
from .service import FarmService, Principal
from .api import create_router, install_boundary
from .domain import need
from .rate_limits import SharedRateLimits, RateSettings, rate_table, PREFLIGHT_SECONDS, unavailable
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
from storage.question_bank import QuestionBank, normalized


_QUESTION_COUNT = text("""
    SELECT COALESCE(SUM(CASE WHEN json_typeof(questions) = 'array'
        THEN json_array_length(questions) ELSE 0 END), 0)
    FROM question_categories WHERE archived = false
""")
_QUESTION_CATEGORY = text("""
    SELECT name, CASE WHEN json_typeof(questions) = 'array'
        THEN json_array_length(questions) ELSE 0 END AS question_count
    FROM question_categories
    WHERE archived = false AND CASE WHEN json_typeof(questions) = 'array'
        THEN json_array_length(questions) ELSE 0 END > 0
    ORDER BY random() LIMIT 1
""")
_QUESTION_ONE = text("""
    SELECT CAST(questions -> CAST(:index AS integer) AS text)
    FROM question_categories
    WHERE name = :name AND archived = false AND json_typeof(questions) = 'array'
""")
_QUESTION_PAGE = text("""
    SELECT CAST(item.source AS text)
    FROM question_categories AS category
    CROSS JOIN LATERAL json_array_elements(
        CASE WHEN json_typeof(category.questions) = 'array'
            THEN category.questions ELSE '[]'::json END
    ) WITH ORDINALITY AS item(source, ordinal)
    WHERE category.archived = false
    ORDER BY category.name, item.ordinal
    LIMIT :take OFFSET :skip
""")


async def _farm_question(session):
    """Read bounded pages from the current Classic PG bank, never ORM-load its arrays."""
    category = (await session.execute(_QUESTION_CATEGORY)).first()
    if category:
        index = random.SystemRandom().randrange(category[1])
        source_json = (await session.execute(_QUESTION_ONE, {'name': category[0], 'index': index})).scalar_one_or_none()
        if source_json is not None:
            source = json.loads(source_json)
            if QuestionBank.is_valid(source):
                item = normalized(source)
                return [{'question': item['question'], 'options': item['options'],
                         'correct_option_text': item['correct']}]
    total = int((await session.execute(_QUESTION_COUNT)).scalar_one())
    if not total:
        return []
    start = random.SystemRandom().randrange(total)
    # A random starting point gives a different question; bounded pages preserve
    # exact valid/archived filtering even when a bank contains legacy bad rows.
    for begin, end in ((start, total), (0, start)):
        for offset in range(begin, end, 32):
            rows = (await session.execute(_QUESTION_PAGE, {'skip': offset, 'take': min(32, end-offset)})).scalars()
            for source_json in rows:
                source = json.loads(source_json)
                if QuestionBank.is_valid(source):
                    item = normalized(source)
                    return [{'question': item['question'], 'options': item['options'],
                             'correct_option_text': item['correct']}]
    return []


def register_models():
    from storage.models import Base
    rate_table(Base.metadata)
    return tables(Base.metadata)


def install_farm(app, database, settings, *, allowed_user_ids=None, clock=time.time):
    """Preserve host auth, same transaction, moderation and private-test boundary."""
    if os.getenv('QW_FARM_ENABLED') != '1':
        return
    schema=register_models()
    from storage.admin_actions import operation_fence, access_allowed_in
    guest_store=app.state.guest_store
    mini_store=app.state.mini_store
    shared = os.getenv('QW_FARM_SHARED_RATE_ENABLED') == '1'
    limiter = None
    if shared:
        quota_settings = RateSettings.from_env()
        if quota_settings.secret == settings.bot_token:
            raise ValueError('QW_FARM_RATE_SECRET must not reuse the Telegram bot token')
        from storage.models import Base
        limiter = SharedRateLimits(database, rate_table(Base.metadata), quota_settings)
        app.state.farm_shared_rate = limiter

    @asynccontextmanager
    async def authenticated(request):
        from web.principal import PrincipalError, resolve_principal
        mode=request.query_params.get('identity')
        need(mode in {None,'guest','telegram'},'identity','Неизвестный способ входа.',422)
        if mode=='guest' or (mode is None and not request.cookies.get('mqb_mini')):
            need(allowed_user_ids is None,'private_test','Гостевой вход закрыт в этом тестовом контуре.',403)

        async def gate(session, user_id):
            # Same order as before: maintenance check after the host session is verified.
            need(await access_allowed_in(session, **({} if user_id is None else {'user_id': user_id})),
                 'maintenance', 'Платформа на обслуживании. Прогресс сохранён.', 503)

        try:
            async with resolve_principal(request, database=database, guest_store=guest_store,
                                         mini_store=mini_store, lock=True, identity=mode, gate=gate) as (session, who):
                need(session.get_bind().dialect.name=='postgresql','database','Для интеграции требуется PostgreSQL.',503)
                async def farm_question_provider(current_session):
                    return await _farm_question(current_session)

                yield FarmService(Unit(session,schema),Principal(who.account_id,who.display_name,who.channel,who.address_form),
                                  clock=clock,speed=1,question_provider=farm_question_provider)
        except PrincipalError as error:
            need(False,error.code,error.message,error.status)

    @asynccontextmanager
    async def context(request):
        if limiter is not None:
            # Commit quota after verified host auth, before opening the game tx.
            # Re-authentication below catches revocation/moderation in this gap.
            scope = 'account_read' if request.method in {'GET', 'HEAD'} else 'account_write'
            try:
                async with asyncio.timeout(PREFLIGHT_SECONDS):
                    async with authenticated(request) as service:
                        await limiter.consume_in(service.u.connection, scope, service.p.account_id)
            except (SQLAlchemyError, OSError, TimeoutError):
                raise unavailable() from None
        async with authenticated(request) as service:
            yield service

    # Put exact Farm paths before the old /app/{asset} catch-all. Other games'
    # routes and their relative order are not modified.
    before=len(app.router.routes)
    app.include_router(create_router(context,origin=settings.origin,
        bot_username=getattr(settings,'bot_username','') or os.getenv('MINI_APP_BOT_USERNAME',''),
        mini_app_short_name=os.getenv('MINI_APP_SHORT_NAME','play')))
    added=app.router.routes[before:]
    app.router.routes[:]=added+app.router.routes[:before]
    install_boundary(app,settings.origin, shared=shared)
