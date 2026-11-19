"""Building benefits preview; run the browser inside Docker.

python scripts/art/village/preview_building_effects.py --out /out
The output directory may be mounted from F:; browser profile stays in Docker.
After owner approval, --install-reviewed installs only the six-symbol sprite and
its generated manifest. It never rebuilds or replaces the village background.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import harness

CAPTURE_RETRIES = []


def capture(html, path, size, mounts=None):
    """Wait for SVG compositing; retry only Chromium's transient capture error."""
    from playwright.sync_api import sync_playwright
    harness._env_browsers()
    for attempt in range(3):
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=harness._chromium(), args=['--disable-gpu', '--force-color-profile=srgb'])
                try:
                    page = browser.new_page(viewport={'width': size[0], 'height': size[1]}, device_scale_factor=1)
                    errors = []
                    page.on('pageerror', lambda err: errors.append(str(err)))
                    def route(req):
                        url = req.request.url[len(harness.ORIGIN):].split('?')[0]
                        if url == '/index.html':
                            return req.fulfill(body=html, content_type='text/html')
                        prefix = next((key for key in (mounts or {}) if url.startswith(key)), None)
                        target = Path(mounts[prefix]) / url[len(prefix):] if prefix else None
                        if target is None or not target.is_file():
                            return req.fulfill(status=404, body='')
                        return req.fulfill(body=target.read_bytes(), content_type=harness.TYPES.get(target.suffix, 'application/octet-stream'))
                    page.route(harness.ORIGIN + '/**', route)
                    page.goto(harness.ORIGIN + '/index.html')
                    page.wait_for_load_state('networkidle')
                    page.evaluate('async () => {await document.fonts.ready; await Promise.all([...document.images].map(i=>i.decode())); await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));}')
                    if errors:
                        raise RuntimeError('Preview JavaScript error: ' + '; '.join(errors))
                    page.screenshot(path=str(path), full_page=False)
                    print('captured ' + path.name, flush=True)
                finally:
                    browser.close()
            return
        except Exception as exc:
            if 'Page.captureScreenshot' not in str(exc) or attempt == 2:
                raise
            CAPTURE_RETRIES.append({'file': path.name, 'attempt': attempt + 1})
            print('retry compositor capture ' + path.name, flush=True)


def inner(svg):
    return svg.split('>', 1)[1].rsplit('</svg>', 1)[0]


def scene(build, effects, crop, new, night):
    ids = ['site-tavern-done', 'site-greenhouse-done', 'site-fairground-done', 'site-stalls-done']
    ids += ['stall-' + s['id'] + '-open' for s in build['stalls']]
    body = '<image href="/files/world.png" width="2400" height="1800"/>'
    body += ''.join(inner(build['files'][key]) for key in ids)
    if new:
        body += ''.join(p['body'] for p in effects['pieces'].values())
    if night:
        body += '<rect width="2400" height="1800" fill="#142d4b" opacity=".44"/>'
        body += ''.join(inner(build['files'][key + '-night']) for key in ids if key + '-night' in build['files'])
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="' + ' '.join(map(str, crop)) + '">' + body + '</svg>'


def page(left, right, title, night):
    return f'''<!doctype html><html lang="ru"><meta charset="utf-8"><title>{title}</title>
<style>*{{box-sizing:border-box}}body{{margin:0;padding:18px;font:16px system-ui;background:{'#182b28' if night else '#f3f1e5'};color:{'#f4ede0' if night else '#304b36'}}}
h1{{font-size:22px;line-height:1.25;margin:0 0 8px}}p{{line-height:1.4;margin:0 0 14px}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}h2{{font-size:16px;margin:0 0 8px}}.art{{background:{'#223932' if night else '#c1d5a3'};border-radius:12px;overflow:hidden}}svg{{display:block;width:100%;height:auto}}
.note{{margin-top:14px;font-size:14px;opacity:.85}}@media(max-width:500px){{body{{padding:12px}}h1{{font-size:20px}}h2{{font-size:14px;min-height:40px}}.pair{{gap:8px}}}}</style>
<h1>{title}</h1><p>{'Ночь · существующая тонировка и окна' if night else 'День'} · предложение, к игре не подключено</p>
<div class="pair"><section><h2>Сейчас · генератор фермы</h2><div class="art">{left}</div></section><section><h2>Новое · те же функции</h2><div class="art">{right}</div></section></div>
<p class="note">Скамья, меню и флаг — публичные отличия. Два прилавка используют существующие шатры; подиум стоит на прежней сцене. Имена ферм и любимое блюдо подставит интерфейс из разрешённой серверной проекции.</p></html>'''


