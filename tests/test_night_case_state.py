import copy
import json
import unittest
from types import SimpleNamespace

from domain.night_case_state import (
    Command, KernelState, PlayerActor, SystemActor, decode_state, encode_state,
    event_id_for, event_scope, parse_command, rules_snapshot, engine_build_for,
)


class FakeCase:
    case_id = "sample_case"
    case_version = 1
    content_hash = "a" * 64
    compiler_version = "v2-1"

    def document(self):
        return {
            "ruleset_ref": {"id": "night_case.core", "version": 1},
            "characters": [{"id": "alice"}, {"id": "bob"}],
            "locations": [{"id": "house"}],
            "observations": [{"id": "note", "kind": "proof", "exists_in": ["variant_a"]}, {"id": "other", "kind": "proof", "exists_in": ["variant_b"]}, {"id": "rumor", "kind": "claim", "exists_in": "all"}],
            "variants": [{"id": "variant_a"}, {"id": "variant_b"}],
            "compositions": [{"id": "party"}],
            "dialogues": [], "actions": [], "events": [{"id": "scene_later", "window": 3, "body": {"text": "A bell rings", "mentions": []}}], "flags": [],
            "initial": {"public_observations": ["note"]},
        }


def valid_state():
    rules = rules_snapshot("Europe/Berlin")
    source = {"kind": "initial", "source_id": "initial", "actor_character": None, "location": None, "window_idx": 1}
    private = {"kind": "accounts", "ids": ["user-1"]}
    grant_id = event_id_for("game-1", private, 1)
    digest_id = event_id_for("game-1", private, 2)
    return {
        "state_schema": "night-city-state/1", "game_id": "game-1",
        "case_ref": {"case_id": "sample_case", "case_version": 1, "content_hash": "a" * 64},
        "ruleset_ref": {"id": "night_case.core", "version": 1},
        "rules": rules.document(), "rules_hash": rules.rules_hash,
        "compiler_version": "v2-1", "engine_build": "night-case-core/1",
        "sealed": {"variant_id": "variant_a", "seed": 10, "composition_id": "party", "assignments": [{"account_id": "user-1", "character_id": "alice"}]},
        "clock": {"timezone": "Europe/Berlin", "window_idx": 1, "window_seq": 1, "timer_seq": 1, "opened_at": "2026-01-01T08:00:00Z", "closes_at": "2026-01-01T18:00:00Z", "early_not_before": "2026-01-01T08:30:00Z", "slot_cursor": None, "phase": "investigation", "opening_pending": False, "freeze_at": None, "forget_at": None, "resume_receipts": []},
        "players": [{"account_id": "user-1", "character_id": "alice", "name": "Alice", "status": "active", "location": "house", "ap": 3, "actor_seq": 0, "knowledge_revision": 1, "last_seen_window": 0, "missed_windows": 0, "finished_window": False, "ghost_used_window": None, "accusations_used": 0, "wrong_accusations": 0, "participated_windows": [], "departed_snapshot": None}],
        "npcs": [{"character_id": "bob", "name": "Bob", "location": "house", "status": "active", "origin": "authored"}],
        "public": {"flags": [], "locks": [], "observations": [], "board": [], "chronicle": [], "revision": 0, "framed_count": 0},
        "knowledge": [{"account_id": "user-1", "observation_id": "note", "source": source}],
        "private_events": [
            {"event_id": grant_id, "window_idx": 1, "audience_seq": 1, "kind": "observation_granted", "audience": private, "payload": {"observation_id": "note", "source": source}},
            {"event_id": digest_id, "window_idx": 1, "audience_seq": 2, "kind": "window_digest", "audience": private, "payload": {"window_idx": 1, "event_ids": [grant_id], "observation_ids": ["note"]}},
        ],
        "dialogue_cursors": [], "action_uses": [], "event_uses": [],
        "hearing": None, "final_ballots": [],
        "receipts": [{"actor_key": "account:user-1", "command_id": "command-1", "payload_hash": "b" * 64, "accepted": True, "code": "ok", "actor_revision": 1, "result_ref": {"kind": "event", "event_id": grant_id}}],
        "idle_windows": 0, "final": None,
    }


