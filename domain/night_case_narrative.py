"""Pure decisions at the Night City narrator boundary.

Callers provide authorized views/actions and persist decisions atomically later.
Free prose is structurally checked here, never proved semantically safe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any


MAX_TEXT = 4000
MAX_FALLBACK = 4000
MAX_ITEMS = 64
MAX_FACT_TEXT = 1200
MAX_CONTEXT_TEXT = 16000
MAX_SLIP_CODEC_BYTES = 16 * 1024
MAX_SLIP_CODEC_DEPTH = 8
SLIP_CODEC_SCHEMA = "night-city-slip/1"
JOB_KINDS = frozenset({"window_digest", "npc_reply", "scene_narration", "story_offer"})
EPISODE_KINDS = frozenset({"scene_narration", "npc_reply", "window_digest", "story_offer"})


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware UTC datetime required")
    if value.utcoffset().total_seconds() != 0:
        raise ValueError("UTC datetime required")
    return value.astimezone(timezone.utc)


def _nonempty(value: str, label: str, *, limit: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"invalid {label}")
    return value


def _strings(values: Any, label: str, *, max_length: int = 128) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)) or len(values) > MAX_ITEMS:
        raise ValueError(f"invalid {label}")
    result = tuple(_nonempty(v, label, limit=max_length) for v in values)
    if len(set(result)) != len(result):
        raise ValueError(f"duplicate {label}")
    return result


def _json_value(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        raise ValueError("parameters too deep")
    if value is None or isinstance(value, (str, bool)) or type(value) is int:
        return value
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_ITEMS:
            raise ValueError("too many parameters")
        return [_json_value(v, depth + 1) for v in value]
    if isinstance(value, dict):
        if len(value) > MAX_ITEMS or any(not isinstance(k, str) for k in value):
            raise ValueError("invalid parameters")
        return {k: _json_value(v, depth + 1) for k, v in sorted(value.items())}
    raise ValueError("unsupported parameter value")


def _snapshot(value: Any) -> str:
    """Immutable, type-preserving canonical JSON of a command's parameters."""
    return json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class NarrationView:
    audience: str
    audience_key: str
    facts: tuple[str, ...]
    references: tuple[str, ...]
    catalog_ids: tuple[str, ...]
    knowledge_revision: str
    window_idx: int
    case_hash: str
    ruleset_version: str

    def __post_init__(self) -> None:
        _nonempty(self.audience, "audience")
        _nonempty(self.audience_key, "audience key")
        facts = _strings(self.facts, "facts", max_length=MAX_FACT_TEXT)
        if sum(map(len, facts)) > MAX_CONTEXT_TEXT:
            raise ValueError("facts context too long")
        object.__setattr__(self, "facts", facts)
        object.__setattr__(self, "references", _strings(self.references, "references"))
        object.__setattr__(self, "catalog_ids", _strings(self.catalog_ids, "catalog IDs"))
        _nonempty(self.knowledge_revision, "knowledge revision")
        _nonempty(self.case_hash, "case hash")
        _nonempty(self.ruleset_version, "ruleset version")
        if type(self.window_idx) is not int or self.window_idx < 0:
            raise ValueError("invalid window")


@dataclass(frozen=True)
class NarrativeJob:
    job_id: str
    cause_id: str
    kind: str
    expires_at: datetime
    fallback: str
    view: NarrationView

    @property
    def request_token(self) -> str:
        # Opaque correlation value; provider never sees internal IDs or scope.
        parts = [self.job_id, self.cause_id, self.kind, self.view.audience,
                 self.view.audience_key, self.view.knowledge_revision,
                 self.view.window_idx, self.view.case_hash, self.view.ruleset_version]
        raw = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @property
    def provider_payload(self) -> dict[str, Any]:
        # Internal routing and secret scope identifiers stay outside this payload.
        return {"request_token": self.request_token, "kind": self.kind, "facts": list(self.view.facts),
                "references": list(self.view.references), "catalog_ids": list(self.view.catalog_ids)}


