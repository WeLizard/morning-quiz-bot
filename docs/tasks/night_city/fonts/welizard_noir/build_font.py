#!/usr/bin/env python3
"""WeLizard Noir typeface assembly from artist's outlined glyph contact-sheet SVG.

Reuses original vector paths instead of tracing raster artwork.
Supports Cyrillic/Latin, punctuation, Cyrillic Ё/ё/Й/й, selected decorative glyphs.
"""
import io, math, re, copy, json, os, sys, shutil
from collections import OrderedDict
from pathlib import Path
from lxml import etree
from fontTools.svgLib.path import parse_path
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.fontBuilder import FontBuilder
from fontTools.misc.timeTools import timestampNow
from fontTools.ttLib import TTFont
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'sources'/'original-character-set.svg'
TREE=etree.parse(str(SOURCE))
# Preserve the historical drawing-element index mapping from v1.0.
# Adobe Illustrator moved the lowercase hard-sign outline to the final layer,
# converted one accent circle to an ellipse, and split lowercase Ы into two
# separate outlines.  We map the original elements to their correct new nodes,
# then register the NEW stem of lowercase Ы as index 395.
_source_nodes=list(TREE.getroot().iter())
ELEMENTS={i:_source_nodes[i] for i in range(376)}
ELEMENTS[376]=_source_nodes[395]        # revised lowercase hard sign
ELEMENTS.update({i:_source_nodes[i-1] for i in range(377,394)})
ELEMENTS[395]=_source_nodes[396]        # newly added second stroke of Ы
assert len(_source_nodes)==397 and etree.QName(_source_nodes[396]).localname=='path'
UPM=1000
SCALE={
 'latinupper':(15.35,15.35,742.45),
 'latinlower':(15.35,15.35,834.2),
 'cyrupper':(17.85,17.85,926.8),
 'cyrlower':(17.85,17.85,1013.7),
 'digits':(17.55,17.55,80.3),
 'fractions':(17.45,17.45,80.3),
 'currency':(15.5,15.5,162.9),
 'symbols':(17.4,17.4,339.1),
 'punct':(17.5,17.5,245.0),
 'math':(16.7,16.7,511.9),
 'ornament':(20.0,20.0,594.0),
 'geometric':(24.0,24.0,659.0),
}
# Illustrator shifted all artwork in v1.1 SVG relative to the original page;
# compensate consistently to retain v1.0 baseline metrics.
SCALE={k:(sx,sy,base-1.1368) for k,(sx,sy,base) in SCALE.items()}
# Some glyph classes align to common typographic levels, not sheet's row baseline.
# Punctuation on contact sheet has actual dots at y245 and commas at y250;
# baseline ~245 puts the comma under it.

G=OrderedDict()
reused=[]


def mat_for_element(e):
 t=e.get('transform')
 if not t: return (1,0,0,1,0,0)
 m=re.search(r'matrix\(([^)]+)\)',t)
 if not m: raise ValueError(f'Unexpected element transform: {t}')
 vv=[float(a) for a in re.split(r'[\s,]+',m.group(1).strip())]
 assert len(vv)==6
 return tuple(vv)


def draw_element(idx,pen):
 e=ELEMENTS[idx]
 tag=etree.QName(e).localname
 P=TransformPen(pen,mat_for_element(e))
 if tag=='path':
  parse_path(e.attrib['d'],P)
 elif tag=='rect':
  x,y,w,h=(float(e.get(k)) for k in ('x','y','width','height'))
  P.moveTo((x,y));P.lineTo((x+w,y));P.lineTo((x+w,y+h));P.lineTo((x,y+h));P.closePath()
 elif tag in ('circle','ellipse'):
  x,y=(float(e.get(k)) for k in ('cx','cy'))
  if tag=='circle': rx=ry=float(e.get('r'))
  else: rx=float(e.get('rx'));ry=float(e.get('ry'))
  k=.5522847498307936
  P.moveTo((x+rx,y))
  P.curveTo((x+rx,y+k*ry),(x+k*rx,y+ry),(x,y+ry))
  P.curveTo((x-k*rx,y+ry),(x-rx,y+k*ry),(x-rx,y))
  P.curveTo((x-rx,y-k*ry),(x-k*rx,y-ry),(x,y-ry))
  P.curveTo((x+k*rx,y-ry),(x+rx,y-k*ry),(x+rx,y))
  P.closePath()
 elif tag=='polygon':
  s=e.attrib['points'].strip()
  vals=[float(v) for v in re.split(r'[\s,]+',s) if v]
  assert len(vals)%2==0 and len(vals)>=6
  pts=list(zip(vals[::2],vals[1::2]))
  P.moveTo(pts[0]);[P.lineTo(q) for q in pts[1:]];P.closePath()
 else: raise ValueError(f'Unexpected {tag} for index {idx}')


