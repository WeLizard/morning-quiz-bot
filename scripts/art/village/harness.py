"""Headless Chromium harness for the village art generator.

The farm's own drawing modules (qw_farm/static/scene*.js) are served from a private origin, read from the
working tree on every run. scene_buildings.js gets recorder hooks and an export line at serve time
(the same patch the 2026-10-15 generator applied to its copy): windows are recorded for the night lights,
chimney smoke and windmill sails are recorded instead of painted (they are live layers in the game); roofs,
chimneys and doors are recorded for the festival layers without changing the drawing.
Nothing is written into qw_farm/static.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STATIC = ROOT / "qw_farm" / "static"
GEN = Path(__file__).resolve().parent
ORIGIN = "http://village.gen"

# Internals of scene_buildings.js the village painter reuses (module top-level declarations there).
BUILDING_EXPORTS = (
    "TW,TH,PI,px,py,Q,L,E,wallY,wallX,top,box,fullBox,courses,ground,shadowAt,winY,winX,doorY,doorX,plinth,corners,"
    "boards,GABLE,GAMBREL,gableWall,gableRoof,hipRoof,shedRoof,shedBox,T,octBody,octTop,cone,facePt,faceQuad,cyl,"
    "barrel,crate,bale,sack,smoke,chimney,flowerPot,rail,yardFence,awning,body,roofOf,gparams,planter,TYPES"
)
# (anchor, inserted right after it) — a missing anchor fails the build instead of silently losing lights or smoke.
BUILDING_HOOKS = (
    ("function winY(s,Y,xc,z,w,h,glass='#abc9c7',frame='#f3ead2'){", "s.win&&s.win.push(['a',px(xc,Y),py(xc,Y,z+h/2),w,h]);"),
    ("function winX(s,X,yc,z,w,h,glass='#9fbebc',frame='#eadfc4'){", "s.win&&s.win.push(['b',px(X,yc),py(X,yc,z+h/2),w,h]);"),
    ("function smoke(s,x,y,z,on=true,k=1){", "if(s.smk){s.smk.push([px(x,y),py(x,y,z)]);return}"),
    # roofs, chimneys and doors, for festival layers that dress them (snow, lights, flowerbeds): recorded, the drawing is unchanged
    ("function gableRoof(s,axis,g){", "s.roofs&&s.roofs.push(['gable',axis,{...g}]);"),
    ("function hipRoof(s,x0,y0,x1,y1,zE,rise,col,ov,topFlat=0){", "s.roofs&&s.roofs.push(['hip',[x0,y0,x1,y1,zE,rise,col,ov,topFlat]]);"),
    ("function chimney(s,x,y,za,zb,col='#a8826a',w=.11){", "s.chim&&s.chim.push([x,y,za,zb,col,w]);"),
    ("function doorY(s,Y,xc,w,h,fill='#8f7556',frame='#efe5cb',arch=false){", "s.doors&&s.doors.push(['y',Y,xc,w]);"),
    ("function doorX(s,X,yc,w,h,fill='#7f6a4d',frame='#e5d9bb',arch=false){", "s.doors&&s.doors.push(['x',X,yc,w]);"),
)
SAILS = "const c=s.c;c.save();c.translate(px(hx,hy),py(hx,hy,hz));c.rotate(s.time*(work?.9:.2)+.45);"


def patch_buildings(src: str) -> str:
    for anchor, hook in BUILDING_HOOKS:
        if src.count(anchor) != 1:
            raise RuntimeError(f"scene_buildings.js changed: hook anchor not found: {anchor[:60]}")
        src = src.replace(anchor, anchor + hook)
    if src.count(SAILS) != 1:
        raise RuntimeError("scene_buildings.js changed: windmill sails anchor not found")
    i = src.index(SAILS)
    j = src.index("c.restore();", i) + len("c.restore();")
    src = src[:i] + "if(s.sails){s.sails.push([px(hx,hy),py(hx,hy,hz)])}else{" + src[i:j] + "}" + src[j:]
    return src + "\nexport {" + BUILDING_EXPORTS + "};\n"


def _module_source(path: Path) -> str:
    src = path.read_text(encoding="utf-8")
    return patch_buildings(src) if path.name == "scene_buildings.js" else src


PAGE = """<!doctype html><meta charset="utf-8"><body style="margin:0;background:#fff">
<script type="module">
import * as gen from '/gen/%(entry)s';
window.__run = async (args) => gen.render(args);
window.__ready = true;
</script></body>"""


def _env_browsers() -> None:
    # Playwright browsers live on F: (see CLAUDE.md: nothing heavy on C:).
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", r"F:\Caches\ms-playwright")


def _chromium() -> str | None:
    """A pinned Chromium build keeps the raster stable; VILLAGE_CHROMIUM overrides it, None = Playwright's own."""
    if os.environ.get("VILLAGE_CHROMIUM"):
        return os.environ["VILLAGE_CHROMIUM"]
    base = Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"])
    found = sorted(base.glob("chromium_headless_shell-*/chrome-*/headless_shell.exe")) + sorted(base.glob("chromium_headless_shell-*/chrome-*/chrome-headless-shell.exe"))
    return str(found[-1]) if found else None


