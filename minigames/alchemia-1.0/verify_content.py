"""Deterministic structural checks. Not a substitute for human playtesting."""
from pathlib import Path
from collections import Counter
import json, re, hashlib, xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parent
BASE={'water','earth','fire','air'}
def validate(check_art=True):
 d=json.loads((ROOT/'data.json').read_text(encoding='utf-8'))
 elements=d['elements'];ids={e['id'] for e in elements}; cats={c['id'] for c in d['categories']}
 assert len(ids)==len(elements),'Duplicate element ID'
 pairs=set();used=Counter();incoming=Counter()
 for r in d['recipes']:
  assert {r['a'],r['b'],r['result']}<=ids,r
  k='+'.join(sorted([r['a'],r['b']]))
  assert k==r['key'] and k not in pairs,r
  assert r['result'] not in [r['a'],r['b']],('No-op recipe',r)
  pairs.add(k);incoming[r['result']]+=1;used.update(set([r['a'],r['b']]))
 found=set(BASE);sweeps=0
 while True:
  before=len(found)
  for r in d['recipes']:
   if {r['a'],r['b']}<=found:found.add(r['result'])
  sweeps+=1
  if len(found)==before:break
 assert found==ids,ids-found
 for e in elements:
  assert e['category'] in cats
  assert e['art']==e['id']
  assert e['terminal']==(used[e['id']]==0)
 worlds={w['id'] for w in d['worlds']}
 assert len(worlds)==len(d['worlds'])
 assert len({c['id'] for c in d['chapters']})==len(d['chapters'])
 for c in d['chapters']:assert set(c['goals'])<=ids and c['world'] in worlds
 for w in d['worlds']:assert set(w['chapters'])=={c['id'] for c in d['chapters'] if c['world']==w['id']}
 stages=set()
 for c in d['campaigns']:
  assert c['world'] in worlds and len(c['stages'])==4
  for step in c['stages']:
   assert step['id'] not in stages;stages.add(step['id'])
   assert set(step['goals'])<=ids and set(step['craft'])<=ids
   assert all(incoming[x]>0 for x in step['craft'])
   assert step['reward']['points']==10
 for a in d['achievements']:
  assert a['art'] in ids
  if a['type']=='elements':assert set(a['elements'])<=ids
  elif a['type']=='count':assert a['value']<=len(ids)
  elif a['type']=='recipes':assert a['value']<=len(pairs)
 report={'elements':len(ids),'recipes':len(pairs),'reachable':len(found),'chapters':len(d['chapters']),'worlds':len(worlds),'campaigns':len(d['campaigns']),'stages':len(stages),'achievements':len(d['achievements']),'terminals':[e['id'] for e in elements if used[e['id']]==0],'single_recipe_elements':[e['id'] for e in elements if incoming[e['id']]==1]}
 if check_art:
  svg=(ROOT/'art.svg').read_text(encoding='utf-8');root=ET.fromstring(svg)
  nodes={x.attrib.get('id'):x for x in root.iter() if 'id' in x.attrib}
  assert len(nodes)==len([x for x in root.iter() if 'id' in x.attrib]),'Repeated SVG id'
  visual={}
  for e in elements:
   node=nodes['art-'+e['id']]
   body=''.join(ET.tostring(child,encoding='unicode') for child in node)
   visual[e['id']]=hashlib.sha256(body.encode()).hexdigest()
  assert len(set(visual.values()))==len(ids),'Exact duplicate illustration content'
  for ref in re.findall(r'url\(#([^\)]+)\)',svg):assert ref in nodes,('Missing SVG reference',ref)
  report['illustration_symbols']=len(visual);report['distinct_svg_bodies']=len(set(visual.values()))
  report['art_hashes']=visual
 return report
if __name__=='__main__':
 result=validate();(ROOT/'CONTENT_REPORT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print({k:v for k,v in result.items() if k not in ['art_hashes','terminals','single_recipe_elements']})
