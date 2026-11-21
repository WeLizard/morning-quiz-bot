"""Design rules P1-P9 for every Night City case (docs/tasks/night_city/NIGHT_CITY_MENU_DESIGN.md §2.1).

The compiler accepts any well-formed case; this report says which design rules a compiled case
already keeps. A rule is "passed", "failed" (with problems naming the place in the case) or
"not_checked" when the engine does not support its check yet. Read-only, no I/O.
"""
from __future__ import annotations

from typing import Any

from .night_case_text import looks_of

MIN_VARIANTS = 5

NOT_YET = {
    "P1": "Проверка появится вместе со свободными местами в сборе: движок пока играет составы 4/5/8/12.",
    "P3": "Прохождение без каждого отдельного героя проверяется вместе со свободными местами.",
    "P8": "Канон мира — документ, а не поле дела; проверяется при ревью канона.",
    "P9": "Ведущий получает облики, предметы и места дела (cast); это проверяют тесты кода, а не дело.",
}

TITLES = {
    "P1": "Играет столько, сколько пришло",
    "P2": "Невзятый герой — полноценный персонаж игры",
    "P3": "Ключевые улики не привязаны к одному герою",
    "P4": "Кто злодей, заранее неизвестно",
    "P5": "Вариантов достаточно",
    "P6": "Место за столом — это облик героя",
    "P7": "Предметы описаны",
    "P8": "Канон мира полный",
    "P9": "Ведущий знает то же, что видно на картинках",
}


def _playable(d: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in d["characters"] if c["can_be_player"]]


def _p2(d):
    talk = {x["character"] for x in d["dialogues"]}
    return [f"/characters/{c['id']}: у игрового героя нет диалога — невзятым его нельзя расспросить"
            for c in _playable(d) if c["id"] not in talk]


def _p4(d):
    problems = []
    for c in _playable(d):
        if c["faction"] == "shadow":
            problems.append(f"/characters/{c['id']}/faction: постоянная сторона «Тень» — взявший героя знает, что он злодей")
            continue
        shadow_in = [v["id"] for v in d["variants"] if c["id"] == v["culprit"] or c["id"] in v["accomplices"]]
        if d["variants"] and len(shadow_in) == len(d["variants"]):
            problems.append(f"/characters/{c['id']}: в Тени во всех вариантах правды")
    return problems


def _p5(d):
    problems = []
    if len(d["variants"]) < MIN_VARIANTS:
        problems.append(f"/variants: вариантов правды {len(d['variants'])}, нужно не меньше {MIN_VARIANTS}")
    for v in d["variants"]:
        if not v.get("art"):
            problems.append(f"/variants/{v['id']}/art: у варианта нет картинки финала")
    return problems


def _p6(d):
    problems = []
    for c in d["characters"]:
        for look in looks_of(c):
            where = f"/characters/{c['id']}" + ("" if look["id"] == "base" else f"/looks/{look['id']}")
            missing = [label for key, label in (("name", "имени"), ("public", "строки «что знают все»"))
                       if not look.get(key)]
            if look.get("age") is None:
                missing.append("возраста")
            if missing:
                problems.append(f"{where}: нет " + ", ".join(missing))
    return problems


def _p7(d):
    problems = []
    if not d.get("items"):
        problems.append("/items: в деле не описано ни одного предмета")
    keys = {oid for v in d["variants"] for oid in v["key_proofs"]}
    for o in d["observations"]:
        if o["id"] in keys and "subject" not in o:
            problems.append(f"/observations/{o['id']}: ключевая улика не ссылается на предмет, место или героя")
    return problems


CHECKS = {"P2": _p2, "P4": _p4, "P5": _p5, "P6": _p6, "P7": _p7}


def check_rules(case_doc: dict[str, Any]) -> dict[str, Any]:
    """{"passed": bool, "rules": {Pn: {"title", "status", "problems"}}}; passed needs every rule passed."""
    rules = {}
    for rule, title in TITLES.items():
        if rule in CHECKS:
            problems = CHECKS[rule](case_doc)
            rules[rule] = {"title": title, "status": "failed" if problems else "passed", "problems": problems}
        else:
            rules[rule] = {"title": title, "status": "not_checked", "problems": [], "reason": NOT_YET[rule]}
    return {"passed": all(r["status"] == "passed" for r in rules.values()), "rules": rules}
