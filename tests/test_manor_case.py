"""Authored Manor acceptance through production quote/step; no test-owned effects."""
import hashlib
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from domain.night_case_engine import _initialize, step
from domain.night_case_projection import CommandIntent, available_actions, project, quote_action
from domain.night_case_simulation import _route, SearchBudget, find_witness, replay_witness
from domain.night_case_state import PlayerActor, SystemActor, encode_state, rules_snapshot
from domain.night_case_v2_format import compile_v2, load_v2

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "content/night_city/manor_lake.case.json"
RAW = json.loads(PATH.read_text(encoding="utf8"))
CASE = compile_v2(load_v2(PATH.read_bytes()))
RULES = rules_snapshot("Europe/Berlin")
START = datetime(2026, 11, 15, 10, tzinfo=timezone.utc)


class Play:
    """Command/clock driver retaining actual transitions for subsequent witness replay."""
    def __init__(self, count=12, variant="variant_a"):
        self.roster = {"players": [{"account_id": f"actor{i:02d}", "display_name": f"Игрок {i:02d}"} for i in range(count)], "npc_name_pool": [f"Гость {i:02d}" for i in range(20)]}
        self.variant, self.composition = variant, f"manor_{count}"
        self.game_id, self.seed = "manor_acceptance", 42
        self.t = _initialize(CASE, RULES, self.roster, game_id=self.game_id, seed=self.seed, composition_id=self.composition, selected_variant_id=variant, now_utc=START)
        self.now, self.seq, self.steps = START, 0, []
        self.keep = {"investigator", "daughter"}

    @property
    def doc(self):
        return self.t.state.document()

    def player(self, char):
        return next(p for p in self.doc["players"] if p["character_id"] == char)

    def apply(self, actor, command):
        self.t = step(CASE, RULES, self.t.state, actor, command, now_utc=self.now)
        assert self.t.receipt["accepted"], self.t.receipt
        trusted = {"kind": "player", "account_id": actor.account_id} if isinstance(actor, PlayerActor) else {"kind": "system"}
        self.steps.append({"actor": trusted, "command": command, "now_utc": self.now.isoformat().replace("+00:00", "Z"), "expected_receipt": self.t.receipt, "expected_messages": list(self.t.messages), "state_hash": hashlib.sha256(encode_state(self.t.state)).hexdigest()})
        return self.t

    def cmd(self, char, kind, params=None):
        self.keep.add(char)
        p, clock = self.player(char), self.doc["clock"]
        actor = PlayerActor(p["account_id"])
        quote_action(CASE, RULES, self.t.state, actor, CommandIntent(kind, params or {}), now_utc=self.now)
        self.seq += 1
        return self.apply(actor, {"command_id": f"accept_{self.seq}", "kind": kind, "params": params or {}, "window_idx": clock["window_idx"], "window_seq": clock["window_seq"], "actor_seq": p["actor_seq"]})

    def tick(self):
        if self.doc["final"]:
            return
        for char in sorted(self.keep):
            p = self.player(char)
            if p["status"] in {"active", "fog"} and p["last_seen_window"] != self.doc["clock"]["window_idx"]:
                self.cmd(char, "seen")
        due, clock = self.t.due, self.doc["clock"]
        self.now = datetime.fromisoformat(due["at"].replace("Z", "+00:00"))
        self.seq += 1
        self.apply(SystemActor(), {"command_id": f"clock_{self.seq:06d}", "kind": "system.tick", "window_seq": clock["window_seq"], "timer_seq": clock["timer_seq"], "params": {"expected_due_at": due["at"]}})

    def ap(self, char):
        self.keep.add(char)
        if self.player(char)["status"] == "fog":
            self.cmd(char, "seen")
        if self.player(char)["ap"] < 1:
            self.tick()
        assert not self.doc["final"]

    def go(self, char, location):
        self.keep.add(char)
        while self.player(char)["location"] != location:
            self.ap(char)
            path = _route(RAW, self.doc, self.player(char)["location"], location)
            assert path
            while any(lock["location"] == path[0] for lock in self.doc["public"]["locks"]):
                self.tick()
            self.cmd(char, "move", {"location": path[0]})

    def act(self, char, action):
        self.go(char, next(a["location"] for a in RAW["actions"] if a["id"] == action))
        self.ap(char)
        return self.cmd(char, "act", {"action_id": action})

    def read(self, char, obs, publish=False):
        self.act(char, "inspect_" + obs)
        if publish:
            self.cmd(char, "pin", {"observation_id": obs})

    def find_rights(self):
        """The daughter has to learn where to look before she can find the original appendix."""
        for obs in ["official_will_copy", "will_register_copy"]:
            self.read("daughter", obs)
        return self.act("daughter", "act_find_rights")

    def until(self, window):
        while not self.doc["final"] and self.doc["clock"]["window_idx"] < window:
            self.tick()

    def finish(self):
        while not self.doc["final"]:
            self.tick()

    def goal(self, char):
        account = self.player(char)["account_id"]
        return next(row["met"] for row in self.doc["final"]["goal_results"] if row["account_id"] == account)

    def verified_witness(self):
        prefix = [{key: row[key] for key in ["actor", "command", "now_utc"]} for row in self.steps]
        result = find_witness(CASE, RULES, self.composition, self.variant, seed=self.seed,
                              start_at=START.isoformat().replace("+00:00", "Z"),
                              roster=self.roster, game_id=self.game_id, prefix_steps=prefix,
                              budget=SearchBudget(max_seconds=10))
        assert result.status == "found", (result.status, result.reason)
        actual = result.witness.document()["steps"]
        assert len(actual) == len(self.steps), "The completed prefix should need no extra commands"
        for source, replayed in zip(self.steps, actual):
            for key in ["actor", "command", "expected_receipt", "expected_messages", "state_hash"]:
                assert replayed[key] == source[key], key
        assert replay_witness(CASE, RULES, result.witness).passed
        return result.witness

    def collect_a(self):
        for key, sources in [("a1", ["draft_copy", "will_register_copy"]), ("a2", ["key_ledger"]), ("a3", ["lawyer_receipt", "bolt_order"])]:
            for obs in sources:
                self.read("investigator", obs)
            self.act("investigator", "compare_" + key)
            self.cmd("investigator", "pin", {"observation_id": key})

    def hearing(self, final=False):
        self.until(14 if final else max(3, self.doc["clock"]["window_idx"]))
        citations = [b["id"] for b in self.doc["public"]["board"] if b["observation_id"] in {"a1", "a2", "a3"}]
        active = [p["character_id"] for p in self.doc["players"] if p["status"] == "active"]
        if final:
            for char in active:
                self.cmd(char, "final_vote", {"suspect": "lawyer", "citations": citations})
        else:
            self.cmd("investigator", "accuse", {"suspect": "lawyer", "citations": citations})
            for char in active:
                self.cmd(char, "vote", {"hearing_id": self.doc["hearing"]["id"], "choice": "support", "citations": []})
        self.tick()
        if not final:
            while self.doc["hearing"] is not None and self.doc["final"] is None:
                self.tick()


