"""Trusted personal-task snapshot consistency, without engine or codec imports.

The journal records actor-qualified physical changes. This fold checks that the
retained data agrees; command replay remains the proof of actual reachability.
"""

from __future__ import annotations

import re
from collections import Counter


def _require(condition, message):
    if not condition:
        raise ValueError("personal story: " + message)


def _obj(value, fields, label):
    _require(type(value) is dict and set(value) == set(fields), label + " fields")
    return value


def _array(value, low, high, label):
    _require(type(value) is list and low <= len(value) <= high, label + " array")
    return value


def _integer(value, low, high, label):
    _require(type(value) is int and low <= value <= high, label + " exact integer")


def _string(value, low, high, label):
    _require(type(value) is str and low <= len(value) <= high, label + " string")


def _content_id(value):
    _string(value, 2, 32, "ID")
    _require(re.fullmatch(r"[a-z][a-z0-9_]{1,31}", value, re.ASCII) is not None, "content ID")


ENTRY_FIELDS = {
    "step_done": {"kind", "step_id", "account_id"},
    "return_offered": {"kind", "step_id", "account_id", "offer_event_id", "recipient_account_id"},
    "return_answered": {"kind", "offer_event_id", "decision"},
    "public_reveal": {"kind", "topic_id", "publisher_account_id", "event_id"},
    "actor_closed": {"kind", "account_id"},
    "departed_epilogue": {"kind", "trip_id", "account_id"},
}


def _validate_goals(case, tasks, steps, trips, originals, topics):
    for character in case["characters"]:
        goal = character.get("goal")
        if goal is None:
            continue
        personal = False
        for pred in goal["when"]:
            kind = pred["kind"]
            if not kind.startswith("story_"):
                continue
            personal = True
            fields = {
                "story_done": {"kind", "step"}, "story_any_done": {"kind", "steps"},
                "story_before": {"kind", "step", "boundary"}, "story_unexposed": {"kind", "topic", "by"},
                "story_departed": {"kind", "trip"},
            }
            _require(kind in fields, "unknown personal goal predicate")
            _obj(pred, fields[kind], "goal predicate")
            if kind in {"story_done", "story_before", "story_any_done"}:
                refs = pred["steps"] if kind == "story_any_done" else [pred["step"]]
                _array(refs, 1, 4, "goal steps")
                _require(all(type(s) is str and s in steps for s in refs) and len(refs) == len(set(refs)), "goal step reference")
                _require(all(character["id"] in steps[s]["actors"] for s in refs), "goal actor scope")
            if kind == "story_before":
                boundary = pred["boundary"]
                _require(type(boundary) is dict, "boundary object")
                if boundary.get("kind") == "public_reveal":
                    _obj(boundary, {"kind", "topic", "by"}, "public boundary")
                    _require(boundary["topic"] in topics and boundary["by"] in {"self", "any"}, "public boundary reference")
                else:
                    _obj(boundary, {"kind", "original"}, "inspection boundary")
                    _require(boundary["kind"] == "foreign_inspection" and boundary["original"] in originals, "inspection boundary reference")
            elif kind == "story_unexposed":
                _require(pred["topic"] in topics and pred["by"] in {"self", "any"}, "unexposed reference")
            elif kind == "story_departed":
                _require(pred["trip"] in trips and trips[pred["trip"]]["traveler"] == character["id"], "trip goal scope")
        _require(not personal or "criteria" in goal, "personal goal criteria missing")


