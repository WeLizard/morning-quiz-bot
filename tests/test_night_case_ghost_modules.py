"""Removed-player modules (MANOR_MODULES_V2 §9): whisper, testimony and signs, with codec and projection."""

import copy
import json
import unittest

from domain.night_case_projection import CommandIntent, MenuChoice, MenuForm, available_actions, project, quote_action, removed_label
from domain.night_case_state import KernelState, PlayerActor, decode_state, encode_state
from tests.test_night_case_engine import module_play, module_setup, tick

GHOST_MODULES = ("ghost_whisper", "ghost_testimony", "ghost_visions")
SIGN = {"id": "sign_cold", "character": "person_00", "location": "foyer", "label": "Остудить прихожую",
        "body": {"text": "В прихожей вдруг стало холодно, свеча легла набок.", "mentions": []}}


def ghost_case(modules=GHOST_MODULES, count=4):
    def mutate(document):
        document["meta"]["modules"] += list(modules)
        for name in modules:
            document["module_data"][name] = {"signs": [SIGN]} if name == "ghost_visions" else {}
        for character in document["characters"]:
            character["ghost_memories"] = ["public_note", "proof_common", "proof_mechanism"]
    return module_setup(count=count, mutate=mutate)


def character_of(t, account):
    return next(p["character_id"] for p in t.state.players if p["account_id"] == account)


def make_ghost(case, rules, t, account="account0", accuser="account2"):
    """A wrong accusation removes `account` (the fixture culprit is an NPC in a 4-player table)."""
    while t.state.clock["window_idx"] < 3:
        for p in list(t.state.players): t = module_play(case, rules, t, "seen", account=p["account_id"])
        t = tick(case, rules, t.state, command_id="before00" + str(t.state.clock["window_idx"]))
    t = module_play(case, rules, t, "accuse", {"suspect": character_of(t, account), "citations": []}, accuser)
    hearing = t.state.hearing["id"]
    for p in list(t.state.players):
        if p["status"] == "active": t = module_play(case, rules, t, "vote", {"hearing_id": hearing, "choice": "support", "citations": []}, p["account_id"])
    t = tick(case, rules, t.state, command_id="open0000" + str(t.state.clock["window_idx"]))
    for p in list(t.state.players):
        if p["status"] == "active": t = module_play(case, rules, t, "seen", account=p["account_id"])
    t = tick(case, rules, t.state, command_id="resolve" + str(t.state.clock["window_idx"]))
    assert next(p for p in t.state.players if p["account_id"] == account)["status"] == "ghost"
    return t


def learn_key(case, rules, t, account="account0"):
    """The actor learns proof_common privately (inspect_key in the foyer)."""
    t = module_play(case, rules, t, "act", {"action_id": "inspect_key"}, account)
    assert t.receipt["accepted"], t.receipt
    assert any(k["account_id"] == account and k["observation_id"] == "proof_common" for k in t.state.knowledge)
    return t


def menu(case, rules, t, account):
    clock = t.state.clock
    from datetime import datetime
    now = datetime.fromisoformat((clock["opened_at"] or clock["freeze_at"]).replace("Z", "+00:00"))
    return available_actions(case, rules, t.state, PlayerActor(account), now_utc=now)


def choices(entries, kind):
    return [e for e in entries if isinstance(e, MenuChoice) and e.quote.kind == kind]


def roundtrip(case, rules, t):
    return decode_state(encode_state(t.state), case, rules).document()


def rejects(case, rules, document):
    with_error = None
    try: KernelState.from_document(document, case, rules)
    except ValueError as exc: with_error = str(exc)
    return with_error


