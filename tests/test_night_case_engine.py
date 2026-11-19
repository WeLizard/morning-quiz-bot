"""Core/1 transition tests, with no storage or transport dependencies."""

import unittest
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from domain.night_case_engine import _initialize, start, step
from domain.night_case_state import PlayerActor, SystemActor, decode_state, encode_state, rules_snapshot
from domain.night_case_v2_format import compile_v2, load_v2


FIXTURE = Path(__file__).parent / "fixtures" / "night_city" / "core_case_v2.json"
NOW = datetime(2026, 11, 15, 10, tzinfo=timezone.utc)


def setup(count=4, variant="variant_a"):
    case = compile_v2(load_v2(FIXTURE.read_bytes()))
    rules = rules_snapshot("Europe/Berlin")
    roster = {"players": [{"account_id": f"account{i}", "display_name": f"Player {i}"} for i in range(count)], "npc_name_pool": [f"NPC {i}" for i in range(20)]}
    transition = _initialize(case, rules, roster, game_id="testgame", seed=42, composition_id=f"players_{count:02d}", selected_variant_id=variant, now_utc=NOW)
    return case, rules, roster, transition


def player_cmd(state, account, kind, params=None, command_id="command01"):
    doc = state.document()
    p = next(p for p in doc["players"] if p["account_id"] == account)
    clock = doc["clock"]
    return {"command_id": command_id, "kind": kind, "window_idx": clock["window_idx"], "window_seq": clock["window_seq"], "actor_seq": p["actor_seq"], "params": params or {}}


def tick(case, rules, state, now=None, command_id="system001"):
    from domain.night_case_engine import _due
    due = _due(state.document())
    raw = {"command_id": command_id, "kind": "system.tick", "window_seq": state.clock["window_seq"], "timer_seq": state.clock["timer_seq"], "params": {"expected_due_at": due["at"]}}
    return step(case, rules, state, SystemActor(), raw, now_utc=now or datetime.fromisoformat(due["at"].replace("Z", "+00:00")))


