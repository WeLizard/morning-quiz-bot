// Headless farm scene for the performance budget (tests/js/farm_perf_budget.test.cjs, docs/FARM_PERF_DEBUG.md).
// A fake 2D canvas counts every context method call; the real FarmScene draws a synthetic heavy farm into it, and the
// scene profiler (qw_farm/static/scene_profiler.js) attributes the calls to layers and object types by the same rules the
// in-game overlay uses for milliseconds. Clocks and Math.random are fixed, so the counts are the same on every machine.

let calls=0;
const methodCalls=new Map();
const PROPS={fillStyle:'#000',strokeStyle:'#000',lineWidth:1,globalAlpha:1,font:'10px sans-serif',textAlign:'start',textBaseline:'alphabetic',
 lineCap:'butt',lineJoin:'miter',miterLimit:10,filter:'none',globalCompositeOperation:'source-over',shadowBlur:0,shadowColor:'transparent',
 shadowOffsetX:0,shadowOffsetY:0,imageSmoothingEnabled:true,imageSmoothingQuality:'low',lineDashOffset:0,direction:'inherit',letterSpacing:'0px'};
const mul=(m,n)=>({a:m.a*n.a+m.c*n.b,b:m.b*n.a+m.d*n.b,c:m.a*n.c+m.c*n.d,d:m.b*n.c+m.d*n.d,e:m.a*n.e+m.c*n.f+m.e,f:m.b*n.e+m.d*n.f+m.f});
const ID={a:1,b:0,c:0,d:1,e:0,f:0};

function fakeContext(canvas){
 const state={m:{...ID},stack:[],props:{...PROPS}};
 const own={
  canvas,
  save(){state.stack.push({m:state.m,props:{...state.props}})},
  restore(){const s=state.stack.pop();if(s){state.m=s.m;state.props=s.props}},
  setTransform(a,b,c,d,e,f){state.m=typeof a==='object'?{a:a.a,b:a.b,c:a.c,d:a.d,e:a.e,f:a.f}:{a,b,c,d,e,f}},
  resetTransform(){state.m={...ID}},
  transform(a,b,c,d,e,f){state.m=mul(state.m,{a,b,c,d,e,f})},
  translate(x,y){state.m=mul(state.m,{a:1,b:0,c:0,d:1,e:x,f:y})},
  scale(x,y){state.m=mul(state.m,{a:x,b:0,c:0,d:y,e:0,f:0})},
  rotate(r){const c=Math.cos(r),s=Math.sin(r);state.m=mul(state.m,{a:c,b:s,c:-s,d:c,e:0,f:0})},
  getTransform(){return {...state.m}},
  measureText(text){return {width:String(text).length*6,actualBoundingBoxAscent:8,actualBoundingBoxDescent:2}},
  createLinearGradient(){return {addColorStop(){}}},
  createRadialGradient(){return {addColorStop(){}}},
  createConicGradient(){return {addColorStop(){}}},
  createPattern(){return {setTransform(){}}},
  getImageData(x,y,w,h){return {width:w,height:h,data:new Uint8ClampedArray(Math.max(0,w*h*4))}},
  getLineDash(){return []},
  isPointInPath(){return false},
 };
 return new Proxy(own,{
  get(t,prop){
   if(prop in state.props)return state.props[prop];
   if(typeof prop!=='string')return t[prop];
   const fn=t[prop]||(()=>{});
   if(prop==='canvas')return canvas;
   return function(...args){calls++;methodCalls.set(prop,(methodCalls.get(prop)||0)+1);return fn.apply(t,args)};
  },
  set(t,prop,value){state.props[prop]=value;return true},
  has(t,prop){return prop in state.props||prop in t},
 });
}
function fakeCanvas(w=0,h=0){
 const canvas={width:w,height:h,hidden:false,style:{},offsetParent:{},cssW:w,cssH:h,
  addEventListener(){},removeEventListener(){},setPointerCapture(){},releasePointerCapture(){},hasPointerCapture(){return false},
  getBoundingClientRect(){return {left:0,top:0,width:canvas.cssW,height:canvas.cssH,right:canvas.cssW,bottom:canvas.cssH}}};
 let ctx=null;canvas.getContext=()=>ctx||(ctx=fakeContext(canvas));
 return canvas;
}

// Deterministic environment: one fake clock for Date.now and performance.now, a seeded Math.random.
function installEnvironment(){
 const saved={};
 for(const k of ['document','window','matchMedia','ResizeObserver','requestAnimationFrame','cancelAnimationFrame','devicePixelRatio','performance','getComputedStyle'])saved[k]=Object.getOwnPropertyDescriptor(globalThis,k);
 const clock={ms:1_800_000_000_000};
 const savedNow=Date.now,savedRandom=Math.random;
 let seed=12345;
 const define=(k,v)=>Object.defineProperty(globalThis,k,{value:v,configurable:true,writable:true});
 define('document',{hidden:false,addEventListener(){},removeEventListener(){},createElement:()=>fakeCanvas(),querySelector:()=>null,
  documentElement:{getAttribute:()=>null}});
 define('window',{addEventListener(){},removeEventListener(){},devicePixelRatio:1});
 define('matchMedia',()=>({matches:false,addEventListener(){}}));
 define('ResizeObserver',class{observe(){}disconnect(){}});
 define('requestAnimationFrame',()=>1);define('cancelAnimationFrame',()=>{});
 define('devicePixelRatio',1);
 define('performance',{now:()=>clock.ms-1_800_000_000_000});
 Date.now=()=>clock.ms;
 Math.random=()=>{seed=(seed*1103515245+12345)&0x7fffffff;return seed/0x80000000};
 return {clock,restore(){
  Date.now=savedNow;Math.random=savedRandom;
  for(const [k,d] of Object.entries(saved)){if(d)Object.defineProperty(globalThis,k,d);else delete globalThis[k]}
 }};
}