def bounds(indices):
 p=BoundsPen(None)
 for i in indices: draw_element(i,p)
 if p.bounds is None: raise ValueError(indices)
 return p.bounds


def add(ch,indices,kind,*, lsb=None,rsb=None,xscale=None,yscale=None, ybase=None, note=None):
 if ch in G: raise ValueError(f'Unicode duplicate {ch}')
 assert indices, ch
 b=bounds(indices)
 sx,sy,base=SCALE[kind]
 if xscale is not None: sx*=xscale
 if yscale is not None: sy*=yscale
 if ybase is not None: base=ybase
 if lsb is None: lsb=44 if kind in ('latinupper','latinlower','cyrupper','cyrlower') else 48
 if rsb is None:rsb=lsb
 advance=round((b[2]-b[0])*sx+lsb+rsb)
 G[ch]=dict(indices=indices,kind=kind,sx=sx,sy=sy,base=base,b=b,lsb=lsb,rsb=rsb,advance=advance,note=note)
 return G[ch]


def copy_char(new,old,*,xscale=1,advance=None, note='reused source glyph'):
 if new in G:raise ValueError(f'duplicate char {new}')
 d=copy.deepcopy(G[old]);d['sx']*=xscale
 d['advance']=round((d['b'][2]-d['b'][0])*d['sx']+d['lsb']+d['rsb']) if advance is None else advance
 d['note']=note
 G[new]=d
 reused.append((old,new))


def band(lo,hi,min_h=0, max_x=None):
 arr=[]
 for i,e in ELEMENTS.items():
  if etree.QName(e).localname not in ('path','rect','circle','ellipse','polygon'):continue
  x0,y0,x1,y1=bounds([i])
  if (lo <=(y0+y1)/2 < hi) and (y1-y0)>=min_h and (max_x is None or x0<max_x):
   arr.append((i,x0,x1,y0,y1))
 return sorted(arr,key=lambda z:(z[1]+z[2])/2)

# Source is a traced, precisely positioned vector specimen; letter order is
# left-to-right as on the supplied sheet.
LAT='ABCDEFGHIJKLMNOPQRSTUVWXYZ'
latinU=band(685,760,20)
assert len(latinU)==26,latinU
for c,r in zip(LAT,latinU):add(c,[r[0]],'latinupper')
latinL=band(780,855,19)
assert len(latinL)==26,latinL
for c,r in zip(LAT.lower(),latinL):
 idxs=[r[0]]
 if c=='i':idxs+=[389]
 elif c=='j':idxs+=[388]
 add(c,idxs,'latinlower')

CYR_U='АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ'
assert len(CYR_U)==33
cyru=band(872,943,15)
assert len(cyru)==34,cyru
# Two source paths comprise capital Ы; a single cmap entry must contain both.
cyru_list=[[i] for i,*_ in cyru]
positions=[j for j,ids in enumerate(cyru_list) if ids==[340]]
assert len(positions)==1
pos=positions[0];assert cyru_list[pos+1]==[381]
cyru_list[pos].append(381);del cyru_list[pos+1]
assert len(cyru_list)==33
for c,ids in zip(CYR_U,cyru_list):
 if c=='Ё': ids=ids+[390,391]
 elif c=='Й':ids=ids+[386]
 add(c,ids,'cyrupper')

cyrl=band(962,1038,15)
assert len(cyrl)==34, cyrl
# Lowercase Ы was fixed in the source; its right-side stroke is now a
# distinct second contour. Combine both glyph outlines in one Unicode entry.
cyrl_list=[[r[0]] for r in cyrl]
pos=[j for j,ids in enumerate(cyrl_list) if ids==[372]]
assert len(pos)==1 and cyrl_list[pos[0]+1]==[395],cyrl_list
cyrl_list[pos[0]] += cyrl_list.pop(pos[0]+1)
assert len(cyrl_list)==33
for c,ids in zip(CYR_U.lower(),cyrl_list):
 if c=='ё':ids += [392,393]
 if c=='й':ids += [387]
 add(c,ids,'cyrlower')

