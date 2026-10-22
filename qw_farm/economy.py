"""r9 stage 14: farm upkeep (a coin sink from L10) and the two-part village fund (personal season scale + shared counter).

State lives in ``farm['economy']`` (``setdefault`` only, ``schema_version`` is not raised). Everything here is pure: the shared
village counter is a PostgreSQL row owned by the service (``Unit.village_add``); this module only decides what a contribution is
worth and what the player has earned. XP is never written here (the only funnel is ``progression.grant_xp``).

Upkeep. One bill per Moscow day on which the owner successfully issued a command (never for ``rescue`` / ``pay_upkeep``). The
bill is ``min(U, coins - starter_credit)`` taken directly from the balance (not through ``domain.pay``, which would eat the starter
credit); the unpaid rest is ``debt`` and the next bill REPLACES it (debt never piles up). While ``debt > 0`` every timer the
player starts takes 1.2x as long (``domain.duration(..., farm)``); running timers never change. Items never disappear.

Fund. Season = 28 Moscow days (calendar-aligned). A contribution (earned coins 1:1 or goods at price x1.25) goes into the
personal season scale AND into the village counter. Personal tiers pay rewards immediately. When the village counter reaches
the season goal, every farm that put in at least ``MIN_SHARE_PCT`` of its reference income gets the common reward lazily, on its
next visit (``claim_village``): no background workers.
"""
from .catalog import (BUILDINGS, ITEMS, level, income_ref, plot_upkeep, UPKEEP_PCT, FIELD_UPKEEP, UPKEEP_LEVEL, FUND_LEVEL,
                      SEASON_DAYS, FUND_TIERS, FUND_MARKUP, MIN_SHARE_PCT, DEBT_SLOW, DEBT_SLOW_DEN, FEAST_DAYS, FEAST_PCT,
                      DECOR_SHOP, DECOR_EXTRA, REWARD_DECOR, TIER_DISCOUNT_PCT, MAX_CONTRIBUTION, FUND_REWARD_TEXT)

TZ_OFFSET = 10800
DAY = 86400
KEEP_SEASONS = 2
TIER_REWARD = {1: 'garland', 2: 'feast', 3: 'discount', 4: 'pinwheel', 5: 'cup'}
TIER_TEXT = FUND_REWARD_TEXT
TITLE = 'Староста деревни'
REWARD_BY_TIER = {1: 'fd_garland', 4: 'fd_pinwheel', 5: 'fd_cup'}
COMMON_DECOR = 'fd_banner'
DECOR_IDS = frozenset(d['id'] for d in [*DECOR_SHOP, *DECOR_EXTRA])


def blank():
    return dict(billed_day=-1, debt=0, seasons={}, unlocked=[], titles=[], feast_until=0,
                stats=dict(upkeep_billed=0, upkeep_paid=0, fund_coins=0, fund_goods=0, fund_village=0, decor=0, feast_xp=0))


def state(farm):
    e = farm.setdefault('economy', blank())
    for key, value in blank().items():
        e.setdefault(key, value)
    for key, value in blank()['stats'].items():
        e['stats'].setdefault(key, value)
    return e


