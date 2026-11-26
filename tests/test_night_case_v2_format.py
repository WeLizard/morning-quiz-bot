"""Executable v2 case boundary and semantic invariants."""

import copy
import json
from pathlib import Path
import unittest

from domain.night_case_format import canonical_content_hash
from domain.night_case_v2_format import CaseV2, CaseV2Error, compile_v2, load_v2


FIXTURE = Path(__file__).parent / "fixtures/night_city/core_case_v2.json"


def source():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def compile_document(document):
    return compile_v2(load_v2(json.dumps(document, ensure_ascii=False).encode()))


class NightCaseV2FormatTests(unittest.TestCase):
    def test_fixture_compiles_without_publication_claim(self):
        document = source()
        compiled = compile_document(document)
        self.assertEqual("station_demo", compiled.case_id)
        self.assertEqual(1, compiled.case_version)
        self.assertEqual(canonical_content_hash(document), compiled.content_hash)
        self.assertTrue(compiled.compiler_version)
        self.assertEqual(document, compiled.document())
        changed = compiled.document()
        changed["facts"].clear()
        self.assertEqual(document, compiled.document())
        self.assertEqual({4, 5, 8, 12}, {c["players"] for c in document["compositions"]})
        self.assertEqual(2, len(document["variants"]))

    def test_unknown_fields_and_bad_primitives_rejected(self):
        for path, value in [(("setting", "extra"), 1), (("meta", "version"), True),
                            (("locations", 0, "id"), "Bad-ID"),
                            (("observations", 0, "body", "text"), "")]:
            with self.subTest(path=path):
                doc = source()
                target = doc
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = value
                with self.assertRaises(CaseV2Error):
                    load_v2(json.dumps(doc).encode())

    def test_parser_is_bounded_and_strict(self):
        for raw in (b'{"a":1,"a":2}', b'{"x":NaN}', b'\xff', b'[]', b' '* (2*1024*1024+1)):
            with self.subTest(raw=raw[:20]):
                with self.assertRaises(CaseV2Error) as caught:
                    load_v2(raw)
                self.assertTrue(caught.exception.issue.code)
                self.assertIsInstance(caught.exception.issue.pointer, str)
                self.assertTrue(caught.exception.issue.message)

    def test_integer_fields_reject_float_lookalikes(self):
        for mutate in (
            lambda d: d["meta"].update(version=1.0),
            lambda d: d["ruleset_ref"].update(version=1.0),
            lambda d: d["characters"][0]["schedule"][0].update(windows=[1.0]),
        ):
            doc = source()
            mutate(doc)
            with self.subTest(mutate=mutate), self.assertRaises(CaseV2Error):
                load_v2(json.dumps(doc).encode())

    def test_unknown_rules_and_modules_fail_closed(self):
        for change in (lambda d: d["ruleset_ref"].update(version=2),
                       lambda d: d["meta"].update(modules=["archive_requests"]),
                       lambda d: d.update(episode_refs=["episode_a"])):
            doc = source()
            change(doc)
            with self.assertRaises(CaseV2Error):
                compile_document(doc)

    def test_source_hash_and_materialized_defaults_are_separate(self):
        doc = source()
        doc["meta"].pop("duration")
        doc["meta"].pop("modules")
        doc["locations"][0].pop("art")
        case = load_v2(json.dumps(doc).encode())
        compiled = compile_v2(case)
        self.assertEqual(doc, case.document())
        self.assertEqual(canonical_content_hash(doc), compiled.content_hash)
        self.assertEqual("week", compiled.document()["meta"]["duration"])
        self.assertEqual([], compiled.document()["meta"]["modules"])
        self.assertIsNone(compiled.document()["locations"][0]["art"])
        with self.assertRaises(CaseV2Error):
            compile_v2(CaseV2(b"{}", case.content_hash))

    def test_typed_refs_proof_truth_and_false_claim(self):
        doc = source()
        self.assertEqual("none", doc["facts"][-1]["true_in"])
        compile_document(doc)
        mutations = [lambda d: d["characters"][0].update(home=d["facts"][0]["id"]),
                     lambda d: d["observations"][0].update(proves=[d["facts"][-1]["id"]]),
                     lambda d: d["actions"][0]["outcomes"][0]["effects"][0].update(observation="absent")]
        for mutate in mutations:
            bad = copy.deepcopy(doc)
            mutate(bad)
            with self.assertRaises(CaseV2Error):
                compile_document(bad)

    def test_outcomes_initial_and_schedule(self):
        mutations = [
            lambda d: d["actions"][0]["outcomes"][1]["guard"].update(variants=[d["variants"][0]["id"]]),
            lambda d: d["initial"]["public_observations"].append("variant_only"),
            lambda d: d["characters"][0]["schedule"].append({"windows":[1],"location":d["locations"][0]["id"]}),
            lambda d: d["events"].append({"id":"lock_evt","window":1,"body":{"text":"Закрыто","mentions":[]},"effects":[{"kind":"lock_location","location":d["locations"][0]["id"],"through_window":2}]}),
        ]
        for mutate in mutations:
            doc = source()
            mutate(doc)
            with self.subTest(mutate=mutate):
                with self.assertRaises(CaseV2Error):
                    compile_document(doc)

    def test_schedule_considers_player_who_may_forfeit(self):
        doc = source()
        doc["characters"][0]["home"] = "office"
        doc["characters"][0]["schedule"] = []
        doc["events"] = [{"id": "lock_office", "window": 1,
                          "body": {"text": "Закрыто", "mentions": []},
                          "effects": [{"kind": "lock_location", "location": "office", "through_window": 14}]}]
        with self.assertRaises(CaseV2Error) as caught:
            compile_document(doc)
        self.assertEqual("v2.schedule", caught.exception.issue.code)

    def test_flag_budget_boundary(self):
        for count in (64, 65):
            doc = source()
            doc["flags"] = [{"id": f"flag_{i:02}", "initial": False} for i in range(count)]
            doc["events"] = [{"id": "flag_event", "window": 1,
                              "body": {"text": "Флаги", "mentions": []},
                              "effects": [{"kind": "set_flag", "flag": f"flag_{i:02}", "value": True}
                                          for i in range(count)]}]
            with self.subTest(count=count):
                if count == 64:
                    compile_document(doc)
                else:
                    with self.assertRaises(CaseV2Error):
                        load_v2(json.dumps(doc).encode())

    def test_compositions_dialogue_goal_and_variant_refs(self):
        mutations = [
            lambda d: d["compositions"][0]["player_characters"].append(d["characters"][0]["id"]),
            lambda d: d["dialogues"][0].update(entry_node="missing"),
            lambda d: d["dialogues"][0]["nodes"][0]["options"][0].update(next_node="missing"),
            lambda d: d["characters"][0]["goal"]["when"].append({"kind":"knows","observation":"missing"}),
            lambda d: d["variants"][0].update(key_proofs=[d["observations"][2]["id"]]),
        ]
        for mutate in mutations:
            doc = source()
            mutate(doc)
            with self.subTest(mutate=mutate):
                with self.assertRaises(CaseV2Error):
                    compile_document(doc)


