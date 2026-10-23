"""Build the village map (qw_farm/static/village.svg) with the farm's own drawing code.

    python scripts/art/village/build_village.py                 # -> .local/village-generator/out/ (preview only)
    python scripts/art/village/build_village.py --install       # also writes qw_farm/static/village.svg (owner approval first)

Outputs in --out:
    world.png      the 3200x2400 painted world (lossless, for previews and the pixel hash)
    village.svg    viewBox 2400x1800 with the world embedded once as WebP (same shape as the game asset)
    manifest.json  coordinates of the live layers in world units (night lights, chimney smoke, mill sails,
                   water wheel hub, gate posts, resident spots) — what app.js places over the art
    hashes.json    sha256 of the raw RGBA pixels, the WebP and the SVG, plus the tool versions that produced them
The render is deterministic: the scene uses a seeded generator and a fixed clock, no text is drawn on the canvas.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import harness  # noqa: E402

DEFAULT_OUT = ROOT / ".local" / "village-generator" / "out"
GAME_SVG = ROOT / "qw_farm" / "static" / "village.svg"
WEBP = {"quality": 88, "method": 6}          # the encoder settings of the 2026-10-15 asset
F = .75                                      # canvas px (3200x2400) -> world units (2400x1800)


def svg_document(webp: bytes) -> str:
    data = base64.b64encode(webp).decode()
    return ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 2400 1800" '
            'preserveAspectRatio="xMidYMid meet"><title>Деревня</title>'
            f'<image width="2400" height="1800" xlink:href="data:image/webp;base64,{data}"/></svg>')


def _app_consts() -> dict:
    src = (ROOT / "qw_farm" / "static" / "app.js").read_text(encoding="utf-8")
    decl = [src[src.index(f"const {n}="):src.index(";\n", src.index(f"const {n}=")) + 1]
            for n in ("VILLAGE_SPOTS", "VILLAGE_PLACES", "VILLAGE_VISITOR_SPOTS", "VILLAGE_C")]   # VILLAGE_C line holds START/GATE/HALL
    js = "\n".join(decl) + ("\nconsole.log(JSON.stringify({spots:VILLAGE_SPOTS,places:VILLAGE_PLACES,visitors:VILLAGE_VISITOR_SPOTS,"
                            "gate:VILLAGE_GATE,hall:VILLAGE_HALL,start:VILLAGE_START}))")
    return json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, encoding="utf-8", check=True).stdout)


def app_buttons() -> list:
    """Centres of the game's tap targets in the village (residents, guests, place signs, hall, gate), world units."""
    d = _app_consts()
    w = lambda x, y: [round(x * 24, 1), round(y * 18, 1)]  # noqa: E731
    return ([w(*v) for v in d["spots"].values()] + [w(p[3], p[4]) for p in d["places"]] + [w(*v) for v in d["visitors"]]
            + [w(*d["hall"]), w(*d["gate"])])


def festival_badge() -> list:
    """The village festival badge («Праздник с N ур.», «Праздник 2/4»), a world-unit rect: a wide DOM plate under the plaza
    (style.css .village-festival box, .village-stage-badge at its left/top). Festival decor keeps clear of it."""
    css = (ROOT / "qw_farm" / "static" / "style.css").read_text(encoding="utf-8")
    box = re.search(r"\.village-festival\{inset:auto;left:([\d.]+)%;top:([\d.]+)%;width:([\d.]+)%;height:([\d.]+)%\}", css)
    badge = re.search(r"\.village-stage-badge\{position:absolute;left:([\d.]+)%;top:([\d.]+)%", css)
    if not box or not badge:
        raise RuntimeError("style.css changed: the village festival badge is not found")
    l, t, w, h = map(float, box.groups())
    x, y = (l + w * float(badge[1]) / 100) * 24, (t + h * float(badge[2]) / 100) * 18
    # [x0, y0, x1, y1]: about 110x24 css px, which is ~260x56 world units at the phone zoom of the village
    return [round(x - 130, 1), round(y - 32, 1), round(x + 130, 1), round(y + 32, 1)]


def walk_targets() -> dict:
    """Where the client sends the player (app.js villageGo targets), in world units: these become the graph's anchors."""
    d = _app_consts()
    w = lambda x, y: [round(x * 24, 1), round(y * 18, 1)]  # noqa: E731  (% of the world -> world units)
    t = {name: w(x, y + 1.6) for name, (x, y) in d["spots"].items()}
    t.update({f"place:{p[0]}": w(p[3], p[4] + 2.4) for p in d["places"]})
    t.update({f"visitor:{i}": w(x, y + 1.6) for i, (x, y) in enumerate(d["visitors"])})
    t["gate"] = w(d["gate"][0], d["gate"][1] - 1.2)
    t["hall"] = w(d["hall"][0], d["hall"][1] + 3.6)
    t["start"] = w(*d["start"])
    return t


