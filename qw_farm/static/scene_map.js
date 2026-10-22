/* Farm map helpers: view geometry, culling bounds, object categories, mini-map.
   Pure functions first (unit-tested in tests/js/farm_map.test.cjs), then the DOM mini-map.
   Nothing here can change goods, timestamps or balances: it only reads the farm snapshot. */
export const TW=36,TH=18;
export const iso=(x,y,z=0)=>({x:(x-y)*TW,y:(x+y)*TH-z});
export const CATEGORIES=[['plots','Грядки','#a9885b'],['animals','Животные','#e0a23f'],['workshops','Мастерские','#5f8fb8'],['decor','Декор','#86b363'],['other','Дом и склад','#b5675b']];
export const CATEGORY_COLOR=Object.fromEntries(CATEGORIES.map(([id,,color])=>[id,color]));

/** Visible rectangle in world (isometric pixel) coordinates; `margin` is in screen pixels. */
export function viewRect(w,h,origin,scale,margin=0){
 return {x0:(-margin-origin.x)/scale,y0:(-margin-origin.y)/scale,x1:(w+margin-origin.x)/scale,y1:(h+margin-origin.y)/scale};
}
export function overlaps(a,b){return a.x0<b.x1&&a.x1>b.x0&&a.y0<b.y1&&a.y1>b.y0;}
/** Generous world bounding box of everything an object may paint (sprite, roof, bubbles, label, animals). */
export function objectBounds(o){
 const cx=((o.x+o.w/2)-(o.y+o.h/2))*TW,cy=((o.x+o.w/2)+(o.y+o.h/2))*TH;
 if(o.type==='road')return {x0:cx-38,x1:cx+38,y0:cy-20,y1:cy+20};
 if(o.type==='plot')return {x0:cx-46,x1:cx+46,y0:cy-66,y1:cy+28};
 const half=(o.w+o.h)*TW/2+34;
 return {x0:cx-half,x1:cx+half,y0:cy-200,y1:cy+(o.w+o.h)*TH/2+56};
}
/* ---- depth order (painter's algorithm) ----
   The viewer looks from the +x/+y corner, so a thing with a larger x+y is nearer. An object is a footprint rectangle
   {x,y,w,h} (a sprite standing on one point has w=h=0). A is behind B when A lies entirely on the low-x side of B or on
   the low-y side of B; that is exact for rectangles of different sizes, which a single x+y key is not (a 3x3 barn and a
   1x1 bed beside it get the wrong order from a corner-sum key). Pairs the rule cannot separate fall back to the key of
   the front-bottom corner, then to the input order, so the result is stable. */
/** x+y of the front-bottom corner of the footprint. */
export function depthKey(o){return (o.x+(o.w||0))+(o.y+(o.h||0));}
/** -1: a must be drawn before b, 1: after b, 0: the footprints do not decide it. */
export function depthSeparation(a,b){
 const aw=a.w||0,ah=a.h||0,bw=b.w||0,bh=b.h||0;
 const ab=a.x+aw<=b.x||a.y+ah<=b.y,ba=b.x+bw<=a.x||b.y+bh<=a.y;
 return ab&&!ba?-1:ba&&!ab?1:0;
}
/** -1 or 1 (0 only for identical footprints): footprint separation, else corner key, else front edge, else x. */
export function compareDepth(a,b){
 const s=depthSeparation(a,b);if(s)return s;
 const k=depthKey(a)-depthKey(b);if(k)return k<0?-1:1;
 const f=(a.y+(a.h||0))-(b.y+(b.h||0));if(f)return f<0?-1:1;
 const g=a.x-b.x;return g?(g<0?-1:1):0;
}
/** Back-to-front copy of `items` (a topological sort of depthSeparation; ties by corner key then input order). */
export function sortByDepth(items){
 const n=items.length,keys=items.map(depthKey),after=Array.from({length:n},()=>[]),need=new Array(n).fill(0);
 for(let i=0;i<n;i++)for(let j=i+1;j<n;j++){
  const s=depthSeparation(items[i],items[j]);
  if(s<0){after[i].push(j);need[j]++;}else if(s>0){after[j].push(i);need[i]++;}
 }
 const better=(a,b)=>keys[a]-keys[b]||(items[a].y+(items[a].h||0))-(items[b].y+(items[b].h||0))||a-b;
 const done=new Array(n).fill(false),ready=[],out=[];
 for(let i=0;i<n;i++)if(!need[i])ready.push(i);
 while(out.length<n){
  let pick=-1,at=-1;
  for(let r=0;r<ready.length;r++)if(pick<0||better(ready[r],pick)<0){pick=ready[r];at=r;}
  if(pick<0){ // cannot happen for disjoint rectangles; stay safe on bad data
   for(let i=0;i<n;i++)if(!done[i]&&(pick<0||better(i,pick)<0))pick=i;
  }else ready.splice(at,1);
  done[pick]=true;out.push(items[pick]);
  for(const j of after[pick])if(!done[j]&&--need[j]===0)ready.push(j);
 }
 return out;
}
/** Where moving sprites (a point each) go in an already sorted list: slots[i] = sprites painted just before list[i],
    slots[list.length] = after the last. A sprite goes after everything that must come before it and before the
    first thing in front of it; sprites in one slot keep depth order. A parentId keeps an attached sprite
    (an animal standing within its house footprint) after that house while retaining its own ground anchor. */
