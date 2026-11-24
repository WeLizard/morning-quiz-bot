"""Explicit server grants and one-time farm claims."""
from copy import deepcopy
from hashlib import sha256
import re

from .catalog import BUILDINGS, ITEMS, tick
from .domain import inventory_after, need

KEY = 'farm_rewards'
SCHEMAS = {'claim_farm_reward': {'reward'}}
TITLE_LIMIT = 80
MESSAGE_LIMIT = 500
MAX_COINS = 10**12
MAX_ITEM_STOCK = 10**9
MAX_ITEM_GRANT = 10**6
ID_PATTERN = re.compile(r'[a-zA-Z0-9_:-]{1,64}')
ALLOWED_DECOR = frozenset(key for key, spec in BUILDINGS.items()
                          if spec.get('decor') and not any(spec.get(flag) for flag in ('ground', 'secret', 'curio')))
ALLOWED_ITEMS = frozenset(key for key, spec in ITEMS.items() if not spec.get('bound'))
FIELDS = {'title', 'message', 'coins', 'items', 'decor', 'created_at', 'claimed_at', 'used_decor'}


def _valid_id(reward_id):
    return type(reward_id) is str and ID_PATTERN.fullmatch(reward_id) is not None


def _valid_text(text, limit):
    return type(text) is str and 0 < len(text) <= limit and text == text.strip() and text.isprintable()


def _valid_contents(title, message, coins, items, decor):
    return (_valid_text(title, TITLE_LIMIT) and (message is None or _valid_text(message, MESSAGE_LIMIT))
            and type(coins) is int and 0 <= coins <= MAX_COINS
            and type(items) is dict and all(k in ALLOWED_ITEMS and type(q) is int and 0 < q <= MAX_ITEM_GRANT
                                            for k, q in items.items())
            and type(decor) is list and all(type(k) is str and k in ALLOWED_DECOR for k in decor)
            and len(set(decor)) == len(decor) and bool(coins or items or decor))


def enqueue(farm, reward_id, now, *, title, message=None, coins=0, items=None, decor=None):
    """Append a trusted grant while the caller holds the farm transaction lock."""
    items = {} if items is None else items
    decor = [] if decor is None else decor
    need(_valid_id(reward_id) and _valid_contents(title, message, coins, items, decor),
         'invalid_farm_reward', 'Некорректная награда фермы.', 422)
    stamp = tick(now)
    need(stamp >= 0, 'invalid_farm_reward', 'Некорректная дата награды фермы.', 422)
    payload = dict(title=title, message=message, coins=coins, items=dict(items), decor=sorted(decor))
    previous = farm.get(KEY, {}).get(reward_id)
    if previous is not None:
        need(all(previous[k] == v for k, v in payload.items()), 'farm_reward_key_reused',
             'Этот номер уже используется другой наградой.')
        return False
    farm.setdefault(KEY, {})[reward_id] = dict(payload, created_at=stamp, claimed_at=None, used_decor=[])
    return True


async def enqueue_for(unit, account_id, reward_id, now, **reward):
    """Store a trusted grant on an existing active farm within the caller's transaction."""
    from .domain import validate_state

    await unit.lock('account:' + str(account_id))
    target = await unit.by_account(account_id)
    need(target is not None, 'not_found', 'Ферма не найдена.', 404)
    await unit.lock('farm:' + target['id'])
    farm = await unit.get(target['id'])
    need(farm is not None, 'not_found', 'Ферма не найдена.', 404)
    before = deepcopy(farm)
    created = enqueue(farm, reward_id, now, **reward)
    if created:
        farm['revision'] += 1
        validate_state(farm)
        await unit.save(farm)
        # A slash keeps the system ledger key outside the client command ID namespace.
        key = 'reward-queued/' + sha256(reward_id.encode()).hexdigest()[:48]
        await unit.record(account_id, key, 'farm_reward_queued', before, farm, tick(now))
    return created


def claim(farm, reward_id, now):
    need(_valid_id(reward_id), 'invalid_command', 'Некорректный номер награды.', 422)
    reward = farm.get(KEY, {}).get(reward_id)
    need(reward is not None, 'farm_reward_not_found', 'Награда не найдена.', 404)
    need(reward['claimed_at'] is None, 'farm_reward_claimed', 'Эту награду уже забрали.')
    need(farm['coins'] + reward['coins'] <= MAX_COINS, 'balance_full', 'На счёте нет места для награды.')
    stock = inventory_after(farm, reward['items'])
    need(all(q <= MAX_ITEM_STOCK for q in stock.values()), 'inventory_full', 'На складе нет места для награды.')
    farm['inventory'].update(stock)
    farm['coins'] += reward['coins']
    reward['claimed_at'] = max(now, reward['created_at'])
    return 'Награда получена.'


def pending(farm):
    rewards = farm.get(KEY, {})
    return [dict(id=reward_id, title=r['title'], message=r['message'], created_at=r['created_at'],
                 coins=r['coins'], items=dict(r['items']), decor=list(r['decor']))
            for reward_id, r in sorted(rewards.items(), key=lambda entry: (entry[1]['created_at'], entry[0]))
            if r['claimed_at'] is None]


def decor_credits(farm):
    available = {}
    for r in farm.get(KEY, {}).values():
        if r['claimed_at'] is not None:
            for kind in r['decor']:
                if kind not in r['used_decor']:
                    available[kind] = available.get(kind, 0) + 1
    return available


def take_decor(farm, kind):
    """Consume one gift placement after the build's other checks have succeeded."""
    eligible = ((reward_id, r) for reward_id, r in farm.get(KEY, {}).items()
                if r['claimed_at'] is not None and kind in r['decor'] and kind not in r['used_decor'])
    selected = min(eligible, key=lambda entry: (entry[1]['created_at'], entry[0]), default=None)
    if selected is not None:
        selected[1]['used_decor'].append(kind)


def merge(main, secondary):
    """Union grants by stable ID, retaining claims and used placements on either farm."""
    other = secondary.get(KEY)
    if not other:
        return
    result = deepcopy(main.get(KEY, {}))
    for reward_id, incoming in other.items():
        existing = result.get(reward_id)
        if existing is None:
            result[reward_id] = deepcopy(incoming)
            continue
        contents = ('title', 'message', 'coins', 'items', 'decor')
        need(all(existing[k] == incoming[k] for k in contents), 'farm_reward_key_reused',
             'Награды ферм с одинаковым номером различаются.')
        existing['created_at'] = min(existing['created_at'], incoming['created_at'])
        claims = [stamp for stamp in (existing['claimed_at'], incoming['claimed_at']) if stamp is not None]
        existing['claimed_at'] = min(claims, default=None)
        existing['used_decor'] = sorted(set(existing['used_decor']) | set(incoming['used_decor']))
    main[KEY] = result


def validate(farm):
    if KEY not in farm:
        return

    def valid(condition):
        need(condition, 'invalid_farm_rewards', 'Некорректное состояние наград фермы.', 500)

    rewards = farm[KEY]
    valid(type(rewards) is dict)
    for reward_id, r in rewards.items():
        valid(_valid_id(reward_id) and type(r) is dict and set(r) == FIELDS)
        valid(_valid_contents(r['title'], r['message'], r['coins'], r['items'], r['decor']))
        created, claimed, used = r['created_at'], r['claimed_at'], r['used_decor']
        valid(type(created) is int and created >= 0 and
              (claimed is None or type(claimed) is int and claimed >= created))
        valid(type(used) is list and all(type(k) is str and k in r['decor'] for k in used)
              and len(set(used)) == len(used) and (claimed is not None or not used))
