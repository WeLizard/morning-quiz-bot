"""Icons of the «Битва с Сантой» rewards (docs/tasks/FARM_SANTA_BATTLE.md §6): symbols for qw_farm/static/icons.svg.

    python scripts/art/village_games/santa_icons.py            # -> .local/santa-icons-preview/ (sheet for the owner)
    python scripts/art/village_games/santa_icons.py --icons    # also add/refresh the three symbols in icons.svg

The festival icons are flat 48×48 symbols without outlines, like fest_ny_sleigh and fest_posid_lantern; the colours are
the battle art's (new_year_guests.js: Санта's coat and sack, Крампус's fur, horns and gold bell). Values stay far apart
(dark strap and clapper on gold, white trims on red, cream horns on brown) so the icons read at 24 px for weak eyesight.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / 'village'))
import harness  # noqa: E402

ICONS = ROOT / 'qw_farm' / 'static' / 'icons.svg'
OUT = ROOT / '.local' / 'santa-icons-preview'
GOLD, GOLD_SHADE, GOLD_LIGHT, GOLD_RIM = '#e2b04a', '#c4912f', '#f6dc8c', '#a87a24'
FUR, FUR_DARK, BELLY, HORN, HORN_TIP = '#5d4337', '#433026', '#87644f', '#ddcfae', '#b49f74'
RED, RED_SHADE, WHITE, SACK, SACK_SHADE, GREEN, STEEL = '#d23a32', '#b52f29', '#f6f7fa', '#a9875b', '#8c6d47', '#3f7a54', '#a3a9b1'

SYMBOLS = {
    # Колокольчик Крампуса (battle 1): his gold bell on a dark leather strap with two little horns, a dark clapper
    'fest_ny_krampus_bell': (
        '<circle cx="24" cy="27" r="18" fill="#ffe3a0" opacity=".3"/>'
        f'<path d="M15 8q-6-1-7-7M33 8q6-1 7-7" fill="none" stroke="{HORN}" stroke-width="2.8" stroke-linecap="round"/>'
        f'<path d="M8.4 2.6q-.4-1.2 0-2M39.6 2.6q.4-1.2 0-2" fill="none" stroke="{HORN_TIP}" stroke-width="2.4" stroke-linecap="round"/>'
        f'<rect x="14" y="5" width="20" height="6" rx="2.4" fill="{FUR_DARK}"/>'
        f'<circle cx="18" cy="8" r="1.1" fill="{STEEL}"/><circle cx="24" cy="8" r="1.1" fill="{STEEL}"/><circle cx="30" cy="8" r="1.1" fill="{STEEL}"/>'
        f'<ellipse cx="24" cy="13.2" rx="1.6" ry="2.2" fill="none" stroke="{STEEL}" stroke-width="1.3"/>'
        f'<path d="M24 15c-7 0-10 6-10 13v6l-3 4h26l-3-4v-6c0-7-3-13-10-13Z" fill="{GOLD}"/>'
        f'<path d="M24 15c7 0 10 6 10 13v6l3 4H24Z" fill="{GOLD_SHADE}"/>'
        f'<path d="M18.4 21q-1.6 4-1.4 11" fill="none" stroke="{GOLD_LIGHT}" stroke-width="2.2" stroke-linecap="round"/>'
        f'<rect x="10" y="37" width="28" height="3.6" rx="1.8" fill="{GOLD_RIM}"/>'
        f'<circle cx="24" cy="43.4" r="3.2" fill="{FUR_DARK}"/>'
    ),
    # Мешок Санты (battle 2): the battle's sack, a gold rope at the neck, gifts and a candy cane peeking out
    'fest_ny_santa_sack': (
        f'<path d="M33.5 19V9.5q0-3.2 3-3.2t3 3.2" fill="none" stroke="{WHITE}" stroke-width="2.8" stroke-linecap="round"/>'
        f'<path d="M33.5 19V9.5q0-3.2 3-3.2t3 3.2" fill="none" stroke="{RED}" stroke-width="2.8" stroke-dasharray="2 2.2"/>'
        f'<rect x="12" y="8" width="11" height="12" rx="1.2" fill="{RED}"/><path d="M17.5 8v12M12 13.5h11" stroke="{WHITE}" stroke-width="2"/>'
        f'<rect x="22" y="4.5" width="10" height="15" rx="1.2" fill="{GREEN}"/><path d="M27 4.5v15" stroke="#e7c56c" stroke-width="2"/>'
        f'<path d="M23.5 4.5q3.5-4.4 3.5 0 0-4.4 3.5 0" fill="none" stroke="#e7c56c" stroke-width="1.6"/>'
        f'<path d="M14 21q-6 8-5 15.5Q10 44 24 44t15-7.5Q40 29 34 21Z" fill="{SACK}"/>'
        f'<path d="M31 21q5 8 5 15.5 0 5.6-9 7.3Q38.6 42.6 39 36.5 40 29 34 21Z" fill="{SACK_SHADE}"/>'
        f'<path d="M12.6 34.6h6.4v5.6h-6.4Z" fill="#c9a878"/><path d="M13.4 35.4h4.8v4M13.4 39.4" fill="none" stroke="{SACK_SHADE}" stroke-width=".9" stroke-dasharray="1.2 1"/>'
        f'<path d="M13 20q11 3.6 22 0l-1.6 3.4q-9.4 2.6-18.8 0Z" fill="{SACK_SHADE}"/>'
        f'<path d="M14.6 21.6q9.4 2.8 18.8 0" fill="none" stroke="#e7c56c" stroke-width="2" stroke-linecap="round"/>'
        f'<path d="M25 23.4q-2 4-4.6 6M25 23.4q2.4 3.6 5.4 5" fill="none" stroke="#e7c56c" stroke-width="1.8" stroke-linecap="round"/>'
    ),
    # Санта и Крампус в гостях (battle 3): their two mugs at the fir — Санта's red one in his hat, Крампус's brown one with horns
    'fest_ny_santa_visit': (
        '<ellipse cx="24" cy="42.6" rx="20" ry="2.6" fill="#41623530"/>'
        f'<path d="M24 3l7 12H17Z" fill="#4f8a5b"/><path d="M24 9l10 15H14Z" fill="#4f8a5b"/><path d="M24 9l-10 15h10Z" fill="#6aa676"/>'
        '<path d="M24 1.2l1.1 2.3 2.5.3-1.8 1.7.5 2.5L24 6.8l-2.3 1.2.5-2.5-1.8-1.7 2.5-.3Z" fill="#e7c56c"/>'
        f'<path d="M5.6 32.6q-4.6 0-4.6 4.2t4.6 4.2" fill="none" stroke="{RED_SHADE}" stroke-width="2.4"/>'
        f'<rect x="5" y="27" width="16" height="15" rx="3" fill="{RED}"/><rect x="5" y="31" width="16" height="3" fill="{WHITE}"/>'
        f'<path d="M5 28q1.6-10 10.4-11.6 6.4-.6 8.6 5.4l-3 6.2Z" fill="{RED}"/><path d="M15.4 16.4q6.4-.6 8.6 5.4l-2.8 1.4q-1.8-4.4-5.8-5.4Z" fill="{RED_SHADE}"/>'
        f'<circle cx="24" cy="22.4" r="2.6" fill="{WHITE}"/><rect x="4" y="26" width="18" height="3.8" rx="1.9" fill="{WHITE}"/>'
        f'<path d="M42.4 32.6q4.6 0 4.6 4.2t-4.6 4.2" fill="none" stroke="{FUR_DARK}" stroke-width="2.4"/>'
        f'<rect x="27" y="27" width="16" height="15" rx="3" fill="{FUR}"/><rect x="27" y="35.6" width="16" height="2.6" fill="{BELLY}"/>'
        '<ellipse cx="35" cy="27.4" rx="7.4" ry="1.9" fill="#b27b4e"/>'
        f'<path d="M29 27q-4-6 0-11.6M41 27q4-6 0-11.6" fill="none" stroke="{HORN}" stroke-width="2.8" stroke-linecap="round"/>'
        '<circle cx="32" cy="31.4" r="1.4" fill="#f2c94c"/><circle cx="38" cy="31.4" r="1.4" fill="#f2c94c"/>'
        '<path d="M35 24.4q-1.6-2 0-4.2t0-4.2" fill="none" stroke="#ffffff" stroke-width="1.4" stroke-linecap="round" opacity=".9"/>'
    ),
}


def symbols() -> dict:
    return {sid: f'<symbol id="{sid}" viewBox="0 0 48 48">{body}</symbol>' for sid, body in SYMBOLS.items()}


def check(syms: dict) -> None:
    for sid, sym in syms.items():
        ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{sym}</svg>')
        assert not re.search(r'<image|data:image|<filter| style=|<text', sym), sid


def install(syms: dict) -> str:
    src = ICONS.read_text(encoding='utf-8')
    for sid, sym in syms.items():
        pat = re.compile(r'<symbol id="%s".*?</symbol>' % re.escape(sid), re.S)
        if pat.search(src):
            src = pat.sub(lambda m: sym, src, count=1)
        else:   # after the New Year block, before the next festival's symbols
            i = src.index('<symbol id="fest_mas_samovar"')
            src = src[:i] + sym + '\n' + src[i:]
    ET.fromstring(src)
    ICONS.write_text(src, encoding='utf-8', newline='')
    return hashlib.sha256(src.encode()).hexdigest()


NEIGHBOURS = ['fest_ny_sleigh', 'fest_ny_ball', 'fest_ny_bullfinch', 'fest_posid_lantern']
NAMES = {'fest_ny_krampus_bell': 'Колокольчик Крампуса', 'fest_ny_santa_sack': 'Мешок Санты', 'fest_ny_santa_visit': 'Санта и Крампус в гостях'}


def sheet(syms: dict) -> str:
    live = ICONS.read_text(encoding='utf-8')
    for sid in syms:
        live = re.sub(r'<symbol id="%s".*?</symbol>' % re.escape(sid), '', live, flags=re.S)
    sprite = live.replace('</defs>', ''.join(syms.values()) + '</defs>', 1) if '</defs>' in live else live.replace('</svg>', ''.join(syms.values()) + '</svg>')
    use = lambda sid, px: f'<svg width="{px}" height="{px}" viewBox="0 0 48 48"><use href="#{sid}"/></svg>'  # noqa: E731
    def row(bg, fg, title):
        cells = ''.join(f'<div class=c><div class=i>{use(s, 96)}{use(s, 48)}{use(s, 24)}</div><b>{NAMES.get(s, s)}</b></div>' for s in [*syms, *NEIGHBOURS])
        return f'<section style="background:{bg};color:{fg}"><h2>{title}</h2><div class=r>{cells}</div></section>'
    css = ('body{margin:0;font:14px system-ui,sans-serif}section{padding:14px 18px}h2{margin:0 0 10px;font-size:15px}'
           '.r{display:flex;gap:18px;flex-wrap:wrap}.c{width:150px;display:grid;gap:6px}.i{display:flex;align-items:end;gap:8px}'
           'b{font-size:12px;font-weight:700}')
    hidden = f'<div style="display:none">{sprite}</div>'
    return (f'<meta charset=utf-8><style>{css}</style>{hidden}'
            + row('#fffaf0', '#28331f', 'День: карточка праздника (новые три — первые; справа соседи по празднику для сравнения)')
            + row('#26313c', '#eef2f4', 'Ночь')
            + row('#ffffff', '#10231a', 'Контрастный режим'))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--icons', action='store_true', help='add/refresh the symbols in qw_farm/static/icons.svg (after the owner approved)')
    a = ap.parse_args()
    syms = symbols()
    check(syms)
    OUT.mkdir(parents=True, exist_ok=True)
    html = sheet(syms)
    (OUT / 'sheet.html').write_text(html, encoding='utf-8')
    harness.screenshot(html, OUT / 'sheet.png', (1340, 640))
    for sid, sym in syms.items():
        (OUT / f'{sid}.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><defs>{sym}</defs><use href="#{sid}"/></svg>', encoding='utf-8')
    print('preview', OUT / 'sheet.png')
    if a.icons:
        print('installed icons.svg', install(syms))


if __name__ == '__main__':
    main()