def manifest(meta: dict) -> dict:
    """Live-layer coordinates in village world units, built the way the 2026-10-15 export filled app.js."""
    u = lambda x, y: [round(x * F), round(y * F)]           # noqa: E731
    pc = lambda x, y: [round(x / 32, 1), round(y / 24, 1)]  # noqa: E731  (percent of the world)
    lights = [meta["gate_art"]["lantern"] + ["l"]]          # the lantern on the «Ферма» gate (gate.js)
    if meta.get("den"):                                      # the bear den's round window (added by hand then)
        lights.append(u(*meta["den"]["window"]) + ["r"])
    for i, (x, y, k) in enumerate(meta["windows"]):
        if k == "r" or (i * 7) % 10 < 8:                     # a few windows stay dark
            lights.append(u(x, y) + [k])
    for c in (meta["clock"], meta["clock2"]):
        lights.append(u(*c) + ["c"])
    for x, y in meta["lamps"]:
        lights.append(u(x, y) + ["l"])
        lights.append(u(x, y + 56) + ["p"])
    return {
        "world": [2400, 1800],
        "lights": lights,
        "smoke": [u(x, y) for x, y in meta["smoke"]],
        "sails": [u(x, y) for x, y in meta["sails"]],
        "wheel_hub": u(*meta["wheel"]),
        # box of the live wheel (app.js villageWaterWheel, % of the world): VILLAGE_WHEEL_SVG viewBox -40 -50 80 95, hub at 0,0
        "wheel_box": [round((meta["wheel"][0] * F - 40) / 24, 2), round((meta["wheel"][1] * F - 50) / 18, 2), 3.33, 5.28],
        # the «Ферма» board = the DOM button (app.js VILLAGE_GATE_SIGN / VILLAGE_GATE_BOARD): its art and box come from here
        "gate_board": {"posts": [[round(x, 1), round(y, 1)] for x, y in meta["gate_art"]["posts"]],
                 "board_box": meta["gate_art"]["board"]["box"], "board_pct": meta["gate_art"]["board"]["pct"],
                 "lantern": meta["gate_art"]["lantern"]},
        "spots": {k: pc(x, y - 26) for k, (x, y) in meta["spots"].items()},
        "hall": pc(*meta["hall"]),
        "gate": pc(meta["gate"][0], meta["gate"][1] - 70),
        "plaza_corner": u(*meta["plaza"][0]),
        # construction (build.js, FARM_VILLAGE_CONSTRUCTION.md §6): sites by id — caption point (% of the world), boxes of the stage
        # pieces and the crew's foot points (world units); the stalls of the rows — owner, place (tiles) and boxes
        "sites": {s["id"]: {"label": s["label"], "sign": pc(*s["at"])} for s in meta["sites"]},
        "build": {"boxes": meta["build"]["boxes"], "crew": meta["build"]["crew"]},
        "stalls": meta["build"]["stalls"],
        # the peddler (merchant.js): cart layer box and the magpie's foot point, world units
        "merchant": {"cart": meta["merchant"]["cart"], "foot": meta["merchant"]["foot"]},
        # walk graph (walk.js, README «Граф проходимости»): flat world-unit node pairs, flat index pairs, named anchors
        "walk": {k: meta["walk"][k] for k in ("nodes", "edges", "anchors", "areas")},
        # the New Year fir on the plaza and its empty loops for the players' named toys (fest_ny_toy), world units
        "new_year_fir": {k: meta["fest"]["new_year"][k] for k in ("fir", "hooks")},
        "problems": meta.get("problems", []) + meta["walk"]["problems"] + [p for f in meta["fest"].values() for p in f["problems"]],
    }


INPUTS = ("scripts/art/village/gate.js", "scripts/art/village/svg_ctx.js", "scripts/art/village/walk.js", "scripts/art/village/player.js", "scripts/art/village/fest_posidelki.js", "scripts/art/village/fest_kit.js", "scripts/art/village/fest_snow.js", "scripts/art/village/fest_newyear.js", "scripts/art/village/fest_maslenitsa.js", "scripts/art/village/fest_flowers.js", "scripts/art/village/build.js", "scripts/art/village/crew.js", "scripts/art/village/merchant.js", "qw_farm/static/scene_buildings.js", "qw_farm/static/scene.js", "qw_farm/static/scene_expansion.js",
          "qw_farm/static/scene_map.js", "scripts/art/village/village.js", "scripts/art/village/common.js")


