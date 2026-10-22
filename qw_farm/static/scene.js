import {drawTeamZones,teamSprites,smallAnimal,specialDecor,machineAt,resetWalkingGeese,reactWalkingGeese,releaseWalkingGeese,drawTeaArbor,resetLivestock,livestockMoves} from './scene_expansion.js';
import {drawBuilding,drawUpgrade,drawBadge,drawRoad} from './scene_buildings.js';
import {Minimap,viewRect,overlaps,objectBounds,panToCenter,clampWorldPoint,sortByDepth,spriteSlots,compareDepth,isoInverse} from './scene_map.js';
const LATE_CROPS={zucchini:['leaf','#8fb86a'],beans:['pod','#a9c079'],currant:['berry','#4b3f6b'],ginger:['root','#d9b87a'],broccoli:['leaf','#6fa65a'],turnip:['root','#e6d9a8'],gooseberry:['berry','#a8c96a'],barley:['grain','#d7bf74'],celery:['stalk','#8fc07a'],apple:['tree','#d9534f'],cherry:['tree','#b3263e'],millet:['grain','#e2c35a'],leek:['stalk','#a7cf8a'],pear:['tree','#c6cf5a'],rosehip:['berry','#d0453c'],chickpea:['pod','#d8b878'],kohlrabi:['root','#b7d68a'],plum:['tree','#6b4a8c'],sea_buckthorn:['berry','#f09a2a'],ginseng:['root','#d8c49a'],asparagus:['stalk','#9bc872'],apricot:['tree','#f0a64a'],viburnum:['berry','#c4232f'],pomegranate:['tree','#b3262f'],artichoke:['leaf','#8fae6a'],peach:['tree','#f2a07a']};
/* Original procedural farm artwork + isometric renderer. No third-party assets.
   Scene is a view only: it cannot change goods, timestamps or balances.
   Performance model (r8 step 9): the ground, lane and back trees never depend on the objects, so they are
   painted once into an offscreen canvas slightly larger than the screen and only blitted while the camera pans;
   it is repainted when zoom/size/land size change or the pan leaves the margin. Objects are depth-sorted once per
   farm snapshot (sortByDepth: footprint rectangles, not a corner sum) and skipped when their bounding box is off screen;
   semantic layers paint soil, then animated crops, then solid objects, then markers. Plants always stay below
   animals, machines and fences without silhouette masks. Solid sprites use ground anchors; their order relative
   to buildings is cached per snapshot. Machines, helpers and the goose merge into the solid pass every frame
   (spriteSlots), and front trees follow it. The loop pauses in a hidden tab and backs off
   its animation rate when frames are slow. */
const TW=36, TH=18;
// Mill tap box = its drawn silhouette: tower 100 px, sail tips ~104 px above the footprint centre. The old 125 px reach stole taps from neighbours.
export const MILL_HIT={hw:40,top:106};
const P=(x,y,z=0)=>({x:(x-y)*TW,y:(x+y)*TH-z});
const mix=(a,b,t)=>a+(b-a)*t;
const seed=(x,y=0)=>{let n=Math.sin(x*127.1+y*311.7)*43758.5453;return n-Math.floor(n)};
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
// Plant detail drops to a stem and a head below this zoom. 0 = never (identical art at every zoom); ~.4 would save ~25% on a 20x20 phone view.
const PLANT_LOD_SCALE=0;
const MIN_SCALE=.25,MAX_SCALE=2,CACHE_MARGIN=.18,MAIN_MAX_PIXELS=4e6,CACHE_MAX_PIXELS=6e6;
const KEY_PAN={ArrowLeft:[1,0],KeyA:[1,0],ArrowRight:[-1,0],KeyD:[-1,0],ArrowUp:[0,1],KeyW:[0,1],ArrowDown:[0,-1],KeyS:[0,-1]};
const KEY_SPEED=560;
// Per-farm salt: the same farm always gets the same wood, different farms get different ones.
const farmSalt=id=>{let h=7;for(const ch of String(id??''))h=(h*31+ch.charCodeAt(0))%9973;return h+1};

// Presentation clock only. Crop deadlines still use the server clock in now().
// The UI owns the saved mode and calls setLighting on resume and once a minute.
export function farmLightingAt(date=new Date(),mode='auto'){
 const selected=['auto','day','night'].includes(mode)?mode:'auto';
 if(selected!=='auto')return {mode:selected,phase:selected,darkness:selected==='night'?1:0,warmth:0};
 const hour=date.getHours()+date.getMinutes()/60+date.getSeconds()/3600;
 const smooth=v=>v*v*(3-2*v);
 if(hour>=5&&hour<8){const p=(hour-5)/3;return {mode:selected,phase:'dawn',darkness:1-smooth(p),warmth:.7*Math.sin(Math.PI*p)}}
 if(hour>=8&&hour<17)return {mode:selected,phase:'day',darkness:0,warmth:0};
 if(hour>=17&&hour<21){const p=(hour-17)/4;return {mode:selected,phase:'dusk',darkness:smooth(p),warmth:Math.sin(Math.PI*p)}}
 return {mode:selected,phase:'night',darkness:1,warmth:0};
}
const lightingColor=(day,night,darkness,warmth=0)=>`rgb(${day.map((v,i)=>Math.round(mix(v,night[i],darkness)+[12,2,-8][i]*warmth)).join(',')})`;

