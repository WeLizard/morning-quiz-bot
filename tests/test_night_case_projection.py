"""Visible action gating and explicit projections."""

import unittest
import json
from datetime import datetime, timedelta

from domain.night_case_engine import _initialize, step
from domain.night_case_projection import CommandIntent, MenuChoice, MenuForm, available_actions, project, quote_action
from domain.night_case_state import PlayerActor
from tests.test_night_case_engine import FIXTURE, NOW, player_cmd, setup, tick
from domain.night_case_v2_format import load_v2, compile_v2
from domain.night_case_engine import _initialize
from domain.night_case_state import rules_snapshot


class ProjectionTests(unittest.TestCase):
    def test_quote_accuse_and_vote_with_public_citation(self):
        case, rules, _, t = setup()
        actor = PlayerActor("account0")
        t = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "act", {"action_id": "inspect_desk"}, "inspect01"), now_utc=NOW)
        proof = next(k["observation_id"] for k in t.state.knowledge if k["account_id"] == actor.account_id and k["observation_id"].startswith("proof"))
        t = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "pin", {"observation_id": proof}, "publish1"), now_utc=NOW)
        board_id = t.state.public["board"][0]["id"]
        for idx in range(2): t = tick(case, rules, t.state, command_id=f"advance{idx}")
        opened = datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00"))
        t = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "seen", command_id="seen0000"), now_utc=opened)
        voter = PlayerActor("account1")
        t = step(case, rules, t.state, voter, player_cmd(t.state, voter.account_id, "seen", command_id="seen0001"), now_utc=opened)
        accused = quote_action(case, rules, t.state, actor, CommandIntent("accuse", {"suspect": "person_10", "citations": [board_id]}), now_utc=opened)
        self.assertEqual(accused.kind, "accuse")
        t = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "accuse", {"suspect": "person_10", "citations": [board_id]}, "accuse01"), now_utc=opened)
        voted = quote_action(case, rules, t.state, voter, CommandIntent("vote", {"hearing_id": t.state.hearing["id"], "choice": "support", "citations": [board_id]}), now_utc=opened)
        self.assertEqual(voted.kind, "vote")

    def test_the_accused_may_object_but_not_support_the_accusation_of_their_own_hero(self):
        """Finding 3: the accused keeps the vote form, but only «Возражаю» is accepted from them."""
        case, rules, _, t = setup()
        actor, accused = PlayerActor("account0"), PlayerActor("account1")
        for idx in range(2): t = tick(case, rules, t.state, command_id=f"advance{idx}")
        opened = datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00"))
        for account in ("account0", "account1"):
            t = step(case, rules, t.state, PlayerActor(account), player_cmd(t.state, account, "seen", command_id=f"seen{account[-1]}000"), now_utc=opened)
        hero = next(p["character_id"] for p in t.state.players if p["account_id"] == accused.account_id)
        t = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "accuse", {"suspect": hero, "citations": []}, "accuse01"), now_utc=opened)
        hearing = t.state.hearing["id"]
        with self.assertRaises(ValueError):
            quote_action(case, rules, t.state, accused, CommandIntent("vote", {"hearing_id": hearing, "choice": "support", "citations": []}), now_utc=opened)
        self.assertEqual(quote_action(case, rules, t.state, accused, CommandIntent("vote", {"hearing_id": hearing, "choice": "oppose", "citations": []}), now_utc=opened).kind, "vote")
        forms = [e for e in available_actions(case, rules, t.state, accused, now_utc=opened) if isinstance(e, MenuForm)]
        self.assertIn("vote", [form.command_kind for form in forms])
        # Others may still support it.
        self.assertEqual(quote_action(case, rules, t.state, actor, CommandIntent("vote", {"hearing_id": hearing, "choice": "support", "citations": []}), now_utc=opened).kind, "vote")

    def test_quote_flag_predicate_uses_json_dependency(self):
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        raw["flags"] = [{"id": "lamp_lit", "initial": True}]
        raw["actions"][0]["available_when"] = [{"kind": "flag_is", "flag": "lamp_lit", "value": True}]
        case = compile_v2(load_v2(json.dumps(raw, ensure_ascii=False).encode()))
        rules = rules_snapshot("Europe/Berlin")
        roster = {"players": [{"account_id": f"account{i}", "display_name": f"Player {i}"} for i in range(4)], "npc_name_pool": [f"NPC {i}" for i in range(20)]}
        t = _initialize(case, rules, roster, game_id="flagquote", seed=42, composition_id="players_04", selected_variant_id="variant_a", now_utc=NOW)
        quote = quote_action(case, rules, t.state, PlayerActor("account0"), CommandIntent("act", {"action_id": "inspect_desk"}), now_utc=NOW)
        self.assertEqual(quote.kind, "act")

    def test_quote_npc_dialogue_cursor_uses_json_dependency(self):
        case, rules, _, t = setup()
        actor = PlayerActor("account0")
        moved = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "move", {"location": "platform"}, "move0001"), now_utc=NOW)
        quote = quote_action(case, rules, moved.state, actor, CommandIntent("talk", {"dialogue_id": "station_talk", "node_id": "opening", "option_id": "ask"}), now_utc=NOW)
        self.assertEqual(quote.kind, "talk")
    def test_variant_canary_menu_and_quote(self):
        case, rules, roster, a = setup(4, "variant_a")
        b = _initialize(case, rules, roster, game_id="testgame", seed=42, composition_id="players_04", selected_variant_id="variant_b", now_utc=NOW)
        actor = PlayerActor("account0")
        menu_a = available_actions(case, rules, a.state, actor, now_utc=NOW)
        menu_b = available_actions(case, rules, b.state, actor, now_utc=NOW)
        self.assertEqual(menu_a, menu_b)
        quote_a = quote_action(case, rules, a.state, actor, CommandIntent("act", {"action_id": "inspect_desk"}), now_utc=NOW)
        quote_b = quote_action(case, rules, b.state, actor, CommandIntent("act", {"action_id": "inspect_desk"}), now_utc=NOW)
        self.assertEqual(quote_a, quote_b)
        self.assertTrue(any(isinstance(x, MenuChoice) and x.quote.kind == "act" for x in menu_a))
        self.assertTrue(any(isinstance(x, MenuForm) and x.command_kind == "claim" for x in menu_a))

    def test_quote_only_relevant_revision_and_deadline(self):
        case, rules, _, t = setup()
        actor0, actor1 = PlayerActor("account0"), PlayerActor("account1")
        intent = CommandIntent("act", {"action_id": "inspect_desk"})
        before = quote_action(case, rules, t.state, actor0, intent, now_utc=NOW)
        other = step(case, rules, t.state, actor1, player_cmd(t.state, "account1", "seen"), now_utc=NOW)
        after = quote_action(case, rules, other.state, actor0, intent, now_utc=NOW)
        self.assertEqual(before, after)
        with self.assertRaisesRegex(ValueError, "deadline_pending"):
            quote_action(case, rules, t.state, actor0, intent, now_utc=NOW + timedelta(days=2))

    def test_public_projection_excludes_sealed_and_private(self):
        case, rules, _, t = setup()
        public = project(case, rules, t.state)
        self.assertNotIn("sealed", public)
        self.assertNotIn("knowledge", public)
        self.assertNotIn("private_events", public)
        self.assertNotIn("location", public["players"][0])
        self.assertIn("body", public["observations"][0])
        self.assertIn("title", public["observations"][0])
        self.assertNotIn("true_in", public["observations"][0])
        own = project(case, rules, t.state, PlayerActor("account0"))
        self.assertIn("self", own)
        self.assertNotIn("sealed", own)
        self.assertEqual(own["self"]["ap"], 3)

    def test_postmortem_is_participant_only_and_has_authored_text(self):
        case, rules, _, t = setup()
        actor = PlayerActor("account0")
        for idx in range(14):
            now = datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00"))
            t = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "seen", command_id=f"seen{idx:04d}"), now_utc=now)
            t = tick(case, rules, t.state, command_id=f"advance{idx:02d}")
        public = project(case, rules, t.state)
        own = project(case, rules, t.state, actor)
        self.assertEqual(set(public["final"]), {"code", "at"})
        self.assertEqual(own["self"]["postmortem"]["ending"], case.document()["endings"]["unresolved"])
        self.assertIsNotNone(own["self"]["postmortem"]["variant_final_text"])
        # «Who was who» (MQB-012 screen 14): every seat with its side; the culprit by role, also when the game leads that hero.
        cast = own["self"]["postmortem"]["cast"]
        self.assertEqual({row["account_id"] for row in cast if row["controller"] == "player"}, {p["account_id"] for p in t.state.players})
        variant = next(v for v in case.document()["variants"] if v["id"] == t.state.sealed["variant_id"])
        culprit = [row for row in cast if row["part"] == "culprit"]
        self.assertEqual([row["character_id"] for row in culprit], [variant["culprit"]])
        self.assertTrue(all(row["faction"] == "shadow" for row in cast if row["part"]))
        self.assertTrue(all(row["faction"] in {"investigation", "independent", "shadow"} for row in cast))
        self.assertNotIn("postmortem", public.get("self") or {})

    def test_private_variant_result_does_not_enter_public_events(self):
        case, rules, roster, a = setup(4, "variant_a")
        b = _initialize(case, rules, roster, game_id="testgame", seed=42, composition_id="players_04", selected_variant_id="variant_b", now_utc=NOW)
        actor = PlayerActor("account0")
        raw = player_cmd(a.state, actor.account_id, "act", {"action_id": "inspect_desk"})
        result_a = step(case, rules, a.state, actor, raw, now_utc=NOW)
        result_b = step(case, rules, b.state, actor, raw, now_utc=NOW)
        self.assertEqual(project(case, rules, result_a.state), project(case, rules, result_b.state))
        self.assertNotEqual(project(case, rules, result_a.state, actor)["self"]["knowledge"], project(case, rules, result_b.state, actor)["self"]["knowledge"])

    def test_authored_claim_board_materializes_speaker_without_truth(self):
        case, rules, _, t = setup()
        from domain.night_case_state import KernelState
        doc = t.state.document(); doc["players"][0]["status"] = "ghost"; doc["players"][0]["ap"] = 0
        state = KernelState.from_document(doc, case, rules)
        actor = PlayerActor("account0")
        out = step(case, rules, state, actor, player_cmd(state, actor.account_id, "ghost_share", {"observation_id": "public_note"}, "ghostsh1"), now_utc=NOW)
        board = project(case, rules, out.state)["board"][-1]
        authored = next(o for o in case.document()["observations"] if o["id"] == "public_note")
        self.assertEqual(board["observation"]["speaker"], authored["speaker"])
        self.assertEqual(board["observation"]["body"], authored["body"])
        self.assertNotIn("true_in", board["observation"])

    def test_ghost_menu_includes_public_memory_without_private_grant(self):
        case, rules, _, t = setup()
        from domain.night_case_state import KernelState
        doc = t.state.document(); doc["players"][0]["status"] = "ghost"; doc["players"][0]["ap"] = 0
        state = KernelState.from_document(doc, case, rules)
        actor = PlayerActor("account0")
        quote = quote_action(case, rules, state, actor, CommandIntent("ghost_share", {"observation_id": "public_note"}), now_utc=NOW)
        menu = available_actions(case, rules, state, actor, now_utc=NOW)
        self.assertIn(quote, [entry.quote for entry in menu if isinstance(entry, MenuChoice)])


