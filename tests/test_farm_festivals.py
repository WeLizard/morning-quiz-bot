"""Festivals engine and the pilot «Посиделки»: calendar, windows and overlaps, fair tasks and purchases, privacy, replay."""
import asyncio
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from qw_farm import economy, festivals as F
from qw_farm.catalog import LEVELS, income_ref
from qw_farm.domain import FarmError, apply, new_farm, project, validate_state
from qw_farm.expansion import upgrade_state
from qw_farm.service import FarmService, Principal
from tests.test_farm_platform import farm_pg_url  # noqa: F401  (fixture: skips without TEST_DATABASE_URL)

MSK = timezone(timedelta(hours=3))


def ts(y, m, d, h=12, minute=0, second=0):
    return int(datetime(y, m, d, h, minute, second, tzinfo=MSK).timestamp())


FAIR = ts(2026, 11, 26)          # first fair day of the pilot, Moscow noon
FAIR2 = ts(2026, 11, 27)
AFTER = ts(2026, 12, 5)


def orthodox_easter(year):
    """Julian (Meeus) Easter converted to the Gregorian calendar: independent of the table under test."""
    a, b, c = year % 4, year % 7, year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month, day = divmod(d + e + 114, 31)
    return date(year, month, day + 1) + timedelta(days=13)


def farm(coins=10 ** 6, xp=LEVELS[29], inv=None, at=FAIR):
    f = upgrade_state(new_farm(str(uuid4()), 'Fest', at))
    f.update(xp=xp, coins=coins, starter_credit=0, inventory=dict(inv or {}))
    f['progress'].update(day=10 ** 9, dew=10 ** 9)
    economy.state(f)['billed_day'] = 10 ** 9      # no upkeep bill in the middle of the arithmetic
    return f


def cmd(f, kind, data, at=FAIR, key=None):
    return apply(f, f, kind, data, at, key or f'{kind}-{at}-{len(f["events"])}')


def code(f, kind, data, at=FAIR):
    before = deepcopy(f)
    with pytest.raises(FarmError) as error:
        cmd(f, kind, data, at)
    assert f == before, 'a refused command leaves the farm untouched'
    return error.value.code


def task(tid, option=0, fest='posidelki'):
    return {'festival': fest, 'task': tid, 'option': option}


def buy(item, fest='posidelki'):
    return {'festival': fest, 'item': item}


# ---- calendar ----------------------------------------------------------------------------------------------------------------
def test_movable_tables_match_the_easter_arithmetic_and_the_design_table():
    doc = {2027: ((3, 8), (3, 14)), 2028: ((2, 21), (2, 27)), 2029: ((2, 12), (2, 18)), 2030: ((3, 4), (3, 10))}
    for year in range(2026, 2031):
        sunday = orthodox_easter(year) - timedelta(days=49)       # Forgiveness Sunday closes Масленица
        mon = sunday - timedelta(days=6)
        assert F.MOVING['maslenitsa'][year] == ((mon.month, mon.day), (sunday.month, sunday.day))
        july = date(year, 7, 1)
        second_sunday = july + timedelta(days=(6 - july.weekday()) % 7 + 7)
        fri = second_sunday - timedelta(days=2)
        assert F.MOVING['fisher_day'][year] == ((fri.month, fri.day), (second_sunday.month, second_sunday.day))
    for year, row in doc.items():
        assert F.MOVING['maslenitsa'][year] == row
    assert F.MOVING['fisher_day'][2027] == ((7, 9), (7, 11)) and F.MOVING['fisher_day'][2030] == ((7, 12), (7, 14))


def test_table_reaches_at_least_a_year_past_today():
    assert (F.TABLE_END - date.today()).days >= 365, 'extend FESTIVALS MOVING: the table is about to run out'
    for fid, rows in F.MOVING.items():
        assert max(rows) == F.TABLE_END.year


def test_every_fair_lies_inside_its_decoration_window_for_all_years():
    for year in range(2026, 2032):
        for o in F.occurrences(year):
            if o['id'] in F.MOVING and year not in F.MOVING[o['id']]:
                continue
            assert all(o['deco'][0] <= a <= b <= o['deco'][1] for a, b in o['fair']), o
            assert o['key'] == f'{o["id"]}-{year}'


