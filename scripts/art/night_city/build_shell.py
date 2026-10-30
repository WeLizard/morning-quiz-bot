"""Neutral Night City shell art: everything that is NOT a world. Vector only (plus a neutral paper-grain tile).

    skyline.svg — the brand scene of the shell (entry, invitation): a night city skyline, crescent moon, street lamp and fog,
                  drawn as paths and rects from a fixed seed (no raster inside, reproducible byte for byte)
    icons.svg   — one sprite of line icons (currentColor) used by every world; worlds bring art, not icons
    icons.js    — the same sprite as a string for pages opened from file:// (preview)
    grain.webp  — neutral paper grain tile (the page CSP has no data: images), replaces the warm style-A grain
    WeLizardNoir-Regular.woff2 — the owner's display face (docs/tasks/night_city/fonts/welizard_noir), brand titles only
    shell_<slot>_<portrait|landscape>.webp + shell.json — generated backgrounds of the shell slots (owner decision
                  2026-10-30) from docs/tasks/night_city/art_batch2/shell; a slot without art keeps skyline.svg

    python -I scripts/art/night_city/build_shell.py [--out DIR]   (default .local/night-city-packs/shell)
"""
import argparse
import json
import random
import shutil
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SHELL_ART = ROOT / 'docs/tasks/night_city/art_batch2/shell'
SHELL_SLOTS = ('entry', 'rooms', 'invite', 'empty', 'loading')
SHELL_WIDTH = {'portrait': 720, 'landscape': 1280}   # phone portrait, PC landscape
SHELL_BUDGET = 150 * 1024
FONT = ROOT / 'docs/tasks/night_city/fonts/welizard_noir/web/WeLizardNoir-Regular.woff2'

# Neutral brand palette: ink, ivory and one red «stamp». Worlds bring their own colour.
INK, INK_2, INK_3, IVORY, STAMP = '#0c0d10', '#0a0c11', '#181d29', '#efe6cf', '#e0483c'