class StateTests(unittest.TestCase):
    def setUp(self):
        self.case = FakeCase()
        self.rules = rules_snapshot("Europe/Berlin")

    def test_roundtrip_preserves_private_result_and_no_alias(self):
        source = valid_state()
        state = KernelState.from_document(source, self.case, self.rules)
        source["private_events"][0]["payload"]["source"]["source_id"] = "changed"
        copy_out = state.document()
        copy_out["private_events"][0]["payload"]["source"]["source_id"] = "changed"
        restored = decode_state(encode_state(state), self.case, self.rules)
        self.assertEqual(restored.document()["private_events"][0]["payload"]["source"]["source_id"], "initial")
        self.assertEqual(restored.receipts[0]["result_ref"]["event_id"], event_id_for("game-1", {"kind": "accounts", "ids": ["user-1"]}, 1))

    def test_wrong_hash_unknown_and_duplicate_json_key_rejected(self):
        for change in (lambda d: d["case_ref"].update(content_hash="c" * 64), lambda d: d["players"][0].update(extra=1), lambda d: d["rules"].update(ap_per_window=4), lambda d: d["rules"].update(move_cost=True), lambda d: d["rules"].update(ap_per_window=3.0), lambda d: d["ruleset_ref"].update(version=True)):
            document = valid_state()
            change(document)
            with self.assertRaises(ValueError):
                decode_state(json.dumps(document).encode(), self.case, self.rules)
        raw = encode_state(KernelState.from_document(valid_state(), self.case, self.rules))
        with self.assertRaises(ValueError):
            decode_state(raw.replace(b'"game_id":"game-1"', b'"game_id":"game-1","game_id":"game-2"'), self.case, self.rules)

    def test_ownership_and_dangling_result_rejected(self):
        for change in (lambda d: d["npcs"].append({"character_id": "alice", "name": "Other", "location": "house", "status": "active", "origin": "authored"}), lambda d: d["receipts"][0]["result_ref"].update(event_id="missing"), lambda d: d["knowledge"].append(copy.deepcopy(d["knowledge"][0]))):
            document = valid_state()
            change(document)
            with self.assertRaises(ValueError):
                KernelState.from_document(document, self.case, self.rules)

    def test_private_event_payload_and_audience_are_closed(self):
        for change in (
            lambda d: d["private_events"][0]["payload"].update(secret=True),
            lambda d: d["private_events"][0]["audience"].update(ids=["user-1", "user-2"]),
            lambda d: d["private_events"][0]["payload"].update(observation_id="missing"),
        ):
            document = valid_state()
            change(document)
            with self.assertRaises(ValueError):
                KernelState.from_document(document, self.case, self.rules)

    def test_variant_absent_observation_cannot_be_restored(self):
        document = valid_state()
        document["knowledge"][0]["observation_id"] = "other"
        document["private_events"][0]["payload"]["observation_id"] = "other"
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)

    def test_departed_requires_snapshot_and_former_npc(self):
        base = valid_state()
        base["players"][0]["status"] = "departed"
        base["players"][0]["ap"] = 0
        with self.assertRaises(ValueError):
            KernelState.from_document(base, self.case, self.rules)
        base["players"][0]["departed_snapshot"] = {"location": "house", "known_observations": ["note"], "window_idx": 1}
        base["npcs"].append({"character_id": "alice", "name": "Alice NPC", "location": "house", "status": "active", "origin": "former_player"})
        KernelState.from_document(base, self.case, self.rules)
        base["players"][0]["status"] = "active"
        base["players"][0]["ap"] = 3
        with self.assertRaises(ValueError):
            KernelState.from_document(base, self.case, self.rules)

    def test_hearing_and_ballots_only_in_valid_window(self):
        ballot = {"account_id": "user-1", "suspect": "bob", "citations": []}
        document = valid_state()
        document["final_ballots"] = [ballot]
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)
        document = valid_state()
        document["hearing"] = {"id": "hearing-1", "accuser": "user-1", "suspect": "bob", "opened_window": 3, "resolve_window": 4, "eligible_accounts": ["user-1"], "initial_citations": [], "votes": []}
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)
        document["clock"]["window_idx"] = 3
        KernelState.from_document(document, self.case, self.rules)
        document["hearing"] = None
        document["clock"]["window_idx"] = 14
        document["clock"]["phase"] = "final_hearing"
        document["final_ballots"] = [ballot]
        KernelState.from_document(document, self.case, self.rules)

    def test_public_observation_requires_public_event_provenance(self):
        document = valid_state()
        document["public"]["observations"] = [{"observation_id": "note", "source": {"kind": "event", "source_id": "fake-event", "actor_character": None, "location": None, "window_idx": 1}}]
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)
        grant_id = event_id_for("game-1", {"kind": "public"}, 1)
        source = {"kind": "event", "source_id": grant_id, "actor_character": None, "location": None, "window_idx": 1}
        document["public"]["observations"][0]["source"] = source
        document["public"]["chronicle"] = [{"event_id": grant_id, "window_idx": 1, "audience_seq": 1, "kind": "observation_granted", "audience": {"kind": "public"}, "payload": {"observation_id": "note", "source": source}}]
        KernelState.from_document(document, self.case, self.rules)

    def test_scene_body_is_authored_and_exact(self):
        document = valid_state()
        scene = {"event_id": event_id_for("game-1", {"kind": "public"}, 1), "window_idx": 1, "audience_seq": 1, "kind": "scene", "audience": {"kind": "public"}, "payload": {"content_event_id": "scene_later", "body": {"text": "Forged secret", "mentions": []}}}
        document["public"]["chronicle"] = [scene]
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)
        scene["payload"]["body"] = {"text": "A bell rings", "mentions": []}
        KernelState.from_document(document, self.case, self.rules)

    def test_future_content_event_is_not_used(self):
        document = valid_state()
        document["event_uses"] = ["scene_later"]
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)

    def test_phase_matches_window_number(self):
        document = valid_state()
        document["clock"]["phase"] = "final_hearing"
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)
        document["clock"]["phase"] = "investigation"
        document["clock"]["window_idx"] = 14
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)

    def test_map_encoding_order_is_canonical(self):
        document = valid_state()
        second = copy.deepcopy(document["players"][0])
        second.update(account_id="user-2", character_id="bob", name="Bobby", knowledge_revision=0)
        document["players"].append(second)
        document["npcs"] = []
        document["sealed"]["assignments"].append({"account_id": "user-2", "character_id": "bob"})
        document["clock"]["window_idx"] = 3
        document["hearing"] = {"id": "hearing:123", "accuser": "user-1", "suspect": "bob", "opened_window": 3, "resolve_window": 4, "eligible_accounts": ["user-1", "user-2"], "initial_citations": [], "votes": [{"account_id": "user-1", "choice": "support", "citations": []}, {"account_id": "user-2", "choice": "oppose", "citations": []}]}
        document["clock"]["resume_receipts"] = [{"outage_id": "a", "payload_hash": "a" * 64}, {"outage_id": "b", "payload_hash": "b" * 64}]
        encoded = encode_state(KernelState.from_document(document, self.case, self.rules))
        document["sealed"]["assignments"].reverse()
        document["clock"]["resume_receipts"].reverse()
        document["hearing"]["votes"].reverse()
        self.assertEqual(encode_state(KernelState.from_document(document, self.case, self.rules)), encoded)

    def test_event_id_stream_is_scoped_and_contiguous(self):
        public = {"kind": "public"}
        private = {"kind": "accounts", "ids": ["user-1"]}
        self.assertEqual(event_scope(public), "public")
        self.assertEqual(event_scope(private), "account:user-1")
        self.assertNotEqual(event_id_for("game-1", public, 1), event_id_for("game-1", private, 1))
        with self.assertRaises(ValueError):
            event_id_for("game-1", public, True)
        document = valid_state()
        document["private_events"][0]["event_id"] = "evt_" + "0" * 64
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)
        document = valid_state()
        event = document["private_events"][1]
        event["audience_seq"] = 3
        event["event_id"] = event_id_for("game-1", event["audience"], 3)
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)

    def test_digest_exact_previous_window_and_notice(self):
        document = valid_state()
        document["clock"]["window_idx"] = 2
        audience = {"kind": "accounts", "ids": ["user-1"]}
        action_id = event_id_for("game-1", audience, 3)
        document["private_events"].append({"event_id": action_id, "window_idx": 1, "audience_seq": 3, "kind": "action_result", "audience": audience, "payload": {"body": {"text": "Found note", "mentions": []}, "observation_ids": ["note"]}})
        grant_id = document["private_events"][0]["event_id"]
        digest = {"event_id": event_id_for("game-1", audience, 4), "window_idx": 2, "audience_seq": 4, "kind": "window_digest", "audience": audience, "payload": {"window_idx": 1, "event_ids": [grant_id, action_id], "observation_ids": ["note"]}}
        document["private_events"].append(digest)
        document["private_events"].append({"event_id": event_id_for("game-1", audience, 5), "window_idx": 2, "audience_seq": 5, "kind": "afk_notice", "audience": audience, "payload": {"window_idx": 1, "missed_windows": 1}})
        state = KernelState.from_document(document, self.case, self.rules)
        document["private_events"].reverse()
        self.assertEqual(encode_state(KernelState.from_document(document, self.case, self.rules)), encode_state(state))
        digest["payload"]["event_ids"] = [grant_id]
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)
        digest["payload"]["event_ids"] = [grant_id, action_id]
        digest["payload"]["observation_ids"] = []
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)

    def test_initial_digest_ignores_dynamic_result(self):
        document = valid_state()
        audience = {"kind": "accounts", "ids": ["user-1"]}
        action = {"event_id": event_id_for("game-1", audience, 2), "window_idx": 1, "audience_seq": 2, "kind": "action_result", "audience": audience, "payload": {"body": {"text": "Later", "mentions": []}, "observation_ids": []}}
        document["private_events"].insert(1, action)
        digest = document["private_events"][2]
        digest["audience_seq"] = 3
        digest["event_id"] = event_id_for("game-1", audience, 3)
        KernelState.from_document(document, self.case, self.rules)
        digest["payload"]["event_ids"].append(action["event_id"])
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)

    def test_frozen_pending_window_has_no_private_opening_events(self):
        document = valid_state()
        document["clock"].update(window_idx=2, phase="frozen", opening_pending=True, opened_at=None, closes_at=None, early_not_before=None, freeze_at="2026-01-02T00:00:00Z", forget_at="2026-01-16T00:00:00Z")
        audience = {"kind": "accounts", "ids": ["user-1"]}
        document["private_events"].append({"event_id": event_id_for("game-1", audience, 3), "window_idx": 2, "audience_seq": 3, "kind": "afk_notice", "audience": audience, "payload": {"window_idx": 1, "missed_windows": 1}})
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)

    def test_frozen_forfeit_can_publish_former_player_status(self):
        document = valid_state()
        document["clock"].update(window_idx=2, phase="frozen", opening_pending=True, opened_at=None, closes_at=None, early_not_before=None, freeze_at="2026-01-02T00:00:00Z", forget_at="2026-01-16T00:00:00Z")
        document["players"][0].update(status="departed", ap=0, departed_snapshot={"location": "house", "known_observations": ["note"], "window_idx": 1})
        document["npcs"].append({"character_id": "alice", "name": "Alice", "location": "house", "status": "active", "origin": "former_player"})
        document["public"]["chronicle"] = [{"event_id": event_id_for("game-1", {"kind": "public"}, 1), "window_idx": 2, "audience_seq": 1, "kind": "status", "audience": {"kind": "public"}, "payload": {"character_id": "alice", "controller": "npc", "status": "active"}}]
        KernelState.from_document(document, self.case, self.rules)

    def test_former_player_can_keep_max_length_name_only_for_same_character(self):
        document = valid_state()
        name = "Н" * 120
        document["players"][0].update(name=name, status="departed", ap=0, departed_snapshot={"location": "house", "known_observations": ["note"], "window_idx": 1})
        document["npcs"].append({"character_id": "alice", "name": name, "location": "house", "status": "active", "origin": "former_player"})
        KernelState.from_document(document, self.case, self.rules)
        document["npcs"][0]["name"] = name
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)

    def test_board_proof_requires_owner_or_prior_public_root(self):
        document = valid_state()
        second = copy.deepcopy(document["players"][0])
        second.update(account_id="user-2", character_id="bob", name="Bobby", knowledge_revision=0)
        document["players"].append(second)
        document["npcs"] = []
        document["sealed"]["assignments"].append({"account_id": "user-2", "character_id": "bob"})
        source = document["knowledge"][0]["source"]
        second_board = {"id": "board-2", "owner_account_id": "user-2", "kind": "proof", "observation_id": "note", "text": None, "source": source}
        document["public"]["board"] = [second_board]
        document["public"]["chronicle"] = [{"event_id": event_id_for("game-1", {"kind": "public"}, 1), "window_idx": 1, "audience_seq": 1, "kind": "board", "audience": {"kind": "public"}, "payload": {"board_id": "board-2"}}]
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)
        first_board = {**second_board, "id": "board-1", "owner_account_id": "user-1"}
        document["public"]["board"].insert(0, first_board)
        document["public"]["chronicle"][0]["payload"]["board_id"] = "board-1"
        document["public"]["chronicle"].append({"event_id": event_id_for("game-1", {"kind": "public"}, 2), "window_idx": 1, "audience_seq": 2, "kind": "board", "audience": {"kind": "public"}, "payload": {"board_id": "board-2"}})
        KernelState.from_document(document, self.case, self.rules)
        document["public"]["chronicle"].reverse()
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)

    def test_public_grant_must_precede_board_using_it(self):
        document = valid_state()
        public_audience = {"kind": "public"}
        grant_id = event_id_for("game-1", public_audience, 1)
        source = {"kind": "event", "source_id": grant_id, "actor_character": None, "location": None, "window_idx": 1}
        document["public"]["observations"] = [{"observation_id": "note", "source": source}]
        document["public"]["board"] = [{"id": "board-1", "owner_account_id": "user-1", "kind": "proof", "observation_id": "note", "text": None, "source": source}]
        document["public"]["chronicle"] = [
            {"event_id": grant_id, "window_idx": 1, "audience_seq": 1, "kind": "observation_granted", "audience": public_audience, "payload": {"observation_id": "note", "source": source}},
            {"event_id": event_id_for("game-1", public_audience, 2), "window_idx": 1, "audience_seq": 2, "kind": "board", "audience": public_audience, "payload": {"board_id": "board-1"}},
        ]
        KernelState.from_document(document, self.case, self.rules)
        document["public"]["chronicle"][0]["audience_seq"] = 2
        document["public"]["chronicle"][0]["event_id"] = event_id_for("game-1", public_audience, 2)
        document["public"]["chronicle"][1]["audience_seq"] = 1
        document["public"]["chronicle"][1]["event_id"] = event_id_for("game-1", public_audience, 1)
        document["public"]["chronicle"].reverse()
        document["public"]["observations"][0]["source"]["source_id"] = event_id_for("game-1", public_audience, 2)
        document["public"]["chronicle"][1]["payload"]["source"]["source_id"] = event_id_for("game-1", public_audience, 2)
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)

    def test_authored_claim_keeps_observation_and_source(self):
        document = valid_state()
        source = document["knowledge"][0]["source"]
        document["knowledge"].append({"account_id": "user-1", "observation_id": "rumor", "source": source})
        entry = {"id": "claim-1", "owner_account_id": "user-1", "kind": "claim", "observation_id": "rumor", "text": None, "source": source}
        document["public"]["board"].append(entry)
        document["public"]["chronicle"].append({"event_id": event_id_for("game-1", {"kind": "public"}, 1), "window_idx": 1, "audience_seq": 1, "kind": "board", "audience": {"kind": "public"}, "payload": {"board_id": "claim-1"}})
        KernelState.from_document(document, self.case, self.rules)
        entry["kind"] = "proof"
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)
        entry["kind"] = "claim"
        entry["text"] = "Player's invented note"
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)
        entry.update(observation_id=None, source=None)
        KernelState.from_document(document, self.case, self.rules)

    def test_board_cannot_publish_source_from_later_window(self):
        document = valid_state()
        source = {"kind": "action", "source_id": "action-later", "actor_character": "alice", "location": "house", "window_idx": 2}
        document["knowledge"][0]["source"] = source
        document["clock"]["window_idx"] = 2
        document["public"]["board"] = [{"id": "board-early", "owner_account_id": "user-1", "kind": "proof", "observation_id": "note", "text": None, "source": source}]
        document["public"]["chronicle"] = [{"event_id": event_id_for("game-1", {"kind": "public"}, 1), "window_idx": 1, "audience_seq": 1, "kind": "board", "audience": {"kind": "public"}, "payload": {"board_id": "board-early"}}]
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)

    def test_initial_public_source_needs_matching_grant(self):
        document = valid_state()
        fake = {"kind": "initial", "source_id": "fabricated", "actor_character": None, "location": None, "window_idx": 1}
        document["public"]["observations"] = [{"observation_id": "note", "source": fake}]
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)
        grant_id = event_id_for("game-1", {"kind": "public"}, 1)
        source = {**fake, "source_id": grant_id}
        document["public"]["observations"][0]["source"] = source
        document["public"]["chronicle"] = [{"event_id": grant_id, "window_idx": 1, "audience_seq": 1, "kind": "observation_granted", "audience": {"kind": "public"}, "payload": {"observation_id": "note", "source": source}}]
        document["private_events"][1]["payload"]["event_ids"].insert(0, grant_id)
        KernelState.from_document(document, self.case, self.rules)
        document["public"]["observations"][0]["observation_id"] = "rumor"
        document["public"]["chronicle"][0]["payload"]["observation_id"] = "rumor"
        document["private_events"][1]["payload"]["observation_ids"] = ["note", "rumor"]
        with self.assertRaises(ValueError):
            KernelState.from_document(document, self.case, self.rules)

    def test_digest_includes_authored_claim_observation(self):
        document = valid_state()
        source = document["knowledge"][0]["source"]
        document["knowledge"].append({"account_id": "user-1", "observation_id": "rumor", "source": source})
        document["public"]["board"] = [{"id": "claim-1", "owner_account_id": "user-1", "kind": "claim", "observation_id": "rumor", "text": None, "source": source}]
        board_event_id = event_id_for("game-1", {"kind": "public"}, 1)
        document["public"]["chronicle"] = [{"event_id": board_event_id, "window_idx": 1, "audience_seq": 1, "kind": "board", "audience": {"kind": "public"}, "payload": {"board_id": "claim-1"}}]
        document["clock"]["window_idx"] = 2
        audience = {"kind": "accounts", "ids": ["user-1"]}
        document["private_events"].append({"event_id": event_id_for("game-1", audience, 3), "window_idx": 2, "audience_seq": 3, "kind": "window_digest", "audience": audience, "payload": {"window_idx": 1, "event_ids": [board_event_id, document["private_events"][0]["event_id"]], "observation_ids": ["note", "rumor"]}})
        KernelState.from_document(document, self.case, self.rules)

    def test_command_strict_union_and_payload_hash(self):
        actor = PlayerActor("user-1")
        command = {"command_id": "command-1", "kind": "move", "window_idx": 1, "window_seq": 1, "actor_seq": 0, "params": {"location": "house"}}
        parsed = parse_command(command, actor)
        self.assertEqual(parsed.kind, "move")
        self.assertEqual(parsed.payload_hash, Command.from_document({**command, "command_id": "command-2"}, actor).payload_hash)
        with self.assertRaises(ValueError):
            Command.from_document({**command, "actor_seq": False}, actor)
        with self.assertRaises(ValueError):
            Command.from_document({**command, "params": {"location": "house", "hidden": 1}}, actor)
        with self.assertRaises(ValueError):
            Command.from_document(command, SystemActor())
        vote = {"command_id": "command-3", "kind": "vote", "window_idx": 4, "window_seq": 4, "actor_seq": 1, "params": {"hearing_id": "hearing:" + "a" * 32, "choice": "support", "citations": []}}
        self.assertEqual(parse_command(vote, actor).kind, "vote")