class ManorSemantics(unittest.TestCase):
    def test_archive_request_labels_are_distinct_and_explain_the_choice(self):
        queries = RAW['module_data']['archive_requests']['queries']
        will_register = next(
            query for query in queries
            if any('will_register_copy' in response.get('observations', []) for response in query['responses'])
        )
        self.assertEqual(will_register['id'], 'will_register')
        expected = {
            'will_register': 'Копия реестра завещаний',
            'rounds_register': 'Копия журнала обходов',
            'owner_correspondence': 'Копия переписки хозяина',
            'invitation_register': 'Копия журнала приглашений',
        }
        labels = {query['id']: query['label'] for query in queries}
        self.assertEqual({key: labels[key] for key in expected}, expected)
        self.assertEqual(len(set(labels.values())), len(queries))

    def test_public_art_alt_uses_only_names_without_source_style_or_filename(self):
        for character in RAW['characters']:
            alt = character['art']['alt']
            self.assertEqual(alt, f"Портрет: {character['title']}")
            self.assertNotIn('.png', alt.lower())
            self.assertNotIn('noir_print_a', alt.lower())
        for location in RAW['locations']:
            alt = location['art']['alt']
            self.assertEqual(alt, location['name'])
            self.assertNotIn('.png', alt.lower())
            self.assertNotIn('noir_print_a', alt.lower())

    def test_character_speech_is_canonical_text_without_source_paths(self):
        speeches = {}
        for line in (ROOT / 'docs/tasks/night_city/worlds/canon/manor_lake.md').read_text(encoding='utf8').splitlines():
            cells = [cell.strip() for cell in line.strip('|').split('|')]
            if line.startswith('| `') and len(cells) == 11:
                speeches[cells[0].strip('`')] = cells[9]
        self.assertEqual(len(speeches), 20)
        for character in RAW['characters']:
            self.assertTrue(character['bio']['text'].endswith(' Речь: ' + speeches[character['id']]))
            self.assertNotIn('.png', character['bio']['text'])

    def test_cast_truth_compositions_and_immutable_owner(self):
        self.assertEqual(len(RAW["characters"]), 20)
        self.assertEqual(len(RAW["locations"]), 8)
        self.assertEqual([x["players"] for x in RAW["compositions"]], [4, 5, 8, 12])
        self.assertEqual([(v["culprit"], v["accomplices"]) for v in RAW["variants"]], [("lawyer", ["housekeeper"]), ("hunter", ["watchman"]), ("owner", [])])
        self.assertFalse(next(c for c in RAW["characters"] if c["id"] == "owner")["can_be_player"])
        self.assertEqual(RAW["module_data"]["turning_point"]["concealed_npcs"][0]["placements"], [{"variants": ["variant_a", "variant_b"], "location": "cellar"}, {"variants": ["variant_c"], "location": "tower_room"}])

    def test_three_independent_keys_include_distinctive_third_without_npc(self):
        obs = {o["id"]: o for o in RAW["observations"]}
        for v in RAW["variants"]:
            letter = v["id"][-1]
            self.assertEqual(v["key_proofs"], [letter + str(n) for n in [1, 2, 3]])
            self.assertEqual(v["required_key_proofs"], [letter + "3"])
            self.assertEqual(v["min_key"], 3)
            for key in v["key_proofs"]:
                self.assertEqual(obs[key]["kind"], "proof")
                self.assertEqual(obs[key]["exists_in"], [v["id"]])
                producer = next(a for a in RAW["actions"] if a["id"] == "compare_" + key)
                self.assertNotIn("personal_step", producer)
                self.assertTrue(all(g["kind"] == "knows" for g in producer["available_when"]))
        for key, words in [("a3", ["распоряжение", "адвоката"]), ("b3", ["приёмная отметка", "охотника"]), ("c3", ["разыгрываю сам", "самостоятельная"])]:
            for word in words:
                self.assertIn(word, obs[key]["body"]["text"].lower())

    def test_claims_debunks_and_goals_preserve_meaning(self):
        obs = {o["id"]: o for o in RAW["observations"]}
        self.assertEqual(obs["claim_owner_crossed_lake"]["kind"], "claim")
        self.assertEqual(next(f["true_in"] for f in RAW["facts"] if f["id"] == "fact_owner_crossed_lake"), "none")
        for key, word in [("ice_track_record", "не через озеро"), ("scarf_receipt", "врача"), ("both_wills_are_drafts", "рабочие")]:
            self.assertIn(word, obs[key]["body"]["text"])
        for char in RAW["characters"]:
            if char["can_be_player"] and char["id"] != "investigator":
                self.assertTrue(any(p["kind"].startswith("story_") for p in char["goal"]["when"]))
                self.assertIn("criteria", char["goal"])
        self.assertEqual(RAW["personal_tasks"]["works"][0]["stages"], ["underlayer", "likeness", "finish"])
        self.assertIn("вступившее в силу", RAW["personal_tasks"]["commitments"][1]["document"]["text"])


