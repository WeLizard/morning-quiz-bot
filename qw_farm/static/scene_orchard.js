/* Fruit trees of the orchard and their markers (docs/tasks/FARM_ORCHARD.md, section 7). View only: drawn with the farm's own
   primitives (FarmScene ellipse / line / poly / leaf / shadow), the greens of treeSprite and soft translucent shadows, no outlines.
   One call per tree object. The stage and the cycle phase come from orchard.js treeLook (the server owns every number); the care
   marks (pest, dry branches, golden fruit, the starling of a near birdhouse) need the owner's snapshot and stay hidden from guests.
   A tree is anchored at the centre of its tile; the crown keeps inside objectBounds (scene_map.js: ±70 px, 150 px up). */
import {treeLook} from './orchard.js';

// Per species: trunk height and limbs, crown blobs [dx,dy,rx,ry,tone 0 dark..3 highlight] back to front, the fruit spots in the
// order they fill (young trees use the first few), leaves, fruit and blossom colours, where the care marks sit. Adult size, px.
const KIT={
 apple:{trunk:26,limbs:[[-9,-38],[10,-40],[0,-44]],leaf:['#6f966b','#7fa577','#92b282','#a9c495'],
  crown:[[0,-50,30,21,0],[-19,-44,13,11,0],[19,-45,13,11,0],[-10,-54,18,14,1],[11,-52,18,14,1],[0,-62,17,11,1],[-12,-60,11,8,2],[5,-65,11,7,2],[-15,-63,6,4,3]],
  spots:[[-17,-42],[6,-41],[19,-47],[-6,-49],[12,-56],[-22,-51],[1,-58],[-11,-56],[17,-40],[-2,-43],[23,-53]],
  fruit:'apple',bloom:['#fbeef0','#eeb2c0'],pest:[22,-40],dry:[-18,-62],bird:[16,-66],shadow:[27,9]},
 pear:{trunk:30,limbs:[[-5,-46],[5,-48]],leaf:['#72976a','#83a873','#98b67f','#b1c893'],
  crown:[[0,-60,19,29,0],[-9,-47,11,12,0],[9,-49,11,12,0],[-6,-64,13,21,1],[7,-57,12,18,1],[0,-79,10,11,1],[-7,-72,8,11,2],[-1,-83,6,6,2],[-9,-74,3.5,5,3]],
  spots:[[-10,-46],[9,-48],[1,-54],[-12,-60],[12,-63],[-4,-68],[8,-74],[-14,-52],[14,-54],[1,-44],[-6,-78]],
  fruit:'pear',bloom:['#fbf7ee','#e8dcc0'],pest:[16,-50],dry:[-12,-82],bird:[11,-84],shadow:[20,8]},
 cherry:{trunk:16,limbs:[[-16,-30],[16,-31],[0,-36]],leaf:['#668f66','#77a071','#8bae7e','#a3c091'],
  crown:[[-15,-36,18,13,0],[15,-36,18,13,0],[0,-40,22,14,0],[-21,-40,12,9,1],[21,-40,12,9,1],[-5,-46,16,10,1],[8,-44,14,9,1],[-12,-48,10,6,2],[6,-50,9,6,2],[-15,-49,5,3,3]],
  spots:[[-24,-30],[-10,-28],[4,-29],[18,-30],[28,-35],[-18,-40],[10,-38],[-3,-37],[22,-41],[-29,-38],[1,-46]],
  fruit:'cherry',bloom:['#fdfaf3','#f0dfe2'],pest:[26,-34],dry:[-22,-48],bird:[18,-52],shadow:[31,9]},
 plum:{trunk:24,limbs:[[-7,-38],[7,-40]],leaf:['#6a906e','#7b9f7a','#8fae88','#a7c09e'],
  crown:[[0,-55,23,26,0],[-14,-46,11,11,0],[14,-47,11,11,0],[-8,-59,15,18,1],[9,-53,14,17,1],[0,-71,13,11,1],[-9,-67,9,10,2],[2,-75,7,6,2],[-11,-70,4,5,3]],
  spots:[[-14,-44],[7,-43],[16,-50],[-4,-50],[11,-60],[-17,-55],[0,-62],[-9,-67],[17,-42],[-2,-41],[8,-71]],
  fruit:'plum',bloom:['#fbf8f2','#e2dde6'],pest:[19,-44],dry:[-15,-74],bird:[13,-77],shadow:[24,9]},
 apricot:{trunk:24,limbs:[[-12,-36],[12,-37],[0,-40]],leaf:['#719669','#82a674','#97b47f','#adc391'],
  crown:[[0,-46,33,17,0],[-21,-41,13,10,0],[21,-41,13,10,0],[-12,-50,19,12,1],[12,-49,19,12,1],[0,-56,21,10,1],[-13,-56,11,7,2],[6,-59,12,6,2],[-16,-58,6,3,3]],
  spots:[[-22,-39],[-8,-37],[7,-38],[22,-41],[-15,-47],[1,-45],[15,-49],[-27,-45],[27,-46],[-4,-53],[9,-55]],
  fruit:'apricot',bloom:['#f8d3dc','#e48ea2'],pest:[27,-40],dry:[-24,-56],bird:[20,-60],shadow:[30,9]},
 peach:{trunk:16,limbs:[[-12,-40],[1,-48],[12,-42]],leaf:['#76996a','#88aa73','#9eba80','#b4c994'],fringe:true,
  crown:[[0,-50,20,21,0],[-12,-42,10,10,0],[12,-44,10,10,0],[-8,-55,12,15,1],[9,-50,12,14,1],[0,-63,10,9,1],[-7,-62,7,8,2],[5,-60,6,7,2],[-9,-64,3,4,3]],
  spots:[[-12,-40],[9,-41],[0,-46],[-8,-52],[14,-49],[5,-56],[-15,-47],[-2,-60],[12,-58],[-6,-44],[17,-44]],
  fruit:'peach',bloom:['#f9c9d6','#df7f99'],pest:[18,-42],dry:[-14,-66],bird:[12,-68],shadow:[22,8]},
 pomegranate:{trunk:0,tub:true,stems:[[-9,-34],[1,-40],[9,-35],[-3,-30]],leaf:['#5f8a5e','#6f9a67','#84ab76','#9dbd8a'],
  crown:[[-10,-38,12,10,0],[10,-39,12,10,0],[0,-47,14,12,0],[-13,-44,8,7,1],[12,-45,8,7,1],[-1,-54,10,8,1],[3,-41,9,7,1],[-5,-53,6,5,2],[6,-47,6,4,2],[-9,-46,4,3,2],[-6,-55,3,2.5,3]],
  spots:[[-12,-35],[9,-36],[1,-40],[-6,-47],[13,-44],[-15,-43],[5,-51],[-3,-34],[16,-38],[-10,-52],[9,-55]],
  fruit:'pomegranate',bloom:['#ee7a52','#c9442e'],pest:[17,-38],dry:[-14,-56],bird:[11,-60],shadow:[21,8]}
};
// Graft looks (obj.look): crown, fruit or dress change, the species stays. An unknown look draws the plain species.
const LOOK={
 paradise:{leaf:['#7a8a5e','#8c9a67','#a2aa76','#bcb98a'],fruit:'paradise',bloom:['#f6b3c8','#c9507a']},
 bergamot:{fruit:'bergamot',crown:[[0,-56,23,24,0],[-13,-46,12,11,0],[13,-48,12,11,0],[-7,-60,15,17,1],[8,-54,14,15,1],[0,-72,12,9,1],[-8,-67,9,9,2],[1,-76,6,5,2],[-10,-69,4,4,3]]},
 cozy:{cozy:true},
 frost:{leaf:['#96b2b6','#adc6c8','#c8dadb','#eaf3f3'],frost:true},
 bloom:{always:true,bloom:['#fde6ee','#ef9fb8']}
};
const STAGE={sapling:.58,young:.76,adult:.92,elder:1.02,century:1.06};
const WIDE={elder:1.08,century:1.12};
const TRUNK={sapling:2.2,young:3,adult:4,elder:5.4,century:6.2};
const COUNT={sapling:3,young:4,adult:7,elder:9,century:10};
const BARK='#9a8360',BARK_DARK='#7c6849',UNRIPE='#b4c88a';

