"""Preview of the «Ферма» gate: the original background, the current vector version and the generated one,
day / night / hover, at the village size of a 375 px phone (world 1600 css px) and a 1280 px desktop (world 2860 css px).

    python scripts/art/village/build_village.py && python scripts/art/village/preview_gate.py

Writes .local/village-generator-preview/gate_375.png and gate_1280.png (columns: original, current, generated).
The generated board is shown the way the game would show it after approval: the button holds gate_board.svg,
its hit shape is the painted board, hover uses the farm's --farm-lit outline. Nothing in qw_farm is changed.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import harness  # noqa: E402
from preview import app_layers, label  # noqa: E402

OUT = ROOT / ".local" / "village-generator-preview"
GEN = ROOT / ".local" / "village-generator" / "out"
ORIGINAL_PNG = ROOT / ".local" / "village-generator" / "bg_current.png"   # the WebP of village.svg before any gate overlay
CENTER = (1200.1, 1442.8)                                                 # board centre, world units
GEN_CSS = """.village-gate.vg-gen{pointer-events:none}.vg-gen .vg-hit{pointer-events:visiblePainted;cursor:pointer}
.vg-gen .vg-night{display:none}:root[data-farm-theme=night] .vg-gen .vg-day{display:none}:root[data-farm-theme=night] .vg-gen .vg-night{display:inline}"""


def gen_button(gen: Path) -> str:
    """The generated board as the game's button: box from manifest.json, art from gate_board.svg."""
    man = json.loads((gen / "manifest.json").read_text(encoding="utf-8"))
    x0, y0, w, h = man["gate_board"]["board_box"]
    return (f'<button class="village-gate vg-gen" style="left:{(x0 + w / 2) / 24:.3f}%;top:{(y0 + h / 2) / 18:.3f}%;'
            f'width:{w / 24:.3f}%;height:{h / 18:.3f}%">{(gen / "gate_board.svg").read_text(encoding="utf-8")}</button>')


def page(art: str, theme: str, world_w: int, view: tuple[int, int], L: dict, gate: str, extra_lights=()) -> str:
    k = world_w / 2400
    ox, oy = CENTER[0] * k - view[0] / 2, CENTER[1] * k - view[1] / 2
    at = lambda x, y: f"left:{x / 24:.2f}%;top:{y / 18:.2f}%"  # noqa: E731
    lights = "".join(f'<i class="vn-light vn-{c}" style="{at(x, y)}"></i>' for x, y, c in [*L["lights"], *extra_lights])
    return f"""<!doctype html><html data-farm-theme="{theme}"><meta charset="utf-8">
<link rel="stylesheet" href="/static/style.css">
<style>html,body{{margin:0;overflow:hidden;background:#fff}}*,*::before,*::after{{animation:none!important;transition:none!important}}{GEN_CSS}</style>
<div class="village-world" style="position:absolute;left:{-ox:.1f}px;top:{-oy:.1f}px;width:{world_w}px;height:{world_w * .75:.0f}px">
<img class="village-art" src="{art}" style="display:block;width:100%;height:100%">
<div class="village-sun"></div><div class="village-night"><div class="vn-tint"></div>{lights}</div>{gate}
</div></html>"""


def main():
    from PIL import Image
    OUT.mkdir(parents=True, exist_ok=True)
    work = OUT / "src"
    work.mkdir(exist_ok=True)
    Image.open(ORIGINAL_PNG).save(work / "original.png")
    shutil.copyfile(ROOT / "qw_farm" / "static" / "village.svg", work / "current.svg")
    shutil.copyfile(GEN / "village.svg", work / "generated.svg")
    man = json.loads((GEN / "manifest.json").read_text(encoding="utf-8"))
    L = app_layers()
    b = L["board"]
    cur_gate = f'<button class="village-gate" style="left:{b[0]}%;top:{b[1]}%;width:{b[2]}%;height:{b[3]}%">{L["sign"]}</button>'
    gen_gate = gen_button(GEN)
    lantern = [(*man["gate_board"]["lantern"], "l")]
    cols = [("Исходный фон", "/files/original.png", "", ()),
            ("Сейчас: вектор + кнопка", "/files/current.svg", cur_gate, ()),
            ("Генератор: стиль таблички фермы", "/files/generated.svg", gen_gate, lantern)]
    for name, world_w, view, dpr in (("375", 1600, (375, 300), 3), ("1280", 2860, (640, 400), 2)):
        rows = []
        for theme, hover in (("day", False), ("night", False), ("day", True)):
            row = []
            for title, art, gate, extra in cols:
                p = work / f"gate_{name}_{theme}_{int(hover)}_{len(row)}.png"
                harness.screenshot(page(art, theme, world_w, view, L, gate, extra), p, view, {"/files/": work}, dpr=dpr,
                                   hover=(view[0] / 2, view[1] / 2) if hover else None)
                im = Image.open(p).convert("RGB")
                cap = Image.new("RGB", (im.width, 34))
                label(cap, f"{title} · {'наведение' if hover else ('день' if theme == 'day' else 'ночь')}")
                cell = Image.new("RGB", (im.width, im.height + 34))
                cell.paste(cap, (0, 0))
                cell.paste(im, (0, 34))
                row.append(cell)
            rows.append(row)
        cw, ch = rows[0][0].size
        sheet = Image.new("RGB", (cw * 3 + 32, ch * 3 + 32), "#f4f1e6")
        for j, row in enumerate(rows):
            for i, cell in enumerate(row):
                sheet.paste(cell, (i * (cw + 16), j * (ch + 16)))
        sheet.save(OUT / f"gate_{name}.png")
    print("preview ->", OUT / "gate_375.png", OUT / "gate_1280.png")


if __name__ == "__main__":
    main()
