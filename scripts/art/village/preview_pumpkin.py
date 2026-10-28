"""Build and verify Pumpkin Night review art without installing it in the game.

python scripts/art/village/preview_pumpkin.py
All outputs and child-process temporary files stay in .local/pumpkin-preview on F:.
The farm comparison is a render of actual farm functions, not an application screenshot.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET
import harness
import build_village
import preview

OUT=harness.ROOT.resolve()/'.local'/'pumpkin-preview'

def scene(theme,svg,layers,decor=True,jack=None):
    page=preview.page('/static/village.svg',theme,layers)
    # The shipped background stays byte-for-byte unchanged. Only this review page adds the new layer.
    base=f'<div class="village-fest village-fest-base" style="display:block">{svg}</div>' if decor else ''
    glow=f'<div class="village-fest village-fest-glow" style="display:block">{svg}</div>' if decor else ''
    page=page.replace('<div class="village-night">',base+'<div class="village-night">')
    page=page.replace('<i class="vfx-wheel',glow+'<i class="vfx-wheel')
    if jack and decor:
        x,y,w,h=jack['box']
        live=f'<div class="jack-preview" style="position:absolute;left:{x/24}%;top:{y/18}%;width:{w/24}%;height:{h/18}%;pointer-events:none">{jack["svg"]}</div>'
        page=page.replace('</div></html>',live+'</div></html>')
        page=page.replace('</style>','.jack-preview>svg{display:block;width:100%;height:100%}</style>',1)
    return page

def main():
    if os.name=='nt' and OUT.drive.upper()!='F:':raise RuntimeError('Previews must stay on F:')
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'tmp').mkdir(exist_ok=True)
    os.environ['TEMP']=os.environ['TMP']=str(OUT/'tmp')
    figure=harness.run('pumpkin_jack.js',{})
    assert figure==harness.run('pumpkin_jack.js',{}),'Character/candy generation is not deterministic'
    for theme,bg in [('day','#c1d5a3'),('night','#314c61')]:
        figure_page=f'<html><body style="margin:0;background:{bg}">{figure["svg"]}</body></html>'
        harness.screenshot(figure_page,OUT/f'jack-figure-{theme}.png',(400,496))
    for suffix,key in [('', 'svg'),('-symbol','symbol')]:
        candy_root=ET.fromstring(figure['candy'][key])
        assert not candy_root.findall('.//{http://www.w3.org/2000/svg}image')
        assert all(x not in figure['candy'][key] for x in ('data:image','<style','style='))
        (OUT/f'pumpkin-candy{suffix}.svg').write_text(figure['candy'][key],encoding='utf-8')
    candy_page='<html><body style="margin:0;background:#f4f1e6">'+figure['candy']['svg']+'</body></html>'
    harness.screenshot(candy_page,OUT/'pumpkin-candy-closeup.png',(240,240))
    opts={'targets':build_village.walk_targets(),'buttons':build_village.app_buttons(),'badge':build_village.festival_badge(),'pumpkinPreview':True}
    first=harness.run('village.js',opts)
    layer=first['meta']['fest']['pumpkin_night'];svg=layer['svg'];jack=layer['jack']
    (OUT/'village-fest-pumpkin_night.svg').write_text(svg,encoding='utf-8')
    (OUT/'layout.json').write_text(json.dumps({'problems':layer['problems'],'placements':layer['placements'],'jack':{k:v for k,v in (jack or {}).items() if k!='svg'}},indent=2),encoding='utf-8')
    assert not layer['problems'],layer['problems']
    print('Layout passed; checking second render',flush=True)
    second=harness.run('village.js',opts)
    assert first['world']==second['world'],'background render is not deterministic'
    assert first['meta']['fest']==second['meta']['fest'],'festival layers are not deterministic'
    assert not layer['problems'],layer['problems']
    root=ET.fromstring(svg)
    assert not root.findall('.//{http://www.w3.org/2000/svg}image')
    assert 'data:image' not in svg and '<style' not in svg and 'style=' not in svg
    assert len(layer['placements'])>=8
    assert jack,'No safe position for Jack'
    jack_root=ET.fromstring(jack['svg'])
    assert not jack_root.findall('.//{http://www.w3.org/2000/svg}image')
    assert all(x not in jack['svg'] for x in ('data:image','<style','style='))
    (OUT/'pumpkin-jack.svg').write_text(jack['svg'],encoding='utf-8')
    (OUT/'jack-manifest.json').write_text(json.dumps({k:v for k,v in jack.items() if k!='svg'},ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'village-fest-pumpkin_night.svg').write_text(svg,encoding='utf-8')
    (OUT/'reference.png').write_bytes(harness.run('pumpkin_reference.js',{})['reference'])
    layers=preview.app_layers()
    from PIL import Image
    for theme in ('day','night'):
        for enabled in (False,True):
            name=f'{theme}-'+('new' if enabled else 'before')
            harness.screenshot(scene(theme,svg,layers,enabled,jack),OUT/(name+'.png'),(3200,2400))
        old=Image.open(OUT/f'{theme}-before.png');new=Image.open(OUT/f'{theme}-new.png')
        preview.pair(old,new,'Деревня сейчас','Тыквенная ночь · предложение',.4).save(OUT/f'{theme}-overview.png')
        # Full scene and the two changed areas, inspected at useful magnification.
        new.crop((1180,780,2110,1490)).save(OUT/f'{theme}-plaza-closeup.png')
        new.crop((1470,1430,2300,1940)).save(OUT/f'{theme}-pond-closeup.png')
        jx,jy=jack['foot'][0]*4/3,jack['foot'][1]*4/3
        new.crop((round(jx-240),round(jy-235),round(jx+240),round(jy+125))).save(OUT/f'{theme}-jack-closeup.png')
        # Actual phone scale: 1600px village world / 3200px render = .5.
        for w,h in ((375,812),(390,844),(1280,800)):
            scale=.5 if w<600 else .75
            scaled=new.resize((round(3200*scale),round(2400*scale)),Image.Resampling.LANCZOS)
            cx,cy=round(1640*scale),round(1140*scale)
            scaled.crop((cx-w//2,cy-h//2,cx-w//2+w,cy-h//2+h)).save(OUT/f'village-{w}x{h}-{theme}.png')
            html=f'''<!doctype html><html lang="ru"><meta charset="utf-8"><style>
body{{margin:0;padding:18px;background:{'#172c39' if theme=='night' else '#f4f1e6'};color:{'#f4ead0' if theme=='night' else '#36523c'};font:15px system-ui}}
h1{{font-size:22px;margin:0 0 6px}}p{{margin:0 0 20px}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}h2{{font-size:15px;min-height:38px}}img{{display:block;width:100%}}.farm{{filter:{'brightness(.55) saturate(.8)' if theme=='night' else 'none'}}}
.close{{margin-top:22px}}.note{{font-size:13px;margin-top:15px;opacity:.85}}</style><h1>Тыквенная ночь</h1><p>{'Ночная' if theme=='night' else 'Дневная'} тема · вечерний гость</p>
<div class="pair"><section><h2>Ферма · исходный стиль</h2><img class="farm" src="/files/reference.png"></section><section><h2>Деревня · новый слой</h2><img src="/files/{theme}-plaza-closeup.png"></section></div>
<div class="close"><h2>Джек · 17:00–05:00 МСК</h2><img src="/files/{theme}-jack-closeup.png"></div>
<p style="display:flex;align-items:center;gap:8px;margin-top:12px"><img src="/files/pumpkin-candy.svg" style="width:36px;height:36px">3 тыквенные конфеты · подарок раз в игровой день</p>
<p class="note">Слева — рендер функций фермы. Справа — векторный слой поверх текущей карты. Это арт-превью; к игре не подключено.</p></html>'''
            harness.screenshot(html,OUT/f'comparison-{w}x{h}-{theme}.png',(w,h),{'/files/':OUT})
    report={'status':'preview_only_owner_review_required','runtime_installed':False,'deterministic':True,
        'svg_bytes':len(svg.encode()),'svg_sha256':hashlib.sha256(svg.encode()).hexdigest(),'image_nodes':0,
        'jack_svg_bytes':len(jack['svg'].encode()),'jack_sha256':hashlib.sha256(jack['svg'].encode()).hexdigest(),
        'candy_svg_bytes':len(figure['candy']['svg'].encode()),'candy_sha256':hashlib.sha256(figure['candy']['svg'].encode()).hexdigest(),
        'background_sha256':hashlib.sha256((harness.STATIC/'village.svg').read_bytes()).hexdigest(),
        'placements':layer['placements'],'problems':layer['problems'],'jack':{k:v for k,v in jack.items() if k!='svg'},
        'source_functions':['FarmScene.plant pumpkin geometry/palette (harvested fruit, no tall stem)','FarmScene.decor(scarecrow)','FarmScene.poly/line/ellipse','festKit.place/garland'],
        'limits':'Art proposal only; Jack is a separate live SVG. Gift logic and time gating are not implemented here. Screenshots are generator review pages, not live application acceptance.'}
    (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='placements'},ensure_ascii=False))
    print(OUT)

if __name__=='__main__':main()