const MIX=new Map();
function mixHex(a,b,k){k=Math.round(Math.max(0,Math.min(1,k))*8)/8;const key=a+b+k;let v=MIX.get(key);if(v)return v;
 const A=parseInt(a.slice(1),16),B=parseInt(b.slice(1),16),m=sh=>Math.round(((A>>sh)&255)+(((B>>sh)&255)-((A>>sh)&255))*k);
 v=`rgb(${m(16)},${m(8)},${m(0)})`;MIX.set(key,v);return v}
const RIPE={apple:'#d9534f',pear:'#c6cf5a',cherry:'#a3203a',plum:'#6b4a8c',apricot:'#f0a64a',peach:'#f2a07a',pomegranate:'#b3262f',paradise:'#c42f3c',bergamot:'#d2b24a'};

// Birdhouses of a snapshot, found once per objects array (a farm has a few at most).
const HOUSES=new WeakMap();
function birdhouses(farm){const objs=farm?.objects;if(!objs)return [];let v=HOUSES.get(objs);if(!v||v.n!==objs.length){v={n:objs.length,list:objs.filter(o=>o.type==='birdhouse')};HOUSES.set(objs,v)}return v.list}
export function nearBirdhouse(farm,o,radius=2){return birdhouses(farm).some(b=>Math.max(Math.abs(b.x-o.x),Math.abs(b.y-o.y))<=radius)}

