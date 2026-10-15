"""Canonical public catalog of Morning Quiz game modes and their current capabilities."""

from copy import deepcopy
import os


_MODES = (
    {
        'id': 'classic',
        'title': 'Классический квиз',
        'status': 'available',
        'interfaces': ['telegram', 'mini_app'],
        'capabilities': ['timed_questions', 'shared_score', 'history'],
    },
    {
        'id': 'photo',
        'title': 'Фото-загадки',
        'status': 'available',
        'interfaces': ['telegram', 'mini_app'],
        'capabilities': ['timed_questions', 'photo_hints', 'shared_score'],
    },
    {
        'id': 'night',
        'title': 'Ночной город',
        'status': 'development',
        'interfaces': ['telegram', 'mini_app'],
        'capabilities': ['asynchronous_phases', 'private_role_actions', 'durable_state'],
    },
    {
        'id': 'atlas',
        'title': 'Атлас маленьких чудес',
        'status': 'available',
        'interfaces': ['mini_app'],
        'capabilities': ['account_progress', 'server_verified_rewards', 'offline_collection'],
    },
    {
        'id': 'farm',
        'title': 'Весёлый фермер',
        'status': 'coming_soon',
        'interfaces': [],
        'capabilities': [],
    },
)


def game_modes():
    """Return detached data so API consumers cannot mutate the canonical catalog."""
    modes = deepcopy(_MODES)
    if os.getenv('QW_FARM_ENABLED') == '1':
        farm = next(item for item in modes if item['id'] == 'farm')
        farm.update(status='development', interfaces=['browser', 'mini_app'],
                    capabilities=['account_farm', 'production', 'neighbors', 'equipment',
                                  'helpers', 'forest_trips', 'telegram_invites', 'server_owned_economy'])
    return modes


def game_mode(mode_id):
    return next((item for item in game_modes() if item['id'] == mode_id), None)
