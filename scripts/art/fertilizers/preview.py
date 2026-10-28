"""Preview of the fertilizer art (docs/tasks/FARM_FERTILIZERS.md §7): compost heap, fed beds, fed trees, storehouse icons.

The farm's own FarmScene (qw_farm/static/scene.js) paints a fixed farm snapshot in headless Chromium.
Left half of every comparison = the committed scene code (git HEAD) and the farm without fertilizers;
right half = the working tree with a compost heap and fed beds/trees. Frames: 375x812, 390x844, 1280x800,
day and night, regular and contrast mode, plus close-ups and the icon sheet.
A regression check renders the farm WITHOUT fertilizers with both code versions and requires identical pixels.

    python scripts/art/fertilizers/preview.py [--out DIR]

Everything is written under .local/fertilizers-art/ (F:), nothing goes into qw_farm/static.
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

ORIGIN = "http://fert.preview"
T0 = 1_700_000_000
CHANGED = ("scene.js", "scene_buildings.js", "icons.svg")
VIEWPORTS = ((375, 812), (390, 844), (1280, 800))


# ---------- farm snapshots ----------
def building(i, typ, x, y, w=2, h=2, level=1, jobs=None):
    return dict(id=f"b{i}", type=typ, x=x, y=y, w=w, h=h, revision=0, level=level, jobs=jobs or [], animal=None, animal_job=None)


def plot(i, x, y, crop=None, fed=False, left=600, total=1800):
    o = dict(id=f"p{i}", type="plot", x=x, y=y, w=1, h=1, revision=0, crop=None)
    if crop:
        o["crop"] = dict(id=crop, planted_at=T0 - (total - left), ready_at=T0 + left, yield_qty=3, xp=2, helped=False, cost=0, gift=0)
        if fed:
            o["crop"]["fert"] = 1
    return o


def tree(i, x, y, species="apple", fed=False, harvests=8, phase_left=30000, guest_flag=False):
    o = dict(id=f"t{i}", type="tree", species=species, x=x, y=y, w=1, h=1, revision=0, harvests=harvests,
             planted_at=T0 - 20 * 72000, cost=2300, look=None,
             fruit=dict(started_at=T0 - (72000 - phase_left), ready_at=T0 + phase_left, qty=2, xp=20, pest=None, golden=False, helped=False))
    if fed and guest_flag:
        o["fert"] = 1
    elif fed:
        o["fruit"]["fert"] = 1
    return o


def job(ready_in):
    return dict(id=f"j{ready_in}", recipe="compost", ready_at=T0 + ready_in, started_at=T0 - 600)


def farm_snapshot(new: bool) -> dict:
    """The comparison farm. new=False: the same farm before fertilizers (no heap, no flags)."""
    objs = [building(0, "house", 0, 0), building(1, "barn", 0, 3), building(2, "mill", 3, 0), building(3, "coop", 6, 0),
            building(4, "bakery", 9, 0), building(5, "dryer", 9, 3)]
    if new:
        objs.append(building(6, "compost_heap", 2, 5, 1, 1, jobs=[job(5400)]))
    crops = ["wheat", "carrot", "corn", "strawberry", "potato", "tomato", "cabbage", "sunflower", "pumpkin"]
    k = 0
    for y in (4, 5, 6):
        for x in range(3, 9):
            crop = crops[(x + y) % len(crops)]
            fed = new and (x + y) % 2 == 0
            left = -60 if (x == 3 and y == 4) else 300 + ((x * 7 + y * 3) % 5) * 300
            objs.append(plot(k, x, y, crop, fed, left))
            k += 1
    objs.append(plot(k, 3, 7)); k += 1
    objs.append(plot(k, 4, 7, "wheat", new, 900)); k += 1
    for j, (x, y, sp) in enumerate([(0, 8, "apple"), (1, 8, "pear"), (2, 8, "cherry"), (0, 10, "plum"), (1, 10, "apricot"), (2, 10, "pomegranate")]):
        objs.append(tree(j, x, y, sp, fed=new and j % 2 == 0, phase_left=20000 + j * 4000))
    for x in range(5, 12):
        objs.append(dict(id=f"r{x}", type="road", x=x, y=7, w=1, h=1, revision=0))
    return dict(id="fert-preview", name="Ферма", size=12, level=20, server_time=T0, is_owner=True, objects=objs,
                home_projects={"entries": {}}, coins=0, xp=0)


def closeup_snapshot(new: bool) -> dict:
    """Close-ups: the heap in every state and level beside a barn and a plot, fed vs plain beds, fed vs plain trees."""
    objs = [building(0, "barn", 0, 0), building(1, "dryer", 0, 3)]
    if new:
        for i, (x, y, lv, jobs) in enumerate([(3, 0, 1, []), (5, 0, 1, [job(5400)]), (7, 0, 1, [job(-60)]),
                                             (3, 2, 2, [job(5400)]), (5, 2, 3, [job(-60), job(9000)]), (7, 2, 3, [])]):
            objs.append(building(10 + i, "compost_heap", x, y, 1, 1, level=lv, jobs=jobs))
    k = 0
    for x, crop in enumerate(["wheat", "carrot", "corn", "strawberry", "pumpkin", "cabbage"]):
        for y, fed in ((4, False), (5, True)):
            objs.append(plot(k, 2 + x, y, crop, fed and new, 900 if x % 2 else -60)); k += 1
    objs.append(plot(k, 8, 4, None)); k += 1
    for j, (sp, x) in enumerate([("apple", 2), ("pear", 4), ("pomegranate", 6)]):
        objs.append(tree(2 * j, x, 8, sp, False, phase_left=26000))
        objs.append(tree(2 * j + 1, x + 1, 8, sp, new, phase_left=26000))
    objs.append(tree(9, 8, 8, "plum", new, harvests=0, phase_left=60000))  # young tree, fed
    return dict(id="fert-closeup", name="Ферма", size=12, level=30, server_time=T0, is_owner=True, objects=objs,
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
// contrast badges load the crop icons asynchronously: wait for them, then paint the final frame
await scene.iconSheet();await new Promise(r=>setTimeout(r,400));scene.draw(%(time)s);window.__done=true;
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

    def shot(self, path: Path, size, farm, *, head=False, night=False, contrast=False, cam=None, time=12.3, dpr=1):
        html = PAGE % dict(attr=' data-qw-contrast="1"' if contrast else "",
                           filter="filter:saturate(1.18) contrast(1.1)" if contrast else "",
                           farm=json.dumps(farm, ensure_ascii=False), catalog=self.catalog,
                           base="head" if head else "static", t0=T0, motion="true", time=time,
                           light=json.dumps({"mode": "night" if night else "day", "phase": "night" if night else "day",
                                             "darkness": 1 if night else 0, "warmth": 0}),
                           cam=json.dumps(cam))
        page = self.browser.new_page(viewport={"width": size[0], "height": size[1]}, device_scale_factor=dpr)
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
        page.screenshot(path=str(path))
        page.close()
        if errors:
            raise RuntimeError(f"{path.name}: " + "\n".join(errors))


# ---------- sheets ----------
def label_font(size=15):
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
    d = ImageDraw.Draw(img); f = label_font()
    d.text((8, 8), "ферма сейчас · " + title, fill="#2b2a22", font=f)
    d.text((a.width + gap + 8, 8), "новое: куча, подкормка · " + title, fill="#2b2a22", font=f)
    img.save(out)


def icon_sheet(r: Renderer, out: Path):
    from PIL import Image
    ids = ["manure", "compost", "humate", "hay", "feed", "flour", "wood", "herbs", "garden_infusion"]
    cells = "".join(f'<div class="c"><svg viewBox="0 0 48 48"><use href="/static/icons.svg#{i}"/></svg><b>{i}</b></div>' for i in ids)
    small = "".join(f'<svg class="s" viewBox="0 0 48 48"><use href="/static/icons.svg#{i}"/></svg>' for i in ids)
    html = ("<!doctype html><meta charset='utf-8'><style>body{margin:0;padding:16px;font:600 13px 'Segoe UI';background:#fbf7ea}"
            ".g{display:flex;gap:12px;flex-wrap:wrap}.c{background:#fff;border-radius:12px;padding:10px;text-align:center;width:120px}"
            ".c svg{width:96px;height:96px}.c b{display:block;color:#4d3c27}.s{width:32px;height:32px;margin:6px}"
            ".n{background:#203029;border-radius:12px;padding:6px;margin-top:12px}.w{background:#fff;border-radius:12px;padding:6px;margin-top:12px}"
            "</style><div class='g'>" + cells + "</div><div class='w'>" + small + "</div><div class='n'>" + small + "</div>")
    page = r.browser.new_page(viewport={"width": 1240, "height": 420}, device_scale_factor=1)

    def handle(route):
        url = route.request.url[len(ORIGIN):].split("?")[0]
        if url == "/index.html":
            return route.fulfill(body=html, content_type="text/html")
        if url.startswith("/static/"):
            return route.fulfill(body=(STATIC / url[8:]).read_bytes(), content_type="image/svg+xml")
        return route.fulfill(status=404, body="")

    page.route(ORIGIN + "/**", handle)
    page.goto(ORIGIN + "/index.html")
    page.wait_for_load_state("networkidle")
    page.screenshot(path=str(out), full_page=True)
    page.close()
    Image.open(out)  # sanity: a readable PNG


def same_pixels(a: Path, b: Path) -> bool:
    from PIL import Image, ImageChops
    return ImageChops.difference(Image.open(a).convert("RGB"), Image.open(b).convert("RGB")).getbbox() is None


def head_static(dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(STATIC, dst)
    for name in CHANGED:
        data = subprocess.run(["git", "show", f"HEAD:qw_farm/static/{name}"], cwd=ROOT, capture_output=True, check=True).stdout
        (dst / name).write_bytes(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".local" / "fertilizers-art"))
    out = Path(ap.parse_args().out)
    raw, frames, close = out / "raw", out / "frames", out / "closeups"
    for d in (raw, frames, close):
        d.mkdir(parents=True, exist_ok=True)
    head_static(out / "head_static")
    from qw_farm.catalog import public_catalog  # noqa: E402
    catalog = json.loads(json.dumps(public_catalog(), ensure_ascii=False))
    base, new = farm_snapshot(False), farm_snapshot(True)
    regress = []
    with Renderer(out / "head_static", catalog) as r:
        for w, h in VIEWPORTS:
            cam = None if w >= 650 else {"scale": .85, **P(3.6, 5.6)}
            for night in (False, True):
                for contrast in (False, True):
                    tag = f"{w}x{h}_{'night' if night else 'day'}{'_contrast' if contrast else ''}"
                    kw = dict(night=night, contrast=contrast, cam=cam)
                    r.shot(raw / f"{tag}_head.png", (w, h), base, head=True, **kw)
                    r.shot(raw / f"{tag}_base.png", (w, h), base, **kw)
                    r.shot(raw / f"{tag}_new.png", (w, h), new, **kw)
                    regress.append((tag, same_pixels(raw / f"{tag}_head.png", raw / f"{tag}_base.png")))
                    side_by_side(raw / f"{tag}_head.png", raw / f"{tag}_new.png", frames / f"{tag}.png", tag)
        cb, cn = closeup_snapshot(False), closeup_snapshot(True)
        views = {"heap": (P(5.5, 1.5), 2.0, (1000, 620)), "beds": (P(4.6, 4.9), 2.2, (900, 560)), "trees": (P(5.6, 8.2), 1.9, (980, 560))}
        for name, (pt, scale, size) in views.items():
            for night in (False, True):
                for contrast in (False, True):
                    tag = f"{name}_{'night' if night else 'day'}{'_contrast' if contrast else ''}"
                    kw = dict(night=night, contrast=contrast, cam={"scale": scale, **pt})
                    r.shot(raw / f"{tag}_head.png", size, cb, head=True, **kw)
                    r.shot(raw / f"{tag}_new.png", size, cn, **kw)
                    side_by_side(raw / f"{tag}_head.png", raw / f"{tag}_new.png", close / f"{tag}.png", tag)
            # the heap on a phone-width canvas: steam stays still
        r.shot(close / "heap_phone_still.png", (390, 420), cn, cam={"scale": 2.4, **P(5.5, 0.5)})
        icon_sheet(r, close / "icons.png")
    bad = [t for t, ok in regress if not ok]
    print("regression (farm without fertilizers, HEAD vs working tree):", "identical" if not bad else "DIFFERS: " + ", ".join(bad))
    print("frames:", frames)
    print("closeups:", close)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
