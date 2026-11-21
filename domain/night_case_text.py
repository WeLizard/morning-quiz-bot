"""Appearance looks of roles and the pure renderer of authored text templates.

The kernel keeps raw templates ({c:id}, {t:id|case}, {g:id|m|f}); only projections render them for the
party's sealed looks. A look changes portrait, title and grammar, never the role, secrets, goals or proofs.
"""

from __future__ import annotations

import copy
import random
import re
from typing import Any

TITLE_CASES = ("gen", "dat", "acc", "ins", "prep")
SELF = "@self"
_TOKEN = re.compile(r"\{([^{}]*)\}")
_SENTENCE_START = re.compile(r"(^\s*|[.!?…]\s+|\n\s*|[«„]\s*)$")


def looks_of(character: dict[str, Any]) -> list[dict[str, Any]]:
    """Materialized looks; a character without looks has one implicit look from its top-level fields."""
    base = {"id": "base", "gender": character["gender"], "age": None, "title": character["title"],
            "title_forms": character["title_forms"], "bio": character["bio"], "art": character.get("art")}
    for key in ("name", "public"):   # optional: present only when the case authored them
        if key in character:
            base[key] = character[key]
    authored = character.get("looks")
    if not authored:
        return [copy.deepcopy(base)]
    result = []
    for look in authored:
        row = copy.deepcopy(base)
        row.update(copy.deepcopy(look))
        result.append(row)
    return result


def pick_looks(case_doc: dict[str, Any], rng: random.Random) -> dict[str, str]:
    """Seeded choice for every character with authored looks, in character-id order."""
    picked = {}
    for character in sorted(case_doc["characters"], key=lambda c: c["id"]):
        looks = character.get("looks")
        if looks:
            picked[character["id"]] = looks[rng.randrange(len(looks))]["id"]
    return picked


def chosen_looks(case_doc: dict[str, Any], doc: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """The look of every character for this party; states without sealed.looks use the default look."""
    sealed = (doc or {}).get("sealed", {}).get("looks", {})
    result = {}
    for character in case_doc["characters"]:
        looks = looks_of(character)
        wanted = sealed.get(character["id"])
        result[character["id"]] = next((look for look in looks if look["id"] == wanted), looks[0])
    return result


def public_look(look: dict[str, Any]) -> dict[str, Any]:
    """What everyone sees of a hero; name and public line only when the case authored them."""
    result = {key: copy.deepcopy(look[key]) for key in ("id", "gender", "age", "title", "title_forms", "art")}
    for key in ("name", "public"):
        if look.get(key) is not None:
            result[key] = copy.deepcopy(look[key])
    return result


class Renderer:
    """Renders template bodies for one party and one reader (viewer_character for {g:@self|..})."""

    def __init__(self, case_doc: dict[str, Any], doc: dict[str, Any] | None = None, viewer_character: str | None = None):
        self.looks = chosen_looks(case_doc, doc)
        self.viewer = viewer_character
        self.names = {}
        for row in (doc or {}).get("players", []) + (doc or {}).get("npcs", []):
            self.names[row["character_id"]] = row["name"]

    def _gender(self, target: str) -> str:
        key = self.viewer if target == SELF else target
        look = self.looks.get(key) if key else None
        return look["gender"] if look else "m"

    def text(self, text: str) -> str:
        if "{" not in text:
            return text
        out, last = [], 0
        for match in _TOKEN.finditer(text):
            out.append(text[last:match.start()])
            head = "".join(out)
            kind, _, rest = match.group(1).partition(":")
            if kind == "g":
                target, male, female = (rest.split("|") + ["", ""])[:3]
                value = female if self._gender(target) == "f" else male
            elif kind == "c":
                # The hero's own name from its look; a player's label never enters case text.
                look = self.looks.get(rest)
                value = (look or {}).get("name") or self.names.get(rest)
                if value is None:   # no party name (e.g. a case preview): the role title, cased like {t:}
                    value = look["title"] if look else rest
                    if value and not _SENTENCE_START.search(head):
                        value = value[0].lower() + value[1:]
            elif kind == "t":
                target, _, form = rest.partition("|")
                look = self.looks.get(target)
                if look is None:
                    value = target
                else:
                    value = look["title_forms"][form] if form in TITLE_CASES else look["title"]
                    if value and not _SENTENCE_START.search(head):
                        value = value[0].lower() + value[1:]
            else:
                value = match.group(0)
            out.append(value)
            last = match.end()
        out.append(text[last:])
        return "".join(out)

    def body(self, body: dict[str, Any] | None) -> dict[str, Any] | None:
        if body is None:
            return None
        result = copy.deepcopy(body)
        result["text"] = self.text(body["text"])
        return result

    def tree(self, value: Any) -> Any:
        """Copy of value with every authored Body ({"text", "mentions"}) rendered."""
        if isinstance(value, dict):
            if set(value) == {"text", "mentions"} and isinstance(value["text"], str):
                return self.body(value)
            return {key: self.tree(child) for key, child in value.items()}
        if isinstance(value, list):
            return [self.tree(child) for child in value]
        return value


def render_text(text: str, case_doc: dict[str, Any], doc: dict[str, Any] | None = None,
                viewer_character: str | None = None) -> str:
    return Renderer(case_doc, doc, viewer_character).text(text)


def render(body: dict[str, Any], case_doc: dict[str, Any], doc: dict[str, Any] | None = None,
           viewer_character: str | None = None) -> dict[str, Any]:
    return Renderer(case_doc, doc, viewer_character).tree(body)
