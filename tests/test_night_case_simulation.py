"""Reproducible core-case witness and bounded policy checks."""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from domain.night_case_engine import _initialize
from domain.night_case_projection import CommandIntent, quote_action
from domain.night_case_simulation import (
    DEFAULT_START, SearchBudget, Witness, find_witness, replay_witness, run_smoke_policy,
    validate_matrix,
)
from domain.night_case_state import PlayerActor, canonical_hash, rules_snapshot
from domain.night_case_v2_format import compile_v2, load_v2


FIXTURE = Path(__file__).parent / "fixtures" / "night_city" / "core_case_v2.json"
MODULE_FIXTURE = Path(__file__).parent / "fixtures" / "night_city" / "modules_case_v2.json"
RUNTIME_FIXTURE = Path(__file__).parent / "fixtures" / "night_city" / "runtime_case_v2.json"
CORE_TRACE_HASHES = (
    "7810f787aabe48873f757eb717fb23152cdfe9e9edf3c2b8da6c094cb48719da",
    "c46811f13d2a64754281dd9ac5a21287c3e8a2d6b1860bbc76c4280959f9bfff",
    "8153049297c7012ab6dce48833bd1e5f403d5be9860774a445639b66e7757da9",
    "96459c6fc31930a731a1e362884c19144f2fb14c9735f690bde2d5bc2fb6b20a",  # the accused player opposes (finding 3)
    "c718a1a57d638da539f0e1187e13f01ea9bd6a34fbe64499f0fa01899bd46265",
    "56e6dda31bd0f91e91750c9acfa6f9d6650e9a4e7dc9fcf8c33ec8eb2fecb205",
    "29946ab48efd264f6e8ffe1b811a2ab9c3bf77f3a605613bfa33cadec10f144b",
    "8411afd7ff6bd28b986d7c3349d21a27536a72378e0b30a28f34d8ec53fa8a64",  # the accused player opposes (finding 3)
)


class SimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = compile_v2(load_v2(FIXTURE.read_bytes()))
        cls.rules = rules_snapshot("Europe/Berlin")

    def test_matrix_replays_all_compositions_and_variants(self):
        before_case, before_rules = self.case.document(), self.rules.document()
        report = validate_matrix(self.case, self.rules, seed=42, budget=SearchBudget())
        self.assertEqual(len(report.results), 8)
        self.assertTrue(report.scope_passed)
        for result, historical_hash in zip(report.results, CORE_TRACE_HASHES):
            actual = result.witness.document()["trace_hash"]
            if historical_hash is not None:
                self.assertEqual(actual, historical_hash)
        for result in report.results:
            self.assertEqual(result.status, "found")
            self.assertTrue(replay_witness(self.case, self.rules, result.witness).passed)
        again = find_witness(self.case, self.rules, "players_04", "variant_a", seed=42, budget=SearchBudget())
        self.assertEqual(report.results[0].witness.document()["trace_hash"], again.witness.document()["trace_hash"])
        self.assertEqual(self.case.document(), before_case)
        self.assertEqual(self.rules.document(), before_rules)

    def test_witness_strict_and_tamper_resistant(self):
        result = find_witness(self.case, self.rules, "players_04", "variant_a", seed=42, budget=SearchBudget())
        self.assertEqual(result.status, "found")
        witness = result.witness
        self.assertTrue(replay_witness(self.case, self.rules, witness).passed)
        self.assertEqual(witness.document(), Witness.from_json(witness.to_json()).document())
        for field, value in (("case_hash", "0" * 64), ("rules_hash", "0" * 64),
                             ("variant_id", "variant_b"), ("final_code", "unresolved")):
            changed = witness.document(); changed[field] = value
            self.assertFalse(replay_witness(self.case, self.rules, Witness.from_document(changed)).passed)
        bad_receipt = witness.document()["steps"][0]["expected_receipt"]
        bad_receipt["accepted"] = False
        for field, value in (("command", {"kind": "seen"}), ("now_utc", "2020-01-01T00:00:00Z"),
                             ("expected_receipt", bad_receipt), ("state_hash", "0" * 64)):
            changed = witness.document(); changed["steps"][0][field] = value
            self.assertFalse(replay_witness(self.case, self.rules, Witness.from_document(changed)).passed)
        changed = witness.document(); changed["steps"][0]["actor"] = {"kind": "player", "account_id": "intruder"}
        self.assertFalse(replay_witness(self.case, self.rules, Witness.from_document(changed)).passed)
        changed = witness.document(); changed["steps"][0]["now_utc"] = "1999-01-01T00:00:00Z"
        self.assertFalse(replay_witness(self.case, self.rules, Witness.from_document(changed)).passed)
        changed = witness.document(); changed["unexpected"] = 1
        with self.assertRaises(ValueError): Witness.from_document(changed)
        raw = witness.to_json().decode().replace('"schema":', '"schema":"night-city-witness/1","schema":', 1)
        with self.assertRaises(ValueError): Witness.from_json(raw.encode())

    def test_budget_is_inconclusive(self):
        result = find_witness(self.case, self.rules, "players_04", "variant_a", seed=42,
                              budget=SearchBudget(max_commands=1, max_states=1, max_seconds=1))
        self.assertEqual(result.status, "inconclusive")
        self.assertIsNone(result.witness)
        with self.assertRaises(ValueError): SearchBudget(max_commands=True)
        with self.assertRaises(ValueError): SearchBudget(max_seconds=float("nan"))

    def test_smoke_policies_reach_terminal(self):
        for policy, expected in (("passive_presence", "unresolved"), ("absent", "forgotten")):
            with self.subTest(policy=policy):
                result = run_smoke_policy(self.case, self.rules, "players_04", "variant_a",
                                          policy=policy, seed=42, budget=SearchBudget())
                self.assertEqual(result.final_code, expected)
                self.assertTrue(result.passed)
        random_result = run_smoke_policy(self.case, self.rules, "players_04", "variant_a",
                                          policy="seeded_random", seed=42, budget=SearchBudget())
        self.assertIn(random_result.status, {"terminal", "inconclusive"})