/* One fruit: r is the full radius at this stage (scaled), k 0..1 how ripe (colour and size). */
function fruit(s,kind,x,y,r,k){
 const col=k>=1?RIPE[kind]:k<.35?UNRIPE:mixHex(UNRIPE,RIPE[kind],(k-.35)/.65),R=r*(.55+.45*Math.min(1,k));
 if(kind==='cherry'){s.line(x,y-R*2.6,x-R*.9,y-R*.4,'#7d7a4c',.7);s.line(x,y-R*2.6,x+R*.9,y-R*.2,'#7d7a4c',.7);
  s.ellipse(x-R*.9,y,R*.82,R*.82,col);s.ellipse(x+R*.9,y+.2,R*.82,R*.82,col);if(k>.8){s.ellipse(x-R*1.15,y-R*.3,R*.25,R*.22,'#f4b4c0');s.ellipse(x+R*.65,y-R*.1,R*.25,R*.22,'#f4b4c0')}return}
 if(kind==='paradise'){for(const [dx,dy] of [[-.8,0],[.8,.2],[0,-.9]])s.ellipse(x+dx*R,y+dy*R,R*.58,R*.58,col);if(k>.8)s.ellipse(x-R*.95,y-R*.2,R*.2,R*.18,'#f6b8b0');return}
 if(kind==='pear'){s.ellipse(x,y+R*.25,R*.86,R*.86,col);s.ellipse(x,y-R*.55,R*.52,R*.62,col);if(k>.8)s.ellipse(x+R*.4,y+R*.35,R*.32,R*.3,'#dcae5a');s.line(x,y-R*1.15,x+R*.3,y-R*1.6,'#7c6849',.7);return}
 if(kind==='plum'){s.ellipse(x,y,R*.78,R,col);if(k>.8){s.ellipse(x-R*.3,y-R*.3,R*.3,R*.45,'#a596c4');s.line(x+R*.1,y-R*.85,x+R*.15,y+R*.7,'#57396f',.6)}return}
 s.ellipse(x,y,R,R,col);
 if(kind==='peach'&&k>.6){s.ellipse(x+R*.32,y+R*.15,R*.62,R*.62,mixHex('#f2a07a','#e0675a',k));s.ellipse(x-R*.38,y-R*.36,R*.28,R*.26,'#fcd8c0')}
 else if(kind==='apricot'&&k>.6){s.ellipse(x+R*.4,y+R*.2,R*.42,R*.4,'#e48a3e');s.ellipse(x-R*.4,y-R*.4,R*.26,R*.24,'#fbd49a')}
 else if(kind==='pomegranate'){s.poly([{x:x-R*.42,y:y-R*.8},{x:x-R*.3,y:y-R*1.35},{x,y:y-R*.95},{x:x+R*.3,y:y-R*1.35},{x:x+R*.42,y:y-R*.8}],k>.6?'#8e1c26':'#8aa36a');if(k>.8)s.ellipse(x-R*.4,y-R*.3,R*.26,R*.24,'#e8818a')}
 else if(kind==='bergamot'){if(k>.6)s.ellipse(x+R*.35,y+R*.25,R*.45,R*.4,'#a8763a');if(k>.8)s.ellipse(x-R*.4,y-R*.4,R*.25,R*.22,'#f4e09a')}
 else if(k>.8)s.ellipse(x-R*.38,y-R*.38,R*.28,R*.26,'#f3a99a');
 if(kind==='apple'||kind==='bergamot'||kind==='apricot')s.line(x,y-R,x+R*.25,y-R*1.45,'#7c6849',.7);
}
function blossom(s,x,y,r,col){s.ellipse(x,y,r,r*.86,col[0]);s.ellipse(x-r*.5,y-r*.4,r*.55,r*.5,col[0]);s.ellipse(x+.2,y-.1,r*.36,r*.36,col[1])}
// Spots for blossoms and rime: the fruit spots plus a jittered second ring, fixed per species.
const BLOOM_SPOTS=new Map();
function bloomSpots(id,kit){let v=BLOOM_SPOTS.get(id);if(v)return v;v=[];
 for(const [x,y] of kit.spots)v.push([x,y]);
 for(const [dx,dy,rx,ry,tone] of kit.crown)if(tone>=1)for(const a of [.6,2.4,4.3])v.push([dx+Math.cos(a)*rx*.62,dy+Math.sin(a)*ry*.55]);
 BLOOM_SPOTS.set(id,v);return v}

