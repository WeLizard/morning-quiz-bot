"""Export the canonical SVG sprite as portable individual SVGs plus an offline gallery."""
from pathlib import Path
import json,html,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parent

def export():
 data=json.loads((ROOT/'data.json').read_text(encoding='utf-8'));sprite=(ROOT/'art.svg').read_text(encoding='utf-8');root=ET.fromstring(sprite)
 defs=next(x for x in root if x.tag.endswith('defs'));definition=ET.tostring(defs,encoding='unicode');symbols={x.get('id'):x for x in root if x.tag.endswith('symbol')}
 out=ROOT/'illustrations';out.mkdir(exist_ok=True)
 for e in data['elements']:
  body=''.join(ET.tostring(x,encoding='unicode') for x in symbols['art-'+e['id']])
  (out/(e['id']+'.svg')).write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" role="img"><title>'+html.escape(e['name'])+'</title>'+definition+body+'</svg>',encoding='utf-8')
 tiles=''.join('<div class="tile" data-name="'+html.escape(e['name'].lower())+'"><svg viewBox="0 0 120 120"><use href="#art-'+e['id']+'"/></svg><span>'+html.escape(e['name'])+'</span></div>' for e in data['elements'])
 content='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Галерея Alchemia</title><style>html{background:#183428;color:#f0ead3;font:14px system-ui}body{max-width:1240px;margin:auto;padding:30px}.sprite{position:absolute;width:0;height:0;overflow:hidden}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:10px}.tile{background:#264434;border:1px solid #abc29926;border-radius:12px;padding:12px 5px;text-align:center;min-height:135px}.tile>svg{width:88px;height:88px;display:block;margin:auto}.tile>span{display:block;font-size:11px;line-height:1.4}h1{font:32px Georgia}p{line-height:1.7;color:#c0cbaa}input{padding:12px;width:min(90%,440px);margin-bottom:22px;background:#20392e;color:inherit;border:1px solid #a8c39480;border-radius:9px}</style>'''+sprite+'''<body><h1>Атлас иллюстраций</h1><p>Полная галерея содержит спойлеры названий и изображений. В рисунках используются общие визуальные мотивы; точных копий SVG-содержимого нет.</p><input id="filter" placeholder="Найти иллюстрацию…" aria-label="Найти иллюстрацию"><main class="grid">'''+tiles+'''</main><script>document.getElementById('filter').addEventListener('input',e=>{const q=e.target.value.toLowerCase().replaceAll('ё','е');document.querySelectorAll('.tile').forEach(t=>t.style.display=t.dataset.name.replaceAll('ё','е').includes(q)?'':'none')});</script></body></html>'''
 (ROOT/'art_gallery.html').write_text(content,encoding='utf-8')
 print('Exported',len(data['elements']),'SVGs and gallery')
if __name__=='__main__':export()