class ModuleCase(FakeCase):
    compiler_version = "v2-2"

    def document(self):
        document = super().document()
        document["ruleset_ref"]["version"] = 2
        document["locations"].append({"id": "yard"})
        document["observations"].append({"id": "archive_copy", "kind": "proof", "exists_in": "all"})
        document["flags"] = [{"id": "bob_revealed", "initial": False}]
        document["actions"] = [{"id": "search_house", "location": "house", "repeat": "player_game", "outcomes": [{"guard": {"variants": ["variant_a"], "when": []}, "body": {"text": "Bob found", "mentions": []}, "effects": [{"kind": "reveal_npc", "character": "bob"}]}]}]
        document["module_data"] = {
            "archive_requests": {"queries": [{"id": "register_query", "location": "house", "available_when": [], "responses": [{"variants": "all", "body": {"text": "Archive copy", "mentions": []}, "observations": ["archive_copy"]}]}]},
            "version_archive": {"theories": [{"id": "theory_a"}, {"id": "theory_b"}]},
            "turning_point": {"routes": [], "scenes": [{"id": "module_scene", "not_before": 2, "through_window": 4, "when": [], "body": {"text": "Scene", "mentions": []}, "effects": []}], "concealed_npcs": [{"character": "bob", "revealed_flag": "bob_revealed", "placements": [{"variants": ["variant_a"], "location": "house"}, {"variants": ["variant_b"], "location": "yard"}]}]},
        }
        return document


class PersonalCase(ModuleCase):
    compiler_version = "v2-3"

    def document(self):
        document = super().document()
        document["personal_tasks"] = {
            "version": 1, "originals": [], "caches": [], "works": [], "commitments": [], "trips": [], "topics": [],
            "steps": [{"id": "record_step", "action": "record_action", "actors": ["alice"], "requires": [], "choice_group": None, "operation": {"kind": "record_deed"}, "responses": [{"variants": "all", "body": {"text": "Recorded deed", "mentions": []}, "observations": []}]}],
        }
        document["initial"]["public_observations"] = []
        for observation in document["observations"]:
            observation["body"] = {"text": observation["id"], "mentions": []}
        document["actions"].append({"id": "record_action", "location": "house", "kind": "interact", "repeat": "player_window", "personal_step": "record_step", "outcomes": [], "available_when": [], "fallback": {"text": "Nothing happened", "mentions": []}})
        return document


def personal_state():
    document = module_state()
    document["compiler_version"] = "v2-3"
    document["personal_story"] = {"version": 1, "journal": []}
    return document


class AlteredPersonalCase(PersonalCase):
    def __init__(self, alter):
        self.alter = alter

    def document(self):
        document = super().document()
        self.alter(document)
        return document


def personal_step(document, step_id, operation, requires=(), actors=("alice",), location="house"):
    document["personal_tasks"]["steps"].append({"id": step_id, "action": "act_" + step_id, "actors": list(actors), "requires": list(requires), "choice_group": None, "operation": operation, "responses": [{"variants": "all", "body": {"text": step_id, "mentions": []}, "observations": []}]})
    document["actions"].append({"id": "act_" + step_id, "kind": "interact", "location": location, "repeat": "player_window", "personal_step": step_id, "outcomes": [], "available_when": [], "fallback": {"text": "Nothing happened", "mentions": []}})


def personal_receipt(document, account, result=None):
    command_id = "personal" + str(len(document["receipts"])).zfill(4)
    document["receipts"].append({"actor_key": "account:" + account, "command_id": command_id, "payload_hash": "d" * 64, "accepted": True, "code": "accepted", "actor_revision": len(document["receipts"]), "result_ref": {"kind": "event", "event_id": result["event_id"]} if result else None})
    return {"kind": "command", "account_id": account, "command_id": command_id}


def personal_batch(document, entries, cause):
    journal = document["personal_story"]["journal"]
    journal.append({"seq": len(journal) + 1, "window_idx": document["clock"]["window_idx"], "cause": cause, "entries": entries})
    return journal[-1]


def complete_personal(document, case, step_id, account="user-1"):
    step = next(s for s in case.document()["personal_tasks"]["steps"] if s["id"] == step_id)
    result = step["responses"][0]
    observations = list(result["observations"])
    if step["operation"]["kind"] == "inspect_original":
        original = next(o for o in case.document()["personal_tasks"]["originals"] if o["id"] == step["operation"]["original"])
        observations += [s["observation"] for s in original["sections"] if s["id"] == step["operation"]["section"]]
    event = append_event(document, "story_result", {"step_id": step_id, "disposition": "completed", "body": result["body"], "observation_ids": list(dict.fromkeys(observations))}, document["clock"]["window_idx"], account)
    return personal_batch(document, [{"kind": "step_done", "step_id": step_id, "account_id": account}], personal_receipt(document, account, event))


def second_personal_player(document):
    player = copy.deepcopy(document["players"][0])
    player.update(account_id="user-2", character_id="bob", name="Bobby", knowledge_revision=0)
    document["players"].append(player)
    document["npcs"] = []
    document["sealed"]["assignments"].append({"account_id": "user-2", "character_id": "bob"})


def letter_case(document, pc=True):
    if pc:
        document["module_data"]["turning_point"]["concealed_npcs"] = []
    document["personal_tasks"]["originals"] = [{"id": "personal_letter", "source_location": "house", "initial_holder": "alice", "sections": [{"id": "letter_section", "observation": "note", "backup_proofs": []}], "destroy_locations": [], "return_to": "bob", "return_location": "house", "offer_body": {"text": "A letter awaits", "mentions": []}}]
    personal_step(document, "return_letter", {"kind": "offer_return", "original": "personal_letter"})


def offer_personal_letter(document, case, recipient="user-2"):
    offer = append_event(document, "story_offer", {"step_id": "return_letter", "from_character": "alice", "original_id": "personal_letter", "return_location": "house", "body": {"text": "A letter awaits", "mentions": []}}, document["clock"]["window_idx"], recipient or "user-1")
    result = append_event(document, "story_result", {"step_id": "return_letter", "disposition": "offered", "body": {"text": "A letter awaits", "mentions": []}, "observation_ids": []}, document["clock"]["window_idx"], "user-1")
    personal_batch(document, [{"kind": "return_offered", "step_id": "return_letter", "account_id": "user-1", "offer_event_id": offer["event_id"], "recipient_account_id": recipient}], personal_receipt(document, "user-1", result))
    return offer


def module_state():
    document = valid_state()
    document["ruleset_ref"]["version"] = 2
    document["compiler_version"] = "v2-2"
    document["engine_build"] = "night-case-core/2"
    document["public"]["flags"] = [{"id": "bob_revealed", "value": False}]
    return document


def append_event(document, kind, payload, window, account=None):
    audience = {"kind": "public"} if account is None else {"kind": "accounts", "ids": [account]}
    events = document["public"]["chronicle"] if account is None else document["private_events"]
    seq = 1 + sum(e["audience"] == audience for e in events)
    event = {"event_id": event_id_for(document["game_id"], audience, seq), "audience_seq": seq, "audience": audience, "window_idx": window, "kind": kind, "payload": payload}
    events.append(event)
    return event


def requested_state():
    document = module_state()
    request = append_event(document, "archive_requested", {"query_id": "register_query", "due_window": 2}, 1, "user-1")
    return document, request


def open_second(document):
    document["clock"]["window_idx"] = 2
    return append_event(document, "window", {"window_idx": 2, "phase": "investigation", "opened_at": "2026-01-01T18:00:00Z", "closes_at": "2026-01-02T08:00:00Z"}, 2)


def delivered_state():
    document, request = requested_state()
    open_second(document)
    append_event(document, "archive_response", {"request_event_id": request["event_id"], "disposition": "delivered", "body": {"text": "Archive copy", "mentions": []}, "observation_ids": ["archive_copy"]}, 2, "user-1")
    source = {"kind": "event", "source_id": request["event_id"], "actor_character": "alice", "location": None, "window_idx": 2}
    document["knowledge"].append({"account_id": "user-1", "observation_id": "archive_copy", "source": source})
    append_event(document, "observation_granted", {"observation_id": "archive_copy", "source": copy.deepcopy(source)}, 2, "user-1")
    return document


def discovery_trace(document):
    result = append_event(document, "action_result", {"body": {"text": "Bob found", "mentions": []}, "observation_ids": []}, 1, "user-1")
    document["action_uses"].append({"account_id": "user-1", "action_key": "search_house", "window_idx": None})
    document["receipts"].append({"actor_key": "account:user-1", "command_id": "search-bob", "payload_hash": "c" * 64, "accepted": True, "code": "accepted", "actor_revision": 2, "result_ref": {"kind": "event", "event_id": result["event_id"]}})


