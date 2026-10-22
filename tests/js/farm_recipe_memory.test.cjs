const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../../qw_farm/static/app.js'),'utf8');
const fn=name=>{const a=source.indexOf(`function ${name}(`);let d=0,k=source.indexOf('{',a);for(;;k++){if(source[k]==='{')d++;else if(source[k]==='}'&&--d===0)break;}return source.slice(a,k+1)+';\n';};
const code=source.slice(source.indexOf('function renderObject(p)'),source.indexOf('async function visit(id)'))+['recipeMemory','bulkCounts','jobRefund','confirmCancelJob'].map(fn).join('');
class Node{constructor(text,cls){this.textContent=text;this.className=cls;this.children=[];this.dataset={};}append(...n){this.children.push(...n);}all(){return this.children.flatMap(c=>c instanceof Node?[c,...c.all()]:[]);}}
const recipes={bread:{id:'bread',building:'bakery',name:'Хлеб',inputs:{wheat:1},outputs:{bread:1},seconds:20,level:1},pie:{id:'pie',building:'bakery',name:'Пирог',inputs:{wheat:2},outputs:{pie:1},seconds:30,level:1},cake:{id:'cake',building:'bakery',name:'Торт',inputs:{wheat:9},outputs:{cake:1},seconds:30,level:5}};
function setup(o){
 const p=new Node(),calls=[],notes=[],modals=[];
 const ctx={S:{selected:o.id,farm:{objects:[o]},me:{level:10,coins:100,inventory:{wheat:3},objects:[o]},catalog:{animals:{},recipes,buildings:{}}},
  own:()=>true,heading:()=>{},objName:()=>'bakery',buildingPurpose:()=>[],lvlOf:()=>1,slotsOf:()=>5,now:()=>100,note:t=>notes.push(t),upgradeCard:()=>{},renderVisitActions:()=>{},enough:()=>true,speedOf:()=>1,
  el:(tag,text,cls)=>new Node(text,cls),card:()=>new Node(),goods:()=>new Node(),timer:()=>new Node(),itemName:x=>x,duration:x=>x,
  button:(text,fn,cls)=>{const n=new Node(text,cls);n.onclick=fn;return n;},command:(...a)=>calls.push(a),safe:fn=>fn,modal:(title,text,buttons)=>modals.push({title,text,buttons}),
  $:()=>({close(){}}),undoFull:()=>true,undoLeft:()=>0,undoRules:()=>({late_refund_pct:50}),inArea:()=>true};
 vm.createContext(ctx);vm.runInContext(code,ctx);return {ctx,p,calls,notes,modals};
}
const workshop=extra=>({id:'w1',type:'bakery',jobs:[],level:1,...extra});
test('workshop lists remembered recipes in order with one forget control each',()=>{
 const h=setup(workshop({recipes_memory:['bread','pie'],last_recipe:'pie'}));h.ctx.renderObject(h.p);
 assert.ok(h.notes.some(t=>t.startsWith('Мастер повторяет: Хлеб, Пирог')),h.notes.join('|'));
 const forgets=h.p.all().filter(n=>/(^| )forget-recipe( |$)/.test(n.className||''));
 assert.deepEqual(forgets.map(n=>n.dataset.recipe),['bread','pie']);
 forgets[0].onclick();assert.deepEqual(JSON.parse(JSON.stringify(h.calls[0])),['forget_recipe',{object:'w1',recipe:'bread'}]);
 assert.equal(h.p.all().some(n=>n.textContent==='Забыть рецепт'),false,'single forget button is gone');
});
test('empty memory shows no line and no forget controls; legacy last_recipe still works',()=>{
 let h=setup(workshop({recipes_memory:[]}));h.ctx.renderObject(h.p);
 assert.equal(h.notes.some(t=>t.includes('Мастер повторяет')),false);assert.equal(h.p.all().some(n=>/(^| )forget-recipe( |$)/.test(n.className||'')),false);
 h=setup(workshop({last_recipe:'bread'}));h.ctx.renderObject(h.p);assert.ok(h.notes.some(t=>t.startsWith('Мастер повторяет: Хлеб')));
});
test('cancel-and-forget is offered for every queued job whose recipe is remembered',()=>{
 const jobs=[{id:'a',recipe:'bread',starts_at:200,ready_at:300,inputs:{wheat:1}},{id:'b',recipe:'pie',starts_at:200,ready_at:300,inputs:{wheat:2}}];
 const h=setup(workshop({jobs,recipes_memory:['bread'],last_recipe:'bread'}));h.ctx.renderObject(h.p);
 const cancels=h.p.all().filter(n=>n.textContent==='Отменить');assert.equal(cancels.length,2);
 cancels[0].onclick();assert.equal(h.modals.length,1,'remembered (queued) recipe asks first');
 assert.ok(h.modals[0].buttons.some(b=>b.textContent==='Отменить и забыть рецепт'));
 h.modals[0].buttons.find(b=>b.textContent==='Отменить и забыть рецепт').onclick();
 return Promise.resolve().then(()=>{assert.deepEqual(JSON.parse(JSON.stringify(h.calls.at(-1))),['cancel_job_and_forget_recipe',{object:'w1',job:'a'}]);
  cancels[1].onclick();assert.equal(h.calls.at(-1)[0],'cancel_job','unremembered queued job cancels directly');});
});
test('restart counter uses any affordable remembered recipe and the client has no recipe_changed handling',()=>{
 const o=workshop({recipes_memory:['cake','bread']});const h=setup(o);
 const z={};h.ctx.inArea=()=>true;const c=h.ctx.bulkCounts(z);assert.equal(c.restart,1,'cake is unaffordable, bread restarts');
 assert.equal(h.ctx.bulkCounts(z).restart,1);
 assert.equal(setup(workshop({recipes_memory:[]})).ctx.bulkCounts(z).restart,0);
 assert.doesNotMatch(source,/recipe_changed/);
});