function trunk(s,kit,stage,w){
 if(kit.tub){
  for(const [x,y] of kit.stems){s.line(x*.15,-11,x*.62,y*.62,BARK,Math.max(1.4,w*.42));s.line(x*.62,y*.62,x,y+4,BARK,Math.max(1,w*.3))}
  return}
 const h=kit.trunk;
 if(stage==='elder'||stage==='century'){s.ellipse(-w*.55,-.6,w*.6,w*.28,BARK);s.ellipse(w*.6,-.3,w*.55,w*.26,BARK_DARK)}
 s.line(0,0,0,-h,BARK,w);s.line(w*.3,-1,w*.3,-h+2,BARK_DARK,Math.max(.8,w*.3));
 for(const [x,y] of kit.limbs){const mx=x*.5,my=(y-h)/2;s.line(0,-h+2,mx,my,BARK,w*.62);s.line(mx,my,x,y,BARK,w*.4)}
 if(stage==='century'){s.ellipse(-.4,-h*.55,w*.22,w*.36,'#5d4c35')}
}
function tub(s){
 s.poly([{x:-12,y:-12},{x:12,y:-12},{x:10,y:0},{x:-10,y:0}],'#b48a5c');s.ellipse(0,0,10,3.4,'#b48a5c');
 s.poly([{x:2,y:-12},{x:12,y:-12},{x:10,y:0},{x:2,y:1}],'#9f7a50');
 for(const x of [-7,-2.5,6.5])s.line(x,-11,x*.9,0,'rgba(90,62,36,.35)',.8);
 for(const y of [-3,-9])s.line(-11.4+(y+12)*.15,y,11.4-(y+12)*.15,y,'#6f5a44',1.3);
 s.ellipse(0,-12,12,3.8,'#c9a274');s.ellipse(0,-12,9.6,2.6,'#6f5a40')}
