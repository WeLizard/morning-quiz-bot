"""Scene pictures of case events and per-variant finales (format v2, Manor case, projection)."""
import copy
import json
import unittest
from pathlib import Path

import hashlib
import tempfile

from application import night_art
from application.night_case import NightCaseError, _art_binding, _reveal_finale
from domain.night_case_projection import project
from domain.night_case_simulation import DEFAULT_START, SearchBudget, _Runner
from domain.night_case_state import PlayerActor, rules_snapshot
from domain.night_case_v2_format import CaseV2Error, compile_v2, load_v2

ROOT = Path(__file__).resolve().parents[1]
RAW = json.loads((ROOT / 'content/night_city/manor_lake.case.json').read_text(encoding='utf-8'))
CASE = compile_v2(load_v2((ROOT / 'content/night_city/manor_lake.case.json').read_bytes()))
RULES = rules_snapshot('Europe/Berlin')


def compiled(doc):
    return compile_v2(load_v2(json.dumps(doc, ensure_ascii=False).encode('utf-8')))


def finished(variant_id):
    """Everyone only checks in: the week ends unresolved and the variant finale is revealed."""
    runner = _Runner(CASE, RULES, 'manor_5', variant_id, 3, SearchBudget(), DEFAULT_START)
    while runner.final_code() is None:
        doc = runner.transition.state.document()
        account = next((p['account_id'] for p in doc['players'] if p['status'] == 'active'
                        and p['last_seen_window'] != doc['clock']['window_idx']), None)
        if account and runner.choice(account, 'seen', {}):
            break
        if runner.tick():
            break
    return runner


class SceneArtFormatTests(unittest.TestCase):
    def test_manor_events_and_variants_name_their_own_scene_assets(self):
        for group in ('events', 'variants'):
            self.assertEqual(len(RAW[group]), 6 if group == 'events' else 3)
            for entry in RAW[group]:
                self.assertEqual(entry['art']['asset_id'], 'manor_scene_' + entry['id'])
                self.assertTrue(entry['art']['alt'])

    def test_art_is_optional_and_strict(self):
        doc = copy.deepcopy(RAW)
        doc['events'][0].pop('art'); doc['variants'][0].pop('art')
        compiled(doc)
        doc = copy.deepcopy(RAW)
        doc['events'][0]['art']['url'] = 'x.webp'
        with self.assertRaises(CaseV2Error):
            compiled(doc)

    def test_scene_asset_cannot_reuse_a_portrait_place_or_other_scene(self):
        for other in (RAW['characters'][0]['art']['asset_id'], RAW['locations'][0]['art']['asset_id'],
                      RAW['characters'][0]['looks'][1]['art']['asset_id'], RAW['events'][1]['art']['asset_id']):
            doc = copy.deepcopy(RAW)
            doc['events'][0]['art']['asset_id'] = other
            with self.assertRaises(CaseV2Error) as caught:
                compiled(doc)
            self.assertEqual(caught.exception.issue.code, 'v2.art')
        doc = copy.deepcopy(RAW)
        doc['variants'][0]['art']['asset_id'] = RAW['events'][0]['art']['asset_id']
        with self.assertRaises(CaseV2Error):
            compiled(doc)


class SceneArtProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = finished('variant_b')
        cls.state = cls.runner.transition.state

    def test_every_fired_event_scene_carries_its_picture(self):
        public = project(CASE, RULES, self.state)
        scenes = [e for e in public['chronicle'] if e['kind'] == 'scene']
        by_event = {e['id']: e['art'] for e in RAW['events']}
        self.assertLessEqual(set(by_event), {e['payload']['content_event_id'] for e in scenes})
        for entry in scenes:
            # Module scenes (turning point) have no picture of their own.
            self.assertEqual(entry.get('art'), by_event.get(entry['payload']['content_event_id']))
        self.assertFalse(any('art' in e for e in public['chronicle'] if e['kind'] != 'scene'))
        self.assertNotIn('art', self.state.document()['public']['chronicle'][0])

    def test_finale_shows_only_the_played_variant_picture(self):
        self.assertEqual(self.runner.final_code(), 'unresolved')
        expected = next(v['art'] for v in RAW['variants'] if v['id'] == 'variant_b')
        for player in self.state.document()['players']:
            postmortem = project(CASE, RULES, self.state, PlayerActor(player['account_id']))['self']['postmortem']
            self.assertEqual(postmortem['variant_art'], expected)
        self.assertNotIn('variant_art', json.dumps(project(CASE, RULES, self.state)['final'] or {}))

    def test_running_game_reveals_no_finale_picture(self):
        runner = _Runner(CASE, RULES, 'manor_5', 'variant_c', 3, SearchBudget(), DEFAULT_START)
        state = runner.transition.state
        account = state.document()['players'][0]['account_id']
        view = project(CASE, RULES, state, PlayerActor(account))
        self.assertNotIn('postmortem', view['self'])
        self.assertNotIn('manor_scene_variant', json.dumps(view, ensure_ascii=False))


