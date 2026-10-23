// Village world painted with the farm's own drawing code (common.js: FarmScene methods + scene_buildings.js).
// Projection = farm (TW 36, TH 18) scaled by K: canvas px = (OX + K*(x-y)*36, OY + K*((x+y)*18 - z)); the 3200x2400 canvas
// is the village.svg viewBox 2400x1800 at 4/3. Restored 2026-10-22 from the 2026-10-15 generator (see README.md).
// Live parts are not painted here: chimney smoke, mill sails, the water wheel, night lights and the gate board are
// layers of the game (app.js) placed from the coordinates this render exports (meta).
import {B,makeS,P,TW,TH} from './common.js';
import {paintGate,boardSvg} from './gate.js';
import {buildWalk} from './walk.js';
import {playerSvg} from './player.js';
import {posidelki} from './fest_posidelki.js';
import {newYear} from './fest_newyear.js';
import {maslenitsa} from './fest_maslenitsa.js';
import {springFlowers} from './fest_flowers.js';
import {buildArt} from './build.js';
import {crewSvgs} from './crew.js';
import {merchantCart,magpieSvg} from './merchant.js';

export async function render(opts={}){
const W=3200,H=2400,OX=1600,OY=300,K=1.3;
const DEBUG=!!opts.debug;
const cv=document.createElement('canvas');cv.width=W;cv.height=H;
const ctx=cv.getContext('2d');const s=makeS(ctx);s.sails=[];
ctx.setTransform(K,0,0,K,OX,OY);
const scr=(p)=>[Math.round(OX+K*p.x),Math.round(OY+K*p.y)];
const meta={sites:[],windows:[],smoke:[],lamps:[],sails:[],wheel:null,gear:null,clock:null,spots:{},places:{},chimneys:[]};
let seed=11;const rnd=()=>(seed=(seed*16807)%2147483647)/2147483647;
const hash=(x,y)=>{const n=Math.sin(x*127.1+y*311.7)*43758.5453;return n-Math.floor(n)};

/* ---------- plan (tile coordinates) ---------- */
const inR=(x,y,r)=>x>=r[0]&&x<r[2]&&y>=r[1]&&y<r[3];
const PLAZA=[14,14,24,24];
const ROADS=[[-30,19,14,21],[19,-30,21,14],[16,24,18,80],[24,16,80,18],[22,24,24,35],[12,35,60,37]];
const LANES=[[11,10,19,11],[15,-5,19,-4],[8,25,12,26],[24,26,30,27],[27,21,28,26],[34,18,35,24]];
const isRoad=(x,y)=>ROADS.some(r=>inR(x,y,r));
const isLane=(x,y)=>!isRoad(x,y)&&LANES.some(r=>inR(x,y,r));
const isPlaza=(x,y)=>inR(x,y,PLAZA);
const RIVER=[[-16,2],[-11,5],[-6,8],[-2,10.5],[1.6,13],[3.6,15.6],[4,18],[4,21],[4.1,23.6],[5.6,27],[8,31],[10,35.5],[12,41],[13,48]];
const RW=2.6;
function catmull(pts,step=.2){const Q=[pts[0],...pts,pts[pts.length-1]],out=[];
 for(let i=1;i<Q.length-2;i++){const [p0,p1,p2,p3]=[Q[i-1],Q[i],Q[i+1],Q[i+2]],L=Math.hypot(p2[0]-p1[0],p2[1]-p1[1]),n=Math.max(2,Math.floor(L/step));
  for(let k=0;k<n;k++){const t=k/n,t2=t*t,t3=t2*t,f=j=>.5*(2*p1[j]+(-p0[j]+p2[j])*t+(2*p0[j]-5*p1[j]+4*p2[j]-p3[j])*t2+(-p0[j]+3*p1[j]-3*p2[j]+p3[j])*t3);out.push([f(0),f(1)])}}
 out.push(pts[pts.length-1]);return out}
const river=catmull(RIVER);
const distRiver=(x,y)=>{let m=1e9;for(const [a,b] of river){const d=(a-x)**2+(b-y)**2;if(d<m)m=d}return Math.sqrt(m)};
const POND={x:31.2,y:28.6,rx:2.6,ry:2.0};
const inPond=(x,y,m=0)=>((x-POND.x)/(POND.rx+m))**2+((y-POND.y)/(POND.ry+m))**2<1;
const FIELDS=[];const GARDENS=[];

/* ---------- depth-sorted things ---------- */
const items=[];const add=(key,fn)=>items.push({key,fn});
const anchors=[];const anchor=(x,y,what,water=false)=>anchors.push([x,y,what,water]);
const inWater=(x,y)=>distRiver(x,y)<RW/2||inPond(x,y);
const occupied=[];
// h = how tall the thing stands (farm px): the walk graph keeps grass routes out of the area a tall object hides on screen
function claim(x0,y0,x1,y1,tag,h=0){occupied.push(Object.assign([x0,y0,x1,y1],{tag,h}))}
const FENCES=[],BRIDGES=[],BENCHES=[],LAMPS=[];
function free(x,y,m=.6){return !occupied.some(r=>x>r[0]-m&&x<r[2]+m&&y>r[1]-m&&y<r[3]+m)}
function blockedArea(x0,y0,x1,y1){for(let x=x0;x<x1;x+=.25)for(let y=y0;y<y1;y+=.25){if(isRoad(x,y)||isPlaza(x,y)||distRiver(x,y)<RW/2+.5||inPond(x,y,.3))return true}return false}
const problems=[];
function building(type,x,y,w=2,h=2,extra=null,name=''){const o={type,x,y,w,h,level:1,jobs:[]};for(const [ax,ay] of [[x,y],[x+w,y],[x,y+h],[x+w,y+h]])anchor(ax,ay,type);if(type!=='teahouse'&&blockedArea(x,y,x+w,y+h))problems.push('building on road/water: '+type+' '+x+','+y);if(!free(x+w/2,y+h/2,-Math.min(w,h)/2+.05))problems.push('overlap '+type+' '+x+','+y);claim(x,y,x+w,y+h,'building',80);
 add(x+w+y+h,()=>{B.TYPES[type](s,o);extra&&extra(o)})}

/* ---------- ground ---------- */
function groundTiles(){
 const pal=['#b9ce98','#bdd29d','#c1d5a3','#b6cd96'];
 for(let x=-60;x<110;x++)for(let y=-60;y<110;y++){
  const p=P(x,y),[sx,sy]=scr(p);if(sx< -120||sx>W+120||sy< -80||sy>H+80)continue;
  const r=hash(x,y);
  if(isPlaza(x,y)){s.tile(x,y,((x+y)&1)?'#e4dcc1':'#ddd4b6','#cbbf9a40');continue}
  if(isRoad(x,y)){s.tile(x,y,'#dbd3ae');const q=P(x+.4,y+.5);s.ellipse(q.x,q.y,3,1,'#c5ba934c');continue}
  if(isLane(x,y)){s.tile(x,y,pal[Math.floor(r*4)],'#a5bd891e');s.poly([P(x+.18,y+.18),P(x+.82,y+.18),P(x+.82,y+.82),P(x+.18,y+.82)],'#e4dcc1');continue}
  s.tile(x,y,pal[Math.floor(r*4)],'#a5bd891e');
  const q=P(x+.48,y+.48);if(r>.56){s.line(q.x-8,q.y,q.x-6,q.y-4,'#8da87255',.8);s.line(q.x-4,q.y+1,q.x-4,q.y-2,'#9aaf7855',.8)}
 }
 s.poly([P(14,14),P(24,14),P(24,24),P(14,24)],null,'#c9bd97',2);
}
function isoStroke(pts,w,col,alpha=1){ctx.save();ctx.transform(TW,TH,-TW,TH,0,0);ctx.globalAlpha=alpha;ctx.beginPath();pts.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.strokeStyle=col;ctx.lineWidth=w;ctx.lineJoin='round';ctx.lineCap='round';ctx.stroke();ctx.restore()}
function isoRect(x0,y0,x1,y1,col){s.poly([P(x0,y0),P(x1,y0),P(x1,y1),P(x0,y1)],col)}
function riverDraw(){
 isoStroke(river,RW+2.1,'#c3cfaa');isoStroke(river,RW+.9,'#ded9b4');
 isoStroke(river,RW,'#a6cdbf');isoRect(2.75,15.4,4.1,18.3,'#a6cdbf');
 isoStroke(river,RW*.62,'#8fbdb4');isoStroke(river,RW*.28,'#80b3ac',.8);
 for(let i=6;i<river.length-4;i+=9){const [x,y]=river[i],p=P(x+(hash(i,1)-.5)*.6,y);s.line(p.x-10,p.y,p.x+12,p.y,'#e8f3ea88',1.6)}
 for(let i=3;i<river.length-2;i+=4){const [x,y]=river[i],[x2,y2]=river[i+1],dx=x2-x,dy=y2-y,L=Math.hypot(dx,dy)||1,nx=-dy/L,ny=dx/L;
  for(const sd of [-1,1]){const k=RW/2+.32,ex=x+nx*k*sd,ey=y+ny*k*sd,p=P(ex,ey);if(isRoad(ex,ey))continue;if(hash(i,sd)>.55)s.ellipse(p.x,p.y,2+(i%3),1.2+(i%2),i%2?'#b8b6a0':'#cfcbb0')}}
 for(let i=10;i<river.length-2;i+=11){const [x,y]=river[i],[x2,y2]=river[i+1],dx=x2-x,dy=y2-y,L=Math.hypot(dx,dy)||1,nx=-dy/L,ny=dx/L;
  for(const sd of [-1,1]){if(hash(i,sd*3)<.4)continue;const k=RW/2-.05,ex=x+nx*k*sd,ey=y+ny*k*sd;if(isRoad(ex,ey)||Math.abs(ey-20)<3||(ex>2&&ex<7&&ey>14&&ey<28))continue;add(ex+ey,()=>reedClump(P(ex,ey),i))}}
}
function reedClump(e,i){for(let k=0;k<4;k++){const bx=e.x+(k-1.5)*3.2,h=14+((i*3+k*5)%7);s.line(bx,e.y,bx+(k%2?2:-2),e.y-h,'#68925d',1.6);if(k%2)s.ellipse(bx+2,e.y-h-2,1.7,4,'#8b6a48')}s.ellipse(e.x,e.y+1,9,2.6,'#7fb092aa')}
function pondDraw(){const c=P(POND.x,POND.y),rx=(POND.rx+POND.ry)*36*.72,ry=rx*.5;
 const blob=(k,ox,oy)=>{ctx.beginPath();for(let i=0;i<=40;i++){const a=i/40*Math.PI*2,r=1+.07*Math.sin(3*a+1)+.05*Math.cos(5*a);const x=c.x+ox+Math.cos(a)*rx*r*k,y=c.y+oy+Math.sin(a)*ry*r*k;i?ctx.lineTo(x,y):ctx.moveTo(x,y)}ctx.closePath()};
 blob(1.12,5,8);ctx.fillStyle='#c3cfaa';ctx.fill();blob(1.06,1,3);ctx.fillStyle='#ded9b4';ctx.fill();blob(1,0,0);ctx.fillStyle='#a6cdbf';ctx.fill();
 const g=ctx.createRadialGradient(c.x-20,c.y-8,6,c.x,c.y,rx*.95);g.addColorStop(0,'#6aa09f');g.addColorStop(.55,'#80b3ac');g.addColorStop(1,'#9fcabc');blob(.84,-4,-2);ctx.fillStyle=g;ctx.fill();
 for(const [dx,dy,w] of [[-50,-14,30],[10,-24,22],[30,8,26],[-30,16,28]])s.line(c.x+dx,c.y+dy,c.x+dx+w,c.y+dy,'#e8f3ea88',1.6);
 for(const [dx,dy,f] of [[-60,10,1],[-20,26,0],[40,18,1],[56,-6,0]]){s.ellipse(c.x+dx,c.y+dy,9,3.6,'#6f9f6e');s.ellipse(c.x+dx+2,c.y+dy-.5,5,1.8,'#86b384');if(f){s.ellipse(c.x+dx,c.y+dy-3,2.6,2,'#f1cdd6');s.ellipse(c.x+dx,c.y+dy-4,1.1,1,'#ecd070')}}
 for(const [dx,dy] of [[-8,-4],[18,4]]){const x=c.x+dx,y=c.y+dy;s.ellipse(x,y+2,12,3,'#9cc6b8');s.ellipse(x,y-3,10,5.5,'#fbf8ef');s.line(x+6,y-5,x+8,y-16,'#fbf8ef',3);s.ellipse(x+9,y-17,3,2.4,'#fbf8ef');s.poly([{x:x+11,y:y-18},{x:x+15,y:y-16.5},{x:x+11,y:y-15.5}],'#e39a4e')}
 for(const a of [0.4,1.6,2.6,3.9,5.2]){const e={x:c.x+Math.cos(a)*rx*.99,y:c.y+Math.sin(a)*ry*.99};add(POND.x+POND.y+Math.sin(a)*2,()=>reedClump(e,Math.round(a*7)))}
}
const CROPS={wheat:['#d8bf6a','#ecd88a'],cabbage:['#7ea05b','#a3c27a'],carrot:['#6f9f5a','#e09a4c'],berry:['#6f9a58','#d9564b'],flax:['#8fae7a','#b9b4e0'],potato:['#7d9a5a','#a9c27a']};
function field(x0,y0,x1,y1,crop,fenced=true){if(blockedArea(x0,y0,x1,y1))problems.push('field on road '+x0+','+y0);claim(x0,y0,x1,y1);FIELDS.push([x0,y0,x1,y1,crop]);
 if(fenced){fence(x0-.1,y0-.1,x1+.1,y0-.1);fence(x0-.1,y0-.1,x0-.1,y1+.1);fence(x0-.1,y1+.1,x1-.6,y1+.1);fence(x1+.1,y0-.1,x1+.1,y1+.1)}}
function fieldsDraw(){for(const [x0,y0,x1,y1,crop] of FIELDS){for(let x=x0;x<x1;x++)for(let y=y0;y<y1;y++)s.tile(x,y,'#b39572','#9a7d5c55');
 const c=CROPS[crop];for(let x=x0;x<x1;x++)for(let y=y0;y<y1;y++)add(x+y+1,()=>{for(let k=0;k<3;k++){const p=P(x+.2+k*.3,y+.5);s.ellipse(p.x,p.y-3,4.5,3.2,c[0]);s.ellipse(p.x-1,p.y-4.5,2.4,1.8,c[1])}})}}
function garden(x0,y0,x1,y1,crop){claim(x0,y0,x1,y1);GARDENS.push([x0,y0,x1,y1,crop])}
function gardensDraw(){for(const [x0,y0,x1,y1,crop] of GARDENS){s.poly([P(x0,y0),P(x1,y0),P(x1,y1),P(x0,y1)],'#a88a66');for(let x=x0+.25;x<x1;x+=.5)s.poly([P(x,y0+.1),P(x+.3,y0+.1),P(x+.3,y1-.1),P(x,y1-.1)],'#8f7354');
 const c=CROPS[crop];for(let x=x0+.4;x<x1;x+=.5)for(let y=y0+.35;y<y1;y+=.45)add(x+y,()=>{const p=P(x,y);s.ellipse(p.x,p.y-2.5,3.6,2.6,c[0]);s.ellipse(p.x-1,p.y-3.5,1.8,1.4,c[1])})}}

/* ---------- objects ---------- */
function hall(){const x0=14.4,y0=14.4,x1=17.8,y1=17.8,Hh=44;claim(14.2,14.2,19.6,19.6,'hall',150);
 add(x1+y1-.01,()=>{B.shadowAt(s,x0,y0,x1,y1,90,36);B.box(s,'#efe3c4',x0,y0,x1,y1,0,Hh);B.plinth(s,'#c2b79c',x0,y0,x1,y1,5);B.corners(s,x0,y0,x1,y1,Hh,'#f9f2de');
  B.L(s,x0,y1,23,x1,y1,23,'#ddd0ae',2);B.L(s,x1,y0,23,x1,y1,23,'#d0c3a2',2);
  for(const xc of [x0+.5,x0+1.3])for(const z of [6,28])B.winY(s,y1,xc,z,.34,12);
  for(const yc of [y0+.5,y0+1.3])for(const z of [6,28])B.winX(s,x1,yc,z,.34,12);
  B.hipRoof(s,x0,y0,x1,y1,Hh,26,'#7c9d83',.16)});
 const tx0=17.5,ty0=17.5,tx1=19.3,ty1=19.3,Ht=104;
 add(tx1+ty1,()=>{B.shadowAt(s,tx0,ty0,tx1,ty1,60,24);B.box(s,'#efe3c4',tx0,ty0,tx1,ty1,0,Ht);B.plinth(s,'#c2b79c',tx0,ty0,tx1,ty1,5);B.corners(s,tx0,ty0,tx1,ty1,Ht,'#f9f2de');
  B.L(s,tx0,ty1,26,tx1,ty1,26,'#ddd0ae',2);B.L(s,tx1,ty0,26,tx1,ty1,26,'#d0c3a2',2);
  B.doorY(s,ty1,(tx0+tx1)/2,.5,20,'#8f7556','#efe5cb',true);B.doorX(s,tx1,(ty0+ty1)/2,.5,20,'#7f6a4d','#e5d9bb',true);
  B.fullBox(s,'#d6cbae',tx0+.3,ty1,tx1-.3,ty1+.22,0,3,'#e3d9bf');B.fullBox(s,'#d6cbae',tx1,ty0+.3,tx1+.22,ty1-.3,0,3,'#e3d9bf');
  const cx=(tx0+tx1)/2;B.winY(s,ty1,cx,33,.3,12);B.winX(s,tx1,cx,33,.3,12);B.winY(s,ty1,cx,54,.26,10);B.winX(s,tx1,cx,54,.26,10);
  B.E(s,cx,ty1,84,7,8,'#f6eed6');B.E(s,cx,ty1,84,5.2,6.2,'#fbf7ea');B.L(s,cx,ty1,84,cx,ty1,89,'#6b5f4c',1.4);B.L(s,cx,ty1,84,cx+.1,ty1,84,'#6b5f4c',1.4);
  B.E(s,tx1,cx,84,7,8,'#e6dcc2');B.E(s,tx1,cx,84,5.2,6.2,'#efe8d6');B.L(s,tx1,cx,84,tx1,cx,89,'#6b5f4c',1.4);
  meta.clock=scr(P(cx,ty1,84));meta.clock2=scr(P(tx1,cx,84));
  B.hipRoof(s,tx0,ty0,tx1,ty1,Ht,44,'#b9724f',.12);
  const t=P(cx,cx,Ht+44);s.line(t.x,t.y,t.x,t.y-14,'#8a7a5c',1.6);s.poly([{x:t.x,y:t.y-14},{x:t.x+11,y:t.y-11},{x:t.x,y:t.y-8}],'#d9866b');s.ellipse(t.x,t.y-15,1.8,1.8,'#d8bf7a');
  // notice board by the hall: the village board of requests
  board(19.9,17.2)});
}
function board(x,y){B.L(s,x,y-.3,0,x,y-.3,26,'#8a6c4c',2.2);B.L(s,x,y+.3,0,x,y+.3,26,'#8a6c4c',2.2);B.Q(s,'#a98260',[x,y-.4,12,x,y+.4,12,x,y+.4,26,x,y-.4,26]);
 for(const [dy,dz,c] of [[-.2,15,'#f6f0de'],[.05,19,'#f2e3b5'],[.25,14,'#f6f0de']])B.Q(s,c,[x+.01,y+dy-.1,dz,x+.01,y+dy+.1,dz,x+.01,y+dy+.1,dz+8,x+.01,y+dy-.1,dz+8]);B.Q(s,'#8a6c4c',[x-.05,y-.45,26,x+.12,y-.45,26,x+.12,y+.45,26,x-.05,y+.45,26])}
const WELLS=[],STALL_BOXES=[];
function well(x,y){WELLS.push([x,y]);anchor(x,y,'well');claim(x-.5,y-.5,x+.5,y+.5,'well',24);add(x+y+.5,()=>{const p=P(x,y);s.shadow(p.x,p.y,24,10);B.cyl(s,x,y,.42,0,14,'#c9bea2','#ddd3b8');B.cyl(s,x,y,.3,13.5,14,'#7fb0ac');
 for(const d of [-1,1]){const q=P(x+d*.3,y-d*.3);s.line(q.x,q.y-12,q.x,q.y-40,'#9e8a60',3)}
 const a=P(x-.45,y+.45,40),b=P(x+.45,y-.45,40),tp=P(x,y,52);s.poly([{x:a.x-4,y:a.y+2},{x:tp.x,y:tp.y},{x:b.x+4,y:b.y+2},{x:b.x+4,y:b.y+6},{x:tp.x,y:tp.y+4},{x:a.x-4,y:a.y+6}],'#8aa98f');s.poly([{x:a.x-4,y:a.y+2},{x:tp.x,y:tp.y},{x:tp.x,y:tp.y+4},{x:a.x-4,y:a.y+6}],'#9db89f');
 const c=P(x,y,30);s.line(c.x-10,c.y,c.x+10,c.y,'#7a6046',2);s.line(c.x,c.y,c.x,c.y+8,'#8b7a60',.8);s.poly([{x:c.x-3,y:c.y+8},{x:c.x+3,y:c.y+8},{x:c.x+2.5,y:c.y+13},{x:c.x-2.5,y:c.y+13}],'#a98763')})}
function lamp(x,y){LAMPS.push([x,y]);anchor(x,y,'lamp');if(isRoad(x,y)||isPlaza(x,y)&&false)problems.push('lamp on road '+x+','+y);claim(x-.15,y-.15,x+.15,y+.15);add(x+y,()=>{const p=P(x,y);s.lantern(p);meta.lamps.push(scr({x:p.x,y:p.y-43}))})}
function tree(x,y,k=1,fruit=null){anchor(x,y,'tree');add(x+y,()=>{s.treeSprite(x,y,k);if(fruit){const p=P(x,y);for(const [dx,dy] of [[-10,-44],[8,-50],[12,-36],[-2,-60],[-14,-54],[4,-40]])s.ellipse(p.x+dx*k,p.y+dy*k,2.4*k,2.4*k,fruit)}})}
function pine(x,y,k=1){anchor(x,y,'pine');add(x+y,()=>{const p=P(x,y),c=ctx;c.save();c.translate(p.x,p.y);c.scale(k,k);s.shadow(0,0,17,7);s.line(0,0,0,-14,'#9e8a60',4);
 for(const [t,w,b] of [[-62,20,-12],[-78,16,-32],[-92,12,-50]]){s.poly([{x:0,y:t},{x:-w,y:b},{x:0,y:b+3}],'#7da073');s.poly([{x:0,y:t},{x:w,y:b},{x:0,y:b+3}],'#71976d')}
 s.poly([{x:0,y:-92},{x:-5,y:-80},{x:0,y:-82}],'#96b183');c.restore()})}
function log(x,y){anchor(x,y,'log');add(x+y,()=>{const p=P(x,y);s.ellipse(p.x+4,p.y+3,24,6,'#41623517');s.poly([{x:p.x-22,y:p.y-12},{x:p.x+14,y:p.y+6},{x:p.x+14,y:p.y-4},{x:p.x-22,y:p.y-22}],'#9c7a58');s.poly([{x:p.x-22,y:p.y-12},{x:p.x+14,y:p.y+6},{x:p.x+14,y:p.y+2},{x:p.x-22,y:p.y-16}],'#86684b');s.ellipse(p.x+14,p.y+1,4,5,'#d9bd8a');s.ellipse(p.x+14,p.y+1,1.8,2.2,'#b8955f');s.ellipse(p.x-6,p.y-14,4,2,'#86ad70')})}
function stumpSmall(x,y){anchor(x,y,'stump');add(x+y,()=>{B.cyl(s,x,y,.2,0,9,'#9c7a58','#d9bd8a');const p=P(x,y,9);s.ellipse(p.x,p.y,4,2,'#c4a36e')})}
function boulder(x,y){anchor(x,y,'boulder');add(x+y,()=>{const p=P(x,y);s.ellipse(p.x+5,p.y+3,22,7,'#7d806e30');s.poly([{x:p.x-18,y:p.y+2},{x:p.x-14,y:p.y-14},{x:p.x-2,y:p.y-22},{x:p.x+12,y:p.y-18},{x:p.x+19,y:p.y-4},{x:p.x+14,y:p.y+4},{x:p.x,y:p.y+7}],'#a9ab9a');s.poly([{x:p.x+12,y:p.y-18},{x:p.x+19,y:p.y-4},{x:p.x+14,y:p.y+4},{x:p.x+6,y:p.y-6}],'#999b8a');s.poly([{x:p.x-14,y:p.y-14},{x:p.x-2,y:p.y-22},{x:p.x+4,y:p.y-12},{x:p.x-8,y:p.y-8}],'#bfc1b0');s.ellipse(p.x-6,p.y-18,6,2.4,'#86ad70')})}
function mushrooms(x,y){anchor(x,y,'mushrooms');add(x+y,()=>{const p=P(x,y);for(const [dx,dy,k] of [[-4,0,1],[4,2,.8],[1,-3,.7]]){s.line(p.x+dx,p.y+dy,p.x+dx,p.y+dy-5*k,'#f3ead0',2*k);s.ellipse(p.x+dx,p.y+dy-6*k,4.5*k,3*k,'#c9604f');s.ellipse(p.x+dx-1,p.y+dy-7*k,1,.8,'#f6e9d8')}})}
const BUSHES=[];
function bush(x,y,berry){BUSHES.push([x,y]);anchor(x,y,'bush');add(x+y,()=>{const p=P(x,y);s.ellipse(p.x+3,p.y+2,12,4.5,'#6f8e5a30');s.ellipse(p.x-5,p.y-3,7,6,'#78a269');s.ellipse(p.x+4,p.y-4,6.5,5.5,'#86b074');s.ellipse(p.x-1,p.y-8,5.5,5,'#8fbb7c');if(berry){s.ellipse(p.x+5,p.y-6,1.3,1.3,'#d46f6a');s.ellipse(p.x-3,p.y-4,1.2,1.2,'#d46f6a')}})}
function flowers(x,y){anchor(x,y,'flowers');add(x+y,()=>{const p=P(x,y),cols=['#e7a8b5','#f1dc8a','#c3b0de','#f4f1e6'];for(let i=0;i<6;i++){const fx=p.x+(i-2.5)*4.3,fy=p.y+((i*5)%4)-1,h=6+((i*3)%4);s.line(fx,fy,fx,fy-h,'#7ea468',1);s.ellipse(fx,fy-h-1,2.1,1.8,cols[(i+Math.floor(x))%4]);s.ellipse(fx,fy-h-1,.8,.7,'#d9a93d')}})}
function rock(x,y){anchor(x,y,'rock');add(x+y,()=>{const p=P(x,y);s.ellipse(p.x+3,p.y+2,10,3.6,'#7d806e30');s.ellipse(p.x,p.y-1,8.5,4.4,'#9c9e8e');s.ellipse(p.x-1,p.y-4,7,5,'#b1b3a2');s.ellipse(p.x-2,p.y-5.5,3,1.6,'#cfd1c0')})}
function fence(x1,y1,x2,y2){FENCES.push([x1,y1,x2,y2]);const n=Math.max(1,Math.round(Math.hypot(x2-x1,y2-y1)/1.2));for(let i=0;i<n;i++){const a=[x1+(x2-x1)*i/n,y1+(y2-y1)*i/n],b=[x1+(x2-x1)*(i+1)/n,y1+(y2-y1)*(i+1)/n];add(Math.max(a[0],b[0])+Math.max(a[1],b[1])-.05,()=>B.rail(s,a[0],a[1],b[0],b[1],10,'#b79f72'))}}
function bench(x,y,axis='x'){BENCHES.push([x,y,axis]);anchor(x,y,'bench');claim(x-.35,y-.35,x+.35,y+.35);add(x+y,()=>{if(axis==='x'){B.fullBox(s,'#b48f66',x-.32,y-.12,x+.32,y+.12,6,8,'#c9a57a');for(const dx of [-.26,.26]){B.L(s,x+dx,y+.1,0,x+dx,y+.1,6,'#8a6c4c',1.8);B.L(s,x+dx,y-.1,0,x+dx,y-.1,14,'#8a6c4c',1.8)}B.Q(s,'#b48f66',[x-.32,y-.12,10,x+.32,y-.12,10,x+.32,y-.12,15,x-.32,y-.12,15])}
 else{B.fullBox(s,'#b48f66',x-.12,y-.32,x+.12,y+.32,6,8,'#c9a57a');for(const dy of [-.26,.26]){B.L(s,x+.1,y+dy,0,x+.1,y+dy,6,'#8a6c4c',1.8);B.L(s,x-.1,y+dy,0,x-.1,y+dy,14,'#8a6c4c',1.8)}B.Q(s,'#a07e58',[x-.12,y-.32,10,x-.12,y+.32,10,x-.12,y+.32,15,x-.12,y-.32,15])}})}
function bales(x,y){anchor(x,y,'bales');claim(x-.3,y-.3,x+.7,y+.5);add(x+y+.6,()=>{B.bale(s,x,y,.34,11);B.bale(s,x+.42,y+.1,.34,11);B.bale(s,x+.2,y+.05,.3,11)})}
function haystack(x,y){anchor(x,y,'haystack');claim(x-.6,y-.6,x+.6,y+.6,'haystack',40);add(x+y+.5,()=>{const p=P(x,y);s.shadow(p.x,p.y,26,10);ctx.beginPath();ctx.moveTo(p.x-24,p.y);ctx.bezierCurveTo(p.x-26,p.y-26,p.x-12,p.y-40,p.x,p.y-40);ctx.bezierCurveTo(p.x+12,p.y-40,p.x+26,p.y-26,p.x+24,p.y);ctx.quadraticCurveTo(p.x,p.y+9,p.x-24,p.y);ctx.fillStyle='#e0c97c';ctx.fill();
 ctx.beginPath();ctx.moveTo(p.x+4,p.y+6);ctx.bezierCurveTo(p.x+16,p.y,p.x+24,p.y-14,p.x+20,p.y-26);ctx.bezierCurveTo(p.x+26,p.y-12,p.x+26,p.y-2,p.x+24,p.y);ctx.closePath();ctx.fillStyle='#ccb465';ctx.fill();for(const dx of [-12,-2,8])s.line(p.x+dx,p.y-4,p.x+dx+4,p.y-26,'#f0dc98',1.2);s.line(p.x,p.y-40,p.x,p.y-47,'#9e8a60',2)})}
function laundry(x,y){anchor(x,y-.85,'laundry');anchor(x,y+.85,'laundry');claim(x-.1,y-.9,x+.1,y+.9);add(x+y+.8,()=>{const a=[x,y-.85],b=[x,y+.85];for(const q of [a,b])B.L(s,q[0],q[1],0,q[0],q[1],26,'#9e8a60',2);
 const pts=[];for(let i=0;i<=10;i++){const t=i/10;pts.push(P(x,a[1]+(b[1]-a[1])*t,24-5*Math.sin(Math.PI*t)))}ctx.beginPath();pts.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.strokeStyle='#8a8478';ctx.lineWidth=.8;ctx.stroke();
 ['#f4efe2','#e7a8b5','#a9c7d6','#f1dc8a'].forEach((c,i)=>{const t=.18+i*.2,yy=a[1]+(b[1]-a[1])*t,z=24-5*Math.sin(Math.PI*t);B.Q(s,c,[x,yy-.12,z,x,yy+.12,z,x,yy+.12,z-11,x,yy-.12,z-9])})})}
function shed(x,y,col='#c9a672'){anchor(x,y,'shed');anchor(x+1,y+1,'shed');claim(x,y,x+1,y+1,'shed',30);add(x+y+2,()=>{B.shadowAt(s,x,y,x+1,y+1,36,14);B.shedBox(s,col,x,y,x+1,y+1,0,16,22);B.boards(s,'y',y+1,x,x+1,0,16,4,'rgba(80,55,30,.22)');B.doorY(s,y+1,x+.5,.34,13,'#8f7556');B.shedRoof(s,x,y,x+1,y+1,16,22,'#8f7a6a',.1)})}
const PADS=[],PADS2=[];
function playground(x,y){claim(x,y,x+3,y+2.6);PADS.push([x,y]);add(x+y+5,()=>{
 // sandbox
 B.fullBox(s,'#c9a672',x+.3,y+1.4,x+1.4,y+2.4,0,4,'#ead9a4');for(const [a,b] of [[.6,1.8],[1,2.1]]){const p=P(x+a,y+b,4);s.ellipse(p.x,p.y,4,2,'#d8c690')}
 // swings
 const sx=x+1.9,sy=y+.3;B.L(s,sx,sy,0,sx,sy,34,'#8a6c4c',2.4);B.L(s,sx+.9,sy,0,sx+.9,sy,34,'#8a6c4c',2.4);B.L(s,sx,sy,34,sx+.9,sy,34,'#d96f5e',3);
 for(const k of [.3,.62]){B.L(s,sx+k,sy,34,sx+k,sy,10,'#7a7468',.8);B.fullBox(s,'#e2a64c',sx+k-.1,sy-.07,sx+k+.1,sy+.07,9,11,'#f2c46a')}
 // slide
 const lx=x+1.9,ly=y+1.4;B.L(s,lx,ly,0,lx,ly,22,'#8fb0c6',2);B.L(s,lx,ly+.4,0,lx,ly+.4,22,'#8fb0c6',2);B.fullBox(s,'#a9c4d6',lx-.1,ly-.05,lx+.4,ly+.45,20,22,'#c3d8e4');B.Q(s,'#e79a8e',[lx+.4,ly,22,lx+.4,ly+.4,22,lx+1,ly+.4,1,lx+1,ly,1]);
 })}
function chapel(x,y){claim(x,y,x+2.4,y+2.6,'building',90);add(x+2.4+y+2.6,()=>{const g=B.gparams({x0:x+.2,y0:y+.2,x1:x+2.2,y1:y+2.4,H:34,col:'#f1e6cc',roof:'#7f8fa0',axis:'x',prof:B.GABLE,R:30,ov:.12,base:'#c2b79c',corner:'#fbf4e2',trim:'#e6dccb'},{});
 B.body(s,g);B.doorX(s,g.x1,(g.y0+g.y1)/2,.42,22,'#8b6a4e','#efe5cb',true);B.winY(s,g.y1,x+.8,12,.22,14,'#a9c4d6');B.winY(s,g.y1,x+1.6,12,.22,14,'#a9c4d6');
 // carved trim along the eaves
 for(let k=0;k<8;k++){const yy=g.y0+.1+k*.27;B.E(s,g.x1+.02,yy,g.H-2,2,2,'#d8c6a2')}
 B.roofOf(s,g);
 // bell tower with an onion dome over the gable end
 const bx=g.x1-.55,by=(g.y0+g.y1)/2;B.fullBox(s,'#f1e6cc',bx-.32,by-.32,bx+.32,by+.32,g.H+12,g.H+34,'#e6dcc2');B.Q(s,'#5f554a',[bx-.18,by+.32,g.H+18,bx+.18,by+.32,g.H+18,bx+.18,by+.32,g.H+30,bx-.18,by+.32,g.H+30]);
 const d=P(bx,by,g.H+34);ctx.beginPath();ctx.moveTo(d.x-15,d.y);ctx.bezierCurveTo(d.x-22,d.y-14,d.x-6,d.y-22,d.x,d.y-34);ctx.bezierCurveTo(d.x+6,d.y-22,d.x+22,d.y-14,d.x+15,d.y);ctx.closePath();ctx.fillStyle='#6f9fb0';ctx.fill();
 ctx.beginPath();ctx.moveTo(d.x+2,d.y);ctx.bezierCurveTo(d.x+10,d.y-10,d.x+6,d.y-20,d.x,d.y-34);ctx.bezierCurveTo(d.x+6,d.y-22,d.x+22,d.y-14,d.x+15,d.y);ctx.closePath();ctx.fillStyle='#5d8c9e';ctx.fill();
 s.line(d.x,d.y-34,d.x,d.y-46,'#c9a85f',1.8);s.line(d.x-4,d.y-42,d.x+4,d.y-42,'#c9a85f',1.6)})}
function watermill(){const x0=-.4,y0=15.2,x1=2.9,y1=18.4,Hm=36;claim(x0,y0,x1+.9,y1,'building',70);
 add(x1+y1,()=>{const g=B.gparams({x0,y0,x1,y1,H:Hm,col:'#e6d6b0',roof:'#a86f58',axis:'y',prof:B.GABLE,R:26,ov:.14,base:'#a99d84',baseH:9,corner:'#f6eed6',trim:'#e9c5b2'},{});
  B.body(s,g);B.boards(s,'x',x1,y0,y1,10,Hm,6,'rgba(120,90,60,.16)');
  B.doorY(s,y1,x0+1.0,.42,21);B.winY(s,y1,x0+2.2,12,.32,12);B.winX(s,x1,y0+.7,20,.3,11);
  B.roofOf(s,g);B.chimney(s,x0+.9,y0+1.0,Hm+12,Hm+30,'#a8826a',.1);B.smoke(s,x0+.9,y0+1.0,Hm+30);
  const wc=[x1+.55,(y0+y1)/2,26];const ax=P(x1,wc[1],wc[2]),hb=P(...wc);s.line(ax.x,ax.y,hb.x,hb.y,'#6f5640',4);s.ellipse(hb.x,hb.y,4,4,'#6f5640');
  meta.wheel=scr(hb);
  const f=P(wc[0],wc[1],0);s.ellipse(f.x,f.y+2,20,5,'#e8f3eacc');s.ellipse(f.x+6,f.y+5,10,2.5,'#ffffffaa');
  // tail water: foam under the wheel and ripples running downstream back into the river
  for(const [dv,w] of [[.6,16],[1.2,12],[1.8,9]]){const r=P(wc[0]+.1,wc[1]+dv,0);s.line(r.x-w,r.y,r.x+w*.6,r.y,'#e8f3eacc',1.6)}});
}
function headrace(){const fu=3.45,v0=13.55,v1=16.35,za=62,zb=56;claim(-.3,12.7,4.1,13.6,'headrace',60);
 // low weir across the river: stones + timber crest, water spilling over it
 add(4.1+13.5,()=>{const a0=-.3,a1=3.3,y=13.05;B.Q(s,'#9e9886',[a0,y+.35,0,a1,y+.35,0,a1,y+.35,7,a0,y+.35,7]);B.Q(s,'#bdb6a2',[a0,y,7,a1,y,7,a1,y+.35,7,a0,y+.35,7]);
  B.Q(s,'#8c6a46',[a0,y+.02,7,a1,y+.02,7,a1,y+.12,9,a0,y+.12,9]);
  for(let u=a0+.2;u<a1;u+=.45){const p=P(u,y+.42,3);s.ellipse(p.x,p.y+2,7,2.2,'#eef7f2dd');s.line(p.x-3,p.y-3,p.x-2,p.y+2,'#f4fbf8',1.2)}
  // sluice box (header tank) at the east end of the weir, open to the river
  B.fullBox(s,'#9c7a54',fu-.28,v0-.55,fu+.28,v0+.02,0,za+4,'#b08a62');B.boards(s,'y',v0+.02,fu-.28,fu+.28,2,za+4,6,'rgba(70,45,25,.3)');B.boards(s,'x',fu+.28,v0-.55,v0+.02,2,za+4,6,'rgba(60,40,20,.3)');
  B.Q(s,'#8fc7c0',[fu-.22,v0-.49,za+4.2,fu+.22,v0-.49,za+4.2,fu+.22,v0-.04,za+4.2,fu-.22,v0-.04,za+4.2]);
  B.L(s,fu-.32,v0-.6,za+4,fu+.32,v0-.6,za+4,'#7f6146',1.6);
  // sluice gate wheel on top
  const g=P(fu,v0-.3,za+12);B.L(s,fu,v0-.3,za+4,fu,v0-.3,za+12,'#6f5640',1.6);s.ellipse(g.x,g.y,5,2.4,'none');ctx.beginPath();ctx.ellipse(g.x,g.y,5,2.5,0,0,Math.PI*2);ctx.strokeStyle='#6f5640';ctx.lineWidth=1.6;ctx.stroke();
 });
 // open flume on trestles along the bank, falling gently to the top of the wheel; drawn in front of the mill wall
 add(21.35,()=>{for(const v of [14.3,15.1,15.85]){const z=za+(zb-za)*(v-v0)/(v1-v0);B.L(s,fu-.12,v,0,fu-.12,v,z-4,'#7f6146',2.4);B.L(s,fu+.12,v,0,fu+.12,v,z-4,'#6c5039',2.4);B.L(s,fu-.12,v,z*.45,fu+.12,v,z*.45,'#8a6a4a',1.4);const b=P(fu,v,0);s.ellipse(b.x,b.y,6,2,'#d8ece4aa')}
  B.Q(s,'#8a6a4a',[fu+.14,v0,za-4,fu+.14,v1,zb-4,fu+.14,v1,zb+1,fu+.14,v0,za+1]);
  B.Q(s,'#a07c56',[fu-.14,v1,zb-4,fu+.14,v1,zb-4,fu+.14,v1,zb+1,fu-.14,v1,zb+1]);
  B.Q(s,'#86c2bb',[fu-.1,v0,za,fu+.1,v0,za,fu+.1,v1,zb,fu-.1,v1,zb]);
  for(let k=1;k<5;k++){const v=v0+(v1-v0)*k/5,z=za+(zb-za)*k/5;B.L(s,fu-.03,v-.12,z+.3,fu-.03,v+.08,z+.3,'#e8f6f2',1.1)}
  B.L(s,fu-.14,v0,za+1,fu-.14,v1,zb+1,'#b08a62',1.4);
  // water pouring from the open end onto the top of the wheel
  const e=P(fu,v1,zb),f=P(fu,v1+.35,zb-9);ctx.beginPath();ctx.moveTo(e.x-2,e.y);ctx.quadraticCurveTo(e.x-3,e.y+4,f.x,f.y);ctx.strokeStyle='#cfeee8';ctx.lineWidth=3;ctx.lineCap='round';ctx.stroke()});
}
// construction sites (FARM_VILLAGE_CONSTRUCTION.md): only the level trodden ground is painted; the stages (soon, pit, frame, done)
// are vector layers of the game drawn by build.js over this ground
const SITES={};
function site(id,x,y,w,h,label){if(blockedArea(x,y,x+w,y+h))problems.push('site on road/water '+label);claim(x,y,x+w,y+h,'site',40);for(const [ax,ay] of [[x,y],[x+w,y+h]])anchor(ax,ay,'site');
 PADS2.push([x,y,w,h]);SITES[id]=[x,y,x+w,y+h];meta.sites.push({id,label,at:scr(P(x+w/2,y+h/2,46))})}
// the market rows: empty places for six stalls on the plaza (trodden ground and four stub posts); the stalls are layers of the game
const STALL_SLOTS=[];
function stallSlot(x,y){const x1=x+1.4,y1=y+1;if(!free(x+.7,y+.5,.6))problems.push(`stall slot on an object at ${x},${y}`);
 STALL_BOXES.push([x,y,x1,y1]);STALL_SLOTS.push([x,y,x1,y1]);anchor(x,y,'stall');anchor(x1,y1,'stall');claim(x,y,x1,y1,'stall',34);
 add(x+y+.2,()=>{s.poly([P(x,y),P(x1,y),P(x1,y1),P(x,y1)],'#d3c6a0');s.poly([P(x,y),P(x1,y),P(x1,y1),P(x,y1)],null,'#bcae86',1.2);
  for(const [a,b] of [[x+.06,y+.06],[x1-.06,y+.06],[x+.06,y1-.06],[x1-.06,y1-.06]])B.fullBox(s,'#9c7d58',a-.04,b-.04,a+.04,b+.04,0,5,'#b79a72')})}
function bearDen(X,Y){// Bear Pukh's den: a half-buried log house under a turf roof, round door toward the lane
 const x0=26.75,y0=38.0,x1=28.3,y1=39.75,Hd=22;claim(X,Y,X+2.6,Y+2.6,'building',50);for(const [ax,ay] of [[X,Y],[X+2.6,Y+2.6]])anchor(ax,ay,'den');
 add(X+2.6+Y+2.6,()=>{
  // earth mound grown over the back of the house
  const m=P(x0+.1,y0+.05);s.ellipse(m.x+12,m.y+8,96,30,'#41623517');const hill=(w,h,dy,c)=>{ctx.beginPath();ctx.moveTo(m.x-w,m.y+dy);ctx.bezierCurveTo(m.x-w*.9,m.y+dy-h*1.15,m.x+w*.55,m.y+dy-h*1.3,m.x+w,m.y+dy);ctx.ellipse(m.x,m.y+dy,w,w*.36,0,0,Math.PI);ctx.closePath();ctx.fillStyle=c;ctx.fill()};hill(92,58,0,'#9c7c5a');hill(88,56,-4,'#93b27c');hill(60,40,-14,'#a3c08a');s.ellipse(m.x-26,m.y-46,16,6,'#b3cf99');
  for(const [dx,dy] of [[-40,-10],[-12,-30],[22,-22],[44,-6]]){s.ellipse(m.x+dx,m.y+dy,5,3,'#86ad70')}
  B.ground(s,x1,y0-.2,X+2.6,Y+2.6,'rgba(205,185,140,.35)');
  const g=B.gparams({x0,y0,x1,y1,H:Hd,col:'#b48a62',roof:'#86a86c',axis:'x',prof:B.GABLE,R:17,ov:.16,base:'#8f7a62',baseH:5,corner:'#c9a272',trim:'#a9c58f'},{});
  B.shadowAt(s,x0,y0,x1,y1,56,22);B.body(s,g);
  B.boards(s,'y',y1,x0,x1,4,Hd,4,'rgba(80,50,30,.32)');B.boards(s,'x',x1,y0,y1,4,Hd,4,'rgba(70,45,25,.34)');
  // log ends at the corners
  for(let z=6;z<Hd;z+=4){B.E(s,x1+.03,y1+.03,z,2.2,1.8,'#d9bd8a')}
  // round window on the long wall
  const wv=[x0+.55,y1,10];B.E(s,...wv,6.5,6.5,'#f3ead2');B.E(s,...wv,4.6,4.6,'#a9c7c6');B.L(s,wv[0]-.1,y1,13,wv[0]+.1,y1,13,'#f3ead2',1);
  const wp=P(...wv);meta.den={window:scr(wp)};
  // round door in the gable wall (faces the lane), with a step
  const dc=(y0+y1)/2,pts=[];for(let i=0;i<=20;i++){const a=Math.PI*i/20;pts.push(x1,dc+Math.cos(a)*.3,9+Math.sin(a)*10)}
  B.Q(s,'#c9a272',[x1,dc-.34,0,...pts.map((v,i)=>i%3===1?v+Math.sign(v-dc)*.04*0:v),x1,dc+.34,0].map((v,i)=>i===2||i===pts.length+2?0:v));
  const dp=[];for(let i=0;i<=20;i++){const a=Math.PI*i/20;dp.push(x1+.01,dc+Math.cos(a)*.26,9+Math.sin(a)*8.5)}
  B.Q(s,'#7a5a3c',[x1+.01,dc+.26,0,...dp,x1+.01,dc-.26,0]);B.L(s,x1+.01,dc,1,x1+.01,dc,16,'#5f4530',1);B.E(s,x1+.01,dc-.14,8,1.4,1.4,'#e8d9a8');
  B.fullBox(s,'#a99c84',x1,dc-.32,x1+.3,dc+.32,0,3,'#c2b69c');
  B.roofOf(s,g);
  for(const [a,b,c] of [[x0+.3,y0+.4,0],[x0+.9,y1-.2,1],[x1-.2,y0+.6,0],[x0+1.2,y0+.2,1]]){const q=P(a,b,Hd+11);s.ellipse(q.x,q.y,5,2.4,c?'#9cc183':'#7fa36a');s.line(q.x-2,q.y,q.x-3,q.y-4,'#7fa36a',1)}
  // stone chimney through the turf with a curl of smoke
  B.chimney(s,x0+.45,y0+.5,Hd+8,Hd+30,'#a39b8c',.1);B.smoke(s,x0+.45,y0+.5,Hd+30);meta.den.smoke=s.smk[s.smk.length-1];
  // at the door: a straw beehive on a stump, a keg, a stack of mugs, a crate of cans
  B.cyl(s,x1+.45,y0+.15,.16,0,8,'#9c7a58','#d9bd8a');
  const h=P(x1+.45,y0+.15,8);for(const [r,dy,c] of [[9,0,'#d9b86a'],[8,-5,'#e2c47a'],[6.5,-10,'#d9b86a'],[4.5,-14,'#e8cf8c']])s.ellipse(h.x,h.y+dy-2,r,4.2,c);s.ellipse(h.x+1,h.y-3,1.8,1.6,'#5f4530');
  B.barrel(s,x1+.55,y1-.2,.17,15,'#b98b5c');B.L(s,x1+.6,y1-.08,9,x1+.72,y1-.08,9,'#8a8478',1.6);
  B.cyl(s,x1+.95,y1+.35,.16,0,7,'#9c7a58','#d9bd8a');for(const [dx,dz,c] of [[-.05,7,'#e9e2d0'],[.06,7,'#c9604f'],[0,11,'#e9e2d0']]){B.cyl(s,x1+.95+dx,y1+.35-dx,.05,dz,dz+4,c,'#f6f0e2')}
  B.fullBox(s,'#c9a672',x0+.2,y1+.2,x0+.8,y1+.5,0,6,'#d8b886');['#c25a6a','#e3b04a','#7fa36a','#c25a6a'].forEach((c,k)=>B.cyl(s,x0+.28+k*.15,y1+.35,.045,6,10,c,'#f1ead8'));
 })}
function bridge(x0,x1,y0,y1){BRIDGES.push([x0,y0,x1,y1]);add(x1+y1+.5,()=>{const Z=8;
 for(const xx of [x0+1.1,x1-1.1])for(const yy of [y0+.15,y1-.15]){const t=P(xx,yy,Z),b=P(xx,yy,-8);s.line(t.x,t.y,b.x,b.y,'#5d4733',3.6);s.ellipse(b.x,b.y,4.6,1.9,'#8fbab0')}
 B.Q(s,'#6c5039',[x1,y0,Z,x1,y1,Z,x1,y1,Z-5,x1,y0,Z-5]);B.Q(s,'#7e6044',[x0,y1,Z,x1,y1,Z,x1,y1,Z-5,x0,y1,Z-5]);
 B.Q(s,'#bb9365',[x0,y0,Z,x1,y0,Z,x1,y1,Z,x0,y1,Z]);for(let xx=x0+.25;xx<x1;xx+=.25)B.L(s,xx,y0,Z,xx,y1,Z,'#8c6a46',1);
 for(const yy of [y0+.05,y1-.05]){for(let i=0;i<=5;i++){const xx=x0+(x1-x0)*i/5;B.L(s,xx,yy,Z,xx,yy,Z+13,'#75583c',2.6)}B.L(s,x0,yy,Z+13,x1,yy,Z+13,'#d3ad78',2);B.L(s,x0,yy,Z+7,x1,yy,Z+7,'#c4a072',1.2)}})}
function pier(x0,x1,y0,y1){anchor(x1,(y0+y1)/2,'pier land end');anchor(x0,(y0+y1)/2,'pier water end',true);if(inWater(x1+.1,(y0+y1)/2))problems.push('pier does not reach the bank');
 const bx=x0+.85,by=y1+.75;anchor(bx,by,'boat',true);if(!inWater(bx,by))problems.push('boat not on water');
 add(x1+y1,()=>{const Z=5;
 // shade of the deck on the water
 s.poly([P(x0,y0+.25,-2),P(x1-.6,y0+.25,-2),P(x1-.6,y1+.25,-2),P(x0,y1+.25,-2)],'#4b7f7a30');
 for(let xx=x0+.2;xx<x1-.3;xx+=.55)for(const yy of [y0+.08,y1-.08]){const t=P(xx,yy,Z),b=P(xx,yy,-9);s.line(t.x,t.y,b.x,b.y,'#5d4733',3);if(inWater(xx,yy))s.ellipse(b.x,b.y,4,1.6,'#8fbab0')}
 B.Q(s,'#6c5039',[x1,y0,Z,x1,y1,Z,x1,y1,0,x1,y0,0]);B.Q(s,'#7e6044',[x0,y1,Z,x1,y1,Z,x1,y1,Z-4,x0,y1,Z-4]);B.Q(s,'#bb9365',[x0,y0,Z,x1,y0,Z,x1,y1,Z,x0,y1,Z]);for(let xx=x0+.22;xx<x1;xx+=.22)B.L(s,xx,y0,Z,xx,y1,Z,'#8c6a46',.9);
 // mooring post, rod and a bucket on the deck
 const mp=P(x0+.12,y1-.08,Z+12);B.L(s,x0+.12,y1-.08,Z,x0+.12,y1-.08,Z+12,'#5d4733',3.2);
 const r=P(x0+.7,(y0+y1)/2,Z);s.line(r.x,r.y,r.x-30,r.y-40,'#7a6046',1.4);s.line(r.x-30,r.y-40,r.x-36,r.y+12,'#d8d2c0',.6);B.cyl(s,x0+1.1,(y0+y1)/2,.12,Z,Z+9,'#a98763','#7fb0ac');
 // rowing boat on the water, tied to the post
 const b=P(bx,by,0);s.ellipse(b.x+2,b.y+4,26,6,'#9cc6b8');
 s.poly([{x:b.x-24,y:b.y-6},{x:b.x+18,y:b.y+12},{x:b.x+26,y:b.y+5},{x:b.x+6,y:b.y-8},{x:b.x-16,y:b.y-13}],'#a8774f');
 s.poly([{x:b.x-17,y:b.y-10},{x:b.x+6,y:b.y-4},{x:b.x+20,y:b.y+5},{x:b.x+17,y:b.y+8},{x:b.x-20,y:b.y-6}],'#7c5b40');
 s.line(b.x-6,b.y-6,b.x+4,b.y-1,'#c9a272',2.4);
 ctx.beginPath();ctx.moveTo(b.x+22,b.y+6);ctx.quadraticCurveTo((b.x+mp.x)/2+4,Math.max(b.y,mp.y)+6,mp.x,mp.y+2);ctx.strokeStyle='#d8cfb4';ctx.lineWidth=1.2;ctx.stroke()})}
function stump(x,y){claim(x-1.4,y-1.4,x+1.4,y+1.4,'building',90);add(x+y+1.4,()=>{const p=P(x,y);s.shadow(p.x,p.y,62,24);
 B.cyl(s,x,y,1.05,0,62,'#a98763','#d9bd8a');const t=P(x,y,62);s.ellipse(t.x,t.y,36,18,'#e2c896');s.ellipse(t.x,t.y,24,12,'#d6b882');s.ellipse(t.x,t.y,12,6,'#e2c896');
 for(const [dx,dy] of [[-48,4],[44,6],[-20,22],[24,22]])s.ellipse(p.x+dx,p.y+dy,12,4,'#97764f');
 const d=P(x+.74,y+.74,0);s.poly([{x:d.x-10,y:d.y},{x:d.x-10,y:d.y-20},{x:d.x-5,y:d.y-27},{x:d.x+5,y:d.y-27},{x:d.x+10,y:d.y-20},{x:d.x+10,y:d.y}],'#8f7556');s.ellipse(d.x+5,d.y-11,1.4,1.4,'#e8d9a8');
 for(const [dx,dy] of [[-30,-34],[34,-40]]){s.ellipse(p.x+dx,p.y+dy,7,7,'#f3ead2');s.ellipse(p.x+dx,p.y+dy,5,5,'#a9c7c6');meta.windows.push([...scr({x:p.x+dx,y:p.y+dy}),'r'])}
 for(const [dx,k] of [[-14,1],[10,.8]]){s.line(t.x+dx,t.y,t.x+dx,t.y-8,'#f3ead0',3*k);s.ellipse(t.x+dx,t.y-9,8*k,5*k,'#d5735f');s.ellipse(t.x+dx-2,t.y-11,1.8,1.3,'#f6e9d8')}
 // a crooked chimney pipe and a lantern on a stick
 B.fullBox(s,'#8a8a80',x-.5,y-.3,x-.36,y-.16,58,80,'#a3a399');meta.chimneys.push(scr(P(x-.43,y-.23,82)));
 B.flowerPot(s,x+1.2,y+.9);B.flowerPot(s,x+.9,y+1.3)})}
function gate(x,y){anchor(x,y-1.3,'gate post');anchor(x,y+1.3,'gate post');add(x+y+1.3,()=>{
 // gate.js: posts, beam, chains, lantern in the background; the board is the game's button (meta.gate.board)
 meta.gate_art=paintGate(s,ctx,W/2400);meta.gate_art.board=boardSvg()})}
function owl(o){const xm=o.x+o.w/2,p=P(xm-.1,o.y+.6,32+26+6);s.ellipse(p.x,p.y,6,7.5,'#8a6c4c');s.ellipse(p.x,p.y-9,5,4.5,'#8a6c4c');s.ellipse(p.x-2,p.y-9.5,1.8,1.8,'#f3e2a2');s.ellipse(p.x+2,p.y-9.5,1.8,1.8,'#f3e2a2');s.ellipse(p.x,p.y+1,3.6,4.4,'#c9ad86');s.poly([{x:p.x-4,y:p.y-13},{x:p.x-3,y:p.y-16},{x:p.x-1.5,y:p.y-13}],'#8a6c4c');s.poly([{x:p.x+4,y:p.y-13},{x:p.x+3,y:p.y-16},{x:p.x+1.5,y:p.y-13}],'#8a6c4c');
 // stack of books by the door
 const b=P(o.x+o.w+.12,o.y+o.h-.55,0);[['#b4506a',0],['#5f8fb0',4],['#e0b062',8]].forEach(([c,z])=>s.poly([{x:b.x-7,y:b.y-z},{x:b.x+7,y:b.y-z},{x:b.x+7,y:b.y-z-4},{x:b.x-7,y:b.y-z-4}],c))}
function post(o){const x=o.x+o.w+.25,y=o.y+.45;B.L(s,x,y,0,x,y,16,'#6f6a5e',2.2);B.fullBox(s,'#c9604f',x-.13,y-.1,x+.13,y+.1,16,26,'#d97a68');B.Q(s,'#f4ece0',[x+.13,y-.06,19,x+.13,y+.06,19,x+.13,y+.06,22,x+.13,y-.06,22])}

/* ---------- compose ---------- */
// residents' homes (spot = where the resident stands, tile coords)
const SPOT={};
const spot=(name,x,y)=>{SPOT[name]=[x,y];claim(x-.4,y-.4,x+.4,y+.4,'spot')};
hall();
building('house',9.6,15.3,3,2.8,owl,'Филиныч');spot('Филиныч',13.1,17.2);
building('bakery',21.6,10.7,3,3,null,'Агата');spot('Агата',23.0,14.4);
building('tailor',12.4,26.4,3,3,post,'Ёж');spot('Почтальон Ёж',16.4,27.9);
building('garage',29.6,12.3,3,3,null,'Крот');spot('Механик Крот',31.1,15.6);
building('smokehouse',33.4,12.6,2.6,2.6);// forge next to the workshop
building('creamery',6.8,22.4,2.8,2.8,null,'Кая');spot('Кошка Кая',8.4,25.6);
building('soapery',25,19.4,2.8,2.8,null,'Соня');spot('Кошка Соня',26.4,22.6);
building('oil_press',18.8,26.4,2.6,2.6,null,'Игорь');spot('Суслик Игорь',22.2,27.6);
stump(14,-5.6);spot('Неведома Зверушка',15.8,-3.4);
building('mill',7.6,2.6,2.8,2.8);
watermill();headrace();bridge(1.9,6.3,19,21);pier(4.6,7.4,26.4,27.2);
chapel(10.6,7.2);building('loom',15,11.2,3,2.4);// school
// neighbours
building('dairy',6.6,15.6,2.4,2.4);building('noodle_shop',10.4,22.4,2.6,2.6);
building('house',12.4,30.6,2.8,2.6);building('syrupery',19,40.8,2.6,2.4);building('juicery',18.8,30.6,2.6,2.6);
building('sausage_shop',25.4,11.6,2.6,2.6);building('cannery',37.4,12.6,2.6,2.6);
building('house',29.2,19.4,2.8,2.6);building('cowshed',35.6,19.4,3,2.8);building('barn',40,19.4,3,2.8);
building('confectionery',21.6,6.8,2.4,2.4);garden(25.2,23.4,27.6,24.4,'berry');flowers(27.2,24.8);building('pheasantry',25.2,30.4,2.6,2.6);building('goatshed',35.4,25.6,2.6,2.6);building('house',29.4,32,2.6,2.6);
building('yak_pen',19,37.8,2.6,2.4);bearDen(26.4,37.8);building('coop',30.6,37.8,2.4,2.4);
building('apiary',2.6,7.6,2.4,2.4);building('pheasantry',23.6,4.4,2.6,2.6);
building('teahouse',20.6,15.0,2.2,2.2);
// fields and kitchen gardens
field(44,24,48,28,'cabbage');field(39.6,26,43.6,30,'potato');building('feedmill',28.6,4.4,2.8,2.8);field(28,8.6,31,10.8,'carrot',false);
garden(6.4,18.4,8.4,19.0,'cabbage');garden(9.8,18.5,12.4,19.0,'carrot');garden(13,33.5,15.4,34.6,'cabbage');garden(19,33.6,21.6,34.6,'carrot');garden(33.6,22.6,35.2,24.2,'berry');garden(19.6,24.6,21.4,26,'potato');
// plaza life
well(21.8,20.8);
for(let i=0;i<6;i++)stallSlot(14.3+i*1.6,22.3);meta.sites.push({id:'stalls',label:'Торговые ряды',at:scr(P(STALL_SLOTS[0][0]-1.2,23.6,20))});   // caption by the west end, off the stalls
bench(18.2,20.8);bench(23.0,18.4,'y');bench(23.2,21.9,'y');
for(const [x,y] of [[14.4,14.6],[23.6,14.4],[14.4,23.6],[23.6,23.6]])flowers(x,y);
// streets: lamps on verges
for(const [x,y] of [[13.6,18.6],[9,18.6],[6.9,18.6],[-1,18.6],[18.6,13.6],[18.6,9],[18.6,4],[18.6,-1],[15.6,24.6],[15.6,30],[15.6,33.4],[18.4,40],[24.6,15.6],[34,15.6],[39,15.6],[24.6,24.6],[24.6,30],[21.6,34.6],[27,34.6],[33,34.6],[40,34.6],[45,37.4],[29,18.4],[44,15.6],[11.6,21.4],[21.4,11.6],[10,21.4]])lamp(x,y);
gate(36,36);site('tavern',27.4,42.2,2.8,2.4,'Трактир');site('greenhouse',4.8,9.4,2.6,2.4,'Оранжерея');site('fairground',44.2,29.4,2.6,2.4,'Ярмарка');
// village details
bales(43,18.4);haystack(48.6,29);haystack(42.6,31);haystack(32.6,8.6);laundry(12.2,25.0);laundry(28.4,23.0);laundry(17.9,38.6);
shed(9.4,28.4);shed(23.2,31.6);shed(32.4,22.2);shed(28,15);playground(36,29.6);well(29.6,24.8);
fence(9.6,18.3,12.6,18.3);fence(6.6,18.3,8.4,18.3);
// trees: forest edges, orchards, groves; never on roads, water, plaza or buildings
function okTree(x,y,m=.7){if(nearGate(x,y))return false;if(isRoad(x,y)||isPlaza(x,y)||isLane(x,y))return false;for(const [dx,dy] of [[m,0],[-m,0],[0,m],[0,-m]])if(isRoad(x+dx,y+dy)||isPlaza(x+dx,y+dy)||isLane(x+dx,y+dy))return false;if(distRiver(x,y)<RW/2+1.1)return false;if(inPond(x,y,1))return false;return free(x,y,1.0)}
const GATE=[36,36];const nearGate=(x,y)=>Math.hypot(x-GATE[0],y-GATE[1])<4.4;
const trees=[];
// wild lands: a closed ring of forest around the inhabited part, sparser groves inside
const edgeOf=(sx,sy)=>Math.min(sx,W-sx,sy+40,H-sy+80);
for(let i=0;i<30000;i++){const x=-70+rnd()*190,y=-70+rnd()*190,[sx,sy]=scr(P(x,y));if(sx<-40||sx>W+40||sy<-20||sy>H+120)continue;
 const edge=edgeOf(sx,sy);const dense=edge<330?1:edge<470?.4:.05;if(rnd()>dense)continue;if(!okTree(x,y))continue;
 const gap=edge<330?.9:1.5;if(trees.some(t=>(t[0]-x)**2+(t[1]-y)**2<gap*gap))continue;trees.push([x,y,(edge<330?.95:.85)+rnd()*.4,null,edge<470&&rnd()<.35?'pine':null])}
for(let i=0;i<4;i++)for(let j=0;j<3;j++){const x=2.4+i*1.4,y=1.2+j*1.5;if(okTree(x,y,.4))trees.push([x,y,.78,'#d46f6a'])}
for(let i=0;i<3;i++)for(let j=0;j<2;j++){const x=40.6+i*1.4,y=31.6+j*1.4;if(okTree(x,y,.4))trees.push([x,y,.78,['#d46f6a','#e8b64c','#c9604f'][j]])}
for(const t of trees){claim(t[0]-.25,t[1]-.25,t[0]+.25,t[1]+.25,'tree');t[4]==='pine'?pine(t[0],t[1],t[2]):tree(t[0],t[1],t[2],t[3])}
// forest floor in the wild ring: logs, stumps, boulders, clearings with flowers and mushrooms
for(let i=0;i<2600;i++){const x=-70+rnd()*190,y=-70+rnd()*190,[sx,sy]=scr(P(x,y));if(sx<20||sx>W-20||sy<20||sy>H-10)continue;const edge=edgeOf(sx,sy);if(edge>520||!okTree(x,y,.4))continue;const r=rnd();
 r<.12?log(x,y):r<.24?stumpSmall(x,y):r<.36?boulder(x,y):r<.6?bush(x,y,r<.4):r<.85?flowers(x,y):mushrooms(x,y)}
for(let i=0;i<420;i++){const x=-30+rnd()*100,y=-30+rnd()*100;if(!okTree(x,y,.4))continue;const r=rnd();r<.4?bush(x,y,r<.12):r<.8?flowers(x,y):rock(x,y)}

groundTiles();
const GROUND_PX=ctx.getImageData(0,0,W,H).data;   // the bare ground, before anything stands on it (festival snow: bare())
fieldsDraw();gardensDraw();for(const [x,y,w,h] of PADS2){s.poly([P(x,y),P(x+w,y),P(x+w,y+h),P(x,y+h)],'#cbb894');s.poly([P(x,y),P(x+w,y),P(x+w,y+h),P(x,y+h)],null,'#b5a17a',1.2)}for(const [x,y] of PADS){s.poly([P(x,y),P(x+3,y),P(x+3,y+2.6),P(x,y+2.6)],'#ddd3ad');s.poly([P(x,y),P(x+3,y),P(x+3,y+2.6),P(x,y+2.6)],null,'#c5ba93',1.5)}riverDraw();pondDraw();
items.sort((a,b)=>a.key-b.key);for(const it of items)it.fn();
const FULL_PX=ctx.getImageData(0,0,W,H).data;     // everything painted, before the edge shade
// soft edge of the world: forest shade toward the frame, matching the page background at the very edge
ctx.save();ctx.setTransform(1,0,0,1,0,0);
const edgeG=(ax,ay,bx,by)=>{const g=ctx.createLinearGradient(ax,ay,bx,by);g.addColorStop(0,'rgba(104,136,92,.6)');g.addColorStop(.45,'rgba(104,136,92,.22)');g.addColorStop(1,'rgba(104,136,92,0)');ctx.fillStyle=g;ctx.fillRect(0,0,W,H)};
edgeG(0,0,170,0);edgeG(W,0,W-170,0);edgeG(0,0,0,150);edgeG(0,H,0,H-150);
ctx.restore();
for(const [x,y,what,water] of anchors){const w=inWater(x,y);if(w&&!water)problems.push(`${what} in water at ${x.toFixed(1)},${y.toFixed(1)}`);if(!w&&water&&!/pier/.test(what))problems.push(`${what} should be on water at ${x.toFixed(1)},${y.toFixed(1)}`)}
// exported coordinates (screen px of the 2400x1800 world)
meta.windows.push(...s.win.map(w=>[...scr({x:w[1],y:w[2]}),w[0]]));
meta.smoke=[...s.smk.map(p=>scr({x:p[0],y:p[1]})),...meta.chimneys];
meta.sails=s.sails.map(p=>scr({x:p[0],y:p[1]}));
for(const [k,v] of Object.entries(SPOT))meta.spots[k]=scr(P(v[0],v[1]));
meta.hall=scr(P(19.8,19.8));meta.gate=scr(P(36,36));meta.start=scr(P(33.5,36));meta.plaza=[P(14,14),P(24,14),P(24,24),P(14,24)].map(scr);
meta.board=scr(P(20.3,17.2));meta.problems=problems;
if(DEBUG){ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle='#f0f8';for(const [k,[x,y]] of Object.entries(meta.spots)){ctx.fillRect(x-24,y-24-20,48,48)}ctx.fillStyle='#00f8';ctx.fillRect(meta.hall[0]-31,meta.hall[1]-22,62,44);ctx.fillRect(meta.gate[0]-48,meta.gate[1]-24,96,48)}
// walk graph (walk.js): the paths of this plan, checked against everything placed on it
const toWorld=(x,y)=>{const p=P(x,y);return [(OX+K*p.x)*.75,(OY+K*p.y)*.75]};
const toTile=(X,Y)=>{const px=(X/.75-OX)/K,py=(Y/.75-OY)/K;return [(px/TW+py/TH)/2,(py/TH-px/TW)/2]};
// the peddler's place on the plaza by the market stalls: kept free in the walk graph, drawn only during her visit
// Candidates on and around the plaza near the stalls; kept: the cart on free ground, the magpie's figure (≈90 world units tall)
// and the cart away from every tap target of the game (opts.buttons, world units), nearest to the stalls wins.
const STALLS=[18.1,22.9],BUTTONS=opts.buttons||[];
const T2W=(x,y,z=0)=>{const p=P(x,y,z);return [(OX+K*p.x)*.75,(OY+K*p.y)*.75]};
const clearOfButtons=(pt,r)=>BUTTONS.every(([bx,by])=>Math.hypot(bx-pt[0],by-pt[1])>=r);
const cands=[];
for(let gy=19.5;gy<=24.6;gy+=.25)for(let gx=13.5;gx<=24.6;gx+=.25){
 const cart=[gx,gy,gx+1.4,gy+.9],mag=[gx+1.75,gy+.5],app=[gx+1.8,gy+1.2];
 let ok=true;for(let x=cart[0]-.1;x<=cart[2]+.1&&ok;x+=.2)for(let y=cart[1]-.1;y<=cart[3]+.1&&ok;y+=.2)if(!free(x,y,0)||isRoad(x,y)&&!isPlaza(x,y))ok=false;
 if(!ok||!free(...mag,.25)||!free(...app,.2))continue;
 const head=T2W(...mag,46),cartC=T2W(gx+.7,gy+.45,30);
 if(!clearOfButtons(head,90)||!clearOfButtons(cartC,80))continue;
 cands.push([Math.hypot(gx+.7-STALLS[0],gy+.45-STALLS[1]),gx,gy]);
}
cands.sort((a,b)=>a[0]-b[0]||a[1]-b[1]||a[2]-b[2]);
if(!cands.length)problems.push('merchant: no free place by the stalls clear of the buttons');
const [,cgx,cgy]=cands[0]||[0,21.55,22.55];
const CART=[cgx,cgy,cgx+1.4,cgy+.9],MAGPIE=[cgx+1.75,cgy+.5],MAGPIE_APPROACH=[cgx+1.8,cgy+1.2];
claim(...CART,'cart',40);claim(MAGPIE[0]-.25,MAGPIE[1]-.25,MAGPIE[0]+.25,MAGPIE[1]+.25,'spot');
meta.walk=buildWalk({toWorld,toTile,roads:ROADS,lanes:LANES,plaza:PLAZA,bridges:BRIDGES,occupied:occupied.map(r=>({r:[r[0],r[1],r[2],r[3]],tag:r.tag,h:r.h||0})),toScreen:(x,y,z=0)=>P(x,y,z),
 trees:trees.map(t=>[t[0],t[1],t[2]]),fences:FENCES,inWater,targets:{...(opts.targets||{}),merchant:toWorld(...MAGPIE_APPROACH)}});
meta.walk_blockers={occupied:occupied.filter(r=>r.tag!=='spot'&&r.tag!=='tree').map(r=>r.slice(0,4).map(v=>+v.toFixed(3))),trees:trees.map(t=>[+t[0].toFixed(3),+t[1].toFixed(3),+t[2].toFixed(3)]),
 fences:FENCES,bridges:BRIDGES,river:river.map(([a,b])=>[+a.toFixed(3),+b.toFixed(3)]),river_width:RW,pond:POND};
// festival layers (vector, live in the game, shown by html[data-festival] flags): anchored to this render
meta.fest={posidelki:posidelki({B,P,matrix:[.75*K,0,0,.75*K,.75*OX,.75*OY],windows:s.win,chimneys:s.smk,fences:FENCES,bridges:BRIDGES,
 benches:BENCHES.filter(b=>isPlaza(b[0],b[1])),lamps:LAMPS,spots:SPOT,free:(x,y)=>free(x,y,.05),samovar:[20.3,18.9],plaza:PLAZA,
 tall:occupied.filter(r=>r.h>=20).map(r=>({r:[r[0],r[1],r[2],r[3]],h:r.h}))})};
{const festV={B,P,matrix:[.75*K,0,0,.75*K,.75*OX,.75*OY],windows:s.win,chimneys:s.smk,fences:FENCES,bridges:BRIDGES,
  benches:BENCHES.filter(b=>isPlaza(b[0],b[1])),lamps:LAMPS,spots:SPOT,free:(x,y)=>free(x,y,.05),plaza:PLAZA,roofs:s.roofs,chimneys3d:s.chim,doors:s.doors,
  // ground for the winter layers: bare(x,y) = what is painted over the ground tile there (nothing, a shadow, something:
  // a house, tree, fence, field, water), kind(x,y) = what the ground is; trees [x,y,scale,pine] and bushes for their snow caps
  // 0 = bare, 1 = only a shadow lies there (the pixel is the ground darkened towards the farm's shadow #416235), 2 = something
  bare:(x,y)=>{const [sx,sy]=scr(P(x,y));if(sx<0||sy<0||sx>=W||sy>=H)return 2;const i=(sy*W+sx)*4,g=[GROUND_PX[i],GROUND_PX[i+1],GROUND_PX[i+2]],f=[FULL_PX[i],FULL_PX[i+1],FULL_PX[i+2]];
   if(Math.abs(g[0]-f[0])+Math.abs(g[1]-f[1])+Math.abs(g[2]-f[2])<6)return 0;
   const sc=[65,98,53],dv=g.map((v,k)=>sc[k]-v),L=dv.reduce((a,v)=>a+v*v,0)||1,t=f.reduce((a,v,k)=>a+(v-g[k])*dv[k],0)/L;
   const off=Math.hypot(...f.map((v,k)=>v-(g[k]+t*dv[k])));return t>0&&t<.35&&off<6?1:2},
  kind:(x,y)=>{if(isPlaza(x,y))return 'plaza';if(isRoad(x,y))return 'road';const tx=Math.floor(x),ty=Math.floor(y),fx=x-tx,fy=y-ty;
   return isLane(tx,ty)&&fx>.18&&fx<.82&&fy>.18&&fy<.82?'lane':'grass'},
  trees:trees.map(t=>[t[0],t[1],t[2],t[4]==='pine']),bushes:BUSHES,
  edge:(x,y)=>{const [sx,sy]=scr(P(x,y));return Math.max(0,Math.min(1,sx/170,(W-sx)/170,sy/150,(H-sy)/150))},   // 0 at the frame .. 1 past the edge shade
  wells:WELLS,clear:(x,y,z,r)=>clearOfButtons(T2W(x,y,z),r),walk:(()=>{const n=meta.walk.nodes,e=meta.walk.edges,t=i=>toTile(n[2*i],n[2*i+1]),out=[];for(let i=0;i<e.length;i+=2)out.push([...t(e[i]),...t(e[i+1])]);return out})(),avoid:opts.badge?[[opts.badge[0]/.75,opts.badge[1]/.75,opts.badge[2]/.75,opts.badge[3]/.75].map((v,i)=>i%2?(v-OY)/K:(v-OX)/K)]:[],ground:(x,y)=>!inWater(x,y)&&(!isRoad(x,y)||isPlaza(x,y)),stalls:STALL_BOXES,
  // trees stand in front of things too: crowns as tall boxes
  tall:occupied.filter(r=>r.h>=20).map(r=>({r:[r[0],r[1],r[2],r[3]],h:r.h})).concat(trees.map(t=>({r:[t[0]-.3,t[1]-.3,t[0]+.3,t[1]+.3],h:80*t[2]})))};
 meta.fest.new_year=newYear(festV);meta.fest.maslenitsa=maslenitsa(festV);meta.fest.spring_flowers=springFlowers(festV)}
{const corners=[];for(const [x,y] of [[CART[0],CART[1]],[CART[2],CART[1]],[CART[2],CART[3]],[CART[0],CART[3]]])for(const z of [0,64])corners.push(scr(P(x,y,z)).map(v=>v*.75));
 const xs=corners.map(c=>c[0]),ys=corners.map(c=>c[1]);
 meta.merchant={svg:merchantCart({B,P,matrix:[.75*K,0,0,.75*K,.75*OX,.75*OY],box:CART}),figure:magpieSvg(),
  cart:[Math.min(...xs),Math.min(...ys),Math.max(...xs)-Math.min(...xs),Math.max(...ys)-Math.min(...ys)].map(Math.round),foot:toWorld(...MAGPIE).map(Math.round)}}
// construction (build.js): stages of the sites and the stalls of the rows, anchored to this render
meta.build=buildArt({B,P,matrix:[.75*K,0,0,.75*K,.75*OX,.75*OY],sites:SITES,slots:STALL_SLOTS});
meta.build.figures=crewSvgs();
meta.player=playerSvg();   // the player's figure (player.js), a live layer like the gate board
return {world:cv.toDataURL('image/png'),meta,size:[W,H]};
}
