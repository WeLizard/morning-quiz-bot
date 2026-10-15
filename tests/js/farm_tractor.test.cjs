const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
// tractor_game.js is an ES module: pure rules first, DOM only inside openFieldGame (never called here).
const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/tractor_game.js'),'utf8').replace(/export (const|function|class) /g,'$1 ');
const names='DEFAULTS simulate simulateCultivate simulateSow simulateHarvest Run quality growthPermille yieldQty autoSeconds maxPath reachableAnchors effectLines timedQuality timeKeep timeLimits gameCfg QRULE_TIMED'.split(' ');
const ctx={Set,Map,Math,Object,String,Array,performance:{now:()=>0}};vm.createContext(ctx);vm.runInContext(source+`\nglobalThis.api={${names.join(',')}};`,ctx);
const api=ctx.api;
const dir=path.join(__dirname,'../fixtures/farm_fields');
const files=fs.readdirSync(dir).filter(f=>f.endsWith('.json')).sort();

test('fixtures exist for all three operations',()=>{assert.deepEqual(files,['cultivate.json','harvest.json','sow.json']);});

for(const file of files){
 const data=JSON.parse(fs.readFileSync(path.join(dir,file),'utf8'));
 const sim={cultivate:api.simulateCultivate,sow:api.simulateSow,harvest:api.simulateHarvest}[data.op];
 test(`${data.op}: JS estimate equals the server estimate on every fixture (${data.cases.length} cases)`,()=>{
  assert.ok(data.cases.length>0);
  const cfg={...api.DEFAULTS,hopper:data.constants.hopper};
  for(const c of data.cases){
   const field={w:c.field.w,h:c.field.h};
   const got=sim(field,c.run,c.path,cfg);
   assert.equal(got,c.score,`${data.op} / ${c.name}`);
  }
 });
}

test('incremental Run (what the game shows) agrees with the one-shot estimate, and undo restores the state',()=>{
 for(const file of files){
  const data=JSON.parse(fs.readFileSync(path.join(dir,file),'utf8'));
  for(const c of data.cases.filter(c=>c.score!==null)){
   const r=new api.Run({w:c.field.w,h:c.field.h},{...c.run,op:data.op},{...api.DEFAULTS,hopper:data.constants.hopper});
   for(const ch of c.path)assert.equal(r.push(ch),true);
   assert.equal(r.score(),c.score,c.name);
   if(c.path.length){r.undo();assert.equal(r.path.length,c.path.length-1);assert.equal(r.push(c.path.at(-1)),true);assert.equal(r.score(),c.score,c.name+' after undo');}
  }
 }
});

test('illegal moves are refused without changing the run',()=>{
 const r=new api.Run({w:8,h:8},{op:'harvest',width:1,rocks:[],weeds:[]});
 assert.equal(r.push('U'),false);assert.equal(r.push('X'),true);r.push('D');assert.equal(r.push('X'),false);assert.equal(r.path,'XD');
 const s=new api.Run({w:8,h:8},{op:'sow',width:1,rocks:[],weeds:[]});assert.equal(s.push('X'),false);
});

test('derived numbers follow the server formulas',()=>{
 assert.equal(api.quality(0),850);assert.equal(api.quality(1000),1100);assert.equal(api.quality(500),975);
 assert.equal(api.growthPermille(1100),850);assert.equal(api.growthPermille(950),1000);
 assert.equal(api.autoSeconds(1,1),90);assert.equal(api.autoSeconds(3,2),135);assert.equal(api.autoSeconds(1,3,60),1);
 assert.equal(api.yieldQty(1000,1000,1000),1000);assert.equal(api.yieldQty(1,1,1),1);
 assert.equal(api.maxPath({w:8,h:8},{width:1}),192);assert.equal(api.maxPath({w:8,h:24},{width:1}),576);
});

test('timed quality equals the server formula on every fixture point (qw_farm/fields.py timed_quality)',()=>{
 const data=JSON.parse(fs.readFileSync(path.join(__dirname,'../fixtures/farm_fields_timed/timed.json'),'utf8'));
 const k=data.constants,cfg={...api.DEFAULTS,qBase:k.q_base,qSpan:k.q_span,qAuto:k.q_auto,autoS:k.auto_s,fullK:k.run_full_k,zeroK:k.run_zero_k};
 assert.ok(data.cases.length>300);
 for(const c of data.cases)assert.equal(api.timedQuality(c.score,c.elapsed,c.ha,c.width,cfg),c.q,JSON.stringify(c));
 assert.equal(api.QRULE_TIMED,2);
});

test('time keeps the whole bonus up to 2.5x the autopilot time, melts linearly, and is zero from 6x',()=>{
 assert.deepEqual({...api.timeLimits(1,1)},{auto:90,full:225,zero:540});
 assert.deepEqual([0,225,226,382,539,540,9999].map(t=>api.timeKeep(t,1,1)),[1000,1000,996,501,3,0,0]);
 assert.deepEqual([0,60,225,226,380,539,540,9999].map(t=>api.timedQuality(1000,t,1,1)),[1100,1100,1100,1099,1026,950,950,950]);
 assert.equal(api.timedQuality(0,9999,1,1),850);assert.equal(api.timedQuality(400,9999,1,1),950);
});

test('catalog keys reach the game config; missing keys fall back to the decided numbers',()=>{
 const c=api.gameCfg({run_ttl:1800,run_full_k:300,run_zero_k:700});
 assert.equal(c.runTtl,1800);assert.equal(c.fullK,300);assert.equal(c.zeroK,700);
 const d=api.gameCfg(null);assert.equal(d.runTtl,1800);assert.equal(d.fullK,250);assert.equal(d.zeroK,600);
});
