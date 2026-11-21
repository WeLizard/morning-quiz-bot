"""Pure, one-batch transitions for executable night cases."""

from __future__ import annotations

import copy
import hashlib
import json
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .night_case_projection import _eligibility, _predicates, _module, _flag, _npc_visible
from .night_case_delivery import make_message, dialogue_topic, resolve_dialogue
from .night_case_personal import story_index, story_predicate, completed_steps, open_offers, original_state, work_progress, record_story, publication
from .night_case_state import Clock, KernelState, PlayerActor, SystemActor, canonical_hash, event_id_for, parse_command, engine_build_for
from .night_case_time import _parse, _stamp, _utc, after_quiet, next_slot, resume_deadline
from .night_case_text import chosen_looks, pick_looks

ENGINE_BUILD = "night-case-core/1"


class Transition:
    """Defensive transition: each property returns a fresh materialized value."""

    __slots__ = ("state", "_events", "_receipt", "_due", "_messages")

    def __init__(self, state: KernelState, events, receipt, due, messages=()):
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "_events", json.dumps(events, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        object.__setattr__(self, "_receipt", json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        object.__setattr__(self, "_messages", json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        object.__setattr__(self, "_due", json.dumps(due, ensure_ascii=False, sort_keys=True, separators=(",", ":")))

    def __setattr__(self, key, value):
        raise AttributeError("frozen transition")

    @property
    def events(self): return tuple(json.loads(self._events))

    @property
    def messages(self): return tuple(json.loads(self._messages))

    @property
    def receipt(self): return json.loads(self._receipt)

    @property
    def due(self): return json.loads(self._due)


def _event(doc, batch, kind, payload, account=None):
    audience = {"kind": "accounts", "ids": [account]} if account else {"kind": "public"}
    seq = 1 + (sum(e["audience"]["kind"] == "accounts" and e["audience"]["ids"] == [account] for e in doc["private_events"]) if account else len(doc["public"]["chronicle"]))
    row = {"event_id": event_id_for(doc["game_id"], audience, seq), "window_idx": doc["clock"]["window_idx"], "audience_seq": seq, "kind": kind, "audience": audience, "payload": copy.deepcopy(payload)}
    (doc["private_events"] if account else doc["public"]["chronicle"]).append(row)
    if not account: doc["public"]["revision"] += 1
    batch.append(row)
    return row


def _digest(doc, batch, account, summarized_idx, *, initial=False):
    public = [e for e in doc["public"]["chronicle"] if e["window_idx"] == summarized_idx]
    own = [e for e in doc["private_events"] if e["window_idx"] == summarized_idx and e["audience"]["ids"] == [account]]
    candidates = public + own
    if initial:
        candidates = [e for e in candidates if e["kind"] == "observation_granted" and e["payload"]["source"]["kind"] == "initial"]
    else:
        candidates = [e for e in candidates if e["kind"] not in {"window_digest", "afk_notice"}]
    chosen = candidates[-64:]
    board = {b["id"]: b for b in doc["public"]["board"]}
    observations = set()
    for e in chosen:
        if e["kind"] == "observation_granted": observations.add(e["payload"]["observation_id"])
        elif e["kind"] in {"action_result", "archive_response", "story_result"}: observations.update(e["payload"]["observation_ids"])
        elif e["kind"] == "authored_card_delivered": observations.add(e["payload"]["observation_id"])
        elif e["kind"] == "board":
            item = board[e["payload"]["board_id"]]
            if item["observation_id"] is not None: observations.add(item["observation_id"])
    _event(doc, batch, "window_digest", {"window_idx": summarized_idx, "observation_ids": sorted(observations), "event_ids": [e["event_id"] for e in chosen]}, account)


def _due(doc):
    clock = doc["clock"]
    if clock["phase"] == "finished": return None
    if clock["phase"] == "frozen": return {"kind": "forget", "at": clock["forget_at"], "window_seq": clock["window_seq"], "timer_seq": clock["timer_seq"], "reason": "frozen"}
    ready = [p for p in doc["players"] if p["status"] == "active"]
    early = bool(ready) and all(p["finished_window"] for p in ready)
    at = min(clock["early_not_before"], clock["closes_at"]) if early else clock["closes_at"]
    return {"kind": "phase", "at": at, "window_seq": clock["window_seq"], "timer_seq": clock["timer_seq"], "reason": "early" if early and at < clock["closes_at"] else "deadline"}


def _transition(doc, case, rules, batch, receipt=None, messages=()):
    if "personal_story" in doc and doc["personal_story"]["journal"] and not doc["personal_story"]["journal"][-1]["entries"]: doc["personal_story"]["journal"].pop()
    state = KernelState.from_document(doc, case, rules)
    external = None if receipt is None else {key: receipt[key] for key in ("accepted", "code", "actor_revision")}
    return Transition(state, tuple(copy.deepcopy(batch)), external, copy.deepcopy(_due(doc)), messages)


def _source(kind, source_id, window_idx, character=None, location=None):
    return {"kind": kind, "source_id": source_id, "actor_character": character, "location": location, "window_idx": window_idx}


def _known_source(doc, account, observation_id):
    own = next((k["source"] for k in doc["knowledge"] if k["account_id"] == account and k["observation_id"] == observation_id), None)
    if own is not None: return copy.deepcopy(own)
    public = next((k["source"] for k in doc["public"]["observations"] if k["observation_id"] == observation_id), None)
    if public is not None: return copy.deepcopy(public)
    board = next((b["source"] for b in doc["public"]["board"] if b["observation_id"] == observation_id and b["source"] is not None), None)
    if board is not None: return copy.deepcopy(board)
    raise ValueError("observation unavailable")


def _world_snapshot(doc):
    return ({f["id"]: f["value"] for f in doc["public"]["flags"]}, {l["location"]: l["through_window"] for l in doc["public"]["locks"]})


def _world_changed(doc, batch, before):
    flags_now, locks_now = _world_snapshot(doc)
    flags = [{"id": key, "value": flags_now[key]} for key in sorted(flags_now) if before[0].get(key) != flags_now[key]]
    locks = [{"location": key, "through_window": locks_now.get(key)} for key in sorted(set(before[1]) | set(locks_now)) if before[1].get(key) != locks_now.get(key)]
    if flags or locks: _event(doc, batch, "world_changed", {"flags": flags, "locks": locks})


def _grant(doc, batch, observation_id, account=None, *, kind="event", source_id=None, character=None, location=None, case_doc=None, publisher=None):
    idx = doc["clock"]["window_idx"]
    if account:
        if any(k["account_id"] == account and k["observation_id"] == observation_id for k in doc["knowledge"]): return
        if kind == "initial":
            audience = {"kind": "accounts", "ids": [account]}
            seq = 1 + sum(e["audience"] == audience for e in doc["private_events"])
            source_id = event_id_for(doc["game_id"], audience, seq)
        source = _source(kind, source_id or "initial", idx, character, location)
        doc["knowledge"].append({"account_id": account, "observation_id": observation_id, "source": source})
        player = next(p for p in doc["players"] if p["account_id"] == account)
        player["knowledge_revision"] += 1
        _event(doc, batch, "observation_granted", {"observation_id": observation_id, "source": source}, account)
    else:
        if any(k["observation_id"] == observation_id for k in doc["public"]["observations"]): return
        eid = event_id_for(doc["game_id"], {"kind": "public"}, len(doc["public"]["chronicle"]) + 1)
        source = _source("initial" if kind == "initial" else "event", eid, idx)
        doc["public"]["observations"].append({"observation_id": observation_id, "source": source})
        event = _event(doc, batch, "observation_granted", {"observation_id": observation_id, "source": source})
        if case_doc: publication(case_doc, doc, observation_id, publisher, event["event_id"])


def _effects(doc, batch, effects, account=None, *, source_kind="action", source_id="initial", case_doc=None):
    player = next((p for p in doc["players"] if p["account_id"] == account), None)
    for effect in effects:
        kind = effect["kind"]
        if kind == "grant_observation":
            private = effect["audience"] == "actor"
            _grant(doc, batch, effect["observation"], account if private else None, kind=source_kind, source_id=source_id, character=player["character_id"] if private else None, location=player["location"] if private else None, case_doc=case_doc, publisher=account)
        elif kind == "set_flag":
            row = next(f for f in doc["public"]["flags"] if f["id"] == effect["flag"])
            if row["value"] != effect["value"]:
                row["value"] = effect["value"]
        elif kind == "lock_location":
            doc["public"]["locks"] = [l for l in doc["public"]["locks"] if l["location"] != effect["location"]]
            lock = {"location": effect["location"], "through_window": effect["through_window"]}
            doc["public"]["locks"].append(lock)
        elif kind == "unlock_location":
            doc["public"]["locks"] = [l for l in doc["public"]["locks"] if l["location"] != effect["location"]]
        elif kind == "reveal_npc":
            hidden = next(n for n in _module(case_doc, "turning_point")["concealed_npcs"] if n["character"] == effect["character"])
            npc = next(n for n in doc["npcs"] if n["character_id"] == effect["character"])
            if player is None or npc["status"] != "active" or npc["location"] != player["location"]: raise ValueError("invalid NPC reveal content")
            if not _flag(doc, hidden["revealed_flag"]):
                next(f for f in doc["public"]["flags"] if f["id"] == hidden["revealed_flag"])["value"] = True
                _event(doc, batch, "npc_revealed", {"character_id": npc["character_id"], "location": npc["location"]})
        else: raise ValueError("unsupported effect")


def _settle(doc, c, batch):
    turning = _module(c, "turning_point")
    routes, scenes = turning.get("routes", []), turning.get("scenes", [])
    # Each successful pass consumes a new route or scene; no separate clock.
    for _ in range(len(routes) + len(scenes) + 1):
        changed = False
        proxy = {"account_id": "", "location": None}
        for route in routes:
            if not _flag(doc, route["opened_flag"]) and _predicates(route["open_when"], doc, proxy):
                next(f for f in doc["public"]["flags"] if f["id"] == route["opened_flag"])["value"] = True
                changed = True
        scene = next((s for s in scenes if s["id"] not in doc["event_uses"] and s["not_before"] <= doc["clock"]["window_idx"] <= s["through_window"] and _predicates(s["when"], doc, proxy)), None)
        if scene:
            doc["event_uses"].append(scene["id"])
            _event(doc, batch, "scene", {"content_event_id": scene["id"], "body": scene["body"]})
            _effects(doc, batch, scene["effects"], source_kind="event", source_id=scene["id"], case_doc=c)
            changed = True
        if not changed: return
    raise ValueError("settle bound exceeded")


def _deliver_archive(doc, c, batch):
    responses = {e["payload"]["request_event_id"] for e in doc["private_events"] if e["kind"] == "archive_response"}
    requests = sorted((e for e in doc["private_events"] if e["kind"] == "archive_requested" and e["event_id"] not in responses and e["payload"]["due_window"] == doc["clock"]["window_idx"]), key=lambda e: (e["audience"]["ids"][0], e["audience_seq"]))
    for request in requests:
        account = request["audience"]["ids"][0]
        player = next(p for p in doc["players"] if p["account_id"] == account)
        query = next(q for q in _module(c, "archive_requests")["queries"] if q["id"] == request["payload"]["query_id"])
        response = next(r for r in query["responses"] if r["variants"] == "all" or doc["sealed"]["variant_id"] in r["variants"])
        delivered = player["status"] in {"active", "fog"}
        _event(doc, batch, "archive_response", {"request_event_id": request["event_id"], "disposition": "delivered" if delivered else "cancelled", "body": response["body"] if delivered else None, "observation_ids": response["observations"] if delivered else []}, account)
        if delivered:
            for oid in response["observations"]:
                _grant(doc, batch, oid, account, kind="event", source_id=request["event_id"], character=player["character_id"], location=None)


def _proven(variant, keys):
    return len(keys & set(variant["key_proofs"])) >= variant["min_key"] and set(variant.get("required_key_proofs", [])) <= keys


def _recovery(doc, c, rules, batch, now):
    recovery = _module(c, "turning_point").get("recovery")
    if not recovery or doc["clock"]["window_idx"] > recovery["through_window"]: return
    hidden = next(n for n in _module(c, "turning_point")["concealed_npcs"] if n["character"] == recovery["character"])
    variant = next(v for v in c["variants"] if v["id"] == doc["sealed"]["variant_id"])
    if _flag(doc, hidden["revealed_flag"]) and _proven(variant, _cited_keys(doc, c, [b["id"] for b in doc["public"]["board"]])):
        _terminal(doc, c, rules, batch, now, "solved")


def _open_window(doc, c, rules, batch, now):
    clock = doc["clock"]
    world_before = _world_snapshot(doc)
    clock["phase"] = "final_hearing" if clock["window_idx"] == rules.final_hearing_window else "investigation"
    clock["opening_pending"] = False
    clock["freeze_at"] = clock["forget_at"] = None
    clock["opened_at"] = _stamp(now)
    end = next_slot(now + timedelta(seconds=rules.early_min_seconds, microseconds=-1), rules.timezone, rules)
    clock["closes_at"] = _stamp(after_quiet(end, rules.timezone, rules))
    clock["early_not_before"] = _stamp(now + timedelta(seconds=rules.early_min_seconds))
    for p in doc["players"]:
        p["ap"] = rules.ap_per_window if p["status"] in {"active", "fog"} else 0
        p["finished_window"] = False
    old = doc["public"]["locks"]
    doc["public"]["locks"] = [l for l in old if l["through_window"] >= clock["window_idx"]]
    for event in c["events"]:
        if event["window"] == clock["window_idx"] and event["id"] not in doc["event_uses"]:
            doc["event_uses"].append(event["id"])
            _event(doc, batch, "scene", {"content_event_id": event["id"], "body": event["body"]})
            _effects(doc, batch, event["effects"], source_kind="event", source_id=event["id"], case_doc=c)
    characters = {x["id"]: x for x in c["characters"]}
    for npc in doc["npcs"]:
        if npc["status"] != "active" or npc["origin"] != "authored": continue
        if any(n["character"] == npc["character_id"] for n in _module(c, "turning_point").get("concealed_npcs", [])): continue
        char = characters[npc["character_id"]]
        overrides = [s["location"] for s in char["schedule"] if clock["window_idx"] in s["windows"]]
        location = overrides[0] if overrides else char["home"]
        if location in {l["location"] for l in doc["public"]["locks"]}: raise ValueError("scheduled NPC enters locked location")
        npc["location"] = location
    if c["ruleset_ref"]["version"] == 2:
        _deliver_archive(doc, c, batch)
        _settle(doc, c, batch)
    _world_changed(doc, batch, world_before)
    _event(doc, batch, "window", {"window_idx": clock["window_idx"], "phase": clock["phase"], "opened_at": clock["opened_at"], "closes_at": clock["closes_at"]})
    if clock["window_idx"] > 1:
        for player in doc["players"]:
            if player["status"] != "departed":
                _digest(doc, batch, player["account_id"], clock["window_idx"] - 1)
                if player["missed_windows"] == rules.afk_notice_windows:
                    _event(doc, batch, "afk_notice", {"window_idx": clock["window_idx"] - 1, "missed_windows": player["missed_windows"]}, player["account_id"])


def _rng(seed, label):
    material = hashlib.sha256(f"night-case-rng/1:{seed}:{label}".encode()).digest()
    return random.Random(int.from_bytes(material, "big"))


def start(case, rules, roster, *, game_id, seed, now_utc):
    c = case.document()
    if type(roster) is not dict or set(roster) != {"players", "npc_name_pool"}: raise ValueError("invalid roster")
    count = len(roster["players"])
    composition = next((x for x in c["compositions"] if x["players"] == count), None)
    if composition is None: raise ValueError("unsupported player count")
    variants = sorted(v["id"] for v in c["variants"] if composition["id"] in v["composition_ids"])
    variant = _rng(seed, "variant").choice(variants)
    return _initialize(case, rules, roster, game_id=game_id, seed=seed, composition_id=composition["id"], selected_variant_id=variant, now_utc=now_utc)


OPEN_SEATING = "open"
OPEN_MIN, OPEN_MAX = 3, 12


def playable_heroes(case_doc):
    return sorted(x["id"] for x in case_doc["characters"] if x["can_be_player"])


def open_counts(case_doc):
    """Table sizes of free seating: 3..12, never more than the case has playable heroes."""
    return list(range(OPEN_MIN, min(OPEN_MAX, len(playable_heroes(case_doc))) + 1))


def seated_variants(case_doc, heroes):
    """Variants in which at least one seated human hero investigates (otherwise no_investigators at once)."""
    chars = {x["id"]: x for x in case_doc["characters"]}
    return sorted(v["id"] for v in case_doc["variants"]
                  if any(h != v["culprit"] and h not in v["accomplices"] and chars[h]["faction"] == "investigation" for h in heroes))


def _seat_anyone(c, players, seed):
    """Seats for "any seat" players: a seeded draw from free heroes; if no variant fits, investigators go first."""
    chars = {x["id"]: x for x in c["characters"]}
    fixed = {p["account_id"]: p["character_id"] for p in players if p["character_id"] is not None}
    anyone = sorted(p["account_id"] for p in players if p["character_id"] is None)
    free = [h for h in playable_heroes(c) if h not in set(fixed.values())]
    _rng(seed, "seats").shuffle(free)
    for order in (free, sorted(free, key=lambda h: chars[h]["faction"] != "investigation")):
        seats = {**fixed, **dict(zip(anyone, order))}
        if seated_variants(c, seats.values()): return seats
    return None


def start_open(case, rules, roster, *, game_id, seed, now_utc):
    """Free seating: as many players as came (3..12), each on a chosen hero and look or on any free seat.

    roster.players rows: {account_id, display_name, character_id|None, look_id|None}. Heroes nobody took are
    played by the game. The variant of the truth is drawn only among those where a seated human investigates.
    """
    c = case.document()
    if type(roster) is not dict or set(roster) != {"players", "npc_name_pool"} or type(roster["players"]) is not list: raise ValueError("invalid roster")
    players = roster["players"]
    playable = {x["id"]: x for x in c["characters"] if x["can_be_player"]}
    if len(players) not in open_counts(c): raise ValueError("unsupported player count")
    looks = {}
    for p in players:
        if type(p) is not dict or set(p) != {"account_id", "display_name", "character_id", "look_id"}: raise ValueError("invalid players")
        hero, look = p["character_id"], p["look_id"]
        if hero is None:
            if look is not None: raise ValueError("look without a hero")
            continue
        if hero not in playable: raise ValueError("hero is not playable")
        if look is not None:
            if look not in {x["id"] for x in playable[hero].get("looks") or ()}: raise ValueError("unknown look")
            looks[hero] = look
    taken = [p["character_id"] for p in players if p["character_id"] is not None]
    if len(set(taken)) != len(taken): raise ValueError("hero taken twice")
    seats = _seat_anyone(c, players, seed)
    if seats is None: raise ValueError("no variant for seats")
    variant = _rng(seed, "variant").choice(seated_variants(c, seats.values()))
    plain = {"players": [{"account_id": p["account_id"], "display_name": p["display_name"]} for p in players], "npc_name_pool": roster["npc_name_pool"]}
    return _initialize(case, rules, plain, game_id=game_id, seed=seed, composition_id=OPEN_SEATING, selected_variant_id=variant, now_utc=now_utc, seats=seats, seat_looks=looks)


def _initialize(case, rules, roster, *, game_id, seed, composition_id, selected_variant_id, now_utc, seats=None, seat_looks=None):
    now = _utc(now_utc)
    c = case.document()
    if type(seed) is not int or seed < 0 or type(game_id) is not str or not game_id: raise ValueError("invalid start identity")
    if type(roster) is not dict or set(roster) != {"players", "npc_name_pool"}: raise ValueError("invalid roster")
    variant = next((x for x in c["variants"] if x["id"] == selected_variant_id), None)
    if composition_id == OPEN_SEATING:
        if type(seats) is not dict or variant is None: raise ValueError("incompatible seating/variant")
        comp = {"players": len(seats), "player_characters": sorted(seats.values())}
    else:
        comp = next((x for x in c["compositions"] if x["id"] == composition_id), None)
        if seats is not None or comp is None or variant is None or composition_id not in variant["composition_ids"]: raise ValueError("incompatible composition/variant")
    human = copy.deepcopy(roster["players"])
    if len(human) != comp["players"] or any(type(p) is not dict or set(p) != {"account_id", "display_name"} or type(p["account_id"]) is not str or not p["account_id"] or type(p["display_name"]) is not str or not 1 <= len(p["display_name"]) <= 120 for p in human): raise ValueError("invalid players")
    if len({p["account_id"] for p in human}) != len(human) or len({p["display_name"] for p in human}) != len(human): raise ValueError("duplicate roster")
    pool = copy.deepcopy(roster["npc_name_pool"])
    npc_count = len(c["characters"]) - len(human)
    if type(pool) is not list or len(pool) < npc_count or any(type(n) is not str or not 1 <= len(n) <= 120 for n in pool) or len(set(pool)) != len(pool) or set(pool) & {p["display_name"] for p in human}: raise ValueError("invalid NPC name pool")
    human.sort(key=lambda p: p["account_id"])
    chars = sorted(comp["player_characters"])
    if seats is None:
        _rng(seed, "assignments").shuffle(chars)
        assigned = dict(zip((p["account_id"] for p in human), chars))
    else:
        if set(seats) != {p["account_id"] for p in human}: raise ValueError("seats do not match the roster")
        assigned = {p["account_id"]: seats[p["account_id"]] for p in human}
    names = sorted(pool); _rng(seed, "names").shuffle(names)
    characters = {x["id"]: x for x in c["characters"]}
    profile = c["ruleset_ref"]
    doc = {"state_schema": "night-city-state/1", "game_id": game_id, "case_ref": {"case_id": case.case_id, "case_version": case.case_version, "content_hash": case.content_hash}, "ruleset_ref": copy.deepcopy(profile), "rules": rules.document(), "rules_hash": rules.rules_hash, "compiler_version": case.compiler_version, "engine_build": engine_build_for(profile), "sealed": {"variant_id": selected_variant_id, "seed": seed, "composition_id": composition_id, "assignments": [{"account_id": a, "character_id": x} for a, x in assigned.items()]}, "clock": {"timezone": rules.timezone, "window_idx": 1, "window_seq": 1, "timer_seq": 1, "opened_at": None, "closes_at": None, "early_not_before": None, "slot_cursor": None, "phase": "investigation", "opening_pending": False, "freeze_at": None, "forget_at": None, "resume_receipts": []}, "players": [], "npcs": [], "public": {"flags": [{"id": f["id"], "value": f["initial"]} for f in c["flags"]], "locks": [], "observations": [], "board": [], "chronicle": [], "revision": 0, "framed_count": 0}, "knowledge": [], "private_events": [], "dialogue_cursors": [], "action_uses": [], "event_uses": [], "hearing": None, "final_ballots": [], "receipts": [], "idle_windows": 0, "final": None}
    for p in human:
        cid = assigned[p["account_id"]]
        doc["players"].append({"account_id": p["account_id"], "character_id": cid, "name": p["display_name"], "status": "active", "location": characters[cid]["home"], "ap": 3, "actor_seq": 0, "knowledge_revision": 0, "last_seen_window": 0, "missed_windows": 0, "finished_window": False, "ghost_used_window": None, "accusations_used": 0, "wrong_accusations": 0, "participated_windows": [], "departed_snapshot": None})
    for i, cid in enumerate(sorted(set(characters) - set(chars))):
        doc["npcs"].append({"character_id": cid, "name": names[i], "location": characters[cid]["home"], "status": "active", "origin": "authored"})
    for hidden in _module(c, "turning_point").get("concealed_npcs", []):
        placement = next(p for p in hidden["placements"] if p["variants"] == "all" or selected_variant_id in p["variants"])
        next(n for n in doc["npcs"] if n["character_id"] == hidden["character"])["location"] = placement["location"]
    looks = pick_looks(c, _rng(seed, "looks"))
    looks.update({hero: look for hero, look in (seat_looks or {}).items() if hero in looks})
    if looks: doc["sealed"]["looks"] = looks
    # A hero the game plays carries the name of its look; the era pool only names cases without authored names.
    authored = chosen_looks(c, doc)
    for npc in doc["npcs"]:
        if authored[npc["character_id"]].get("name"): npc["name"] = authored[npc["character_id"]]["name"]
    batch = []
    if "communication" in c: doc["communication"] = {"version": 1, "sent": []}
    if "npc_delivery" in c: doc["npc_delivery"] = {"version": 1, "decisions": [], "lines": []}
    if "personal_tasks" in c:
        doc["personal_story"] = {"version": 1, "journal": []}
        _begin_story(doc, {"kind": "system", "transition_key": "start_1"})
    _open_window(doc, c, rules, batch, now)
    for oid in c["initial"]["public_observations"]: _grant(doc, batch, oid, kind="initial", source_id="start:" + game_id, case_doc=c)
    for grant in c["initial"]["personal"]:
        for p in doc["players"]:
            if p["character_id"] == grant["character"]:
                for oid in grant["observations"]: _grant(doc, batch, oid, p["account_id"], kind="initial", source_id="start:" + game_id, case_doc=c)
    for player in doc["players"]: _digest(doc, batch, player["account_id"], 1, initial=True)
    return _transition(doc, case, rules, batch)


def _begin_story(doc, cause):
    journal = doc["personal_story"]["journal"]
    journal.append({"seq": len(journal) + 1, "window_idx": doc["clock"]["window_idx"], "cause": cause, "entries": []})


def _story_response(c, doc, step):
    return next(r for r in step["responses"] if r["variants"] == "all" or doc["sealed"]["variant_id"] in r["variants"])


def _story_result(doc, c, batch, player, step, disposition, body, observations, *, location=None):
    # Receipt enumerates the authored result even when a card was already known.
    for oid in observations:
        _grant(doc, batch, oid, player["account_id"], kind="action", source_id=step["action"], character=player["character_id"], location=location or player["location"])
    return _event(doc, batch, "story_result", {"step_id": step["id"], "disposition": disposition, "body": body, "observation_ids": list(dict.fromkeys(observations))}, player["account_id"])


def _close_return(doc, c, batch, offer, decision):
    record_story(doc, {"kind": "return_answered", "offer_event_id": offer["offer_event_id"], "decision": decision})
    for account in dict.fromkeys([offer["account_id"], offer["recipient_account_id"]]):
        if account: _event(doc, batch, "story_return_closed", {"offer_event_id": offer["offer_event_id"], "decision": decision}, account)


def _complete_return(doc, c, batch, offer):
    step = next(s for s in c["personal_tasks"]["steps"] if s["id"] == offer["step_id"])
    original = next(o for o in c["personal_tasks"]["originals"] if o["id"] == step["operation"]["original"])
    sender = next(p for p in doc["players"] if p["account_id"] == offer["account_id"])
    _close_return(doc, c, batch, offer, "accepted")
    record_story(doc, {"kind": "step_done", "step_id": step["id"], "account_id": sender["account_id"]})
    recipient = offer["recipient_account_id"]
    if recipient:
        for section in original["sections"]:
            _grant(doc, batch, section["observation"], recipient, kind="action", source_id=step["action"], character=sender["character_id"], location=original["return_location"])
    response = _story_response(c, doc, step)
    return _story_result(doc, c, batch, sender, step, "completed", response["body"], response["observations"], location=original["return_location"])


def _reply_return(doc, c, batch, offer, accept):
    if accept: _complete_return(doc, c, batch, offer)
    else: _close_return(doc, c, batch, offer, "declined")
    # Reply events may belong to the sender, so the recipient receipt has no private result ref.
    return None


def _cancel_returns(doc, c, batch, *, terminal=False):
    for offer in open_offers(c, doc):
        sender = next(p for p in doc["players"] if p["account_id"] == offer["account_id"])
        recipient = next((p for p in doc["players"] if p["account_id"] == offer["recipient_account_id"]), None)
        if terminal or sender["status"] in {"ghost", "departed"} or recipient and recipient["status"] in {"ghost", "departed"}:
            _close_return(doc, c, batch, offer, "cancelled")


def _personal_act(doc, c, batch, player, action):
    tasks = c["personal_tasks"]
    step = next(s for s in tasks["steps"] if s["id"] == action["personal_step"])
    op, account = step["operation"], player["account_id"]
    success, extra = True, []
    kind = op["kind"]
    if kind in {"inspect_original", "take_original", "destroy_original", "offer_return"}:
        original = next(o for o in tasks["originals"] if o["id"] == op["original"])
        status, holder = original_state(c, doc, original["id"])
        own = status == "held" and holder == player["character_id"]
        if kind == "inspect_original":
            success = own or status == "at_source" and player["location"] == original["source_location"]
            extra = [next(s["observation"] for s in original["sections"] if s["id"] == op["section"])] if success else []
        elif kind == "take_original": success = status == "at_source" and player["location"] == original["source_location"]
        elif kind == "destroy_original": success = own and player["location"] in original["destroy_locations"]
        else:
            recipient = next((p for p in doc["players"] if p["character_id"] == original["return_to"]), None)
            npc = next((n for n in doc["npcs"] if n["character_id"] == original["return_to"] and n["origin"] == "authored"), None)
            success = own and player["location"] == original["return_location"] and (recipient is not None and recipient["status"] in {"active", "fog"} or recipient is None and npc is not None and npc["status"] == "active" and npc["location"] == original["return_location"] and _npc_visible(c, doc, npc))
            if success:
                event = _event(doc, batch, "story_offer", {"step_id": step["id"], "from_character": player["character_id"], "original_id": original["id"], "return_location": original["return_location"], "body": original["offer_body"]}, recipient["account_id"] if recipient else account)
                offer = {"kind": "return_offered", "step_id": step["id"], "account_id": account, "offer_event_id": event["event_id"], "recipient_account_id": recipient["account_id"] if recipient else None}
                record_story(doc, offer)
                if recipient: return _story_result(doc, c, batch, player, step, "offered", original["offer_body"], [])
                return _complete_return(doc, c, batch, offer)
    elif kind == "recover_cache":
        cache = next(x for x in tasks["caches"] if x["id"] == op["cache"])
        success = _flag(doc, cache["thaw_flag"]) and not any(s["operation"].get("cache") == cache["id"] and s["id"] in completed_steps(c, doc, account) for s in tasks["steps"])
    elif kind == "issue_commitment":
        commitment = next(x for x in tasks["commitments"] if x["id"] == op["commitment"])
        npc = next(n for n in doc["npcs"] if n["character_id"] == commitment["issuer"])
        success = npc["status"] == "active" and npc["origin"] == "authored" and npc["location"] == player["location"] and _npc_visible(c, doc, npc)
    elif kind == "deliver_card":
        target = op["recipient"]
        if target is None:
            content = next(o for o in c["observations"] if o["id"] == op["observation"])
            event = _event(doc, batch, "authored_card_delivered", {"observation_id": content["id"], "body": content["body"]})
            if not any(o["observation_id"] == content["id"] for o in doc["public"]["observations"]):
                doc["public"]["observations"].append({"observation_id": content["id"], "source": _source("event", event["event_id"], doc["clock"]["window_idx"])})
            publication(c, doc, content["id"], account, event["event_id"])
        else:
            recipient = next((p for p in doc["players"] if p["character_id"] == target), None)
            npc = next((n for n in doc["npcs"] if n["character_id"] == target and n["origin"] == "authored"), None)
            success = recipient is not None and recipient["status"] in {"active", "fog"} or recipient is None and npc is not None and npc["status"] == "active"
            if success and recipient: _grant(doc, batch, op["observation"], recipient["account_id"], kind="action", source_id=step["action"], character=player["character_id"], location=player["location"])
    elif kind not in {"advance_work", "record_deed", "book_departure"}: raise ValueError("unsupported personal operation")
    if not success: return _story_result(doc, c, batch, player, step, "not_completed", action["fallback"], [])
    record_story(doc, {"kind": "step_done", "step_id": step["id"], "account_id": account})
    response = _story_response(c, doc, step)
    return _story_result(doc, c, batch, player, step, "completed", response["body"], extra + response["observations"])


def _story_epilogue(doc, c, batch, code):
    if code == "forgotten": return
    tasks = c["personal_tasks"]
    for trip in tasks["trips"]:
        player = next((p for p in doc["players"] if p["character_id"] == trip["traveler"] and p["status"] != "departed"), None)
        if player is None: continue
        own = completed_steps(c, doc, player["account_id"])
        booked = any(s["id"] in own and s["operation"]["kind"] == "book_departure" and s["operation"]["trip"] == trip["id"] for s in tasks["steps"])
        work = next(w for w in tasks["works"] if w["id"] == trip["work"])
        if booked and work_progress(c, doc, player["account_id"], work["id"]) == work["stages"]:
            record_story(doc, {"kind": "departed_epilogue", "trip_id": trip["id"], "account_id": player["account_id"]})
            _event(doc, batch, "story_epilogue", {"trip_id": trip["id"], "body": trip["epilogue"]}, player["account_id"])


def _presence(player, idx):
    player["last_seen_window"] = idx
    if idx not in player["participated_windows"]: player["participated_windows"].append(idx)
    player["missed_windows"] = 0
    if player["status"] == "fog": player["status"] = "active"



def _presence_event(doc, batch, player, idx, *, leaving=False):
    was_fog = player["status"] == "fog"
    _presence(player, idx)
    if was_fog and not leaving and doc["ruleset_ref"]["version"] == 2:
        _event(doc, batch, "status", {"character_id": player["character_id"], "controller": "player", "status": "active"})


def _finish(doc, c, rules, batch, code, now):
    if doc["final"] is not None: return
    if doc["hearing"] is not None:
        h = doc["hearing"]
        _event(doc, batch, "hearing", {"hearing_id": h["id"], "suspect": h["suspect"], "stage": "closed", "resolution": "cancelled", "resolve_window": h["resolve_window"]})
        doc["hearing"] = None
    if "personal_tasks" in c:
        _cancel_returns(doc, c, batch, terminal=True)
        _story_epilogue(doc, c, batch, code)
    variant = next(v for v in c["variants"] if v["id"] == doc["sealed"]["variant_id"])
    clock = doc["clock"]
    goals, facts = [], []
    for p in doc["players"]:
        character = next(x for x in c["characters"] if x["id"] == p["character_id"])
        holder = copy.deepcopy(p)
        if p["status"] == "departed" and p["departed_snapshot"]:
            holder["location"] = p["departed_snapshot"]["location"]
        goal_doc = doc
        if p["status"] == "departed" and p["departed_snapshot"]:
            goal_doc = copy.deepcopy(doc)
            goal_doc["clock"]["window_idx"] = p["departed_snapshot"]["window_idx"]
        goal_met = _predicates(character["goal"]["when"], goal_doc, holder, c)
        goals.append({"account_id": p["account_id"], "goal_id": character["goal"]["id"], "met": goal_met})
        faction = "shadow" if p["character_id"] == variant["culprit"] or p["character_id"] in variant["accomplices"] else character["faction"]
        won = (faction == "investigation" and code == "solved") or (faction == "shadow" and code in {"shadow_framed", "no_investigators", "unresolved"})
        total_windows = clock["window_idx"] - int(clock["opening_pending"])
        facts.append({"account_id": p["account_id"], "participated_windows": len(p["participated_windows"]), "total_windows": total_windows, "completed": p["status"] != "departed" and code != "forgotten", "goal_met": goal_met, "faction_won": won, "wrong_accusations": p["wrong_accusations"]})
    doc["final"] = {"code": code, "at": _stamp(now), "variant_id": variant["id"], "culprit": variant["culprit"], "key_proofs": list(variant["key_proofs"]), "goal_results": goals, "reward_facts": facts}
    clock["phase"] = "finished"
    clock["opening_pending"] = False
    clock["opened_at"] = clock["closes_at"] = clock["early_not_before"] = None
    clock["freeze_at"] = clock["forget_at"] = None
    _event(doc, batch, "final", {"code": code, "at": _stamp(now)})


def _terminal(doc, c, rules, batch, now, requested=None):
    variant = next(v for v in c["variants"] if v["id"] == doc["sealed"]["variant_id"])
    if requested == "solved": code = "solved"
    elif c["victory"]["framed_limit"] is not None and doc["public"]["framed_count"] >= c["victory"]["framed_limit"]: code = "shadow_framed"
    else:
        living = [p for p in doc["players"] if p["status"] in {"active", "fog"}]
        investigators = [p for p in living if p["character_id"] != variant["culprit"] and p["character_id"] not in variant["accomplices"] and next(x for x in c["characters"] if x["id"] == p["character_id"])["faction"] == "investigation"]
        code = "no_investigators" if not investigators else requested
    if code: _finish(doc, c, rules, batch, code, now)


def _cited_keys(doc, c, citations):
    by_id = {b["id"]: b for b in doc["public"]["board"]}
    return {by_id[x]["observation_id"] for x in citations if x in by_id and by_id[x]["kind"] == "proof"}


def _resolve_hearing(doc, c, rules, batch, now):
    h = doc["hearing"]
    if h is None or h["resolve_window"] != doc["clock"]["window_idx"]: return
    eligible = {p["account_id"] for p in doc["players"] if p["account_id"] in h["eligible_accounts"] and p["status"] == "active"}
    support = sum(v["choice"] == "support" for v in h["votes"] if v["account_id"] in eligible)
    resolution = "not_supported"
    variant = next(v for v in c["variants"] if v["id"] == doc["sealed"]["variant_id"])
    if eligible and support > len(eligible) / 2:
        cited = h["initial_citations"] + [x for v in h["votes"] if v["account_id"] in eligible for x in v["citations"]]
        keys = _cited_keys(doc, c, cited) & set(variant["key_proofs"])
        if h["suspect"] == variant["culprit"]: resolution = "solved" if _proven(variant, keys) else "not_proven"
        else:
            resolution = "wrong"
            suspect = next((p for p in doc["players"] if p["character_id"] == h["suspect"] and p["status"] != "departed"), None)
            if suspect:
                suspect["status"] = "ghost"; suspect["ap"] = 0
                _event(doc, batch, "status", {"character_id": suspect["character_id"], "controller": "player", "status": "ghost"})
            else:
                npc = next((n for n in doc["npcs"] if n["character_id"] == h["suspect"]), None)
                if npc and npc["status"] == "active":
                    npc["status"] = "removed"
                    _event(doc, batch, "status", {"character_id": npc["character_id"], "controller": "npc", "status": "removed"})
            doc["public"]["framed_count"] += 1
            accuser = next(p for p in doc["players"] if p["account_id"] == h["accuser"])
            accuser["wrong_accusations"] += 1
    if "personal_tasks" in c: _cancel_returns(doc, c, batch)
    _event(doc, batch, "hearing", {"hearing_id": h["id"], "suspect": h["suspect"], "stage": "closed", "resolution": resolution, "resolve_window": h["resolve_window"]})
    doc["hearing"] = None
    _terminal(doc, c, rules, batch, now, "solved" if resolution == "solved" else None)


def _resolve_final(doc, c, rules, batch, now):
    active = {p["account_id"] for p in doc["players"] if p["status"] == "active"}
    ballots = [b for b in doc["final_ballots"] if b["account_id"] in active]
    counts = {}
    for ballot in ballots:
        if ballot["suspect"] is not None: counts[ballot["suspect"]] = counts.get(ballot["suspect"], 0) + 1
    majority = next((suspect for suspect, n in counts.items() if n > len(active) / 2), None)
    variant = next(v for v in c["variants"] if v["id"] == doc["sealed"]["variant_id"])
    cited = [x for b in ballots for x in b["citations"]]
    keys = _cited_keys(doc, c, cited) & set(variant["key_proofs"])
    _terminal(doc, c, rules, batch, now, "solved" if majority == variant["culprit"] and _proven(variant, keys) else "unresolved")


def _tick(doc, c, rules, batch, now):
    clock = doc["clock"]
    if clock["phase"] == "frozen":
        if now >= _parse(clock["forget_at"]): _finish(doc, c, rules, batch, "forgotten", now)
        return
    due = _due(doc)
    if now < _parse(due["at"]): return
    if due["reason"] == "deadline":
        civil = _parse(clock["closes_at"]).astimezone(ZoneInfo(rules.timezone))
        hhmm = civil.strftime("%H:%M")
        if hhmm in rules.slots:
            clock["slot_cursor"] = {"local_date": civil.date().isoformat(), "local_time": hhmm}
    idx = clock["window_idx"]
    present = any(p["last_seen_window"] == idx for p in doc["players"] if p["status"] != "departed")
    doc["idle_windows"] = 0 if present else doc["idle_windows"] + 1
    for p in doc["players"]:
        if p["status"] in {"departed", "ghost"}: continue
        if p["last_seen_window"] != idx:
            p["missed_windows"] += 1
            if p["missed_windows"] >= rules.afk_fog_windows and p["status"] == "active":
                p["status"] = "fog"
                _event(doc, batch, "status", {"character_id": p["character_id"], "controller": "player", "status": "fog"})
        else: p["missed_windows"] = 0
    _resolve_hearing(doc, c, rules, batch, now)
    if doc["final"] is not None: return
    if idx == rules.final_hearing_window:
        _resolve_final(doc, c, rules, batch, now)
        return
    if present:
        for p in doc["players"]:
            if p["status"] == "fog" and p["missed_windows"] >= rules.afk_depart_windows:
                _depart(doc, c, batch, p)
    _terminal(doc, c, rules, batch, now)
    if doc["final"] is not None: return
    clock["window_idx"] += 1
    clock["window_seq"] += 1
    clock["timer_seq"] += 1
    if doc["idle_windows"] >= rules.freeze_after_idle_windows:
        clock.update({"phase": "frozen", "opening_pending": True, "opened_at": None, "closes_at": None, "early_not_before": None, "freeze_at": _stamp(now), "forget_at": _stamp(now + timedelta(days=rules.forget_after_days))})
        _event(doc, batch, "window", {"window_idx": clock["window_idx"], "phase": "frozen", "opened_at": None, "closes_at": None})
        return
    _open_window(doc, c, rules, batch, now)
    _recovery(doc, c, rules, batch, now)


def _depart(doc, c, batch, player):
    if player["status"] == "departed": return
    player["departed_snapshot"] = {"location": player["location"], "known_observations": [k["observation_id"] for k in doc["knowledge"] if k["account_id"] == player["account_id"]], "window_idx": doc["clock"]["window_idx"] - int(doc["clock"]["opening_pending"])}
    player["status"] = "departed"; player["ap"] = 0
    if "personal_tasks" in c:
        record_story(doc, {"kind": "actor_closed", "account_id": player["account_id"]})
        _cancel_returns(doc, c, batch)
    hero = chosen_looks(c, doc)[player["character_id"]].get("name")   # the hero keeps its own name; the label leaves with the player
    doc["npcs"].append({"character_id": player["character_id"], "name": hero or player["name"], "location": player["location"], "status": "active", "origin": "former_player"})
    _event(doc, batch, "status", {"character_id": player["character_id"], "controller": "npc", "status": "active"})


def _apply_player(doc, c, rules, batch, player, kind, params, target, command_id, now, messages):
    idx = doc["clock"]["window_idx"]
    account = player["account_id"]
    result = None
    world_before = _world_snapshot(doc)
    modular = c["ruleset_ref"]["version"] == 2
    if kind == "seen":
        if doc["clock"]["phase"] == "frozen":
            doc["idle_windows"] = 0
            _presence_event(doc, batch, player, idx, leaving=kind == "forfeit")
            _open_window(doc, c, rules, batch, now)
        else: _presence_event(doc, batch, player, idx, leaving=kind == "forfeit")
    else:
        if doc["clock"]["phase"] != "frozen": _presence_event(doc, batch, player, idx, leaving=kind == "forfeit")
        if kind == "say":
            message, result = make_message(doc, player, params, target, command_id)
            messages.append(message)
        elif kind == "move":
            player["location"] = params["location"]
            player["ap"] -= rules.move_cost
        elif kind == "act" and "personal_step" in target:
            player["ap"] -= rules.act_cost
            doc["action_uses"].append({"account_id": account, "action_key": target["id"], "window_idx": idx})
            result = _personal_act(doc, c, batch, player, target)
        elif kind == "story_reply":
            result = _reply_return(doc, c, batch, target, params["accept"])
        elif kind in {"act", "talk"}:
            world_before = _world_snapshot(doc)
            outcomes = target["outcomes"]
            selected = [o for o in outcomes if (o["guard"]["variants"] == "all" or doc["sealed"]["variant_id"] in o["guard"]["variants"]) and _predicates(o["guard"]["when"], doc, player, c)]
            if len(selected) > 1: raise ValueError("overlapping authored outcomes")
            outcome = selected[0] if selected else None
            body = outcome["body"] if outcome else target["fallback"]
            before = {k["observation_id"] for k in doc["knowledge"] if k["account_id"] == account}
            if outcome: _effects(doc, batch, outcome["effects"], account, source_kind="action" if kind == "act" else "dialogue", source_id=target["id"], case_doc=c)
            if kind == "talk" and "npc_delivery" in c:
                topic = dialogue_topic(c, params)
                eligible = topic is not None and topic["slip"] is not None and _predicates(topic["slip"]["requires"], doc, player, c)
                body, claims = resolve_dialogue(c, doc, topic, body, slip_eligible=eligible)
                for oid in claims: _grant(doc, batch, oid, account, kind="dialogue", source_id=params["option_id"], character=player["character_id"], location=player["location"])
            if not modular: _world_changed(doc, batch, world_before)
            gained = [k["observation_id"] for k in doc["knowledge"] if k["account_id"] == account and k["observation_id"] not in before]
            result = _event(doc, batch, "action_result", {"body": body, "observation_ids": gained}, account)
            player["ap"] -= rules.act_cost if kind == "act" else rules.talk_cost
            if kind == "act":
                action = next(a for a in c["actions"] if a["id"] == params["action_id"])
                doc["action_uses"].append({"account_id": account, "action_key": action["id"], "window_idx": None if action["repeat"] == "player_game" else idx})
            else:
                dialogue = next(d for d in c["dialogues"] if d["id"] == params["dialogue_id"])
                next_node = target["next_node"] or dialogue["entry_node"]
                doc["dialogue_cursors"] = [x for x in doc["dialogue_cursors"] if x["account_id"] != account or x["dialogue_id"] != dialogue["id"]]
                doc["dialogue_cursors"].append({"account_id": account, "dialogue_id": dialogue["id"], "node_id": next_node})
        elif kind == "archive_request":
            player["ap"] -= rules.act_cost
            result = _event(doc, batch, "archive_requested", {"query_id": params["query_id"], "due_window": idx + 1}, account)
        elif kind == "version_mark":
            _event(doc, batch, "version_marked", {"version_id": params["version_id"], "state": params["state"], "by_account": account})
        elif kind == "pin":
            knowledge = next(k for k in doc["knowledge"] if k["account_id"] == account and k["observation_id"] == params["observation_id"])
            observation = next(o for o in c["observations"] if o["id"] == params["observation_id"])
            board_id = "board:" + canonical_hash({"game": doc["game_id"], "actor": account, "command_id": command_id})[:32]
            entry = {"id": board_id, "owner_account_id": account, "kind": observation["kind"], "observation_id": observation["id"], "text": None, "source": copy.deepcopy(knowledge["source"])}
            doc["public"]["board"].append(entry)
            event = _event(doc, batch, "board", {"board_id": board_id})
            if "personal_tasks" in c and entry["observation_id"]: publication(c, doc, entry["observation_id"], account, event["event_id"])
        elif kind == "claim":
            board_id = "board:" + canonical_hash({"game": doc["game_id"], "actor": account, "command_id": command_id})[:32]
            doc["public"]["board"].append({"id": board_id, "owner_account_id": account, "kind": "claim", "observation_id": None, "text": params["text"], "source": None})
            _event(doc, batch, "board", {"board_id": board_id})
        elif kind == "finish_window": player["finished_window"] = True
        elif kind == "accuse":
            player["accusations_used"] += 1
            hearing_id = "hearing:" + canonical_hash({"game": doc["game_id"], "actor": account, "command_id": command_id})[:32]
            h = {"id": hearing_id, "accuser": account, "suspect": params["suspect"], "opened_window": idx, "resolve_window": idx + 1, "eligible_accounts": [p["account_id"] for p in doc["players"] if p["status"] == "active"], "initial_citations": list(params["citations"]), "votes": []}
            doc["hearing"] = h
            _event(doc, batch, "hearing", {"hearing_id": hearing_id, "suspect": h["suspect"], "stage": "opened", "resolution": None, "resolve_window": h["resolve_window"]})
        elif kind == "vote":
            h = doc["hearing"]
            h["votes"] = [v for v in h["votes"] if v["account_id"] != account]
            h["votes"].append({"account_id": account, "choice": params["choice"], "citations": list(params["citations"])})
        elif kind == "final_vote":
            doc["final_ballots"] = [b for b in doc["final_ballots"] if b["account_id"] != account]
            doc["final_ballots"].append({"account_id": account, "suspect": params["suspect"], "citations": list(params["citations"])})
        elif kind == "ghost_share":
            player["ghost_used_window"] = idx
            # A ghost publishes its remembered proof through a board entry with its historical provenance.
            source = _known_source(doc, account, params["observation_id"])
            observation = next(o for o in c["observations"] if o["id"] == params["observation_id"])
            board_id = "board:" + canonical_hash({"game": doc["game_id"], "actor": account, "command_id": command_id})[:32]
            entry = {"id": board_id, "owner_account_id": account, "kind": observation["kind"], "observation_id": observation["id"], "text": None, "source": source}
            doc["public"]["board"].append(entry)
            event = _event(doc, batch, "board", {"board_id": board_id})
            if "personal_tasks" in c and entry["observation_id"]: publication(c, doc, entry["observation_id"], account, event["event_id"])
        elif kind == "forfeit": _depart(doc, c, batch, player)
        else: raise ValueError("unsupported player command")
    if kind not in {"seen", "finish_window"} and player["status"] != "departed": player["finished_window"] = False
    player["actor_seq"] += 1
    if modular:
        _settle(doc, c, batch)
        # Wake already folded opening effects into its world event.
        if kind != "seen" or not any(e["kind"] == "window" for e in batch): _world_changed(doc, batch, world_before)
        _recovery(doc, c, rules, batch, now)
    _terminal(doc, c, rules, batch, now)
    return result


def step(case, rules, state, actor, command, *, now_utc):
    """Return a checked new snapshot; refusal receipts are retained for replay."""
    now = _utc(now_utc)
    # Revalidate the entire sealed input before using any field for a decision.
    doc = KernelState.from_document(state.document(), case, rules).document()
    c = case.document()
    cmd = parse_command(command.document() if hasattr(command, "payload_hash") else command, actor, ruleset_version=c["ruleset_ref"]["version"])
    raw = cmd.document()
    key = actor.actor_key
    batch, messages = [], []
    prior = next((r for r in doc["receipts"] if r["actor_key"] == key and r["command_id"] == raw["command_id"]), None)
    if prior:
        if prior["payload_hash"] == cmd.payload_hash: return _transition(doc, case, rules, [], prior)
        return _transition(doc, case, rules, [], {"accepted": False, "code": "command_id_conflict", "actor_revision": prior["actor_revision"]})
    player = next((p for p in doc["players"] if isinstance(actor, PlayerActor) and p["account_id"] == actor.account_id), None)
    if isinstance(actor, PlayerActor) and player is None:
        return _transition(doc, case, rules, [], {"accepted": False, "code": "not_participant", "actor_revision": 0})
    if not isinstance(actor, (PlayerActor, SystemActor)): raise ValueError("invalid trusted actor")
    code, target, result = "accepted", None, None
    if player:
        clock = doc["clock"]
        if clock["phase"] in {"investigation", "final_hearing"} and now >= _parse(clock["closes_at"]): code = "deadline_pending"
        elif (raw["window_idx"], raw["window_seq"], raw["actor_seq"]) != (clock["window_idx"], clock["window_seq"], player["actor_seq"]): code = "stale_context"
        else: code, _, target = _eligibility(c, doc, actor, raw["kind"], raw["params"], now)
        if code == "accepted":
            old_due = _due(doc)
            if "personal_tasks" in c: _begin_story(doc, {"kind": "command", "account_id": player["account_id"], "command_id": raw["command_id"]})
            result = _apply_player(doc, c, rules, batch, player, raw["kind"], raw["params"], target, raw["command_id"], now, messages)
            if _due(doc) != old_due: doc["clock"]["timer_seq"] += 1
    else:
        clock = doc["clock"]
        if (raw["window_seq"], raw["timer_seq"]) != (clock["window_seq"], clock["timer_seq"]): code = "stale_context"
        elif raw["kind"] == "system.tick":
            due = _due(doc)
            if due is None or raw["params"]["expected_due_at"] != due["at"]: code = "stale_context"
            elif now >= _parse(due["at"]):
                if "personal_tasks" in c: _begin_story(doc, {"kind": "system", "transition_key": ("forget_" if clock["phase"] == "frozen" else "close_") + str(clock["window_idx"])})
                _tick(doc, c, rules, batch, now)
            else: code = "action_unavailable"
        elif raw["kind"] == "system.resume":
            if clock["phase"] not in {"investigation", "final_hearing"}: code = "action_unavailable"
            else:
                old_due = _due(doc)
                old_timer_seq = clock["timer_seq"]
                updated = resume_deadline(Clock.from_document(clock), raw["params"], rules, now)
                doc["clock"] = updated.document()
                if old_due and old_due["reason"] == "early" and _parse(raw["params"]["unavailable_from"]) <= _parse(old_due["at"]) <= now:
                    for ready_player in doc["players"]: ready_player["finished_window"] = False
                if _due(doc) != old_due and doc["clock"]["timer_seq"] == old_timer_seq:
                    doc["clock"]["timer_seq"] += 1
        else: code = "action_unavailable"
    revision = player["actor_seq"] if player else doc["clock"]["timer_seq"]
    receipt = {"actor_key": key, "command_id": raw["command_id"], "payload_hash": cmd.payload_hash, "accepted": code == "accepted", "code": code, "actor_revision": revision, "result_ref": result if result and result.get("kind") == "message" else {"kind": "event", "event_id": result["event_id"]} if result else None}
    doc["receipts"].append(receipt)
    return _transition(doc, case, rules, batch, receipt, messages)
