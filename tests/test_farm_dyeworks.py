"""Bridge «Алхимия» → farm: dyer's notes sealed by the server teach the farm its dye recipes."""

import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from qw_farm import dyeworks
from qw_farm.construction import merge_effect_state
from qw_farm.catalog import LEVELS
from qw_farm.domain import FarmError, new_farm, project, validate_state
from qw_farm.expansion import upgrade_state
from qw_farm.persistence import Unit
from qw_farm.service import FarmService, Principal
from storage.database import normalize_database_url

NOW = 1_800_000_000


def farm():
    return upgrade_state(new_farm(str(uuid4()), 'Игрок', NOW))


def test_learn_is_monotonic_and_ignores_foreign_stages():
    f = farm()
    assert dyeworks.unlocked(f) == []
    assert dyeworks.learn(f, {'dyers_2', 'paths_1', 'dyers_9'}, NOW) == ['indigo']
    assert dyeworks.learn(f, {'dyers_2'}, NOW + 5) == []
    assert f['dyeworks']['unlocked'] == {'indigo': NOW}
    assert dyeworks.learn(f, {'dyers_4', 'dyers_1'}, NOW + 9) == ['mordant', 'saffron']
    assert dyeworks.unlocked(f) == ['mordant', 'indigo', 'saffron']
    validate_state(f)


def test_learning_nothing_leaves_old_saves_untouched():
    f = farm()
    assert dyeworks.learn(f, set(), NOW) == []
    assert 'dyeworks' not in f


def test_public_shows_only_learned_recipes_and_hides_the_riddle():
    f = farm()
    assert dyeworks.public(f) == {'recipes': []}
    dyeworks.learn(f, {'dyers_3', 'dyers_1'}, NOW)
    view = dyeworks.public(f)
    assert view == {'recipes': [dict(recipe='mordant', name='Протрава', learned_at=NOW),
                                dict(recipe='madder', name='Марена', learned_at=NOW)]}
    text = repr(view)
    for leak in ('Записка', 'dyers_', 'alchemy', 'Атлас', 'total'):
        assert leak not in text


def test_owner_projection_carries_notes_and_visitor_does_not_see_them():
    owner, visitor = farm(), farm()
    owner['xp'] = visitor['xp'] = LEVELS[2]
    dyeworks.learn(owner, {'dyers_1'}, NOW)
    assert len(project(owner, owner, NOW)['dyeworks']['recipes']) == 1
    owner['settings']['visibility'] = 'public'
    assert 'dyeworks' not in project(owner, visitor, NOW)


def test_merge_is_union_with_earliest_date():
    main, secondary = farm(), farm()
    dyeworks.learn(main, {'dyers_1', 'dyers_2'}, NOW + 100)
    dyeworks.learn(secondary, {'dyers_2', 'dyers_4'}, NOW)
    merge_effect_state(main, secondary, NOW + 200)
    assert main['dyeworks']['unlocked'] == {'mordant': NOW + 100, 'indigo': NOW, 'saffron': NOW}
    empty = farm()
    merge_effect_state(empty, farm(), NOW)
    assert 'dyeworks' not in empty


@pytest.mark.parametrize('value', [
    [], {'unlocked': []}, {'unlocked': {'gold': NOW}}, {'unlocked': {'indigo': -1}},
    {'unlocked': {'indigo': 1.5}}, {'unlocked': {'indigo': True}}, {'unlocked': {}, 'extra': 1},
])
def test_validate_rejects_broken_state(value):
    f = farm()
    f['dyeworks'] = value
    with pytest.raises(FarmError):
        validate_state(f)


def test_claims_are_ignored_outside_postgresql():
    class Plain:
        dialect = 'sqlite'
        asynchronous = True

    f = farm()
    assert asyncio.run(dyeworks.refresh(Plain(), f, str(uuid4()), NOW)) == []
    assert 'dyeworks' not in f


@pytest.fixture
def pg_url():
    raw = os.getenv('TEST_DATABASE_URL')
    if not raw:
        pytest.skip('TEST_DATABASE_URL is not configured')
    return normalize_database_url(raw)


def test_sealed_note_unlocks_recipe_on_open_for_owner_only(pg_url):
    from storage.models import AlchemyStageClaim
    from tests.test_farm_oleg_pg import environment, seeded

    async def scenario():
        async with environment(pg_url) as env:
            owner, farm_id = await seeded(env, NOW)
            stranger, _ = await seeded(env, NOW)
            claimed = datetime.fromtimestamp(NOW, timezone.utc)
            async with env.db.transaction() as session:
                for account, stage, campaign in ((owner, 'dyers_2', dyeworks.CAMPAIGN),
                                                 (owner, 'dyers_3', 'paths_camp_other'),
                                                 (stranger, 'dyers_1', dyeworks.CAMPAIGN)):
                    session.add(AlchemyStageClaim(account_id=account, stage_id=stage, campaign_id=campaign,
                                                  catalog_revision='test', reward={}, claimed_at=claimed))

            async def open_view(account, at):
                async with env.db.transaction() as session:
                    service = FarmService(Unit(session, env.schema), Principal(str(account), 'Игрок'), clock=lambda: at)
                    return (await service.view())['farm']

            shown = await open_view(owner, NOW + 60)
            assert [r['recipe'] for r in shown['dyeworks']['recipes']] == ['indigo']
            async with env.db.transaction() as session:
                stored = await Unit(session, env.schema).get(farm_id)
            assert stored['dyeworks'] == {'unlocked': {'indigo': NOW + 60}}
            revision = stored['revision']
            again = await open_view(owner, NOW + 120)
            assert again['dyeworks']['recipes'][0]['learned_at'] == NOW + 60
            async with env.db.transaction() as session:
                assert (await Unit(session, env.schema).get(farm_id))['revision'] == revision
            assert [r['recipe'] for r in (await open_view(stranger, NOW + 60))['dyeworks']['recipes']] == ['mordant']
    asyncio.run(scenario())