if __name__ == "__main__":
    unittest.main()


class ModuleProjectionTests(unittest.TestCase):
    def test_theory_quotes_are_independent_and_noop_repeat_fail(self):
        from tests.test_night_case_engine import module_setup, module_play
        case, rules, t = module_setup()
        actor = PlayerActor("account0")
        theories = case.document()["module_data"]["version_archive"]["theories"]
        first, second = theories[0]["id"], theories[1]["id"]
        intent = CommandIntent("version_mark", {"version_id": first, "state": "archived"})
        quote = quote_action(case, rules, t.state, actor, intent, now_utc=NOW)
        t = module_play(case, rules, t, "version_mark", {"version_id": second, "state": "archived"}, "account1")
        self.assertEqual(quote, quote_action(case, rules, t.state, actor, intent, now_utc=NOW))
        t = module_play(case, rules, t, "version_mark", intent.params)
        self.assertTrue(t.receipt["accepted"])
        self.assertEqual(t.state.players[0]["ap"], 3)
        self.assertEqual(module_play(case, rules, t, "version_mark", intent.params).receipt["code"], "action_unavailable")
        self.assertEqual(module_play(case, rules, t, "version_mark", {"version_id": first, "state": "active"}).receipt["code"], "action_unavailable")
        t = tick(case, rules, t.state)
        t = module_play(case, rules, t, "version_mark", {"version_id": first, "state": "active"})
        self.assertTrue(t.receipt["accepted"])
        self.assertEqual(next(x for x in project(case, rules, t.state)["modules"]["version_archive"]["theories"] if x["id"] == first)["state"], "active")

    def test_hidden_npc_shared_gate_and_variant_independent_menu(self):
        from tests.test_night_case_engine import module_setup, module_play
        def dialogue(c): c["dialogues"][0]["character"] = "missing_keeper"
        states = []
        for variant in ("variant_a", "variant_b"):
            case, rules, t = module_setup(variant=variant, mutate=dialogue)
            for location in ("platform", "office"): t = module_play(case, rules, t, "move", {"location": location})
            actor = PlayerActor("account0")
            self.assertNotIn("missing_keeper", [x["character_id"] for x in project(case, rules, t.state, actor)["self"]["nearby"]])
            intent = CommandIntent("talk", {"dialogue_id": "station_talk", "node_id": "opening", "option_id": "ask"})
            with self.assertRaisesRegex(ValueError, "action_unavailable"): quote_action(case, rules, t.state, actor, intent, now_utc=NOW)
            self.assertEqual(module_play(case, rules, t, "talk", intent.params).receipt["code"], "action_unavailable")
            states.append((case, rules, t, available_actions(case, rules, t.state, actor, now_utc=NOW)))
        self.assertEqual(states[0][3], states[1][3])
        case, rules, t, _ = states[0]
        t = module_play(case, rules, t, "act", {"action_id": "search_office"})
        self.assertIn("missing_keeper", [x["character_id"] for x in project(case, rules, t.state, PlayerActor("account0"))["self"]["nearby"]])

    def test_module_views_whitelist_art_and_knowledge(self):
        from tests.test_night_case_engine import module_setup, module_play
        def noart(c):
            for l in c["locations"]: l.pop("art", None)
        case, rules, t = module_setup(mutate=noart)
        view = project(case, rules, t.state, PlayerActor("account0"))
        self.assertTrue(all(l["art"] is None for l in view["locations"]))
        self.assertEqual(view["self"]["modules"]["version_archive"]["comparisons"], [])
        self.assertTrue(all(not th["links"] for th in view["modules"]["version_archive"]["theories"]))
        public = json.dumps(project(case, rules, t.state))
        for key in ("placements", "responses", "outcomes", "open_when", "revealed_flag", "observation_ids"):
            self.assertNotIn('"' + key + '"', json.dumps(view["modules"]))
        self.assertNotIn('"self"', public)
        t = module_play(case, rules, t, "archive_request", {"query_id": "register_query"})
        self.assertEqual(project(case, rules, t.state, PlayerActor("account1"))["self"]["modules"]["archive_requests"]["requests"], [])
        t = tick(case, rules, t.state)
        self.assertEqual(len(project(case, rules, t.state, PlayerActor("account0"))["self"]["modules"]["version_archive"]["comparisons"]), 1)


