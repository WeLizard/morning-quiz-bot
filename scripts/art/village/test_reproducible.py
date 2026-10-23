"""Reproducibility check of the village generator (needs Playwright's Chromium; not part of run_all_tests).

    python scripts/art/village/test_reproducible.py      # or: python -m pytest scripts/art/village/test_reproducible.py

1. Two builds in a row give byte-identical pixels, WebP and village.svg.
2. The hashes equal reference.json when the same Chromium / Pillow / libwebp versions are used
   (another browser build may anti-alias differently: then only the in-run equality is asserted, and the
   mismatch is reported so reference.json can be refreshed on purpose).
3. The exported live-layer coordinates are the ones app.js uses (night lights, chimney smoke, plaza, hall).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import build_village  # noqa: E402

WORK = ROOT / ".local" / "village-generator" / "test"
KEYS = ("rgba_sha256", "webp_sha256", "svg_sha256", "fest_sha256", "merchant_sha256", "build_sha256")


def _app_const(src: str, name: str):
    s = src[src.index(f"const {name}="):]
    return json.loads(s[s.index("=") + 1:s.index(";")].replace("'", '"'))


def test_village_generator_is_reproducible():
    a = build_village.build(WORK / "a")
    b = build_village.build(WORK / "b")
    assert {k: a[k] for k in KEYS} == {k: b[k] for k in KEYS}, "two runs differ"
    assert (WORK / "a" / "village.svg").read_bytes() == (WORK / "b" / "village.svg").read_bytes()
    assert a["fest_sha256"] == b["fest_sha256"], "festival layers differ between runs"
    for fid in a["fest_sha256"]:   # the installed festival layer is the generated one
        game = ROOT / "qw_farm" / "static" / f"village-fest-{fid}.svg"
        assert game.read_bytes() == (WORK / "a" / f"village-fest-{fid}.svg").read_bytes(), f"{game.name}: rebuild with --install"
    cart = ROOT / "qw_farm" / "static" / "village-merchant.svg"
    assert cart.read_bytes() == (WORK / "a" / "village-merchant.svg").read_bytes(), "village-merchant.svg: rebuild with --install"
    app = (ROOT / "qw_farm" / "static" / "app.js").read_text(encoding="utf-8")
    assert (WORK / "a" / "merchant-figure.svg").read_text(encoding="utf-8") in app, "app.js VILLAGE_MERCHANT.figure is the generated one"
    sprite = ROOT / "qw_farm" / "static" / "village-build.svg"   # construction stages and stalls (build.js)
    assert sprite.read_bytes() == (WORK / "a" / "village-build.svg").read_bytes(), "village-build.svg: rebuild with --install"
    ref = json.loads((HERE / "reference.json").read_text(encoding="utf-8"))
    changed = sorted(k for k in set(ref["inputs"]) | set(a["inputs"]) if ref["inputs"].get(k) != a["inputs"].get(k))
    if changed:
        print("note: inputs changed since reference.json:", ", ".join(changed), "; reference not compared")
    elif ref["versions"] == a["versions"]:
        assert {k: a[k] for k in KEYS} == {k: ref[k] for k in KEYS}, "output changed: review the preview, then refresh reference.json"
    else:
        print("note: tool versions differ from reference.json", ref["versions"], "->", a["versions"], "; reference not compared")


def test_live_layers_match_app():
    if not (WORK / "a" / "manifest.json").exists():
        build_village.build(WORK / "a")
    man = json.loads((WORK / "a" / "manifest.json").read_text(encoding="utf-8"))
    app = (ROOT / "qw_farm" / "static" / "app.js").read_text(encoding="utf-8")
    assert man["problems"] == []
    assert man["lights"] == _app_const(app, "VILLAGE_LIGHTS")
    assert man["smoke"] == _app_const(app, "VILLAGE_SMOKE")
    c = re.search(r"const VILLAGE_C=\[(\d+),(\d+)\].*?VILLAGE_HALL=\[([\d.]+),([\d.]+)\]", app)
    assert man["plaza_corner"] == [int(c.group(1)), int(c.group(2))]
    assert man["hall"] == [float(c.group(3)), float(c.group(4))]
    # construction: the boxes and crew points of the pieces, the crew figures, the captions of the sites
    build = _app_const(app, "VILLAGE_BUILD")
    assert build["boxes"] == man["build"]["boxes"] and build["crew"] == man["build"]["crew"]
    assert build["stalls"] == [st["id"] for st in man["stalls"]] and sorted(build["sites"]) == sorted(man["sites"])
    for name in ("krot", "pooh", "kaya"):
        assert (WORK / "a" / "build" / f"crew-{name}.svg").read_text(encoding="utf-8") in app, f"app.js VILLAGE_CREW.{name} is the generated one"
    for sid, site in man["sites"].items():
        assert f"['{sid}','{site['label']}',{site['sign'][0]},{site['sign'][1]}]" in app, f"app.js VILLAGE_SITES {sid}"
    # the live wheel sits on the painted axle, the gate board hangs between the painted posts
    wheel = re.search(r"function villageWaterWheel\(\)\{(.*?)return w;\}", app).group(1)
    box = [float(v) for v in re.findall(r"w\.style\.(?:left|top|width|height)='([\d.]+)%'", wheel)]
    assert len(box) == 4 and all(abs(x - y) < .06 for x, y in zip(box, man["wheel_box"])), (box, man["wheel_box"])
    # the gate board (the DOM button art) hangs between the painted posts, above the road
    g = man["gate_board"]
    (nx, ny), (fx, fy) = g["posts"]
    x0, y0, w, h = g["board_box"]
    assert nx < x0 and x0 + w < fx + 6 and y0 + h < max(ny, fy), g
    assert (WORK / "a" / "gate_board.svg").read_text(encoding="utf-8").count('class="vg-hit"') == 1


if __name__ == "__main__":
    test_village_generator_is_reproducible()
    test_live_layers_match_app()
    print("ok")
