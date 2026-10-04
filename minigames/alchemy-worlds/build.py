"""Validate the content graph and build a completely offline, single-file game.
Requires only Python 3.10+ and the standard library. Run: python build.py
"""
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parent

def build() -> Path:
    data = json.loads((ROOT / 'data.json').read_text(encoding='utf-8'))
    elements, recipes, bases = data['elements'], data['recipes'], data['base']
    sprite = (ROOT / 'illustrations.svg').read_text(encoding='utf-8')
    pairs = set()
    illustrated = set(re.findall(r'<symbol id="art-([a-z0-9_]+)"', sprite))
    if set(elements) - illustrated:
        raise ValueError(f"Missing illustrations: {set(elements) - illustrated}")
    for r in recipes:
        if not all(x in elements for x in (r['a'], r['b'], r['r'])):
            raise ValueError(f"Unknown element in recipe: {r}")
        key = '+'.join(sorted((r['a'], r['b'])))
        if key in pairs or r['key'] != key:
            raise ValueError(f"Duplicate or malformed recipe: {r}")
        pairs.add(key)
    reachable = set(bases)
    while True:
        additions = {r['r'] for r in recipes if r['a'] in reachable and r['b'] in reachable}
        if additions <= reachable:
            break
        reachable |= additions
    if set(elements) - reachable:
        raise ValueError(f"Unreachable elements: {set(elements) - reachable}")
    template = (ROOT / 'template.html').read_text(encoding='utf-8')
    parts = {
        '/*STYLE*/': (ROOT / 'styles.css').read_text(encoding='utf-8'),
        '<!--SPRITE-->': sprite,
        '/*DATA*/': json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/'),
        '/*GAME*/': (ROOT / 'game.js').read_text(encoding='utf-8'),
    }
    for marker, content in parts.items():
        if marker not in template:
            raise ValueError(f"Missing template marker: {marker}")
        template = template.replace(marker, content)
    out = ROOT / 'dist' / 'index.html'
    out.parent.mkdir(exist_ok=True)
    out.write_text(template, encoding='utf-8')
    print(f'{len(elements)} elements, {len(recipes)} unique recipes; every element is reachable.')
    print(f'Created: {out} ({out.stat().st_size:,} bytes)')
    return out

if __name__ == '__main__':
    try:
        build()
    except (OSError, ValueError, KeyError) as error:
        print(f'Build failed: {error}', file=sys.stderr)
        raise SystemExit(1)
