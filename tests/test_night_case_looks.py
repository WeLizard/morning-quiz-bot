"""Appearance looks of roles: v2 format, seeded choice, template renderer and look-aware projection."""
import copy
import json
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from domain import night_case_engine
from domain.night_case_engine import _initialize, start
from domain.night_case_projection import project
from domain.night_case_simulation import run_smoke_policy
from domain.night_case_state import KernelState, PlayerActor, rules_snapshot
from domain.night_case_text import Renderer, chosen_looks, looks_of, render, render_text
from domain.night_case_v2_format import CaseV2Error, SCHEMA_PATH, compile_v2, load_v2, self_text_allowed

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "content/night_city/manor_lake.case.json"
RAW = json.loads(PATH.read_text(encoding="utf8"))
CASE = compile_v2(load_v2(PATH.read_bytes()))
RULES = rules_snapshot("Europe/Berlin")
START = datetime(2026, 11, 15, 10, tzinfo=timezone.utc)
LOOK_ROLES = {c["id"] for c in RAW["characters"]}   # since 2026-11-21 every Manor role has a second look


def roster(count=12):
    return {"players": [{"account_id": f"actor{i:02d}", "display_name": f"Игрок {i:02d}"} for i in range(count)],
            "npc_name_pool": [f"Гость {i:02d}" for i in range(20)]}


def compile_doc(doc):
    return compile_v2(load_v2(json.dumps(doc, ensure_ascii=False).encode("utf-8")))


def synthetic():
    forms = {"gen": "Фотографа-гостя", "dat": "Фотографу-гостю", "acc": "Фотографа-гостя", "ins": "Фотографом-гостем", "prep": "Фотографе-госте"}
    female = {"gen": "Фотографа-гостьи", "dat": "Фотографу-гостье", "acc": "Фотографа-гостью", "ins": "Фотографом-гостьей", "prep": "Фотографе-гостье"}
    return {"characters": [
        {"id": "photographer", "title": "Фотограф-гость", "title_forms": forms, "gender": "m",
         "bio": {"text": "Кепка.", "mentions": []}, "art": {"asset_id": "p", "alt": "м"},
         "looks": [{"id": "base", "gender": "m", "age": 30, "bio": {"text": "Кепка.", "mentions": []}, "art": {"asset_id": "p", "alt": "м"}},
                   {"id": "f30", "gender": "f", "age": 30, "title": "Фотограф-гостья", "title_forms": female,
                    "bio": {"text": "Шарф.", "mentions": []}, "art": {"asset_id": "p__f30", "alt": "ж"}}]},
        {"id": "maid", "title": "Горничная", "title_forms": {"gen": "Горничной", "dat": "Горничной", "acc": "Горничную", "ins": "Горничной", "prep": "Горничной"},
         "gender": "f", "bio": {"text": "Чепчик.", "mentions": []}, "art": None}]}