def build_narrative_job(view: NarrationView, *, job_id: str, cause_id: str,
                        kind: str, expires_at: datetime, fallback: str) -> NarrativeJob:
    if not isinstance(view, NarrationView):
        raise ValueError("authorized NarrationView required")
    if kind not in JOB_KINDS:
        raise ValueError("unknown job kind")
    if not isinstance(fallback, str) or not fallback or len(fallback) > MAX_FALLBACK:
        raise ValueError("invalid fallback")
    return NarrativeJob(_nonempty(job_id, "job ID"), _nonempty(cause_id, "cause ID"),
                        kind, _utc(expires_at), fallback, view)


@dataclass(frozen=True)
class RenderingDecision:
    text: str
    source: str
    references: tuple[str, ...] = ()
    catalog_ids: tuple[str, ...] = ()


def validate_narrative_result(job: NarrativeJob, result: Any, *, now: datetime) -> RenderingDecision:
    _utc(now)
    fallback = RenderingDecision(job.fallback, "fallback")
    if now >= job.expires_at or not isinstance(result, dict):
        return fallback
    if set(result) != {"request_token", "kind", "text", "references", "catalog_ids"}:
        return fallback
    if result["request_token"] != job.request_token or result["kind"] != job.kind:
        return fallback
    text = result["text"]
    if not isinstance(text, str) or not text or len(text) > MAX_TEXT:
        return fallback
    try:
        refs = _strings(result["references"], "references")
        ids = _strings(result["catalog_ids"], "catalog IDs")
    except ValueError:
        return fallback
    if not set(refs).issubset(job.view.references) or not set(ids).issubset(job.view.catalog_ids):
        return fallback
    return RenderingDecision(text, "candidate", refs, ids)


@dataclass(frozen=True)
class LegalAction:
    selection_id: str
    kind: str
    target_id: str
    cost: int
    resource_id: str
    params: Any = field(default_factory=dict)
    resource_revision: str = "0"

    def __post_init__(self) -> None:
        for name in ("selection_id", "kind", "target_id", "resource_id"):
            _nonempty(getattr(self, name), name)
        _nonempty(self.resource_revision, "resource revision")
        if type(self.cost) is not int or self.cost < 0:
            raise ValueError("invalid cost")
        object.__setattr__(self, "params", _snapshot(self.params))


@dataclass(frozen=True)
class ActionContext:
    game_id: str
    actor_id: str
    window_idx: int
    window_seq: int
    now: datetime

    def __post_init__(self) -> None:
        _nonempty(self.game_id, "game ID")
        _nonempty(self.actor_id, "actor ID")
        if any(type(v) is not int or v < 0 for v in (self.window_idx, self.window_seq)):
            raise ValueError("invalid window fence")
        object.__setattr__(self, "now", _utc(self.now))


@dataclass(frozen=True)
class ActionProposal:
    proposal_id: str
    game_id: str
    actor_id: str
    selection_id: str
    kind: str
    target_id: str
    cost: int
    resource_id: str
    resource_revision: str
    params: Any
    window_idx: int
    window_seq: int
    created_at: datetime
    expires_at: datetime


def _selected(selection_id: str, legal_actions: Any) -> LegalAction:
    if not isinstance(selection_id, str):
        raise ValueError("one selection ID required")
    matches = [a for a in legal_actions if isinstance(a, LegalAction) and a.selection_id == selection_id]
    if len(matches) != 1:
        raise ValueError("selection unavailable or ambiguous")
    return matches[0]


def propose_action(selection_id: str, legal_actions: Any, context: ActionContext, *,
                   proposal_id: str, expires_at: datetime) -> ActionProposal:
    expires = _utc(expires_at)
    if expires <= context.now:
        raise ValueError("proposal already expired")
    action = _selected(selection_id, legal_actions)
    return ActionProposal(_nonempty(proposal_id, "proposal ID"), context.game_id,
                          context.actor_id, action.selection_id, action.kind,
                          action.target_id, action.cost, action.resource_id,
                          action.resource_revision, action.params, context.window_idx, context.window_seq,
                          context.now, expires)


@dataclass(frozen=True)
class AuthorizedCommand:
    command_id: str
    game_id: str
    actor_id: str
    kind: str
    target_id: str
    cost: int
    resource_id: str
    resource_revision: str
    params: Any
    window_idx: int
    window_seq: int


