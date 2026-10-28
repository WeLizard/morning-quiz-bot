const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/tractor_game.js'),'utf8').replace(/export (const|function|class) /g,'$1 ');
const names='DEFAULTS simulate simulateSpray Run qualityFull conditionQuality sprayBonus yieldQty gameCfg RULES_TURN RULES_FULL reachableOrientCells stepAnchorOrient'.split(' ');
const ctx={Set,Map,Math,Object,String,Array,Number,performance:{now:()=>0}};vm.createContext(ctx);vm.runInContext(source+`\nglobalThis.api={${names.join(',')}};`,ctx);
const api=ctx.api;
const data=JSON.parse(fs.readFileSync(path.join(__dirname,'../fixtures/farm_fields_rules3/full.json'),'utf8'));
const k=data.constants;
const cfg={...api.DEFAULTS,hopper:k.hopper,tank:k.tank,tankChunks:k.tank_chunks,hitDamage:k.hit_damage,hitRepair:k.hit_repair,condPenalty:k.cond_penalty};

test('rules=3: every fixture path matches the server, including damage, spray and partial transfer',()=>{
 assert.ok(data.cases.length>=60);
 for(const c of data.cases){
  const field={w:c.field.w,h:c.field.h};
  const r=new api.Run(field,c.run,cfg);
  let ok=true;
  for(const ch of c.path)if(!r.push(ch)){ok=false;break;}
  if(c.result===null){assert.equal(ok,false,`${c.name}: JS accepted a path the server rejects`);continue;}
  assert.equal(ok,true,`${c.name}: JS rejected a valid path`);
  assert.equal(r.score(),c.result.score,`${c.name}: score`);
  assert.equal(r.condition,c.result.condition,`${c.name}: condition`);
  assert.equal(r.hits,c.result.hits,`${c.name}: hits`);
  assert.equal(r.repair,c.result.repair,`${c.name}: repair`);
  if('load' in c.result)assert.equal(r.load,c.result.load,`${c.name}: load`);
  const one=api.simulate(field,c.run,c.path,cfg);
  assert.equal(one,c.result.score,`${c.name}: one-shot`);
 }
});

test('rules=3: full economy helpers match the server formulas',()=>{
 assert.equal(api.RULES_FULL,3);
 assert.equal(api.qualityFull(0),850);assert.equal(api.qualityFull(1000),1250);
 assert.equal(api.conditionQuality(1250,97),1238);assert.equal(api.conditionQuality(1250,0),850);
 assert.equal(api.sprayBonus(850),1000);assert.equal(api.sprayBonus(900),1025);assert.equal(api.sprayBonus(1250),1200);
 assert.equal(api.yieldQty(80,1250,1250),125);assert.equal(api.yieldQty(80,1250,1250,1200),150);
 assert.equal(api.reachableOrientCells(8,8,2,new Set()).size,64);
});
