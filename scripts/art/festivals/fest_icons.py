"""Icons of the festival items filled 2026-11-19 (qw_farm/festivals.py CONTENT): symbols for qw_farm/static/icons.svg.

    python scripts/art/festivals/fest_icons.py april_fools            # -> .local/fest-icons-preview/<fest>/ (sheet for the owner)
    python scripts/art/festivals/fest_icons.py april_fools --install  # also add/refresh the symbols in icons.svg and drop their
                                                                      # ICON_FALLBACK lines in qw_farm/static/festivals.js

Flat 48×48 symbols without outlines, like the Посиделки, Новый год and Масленица ones; the farm palette (muted reds, mustard,
sage, cream). Values stay far apart (a dark detail on a light body and back) so every icon reads at 24 px for weak eyesight.
One festival per run, in calendar order (FARM_FESTIVALS_DESIGN 9.8, 2026-11-19 note).
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
FEST_JS = ROOT / 'qw_farm' / 'static' / 'festivals.js'
OUT = ROOT / '.local' / 'fest-icons-preview'

RED, RED_SHADE, MUSTARD, MUSTARD_SHADE, SAGE, SAGE_DARK = '#d9553f', '#b8432f', '#e8c25a', '#c9a23e', '#8fae86', '#5f7f58'
CREAM, CREAM_SHADE, BLUE, BLUE_DARK, LILAC, PINK = '#f4ede0', '#e2d7bd', '#7fa3c4', '#4f7396', '#c3b0de', '#e7a8b5'
WOOD, WOOD_LIGHT, WOOD_DARK, INK, STEEL, STEEL_LIGHT = '#b48f66', '#c9a57a', '#7a5a3e', '#3f3428', '#9aa1a8', '#c9ced4'
COPPER, COPPER_DARK = '#c98a3e', '#8f5a24'
GLASS, GLASS_SHADE, STRAW, STRAW_SHADE, BURLAP = '#d6e8ee', '#b5d0da', '#e3c27a', '#c9a24f', '#d8bb84'


def star(x, y, r, fill):
    """A four-point sparkle centred at (x, y)."""
    k = r * .28
    return (f'<path d="M{x} {y - r}L{x + k} {y - k}L{x + r} {y}L{x + k} {y + k}L{x} {y + r}L{x - k} {y + k}L{x - r} {y}L{x - k} {y - k}Z" '
            f'fill="{fill}"/>')


def party_hat(x, y, h, w, tilt, base=RED, stripe=MUSTARD, pom=CREAM):
    """A party cone with two stripes and a pompom; (x, y) is the middle of its brim, ``tilt`` degrees."""
    return (f'<g transform="translate({x} {y}) rotate({tilt})">'
            f'<path d="M{-w / 2} 0L0 {-h}L{w / 2} 0Z" fill="{base}"/>'
            f'<path d="M{-w * .36} {-h * .28}L{w * .36} {-h * .28}L{w * .27} {-h * .46}L{-w * .27} {-h * .46}Z" fill="{stripe}"/>'
            f'<path d="M{-w * .19} {-h * .62}L{w * .19} {-h * .62}L{w * .11} {-h * .78}L{-w * .11} {-h * .78}Z" fill="{stripe}"/>'
            f'<circle cx="0" cy="{-h}" r="{w * .2:.2f}" fill="{pom}"/></g>')


FESTIVALS = {
    # «День смеха» (9.2 item 4): Даша's «Честная лавка» of jokes, the mixed-up signs, the scarecrow in Филиныч's glasses
    'april_fools': {
        # Пустая банка из-под тишины: a clear jar with a cork, nothing inside; on its label a speech bubble struck out
        'fest_fool_jar': (
            f'<rect x="14" y="4" width="20" height="7" rx="2" fill="{WOOD}"/><rect x="14" y="4" width="20" height="2.6" rx="1.3" fill="{WOOD_LIGHT}"/>'
            f'<rect x="16" y="10" width="16" height="5" fill="{GLASS_SHADE}"/>'
            f'<path d="M17 14h14q6 0 6 6v19q0 5-5 5H16q-5 0-5-5V20q0-6 6-6Z" fill="{GLASS}"/>'
            f'<path d="M30 14h1q6 0 6 6v19q0 5-5 5h-2Z" fill="{GLASS_SHADE}"/>'
            f'<path d="M15 19v18" stroke="#ffffff" stroke-width="2.4" stroke-linecap="round"/>'
            f'<rect x="17" y="23" width="15" height="13" rx="2" fill="{CREAM}"/>'
            f'<path d="M20.4 27.2q0-2.6 4.1-2.6t4.1 2.6-4.1 2.6l-2.6 2.4.4-2.7q-1.9-.6-1.9-2.3Z" fill="{LILAC}"/>'
            f'<path d="M19 34.4L30 24.6" stroke="{RED}" stroke-width="2.2" stroke-linecap="round"/>'
        ),
        # Носок-невидимка: only a dashed outline of a sock and a few sparkles where it should be
        'fest_fool_sock': (
            f'<path d="M15 4H28V25L36.6 31.2Q41.6 35 38.8 40Q35.8 44.6 30.4 41.4L18.6 33.6Q15 31.2 15 27Z" fill="#ffffff" opacity=".45"/>'
            f'<path d="M15 4H28V25L36.6 31.2Q41.6 35 38.8 40Q35.8 44.6 30.4 41.4L18.6 33.6Q15 31.2 15 27Z" fill="none" stroke="{BLUE_DARK}" '
            f'stroke-width="2.2" stroke-dasharray="3.4 2.6" stroke-linejoin="round"/>'
            f'<path d="M15.6 10.4H27.4" stroke="{BLUE}" stroke-width="1.8" stroke-dasharray="2.6 2.2"/>'
            + star(39, 10, 5, MUSTARD) + star(8, 33, 3.6, MUSTARD) + star(33, 20, 2.6, MUSTARD_SHADE)
        ),
        # Подкова наоборот: the horseshoe hangs open side down, so the luck drips out of it
        'fest_fool_horseshoe': (
            f'<path d="M12.5 33V19.5a11.5 11.5 0 0 1 23 0V33" fill="none" stroke="{STEEL}" stroke-width="7.4"/>'
            f'<path d="M10.4 30V19.5a13.6 13.6 0 0 1 9-12.8" fill="none" stroke="{STEEL_LIGHT}" stroke-width="2"/>'
            f'<rect x="8.6" y="31" width="7.8" height="3.6" rx="1" fill="#7f868d"/><rect x="31.6" y="31" width="7.8" height="3.6" rx="1" fill="#7f868d"/>'
            f'<circle cx="12.5" cy="24" r="1.2" fill="{INK}"/><circle cx="14.6" cy="15" r="1.2" fill="{INK}"/><circle cx="35.5" cy="24" r="1.2" fill="{INK}"/>'
            f'<circle cx="33.4" cy="15" r="1.2" fill="{INK}"/><circle cx="24" cy="10.6" r="1.2" fill="{INK}"/>'
            f'<path d="M12.5 37.4q2.2 3 0 4.8-2.2-1.8 0-4.8Z" fill="{MUSTARD}"/><path d="M35.5 38.4q2.2 3 0 4.8-2.2-1.8 0-4.8Z" fill="{MUSTARD}"/>'
            + star(17.5, 43.4, 2.6, MUSTARD_SHADE) + star(30.6, 45, 2.2, MUSTARD_SHADE)
        ),
        # Торт-обманка: a handsome cake, but the cut shows a yellow kitchen sponge with its green scrub layer
        'fest_fool_cake': (
            f'<ellipse cx="24" cy="40" rx="21" ry="5" fill="{CREAM_SHADE}"/>'
            f'<path d="M7 20h34v17q0 4-17 4T7 37Z" fill="{PINK}"/>'
            f'<path d="M29 20h12v17q0 3.4-12 3.9Z" fill="#d48e9b"/>'
            f'<ellipse cx="24" cy="20" rx="17" ry="5" fill="{CREAM}"/>'
            f'<path d="M7 20q2 5 4 0 2 6 4.4 0 2 5 4 0M33 21q2 5 4-.4 2 4.6 4-.6" fill="none" stroke="{CREAM}" stroke-width="2.6" stroke-linecap="round"/>'
            f'<path d="M20 22.4L30 24.4V40.4L20 39Z" fill="#ead36a"/>'
            f'<path d="M20 35.6L30 36.8V40.4L20 39Z" fill="{SAGE_DARK}"/>'
            f'<circle cx="23" cy="27" r="1.2" fill="#c9a83e"/><circle cx="27" cy="29.6" r="1" fill="#c9a83e"/><circle cx="24.4" cy="32.4" r="1.3" fill="#c9a83e"/>'
            f'<circle cx="28" cy="26" r=".9" fill="#c9a83e"/>'
            f'<circle cx="15" cy="15" r="3.6" fill="{RED}"/><path d="M15 11.6q1-4 4-5" fill="none" stroke="{SAGE_DARK}" stroke-width="1.3" stroke-linecap="round"/>'
            f'<circle cx="13.8" cy="13.8" r="1" fill="#ffffff" opacity=".7"/>'
        ),
        # Кривое зеркало на площади: a wavy gilded frame on legs, the reflection stretched into a long funny face
        'fest_fool_mirror': (
            f'<path d="M15 38l-4 8M33 38l4 8" stroke="{WOOD_DARK}" stroke-width="2.6" stroke-linecap="round"/>'
            f'<path d="M24 2q8 0 11 6t-1 10q5 5 1 11t-11 10q-8 0-11-6t1-10q-5-5-1-11T24 2Z" fill="{MUSTARD}"/>'
            f'<path d="M24 5q6 0 8.4 4.8T31 17.6q4 4.4 1 9.4T24 36q-6 0-8.4-4.8T17 23.4q-4-4.4-1-9.4T24 5Z" fill="{GLASS}"/>'
            f'<path d="M24 5q6 0 8.4 4.8T31 17.6q4 4.4 1 9.4T24 36Z" fill="{GLASS_SHADE}"/>'
            f'<ellipse cx="24" cy="21" rx="4.4" ry="10" fill="{PINK}"/>'
            f'<circle cx="21.6" cy="16" r="1.1" fill="{INK}"/><circle cx="26.4" cy="17.4" r="1.1" fill="{INK}"/>'
            f'<path d="M21.4 25q1.4 2.2 2.6 0t2.6 0" fill="none" stroke="{INK}" stroke-width="1.1" stroke-linecap="round"/>'
            f'<path d="M18 9q-2 3-1.6 6" stroke="#ffffff" stroke-width="1.6" stroke-linecap="round" fill="none"/>'
        ),
        # Полосатые носки на забор: two striped socks pegged on the fence rail
        'fest_fool_stripes': (
            f'<rect x="4" y="2" width="6" height="44" fill="{WOOD}"/><rect x="38" y="2" width="6" height="44" fill="{WOOD}"/>'
            f'<path d="M4 2l3-2 3 2M38 2l3-2 3 2" fill="{WOOD}"/>'
            f'<rect x="2" y="9" width="44" height="4" rx="1" fill="{WOOD_DARK}"/>'
            f'<path d="M12 11h9v17l6 4.4q3 2.4 1 5.4-2 2.8-5.4.8l-8.4-5.4Q12 31.6 12 29Z" fill="{RED}"/>'
            f'<path d="M12 15h9v3h-9ZM12 21h9v3h-9ZM12 27h9v2.8h-9Z" fill="{CREAM}"/>'
            f'<path d="M25 11h9v19l5 4q2.6 2.4.6 5.2-2 2.6-5.2.6l-7.2-5.2Q25 33.4 25 31Z" fill="{BLUE}"/>'
            f'<path d="M25 15h9v3h-9ZM25 21h9v3h-9ZM25 27h9v3h-9Z" fill="{MUSTARD}"/>'
            f'<rect x="14.6" y="7.6" width="3.6" height="6.4" rx="1" fill="{SAGE_DARK}"/><rect x="27.6" y="7.6" width="3.6" height="6.4" rx="1" fill="{SAGE_DARK}"/>'
        ),
        # Заморская свистулька-пищалка: a party blower, unrolled with a squeak
        'fest_fool_whistle': (
            f'<rect x="3" y="31" width="10" height="6" rx="2" fill="{SAGE_DARK}"/>'
            f'<path d="M12 34L33 17" stroke="{MUSTARD}" stroke-width="6.4"/>'
            f'<path d="M12 34L33 17" stroke="{RED}" stroke-width="6.4" stroke-dasharray="3.2 3.2"/>'
            f'<path d="M33 17q6-5 9-1t-2 8-5-2 2.6-3" fill="none" stroke="{MUSTARD}" stroke-width="4" stroke-linecap="round"/>'
            f'<path d="M19 8q3 1.6 3 4.8M23 4q5.4 2.6 5.4 8" fill="none" stroke="{BLUE_DARK}" stroke-width="2" stroke-linecap="round"/>'
            f'<path d="M37 33q3 1 4 4M40 30q5 2 6 7" fill="none" stroke="{BLUE_DARK}" stroke-width="2" stroke-linecap="round"/>'
            + star(8, 20, 3.4, LILAC)
        ),
        # Колпак на флюгере: the rooster of the weathervane in a party cone
        'fest_fool_cap': (
            f'<path d="M24 26v20" stroke="{INK}" stroke-width="2.4"/>'
            f'<path d="M6 30h34" stroke="{INK}" stroke-width="2"/><path d="M40 30l-5-3.4v6.8Z" fill="{INK}"/><path d="M6 30l4-3v6Z" fill="{INK}"/>'
            f'<path d="M14 24q-3-6 1-11 2 4 5 5l2-7q4-1 6 2l4 1-3 2q2 6-2 9-5 3-13-1Z" fill="{COPPER}"/>'
            f'<path d="M10 22q-5-4-4-10 3 4 6 5-3-5 0-9 1 5 4 7Z" fill="{COPPER}"/>'
            f'<path d="M15 21q4 3 10 1" fill="none" stroke="{COPPER_DARK}" stroke-width="1.4" stroke-linecap="round"/>'
            f'<path d="M26 11q1-3 3-2t0 3Z" fill="{RED}"/><circle cx="28.4" cy="13.6" r="1" fill="{CREAM}"/>'
            + party_hat(25, 11, 11, 8, 14)
        ),
        # Табличка «Почта» на мельнице: the post office's envelope sign nailed to the mill
        'fest_fool_signs': (
            f'<path d="M14 46l3-26h14l3 26Z" fill="{CREAM_SHADE}"/><path d="M24 46V20h7l3 26Z" fill="#cdbf9f"/>'
            f'<path d="M12 21l12-9 12 9Z" fill="#c97a6a"/>'
            f'<path d="M24 13L9 2M24 13l15-11M24 13L8 25M24 13l16 12" stroke="{WOOD_DARK}" stroke-width="2.6" stroke-linecap="round"/>'
            f'<circle cx="24" cy="13" r="2.4" fill="{INK}"/>'
            f'<rect x="20" y="40" width="8" height="6" fill="{WOOD_DARK}"/>'
            f'<g transform="rotate(-9 24 31)"><rect x="13.6" y="25" width="20.8" height="13" rx="1.4" fill="{WOOD}"/>'
            f'<rect x="17" y="27.4" width="14" height="8.4" fill="#ffffff"/><path d="M17 27.4l7 5 7-5" fill="none" stroke="{BLUE_DARK}" stroke-width="1.5"/>'
            f'<circle cx="15.2" cy="31.4" r=".9" fill="{INK}"/><circle cx="32.8" cy="31.4" r=".9" fill="{INK}"/></g>'
        ),
        # Гуси в колпаках: a goose head in a tilted party cone
        'fest_fool_geese': (
            f'<g transform="translate(4 9.4) scale(.8)">'
            f'<path d="M14 46q-3-12 4-18 3-3 3-9v-6q0-8 8-8 7 0 8 7 1 5-4 7-3 1-3 6v6q0 8 6 15Z" fill="#f6f7fa"/>'
            f'<path d="M30 21q-3 1-3 6v6q0 8 6 15H26q-4-8-4-16v-6q0-4 3-5Z" fill="#dfe4e8"/>'
            f'<path d="M36 10q6-1 9 2-3 3-9 2Z" fill="#e8955a"/><path d="M36 13l8 .6q-3 2.4-8 1.4Z" fill="#c97440"/>'
            f'<circle cx="31" cy="10" r="1.8" fill="{INK}"/><circle cx="31.5" cy="9.4" r=".6" fill="#ffffff"/></g>'
            + party_hat(27.4, 14, 13, 11, -14, base=RED, stripe=MUSTARD, pom=CREAM)
        ),
        # Пугало-шутник (the keepsake of the day): the scarecrow in Филиныч's round glasses and a bow tie
        'fest_fool_scarecrow': (
            f'<path d="M24 34v12" stroke="{WOOD_DARK}" stroke-width="3"/>'
            f'<path d="M4 31h40" stroke="{WOOD_DARK}" stroke-width="2.6"/>'
            f'<path d="M4 31l-2 5M4 31l1 5M44 31l2 5M44 31l-1 5" stroke="{STRAW_SHADE}" stroke-width="1.4"/>'
            f'<path d="M13 15q0-10 11-10t11 10v8q0 9-11 9T13 23Z" fill="{BURLAP}"/>'
            f'<path d="M24 5q11 0 11 10v8q0 9-11 9Z" fill="#c9a874"/>'
            f'<path d="M12 22q-3 3-5 1M36 22q3 3 5 1M15 28q-2 4-4 4M33 28q2 4 4 4" stroke="{STRAW}" stroke-width="1.6" stroke-linecap="round" fill="none"/>'
            f'<path d="M7 11q17-9 34 0l-3 3q-14-6-28 0Z" fill="{STRAW_SHADE}"/><path d="M14 9q10-12 20 0Z" fill="{STRAW}"/>'
            f'<circle cx="18.6" cy="17.4" r="4.4" fill="#ffffff" opacity=".55"/><circle cx="29.4" cy="17.4" r="4.4" fill="#ffffff" opacity=".55"/>'
            f'<circle cx="18.6" cy="17.4" r="4.4" fill="none" stroke="{INK}" stroke-width="1.8"/>'
            f'<circle cx="29.4" cy="17.4" r="4.4" fill="none" stroke="{INK}" stroke-width="1.8"/><path d="M23 17q1-1.4 2 0" stroke="{INK}" stroke-width="1.6" fill="none"/>'
            f'<circle cx="18.6" cy="17.8" r="1.3" fill="{INK}"/><circle cx="29.4" cy="17.8" r="1.3" fill="{INK}"/>'
            f'<path d="M18 25q6 4 12 0" fill="none" stroke="{WOOD_DARK}" stroke-width="1.4" stroke-linecap="round"/>'
            f'<path d="M20 25.6l.4 1.6M24 27l0 1.6M28 25.6l-.4 1.6" stroke="{WOOD_DARK}" stroke-width="1"/>'
            f'<path d="M24 34l-7-3.4v7ZM24 34l7-3.4v7Z" fill="{RED}"/><circle cx="24" cy="34" r="1.8" fill="{RED_SHADE}"/>'
        ),
    },
}

NAMES = {
    'fest_fool_jar': 'Пустая банка из-под тишины', 'fest_fool_sock': 'Носок-невидимка', 'fest_fool_horseshoe': 'Подкова наоборот',
    'fest_fool_cake': 'Торт-обманка', 'fest_fool_mirror': 'Кривое зеркало на площади', 'fest_fool_stripes': 'Полосатые носки на забор',
    'fest_fool_whistle': 'Свистулька-пищалка', 'fest_fool_cap': 'Колпак на флюгере', 'fest_fool_signs': 'Табличка «Почта» на мельнице',
    'fest_fool_geese': 'Гуси в колпаках', 'fest_fool_scarecrow': 'Пугало-шутник',
}
NEIGHBOURS = ['fest_mas_effigy', 'fest_flw_pots', 'fest_posid_lantern']


def symbols(fest: str) -> dict:
    return {sid: f'<symbol id="{sid}" viewBox="0 0 48 48">{body}</symbol>' for sid, body in FESTIVALS[fest].items()}


def check(syms: dict) -> None:
    for sid, sym in syms.items():
        ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{sym}</svg>')
        assert not re.search(r'<image|data:image|<filter| style=|<text', sym), sid


def install(syms: dict) -> str:
    """Refresh existing symbols in place; new ones go after the last festival symbol, one per line."""
    src = ICONS.read_text(encoding='utf-8')
    for sid, sym in syms.items():
        pat = re.compile(r'<symbol id="%s".*?</symbol>' % re.escape(sid), re.S)
        if pat.search(src):
            src = pat.sub(lambda m: sym, src, count=1)
        else:
            last = [m for m in re.finditer(r'<symbol id="fest_[^"]+".*?</symbol>', src, re.S)][-1]
            src = src[:last.end()] + '\n' + sym + src[last.end():]
    ET.fromstring(src)
    ICONS.write_text(src, encoding='utf-8', newline='')
    js = FEST_JS.read_text(encoding='utf-8')
    for sid in syms:
        js = re.sub(r"%s:'fest_posid_[a-z_]+'," % re.escape(sid), '', js)
    # a festival's fallbacks sit on a line of their own: drop the line (and its heading) once all of them are gone
    head, sep, tail = js.partition('export const ICON_FALLBACK={')
    body, end, rest = tail.partition('};')
    body = re.sub(r'\n[ \t]+(?=\n)', '', body)
    body = re.sub(r'\n[ \t]*//[^\n]*(?=\n[ \t]*//|\n?$)', '', body)   # a festival's heading with nothing under it
    js = head + sep + body + end + rest
    FEST_JS.write_text(js, encoding='utf-8', newline='')
    return hashlib.sha256(src.encode()).hexdigest()


def sheet(syms: dict, title: str) -> str:
    live = ICONS.read_text(encoding='utf-8')
    for sid in syms:
        live = re.sub(r'<symbol id="%s".*?</symbol>' % re.escape(sid), '', live, flags=re.S)
    sprite = live.replace('</svg>', ''.join(syms.values()) + '</svg>')
    use = lambda sid, px: f'<svg width="{px}" height="{px}" viewBox="0 0 48 48"><use href="#{sid}"/></svg>'  # noqa: E731
    def row(bg, fg, caption):
        cells = ''.join(f'<div class=c><div class=i>{use(s, 96)}{use(s, 48)}{use(s, 24)}</div><b>{NAMES.get(s, s)}</b></div>'
                        for s in [*syms, *NEIGHBOURS])
        return f'<section style="background:{bg};color:{fg}"><h2>{caption}</h2><div class=r>{cells}</div></section>'
    css = ('body{margin:0;font:14px system-ui,sans-serif}section{padding:14px 18px}h2{margin:0 0 10px;font-size:15px}'
           '.r{display:flex;gap:18px;flex-wrap:wrap}.c{width:170px;display:grid;gap:6px}.i{display:flex;align-items:end;gap:8px}'
           'b{font-size:12px;font-weight:700}')
    return (f'<meta charset=utf-8><style>{css}</style><div style="display:none">{sprite}</div>'
            + row('#fffaf0', '#28331f', f'{title}: день (справа — соседи из других праздников для сравнения)')
            + row('#26313c', '#eef2f4', 'Ночь')
            + row('#ffffff', '#10231a', 'Контрастный режим'))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('fest', choices=sorted(FESTIVALS))
    ap.add_argument('--install', action='store_true', help='write the symbols into icons.svg (after the owner approved the sheet)')
    a = ap.parse_args()
    syms = symbols(a.fest)
    check(syms)
    out = OUT / a.fest
    out.mkdir(parents=True, exist_ok=True)
    html = sheet(syms, a.fest)
    (out / 'sheet.html').write_text(html, encoding='utf-8')
    harness.screenshot(html, out / 'sheet.png', (1560, 1240))
    print('preview', out / 'sheet.png')
    if a.install:
        print('installed icons.svg', install(syms))


if __name__ == '__main__':
    main()
