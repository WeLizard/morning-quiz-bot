"""Side-by-side preview for the owner: the current village (left) and the generated one (right), day and night.

    python scripts/art/village/preview.py [--current qw_farm/static/village.svg] [--generated .local/village-generator/out/village.svg]

Both sides get the same live layers as the game, taken from qw_farm/static/app.js and style.css: the night tint and
window/lamp lights, the water wheel, the windmill sails and the «Ферма» gate board. Animations are frozen.
Writes .local/village-generator-preview/{day,night}_full.png, {day,night}_<crop>.png and diff_*.png.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import harness  # noqa: E402

OUT = ROOT / ".local" / "village-generator-preview"
APP = ROOT / "qw_farm" / "static" / "app.js"
# crops in canvas px of the 3200x2400 world (= world units x 4/3)
CROPS = {"mill": (640, 400, 1280, 880), "gate": (1360, 1720, 1840, 2080), "plaza": (1340, 840, 1980, 1320),
         "den": (840, 1600, 1360, 1990), "river": (300, 1000, 940, 1480), "east": (2300, 1050, 2940, 1530)}


def app_layers() -> dict:
    """Live-layer constants of the game, evaluated with node straight from app.js (no copies)."""
    src = APP.read_text(encoding="utf-8")
    parts = []
    for name in ("VILLAGE_LIGHTS", "VILLAGE_GATE_BOARD", "VILLAGE_GATE_SIGN", "VILLAGE_WHEEL_SVG"):
        i = src.index(f"const {name}=")
        end = src.index("})();", i) + 5 if name == "VILLAGE_WHEEL_SVG" else src.index(";\n", i) + 1
        parts.append(src[i:end])
    sails = re.search(r"vfx-sails va'\),(\d+),(\d+)", src)
    wheel = re.search(r"function villageWaterWheel\(\)\{(.*?)return w;\}", src).group(1)
    box = dict(re.findall(r"w\.style\.(left|top|width|height)='([\d.]+%)'", wheel))
    js = "\n".join(parts) + "\nconsole.log(JSON.stringify({lights:VILLAGE_LIGHTS,board:VILLAGE_GATE_BOARD,sign:VILLAGE_GATE_SIGN,wheel:VILLAGE_WHEEL_SVG}))"
    data = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    data["sails"] = [int(sails.group(1)), int(sails.group(2))]
    data["wheel_box"] = box
    return data


def page(art_url: str, theme: str, L: dict, gate: str | None = None) -> str:
    at = lambda x, y: f"left:{x / 24:.2f}%;top:{y / 18:.2f}%"  # noqa: E731  (app.js villageAt)
    lights = "".join(f'<i class="vn-light vn-{k}" style="{at(x, y)}"></i>' for x, y, k in L["lights"])
    b, w = L["board"], L["wheel_box"]
    return f"""<!doctype html><html data-farm-theme="{theme}"><meta charset="utf-8">
<link rel="stylesheet" href="/static/style.css">
<style>html,body{{margin:0;background:#fff}}*,*::before,*::after{{animation:none!important;transition:none!important}}</style>
<div class="village-world" style="position:relative;width:3200px;height:2400px;overflow:hidden">
<img class="village-art" src="{art_url}" style="display:block;width:100%;height:100%">
<div class="village-sun"></div>
<div class="village-fx"><i class="vfx-sails va" style="{at(*L['sails'])}"><b></b><b></b><b></b><b></b></i></div>
<div class="village-night"><div class="vn-tint"></div>{lights}</div>
<i class="vfx-wheel va" style="left:{w['left']};top:{w['top']};width:{w['width']};height:{w['height']}">{L['wheel']}</i>
{gate or f'<button class="village-gate" style="left:{b[0]}%;top:{b[1]}%;width:{b[2]}%;height:{b[3]}%">{L["sign"]}</button>'}
</div></html>"""


def label(im, text):
    from PIL import ImageDraw, ImageFont
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 22)
    except OSError:
        f = ImageFont.load_default()
    d.rectangle((0, 0, im.width, 34), fill="#f4f1e6")
    d.text((10, 3), text, fill="#45644b", font=f)


def pair(a, b, left="Сейчас (qw_farm/static/village.svg)", right="Генератор (scripts/art/village)", scale=1.0):
    from PIL import Image
    if scale != 1:
        a = a.resize((round(a.width * scale), round(a.height * scale)), Image.LANCZOS)
        b = b.resize((round(b.width * scale), round(b.height * scale)), Image.LANCZOS)
    out = Image.new("RGB", (a.width * 2 + 16, a.height + 34), "#f4f1e6")
    la, lb = Image.new("RGB", (a.width, 34)), Image.new("RGB", (b.width, 34))
    label(la, left)
    label(lb, right)
    out.paste(la, (0, 0))
    out.paste(lb, (a.width + 16, 0))
    out.paste(a, (0, 34))
    out.paste(b, (a.width + 16, 34))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", type=Path, default=ROOT / "qw_farm" / "static" / "village.svg")
    ap.add_argument("--generated", type=Path, default=ROOT / ".local" / "village-generator" / "out" / "village.svg")
    a = ap.parse_args()
    from PIL import Image, ImageChops
    OUT.mkdir(parents=True, exist_ok=True)
    work = OUT / "src"
    work.mkdir(exist_ok=True)
    shutil.copyfile(a.current, work / "current.svg")      # snapshot: the game file may change while we render
    shutil.copyfile(a.generated, work / "generated.svg")
    L = app_layers()
    shots = {}
    for theme in ("day", "night"):
        for side in ("current", "generated"):
            p = work / f"{side}_{theme}.png"
            gate = None
            board = a.generated.parent / "gate_board.svg"
            if side == "generated" and board.exists():           # the generated board as the button (preview_gate.py)
                from preview_gate import GEN_CSS, gen_button
                gate = f"<style>{GEN_CSS}</style>" + gen_button(a.generated.parent)
            harness.screenshot(page(f"/files/{side}.svg", theme, L, gate), p, (3200, 2400), {"/files/": work})
            shots[side, theme] = Image.open(p).convert("RGB")
        cur, gen = shots["current", theme], shots["generated", theme]
        pair(cur, gen, scale=.5).save(OUT / f"{theme}_full.png")
        for name, box in CROPS.items():
            pair(cur.crop(box), gen.crop(box)).save(OUT / f"{theme}_{name}.png")
    # where the art itself differs (day, no overlays would be identical on both sides anyway)
    d = ImageChops.difference(shots["current", "day"], shots["generated", "day"]).convert("L").point(lambda v: 255 if v > 24 else 0)
    d.resize((1600, 1200)).save(OUT / "diff_day_mask.png")
    print("preview ->", OUT)


if __name__ == "__main__":
    main()
