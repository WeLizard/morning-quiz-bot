"""Pure delivery effects for communication and authored NPC dialogue."""
from __future__ import annotations

import json

from .night_case_delivery_state import (
    composed_body, delivery_draw, message_id_for, text_hash_for, thread_key_for,
)
from .night_case_narrative import (
    SlipRule, SlipScope, decide_slip, slip_decision_from_json, slip_decision_to_json,
)


def sent_count(doc, account):
    return next((r["count"] for r in doc["communication"]["sent"] if r["account_id"] == account and r["window_idx"] == doc["clock"]["window_idx"]), 0)


def say_audience(doc, player, params):
    channel = params["channel"]
    if channel == "square":
        return sorted(p["account_id"] for p in doc["players"]) if player["status"] in {"active", "fog"} else None
    if channel == "ghost":
        return sorted(p["account_id"] for p in doc["players"] if p["status"] == "ghost") if player["status"] == "ghost" else None
    targets = [next((p for p in doc["players"] if p["character_id"] == cid), None) for cid in params["recipients"]]
    if player["character_id"] in params["recipients"] or player["status"] not in {"active", "fog"} or player["ap"] < 1: return None
    if any(p is None or p["status"] not in {"active", "fog"} or p["location"] != player["location"] for p in targets): return None
    return sorted([player["account_id"]] + [p["account_id"] for p in targets])


def make_message(doc, player, params, audience, command_id):
    message = {"id": message_id_for(doc["game_id"], player["account_id"], command_id), "channel": params["channel"], "thread_key": thread_key_for(doc["game_id"], params["channel"], audience), "sender_account_id": player["account_id"], "recipient_account_ids": list(audience), "window_idx": doc["clock"]["window_idx"], "text": params["text"], "text_hash": text_hash_for(params["text"])}
    row = next((r for r in doc["communication"]["sent"] if r["account_id"] == player["account_id"] and r["window_idx"] == doc["clock"]["window_idx"]), None)
    if row: row["count"] += 1
    else: doc["communication"]["sent"].append({"account_id": player["account_id"], "window_idx": doc["clock"]["window_idx"], "count": 1})
    if params["channel"] == "whisper": player["ap"] -= 1
    ref = {"kind": "message", "message_id": message["id"], **{k: message[k] for k in ("text_hash", "channel", "thread_key", "recipient_account_ids", "window_idx")}}
    return message, ref


def dialogue_topic(c, params):
    return next((t for t in c.get("npc_delivery", {}).get("topics", []) if (t["dialogue"], t["node"], t["option"]) == (params["dialogue_id"], params["node_id"], params["option_id"])), None)


def resolve_dialogue(c, doc, topic, body, *, slip_eligible):
    if topic is None: return body, []
    runtime = doc["npc_delivery"]
    npc, tid, window = topic["npc"], topic["id"], doc["clock"]["window_idx"]
    prior_line = next((r for r in runtime["lines"] if (r["npc"], r["topic"], r["window_idx"]) == (npc, tid, window)), None)
    if prior_line is None:
        index = delivery_draw(doc["sealed"]["seed"], npc, tid, window, 1, domain="night-case-line/1", upper=len(topic["lines"]))
        line = topic["lines"][index]
        runtime["lines"].append({"npc": npc, "topic": tid, "window_idx": window, "line_id": line["id"]})
    else: line = next(l for l in topic["lines"] if l["id"] == prior_line["line_id"])
    claims = []
    if topic["slip"] is not None and slip_eligible:
        slip = topic["slip"]
        scope = SlipScope(doc["game_id"], npc, tid, window)
        rule = SlipRule(slip["rule_id"], slip["version"], slip["probability_bp"], slip["observation"])
        previous = next((slip_decision_from_json(json.dumps(r)) for r in runtime["decisions"] if r["scope"] == {"game_id": doc["game_id"], "npc_id": npc, "topic_id": tid, "window_idx": window}), None)
        revealed = [r for r in runtime["decisions"] if r["scope"]["npc_id"] == npc and r["revealed"]]
        remaining = min(c["npc_delivery"]["window_reveal_budget"] - sum(r["scope"]["window_idx"] == window for r in revealed), c["npc_delivery"]["game_reveal_budget"] - len(revealed))
        draw = delivery_draw(doc["sealed"]["seed"], npc, tid, window, slip["version"], domain="night-case-slip/1", upper=10000)
        resolution = decide_slip(rule, scope, previous=previous, remaining_budget=remaining, draw=draw)
        if not resolution.reused: runtime["decisions"].append(json.loads(slip_decision_to_json(resolution.decision)))
        if resolution.decision.revealed: claims.append(slip["observation"])
    return composed_body(line["body"], body), claims
