"""Lossless identity codec for persisted Mafia states; no gameplay normalization.

Persisted state version 2 and the version-1 conversion rules are migration
contracts: preserve their semantics and add a new state version for future changes.
Alembic revision 0021 uses this codec to migrate durable game rows.
"""

from copy import deepcopy
from collections.abc import Mapping
import re
from uuid import UUID


def _account(value):
    if not isinstance(value, (str, UUID)):
        raise ValueError('Invalid account identity')
    try:
        result = str(UUID(str(value)))
    except (ValueError, AttributeError):
        raise ValueError('Invalid account identity') from None
    if isinstance(value, str) and value != result:
        raise ValueError('Account identity must be a canonical UUID')
    return result


def _user(value, *, key=False):
    if key and isinstance(value, str) and re.fullmatch(r'[1-9][0-9]*', value):
        value = int(value)
    if type(value) is not int or not 0 < value < 2**52:
        raise ValueError('Invalid Telegram user identity')
    return value


def _chat(value):
    if type(value) is not int or not -(2**52) < value < 0:
        raise ValueError('Invalid Telegram group identity')
    return value


def _room(value):
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValueError('Invalid room identity')
    if value.startswith('telegram:'):
        raw = value.removeprefix('telegram:')
        if not re.fullmatch(r'-[1-9][0-9]*', raw):
            raise ValueError('Invalid Telegram room identity')
        _chat(int(raw))
    else:
        if value.startswith('telegram:') or any(ord(char) < 32 for char in value):
            raise ValueError('Invalid standalone room identity')
    return value


def _mapping(values, *, reverse=False):
    if not isinstance(values, Mapping):
        raise ValueError('An identity mapping is required')
    result = {}
    for source, target in values.items():
        source = _account(source) if reverse else _user(source, key=True)
        target = _user(target) if reverse else _account(target)
        if source in result or target in result.values():
            raise ValueError('Duplicate or conflicting identity mapping')
        result[source] = target
    return result


def _convert_positions(state, translate):
    """Translate only documented identity positions, preserving dict/list order."""
    def actors(value, convert_value):
        if not isinstance(value, dict):
            raise ValueError('Malformed actor dictionary')
        result = {}
        for actor, payload in value.items():
            if not isinstance(actor, str):
                raise ValueError('Actor keys must be strings')
            translated = str(translate(actor, key=True))
            if translated in result:
                raise ValueError('Duplicate actor identity')
            result[translated] = convert_value(payload)
        return result

    if 'assignments' in state:
        state['assignments'] = actors(state['assignments'], lambda value: value)
    if 'alive' in state:
        if not isinstance(state['alive'], list):
            raise ValueError('Malformed alive identities')
        converted = [translate(value) for value in state['alive']]
        if len(set(converted)) != len(converted):
            raise ValueError('Duplicate alive identity')
        state['alive'] = converted
    if 'night_actions' in state:
        actions = state['night_actions']
        if not isinstance(actions, dict) or any(not isinstance(role, str) for role in actions):
            raise ValueError('Malformed night actions')
        state['night_actions'] = {
            role: actors(value, translate) for role, value in actions.items()
        }
    if 'votes' in state:
        state['votes'] = actors(state['votes'], translate)
    if 'investigations' in state:
        def checks(value):
            if not isinstance(value, list):
                raise ValueError('Malformed investigations')
            result = []
            for check in value:
                if not isinstance(check, dict) or 'target' not in check:
                    raise ValueError('Malformed investigation target')
                result.append({**check, 'target': translate(check['target'])})
            return result
        state['investigations'] = actors(state['investigations'], checks)