export class FarmScene {
 constructor(canvas,callbacks={}){
  this.canvas=canvas;this.c=canvas.getContext('2d');this.cb=callbacks;this.farm=null;this.catalog=null;
  this.dirty=true;this.scale=1;this.pan={x:0,y:0};this.hover=null;this.hoverId=null;this.selected=null;this.placement=null;this.pointers=new Map();this.dragging=false;
  this.motion=!matchMedia('(prefers-reduced-motion: reduce)').matches;this.lastFrame=0;this.particles=[];this.serverOffset=0;
  this.farmToken=0;this.layout=null;this.cache=null;this.sorted=null;this.anim=null;this.keys=new Set();this.cost=0;this.frameInterval=32;this.lastTick=0;this.pinch=null;
  this.stats={objects:0,drawn:0,staticPaints:0,staticBlits:0,frames:0};
  this.mini=callbacks.minimap?new Minimap(callbacks.minimap,this):null;
  this.paused=false;this.raf=0;
  this.tick=this.tick.bind(this);
  new ResizeObserver(()=>this.resize()).observe(canvas);this.setupInput();this.resize();
  document.addEventListener('visibilitychange',()=>this.syncLoop());this.syncLoop();
 }
 grid(){return Math.max(12,this.farm?.size||12)}
 layoutKey(){const id=this.farm.id;return `${this.grid()}|${this.farm.size}${id===undefined?'':'|'+id}`}
 set(farm,catalog){this.dirty=true;this.farmToken++;this.sorted=null;this.renderOrder=null;const before=this.grid();this.farm=farm;this.catalog=catalog;resetWalkingGeese(this);resetLivestock(this);this.serverOffset=farm.server_time-Date.now()/1000;if(!this.initialized){this.fit();this.initialized=true}else if(this.grid()!==before)this.fit()}
 projectStage(id){const stage=this.farm?.home_projects?.entries?.[id]?.stage;return stage===1||stage===2?stage:0}
 now(){return Date.now()/1000+this.serverOffset}
 setLighting(state){
  if(!state||!Number.isFinite(state.darkness)||!Number.isFinite(state.warmth))return;
  const next={...state,darkness:clamp(state.darkness,0,1),warmth:clamp(state.warmth,0,1)};
  const at=performance.now();this.stepLighting(at);
  if(!this.lighting||!this.motion||this.isPaused()){this.lighting=next;this.lightingTransition=null}
  else if(this.lighting.darkness!==next.darkness||this.lighting.warmth!==next.warmth)this.lightingTransition={from:this.lighting,to:next,at};
  else{this.lighting=next;this.lightingTransition=null}
  this.dirty=true;
 }
 stepLighting(at){
  const a=this.lightingTransition;if(!a)return;
  const p=clamp((at-a.at)/1000,0,1),e=p*p*(3-2*p);
  this.lighting={...a.to,darkness:mix(a.from.darkness,a.to.darkness,e),warmth:mix(a.from.warmth,a.to.warmth,e)};
  if(p===1)this.lightingTransition=null;
 }
 // One source-over pass on the existing canvas: no extra bitmap, CSS filter,
 // static cache invalidation or changes to animation/detail/camera coordinates.
 paintLighting(){
  const {darkness=0,warmth=0}=this.lighting||{},alpha=.56*darkness+.12*warmth;
  if(alpha<=0)return;
  const c=this.c;c.save();c.setTransform(this.dpr,0,0,this.dpr,0,0);
  c.globalAlpha=alpha;c.fillStyle=lightingColor([65,43,36],[12,24,43],darkness);c.fillRect(0,0,this.w,this.h);c.restore();
 }
 isPaused(){return this.paused||document.hidden}
 setPaused(paused){this.paused=Boolean(paused);this.syncLoop()}
 clearInput(){
  for(const id of this.pointers.keys())try{if(this.canvas.hasPointerCapture(id))this.canvas.releasePointerCapture(id)}catch{}
  this.pointers.clear();this.keys.clear();this.pinch=null;this.start=null;this.moved=true;this.dragging=false;
  this.hover=null;this.hoverId=null;this.canvas.style.cursor='';
 }
 syncLoop(){
  if(this.isPaused()){
   if(this.raf){cancelAnimationFrame(this.raf);this.raf=0}
   this.clearInput();this.anim=null;return;
  }
  if(!this.raf){this.dirty=true;this.lastTick=0;this.lastFrame=0;this.raf=requestAnimationFrame(this.tick)}
 }
 resize(){
  const r=this.canvas.getBoundingClientRect(),w=Math.max(0,r.width),h=Math.max(0,r.height);
  // One effective DPR is shared by all map layers. Large monitors lower resolution rather than allocating unbounded buffers.
  const d=Math.min(devicePixelRatio||1,2,Math.sqrt(MAIN_MAX_PIXELS/Math.max(1,w*h)));
  const pw=Math.floor(w*d),ph=Math.floor(h*d),changed=this.w!==w||this.h!==h||this.dpr!==d;
  if(!changed)return;this.w=w;this.h=h;this.dpr=d;this.dirty=true;
  if(this.canvas.width!==pw)this.canvas.width=pw;if(this.canvas.height!==ph)this.canvas.height=ph;
  this.bg=null;
  if(this.cache){this.cache.canvas.width=0;this.cache.canvas.height=0;this.cache=null}
  if(!this.initialized)this.fit();
 }
 fit(all=false){this.dirty=true;this.anim=null;const G=this.grid();this.scale=this.w<650&&!all?.85:Math.min(this.w>=1100?1.8:1.2,Math.max(.25,Math.min((this.w-55)/(72*G+1+170),(this.h-155)/(36*G+138))));if(G>12&&this.w<650&&!all)this.scale=Math.min(this.scale,Math.max(.25,(this.w-30)/(72*G+1)));this.pan={x:0,y:0}}
 baseOrigin(){return {x:this.w/2+85*this.scale,y:Math.max(140,(this.h-this.grid()*36*this.scale)/2)-12}}
 origin(){const b=this.baseOrigin();return {x:b.x+this.pan.x,y:b.y+this.pan.y}}
 viewRect(margin=0){return viewRect(this.w,this.h,this.origin(),this.scale,margin)}
 // Zoom keeps the world point under (sx,sy) fixed: the viewport centre for buttons/keys, the cursor for the wheel, the finger midpoint for pinch.
 zoomAt(sx,sy,mult){const old=this.world(sx,sy),next=clamp(this.scale*mult,MIN_SCALE,MAX_SCALE);if(next===this.scale)return;this.dirty=true;this.scale=next;const o=this.origin();this.pan.x+=sx-(old.x*next+o.x);this.pan.y+=sy-(old.y*next+o.y)}
 zoom(mult){this.anim=null;this.zoomAt(this.w/2,this.h/2,mult)}
 centerOn(wx,wy,cy=this.h/2){this.anim=null;this.dirty=true;const q=clampWorldPoint(this.grid(),wx,wy);this.pan=panToCenter(this.w,this.h,this.baseOrigin(),this.scale,q.x,q.y,cy)}
 world(x,y){let o=this.origin();return{x:(x-o.x)/this.scale,y:(y-o.y)/this.scale}}
 cell(x,y){const q=this.world(x,y);return{x:Math.floor((q.x/TW+q.y/TH)/2),y:Math.floor((q.y/TH-q.x/TW)/2)}}
 setupInput(){const el=this.canvas;
  el.addEventListener('wheel',e=>{if(this.isPaused())return;e.preventDefault();this.anim=null;const r=el.getBoundingClientRect();const unit=e.deltaMode===1?16:e.deltaMode===2?400:1;const d=clamp(e.deltaY*unit,-120,120);this.zoomAt(e.clientX-r.left,e.clientY-r.top,Math.exp(-d*(e.ctrlKey?.01:.0008)))},{passive:false});
  el.addEventListener('pointerdown',e=>{if(this.isPaused())return;this.anim=null;el.setPointerCapture(e.pointerId);this.pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});this.start={x:e.clientX,y:e.clientY};this.moved=false;{const r=el.getBoundingClientRect();reactWalkingGeese(this,this.world(e.clientX-r.left,e.clientY-r.top),null,true)}if(this.pointers.size===2){this.moved=true;this.pinch=this.pinchState()}});
  el.addEventListener('pointermove',e=>{if(this.isPaused())return;const r=el.getBoundingClientRect();const h=this.cell(e.clientX-r.left,e.clientY-r.top);if(!this.hover||h.x!==this.hover.x||h.y!==this.hover.y)this.dirty=true;this.hover=h;
   // Desktop only: the object under the mouse (not a bed: its own tile highlight is already the object) is lit instead of its cell.
   const under=e.pointerType==='mouse'&&!this.placement&&!this.pointers.size?this.pick(e.clientX-r.left,e.clientY-r.top):null,hid=under&&under.type!=='plot'?under.id:null;
   if(e.pointerType==='mouse'||this.pointers.size===1)reactWalkingGeese(this,this.world(e.clientX-r.left,e.clientY-r.top),under);
   if(hid!==this.hoverId){this.hoverId=hid;this.dirty=true;el.style.cursor=hid?'pointer':''}
   let prev=this.pointers.get(e.pointerId);
   if(prev){this.pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
    if(this.pointers.size>=2){this.moved=true;this.pinchMove(r)}
    else{let dx=e.clientX-prev.x,dy=e.clientY-prev.y;if(Math.hypot(e.clientX-this.start.x,e.clientY-this.start.y)>7)this.moved=true;if(this.moved){this.pan.x+=dx;this.pan.y+=dy;this.dirty=true}}}
  });
  const release=e=>{this.pointers.delete(e.pointerId);if(!this.pointers.size)releaseWalkingGeese(this,e.pointerType==='mouse'?3600:1.4);this.pinch=this.pointers.size>=2?this.pinchState():null};
  el.addEventListener('pointerup',e=>{release(e);if(this.isPaused())return;if(!this.moved){let r=el.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top,cell=this.cell(x,y),under=this.pick(x,y);reactWalkingGeese(this,this.world(x,y),under);if(e.pointerType!=='mouse')releaseWalkingGeese(this,1.4);this.cb.click?.(under,cell)}if(this.pointers.size)this.moved=true});
  el.addEventListener('pointercancel',e=>{release(e);this.moved=true});
  el.addEventListener('pointerleave',()=>{releaseWalkingGeese(this,.4);if(!this.pointers.size){this.hover=null;this.hoverId=null;el.style.cursor='';this.dirty=true}});
  // Desktop keys: WASD / arrows pan (held = smooth), + / - zoom, 0 shows the whole land. Layout-independent codes keep WASD working in Russian.
  document.addEventListener('keydown',e=>{
   if(e.ctrlKey||e.metaKey||e.altKey||!this.keyTarget(e))return;
   const code=e.code;
   if(KEY_PAN[code]){e.preventDefault();this.anim=null;this.keys.add(code);this.dirty=true;return}
   if(code==='Equal'||code==='NumpadAdd'||e.key==='+'){e.preventDefault();this.zoom(1.15)}
   else if(code==='Minus'||code==='NumpadSubtract'||e.key==='-'){e.preventDefault();this.zoom(1/1.15)}
   else if(code==='Digit0'||code==='Numpad0'){e.preventDefault();this.fit()}
  });
  document.addEventListener('keyup',e=>{this.keys.delete(e.code)});
  window.addEventListener('blur',()=>this.keys.clear());
  el.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();this.cb.cancel?.()}});
 }
 // Keys act only while the map (or the page body) has focus and no dialog or text field is active.
 keyTarget(e){if(this.isPaused())return false;const t=e.target,tag=t?.tagName;if(['INPUT','SELECT','TEXTAREA','BUTTON','A','SUMMARY'].includes(tag)||t?.isContentEditable)return false;if(!this.canvas.offsetParent||document.querySelector('dialog[open]'))return false;return true}
 pinchState(){const [a,b]=[...this.pointers.values()];if(!a||!b)return null;return {dist:Math.max(1,Math.hypot(a.x-b.x,a.y-b.y)),mx:(a.x+b.x)/2,my:(a.y+b.y)/2}}
 pinchMove(r){const next=this.pinchState(),prev=this.pinch;if(!next||!prev){this.pinch=next;return}
  this.zoomAt(prev.mx-r.left,prev.my-r.top,next.dist/prev.dist);this.pan.x+=next.mx-prev.mx;this.pan.y+=next.my-prev.my;this.dirty=true;this.pinch=next}
 pick(x,y){if(!this.farm)return null;let cell=this.cell(x,y),q=this.world(x,y);const mid=this.farm.is_owner?machineAt(this,q.x,q.y):null;if(mid&&mid!=='robot')return {type:'machine',machine:mid,id:'machine:'+mid,x:0,y:0,w:0,h:0};const lake=this.pondCenter(),dx=(q.x-lake.x)/this.lakeSize().rx,dy=(q.y-lake.y)/this.lakeSize().ry,pier=isoInverse(q.x,q.y),G=this.grid(),dock=this.projectStage('lake_pier')>=1&&pier.x>=2&&pier.x<=3&&pier.y>=G-.65&&pier.y<=G+2.2;const ap=this.arborPos();if(this.projectStage('tea_arbor')>=1&&q.x>ap.x-48&&q.x<ap.x+48&&q.y>ap.y-86&&q.y<ap.y+24)return {type:'arbor',id:'arbor'};{const st=this.stonePos();if(q.x>st.x-24&&q.x<st.x+26&&q.y>st.y-58&&q.y<st.y+10)return {type:'stone',id:'stone'}}if(this.inLake(dx,dy)||dock)return {type:'lake',id:'lake'};let objs=[...this.sortedObjects().list].reverse(); // front-most first: the reverse of the paint order
  const exact=objs.find(o=>cell.x>=o.x&&cell.x<o.x+o.w&&cell.y>=o.y&&cell.y<o.y+o.h);
  if(exact)return exact;
  for(let o of objs){if(o.type==='plot'||o.type==='road')continue;let p=P(o.x+o.w/2,o.y+o.h/2);const hw=o.type==='mill'?MILL_HIT.hw:43,top=o.type==='mill'?MILL_HIT.top:90;if(q.x>p.x-hw&&q.x<p.x+hw&&q.y>p.y-top&&q.y<p.y+10)return o}
  return null;
 }
 // `camera` moves the view to the object (lists and the mini-map); a tap on the map itself only selects.
 focus(obj,camera=false,inset=0){this.selected=obj.id;this.dirty=true;if(camera)this.flyTo((obj.x+obj.w/2-obj.y-obj.h/2)*TW,(obj.x+obj.w/2+obj.y+obj.h/2)*TH-(obj.type==='plot'?6:22),Math.max(this.scale,.9),inset)}
 // `inset` = canvas pixels covered at the bottom (the phone sheet): the target is centred in the visible strip above it.
 flyTo(wx,wy,scale,inset=0){
  const q=clampWorldPoint(this.grid(),wx,wy),to=clamp(scale,MIN_SCALE,MAX_SCALE),cy=Math.max(40,(this.h-Math.min(inset,this.h*.8))/2);
  if(!this.motion||!this.w){this.scale=to;this.centerOn(q.x,q.y,cy);return}
  const from=this.world(this.w/2,cy);this.anim={t0:null,dur:320,s0:this.scale,s1:to,x0:from.x,y0:from.y,x1:q.x,y1:q.y,cy};this.dirty=true;
 }
 stepCamera(t){
  const dt=this.lastTick?Math.min(.05,(t-this.lastTick)/1000):0;this.lastTick=t;
  if(this.anim){const a=this.anim;if(a.t0===null)a.t0=t;const k=Math.min(1,(t-a.t0)/a.dur),e=1-Math.pow(1-k,3);this.scale=a.s0+(a.s1-a.s0)*e;const wx=a.x0+(a.x1-a.x0)*e,wy=a.y0+(a.y1-a.y0)*e;this.pan=panToCenter(this.w,this.h,this.baseOrigin(),this.scale,wx,wy,a.cy);this.dirty=true;if(k>=1)this.anim=null}
  if(this.keys.size&&dt){let dx=0,dy=0;for(const k of this.keys){dx+=KEY_PAN[k][0];dy+=KEY_PAN[k][1]}if(dx||dy){const n=Math.hypot(dx,dy);this.pan.x+=dx/n*KEY_SPEED*dt;this.pan.y+=dy/n*KEY_SPEED*dt;this.dirty=true}}
 }
 burst(obj,color='#e2bd62'){let p=P(obj.x+.5,obj.y+.5);for(let i=0;i<12;i++)this.particles.push({x:p.x,y:p.y-12,dx:(seed(i,Date.now()%5000)-.5)*2.5,dy:-1-seed(i+8)*2,age:0,color});this.dirty=true}
 tick(t){this.raf=0;if(this.isPaused())return;this.raf=requestAnimationFrame(this.tick);this.stepCamera(t);
  let reacting=false;for(const g of this.walkingGeese||[])if(g.mode&&g.mode!=='idle')reacting=true;
  const interval=this.motion?this.frameInterval:reacting?100:1000;if(this.particles.length||reacting&&t-this.lastFrame>=interval)this.dirty=true;
  const elapsed=t-this.lastFrame;if(elapsed<interval&&(this.motion||reacting||!this.dirty))return;this.dirty=false;const remainder=this.motion&&this.lastFrame>0?elapsed%interval:0;const a=performance.now();this.draw(t/1000);
  // Slow devices: stretch the animation interval to ~2.5 frame costs (32..100 ms), including during camera movement.
  this.cost=this.cost?this.cost*.88+(performance.now()-a)*.12:performance.now()-a;this.frameInterval=clamp(this.cost*2.5,32,100);
  // Preserve sub-frame time on displays whose refresh period does not divide the target interval.
  this.lastFrame=t-(this.motion?remainder%this.frameInterval:0)}
 poly(points,fill,stroke=null,width=1){const c=this.c;c.beginPath();points.forEach((p,i)=>i?c.lineTo(p.x,p.y):c.moveTo(p.x,p.y));c.closePath();if(fill){c.fillStyle=fill;c.fill()}if(stroke){c.strokeStyle=stroke;c.lineWidth=width;c.stroke()}}
 ellipse(x,y,rx,ry,color){const c=this.c;c.beginPath();c.ellipse(x,y,rx,ry,0,0,Math.PI*2);c.fillStyle=color;c.fill()}
 line(x1,y1,x2,y2,color,width=1){const c=this.c;c.beginPath();c.moveTo(x1,y1);c.lineTo(x2,y2);c.strokeStyle=color;c.lineWidth=width;c.lineCap='round';c.stroke()}
 tile(x,y,color,stroke=null,z=0){this.poly([P(x,y,z),P(x+1,y,z),P(x+1,y+1,z),P(x,y+1,z)],color,stroke)}
 footprint(o,color,stroke=null){this.poly([P(o.x,o.y,1),P(o.x+o.w,o.y,1),P(o.x+o.w,o.y+o.h,1),P(o.x,o.y+o.h,1)],color,stroke,2)}
 label(x,y,text,ready=false){
  if(this.lightMarkers){this.lightMarkers.push({kind:'label',x,y,text,ready});return}
  const dark=(this.lighting?.darkness||0)>.25,c=this.c;c.font='600 10px "Segoe UI", sans-serif';let w=c.measureText(text).width+17;
  c.fillStyle=dark?'#24333b':ready?'#f9edbd':'#fdfcf1';c.beginPath();c.roundRect(x-w/2,y-17,w,23,7);c.fill();
  c.fillStyle=dark?'#f3e5c5':ready?'#947439':'#617658';c.textAlign='center';c.fillText(text,x,y-2)
 }
 shadow(x,y,rx,ry){const d=this.inStatic?[0,.5,1][this.shadowLevel||0]:(this.lighting?.darkness||0);this.ellipse(x+6,y+3,rx,ry,d>.02?this.nightShadowColor(d):'#41623517')}
 nightShadowColor(d){const q=Math.round(d*12)/12,cache=this.shadowCache||(this.shadowCache={});return cache[q]||(cache[q]=`rgba(5,11,20,${(.12+.4*q).toFixed(2)})`)}
 // ---- static ground layer: land, lane and back trees ----
 buildLayout(){
  const G=this.grid(),area=this.farm.size,tiles=[],salt=farmSalt(this.farm.id),rs=(x,y=0)=>seed(x+salt*.371,y+salt*.913);
  for(let x=0;x<G;x++)for(let y=0;y<G;y++){
   const unlocked=x<area&&y<area,random=rs(x,y);
   const rr=rs(x*1.7,y*2.3),wild=!unlocked&&(x<1||x>3)?(rr>.92?'rock':rr>.78?'bush':rr>.52?'flowers':null):null;
   tiles.push({x,y,random,wild,wr:rs(y*3.3,x*.7),col:unlocked?['#b9ce98','#bdd29d','#c1d5a3','#b6cd96'][Math.floor(random*4)]:['#d2dfbd','#cfddb7','#ccdbb2'][Math.floor(random*3)],stroke:unlocked?'#a5bd891e':'#bccdaa25',unlocked});
  }
  // Random but fair: positions are jittered per farm, a few trees drop out, and treeBlocked keeps the working land, lanes, sign, lake and arbor clear.
  const before=[],after=[],add=(list,x,y,s,key=0)=>{const jx=(rs(x*3.1,y*1.7+key)-.5)*.8,jy=(rs(y*2.3+key,x*1.3)-.5)*.8;if(rs(x+key,y*5.7)<.12)return;x+=jx;y+=jy;if(!this.treeBlocked(x,y,s))list.push({x,y,s,p:P(x,y)})};
  for(let i=0,n=Math.round((G-1)/1.12);i<n;i++)add(before,-1.2-Math.floor(rs(i,2)*3),1+i*1.12,.8+rs(i)*.5,1);
  for(let i=0,n=Math.round((G-.8)/1.6)+1;i<n;i++)add(before,2+i*1.6,-1.25-rs(i,5)*.8,1+rs(i,4)*.25,2);
  for(let x=area;x<G;x++)for(let y=0;y<G;y++){if(rs(x,y)>.67)add(after,x+.5,y+.5,.65+rs(y,x)*.25,3)}
  for(let y=area;y<G;y++)for(let x=0;x<area;x++){if(rs(x,y)>.72)add(after,x+.5,y+.5,.6+rs(y,x)*.25,4)}
  // Forest ring beyond the far edges, so the plot is surrounded by trees at every size.
  if(area>=G){for(let i=0,n=Math.round((G-3)/1.6);i<n;i++)add(after,G+3+Math.floor(rs(i,3)*3)*.8,2.4+i*1.6,.85+rs(i,9)*.25,5);for(let i=0,n=Math.round((G-5.5)/1.12);i<n;i++)add(after,5.2+i*1.12,G+3+Math.floor(rs(i,6)*3)*.8,.7+rs(i,7)*.35,6)}
  const k=G/12,pond=this.pondCenter();
  const fog=[{x:0,y:-34,rx:116*k,ry:32*k,phase:0},{x:36*G+38,y:18*G,rx:96*k,ry:43*k,phase:1.7},{x:0,y:36*G+36,rx:118*k,ry:36*k,phase:3.1},{x:-36*G-38,y:18*G,rx:96*k,ry:43*k,phase:4.6}];
  this.layout={key:this.layoutKey(),G,area,tiles,before,after,fog,pond};
 }
 paintStatic(c,v){
  const L=this.layout,G=L.G,area=L.area,vis=(x0,y0,x1,y1)=>x0<v.x1&&x1>v.x0&&y0<v.y1&&y1>v.y0;
  this.lake(L.pond.x,L.pond.y);
  for(const t of L.tiles){
   const x=t.x,y=t.y,bx=(x-y-1)*TW,by=(x+y)*TH;if(!vis(bx,by,bx+2*TW,by+2*TH))continue;
   this.tile(x,y,t.col,t.stroke);
   let p=P(x+.48,y+.48);if(t.random>.56){this.line(p.x-8,p.y,p.x-6,p.y-4,'#8da87255',.8);this.line(p.x-4,p.y+1,p.x-4,p.y-2,'#9aaf7855',.8)}
   if(!t.unlocked&&t.random>.88){this.ellipse(p.x,p.y,3,1.5,'#bdcca7');}
   if(t.wild)this.wildSpot(t);
  }
  // Soil edges anchor the diorama.
  let n=G;this.poly([P(0,n),P(n,n),P(n,n,-10),P(0,n,-10)],'#b8caa0');this.poly([P(n,0),P(n,n),P(n,n,-10),P(n,0,-10)],'#afc49b');
  if(area<G){c.setLineDash([4,6]);this.poly([P(0,0),P(area,0),P(area,area),P(0,area)],null,'#91a66e88',1.3);c.setLineDash([])
   // survey stakes mark the free land that can still be bought
   for(let i=1;i<area;i+=3)for(const q of [P(area,i),P(i,area)]){this.line(q.x,q.y,q.x,q.y-12,'#9d7a4c',2.2);this.poly([{x:q.x,y:q.y-12},{x:q.x+7,y:q.y-10},{x:q.x,y:q.y-7}],'#e0a24f');this.ellipse(q.x,q.y,3,1.3,'#8da872')}}
  // A gravel lane, fixed outside occupied starting cells.
  for(let i=0;i<area;i++){let bx=(i-2-1)*TW,by=(i+2)*TH;if(!vis(bx,by,bx+2*TW,by+2*TH))continue;this.tile(i,2,'#dbd3ae');let p=P(i+.4,2.5);this.ellipse(p.x,p.y,3,1,'#c5ba934c')}
  for(let y=3;y<area;y++){let bx=(2-y-1)*TW,by=(2+y)*TH;if(!vis(bx,by,bx+2*TW,by+2*TH))continue;this.tile(2,y,'#dbd3ae')}
  if(area<G-.65)this.poly([P(2,area),P(3,area),P(3,G-.65),P(2,G-.65)],'#dbd3ae');
  this.lakePier(G);
  this.paintTrees(L.before,v); // behind the whole farm square; the trees in front of it are painted after the objects
 }
 wildSpot(t){
  const jx=(t.wr-.5)*.5,p=P(t.x+.5+jx,t.y+.5-jx*.7);
  if(t.wild==='bush'){this.ellipse(p.x+3,p.y+2,12,4.5,'#6f8e5a30');this.ellipse(p.x-5,p.y-3,7,6,'#78a269');this.ellipse(p.x+4,p.y-4,6.5,5.5,'#86b074');this.ellipse(p.x-1,p.y-8,5.5,5,'#8fbb7c');if(t.wr>.5){this.ellipse(p.x+5,p.y-6,1.3,1.3,'#d46f6a');this.ellipse(p.x-3,p.y-4,1.2,1.2,'#d46f6a')}}
  else if(t.wild==='rock'){this.ellipse(p.x+3,p.y+2,10,3.6,'#7d806e30');this.ellipse(p.x,p.y-1,8.5,4.4,'#9c9e8e');this.ellipse(p.x-1,p.y-4,7,5,'#b1b3a2');this.ellipse(p.x-2,p.y-5.5,3,1.6,'#cfd1c0');if(t.wr>.5)this.ellipse(p.x+9,p.y,3.5,2,'#a9ab9b')}
  else{const cols=['#e7a8b5','#f1dc8a','#c3b0de','#f4f1e6'];for(let i=0;i<6;i++){const fx=p.x+(i-2.5)*4.3,fy=p.y+((i*5)%4)-1,h=6+((i*3)%4);this.line(fx,fy,fx,fy-h,'#7ea468',1);this.ellipse(fx,fy-h-1,2.1,1.8,cols[(i+Math.floor(t.wr*4))%4]);this.ellipse(fx,fy-h-1,.8,.7,'#d9a93d')}}
 }
 paintTrees(list,v){const seen=[];for(const t of list){const p=t.p,s=t.s;if(p.x+26*s<v.x0||p.x-26*s>v.x1||p.y-76*s>v.y1||p.y+14*s<v.y0)continue;seen.push(t)}
  for(const t of seen)this.shadow(t.p.x+6*(t.s-1),t.p.y+3*(t.s-1),19*t.s,8*t.s);
  for(const t of seen)this.treeSprite(t.x,t.y,t.s,false)}
 // The offscreen ground layer is a little larger than the screen, so panning usually only shifts it.
 layerBox(){
  const d=this.dpr;let kx=Math.round(this.w*CACHE_MARGIN),ky=Math.round(this.h*CACHE_MARGIN);
  while(Math.floor((this.w+2*kx)*d)*Math.floor((this.h+2*ky)*d)>CACHE_MAX_PIXELS&&(kx>0||ky>0)){kx=Math.floor(kx/2);ky=Math.floor(ky/2)}
  return {mx:kx,my:ky,pw:Math.floor((this.w+2*kx)*d),ph:Math.floor((this.h+2*ky)*d)};
 }
 // Paints into `layer` with the world origin at screen `origin`, then restores the main context.
 paintLayer(layer,origin,fn){
  const d=this.dpr,box=this.layerBox(),cv=layer.canvas;
  if(cv.width!==box.pw||cv.height!==box.ph){cv.width=box.pw;cv.height=box.ph}
  const g=cv.getContext('2d'),main=this.c;
  Object.assign(layer,{ox:origin.x,oy:origin.y,mx:box.mx,my:box.my,scale:this.scale,painted:true});
  g.setTransform(1,0,0,1,0,0);g.clearRect(0,0,box.pw,box.ph);
  g.setTransform(d*this.scale,0,0,d*this.scale,(box.mx+origin.x)*d,(box.my+origin.y)*d);
  const v={x0:(-box.mx-origin.x)/this.scale,y0:(-box.my-origin.y)/this.scale,x1:(this.w+box.mx-origin.x)/this.scale,y1:(this.h+box.my-origin.y)/this.scale};
  this.c=g;const prevView=this.view;this.view=v;try{fn(g,v)}finally{this.c=main;this.view=prevView}
 }
 // Static layer: ground, lane, back trees. Repainted only on zoom/size/land change or when the pan leaves the margin.
 staticLayer(origin){
  const projects=['lake_pier','flower_entry'].map(id=>this.projectStage(id)).join(',');
  const dk=this.lighting?.darkness||0,level=dk<.1?0:dk<.6?1:2,key=`${this.farm.id}|${projects}|${this.layout.key}|${this.scale}|${this.dpr}|${this.w}|${this.h}|${level}`;
  let C=this.cache;
  if(!C||C.key!==key||Math.abs(origin.x-C.ox)>C.mx||Math.abs(origin.y-C.oy)>C.my){
   if(!C)C=this.cache={canvas:document.createElement('canvas')};C.key=key;
   this.shadowLevel=level;this.paintLayer(C,origin,(g,v)=>{this.inStatic=true;try{this.paintStatic(g,v)}finally{this.inStatic=false}});this.stats.staticPaints++;
  }else this.stats.staticBlits++;
  const d=this.dpr;this.c.setTransform(1,0,0,1,0,0);this.c.drawImage(C.canvas,Math.round((origin.x-C.ox-C.mx)*d),Math.round((origin.y-C.oy-C.my)*d));
 }
 background(){
  const darkness=Math.round((this.lighting?.darkness||0)*255)/255,warmth=Math.round((this.lighting?.warmth||0)*255)/255,key=`${this.h}|${darkness}|${warmth}`;
  if(!this.bg||this.bg.key!==key){const g=this.c.createLinearGradient(0,0,0,this.h);g.addColorStop(0,lightingColor([237,243,226],[24,37,48],darkness,warmth));g.addColorStop(1,lightingColor([227,236,211],[35,49,51],darkness,warmth));this.bg={key,g}}
  this.c.fillStyle=this.bg.g;this.c.fillRect(0,0,this.w,this.h);
 }
 // Daytime washes and the outer path fade with the sky rather than remain pale islands in
 // the night background. Keep them outside the ground cache so the clock never repaints it.
 groundWash(origin){
  const dk=this.lighting?.darkness||0,alpha=1-dk,c=this.c,G=this.grid(),k=G/12;
  c.save();c.translate(origin.x,origin.y);c.scale(this.scale,this.scale);
  if(dk>0)this.nightMeadow(dk,G);
  if(alpha>0){c.globalAlpha=alpha;this.ellipse(0,250*k,500*k,210*k,'#ccddbb35');this.ellipse(-380*k,320*k,125*k,90*k,'#d5e3c855');this.path(G)}
  c.restore();
 }
 // One cached soft-edged sprite, stretched over the whole wood: dark grass for trunks and shadows to stand on.
 nightMeadow(dk,G){
  if(!this.meadowSprite){
   const cv=document.createElement('canvas');cv.width=cv.height=256;const g=cv.getContext('2d'),gr=g.createRadialGradient(128,128,10,128,128,128);
   gr.addColorStop(0,'rgba(78,108,86,.95)');gr.addColorStop(.62,'rgba(70,98,78,.9)');gr.addColorStop(.86,'rgba(60,86,70,.45)');gr.addColorStop(1,'rgba(52,76,62,0)');
   g.fillStyle=gr;g.fillRect(0,0,256,256);this.meadowSprite=cv;
  }
  const c=this.c,rx=(G+9)*36,ry=(G+9)*18;c.globalAlpha=dk;c.drawImage(this.meadowSprite,-30-rx,18*G+43-ry,rx*2,ry*2);c.globalAlpha=1;
 }
 // Depth-sorted objects with their screen bounds: rebuilt once per farm snapshot, not per frame.
 sortedObjects(){
  const objs=this.farm.objects;
  if(!this.sorted||this.sorted.src!==objs||this.sorted.n!==objs.length){
   const list=sortByDepth(objs);
   this.sorted={src:objs,n:objs.length,list,bounds:list.map(objectBounds)};
  }
  return this.sorted;
 }
 // Build each semantic layer once per snapshot. Crops sort among themselves at their ground anchors;
 // solids retain footprint depth order and attached animals stay after their houses. Picking keeps
 // the original footprint order. Only buildings need the rectangle sort.
 standingOrder(){
  const src=this.farm.objects,key=this.layout.key;
  if(this.renderOrder?.src===src&&this.renderOrder.key===key)return this.renderOrder;
  const plots=[],roads=[],crops=[],buildings=[],sprites=[];
  const point=(x,y,draw,bounds)=>sprites.push({x,y,w:0,h:0,draw,bounds});
  const pixelPoint=(q,draw,parentId)=>{const p=isoInverse(q.x,q.y);point(p.x,p.y,draw,{x0:q.x-45,x1:q.x+45,y0:q.y-70,y1:q.y+20});if(parentId!==undefined)sprites[sprites.length-1].parentId=parentId};
  for(const o of src){
   if(o.type==='road'){roads.push({object:o,bounds:objectBounds(o)});continue}
   if(o.type==='plot'){
    plots.push({object:o,bounds:objectBounds(o)});
    if(o.crop)for(let i=0;i<2;i++)for(let j=0;j<3;j++){
     const x=o.x+.24+i*.45,y=o.y+.15+j*.3,p=P(x,y);
     crops.push({x,y,w:0,h:0,draw:()=>this.plotPlant(o,i,j),bounds:{x0:p.x-16,x1:p.x+16,y0:p.y-40,y1:p.y+12}});
    }
    continue;
   }
   buildings.push({...o,object:o,bounds:objectBounds(o)});
   if(o.animal&&!livestockMoves(o)){
    if(o.type==='duckpond'){const p=P(o.x+o.w/2,o.y+o.h/2);pixelPoint(p,()=>{if(!this.nightFlag)smallAnimal(this,p.x,p.y,'duck_swim')},o.id);continue}
    const p=P(o.x+.35,o.y+1.8);
    if(o.animal==='chicken')for(const [dx,dy] of [[12,6],[30,15]]){const q={x:p.x+dx,y:p.y+dy};pixelPoint(q,()=>this.chicken(q.x,q.y),o.id)}
    else{const q={x:p.x+(o.animal==='sheep'?18:o.animal==='bees'?19:17),y:p.y+9};pixelPoint(q,()=>{if(!(this.nightFlag&&o.animal!=='bees'))this.drawAnimal(o.animal,q)},o.id)}
   }
  }
  const area=this.layout.area;
  const sign=this.signPosition(area),signCell=isoInverse(sign.x,sign.y),{width:signWidth,lines:signLines}=this.signLayout();
  const signClearance={x0:sign.x-signWidth/2-14,x1:sign.x+signWidth/2+26,y0:sign.y-(signLines.length>1?60:50)-14,y1:sign.y+12};
  // Decorative fixtures sit outside the usable square, clear of the two lane entrances.
  // At most 24 lamps even on the largest farm; positions are cached with the solid order.
  const lampCount=Math.min(6,Math.max(2,Math.ceil(area/4)));
  for(let i=0;i<lampCount;i++){
   const along=.7+(area-1.4)*i/(lampCount-1);if(along>1.7&&along<3.3)continue;
   for(const [x,y] of [[along,-.35],[-.35,along],[along,area+.35],[area+.35,along]]){
    const p=P(x,y),bounds={x0:p.x-28,x1:p.x+28,y0:p.y-72,y1:p.y+16};
    if(overlaps(bounds,signClearance))continue;
    point(x,y,()=>this.perimeterLantern(p),bounds);
   }
  }
  const fence=(x,y,w,h)=>{const a=P(x,y),b=P(x+w,y+h);sprites.push({x,y,w,h,draw:()=>this.fence(x,y,x+w,y+h),bounds:{x0:Math.min(a.x,b.x)-5,x1:Math.max(a.x,b.x)+5,y0:Math.min(a.y,b.y)-24,y1:Math.max(a.y,b.y)+5}})};
  for(let i=0;i<area;i++)if(i!==2){fence(i,area+.08,1,0);fence(area+.08,i,0,1)}
  point(signCell.x,signCell.y,()=>this.welcomeSign(area),{x0:sign.x-signWidth/2-10,x1:sign.x+signWidth/2+24,y0:sign.y-72,y1:sign.y+12});
  const list=sortByDepth(buildings),slots=spriteSlots(list,sprites),entries=[];
  for(let i=0;i<=list.length;i++){entries.push(...slots[i]);if(i<list.length)entries.push(list[i])}
  crops.sort(compareDepth);return this.renderOrder={src,key,plots,roads,crops,entries};
 }
 draw(t){this.stepLighting(performance.now());let c=this.c;c.setTransform(this.dpr,0,0,this.dpr,0,0);c.clearRect(0,0,this.w,this.h);
  if(!this.w||!this.h)return;this.background();this.stats.frames++;
  if(!this.farm)return;const origin=this.origin();this.time=this.motion?t:0;
  if(!this.layout||this.layout.key!==this.layoutKey())this.buildLayout();
  const now=performance.now(),area=this.farm.size;
  // Keep objects live while panning and zooming; only the ground is cached.
  this.groundWash(origin);
  this.staticLayer(origin);
  c.setTransform(this.dpr,0,0,this.dpr,0,0);c.translate(origin.x,origin.y);c.scale(this.scale,this.scale);
  // Text and ready badges retain contrast above the ambient tint. Collect only
  // during this frame; all world sprites keep their existing depth order.
  this.lightMarkers=(this.lighting?.darkness||this.lighting?.warmth)?[]:null;
  this.lanternLights=[];this.view=this.viewRect(0);this.paintDynamic(c,this.view);
  const markers=this.lightMarkers;this.lightMarkers=null;this.paintLighting();
  c.setTransform(this.dpr,0,0,this.dpr,0,0);c.translate(origin.x,origin.y);c.scale(this.scale,this.scale);
  this.paintLanternLights();
  if(markers)for(const marker of markers){if(marker.kind==='label')this.label(marker.x,marker.y,marker.text,marker.ready);else if(marker.kind==='fn')marker.fn();else this.ready(marker.x,marker.y)}
  if(this.placement){let cell=this.placement.cell||this.hover;if(cell){let spec=this.placement.spec,obj={...cell,w:spec.w,h:spec.h};let busy=this.farm.objects.some(o=>o.id!==this.placement.ignore&&o.x<obj.x+obj.w&&o.x+o.w>obj.x&&o.y<obj.y+obj.h&&o.y+o.h>obj.y);let valid=obj.x>=0&&obj.y>=0&&obj.x+obj.w<=area&&obj.y+obj.h<=area&&!busy;this.footprint(obj,valid?'#f9f8d076':'#e3857570',valid?'#fff8c4':'#c96c5e');}}
  else if(this.hover&&!this.hoverId&&this.hover.x>=0&&this.hover.y>=0&&this.hover.x<area&&this.hover.y<area)this.tile(this.hover.x,this.hover.y,'#fffbe124','#faf7cb99',2);
  if(this.particles.length){let live=0;for(let particle of this.particles){particle.x+=particle.dx;particle.y+=particle.dy;particle.dy+=.08;particle.age++;c.globalAlpha=Math.max(0,1-particle.age/22);this.ellipse(particle.x,particle.y,2,3,particle.color);if(particle.age<22)this.particles[live++]=particle}this.particles.length=live;c.globalAlpha=1}
  // Ambient petals, subtle rather than a full-screen particle storm.
  if(this.motion)for(let i=0;i<6;i++){let x=-330+((t*6+i*123)%700),y=130+Math.sin(t*.7+i)*15+i*41;this.ellipse(x,y,1.5,1,(this.lighting?.darkness||0)>.5?'#e3c98580':'#fff9d380')}
  this.mini?.update(now);this.cb.frame?.();
 }
 // Everything that moves or changes with the farm: haze, objects (depth-sorted, culled), the goose and the team.
 paintDynamic(c,view){
  const G=this.grid();
  this.forestFog(G,view);
  if(this.c)this.lakeLife(view);
  const {plots,roads=[],crops,entries}=this.standingOrder(),visible=b=>overlaps(b,view),lit=this.placement?null:this.hoverId,drawnObjects=new Set();
  for(const r of roads)if(visible(r.bounds)){this.drawObject(r.object);if(r.object.id===lit)this.footprint(r.object,'#fffbe130','#fff6b8');drawnObjects.add(r.object.id)}
  // Soil is a ground surface: no later bed can paint over a vehicle, animal or fence.
  for(const p of plots)if(visible(p.bounds)){this.plotGround(p.object);drawnObjects.add(p.object.id)}
  // Vegetation is a separate layer below all solid sprites: no per-plant scratch canvases or masks.
  for(const e of crops)if(visible(e.bounds))e.draw();
  const list=entries.filter(e=>visible(e.bounds)),moving=teamSprites(this),slots=spriteSlots(list,moving);
  // Buildings, animals, fence and moving sprites keep their existing depth/parent constraints.
  for(let i=0;i<=list.length;i++){
   for(const sp of slots[i])sp.draw();
   if(i===list.length)break;
   const e=list[i];
   if(e.object){if(lit&&e.object.id===lit)this.drawLit(e.object);else this.drawObject(e.object);drawnObjects.add(e.object.id)}
   else e.draw();
  }
  for(const p of plots)if(visible(p.bounds))this.plotMarkers(p.object);
  // The tea arbor is dynamic so it paints above lanterns and fences, while front trees still cover it.
  const arbor=this.projectStage('tea_arbor');if(arbor||this.farm.home_projects?.active==='tea_arbor')drawTeaArbor(this,this.arborPos(),arbor);
  this.stats.objects=this.farm.objects.length;this.stats.drawn=drawnObjects.size;
  drawTeamZones(this);
  this.paintTrees(this.layout.after,view); // trees in front of the fenced square stand over whatever is behind them
  this.skyFlock(view);
 }
 // Mouse hover: the object itself is lightened and gets a soft pale outline (drawn into a scratch canvas, then filtered once).
 // The same filter is the CSS token --farm-lit (style.css) used by the village sign and residents: keep the two in step.
 drawLit(o){
  const main=this.c;
  if(!('filter' in main)){this.drawObject(o);this.footprint(o,'#fffbe130','#fff6b8');return}
  const b=objectBounds(o),k=this.dpr*this.scale,w=Math.ceil((b.x1-b.x0)*k),h=Math.ceil((b.y1-b.y0)*k);
  if(w<1||h<1||w*h>8e6){this.drawObject(o);return}
  const cv=this.litCanvas||(this.litCanvas=document.createElement('canvas'));
  if(cv.width!==w||cv.height!==h){cv.width=w;cv.height=h}
  const g=cv.getContext('2d');g.setTransform(1,0,0,1,0,0);g.clearRect(0,0,w,h);g.setTransform(k,0,0,k,-b.x0*k,-b.y0*k);
  this.c=g;try{this.drawObject(o)}finally{this.c=main}
  main.save();main.filter=`brightness(1.12) drop-shadow(0 0 ${this.dpr}px #fffbd0) drop-shadow(0 0 ${this.dpr*2}px #fff2a0)`;main.drawImage(cv,b.x0,b.y0,w/k,h/k);main.restore();
 }
 path(G=12){this.poly([P(-3,3),P(-1,2),P(2,G+1),P(1,G+2)],'#e4dcc160');}
 forestFog(G=12,view=null){
  const alpha=1-(this.lighting?.darkness||0);if(alpha<=0)return;
  const c=this.c,clouds=this.layout.fog;
  // Soft haze hugs the outer tree line; interactive farm objects remain above it.
  // Bake one soft circle and stretch the entire texture: the gradient and its
  // boundary always share coordinates, including after camera pan and zoom.
  if(!this.fogSprite){
   const cv=document.createElement('canvas');cv.width=cv.height=128;const g=cv.getContext('2d'),gradient=g.createRadialGradient(64,64,1,64,64,64);
   gradient.addColorStop(0,'rgba(237,243,230,.12)');gradient.addColorStop(.38,'rgba(237,243,230,.25)');gradient.addColorStop(1,'rgba(237,243,230,0)');
   g.fillStyle=gradient;g.fillRect(0,0,128,128);this.fogSprite=cv;
  }
  clouds.forEach(fog=>{
   const drift=this.motion?Math.sin(this.time*.16+fog.phase)*3:0,x=fog.x+drift,y=fog.y;
   if(view&&(x+fog.rx<view.x0||x-fog.rx>view.x1||y+fog.ry<view.y0||y-fog.ry>view.y1))return;
   c.save();c.globalAlpha=alpha;c.drawImage(this.fogSprite,x-fog.rx,y-fog.ry,fog.rx*2,fog.ry*2);c.restore();
  });
 }
 perimeterLantern(p){
  const {x,y}=p;this.shadow(x,y,7,3);
  this.ellipse(x,y,5,2.3,'#7c8267');this.line(x,y-2,x,y-40,'#65745f',3);
  this.line(x-1,y-4,x-1,y-36,'#a0a580',.8);
  this.poly([{x:x-5,y:y-49},{x:x+5,y:y-49},{x:x+4,y:y-37},{x:x-4,y:y-37}],lightingColor([229,211,160],[255,237,177],this.lighting?.darkness||0),'#65745f',1.3);
  // The opaque flame shares the fixture's depth, so a foreground tree can hide it.
  if((this.lighting?.darkness||0)>.15)this.line(x-1.6,y-46,x-1.6,y-40,'#fff3c9',1.4);
  this.line(x,y-48,x,y-38,'#a0916a',.9);
  this.poly([{x:x-7,y:y-49},{x,y:y-55},{x:x+7,y:y-49}],'#63765f');
  this.ellipse(x,y-56,1.4,1.6,'#a9ac83');this.line(x-5,y-36,x+5,y-36,'#65745f',2);
  this.lanternLights?.push(p);
 }
 paintLanternLights(){
  const strength=clamp(((this.lighting?.darkness||0)-.15)/.85,0,1);
  if(!strength||!this.lanternLights?.length)return;
  // One tiny reusable glow texture. No blur filters, screen-sized light layer or per-frame gradients.
  if(!this.lanternGlow){
   const cv=document.createElement('canvas');cv.width=112;cv.height=176;
   const g=cv.getContext('2d');g.scale(2,2);g.translate(28,72);
   const halo=g.createRadialGradient(0,-43,1,0,-43,23);halo.addColorStop(0,'#ffdf9270');halo.addColorStop(.3,'#f6c76630');halo.addColorStop(1,'#f6c76600');
   g.fillStyle=halo;g.fillRect(-24,-67,48,48);
   g.save();g.scale(1,.42);const pool=g.createRadialGradient(0,0,1,0,0,25);pool.addColorStop(0,'#f2c97a48');pool.addColorStop(1,'#edc37900');g.fillStyle=pool;g.fillRect(-25,-25,50,50);g.restore();
   this.lanternGlow=cv;
  }
  const c=this.c;c.save();c.globalAlpha=strength;
  for(const p of this.lanternLights)c.drawImage(this.lanternGlow,p.x-28,p.y-72,56,88);
  c.restore();
 }
 pond(x,y){this.ellipse(x+3,y+8,105,57,'#c8d4b3');this.ellipse(x,y,95,49,'#a9c8bb');this.ellipse(x-4,y-5,84,39,'#b1d0c4');this.line(x-38,y-9,x-5,y-9,'#e2eee065',2);this.line(x+5,y+7,x+45,y+7,'#e2eee075',1.5);for(let i=0;i<8;i++){let a=i*.8;this.ellipse(x+Math.cos(a)*88,y+Math.sin(a)*41,7,3,'#b3bd9c')}this.ellipse(x+40,y-15,8,3,'#7aab82');this.ellipse(x+30,y+12,7,3,'#89b48c')}
 lakeSize(){return {rx:250,ry:128}}
 arborPos(){const p=this.pondCenter(),{rx}=this.lakeSize();return {x:p.x+rx+24,y:p.y+30}}
 lakeShape(){
  if(this.lakePts)return this.lakePts;
  // Irregular shoreline: a few lobes plus a bay that opens toward the pier; normalised so the outline fits the lakeSize() ellipse.
  const n=44,raw=Array.from({length:n},(_,i)=>{const a=i/n*Math.PI*2,d=Math.atan2(Math.sin(a+1.12),Math.cos(a+1.12));return {a,r:.78+.13*Math.cos(2*(a-.2))+.08*Math.cos(3*(a+1.1))+.05*Math.cos(5*(a-2.6))+.2*Math.exp(-d*d/.2)}}),top=Math.max(...raw.map(p=>p.r));
  return this.lakePts=raw.map(p=>({a:p.a,r:p.r/top}));
 }
 // Is the normalised offset (dx/rx, dy/ry) from the lake centre inside the shoreline?
 inLake(dx,dy){
  const pts=this.lakeShape(),n=pts.length,m=Math.hypot(dx,dy);if(m>=1)return false;
  const t=((Math.atan2(dy,dx)/(Math.PI*2))+1)%1*n,i=Math.floor(t)%n,f=t-Math.floor(t);
  return m<pts[i].r+(pts[(i+1)%n].r-pts[i].r)*f;
 }
 lakeEdge(i,x,y,k=1){const pts=this.lakeShape(),p=pts[((i%pts.length)+pts.length)%pts.length],{rx,ry}=this.lakeSize();return {x:x+Math.cos(p.a)*rx*p.r*k,y:y+Math.sin(p.a)*ry*p.r*k}}
 // A closed smooth path through the irregular shoreline, scaled/offset for the bank, sand and water layers.
 lakePath(x,y,k=1,ox=0,oy=0){
  const c=this.c,{rx,ry}=this.lakeSize(),pts=this.lakeShape().map(p=>({x:x+ox+Math.cos(p.a)*rx*p.r*k,y:y+oy+Math.sin(p.a)*ry*p.r*k})),n=pts.length,mid=(a,b)=>({x:(a.x+b.x)/2,y:(a.y+b.y)/2});
  const first=mid(pts[n-1],pts[0]);c.beginPath();c.moveTo(first.x,first.y);
  for(let i=0;i<n;i++){const m=mid(pts[i],pts[(i+1)%n]);c.quadraticCurveTo(pts[i].x,pts[i].y,m.x,m.y)}c.closePath();
 }
 lake(x,y){
  const c=this.c,{rx}=this.lakeSize();
  this.lakePath(x,y,1.1,5,11);c.fillStyle='#c3cfaa';c.fill();
  this.lakePath(x,y,1.065,1,4);c.fillStyle='#ded9b4';c.fill();
  this.lakePath(x,y,1);c.fillStyle='#a6cdbf';c.fill();
  const g=c.createRadialGradient(x-30,y-14,8,x,y,rx*.95);g.addColorStop(0,'#6aa09f');g.addColorStop(.55,'#80b3ac');g.addColorStop(1,'#9fcabc');
  this.lakePath(x,y,.86,-5,-2);c.fillStyle=g;c.fill();
  this.lakePath(x,y,.5,-26,-12);c.fillStyle='#5a959a55';c.fill();
  for(const [dx,dy,w] of [[-92,-26,38],[18,-44,26],[78,10,32],[-44,30,40],[116,-14,20],[-130,12,26]])this.line(x+dx,y+dy,x+dx+w,y+dy,'#e8f3ea88',1.6);
  for(let i=0;i<44;i++)if((i*7)%5===0){const e=this.lakeEdge(i,x,y,1.045);this.ellipse(e.x,e.y,2+(i%3),1.2+(i%2),i%2?'#b8b6a0':'#cfcbb0')}
  // reeds with cattails, kept away from the pier and the arbor
  for(const i of [4,7,11,14,17,20,23,26,29,32]){
   const e=this.lakeEdge(i,x,y,.99);
   for(let k=0;k<4;k++){const bx=e.x+(k-1.5)*3.2,h=14+((i*3+k*5)%7);this.line(bx,e.y,bx+(k%2?2:-2),e.y-h,'#68925d',1.6);if(k%2)this.ellipse(bx+2,e.y-h-2,1.7,4,'#8b6a48')}
   this.ellipse(e.x,e.y+1,9,2.6,'#7fb092aa');
  }
  this.bogatyrStone(x,y);
  for(const [dx,dy,f] of [[-96,20,1],[-60,40,0],[10,44,1],[72,26,0],[-132,-6,0],[-20,-30,1]]){this.ellipse(x+dx,y+dy,9,3.6,'#6f9f6e');this.ellipse(x+dx+2,y+dy-.5,5,1.8,'#86b384');if(f){this.ellipse(x+dx,y+dy-3,2.6,2,'#f1cdd6');this.ellipse(x+dx,y+dy-4,1.1,1,'#ecd070')}}
 }
 // A nod to the owner's future game: the hero's stone at the crossroads, a sword in it and a raven on the hilt.
 worldToScreen(x,y){const o=this.origin();return {x:x*this.scale+o.x,y:y*this.scale+o.y}}
 stoneRavenPos(){const e=this.stonePos();return {x:e.x+17,y:e.y-61}}
 stonePos(){const p=this.pondCenter(),e=this.lakeEdge(16,p.x,p.y,1.12);return {x:e.x,y:e.y}}
 bogatyrStone(x,y){
  const e=this.lakeEdge(16,x,y,1.12),c=this.c;
  this.ellipse(e.x+6,e.y+4,24,7,'#5a6f4a30');
  this.poly([{x:e.x-17,y:e.y+2},{x:e.x-14,y:e.y-13},{x:e.x-4,y:e.y-22},{x:e.x+9,y:e.y-19},{x:e.x+17,y:e.y-8},{x:e.x+15,y:e.y+3},{x:e.x,y:e.y+7}],'#a9ab9a','#80826f',1);
  this.poly([{x:e.x-17,y:e.y+2},{x:e.x-14,y:e.y-13},{x:e.x-6,y:e.y-9},{x:e.x-7,y:e.y+4}],'#9a9c8b');
  this.poly([{x:e.x+9,y:e.y-19},{x:e.x+17,y:e.y-8},{x:e.x+15,y:e.y+3},{x:e.x+8,y:e.y-4}],'#b9bba9');
  this.ellipse(e.x-3,e.y-18,8,3,'#7ea468');this.ellipse(e.x-11,e.y-6,5,2.4,'#86ad70');
  this.line(e.x-9,e.y-2,e.x-3,e.y-8,'#6b6d5c',1);this.line(e.x+2,e.y-7,e.x+8,e.y-2,'#6b6d5c',1); // carved runes
  this.line(e.x-3,e.y-4,e.x-1,e.y-9,'#6b6d5c',1);
  // the sword: blade, crossguard, grip and a pommel
  const sx=e.x+2,sy=e.y-20;
  this.line(sx,sy,sx+2,sy-30,'#d7dde0',2.6);this.line(sx-.5,sy,sx+1.5,sy-29,'#f3f6f6',.9);
  this.line(sx-7,sy-31,sx+9,sy-33,'#8a6b3c',2.4);
  this.line(sx+2,sy-33,sx+2.6,sy-40,'#5c432a',2.6);this.ellipse(sx+2.7,sy-41,2.2,2.2,'#c9a85d');
  // the raven
  this.ellipse(sx+11,sy-39,4,3,'#2c3037');this.ellipse(sx+15,sy-41,2.2,2.2,'#2c3037');this.poly([{x:sx+17,y:sy-41},{x:sx+21,y:sy-40},{x:sx+17,y:sy-39.5}],'#4a4d55');this.ellipse(sx+15.6,sy-41.4,.6,.6,'#e9d9a0');
  void c;
 }
 pierStakes(G){
  const y0=G-.65,y1=G+2.2;
  for(const [x,y] of [[2,y0],[3,y0],[3,y1],[2,y1]]){const q=P(x,y,2);this.line(q.x,q.y,q.x,q.y-15,'#c9a36a',2.4);this.ellipse(q.x,q.y-15,1.8,1.2,'#e9d29d')}
  const a=P(2,y0,12),b=P(3,y0,12),c=P(3,y1,12),d=P(2,y1,12);
  for(const [u,v] of [[a,b],[b,c],[c,d],[d,a]])this.line(u.x,u.y,v.x,v.y,'#d96f5e',1.3);
 }
 lakePier(G){
  const stage=this.projectStage('lake_pier');
  if(stage<1){if(this.farm?.home_projects?.active==='lake_pier')this.pierStakes(G);return}
  const y0=G-.65,y1=G+2.2,Z=4,TH=6,T=(x,y,z=Z)=>P(x,y,z),a=T(2,y0),b=T(3,y0),c=T(3,y1),d=T(2,y1);
  // shade cast by the deck on the water, then the piles that carry it
  this.poly([P(2.1,y0+.5,-9),P(3.4,y0+.5,-9),P(3.4,y1+.2,-9),P(2.1,y1+.2,-9)],'#4b7f7a30');
  for(let y=y0+.3;y<=y1-.1;y+=.58)for(const x of [2.08,2.92]){
   const top=P(x,y,Z-TH),bot=P(x,y,-11);this.line(top.x,top.y,bot.x,bot.y,'#5d4733',3.6);this.line(top.x-1.1,top.y,bot.x-1.1,bot.y,'#7b5e42',1);
   if(y>G-.1)this.ellipse(bot.x,bot.y,4.6,1.9,'#8fbab0');
  }
  // the deck: two visible edge faces, planks across the walk, beams along it
  this.poly([b,c,T(3,y1,Z-TH),T(3,y0,Z-TH)],'#6c5039');
  this.poly([d,c,T(3,y1,Z-TH),T(2,y1,Z-TH)],'#7e6044');
  this.poly([a,b,c,d],'#bb9365','#755a3f',1.2);
  const rows=Math.round((y1-y0)/.16);
  for(let i=0;i<rows;i++){
   const ya=y0+i*(y1-y0)/rows,yb=y0+(i+1)*(y1-y0)/rows,l=T(2,yb),r=T(3,yb);
   if(i%2)this.poly([T(2,ya),T(3,ya),r,l],'#c4a072');
   this.line(l.x,l.y,r.x,r.y,'#8c6a46',1);
  }
  this.line(a.x,a.y,d.x,d.y,'#d3ad78',1.6);this.line(b.x,b.y,c.x,c.y,'#e0bc87',1.8);this.line(a.x,a.y,b.x,b.y,'#e0bc87',1.2);
  for(const p of [c,d]){this.line(p.x,p.y,p.x,p.y-12,'#75583c',3.6);this.ellipse(p.x,p.y-13,2.9,1.6,'#ddbb83')}
  const lp=P(2.92,y1-.12,Z);
  this.line(lp.x,lp.y,lp.x,lp.y-40,'#5d4733',3);
  this.poly([{x:lp.x-5,y:lp.y-50},{x:lp.x+5,y:lp.y-50},{x:lp.x+4,y:lp.y-39},{x:lp.x-4,y:lp.y-39}],'#f1dc9b','#5d4733',1.2);
  this.poly([{x:lp.x-7,y:lp.y-50},{x:lp.x,y:lp.y-56},{x:lp.x+7,y:lp.y-50}],'#5d4733');
  if(stage>=2){
   const posts=[];for(let y=y0+.3;y<=y1-.8;y+=.5)posts.push(P(2.97,y,Z));
   for(const p of posts){this.line(p.x,p.y,p.x,p.y-15,'#8b6949',2.8);this.ellipse(p.x,p.y-16,2.4,1.4,'#d8b582')}
   for(let i=1;i<posts.length;i++){const p=posts[i-1],q=posts[i];this.line(p.x,p.y-14,q.x,q.y-14,'#a27e55',2.2);this.line(p.x,p.y-7,q.x,q.y-7,'#a27e55',1.8)}
   const near=[];for(let y=y0+.3;y<=y0+1.4;y+=.55)near.push(P(2.03,y,Z));
   for(const p of near){this.line(p.x,p.y,p.x,p.y-15,'#8b6949',2.8);this.ellipse(p.x,p.y-16,2.4,1.4,'#d8b582')}
   for(let i=1;i<near.length;i++){const p=near[i-1],q=near[i];this.line(p.x,p.y-14,q.x,q.y-14,'#a27e55',2.2);this.line(p.x,p.y-7,q.x,q.y-7,'#a27e55',1.8)}
   const seat=[P(2.1,y1-1.15,Z+8),P(2.72,y1-1.15,Z+8),P(2.72,y1-.9,Z+8),P(2.1,y1-.9,Z+8)];
   for(const p of [seat[1],seat[2],seat[3]])this.line(p.x,p.y,p.x,p.y+8,'#795a3e',2);
   this.poly(seat,'#ad8558','#75583f',1);
   const back=[P(2.1,y1-1.15,Z+8),P(2.72,y1-1.15,Z+8)];this.line(back[0].x,back[0].y,back[0].x,back[0].y-11,'#795a3e',2);this.line(back[1].x,back[1].y,back[1].x,back[1].y-11,'#795a3e',2);this.line(back[0].x,back[0].y-10,back[1].x,back[1].y-10,'#ad8558',3);
   const rod=P(2.06,y1-.12,Z),tip={x:rod.x-30,y:rod.y-36};
   this.line(rod.x,rod.y,tip.x,tip.y,'#6b6048',2);this.line(tip.x,tip.y,tip.x-4,tip.y+40,'#e5e0bc',.7);this.ellipse(tip.x-4,tip.y+40,2.2,2.2,'#d08c5b');
   const bucket=P(2.78,y1-.55,Z);this.poly([{x:bucket.x-4,y:bucket.y-5},{x:bucket.x+4,y:bucket.y-5},{x:bucket.x+3,y:bucket.y+3},{x:bucket.x-3,y:bucket.y+3}],'#8c7558','#634f3a',1);
  }
 }
 lakeLife(view){
  const p=this.pondCenter(),{rx,ry}=this.lakeSize();
  if(!overlaps({x0:p.x-rx-20,x1:p.x+rx+80,y0:p.y-ry-70,y1:p.y+ry+30},view))return;
  const t=this.time||0,c=this.c,dk=this.lighting?.darkness||0,G=this.grid(),wave=this.motion?Math.sin(t*1.6):0;
  for(let i=0;i<4;i++){const x=p.x-78+i*38+(this.motion?Math.sin(t*.32+i*3)*7:0),y=p.y-6+i*12+(i%2)*6;
   this.ellipse(x,y,6,2,'#6b9f95a0');this.poly([{x:x+5,y},{x:x+9,y:y-2},{x:x+9,y:y+2}],'#679b90a0');
   this.line(x-10,y+8+wave,x+10,y+8+wave,'#e2eee078',1);
  }
  const ring=(x,y,ph,k=1)=>{c.save();c.globalAlpha=(1-ph)*.55;c.strokeStyle='#eef7f0';c.lineWidth=1;c.beginPath();c.ellipse(x,y,(3+ph*20)*k,(1.4+ph*8)*k,0,0,Math.PI*2);c.stroke();c.restore()};
  if(this.motion){
   for(let i=0;i<3;i++)ring(p.x+[-54,44,-4][i]*1.3,p.y+[14,-20,32][i],(t*.22+i*.34)%1);
  }
  if(this.projectStage('lake_pier')>=1){
   const y0=G-.65,y1=G+2.2;
   // Only the piles on the open (right) side get rings: the left row stands under the deck, where rings would show through the planks.
   for(let y=Math.max(y0+.3,G+.2);y<=y1-.1;y+=.58){const b=P(2.92,y,-11),ph=this.motion?((t*.45+y*2)%1):.3;ring(b.x+2,b.y+3,ph,.45)}
   const lp=P(2.92,y1-.12,4);this.lanternLights?.push({x:lp.x,y:lp.y+7});
   if(this.projectStage('lake_pier')>=2){
    const bp=P(3.95,G+1.7),bob=this.motion?Math.sin(t*1.3)*1.2:0,x=bp.x,y=bp.y+bob;
    this.ellipse(x+2,y+5,17,4,'#4b7f7a40');
    this.poly([{x:x-17,y:y-3},{x:x+17,y:y-3},{x:x+11,y:y+6},{x:x-11,y:y+6}],'#9a7650','#6a4f35',1);
    this.poly([{x:x-17,y:y-3},{x:x+17,y:y-3},{x:x+15,y:y-1},{x:x-15,y:y-1}],'#c8a574');
    this.line(x-6,y-3,x-14,y-12+bob,'#7a603f',1.6);this.line(x+6,y-3,x+14,y-11+bob,'#7a603f',1.6);
    const rope=P(3,G+1.55,4);this.line(rope.x,rope.y-8,x-12,y-3,'#d9c9a1',.9);
   }
  }
  if(dk>.4){c.save();c.globalAlpha=Math.min(1,(dk-.4)*1.7);for(let i=0;i<5;i++){const w=16-i*2.4+(this.motion?Math.sin(t*1.7+i)*2:0);this.line(p.x+50-w/2,p.y-34+i*10,p.x+50+w/2,p.y-34+i*10,'#f2edc4',1.6)}c.restore()}
  // Lake dwellers: the wild duck is always about (it paddles a lazy loop and tips over to feed now and then); a pair of swans
  // glides by in turn; every minute or so a flock of swan-geese crosses the sky above the water. Pure scene clock, no state.
  const face=v=>v>=0?1:-1,sprite=(kind,x,y,dir,tilt=0)=>{c.save();c.translate(x,y);c.scale(dir,1);if(tilt)c.rotate(tilt);smallAnimal(this,0,0,kind);c.restore()};
  {const u=t*.13,dx=-Math.sin(u)*70,x=p.x-42+Math.cos(u)*70,y=p.y+8+Math.sin(u*2)*16,dive=this.motion&&Math.sin(t*.55)>.93;
   // Tipping over to feed: only the tail end shows, in the same ripple as the swimming pose (duck_swim draws its own ripple).
   if(dive){this.ellipse(x,y,11,2.8,'#b6d3cf');this.ellipse(x,y-2.6,6,4,'#ada186');this.poly([{x:x-2.4,y:y-4.6},{x:x+2.4,y:y-4.6},{x:x+.6,y:y-11}],'#3f4a40');this.ellipse(x,y-.5,7.6,1.5,'#c3dcd7');this.ellipse(x,y+.6,9,1.2,'#eef7f080')}
   else sprite('duck_swim',x,y,face(dx));}
  if(((t%120)+120)%120<80){const u=t*.07+2,x=p.x+70+Math.cos(u)*50,y=p.y-8+Math.sin(u)*14,dir=face(-Math.sin(u));
   for(const k of [0,1]){const ox=k*34*dir*-1,oy=k*7;this.ellipse(x+ox,y+oy+3,19,4,'#a8cfc6a0');sprite('swan',x+ox,y+oy,dir)}}

 }
 // The swan-geese cross the sky above everything else (after the trees), so nothing on the ground ever covers them.
 skyFlock(view){
  const p=this.pondCenter(),{ry}=this.lakeSize(),t=this.time||0,c=this.c,dk=this.lighting?.darkness||0;
  if(!this.motion)return;
  const T=((t+30)%72+72)%72;if(T>=17)return;
  const k=T/17,fx=p.x-330+k*820,fy=p.y-ry-95-Math.sin(k*Math.PI)*34;
  // Painted last of all (also after the night-lit sign board and the badges), so no board or tree ever covers a bird.
  const paint=()=>{
   for(let i=0;i<5;i++){const row=Math.ceil(i/2),side=i%2?1:-1,bx=fx-row*26,by=fy+(i?side*row*11:0)+Math.sin(t*3+i)*2,flap=Math.sin(t*8+i*1.3);
    c.save();c.globalAlpha=Math.min(1,k*6,(1-k)*6)*(1-.4*dk);
    this.ellipse(bx,by,8,3.4,'#f6f3e6');this.ellipse(bx+8,by-1,2.6,2.2,'#f6f3e6');this.poly([{x:bx+10,y:by-1},{x:bx+14,y:by},{x:bx+10,y:by+1}],'#d8a85f');
    this.poly([{x:bx-1,y:by-1},{x:bx-7,y:by-7*flap-2},{x:bx+4,y:by-2}],'#ffffff','#d9d6c4',.6);this.poly([{x:bx-1,y:by+1},{x:bx-8,y:by+6*flap+3},{x:bx+3,y:by+2}],'#e9e6d6');
    c.restore()}
  };
  if(this.lightMarkers)this.lightMarkers.push({kind:'fn',fn:paint});else paint();
 }
 // Trees never stand on the pond (screen-space test on the sprite) nor inside the fenced farm square.
 treeBlocked(x,y,s){const G=this.grid(),area=this.farm?.size||8;if(x>-.3&&y>-.3&&x<area+.25&&y<area+.25)return true;
  // Entrance lanes, the way down to the lake, the farm sign and the arbor stay free of trunks.
  if((x>1.3&&x<3.7&&y<0.5&&y>-4)||(y>1.3&&y<3.7&&x<0.5&&x>-4.5)||(x>1.1&&x<3.9&&y>=area-.5&&y<G+3.2))return true;
  if(Math.hypot(x+.8,y-(area-.7))<1.9)return true;
  {const q=P(x,y),ap=this.arborPos();if(Math.abs(q.x-ap.x)<62&&q.y>ap.y-48&&q.y<ap.y+44)return true}
  const p=P(x,y),cx=this.pondCenter().x,cy=this.pondCenter().y,rx=this.lakeSize().rx+40,ry=this.lakeSize().ry+12;
  for(const [dx,dy] of [[0,0],[-18,0],[18,0],[0,-20],[-16,-20],[16,-20],[0,-40],[-17,-40],[17,-40],[0,-60]]){const u=(p.x+dx*s-cx)/rx,v=(p.y+dy*s-cy)/ry;if(u*u+v*v<=1)return true}
  return false}
 pondCenter(){const G=this.grid();return{x:-36*G+10,y:18*G+140}}
 tree(x,y,s=1){if(this.treeBlocked(x,y,s))return;this.treeSprite(x,y,s)}
 treeSprite(x,y,s=1,withShadow=true){let p=P(x,y),c=this.c;c.save();c.translate(p.x,p.y);c.scale(s,s);if(withShadow)this.shadow(0,0,19,8);this.line(0,0,0,-40,'#9e8a60',4);this.ellipse(0,-40,20,28,'#71976d');this.ellipse(-7,-48,15,22,'#82a77a');this.ellipse(6,-40,15,22,'#7da073');this.ellipse(-4,-56,11,14,'#96b183');c.restore()}
 fence(x1,y1,x2,y2){let a=P(x1,y1),b=P(x2,y2);for(let z of [6,13])this.line(a.x,a.y-z,b.x,b.y-z,'#a89063',2.5);for(let p of [a,b]){this.line(p.x,p.y,p.x,p.y-19,'#b29a70',3);this.ellipse(p.x,p.y-19,2.4,1.4,'#d6c295')}}
 signLayout(){
  const stage=[[2,'Огород'],[5,'Участок'],[8,'Хозяйство'],[12,'Ферма'],[17,'Большая ферма'],[29,'Усадьба']].find(([max])=>this.farm.level<=max)?.[1]||'Усадьба';
  const owner=String(this.farm.name||'').replace(/^Ферма\s+/i,'').trim(),label=`${stage} ${owner||this.farm.name||''}`.trim();
  const c=this.c;if(c){c.save();c.font='700 10px "Segoe UI",sans-serif'}
  const textWidth=line=>c?.measureText?c.measureText(line).width:Array.from(line).length*7;
  let lines=[label];if(textWidth(label)>118){const words=label.split(/\s+/),left=[],right=[];for(const word of words){const joined=[...left,word].join(' ');if(!left.length||textWidth(joined)<92)left.push(word);else right.push(word)}if(right.length)lines=[left.join(' '),right.join(' ')];else{const chars=Array.from(label),at=Math.ceil(chars.length/2);lines=[chars.slice(0,at).join(''),chars.slice(at).join('')]}}
  // Long names never grow the board: two lines at most, each clipped with an ellipsis, so the sign stays small and clear of the farm.
  const clip=(line,max)=>{if(textWidth(line)<=max)return line;const t=Array.from(line);while(t.length>1&&textWidth(t.join('')+'…')>max)t.pop();return t.join('').trimEnd()+'…'};
  lines=lines.slice(0,2).map(l=>clip(l,116));
  const measured=Math.max(...lines.map(textWidth)),boardWidth=Math.min(132,Math.max(52,measured+17));if(c)c.restore();
  return {lines,width:boardWidth,twoPosts:boardWidth>80};
 }
 signWidth(){return this.signLayout().width}
 signPosition(area){return P(-.8,area-.7)}
 signBoard(sign,left,top,width,height,lines,night){
  const c=this.c,two=lines.length>1,pts=(d=0)=>[{x:left+3,y:top+d},{x:left+width-3,y:top+d},{x:left+width,y:top+4+d},{x:left+width,y:top+height-4+d},{x:left+width-3,y:top+height+d},{x:left+3,y:top+height+d},{x:left,y:top+height-4+d},{x:left,y:top+4+d}];
  this.poly(pts(3),night?'#7d6240':'#a58559');
  const g=c.createLinearGradient(0,top,0,top+height);g.addColorStop(0,night?'#dcc48f':'#f1dfb2');g.addColorStop(1,night?'#c3a676':'#dcc08c');
  this.poly(pts(),g,'#8d6c45',1.5);
  this.line(left+5,top+3.5,left+width-5,top+3.5,'#fff3cf',1);this.line(left+5,top+height-3.5,left+width-5,top+height-3.5,'#bd9a64',1);
  for(const [nx,ny] of [[left+4.5,top+5],[left+width-4.5,top+5],[left+4.5,top+height-5],[left+width-4.5,top+height-5]])this.ellipse(nx,ny,1.1,1.1,'#7a6240');
  c.textAlign='center';c.font='700 10px "Segoe UI",sans-serif';
  lines.forEach((line,i)=>{const y=top+(two?15+i*13:17);c.fillStyle='#fff0c6';c.fillText(line,sign.x+.6,y+.8,width-14);c.fillStyle=night?'#2f2617':'#4d3c27';c.fillText(line,sign.x,y,width-14)});
 }
 welcomeSign(area){
  const sign=this.signPosition(area),{lines,width,twoPosts}=this.signLayout(),left=sign.x-width/2,two=lines.length>1,top=sign.y-(two?54:44),height=two?37:26,dk=this.lighting?.darkness||0;
  this.shadow(sign.x,sign.y+1,width/2+5,6);
  for(const k of [-1,1]){const gx=sign.x+k*(width/2+3);this.ellipse(gx,sign.y,7,2.6,'#86a96a');for(let i=0;i<3;i++)this.line(gx+(i-1)*3,sign.y,gx+(i-1)*4,sign.y-5-i%2*2,'#6f9a5c',1.2);if(k>0){this.line(gx+5,sign.y,gx+5,sign.y-6,'#7ea468',1);this.ellipse(gx+5,sign.y-7,2,1.7,'#e7a8b5')}}
  const posts=twoPosts?[left+9,left+width-9]:[sign.x],last=posts[posts.length-1];
  for(const x of posts){this.line(x,sign.y+1,x,top+3,'#5f4630',5);this.line(x-1,sign.y,x-1,top+3,'#8c6c4a',2.6);this.ellipse(x,sign.y+1,4,1.8,'#7a6246');this.poly([{x:x-4.5,y:top+3},{x,y:top-3},{x:x+4.5,y:top+3}],'#6b5036','#4e3a27',.8)}
  const lx=left+width+9,ly=top+13;
  this.line(last,top-1,lx,top-1,'#5f4630',2);this.line(lx,top-1,lx,ly-6,'#4e3a27',1);
  this.poly([{x:lx-4,y:ly-6},{x:lx+4,y:ly-6},{x:lx+3.5,y:ly+4},{x:lx-3.5,y:ly+4}],dk>.15?'#ffe7a0':'#d9c58c','#4e3a27',1);
  this.poly([{x:lx-5.5,y:ly-6},{x:lx,y:ly-10},{x:lx+5.5,y:ly-6}],'#4e3a27');
  this.lanternLights?.push({x:lx,y:ly+39});
  // After dusk the board is painted above the night tint (like the ready badges) so the name stays readable by lantern light.
  if(this.lightMarkers&&dk>.2)this.lightMarkers.push({kind:'fn',fn:()=>this.signBoard(sign,left,top,width,height,lines,true)});
  else this.signBoard(sign,left,top,width,height,lines,false);
 }
 drawAnimal(id,q){if(id==='cow')this.cow(q.x,q.y);else if(id==='sheep')this.sheep(q.x,q.y);else if(id==='bees')this.beehive(q.x,q.y);else smallAnimal(this,q.x,q.y,id)}
 drawObject(o){let p=P(o.x+o.w/2,o.y+o.h/2);if(o.id===this.selected)this.footprint(o,'#f8edb837','#f7f0c3');
  if(o.type==='plot'){this.plot(o);return}
  if(o.type==='road'){drawRoad(this,o);return}
  if(o.type==='duckpond'){this.c.save();this.c.translate(p.x,p.y);this.c.scale(.48,.48);this.pond(0,0);this.c.restore();drawBadge(this,o);if(o.animal_job?.ready_at<=this.now())this.ready(p.x,p.y-30);return;}
  if(specialDecor(this,o,p))return;
  if(['flowerbed','bench','lantern','scarecrow'].includes(o.type)){this.decor(o,p);return}
  const top=drawUpgrade(this,o,drawBuilding(this,o,p));
  let ready=o.jobs?.some(j=>j.ready_at<=this.now())||(o.animal_job&&o.animal_job.ready_at<=this.now());
  const by=Math.max(70,top+6);
  if(ready)this.ready(p.x+22,p.y-by);
  else if(o.jobs?.length||o.animal_job){let job=o.jobs?.[0]||o.animal_job;this.clockBubble(p.x+25,p.y-by-1,job.ready_at)}
 }
 title(o){return {house:'Дом Филиныча',barn:'Склад',plot:'Грядка'}[o.type]||this.catalog?.buildings[o.type]?.name||o.type}
 plotGround(o){this.footprint(o,'#b19a70','#a18a62');this.poly([P(o.x+.06,o.y+.06),P(o.x+.94,o.y+.06),P(o.x+.94,o.y+.94),P(o.x+.06,o.y+.94)],'#937f5d');for(let f of [.25,.48,.71]){let a=P(o.x+.1,o.y+f),b=P(o.x+.9,o.y+f);this.line(a.x,a.y,b.x,b.y,'#b19b73',2.4)}
  if(o.id===this.selected)this.footprint(o,'#f8edb837','#f7f0c3');
  if(!o.crop){let p=P(o.x+.5,o.y+.5);this.line(p.x-3,p.y,p.x+3,p.y,'#d3c49855',1);this.line(p.x,p.y-3,p.x,p.y+3,'#d3c49855',1)}
 }
 plotPlant(o,i,j){const crop=o.crop;if(!crop)return;const nowT=this.now(),f=crop.ready_at<=nowT?1:Math.max(.12,Math.min(.95,1-(crop.ready_at-nowT)/Math.max(1,crop.ready_at-crop.planted_at))),p=P(o.x+.24+i*.45,o.y+.15+j*.3);this.plant(p.x,p.y,crop.id,f,this.time+j*.5+i)}
 plotMarkers(o){const crop=o.crop;if(!crop)return;const ready=crop.ready_at<=this.now();
  let p=P(o.x+.5,o.y+.5);
  if(ready)this.ready(p.x,p.y-32);
  else if(o.id===this.selected)this.clockBubble(p.x,p.y-34,crop.ready_at);
  if(crop.helped){this.ellipse(p.x+24,p.y-5,3,4,'#9ecaca');this.line(p.x+24,p.y-10,p.x+24,p.y-5,'#9ecaca',2)}
 }
 plot(o){this.plotGround(o);if(o.crop)for(let i=0;i<2;i++)for(let j=0;j<3;j++)this.plotPlant(o,i,j);this.plotMarkers(o)}
 plant(x,y,id,f,t){
  // Zoomed far out (whole 20x20 land on a phone) a plant is a few pixels: draw a stem and a head in the crop colour.
  if(this.scale<PLANT_LOD_SCALE){const h=6+f*9;this.line(x,y,x,y-h,'#719856',1.8);if(f>.55)this.ellipse(x,y-h-1,2.6,2.8,f>.8?(this.catalog?.crops?.[id]?.color||'#d9c777'):'#8fb06a');return}
  let sway=this.motion?Math.sin(t*1.2+x)*1.2:0,green='#719856';this.shadow(x,y,4,2);if(f<.6){this.sapling(x,y,id,f,sway);return}
  if(this.plantNew(x,y,id,f,sway))return;
  let h=8+f*13;this.line(x,y,x+sway,y-h,green,1.3);
  if(id==='wheat'){for(let d of [0,1,2]){this.line(x+(d-1)*3,y,x+sway+(d-1)*3,y-h+(d%2)*3,'#a4a966',1);for(let k=0;k<3;k++){this.ellipse(x+sway+(d-1)*3-1,y-h+k*3,2,2.5,f>.72?'#edd088':'#b8c789')}}}
  else if(id==='carrot'){if(f>.7){this.poly([{x:x-3,y:y-4},{x:x+4,y:y-4},{x:x+1,y:y+4}],'#e59b54')}for(let k=-1;k<=1;k++){this.line(x,y-3,x+k*5+sway,y-13,green,2);this.line(x+k*3,y-8,x+k*7,y-9,'#87aa62',2)}}
  else if(id==='corn'){this.ellipse(x-4,y-8,6,2,'#87a864');this.ellipse(x+4,y-12,6,2,green);if(f>.6){this.ellipse(x+2+sway,y-12,3,6,'#e7c960');this.line(x+2,y-18,x+3,y-21,'#b2a570',.7)}}
  else if(id==='pumpkin'){this.ellipse(x-3,y-5,8,3,'#789757');if(f>.65){this.ellipse(x,y-4,7,6,'#d68e45');this.ellipse(x-2,y-4,3,6,'#e5a451');this.line(x,y-10,x+1,y-13,'#6d8750',1.6)}}
  else if(id==='lavender'){for(let k=-1;k<=1;k++){this.line(x,y,x+k*4,y-h+k,'#8ea168',1);this.ellipse(x+k*4,y-h+k,2.3,5,f>.65?'#afa0cc':'#99b07b')}}
  else if(id==='sunflower'){this.ellipse(x-5,y-8,5,2,green);if(f>.6){for(let a=0;a<6;a++)this.ellipse(x+sway+Math.cos(a)*4,y-h+Math.sin(a)*4,3,3,'#e7c364');this.ellipse(x+sway,y-h,3.3,3.3,'#8f764c')}}
  else{this.ellipse(x-3,y-7,6,3,'#87a367');this.ellipse(x+3,y-9,5,4,'#779758');this.ellipse(x+sway,y-12,5,3,'#96b575');if(f>.65){let color={strawberry:'#d47b73',tomato:'#d27a5e',clover:'#c792b0',potato:'#bba37b'}[id]||this.catalog?.crops[id]?.color||'#c792b0';this.ellipse(x-4,y-6,3.3,3.3,color);this.ellipse(x+4,y-9,3,3,color)}}
 }
 leaf(x,y,ang,len,w,color){const c=this.c;c.beginPath();c.ellipse(x+Math.cos(ang)*len/2,y+Math.sin(ang)*len/2,len/2,w,ang,0,Math.PI*2);c.fillStyle=color;c.fill()}
 plantNew(x,y,id,f,sway){
  const ok=f>.8,h=8+f*13,sx=x+sway,L=(px,py,a,l,w,col)=>this.leaf(px,py,a,l,w,col),ST='#6f9a55';
  const late=LATE_CROPS[id];
  if(late){
   const [shape,color]=late,fruit=ok?color:'#a6bc7c';
   if(shape==='tree'){this.line(x,y,sx,y-h*1.15,'#a58d65',2);this.ellipse(sx,y-h,9*f+3,7*f+3,'#8ea975');this.ellipse(sx-3,y-h-3,6*f+2,5*f+2,'#a4ba83');if(f>.6)for(let k=0;k<3;k++)this.ellipse(sx+(k-1)*5,y-h+(k%2)*5,2.5,3,fruit)}
   else if(shape==='berry'){this.line(x,y,sx,y-h,'#a08a67',1.3);for(let k=0;k<5;k++){const bx=sx+(k%2?-5:5),by=y-h*.25-k*h*.15;L(sx,by,k%2?Math.PI+.2:-.2,8,2.6,'#83a66b');if(f>.6){this.ellipse(bx,by+3,2,2,fruit);this.ellipse(bx+2,by+5,1.8,1.8,fruit)}}}
   else if(shape==='grain'){for(let k=-2;k<=2;k++){const bx=sx+k*3,by=y-h*(1-Math.abs(k)*.08);this.line(x+k*2,y,bx,by,'#9ca678',1);for(let j=0;j<4;j++){this.ellipse(bx+(j%2?1:-1),by+j*2.5,id==='millet'?2:1.4,2,fruit);if(id==='barley')this.line(bx,by+j*2,bx+k,by-5+j,'#c2b882',.6)}}}
   else if(shape==='stalk'){for(let k=-2;k<=2;k++){const bx=sx+k*2,by=y-h*(1-Math.abs(k)*.11);this.line(x+k,y,bx,by,'#8aa76c',id==='leek'?2.2:1.5);L(bx,by,Math.PI*1.4,5,1.6,'#a4be81');if(id==='asparagus')this.ellipse(bx,by,1.6,3,fruit)}}
   else if(shape==='pod'){this.line(x,y,sx,y-h,ST,1.1);this.line(x+5,y,x+5,y-h*1.1,'#b4a47d',.8);for(let k=0;k<4;k++){const by=y-h*.2-k*h*.2;L(sx,by,k%2?-.4:Math.PI+.4,6,2.7,'#8eac71');if(f>.6)this.ellipse(sx+(k%2?4:-4),by+2,id==='beans'?2:2.5,id==='beans'?5:3,fruit)}}
   else if(shape==='root'){for(let k=-1;k<=1;k++)L(x,y-3,-Math.PI/2+k*.65,8+f*9,2.5,'#8eae70');if(f>.6){this.ellipse(x,y-1,4.5,3.5,fruit);if(id==='ginger'||id==='ginseng'){this.ellipse(x-5,y+1,3,2.3,fruit);this.ellipse(x+4,y+2,2.5,2,fruit)}else this.line(x,y+2,x+1,y+6,fruit,1)}}
   else{for(let k=-1;k<=1;k++)L(x,y-2,-Math.PI/2+k*.8,8+f*5,3.5,'#7f9f66');if(f>.6){if(id==='broccoli'){for(let k=-1;k<=1;k++)this.ellipse(x+k*3,y-7-Math.abs(k),4,4,fruit)}else if(id==='zucchini')this.ellipse(x+2,y-1,7,2.8,fruit);else for(let k=0;k<3;k++)this.ellipse(x+(k-1)*2,y-5-k,3.5,4,fruit)}}
   return true;
  }
  switch(id){
  case 'beet':for(let k=-1;k<=1;k++){this.line(x+k*2,y-1,sx+k*4,y-h*.8,'#b9607a',1.3);L(sx+k*4,y-h*.8,-Math.PI/2+k*.5,7,2.6,k?'#6f9a5d':'#7fab68')}this.ellipse(x,y-1,3.4,2.6,'#b3566f');return true;
  case 'cucumber':this.line(x,y,x-7,y-1,ST,1);this.line(x,y,x+8,y-1,ST,1);this.ellipse(x-7,y-3,5,2.6,'#6aa05b');this.ellipse(x+8,y-3,5,2.6,'#5f9553');this.ellipse(x,y-6,4,2.4,'#78ab66');this.ellipse(x+2,y,2*(1+f*.6),1.2*(1+f*.5),ok?'#4f8a3f':'#8bb86f');this.ellipse(x-4,y-2,1.8,3,ok?'#4f8a3f':'#8bb86f');return true;
  case 'peas':this.line(x,y,sx,y-h*1.2,'#7fae62',1.2);this.line(x+5,y+1,x+5,y-h*1.3,'#a68b60',.9);for(let k=0;k<4;k++)L(sx,y-h*(.3+k*.22),k%2?-.4:Math.PI+.4,5,1.7,'#8dbb70');for(let k=0;k<3;k++)this.ellipse(sx+(k%2?4:-4),y-h*(.4+k*.2),3,1.2,ok?'#6fa856':'#a6cf84');return true;
  case 'flax':for(let k=-2;k<=2;k++){let tx=sx+k*2.6,ty=y-h*(1.1-Math.abs(k)*.08);this.line(x+k*1.5,y,tx,ty,'#86a981',.9);if(f>.7)this.ellipse(tx,ty,2,2,'#a3bdd8')}return true;
  case 'rice':for(let k=-3;k<=3;k++){let tx=sx+k*2.2,ty=y-h*(1-Math.abs(k)*.06);this.line(x+k*1.2,y,tx,ty,'#9cc27a',1);if(f>.7)this.ellipse(tx+1,ty+2,1.2,3,ok?'#e6dfa6':'#c2d98f')}this.line(x-7,y,x+7,y,'#b9d3d9',1);return true;
  case 'oat':for(let k=-2;k<=2;k++){let tx=sx+k*3,ty=y-h*(1-Math.abs(k)*.08);this.line(x+k*1.5,y,tx,ty,'#9cab72',1);for(let j=0;j<3;j++)this.ellipse(tx+(j%2?1.4:-1.4),ty+j*2.6,1.1,2.1,ok?'#cdb86f':'#b5c58a')}return true;
  case 'rye':for(let k=-2;k<=2;k++){let tx=sx+k*2.8,ty=y-h*1.15*(1-Math.abs(k)*.05);this.line(x+k*1.4,y,tx,ty,'#9aa886',1);this.ellipse(tx,ty,1.2,4,ok?'#c2ae7a':'#a9b98a');this.line(tx,ty-3,tx,ty-7,ok?'#d6c690':'#b9c79a',.7)}return true;
  case 'raspberry':this.line(x,y,sx,y-h*1.2,'#9a8461',1.4);for(let k=0;k<4;k++)L(sx,y-h*(.3+k*.22),k%2?-.3:Math.PI+.3,6,2,'#7ba35e');for(let k=0;k<4;k++)this.ellipse(sx+(k%2?4.5:-4.5),y-h*(.3+k*.2)+2,2.1,2.1,ok?'#c96785':'#d9a0b0');return true;
  case 'blueberry':this.line(x,y,sx,y-h,'#9a8461',1.4);this.line(x,y,sx-5,y-h*.8,'#9a8461',1.1);this.line(x,y,sx+5,y-h*.8,'#9a8461',1.1);for(let k=0;k<5;k++)L(sx+(k-2)*3,y-h*(.6+(k%2)*.3),k%2?-.5:Math.PI+.5,5,2,'#6f9a5d');for(let k=0;k<5;k++)this.ellipse(sx+(k-2)*3.2,y-h*(.35+(k%2)*.2),2,2,ok?'#6f79b0':'#9aa0c8');return true;
  case 'basil':this.line(x,y,x,y-h*.9,'#6e9a5c',1.3);for(let k=0;k<4;k++){let yy=y-1-k*h*.24;L(x,yy,-.5,6,2.6,'#79b06d');L(x,yy,Math.PI+.5,6,2.6,'#6ca566')}L(x,y-h*.9,-Math.PI/2,5,2,'#8cc27c');return true;
  case 'cabbage':this.ellipse(x-4,y-3,6,2.8,'#8fb575');this.ellipse(x+4,y-3,6,2.8,'#8fb575');this.ellipse(x,y-5,4+f*3,3+f*2.4,'#a9c68b');this.ellipse(x-1,y-7,3+f*2.4,2.4+f*2,'#bcd69f');this.ellipse(x+1,y-8,2+f*2,1.8+f*1.4,'#d0e4b4');return true;
  case 'watermelon':this.line(x,y,x-7,y-1,'#4f8c60',1.1);this.line(x,y,x+8,y-1,'#4f8c60',1.1);this.ellipse(x-7,y-3,5,2.6,'#5a9a66');this.ellipse(x+8,y-3,5,2.6,'#5a9a66');this.ellipse(x,y-6,4,2.4,'#5a9a66');this.ellipse(x+1,y-1,4.5+f*2,3.6+f*1.4,ok?'#4f8c60':'#7bb083');if(ok){this.line(x-3,y-3,x+4,y+1,'#2f6a45',1);this.line(x-1,y-4,x+6,y,'#2f6a45',.8)}return true;
  case 'pepper':this.line(x,y,sx,y-h,ST,1.3);for(let k=0;k<4;k++)L(sx,y-h*(.3+k*.2),k%2?-.5:Math.PI+.5,6,2.2,k%2?'#5f9550':'#6fa05a');for(let k=-1;k<=1;k+=2){this.line(sx,y-h*.7,sx+k*5,y-h*.55,ST,.8);this.ellipse(sx+k*5,y-h*.55+3,2.2,3.6,ok?'#d9553f':'#8fb061')}return true;
  case 'eggplant':this.line(x,y,sx,y-h,'#6f8a5a',1.4);for(let k=0;k<3;k++)L(sx,y-h*(.4+k*.25),k%2?-.4:Math.PI+.4,7,2.8,'#6a9a5e');for(let k=-1;k<=1;k+=2)this.ellipse(sx+k*4,y-h*.35+2,2.8,4.2,ok?'#5f4a80':'#7d6aa0');return true;
  case 'buckwheat':for(let k=-1;k<=1;k++){this.line(x+k*2,y,sx+k*3,y-h,'#86a97a',1);L(sx+k*3,y-h*.55,-Math.PI/2+k*.8,5,1.6,'#8cb27f');this.ellipse(sx+k*3,y-h,2.4,2.6,ok?'#a58f6e':'#f0cdd3');this.ellipse(sx+k*3,y-h+3,2,2,ok?'#8f7a5a':'#f4dde1')}return true;
  case 'mint':for(let k=-3;k<=3;k++)L(x,y-1,-Math.PI/2+k*.5,6+f*3,2.3,k%2?'#5fae8f':'#74be9f');this.line(x,y,x,y-h*.8,'#4f8f6f',1);return true;
  case 'grape':this.line(x+5,y+1,x+5,y-h*1.4,'#a68b60',1.5);this.line(x-5,y+1,x-5,y-h*1.4,'#a68b60',1.5);this.line(x-5,y-h*1.2,x+5,y-h*1.2,'#a68b60',1);for(let k=0;k<4;k++)L(x+(k-1.5)*3.4,y-h*1.05,k%2?.3:Math.PI-.3,5,2.4,'#79a85f');for(let k=-1;k<=1;k+=2)for(let j=0;j<3;j++)this.ellipse(x+k*3+(j%2)*1.6,y-h*.9+j*2.8,1.9,1.9,ok?'#7b5f9a':'#9bc27a');return true;
  case 'chamomile':for(let k=-1;k<=1;k++){let hx=sx+k*5,hy=y-h*(.95-Math.abs(k)*.15);this.line(x,y,hx,hy,'#86b078',1);for(let a=0;a<6;a++)this.ellipse(hx+Math.cos(a)*3,hy+Math.sin(a)*3,1.9,1.5,'#f6f2e2');this.ellipse(hx,hy,1.8,1.8,'#e9bf48')}return true;
  case 'hops':this.line(x+2,y+1,x+2,y-h*1.6,'#a68b60',1.6);this.line(x,y,sx+2,y-h*1.4,'#8cb066',1);for(let k=0;k<4;k++)L(sx+2,y-h*(.5+k*.25),k%2?-.3:Math.PI+.3,5,2.4,'#7ea657');for(let k=0;k<3;k++){this.ellipse(sx+(k%2?5:-2),y-h*(.55+k*.28)+3,1.8,3,ok?'#a8c76a':'#8fb868')}return true;
  case 'garlic':for(let k=-3;k<=3;k++)this.line(x,y-1,sx+k*2.6,y-h*(1-Math.abs(k)*.1),'#8cb77a',1.4);this.ellipse(x,y,3.4,2.4,'#eee8d8');this.ellipse(x,y+.5,3.2,1.6,'#d8cfb9');return true;
  case 'poppy':for(let k=-1;k<=1;k++){let hx=sx+k*4.5,hy=y-h*(.95-Math.abs(k)*.1);this.line(x,y,hx,hy,'#7aa070',1);if(ok){for(let a=0;a<4;a++)this.ellipse(hx+Math.cos(a*1.57)*2.4,hy+Math.sin(a*1.57)*2.4,2.6,2.6,'#c4506b');this.ellipse(hx,hy,1.6,1.6,'#463a4a')}else{this.ellipse(hx,hy,2.2,2.8,'#9bb88a');this.ellipse(hx,hy-3,1.4,1.4,'#c4506b')}}L(x,y-3,-Math.PI/2-.9,6,1.6,'#8aaf86');L(x,y-3,-Math.PI/2+.9,6,1.6,'#8aaf86');return true;
  case 'melon':this.line(x,y,x-7,y-1,'#6f9a55',1.1);this.line(x,y,x+8,y-1,'#6f9a55',1.1);this.ellipse(x-7,y-3,5,2.6,'#78a859');this.ellipse(x+8,y-3,5,2.6,'#78a859');this.ellipse(x,y-6,4,2.4,'#78a859');this.ellipse(x+1,y-1,4+f*2,3.4+f*1.4,ok?'#e4c26b':'#b3c98a');this.line(x-2,y-3,x+4,y+1,ok?'#c9a54e':'#9fb778',.7);return true;
  case 'cranberry':for(let k=-3;k<=3;k++)L(x,y-1,-Math.PI/2+k*.55,5,1.4,'#5d8f58');for(let k=0;k<5;k++)this.ellipse(x+(k-2)*3,y-3-(k%2)*3,1.7,1.7,ok?'#b83f4f':'#d9a0a6');return true;
  case 'saffron':for(let k=-3;k<=3;k++)this.line(x,y,sx+k*2.6,y-h*(.8-Math.abs(k)*.08),'#88b27a',.9);for(let k=-1;k<=1;k++){let hx=sx+k*4.5,hy=y-h*.7;this.poly([{x:hx-3,y:hy},{x:hx+3,y:hy},{x:hx+2,y:hy-5},{x:hx,y:hy-8},{x:hx-2,y:hy-5}],ok?'#9a62b5':'#b9a0c9');if(ok)this.line(hx,hy-3,hx+1,hy-7,'#d9553f',1)}return true;
  }
  return false;
 }
 sapling(x,y,id,f,sway){
  const g=Math.min(1,f/.6),h=3+g*10,L=(a,l,w,col)=>this.leaf(x+sway*.5,y-(a[1]),a[0],l,w,col),up=-Math.PI/2,top=y-h,sx=x+sway;
  const grass=(n,col,col2,tall)=>{for(let k=0;k<n;k++){let d=(k-(n-1)/2),hh=h*(tall||1)*(1-Math.abs(d)*.12);this.line(x+d*2,y,sx+d*3.2,y-hh,k%2?col2:col,1.2)}};
  const fruit=(col,n)=>{if(f>.42)for(let k=0;k<n;k++)this.ellipse(x+(k-(n-1)/2)*4,y-4-k%2*3,1.6+(f-.42)*5,1.6+(f-.42)*5,col)};
  const G='#719856',G2='#8daf66',G3='#5f8a4e';
  switch(id){
  case 'wheat':grass(3,'#8fb06a','#a4b672',1);if(f>.45)this.ellipse(sx,top,1.2,2.4,'#d9c777');break;
  case 'oat':grass(4,'#8cae7e','#a2bd8a',.95);if(f>.45){this.ellipse(sx-2,top+1,1,2,'#cdb86f');this.ellipse(sx+2,top,1,2,'#cdb86f')}break;
  case 'rye':grass(3,'#8aa08c','#9db39a',1.3);if(f>.45)this.ellipse(sx,top,1,3,'#c2ae7a');break;
  case 'rice':grass(5,'#a5cf84','#b8dc98',.9);this.line(x-4,y,x+4,y,'#b9d3d9',1);break;
  case 'flax':for(let k=-1;k<=1;k++)this.line(x+k*2,y,sx+k*2.6,y-h*1.15,'#86a981',.9);if(f>.45)this.ellipse(sx,top-h*.15,1.8,1.8,'#a3bdd8');break;
  case 'carrot':for(let k=-2;k<=2;k++){this.line(x,y-1,sx+k*2.4,y-h*(.9-Math.abs(k)*.1),'#7fae62',.9);this.ellipse(sx+k*2.4,y-h*(.9-Math.abs(k)*.1),1.2+g,1.2+g,'#8fbc6b')}if(f>.4)this.poly([{x:x-2,y:y-1},{x:x+2,y:y-1},{x:x,y:y+2.5}],'#e59b54');break;
  case 'beet':for(let k=-1;k<=1;k++){this.line(x,y,x+k*3.5,y-h*.7,'#b9607a',1.1);this.leaf(x+k*3.5,y-h*.7,up+k*.5,3+g*5,2+g*1.2,k?'#6f9a5d':'#7fab68')}if(f>.4)this.ellipse(x,y-1,2.6,2,'#b3566f');break;
  case 'cabbage':this.ellipse(x,y-2,3+g*5,2+g*2.5,'#a9c68b');this.ellipse(x-1,y-3-g*2,2+g*3,1.5+g*2,'#bcd69f');this.ellipse(x+1,y-4-g*2,1+g*2,1+g*1.5,'#cde2b0');break;
  case 'peas':this.line(x,y,sx,y-h*1.1,'#7fae62',1);this.leaf(sx,y-h*.5,-.4,3+g*3,1.3,'#8dbb70');this.leaf(sx,y-h*.8,Math.PI+.4,3+g*3,1.3,'#8dbb70');this.line(sx,y-h*1.1,sx+3,y-h*1.35,'#a5cf84',.7);if(f>.42)this.ellipse(sx+2,y-h*.35,3,1.2,'#88b86c');break;
  case 'cucumber':this.line(x,y,x-4,y-1,'#6f9a5d',.9);this.line(x,y,x+5,y-2,'#6f9a5d',.9);this.ellipse(x-5,y-2,3+g*2,2+g*1.2,'#6aa05b');this.ellipse(x+6,y-3,3+g*2,2+g*1.2,'#5f9553');this.ellipse(x,y-4-g*3,2.4+g*2,2+g,'#78ab66');if(f>.42)this.ellipse(x+2,y,3,1.4,'#6f9a5a');break;
  case 'watermelon':case 'pumpkin':{let col=id==='pumpkin'?'#7aa053':'#4f8c60';this.line(x,y,x-5,y-1,col,1);this.line(x,y,x+6,y-1,col,1);this.ellipse(x-5,y-3,3+g*2.4,2+g*1.4,col);this.ellipse(x+6,y-3,3+g*2.4,2+g*1.4,col);this.ellipse(x,y-5-g*2,2.6+g*2,2+g,col);if(f>.42)this.ellipse(x+1,y-1,1.8+(f-.42)*8,1.6+(f-.42)*7,id==='pumpkin'?'#d9a065':'#7bb083');break}
  case 'corn':for(let k=-1;k<=1;k+=2)this.leaf(x,y-h*.35,up+k*(.9-g*.3),4+g*8,1.2+g*.5,k<0?'#86ad62':'#76a158');this.line(x,y,sx,top,'#8cb066',1.5);this.leaf(sx,top,up+.15,3+g*4,1.1,'#92b86c');break;
  case 'clover':for(let k=0;k<3;k++){let a=up+(k-1)*.9,px=x+Math.cos(a)*(3+g*3),py=y-3-g*2+Math.sin(a)*(3+g*3);this.line(x,y,px,py,'#85aa66',.8);this.ellipse(px,py,2+g*1.3,2+g*1.3,'#8cb86c')}if(f>.42)this.ellipse(x,y-7-g*2,2,2,'#cfa0c3');break;
  case 'strawberry':for(let k=-1;k<=1;k++){this.line(x,y,x+k*4,y-3-g*2,'#7fa062',.8);this.ellipse(x+k*4,y-4-g*2,2.2+g*1.5,1.8+g,'#73a05a')}fruit('#e6827b',2);if(f>.3)this.ellipse(x+3,y-6,1.2,1.2,'#f5efe8');break;
  case 'raspberry':case 'blueberry':{let col=id==='raspberry'?'#d27792':'#8f98c4';this.line(x,y,sx,y-h*1.2,'#9a8461',1.3);for(let k=0;k<3;k++){let yy=y-h*(.35+k*.3);this.leaf(sx,yy,k%2?-.3:Math.PI+.3,3+g*2,1.2,'#7ba35e')}fruit(col,2);break}
  case 'basil':for(let k=0;k<3;k++){let yy=y-1-k*h*.28,s=3+g*1.5-k*.4;this.leaf(x,yy,-.5,s,1.7,'#79b06d');this.leaf(x,yy,Math.PI+.5,s,1.7,'#6ca566')}this.line(x,y,x,y-h*.8,'#6e9a5c',.9);break;
  case 'lavender':for(let k=-2;k<=2;k++)this.line(x,y,x+k*2.2,y-h*(1-Math.abs(k)*.1),'#8fa88a',.8);if(f>.42){for(let k=-1;k<=1;k++)this.ellipse(x+k*3,y-h*.95,1,2.4,'#a898cc')}break;
  case 'sunflower':this.line(x,y,sx,y-h*1.15,'#72a057',1.6);this.leaf(sx,y-h*.45,Math.PI+.35,3+g*5,1.7+g,'#7fb066');this.leaf(sx,y-h*.45,-.35,3+g*5,1.7+g,'#6fa25d');if(f>.42)this.ellipse(sx,y-h*1.2,2.3,2.3,'#e6c35e');break;
  case 'tomato':this.line(x+3,y+1,x+3,y-h*1.3,'#b69a6b',.8);this.line(x,y,sx,y-h,'#6f9a55',1.1);for(let k=0;k<3;k++){this.leaf(sx,y-h*(.35+k*.28),k%2?-.4:Math.PI+.4,3.5+g*2,1.2,'#6f9d5b')}fruit('#df7a62',2);break;
  case 'potato':for(let k=-2;k<=2;k++){this.leaf(x,y-1,up+k*.55,3+g*5-Math.abs(k),1.5+g*.6,Math.abs(k)%2?'#6b9154':'#5f8a4e')}if(f>.42)this.ellipse(x+3,y,2,1.4,'#c9a87a');break;
  case 'pepper':this.line(x,y,sx,y-h,'#6f9a55',1.1);for(let k=0;k<3;k++)this.leaf(sx,y-h*(.4+k*.25),k%2?-.5:Math.PI+.5,3+g*2,1.3,'#6fa05a');if(f>.42)this.ellipse(sx+2,y-h*.35,1.3,2.2,'#7fb061');break;
  case 'eggplant':this.line(x,y,sx,y-h,'#7a6a8c',1.2);for(let k=0;k<3;k++)this.leaf(sx,y-h*(.35+k*.25),k%2?-.4:Math.PI+.4,4+g*3,1.7,'#6f9a62');if(f>.42)this.ellipse(sx+3,y-h*.4,1.4,1.4,'#8a73b0');break;
  case 'buckwheat':for(let k=-1;k<=1;k++){this.line(x+k*2,y,sx+k*3,y-h*(1-Math.abs(k)*.15),'#86a97a',.9);this.leaf(sx+k*3,y-h*.8,up+k*.9,3+g,1.4,'#8cb27f')}if(f>.45)this.ellipse(sx,top-1,1.6,1.6,'#f0cdd3');break;
  case 'mint':for(let k=-2;k<=2;k++)this.leaf(x,y-1,up+k*.6,3+g*3,1.6+g*.6,k%2?'#5fae8f':'#74be9f');break;
  case 'grape':this.line(x+4,y+1,x+4,y-h*1.4,'#a68b60',1);this.line(x,y,sx,y-h,'#7a9a58',1);this.leaf(sx,y-h*.7,Math.PI+.3,3+g*3,1.7,'#79a85f');this.leaf(sx,y-h,-.3,3+g*3,1.7,'#6f9a55');if(f>.42)this.ellipse(sx-1,y-h*.35,1.6,1.6,'#7b5f9a');break;
  case 'chamomile':for(let k=-1;k<=1;k++){this.line(x,y,x+k*3,y-h*.6,'#86b078',.8);this.leaf(x+k*3,y-h*.6,up+k*.7,2.5+g*2.5,.9,'#8cba7c')}if(f>.45){this.ellipse(sx,top-1,1.8,1.8,'#f6f2e2');this.ellipse(sx,top-1,.8,.8,'#e9bf48')}break;
  case 'hops':this.line(x+3,y+1,x+3,y-h*1.5,'#a68b60',1);this.line(x,y,sx+2,y-h*1.2,'#8cb066',1);this.leaf(sx+2,y-h*.7,-.2,3+g*2,1.5,'#8fba62');this.leaf(sx,y-h,Math.PI+.3,3+g*2,1.5,'#7ea657');break;
  case 'garlic':for(let k=-2;k<=2;k++)this.line(x,y,sx+k*2.4,y-h*(1-Math.abs(k)*.15),'#9fbf8b',1);if(f>.42)this.ellipse(x,y,2.2,1.4,'#eee8d8');break;
  case 'poppy':for(let k=-2;k<=2;k++)this.leaf(x,y-1,up+k*.65,3+g*3,1.2,'#8aaf86');if(f>.45)this.ellipse(sx,top-2,1.6,1.6,'#c4506b');break;
  case 'melon':this.line(x,y,x-5,y-1,'#6f9a55',1);this.line(x,y,x+6,y-1,'#6f9a55',1);this.ellipse(x-5,y-3,3+g*2.4,2+g*1.4,'#78a859');this.ellipse(x+6,y-3,3+g*2.4,2+g*1.4,'#78a859');this.ellipse(x,y-5-g*2,2.6+g*2,2+g,'#78a859');if(f>.42)this.ellipse(x+1,y-1,1.8+(f-.42)*8,1.6+(f-.42)*7,'#e4c26b');break;
  case 'cranberry':for(let k=-2;k<=2;k++)this.leaf(x,y-1,up+k*.7,2.5+g*2.5,1,'#5d8f58');if(f>.42){this.ellipse(x-2,y-2,1.3,1.3,'#d65a68');this.ellipse(x+3,y-3,1.3,1.3,'#d65a68')}break;
  case 'saffron':for(let k=-2;k<=2;k++)this.line(x,y,sx+k*2.4,y-h*(1-Math.abs(k)*.12),'#88b27a',.7);if(f>.45)this.poly([{x:sx-2,y:top},{x:sx+2,y:top},{x:sx,y:top-4}],'#a778c2');break;
  default:this.line(x,y,sx,top,G,1.2);this.leaf(sx,top+2,up-.7,3+g*2,1.3,G2);this.leaf(sx,top+2,up+.7,3+g*2,1.3,G3);
  }
 }
 ready(x,y){if(this.lightMarkers){this.lightMarkers.push({kind:'ready',x,y});return}const dark=(this.lighting?.darkness||0)>.25;this.ellipse(x,y,7,7,dark?'#d9bf7a':'#f8ebba');this.line(x-3,y,x-1,y+2,dark?'#29352f':'#a1864c',1.5);this.line(x-1,y+2,x+3,y-3,dark?'#29352f':'#a1864c',1.5)}
 clockBubble(x,y,at){let sec=Math.max(0,Math.ceil(at-this.now())),text=sec>=3600?Math.ceil(sec/3600)+' ч':sec>=60?Math.ceil(sec/60)+' м':sec+' с';this.label(x,y,text)}
 chicken(x,y){this.shadow(x,y,7,3);this.line(x-3,y,x-3,y+4,'#c39b59',1);this.line(x+3,y,x+3,y+4,'#c39b59',1);this.ellipse(x,y-4,7,5,'#f2edcf');this.ellipse(x+5,y-9,3.5,4,'#f7f1d8');this.ellipse(x+6,y-13,2,2,'#bb7561');this.ellipse(x+6,y-10,1,1,'#435444');this.poly([{x:x+8,y:y-10},{x:x+12,y:y-8},{x:x+8,y:y-7}],'#d4a55e');this.poly([{x:x-5,y:y-5},{x:x-10,y:y-12},{x:x-9,y:y-3}],'#e5dbb9')}
 cow(x,y){this.shadow(x,y,17,6);for(let dx of [-10,-5,8,12])this.line(x+dx,y-5,x+dx,y+6,'#9e947a',3);this.ellipse(x,y-12,18,10,'#e8dfc6');this.ellipse(x-4,y-14,6,7,'#8c8778');this.ellipse(x+13,y-11,8,9,'#eee5cd');this.ellipse(x+18,y-6,7,4,'#d6b7a3');this.ellipse(x+15,y-13,1.2,1.2,'#455441');this.line(x+10,y-19,x+7,y-23,'#ab9f7f',2);this.line(x+16,y-20,x+19,y-24,'#ab9f7f',2)}
 sheep(x,y){this.shadow(x,y,13,5);this.line(x-7,y-1,x-7,y+5,'#8b8370',2);this.line(x+8,y-1,x+8,y+5,'#8b8370',2);for(let i=0;i<5;i++)this.ellipse(x-8+i*4,y-8+(i%2)*2,6,7,'#eae4d1');this.ellipse(x+13,y-7,5,6,'#9b9684');this.ellipse(x+14,y-9,1,1,'#394c3d')}
 beehive(x,y){this.ellipse(x,y-8,12,8,'#d8bc76');this.ellipse(x,y-15,10,8,'#e0c886');this.ellipse(x,y-21,7,5,'#e5d19a');this.ellipse(x+4,y-6,3,3,'#8f794f');for(let i=0;i<2;i++){let bx=x+Math.sin(this.time+i*3)*17,by=y-25+Math.cos(this.time*1.3+i)*6;this.ellipse(bx,by,2,1.3,'#9b885a')}}
 goose(x,y,t,pose=null){
  const run=pose==='run',hiss=pose==='hiss',bob=Math.sin(t*(run?14:4))*(run?1.6:1),c=this.c,lean=run?3:0;
  this.shadow(x,y,13,5);
  const sw=Math.sin(t*(run?16:5))*(run?3.2:2);
  this.line(x-4,y-1,x-5+sw,y+5,'#cea260',2);this.line(x+3,y-1,x+4-sw,y+5,'#cea260',2);
  if(hiss){ // wings out, neck low and forward, beak open
   for(const k of [-1,1])this.poly([{x:x-2,y:y-8},{x:x-17,y:y-9-k*7},{x:x-13,y:y-3},{x:x-4,y:y-2}],'#f4f4e6','#d7d7c4',.8);
   this.ellipse(x,y-6,13,7,'#ececdb');
   this.line(x+9,y-8,x+19,y-15,'#f2f2e3',6);this.ellipse(x+21,y-16,5,4,'#f2f2e3');
   this.poly([{x:x+25,y:y-19},{x:x+31,y:y-20},{x:x+25,y:y-17}],'#d8aa63');this.poly([{x:x+25,y:y-15},{x:x+31,y:y-13},{x:x+25,y:y-17}],'#c9964f');
   this.ellipse(x+22,y-17,1,1,'#405844');
   return;
  }
  this.ellipse(x+lean*.4,y-6+bob,13,7,'#ececdb');
  if(run)this.poly([{x:x-3,y:y-8+bob},{x:x-15,y:y-12+bob},{x:x-9,y:y-3+bob}],'#f4f4e6');
  this.line(x+9+lean,y-8+bob,x+10+lean*2.6,y-23+bob+(run?5:0),'#f2f2e3',6);this.ellipse(x+11+lean*2.6,y-25+bob+(run?5:0),5,4,'#f2f2e3');
  const hx=x+lean*2.6,hy=bob+(run?5:0);
  c.beginPath();c.moveTo(hx+15,y-26+hy);c.quadraticCurveTo(hx+18,y-26+hy,hx+22,y-23+hy);c.quadraticCurveTo(hx+19,y-22+hy,hx+15,y-22+hy);c.quadraticCurveTo(hx+16,y-24+hy,hx+15,y-26+hy);c.fillStyle='#d8aa63';c.fill();
  this.ellipse(hx+13,y-26+hy,1,1,'#405844');
 }
 potted(x,y){this.poly([{x:x-4,y:y-6},{x:x+4,y:y-6},{x:x+3,y:y+2},{x:x-3,y:y+2}],'#b59169');this.ellipse(x,y-8,6,5,'#8aa270');this.ellipse(x-2,y-10,2,2,'#d3b0a4')}
 decor(o,p){this.shadow(p.x,p.y,15,6);if(o.type==='flowerbed'){this.ellipse(p.x,p.y,18,8,'#a5b784');for(let i=0;i<7;i++){let x=p.x+(seed(i,o.x)-.5)*27,y=p.y-3+(seed(i+10,o.y)-.5)*8;this.line(x,y,x,y-8,'#85a669',1);this.ellipse(x,y-10,3.5,3,'#c491a1');this.ellipse(x,y-10,1.5,1.5,'#ecdaa1')}}else if(o.type==='bench'){for(let d of [-11,11])this.line(p.x+d,p.y-2,p.x+d,p.y+6,'#8b7756',2);this.poly([{x:p.x-16,y:p.y-7},{x:p.x+9,y:p.y+5},{x:p.x+18,y:p.y},{x:p.x-8,y:p.y-12}],'#c6a977');this.line(p.x-14,p.y-15,p.x+13,p.y-2,'#ac8e61',6)}else if(o.type==='lantern'){this.line(p.x,p.y,p.x,p.y-39,'#83927a',3);this.poly([{x:p.x-7,y:p.y-49},{x:p.x+7,y:p.y-49},{x:p.x+5,y:p.y-35},{x:p.x-5,y:p.y-35}],'#ead7a0','#8f9276',1.4);this.poly([{x:p.x-9,y:p.y-49},{x:p.x,y:p.y-57},{x:p.x+9,y:p.y-49}],'#83927a')}else{this.line(p.x,p.y,p.x,p.y-37,'#a28b60',3);this.line(p.x-16,p.y-25,p.x+16,p.y-25,'#a28b60',3);this.poly([{x:p.x-10,y:p.y-28},{x:p.x+9,y:p.y-28},{x:p.x+7,y:p.y-11},{x:p.x-9,y:p.y-11}],'#b6926c');this.ellipse(p.x,p.y-36,7,8,'#d5bd8c');this.ellipse(p.x,p.y-41,12,3,'#bc9f65');this.ellipse(p.x,p.y-45,7,6,'#d0b078')}}
}
function shade(hex,f){let n=parseInt(hex.slice(1),16),r=n>>16,g=n>>8&255,b=n&255;return `rgb(${Math.round(r*(1+f))},${Math.round(g*(1+f))},${Math.round(b*(1+f))})`}
