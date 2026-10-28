"""Server-authoritative Pumpkin Night visitor and gift."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from qw_farm import economy, horseman
from qw_farm.catalog import ITEMS
from qw_farm.domain import FarmError, apply, new_farm, project, validate_state
from qw_farm.expansion import upgrade_state

MSK = timezone(timedelta(hours=3))


def ts(month, day, hour=0, year=2026, minute=0):
    return int(datetime(year, month, day, hour, minute, tzinfo=MSK).timestamp())


def farm(now=ts(10, 26, 17)):
    return upgrade_state(new_farm(str(uuid4()), 'Игрок', now))


def claim(f, now):
    return apply(f, f, 'claim_horseman_gift', {}, now, str(uuid4()))


def error(f, now, data=None, other=None):
    before = deepcopy(f)
    with pytest.raises(FarmError) as exc:
        apply(f, other or f, 'claim_horseman_gift', {} if data is None else data, now, str(uuid4()))
    assert f == before
    return exc.value.code


def test_catalog_and_unreachable_order_goods():
    from qw_farm.domain import reachable
    f = farm()
    assert ITEMS['pumpkin_candy'] == dict(id='pumpkin_candy', name='Тыквенная конфета',
                                          price=4, color='#e89137', kind='product')
    assert 'pumpkin_candy' not in reachable(f)


def test_candy_can_be_sold_as_ordinary_inventory():
    at = ts(10, 26, 18)
    f = farm(at)
    claim(f, at)
    economy.state(f)['billed_day'] = economy.moscow_day(at)
    before = f['coins']
    apply(f, f, 'sell', {'item': 'pumpkin_candy', 'qty': 1}, at, str(uuid4()))
    assert f['inventory']['pumpkin_candy'] == 2
    assert f['coins'] == before + 4


def test_window_boundaries_and_owner_projection():
    f = farm()
    assert horseman.owner_view(f, ts(10, 26, 16, minute=59))['active'] is False
    assert horseman.owner_view(f, ts(10, 26, 16, minute=59))['next_gift_at'] == ts(10, 26, 17)
    start = horseman.owner_view(f, ts(10, 26, 17))
    assert start['active'] and start['can_claim'] and not start['claimed_today']
    assert start['next_gift_at'] == ts(10, 26, 17)
    assert start['next_change_at'] == ts(10, 27, 0)
    assert start['gift'] == {'items': {'pumpkin_candy': 3, 'wheat': 4}}
    assert horseman.owner_view(f, ts(10, 27, 4, minute=59))['active']
    assert not horseman.owner_view(f, ts(10, 27, 5))['active']
    assert horseman.owner_view(f, ts(10, 27, 5))['next_change_at'] == ts(10, 27, 17)
    assert horseman.owner_view(f, ts(11, 2, 17))['active']
    assert horseman.owner_view(f, ts(11, 2, 17))['next_change_at'] == ts(11, 3)
    assert horseman.owner_view(f, ts(10, 25, 23)) is None
    assert horseman.owner_view(f, ts(11, 3)) is None


def test_claim_once_per_day_bonus_rotation_and_clock_rollback():
    f = farm()
    assert 'horseman_gifts' not in f
    assert error(f, ts(10, 26, 16)) == 'horseman_unavailable'
    assert error(f, ts(10, 25, 23)) == 'horseman_unavailable'
    assert error(f, ts(10, 26, 17), {'gift': 'anything'}) == 'invalid_command'
    coins, xp = f['coins'], f['xp']
    feed_before = f['inventory'].get('feed', 0)
    claim(f, ts(10, 26, 17))
    assert f['horseman_gifts'] == {'last_claim_day': economy.moscow_day(ts(10, 26, 17))}
    assert f['inventory']['pumpkin_candy'] == 3 and f['inventory']['wheat'] >= 4
    assert (f['coins'], f['xp']) == (coins, xp)
    assert error(f, ts(10, 26, 23)) == 'horseman_claimed'
    claim(f, ts(10, 27, 0))
    assert f['inventory']['pumpkin_candy'] == 6 and f['inventory']['feed'] == feed_before + 2
    assert horseman.owner_view(f, ts(10, 27, 0))['active']
    assert horseman.owner_view(f, ts(10, 27, 0))['next_gift_at'] == ts(10, 28)
    assert error(f, ts(10, 26, 23)) == 'horseman_claimed'
    claim(f, ts(10, 28, 0))
    assert f['inventory']['oat_cookie'] == 1
    claim(f, ts(10, 29, 0))
    assert f['inventory']['apple'] == 2
    validate_state(f)


def test_end_of_festival_and_visitor_privacy():
    f = farm()
    visitor = farm()
    f['settings']['visibility'] = 'public'
    claim(f, ts(11, 2, 17))
    shown = project(f, f, ts(11, 2, 18))
    assert shown['horseman']['claimed_today']
    assert shown['horseman']['active'] and shown['horseman']['next_gift_at'] is None
    seen = project(f, visitor, ts(11, 2, 18))
    assert 'horseman' not in seen and 'horseman_gifts' not in seen
    assert error(f, ts(11, 3)) == 'horseman_unavailable'
    assert error(f, ts(11, 2, 18), other=visitor) == 'not_owner'


def test_optional_state_validation():
    f = farm()
    for record in ({'last_claim_day': True}, {'last_claim_day': -1}, {'last_claim_day': 1, 'extra': 2}):
        f['horseman_gifts'] = record
        with pytest.raises(FarmError) as exc:
            validate_state(f)
        assert exc.value.code == 'invalid_horseman_gifts'
