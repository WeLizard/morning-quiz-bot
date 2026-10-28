import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.run_admin_preview import seed_photo_catalog
from storage.photos import PhotoCatalog


class AdminPreviewPhotoSeedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        local_root = Path(__file__).resolve().parents[1] / ".local"
        local_root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="test-admin-preview-seed-", dir=local_root)
        self.addCleanup(temporary.cleanup)
        self.temp_root = Path(temporary.name)

    async def test_seed_uses_only_explicit_answer_metadata(self):
        with tempfile.TemporaryDirectory(dir=self.temp_root) as tmp:
            root = Path(tmp)
            image_dir = root / "images"
            image_dir.mkdir()
            (image_dir / "Сова.webp").write_bytes(b"curated image")
            (image_dir / "unlisted.webp").write_bytes(b"no answer metadata")
            (image_dir / f"{'sha256-' + 'a' * 64}.webp").write_bytes(b"content addressed image")
            (image_dir / f"{'sha256-' + 'c' * 64}.webp").write_bytes(b"unmapped content addressed image")
            metadata_path = root / "photo_quiz_metadata.json"
            metadata_path.write_text(json.dumps({
                "Сова": {"correct_answer": "Сова", "hints": {"first_letter": "С"}},
                "sha256-" + "a" * 64: {"correct_answer": "Сова", "hints": {}},
            }, ensure_ascii=False), encoding="utf-8")

            created, patched = [], []

            async def fake_create_photo(database, upload_id, raw, answer, enabled, *, root):
                created.append((upload_id, raw, answer, enabled, root))
                key = f"mqb-upload-{upload_id}-photo"
                return key, {"correct_answer": answer, "display_answer": answer,
                             "enabled": enabled, "hints": {}}, True

            async def fake_patch(self, key, changes, *, expected_version):
                patched.append((key, changes, expected_version))

            with patch("storage.photo_media.create_photo", new=fake_create_photo), \
                    patch.object(PhotoCatalog, "patch", new=fake_patch):
                count = await seed_photo_catalog(None, image_dir, metadata_path, root / "preview")

            self.assertEqual(count, 2)
            self.assertEqual([item[2] for item in created], ["Сова", "Сова"])
            self.assertTrue(all(not item[2].startswith("sha256-") for item in created))
            self.assertEqual(patched[0][1], {"hints": {"first_letter": "С"}})

    async def test_seed_rejects_a_digest_used_as_the_curated_answer(self):
        with tempfile.TemporaryDirectory(dir=self.temp_root) as tmp:
            root = Path(tmp)
            image_dir = root / "images"
            image_dir.mkdir()
            stem = "sha256-" + "b" * 64
            (image_dir / f"{stem}.webp").write_bytes(b"content addressed image")
            metadata_path = root / "photo_quiz_metadata.json"
            metadata_path.write_text(json.dumps({stem: {"correct_answer": stem}}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "image digest"):
                await seed_photo_catalog(None, image_dir, metadata_path, root / "preview")


if __name__ == "__main__":
    unittest.main()