numerals=band(29,89,20,max_x=260)
assert len(numerals)==10,numerals
for c,r in zip('0123456789',numerals): add(c,[r[0]],'digits',lsb=54,rsb=54)

# The three vulgar fractions in the source are separate numerator / slash /
# denominator paths. The slash is a transformed Illustrator rectangle.
add('½',[72,56,78],'fractions',lsb=42)
add('¼',[65,54,76],'fractions',lsb=42)
add('¾',[58,57,77],'fractions',lsb=42)

# Currency drawn at the top of the SVG; map only unambiguous actual outlines.
CURRENCY={
 '$':[16], '€':[28], '£':[20], '¥':[21], '¢':[25], '₵':[27],
 '¤':[36], 'ƒ':[17], '₩':[4], '₿':[5], '₱':[10],
 '₨':[6,29], '₺':[14], '₹':[15], '₸':[41,73], '₽':[13],
}
for c,ids in CURRENCY.items(): add(c,ids,'currency')

# Source sample line 3: punctuation. Several marks are split into components.
PUNCT={
 '!':[70,126], '?':[52,128], '.':[125], ',':[121], ':':[131,123], ';':[130,114],
 '-':[134], '_':[122], '—':[83], "' ":[108], '"':[105,117],
 '‘':[107], '’':[108], '“':[102,104], '”':[119,106],
 '‚':[120], '„':[111,115],
 '«':[87,84], '»':[86,85], '‹':[92], '›':[93],
 '/':[64], '\\':[63],
 '(':[49], ')':[51], '[':[45], ']':[50], '{':[47], '}':[46],
 '<':[81], '>':[80], '…':[124,129,127],
 '¡':[133,71], '¿':[132,53],
}
for c,ids in PUNCT.items():
 c=c.strip() if c.endswith(' ') else c
 add(c,ids,'punct',lsb=35,rsb=35)
copy_char('–','—',xscale=.68)
copy_char('‐','-',note='Unicode hyphen from source hyphen-minus')
copy_char('‑','-',note='nonbreaking hyphen')
copy_char('−','—',note='temporary replaced below') if False else None

SYMS={
 '@':[9], '#':[37], '№':[32,55,135], '%':[62,61,79], '&':[18], '*':[82],
 '+':[74], '=':[118,116], '~':[94], '^':[75],
 '©':[39,137], '®':[60,138], '™':[89,59],
 '†':[44], '‡':[38], '•':[90], 'ª':[66], 'º':[69],
 '¦':[88,91], '§':[31], '¶':[24],
 '◈':[97,95,98,96], '♠':[34], '♥':[22], '♦':[40], '♣':[19],
 '♢':[48],
}
for c,ids in SYMS.items():add(c,ids,'symbols')

# Geometric and mathematical language on later lines.
MATH={
 '−':[249], '×':[214], '÷':[262,263,246], '≠':[207],
 '±':[232,241], '∓':[231,242], '≈':[238,239], '∝':[206],
 '≅':[245,247], '≤':[221,250], '≥':[220,251],
 '≪':[217,218], '≫':[222,219], '√':[179], '∛':[205,240],
 '∞':[194], '∂':[181], '∇':[188], '∏':[172], '∑':[190],
 '∫':[185], '∬':[184,176], '∮':[176],
}
for c,ids in MATH.items():add(c,ids,'math')
ORN={
 '℠':[215,196], '◦':[233], '►':[204], '♯':[177], '♭':[195], '♮':[187],
}
for c,ids in ORN.items():add(c,ids,'ornament')
GEO={
 '▲':[167],'▼':[168],'◀':[170],'▶':[171],'◆':[166],
 '❖':[224,226,223,225],'■':[143],'□':[198],
 '●':[147],'○':[203],'★':[178],'☆':[201],
 '✦':[183],'✧':[197],'✸':[174],'✺':[191],'✹':[175],
}
for c,ids in GEO.items():add(c,ids,'geometric')

