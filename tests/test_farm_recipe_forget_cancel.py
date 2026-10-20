"""forget_recipe and cancelling a running workshop batch (undo.py canon: 60 s window, then half, no XP)."""
import asyncio

import pytest

from tests.test_farm_automation_r7 import T0, add_building, cmd, err, farm, hire_and_start, obj
from tests.test_farm_market_r8 import MemoryUnit
from qw_farm.expansion import settle
from qw_farm.service import FarmService, Principal
from qw_farm.undo import LATE_REFUND_PCT, UNDO_WINDOW, job_refund


def queue_flour(st, at=T0, recipe='flour'):
    cmd(st, 'queue', {'object': 'm', 'recipe': recipe}, at)
    return obj(st, 'm')['jobs'][-1]


def test_forget_clears_last_recipe_and_queue_remembers_it_again():
    st = farm()
    add_building(st, 'mill', 'm', 0, 0, last_recipe='flour')
    st['inventory'] = {'wheat': 10}
    rev = obj(st, 'm')['revision']
    text = cmd(st, 'forget_recipe', {'object': 'm'})
    assert 'last_recipe' not in obj(st, 'm') and obj(st, 'm')['revision'] == rev + 1 and 'забыт' in text
    assert err(st, 'forget_recipe', {'object': 'm'}) == 'no_recipe'
    queue_flour(st)
    assert obj(st, 'm')['last_recipe'] == 'flour'


def test_forget_rejects_non_workshop():
    st = farm()
    st['objects'].append(dict(id='r', type='road', x=0, y=0, w=1, h=1, revision=0))
    assert err(st, 'forget_recipe', {'object': 'r'}) == 'wrong_object'


def test_artisan_collects_but_does_not_restart_after_forget():
    st = farm()
    add_building(st, 'mill', 'm', 0, 0, last_recipe='flour')
    st['inventory'] = {'wheat': 10}
    queue_flour(st)
    cmd(st, 'forget_recipe', {'object': 'm'})
    hire_and_start(st, 'beaver_artisan', 'day')
    settle(st, T0 + 7200)
    assert st['inventory'] == {'wheat': 8, 'flour': 1} and obj(st, 'm')['jobs'] == []


def test_restart_all_skips_forgotten_recipe():
    st = farm()
    add_building(st, 'mill', 'm', 0, 0, last_recipe='flour')
    st['inventory'] = {'wheat': 10}
    add_building(st, 'mill', 'other', 6, 0, last_recipe='flour')
    cmd(st, 'forget_recipe', {'object': 'm'})
    cmd(st, 'restart_all', {'area': None})
    assert obj(st, 'm')['jobs'] == [] and len(obj(st, 'other')['jobs']) == 1


def test_cancel_queued_is_full_refund_at_any_time_and_following_batches_shift():
    st = farm()
    add_building(st, 'mill', 'm', 0, 0)
    st['inventory'] = {'sunflower': 6}
    a, b, c = queue_flour(st, recipe='oil'), queue_flour(st, recipe='oil'), queue_flour(st, recipe='oil')
    assert st['inventory']['sunflower'] == 0 and b['starts_at'] == a['ready_at']
    at = T0 + UNDO_WINDOW + 10  # long after the window, but batch b has not started
    text = cmd(st, 'cancel_job', {'object': 'm', 'job': b['id']}, at)
    assert st['inventory'] == {'sunflower': 2} and 'полностью' in text
    assert c['starts_at'] == a['ready_at'] and c['ready_at'] == c['starts_at'] + c['seconds']


def test_cancel_running_in_window_is_full_and_next_batch_starts_now():
    st = farm()
    add_building(st, 'mill', 'm', 0, 0)
    st['inventory'] = {'sunflower': 4}
    a, b = queue_flour(st, recipe='oil'), queue_flour(st, recipe='oil')
    at = T0 + UNDO_WINDOW
    text = cmd(st, 'cancel_job', {'object': 'm', 'job': a['id']}, at)
    assert st['inventory'] == {'sunflower': 2} and 'полностью' in text
    assert b['starts_at'] == at and b['ready_at'] == at + b['seconds']
    assert obj(st, 'm')['last_recipe'] == 'oil'


def test_cancel_running_after_window_is_half_floor_no_xp_no_products():
    st = farm()
    add_building(st, 'mill', 'm', 0, 0)
    st['inventory'] = {'sunflower': 5}
    a = queue_flour(st, recipe='oil')  # inputs wheat x2
    xp, at = st['xp'], T0 + UNDO_WINDOW + 1
    text = cmd(st, 'cancel_job', {'object': 'm', 'job': a['id']}, at)
    assert st['inventory'] == {'sunflower': 4} and 'oil' not in st['inventory'] and st['xp'] == xp
    assert 'Подсолнух ×1' in text and 'опыта нет' in text
    assert obj(st, 'm')['jobs'] == []