class ModuleStateTests(unittest.TestCase):
    def setUp(self):
        self.case = ModuleCase()
        self.rules = rules_snapshot("Europe/Berlin")

    def accept(self, document):
        return decode_state(encode_state(KernelState.from_document(document, self.case, self.rules)), self.case, self.rules)

    def reject(self, document):
        with self.assertRaises(ValueError):
            self.accept(document)

    def test_engine_build_and_parser_exact_profile_gates(self):
        for version in (1, 2):
            self.assertEqual(engine_build_for({"id": "night_case.core", "version": version}), f"night-case-core/{version}")
        for ref in ({"id": "unknown", "version": 1}, {"id": "night_case.core", "version": True}, {"id": "night_case.core", "version": 2.0}, {"id": "night_case.core", "version": 3}, {"id": "night_case.core", "version": 1, "extra": 1}):
            with self.assertRaises(ValueError):
                engine_build_for(ref)
        raw = {"command_id": "archive-1", "kind": "archive_request", "window_idx": 1, "window_seq": 1, "actor_seq": 0, "params": {"query_id": "register_query"}}
        actor = PlayerActor("user-1")
        command = parse_command(raw, actor, ruleset_version=2)
        self.assertEqual(parse_command(command, actor, ruleset_version=2), command)
        for version in (1, True, 2.0, 0, 3):
            with self.assertRaises(ValueError):
                parse_command(command, actor, ruleset_version=version)
        for params in ({"query_id": "register_query", "due_window": 2}, {"query_id": "BAD"}):
            with self.assertRaises(ValueError):
                parse_command({**raw, "params": params}, actor, ruleset_version=2)
        mark = {**raw, "kind": "version_mark", "params": {"version_id": "theory_a", "state": "archived"}}
        self.assertEqual(parse_command(mark, actor, ruleset_version=2).kind, "version_mark")
        with self.assertRaises(ValueError):
            parse_command({**mark, "params": {**mark["params"], "state": "removed"}}, actor, ruleset_version=2)

    def test_case_state_profile_and_build_are_bound(self):
        self.accept(module_state())
        for change in (lambda d: d["ruleset_ref"].update(version=1), lambda d: d.update(engine_build="night-case-core/1"), lambda d: d.update(compiler_version="v2-1")):
            document = module_state()
            change(document)
            self.reject(document)

    def test_archive_pending_and_delivered_roundtrip_have_no_new_root(self):
        document, _ = requested_state()
        self.accept(document)
        self.accept(delivered_state())
        document["pending_requests"] = []
        self.reject(document)

    def test_archive_request_closed_refs_exact_due_and_repeat(self):
        for patch in ({"due_window": True}, {"due_window": 2.0}, {"due_window": 3}, {"query_id": "unknown"}, {"body": None}):
            document, request = requested_state()
            request["payload"].update(patch)
            self.reject(document)
        document, _ = requested_state()
        append_event(document, "archive_requested", {"query_id": "register_query", "due_window": 2}, 1, "user-1")
        self.reject(document)

    def test_archive_response_authorship_refs_acl_and_exactly_once(self):
        for patch in ({"request_event_id": "missing"}, {"body": {"text": "Forged", "mentions": []}}, {"observation_ids": ["note"]}, {"disposition": "cancelled"}):
            document = delivered_state()
            document["private_events"][3]["payload"].update(patch)
            self.reject(document)
        document = delivered_state()
        append_event(document, "archive_response", copy.deepcopy(document["private_events"][3]["payload"]), 2, "user-1")
        self.reject(document)
        document = delivered_state()
        document["private_events"][3]["audience"]["ids"] = ["somebody-else"]
        self.reject(document)

    def test_archive_delivery_provenance_cannot_be_local_or_other_actor(self):
        for patch in ({"location": "house"}, {"actor_character": "bob"}, {"window_idx": 1}, {"kind": "action"}, {"source_id": "forged"}):
            document = delivered_state()
            document["knowledge"][-1]["source"].update(patch)
            if patch.get("source_id") != "forged":
                document["private_events"][-1]["payload"]["source"].update(patch)
            self.reject(document)

    def test_archive_must_deliver_at_actual_opening(self):
        document, _ = requested_state()
        open_second(document)
        self.reject(document)
        document = delivered_state()
        document["public"]["chronicle"] = []
        self.reject(document)

    def test_delivery_uses_historical_status_before_opening(self):
        document = delivered_state()
        # Later exclusion in this same window cannot cancel an already delivered reply.
        append_event(document, "status", {"character_id": "alice", "controller": "player", "status": "ghost"}, 2)
        document["players"][0].update(status="ghost", ap=0)
        self.accept(document)
        # Move that exclusion into the preceding closing window.
        status = document["public"]["chronicle"].pop()
        status["window_idx"] = 1
        opening = document["public"]["chronicle"].pop()
        document["public"]["chronicle"] = []
        append_event(document, "status", status["payload"], 1)
        append_event(document, "window", opening["payload"], 2)
        self.reject(document)
        response = document["private_events"][3]
        response["payload"].update(disposition="cancelled", body=None, observation_ids=[])
        document["private_events"].pop()
        document["knowledge"].pop()
        self.accept(document)

    def test_frozen_pending_can_retain_request_but_not_delivery(self):
        document, _ = requested_state()
        document["clock"].update(window_idx=2, phase="frozen", opening_pending=True, opened_at=None, closes_at=None, early_not_before=None, freeze_at="2026-01-01T18:00:00Z", forget_at="2026-01-15T18:00:00Z")
        append_event(document, "window", {"window_idx": 2, "phase": "frozen", "opened_at": None, "closes_at": None}, 2)
        self.accept(document)
        append_event(document, "archive_response", {"request_event_id": document["private_events"][-1]["event_id"], "disposition": "cancelled", "body": None, "observation_ids": []}, 2, "user-1")
        self.reject(document)

    def test_version_mark_refs_noop_repeat_and_restore(self):
        document = module_state()
        append_event(document, "version_marked", {"version_id": "theory_a", "state": "archived", "by_account": "user-1"}, 1)
        self.accept(document)
        append_event(document, "version_marked", {"version_id": "theory_a", "state": "active", "by_account": "user-1"}, 1)
        self.reject(document)
        document["public"]["chronicle"][-1]["window_idx"] = 2
        document["clock"]["window_idx"] = 2
        self.accept(document)
        for patch in ({"version_id": "missing"}, {"by_account": "missing"}, {"state": "archived"}):
            changed = copy.deepcopy(document)
            changed["public"]["chronicle"][-1]["payload"].update(patch)
            self.reject(changed)

    def test_version_mark_rejects_fog_without_presence_recovery(self):
        from tests.test_night_case_engine import module_setup, tick
        case, rules, transition = module_setup()
        transition = tick(case, rules, transition.state, command_id="fog_tick1")
        transition = tick(case, rules, transition.state, command_id="fog_tick2")
        document = transition.state.document()
        self.assertEqual(document["players"][0]["status"], "fog")
        append_event(document, "version_marked", {"version_id": "theory_a", "state": "archived", "by_account": "account0"}, 3)
        document["public"]["revision"] += 1
        with self.assertRaises(ValueError):
            KernelState.from_document(document, case, rules)

    def test_version_mark_after_fog_seen_recovery_is_legal(self):
        from tests.test_night_case_engine import module_setup, module_play, tick
        case, rules, transition = module_setup()
        transition = tick(case, rules, transition.state, command_id="fog_tick1")
        transition = tick(case, rules, transition.state, command_id="fog_tick2")
        transition = module_play(case, rules, transition, "seen")
        self.assertEqual(transition.state.players[0]["status"], "active")
        transition = module_play(case, rules, transition, "version_mark", {"version_id": "theory_a", "state": "archived"})
        self.assertTrue(transition.receipt["accepted"])
        self.assertEqual(decode_state(encode_state(transition.state), case, rules), transition.state)

    def test_discovery_without_search_trace_is_rejected(self):
        from tests.test_night_case_engine import module_setup
        case, rules, transition = module_setup()
        document = transition.state.document()
        append_event(document, "npc_revealed", {"character_id": "missing_keeper", "location": "office"}, 1)
        append_event(document, "world_changed", {"flags": [{"id": "keeper_revealed", "value": True}], "locks": []}, 1)
        next(f for f in document["public"]["flags"] if f["id"] == "keeper_revealed")["value"] = True
        document["public"]["revision"] += 2
        with self.assertRaises(ValueError):
            KernelState.from_document(document, case, rules)

    def test_discovery_trace_needs_matching_result_use_receipt_and_variant(self):
        document = module_state()
        discovery_trace(document)
        append_event(document, "npc_revealed", {"character_id": "bob", "location": "house"}, 1)
        append_event(document, "world_changed", {"flags": [{"id": "bob_revealed", "value": True}], "locks": []}, 1)
        document["public"]["flags"][0]["value"] = True
        self.accept(document)
        for change in (
            lambda d: d.update(action_uses=[]),
            lambda d: d["receipts"].pop(),
            lambda d: d["receipts"][-1].update(accepted=False),
            lambda d: d["private_events"][-1]["payload"]["body"].update(text="Unrelated result"),
            lambda d: d["private_events"][-1].update(window_idx=2),
        ):
            changed = copy.deepcopy(document)
            change(changed)
            self.reject(changed)
        class WrongOutcomeVariant(ModuleCase):
            def document(self):
                case = super().document()
                case["actions"][0]["outcomes"][0]["guard"]["variants"] = ["variant_b"]
                return case
        with self.assertRaises(ValueError):
            KernelState.from_document(document, WrongOutcomeVariant(), self.rules)

    def test_concealed_static_placement_and_discovery_flag_history(self):
        document = module_state()
        document["npcs"][0]["location"] = "yard"
        self.reject(document)
        document = module_state()
        document["public"]["flags"][0]["value"] = True
        self.reject(document)
        discovery_trace(document)
        append_event(document, "npc_revealed", {"character_id": "bob", "location": "house"}, 1)
        append_event(document, "world_changed", {"flags": [{"id": "bob_revealed", "value": True}], "locks": []}, 1)
        self.accept(document)
        append_event(document, "npc_revealed", {"character_id": "bob", "location": "house"}, 1)
        self.reject(document)

    def test_protected_flags_cannot_reset_or_double_publish(self):
        for value in (False, True):
            document = module_state()
            document["public"]["flags"][0]["value"] = value
            discovery_trace(document)
            append_event(document, "npc_revealed", {"character_id": "bob", "location": "house"}, 1)
            append_event(document, "world_changed", {"flags": [{"id": "bob_revealed", "value": True}], "locks": []}, 1)
            append_event(document, "world_changed", {"flags": [{"id": "bob_revealed", "value": value}], "locks": []}, 1)
            self.reject(document)

    def test_module_event_kind_requires_its_module(self):
        class ArchiveOnly(ModuleCase):
            def document(self):
                document = super().document()
                del document["module_data"]["version_archive"]
                return document
        document = module_state()
        append_event(document, "version_marked", {"version_id": "theory_a", "state": "archived", "by_account": "user-1"}, 1)
        with self.assertRaises(ValueError):
            KernelState.from_document(document, ArchiveOnly(), self.rules)

    def test_archive_digest_includes_delivery_only_in_next_window(self):
        document = delivered_state()
        document["clock"]["window_idx"] = 3
        own = [e for e in document["private_events"] if e["window_idx"] == 2]
        opening = document["public"]["chronicle"][0]
        append_event(document, "window_digest", {"window_idx": 2, "observation_ids": ["archive_copy"], "event_ids": [opening["event_id"]] + [e["event_id"] for e in own]}, 3, "user-1")
        self.accept(document)
        document["private_events"][-1]["payload"]["observation_ids"] = []
        self.reject(document)

    def test_departure_before_wake_cancels_pending_archive(self):
        document, request = requested_state()
        document["players"][0].update(status="departed", ap=0, departed_snapshot={"location": "house", "known_observations": ["note"], "window_idx": 1})
        document["npcs"].append({"character_id": "alice", "name": "Alice", "location": "house", "status": "active", "origin": "former_player"})
        document["clock"].update(window_idx=2, phase="frozen", opening_pending=True, opened_at=None, closes_at=None, early_not_before=None, freeze_at="2026-01-01T18:00:00Z", forget_at="2026-01-15T18:00:00Z")
        append_event(document, "window", {"window_idx": 2, "phase": "frozen", "opened_at": None, "closes_at": None}, 2)
        append_event(document, "status", {"character_id": "alice", "controller": "npc", "status": "active"}, 2)
        self.accept(document)
        document["clock"].update(phase="investigation", opening_pending=False, opened_at="2026-01-02T08:00:00Z", closes_at="2026-01-02T18:00:00Z", early_not_before="2026-01-02T08:30:00Z", freeze_at=None, forget_at=None)
        open_second(document)
        append_event(document, "archive_response", {"request_event_id": request["event_id"], "disposition": "cancelled", "body": None, "observation_ids": []}, 2, "user-1")
        self.accept(document)

    def test_module_scene_catalog_use_window_and_duplicate(self):
        document = module_state()
        document["clock"]["window_idx"] = 2
        document["event_uses"] = ["module_scene"]
        append_event(document, "scene", {"content_event_id": "module_scene", "body": {"text": "Scene", "mentions": []}}, 2)
        self.accept(document)
        for change in (lambda d: d.update(event_uses=[]), lambda d: d["public"]["chronicle"][0]["payload"]["body"].update(text="Forged"), lambda d: d["public"]["chronicle"][0].update(window_idx=1)):
            changed = copy.deepcopy(document)
            change(changed)
            self.reject(changed)
        append_event(document, "scene", {"content_event_id": "module_scene", "body": {"text": "Scene", "mentions": []}}, 2)
        self.reject(document)

    def test_route_protected_flag_requires_preceding_board_publication(self):
        class RouteCase(ModuleCase):
            def document(self):
                document = super().document()
                document["flags"].append({"id": "route_opened", "initial": False})
                document["module_data"]["turning_point"]["routes"] = [{"id": "secret_route", "ends": ["house", "yard"], "opened_flag": "route_opened", "open_when": [{"kind": "published", "observation": "note"}]}]
                return document
        self.case = RouteCase()
        document = module_state()
        document["public"]["flags"].append({"id": "route_opened", "value": True})
        append_event(document, "world_changed", {"flags": [{"id": "route_opened", "value": True}], "locks": []}, 1)
        self.reject(document)
        document["public"]["board"] = [{"id": "proof-1", "owner_account_id": "user-1", "kind": "proof", "observation_id": "note", "text": None, "source": document["knowledge"][0]["source"]}]
        document["public"]["chronicle"] = []
        append_event(document, "board", {"board_id": "proof-1"}, 1)
        append_event(document, "world_changed", {"flags": [{"id": "route_opened", "value": True}], "locks": []}, 1)
        self.accept(document)

    def test_conditional_scene_cannot_run_on_fresh_closed_route(self):
        from tests.test_night_case_engine import module_setup
        case, rules, transition = module_setup()
        document = transition.state.document()
        scene = case.document()["module_data"]["turning_point"]["scenes"][0]
        document["event_uses"].append(scene["id"])
        append_event(document, "scene", {"content_event_id": scene["id"], "body": scene["body"]}, 1)
        document["public"]["revision"] += 1
        with self.assertRaisesRegex(ValueError, "scene prerequisites"):
            KernelState.from_document(document, case, rules)

    def test_coalesced_route_and_scene_chain_roundtrip(self):
        from tests.test_night_case_engine import module_setup, module_play
        def chain(case):
            case["flags"].append({"id": "chain_ready", "initial": False})
            case["module_data"]["turning_point"]["scenes"].append({"id": "chained_scene", "not_before": 1, "through_window": 14, "when": [{"kind": "flag_is", "flag": "scene_ready", "value": True}], "body": {"text": "Second scene", "mentions": []}, "effects": [{"kind": "set_flag", "flag": "chain_ready", "value": True}]})
        case, rules, transition = module_setup(mutate=chain)
        for action, proof in (("inspect_key", "proof_common"), ("inspect_mechanism", "proof_mechanism")):
            transition = module_play(case, rules, transition, "act", {"action_id": action})
            transition = module_play(case, rules, transition, "pin", {"observation_id": proof})
        self.assertEqual([e["payload"]["content_event_id"] for e in transition.events if e["kind"] == "scene"], ["archive_scene", "chained_scene"])
        self.assertEqual(sum(e["kind"] == "world_changed" for e in transition.events), 1)
        self.assertEqual(decode_state(encode_state(transition.state), case, rules), transition.state)

    def test_later_proof_and_world_change_cannot_justify_earlier_scene(self):
        from tests.test_night_case_engine import module_setup, module_play
        case, rules, transition = module_setup()
        for action, proof in (("inspect_key", "proof_common"), ("inspect_mechanism", "proof_mechanism")):
            transition = module_play(case, rules, transition, "act", {"action_id": action})
            transition = module_play(case, rules, transition, "pin", {"observation_id": proof})
        document = transition.state.document()
        chronicle = document["public"]["chronicle"]
        scene_index = next(i for i, e in enumerate(chronicle) if e["kind"] == "scene" and e["payload"]["content_event_id"] == "archive_scene")
        scene = chronicle.pop(scene_index)
        # The route's second proof is now published after this scene, even though
        # its coalesced world change remains in the same window after both.
        last_board_index = max(i for i, e in enumerate(chronicle) if e["kind"] == "board")
        chronicle.insert(last_board_index, scene)
        for seq, event in enumerate(chronicle, 1):
            event["audience_seq"] = seq
            event["event_id"] = event_id_for(document["game_id"], {"kind": "public"}, seq)
        with self.assertRaisesRegex(ValueError, "scene prerequisites"):
            KernelState.from_document(document, case, rules)

    def test_discovery_semantic_evidence_checks_both_flag_values_before_world_change(self):
        from tests.test_night_case_engine import module_setup, module_play, tick
        def scenes(case):
            for value, name in ((False, "before_discovery"), (True, "after_discovery")):
                case["module_data"]["turning_point"]["scenes"].append({"id": name, "not_before": 2, "through_window": 14, "when": [{"kind": "flag_is", "flag": "keeper_revealed", "value": value}], "body": {"text": name, "mentions": []}, "effects": []})
        case, rules, transition = module_setup(mutate=scenes)
        for action, proof in (("inspect_key", "proof_common"), ("inspect_mechanism", "proof_mechanism")):
            transition = module_play(case, rules, transition, "act", {"action_id": action})
            transition = module_play(case, rules, transition, "pin", {"observation_id": proof})
        transition = module_play(case, rules, transition, "move", {"location": "office"})
        transition = tick(case, rules, transition.state)
        transition = module_play(case, rules, transition, "act", {"action_id": "search_office"})
        self.assertTrue(any(e["kind"] == "scene" and e["payload"]["content_event_id"] == "after_discovery" for e in transition.events))
        self.assertEqual(decode_state(encode_state(transition.state), case, rules), transition.state)
        document = transition.state.document()
        chronicle = document["public"]["chronicle"]
        before = next(e for e in chronicle if e["kind"] == "scene" and e["payload"]["content_event_id"] == "before_discovery")
        chronicle.remove(before)
        discovery_index = next(i for i, e in enumerate(chronicle) if e["kind"] == "npc_revealed")
        chronicle.insert(discovery_index + 1, before)
        for seq, event in enumerate(chronicle, 1):
            event["audience_seq"] = seq
            event["event_id"] = event_id_for(document["game_id"], {"kind": "public"}, seq)
        with self.assertRaisesRegex(ValueError, "scene prerequisites"):
            KernelState.from_document(document, case, rules)

    def test_route_semantic_evidence_rejects_false_guard_before_late_world_change(self):
        from tests.test_night_case_engine import module_setup, module_play, tick
        def scenes(case):
            case["module_data"]["turning_point"]["scenes"].append({"id": "before_route", "not_before": 2, "through_window": 14, "when": [{"kind": "flag_is", "flag": "route_opened", "value": False}], "body": {"text": "Before route", "mentions": []}, "effects": []})
        case, rules, transition = module_setup(mutate=scenes)
        transition = tick(case, rules, transition.state)
        for action, proof in (("inspect_key", "proof_common"), ("inspect_mechanism", "proof_mechanism")):
            transition = module_play(case, rules, transition, "act", {"action_id": action})
            transition = module_play(case, rules, transition, "pin", {"observation_id": proof})
        self.assertEqual(decode_state(encode_state(transition.state), case, rules), transition.state)
        document = transition.state.document()
        chronicle = document["public"]["chronicle"]
        before = next(e for e in chronicle if e["kind"] == "scene" and e["payload"]["content_event_id"] == "before_route")
        chronicle.remove(before)
        after_proofs = max(i for i, e in enumerate(chronicle) if e["kind"] == "board")
        chronicle.insert(after_proofs + 1, before)
        for seq, event in enumerate(chronicle, 1):
            event["audience_seq"] = seq
            event["event_id"] = event_id_for(document["game_id"], {"kind": "public"}, seq)
        with self.assertRaisesRegex(ValueError, "scene prerequisites"):
            KernelState.from_document(document, case, rules)

    def test_core_profile_rejects_new_event_kinds(self):
        for kind, payload, account in (("archive_requested", {"query_id": "register_query", "due_window": 2}, "user-1"), ("archive_response", {"request_event_id": "missing", "disposition": "cancelled", "body": None, "observation_ids": []}, "user-1"), ("version_marked", {"version_id": "theory_a", "state": "archived", "by_account": "user-1"}, None), ("npc_revealed", {"character_id": "bob", "location": "house"}, None)):
            document = valid_state()
            append_event(document, kind, payload, 1, account)
            with self.assertRaises(ValueError):
                KernelState.from_document(document, FakeCase(), self.rules)