class RendererTests(unittest.TestCase):
    def test_gender_agreement_follows_the_sealed_look_and_defaults_without_looks(self):
        case = synthetic()
        text = "Фотограф {g:photographer|поправил|поправила} ремень; {t:maid} {g:maid|ушёл|ушла}."
        self.assertEqual(render_text(text, case), "Фотограф поправил ремень; горничная ушла.")
        sealed = {"sealed": {"looks": {"photographer": "f30"}}}
        self.assertEqual(render_text(text, case, sealed), "Фотограф поправила ремень; горничная ушла.")
        # An unknown or absent look id (old states) falls back to the first, default look.
        self.assertEqual(render_text(text, case, {"sealed": {"looks": {"photographer": "gone"}}}), "Фотограф поправил ремень; горничная ушла.")

    def test_title_cases_and_sentence_position(self):
        case = synthetic()
        sealed = {"sealed": {"looks": {"photographer": "f30"}}}
        self.assertEqual(render_text("{t:photographer} пришла. Видели {t:photographer|acc}.", case, sealed),
                         "Фотограф-гостья пришла. Видели фотографа-гостью.")
        self.assertEqual(render_text("Слово {t:photographer|gen}: «{t:photographer|ins} быть»", case),
                         "Слово фотографа-гостя: «Фотографом-гостем быть»")
        for form in ("gen", "dat", "acc", "ins", "prep"):
            self.assertEqual(render_text("{t:maid|%s}" % form, case), synthetic()["characters"][1]["title_forms"][form])

    def test_self_agreement_uses_the_reader_and_names_come_from_the_party(self):
        case = synthetic()
        text = "Ты {g:@self|сам|сама} {g:@self|сверил|сверила}, а {c:photographer} молчит."
        party = {"sealed": {"looks": {"photographer": "f30"}},
                 "players": [{"character_id": "photographer", "name": "Ника"}], "npcs": [{"character_id": "maid", "name": "Гость 01"}]}
        self.assertEqual(render_text(text, case, party, "photographer"), "Ты сама сверила, а Ника молчит.")
        self.assertEqual(render_text(text, case, party, "maid"), "Ты сама сверила, а Ника молчит.")
        self.assertEqual(render_text(text, case, {"sealed": {}}, "photographer"), "Ты сам сверил, а фотограф-гость молчит.")
        self.assertEqual(render_text("{g:@self||а}", case), "")

    def test_tree_renders_only_authored_bodies(self):
        case = synthetic()
        value = {"body": {"text": "{g:photographer|он|она}", "mentions": []}, "claim": {"text": "{g:photographer|он|она}"}, "n": 1}
        rendered = render(value, case, {"sealed": {"looks": {"photographer": "f30"}}})
        self.assertEqual(rendered, {"body": {"text": "она", "mentions": []}, "claim": {"text": "{g:photographer|он|она}"}, "n": 1})
        self.assertEqual(value["body"]["text"], "{g:photographer|он|она}", "rendering never mutates the raw template")

    def test_looks_materialize_inherited_fields(self):
        looks = looks_of(synthetic()["characters"][0])
        self.assertEqual([look["id"] for look in looks], ["base", "f30"])
        self.assertEqual(looks[0]["title"], "Фотограф-гость")
        self.assertEqual(looks[1]["title_forms"]["acc"], "Фотографа-гостью")
        self.assertEqual(looks_of(synthetic()["characters"][1])[0]["id"], "base")