if __name__ == "__main__": unittest.main()


class ModuleSimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = compile_v2(load_v2(MODULE_FIXTURE.read_bytes()))
        cls.rules = rules_snapshot("Europe/Berlin")

    def test_module_matrix_replays_through_archive_delivery_and_comparison(self):
        report = validate_matrix(self.case, self.rules, seed=42, budget=SearchBudget())
        self.assertEqual(len(report.results), 8)
        self.assertTrue(report.scope_passed, [(r.status, r.reason) for r in report.results])
        for result in report.results:
            self.assertEqual(result.status, "found")
            witness = result.witness
            self.assertEqual(witness.document()["engine_version"], "night-case-core/2")
            self.assertTrue(replay_witness(self.case, self.rules, witness).passed)
            kinds = [step["command"]["kind"] for step in witness.document()["steps"]]
            self.assertIn("archive_request", kinds)
            self.assertIn("system.tick", kinds)
            self.assertIn("act", kinds)
            self.assertIn("pin", kinds)
        wrong_build = report.results[0].witness.document()
        wrong_build["engine_version"] = "night-case-core/1"
        self.assertFalse(replay_witness(self.case, self.rules, Witness.from_document(wrong_build)).passed)

    def test_module_smoke_reports_terminal_or_inconclusive(self):
        for policy, expected in (("passive_presence", "unresolved"), ("absent", "forgotten")):
            result = run_smoke_policy(self.case, self.rules, "players_04", "variant_a",
                                      policy=policy, seed=42, budget=SearchBudget())
            self.assertEqual(result.final_code, expected)
            self.assertTrue(result.passed)
        random_result = run_smoke_policy(self.case, self.rules, "players_04", "variant_a",
                                          policy="seeded_random", seed=42, budget=SearchBudget())
        self.assertIn(random_result.status, {"terminal", "inconclusive"})

    def test_required_proofs_are_not_dropped_when_min_key_is_lower(self):
        source = json.loads(MODULE_FIXTURE.read_text(encoding="utf-8"))
        variant = source["variants"][0]
        variant["min_key"] = 2
        variant["required_key_proofs"] = list(variant["key_proofs"])
        case = compile_v2(load_v2(json.dumps(source, ensure_ascii=False).encode()))
        result = find_witness(case, self.rules, "players_04", variant["id"], seed=42,
                              budget=SearchBudget())
        self.assertEqual(result.status, "found", result.reason)
        self.assertTrue(replay_witness(case, self.rules, result.witness).passed)
        cited = [s["command"]["params"]["citations"] for s in result.witness.document()["steps"]
                 if s["command"]["kind"] in {"accuse", "vote", "final_vote"}]
        self.assertGreaterEqual(len(set().union(*map(set, cited))), 3)


class CommunicationSimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = compile_v2(load_v2(RUNTIME_FIXTURE.read_bytes()))
        cls.rules = rules_snapshot("Europe/Berlin")

    def _say_prefix(self):
        roster = {"players": [{"account_id": f"speaker_{i:02d}", "display_name": f"Speaker {i}"}
                             for i in range(4)],
                  "npc_name_pool": [f"Case NPC {i:02d}" for i in range(20)]}
        game_id = "runtime_prefix_case"
        now = datetime.fromisoformat(DEFAULT_START.replace("Z", "+00:00"))
        initial = _initialize(self.case, self.rules, roster, game_id=game_id, seed=42,
                              composition_id="players_04", selected_variant_id="variant_a", now_utc=now)
        actor = PlayerActor("speaker_00")
        params = {"channel": "square", "recipients": [], "text": "Проверка сообщения"}
        quote_action(self.case, self.rules, initial.state, actor, CommandIntent("say", params), now_utc=now)
        clock = initial.state.clock
        command = {"command_id": "prefix_say_001", "kind": "say", "params": params,
                   "window_idx": clock["window_idx"], "window_seq": clock["window_seq"], "actor_seq": 0}
        return roster, game_id, {"actor": {"kind": "player", "account_id": actor.account_id},
                                 "command": command, "now_utc": DEFAULT_START}

    def test_chat_witness_prefix_replay_and_tampering(self):
        roster, game_id, prefix = self._say_prefix()
        result = find_witness(self.case, self.rules, "players_04", "variant_a", seed=42,
                              roster=roster, game_id=game_id, prefix_steps=(prefix,), budget=SearchBudget())
        self.assertEqual(result.status, "found", result.reason)
        doc = result.witness.document()
        self.assertEqual(doc["schema"], "night-city-witness/2")
        self.assertEqual(doc["steps"][0]["command"], prefix["command"])
        self.assertEqual(doc["steps"][0]["expected_messages"][0]["text"], "Проверка сообщения")
        self.assertTrue(replay_witness(self.case, self.rules, result.witness).passed)
        self.assertEqual(doc, Witness.from_json(result.witness.to_json()).document())
        for field, value in (("text", "подмена"), ("text_hash", "0" * 64),
                             ("recipient_account_ids", ["speaker_00"]), ("thread_key", "0" * 64)):
            changed = result.witness.document()
            changed["steps"][0]["expected_messages"][0][field] = value
            changed["trace_hash"] = canonical_hash({k: v for k, v in changed.items() if k != "trace_hash"})
            self.assertFalse(replay_witness(self.case, self.rules, Witness.from_document(changed)).passed)
        changed = result.witness.document(); changed["steps"][0]["expected_messages"] = []
        changed["trace_hash"] = canonical_hash({k: v for k, v in changed.items() if k != "trace_hash"})
        self.assertFalse(replay_witness(self.case, self.rules, Witness.from_document(changed)).passed)
        changed = result.witness.document(); changed["steps"][0]["now_utc"] = "1999-01-01T00:00:00Z"
        changed["trace_hash"] = canonical_hash({k: v for k, v in changed.items() if k != "trace_hash"})
        self.assertFalse(replay_witness(self.case, self.rules, Witness.from_document(changed)).passed)
        changed = result.witness.document(); changed["steps"][0]["command"]["params"]["text"] = "другой текст"
        changed["trace_hash"] = canonical_hash({k: v for k, v in changed.items() if k != "trace_hash"})
        self.assertFalse(replay_witness(self.case, self.rules, Witness.from_document(changed)).passed)

    def test_prefix_budget_and_time_are_checked(self):
        roster, game_id, prefix = self._say_prefix()
        result = find_witness(self.case, self.rules, "players_04", "variant_a", seed=42,
                              roster=roster, game_id=game_id, prefix_steps=(prefix,),
                              budget=SearchBudget(max_commands=1, max_states=2, max_seconds=10))
        self.assertEqual(result.status, "inconclusive")
        self.assertEqual(result.reason, "command_budget")
        earlier = dict(prefix); earlier["now_utc"] = "1999-01-01T00:00:00Z"
        with self.assertRaises(ValueError):
            find_witness(self.case, self.rules, "players_04", "variant_a", seed=42,
                         roster=roster, game_id=game_id, prefix_steps=(earlier,), budget=SearchBudget())

    def test_original_and_all_slips_false_clone_have_distinct_witnesses(self):
        source = json.loads(RUNTIME_FIXTURE.read_text(encoding="utf-8"))
        clone = json.loads(json.dumps(source))
        for topic in clone["npc_delivery"]["topics"]:
            if topic["slip"] is not None:
                topic["slip"]["probability_bp"] = 0
        changed = compile_v2(load_v2(json.dumps(clone, ensure_ascii=False).encode()))
        self.assertEqual(self.case.content_hash, "0936e96c0918b07e06daf0ae7dd64f93822e83dd40af57b72f7b17018c1139e2")
        self.assertEqual(changed.content_hash, "d7c132dbc57154d8526358fac047bfdec19e8624278617debe7af0208eaa932d")
        witnesses = []
        for case in (self.case, changed):
            result = find_witness(case, self.rules, "players_04", "variant_a", seed=42, budget=SearchBudget())
            self.assertEqual(result.status, "found", result.reason)
            self.assertEqual(result.witness.document()["case_hash"], case.content_hash)
            self.assertTrue(replay_witness(case, self.rules, result.witness).passed)
            witnesses.append(result.witness)
        self.assertFalse(replay_witness(self.case, self.rules, witnesses[1]).passed)


class ManorPrefixSimulationTests(unittest.TestCase):
    def test_burn_history_continues_to_standard_witness(self):
        from tests.test_manor_case import CASE, RULES, START, Play

        play = Play(4)
        for action in ("lawyer_read_draft", "lawyer_take_draft", "burn_original"):
            play.act("lawyer", "act_" + action)
        prefix = tuple({key: item[key] for key in ("actor", "command", "now_utc")}
                       for item in play.steps)
        result = find_witness(CASE, RULES, play.composition, play.variant, seed=play.seed,
                              start_at=START.isoformat().replace("+00:00", "Z"),
                              roster=play.roster, game_id=play.game_id, prefix_steps=prefix,
                              budget=SearchBudget())
        self.assertEqual(result.status, "found", result.reason)
        steps = result.witness.document()["steps"]
        self.assertEqual([s["command"] for s in steps[:len(prefix)]], [s["command"] for s in prefix])
        self.assertTrue(replay_witness(CASE, RULES, result.witness).passed)
