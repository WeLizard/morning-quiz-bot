"""Build a single, offline HTML from editable source files. Python 3.9+, no dependencies."""
from pathlib import Path
import subprocess, sys
root=Path(__file__).resolve().parent
for f in ['build_data.py','build_art.py']:
 subprocess.run([sys.executable,str(root/f)],check=True)
html=(root/'shell.html').read_text(encoding='utf-8')
for marker,filename in [('/*__STYLE__*/','style.css'),('<!--__ART__-->','art.svg'),('/*__DATA__*/','data.json'),('/*__SCRIPT__*/','game.js')]:
 html=html.replace(marker,(root/filename).read_text(encoding='utf-8'))
assert not any(s in html for s in ['/*__STYLE__*/','/*__SCRIPT__*/','/*__DATA__*/','<!--__ART__-->'])
(root/'index.html').write_text(html,encoding='utf-8')
print('Built',len(html.encode('utf-8')),'bytes')