class NightCaseModulesFormatTests(unittest.TestCase):
    def source(self):
        return json.loads(FIXTURE.with_name("modules_case_v2.json").read_text(encoding="utf-8"))

    def test_modules_compile_and_bind_explicit_profile(self):
        doc = self.source()
        result = compile_document(doc)
        self.assertEqual(doc, result.document())
        self.assertEqual("night-city-case-compiler/2.2", result.compiler_version)
        self.assertEqual(canonical_content_hash(doc), result.content_hash)
        self.assertEqual("night-city-case-compiler/2.1", compile_document(source()).compiler_version)

    def test_module_contracts_fail_closed(self):
        mutations = [
            lambda d: d["module_data"]["archive_requests"]["queries"][0]["responses"].clear(),
            lambda d: d["module_data"]["turning_point"]["routes"][0].update(open_when=[{"kind":"published","observation":"proof_common"}]),
            lambda d: d["module_data"]["turning_point"]["concealed_npcs"][0]["placements"].pop(),
            lambda d: d["module_data"]["version_archive"]["comparisons"][0].update(right="missing"),
            lambda d: d["variants"][0].update(required_key_proofs=["proof_b"]),
            lambda d: d["actions"][-1].update(available_when=[]),
            lambda d: d["actions"][0]["outcomes"][0]["effects"].append({"kind":"set_flag","flag":"route_opened","value":True}),
        ]
        for mutate in mutations:
            doc = self.source()
            mutate(doc)
            with self.subTest(mutate=mutate), self.assertRaises(CaseV2Error):
                compile_document(doc)

    def test_profile_gate_and_registry_are_closed(self):
        doc = self.source()
        compile_document(doc)
        with self.assertRaises(CaseV2Error):
            compile_v2(load_v2(json.dumps(doc).encode()), {("night_case.core", 1)})
        for mutate in (
            lambda d: d["ruleset_ref"].update(version=1),
            lambda d: d["meta"].update(modules=["archive_requests"]),
            lambda d: d["meta"].update(modules=["unknown_module"]),
            lambda d: d["module_data"].update(extra={}),
            lambda d: d["module_data"]["archive_requests"].update(delay=2),
        ):
            changed = copy.deepcopy(doc)
            mutate(changed)
            with self.subTest(mutate=mutate), self.assertRaises(CaseV2Error):
                compile_document(changed)
        for kind in ({"kind":"character_active","character":"person_00"},):
            changed = source()
            changed["actions"][0]["available_when"].append(kind)
            with self.assertRaises(CaseV2Error):
                compile_document(changed)

    def test_module_exact_integers_and_limits(self):
        for mutate in (
            lambda d: d["module_data"]["version_archive"]["documents"][0].update(revision=True),
            lambda d: d["module_data"]["version_archive"]["documents"][0].update(revision=1.0),
            lambda d: d["module_data"]["turning_point"]["recovery"].update(through_window=12.0),
            lambda d: d["module_data"]["archive_requests"].update(queries=d["module_data"]["archive_requests"]["queries"] * 13),
            lambda d: d["module_data"]["turning_point"]["routes"][0].update(open_when=[{"kind":"knows","observation":"proof_common"}]),
            lambda d: d["module_data"]["turning_point"]["scenes"][0].update(effects=[{"kind":"lock_location","location":"office","through_window":12}]),
            lambda d: d["module_data"]["turning_point"]["scenes"][0].update(effects=[{"kind":"grant_observation","observation":"public_note","audience":"actor"}]),
        ):
            doc = self.source()
            mutate(doc)
            with self.subTest(mutate=mutate), self.assertRaises(CaseV2Error):
                compile_document(doc)

    def test_partitions_documents_and_module_refs(self):
        for mutate in (
            lambda d: d["module_data"]["archive_requests"]["queries"][0]["responses"].append(copy.deepcopy(d["module_data"]["archive_requests"]["queries"][0]["responses"][0])),
            lambda d: d["module_data"]["archive_requests"]["queries"][0]["responses"][0].update(observations=["proof_a"]),
            lambda d: d["module_data"]["version_archive"]["documents"][1].update(revision=1),
            lambda d: d["module_data"]["version_archive"]["documents"][1].update(observation="public_note"),
            lambda d: d["module_data"]["version_archive"]["documents"][1].update(family="other_family"),
            lambda d: d["actions"][0].update(kind="examine"),
            lambda d: d["actions"][0].update(available_when=[]),
            lambda d: d["module_data"]["version_archive"]["theories"][0]["links"][0].update(observation="missing"),
            lambda d: d["module_data"]["turning_point"]["recovery"].update(character="person_00"),
            lambda d: d["module_data"]["turning_point"]["scenes"][0].update(not_before=13),
        ):
            doc = self.source()
            mutate(doc)
            with self.subTest(mutate=mutate), self.assertRaises(CaseV2Error):
                compile_document(doc)

    def test_protected_flags_routes_and_reveal_location(self):
        for mutate in (
            lambda d: d["flags"][0].update(initial=True),
            lambda d: d["module_data"]["turning_point"]["concealed_npcs"][0].update(revealed_flag="route_opened"),
            lambda d: d["module_data"]["turning_point"]["routes"][0].update(ends=["foyer","yard"]),
            lambda d: d["module_data"]["turning_point"]["routes"][0]["open_when"][1].update(observation="public_note"),
            lambda d: d["actions"][-1]["outcomes"][0]["guard"].update(variants="all"),
            lambda d: d["actions"][-1]["outcomes"][0]["effects"][0].update(character="person_00"),
            lambda d: d["characters"][-1].update(can_be_player=True),
            lambda d: d["characters"][-1].update(schedule=[{"windows":[2],"location":"office"}]),
        ):
            doc = self.source()
            mutate(doc)
            with self.subTest(mutate=mutate), self.assertRaises(CaseV2Error):
                compile_document(doc)

    def test_static_concealed_occupant_may_remain_behind_later_lock(self):
        doc = self.source()
        doc["events"] = [{"id":"later_lock","window":2,"body":{"text":"Закрытая дверь","mentions":[]},
                          "effects":[{"kind":"lock_location","location":"office","through_window":4}]}]
        # Everyone else stays at foyer, so the lock isolates only the hidden occupant.
        for character in doc["characters"][:-1]:
            character["home"] = "foyer"
            character["schedule"] = []
        compile_document(doc)
        doc["characters"][0]["schedule"] = [{"windows":[3],"location":"office"}]
        with self.assertRaises(CaseV2Error) as caught:
            compile_document(doc)
        self.assertEqual("v2.schedule", caught.exception.code)

    def test_required_subset_can_exceed_count_threshold(self):
        doc = self.source()
        doc["variants"][0].update(min_key=1, required_key_proofs=["proof_a","proof_common"])
        compile_document(doc)


