"""«Ночной город» Telegram nudges: what is said about a transition, when, and that no secret is in it."""
from datetime import datetime, timezone

import pytest

from application.night_case_nudges import after_quiet_hours, case_nudges
from handlers.mafia_handlers import NIGHT_NUDGE_LINES, render_night_nudge

HERO = {'gender': 'm', 'title_forms': {}, 'bio': ''}
CASE = {'meta': {'title': 'Тайна усадьбы'}, 'characters': [
    {**HERO, 'id': 'butler', 'title': 'Дворецкий', 'looks': [{'id': 'a', 'title': 'Дворецкий', 'name': 'Арчибальд',
                                                               'gender': 'm', 'age': 60, 'title_forms': {}, 'art': None}]},
    {**HERO, 'id': 'maid', 'title': 'Горничная', 'gender': 'f'},
]}
RULES = {'timezone': 'Europe/Berlin', 'quiet_start': '23:00', 'quiet_end': '08:00', 'window_count': 14}


def state(*, window_seq=1, phase='investigation', opened: str | None = '2026-11-15T08:00:00Z', hearing=None, final=None,
          statuses=('active', 'active', 'fog', 'departed')):
    players = [{'account_id': f'a{i}', 'character_id': ['butler', 'maid', 'maid', 'maid'][i], 'status': s}
               for i, s in enumerate(statuses)]
    return {'clock': {'window_idx': window_seq, 'window_seq': window_seq, 'phase': phase, 'opened_at': opened},
            'players': players, 'hearing': hearing, 'final': final, 'sealed': {}}


def events_of(result):
    return sorted((account, event) for account, event, *_ in result)


def test_start_tells_every_seated_player_but_the_one_who_started():
    result = case_nudges(CASE, None, state(), [], [], actor_account='a0')
    assert events_of(result) == [('a1', 'start'), ('a2', 'start')]


def test_a_new_window_is_one_nudge_per_playing_seat_and_a_frozen_table_is_silent():
    result = case_nudges(CASE, state(), state(window_seq=2), [], [])
    assert events_of(result) == [('a0', 'window'), ('a1', 'window'), ('a2', 'window')]
    assert {part for _, _, part, _ in result} == {'window:2'}
    assert result[0][3] == {'window_idx': 2, 'window_seq': 2, 'final_hearing': False}
    assert case_nudges(CASE, state(), state(window_seq=2, phase='frozen', opened=None), [], []) == []
    final_hearing = case_nudges(CASE, state(window_seq=13), state(window_seq=14, phase='final_hearing'), [], [])
    assert final_hearing[0][3]['final_hearing'] is True


def test_a_hearing_names_the_public_suspect_to_the_eligible_voters_except_the_accuser():
    hearing = {'id': 'hearing:1', 'suspect': 'butler', 'eligible_accounts': ['a0', 'a1', 'a2']}
    result = case_nudges(CASE, state(), state(hearing=hearing), [], [], actor_account='a1')
    assert events_of(result) == [('a0', 'hearing'), ('a2', 'hearing')]
    assert result[0][3] == {'hearing_id': 'hearing:1', 'suspect': 'Арчибальд'}
    # The same hearing on the next move is not news.
    assert case_nudges(CASE, state(hearing=hearing), state(hearing=hearing), [], []) == []


def test_whispers_and_letters_go_to_their_recipients_only_without_text():
    whisper = {'id': 'm1', 'channel': 'whisper', 'sender_account_id': 'a0', 'recipient_account_ids': ['a0', 'a2'],
               'text': 'SECRET_TEXT'}
    square = {'id': 'm2', 'channel': 'square', 'sender_account_id': 'a0', 'recipient_account_ids': ['a1', 'a2'],
              'text': 'hello'}
    letter = {'kind': 'story_offer', 'event_id': 'e1', 'audience': {'kind': 'accounts', 'ids': ['a1']},
              'payload': {'body': 'SECRET_BODY'}}
    public = {'kind': 'scene', 'event_id': 'e2', 'audience': {'kind': 'public'}, 'payload': {}}
    result = case_nudges(CASE, state(), state(), [whisper, square], [letter, public], actor_account='a0')
    assert events_of(result) == [('a1', 'letter'), ('a2', 'whisper')]
    assert 'SECRET' not in repr(result)