TYPES = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png",
         ".webp": "image/webp", ".html": "text/html", ".json": "application/json"}


def run(entry: str, args: dict, viewport=(800, 600), mounts: dict | None = None) -> dict:
    """Load /gen/<entry> in headless Chromium and return the JSON result of render(args).
    PNG layers come back as data URLs and are decoded to bytes under the same keys.
    mounts: extra URL prefixes ('/files/') served from local directories (previews)."""
    _env_browsers()
    from playwright.sync_api import sync_playwright

    def handle(route):
        url = route.request.url[len(ORIGIN):].split("?")[0]
        if url == "/index.html":
            return route.fulfill(body=PAGE % {"entry": entry}, content_type="text/html")
        if url.startswith("/static/"):
            p = STATIC / url[len("/static/"):]
        elif url.startswith("/gen/"):
            p = GEN / url[len("/gen/"):]
        else:
            prefix = next((m for m in (mounts or {}) if url.startswith(m)), None)
            if prefix is None:
                return route.fulfill(status=404, body="")
            p = Path(mounts[prefix]) / url[len(prefix):]
        if not p.is_file():
            return route.fulfill(status=404, body="")
        if p.suffix == ".js":
            return route.fulfill(body=_module_source(p), content_type="text/javascript")
        return route.fulfill(body=p.read_bytes(), content_type=TYPES.get(p.suffix, "application/octet-stream"))

    with sync_playwright() as pw:
        # Software rasteriser, fixed DPR and fonts from the system: the same machine gives the same pixels.
        browser = pw.chromium.launch(executable_path=_chromium(), args=["--disable-gpu", "--force-color-profile=srgb", "--font-render-hinting=none",
                                           "--disable-lcd-text", "--disable-font-subpixel-positioning"])
        page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]}, device_scale_factor=1)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.route(ORIGIN + "/**", handle)
        page.goto(ORIGIN + "/index.html")
        try:
            page.wait_for_function("window.__ready === true", timeout=30000)
        except Exception as exc:   # a module that fails to load never sets __ready: show why
            browser.close()
            raise RuntimeError("generator page did not load:\n" + "\n".join(errors)) from exc
        result = page.evaluate("args => window.__run(args)", args)
        browser.close()
    if errors:
        raise RuntimeError("generator page errors:\n" + "\n".join(errors))
    out = {}
    for k, v in (result or {}).items():
        if isinstance(v, str) and v.startswith("data:image/png;base64,"):
            out[k] = base64.b64decode(v.split(",", 1)[1])
        else:
            out[k] = v
    return out


def screenshot(html: str, path: Path, size: tuple[int, int], mounts: dict | None = None, dpr: float = 1,
               clip: dict | None = None, hover: tuple[float, float] | None = None) -> None:
    """Render a static page (served at /index.html, with /static/ and mounts) and save a PNG screenshot
    (whole viewport or clip {x, y, width, height} in css px; hover = pointer position before the shot)."""
    _env_browsers()
    from playwright.sync_api import sync_playwright

    def handle(route):
        url = route.request.url[len(ORIGIN):].split("?")[0]
        if url == "/index.html":
            return route.fulfill(body=html, content_type="text/html")
        base = {"/static/": STATIC, **(mounts or {})}
        prefix = next((m for m in base if url.startswith(m)), None)
        p = Path(base[prefix]) / url[len(prefix):] if prefix else None
        if p is None or not p.is_file():
            return route.fulfill(status=404, body="")
        return route.fulfill(body=p.read_bytes(), content_type=TYPES.get(p.suffix, "application/octet-stream"))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=_chromium(), args=["--disable-gpu", "--force-color-profile=srgb"])
        page = browser.new_page(viewport={"width": size[0], "height": size[1]}, device_scale_factor=dpr)
        page.route(ORIGIN + "/**", handle)
        page.goto(ORIGIN + "/index.html")
        page.wait_for_load_state("networkidle")
        page.evaluate("() => Promise.all([...document.images].map(i => i.decode()))")
        if hover:
            page.mouse.move(*hover)
        page.screenshot(path=str(path), full_page=False, clip=clip)
        browser.close()


if __name__ == "__main__":
    import sys
    res = run(sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 else {})
    for k, v in res.items():
        if isinstance(v, bytes):
            Path(sys.argv[3] if len(sys.argv) > 3 else ".").joinpath(k + ".png").write_bytes(v)
        else:
            print(k, json.dumps(v, ensure_ascii=False)[:400])