class PersonalStateTests(unittest.TestCase):
    def setUp(self):
        self.rules = rules_snapshot("Europe/Berlin")

    def accept(self, document, case=None):
        case = case or PersonalCase()
        state = KernelState.from_document(document, case, self.rules)
        return decode_state(encode_state(state), case, self.rules)

    def reject(self, document, case=None):
        with self.assertRaises(ValueError):
            self.accept(document, case)

    def test_empty_capability_roundtrip(self):
        rules = rules_snapshot("Europe/Berlin")
        document = personal_state()
        state = KernelState.from_document(document, PersonalCase(), rules)
        self.assertEqual(decode_state(encode_state(state), PersonalCase(), rules), state)
        document["personal_story"]["journal"].append({})
        self.assertEqual(state.document()["personal_story"]["journal"], [])

    def test_story_reply_profile_parser_boolean_and_event_id(self):
        actor = PlayerActor("user-1")
        raw = {"command_id": "storyreply1", "kind": "story_reply", "window_idx": 1, "window_seq": 1, "actor_seq": 0, "params": {"offer_event_id": "evt_" + "a" * 64, "accept": True}}
        command = parse_command(raw, actor, ruleset_version=2)
        self.assertEqual(parse_command(command, actor, ruleset_version=2), command)
        with self.assertRaises(ValueError):
            parse_command(command, actor)
        for value in (0, 1, "true", None):
            with self.assertRaises(ValueError):
                parse_command({**raw, "params": {**raw["params"], "accept": value}}, actor, ruleset_version=2)

    def test_capability_is_exact_and_required_only_when_enabled(self):
        self.accept(personal_state())
        for change in (lambda d: d["personal_story"].update(version=True), lambda d: d["personal_story"].update(version=1.0), lambda d: d["personal_story"].update(pending=[]), lambda d: d.pop("personal_story")):
            document = personal_state()
            change(document)
            self.reject(document)
        disabled = module_state()
        disabled["personal_story"] = {"version": 1, "journal": []}
        self.reject(disabled, ModuleCase())
        disabled = module_state()
        append_event(disabled, "story_result", {"step_id": "record_step", "disposition": "not_completed", "body": {"text": "Nothing happened", "mentions": []}, "observation_ids": []}, 1, "user-1")
        self.reject(disabled, ModuleCase())

    def test_done_requires_journal_receipt_and_owned_step_not_body(self):
        document = personal_state()
        complete_personal(document, PersonalCase(), "record_step")
        self.accept(document)
        for change in (
            lambda d: d["personal_story"].update(journal=[]),
            lambda d: d["receipts"].pop(),
            lambda d: d["receipts"][-1].update(accepted=False),
            lambda d: d["personal_story"]["journal"][0]["entries"][0].update(account_id="bob"),
            lambda d: d["personal_story"]["journal"][0]["entries"][0].update(step_id="missing"),
            lambda d: d["private_events"][-1]["payload"].update(body={"text": "I did it", "mentions": []}),
        ):
            changed = copy.deepcopy(document)
            change(changed)
            self.reject(changed)

    def test_journal_bounds_shapes_exact_order_and_replay(self):
        def extra(case):
            personal_step(case, "second_step", {"kind": "record_deed"}, requires=("record_step",))
        case = AlteredPersonalCase(extra)
        document = personal_state()
        complete_personal(document, case, "record_step")
        complete_personal(document, case, "second_step")
        state = self.accept(document, case)
        for change in (
            lambda d: d["personal_story"]["journal"][0].update(seq=True),
            lambda d: d["personal_story"]["journal"][0].update(seq=1.0),
            lambda d: d["personal_story"]["journal"][1].update(seq=3),
            lambda d: d["personal_story"]["journal"][1].update(window_idx=2),
            lambda d: d["personal_story"]["journal"][0].update(entries=[]),
            lambda d: d["personal_story"]["journal"][0]["entries"][0].update(extra=1),
            lambda d: d["personal_story"]["journal"][0]["entries"][0].update(kind="money_paid"),
            lambda d: d["personal_story"]["journal"][1].update(cause=copy.deepcopy(d["personal_story"]["journal"][0]["cause"])),
        ):
            changed = copy.deepcopy(document)
            change(changed)
            self.reject(changed, case)
        output = state.document()
        output["personal_story"]["journal"][0]["entries"][0]["account_id"] = "changed"
        self.assertEqual(state.document()["personal_story"]["journal"][0]["entries"][0]["account_id"], "user-1")
        reordered = copy.deepcopy(document)
        reordered["personal_story"]["journal"].reverse()
        self.reject(reordered, case)

    def test_physical_original_inspection_take_destroy_cannot_be_faked_by_copy(self):
        def original(case):
            case["personal_tasks"]["originals"] = [{"id": "will_original", "source_location": "house", "initial_holder": None, "sections": [{"id": "draft", "observation": "note", "backup_proofs": ["note"]}], "destroy_locations": ["yard"], "return_to": None, "return_location": None, "offer_body": None}]
            personal_step(case, "inspect_paper", {"kind": "inspect_original", "original": "will_original", "section": "draft"})
            personal_step(case, "take_paper", {"kind": "take_original", "original": "will_original"}, requires=("inspect_paper",))
            personal_step(case, "burn_paper", {"kind": "destroy_original", "original": "will_original"}, requires=("take_paper",), location="yard")
            personal_step(case, "inspect_again", {"kind": "inspect_original", "original": "will_original", "section": "draft"})
        case = AlteredPersonalCase(original)
        document = personal_state()
        # Existing knowledge from a copy does not itself complete a physical step.
        self.accept(document, case)
        for step in ("inspect_paper", "take_paper", "burn_paper"):
            complete_personal(document, case, step)
        self.accept(document, case)
        complete_personal(document, case, "inspect_again")
        self.reject(document, case)
        skipped = personal_state()
        complete_personal(skipped, case, "burn_paper")
        self.reject(skipped, case)

    def test_work_stages_booking_and_epilogue_require_real_completion(self):
        def work(case):
            case["personal_tasks"]["works"] = [{"id": "portrait", "owner": "alice", "location": "house", "stages": ["underlayer", "likeness", "finish"]}]
            case["personal_tasks"]["trips"] = [{"id": "journey", "traveler": "alice", "work": "portrait", "road_open_flag": "bob_revealed", "epilogue": {"text": "Later, Alice left", "mentions": []}}]
            for stage in ("underlayer", "likeness", "finish"):
                personal_step(case, "paint_" + stage, {"kind": "advance_work", "work": "portrait", "stage": stage})
            personal_step(case, "book_journey", {"kind": "book_departure", "trip": "journey"})
        case = AlteredPersonalCase(work)
        out_of_order = personal_state()
        complete_personal(out_of_order, case, "paint_finish")
        self.reject(out_of_order, case)
        early = personal_state()
        complete_personal(early, case, "book_journey")
        self.reject(early, case)
        document = personal_state()
        for step in ("paint_underlayer", "paint_likeness", "paint_finish", "book_journey"):
            complete_personal(document, case, step)
        self.accept(document, case)
        append_event(document, "story_epilogue", {"trip_id": "journey", "body": {"text": "Later, Alice left", "mentions": []}}, 1, "user-1")
        personal_batch(document, [{"kind": "departed_epilogue", "trip_id": "journey", "account_id": "user-1"}], personal_receipt(document, "user-1"))
        self.reject(document, case)
        document["clock"].update(phase="finished", opened_at=None, closes_at=None, early_not_before=None)
        document["final"] = {"code": "unresolved", "at": "2026-01-01T18:00:00Z", "variant_id": "variant_a", "culprit": "bob", "key_proofs": [], "goal_results": [{"account_id": "user-1", "goal_id": "personal_goal", "met": True}], "reward_facts": [{"account_id": "user-1", "participated_windows": 0, "total_windows": 1, "completed": True, "goal_met": True, "faction_won": False, "wrong_accusations": 0}]}
        self.accept(document, case)
        for change in (
            lambda d: d["final"].update(code="forgotten"),
            lambda d: d["private_events"][-1]["payload"].update(body={"text": "Instant departure", "mentions": []}),
            lambda d: d["personal_story"]["journal"][-1]["entries"][0].update(trip_id="unknown_trip"),
        ):
            changed = copy.deepcopy(document)
            change(changed)
            self.reject(changed, case)
        missing = copy.deepcopy(document)
        missing["personal_story"]["journal"].pop()
        missing["private_events"].pop()
        self.reject(missing, case)

    def test_personal_goal_predicates_are_closed_and_owned(self):
        def goal(case):
            case["characters"][0]["goal"] = {"id": "personal_goal", "body": {"text": "Goal", "mentions": []}, "criteria": {"text": "Perform own deed", "mentions": []}, "when": [{"kind": "story_done", "step": "record_step"}]}
        case = AlteredPersonalCase(goal)
        self.accept(personal_state(), case)
        for pred in ({"kind": "story_done", "step": "unknown"}, {"kind": "story_any_done", "steps": ["record_step", "record_step"]}, {"kind": "story_before", "step": "record_step", "boundary": {"kind": "public_reveal", "topic": "unknown", "by": "any"}}, {"kind": "story_unexposed", "topic": "unknown", "by": "self"}, {"kind": "story_departed", "trip": "unknown"}):
            def invalid(document, pred=pred):
                goal(document)
                document["characters"][0]["goal"]["when"] = [pred]
            self.reject(personal_state(), AlteredPersonalCase(invalid))

    def test_pc_return_is_pending_until_own_acceptance_and_grants_keep_sender(self):
        case = AlteredPersonalCase(letter_case)
        document = personal_state()
        second_personal_player(document)
        offer = offer_personal_letter(document, case)
        self.accept(document, case)
        for change in (
            lambda d: d["personal_story"]["journal"][0]["entries"][0].update(recipient_account_id="user-1"),
            lambda d: d["private_events"][-1]["payload"].update(disposition="completed"),
            lambda d: d["private_events"][-1]["payload"]["body"].update(text="The letter was accepted"),
        ):
            changed = copy.deepcopy(document)
            change(changed)
            self.reject(changed, case)
        closes = [append_event(document, "story_return_closed", {"offer_event_id": offer["event_id"], "decision": "accepted"}, 1, account) for account in ("user-1", "user-2")]
        append_event(document, "story_result", {"step_id": "return_letter", "disposition": "completed", "body": {"text": "return_letter", "mentions": []}, "observation_ids": []}, 1, "user-1")
        source = {"kind": "action", "source_id": "act_return_letter", "actor_character": "alice", "location": "house", "window_idx": 1}
        append_event(document, "observation_granted", {"observation_id": "note", "source": source}, 1, "user-2")
        document["knowledge"].append({"account_id": "user-2", "observation_id": "note", "source": source})
        personal_batch(document, [{"kind": "return_answered", "offer_event_id": offer["event_id"], "decision": "accepted"}, {"kind": "step_done", "step_id": "return_letter", "account_id": "user-1"}], personal_receipt(document, "user-2", closes[1]))
        self.accept(document, case)
        forged = copy.deepcopy(document)
        forged["personal_story"]["journal"][-1]["cause"]["account_id"] = "user-1"
        self.reject(forged, case)
        for patch in ({"actor_character": "bob"}, {"location": "yard"}, {"window_idx": 2}):
            forged = copy.deepcopy(document)
            forged["knowledge"][-1]["source"].update(patch)
            self.reject(forged, case)

    def test_ghost_recipient_failure_has_no_offer_or_completion(self):
        case = AlteredPersonalCase(letter_case)
        document = personal_state()
        second_personal_player(document)
        document["players"][1].update(status="ghost", ap=0)
        append_event(document, "status", {"character_id": "bob", "controller": "player", "status": "ghost"}, 1)
        document["clock"]["window_idx"] = 2
        result = append_event(document, "story_result", {"step_id": "return_letter", "disposition": "not_completed", "body": {"text": "Nothing happened", "mentions": []}, "observation_ids": []}, 2, "user-1")
        personal_receipt(document, "user-1", result)
        self.accept(document, case)
        offer_personal_letter(document, case)
        self.reject(document, case)

    def test_return_decline_requires_both_closed_streams_and_never_step_done(self):
        case = AlteredPersonalCase(letter_case)
        document = personal_state()
        second_personal_player(document)
        offer = offer_personal_letter(document, case)
        closes = [append_event(document, "story_return_closed", {"offer_event_id": offer["event_id"], "decision": "declined"}, 1, account) for account in ("user-1", "user-2")]
        personal_batch(document, [{"kind": "return_answered", "offer_event_id": offer["event_id"], "decision": "declined"}], personal_receipt(document, "user-2", closes[1]))
        self.accept(document, case)
        forged = copy.deepcopy(document)
        forged["private_events"].remove(next(e for e in forged["private_events"] if e["kind"] == "story_return_closed" and e["audience"]["ids"] == ["user-2"]))
        self.reject(forged, case)
        forged = copy.deepcopy(document)
        forged["personal_story"]["journal"][-1]["entries"].append({"kind": "step_done", "step_id": "return_letter", "account_id": "user-1"})
        self.reject(forged, case)

    def test_public_card_repeat_has_new_redacted_witness_and_first_source(self):
        def public_card(case):
            case["module_data"]["turning_point"]["concealed_npcs"] = []
            case["personal_tasks"]["topics"] = [{"id": "paper_topic", "subject": "alice", "observations": ["note"]}]
            personal_step(case, "publish_card", {"kind": "deliver_card", "observation": "note", "recipient": None}, actors=("alice", "bob"))
        case = AlteredPersonalCase(public_card)
        document = personal_state()
        second_personal_player(document)
        for account in ("user-1", "user-2"):
            batch = complete_personal(document, case, "publish_card", account)
            event = append_event(document, "authored_card_delivered", {"observation_id": "note", "body": {"text": "note", "mentions": []}}, 1)
            batch["entries"].append({"kind": "public_reveal", "topic_id": "paper_topic", "publisher_account_id": account, "event_id": event["event_id"]})
            if not document["public"]["observations"]:
                document["public"]["observations"].append({"observation_id": "note", "source": {"kind": "event", "source_id": event["event_id"], "actor_character": None, "location": None, "window_idx": 1}})
        self.accept(document, case)

        self.assertEqual(len(document["public"]["observations"]), 1)
        self.assertEqual(document["public"]["observations"][0]["source"]["source_id"], document["public"]["chronicle"][0]["event_id"])
        for change in (
            lambda d: d["public"]["chronicle"][0]["payload"].update(publisher="user-1"),
            lambda d: d["public"]["chronicle"][1]["payload"]["body"].update(text="forged"),
            lambda d: d["public"]["observations"][0]["source"].update(source_id=d["public"]["chronicle"][1]["event_id"]),
            lambda d: d["personal_story"]["journal"][-1]["entries"][-1].update(publisher_account_id="user-1"),
            lambda d: d["personal_story"]["journal"][-1]["entries"].pop(),
        ):
            forged = copy.deepcopy(document)
            change(forged)
            self.reject(forged, case)
        # Next digest includes card IDs once and only the recipient's own results.
        document["clock"]["window_idx"] = 2
        candidates = [e for e in document["public"]["chronicle"]] + [e for e in document["private_events"] if e["audience"]["ids"] == ["user-2"] and e["kind"] != "window_digest"]
        append_event(document, "window_digest", {"window_idx": 1, "event_ids": [e["event_id"] for e in candidates], "observation_ids": ["note"]}, 2, "user-2")
        self.accept(document, case)

    def test_public_batch_order_must_agree_across_different_card_witnesses(self):
        from tests.test_night_case_engine import personal_setup, personal_act
        from domain.night_case_personal import story_index, story_predicate
        def cards(case):
            case["initial"]["public_observations"].remove("public_note")
            case["personal_tasks"]["topics"][0]["observations"] = ["public_note"]
            case["personal_tasks"]["topics"].append({"id": "second_topic", "subject": "person_02", "observations": ["archive_copy"]})
            step = copy.deepcopy(next(s for s in case["personal_tasks"]["steps"] if s["id"] == "public_card"))
            step.update(id="public_second", action="act_public_second", actors=["person_02"])
            step["operation"]["observation"] = "archive_copy"
            case["personal_tasks"]["steps"].append(step)
            action = copy.deepcopy(next(a for a in case["actions"] if a["id"] == "act_public_card"))
            action.update(id="act_public_second", personal_step="public_second")
            case["actions"].append(action)
        case, rules, transition, actors = personal_setup(mutate=cards)
        transition = personal_act(case, rules, transition, actors, "person_01", "public_card")
        transition = personal_act(case, rules, transition, actors, "person_02", "public_second")
        self.assertEqual(decode_state(encode_state(transition.state), case, rules), transition.state)
        predicate = {"kind": "story_before", "step": "public_card", "boundary": {"kind": "public_reveal", "topic": "second_topic", "by": "any"}}
        self.assertTrue(story_predicate(predicate, story_index(case, transition.state), actors["person_01"]))
        forged = transition.state.document()
        journal = forged["personal_story"]["journal"]
        journal[-2:] = list(reversed(journal[-2:]))
        for seq, batch in enumerate(journal, 1):
            batch["seq"] = seq
        self.assertFalse(story_predicate(predicate, story_index(case, forged), actors["person_01"]))
        with self.assertRaisesRegex(ValueError, "public witness chronology"):
            KernelState.from_document(forged, case, rules)

    def test_frozen_return_cancellation_on_either_party_forfeit(self):
        from tests.test_night_case_engine import personal_setup, personal_act, module_play, tick
        for character in ("person_01", "person_02"):
            with self.subTest(character=character):
                case, rules, transition, actors = personal_setup()
                transition = personal_act(case, rules, transition, actors, "person_01", "return_letter")
                while transition.state.clock["phase"] != "frozen":
                    transition = tick(case, rules, transition.state, command_id="freeze" + str(transition.state.clock["window_idx"]).zfill(4))
                frozen = transition.state
                self.assertTrue(frozen.clock["opening_pending"])
                transition = module_play(case, rules, transition, "forfeit", account=actors[character])
                self.assertTrue(transition.receipt["accepted"])
                self.assertEqual(transition.state.clock["phase"], "frozen")
                closed = [e for e in transition.events if e["kind"] == "story_return_closed"]
                self.assertEqual(len(closed), 2)
                self.assertTrue(all(e["payload"]["decision"] == "cancelled" for e in closed))
                self.assertEqual(decode_state(encode_state(transition.state), case, rules), transition.state)
                forged = frozen.document()
                append_event(forged, "story_return_closed", {"offer_event_id": "unrelated-offer", "decision": "cancelled"}, frozen.clock["window_idx"], actors[character])
                with self.assertRaises(ValueError):
                    KernelState.from_document(forged, case, rules)

                forged = frozen.document()
                offer_id = next(e["event_id"] for e in forged["private_events"] if e["kind"] == "story_offer")
                for participant in ("person_01", "person_02"):
                    append_event(forged, "story_return_closed", {"offer_event_id": offer_id, "decision": "cancelled"}, frozen.clock["window_idx"], actors[participant])
                personal_batch(forged, [{"kind": "return_answered", "offer_event_id": offer_id, "decision": "cancelled"}], personal_receipt(forged, actors[character]))
                with self.assertRaisesRegex(ValueError, "frozen return cancellation"):
                    KernelState.from_document(forged, case, rules)

