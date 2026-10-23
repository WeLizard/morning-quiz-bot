// Leaving the village for a section (visiting guests, place signs) must close the village and keep the Back stack aligned.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(process.env.FARM_APP_JS||path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
const villageTest=fs.readFileSync(path.join(__dirname,'farm_village.test.cjs'),'utf8');
// Reuse the village harness (Node stub, setup()) of farm_village.test.cjs without duplicating it.
const harness=villageTest.slice(villageTest.indexOf('class Node{'),villageTest.indexOf('\ntest('));
const block=source.slice(source.indexOf('// Living village uses existing personal orders'),source.indexOf('/* ---- r9 stage 15B:'));
const declarations=source.slice(source.indexOf('const VILLAGE_VOICES='),source.indexOf('const fmt='));
const {setup}=new Function('fs','path','vm','source','block','declarations',harness+'\nreturn {setup};')(fs,path,vm,source,block,declarations);
const targets=[
 ...vm.runInNewContext('['+source.slice(source.indexOf('const VILLAGE_VISITORS=')+'const VILLAGE_VISITORS='.length,source.indexOf(';',source.indexOf('const VILLAGE_VISITORS='))+0)+']')[0].map(v=>['visitor '+v[0],v[5]]),
 ...vm.runInNewContext('['+source.slice(source.indexOf('const VILLAGE_EGGS=')+'const VILLAGE_EGGS='.length,source.indexOf('];',source.indexOf('const VILLAGE_EGGS='))+1)+']')[0].map(v=>['egg '+v[0],v[5]]),
 ...vm.runInNewContext('['+source.slice(source.indexOf('const VILLAGE_PLACES=')+'const VILLAGE_PLACES='.length,source.indexOf('];',source.indexOf('const VILLAGE_PLACES='))+1)+']')[0].map(v=>['place '+v[0],v[5]]),
];

test('guest and place buttons route through selectTab to a section that exists',()=>{
 assert.ok(targets.length>=7+7+6,'visitors, easter eggs and place signs are all collected');
 assert.match(source,/villageSheet==='visitor'[\s\S]{0,400}button\(v\[4\],\(\)=>selectTab\(v\[5\]\)/);
 assert.match(source,/villageGo\(\[x,y\+2\.4\],\(\)=>selectTab\(tab\),e\)/);
 const nav=fs.readFileSync(path.join(path.dirname(require.resolve('../../qw_farm/static/app.js')),'farm_nav.js'),'utf8');
 for(const [name,tab] of targets)assert.ok(nav.includes(`['${tab}','`)||source.includes(`${tab}:render`)||source.includes(`S.tab==='${tab}'`),`${name}: unknown section ${tab}`);
});

test('every guest and place sign leaves the village completely and opens its section',()=>{
 for(const [name,tab] of targets){
  const h=setup();h.S.tab='village';h.ctx.syncVillageScene();
  assert.equal(h.bodyClasses.has('village-open'),true,name);assert.equal(h.pause.at(-1),true,name);
  if(name.startsWith('visitor')||name.startsWith('egg'))h.ctx.openVillageVisitor(name.split(' ')[1]);
  const epoch=h.ctx.farmViewEpoch;
  h.ctx.selectTab(tab);
  assert.equal(h.S.tab,tab,name);
  assert.equal(h.ctx.villageVisible(),false,name);
  assert.equal(h.bodyClasses.has('village-open'),false,name);
  assert.equal(h.nodes.get('village-scene').hidden,true,name);
  assert.equal(h.nodes.get('farm-canvas').inert,false,name);
  assert.equal(h.pause.at(-1),false,`${name}: map scene must not stay paused`);
  assert.equal(h.bodyClasses.has('panel-open'),true,name);
  assert.ok(h.ctx.farmViewEpoch>epoch,name);
 }
});

// Minimal model of the shell back stack (web/shell/qw-shell.js nav) over a browser history whose go(n) is asynchronous.
function navHarness(){
 const hist={entries:[null],idx:0,listeners:new Set(),epoch:0,fired:0};
 const stack=[];let suppress=0;
 const win={
  pushState(state){hist.epoch++;/* a new entry cancels a traversal that is still queued */hist.entries.splice(hist.idx+1);hist.entries.push(state);hist.idx++;},
  go(n){const epoch=hist.epoch;setTimeout(()=>{if(epoch!==hist.epoch){suppress=Math.max(0,suppress-1);return;}hist.idx=Math.max(0,Math.min(hist.entries.length-1,hist.idx+n));hist.fired++;if(suppress>0){suppress--;}for(const f of [...hist.listeners])f();},0);},
 };
 const QW={config:{mode:'game'},nav:{
  push(e){if(stack.some(i=>i.id===e.id))return;stack.push({id:e.id,onBack:e.onBack});win.pushState({qwNav:e.id});},
  pop(id){const i=stack.findIndex(x=>x.id===id);if(i<0)return false;const removed=stack.length-i;stack.splice(i);suppress++;win.go(-removed);return true;},
  has(id){return stack.some(x=>x.id===id);},get depth(){return stack.length;}}};
 return {hist,stack,win,QW};
}
test('syncNav never pushes a history entry while a pop traversal is still in flight',async()=>{
 const nav=navHarness(),body=new Set();
 const ctx={QW:nav.QW,S:{me:{}},document:{body:{classList:{contains:k=>body.has(k)}}},returnToFarm(){},closePanel(){},
  villageVisible:()=>ctx.vv,own:()=>true,vv:false,addEventListener:(t,f)=>nav.hist.listeners.add(f),removeEventListener:(t,f)=>nav.hist.listeners.delete(f),setTimeout,clearTimeout};
 vm.createContext(ctx);
 vm.runInContext(source.slice(source.indexOf('function navPush('),source.indexOf('new MutationObserver(syncNav)')),ctx);
 const aligned=()=>nav.hist.idx===nav.stack.length;
 // 1) village opens, then a guest sheet over it (stack: village, panel)
 ctx.vv=true;ctx.syncNav();body.add('panel-open');ctx.syncNav();
 assert.deepEqual(nav.stack.map(e=>e.id),['village','panel']);assert.ok(aligned());
 // 2) guest button: village closes, the section panel stays open
 ctx.vv=false;ctx.syncNav();
 await new Promise(r=>setTimeout(r,20));
 assert.deepEqual(nav.stack.map(e=>e.id),['panel']);
 assert.equal(nav.hist.idx,nav.stack.length,'history position matches the stack (a drift makes Back leave the farm)');
 // 3) place sign: village only (stack: village) -> section panel opens in the same tick
 body.clear();nav.stack.length=0;nav.hist.entries=[null];nav.hist.idx=0;
 ctx.vv=true;ctx.syncNav();assert.ok(aligned());
 ctx.vv=false;body.add('panel-open');ctx.syncNav();
 await new Promise(r=>setTimeout(r,20));
 assert.deepEqual(nav.stack.map(e=>e.id),['panel']);assert.equal(nav.hist.idx,1);
 // Back closes the panel: history returns to the base entry, not before it
 body.delete('panel-open');ctx.syncNav();await new Promise(r=>setTimeout(r,20));
 assert.equal(nav.stack.length,0);assert.equal(nav.hist.idx,0);
});