class GhostWhisperTests(unittest.TestCase):
    def setUp(self):
        self.case, self.rules, t = ghost_case()
        t = learn_key(self.case, self.rules, t)
        self.t = make_ghost(self.case, self.rules, t)
        self.ghost, self.living = character_of(self.t, "account0"), character_of(self.t, "account1")

    def test_whisper_passes_memory_privately_with_ghost_source(self):
        case, rules, t = self.case, self.rules, self.t
        offered = choices(menu(case, rules, t, "account0"), "ghost_whisper")
        # Only the private memory, never the public note, to each living player.
        self.assertEqual({json.loads(c.quote.params)["observation_id"] for c in offered}, {"proof_common"})
        self.assertEqual(len(offered), 3)
        self.assertTrue(all(c.quote.cost == 0 for c in offered))
        out = module_play(case, rules, t, "ghost_whisper", {"observation_id": "proof_common", "recipient": self.living})
        self.assertTrue(out.receipt["accepted"], out.receipt)
        ghost = next(p for p in out.state.players if p["account_id"] == "account0")
        self.assertEqual(ghost["ghost_used_window"], out.state.clock["window_idx"])
        knowledge = next(k for k in out.state.knowledge if k["account_id"] == "account1" and k["observation_id"] == "proof_common")
        received = next(e for e in out.state.private_events if e["kind"] == "ghost_whisper_received")
        self.assertEqual(received["audience"]["ids"], ["account1"])
        self.assertEqual(knowledge["source"], {"kind": "ghost", "source_id": received["event_id"], "actor_character": self.ghost, "location": None, "window_idx": received["window_idx"]})
        whispered = next(e["event_id"] for e in out.state.private_events if e["kind"] == "ghost_whispered")
        self.assertTrue(any(r["actor_key"] == "account:account0" and r["result_ref"] == {"kind": "event", "event_id": whispered} for r in out.state.receipts))
        self.assertEqual(roundtrip(case, rules, out), out.state.document())
        # The recipient sees who passed it; the sender sees whom; nothing goes public.
        view = project(case, rules, out.state, PlayerActor("account1"))
        self.assertEqual([(r["observation_id"], r["from_character"]) for r in view["self"]["modules"]["ghost_whisper"]["received"]], [("proof_common", self.ghost)])
        sender = project(case, rules, out.state, PlayerActor("account0"))
        self.assertEqual([r["recipient_character"] for r in sender["self"]["modules"]["ghost_whisper"]["sent"]], [self.living])
        self.assertNotIn("ghost_whispered", {e["kind"] for e in out.state.public["chronicle"]})
        # One ghost action per window: the share is gone for this window.
        refused = module_play(case, rules, out, "ghost_share", {"observation_id": "proof_common"})
        self.assertEqual(refused.receipt["code"], "action_unavailable")
        # The recipient can publish it; the board keeps the ghost path.
        pinned = module_play(case, rules, out, "pin", {"observation_id": "proof_common"}, "account1")
        self.assertTrue(pinned.receipt["accepted"], pinned.receipt)
        self.assertEqual(pinned.state.public["board"][-1]["source"]["kind"], "ghost")

    def test_no_second_copy_to_the_same_player(self):
        case, rules = self.case, self.rules
        out = module_play(case, rules, self.t, "ghost_whisper", {"observation_id": "proof_common", "recipient": self.living})
        t = out
        for p in list(t.state.players):
            if p["status"] == "active": t = module_play(case, rules, t, "seen", account=p["account_id"])
        t = tick(case, rules, t.state, command_id="next0000" + str(t.state.clock["window_idx"]))
        self.assertEqual(t.state.clock["window_idx"], out.state.clock["window_idx"] + 1)
        offered = {json.loads(c.quote.params)["recipient"] for c in choices(menu(case, rules, t, "account0"), "ghost_whisper")}
        self.assertEqual(offered, {character_of(t, "account2"), character_of(t, "account3")})
        again = module_play(case, rules, t, "ghost_whisper", {"observation_id": "proof_common", "recipient": self.living})
        self.assertEqual(again.receipt["code"], "action_unavailable")

    def test_whisper_refusals(self):
        case, rules, t = self.case, self.rules, self.t
        for params in ({"observation_id": "public_note", "recipient": self.living},          # public already
                       {"observation_id": "proof_mechanism", "recipient": self.living},      # not known
                       {"observation_id": "proof_common", "recipient": self.ghost},          # self
                       {"observation_id": "proof_common", "recipient": "missing_keeper"}):   # NPC
            with self.subTest(params=params):
                self.assertEqual(module_play(case, rules, t, "ghost_whisper", params).receipt["code"], "action_unavailable")
        living = module_play(case, rules, t, "ghost_whisper", {"observation_id": "proof_common", "recipient": self.ghost}, "account1")
        self.assertEqual(living.receipt["code"], "action_unavailable")

    def test_codec_rejects_tampered_whisper_history(self):
        case, rules = self.case, self.rules
        out = module_play(case, rules, self.t, "ghost_whisper", {"observation_id": "proof_common", "recipient": self.living})
        base = out.state.document()
        cases = {}
        doc = copy.deepcopy(base); next(e for e in doc["private_events"] if e["kind"] == "ghost_whisper_received")["payload"]["from_character"] = self.living
        cases["forged sender"] = doc
        doc = copy.deepcopy(base); next(e for e in doc["private_events"] if e["kind"] == "ghost_whispered")["payload"]["recipient_character"] = character_of(self.t, "account3")
        cases["pair mismatch"] = doc
        doc = copy.deepcopy(base); next(p for p in doc["players"] if p["account_id"] == "account0")["ghost_used_window"] = None
        cases["used window behind"] = doc
        doc = copy.deepcopy(base)
        row = next(k for k in doc["knowledge"] if k["account_id"] == "account1" and k["observation_id"] == "proof_common")
        row["source"]["actor_character"] = character_of(self.t, "account3")
        next(e for e in doc["private_events"] if e["kind"] == "observation_granted" and e["audience"]["ids"] == ["account1"] and e["payload"]["observation_id"] == "proof_common")["payload"]["source"]["actor_character"] = character_of(self.t, "account3")
        cases["forged provenance"] = doc
        for name, doc in cases.items():
            with self.subTest(name):
                self.assertIsNotNone(rejects(case, rules, doc))


