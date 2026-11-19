"""Database-free structural checks for the Night City case validator."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from domain.night_case_validator import validate_structure
from domain.night_case_format import validate_case


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "docs" / "tasks" / "night_city" / "example_case.json"


def example_case() -> dict:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8-sig"))


class NightCaseStructureTests(unittest.TestCase):
    def assert_issue(self, document: dict, code: str, pointer: str | None = None) -> None:
        issues = validate_structure(document)
        self.assertIn(code, {issue.code for issue in issues}, issues)
        if pointer is not None:
            self.assertIn(pointer, {issue.pointer for issue in issues}, issues)

    def test_current_example_is_structurally_valid(self) -> None:
        self.assertEqual(validate_structure(example_case()), ())

    def test_true_in_none_is_a_valid_fact_truth_marker(self) -> None:
        case = example_case()
        case["facts"][0]["true_in"] = "none"
        self.assertEqual(validate_structure(case), ())

    def test_text_claim_may_be_false_in_a_variant(self) -> None:
        """A witness may lie; mentions do not imply truth-set containment."""
        case = example_case()
        witness = next(item for item in case["evidence"] if item["id"] == "e_pavel_word")
        fact = next(item for item in case["facts"] if item["id"] == witness["fact"])
        self.assertEqual(fact["true_in"], ["v_igor"])
        self.assertEqual("all", witness["exists_in"])
        self.assertEqual(validate_structure(case), ())

    def test_duplicate_ids_are_rejected_with_collection_pointer(self) -> None:
        case = example_case()
        case["locations"].append(copy.deepcopy(case["locations"][0]))
        self.assert_issue(case, "V1.ids", "/locations/5/id")

    def test_each_reference_collection_is_checked(self) -> None:
        mutations = (
            ("V1.refs", "/locations/0/connects/0", lambda c: c["locations"][0]["connects"].__setitem__(0, "missing")),
            ("V1.refs", "/characters/0/home", lambda c: c["characters"][0].__setitem__("home", "missing")),
            ("V1.refs", "/characters/0/schedule_overrides/0/location", lambda c: c["characters"][0]["schedule_overrides"].append({"windows": [1], "location": "missing"})),
            ("V1.refs", "/facts/0/at/character", lambda c: c["facts"][0].__setitem__("at", {"character": "missing", "location": c["locations"][0]["id"], "window": 1})),
            ("V1.refs", "/facts/0/at/location", lambda c: c["facts"][0].__setitem__("at", {"character": c["characters"][0]["id"], "location": "missing", "window": 1})),
            ("V1.refs", "/facts/0/true_in/0", lambda c: c["facts"][0].__setitem__("true_in", ["missing"])),
            ("V1.refs", "/evidence/0/fact", lambda c: c["evidence"][0].__setitem__("fact", "missing")),
            ("V1.refs", "/evidence/0/found/location", lambda c: c["evidence"][0]["found"].__setitem__("location", "missing")),
            ("V1.refs", "/evidence/0/exists_in/0", lambda c: c["evidence"][0].__setitem__("exists_in", ["missing"])),
            ("V1.refs", "/evidence/0/requires/0", lambda c: c["evidence"][0]["requires"].append("missing")),
            ("V1.refs", "/evidence/0/key_for/0", lambda c: c["evidence"][0].__setitem__("key_for", ["missing"])),
            ("V1.refs", "/evidence/0/misleads_toward/0", lambda c: c["evidence"][0].__setitem__("misleads_toward", ["missing"])),
            ("V1.refs", "/evidence/0/debunked_by/0", lambda c: c["evidence"][0].__setitem__("debunked_by", ["missing"])),
            ("V1.refs", "/evidence/0/mentions/0", lambda c: c["evidence"][0].__setitem__("mentions", ["missing", *c["evidence"][0]["mentions"]])),
            ("V1.refs", "/dialogues/0/character", lambda c: c["dialogues"][0].__setitem__("character", "missing")),
            ("V1.refs", "/dialogues/0/valid_in/0", lambda c: c["dialogues"][0].__setitem__("valid_in", ["missing"])),
            ("V1.refs", "/dialogues/0/mentions/0", lambda c: c["dialogues"][0]["mentions"].append("missing")),
            ("V1.refs", "/dialogues/0/options/0/goto", lambda c: c["dialogues"][0]["options"][0].__setitem__("goto", "missing")),
            ("V1.refs", "/dialogues/0/options/0/grants/0", lambda c: c["dialogues"][0]["options"][0]["grants"].append("missing")),
            ("V1.refs", "/dialogues/0/options/0/requires/0", lambda c: c["dialogues"][0]["options"][0]["requires"].append("missing")),
            ("V1.refs", "/variants/0/culprit", lambda c: c["variants"][0].__setitem__("culprit", "missing")),
            ("V1.refs", "/variants/0/accomplices/0", lambda c: c["variants"][0]["accomplices"].append("missing")),
            ("V1.refs", "/variants/0/key_evidence/0", lambda c: c["variants"][0]["key_evidence"].__setitem__(0, "missing")),
            ("V1.refs", "/events/0/effect/fact", lambda c: c["events"][0].__setitem__("effect", {"kind": "reveal_fact", "fact": "missing"})),
            ("V1.refs", "/events/0/effect/location", lambda c: c["events"][0]["effect"].__setitem__("location", "missing")),
            ("V1.refs", "/endings/0/variant", lambda c: c["endings"][0].__setitem__("variant", "missing")),
        )
        for code, pointer, mutate in mutations:
            with self.subTest(pointer=pointer):
                case = example_case()
                mutate(case)
                self.assert_issue(case, code, pointer)

    def test_invalid_placeholder_character_is_rejected(self) -> None:
        case = example_case()
        case["variants"][0]["motive"] += " {c:missing}"
        self.assert_issue(case, "V1.placeholders", "/variants/0/motive")

    def test_invalid_placeholder_role_is_rejected(self) -> None:
        case = example_case()
        case["variants"][0]["motive"] += " {t:missing|gen}"
        self.assert_issue(case, "V1.placeholders", "/variants/0/motive")

    def test_min_key_cannot_exceed_number_of_unique_keys(self) -> None:
        case = example_case()
        variant = case["variants"][0]
        variant["min_key"] = len(set(variant["key_evidence"])) + 1
        self.assert_issue(case, "V1.min_key", "/variants/0/min_key")

    def test_key_for_and_key_evidence_must_agree_when_key_for_is_present(self) -> None:
        case = example_case()
        variant = case["variants"][0]
        evidence_id = variant["key_evidence"][0]
        evidence = next(item for item in case["evidence"] if item["id"] == evidence_id)
        evidence["key_for"] = []
        self.assert_issue(case, "V1.key_evidence", f"/evidence/{case['evidence'].index(evidence)}/key_for")

    def test_absent_key_for_does_not_imply_an_empty_variant_claim(self) -> None:
        case = example_case()
        for evidence in case["evidence"]:
            evidence.pop("key_for", None)
        self.assertEqual(validate_structure(case), ())

    def test_misleading_evidence_requires_distinct_debunking_evidence(self) -> None:
        case = example_case()
        evidence = case["evidence"][0]
        evidence["misleads_toward"] = [case["characters"][0]["id"]]
        evidence.pop("debunked_by", None)
        self.assert_issue(case, "V5.debunk", f"/evidence/{case['evidence'].index(evidence)}/debunked_by")

    def test_misleading_evidence_cannot_debunk_itself(self) -> None:
        case = example_case()
        evidence = case["evidence"][0]
        evidence["misleads_toward"] = [case["characters"][0]["id"]]
        evidence["debunked_by"] = [evidence["id"]]
        self.assert_issue(case, "V5.debunk", f"/evidence/{case['evidence'].index(evidence)}/debunked_by/0")

    def test_player_range_must_be_ordered(self) -> None:
        case = example_case()
        case["meta"]["players"] = {"min": 5, "max": 4}
        self.assert_issue(case, "V1.players", "/meta/players")

    def test_referenced_windows_must_fit_case_days(self) -> None:
        case = example_case()
        case["events"][0]["window"] = case["setting"]["days"] * 2 + 1
        self.assert_issue(case, "V1.windows", "/events/0/window")

    def test_window_intervals_must_be_ordered(self) -> None:
        case = example_case()
        case["evidence"][0]["found"]["windows"] = [14, 1]
        schema = json.loads((ROOT / "docs" / "tasks" / "night_city" / "case.schema.json").read_text(encoding="utf-8-sig"))
        self.assertTrue(Draft202012Validator(schema).is_valid(case))
        self.assert_issue(case, "V1.windows", "/evidence/0/found/windows")

    def test_schedule_and_locked_windows_are_sets_not_intervals(self) -> None:
        case = example_case()
        case["characters"][0]["schedule_overrides"].append(
            {"windows": [4, 2], "location": case["locations"][0]["id"]}
        )
        case["events"][0]["effect"]["windows"] = [6, 5]
        self.assertEqual("passed", validate_case(case).checks["V1"])
        self.assertEqual((), validate_structure(case))


if __name__ == "__main__":
    unittest.main()
