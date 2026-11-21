"""Night Case read path: shared read-only data, validation memo, lock-free view."""
import asyncio
import copy
import json
import pickle
import unittest
from datetime import datetime, timezone
from pathlib import Path

from domain.night_case_engine import _initialize
from domain.night_case_projection import available_actions, project
from domain.night_case_state import KernelState, PlayerActor, rules_snapshot
from domain.night_case_v2_format import compile_v2, load_v2

ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = ROOT / 'content/night_city/manor_lake.case.json'
START = datetime(2026, 11, 15, 10, tzinfo=timezone.utc)


def manor():
    return compile_v2(load_v2(CASE_PATH.read_bytes()))


def started(case, rules):
    roster = {'players': [{'account_id': f'actor{i:02d}', 'display_name': f'Игрок {i:02d}'} for i in range(8)],
              'npc_name_pool': [f'Гость {i:02d}' for i in range(20)]}
    return _initialize(case, rules, roster, game_id='read_path', seed=7, composition_id='manor_8',
                       selected_variant_id='variant_a', now_utc=START).state


class ReadOnlyCaseTests(unittest.TestCase):
    def test_readonly_is_parsed_once_frozen_and_equal_to_document(self):
        case = manor()
        shared = case.readonly()
        self.assertIs(shared, case.readonly())
        self.assertEqual(shared, case.document())
        self.assertEqual(json.dumps(shared, sort_keys=True), json.dumps(case.document(), sort_keys=True))
        for mutate in (lambda: shared.__setitem__('x', 1), lambda: shared['meta'].update(title='x'),
                       lambda: shared['characters'].append({}), lambda: shared['characters'][0].pop('id'),
                       lambda: shared['locations'].sort(), lambda: shared.setdefault('y', 1)):
            with self.assertRaises(TypeError):
                mutate()
        self.assertEqual(shared, case.document())

    def test_copies_of_readonly_parts_are_plain_and_mutable(self):
        case = manor()
        part = copy.deepcopy(case.readonly()['characters'][0])
        self.assertIs(type(part), dict)
        part['id'] = 'changed'
        self.assertNotEqual(case.readonly()['characters'][0]['id'], 'changed')
        self.assertIs(type(pickle.loads(pickle.dumps(case.readonly()['meta']))), dict)
        fresh = case.document()
        fresh['meta']['title'] = 'changed'
        self.assertNotEqual(case.readonly()['meta']['title'], 'changed')


class ValidationMemoTests(unittest.TestCase):
    def test_validated_for_skips_only_for_equal_case_and_rules(self):
        case, rules = manor(), rules_snapshot('Europe/Berlin')
        state = KernelState.from_document(started(case, rules).document(), case, rules)
        self.assertIs(state.validated_for(case, rules), state)
        self.assertIs(state.validated_for(manor(), rules_snapshot('Europe/Berlin')), state)
        plain = KernelState(state.document(), ruleset_version=2)
        revalidated = plain.validated_for(case, rules)
        self.assertIsNot(revalidated, plain)
        self.assertEqual(revalidated, KernelState.from_document(state.document(), case, rules))

    def test_unvalidated_snapshot_is_still_rejected_by_projection(self):
        case, rules = manor(), rules_snapshot('Europe/Berlin')
        doc = started(case, rules).document()
        doc['players'][0]['character_id'] = 'nobody'
        with self.assertRaises((ValueError, KeyError, StopIteration)):
            project(case, rules, KernelState(doc, ruleset_version=2), PlayerActor(doc['players'][0]['account_id']))

    def test_projection_and_menu_match_fresh_documents(self):
        case, rules = manor(), rules_snapshot('Europe/Berlin')
        state = started(case, rules)
        viewer = PlayerActor(state.document()['players'][0]['account_id'])
        fresh = compile_v2(load_v2(CASE_PATH.read_bytes()))
        self.assertEqual(project(case, rules, state, viewer), project(fresh, rules, state, viewer))
        self.assertEqual(available_actions(case, rules, state, viewer, now_utc=START),
                         available_actions(fresh, rules, state, viewer, now_utc=START))


from tests.test_night_case_application import NightApplicationPostgresTests  # noqa: E402


class NightReadPathPostgresTests(NightApplicationPostgresTests):
    """Reuses the application fixture; only the tests below run here."""


    async def view(self, game, actor):
        async with self.db.transaction() as session:
            return await self.service(session).get_view(account_id=actor, game_id=game)


    async def test_view_does_not_wait_for_a_writer_lock(self):
        game, *_ = await self.running()
        await self.view(game, self.owner)
        async with self.db.transaction() as writer:
            from storage.night_cases import NightCaseRepository
            self.assertIsNotNone(await NightCaseRepository(writer).lock_game(game))
            view = await asyncio.wait_for(self.view(game, self.accounts[1]), 5)
        self.assertEqual(view['game_id'], game)


    async def test_view_retries_under_share_lock_when_revision_moves(self):
        game, *_ = await self.running()
        command = await self.player_command(game, self.owner, 'seen')
        calls = []

        async with self.db.transaction() as session:
            service = self.service(session)
            original = service._view

            async def racing(*args, snapshot, **kwargs):
                calls.append(snapshot)
                result = await original(*args, snapshot=snapshot, **kwargs)
                if snapshot:  # a writer commits between the state read and the revision check
                    async with self.db.transaction() as other:
                        await self.service(other).execute(account_id=self.owner, game_id=game, command=command)
                return result

            service._view = racing
            view = await service.get_view(account_id=self.owner, game_id=game)
        self.assertEqual(calls, [True, False])
        self.assertEqual(view['self']['actor_seq'], command['actor_seq'] + 1)


    async def test_cached_projection_is_not_shared_with_callers(self):
        game, *_ = await self.running()
        first = await self.view(game, self.owner)
        first['public']['npcs'].clear(); first['self']['location'] = 'tampered'
        first['public']['clock']['phase'] = 'tampered'
        second = await self.view(game, self.owner)
        self.assertTrue(second['public']['npcs'])
        self.assertNotEqual(second['self']['location'], 'tampered')
        self.assertNotEqual(second['public']['clock']['phase'], 'tampered')
        other = await self.view(game, self.accounts[1])
        self.assertNotEqual(other['self']['account_id'], second['self']['account_id'])


    async def test_shared_read_cannot_write(self):
        from storage.night_cases import NightCaseRepository, NightStorageCorruption
        game, *_ = await self.running()
        async with self.db.transaction() as session:
            repo = NightCaseRepository(session)
            for mode in ({'shared': True}, {'snapshot': True}):
                locked = await repo.lock_game(game, **mode)
                assert locked is not None
                with self.assertRaises(NightStorageCorruption):
                    await repo.write_snapshot(locked, expected_storage_revision=locked.sealed.storage_revision,
                                              kernel=locked.sealed.kernel, lobby=None,
                                              snapshot_hash=locked.sealed.snapshot_hash, lifecycle='running')


# Only the tests defined above run here; the inherited fixture's own tests run in their module.
for _name in [n for n in dir(NightApplicationPostgresTests) if n.startswith('test_') and n not in vars(NightReadPathPostgresTests)]:
    setattr(NightReadPathPostgresTests, _name, None)
del NightApplicationPostgresTests