def confirm_action(proposal: ActionProposal, context: ActionContext, legal_actions: Any, *,
                   now: datetime) -> AuthorizedCommand:
    instant = _utc(now)
    if instant >= proposal.expires_at or instant < proposal.created_at:
        raise ValueError("proposal expired or clock invalid")
    if (context.game_id, context.actor_id, context.window_idx, context.window_seq) != (
        proposal.game_id, proposal.actor_id, proposal.window_idx, proposal.window_seq
    ):
        raise ValueError("stale proposal context")
    current = _selected(proposal.selection_id, legal_actions)
    if (current.kind, current.target_id, current.cost, current.resource_id, current.resource_revision, current.params) != (
        proposal.kind, proposal.target_id, proposal.cost, proposal.resource_id, proposal.resource_revision, proposal.params
    ):
        raise ValueError("action changed")
    # Stable 8–64 character ID; persistence must still enforce exactly-once semantics.
    raw = json.dumps([proposal.game_id, proposal.actor_id, proposal.proposal_id],
                     ensure_ascii=False, separators=(",", ":"))
    command_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return AuthorizedCommand(command_id, proposal.game_id, proposal.actor_id,
                             proposal.kind, proposal.target_id, proposal.cost,
                             proposal.resource_id, proposal.resource_revision, proposal.params, proposal.window_idx,
                             proposal.window_seq)


@dataclass(frozen=True)
class SlipRule:
    rule_id: str
    version: int
    probability_bp: int
    fact_id: str

    def __post_init__(self) -> None:
        _nonempty(self.rule_id, "rule ID")
        _nonempty(self.fact_id, "fact ID")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("invalid rule version")
        if type(self.probability_bp) is not int or not 0 <= self.probability_bp <= 10000:
            raise ValueError("invalid probability")


@dataclass(frozen=True)
class SlipScope:
    game_id: str
    npc_id: str
    topic_id: str
    window_idx: int

    def __post_init__(self) -> None:
        for name in ("game_id", "npc_id", "topic_id"):
            _nonempty(getattr(self, name), name)
        if type(self.window_idx) is not int or self.window_idx < 0:
            raise ValueError("invalid window")


@dataclass(frozen=True)
class SlipDecision:
    scope: SlipScope
    rule_id: str
    rule_version: int
    probability_bp: int
    fact_id: str
    revealed: bool
    draw: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.scope, SlipScope):
            raise ValueError("invalid slip scope")
        _nonempty(self.rule_id, "rule ID")
        _nonempty(self.fact_id, "fact ID")
        if type(self.rule_version) is not int or self.rule_version < 1:
            raise ValueError("invalid rule version")
        if type(self.probability_bp) is not int or not 0 <= self.probability_bp <= 10000:
            raise ValueError("invalid probability")
        if type(self.revealed) is not bool:
            raise ValueError("invalid slip outcome")
        if self.draw is None:
            if self.revealed:
                raise ValueError("revealed slip requires a draw")
        elif type(self.draw) is not int or not 0 <= self.draw <= 9999:
            raise ValueError("invalid slip draw")
        elif self.revealed != (self.draw < self.probability_bp):
            raise ValueError("slip outcome does not match draw and probability")


@dataclass(frozen=True)
class SlipResolution:
    decision: SlipDecision
    reused: bool
    budget_delta: int


def decide_slip(rule: SlipRule, scope: SlipScope, *, previous: SlipDecision | None,
                remaining_budget: int, draw: int) -> SlipResolution:
    if type(remaining_budget) is not int or remaining_budget < 0:
        raise ValueError("invalid budget")
    if type(draw) is not int or not 0 <= draw <= 9999:
        raise ValueError("invalid draw")
    if previous is not None:
        if not isinstance(previous, SlipDecision) or (
            previous.scope, previous.rule_id, previous.rule_version,
            previous.probability_bp, previous.fact_id
        ) != (
            scope, rule.rule_id, rule.version, rule.probability_bp, rule.fact_id
        ):
            raise ValueError("previous decision belongs to another scope/rule")
        return SlipResolution(previous, True, 0)
    eligible = remaining_budget > 0 and rule.probability_bp > 0
    decision = SlipDecision(scope, rule.rule_id, rule.version, rule.probability_bp, rule.fact_id,
                            eligible and draw < rule.probability_bp, draw if eligible else None)
    return SlipResolution(decision, False, -1 if decision.revealed else 0)


