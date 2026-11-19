/* Scene profiler (docs/FARM_PERF_DEBUG.md). It wraps FarmScene.prototype methods from the outside, so scene.js carries no
   measuring code and an unwrapped scene costs nothing. Every wrapped call is a section on a stack; a section keeps its
   EXCLUSIVE cost (its nested sections are subtracted), so the per-section numbers of a frame add up to the whole frame.
   The metric is pluggable: the in-game overlay uses milliseconds (performance.now), the budget test in tests/js counts the
   calls of a fake canvas. Sections:
     - draw is the frame root; its own cost is what draw() paints inline (clear, markers above the night, minimap callback);
     - drawObject and drawObjectSprite (the cached bitmap of a building or tree) are labelled by the object:
       'building:<type>', 'trees', 'plots', 'roads', 'decor:<type>'; the per-object cost counts the outer call only;
     - opaque sections (the cached ground repaint, the field layer) keep everything they call as their own cost.
   Methods missing from the prototype are skipped, so the profiler survives refactors of scene.js. */

// id -> human name for the overlay and the budget report. Ids not listed (building:*, decor:*) are formatted by sectionName().
export const SECTION_NAMES={
 draw:'кадр: метки и прочее',background:'фон и небо',groundWash:'фон и небо',
 staticLayer:'земля (готовая картинка)',paintStatic:'земля: перерисовка кэша',
 paintFields:'посев: грядки и растения',forestFog:'туман',lakeLife:'озеро: лебеди, утки',standingOrder:'сортировка слоёв',
 plots:'грядки (вне слоя посева)',trees:'деревья сада',roads:'дороги',
 drawLit:'подсветка объекта под мышью',paintHover:'подсветка клетки',drawMeadow:'луг',plotMarkers:'метки грядок',
 perimeterLantern:'фонари по краю',fence:'забор',welcomeSign:'табличка фермы',animals:'животные у построек',
 paintTrees:'лес',skyFlock:'птицы в небе',paintDynamic:'слои: проход, зоны команды, беседка',drawSprite:'команда, гуси, скот на выгуле',
 paintLighting:'ночь: затемнение',paintLanternLights:'ночь: свет фонарей',paintParticles:'частицы',paintPetals:'лепестки',
 minimap:'мини-карта'
};
export function sectionName(id){
 if(SECTION_NAMES[id])return SECTION_NAMES[id];
 if(id.startsWith('building:'))return 'постройка: '+id.slice(9);
 if(id.startsWith('decor:'))return 'декор: '+id.slice(6);
 return id;
}
const DECOR=new Set(['flowerbed','bench','lantern','scarecrow','birdhouse','duckpond']);
export function objectSection(o){
 const t=o?.type||'?';
 if(t==='tree')return 'trees';if(t==='plot')return 'plots';if(t==='road')return 'roads';
 return (DECOR.has(t)?'decor:':'building:')+t;
}
// [method, section id or (this,args)=>id, options]. `object` records the per-object (inclusive) cost.
const SCENE_SECTIONS=[
 ['draw','draw',{root:true}],
 ['background','background'],['groundWash','groundWash'],
 ['staticLayer','staticLayer'],['paintStatic','paintStatic',{opaque:true}],
 ['paintFields','paintFields',{opaque:true}],['plotGround','paintFields'],['plotPlant','paintFields'],   // beds drawn live count as the field layer
 ['paintDynamic','paintDynamic'],['standingOrder','standingOrder'],['forestFog','forestFog'],['lakeLife','lakeLife'],
 ['drawObjectSprite',(s,a)=>objectSection(a[0]),{object:true}],['drawObject',(s,a)=>objectSection(a[0]),{object:true}],['drawLit','drawLit'],
 ['drawMeadow','drawMeadow'],['plotMarkers','plotMarkers'],
 ['perimeterLantern','perimeterLantern'],['fence','fence'],['welcomeSign','welcomeSign'],
 ['drawAnimal','animals'],['chicken','animals'],
 ['paintTrees','paintTrees'],['skyFlock','skyFlock'],['drawSprite','drawSprite'],
 ['paintLighting','paintLighting'],['paintLanternLights','paintLanternLights'],
 ['paintParticles','paintParticles'],['paintPetals','paintPetals'],['paintHover','paintHover'],
];
const STAT_KEYS=['staticPaints','staticBlits','fieldPaints','spritePaints','spriteBlits'];

