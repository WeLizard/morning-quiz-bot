"""Preview of the player's two looks (player_looks.js) for the owner's approval; nothing goes into qw_farm/static.

    python scripts/art/village/preview_player_looks.py [--out DIR]

Writes into .local/player-looks-preview/ (default): player-m.svg / player-f.svg, a sheet with the figure the game shows now
next to the farmer and the farmer woman (every walking frame, ×8), the same at game size ×3 on a crop of the real village
(day and night), and the «Битва с Сантой» fighters of both looks if santa_battle.js is passed with --battle.
Checks XML, no raster and two identical runs.
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import ROOT, STATIC, run, screenshot  # noqa: E402

OUT = ROOT / '.local' / 'player-looks-preview'
WORLD_SCALE = 0.656            # village.svg CSS px per world px on a 390 px phone
UNIT = 39 / 34                 # .village-player is 39 CSS px wide for the 34-unit viewBox
SPOTS = [(1290, 1120), (797, 1030)]   # world px of the feet: by the square, on the path at the post office


def frames(svg: str) -> list[str]:
    head = svg[:svg.index('>') + 1]
    return [head + g + '</svg>' for g in re.findall(r'<g class="vp-[^"]+">.*?</g>(?=<g class="vp-|</svg>)', svg, re.S)]


def fit(svg: str, w: float, h: float, mirror: bool = False) -> str:
    tr = ' style="transform:scaleX(-1)"' if mirror else ''
    return f'<div style="width:{w:.1f}px;height:{h:.1f}px"{tr}>{svg.replace("<svg ", "<svg width=\"100%\" height=\"100%\" ", 1)}</div>'


def main() -> None:
    out = Path(sys.argv[sys.argv.index('--out') + 1]) if '--out' in sys.argv else OUT
    out.mkdir(parents=True, exist_ok=True)
    res = run('player_looks.js', {})
    if res != run('player_looks.js', {}):
        raise SystemExit('two runs differ')
    for look, svg in res.items():
        root = ET.fromstring(svg)
        if any(el.tag.endswith('image') for el in root.iter()) or 'data:image' in svg or '<filter' in svg:
            raise SystemExit(f'{look}: raster or filter inside the figure')
        (out / f'player-{look}.svg').write_text(svg, encoding='utf-8')
    app = (STATIC / 'app.js').read_text(encoding='utf-8')
    now = re.search(r"const VILLAGE_PLAYER_SVG='(.*?)';", app).group(1)

    names = {'stand': 'стоит', 'stepA': 'шаг 1', 'stepB': 'шаг 2'}

    def row(title: str, svg: str) -> str:
        cells = ''.join(f'<figure>{fit(f, 34 * 8, 52 * 8)}<figcaption>{names[p]}</figcaption></figure>'
                        for f, p in zip(frames(svg), names))
        return f'<section><h2>{title}</h2><div class="row">{cells}</div></section>'

    sheet = ('<html><head><meta charset="utf-8"><style>body{margin:0;padding:16px;background:#e8eedc;font:15px system-ui;color:#1b2319}'
             'h2{font-size:17px;margin:12px 0 4px}.row{display:flex;gap:18px;align-items:flex-end}figure{margin:0;text-align:center}'
             '</style></head><body>' + row('Сейчас в игре', now) + row('Фермер (обращение «он» и нейтральное)', res['m'])
             + row('Фермерша (обращение «она»)', res['f']) + '</body></html>')
    (out / 'sheet.html').write_text(sheet, encoding='utf-8')
    screenshot(sheet, out / 'sheet.png', (900, 1460))

    village = '/static/village.svg'
    crops = []
    for night in (False, True):
        for fx, fy in SPOTS:
            cw, ch = 150, 96
            left, top = fx * WORLD_SCALE - cw / 2, fy * WORLD_SCALE - ch * .7
            figs = ''
            for i, (svg, mirror) in enumerate(((now, False), (res['m'], False), (res['f'], False))):
                first = frames(svg)[0]
                x0 = fx * WORLD_SCALE - left + (i - 1) * 34
                figs += (f'<div style="position:absolute;left:{x0 - 34 * UNIT / 2:.1f}px;top:{fy * WORLD_SCALE - top - 48 * UNIT:.1f}px">'
                         f'{fit(first, 34 * UNIT, 52 * UNIT, mirror)}</div>')
            tint = '<div style="position:absolute;inset:0;background:linear-gradient(180deg,#16215ac2,#223a6cb0 55%,#1b2f5cb8)"></div>' if night else ''
            crops.append(
                f'<figure><div style="position:relative;width:{cw * 3}px;height:{ch * 3}px;overflow:hidden">'
                f'<div style="position:absolute;left:0;top:0;width:{cw}px;height:{ch}px;transform:scale(3);transform-origin:0 0;overflow:hidden">'
                f'<img src="{village}" style="position:absolute;left:{-left:.1f}px;top:{-top:.1f}px;width:{2400 * WORLD_SCALE:.1f}px;height:{1800 * WORLD_SCALE:.1f}px">'
                f'{tint}{figs}</div></div><figcaption>{"ночь" if night else "день"} · слева направо: сейчас, фермер, фермерша · игровой размер ×3</figcaption></figure>')
    insitu = ('<html><head><meta charset="utf-8"><style>body{margin:0;padding:16px;background:#e8eedc;font:14px system-ui;color:#1b2319}'
              '.grid{display:grid;grid-template-columns:repeat(2,auto);gap:14px}figure{margin:0}</style></head><body><div class="grid">'
              + ''.join(crops) + '</div></body></html>')
    (out / 'in-village.html').write_text(insitu, encoding='utf-8')
    screenshot(insitu, out / 'in-village.png', (960, 680))
    print(f'ok -> {out}')


if __name__ == '__main__':
    main()