ICONS = {
    'moon': '<path d="M19.5 14.6A7.8 7.8 0 1 1 9.4 4.5a6.3 6.3 0 0 0 10.1 10.1Z"/>',
    'sun': '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/>',
    'scales': '<path d="M12 4.5v15.5M8 20h8M4.5 7h15"/><circle cx="12" cy="4" r="1"/><path d="M2.5 13 5 7l2.5 6M2.5 13a2.5 2.5 0 0 0 5 0M16.5 13 19 7l2.5 6M16.5 13a2.5 2.5 0 0 0 5 0"/>',
    'people': '<circle cx="9" cy="8.5" r="3"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><circle cx="16.5" cy="9.5" r="2.4"/><path d="M15.6 14.3A4.6 4.6 0 0 1 20.5 19"/>',
    'key': '<circle cx="7.5" cy="12" r="3.5"/><path d="M11 12h10M17.5 12v3M20.5 12v2.2"/>',
    'calendar': '<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 9.5h17M8 3v4M16 3v4M7.5 13h2M11 13h2M14.5 13h2M7.5 16.5h2M11 16.5h2"/>',
    'table': '<ellipse cx="12" cy="9.5" rx="8.5" ry="3"/><path d="M4.5 11v7M19.5 11v7M12 12.5v8M9 20.5h6"/>',
    'hourglass': '<path d="M6.5 3.5h11M6.5 20.5h11M7.5 3.5c0 4.5 4.5 5.5 4.5 8.5s-4.5 4-4.5 8.5M16.5 3.5c0 4.5-4.5 5.5-4.5 8.5s4.5 4 4.5 8.5"/>',
    'check': '<path d="m4.5 12.5 4.5 4.5 10.5-11"/>',
    'lock': '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5v-3a4 4 0 0 1 8 0v3M12 14.5V17"/>',
    'envelope': '<rect x="3" y="5.5" width="18" height="13" rx="2"/><path d="m3.5 7 8.5 6.5L20.5 7"/>',
    'alert': '<path d="M12 3.5 2.5 20h19Z"/><path d="M12 9.5v5M12 17.2v.3"/>',
    'door': '<path d="M3.5 20.5h17M6.5 20.5v-17h11v17"/><path d="m6.5 3.5 6.5 2v16l-6.5-1"/><path d="M11 12.5v1"/>',
    'talk': '<path d="M4 5h16v10.5h-9.5L6 19v-3.5H4Z"/><path d="M8 9h8M8 12h5"/>',
    'lens': '<circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 5.5 5.5"/>',
    'house': '<path d="M3.5 11 12 4l8.5 7M6 9.5V20h12V9.5M10 20v-5h4v5"/>',
    'papers': '<path d="M8.5 3.5h7.5l4 4v13H8.5Z"/><path d="M16 3.5v4h4M11.5 11h5.5M11.5 14h5.5M11.5 17h3.5M5.5 7v15h11"/>',
    'ghost': '<path d="M6 20.5V10a6 6 0 0 1 12 0v10.5l-2-1.5-2 1.5-2-1.5-2 1.5-2-1.5Z"/><path d="M10 10.5v1M14 10.5v1"/>',
    'laurel': '<path d="M8.5 20.5c-4-3-5.5-8-3.5-13.5M15.5 20.5c4-3 5.5-8 3.5-13.5"/><path d="M5.3 10.6c1.5.2 2.6 1.2 3 2.6M4.9 7c1.3 0 2.4.9 2.8 2.1M6.5 14.6c1.4-.1 2.6.6 3.1 1.8M18.7 10.6c-1.5.2-2.6 1.2-3 2.6M19.1 7c-1.3 0-2.4.9-2.8 2.1M17.5 14.6c-1.4-.1-2.6.6-3.1 1.8"/>',
    'seal': '<circle cx="12" cy="9.5" r="6"/><circle cx="12" cy="9.5" r="3"/><path d="M8.6 14.4 7 21l5-2.5 5 2.5-1.6-6.6"/>',
    'repeat': '<path d="m17 3.5 3 3-3 3"/><path d="M20 6.5H8a4 4 0 0 0-4 4v1M7 20.5l-3-3 3-3"/><path d="M4 17.5h12a4 4 0 0 0 4-4v-1"/>',
    'eye': '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/>',
    'vial': '<path d="M9.5 3.5h5M10.5 3.5v6L5.5 18a2 2 0 0 0 1.8 2.5h9.4a2 2 0 0 0 1.8-2.5l-5-8.5v-6M7.6 15h8.8"/>',
    'plane': '<path d="M21 3.5 2.5 10.5l7 3 3 7Z"/><path d="M21 3.5 9.5 13.5"/>',
    'story': '<path d="M3.5 5.5c3-1 6-1 8.5 1 2.5-2 5.5-2 8.5-1v13c-3-1-6-1-8.5 1-2.5-2-5.5-2-8.5-1Z"/><path d="M12 6.5v13"/>',
    'share': '<path d="M12 14.5v-11M7.5 8 12 3.5 16.5 8"/><path d="M5 11.5v8.5h14v-8.5"/>',
    'gear': '<circle cx="12" cy="12" r="3.2"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/>',
    'back': '<path d="m15 5-7 7 7 7"/>',
    'home': '<path d="M3 11 12 4l9 7v9h-6v-6H9v6H3Z"/>',
    'full': '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    'bug': '<path d="M9 7.5V7a3 3 0 0 1 6 0v.5M7 9h10v5a5 5 0 0 1-10 0Zm5 0v10M3 13h4m10 0h4"/>',
}


def sprite():
    symbols = ''.join(f'<symbol id="nc-i-{name}" viewBox="0 0 24 24">{body}</symbol>' for name, body in ICONS.items())
    return ('<svg xmlns="http://www.w3.org/2000/svg" style="display:none" fill="none" stroke="currentColor" '
            'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' + symbols + '</svg>')