export function createProfiler({clock=()=>performance.now(),wall=clock,keep=120}={}){
 const P={on:true,frames:[],objects:new Map(),wrapped:[],stack:[],opaque:0,cur:null,statsAt:null,scene:null,totalFrames:0};
 const enter=(id,obj,opaque)=>{
  const top=P.stack[P.stack.length-1];if(obj&&top?.obj===obj)obj=null;   // drawObjectSprite -> drawObject: one object, counted once
  P.stack.push({id,t:clock(),child:0,obj,opaque});if(opaque)P.opaque++;
 };
 const leave=()=>{
  const e=P.stack.pop(),dt=clock()-e.t,own=dt-e.child;
  if(e.opaque)P.opaque--;
  P.cur[e.id]=(P.cur[e.id]||0)+own;
  if(P.stack.length)P.stack[P.stack.length-1].child+=dt;
  if(e.obj){const key=e.obj.id??e.obj;let r=P.objects.get(key);if(!r)P.objects.set(key,r={id:key,type:e.obj.type,x:e.obj.x,y:e.obj.y,sum:0,n:0,last:0,max:0});r.sum+=dt;r.n++;r.last=dt;if(dt>r.max)r.max=dt}
  return dt;
 };
 const statsOf=s=>{const o={};for(const k of STAT_KEYS)o[k]=s?.stats?.[k]||0;return o};
 const startFrame=scene=>{P.cur={};P.scene=scene;P.statsAt=statsOf(scene);P.frameWall=wall()};
 const endFrame=(scene,total)=>{
  const now=statsOf(scene),stats={};for(const k of STAT_KEYS)stats[k]=now[k]-P.statsAt[k];
  stats.objects=scene?.stats?.objects||0;stats.drawn=scene?.stats?.drawn||0;
  P.frames.push({at:P.frameWall,total,sections:P.cur,stats});if(P.frames.length>keep)P.frames.shift();
  P.totalFrames++;P.cur=null;P.onFrame?.(P.frames[P.frames.length-1]);
 };
 P.wrap=(target,name,label,{root=false,opaque=false,object=false}={})=>{
  const orig=target?.[name];if(typeof orig!=='function'||orig.__perfOrig)return false;
  const wrapped=function(...args){
   if(!P.on||P.opaque||(root?P.stack.length:!P.stack.length))return orig.apply(this,args);
   const id=typeof label==='function'?label(this,args):label;
   if(root)startFrame(this);
   enter(id,object?args[0]:null,opaque);
   let dt=0;try{return orig.apply(this,args)}finally{dt=leave();if(root)endFrame(this,dt)}
  };
  wrapped.__perfOrig=orig;target[name]=wrapped;P.wrapped.push([target,name,orig]);return true;
 };
 // proto: FarmScene.prototype; minimap: Minimap.prototype (optional).
 P.instrument=(proto,minimap=null)=>{
  for(const [name,label,opts] of SCENE_SECTIONS)P.wrap(proto,name,label,opts);
  if(minimap)P.wrap(minimap,'update','minimap');
  return P;
 };
 P.restore=()=>{for(const [target,name,orig] of P.wrapped.reverse())target[name]=orig;P.wrapped=[]};
 P.reset=()=>{P.frames.length=0;P.objects.clear()};
 // Averages over the kept frames: sections sorted by cost, the costliest objects and the cache counters.
 P.summary=({frames=P.frames}={})=>{
  const n=frames.length,sections=new Map(),stats={};let total=0,max=0;
  for(const f of frames){total+=f.total;if(f.total>max)max=f.total;
   for(const [id,v] of Object.entries(f.sections)){let r=sections.get(id);if(!r)sections.set(id,r={id,name:sectionName(id),sum:0,max:0});r.sum+=v;if(v>r.max)r.max=v}
   for(const [k,v] of Object.entries(f.stats))stats[k]=(stats[k]||0)+(k==='objects'||k==='drawn'?0:v);}
  const last=frames[n-1];if(last){stats.objects=last.stats.objects;stats.drawn=last.stats.drawn}
  const span=n>1?(frames[n-1].at-frames[0].at)/1000:0;
  const list=[...sections.values()].map(r=>({id:r.id,name:r.name,avg:n?r.sum/n:0,max:r.max,share:total?r.sum/total:0})).sort((a,b)=>b.avg-a.avg);
  const objects=[...P.objects.values()].map(r=>({...r,avg:r.sum/r.n})).sort((a,b)=>b.avg-a.avg);
  return {frames:n,avg:n?total/n:0,max,fps:span>0?(n-1)/span:0,sections:list,objects,stats};
 };
 return P;
}