class EngineTests(unittest.TestCase):
    def test_all_compositions_have_deterministic_assignments(self):
        for count in (4, 5, 8, 12):
            with self.subTest(players=count):
                case, rules, roster, t = setup(count)
                again = _initialize(case, rules, roster, game_id="testgame", seed=42, composition_id=f"players_{count:02d}", selected_variant_id="variant_a", now_utc=NOW)
                self.assertEqual(t.state.document(), again.state.document())
                self.assertEqual(len(t.state.players), count)
                self.assertEqual(len(t.state.npcs), 12 - count)

    def test_start_and_private_action_survive_codec(self):
        case, rules, roster, t = setup()
        self.assertEqual(t.state.clock["window_idx"], 1)
        self.assertEqual(t.state.players[0]["ap"], 3)
        self.assertEqual(len(t.state.public["observations"]), 1)
        t.events[0]["payload"]["window_idx"] = 99
        self.assertEqual(t.events[0]["payload"]["window_idx"], 1)
        t.due["at"] = "tampered"
        self.assertNotEqual(t.due["at"], "tampered")
        actor = PlayerActor("account0")
        raw = player_cmd(t.state, actor.account_id, "act", {"action_id": "inspect_desk"})
        a = step(case, rules, t.state, actor, raw, now_utc=NOW)
        self.assertTrue(a.receipt["accepted"])
        a.receipt["accepted"] = False
        self.assertTrue(a.receipt["accepted"])
        self.assertEqual(a.state.players[0]["ap"], 2)
        self.assertEqual(a.state.receipts[-1]["result_ref"]["kind"], "event")
        self.assertEqual(set(a.receipt), {"accepted", "code", "actor_revision"})
        restored = decode_state(encode_state(a.state), case, rules)
        self.assertEqual(restored.document(), a.state.document())
        replay = step(case, rules, restored, actor, raw, now_utc=NOW + timedelta(days=2))
        self.assertEqual(replay.receipt, a.receipt)
        self.assertEqual(replay.events, ())

    def test_independent_actor_fences_and_refusal_replay(self):
        case, rules, _, t = setup()
        a0, a1 = PlayerActor("account0"), PlayerActor("account1")
        first = step(case, rules, t.state, a0, player_cmd(t.state, a0.account_id, "seen"), now_utc=NOW)
        second = step(case, rules, first.state, a1, player_cmd(t.state, a1.account_id, "seen"), now_utc=NOW)
        self.assertTrue(second.receipt["accepted"])
        bad = player_cmd(second.state, a0.account_id, "move", {"location": "office"}, "command02")
        refused = step(case, rules, second.state, a0, bad, now_utc=NOW)
        self.assertEqual(refused.receipt["code"], "action_unavailable")
        self.assertEqual(step(case, rules, refused.state, a0, bad, now_utc=NOW + timedelta(days=2)).receipt, refused.receipt)
        changed = dict(bad); changed["params"] = {"location": "yard"}
        self.assertEqual(step(case, rules, refused.state, a0, changed, now_utc=NOW).receipt["code"], "command_id_conflict")

    def test_one_window_tick_and_timer_fence(self):
        case, rules, _, t = setup()
        nxt = tick(case, rules, t.state)
        self.assertEqual(nxt.state.clock["window_idx"], 2)
        self.assertEqual(nxt.state.clock["window_seq"], 2)
        self.assertEqual(nxt.state.clock["timer_seq"], 2)
        self.assertEqual(nxt.state.players[0]["missed_windows"], 1)
        self.assertEqual(nxt.state.clock["slot_cursor"]["local_time"], "19:00")

    def test_freeze_wake_and_forget_boundary(self):
        case, rules, _, t = setup()
        for idx in range(6):
            t = tick(case, rules, t.state, command_id=f"system{idx:03d}")
        self.assertEqual(t.state.clock["phase"], "frozen")
        self.assertEqual(t.state.clock["window_idx"], 7)
        self.assertTrue(all(p["status"] != "departed" for p in t.state.players))
        forget = datetime.fromisoformat(t.state.clock["forget_at"].replace("Z", "+00:00"))
        wake = step(case, rules, t.state, PlayerActor("account0"), player_cmd(t.state, "account0", "seen", command_id="wake0001"), now_utc=forget - timedelta(seconds=1))
        self.assertTrue(wake.receipt["accepted"])
        self.assertEqual(wake.state.clock["phase"], "investigation")
        self.assertEqual(wake.state.players[0]["status"], "active")
        forgotten = tick(case, rules, t.state, now=forget, command_id="forget001")
        self.assertEqual(forgotten.state.final["code"], "forgotten")

    def test_forfeit_creates_silent_former_player(self):
        case, rules, _, t = setup()
        actor = PlayerActor("account0")
        out = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "forfeit"), now_utc=NOW)
        self.assertEqual(out.state.players[0]["status"], "departed")
        former = next(n for n in out.state.npcs if n["character_id"] == out.state.players[0]["character_id"])
        self.assertEqual(former["origin"], "former_player")
        self.assertEqual(out.state.players[0]["ap"], 0)

    def test_forfeit_preserves_maximum_length_player_name(self):
        case, rules, roster, _ = setup()
        roster["players"][0]["display_name"] = "И" * 120
        t = _initialize(case, rules, roster, game_id="longname", seed=42, composition_id="players_04", selected_variant_id="variant_a", now_utc=NOW)
        actor = PlayerActor("account0")
        out = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "forfeit"), now_utc=NOW)
        former = next(n for n in out.state.npcs if n["character_id"] == out.state.players[0]["character_id"])
        self.assertEqual(former["name"], "И" * 120)

    def test_ordinary_hearing_can_solve_with_cited_proof(self):
        case, rules, _, t = setup()
        actor = PlayerActor("account0")
        t = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "act", {"action_id": "inspect_desk"}, "inspect01"), now_utc=NOW)
        proof = next(k["observation_id"] for k in t.state.knowledge if k["account_id"] == actor.account_id and k["observation_id"].startswith("proof"))
        t = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "pin", {"observation_id": proof}, "publish1"), now_utc=NOW)
        board_id = t.state.public["board"][0]["id"]
        for idx in range(2): t = tick(case, rules, t.state, command_id=f"advance{idx}")
        self.assertEqual(t.state.clock["window_idx"], 3)
        for idx in range(4):
            name = f"account{idx}"
            t = step(case, rules, t.state, PlayerActor(name), player_cmd(t.state, name, "seen", command_id=f"seen{idx:04d}"), now_utc=datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00")))
        t = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "accuse", {"suspect": "person_10", "citations": [board_id]}, "accuse01"), now_utc=datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00")))
        self.assertTrue(t.receipt["accepted"])
        t = tick(case, rules, t.state, command_id="advance02")
        for idx in range(3):
            name = f"account{idx}"
            t = step(case, rules, t.state, PlayerActor(name), player_cmd(t.state, name, "vote", {"hearing_id": t.state.hearing["id"], "choice": "support", "citations": []}, f"vote{idx:04d}"), now_utc=datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00")))
            self.assertTrue(t.receipt["accepted"])
        t = tick(case, rules, t.state, command_id="advance03")
        self.assertEqual(t.state.final["code"], "solved")

    def test_confirmed_outage_extends_one_window(self):
        case, rules, _, t = setup()
        initial = t.state.clock["closes_at"]
        now = NOW + timedelta(hours=30)
        raw = {"command_id": "resume001", "kind": "system.resume", "window_seq": 1, "timer_seq": 1, "params": {"outage_id": "outage01", "unavailable_from": NOW.isoformat().replace("+00:00", "Z"), "resumed_at": now.isoformat().replace("+00:00", "Z")}}
        resumed = step(case, rules, t.state, SystemActor(), raw, now_utc=now)
        self.assertTrue(resumed.receipt["accepted"])
        self.assertEqual(resumed.state.clock["window_idx"], 1)
        self.assertNotEqual(resumed.state.clock["closes_at"], initial)
        self.assertEqual(resumed.state.clock["window_seq"], 1)
        self.assertEqual(resumed.state.clock["timer_seq"], 2)
        self.assertEqual(step(case, rules, resumed.state, SystemActor(), raw, now_utc=now).receipt, resumed.receipt)

    def test_final_hearing_solved_without_extra_window(self):
        case, rules, _, t = setup()
        actor = PlayerActor("account0")
        t = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "act", {"action_id": "inspect_desk"}, "inspect01"), now_utc=NOW)
        proof = next(k["observation_id"] for k in t.state.knowledge if k["account_id"] == actor.account_id and k["observation_id"].startswith("proof"))
        t = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "pin", {"observation_id": proof}, "publish1"), now_utc=NOW)
        board_id = t.state.public["board"][0]["id"]
        for idx in range(13):
            opened = datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00"))
            if t.state.players[0]["last_seen_window"] != t.state.clock["window_idx"]:
                t = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "seen", command_id=f"seen{idx:04d}"), now_utc=opened)
            t = tick(case, rules, t.state, command_id=f"advance{idx:02d}")
        self.assertEqual(t.state.clock["phase"], "final_hearing")
        opened = datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00"))
        t = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "final_vote", {"suspect": "person_10", "citations": [board_id]}, "finalvote1"), now_utc=opened)
        self.assertTrue(t.receipt["accepted"])
        t = tick(case, rules, t.state, command_id="finaltick")
        self.assertEqual(t.state.final["code"], "solved")
        self.assertEqual(t.state.clock["window_idx"], 14)

    def test_wrong_accusation_removes_npc_without_ghost_player(self):
        case, rules, _, t = setup()
        for idx in range(2): t = tick(case, rules, t.state, command_id=f"advance{idx}")
        for idx in range(4):
            name = f"account{idx}"
            opened = datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00"))
            t = step(case, rules, t.state, PlayerActor(name), player_cmd(t.state, name, "seen", command_id=f"seen{idx:04d}"), now_utc=opened)
        actor = PlayerActor("account0")
        opened = datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00"))
        t = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "accuse", {"suspect": "person_11", "citations": []}, "accuse01"), now_utc=opened)
        t = tick(case, rules, t.state, command_id="advance02")
        for idx in range(3):
            name = f"account{idx}"
            opened = datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00"))
            t = step(case, rules, t.state, PlayerActor(name), player_cmd(t.state, name, "vote", {"hearing_id": t.state.hearing["id"], "choice": "support", "citations": []}, f"vote{idx:04d}"), now_utc=opened)
        t = tick(case, rules, t.state, command_id="advance03")
        self.assertIsNone(t.state.final)
        self.assertEqual(t.state.public["framed_count"], 1)
        self.assertEqual(next(n["status"] for n in t.state.npcs if n["character_id"] == "person_11"), "removed")
        self.assertEqual(len(t.state.players), 4)

    def test_final_without_majority_is_unresolved(self):
        case, rules, _, t = setup()
        actor = PlayerActor("account0")
        for idx in range(14):
            opened = datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00"))
            t = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "seen", command_id=f"seen{idx:04d}"), now_utc=opened)
            t = tick(case, rules, t.state, command_id=f"advance{idx:02d}")
        self.assertEqual(t.state.final["code"], "unresolved")
        self.assertEqual(t.state.clock["window_idx"], 14)

    def test_event_stream_ids_and_initial_digest(self):
        case, rules, _, t = setup()
        from domain.night_case_state import event_id_for
        streams = {}
        for event in list(t.state.public["chronicle"]) + list(t.state.private_events):
            audience = event["audience"]
            key = "public" if audience["kind"] == "public" else audience["ids"][0]
            streams.setdefault(key, []).append(event["audience_seq"])
            self.assertEqual(event["event_id"], event_id_for(t.state.game_id, audience, event["audience_seq"]))
            self.assertEqual(event["window_idx"], 1)
        self.assertTrue(all(sorted(seq) == list(range(1, len(seq) + 1)) for seq in streams.values()))
        digests = [e for e in t.state.private_events if e["kind"] == "window_digest"]
        self.assertEqual(len(digests), 4)
        self.assertTrue(all(e["payload"]["window_idx"] == 1 for e in digests))

    def test_opening_digest_and_afk_notice_reference_closed_window(self):
        case, rules, _, t = setup()
        opened = tick(case, rules, t.state)
        private = [e for e in opened.events if e["audience"]["kind"] == "accounts"]
        digests = [e for e in private if e["kind"] == "window_digest"]
        notices = [e for e in private if e["kind"] == "afk_notice"]
        self.assertEqual(len(digests), 4)
        self.assertEqual(len(notices), 4)
        self.assertTrue(all(e["window_idx"] == 2 and e["payload"]["window_idx"] == 1 for e in digests + notices))
        self.assertTrue(all(e["event_id"] not in e["payload"]["event_ids"] for e in digests))

    def test_world_changed_collapses_repeated_flag_effects(self):
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        raw["flags"] = [{"id": "lamp_lit", "initial": False}]
        effects = raw["actions"][0]["outcomes"][0]["effects"]
        effects.extend([{"kind": "set_flag", "flag": "lamp_lit", "value": True}, {"kind": "set_flag", "flag": "lamp_lit", "value": False}, {"kind": "set_flag", "flag": "lamp_lit", "value": True}])
        case = compile_v2(load_v2(json.dumps(raw, ensure_ascii=False).encode()))
        rules = rules_snapshot("Europe/Berlin")
        roster = {"players": [{"account_id": f"account{i}", "display_name": f"Player {i}"} for i in range(4)], "npc_name_pool": [f"NPC {i}" for i in range(20)]}
        t = _initialize(case, rules, roster, game_id="flaggame", seed=42, composition_id="players_04", selected_variant_id="variant_a", now_utc=NOW)
        self.assertEqual(t.state.public["flags"], [{"id": "lamp_lit", "value": False}])
        actor = PlayerActor("account0")
        out = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "act", {"action_id": "inspect_desk"}), now_utc=NOW)
        world = [e for e in out.events if e["kind"] == "world_changed"]
        self.assertEqual(len(world), 1)
        self.assertEqual(world[0]["payload"]["flags"], [{"id": "lamp_lit", "value": True}])

    def test_terminal_forfeit_cancels_open_hearing(self):
        case, rules, _, t = setup()
        for idx in range(2): t = tick(case, rules, t.state, command_id=f"advance{idx}")
        actor = PlayerActor("account0")
        opened = datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00"))
        t = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "seen", command_id="seen0000"), now_utc=opened)
        t = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "accuse", {"suspect": "person_11", "citations": []}, "accuse01"), now_utc=opened)
        for idx in range(4):
            name = f"account{idx}"
            t = step(case, rules, t.state, PlayerActor(name), player_cmd(t.state, name, "forfeit", command_id=f"forfeit{idx}"), now_utc=opened)
        self.assertEqual(t.state.final["code"], "no_investigators")
        self.assertIsNone(t.state.hearing)
        terminal = [e for e in t.events if e["kind"] in {"hearing", "final"}]
        self.assertEqual([e["kind"] for e in terminal], ["hearing", "final"])
        self.assertEqual(terminal[0]["payload"]["resolution"], "cancelled")

    def test_ghost_share_of_public_initial_is_accepted(self):
        case, rules, _, t = setup()
        doc = t.state.document()
        doc["players"][0]["status"] = "ghost"
        doc["players"][0]["ap"] = 0
        from domain.night_case_state import KernelState
        state = KernelState.from_document(doc, case, rules)
        actor = PlayerActor("account0")
        cmd = player_cmd(state, actor.account_id, "ghost_share", {"observation_id": "public_note"}, "ghostsh1")
        out = step(case, rules, state, actor, cmd, now_utc=NOW)
        self.assertTrue(out.receipt["accepted"])
        self.assertEqual(out.state.players[0]["ghost_used_window"], 1)
        self.assertEqual(out.state.public["board"][-1]["kind"], "claim")
        self.assertEqual(out.state.public["board"][-1]["observation_id"], "public_note")
        self.assertEqual(out.state.public["board"][-1]["source"], t.state.public["observations"][0]["source"])

    def test_pin_authored_claim_keeps_observation_and_source(self):
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        raw["initial"]["personal"].append({"character": "person_00", "observations": ["public_note"]})
        case = compile_v2(load_v2(json.dumps(raw, ensure_ascii=False).encode()))
        rules = rules_snapshot("Europe/Berlin")
        roster = {"players": [{"account_id": f"account{i}", "display_name": f"Player {i}"} for i in range(4)], "npc_name_pool": [f"NPC {i}" for i in range(20)]}
        t = _initialize(case, rules, roster, game_id="claimcase", seed=42, composition_id="players_04", selected_variant_id="variant_a", now_utc=NOW)
        owner = next(p["account_id"] for p in t.state.players if p["character_id"] == "person_00")
        source = next(k["source"] for k in t.state.knowledge if k["account_id"] == owner and k["observation_id"] == "public_note")
        out = step(case, rules, t.state, PlayerActor(owner), player_cmd(t.state, owner, "pin", {"observation_id": "public_note"}, "pinclaim1"), now_utc=NOW)
        board = out.state.public["board"][-1]
        self.assertEqual((board["kind"], board["observation_id"], board["text"], board["source"]), ("claim", "public_note", None, source))
        from domain.night_case_engine import _cited_keys
        self.assertEqual(_cited_keys(out.state.document(), case.document(), [board["id"]]), set())

    def test_other_player_digest_contains_pinned_authored_claim(self):
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        raw["initial"]["personal"].append({"character": "person_00", "observations": ["false_statement"]})
        case = compile_v2(load_v2(json.dumps(raw, ensure_ascii=False).encode()))
        rules = rules_snapshot("Europe/Berlin")
        roster = {"players": [{"account_id": f"account{i}", "display_name": f"Player {i}"} for i in range(4)], "npc_name_pool": [f"NPC {i}" for i in range(20)]}
        t = _initialize(case, rules, roster, game_id="claimdigest", seed=42, composition_id="players_04", selected_variant_id="variant_a", now_utc=NOW)
        owner = next(p["account_id"] for p in t.state.players if p["character_id"] == "person_00")
        other = next(p["account_id"] for p in t.state.players if p["account_id"] != owner)
        pinned = step(case, rules, t.state, PlayerActor(owner), player_cmd(t.state, owner, "pin", {"observation_id": "false_statement"}, "pinclaim1"), now_utc=NOW)
        board_event = next(e for e in pinned.events if e["kind"] == "board")
        opened = tick(case, rules, pinned.state)
        digest = next(e for e in opened.events if e["kind"] == "window_digest" and e["audience"]["ids"] == [other])
        self.assertIn(board_event["event_id"], digest["payload"]["event_ids"])
        self.assertIn("false_statement", digest["payload"]["observation_ids"])

    def test_resume_clears_old_early_ready_due(self):
        case, rules, _, t = setup()
        for idx in range(4):
            account = f"account{idx}"
            cmd = player_cmd(t.state, account, "finish_window", command_id=f"finish{idx:02d}")
            t = step(case, rules, t.state, PlayerActor(account), cmd, now_utc=NOW)
        self.assertEqual(t.due["reason"], "early")
        old_due = t.due["at"]
        now = NOW + timedelta(hours=30)
        raw = {"command_id": "resume001", "kind": "system.resume", "window_seq": t.state.clock["window_seq"], "timer_seq": t.state.clock["timer_seq"], "params": {"outage_id": "outage01", "unavailable_from": NOW.isoformat().replace("+00:00", "Z"), "resumed_at": now.isoformat().replace("+00:00", "Z")}}
        out = step(case, rules, t.state, SystemActor(), raw, now_utc=now)
        self.assertTrue(out.receipt["accepted"])
        self.assertEqual(out.state.clock["window_idx"], 1)
        self.assertNotEqual(out.due["at"], old_due)
        self.assertEqual(out.due["at"], out.state.clock["closes_at"])
        self.assertFalse(any(p["finished_window"] for p in out.state.players))

    def test_ready_due_changes_timer_without_invalidating_other_actor(self):
        case, rules, _, t = setup()
        from domain.night_case_state import KernelState
        doc = t.state.document(); doc["players"][3]["status"] = "fog"
        state = KernelState.from_document(doc, case, rules)
        old_independent = player_cmd(state, "account3", "seen", command_id="other003")
        for idx in range(3):
            account = f"account{idx}"
            t = step(case, rules, state, PlayerActor(account), player_cmd(state, account, "finish_window", command_id=f"finish{idx:02d}"), now_utc=NOW)
            state = t.state
        self.assertEqual(t.state.clock["window_seq"], 1)
        self.assertEqual(t.state.clock["timer_seq"], 2)
        accepted = step(case, rules, t.state, PlayerActor("account3"), old_independent, now_utc=NOW)
        self.assertTrue(accepted.receipt["accepted"])

    def test_frozen_forfeit_and_pending_window_reward_count(self):
        case, rules, _, t = setup()
        for idx in range(6): t = tick(case, rules, t.state, command_id=f"system{idx:03d}")
        actor = PlayerActor("account0")
        before = datetime.fromisoformat(t.state.clock["forget_at"].replace("Z", "+00:00")) - timedelta(seconds=1)
        out = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "forfeit", command_id="forfeit1"), now_utc=before)
        self.assertTrue(out.receipt["accepted"])
        final = tick(case, rules, out.state, now=datetime.fromisoformat(out.state.clock["forget_at"].replace("Z", "+00:00")), command_id="forget001")
        self.assertEqual(final.state.final["code"], "forgotten")
        self.assertTrue(all(f["total_windows"] == 6 for f in final.state.final["reward_facts"]))

    def test_individual_afk_four_departures_after_table_presence(self):
        case, rules, _, t = setup()
        actor = PlayerActor("account0")
        for idx in range(4):
            opened = datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00"))
            t = step(case, rules, t.state, actor, player_cmd(t.state, actor.account_id, "seen", command_id=f"seen{idx:04d}"), now_utc=opened)
            t = tick(case, rules, t.state, command_id=f"advance{idx:02d}")
        self.assertEqual(t.state.clock["window_idx"], 5)
        self.assertEqual(t.state.players[0]["status"], "active")
        self.assertTrue(all(p["status"] == "departed" for p in t.state.players[1:]))
        self.assertEqual(sum(n["origin"] == "former_player" for n in t.state.npcs), 3)


