"""R16 references and paid-decoration economic contract (no database)."""
from copy import deepcopy

import pytest

from qw_farm import catalog as C, economy as E


def test_r16_content_references_are_playable():
    for item_id in C.R16_ITEM_IDS:
        assert item_id in C.ITEMS
    for crop_id in C.R16_CROP_IDS:
        crop = C.CROPS[crop_id]
        assert crop['seconds'] > 0 and crop['yield_qty'] > 0
        assert 1 <= crop['level'] <= 50
    for rows, table, ids in ((C.R16_RECIPE_ROWS, C.RECIPES, C.R16_RECIPE_IDS),
                             (C.R16_ANIMAL_ROWS, C.ANIMALS, C.R16_ANIMAL_IDS)):
        assert len(ids) == len(rows), 'Duplicate R16 identifiers'
        for key in ids:
            spec = table[key]
            building = C.BUILDINGS[spec['building']]
            assert not building['decor']
            assert building['level'] <= spec['level'] <= 50
            assert spec['seconds'] > 0
            for goods in (spec['inputs'], spec['outputs']):
                assert goods and all(k in C.ITEMS and type(q) is int and q > 0
                                     for k, q in goods.items())


@pytest.mark.parametrize('decor', C.DECOR_EXTRA, ids=lambda d: d['id'])
def test_extra_decor_is_paid_sink_without_upkeep(decor):
    farm = {'size': 20, 'objects': [{'type': decor['id'], 'level': 3}], 'fields': []}
    assert E.base_upkeep(farm) == 0
    E.note_decor_spend(farm, decor['id'], decor['cost'])
    assert E.state(farm)['stats']['decor'] == decor['cost']
    before = deepcopy(farm)
    E.note_decor_spend(farm, decor['id'], 0)
    assert farm == before


def test_non_decor_spend_does_not_pollute_decor_statistics():
    farm = {}
    E.note_decor_spend(farm, 'mill', C.BUILDINGS['mill']['cost'])
    assert farm == {}