def test_design_windows_for_fixed_festivals():
    def span(fid, year):
        o = next(o for o in F.occurrences(year) if o['id'] == fid)
        d = lambda n: date.fromordinal(n + F.EPOCH)
        return d(o['deco'][0]), d(o['deco'][1]), [(d(a), d(b)) for a, b in o['fair']]
    assert span('new_year', 2027) == (date(2026, 12, 20), date(2027, 1, 14), [(date(2026, 12, 30), date(2027, 1, 8))])
    assert span('posidelki', 2026) == (date(2026, 11, 20), date(2026, 11, 30), [(date(2026, 11, 26), date(2026, 11, 30))])
    assert span('pumpkin_night', 2027)[2] == [(date(2027, 10, 31), date(2027, 10, 31))]
    assert [a for a, _ in span('spas', 2027)[2]] == [date(2027, 8, 14), date(2027, 8, 19), date(2027, 8, 29)]
    assert span('maslenitsa', 2027) == (date(2027, 3, 8), date(2027, 3, 14), [(date(2027, 3, 8), date(2027, 3, 14))])
    assert span('fisher_day', 2028)[2] == [(date(2028, 7, 9), date(2028, 7, 9))]
    assert len(F.FESTIVALS) == 16 and F.birthday  # sixteen calendar festivals; the personal birthday is kept out of the table


def test_calendar_has_one_festival_per_day_and_the_documented_overlap_results():
    def who(y, m, d):
        c = F.current(ts(y, m, d))
        return c and (c['id'], c['phase'])
    assert who(2027, 3, 7) == ('spring_flowers', 'fair')
    assert who(2027, 3, 8) == ('spring_flowers', 'fair')          # 8 March beats the first day of Масленица
    assert who(2027, 3, 9) == ('maslenitsa', 'fair')
    assert who(2027, 3, 14) == ('maslenitsa', 'fair')             # the show evening is never lost
    assert [who(2030, 3, d)[0] for d in (4, 5, 6, 7, 8, 9, 10)] == ['maslenitsa'] * 2 + ['spring_flowers'] * 3 + ['maslenitsa'] * 2
    # 2029: Рыбака (06-08.07) covers Купала (05-08.07); the fair day decides (design 9.1, rule 4)
    assert [who(2029, 7, d) for d in (5, 6, 7, 8)] == [('kupala', 'decor'), ('kupala', 'fair'), ('kupala', 'fair'), ('fisher_day', 'fair')]
    assert [who(2028, 7, d) for d in (6, 7, 8, 9)] == [('kupala', 'fair'), ('kupala', 'fair'), ('kupala', 'decor'), ('fisher_day', 'fair')]
    assert who(2026, 12, 1) is None and who(2027, 6, 25) is None


def test_moscow_day_boundaries_not_utc_and_not_device_time():
    utc = lambda *a: int(datetime(*a, tzinfo=timezone.utc).timestamp())
    assert F.current(utc(2026, 11, 25, 20, 59, 59))['phase'] == 'decor'    # 23:59:59 Moscow on the 25th
    assert F.current(utc(2026, 11, 25, 21, 0, 0))['phase'] == 'fair'       # 00:00 Moscow on the 26th
    assert F.current(utc(2026, 11, 30, 20, 59, 59))['phase'] == 'fair'
    assert F.current(utc(2026, 11, 30, 21, 0, 0)) is None
    assert F.current(utc(2026, 11, 19, 20, 59, 59)) is None
    assert F.current(utc(2026, 11, 19, 21, 0, 0))['id'] == 'posidelki'
    c = F.current(FAIR)
    assert c['starts_at'] == ts(2026, 11, 20, 0) and c['ends_at'] == ts(2026, 12, 1, 0) and c['fair_ends_at'] == ts(2026, 12, 1, 0)


