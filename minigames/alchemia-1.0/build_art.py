"""Original vector illustration library. All 190 drawings are embedded; no CDN, font, or bitmap dependency."""
from pathlib import Path
import json, math
ROOT=Path(__file__).parent
A={}
def path(d,f='none',s=None,w=2,**kw):
 return '<path d="%s" fill="%s"%s%s/>'%(d,f,(' stroke="%s" stroke-width="%s" stroke-linecap="round" stroke-linejoin="round"'%(s,w)) if s else '', ''.join(' %s="%s"'%(k.replace('_','-'),v) for k,v in kw.items()))
def circle(x,y,r,f,s=None,w=2):
 return f'<circle cx="{x}" cy="{y}" r="{r}" fill="{f}"'+(f' stroke="{s}" stroke-width="{w}"' if s else '')+'/>'
def ellipse(x,y,rx,ry,f,s=None,w=2):
 return f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="{f}"'+(f' stroke="{s}" stroke-width="{w}"' if s else '')+'/>'
def rect(x,y,w,h,f,r=0,s=None):
 return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{f}"'+(f' stroke="{s}" stroke-width="2"' if s else '')+'/>'
def group(v,t='',**kw):return '<g'+(f' transform="{t}"' if t else '')+''.join(' %s="%s"'%(k.replace('_','-'),v) for k,v in kw.items())+'>'+v+'</g>'
def star(x,y,r=7,f='#f5db9c',points=4):
 ps=[]
 for i in range(points*2):
  an=i*math.pi/points-math.pi/2;rr=r if i%2==0 else r*.34
  ps.append(f'{x+math.cos(an)*rr:.2f},{y+math.sin(an)*rr:.2f}')
 return '<polygon points="'+' '.join(ps)+'" fill="'+f+'"/>'
def line(d,s='#f4deae',w=2):return path(d,'none',s,w)
def leaf(x=0,y=0,sc=1,rot=0,c='url(#leaf)'):
 return group(path('M0 0C-23-1-31-23-26-40C-5-37 10-17 0 0Z',c)+line('M-1-3L-20-31','#b8d597',1.5),f'translate({x} {y}) rotate({rot}) scale({sc})')
def cloud(c='url(#cloud)'):
 return path('M29 75C11 75 10 52 28 50C27 29 55 22 66 39C82 29 98 40 94 54C115 59 107 79 92 79H31Z',c,'#bcd0c5',1.2)+path('M26 56C31 50 38 51 42 54M43 42C47 34 57 35 60 40','none','#f2f6dd',3)
def flame(c='url(#flame)'):
 return path('M62 12C70 36 95 41 93 68C92 92 76 105 58 104C36 103 21 90 25 68C27 55 38 42 39 31C42 46 53 48 52 58C66 45 58 27 62 12Z',c,'#dca966',1)+path('M59 61C63 71 77 74 76 85C74 100 49 106 45 87C43 79 52 68 54 62L56 75Z','#ffe6a0')
def drop(c='url(#water)'):
 return path('M60 14C50 33 28 52 28 71A32 32 0 0 0 92 71C92 51 71 32 60 14Z',c,'#b2dfd8',1.4)+path('M42 66C37 81 44 88 52 91','none','#d4f9e8',4)+ellipse(69,76,13,16,'#b8eee5')
def rock(c='url(#stone)'):
 return path('M24 71L36 36L68 25L93 48L102 80L76 99L39 93Z',c,'#c3c2ad',1)+path('M36 36L55 63L68 25L72 65L93 48L81 87L39 93L55 63Z','#c4c4ab',opacity='.30')+line('M27 71L55 63L72 65L81 87','#e5dec0',1)
def gem(c='url(#violet)'):
 return path('M61 12L88 40L85 86L60 107L32 83L32 43Z',c,'#d8d8ee',1.3)+path('M61 12L53 47L60 107L32 83L32 43Z','#ffffff',opacity='.22')+path('M53 47L88 40L85 86L60 107Z','#192d5b',opacity='.23')+line('M32 43L53 47L88 40M61 12L53 47L60 107','#ffffff',1.1)
def bottle(c='url(#mint)',shape='round'):
 neck=rect(48,17,25,14,'#a78353',3)+line('M51 20L70 20','#d1b87c',2)
 if shape=='round': body=path('M45 30H76V47C108 70 94 104 60 105C23 106 11 71 45 47Z','#9dccbc', '#d8e9cc',1.8)+path('M32 73C43 67 73 83 87 71C93 87 80 99 60 99C38 99 28 90 32 73Z',c)
 else: body=path('M43 29H77V54L100 92Q103 103 90 104H30Q16 103 21 92L43 54Z','#638f82','#bbd4bc',1.8)+path('M38 70C53 75 65 65 81 71L94 95H26Z',c)
 return body+neck+path('M43 52C35 58 31 68 32 76','none','#e8f5d4',3)+circle(65,81,3,'#f0ebc3')+circle(53,91,2,'#f0ebc3')
def trunk(c='url(#wood)'):return path('M56 52H66L69 102H47L53 68Z',c)+line('M59 67L57 94','#d5b179',1.2)
def tree():return trunk()+path('M61 13L84 44H74L96 70H27L48 44H37Z','url(#leaf)','#99bd81',1)+path('M61 16L57 65H34L52 42H44Z','#b4c897',opacity='.3')
def flower(col='#e4a197'):
 return line('M59 96Q67 71 60 48','#688b4c',5)+leaf(61,80,.5,60)+''.join(ellipse(60+math.cos(a)*14,40+math.sin(a)*14,12,13,col) for a in [i*2*math.pi/5 for i in range(5)])+circle(60,40,10,'url(#gold)')
def house(c='url(#ochre)'):
 return path('M25 55H94V103H25Z',c,'#d9bb88',1)+path('M13 58L58 18L106 58H13Z','url(#roof)','#b79269',2)+rect(54,76,16,27,'#423c32',3)+rect(32,64,13,15,'#e9d997',2)+rect(78,64,11,14,'#e9d997',2)+line('M38 65V78M33 71H44','#746550',1.5)+line('M30 54L60 27L90 54','#e0b18a',2)
def book(c='url(#teal)'):
 return path('M23 26L83 18Q92 18 93 27V91L29 103Q17 103 18 91V35Q18 29 23 26Z',c,'#bdb581',1.5)+path('M29 90L91 80V92L30 103Q18 103 20 92Z','#e8d6ac')+line('M29 94L86 85M30 98L88 89','#a59a7b',1)+line('M30 32L30 83','#d3c293',2)+star(61,55,14)+line('M47 76L77 71','#d3c293',2)
def face(c='#d8b388',ears=False):
 v=ellipse(59,61,31,35,c,'#d7c5a2',1)
 if ears:v=path('M31 44L28 15L50 31L71 30L92 14L88 51Z',c,'#d7c5a2',1)+v
 return v+ellipse(48,59,3,5,'#293b32')+ellipse(73,59,3,5,'#293b32')+path('M56 73L63 73L60 78Z','#a47169')+line('M60 78Q54 84 49 78M60 78Q66 84 72 78','#4c4838',1.7)
def fish(c='url(#water)'):
 return path('M25 60L9 41V81Z',c,'#b7d5bf',1)+path('M23 59Q59 21 100 59Q60 98 23 59Z',c,'#b7d5bf',1.5)+path('M48 44L63 26L75 41M45 76L61 90L74 77',c,'#b7d5bf',1)+circle(84,55,5,'#efeed3')+circle(85,55,2,'#243d3a')+line('M72 47Q65 62 74 71','#c2dfca',2)+path('M42 57l5 5-5 5M54 51l5 5-5 5M55 67l5 5-5 5','none','#c2dfca',1.5)
def bird(c='url(#teal)'):
 return path('M22 76L8 58L26 61Q23 27 53 29Q81 31 88 48L109 53L92 63Q83 96 46 90Z',c,'#a2c4ac',1.3)+path('M35 51Q75 37 67 68Q54 78 35 51Z','#8fb8aa')+path('M92 47L111 54L92 60Z','#dab775')+circle(82,44,3,'#26392f')+line('M49 89L45 105M59 90L59 105M40 105H51M54 105H65','#c8a16c',2.5)
def monitor():return rect(18,22,84,62,'url(#metal)',6,'#cdd1b6')+rect(25,29,70,45,'#254743',3)+line('M51 87V96H38M69 87V96H83','#c2c5ab',5)+line('M39 96H83','#c2c5ab',5)+path('M36 46l8 6-8 6M52 59H69','none','#a0d0a5',3)
def mushroom(c='url(#roof)'):
 return path('M51 57H70L77 99Q60 107 43 99Z','url(#cream)')+path('M13 62C21 5 96 5 106 62Q60 79 13 62Z',c,'#d8b799',1.3)+ellipse(59,64,45,9,'#cdba8e')+ellipse(44,41,8,9,'#f0dab0')+ellipse(75,32,7,6,'#f0dab0')+ellipse(87,53,6,5,'#f0dab0')