if __name__ == "__main__":
    unittest.main()


MODULE_FIXTURE = FIXTURE.with_name("modules_case_v2.json")


def module_setup(count=4, variant="variant_a", mutate=None):
    document = json.loads(MODULE_FIXTURE.read_bytes())
    if mutate: mutate(document)
    case = compile_v2(load_v2(json.dumps(document).encode()))
    rules = rules_snapshot("Europe/Berlin")
    roster = {"players": [{"account_id": f"account{i}", "display_name": f"Player {i}"} for i in range(count)], "npc_name_pool": [f"NPC {i}" for i in range(20)]}
    return case, rules, _initialize(case, rules, roster, game_id="modgame", seed=42, composition_id=f"players_{count:02d}", selected_variant_id=variant, now_utc=NOW)


def module_play(case, rules, t, kind, params=None, account="account0"):
    clock = t.state.clock
    now = datetime.fromisoformat((clock["opened_at"] or clock["freeze_at"]).replace("Z", "+00:00"))
    cid = "module" + str(len(t.state.receipts)).zfill(5)
    return step(case, rules, t.state, PlayerActor(account), player_cmd(t.state, account, kind, params, cid), now_utc=now)


class ModuleEngineTests(unittest.TestCase):
    def test_request_delivery_replay_codec_and_provenance(self):
        case, rules, t = module_setup()
        self.assertEqual(t.state.document()["engine_build"], "night-case-core/2")
        raw = player_cmd(t.state, "account0", "archive_request", {"query_id": "register_query"}, "request01")
        t = step(case, rules, t.state, PlayerActor("account0"), raw, now_utc=NOW)
        self.assertTrue(t.receipt["accepted"])
        self.assertEqual(t.state.players[0]["ap"], 2)
        req = next(e for e in t.events if e["kind"] == "archive_requested")
        restored = decode_state(encode_state(t.state), case, rules)
        self.assertEqual(step(case, rules, restored, PlayerActor("account0"), raw, now_utc=NOW + timedelta(days=10)).events, ())
        self.assertEqual(module_play(case, rules, t, "archive_request", {"query_id": "register_query"}).receipt["code"], "action_unavailable")
        t = tick(case, rules, t.state)
        response = next(e for e in t.events if e["kind"] == "archive_response")
        self.assertEqual(response["payload"]["request_event_id"], req["event_id"])
        self.assertEqual(response["window_idx"], 2)
        knowledge = next(k for k in t.state.knowledge if k["observation_id"] == "archive_copy")
        self.assertEqual(knowledge["source"], {"kind": "event", "source_id": req["event_id"], "actor_character": t.state.players[0]["character_id"], "location": None, "window_idx": 2})
        self.assertEqual(t.state.players[0]["actor_seq"], 1)
        self.assertEqual(t.state.players[0]["last_seen_window"], 1)
        self.assertEqual(decode_state(encode_state(t.state), case, rules).document(), t.state.document())
        self.assertLess(next(i for i,e in enumerate(t.events) if e["kind"] == "archive_response"), next(i for i,e in enumerate(t.events) if e["kind"] == "window_digest"))
        t = tick(case, rules, t.state, command_id="advance02")
        self.assertFalse(any(e["kind"] == "archive_response" for e in t.events))

    def test_forfeit_cancels_request_and_terminal_does_not_deliver(self):
        case, rules, t = module_setup()
        t = module_play(case, rules, t, "archive_request", {"query_id": "register_query"})
        t = module_play(case, rules, t, "forfeit")
        t = tick(case, rules, t.state)
        response = next(e for e in t.events if e["kind"] == "archive_response")
        self.assertEqual(response["payload"]["disposition"], "cancelled")
        self.assertIsNone(response["payload"]["body"])
        self.assertFalse(any(k["account_id"] == "account0" and k["observation_id"] == "archive_copy" for k in t.state.knowledge))
        case, rules, t = module_setup()
        t = module_play(case, rules, t, "archive_request", {"query_id": "register_query"})
        for p in list(t.state.players): t = module_play(case, rules, t, "forfeit", account=p["account_id"])
        self.assertIsNotNone(t.state.final)
        from domain.night_case_projection import project
        request = project(case, rules, t.state, PlayerActor("account0"))["self"]["modules"]["archive_requests"]["requests"][0]
        self.assertEqual(request["status"], "cancelled_terminal")

    def test_route_batch_and_late_pin_recovery(self):
        case, rules, t = module_setup()
        from domain.night_case_projection import project
        def connections(): return next(l["connects"] for l in project(case, rules, t.state)["locations"] if l["id"] == "foyer")
        self.assertNotIn("office", connections())
        for action, proof in (("inspect_key", "proof_common"), ("inspect_mechanism", "proof_mechanism")):
            t = module_play(case, rules, t, "act", {"action_id": action})
            t = module_play(case, rules, t, "pin", {"observation_id": proof})
            if proof == "proof_common": self.assertNotIn("office", connections())
        self.assertIn("office", connections())
        self.assertEqual(sum(e["kind"] == "world_changed" for e in t.events), 1)
        self.assertEqual(sum(e["kind"] == "scene" for e in t.events), 1)
        t = module_play(case, rules, t, "move", {"location": "office"})
        self.assertEqual(t.state.players[0]["ap"], 0)
        t = tick(case, rules, t.state)
        t = module_play(case, rules, t, "act", {"action_id": "search_office"})
        self.assertEqual(sum(e["kind"] == "npc_revealed" for e in t.events), 1)
        self.assertIsNone(t.state.final)
        t = module_play(case, rules, t, "move", {"location": "foyer"})
        t = module_play(case, rules, t, "archive_request", {"query_id": "register_query"})
        t = tick(case, rules, t.state, command_id="delivery02")
        t = module_play(case, rules, t, "act", {"action_id": "inspect_desk"})
        t = module_play(case, rules, t, "pin", {"observation_id": "proof_a"})
        self.assertEqual(t.state.final["code"], "solved")

    def test_wrong_room_paid_fallback_static_placement(self):
        case, rules, t = module_setup(variant="variant_b")
        for location in ("platform", "office"): t = module_play(case, rules, t, "move", {"location": location})
        t = module_play(case, rules, t, "act", {"action_id": "search_office"})
        self.assertTrue(t.receipt["accepted"])
        self.assertEqual(t.state.players[0]["ap"], 0)
        self.assertFalse(any(e["kind"] == "npc_revealed" for e in t.events))
        self.assertEqual(next(e["payload"]["body"] for e in t.events if e["kind"] == "action_result"), case.document()["actions"][3]["fallback"])
        t = tick(case, rules, t.state)
        self.assertEqual(next(n for n in t.state.npcs if n["character_id"] == "missing_keeper")["location"], "yard")


    def test_required_proof_blocks_both_hearings_with_enough_common_keys(self):
        def weaken(c):
            for v in c["variants"]: v["min_key"] = 2
        for final in (False, True):
            with self.subTest(final=final):
                case, rules, t = module_setup(mutate=weaken)
                for action, proof in (("inspect_key", "proof_common"), ("inspect_mechanism", "proof_mechanism")):
                    t = module_play(case, rules, t, "act", {"action_id": action})
                    t = module_play(case, rules, t, "pin", {"observation_id": proof})
                while t.state.clock["window_idx"] < (14 if final else 3):
                    for p in list(t.state.players): t = module_play(case, rules, t, "seen", account=p["account_id"])
                    t = tick(case, rules, t.state, command_id="advance" + str(t.state.clock["window_idx"]))
                citations = [b["id"] for b in t.state.public["board"]]
                if final:
                    for p in list(t.state.players): t = module_play(case, rules, t, "final_vote", {"suspect": "person_10", "citations": citations}, p["account_id"])
                    t = tick(case, rules, t.state, command_id="resolve01")
                    self.assertEqual(t.state.final["code"], "unresolved")
                else:
                    t = module_play(case, rules, t, "accuse", {"suspect": "person_10", "citations": citations})
                    hid = t.state.hearing["id"]
                    for p in list(t.state.players): t = module_play(case, rules, t, "vote", {"hearing_id": hid, "choice": "support", "citations": citations}, p["account_id"])
                    t = tick(case, rules, t.state, command_id="open0004")
                    for p in list(t.state.players): t = module_play(case, rules, t, "seen", account=p["account_id"])
                    t = tick(case, rules, t.state, command_id="resolve01")
                    self.assertIsNone(t.state.final)
                    self.assertTrue(any(e["kind"] == "hearing" and e["payload"]["resolution"] == "not_proven" for e in t.events))

    def test_request_window13_delivers14_and_new_request_refused(self):
        case, rules, t = module_setup()
        while t.state.clock["window_idx"] < 13:
            for p in list(t.state.players): t = module_play(case, rules, t, "seen", account=p["account_id"])
            t = tick(case, rules, t.state, command_id="advance" + str(t.state.clock["window_idx"]))
        t = module_play(case, rules, t, "archive_request", {"query_id": "register_query"})
        self.assertTrue(t.receipt["accepted"])
        t = tick(case, rules, t.state, command_id="open0014")
        self.assertTrue(any(e["kind"] == "archive_response" for e in t.events))
        t = module_play(case, rules, t, "archive_request", {"query_id": "register_query"}, "account1")
        self.assertEqual(t.receipt["code"], "action_unavailable")

    def test_pending_freeze_wake_delivery_once(self):
        case, rules, t = module_setup(count=12)
        for i in range(5): t = tick(case, rules, t.state, command_id="idle000" + str(i))
        t = module_play(case, rules, t, "seen")
        t = module_play(case, rules, t, "archive_request", {"query_id": "register_query"})
        t = module_play(case, rules, t, "forfeit")
        t = tick(case, rules, t.state, command_id="freeze01")
        self.assertEqual(t.state.clock["phase"], "frozen")
        self.assertFalse(any(e["kind"] == "archive_response" for e in t.events))
        t = module_play(case, rules, t, "seen", account="account1")
        self.assertEqual(t.state.clock["phase"], "investigation")
        self.assertEqual(sum(e["kind"] == "archive_response" for e in t.events), 1)
        self.assertEqual(next(e["payload"]["disposition"] for e in t.events if e["kind"] == "archive_response"), "cancelled")
        t = module_play(case, rules, t, "seen", account="account1")
        self.assertFalse(any(e["kind"] == "archive_response" for e in t.events))

    def test_ghost_at_opening_cancels_without_new_knowledge(self):
        case, rules, t = module_setup()
        for i in range(2):
            for p in list(t.state.players): t = module_play(case, rules, t, "seen", account=p["account_id"])
            t = tick(case, rules, t.state, command_id="advance" + str(i))
        target = t.state.players[0]["character_id"]
        t = module_play(case, rules, t, "accuse", {"suspect": target, "citations": []}, "account1")
        hid = t.state.hearing["id"]
        for p in list(t.state.players): t = module_play(case, rules, t, "vote", {"hearing_id": hid, "choice": "support", "citations": []}, p["account_id"])
        t = tick(case, rules, t.state, command_id="open0004")
        t = module_play(case, rules, t, "archive_request", {"query_id": "register_query"})
        t = tick(case, rules, t.state, command_id="open0005")
        self.assertEqual(t.state.players[0]["status"], "ghost")
        self.assertEqual(next(e["payload"]["disposition"] for e in t.events if e["kind"] == "archive_response"), "cancelled")
        self.assertFalse(any(k["account_id"] == "account0" and k["observation_id"] == "archive_copy" for k in t.state.knowledge))


    def test_outage_defers_archive_until_actual_opening(self):
        case, rules, t = module_setup()
        t = module_play(case, rules, t, "archive_request", {"query_id": "register_query"})
        now = NOW + timedelta(days=2)
        clock = t.state.clock
        raw = {"command_id": "resume001", "kind": "system.resume", "window_seq": clock["window_seq"], "timer_seq": clock["timer_seq"], "params": {"outage_id": "outage01", "unavailable_from": NOW.isoformat().replace("+00:00", "Z"), "resumed_at": now.isoformat().replace("+00:00", "Z")}}
        t = step(case, rules, t.state, SystemActor(), raw, now_utc=now)
        self.assertTrue(t.receipt["accepted"])
        self.assertEqual(t.state.clock["window_idx"], 1)
        self.assertFalse(any(e["kind"] == "archive_response" for e in t.events))
        t = tick(case, rules, t.state)
        self.assertEqual(sum(e["kind"] == "archive_response" for e in t.events), 1)

    def test_scene_chain_late_expiry_and_route_lock(self):
        def scenes(c):
            c["flags"].append({"id": "chain_flag", "initial": False})
            c["module_data"]["turning_point"]["scenes"] += [
                {"id": "late_scene", "not_before": 2, "through_window": 2, "when": [{"kind": "flag_is", "flag": "scene_ready", "value": True}], "body": {"text": "late", "mentions": []}, "effects": [{"kind": "set_flag", "flag": "chain_flag", "value": True}]},
                {"id": "chain_scene", "not_before": 1, "through_window": 14, "when": [{"kind": "flag_is", "flag": "chain_flag", "value": True}], "body": {"text": "chain", "mentions": []}, "effects": []}]
        for late in (False, True):
            case, rules, t = module_setup(mutate=scenes)
            if late:
                for i in range(2): t = tick(case, rules, t.state, command_id="late000" + str(i))
            for action, proof in (("inspect_key", "proof_common"), ("inspect_mechanism", "proof_mechanism")):
                t = module_play(case, rules, t, "act", {"action_id": action})
                t = module_play(case, rules, t, "pin", {"observation_id": proof})
            if not late: t = tick(case, rules, t.state, command_id="scenes02")
            ids = [e["payload"]["content_event_id"] for e in t.events if e["kind"] == "scene"]
            self.assertEqual("late_scene" in ids, not late)
            self.assertEqual("chain_scene" in ids, not late)
            self.assertLessEqual(sum(e["kind"] == "world_changed" for e in t.events), 1)


    def test_recovery_cutoff12_and_required_keys_with_replay(self):
        for search_window in (12, 13):
            case, rules, t = module_setup()
            t = module_play(case, rules, t, "archive_request", {"query_id": "register_query"})
            t = tick(case, rules, t.state, command_id="archive02")
            for action, proof in (("inspect_key", "proof_common"), ("inspect_mechanism", "proof_mechanism"), ("inspect_desk", "proof_a")):
                t = module_play(case, rules, t, "act", {"action_id": action})
                t = module_play(case, rules, t, "pin", {"observation_id": proof})
            while t.state.clock["window_idx"] < search_window:
                for p in list(t.state.players): t = module_play(case, rules, t, "seen", account=p["account_id"])
                t = tick(case, rules, t.state, command_id="advance" + str(t.state.clock["window_idx"]))
            t = module_play(case, rules, t, "move", {"location": "office"})
            now = datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00"))
            raw = player_cmd(t.state, "account0", "act", {"action_id": "search_office"}, "search001")
            t = step(case, rules, t.state, PlayerActor("account0"), raw, now_utc=now)
            self.assertEqual(t.state.final is not None, search_window == 12)
            self.assertEqual(step(case, rules, t.state, PlayerActor("account0"), raw, now_utc=now + timedelta(days=1)).events, ())
        def minimum(c):
            for v in c["variants"]: v["min_key"] = 2
        case, rules, t = module_setup(mutate=minimum)
        for action, proof in (("inspect_key", "proof_common"), ("inspect_mechanism", "proof_mechanism")):
            t = module_play(case, rules, t, "act", {"action_id": action})
            t = module_play(case, rules, t, "pin", {"observation_id": proof})
        t = module_play(case, rules, t, "move", {"location": "office"})
        t = tick(case, rules, t.state)
        t = module_play(case, rules, t, "act", {"action_id": "search_office"})
        self.assertIsNone(t.state.final)

    def test_open_route_still_respects_destination_lock(self):
        def lock(c):
            c["events"].append({"id": "office_lock", "window": 2, "body": {"text": "locked", "mentions": []}, "effects": [{"kind": "lock_location", "location": "office", "through_window": 2}]})
        case, rules, t = module_setup(mutate=lock)
        for action, proof in (("inspect_key", "proof_common"), ("inspect_mechanism", "proof_mechanism")):
            t = module_play(case, rules, t, "act", {"action_id": action})
            t = module_play(case, rules, t, "pin", {"observation_id": proof})
        t = tick(case, rules, t.state)
        self.assertEqual(module_play(case, rules, t, "move", {"location": "office"}).receipt["code"], "action_unavailable")
        t = module_play(case, rules, t, "seen")
        t = tick(case, rules, t.state, command_id="unlock03")
        self.assertTrue(module_play(case, rules, t, "move", {"location": "office"}).receipt["accepted"])


    def test_fog_seen_publishes_active_before_legal_version_mark(self):
        case, rules, t = module_setup()
        for idx in range(2): t = tick(case, rules, t.state, command_id=f"fogtick{idx}")
        self.assertEqual(t.state.players[0]["status"], "fog")
        theory = case.document()["module_data"]["version_archive"]["theories"][0]["id"]
        t = module_play(case, rules, t, "seen")
        self.assertEqual([e["payload"] for e in t.events if e["kind"] == "status"], [{"character_id": t.state.players[0]["character_id"], "controller": "player", "status": "active"}])
        t = module_play(case, rules, t, "version_mark", {"version_id": theory, "state": "archived"})
        self.assertTrue(t.receipt["accepted"])
        self.assertEqual(decode_state(encode_state(t.state), case, rules).document(), t.state.document())
        history = t.state.public["chronicle"]
        active = next(e["audience_seq"] for e in history if e["kind"] == "status" and e["payload"]["character_id"] == t.state.players[0]["character_id"] and e["payload"]["status"] == "active")
        marked = next(e["audience_seq"] for e in history if e["kind"] == "version_marked")
        self.assertLess(active, marked)

    def test_fog_frozen_wake_publishes_active_before_opening(self):
        case, rules, t = module_setup()
        for idx in range(6): t = tick(case, rules, t.state, command_id=f"fogtick{idx}")
        self.assertEqual(t.state.clock["phase"], "frozen")
        t = module_play(case, rules, t, "seen")
        kinds = [e["kind"] for e in t.events]
        self.assertLess(kinds.index("status"), kinds.index("window"))
        self.assertEqual(next(e["payload"]["status"] for e in t.events if e["kind"] == "status"), "active")
        theory = case.document()["module_data"]["version_archive"]["theories"][0]["id"]
        t = module_play(case, rules, t, "version_mark", {"version_id": theory, "state": "archived"})
        self.assertTrue(t.receipt["accepted"])
        self.assertEqual(decode_state(encode_state(t.state), case, rules).document(), t.state.document())

    def test_core1_fog_seen_keeps_historical_event_stream(self):
        case, rules, _, t = setup()
        for idx in range(2): t = tick(case, rules, t.state, command_id=f"fogtick{idx}")
        self.assertEqual(t.state.players[0]["status"], "fog")
        t = module_play(case, rules, t, "seen")
        self.assertEqual(t.state.players[0]["status"], "active")
        self.assertEqual(t.events, ())