class PersonalProjectionTests(unittest.TestCase):
    def test_original_race_does_not_invalidate_foreign_quote_or_leak_journal(self):
        from tests.test_night_case_engine import personal_setup, personal_act
        case, rules, t, actors = personal_setup()
        viewer = PlayerActor(actors["person_02"])
        intent = CommandIntent("act", {"action_id": "act_read_original"})
        before = quote_action(case, rules, t.state, viewer, intent, now_utc=NOW)
        t = personal_act(case, rules, t, actors, "person_00", "read_original")
        t = personal_act(case, rules, t, actors, "person_00", "take_original")
        after = quote_action(case, rules, t.state, viewer, intent, now_utc=NOW)
        self.assertEqual(before, after)
        view = project(case, rules, t.state, viewer)
        personal = view["self"]["personal"]
        self.assertEqual(set(personal), {"criteria", "completed_steps", "pending_returns", "booked_trips", "work_progress", "lost_observations"})
        self.assertEqual(personal["completed_steps"], [])
        self.assertEqual(personal["lost_observations"], [])  # taken, not destroyed
        self.assertNotIn("personal", project(case, rules, t.state))
        self.assertNotIn("personal_story", json.dumps(view))
        self.assertNotIn('"journal"', json.dumps(view))
        self.assertNotIn('"seq"', json.dumps(view))

    def test_reply_quotes_are_concrete_own_offers_and_capability_gated(self):
        from tests.test_night_case_engine import personal_setup, personal_act
        case, rules, t, actors = personal_setup()
        t = personal_act(case, rules, t, actors, "person_01", "return_letter")
        recipient = PlayerActor(actors["person_02"])
        choices = [m for m in available_actions(case, rules, t.state, recipient, now_utc=NOW) if isinstance(m, MenuChoice) and m.quote.kind == "story_reply"]
        self.assertEqual(len(choices), 2)
        self.assertEqual({json.loads(m.quote.params)["accept"] for m in choices}, {False, True})
        self.assertTrue(all(m.quote.cost == 0 for m in choices))
        for char in ("person_00", "person_01", "person_03"):
            self.assertFalse(any(isinstance(m, MenuChoice) and m.quote.kind == "story_reply" for m in available_actions(case, rules, t.state, PlayerActor(actors[char]), now_utc=NOW)))
        case, rules, t = __import__("tests.test_night_case_engine", fromlist=["module_setup"]).module_setup()
        with self.assertRaisesRegex(ValueError, "action_unavailable"):
            quote_action(case, rules, t.state, PlayerActor("account0"), CommandIntent("story_reply", {"offer_event_id": "event:12345678", "accept": True}), now_utc=NOW)