def slip_decision_to_json(decision: SlipDecision) -> str:
    if not isinstance(decision, SlipDecision):
        raise ValueError("slip decision required")
    encoded = json.dumps({"schema": SLIP_CODEC_SCHEMA,
                          "scope": {"game_id": decision.scope.game_id,
                                 "npc_id": decision.scope.npc_id,
                                 "topic_id": decision.scope.topic_id,
                                 "window_idx": decision.scope.window_idx},
                       "rule_id": decision.rule_id, "rule_version": decision.rule_version,
                       "probability_bp": decision.probability_bp,
                       "fact_id": decision.fact_id, "revealed": decision.revealed,
                       "draw": decision.draw}, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_SLIP_CODEC_BYTES:
        raise ValueError("slip decision too large")
    return encoded


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON number")
    return parsed


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _check_slip_json_depth(value: Any) -> None:
    stack = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_SLIP_CODEC_DEPTH:
            raise ValueError("slip decision too deep")
        if isinstance(node, dict):
            stack.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            stack.extend((child, depth + 1) for child in node)


def slip_decision_from_json(raw: str | bytes) -> SlipDecision:
    if isinstance(raw, str):
        try:
            raw_bytes = raw.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("invalid slip decision encoding") from exc
    elif isinstance(raw, bytes):
        raw_bytes = raw
    else:
        raise ValueError("slip decision JSON must be text or bytes")
    if len(raw_bytes) > MAX_SLIP_CODEC_BYTES:
        raise ValueError("slip decision too large")
    try:
        text = raw_bytes.decode("utf-8")
        data = json.loads(text, object_pairs_hook=_reject_duplicate_json_keys,
                          parse_constant=_reject_json_constant, parse_float=_finite_float)
        _check_slip_json_depth(data)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("invalid slip decision JSON") from exc
    if not isinstance(data, dict) or set(data) != {
        "schema", "scope", "rule_id", "rule_version", "probability_bp", "fact_id", "revealed", "draw"
    } or data["schema"] != SLIP_CODEC_SCHEMA:
        raise ValueError("invalid slip decision")
    scope = data["scope"]
    if not isinstance(scope, dict) or set(scope) != {"game_id", "npc_id", "topic_id", "window_idx"}:
        raise ValueError("invalid slip scope")
    return SlipDecision(SlipScope(**scope), _nonempty(data["rule_id"], "rule ID"),
                        data["rule_version"], data["probability_bp"], _nonempty(data["fact_id"], "fact ID"),
                        data["revealed"], data["draw"])


@dataclass(frozen=True)
class EpisodeCandidateDraft:
    candidate_id: str
    kind: str
    text: str
    catalog_ids: tuple[str, ...]
    source_job_id: str
    status: str = "draft"

    def __post_init__(self) -> None:
        if self.status != "draft":
            raise ValueError("episode candidate cannot be published here")
        _nonempty(self.candidate_id, "candidate ID")
        _nonempty(self.source_job_id, "source job ID")
        if self.kind not in EPISODE_KINDS or not isinstance(self.text, str) or not self.text or len(self.text) > MAX_TEXT:
            raise ValueError("invalid episode candidate")
        object.__setattr__(self, "catalog_ids", _strings(self.catalog_ids, "catalog IDs"))

    @classmethod
    def create(cls, candidate_id: str, kind: str, text: str, catalog_ids: Any,
               *, source_job_id: str = "manual", allowed_catalog_ids: Any = ()) -> EpisodeCandidateDraft:
        if kind not in EPISODE_KINDS or not isinstance(text, str) or not text or len(text) > MAX_TEXT:
            raise ValueError("invalid episode candidate")
        ids = _strings(catalog_ids, "catalog IDs")
        allowed = _strings(allowed_catalog_ids, "allowed catalog IDs")
        if ids and not set(ids).issubset(allowed):
            raise ValueError("unknown catalog ID")
        return cls(_nonempty(candidate_id, "candidate ID"), kind, text, ids,
                   _nonempty(source_job_id, "source job ID"))
