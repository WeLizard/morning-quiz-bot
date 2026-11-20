"""Build Night City world packs (one folder per world) from the style folders of docs/tasks/night_city/art_batch2.

A world pack is everything a story brings to the shared Night City shell: scene slots (cover, title, lobby, night, day,
vote, finale, out) with time-of-day variants, role-neutral seat portraits, faction emblems, card backs, card frames with
their transparent holes, and a palette checked for contrast. Screens ask for slots, never for place names; the pack
decides which picture fills a slot. Format: world_pack.schema.json; sources and slot choices: worlds.json.

Generalises .local/night-city-design/v2/build_assets.py + install_client_art.py (noir_print_a only) to all 11 worlds.

    python -I scripts/art/night_city/build_world_pack.py                       # the three preview worlds
    python -I scripts/art/night_city/build_world_pack.py --all                 # all worlds of worlds.json
    python -I scripts/art/night_city/build_world_pack.py neon_city circus      # chosen worlds
    python -I scripts/art/night_city/build_world_pack.py --inventory           # art per slot for all worlds, no encoding
    options: --out DIR (default .local/night-city-packs/worlds), --places (also every canon place × time, lazy set)

Budgets (as in v2): scene ≤ 150 KB, card back / hero frame ≤ 90 KB, evidence frame ≤ 60 KB, icon / emblem / portrait ≤ 30 KB,
world thumbnail ≤ 20 KB. WebP; quality steps down by 4 until the file fits. Output is reproducible (no timestamps).
"""
import argparse
import colorsys
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

import PIL
from PIL import Image, features

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ART = ROOT / 'docs/tasks/night_city/art_batch2'
CANON = ROOT / 'docs/tasks/night_city/worlds/canon'
TIMES = ['morning', 'day', 'evening', 'night']
PREVIEW_WORLDS = ['manor_lake', 'neon_city', 'circus']
SCHEMA = 'nc-world-pack/1'
MANOR_CASE_CANONICAL_SHA256 = 'c062098db8c18849c724412f57dd4dab4498cf6fdfe83630ca23ee1201f04e9b'
MANOR_LOOKS = 20                                  # extra appearance portraits from characters_variants/
MANOR_ART_REFS = 20 + 8 + MANOR_LOOKS             # characters, locations, looks
MANOR_WEBPS = 20 + 8 * 4 + 81 + MANOR_LOOKS       # portraits, place times, items, looks

BUDGET = {'scene': 150_000, 'back': 90_000, 'frame': 90_000, 'frame_small': 60_000, 'icon': 30_000, 'thumb': 20_000}


# ---------------------------------------------------------------- source selection
class Source:
    """Files of one style folder: manifest entries marked selected=false are skipped; of name, name_v2, name_v3 the
    highest version wins (the art queue keeps rejected originals next to the chosen replacement)."""

    def __init__(self, style):
        self.dir = ART / style
        if not self.dir.is_dir():
            raise SystemExit(f'no style folder {self.dir}')
        self.rejected = set()
        manifest = self.dir / 'manifest.json'
        if manifest.exists():
            self._walk(json.loads(manifest.read_text(encoding='utf-8')))

    def _walk(self, node):
        if isinstance(node, dict):
            if node.get('selected') is False and isinstance(node.get('file'), str):
                self.rejected.add(node['file'].replace('\\', '/').lstrip('./'))
            for value in node.values():
                self._walk(value)
        elif isinstance(node, list):
            for value in node:
                self._walk(value)

    def find(self, rel):
        """rel without version: 'locations/main_hall_night.png' → the chosen file (Path) or None."""
        rel = rel.replace('\\', '/')
        folder, name = rel.rsplit('/', 1)
        stem = name[:-4] if name.endswith('.png') else name
        best, best_v = None, -1
        for path in (self.dir / folder).glob(f'{stem}*.png'):
            tail = path.name[len(stem):]
            m = re.fullmatch(r'(?:_v(\d+))?\.png(?:\.png)?', tail)
            if not m:
                continue
            if f'{folder}/{path.name}' in self.rejected:
                continue
            version = int(m.group(1) or 1)
            if version > best_v:
                best, best_v = path, version
        return best

    def rel(self, path):
        return path.relative_to(ART).as_posix() if path else None


# ---------------------------------------------------------------- canon
def md_table(text, heading):
    """Rows of the first table under '## <heading>' as lists of cells."""
    m = re.search(rf'^## {re.escape(heading)}.*?$(.*?)(?=^## |\Z)', text, re.M | re.S)
    if not m:
        return []
    rows = []
    for line in m.group(1).splitlines():
        if not line.startswith('|') or line.startswith('| ---'):
            continue
        rows.append([cell.strip() for cell in line.strip().strip('|').split('|')])
    return rows[1:] if rows else []


def canon(world):
    text = (CANON / world['canon']).read_text(encoding='utf-8')
    places = [row[0].strip('`') for row in md_table(text, '2.') if row and row[0].startswith('`')]
    heroes = []
    for row in md_table(text, '3.'):
        if not row or not row[0].startswith('`'):
            continue
        art = re.search(r'characters/([\w.-]+?)\.png', row[-1])
        heroes.append({'id': row[0].strip('`'), 'title': row[1], 'sex': {'м': 'm', 'ж': 'f'}.get(row[2].strip()[:1], 'x'),
                       'art': art.group(1) if art else None})
    cases = len([row for row in md_table(text, '7.') if row and re.fullmatch(r'[0-9A-Z]{1,2}', row[0])])
    return {'places': places, 'heroes': heroes, 'cases': cases}


# ---------------------------------------------------------------- colour
def hex_rgb(value):
    value = value.lstrip('#')
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def rgb_hex(rgb):
    return '#' + ''.join(f'{max(0, min(255, round(c))):02x}' for c in rgb)


def mix(a, b, t):
    a, b = hex_rgb(a), hex_rgb(b)
    return rgb_hex([a[i] + (b[i] - a[i]) * t for i in range(3)])


def lum(value):
    def f(c):
        c /= 255
        return c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4
    r, g, b = hex_rgb(value)
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)


