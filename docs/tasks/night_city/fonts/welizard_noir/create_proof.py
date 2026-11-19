from PIL import Image, ImageDraw,ImageFont
from pathlib import Path
import math
BASE=Path(__file__).resolve().parent
T=BASE/'desktop'/'WeLizardNoir-Regular.ttf'
B=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',19)
REG=ImageFont.truetype(str(T),56)
REG2=ImageFont.truetype(str(T),40)
SML=ImageFont.truetype(str(T),27)

def draw_spec():
 W,H=1460,1280
 im=Image.new('RGB',(W,H),'#eee9de');d=ImageDraw.Draw(im)
 d.rectangle((30,25,W-30,H-25),outline='#171515',width=2)
 d.text((88,55),'WeLizard Noir',font=ImageFont.truetype(str(T),105),fill='#161719')
 d.text((91,185),'Regular  |  Source: original Illustrator SVG outlines  |  RU + EN',font=B,fill='#5f574a')
 lines=[
  ('LATIN', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 270,REG2),
  ('LATIN', 'abcdefghijklmnopqrstuvwxyz', 365,REG2),
  ('КИРИЛЛИЦА', 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ', 465,ImageFont.truetype(str(T),33)),
  ('КИРИЛЛИЦА', 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя', 558,ImageFont.truetype(str(T),33)),
  ('ЦИФРЫ И ЗНАКИ','0123456789  № ₽ € $ £ ¥ ½ ¼ ¾', 650,REG),
  ('ПУНКТУАЦИЯ','!?.,:;–—_ «» “„” ‘‚’ () [] {} <> /\\ …', 765,REG2),
  ('ТЕКСТ','Детектив вошёл в тёмную комнату.', 880,REG),
  ('ТЕКСТ','The detective opened the case.', 1005,REG),
 ]
 for title,text,y,f in lines:
  d.text((85,y),title,font=B,fill='#746c60')
  d.text((85,y+25),text,font=f,fill='#131313')
 d.text((85,1182),'Desktop: TTF / OTF  |  Web: WOFF / WOFF2  |  Display typeface',font=B,fill='#393632')
 im.save(BASE/'proof'/'specimen-light.png')

def draw_mockup():
 W,H=1380,950
 im=Image.new('RGB',(W,H),'#0f1013');d=ImageDraw.Draw(im)
 d.line((80,55,80,H-50),fill='#3c3631',width=2)
 d.text((110,85),'WeLizard Noir',font=ImageFont.truetype(str(T),94),fill='#e3d0ac')
 d.text((113,201),'ТАЙНОЕ ДЕЛО № 0192',font=ImageFont.truetype(str(T),63),fill='#e9dfcc')
 d.line((112,300,1260,300),fill='#3c3631',width=3)
 d.text((113,335),'ЗАГАДКА СТАРОГО ГОРОДА',font=ImageFont.truetype(str(T),56),fill='#ded4c4')
 d.text((114,440),'Ночь. Дождь. Двадцать три свидетеля.',font=REG2,fill='#e5ddcb')
 d.text((114,518),'An unfinished case · 12 OCTOBER 1926',font=REG2,fill='#e5ddcb')
 d.text((114,595),'«Следы ведут в никуда…»',font=ImageFont.truetype(str(T),58),fill='#e6d4b4')
 d.text((114,720),'Файл № 024   ₽150   ½   №-35   © 2026',font=REG2,fill='#cdc3b1')
 d.text((114,827),'RU  /  EN   •   TrueType  /  OpenType  /  Web',font=B,fill='#80796d')
 im.save(BASE/'proof'/'specimen-dark.png')

def draw_grid(chars,fn,ncols=14,cellW=95,cellH=112):
 n=len(chars);rows=math.ceil(n/ncols)
 im=Image.new('RGB',(ncols*cellW,rows*cellH),'white');d=ImageDraw.Draw(im)
 font=ImageFont.truetype(str(T),58)
 ctrl=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',16)
 for i,c in enumerate(chars):
  x=(i%ncols)*cellW;y=(i//ncols)*cellH
  d.rectangle((x,y,x+cellW-1,y+cellH-1),outline='#ddd')
  d.text((x+9,y+4),f'U+{ord(c):04X}',font=ctrl,fill='#666')
  d.text((x+10,y+32),c,font=font,fill='#111',anchor='lt')
 im.save(BASE/'proof'/fn)

if __name__=='__main__':
 draw_spec();draw_mockup()
 draw_grid('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz','qa-latin.png')
 draw_grid('АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя','qa-cyrillic.png',ncols=11,cellW=100)
 draw_grid('0123456789!?.,:;–—_«»“„”‘‚’()[]{}<>/\\…№₽€¢£¥@%&*±≠≤≥∞∫','qa-symbols.png')