class GhostTestimonyTests(unittest.TestCase):
    def setUp(self):
        self.case, self.rules, t = ghost_case()
        self.t = make_ghost(self.case, self.rules, t)
        self.ghost = character_of(self.t, "account0")

    def test_question_costs_an_action_and_answer_is_public(self):
        case, rules, t = self.case, self.rules, self.t
        form = next(e for e in menu(case, rules, t, "account1") if isinstance(e, MenuForm) and e.command_kind == "testimony_ask")
        self.assertEqual((form.subject_ids, form.cost), ((self.ghost,), 1))
        self.assertFalse(any(isinstance(e, MenuForm) and e.command_kind == "testimony_ask" for e in menu(case, rules, t, "account0")))
        ap = next(p["ap"] for p in t.state.players if p["account_id"] == "account1")
        asked = module_play(case, rules, t, "testimony_ask", {"ghost": self.ghost, "text": "Ты видел хозяина у озера?"}, "account1")
        self.assertTrue(asked.receipt["accepted"], asked.receipt)
        self.assertEqual(next(p["ap"] for p in asked.state.players if p["account_id"] == "account1"), ap - 1)
        question = asked.state.public["chronicle"][-1]
        self.assertEqual(question["kind"], "testimony_asked")
        self.assertEqual(question["payload"]["answer_by"], question["window_idx"] + 1)
        again = module_play(case, rules, asked, "testimony_ask", {"ghost": self.ghost, "text": "Ещё раз?"}, "account1")
        self.assertEqual(again.receipt["code"], "action_unavailable")
        offers = choices(menu(case, rules, asked, "account0"), "testimony_answer")
        self.assertEqual(sorted(c.label for c in offers), ["Ответить «да»", "Ответить «нет»"])
        answered = module_play(case, rules, asked, "testimony_answer", {"question_event_id": question["event_id"], "answer": "no"})
        self.assertTrue(answered.receipt["accepted"], answered.receipt)
        view = project(case, rules, answered.state, PlayerActor("account2"))
        row = view["modules"]["ghost_testimony"]["questions"][0]
        self.assertEqual((row["status"], row["answer"], row["text"], row["asker_character"]), ("answered", "no", "Ты видел хозяина у озера?", character_of(t, "account1")))
        self.assertEqual(roundtrip(case, rules, answered), answered.state.document())
        # The answer is not evidence: nothing reaches the board or anyone's knowledge.
        self.assertEqual(answered.state.public["board"], asked.state.public["board"])
        self.assertEqual(module_play(case, rules, answered, "testimony_answer", {"question_event_id": question["event_id"], "answer": "yes"}).receipt["code"], "action_unavailable")
        # Tampering: a second answer or an unknown question is rejected by the codec.
        doc = answered.state.document()
        doc["public"]["chronicle"][-1]["payload"]["question_event_id"] = "unknown-question"
        self.assertIsNotNone(rejects(case, rules, doc))

    def test_question_expires_after_the_next_window(self):
        case, rules, t = self.case, self.rules, self.t
        t = module_play(case, rules, t, "testimony_ask", {"ghost": self.ghost, "text": "Ключ был у тебя?"}, "account1")
        question = t.state.public["chronicle"][-1]
        for n in range(2):
            for p in list(t.state.players): t = module_play(case, rules, t, "seen", account=p["account_id"])
            t = tick(case, rules, t.state, command_id="expire00" + str(n))
        view = project(case, rules, t.state, PlayerActor("account1"))
        self.assertEqual(view["modules"]["ghost_testimony"]["questions"][0]["status"], "expired")
        late = module_play(case, rules, t, "testimony_answer", {"question_event_id": question["event_id"], "answer": "yes"})
        self.assertEqual(late.receipt["code"], "action_unavailable")
        # An expired question frees the pair for a new one.
        self.assertTrue(module_play(case, rules, t, "testimony_ask", {"ghost": self.ghost, "text": "А теперь?"}, "account1").receipt["accepted"])

    def test_living_cannot_be_asked_and_text_is_bounded(self):
        case, rules, t = self.case, self.rules, self.t
        self.assertEqual(module_play(case, rules, t, "testimony_ask", {"ghost": character_of(t, "account2"), "text": "Да?"}, "account1").receipt["code"], "action_unavailable")
        with self.assertRaises(ValueError):
            quote_action(case, rules, t.state, PlayerActor("account1"), CommandIntent("testimony_ask", {"ghost": self.ghost, "text": "x" * 201}), now_utc=None)