PERSONAL_FIXTURE = FIXTURE.with_name("personal_case_v2.json")


def personal_setup(mutate=None):
    c = json.loads(PERSONAL_FIXTURE.read_bytes())
    if mutate: mutate(c)
    case = compile_v2(load_v2(json.dumps(c).encode()))
    rules = rules_snapshot("Europe/Berlin")
    roster = {"players": [{"account_id": f"account{i}", "display_name": f"Player {i}"} for i in range(4)], "npc_name_pool": [f"NPC {i}" for i in range(20)]}
    t = _initialize(case, rules, roster, game_id="personalgame", seed=42, composition_id="players_04", selected_variant_id="variant_a", now_utc=NOW)
    accounts = {p["character_id"]: p["account_id"] for p in t.state.players}
    return case, rules, t, accounts


def personal_act(case, rules, t, accounts, character, step):
    return module_play(case, rules, t, "act", {"action_id": "act_" + step}, accounts[character])


class PersonalEngineTests(unittest.TestCase):
    def test_original_race_paid_fallback_and_historical_goal(self):
        from domain.night_case_personal import story_index, story_predicate
        for foreign_first in (False, True):
            case, rules, t, actors = personal_setup()
            if foreign_first: t = personal_act(case, rules, t, actors, "person_02", "read_original")
            t = personal_act(case, rules, t, actors, "person_00", "read_original")
            t = personal_act(case, rules, t, actors, "person_00", "take_original")
            t = module_play(case, rules, t, "move", {"location": "yard"}, actors["person_00"])
            t = tick(case, rules, t.state)
            t = personal_act(case, rules, t, actors, "person_00", "burn_original")
            pred = case.document()["characters"][0]["goal"]["when"][0]
            self.assertEqual(story_predicate(pred, story_index(case, t.state), actors["person_00"], None), not foreign_first)
            if not foreign_first:
                t = personal_act(case, rules, t, actors, "person_02", "read_original")
                self.assertTrue(t.receipt["accepted"])
                self.assertEqual(next(e["payload"]["disposition"] for e in t.events if e["kind"] == "story_result"), "not_completed")
            self.assertEqual(decode_state(encode_state(t.state), case, rules).document(), t.state.document())

    def test_return_pc_offer_accept_decline_acl_and_replay(self):
        for accept in (False, True):
            case, rules, t, actors = personal_setup()
            t = personal_act(case, rules, t, actors, "person_01", "return_letter")
            offer = next(e for e in t.events if e["kind"] == "story_offer")
            self.assertEqual(next(e["payload"]["disposition"] for e in t.events if e["kind"] == "story_result"), "offered")
            self.assertFalse(any(k["observation_id"] == "archive_copy" for k in t.state.knowledge))
            bad = module_play(case, rules, t, "story_reply", {"offer_event_id": offer["event_id"], "accept": accept}, actors["person_00"])
            self.assertEqual(bad.receipt["code"], "action_unavailable")
            raw = player_cmd(t.state, actors["person_02"], "story_reply", {"offer_event_id": offer["event_id"], "accept": accept}, "reply0001")
            t = step(case, rules, t.state, PlayerActor(actors["person_02"]), raw, now_utc=NOW)
            self.assertTrue(t.receipt["accepted"])
            self.assertEqual(any(k["account_id"] == actors["person_02"] and k["observation_id"] == "archive_copy" for k in t.state.knowledge), accept)
            self.assertEqual(step(case, rules, t.state, PlayerActor(actors["person_02"]), raw, now_utc=NOW).events, ())
            self.assertEqual(decode_state(encode_state(t.state), case, rules).document(), t.state.document())

    def test_public_delivery_is_redacted_and_dedup_preserves_source(self):
        def card(c):
            for s in c["personal_tasks"]["steps"]:
                if s["id"] == "public_card": s["operation"]["observation"] = "archive_copy"
        case, rules, t, actors = personal_setup(card)
        t = personal_act(case, rules, t, actors, "person_01", "public_card")
        event = next(e for e in t.events if e["kind"] == "authored_card_delivered")
        self.assertEqual(set(event["payload"]), {"observation_id", "body"})
        source = next(o["source"] for o in t.state.public["observations"] if o["observation_id"] == "archive_copy")
        self.assertEqual(source["source_id"], event["event_id"])
        self.assertIsNone(source["actor_character"])
        self.assertFalse(any(k["account_id"] == actors["person_01"] and k["observation_id"] == "archive_copy" for k in t.state.knowledge))
        self.assertEqual(decode_state(encode_state(t.state), case, rules).document(), t.state.document())


    def test_work_booking_epilogue_scoring_and_forgotten_departed(self):
        for ending in ("unresolved", "forgotten", "departed"):
            case, rules, t, actors = personal_setup()
            self.assertFalse(personal_act(case, rules, t, actors, "person_03", "paint_finish").receipt["accepted"])
            for name in ("paint_underlayer", "paint_likeness", "paint_finish"):
                t = personal_act(case, rules, t, actors, "person_03", name)
            self.assertFalse(any(e["kind"] == "story_epilogue" for e in t.state.private_events))
            t = tick(case, rules, t.state)
            t = personal_act(case, rules, t, actors, "person_03", "book_trip")
            if ending == "departed":
                t = module_play(case, rules, t, "forfeit", account=actors["person_03"])
                for p in list(t.state.players):
                    if p["status"] != "departed": t = module_play(case, rules, t, "forfeit", account=p["account_id"])
            elif ending == "forgotten":
                while t.state.clock["phase"] != "frozen": t = tick(case, rules, t.state, command_id="idle" + str(t.state.clock["window_idx"]).zfill(4))
                t = tick(case, rules, t.state, now=datetime.fromisoformat(t.state.clock["forget_at"].replace("Z", "+00:00")), command_id="forget01")
            else:
                while t.state.clock["window_idx"] < 14:
                    for p in list(t.state.players): t = module_play(case, rules, t, "seen", account=p["account_id"])
                    t = tick(case, rules, t.state, command_id="next" + str(t.state.clock["window_idx"]).zfill(4))
                t = tick(case, rules, t.state, command_id="final001")
            epilogues = [e for e in t.state.private_events if e["kind"] == "story_epilogue"]
            self.assertEqual(len(epilogues), int(ending == "unresolved"))
            met = next(g["met"] for g in t.state.final["goal_results"] if g["account_id"] == actors["person_03"])
            self.assertEqual(met, ending == "unresolved")
            self.assertEqual(decode_state(encode_state(t.state), case, rules).document(), t.state.document())

    def test_cancel_offer_on_departure_and_no_offer_to_departed(self):
        case, rules, t, actors = personal_setup()
        t = module_play(case, rules, t, "forfeit", account=actors["person_02"])
        t = personal_act(case, rules, t, actors, "person_01", "return_letter")
        self.assertEqual(next(e["payload"]["disposition"] for e in t.events if e["kind"] == "story_result"), "not_completed")
        self.assertFalse(any(e["kind"] == "story_offer" for e in t.events))
        self.assertEqual(t.state.document()["personal_story"]["journal"][-1]["entries"], [{"kind": "actor_closed", "account_id": actors["person_02"]}])
        case, rules, t, actors = personal_setup()
        t = personal_act(case, rules, t, actors, "person_01", "return_letter")
        offer = next(e for e in t.events if e["kind"] == "story_offer")
        t = module_play(case, rules, t, "forfeit", account=actors["person_01"])
        self.assertEqual(sum(e["kind"] == "story_return_closed" for e in t.events), 2)
        t = module_play(case, rules, t, "story_reply", {"offer_event_id": offer["event_id"], "accept": True}, actors["person_02"])
        self.assertEqual(t.receipt["code"], "action_unavailable")

    def test_private_delivery_choice_and_neutral_cache_failure(self):
        case, rules, t, actors = personal_setup()
        t = personal_act(case, rules, t, actors, "person_01", "send_proposal")
        self.assertEqual(t.receipt["code"], "action_unavailable")
        t = personal_act(case, rules, t, actors, "person_01", "private_card")
        self.assertTrue(t.receipt["accepted"])
        self.assertFalse(any(e["kind"] == "authored_card_delivered" for e in t.events))
        self.assertFalse(any(e["kind"] == "public_reveal" for b in t.state.document()["personal_story"]["journal"] for e in b["entries"]))
        t = module_play(case, rules, t, "move", {"location": "yard"}, actors["person_03"])
        t = personal_act(case, rules, t, actors, "person_03", "recover_cache")
        self.assertTrue(t.receipt["accepted"])
        self.assertEqual(next(e["payload"]["disposition"] for e in t.events if e["kind"] == "story_result"), "not_completed")


    def test_npc_return_commitment_and_cross_window_system_batch(self):
        case, rules, t, actors = personal_setup()
        for loc in ("platform", "office"): t = module_play(case, rules, t, "move", {"location": loc}, actors["person_01"])
        t = module_play(case, rules, t, "act", {"action_id": "search_office"}, actors["person_01"])
        t = tick(case, rules, t.state)
        t = personal_act(case, rules, t, actors, "person_01", "return_keeper")
        self.assertEqual(next(e["payload"]["disposition"] for e in t.events if e["kind"] == "story_result"), "completed")
        self.assertEqual(next(e["audience"]["ids"] for e in t.events if e["kind"] == "story_offer"), [actors["person_01"]])
        for name in ("paint_underlayer", "paint_likeness", "paint_finish"): t = personal_act(case, rules, t, actors, "person_03", name)
        t = tick(case, rules, t.state, command_id="worknext")
        for loc in ("platform", "office"): t = module_play(case, rules, t, "move", {"location": loc}, actors["person_03"])
        t = personal_act(case, rules, t, actors, "person_03", "receive_letter")
        self.assertTrue(t.receipt["accepted"])
        self.assertEqual(next(e["payload"]["body"] for e in t.events if e["kind"] == "story_result"), case.document()["personal_tasks"]["commitments"][0]["document"])
        def scheduled(c): c["events"].append({"id": "scheduled_publication", "window": 6, "body": {"text": "archive", "mentions": []}, "effects": [{"kind": "grant_observation", "observation": "archive_copy", "audience": "public"}]})
        case, rules, t, actors = personal_setup(scheduled)
        t = personal_act(case, rules, t, actors, "person_01", "return_letter")
        for idx in range(5):
            for char in ("person_00", "person_02", "person_03"): t = module_play(case, rules, t, "seen", account=actors[char])
            t = tick(case, rules, t.state, command_id="afknext" + str(idx))
        last = t.state.document()["personal_story"]["journal"][-1]
        self.assertEqual(last["cause"], {"kind": "system", "transition_key": "close_5"})
        self.assertEqual(last["window_idx"], 5)
        self.assertTrue({"actor_closed", "return_answered", "public_reveal"} <= {e["kind"] for e in last["entries"]})
        self.assertEqual(decode_state(encode_state(t.state), case, rules).document(), t.state.document())

    def test_repeat_public_card_retains_source_and_same_batch_is_not_before(self):
        def card(c):
            for s in c["personal_tasks"]["steps"]:
                if s["id"] == "public_card":
                    s["operation"]["observation"] = "archive_copy"
                    s["actors"] = ["person_01", "person_02"]
        case, rules, t, actors = personal_setup(card)
        t = personal_act(case, rules, t, actors, "person_01", "public_card")
        first = next(o for o in t.state.public["observations"] if o["observation_id"] == "archive_copy")
        from domain.night_case_personal import story_index, story_predicate
        pred = {"kind": "story_before", "step": "public_card", "boundary": {"kind": "public_reveal", "topic": "paper_topic", "by": "self"}}
        self.assertFalse(story_predicate(pred, story_index(case, t.state), actors["person_01"], None))
        t = personal_act(case, rules, t, actors, "person_02", "public_card")
        self.assertEqual(sum(e["kind"] == "authored_card_delivered" for e in t.events), 1)
        self.assertEqual([o for o in t.state.public["observations"] if o["observation_id"] == "archive_copy"], [first])
        reveals = [e for b in t.state.document()["personal_story"]["journal"] for e in b["entries"] if e["kind"] == "public_reveal"]
        self.assertEqual({e["publisher_account_id"] for e in reveals}, {actors["person_01"], actors["person_02"]})


    def test_closed_actor_cutoff_ignores_later_publication_and_claim(self):
        def card(c):
            for s in c["personal_tasks"]["steps"]:
                if s["id"] == "public_card": s["operation"]["observation"] = "archive_copy"
        case, rules, t, actors = personal_setup(card)
        t = module_play(case, rules, t, "forfeit", account=actors["person_03"])
        t = module_play(case, rules, t, "claim", {"text": "I published every secret"}, actors["person_01"])
        t = personal_act(case, rules, t, actors, "person_01", "public_card")
        from domain.night_case_personal import story_index, story_predicate
        index = story_index(case, t.state)
        predicate = {"kind": "story_unexposed", "topic": "paper_topic", "by": "any"}
        self.assertTrue(story_predicate(predicate, index, actors["person_03"], None))
        self.assertFalse(story_predicate(predicate, index, actors["person_01"], None))
        self.assertEqual(decode_state(encode_state(t.state), case, rules).document(), t.state.document())


    def test_choice_completion_and_pin_publication_use_own_receipts(self):
        case, rules, t, actors = personal_setup()
        account = actors["person_01"]
        t = module_play(case, rules, t, "archive_request", {"query_id": "register_query"}, account)
        t = tick(case, rules, t.state)
        t = personal_act(case, rules, t, actors, "person_01", "compare_sources")
        t = personal_act(case, rules, t, actors, "person_01", "remain_silent")
        self.assertEqual(personal_act(case, rules, t, actors, "person_01", "send_proposal").receipt["code"], "action_unavailable")
        from domain.night_case_personal import story_index, story_predicate
        predicate = {"kind": "story_any_done", "steps": ["remain_silent", "send_proposal"]}
        self.assertTrue(story_predicate(predicate, story_index(case, t.state), account, None))
        self.assertFalse(story_predicate(predicate, story_index(case, t.state), actors["person_00"], None))
        t = module_play(case, rules, t, "pin", {"observation_id": "archive_copy"}, account)
        journal = t.state.document()["personal_story"]["journal"]
        reveal = next(e for e in journal[-1]["entries"] if e["kind"] == "public_reveal")
        self.assertEqual(reveal["publisher_account_id"], account)
        self.assertEqual(reveal["event_id"], next(e["event_id"] for e in t.events if e["kind"] == "board"))

    def test_pending_return_cancels_when_recipient_becomes_ghost(self):
        case, rules, t, actors = personal_setup()
        t = personal_act(case, rules, t, actors, "person_01", "return_letter")
        offer = next(e for e in t.events if e["kind"] == "story_offer")
        for i in range(2):
            for p in list(t.state.players): t = module_play(case, rules, t, "seen", account=p["account_id"])
            t = tick(case, rules, t.state, command_id=f"hearing{i}")
        t = module_play(case, rules, t, "accuse", {"suspect": "person_02", "citations": []}, actors["person_00"])
        hid = t.state.hearing["id"]
        for p in list(t.state.players): t = module_play(case, rules, t, "vote", {"hearing_id": hid, "choice": "support", "citations": []}, p["account_id"])
        t = tick(case, rules, t.state, command_id="hearing3")
        for p in list(t.state.players): t = module_play(case, rules, t, "seen", account=p["account_id"])
        t = tick(case, rules, t.state, command_id="hearing4")
        self.assertEqual(next(p["status"] for p in t.state.players if p["character_id"] == "person_02"), "ghost")
        self.assertEqual(sum(e["kind"] == "story_return_closed" and e["payload"]["offer_event_id"] == offer["event_id"] and e["payload"]["decision"] == "cancelled" for e in t.events), 2)
        self.assertFalse(any(k["account_id"] == actors["person_02"] and k["observation_id"] == "archive_copy" for k in t.state.knowledge))


    def test_alternative_booking_steps_share_own_trip_gate(self):
        import copy
        def duplicate(c):
            step = copy.deepcopy(next(s for s in c["personal_tasks"]["steps"] if s["id"] == "book_trip"))
            step["id"], step["action"] = "book_again", "act_book_again"
            action = copy.deepcopy(next(a for a in c["actions"] if a["id"] == "act_book_trip"))
            action["id"], action["personal_step"] = "act_book_again", "book_again"
            c["personal_tasks"]["steps"].append(step); c["actions"].append(action)
        case, rules, t, actors = personal_setup(duplicate)
        for name in ("paint_underlayer", "paint_likeness", "paint_finish"): t = personal_act(case, rules, t, actors, "person_03", name)
        t = tick(case, rules, t.state)
        from domain.night_case_projection import CommandIntent, quote_action, available_actions, MenuChoice
        actor = PlayerActor(actors["person_03"])
        now = datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00"))
        intent = CommandIntent("act", {"action_id": "act_book_again"})
        old_quote = quote_action(case, rules, t.state, actor, intent, now_utc=now)
        t = personal_act(case, rules, t, actors, "person_03", "book_trip")
        self.assertTrue(t.receipt["accepted"])
        ap, journal = next(p["ap"] for p in t.state.players if p["account_id"] == actor.account_id), t.state.document()["personal_story"]["journal"]
        with self.assertRaisesRegex(ValueError, "action_unavailable"): quote_action(case, rules, t.state, actor, intent, now_utc=now)
        self.assertFalse(any(isinstance(m, MenuChoice) and m.quote.target_id == old_quote.target_id for m in available_actions(case, rules, t.state, actor, now_utc=now)))
        t = module_play(case, rules, t, old_quote.kind, json.loads(old_quote.params), actor.account_id)
        self.assertEqual(t.receipt["code"], "action_unavailable")
        self.assertEqual(next(p["ap"] for p in t.state.players if p["account_id"] == actor.account_id), ap)
        self.assertEqual(t.state.document()["personal_story"]["journal"], journal)
        self.assertEqual(t.events, ())

    def test_alternative_commitment_steps_share_own_document_gate(self):
        import copy
        def duplicate(c):
            step = copy.deepcopy(next(s for s in c["personal_tasks"]["steps"] if s["id"] == "receive_letter"))
            step["id"], step["action"] = "receive_again", "act_receive_again"
            action = copy.deepcopy(next(a for a in c["actions"] if a["id"] == "act_receive_letter"))
            action["id"], action["personal_step"] = "act_receive_again", "receive_again"
            c["personal_tasks"]["steps"].append(step); c["actions"].append(action)
        case, rules, t, actors = personal_setup(duplicate)
        for loc in ("platform", "office"): t = module_play(case, rules, t, "move", {"location": loc}, actors["person_01"])
        t = module_play(case, rules, t, "act", {"action_id": "search_office"}, actors["person_01"])
        for name in ("paint_underlayer", "paint_likeness", "paint_finish"): t = personal_act(case, rules, t, actors, "person_03", name)
        t = tick(case, rules, t.state)
        for loc in ("platform", "office"): t = module_play(case, rules, t, "move", {"location": loc}, actors["person_03"])
        t = tick(case, rules, t.state, command_id="commitwindow")
        from domain.night_case_projection import CommandIntent, quote_action
        actor = PlayerActor(actors["person_03"])
        now = datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00"))
        intent = CommandIntent("act", {"action_id": "act_receive_again"})
        old_quote = quote_action(case, rules, t.state, actor, intent, now_utc=now)
        t = personal_act(case, rules, t, actors, "person_03", "receive_letter")
        self.assertTrue(t.receipt["accepted"])
        ap, journal = next(p["ap"] for p in t.state.players if p["account_id"] == actor.account_id), t.state.document()["personal_story"]["journal"]
        with self.assertRaisesRegex(ValueError, "action_unavailable"): quote_action(case, rules, t.state, actor, intent, now_utc=now)
        t = module_play(case, rules, t, old_quote.kind, json.loads(old_quote.params), actor.account_id)
        self.assertEqual(t.receipt["code"], "action_unavailable")
        self.assertEqual(next(p["ap"] for p in t.state.players if p["account_id"] == actor.account_id), ap)
        self.assertEqual(t.state.document()["personal_story"]["journal"], journal)
        self.assertEqual(t.events, ())


    def test_alternative_work_stage_is_blocked_and_cache_repeat_is_paid_fallback(self):
        import copy
        def duplicate(c):
            for original_id, new_id in (("paint_underlayer", "paint_again"), ("recover_cache", "recover_again")):
                step = copy.deepcopy(next(s for s in c["personal_tasks"]["steps"] if s["id"] == original_id))
                step["id"], step["action"] = new_id, "act_" + new_id
                action = copy.deepcopy(next(a for a in c["actions"] if a["id"] == "act_" + original_id))
                action["id"], action["personal_step"] = "act_" + new_id, new_id
                c["personal_tasks"]["steps"].append(step); c["actions"].append(action)
            next(f for f in c["flags"] if f["id"] == "cache_thawed")["initial"] = True
        case, rules, t, actors = personal_setup(duplicate)
        t = personal_act(case, rules, t, actors, "person_03", "paint_underlayer")
        self.assertTrue(t.receipt["accepted"])
        t = personal_act(case, rules, t, actors, "person_03", "paint_again")
        self.assertEqual(t.receipt["code"], "action_unavailable")
        t = module_play(case, rules, t, "move", {"location": "yard"}, actors["person_03"])
        t = personal_act(case, rules, t, actors, "person_03", "recover_cache")
        self.assertEqual(next(e["payload"]["disposition"] for e in t.events if e["kind"] == "story_result"), "completed")
        t = tick(case, rules, t.state)
        before = next(p["ap"] for p in t.state.players if p["account_id"] == actors["person_03"])
        t = personal_act(case, rules, t, actors, "person_03", "recover_again")
        self.assertTrue(t.receipt["accepted"])
        self.assertEqual(next(e["payload"]["disposition"] for e in t.events if e["kind"] == "story_result"), "not_completed")
        self.assertEqual(next(p["ap"] for p in t.state.players if p["account_id"] == actors["person_03"]), before - 1)
        self.assertEqual(decode_state(encode_state(t.state), case, rules).document(), t.state.document())