def test_per_day_cache_and_upcoming_preview():
    F._resolved.cache_clear()
    for _ in range(3):
        F.current(FAIR)
        F.current(FAIR + 3600)
    info = F._resolved.cache_info()
    assert info.hits >= 5
    soon = F.upcoming(ts(2026, 11, 10))
    assert soon['id'] == 'posidelki' and soon['days'] == 10 and soon['soon'] and soon['starts_at'] == ts(2026, 11, 20, 0)
    far = F.upcoming(ts(2026, 12, 2))
    assert far['id'] == 'new_year' and not far['soon']
    assert F.upcoming(ts(2026, 11, 22))['id'] == 'new_year'


def test_magpie_comes_on_the_first_fair_day_only_except_spas():
    assert F.current(FAIR)['magpie'] and not F.current(FAIR2)['magpie']
    assert all(F.current(ts(2027, 8, d))['magpie'] for d in (14, 19, 29))
    assert not F.current(ts(2027, 8, 20)) or not F.current(ts(2027, 8, 20))['magpie']
    assert not F.current(ts(2026, 11, 22))['magpie']


def test_birthday_needs_a_real_creation_date():
    f = farm()
    f['created_at'] = ts(2025, 11, 26)
    assert F.birthday(f, FAIR) == {'years': 1}
    assert F.birthday(f, FAIR2) is None and F.birthday(f, ts(2025, 11, 26)) is None
    del f['created_at']
    assert F.birthday(f, FAIR) is None
    f['created_at'] = ts(2024, 2, 29)
    assert F.birthday(f, ts(2025, 2, 28)) == {'years': 1}