class NightCasePersonalFormatTests(unittest.TestCase):
    def source(self):
        return json.loads(FIXTURE.with_name("personal_case_v2.json").read_text(encoding="utf-8"))

    def test_personal_capability_compiles_with_separate_version(self):
        doc = self.source()
        compiled = compile_document(doc)
        self.assertEqual(doc, compiled.document())
        self.assertEqual("night-city-case-compiler/2.3", compiled.compiler_version)
        self.assertEqual(canonical_content_hash(doc), compiled.content_hash)

    def test_bad_personal_graphs_and_operation_refs(self):
        compile_document(self.source())
        for mutate in (
            lambda d: d["personal_tasks"]["steps"][0].update(requires=["read_original"]),
            lambda d: d["personal_tasks"]["steps"][1]["operation"].update(original="missing"),
            lambda d: d["personal_tasks"]["steps"][1].update(actors=["person_01"]),
            lambda d: d["personal_tasks"]["originals"][0]["sections"][0].update(backup_proofs=[]),
        ):
            doc = self.source()
            mutate(doc)
            with self.subTest(mutate=mutate), self.assertRaises(CaseV2Error):
                compile_document(doc)

    def test_capability_is_explicit_and_numbers_are_exact(self):
        for mutate in (
            lambda d: d["ruleset_ref"].update(version=1),
            lambda d: d.pop("personal_tasks"),
            lambda d: d["personal_tasks"].update(version=True),
            lambda d: d["personal_tasks"].update(version=1.0),
            lambda d: d["personal_tasks"].update(version=2),
            lambda d: d["personal_tasks"].update(extra=[]),
            lambda d: d["personal_tasks"]["steps"][0]["operation"].update(kind="invent_inventory"),
            lambda d: d["personal_tasks"]["steps"][0]["operation"].update(body="untrusted"),
            lambda d: d["personal_tasks"].update(steps=[]),
        ):
            doc = self.source()
            mutate(doc)
            with self.subTest(mutate=mutate), self.assertRaises(CaseV2Error):
                compile_document(doc)

    def test_personal_action_bijection_and_ordinary_outcomes(self):
        for mutate in (
            lambda d: d["actions"][-1].update(personal_step="missing"),
            lambda d: d["personal_tasks"]["steps"][-1].update(action="inspect_key"),
            lambda d: d["actions"][-1].update(kind="examine"),
            lambda d: d["actions"][-1].update(repeat="player_game"),
            lambda d: d["actions"][-1].update(outcomes=copy.deepcopy(d["actions"][0]["outcomes"])),
            lambda d: d["actions"][0].update(outcomes=[]),
        ):
            doc = self.source()
            mutate(doc)
            with self.subTest(mutate=mutate), self.assertRaises(CaseV2Error):
                compile_document(doc)
        # Compatibility: old profiles retain their pre-capability structural contract.
        for doc in (source(), NightCaseModulesFormatTests().source()):
            doc["actions"][0]["outcomes"] = []
            compile_document(doc)

    def test_a_turning_scene_may_carry_a_picture_of_its_own(self):
        doc = self.source()
        scene = doc["module_data"]["turning_point"]["scenes"][0]
        scene["art"] = {"asset_id": "manor_scene_turn", "alt": "Сцена поворота"}
        self.assertEqual(compile_document(doc).document()["module_data"]["turning_point"]["scenes"][0]["art"]["asset_id"], "manor_scene_turn")
        doc["variants"][0]["art"] = {"asset_id": "manor_scene_turn", "alt": "Финал"}  # one picture, two places

        with self.assertRaises(CaseV2Error):
            compile_document(doc)

    def test_destroyed_flag_names_a_false_flag_of_a_destroyable_original(self):
        def with_flag(d, initial=False):
            d["flags"].append({"id": "original_burned", "initial": initial})
            return d
        doc = with_flag(self.source())
        doc["personal_tasks"]["originals"][0]["destroyed_flag"] = "original_burned"
        self.assertEqual(compile_document(doc).document()["personal_tasks"]["originals"][0]["destroyed_flag"], "original_burned")
        for mutate in (
            lambda d: d["personal_tasks"]["originals"][0].update(destroyed_flag="missing"),
            lambda d: with_flag(d, True)["personal_tasks"]["originals"][0].update(destroyed_flag="original_burned"),
            lambda d: with_flag(d)["personal_tasks"]["originals"][1].update(destroyed_flag="original_burned"),
        ):
            doc = self.source()
            mutate(doc)
            with self.subTest(mutate=mutate), self.assertRaises(CaseV2Error):
                compile_document(doc)

    def test_physical_operation_refs_locations_and_ownership(self):
        for mutate in (
            lambda d: d["personal_tasks"]["originals"][0].update(return_to="person_01"),
            lambda d: d["personal_tasks"]["originals"][1].update(return_to="person_01"),
            lambda d: d["personal_tasks"]["originals"][0]["sections"][0].update(observation="proof_a"),
            lambda d: d["personal_tasks"]["originals"][0]["sections"][0].update(backup_proofs=["public_note"]),
            lambda d: d["personal_tasks"]["originals"][0]["sections"][0].update(backup_proofs=["proof_a"]),
            lambda d: d["personal_tasks"]["commitments"][0].update(issuer="person_00"),
            lambda d: d["personal_tasks"]["trips"][0].update(traveler="person_02"),
            lambda d: d["personal_tasks"]["topics"][0].update(subject="missing"),
            lambda d: d["personal_tasks"]["steps"][0]["operation"].update(section="missing"),
            lambda d: next(a for a in d["actions"] if a["id"] == "act_read_original").update(location="yard"),
            lambda d: next(a for a in d["actions"] if a["id"] == "act_take_original").update(available_when=[]),
            lambda d: next(a for a in d["actions"] if a["id"] == "act_burn_original").update(location="foyer"),
            lambda d: next(x for x in d["personal_tasks"]["steps"] if x["id"] == "burn_original").update(requires=[]),
            lambda d: next(x for x in d["personal_tasks"]["steps"] if x["id"] == "recover_cache").update(actors=["person_02"]),
            lambda d: next(x for x in d["personal_tasks"]["steps"] if x["id"] == "paint_finish")["operation"].update(stage="missing"),
            lambda d: next(x for x in d["personal_tasks"]["steps"] if x["id"] == "receive_letter")["responses"][0]["body"].update(text="Неподписанное обещание"),
            lambda d: next(x for x in d["personal_tasks"]["steps"] if x["id"] == "private_card")["operation"].update(observation="variant_only"),
        ):
            doc = self.source()
            mutate(doc)
            with self.subTest(mutate=mutate), self.assertRaises(CaseV2Error):
                compile_document(doc)

    def test_personal_goal_and_visible_predicate_scopes(self):
        for mutate in (
            lambda d: d["characters"][0]["goal"].pop("criteria"),
            lambda d: d["characters"][0]["goal"]["when"][0].update(step="return_letter"),
            lambda d: d["characters"][3]["goal"]["when"][0].update(trip="missing"),
            lambda d: next(a for a in d["actions"] if a["id"] == "act_take_original")["available_when"].append({"kind":"story_before","step":"take_original","boundary":{"kind":"foreign_inspection","original":"station_original"}}),
            lambda d: d["actions"][0]["available_when"].append({"kind":"story_done","step":"read_original"}),
            lambda d: d["characters"][0]["goal"]["when"][0]["boundary"].update(original="missing"),
        ):
            doc = self.source()
            mutate(doc)
            with self.subTest(mutate=mutate), self.assertRaises(CaseV2Error):
                compile_document(doc)

    def test_personal_partition_choice_and_duplicate_inspection(self):
        for mutate in (
            lambda d: d["personal_tasks"]["steps"][0]["responses"][0].update(variants=["variant_a"]),
            lambda d: d["personal_tasks"]["steps"][0]["responses"].append(copy.deepcopy(d["personal_tasks"]["steps"][0]["responses"][0])),
            lambda d: d["personal_tasks"]["steps"][0]["responses"][0].update(observations=["proof_a"]),
            lambda d: d["personal_tasks"]["steps"][-1].update(choice_group=None),
            lambda d: d["personal_tasks"]["steps"][-1].update(requires=[]),
        ):
            doc = self.source()
            mutate(doc)
            with self.subTest(mutate=mutate), self.assertRaises(CaseV2Error):
                compile_document(doc)
        doc = self.source()
        action = copy.deepcopy(next(a for a in doc["actions"] if a["id"] == "act_read_original"))
        action.update(id="act_read_again", personal_step="read_again")
        step = copy.deepcopy(doc["personal_tasks"]["steps"][0])
        step.update(id="read_again", action=action["id"])
        doc["actions"].append(action)
        doc["personal_tasks"]["steps"].append(step)
        with self.assertRaises(CaseV2Error):
            compile_document(doc)

    def test_prerequisite_depth_boundary_is_independent_of_catalog_order(self):
        for count in (8, 9):
            for reverse in (False, True):
                doc = self.source()
                chain = []
                for n in range(count):
                    ident = f"chain_{n:02}"
                    action_id = "act_" + ident
                    doc["actions"].append({"id":action_id,"kind":"interact","location":"foyer","label":"Этап", "available_when":[],"repeat":"player_window","outcomes":[],"fallback":{"text":"Нет результата","mentions":[]},"personal_step":ident})
                    chain.append({"id":ident,"action":action_id,"actors":["person_00"],"requires":[] if n == 0 else [f"chain_{n-1:02}"],"choice_group":None,"operation":{"kind":"record_deed"},"responses":[{"variants":"all","body":{"text":"Этап выполнен","mentions":[]},"observations":[]}]})
                doc["personal_tasks"]["steps"].extend(reversed(chain) if reverse else chain)
                with self.subTest(count=count, reverse=reverse):
                    if count == 8:
                        compile_document(doc)
                    else:
                        with self.assertRaises(CaseV2Error):
                            compile_document(doc)

    def test_topic_cannot_contain_initial_public_observation(self):
        doc = self.source()
        topic = doc["personal_tasks"]["topics"][0]
        topic["observations"] = [doc["initial"]["public_observations"][0]]
        with self.assertRaises(CaseV2Error) as caught:
            compile_document(doc)
        self.assertEqual("v2.personal", caught.exception.code)
        self.assertEqual("/personal_tasks/topics/0/observations", caught.exception.pointer)