def wheat():
 return line('M54 106L61 20','#b29a5d',3)+''.join(group(ellipse(0,0,6,13,'url(#gold)'),f'translate({x} {y}) rotate({r})') for x,y,r in [(52,34,-35),(70,44,35),(51,52,-40),(68,63,40),(49,72,-40),(65,83,40)])
def sparkle_ring():return star(21,27,6)+star(92,23,4)+star(103,79,6)
# Four originals; intentionally larger and more detailed than generic UI symbols.
A['water']=drop()+star(91,27,5,'#badfd4')
A['fire']=flame()+star(91,29,5,'#f2bf7e')
A['earth']=path('M18 54L55 28L102 48L71 79L34 75Z','url(#leaf)','#bdd28c',1)+path('M18 54L34 75L71 79L102 48L89 86L59 106L28 88Z','url(#earth)','#b5aa71',1)+path('M34 75L59 106L71 79Z','#98704c')+line('M48 77l7 10-3 6M77 74l-4 16M34 79l5 9','#d0af75',2)+leaf(61,45,.52,18)+leaf(63,45,.33,98)+ellipse(35,53,7,3,'#a3c276')
A['air']=line('M13 48H73C96 48 96 19 79 20C69 21 68 33 74 35M18 62H93C117 62 113 89 94 87C86 86 85 79 89 75M30 76H64Q79 76 74 91M10 34H52','#c3dbd1',6)+leaf(42,98,.38,80)
A['mud']=ellipse(61,80,49,18,'url(#earth)')+ellipse(64,74,39,12,'#9c8161')+ellipse(40,66,16,10,'#90765c')+ellipse(44,64,10,5,'#b09a72')+circle(77,64,5,'#c1a67b')+leaf(82,74,.35,30)
A['dust']=''.join(circle(x,y,r,c) for x,y,r,c in [(20,71,4,'#cfb893'),(30,55,7,'#b29d7d'),(47,69,11,'#bca787'),(59,51,13,'#d2bc91'),(76,67,14,'#9d9479'),(93,62,6,'#b9ae8a'),(44,38,4,'#cdbb96'),(87,36,3,'#b7ae8e')])+line('M17 91Q55 85 96 88','#9b9e83',3)
A['sand']=path('M9 85L53 40L83 77L102 65L114 88Q58 109 9 85Z','url(#gold)')+path('M53 40L62 85L83 77Z','#a38d5a')+path('M17 87Q58 92 102 86','none','#f1dba6',2)+''.join(circle(x,y,1.3,'#eee0b4') for x,y in [(48,74),(30,81),(40,68),(63,88),(71,94),(84,85)])
A['plant']=line('M62 103C53 82 70 56 64 27','#9cbc79',5)+leaf(61,67,.85,-3)+leaf(60,85,.73,95)+ellipse(60,104,29,5,'#9c8b60')
A['tree']=tree()
A['forest']=group(tree(),'translate(-13 18) scale(.75)')+group(tree(),'translate(42 15) scale(.75)')+group(tree(),'translate(10 0) scale(.9)')
A['seed']=path('M34 84C8 56 55 38 87 30C88 68 69 112 34 84Z','url(#wood)','#cfb992',2)+path('M36 79Q67 74 86 32','none','#edd7a4',2)+leaf(86,33,.4,40)
A['algae']=line('M39 104Q64 79 37 64Q18 43 40 22M68 103Q82 81 66 63Q46 41 68 27M87 103Q98 79 90 55','#80b98c',7)+line('M36 82Q19 81 17 65M66 72Q86 64 83 49','#b2ce90',4)+circle(26,32,4,'none','#a6d8c6',1)+circle(93,28,6,'none','#a6d8c6',1)
A['grass']=''.join(path(d,'url(#leaf)') for d in ['M32 101Q12 68 17 39Q44 72 44 101Z','M44 101Q35 56 57 19Q52 64 57 101Z','M54 101Q69 44 94 34Q75 68 67 101Z','M75 101Q82 74 108 63Q91 91 88 101Z'])+ellipse(58,103,42,5,'#73835a')
A['swamp']=ellipse(59,86,49,16,'#607d5c')+ellipse(58,82,42,9,'#829d79')+ellipse(44,78,17,5,'#b2c784')+line('M22 80L27 34M91 81L89 37','#aab780',3)+rect(21,27,10,28,'#9b8661',5)+rect(84,26,10,24,'#9b8661',5)+circle(73,69,5,'none','#9bb192',2)
A['mountain']=path('M6 100L45 29L64 55L80 20L114 100Z','url(#stone)','#bbbba0',1)+path('M80 20L82 100H114Z','#667572')+path('M45 29L64 55L60 67L46 54L37 62L30 55Z','#d9dfcb')+path('M80 20L96 59L84 48L76 52L66 45Z','#e6e6d0')
A['desert']=circle(83,35,20,'url(#gold)')+path('M4 88Q34 42 72 78Q95 72 117 94L117 107H4Z','url(#gold)')+path('M5 103Q64 52 118 96V107Z','#c2a370')+line('M28 79V51M28 65H20V56M28 71H36V61','#6a9069',5)
A['sky']=circle(76,34,20,'url(#gold)')+group(cloud(),'translate(-5 14) scale(.9)')+star(99,22,4)
A['night']=circle(60,60,45,'url(#night)')+path('M74 22A31 31 0 1 0 93 70A34 34 0 0 1 74 22Z','url(#cream)')+star(36,30,5)+star(26,68,4)+star(53,77,3)
for i in ['ocean','sea','lake','river','beach','island']:
 if i=='ocean':v=path('M13 95C14 69 50 71 66 49C81 28 48 30 45 48C45 13 98 15 105 58C113 83 85 103 59 103Z','url(#water)','#b3ddd4',1.5)+path('M17 91C23 76 51 80 74 59Q96 41 72 25Q111 36 98 70Q76 99 17 91Z','#cee5d1')
 elif i=='sea':v=''.join(path(f'M10 {y}Q23 {y-14} 37 {y}T65 {y}T94 {y}T119 {y}', 'none',c,8) for y,c in [(45,'#a1d0c5'),(66,'#75b2b7'),(87,'#568f9c')])
 elif i=='lake':v=ellipse(60,83,50,22,'#6d8965')+ellipse(60,77,44,17,'url(#water)')+path('M18 73Q55 80 92 71','none','#c2ded0',2)+group(tree(),'translate(3 3) scale(.62)')
 elif i=='river':v=path('M9 105L12 39Q42 32 60 41Q86 30 110 40L112 103Z','#81976a')+path('M65 35C20 48 98 65 45 79Q29 89 45 108H94C51 87 103 82 100 63Q95 45 73 35Z','url(#water)')+line('M66 48Q93 63 74 70M57 89Q53 98 70 103','#d4e4c6',2)
 elif i=='beach':v=ellipse(60,82,51,24,'url(#water)')+path('M12 80Q60 48 99 70Q68 80 56 105Q29 103 12 80Z','url(#gold)')+path('M18 78Q53 57 97 69','none','#ede0b6',4)+star(41,88,9,'#cf9a77',5)
 else:v=ellipse(60,88,51,19,'url(#water)')+ellipse(59,80,37,15,'url(#gold)')+path('M55 77Q69 51 64 31','none','#b39966',7)+''.join(group(leaf(0,0,.7,a),f'translate(65 36)') for a in [-40,30,90,160,230])
 A[i]=v