# ---- content contract --------------------------------------------------------------------------------------------------------
def test_content_contract_and_pilot_shape():
    F.validate_content()
    c = F.CONTENT['posidelki']
    assert 3 <= len(c['tasks']) <= 5
    sold = [g for g in c['goods'] if g['source'] == 'fair']
    assert {g['kind'] for g in sold} >= {'decor_big', 'tree_decor', 'graft', 'voucher', 'mascot', 'curio'}
    assert all(g['bound'] and not g['wired'] for g in c['goods'])           # placeholders: nothing is wired to the scene yet
    assert any(g['seller'] == 'magpie' for g in sold) and any(g['seller'] == 'sonya' for g in sold)
    assert all(F.CONTENT[f] is None for f in F.FESTIVALS if f != 'posidelki')    # stubs: engine handles them, content is TODO
    for g in sold:
        assert F.price(g) == max(1, -(-g['k'] * income_ref(g['level']) // 100))
    big = next(g for g in sold if g['kind'] == 'decor_big')
    assert F.price(big) == 600 * income_ref(20) // 100


# ---- tasks -------------------------------------------------------------------------------------------------------------------
def test_task_takes_goods_gives_a_festival_item_and_never_coins_or_xp():
    f = farm(inv={'yarn': 5})
    coins, xp = f['coins'], f['xp']
    text = cmd(f, 'festival_task', task('yarn'))
    assert f['inventory']['yarn'] == 1 and 'Корзинка с пряжей' in text
    assert (f['coins'], f['xp']) == (coins, xp)
    assert f['festivals']['posidelki-2026']['rewards'] == {'fest_posid_basket': 1}
    assert code(f, 'festival_task', task('yarn')) == 'already_claimed'
    validate_state(f)


def test_task_alternative_option_and_missing_goods():
    f = farm(inv={'wool': 6})
    assert code(f, 'festival_task', task('yarn', 0)) == 'missing_goods'
    cmd(f, 'festival_task', task('yarn', 1))
    assert f['inventory']['wool'] == 0


@pytest.mark.parametrize('data', [task('yarn', 9), task('yarn', -1), task('yarn', True), task('yarn', '0')])
def test_task_rejects_bad_option(data):
    f = farm(inv={'yarn': 9})
    assert code(f, 'festival_task', data) == 'invalid_option'


def test_task_level_gate_closed_fair_and_unknown_ids():
    low = farm(xp=LEVELS[3], inv={'yarn': 9, 'pie': 9})
    assert code(low, 'festival_task', task('yarn')) == 'locked'
    cmd(low, 'festival_task', task('tea'))                                  # level 3 is enough for the pie task
    f = farm(inv={'yarn': 9})
    assert code(f, 'festival_task', task('yarn'), ts(2026, 11, 22)) == 'fair_closed'        # decoration only, fair not open yet
    assert code(f, 'festival_task', task('yarn'), ts(2026, 12, 2)) == 'fair_closed'
    assert code(f, 'festival_task', task('yarn', fest='new_year'), FAIR) == 'fair_closed'
    assert code(f, 'festival_task', task('yarn', fest='nope')) == 'unknown_festival'
    assert code(f, 'festival_task', task('ghost')) == 'unknown_task'


def test_finishing_every_task_gives_the_memorable_item_once_and_it_is_not_for_sale():
    f = farm(inv={'yarn': 4, 'mittens': 2, 'pillow': 2, 'pie': 3})
    texts = [cmd(f, 'festival_task', task(t)) for t in ('yarn', 'warm', 'pillows')]
    assert not f['festivals']['posidelki-2026']['keepsake'] and 'Носки года' not in ''.join(texts)
    last = cmd(f, 'festival_task', task('tea'))
    assert f['festivals']['posidelki-2026']['keepsake'] and 'Носки года' in last
    assert F.collection(f)['fest_posid_socks']['count'] == 1
    assert code(f, 'festival_buy', buy('fest_posid_socks')) == 'unknown_item'
    assert code(f, 'festival_buy', buy('fest_posid_basket')) == 'unknown_item'          # task rewards are not sold either
    validate_state(f)


# ---- fair purchases ----------------------------------------------------------------------------------------------------------
def test_buy_charges_the_value_law_price_and_grants_no_xp_or_coins():
    f = farm()
    g = F.good_of('posidelki', 'fest_posid_lights')
    cost = -(-90 * income_ref(8) // 100)
    assert F.price(g) == cost
    coins, xp = f['coins'], f['xp']
    text = cmd(f, 'festival_buy', buy('fest_posid_lights'))
    assert f['coins'] == coins - cost and f['xp'] == xp and str(cost) in text
    assert f['festivals']['posidelki-2026']['bought'] == {'fest_posid_lights': 1}
    assert code(f, 'festival_buy', buy('fest_posid_lights')) == 'limit_reached'
    assert f['coins'] == coins - cost


def test_buy_rules_level_funds_unknown_and_magpie_day():
    low = farm(xp=LEVELS[3])
    assert code(low, 'festival_buy', buy('fest_posid_quilt')) == 'locked'
    poor = farm(coins=10)
    assert code(poor, 'festival_buy', buy('fest_posid_wreath')) == 'insufficient_coins'
    f = farm()
    assert code(f, 'festival_buy', buy('nope')) == 'unknown_item'
    assert code(f, 'festival_buy', buy('fest_posid_lantern'), FAIR2) == 'seller_away'     # Сорока only on the first fair day
    cmd(f, 'festival_buy', buy('fest_posid_lantern'), FAIR)
    assert code(f, 'festival_buy', buy('fest_posid_lantern'), FAIR) == 'limit_reached'
    assert code(f, 'festival_buy', buy('fest_posid_wreath', fest='new_year'), ts(2026, 12, 31)) == 'unknown_item'   # stub festival: no goods yet


def test_past_festivals_shop_x15_and_limit_is_per_year():
    f = farm()
    assert code(f, 'festival_buy', buy('fest_posid_wreath'), ts(2026, 11, 10)) == 'festival_not_past'     # never happened yet
    g = F.good_of('posidelki', 'fest_posid_wreath')
    fair_price, late_price = F.price(g), -(-F.price(g) * 150 // 100)
    assert late_price == F.past_price(g) and late_price > fair_price
    before = f['coins']
    cmd(f, 'festival_buy', buy('fest_posid_wreath'), AFTER)
    assert before - f['coins'] == late_price and 'Лавке прошлых праздников' in f['events'][0]['text']
    assert 'fest_posid_wreath' in f['festivals']['posidelki-2026']['bought']
    assert code(f, 'festival_buy', buy('fest_posid_wreath'), AFTER) == 'limit_reached'
    # the magpie's goods are available later at the past price
    cmd(f, 'festival_buy', buy('fest_posid_lantern'), AFTER)
    # the memorable item of a year never returns
    assert code(f, 'festival_buy', buy('fest_posid_socks'), AFTER) == 'unknown_item'
    # next year the same festival sells again at the fair price under a fresh key
    c0 = f['coins']
    cmd(f, 'festival_buy', buy('fest_posid_wreath'), ts(2027, 11, 26))
    assert c0 - f['coins'] == fair_price and 'posidelki-2027' in f['festivals']
    validate_state(f)


def test_fair_buy_inside_a_live_fair_uses_the_fair_price_not_the_past_one():
    f = farm()
    g = F.good_of('posidelki', 'fest_posid_window')
    c0 = f['coins']
    cmd(f, 'festival_buy', buy('fest_posid_window'), ts(2027, 11, 28))                      # 2027 fair while 2026 is "past"
    assert c0 - f['coins'] == F.price(g)


def test_command_schemas_are_strict_and_owner_only():
    f = farm(inv={'yarn': 5})
    with pytest.raises(FarmError) as e:
        cmd(f, 'festival_task', {'festival': 'posidelki', 'task': 'yarn', 'option': 0, 'coins': 99})
    assert e.value.code == 'invalid_command'
    with pytest.raises(FarmError) as e:
        cmd(f, 'festival_task', {'festival': 'posidelki', 'task': 'yarn'})
    assert e.value.code == 'invalid_command'
    other = farm()
    with pytest.raises(FarmError) as e:
        apply(f, other, 'festival_buy', buy('fest_posid_wreath'), FAIR, 'k-other')
    assert e.value.code == 'not_owner'


# ---- migration, validation, privacy -------------------------------------------------------------------------------------------
def test_old_farm_without_festivals_loads_and_stays_unchanged_otherwise():
    f = farm()
    del f['festivals']
    before = deepcopy({k: v for k, v in f.items() if k != 'festivals'})
    upgrade_state(f)
    assert f['festivals'] == {} and {k: v for k, v in f.items() if k != 'festivals'} == before
    validate_state(f)
    view = project(f, f, FAIR)['festival']
    assert view['fair']['id'] == 'posidelki' and view['collection'] == {}


@pytest.mark.parametrize('bad', [
    {'ghost-2026': {}},
    {'posidelki-1999': F.blank()},
    {'posidelki-2026': {**F.blank(), 'bought': {'fest_posid_basket': 1}}},                  # a task reward cannot be "bought"
    {'posidelki-2026': {**F.blank(), 'bought': {'fest_posid_wreath': 2}}},                  # over the yearly limit
    {'posidelki-2026': {**F.blank(), 'tasks': {'ghost': 1}}},
    {'new_year-2027': {**F.blank(), 'keepsake': True}},                                    # a stub festival has no memorable item
    {'posidelki-2026': {'tasks': {}}},
])
def test_validate_state_rejects_corrupt_festival_state(bad):
    f = farm()
    f['festivals'] = bad
    with pytest.raises(FarmError) as e:
        validate_state(f)
    assert e.value.code == 'invalid_festivals'


def test_neighbours_see_the_world_calendar_but_never_the_collection_or_economy():
    owner, guest = farm(inv={'yarn': 4}), farm()
    owner['settings']['visibility'] = 'public'
    cmd(owner, 'festival_task', task('yarn'))
    cmd(owner, 'festival_buy', buy('fest_posid_wreath'))
    mine = project(owner, owner, FAIR)
    assert mine['festival']['fair']['tasks'][0]['done'] and mine['festival']['collection']
    seen = project(owner, guest, FAIR)
    assert set(seen['festival']) == {'current', 'upcoming', 'birthday'}
    assert seen['festival']['current']['id'] == 'posidelki' and 'festivals' not in seen
    flat = repr(seen)
    for secret in ('fest_posid_basket', 'fest_posid_wreath', 'bought', 'rewards', 'keepsake'):
        assert secret not in flat


def test_owner_view_lists_goods_prices_status_and_the_past_shop():
    f = farm(xp=LEVELS[7])
    view = F.owner_view(f, FAIR)
    goods = {g['id']: g for g in view['fair']['goods']}
    assert goods['fest_posid_quilt']['status'] == 'locked' and goods['fest_posid_wreath']['status'] == 'ok'
    assert goods['fest_posid_lantern']['away'] is False
    cmd(f, 'festival_buy', buy('fest_posid_wreath'))
    assert F.owner_view(f, FAIR)['fair']['goods'][2]['status'] == 'owned'
    assert F.owner_view(f, FAIR2)['fair']['goods'][-1]['away'] is True
    assert view['past'] == [] and F.owner_view(f, ts(2026, 12, 1))['fair'] is None
    past = F.owner_view(f, AFTER)['past'][0]
    assert past['id'] == 'posidelki' and past['key'] == 'posidelki-2026'
    assert next(g for g in past['goods'] if g['id'] == 'fest_posid_wreath')['status'] == 'owned'
    assert next(g for g in past['goods'] if g['id'] == 'fest_posid_lights')['price'] == F.past_price(F.good_of('posidelki', 'fest_posid_lights'))
    stub = F.owner_view(f, ts(2027, 1, 3))
    assert stub['fair']['id'] == 'new_year' and stub['fair']['todo'] and stub['fair']['tasks'] == [] and stub['fair']['goods'] == []


# ---- service: idempotency by command_id and the ledger -------------------------------------------------------------------------
class FakeUnit:
    def __init__(self, account_id, farm):
        self.account_id, self.farm, self.receipts, self.records = account_id, farm, {}, []

    async def lock(self, *keys): pass
    async def by_account(self, account_id): return self.farm if account_id == self.account_id else None
    async def get(self, farm_id): return self.farm if farm_id == self.farm['id'] else None
    async def owner_account(self, farm_id): return self.account_id
    async def save(self, farm, account_id=None): self.farm = farm
    async def receipt(self, account_id, key): return self.receipts.get((account_id, key))
    async def remember(self, account_id, key, fingerprint, result, now):
        self.receipts[(account_id, key)] = {'fingerprint': fingerprint, 'result': result}
    async def record(self, actor, key, kind, before, after, now): self.records.append((key, kind))


def test_service_replay_charges_once_and_writes_one_ledger_record():
    async def run():
        f = farm(inv={'yarn': 4})
        unit = FakeUnit('acc', f)
        service = FarmService(unit, Principal('acc', 'Игрок'), clock=lambda: FAIR)
        first = await service.command('fest-buy-0001', 'festival_buy', buy('fest_posid_wreath'))
        coins = unit.farm['coins']
        replay = await service.command('fest-buy-0001', 'festival_buy', buy('fest_posid_wreath'))
        assert replay == first and unit.farm['coins'] == coins
        with pytest.raises(FarmError) as reused:
            await service.command('fest-buy-0001', 'festival_buy', buy('fest_posid_lights'))
        assert reused.value.code == 'key_reused'
        with pytest.raises(FarmError) as again:
            await service.command('fest-buy-0002', 'festival_buy', buy('fest_posid_wreath'))
        assert again.value.code == 'limit_reached' and unit.farm['coins'] == coins
        done = await service.command('fest-task-001', 'festival_task', task('yarn'))
        assert await service.command('fest-task-001', 'festival_task', task('yarn')) == done
        assert unit.farm['festivals']['posidelki-2026']['rewards'] == {'fest_posid_basket': 1} and unit.farm['inventory']['yarn'] == 0
        assert [k for k, kind in unit.records if kind.startswith('festival')] == ['fest-buy-0001', 'fest-task-001']
        shown = await service.open()
        assert shown['farm']['festival']['fair']['id'] == 'posidelki'
    asyncio.run(run())


# ---- PostgreSQL acceptance (skipped without TEST_DATABASE_URL, like the other farm PG tests) ----------------------------------
def test_postgres_festival_commands_replay_once_and_neighbour_view_is_clean(farm_pg_url):
    from qw_farm.persistence import Unit
    from tests.test_farm_platform import accepted, command, environment, player, raw_farm, view

    async def scenario():
        async with environment(farm_pg_url) as env:
          # Guest sessions live 30 days: start the clock at the fair before the players sign in.
          env.now[0] = FAIR
          async with player(env) as owner, player(env, 'telegram') as other:
            async with env.db.transaction() as db:
                unit = Unit(db, env.schema)
                state = await unit.by_account(owner.account_id)
                state.update(xp=LEVELS[29], coins=10 ** 6, starter_credit=0)
                state['inventory']['yarn'] = 4
                state['settings']['visibility'] = 'public'
                validate_state(state)
                await unit.save(state)
            before = await raw_farm(env, owner)
            key = str(uuid4())
            first = await accepted(owner, 'festival_buy', buy('fest_posid_wreath'), key=key)
            assert await accepted(owner, 'festival_buy', buy('fest_posid_wreath'), key=key) == first
            after = await raw_farm(env, owner)
            assert after['coins'] < before['coins'] and after['festivals']['posidelki-2026']['bought'] == {'fest_posid_wreath': 1}
            assert (await command(owner, 'festival_buy', buy('fest_posid_wreath'))).status_code == 409
            await accepted(owner, 'festival_task', task('yarn'))
            mine = await view(owner)
            assert mine['festival']['fair']['tasks'][0]['done'] and mine['festival']['collection']
            seen = await view(other, owner.farm_id)
            assert set(seen['festival']) == {'current', 'upcoming', 'birthday'} and 'festivals' not in seen
            assert (await command(other, 'festival_buy', buy('fest_posid_lights'), target=owner.farm_id)).status_code == 403
            env.now[0] = ts(2026, 12, 2)
            assert (await command(owner, 'festival_task', task('warm'))).status_code == 409   # the fair is over
    asyncio.run(scenario())


def test_past_shop_hides_last_years_lots_while_the_same_fair_is_open():
    f = farm(xp=LEVELS[7])
    live = F.owner_view(f, ts(2027, 11, 28))
    assert live['fair']['id'] == 'posidelki'
    assert all(p['id'] != 'posidelki' for p in live['past'])               # the stall sells at the fair price, no x1.5 list beside it
    after = F.owner_view(f, ts(2027, 12, 5))
    assert [p['key'] for p in after['past'] if p['id'] == 'posidelki'] == ['posidelki-2027']
    c0 = f['coins']
    cmd(f, 'festival_buy', buy('fest_posid_wreath'), ts(2027, 11, 28))
    assert c0 - f['coins'] == F.price(F.good_of('posidelki', 'fest_posid_wreath'))


def test_magpie_first_means_the_first_fair_day_the_festival_actually_gets():
    # Maslenitsa 2027 (8-14 March) loses 8 March to Spring Flowers (higher priority, fair 6-8 March): the magpie comes on the 9th
    assert F.current(ts(2027, 3, 8))['id'] == 'spring_flowers'
    assert F.current(ts(2027, 3, 9))['id'] == 'maslenitsa' and F.current(ts(2027, 3, 9))['magpie']
    assert not F.current(ts(2027, 3, 10))['magpie']
    # an untouched festival keeps its own first day
    assert F.current(ts(2026, 11, 26))['magpie'] and not F.current(ts(2026, 11, 27))['magpie']


def test_split_festival_year_has_one_key_for_both_runs_and_the_magpie_comes_once():
    a, b = F.current(ts(2030, 3, 4)), F.current(ts(2030, 3, 9))
    assert a['id'] == b['id'] == 'maslenitsa' and a['key'] == b['key'] == 'maslenitsa-2030'
    assert a['starts_at'] != b['starts_at']                                 # two runs, so starts_at alone is not a once-per-year mark
    assert F.public_calendar(farm(), ts(2030, 3, 4))['current']['key'] == 'maslenitsa-2030'
    assert [d for d in range(4, 11) if F.current(ts(2030, 3, d)) and F.current(ts(2030, 3, d))['id'] == 'maslenitsa' and F.current(ts(2030, 3, d))['magpie']] == [4]
