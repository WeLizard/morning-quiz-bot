"""Bounded, oracle-guided validation through the production Night City kernel.

The planner knows sealed authored truth. This proves a cooperative route exists,
not that players can deduce it or win against sabotage.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from .night_case_engine import _initialize, step
from .night_case_projection import CommandIntent, MenuChoice, _predicates, available_actions, quote_action
from .night_case_state import PlayerActor, SystemActor, canonical_hash, encode_state, engine_build_for

SCHEMA = "night-city-witness/1"
MESSAGE_SCHEMA = "night-city-witness/2"
DEFAULT_START = "2000-01-03T08:00:00Z"
MAX_WITNESS_BYTES = 16 * 1024 * 1024
MAX_WITNESS_STEPS = 5000
ASSUMPTIONS = ("oracle-guided cooperative reachability", "all human players including shadow cooperate",
               "authored culprit and proof IDs guide the planner; kernel alone authorizes effects",
               "bounded heuristic; no exhaustive search or human deduction claim")


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result: raise ValueError("duplicate witness field")
        result[key] = value
    return result


def _exact(doc, fields):
    if type(doc) is not dict or set(doc) != set(fields): raise ValueError("invalid witness fields")


def _timestamp(value):
    if type(value) is not str or not value.endswith("Z"): raise ValueError("invalid UTC timestamp")
    try: result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc: raise ValueError("invalid UTC timestamp") from exc
    if result.tzinfo is None or result.utcoffset().total_seconds() != 0: raise ValueError("invalid UTC timestamp")
    return result


def _stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class SearchBudget:
    max_commands: int = 2000
    max_states: int = 5000
    max_seconds: float = 10.0

    def __post_init__(self):
        for name in ("max_commands", "max_states"):
            value = getattr(self, name)
            if type(value) is not int or value < 1: raise ValueError("invalid search budget")
        if type(self.max_seconds) not in (int, float) or not 0 < self.max_seconds < float("inf"):
            raise ValueError("invalid search budget")


@dataclass(frozen=True, slots=True)
class Witness:
    _bytes: bytes

    @classmethod
    def from_document(cls, value):
        if type(value) is not dict: raise ValueError("invalid witness fields")
        schema = value.get("schema")
        if schema not in {SCHEMA, MESSAGE_SCHEMA}: raise ValueError("unsupported witness version")
        fields = {"schema", "case_id", "case_version", "case_hash", "rules_hash", "compiler_version",
                  "engine_version", "composition_id", "variant_id", "seed", "roster", "input_hash",
                  "game_id", "start_at", "steps", "final_code", "trace_hash"}
        _exact(value, fields)
        if type(value["case_version"]) is not int or value["case_version"] < 0 or type(value["seed"]) is not int or value["seed"] < 0:
            raise ValueError("invalid witness integer")
        for field in ("case_id", "compiler_version", "engine_version", "composition_id", "variant_id", "game_id", "final_code"):
            if type(value[field]) is not str or not value[field]: raise ValueError("invalid witness identity")
        for field in ("case_hash", "rules_hash", "input_hash", "trace_hash"):
            if type(value[field]) is not str or len(value[field]) != 64 or any(c not in "0123456789abcdef" for c in value[field]):
                raise ValueError("invalid witness hash")
        _timestamp(value["start_at"])
        roster = value["roster"]
        _exact(roster, ("players", "npc_name_pool"))
        if type(roster["players"]) is not list or type(roster["npc_name_pool"]) is not list: raise ValueError("invalid roster")
        for player in roster["players"]:
            _exact(player, ("account_id", "display_name"))
            if any(type(x) is not str or not x for x in player.values()): raise ValueError("invalid roster")
        if any(type(x) is not str or not x for x in roster["npc_name_pool"]): raise ValueError("invalid roster")
        if type(value["steps"]) is not list or len(value["steps"]) > MAX_WITNESS_STEPS: raise ValueError("invalid witness steps")
        for item in value["steps"]:
            step_fields = {"actor", "command", "now_utc", "expected_receipt", "state_hash"}
            if schema == MESSAGE_SCHEMA: step_fields.add("expected_messages")
            _exact(item, step_fields)
            actor = item["actor"]
            if type(actor) is not dict or not (set(actor) == {"kind"} and actor["kind"] == "system" or
                                                  set(actor) == {"kind", "account_id"} and actor["kind"] == "player" and type(actor["account_id"]) is str):
                raise ValueError("invalid trusted actor")
            if type(item["command"]) is not dict: raise ValueError("invalid command")
            _exact(item["expected_receipt"], ("accepted", "code", "actor_revision"))
            _timestamp(item["now_utc"])
            if type(item["state_hash"]) is not str or len(item["state_hash"]) != 64 or any(c not in "0123456789abcdef" for c in item["state_hash"]):
                raise ValueError("invalid state hash")
            if schema == MESSAGE_SCHEMA:
                messages = item["expected_messages"]
                if type(messages) is not list or len(messages) > 1: raise ValueError("invalid witness messages")
                for message in messages:
                    _exact(message, {"id", "channel", "thread_key", "sender_account_id",
                                     "recipient_account_ids", "window_idx", "text", "text_hash"})
                    if any(type(message[k]) is not str for k in ("id", "channel", "thread_key", "sender_account_id", "text", "text_hash")):
                        raise ValueError("invalid witness message")
                    if type(message["window_idx"]) is not int or not 1 <= message["window_idx"] <= 14:
                        raise ValueError("invalid witness message window")
                    recipients = message["recipient_account_ids"]
                    if type(recipients) is not list or not 1 <= len(recipients) <= 12 or any(type(r) is not str or not r for r in recipients):
                        raise ValueError("invalid witness recipients")
        raw = _json(value)
        if len(raw) > MAX_WITNESS_BYTES: raise ValueError("witness too large")
        return cls(raw)

    @classmethod
    def from_json(cls, raw):
        if type(raw) is not bytes: raise ValueError("witness must be bytes")
        if len(raw) > MAX_WITNESS_BYTES: raise ValueError("witness too large")
        try: value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite witness")))
        except (UnicodeError, json.JSONDecodeError) as exc: raise ValueError("invalid witness JSON") from exc
        return cls.from_document(value)

    def document(self): return json.loads(self._bytes)
    def to_json(self): return bytes(self._bytes)


@dataclass(frozen=True, slots=True)
class ReplayResult:
    passed: bool
    code: str
    state_hash: str | None
    final_code: str | None


@dataclass(frozen=True, slots=True)
class SearchResult:
    status: str
    witness: Witness | None
    reason: str
    commands: int
    states: int
    elapsed_seconds: float
    assumptions: tuple[str, ...] = ASSUMPTIONS
    search_elapsed_seconds: float = 0.0
    replay_elapsed_seconds: float = 0.0
    budget_scope: str = "between_commands"


@dataclass(frozen=True, slots=True)
class MatrixReport:
    results: tuple[SearchResult, ...]
    scope_passed: bool
    assumptions: tuple[str, ...] = ASSUMPTIONS


@dataclass(frozen=True, slots=True)
class PolicyResult:
    policy: str
    status: str
    final_code: str | None
    passed: bool
    reason: str
    commands: int
    elapsed_seconds: float


def _state_hash(state): return hashlib.sha256(encode_state(state)).hexdigest()


def _roster(case, composition_id):
    c = case.document()
    comp = next((x for x in c["compositions"] if x["id"] == composition_id), None)
    if comp is None: raise ValueError("unknown composition")
    return {"players": [{"account_id": f"synthetic_{i:02d}", "display_name": f"Tester {i:02d}"}
                        for i in range(comp["players"])],
            "npc_name_pool": [f"Case NPC {i:02d}" for i in range(len(c["characters"]))]}


def _init(case, rules, composition_id, variant_id, seed, start_at, roster=None, game_id=None):
    roster = _roster(case, composition_id) if roster is None else roster
    game_id = game_id or "witness_" + canonical_hash({"case": case.content_hash, "composition": composition_id,
                                                     "variant": variant_id, "seed": seed, "start": start_at})[:24]
    return roster, game_id, _initialize(case, rules, roster, game_id=game_id, seed=seed,
        composition_id=composition_id, selected_variant_id=variant_id, now_utc=_timestamp(start_at))


def replay_witness(case, rules, witness):
    try:
        doc = Witness.from_document(witness.document() if isinstance(witness, Witness) else witness).document()
        has_messages = "communication" in case.document()
        if doc["schema"] != (MESSAGE_SCHEMA if has_messages else SCHEMA):
            return ReplayResult(False, "capability_mismatch", None, None)
        if doc["case_id"] != case.case_id or doc["case_version"] != case.case_version or doc["case_hash"] != case.content_hash or doc["rules_hash"] != rules.rules_hash or doc["compiler_version"] != case.compiler_version or doc["engine_version"] != engine_build_for(case.document()["ruleset_ref"]):
            return ReplayResult(False, "input_mismatch", None, None)
        if doc["input_hash"] != canonical_hash({"roster": doc["roster"], "game_id": doc["game_id"], "start_at": doc["start_at"]}):
            return ReplayResult(False, "input_mismatch", None, None)
        trace = dict(doc); trace.pop("trace_hash")
        if canonical_hash(trace) != doc["trace_hash"]: return ReplayResult(False, "trace_mismatch", None, None)
        _, _, transition = _init(case, rules, doc["composition_id"], doc["variant_id"], doc["seed"], doc["start_at"], doc["roster"], doc["game_id"])
        now = _timestamp(doc["start_at"])
        for item in doc["steps"]:
            at = _timestamp(item["now_utc"])
            if at < now: return ReplayResult(False, "time_reversed", None, None)
            now = at
            actor_doc = item["actor"]
            actor = SystemActor() if actor_doc["kind"] == "system" else PlayerActor(actor_doc["account_id"])
            transition = step(case, rules, transition.state, actor, item["command"], now_utc=at)
            if transition.receipt != item["expected_receipt"] or not transition.receipt["accepted"]:
                return ReplayResult(False, "receipt_mismatch", None, None)
            if _state_hash(transition.state) != item["state_hash"]:
                return ReplayResult(False, "state_mismatch", None, None)
            if has_messages and list(transition.messages) != item["expected_messages"]:
                return ReplayResult(False, "message_mismatch", None, None)
            if has_messages and transition.messages:
                message = transition.messages[0]
                ref = transition.state.document()["receipts"][-1]["result_ref"]
                expected_ref = {"kind": "message", "message_id": message["id"], "text_hash": message["text_hash"],
                                "channel": message["channel"], "thread_key": message["thread_key"],
                                "recipient_account_ids": message["recipient_account_ids"], "window_idx": message["window_idx"]}
                if ref != expected_ref or not transition.receipt["accepted"] or not isinstance(actor, PlayerActor) or message["sender_account_id"] != actor.account_id:
                    return ReplayResult(False, "message_receipt_mismatch", None, None)
        final = transition.state.document()["final"]
        final_code = final["code"] if final else None
        h = _state_hash(transition.state)
        return ReplayResult(final_code == doc["final_code"] == "solved", "solved" if final_code == "solved" else "not_solved", h, final_code)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return ReplayResult(False, "invalid_witness:" + type(exc).__name__, None, None)


class _Runner:
    def __init__(self, case, rules, composition_id, variant_id, seed, budget, start_at, roster=None, game_id=None):
        self.case, self.rules, self.budget = case, rules, budget
        self.roster, self.game_id, self.transition = _init(case, rules, composition_id, variant_id, seed, start_at, roster, game_id)
        self.composition_id, self.variant_id, self.seed, self.start_at = composition_id, variant_id, seed, start_at
        self.now = _timestamp(start_at)
        self.steps = []
        self.states = 1
        self.began = time.perf_counter()
        self.replay_elapsed = 0.0

    def limit(self):
        if len(self.steps) >= self.budget.max_commands: return "command_budget"
        if self.states >= self.budget.max_states: return "state_budget"
        if time.perf_counter() - self.began >= self.budget.max_seconds: return "time_budget"
        return None

    def do(self, actor, kind, params, *, at=None):
        reason = self.limit()
        if reason: return reason
        at = max(self.now, at or self.now)
        doc = self.transition.state.document(); clock = doc["clock"]
        command_index = len(self.steps)
        command_id = f"witness_{command_index:08d}"
        if self.steps:
            prior_ids = {r["command_id"] for r in doc["receipts"]}
            while command_id in prior_ids:
                command_index += 1
                command_id = f"witness_{command_index:08d}"
        if isinstance(actor, SystemActor):
            cmd = {"command_id": command_id, "kind": kind,
                   "window_seq": clock["window_seq"], "timer_seq": clock["timer_seq"], "params": params}
            trusted = {"kind": "system"}
        else:
            player = next(p for p in doc["players"] if p["account_id"] == actor.account_id)
            cmd = {"command_id": command_id, "kind": kind,
                   "window_idx": clock["window_idx"], "window_seq": clock["window_seq"],
                   "actor_seq": player["actor_seq"], "params": params}
            trusted = {"kind": "player", "account_id": actor.account_id}
        self.transition = step(self.case, self.rules, self.transition.state, actor, cmd, now_utc=at)
        self.now = at
        receipt = self.transition.receipt
        if not receipt["accepted"]: raise ValueError(f"planner produced rejected command: {receipt['code']}")
        record = {"actor": trusted, "command": cmd, "now_utc": _stamp(at),
                  "expected_receipt": receipt, "state_hash": _state_hash(self.transition.state)}
        if "communication" in self.case.document(): record["expected_messages"] = list(self.transition.messages)
        self.steps.append(record)
        self.states += 1
        return None

    def apply_prefix(self, item):
        _exact(item, {"actor", "command", "now_utc"})
        actor_doc = item["actor"]
        if type(actor_doc) is not dict: raise ValueError("invalid prefix actor")
        if set(actor_doc) == {"kind"} and actor_doc["kind"] == "system":
            actor = SystemActor()
        elif set(actor_doc) == {"kind", "account_id"} and actor_doc["kind"] == "player" and type(actor_doc["account_id"]) is str:
            actor = PlayerActor(actor_doc["account_id"])
        else: raise ValueError("invalid prefix actor")
        at = _timestamp(item["now_utc"])
        if at < self.now: raise ValueError("prefix time reversed")
        if type(item["command"]) is not dict: raise ValueError("invalid prefix command")
        reason = self.limit()
        if reason: return reason
        self.transition = step(self.case, self.rules, self.transition.state, actor, item["command"], now_utc=at)
        self.now = at
        record = {"actor": actor_doc, "command": json.loads(_json(item["command"])), "now_utc": _stamp(at),
                  "expected_receipt": self.transition.receipt, "state_hash": _state_hash(self.transition.state)}
        if "communication" in self.case.document(): record["expected_messages"] = list(self.transition.messages)
        self.steps.append(record)
        self.states += 1
        return None

    def choice(self, account, kind, params=None):
        actor = PlayerActor(account)
        entries = available_actions(self.case, self.rules, self.transition.state, actor, now_utc=self.now)
        if any(isinstance(e, MenuChoice) and e.quote.kind == kind and (params is None or json.loads(e.quote.params) == params) for e in entries):
            return self.do(actor, kind, params or {})
        return "unavailable"

    def form(self, account, kind, params):
        actor = PlayerActor(account)
        entries = available_actions(self.case, self.rules, self.transition.state, actor, now_utc=self.now)
        if not any(getattr(e, "command_kind", None) == kind for e in entries): return "unavailable"
        quote_action(self.case, self.rules, self.transition.state, actor, CommandIntent(kind, params), now_utc=self.now)
        return self.do(actor, kind, params)

    def tick(self):
        due = self.transition.due
        if due is None: return "no_due"
        return self.do(SystemActor(), "system.tick", {"expected_due_at": due["at"]}, at=_timestamp(due["at"]))

    def final_code(self):
        value = self.transition.state.document()["final"]
        return value["code"] if value else None

    def witness(self):
        doc = {"schema": MESSAGE_SCHEMA if "communication" in self.case.document() else SCHEMA,
               "case_id": self.case.case_id, "case_version": self.case.case_version,
               "case_hash": self.case.content_hash, "rules_hash": self.rules.rules_hash,
               "compiler_version": self.case.compiler_version,
               "engine_version": engine_build_for(self.case.document()["ruleset_ref"]),
               "composition_id": self.composition_id, "variant_id": self.variant_id, "seed": self.seed,
               "roster": self.roster, "game_id": self.game_id, "start_at": self.start_at,
               "input_hash": canonical_hash({"roster": self.roster, "game_id": self.game_id, "start_at": self.start_at}),
               "steps": self.steps, "final_code": self.final_code()}
        doc["trace_hash"] = canonical_hash(doc)
        return Witness.from_document(doc)


def _result(runner, status, reason, witness=None):
    total = time.perf_counter() - runner.began
    return SearchResult(status, witness, reason, len(runner.steps), runner.states,
                        total, ASSUMPTIONS, max(0.0, total - runner.replay_elapsed), runner.replay_elapsed)


def _relevant_targets(c, variant):
    needed = set(variant["key_proofs"])
    flags = set()
    providers = []
    for action in c["actions"]:
        providers.append(("act", action["location"], {"action_id": action["id"]},
                          action["available_when"], action["outcomes"]))
    for dialogue in c["dialogues"]:
        home = next(ch["home"] for ch in c["characters"] if ch["id"] == dialogue["character"])
        for node in dialogue["nodes"]:
            for option in node["options"]:
                providers.append(("talk", home, {"dialogue_id": dialogue["id"], "node_id": node["id"],
                                                 "option_id": option["id"]}, option["available_when"], option["outcomes"]))
    for query in c.get("module_data", {}).get("archive_requests", {}).get("queries", []):
        providers.append(("archive_request", query["location"], {"query_id": query["id"]},
                          query["available_when"],
                          [{"guard": {"when": []}, "effects": [{"kind": "grant_observation", "observation": observation}
                           for response in query["responses"]
                           if response["variants"] == "all" or variant["id"] in response["variants"]
                           for observation in response["observations"]]}]))
    selected = []
    remaining = list(providers)
    while True:
        picked = []
        for provider in remaining:
            if any((e["kind"] == "grant_observation" and e["observation"] in needed) or
                   (e["kind"] == "set_flag" and (e["flag"], e["value"]) in flags)
                   for outcome in provider[4] for e in outcome["effects"]):
                picked.append(provider)
        if not picked: break
        for provider in picked:
            remaining.remove(provider)
            selected.insert(0, provider)
            for predicate in provider[3] + [p for out in provider[4] for p in out["guard"]["when"]]:
                if predicate["kind"] in {"knows", "published"}: needed.add(predicate["observation"])
                elif predicate["kind"] == "flag_is": flags.add((predicate["flag"], predicate["value"]))
    return [(kind, location, params) for kind, location, params, _, _ in selected], needed


def _route(c, doc, source, destination):
    todo = [(source, [])]; visited = {source}; links = {l["id"]: l["connects"] for l in c["locations"]}
    flags = {f["id"]: f["value"] for f in doc["public"]["flags"]}
    for route in c.get("module_data", {}).get("turning_point", {}).get("routes", []):
        if flags.get(route["opened_flag"]):
            a, b = route["ends"]
            links[a] = [*links[a], b]
            links[b] = [*links[b], a]
    for current, path in todo:
        if current == destination: return path
        for nxt in sorted(links[current]):
            if nxt not in visited: visited.add(nxt); todo.append((nxt, path + [nxt]))
    return None


def _distance(c, doc, source, destination):
    path = _route(c, doc, source, destination)
    return 100 if path is None else len(path)


def _target_satisfied(c, doc, variant_id, kind, params):
    if kind == "archive_request":
        return any(e["kind"] == "archive_requested" and e["payload"]["query_id"] == params["query_id"]
                   for e in doc["private_events"])
    if kind == "act":
        outcomes = next(a["outcomes"] for a in c["actions"] if a["id"] == params["action_id"])
    elif kind == "talk":
        outcomes = next(o["outcomes"] for d in c["dialogues"] if d["id"] == params["dialogue_id"]
                        for n in d["nodes"] if n["id"] == params["node_id"]
                        for o in n["options"] if o["id"] == params["option_id"])
    else:
        return False
    produced = {effect["observation"] for outcome in outcomes
                if outcome["guard"]["variants"] == "all" or variant_id in outcome["guard"]["variants"]
                for effect in outcome["effects"] if effect["kind"] == "grant_observation"}
    known = {k["observation_id"] for k in doc["knowledge"]} | {k["observation_id"] for k in doc["public"]["observations"]}
    return bool(produced) and produced <= known


def _target_ready(c, doc, player, kind, params):
    if kind == "act":
        predicates = next(a["available_when"] for a in c["actions"] if a["id"] == params["action_id"])
    elif kind == "archive_request":
        predicates = next(q["available_when"] for q in c.get("module_data", {}).get("archive_requests", {}).get("queries", [])
                          if q["id"] == params["query_id"])
    elif kind == "talk":
        predicates = next(o["available_when"] for d in c["dialogues"] if d["id"] == params["dialogue_id"]
                          for n in d["nodes"] if n["id"] == params["node_id"]
                          for o in n["options"] if o["id"] == params["option_id"])
    else:
        return True
    return _predicates([p for p in predicates if p["kind"] != "at"], doc, player)


def _proof_goal_met(published, variant):
    keys = set(variant["key_proofs"])
    return len(keys & published) >= variant["min_key"] and set(variant.get("required_key_proofs", [])) <= published


def find_witness(case, rules, composition_id, variant_id, *, seed, budget=None, start_at=DEFAULT_START,
                 prefix_steps=(), roster=None, game_id=None):
    budget = budget or SearchBudget()
    if not isinstance(budget, SearchBudget): raise ValueError("invalid budget")
    runner = _Runner(case, rules, composition_id, variant_id, seed, budget, start_at, roster, game_id)
    if type(prefix_steps) not in (tuple, list): raise ValueError("invalid prefix steps")
    for prefix_step in prefix_steps:
        reason = runner.apply_prefix(prefix_step)
        if reason: return _result(runner, "inconclusive", reason)
    c = case.document(); variant = next(v for v in c["variants"] if v["id"] == variant_id)
    target_actions, planner_needed = _relevant_targets(c, variant)
    if not target_actions: return _result(runner, "inconclusive", "policy_has_no_target_action")
    while runner.final_code() is None:
        doc = runner.transition.state.document(); clock = doc["clock"]
        if clock["phase"] == "frozen": return _result(runner, "inconclusive", "policy_froze")
        board = doc["public"]["board"]
        proven = {b["observation_id"] for b in board if b["kind"] == "proof"}
        needed = set(variant["key_proofs"])
        for p in doc["players"]:
            if p["status"] != "active": continue
            account = p["account_id"]
            for k in doc["knowledge"]:
                if k["account_id"] == account and k["observation_id"] in planner_needed - proven:
                    reason = runner.choice(account, "pin", {"observation_id": k["observation_id"]})
                    if reason is None: proven.add(k["observation_id"])
                    elif reason != "unavailable": return _result(runner, "inconclusive", reason)
            if _proof_goal_met(proven, variant): break
            if p["ap"] < 1: continue
            candidates = target_actions
            if c["ruleset_ref"]["version"] == 2:
                candidates = sorted(target_actions, key=lambda item: (
                    _distance(c, runner.transition.state.document(), p["location"], item[1]),
                    target_actions.index(item)))
            for kind, location, params in candidates:
                if _proof_goal_met(proven, variant): break
                if c["ruleset_ref"]["version"] == 2:
                    current = runner.transition.state.document()
                    if _target_satisfied(c, current, variant_id, kind, params) or not _target_ready(c, current, p, kind, params): continue
                path = _route(c, runner.transition.state.document(), p["location"], location)
                if path is None or (len(path) >= p["ap"] if c["ruleset_ref"]["version"] == 1 else len(path) > p["ap"]): continue
                if path:
                    reason = runner.choice(account, "move", {"location": path[0]})
                    if reason is None: break
                    if reason != "unavailable": return _result(runner, "inconclusive", reason)
                else:
                    reason = runner.choice(account, kind, params)
                    if reason is None: break
                    if reason != "unavailable": return _result(runner, "inconclusive", reason)
        doc = runner.transition.state.document(); clock = doc["clock"]
        by_observation = {}
        for b in doc["public"]["board"]:
            if b["kind"] == "proof" and b["observation_id"] in needed:
                by_observation.setdefault(b["observation_id"], b)
        board = [by_observation[key] for key in sorted(by_observation)]
        if _proof_goal_met(set(by_observation), variant) and clock["phase"] == "investigation" and clock["window_idx"] >= rules.first_accusation_window and doc["hearing"] is None:
            active = [p["account_id"] for p in doc["players"] if p["status"] == "active"]
            citations = [b["id"] for b in board]
            if active:
                reason = runner.form(active[0], "accuse", {"suspect": variant["culprit"], "citations": citations[:5]})
                if reason is None:
                    for i, account in enumerate(active):
                        chunk = citations[5 + 5*i:10 + 5*i]
                        reason = runner.form(account, "vote", {"hearing_id": runner.transition.state.document()["hearing"]["id"],
                                                             "choice": "support", "citations": chunk})
                        if reason and reason != "unavailable": return _result(runner, "inconclusive", reason)
                elif reason != "unavailable": return _result(runner, "inconclusive", reason)
        # Presence is a bounded once-per-window action; only needed to keep the table awake.
        doc = runner.transition.state.document()
        if c["ruleset_ref"]["version"] == 1:
            for p in doc["players"]:
                if p["status"] == "active" and p["last_seen_window"] != doc["clock"]["window_idx"]:
                    reason = runner.choice(p["account_id"], "seen", {})
                    if reason and reason != "unavailable": return _result(runner, "inconclusive", reason)
        elif doc["hearing"] is None and not any(p["last_seen_window"] == doc["clock"]["window_idx"] for p in doc["players"]):
            account = next((p["account_id"] for p in doc["players"] if p["status"] == "active"), None)
            if account:
                reason = runner.choice(account, "seen", {})
                if reason and reason != "unavailable": return _result(runner, "inconclusive", reason)
        reason = runner.tick()
        if reason: return _result(runner, "inconclusive", reason)
        if runner.transition.state.document()["clock"]["phase"] == "final_hearing":
            doc = runner.transition.state.document()
            board = [b["id"] for b in doc["public"]["board"] if b["observation_id"] in needed and b["kind"] == "proof"]
            for i, p in enumerate(doc["players"]):
                if p["status"] != "active": continue
                reason = runner.form(p["account_id"], "final_vote", {"suspect": variant["culprit"], "citations": board[5*i:5*i+5]})
                if reason and reason != "unavailable": return _result(runner, "inconclusive", reason)
    if runner.final_code() != "solved": return _result(runner, "inconclusive", "policy_terminal_" + runner.final_code())
    witness = runner.witness()
    replay_began = time.perf_counter()
    replay = replay_witness(case, rules, witness)
    runner.replay_elapsed = time.perf_counter() - replay_began
    if not replay.passed: raise ValueError("generated witness failed replay")
    return _result(runner, "found", "replay_solved", witness)


def validate_matrix(case, rules, *, seed, budget=None, start_at=DEFAULT_START):
    c = case.document(); results = []
    for variant in c["variants"]:
        for composition_id in variant["composition_ids"]:
            results.append(find_witness(case, rules, composition_id, variant["id"], seed=seed,
                                        budget=budget, start_at=start_at))
    return MatrixReport(tuple(results), bool(results) and all(r.status == "found" for r in results))


def run_smoke_policy(case, rules, composition_id, variant_id, *, policy, seed, budget=None, start_at=DEFAULT_START):
    if policy not in {"passive_presence", "absent", "seeded_random"}: raise ValueError("unknown policy")
    runner = _Runner(case, rules, composition_id, variant_id, seed, budget or SearchBudget(), start_at)
    rng = random.Random(seed)
    reason = "terminal"
    while runner.final_code() is None:
        doc = runner.transition.state.document(); clock = doc["clock"]
        if policy == "passive_presence":
            if clock["phase"] == "frozen": raise ValueError("passive policy unexpectedly froze")
            c = case.document()
            variant = next(v for v in c["variants"] if v["id"] == variant_id)
            investigators = {ch["id"] for ch in c["characters"] if ch["faction"] == "investigation"}
            investigators -= {variant["culprit"], *variant["accomplices"]}
            account = next((p["account_id"] for p in doc["players"] if p["character_id"] in investigators
                            and p["status"] == "active" and p["last_seen_window"] != clock["window_idx"]), None)
            if account is None:
                account = next((p["account_id"] for p in doc["players"] if p["status"] == "active"
                                and p["last_seen_window"] != clock["window_idx"]), None)
            if account:
                reason = runner.choice(account, "seen", {})
                if reason: break
        elif policy == "seeded_random" and clock["phase"] != "frozen":
            options = []
            active_players = [p for p in doc["players"] if p["status"] == "active"]
            for p in (rng.choice(active_players),) if active_players else ():
                actor = PlayerActor(p["account_id"])
                for entry in available_actions(case, rules, runner.transition.state, actor, now_utc=runner.now):
                    if isinstance(entry, MenuChoice) and entry.quote.kind in {"move", "act", "talk", "seen", "pin"}:
                        if entry.quote.kind == "seen" and p["last_seen_window"] == clock["window_idx"]: continue
                        options.append((p["account_id"], entry.quote.kind, json.loads(entry.quote.params)))
            if options:
                account, kind, params = rng.choice(options)
                reason = runner.choice(account, kind, params)
                if reason: break
        reason = runner.tick()
        if reason: break
    code = runner.final_code()
    status = "terminal" if code else "inconclusive"
    expected = {"passive_presence": "unresolved", "absent": "forgotten"}.get(policy)
    return PolicyResult(policy, status, code, status == "terminal" and (expected is None or code == expected),
                        reason if status == "inconclusive" else "terminal", len(runner.steps), time.perf_counter() - runner.began)
