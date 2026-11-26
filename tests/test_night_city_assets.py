"""Reproducibility and public-boundary checks for the Manor Lake asset export."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / 'scripts/art/night_city/build_world_pack.py'
SCHEMA = ROOT / 'scripts/art/night_city/assets_manifest.schema.json'
IMMUTABLE_SCHEMA = ROOT / 'scripts/art/night_city/immutable_assets_manifest.schema.json'
CASE = ROOT / 'content/night_city/manor_lake.case.json'
ART = ROOT / 'docs/tasks/night_city/art_batch2/noir_print_a'
PINNED_CASE_HASH = '4c8a5f882beafd02104d0a623aec3996cf9dec8b9677b42103fa383add717728'


def case_art_refs(groups=('characters', 'locations', 'events', 'items')):
    """Read only public art IDs and alt text; never include case prose in the manifest.

    Per-variant finales ('variants') are sealed: never in the public manifest or folder."""
    case = json.loads(CASE.read_text(encoding='utf-8'))
    refs = {}
    for group in groups:
        for entry in case[group]:
            # Appearance looks add portraits; the first look is the top-level art itself.
            for art in [entry.get('art') or {}] + [look['art'] for look in entry.get('looks', [])[1:]]:
                refs[art.get('asset_id')] = {'group': group, 'id': entry.get('id'), 'alt': art.get('alt')}
    return refs


LOOK_ASSETS = {
    'manor_char_doctor__f61', 'manor_char_cook__f45', 'manor_char_photographer__f30',
    'manor_char_investigator__m44', 'manor_char_gardener__m63',
}


class ManorAssetExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ART.is_dir():
            raise unittest.SkipTest(f'optional Manor raw art inputs are absent: {ART}')
        cls.temp = tempfile.TemporaryDirectory(prefix='mqb-manor-assets-')
        cls.out = Path(cls.temp.name) / 'manor_lake'
        cls.report_path = Path(cls.temp.name) / 'asset_hash_report.json'
        cls.packs = Path(cls.temp.name) / 'packs'
        cls.sealed = Path(cls.temp.name) / 'sealed'
        env = os.environ.copy()
        env['TEMP'] = env['TMP'] = r'F:\Temp'
        subprocess.run([
            sys.executable, '-I', str(BUILDER), '--assets-only',
            '--assets-out', str(cls.out), '--report-out', str(cls.report_path), '--sealed-out', str(cls.sealed),
        ], cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        subprocess.run([
            sys.executable, '-I', str(BUILDER), '--immutable-only',
            '--assets-out', str(cls.out), '--immutable-out', str(cls.packs), '--sealed-out', str(cls.sealed),
            '--report-out', str(cls.report_path), '--compare-assets', str(cls.out / 'assets'),
        ], cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        cls.manifest = json.loads((cls.out / 'assets.json').read_text(encoding='utf-8'))
        cls.report = json.loads(cls.report_path.read_text(encoding='utf-8'))
        cls.schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
        errors = sorted(Draft202012Validator(cls.schema).iter_errors(cls.manifest), key=lambda error: list(error.path))
        if errors:
            raise AssertionError('; '.join(error.message for error in errors))
        cls.immutable_schema = json.loads(IMMUTABLE_SCHEMA.read_text(encoding='utf-8'))
        cls.immutable_path = cls.packs / cls.report['immutable_manifest_sha256']
        cls.immutable_bytes = (cls.immutable_path / 'assets.json').read_bytes()
        cls.immutable_manifest = json.loads(cls.immutable_bytes.decode('utf-8'))
        errors = sorted(
            Draft202012Validator(cls.immutable_schema).iter_errors(cls.immutable_manifest),
            key=lambda error: list(error.path),
        )
        if errors:
            raise AssertionError('; '.join(error.message for error in errors))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_manifest_uses_only_case_art_ids_and_public_alt(self):
        refs = case_art_refs()
        self.assertEqual(set(self.manifest), {'schema', 'world', 'assets'})
        self.assertEqual(self.manifest['schema'], 'nc-assets/1')
        self.assertEqual(self.manifest['world'], 'manor_lake')
        self.assertEqual(set(self.manifest['assets']), set(refs))
        self.assertEqual(len(refs), 93)
        self.assertLessEqual(LOOK_ASSETS, set(refs))
        for asset_id, value in self.manifest['assets'].items():
            self.assertEqual(value['alt'], refs[asset_id]['alt'])
            self.assertNotIn('.png', value['alt'].lower())
            self.assertNotIn('noir_print_a', value['alt'].lower())
            self.assertNotIn('source', value)
            self.assertNotIn('case', value)
            for url in [value['url'], *value.get('variants', {}).values()]:
                self.assertRegex(url, r'^/app/night/worlds/manor_lake/assets/[a-z0-9_]+\.webp$')
                self.assertTrue((self.out / 'assets' / url.split('/assets/', 1)[1]).is_file())

    def test_look_portraits_come_from_characters_variants_not_characters(self):
        self.assertFalse(list((ART / 'characters').glob('*__*.png')), 'look portraits must stay out of characters/')
        listed = {row['file'] for row in json.loads((ART / 'characters_variants/manifest.json').read_text(encoding='utf-8'))['variants']}
        refs = case_art_refs()
        sources = {row['asset_id']: row['source'] for row in self.report['assets'] if row['asset_id']}
        for asset_id in LOOK_ASSETS:
            role, look = asset_id.removeprefix('manor_char_').split('__')
            value = self.manifest['assets'][asset_id]
            self.assertEqual(value['alt'], refs[asset_id]['alt'])
            self.assertTrue(value['url'].endswith(f'/character_{role}__{look}.webp'))
            self.assertNotIn('variants', value)
            folder, name = sources[asset_id].rsplit('/', 1)
            self.assertTrue(folder.endswith('characters_variants'), sources[asset_id])
            self.assertIn(name, listed)

    def test_scenes_are_single_pictures_from_scenes_events(self):
        refs = case_art_refs()
        sources = {row['asset_id']: row['source'] for row in self.report['assets'] if row['asset_id']}
        scenes = {key: ref for key, ref in refs.items() if ref['group'] == 'events'}
        self.assertEqual(len(scenes), 6)
        for asset_id, ref in scenes.items():
            self.assertEqual(asset_id, f"manor_scene_{ref['id']}")
            value = self.manifest['assets'][asset_id]
            self.assertEqual(value['alt'], ref['alt'])
            self.assertTrue(value['url'].endswith(f"/scene_{ref['id']}.webp"))
            self.assertNotIn('variants', value)
            self.assertEqual(sources[asset_id].rsplit('/', 1), [f'noir_print_a/scenes_events', f"scene_{ref['id']}.png"])

    def test_variant_finales_are_sealed_out_of_every_public_place(self):
        finales = case_art_refs(('variants',))
        self.assertEqual(len(finales), 5)
        sealed = self.report['sealed']
        self.assertEqual(set(sealed), set(finales))
        manifest_sha, case_hash = self.report['immutable_manifest_sha256'], self.report['case_canonical_sha256']
        self.assertEqual({path.name for path in self.sealed.iterdir()}, {digest + '.webp' for digest in sealed.values()}
                         | {f'case-{case_hash}.json', f'pack-{manifest_sha}-case-{case_hash}.json'})
        # The game finds the pack and the finales itself, from the published index.
        from application import night_art
        meta = json.loads(CASE.read_text(encoding='utf-8'))['meta']
        self.assertEqual(night_art.binding_for_case(meta, case_hash, self.sealed),
                         {'schema': 'night-art-binding/1', 'world': 'manor_lake', 'style_pack': meta['style_pack'],
                          'manifest_sha256': manifest_sha})
        self.assertEqual(night_art.sealed_pictures(manifest_sha, case_hash, self.sealed), sealed)
        self.assertEqual(night_art.sealed_pictures(manifest_sha, 'f' * 64, self.sealed), {})
        for row in self.report['sealed_assets']:
            path = self.sealed / (row['export_sha256'] + '.webp')
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), sealed[row['asset_id']])
            self.assertEqual(row['export'], f"/app/night/sealed/{sealed[row['asset_id']]}.webp")
            self.assertEqual(row['source'], f"noir_print_a/scenes_events/scene_final_{finales[row['asset_id']]['id']}.png")
        public = [(self.out / 'assets.json').read_text(encoding='utf-8'), self.immutable_bytes.decode('utf-8')]
        public += [path.name for path in (self.out / 'assets').iterdir()] + [path.name for path in (self.immutable_path / 'assets').iterdir()]
        for text in public:
            self.assertNotIn('scene_final', text)
            self.assertNotIn('manor_scene_variant', text)
            for digest in sealed.values():
                self.assertNotIn(digest, text)
        public_hashes = {row['export_sha256'] for row in self.report['assets']}
        self.assertFalse(public_hashes & set(sealed.values()))

    def test_places_have_day_default_and_four_same_world_variants(self):
        refs = case_art_refs()
        place_ids = {key for key, ref in refs.items() if ref['group'] == 'locations'}
        self.assertEqual(len(place_ids), 8)
        for asset_id in place_ids:
            value = self.manifest['assets'][asset_id]
            self.assertEqual(set(value['variants']), {'morning', 'day', 'evening', 'night'})
            self.assertEqual(value['url'], value['variants']['day'])

    def test_all_source_images_are_accounted_for_and_hashes_match(self):
        records = self.report['assets']
        self.assertEqual(self.report['manifest_count'], 93)
        self.assertEqual(self.report['character_count'], 20)
        self.assertEqual(self.report['look_count'], 20)
        self.assertEqual(self.report['location_variant_count'], 32)
        self.assertEqual(self.report['scene_count'], 6)
        self.assertEqual(self.report['item_count'], 39)
        self.assertEqual(len(records), 117)
        self.assertLessEqual(self.report['item_bytes'], 10_000_000)
        self.assertEqual(
            hashlib.sha256((self.out / 'assets.json').read_bytes()).hexdigest(),
            self.report['manifest_sha256'],
        )
        self.assertTrue(all(row['source_alpha'] == row['export_alpha'] for row in records))
        self.assertEqual(sum(row['bytes'] for row in records), self.report['total_export_bytes'])
        for row in records:
            src = ART.parent / row['source']
            exported = self.out / row['export']
            self.assertTrue(src.is_file(), row['source'])
            self.assertTrue(exported.is_file(), row['export'])
            self.assertEqual(hashlib.sha256(src.read_bytes()).hexdigest(), row['source_sha256'])
            self.assertEqual(hashlib.sha256(exported.read_bytes()).hexdigest(), row['export_sha256'])

    def test_immutable_manifest_is_canonical_content_address_and_has_all_file_hashes(self):
        encoded = json.dumps(
            self.immutable_manifest, ensure_ascii=False, sort_keys=True,
            separators=(',', ':'), allow_nan=False,
        ).encode('utf-8')
        digest = hashlib.sha256(encoded).hexdigest()
        self.assertEqual(encoded, self.immutable_bytes)
        self.assertEqual(digest, self.immutable_path.name)
        self.assertEqual(digest, self.report['immutable_manifest_sha256'])
        self.assertEqual(self.report['public_manifest_url'], f'/app/night/packs/{digest}/assets.json')
        self.assertEqual(self.report['legacy_webp_comparison']['identical'], True)
        self.assertEqual(set(self.report['encoder']), {'python', 'pillow', 'libwebp'})
        self.assertEqual(set(self.immutable_manifest), {'schema', 'world', 'files', 'assets'})
        self.assertEqual(self.immutable_manifest['schema'], 'nc-assets/2')
        self.assertEqual(set(self.immutable_manifest['files']), {
            f'assets/{path.name.lower()}' for path in (self.out / 'assets').glob('*.webp')
        })
        self.assertEqual(len(self.immutable_manifest['files']), 117)  # 20 portraits, 32 place times, 39 items, 26 looks and scenes
        self.assertEqual(set(self.immutable_manifest['assets']), set(case_art_refs()))
        self.assertNotIn(digest, json.dumps(self.immutable_manifest, ensure_ascii=False))
        for relative, expected_hash in self.immutable_manifest['files'].items():
            self.assertRegex(relative, r'^assets/[a-z0-9_]+\.webp$')
            self.assertEqual(
                hashlib.sha256((self.immutable_path / relative).read_bytes()).hexdigest(),
                expected_hash,
            )
        for asset in self.immutable_manifest['assets'].values():
            paths = [asset['url'], *asset.get('variants', {}).values()]
            self.assertTrue(all(path in self.immutable_manifest['files'] for path in paths))

    def test_repeat_publish_reuses_identical_pack(self):
        env = os.environ.copy()
        env['TEMP'] = env['TMP'] = r'F:\Temp'
        result = subprocess.run([
            sys.executable, '-I', str(BUILDER), '--immutable-only',
            '--assets-out', str(self.out), '--immutable-out', str(self.packs), '--sealed-out', str(self.sealed),
            '--report-out', str(self.report_path), '--compare-assets', str(self.out / 'assets'),
        ], cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        self.assertIn('reused', result.stdout)
        self.assertEqual((self.immutable_path / 'assets.json').read_bytes(), self.immutable_bytes)

    def test_existing_digest_directory_with_foreign_bytes_is_never_overwritten(self):
        fake_root = Path(self.temp.name) / 'foreign-packs'
        fake = fake_root / self.immutable_path.name
        (fake / 'assets').mkdir(parents=True)
        foreign_file = fake / 'assets/character_housekeeper.webp'
        foreign_file.write_bytes(b'foreign owner data')
        result = subprocess.run([
            sys.executable, '-I', str(BUILDER), '--immutable-only',
            '--assets-out', str(self.out), '--immutable-out', str(fake_root), '--sealed-out', str(self.sealed),
            '--report-out', str(self.report_path),
        ], cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(foreign_file.read_bytes(), b'foreign owner data')
        self.assertFalse((fake / 'assets.json').exists())

    def test_external_and_traversal_legacy_urls_are_rejected(self):
        bad_out = Path(self.temp.name) / 'bad-legacy'
        shutil.copytree(self.out / 'assets', bad_out / 'assets')
        original = json.loads((self.out / 'assets.json').read_text(encoding='utf-8'))
        invalid_urls = ('https://example.invalid/x.webp', '/app/night/worlds/manor_lake/../../x.webp')
        for index, invalid in enumerate(invalid_urls):
            variant_out = Path(self.temp.name) / f'bad-legacy-{index}'
            shutil.copytree(bad_out, variant_out)
            bad_manifest = json.loads(json.dumps(original))
            bad_manifest['assets'][next(iter(bad_manifest['assets']))]['url'] = invalid
            (variant_out / 'assets.json').write_text(
                json.dumps(bad_manifest, ensure_ascii=False, indent=2), encoding='utf-8',
            )
            packs = Path(self.temp.name) / f'bad-packs-{index}'
            result = subprocess.run([
                sys.executable, '-I', str(BUILDER), '--immutable-only',
                '--assets-out', str(variant_out), '--immutable-out', str(packs), '--sealed-out', str(self.sealed),
                '--report-out', str(self.report_path),
            ], cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(packs.exists())

    def test_pinned_case_version_and_hash(self):
        case = json.loads(CASE.read_text(encoding='utf-8'))
        canonical = json.dumps(case, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
        self.assertEqual(case['meta']['version'], 5)
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), PINNED_CASE_HASH)


class ImmutableManifestPureContractTests(unittest.TestCase):
    """Keep manifest/path/hash contract coverage runnable without the ignored raw art archive."""

    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(IMMUTABLE_SCHEMA.read_text(encoding='utf-8'))

    def valid_manifest(self):
        return {
            'schema': 'nc-assets/2',
            'world': 'manor_lake',
            'files': {'assets/portrait.webp': 'a' * 64},
            'assets': {
                'manor_char_doctor': {'url': 'assets/portrait.webp', 'alt': 'Портрет врача'},
            },
        }

    def test_small_synthetic_manifest_is_valid_and_canonical_hash_is_stable(self):
        manifest = self.valid_manifest()
        encoded = json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False,
        ).encode('utf-8')
        Draft202012Validator(self.schema).validate(manifest)
        changed = self.valid_manifest()
        changed['assets']['manor_char_doctor']['alt'] = 'Другой alt'
        changed_encoded = json.dumps(
            changed, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False,
        ).encode('utf-8')
        self.assertNotEqual(hashlib.sha256(encoded).hexdigest(), hashlib.sha256(changed_encoded).hexdigest())

    def test_missing_optional_art_inputs_skip_only_the_build_dependent_class(self):
        from unittest.mock import patch
        missing = Path(tempfile.gettempdir()) / 'mqb-art-intentionally-missing'
        self.assertFalse(missing.exists())
        with patch(__name__ + '.ART', missing):
            with self.assertRaisesRegex(unittest.SkipTest, 'optional Manor raw art inputs are absent'):
                ManorAssetExportTests.setUpClass()

    def test_synthetic_manifest_rejects_unsafe_paths_and_bad_hashes(self):
        for path in ('../portrait.webp', 'assets/../portrait.webp', 'https://example.invalid/a.webp'):
            manifest = self.valid_manifest()
            manifest['assets']['manor_char_doctor']['url'] = path
            with self.subTest(path=path), self.assertRaises(ValidationError):
                Draft202012Validator(self.schema).validate(manifest)
        for digest in ('not-a-hash', 'A' * 64):
            manifest = self.valid_manifest()
            manifest['files']['assets/portrait.webp'] = digest
            with self.subTest(digest=digest), self.assertRaises(ValidationError):
                Draft202012Validator(self.schema).validate(manifest)


if __name__ == '__main__':
    unittest.main()
