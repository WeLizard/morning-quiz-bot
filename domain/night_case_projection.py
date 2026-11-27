"""Explicit public/self views and variant-independent legal action quotes."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime

from .night_case_narrative import LegalAction
from .night_case_delivery import dialogue_topic, say_audience, sent_count
from .night_case_personal import story_index, story_predicate, completed_steps, open_offers, original_state, step_visible, work_progress
from .night_case_state import KernelState, PlayerActor, _case_doc, canonical_hash, parse_command
from .night_case_text import Renderer, public_look
from .night_case_time import _parse, _utc


@dataclass(frozen=True)
class CommandIntent:
    kind: str
    params: dict


@dataclass(frozen=True)
class MenuChoice:
    kind: str
    entry_id: str
    label: str
    quote: LegalAction


@dataclass(frozen=True)
class MenuForm:
    kind: str
    entry_id: str
    label: str
    command_kind: str
    cost: int
    subject_ids: tuple[str, ...]
    board_ids: tuple[str, ...]
    hearing_id: str | None


@dataclass(frozen=True)
class SayForm:
    kind: str
    entry_id: str
    label: str
    command_kind: str
    channel: str
    cost: int
    subject_ids: tuple[str, ...]


MenuEntry = MenuChoice | MenuForm | SayForm


def _player(doc, actor):
    return next((p for p in doc["players"] if p["account_id"] == actor.account_id), None)


def _known(doc, account):
    return {r["observation_id"] for r in doc["knowledge"] if r["account_id"] == account} | {r["observation_id"] for r in doc["public"]["observations"]} | {r["observation_id"] for r in doc["public"]["board"] if r["observation_id"] is not None}


def _module(c, name):
    return c.get("module_data", {}).get(name, {})


def _enabled(c, name):
    """A module may carry no settings (`{}`), so presence of its key is what enables it."""
    return name in c.get("module_data", {})


GHOST_KINDS = frozenset({"ghost_share", "ghost_whisper", "testimony_answer", "ghost_sign"})


def removed_label(c):
    """Mysticism is a property of the case: only cases with ghost_visions speak of ghosts (MANOR_MODULES_V2 §9)."""
    return "Призраки" if _enabled(c, "ghost_visions") else "Отстранённые"


def _questions(doc):
    """Public testimony questions with their answer event (or None), in chronicle order."""
    chronicle = doc["public"]["chronicle"]
    answers = {e["payload"]["question_event_id"]: e for e in chronicle if e["kind"] == "testimony_answered"}
    return [(e, answers.get(e["event_id"])) for e in chronicle if e["kind"] == "testimony_asked"]


def _question_open(doc, question, answer):
    return answer is None and doc["final"] is None and doc["clock"]["window_idx"] <= question["payload"]["answer_by"]


def _shown_signs(doc):
    return {e["payload"]["sign_id"] for e in doc["public"]["chronicle"] if e["kind"] == "ghost_sign"}


def _ghost_eligibility(case_doc, doc, player, kind, params):
    """One free action per window for a removed player; it never reveals what others know."""
    if kind not in GHOST_KINDS or player["ghost_used_window"] == doc["clock"]["window_idx"]: return "action_unavailable", player, None
    character = next(c for c in case_doc["characters"] if c["id"] == player["character_id"])
    own = {k["observation_id"] for k in doc["knowledge"] if k["account_id"] == player["account_id"]}
    if kind == "ghost_share":
        # Like pin: an observation this player already put on the board is not offered a second time.
        posted = any(b["owner_account_id"] == player["account_id"] and b["observation_id"] == params["observation_id"] for b in doc["public"]["board"])
        allowed = params["observation_id"] in character["ghost_memories"] and params["observation_id"] in _known(doc, player["account_id"]) and not posted
        return ("accepted" if allowed else "action_unavailable"), player, None
    if kind == "ghost_whisper":
        public = {o["observation_id"] for o in doc["public"]["observations"]} | {b["observation_id"] for b in doc["public"]["board"] if b["observation_id"] is not None}
        recipient = next((p for p in doc["players"] if p["character_id"] == params["recipient"] and p["account_id"] != player["account_id"] and p["status"] in {"active", "fog"}), None)
        oid = params["observation_id"]
        # A second copy to the same person would only spend the window; the check reads the sender's own history.
        repeat = any(e["kind"] == "ghost_whispered" and player["account_id"] in e["audience"]["ids"] and e["payload"]["observation_id"] == oid
                     and e["payload"]["recipient_character"] == params["recipient"] for e in doc["private_events"])
        if _enabled(case_doc, "ghost_whisper") and oid in character["ghost_memories"] and oid in own and oid not in public and recipient is not None and not repeat:
            return "accepted", player, recipient
    elif kind == "testimony_answer":
        question = next(((q, a) for q, a in _questions(doc) if q["event_id"] == params["question_event_id"]), None)
        if _enabled(case_doc, "ghost_testimony") and question and question[0]["payload"]["ghost_character"] == player["character_id"] and _question_open(doc, *question):
            return "accepted", player, question[0]
    elif kind == "ghost_sign":
        sign = next((x for x in _module(case_doc, "ghost_visions").get("signs", []) if x["id"] == params["sign_id"]), None)
        if sign and sign["character"] == player["character_id"] and sign["id"] not in _shown_signs(doc):
            return "accepted", player, sign
    return "action_unavailable", player, None


def _talk_exhausted(c, doc, account, params, option):
    """A talk option that can no longer tell this player anything new is not offered (it would only burn AP)."""
    grants = {e["observation"] for o in option["outcomes"] for e in o["effects"] if e["kind"] == "grant_observation"}
    if not grants: return False
    known = _known(doc, account)
    topic = dialogue_topic(c, params)
    if topic is not None and topic["slip"] is not None and topic["slip"]["observation"] not in known: return False
    return grants <= known


def _flag(doc, name):
    return next(f["value"] for f in doc["public"]["flags"] if f["id"] == name)


def _npc_visible(c, doc, npc):
    concealed = next((n for n in _module(c, "turning_point").get("concealed_npcs", []) if n["character"] == npc["character_id"]), None)
    return concealed is None or _flag(doc, concealed["revealed_flag"])


def _connections(c, doc, location):
    ends = set(next(l["connects"] for l in c["locations"] if l["id"] == location))
    for route in _module(c, "turning_point").get("routes", []):
        if location in route["ends"] and _flag(doc, route["opened_flag"]):
            ends.update(set(route["ends"]) - {location})
    return sorted(ends)


def _theory_mark(doc, theory):
    return next((e for e in reversed(doc["public"]["chronicle"]) if e["kind"] == "version_marked" and e["payload"]["version_id"] == theory), None)


def _predicates(predicates, doc, player, case_doc=None):
    known = _known(doc, player["account_id"])
    board = {r["observation_id"] for r in doc["public"]["board"] if r["observation_id"] is not None}
    flags = {r["id"]: r["value"] for r in doc["public"]["flags"]}
    for pred in predicates:
        kind = pred["kind"]
        if kind.startswith("story_"): ok = story_predicate(pred, story_index(case_doc, doc), player["account_id"], None)
        elif kind == "window_in": ok = pred["from"] <= doc["clock"]["window_idx"] <= pred["to"]
        elif kind == "knows": ok = pred["observation"] in known
        elif kind == "published": ok = pred["observation"] in board
        elif kind == "flag_is": ok = flags[pred["flag"]] == pred["value"]
        elif kind == "at": ok = player["location"] == pred["location"]
        elif kind == "character_active": ok = any(p["character_id"] == pred["character"] and p["status"] in {"active", "fog"} for p in doc["players"]) or any(n["character_id"] == pred["character"] and n["status"] == "active" for n in doc["npcs"])
        else: raise ValueError("unsupported predicate")
        if not ok: return False
    return True


def _validated_intent(intent, doc, actor):
    if isinstance(intent, CommandIntent):
        intent = {"kind": intent.kind, "params": intent.params}
    if type(intent) is not dict or set(intent) != {"kind", "params"}:
        raise ValueError("invalid intent")
    player = _player(doc, actor)
    seq = player["actor_seq"] if player else 0
    cmd = {"command_id": "quote000", "kind": intent["kind"], "params": intent["params"], "window_idx": doc["clock"]["window_idx"], "window_seq": doc["clock"]["window_seq"], "actor_seq": seq}
    return parse_command(cmd, actor, ruleset_version=doc["ruleset_ref"]["version"]).document()["params"]


def _eligibility(case_doc, doc, actor, kind, params, now_utc):
    """The sole visible gate for menu, quote and step; never reads variant/outcomes."""
    player = _player(doc, actor)
    if player is None: return "not_participant", None, None
    clock = doc["clock"]
    if clock["phase"] == "frozen":
        if kind not in {"seen", "forfeit"} or _utc(now_utc) >= _parse(clock["forget_at"]): return "action_unavailable", player, None
    elif clock["phase"] == "finished": return "action_unavailable", player, None
    elif _utc(now_utc) >= _parse(clock["closes_at"]): return "deadline_pending", player, None
    if player["status"] == "departed": return "action_unavailable", player, None
    if kind == "forfeit": return "accepted", player, None
    if kind == "seen": return "accepted", player, None
    if kind == "say":
        if "communication" not in case_doc: return "action_unavailable", player, None
        audience = say_audience(doc, player, params)
        if audience is not None and sent_count(doc, actor.account_id) < case_doc["communication"]["max_messages_per_window"]:
            return "accepted", player, audience
        return "action_unavailable", player, None
    if player["status"] == "ghost": return _ghost_eligibility(case_doc, doc, player, kind, params)
    if kind in GHOST_KINDS: return "action_unavailable", player, None
    if player["status"] == "fog" and kind != "story_reply": return "action_unavailable", player, None
    if kind == "move":
        source = next(l for l in case_doc["locations"] if l["id"] == player["location"])
        target = params["location"]
        ok = target in _connections(case_doc, doc, player["location"]) and target not in {l["location"] for l in doc["public"]["locks"]}
        if ok and player["ap"] >= 1: return "accepted", player, None
    elif kind == "act":
        action = next((a for a in case_doc["actions"] if a["id"] == params["action_id"]), None)
        if action is not None:
            if "personal_step" in action:
                if "personal_tasks" not in case_doc: return "action_unavailable", player, None
                story_step = next(s for s in case_doc["personal_tasks"]["steps"] if s["id"] == action["personal_step"])
                if not step_visible(case_doc, doc, player, story_step): return "action_unavailable", player, None
            used = any(u["account_id"] == actor.account_id and u["action_key"] == action["id"] and (action["repeat"] == "player_game" or u["window_idx"] == clock["window_idx"]) for u in doc["action_uses"])
            if action["location"] == player["location"] and not used and player["ap"] >= 1 and _predicates(action["available_when"], doc, player, case_doc): return "accepted", player, action
    elif kind == "talk":
        dialogue = next((d for d in case_doc["dialogues"] if d["id"] == params["dialogue_id"]), None)
        npc = next((n for n in doc["npcs"] if dialogue and n["character_id"] == dialogue["character"]), None)
        if dialogue and npc and _npc_visible(case_doc, doc, npc) and npc["status"] == "active" and npc["origin"] == "authored" and npc["location"] == player["location"] and player["ap"] >= 1:
            cursor = next((c["node_id"] for c in doc["dialogue_cursors"] if c["account_id"] == actor.account_id and c["dialogue_id"] == dialogue["id"]), dialogue["entry_node"])
            node = next((n for n in dialogue["nodes"] if n["id"] == cursor == params["node_id"]), None)
            option = next((o for o in node["options"] if o["id"] == params["option_id"]), None) if node else None
            if option and _predicates(option["available_when"], doc, player, case_doc) and not _talk_exhausted(case_doc, doc, actor.account_id, params, option): return "accepted", player, option
    elif kind == "story_reply":
        if "personal_tasks" not in case_doc: return "action_unavailable", player, None
        offer = next((o for o in open_offers(case_doc, doc) if o["offer_event_id"] == params["offer_event_id"] and o["recipient_account_id"] == actor.account_id), None)
        if offer:
            step = next(s for s in case_doc["personal_tasks"]["steps"] if s["id"] == offer["step_id"])
            original = next(o for o in case_doc["personal_tasks"]["originals"] if o["id"] == step["operation"]["original"])
            if player["location"] == original["return_location"]: return "accepted", player, offer
    elif kind == "archive_request":
        query = next((q for q in _module(case_doc, "archive_requests").get("queries", []) if q["id"] == params["query_id"]), None)
        used = any(e["kind"] == "archive_requested" and e["audience"]["ids"] == [actor.account_id] and e["payload"]["query_id"] == params["query_id"] for e in doc["private_events"])
        if query and clock["phase"] == "investigation" and 1 <= clock["window_idx"] <= 13 and query["location"] == player["location"] and not used and player["ap"] >= 1 and _predicates(query["available_when"], doc, player, case_doc):
            return "accepted", player, query
    elif kind == "version_mark":
        theory = next((t for t in _module(case_doc, "version_archive").get("theories", []) if t["id"] == params["version_id"]), None)
        mark = _theory_mark(doc, params["version_id"])
        current = mark["payload"]["state"] if mark else "active"
        used = any(e["kind"] == "version_marked" and e["window_idx"] == clock["window_idx"] and e["payload"]["version_id"] == params["version_id"] and e["payload"]["by_account"] == actor.account_id for e in doc["public"]["chronicle"])
        if theory and params["state"] != current and not used:
            return "accepted", player, theory
    elif kind == "pin":
        if any(k["account_id"] == actor.account_id and k["observation_id"] == params["observation_id"] for k in doc["knowledge"]):
            if not any(b["owner_account_id"] == actor.account_id and b["observation_id"] == params["observation_id"] for b in doc["public"]["board"]): return "accepted", player, None
    elif kind == "testimony_ask":
        ghost = next((p for p in doc["players"] if p["character_id"] == params["ghost"] and p["status"] == "ghost"), None)
        repeat = any(q["payload"]["asker_character"] == player["character_id"] and q["payload"]["ghost_character"] == params["ghost"] and _question_open(doc, q, a) for q, a in _questions(doc))
        if _enabled(case_doc, "ghost_testimony") and ghost and not repeat and clock["phase"] == "investigation" and 1 <= clock["window_idx"] <= 13 and player["ap"] >= 1:
            return "accepted", player, ghost
    elif kind == "claim": return "accepted", player, None
    elif kind == "finish_window": return ("action_unavailable" if player["finished_window"] else "accepted"), player, None
    elif kind == "accuse":
        target = params["suspect"]
        alive = any(p["character_id"] == target and p["status"] in {"active", "fog"} for p in doc["players"]) or any(n["character_id"] == target and n["status"] == "active" for n in doc["npcs"])
        ok = clock["phase"] == "investigation" and 3 <= clock["window_idx"] <= 12 and doc["hearing"] is None and player["accusations_used"] < 1 and alive
        if ok and set(params["citations"]) <= {b["id"] for b in doc["public"]["board"]}: return "accepted", player, None
    elif kind == "vote":
        h = doc["hearing"]
        # The accused may object but never support the accusation against their own hero (finding 3).
        own_case = h is not None and player["character_id"] == h["suspect"] and params.get("choice") == "support"
        if h and not own_case and params["hearing_id"] == h["id"] and actor.account_id in h["eligible_accounts"] and set(params["citations"]) <= {b["id"] for b in doc["public"]["board"]}: return "accepted", player, None
    elif kind == "final_vote":
        target = params["suspect"]
        alive = target is None or any(p["character_id"] == target and p["status"] in {"active", "fog"} for p in doc["players"]) or any(n["character_id"] == target and n["status"] == "active" for n in doc["npcs"])
        if clock["phase"] == "final_hearing" and alive and set(params["citations"]) <= {b["id"] for b in doc["public"]["board"]}: return "accepted", player, None
    return "action_unavailable", player, None


def _revision(doc, player, kind, params, case_doc):
    dependencies = {"game": doc["game_id"], "actor": player["account_id"], "window": doc["clock"]["window_seq"], "actor_seq": player["actor_seq"], "status": player["status"], "ap": player["ap"], "location": player["location"]}
    if kind == "say":
        dependencies["sent"] = sent_count(doc, player["account_id"])
        dependencies["participants"] = [{"character_id": cid, "available": any(p["character_id"] == cid and p["status"] in {"active", "fog"} and p["location"] == player["location"] for p in doc["players"])} for cid in params["recipients"]]
        if params["channel"] == "ghost": dependencies["ghost_accounts"] = sorted(p["account_id"] for p in doc["players"] if p["status"] == "ghost")
        preds = []
    elif kind == "act":
        a = next(a for a in case_doc["actions"] if a["id"] == params["action_id"])
        dependencies["repeat"] = [u for u in doc["action_uses"] if u["account_id"] == player["account_id"] and u["action_key"] == a["id"]]
        if "personal_step" in a:
            step = next(s for s in case_doc["personal_tasks"]["steps"] if s["id"] == a["personal_step"])
            own = completed_steps(case_doc, doc, player["account_id"])
            relevant = set(step["requires"]) | {step["id"]} | {s["id"] for s in case_doc["personal_tasks"]["steps"] if step["choice_group"] and s["choice_group"] == step["choice_group"]}
            dependencies["personal_completed"] = sorted(own & relevant)
            dependencies["personal_offered"] = any(e["kind"] == "return_offered" and e["account_id"] == player["account_id"] and e["step_id"] == step["id"] for _, e in story_index(case_doc, doc).entries)
        preds = a["available_when"]
    elif kind == "story_reply":
        dependencies["open_offer"] = next((o for o in open_offers(case_doc, doc) if o["offer_event_id"] == params["offer_event_id"] and o["recipient_account_id"] == player["account_id"]), None)
        preds = []
    elif kind == "archive_request":
        q = next(q for q in _module(case_doc, "archive_requests")["queries"] if q["id"] == params["query_id"])
        dependencies["repeat"] = [e["event_id"] for e in doc["private_events"] if e["kind"] == "archive_requested" and e["audience"]["ids"] == [player["account_id"]] and e["payload"]["query_id"] == q["id"]]
        preds = q["available_when"]
    elif kind == "version_mark":
        mark = _theory_mark(doc, params["version_id"])
        dependencies["theory"] = mark
        dependencies["repeat"] = any(e["kind"] == "version_marked" and e["window_idx"] == doc["clock"]["window_idx"] and e["payload"]["version_id"] == params["version_id"] and e["payload"]["by_account"] == player["account_id"] for e in doc["public"]["chronicle"])
        preds = []
    elif kind == "talk":
        d = next(d for d in case_doc["dialogues"] if d["id"] == params["dialogue_id"])
        dependencies["cursor"] = next((c["node_id"] for c in doc["dialogue_cursors"] if c["account_id"] == player["account_id"] and c["dialogue_id"] == d["id"]), d["entry_node"])
        dependencies["npc"] = next({"status": n["status"], "location": n["location"], "origin": n["origin"]} for n in doc["npcs"] if n["character_id"] == d["character"])
        preds = next(o["available_when"] for n in d["nodes"] if n["id"] == params["node_id"] for o in n["options"] if o["id"] == params["option_id"])
    elif kind == "ghost_whisper":
        dependencies["recipient"] = next((p["status"] for p in doc["players"] if p["character_id"] == params["recipient"]), None)
        dependencies["public"] = any(o["observation_id"] == params["observation_id"] for o in doc["public"]["observations"]) or any(b["observation_id"] == params["observation_id"] for b in doc["public"]["board"])
        preds = []
    elif kind == "testimony_ask":
        dependencies["ghost"] = next((p["status"] for p in doc["players"] if p["character_id"] == params["ghost"]), None)
        dependencies["open"] = [q["event_id"] for q, a in _questions(doc) if q["payload"]["asker_character"] == player["character_id"] and q["payload"]["ghost_character"] == params["ghost"] and _question_open(doc, q, a)]
        preds = []
    elif kind == "testimony_answer":
        dependencies["answered"] = any(a is not None for q, a in _questions(doc) if q["event_id"] == params["question_event_id"])
        preds = []
    elif kind == "ghost_sign":
        dependencies["shown"] = params["sign_id"] in _shown_signs(doc)
        preds = []
    else: preds = []
    dependencies["predicates"] = [{"predicate": p, "satisfied": _predicates([p], doc, player, case_doc)} for p in preds]
    if kind == "move": dependencies["locked"] = params["location"] in {l["location"] for l in doc["public"]["locks"]}
    if kind in {"accuse", "vote", "final_vote"}:
        visible_board_ids = {b["id"] for b in doc["public"]["board"]}
        dependencies["board_ids"] = [{"id": x, "exists": x in visible_board_ids} for x in params["citations"]]
    if kind in {"vote", "accuse"}: dependencies["hearing"] = None if doc["hearing"] is None else doc["hearing"]["id"]
    return canonical_hash(dependencies)


def _validated(state, case, rules):
    if type(state) is KernelState: return state.validated_for(case, rules)
    return KernelState.from_document(state.document(), case, rules)


def quote_action(case, rules, state, actor, intent, *, now_utc):
    if not isinstance(actor, PlayerActor): raise ValueError("not_participant")
    doc, case_doc = _validated(state, case, rules).document(), _case_doc(case)
    return _quote_from_documents(rules, doc, case_doc, actor, intent, now_utc=now_utc)


def _quote_from_documents(rules, doc, case_doc, actor, intent, *, now_utc):
    """Materialize one quote from documents already validated by the owning public API."""
    params = _validated_intent(intent, doc, actor)
    kind = intent.kind if isinstance(intent, CommandIntent) else intent["kind"]
    code, player, _ = _eligibility(case_doc, doc, actor, kind, params, now_utc)
    if code != "accepted": raise ValueError(code)
    target_key = {"story_reply": "offer_event_id", "archive_request": "query_id", "version_mark": "version_id", "move": "location", "act": "action_id", "talk": "option_id", "pin": "observation_id", "ghost_share": "observation_id", "ghost_whisper": "recipient", "testimony_answer": "question_event_id", "ghost_sign": "sign_id", "accuse": "suspect", "vote": "hearing_id", "final_vote": "suspect"}.get(kind)
    target = params.get(target_key) if target_key else kind
    if kind in {"claim", "say", "testimony_ask"}: target = kind + ":" + canonical_hash(params)[0:24]
    if target is None: target = "abstain"
    selection = canonical_hash({"kind": kind, "params": params})[:24]
    cost = rules.move_cost if kind == "move" else rules.act_cost if kind in {"act", "archive_request", "testimony_ask"} else rules.talk_cost if kind == "talk" else 0
    if kind == "say": cost = 1 if params["channel"] == "whisper" else 0
    resource_id = "case:" + canonical_hash({"game": doc["game_id"], "actor": actor.account_id, "kind": kind})[:32]
    return LegalAction(selection, kind, str(target), cost, resource_id, params, _revision(doc, player, kind, params, case_doc))


def available_actions(case, rules, state, viewer, *, now_utc):
    if not isinstance(viewer, PlayerActor): return ()
    doc, c = _validated(state, case, rules).document(), _case_doc(case)
    player = _player(doc, viewer)
    if player is None: return ()
    intents = []
    for l in c["locations"]: intents.append(("move", {"location": l["id"]}, l["name"]))
    for a in c["actions"]: intents.append(("act", {"action_id": a["id"]}, a["label"]))
    if "personal_tasks" in c:
        for offer in open_offers(c, doc):
            if offer["recipient_account_id"] == viewer.account_id:
                for accept in (True, False): intents.append(("story_reply", {"offer_event_id": offer["offer_event_id"], "accept": accept}, "Принять письмо" if accept else "Отклонить письмо"))
    for q in _module(c, "archive_requests").get("queries", []): intents.append(("archive_request", {"query_id": q["id"]}, q["label"]))
    for t in _module(c, "version_archive").get("theories", []):
        mark = _theory_mark(doc, t["id"])
        mark_state = "active" if mark and mark["payload"]["state"] == "archived" else "archived"
        intents.append(("version_mark", {"version_id": t["id"], "state": mark_state}, t["title"]))
    for d in c["dialogues"]:
        node_id = next((x["node_id"] for x in doc["dialogue_cursors"] if x["account_id"] == viewer.account_id and x["dialogue_id"] == d["id"]), d["entry_node"])
        for n in d["nodes"]:
            if n["id"] == node_id:
                for o in n["options"]: intents.append(("talk", {"dialogue_id": d["id"], "node_id": node_id, "option_id": o["id"]}, o["label"]))
    for k in doc["knowledge"]:
        if k["account_id"] == viewer.account_id:
            intents.append(("pin", {"observation_id": k["observation_id"]}, "Опубликовать улику"))
    character = next(item for item in c["characters"] if item["id"] == player["character_id"])
    for observation_id in sorted(_known(doc, viewer.account_id) & set(character["ghost_memories"])):
        intents.append(("ghost_share", {"observation_id": observation_id}, "Поделиться воспоминанием"))
    if player["status"] == "ghost":
        own = sorted({k["observation_id"] for k in doc["knowledge"] if k["account_id"] == viewer.account_id} & set(character["ghost_memories"]))
        living = sorted(p["character_id"] for p in doc["players"] if p["account_id"] != viewer.account_id and p["status"] in {"active", "fog"})
        for observation_id in own:
            for recipient in living: intents.append(("ghost_whisper", {"observation_id": observation_id, "recipient": recipient}, "Передать лично"))
        for question, answer in _questions(doc):
            if question["payload"]["ghost_character"] == player["character_id"]:
                for value, label in (("yes", "Ответить «да»"), ("no", "Ответить «нет»")): intents.append(("testimony_answer", {"question_event_id": question["event_id"], "answer": value}, label))
        for sign in _module(c, "ghost_visions").get("signs", []):
            if sign["character"] == player["character_id"]: intents.append(("ghost_sign", {"sign_id": sign["id"]}, sign["label"]))
    intents += [("seen", {}, "Я здесь"), ("finish_window", {}, "Завершить окно"), ("forfeit", {}, "Покинуть дело")]
    entries = []
    for kind, params, label in intents:
        try: quote = _quote_from_documents(rules, doc, c, viewer, CommandIntent(kind, params), now_utc=now_utc)
        except ValueError: continue
        entries.append(MenuChoice("choice", quote.selection_id, label, quote))
    board_ids = tuple(b["id"] for b in doc["public"]["board"])
    subjects = tuple(c["id"] for c in c["characters"] if any(p["character_id"] == c["id"] and p["status"] in {"active", "fog"} for p in doc["players"]) or any(n["character_id"] == c["id"] and n["status"] == "active" for n in doc["npcs"]))
    for kind, params in (("claim", {"text": "x"}), ("accuse", {"suspect": subjects[0], "citations": []}) if subjects else ("accuse", {"suspect": "none", "citations": []}), ("vote", {"hearing_id": doc["hearing"]["id"], "choice": "oppose", "citations": []}) if doc["hearing"] else ("vote", {"hearing_id": "none", "choice": "oppose", "citations": []}), ("final_vote", {"suspect": None, "citations": []})):
        if _eligibility(c, doc, viewer, kind, params, now_utc)[0] == "accepted":
            entries.append(MenuForm("form", kind, kind, kind, 0, subjects if kind in {"accuse", "final_vote"} else (), board_ids if kind != "claim" else (), doc["hearing"]["id"] if kind == "vote" else None))
    if _enabled(c, "ghost_testimony"):
        askable = tuple(sorted(p["character_id"] for p in doc["players"] if p["status"] == "ghost" and _eligibility(c, doc, viewer, "testimony_ask", {"ghost": p["character_id"], "text": "x"}, now_utc)[0] == "accepted"))
        if askable: entries.append(MenuForm("form", "testimony_ask", "testimony_ask", "testimony_ask", rules.act_cost, askable, (), None))
    if "communication" in c:
        nearby = tuple(sorted(p["character_id"] for p in doc["players"] if p["account_id"] != viewer.account_id and p["status"] in {"active", "fog"} and p["location"] == player["location"]))
        samples = [("square", [], ()), ("ghost", [], ())]
        if nearby: samples.append(("whisper", [nearby[0]], nearby))
        for channel, recipients, targets in samples:
            if _eligibility(c, doc, viewer, "say", {"channel": channel, "recipients": recipients, "text": "x"}, now_utc)[0] == "accepted":
                entries.append(SayForm("form", "say:" + channel, {"square": "Площадь", "whisper": "Приватная беседа", "ghost": removed_label(c)}[channel], "say", channel, int(channel == "whisper"), targets))
    return tuple(entries)


def project(case, rules, state, viewer=None):
    doc, c = _validated(state, case, rules).document(), _case_doc(case)
    player = _player(doc, viewer) if isinstance(viewer, PlayerActor) else None
    content_observations = {o["id"]: o for o in c["observations"]}
    item_art = {i["id"]: i["art"] for i in c.get("items", []) if i.get("art")}
    def materialized(oid, source):
        content = content_observations[oid]
        item = {"observation_id": oid, "kind": content["kind"], "title": content["title"], "body": copy.deepcopy(content["body"]), "source": copy.deepcopy(source)}
        if content["kind"] == "claim": item["speaker"] = content["speaker"]
        # A record about an item shows the item's picture (the client draws it in the evidence frame).
        subject_item = (content.get("subject") or {}).get("item")
        if subject_item in item_art: item["art"] = copy.deepcopy(item_art[subject_item])
        return item
    public_final = None if doc["final"] is None else {"code": doc["final"]["code"], "at": doc["final"]["at"]}
    board = copy.deepcopy(doc["public"]["board"])
    for entry in board:
        entry["observation"] = materialized(entry["observation_id"], entry["source"]) if entry["observation_id"] is not None else None
    result = {"game_id": doc["game_id"], "case_id": case.case_id, "clock": copy.deepcopy(doc["clock"]), "flags": copy.deepcopy(doc["public"]["flags"]), "locks": copy.deepcopy(doc["public"]["locks"]), "observations": [materialized(o["observation_id"], o["source"]) for o in doc["public"]["observations"]], "board": board, "chronicle": copy.deepcopy(doc["public"]["chronicle"]), "players": [{"account_id": p["account_id"], "character_id": p["character_id"], "name": p["name"], "status": p["status"]} for p in doc["players"]], "npcs": [{"character_id": n["character_id"], "name": n["name"], "status": n["status"]} for n in doc["npcs"]], "hearing": copy.deepcopy(doc["hearing"]), "final": public_final}
    result["clock"].pop("resume_receipts", None)
    # Case events may carry a public picture; the kernel event keeps only its id and text.
    scene_art = {e["id"]: e["art"] for e in [*c["events"], *_module(c, "turning_point").get("scenes", [])] if e.get("art")}
    for entry in result["chronicle"]:
        if entry["kind"] == "scene" and entry["payload"]["content_event_id"] in scene_art:
            entry["art"] = copy.deepcopy(scene_art[entry["payload"]["content_event_id"]])
    if result["hearing"]: result["hearing"].pop("votes", None)
    if player:
        character = next(x for x in c["characters"] if x["id"] == player["character_id"])
        variant = doc["sealed"]["variant_id"]
        secrets = [s["body"] for s in character["secrets"] if s["variants"] == "all" or variant in s["variants"]]
        selected = next(v for v in c["variants"] if v["id"] == variant)
        is_shadow = player["character_id"] == selected["culprit"] or player["character_id"] in selected["accomplices"]
        truth = {key: copy.deepcopy(selected[key]) for key in ("culprit", "accomplices", "motive", "method")} if is_shadow else None
        result["self"] = {"account_id": player["account_id"], "character_id": player["character_id"], "status": player["status"], "location": player["location"], "ap": player["ap"], "finished_window": player["finished_window"], "final_ballot": copy.deepcopy(next((b for b in doc.get("final_ballots", []) if b["account_id"] == player["account_id"]), None)), "actor_seq": player["actor_seq"], "knowledge_revision": player["knowledge_revision"], "faction": "shadow" if is_shadow else character["faction"], "goal": copy.deepcopy(character["goal"]), "secrets": copy.deepcopy(secrets), "truth": truth, "knowledge": copy.deepcopy([k for k in doc["knowledge"] if k["account_id"] == viewer.account_id]), "observations": [materialized(k["observation_id"], k["source"]) for k in doc["knowledge"] if k["account_id"] == viewer.account_id], "private_events": copy.deepcopy([e for e in doc["private_events"] if viewer.account_id in e["audience"]["ids"]]), "receipts": [{key: copy.deepcopy(r[key]) for key in ("command_id", "accepted", "code", "actor_revision", "result_ref")} for r in doc["receipts"] if r["actor_key"] == viewer.actor_key], "dialogue_cursors": copy.deepcopy([x for x in doc["dialogue_cursors"] if x["account_id"] == viewer.account_id]), "nearby": [{"character_id": x["character_id"], "name": x["name"], "controller": "player"} for x in doc["players"] if x["location"] == player["location"] and x["status"] != "departed"] + [{"character_id": x["character_id"], "name": x["name"], "controller": "npc"} for x in doc["npcs"] if x["location"] == player["location"] and x["status"] == "active" and _npc_visible(c, doc, x)]}
        if doc["final"] is not None:
            # «Who was who» once the case is closed: every seat's hero and side, the culprit and accomplices by role.
            def part(char):
                return "culprit" if char == selected["culprit"] else "accomplice" if char in selected["accomplices"] else None
            def side(char):
                return "shadow" if part(char) else next(x for x in c["characters"] if x["id"] == char)["faction"]
            cast = [{"character_id": p["character_id"], "account_id": p["account_id"], "controller": "player", "faction": side(p["character_id"]), "part": part(p["character_id"])} for p in doc["players"]]
            seated = {p["character_id"] for p in doc["players"]}
            cast += [{"character_id": char, "account_id": None, "controller": "npc", "faction": "shadow", "part": part(char)} for char in [selected["culprit"], *selected["accomplices"]] if char not in seated]
            result["self"]["postmortem"] = {**copy.deepcopy(doc["final"]), "ending": copy.deepcopy(c["endings"][doc["final"]["code"]]), "variant_final_text": copy.deepcopy(selected["final_text"]) if doc["final"]["code"] in {"solved", "unresolved"} else None, "variant_art": copy.deepcopy(selected.get("art")) if doc["final"]["code"] in {"solved", "unresolved"} else None, "cast": cast}
    if c["ruleset_ref"]["version"] == 2:
        result["locations"] = [{"id": l["id"], "name": l["name"], "body": copy.deepcopy(l["body"]), "art": copy.deepcopy(l.get("art")), "connects": _connections(c, doc, l["id"])} for l in sorted(c["locations"], key=lambda x: x["id"])]
        result["modules"] = {}
        if player: result["self"]["modules"] = {}
        archive = _module(c, "version_archive")
        published = {o["observation_id"] for o in doc["public"]["observations"]} | {b["observation_id"] for b in doc["public"]["board"] if b["observation_id"]}
        if archive:
            theories = []
            for t in sorted(archive["theories"], key=lambda x: x["id"]):
                mark = _theory_mark(doc, t["id"])
                theories.append({"id": t["id"], "title": t["title"], "body": copy.deepcopy(t["body"]), "state": mark["payload"]["state"] if mark else "active", "links": [{"observation_id": link["observation"], "relation": link["relation"]} for link in sorted(t["links"], key=lambda x: x["observation"]) if link["observation"] in published]})
            result["modules"]["version_archive"] = {"theories": theories}
            if player:
                known = _known(doc, player["account_id"])
                docs = [d for d in sorted(archive["documents"], key=lambda x: x["id"]) if d["observation"] in known]
                ids = {d["id"] for d in docs}
                result["self"]["modules"]["version_archive"] = {"documents": [{"id": d["id"], "family": d["family"], "revision": d["revision"], "observation_id": d["observation"]} for d in docs], "comparisons": [copy.deepcopy(x) for x in sorted(archive["comparisons"], key=lambda x: x["id"]) if x["left"] in ids and x["right"] in ids]}
        turning = _module(c, "turning_point")
        if turning:
            result["modules"]["turning_point"] = {"routes": [{"id": r["id"], "ends": list(r["ends"])} for r in sorted(turning["routes"], key=lambda x: x["id"]) if _flag(doc, r["opened_flag"])], "discoveries": [{"event_id": e["event_id"], "character_id": e["payload"]["character_id"], "location": e["payload"]["location"], "window_idx": e["window_idx"]} for e in doc["public"]["chronicle"] if e["kind"] == "npc_revealed"]}
        if player and _module(c, "archive_requests"):
            own = [e for e in doc["private_events"] if e["audience"]["ids"] == [player["account_id"]]]
            requests = []
            for e in own:
                if e["kind"] != "archive_requested": continue
                response = next((r for r in own if r["kind"] == "archive_response" and r["payload"]["request_event_id"] == e["event_id"]), None)
                requests.append({"request_event_id": e["event_id"], "query_id": e["payload"]["query_id"], "due_window": e["payload"]["due_window"], "status": response["payload"]["disposition"] if response else "cancelled_terminal" if doc["final"] else "pending", "response_event_id": response["event_id"] if response else None})
            result["self"]["modules"]["archive_requests"] = {"requests": sorted(requests, key=lambda x: x["query_id"])}
        if _enabled(c, "ghost_testimony"):
            result["modules"]["ghost_testimony"] = {"questions": [{"question_event_id": q["event_id"], "asker_character": q["payload"]["asker_character"], "ghost_character": q["payload"]["ghost_character"], "text": q["payload"]["text"], "window_idx": q["window_idx"], "answer_by": q["payload"]["answer_by"], "answer": a["payload"]["answer"] if a else None, "status": "answered" if a else "open" if _question_open(doc, q, a) else "expired"} for q, a in _questions(doc)]}
        if _enabled(c, "ghost_visions"):
            result["modules"]["ghost_visions"] = {"signs": [{"event_id": e["event_id"], "sign_id": e["payload"]["sign_id"], "character_id": e["payload"]["character_id"], "location": e["payload"]["location"], "window_idx": e["window_idx"], "body": copy.deepcopy(e["payload"]["body"])} for e in doc["public"]["chronicle"] if e["kind"] == "ghost_sign"]}
        if player and _enabled(c, "ghost_whisper"):
            own = [e for e in doc["private_events"] if e["audience"]["ids"] == [player["account_id"]]]
            result["self"]["modules"]["ghost_whisper"] = {"sent": [{"event_id": e["event_id"], "observation_id": e["payload"]["observation_id"], "recipient_character": e["payload"]["recipient_character"], "window_idx": e["window_idx"]} for e in own if e["kind"] == "ghost_whispered"],
                                                          "received": [{"event_id": e["event_id"], "observation_id": e["payload"]["observation_id"], "from_character": e["payload"]["from_character"], "window_idx": e["window_idx"]} for e in own if e["kind"] == "ghost_whisper_received"]}
    if player and "communication" in c:
        sent = sent_count(doc, player["account_id"])
        limit = c["communication"]["max_messages_per_window"]
        result["self"]["communication"] = {"max_messages_per_window": limit, "sent_this_window": sent, "remaining": limit - sent}
    if player and "personal_tasks" in c:
        own = completed_steps(c, doc, player["account_id"])
        char = next(x for x in c["characters"] if x["id"] == player["character_id"])
        result["self"]["personal"] = {"criteria": copy.deepcopy(char["goal"].get("criteria", char["goal"]["body"])), "completed_steps": sorted(own), "pending_returns": sorted(o["offer_event_id"] for o in open_offers(c, doc) if o["recipient_account_id"] == player["account_id"]), "booked_trips": sorted(s["operation"]["trip"] for s in c["personal_tasks"]["steps"] if s["id"] in own and s["operation"]["kind"] == "book_departure"), "work_progress": [{"work": w["id"], "completed_stages": work_progress(c, doc, player["account_id"], w["id"])} for w in sorted(c["personal_tasks"]["works"], key=lambda x: x["id"]) if w["owner"] == player["character_id"]], "lost_observations": sorted({s["observation"] for o in c["personal_tasks"]["originals"] if original_state(c, doc, o["id"])[0] == "destroyed" for s in o["sections"]} & _known(doc, player["account_id"]))}
    # Appearance of the party: the kernel keeps raw templates, the projection renders them for these looks.
    renderer = Renderer(c, doc, player["character_id"] if player else None)
    result["looks"] = {cid: public_look(look) for cid, look in sorted(renderer.looks.items())}
    if player:
        own_look = renderer.looks[player["character_id"]]
        result["self"]["role"] = {"id": player["character_id"], "look_id": own_look["id"], "title": own_look["title"], "title_forms": copy.deepcopy(own_look["title_forms"]), "gender": own_look["gender"], "age": own_look["age"], "bio": copy.deepcopy(own_look["bio"]), "art": copy.deepcopy(own_look["art"])}
    return renderer.tree(result)