def validate_personal_state(case_doc, state_doc) -> None:
    """Validate a sealed snapshot using a compiled case, without mutating either."""
    tasks = case_doc.get("personal_tasks")
    if tasks is None:
        _require("personal_story" not in state_doc, "disabled capability fields")
        return
    _require(case_doc["ruleset_ref"] == {"id": "night_case.core", "version": 2}, "capability profile")
    _integer(tasks["version"], 1, 1, "capability version")
    story = _obj(state_doc.get("personal_story"), {"version", "journal"}, "story")
    _integer(story["version"], 1, 1, "story version")
    journal = _array(story["journal"], 0, 2048, "journal")
    steps = {s["id"]: s for s in tasks["steps"]}
    originals = {o["id"]: o for o in tasks["originals"]}
    caches = {c["id"]: c for c in tasks["caches"]}
    works = {w["id"]: w for w in tasks["works"]}
    commitments = {c["id"]: c for c in tasks["commitments"]}
    trips = {t["id"]: t for t in tasks["trips"]}
    topics = {t["id"]: t for t in tasks["topics"]}
    _validate_goals(case_doc, tasks, steps, trips, originals, topics)
    actions = {a["id"]: a for a in case_doc["actions"]}
    players = {p["account_id"]: p for p in state_doc["players"]}
    account_for_character = {p["character_id"]: a for a, p in players.items()}
    observation_by_id = {o["id"]: o for o in case_doc["observations"]}
    public_events = state_doc["public"]["chronicle"]
    private_events = state_doc["private_events"]
    event_by_id = {e["event_id"]: e for e in public_events + private_events}
    receipts = {(r["actor_key"], r["command_id"]): r for r in state_doc["receipts"]}
    variant = state_doc["sealed"]["variant_id"]
    done, closed, offers, answered, revealed, epilogues = {}, {}, {}, {}, {}, {}
    custody = {o["id"]: ("at_source", None) if o["initial_holder"] is None else ("held", o["initial_holder"]) for o in originals.values()}
    inspected, choices, recovered, issued, booked = set(), set(), set(), set(), set()
    progress = {}
    causes, completion_results, offered_results, expected_grants = set(), set(), set(), set()
    expected_public_cards = Counter()
    public_deliveries = []
    previous_window = 0

    def response(step):
        return next(r for r in step["responses"] if r["variants"] == "all" or variant in r["variants"])

    def own_events(kind, account, window):
        return [e for e in private_events if e["kind"] == kind and e["audience"]["ids"] == [account] and e["window_idx"] == window]

    def receipt_for_result(event, account):
        return any(r["accepted"] and r["actor_key"] == "account:" + account and r["result_ref"] == {"kind": "event", "event_id": event["event_id"]} for r in state_doc["receipts"])

    def eligible_step(account, step_id, completed_before):
        _require(account in players and step_id in steps, "step/account reference")
        step = steps[step_id]
        _require(players[account]["character_id"] in step["actors"] and account not in closed, "step actor ownership or cutoff")
        _require(not inactive_before(account, window), "inactive personal actor")
        _require((account, step_id) not in done, "duplicate completed step")
        _require(all((account, ref) in completed_before for ref in step["requires"]), "prior own prerequisites")
        _require(step["choice_group"] is None or (account, step["choice_group"]) not in choices, "exclusive own choice")
        action = actions.get(step["action"])
        _require(action is not None and action.get("personal_step") == step_id, "personal action binding")
        return step

    def grant(account, observation, step, sender, window, location=None):
        expected_grants.add((account, observation, step["action"], players[sender]["character_id"], location or actions[step["action"]]["location"], window))

    def inactive_before(account, window):
        return account in closed or any(e["kind"] == "status" and e["window_idx"] < window and e["payload"]["character_id"] == players[account]["character_id"] and (e["payload"]["controller"] == "npc" or e["payload"]["status"] == "ghost") for e in public_events)

    def original_npc(character, window):
        npc = next((n for n in state_doc["npcs"] if n["character_id"] == character), None)
        _require(character not in account_for_character and npc is not None and npc["origin"] == "authored", "requires original NPC")
        _require(not any(e["kind"] == "status" and e["window_idx"] < window and e["payload"]["character_id"] == character and e["payload"]["status"] == "removed" for e in public_events), "removed original NPC")

    def visible_npc(character, window):
        original_npc(character, window)
        concealed = case_doc.get("module_data", {}).get("turning_point", {}).get("concealed_npcs", [])
        if any(n["character"] == character for n in concealed):
            _require(any(e["kind"] == "npc_revealed" and e["window_idx"] <= window and e["payload"]["character_id"] == character for e in public_events), "concealed issuer or recipient never discovered")

    for seq, batch in enumerate(journal, 1):
        _obj(batch, {"seq", "window_idx", "cause", "entries"}, "batch")
        _integer(batch["seq"], 1, 2048, "batch seq")
        _require(batch["seq"] == seq, "journal sequence gap or reordering")
        window = batch["window_idx"]
        _integer(window, 1, 14, "batch window")
        _require(previous_window <= window <= state_doc["clock"]["window_idx"], "backdated or future batch")
        previous_window = window
        cause = batch["cause"]
        transition_windows = {window}
        _require(type(cause) is dict, "cause object")
        if cause.get("kind") == "command":
            _obj(cause, {"kind", "account_id", "command_id"}, "command cause")
            _string(cause["account_id"], 1, 120, "cause account")
            _require(cause["account_id"] in players, "cause account")
            _string(cause["command_id"], 8, 64, "command ID")
            receipt = receipts.get(("account:" + cause["account_id"], cause["command_id"]))
            _require(receipt is not None and receipt["accepted"], "cause lacks accepted own receipt")
            cause_key = ("command", cause["account_id"], cause["command_id"])
        else:
            _obj(cause, {"kind", "transition_key"}, "system cause")
            _require(cause["kind"] == "system", "cause kind")
            _content_id(cause["transition_key"])
            transition = cause["transition_key"]
            if transition == "start_1":
                _require(seq == 1 and window == 1, "initial system batch")
            elif transition.startswith("close_"):
                _require(transition in {"close_" + str(window), "close_" + str(window - 1)} and transition != "close_0", "system close cursor")
                old_window = int(transition.removeprefix("close_"))
                transition_windows = {old_window, old_window + 1} & set(range(1, state_doc["clock"]["window_idx"] + 1))
            else:
                _require(transition == "forget_" + str(window) and state_doc["final"] is not None and state_doc["final"]["code"] == "forgotten", "system terminal cause")
            cause_key = ("system", cause["transition_key"])
        _require(cause_key not in causes, "duplicate transition batch")
        causes.add(cause_key)
        entries = _array(batch["entries"], 1, 128, "batch entries")
        for entry in entries:
            _require(type(entry) is dict and type(entry.get("kind")) is str and entry["kind"] in ENTRY_FIELDS, "entry kind")
            _obj(entry, ENTRY_FIELDS[entry["kind"]], "entry")
            for field in ("account_id", "recipient_account_id", "publisher_account_id"):
                if field in entry and entry[field] is not None:
                    _string(entry[field], 1, 120, field)
                    _require(entry[field] in players, "entry account reference")
            for field in ("step_id", "topic_id", "trip_id"):
                if field in entry:
                    _content_id(entry[field])
            for field in ("offer_event_id", "event_id"):
                if field in entry:
                    _string(entry[field], 1, 128, field)
            if "decision" in entry:
                _require(type(entry["decision"]) is str and entry["decision"] in {"accepted", "declined", "cancelled"}, "answer decision")
        completed_before = set(done)

        for entry in (e for e in entries if e["kind"] == "return_offered"):
            account, step_id, offer_id, recipient = entry["account_id"], entry["step_id"], entry["offer_event_id"], entry["recipient_account_id"]
            step = eligible_step(account, step_id, completed_before)
            op = step["operation"]
            _require(op["kind"] == "offer_return" and cause.get("account_id") == account, "offer cause/operation")
            original = originals[op["original"]]
            _require(custody[original["id"]] == ("held", players[account]["character_id"]), "offered original not held by sender")
            expected_recipient = account_for_character.get(original["return_to"])
            _require(recipient == expected_recipient and (recipient is None or not inactive_before(recipient, window)), "offer recipient ownership or inactive")
            _require(not inactive_before(account, window), "inactive sender offered return")
            if recipient is None:
                visible_npc(original["return_to"], window)
            _require(offer_id not in offers and not any(v["account"] == account and v["step"] == step_id for v in offers.values()), "duplicate offer")
            event = event_by_id.get(offer_id)
            _require(event is not None and event["kind"] == "story_offer" and event["window_idx"] == window and event["audience"]["ids"] == [recipient or account], "offer event ACL/window")
            _require(event["payload"] == {"step_id": step_id, "from_character": players[account]["character_id"], "original_id": original["id"], "return_location": original["return_location"], "body": original["offer_body"]}, "offer authored payload")
            offers[offer_id] = {"account": account, "step": step_id, "recipient": recipient, "seq": seq, "window": window}
            custody[original["id"]] = ("offered", None)
            offered_results.add((account, step_id, window))

        for entry in (e for e in entries if e["kind"] == "return_answered"):
            offer_id, decision = entry["offer_event_id"], entry["decision"]
            _require(offer_id in offers and offer_id not in answered and decision in {"accepted", "declined", "cancelled"}, "answer reference/duplicate/decision")
            offer = offers[offer_id]
            account, recipient, step_id = offer["account"], offer["recipient"], offer["step"]
            if decision in {"accepted", "declined"}:
                _require(not inactive_before(account, window) and (recipient is None or not inactive_before(recipient, window)), "inactive return participant")
                _require(cause.get("account_id") == (recipient or account), "answer actor ACL")
            original = originals[steps[step_id]["operation"]["original"]]
            custody[original["id"]] = ({"accepted": "delivered", "declined": "declined", "cancelled": "cancelled"}[decision], None)
            expected_accounts = {account} | ({recipient} if recipient is not None else set())
            actual = [e for e in private_events if e["kind"] == "story_return_closed" and e["payload"]["offer_event_id"] == offer_id]
            _require(len(actual) == len(expected_accounts) and {e["audience"]["ids"][0] for e in actual} == expected_accounts and len({e["window_idx"] for e in actual}) == 1 and all(e["window_idx"] in transition_windows and e["payload"]["decision"] == decision for e in actual), "return closing events ACL/content")
            answer_window = actual[0]["window_idx"]
            answered[offer_id] = (decision, seq, answer_window)
            paired_done = any(e["kind"] == "step_done" and e["account_id"] == account and e["step_id"] == step_id for e in entries)
            _require(paired_done == (decision == "accepted"), "accepted return must atomically complete sender step")
            if decision == "accepted" and recipient is not None:
                for section in original["sections"]:
                    grant(recipient, section["observation"], steps[step_id], account, answer_window, original["return_location"])

        for entry in (e for e in entries if e["kind"] == "step_done"):
            account, step_id = entry["account_id"], entry["step_id"]
            step = eligible_step(account, step_id, completed_before)
            op, character = step["operation"], players[account]["character_id"]
            kind = op["kind"]
            accepted_return = kind == "offer_return" and any(o["account"] == account and o["step"] == step_id and key in answered and answered[key][:2] == ("accepted", seq) for key, o in offers.items())
            _require(accepted_return or cause.get("account_id") == account, "completed step cause actor")
            if kind in {"inspect_original", "take_original", "destroy_original"}:
                original = originals[op["original"]]
                status, holder = custody[original["id"]]
                if kind == "inspect_original":
                    _require(status == "at_source" or (status, holder) == ("held", character), "original unavailable for inspection")
                    key = (account, original["id"], op["section"])
                    _require(key not in inspected, "repeated section inspection")
                    inspected.add(key)
                    section = next(s for s in original["sections"] if s["id"] == op["section"])
                    grant(account, section["observation"], step, account, window)
                elif kind == "take_original":
                    _require(status == "at_source", "original not at source")
                    custody[original["id"]] = ("held", character)
                else:
                    _require((status, holder) == ("held", character) and actions[step["action"]]["location"] in original["destroy_locations"], "destroy custody/location")
                    custody[original["id"]] = ("destroyed", None)
            elif kind == "offer_return":
                _require(accepted_return, "return completed without acceptance")
            elif kind == "recover_cache":
                cache = caches[op["cache"]]
                _require(cache["owner"] == character and cache["id"] not in recovered, "cache ownership/repeat")
                initially_thawed = next(f["initial"] for f in case_doc["flags"] if f["id"] == cache["thaw_flag"])
                _require(initially_thawed or any(e["kind"] == "world_changed" and e["window_idx"] <= window and {"id": cache["thaw_flag"], "value": True} in e["payload"]["flags"] for e in public_events), "cache never thawed before recovery")
                recovered.add(cache["id"])
            elif kind == "advance_work":
                work = works[op["work"]]
                stages = progress.setdefault((account, work["id"]), [])
                _require(work["owner"] == character and len(stages) < len(work["stages"]) and op["stage"] == work["stages"][len(stages)], "work owner/stage order")
                stages.append(op["stage"])
            elif kind == "issue_commitment":
                commitment = commitments[op["commitment"]]
                _require(commitment["beneficiary"] == character and commitment["issuer"] not in account_for_character and (account, commitment["id"]) not in issued, "commitment owner/issuer/repeat")
                visible_npc(commitment["issuer"], window)
                _require(response(step)["body"] == commitment["document"], "commitment authored signed document")
                issued.add((account, commitment["id"]))
            elif kind == "book_departure":
                trip = trips[op["trip"]]
                _require(trip["traveler"] == character and progress.get((account, trip["work"]), []) == works[trip["work"]]["stages"] and (account, trip["id"]) not in booked, "departure requires own completed work")
                booked.add((account, trip["id"]))
            elif kind == "deliver_card":
                recipient = op["recipient"]
                if recipient is None:
                    expected_public_cards[(window, op["observation"])] += 1
                    public_deliveries.append((seq, account, window, op["observation"]))
                elif recipient in account_for_character:
                    recipient_account = account_for_character[recipient]
                    _require(not inactive_before(recipient_account, window), "card recipient inactive")
                    grant(recipient_account, op["observation"], step, account, window)
                else:
                    original_npc(recipient, window)
            else:
                _require(kind == "record_deed", "unknown operation")
            done[(account, step_id)] = (seq, window)
            if step["choice_group"] is not None:
                choices.add((account, step["choice_group"]))
            for observation in response(step)["observations"]:
                grant(account, observation, step, account, window)
            completion_results.add((account, step_id, window))
            if not accepted_return:
                result_events = [e for e in own_events("story_result", account, window) if e["payload"]["step_id"] == step_id and e["payload"]["disposition"] == "completed"]
                _require(len(result_events) == 1 and receipt["result_ref"] == {"kind": "event", "event_id": result_events[0]["event_id"]}, "completion own receipt result")

        for entry in (e for e in entries if e["kind"] == "public_reveal"):
            topic, publisher, event_id = entry["topic_id"], entry["publisher_account_id"], entry["event_id"]
            _require(topic in topics and (publisher is None or publisher in players) and (topic, publisher) not in revealed, "reveal ref/duplicate")
            _require(publisher == cause.get("account_id"), "sealed publisher differs from cause")
            event = event_by_id.get(event_id)
            _require(event is not None and event["audience"] == {"kind": "public"} and event["window_idx"] in transition_windows, "reveal witness ACL/window")
            if event["kind"] == "board":
                board = next(b for b in state_doc["public"]["board"] if b["id"] == event["payload"]["board_id"])
                observation = board["observation_id"]
                _require(publisher == board["owner_account_id"], "board publisher")
            else:
                _require(event["kind"] in {"observation_granted", "authored_card_delivered"}, "non-publication reveal witness")
                observation = event["payload"]["observation_id"]
            _require(observation in topics[topic]["observations"], "reveal topic witness")
            revealed[(topic, publisher)] = (seq, event_id)

        for entry in (e for e in entries if e["kind"] == "actor_closed"):
            account = entry["account_id"]
            _require(account in players and account not in closed and players[account]["status"] == "departed", "actor cutoff/status/duplicate")
            _require(cause["kind"] == "system" or cause["account_id"] == account, "actor cutoff command owner")
            closed[account] = seq
        for entry in (e for e in entries if e["kind"] == "departed_epilogue"):
            account, trip_id = entry["account_id"], entry["trip_id"]
            _require(account in players and trip_id in trips and account not in closed and (account, trip_id) in booked and (account, trip_id) not in epilogues, "epilogue ownership/booked/cutoff")
            _require(state_doc["final"] is not None and state_doc["final"]["code"] != "forgotten" and seq == len(journal), "epilogue requires terminal except forgotten")
            epilogues[(account, trip_id)] = (seq, window)

    _require(set(closed) == {a for a, p in players.items() if p["status"] == "departed"}, "departed actor lacks journal cutoff")
    expected_epilogues = {key for key in booked if key[0] not in closed} if state_doc["final"] is not None and state_doc["final"]["code"] != "forgotten" else set()
    _require(set(epilogues) == expected_epilogues, "terminal booked travelers lack deterministic epilogue")
    for offer_id, offer in offers.items():
        if offer_id not in answered:
            _require(state_doc["final"] is None and offer["account"] not in closed and offer["recipient"] not in closed and players[offer["account"]]["status"] != "ghost" and (offer["recipient"] is None or players[offer["recipient"]]["status"] != "ghost"), "offer left pending after cancellation boundary")
    for offer_id, offer in offers.items():
        if offer["recipient"] is None:
            _require(offer_id in answered and answered[offer_id][:2] == ("accepted", offer["seq"]), "original NPC return not immediately accepted")

    actual_results, actual_offered, actual_epilogues = Counter(), Counter(), Counter()
    for event in private_events:
        payload, kind = event["payload"], event["kind"]
        account, window = event["audience"]["ids"][0], event["window_idx"]
        if kind == "story_result":
            step_id = payload["step_id"]
            _require(step_id in steps and players[account]["character_id"] in steps[step_id]["actors"], "story result ownership")
            step, disposition = steps[step_id], payload["disposition"]
            expected = set(response(step)["observations"])
            if step["operation"]["kind"] == "inspect_original":
                expected.add(next(s["observation"] for s in originals[step["operation"]["original"]]["sections"] if s["id"] == step["operation"]["section"]))
            if disposition == "completed":
                _require((account, step_id, window) in completion_results and payload["body"] == response(step)["body"] and set(payload["observation_ids"]) == expected, "unbacked or unauthored completed result")
                actual_results[(account, step_id, window)] += 1
            elif disposition == "offered":
                _require((account, step_id, window) in offered_results and payload["body"] == originals[step["operation"]["original"]]["offer_body"] and not payload["observation_ids"], "unbacked offered result")
                actual_offered[(account, step_id, window)] += 1
            else:
                _require(payload["body"] == actions[step["action"]]["fallback"] and not payload["observation_ids"] and receipt_for_result(event, account), "failure must be own paid neutral fallback")
        elif kind == "story_offer":
            _require(event["event_id"] in offers, "offer event lacks journal offer")
        elif kind == "story_return_closed":
            _require(payload["offer_event_id"] in answered, "closing event lacks answer")
            if state_doc["clock"]["phase"] == "frozen" and window == state_doc["clock"]["window_idx"]:
                offer = offers[payload["offer_event_id"]]
                answer = answered[payload["offer_event_id"]]
                batch = journal[answer[1] - 1]
                cause = batch["cause"]
                _require(payload["decision"] == "cancelled" and cause["kind"] == "command" and cause["account_id"] in {offer["account"], offer["recipient"]} and any(e["kind"] == "actor_closed" and e["account_id"] == cause["account_id"] for e in batch["entries"]), "frozen return cancellation lacks same-command participant cutoff")
        elif kind == "story_epilogue":
            key = (account, payload["trip_id"])
            _require(key in epilogues and epilogues[key][1] == window and payload["body"] == trips[payload["trip_id"]]["epilogue"], "unbacked epilogue result")
            actual_epilogues[key] += 1
    _require(set(actual_results) == completion_results and all(n == 1 for n in actual_results.values()), "completion result cardinality")
    required_offered = {(o["account"], o["step"], o["window"]) for o in offers.values() if o["recipient"] is not None}
    _require(required_offered <= set(actual_offered) and all(n == 1 for n in actual_offered.values()), "PC sender offered result missing or duplicate")
    _require(set(actual_epilogues) == set(epilogues) and all(n == 1 for n in actual_epilogues.values()), "epilogue result cardinality")
    actual_cards = Counter()
    for event in public_events:
        if event["kind"] == "authored_card_delivered":
            observation = event["payload"]["observation_id"]
            _require(observation in observation_by_id and event["payload"]["body"] == observation_by_id[observation]["body"], "public card authored content")
            actual_cards[(event["window_idx"], observation)] += 1
            _require(any(o["observation_id"] == observation for o in state_doc["public"]["observations"]), "public card observation not retained")
    _require(actual_cards == expected_public_cards, "public card witnesses differ from completed deliveries")

    def require_reveal(topic, publisher, witness, no_later_than=None):
        reveal = revealed.get((topic, publisher))
        _require(reveal is not None and event_by_id[reveal[1]]["audience_seq"] <= witness["audience_seq"] and (no_later_than is None or reveal[0] <= no_later_than), "publication lacks first sealed publisher/topic hook")

    # The sealed command order and the public stream agree on deliveries of the
    # same card in a window. Pair those witnesses locally, without publishing IDs
    # or journal counters in either direction.
    used_cards = Counter()
    public_witnesses = [(seq, event_by_id[event_id]) for seq, event_id in revealed.values()]
    for seq, publisher, window, observation in public_deliveries:
        candidates = [e for e in public_events if e["kind"] == "authored_card_delivered" and e["window_idx"] == window and e["payload"]["observation_id"] == observation]
        witness = candidates[used_cards[(window, observation)]]
        used_cards[(window, observation)] += 1
        public_witnesses.append((seq, witness))
        for topic in topics.values():
            if observation in topic["observations"]:
                require_reveal(topic["id"], publisher, witness, seq)
    witness_batch, public_ranges = {}, {}
    for seq, witness in public_witnesses:
        event_id = witness["event_id"]
        _require(event_id not in witness_batch or witness_batch[event_id] == seq, "public witness chronology assigns one event to different batches")
        witness_batch[event_id] = seq
        public_ranges.setdefault(seq, set()).add(witness["audience_seq"])
    previous_public_seq = 0
    for seq in sorted(public_ranges):
        positions = public_ranges[seq]
        _require(min(positions) > previous_public_seq, "public witness chronology differs from sealed batch order")
        previous_public_seq = max(positions)
    for event in public_events:
        if event["kind"] == "board":
            board = next(b for b in state_doc["public"]["board"] if b["id"] == event["payload"]["board_id"])
            for topic in topics.values():
                if board["observation_id"] in topic["observations"]:
                    require_reveal(topic["id"], board["owner_account_id"], event)
        elif event["kind"] == "observation_granted":
            for topic in topics.values():
                if event["payload"]["observation_id"] in topic["observations"]:
                    _require(any(t == topic["id"] and event_by_id[r[1]]["audience_seq"] <= event["audience_seq"] for (t, _), r in revealed.items()), "public grant lacks topic disclosure hook")
    for row in state_doc["public"]["observations"]:
        candidates = [e for e in public_events if e["kind"] in {"observation_granted", "authored_card_delivered"} and e["payload"]["observation_id"] == row["observation_id"]]
        _require(candidates and row["source"]["source_id"] == candidates[0]["event_id"], "public observation lost first provenance")
    personal_actions = {s["action"] for s in steps.values()}
    for account, observation, *_ in expected_grants:
        _require(any(k["account_id"] == account and k["observation_id"] == observation for k in state_doc["knowledge"]), "personal delivered knowledge not retained")
    sources = [(k["account_id"], k["observation_id"], k["source"]) for k in state_doc["knowledge"]]
    sources += [(e["audience"]["ids"][0], e["payload"]["observation_id"], e["payload"]["source"]) for e in private_events if e["kind"] == "observation_granted"]
    for account, observation, source in sources:
        if source["source_id"] in personal_actions:
            signature = (account, observation, source["source_id"], source["actor_character"], source["location"], source["window_idx"])
            _require(source["kind"] == "action" and signature in expected_grants, "personal grant provenance/recipient")
    for event in private_events:
        if event["kind"] == "observation_granted" and event["payload"]["source"]["source_id"] in personal_actions:
            _require(any(k["account_id"] == event["audience"]["ids"][0] and k["observation_id"] == event["payload"]["observation_id"] and k["source"] == event["payload"]["source"] for k in state_doc["knowledge"]), "personal grant lost retained provenance")