class CommunicationCase(ModuleCase):
    def document(self):
        doc = super().document()
        doc["communication"] = {"version": 1, "max_messages_per_window": 20}
        return doc


def communication_state():
    doc = module_state()
    doc["communication"] = {"version": 1, "sent": []}
    return doc


def message_receipt(doc, account="user-1", channel="square", audience=None, window=1):
    from domain.night_case_delivery_state import message_id_for, thread_key_for, text_hash_for
    audience = sorted(audience or [p["account_id"] for p in doc["players"]])
    cause = personal_receipt(doc, account)
    ref = {"kind": "message", "message_id": message_id_for(doc["game_id"], account, cause["command_id"]), "channel": channel, "thread_key": thread_key_for(doc["game_id"], channel, audience), "recipient_account_ids": audience, "window_idx": window, "text_hash": text_hash_for("A quiet message")}
    doc["receipts"][-1]["result_ref"] = ref
    sent = next((r for r in doc["communication"]["sent"] if r["account_id"] == account and r["window_idx"] == window), None)
    if sent is None:
        doc["communication"]["sent"].append({"account_id": account, "window_idx": window, "count": 1})
    else:
        sent["count"] += 1
    return ref


class DeliveryStateTests(unittest.TestCase):
    def setUp(self):
        self.rules = rules_snapshot("Europe/Berlin")

    def accept(self, doc, case=None):
        case = case or CommunicationCase()
        result = KernelState.from_document(doc, case, self.rules)
        self.assertEqual(decode_state(encode_state(result), case, self.rules), result)
        return result

    def reject(self, doc, case=None):
        with self.assertRaises(ValueError):
            self.accept(doc, case)

    def test_say_nfc_before_hash_sorted_targets_and_closed_text(self):
        actor = PlayerActor("user-1")
        raw = {"command_id": "speaking01", "kind": "say", "window_idx": 1, "window_seq": 1, "actor_seq": 0, "params": {"channel": "whisper", "recipients": ["charlie", "bob"], "text": "cafe\u0301"}}
        command = parse_command(raw, actor, ruleset_version=2)
        normalized = {**raw, "params": {"channel": "whisper", "recipients": ["bob", "charlie"], "text": "café"}}
        self.assertEqual(command.document(), normalized)
        self.assertEqual(command.payload_hash, parse_command(normalized, actor, ruleset_version=2).payload_hash)
        with self.assertRaises(ValueError):
            parse_command(command, actor)
        for params in (
            {"channel": "square", "recipients": ["bob"], "text": "hello"},
            {"channel": "ghost", "recipients": ["bob"], "text": "hello"},
            {"channel": "whisper", "recipients": [], "text": "hello"},
            {"channel": "whisper", "recipients": ["bob", "bob"], "text": "hello"},
            {"channel": "square", "recipients": [], "text": " \n "},
            {"channel": "square", "recipients": [], "text": "x\x00"},
            {"channel": "square", "recipients": [], "text": "x\t"},
            {"channel": "square", "recipients": [], "text": "x" * 1001},
            {"channel": "square", "recipients": [], "text": "x", "html": True},
        ):
            with self.assertRaises(ValueError):
                parse_command({**raw, "params": params}, actor, ruleset_version=2)

    def test_message_reference_acl_id_hash_thread_quota_and_capability(self):
        doc = communication_state()
        message_receipt(doc)
        self.accept(doc)
        for change in (
            lambda d: d["receipts"][-1]["result_ref"].update(message_id="msg_" + "a" * 64),
            lambda d: d["receipts"][-1]["result_ref"].update(thread_key="b" * 64),
            lambda d: d["receipts"][-1]["result_ref"].update(text_hash="invalid"),
            lambda d: d["receipts"][-1]["result_ref"].update(recipient_account_ids=["unknown"]),
            lambda d: d["receipts"][-1].update(accepted=False),
            lambda d: d["receipts"][-1].update(actor_key="system"),
            lambda d: d["receipts"][-1]["result_ref"].update(text="raw text must not be retained"),
            lambda d: d["communication"]["sent"][0].update(count=True),
            lambda d: d["communication"]["sent"][0].update(count=2),
            lambda d: d["communication"]["sent"].append(copy.deepcopy(d["communication"]["sent"][0])),
        ):
            changed = copy.deepcopy(doc)
            change(changed)
            self.reject(changed)
        self.reject(doc, ModuleCase())
        for _ in range(19):
            message_receipt(doc)
        self.accept(doc)
        message_receipt(doc)
        self.reject(doc)




