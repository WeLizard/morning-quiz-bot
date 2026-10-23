"""Neighbour requests: transactional escrow, limits and owner-only projections."""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4
import math
import sqlalchemy as sa

from . import economy
from .catalog import ITEMS, income_ref, level
from .domain import FarmError, need, inventory, event, reachable, named, number, unbound, validate_state
from .request_rules import upgrade, gift_daily, mutual, unlocked

COMMANDS = {'request_create', 'request_give', 'request_accept', 'request_decline', 'request_cancel', 'request_hide'}
OPEN_SECONDS = 48 * 3600
SETTLE_SECONDS = 72 * 3600


def table(metadata):
    if 'farm_requests' in metadata.tables:
        return metadata.tables['farm_requests']
    t = sa.Table('farm_requests', metadata,
        sa.Column('id', sa.Uuid, primary_key=True),
        sa.Column('requester_farm', sa.Uuid, sa.ForeignKey('farm_states.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('requester_account', sa.Uuid, sa.ForeignKey('accounts.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('audience_farm', sa.Uuid, sa.ForeignKey('farm_states.id', ondelete='RESTRICT')),
        sa.Column('item', sa.Text, nullable=False), sa.Column('qty', sa.Integer, nullable=False),
        sa.Column('offer_kind', sa.Text, nullable=False), sa.Column('offer_item', sa.Text),
        sa.Column('offer_qty', sa.Integer), sa.Column('offer_coins', sa.Integer),
        sa.Column('value', sa.Integer, nullable=False), sa.Column('status', sa.Text, nullable=False),
        sa.Column('giver_farm', sa.Uuid, sa.ForeignKey('farm_states.id', ondelete='RESTRICT')),
        sa.Column('giver_account', sa.Uuid, sa.ForeignKey('accounts.id', ondelete='RESTRICT')),
        sa.Column('created_at', sa.Float, nullable=False), sa.Column('expires_at', sa.Float, nullable=False),
        sa.Column('delivered_at', sa.Float), sa.Column('settle_by', sa.Float), sa.Column('closed_at', sa.Float),
        sa.CheckConstraint("offer_kind IN ('free','coins','item')", name='ck_farm_request_offer'),
        sa.CheckConstraint("status IN ('open','delivered','settled','returned','cancelled','expired')", name='ck_farm_request_status'),
        sa.CheckConstraint('qty BETWEEN 1 AND 20 AND value > 0', name='ck_farm_request_amount'),
        sa.CheckConstraint("(offer_kind='free' AND offer_item IS NULL AND offer_qty IS NULL AND offer_coins IS NULL) OR "
            "(offer_kind='coins' AND offer_item IS NULL AND offer_qty IS NULL AND offer_coins > 0) OR "
            "(offer_kind='item' AND offer_item IS NOT NULL AND offer_qty > 0 AND offer_coins IS NULL)", name='ck_farm_request_terms'),
        sa.CheckConstraint('giver_farm IS NULL OR giver_farm <> requester_farm', name='ck_farm_request_not_self'))
    sa.Index('ix_farm_requests_requester_status', t.c.requester_farm, t.c.status)
    sa.Index('ix_farm_requests_giver_delivered', t.c.giver_farm, t.c.delivered_at)
    return t


def available(unit):
    return getattr(unit, 't', {}).get('requests') is not None


async def neighborhood_age(unit, a, b, now):
    edge_a = a['neighbors'].get(b['id'], {})
    edge_b = b['neighbors'].get(a['id'], {})
    dates = [x.get('accepted_at') for x in (edge_a, edge_b) if x.get('accepted_at') is not None]
    if len(dates) == 2:
        return now - max(dates)
    pairs = unit.t.get('neighbor_pairs')
    if pairs is not None:
        low, high = sorted((UUID(a['id']), UUID(b['id'])))
        created = (await unit.execute(sa.select(pairs.c.created_at).where(
            pairs.c.farm_low_id == low, pairs.c.farm_high_id == high))).scalar_one_or_none()
        if created is not None:
            return now - max([created, *dates])
    return 0


async def pair_value(unit, a, b, now):
    t = unit.t['requests']; a, b = UUID(a), UUID(b)
    return int((await unit.execute(sa.select(sa.func.coalesce(sa.func.sum(t.c.value), 0)).where(
        sa.or_(sa.and_(t.c.requester_farm == a, t.c.giver_farm == b),
               sa.and_(t.c.requester_farm == b, t.c.giver_farm == a)),
        t.c.delivered_at > now - 7 * 86400))).scalar_one())


async def delivery_check(unit, row, requester, giver, now):
    need(mutual(requester, giver), 'not_neighbor', 'Просьба доступна только взаимным соседям.', 403)
    need(giver['settings'].get('allow_requests', True), 'permission_denied', 'Просьбы соседей отключены.', 403)
    need(row['audience_farm'] is None or str(row['audience_farm']) == giver['id'],
         'not_neighbor', 'Эта просьба адресована другому соседу.', 403)
    unlocked(giver, row['offer_kind'] == 'coins')
    need(await neighborhood_age(unit, requester, giver, now) >= 86400,
         'request_age', 'Отдавать посылки можно через 24 часа после начала соседства.')
    unbound([row['item']])
    need(row['item'] in reachable(giver), 'request_unreachable', 'Сначала научись производить этот товар.')
    need(await pair_value(unit, requester['id'], giver['id'], now) + row['value'] <= income_ref(level(requester['xp'])) * 5 // 100,
         'request_pair_limit', 'Недельный лимит обмена между этими фермами исчерпан.')
    need(giver['inventory'].get(row['item'], 0) >= row['qty'], 'missing_goods', 'Не хватает товара для посылки.')
    # Validate the shared counters on a disposable copy for projections; command consumes after validation.
    gift_daily(deepcopy(giver), requester['id'], now)


async def limits(unit, farm, now):
    t = unit.t['requests']; uid = UUID(farm['id']); day = economy.moscow_day(now)
    lo = day * 86400 - economy.TZ_OFFSET
    rows = (await unit.execute(sa.select(t.c.value).where(t.c.requester_farm == uid,
        t.c.created_at >= lo, t.c.created_at < lo + 86400))).all()
    opened = int((await unit.execute(sa.select(sa.func.count()).select_from(t).where(
        t.c.requester_farm == uid, t.c.status.in_(['open', 'delivered'])))).scalar_one())
    maximum = income_ref(level(farm['xp'])) * 2 // 100
    return dict(count_left=max(0, 3 - len(rows)), value_left=max(0, maximum - sum(r[0] for r in rows)),
                value_limit=maximum, open_left=max(0, 3 - opened))


async def notify(unit, farm, row, kind, now, text, *, available_at=None):
    """Enqueue in the gameplay transaction, with durable per-recipient cadence fences."""
    upgrade(farm)
    if not farm['settings'].get('notify_requests', True) or unit.dialect != 'postgresql':
        return
    metadata = unit.t['states'].metadata
    identities = metadata.tables.get('account_identities')
    outbox = metadata.tables.get('notification_outbox')
    if identities is None or outbox is None:
        return
    account = await unit.owner_account(farm['id'])
    subject = (await unit.execute(sa.select(identities.c.provider_subject).where(
        identities.c.account_id == UUID(account), identities.c.provider == 'telegram',
        identities.c.revoked_at.is_(None), identities.c.verified_at.is_not(None)).limit(1))).scalar_one_or_none()
    if subject is None or not str(subject).lstrip('-').isdigit():
        return
    rec = upgrade(farm)['telegram']
    event_name = kind
    request_id = str(row['id'])
    payload = dict(text=text, request=request_id, event=kind, recipient_farm=farm['id'])
    url = getattr(unit, 'notification_url', '')
    if isinstance(url, str) and url.startswith('https://'):
        payload['url'] = url
    if kind == 'digest':
        day = economy.moscow_day(now)
        marker = 'digest:' + str(day)
        event_name = 'digest-' + str(day)
        previous = rec.get(marker)
        if previous:
            # Aggregate new requests into today's queued digest, without creating another message.
            if isinstance(previous, str):
                await unit.execute(outbox.update().where(outbox.c.dedupe_key == previous,
                    outbox.c.status == 'pending').values(payload=payload))
            return
        due = max(now, rec.get('last_at', 0) + 3600)
        rec['last_at'] = due
        rec[marker] = f"farm-request:{request_id}:{event_name}:{farm['id']}"
        for key in list(rec):
            if key.startswith('digest:') and key != marker:
                del rec[key]
    else:
        fence = request_id + ':' + kind
        sent = rec.setdefault('sent', [])
        if fence in sent:
            return
        sent.append(fence)
        rec['sent'] = sent[-200:]
        due = available_at if available_at is not None else max(now, rec.get('last_at', 0) + 3600)
        if available_at is None:
            rec['last_at'] = due
    from storage.notifications import NotificationQueue
    await NotificationQueue.enqueue_in(unit.connection, kind='farm.request',
        dedupe_key=f"farm-request:{request_id}:{event_name}:{farm['id']}", user_id=int(subject), chat_id=int(subject),
        available_at=datetime.fromtimestamp(due, timezone.utc), payload=payload)


async def announce_created(unit, requester, row, recipients, account, now):
    """Cards, journal and daily Telegram digest appear even if the neighbour is offline."""
    t = unit.t['requests']
    for fid in recipients:
        neighbor = await unit.get(fid)
        if not mutual(requester, neighbor) or not neighbor['settings'].get('allow_requests', True):
            continue
        if row['audience_farm'] is not None and str(row['audience_farm']) != fid:
            continue
        before = deepcopy(neighbor)
        state = upgrade(neighbor)
        state['seen'] = [*state['seen'], str(row['id'])][-100:]
        event(neighbor, now, f"Сосед просит: {ITEMS[row['item']]['name']} ×{row['qty']}.", 'social')
        peers = [UUID(other) for other, edge in neighbor['neighbors'].items() if edge.get('status') == 'accepted']
        active = (await unit.execute(sa.select(t.c.item).where(t.c.status == 'open', t.c.expires_at > now,
            t.c.requester_farm.in_(peers), sa.or_(t.c.audience_farm.is_(None), t.c.audience_farm == UUID(fid))))).all()
        text = 'Соседи просят: ' + ', '.join(dict.fromkeys(ITEMS[item]['name'] for (item,) in active)) + '.'
        await notify(unit, neighbor, row, 'digest', now, text)
        neighbor['revision'] += 1
        await unit.save(neighbor)
        await unit.record(account, f"request:{row['id']}:received", 'request_received', before, neighbor, now)


async def persist_transition(unit, row, farms, before, status, actor, now):
    """One ledger row per farm and status; status CAS always precedes movement persistence."""
    for fid, farm in farms.items():
        event(farm, now, {'delivered':'Ёж понёс посылку соседу.', 'settled':'Сосед принял посылку — спасибо!',
             'returned':'Ёж вернул посылку дарителю.', 'cancelled':'Просьба отменена.',
             'expired':'Срок просьбы истёк.', 'open':'Записка отправлена соседям.'}[status], 'social')
        farm['revision'] += 1
        validate_state(farm)
        await unit.save(farm)
        await unit.record(actor, f"request:{row['id']}:{status}", 'request_' + status, before[fid], farm, now)


async def locked_row(unit, rid, actor_farm=None, *, prelocked=None):
    t = unit.t['requests']
    row = (await unit.execute(sa.select(t).where(t.c.id == rid))).mappings().first()
    need(row is not None, 'request_not_found', 'Просьба не найдена.', 404)
    ids = {str(row['requester_farm'])}
    if row['giver_farm'] is not None:
        ids.add(str(row['giver_farm']))
    if actor_farm:
        ids.add(actor_farm)
    need(prelocked is None or ids <= prelocked, 'request_retry', 'Состояние посылки изменилось. Обнови ферму.')
    await unit.lock(*('farm:' + fid for fid in sorted(ids)))
    row = (await unit.execute(sa.select(t).where(t.c.id == rid).with_for_update())).mappings().first()
    need(row is not None, 'request_not_found', 'Просьба не найдена.', 404)
    # An open row can only gain a giver. A different giver winning while locks were pending
    # makes this command closed; never touch their farm without its lock.
    if row['giver_farm'] is not None and str(row['giver_farm']) not in ids:
        raise FarmError('request_closed', 'Уже отнесли — спасибо!')
    farms = {fid: await unit.get(fid) for fid in sorted(ids)}
    need(all(farms.values()), 'request_not_found', 'Ферма участника недоступна.', 404)
    for farm in farms.values():
        upgrade(farm)
    return dict(row), farms


async def transition(unit, row, farms, status, actor, now):
    t = unit.t['requests']; old = row['status']
    values = dict(status=status)
    if status == 'delivered':
        giver = next(f for fid, f in farms.items() if fid != str(row['requester_farm']))
        values.update(giver_farm=UUID(giver['id']), giver_account=UUID(actor), delivered_at=now, settle_by=now + SETTLE_SECONDS)
    else:
        values['closed_at'] = now
    changed = await unit.execute(t.update().where(t.c.id == row['id'], t.c.status == old).values(**values))
    need(changed.rowcount == 1, 'request_closed', 'Просьба уже закрыта.')
    before = deepcopy(farms)
    requester = farms[str(row['requester_farm'])]
    if status == 'delivered':
        inventory(giver, {row['item']: row['qty']}, -1)
        gift_daily(giver, requester['id'], now)
        await notify(unit, requester, row, 'delivered', now, f"Сосед привёз {ITEMS[row['item']]['name']} ×{row['qty']}.")
        await notify(unit, requester, row, 'reminder', now, 'Ёж ждёт: прими посылку в течение 12 часов.',
                     available_at=now + SETTLE_SECONDS - 12 * 3600)
    elif status == 'returned':
        inventory(farms[str(row['giver_farm'])], {row['item']: row['qty']})
    elif status == 'settled':
        giver = farms[str(row['giver_farm'])]
        inventory(requester, {row['item']: row['qty']})
        if row['offer_kind'] == 'coins':
            cost = row['offer_coins']
            need(requester['coins'] - requester['starter_credit'] >= cost, 'earned_coins', 'Нужны заработанные монеты.')
            net = cost - math.ceil(cost * 3 / 100)
            need(giver['coins'] + net <= 10**12, 'balance_limit', 'У соседа нет места на балансе.')
            requester['coins'] -= cost
            giver['coins'] += net
        elif row['offer_kind'] == 'item':
            unbound([row['offer_item']])
            inventory(requester, {row['offer_item']: row['offer_qty']}, -1)
            inventory(giver, {row['offer_item']: row['offer_qty']})
        else:
            upgrade(giver)['good_deeds'] += 1
            giver['stats']['helps'] += 1
            thanks = upgrade(giver).setdefault('thanks', [])
            thanks.insert(0, dict(at=now, text='Спасибо от соседа за посылку!'))
            del thanks[20:]
    await persist_transition(unit, row, farms, before, status, actor, now)


async def expire(unit, farm_id, now):
    if not available(unit):
        return
    ids = farm_id if isinstance(farm_id, (list, tuple, set)) else [farm_id]
    t = unit.t['requests']; uids = [UUID(str(fid)) for fid in ids]
    rows = (await unit.execute(sa.select(t.c.id).where(sa.or_(t.c.requester_farm.in_(uids), t.c.giver_farm.in_(uids)),
        sa.or_(sa.and_(t.c.status == 'open', t.c.expires_at <= now),
               sa.and_(t.c.status == 'delivered', t.c.settle_by <= now))).order_by(t.c.id))).all()
    if not rows:
        # Read paths (open/visit) run this before their own sorted farm locks: with nothing to expire
        # it must take no lock at all, or it would pre-empt the caller's lock schedule.
        return
    # Lock the union once: multiple expiries in one transaction cannot invert farm lock order.
    ids = {str(fid) for fid in ids}
    for (rid,) in rows:
        raw = (await unit.execute(sa.select(t.c.requester_farm, t.c.giver_farm).where(t.c.id == rid))).first()
        if raw:
            ids.update(str(fid) for fid in raw if fid is not None)
    await unit.lock(*('farm:' + fid for fid in sorted(ids)))
    for (rid,) in rows:
        row, farms = await locked_row(unit, rid, prelocked=ids)
        status = ('expired' if row['status'] == 'open' and row['expires_at'] <= now else
                  'returned' if row['status'] == 'delivered' and row['settle_by'] <= now else None)
        if status:
            await transition(unit, row, farms, status, str(row['requester_account']), now)


async def projection(unit, farm, now):
    if not available(unit):
        return dict(incoming=[], own=[], good_deeds=0, limits=dict(count_left=0, value_left=0, value_limit=0), neighbors=[])
    t = unit.t['requests']; uid = UUID(farm['id']); state = upgrade(farm)
    peers = {}
    for fid, edge in farm['neighbors'].items():
        if edge.get('status') == 'accepted':
            other = await unit.get(fid)
            if mutual(farm, other):
                peers[fid] = other
    rows = (await unit.execute(sa.select(t).where(sa.or_(t.c.requester_farm == uid, t.c.giver_farm == uid,
        sa.and_(t.c.status == 'open', t.c.requester_farm.in_([UUID(fid) for fid in peers]),
                sa.or_(t.c.audience_farm.is_(None), t.c.audience_farm == uid))))
        .order_by(t.c.status.in_(['open', 'delivered']).desc(), t.c.created_at.desc(), t.c.id).limit(500))).mappings().all()
    own, incoming = [], []
    before = deepcopy(farm)
    digest_row = None
    digest_items = []
    for raw in rows:
        row = dict(raw)
        if row['status'] == 'open' and row['expires_at'] <= now:
            continue
        # Players see farms, never account ids; whom a request was aimed at stays with its author.
        data = {k: str(v) if isinstance(v, UUID) else v for k, v in row.items()
                if not k.endswith('_account') and (k != 'audience_farm' or row['requester_farm'] == uid)}
        requester = farm if row['requester_farm'] == uid else peers.get(str(row['requester_farm']))
        giver = farm if row['giver_farm'] == uid else (await unit.get(str(row['giver_farm'])) if row['giver_farm'] else None)
        data.update(requester_name='Сосед', giver_name='Сосед', can_give=False, reason=None, can_accept=False, accept_reason=None,
                    expiring=bool(row['status'] == 'delivered' and row['settle_by'] - now <= 12 * 3600))
        if row['requester_farm'] == uid:
            own.append(data)
            if row['status'] == 'delivered':
                data['can_accept'] = row['settle_by'] > now
                if not data['can_accept']:
                    data['accept_reason'] = 'Срок принятия посылки истёк.'
                elif row['offer_kind'] == 'coins' and farm['coins'] - farm['starter_credit'] < row['offer_coins']:
                    data.update(can_accept=False, accept_reason='Не хватает заработанных монет.')
                elif row['offer_kind'] == 'item' and farm['inventory'].get(row['offer_item'], 0) < row['offer_qty']:
                    data.update(can_accept=False, accept_reason='Не хватает встречного товара.')
                incoming.append(data)
                if data['expiring']:
                    await notify(unit, farm, row, 'reminder', now, 'Ёж ждёт: прими посылку в течение 12 часов.')
        elif row['status'] == 'open' and str(row['id']) not in state['hidden'] and farm['settings'].get('allow_requests', True) and requester:
            try:
                await delivery_check(unit, row, requester, farm, now)
                data['can_give'] = True
            except FarmError as error:
                data['reason'] = error.message
            incoming.append(data)
            digest_row = row
            digest_items.append(ITEMS[row['item']]['name'])
            if str(row['id']) not in state['seen']:
                state['seen'] = [*state['seen'], str(row['id'])][-100:]
                event(farm, now, f"Сосед просит: {ITEMS[row['item']]['name']} ×{row['qty']}.", 'social')
    if digest_row:
        await notify(unit, farm, digest_row, 'digest', now, 'Соседи просят: ' + ', '.join(dict.fromkeys(digest_items)) + '.')
    if farm != before:
        farm['revision'] += 1
        await unit.save(farm)
        await unit.record(await unit.owner_account(farm['id']), 'request-inbox:' + str(farm['revision']), 'request_inbox', before, farm, now)
    return dict(incoming=incoming, own=own, good_deeds=state['good_deeds'], thanks=deepcopy(state.get('thanks', [])), limits=await limits(unit, farm, now),
                neighbors=[dict(id=fid, name='Сосед') for fid in peers])


async def create(unit, farm, account, data, now):
    allowed = {'item', 'qty', 'offer_kind', 'offer_item', 'offer_qty', 'offer_coins', 'to'}
    need(isinstance(data, dict) and {'item', 'qty', 'offer_kind'} <= set(data) <= allowed,
         'invalid_command', 'Некорректная записка.', 422)
    item = named(ITEMS, data['item']); qty = number(data['qty'], 1, 20); unbound([item['id']])
    kind = data['offer_kind']; need(kind in {'free', 'coins', 'item'}, 'invalid_command', 'Некорректный обмен.', 422)
    unlocked(farm, kind == 'coins')
    value = item['price'] * qty
    need(value > 0, 'invalid_command', 'Этот товар нельзя просить.', 422)
    terms = dict(offer_item=None, offer_qty=None, offer_coins=None)
    if kind == 'coins':
        coins = number(data.get('offer_coins'), 1, 10**12)
        need(value <= coins * 2 <= value * 3, 'request_offer_value', 'Предложи от половины до полутора стоимостей товара.')
        terms['offer_coins'] = coins
    elif kind == 'item':
        offered = named(ITEMS, data.get('offer_item')); amount = number(data.get('offer_qty'), 1, 1000000)
        unbound([offered['id']]); other_value = offered['price'] * amount
        need(value <= other_value * 2 <= value * 3, 'request_offer_value', 'Стоимость обмена должна быть от 0,5 до 1,5 стоимости просьбы.')
        need(farm['inventory'].get(offered['id'], 0) >= amount, 'missing_goods', 'Встречного товара пока нет на складе.')
        terms.update(offer_item=offered['id'], offer_qty=amount)
    lim = await limits(unit, farm, now)
    need(lim['count_left'] > 0, 'request_daily_limit', 'Можно отправить три просьбы в сутки.', 429)
    need(lim['open_left'] > 0, 'request_open_limit', 'Сначала закрой одну из трёх открытых просьб.')
    need(value <= lim['value_left'], 'request_value_limit', 'Дневной лимит стоимости просьб исчерпан.')
    audience = data.get('to')
    if audience:
        try:
            audience = str(UUID(audience))
        except (ValueError, TypeError, AttributeError):
            raise FarmError('invalid_command', 'Некорректный сосед.', 422)
        need(mutual(farm, await unit.get(audience)), 'not_neighbor', 'Выбери взаимного соседа.', 403)
    row = dict(id=uuid4(), requester_farm=UUID(farm['id']), requester_account=UUID(account),
        audience_farm=UUID(audience) if audience else None, item=item['id'], qty=qty, offer_kind=kind,
        **terms, value=value, status='open', created_at=now, expires_at=now + OPEN_SECONDS)
    await unit.execute(unit.t['requests'].insert().values(**row))
    before = {farm['id']: deepcopy(farm)}
    await persist_transition(unit, row, {farm['id']: farm}, before, 'open', account, now)
    return row


async def command(service, key, kind, data, target_id):
    unit, account, now = service.u, service.p.account_id, service.clock()
    need(available(unit), 'request_unavailable', 'Просьбы временно недоступны.', 503)
    me = await service.me()
    need(target_id == me['id'], 'not_owner', 'Это не твоя ферма.', 403)
    if kind == 'request_create':
        recipients = {fid for fid, edge in me['neighbors'].items() if edge.get('status') == 'accepted'}
        await unit.lock(*('farm:' + fid for fid in sorted({me['id'], *recipients})))
        me = await unit.get(me['id']); upgrade(me)
        row = await create(unit, me, account, data, now)
        await announce_created(unit, me, row, recipients, account, now)
        notice = 'Ёж отнёс записку соседям.'
    else:
        need(isinstance(data, dict) and set(data) == {'request'}, 'invalid_command', 'Некорректная просьба.', 422)
        try:
            rid = UUID(data['request'])
        except (ValueError, TypeError, AttributeError):
            raise FarmError('invalid_command', 'Некорректная просьба.', 422)
        row, farms = await locked_row(unit, rid, me['id'])
        me = farms[me['id']]
        requester = farms[str(row['requester_farm'])]
        if kind in {'request_accept', 'request_decline', 'request_cancel'}:
            need(requester['id'] == me['id'], 'not_owner', 'Это не твоя просьба.', 403)
        if kind == 'request_hide':
            need(row['status'] == 'open' and mutual(requester, me) and
                 (row['audience_farm'] is None or str(row['audience_farm']) == me['id']),
                 'request_not_found', 'Просьба недоступна.', 404)
            state = upgrade(me)
            state['hidden'] = list(dict.fromkeys([*state['hidden'], str(rid)]))[-100:]
            me['revision'] += 1; await unit.save(me)
            notice = 'Просьба скрыта.'
        elif kind == 'request_give':
            need(row['status'] == 'open', 'request_closed', 'Уже отнесли — спасибо!')
            need(row['expires_at'] > now, 'request_expired', 'Срок просьбы истёк.')
            await delivery_check(unit, row, requester, me, now)
            await transition(unit, row, farms, 'delivered', account, now)
            notice = 'Ёж понёс посылку.'
        elif kind == 'request_cancel':
            need(row['status'] == 'open', 'request_closed', 'Просьба уже закрыта.')
            await transition(unit, row, farms, 'cancelled', account, now)
            notice = 'Просьба отменена.'
        else:
            need(row['status'] == 'delivered', 'request_closed', 'Просьба уже закрыта.')
            need(row['settle_by'] > now, 'request_expired', 'Срок принятия посылки истёк.')
            await transition(unit, row, farms, 'settled' if kind == 'request_accept' else 'returned', account, now)
            notice = 'Посылка принята. Спасибо соседу!' if kind == 'request_accept' else 'Ёж вернул посылку.'
    return dict(command_id=key, request=str(row['id']), notice=notice, server_time=now, revision=me['revision'])


async def break_pair(unit, a, b, actor, now):
    if not available(unit):
        return
    t = unit.t['requests']; aa, bb = UUID(a['id']), UUID(b['id'])
    rows = (await unit.execute(sa.select(t).where(t.c.status == 'open', sa.or_(
        sa.and_(t.c.requester_farm == aa, t.c.audience_farm == bb),
        sa.and_(t.c.requester_farm == bb, t.c.audience_farm == aa))).with_for_update())).mappings().all()
    for row in rows:
        # Pair farms are already locked by the ordinary remove/block command.
        await transition(unit, dict(row), {str(row['requester_farm']): a if str(row['requester_farm']) == a['id'] else b},
                         'cancelled', actor, now)


async def merge_participants(unit, farm_ids):
    """Find all affected escrow participants before the merge takes any farm lock."""
    if not available(unit) or not farm_ids:
        return set(farm_ids)
    t = unit.t['requests']; ids = [UUID(fid) for fid in farm_ids]
    rows = (await unit.execute(sa.select(t.c.requester_farm, t.c.giver_farm, t.c.audience_farm).where(
        sa.or_(t.c.requester_farm.in_(ids), t.c.giver_farm.in_(ids), t.c.audience_farm.in_(ids)),
        t.c.status.in_(['open', 'delivered'])))).all()
    return {*(farm_ids), *(str(fid) for row in rows for fid in row if fid is not None)}


async def merge_close(unit, main_account, secondary_account, now):
    if not available(unit):
        return
    t = unit.t['requests']; main, secondary = UUID(str(main_account)), UUID(str(secondary_account))
    secondary_farm = await unit.by_account(secondary_account)
    audience = UUID(secondary_farm['id']) if secondary_farm else None
    rows = (await unit.execute(sa.select(t).where(sa.or_(t.c.requester_account == secondary,
        t.c.giver_account == secondary, t.c.audience_farm == audience if audience else sa.false()),
        t.c.status.in_(['open', 'delivered'])).order_by(t.c.id).with_for_update())).mappings().all()
    for raw in rows:
        row = dict(raw)
        ids = {str(row['requester_farm'])}
        if row['giver_farm']:
            ids.add(str(row['giver_farm']))
        farms = {fid: await unit.get(fid) for fid in ids}
        need(all(farms.values()), 'merge_request_unsettled', 'Сначала закрой посылки соседей.')
        locked = getattr(unit, 'friend_request_merge_farms', None)
        need(locked is None or ids <= locked, 'merge_request_unsettled', 'Состояние посылок изменилось. Повтори объединение.')
        await transition(unit, row, farms, 'returned' if row['status'] == 'delivered' else 'cancelled', str(main), now)
    await unit.execute(t.update().where(t.c.requester_account == secondary).values(requester_account=main))
    await unit.execute(t.update().where(t.c.giver_account == secondary).values(giver_account=main))