function crown(s,blobs,leaf,wide){for(const [dx,dy,rx,ry,tone] of blobs)s.ellipse(dx*wide,dy,rx*wide,ry,leaf[tone])}
// Narrow willow-like leaves around the peach crown: the slender species reads by its fringe, not only by its size.
function fringe(s,leaf){for(const [x,y,a] of [[-15,-42,2.2],[-19,-50,2.6],[15,-42,.95],[18,-51,.55],[-6,-35,1.9],[7,-36,1.25],[-12,-62,3.5],[12,-61,5.9]])s.leaf(x,y,a,8,1.6,leaf[a>3?1:0])}
// Dormant winter look (s.orchardWinter; off until the owner decides, FARM_ORCHARD.md question 9): bare limbs and snow caps.
function bare(s,kit,w){
 for(const [dx,dy,rx,ry,tone] of kit.crown){if(tone>1)continue;const tx=dx+(dx>=0?rx*.35:-rx*.35),ty=dy-ry*.45;s.line(dx*.3,(dy+ry)*.8,tx,ty,BARK_DARK,Math.max(.9,w*.28));s.line(tx,ty,tx+(dx>=0?4:-4),ty-4,BARK_DARK,.8);s.ellipse(tx,ty-1,3.2,1.3,'#f4f7f8')}
 for(const [dx,dy,rx,ry,tone] of kit.crown)if(tone===2)s.ellipse(dx,dy-ry*.6,rx*.7,1.6,'#eef4f5')}

function caterpillar(s,x,y,t){const wig=s.motion?Math.sin(t*3)*.8:0;
 s.line(x-9,y+3,x+3,y+1,BARK,1.6);
 for(let i=0;i<4;i++)s.ellipse(x-7+i*2.6,y-1.4-(i%2?wig:0),1.9,1.9,i%2?'#93c45a':'#86b84f');
 s.ellipse(x+3.6,y-2.6,2.3,2.3,'#9fcf62');s.ellipse(x+4.4,y-3,.55,.55,'#2f3a26');
 s.poly([{x:x+1.2,y:y-4.2},{x:x+3.6,y:y-6.6},{x:x+6,y:y-4.4}],'#d9553f');s.line(x+5.4,y-4.4,x+8,y-4.2,'#c04a36',1.2)}
function aphids(s,x,y){s.leaf(x,y,.4,8,2.6,'#b9c47a');for(const [dx,dy] of [[-2,-1],[0,-2],[2,-1],[1,.4],[-1,.5]])s.ellipse(x+dx,y+dy,.95,.8,'#a9d46e');s.ellipse(x+4,y-3,1,1,'#a9d46e')}
function moth(s,x,y,t){const f=s.motion?Math.abs(Math.sin(t*9))*.5+.5:.85,yy=y+(s.motion?Math.sin(t*1.7)*2:0);
 s.poly([{x,y:yy},{x:x-7*f,y:yy-5.5},{x:x-6*f,y:yy+2}],'#efe4c8');s.poly([{x,y:yy},{x:x+7*f,y:yy-5.5},{x:x+6*f,y:yy+2}],'#e2d4b4');
 s.ellipse(x,yy-.5,1.1,2.8,'#6f5f4a');s.ellipse(x-3.6*f,yy-1.6,1,1,'#9a7a56');s.ellipse(x+3.6*f,yy-1.6,1,1,'#9a7a56');s.line(x,yy-3,x-1.6,yy-5.4,'#6f5f4a',.5);s.line(x,yy-3,x+1.6,yy-5.4,'#6f5f4a',.5)}