RUNTIME_FIXTURE = FIXTURE.with_name("runtime_case_v2.json")


def runtime_setup(mutate=None):
    c = json.loads(RUNTIME_FIXTURE.read_bytes())
    if mutate: mutate(c)
    case = compile_v2(load_v2(json.dumps(c).encode()))
    rules = rules_snapshot("Europe/Berlin")
    roster = {"players": [{"account_id": f"account{i}", "display_name": f"Player {i}"} for i in range(4)], "npc_name_pool": [f"NPC {i}" for i in range(20)]}
    return case, rules, _initialize(case, rules, roster, game_id="runtimegame", seed=42, composition_id="players_04", selected_variant_id="variant_a", now_utc=NOW)


def say(case, rules, t, channel="square", recipients=None, text="Hello", account="account0"):
    return module_play(case, rules, t, "say", {"channel": channel, "recipients": recipients or [], "text": text}, account)


def ready_keeper(case, rules, t):
    for location in ("platform", "office"): t = module_play(case, rules, t, "move", {"location": location})
    t = module_play(case, rules, t, "act", {"action_id": "search_office"})
    return tick(case, rules, t.state, command_id="keeper02")


KEEPER_TALK = {"dialogue_id": "keeper_dialogue", "node_id": "keeper_entry", "option_id": "keeper_question"}


