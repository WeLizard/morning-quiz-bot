const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
// trip_game.js is an ES module: pure rules first, DOM only inside openTripGame (never called here, except with a tiny fake DOM below).
const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/trip_game.js'),'utf8').replace(/export (const|function|class) /g,'$1 ');
const names='RULES markPosition accuracy strikeScore fishScore forageScore walk scaledOutputs quality finalOutputs canPlay playLeft bonusLine castScore castEnd'.split(' ');
const ctx={Set,Map,Math,Object,String,Array,Number,performance:{now:()=>0}};vm.createContext(ctx);vm.runInContext(source+`\nglobalThis.api={${names.join(',')}};`,ctx);
const api=ctx.api;
const data=JSON.parse(fs.readFileSync(path.join(__dirname,'../fixtures/farm_trip_games/games.json'),'utf8'));

test('rules shipped by the server equal the client defaults',()=>{
 for(const k of ['bonus','mark_period','dead_zone','acc_span','react','first_aim_ms','grid','trap_cost','step_cs'])assert.equal(api.RULES[k],{...data.rules,first_aim_ms:data.rules.first_aim_ms}[k],k);
});

test(`JS score equals the server score on every fixture (${data.cases.length} cases)`,()=>{
 assert.ok(data.cases.length>100);
 for(const c of data.cases){
  const got=c.kind==='fish'?api.fishScore(c.plan,c.log,data.rules):api.forageScore(c.plan,c.log);
  assert.equal(got,c.score,c.name);
 }
});

test('both kinds have scored and rejected fixtures, including a perfect forest walk',()=>{
 for(const kind of ['fish','forage']){
  const rows=data.cases.filter(c=>c.kind===kind);
  assert.ok(rows.some(c=>c.score===null),kind+' rejected');assert.ok(rows.some(c=>c.score>0),kind+' scored');
 }
 assert.ok(data.cases.some(c=>c.kind==='forage'&&c.score===1000));
});

test('scaled outputs and quality match the server table',()=>{
 for(const o of data.outputs)assert.deepEqual(JSON.parse(JSON.stringify(api.scaledOutputs(o.base,o.q))),o.out,JSON.stringify(o));
 assert.equal(api.quality(0),1000);assert.equal(api.quality(1000),1250);assert.equal(api.quality(500),1125);
});

test('strike window and aiming accuracy',()=>{
 const bite=2800;
 assert.equal(api.strikeScore(bite,bite,900),0);assert.equal(api.strikeScore(bite+149,bite,900),0);assert.equal(api.strikeScore(bite+1051,bite,900),0);
 assert.equal(api.strikeScore(bite+150+450,bite,900),1000);assert.ok(api.strikeScore(bite+150,bite,900)>0);
 const mark=api.markPosition(800,0);assert.equal(api.accuracy(800,{phase:0,zone:mark,wait:2000}),1000);
});

test('walk: undo-friendly, traps cost two extra steps once, budget enforced',()=>{
 const plan={w:6,h:6,start:30,budget:4,items:{24:'a',18:'a'},traps:[25],gold:2};
 assert.equal(api.walk(plan,'UU').got,2);assert.equal(api.walk(plan,'UR').used,4);assert.equal(api.walk(plan,'URL'),null);
 assert.equal(api.walk(plan,'D'),null);assert.equal(api.walk(plan,'UUUUU'),null);assert.equal(api.walk(plan,'Z'),null);
 assert.equal(api.forageScore(plan,'U'),500);
});

test('canPlay: only the player\'s own open game with time left; bonusLine words',()=>{
 const t={guide:'',outputs:{x:3},game:{state:'open',expires_at:1000,q:1000}};
 assert.equal(api.canPlay(t,900),true);assert.equal(api.canPlay(t,998),false);assert.equal(api.canPlay({...t,guide:'g'},900),false);
 assert.equal(api.canPlay({guide:'',outputs:{}},900),false);assert.equal(api.canPlay({...t,game:{...t.game,state:'done'}},900),false);
 const done={outputs:{x:3},game:{state:'done',q:1250}};
 assert.deepEqual(JSON.parse(JSON.stringify(api.finalOutputs(done))),{x:4});
 assert.match(api.bonusLine(done,id=>id),/x \+1/);assert.equal(api.bonusLine({outputs:{x:3},game:{state:'done',q:1000}},id=>id),'Как у автопилота');
});
