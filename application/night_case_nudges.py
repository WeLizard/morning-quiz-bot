"""«Ночной город»: private Telegram nudges about a running case (MQB-012 stage 11, delivery plan §5 step 1).

The room in the mini app stays the source of truth; a nudge only says that something is waiting there.
It carries public facts only — the window number, that a hearing opened and on whom (the accusation is
public), that a whisper or a letter arrived — never a role, a secret, a clue or the text of a message.

Nudges are written into the shared notification outbox in the same transaction as the move that caused
them. Dedupe is per game, event and Telegram user, so a replayed command or a racing deadline never sends
twice. The bot delivers them (handlers/mafia_handlers.py) and drops the stale ones at sending time.
"""
from __future__ import annotations

from datetime import datetime, timedelta, time
from uuid import UUID
from zoneinfo import ZoneInfo

from application.room_telegram import telegram_members
from domain.night_case_text import chosen_looks, public_look
from storage.models import Account, NightGameSealed, Room
from storage.notifications import NotificationQueue

KIND = 'night_case.nudge'
EVENTS = frozenset({'start', 'window', 'hearing', 'whisper', 'letter', 'final'})
# Account-wide switch in «Профиль → Настройки игр» (domain/account_game_preferences.py); absent means on.
PREFERENCE = 'night_case_notifications'
_PLAYING = {'active', 'fog', 'ghost'}


def _hero_name(case_doc, doc, character_id):
    look = public_look(chosen_looks(case_doc, doc)[character_id])
    return str(look.get('name') or look.get('title') or '')[:80]


def case_nudges(case_doc, before, after, messages, events, *, actor_account=None):
    """What each player should hear about one transition: [(account id, event, dedupe part, extra)].

    ``before`` is the kernel before the transition (None at start); ``events`` and ``messages`` are the
    transition's own. The actor already saw the change in the app and is not nudged about it.
    """
    clock = after['clock']
    playing = [p['account_id'] for p in after['players'] if p['status'] in _PLAYING]
    result = []
    if before is None:
        result += [(a, 'start', 'start', {}) for a in playing]
    elif after['final'] is not None:
        if before['final'] is None:
            result += [(p['account_id'], 'final', 'final', {}) for p in after['players']]
    elif (clock['window_seq'] != before['clock']['window_seq'] and clock['phase'] in {'investigation', 'final_hearing'}
          and clock['opened_at'] is not None):
        extra = {'window_idx': clock['window_idx'], 'window_seq': clock['window_seq'],
                 'final_hearing': clock['phase'] == 'final_hearing'}
        result += [(a, 'window', f"window:{clock['window_seq']}", extra) for a in playing]
    hearing = after.get('hearing')
    if after['final'] is None and hearing and (before is None or (before.get('hearing') or {}).get('id') != hearing['id']):
        extra = {'hearing_id': hearing['id'], 'suspect': _hero_name(case_doc, after, hearing['suspect'])}
        result += [(a, 'hearing', hearing['id'], extra) for a in hearing['eligible_accounts']]
    for message in messages:
        if message['channel'] == 'whisper':
            result += [(a, 'whisper', 'whisper:' + message['id'], {}) for a in message['recipient_account_ids']
                       if a != message['sender_account_id']]
    for event in events:
        if event['kind'] in {'story_offer', 'ghost_whisper_received'} and event['audience']['kind'] == 'accounts':
            name = 'letter' if event['kind'] == 'story_offer' else 'whisper'
            result += [(a, name, 'event:' + event['event_id'], {}) for a in event['audience']['ids']]
    return [r for r in result if r[0] != actor_account]


def after_quiet_hours(now: datetime, rules_doc) -> datetime:
    """``now``, or the end of the case's quiet hours (its own time zone) if ``now`` falls inside them."""
    zone = ZoneInfo(rules_doc['timezone'])
    local = now.astimezone(zone)
    start, end = (time.fromisoformat(rules_doc[k]) for k in ('quiet_start', 'quiet_end'))
    at = local.time()
    inside = (start <= at or at < end) if start > end else (start <= at < end)
    if not inside:
        return now
    day = local.date() if at < end else local.date() + timedelta(days=1)
    return datetime.combine(day, end, zone).astimezone(now.tzinfo)


async def enqueue_case_nudges(session, *, game, case_doc, rules_doc, before, after, messages, events, actor_key, now) -> int:
    """Queue the nudges of one transition, inside the caller's transaction. Returns how many were new."""
    actor = actor_key if actor_key and actor_key != 'system' else None
    planned = case_nudges(case_doc, before, after, messages, events, actor_account=actor)
    if not planned or not game.room_id:
        return 0
    members = dict(await telegram_members(session, game.room_id, {a for a, *_ in planned}))
    if not members:
        return 0
    room = await session.get(Room, game.room_id)
    base = {'game_id': game.id, 'room_id': game.room_id, 'room_title': (room.title if room else '')[:80],
            'case_title': str(case_doc['meta']['title'])[:80], 'window_count': rules_doc['window_count']}
    due = after_quiet_hours(now, rules_doc)
    queued = 0
    for account, event, part, extra in planned:
        user_id = members.get(_uuid(account))
        if user_id is None:
            continue
        queued += await NotificationQueue.enqueue_in(
            session, kind=KIND, dedupe_key=f'night:{game.id}:{part}:{user_id}',
            payload={**base, 'event': event, 'account_id': str(account), **extra},
            game_id=game.id, chat_id=user_id, user_id=user_id, available_at=due)
    return queued


def _uuid(value):
    return UUID(str(value))


async def nudge_is_current(session, payload) -> bool:
    """Delivery-time check: drop a nudge the player can no longer act on, or one they switched off."""
    account = await session.get(Account, _uuid(payload.get('account_id')))
    if account is None or (account.game_preferences or {}).get(PREFERENCE) is False:
        return False
    if payload.get('event') not in EVENTS:
        return False
    sealed = await session.get(NightGameSealed, payload.get('game_id'))
    if sealed is None or sealed.lifecycle not in {'running', 'finished'}:
        return False
    if payload['event'] == 'final':
        return sealed.lifecycle == 'finished'
    if sealed.lifecycle != 'running':
        return False
    kernel = sealed.kernel or {}
    if payload['event'] == 'window':
        return (kernel.get('clock') or {}).get('window_seq') == payload.get('window_seq')
    if payload['event'] == 'hearing':
        return (kernel.get('hearing') or {}).get('id') == payload.get('hearing_id')
    return True
