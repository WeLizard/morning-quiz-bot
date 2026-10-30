const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
// "Валка" (felling): the client replay must equal the server replay on tests/fixtures/farm_trip_games/fell.json (built by trip_games.fell_result).
const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/trip_game.js'),'utf8').replace(/^import .*$/mg,'').replace(/export (const|function|class) /g,'$1 ');
const names='RULES FELL markPosition fellAccuracy fellStart fellStep fellTree fellResult fellScore fellQuality fellHinge fellPinched pinchMarks scaledOutputs'.split(' ');
const ctx={Set,Map,Math,Object,String,Array,Number,JSON,performance:{now:()=>0},smallAnimal:()=>{},drawFellScene:()=>{},fellVerdict:()=>({}),FELL_ANIM:{fall_ms:1000,result_ms:1600}};
vm.createContext(ctx);vm.runInContext(source+`\nglobalThis.api={${names.join(',')}};`,ctx);
const api=ctx.api,data=JSON.parse(fs.readFileSync(path.join(__dirname,'../fixtures/farm_trip_games/fell.json'),'utf8'));
const plain=x=>JSON.parse(JSON.stringify(x));

test('felling rules shipped by the server equal the client defaults',()=>{
 assert.deepEqual(plain(api.FELL),data.rules);
 assert.equal(api.RULES.fell,api.FELL);
});

test(`felling: score and every tree match the server replay (${data.cases.length} cases)`,()=>{
 assert.ok(data.cases.length>=27);
 for(const c of data.cases){
  const plan=data.plans[c.plan_ref],r=api.fellResult(plan,c.log,data.rules);
  if(c.score===null){assert.equal(r,null,c.name);assert.equal(api.fellScore(plan,c.log,data.rules),null,c.name);continue;}
  assert.ok(r,c.name);
  assert.equal(r.score,c.score,c.name);assert.equal(r.end,c.end,c.name);
  assert.deepEqual(plain(r.trees.map(t=>[t.acc,t.cut,t.points,t.result,t.stalled,t.ticks,t.end,t.free])),c.trees,c.name);
 }
});

test('felling fixtures cover every outcome and the rejected logs',()=>{
 const res=new Set(data.cases.flatMap(c=>c.trees||[]).map(t=>t[3]));
 for(const k of ['felled','cut_through','timeout','idle'])assert.ok(res.has(k),k);
 assert.ok(data.cases.some(c=>(c.trees||[]).some(t=>t[4])),'a stalled saw');
 assert.ok(data.cases.some(c=>c.score===null)&&data.cases.some(c=>c.score===1000));
});

test('felling quality is x1.0..x1.6 and feeds the shared output scaling',()=>{
 assert.equal(api.fellQuality(0,{fell:data.rules}),1000);assert.equal(api.fellQuality(1000,{fell:data.rules}),1600);assert.equal(api.fellQuality(500),1300);
 assert.deepEqual(plain(api.scaledOutputs({wood:10},1600)),{wood:16});assert.deepEqual(plain(api.scaledOutputs({wood:10},1000)),{wood:10});
});

test('live stepping equals the replay: the same toggles give the same tree',()=>{
 for(const c of data.cases.filter(c=>c.score!==null)){
  const plan=data.plans[c.plan_ref];
  c.log.trees.forEach(([aim,toggles],i)=>{
   if(!toggles.length)return;
   const tree=plan.trees[i],r=api.fellTree(tree,aim,toggles,data.rules),st=api.fellStart();
   // live mode: waiting for a later toggle is not a timeout; every other ending is identical
   while(!st.result)api.fellStep(st,tree,toggles[0],toggles,true,data.rules);
   if(r.result==='timeout')assert.equal(st.result,'timeout',c.name);   // live waits up to max_ticks, the replay ends at the last release
   else{assert.equal(st.result,r.result,c.name);assert.equal(st.k,r.ticks,c.name);}
  });
 }
});

test('pinch marks are cut positions inside 0..1000, in order',()=>{
 for(const plan of Object.values(data.plans))for(const tree of plan.trees){
  const m=api.pinchMarks(tree,data.rules);assert.equal(m.length,tree.pinches.length);
  m.forEach((x,i)=>{assert.ok(x>=0&&x<=1000);if(i)assert.ok(x>=m[i-1]);});
 }
});