class ManorCommandAcceptance(unittest.TestCase):
    def test_passage_zero_one_two_clues(self):
        p = Play(4)
        opened = lambda: next(f["value"] for f in p.doc["public"]["flags"] if f["id"] == "route_opened")
        self.assertFalse(opened())
        p.read("investigator", "passage_key_spec", True)
        self.assertFalse(opened())
        p.read("investigator", "passage_plan")
        self.assertFalse(opened())
        p.cmd("investigator", "pin", {"observation_id": "passage_plan"})
        self.assertTrue(opened())
        p.go("investigator", "cellar")
        self.assertEqual(p.player("investigator")["location"], "cellar")

    def test_burn_preserves_knowledge_and_backup_really_solves(self):
        p = Play(4)
        for action in ["lawyer_read_draft", "lawyer_take_draft", "burn_original"]:
            p.act("lawyer", "act_" + action)
        retained = [k for k in p.doc["knowledge"] if k["observation_id"] == "will_original_section"]
        self.assertEqual(len(retained), 1)
        p.find_rights()
        self.assertEqual([e["payload"]["disposition"] for e in p.t.events if e["kind"] == "story_result"], ["not_completed"])
        p.collect_a()
        p.hearing()
        self.assertEqual(p.doc["final"]["code"], "solved")
        self.assertTrue(p.goal("lawyer"))
        self.assertFalse(p.goal("daughter"))
        self.assertEqual([k for k in p.doc["knowledge"] if k["observation_id"] == "will_original_section"], retained)
        self.assertEqual(p.verified_witness().document()["schema"], "night-city-witness/2")

    def test_recovery_and_late_cutoff_final_hearing(self):
        for late in [False, True]:
            with self.subTest(late=late):
                p = Play(4)
                p.collect_a()
                if late:
                    p.until(13)
                p.act("investigator", "search_cellar")
                if late:
                    self.assertIsNone(p.doc["final"])
                    p.hearing(True)
                self.assertEqual(p.doc["final"]["code"], "solved")
                self.assertEqual(p.verified_witness().document()["final_code"], "solved")

    def test_daughter_original_is_personal_and_competes_with_burn(self):
        p = Play(4)
        p.find_rights()
        for action in ["lawyer_read_draft", "lawyer_take_draft", "burn_original"]:
            p.act("lawyer", "act_" + action)
        p.finish()
        self.assertTrue(p.goal("daughter"))
        self.assertFalse(p.goal("lawyer"))

    def test_daughter_needs_both_copies_before_the_original(self):
        p = Play(4)
        ids = lambda: {row.quote.target_id for row in available_actions(CASE, RULES, p.t.state, PlayerActor(p.player("daughter")["account_id"]), now_utc=p.now) if row.kind == "choice" and row.quote.kind == "act"}
        self.assertNotIn("act_find_rights", ids())
        p.read("daughter", "official_will_copy")
        self.assertNotIn("act_find_rights", ids())
        p.read("daughter", "will_register_copy")
        p.act("daughter", "act_find_rights")
        p.finish()
        self.assertTrue(p.goal("daughter"))

    def scenes(self, p):
        return [e["payload"]["content_event_id"] for e in p.doc["public"]["chronicle"] if e["kind"] == "scene"]

    def test_found_owner_talks_and_silences_the_knock(self):
        quiet = Play(4)
        quiet.until(11)
        self.assertIn("ev_cellar_knock", self.scenes(quiet))
        p = Play(4)
        p.act("investigator", "search_cellar")
        reply = next(e for e in p.t.events if e["kind"] == "action_result")
        self.assertIn("хозяин усадьбы", reply["payload"]["body"]["text"])
        p.ap("investigator")
        talk = {"dialogue_id": "talk_owner", "node_id": "opening", "option_id": "ask_night"}
        p.cmd("investigator", "talk", talk)
        self.assertIn("owner_statement", {k["observation_id"] for k in p.doc["knowledge"] if k["account_id"] == p.player("investigator")["account_id"]})
        p.until(11)
        self.assertNotIn("ev_cellar_knock", self.scenes(p))

    def test_spent_talk_is_not_offered_again(self):
        p = Play(4)
        p.go("investigator", "kitchen_wing")
        p.ap("investigator")
        talk = {"dialogue_id": "talk_maid", "node_id": "opening", "option_id": "ask_night"}
        actor = PlayerActor(p.player("investigator")["account_id"])
        offered = lambda: [row.label for row in available_actions(CASE, RULES, p.t.state, actor, now_utc=p.now) if row.kind == "choice" and row.quote.kind == "talk" and "горничн" in row.label]
        self.assertEqual(offered(), ["Выслушать горничную"])
        p.cmd("investigator", "talk", talk)
        self.assertEqual(offered(), [])
        with self.assertRaises(ValueError):
            quote_action(CASE, RULES, p.t.state, actor, CommandIntent("talk", talk), now_utc=p.now)

    def test_texts_do_not_leak_the_variant_or_the_conclusion(self):
        titles = {o["id"]: o["title"].lower() for o in RAW["observations"]}
        for action in RAW["actions"]:
            for outcome in action.get("outcomes", []):
                self.assertNotRegex(outcome["body"]["text"], r"^[ABC]:")
                self.assertNotIn("осмотр завершён", outcome["body"]["text"])
                for effect in outcome["effects"]:
                    if action["id"].startswith("compare_") and effect["kind"] == "grant_observation":
                        self.assertNotEqual(action["label"].lower(), titles[effect["observation"]])
        labels = [o["label"] for d in RAW["dialogues"] for n in d["nodes"] for o in n["options"]]
        self.assertEqual(len(labels), len(set(labels)))

    def test_doctor_butler_housekeeper_investigator_actual_goals(self):
        p = Play()
        p.keep.update(["housekeeper", "doctor", "butler"])
        for obs in ["regimen_sample", "regimen_control"]:
            p.read("doctor", obs)
        p.act("doctor", "act_compare_regimen")
        for obs in ["daughter_rights_copy", "daughter_alibi"]:
            p.read("housekeeper", obs, True)
        p.act("housekeeper", "act_defend_daughter")
        p.go("daughter", "library")
        p.act("butler", "act_return_letter")
        offer = next(e for e in p.t.events if e["kind"] == "story_offer")
        p.cmd("daughter", "story_reply", {"offer_event_id": offer["event_id"], "accept": True})
        for obs in ["anonymous_invitation", "invitation_order_copy"]:
            p.read("investigator", obs)
        p.act("investigator", "compare_invitation_provenance")
        p.finish()
        for char in ["doctor", "butler", "housekeeper", "investigator"]:
            self.assertTrue(p.goal(char), char)
        self.assertFalse(p.goal("daughter"))

    def test_cook_gardener_gambler_artist_actual_goals(self):
        p = Play()
        p.keep.update(["cook", "gardener", "nephew_gambler", "niece_artist"])
        for obs in ["meal_order", "meal_receipt"]:
            p.read("cook", obs)
        p.act("cook", "act_compare_meals")
        p.act("cook", "act_keep_silent")
        for obs in ["cash_ledger", "cash_location"]:
            p.read("nephew_gambler", obs)
        p.act("nephew_gambler", "act_find_cash")
        for action in ["paint_underlayer", "paint_likeness", "paint_finish", "book_departure"]:
            p.act("niece_artist", "act_" + action)
        self.assertFalse(any(e["kind"] == "story_epilogue" for e in p.doc["private_events"]))
        p.until(11)
        p.act("gardener", "act_recover_cache")
        p.finish()
        for char in ["cook", "gardener", "nephew_gambler", "niece_artist"]:
            self.assertTrue(p.goal(char), char)

    def test_maid_companion_signed_results_and_no_npc_rewards(self):
        p = Play()
        p.keep.update(["maid", "companion"])
        p.act("maid", "read_maid_testimony")
        p.read("maid", "verified_sighting")
        p.act("maid", "act_submit_sighting")
        p.act("companion", "act_send_anonymous")
        p.act("companion", "act_send_conflicting")
        p.act("investigator", "search_cellar")
        self.assertIsNone(p.doc["final"])
        p.act("maid", "act_get_reference")
        p.act("companion", "act_secure_share")
        p.finish()
        self.assertTrue(p.goal("maid"))
        self.assertTrue(p.goal("companion"))
        self.assertEqual(len(p.doc["final"]["goal_results"]), 12)

    def test_private_sources_story_chronology_and_authorship_are_not_public(self):
        p = Play()
        p.read("lawyer", "intrigue_authorship_card")
        p.act("companion", "act_send_anonymous")
        view = project(CASE, RULES, p.t.state, PlayerActor(p.player("daughter")["account_id"]))
        text = json.dumps(view, ensure_ascii=False, default=lambda x: x.__dict__)
        for canary in ["Компаньонка изготовила анонимные письма", "personal_story", "journal", "intrigue_authorship_card"]:
            self.assertNotIn(canary, text)
        self.assertIn("Одним достанутся бумаги", text)
        self.assertTrue(p.doc["personal_story"]["journal"])

    def test_authored_npc_variations_are_private_claims_not_key_proofs(self):
        p = Play(4)
        p.read("investigator", "undeveloped_plate")
        p.ap("investigator")
        p.cmd("investigator", "talk", {"dialogue_id": "talk_photographer", "node_id": "opening", "option_id": "ask_night"})
        delivery = p.doc["npc_delivery"]
        self.assertEqual(len(delivery["lines"]), 1)
        self.assertEqual(len(delivery["decisions"]), 1)
        topic = next(t for t in RAW["npc_delivery"]["topics"] if t["npc"] == "photographer")
        result = next(e for e in p.t.events if e["kind"] == "action_result")
        self.assertTrue(any(result["payload"]["body"]["text"].startswith(line["body"]["text"] + "\n") for line in topic["lines"]))
        claim = next(o for o in RAW["observations"] if o["id"] == topic["slip"]["observation"])
        self.assertEqual((claim["kind"], claim["speaker"]), ("claim", "photographer"))
        self.assertTrue(all(claim["id"] not in v["key_proofs"] for v in RAW["variants"]))
        self.assertTrue(delivery["decisions"][0]["revealed"])  # Pinned seed/game/window, not a statistical assertion.
        heard = next(k for k in p.doc["knowledge"] if k["observation_id"] == claim["id"])
        self.assertEqual(heard["account_id"], p.player("investigator")["account_id"])
        self.assertEqual(heard["source"]["kind"], "dialogue")
        # The exact regular observation remains an authored claim even when an intro changes.
        self.assertIn("claim_light_proves_owner", {k["observation_id"] for k in p.doc["knowledge"] if k["account_id"] == p.player("investigator")["account_id"]})
        outsider = project(CASE, RULES, p.t.state, PlayerActor(p.player("daughter")["account_id"]))
        self.assertNotIn(claim["body"]["text"], json.dumps(outsider, ensure_ascii=False))
        menu = available_actions(CASE, RULES, p.t.state, PlayerActor(p.player("investigator")["account_id"]), now_utc=p.now)
        for visible in [outsider, menu]:
            text = json.dumps(visible, ensure_ascii=False, default=lambda x: x.__dict__)
            for forbidden in ["probability_bp", "photographer_slip_rule", "photographer_night_topic", "photographer_intro_1", "photographer_intro_2", '"draw":', '"revealed":']:
                self.assertNotIn(forbidden, text)

    def test_whisper_has_frozen_recipients_and_chat_witness_messages(self):
        p = Play(4)
        p.go("daughter", "main_hall")
        p.cmd("investigator", "say", {"channel": "whisper", "recipients": ["daughter"], "text": "Частный текст: сравним старую бумагу."})
        messages = list(p.t.messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(set(messages[0]["recipient_account_ids"]), {p.player(x)["account_id"] for x in ["investigator", "daughter"]})
        self.assertEqual(p.player("investigator")["ap"], 2)
        self.assertNotIn("Частный текст", json.dumps(p.doc, ensure_ascii=False))
        self.assertEqual(RAW["communication"], {"version": 1, "max_messages_per_window": 20})
        p.collect_a()
        p.hearing()
        witness = p.verified_witness().document()
        self.assertEqual(witness["schema"], "night-city-witness/2")
        self.assertEqual([m for row in witness["steps"] for m in row["expected_messages"]], messages)


if __name__ == "__main__":
    unittest.main()
