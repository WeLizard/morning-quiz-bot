// Draw-call budget of the farm scene (docs/FARM_PERF_DEBUG.md). The real FarmScene draws a synthetic heavy farm (120 barley
// beds, 40 fruit trees, 39 upgraded buildings, 6 decor pieces, crew at work) into a fake canvas that counts context calls.
// Each scenario (idle, pan, zoom, night) is compared with tests/js/farm_perf_budget.json per layer and object type: when a
// change makes a layer or a building type paint more than its budget, the test fails and names it.
// Re-record after a justified change or an optimisation (PowerShell):
//   $env:FARM_PERF_UPDATE='1'; node --test tests/js/farm_perf_budget.test.cjs; Remove-Item Env:FARM_PERF_UPDATE
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {openScene}=require('./farm_perf_harness.cjs');

const BUDGET_FILE=path.join(__dirname,'farm_perf_budget.json');
const UPDATE=process.env.FARM_PERF_UPDATE==='1';
const TOLERANCE={ratio:.15,calls:25};   // a layer may grow 15% + 25 calls a frame before the test fails
const NEW_SECTION_LIMIT=150;             // a layer that has no budget yet may cost this much a frame
// Cache repaints over the measured frames: a cache that starts expiring (a sprite reading the clock) costs few calls
// on average but stalls the frame it repaints in, so the counters have their own budget.
const REPAINTS={staticPaints:'земля',fieldPaints:'посев',spritePaints:'постройки и деревья'};
const allowedRepaints=b=>b+Math.max(2,Math.ceil(b*TOLERANCE.ratio));
const WARMUP=30,FRAMES=60;               // ~1 s to fill caches, then ~2 s measured at the 33 ms idle rate

const SCENARIOS={
 // Nothing moves but the ambience: plants sway in the cached field layer, smoke and flags animate, the crew works.
 idle:{},
 // The camera slides ~180 px/s to the right: the ground and field caches are reused and repainted when the pan leaves the margin.
 pan:{step(h){h.scene.pan.x+=6;h.scene.dirty=true}},
 // Wheel zoom in then out around the centre: every frame has a new scale, the field layer is drawn live until the zoom settles.
 zoom:{step(h,i){const s=h.scene;s.zoomAt(s.w/2,s.h/2,i<FRAMES/2?1.02:1/1.02)}},
 // Night: lantern glows, the night tint and ready badges painted above it.
 night:{setup(h){h.scene.setLighting({mode:'night',phase:'night',darkness:1,warmth:0})}},
};

async function measure(name){
 const sc=SCENARIOS[name],h=await openScene();
 try{
  sc.setup?.(h);
  for(let i=0;i<WARMUP;i++)h.frame();
  h.profiler.reset();
  for(let i=0;i<FRAMES;i++){sc.step?.(h,i);h.frame()}
  const s=h.profiler.summary();
  // The profiler is exclusive: the sections of every frame add up to the frame total.
  for(const f of h.profiler.frames)assert.equal(Object.values(f.sections).reduce((a,b)=>a+b,0),f.total,`${name}: sections add up to the frame`);
  return s;
 }finally{h.close()}
}
const allowed=b=>Math.round(b*(1+TOLERANCE.ratio)+TOLERANCE.calls);
const pct=(v,b)=>b?`${v>=b?'+':''}${Math.round((v/b-1)*100)}%`:'новый';