def canonicalize_mafia_state(state, room_id, telegram_user_accounts=None, legacy_chat_id=None):
    """Upgrade old Telegram/standalone or validate v2 without changing game data."""
    if not isinstance(state, dict):
        raise ValueError('Mafia state must be a dictionary')
    room_id = _room(room_id)
    version = state.get('state_version', 1)
    if type(version) is not int or version not in {1, 2}:
        raise ValueError('Unsupported Mafia state version')
    canonical = version == 2
    standalone = state.get('scope') == 'standalone'
    if canonical:
        if any(field in state for field in ('scope', 'chat_id', 'host_id')):
            raise ValueError('Canonical state contains transport identity')
    elif state.get('scope') not in (None, 'standalone', 'telegram'):
        raise ValueError('Unknown legacy scope')
    supplied_mapping = (_mapping(telegram_user_accounts)
                        if telegram_user_accounts is not None else None)
    if 'room_id' in state and state['room_id'] != room_id:
        raise ValueError('Room identity mismatch')
    if canonical or standalone:
        if state.get('room_id') != room_id:
            raise ValueError('Room identity is required')
        if standalone and (room_id.startswith('telegram:') or any(field in state for field in ('chat_id', 'host_id'))):
            raise ValueError('Standalone state contains transport identity')
        identity = 'account_id'
        mapping = None
        host = _account(state.get('host_account_id'))
    else:
        chat_id = _chat(state.get('chat_id'))
        if legacy_chat_id is not None and _chat(legacy_chat_id) != chat_id:
            raise ValueError('Chat identity mismatch')
        if room_id != f'telegram:{chat_id}':
            raise ValueError('Telegram room/chat mismatch')
        identity = 'user_id'
        mapping = supplied_mapping
        if mapping is None:
            raise ValueError('An identity mapping is required')
        host_user = _user(state.get('host_id'))
        if host_user not in mapping:
            raise ValueError('Missing host mapping')
        host = mapping[host_user]
        if 'host_account_id' in state and _account(state['host_account_id']) != host:
            raise ValueError('Conflicting host identity')
    if legacy_chat_id is not None and (not room_id.startswith('telegram:') or room_id != f'telegram:{_chat(legacy_chat_id)}'):
        raise ValueError('Room/chat identity mismatch')
    players = state.get('players')
    if not isinstance(players, list) or not players:
        raise ValueError('Missing player roster')
    result = deepcopy(state)
    accounts, sources = set(), set()
    for player in result['players']:
        if not isinstance(player, dict):
            raise ValueError('Malformed player')
        source = _account(player.get(identity)) if identity == 'account_id' else _user(player.get(identity))
        if mapping is not None and source not in mapping:
            raise ValueError('Missing player mapping')
        account = mapping[source] if mapping is not None else source
        if source in sources or account in accounts:
            raise ValueError('Duplicate player identity')
        if identity == 'account_id' and 'user_id' in player:
            raise ValueError('Account player contains transport identity')
        if identity == 'user_id' and 'account_id' in player and _account(player['account_id']) != account:
            raise ValueError('Conflicting player identity')
        sources.add(source)
        accounts.add(account)
        player.pop('user_id', None)
        player['account_id'] = account
    if host not in accounts:
        raise ValueError('Host is missing from roster')

    def translate(value, *, key=False):
        source = _account(value) if identity == 'account_id' else _user(value, key=key)
        if source not in sources:
            raise ValueError('Identity is missing from roster')
        return mapping[source] if mapping is not None else source

    _convert_positions(result, translate)
    for field in ('scope', 'chat_id', 'host_id'):
        result.pop(field, None)
    result.update(state_version=2, room_id=room_id, host_account_id=host)
    return result


def restore_legacy_mafia_state(state, room_kind, chat_id=None, account_user_ids=None):
    """Downgrade a validated canonical state for old deployments, losslessly."""
    if not isinstance(state, dict) or state.get('state_version') != 2:
        raise ValueError('A canonical v2 state is required')
    result = canonicalize_mafia_state(state, state.get('room_id'))
    result.pop('state_version')
    if room_kind == 'standalone':
        if chat_id is not None or account_user_ids is not None or result['room_id'].startswith('telegram:'):
            raise ValueError('Standalone downgrade contains Telegram identity')
        result['scope'] = 'standalone'
        return result
    if room_kind != 'telegram':
        raise ValueError('Unknown room kind')
    chat_id = _chat(chat_id)
    if result['room_id'] != f'telegram:{chat_id}':
        raise ValueError('Telegram room/chat mismatch')
    mapping = _mapping(account_user_ids, reverse=True)
    roster = {player['account_id'] for player in result['players']}

    def translate(value, *, key=False):
        account = _account(value)
        if account not in roster or account not in mapping:
            raise ValueError('Missing account/user mapping')
        return mapping[account]

    host = translate(result.pop('host_account_id'))
    _convert_positions(result, translate)
    for player in result['players']:
        player['user_id'] = translate(player.pop('account_id'))
    result.pop('room_id')
    result.update(chat_id=chat_id, host_id=host)
    return result
