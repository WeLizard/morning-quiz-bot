from application.game_catalog import game_mode, game_modes
from storage.games import telegram_room_id
from storage.models import AlchemyCraftCommand, Game


def test_game_catalog_has_unique_ids_and_explicit_capabilities():
    modes = game_modes()
    assert [mode['id'] for mode in modes] == ['classic', 'photo', 'night', 'atlas', 'farm']
    assert len({mode['id'] for mode in modes}) == len(modes)
    assert {mode['status'] for mode in modes} <= {'available', 'development', 'coming_soon'}
    assert all(mode['title'] and isinstance(mode['interfaces'], list)
               and isinstance(mode['capabilities'], list) for mode in modes)


def test_farmer_is_visible_as_coming_soon_not_as_playable():
    farm = game_mode('farm')
    assert farm == {
        'id': 'farm', 'title': 'Весёлый фермер', 'status': 'coming_soon',
        'interfaces': [], 'capabilities': [],
    }


def test_catalog_results_are_detached_from_the_canonical_manifest():
    modes = game_modes()
    modes[0]['capabilities'].clear()
    assert game_mode('classic')['capabilities']


def test_telegram_room_id_is_stable_and_transport_scoped():
    assert telegram_room_id(-1001234567890) == 'telegram:-1001234567890'
    assert telegram_room_id(42) == 'telegram:42'


def test_room_reference_belongs_to_game_not_alchemy_receipt():
    game = Game(id='game-1', chat_id=-100, room_id='telegram:-100',
                mode='mafia', status='lobby', phase='lobby')
    assert game.room_id == 'telegram:-100'
    assert not hasattr(AlchemyCraftCommand, 'room_id')