function compare(name,s,budget){
 const over=[],lines=[];
 const total=budget.total;
 if(s.avg>allowed(total.avg))over.push({id:'кадр целиком (среднее)',v:s.avg,b:total.avg});
 if(s.max>allowed(total.max))over.push({id:'кадр целиком (худший)',v:s.max,b:total.max});
 for(const r of s.sections){
  const b=budget.sections[r.id];
  if(b===undefined){if(r.avg>NEW_SECTION_LIMIT)over.push({id:`${r.name} (${r.id})`,v:r.avg,b:0,limit:NEW_SECTION_LIMIT});continue}
  if(r.avg>allowed(b))over.push({id:`${r.name} (${r.id})`,v:r.avg,b});
 }
 over.sort((a,b)=>(b.v-b.b)-(a.v-a.b));
 for(const o of over)lines.push(o.limit?`  ${o.id}: ${Math.round(o.v)} вызовов/кадр — нового слоя нет в бюджете, без записи допускается ${o.limit}`:
  `  ${o.id}: ${Math.round(o.v)} вызовов/кадр, бюджет ${allowed(o.b)} (база ${o.b}, ${pct(o.v,o.b)})`);
 for(const [k,label] of Object.entries(REPAINTS)){
  const v=s.stats[k]||0,b=budget.stats?.[k]||0;
  if(v>allowedRepaints(b))lines.push(`  перерисовки кэша «${label}» (${k}): ${v} за ${FRAMES} кадров, бюджет ${allowedRepaints(b)} (база ${b})`);
 }
 return lines.length?`Сцена «${name}» превысила бюджет отрисовки:\n${lines.join('\n')}\n`+
  'Найди, что стало рисоваться чаще (оверлей ?debug=perf покажет то же в миллисекундах). Если рост оправдан — перезапиши бюджет:\n'+
  "  $env:FARM_PERF_UPDATE='1'; node --test tests/js/farm_perf_budget.test.cjs; Remove-Item Env:FARM_PERF_UPDATE":'';
}
const record=s=>({total:{avg:Math.round(s.avg),max:Math.round(s.max)},
 stats:s.stats,sections:Object.fromEntries(s.sections.filter(r=>r.avg>=1).map(r=>[r.id,Math.round(r.avg)]))});

const recorded={};
for(const name of Object.keys(SCENARIOS)){
 test(`farm scene stays within its draw-call budget: ${name}`,async t=>{
  const s=await measure(name);
  t.diagnostic(`${name}: ${Math.round(s.avg)} вызовов/кадр в среднем, худший ${Math.round(s.max)}; дороже всего: `+
   s.sections.slice(0,4).map(r=>`${r.id} ${Math.round(r.avg)}`).join(', '));
  if(UPDATE){recorded[name]=record(s);return}
  const budget=JSON.parse(fs.readFileSync(BUDGET_FILE,'utf8')).scenarios[name];
  assert.ok(budget,`no budget for «${name}» in ${path.basename(BUDGET_FILE)}: record it with FARM_PERF_UPDATE=1`);
  const message=compare(name,s,budget);
  if(message)assert.fail(message);
  if(s.avg<budget.total.avg*.7)t.diagnostic(`${name}: кадр на ${pct(s.avg,budget.total.avg)} дешевле бюджета — перезапиши бюджет, чтобы закрепить выигрыш`);
 });
}
test('budget file is written in update mode',{skip:!UPDATE},()=>{
 const out={
  about:'Бюджет вызовов canvas на кадр для tests/js/farm_perf_budget.test.cjs (docs/FARM_PERF_DEBUG.md). Числа — среднее за 60 кадров; '+
   `допуск ${TOLERANCE.ratio*100}% + ${TOLERANCE.calls} вызовов. Перезаписывается командой из шапки теста.`,
  scenarios:recorded,
 };
 fs.writeFileSync(BUDGET_FILE,JSON.stringify(out,null,1)+'\n');
});

test('the same scene and clock give the same counts (the budget does not depend on the machine)',async()=>{
 const a=await measure('idle'),b=await measure('idle');
 assert.equal(a.avg,b.avg);assert.equal(a.max,b.max);
});

test('a cache that starts repainting is reported even when the average calls barely move',async()=>{
 const s=await measure('idle'),budget=record(s);
 assert.equal(compare('idle',s,budget),'');
 const leaking={...s,stats:{...s.stats,spritePaints:(s.stats.spritePaints||0)+12}};
 assert.match(compare('idle',leaking,budget),/перерисовки кэша «постройки и деревья» \(spritePaints\)/);
});

test('a building that paints more is reported by its type',async()=>{
 const {FarmScene}=await import('../../qw_farm/static/scene.js');
 const budget=record(await measure('idle'));
 const orig=FarmScene.prototype.drawObject;
 // A pretend regression: every mill gets 300 extra strokes a frame.
 FarmScene.prototype.drawObject=function(o){orig.call(this,o);if(o.type==='mill')for(let i=0;i<300;i++)this.line(0,0,1,1,'#000')};
 try{
  const message=compare('idle',await measure('idle'),budget);
  assert.match(message,/постройка: mill \(building:mill\)/);
  assert.doesNotMatch(message,/building:barn/);
 }finally{FarmScene.prototype.drawObject=orig}
});