def ratio(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + .05) / (min(la, lb) + .05)


def lighten_to(color, bg, target):
    """Move color towards white until it reaches the contrast target against bg."""
    for step in range(0, 101):
        out = mix(color, '#ffffff', step / 100)
        if ratio(out, bg) >= target:
            return out
    return '#ffffff'


def ink_for(fill):
    """Dark ink of the fill's hue (or white when the fill is dark)."""
    r, g, b = [c / 255 for c in hex_rgb(fill)]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    dark = rgb_hex([c * 255 for c in colorsys.hls_to_rgb(h, .07, min(1, s))])
    return dark if ratio(dark, fill) >= 4.5 else '#ffffff'


def palette(base):
    page = base['page']
    p = dict(base)
    p['page_rgb'] = ' '.join(str(c) for c in hex_rgb(page))
    p['surface'] = mix(page, base['edge'], .06)
    p['surface_2'] = mix(page, base['edge'], .11)
    p['accent_hi'] = mix(base['accent'], '#ffffff', .28)
    p['accent_lo'] = mix(base['accent'], '#000000', .16)
    p['accent_ink'] = base.get('accent_ink') or ink_for(base['accent'])
    p['accent_soft'] = 'rgb({} / .32)'.format(' '.join(str(c) for c in hex_rgb(base['edge'])))
    p['rule'] = 'rgb({} / .24)'.format(' '.join(str(c) for c in hex_rgb(base['edge'])))
    p['tint'] = mix(page, base['accent'], .16)
    p['btn'] = mix(page, base['accent'], .05)
    p['btn_text'] = mix(base['text'], base['accent_text'], .25)
    p['field'] = mix(page, '#000000', .25)
    p['field_line'] = mix(base['muted'], page, .35)
    # contrast mode («Контрастный режим», UI_RULES §16): text ≥ 4.5:1 and outlines ≥ 3:1 on the surface
    surface = p['surface']
    p['contrast'] = {'line': lighten_to(base['line'], surface, 3.2), 'edge': lighten_to(base['edge'], surface, 3.2),
                     'muted': lighten_to(base['muted'], surface, 7), 'accent_text': lighten_to(base['accent_text'], surface, 7),
                     'shadow': lighten_to(base['shadow'], surface, 7), 'investigation': lighten_to(base['investigation'], surface, 7)}
    checks = {'text/surface': ratio(base['text'], surface), 'muted/surface': ratio(base['muted'], surface),
              'accent_text/page': ratio(base['accent_text'], page), 'accent_text/surface_2': ratio(base['accent_text'], p['surface_2']),
              'ink/accent': ratio(p['accent_ink'], base['accent']), 'ink/accent_lo': ratio(p['accent_ink'], p['accent_lo']),
              'shadow/surface': ratio(base['shadow'], surface), 'investigation/surface': ratio(base['investigation'], surface),
              'edge/page (non-text)': ratio(base['edge'], page)}
    need = {'text/surface': 7, 'edge/page (non-text)': 3}
    failed = {k: round(v, 2) for k, v in checks.items() if v < need.get(k, 4.5)}
    return p, {k: round(v, 2) for k, v in checks.items()}, failed


# ---------------------------------------------------------------- music
def music_slots(world_id, out):
    """{slot: {file, duration, bytes}} of the encoded tracks (build_music.py) that exist in the pack folder; no track - no slot."""
    index = ROOT / '.local/night-city-packs/music.json'
    if not index.exists():
        return {}
    found = json.loads(index.read_text(encoding='utf-8')).get('worlds', {}).get(world_id, {})
    return {slot: {'file': t['file'], 'duration': t['duration'], 'bytes': (out / t['file']).stat().st_size}
            for slot in ('day', 'night', 'finale') if (t := found.get(slot)) and (out / t['file']).exists()}


# ---------------------------------------------------------------- encoding
class Writer:
    def __init__(self, out):
        self.out = out
        self.files = {}

    def save(self, im, name, kind, quality, src):
        path = self.out / f'{name}.webp'
        budget = BUDGET[kind]
        q = quality
        while True:
            im.save(path, 'WEBP', quality=q, method=6, exact=False)
            size = path.stat().st_size
            if size <= budget or q <= 40:
                break
            q -= 4
        self.files[f'{name}.webp'] = {'bytes': size, 'kind': kind, 'budget': budget, 'quality': q, 'size': list(im.size), 'source': src}
        return f'{name}.webp'


def scene(writer, path, name, width=600, src=None):
    im = Image.open(path).convert('RGB')
    im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    return writer.save(im, name, 'scene', 66, src)


def thumb(writer, path, src):
    im = Image.open(path).convert('RGB')
    im = im.resize((240, round(im.height * 240 / im.width)), Image.LANCZOS)
    return writer.save(im, 'thumb', 'thumb', 70, src)


def trimmed(writer, path, name, width, kind, src, quality=78):
    im = Image.open(path).convert('RGBA')
    im = im.crop(im.getchannel('A').getbbox())
    im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    return writer.save(im, name, kind, quality, src), im


