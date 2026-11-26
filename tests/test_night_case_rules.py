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


def unnamed(doc=None):
    """The Manor as an old case without names and public lines on its heroes."""
    doc = copy.deepcopy(doc or RAW)
    for c in doc["characters"]:
        for entry in [c, *(c.get("looks") or ())]:
            entry.pop("name", None)
            entry.pop("public", None)
    return doc


def drawer_key(doc, location="library", title="Ключ от ящика", text="Медный ключ с зелёной ниткой."):
    """Add one test item next to the case's own items."""
    doc["items"] = list(doc.get("items", [])) + [{"id": "drawer_key", "title": title, "body": body(text), "location": location}]
    return doc


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
        doc = drawer_key(named())
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
        doc = drawer_key(named(), location="nowhere")
        with self.assertRaises(CaseV2Error):
            compile_doc(doc)
        doc["items"][-1]["location"] = None
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
        self.assertNotIn("name", public_look(Renderer(unnamed()).looks["cook"]))

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
        # Manor v5 keeps every rule the report can check; P1, P3, P8 and P9 are not checked yet.
        self.assertEqual(status, {"P1": "not_checked", "P2": "passed", "P3": "not_checked", "P4": "passed",
                                  "P5": "passed", "P6": "passed", "P7": "passed", "P8": "not_checked", "P9": "not_checked"},
                         {rule: row["problems"][:3] for rule, row in report["rules"].items()})
        self.assertFalse(report["passed"])

    def test_an_old_shadow_faction_still_fails_P4(self):
        doc = copy.deepcopy(RAW)
        next(c for c in doc["characters"] if c["id"] == "lawyer")["faction"] = "shadow"
        self.assertTrue(any("/characters/lawyer/faction" in p for p in check_rules(doc)["rules"]["P4"]["problems"]))

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
        drawer_key(doc)
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


class DirectorCastTests(unittest.TestCase):
    """Rule P9: the narrator sees the heroes, items and places the records touch, never a player label."""

    def frozen(self, cast):
        from domain.night_case_director import AuthorizedSource, SafeRecord, build_frozen_context
        account = 'account:00000000-0000-0000-0000-000000000001'
        source = AuthorizedSource('window_digest', 'digest-2', account, 2, 1, ('event-1',), ('proof-a',), '')
        records = (SafeRecord('event', 'event-1', 'result', 'Дверь открыта', account, 1),
                   SafeRecord('observation', 'proof-a', 'proof', 'Старая улика', account, 1, 'event-1'))
        return build_frozen_context(source, records, (), case_hash='c' * 64, ruleset_version='core/2',
                                    fallback='Авторская сводка.', created_at=START,
                                    closes_at=START.replace(hour=11), cast=cast), source

    def test_cast_enters_the_facts_and_survives_the_frozen_round_trip(self):
        from domain.night_case_director import FrozenContext, SafeCast
        cast = (SafeCast('hero', 'Повар', 'Агафья, 45 лет: румяная, в муке по локоть.'),
                SafeCast('item', 'Ключ от ящика', 'Медный ключ с зелёной ниткой.'))
        context, source = self.frozen(cast)
        doc = context.document()
        self.assertEqual(doc['schema'], 'night-director-view/2')
        self.assertIn('[герой; Повар] Агафья, 45 лет: румяная, в муке по локоть.', doc['narrative']['facts'])
        self.assertIn('[предмет; Ключ от ящика] Медный ключ с зелёной ниткой.', doc['narrative']['facts'])
        FrozenContext.from_document(doc, input_hash=context.input_hash, source=source)
        tampered = copy.deepcopy(doc); tampered['cast'][0]['body'] = 'Другое'
        with self.assertRaises(ValueError):
            FrozenContext.from_document(tampered, input_hash=context.input_hash, source=source)

    def test_without_cast_the_context_stays_version_one(self):
        context, _ = self.frozen(())
        self.assertEqual(context.document()['schema'], 'night-director-view/1')
        self.assertNotIn('cast', context.document())

    def test_cast_that_does_not_fit_is_left_out_not_the_records(self):
        from domain.night_case_director import SafeCast
        cast = tuple(SafeCast('hero', f'Герой {i}', 'ж' * 990) for i in range(40))
        context, _ = self.frozen(cast)
        facts = context.document()['narrative']['facts']
        self.assertTrue(any('Старая улика' in f for f in facts))
        self.assertLessEqual(sum(map(len, facts)), 16000)

    def test_director_cast_describes_the_party_look_and_clue_subjects(self):
        from application.night_case_director import director_cast
        doc = drawer_key(named(), text="Медный ключ.")
        key = RAW["variants"][0]["key_proofs"][0]
        next(o for o in doc["observations"] if o["id"] == key)["subject"] = {"item": "drawer_key"}
        party = {"sealed": {"looks": {"cook": "f45"}}, "players": [{"character_id": "lawyer", "name": "Маша"}], "npcs": []}
        cast = director_cast(doc, party, heroes=("cook", "lawyer"), observation_ids=(key,))
        kinds = [(c.kind, c.title) for c in cast]
        self.assertIn(("hero", "Повар"), kinds)
        self.assertIn(("item", "Ключ от ящика"), kinds)
        cook = next(c for c in cast if c.title == "Повар")
        self.assertTrue(cook.body.startswith("Имя cook f45, 45 лет: "), cook.body)
        self.assertFalse(any("Маша" in c.body for c in cast))
