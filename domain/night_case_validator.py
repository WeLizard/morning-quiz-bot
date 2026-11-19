"""Static structural checks that run after the case JSON Schema gate."""

from __future__ import annotations

import re
from collections.abc import Iterable

from domain.night_case_format import ValidationIssue


_COLLECTIONS = (
    "locations",
    "characters",
    "facts",
    "evidence",
    "dialogues",
    "variants",
    "events",
    "endings",
)
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_VALID_PLACEHOLDER = re.compile(r"^(?:c:([a-z][a-z0-9_]{1,31})|t:([a-z][a-z0-9_]{1,31})(?:\|(gen|dat|acc|ins|prep))?)$")


def _pointer(*parts: object) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _child(pointer: str, *parts: object) -> str:
    return pointer + _pointer(*parts)


def validate_structure(document: dict) -> tuple[ValidationIssue, ...]:
    """Check typed IDs, cross-references, placeholders, and simple invariants.

    The caller must first pass ``document`` through V1 JSON Schema validation.
    This function intentionally does not infer game semantics or report V2–V11.
    """
    issues: list[ValidationIssue] = []
    indexes: dict[str, dict[str, dict]] = {}

    def issue(code: str, pointer: str, message: str) -> None:
        issues.append(ValidationIssue(code, pointer, message))

    # Typed ID tables make a reference to (for example) a character invalid when
    # it accidentally points at a location that happens to use the same ID.
    for collection_name in _COLLECTIONS:
        index: dict[str, dict] = {}
        for item_index, item in enumerate(document.get(collection_name, [])):
            item_id = item["id"]
            if item_id in index:
                issue("V1.ids", _pointer(collection_name, item_index, "id"),
                      f"Повторный id в коллекции {collection_name}: {item_id}")
            else:
                index[item_id] = item
        indexes[collection_name] = index

    def ref(value: str, target: str, pointer: str) -> None:
        if value not in indexes[target]:
            issue("V1.refs", pointer, f"Неизвестный id {value!r} в коллекции {target}")

    def ref_list(values: Iterable[str], target: str, pointer: str) -> None:
        for value_index, value in enumerate(values):
            ref(value, target, _child(pointer, value_index))

    def variant_set(value: str | list[str], pointer: str) -> None:
        if isinstance(value, list):
            ref_list(value, "variants", pointer)

    # Locations and character placement.
    for i, location in enumerate(document.get("locations", [])):
        ref_list(location["connects"], "locations", _pointer("locations", i, "connects"))

    for i, character in enumerate(document.get("characters", [])):
        ref(character["home"], "locations", _pointer("characters", i, "home"))
        for schedule_i, schedule in enumerate(character["schedule_overrides"]):
            ref(schedule["location"], "locations",
                _pointer("characters", i, "schedule_overrides", schedule_i, "location"))

    # Facts and their optional structured location claims.
    for i, fact in enumerate(document.get("facts", [])):
        variant_set(fact["true_in"], _pointer("facts", i, "true_in"))
        at = fact.get("at")
        if at is not None:
            ref(at["character"], "characters", _pointer("facts", i, "at", "character"))
            ref(at["location"], "locations", _pointer("facts", i, "at", "location"))

    # Evidence: facts, discovery locations, variant scope, prerequisite graph,
    # optional key claims, decoys, and declared fact mentions.
    for i, evidence in enumerate(document.get("evidence", [])):
        base = _pointer("evidence", i)
        ref(evidence["fact"], "facts", _child(base, "fact"))
        found = evidence["found"]
        if found["via"] == "examine":
            ref(found["location"], "locations", _child(base, "found", "location"))
        variant_set(evidence["exists_in"], _child(base, "exists_in"))
        ref_list(evidence["requires"], "evidence", _child(base, "requires"))
        if "key_for" in evidence:
            variant_set(evidence["key_for"], _child(base, "key_for"))
        ref_list(evidence.get("misleads_toward", []), "characters", _child(base, "misleads_toward"))
        ref_list(evidence.get("debunked_by", []), "evidence", _child(base, "debunked_by"))
        ref_list(evidence["mentions"], "facts", _child(base, "mentions"))

    # Dialogue graph. ``goto`` addresses another dialogue; grants/requires are
    # evidence IDs, while mentions are fact IDs.
    for i, dialogue in enumerate(document.get("dialogues", [])):
        base = _pointer("dialogues", i)
        ref(dialogue["character"], "characters", _child(base, "character"))
        variant_set(dialogue["valid_in"], _child(base, "valid_in"))
        ref_list(dialogue["mentions"], "facts", _child(base, "mentions"))
        for option_i, option in enumerate(dialogue["options"]):
            option_base = _child(base, "options", option_i)
            if option["goto"] is not None:
                ref(option["goto"], "dialogues", _child(option_base, "goto"))
            ref_list(option["grants"], "evidence", _child(option_base, "grants"))
            ref_list(option["requires"], "evidence", _child(option_base, "requires"))

    # Variants and their evidence keys.
    for i, variant in enumerate(document.get("variants", [])):
        base = _pointer("variants", i)
        ref(variant["culprit"], "characters", _child(base, "culprit"))
        ref_list(variant["accomplices"], "characters", _child(base, "accomplices"))
        ref_list(variant["key_evidence"], "evidence", _child(base, "key_evidence"))
        if variant["min_key"] > len(set(variant["key_evidence"])):
            issue("V1.min_key", _child(base, "min_key"),
                  "min_key не может быть больше числа уникальных key_evidence")

    # Event effects are a tagged union in the schema; only the chosen arm carries
    # a reference. Their windows share the case's two-windows-per-day calendar.
    for i, event in enumerate(document.get("events", [])):
        effect = event["effect"]
        kind = effect["kind"]
        if kind == "reveal_fact":
            ref(effect["fact"], "facts", _pointer("events", i, "effect", "fact"))
        elif kind == "lock_location":
            ref(effect["location"], "locations", _pointer("events", i, "effect", "location"))

    # Endings may be general or tied to one specific variant.
    for i, ending in enumerate(document.get("endings", [])):
        if "variant" in ending:
            ref(ending["variant"], "variants", _pointer("endings", i, "variant"))

    # key_for is optional, but when authored it must agree in both directions
    # with variants.key_evidence.
    for evidence_i, evidence in enumerate(document.get("evidence", [])):
        if "key_for" not in evidence:
            continue
        for variant_id in evidence["key_for"]:
            variant = indexes["variants"].get(variant_id)
            if variant is not None and evidence["id"] not in variant["key_evidence"]:
                issue("V1.key_evidence", _pointer("evidence", evidence_i, "key_for"),
                      f"Улика {evidence['id']} заявлена ключевой для {variant_id}, но отсутствует в key_evidence")
        for variant_i, variant in enumerate(document.get("variants", [])):
            if evidence["id"] in variant["key_evidence"] and variant["id"] not in evidence["key_for"]:
                issue("V1.key_evidence", _pointer("evidence", evidence_i, "key_for"),
                      f"Вариант {variant['id']} содержит улику {evidence['id']} в key_evidence, но не в key_for")

    # A declared red herring must point to at least one different piece of
    # evidence that can refute it. This does not claim the refutation is reached.
    for evidence_i, evidence in enumerate(document.get("evidence", [])):
        if not evidence.get("misleads_toward"):
            continue
        debunked_by = evidence.get("debunked_by", [])
        pointer = _pointer("evidence", evidence_i, "debunked_by")
        if not debunked_by:
            issue("V5.debunk", pointer, "Для ложного следа нужна хотя бы одна улика-опровержение")
        for debunk_i, debunk_id in enumerate(debunked_by):
            if debunk_id == evidence["id"]:
                issue("V5.debunk", _child(pointer, debunk_i), "Улика не может опровергать саму себя")

    # The schema already bounds individual windows to 1..14; this cross-check
    # keeps the document contract correct if its permitted day count changes.
    maximum_window = document["setting"]["days"] * 2

    def check_window(value: int, pointer: str) -> None:
        if value > maximum_window:
            issue("V1.windows", pointer, f"Окно {value} выходит за пределы дела ({maximum_window})")

    for i, character in enumerate(document.get("characters", [])):
        for schedule_i, schedule in enumerate(character["schedule_overrides"]):
            for window_i, window in enumerate(schedule["windows"]):
                check_window(window, _pointer("characters", i, "schedule_overrides", schedule_i, "windows", window_i))
    for i, fact in enumerate(document.get("facts", [])):
        if "at" in fact:
            check_window(fact["at"]["window"], _pointer("facts", i, "at", "window"))
    for i, evidence in enumerate(document.get("evidence", [])):
        found = evidence["found"]
        if found["via"] == "examine":
            if found["windows"][0] > found["windows"][1]:
                issue("V1.windows", _pointer("evidence", i, "found", "windows"),
                      "Начальное окно улику нельзя назначить позже конечного")
            for window_i, window in enumerate(found["windows"]):
                check_window(window, _pointer("evidence", i, "found", "windows", window_i))
    for i, event in enumerate(document.get("events", [])):
        check_window(event["window"], _pointer("events", i, "window"))
        effect = event["effect"]
        if effect["kind"] == "lock_location":
            for window_i, window in enumerate(effect["windows"]):
                check_window(window, _pointer("events", i, "effect", "windows", window_i))

    player_range = document["meta"]["players"]
    if player_range["min"] > player_range["max"]:
        issue("V1.players", "/meta/players", "Минимальный состав не может быть больше максимального")

    # Validate only declared character placeholders. Schema V1 rejects malformed
    # braces; this layer resolves valid {c:id}/{t:id|case} references.
    def visit_text(node: object, path: tuple[str | int, ...] = ()) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                visit_text(value, (*path, key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                visit_text(value, (*path, index))
        elif isinstance(node, str):
            for match in _PLACEHOLDER.finditer(node):
                token = match.group(1)
                parsed = _VALID_PLACEHOLDER.fullmatch(token)
                pointer = _pointer(*path)
                if parsed is None:
                    issue("V1.placeholders", pointer, f"Неизвестная подстановка {{{token}}}")
                    continue
                character_id = parsed.group(1) or parsed.group(2)
                if character_id not in indexes["characters"]:
                    issue("V1.placeholders", pointer, f"Подстановка ссылается на неизвестного героя {character_id}")

    visit_text(document)
    return tuple(issues)