def hole(im):
    """Transparent region around the centre, as fractions [left, top, right, bottom] of the image."""
    import numpy as np
    from scipy import ndimage

    a = np.array(im)[:, :, 3] < 40
    lab, _ = ndimage.label(a)
    c = lab[im.height // 2, im.width // 2]
    if not c:
        return None
    ys, xs = np.where(lab == c)
    return [round(xs.min() / im.width, 4), round(ys.min() / im.height, 4),
            round((xs.max() + 1) / im.width, 4), round((ys.max() + 1) / im.height, 4)]


def head_box(im, tweak=None):
    """Square head-and-shoulders box from the alpha mask: scan down from the top of the head, past the widest part of the
    head (or hat) to the narrowest row (neck) after which the width at least doubles (shoulders). Works for full-length
    and half-length cut-outs; tweak = [dx, dy, scale] in units of the box side for a figure the rule misreads."""
    import numpy as np

    a = np.array(im)[:, :, 3] > 60
    rows = np.where(a.any(axis=1))[0]
    top, bottom = rows[0], rows[-1]
    height = bottom - top
    width = np.convolve(a.sum(axis=1).astype(float), np.ones(9) / 9, mode='same')
    widest, narrow, neck_row, past_head, neck = 0, 1e9, None, False, None
    for y in range(top, top + int(.55 * height)):
        v = width[y]
        if not past_head:
            widest = max(widest, v)
            if y > top + 15 and v < .85 * widest:
                past_head, narrow, neck_row = True, v, y
        else:
            if v < narrow:
                narrow, neck_row = v, y
            if v > 1.8 * narrow:
                if neck_row - top < .08 * height:
                    # a plume or a hat brim narrowed first: that was not the neck, keep scanning
                    past_head, widest = False, v
                    continue
                neck = neck_row
                break
    if neck is None:
        neck = top + int(.16 * height)
    head = neck - top
    ys, xs = np.nonzero(a[top:neck])
    cx = xs.mean() if len(xs) else im.width / 2
    side = head * 2.0
    y0 = top - .1 * head
    if tweak:
        dx, dy, scale = tweak
        cx += dx * side
        y0 += dy * side
        cx_side = side * scale
        y0 += (side - cx_side) / 2
        side = cx_side
    return tuple(int(round(v)) for v in (cx - side / 2, y0, cx + side / 2, y0 + side))


def portrait(writer, path, name, plate, tweak, src, px=128):
    im = Image.open(path).convert('RGBA')
    box = head_box(im, tweak)
    crop = im.crop(box)
    bg = Image.new('RGBA', crop.size, hex_rgb(plate) + (255,))
    bg.alpha_composite(crop)
    return writer.save(bg.convert('RGB').resize((px, px), Image.LANCZOS), name, 'icon', 80, src)


# ---------------------------------------------------------------- one world
def plan(world, defaults):
    """What each slot would use, and what is missing (no encoding)."""
    src = Source(world['style'])
    info = canon(world)
    slot_times = {**defaults['slot_times'], **world.get('slot_times', {})}
    scenes, missing = {}, []
    cover = src.find(world['cover'])
    scenes['cover'] = {'_': cover}
    for slot, rel in {**defaults['screens'], **world.get('screens', {})}.items():
        scenes[slot] = {'_': src.find(rel)}
    for slot, place in world['slots'].items():
        scenes[slot] = {time: src.find(f'locations/{place}_{time}.png') for time in slot_times.get(slot, ['evening'])}
    for slot, variants in scenes.items():
        for time, path in variants.items():
            if path is None:
                missing.append(f'scene {slot}' + ('' if time == '_' else f' · {time}'))
    art_places = sorted({re.sub(r'_(morning|day|evening|night)(_v\d+)?$', '', p.stem) for p in (src.dir / 'locations').glob('*.png')
                         if not p.stem.startswith('reference')})
    place_times = {p: [t for t in TIMES if src.find(f'locations/{p}_{t}.png')] for p in art_places}
    # portraits: canon hero ↔ art file by the art column, then by slug, then by order
    files = sorted({re.sub(r'_v\d+$', '', p.stem) for p in (src.dir / 'characters').glob('c_*.png')})
    by_slug = {re.sub(r'^c_\d+_', '', f): f for f in files}
    heroes = []
    for index, hero in enumerate(info['heroes']):
        stem = hero['art'] if hero['art'] in files else by_slug.get(hero['id']) or by_slug.get(re.sub(r'^hero_', '', hero['id']))
        if stem is None and index < len(files) and not any(h['art'] in files for h in info['heroes'] if h['art']):
            stem = files[index]
        heroes.append({**hero, 'file': stem})
    matched = {h['file'] for h in heroes if h['file']}
    for stem in files:
        if stem not in matched:
            heroes.append({'id': re.sub(r'^c_\d+_', '', stem), 'title': None, 'sex': world.get('art_sex', {}).get(stem, 'x'), 'art': stem,
                           'file': stem, 'extra': True})
    hint = re.compile(defaults['seat_exclude'])
    for hero in heroes:
        hero['seat'] = bool(hero['file']) and not hint.search(hero['file'] or '') and not hint.search(hero['id'])
    # worlds.json `ui` maps a logical name to the style's own file name when the art queue named it differently
    aliases = world.get('ui', {})
    ui = {name: src.find(aliases.get(name, f'ui/{name}.png')) for name in
          ['emblem_shadow', 'emblem_investigation', 'emblem_independent', 'card_back_role', 'card_back_case', 'card_back_event',
           'frame_hero', 'frame_evidence', 'frame_dossier', 'frame_place', 'frame_item', 'frame_ghost', 'frame_ending']}
    for name, path in ui.items():
        if path is None:
            missing.append(name)
    canon_missing = [p for p in info['places'] if p not in art_places]
    art_extra = [p for p in art_places if p not in info['places']]
    case_covers = sorted({re.sub(r'_v\d+$', '', p.name.split('.')[0]) for p in (src.dir / 'covers').glob('case_*.png')})
    seats = [h for h in heroes if h['seat']]
    return {'src': src, 'canon': info, 'scenes': scenes, 'missing': missing, 'place_times': place_times, 'heroes': heroes,
            'seats': seats, 'ui': ui, 'canon_places_missing': canon_missing, 'art_places_extra': art_extra,
            'case_covers': case_covers}


def order_seats(seats, limit):
    """Men and women alternate so a default table looks varied; at most `limit` seats."""
    women = [s for s in seats if s['sex'] == 'f']
    others = [s for s in seats if s['sex'] != 'f']
    out = []
    while (women or others) and len(out) < limit:
        if others:
            out.append(others.pop(0))
        if women and len(out) < limit:
            out.append(women.pop(0))
    return out


def build(world, defaults, out_root, with_places=False):
    p = plan(world, defaults)
    src = p['src']
    out = out_root / world['id']
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob('*.webp'):
        old.unlink()
    writer = Writer(out)
    pal, checks, failed = palette(world['palette'])
    focus = {**defaults['focus'], **world.get('focus', {})}
    scenes = {}
    for slot, variants in p['scenes'].items():
        entry = {'focus': focus.get(slot, '50% 40%')}
        for time, path in variants.items():
            if path is None:
                continue
            name = f'scene_{slot}' if time == '_' else f'scene_{slot}_{time}'
            file = scene(writer, path, name, src=src.rel(path))
            if time == '_':
                entry['file'] = file
            else:
                entry.setdefault('times', {})[time] = file
        if 'file' in entry or 'times' in entry:
            if 'times' in entry and 'file' not in entry:
                entry['default'] = next(iter(entry['times']))
            scenes[slot] = entry
    if p['scenes']['cover']['_']:
        thumb(writer, p['scenes']['cover']['_'], src.rel(p['scenes']['cover']['_']))
    places = {}
    for place, times in p['place_times'].items():
        entry = {'times': {}}
        for time in times:
            name = f'place_{place}_{time}'
            if with_places:
                path = src.find(f'locations/{place}_{time}.png')
                entry['times'][time] = scene(writer, path, name, src=src.rel(path))
            else:
                entry['times'][time] = None   # not built: lazy set, --places
        places[place] = entry
    seats = order_seats(p['seats'], defaults['seat_max'])
    tweaks = world.get('portrait_crop', {})
    portraits = []
    for k, hero in enumerate(seats, 1):
        path = src.find(f'characters/{hero["file"]}.png')
        file = portrait(writer, path, f'portrait_{k:02d}', pal['plate'], tweaks.get(hero['file']), src.rel(path))
        portraits.append({'n': k, 'file': file, 'hero': hero['id'], 'title': hero['title'], 'sex': hero['sex']})
    factions = {}
    for faction in ('shadow', 'investigation', 'independent'):
        path = p['ui'][f'emblem_{faction}']
        if path:
            factions[faction] = {'emblem': trimmed(writer, path, f'emblem_{faction}', 200, 'icon', src.rel(path))[0]}
    backs = {}
    for kind in ('role', 'case', 'event'):
        path = p['ui'][f'card_back_{kind}']
        if path:
            im = Image.open(path)
            if im.mode in ('RGBA', 'LA', 'P'):
                # a back drawn as a cut-out (transparent corners or middle) lies on the world's page colour
                card = Image.new('RGBA', im.size, hex_rgb(pal['page']) + (255,))
                card.alpha_composite(im.convert('RGBA'))
                im = card
            im = im.convert('RGB')
            im = im.resize((480, round(im.height * 480 / im.width)), Image.LANCZOS)
            backs[kind] = writer.save(im, f'back_{kind}', 'back', 72, src.rel(path))
    frames = {}
    for kind, width, budget in (('hero', 480, 'frame'), ('evidence', 400, 'frame_small'), ('dossier', 480, 'frame')):
        path = p['ui'][f'frame_{kind}']
        if path:
            file, im = trimmed(writer, path, f'frame_{kind}', width, budget, src.rel(path), quality=80)
            frames[kind] = {'file': file, 'aspect': [im.width, im.height], 'hole': hole(im)}
    total = sum(f['bytes'] for f in writer.files.values())
    over = sorted(name for name, f in writer.files.items() if f['bytes'] > f['budget'])
    music = music_slots(world['id'], out)
    sizes = {n: f['bytes'] for n, f in sorted(writer.files.items())}
    sizes.update({t['file']: t['bytes'] for t in music.values()})   # a world without music keeps its old version hash
    digest = hashlib.sha256(json.dumps(sizes).encode()).hexdigest()[:12]
    pack = {
        'schema': SCHEMA, 'id': world['id'], 'title': world['title'], 'era': world.get('era'), 'style_pack': world['style'],
        'version': digest, 'default': world['id'] == defaults['default_world'],
        'age': world.get('age', defaults.get('age', 12)),
        'palette': {k: v for k, v in pal.items()},
        'font': {'display': world.get('font')},
        'thumb': 'thumb.webp' if (out / 'thumb.webp').exists() else None,
        **({'music': {slot: {'file': t['file'], 'duration': t['duration']} for slot, t in music.items()}} if music else {}),
        'scenes': scenes, 'places': places, 'portraits': portraits, 'factions': factions, 'backs': backs, 'frames': frames,
        'checks': {'contrast': checks, 'contrast_failed': failed, 'over_budget': over, 'missing': p['missing']},
        'total_bytes': total, 'files': {n: {'bytes': f['bytes'], 'kind': f['kind'], 'quality': f['quality'], 'source': f['source']}
                                        for n, f in sorted(writer.files.items())},
    }
    (out / 'pack.json').write_text(json.dumps(pack, ensure_ascii=False, indent=1), encoding='utf-8')
    # preview pages open from file://, where fetch() of JSON is blocked: the same data as a script
    (out / 'pack.js').write_text('(window.NC_PACKS = window.NC_PACKS || {})[%s] = %s;\n'
                                 % (json.dumps(world['id']), json.dumps(pack, ensure_ascii=False)), encoding='utf-8')
    print(f"{world['id']:15s} {len(writer.files):3d} files {total / 1024:7.0f} KB  portraits {len(portraits):2d}  "
          f"over budget {over or '-'}  contrast {failed or 'ok'}  missing {p['missing'] or '-'}")
    return pack


def index(out_root, packs, defaults):
    items = [{'id': pk['id'], 'title': pk['title'], 'era': pk['era'], 'style_pack': pk['style_pack'], 'version': pk['version'],
              'thumb': f"{pk['id']}/{pk['thumb']}" if pk['thumb'] else None, 'accent': pk['palette']['accent'],
              'page': pk['palette']['page'], 'age': pk.get('age'), 'default': pk['default']} for pk in packs]
    data = {'schema': 'nc-world-index/1', 'default': defaults['default_world'], 'worlds': items}
    (out_root / 'index.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    (out_root / 'index.js').write_text('window.NC_WORLDS = %s;\n' % json.dumps(data, ensure_ascii=False), encoding='utf-8')


def alpha_info(path):
    with Image.open(path) as im:
        return list(im.size), 'A' in im.getbands() or 'transparency' in im.info


def encode_asset(path, target, width, quality):
    """Encode a case asset as WebP, retaining its alpha channel and aspect ratio."""
    with Image.open(path) as opened:
        has_alpha = 'A' in opened.getbands() or 'transparency' in opened.info
        im = opened.convert('RGBA' if has_alpha else 'RGB')
    im.thumbnail((width, width * 4), Image.Resampling.LANCZOS)
    im.save(target, 'WEBP', quality=quality, method=4, exact=True)
    with Image.open(target) as encoded:
        if ('A' in encoded.getbands()) != ('A' in im.getbands()):
            raise ValueError(f'alpha channel changed while encoding {path}')
        return list(encoded.size), 'A' in encoded.getbands(), target.stat().st_size


def build_manor_assets(world, defaults, out_dir, report_out=None):
    """Build the public H asset manifest and compact raster exports for Manor Lake only.

    The public manifest contains only art.asset_id and art.alt from the authored case.
    Source paths and hashes go to the optional private report, never to assets.json.
    """
    case_path = ROOT / 'content/night_city/manor_lake.case.json'
    case_bytes = case_path.read_bytes()
    case = json.loads(case_bytes.decode('utf-8'))
    case_canonical_hash = hashlib.sha256(canonical_json_bytes(case)).hexdigest()
    source = Source(world['style'])
    planned = plan(world, defaults)
    heroes_by_id = {h['id']: h for h in planned['heroes'] if h.get('file')}
    case_chars = case.get('characters', [])
    case_places = case.get('locations', [])
    if len(case_chars) != 20 or len(case_places) != 8:
        raise SystemExit(f'manor_lake authored case expected 20 characters and 8 locations, found {len(case_chars)} and {len(case_places)}')
    if set(h.get('id') for h in case_chars) != set(heroes_by_id):
        raise SystemExit('manor_lake case character IDs do not match canon source mapping')

    out_dir = Path(out_dir)
    report_path = Path(report_out) if report_out else None
    if report_path:
        resolved_report = report_path.resolve()
        resolved_public = out_dir.resolve()
        if resolved_report == resolved_public or resolved_public in resolved_report.parents:
            raise SystemExit('--report-out must be outside the public asset folder')
    assets_dir = out_dir / 'assets'
    assets_dir.mkdir(parents=True, exist_ok=True)
    assets = {}
    entries = []

    def export_one(path, rel_target, width, quality, asset_id=None):
        target = assets_dir / rel_target
        size, alpha, byte_count = encode_asset(path, target, width, quality)
        source_size, source_alpha = alpha_info(path)
        if alpha != source_alpha:
            raise ValueError(f'alpha mismatch for {path}')
        encoded_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        rec = {
            'asset_id': asset_id,
            'source': source.rel(path),
            'source_dimensions': source_size,
            'source_alpha': source_alpha,
            'source_sha256': source_hash,
            'export': f'assets/{rel_target}',
            'export_dimensions': size,
            'export_alpha': alpha,
            'export_sha256': encoded_hash,
            'quality': quality,
            'bytes': byte_count,
        }
        entries.append(rec)
        return f'/app/night/worlds/manor_lake/assets/{rel_target}'

    variant_files = manor_look_sources(source)
    look_count = 0
    for character in case_chars:
        art = character.get('art') or {}
        asset_id, alt = art.get('asset_id'), art.get('alt')
        hero = heroes_by_id[character['id']]
        path = source.find(f"characters/{hero['file']}.png")
        if not isinstance(asset_id, str) or not isinstance(alt, str) or path is None:
            raise SystemExit(f"missing public art reference or source for character {character['id']}")
        if asset_id in assets:
            raise SystemExit(f'duplicate case art asset_id: {asset_id}')
        url = export_one(path, f"character_{character['id']}.webp", 512, 82, asset_id)
        assets[asset_id] = {'url': url, 'alt': alt}
        # Appearance looks: the first look is the base portrait above; the others come from characters_variants/.
        for look in (character.get('looks') or [])[1:]:
            look_art = look.get('art') or {}
            look_id, look_alt = look_art.get('asset_id'), look_art.get('alt')
            file_name = f"{hero['file']}__{look['id']}.png"
            if look_id != f"manor_char_{character['id']}__{look['id']}" or not isinstance(look_alt, str) or not look_alt:
                raise SystemExit(f"look art must be manor_char_<role>__<look> with alt: {character['id']}/{look['id']}")
            if variant_files.get(file_name) != f"{hero['file']}.png":
                raise SystemExit(f'look portrait missing from characters_variants/manifest.json: {file_name}')
            look_path = source.find(f'characters_variants/{file_name}')
            if look_path is None:
                raise SystemExit(f'missing look portrait {file_name}')
            if look_id in assets:
                raise SystemExit(f'duplicate case art asset_id: {look_id}')
            look_url = export_one(look_path, f"character_{character['id']}__{look['id']}.webp", 512, 82, look_id)
            assets[look_id] = {'url': look_url, 'alt': look_alt}
            look_count += 1
    if look_count != MANOR_LOOKS:
        raise SystemExit(f'manor_lake case must have {MANOR_LOOKS} extra looks, found {look_count}')

    for place in case_places:
        art = place.get('art') or {}
        asset_id, alt, place_id = art.get('asset_id'), art.get('alt'), place.get('id')
        if not isinstance(asset_id, str) or not isinstance(alt, str) or not isinstance(place_id, str):
            raise SystemExit('missing public art reference for a Manor Lake location')
        if asset_id in assets:
            raise SystemExit(f'duplicate case art asset_id: {asset_id}')
        variants = {}
        for time in TIMES:
            path = source.find(f'locations/{place_id}_{time}.png')
            if path is None:
                raise SystemExit(f'missing source location image {place_id}_{time}')
            variants[time] = export_one(path, f'location_{place_id}_{time}.webp', 600, 76, asset_id)
        assets[asset_id] = {'url': variants['day'], 'alt': alt, 'variants': variants}

    item_paths = sorted((source.dir / 'items').glob('i_*.png'))
    if len(item_paths) != 81:
        raise SystemExit(f'expected 81 individual Manor item PNGs, found {len(item_paths)}')
    item_start = len(entries)
    item_quality = 80
    for item_path in item_paths:
        stem = item_path.stem
        export_one(item_path, f'item_{stem}.webp', 400, item_quality)
    item_bytes = sum(rec['bytes'] for rec in entries[item_start:])
    while item_bytes > 10_000_000 and item_quality > 60:
        item_quality -= 4
        for index_ in range(item_start, len(entries)):
            rec = entries[index_]
            original = source.dir / rec['source'].removeprefix(f"{world['style']}/")
            target = out_dir / rec['export']
            size, alpha, byte_count = encode_asset(original, target, 400, item_quality)
            rec.update({
                'export_dimensions': size, 'export_alpha': alpha,
                'export_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                'quality': item_quality, 'bytes': byte_count,
            })
        item_bytes = sum(rec['bytes'] for rec in entries[item_start:])
    if item_bytes > 10_000_000:
        raise SystemExit(f'81 item WebPs exceed 10 MB at quality {item_quality}: {item_bytes} bytes')

    manifest = {'schema': 'nc-assets/1', 'world': 'manor_lake', 'assets': assets}
    (out_dir / 'assets.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"manor_lake assets: {len(case_chars)} characters, {look_count} looks, {len(case_places) * len(TIMES)} place variants, "
          f"{len(item_paths)} items, {item_bytes} item bytes, {sum(r['bytes'] for r in entries)} total image bytes")
    if report_out:
        report = {
            'schema': 'nc-assets-build-report/1', 'world': 'manor_lake',
            'case_canonical_sha256': case_canonical_hash,
            'encoder': {
                'python': sys.version.split()[0],
                'pillow': PIL.__version__,
                'libwebp': features.version('webp'),
            },
            'manifest_sha256': hashlib.sha256((out_dir / 'assets.json').read_bytes()).hexdigest(),
            'manifest_asset_ids': sorted(assets), 'manifest_count': len(assets),
            'character_count': len(case_chars), 'look_count': look_count, 'location_count': len(case_places),
            'location_variant_count': len(case_places) * len(TIMES), 'item_count': len(item_paths),
            'item_bytes': item_bytes, 'total_export_bytes': sum(r['bytes'] for r in entries),
            'assets': entries,
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def manor_look_sources(source):
    """Look portraits listed in characters_variants/manifest.json as {variant file: base file}.

    Variants never live in characters/: plan() treats any c_*.png there as an extra hero."""
    path = source.dir / 'characters_variants' / 'manifest.json'
    if not path.is_file():
        return {}
    result = {}
    for row in json.loads(path.read_text(encoding='utf-8')).get('variants', []):
        name, base = row.get('file'), row.get('base')
        if not isinstance(name, str) or not isinstance(base, str) or not re.fullmatch(r'c_\d+_[a-z_]+__[a-z0-9]+\.png', name):
            raise SystemExit(f'invalid characters_variants manifest row: {row!r}')
        if name.split('__', 1)[0] + '.png' != base or name in result:
            raise SystemExit(f'characters_variants manifest row does not match its base: {name}')
        result[name] = base
    return result


def canonical_json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def case_art_refs(case_path):
    """Read only the pinned case version/hash and public art IDs/alt strings."""
    raw = Path(case_path).read_bytes()
    case = json.loads(raw.decode('utf-8'))
    canonical_hash = hashlib.sha256(canonical_json_bytes(case)).hexdigest()
    if case.get('meta', {}).get('version') != 2 or canonical_hash != MANOR_CASE_CANONICAL_SHA256:
        raise SystemExit('manor_lake case does not match the pinned v2 art source')
    refs = {}
    for group in ('characters', 'locations'):
        for entry in case.get(group, []):
            arts = [entry.get('art') or {}] + [look.get('art') or {} for look in (entry.get('looks') or [])[1:]]
            for art in arts:
                asset_id, alt = art.get('asset_id'), art.get('alt')
                if not isinstance(asset_id, str) or not re.fullmatch(r'manor_(?:char|loc)_[a-z0-9_]+', asset_id):
                    raise SystemExit(f'missing or invalid public art.asset_id in {group}')
                if not isinstance(alt, str) or not alt:
                    raise SystemExit(f'missing public art.alt for {asset_id}')
                if asset_id in refs:
                    raise SystemExit(f'duplicate public art.asset_id: {asset_id}')
                refs[asset_id] = {'group': group, 'id': entry.get('id'), 'alt': alt}
    if len(refs) != MANOR_ART_REFS:
        raise SystemExit(f'pinned Manor Lake case must have {MANOR_ART_REFS} art references, found {len(refs)}')
    return refs, canonical_hash


def safe_immutable_asset_path(value):
    return isinstance(value, str) and re.fullmatch(r'assets/[a-z0-9_]+\.webp', value) is not None


def verify_immutable_pack(directory, manifest_bytes, files):
    """Accept an existing digest directory only if its exact contents already match."""
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise SystemExit(f'content-addressed path exists but is not a regular directory: {directory}')
    expected_names = set(files) | {'assets.json'}
    actual_files = set()
    actual_dirs = set()
    for path in directory.rglob('*'):
        if path.is_symlink():
            raise SystemExit(f'symlink is forbidden in immutable pack: {path.relative_to(directory).as_posix()}')
        rel = path.relative_to(directory).as_posix()
        if path.is_dir():
            actual_dirs.add(rel)
        elif path.is_file():
            actual_files.add(rel)
    if actual_dirs != {'assets'} or actual_files != expected_names:
        raise SystemExit(f'content-addressed path has unexpected/missing entries: {directory}')
    manifest_path = directory / 'assets.json'
    if manifest_path.read_bytes() != manifest_bytes:
        raise SystemExit(f'content-addressed manifest differs; refusing overwrite: {directory}')
    for rel, digest in files.items():
        if hashlib.sha256((directory / rel).read_bytes()).hexdigest() != digest:
            raise SystemExit(f'content-addressed file differs; refusing overwrite: {directory / rel}')


def publish_immutable_manor_assets(assets_out, packs_root, report_out, compare_assets=None):
    """Publish immutable nc-assets/2 from existing WebPs. Does not re-encode or edit nc-assets/1."""
    assets_out, packs_root, report_path = Path(assets_out), Path(packs_root), Path(report_out)
    resolved_report = report_path.resolve()
    for public_path in (assets_out.resolve(), packs_root.resolve()):
        if resolved_report == public_path or public_path in resolved_report.parents:
            raise SystemExit('--report-out must be outside public asset folders')
    legacy_path = assets_out / 'assets.json'
    legacy_bytes = legacy_path.read_bytes()
    legacy = json.loads(legacy_bytes.decode('utf-8'))
    if legacy.get('schema') != 'nc-assets/1' or legacy.get('world') != 'manor_lake':
        raise SystemExit('immutable publishing requires the existing nc-assets/1 Manor Lake manifest')
    refs, case_hash = case_art_refs(ROOT / 'content/night_city/manor_lake.case.json')
    if set(legacy.get('assets', {})) != set(refs):
        raise SystemExit('legacy asset IDs do not match the pinned case art IDs')
    for asset_id, entry in legacy['assets'].items():
        if not isinstance(entry, dict) or entry.get('alt') != refs[asset_id]['alt']:
            raise SystemExit(f'legacy alt text differs from pinned case for {asset_id}')

    source_files = sorted((assets_out / 'assets').glob('*.webp'))
    if len(source_files) != MANOR_WEBPS or any(not re.fullmatch(r'[A-Za-z0-9_]+\.webp', f.name) for f in source_files):
        raise SystemExit(f'expected {MANOR_WEBPS} flat, safely named WebPs, found {len(source_files)}')
    source_by_relative = {f'assets/{path.name.lower()}': path for path in source_files}
    if len(source_by_relative) != MANOR_WEBPS:
        raise SystemExit('source WebP names collide after canonical lowercase path mapping')
    files = {rel: hashlib.sha256(path.read_bytes()).hexdigest() for rel, path in source_by_relative.items()}
    if sum(name.rsplit('/', 1)[1].startswith('item_') for name in files) != 81:
        raise SystemExit('immutable source set must contain all 81 item WebPs')

    def relative_url(url):
        prefix = '/app/night/worlds/manor_lake/'
        if not isinstance(url, str) or not url.startswith(prefix):
            raise SystemExit(f'non-local or cross-world legacy URL: {url!r}')
        rel = url[len(prefix):]
        if not re.fullmatch(r'assets/[A-Za-z0-9_]+\.webp', rel):
            raise SystemExit(f'unsafe or missing legacy asset path: {url!r}')
        canonical_rel = rel.lower()
        if not safe_immutable_asset_path(canonical_rel) or canonical_rel not in files:
            raise SystemExit(f'unsafe or missing legacy asset path: {url!r}')
        return canonical_rel

    assets = {}
    location_ids = {asset_id for asset_id, ref in refs.items() if ref['group'] == 'locations'}
    for asset_id, entry in legacy['assets'].items():
        record = {'url': relative_url(entry.get('url')), 'alt': entry['alt']}
        variants = entry.get('variants')
        if asset_id in location_ids:
            if not isinstance(variants, dict) or set(variants) != set(TIMES):
                raise SystemExit(f'location variants incomplete for {asset_id}')
            record['variants'] = {time: relative_url(variants[time]) for time in TIMES}
            if record['url'] != record['variants']['day']:
                raise SystemExit(f'location default does not select day for {asset_id}')
        elif variants is not None:
            raise SystemExit(f'character art cannot have time variants: {asset_id}')
        assets[asset_id] = record
    referenced = {entry['url'] for entry in assets.values()}
    referenced.update(url for entry in assets.values() for url in entry.get('variants', {}).values())
    if not referenced.issubset(files):
        raise SystemExit('asset references escape the hashed file table')
    if not report_path.is_file():
        raise SystemExit(f'private source/hash report is required: {report_path}')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if report.get('manifest_sha256') != hashlib.sha256(legacy_bytes).hexdigest():
        raise SystemExit('private source/hash report does not match the legacy manifest')
    exported = {row.get('export', '').lower(): row.get('export_sha256') for row in report.get('assets', [])}
    if len(exported) != MANOR_WEBPS or any(exported.get(rel) != digest for rel, digest in files.items()):
        raise SystemExit(f'private source/hash report does not match all {MANOR_WEBPS} WebPs')
    comparison = None
    if compare_assets:
        compare_dir = Path(compare_assets)
        previous = {f.name.lower(): hashlib.sha256(f.read_bytes()).hexdigest() for f in compare_dir.glob('*.webp')}
        current = {name.rsplit('/', 1)[1]: digest for name, digest in files.items()}
        changed = sorted(name for name in set(previous) | set(current) if previous.get(name) != current.get(name))
        comparison = {
            'directory': str(compare_dir.resolve()), 'same_file_set': set(previous) == set(current),
            'identical': not changed, 'changed_files': changed,
        }

    manifest = {'schema': 'nc-assets/2', 'world': 'manor_lake', 'files': files, 'assets': assets}
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    destination = packs_root / manifest_sha
    packs_root.mkdir(parents=True, exist_ok=True)

    if destination.exists() or destination.is_symlink():
        verify_immutable_pack(destination, manifest_bytes, files)
        action = 'reused'
    else:
        destination.mkdir()
        (destination / 'assets').mkdir()
        for rel in sorted(files):
            source_file = source_by_relative[rel]
            target_file = destination / rel
            with source_file.open('rb') as source_handle, target_file.open('xb') as target_handle:
                shutil.copyfileobj(source_handle, target_handle)
            if hashlib.sha256(target_file.read_bytes()).hexdigest() != files[rel]:
                raise SystemExit(f'copy hash mismatch for {rel}')
        # Publish the manifest only after every immutable file has passed its hash check.
        for rel, digest in files.items():
            if hashlib.sha256((destination / rel).read_bytes()).hexdigest() != digest:
                raise SystemExit(f'pre-publication verification failed for {rel}')
        with (destination / 'assets.json').open('xb') as manifest_handle:
            manifest_handle.write(manifest_bytes)
        verify_immutable_pack(destination, manifest_bytes, files)
        action = 'published'

    report.update({
        'case_canonical_sha256': case_hash,
        'immutable_manifest_sha256': manifest_sha,
        'immutable_manifest_path': str((destination / 'assets.json').resolve()),
        'public_manifest_url': f'/app/night/packs/{manifest_sha}/assets.json',
        'immutable_publish_action': action,
    })
    if comparison is not None:
        report['legacy_webp_comparison'] = comparison
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"immutable manor pack {action}: sha256={manifest_sha} files={len(files)} url=/app/night/packs/{manifest_sha}/assets.json")
    return manifest_sha


def inventory(config, out_root):
    defaults = config['defaults']
    rows = []
    for world in config['worlds']:
        p = plan(world, defaults)
        sex = [h['sex'] for h in p['seats']]
        rows.append({'id': world['id'], 'title': world['title'], 'style': world['style'], 'age': world.get('age', defaults.get('age', 12)),
                     'slots': {slot: [t for t, path in v.items() if path] for slot, v in p['scenes'].items()},
                     'missing': p['missing'], 'heroes_canon': len(p['canon']['heroes']),
                     'heroes_with_art': sum(1 for h in p['heroes'] if h['file'] and not h.get('extra')),
                     'heroes_without_art': [h['id'] for h in p['heroes'] if not h['file']],
                     'seats': len(p['seats']), 'seats_f': sex.count('f'), 'seats_m': sex.count('m'), 'seats_x': sex.count('x'),
                     'role_hint_portraits': [h['file'] for h in p['heroes'] if h['file'] and not h['seat']],
                     'places_art': len(p['place_times']), 'places_all_times': sum(1 for t in p['place_times'].values() if len(t) == 4),
                     'canon_places_missing': p['canon_places_missing'], 'art_places_extra': p['art_places_extra'],
                     'cases_canon': p['canon']['cases'], 'case_covers': len(p['case_covers']),
                     'ui': {k: bool(v) for k, v in p['ui'].items()}})
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / 'inventory.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    lines = ['| мир | стиль | слоты сцен | портреты (м/ж/?) | эмблемы · рубашки · рамки | места канона без арта | обложки дел | не хватает |',
             '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for r in rows:
        ui = r['ui']
        emb = sum(ui[f'emblem_{f}'] for f in ('shadow', 'investigation', 'independent'))
        backs = sum(ui[f'card_back_{k}'] for k in ('role', 'case', 'event'))
        frames = sum(ui[k] for k in ui if k.startswith('frame_'))
        gaps = list(r['missing'])
        if r['canon_places_missing']:
            gaps.append(f"места {', '.join(r['canon_places_missing'])}")
        if r['case_covers'] < r['cases_canon']:
            gaps.append(f"обложки дел {r['case_covers']}/{r['cases_canon']}")
        if r['heroes_without_art']:
            gaps.append(f"герои без арта {len(r['heroes_without_art'])}")
        lines.append(f"| {r['title']} (`{r['id']}`) | `{r['style']}` | {sum(1 for v in r['slots'].values() if v)}/8 | "
                     f"{r['seats']} ({r['seats_m']}/{r['seats_f']}/{r['seats_x']}) | {emb}/3 · {backs}/3 · {frames}/7 | "
                     f"{len(r['canon_places_missing'])} из 8 | {r['case_covers']}/{r['cases_canon']} | {'; '.join(gaps) or '—'} |")
    (out_root / 'inventory.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('worlds', nargs='*')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--inventory', action='store_true')
    parser.add_argument('--places', action='store_true')
    parser.add_argument('--out', default=str(ROOT / '.local/night-city-packs/worlds'))
    parser.add_argument('--assets-only', action='store_true', help='build only the Manor Lake H asset manifest and WebPs')
    parser.add_argument('--immutable-only', action='store_true', help='publish a content-addressed pack from existing Manor Lake WebPs')
    parser.add_argument('--assets-out', default=str(ROOT / 'web/mini_client/night/worlds/manor_lake'))
    parser.add_argument('--immutable-out', default=str(ROOT / 'web/mini_client/night/packs'))
    parser.add_argument('--compare-assets', help='optional legacy WebP directory for a private byte comparison')
    parser.add_argument('--report-out', help='optional private inventory/hash report; not copied to the web asset folder')
    args = parser.parse_args()
    config = json.loads((HERE / 'worlds.json').read_text(encoding='utf-8'))
    out_root = Path(args.out)
    if args.immutable_only:
        if args.assets_only or args.worlds or args.all or args.inventory or args.places:
            parser.error('--immutable-only is standalone; do not combine it with other build options')
        if not args.report_out:
            parser.error('--report-out is required with --immutable-only')
        publish_immutable_manor_assets(args.assets_out, args.immutable_out, args.report_out, args.compare_assets)
        return
    if args.assets_only:
        if args.worlds or args.all or args.inventory or args.places:
            parser.error('--assets-only is a standalone Manor Lake export; do not combine it with world-pack options')
        manor = next(w for w in config['worlds'] if w['id'] == 'manor_lake')
        build_manor_assets(manor, config['defaults'], args.assets_out, args.report_out)
        return
    if args.report_out or args.compare_assets:
        parser.error('--report-out and --compare-assets are only valid with --assets-only or --immutable-only')
    if args.inventory:
        inventory(config, out_root)
        return
    by_id = {w['id']: w for w in config['worlds']}
    ids = list(by_id) if args.all else (args.worlds or PREVIEW_WORLDS)
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        sys.exit(f'unknown worlds: {unknown}')
    out_root.mkdir(parents=True, exist_ok=True)
    packs = [build(by_id[i], config['defaults'], out_root, args.places) for i in ids]
    # the index lists every pack present in the output folder, not only the ones built now
    present = []
    for world in config['worlds']:
        path = out_root / world['id'] / 'pack.json'
        if path.exists():
            present.append(json.loads(path.read_text(encoding='utf-8')))
    index(out_root, present, config['defaults'])


if __name__ == '__main__':
    main()