# Some common Unicode typography variants retain the same drawn source shape.
copy_char('·','•',xscale=.75)
copy_char('′',"'",note='prime')
copy_char('″','"',note='double prime')
copy_char('⁄','/',note='fraction slash')
copy_char('∕','/',note='division slash')
copy_char('╱','/',note='long diagonal')
copy_char('‐','-',note='hyphen') if '‐' not in G else None
copy_char('‒','—',xscale=.52,note='figure dash')
copy_char('―','—',xscale=1.12,note='horizontal bar')
copy_char('⁂','✸',note='decorative asterism from source star')
copy_char('°','◦',xscale=.8)

# Glyph spacing (codepoint-driven). No system or fallback fonts are mixed in.
SPACES={
  ' ':270, '\u00a0':270, '\u2002':500, '\u2003':1000, '\u2009':180,
  '\u202f':200, '\u200b':0,
}

def glyphname(char):return f'uni{ord(char):04X}'

GLYPHS=OrderedDict((glyphname(c),c) for c in G)
# Names for special blank glyphs
for blank in SPACES:GLYPHS[glyphname(blank)]=blank
ORDER=['.notdef']+list(GLYPHS)
CMAP={ord(ch):glyphname(ch) for ch in GLYPHS.values()}
HM={glyphname(ch):(d['advance'],d['lsb']) for ch,d in G.items()}
for ch,w in SPACES.items():HM[glyphname(ch)]=(w,0)
HM['.notdef']=(500,50)


def contours_for_glyph(gname,pen,*,build_type):
 if gname=='.notdef':
  # Render a hollow outline box. Correct winding is respected by both CFF and TT.
  pen.moveTo((50,0));pen.lineTo((450,0));pen.lineTo((450,700));pen.lineTo((50,700));pen.closePath()
  pen.moveTo((110,60));pen.lineTo((110,640));pen.lineTo((390,640));pen.lineTo((390,60));pen.closePath()
  return
 if gname not in GLYPHS:raise KeyError(gname)
 ch=GLYPHS[gname]
 if ch in SPACES:return
 d=G[ch]; x0,y0,x1,y1=d['b']
 font_transform=(d['sx'],0,0,-d['sy'],d['lsb']-x0*d['sx'],d['base']*d['sy'])
 T=TransformPen(pen,font_transform)
 for idx in d['indices']:draw_element(idx,T)


def ttf_glyph(name):
 t=TTGlyphPen(None)
 p=Cu2QuPen(t,max_err=1.1,reverse_direction=False)
 contours_for_glyph(name,p,build_type='ttf')
 return t.glyph()


def otf_charstring(name):
 width=HM[name][0]
 p=T2CharStringPen(width,None)
 contours_for_glyph(name,p,build_type='otf')
 return p.getCharString(private=None,globalSubrs=None)

FONT_INFO={
 'familyName':'WeLizard Noir',
 'styleName':'Regular',
 'uniqueFontIdentifier':'WeLizard Noir Regular 1.100; 2026; WeLizard',
 'fullName':'WeLizard Noir Regular',
 'psName':'WeLizardNoir-Regular',
 'version':'Version 1.100',
 'copyright':'Copyright (c) 2026 WeLizard. Original outline art provided by the font owner.',
 'designer':'WeLizard',
 'description':'Custom condensed noir display typeface derived from the owner-provided vector character sheet. Cyrillic, Latin and selected decorative glyphs.',
 'licenseDescription':'Private artwork supplied by typeface owner; usage rights remain with WeLizard.',
}


