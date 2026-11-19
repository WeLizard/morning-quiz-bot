"""Preview of the «Битва с Сантой» art (santa_battle.js) for the owner's approval. Never installs into qw_farm/static.

    python scripts/art/village_games/santa_battle.py [--out DIR]

Writes into .local/santa-battle-preview/ (default): the scene SVG per theme, the square with all five fighters, a battle
moment with effects (day, night, phone width), a sheet of every pose and a sheet of the effects. Checks: two identical runs,
XML, no raster, no filters, no inline styles, every pose and effect present.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'village'))
import harness  # noqa: E402
harness.GEN = HERE.parent

EFFECTS = ['snowball', 'hit', 'blizzard', 'icestar', 'coal', 'candy', 'gift', 'chain', 'switch', 'notes', 'heal', 'wall',
           'freeze', 'rage', 'sleigh']
NAMES = {'player': 'Игрок-фермер', 'player_f': 'Игрок-фермерша', 'ded_moroz': 'Дед Мороз', 'snegurochka': 'Снегурочка', 'santa': 'Санта', 'krampus': 'Крампус'}
POSE_NAMES = {'stand': 'стоит', 'attack': 'удар', 'hurt': 'получил', 'win': 'победа', 'down': 'в сугробе', 'hide': '«В мешок!»'}
ENEMIES = {'santa', 'krampus'}


def check(svg: str, result: dict) -> None:
    root = ET.fromstring(svg)
    assert root.attrib['viewBox'] == '0 0 1000 600'
    assert not root.findall('.//{http://www.w3.org/2000/svg}image')
    assert 'data:image' not in svg and '<filter' not in svg and ' style=' not in svg
    ids = [el.attrib['id'] for el in root.iter() if 'id' in el.attrib]
    assert len(ids) == len(set(ids)), 'duplicate ids'
    need = {f'sb-{w}-{p}' for w in result['fighters'] for p in result['poses']} | {'sb-santa-hide', 'sb-stage'}
    need |= {f'sb-fx-{e}' for e in EFFECTS}
    assert need <= set(ids), sorted(need - set(ids))
    json.loads(root.attrib['data-anchors'])


def use(who: str, pose: str, x: float, y: float, k: float, mirror: bool) -> str:
    return f'<use href="#sb-{who}-{pose}" transform="translate({x} {y}) scale({-k if mirror else k} {k})"/>'


def fx(name: str, x: float, y: float, k: float) -> str:
    return f'<use href="#sb-fx-{name}" transform="translate({x} {y}) scale({k})"/>'


def staged(svg: str, stage: str) -> str:
    return svg.replace('<g id="sb-stage"></g>', f'<g id="sb-stage">{stage}</g>')


def main() -> None:
    out = Path(sys.argv[sys.argv.index('--out') + 1]) if '--out' in sys.argv else harness.ROOT.resolve() / '.local' / 'santa-battle-preview'
    if os.name == 'nt' and out.resolve().drive.upper() != 'F:':
        raise SystemExit('Preview output must be on F:')
    out.mkdir(parents=True, exist_ok=True)
    manifest = {'status': 'preview_owner_review_required', 'themes': {}}
    pages = {}
    for night in (False, True):
        result = harness.run('village_games/santa_battle.js', {'night': night})
        assert result == harness.run('village_games/santa_battle.js', {'night': night}), 'not deterministic'
        svg = result['svg']
        check(svg, result)
        theme = 'night' if night else 'day'
        (out / f'santa-battle-{theme}.svg').write_text(svg, encoding='utf-8')
        manifest['themes'][theme] = {'bytes': len(svg.encode()), 'sha256': hashlib.sha256(svg.encode()).hexdigest()}
        a, k = result['anchors'], result['scale']
        # 1. the square with everybody standing
        line_up = ''.join(use(w, 'stand', *a[w], k, w in ENEMIES) for w in ['snegurochka', 'ded_moroz', 'player', 'krampus', 'santa'])
        # 2. a battle moment: the farmer throws, Дед Мороз strikes with the blizzard on Крампус, Снегурочка sings, Санта hid in his sack
        sx, sy = a['santa']; kx, ky = a['krampus']
        moment = (use('snegurochka', 'win', *a['snegurochka'], k, False) + fx('notes', a['snegurochka'][0] + 40, a['snegurochka'][1] - 190, k)
                  + use('ded_moroz', 'attack', *a['ded_moroz'], k, False)
                  + use('player', 'attack', *a['player'], k, False) + fx('snowball', 540, 392, k)
                  + use('krampus', 'hurt', kx, ky, k, True) + fx('blizzard', kx, ky - 110, k) + fx('hit', kx - 20, ky - 120, k * .9)
                  + use('santa', 'hide', sx, sy, k, True))
        # 3. the end: the heroes win, both guests in the snowdrift
        end = (use('snegurochka', 'win', *a['snegurochka'], k, False) + use('ded_moroz', 'win', *a['ded_moroz'], k, False)
               + use('player', 'win', *a['player'], k, False)
               + use('krampus', 'down', kx, ky, k, True) + use('santa', 'down', sx, sy, k, True))
        for name, stage in (('lineup', line_up), ('moment', moment), ('end', end)):
            pages[f'{name}-{theme}'] = staged(svg, stage)
            # the other look of the player (address form «она»): the same moment with the farmer woman
            pages[f'{name}-f-{theme}'] = staged(svg, stage.replace('#sb-player-', '#sb-player_f-'))
        # 4. sheet of poses and effects (defs from the scene, scene itself hidden)
        if not night:
            cells = []
            for who in result['fighters']:
                poses = result['poses'] + (['hide'] if who == 'santa' else [])
                row = ''.join(f'<figure><svg viewBox="-24 -56 48 62" width="168" height="217"><use href="#sb-{who}-{p}"/></svg>'
                              f'<figcaption>{POSE_NAMES[p]}</figcaption></figure>' for p in poses)
                cells.append(f'<h2>{NAMES[who]}</h2><div class="row">{row}</div>')
            fxrow = ''.join(f'<figure><svg viewBox="-28 -50 56 56" width="140" height="140"><use href="#sb-fx-{e}" transform="translate(0 -18)"/></svg>'
                            f'<figcaption>{e}</figcaption></figure>' for e in EFFECTS)
            sheet = ('<html><head><meta charset="utf-8"><style>body{margin:0;padding:16px;background:#e8eedc;font:15px system-ui;color:#1b2319}'
                     'h2{font-size:17px;margin:12px 0 4px}.row{display:flex;flex-wrap:wrap;gap:10px}figure{margin:0;text-align:center;background:#eef2f6;border-radius:10px}'
                     '.defs{position:absolute;width:0;height:0}</style></head><body>'
                     f'<div class="defs">{svg.replace("<svg ", "<svg width=\"0\" height=\"0\" ", 1)}</div>' + ''.join(cells)
                     + f'<h2>Эффекты</h2><div class="row">{fxrow}</div></body></html>')
            (out / 'poses.html').write_text(sheet, encoding='utf-8')
            harness.screenshot(sheet, out / 'poses.png', (1200, 2060))
    for name, svg in pages.items():
        page = f'<html><body style="margin:0;background:#222"><div style="width:100%">{svg.replace("<svg ", "<svg width=\"100%\" ", 1)}</div></body></html>'
        (out / f'{name}.html').write_text(page, encoding='utf-8')
        harness.screenshot(page, out / f'{name}.png', (1000, 600))
        if name.startswith('moment-'):
            harness.screenshot(page, out / f'{name}-390.png', (390, 234))
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'ok -> {out}')


if __name__ == '__main__':
    main()