class FormatTests(unittest.TestCase):
    def doc(self):
        return copy.deepcopy(RAW)

    def char(self, doc, ident):
        return next(c for c in doc["characters"] if c["id"] == ident)

    def assertRejected(self, doc, code):
        with self.assertRaises(CaseV2Error) as caught:
            compile_doc(doc)
        self.assertEqual(caught.exception.code, code, caught.exception.message)

    def test_every_manor_role_has_two_looks_and_canon_second_looks_stay(self):
        looks = {c["id"]: [(l["id"], l["gender"], l["age"]) for l in c["looks"]] for c in RAW["characters"] if "looks" in c}
        self.assertEqual(set(looks), LOOK_ROLES)
        self.assertEqual(len(LOOK_ROLES), 20)
        self.assertEqual({role: len(items) for role, items in looks.items()}, {role: 2 for role in LOOK_ROLES})
        self.assertEqual(looks["hunter"][1], ("f55", "f", 55))
        self.assertEqual(looks["chauffeur"][1], ("f28", "f", 28))
        self.assertEqual(looks["doctor"][1], ("f61", "f", 61))
        self.assertEqual(looks["cook"][1], ("f45", "f", 45))
        self.assertEqual(looks["photographer"][1], ("f30", "f", 30))
        self.assertEqual(looks["investigator"][1], ("m44", "m", 44))
        self.assertEqual(looks["gardener"][1], ("m63", "m", 63))
        for character in RAW["characters"]:
            for look in character.get("looks", [])[1:]:
                self.assertEqual(look["art"]["asset_id"], f"manor_char_{character['id']}__{look['id']}")

    def test_schema_accepts_agreement_templates(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        pattern = re.compile(schema["$defs"]["body"]["properties"]["text"]["pattern"])
        for ok in ("{g:doctor|начал|начала} сверку", "Ты {g:@self||а}", "{t:cook|gen} и {c:cook}"):
            self.assertRegex(ok, pattern)
        for bad in ("{g:doctor|начал}", "{g:Doctor|а|б}", "{x:doctor}"):
            self.assertNotRegex(bad, pattern)
        Draft202012Validator(schema).validate(RAW)

    def test_agreement_must_name_a_character_or_self_in_a_private_text(self):
        doc = self.doc()
        doc["facts"][0]["body"]["text"] = "{g:ghost|был|была} тут."
        self.assertRejected(doc, "v2.ref")
        doc = self.doc()
        doc["observations"][0]["body"]["text"] = "Ты {g:@self|видел|видела} ключ."
        self.assertRejected(doc, "v2.template")
        doc = self.doc()
        self.char(doc, "doctor")["bio"]["text"] = "{g:@self|Сам|Сама}."
        self.char(doc, "doctor")["looks"][0]["bio"]["text"] = "{g:@self|Сам|Сама}."
        self.assertRejected(doc, "v2.template")
        self.assertTrue(self_text_allowed("/personal_tasks/steps/4/responses/0/body/text"))
        self.assertTrue(self_text_allowed("/characters/2/goal/criteria/text"))
        self.assertFalse(self_text_allowed("/characters/2/bio/text"))
        self.assertFalse(self_text_allowed("/observations/53/body/text"))

    def test_first_look_must_match_top_level_and_ids_are_unique(self):
        doc = self.doc()
        self.char(doc, "doctor")["gender"] = "f"
        self.assertRejected(doc, "v2.looks")
        doc = self.doc()
        self.char(doc, "cook")["looks"][1]["id"] = "base"
        self.assertRejected(doc, "v2.duplicate_ref")
        doc = self.doc()
        self.char(doc, "cook")["looks"][1]["art"]["asset_id"] = "manor_char_maid"
        self.assertRejected(doc, "v2.looks")
        doc = self.doc()
        del self.char(doc, "photographer")["looks"][1]["title_forms"]
        self.assertRejected(doc, "v2.looks")

    def test_case_without_looks_still_compiles(self):
        doc = self.doc()
        for character in doc["characters"]:
            character.pop("looks", None)
        compiled = compile_doc(doc)
        state = start(compiled, RULES, roster(), game_id="no_looks", seed=7, now_utc=START).state
        self.assertNotIn("looks", state.document()["sealed"])


class DeterminismTests(unittest.TestCase):
    def test_same_seed_same_looks_and_both_looks_occur(self):
        seen = {role: set() for role in LOOK_ROLES}
        for seed in range(24):
            a = start(CASE, RULES, roster(), game_id="looks", seed=seed, now_utc=START).state.document()["sealed"]
            b = start(CASE, RULES, roster(), game_id="looks", seed=seed, now_utc=START).state.document()["sealed"]
            self.assertEqual(a["looks"], b["looks"])
            self.assertEqual(set(a["looks"]), LOOK_ROLES)
            for role, look in a["looks"].items():
                seen[role].add(look)
        self.assertEqual({role: len(looks) for role, looks in seen.items()}, {role: 2 for role in LOOK_ROLES})

    def test_looks_do_not_change_variant_roles_or_npcs(self):
        doc = copy.deepcopy(RAW)
        for character in doc["characters"]:
            character.pop("looks", None)
        plain = compile_doc(doc)
        for seed in (1, 5, 42, 1234):
            for count in (4, 5, 8, 12):
                with_looks = start(CASE, RULES, roster(count), game_id="g", seed=seed, now_utc=START).state.document()
                without = start(plain, RULES, roster(count), game_id="g", seed=seed, now_utc=START).state.document()
                sealed = dict(with_looks["sealed"]); sealed.pop("looks")
                self.assertEqual(sealed, without["sealed"])
                self.assertEqual(with_looks["players"], without["players"])
                self.assertEqual(with_looks["npcs"], without["npcs"])

    def test_passability_does_not_depend_on_looks(self):
        results = []
        for choice in (0, 1):   # every role in its default look, then every role in its second look
            def pick(case_doc, _rng, choice=choice):
                return {c["id"]: c["looks"][choice]["id"] for c in case_doc["characters"] if c.get("looks")}
            with patch.object(night_case_engine, "pick_looks", pick):
                outcome = [run_smoke_policy(CASE, RULES, "manor_5", variant, policy="seeded_random", seed=3)
                           for variant in ("variant_a", "variant_b", "variant_c")]
            results.append([(r.final_code, r.commands, r.passed) for r in outcome])
        self.assertEqual(results[0], results[1])
        self.assertTrue(all(passed for _, _, passed in results[0]))


class StateTests(unittest.TestCase):
    def started(self, seed=42):
        return start(CASE, RULES, roster(), game_id="state_looks", seed=seed, now_utc=START).state

    def test_old_state_without_looks_reads_default_looks(self):
        doc = self.started().document()
        doc["sealed"].pop("looks")
        state = KernelState.from_document(doc, CASE, RULES)
        looks = chosen_looks(CASE.document(), state.document())
        self.assertEqual({role: looks[role]["id"] for role in LOOK_ROLES}, {role: "base" for role in LOOK_ROLES})
        public = project(CASE, RULES, state)
        self.assertEqual(public["looks"]["doctor"]["gender"], "m")

    def test_sealed_looks_are_validated(self):
        doc = self.started().document()
        broken = copy.deepcopy(doc); broken["sealed"]["looks"]["doctor"] = "f99"
        with self.assertRaises(ValueError):
            KernelState.from_document(broken, CASE, RULES)
        broken = copy.deepcopy(doc); broken["sealed"]["looks"].pop("cook")
        with self.assertRaises(ValueError):
            KernelState.from_document(broken, CASE, RULES)
        broken = copy.deepcopy(doc); broken["sealed"]["looks"]["stranger"] = "base"
        with self.assertRaises(ValueError):
            KernelState.from_document(broken, CASE, RULES)


class ProjectionTests(unittest.TestCase):
    def state_with(self, role, look, seed=42):
        state = _initialize(CASE, RULES, roster(), game_id="proj_looks", seed=seed, composition_id="manor_12",
                            selected_variant_id="variant_a", now_utc=START).state
        doc = state.document()
        doc["sealed"]["looks"][role] = look
        return KernelState.from_document(doc, CASE, RULES), doc

    def diff(self, a, b, path=""):
        if isinstance(a, dict) and isinstance(b, dict):
            keys = set(a) | set(b)
            return [d for k in sorted(keys) for d in self.diff(a.get(k), b.get(k), f"{path}/{k}")]
        if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            return [d for i, (x, y) in enumerate(zip(a, b)) for d in self.diff(x, y, f"{path}/{i}")]
        return [] if a == b else [path]

    def test_two_looks_of_one_role_differ_only_in_portrait_title_alt_and_grammar(self):
        for role in ("doctor", "cook", "investigator", "gardener"):
            base_state, doc = self.state_with(role, "base")
            alt = next(c for c in RAW["characters"] if c["id"] == role)["looks"][1]
            alt_state, _ = self.state_with(role, alt["id"])
            player = next(p for p in doc["players"] if p["character_id"] == role)
            viewer = PlayerActor(player["account_id"])
            a, b = project(CASE, RULES, base_state, viewer), project(CASE, RULES, alt_state, viewer)
            allowed = re.compile(rf"^(/looks/{role}/|/self/role/(look_id|gender|age|bio|art|title|title_forms)\b|/self/(goal|secrets|personal)/.*text$)")
            changed = self.diff(a, b)
            self.assertTrue(changed, role)
            self.assertEqual([path for path in changed if not allowed.match(path)], [], role)
            self.assertEqual(b["self"]["role"]["art"]["asset_id"], f"manor_char_{role}__{alt['id']}")
            self.assertEqual(b["self"]["role"]["gender"], alt["gender"])
            self.assertEqual(a["self"]["faction"], b["self"]["faction"])

    def test_projection_renders_templates_and_keeps_raw_kernel_text(self):
        state, doc = self.state_with("investigator", "m44")
        player = next(p for p in doc["players"] if p["character_id"] == "investigator")
        own = project(CASE, RULES, state, PlayerActor(player["account_id"]))["self"]
        self.assertEqual(own["secrets"][0]["text"], "Приехал не случайно: за неделю получил анонимное письмо с приглашением.")
        self.assertEqual(own["goal"]["body"]["text"], "Найти отправителя и понять, кто его позвал и зачем.")
        self.assertEqual(own["role"]["title"], "Следователь из города")
        raw = next(c for c in CASE.document()["characters"] if c["id"] == "investigator")
        self.assertIn("{g:investigator|", raw["secrets"][0]["body"]["text"])
        state, doc = self.state_with("investigator", "base")
        own = project(CASE, RULES, state, PlayerActor(player["account_id"]))["self"]
        self.assertEqual(own["secrets"][0]["text"], "Приехала не случайно: за неделю получила анонимное письмо с приглашением.")

    def test_photographer_title_follows_the_look(self):
        state, _ = self.state_with("photographer", "f30")
        self.assertEqual(project(CASE, RULES, state)["looks"]["photographer"]["title"], "Фотограф-гостья")
        state, _ = self.state_with("photographer", "base")
        self.assertEqual(project(CASE, RULES, state)["looks"]["photographer"]["title_forms"]["acc"], "Фотографа-гостя")


class GenderLintTests(unittest.TestCase):
    """No hard-coded gendered words next to roles whose looks differ in gender."""

    STEMS = {"doctor": r"врач", "cook": r"повар", "photographer": r"фотограф", "investigator": r"следовател",
             "hunter": r"охотни[кц]", "chauffeur": r"шофёр"}
    PAST = r"[а-яё]+(?:л|ла|лся|лась)"

    def strip(self, text):
        return re.sub(r"\{[^{}]*\}", "§", text)

    def texts(self, value, pointer=""):
        if isinstance(value, dict):
            for key, child in value.items():
                yield from self.texts(child, f"{pointer}/{key}")
        elif isinstance(value, list):
            for i, child in enumerate(value):
                yield from self.texts(child, f"{pointer}/{i}")
        elif isinstance(value, str) and pointer.endswith(("/text", "/label", "/title")):
            yield pointer, value

    def test_varying_roles_have_both_genders(self):
        varying = {c["id"] for c in RAW["characters"] if len({l["gender"] for l in c.get("looks", [])}) > 1}
        self.assertEqual(varying, set(self.STEMS))

    def test_role_mentions_do_not_carry_fixed_gender(self):
        bad = []
        for pointer, text in self.texts(RAW):
            if "/looks/" in pointer or pointer.endswith("/bio/text") or re.fullmatch(r"/characters/\d+/title", pointer):
                continue   # per-look fields: the top-level title and bio are the default look
            plain = self.strip(text).lower()
            for stem in self.STEMS.values():
                if re.search(rf"\b{stem}[а-яё-]*\s+(?:\S+\s+)?{self.PAST}\b", plain) or re.search(rf"\b{stem}[а-яё]*-гост(?:ь|ья|ьи|ью|ьей|ье|я|ю|ем|е)\b", plain):
                    bad.append((pointer, text))
        self.assertEqual(bad, [])

    def test_texts_addressed_to_varying_roles_use_agreement(self):
        index = {c["id"]: i for i, c in enumerate(RAW["characters"])}
        pointers = []
        for role in self.STEMS:
            i = index[role]
            pointers += [f"/characters/{i}/goal", f"/characters/{i}/secrets"]
        for n, step in enumerate(RAW["personal_tasks"]["steps"]):
            if set(step["actors"]) & set(self.STEMS):
                pointers.append(f"/personal_tasks/steps/{n}/responses")
        bad = []
        for pointer, text in self.texts(RAW):
            if not pointer.startswith(tuple(pointers)):
                continue
            plain = self.strip(text)
            if (re.search(r"\b(?:сам|сама)\b", plain, re.I) or re.search(rf"\bТы\s+(?:\S+\s+)?{self.PAST}\b", plain)
                    or re.search(rf"(?:^|[.!?]\s+){self.PAST}\b", plain.lower())):
                bad.append((pointer, text))
        self.assertEqual(bad, [])

    def test_rendered_manor_texts_have_no_leftover_templates(self):
        for seed in (0, 1, 2, 3):
            state = start(CASE, RULES, roster(), game_id="lint", seed=seed, now_utc=START).state
            doc = state.document()
            for player in doc["players"]:
                renderer = Renderer(CASE.document(), doc, player["character_id"])
                for pointer, text in self.texts(CASE.document()):
                    self.assertNotRegex(renderer.text(text), r"[{}]", pointer)


if __name__ == "__main__":
    unittest.main()