export function spriteSlots(list,sprites){
 const slots=Array.from({length:list.length+1},()=>[]);
 for(const sp of [...sprites].sort(compareDepth)){
  let lower=0,upper=list.length;
  for(let i=0;i<list.length;i++){
   if(sp.parentId!==undefined&&list[i].id===sp.parentId){lower=Math.max(lower,i+1);continue}
   const hard=depthSeparation(list[i],sp);
   if(hard<0)lower=Math.max(lower,i+1);else if(hard>0)upper=Math.min(upper,i);
  }
  // Corner-key ties are only preferences: a diagonal solid must not pull a sprite behind a building
  // that its footprint puts behind the sprite. Conflicting constraints can occur in malformed or
  // attached-sprite orders; keep all required predecessors (including the parent) in that case.
  let at=lower>upper?lower:upper;
  if(lower<=upper)for(let i=lower;i<upper;i++)if(compareDepth(list[i],sp)>0){at=i;break}
  slots[at].push(sp);
 }
 return slots;
}
/** Inverse of iso(): cell coordinates of a world (isometric pixel) point. */
export const isoInverse=(px,py)=>({x:(px/TW+py/TH)/2,y:(py/TH-px/TW)/2});

/* ---- toasts: short, quiet, identical ones merge ---- */
export const TOAST_MS=2600,TOAST_ERROR_MS=6500,TOAST_MAX=3;
let toastSeq=0;
/** Adds (or refreshes) a toast in `list`; returns it. Same text and kind -> counter, not a new line. */
export function pushToast(list,text,error=false,now=0){
 const ms=error?TOAST_ERROR_MS:TOAST_MS,hit=list.find(t=>t.text===text&&t.error===!!error);
 if(hit){hit.count++;hit.until=now+ms;return hit;}
 const t={id:++toastSeq,text,error:!!error,count:1,until:now+ms};
 list.push(t);
 while(list.length>TOAST_MAX){const i=list.findIndex(x=>!x.error);list.splice(i<0?0:i,1);}
 return t;
}
/** Drops expired toasts in place; true when anything was removed. */
export function expireToasts(list,now){let kept=0;for(const t of list)if(t.until>now)list[kept++]=t;const changed=kept!==list.length;list.length=kept;return changed;}
export const toastText=t=>t.count>1?`${t.text} ×${t.count}`:t.text;