def build(is_ttf=True):
 fb=FontBuilder(UPM,isTTF=is_ttf)
 fb.setupGlyphOrder(ORDER)
 fb.setupCharacterMap(CMAP)
 fb.setupHorizontalMetrics(HM)
 fb.setupHorizontalHeader(ascent=880,descent=-260, lineGap=100)
 if is_ttf:
  gl={name:ttf_glyph(name) for name in ORDER}
  fb.setupGlyf(gl)
 else:
  cs={name:otf_charstring(name) for name in ORDER}
  fb.setupCFF(FONT_INFO['psName'],
     {'FullName':'WeLizard Noir Regular','FamilyName':'WeLizard Noir','Weight':'Regular','version':'1.100',
      'Notice':FONT_INFO['copyright']},cs,privateDict={'defaultWidthX':0,'nominalWidthX':0})
 fb.setupNameTable(FONT_INFO)
 fb.setupOS2(
   sTypoAscender=880,sTypoDescender=-260,sTypoLineGap=100,
   usWinAscent=980,usWinDescent=300,fsType=0,
   sxHeight=505,sCapHeight=705,usWeightClass=400,usWidthClass=3,
   fsSelection=0x40,achVendID='WLZD',
   ulUnicodeRange1=0,ulUnicodeRange2=0,ulUnicodeRange3=0,ulUnicodeRange4=0,
   ulCodePageRange1=0,ulCodePageRange2=0)
 fb.setupPost(italicAngle=0,underlinePosition=-120,underlineThickness=48,
              isFixedPitch=0)
 fb.setupMaxp()
 fb.setupHead(created=timestampNow(),modified=timestampNow())
 font=fb.font
 # Make Unicode range/codepage bits consistent with cmap through fontTools.
 os2=font['OS/2']
 from fontTools.ttLib.tables.O_S_2f_2 import calcCodePageRanges
 from fontTools.unicodedata import ScriptExtensions
 try:os2.recalcUnicodeRanges(font,pruneOnly=False)
 except Exception:pass
 try:
  os2.ulCodePageRange1=1<<2 | 1<<0 # 1251 Cyrillic / 1252 Latin 1
 except Exception:pass
 return font


def validate(path):
 from fontTools.ttLib import TTFont
 from fontTools.pens.boundsPen import BoundsPen
 font=TTFont(path)
 cmap=font.getBestCmap()
 required='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyzАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя0123456789№₽«»—…'
 missing=sorted({x for x in required if ord(x) not in cmap})
 if missing: raise RuntimeError('Missing required characters '+''.join(missing))
 for name in font.getGlyphOrder():
  g=font.getGlyphSet()[name]
  pen=BoundsPen(font.getGlyphSet())
  try:g.draw(pen)
  except Exception as e:raise RuntimeError(f'Invalid glyph {name}: {e}')
 assert len(cmap)>=165, len(cmap)
 assert font['head'].unitsPerEm==UPM
 font.close()
 return len(cmap)


def css():
 return """/* WeLizard Noir v1.1 | SVG-outline-source based display font */
@font-face {
  font-family: 'WeLizard Noir';
  src: url('./WeLizardNoir-Regular.woff2') format('woff2'),
       url('./WeLizardNoir-Regular.woff') format('woff');
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}
/* For titles, lettering, covers and decorative headings; use a readable
   UI text font for body copy on mobile. */
.welizard-noir { font-family: 'WeLizard Noir', Georgia, serif; font-weight: 400; }
"""


def main():
 (ROOT/'desktop').mkdir(exist_ok=True)
 (ROOT/'web').mkdir(exist_ok=True)
 (ROOT/'proof').mkdir(exist_ok=True)
 f=build(True)
 ttf=str(ROOT/'desktop'/'WeLizardNoir-Regular.ttf')
 f.save(ttf)
 font=TTFont(ttf)
 for flv in ('woff','woff2'):
  font.flavor=flv
  font.save(str(ROOT/'web'/f'WeLizardNoir-Regular.{flv}'))
 font.close()
 fo=build(False)
 otf=str(ROOT/'desktop'/'WeLizardNoir-Regular.otf')
 fo.save(otf)
 n1=validate(ttf);n2=validate(otf)
 assert n1==n2
 (ROOT/'web'/'welizard-noir.css').write_text(css(),encoding='utf-8')
 report={'family':'WeLizard Noir','style':'Regular','glyphs':n1+1,'supported_codepoints':n1,
   'source_file':SOURCE.name,
   'source_elements':len([e for e in ELEMENTS.values() if etree.QName(e).localname in ('path','rect','circle','ellipse','polygon')]),
   'blocks':{'Latin capitals':26,'Latin lower':26,'Cyrillic capitals':33,'Cyrillic lower':33,'digits':10},
   'characters':''.join(G.keys()),
   'unicode':{f'U+{ord(c):04X}':{'char':c,'source_elements':d['indices'],'type':d['kind'],'glyph_name':glyphname(c)} for c,d in G.items()},
   'spaces':{f'U+{ord(c):04X}':w for c,w in SPACES.items()}}
 (ROOT/'proof'/'glyph-index.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print('Created',ttf,otf,'glyph_count',n1, 'TTF size',os.path.getsize(ttf),'OTF size',os.path.getsize(otf))

if __name__=='__main__':main()
