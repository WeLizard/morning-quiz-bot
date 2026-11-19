"""Preview of the festival characters (fest_characters.js) for the owner's approval.

    python scripts/art/village/preview_fest_characters.py [--out DIR]

Writes into .local/fest-characters-preview/ (default): every figure as its own SVG, a large sheet (each figure ×8, mascot
frames side by side, next to the everyday resident it varies), and game-scale crops of the real village (village.svg) with the
figure standing where it would stand, day and night, shown ×3 for reading. Checks XML, no raster inside the figures and two
identical runs. Nothing is written into qw_farm/static: the game takes the figures only after approval.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import ROOT, STATIC, _chromium, _env_browsers, run  # noqa: E402

OUT = ROOT / ".local" / "fest-characters-preview"
WORLD_SCALE = 0.656          # village.svg CSS px per world px on a 390 px phone (measured in the game)
UNIT = 40 / 36               # resident and player figures: 1.11 CSS px per drawing unit

# where each figure is shown in the village (world px of the feet), and the resident it is a variant of
PLACES = {
    'resident-sonya-posidelki': ((1334, 1094), 'Кошка Соня'),
    'resident-hedgehog-new_year': ((797, 1012), 'Почтальон Ёж'),
    'mascot-fest_posid_snowman': ((1290, 1120), None),     # beside the player, as a follower
    'mascot-fest_ny_bullfinch': ((830, 1030), None),
    'guest-ded_moroz': ((1180, 960), None),          # the square by the town hall
    'guest-snegurochka': ((1220, 975), None),
    'guest-santa': ((1180, 960), None),
    'guest-krampus': ((1220, 975), None),
}
TITLES = {
    'resident-sonya-posidelki': 'Посиделки · Соня дремлет на крыльце в шарфе',
    'mascot-fest_posid_snowman': 'Посиделки · маскот «Снеговик в шарфе» (стоит / шаг)',
    'mascot-fest_ny_bullfinch': 'Новый год · маскот «Снегирь» (стоит / прыжок)',
    'resident-hedgehog-new_year': 'Новый год · Ёж разносит открытки',
    'guest-ded_moroz': 'Новый год · Дед Мороз',
    'guest-snegurochka': 'Новый год · Снегурочка',
    'guest-santa': 'Битва с Сантой · Санта',
    'guest-krampus': 'Битва с Сантой · Крампус',
}


def view_box(svg: str) -> list[float]:
    return [float(v) for v in ET.fromstring(svg).get('viewBox').split()]


def check(svgs: dict) -> None:
    for name, svg in svgs.items():
        root = ET.fromstring(svg)                       # well-formed XML
        if any(el.tag.endswith('image') for el in root.iter()) or 'data:image' in svg:
            raise SystemExit(f'{name}: raster inside a figure')


def main() -> None:
    out = Path(sys.argv[sys.argv.index('--out') + 1]) if '--out' in sys.argv else OUT
    out.mkdir(parents=True, exist_ok=True)
    svgs = run('fest_characters.js', {})
    again = run('fest_characters.js', {})
    if svgs != again:
        raise SystemExit('two runs differ')
    check(svgs)
    for name, svg in svgs.items():
        (out / f'{name}.svg').write_text(svg, encoding='utf-8')

    # the everyday residents, as the game shows them, for the side-by-side
    app = (STATIC / 'app.js').read_text(encoding='utf-8')
    import json, re
    m = re.search(r'const VILLAGE_RESIDENT_FIGURES=(\{.*?\});\n', app, re.S)
    figures = json.loads(m.group(1)) if m else {}

    def figure_html(svg: str, scale: float) -> str:
        x, y, w, h = view_box(svg)
        return f'<div style="width:{w * scale:.1f}px;height:{h * scale:.1f}px">{svg.replace("<svg ", "<svg width=\"100%\" height=\"100%\" ")}</div>'

    def frames(svg: str, cls: str) -> list[str]:
        """A mascot SVG with <g class=cls-stand|cls-hop>: one SVG per frame."""
        root_open = svg[:svg.index('>') + 1]
        groups = re.findall(r'<g class="[^"]+">.*?</g>(?=<g class=|</svg>)', svg, re.S)
        return [root_open + g + '</svg>' for g in groups] or [svg]

    rows, guests, winter = [], [], []
    winter_names = {'filinych': 'Филиныч', 'agata': 'Агата', 'hedgehog': 'Почтальон Ёж', 'mole': 'Механик Крот',
                    'kaya': 'Кошка Кая', 'sonya': 'Кошка Соня', 'igor': 'Суслик Игорь', 'zverushka': 'Неведома Зверушка',
                    'pukh': 'Медведь Пух', 'dasha': 'Лиса Даша', 'oleg': 'Петух Олег'}

    def dressed(base_svg: str, overlay: str) -> str:
        """The resident with the winter overlay laid on top, as the game would stack them."""
        inner = overlay[overlay.index('>') + 1:overlay.rindex('</svg>')]
        return base_svg[:base_svg.rindex('</svg>')] + inner + '</svg>'

    for name, svg in svgs.items():
        if name.startswith('winter-'):
            base = winter_names[name[len('winter-'):]]
            winter.append((base, dressed(figures[base][1], svg)))
            continue
        if name.startswith('guest-'):            # the New Year guests side by side, at the same scale, for heights
            guests.append(f'<figure>{figure_html(svg, 7)}<figcaption>{TITLES[name].split(" · ")[-1]}</figcaption></figure>')
            continue
        base = PLACES[name][1]
        cells = []
        if base and base in figures:
            cells.append(f'<figure>{figure_html(figures[base][1], 8)}<figcaption>сейчас: {base}</figcaption></figure>')
        for i, f in enumerate(frames(svg, '')):
            cells.append(f'<figure>{figure_html(f, 8)}<figcaption>{"новое" if not i else "кадр 2"}</figcaption></figure>')
        rows.append(f'<section><h2>{TITLES[name]}</h2><div class="row">{"".join(cells)}</div></section>')
    if winter:
        big = ''.join(f'<figure>{figure_html(svg, 5)}<figcaption>{base}</figcaption></figure>' for base, svg in winter)
        game = ''.join(f'<figure>{figure_html(svg, UNIT * 2)}</figure>' for base, svg in winter)
        rows.append(f'<section><h2>Новый год · жители в зимнем</h2><div class="row wrap">{big}</div>'
                    f'<h2>то же в игровом масштабе ×2</h2><div class="row wrap">{game}</div></section>')
    if guests:
        rows.append(f'<section><h2>Новый год · гости</h2><div class="row">{"".join(guests)}</div></section>')
    sheet = ('<html><head><meta charset="utf-8"><style>body{margin:0;padding:16px;background:#e8eedc;font:15px system-ui;color:#1b2319}'
             'h2{font-size:17px;margin:14px 0 6px}.row{display:flex;gap:28px;align-items:flex-end}.wrap{flex-wrap:wrap;gap:14px}figure{margin:0;text-align:center}'
             'figcaption{margin-top:4px}</style></head><body>' + ''.join(rows) + '</body></html>')
    (out / 'sheet.html').write_text(sheet, encoding='utf-8')

    village = (STATIC / 'village.svg').as_uri()
    crops = []
    for name, svg in svgs.items():
        if name not in PLACES:
            continue
        (fx, fy), _ = PLACES[name]
        x, y, w, h = view_box(svg)
        first = frames(svg, '')[0]
        for night in (False, True):
            cw, ch = 200, 160                       # crop in CSS px at game scale
            left = fx * WORLD_SCALE - cw / 2
            top = fy * WORLD_SCALE - ch * .62
            fig_w, fig_h = w * UNIT, h * UNIT
            fig_left = fx * WORLD_SCALE - left - (-x) * UNIT
            fig_top = fy * WORLD_SCALE - top - (-y) * UNIT
            tint = '<div style="position:absolute;inset:0;background:linear-gradient(180deg,#16215ac2,#223a6cb0 55%,#1b2f5cb8)"></div>' if night else ''
            crops.append(
                f'<figure><div style="position:relative;width:{cw * 3}px;height:{ch * 3}px;overflow:hidden">'
                f'<div style="position:absolute;left:0;top:0;width:{cw}px;height:{ch}px;transform:scale(3);transform-origin:0 0;overflow:hidden">'
                f'<img src="{village}" style="position:absolute;left:{-left:.1f}px;top:{-top:.1f}px;width:{2400 * WORLD_SCALE:.1f}px;height:{1800 * WORLD_SCALE:.1f}px">'
                f'{tint}<div style="position:absolute;left:{fig_left:.1f}px;top:{fig_top:.1f}px;width:{fig_w:.1f}px;height:{fig_h:.1f}px">'
                f'{first.replace("<svg ", "<svg width=\"100%\" height=\"100%\" ")}</div></div></div>'
                f'<figcaption>{TITLES[name]} · {"ночь" if night else "день"} · игровой масштаб ×3</figcaption></figure>')
    insitu = ('<html><head><meta charset="utf-8"><style>body{margin:0;padding:16px;background:#e8eedc;font:14px system-ui;color:#1b2319}'
              '.grid{display:grid;grid-template-columns:repeat(2,auto);gap:16px}figure{margin:0}</style></head><body><div class="grid">'
              + ''.join(crops) + '</div></body></html>')
    (out / 'in-village.html').write_text(insitu, encoding='utf-8')

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        _env_browsers(); browser = pw.chromium.launch(executable_path=_chromium())
        for page_name in ('sheet', 'in-village'):
            page = browser.new_page(viewport={'width': 1300, 'height': 900})
            page.goto((out / f'{page_name}.html').as_uri())
            page.wait_for_timeout(800)
            page.screenshot(path=str(out / f'{page_name}.png'), full_page=True)
            page.close()
        browser.close()
    print(f'ok: {len(svgs)} figures -> {out}')


if __name__ == '__main__':
    main()
