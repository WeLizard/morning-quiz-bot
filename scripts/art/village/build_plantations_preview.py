"""Reproducible wave-1 vector artwork and review.

python scripts/art/village/build_plantations_preview.py --out F:/.../plantations-preview
Use --install only after owner approval; --assets-only skips review screenshots.
The SVGs and HTML are editable; PNGs are review renders, not game assets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

import harness

ITEMS = [('tea_leaf', 'Чайный лист'), ('green_tea', 'Зелёный чай'),
         ('black_tea', 'Чёрный чай'), ('wine_zero', 'Вино 0 %'), ('raisin', 'Изюм')]
STAGES = [('young', 'Саженцы'), ('adult', 'Взрослые'), ('ripe', 'Спелые')]
SPRITE_NAMES = [('card','plantation-card')]+[(f'{kind}-{stage}',f'{kind}-{stage}')
    for kind in ['vineyard','tea_garden'] for stage in ['young','adult','ripe']]+[
    ('vineyard-winter','vineyard-winter'),('plantation-empty','plantation-empty')]


def symbol(svg, ident):
    root=ET.fromstring(svg)
    inner=svg[svg.index('>')+1:svg.rindex('</svg>')]
    return f'<symbol id="{ident}" viewBox="{root.attrib["viewBox"]}">{inner}</symbol>'


def runtime_sprites(assets, out, install):
    sprite='<svg xmlns="http://www.w3.org/2000/svg">\n'+''.join(
        symbol(assets[name],ident)+'\n' for name,ident in SPRITE_NAMES)+'</svg>\n'
    icons='\n'.join(symbol(assets[name],name) for name,_ in ITEMS)
    (out/'plantations-art.svg').write_text(sprite,encoding='utf-8')
    (out/'plantations-icons.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg">'+icons+'</svg>\n',encoding='utf-8')
    if install:
        (harness.STATIC/'plantations-art.svg').write_text(sprite,encoding='utf-8')
        path=harness.STATIC/'icons.svg'
        current=path.read_text(encoding='utf-8')
        start='<!-- BEGIN GENERATED PLANTATION ICONS -->'
        end='<!-- END GENERATED PLANTATION ICONS -->'
        block=start+'\n'+icons+'\n'+end
        if start in current:
            a=current.index(start);b=current.index(end,a)+len(end)
            current=current[:a]+block+current[b:]
        else:
            existing={n.attrib.get('id') for n in ET.fromstring(current).iter()}
            assert not existing.intersection(name for name,_ in ITEMS),'Unmanaged plantation icon already exists'
            pos=current.rindex('</svg>')
            current=current[:pos]+block+'\n'+current[pos:]
        ET.fromstring(current)
        for name,_ in ITEMS:
            assert sum(n.attrib.get('id')==name for n in ET.fromstring(current).iter())==1,name
        path.write_text(current,encoding='utf-8')
    return {'symbols':len(SPRITE_NAMES),'bytes':len(sprite.encode()),'installed':install}


def img(name, cls=''):
    return f'<img class="{cls}" src="{name}.svg" alt="{name}">'


def card(name, label):
    return f'<div class="destination">{img(name)}<span>{label}</span></div>'


def products():
    return '<div class="products">'+''.join(f'<div>{img(k)}<span>{label}</span></div>' for k,label in ITEMS)+'</div>'


CSS = '''*{box-sizing:border-box}body{margin:0;background:#f3f1e5;color:#334d36;font:15px/1.45 system-ui,sans-serif}h1,h2,h3,p{margin:0}h1{font-size:32px;letter-spacing:-.035em}h2{font-size:20px}h3{font-size:16px}small,.muted{color:#65725b}.page{padding:32px;max-width:1600px;margin:auto}.eyebrow{font-size:12px;font-weight:750;letter-spacing:.12em;color:#7b8669}.intro{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}.tag{border:1px solid #b9c5a3;border-radius:30px;padding:8px 14px;font-size:13px;background:#e6ebd5}.pair{display:grid;grid-template-columns:1fr 1fr;gap:24px}.panel{background:#e5ead4;border:1px solid #c5d0af;border-radius:18px;overflow:hidden}.panel h2,.panel h3{padding:14px 18px 0}.panel>img{display:block;width:100%;height:auto}.panel>p{padding:0 18px 14px}.strip{display:grid;grid-template-columns:1.15fr 1fr 1.35fr;gap:24px;margin:24px 0}.sub{padding:16px;border-radius:18px;background:#e9ecd9;border:1px solid #ccd5b8}.row{display:flex;gap:12px;align-items:center;margin-top:12px}.destination{width:160px;flex:none;position:relative}.destination img{display:block;width:160px;height:68px;border-radius:12px}.destination span{display:block;font-size:13px;font-weight:700;margin-top:5px}.products{display:flex;justify-content:space-around;gap:8px;margin-top:16px}.products>div{text-align:center;flex:1}.products img{display:block;width:48px;height:48px;margin:auto}.products span{font-size:12px;display:block;margin-top:5px}.factory-line{display:flex;align-items:center;gap:8px}.factory-line img:first-child{width:155px;height:122px}.factory-line .mini{width:64px;height:64px;object-fit:contain;border:1px solid #b5c3a2;background:#dce6cb;border-radius:12px}.note{font-size:13px;color:#65725b;margin-top:14px}.stage-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:16px 0 24px}.stage-grid .panel h3{font-size:16px}.stage-grid img{width:100%;display:block}.contact-bottom{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px}.contact-bottom .products{flex-wrap:wrap}.contact-bottom .products>div{min-width:70px}.night{background:#1c2a25;color:#e6ebd5}.night .panel,.night .sub{background:#293c31;border-color:#4b6048}.night .muted,.night small,.night .note,.night .eyebrow{color:#b6c3a8}.night .art-tone{filter:brightness(.64) saturate(.78)}.night .tag{background:#344a37;border-color:#667858}.night .destination span{color:#e6ebd5}'''


def document(body, extra='', night=False):
    return f'<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Плантации · превью волны 1</title><style>{CSS}{extra}</style><body class="{"night" if night else ""}">{body}</body></html>'


def hero():
    return document('''<main class="page"><div class="intro"><div><div class="eyebrow">ВЕСЁЛЫЙ ФЕРМЕР · ВОЛНА 1</div><h1>Плантации за околицей</h1><p class="muted">Виноград, чай и своя чайная фабрика · открытие с L32</p></div><div class="tag">Векторное превью · 01</div></div>
<div class="pair"><section class="panel"><h2>Ферма · действующий рисунок</h2>'''+img('reference')+'''<p class="muted">Дом, амбар, пшеница и чайная — исходные функции фермы.</p></section><section class="panel"><h2>Новое · фабрика среди знакомых построек</h2>'''+img('context')+'''<p class="muted">Та же сетка, палитра и масштаб. Фабрика — справа внизу.</p></section></div>
<div class="strip"><section class="sub"><h3>Рядом с «Полями»</h3><div class="row">'''+card('fields','Поля')+card('card','Плантации · L32')+'''</div><p class="note">Оригиналы карточек — 160 × 68.</p></section><section class="sub"><h3>Чайная фабрика</h3><div class="factory-line">'''+img('factory')+img('factory','mini')+'''<span class="muted">64 px<br>каталог</span></div></section><section class="sub"><h3>Из своего урожая</h3>'''+products()+'''</section></div>
<div class="pair"><section class="panel"><h3>Виноградник · 1 га · 8 × 8</h3>'''+img('vineyard-ripe')+'''</section><section class="panel"><h3>Чайная плантация · 1 га · 8 × 8</h3>'''+img('tea_garden-ripe')+'''</section></div><p class="note">Примеры гектаров за околицей, отдельно от участка фермы. Второй гектар открывается с L36. Превью не подключено к игре.</p></main>''', '.page{padding:28px}.pair .panel>img{max-height:325px;object-fit:contain}.strip{margin:20px 0}.strip .sub{padding:14px}.strip .row{gap:10px}')


def contact():
    body='<main class="page"><div class="intro"><div><div class="eyebrow">ПЛАНТАЦИИ · ВОЛНА 1</div><h1>Стадии, силуэты, продукты</h1></div><div class="tag">64 растения на каждом гектаре</div></div>'
    for kind,label in [('vineyard','Виноград · шпалеры и целые грозди'),('tea_garden','Чай · два листа и почка')]:
        body+=f'<h2>{label}</h2><div class="stage-grid">'
        for stage,title in STAGES:
            note={'young':'Мало листвы, урожая нет','adult':'Зелёные грозди, идёт созревание','ripe':'Фиолетовые грозди, можно собирать'} if kind=='vineyard' else {'young':'Отдельные невысокие саженцы','adult':'Плотная тёмная листва','ripe':'Светлые молодые верхушки'}
            body+=f'<section class="panel"><h3>{title}</h3>{img(kind+"-"+stage)}<p class="muted">{note[stage]}</p></section>'
        body+='</div>'
    body+='<div class="contact-bottom"><section class="panel"><h3>Зимняя пауза винограда</h3>'+img('vineyard-winter')+'<p class="muted">Голая лоза и снег. Чай растёт круглый год.</p></section><section class="panel"><h3>Чайная фабрика · отдельный рисунок</h3>'+img('factory')+'</section><section class="sub"><h3>Продукты · 48 / 24 px</h3>'+products()+'<div class="micro">'+''.join(img(k) for k,_ in ITEMS)+'</div><p class="note">Чайный лист; зелёный и чёрный чай; вино 0 %; изюм.</p><div class="row">'+card('fields','Поля')+card('card','Плантации')+'</div></section></div><p class="note">Объекты собраны примитивами FarmScene и scene_buildings. Каждый SVG содержит только вектор.</p></main>'
    return document(body,'.micro{display:flex;justify-content:space-around;margin:24px 0}.micro img{width:24px;height:24px}.contact-bottom .destination{width:140px}.contact-bottom .destination img{width:140px;height:auto}.contact-bottom .panel>img{height:260px;object-fit:contain}')


def context(night=False, screen='farm'):
    # A static review composition, not a running game or an acceptance screenshot.
    # Tokens are imported verbatim from the shell; no new runtime CSS is written.
    shell=(harness.ROOT/'web/shell/qw-tokens.css').read_text(encoding='utf-8')
    level='L32' if screen=='farm' else 'L36'
    body='<div class="safe"></div><header><span class="sun">'+('☾' if night else '☀')+'</span><strong>Весёлый фермер</strong><span class="hud">'+level+'</span><span class="gear">⚙</span></header><nav>'+card('fields','Поля')+card('card','Плантации')+'</nav>'
    if screen=='farm':
        body+='<main class="farm-view"><div class="farm-title"><div class="eyebrow">СВОЁ МЕСТО ПОД СОЛНЦЕМ</div><h1>Тихая поляна</h1><p class="muted">Чайная фабрика на своём участке</p></div>'+img('context','farm-art art-tone')+'<div class="controls"><div>☰ Меню</div><div>Собрать урожай</div></div><section class="catalog"><h3>Всё · новая мастерская</h3><div class="catalog-row">'+img('factory','art-tone')+'<div><b>Чайная фабрика</b><p class="muted">L32 · зелёный и чёрный чай</p></div></div></section></main>'
    else:
        body+='<main class="plantation-view"><div class="farm-title"><div class="eyebrow">ЗА ОКОЛИЦЕЙ</div><h1>Плантации</h1><p class="muted">2 гектара · многолетние культуры</p></div><div class="acre-pair">'
        for k,label,note in [('vineyard-ripe','Виноградник','Урожай созрел'),('tea_garden-ripe','Чайная плантация','Молодые верхушки готовы')]:
            body+=f'<section class="acre"><div><h3>{label}</h3><span class="muted">1 га · 8 × 8</span></div>{img(k,"art-tone")}<p><span class="dot"></span>{note}</p></section>'
        body+='</div></main>'
    body+='<footer>Дизайн-превью · к игре не подключено'+(' · ночная тонировка' if night else '')+'</footer>'
    return document(body,shell+'''body{min-height:100vh}.safe{height:48px;background:#e4e9d6}header{height:56px;display:flex;align-items:center;gap:12px;padding:0 10px;background:#edf0df;border-bottom:1px solid #c4ceaf}header strong{font-size:15px}.sun{font-size:27px;width:36px;text-align:center}.hud{margin-left:auto;font-weight:700;font-size:13px}.gear{display:grid;place-items:center;width:36px;height:36px;border-radius:12px;background:#dce5cb;font-size:24px}nav{display:flex;gap:12px;padding:12px 16px 2px;max-width:1100px;margin:auto}.destination{width:104px}.destination img{width:104px;height:44px}.destination span{font-size:12px}.farm-title{padding:18px 18px 0}.farm-title h1{font-size:26px}.farm-title p{font-size:13px;margin-top:4px}.farm-view,.plantation-view{max-width:1100px;margin:auto}.farm-art{width:100%;height:300px;object-fit:contain;display:block}.controls{display:flex;gap:12px;padding:0 18px}.controls>div{display:grid;place-items:center;min-height:44px;background:#dce6c7;border:1px solid #adbf90;border-radius:12px;padding:0 16px;font-size:15px;font-weight:650}.controls>div:last-child{flex:1}.catalog{margin:18px;background:#e6ecd6;border:1px solid #c3d0ac;border-radius:18px;padding:12px}.catalog h3{font-size:15px}.catalog-row{display:flex;gap:14px;align-items:center}.catalog-row img{width:80px;height:72px;object-fit:contain}.catalog-row b{font-size:15px}.catalog-row p{font-size:13px}.acre-pair{display:grid;grid-template-columns:1fr 1fr;gap:20px;padding:20px 18px 4px}.acre{background:#e5ead4;border:1px solid #c5d0af;border-radius:18px;overflow:hidden;padding:14px}.acre>div{display:flex;align-items:center;justify-content:space-between;gap:8px}.acre h3{font-size:17px}.acre span{font-size:13px}.acre img{display:block;width:100%;height:250px;object-fit:contain}.acre p{font-size:13px}.dot{display:inline-block;width:7px;height:7px;background:#7e9d50;border-radius:50%;margin-right:8px}footer{text-align:center;font-size:12px;color:#65725b;padding:8px 12px 14px}.night header,.night .safe{background:#25392d;border-color:#435b40}.night .gear,.night .controls>div{background:#3a5039;color:#e8edda;border-color:#5e7651}.night .catalog,.night .acre{background:#2b3e31;border-color:#4b6048}.night footer{color:#b6c3a8}@media(max-width:600px){.acre-pair{grid-template-columns:1fr;gap:12px;padding-top:16px}.acre{padding:12px}.acre img{height:164px}.acre h3{font-size:16px}.acre>div{align-items:baseline}.plantation-view .farm-title{padding-top:14px}.plantation-view .farm-title p{margin-top:2px}.farm-art{height:280px}}@media(min-width:900px){.safe{height:48px}nav{position:absolute;top:53px;left:260px;padding:5px}.destination span{display:none}header{padding:0 24px}header .hud{margin-right:14px}.farm-art{height:390px}.farm-view{display:grid;grid-template-columns:1fr 320px;position:relative}.farm-title{grid-column:1/3}.farm-art{grid-column:1;grid-row:2/4}.catalog{grid-column:2;grid-row:2;margin-top:36px}.controls{grid-column:2;grid-row:3;align-self:start}.controls>div{padding:0 10px}.plantation-view .farm-title{padding-top:28px}.acre img{height:290px}}''',night)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--first-frame',action='store_true',help='Build assets and hero only')
    p.add_argument('--install',action='store_true',help='Install the owner-approved sprite and five icons')
    p.add_argument('--assets-only',action='store_true',help='Validate and generate vector assets without screenshots')
    args=p.parse_args()
    os.environ['TEMP']=os.environ['TMP']=r'F:\Temp'
    out=args.out.resolve()
    if os.name=='nt' and out.drive.upper()!='F:':
        raise SystemExit('Preview artifacts must be on F:')
    out.mkdir(parents=True,exist_ok=True)
    result=harness.run('plantations_preview.js',{})
    checks={}
    for name,svg in result['assets'].items():
        root=ET.fromstring(svg)
        assert not root.findall('.//{http://www.w3.org/2000/svg}image'),name
        assert 'data:image' not in svg and 'NaN' not in svg and 'Infinity' not in svg,name
        plants=root.findall('.//{http://www.w3.org/2000/svg}g')
        count=sum((n.attrib.get('class','').startswith('plant row-')) for n in plants)
        if name.startswith(('vineyard-','tea_garden-')):
            assert count==64,(name,count)
        (out/f'{name}.svg').write_text(svg,encoding='utf-8')
        checks[name]={'sha256':hashlib.sha256(svg.encode()).hexdigest(),'bytes':len(svg.encode()),'image_nodes':0,'plants':count}
    second=harness.run('plantations_preview.js',{})
    assert result==second,'Non-deterministic vector generation'
    runtime=runtime_sprites(result['assets'],out,args.install)
    (out/'native-factory.png').write_bytes(result['native_factory'])
    (out/'native-thumbnail.png').write_bytes(result['native_thumbnail'])
    validation={'runtime_sprite':runtime,'deterministic':True,'assets':checks,'bounds':result['bounds'],
                'geometry':result['geometry'],'native_canvas_and_thumbnail':True,
                'runtime_sprite_sha256':hashlib.sha256((out/'plantations-art.svg').read_bytes()).hexdigest(),
                'icon_ids':[name for name,_ in ITEMS],
                'note':'Native renderer and external SVG-use are art checks; live app acceptance is separate.'}
    (out/'art-validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'runtime_art':runtime},ensure_ascii=False),flush=True)
    if args.assets_only:
        return
    def shot(name,html,size):
        (out/f'{name}.html').write_text(html,encoding='utf-8')
        # Relative paths resolve at the origin root; use an explicit artifact mount.
        routed=html.replace('src="','src="/files/')
        harness.screenshot(routed,out/f'{name}.png',size,{'/files/':out},dpr=1)
    if args.install:
        external='<main class="page"><h1>Игровой SVG-use и настоящий Canvas</h1><div class="stage-grid">'
        for name,ident in SPRITE_NAMES:
            vb='0 0 160 68' if name=='card' else '0 0 640 370'
            external+=f'<section class="panel"><h3>{ident}</h3><svg viewBox="{vb}" style="width:100%;height:200px"><use href="/static/plantations-art.svg#{ident}"/></svg></section>'
        external+='</div><div class="row"><img src="native-factory.png" width="240" alt="Настоящий Canvas"><img src="native-thumbnail.png" width="80" alt="FarmScene.thumb">'
        for ident,_ in ITEMS:
            external+=f'<svg viewBox="0 0 48 48" width="64" height="64"><use href="/static/icons.svg#{ident}"/></svg>'
        external+='</div></main>'
        shot('runtime-art-check',document(external),(1280,1100))
    shot('hero',hero(),(1440,1210))
    print(f'FIRST_FRAME={out/"hero.png"}',flush=True)
    if args.first_frame:
        return
    shot('contact-sheet',contact(),(1600,1410))
    for w,h in [(375,812),(390,844),(1280,800)]:
        for night in [False,True]:
            for screen in ['farm','plantations']:
                shot(f'{screen}-{w}x{h}-'+('night' if night else 'day'),context(night,screen),(w,h))
    shot('closeup-factory',document(img('factory'), 'body{background:#dce6cb}img{width:960px;height:758px}'),(960,758))
    shot('closeup-vineyard',document(img('vineyard-ripe'),'img{width:1280px;display:block}'),(1280,740))
    shot('closeup-tea',document(img('tea_garden-ripe'),'img{width:1280px;display:block}'),(1280,740))
    shot('closeup-winter',document(img('vineyard-winter'),'img{width:1280px;display:block}'),(1280,740))
    rasters={}
    for path in sorted(out.glob('*.png')):
        raw=path.read_bytes()
        assert raw[:8]==b'\x89PNG\r\n\x1a\n',path
        width,height=struct.unpack('>II',raw[16:24])
        assert width>0 and height>0,path
        rasters[path.name]={'width':width,'height':height,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    source_paths=['scripts/art/village/plantations_preview.js','scripts/art/village/build_plantations_preview.py',
                  'scripts/art/village/common.js','scripts/art/village/svg_ctx.js','scripts/art/village/fields_card.js',
                  'scripts/art/village/harness.py','qw_farm/static/scene.js','qw_farm/static/scene_buildings.js',
                  'qw_farm/static/scene_expansion.js','web/shell/qw-tokens.css']
    source_hashes={name:hashlib.sha256((harness.ROOT/name).read_bytes()).hexdigest() for name in source_paths}
    manifest={'status':'approved_art_installed' if args.install else 'preview_only','runtime_installed':args.install,'PLANTATIONS_WIRED_changed':False,
              'runtime_sprite':runtime,
              'deterministic':True,'geometry':result['geometry'],'bounds':result['bounds'],'assets':checks,
              'determinism_scope':'Two independent vector generator runs compared exactly; raster hashes identify the review renders.',
              'rasters':rasters,'source_sha256':source_hashes,
              'reference':'Real farm drawing functions with a fixed illustrative layout; not a player farm screenshot.',
              'context':'Static header/view review mockup; not a live application or sandbox acceptance.',
              'night':'Uniform review tint; runtime light-layer integration remains pending.',
              'stage_semantics':'young is a juvenile seedling without harvest, not the first three 60-percent harvests; ripe artwork also applies to those early harvests.',
              'source_functions':['FarmScene.tile/plant/leaf/poly/ellipse/line/shadow','scene_buildings.body/roofOf/doorY/winY/winX/shedBox/shedRoof/fullBox/ground/rail','fields_card.fieldsCard']}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'out':str(out),'svg_count':len(checks),'deterministic':True},ensure_ascii=False))


if __name__=='__main__':
    main()