def test_the_end_of_the_case_reaches_everyone_seated_once():
    result = case_nudges(CASE, state(), state(phase='finished', final={'code': 'solved'}), [], [])
    assert events_of(result) == [('a0', 'final'), ('a1', 'final'), ('a2', 'final'), ('a3', 'final')]
    finished = state(phase='finished', final={'code': 'solved'})
    assert case_nudges(CASE, finished, finished, [], []) == []


@pytest.mark.parametrize('utc, expected', [
    ('2026-11-15T10:00:00+00:00', '2026-11-15T10:00:00+00:00'),   # 11:00 in Berlin: now
    ('2026-11-15T22:30:00+00:00', '2026-11-16T07:00:00+00:00'),   # 23:30: tomorrow 08:00
    ('2026-11-16T03:00:00+00:00', '2026-11-16T07:00:00+00:00'),   # 04:00: today 08:00
    ('2026-11-16T07:00:00+00:00', '2026-11-16T07:00:00+00:00'),   # 08:00 sharp: awake
])
def test_quiet_hours_of_the_case_time_zone_hold_a_nudge_until_morning(utc, expected):
    assert after_quiet_hours(datetime.fromisoformat(utc), RULES) == datetime.fromisoformat(expected)
    assert after_quiet_hours(datetime.fromisoformat(utc), RULES).tzinfo is not None


def test_every_event_renders_with_the_open_button_and_unknown_ones_are_dropped():
    base = {'case_title': 'Тайна <усадьбы>', 'room_title': 'Наши', 'window_idx': 3, 'window_count': 14,
            'suspect': 'Арчибальд'}
    for event in ('start', 'window', 'hearing', 'whisper', 'letter', 'final'):
        text, rows = render_night_nudge({**base, 'event': event}, url='https://t.me/bot/app?startapp=roomid_x')
        assert text.startswith('🌒 <b>Тайна &lt;усадьбы&gt;</b> · Наши\n')
        assert rows[0][0].text == 'Открыть дело'
    assert 'окно 3 из 14' in render_night_nudge({**base, 'event': 'window'})[0]
    assert 'итоговое слушание' in render_night_nudge({**base, 'event': 'window', 'final_hearing': True})[0]
    assert 'Арчибальд' in render_night_nudge({**base, 'event': 'hearing'})[0]
    assert render_night_nudge({**base, 'event': 'role'}) is None
    # The lines only use public placeholders.
    assert all(set(__import__('re').findall(r'{(\w+)}', line)) <= {'window_idx', 'window_count', 'suspect'}
               for line in NIGHT_NUDGE_LINES.values())


def test_a_nudge_is_dated_in_utc_aware_time():
    assert after_quiet_hours(datetime(2026, 11, 15, 12, tzinfo=timezone.utc), RULES).utcoffset().total_seconds() == 0


def test_the_bot_sends_a_current_nudge_with_the_open_button_and_skips_a_stale_one(monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import application.night_case_nudges as nudges
    from handlers.mafia_handlers import MafiaHandlers

    class Database:
        @asynccontextmanager
        async def transaction(self):
            yield object()

    room = '0e3b5a52-6a51-4a59-9a39-6c1e0e0e0e0e'
    item = {'id': 'n1', 'kind': nudges.KIND, 'game_id': 'g', 'chat_id': 42, 'user_id': 42, 'claim_version': 1,
            'payload': {'event': 'window', 'window_idx': 2, 'window_count': 14, 'room_id': room,
                        'case_title': 'Тайна усадьбы', 'room_title': 'Наши'}}
    for current in (True, False):
        monkeypatch.setattr(nudges, 'nudge_is_current', AsyncMock(return_value=current))
        queue = SimpleNamespace(delivered=AsyncMock(), skipped=AsyncMock(), uncertain=AsyncMock(), retry_after=AsyncMock())
        bot = SimpleNamespace(username='QuizzyBot', send_message=AsyncMock())
        asyncio.run(MafiaHandlers(Database())._deliver_night_nudge(SimpleNamespace(bot=bot), queue, 'w', item))
        if current:
            args, kwargs = bot.send_message.await_args
            assert args[0] == 42 and 'окно 2 из 14' in args[1] and kwargs['parse_mode'] == 'HTML'
            button = kwargs['reply_markup'].inline_keyboard[0][0]
            assert button.text == 'Открыть дело' and button.url.endswith('startapp=roomid_' + room)
            queue.delivered.assert_awaited_once()
        else:
            bot.send_message.assert_not_awaited()
            queue.skipped.assert_awaited_once()