def test_job_refund_floor_and_zero_positions():
    job = dict(starts_at=0, ready_at=500, inputs={'a': 1, 'b': 5, 'c': 2})
    assert job_refund(job, 60) == ({'a': 1, 'b': 5, 'c': 2}, True)
    assert job_refund(job, 61) == ({'b': 2, 'c': 1}, False) and LATE_REFUND_PCT == 50
    assert job_refund(dict(starts_at=0, ready_at=500, inputs={'a': 1}), 100) == ({}, False)


def test_cancel_late_with_nothing_to_return_says_so():
    st = farm()
    add_building(st, 'mill', 'm', 0, 0)
    a = dict(id='j1', recipe='flour', starts_at=T0, ready_at=T0 + 500, seconds=500, inputs={'wheat': 1}, outputs={'flour': 1}, xp=1)
    obj(st, 'm')['jobs'].append(a)
    text = cmd(st, 'cancel_job', {'object': 'm', 'job': 'j1'}, T0 + 100)
    assert 'Ничего не вернулось' in text and st['inventory'] == {}


def test_cancel_ready_batch_is_refused():
    st = farm()
    add_building(st, 'mill', 'm', 0, 0)
    st['inventory'] = {'sunflower': 2}
    a = queue_flour(st, recipe='oil')
    assert err(st, 'cancel_job', {'object': 'm', 'job': a['id']}, a['ready_at']) == 'job_done'
    assert len(obj(st, 'm')['jobs']) == 1


@pytest.mark.parametrize('elapsed,refunded', [(UNDO_WINDOW, 2), (UNDO_WINDOW + 1, 1)])
def test_atomic_cancel_forget_preserves_refund_and_no_xp(elapsed, refunded):
    st = farm()
    mill = add_building(st, 'mill', 'm', 0, 0)
    st['inventory'] = {'sunflower': 2}
    batch = queue_flour(st, recipe='oil')
    xp, rev = st['xp'], mill['revision']
    text = cmd(st, 'cancel_job_and_forget_recipe', {'object': 'm', 'job': batch['id']}, T0 + elapsed)
    assert mill['jobs'] == [] and 'last_recipe' not in mill
    assert mill['revision'] == rev + 1
    assert st['inventory'] == {'sunflower': refunded} and st['xp'] == xp
    assert 'Рецепт забыт' in text


@pytest.mark.parametrize('remembered,error', [(None, 'no_recipe'), ('oil', 'recipe_changed')])
def test_atomic_cancel_requires_matching_remembered_recipe_before_mutation(remembered, error):
    st = farm()
    mill = add_building(st, 'mill', 'm', 0, 0)
    st['inventory'] = {'wheat': 2}
    batch = queue_flour(st)
    if remembered is None:
        mill.pop('last_recipe')
    else:
        mill['last_recipe'] = remembered
    assert err(st, 'cancel_job_and_forget_recipe', {'object': 'm', 'job': batch['id']}, T0 + 1) == error
    assert mill.get('last_recipe') == remembered
    assert mill['jobs'] == [batch] and st['inventory'] == {'wheat': 0}


def test_atomic_cancel_errors_leave_batch_and_recipe_unchanged():
    st = farm()
    add_building(st, 'mill', 'm', 0, 0)
    st['inventory'] = {'wheat': 2}
    batch = queue_flour(st)
    assert err(st, 'cancel_job_and_forget_recipe', {'object': 'm', 'job': 'missing'}) == 'not_found'
    assert err(st, 'cancel_job_and_forget_recipe', {'object': 'm'}) == 'invalid_command'
    assert err(st, 'cancel_job_and_forget_recipe', {'object': 'm', 'job': batch['id']}, batch['ready_at']) == 'job_done'
    st['objects'].append(dict(id='r', type='road', x=6, y=0, w=1, h=1, revision=0))
    assert err(st, 'cancel_job_and_forget_recipe', {'object': 'r', 'job': 'missing'}) == 'wrong_object'


def test_atomic_cancel_through_service_does_not_let_artisan_requeue_refund():
    async def run():
        st = farm()
        mill = add_building(st, 'mill', 'm', 0, 0)
        st['inventory'] = {'wheat': 2}
        batch = queue_flour(st)
        hire_and_start(st, 'beaver_artisan', 'day')
        clock = [T0 + 10]
        unit = MemoryUnit('acc', st)
        service = FarmService(unit, Principal('acc', 'Игрок'), clock=lambda: clock[0])
        data = {'object': 'm', 'job': batch['id']}
        result = await service.command('cancel-forget-0001', 'cancel_job_and_forget_recipe', data)
        assert mill['jobs'] == [] and 'last_recipe' not in mill
        assert st['inventory'] == {'wheat': 2}
        clock[0] = T0 + 7200
        await service.view()  # a later request settles all due assistant work
        assert mill['jobs'] == [] and st['inventory'] == {'wheat': 2}
        assert st['helpers']['beaver_artisan']['shift']['done'] == 0
        assert await service.command('cancel-forget-0001', 'cancel_job_and_forget_recipe', data) == result
        assert st['inventory'] == {'wheat': 2}  # replay must not refund twice
        assert sum(kind == 'cancel_job_and_forget_recipe' for _, kind in unit.records) == 1

    asyncio.run(run())