class NpcDeliveryCase(CommunicationCase):
    def document(self):
        doc = super().document()
        doc["actions"][0]["fallback"] = {"text": "No clue", "mentions": []}
        doc["characters"][1].update(home="house", schedule=[])
        doc["observations"].append({"id": "slip_note", "kind": "claim", "speaker": "bob", "exists_in": "all", "body": {"text": "An uncertain recollection", "mentions": []}})
        doc["dialogues"] = [{"id": "keeper_dialogue", "character": "bob", "entry_node": "keeper_entry", "nodes": [{"id": "keeper_entry", "options": [{"id": "ask_keeper", "outcomes": [], "fallback": {"text": "The papers were here", "mentions": []}}]}]}]
        doc["npc_delivery"] = {"version": 1, "window_reveal_budget": 2, "game_reveal_budget": 4, "topics": [{"id": "keeper_topic", "npc": "bob", "dialogue": "keeper_dialogue", "node": "keeper_entry", "option": "ask_keeper", "lines": [{"id": "line_alpha", "body": {"text": "He hesitated", "mentions": []}}, {"id": "line_beta", "body": {"text": "He paused", "mentions": []}}], "slip": {"rule_id": "keeper_rule", "version": 1, "probability_bp": 10000, "observation": "slip_note", "requires": []}}]}
        return doc