class NightCaseRuntimeFormatTests(unittest.TestCase):
    def source(self):
        return json.loads(FIXTURE.with_name("runtime_case_v2.json").read_text(encoding="utf-8"))

    def test_runtime_capabilities_are_explicit_and_hash_bound(self):
        doc = self.source()
        for remove in (None, "communication", "npc_delivery"):
            changed = copy.deepcopy(doc)
            if remove:
                changed.pop(remove)
            compiled = compile_document(changed)
            self.assertEqual(changed, compiled.document())
            self.assertEqual("night-city-case-compiler/2.4", compiled.compiler_version)
            self.assertEqual(canonical_content_hash(changed), compiled.content_hash)
        doc.pop("communication")
        doc.pop("npc_delivery")
        self.assertEqual("night-city-case-compiler/2.2", compile_document(doc).compiler_version)

    def test_npc_catalogue_references_fail_closed(self):
        compile_document(self.source())
        for mutate in (
            lambda d: d["npc_delivery"]["topics"][0].update(npc="person_00"),
            lambda d: d["npc_delivery"]["topics"][0].update(option="missing"),
            lambda d: d["npc_delivery"]["topics"][0]["slip"].update(observation="proof_common"),
            lambda d: d["npc_delivery"]["topics"][0]["slip"].update(observation="public_note"),
        ):
            doc = self.source()
            mutate(doc)
            with self.subTest(mutate=mutate), self.assertRaises(CaseV2Error):
                compile_document(doc)

    def test_runtime_capabilities_reject_wrong_profiles_extras_and_numbers(self):
        for mutate in (
            lambda d: d["ruleset_ref"].update(version=1),
            lambda d: d["communication"].update(version=True),
            lambda d: d["communication"].update(version=1.0),
            lambda d: d["communication"].update(max_messages_per_window=20.0),
            lambda d: d["communication"].update(max_messages_per_window=19),
            lambda d: d["communication"].update(whisper_cost=0),
            lambda d: d["npc_delivery"].update(version=2),
            lambda d: d["npc_delivery"].update(window_reveal_budget=True),
            lambda d: d["npc_delivery"].update(window_reveal_budget=1.0),
            lambda d: d["npc_delivery"].update(window_reveal_budget=4),
            lambda d: d["npc_delivery"].update(game_reveal_budget=13),
            lambda d: d["npc_delivery"].update(extra=[]),
            lambda d: d["npc_delivery"]["topics"][0]["slip"].update(version=True),
            lambda d: d["npc_delivery"]["topics"][0]["slip"].update(probability_bp=10000.0),
            lambda d: d["npc_delivery"]["topics"][0]["slip"].update(probability_bp=10001),
            lambda d: d["npc_delivery"]["topics"][0]["slip"].update(extra=True),
        ):
            doc = self.source()
            mutate(doc)
            with self.subTest(mutate=mutate), self.assertRaises(CaseV2Error):
                compile_document(doc)

    def test_runtime_catalogues_and_visible_guards_are_closed(self):
        for mutate in (
            lambda d: d["npc_delivery"].update(topics=[]),
            lambda d: d["npc_delivery"].update(topics=d["npc_delivery"]["topics"] * 33),
            lambda d: d["npc_delivery"]["topics"][0].update(node="missing"),
            lambda d: d["npc_delivery"]["topics"][0].update(dialogue=d["dialogues"][0]["id"]),
            lambda d: d["npc_delivery"]["topics"][0].update(lines=[]),
            lambda d: d["npc_delivery"]["topics"][0].update(lines=d["npc_delivery"]["topics"][0]["lines"] * 3),
            lambda d: d["npc_delivery"]["topics"][0]["lines"][1].update(id="keeper_line_a"),
            lambda d: d["npc_delivery"]["topics"][0]["slip"].update(requires=[{"kind":"knows","observation":"missing"}]),
            lambda d: d["npc_delivery"]["topics"][0]["slip"].update(requires=[{"kind":"window_in","from":3,"to":2}]),
            lambda d: d["npc_delivery"]["topics"][0]["slip"].update(requires=[{"kind":"story_done","step":"read_original"}]),
            lambda d: d["observations"][-1].update(exists_in=["variant_a"]),
            lambda d: d["characters"][-1].update(can_be_player=True),
        ):
            doc = self.source()
            mutate(doc)
            with self.subTest(mutate=mutate), self.assertRaises(CaseV2Error):
                compile_document(doc)
        doc = self.source()
        duplicate = copy.deepcopy(doc["npc_delivery"]["topics"][0])
        duplicate["id"] = "other_topic"
        duplicate["slip"] = None
        doc["npc_delivery"]["topics"].append(duplicate)
        with self.assertRaises(CaseV2Error):
            compile_document(doc)

    def test_every_line_outcome_and_fallback_combination_obeys_body_bound(self):
        for outcome, count in ((False, 599), (False, 600), (True, 599), (True, 600)):
            doc = self.source()
            topic = doc["npc_delivery"]["topics"][0]
            topic["lines"][0]["body"]["text"] = "x" * count
            option = doc["dialogues"][-1]["nodes"][0]["options"][0]
            body = {"text":"y" * 600,"mentions":[]}
            if outcome:
                option["outcomes"] = [{"id":"long_outcome","guard":{"variants":"all","when":[]},"body":body,"effects":[]}]
            else:
                option["fallback"] = body
            with self.subTest(outcome=outcome, count=count):
                if count == 599:
                    compile_document(doc)
                else:
                    with self.assertRaises(CaseV2Error) as caught:
                        compile_document(doc)
                    self.assertEqual("v2.npc_delivery", caught.exception.code)

    def test_null_slip_and_zero_budgets_are_valid_and_do_not_create_key_authority(self):
        doc = self.source()
        doc["npc_delivery"].update(window_reveal_budget=0, game_reveal_budget=0)
        for slip in (None, doc["npc_delivery"]["topics"][0]["slip"]):
            doc["npc_delivery"]["topics"][0]["slip"] = slip
            compile_document(doc)
        # The fixture keeps every key grant on ordinary actions, independently of NPC delivery.
        key_proofs = {proof for variant in doc["variants"] for proof in variant["key_proofs"]}
        action_grants = {effect["observation"] for action in doc["actions"] for outcome in action["outcomes"] for effect in outcome["effects"] if effect["kind"] == "grant_observation"}
        self.assertTrue(key_proofs <= action_grants)
        self.assertNotIn("keeper_slip", key_proofs)

    def test_runtime_capabilities_compose_with_personal_without_reinterpretation(self):
        personal = NightCasePersonalFormatTests().source()
        personal["communication"] = self.source()["communication"]
        compiled = compile_document(personal)
        self.assertEqual("night-city-case-compiler/2.4", compiled.compiler_version)
        self.assertEqual(personal, compiled.document())
        personal.pop("communication")
        self.assertEqual("night-city-case-compiler/2.3", compile_document(personal).compiler_version)


if __name__ == "__main__":
    unittest.main()