A['volcano']=path('M8 100L41 42H74L110 100Z','url(#earth)','#b9a783',1)+ellipse(58,42,18,6,'#dda563')+path('M48 42L58 80L65 59L70 86L78 83L68 42Z','url(#flame)')+line('M53 29Q39 20 51 8M69 28Q84 15 71 9','#adb69e',6)
A['soil']=path('M15 55L59 36L105 54L95 90L60 107L26 91Z','url(#earth)')+ellipse(59,56,46,15,'#7f9060')+leaf(62,46,.54,14)+line('M60 66L54 83L59 98M55 80L43 76M57 91L77 81','#d6b67f',2)+circle(82,73,3,'#ae9e7f')
A['steam']=line('M29 80Q14 63 31 49Q46 34 32 20M60 86Q42 65 62 48Q78 31 63 14M88 79Q75 64 88 49Q102 34 89 25','#c0d6cb',7)+ellipse(61,103,37,4,'#90afa6')
A['cloud']=cloud()
A['rain']=group(cloud(),'translate(8 -2) scale(.85)')+line('M36 82L30 96M59 85L53 99M82 81L76 95','#87bbb6',4)
A['smoke']=group(cloud('#7f9590'),'translate(6 -3) scale(.9)')+path('M46 75Q57 88 40 104Q78 92 75 72Z','#a6b8a6')
A['storm']=group(cloud('#839c98'),'translate(7 -6) scale(.85)')+path('M59 64L45 88H60L54 112L80 78H65L73 64Z','url(#gold)')+line('M34 80L28 94M91 79L86 93','#8bbbb8',3)
A['lightning']=path('M64 7L23 67H53L45 114L99 47H70L87 7Z','url(#gold)','#eddfa9',1.5)+path('M64 10L51 54H31L56 23Z','#fff0bc')
A['energy']=circle(60,62,46,'#b49b56')+circle(60,62,40,'#343f36')+group(A['lightning'],'translate(14 17) scale(.74)')+star(102,25,6)+star(20,92,4)
A['snow']=group(cloud(),'translate(8 -7) scale(.85)')+''.join(line(f'M{x-5} {y}H{x+5}M{x} {y-5}V{y+5}M{x-4} {y-4}L{x+4} {y+4}M{x+4} {y-4}L{x-4} {y+4}','#c5e0d1',1.8) for x,y in [(32,89),(59,95),(86,87)])
A['fog']=group(cloud(),'translate(0 -5)')+line('M14 84H103M26 96H87M6 71H37','#afc7b4',4)
A['rainbow']=''.join(path(f'M{x} 95A{60-x} {60-x} 0 0 1 {120-x} 95','none',c,9) for x,c in [(13,'#d29382'),(22,'#dbb071'),(31,'#dbcf8c'),(40,'#83aa82'),(49,'#7badae')])+group(cloud(),'translate(-6 68) scale(.36)')+group(cloud(),'translate(77 68) scale(.36)')
A['wind']=A['air']+leaf(102,103,.28,132)
A['hurricane']=''.join(path(f'M{22+i*7} {25+i*15}Q{60} {15+i*15} {105-i*8} {25+i*15}Q{62} {39+i*15} {31+i*7} {30+i*15}','none',c,5) for i,c in enumerate(['#cad8c8','#abc5b8','#8eaca5','#76928b','#65857e']))
A['dew']=leaf(69,109,1.5,-9)+group(drop(),'translate(21 21) scale(.64)')
A['blizzard']=A['snow']+line('M8 38H60M5 51H40M16 64H53','#cbdccb',3)
A['flower']=flower()
A['mushroom']=mushroom()
A['bacteria']=group(rect(30,28,59,66,'url(#leaf)',28,'#bed697')+''.join(circle(x,y,r,'#c7d997') for x,y,r in [(46,47,5),(65,70,7),(70,45,3),(44,76,3)]),'rotate(28 60 60)')+''.join(line(f'M{x} {y}l{dx} {dy}','#8fb781',3) for x,y,dx,dy in [(30,30,-8,-8),(22,56,-10,0),(34,90,-5,8),(70,23,3,-10),(93,58,10,0),(84,88,8,9)])
A['fish']=fish()
A['bird']=bird()
A['animal']=face('#c29467',True)+path('M27 59Q32 93 60 96L44 70ZM89 58Q88 92 60 96L76 71Z','#f1d6a6')+ellipse(48,59,3,5,'#283b31')+ellipse(73,59,3,5,'#283b31')+path('M54 78L66 78L60 84Z','#394334')
A['human']=path('M23 108Q23 76 60 76Q96 76 97 108Z','url(#teal)','#a5c4a5',1)+ellipse(60,49,24,29,'url(#skin)')+path('M35 45Q26 12 58 11Q92 10 86 43L74 29Q49 42 35 36Z','url(#earth)')+circle(51,50,2,'#404336')+circle(71,50,2,'#404336')+line('M52 66Q60 71 69 64','#865d4b',2)
A['lizard']=path('M91 74Q123 99 83 105Q67 107 62 89L53 66Q27 70 18 55Q6 36 28 30Q49 21 53 46L72 68Q93 86 97 97Q109 85 91 74Z','url(#leaf)','#b8d095',1)+circle(27,38,6,'#e5dbae')+circle(28,38,3,'#283d30')+line('M52 56L74 44L81 49M53 59L37 77L28 76M65 79L57 99L46 103','#9ebb7b',7)+line('M28 47L16 49','#688356',1.5)
A['horse']=path('M31 94L33 71L44 50L52 20L81 23L98 49L84 61L73 48L73 100Z','url(#wood)','#d0b58c',1.5)+path('M50 24L40 54L29 74L38 41L46 23L59 13Z','#6c6048')+path('M61 24L58 10L71 25Z','#c8a16e')+circle(76,35,3,'#2b3c30')+line('M78 51L85 55','#5d5542',2)
A['heart']=path('M60 103C35 83 12 67 14 42C16 12 47 9 60 34C76 9 106 15 107 43C108 66 81 88 60 103Z','url(#rose)','#dcab96',1.5)+path('M27 41Q31 23 45 32','none','#f3d0b5',4)
A['blood']=drop('url(#rose)')
A['wound']=group(rect(15,40,91,38,'url(#skin)',14,'#dfc6a2')+rect(44,44,31,30,'#ecdbc0',5)+''.join(circle(x,y,1.5,'#b39370') for x,y in [(25,52),(34,52),(25,65),(34,65),(86,52),(95,52),(86,65),(95,65)]),'rotate(-35 60 60)')
A['egg']=path('M60 15C43 15 23 53 23 74C23 116 97 116 97 74C97 53 77 15 60 15Z','url(#cream)','#cfbf95',1.5)+ellipse(47,64,11,24,'#fff0d0')+circle(74,87,4,'#caba93')+circle(78,73,2,'#caba93')
A['insect']=ellipse(59,65,28,34,'url(#leaf)')+circle(59,31,15,'#647d51')+line('M59 44V96M33 51L18 40M30 65H13M34 83L21 95M85 51L102 40M89 66H106M85 83L99 96','#bccb97',3)+circle(53,29,3,'#e1dcb5')+circle(66,29,3,'#e1dcb5')+circle(47,61,5,'#516c4a')+circle(73,77,5,'#516c4a')
A['bee']=ellipse(46,37,17,26,'#bfdfce')+ellipse(78,39,17,26,'#dfedce')+ellipse(61,70,34,25,'url(#gold)')+path('M49 46Q40 69 49 94M70 47Q63 73 70 95','none','#5c5c3b',9)+circle(87,66,13,'#647456')+circle(91,63,3,'#eee2ad')+path('M27 64L14 72L28 77Z','#d1b774')
A['butterfly']=path('M57 52C15-5-4 52 32 69C0 107 43 121 58 77L64 78C92 129 123 83 84 66C120 21 76 4 63 50Z','url(#rose)','#d9bd98',1)+ellipse(60,68,6,29,'#65724f')+line('M58 43L47 26M63 43L75 26','#b8c894',2)+ellipse(35,51,10,16,'#e3bc86')+ellipse(84,50,10,16,'#e3bc86')+circle(36,89,6,'#ecd2a2')+circle(87,88,6,'#ecd2a2')
A['cat']=face('#9eafa2',True)+path('M48 30l4 12M62 28v13M75 31l-5 11','none','#566e63',3)+line('M26 72H9M27 79L11 86M91 72H111M90 79L108 86','#e6dcc0',2)
A['mouse']=circle(30,36,22,'#abb3a2')+circle(91,36,22,'#abb3a2')+circle(30,36,14,'#d5aaa0')+circle(91,36,14,'#d5aaa0')+face('#b6bca6')+line('M32 78L13 73M32 83L14 88M87 78L108 73M87 83L106 90','#dddec0',2)
A['dog']=ellipse(31,52,14,31,'#8b6f4c')+ellipse(89,52,14,31,'#8b6f4c')+face('#c4ac7e')+path('M58 82Q49 108 67 106Q79 101 68 82Z','#d39987')+line('M63 90V102','#a56e67',1.5)
A['wolf']=face('#82968c',True)+path('M29 53L14 73L34 76L25 88L47 88L59 102L75 87L98 89L88 74L106 69L89 51L73 75L60 87L47 73Z','#cad0b1')+ellipse(47,59,4,4,'#d6bd72')+ellipse(73,59,4,4,'#d6bd72')+path('M53 80H67L60 89Z','#324c41')
A['turtle']=ellipse(58,75,36,25,'url(#leaf)','#bdcf9e',1.5)+circle(100,69,12,'#a4bb80')+circle(103,66,2,'#354e3a')+ellipse(34,98,12,7,'#8da87a')+ellipse(79,98,12,7,'#8da87a')+ellipse(35,52,10,6,'#8da87a')+line('M49 52L43 70L59 86L80 74L75 53M43 70L24 75M59 86L58 100M80 74L91 77','#d3d8a5',2)
A['coral']=line('M56 106V34M56 77L31 63V31M56 66L81 51V25M31 52L17 40V27M81 41L99 32V20M56 89L87 81L100 63','#d69786',8)+line('M37 65L37 89M59 51L69 37','#e9b39a',5)+ellipse(60,106,36,5,'#87987e')
A['whale']=path('M15 66C19 30 72 31 82 53Q92 68 104 50L115 43L112 68L99 80Q62 110 26 88Z','url(#water)','#c1d9c4',1)+path('M19 72Q58 99 96 77Q44 117 19 72Z','#ccd9bd')+path('M58 68L62 95L81 83Z','#719fa6')+circle(30,62,3,'#283f35')+line('M45 28V11M45 18L35 12M45 19L56 9','#bad4c5',3)
A['dinosaur']=path('M15 88Q46 90 48 65L46 31Q52 7 82 16L102 25L101 45L74 47L80 67L100 81L89 90L69 80L68 108H53L51 89Q28 105 15 88Z','url(#leaf)','#c4d398',1.3)+path('M47 27L34 34L46 45L35 55L47 65L36 73L45 81Z','#d3b573')+circle(81,27,3,'#314633')+line('M76 37H99','#527352',2)
A['dragonfly']=ellipse(38,48,29,10,'#b8d7c2')+ellipse(84,49,28,10,'#b8d7c2')+ellipse(32,67,26,9,'#9bbfb2')+ellipse(85,69,25,9,'#9bbfb2')+path('M57 46L66 46L63 107L59 113Z','url(#teal)')+circle(61,39,10,'#8bab83')+circle(55,36,5,'#cfdaaa')+circle(67,36,5,'#cfdaaa')+line('M57 63H65M57 75H64M58 88H64','#cad6a8',2)
A['lava']=rock('url(#earth)')+line('M39 38L54 61L41 78L46 94M54 61L79 50L93 64M79 50L71 31M74 66L65 80L81 91','#e2a267',5)+line('M39 38L54 61L41 78M54 61L79 50L93 64','#f3d490',2)
A['stone']=rock()
A['clay']=ellipse(60,88,44,16,'url(#ochre)')+ellipse(60,72,34,16,'#bd956c')+ellipse(60,57,24,14,'#cfa67d')+ellipse(60,42,16,10,'#dcbb92')+line('M40 88Q60 95 86 85','#ebc59b',2)
A['ice']=path('M23 40L66 22L101 39V88L59 105L23 88Z','url(#glass)','#d6eee2',2)+path('M23 40L60 58L101 39M60 58V104','none','#e6f2d8',2)+line('M31 53L50 76M75 60L91 51M76 71L91 63','#b7e4dd',3)+star(95,22,6,'#e3efe1')
A['glass']=path('M25 27L82 13L95 90L40 109Z','url(#glass)','#d4e7ce',2)+path('M32 32L47 28L84 94L70 99Z','#d9efdc',opacity='.4')+line('M75 25L85 77','#f1f2d9',2)+star(93,18,5)
A['metal']=path('M17 65L35 42H87L108 77L96 92H20Z','url(#metal)','#d1cfad',1.5)+path('M17 65L92 67L108 77M92 67L87 42M92 67L96 92','none','#edf0ce',1.5)
A['gold']=path('M14 74L32 44H90L108 74L91 98H22Z','url(#gold)','#f5d99d',1.2)+path('M14 74H89L108 74M89 74L90 44M89 74L91 98','none','#f6e8b8',1.5)+star(85,25,7)+star(21,34,4)
A['wood']=path('M20 53L78 20L103 69L47 104Z','url(#wood)','#cdb78d',1)+ellipse(34,77,22,29,'#d0b081','#806b46',2)+ellipse(34,77,14,20,'none','#9f8556',2)+ellipse(34,77,7,11,'none','#ab8d5f',2)+line('M54 73L91 47M47 58L82 37M59 85L99 62','#deb986',2)
A['coal']=rock('url(#coal)')+path('M49 51L56 58L45 69L49 79M82 44L76 68','none','#8b9d88',2)
A['diamond']=path('M15 43L34 20H86L106 43L60 106Z','url(#glass)','#d8e9d7',1.4)+path('M15 43H106M34 20L46 43L60 106L78 43L86 20M46 43L60 20L78 43','none','#eef7d9',1.4)+star(104,23,6)
A['ash']=ellipse(59,86,48,15,'#858e7e')+path('M13 81L32 69L45 49L59 57L80 43L102 80Z','url(#stone)')+line('M47 27Q61 17 54 7M72 31Q87 20 81 12','#a3b29b',3)+circle(24,50,2,'#d0ccad')
A['mineral']=group(rock(),'translate(-8 20) scale(.86)')+group(gem(),'translate(51 21) scale(.48)')
A['crystal']=group(gem(),'translate(-1 24) scale(.62)')+group(gem(),'translate(39 26) scale(.66)')+group(gem(),'translate(12 0) scale(.83)')+star(100,20,6)
A['copper']=path('M17 65L35 42H87L108 77L96 92H20Z','url(#copper)','#e9bf93',1.5)+line('M18 65H92L87 42M92 65L96 92','#eed1a5',2)+circle(38,42,18,'url(#copper)','#e7c197',1)+circle(38,42,9,'none','#8f674d',2)
A['steel']=A['metal']+line('M40 50L65 50M35 77H69','#bccbbb',3)+star(94,26,5)
A['paper']=path('M26 18H77L96 39V104H26Z','url(#cream)','#cabb96',1.5)+path('M77 18V39H96Z','#b9b58e')+line('M40 54H80M40 64H78M40 74H80M40 84H63','#acac85',2)
A['thread']=rect(32,29,56,65,'#d5c69a',8)+ellipse(60,29,33,11,'#bdaf87')+ellipse(60,93,33,11,'#c4b88f')+rect(35,34,50,53,'url(#rose)',5)+line('M38 43H82M38 52H82M38 61H82M38 70H82M38 79H82M84 68Q111 84 98 111','#edd2b3',2)+ellipse(60,27,12,4,'#8c825e')
A['fabric']=path('M28 23L98 31L87 106L54 101L41 84L17 85Z','url(#teal)','#c5d1a9',1.5)+line('M45 30L33 78L49 82L59 96M89 39L78 96M28 49L90 59M24 67L86 76','#d2d8b0',1.5)+line('M41 26L38 39M66 32L52 89M85 38L72 99','#809d83',1)
A['brick']=path('M12 59L64 34L108 50V84L56 109L12 91Z','url(#roof)','#e0bb96',1.2)+path('M12 59L56 78L108 50M56 78V109','none','#f0c69e',2)+ellipse(62,49,9,4,'#8e634b')+ellipse(81,57,9,4,'#8e634b')+line('M21 74L46 84M70 91L99 77','#b88b68',2)
A['obsidian']=gem('url(#coal)')+path('M59 20L70 45L58 84L66 93M40 49L53 47','none','#8c86ab',2)
A['oil']=drop('url(#coal)')+path('M42 60Q56 44 72 60','none','#8f8896',4)
A['rubber']=ellipse(59,63,42,44,'#445747','#839480',2)+ellipse(59,63,19,23,'#273c30','#a8b598',3)+line('M30 33L39 39M18 59L30 61M26 88L36 84M49 106L50 94M84 98L76 89M100 68L88 67M90 37L80 44','#829077',4)
A['plastic']=path('M40 44L49 35V23H74V36L83 47V97Q59 112 34 97V53Z','url(#water)','#bedac2',1.4)+rect(46,17,31,13,'#b7c39b',3)+path('M36 66Q59 75 82 65V84Q58 94 35 84Z','#c5d3ac')+line('M44 50V60M44 93V98','#e0e2b7',2)
A['silicon']=path('M25 27H96L85 104H15Z','url(#night)','#bfcdab',1.5)+''.join(line(f'M{x} 32L{x-9} 99','#91b8a2',1) for x in [40,55,70,85])+''.join(line(f'M23 {y}H{97-int(y/10)}','#91b8a2',1) for y in [44,59,74,89])+star(96,21,5)
A['life']=path('M60 97C31 84 30 54 60 16C94 57 96 82 60 97Z','url(#mint)','#cde7ad',1)+path('M60 99V42M60 69L43 57M60 83L79 62','none','#ecedbc',3)+sparkle_ring()
A['time']=path('M31 22H89V31Q89 47 66 59Q89 74 89 90V99H31V90Q31 74 54 59Q31 47 31 31Z','url(#glass)','#d9d3ae',1.5)+path('M34 34H87L60 57Z','url(#gold)')+path('M36 93L60 70L86 93Z','url(#gold)')+rect(23,13,74,10,'url(#wood)',3)+rect(23,98,74,10,'url(#wood)',3)+line('M60 57V68','#ead395',2)
A['light']=circle(60,53,30,'url(#gold)','#eddfad',2)+path('M43 76H77L73 94H47Z','url(#metal)')+rect(49,96,22,9,'#96a88c',4)+line('M57 83V58L48 47M64 83V57L74 46','#fcf1c2',3)+line('M60 6V13M15 27L24 31M99 27L107 21M9 58H18M103 58H112','#d6c27f',3)
A['darkness']=circle(60,61,41,'url(#night)','#8e99b1',1.5)+path('M71 22A39 39 0 0 1 43 95A38 38 0 0 0 71 22Z','#52577a')+star(23,20,5,'#b8bbc3')
A['sound']=path('M16 48H35L60 26V97L35 74H16Z','url(#wood)','#d4c296',1.5)+line('M75 43Q96 61 75 80M87 29Q120 61 87 94','#bbd1ad',5)
A['thought']=group(cloud('url(#violet)'),'translate(2 -3)')+circle(30,94,7,'#b3b8b7')+circle(17,107,4,'#b3b8b7')+star(65,56,14)
A['heat']=group(flame(),'translate(-7 12) scale(.75)')+line('M90 17V94','#cebda0',13)+line('M90 51V94','#d4926f',7)+circle(90,96,14,'url(#flame)','#dbbd8e',2)+line('M98 26H108M98 42H106M98 58H108','#bfc5a2',2)
A['cold']=line('M60 13V106M19 36L100 83M19 83L100 36M44 24L60 36L77 24M44 96L60 83L77 95M18 53L35 46L36 26M84 96L84 75L104 69M17 69L35 75L34 96M86 26L84 47L104 54','#b9ddd0',4)+circle(60,60,8,'#dbead1')
A['pressure']=rect(25,12,69,10,'url(#metal)',3)+rect(27,96,67,11,'url(#metal)',3)+line('M32 21V96M88 21V96','#809a88',5)+path('M53 28H67V47H81L60 68L38 47H53Z','url(#gold)')+group(rock(),'translate(35 57) scale(.43)')
A['gravity']=circle(60,81,22,'url(#water)')+path('M53 12H67V45H80L60 68L39 45H53Z','url(#gold)')+ellipse(61,84,48,12,'none','#a5bba1',2)
A['magnetism']=path('M24 24H44V69Q44 87 60 86Q76 86 76 68V24H96V71C96 117 22 117 24 71Z','url(#rose)','#d5b896',1.5)+rect(23,19,22,22,'url(#metal)',2)+rect(75,19,22,22,'url(#metal)',2)+line('M49 22Q60 13 71 22M48 34Q60 27 71 34','#d0cea0',2)
A['explosion']=path('M61 4L69 35L100 14L90 47L117 55L91 69L111 98L77 87L65 115L50 86L18 108L27 72L3 61L31 48L17 15L50 34Z','url(#flame)')+star(61,62,30,'#f1dc99',8)
A['plasma']=circle(60,60,39,'url(#violet)','#d3c8c8',2)+line('M28 46L47 54L48 28L60 57L80 33L69 61L95 77L62 69L52 94L52 69L26 84','#e6dfb9',2)+circle(61,62,9,'#fae8b1')
A['acid']=bottle('url(#mint)','flask')
A['base']=bottle('url(#water)','flask')+line('M48 84H71M60 74V94','#edf0c9',3)
A['salt']=path('M35 40H87L94 99Q60 111 27 99Z','url(#glass)','#dfdfbf',1)+path('M33 72L89 68L91 98Q60 108 31 98Z','#e7e3c5')+rect(34,23,54,21,'url(#metal)',5)+circle(48,31,2,'#687967')+circle(61,30,2,'#687967')+circle(75,31,2,'#687967')
A['alcohol']=bottle('url(#gold)')+rect(44,70,33,25,'#e9d7b0',4)+leaf(65,91,.45,0)
A['gas']=cloud('url(#mint)')+circle(27,99,6,'none','#b9cfaa',2)+circle(80,20,5,'none','#b9cfaa',2)+circle(99,96,4,'none','#b9cfaa',2)
A['radioactivity']=circle(60,61,44,'url(#gold)','#e4d7ab',2)+circle(60,61,9,'#3c5140')+''.join(group(path('M52 43L40 22A45 45 0 0 1 81 22L68 43Z','#3c5140'),f'rotate({r} 60 61)') for r in [0,120,240])
A['fruit']=path('M61 40Q41 23 23 46C-1 84 47 121 60 102C81 120 122 75 97 44Q82 30 61 40Z','url(#rose)','#dfb39b',1)+line('M60 44Q52 28 66 17','#9baa73',5)+leaf(68,29,.5,95)+line('M28 56Q20 72 35 83','#f0cdb0',3)
A['vegetable']=path('M49 37L84 54Q62 88 29 111Q31 74 49 37Z','url(#flame)','#e2c28e',1)+line('M45 67L54 73M39 84L46 89M59 55L69 61','#d0875d',2)+leaf(64,45,.65,-5)+leaf(64,45,.56,75)+leaf(64,45,.5,140)
A['meat']=path('M18 73C2 40 47 22 75 32C115 38 106 82 86 88C70 92 70 110 45 100C33 96 21 86 18 73Z','url(#rose)','#e4c6ac',5)+path('M30 59Q59 34 80 47Q93 64 77 70Q53 66 51 88Q24 85 30 59Z','none','#e8b9a6',3)+ellipse(80,51,9,7,'#efd7b6')
A['bread']=path('M16 60Q11 30 33 33Q39 12 64 24Q87 13 99 37Q115 48 104 64V98Q63 114 18 98Z','url(#bread)','#c1a577',1.5)+path('M28 62H94V94Q60 105 27 94Z','#ecd1a0')+circle(46,75,3,'#c5ad7a')+circle(74,86,4,'#c5ad7a')+circle(62,69,2,'#c5ad7a')
A['cheese']=path('M15 66L84 29L105 61V98L15 103Z','url(#gold)','#e6ce94',1.5)+path('M15 66L105 61M83 30L84 63','none','#f5dfaa',2)+ellipse(58,52,9,4,'#b59b5c')+ellipse(39,80,9,7,'#b39a5d')+circle(79,85,6,'#b39a5d')+circle(97,70,3,'#b39a5d')
A['soup']=ellipse(60,56,47,18,'#cdbb8e')+path('M13 55Q20 108 60 108Q101 108 107 55Z','url(#teal)','#b7bfa0',1.3)+ellipse(60,54,42,13,'#c1945d')+leaf(55,58,.28,55)+circle(76,50,5,'#d6aa68')+circle(39,53,4,'#b7b470')+line('M43 32Q35 23 45 14M66 29Q56 17 68 8','#bcc5a9',3)
A['cake']=path('M20 58H100V96Q60 111 20 96Z','url(#bread)')+path('M20 65Q28 82 36 67Q48 86 56 67Q68 80 76 65Q86 83 100 64V85Q61 99 20 85Z','#e5b1a0')+ellipse(60,58,40,15,'#e3d8b4')+line('M39 50V27M61 46V19M82 51V28','#a8baa0',5)+group(flame(),'translate(31 9) scale(.14)')+group(flame(),'translate(53 1) scale(.14)')+group(flame(),'translate(74 10) scale(.14)')
A['wheat']=wheat()
A['milk']=path('M32 37L46 14H79L92 36V106H32Z','url(#cream)','#d8d2ad',1.5)+path('M32 37H92M46 14L58 36V106M58 36L79 14','none','#98b7a3',2)+path('M58 51H92V87H58Z','url(#water)')+group(drop(),'translate(63 57) scale(.2)')
A['flour']=path('M35 24H88L80 47Q111 96 85 108H33Q10 96 42 47Z','url(#cream)','#cfc299',1.5)+line('M38 41H82M39 47H81','#9caa7d',4)+group(wheat(),'translate(39 54) scale(.37)')
A['dough']=ellipse(60,91,49,17,'#bda47b')+path('M16 86C11 31 100 30 104 79Q107 105 61 104Q21 106 16 86Z','url(#cream)')+line('M34 67Q50 55 62 67M68 66Q82 57 90 72','#c9b890',3)+circle(32,94,2,'#fbebc7')
def cup(c='url(#teal)',drink='#8c6644'):
 return path('M87 44C119 34 122 80 88 84','none','#bcb78c',9)+path('M22 40H90V78Q89 105 57 105Q22 103 22 78Z',c,'#c5cba6',1.5)+ellipse(56,42,34,11,'#e0d9b3')+ellipse(56,43,29,8,drink)+ellipse(56,105,48,6,'#afae88')+line('M42 23Q31 12 42 5M68 25Q55 13 67 6','#b9c7aa',2.5)
