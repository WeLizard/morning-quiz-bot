"""E17 review only: vector card and farm-left/new-right previews. No install option.

python scripts/art/village/build_fields_card.py
Outputs exclusively to physical F: .local/fields-card-preview by default.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import xml.etree.ElementTree as ET

import harness


def comparison(svg, forest, night):
    theme = 'ночь · тонировка превью' if night else 'день'
    return f'''<!doctype html><html lang="ru"><meta charset="utf-8"><title>E17 · Поля</title>
<style>*{{box-sizing:border-box}}body{{margin:0;padding:24px;background:{'#17251f' if night else '#f3f1e5'};color:{'#f3f1e5' if night else '#294633'};font:16px system-ui}}
h1{{font-size:24px;margin:0 0 5px}}p{{margin:0 0 20px;line-height:1.5}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}h2{{font-size:18px;margin:0 0 12px}}
.art{{width:100%;border-radius:16px;overflow:hidden;display:block;filter:{'brightness(.62) saturate(.82)' if night else 'none'}}}.new{{background:#dce8c9;aspect-ratio:640/340;display:grid;align-items:center}}
.new svg{{width:100%;display:block}}.row{{display:flex;gap:12px;align-items:flex-start;margin:18px 0}}.card{{width:104px;height:44px;border-radius:11px;overflow:hidden;border:1px solid #91a078;position:relative;flex:none}}.card svg{{height:100%;width:100%;display:block}}.card span{{position:absolute;bottom:2px;left:4px;font-weight:700;font-size:12px;background:#f8f5dfeb;color:#2d4934;border-radius:4px;padding:0 3px}}
.note{{font-size:13px;opacity:.8;margin-top:22px}}@media(max-width:600px){{body{{padding:14px}}h1{{font-size:21px}}.pair{{gap:10px}}h2{{font-size:15px;min-height:40px}}.row{{flex-wrap:wrap}}.card{{width:92px;height:44px}}}}</style>
<h1>Поля · предложение E17</h1><p>{theme}. Только превью, к игре не подключено.</p>
<div class="pair"><section><h2>Ферма · исходные функции</h2><img class="art" src="/files/reference.png" alt="Сарай, грядки и трактор фермы"></section>
<section><h2>Новое · карточка «Поля»</h2><div class="art new">{svg}</div></section></div>
<h2 style="margin-top:28px">Рядом с существующей карточкой «Лес»</h2><div class="row art" style="width:auto;overflow:visible">
<div class="card">{forest}<span>Лес</span></div><div class="card">{svg}<span>Поля</span></div></div>
<p class="note">Справа — чистый SVG. Техника рисуется vehicle() фермы; фон и полосы — примитивами FarmScene. Слева — настоящий рендер функций фермы, без нового арта. Ночь здесь — сравнительная тонировка; проверка в игровом экране последует после одобрения.</p></html>'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, default=harness.ROOT.resolve()/'.local'/'fields-card-preview')
    args = p.parse_args()
    out = args.out.resolve()
    if os.name == 'nt' and out.drive.upper() != 'F:':
        raise SystemExit('Preview output must be on F:')
    out.mkdir(parents=True, exist_ok=True)
    first = harness.run('fields_card.js', {})
    second = harness.run('fields_card.js', {})
    if first != second:
        raise RuntimeError('Generator output is not deterministic')
    root = ET.fromstring(first['svg'])
    assert not root.findall('.//{http://www.w3.org/2000/svg}image')
    assert 'data:image' not in first['svg']
    (out/'fields-card.svg').write_text(first['svg'], encoding='utf-8')
    (out/'fields-card-inner.svg').write_text(first['inner'], encoding='utf-8')
    (out/'reference.png').write_bytes(first['reference'])
    source = (harness.STATIC/'app.js').read_text(encoding='utf-8')
    match = re.search(r"const FOREST_CARD_ART='([^']+)';", source)
    if not match:
        raise RuntimeError('Existing forest reference declaration changed')
    forest = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 68"><rect width="160" height="68" fill="#dce8c9"/>'+match[1]+'</svg>'
    for w,h in [(375,812),(390,844),(1280,800)]:
        for night in (False,True):
            name = f'comparison-{w}x{h}-'+('night' if night else 'day')
            page = comparison(first['svg'],forest,night)
            (out/(name+'.html')).write_text(page.replace('/files/reference.png','reference.png'),encoding='utf-8')
            harness.screenshot(page,out/(name+'.png'),(w,h),{'/files/':out},dpr=1)
    closeup='<html><body style="margin:0;background:#f3f1e5">'+first['svg']+'</body></html>'
    harness.screenshot(closeup,out/'fields-closeup.png',(960,408))
    manifest={'status':'preview_only_owner_review_required','viewBox':[0,0,160,68],
              'svg_sha256':hashlib.sha256(first['svg'].encode()).hexdigest(),
              'svg_bytes':len(first['svg'].encode()),'image_nodes':0,'deterministic':True,
              'source_functions':['FarmScene.poly/line/ellipse','scene_expansion.vehicle'],
              'runtime_installed':False}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(out)
    print(json.dumps(manifest,ensure_ascii=False))


if __name__ == '__main__':
    main()