def moscow_day(at):
    return int((at + TZ_OFFSET) // DAY)


def season_of(at):
    return moscow_day(at) // SEASON_DAYS


def season_end(season):
    """First instant after the season (unix time)."""
    return (season + 1) * SEASON_DAYS * DAY - TZ_OFFSET


def thresholds(ref):
    return [ref * m // 10 for m in FUND_TIERS]


def min_share(ref):
    return max(1, ref * MIN_SHARE_PCT // 100)


# ---------------------------------------------------------------- upkeep
def base_upkeep(farm):
    """Daily bill U before any discount: beds by land size + 1% of the price x level of every non-decor building + fields."""
    size = farm['size']
    per_plot = plot_upkeep(size)
    total = 0
    for obj in farm['objects']:
        if obj['type'] in ('plot', 'tree'):   # a tree stands on land like a bed: «земля под деревом»
            total += per_plot
            continue
        spec = BUILDINGS.get(obj['type'])
        if spec and not spec.get('decor'):
            lvl = obj.get('level', 1)
            total += -(-spec['cost'] * (lvl if type(lvl) is int and lvl >= 1 else 1) // UPKEEP_PCT)
    total += FIELD_UPKEEP * sum(f.get('ha', 0) for f in farm.get('fields', []) if isinstance(f, dict))
    return total


def discount_active(farm, at):
    rec = state(farm)['seasons'].get(str(season_of(at)))
    return bool(rec and rec['tiers'] >= 3)


def upkeep(farm, at):
    u = base_upkeep(farm)
    return u * (100 - TIER_DISCOUNT_PCT) // 100 if discount_active(farm, at) else u


def slowed(farm):
    """True while unpaid debt makes new timers slower."""
    return state(farm)['debt'] > 0


def stretch(seconds, farm):
    """Timer length for a timer the player starts now (1.2x with debt), as a float for ``domain.duration``."""
    if farm is not None and farm.get('economy', {}).get('debt', 0) > 0:
        return seconds * DEBT_SLOW / DEBT_SLOW_DEN
    return seconds


def bill(farm, at):
    """Charge today's bill once per Moscow day (L10+). Returns the coins paid (0 when nothing was charged)."""
    e = state(farm)
    day = moscow_day(at)
    if level(farm['xp']) < UPKEEP_LEVEL or e['billed_day'] >= day:
        return 0
    first = e['billed_day'] < 0
    e['billed_day'] = day
    if first:
        e['debt'] = 0            # the day the farm becomes liable is a free grace day
        return 0
    due = upkeep(farm, at)
    paid = min(due, max(0, farm['coins'] - farm['starter_credit']))
    farm['coins'] -= paid
    e['debt'] = due - paid
    e['stats']['upkeep_billed'] += due
    e['stats']['upkeep_paid'] += paid
    return paid


def pay_debt(farm):
    from .domain import need
    e = state(farm)
    need(e['debt'] > 0, 'no_debt', 'Долга по содержанию нет.')
    paid = min(e['debt'], max(0, farm['coins'] - farm['starter_credit']))
    need(paid > 0, 'insufficient_coins', 'Нет заработанных монет, чтобы погасить долг. Продай урожай или выполни заказ.')
    farm['coins'] -= paid
    e['debt'] -= paid
    e['stats']['upkeep_paid'] += paid
    return paid


# ---------------------------------------------------------------- fund
def record(farm, season, lv):
    e = state(farm)
    key = str(season)
    rec = e['seasons'].get(key)
    if rec is None:
        rec = e['seasons'][key] = dict(level=lv, ref=income_ref(lv), personal=0, tiers=0, joined=False, common=False)
        for old in sorted(e['seasons'], key=int)[:-KEEP_SEASONS]:
            del e['seasons'][old]
    return rec


def goods_value(items):
    return sum(ITEMS[k].get('fund_price', ITEMS[k]['price']) * q * FUND_MARKUP // 100 for k, q in items.items())


def _unlock(farm, decor_id):
    e = state(farm)
    if decor_id not in e['unlocked']:
        e['unlocked'].append(decor_id)


def _grant_feast(farm, at):
    e = state(farm)
    e['feast_until'] = max(e['feast_until'], int(at) + FEAST_DAYS * DAY)


def contribute(farm, coins, items, at):
    """Validate and book one contribution; returns (value, notice). The caller (domain) already checked the schema."""
    from .domain import need, inventory, unbound
    lv = level(farm['xp'])
    need(lv >= FUND_LEVEL, 'locked', f'Фонд деревни открывается с {FUND_LEVEL} уровня.')
    need(type(coins) is int and coins >= 0 and isinstance(items, dict) and len(items) <= 12, 'invalid_command', 'Некорректный вклад.', 422)
    need(coins <= max(0, farm['coins'] - farm['starter_credit']), 'earned_coins',
         'В фонд идут только заработанные монеты, не стартовый подарок.')
    if items:
        unbound([k for k in items if isinstance(k, str)])
        inventory(farm, items, -1)           # validates ids, quantities and stock before anything is spent
    value = coins + goods_value(items)
    need(value > 0, 'invalid_command', 'Добавь монеты или товары.', 422)
    need(value <= MAX_CONTRIBUTION, 'invalid_command', 'Слишком большой вклад за один раз.', 422)
    farm['coins'] -= coins
    e = state(farm)
    season = season_of(at)
    rec = record(farm, season, lv)
    first = not rec['joined']
    rec['joined'] = True
    rec['personal'] += value
    e['stats']['fund_coins'] += coins
    e['stats']['fund_goods'] += value - coins
    e['stats']['fund_village'] += value
    got = []
    ths = thresholds(rec['ref'])
    while rec['tiers'] < len(ths) and rec['personal'] >= ths[rec['tiers']]:
        rec['tiers'] += 1
        tier = rec['tiers']
        kind = TIER_REWARD[tier]
        if kind == 'feast':
            _grant_feast(farm, at)
        elif kind == 'cup':
            _unlock(farm, REWARD_BY_TIER[tier])
            if TITLE not in e['titles']:
                e['titles'].append(TITLE)
        elif kind in ('garland', 'pinwheel'):
            _unlock(farm, REWARD_BY_TIER[tier])
        got.append(TIER_TEXT[tier])
    text = f'В фонд деревни внесено: {value}.'
    if got:
        text += ' Награда: ' + '; '.join(got) + '.'
    return value, text, first


def goal_share(ref):
    """What a participating farm adds to the village goal (3 reference days of income)."""
    return 3 * ref


# ---------------------------------------------------------------- lazy village reward
def claimable_seasons(farm):
    """Seasons whose common reward may be due: contributed at least the minimum share and not yet paid."""
    out = []
    for key, rec in state(farm)['seasons'].items():
        if rec['joined'] and not rec['common'] and rec['personal'] >= min_share(rec['ref']):
            out.append(int(key))
    return sorted(out)


def claim_village(farm, season, reached, at):
    """Pay the common reward of ``season`` if the village counter reached its goal. Returns True when paid."""
    rec = state(farm)['seasons'].get(str(season))
    if not reached or rec is None or rec['common'] or not rec['joined'] or rec['personal'] < min_share(rec['ref']):
        return False
    rec['common'] = True
    _unlock(farm, COMMON_DECOR)
    _grant_feast(farm, at)
    from .domain import event
    event(farm, at, 'Деревня выполнила цель сезона! Общий праздник: +10% опыта на 3 дня и знамя деревни.', 'village')
    return True


# ---------------------------------------------------------------- decor
def reward_allowed(farm, typ):
    return typ in state(farm)['unlocked']


def note_decor_spend(farm, typ, cost):
    if typ in DECOR_IDS and cost > 0:
        state(farm)['stats']['decor'] += cost


# ---------------------------------------------------------------- projection / validation
def status(farm, at):
    """Read-only owner view for the client (does not mutate the farm)."""
    e = {**blank(), **(farm.get('economy') or {})}
    lv = level(farm['xp'])
    season = season_of(at)
    rec = (e.get('seasons') or {}).get(str(season))
    ref = rec['ref'] if rec else income_ref(max(lv, FUND_LEVEL))
    return dict(
        active=lv >= UPKEEP_LEVEL, fund_open=lv >= FUND_LEVEL,
        upkeep=upkeep(farm, at) if lv >= UPKEEP_LEVEL else 0, base_upkeep=base_upkeep(farm),
        discount=discount_active(farm, at), debt=e['debt'], slow=e['debt'] > 0, billed_today=e['billed_day'] >= moscow_day(at),
        season=season, season_ends_at=season_end(season), ref=ref, thresholds=thresholds(ref),
        personal=rec['personal'] if rec else 0, tiers=rec['tiers'] if rec else 0, joined=bool(rec and rec['joined']),
        min_share=min_share(ref), common=bool(rec and rec['common']),
        feast_until=e['feast_until'], unlocked=list(e['unlocked']), titles=list(e['titles']),
        pending_common=[s for s in claimable_seasons(farm)] if farm.get('economy') else [],
        stats=dict(e['stats']))


def validate(farm):
    from .domain import need
    e = farm.get('economy')
    if e is None:
        return
    ok = (isinstance(e, dict) and type(e.get('debt')) is int and e['debt'] >= 0 and type(e.get('billed_day')) is int
          and type(e.get('feast_until')) is int and e['feast_until'] >= 0 and isinstance(e.get('seasons'), dict)
          and len(e['seasons']) <= KEEP_SEASONS + 1 and set(e.get('unlocked', [])) <= {d['id'] for d in REWARD_DECOR}
          and isinstance(e.get('stats'), dict) and all(type(v) is int and v >= 0 for v in e['stats'].values()))
    if ok:
        for rec in e['seasons'].values():
            ok = ok and isinstance(rec, dict) and all(type(rec.get(k)) is int and rec[k] >= 0 for k in ('level', 'ref', 'personal', 'tiers')) \
                and rec['tiers'] <= len(FUND_TIERS) and isinstance(rec.get('joined'), bool) and isinstance(rec.get('common'), bool)
    need(ok, 'invalid_state', 'Некорректное состояние экономики.', 500)