/* ---- seed strip: the mouse wheel scrolls it sideways ---- */
/** Pixels to add to scrollLeft for a wheel event, or 0 when the strip cannot move that way (then do not preventDefault). */
export function wheelScrollDelta(e,scrollLeft,scrollWidth,clientWidth){
 const max=scrollWidth-clientWidth;if(max<=0||e.ctrlKey)return 0;
 const unit=e.deltaMode===1?16:e.deltaMode===2?clientWidth:1;
 const raw=(Math.abs(e.deltaX)>Math.abs(e.deltaY)?e.deltaX:e.deltaY)*unit;if(!raw)return 0;
 const next=Math.max(0,Math.min(max,scrollLeft+raw));
 return next===scrollLeft?0:next-scrollLeft;
}

/* ---- object hint: where the floating card goes ---- */
/** Card of size {w,h} for a sprite at `a` {x,top,bottom} (screen px), kept inside `box` {x0,y0,x1,y1}.
    Above the sprite when it fits, else below, else pinned inside the box; always fully visible. */
export function placeHint(a,size,box,gap=8){
 const w=Math.min(size.w,box.x1-box.x0),h=Math.min(size.h,box.y1-box.y0);
 const left=Math.max(box.x0,Math.min(box.x1-w,a.x-w/2));
 let top=a.top-gap-h,side='above';
 if(top<box.y0){top=a.bottom+gap;side='below';}
 if(top+h>box.y1){top=Math.max(box.y0,Math.min(box.y1-h,a.top-gap-h));side='pinned';}
 return {left,top,width:w,side};
}

/* ---- what a building is for, generated from the catalog ---- */
const PURPOSE_LEAD={mill:'Мелет урожай в муку и масло.',feedmill:'Готовит корм для животных.',bakery:'Печёт хлеб и сладкое.',kitchen:'Готовит блюда и варенье.',dairy:'Перерабатывает молочное.',loom:'Вяжет, набивает подушки и плетёт букеты.',spinnery:'Прядёт шерсть, пух и лён.',weavery:'Ткёт полотно, сукно и пледы.'};
const uniq=a=>[...new Set(a)];
const short=(a,max)=>a.slice(0,max).join(', ')+(a.length>max?' и др.':'');
/** Up to two short lines: what the building makes, from what, and who or what needs it. [] for decor and plain houses. */
export function buildingPurpose(type,catalog){
 if(type==='road')return ['Грунтовая дорога занимает одну свободную клетку. Продолжай существующую дорогу или прокладывай новые повороты и перекрёстки.'];
 if(!catalog)return [];
 const items=catalog.items||{},nm=id=>String(items[id]?.name||id).toLowerCase();
 const recipes=Object.values(catalog.recipes||{}).filter(r=>r.building===type);
 const animals=Object.values(catalog.animals||{}).filter(a=>a.building===type);
 if(animals.length){
  const a=animals[0],out=uniq(Object.keys(a.outputs||{}).map(nm)),feed=uniq(Object.keys(a.inputs||{}).map(nm));
  return [`Здесь живут ${String(a.name).toLowerCase()}: дают ${short(out,4)}.`,`Корм: ${short(feed,4)}.`];
 }
 if(!recipes.length)return [];
 const outIds=uniq(recipes.flatMap(r=>Object.keys(r.outputs||{}))),inIds=uniq(recipes.flatMap(r=>Object.keys(r.inputs||{})));
 const users=[];
 for(const a of Object.values(catalog.animals||{}))if(outIds.some(id=>a.inputs&&id in a.inputs))users.push(String(a.name).toLowerCase());
 for(const r of Object.values(catalog.recipes||{}))if(r.building!==type&&outIds.some(id=>r.inputs&&id in r.inputs))for(const o of Object.keys(r.outputs||{}))users.push(nm(o));
 const lead=PURPOSE_LEAD[type];
 return [`${lead?lead+' ':''}Делает: ${short(outIds.map(nm),5)}.`,`Из: ${short(inIds.map(nm),5)}.${users.length?` Нужно для: ${short(uniq(users),4)}.`:''}`];
}

/** Camera pan that puts world point (wx,wy) in the middle of a w×h viewport. */
export function panToCenter(w,h,base,scale,wx,wy,cy=h/2){return {x:w/2-base.x-wx*scale,y:cy-base.y-wy*scale};}
export function clampWorldPoint(G,wx,wy){return {x:Math.max(-G*TW,Math.min(G*TW,wx)),y:Math.max(0,Math.min(G*TW,wy))};}