def path_overlaps(walk, layout, placements):
    """Check the candidate footprints against the unchanged live walking graph."""
    m = layout['matrix']
    def tile(x, y):
        a, b = (x - m[4]) / (m[0] * 36), (y - m[5]) / (m[3] * 18)
        return ((a + b) / 2, (b - a) / 2)
    nodes = [tile(*walk['nodes'][i:i + 2]) for i in range(0, len(walk['nodes']), 2)]
    found = set()
    for i in range(0, len(walk['edges']), 2):
        a, b = (nodes[k] for k in walk['edges'][i:i + 2])
        n = max(1, math.ceil(math.dist(a, b) / .035))
        for step in range(n + 1):
            x, y = (a[k] + (b[k] - a[k]) * step / n for k in (0, 1))
            for key, placement in placements.items():
                x0, y0, x1, y1 = placement['footprint']
                if x0 < x < x1 and y0 < y < y1:
                    found.add(key)
    return sorted(found)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reuse-fairground', action='store_true', help='Reuse already inspected unchanged fairground captures; render missing frames.')
    parser.add_argument('--install-reviewed', action='store_true', help='Install the verified output after owner approval; no browser or background rebuild.')
    parser.add_argument('--geometry-only', action='store_true', help='Verify/export geometry; live UI renderer owns final screenshots.')
    args = parser.parse_args()
    out = args.out.resolve()
    if args.install_reviewed:
        manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
        if (not manifest.get('deterministic') or manifest.get('walk_graph_overlaps') != []
                or len(manifest.get('tree_overlap_pixels', {})) != 6
                or any(manifest['tree_overlap_pixels'].values())):
            raise RuntimeError('Only a complete tree-clear verified preview can be installed')
        sprite = (out / manifest['sprite']).read_text(encoding='utf-8')
        root = ET.fromstring(sprite)
        symbols = root.findall('{http://www.w3.org/2000/svg}symbol')
        if len(symbols) != 6 or root.findall('.//{http://www.w3.org/2000/svg}image'):
            raise RuntimeError('Expected exactly six pure-vector symbols')
        for key, check in manifest['checks'].items():
            data = (out / (key + '.svg')).read_bytes()
            if hashlib.sha256(data).hexdigest() != check['sha256']:
                raise RuntimeError('Preview geometry changed after verification: ' + key)
        config = {'asset': manifest['sprite'],
                  'boxes': {key: item['box'] for key, item in manifest['pieces'].items()},
                  'pieces': manifest['pieces']}
        (harness.STATIC / manifest['sprite']).write_text(sprite, encoding='utf-8')
        module = '// Generated by scripts/art/village/preview_building_effects.py; edit source geometry.\n'
        module += 'export const VILLAGE_BUILDING_EFFECTS = ' + json.dumps(config, ensure_ascii=False, indent=2) + ';\n'
        (harness.STATIC / 'village_building_effects_manifest.js').write_text(module, encoding='utf-8')
        print(json.dumps({'installed': [manifest['sprite'], 'village_building_effects_manifest.js']}))
        return
    out.mkdir(parents=True, exist_ok=True)
    result = harness.run('building_effects.js', {})
    effects, build = result['effects'], result['build']
    repeat = harness.run('building_effects.js', {'layout': build['layout']})['effects']
    if effects != repeat:
        raise RuntimeError('Building effects are not deterministic')
    overlaps = path_overlaps(result['walk'], build['layout'], effects['placements'])
    if overlaps:
        raise RuntimeError('Proposed art blocks the existing walk graph: ' + ', '.join(overlaps))
    if any(result['tree_overlaps'].values()):
        raise RuntimeError('Proposed art overlaps actual tree crowns/trunks: ' + json.dumps(result['tree_overlaps']))
    (out / 'world.png').write_bytes(result['world'])
    (out / 'village-building-effects.svg').write_text(effects['sprite'], encoding='utf-8')
    checks = {}
    for key, svg in effects['files'].items():
        root = ET.fromstring(svg)
        assert not root.findall('.//{http://www.w3.org/2000/svg}image') and 'data:image' not in svg
        (out / (key + '.svg')).write_text(svg, encoding='utf-8')
        checks[key] = {'bytes': len(svg.encode()), 'sha256': hashlib.sha256(svg.encode()).hexdigest(), 'image_nodes': 0}
    # Same generated ground, buildings and camera on each side: only the proposed
    # live pieces differ. Crops include their complete physical footprints.
    crops = {'overview': ([0, 0, 2400, 1800], 'Деревня · общий вид')}
    for key, title in [('tavern', 'Трактир · скамья и меню'), ('fairground', 'Ярмарка · лавки, подиум и флаг')]:
        box = build['boxes']['site-' + key + '-done']
        crops[key] = ([box[0] - 45, box[1] - 25, box[2] + 90, box[3] + 90], title)
    for name, (crop, title) in crops.items():
        for night in (False, True):
            html = page(scene(build, effects, crop, False, night), scene(build, effects, crop, True, night), title, night)
            theme = 'night' if night else 'day'
            (out / f'{name}-{theme}.html').write_text(html.replace('/files/world.png', 'world.png'), encoding='utf-8')
            for size in ([] if args.geometry_only else [(375, 812), (390, 844), (1280, 800)]):
                target = out / f'{name}-{size[0]}x{size[1]}-{theme}.png'
                if args.reuse_fairground and name == 'fairground' and target.exists():
                    continue
                capture(html, target, size, {'/files/': out})
    # A large isolated contact sheet catches detached supports and small-face
    # details that are intentionally tiny on the full village map.
    cards = ''.join('<section><h2>' + key + '</h2>' + svg + '</section>' for key, svg in effects['files'].items())
    sheet = '<html><meta charset="utf-8"><style>body{margin:0;padding:20px;background:#f3f1e5;font:14px system-ui;color:#304b36}main{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}h2{font-size:14px}section{background:#c1d5a3;border-radius:12px;padding:12px}svg{width:100%;height:270px}</style><main>' + cards + '</main></html>'
    (out / 'details.html').write_text(sheet, encoding='utf-8')
    if not args.geometry_only:
        capture(sheet, out / 'details-1280x800.png', (1280, 800))
    manifest = {'status': 'preview_only_owner_review_required', 'runtime_installed': False, 'world': [2400, 1800],
                'sprite': 'village-building-effects.svg', 'deterministic': True, 'pieces': effects['placements'],
                'checks': checks, 'capture_retries': CAPTURE_RETRIES, 'walk_graph_overlaps': overlaps,
                'tree_overlap_pixels': result['tree_overlaps'], 'existing_stage': 'site-fairground-done',
                'projection_note': 'Render only grants from server; filter rating_hidden. Names/favorite dish are separate UI text/icons.',
                'source_functions': ['FarmScene.poly/ellipse/line', 'scene_buildings.fullBox/L/Q/shadowAt']}
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'out': str(out), 'symbols': len(checks), 'deterministic': True, 'runtime_installed': False}))


if __name__ == '__main__':
    main()