class GhostVisionTests(unittest.TestCase):
    def test_sign_is_public_once_and_names_ghosts(self):
        case, rules, t = ghost_case()
        account = next(p["account_id"] for p in t.state.players if p["character_id"] == "person_00")
        accuser = next(p["account_id"] for p in t.state.players if p["account_id"] != account)
        t = make_ghost(case, rules, t, account, accuser)
        offered = choices(menu(case, rules, t, account), "ghost_sign")
        self.assertEqual([c.label for c in offered], [SIGN["label"]])
        shown = module_play(case, rules, t, "ghost_sign", {"sign_id": "sign_cold"}, account)
        self.assertTrue(shown.receipt["accepted"], shown.receipt)
        event = shown.state.public["chronicle"][-1]
        self.assertEqual(event["payload"], {"sign_id": "sign_cold", "character_id": "person_00", "location": "foyer", "body": SIGN["body"]})
        view = project(case, rules, shown.state, PlayerActor(accuser))
        self.assertEqual([s["sign_id"] for s in view["modules"]["ghost_visions"]["signs"]], ["sign_cold"])
        self.assertEqual(roundtrip(case, rules, shown), shown.state.document())
        for p in list(shown.state.players): shown = module_play(case, rules, shown, "seen", account=p["account_id"])
        later = tick(case, rules, shown.state, command_id="later001")
        self.assertEqual(choices(menu(case, rules, later, account), "ghost_sign"), [])
        self.assertEqual(removed_label(case.document()), "Призраки")
        doc = shown.state.document(); doc["public"]["chronicle"][-1]["payload"]["body"] = {"text": "Подменённый знак", "mentions": []}
        self.assertIsNotNone(rejects(case, rules, doc))


class DisabledModulesTests(unittest.TestCase):
    def test_without_modules_ghost_actions_stay_closed(self):
        case, rules, t = ghost_case(modules=())
        t = learn_key(case, rules, t)
        t = make_ghost(case, rules, t)
        self.assertEqual(module_play(case, rules, t, "ghost_whisper", {"observation_id": "proof_common", "recipient": character_of(t, "account1")}).receipt["code"], "action_unavailable")
        self.assertEqual(module_play(case, rules, t, "testimony_ask", {"ghost": character_of(t, "account0"), "text": "Да?"}, "account1").receipt["code"], "action_unavailable")
        self.assertEqual(module_play(case, rules, t, "ghost_sign", {"sign_id": "sign_cold"}).receipt["code"], "action_unavailable")
        self.assertFalse({"ghost_whisper", "testimony_answer", "ghost_sign"} & {e.quote.kind for e in menu(case, rules, t, "account0") if isinstance(e, MenuChoice)})
        self.assertNotIn("ghost_testimony", project(case, rules, t.state, PlayerActor("account1"))["modules"])
        self.assertEqual(removed_label(case.document()), "Отстранённые")
        # The old share still works: one free public memory per window.
        self.assertTrue(module_play(case, rules, t, "ghost_share", {"observation_id": "proof_common"}).receipt["accepted"])
        # A ghost source cannot appear in a case without the whisper module.
        doc = t.state.document()
        next(k for k in doc["knowledge"] if k["account_id"] == "account0" and k["observation_id"] == "proof_common")["source"]["kind"] = "ghost"
        self.assertIsNotNone(rejects(case, rules, doc))


if __name__ == "__main__":
    unittest.main()
