"""Preview of the orchard fruit colours (qw_farm/static/scene_orchard.js, fruit()): every species reads by its fruit all cycle long.

The farm's own FarmScene (qw_farm/static/scene.js) paints fixed farm snapshots in headless Chromium.
Left half of every comparison = scene_orchard.js from git HEAD, right half = the working tree; every other module is the
working tree on both sides, so only the fruit drawing differs.

Sheets: all species and all graft looks in the phases set, fill (early / late) and ripe, at a close zoom,
day and night, regular and contrast mode. Frames: a farm with an orchard at 375x812, 390x844 and 1280x800, the same modes.

    python scripts/art/orchard_colors/preview.py [--out DIR]

Everything is written under .local/orchard-colors/ (F:), nothing goes into qw_farm/static.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STATIC = ROOT / "qw_farm" / "static"
sys.path.insert(0, str(ROOT / "scripts" / "art" / "village"))
import harness  # noqa: E402  (Playwright browsers on F:, pinned headless Chromium)

ORIGIN = "http://orchard.preview"
T0 = 1_700_000_000
CYCLE = 86400
CHANGED = ("scene_orchard.js",)
VIEWPORTS = ((375, 812), (390, 844), (1280, 800))
MODES = (("day", False, False), ("night", True, False), ("day_contrast", False, True), ("night_contrast", True, True))

# (label, cycle share passed: bloom < .25 <= set < .7 <= fill < 1, None = ripe)
PHASES = (("завязь (set)", .5), ("налив рано (fill)", .76), ("налив поздно (fill)", .96), ("спелые (ripe)", None))
SPECIES = (("apple", None, "Яблоня"), ("pear", None, "Груша"), ("cherry", None, "Вишня"), ("plum", None, "Слива"),
           ("apricot", None, "Абрикос"), ("peach", None, "Персик"), ("pomegranate", None, "Гранат"))
GRAFTS = (("apple", "paradise", "Райская яблоня"), ("pear", "bergamot", "Груша-бергамот"), ("apple", "cozy", "В чехле"),
          ("apple", "frost", "В инее"), ("apple", "bloom", "В цвету"), ("apple", None, "Яблоня"), ("pear", None, "Груша"))


# ---------- farm snapshots ----------
def tree(i, x, y, species, look=None, share=None, harvests=8, golden=False):
    """share = part of the garden year already passed (None = ripe since a while)."""
    if share is None:
        started, ready = T0 - CYCLE - 600, T0 - 600
    else:
        started, ready = T0 - int(share * CYCLE), T0 + int((1 - share) * CYCLE)
    return dict(id=f"t{i}", type="tree", species=species, x=x, y=y, w=1, h=1, revision=0, harvests=harvests,
                planted_at=T0 - 30 * CYCLE, cost=2000, look=look,
                fruit=dict(started_at=started, ready_at=ready, qty=6, xp=1, pest=None, golden=golden, helped=False))


def sheet_snapshot(kinds) -> tuple[dict, list]:
    """Trees on a screen grid: column = kind, row = phase. Returns the farm and [(row, col, x, y)]."""
    objs, cells = [], []
    for r, (_, share) in enumerate(PHASES):
        for c, (sp, look, _) in enumerate(kinds):
            x, y = c + 3 * r + 1, 12 - c + 3 * r
            objs.append(tree(len(objs), x, y, sp, look, share))
            cells.append((r, c, x, y))
    return dict(id="orchard-sheet", name="Ферма", size=24, level=50, server_time=T0, is_owner=True, objects=objs,
                home_projects={"entries": {}}, coins=0, xp=0), cells


def building(i, typ, x, y, w=2, h=2):
    return dict(id=f"b{i}", type=typ, x=x, y=y, w=w, h=h, revision=0, level=1, jobs=[], animal=None, animal_job=None)


def plot(i, x, y, crop, left):
    return dict(id=f"p{i}", type="plot", x=x, y=y, w=1, h=1, revision=0,
                crop=dict(id=crop, planted_at=T0 - 1800 + left, ready_at=T0 + left, yield_qty=3, xp=2, helped=False, cost=0, gift=0))


def farm_snapshot() -> dict:
    """A farm with an orchard: every species and the two fruit grafts in mixed phases, one golden ripe apple."""
    objs = [building(0, "house", 0, 0), building(1, "barn", 0, 3), building(2, "mill", 3, 0), building(3, "coop", 6, 0),
            building(4, "dryer", 9, 0)]
    crops = ["wheat", "carrot", "corn", "strawberry", "potato", "tomato"]
    for k, (x, y) in enumerate((x, y) for y in (3, 4) for x in range(3, 9)):
        objs.append(plot(k, x, y, crops[(x + y) % len(crops)], -60 if k == 0 else 600 + k * 120))
    plan = [  # (x, y, species, look, share)
        (0, 6, "apple", None, .5), (1, 6, "pear", None, .78), (2, 6, "cherry", None, .9), (3, 6, "plum", None, .6),
        (4, 6, "apricot", None, .85), (5, 6, "peach", None, .95), (6, 6, "pomegranate", None, .8),
        (0, 8, "apple", "paradise", .9), (1, 8, "pear", "bergamot", .7), (2, 8, "cherry", None, None), (3, 8, "plum", None, None),
        (4, 8, "apricot", None, None), (5, 8, "peach", None, None), (6, 8, "pomegranate", None, None),
        (0, 10, "apple", None, None), (1, 10, "pear", None, None), (2, 10, "apple", "paradise", None), (3, 10, "pear", "bergamot", None),
        (4, 10, "apple", None, .92), (5, 10, "pear", None, .55), (6, 10, "plum", None, .95),
    ]
    for j, (x, y, sp, look, share) in enumerate(plan):
        objs.append(tree(j, x, y, sp, look, share, golden=(j == 14)))
    for x in range(7, 12):
        objs.append(dict(id=f"r{x}", type="road", x=x, y=7, w=1, h=1, revision=0))
    return dict(id="orchard-farm", name="Ферма", size=12, level=50, server_time=T0, is_owner=True, objects=objs,
                home_projects={"entries": {}}, coins=0, xp=0)


# ---------- page ----------
PAGE = """<!doctype html><html%(attr)s><meta charset="utf-8">
<style>html,body{margin:0;height:100%%;overflow:hidden;background:#000}#c{display:block;width:100vw;height:100vh;%(filter)s}</style>
<canvas id="c"></canvas>
<script>window.FARM=%(farm)s;window.CATALOG=%(catalog)s;</script>
<script type="module">
import {FarmScene} from '/%(base)s/scene.js';
const cv=document.getElementById('c'),scene=new FarmScene(cv,{iconSheet:'/%(base)s/icons.svg'});
scene.now=()=>%(t0)d;
scene.set(window.FARM,window.CATALOG);scene.now=()=>%(t0)d;
scene.setPaused(true);scene.motion=%(motion)s;
scene.setLighting(%(light)s);scene.resize();scene.fit();
const cam=%(cam)s;if(cam){scene.scale=cam.scale;scene.centerOn(cam.x,cam.y)}
scene.selected=null;scene.draw(%(time)s);
await scene.iconSheet();await new Promise(r=>setTimeout(r,400));scene.draw(%(time)s);
window.__geo={o:scene.origin(),s:scene.scale};window.__done=true;
</script></html>"""


def P(x, y):
    return {"x": (x - y) * 36, "y": (x + y) * 18}


class Renderer:
    def __init__(self, head_dir: Path, catalog: dict):
        self.head_dir = head_dir
        self.catalog = json.dumps(catalog, ensure_ascii=False)

    def __enter__(self):
        harness._env_browsers()
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(executable_path=harness._chromium(), args=[
            "--disable-gpu", "--force-color-profile=srgb", "--font-render-hinting=none", "--disable-lcd-text"])
        return self

    def __exit__(self, *a):
        self.browser.close()
        self.pw.stop()

    def shot(self, path: Path, size, farm, *, head=False, night=False, contrast=False, cam=None, time=0, motion=False):
        html = PAGE % dict(attr=' data-qw-contrast="1"' if contrast else "",
                           filter="filter:saturate(1.18) contrast(1.1)" if contrast else "",
                           farm=json.dumps(farm, ensure_ascii=False), catalog=self.catalog,
                           base="head" if head else "static", t0=T0, motion="true" if motion else "false", time=time,
                           light=json.dumps({"mode": "night" if night else "day", "phase": "night" if night else "day",
                                             "darkness": 1 if night else 0, "warmth": 0}),
                           cam=json.dumps(cam))
        page = self.browser.new_page(viewport={"width": size[0], "height": size[1]}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        def handle(route):
            url = route.request.url[len(ORIGIN):].split("?")[0]
            if url == "/index.html":
                return route.fulfill(body=html, content_type="text/html")
            for prefix, base in (("/static/", STATIC), ("/head/", self.head_dir)):
                if url.startswith(prefix):
                    p = base / url[len(prefix):]
                    if p.is_file():
                        return route.fulfill(body=p.read_bytes(), content_type=harness.TYPES.get(p.suffix, "application/octet-stream"))
            return route.fulfill(status=404, body="")

        page.route(ORIGIN + "/**", handle)
        page.goto(ORIGIN + "/index.html")
        page.wait_for_function("window.__done === true", timeout=30000)
        geo = page.evaluate("window.__geo")
        page.screenshot(path=str(path))
        page.close()
        if errors:
            raise RuntimeError(f"{path.name}: " + "\n".join(errors))
        return geo


# ---------- sheets ----------
def font(size=15):
    from PIL import ImageFont
    for name in ("segoeuib.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def side_by_side(left: Path, right: Path, out: Path, title: str):
    from PIL import Image, ImageDraw
    a, b = Image.open(left).convert("RGB"), Image.open(right).convert("RGB")
    gap, top = 16, 34
    img = Image.new("RGB", (a.width + b.width + gap, max(a.height, b.height) + top), "#f3efe2")
    img.paste(a, (0, top)); img.paste(b, (a.width + gap, top))
    d = ImageDraw.Draw(img); f = font()
    d.text((8, 8), "как сейчас · " + title, fill="#2b2a22", font=f)
    d.text((a.width + gap + 8, 8), "новое: цвет плодов по виду · " + title, fill="#2b2a22", font=f)
    img.save(out)


def crop_cells(shot: Path, geo, cells, kinds):
    """The grid of tree cells cut from one render: rows = phases, columns = kinds."""
    from PIL import Image
    img = Image.open(shot).convert("RGB")
    s, o = geo["s"], geo["o"]
    cw, top, bottom = int(37 * s), int(92 * s), int(16 * s)
    grid = Image.new("RGB", (cw * 2 * len(kinds), (top + bottom) * len(PHASES)), "#000")
    for r, c, x, y in cells:
        p = P(x + .5, y + .5)
        sx, sy = o["x"] + p["x"] * s, o["y"] + p["y"] * s
        grid.paste(img.crop((int(sx - cw), int(sy - top), int(sx + cw), int(sy + bottom))), (c * 2 * cw, r * (top + bottom)))
    return grid, 2 * cw, top + bottom


def sheet(old, new, kinds, out: Path, title: str):
    from PIL import Image, ImageDraw
    (ga, cw, ch), (gb, _, _) = old, new
    lab, head, gap = 160, 56, 24
    img = Image.new("RGB", (lab + ga.width + gap + gb.width, head + ga.height), "#f3efe2")
    img.paste(ga, (lab, head)); img.paste(gb, (lab + ga.width + gap, head))
    d = ImageDraw.Draw(img); f, fs = font(15), font(12)
    d.text((8, 32), title, fill="#2b2a22", font=fs)
    d.text((lab + 6, 6), "как сейчас", fill="#2b2a22", font=f)
    d.text((lab + ga.width + gap + 6, 6), "новое", fill="#2b2a22", font=f)
    for base in (lab, lab + ga.width + gap):
        for c, (_, _, name) in enumerate(kinds):
            d.text((base + c * cw + 6, 32), name, fill="#2b2a22", font=fs)
    for r, (name, _) in enumerate(PHASES):
        d.text((8, head + r * ch + ch // 2 - 8), name, fill="#2b2a22", font=fs)
    img.save(out)


def head_static(dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(STATIC, dst)
    for name in CHANGED:
        data = subprocess.run(["git", "show", f"HEAD:qw_farm/static/{name}"], cwd=ROOT, capture_output=True, check=True).stdout
        (dst / name).write_bytes(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".local" / "orchard-colors"))
    out = Path(ap.parse_args().out)
    raw, frames, sheets = out / "raw", out / "frames", out / "sheets"
    for d in (raw, frames, sheets):
        d.mkdir(parents=True, exist_ok=True)
    head_static(out / "head_static")
    from qw_farm.catalog import public_catalog  # noqa: E402
    catalog = json.loads(json.dumps(public_catalog(), ensure_ascii=False))
    with Renderer(out / "head_static", catalog) as r:
        for group, kinds in (("species", SPECIES), ("grafts", GRAFTS)):
            farm, cells = sheet_snapshot(kinds)
            mid = len(kinds) - 1
            centre = P(mid / 2 + 6, 17 - mid / 2)
            cam = {"scale": 1.9, "x": centre["x"], "y": centre["y"] - 40}
            for tag, night, contrast in MODES:
                res = []
                for head in (True, False):
                    shot = raw / f"sheet_{group}_{tag}_{'head' if head else 'new'}.png"
                    geo = r.shot(shot, (1500, 1000), farm, head=head, night=night, contrast=contrast, cam=cam)
                    res.append(crop_cells(shot, geo, cells, kinds))
                sheet(res[0], res[1], kinds, sheets / f"{group}_{tag}.png", f"{group} · {tag}")
        farm = farm_snapshot()
        for w, h in VIEWPORTS:
            cam = None if w >= 650 else {"scale": .85, **P(4, 8.5)}
            for tag, night, contrast in MODES:
                name = f"{w}x{h}_{tag}"
                r.shot(raw / f"{name}_head.png", (w, h), farm, head=True, night=night, contrast=contrast, cam=cam)
                r.shot(raw / f"{name}_new.png", (w, h), farm, night=night, contrast=contrast, cam=cam)
                side_by_side(raw / f"{name}_head.png", raw / f"{name}_new.png", frames / f"{name}.png", name)
        # the orchard at the desktop zoom of the game (1.8) — the closest a player sees it
        for tag, night, contrast in MODES:
            cam = {"scale": 1.8, **P(3.5, 8.5)}
            name = f"orchard_1280x800_zoom_{tag}"
            r.shot(raw / f"{name}_head.png", (1280, 800), farm, head=True, night=night, contrast=contrast, cam=cam)
            r.shot(raw / f"{name}_new.png", (1280, 800), farm, night=night, contrast=contrast, cam=cam)
            side_by_side(raw / f"{name}_head.png", raw / f"{name}_new.png", frames / f"{name}.png", name)
    print("sheets:", sheets)
    print("frames:", frames)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
