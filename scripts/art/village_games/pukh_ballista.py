"""Reproduce review-only vector art and farm-left/Pukh-right comparisons; never installs."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'village'))
import harness
harness.GEN = HERE.parent


def page(svg: str, night: bool, paired: bool = True) -> str:
    colour, background = ('#eee8cc', '#26392f') if night else ('#334c37', '#f2efdf')
    pair = f'<section><h2>Ферма · исходные функции</h2><img src="/files/reference-{night}.png" alt="Рендер фермы"></section>' if paired else ''
    return f'''<!doctype html><html lang="ru"><meta charset="utf-8"><title>Сцена Пуха · превью</title>
<style>*{{box-sizing:border-box}}body{{margin:0;padding:20px;background:{background};color:{colour};font:16px system-ui}}h1{{font-size:24px;margin:0 0 8px}}p{{line-height:1.5;margin:0 0 20px}}main{{display:grid;grid-template-columns:{'1fr 1fr' if paired else '1fr'};gap:16px}}h2{{font-size:17px;margin:0 0 12px;min-height:40px}}svg,img{{display:block;width:100%;border-radius:16px}}.detail{{margin-top:22px}}.detail svg{{max-height:470px}}@media(max-width:600px){{body{{padding:12px}}h1{{font-size:21px}}main{{gap:8px}}h2{{font-size:14px;min-height:44px}}p{{font-size:14px}}}}</style>
<h1>Энергетос-баллиста</h1><p>{'Ночь' if night else 'День'} · предложение сцены, к игре не подключено</p>
<main>{pair}<section><h2>Пух · новая сцена</h2>{svg}</section></main>
<div class="detail"><h2>Крупный план всей игровой площадки</h2>{svg.replace('id="pb', 'id="detail-pb').replace('url(#pb','url(#detail-pb')}</div>
<p style="margin-top:18px">Пять открытых окон, навес и флюгер. Банка, лапа Пуха, флюгер и цели — отдельные слои. Слева ночью показана сравнительная тонировка исходной фермы.</p></html>'''


def main():
    if '--install' in sys.argv:
        for night in (False, True):
            result = harness.run('village_games/pukh_ballista.js', {'night': night})
            assert result == harness.run('village_games/pukh_ballista.js', {'night': night})
            svg = result['svg']
            root = ET.fromstring(svg)
            assert root.attrib['viewBox'] == '0 0 1000 600'
            assert not root.findall('.//{http://www.w3.org/2000/svg}image')
            ids = [el.attrib['id'] for el in root.iter() if 'id' in el.attrib]
            assert len(ids) == len(set(ids)) and all(f'pb-target-{i}' in ids for i in range(5))
            assert 'data:image' not in svg and '<filter' not in svg
            name = 'pukh-ballista-night.svg' if night else 'pukh-ballista-scene.svg'
            (HERE.parent.parent.parent/'qw_farm'/'static'/name).write_text(svg, encoding='utf-8')
            print(f'Installed {name}: {hashlib.sha256(svg.encode()).hexdigest()}')
        return
    out=harness.ROOT.resolve()/'.local'/'pukh-ballista-preview-20261025'
    if os.name=='nt' and out.drive.upper()!='F:':
        raise SystemExit('Preview output must be on F:')
    out.mkdir(parents=True,exist_ok=True)
    manifest={'status':'preview_only_owner_review_required','runtime_installed':False,'themes':{}}
    for night in (False,True):
        result=harness.run('village_games/pukh_ballista.js',{'night':night})
        second=harness.run('village_games/pukh_ballista.js',{'night':night})
        assert result==second,'Scene output is not deterministic'
        svg=result['svg'];root=ET.fromstring(svg)
        assert root.attrib['viewBox']=='0 0 1000 600'
        assert not root.findall('.//{http://www.w3.org/2000/svg}image')
        assert 'data:image' not in svg and '<filter' not in svg
        ids=[el.attrib['id'] for el in root.iter() if 'id' in el.attrib]
        assert len(ids)==len(set(ids))
        assert all(f'pb-target-{i}' in ids for i in range(5))
        theme='night' if night else 'day'
        (out/f'pukh-ballista-{theme}.svg').write_text(svg,encoding='utf-8')
        (out/f'reference-{night}.png').write_bytes(result['reference'])
        manifest['world']=result['world'];manifest['windows']=result['windows']
        manifest['themes'][theme]={'bytes':len(svg.encode()),'sha256':hashlib.sha256(svg.encode()).hexdigest(),'image_nodes':0,'deterministic':True}
        for w,h in [(375,812),(390,844),(1280,800)]:
            html=page(svg,night)
            stem=f'comparison-{w}x{h}-{theme}'
            (out/f'{stem}.html').write_text(html.replace('/files/',''),encoding='utf-8')
            harness.screenshot(html,out/f'{stem}.png',(w,h),{'/files/':out})
        harness.screenshot(f'<html><body style="margin:0">{svg}</body></html>',out/f'closeup-{theme}.png',(1000,600))
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(str(out));print(json.dumps(manifest,ensure_ascii=False))


if __name__=='__main__':
    main()
