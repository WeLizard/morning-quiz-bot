// Farm performance debugger (qw_farm/static/perf_debug.js, docs/FARM_PERF_DEBUG.md): switched on only explicitly,
// never loaded for players, and its pure helpers (animation check, timers) behave as documented.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.join(__dirname,'..','..');
const read=f=>fs.readFileSync(path.join(root,f),'utf8');

test('the overlay is off unless ?debug=perf or the localStorage flag asks for it',async()=>{
 const {perfDebugEnabled,PERF_KEY}=await import('../../qw_farm/static/perf_debug.js');
 const store=v=>({getItem:k=>k===PERF_KEY?v:null});
 assert.equal(perfDebugEnabled({search:''},store(null)),false);
 assert.equal(perfDebugEnabled({search:'?tab=fields'},store('0')),false);
 assert.equal(perfDebugEnabled({search:'?debug=perf'},store(null)),true);
 assert.equal(perfDebugEnabled({search:'?x=1&debug=layout,perf'},store(null)),true);
 assert.equal(perfDebugEnabled({search:''},store('1')),true);
 assert.equal(perfDebugEnabled({search:''},{getItem(){throw new Error('blocked storage')}}),false);
});

test('app.js loads the debugger only behind the switch and before the timers start',()=>{
 const app=read('qw_farm/static/app.js');
 assert.doesNotMatch(app,/^import[^\n]*perf_debug/m,'perf_debug.js must not be a static import: players would download it');
 const hook=app.indexOf("await import('./perf_debug.js')"),timers=app.indexOf('\nsyncUITimers();');
 assert.ok(hook>0&&timers>hook,'the hook wraps updateReady/poll before syncUITimers() hands them to setInterval');
 const guard=app.slice(app.lastIndexOf('\nif(',hook),hook);
 assert.match(guard,/debug=/);assert.match(guard,/qw-farm-perf/);
 // The server allow-lists farm assets: the debugger files must be served.
 const api=read('qw_farm/api.py');
 for(const f of ['perf_debug.js','perf_debug.css','scene_profiler.js'])assert.ok(api.includes(`'${f}'`),`${f} is in qw_farm/api.py ASSETS`);
});

test('non-composited and in-SVG animations are reported, compositor-only ones are not',async()=>{
 const {animationReport}=await import('../../qw_farm/static/perf_debug.js');
 const target=({village=true,svg=false,tag='div',cls=''}={})=>({tagName:tag.toUpperCase(),className:cls,id:'',ownerSVGElement:svg?{}:null,
  closest:sel=>sel==='.village-scene'&&village?{}:null});
 const anim=(name,keys,t,playState='running')=>({animationName:name,playState,effect:{target:t,getKeyframes:()=>keys.map(k=>({offset:0,easing:'linear',composite:'auto',[k]:'1'}))}});
 const r=animationReport([
  anim('v-walk',['transform'],target()),
  anim('vfx-smoke',['transform','opacity'],target()),
  anim('v-resident-walk',['translate'],target()),
  anim('vp-hop',['marginTop'],target({cls:'village-npc'})),
  anim('v-glow',['boxShadow','opacity'],target({village:false})),
  anim('wing',['transform'],target({svg:true,tag:'g'})),
  anim('paused',['left'],target(),'paused'),
 ]);
 assert.equal(r.total,6);assert.equal(r.village,5);
 assert.deepEqual(r.slow.map(a=>[a.name,a.props.join(','),a.village]),[
  ['vp-hop','margin-top',true],['wing','transform',true],['v-glow','box-shadow',false]]);
 assert.equal(r.slow[1].reason,'элемент внутри SVG');
 assert.equal(r.slow[0].target,'div.village-npc');
});

test('timed() records sync calls and async calls with their synchronous start',async()=>{
 const {timed,mountPerfDebug}=await import('../../qw_farm/static/perf_debug.js');
 assert.equal(typeof mountPerfDebug,'function');
 const sync=timed('t-sync',x=>x*2),later=timed('t-async',async x=>{await new Promise(r=>setTimeout(r,5));return x+1});
 assert.equal(sync(4),8);
 assert.equal(await later(1),2);
 const bad=timed('t-throw',()=>{throw new Error('boom')});
 assert.throws(()=>bad(),/boom/);
});

test('the profiler wraps and restores scene methods without changing what they return',async()=>{
 const {createProfiler,objectSection,sectionName}=await import('../../qw_farm/static/scene_profiler.js');
 let t=0;
 class Scene{draw(){t+=1;this.drawObject({id:'a',type:'mill'});this.drawObject({id:'b',type:'tree'});return 'drawn'}
  drawObject(o){t+=o.type==='mill'?10:3}paintFields(){t+=5;this.drawObject({id:'c',type:'plot'})}}
 const orig=Scene.prototype.drawObject;
 const P=createProfiler({clock:()=>t,wall:()=>t}).instrument(Scene.prototype);
 const s=new Scene();
 s.drawObject({id:'x',type:'mill'});                     // outside a frame: not measured
 assert.equal(s.draw(),'drawn');
 assert.equal(P.frames.length,1);
 assert.deepEqual(P.frames[0].sections,{draw:1,'building:mill':10,trees:3});
 assert.equal(P.frames[0].total,14);
 assert.equal(P.summary().objects[0].id,'a');
 P.restore();assert.equal(Scene.prototype.drawObject,orig);
 assert.equal(objectSection({type:'bench'}),'decor:bench');
 assert.equal(sectionName('building:mill'),'постройка: mill');
});