class DeliveryEngineTests(unittest.TestCase):
    def test_say_normalization_message_receipt_replay_and_immutable_delta(self):
        from domain.night_case_delivery_state import validate_message_record
        case, rules, t = runtime_setup()
        raw = player_cmd(t.state, "account0", "say", {"channel": "square", "recipients": [], "text": "Cafe\u0301"}, "message001")
        t = step(case, rules, t.state, PlayerActor("account0"), raw, now_utc=NOW)
        self.assertTrue(t.receipt["accepted"])
        self.assertEqual(t.events, ())
        message = t.messages[0]
        self.assertEqual(message["text"], "Caf\u00e9")
        self.assertEqual(message["recipient_account_ids"], ["account0", "account1", "account2", "account3"])
        validate_message_record(message, t.state.document()["game_id"], "message001")
        message["text"] = "tampered"
        self.assertEqual(t.messages[0]["text"], "Caf\u00e9")
        self.assertNotIn("Caf", json.dumps(t.state.document()))
        restored = decode_state(encode_state(t.state), case, rules)
        replay = step(case, rules, restored, PlayerActor("account0"), raw, now_utc=NOW + timedelta(days=1))
        self.assertEqual(replay.messages, ())
        self.assertEqual(replay.receipt, t.receipt)
        self.assertEqual(replay.state.document(), t.state.document())
        self.assertEqual(set(t.receipt), {"accepted", "code", "actor_revision"})

    def test_whisper_ap_colocation_and_quota_are_server_owned(self):
        case, rules, t = runtime_setup()
        target = t.state.players[1]["character_id"]
        t = say(case, rules, t, "whisper", [target])
        self.assertEqual(t.state.players[0]["ap"], 2)
        self.assertEqual(t.messages[0]["recipient_account_ids"], ["account0", "account1"])
        t = module_play(case, rules, t, "move", {"location": "yard"}, "account1")
        refused = say(case, rules, t, "whisper", [target], text="not colocated")
        self.assertEqual(refused.receipt["code"], "action_unavailable")
        self.assertEqual(refused.messages, ())
        self.assertEqual(refused.state.document()["communication"], t.state.document()["communication"])
        for i in range(19): t = say(case, rules, t, text=f"quota {i}")
        self.assertEqual(t.state.document()["communication"]["sent"][0]["count"], 20)
        refused = say(case, rules, t, text="quota exhausted")
        self.assertEqual(refused.receipt["code"], "action_unavailable")
        self.assertEqual(refused.messages, ())
        t = say(case, rules, t, text="independent", account="account1")
        self.assertTrue(t.receipt["accepted"])
        t = tick(case, rules, t.state)
        self.assertTrue(say(case, rules, t, text="new window").receipt["accepted"])

    def test_npc_authored_line_claim_reuse_grants_only_current_actor(self):
        case, rules, t = runtime_setup()
        t = ready_keeper(case, rules, t)
        t = module_play(case, rules, t, "talk", KEEPER_TALK)
        state = t.state.document()
        self.assertEqual(len(state["npc_delivery"]["lines"]), 1)
        self.assertEqual(len(state["npc_delivery"]["decisions"]), 1)
        decision = state["npc_delivery"]["decisions"][0]
        self.assertTrue(decision["revealed"])
        self.assertFalse(any(k["account_id"] == "account1" and k["observation_id"] == "keeper_slip" for k in t.state.knowledge))
        result = next(e for e in t.events if e["kind"] == "action_result")
        topic = case.document()["npc_delivery"]["topics"][0]
        line = next(l for l in topic["lines"] if l["id"] == state["npc_delivery"]["lines"][0]["line_id"])
        self.assertTrue(result["payload"]["body"]["text"].startswith(line["body"]["text"] + "\n"))
        source = next(k["source"] for k in t.state.knowledge if k["observation_id"] == "keeper_slip")
        self.assertEqual(source["kind"], "dialogue")
        self.assertEqual(source["source_id"], "keeper_question")
        for location in ("platform", "office"): t = module_play(case, rules, t, "move", {"location": location}, "account1")
        raw = player_cmd(t.state, "account1", "talk", KEEPER_TALK, "keeperreuse")
        now = datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00"))
        t = step(case, rules, t.state, PlayerActor("account1"), raw, now_utc=now)
        self.assertEqual(t.state.document()["npc_delivery"]["decisions"], [decision])
        self.assertTrue(any(k["account_id"] == "account1" and k["observation_id"] == "keeper_slip" for k in t.state.knowledge))
        self.assertEqual(step(case, rules, t.state, PlayerActor("account1"), raw, now_utc=now).events, ())
        self.assertEqual(decode_state(encode_state(t.state), case, rules).document(), t.state.document())

    def test_npc_missing_requirements_and_zero_budget_do_not_reroll(self):
        for missing in (True, False):
            def config(c):
                if missing: c["npc_delivery"]["topics"][0]["slip"]["requires"] = [{"kind": "knows", "observation": "archive_copy"}]
                else: c["npc_delivery"]["window_reveal_budget"] = 0
            case, rules, t = runtime_setup(config)
            t = ready_keeper(case, rules, t)
            t = module_play(case, rules, t, "talk", KEEPER_TALK)
            decisions = t.state.document()["npc_delivery"]["decisions"]
            if missing: self.assertEqual(decisions, [])
            else:
                self.assertFalse(decisions[0]["revealed"])
                self.assertIsNone(decisions[0]["draw"])
                t = module_play(case, rules, t, "talk", KEEPER_TALK)
                self.assertEqual(t.state.document()["npc_delivery"]["decisions"], decisions)
            self.assertFalse(any(k["observation_id"] == "keeper_slip" for k in t.state.knowledge))


    def test_ghost_message_audience_is_frozen_and_active_cannot_use_channel(self):
        case, rules, t = runtime_setup()
        self.assertEqual(say(case, rules, t, "ghost").receipt["code"], "action_unavailable")
        def ghost(t, account, accuser):
            while t.state.clock["window_idx"] < 3:
                for p in list(t.state.players): t = module_play(case, rules, t, "seen", account=p["account_id"])
                t = tick(case, rules, t.state, command_id="before00" + str(t.state.clock["window_idx"]))
            target = next(p["character_id"] for p in t.state.players if p["account_id"] == account)
            t = module_play(case, rules, t, "accuse", {"suspect": target, "citations": []}, accuser)
            hid = t.state.hearing["id"]
            for p in list(t.state.players):
                if p["status"] == "active": t = module_play(case, rules, t, "vote", {"hearing_id": hid, "choice": "support", "citations": []}, p["account_id"])
            t = tick(case, rules, t.state, command_id="open0000" + str(t.state.clock["window_idx"]))
            for p in list(t.state.players):
                if p["status"] == "active": t = module_play(case, rules, t, "seen", account=p["account_id"])
            return tick(case, rules, t.state, command_id="resolve" + str(t.state.clock["window_idx"]))
        t = ghost(t, "account0", "account2")
        t = say(case, rules, t, "ghost")
        first = t.messages[0]
        self.assertEqual(first["recipient_account_ids"], ["account0"])
        self.assertEqual(say(case, rules, t, "square").receipt["code"], "action_unavailable")
        t = ghost(t, "account1", "account3")
        t = say(case, rules, t, "ghost")
        self.assertEqual(t.messages[0]["recipient_account_ids"], ["account0", "account1"])
        self.assertEqual(first["recipient_account_ids"], ["account0"])
        self.assertNotEqual(first["thread_key"], t.messages[0]["thread_key"])

    def test_npc_requirements_rechecked_on_shared_decision_reuse(self):
        def requirements(c): c["npc_delivery"]["topics"][0]["slip"]["requires"] = [{"kind": "knows", "observation": "archive_copy"}]
        case, rules, t = runtime_setup(requirements)
        t = module_play(case, rules, t, "archive_request", {"query_id": "register_query"})
        for location in ("platform", "office"): t = module_play(case, rules, t, "move", {"location": location})
        t = tick(case, rules, t.state)
        t = module_play(case, rules, t, "act", {"action_id": "search_office"})
        t = module_play(case, rules, t, "talk", KEEPER_TALK)
        decisions = t.state.document()["npc_delivery"]["decisions"]
        self.assertTrue(decisions[0]["revealed"])
        for location in ("platform", "office"): t = module_play(case, rules, t, "move", {"location": location}, "account1")
        t = module_play(case, rules, t, "talk", KEEPER_TALK, "account1")
        self.assertTrue(t.receipt["accepted"])
        self.assertEqual(t.state.document()["npc_delivery"]["decisions"], decisions)
        self.assertFalse(any(k["account_id"] == "account1" and k["observation_id"] == "keeper_slip" for k in t.state.knowledge))

    def test_npc_budget_is_per_npc_scope_and_false_remains_reusable(self):
        import copy
        def second(c):
            c["npc_delivery"]["window_reveal_budget"] = 1
            topic = copy.deepcopy(c["npc_delivery"]["topics"][0])
            topic["id"], topic["option"], topic["slip"]["rule_id"] = "keeper_second", "keeper_second", "keeper_second_rule"
            option = copy.deepcopy(c["dialogues"][-1]["nodes"][0]["options"][0]); option["id"] = "keeper_second"
            c["dialogues"][-1]["nodes"][0]["options"].append(option)
            c["npc_delivery"]["topics"].append(topic)
        case, rules, t = runtime_setup(second)
        t = ready_keeper(case, rules, t)
        t = module_play(case, rules, t, "talk", KEEPER_TALK)
        second = {**KEEPER_TALK, "option_id": "keeper_second"}
        t = module_play(case, rules, t, "talk", second)
        decisions = t.state.document()["npc_delivery"]["decisions"]
        keyed = {d["scope"]["topic_id"]: d for d in decisions}
        self.assertTrue(keyed["keeper_topic"]["revealed"])
        self.assertFalse(keyed["keeper_second"]["revealed"])
        self.assertIsNone(keyed["keeper_second"]["draw"])
        t = module_play(case, rules, t, "talk", second)
        self.assertEqual(t.state.document()["npc_delivery"]["decisions"], decisions)


    def test_say_fog_presence_fences_frozen_and_terminal(self):
        case, rules, t = runtime_setup()
        for idx in range(2): t = tick(case, rules, t.state, command_id=f"fogtick{idx}")
        self.assertEqual(t.state.players[0]["status"], "fog")
        t = say(case, rules, t, text="back from fog")
        self.assertTrue(t.receipt["accepted"])
        self.assertEqual(t.state.players[0]["status"], "active")
        self.assertTrue(any(e["kind"] == "status" and e["payload"]["status"] == "active" for e in t.events))
        raw = player_cmd(t.state, "account0", "say", {"channel": "square", "recipients": [], "text": "stale"}, "stalesay01")
        t = say(case, rules, t, text="changes own fence")
        now = datetime.fromisoformat(t.state.clock["opened_at"].replace("Z", "+00:00"))
        refused = step(case, rules, t.state, PlayerActor("account0"), raw, now_utc=now)
        self.assertEqual(refused.receipt["code"], "stale_context")
        self.assertEqual(refused.messages, ())
        while t.state.clock["phase"] != "frozen": t = tick(case, rules, t.state, command_id="freeze" + str(t.state.clock["window_idx"]).zfill(4))
        self.assertEqual(say(case, rules, t).receipt["code"], "action_unavailable")
        t = module_play(case, rules, t, "seen")
        for p in list(t.state.players): t = module_play(case, rules, t, "forfeit", account=p["account_id"])
        self.assertIsNotNone(t.state.final)
        refused = step(case, rules, t.state, PlayerActor("account0"), player_cmd(t.state, "account0", "say", {"channel": "square", "recipients": [], "text": "finished"}, "finishedsay"), now_utc=NOW)
        self.assertEqual(refused.receipt["code"], "action_unavailable")

    def test_npc_game_budget_remains_exhausted_in_next_window(self):
        def limit(c): c["npc_delivery"]["game_reveal_budget"] = 1
        case, rules, t = runtime_setup(limit)
        t = ready_keeper(case, rules, t)
        t = module_play(case, rules, t, "talk", KEEPER_TALK)
        t = tick(case, rules, t.state, command_id="nexttalk03")
        t = module_play(case, rules, t, "talk", KEEPER_TALK)
        decisions = t.state.document()["npc_delivery"]["decisions"]
        self.assertEqual(len(decisions), 2)
        self.assertEqual(sum(d["revealed"] for d in decisions), 1)
        last = next(d for d in decisions if d["scope"]["window_idx"] == 3)
        self.assertFalse(last["revealed"])
        self.assertIsNone(last["draw"])
        self.assertEqual(decode_state(encode_state(t.state), case, rules).document(), t.state.document())
