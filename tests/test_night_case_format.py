"""Boundaries for the untrusted Night City case format."""

import hashlib
import json
import os
import copy
from pathlib import Path
import subprocess
import sys
import unittest

from domain.night_case_format import (
    CaseFormatError,
    canonical_content_hash,
    load_case_bytes,
    validate_case,
    validate_case_file,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "docs/tasks/night_city/example_case.json"
SCHEMA = ROOT / "docs/tasks/night_city/case.schema.json"


class NightCaseFormatTests(unittest.TestCase):
    def test_example_schema_passes_but_publication_remains_blocked(self):
        report = validate_case_file(EXAMPLE)
        self.assertEqual("passed", report.checks["V1"])
        self.assertFalse(report.publishable)
        self.assertEqual("not_checked", report.checks["V2"])
        self.assertEqual("not_checked", report.checks["U10"])
        self.assertEqual(21, len(report.checks))
        self.assertEqual([], list(report.issues))
        self.assertEqual(64, len(report.content_hash))
        self.assertEqual("night-city-validator/0.1", report.validator_version)
        self.assertEqual("schema_and_structure", report.validation_scope)

    def test_schema_valid_broken_home_reference_fails_v1(self):
        document = load_case_bytes(EXAMPLE.read_bytes())
        document["characters"][0]["home"] = "missing_home"
        report = validate_case(document)
        self.assertEqual("failed", report.checks["V1"])
        self.assertTrue(any(issue.code == "V1.refs" and issue.pointer == "/characters/0/home"
                            for issue in report.issues))

    def test_missing_red_herring_debunk_fails_v5_but_keeps_v1_passed(self):
        document = load_case_bytes(EXAMPLE.read_bytes())
        evidence = document["evidence"][0]
        evidence["misleads_toward"] = [document["characters"][0]["id"]]
        evidence.pop("debunked_by", None)
        report = validate_case(document)
        self.assertEqual("passed", report.checks["V1"])
        self.assertEqual("failed", report.checks["V5"])
        self.assertTrue(any(issue.code == "V5.debunk" for issue in report.issues))

    def test_schema_failure_does_not_run_structural_validator(self):
        report = validate_case({})
        self.assertEqual("failed", report.checks["V1"])
        self.assertTrue(any(issue.code == "V1.schema" for issue in report.issues))

    def test_validation_does_not_mutate_document(self):
        document = load_case_bytes(EXAMPLE.read_bytes())
        original = copy.deepcopy(document)
        validate_case(document)
        self.assertEqual(original, document)

    def test_unresolvable_local_schema_reference_returns_report(self):
        document = load_case_bytes(EXAMPLE.read_bytes())
        schema = json.loads(SCHEMA.read_text(encoding="utf-8-sig"))
        schema["properties"]["schema"] = {"$ref": "#/$defs/missing"}
        report = validate_case(document, schema=schema)
        self.assertEqual("failed", report.checks["V1"])
        self.assertTrue(any(issue.code == "invalid_schema" for issue in report.issues))

    def test_deep_or_oversized_schema_returns_report(self):
        document = load_case_bytes(EXAMPLE.read_bytes())
        base = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "night-city-case/1"}
        deep_schema = dict(base)
        node = deep_schema
        for _ in range(70):
            child = {}
            node["x"] = child
            node = child
        oversized_schema = dict(base, x=[None] * 100_001)
        for schema in (deep_schema, oversized_schema):
            with self.subTest(schema_size=len(schema.get("x", []))):
                report = validate_case(document, schema=schema)
                self.assertEqual("failed", report.checks["V1"])
                self.assertTrue(any(issue.code == "invalid_schema" for issue in report.issues))

    def test_hash_sorts_object_keys_but_preserves_array_order(self):
        first = {"b": [{"z": 1, "a": "я"}, 2], "a": True}
        reordered = {"a": True, "b": [{"a": "я", "z": 1}, 2]}
        swapped = {"b": [2, {"z": 1, "a": "я"}], "a": True}
        self.assertEqual(canonical_content_hash(first), canonical_content_hash(reordered))
        self.assertNotEqual(canonical_content_hash(first), canonical_content_hash(swapped))
        canonical = json.dumps(first, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        self.assertEqual(hashlib.sha256(canonical.encode("utf-8")).hexdigest(), canonical_content_hash(first))

    def test_loader_accepts_utf8_bom_and_rejects_invalid_text(self):
        self.assertEqual({"a": 1}, load_case_bytes(b"\xef\xbb\xbf{\"a\":1}"))
        for raw in (b"\xff", b"\xff\xfe{\x00}", b"{", b"{} trailing"):
            with self.subTest(raw=raw), self.assertRaises(CaseFormatError):
                load_case_bytes(raw)

    def test_loader_rejects_duplicate_keys_and_nonfinite_numbers(self):
        for raw in (b'{"a":1,"a":2}', b'{"outer":{"a":1,"a":2}}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}', b'{"x":1e999}'):
            with self.subTest(raw=raw), self.assertRaises(CaseFormatError):
                load_case_bytes(raw)

    def test_loader_enforces_file_depth_and_node_limits(self):
        with self.assertRaises(CaseFormatError) as caught:
            load_case_bytes(b"{}", max_bytes=1)
        self.assertEqual("file_too_large", caught.exception.issue.code)
        with self.assertRaises(CaseFormatError) as caught:
            load_case_bytes(b'{"a":{"b":1}}', max_depth=2)
        self.assertEqual("depth_limit", caught.exception.issue.code)
        with self.assertRaises(CaseFormatError) as caught:
            load_case_bytes(b'{"a":[1,2,3]}', max_nodes=3)
        self.assertEqual("node_limit", caught.exception.issue.code)

    def test_unknown_case_schema_and_invalid_fields_fail_v1(self):
        document = load_case_bytes(EXAMPLE.read_bytes())
        document["schema"] = "night-city-case/unknown"
        report = validate_case(document)
        self.assertEqual("failed", report.checks["V1"])
        self.assertTrue(any(issue.pointer == "/schema" for issue in report.issues))
        self.assertFalse(report.publishable)
        document = load_case_bytes(EXAMPLE.read_bytes())
        document["unexpected"] = True
        report = validate_case(document)
        self.assertEqual("failed", report.checks["V1"])
        self.assertTrue(any(issue.pointer == "" for issue in report.issues))

    def test_schema_with_remote_reference_fails_closed(self):
        document = load_case_bytes(EXAMPLE.read_bytes())
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$ref": "https://example.invalid/no"}
        report = validate_case(document, schema=schema)
        self.assertEqual("failed", report.checks["V1"])
        self.assertTrue(any(issue.code == "schema_external_ref" for issue in report.issues))

    def test_read_failure_is_reported_without_hash(self):
        report = validate_case_file(ROOT / "does-not-exist-case.json")
        self.assertEqual("failed", report.checks["V1"])
        self.assertIsNone(report.content_hash)
        self.assertTrue(report.issues)

    def test_cli_json_and_nonzero_exit_for_incomplete_case(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", TEMP=r"F:\Temp", TMP=r"F:\Temp")
        completed = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts/validate_night_case.py"), str(EXAMPLE)],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", check=False,
        )
        self.assertNotEqual(0, completed.returncode)
        report = json.loads(completed.stdout)
        self.assertEqual("passed", report["checks"]["V1"])
        self.assertFalse(report["publishable"])

    def test_cli_json_output_is_utf8(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", TEMP=r"F:\Temp", TMP=r"F:\Temp")
        completed = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts/validate_night_case.py"),
             str(ROOT / "missing-night-case.json")],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", check=False,
        )
        self.assertNotEqual(0, completed.returncode)
        self.assertIn("Не удалось прочитать JSON", completed.stdout)
        self.assertEqual("failed", json.loads(completed.stdout)["checks"]["V1"])


if __name__ == "__main__":
    unittest.main()
