"""Reproducible single-file game. Python 3.9+, no build dependencies, explicit UTF-8."""
from pathlib import Path
import subprocess,sys,json,hashlib
from verify_content import validate
ROOT=Path(__file__).resolve().parent

def build():
 validate(check_art=False)
 subprocess.run([sys.executable,str(ROOT/'build_art.py')],check=True,cwd=ROOT)
 report=validate(check_art=True)
 html=(ROOT/'shell.html').read_text(encoding='utf-8')
 js=(ROOT/'game.js').read_text(encoding='utf-8')
 js=js.replace('/*__JOURNEY__*/',(ROOT/'journey.js').read_text(encoding='utf-8'))
 sources={'/*__STYLE__*/':(ROOT/'style.css').read_text(encoding='utf-8'),'<!--__ART__-->':(ROOT/'art.svg').read_text(encoding='utf-8'),'/*__DATA__*/':(ROOT/'data.json').read_text(encoding='utf-8'),'/*__SCRIPT__*/':js}
 for marker,value in sources.items():
  assert html.count(marker)==1,marker
  html=html.replace(marker,value)
 assert not any(m in html for m in [*sources,'/*__JOURNEY__*/'])
 output=html.encode('utf-8');(ROOT/'index.html').write_bytes(output)
 report['html_sha256']=hashlib.sha256(output).hexdigest()
 (ROOT/'CONTENT_REPORT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print('Built',len(output),'bytes;',report['elements'],'elements;',report['recipes'],'recipes;',report['distinct_svg_bodies'],'distinct SVG bodies')
if __name__=='__main__':build()