class MenuMaterializationTests(unittest.TestCase):
    def test_menu_validates_snapshot_once_and_matches_public_quotes(self):
        from unittest.mock import patch
        from domain.night_case_state import KernelState
        from tests.test_night_case_engine import personal_setup
        case, rules, t, actors = personal_setup()
        actor = PlayerActor(actors["person_01"])
        # A snapshot not produced by from_document is validated exactly once per menu;
        # one already validated for this case and rules is not validated again.
        plain = KernelState(t.state.document(), ruleset_version=case.document()["ruleset_ref"]["version"])
        with patch.object(KernelState, "from_document", wraps=KernelState.from_document) as validate:
            menu = available_actions(case, rules, plain, actor, now_utc=NOW)
            self.assertEqual(validate.call_count, 1)
        with patch.object(KernelState, "from_document", wraps=KernelState.from_document) as validate:
            self.assertEqual(available_actions(case, rules, t.state, actor, now_utc=NOW), menu)
            self.assertLessEqual(validate.call_count, 1)
        for entry in menu:
            if isinstance(entry, MenuChoice):
                intent = CommandIntent(entry.quote.kind, json.loads(entry.quote.params))
                with patch.object(KernelState, "from_document", wraps=KernelState.from_document) as validate:
                    self.assertEqual(entry.quote, quote_action(case, rules, plain, actor, intent, now_utc=NOW))
                    self.assertEqual(validate.call_count, 1)


