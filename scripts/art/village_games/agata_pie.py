"""Reproduce the «Пирог до небес» fair scene; --install writes the game assets. Never installs without the flag."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'village'))
import harness
harness.GEN = HERE.parent

# Live layers and drawings the game places (qw_farm/static/pie-game.js).
REQUIRED = {'pie-sky', 'pie-sky-0', 'pie-sky-1', 'pie-sky-2', 'pie-stars', 'pie-earth', 'pie-world', 'pie-clouds', 'pie-ground',
            'pie-scaffold', 'pie-scaffold-l', 'pie-scaffold-r', 'pie-scaffold-cliprect', 'pie-marks', 'pie-tower', 'pie-cuts',
            'pie-falling', 'pie-crane', 'pie-trolley', 'pie-layer', 'pie-korzh', 'pie-tier-a', 'pie-tier-b', 'pie-tier-deck',
            'pie-plate'}


def check(svg: str) -> None:
    root = ET.fromstring(svg)
    assert root.attrib['viewBox'] == '0 0 1000 600'
    assert not root.findall('.//{http://www.w3.org/2000/svg}image')
    assert 'data:image' not in svg and '<filter' not in svg and ' style=' not in svg
    for key in ('data-sky', 'data-stars', 'data-earth'):
        json.loads(root.attrib[key])
    ids = [el.attrib['id'] for el in root.iter() if 'id' in el.attrib]
    assert len(ids) == len(set(ids)) and REQUIRED <= set(ids), set(REQUIRED) - set(ids)


def page(svg: str, night: bool) -> str:
    colour, background = ('#e9e4c8', '#26392f') if night else ('#334c37', '#f2efdf')
    return f'''<!doctype html><html lang="ru"><meta charset="utf-8"><title>Пирог до небес · превью</title>
<style>*{{box-sizing:border-box}}body{{margin:0;padding:20px;background:{background};color:{colour};font:16px system-ui}}
h1{{font-size:24px;margin:0 0 8px}}p{{line-height:1.5;margin:0 0 18px}}.scene{{max-width:1000px;margin:0 auto}}
svg{{display:block;width:100%;height:auto;border-radius:16px}}@media(max-width:600px){{body{{padding:12px}}h1{{font-size:21px}}p{{font-size:14px}}}}</style>
<h1>Пирог до небес</h1><p>{'Ночь' if night else 'День'} · старт забега: ярмарка, леса с краном, корж на тросах, пустая подставка.</p>
<div class="scene">{svg}</div></html>'''


def preview_page(svg: str) -> str:
    return f'<html><body style="margin:0"><style>svg{{display:block;width:100%;height:100vh}}</style>{svg}</body></html>'


def main():
    if '--install' in sys.argv:
        for night in (False, True):
            result = harness.run('village_games/pie_scene.js', {'night': night})
            assert result == harness.run('village_games/pie_scene.js', {'night': night})
            svg = result['svg']
            check(svg)
            name = 'pie-night.svg' if night else 'pie-scene.svg'
            (HERE.parent.parent.parent / 'qw_farm' / 'static' / name).write_text(svg, encoding='utf-8')
            print(f'Installed {name}: {hashlib.sha256(svg.encode()).hexdigest()}')
        return
    out = harness.ROOT.resolve() / '.local' / 'pie-redo' / 'scene'
    if os.name == 'nt' and out.drive.upper() != 'F:':
        raise SystemExit('Preview output must be on F:')
    out.mkdir(parents=True, exist_ok=True)
    manifest = {'status': 'preview_owner_review_required', 'themes': {}}
    for night in (False, True):
        result = harness.run('village_games/pie_scene.js', {'night': night})
        second = harness.run('village_games/pie_scene.js', {'night': night})
        assert result == second, 'Scene output is not deterministic'
        svg = result['svg']
        check(svg)
        theme = 'night' if night else 'day'
        (out / f'pie-{theme}.svg').write_text(svg, encoding='utf-8')
        manifest['themes'][theme] = {'bytes': len(svg.encode()), 'sha256': hashlib.sha256(svg.encode()).hexdigest(),
                                     'image_nodes': 0, 'deterministic': True}
        for w, h in [(375, 812), (390, 844), (1280, 800)]:
            harness.screenshot(page(svg, night), out / f'pie-{w}x{h}-{theme}.png', (w, h))
        harness.screenshot(preview_page(svg), out / f'closeup-{theme}.png', (1000, 600))
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(out)
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == '__main__':
    main()
