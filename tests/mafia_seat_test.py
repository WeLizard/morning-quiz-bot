"""Offline checks for scripts/mafia_seat.py (no network): target resolution,
status projection privacy, availability rules and the wake-up signature.

    python tests/mafia_seat_test.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import mafia_seat as ms  # noqa: E402


def players(n, me=1, alive=None, ready=False):
    alive = alive or list(range(1, n + 1))
    return [{'name': f'Игрок{i}', 'ready': ready, 'seat': f'p{i}', 'alive': i in alive, 'is_me': i == me}
            for i in range(1, n + 1)]


def lobby(status, n=5, me=1, host=True, **extra):
    base = {'mode': 'mafia_lobby', 'status': status, 'revision': 3, 'phase_revision': 1,
            'players': players(n, me), 'is_host': host, 'joined': True, 'can_start': False}
    if status != 'lobby':
        base.update(round=1, winner=None, history=[], ends_at=None)
    base.update(extra)
    return base


def role(name, phase='night', **extra):
    out = {'phase': phase, 'round': 1, 'role': name, 'title': name, 'alive': True, 'seat': 'p1',
           'winner': None, 'phase_revision': 1}
    out.update(extra)
    return out


class SeatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ['MAFIA_SEATS_DIR'] = self.tmp.name
        self.seat = ms.Seat('t', 'http://example.invalid')

    def tearDown(self):
        os.environ.pop('MAFIA_SEATS_DIR', None)
        self.tmp.cleanup()

    def test_resolve_target(self):
        targets = [{'seat': 'p2', 'name': 'Анна'}, {'seat': 'p3', 'name': 'Борис'}, {'seat': 'p4', 'name': 'Анна-Мария'}]
        self.assertEqual(ms.resolve_target('p3', targets)['name'], 'Борис')
        self.assertEqual(ms.resolve_target('3', targets)['seat'], 'p3')
        self.assertEqual(ms.resolve_target('анна', targets)['seat'], 'p2')   # exact beats partial
        self.assertEqual(ms.resolve_target('Бор', targets)['seat'], 'p3')
        with self.assertRaises(ms.SeatError) as ctx:
            ms.resolve_target('Мария-X', targets)
        self.assertIn('allowed_targets', ctx.exception.payload()['error'])
        with self.assertRaises(ms.SeatError):
            ms.resolve_target('5', targets)

    def test_status_never_shows_other_roles(self):
        status = ms.build_status(self.seat, lobby('night'), role('mafia', targets=[
            {'seat': 'p2', 'name': 'Игрок2'}, {'seat': 'p3', 'name': 'Игрок3'}], acted=False))
        raw = json.dumps(status, ensure_ascii=False)
        self.assertEqual(raw.count('"role"'), 1)
        self.assertTrue(all('role' not in p for p in status['players']))
        self.assertEqual(status['me']['role'], 'mafia')
        self.assertEqual([a['action'] for a in status['available']], ['act'])
        self.assertIn('Игрок2(p2)', status['available'][0]['targets'])

    def test_detective_knowledge_accumulates(self):
        lob = lobby('day', host=False)
        inv = {'round': 1, 'seat': 'p3', 'is_mafia': True}
        status = ms.build_status(self.seat, lob, role('detective', phase='day', investigation=inv))
        self.assertEqual(status['me']['knowledge'][0]['result'], 'МАФИЯ')
        inv2 = {'round': 2, 'seat': 'p4', 'is_mafia': False}
        status = ms.build_status(self.seat, lob, role('detective', phase='day', investigation=inv2))
        self.assertEqual([k['night'] for k in status['me']['knowledge']], [1, 2])
        self.assertEqual(status['me']['knowledge'][1]['player'], 'Игрок4(p4)')

    def test_availability(self):
        cit = ms.build_status(self.seat, lobby('night', host=False), role('citizen'))
        self.assertEqual(ms.pending(cit), [])                      # citizens just wait at night
        voting = ms.build_status(self.seat, lobby('voting', host=False, votes_cast=1, votes_needed=5),
                                 role('citizen', phase='voting', voted=False, targets=[{'seat': 'p2', 'name': 'Игрок2'}]))
        self.assertEqual(ms.pending(voting), ['vote'])
        voted = ms.build_status(self.seat, lobby('voting', host=False), role('citizen', phase='voting', voted=True))
        self.assertEqual(ms.pending(voted), [])
        dead = ms.build_status(self.seat, lobby('voting', host=False), role('citizen', phase='voting', alive=False))
        self.assertEqual(ms.pending(dead), [])
        host_day = ms.build_status(self.seat, lobby('day', can_advance=True), role('citizen', phase='day'))
        self.assertIn('advance', [a['action'] for a in host_day['available']])
        self.assertEqual(ms.pending(host_day), [])                 # advance/say never wake `wait` by themselves
        not_joined = ms.build_status(self.seat, dict(lobby('lobby'), joined=False), None)
        self.assertEqual(ms.pending(not_joined), ['sit'])
        ready = ms.build_status(self.seat, lobby('lobby'), None)
        self.assertEqual(ms.pending(ready), ['ready'])

    def test_signature_changes_on_phase_not_chat(self):
        a = ms.signature(lobby('night'))
        self.assertEqual(a, ms.signature(lobby('night')))
        self.assertNotEqual(a, ms.signature(lobby('night', phase_revision=2)))
        self.assertNotEqual(a, ms.signature(lobby('day')))

    def test_history_uses_names_and_finish(self):
        hist = [{'type': 'started', 'round': 1}, {'type': 'night_result', 'round': 1, 'eliminated': 'p3', 'saved': False},
                {'type': 'vote_result', 'round': 1, 'eliminated': None}]
        status = ms.build_status(self.seat, lobby('finished', history=hist, winner='mafia'), role('citizen', phase='finished', winner='mafia'))
        self.assertIn('Игрок3(p3)', status['history'][1])
        self.assertEqual(status['winner'], 'mafia')
        self.assertIn('никто не выбыл', status['history'][2])

    def test_no_table(self):
        status = ms.build_status(self.seat, None, None)
        self.assertEqual(status['phase'], 'no_table')

    def test_seat_file_roundtrip_has_no_secret_in_output(self):
        self.seat.data['cookie'] = 'SECRET-COOKIE-VALUE'
        self.seat.save()
        again = ms.Seat('t')
        self.assertEqual(again.data['cookie'], 'SECRET-COOKIE-VALUE')
        raw = json.dumps(ms.build_status(again, lobby('lobby'), None), ensure_ascii=False)
        self.assertNotIn('SECRET', raw)


if __name__ == '__main__':
    unittest.main(verbosity=2)