function dryTwigs(s,x,y){const D='#9c8b74';s.line(x+4,y+6,x-3,y-5,D,1.5);s.line(x-3,y-5,x-8,y-8,D,1);s.line(x-3,y-5,x-2,y-11,D,1);s.line(x+1,y,x+6,y-4,D,1);
 s.leaf(x-8,y-8,3.6,4,1.4,'#b58b5a');s.leaf(x+6,y-4,5.5,4,1.4,'#c49a62')}
function starling(s,x,y,t){const bob=s.motion?Math.max(0,Math.sin(t*2.3))*1.2:0;
 s.line(x-2,y+3,x-1,y+5,'#c9a24a',.7);s.line(x+1,y+3,x+1.5,y+5,'#c9a24a',.7);
 s.ellipse(x,y,4.2,3,'#3f4352');s.poly([{x:x-3,y:y-1},{x:x-8,y:y+1},{x:x-3,y:y+1.6}],'#363a48');
 s.ellipse(x+3.2,y-2.8+bob*.3,2.4,2.2,'#454a5a');s.poly([{x:x+5,y:y-3.4+bob*.3},{x:x+8,y:y-2.6+bob*.6},{x:x+5,y:y-2+bob*.3}],'#e2b84a');
 for(const [dx,dy] of [[-1,-.6],[1,.6],[-2,1]])s.ellipse(x+dx,y+dy,.45,.45,'#cfd3dc');s.ellipse(x+3.8,y-3.3+bob*.3,.45,.45,'#f3f1e8')}
function plaque(s,x,y){s.line(x,y,x,y-9,BARK_DARK,1.4);s.poly([{x:x-7,y:y-15},{x:x+7,y:y-14},{x:x+7,y:y-8},{x:x-7,y:y-9}],'#e9d6a4');s.line(x-6,y-9.2,x+6,y-8.2,'#bd9a64',.8);
 const c=s.c;c.save();c.font='700 6px "Segoe UI",sans-serif';c.textAlign='center';c.fillStyle='#5a4127';c.fillText('100',x,y-9.6);c.restore()}
function cozyDress(s,kit,w){const h=Math.max(10,kit.trunk*.7),c=['#c75a5a','#f1e6cf','#d9a54a','#f1e6cf'];for(let i=0;i<5;i++){const y0=-2-i*h/5;s.poly([{x:-w*.62,y:y0},{x:w*.62,y:y0+.6},{x:w*.62,y:y0-h/5+.6},{x:-w*.62,y:y0-h/5}],c[i%4])}
 s.line(-w*.62,-h-2,w*.62,-h-1.4,'#a8473f',1.2)}
function pompoms(s){const pts=[[-20,-46],[-8,-42],[5,-43],[18,-47]];s.c.save();s.c.beginPath();s.c.moveTo(-24,-50);s.c.quadraticCurveTo(0,-36,22,-51);s.c.strokeStyle='#c9b48a';s.c.lineWidth=.8;s.c.stroke();s.c.restore();
 pts.forEach(([x,y],i)=>{s.ellipse(x,y,2.4,2.4,['#c75a5a','#e3b04a','#8fb4c8','#f1e6cf'][i]);s.ellipse(x-.7,y-.7,.8,.8,'rgba(255,255,255,.55)')})}