A['tea']=cup()+leaf(58,83,.44,30)
A['coffee']=cup('url(#ochre)','#473f32')+ellipse(57,72,10,15,'#7f684a')+line('M61 60Q50 70 61 83','#e5c19a',2)
A['honey']=path('M37 32H85V47Q97 55 95 88Q96 106 60 106Q26 106 25 88Q24 55 37 47Z','url(#gold)','#d8c793',1.5)+rect(32,20,59,15,'url(#wood)',4)+rect(33,64,54,26,'#e8d4a3',8)+group(leaf(0,0,.45,40), 'translate(62 89)')+line('M40 47V58','#f5e3b7',3)
A['chocolate']=group(rect(23,18,74,87,'#79624b',4,'#ccb08a')+''.join(rect(x,y,28,21,'#9b7754',3,'#5d5240') for x in [29,63] for y in [25,52,79])+path('M23 76L97 88V105H23Z','#abb6a0'),'rotate(10 60 60)')
A['cookie']=circle(60,62,43,'url(#bread)','#d3bc8f',2)+''.join(path(f'M{x-4} {y-4}l8 1 1 7-9 1Z','#765d41') for x,y in [(46,38),(78,45),(34,65),(61,65),(78,83),(49,89)])+circle(60,62,37,'none','#deb985',1)
A['pizza']=path('M21 27Q66 6 105 40L58 110Z','url(#gold)','#d4b07d',1.5)+path('M21 27Q66 6 105 40','none','#b88654',13)+path('M25 30Q66 13 99 40','none','#ddb078',5)+circle(56,44,9,'#b67860')+circle(76,61,9,'#b67860')+circle(55,83,7,'#b67860')+leaf(40,57,.22,55)+leaf(78,39,.21,0)
A['tool']=path('M30 109L20 99L74 41L84 51Z','url(#wood)','#ccb385',1.5)+path('M58 15L108 49L96 67L47 34Z','url(#metal)','#d6d5b2',1.5)+line('M32 98L76 49','#e0bd87',2)
A['wheel']=circle(60,61,45,'url(#wood)','#c7af7d',2)+circle(60,61,33,'#34483a','#d2b580',5)+''.join(group(line('M60 27V95','#c3a477',6),f'rotate({a} 60 61)') for a in [0,60,120])+circle(60,61,10,'url(#metal)','#d0c397',2)
A['electricity']=rect(24,36,71,63,'url(#teal)',7,'#b6c5a4')+rect(29,27,18,12,'url(#metal)',2)+rect(70,27,18,12,'url(#metal)',2)+group(A['lightning'],'translate(30 44) scale(.47)')+line('M18 16L23 23M101 20L97 26','#dfd5a0',3)
A['computer']=monitor()
A['robot']=rect(30,27,61,53,'url(#metal)',12,'#cdd3ae')+rect(39,39,44,26,'#354f42',6)+circle(51,52,5,'#cddda0')+circle(72,52,5,'#cddda0')+line('M60 26V15','#b9c69d',3)+circle(60,12,5,'#debc77')+rect(37,83,48,24,'url(#teal)',5)+rect(15,42,12,25,'#859e8b',4)+rect(94,42,12,25,'#859e8b',4)+line('M40 72H80','#7e9981',3)+circle(60,95,5,'#dcc07f')
A['internet']=circle(60,61,38,'none','#a9c9ad',2)+ellipse(60,61,18,38,'none','#85b5a3',2)+ellipse(60,61,38,14,'none','#85b5a3',2)+line('M24 45H96M24 78H96M60 22V99','#a9c9ad',1)+''.join(circle(x,y,7,'url(#gold)') for x,y in [(26,41),(60,21),(98,66),(40,95)])
A['smartphone']=rect(32,9,60,103,'url(#metal)',10,'#cfd5b2')+rect(38,22,48,74,'#294d47',3)+line('M51 16H72','#678777',3)+circle(61,104,4,'#d7d6ac')+''.join(rect(x,y,10,10,c,2) for x,y,c in [(44,36,'#bdc784'),(62,36,'#d6b37e'),(44,54,'#90b5a5'),(62,54,'#c796a2')])+line('M44 78H75','#9eb995',3)
A['house']=house()
A['village']=group(house(),'translate(-7 33) scale(.65)')+group(house(),'translate(52 13) scale(.63)')+group(tree(),'translate(33 -5) scale(.55)')
A['city']=rect(15,40,24,68,'url(#stone)',2)+rect(43,13,32,95,'url(#metal)',3)+rect(80,50,27,58,'url(#ochre)',2)+''.join(rect(x,y,6,9,'#e4d2a1',1) for x,y in [(23,51),(23,69),(23,87),(50,26),(63,26),(50,46),(63,46),(50,66),(63,66),(50,88),(63,88),(88,63),(88,82)])+line('M7 108H114','#bdb690',3)
A['farm']=group(house('url(#roof)'),'translate(2 -2) scale(.8)')+group(wheat(),'translate(65 54) scale(.46)')+line('M9 90H76M9 101H76M17 83V111M45 83V111M70 83V111','#c4b084',4)
A['temple']=path('M9 40L60 14L111 40Z','url(#cream)','#c3be93',1)+rect(15,44,91,7,'#c8c498',1)+rect(11,103,98,8,'#b9b58d',1)+''.join(rect(x,50,12,53,'url(#cream)',2) for x in [23,53,84])+rect(18,97,84,7,'#d9d1a7',1)
A['pyramid']=path('M8 98L62 14L112 98L65 108Z','url(#gold)','#c9b681',1)+path('M62 14L65 108L112 98Z','#a88f5e')+line('M42 47H60M33 62H64M23 78H65M14 92H66M50 47V61M43 63V76M30 79V91','#d6c28c',1)
A['castle']=rect(29,55,64,52,'url(#stone)',2)+rect(14,26,23,81,'url(#stone)')+rect(84,26,23,81,'url(#stone)')+path('M12 38V19H22V28H30V19H40V38M81 38V19H91V28H99V19H109V38','url(#metal)')+path('M48 109V86A13 13 0 0 1 74 86V109Z','#465649')+rect(21,47,10,18,'#d1c28e',4)+rect(91,47,10,18,'#d1c28e',4)+line('M59 51V14','#b9b998',2)+path('M61 14H83L73 25H61Z','#b98275')
A['ruins']=path('M20 109V31L37 38L48 28V67L63 58L67 75L80 67V42L101 50V107Z','url(#stone)')+path('M34 109V88A12 12 0 0 1 58 88V109Z','#324b3a')+line('M32 45L38 61L29 74M84 72L90 90','#4b6551',2)+leaf(81,100,.6,28)+leaf(27,107,.4,-16)
A['religion']=circle(60,54,35,'none','#d4c18c',3)+star(60,53,28,'url(#gold)',8)+path('M17 91Q32 66 52 84L60 98L68 84Q87 64 104 91L85 109H35Z','url(#skin)')
A['knight']=path('M22 51Q20 13 60 13Q101 12 100 51L91 90L60 111L28 90Z','url(#metal)','#d6d4b0',1.5)+path('M30 53L61 62L91 53V76L60 87L31 76Z','#354f43')+line('M61 17V108M39 61V75M48 64V79M74 63V80M84 60V76','#c2c6a3',3)+path('M55 13L55 4L78 9L77 15Z','#b88278')
A['question']=circle(60,61,43,'url(#teal)','#bccdab',1.2)+path('M42 43C43 21 85 27 80 48C78 58 59 55 59 73','none','#eddfb1',7)+circle(59,91,4,'#eddfb1')
A['boat']=path('M9 73H112L91 103H31Z','url(#wood)','#d6bd91',1.5)+line('M16 84H105M39 76L46 102M78 76L75 102','#e1c297',2)+line('M60 72V14','#c9be94',3)+path('M55 20L24 63H55Z','url(#cream)')+path('M65 31L97 63H65Z','#aec1a2')+line('M9 109Q23 101 39 109T71 109T109 109','#90b5a8',3)
A['sail']=line('M33 110V8','#c5af7e',5)+path('M37 14Q94 26 103 95Q67 80 36 96Z','url(#cream)','#cec69c',1.2)+line('M36 54Q72 45 91 65M60 22Q56 53 60 91','#b4b593',2)
A['pottery']=path('M36 18Q59 12 83 18L77 34Q76 48 94 67Q110 98 81 108H39Q11 99 26 68Q43 47 43 34Z','url(#ochre)','#c9b28a',1.5)+ellipse(60,18,24,6,'#9a7c56')+line('M38 52H82M27 75Q60 89 95 74M24 87Q60 99 97 86','#e5c896',3)+path('M41 33Q51 46 39 62','none','#edcfa4',3)
A['book']=book()
A['music']=line('M43 89V29L91 16V77M43 40L91 27','#d0c492',7)+ellipse(29,92,19,12,'url(#gold)')+ellipse(77,80,19,12,'url(#gold)')+star(15,33,7)
A['paint']=ellipse(52,74,38,32,'url(#wood)','#c6b589',1.3)+ellipse(73,82,11,10,'#293f32')+circle(31,63,7,'#bf8577')+circle(48,53,7,'#d8ba72')+circle(66,60,7,'#93b182')+circle(30,84,7,'#90b9b0')+path('M81 70L91 19L101 23L87 74Z','url(#wood)')+path('M91 19Q91 8 106 6L101 23Z','url(#rose)')
A['art']=rect(19,22,85,72,'url(#gold)',4)+rect(25,28,73,60,'#b7c9a6',2)+circle(79,42,9,'#e4d29a')+path('M25 88L46 49L67 73L80 59L98 87Z','url(#leaf)')+line('M45 96L37 110M81 97L89 110M60 22V12','#bead7c',4)
A['clock']=circle(60,61,44,'url(#wood)','#c9b587',2)+circle(60,61,36,'url(#cream)')+line('M60 32V61L82 74','#56664c',4)+circle(60,61,5,'#b9a270')+''.join(group(line('M60 29V33','#7b8665',2),f'rotate({a} 60 61)') for a in range(0,360,30))
A['engine']=rect(25,41,64,49,'url(#metal)',7,'#bac6a5')+rect(40,27,38,15,'#92a591',3)+rect(84,55,24,28,'url(#wood)',4)+rect(17,59,12,24,'#aaba9b',2)+circle(57,66,18,'#426353','#b9c7a4',3)+circle(57,66,7,'#d0c89c')+line('M37 96H85M30 36V20H44','#a7b497',5)+line('M44 13Q51 4 58 11','#bdccb2',3)
A['car']=path('M10 63L27 55L42 28H78L97 55L109 61V91H11Z','url(#teal)','#bbcaab',1.5)+path('M45 34L34 55H86L74 34Z','#cad8b9')+line('M61 34V55','#729082',3)+circle(32,92,15,'#344a37','#a6b593',2)+circle(88,92,15,'#344a37','#a6b593',2)+circle(32,92,6,'#c4c59e')+circle(88,92,6,'#c4c59e')+rect(14,63,13,9,'#e4d098',2)+rect(99,64,9,9,'#c88f78',2)
A['train']=rect(25,52,70,32,'url(#teal)',4)+rect(12,26,34,55,'url(#wood)',3)+rect(19,33,19,22,'#bfd4b6',2)+rect(66,25,15,30,'url(#metal)',3)+rect(61,23,24,7,'#bfc7a4',2)+path('M95 66L112 91H91Z','#c5b083')+''.join(circle(x,91,12,'#566b4f','#bac099',3) for x in [27,57,84])+line('M26 92H85','#c8c59e',4)+group(cloud(),'translate(53 -7) scale(.42)')
A['airplane']=path('M55 13Q60 2 66 13L70 47L111 79V87L68 68L66 97L81 107V112L60 108L40 112V107L54 97L53 68L10 87V79L51 47Z','url(#cream)','#bcc8aa',1.5)+line('M59 22V96','#88a994',3)+path('M55 19L65 19L66 35H54Z','#548780')
A['rocket']=path('M43 80L37 98L21 99L30 65L44 58M78 80L84 98L100 99L91 65L77 58Z','url(#rose)','#d4b593',1)+path('M43 81C28 45 51 10 60 5C73 13 95 48 78 81Z','url(#cream)','#cdd2ae',1.5)+circle(60,44,13,'url(#water)','#b6ad7e',4)+path('M47 88H74L67 112L60 102L54 115Z','url(#flame)')+line('M44 75H77','#9aaf98',3)
A['satellite']=group(rect(9,39,28,38,'url(#teal)',2,'#ccd2aa')+rect(82,39,28,38,'url(#teal)',2,'#ccd2aa')+line('M23 40V76M95 40V76M10 52H35M10 64H35M84 52H108M84 64H108','#aecbb0',1.5)+rect(42,39,35,42,'url(#metal)',5)+line('M35 61H43M77 61H85M60 39V18','#b2bea0',4)+path('M41 17Q58 46 78 17Z','url(#cream)')+line('M60 17V7','#cbbd8a',3),'rotate(-28 60 60)')
A['printer']=rect(17,13,85,93,'url(#metal)',4,'#c4cca9')+rect(26,25,67,64,'#29453a',2)+line('M28 41H91M51 27V45','#91ae92',4)+rect(43,40,16,12,'url(#gold)',2)+path('M48 52L52 59L55 52Z','#dab876')+path('M46 67L69 62L78 72V86H42V73Z','url(#mint)')+line('M42 77H77M44 82H77','#d4e2b9',1)+line('M30 89H90','#c8d0ac',4)+circle(83,98,3,'#cddda9')+rect(28,95,22,6,'#4a6b58',1)
# Celestial miniatures
A['space']=circle(60,60,45,'url(#night)')+''.join(star(x,y,r,c) for x,y,r,c in [(32,34,7,'#e1d1aa'),(83,38,4,'#d6d5c2'),(53,85,6,'#c9cbbd'),(89,83,3,'#a7b7b1'),(53,51,3,'#a7b7b1')])+line('M32 34L53 51L83 38L53 85','#7b8d90',1)
A['planet']=circle(60,60,35,'url(#water)','#c4dabf',1)+path('M30 50Q40 32 52 38L61 53L46 66L55 87Q31 80 28 65Z','#92b590')+path('M83 36L76 52L84 69L72 80L90 72Z','#aac396')+ellipse(60,65,56,15,'none','#d3c89b',4)+path('M9 62Q23 91 111 64','none','#e1d4a7',3)
A['star']=star(60,61,49,'url(#gold)',5)+star(60,61,27,'#f5e7b6',5)+star(18,20,5)+star(107,37,4)
A['comet']=path('M13 93L102 9L95 45L112 27L86 86Z','url(#water)')+path('M31 79L91 27M53 80L95 55','none','#d9e9cd',3)+circle(35,83,24,'url(#glass)','#e0edcd',2)+star(35,83,12,'#eef2d7')
A['blackhole']=ellipse(60,60,51,26,'none','#c7af8a',6)+ellipse(60,60,39,36,'none','#a399a5',5)+circle(60,60,27,'#162b24','#d4c5a8',2)+path('M9 60Q42 82 109 62','none','#e7cfa2',5)
A['galaxy']=circle(60,60,14,'url(#gold)')+path('M46 58C36 16 97 12 100 52C103 92 43 108 25 76C4 39 46 11 66 19','none','#ababc2',9)+path('M67 65C86 91 31 103 21 61Q18 40 37 28','none','#829daa',6)+star(60,60,14)+star(101,91,4)+star(10,28,4)
A['asteroid']=group(rock(),'translate(-2 26) scale(.74)')+line('M55 29L83 9M77 41L103 19M88 61L113 38','#d1bf94',5)+ellipse(45,77,8,6,'#6f8070')+circle(25,77,4,'#718071')
A['alien']=path('M60 14C4 10 3 59 36 87L60 108L83 88C118 59 116 11 60 14Z','url(#mint)','#c5d7ac',1.5)+group(ellipse(37,59,11,19,'#314e3d'),'rotate(-35 37 59)')+group(ellipse(84,59,11,19,'#314e3d'),'rotate(35 84 59)')+line('M50 88Q60 93 70 88','#4b7660',2)
A['sun']=circle(60,61,29,'url(#gold)','#f0deb0',2)+''.join(group(path('M57 8H63L66 22H54Z','#d8be83'),f'rotate({a} 60 61)') for a in range(0,360,45))
A['moon']=circle(60,60,40,'url(#cream)','#d0d3b3',1.5)+circle(44,40,10,'#bec4a8')+circle(76,75,13,'#b1bba4')+circle(39,75,6,'#bdc3a7')+circle(78,42,4,'#bdc3a7')+path('M69 22Q39 51 60 100Q19 93 20 61Q16 28 69 22Z','#97aaa0',opacity='.22')
A['nebula']=circle(60,60,44,'url(#night)')+path('M20 75Q9 38 47 28Q108 12 96 65Q93 106 59 80Q79 49 41 57Z','url(#violet)',opacity='.7')+star(64,46,9)+star(33,74,6)+star(87,82,4)
A['universe']=circle(60,60,48,'url(#night)','#afb1b9',1.2)+''.join(group(ellipse(60,60,43,19,'none',c,2),f'rotate({a} 60 60)') for a,c in [(0,'#b9cbbb'),(60,'#c3adad'),(120,'#b9ad87')])+star(60,60,16)+star(16,27,5)+star(104,93,5)
A['magic']=line('M29 101L83 31','#bfba97',9)+line('M29 101L60 64','#9b7d62',5)+star(85,29,21,'url(#gold)',5)+star(26,24,7)+star(96,77,9)+star(40,55,4)
A['dragon']=path('M39 57L16 28L9 71L40 79M73 65L89 27L115 67L99 65L87 83Z','url(#rose)','#d6b396',1.5)+group(A['lizard'],'translate(12 1) scale(.87)')+path('M35 29L36 12L46 25M27 30L19 19L24 35Z','#d7c18c')+group(flame(),'translate(-4 51) scale(.32)')
A['phoenix']=path('M58 54Q14 48 17 8Q45 19 63 43Q78 19 106 16Q104 50 71 65L92 106L69 91L60 115L49 93L26 108L45 67Z','url(#flame)','#e2c095',1.2)+circle(65,40,13,'#e0b86e')+path('M75 35L95 43L75 48Z','#f0df9e')+circle(69,36,2,'#504d36')+line('M30 28L58 62L40 94M94 31L66 64L79 95','#f4dba1',2)
A['unicorn']=A['horse'].replace('url(#wood)','url(#cream)').replace('#6c6048','#ac94a8')+path('M80 27L104 1L91 39Z','url(#gold)','#e5d1a8',1)+star(19,24,6)
A['mermaid']=path('M48 58Q91 61 86 89L66 105L96 93L108 97L85 114L61 110L48 97Q66 84 45 79Z','url(#water)','#b5d4bd',1.5)+group(A['human'],'translate(12 4) scale(.64)')+line('M62 74L73 81M64 87L74 92','#d5deb6',2)
A['centaur']=group(A['horse'],'translate(15 23) scale(.74)')+group(A['human'],'translate(-1 -3) scale(.66)')
A['elf']=group(A['human'],'translate(0 0)')+path('M35 45L16 32L29 62L39 57M84 45L106 32L92 63L83 57Z','url(#skin)')+leaf(46,27,.6,85)+leaf(74,28,.5,-20)
A['wizard']=group(A['human'],'translate(8 20) scale(.86)')+path('M15 48L34 41L59 4L78 38L101 47Q61 61 15 48Z','url(#violet)','#bbb5b2',1.5)+star(59,29,7)+path('M44 75L61 110L78 76Q67 90 61 84Q52 91 44 75Z','url(#cream)')
for i,c,m in [('joy','#d5bf76','M42 73Q60 97 81 72'),('sadness','#91b3b3','M45 85Q60 70 78 86'),('anger','#c58d74','M42 89Q60 77 80 89'),('fear','#adabc3','M51 91Q48 70 61 72Q75 72 69 91Z'),('surprise','#d6c991','M53 89Q43 68 61 67Q78 69 67 90Z')]:
 A[i]=circle(60,61,43,c,'#d6cdac',1.5)+ellipse(45,55,3.5,5,'#354d3c')+ellipse(77,55,3.5,5,'#354d3c')+path(m,'#58604a' if i in ['fear','surprise'] else 'none','#58604a',3)
 if i=='sadness':A[i]+=group(drop(),'translate(1 56) scale(.32)')
 if i=='anger':A[i]+=line('M34 39L52 48M86 39L68 48','#7c5744',4)