// The heavy farm of the budget: 120 barley beds, 40 fruit trees, 39 upgraded buildings with animals and jobs, 6 decor pieces,
// a tractor, a harvester and two helpers at work. Land 22 x 22; times are relative to the fake clock (seconds).
const BUILDINGS=['house','barn','mill','coop','cowshed','sheepfold','apiary','goatshed','rabbit_hutch','alpaca_pen','goose_house','pigsty',
 'turkey_yard','quail_house','teahouse','garage','bakery','feedmill','kitchen','dairy','loom','spinnery','weavery','oil_press','juicery',
 'cannery','smokehouse','tailor','confectionery','creamery','sausage_shop','cattle_barn','syrupery','soapery','noodle_shop','energy_shop',
 'dryer','cellar','mill'];
const ANIMAL={coop:'chicken',cowshed:'cow',sheepfold:'sheep',apiary:'bees',goatshed:'goat',rabbit_hutch:'rabbit',alpaca_pen:'alpaca',
 goose_house:'goose',pigsty:'pig',turkey_yard:'turkey',quail_house:'quail'};
const DECOR=['flowerbed','bench','lantern','scarecrow','birdhouse','flowerbed'];
const SPECIES=['apple','cherry','pear','plum','apricot','peach','pomegranate'];
function heavyFarm(now){
 const objects=[];let n=0;const id=p=>`${p}-${++n}`;
 for(let y=3;y<13;y++)for(let x=3;x<15;x++){
  const k=objects.length,ripe=k%3===0;
  objects.push({id:id('plot'),type:'plot',x,y,w:1,h:1,crop:{id:'barley',planted_at:now-600,ready_at:ripe?now-30:now+600+k*7,fert:k%5===0}});
 }
 let trees=0;
 for(let y=3;y<9&&trees<40;y++)for(let x=15;x<22&&trees<40;x++,trees++)
  objects.push({id:id('tree'),type:'tree',species:SPECIES[trees%SPECIES.length],x,y,w:1,h:1,harvests:trees%4*6,planted_at:now-90000,
   fruit:{started_at:now-3000,ready_at:trees%3?now+3000:now-10}});
 const spots=[];for(const y of [9,11])for(const x of [15,17,19])spots.push([x,y]);
 for(const y of [13,15,17,19])for(let x=3;x<21;x+=2)spots.push([x,y]);
 BUILDINGS.forEach((type,i)=>{
  const [x,y]=spots[i],animal=ANIMAL[type]||null,level=1+i%3;
  const jobs=animal?[]:i%2?[{recipe:'r',ready_at:i%4===1?now-5:now+900}]:[];
  objects.push({id:id(type),type,x,y,w:2,h:2,level,revision:1,jobs,animal,animal_job:animal?{ready_at:i%2?now+600:now-5}:null});
 });
 DECOR.forEach((type,i)=>objects.push({id:id(type),type,x:i%2,y:4+i*2,w:1,h:1,level:1,jobs:[]}));
 return {id:'perf-farm',size:22,objects,server_time:now,is_owner:true,xp:20000,
  equipment:{tractor:{zone:{x:3,y:3,w:12,h:10},active:true},harvester:{zone:{x:3,y:3,w:12,h:10}}},
  helpers:{rabbit_gardener:{active:true},raccoon:{active:true}},
  pranks:[],home_projects:{entries:{}},meadow_view:{patches:[]}};
}
const CATALOG={
 crops:{barley:{id:'barley',name:'Ячмень',color:'#d7bf74'}},
 buildings:{},
 equipment:{tractor:{role:'sow'},harvester:{role:'reap'},robot:{role:'harvest'}},
 helpers:{rabbit_gardener:{role:'water'},raccoon:{role:'production'}},
 orchard:{trees:Object.fromEntries(SPECIES.map(s=>[s,{id:s,name:s,juvenile:2}])),rules:{}},
};

// Builds the scene at a fixed viewport and returns helpers to draw frames on the fake clock.
async function openScene({width=1280,height=800}={}){
 const env=installEnvironment();
 const {FarmScene}=await import('../../qw_farm/static/scene.js');
 const {createProfiler}=await import('../../qw_farm/static/scene_profiler.js');
 const canvas=fakeCanvas();canvas.cssW=width;canvas.cssH=height;
 const scene=new FarmScene(canvas,{});
 scene.set(heavyFarm(Date.now()/1000),CATALOG);scene.fit(true);
 const profiler=createProfiler({clock:()=>calls,wall:()=>performance.now()}).instrument(FarmScene.prototype);
 const frame=(ms=33)=>{env.clock.ms+=ms;scene.draw(performance.now()/1000)};
 return {scene,profiler,frame,env,calls:()=>calls,methodCalls,close(){profiler.restore();env.restore()}};
}

module.exports={openScene,heavyFarm,CATALOG,fakeCanvas};