function rime(s,spots){for(let i=0;i<spots.length;i+=2){const [x,y]=spots[i];s.ellipse(x,y,1.2,1,'#ffffff')}}
function goldenFruit(s,x,y){s.ellipse(x,y,3.9,3.9,'#f2c84a');s.ellipse(x+1,y+.9,2,1.8,'#e0a83a');s.ellipse(x-1.2,y-1.3,1.3,1.1,'#fff3b0');s.line(x,y-3.9,x+.9,y-5.6,'#7c6849',.7)}
function goldenSparkle(s,x,y,t){const a=s.motion?.65+.35*Math.sin(t*3.1):1,r=2.2+a*1.6;
 s.c.save();s.c.globalAlpha=a;const X=x+5,Y=y-6;s.poly([{x:X,y:Y-r*1.7},{x:X+r*.4,y:Y-r*.4},{x:X+r*1.7,y:Y},{x:X+r*.4,y:Y+r*.4},{x:X,y:Y+r*1.7},{x:X-r*.4,y:Y+r*.4},{x:X-r*1.7,y:Y},{x:X-r*.4,y:Y-r*.4}],'#fff3b0');s.c.restore()}

/* The whole tree at p (screen point of the tile centre) at server time t. The owner's snapshot carries the care fields; a guest's does not. */
export function drawTree(s,o,p,catalog,t){
 const L=treeLook(catalog,o,t),kit=KIT[o.species]||KIT.apple,look=LOOK[o.look]||null,winter=s.orchardWinter===true;
 const grown=L.phase!=='grow',stage=L.stage,k=grown?STAGE[stage]:.7+.2*L.grow,wide=WIDE[stage]||1,w=TRUNK[stage];
 const leaf=look?.leaf||kit.leaf,blobs=look?.crown||kit.crown,fruitKind=look?.fruit||kit.fruit,bloomCol=look?.bloom||kit.bloom;
 const c=s.c,mine=!!s.farm?.is_owner,f=o.fruit||null,r=s.catalog?.orchard?.rules?.birdhouse_radius??2;
 c.save();c.translate(p.x,p.y);
 s.shadow(0,0,kit.shadow[0]*k*wide*(grown?1:.6),kit.shadow[1]*k*(grown?1:.7));
 c.scale(k,k);
 if(kit.tub)tub(s);
 if(!grown){sapling(s,kit,L.grow,leaf,winter);c.restore();markers(s,o,p,-30*k,L);return}
 if(stage==='sapling')stake(s,kit);
 trunk(s,kit,stage,w);
 if(look?.cozy)cozyDress(s,kit,w);
 const sway=s.motion&&!winter?Math.sin((s.time||0)*1.1+o.x*1.7+o.y*.9)*.8:0;
 c.save();c.translate(sway,0);
 if(winter)bare(s,kit,w);
 else{crown(s,blobs,leaf,wide);if(kit.fringe)fringe(s,leaf)}
 const n=COUNT[stage],spots=kit.spots,ripe=L.phase==='ripe',lod=(s.scale||1)<.45;let golden=null;
 if(!winter&&(L.phase==='bloom'||look?.always)){const all=bloomSpots(o.species,kit),m=look?.always?all.length:Math.ceil(Math.min(all.length,n*1.7)*(.45+.55*Math.min(1,L.k)));for(let i=0;i<m;i+=lod?2:1)blossom(s,all[i][0]*wide,all[i][1],2.3,bloomCol)}
 if(look?.frost&&!winter)rime(s,bloomSpots(o.species,kit));
 if(L.phase==='set'||L.phase==='fill'||ripe){
  const kk=L.phase==='set'?0:L.phase==='fill'?L.k*.85:1,gold=ripe&&mine&&f?.golden;
  if(!winter||ripe)for(let i=gold?1:0;i<n;i++)fruit(s,fruitKind,spots[i][0]*wide,spots[i][1],3.3,L.phase==='set'?.12+.18*L.k:kk);
  if(gold){goldenFruit(s,spots[0][0]*wide,spots[0][1]);golden=[p.x+(spots[0][0]*wide+sway)*k,p.y+spots[0][1]*k]}
 }
 if(look?.cozy&&!winter)pompoms(s);
 c.restore();
 if(stage==='century')plaque(s,11,-1);
 c.restore();
 // The glint of the golden fruit stays bright above the night tint (with the ready badges); the fruit itself keeps its depth.
 if(golden){const [X,Y]=golden,paint=()=>goldenSparkle(s,X,Y,s.time||0);if(s.lightMarkers)s.lightMarkers.push({kind:'fn',fn:paint});else paint()}
 // Care marks: owner only (a guest's snapshot has no pest, prune or golden fields at all).
 if(mine&&f){
  const at=([x,y])=>({x:p.x+(x*wide+sway)*k,y:p.y+y*k}),T=s.time||0;
  if(f.pest&&!nearBirdhouse(s.farm,o,r)){const q=at(kit.pest);if(f.pest==='aphid')aphids(s,q.x,q.y);else if(f.pest==='moth')moth(s,q.x,q.y-4,T);else caterpillar(s,q.x,q.y,T)}
  if(Number.isFinite(o.prune_at)&&o.harvests>=o.prune_at){const q=at(kit.dry);dryTwigs(s,q.x,q.y)}
  if(f.pest&&nearBirdhouse(s.farm,o,r)){const q=at(kit.bird);starling(s,q.x,q.y,T+o.x)}   // the starling of a near birdhouse is minding this year's pest
 }
 markers(s,o,p,Math.min(...blobs.map(b=>b[1]-b[3]))*k,L);
}
function stake(s,kit){const x=kit.tub?6:7,b=kit.tub?-12:1,top=kit.tub?-40:-30;s.line(x,b,x,top,'#b39a70',2);s.line(x-.5,top,x+.5,top-1,'#8d7752',2);s.line(x,(b+top)*.6,0,(b+top)*.6+1,'#d8c9a0',1.6)}
function sapling(s,kit,g,leaf,winter){
 const b=kit.tub?-12:0,h=16+g*14-b,x=kit.tub?5:6;
 s.line(x,b+1,x,-h-4,'#b39a70',1.8);s.line(x,-h*.55,0,-h*.55,'#d8c9a0',1.5);
 s.line(0,b,0,-h,BARK,1.8);s.line(0,-h*.6,-5,-h*.85,BARK,1.1);s.line(0,-h*.75,4,-h*.98,BARK,1.1);
 if(winter){s.ellipse(0,-h-1,2.6,1.1,'#f4f7f8');return}
 const leaves=[[-5,-h*.85,3.6],[4,-h*.98,5.9],[0,-h-1,4.7],[-2,-h*.5,3.2],[3,-h*.65,5.6]];
 for(let i=0;i<Math.min(leaves.length,2+Math.round(g*3));i++){const [lx,ly,a]=leaves[i];s.leaf(lx,ly,a,7,2.4,leaf[i%2?2:1])}
 if(g>.55){const r=4+g*6;s.ellipse(-1,-h-2,r,r*.82,leaf[1]);s.ellipse(-3,-h-4,r*.6,r*.5,leaf[2])}
}
function markers(s,o,p,top,L){
 // Contrast mode (UI_RULES §16): the fruit icon over every tree, green ring and check when ripe, «Яблоня · 3 ч» when selected.
 if(s.contrast&&s.cropBadge){
  const ripe=L.phase==='ripe',r=s.badgeRadius(),y=p.y+top-r-2;s.cropBadge(p.x,y,o.species,ripe);
  if(o.id===s.selected){const name=s.catalog?.orchard?.trees?.[o.species]?.name||'';s.label(p.x,y-r-4,(name?name+' · ':'')+(ripe?'урожай':o.fruit?s.timeLeft(o.fruit.ready_at):'растёт'))}
  return;
 }
 if(L.phase==='ripe')s.ready(p.x+14,p.y+top-6);
 else if(o.id===s.selected&&o.fruit)s.clockBubble(p.x,p.y+top-8,o.fruit.ready_at);
}
