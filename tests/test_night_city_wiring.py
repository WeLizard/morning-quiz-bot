"""Wiring guard of Night City (MQB-012, stage 0).

Everything made for the game must reach the player: every world has a sound pack and a case, every art id
of a registered case is in its pack, every file of a pack is in its manifest, the client draws every group
of the pack, and no Night City text says «мафия».

The guard computes the list of gaps and compares it with KNOWN_GAPS below. A new gap fails the test (wire it,
or list it here with a reason). A listed gap that is gone fails too: delete its line, so the list only shrinks.
The client half (which pack groups the case screens draw) is tests/js/night_city_wiring.test.cjs.

World packs, case packs and raw art live outside git (.git/info/exclude); without them the asset checks skip.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NIGHT = ROOT / 'web/mini_client/night'
CASES = ROOT / 'content/night_city'

# Worlds with no case yet: MQB-012 stages 7 and 8. The list only shrinks.
CASES_BEING_WRITTEN = {
    'night_express': 'draft 02, needs outsider and final_questions (MQB-012 stage 7)',
    'black_bay': 'draft 03, needs secret_identity and final_questions (stage 7)',
    'newsprint_city': 'draft 04, needs efficiency and cipher (stage 7)',
    'palace_masks': 'draft 05, needs expert, refutation, secret_identity (stage 7)',
    'polar_star': 'draft 06, needs survival_clock, victim_clock, final_questions (stage 7)',
    'circus': 'draft 07, needs expert (stage 7)',
    'campus': 'draft 08, needs expert (stage 7)',
    'prohibition': 'draft 09, needs secret_identity, outsider, victim_clock (stage 7)',
    'sand_city': 'draft 10, needs sanity and cipher (stage 7)',
    'neon_city': 'draft 11, needs cipher (stage 7)',
    'deep_choir': '16+, only the premise; content limits are the owner\'s call (stage 8, question B5)',
    'dead_air': '16+, only the premise (stage 8, B5)',
    'velvet_circle': '18+, only the premise (stage 8, B5)',
    'eternal_hotel': '18+, only the premise (stage 8, B5)',
}

# Known gaps on 2026-11-26 (after Manor v5), matching MQB-012 §1.3. Each line goes when its gap is wired.
KNOWN_GAPS = {
    # §1.3 item 6: time-of-day place maps are not built for any world pack (build_world_pack.py --places).
    **{f'world:{w}:places_not_built': 'MQB-012 §1.3.6' for w in (
        'manor_lake', 'night_express', 'black_bay', 'newsprint_city', 'palace_masks', 'polar_star', 'circus',
        'campus', 'sand_city', 'neon_city', 'prohibition', 'deep_choir', 'dead_air', 'velvet_circle',
        'eternal_hotel')},
    # §1.3 item 8: old case packs no current case binds to; deleting them is the owner's call (B3).
    # 701d7ecb is the Manor v4 pack; the mockups in docs/design/mockups/night-case still draw from it.
    'pack:701d7ecb:unbound': 'MQB-012 §1.3.8, question B3',
    'pack:0e56e5e8:unbound': 'MQB-012 §1.3.8, question B3',
    'pack:0e6305c9:unbound': 'MQB-012 §1.3.8, question B3',
    'pack:a640e3af:unbound': 'MQB-012 §1.3.8, question B3',
    # The prototype (removed in stage 12) and the group Mafia game still say «мафия».
    'text:мафия:web/mini_client/night-city-ui.js': 'prototype v1, removed after its components move (stage 1, 12)',
    'text:мафия:handlers/mafia_handlers.py': 'owner decision: remove the word from the game (§1.4)',
    'text:мафия:web/mini_app.py': 'owner decision: remove the word from the game (§1.4)',
}

# Player-facing Night City sources searched for «мафия».
TEXT_SOURCES = ['web/mini_client/night-case-ui.js', 'web/mini_client/night-city-ui.js', 'web/mini_client/night-case.css',
                'web/mini_client/index.html', 'web/mini_app.py',
                'handlers/mafia_handlers.py']
MAFIA = re.compile('мафи', re.IGNORECASE)


def _json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def case_files():
    return sorted(CASES.glob('*.case.json'))


def case_hash(path: Path) -> str:
    from domain.night_case_v2_format import compile_v2, load_v2
    return compile_v2(load_v2(path.read_bytes())).content_hash


def case_art_ids(case: dict) -> tuple[set[str], set[str]]:
    """(public asset ids, sealed asset ids) a case refers to; variant finales are sealed."""
    public, sealed = set(), set()
    for group in ('characters', 'locations', 'events'):
        for entry in case.get(group, []):
            for art in [entry.get('art') or {}] + [look.get('art') or {} for look in entry.get('looks', [])]:
                if art.get('asset_id'):
                    public.add(art['asset_id'])
    for entry in case.get('items', []):
        if (entry.get('art') or {}).get('asset_id'):
            public.add(entry['art']['asset_id'])
    for variant in case.get('variants', []):
        if (variant.get('art') or {}).get('asset_id'):
            sealed.add(variant['art']['asset_id'])
    return public, sealed


def world_gaps() -> set[str]:
    gaps = set()
    index = _json(NIGHT / 'worlds/index.json')
    worlds = {w['id'] for w in index['worlds']}
    with_case = {_json(p)['meta'].get('world') for p in case_files()}
    for world in sorted(worlds):
        folder = NIGHT / 'worlds' / world
        pack_path = folder / 'pack.json'
        if not pack_path.is_file():
            gaps.add(f'world:{world}:no_pack')
            continue
        pack = _json(pack_path)
        if pack.get('schema') != 'nc-world-pack/1' or pack.get('id') != world:
            gaps.add(f'world:{world}:bad_pack')
        for name in pack.get('files', {}):
            if not (folder / name).is_file():
                gaps.add(f'world:{world}:missing_file:{name}')
        if not (folder / str(pack.get('thumb'))).is_file():
            gaps.add(f'world:{world}:no_thumb')
        music = pack.get('music') or {}
        for slot in ('day', 'night', 'finale'):
            entry = music.get(slot)
            file = entry.get('file') if isinstance(entry, dict) else entry
            if not file or not (folder / file).is_file():
                gaps.add(f'world:{world}:no_music:{slot}')
        places = pack.get('places') or {}
        if not places or any(v is None for place in places.values() for v in (place.get('times') or {None: None}).values()):
            gaps.add(f'world:{world}:places_not_built')
        if world not in with_case and world not in CASES_BEING_WRITTEN:
            gaps.add(f'world:{world}:no_case')
    return gaps


def pack_gaps() -> set[str]:
    gaps, bound = set(), set()
    for path in case_files():
        case = _json(path)
        content_hash = case_hash(path)
        pointer_path = NIGHT / 'sealed' / f'case-{content_hash}.json'
        cid = case['meta']['id']
        if not pointer_path.is_file():
            gaps.add(f'case:{cid}:no_pack')
            continue
        sha = _json(pointer_path)['manifest_sha256']
        bound.add(sha)
        manifest = _json(NIGHT / 'packs' / sha / 'assets.json')
        index_path = NIGHT / 'sealed' / f'pack-{sha}-case-{content_hash}.json'
        sealed = _json(index_path).get('sealed', {}) if index_path.is_file() else {}
        public_ids, sealed_ids = case_art_ids(case)
        for asset_id in sorted(public_ids - set(manifest['assets'])):
            gaps.add(f'case:{cid}:asset_not_in_pack:{asset_id}')
        for asset_id in sorted(sealed_ids - set(sealed)):
            gaps.add(f'case:{cid}:sealed_not_in_pack:{asset_id}')
        if not case.get('items'):
            gaps.add(f'case:{cid}:no_items')
    for folder in sorted(p for p in (NIGHT / 'packs').iterdir() if p.is_dir()):
        sha = folder.name
        if sha not in bound:
            gaps.add(f'pack:{sha[:8]}:unbound')
            continue
        # A file counts as listed when an asset of the manifest points at it (hashes alone do not show it).
        manifest = _json(folder / 'assets.json')
        listed = {a.get('url') for a in manifest['assets'].values()}
        listed |= {v for a in manifest['assets'].values() for v in (a.get('variants') or {}).values()}
        for file in sorted((folder / 'assets').iterdir()):
            if f'assets/{file.name}' not in manifest.get('files', {}):
                gaps.add(f'pack:{sha[:8]}:unhashed:{file.name}')
            if f'assets/{file.name}' not in listed:
                gaps.add(f'pack:{sha[:8]}:unlisted:{file.name.split("_", 1)[0]}')
    return gaps


def text_gaps() -> set[str]:
    gaps = set()
    for rel in TEXT_SOURCES:
        path = ROOT / rel
        if path.is_file() and MAFIA.search(path.read_text(encoding='utf-8')):
            gaps.add(f'text:мафия:{rel}')
    for path in case_files():
        if MAFIA.search(path.read_text(encoding='utf-8')):
            gaps.add(f'text:мафия:{path.relative_to(ROOT).as_posix()}')
    for pack in sorted((NIGHT / 'worlds').glob('*/pack.json')) if (NIGHT / 'worlds').is_dir() else []:
        if MAFIA.search(pack.read_text(encoding='utf-8')):
            gaps.add(f'text:мафия:{pack.relative_to(ROOT).as_posix()}')
    return gaps


def assert_gaps(test: unittest.TestCase, found: set[str], prefixes: tuple[str, ...]):
    known = {key for key in KNOWN_GAPS if key.startswith(prefixes)}
    new, gone = sorted(found - known), sorted(known - found)
    test.assertFalse(new, 'not wired (wire it, or list it in KNOWN_GAPS with a reason): ' + ', '.join(new))
    test.assertFalse(gone, 'wired now, delete from KNOWN_GAPS: ' + ', '.join(gone))


class NightCityWiringTests(unittest.TestCase):
    def test_every_world_has_its_pack_music_places_and_a_case_or_a_reason(self):
        if not (NIGHT / 'worlds/index.json').is_file():
            self.skipTest('world packs are outside git and absent here')
        found = world_gaps()
        assert_gaps(self, found, ('world:',))
        index = {w['id'] for w in _json(NIGHT / 'worlds/index.json')['worlds']}
        self.assertEqual(len(index), 15)
        with_case = {_json(p)['meta'].get('world') for p in case_files()}
        self.assertFalse(with_case & set(CASES_BEING_WRITTEN), 'a world got its case: delete it from CASES_BEING_WRITTEN')
        self.assertEqual(index, with_case | set(CASES_BEING_WRITTEN))

    def test_case_art_is_in_its_pack_and_every_pack_file_is_listed(self):
        if not (NIGHT / 'packs').is_dir():
            self.skipTest('case packs are outside git and absent here')
        assert_gaps(self, pack_gaps(), ('case:', 'pack:'))

    def test_no_mafia_in_night_city_texts(self):
        assert_gaps(self, text_gaps(), ('text:',))

    def test_known_gaps_have_reasons(self):
        for key, reason in {**KNOWN_GAPS, **CASES_BEING_WRITTEN}.items():
            self.assertTrue(reason.strip(), key)


if __name__ == '__main__':
    unittest.main()
