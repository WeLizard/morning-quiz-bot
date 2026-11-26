"""Strict, immutable Night City executable case format (core/1 and explicit module profile/2).

Compilation is a structural/content gate, not publication or a V4 witness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from domain.frozen_json import freeze as _freeze
from domain.night_case_format import (
    CaseFormatError, ValidationIssue, canonical_content_hash, load_case_bytes,
)


CASE_SCHEMA_ID = "night-city-case/2"
COMPILER_VERSION = "night-city-case-compiler/2.1"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "docs/tasks/night_city/case.v2.schema.json"
CORE_RULESET = ("night_case.core", 1)
MODULE_RULESET = ("night_case.core", 2)
MODULE_COMPILER_VERSION = "night-city-case-compiler/2.2"
PERSONAL_COMPILER_VERSION = "night-city-case-compiler/2.3"
RUNTIME_COMPILER_VERSION = "night-city-case-compiler/2.4"


class CaseV2Error(ValueError):
    def __init__(self, issue: ValidationIssue):
        self.issue = issue
        self.code = issue.code
        self.pointer = issue.pointer
        self.message = issue.message
        super().__init__(issue.message)


def _bad(code: str, pointer: str, message: str) -> None:
    raise CaseV2Error(ValidationIssue(code, pointer, message))


def _ptr(*parts: Any) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _snapshot(document: dict[str, Any]) -> bytes:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


@dataclass(frozen=True, slots=True)
class CaseV2:
    _json: bytes
    content_hash: str

    @property
    def case_id(self) -> str:
        return self.document()["meta"]["id"]

    @property
    def case_version(self) -> int:
        return self.document()["meta"]["version"]

    def document(self) -> dict[str, Any]:
        return json.loads(self._json)


@dataclass(frozen=True, slots=True)
class CompiledCase:
    _json: bytes
    case_id: str
    case_version: int
    content_hash: str
    compiler_version: str = COMPILER_VERSION
    _readonly: Any = field(default=None, init=False, repr=False, compare=False)

    def document(self) -> dict[str, Any]:
        """Return a fresh copy; no mutable alias reaches the compiled snapshot."""
        return json.loads(self._json)

    def readonly(self) -> dict[str, Any]:
        """The parsed case, shared and deeply frozen (parsed once per instance).

        For hot read paths that only look at the case. Any mutation raises
        ``TypeError``; ``copy.deepcopy`` of any part returns plain dicts/lists.
        """
        cached = self._readonly
        if cached is None:
            cached = _freeze(json.loads(self._json))
            object.__setattr__(self, "_readonly", cached)
        return cached


def _exact_numbers(value: Any, schema: dict[str, Any], defs: dict[str, Any], pointer: str = "") -> None:
    """jsonschema const/enum comparison considers True == 1; reject that parity."""
    if "$ref" in schema:
        _exact_numbers(value, defs[schema["$ref"].split("/")[-1]], defs, pointer)
        return
    if isinstance(value, (int, float)) and type(value) is not int:
        if (schema.get("type") == "integer" or type(schema.get("const")) is int
                or any(type(v) is int for v in schema.get("enum", ()))):
            _bad("v2.schema", pointer, "Ожидается точное целое число")
    if "oneOf" in schema:
        for branch in schema["oneOf"]:
            _exact_numbers(value, branch, defs, pointer)
    if isinstance(value, dict):
        for key, child in value.items():
            child_schema = schema.get("properties", {}).get(key)
            if child_schema is not None:
                _exact_numbers(child, child_schema, defs, pointer + _ptr(key))
    if isinstance(value, list) and "items" in schema:
        for i, child in enumerate(value):
            _exact_numbers(child, schema["items"], defs, pointer + _ptr(i))


def load_v2(raw: bytes) -> CaseV2:
    if not isinstance(raw, bytes):
        _bad("v2.input", "", "Ожидаются bytes")
    try:
        document = load_case_bytes(raw)
    except CaseFormatError as exc:
        raise CaseV2Error(exc.issue) from exc
    if not isinstance(document, dict) or document.get("schema") != CASE_SCHEMA_ID:
        _bad("v2.schema", _ptr("schema"), "Неизвестная версия case schema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda e: (_ptr(*e.path), e.message))
    if errors:
        err = errors[0]
        _bad("v2.schema", _ptr(*err.absolute_path), err.message)
    _exact_numbers(document, schema, schema["$defs"])
    return CaseV2(_snapshot(document), canonical_content_hash(document))


def _ids(items: list[dict[str, Any]], name: str, pointer: str | None = None) -> dict[str, dict[str, Any]]:
    result = {}
    for i, item in enumerate(items):
        ident = item["id"]
        if ident in result:
            _bad("v2.duplicate_id", (pointer or _ptr(name)) + _ptr(i, "id"), f"Повторный ID: {ident}")
        result[ident] = item
    return result


def _unique(values: list[str], pointer: str) -> None:
    if len(values) != len(set(values)):
        _bad("v2.duplicate_ref", pointer, "Повторная ссылка")


def _refs(values: list[str], target: dict[str, Any], pointer: str) -> None:
    _unique(values, pointer)
    for i, value in enumerate(values):
        if value not in target:
            _bad("v2.ref", pointer + _ptr(i), f"Неизвестная типизированная ссылка: {value}")


def _ref(value: str, target: dict[str, Any], pointer: str) -> None:
    if value not in target:
        _bad("v2.ref", pointer, f"Неизвестная типизированная ссылка: {value}")


def _variants(value: Any, variants: dict[str, Any], pointer: str) -> set[str]:
    if value == "all":
        return set(variants)
    _refs(value, variants, pointer)
    return set(value)


# Texts addressed to exactly one player; only they may agree with the reader's own hero via {g:@self|..|..}.
SELF_TEXT_PREFIXES = ("/personal_tasks/", "/actions/", "/dialogues/", "/npc_delivery/",
                      "/module_data/archive_requests/")


def self_text_allowed(pointer: str) -> bool:
    import re
    return pointer.startswith(SELF_TEXT_PREFIXES) or re.match(r"^/characters/\d+/(goal|secrets)/", pointer) is not None


def _body(body: dict[str, Any], facts: dict[str, Any], pointer: str,
          chars: dict[str, Any], locations: dict[str, Any], allow_self: bool = False) -> None:
    _refs(body["mentions"], facts, pointer + "/mentions")
    import re
    text = body["text"]
    for match in re.finditer(r"\{([^{}]*)\}", text):
        token = match.group(1)
        parts = token.split(":", 1)
        if len(parts) != 2 or parts[0] not in ("c", "t", "g"):
            _bad("v2.template", pointer + "/text", "Недопустимая подстановка")
        if parts[0] == "c":
            _ref(parts[1], chars, pointer + "/text")
        elif parts[0] == "g":
            target, *forms = parts[1].split("|")
            if len(forms) != 2:
                _bad("v2.template", pointer + "/text", "Согласование требует мужскую и женскую форму")
            if target == "@self":
                if not allow_self:
                    _bad("v2.template", pointer + "/text", "@self допустим только в тексте для одного игрока")
            else:
                _ref(target, chars, pointer + "/text")
        else:
            target, *form = parts[1].split("|")
            _ref(target, chars, pointer + "/text")
            if len(form) > 1 or (form and form[0] not in ("gen", "dat", "acc", "ins", "prep")):
                _bad("v2.template", pointer + "/text", "Недопустимая форма обращения")
    if text.count("{") != text.count("}") or re.search(r"\{[^{}]*\{", text):
        _bad("v2.template", pointer + "/text", "Незакрытая подстановка")


def _compile_looks(d: dict[str, Any]) -> None:
    """A look changes portrait, title and grammar only; the first look is the authored default."""
    assets = {}
    names: dict[str, str] = {}   # a hero name names one hero: any looks may meet in one party
    for i, c in enumerate(d["characters"]):
        for j, look in enumerate([c] + list(c.get("looks") or ())[1:]):
            name = look.get("name")
            if name is None:
                continue
            p = _ptr("characters", i) + (_ptr("looks", j) if j else "") + "/name"
            if names.setdefault(name.casefold(), c["id"]) != c["id"]:
                _bad("v2.looks", p, f"Имя {name} уже носит другой герой дела")
    for i, c in enumerate(d["characters"]):
        art = c.get("art")
        if art:
            assets.setdefault(art["asset_id"], _ptr("characters", i, "art"))
    for i, c in enumerate(d["characters"]):
        looks = c.get("looks")
        if looks is None:
            continue
        p = _ptr("characters", i, "looks")
        _unique([look["id"] for look in looks], p)
        first = looks[0]
        if (first["gender"] != c["gender"] or first["bio"] != c["bio"] or first["art"] != c.get("art")
                or first.get("title", c["title"]) != c["title"] or first.get("title_forms", c["title_forms"]) != c["title_forms"]
                or first.get("name") != c.get("name") or first.get("public") != c.get("public")):
            _bad("v2.looks", p + "/0", "Первый облик должен совпадать с верхними полями героя")
        for j, look in enumerate(looks):
            if ("title" in look) != ("title_forms" in look):
                _bad("v2.looks", p + _ptr(j), "Название облика задаётся вместе с падежными формами")
            if j and look["art"]["asset_id"] in assets:
                _bad("v2.looks", p + _ptr(j, "art", "asset_id"), "Портрет облика повторяет чужой asset_id")
            if j:
                assets[look["art"]["asset_id"]] = p + _ptr(j)


def _compile_scene_art(d: dict[str, Any]) -> None:
    """Event and variant pictures are optional; each names its own asset, never a portrait or a place."""
    taken = set()
    for group in ("characters", "locations"):
        for entry in d[group]:
            for art in [entry.get("art")] + [look.get("art") for look in entry.get("looks") or ()]:
                if art:
                    taken.add(art["asset_id"])
    for group in ("events", "variants", "items"):
        for i, entry in enumerate(d.get(group, ())):
            art = entry.get("art")
            if art is None:
                continue
            if art["asset_id"] in taken:
                _bad("v2.art", _ptr(group, i, "art", "asset_id"), "Картинка сцены повторяет чужой asset_id")
            taken.add(art["asset_id"])
    for i, scene in enumerate(((d.get("module_data") or {}).get("turning_point") or {}).get("scenes", ())):
        art = scene.get("art")  # a turning scene is shown to everyone like a case event
        if art is not None:
            if art["asset_id"] in taken:
                _bad("v2.art", _ptr("module_data", "turning_point", "scenes", i, "art", "asset_id"), "Картинка сцены повторяет чужой asset_id")
            taken.add(art["asset_id"])


def _compile_modules(d, maps, predicates):
    """Validate the finite module catalogs; never execute authored content."""
    modules = d["module_data"]
    variants, obs, flags = (maps[n] for n in ("variants", "observations", "flags"))
    chars, loc, actions = (maps[n] for n in ("characters", "locations", "actions"))
    all_variants = set(variants)
    protected = set()
    concealed = {}

    def partition(items, pointer):
        covered = set()
        for i, item in enumerate(items):
            vs = _variants(item["variants"], variants, pointer + _ptr(i, "variants"))
            if covered & vs:
                _bad("v2.partition", pointer, "Перекрытие вариантов")
            covered.update(vs)
        if covered != all_variants:
            _bad("v2.partition", pointer, "Неполное покрытие вариантов")

    def protect(flag, pointer):
        _ref(flag, flags, pointer)
        if flag in protected or flags[flag]["initial"]:
            _bad("v2.protected_flag", pointer, "Защищённый флаг должен быть уникальным и false")
        protected.add(flag)

    if "archive_requests" in modules:
        queries = modules["archive_requests"]["queries"]
        base = "/module_data/archive_requests/queries"
        _ids(queries, "queries", base)
        for i, query in enumerate(queries):
            p = base + _ptr(i)
            _ref(query["location"], loc, p + "/location")
            predicates(query["available_when"], p + "/available_when")
            partition(query["responses"], p + "/responses")
            for j, response in enumerate(query["responses"]):
                rp = p + _ptr("responses", j)
                vs = _variants(response["variants"], variants, rp)
                _refs(response["observations"], obs, rp + "/observations")
                if any(not vs <= _variants(obs[o]["exists_in"], variants, rp) for o in response["observations"]):
                    _bad("v2.response", rp, "Observation отсутствует в варианте ответа")
    if "version_archive" in modules:
        archive = modules["version_archive"]
        base = "/module_data/version_archive"
        documents = _ids(archive["documents"], "documents", base + "/documents")
        _ids(archive["comparisons"], "comparisons", base + "/comparisons")
        _ids(archive["theories"], "theories", base + "/theories")
        revisions, observations = set(), set()
        for i, doc in enumerate(archive["documents"]):
            p = base + _ptr("documents", i)
            _ref(doc["observation"], obs, p + "/observation")
            pair = (doc["family"], doc["revision"])
            if pair in revisions or doc["observation"] in observations:
                _bad("v2.document", p, "Повтор family/revision или observation")
            revisions.add(pair)
            observations.add(doc["observation"])
        for i, comparison in enumerate(archive["comparisons"]):
            p = base + _ptr("comparisons", i)
            _ref(comparison["left"], documents, p + "/left")
            _ref(comparison["right"], documents, p + "/right")
            _ref(comparison["action"], actions, p + "/action")
            left, right = (documents[comparison[k]] for k in ("left", "right"))
            action = actions[comparison["action"]]
            known = {v["observation"] for v in action["available_when"] if v["kind"] == "knows"}
            if left["id"] == right["id"] or left["family"] != right["family"] or action["kind"] != "interact" or not {left["observation"], right["observation"]} <= known:
                _bad("v2.comparison", p, "Неверная пара документов или prerequisites interact")
        for i, theory in enumerate(archive["theories"]):
            seen = set()
            for j, link in enumerate(theory["links"]):
                p = base + _ptr("theories", i, "links", j)
                _ref(link["observation"], obs, p + "/observation")
                if link["observation"] in seen:
                    _bad("v2.duplicate_ref", p, "Повторная связь observation")
                seen.add(link["observation"])
    if "turning_point" in modules:
        turning = modules["turning_point"]
        base = "/module_data/turning_point"
        _ids(turning["routes"], "routes", base + "/routes")
        scene_ids = _ids(turning["scenes"], "scenes", base + "/scenes")
        if scene_ids.keys() & maps["events"].keys():
            _bad("v2.duplicate_id", base + "/scenes", "Scene ID пересекается с event ID")
        edges = {frozenset((l["id"], n)) for l in d["locations"] for n in l["connects"]}
        for i, route in enumerate(turning["routes"]):
            p = base + _ptr("routes", i)
            _refs(route["ends"], loc, p + "/ends")
            edge = frozenset(route["ends"])
            if edge in edges:
                _bad("v2.route", p + "/ends", "Повторное ребро")
            edges.add(edge)
            protect(route["opened_flag"], p + "/opened_flag")
            predicates(route["open_when"], p + "/open_when")
            proofs = {v["observation"] for v in route["open_when"] if v["kind"] == "published"}
            if len(proofs) < 2 or any(obs[o]["kind"] != "proof" or _variants(obs[o]["exists_in"], variants, p) != all_variants for o in proofs):
                _bad("v2.route", p + "/open_when", "Нужны два разных общих published proof")
        for i, npc in enumerate(turning["concealed_npcs"]):
            p = base + _ptr("concealed_npcs", i)
            ident = npc["character"]
            _ref(ident, chars, p + "/character")
            if ident in concealed or chars[ident]["can_be_player"] or chars[ident]["schedule"] or any(ident in c["player_characters"] for c in d["compositions"]):
                _bad("v2.concealed", p, "Concealed NPC должен быть уникальным статичным неигровым героем")
            concealed[ident] = npc
            protect(npc["revealed_flag"], p + "/revealed_flag")
            partition(npc["placements"], p + "/placements")
            for j, placement in enumerate(npc["placements"]):
                _ref(placement["location"], loc, p + _ptr("placements", j, "location"))
        for i, scene in enumerate(turning["scenes"]):
            p = base + _ptr("scenes", i)
            if scene["not_before"] > scene["through_window"]:
                _bad("v2.scene", p, "Срок сцены истёк до её начала")
            predicates(scene["when"], p + "/when")
            for j, effect in enumerate(scene["effects"]):
                ep = p + _ptr("effects", j)
                if effect["kind"] == "set_flag":
                    _ref(effect["flag"], flags, ep + "/flag")
                else:
                    _ref(effect["observation"], obs, ep + "/observation")
                    if _variants(obs[effect["observation"]]["exists_in"], variants, ep) != all_variants:
                        _bad("v2.scene", ep, "Scene observation должен существовать во всех вариантах")
        if turning["recovery"] is not None:
            _ref(turning["recovery"]["character"], concealed, base + "/recovery/character")
    if "ghost_visions" in modules:
        signs = modules["ghost_visions"]["signs"]
        base = "/module_data/ghost_visions/signs"
        _ids(signs, "signs", base)
        for i, sign in enumerate(signs):
            p = base + _ptr(i)
            _ref(sign["character"], chars, p + "/character")
            _ref(sign["location"], loc, p + "/location")
            if not chars[sign["character"]]["can_be_player"]:
                _bad("v2.sign", p + "/character", "Знак явления бывает только у игрового героя")
    def protected_writes(value, pointer=""):
        if isinstance(value, dict):
            if value.get("kind") == "set_flag" and value["flag"] in protected:
                _bad("v2.protected_flag", pointer, "Защищённый флаг изменяется только kernel")
            for key, child in value.items():
                protected_writes(child, pointer + _ptr(key))
        elif isinstance(value, list):
            for i, child in enumerate(value):
                protected_writes(child, pointer + _ptr(i))
    protected_writes(d)
    return concealed


def _compile_personal(d, maps):
    """Check finite personal operations and ownership; receipts are runtime truth."""
    data = d["personal_tasks"]
    base = "/personal_tasks"
    catalogs = {name: _ids(data[name], name, base + "/" + name) for name in
                ("originals", "caches", "works", "commitments", "trips", "topics", "steps")}
    originals, works, steps = (catalogs[n] for n in ("originals", "works", "steps"))
    chars, loc, obs, flags, variants, actions = (maps[n] for n in
        ("characters", "locations", "observations", "flags", "variants", "actions"))
    all_variants = set(variants)

    def bad(pointer, message):
        _bad("v2.personal", pointer, message)

    def common_observation(ident, pointer):
        _ref(ident, obs, pointer)
        if _variants(obs[ident]["exists_in"], variants, pointer) != all_variants:
            bad(pointer, "Наблюдение операции должно существовать во всех вариантах")

    sections = {}
    for i, original in enumerate(data["originals"]):
        p = base + _ptr("originals", i)
        _ref(original["source_location"], loc, p + "/source_location")
        _refs(original["destroy_locations"], loc, p + "/destroy_locations")
        if "destroyed_flag" in original:
            _ref(original["destroyed_flag"], flags, p + "/destroyed_flag")
            if not original["destroy_locations"] or flags[original["destroyed_flag"]]["initial"] is not False:
                bad(p + "/destroyed_flag", "Флаг уничтожения требует места уничтожения и начального false")
        if original["initial_holder"] is not None:
            _ref(original["initial_holder"], chars, p + "/initial_holder")
        recipient = original["return_to"]
        if (recipient is None) != (original["return_location"] is None) or (recipient is None) != (original["offer_body"] is None):
            bad(p, "Return fields должны быть одновременно заданы или null")
        if recipient is not None:
            _ref(recipient, chars, p + "/return_to")
            _ref(original["return_location"], loc, p + "/return_location")
            if recipient == original["initial_holder"]:
                bad(p, "Holder и адресат должны различаться")
        sections[original["id"]] = _ids(original["sections"], "sections", p + "/sections")
        for j, section in enumerate(original["sections"]):
            sp = p + _ptr("sections", j)
            common_observation(section["observation"], sp + "/observation")
            _refs(section["backup_proofs"], obs, sp + "/backup_proofs")
            if original["destroy_locations"] and not section["backup_proofs"]:
                bad(sp, "Уничтожаемая section требует backup proof")
            for backup in section["backup_proofs"]:
                if backup == section["observation"] or obs[backup]["kind"] != "proof" or _variants(obs[backup]["exists_in"], variants, sp) != all_variants:
                    bad(sp, "Backup должен быть отдельным proof во всех вариантах section")
    for name, owner_key in (("caches", "owner"), ("works", "owner"), ("trips", "traveler")):
        for i, item in enumerate(data[name]):
            p = base + _ptr(name, i)
            _ref(item[owner_key], chars, p + "/" + owner_key)
            if name != "trips":
                _ref(item["location"], loc, p + "/location")
            if name == "caches":
                _ref(item["thaw_flag"], flags, p + "/thaw_flag")
            elif name == "trips":
                _ref(item["road_open_flag"], flags, p + "/road_open_flag")
                _ref(item["work"], works, p + "/work")
                if works[item["work"]]["owner"] != item["traveler"]:
                    bad(p, "Traveler должен владеть work")
    for i, item in enumerate(data["commitments"]):
        p = base + _ptr("commitments", i)
        _ref(item["issuer"], chars, p + "/issuer")
        _ref(item["beneficiary"], chars, p + "/beneficiary")
        if chars[item["issuer"]]["can_be_player"] or any(item["issuer"] in c["player_characters"] for c in d["compositions"]):
            bad(p, "Issuer должен быть изначальным NPC во всех составах")
    for i, topic in enumerate(data["topics"]):
        p = base + _ptr("topics", i)
        _ref(topic["subject"], chars, p + "/subject")
        _refs(topic["observations"], obs, p + "/observations")
        if set(topic["observations"]) & set(d["initial"]["public_observations"]):
            bad(p + "/observations", "Topic не может содержать начальные публичные наблюдения")

    for i, step in enumerate(data["steps"]):
        p = base + _ptr("steps", i)
        _refs(step["actors"], chars, p + "/actors")
        _refs(step["requires"], steps, p + "/requires")
        for parent in step["requires"]:
            if not set(step["actors"]) <= set(steps[parent]["actors"]):
                bad(p, "Prerequisite недоступен одному из actors")
    ancestors = {}
    def visit(ident, visiting):
        if ident in visiting:
            bad(base + "/steps", "Циклический prerequisite")
        if ident in ancestors:
            return ancestors[ident]
        result = set()
        if len(visiting) >= 8:
            bad(base + "/steps", "Глубина prerequisites больше 8")
        for parent in steps[ident]["requires"]:
            result.add(parent)
            result.update(visit(parent, visiting | {ident}))
        ancestors[ident] = result
        return result
    for ident in steps:
        visit(ident, set())
    # Compute depth independently of memoization, so catalog order cannot hide a long DAG.
    depths = {}
    def depth(ident):
        if ident not in depths:
            depths[ident] = 1 + max((depth(x) for x in steps[ident]["requires"]), default=0)
        return depths[ident]
    if any(depth(x) > 8 for x in steps):
        bad(base + "/steps", "Глубина prerequisites больше 8")
    grouped, action_owners, inspected = {}, {}, set()
    allowed_predicates = set()
    def story_predicates(preds, actors, pointer, goal=False):
        for j, pred in enumerate(preds):
            if not pred["kind"].startswith("story_"):
                continue
            pp = pointer + _ptr(j)
            allowed_predicates.add(id(pred))
            kind = pred["kind"]
            if kind in ("story_done", "story_before", "story_any_done"):
                targets = pred["steps"] if kind == "story_any_done" else [pred["step"]]
                _refs(targets, steps, pp)
                if any(not set(actors) <= set(steps[x]["actors"]) for x in targets):
                    bad(pp, "Story prerequisite должен принадлежать своему actor")
            if not goal and kind not in ("story_done", "story_any_done"):
                bad(pp, "Исторический predicate допустим только в goal")
            if kind == "story_before":
                boundary = pred["boundary"]
                catalog = catalogs["topics"] if boundary["kind"] == "public_reveal" else originals
                key = "topic" if boundary["kind"] == "public_reveal" else "original"
                _ref(boundary[key], catalog, pp + "/boundary/" + key)
            elif kind == "story_unexposed":
                _ref(pred["topic"], catalogs["topics"], pp + "/topic")
            elif kind == "story_departed":
                _ref(pred["trip"], catalogs["trips"], pp + "/trip")
                if set(actors) != {catalogs["trips"][pred["trip"]]["traveler"]}:
                    bad(pp, "Story trip должен принадлежать своему traveler")
    for i, step in enumerate(data["steps"]):
        p = base + _ptr("steps", i)
        _ref(step["action"], actions, p + "/action")
        action = actions[step["action"]]
        if step["action"] in action_owners or action.get("personal_step") != step["id"] or action["kind"] != "interact" or action["repeat"] != "player_window" or action["outcomes"]:
            bad(p, "Personal action требует взаимно-однозначную ссылку, interact, player_window и пустые outcomes")
        action_owners[step["action"]] = step["id"]
        story_predicates(action["available_when"], step["actors"], p + "/available_when")
        if step["choice_group"] is not None:
            grouped.setdefault(step["choice_group"], []).append(step)
        operation, actors = step["operation"], set(step["actors"])
        kind = operation["kind"]
        prior = ancestors[step["id"]]
        if "original" in operation:
            _ref(operation["original"], originals, p + "/operation/original")
            original = originals[operation["original"]]
            if kind in ("inspect_original", "take_original") and action["location"] != original["source_location"]:
                bad(p, "Inspect/take требуют source_location")
            if kind == "inspect_original":
                _ref(operation["section"], sections[original["id"]], p + "/operation/section")
                for actor in actors:
                    key = (actor, original["id"], operation["section"])
                    if key in inspected:
                        bad(p, "Повтор inspect одного actor/section через другой step")
                    inspected.add(key)
            if kind == "take_original":
                own_inspections = {pred["step"] for pred in action["available_when"] if pred["kind"] == "story_done"}
                if not any(steps[x]["operation"]["kind"] == "inspect_original" and steps[x]["operation"]["original"] == original["id"] for x in own_inspections):
                    bad(p, "Take требует visible story_done собственного inspect этого original")
            if kind == "destroy_original" and action["location"] not in original["destroy_locations"]:
                bad(p, "Destroy требует разрешённое место")
            if kind == "offer_return" and (original["return_to"] is None or action["location"] != original["return_location"]):
                bad(p, "Offer требует адрес и return_location")
            if kind in ("destroy_original", "offer_return"):
                for actor in actors:
                    if actor != original["initial_holder"] and not any(steps[x]["operation"]["kind"] == "take_original" and steps[x]["operation"]["original"] == original["id"] and actor in steps[x]["actors"] for x in prior):
                        bad(p, "Destroy/offer требуют initial_holder или обязательный собственный take")
        elif kind in ("recover_cache", "advance_work", "issue_commitment", "book_departure"):
            key, name, owner = {"recover_cache":("cache","caches","owner"),"advance_work":("work","works","owner"),"issue_commitment":("commitment","commitments","beneficiary"),"book_departure":("trip","trips","traveler")}[kind]
            _ref(operation[key], catalogs[name], p + "/operation/" + key)
            target = catalogs[name][operation[key]]
            if actors != {target[owner]}:
                bad(p, "Операция требует единственного owner/beneficiary/traveler")
            if kind in ("recover_cache", "advance_work") and action["location"] != target["location"]:
                bad(p, "Операция требует location каталога")
            if kind == "advance_work":
                if operation["stage"] not in target["stages"]:
                    bad(p, "Неизвестный этап work")
            if kind == "issue_commitment" and any(response["body"] != target["document"] for response in step["responses"]):
                bad(p, "Commitment response должен точно совпадать с document")
        elif kind == "deliver_card":
            common_observation(operation["observation"], p + "/operation/observation")
            if operation["recipient"] is not None:
                _ref(operation["recipient"], chars, p + "/operation/recipient")
        covered = set()
        for j, response in enumerate(step["responses"]):
            rp = p + _ptr("responses", j)
            vs = _variants(response["variants"], variants, rp + "/variants")
            if covered & vs:
                bad(rp, "Response variants пересекаются")
            covered.update(vs)
            _refs(response["observations"], obs, rp + "/observations")
            if any(not vs <= _variants(obs[o]["exists_in"], variants, rp) for o in response["observations"]):
                bad(rp, "Response observation отсутствует в варианте")
        if covered != all_variants:
            bad(p + "/responses", "Response partition не покрывает варианты")
    for group in grouped.values():
        if not 2 <= len(group) <= 4 or any(set(x["actors"]) != set(group[0]["actors"]) or set(x["requires"]) != set(group[0]["requires"]) for x in group):
            bad(base + "/steps", "Choice group требует 2..4 шага с одинаковыми actors/requires")
    for i, action in enumerate(d["actions"]):
        if "personal_step" in action:
            _ref(action["personal_step"], steps, _ptr("actions", i, "personal_step"))
            if action_owners.get(action["id"]) != action["personal_step"]:
                bad(_ptr("actions", i), "Невзаимная personal_step ссылка")
        elif not action["outcomes"]:
            bad(_ptr("actions", i, "outcomes"), "Обычный action требует непустой outcomes")
    for i, character in enumerate(d["characters"]):
        goal = character["goal"]
        story_predicates(goal["when"], [character["id"]], _ptr("characters", i, "goal", "when"), goal=True)
        if any(x["kind"].startswith("story_") for x in goal["when"]) and "criteria" not in goal:
            bad(_ptr("characters", i, "goal"), "Расширенная цель требует criteria")
    def walk(value):
        if isinstance(value, dict):
            if str(value.get("kind", "")).startswith("story_") and id(value) not in allowed_predicates:
                bad(base, "Story predicate допустим только в own personal prerequisites или goal")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(d)


def _compile_runtime_delivery(d, maps, predicates):
    """Bind authored NPC delivery to an original NPC and one exact talk option."""
    if "npc_delivery" not in d:
        return
    base = "/npc_delivery/topics"
    topics = d["npc_delivery"]["topics"]
    _ids(topics, "topics", base)
    chars, dialogues, obs, variants = (maps[n] for n in
                                     ("characters", "dialogues", "observations", "variants"))
    mapped, rule_ids = set(), set()
    for i, topic in enumerate(topics):
        p = base + _ptr(i)
        _ref(topic["npc"], chars, p + "/npc")
        npc = chars[topic["npc"]]
        if npc["can_be_player"] or any(topic["npc"] in c["player_characters"] for c in d["compositions"]):
            _bad("v2.npc_delivery", p + "/npc", "Delivery доступен только изначальному NPC во всех составах")
        _ref(topic["dialogue"], dialogues, p + "/dialogue")
        dialogue = dialogues[topic["dialogue"]]
        if dialogue["character"] != topic["npc"]:
            _bad("v2.npc_delivery", p + "/dialogue", "Dialogue принадлежит другому персонажу")
        nodes = _ids(dialogue["nodes"], "nodes", p + "/node")
        _ref(topic["node"], nodes, p + "/node")
        options = _ids(nodes[topic["node"]]["options"], "options", p + "/option")
        _ref(topic["option"], options, p + "/option")
        key = (topic["npc"], topic["dialogue"], topic["node"], topic["option"])
        if key in mapped:
            _bad("v2.npc_delivery", p, "Talk option уже связан с delivery topic")
        mapped.add(key)
        _ids(topic["lines"], "lines", p + "/lines")
        option = options[topic["option"]]
        bodies = [outcome["body"] for outcome in option["outcomes"]] + [option["fallback"]]
        for j, line in enumerate(topic["lines"]):
            for body in bodies:
                combined = {"text": line["body"]["text"] + "\n" + body["text"],
                            "mentions": list(dict.fromkeys(line["body"]["mentions"] + body["mentions"]))}
                if len(combined["text"]) > 1200 or len(combined["mentions"]) > 200:
                    _bad("v2.npc_delivery", p + _ptr("lines", j, "body"), "Line и outcome/fallback превышают предел Body")
                _body(combined, maps["facts"], p + _ptr("lines", j, "body"), chars, maps["locations"])
        slip = topic["slip"]
        if slip is None:
            continue
        if slip["rule_id"] in rule_ids:
            _bad("v2.duplicate_id", p + "/slip/rule_id", "Повторный slip rule ID")
        rule_ids.add(slip["rule_id"])
        _ref(slip["observation"], obs, p + "/slip/observation")
        observation = obs[slip["observation"]]
        if (observation["kind"] != "claim" or observation["speaker"] != topic["npc"]
                or _variants(observation["exists_in"], variants, p + "/slip/observation") != set(variants)):
            _bad("v2.npc_delivery", p + "/slip/observation", "Slip требует общий authored claim от этого NPC")
        predicates(slip["requires"], p + "/slip/requires")


def compile_v2(case: CaseV2, ruleset_registry: Any = None) -> CompiledCase:
    if not isinstance(case, CaseV2):
        _bad("v2.input", "", "Ожидается CaseV2 из load_v2")
    # Frozen dataclasses can still be constructed directly by a caller.
    checked = load_v2(case._json)
    d = case.document()
    if checked.content_hash != case.content_hash:
        _bad("v2.hash", "", "Хеш CaseV2 не совпадает с документом")
    ruleset = (d["ruleset_ref"]["id"], d["ruleset_ref"]["version"])
    allowed = {CORE_RULESET, MODULE_RULESET} if ruleset_registry is None else set(ruleset_registry)
    if ruleset not in {CORE_RULESET, MODULE_RULESET} or ruleset not in allowed:
        _bad("v2.ruleset", "/ruleset_ref", "Ruleset не зарегистрирован для core compiler")
    if d["episode_refs"]:
        _bad("v2.unsupported", "/meta/modules" if d["meta"].get("modules") else "/episode_refs",
             "Модули и эпизоды ещё не поддержаны")

    if ruleset == CORE_RULESET:
        def core_only(value):
            if isinstance(value, dict):
                if value.get("kind") in ("character_active", "reveal_npc"):
                    _bad("v2.unsupported", "", "Новый kind требует ruleset/2")
                for child in value.values():
                    core_only(child)
            elif isinstance(value, list):
                for child in value:
                    core_only(child)
        core_only(d)
    elif set(d["module_data"]) != set(d["meta"]["modules"]):
        _bad("v2.modules", "/module_data", "Ключи модулей не совпадают с meta.modules")

    maps = {name: _ids(d[name], name) for name in
            ("locations", "characters", "facts", "observations", "actions", "dialogues",
             "variants", "compositions", "flags", "events")}
    maps["items"] = _ids(d.get("items", []), "items")
    _compile_looks(d)
    _compile_scene_art(d)
    if "personal_tasks" in d:
        _compile_personal(d, maps)
    loc, chars, facts, obs = (maps[n] for n in ("locations", "characters", "facts", "observations"))
    variants, comps, flags = maps["variants"], maps["compositions"], maps["flags"]
    if {x["players"] for x in d["compositions"]} != {4, 5, 8, 12}:
        _bad("v2.composition", "/compositions", "Нужен один состав для 4/5/8/12")
    if len({x["players"] for x in d["compositions"]}) != len(d["compositions"]):
        _bad("v2.composition", "/compositions", "Повторный размер состава")
    if any(not any(c["id"] in v["composition_ids"] for v in d["variants"]) for c in d["compositions"]):
        _bad("v2.composition", "/compositions", "Состав не поддержан ни одним вариантом")
    if d["meta"]["players"] != {"min": 4, "max": 12}:
        _bad("v2.composition", "/meta/players", "Диапазон игроков должен быть 4..12")
    for i, c in enumerate(d["compositions"]):
        p = _ptr("compositions", i)
        _refs(c["player_characters"], chars, p + "/player_characters")
        if len(c["player_characters"]) != c["players"] or any(not chars[x]["can_be_player"] for x in c["player_characters"]):
            _bad("v2.composition", p, "Неверное число доступных игровых героев")
    for i, v in enumerate(d["variants"]):
        p = _ptr("variants", i)
        _ref(v["culprit"], chars, p + "/culprit")
        _refs(v["accomplices"], chars, p + "/accomplices")
        if v["culprit"] in v["accomplices"]:
            _bad("v2.variant", p + "/accomplices", "Виновный повторён как сообщник")
        _refs(v["composition_ids"], comps, p + "/composition_ids")
        _refs(v["key_proofs"], obs, p + "/key_proofs")
        if len(v["key_proofs"]) < v["min_key"] or any(obs[x]["kind"] != "proof" for x in v["key_proofs"]):
            _bad("v2.proof", p + "/key_proofs", "Ключи должны быть proof и покрывать min_key")
        if ruleset == MODULE_RULESET:
            _refs(v["required_key_proofs"], obs, p + "/required_key_proofs")
            if not set(v["required_key_proofs"]) <= set(v["key_proofs"]):
                _bad("v2.proof", p + "/required_key_proofs", "Обязательные proof должны входить в key_proofs")
        for obs_id in v["key_proofs"]:
            if v["id"] not in _variants(obs[obs_id]["exists_in"], variants, p + "/key_proofs"):
                _bad("v2.proof", p + "/key_proofs", "Ключевой proof отсутствует в варианте")
        for c_id in v["composition_ids"]:
            pc = comps[c_id]["player_characters"]
            if not any(chars[x]["faction"] == "investigation" and x not in {v["culprit"], *v["accomplices"]} for x in pc):
                _bad("v2.composition", p + "/composition_ids", "Нет human investigator")
    for i, f in enumerate(d["facts"]):
        p = _ptr("facts", i)
        if f["true_in"] != "none":
            _variants(f["true_in"], variants, p + "/true_in")
        if "at" in f:
            _ref(f["at"]["character"], chars, p + "/at/character")
            _ref(f["at"]["location"], loc, p + "/at/location")
    for i, o in enumerate(d["observations"]):
        p = _ptr("observations", i)
        exists = _variants(o["exists_in"], variants, p + "/exists_in")
        if o["kind"] == "proof":
            _refs(o["proves"], facts, p + "/proves")
            for fid in o["proves"]:
                truth = facts[fid]["true_in"]
                if truth == "none" or not exists <= _variants(truth, variants, p + "/proves"):
                    _bad("v2.proof", p + "/proves", "Proof доказывает неистинный факт")
        else:
            _refs(o["asserts"], facts, p + "/asserts")
            if o["speaker"] is not None:
                _ref(o["speaker"], chars, p + "/speaker")
        if "subject" in o:
            (kind, target), = o["subject"].items()
            _ref(target, {"item": maps["items"], "location": loc, "character": chars}[kind], p + "/subject/" + kind)
    for i, item in enumerate(d.get("items", [])):
        if item["location"] is not None:
            _ref(item["location"], loc, _ptr("items", i, "location"))
    for i, l in enumerate(d["locations"]):
        p = _ptr("locations", i)
        _refs(l["connects"], loc, p + "/connects")
        if l["id"] in l["connects"]:
            _bad("v2.graph", p + "/connects", "Self loop")
        for neighbor in l["connects"]:
            if l["id"] not in loc[neighbor]["connects"]:
                _bad("v2.graph", p + "/connects", "Несимметричная связь")
    seen = set()
    stack = [d["locations"][0]["id"]]
    while stack:
        node = stack.pop()
        if node not in seen:
            seen.add(node)
            stack.extend(loc[node]["connects"])
    if len(seen) != len(loc):
        _bad("v2.graph", "/locations", "Граф не связен")
    def predicates(items, pointer):
        for j, pred in enumerate(items):
            pp = pointer + _ptr(j)
            kind = pred["kind"]
            if kind == "window_in" and pred["from"] > pred["to"]:
                _bad("v2.predicate", pp, "from > to")
            if kind in ("knows", "published"):
                _ref(pred["observation"], obs, pp + "/observation")
            if kind == "flag_is":
                _ref(pred["flag"], flags, pp + "/flag")
            if kind == "at":
                _ref(pred["location"], loc, pp + "/location")
            if kind == "character_active":
                _ref(pred["character"], chars, pp + "/character")
    _compile_runtime_delivery(d, maps, predicates)
    concealed = _compile_modules(d, maps, predicates) if ruleset == MODULE_RULESET else {}
    def outcomes(items, pointer, action=None):
        used = set()
        _ids(items, "outcomes", pointer)
        for j, outcome in enumerate(items):
            pp = pointer + _ptr(j)
            vs = _variants(outcome["guard"]["variants"], variants, pp + "/guard/variants")
            if used & vs:
                _bad("v2.outcomes", pp + "/guard/variants", "Перекрывающиеся варианты outcomes")
            used |= vs
            predicates(outcome["guard"]["when"], pp + "/guard/when")
            for k, effect in enumerate(outcome["effects"]):
                ep = pp + _ptr("effects", k)
                if effect["kind"] == "grant_observation":
                    _ref(effect["observation"], obs, ep + "/observation")
                    if not vs <= _variants(obs[effect["observation"]]["exists_in"], variants, ep + "/observation"):
                        _bad("v2.effect", ep + "/observation", "Observation отсутствует в варианте outcome")
                elif effect["kind"] == "set_flag":
                    _ref(effect["flag"], flags, ep + "/flag")
                elif effect["kind"] == "reveal_npc":
                    target = effect["character"]
                    if action is None or target not in concealed:
                        _bad("v2.effect", ep, "Reveal требует action и concealed NPC")
                    if {"kind": "character_active", "character": target} not in action["available_when"]:
                        _bad("v2.effect", ep, "Reveal требует visible character_active")
                    for placement in concealed[target]["placements"]:
                        if vs & _variants(placement["variants"], variants, ep) and action["location"] != placement["location"]:
                            _bad("v2.effect", ep, "Reveal не совпадает с placement")
                else:
                    _bad("v2.effect", ep, "Scheduled effect недопустим в outcome")
    goal_ids = set()
    for i, c in enumerate(d["characters"]):
        p = _ptr("characters", i)
        if c["goal"]["id"] in goal_ids:
            _bad("v2.duplicate_id", p + "/goal/id", "Повторный goal ID")
        goal_ids.add(c["goal"]["id"])
        _ref(c["home"], loc, p + "/home")
        _refs(c["ghost_memories"], obs, p + "/ghost_memories")
        predicates(c["goal"]["when"], p + "/goal/when")
        windows = set()
        for j, schedule in enumerate(c["schedule"]):
            sp = p + _ptr("schedule", j)
            _ref(schedule["location"], loc, sp + "/location")
            for w in schedule["windows"]:
                if w in windows:
                    _bad("v2.schedule", sp + "/windows", "Пересечение окон расписания")
                windows.add(w)
        for j, secret in enumerate(c["secrets"]):
            _variants(secret["variants"], variants, p + _ptr("secrets", j, "variants"))
    for i, a in enumerate(d["actions"]):
        p = _ptr("actions", i)
        _ref(a["location"], loc, p + "/location")
        predicates(a["available_when"], p + "/available_when")
        outcomes(a["outcomes"], p + "/outcomes", a)
    for i, dialogue in enumerate(d["dialogues"]):
        p = _ptr("dialogues", i)
        _ref(dialogue["character"], chars, p + "/character")
        nodes = _ids(dialogue["nodes"], "nodes", p + "/nodes")
        _ref(dialogue["entry_node"], nodes, p + "/entry_node")
        for j, node in enumerate(dialogue["nodes"]):
            np = p + _ptr("nodes", j)
            _ids(node["options"], "options", np + "/options")
            for k, option in enumerate(node["options"]):
                op = np + _ptr("options", k)
                if option["next_node"] is not None:
                    _ref(option["next_node"], nodes, op + "/next_node")
                predicates(option["available_when"], op + "/available_when")
                outcomes(option["outcomes"], op + "/outcomes")
    _refs(d["initial"]["public_observations"], obs, "/initial/public_observations")
    for i, personal in enumerate(d["initial"]["personal"]):
        p = _ptr("initial", "personal", i)
        _ref(personal["character"], chars, p + "/character")
        _refs(personal["observations"], obs, p + "/observations")
    if len({p["character"] for p in d["initial"]["personal"]}) != len(d["initial"]["personal"]):
        _bad("v2.initial", "/initial/personal", "Повторный герой")
    for obs_id in d["initial"]["public_observations"]:
        if _variants(obs[obs_id]["exists_in"], variants, "/initial/public_observations") != set(variants):
            _bad("v2.initial", "/initial/public_observations", "Начальное наблюдение не во всех вариантах")
    for personal in d["initial"]["personal"]:
        for obs_id in personal["observations"]:
            if _variants(obs[obs_id]["exists_in"], variants, "/initial/personal") != set(variants):
                _bad("v2.initial", "/initial/personal", "Начальное личное наблюдение не во всех вариантах")
    # Event locks are applied in window order before checking NPC assignments.
    locked: dict[str, int] = {}
    for window in range(1, 15):
        changes = {}
        for i, event in enumerate(d["events"]):
            if event["window"] != window:
                continue
            for j, effect in enumerate(event["effects"]):
                p = _ptr("events", i, "effects", j)
                kind = effect["kind"]
                if kind == "grant_observation":
                    _ref(effect["observation"], obs, p + "/observation")
                    if effect["audience"] != "public" or _variants(obs[effect["observation"]]["exists_in"], variants, p) != set(variants):
                        _bad("v2.event", p, "Event выдаёт только public observation во всех вариантах")
                elif kind == "set_flag":
                    _ref(effect["flag"], flags, p + "/flag")
                elif kind == "reveal_npc":
                    _bad("v2.event", p, "Reveal разрешён только в action outcome")
                elif kind in ("lock_location", "unlock_location"):
                    place = effect["location"]
                    _ref(place, loc, p + "/location")
                    if place in changes and changes[place] != kind:
                        _bad("v2.event", p, "Конфликт lock/unlock в одном окне")
                    changes[place] = kind
                    if kind == "lock_location":
                        if effect["through_window"] < window:
                            _bad("v2.event", p, "Lock истекает до текущего окна")
                        locked[place] = effect["through_window"]
                    else:
                        locked.pop(place, None)
        # Every player character may become an NPC after departure/AFK.
        for i, c in enumerate(d["characters"]):
            if c["id"] in concealed:
                continue
            assigned = next((s["location"] for s in c["schedule"] if window in s["windows"]), c["home"])
            if locked.get(assigned, 0) >= window:
                _bad("v2.schedule", _ptr("characters", i, "schedule"), "NPC назначен в закрытое место")
    # A Body is never a truth source, but its mentions and templates are typed.
    def walk(value, pointer=""):
        if isinstance(value, dict):
            if set(value) == {"text", "mentions"}:
                _body(value, facts, pointer, chars, loc, self_text_allowed(pointer))
            for k, child in value.items():
                walk(child, pointer + _ptr(k))
        elif isinstance(value, list):
            for i, child in enumerate(value):
                walk(child, pointer + _ptr(i))
        elif isinstance(value, str) and ("{" in value or "}" in value):
            _body({"text": value, "mentions": []}, facts, pointer, chars, loc, self_text_allowed(pointer))
    walk(d)
    materialized = copy.deepcopy(d)
    materialized["meta"].setdefault("modules", [])
    materialized["meta"].setdefault("duration", "week")
    for node in (*materialized["locations"], *materialized["characters"]):
        node.setdefault("art", None)
    return CompiledCase(_snapshot(materialized), d["meta"]["id"], d["meta"]["version"], case.content_hash,
                        RUNTIME_COMPILER_VERSION if "communication" in d or "npc_delivery" in d else
                        PERSONAL_COMPILER_VERSION if "personal_tasks" in d else
                        MODULE_COMPILER_VERSION if ruleset == MODULE_RULESET else COMPILER_VERSION)