const animalHouses=new WeakMap();
function animalBuildingSet(catalog){
 if(!catalog)return new Set();
 let set=animalHouses.get(catalog);
 if(!set){set=new Set(Object.values(catalog.animals||{}).map(a=>a.building));animalHouses.set(catalog,set);}
 return set;
}
/** plots | animals | workshops | decor | other (house, barn). */
export function categoryOf(o,catalog){
 if(o.type==='plot')return 'plots';
 if(o.type==='house'||o.type==='barn')return 'other';
 if(catalog?.buildings?.[o.type]?.decor)return 'decor';
 if(o.animal||animalBuildingSet(catalog).has(o.type))return 'animals';
 return 'workshops';
}
/** {state:'ready'|'busy'|'idle'|'none', at} — `at` is the earliest ready time of work in progress. */
export function readyInfo(o,t,catalog){
 const cat=categoryOf(o,catalog);
 if(cat==='decor'||cat==='other')return {state:'none',at:0};
 if(cat==='plots'){
  if(!o.crop)return {state:'idle',at:0};
  return o.crop.ready_at<=t?{state:'ready',at:0}:{state:'busy',at:o.crop.ready_at};
 }
 let ready=false,at=0;
 for(const j of o.jobs||[]){if(j.ready_at<=t)ready=true;else if(!at||j.ready_at<at)at=j.ready_at;}
 const a=o.animal_job;
 if(a){if(a.ready_at<=t)ready=true;else if(!at||a.ready_at<at)at=a.ready_at;}
 if(ready)return {state:'ready',at:0};
 return at?{state:'busy',at}:{state:'idle',at:0};
}
/** Entries for the «Найти» list: {o,cat,info}; ready first, then by row/column. */
export function listObjects(objects,catalog,t,{category='all',onlyReady=false}={}){
 const rows=[];
 for(const o of objects||[]){
  const cat=categoryOf(o,catalog);
  if(category!=='all'&&cat!==category)continue;
  const info=readyInfo(o,t,catalog);
  if(onlyReady&&info.state!=='ready')continue;
  rows.push({o,cat,info});
 }
 const rank=r=>r.info.state==='ready'?0:1;
 rows.sort((a,b)=>rank(a)-rank(b)||a.o.y-b.o.y||a.o.x-b.o.x);
 return rows;
}
export function countByCategory(objects,catalog,t){
 const out={all:{n:0,ready:0}};for(const [id] of CATEGORIES)out[id]={n:0,ready:0};
 for(const o of objects||[]){
  const cat=categoryOf(o,catalog),ready=readyInfo(o,t,catalog).state==='ready';
  out.all.n++;out[cat].n++;if(ready){out.all.ready++;out[cat].ready++;}
 }
 return out;
}
/** Mini-map projection: world → canvas pixels with uniform scale k and offset (ox,oy). */
export function miniTransform(G,w,h,pad=6){
 const x0=-G*TW-8,x1=G*TW+8,y0=-24,y1=G*TW+24,k=Math.min((w-pad*2)/(x1-x0),(h-pad*2)/(y1-y0));
 return {k,ox:(w-(x1-x0)*k)/2-x0*k,oy:(h-(y1-y0)*k)/2-y0*k};
}
export const miniToWorld=(m,px,py)=>({x:(px-m.ox)/m.k,y:(py-m.oy)/m.k});