A['love']=group(A['heart'],'translate(0 0)')+star(14,20,7)+star(109,85,5)
A['curiosity']=group(A['question'],'translate(-4 -9) scale(.75)')+circle(78,77,22,'#b0c7a7','#d2c38f',6)+line('M94 94L110 110','#bfa87d',10)+star(77,76,10,'#eff0cb')
# explicit final golem (avoid any runtime branch / placeholder)
A['golem']=rect(38,19,44,35,'url(#ochre)',8,'#d5b790')+path('M36 59L60 51L85 59L92 87L72 95L75 110H57L53 98L47 110H29L35 84L18 86L22 64Z','url(#ochre)','#c8ab7e',1.5)+circle(49,35,4,'#d5dc9e')+circle(72,35,4,'#d5dc9e')+star(59,74,11,'#d4dda1')
A['fairy']=group(A['butterfly'],'translate(0 9) scale(1 .9)')+group(A['human'],'translate(32 9) scale(.48)')+star(103,15,8)
A['potion']=bottle('url(#violet)')+star(59,81,12,'#e5dbaa')+star(20,23,6)+star(101,42,5)
A['portal']=ellipse(60,61,36,49,'#718873','#bdcaa3',3)+ellipse(60,61,27,41,'url(#night)')+path('M46 38C71 18 99 73 54 88C32 95 33 49 60 48C81 47 72 75 54 71','none','#b0a5c1',3)+star(59,61,10)+''.join(circle(x,y,2,'#e0d2a2') for x,y in [(60,18),(33,43),(30,72),(61,105),(87,77),(84,42)])
A['philosopher']=gem('url(#rose)')+circle(60,60,45,'none','#d8c58c',2)+path('M60 28L32 81H88Z','none','#ead4a2',2)+star(60,60,12)+star(15,28,6)+star(104,92,6)
# Validate every named illustration exists. Never silently substitute a generic icon.
data=json.loads((ROOT/'data.json').read_text())
missing=[e['id'] for e in data['elements'] if not A.get(e['art'])]
assert not missing,missing
DEFS='<defs>'
gradients={
 'water':['#baded4','#6ba8b4','#3c6d88'],'flame':['#f5d595','#db9b65','#ae6b50'],
 'earth':['#c1a77d','#927654','#5e5941'],'leaf':['#c5d39b','#8ea66a','#4d7456'],
 'mint':['#d8e2ac','#a1c593','#6c9b7d'],'cloud':['#e2e8d7','#bed0c1','#9bafa7'],
 'stone':['#d4d3b6','#a0ac99','#6e8378'],'gold':['#f0ddb0','#d2b577','#a58b53'],
 'wood':['#d5b68a','#a98a60','#756146'],'violet':['#c8c4d8','#a69bb9','#696485'],
 'teal':['#aec8af','#6e9a85','#436c59'],'ochre':['#dec19a','#b6956f','#8d7152'],
 'roof':['#d5ab8d','#b1846c','#826450'],'cream':['#f0e4c3','#d9cda5','#b7b28d'],
 'rose':['#e6b4a2','#c88f88','#9c6b70'],'skin':['#e8cfaa','#c6a77e','#b08b65'],
 'glass':['#e1ead6','#adccc7','#74a3ac'],'metal':['#d1d7b9','#9bae9a','#6c8877'],
 'coal':['#7d8e80','#526d5d','#2d473b'],'copper':['#dfba95','#bc8c69','#956b51'],
 'night':['#777c9c','#455976','#253e50'],'bread':['#e5c798','#c49f6a','#a77e4e']}
