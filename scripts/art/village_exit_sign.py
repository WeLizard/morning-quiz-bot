"""Regenerate the editable SVG village exit gate.

The historic village background is one embedded WebP and is kept byte-for-byte.
The old, baked-in little sign is covered by hand-drawn SVG ground shapes; the
replacement gate, lettering and road arrow are SVG too. No second raster image
or image-processing dependency is used.

Run ``python scripts/art/village_exit_sign.py``. Repeated runs are identical.
Requires fontTools and matplotlib (for its bundled DejaVu Sans Bold font).
"""
import argparse
import importlib.util
import os
import re
import sys

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SVG = os.path.join(ROOT, 'qw_farm', 'static', 'village.svg')
EXIT_START, EXIT_END = '<!-- exit-gate:start -->', '<!-- exit-gate:end -->'

L = (1158.0, 1522.0)                              # left post foot; the gate runs along the iso axis (1, -0.5)
SPAN = 118.0                                      # right post foot = L + SPAN * (1, -0.5)


def P(lx, h, base=L):
    """Point of the gate plane: lx units along the gate axis, h units above the ground."""
    return (base[0] + lx, base[1] - 0.5 * lx - h)


def f(v):
    return f'{v:.1f}'.rstrip('0').rstrip('.')


def ground_svg():
    """Small, editable field and road planes behind the old sign footprint."""
    return ('<g id="farm-exit-ground" data-role="farm-exit-ground">'
            '<path d="M1147 1445H1156V1500L1147 1497Z" fill="#dbd3af"/>'
            '<path d="M1147 1497L1156 1500V1520H1147Z" fill="#bbd09d"/>'
            '<path d="M1234 1382L1252 1376L1252 1470L1234 1463Z" fill="#b9ce99"/>'
            '<ellipse cx="1244" cy="1468" rx="12" ry="5" fill="#abc58d"/>'
            '<path d="M1237 1468q2 -5 4 -6m2 6q1 -8 3 -10m1 10q3 -6 6 -7" fill="none" stroke="#7fa66e" stroke-width="1.2"/>'
            '</g>')


def text_path(text, size, cx, baseline, max_width, squeeze=.84):
    """Lettering as outlines in gate-plane coordinates (x right, y down), centred on cx, slightly condensed and shrunk to fit."""
    # Locate the bundled font without importing matplotlib or starting its cache.
    matplotlib_spec = importlib.util.find_spec('matplotlib')
    if matplotlib_spec is None:
        sys.exit('matplotlib is required for its bundled DejaVu Sans Bold font')
    font = TTFont(os.path.join(os.path.dirname(matplotlib_spec.origin), 'mpl-data', 'fonts', 'ttf', 'DejaVuSans-Bold.ttf'))
    gs, cmap, upm = font.getGlyphSet(), font.getBestCmap(), font['head'].unitsPerEm
    advance = sum(gs[cmap[ord(c)]].width for c in text)
    s = min(size / upm, max_width / (advance * squeeze))
    sx = s * squeeze
    width = advance * sx
    pen, x = SVGPathPen(gs), cx - width / 2
    for c in text:
        glyph = gs[cmap[ord(c)]]
        glyph.draw(TransformPen(pen, (sx, 0, 0, -s, x, baseline)))
        x += glyph.width * sx
    return pen.getCommands(), s * upm


def simple_gate_svg():
    """A small painted-wood sign using the village's flat pastel shapes."""
    plane = f'matrix(1,-0.5,0,1,{f(L[0])},{f(L[1])})'
    right = P(SPAN, 0)
    top, bottom = 117, 62
    board_x, board_w = 3, SPAN - 6
    letters, size = text_path('На ферму', 18, board_x + board_w / 2, 0, board_w - 12, squeeze=.9)
    letters, _ = text_path('На ферму', size, board_x + board_w / 2,
                           -(top + bottom) / 2 + size * .34, board_w - 12, squeeze=.9)
    out = ['<g id="farm-exit-gate" data-role="farm-exit-gate">']
    # The old rear post is concealed by a narrow patch of grass. The new rear
    # post goes first; the board and near post cover its joints naturally.
    for x, y in (right, L):
        out.append(f'<ellipse cx="{f(x + 1)}" cy="{f(y + 1)}" rx="8" ry="3" fill="#8eaa79" opacity=".35"/>')
    out.append(f'<rect x="{f(right[0] - 4)}" y="{f(right[1] - 120)}" width="8" height="117" rx="2" fill="#927050"/>'
               f'<path d="M{f(right[0] - 2)} {f(right[1] - 116)}v110" stroke="#b18c64" stroke-width="1.5" opacity=".7"/>')
    # Both ends of the left brace are behind the foreground post and plank.
    out.append(f'<g transform="{plane}"><path d="M0 -66L30 -104" fill="none" stroke="#876543" stroke-width="5" stroke-linecap="round"/>'
               '<path d="M1 -67L29 -103" fill="none" stroke="#b08a61" stroke-width="1.4" stroke-linecap="round"/></g>')
    out.append(f'<g transform="{plane}"><rect x="{board_x}" y="{-top}" width="{board_w}" height="{top - bottom}" rx="3" '
               'fill="#f3e6c7" stroke="#997654" stroke-width="2.2"/>'
               f'<path d="M{board_x + 5} {-top + 5}H{board_x + board_w - 5}" stroke="#fff2d5" stroke-width="1.4" opacity=".7"/>'
               f'<path d="{letters}" fill="#634b35"/></g>')
    out.append(f'<rect x="{f(L[0] - 4)}" y="{f(L[1] - 120)}" width="8" height="117" rx="2" fill="#927050"/>'
               f'<path d="M{f(L[0] - 2)} {f(L[1] - 116)}v110" stroke="#b18c64" stroke-width="1.5" opacity=".7"/>')
    # The road edges run down-right at about 0.375 viewBox units per x unit.
    fx, fy = right[0] + 3, right[1] - 42
    out.append(f'<g transform="matrix(1,0.375,0,1,{f(fx)},{f(fy)})">'
               '<path d="M0 -5H27L38 0L27 5H0Z" fill="#ba9568" stroke="#76593e" stroke-width="1.4" stroke-linejoin="round"/>'
               '<path d="M7 0H26M22 -3L27 0L22 3" fill="none" stroke="#634b35" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></g>')
    out.append('</g>')
    return '\n'.join(out)


def build(svg_text):
    base = re.search(r'<image width="2400" height="1800" xlink:href="data:image/webp;base64,[^"]+"/>', svg_text)
    if not base:
        sys.exit('village.svg: historic base WebP image not found')
    gate = simple_gate_svg()
    layer = f'{EXIT_START}\n{ground_svg()}\n{gate}\n{EXIT_END}'
    # The asset has no scene elements after its background image other than the
    # former sign overlay. Rebuilding this suffix also makes repeated runs exact.
    return svg_text[:base.end()] + '\n' + layer + '\n</svg>\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    src = open(SVG, encoding='utf-8').read()
    out = build(src)
    print(f'village.svg: {len(src)} -> {len(out)} bytes')
    if not args.dry_run:
        with open(SVG, 'w', encoding='utf-8', newline='') as fh:
            fh.write(out)


if __name__ == '__main__':
    main()