export class Minimap{
 constructor(canvas,scene){
  this.canvas=canvas;this.s=scene;this.ctx=canvas.getContext('2d');this.visible=!canvas.hidden;this.sig='';this.last=0;this.drag=null;this.dpr=1;this.cw=0;this.ch=0;
  canvas.addEventListener('pointerdown',e=>{if(e.button>0)return;e.preventDefault();canvas.setPointerCapture?.(e.pointerId);this.drag=e.pointerId;this.moveTo(e);});
  canvas.addEventListener('pointermove',e=>{if(this.drag===e.pointerId){e.preventDefault();this.moveTo(e);}});
  const end=e=>{if(this.drag===e.pointerId)this.drag=null;};
  canvas.addEventListener('pointerup',end);canvas.addEventListener('pointercancel',end);
 }
 setVisible(on){this.visible=!!on;this.canvas.hidden=!on;this.sig='';this.s.dirty=true;}
 moveTo(e){
  const r=this.canvas.getBoundingClientRect();if(!r.width||!this.s.farm)return;
  const G=this.s.grid(),m=miniTransform(G,r.width,r.height),q=miniToWorld(m,e.clientX-r.left,e.clientY-r.top);
  this.s.centerOn(q.x,q.y);
 }
 fitCanvas(){
  const r=this.canvas.getBoundingClientRect(),d=Math.min(window.devicePixelRatio||1,2);
  if(r.width!==this.cw||r.height!==this.ch||d!==this.dpr){this.cw=r.width;this.ch=r.height;this.dpr=d;this.canvas.width=Math.round(r.width*d);this.canvas.height=Math.round(r.height*d);this.sig='';}
 }
 /** Called after every scene frame: redraws only when the camera, the farm or the clock-second changed. */
 update(nowMs){
  if(!this.visible||!this.s.farm)return;
  const s=this.s;this.fitCanvas();if(!this.cw)return;
  const sig=`${s.scale}|${s.pan.x}|${s.pan.y}|${s.w}|${s.h}|${s.farmToken}|${this.cw}`;
  if(sig===this.sig&&nowMs-this.last<1000)return;
  this.sig=sig;this.last=nowMs;this.draw();
 }
 draw(){
  const s=this.s,c=this.ctx,w=this.cw,h=this.ch,G=s.grid(),area=s.farm.size,m=miniTransform(G,w,h),t=s.now();
  c.setTransform(this.dpr,0,0,this.dpr,0,0);c.clearRect(0,0,w,h);
  const X=(wx)=>m.ox+wx*m.k,Y=(wy)=>m.oy+wy*m.k,diamond=(x,y,ww,hh)=>{const a=iso(x,y),b=iso(x+ww,y),d=iso(x+ww,y+hh),e=iso(x,y+hh);c.beginPath();c.moveTo(X(a.x),Y(a.y));c.lineTo(X(b.x),Y(b.y));c.lineTo(X(d.x),Y(d.y));c.lineTo(X(e.x),Y(e.y));c.closePath();};
  c.fillStyle='#e6eed8';diamond(0,0,G,G);c.fill();
  c.fillStyle='#c4d6a6';diamond(0,0,area,area);c.fill();
  c.setLineDash([]);c.strokeStyle='#6f8f5a';c.lineWidth=1.4;diamond(0,0,area,area);c.stroke();
  if(area<G){c.strokeStyle='#a9bd92';c.lineWidth=1;c.setLineDash([3,3]);diamond(0,0,G,G);c.stroke();c.setLineDash([]);}
  const catalog=s.catalog,ready=[];
  for(const o of s.farm.objects){
   const cat=categoryOf(o,catalog);c.fillStyle=CATEGORY_COLOR[cat];diamond(o.x,o.y,o.w,o.h);c.fill();
   if(readyInfo(o,t,catalog).state==='ready')ready.push(o);
  }
  for(const o of ready){const p=iso(o.x+o.w/2,o.y+o.h/2);c.beginPath();c.arc(X(p.x),Y(p.y),2.6,0,Math.PI*2);c.fillStyle='#fff6c9';c.fill();c.lineWidth=1;c.strokeStyle='#8a6a1e';c.stroke();}
  const v=s.viewRect(0);
  c.save();c.beginPath();c.rect(0,0,w,h);c.clip();
  c.fillStyle='#ffffff2e';c.strokeStyle='#245c43';c.lineWidth=1.8;
  const rx=X(v.x0),ry=Y(v.y0),rw=(v.x1-v.x0)*m.k,rh=(v.y1-v.y0)*m.k;c.fillRect(rx,ry,rw,rh);c.strokeRect(rx,ry,rw,rh);
  c.restore();
 }
}
