"""Strict, sealed snapshots and command envelopes for night-case core/1."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from domain.frozen_json import FrozenDict

ID = re.compile(r"[a-z][a-z0-9_]{1,31}\Z", re.ASCII)
HASH = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
UTC_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z", re.ASCII)
MAX_BYTES = 2 * 1024 * 1024


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"nonfinite JSON number: {value}")


def _walk(value, depth=0, counter=None, *, max_nodes=100000):
    if counter is None:
        counter = [0]
    counter[0] += 1
    if depth > 64 or counter[0] > max_nodes:
        raise ValueError("JSON complexity limit")
    if isinstance(value, dict):
        if any(type(k) is not str for k in value):
            raise ValueError("JSON object key must be string")
        for child in value.values():
            _walk(child, depth + 1, counter, max_nodes=max_nodes)
    elif isinstance(value, list):
        for child in value:
            _walk(child, depth + 1, counter, max_nodes=max_nodes)
    elif value is None or type(value) in (str, bool, int):
        pass
    elif type(value) is float:
        if not __import__("math").isfinite(value):
            raise ValueError("nonfinite JSON number")
    else:
        raise ValueError("non JSON value")


def _json_bytes(value, *, max_bytes=MAX_BYTES, max_nodes=100000):
    _walk(value, max_nodes=max_nodes)
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(data) > max_bytes:
        raise ValueError("snapshot size limit")
    return data


def canonical_hash(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def event_scope(audience: dict) -> str:
    """Return the sole core/1 event stream designated by a closed audience."""
    if type(audience) is not dict:
        raise ValueError("invalid event audience")
    if audience.get("kind") == "public":
        _obj(audience, {"kind"}, "public audience")
        return "public"
    _obj(audience, {"kind", "ids"}, "private audience")
    if audience["kind"] != "accounts" or type(audience["ids"]) is not list or len(audience["ids"]) != 1:
        raise ValueError("invalid private audience")
    return "account:" + _str(audience["ids"][0], "account_id")


def event_id_for(game_id: str, audience: dict, seq: int) -> str:
    _str(game_id, "game_id")
    _int(seq, "audience_seq", 1)
    raw = json.dumps(["night-city-event/1", game_id, event_scope(audience), seq], ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "evt_" + hashlib.sha256(raw).hexdigest()


def _load(raw, *, max_bytes=MAX_BYTES, max_nodes=100000):
    if type(raw) is not bytes or len(raw) > max_bytes:
        raise ValueError("expected bounded bytes")
    result = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_reject_constant)
    _walk(result, max_nodes=max_nodes)
    return result


def _obj(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError(f"{label}: unknown or missing fields")
    return value


def _arr(value, label, maximum=100000):
    if type(value) is not list or len(value) > maximum:
        raise ValueError(f"{label}: expected bounded array")
    return value


def _str(value, label, minimum=1, maximum=120):
    if type(value) is not str or not minimum <= len(value) <= maximum:
        raise ValueError(f"{label}: invalid string")
    return value


def _id(value, label):
    _str(value, label, 2, 32)
    if not ID.fullmatch(value):
        raise ValueError(f"{label}: invalid content ID")
    return value


def _hash(value, label):
    if type(value) is not str or not HASH.fullmatch(value):
        raise ValueError(f"{label}: invalid SHA-256")
    return value


def _int(value, label, low=0, high=2**63 - 1):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label}: invalid exact integer")
    return value


def _bool(value, label):
    if type(value) is not bool:
        raise ValueError(f"{label}: invalid boolean")


def _enum(value, options, label):
    if type(value) is not str or value not in options:
        raise ValueError(f"{label}: invalid enum")


def _timestamp(value, label, nullable=False):
    if value is None and nullable:
        return
    if type(value) is not str or not UTC_STAMP.fullmatch(value):
        raise ValueError(f"{label}: invalid UTC timestamp")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.isoformat().replace("+00:00", "Z") != value:
        raise ValueError(f"{label}: noncanonical UTC timestamp")


def _ids(value, label, *, typed=True, maximum=100000):
    seen = set()
    for item in _arr(value, label, maximum):
        (_id(item, label) if typed else _str(item, label, 1, 128))
        if item in seen:
            raise ValueError(f"{label}: repeated ID")
        seen.add(item)
    return seen


def _unique(rows, fields, label):
    seen = set()
    for row in rows:
        key = tuple(row[field] for field in fields)
        if key in seen:
            raise ValueError(f"{label}: repeated key")
        seen.add(key)


RULE_DEFAULTS = {
    "slots": ["09:00", "19:00"], "quiet_start": "23:00", "quiet_end": "08:00",
    "window_count": 14, "ap_per_window": 3, "move_cost": 1, "act_cost": 1, "talk_cost": 1,
    "early_min_seconds": 1800, "outage_extension_min_seconds": 3600,
    "outage_extension_max_seconds": 21600, "afk_notice_windows": 1,
    "afk_fog_windows": 2, "afk_depart_windows": 4,
    "freeze_after_idle_windows": 6, "forget_after_days": 14,
    "first_accusation_window": 3, "last_ordinary_accusation_window": 12,
    "accusations_per_player": 1, "final_hearing_window": 14,
    "support_policy": "strict_majority", "idle_policy": "table_idle_first",
}


class _Snapshot:
    __slots__ = ("_bytes",)

    def __init__(self, document):
        object.__setattr__(self, "_bytes", _json_bytes(document))

    def __setattr__(self, key, value):
        raise AttributeError("frozen snapshot")

    def document(self):
        return _load(self._bytes)

    def __getattr__(self, name):
        document = self.document()
        if name in document:
            return document[name]
        raise AttributeError(name)

    def __eq__(self, other):
        return type(self) is type(other) and self._bytes == other._bytes


class RulesSnapshot(_Snapshot):
    @classmethod
    def from_document(cls, raw, *, allow_custom=False):
        doc = _obj(copy.deepcopy(raw), {"timezone", *RULE_DEFAULTS}, "rules")
        _str(doc["timezone"], "timezone", 1, 120)
        try:
            ZoneInfo(doc["timezone"])
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("invalid timezone") from exc
        def hhmm(value):
            if type(value) is not str or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
                raise ValueError("invalid local time")
        for key in ("quiet_start", "quiet_end"):
            hhmm(doc[key])
        if doc["quiet_start"] == doc["quiet_end"]:
            raise ValueError("empty or full quiet interval")
        if type(doc["slots"]) is not list or not doc["slots"] or len(doc["slots"]) > 24 or any(type(slot) is not str for slot in doc["slots"]) or len(doc["slots"]) != len(set(doc["slots"])):
            raise ValueError("invalid slots")
        for value in doc["slots"]:
            hhmm(value)
        for key, expected in RULE_DEFAULTS.items():
            if type(expected) is int:
                _int(doc[key], key)
            elif type(expected) is str:
                _str(doc[key], key)
        if not allow_custom and any(type(doc[key]) is not type(expected) or doc[key] != expected for key, expected in RULE_DEFAULTS.items()):
            raise ValueError("unsupported core rules")
        return cls(doc)

    @property
    def rules_hash(self):
        return hashlib.sha256(self._bytes).hexdigest()


def rules_snapshot(timezone: str) -> RulesSnapshot:
    return RulesSnapshot.from_document({"timezone": timezone, **RULE_DEFAULTS})


class Clock(_Snapshot):
    @classmethod
    def from_document(cls, raw):
        doc = _obj(copy.deepcopy(raw), {"timezone", "window_idx", "window_seq", "timer_seq", "opened_at", "closes_at", "early_not_before", "slot_cursor", "phase", "opening_pending", "freeze_at", "forget_at", "resume_receipts"}, "clock")
        _str(doc["timezone"], "timezone")
        try:
            ZoneInfo(doc["timezone"])
        except ZoneInfoNotFoundError as exc:
            raise ValueError("invalid timezone") from exc
        _int(doc["window_idx"], "window_idx", 1, 14)
        for field in ("window_seq", "timer_seq"):
            _int(doc[field], field, 1)
        for field in ("opened_at", "closes_at", "early_not_before", "freeze_at", "forget_at"):
            _timestamp(doc[field], field, True)
        if doc["slot_cursor"] is not None:
            cursor = _obj(doc["slot_cursor"], {"local_date", "local_time"}, "slot_cursor")
            if type(cursor["local_date"]) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cursor["local_date"]):
                raise ValueError("invalid slot date")
            datetime.fromisoformat(cursor["local_date"])
            if type(cursor["local_time"]) is not str or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", cursor["local_time"]):
                raise ValueError("invalid slot time")
        _enum(doc["phase"], {"investigation", "final_hearing", "frozen", "finished"}, "phase")
        _bool(doc["opening_pending"], "opening_pending")
        for row in _arr(doc["resume_receipts"], "resume_receipts", 10000):
            _obj(row, {"outage_id", "payload_hash"}, "resume_receipt")
            _str(row["outage_id"], "outage_id")
            _hash(row["payload_hash"], "payload_hash")
        _unique(doc["resume_receipts"], ("outage_id",), "resume_receipts")
        if doc["phase"] == "frozen":
            if not doc["opening_pending"] or any(doc[k] is not None for k in ("opened_at", "closes_at", "early_not_before")) or doc["freeze_at"] is None or doc["forget_at"] is None:
                raise ValueError("invalid frozen clock")
        elif doc["phase"] in ("investigation", "final_hearing"):
            if doc["opening_pending"] or any(doc[k] is None for k in ("opened_at", "closes_at", "early_not_before")):
                raise ValueError("invalid active clock")
            if not (doc["opened_at"] <= doc["early_not_before"] <= doc["closes_at"]):
                raise ValueError("invalid clock order")
            opened = datetime.fromisoformat(doc["opened_at"].replace("Z", "+00:00"))
            early = datetime.fromisoformat(doc["early_not_before"].replace("Z", "+00:00"))
            if early != opened + timedelta(seconds=1800):
                raise ValueError("invalid minimum window duration")
        return cls(doc)


@dataclass(frozen=True)
class PlayerActor:
    account_id: str

    def __post_init__(self):
        _str(self.account_id, "account_id")

    @property
    def actor_key(self):
        return "account:" + self.account_id


@dataclass(frozen=True)
class SystemActor:
    @property
    def actor_key(self):
        return "system"


PLAYER_PARAMS = {
    "move": {"location"}, "act": {"action_id"},
    "talk": {"dialogue_id", "node_id", "option_id"},
    "pin": {"observation_id"}, "claim": {"text"},
    "seen": set(), "finish_window": set(),
    "accuse": {"suspect", "citations"},
    "vote": {"hearing_id", "choice", "citations"},
    "final_vote": {"suspect", "citations"},
    "ghost_share": {"observation_id"}, "forfeit": set(),
}
SYSTEM_PARAMS = {"system.tick": {"expected_due_at"}, "system.resume": {"outage_id", "unavailable_from", "resumed_at"}}
MODULE_PLAYER_PARAMS = {"archive_request": {"query_id"}, "version_mark": {"version_id", "state"}, "story_reply": {"offer_event_id", "accept"}, "say": {"channel", "recipients", "text"}}


def engine_build_for(ruleset_ref):
    if type(ruleset_ref) is FrozenDict:  # read-only parsed case (CompiledCase.readonly)
        ruleset_ref = dict(ruleset_ref)
    ref = _obj(ruleset_ref, {"id", "version"}, "ruleset_ref")
    _int(ref["version"], "ruleset version", 1, 2)
    if ref["id"] != "night_case.core":
        raise ValueError("unsupported ruleset")
    return "night-case-core/" + str(ref["version"])


class Command(_Snapshot):
    @classmethod
    def from_document(cls, raw, actor, *, ruleset_version=1):
        _int(ruleset_version, "ruleset_version", 1, 2)
        doc = raw.document() if isinstance(raw, Command) else _load(raw) if type(raw) is bytes else copy.deepcopy(raw)
        system = isinstance(actor, SystemActor)
        if not system and not isinstance(actor, PlayerActor):
            raise ValueError("invalid actor")
        fields = {"command_id", "kind", "window_seq", "timer_seq", "params"} if system else {"command_id", "kind", "window_idx", "window_seq", "actor_seq", "params"}
        _obj(doc, fields, "command")
        _str(doc["command_id"], "command_id", 8, 64)
        kinds = SYSTEM_PARAMS if system else PLAYER_PARAMS | (MODULE_PLAYER_PARAMS if ruleset_version == 2 else {})
        _enum(doc["kind"], kinds, "kind")
        for field in fields & {"window_idx", "window_seq", "timer_seq", "actor_seq"}:
            _int(doc[field], field, 1 if field != "actor_seq" else 0, 14 if field == "window_idx" else 2**63 - 1)
        params = _obj(doc["params"], kinds[doc["kind"]], "params")
        if doc["kind"] == "say":
            from domain.night_case_delivery_state import normalize_say_params
            doc["params"] = normalize_say_params(params)
            return cls(doc)
        for field, value in params.items():
            if field == "citations":
                _ids(value, field, typed=False, maximum=5)
            elif field == "text":
                _str(value, field, 1, 1200)
            elif field == "choice":
                _enum(value, {"support", "oppose"}, field)
            elif field == "state":
                _enum(value, {"active", "archived"}, field)
            elif field == "accept":
                _bool(value, field)
            elif field == "offer_event_id":
                _str(value, field, 1, 128)
            elif field in ("expected_due_at", "unavailable_from", "resumed_at"):
                _timestamp(value, field)
            elif value is None and field == "suspect" and doc["kind"] == "final_vote":
                pass
            elif field == "outage_id":
                _str(value, field)
            elif field == "hearing_id":
                _str(value, field, 1, 128)
            else:
                _id(value, field)
        return cls(doc)

    @property
    def payload_hash(self):
        doc = self.document()
        doc.pop("command_id")
        return canonical_hash(doc)


def parse_command(raw, actor, *, ruleset_version=1):
    return Command.from_document(raw, actor, ruleset_version=ruleset_version)


def _source(value):
    row = _obj(value, {"kind", "source_id", "actor_character", "location", "window_idx"}, "source")
    _enum(row["kind"], {"initial", "action", "dialogue", "event", "ghost"}, "source.kind")
    _str(row["source_id"], "source_id", 1, 128)
    if row["actor_character"] is not None:
        _id(row["actor_character"], "actor_character")
    if row["location"] is not None:
        _id(row["location"], "source.location")
    _int(row["window_idx"], "source.window_idx", 1, 14)


def _body(value):
    row = _obj(value, {"text", "mentions"}, "body")
    _str(row["text"], "body.text", 1, 1200)
    _ids(row["mentions"], "body.mentions")


def _event(value, *, private, modules=(), personal=False):
    row = _obj(value, {"event_id", "window_idx", "audience_seq", "kind", "audience", "payload"}, "event")
    _str(row["event_id"], "event_id", 1, 128)
    _int(row["window_idx"], "event.window_idx", 1, 14)
    _int(row["audience_seq"], "event.audience_seq", 1)
    private_kinds = {"action_result", "window_digest", "afk_notice"}
    public_kinds = {"window", "status", "hearing", "final", "board", "scene", "world_changed"}
    if "archive_requests" in modules:
        private_kinds |= {"archive_requested", "archive_response"}
    if "version_archive" in modules:
        public_kinds.add("version_marked")
    if "turning_point" in modules:
        public_kinds.add("npc_revealed")
    if personal:
        private_kinds |= {"story_result", "story_offer", "story_return_closed", "story_epilogue"}
        public_kinds.add("authored_card_delivered")
    _enum(row["kind"], private_kinds | public_kinds | {"observation_granted"}, "event.kind")
    audience = row["audience"]
    if type(audience) is not dict or audience.get("kind") not in {"public", "accounts"}:
        raise ValueError("invalid audience")
    if audience["kind"] == "public":
        _obj(audience, {"kind"}, "public audience")
        if private:
            raise ValueError("private event has public audience")
    else:
        _obj(audience, {"kind", "ids"}, "accounts audience")
        _ids(audience["ids"], "audience.ids", typed=False)
        if len(audience["ids"]) != 1 or not private:
            raise ValueError("wrong event audience")
    if row["kind"] in private_kinds and not private or row["kind"] in public_kinds and private:
        raise ValueError("wrong event kind audience")
    payload = row["payload"]
    kind = row["kind"]
    shapes = {
        "window": {"window_idx", "phase", "opened_at", "closes_at"},
        "status": {"character_id", "controller", "status"},
        "hearing": {"hearing_id", "suspect", "stage", "resolution", "resolve_window"},
        "final": {"code", "at"},
        "action_result": {"body", "observation_ids"},
        "observation_granted": {"observation_id", "source"},
        "window_digest": {"window_idx", "observation_ids", "event_ids"},
        "afk_notice": {"window_idx", "missed_windows"},
        "board": {"board_id"},
        "scene": {"content_event_id", "body"},
        "world_changed": {"flags", "locks"},
        "archive_requested": {"query_id", "due_window"},
        "archive_response": {"request_event_id", "disposition", "body", "observation_ids"},
        "version_marked": {"version_id", "state", "by_account"},
        "npc_revealed": {"character_id", "location"},
        "story_result": {"step_id", "disposition", "body", "observation_ids"},
        "story_offer": {"step_id", "from_character", "original_id", "return_location", "body"},
        "story_return_closed": {"offer_event_id", "decision"},
        "story_epilogue": {"trip_id", "body"},
        "authored_card_delivered": {"observation_id", "body"},
    }
    _obj(payload, shapes[kind], f"{kind} payload")
    if kind == "window":
        _int(payload["window_idx"], "window_idx", 1, 14)
        if payload["window_idx"] != row["window_idx"]:
            raise ValueError("window event cursor mismatch")
        _enum(payload["phase"], {"investigation", "final_hearing", "frozen", "finished"}, "window.phase")
        for field in ("opened_at", "closes_at"):
            _timestamp(payload[field], field, True)
        if payload["phase"] in {"investigation", "final_hearing"}:
            if payload["opened_at"] is None or payload["closes_at"] is None or payload["opened_at"] >= payload["closes_at"]:
                raise ValueError("invalid window event time")
        elif payload["opened_at"] is not None or payload["closes_at"] is not None:
            raise ValueError("finished/frozen window has no active time")
    elif kind == "status":
        _id(payload["character_id"], "character_id")
        _enum(payload["controller"], {"player", "npc"}, "controller")
        allowed = {"active", "fog", "ghost"} if payload["controller"] == "player" else {"active", "removed"}
        _enum(payload["status"], allowed, "status")
    elif kind == "hearing":
        _str(payload["hearing_id"], "hearing_id", 1, 128)
        _id(payload["suspect"], "suspect")
        _enum(payload["stage"], {"opened", "closed"}, "hearing.stage")
        if payload["stage"] == "opened":
            if payload["resolution"] is not None:
                raise ValueError("opened hearing has resolution")
        else:
            _enum(payload["resolution"], {"not_supported", "not_proven", "wrong", "solved", "cancelled"}, "hearing.resolution")
        _int(payload["resolve_window"], "resolve_window", 1, 14)
    elif kind == "final":
        _enum(payload["code"], {"solved", "shadow_framed", "no_investigators", "unresolved", "forgotten"}, "final.code")
        _timestamp(payload["at"], "final.at")
    elif kind in {"action_result", "story_result"}:
        _body(payload["body"])
        _ids(payload["observation_ids"], "observation_ids", maximum=12 if kind == "story_result" else 150)
        if kind == "story_result":
            _id(payload["step_id"], "step_id")
            _enum(payload["disposition"], {"completed", "not_completed", "offered"}, "story disposition")
    elif kind == "story_offer":
        for field in ("step_id", "from_character", "original_id", "return_location"):
            _id(payload[field], field)
        _body(payload["body"])
    elif kind == "story_return_closed":
        _str(payload["offer_event_id"], "offer_event_id", 1, 128)
        _enum(payload["decision"], {"accepted", "declined", "cancelled"}, "return decision")
    elif kind == "story_epilogue":
        _id(payload["trip_id"], "trip_id")
        _body(payload["body"])
    elif kind == "authored_card_delivered":
        _id(payload["observation_id"], "observation_id")
        _body(payload["body"])
    elif kind == "observation_granted":
        _id(payload["observation_id"], "observation_id")
        _source(payload["source"])
        if payload["source"]["window_idx"] != row["window_idx"]:
            raise ValueError("grant source window mismatch")
        if not private and (payload["source"]["actor_character"] is not None or payload["source"]["location"] is not None or payload["source"]["kind"] not in {"initial", "event"} or payload["source"]["source_id"] != row["event_id"]):
            raise ValueError("public grant leaks source")
    elif kind == "window_digest":
        _int(payload["window_idx"], "window_idx", 1, 14)
        if row["window_idx"] != payload["window_idx"] + (0 if row["window_idx"] == 1 else 1):
            raise ValueError("digest window mismatch")
        _ids(payload["observation_ids"], "digest observations", maximum=150)
        _ids(payload["event_ids"], "digest events", typed=False, maximum=64)
        if row["event_id"] in payload["event_ids"]:
            raise ValueError("self digest reference")
    elif kind == "afk_notice":
        _int(payload["window_idx"], "notice window_idx", 1, 13)
        _int(payload["missed_windows"], "missed_windows", 1, 14)
        if row["window_idx"] != payload["window_idx"] + 1:
            raise ValueError("notice window mismatch")
    elif kind == "board":
        _str(payload["board_id"], "board_id", 1, 128)
    elif kind == "scene":
        _id(payload["content_event_id"], "content_event_id")
        _body(payload["body"])
    elif kind == "archive_requested":
        _id(payload["query_id"], "query_id")
        _int(payload["due_window"], "due_window", 2, 14)
        if payload["due_window"] != row["window_idx"] + 1:
            raise ValueError("archive request due window mismatch")
    elif kind == "archive_response":
        _str(payload["request_event_id"], "request_event_id", 1, 128)
        _enum(payload["disposition"], {"delivered", "cancelled"}, "disposition")
        _ids(payload["observation_ids"], "response observations", maximum=8)
        if payload["disposition"] == "delivered":
            _body(payload["body"])
        elif payload["body"] is not None or payload["observation_ids"]:
            raise ValueError("cancelled response has content")
    elif kind == "version_marked":
        _id(payload["version_id"], "version_id")
        _enum(payload["state"], {"active", "archived"}, "version state")
        _str(payload["by_account"], "by_account")
    elif kind == "npc_revealed":
        _id(payload["character_id"], "character_id")
        _id(payload["location"], "location")
    else:
        if not payload["flags"] and not payload["locks"]:
            raise ValueError("empty world change")
        for change in _arr(payload["flags"], "world flags", 64):
            _obj(change, {"id", "value"}, "world flag")
            _id(change["id"], "flag id")
            _bool(change["value"], "flag value")
        _unique(payload["flags"], ("id",), "world flags")
        for change in _arr(payload["locks"], "world locks", 10):
            _obj(change, {"location", "through_window"}, "world lock")
            _id(change["location"], "lock location")
            if change["through_window"] is not None:
                _int(change["through_window"], "through_window", 1, 14)
        _unique(payload["locks"], ("location",), "world locks")


def _validate_modules(doc, case_doc, modules, streams, all_event_by_id):
    """Validate retained module history; it remains the sole request/mark truth."""
    variant_id = doc["sealed"]["variant_id"]
    public = doc["public"]
    players = {p["account_id"]: p for p in doc["players"]}
    chronicle = public["chronicle"]
    queries = {q["id"]: q for q in modules.get("archive_requests", {}).get("queries", [])}
    theories = {t["id"] for t in modules.get("version_archive", {}).get("theories", [])}
    turning = modules.get("turning_point", {})
    concealed = {n["character"]: n for n in turning.get("concealed_npcs", [])}
    flags = {r["id"]: r["value"] for r in public["flags"]}
    npcs = {r["character_id"]: r for r in doc["npcs"]}
    for character, config in concealed.items():
        placement = next(p for p in config["placements"] if p["variants"] == "all" or variant_id in p["variants"])
        npc = npcs.get(character)
        if npc is None or npc["origin"] != "authored" or npc["location"] != placement["location"]:
            raise ValueError("concealed NPC placement mismatch")

    marks, mark_repeats, discoveries, played_scenes = {}, set(), {}, set()
    protected = {r["opened_flag"]: r for r in turning.get("routes", [])}
    protected.update({n["revealed_flag"]: n for n in concealed.values()})
    protected_changes = set()
    history_flags = {f["id"]: f["initial"] for f in case_doc["flags"]}
    controller_status = {p["character_id"]: "active" for p in players.values()}
    pending_scene_flags = {}
    published = set()
    board = {b["id"]: b for b in public["board"]}

    def has_reveal_trace(character, location, window):
        # Public discovery deliberately carries no private event reference. Match
        # the retained private result/use/receipt instead; replay proves full causality.
        for action in case_doc["actions"]:
            if action["location"] != location:
                continue
            outcomes = [o for o in action["outcomes"] if (o["guard"]["variants"] == "all" or variant_id in o["guard"]["variants"]) and any(e["kind"] == "reveal_npc" and e["character"] == character for e in o["effects"])]
            if not outcomes:
                continue
            for use in doc["action_uses"]:
                if use["action_key"] != action["id"] or use["window_idx"] != (None if action["repeat"] == "player_game" else window):
                    continue
                account = use["account_id"]
                for result in streams.get("account:" + account, []):
                    if result["kind"] != "action_result" or result["window_idx"] != window or not any(result["payload"]["body"] == o["body"] for o in outcomes):
                        continue
                    if any(type(r) is dict and r.get("actor_key") == "account:" + account and r.get("accepted") is True and r.get("result_ref") == {"kind": "event", "event_id": result["event_id"]} for r in doc["receipts"]):
                        return True
        return False

    def private_flag_values(window):
        # Separate audience streams have no shared batch cursor. A retained paid
        # result proves a feasible authored effect in this window, not its exact
        # order relative to a public scene. Witness replay checks that order.
        values = {}
        targets = []
        for action in case_doc["actions"]:
            uses = [u for u in doc["action_uses"] if u["action_key"] == action["id"] and u["window_idx"] == (None if action["repeat"] == "player_game" else window)]
            targets.append((action["outcomes"], {u["account_id"] for u in uses}))
        for dialogue in case_doc["dialogues"]:
            for node in dialogue["nodes"]:
                for option in node["options"]:
                    targets.append((option["outcomes"], players))
        for outcomes, eligible_accounts in targets:
            for outcome in outcomes:
                if outcome["guard"]["variants"] != "all" and variant_id not in outcome["guard"]["variants"]:
                    continue
                for account in eligible_accounts:
                    compatible = [e for e in streams.get("account:" + account, []) if e["kind"] == "action_result" and e["window_idx"] == window and e["payload"]["body"] == outcome["body"]]
                    if not any(type(r) is dict and r.get("accepted") is True and r.get("actor_key") == "account:" + account and any(r.get("result_ref") == {"kind": "event", "event_id": e["event_id"]} for e in compatible) for r in doc["receipts"]):
                        continue
                    for effect in outcome["effects"]:
                        if effect["kind"] == "set_flag":
                            values.setdefault(effect["flag"], set()).add(effect["value"])
        return values

    private_flags_by_window = {}

    def flag_values(flag, event, visiting, allow_current_world):
        window = event["window_idx"]
        if flag not in protected:
            feasible = {history_flags[flag]} | pending_scene_flags.get(flag, set())
            if window not in private_flags_by_window:
                private_flags_by_window[window] = private_flag_values(window)
            return feasible | private_flags_by_window[window].get(flag, set())
        if history_flags[flag]:
            return {True}
        config = protected[flag]
        if "character" in config:
            # Discovery proves the semantic value immediately, before the batch's
            # coalesced world_changed. This applies to true and false guards alike.
            return {config["character"] in discoveries}
        # Routes settle before scenes, while their world change may follow them.
        # Only prerequisites already available here can justify an opened route.
        confirmation = any(e["kind"] == "world_changed" and e["window_idx"] == window and (e["audience_seq"] > event["audience_seq"] or allow_current_world and e is event) and {"id": flag, "value": True} in e["payload"]["flags"] for e in chronicle)
        if flag in visiting or not confirmation:
            return {False}
        guards = predicate_values(config["open_when"], event, visiting | {flag}, allow_current_world)
        # Uncertain mutable guards do not prove that a route was already open;
        # definite public prerequisites do, even before its eventual world change.
        return {False} if True not in guards else {True} if guards == {True} else {False, True}

    def predicate_values(predicates, event, visiting, allow_current_world):
        values = []
        for pred in predicates:
            kind = pred["kind"]
            if kind == "published":
                values.append({pred["observation"] in published})
            elif kind == "window_in":
                values.append({pred["from"] <= event["window_idx"] <= pred["to"]})
            else:
                values.append({v == pred["value"] for v in flag_values(pred["flag"], event, visiting, allow_current_world)})
        if any(v == {False} for v in values):
            return {False}
        return {True} if all(v == {True} for v in values) else {False, True}

    def scene_predicates_feasible(predicates, event, *, allow_current_world=False):
        return True in predicate_values(predicates, event, frozenset(), allow_current_world)

    for event in chronicle:
        payload, kind, window = event["payload"], event["kind"], event["window_idx"]
        if kind == "status" and payload["character_id"] in controller_status:
            controller_status[payload["character_id"]] = payload["status"] if payload["controller"] == "player" else "departed"
        elif kind == "board":
            entry = board[payload["board_id"]]
            if entry["observation_id"] is not None:
                published.add(entry["observation_id"])
        elif kind == "version_marked":
            theory, account = payload["version_id"], payload["by_account"]
            if theory not in theories or account not in players:
                raise ValueError("version mark reference")
            if controller_status[players[account]["character_id"]] != "active":
                raise ValueError("inactive player marked version")
            repeat = (account, theory, window)
            if repeat in mark_repeats or marks.get(theory, "active") == payload["state"]:
                raise ValueError("version mark no-op or repeat")
            mark_repeats.add(repeat)
            marks[theory] = payload["state"]
        elif kind == "npc_revealed":
            character = payload["character_id"]
            if character not in concealed or character in discoveries or payload["location"] != npcs[character]["location"]:
                raise ValueError("NPC discovery reference or duplicate")
            if not has_reveal_trace(character, payload["location"], window):
                raise ValueError("NPC discovery has no compatible private search trace")
            # A removed target cannot be discovered; later removal is allowed.
            if any(e["kind"] == "status" and e["payload"]["character_id"] == character and e["payload"]["controller"] == "npc" and e["payload"]["status"] == "removed" and e["audience_seq"] < event["audience_seq"] for e in chronicle):
                raise ValueError("removed NPC discovered")
            discoveries[character] = event
        elif kind == "world_changed":
            next_flags = history_flags | {f["id"]: f["value"] for f in payload["flags"]}
            for change in payload["flags"]:
                flag = change["id"]
                if flag in protected:
                    if change["value"] is not True or flag in protected_changes:
                        raise ValueError("protected flag reset or duplicate")
                    config = protected[flag]
                    if "open_when" in config:
                        if not scene_predicates_feasible(config["open_when"], event, allow_current_world=True):
                            raise ValueError("route opened without published prerequisites")
                    elif config["character"] not in discoveries:
                        raise ValueError("reveal flag without discovery")
                    protected_changes.add(flag)
            history_flags = next_flags
            pending_scene_flags.clear()
        elif kind == "scene" and payload["content_event_id"] in {s["id"] for s in turning.get("scenes", [])}:
            scene = next(s for s in turning["scenes"] if s["id"] == payload["content_event_id"])
            if scene["id"] in played_scenes or scene["id"] not in doc["event_uses"] or not scene["not_before"] <= window <= scene["through_window"]:
                raise ValueError("module scene outside authored window")
            if not scene_predicates_feasible(scene["when"], event):
                raise ValueError("module scene prerequisites have no feasible prior source")
            played_scenes.add(scene["id"])
            for effect in scene["effects"]:
                if effect["kind"] == "set_flag":
                    pending_scene_flags.setdefault(effect["flag"], set()).add(effect["value"])
        elif kind == "scene":
            scheduled = next(s for s in case_doc["events"] if s["id"] == payload["content_event_id"])
            for effect in scheduled["effects"]:
                if effect["kind"] == "set_flag":
                    pending_scene_flags.setdefault(effect["flag"], set()).add(effect["value"])
    if played_scenes != set(doc["event_uses"]) & {s["id"] for s in turning.get("scenes", [])}:
        raise ValueError("module scene use/history mismatch")
    for flag in protected:
        if flags[flag] != (flag in protected_changes):
            raise ValueError("protected flag/history mismatch")
    for character, config in concealed.items():
        if flags[config["revealed_flag"]] != (character in discoveries):
            raise ValueError("discovery flag/history mismatch")

    requests, responses, repeat_requests = {}, {}, set()
    for account in players:
        for event in sorted(streams.get("account:" + account, []), key=lambda e: e["audience_seq"]):
            payload = event["payload"]
            if event["kind"] == "archive_requested":
                query = payload["query_id"]
                if query not in queries or (account, query) in repeat_requests:
                    raise ValueError("archive query reference or repeat")
                repeat_requests.add((account, query))
                requests[event["event_id"]] = event
            elif event["kind"] == "archive_response":
                request_id = payload["request_event_id"]
                request = requests.get(request_id)
                if request is None or request["audience"] != event["audience"] or request_id in responses or event["window_idx"] != request["payload"]["due_window"]:
                    raise ValueError("archive response reference, audience, duplicate or window")
                due = event["window_idx"]
                openings = [e for e in chronicle if e["kind"] == "window" and e["window_idx"] == due and e["payload"]["phase"] in {"investigation", "final_hearing"}]
                if not openings:
                    raise ValueError("archive response before actual window opening")
                opening_seq = openings[0]["audience_seq"]
                inactive = any(e["kind"] == "status" and e["payload"]["character_id"] == players[account]["character_id"] and e["audience_seq"] < opening_seq and (e["payload"]["controller"] == "npc" or e["payload"]["status"] == "ghost") for e in chronicle)
                if (payload["disposition"] == "cancelled") != inactive:
                    raise ValueError("archive disposition disagrees with historical opening status")
                if payload["disposition"] == "delivered":
                    authored = next(r for r in queries[request["payload"]["query_id"]]["responses"] if r["variants"] == "all" or variant_id in r["variants"])
                    if payload["body"] != authored["body"] or payload["observation_ids"] != authored["observations"]:
                        raise ValueError("archive response differs from authored content")
                    known = {k["observation_id"] for k in doc["knowledge"] if k["account_id"] == account}
                    if not set(payload["observation_ids"]) <= known:
                        raise ValueError("archive delivery knowledge not retained")
                    for observation in payload["observation_ids"]:
                        retained = next(k for k in doc["knowledge"] if k["account_id"] == account and k["observation_id"] == observation)
                        if retained["source"]["source_id"] != request_id and not any(e["kind"] == "observation_granted" and e["audience_seq"] < event["audience_seq"] and e["payload"]["observation_id"] == observation and e["payload"]["source"] == retained["source"] for e in streams.get("account:" + account, [])):
                            raise ValueError("archive observation has no prior or delivery source")
                responses[request_id] = event
    opened = {e["window_idx"] for e in chronicle if e["kind"] == "window" and e["payload"]["phase"] in {"investigation", "final_hearing"}}
    for request_id, request in requests.items():
        if request["payload"]["due_window"] in opened and request_id not in responses:
            raise ValueError("archive delivery missing after actual opening")
    sources = [(r["account_id"], r["observation_id"], r["source"]) for r in doc["knowledge"]]
    sources += [(e["audience"]["ids"][0], e["payload"]["observation_id"], e["payload"]["source"]) for e in doc["private_events"] if e["kind"] == "observation_granted"]
    for account, observation, source in sources:
        origin = all_event_by_id.get(source["source_id"])
        if origin is None or origin["kind"] not in {"archive_requested", "archive_response"}:
            continue
        response = responses.get(source["source_id"])
        if response is None or response["payload"]["disposition"] != "delivered" or response["audience"]["ids"] != [account] or observation not in response["payload"]["observation_ids"] or source != {"kind": "event", "source_id": origin["event_id"], "actor_character": players[account]["character_id"], "location": None, "window_idx": response["window_idx"]}:
            raise ValueError("archive grant provenance mismatch")
        if not any(e["kind"] == "observation_granted" and e["audience"]["ids"] == [account] and e["payload"] == {"observation_id": observation, "source": source} for e in doc["private_events"]):
            raise ValueError("archive knowledge has no retained grant")


def _case_doc(case):
    """Read-only parsed case when the case offers one (CompiledCase), else a fresh copy."""
    readonly = getattr(case, "readonly", None)
    return readonly() if readonly is not None else case.document()


def _validate_state(doc, case, rules):
    # A fresh mutable copy: validators below check exact plain types of case data.
    case_doc = case.document()
    personal = "personal_tasks" in case_doc
    fields = {"state_schema", "game_id", "case_ref", "ruleset_ref", "rules", "rules_hash", "compiler_version", "engine_build", "sealed", "clock", "players", "npcs", "public", "knowledge", "private_events", "dialogue_cursors", "action_uses", "event_uses", "hearing", "final_ballots", "receipts", "idle_windows", "final"}
    if personal:
        fields.add("personal_story")
    for capability in ("communication", "npc_delivery"):
        if capability in case_doc:
            fields.add(capability)
    _obj(doc, fields, "state")
    if doc["state_schema"] != "night-city-state/1":
        raise ValueError("unsupported state schema")
    _str(doc["game_id"], "game_id")
    ref = _obj(doc["case_ref"], {"case_id", "case_version", "content_hash"}, "case_ref")
    _id(ref["case_id"], "case_id")
    _int(ref["case_version"], "case_version", 1)
    _hash(ref["content_hash"], "content_hash")
    if (ref["case_id"], ref["case_version"], ref["content_hash"]) != (case.case_id, case.case_version, case.content_hash):
        raise ValueError("case mismatch")
    ruleset = _obj(doc["ruleset_ref"], {"id", "version"}, "ruleset_ref")
    build = engine_build_for(ruleset)
    engine_build_for(case_doc.get("ruleset_ref"))
    if ruleset != case_doc["ruleset_ref"]:
        raise ValueError("case ruleset mismatch")
    modules = case_doc.get("module_data", {}) if ruleset["version"] == 2 else {}
    parsed_rules = RulesSnapshot.from_document(doc["rules"])
    _hash(doc["rules_hash"], "rules_hash")
    if parsed_rules != rules or doc["rules_hash"] != rules.rules_hash:
        raise ValueError("rules mismatch")
    _str(doc["compiler_version"], "compiler_version")
    if doc["compiler_version"] != case.compiler_version:
        raise ValueError("compiler mismatch")
    _str(doc["engine_build"], "engine_build")
    if doc["engine_build"] != build:
        raise ValueError("engine build mismatch")
    clock = Clock.from_document(doc["clock"])
    if clock.timezone != rules.timezone:
        raise ValueError("clock timezone mismatch")
    if clock.phase == "investigation" and clock.window_idx == 14 or clock.phase == "final_hearing" and clock.window_idx != 14:
        raise ValueError("phase/window mismatch")
    character_ids = {row["id"] for row in case_doc["characters"]}
    location_ids = {row["id"] for row in case_doc["locations"]}
    observation_ids = {row["id"] for row in case_doc["observations"]}
    fact_ids = {row["id"] for row in case_doc.get("facts", [])}
    variant_ids = {row["id"] for row in case_doc["variants"]}
    composition_ids = {row["id"] for row in case_doc["compositions"]}
    dialogue_ids = {row["id"] for row in case_doc["dialogues"]}
    action_ids = {row["id"] for row in case_doc["actions"]}
    scene_catalog = case_doc["events"] + modules.get("turning_point", {}).get("scenes", [])
    event_ids = {row["id"] for row in scene_catalog}
    sealed_fields = {"variant_id", "seed", "composition_id", "assignments"}
    # night-city-state/1 extension: sealed.looks is optional; states sealed before looks use default looks.
    sealed = _obj(doc["sealed"], sealed_fields | ({"looks"} if type(doc["sealed"]) is dict and "looks" in doc["sealed"] else set()), "sealed")
    # composition_id "open" is free seating (any playable heroes, 3..12); it is never an authored composition id.
    open_seating = sealed["composition_id"] == "open" and "open" not in composition_ids
    if sealed["variant_id"] not in variant_ids or (sealed["composition_id"] not in composition_ids and not open_seating):
        raise ValueError("unknown variant or composition")
    _int(sealed["seed"], "seed")
    if "looks" in sealed:
        authored_looks = {row["id"]: {look["id"] for look in row["looks"]} for row in case_doc["characters"] if row.get("looks")}
        looks = sealed["looks"]
        if type(looks) is not dict or set(looks) != set(authored_looks) or not looks:
            raise ValueError("sealed looks must cover exactly the characters with looks")
        for character_id, look_id in looks.items():
            if type(look_id) is not str or look_id not in authored_looks[character_id]:
                raise ValueError("unknown sealed look")
    assignments = _arr(sealed["assignments"], "assignments", 12)
    for row in assignments:
        _obj(row, {"account_id", "character_id"}, "assignment")
        _str(row["account_id"], "account_id")
        if row["character_id"] not in character_ids:
            raise ValueError("unknown assigned character")
    _unique(assignments, ("account_id",), "assignments")
    _unique(assignments, ("character_id",), "assignments")
    assigned = {r["account_id"]: r["character_id"] for r in assignments}
    variant = next(row for row in case_doc["variants"] if row["id"] == sealed["variant_id"])
    if open_seating:
        playable = {row["id"] for row in case_doc["characters"] if row.get("can_be_player")}
        if not 3 <= len(assigned) <= 12 or not set(assigned.values()) <= playable:
            raise ValueError("open seating outside the playable heroes")
    else:
        composition = next(row for row in case_doc["compositions"] if row["id"] == sealed["composition_id"])
        if "player_characters" in composition and set(assigned.values()) != set(composition["player_characters"]):
            raise ValueError("composition characters mismatch")
    if not open_seating and "composition_ids" in variant and sealed["composition_id"] not in variant["composition_ids"]:
        raise ValueError("variant incompatible with composition")
    observation_by_id = {row["id"]: row for row in case_doc["observations"]}
    def observation_exists(observation_id):
        item = observation_by_id.get(observation_id)
        if item is None:
            return False
        exists_in = item.get("exists_in")
        return exists_in == "all" or type(exists_in) is list and sealed["variant_id"] in exists_in
    players = _arr(doc["players"], "players", 12)
    for row in players:
        _obj(row, {"account_id", "character_id", "name", "status", "location", "ap", "actor_seq", "knowledge_revision", "last_seen_window", "missed_windows", "finished_window", "ghost_used_window", "accusations_used", "wrong_accusations", "participated_windows", "departed_snapshot"}, "player")
        _str(row["account_id"], "account_id")
        _id(row["character_id"], "character_id")
        _str(row["name"], "name")
        _enum(row["status"], {"active", "fog", "ghost", "departed"}, "player.status")
        if row["location"] not in location_ids:
            raise ValueError("unknown player location")
        _int(row["ap"], "ap", 0, 3)
        for key in ("actor_seq", "knowledge_revision", "missed_windows", "accusations_used", "wrong_accusations"):
            _int(row[key], key)
        _int(row["last_seen_window"], "last_seen_window", 0, 14)
        _bool(row["finished_window"], "finished_window")
        if row["ghost_used_window"] is not None:
            _int(row["ghost_used_window"], "ghost_used_window", 1, 14)
        if type(row["participated_windows"]) is not list or any(type(i) is not int or not 1 <= i <= 14 for i in row["participated_windows"]) or len(row["participated_windows"]) != len(set(row["participated_windows"])):
            raise ValueError("invalid participated_windows")
        if row["departed_snapshot"] is not None:
            snap = _obj(row["departed_snapshot"], {"location", "known_observations", "window_idx"}, "departed_snapshot")
            if snap["location"] not in location_ids:
                raise ValueError("unknown departed location")
            if not all(observation_exists(observation_id) for observation_id in _ids(snap["known_observations"], "known_observations")):
                raise ValueError("unknown departed knowledge")
            _int(snap["window_idx"], "departed.window_idx", 1, 14)
        if (row["status"] == "departed") != (row["departed_snapshot"] is not None):
            raise ValueError("departed snapshot/status mismatch")
        if row["account_id"] not in assigned or row["character_id"] != assigned[row["account_id"]]:
            raise ValueError("player assignment mismatch")
        if row["status"] in {"ghost", "departed"} and row["ap"] != 0:
            raise ValueError("inactive player AP")
    _unique(players, ("account_id",), "players")
    _unique(players, ("character_id",), "players")
    _unique(players, ("name",), "player names")
    accounts = {r["account_id"] for r in players}
    if accounts != set(assigned):
        raise ValueError("roster mismatch")
    npcs = _arr(doc["npcs"], "npcs", 24)
    for row in npcs:
        _obj(row, {"character_id", "name", "location", "status", "origin"}, "npc")
        if row["character_id"] not in character_ids or row["location"] not in location_ids:
            raise ValueError("unknown NPC reference")
        _str(row["name"], "npc.name")
        _enum(row["status"], {"active", "removed"}, "npc.status")
        _enum(row["origin"], {"authored", "former_player"}, "npc.origin")
    _unique(npcs, ("character_id",), "npcs")
    _unique(npcs, ("name",), "npc names")
    player_by_name = {r["name"]: r for r in players}
    for npc in npcs:
        previous = player_by_name.get(npc["name"])
        if previous is not None and not (previous["character_id"] == npc["character_id"] and previous["status"] == "departed" and npc["origin"] == "former_player"):
            raise ValueError("PC and NPC name collision")
    npc_chars = {r["character_id"] for r in npcs}
    if any(r["character_id"] in npc_chars and r["status"] != "departed" for r in players):
        raise ValueError("active PC also NPC")
    former_by_char = {r["character_id"] for r in npcs if r["origin"] == "former_player"}
    if former_by_char != {r["character_id"] for r in players if r["status"] == "departed"}:
        raise ValueError("former NPC/departed player mismatch")
    if any(r["character_id"] in {p["character_id"] for p in players} and r["origin"] != "former_player" for r in npcs):
        raise ValueError("PC character has authored NPC controller")
    if {r["character_id"] for r in players} | npc_chars != character_ids:
        raise ValueError("missing character controller")
    if any(r["origin"] == "former_player" and r["character_id"] not in {p["character_id"] for p in players if p["status"] == "departed"} for r in npcs):
        raise ValueError("impossible former player")
    public = _obj(doc["public"], {"flags", "locks", "observations", "board", "chronicle", "revision", "framed_count"}, "public")
    for key in ("revision", "framed_count"):
        _int(public[key], key)
    for row in _arr(public["flags"], "flags"):
        _obj(row, {"id", "value"}, "flag")
        _id(row["id"], "flag.id")
        _bool(row["value"], "flag.value")
    _unique(public["flags"], ("id",), "flags")
    if {r["id"] for r in public["flags"]} != {r["id"] for r in case_doc["flags"]}:
        raise ValueError("flag set mismatch")
    for row in _arr(public["locks"], "locks"):
        _obj(row, {"location", "through_window"}, "lock")
        if row["location"] not in location_ids:
            raise ValueError("unknown lock location")
        _int(row["through_window"], "through_window", 1, 14)
    _unique(public["locks"], ("location",), "locks")
    for row in _arr(public["observations"], "public.observations"):
        _obj(row, {"observation_id", "source"}, "public.observation")
        if not observation_exists(row["observation_id"]):
            raise ValueError("unknown public observation")
        _source(row["source"])
        if row["source"]["actor_character"] is not None and row["source"]["actor_character"] not in character_ids or row["source"]["location"] is not None and row["source"]["location"] not in location_ids:
            raise ValueError("unknown public source reference")
        if row["source"]["kind"] not in {"initial", "event"} or row["source"]["actor_character"] is not None or row["source"]["location"] is not None:
            raise ValueError("public observation leaks private provenance")
    _unique(public["observations"], ("observation_id",), "public.observations")
    board = _arr(public["board"], "board")
    for row in board:
        _obj(row, {"id", "owner_account_id", "kind", "observation_id", "text", "source"}, "board entry")
        _str(row["id"], "board.id", 1, 128)
        if row["owner_account_id"] not in accounts:
            raise ValueError("unknown board owner")
        _enum(row["kind"], {"proof", "claim"}, "board.kind")
        if row["observation_id"] is not None:
            if not observation_exists(row["observation_id"]) or row["text"] is not None or row["source"] is None:
                raise ValueError("invalid authored board entry")
            observation = observation_by_id[row["observation_id"]]
            if row["kind"] != observation["kind"]:
                raise ValueError("authored board kind mismatch")
            _source(row["source"])
        else:
            if row["kind"] != "claim" or row["source"] is not None:
                raise ValueError("free claim cannot assert source")
            _str(row["text"], "board.text", 1, 1200)
    _unique(board, ("id",), "board")
    board_ids = {r["id"] for r in board}
    for row in _arr(doc["knowledge"], "knowledge"):
        _obj(row, {"account_id", "observation_id", "source"}, "knowledge")
        if row["account_id"] not in accounts or not observation_exists(row["observation_id"]):
            raise ValueError("unknown knowledge reference")
        _source(row["source"])
        if row["source"]["actor_character"] is not None and row["source"]["actor_character"] not in character_ids or row["source"]["location"] is not None and row["source"]["location"] not in location_ids:
            raise ValueError("unknown knowledge source reference")
    _unique(doc["knowledge"], ("account_id", "observation_id"), "knowledge")
    for row in _arr(doc["dialogue_cursors"], "dialogue_cursors"):
        _obj(row, {"account_id", "dialogue_id", "node_id"}, "dialogue_cursor")
        if row["account_id"] not in accounts or row["dialogue_id"] not in dialogue_ids:
            raise ValueError("unknown dialogue cursor")
        _id(row["node_id"], "node_id")
    _unique(doc["dialogue_cursors"], ("account_id", "dialogue_id"), "dialogue_cursors")
    for row in _arr(doc["action_uses"], "action_uses"):
        _obj(row, {"account_id", "action_key", "window_idx"}, "action_use")
        if row["account_id"] not in accounts or row["action_key"] not in action_ids:
            raise ValueError("unknown action use")
        if row["window_idx"] is not None:
            _int(row["window_idx"], "action_use.window_idx", 1, 14)
    _unique(doc["action_uses"], ("account_id", "action_key", "window_idx"), "action_uses")
    _ids(doc["event_uses"], "event_uses")
    if not set(doc["event_uses"]) <= event_ids:
        raise ValueError("unknown event use")
    last_opened_window = clock.window_idx - 1 if clock.opening_pending else clock.window_idx
    event_windows = {row["id"]: row.get("window", row.get("not_before")) for row in scene_catalog}
    if any(event_windows[event_id] > last_opened_window for event_id in doc["event_uses"]):
        raise ValueError("future content event marked used")
    if doc["hearing"] is not None:
        hearing = _obj(doc["hearing"], {"id", "accuser", "suspect", "opened_window", "resolve_window", "eligible_accounts", "initial_citations", "votes"}, "hearing")
        _str(hearing["id"], "hearing.id")
        if hearing["accuser"] not in accounts or hearing["suspect"] not in character_ids:
            raise ValueError("unknown hearing reference")
        for field in ("opened_window", "resolve_window"):
            _int(hearing[field], field, 1, 14)
        if hearing["resolve_window"] != hearing["opened_window"] + 1:
            raise ValueError("invalid hearing duration")
        if clock.phase != "investigation" or not 3 <= hearing["opened_window"] <= 12 or not hearing["opened_window"] <= clock.window_idx <= hearing["resolve_window"]:
            raise ValueError("hearing outside ordinary window")
        if not _ids(hearing["eligible_accounts"], "eligible_accounts", typed=False) <= accounts:
            raise ValueError("unknown eligible account")
        if not _ids(hearing["initial_citations"], "initial_citations", typed=False, maximum=5) <= board_ids:
            raise ValueError("unknown initial citation")
        for vote in _arr(hearing["votes"], "hearing.votes", 12):
            _obj(vote, {"account_id", "choice", "citations"}, "vote")
            if vote["account_id"] not in hearing["eligible_accounts"]:
                raise ValueError("ineligible voter")
            _enum(vote["choice"], {"support", "oppose"}, "vote.choice")
            if not _ids(vote["citations"], "vote.citations", typed=False, maximum=5) <= board_ids:
                raise ValueError("unknown vote citation")
        _unique(hearing["votes"], ("account_id",), "hearing.votes")
    for ballot in _arr(doc["final_ballots"], "final_ballots", 12):
        _obj(ballot, {"account_id", "suspect", "citations"}, "final_ballot")
        if ballot["account_id"] not in accounts or ballot["suspect"] is not None and ballot["suspect"] not in character_ids:
            raise ValueError("unknown final ballot reference")
        if not _ids(ballot["citations"], "ballot.citations", typed=False, maximum=5) <= board_ids:
            raise ValueError("unknown ballot citation")
    _unique(doc["final_ballots"], ("account_id",), "final_ballots")
    if doc["final_ballots"] and not (clock.phase in {"final_hearing", "finished"} and clock.window_idx == 14):
        raise ValueError("final ballots outside final hearing")
    for event in _arr(public["chronicle"], "chronicle"):
        _event(event, private=False, modules=modules, personal=personal)
    for event in _arr(doc["private_events"], "private_events"):
        _event(event, private=True, modules=modules, personal=personal)
        if not set(event["audience"]["ids"]) <= accounts:
            raise ValueError("private event audience mismatch")
    all_events = public["chronicle"] + doc["private_events"]
    _unique(all_events, ("event_id",), "events")
    all_event_by_id = {e["event_id"]: e for e in all_events}
    streams = {}
    for event in all_events:
        scope = event_scope(event["audience"])
        if event["event_id"] != event_id_for(doc["game_id"], event["audience"], event["audience_seq"]):
            raise ValueError("event ID does not match audience stream")
        if event["window_idx"] > clock.window_idx:
            raise ValueError("event from future window")
        if clock.phase == "frozen" and event["window_idx"] == clock.window_idx:
            frozen_header = event["kind"] == "window" and event["payload"]["phase"] == "frozen"
            frozen_forfeit = event["kind"] == "status" and event["payload"]["controller"] == "npc" and event["payload"]["status"] == "active" and event["payload"]["character_id"] in former_by_char
            # Personal validation below requires the exact offer, both audiences,
            # and the same command batch's participant cutoff for this exception.
            frozen_return_cancel = personal and event["kind"] == "story_return_closed" and event["payload"]["decision"] == "cancelled"
            if not (frozen_header or frozen_forfeit or frozen_return_cancel):
                raise ValueError("pending frozen window has no opening events")
        streams.setdefault(scope, []).append(event)
    if [e["audience_seq"] for e in public["chronicle"]] != list(range(1, len(public["chronicle"]) + 1)):
        raise ValueError("public chronicle not in stream order")
    for scope, events_in_scope in streams.items():
        ordered = sorted(events_in_scope, key=lambda e: e["audience_seq"])
        if [e["audience_seq"] for e in ordered] != list(range(1, len(ordered) + 1)):
            raise ValueError("event stream has sequence gap or duplicate")
        if [e["window_idx"] for e in ordered] != sorted(e["window_idx"] for e in ordered):
            raise ValueError("backdated event stream")
    board_by_id = {item["id"]: item for item in board}
    seen_digests = set()
    for event in doc["private_events"]:
        if event["kind"] != "window_digest":
            continue
        account = event["audience"]["ids"][0]
        key = (account, event["window_idx"])
        if key in seen_digests:
            raise ValueError("duplicate window digest")
        seen_digests.add(key)
        if event["window_idx"] == 1:
            eligible = lambda item: item["window_idx"] == 1 and item["kind"] == "observation_granted" and item["payload"]["source"]["kind"] == "initial"
        else:
            previous = event["window_idx"] - 1
            eligible = lambda item: item["window_idx"] == previous and item["kind"] not in {"window_digest", "afk_notice"}
        public_candidates = [item for item in public["chronicle"] if eligible(item)]
        own_candidates = [item for item in streams.get("account:" + account, []) if item["audience_seq"] < event["audience_seq"] and eligible(item)]
        public_candidates.sort(key=lambda item: item["audience_seq"])
        own_candidates.sort(key=lambda item: item["audience_seq"])
        selected = (public_candidates + own_candidates)[-64:]
        expected_ids = [item["event_id"] for item in selected]
        if event["payload"]["event_ids"] != expected_ids:
            raise ValueError("digest event selection mismatch")
        selected_observations = set()
        for item in selected:
            payload = item["payload"]
            if item["kind"] == "observation_granted":
                selected_observations.add(payload["observation_id"])
            elif item["kind"] in {"action_result", "archive_response", "story_result"}:
                selected_observations.update(payload["observation_ids"])
            elif item["kind"] == "authored_card_delivered":
                selected_observations.add(payload["observation_id"])
            elif item["kind"] == "board":
                board_item = board_by_id.get(payload["board_id"])
                if board_item is None:
                    raise ValueError("digest board reference missing")
                if board_item["observation_id"] is not None:
                    selected_observations.add(board_item["observation_id"])
        if event["payload"]["observation_ids"] != sorted(selected_observations):
            raise ValueError("digest observation selection mismatch")
    for item in public["observations"]:
        source = item["source"]
        if source["kind"] in {"initial", "event"}:
            origin = all_event_by_id.get(source["source_id"])
            card_origin = personal and origin is not None and origin["kind"] == "authored_card_delivered" and source == {"kind": "event", "source_id": origin["event_id"], "actor_character": None, "location": None, "window_idx": origin["window_idx"]}
            if origin is None or origin not in public["chronicle"] or origin["kind"] not in ({"observation_granted", "authored_card_delivered"} if personal else {"observation_granted"}) or origin["payload"]["observation_id"] != item["observation_id"] or not card_origin and origin["payload"].get("source") != source:
                raise ValueError("public observation has no matching public grant")
            if source["kind"] == "initial" and item["observation_id"] not in case_doc["initial"]["public_observations"]:
                raise ValueError("unauthored initial public observation")
    published_board = set()
    grounded_proofs = set()
    public_observation_by_id = {item["observation_id"]: item for item in public["observations"]}
    for event in public["chronicle"]:
        if event["kind"] != "board":
            continue
        board_id = event["payload"]["board_id"]
        entry = board_by_id.get(board_id)
        if entry is None or board_id in published_board:
            raise ValueError("board entry lacks unique public publication")
        if entry["observation_id"] is not None:
            observation_id, source = entry["observation_id"], entry["source"]
            if source["window_idx"] > event["window_idx"]:
                raise ValueError("board source comes from a future window")
            signature = (observation_id, _json_bytes(source), entry["kind"])
            own_knowledge = any(item["account_id"] == entry["owner_account_id"] and item["observation_id"] == observation_id and item["source"] == source for item in doc["knowledge"])
            public_item = public_observation_by_id.get(observation_id)
            public_root = public_item is not None and public_item["source"] == source
            if public_root and source["kind"] == "event":
                grant = all_event_by_id.get(source["source_id"])
                public_root = grant is not None and grant["audience_seq"] <= event["audience_seq"]
            if not (own_knowledge or public_root or signature in grounded_proofs):
                raise ValueError("authored board entry has no prior visible source")
            grounded_proofs.add(signature)
        published_board.add(board_id)
    if published_board != board_ids:
        raise ValueError("board entry not publicly published")
    known_by_account = {}
    for item in doc["knowledge"]:
        known_by_account.setdefault(item["account_id"], set()).add(item["observation_id"])
    public_observation_ids = {r["observation_id"] for r in public["observations"]}
    public_board_proofs = {r["observation_id"] for r in board if r["observation_id"] is not None}
    for event in all_events:
        payload = event["payload"]
        kind = event["kind"]
        if kind in {"status", "hearing"}:
            target = payload["character_id"] if kind == "status" else payload["suspect"]
            if target not in character_ids:
                raise ValueError("event character reference")
        elif kind == "observation_granted":
            if not observation_exists(payload["observation_id"]):
                raise ValueError("event observation reference")
            if event["audience"]["kind"] == "accounts" and payload["observation_id"] not in known_by_account.get(event["audience"]["ids"][0], set()):
                raise ValueError("private grant not retained as knowledge")
            if event["audience"]["kind"] == "public" and payload["observation_id"] not in public_observation_ids:
                raise ValueError("public grant not retained")
        elif kind in {"action_result", "story_result"}:
            account = event["audience"]["ids"][0]
            if not set(payload["observation_ids"]) <= known_by_account.get(account, set()) | public_observation_ids | public_board_proofs:
                raise ValueError("action result reveals unowned observation")
        elif kind == "window_digest":
            account = event["audience"]["ids"][0]
            if not set(payload["observation_ids"]) <= known_by_account.get(account, set()) | public_observation_ids | public_board_proofs:
                raise ValueError("digest reveals unowned observation")
            for event_id in payload["event_ids"]:
                referenced = all_event_by_id.get(event_id)
                if referenced is None or referenced is event or referenced["audience"]["kind"] == "accounts" and account not in referenced["audience"]["ids"]:
                    raise ValueError("digest references unavailable event")
        elif kind == "board":
            if payload["board_id"] not in board_ids:
                raise ValueError("board event has no board entry")
        elif kind == "scene":
            if payload["content_event_id"] not in event_ids:
                raise ValueError("unknown scheduled scene")
            authored = next(item for item in scene_catalog if item["id"] == payload["content_event_id"])
            if payload["body"] != authored["body"]:
                raise ValueError("scene body differs from authored event")
        elif kind == "world_changed":
            if not {r["id"] for r in payload["flags"]} <= {r["id"] for r in public["flags"]} or not {r["location"] for r in payload["locks"]} <= location_ids:
                raise ValueError("unknown world change reference")
        if kind in {"action_result", "scene", "story_result", "story_offer", "story_epilogue", "authored_card_delivered"} and not set(payload["body"]["mentions"]) <= fact_ids:
            raise ValueError("event body mentions unknown fact")
    if modules:
        _validate_modules(doc, case_doc, modules, streams, all_event_by_id)
    private_event_ids = {r["event_id"] for r in doc["private_events"]}
    for row in _arr(doc["receipts"], "receipts"):
        _obj(row, {"actor_key", "command_id", "payload_hash", "accepted", "code", "actor_revision", "result_ref"}, "receipt")
        if row["actor_key"] != "system" and row["actor_key"] not in {"account:" + account for account in accounts}:
            raise ValueError("unknown receipt actor")
        _str(row["command_id"], "receipt.command_id", 8, 64)
        _hash(row["payload_hash"], "receipt.payload_hash")
        _bool(row["accepted"], "receipt.accepted")
        _str(row["code"], "receipt.code")
        _int(row["actor_revision"], "actor_revision")
        if row["result_ref"] is not None:
            result = row["result_ref"]
            if "communication" in case_doc and type(result) is dict and result.get("kind") == "message":
                from domain.night_case_delivery_state import validate_message_ref
                validate_message_ref(result, row, doc["game_id"], accounts, clock.window_idx)
            else:
                _obj(result, {"kind", "event_id"}, "result_ref")
                if result["kind"] != "event" or result["event_id"] not in private_event_ids:
                    raise ValueError("dangling private result")
                event = next(e for e in doc["private_events"] if e["event_id"] == result["event_id"])
                if row["actor_key"] == "system" or row["actor_key"][8:] not in event["audience"]["ids"]:
                    raise ValueError("result audience mismatch")
    _unique(doc["receipts"], ("actor_key", "command_id"), "receipts")
    _int(doc["idle_windows"], "idle_windows", 0, 14)
    if doc["final"] is not None:
        final = _obj(doc["final"], {"code", "at", "variant_id", "culprit", "key_proofs", "goal_results", "reward_facts"}, "final")
        _enum(final["code"], {"solved", "shadow_framed", "no_investigators", "unresolved", "forgotten"}, "final.code")
        _timestamp(final["at"], "final.at")
        if final["variant_id"] != sealed["variant_id"] or final["culprit"] not in character_ids or "culprit" in variant and final["culprit"] != variant["culprit"]:
            raise ValueError("final truth mismatch")
        if not _ids(final["key_proofs"], "final.key_proofs") <= observation_ids:
            raise ValueError("unknown final proof")
        if "key_proofs" in variant and not set(final["key_proofs"]) <= set(variant["key_proofs"]):
            raise ValueError("non-key final proof")
        for result in _arr(final["goal_results"], "goal_results", 12):
            _obj(result, {"account_id", "goal_id", "met"}, "goal_result")
            if result["account_id"] not in accounts:
                raise ValueError("unknown goal account")
            _id(result["goal_id"], "goal_id")
            _bool(result["met"], "goal.met")
        _unique(final["goal_results"], ("account_id",), "goal_results")
        if {r["account_id"] for r in final["goal_results"]} != accounts:
            raise ValueError("incomplete goal results")
        for fact in _arr(final["reward_facts"], "reward_facts", 12):
            _obj(fact, {"account_id", "participated_windows", "total_windows", "completed", "goal_met", "faction_won", "wrong_accusations"}, "reward_fact")
            if fact["account_id"] not in accounts:
                raise ValueError("unknown reward account")
            for key in ("participated_windows", "total_windows", "wrong_accusations"):
                _int(fact[key], key, 0, 14 if key != "wrong_accusations" else 2**63 - 1)
            for key in ("completed", "goal_met", "faction_won"):
                _bool(fact[key], key)
        _unique(final["reward_facts"], ("account_id",), "reward_facts")
        if {r["account_id"] for r in final["reward_facts"]} != accounts:
            raise ValueError("incomplete reward facts")
    if (clock.phase == "finished") != (doc["final"] is not None):
        raise ValueError("final phase mismatch")
    if personal:
        from domain.night_case_personal_state import validate_personal_state
        validate_personal_state(case_doc, doc)
    if "communication" in case_doc or "npc_delivery" in case_doc:
        from domain.night_case_delivery_state import validate_delivery_state
        validate_delivery_state(case_doc, doc)


class KernelState(_Snapshot):
    __slots__ = ("_max_bytes", "_max_nodes", "_validated")

    def __init__(self, document, *, ruleset_version=1):
        _int(ruleset_version, "snapshot ruleset version", 1, 2)
        max_bytes, max_nodes = (16 * 1024 * 1024, 500000) if ruleset_version == 2 else (MAX_BYTES, 100000)
        object.__setattr__(self, "_max_bytes", max_bytes)
        object.__setattr__(self, "_max_nodes", max_nodes)
        object.__setattr__(self, "_bytes", _json_bytes(document, max_bytes=max_bytes, max_nodes=max_nodes))
        # (case, rules) this exact snapshot was produced by from_document for;
        # a plainly constructed snapshot is never treated as validated.
        object.__setattr__(self, "_validated", None)

    def validated_for(self, case, rules):
        """This snapshot if from_document already produced it for an equal case and rules,
        else a freshly validated one. from_document is deterministic and idempotent on
        its own output, so the result is identical to from_document(self.document(), ...)."""
        seen = self._validated
        if seen is not None and (seen[0] is case or seen[0] == case) and (seen[1] is rules or seen[1] == rules):
            return self
        return KernelState.from_document(self.document(), case, rules)

    def document(self):
        return _load(self._bytes, max_bytes=self._max_bytes, max_nodes=self._max_nodes)

    @classmethod
    def from_document(cls, raw, case, rules):
        doc = copy.deepcopy(raw)
        _validate_state(doc, case, rules)
        doc["sealed"]["assignments"].sort(key=lambda row: row["account_id"])
        doc["clock"]["resume_receipts"].sort(key=lambda row: row["outage_id"])
        doc["event_uses"].sort()
        doc["final_ballots"].sort(key=lambda row: row["account_id"])
        for player in doc["players"]:
            player["participated_windows"].sort()
        if doc["hearing"] is not None:
            doc["hearing"]["votes"].sort(key=lambda row: row["account_id"])
        if doc["final"] is not None:
            doc["final"]["goal_results"].sort(key=lambda row: row["account_id"])
            doc["final"]["reward_facts"].sort(key=lambda row: row["account_id"])
        doc["private_events"].sort(key=lambda event: (event_scope(event["audience"]), event["audience_seq"]))
        for path, keys in (("players", ("account_id",)), ("npcs", ("character_id",)), ("knowledge", ("account_id", "observation_id")), ("dialogue_cursors", ("account_id", "dialogue_id")), ("action_uses", ("account_id", "action_key", "window_idx")), ("receipts", ("actor_key", "command_id"))):
            doc[path].sort(key=lambda row: tuple(str(row[k]) for k in keys))
        for path, keys in (("flags", ("id",)), ("locks", ("location",)), ("observations", ("observation_id",)), ("board", ("id",))):
            doc["public"][path].sort(key=lambda row: tuple(str(row[k]) for k in keys))
        if "communication" in doc:
            doc["communication"]["sent"].sort(key=lambda r: (r["account_id"], r["window_idx"]))
        if "npc_delivery" in doc:
            doc["npc_delivery"]["lines"].sort(key=lambda r: (r["npc"], r["topic"], r["window_idx"]))
            doc["npc_delivery"]["decisions"].sort(key=lambda r: (r["scope"]["npc_id"], r["scope"]["topic_id"], r["scope"]["window_idx"], r["rule_version"]))
        state = cls(doc, ruleset_version=_case_doc(case)["ruleset_ref"]["version"])
        object.__setattr__(state, "_validated", (case, rules))
        return state


def encode_state(state: KernelState) -> bytes:
    if type(state) is not KernelState:
        raise ValueError("expected KernelState")
    return state._bytes


def decode_state(raw: bytes, case, rules) -> KernelState:
    ref = _case_doc(case)["ruleset_ref"]
    engine_build_for(ref)
    limits = {"max_bytes": 16 * 1024 * 1024, "max_nodes": 500000} if ref["version"] == 2 else {}
    return KernelState.from_document(_load(raw, **limits), case, rules)
