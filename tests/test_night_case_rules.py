"""Case format for design rules P1-P9: hero names, public lines, items, clue subjects, and the rules report."""
import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from domain.night_case_engine import _initialize
from domain.night_case_rules import check_rules
from domain.night_case_state import rules_snapshot
from domain.night_case_text import Renderer, public_look
from domain.night_case_v2_format import CaseV2Error, compile_v2, load_v2

ROOT = Path(__file__).resolve().parents[1]
RAW = json.loads((ROOT / "content/night_city/manor_lake.case.json").read_text(encoding="utf8"))
RULES = rules_snapshot("Europe/Berlin")
START = datetime(2026, 11, 15, 10, tzinfo=timezone.utc)


def compile_doc(doc):
    return compile_v2(load_v2(json.dumps(doc, ensure_ascii=False).encode("utf-8")))


def body(text):
    return {"text": text, "mentions": []}


def named(doc=None):
    """The Manor with a name and a public line on every look (ids give unique names)."""
    doc = copy.deepcopy(doc or RAW)
    for c in doc["characters"]:
        c["name"] = f"Имя {c['id']}"
        c["public"] = body(f"О {c['id']} знают все.")
        for j, look in enumerate(c.get("looks") or ()):
            look["name"] = c["name"] if j == 0 else f"Имя {c['id']} {look['id']}"
            look["public"] = c["public"] if j == 0 else body(f"О {c['id']} {look['id']} знают все.")
    return doc


class FormatTests(unittest.TestCase):
    def test_old_cases_without_names_items_or_subjects_still_compile_unchanged(self):
        self.assertEqual(compile_doc(RAW).content_hash, compile_v2(load_v2((ROOT / "content/night_city/manor_lake.case.json").read_bytes())).content_hash)

    def test_names_public_lines_items_and_subjects_compile(self):
        doc = named()
        doc["items"] = [{"id": "drawer_key", "title": "Ключ от ящика", "body": body("Медный ключ с зелёной ниткой."), "location": "library"}]
        doc["observations"][0]["subject"] = {"item": "drawer_key"}
        doc["observations"][1]["subject"] = {"location": "library"}
        doc["observations"][2]["subject"] = {"character": "lawyer"}
        compile_doc(doc)

    def test_a_hero_name_belongs_to_one_hero(self):
        doc = named()
        doc["characters"][1]["looks"][1]["name"] = doc["characters"][0]["name"]
        with self.assertRaisesRegex(CaseV2Error, "уже носит другой герой"):
            compile_doc(doc)

    def test_first_look_repeats_the_top_level_name(self):
        doc = named()
        doc["characters"][0]["looks"][0]["name"] = "Другое имя"
        with self.assertRaisesRegex(CaseV2Error, "Первый облик"):
            compile_doc(doc)

    def test_items_and_subjects_reference_existing_places_and_things(self):
        doc = named()
        doc["items"] = [{"id": "drawer_key", "title": "Ключ", "body": body("Ключ."), "location": "nowhere"}]
        with self.assertRaises(CaseV2Error):
            compile_doc(doc)
        doc["items"][0]["location"] = None
        doc["observations"][0]["subject"] = {"item": "missing_item"}
        with self.assertRaises(CaseV2Error):
            compile_doc(doc)


class NameTests(unittest.TestCase):
    def test_case_text_names_the_hero_from_its_look_never_the_player_label(self):
        doc = named()
        party = {"sealed": {"looks": {"cook": doc["characters"][[c["id"] for c in doc["characters"]].index("cook")]["looks"][1]["id"]}},
                 "players": [{"character_id": "cook", "name": "Маша"}], "npcs": []}
        text = Renderer(doc, party).text("{c:cook} ставит тесто; {c:lawyer} молчит.")
        self.assertNotIn("Маша", text)
        self.assertIn("Имя cook f45", text)
        self.assertIn("Имя lawyer", text)

    def test_public_look_shows_name_and_public_line_only_when_authored(self):
        doc = named()
        look = Renderer(doc).looks["cook"]
        self.assertEqual(public_look(look)["name"], "Имя cook")
        self.assertNotIn("name", public_look(Renderer(RAW).looks["cook"]))

    def test_heroes_the_game_plays_carry_their_look_names(self):
        case = compile_doc(named())
        roster = {"players": [{"account_id": f"a{i}", "display_name": f"Игрок {i}"} for i in range(4)],
                  "npc_name_pool": [f"Житель {i}" for i in range(1, 33)]}
        doc = _initialize(case, RULES, roster, game_id="g", seed=7, composition_id="manor_4",
                          selected_variant_id="variant_a", now_utc=START).state.document()
        npcs = doc["npcs"]
        self.assertTrue(npcs and all(n["name"].startswith("Имя ") for n in npcs))
        self.assertEqual({p["name"] for p in doc["players"]}, {f"Игрок {i}" for i in range(4)})


class RulesReportTests(unittest.TestCase):
    def test_the_manor_is_reported_against_every_rule(self):
        report = check_rules(RAW)
        status = {rule: row["status"] for rule, row in report["rules"].items()}
        self.assertEqual(status, {"P1": "not_checked", "P2": "failed", "P3": "not_checked", "P4": "failed",
                                  "P5": "failed", "P6": "failed", "P7": "failed", "P8": "not_checked", "P9": "not_checked"})
        self.assertFalse(report["passed"])
        problems = report["rules"]["P4"]["problems"]
        self.assertTrue(any("/characters/lawyer/faction" in p for p in problems))

    def test_a_case_kept_to_the_checkable_rules_passes_them(self):
        doc = named()
        for c in doc["characters"]:
            if c["faction"] == "shadow" and c["can_be_player"]:
                c["faction"] = "independent"
        talk = {d["character"] for d in doc["dialogues"]}
        for c in doc["characters"]:
            if c["can_be_player"] and c["id"] not in talk:
                extra = copy.deepcopy(doc["dialogues"][0]); extra["id"] = "talk_" + c["id"]; extra["character"] = c["id"]
                doc["dialogues"].append(extra)
        while len(doc["variants"]) < 5:
            extra = copy.deepcopy(doc["variants"][1]); extra["id"] = f"variant_x{len(doc['variants'])}"
            doc["variants"].append(extra)
        doc["items"] = [{"id": "drawer_key", "title": "Ключ", "body": body("Ключ."), "location": "library"}]
        for o in doc["observations"]:
            o["subject"] = {"location": "library"}
        report = check_rules(doc)
        for rule in ("P2", "P4", "P5", "P6", "P7"):
            self.assertEqual(report["rules"][rule]["status"], "passed", report["rules"][rule]["problems"])
        self.assertFalse(report["passed"], "P1, P3, P8, P9 are not checked yet, so nothing is release-clean")

    def test_a_hero_in_the_shadow_in_every_variant_fails_P4_even_without_a_shadow_faction(self):
        doc = named()
        for c in doc["characters"]:
            if c["faction"] == "shadow":
                c["faction"] = "independent"
        for v in doc["variants"]:
            v["accomplices"] = [x for x in v["accomplices"] if x != "maid"] + (["maid"] if v["culprit"] != "maid" else [])
        problems = check_rules(doc)["rules"]["P4"]["problems"]
        self.assertTrue(any(p == "/characters/maid: в Тени во всех вариантах правды" for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
