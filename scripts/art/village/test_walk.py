"""Walk graph checks (needs a build; runs one if out/ is missing):

    python scripts/art/village/test_walk.py        # or: python -m pytest scripts/art/village/test_walk.py

- every node is reachable from every other (one connected network) and every walk target of app.js has an anchor;
- no edge crosses a building or prop footprint, a tree trunk, a fence or water (the bridge deck excepted) — checked here
  independently of walk.js, on the obstacle list the same render exported (out/walk_check.json, tile coordinates);
- nearest_point (the reference snap of README.md) puts taps on houses and grass onto an edge;
- app.js VILLAGE_WALK is exactly the generated graph.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import build_village  # noqa: E402

OUT = ROOT / ".local" / "village-generator" / "out"


def _load():
    if not (OUT / "walk_check.json").exists():
        build_village.build(OUT)
    man = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    chk = json.loads((OUT / "walk_check.json").read_text(encoding="utf-8"))
    return man["walk"], chk


def nearest_point(walk: dict, x: float, y: float):
    """Reference snap (README): the closest point of any edge to (x, y), world units -> (edge index, t, qx, qy, dist)."""
    n, e, best = walk["nodes"], walk["edges"], None
    for k in range(0, len(e), 2):
        ax, ay, bx, by = n[2 * e[k]], n[2 * e[k] + 1], n[2 * e[k + 1]], n[2 * e[k + 1] + 1]
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1)))
        qx, qy = ax + t * dx, ay + t * dy
        d = math.hypot(x - qx, y - qy)
        if best is None or d < best[4]:
            best = (k // 2, t, qx, qy, d)
    return best


def test_connected_and_anchored():
    walk, _ = _load()
    nodes, edges = len(walk["nodes"]) // 2, walk["edges"]
    adj = [[] for _ in range(nodes)]
    for k in range(0, len(edges), 2):
        adj[edges[k]].append(edges[k + 1])
        adj[edges[k + 1]].append(edges[k])
    seen, todo = {0}, [0]
    while todo:
        for m in adj[todo.pop()]:
            if m not in seen:
                seen.add(m)
                todo.append(m)
    assert len(seen) == nodes, f"{nodes - len(seen)} nodes are cut off"
    assert all(isinstance(v, int) for v in walk["nodes"] + walk["edges"]), "compact integer format"
    assert all(0 <= walk["nodes"][i] <= 2400 and 0 <= walk["nodes"][i + 1] <= 1800 for i in range(0, len(walk["nodes"]), 2))
    targets = build_village.walk_targets()
    assert sorted(walk["anchors"]) == sorted(targets), "every app.js walk target has an anchor"


def test_edges_avoid_houses_water_trees():
    _, chk = _load()
    g, b = chk["graph"], chk["blockers"]
    river, half = b["river"], b["river_width"] / 2
    pond = b["pond"]

    def seg(px, py, x1, y1, x2, y2):
        dx, dy = x2 - x1, y2 - y1
        t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy or 1)))
        return math.hypot(px - x1 - t * dx, py - y1 - t * dy)

    def hit(x, y):
        for r in b["occupied"]:
            if r[0] - .1 < x < r[2] + .1 and r[1] - .1 < y < r[3] + .1:
                return f"object {r}"
        for tx, ty, k in b["trees"]:
            if math.hypot(x - tx, y - ty) < .28 * k:
                return f"tree {tx:.1f},{ty:.1f}"
        for f in b["fences"]:
            if seg(x, y, *f) < .12:
                return f"fence {f}"
        on_bridge = any(r[0] - .05 < x < r[2] + .05 and r[1] - .05 < y < r[3] + .05 for r in b["bridges"])
        if not on_bridge:
            if min(math.hypot(x - a, y - c) for a, c in river) < half - .02:
                return "river"
            if ((x - pond["x"]) / pond["rx"]) ** 2 + ((y - pond["y"]) / pond["ry"]) ** 2 < 1:
                return "pond"
        return None

    bad = []
    for i, j in g["edges"]:
        (ax, ay), (bx, by) = g["nodes"][i], g["nodes"][j]
        steps = max(1, math.ceil(math.hypot(bx - ax, by - ay) / .05))
        for s in range(steps + 1):
            x, y = ax + (bx - ax) * s / steps, ay + (by - ay) * s / steps
            why = hit(x, y)
            if why:
                bad.append(f"edge {i}-{j} at {x:.2f},{y:.2f}: {why}")
                break
    assert not bad, "\n".join(bad[:20])


def test_taps_snap_to_paths():
    walk, _ = _load()
    # taps on a house, the grass by the river, the pond and the forest edge land on the network
    for x, y in ((1590, 820), (380, 900), (1240, 1250), (300, 1650), (1200, 1440)):
        k, t, qx, qy, d = nearest_point(walk, x, y)
        assert 0 <= t <= 1 and 0 <= qx <= 2400 and 0 <= qy <= 1800 and d < 400, (x, y, d)


def test_app_uses_generated_graph():
    walk, _ = _load()
    src = (ROOT / "qw_farm" / "static" / "app.js").read_text(encoding="utf-8")
    line = src[src.index("const VILLAGE_WALK="):src.index(";\n", src.index("const VILLAGE_WALK="))]
    j = lambda v: json.dumps(v, separators=(",", ":"), ensure_ascii=False)  # noqa: E731
    assert line == f"const VILLAGE_WALK={{n:{j(walk['nodes'])},e:{j(walk['edges'])},a:{j(walk['anchors'])},z:{j(walk['areas'])}}}"


if __name__ == "__main__":
    test_connected_and_anchored()
    test_edges_avoid_houses_water_trees()
    test_taps_snap_to_paths()
    test_app_uses_generated_graph()
    print("ok")