class SealedFinaleBindingTests(unittest.TestCase):
    META = {'world': 'manor_lake', 'style_pack': 'noir_print_a'}
    BASE = {'schema': 'night-art-binding/1', 'world': 'manor_lake', 'style_pack': 'noir_print_a', 'manifest_sha256': 'a' * 64}

    def test_binding_has_no_hand_made_sealed_map(self):
        public = _art_binding({'art': self.BASE}, self.META)
        self.assertEqual(set(public), {'manifest_sha256', 'manifest_url'})
        with self.assertRaises(NightCaseError):
            _art_binding({'art': {**self.BASE, 'sealed': {'manor_scene_variant_b': 'b' * 64}}}, self.META)

    def test_game_finds_pack_and_sealed_pictures_by_itself(self):
        case_hash, manifest = 'c' * 64, 'a' * 64
        with tempfile.TemporaryDirectory(dir=r'F:\Temp') as raw:
            root = Path(raw)
            self.assertIsNone(night_art.binding_for_case(self.META, case_hash, root))
            payload = b'finale'
            digest = hashlib.sha256(payload).hexdigest()
            (root / f'{digest}.webp').write_bytes(payload)
            (root / f'case-{case_hash}.json').write_text(json.dumps({'schema': 'nc-case-art/1', 'world': 'manor_lake',
                'style_pack': 'noir_print_a', 'case_content_hash': case_hash, 'manifest_sha256': manifest}))
            (root / f'pack-{manifest}-case-{case_hash}.json').write_text(json.dumps({'schema': 'nc-pack-index/1',
                'world': 'manor_lake', 'style_pack': 'noir_print_a', 'case_content_hash': case_hash, 'manifest_sha256': manifest,
                'sealed': {'manor_scene_variant_b': digest, 'manor_scene_variant_c': 'd' * 64}}))
            self.assertEqual(night_art.binding_for_case(self.META, case_hash, root), self.BASE)
            self.assertIsNone(night_art.binding_for_case({**self.META, 'world': 'other'}, case_hash, root))
            self.assertIsNone(night_art.binding_for_case(self.META, 'e' * 64, root))
            # Only pictures whose bytes are on disk under their own hash are revealed.
            self.assertEqual(night_art.sealed_pictures(manifest, case_hash, root), {'manor_scene_variant_b': digest})
            self.assertEqual(night_art.sealed_pictures(manifest, 'e' * 64, root), {})
            self.assertEqual(night_art.sealed_pictures('../x', case_hash, root), {})

    def test_only_a_revealed_postmortem_gets_the_sealed_address(self):
        sealed = {'manor_scene_variant_b': 'b' * 64}
        own = {'postmortem': {'variant_art': {'asset_id': 'manor_scene_variant_b', 'alt': 'x'}}}
        _reveal_finale(own, sealed)
        self.assertEqual(own['postmortem']['variant_art'], {'asset_id': 'manor_scene_variant_b', 'alt': 'x', 'url': f"/app/night/sealed/{'b' * 64}.webp"})
        unknown = {'postmortem': {'variant_art': {'asset_id': 'manor_scene_variant_c', 'alt': 'x'}}}
        _reveal_finale(unknown, sealed)
        self.assertIsNone(unknown['postmortem']['variant_art'])
        for own in ({}, {'postmortem': {'variant_art': None}}):
            before = copy.deepcopy(own)
            _reveal_finale(own, sealed)
            self.assertEqual(own, before)
