const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../../qw_farm/static/app.js'),'utf8');
const fn=name=>{const a=source.indexOf(`function ${name}(`);let d=0,k=source.indexOf('{',a);for(;;k++){if(source[k]==='{')d++;else if(source[k]==='}'&&--d===0)break;}return source.slice(a,k+1)+';\n';};
const code=source.slice(source.indexOf('function renderObject(p)'),source.indexOf('async function visit(id)'))+['recipeMemory','repeatToggle','bulkCounts','bulkRepeatPlan','jobRefund','confirmCancelJob'].map(fn).join('');
class Node{constructor(text,cls){this.textContent=text;this.className=cls;this.children=[];this.dataset={};this.attributes={};this.classList={add:c=>{this.className=[this.className,c].filter(Boolean).join(' ');}};}append(...n){this.children.push(...n);}setAttribute(k,v){this.attributes[k]=String(v);}getAttribute(k){return this.attributes[k]??null;}all(){return this.children.flatMap(c=>c instanceof Node?[c,...c.all()]:[]);}}
const recipes={bread:{id:'bread',building:'bakery',name:'Хлеб',inputs:{wheat:1},outputs:{bread:1},seconds:20,level:1},pie:{id:'pie',building:'bakery',name:'Пирог',inputs:{wheat:2},outputs:{pie:1},seconds:30,level:1},cake:{id:'cake',building:'bakery',name:'Торт',inputs:{wheat:9},outputs:{cake:1},seconds:30,level:5},rye_flour:{id:'rye_flour',building:'mill',name:'Ржаная мука',inputs:{rye:1},outputs:{rye_flour:1},seconds:20,level:1},linen:{id:'linen',building:'loom',name:'Лён',inputs:{flax:1},outputs:{linen:1},seconds:20,level:1}};
function setup(o,{helpers={},helperCatalog={},animals={},canAfford=()=>true}={}){
 const p=new Node(),calls=[],notes=[],modals=[];
 const ctx={S:{selected:o.id,farm:{objects:[o]},me:{level:10,coins:100,inventory:{wheat:3},objects:[o],helpers},catalog:{animals:{},recipes,buildings:{},helpers:helperCatalog}},
  own:()=>true,heading:()=>{},objName:()=>'bakery',buildingPurpose:()=>[],lvlOf:()=>1,slotsOf:()=>5,now:()=>100,note:t=>notes.push(t),upgradeCard:()=>{},renderVisitActions:()=>{},speedOf:()=>1,
  el:(tag,text,cls)=>new Node(text,cls),card:()=>new Node(),goods:()=>new Node(),timer:()=>new Node(),itemName:x=>x,duration:x=>x,stock:()=>0,batchOf:()=>({inputs:{feed:1},outputs:{egg:1},seconds:20}),
  document:{createElementNS:()=>new Node()},checkbox:()=>[new Node(),new Node()],
  button:(text,fn,cls,disabled=false)=>{const n=new Node(text,cls);n.disabled=disabled;n.onclick=fn;return n;},command:(...a)=>calls.push(a),safe:fn=>fn,modal:(title,text,buttons)=>modals.push({title,text,buttons}),
  $:()=>({close(){}}),undoFull:()=>true,undoLeft:()=>0,undoRules:()=>({late_refund_pct:50}),inArea:()=>true,enough:canAfford};
 ctx.S.catalog.animals=animals;
 vm.createContext(ctx);vm.runInContext(code,ctx);return {ctx,p,calls,notes,modals};
}
const workshop=extra=>({id:'w1',type:'bakery',jobs:[],level:1,...extra});
test('each workshop batch exposes the same accessible repeat control before its action',()=>{
 const h=setup(workshop({recipes_memory:['bread','pie'],last_recipe:'pie'}));h.ctx.renderObject(h.p);
 assert.ok(h.notes.some(t=>t==='Автоповтор включён: Хлеб, Пирог.'),h.notes.join('|'));
 assert.ok(h.notes.some(t=>t.includes('ждёт мастера')&&t.includes('активной смене')&&t.includes('зоне')),h.notes.join('|'));
 assert.equal(h.notes.some(t=>t.includes('Мастер повторяет')),false);
 const o=workshop({jobs:[{id:'b',recipe:'bread',starts_at:100,ready_at:200},{id:'p',recipe:'pie',starts_at:100,ready_at:200}],recipes_memory:['bread']});
 const batch=setup(o);batch.ctx.renderObject(batch.p);const toggles=batch.p.all().filter(n=>/(^| )repeat-toggle( |$)/.test(n.className||''));
 assert.equal(toggles.length,2);assert.equal(toggles[0].getAttribute('aria-pressed'),'true');assert.equal(toggles[1].getAttribute('aria-pressed'),'false');
 assert.match(toggles[0].getAttribute('aria-label'),/Выключить автоповтор: Хлеб/);assert.match(toggles[1].getAttribute('aria-label'),/Включить автоповтор: Пирог/);
 const queue=batch.p.all().find(n=>n.className==='queue-job');assert.match(queue.children[0].className,/^repeat-toggle/);assert.equal(queue.children[1].textContent,'Отменить');
 toggles[1].onclick();assert.deepEqual(JSON.parse(JSON.stringify(batch.calls[0])),['set_recipe_repeat',{object:'w1',recipe:'pie',enabled:true}]);
});
test('repeat controls render for mill and loom without building-specific UI',()=>{
 for(const [type,recipe]of [['mill','rye_flour'],['loom','linen']]){
  const h=setup({id:type,type,jobs:[{id:'job',recipe,starts_at:100,ready_at:200}],level:1});h.ctx.renderObject(h.p);
  const toggle=h.p.all().find(n=>n.className==='repeat-toggle');assert.ok(toggle,type);assert.equal(toggle.getAttribute('aria-pressed'),'false');
  toggle.onclick();assert.deepEqual(JSON.parse(JSON.stringify(h.calls[0])),['set_recipe_repeat',{object:type,recipe,enabled:true}]);
 }
});
test('active repeat remains switchable when a recipe has no queued row',()=>{
 const h=setup(workshop({jobs:[{id:'p',recipe:'pie',starts_at:100,ready_at:200}],recipes_memory:['bread']}));h.ctx.renderObject(h.p);
 const chips=h.p.all().filter(n=>/(^| )repeat-toggle( |$)/.test(n.className||''));assert.equal(chips.length,2);
 const chip=chips.find(n=>n.getAttribute('aria-label')==='Выключить автоповтор: Хлеб');assert.ok(chip);chip.onclick();
 assert.deepEqual(JSON.parse(JSON.stringify(h.calls[0])),['set_recipe_repeat',{object:'w1',recipe:'bread',enabled:false}]);
});
test('duplicate rows for one recipe share the server repeat setting',()=>{
 const h=setup(workshop({jobs:[{id:'b1',recipe:'bread',starts_at:100,ready_at:200},{id:'b2',recipe:'bread',starts_at:200,ready_at:300}],recipes_memory:['bread']}));h.ctx.renderObject(h.p);
 const rows=h.p.all().filter(n=>n.className==='queue-job');assert.equal(rows.length,2);
 for(const row of rows){const toggle=row.children[0];assert.equal(toggle.getAttribute('aria-pressed'),'true');assert.match(toggle.getAttribute('aria-label'),/Выключить автоповтор: Хлеб/);}
});
test('empty repeat list and legacy last_recipe are presented clearly',()=>{
 let h=setup(workshop({recipes_memory:[]}));h.ctx.renderObject(h.p);
 assert.ok(h.notes.some(t=>t.includes('Автоповтор выключен')&&t.includes('стрелкой')));
 h=setup(workshop({last_recipe:'bread'}));h.ctx.renderObject(h.p);assert.ok(h.notes.some(t=>t==='Автоповтор включён: Хлеб.'));
});
test('only a craft helper with a live shift in its zone is shown as repeating now',()=>{
 const o=workshop({x:4,y:3,w:2,h:2,recipes_memory:['bread']});
 const h=setup(o,{helpers:{badger_artisan:{shift:{status:'working',until:200,remaining:5},zone:{x:3,y:3,w:4,h:3}}},helperCatalog:{badger_artisan:{role:'craft'}}});h.ctx.renderObject(h.p);
 assert.ok(h.notes.some(t=>t.includes('Мастер повторит включённые рецепты')&&t.includes('лимита действий')));
 for(const helpers of [
  {badger_artisan:{shift:{status:'stopped',until:200},zone:{x:3,y:3,w:4,h:3}}},
  {badger_artisan:{shift:{status:'working',until:99},zone:{x:3,y:3,w:4,h:3}}},
  {badger_artisan:{shift:{status:'working',until:200,remaining:0},zone:{x:3,y:3,w:4,h:3}}},
  {badger_artisan:{shift:{status:'working',until:200},zone:{x:10,y:10,w:2,h:2}}}
 ]){const inactive=setup(o,{helpers,helperCatalog:{badger_artisan:{role:'craft'}}});inactive.ctx.renderObject(inactive.p);assert.ok(inactive.notes.some(t=>t.includes('Повтор ждёт мастера')));}
 const nonMaster=setup(o,{helpers:{fox_picker:{shift:{status:'working',until:200}}},helperCatalog:{fox_picker:{role:'reap'}}});nonMaster.ctx.renderObject(nonMaster.p);assert.ok(nonMaster.notes.some(t=>t.includes('Повтор ждёт мастера')));
});
test('workshop explains queue and resource pauses without claiming that production is repeating',()=>{
 const helper={badger_artisan:{shift:{status:'working',until:200,remaining:5}}},helperCatalog={badger_artisan:{role:'craft'}};
 const full=setup(workshop({recipes_memory:['bread'],jobs:Array.from({length:5},(_,i)=>({id:String(i),recipe:'bread',starts_at:110,ready_at:150}))}),{helpers:helper,helperCatalog});
 full.ctx.renderObject(full.p);assert.ok(full.notes.some(t=>t.includes('ждёт свободного места')));
 const empty=setup(workshop({recipes_memory:['bread']}),{helpers:helper,helperCatalog,canAfford:()=>false});
 empty.ctx.renderObject(empty.p);assert.ok(empty.notes.some(t=>t.includes('ждёт сырьё')));
});
test('cancelling a batch never silently disables its repeat setting',()=>{
 const jobs=[{id:'a',recipe:'bread',starts_at:200,ready_at:300,inputs:{wheat:1}}];
 const h=setup(workshop({jobs,recipes_memory:['bread'],last_recipe:'bread'}));h.ctx.renderObject(h.p);
 const cancel=h.p.all().find(n=>n.textContent==='Отменить');cancel.onclick();assert.equal(h.modals.length,1);
 assert.match(h.modals[0].text,/Автоповтор останется включённым/);assert.equal(h.modals[0].buttons.length,1);
 h.modals[0].buttons[0].onclick();assert.deepEqual(JSON.parse(JSON.stringify(h.calls.at(-1))),['cancel_job',{object:'w1',job:'a'}]);
});
test('restart counter uses any affordable remembered recipe and the client has no recipe_changed handling',()=>{
 const o=workshop({recipes_memory:['cake','bread']});const h=setup(o);
 const z={};h.ctx.inArea=()=>true;const c=h.ctx.bulkCounts(z);assert.equal(c.restart,1,'cake is unaffordable, bread restarts');
 assert.equal(h.ctx.bulkCounts(z).restart,1);
 assert.equal(setup(workshop({recipes_memory:[]})).ctx.bulkCounts(z).restart,0);
 assert.doesNotMatch(source,/recipe_changed/);
});
test('remembered recipes are a list, not a single last setup',()=>{
 const h=setup(workshop({recipes_memory:['bread','pie']}));h.ctx.renderObject(h.p);
 assert.equal(h.notes.some(t=>t.includes('Повторяется последняя постановка')),false);
 assert.ok(h.notes.some(t=>t==='Автоповтор включён: Хлеб, Пирог.'));
 const h2=setup(workshop({recipes_memory:[]}));h2.ctx.renderObject(h2.p);assert.equal(h2.notes.some(t=>t.includes('Повторяется последняя')),false);
});
test('animal repeat is explicit, collection waits until ready, and repeat waits for an animal helper',()=>{
 const spec={id:'hen',building:'coop',name:'Куры',inputs:{feed:1},outputs:{egg:1},seconds:20};
 for(const job of [null,{ready_at:200,outputs:{egg:1}},{ready_at:50,outputs:{egg:1}}]){
  const o={id:'coop-1',type:'coop',jobs:[],level:1,animal:'hen',animal_job:job,animal_repeat:false};
  const h=setup(o,{animals:{hen:spec}});h.ctx.renderObject(h.p);
  assert.ok(h.notes.some(t=>t.includes('помощник-животновод на активной смене')));
  const toggle=h.p.all().find(n=>n.className==='repeat-toggle');assert.ok(toggle);assert.equal(toggle.getAttribute('aria-pressed'),'false');
  const actions=h.p.all().find(n=>n.className==='qw-btn-row animal-production-actions');assert.equal(actions.children[0],toggle);assert.equal(actions.children[1].textContent,job?'Забрать продукцию':'Накормить');if(job)assert.equal(actions.children[1].disabled,job.ready_at>100);
  toggle.onclick();assert.deepEqual(JSON.parse(JSON.stringify(h.calls[0])),['set_animal_repeat',{object:'coop-1',enabled:true}]);
 }
 const legacy=setup({id:'coop-2',type:'coop',jobs:[],level:1,animal:'hen',animal_job:null},{animals:{hen:spec}});
 legacy.ctx.renderObject(legacy.p);assert.equal(legacy.p.all().find(n=>/(^| )repeat-toggle( |$)/.test(n.className||'')).getAttribute('aria-pressed'),'true');
});