def f(v):
    return f'{v:.1f}'.rstrip('0').rstrip('.')


def skyline():
    """1200×900 scene. Layers back to front: sky, hatching, moon, cloud bands, far / middle / near blocks, lamp, fog."""
    rnd = random.Random(1929)
    W, H = 1200, 900
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice">',
           '<defs>',
           f'<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#07080b"/><stop offset=".55" stop-color="#171c29"/>'
           f'<stop offset=".78" stop-color="#2a3243"/><stop offset="1" stop-color="{INK}"/></linearGradient>',
           f'<radialGradient id="halo"><stop offset="0" stop-color="{IVORY}" stop-opacity=".22"/><stop offset="1" stop-color="{IVORY}" stop-opacity="0"/></radialGradient>',
           f'<linearGradient id="cone" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{IVORY}" stop-opacity=".26"/>'
           f'<stop offset="1" stop-color="{IVORY}" stop-opacity="0"/></linearGradient>',
           '<linearGradient id="fog" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2b3344" stop-opacity="0"/>'
           '<stop offset=".5" stop-color="#2b3344" stop-opacity=".45"/><stop offset="1" stop-color="#2b3344" stop-opacity="0"/></linearGradient>',
           f'<linearGradient id="floor" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{INK}" stop-opacity="0"/><stop offset="1" stop-color="{INK}"/></linearGradient>',
           f'<pattern id="hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(-32)">'
           f'<path d="M0 0v7" stroke="{IVORY}" stroke-opacity=".045" stroke-width="1"/></pattern>',
           f'<pattern id="rain" width="40" height="90" patternUnits="userSpaceOnUse" patternTransform="rotate(14)">'
           f'<path d="M6 0v26M27 44v30" stroke="{IVORY}" stroke-opacity=".5" stroke-width="1.1"/></pattern>',
           '<clipPath id="conec"><path d="M196 300 70 900h290Z"/></clipPath>',
           f'<mask id="crescent"><rect width="{W}" height="{H}" fill="#fff"/><circle cx="902" cy="170" r="62" fill="#000"/></mask>',
           '</defs>',
           f'<rect width="{W}" height="{H}" fill="url(#sky)"/>',
           f'<rect width="{W}" height="620" fill="url(#hatch)"/>',
           '<circle cx="870" cy="190" r="190" fill="url(#halo)"/>',
           f'<circle cx="870" cy="190" r="104" fill="none" stroke="{IVORY}" stroke-opacity=".1"/>',
           f'<circle cx="870" cy="190" r="132" fill="none" stroke="{IVORY}" stroke-opacity=".06"/>',
           f'<circle cx="870" cy="190" r="70" fill="{IVORY}" mask="url(#crescent)"/>']
    # cloud bands: long thin ink strokes across the moon (engraved look)
    for y, x0, x1, w in [(214, 640, 1080, 9), (232, 700, 1160, 6), (150, 960, 1200, 5), (300, 520, 980, 4)]:
        out.append(f'<path d="M{x0} {y}h{x1 - x0}" stroke="#0b0d12" stroke-width="{w}" stroke-linecap="round" opacity=".85"/>')

    def blocks(base, lo, hi, color, x_step, windows, lit, extras):
        x = -20
        parts, rects = [], []
        while x < W + 20:
            w = rnd.randint(*x_step)
            h = rnd.randint(lo, hi)
            top = base - h
            shape = rnd.random()
            if shape < .22:      # stepped top
                d = f'M{x} {base}V{top + 24}h{f(w * .2)}V{top}h{f(w * .6)}v24h{f(w * .2)}V{base}Z'
            elif shape < .36:    # gable
                d = f'M{x} {base}V{top + 30}l{f(w / 2)} -30l{f(w / 2)} 30V{base}Z'
            else:
                d = f'M{x} {base}V{top}h{w}V{base}Z'
            parts.append(d)
            rects.append((x, w, top, shape))
            if extras and rnd.random() < .3:
                kind = rnd.choice(['tank', 'mast', 'chimney'])
                cx = x + rnd.randint(int(w * .25), int(w * .75))
                if kind == 'tank':
                    parts.append(f'M{cx - 16} {top}v-18h4v-6h24v6h4v18Z M{cx - 14} {top - 24}q14 -14 28 0Z')
                elif kind == 'mast':
                    parts.append(f'M{cx - 2} {top}v-70h4v70Z M{cx - 10} {top - 40}h20v3h-20Z')
                    lights.append((cx, top - 72))
                else:
                    parts.append(f'M{cx - 6} {top}v-26h12v26Z')
            if windows:
                cols = max(1, (w - 16) // 14)
                rows = max(1, (h - 40) // 22)
                for r in range(rows):
                    for c in range(cols):
                        if rnd.random() < lit:
                            wx = x + 10 + c * 14
                            wy = top + 30 + r * 22
                            if wy < base - 12:
                                out_w.append(f'<rect x="{wx}" y="{wy}" width="6" height="9"/>')
            x += w + rnd.randint(0, 6)
        out.append(f'<path fill="{color}" d="{" ".join(parts)}"/>')
        return rects

    out_w = []
    blocks(640, 140, 300, INK_3, (60, 120), False, 0, False)
    out.append('<rect y="560" width="1200" height="130" fill="url(#fog)"/>')
    mid = blocks(720, 170, 400, INK_2, (70, 140), True, .14, False)
    flat = [r for r in mid if r[3] >= .36 and 60 < r[0] < 1140]          # flat roofs only, inside the frame
    flat.sort(key=lambda r: r[2])                                          # tallest first
    marks, red = [], []
    x, w, top, _ = min((r for r in flat if 560 < r[0] < 900), key=lambda r: r[2], default=flat[0])   # mast in the moon halo
    flat = [r for r in flat if r[0] != x]
    cx = x + w * .6
    marks.append(f'M{f(cx - 2)} {top}v-78h4v78Z M{f(cx - 12)} {top - 45}h24v3h-24Z M{f(cx - 8)} {top - 61}h16v3h-16Z')
    red.append((cx, top - 82))
    x, w, top, _ = flat[1]                                                  # water tank
    cx = x + w * .4
    marks.append(f'M{f(cx - 18)} {top}v-22h4v-8h28v8h4v22Z M{f(cx - 16)} {top - 30}q16 -16 32 0Z')
    for x, w, top, _ in flat[2:5]:                                          # chimneys
        marks.append(f'M{f(x + w * .25)} {top}v-24h12v24Z M{f(x + w * .25 - 3)} {top - 24}h18v4h-18Z')
    out.append(f'<path fill="{INK_2}" d="{" ".join(marks)}"/>')
    out.append(f'<g fill="#e9d9a8" opacity=".78">{"".join(out_w)}</g>')
    for lx, ly in red:   # aircraft warning light: the one red stamp of the brand
        out.append(f'<circle cx="{f(lx)}" cy="{ly}" r="3.5" fill="{STAMP}"/><circle cx="{f(lx)}" cy="{ly}" r="11" fill="{STAMP}" opacity=".2"/>')
    # one lit window with a figure in a hat: the watcher of the night city
    x, w, top, _ = max((r for r in mid if 760 < r[0] < 1000), key=lambda r: r[1])
    wx, wy = int(x + w / 2 - 23), max(top + 70, 560)
    out.append(f'<rect x="{wx}" y="{wy}" width="46" height="66" fill="#f0d9a0"/>'
               f'<path fill="{INK_2}" d="M{wx + 5} {wy + 66}Q{wx + 7} {wy + 45} {wx + 23} {wy + 43}Q{wx + 39} {wy + 45} {wx + 41} {wy + 66}Z'
               f'M{wx + 23} {wy + 25}a8 8.5 0 1 0 .1 0Z M{wx + 10} {wy + 26}h26v3h-26Z M{wx + 15} {wy + 27}l2.5 -10h11l2.5 10Z"/>'
               f'<path d="M{wx + 23} {wy}v66M{wx} {wy + 33}h46" stroke="{INK_2}" stroke-width="2"/>')
    out.append('<rect y="660" width="1200" height="110" fill="url(#fog)"/>')
    out_w = []
    blocks(900, 120, 220, '#090b0f', (110, 220), False, 0, False)
    out.append('<path fill="#090b0f" d="M1010 760v-40h6v-12h60v12h6v40Z M1014 708q32 -28 64 0Z M1020 760l-10 -40M1072 760l10 -40 M880 762v-58h3v58Z M870 718h23v3h-23Z"/>')
    # street lamp at the left, its light cone with rain inside
    out.append('<path d="M196 300 70 900h290Z" fill="url(#cone)"/>')
    out.append('<rect x="0" y="280" width="420" height="620" fill="url(#rain)" clip-path="url(#conec)" opacity=".55"/>')
    out.append('<path fill="#07080b" d="M150 900V330q0-46 46-46h20v8h-20q-38 0-38 38V900Z M186 282h40l-6 18h-28Z M140 880h28v20h-28Z"/>')
    out.append(f'<path d="M193 300h30l-4 6h-22Z" fill="{IVORY}"/>')
    out.append(f'<rect y="760" width="{W}" height="140" fill="url(#floor)"/>')
    out.append('</svg>')
    return '\n'.join(out) + '\n'


def grain(path):
    rng = np.random.default_rng(7)
    noise = ndimage.gaussian_filter(rng.random((160, 160)), 0.6)
    noise = (noise - noise.min()) / (noise.max() - noise.min())
    tile = np.zeros((160, 160, 4), np.uint8)
    tile[..., 0], tile[..., 1], tile[..., 2] = 232, 228, 220
    tile[..., 3] = (noise * 34).astype(np.uint8)
    Image.fromarray(tile).save(path, 'WEBP', quality=60, method=6)


def backgrounds(out):
    """WebP of every shell slot and orientation that has art; shell.json maps slot → {portrait, landscape}."""
    scenes = {}
    for slot in SHELL_SLOTS:
        entry = {}
        for orient, width in SHELL_WIDTH.items():
            src = SHELL_ART / f'shell_{slot}_{orient}.png'
            if not src.exists():
                continue
            img = Image.open(src).convert('RGB')
            img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
            name = f'shell_{slot}_{orient}.webp'
            for quality in range(82, 30, -4):
                img.save(out / name, 'WEBP', quality=quality, method=6)
                if (out / name).stat().st_size <= SHELL_BUDGET:
                    break
            assert (out / name).stat().st_size <= SHELL_BUDGET, f'{name} over budget'
            entry[orient] = name
        scenes[slot] = entry or 'skyline.svg'
    data = {'schema': 'nc-shell/2', 'scenes': scenes}
    (out / 'shell.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return [f for entry in scenes.values() if isinstance(entry, dict) for f in entry.values()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=str(ROOT / '.local/night-city-packs/shell'))
    out = Path(parser.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    svg = skyline()
    (out / 'skyline.svg').write_text(svg, encoding='utf-8')
    icons = sprite()
    (out / 'icons.svg').write_text(icons + '\n', encoding='utf-8')
    (out / 'icons.js').write_text('window.NC_ICONS = %r;\n' % icons, encoding='utf-8')
    grain(out / 'grain.webp')
    shutil.copyfile(FONT, out / FONT.name)
    assert '<image' not in svg and 'data:' not in svg, 'shell scene must stay vector'
    for name in ('skyline.svg', 'icons.svg', 'grain.webp', FONT.name, 'shell.json', *backgrounds(out)):
        print(f'{name:28s} {(out / name).stat().st_size / 1024:6.1f} KB')


if __name__ == '__main__':
    main()
