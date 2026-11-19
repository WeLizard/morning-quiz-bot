"""Pure derived story data; no clocks, commands, codec, or terminal policy."""
from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class StoryIndex:
    _case_json: str
    _state_json: str

    @property
    def case(self): return json.loads(self._case_json)

    @property
    def state(self): return json.loads(self._state_json)

    @property
    def entries(self):
        return tuple((b["seq"], MappingProxyType(e)) for b in self.state.get("personal_story", {}).get("journal", []) for e in b["entries"])


def story_index(case, state):
    case = case.document() if hasattr(case, "document") else case
    state = state.document() if hasattr(state, "document") else state
    return StoryIndex(json.dumps(case, ensure_ascii=False), json.dumps(state, ensure_ascii=False))


def validate_story(case, state):
    from .night_case_personal_state import validate_personal_state
    validate_personal_state(case, state)


def story_predicate(predicate, index, account_id, cutoff_seq=None):
    entries = index.entries
    closed = next((seq for seq, e in entries if e["kind"] == "actor_closed" and e["account_id"] == account_id), None)
    cutoff = min(x for x in (cutoff_seq, closed, 2049) if x is not None)
    entries = [(seq, e) for seq, e in entries if seq <= cutoff]
    def done(step): return next((seq for seq, e in entries if e["kind"] == "step_done" and e["account_id"] == account_id and e["step_id"] == step), None)
    def reveal(topic, by): return [seq for seq, e in entries if e["kind"] == "public_reveal" and e["topic_id"] == topic and (by == "any" or e["publisher_account_id"] == account_id)]
    kind = predicate["kind"]
    if kind == "story_done": return done(predicate["step"]) is not None
    if kind == "story_any_done": return any(done(step) is not None for step in predicate["steps"])
    if kind == "story_unexposed": return not reveal(predicate["topic"], predicate["by"])
    if kind == "story_departed": return any(e["kind"] == "departed_epilogue" and e["account_id"] == account_id and e["trip_id"] == predicate["trip"] for _, e in entries)
    if kind == "story_before":
        seq = done(predicate["step"])
        if seq is None: return False
        boundary = predicate["boundary"]
        if boundary["kind"] == "public_reveal": boundaries = reveal(boundary["topic"], boundary["by"])
        else:
            steps = {s["id"]: s for s in index.case["personal_tasks"]["steps"]}
            boundaries = [n for n, e in entries if e["kind"] == "step_done" and e["account_id"] != account_id and steps[e["step_id"]]["operation"]["kind"] == "inspect_original" and steps[e["step_id"]]["operation"]["original"] == boundary["original"]]
        return not boundaries or seq < min(boundaries)
    raise ValueError("unsupported story predicate")


def completed_steps(c, doc, account):
    return {e["step_id"] for _, e in story_index(c, doc).entries if e["kind"] == "step_done" and e["account_id"] == account}


def open_offers(c, doc):
    entries = story_index(c, doc).entries
    answered = {e["offer_event_id"] for _, e in entries if e["kind"] == "return_answered"}
    return [dict(e) for _, e in entries if e["kind"] == "return_offered" and e["offer_event_id"] not in answered]


def original_state(c, doc, original_id):
    original = next(o for o in c["personal_tasks"]["originals"] if o["id"] == original_id)
    status = "held" if original["initial_holder"] else "at_source"
    holder = original["initial_holder"]
    steps = {s["id"]: s for s in c["personal_tasks"]["steps"]}
    chars = {p["account_id"]: p["character_id"] for p in doc["players"]}
    offers = {}
    for _, e in story_index(c, doc).entries:
        if e["kind"] == "return_offered" and steps[e["step_id"]]["operation"].get("original") == original_id:
            status, holder = "offered", None
            offers[e["offer_event_id"]] = True
        elif e["kind"] == "return_answered" and e["offer_event_id"] in offers:
            status = {"accepted": "delivered", "declined": "declined", "cancelled": "cancelled"}[e["decision"]]
        elif e["kind"] == "step_done":
            op = steps[e["step_id"]]["operation"]
            if op.get("original") != original_id: continue
            if op["kind"] == "take_original": status, holder = "held", chars[e["account_id"]]
            elif op["kind"] == "destroy_original": status, holder = "destroyed", None
    return status, holder


def step_visible(c, doc, player, step):
    own = completed_steps(c, doc, player["account_id"])
    if player["character_id"] not in step["actors"] or step["id"] in own or not set(step["requires"]) <= own: return False
    if any(e["kind"] == "return_offered" and e["step_id"] == step["id"] and e["account_id"] == player["account_id"] for _, e in story_index(c, doc).entries): return False
    if step["choice_group"] and any(s["id"] in own and s["choice_group"] == step["choice_group"] for s in c["personal_tasks"]["steps"]): return False
    op = step["operation"]
    own_target = {"book_departure": "trip", "issue_commitment": "commitment"}.get(op["kind"])
    if own_target and any(s["id"] in own and s["operation"]["kind"] == op["kind"] and s["operation"][own_target] == op[own_target] for s in c["personal_tasks"]["steps"]):
        return False
    if op["kind"] == "advance_work":
        work = next(w for w in c["personal_tasks"]["works"] if w["id"] == op["work"])
        stages = work_progress(c, doc, player["account_id"], work["id"])
        if work["stages"][len(stages):len(stages)+1] != [op["stage"]]: return False
    if op["kind"] == "book_departure":
        trip = next(t for t in c["personal_tasks"]["trips"] if t["id"] == op["trip"])
        work = next(w for w in c["personal_tasks"]["works"] if w["id"] == trip["work"])
        if work_progress(c, doc, player["account_id"], work["id"]) != work["stages"]: return False
    return True


def work_progress(c, doc, account, work):
    own = completed_steps(c, doc, account)
    stages = {s["operation"]["stage"] for s in c["personal_tasks"]["steps"] if s["id"] in own and s["operation"]["kind"] == "advance_work" and s["operation"]["work"] == work}
    return [stage for w in c["personal_tasks"]["works"] if w["id"] == work for stage in w["stages"] if stage in stages]


def record_story(doc, entry):
    doc["personal_story"]["journal"][-1]["entries"].append(entry)


def publication(c, doc, observation, publisher, event_id):
    if "personal_tasks" not in c: return
    for topic in c["personal_tasks"]["topics"]:
        if observation not in topic["observations"]: continue
        if any(e["kind"] == "public_reveal" and e["topic_id"] == topic["id"] and e["publisher_account_id"] == publisher for _, e in story_index(c, doc).entries): continue
        record_story(doc, {"kind": "public_reveal", "topic_id": topic["id"], "publisher_account_id": publisher, "event_id": event_id})