def inputs() -> dict:
    """sha256 of everything the picture depends on: a changed hash here explains a changed picture."""
    out = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()[:16] for p in INPUTS}
    return out


def versions() -> dict:
    import PIL
    from PIL import features
    return {"chromium": Path(harness._chromium() or "playwright-default").parent.parent.name,
            "pillow": PIL.__version__, "libwebp": features.version("webp")}


def build(out: Path, install: bool = False) -> dict:
    from PIL import Image
    harness._env_browsers()
    res = harness.run("village.js", {"targets": walk_targets(), "buttons": app_buttons(), "badge": festival_badge()})
    out.mkdir(parents=True, exist_ok=True)
    png = res["world"]
    im = Image.open(io.BytesIO(png)).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "WEBP", **WEBP)
    webp = buf.getvalue()
    svg = svg_document(webp)
    man = manifest(res["meta"])
    (out / "world.png").write_bytes(png)
    (out / "village.svg").write_text(svg, encoding="utf-8", newline="")
    (out / "walk_check.json").write_text(json.dumps({"graph": res["meta"]["walk"]["debug"], "blockers": res["meta"]["walk_blockers"],
                                                     "dropped": res["meta"]["walk"]["dropped"]}, ensure_ascii=False), encoding="utf-8")
    (out / "player.svg").write_text(res["meta"]["player"], encoding="utf-8", newline="")
    (out / "village-merchant.svg").write_text(res["meta"]["merchant"]["svg"], encoding="utf-8", newline="")
    (out / "build").mkdir(exist_ok=True)   # construction pieces one by one (previews) and the sprite the game uses
    for pid, svg_text in res["meta"]["build"]["files"].items():
        (out / "build" / f"{pid}.svg").write_text(svg_text, encoding="utf-8", newline="")
    (out / "village-build.svg").write_text(res["meta"]["build"]["sprite"], encoding="utf-8", newline="")
    for name, svg_text in res["meta"]["build"]["figures"].items():   # the crew (crew.js): inline in app.js VILLAGE_CREW
        (out / "build" / f"crew-{name}.svg").write_text(svg_text, encoding="utf-8", newline="")
    (out / "merchant-figure.svg").write_text(res["meta"]["merchant"]["figure"], encoding="utf-8", newline="")
    for fid, layer in res["meta"]["fest"].items():   # festival layers: qw_farm/static/village-fest-<id>.svg
        (out / f"village-fest-{fid}.svg").write_text(layer["svg"], encoding="utf-8", newline="")
    (out / "gate_board.svg").write_text(res["meta"]["gate_art"]["board"]["svg"], encoding="utf-8", newline="")
    (out / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    hashes = {"rgba_sha256": hashlib.sha256(im.tobytes()).hexdigest(),
              "webp_sha256": hashlib.sha256(webp).hexdigest(),
              "svg_sha256": hashlib.sha256(svg.encode()).hexdigest(),
              "svg_bytes": len(svg.encode()), "versions": versions(), "inputs": inputs(),
              "fest_sha256": {fid: hashlib.sha256(f["svg"].encode()).hexdigest() for fid, f in res["meta"]["fest"].items()},
              "merchant_sha256": hashlib.sha256((res["meta"]["merchant"]["svg"] + res["meta"]["merchant"]["figure"]).encode()).hexdigest(),
              "build_sha256": hashlib.sha256(res["meta"]["build"]["sprite"].encode()).hexdigest()}
    (out / "hashes.json").write_text(json.dumps(hashes, indent=1), encoding="utf-8")
    if man["problems"]:
        print("layout problems:", *man["problems"], sep="\n  ")
    if install:
        GAME_SVG.write_text(svg, encoding="utf-8", newline="")
        for fid, layer in res["meta"]["fest"].items():
            (GAME_SVG.parent / f"village-fest-{fid}.svg").write_text(layer["svg"], encoding="utf-8", newline="")
        (GAME_SVG.parent / "village-merchant.svg").write_text(res["meta"]["merchant"]["svg"], encoding="utf-8", newline="")
        (GAME_SVG.parent / "village-build.svg").write_text(res["meta"]["build"]["sprite"], encoding="utf-8", newline="")
        print("installed", GAME_SVG, "and festival layers", ", ".join(res["meta"]["fest"]))
    return hashes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--install", action="store_true", help="write qw_farm/static/village.svg (only after the owner approved the preview)")
    a = ap.parse_args()
    print(json.dumps(build(a.out, a.install), indent=1))


if __name__ == "__main__":
    main()
