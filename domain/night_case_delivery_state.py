"""Pure communication and authored NPC delivery validation and stable IDs."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import unicodedata
from collections import Counter


def _need(condition, label):
    if not condition:
        raise ValueError("delivery: " + label)


def _obj(value, fields, label):
    _need(type(value) is dict and set(value) == set(fields), label + " fields")


def _int(value, low, high, label):
    _need(type(value) is int and low <= value <= high, label + " exact integer")


def _id(value):
    _need(type(value) is str and re.fullmatch(r"[a-z][a-z0-9_]{1,31}", value, re.ASCII) is not None, "content ID")


def _hash(value):
    _need(type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value, re.ASCII) is not None, "SHA256")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def normalize_say_text(text):
    _need(type(text) is str, "message text")
    text = unicodedata.normalize("NFC", text)
    _need(1 <= len(text) <= 1000 and bool(text.strip()), "message text bounds/whitespace")
    _need(not any(unicodedata.category(c) == "Cc" and c != "\n" for c in text), "message control character")
    try:
        _need(len(text.encode("utf-8")) <= 4096, "message UTF8 bounds")
    except UnicodeEncodeError as exc:
        raise ValueError("delivery: invalid message Unicode") from exc
    return text


def normalize_say_params(params):
    _obj(params, {"channel", "recipients", "text"}, "say params")
    _need(type(params["channel"]) is str and params["channel"] in {"square", "whisper", "ghost"}, "channel")
    recipients = params["recipients"]
    _need(type(recipients) is list and len(recipients) <= 2, "say recipients")
    for recipient in recipients:
        _id(recipient)
    _need(len(set(recipients)) == len(recipients), "duplicate recipient")
    _need((1 <= len(recipients) <= 2) if params["channel"] == "whisper" else not recipients, "channel recipients")
    return {"channel": params["channel"], "recipients": sorted(recipients), "text": normalize_say_text(params["text"])}


def message_id_for(game_id, account_id, command_id):
    return "msg_" + hashlib.sha256(_canonical(["night-case-message/1", game_id, account_id, command_id])).hexdigest()


def thread_key_for(game_id, channel, recipient_account_ids):
    return hashlib.sha256(_canonical(["night-case-thread/1", game_id, channel, sorted(recipient_account_ids)])).hexdigest()


def text_hash_for(text):
    return hashlib.sha256(normalize_say_text(text).encode("utf-8")).hexdigest()


def delivery_draw(seed, npc, topic, window, version, *, domain, upper):
    """Unbiased HMAC draw in a separate seed domain; no shared sequence."""
    _int(seed, 0, 2**63 - 1, "seed")
    _id(npc)
    _id(topic)
    _int(window, 1, 14, "window")
    _int(version, 1, 1, "rule version")
    _int(upper, 1, 10000, "draw upper")
    _need(domain in {"night-case-line/1", "night-case-slip/1"}, "seed domain")
    base = [domain, npc, topic, window, version]
    limit = 2**64 - 2**64 % upper
    counter = 0
    while True:
        data = base if counter == 0 else base + [counter]
        draw = int.from_bytes(hmac.new(str(seed).encode("ascii"), _canonical(data), hashlib.sha256).digest()[:8], "big")
        if draw < limit:
            return draw % upper
        counter += 1


def validate_message_record(record, game_id, command_id):
    _obj(record, {"id", "channel", "thread_key", "sender_account_id", "recipient_account_ids", "window_idx", "text", "text_hash"}, "message record")
    _need(type(command_id) is str and 8 <= len(command_id) <= 64, "message command ID")
    _need(type(record["sender_account_id"]) is str and 1 <= len(record["sender_account_id"]) <= 120, "message sender")
    recipients = record["recipient_account_ids"]
    _need(type(recipients) is list and 1 <= len(recipients) <= 12 and all(type(a) is str and 1 <= len(a) <= 120 for a in recipients), "message recipients")
    _need(recipients == sorted(set(recipients)) and record["sender_account_id"] in recipients, "message frozen audience")
    _need(type(record["channel"]) is str and record["channel"] in {"square", "whisper", "ghost"} and (record["channel"] != "whisper" or 2 <= len(recipients) <= 3), "message channel")
    _int(record["window_idx"], 1, 14, "message window")
    _need(record["text"] == normalize_say_text(record["text"]), "message must already be NFC")
    _need(record["text_hash"] == text_hash_for(record["text"]) and record["id"] == message_id_for(game_id, record["sender_account_id"], command_id) and record["thread_key"] == thread_key_for(game_id, record["channel"], recipients), "message hash/ID/thread binding")


MESSAGE_REF_FIELDS = {"kind", "message_id", "text_hash", "channel", "thread_key", "recipient_account_ids", "window_idx"}


def validate_message_ref(ref, receipt, game_id, accounts, current_window):
    _obj(ref, MESSAGE_REF_FIELDS, "message ref")
    _need(ref["kind"] == "message", "message ref kind")
    _need(receipt["accepted"] is True and receipt["actor_key"].startswith("account:"), "message receipt owner/acceptance")
    sender = receipt["actor_key"][8:]
    _need(sender in accounts, "unknown message sender")
    audience = ref["recipient_account_ids"]
    _need(type(audience) is list and 1 <= len(audience) <= 12 and all(type(a) is str and a in accounts for a in audience), "message audience roster")
    _need(audience == sorted(set(audience)) and sender in audience, "message frozen audience order/uniqueness/sender")
    _need(type(ref["channel"]) is str and ref["channel"] in {"square", "whisper", "ghost"}, "message channel")
    _need(ref["channel"] != "square" or set(audience) == accounts, "square frozen roster")
    _need(ref["channel"] != "whisper" or 2 <= len(audience) <= 3, "whisper audience cardinality")
    _hash(ref["text_hash"])
    _hash(ref["thread_key"])
    _int(ref["window_idx"], 1, current_window, "message window")
    _need(ref["message_id"] == message_id_for(game_id, sender, receipt["command_id"]), "message ID")
    _need(ref["thread_key"] == thread_key_for(game_id, ref["channel"], audience), "message thread")


def composed_body(line, body):
    return {"text": line["text"] + "\n" + body["text"], "mentions": list(dict.fromkeys(line["mentions"] + body["mentions"]))}


def validate_delivery_state(case_doc, state_doc):
    """Check retained delivery data, never historical AP or hidden guard timing."""
    communication = case_doc.get("communication")
    if communication is not None or "npc_delivery" in case_doc:
        _need(case_doc["ruleset_ref"] == {"id": "night_case.core", "version": 2}, "delivery capabilities require profile2")
    accounts = {p["account_id"] for p in state_doc["players"]}
    window = state_doc["clock"]["window_idx"]
    message_counts = Counter()
    for receipt in state_doc["receipts"]:
        ref = receipt["result_ref"]
        if ref is not None and ref.get("kind") == "message":
            _need(communication is not None, "message capability disabled")
            validate_message_ref(ref, receipt, state_doc["game_id"], accounts, window - int(state_doc["clock"]["opening_pending"]))
            message_counts[(receipt["actor_key"][8:], ref["window_idx"])] += 1
    if communication is not None:
        _integer_capability(communication)
        runtime = state_doc.get("communication")
        _obj(runtime, {"version", "sent"}, "communication state")
        _int(runtime["version"], 1, 1, "communication version")
        _need(type(runtime["sent"]) is list and len(runtime["sent"]) <= 168, "communication counts bounds")
        actual = {}
        for row in runtime["sent"]:
            _obj(row, {"account_id", "window_idx", "count"}, "sent row")
            _need(type(row["account_id"]) is str and row["account_id"] in accounts, "sent actor")
            _int(row["window_idx"], 1, window, "sent window")
            _int(row["count"], 1, 20, "sent count")
            key = (row["account_id"], row["window_idx"])
            _need(key not in actual, "duplicate sent counter")
            actual[key] = row["count"]
        _need(actual == dict(message_counts), "sent counts differ from successful message receipts")
    else:
        _need("communication" not in state_doc, "disabled communication state")
    if "npc_delivery" in case_doc:
        _validate_npc(case_doc, state_doc)
    else:
        _need("npc_delivery" not in state_doc, "disabled NPC delivery state")


def _integer_capability(communication):
    _obj(communication, {"version", "max_messages_per_window"}, "communication capability")
    _int(communication["version"], 1, 1, "communication version")
    _int(communication["max_messages_per_window"], 20, 20, "communication quota")


def _validate_npc(case, state):
    from domain.night_case_narrative import slip_decision_from_json

    capability = case["npc_delivery"]
    _int(capability["version"], 1, 1, "NPC capability version")
    _int(capability["window_reveal_budget"], 0, 3, "NPC window budget")
    _int(capability["game_reveal_budget"], 0, 12, "NPC game budget")
    runtime = state.get("npc_delivery")
    _obj(runtime, {"version", "decisions", "lines"}, "NPC delivery state")
    _int(runtime["version"], 1, 1, "NPC state version")
    topics = {t["id"]: t for t in capability["topics"]}
    _need(type(runtime["decisions"]) is list and len(runtime["decisions"]) <= len(topics) * 14 and type(runtime["lines"]) is list and len(runtime["lines"]) <= len(topics) * 14, "NPC scope bounds")
    npcs = {n["character_id"]: n for n in state["npcs"]}
    observations = {o["id"]: o for o in case["observations"]}
    lines, decisions = {}, {}
    game_counts, window_counts = Counter(), Counter()
    for row in runtime["lines"]:
        _obj(row, {"npc", "topic", "window_idx", "line_id"}, "line decision")
        for field in ("npc", "topic", "line_id"):
            _id(row[field])
        _int(row["window_idx"], 1, state["clock"]["window_idx"], "line window")
        topic = topics.get(row["topic"])
        _need(topic is not None and row["npc"] == topic["npc"] and row["npc"] in npcs and npcs[row["npc"]]["origin"] == "authored", "line catalog/original NPC scope")
        key = (row["npc"], row["topic"], row["window_idx"])
        _need(key not in lines, "duplicate line scope")
        index = delivery_draw(state["sealed"]["seed"], row["npc"], row["topic"], row["window_idx"], 1, domain="night-case-line/1", upper=len(topic["lines"]))
        _need(row["line_id"] == topic["lines"][index]["id"], "line differs from seeded selection")
        lines[key] = topic["lines"][index]["body"]
    for row in runtime["decisions"]:
        decision = slip_decision_from_json(_canonical(row))
        scope = decision.scope
        _int(scope.window_idx, 1, state["clock"]["window_idx"], "decision window")
        topic = topics.get(scope.topic_id)
        _need(topic is not None and topic["slip"] is not None and scope.game_id == state["game_id"] and scope.npc_id == topic["npc"], "decision catalog/scope")
        rule = topic["slip"]
        _need((decision.rule_id, decision.rule_version, decision.probability_bp, decision.fact_id) == (rule["rule_id"], rule["version"], rule["probability_bp"], rule["observation"]), "decision rule version/catalog")
        observation = observations[decision.fact_id]
        _need(observation["kind"] == "claim" and observation["speaker"] == scope.npc_id, "slip must be NPC authored claim")
        key = (scope.npc_id, scope.topic_id, scope.window_idx)
        _need(key in lines and key not in decisions, "decision line scope/duplicate")
        if decision.draw is not None:
            _need(decision.probability_bp > 0 and decision.draw == delivery_draw(state["sealed"]["seed"], scope.npc_id, scope.topic_id, scope.window_idx, decision.rule_version, domain="night-case-slip/1", upper=10000), "decision differs from seeded draw")
        decisions[key] = decision
        if decision.revealed:
            game_counts[scope.npc_id] += 1
            window_counts[(scope.npc_id, scope.window_idx)] += 1
    _need(all(n <= capability["game_reveal_budget"] for n in game_counts.values()) and all(n <= capability["window_reveal_budget"] for n in window_counts.values()), "NPC reveal budget exceeded")
    for key, decision in decisions.items():
        if decision.probability_bp > 0 and decision.draw is None:
            earlier = sum(d.revealed for k, d in decisions.items() if k[0] == key[0] and k[2] <= key[2])
            _need(window_counts[(key[0], key[2])] >= capability["window_reveal_budget"] or earlier >= capability["game_reveal_budget"], "unjustified exhausted decision")
    variant = state["sealed"]["variant_id"]
    def authored(target):
        return [target["fallback"]] + [o["body"] for o in target["outcomes"] if o["guard"]["variants"] == "all" or variant in o["guard"]["variants"]]
    ordinary = [b for a in case["actions"] for b in authored(a)]
    targets = {}
    for dialogue in case["dialogues"]:
        for node in dialogue["nodes"]:
            for option in node["options"]:
                key = (dialogue["id"], node["id"], option["id"])
                targets[key] = option
                if not any((t["dialogue"], t["node"], t["option"]) == key for t in topics.values()):
                    ordinary.extend(authored(option))
    heard = {}
    for key, line in lines.items():
        topic = topics[key[1]]
        target = targets[(topic["dialogue"], topic["node"], topic["option"])]
        possible = [composed_body(line, b) for b in authored(target)]
        matching = [e for e in state["private_events"] if e["kind"] == "action_result" and e["window_idx"] == key[2] and e["payload"]["body"] in possible]
        _need(bool(matching), "line scope lacks exact composed talk result")
        heard[key] = {e["audience"]["ids"][0] for e in matching}
    for event in state["private_events"]:
        if event["kind"] == "action_result":
            composed = [composed_body(line, b) for key, line in lines.items() if key[2] == event["window_idx"] for b in authored(targets[(topics[key[1]]["dialogue"], topics[key[1]]["node"], topics[key[1]]["option"])])]
            _need(event["payload"]["body"] in ordinary + composed, "unauthored action/talk result body")
    characters = {p["account_id"]: p["character_id"] for p in state["players"]}
    sources = [(k["account_id"], k["observation_id"], k["source"]) for k in state["knowledge"]]
    sources += [(e["audience"]["ids"][0], e["payload"]["observation_id"], e["payload"]["source"]) for e in state["private_events"] if e["kind"] == "observation_granted"]
    for account, observation_id, source in sources:
        for topic in topics.values():
            if topic["slip"] is None or observation_id != topic["slip"]["observation"] or source["source_id"] != topic["option"]:
                continue
            key = (topic["npc"], topic["id"], source["window_idx"])
            character = next(c for c in case["characters"] if c["id"] == topic["npc"])
            concealed = next((n for n in case.get("module_data", {}).get("turning_point", {}).get("concealed_npcs", []) if n["character"] == topic["npc"]), None)
            if concealed is not None:
                expected_location = next(p["location"] for p in concealed["placements"] if p["variants"] == "all" or variant in p["variants"])
            else:
                expected_location = next((s["location"] for s in character["schedule"] if source["window_idx"] in s["windows"]), character["home"])
            _need(key in decisions and decisions[key].revealed and account in heard[key] and source["kind"] == "dialogue" and source["actor_character"] == characters[account] and source["location"] == expected_location, "slip dialogue grant provenance/ACL/decision")