for k,cols in gradients.items():
 DEFS+=f'<linearGradient id="{k}" x1=".12" y1="0" x2=".83" y2="1">'+''.join(f'<stop offset="{i/2}" stop-color="{c}"/>' for i,c in enumerate(cols))+'</linearGradient>'
DEFS+='<filter id="artShadow" x="-30%" y="-25%" width="160%" height="165%"><feDropShadow dx="0" dy="3" stdDeviation="2.8" flood-color="#071e11" flood-opacity=".2"/></filter></defs>'
sprite='<svg xmlns="http://www.w3.org/2000/svg" class="sprite" aria-hidden="true">'+DEFS+''.join(f'<symbol id="art-{k}" viewBox="0 0 120 120"><g filter="url(#artShadow)">{v}</g></symbol>' for k,v in A.items())+'</svg>'
(ROOT/'art.svg').write_text(sprite)
print(f'{len(A)} original SVG illustrations, {len(sprite):,} bytes; all elements covered')
if __name__=='__main__' and '--gallery' in __import__('sys').argv:
 gallery='<html><meta charset="utf-8"><style>body{background:#223d2e;color:#e5e3c7;font:12px Arial;display:grid;grid-template-columns:repeat(10,1fr);gap:7px;padding:16px}.sprite{position:absolute;width:0;height:0}.tile{padding:10px;background:#2e4838;border-radius:8px;text-align:center}.tile svg{width:90px;height:90px;display:block;margin:auto}</style>'+sprite
 gallery+=''.join(f'<div class="tile"><svg viewBox="0 0 120 120"><use href="#art-{e["id"]}"/></svg>{e["name"]}</div>' for e in data['elements'])+'</html>'
 (ROOT/'art_gallery.html').write_text(gallery)