class DeliveryProjectionTests(unittest.TestCase):
    def test_communication_forms_own_quota_and_concrete_revision_are_private(self):
        from tests.test_night_case_engine import runtime_setup, say
        from domain.night_case_projection import SayForm
        case, rules, t = runtime_setup()
        actor = PlayerActor("account0")
        intent = CommandIntent("say", {"channel": "square", "recipients": [], "text": "hello"})
        quote = quote_action(case, rules, t.state, actor, intent, now_utc=NOW)
        t = say(case, rules, t, text="someone else's say", account="account1")
        self.assertEqual(quote, quote_action(case, rules, t.state, actor, intent, now_utc=NOW))
        view = project(case, rules, t.state, actor)
        self.assertEqual(view["self"]["communication"], {"max_messages_per_window": 20, "sent_this_window": 0, "remaining": 20})
        self.assertNotIn("communication", project(case, rules, t.state))
        forms = [e for e in available_actions(case, rules, t.state, actor, now_utc=NOW) if isinstance(e, SayForm)]
        self.assertEqual({e.channel for e in forms}, {"square", "whisper"})
        self.assertEqual(next(e.cost for e in forms if e.channel == "whisper"), 1)
        self.assertNotIn(t.state.players[0]["character_id"], next(e.subject_ids for e in forms if e.channel == "whisper"))
        t = say(case, rules, t, text="own say")
        self.assertNotEqual(quote.resource_revision, quote_action(case, rules, t.state, actor, intent, now_utc=NOW).resource_revision)
        self.assertEqual(project(case, rules, t.state, actor)["self"]["communication"]["remaining"], 19)
        self.assertNotIn("someone else's say", json.dumps(view))

    def test_whisper_candidate_locations_stale_quote_and_hidden_npc_are_gated(self):
        from tests.test_night_case_engine import runtime_setup, say, module_play
        case, rules, t = runtime_setup()
        actor = PlayerActor("account0")
        target = t.state.players[1]["character_id"]
        intent = CommandIntent("say", {"channel": "whisper", "recipients": [target], "text": "private"})
        quote_action(case, rules, t.state, actor, intent, now_utc=NOW)
        t = module_play(case, rules, t, "move", {"location": "yard"}, "account1")
        with self.assertRaisesRegex(ValueError, "action_unavailable"): quote_action(case, rules, t.state, actor, intent, now_utc=NOW)
        self.assertEqual(say(case, rules, t, "whisper", [target]).receipt["code"], "action_unavailable")
        for cid in ("missing_keeper", t.state.players[0]["character_id"]):
            with self.assertRaisesRegex(ValueError, "action_unavailable"):
                quote_action(case, rules, t.state, actor, CommandIntent("say", {"channel": "whisper", "recipients": [cid], "text": "probe"}), now_utc=NOW)
        case, rules, t = __import__("tests.test_night_case_engine", fromlist=["module_setup"]).module_setup()
        with self.assertRaisesRegex(ValueError, "action_unavailable"):
            quote_action(case, rules, t.state, actor, CommandIntent("say", {"channel": "square", "recipients": [], "text": "no capability"}), now_utc=NOW)

    def test_npc_seed_line_chance_and_decision_are_not_projected_or_quoted(self):
        from tests.test_night_case_engine import runtime_setup, ready_keeper, module_play, KEEPER_TALK
        case, rules, t = runtime_setup()
        t = ready_keeper(case, rules, t)
        actor = PlayerActor("account0")
        now = datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00"))
        quote = quote_action(case, rules, t.state, actor, CommandIntent("talk", KEEPER_TALK), now_utc=now)
        t = module_play(case, rules, t, "talk", KEEPER_TALK)
        view = project(case, rules, t.state, actor)
        for secret in ("npc_delivery", "decisions", "line_id", "probability_bp", "draw", "keeper_rule", "keeper_line_a", "keeper_line_b"):
            self.assertNotIn(secret, json.dumps(view))
            self.assertNotIn(secret, repr(quote))
        result = next(e for e in view["self"]["private_events"] if e["kind"] == "action_result" and e["payload"]["observation_ids"] == ["keeper_slip"])
        self.assertIn("\n", result["payload"]["body"]["text"])
