import json
import unittest
from datetime import datetime, timedelta, timezone

from domain.night_case_narrative import (
    ActionContext, ActionProposal, EpisodeCandidateDraft, LegalAction,
    NarrationView, SlipDecision, SlipRule, SlipScope, build_narrative_job,
    confirm_action, decide_slip, propose_action, validate_narrative_result,
    slip_decision_from_json, slip_decision_to_json,
)


NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)


class NarrativeTests(unittest.TestCase):
    def test_job_whitelist_and_fallback(self):
        view = NarrationView(audience="private", audience_key="account-secret-canary",
                             facts=("Открыта дверь",), references=("door",),
                             catalog_ids=("scene_1",), knowledge_revision="private-rev-canary",
                             window_idx=3, case_hash="sealed-hash-canary",
                             ruleset_version="ruleset-canary")
        job = build_narrative_job(view, job_id="job_1", cause_id="cause_1",
                                  kind="scene_narration", expires_at=NOW + timedelta(hours=1),
                                  fallback="Дверь открыта.")
        payload = json.dumps(job.provider_payload)
        for canary in ("account-secret-canary", "private-rev-canary", "sealed-hash-canary", "ruleset-canary"):
            self.assertNotIn(canary, payload)
        valid = {"text": "Ветер тронул дверь.", "references": ["door"],
                 "catalog_ids": ["scene_1"], "request_token": job.provider_payload["request_token"],
                 "kind": "scene_narration"}
        result = validate_narrative_result(job, valid, now=NOW)
        self.assertEqual(result.source, "candidate")
        self.assertFalse(hasattr(result, "semantic_proof"))
        bads = [dict(valid, references=["secret"]), dict(valid, catalog_ids=["unknown"]),
                dict(valid, request_token="wrong"), dict(valid, kind="npc_reply"),
                dict(valid, effect="win")]
        for bad in bads:
            self.assertEqual(validate_narrative_result(job, bad, now=NOW).text, job.fallback)
        self.assertEqual(validate_narrative_result(job, {}, now=NOW + timedelta(hours=2)).source, "fallback")
        self.assertEqual(validate_narrative_result(job, valid, now=job.expires_at).source, "fallback")
        self.assertEqual(validate_narrative_result(job, valid, now=job.expires_at + timedelta(seconds=1)).source,
                         "fallback")

    def test_view_fact_text_has_per_item_and_total_limits(self):
        base = dict(audience="private", audience_key="account", references=(), catalog_ids=(),
                    knowledge_revision="rev", window_idx=1, case_hash="hash", ruleset_version="rules")
        NarrationView(facts=("x" * 1200,), **base)
        with self.assertRaises(ValueError):
            NarrationView(facts=("x" * 1201,), **base)
        with self.assertRaises(ValueError):
            NarrationView(facts=("x" * 1200,) * 14, **base)
        with self.assertRaises(ValueError):
            NarrationView(facts=("x",) * 65, **base)
        # Entity IDs keep their existing 128-character limit.
        id_view = {**base, "references": ("r" * 128,)}
        NarrationView(facts=(), **id_view)
        with self.assertRaises(ValueError):
            NarrationView(facts=(), **{**base, "references": ("r" * 129,)})

    def test_proposal_is_snapshot_and_confirm_rechecks(self):
        context = ActionContext("game1", "actor1", 2, 4, NOW)
        params = {"item": ["door"]}
        action = LegalAction("look", "examine", "door", 1, "resource1", params)
        proposal = propose_action("look", (action,), context, proposal_id="p1",
                                  expires_at=NOW + timedelta(minutes=5))
        params["item"].append("secret")
        self.assertEqual(json.loads(proposal.params), {"item": ["door"]})
        command = confirm_action(proposal, context, (action,), now=NOW)
        self.assertEqual(command.command_id, confirm_action(proposal, context, (action,), now=NOW).command_id)
        for stale_context in (ActionContext("game2", "actor1", 2, 4, NOW),
                              ActionContext("game1", "actor2", 2, 4, NOW),
                              ActionContext("game1", "actor1", 3, 4, NOW)):
            with self.assertRaises(ValueError):
                confirm_action(proposal, stale_context, (action,), now=NOW)
        with self.assertRaises(ValueError):
            confirm_action(proposal, context, (LegalAction("look", "examine", "door", 2, "resource1", {"item": ["door"]}),), now=NOW)
        self.assertNotEqual(LegalAction("x", "k", "t", 0, "r", {}).params,
                            LegalAction("x", "k", "t", 0, "r", []).params)
        self.assertNotEqual(LegalAction("x", "k", "t", 0, "r", {"k": "v"}).params,
                            LegalAction("x", "k", "t", 0, "r", [["k", "v"]]).params)
        for changed in (LegalAction("look", "examine", "other", 1, "resource1", {"item": ["door"]}),
                        LegalAction("look", "examine", "door", 1, "resource1", {"item": ["other"]}),
                        LegalAction("look", "examine", "door", 1, "resource1", {"item": ["door"]}, "rev2")):
            with self.assertRaises(ValueError):
                confirm_action(proposal, context, (changed,), now=NOW)
        with self.assertRaises(ValueError):
            confirm_action(proposal, context, (action,), now=proposal.expires_at)
        with self.assertRaises(ValueError):
            LegalAction("bad", "move", "door", True, "r")
        with self.assertRaises(ValueError):
            ActionContext("g", "a", True, 0, NOW)
        with self.assertRaises(ValueError):
            propose_action("look", (action, action), context, proposal_id="p2", expires_at=NOW + timedelta(minutes=5))
        other = propose_action("look", (action,), ActionContext("game1", "actor2", 2, 4, NOW),
                               proposal_id="p3", expires_at=NOW + timedelta(minutes=5))
        self.assertNotEqual(other.actor_id, proposal.actor_id)

    def test_slip_roundtrip_reuse_and_budget(self):
        rule = SlipRule("topic_rule", 2, 5000, "fact_1")
        scope = SlipScope("game1", "npc1", "topic1", 3)
        first = decide_slip(rule, scope, previous=None, remaining_budget=1, draw=4000)
        self.assertEqual(first.budget_delta, -1)
        restored = slip_decision_from_json(slip_decision_to_json(first.decision))
        self.assertEqual(restored, first.decision)
        replay = decide_slip(rule, scope, previous=restored, remaining_budget=0, draw=9999)
        self.assertEqual(replay.decision, first.decision)
        self.assertTrue(replay.reused)
        self.assertEqual(replay.budget_delta, 0)
        changed_probability = SlipRule("topic_rule", 2, 4000, "fact_1")
        with self.assertRaises(ValueError):
            decide_slip(changed_probability, scope, previous=restored, remaining_budget=1, draw=1)
        self.assertFalse(decide_slip(rule, SlipScope("game1", "npc1", "topic1", 4),
                                     previous=None, remaining_budget=0, draw=0).decision.revealed)
        self.assertFalse(decide_slip(SlipRule("r", 1, 0, "f"), scope,
                                     previous=None, remaining_budget=1, draw=0).decision.revealed)
        self.assertTrue(decide_slip(SlipRule("r", 1, 10000, "f"), scope,
                                    previous=None, remaining_budget=1, draw=9999).decision.revealed)
        self.assertEqual(decide_slip(SlipRule("r", 1, 0, "f"), scope,
                                     previous=None, remaining_budget=1, draw=0).budget_delta, 0)
        with self.assertRaises(ValueError):
            decide_slip(rule, SlipScope("game1", "npc1", "topic1", 4),
                        previous=restored, remaining_budget=1, draw=1)
        with self.assertRaises(ValueError):
            decide_slip(SlipRule("topic_rule", 3, 5000, "fact_1"), scope,
                        previous=restored, remaining_budget=1, draw=1)
        with self.assertRaises(ValueError):
            decide_slip(rule, scope, previous=None, remaining_budget=1, draw=True)
        with self.assertRaises(ValueError):
            decide_slip(rule, scope, previous=None, remaining_budget=1, draw=10000)

    def test_slip_decision_rejects_impossible_direct_construction(self):
        scope = SlipScope("game1", "npc1", "topic1", 0)
        base = (scope, "rule", 1, 5000, "fact")
        for revealed, draw in ((True, None), (True, 5000), (False, 4999)):
            with self.subTest(revealed=revealed, draw=draw), self.assertRaises(ValueError):
                SlipDecision(*base, revealed, draw)
        for version, probability, draw, revealed in (
            (0, 5000, 1000, True), (True, 5000, 1000, True),
            (1, True, 1000, True), (1, 10001, 1000, True),
            (1, 5000, True, True), (1, 5000, 10000, False),
            (1, 5000, None, 1),
        ):
            with self.subTest(version=version, probability=probability, draw=draw), self.assertRaises(ValueError):
                SlipDecision(scope, "rule", version, probability, "fact", revealed, draw)

    def test_slip_codec_is_versioned_and_rejects_duplicates_nonfinite_and_limits(self):
        decision = decide_slip(SlipRule("r", 1, 5000, "f"),
                               SlipScope("g", "n", "t", 1),
                               previous=None, remaining_budget=1, draw=1000).decision
        encoded = slip_decision_to_json(decision)
        self.assertEqual("night-city-slip/1", json.loads(encoded)["schema"])
        self.assertEqual(decision, slip_decision_from_json(encoded))
        for raw in (
            encoded[:-1] + ',"schema":"night-city-slip/1"}',
            encoded.replace('"draw":1000', '"draw":NaN'),
            encoded.replace('"schema":"night-city-slip/1"', '"schema":"night-city-slip/2"'),
            encoded[:-1] + ',"extra":true}',
            encoded + " " * 16_384,
            '{"schema":"night-city-slip/1","scope":' + "[" * 12 + "0" + "]" * 12 + "}",
        ):
            with self.subTest(raw_length=len(raw)), self.assertRaises(ValueError):
                slip_decision_from_json(raw)

    def test_episode_always_draft(self):
        draft = EpisodeCandidateDraft.create("episode_1", "scene_narration", "A harmless scene", ("scene_1",),
                                             source_job_id="job_1", allowed_catalog_ids=("scene_1",))
        self.assertEqual(draft.status, "draft")
        self.assertEqual(draft.source_job_id, "job_1")
        self.assertFalse(hasattr(draft, "apply"))
        with self.assertRaises(ValueError):
            EpisodeCandidateDraft.create("episode_1", "scene_narration", "x", ("unknown",), allowed_catalog_ids=("scene_1",))
        with self.assertRaises(ValueError):
            EpisodeCandidateDraft("x", "story_offer", "text", (), "job", "published")


if __name__ == "__main__":
    unittest.main()
