const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
// trip_game.js is an ES module: pure rules first, DOM only inside openTripGame (never called here). Imports are stubbed.
const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/trip_game.js'),'utf8').replace(/^import .*$/mg,'').replace(/export (const|function|class) /g,'$1 ');
const names='RULES FISH2 markPosition accuracy strikeTiming fishScore fishResult forageScore walk scaledOutputs quality finalOutputs canPlay playLeft bonusLine evalCast fight fightStart fightStep holdAt biteAt baitSpec hookedFish nibbleTimes skyLine grams fightPoints'.split(' ');
const ctx={Set,Map,Math,Object,String,Array,Number,JSON,performance:{now:()=>0},smallAnimal:()=>{}};vm.createContext(ctx);vm.runInContext(source+`\nglobalThis.api={${names.join(',')}};`,ctx);
const api=ctx.api;
const data=JSON.parse(fs.readFileSync(path.join(__dirname,'../fixtures/farm_trip_games/games.json'),'utf8'));
const plain=x=>JSON.parse(JSON.stringify(x));
const planOf=c=>c.plan_ref?data.plans[c.plan_ref]:c.plan;

test('rules shipped by the server equal the client defaults',()=>{
 for(const k of ['bonus','mark_period','dead_zone','acc_span','react','first_aim_ms','grid','trap_cost','step_cs'])assert.equal(api.RULES[k],data.rules[k],k);
 assert.deepEqual(plain(api.FISH2),data.rules.fish2);
});

test(`JS score equals the server score on every fixture (${data.cases.length} cases)`,()=>{
 assert.ok(data.cases.length>100);
 for(const c of data.cases){
  const got=c.kind==='fish'?api.fishScore(planOf(c),c.log,data.rules):api.forageScore(planOf(c),c.log);
  assert.equal(got,c.score,c.name);
 }
});

test('fishing v2: every cast outcome, end, pause and the catch match the server replay',()=>{
 const fish=data.cases.filter(c=>c.kind==='fish');
 assert.ok(fish.length>=90);
 for(const c of fish){
  const r=api.fishResult(planOf(c),c.log,data.rules);
  if(c.results===null){assert.equal(r,null,c.name);continue;}
  assert.deepEqual(plain(r.casts.map(x=>[x.result,x.points,x.end,x.free,x.fish&&x.fish.id])),c.results,c.name);
  assert.deepEqual(plain(r.catch),c.catch,c.name);
 }
 const kinds=new Set(fish.flatMap(c=>(c.results||[]).map(r=>r[0])));
 for(const k of ['land','snap','escape','early','missed'])assert.ok(kinds.has(k),k);
 assert.ok(fish.some(c=>(c.catch||[]).some(([id])=>data.rules.fish2.species[id].rare)),'a rare fish is in the fixtures');
});

test('both kinds have scored and rejected fixtures, including a perfect forest walk',()=>{
 for(const kind of ['fish','forage']){
  const rows=data.cases.filter(c=>c.kind===kind);
  assert.ok(rows.some(c=>c.score===null),kind+' rejected');assert.ok(rows.some(c=>c.score>0),kind+' scored');
 }
 assert.ok(data.cases.some(c=>c.kind==='forage'&&c.score===1000));
});

test('scaled outputs and quality match the server table',()=>{
 for(const o of data.outputs)assert.deepEqual(plain(api.scaledOutputs(o.base,o.q)),o.out,JSON.stringify(o));
 assert.equal(api.quality(0),1000);assert.equal(api.quality(1000),1250);assert.equal(api.quality(500),1125);
});

test('strike window: instant strike best, scared before the human floor, gone after the window',()=>{
 const bite=2800;
 assert.equal(api.strikeTiming(bite+149,bite,900),0);assert.equal(api.strikeTiming(bite+150,bite,900),1000);
 assert.equal(api.strikeTiming(bite+1050,bite,900),500);assert.equal(api.strikeTiming(bite+1051,bite,900),0);
 const mark=api.markPosition(800,0,api.RULES,1250);assert.equal(api.accuracy(800,{phase:0,zone:mark},api.RULES,1250),1000);
});

test('fight: hold/release toggles, a holding player snaps a pike, a released line goes slack or the fish leaves',()=>{
 assert.equal(api.holdAt([],100),true);assert.equal(api.holdAt([100],100),false);assert.equal(api.holdAt([100,300],250),false);assert.equal(api.holdAt([100,300],300),true);
 const pike={id:'pike',g:2000,pulls:[[10,10],[6,31],[30,68],[20,10],[6,31],[30,68]]};
 assert.equal(api.fight(pike,0,[]).end,'snap');
 assert.ok(['slack','escape'].includes(api.fight(pike,0,[60]).end));
 const crucian={id:'crucian',g:200,pulls:[[20,10],[8,40]]};
 const r=api.fight(crucian,0,[]);assert.equal(r.end,'land');assert.equal(api.fightPoints(r.ticks,90),1000);
});

test('sky line and weights read naturally',()=>{
 assert.match(api.skyLine({sky:{tod:'dusk',weather:'rain'}}),/Вечерняя зорька · дождик: клюёт быстрее/);
 assert.equal(api.grams(340),'340 г');assert.equal(api.grams(2450),'2,5 кг');
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
 assert.deepEqual(plain(api.finalOutputs(done)),{x:4});
 assert.match(api.bonusLine(done,id=>id),/x \+1/);assert.equal(api.bonusLine({outputs:{x:3},game:{state:'done',q:1000}},id=>id),'Как у автопилота');
});