def npc_delivery_state():
    from domain.night_case_delivery_state import composed_body, delivery_draw
    case = NpcDeliveryCase().document()
    doc = communication_state()
    doc["npc_delivery"] = {"version": 1, "decisions": [], "lines": []}
    discovery_trace(doc)
    append_event(doc, "npc_revealed", {"character_id": "bob", "location": "house"}, 1)
    append_event(doc, "world_changed", {"flags": [{"id": "bob_revealed", "value": True}], "locks": []}, 1)
    doc["public"]["flags"][0]["value"] = True
    topic = case["npc_delivery"]["topics"][0]
    index = delivery_draw(10, "bob", "keeper_topic", 1, 1, domain="night-case-line/1", upper=2)
    line = topic["lines"][index]
    doc["npc_delivery"]["lines"].append({"npc": "bob", "topic": "keeper_topic", "window_idx": 1, "line_id": line["id"]})
    doc["npc_delivery"]["decisions"].append({"schema": "night-city-slip/1", "scope": {"game_id": "game-1", "npc_id": "bob", "topic_id": "keeper_topic", "window_idx": 1}, "rule_id": "keeper_rule", "rule_version": 1, "probability_bp": 10000, "fact_id": "slip_note", "revealed": True, "draw": delivery_draw(10, "bob", "keeper_topic", 1, 1, domain="night-case-slip/1", upper=10000)})
    source = {"kind": "dialogue", "source_id": "ask_keeper", "actor_character": "alice", "location": "house", "window_idx": 1}
    doc["knowledge"].append({"account_id": "user-1", "observation_id": "slip_note", "source": source})
    append_event(doc, "observation_granted", {"observation_id": "slip_note", "source": copy.deepcopy(source)}, 1, "user-1")
    body = composed_body(line["body"], case["dialogues"][0]["nodes"][0]["options"][0]["fallback"])
    result = append_event(doc, "action_result", {"body": body, "observation_ids": ["slip_note"]}, 1, "user-1")
    personal_receipt(doc, "user-1", result)
    return doc


class NpcStateTests(unittest.TestCase):
    setUp = DeliveryStateTests.setUp
    accept = DeliveryStateTests.accept
    reject = DeliveryStateTests.reject

    def test_sampler_domains_and_rejection_counter_are_stable(self):
        from unittest.mock import patch
        from domain.night_case_delivery_state import delivery_draw
        requests = []
        class Digest:
            def __init__(self, first):
                self.first = first
            def digest(self):
                return (b"\xff" * 8 if self.first else (1234).to_bytes(8, "big")) + b"\x00" * 24
        def fake_hmac(key, data, digestmod):
            requests.append((key, json.loads(data)))
            return Digest(len(requests) == 1)
        with patch("domain.night_case_delivery_state.hmac.new", side_effect=fake_hmac):
            self.assertEqual(delivery_draw(42, "bob", "keeper_topic", 3, 1, domain="night-case-slip/1", upper=10000), 1234)
        self.assertEqual(requests, [(b"42", ["night-case-slip/1", "bob", "keeper_topic", 3, 1]), (b"42", ["night-case-slip/1", "bob", "keeper_topic", 3, 1, 1])])
        self.assertEqual(delivery_draw(42, "bob", "keeper_topic", 3, 1, domain="night-case-line/1", upper=2), delivery_draw(42, "bob", "keeper_topic", 3, 1, domain="night-case-line/1", upper=2))

    def test_npc_seeded_scope_body_and_claim_provenance_survive_restart(self):
        doc = npc_delivery_state()
        self.accept(doc, NpcDeliveryCase())
        for change in (
            lambda d: d["npc_delivery"]["lines"][0].update(line_id="unknown_line"),
            lambda d: d["npc_delivery"]["lines"].append(copy.deepcopy(d["npc_delivery"]["lines"][0])),
            lambda d: d["npc_delivery"]["decisions"].append(copy.deepcopy(d["npc_delivery"]["decisions"][0])),
            lambda d: d["npc_delivery"]["decisions"][0]["scope"].update(game_id="different-game"),
            lambda d: d["npc_delivery"]["decisions"][0].update(rule_version=True),
            lambda d: d["npc_delivery"]["decisions"][0].update(rule_version=2),
            lambda d: d["npc_delivery"]["decisions"][0].update(draw=9999),
            lambda d: d["npc_delivery"]["decisions"][0].update(revealed=False, draw=None),
            lambda d: d["private_events"][-1]["payload"]["body"].update(text="He invented a new fact"),
            lambda d: d["knowledge"][-1]["source"].update(kind="action"),
            lambda d: d["knowledge"][-1]["source"].update(actor_character="bob"),
            lambda d: d["knowledge"][-1]["source"].update(location="yard"),
        ):
            forged = copy.deepcopy(doc)
            change(forged)
            self.reject(forged, NpcDeliveryCase())

    def test_budget_and_claim_catalog_cannot_turn_slip_into_proof(self):
        doc = npc_delivery_state()
        for field, value in (("game_reveal_budget", 0), ("window_reveal_budget", 0), ("version", True)):
            class InvalidBudget(NpcDeliveryCase):
                def document(self):
                    case = super().document()
                    case["npc_delivery"][field] = value
                    return case
            self.reject(doc, InvalidBudget())
        class FalseProof(NpcDeliveryCase):
            def document(self):
                case = super().document()
                case["observations"][-1]["kind"] = "proof"
                return case
        self.reject(doc, FalseProof())
        orphan = npc_delivery_state()
        orphan["private_events"].pop()
        orphan["receipts"].pop()
        self.reject(orphan, NpcDeliveryCase())


class DeliveryCapacityTests(unittest.TestCase):
    setUp = DeliveryStateTests.setUp
    accept = DeliveryStateTests.accept

    def test_maximum_week_without_chat_text_uses_trusted_profile2_budget(self):
        from domain.night_case_state import MAX_BYTES, _load, _walk
        class WeekCase(CommunicationCase):
            compiler_version = "v2-4"

            def document(self):
                doc = super().document()
                doc["characters"].extend({"id": f"member_{i:02d}"} for i in range(1, 12))
                doc["personal_tasks"] = {"version": 1, "originals": [], "caches": [], "works": [], "commitments": [], "trips": [], "topics": [], "steps": []}
                for i in range(1, 43):
                    personal_step(doc, f"task_{i:02d}", {"kind": "record_deed"}, actors=["alice"] + [f"member_{j:02d}" for j in range(1, 12)])
                return doc
        doc = communication_state()
        doc["compiler_version"] = "v2-4"
        doc["personal_story"] = {"version": 1, "journal": []}
        case = WeekCase()
        for i in range(1, 12):
            account = f"00000000-0000-0000-0000-{i:012d}"
            character = f"member_{i:02d}"
            player = copy.deepcopy(doc["players"][0])
            player.update(account_id=account, character_id=character, name=f"Member {i}", knowledge_revision=0)
            doc["players"].append(player)
            doc["sealed"]["assignments"].append({"account_id": account, "character_id": character})
        for window in range(1, 15):
            doc["clock"].update(window_idx=window, phase="final_hearing" if window == 14 else "investigation")
            for player in doc["players"]:
                for _ in range(20):
                    message_receipt(doc, player["account_id"], window=window)
                for slot in range(1, 4):
                    complete_personal(doc, case, f"task_{(window - 1) * 3 + slot:02d}", player["account_id"])
        for player in doc["players"]:
            actor_receipts = [r for r in doc["receipts"] if r["actor_key"] == "account:" + player["account_id"] and r["accepted"]]
            for revision, receipt in enumerate(actor_receipts, 1):
                receipt["actor_revision"] = revision
            player.update(actor_seq=len(actor_receipts), last_seen_window=14, participated_windows=list(range(1, 15)), ap=0)
        state = self.accept(doc, case)
        encoded = encode_state(state)
        self.assertGreater(len(encoded), MAX_BYTES)
        self.assertLessEqual(len(encoded), 16 * 1024 * 1024)
        self.assertEqual(len(doc["communication"]["sent"]), 12 * 14)
        self.assertEqual(sum(r["count"] for r in doc["communication"]["sent"]), 12 * 14 * 20)
        self.assertEqual(len(doc["personal_story"]["journal"]), 12 * 14 * 3)
        self.assertNotIn(b"A quiet message", encoded)
        counter = [0]
        _walk(state.document(), counter=counter, max_nodes=500000)
        self.assertLessEqual(counter[0], 500000)
        with self.assertRaises(ValueError):
            _load(encoded)
        with self.assertRaises(ValueError):
            decode_state(encoded, FakeCase(), self.rules)
        with self.assertRaises(ValueError):
            decode_state(b" " * (16 * 1024 * 1024 + 1), WeekCase(), self.rules)
        print(f"bounded-week: say={12 * 14 * 20}, personal={12 * 14 * 3}, bytes={len(encoded)}, nodes={counter[0]}")


if __name__ == "__main__":
    unittest.main()
