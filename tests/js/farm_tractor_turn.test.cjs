const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/tractor_game.js'),'utf8').replace(/export (const|function|class) /g,'$1 ');
const names='DEFAULTS simulate RULES_TURN stepAnchorOrient'.split(' ');
const ctx={Set,Map,Math,Object,String,Array,performance:{now:()=>0}};vm.createContext(ctx);vm.runInContext(source+`\nglobalThis.api={${names.join(',')}};`,ctx);
const api=ctx.api;
const data=JSON.parse(fs.readFileSync(path.join(__dirname,'../fixtures/farm_fields_turn/turn.json'),'utf8'));

test('rules=2 turn/per-cell scores match the server fixture',()=>{
 assert.ok(data.cases.length>=8);
 for(const c of data.cases){
  assert.equal(api.simulate(c.field,c.run,c.path),c.score,c.name);
 }
});

test('legacy runs reject the new T character',()=>{
 for(const c of data.cases.filter(c=>c.name.includes('legacy')&&c.path.includes('T'))){
  assert.equal(api.simulate(c.field,c.run,c.path),null,c.name);
 }
});
