// E27 softening, client side (docs/tasks/FARM_ECONOMY_SOFTENING.md §8): demolition refund text, late uprooting, cancel-sowing button, compost heap upgrade.
// Parity with the server: tests/fixtures/farm_refund/parity.json is written by make_parity.py from qw_farm.undo (regenerate after changing the canon).
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');

const ROOT=path.join(__dirname,'../..');
const STATIC=path.join(ROOT,'qw_farm/static');
const load=name=>import(pathToFileURL(path.join(STATIC,name)).href);
const read=f=>fs.readFileSync(path.join(ROOT,f),'utf8');
const parity=JSON.parse(read('tests/fixtures/farm_refund/parity.json'));

test('demolition refund repeats the server formula on every building, level and age (parity sweep)',async()=>{
 const R=await load('orchard.js');
 assert.ok(parity.cases.length>300);
 for(const c of parity.cases){
  const got=R.demolishRefund(parity.catalog,c.obj,c.now);
  assert.deepEqual({refund:got.refund,goods:got.goods,full:got.full,wood:got.wood,xp:got.xp},c.expect,c.name);
 }
});

test('the numbers a player sees in the demolition dialog: late half with goods and wood, the first minute in full, the XP warning',async()=>{
 const R=await load('orchard.js'),cat=parity.catalog,T=5000;
 const late=R.demolishText(cat,{type:'creamery',level:2,paid:4500,built_at:T-3600},T,'Молокозавод');
 assert.ok(late.includes('50% вложенного')&&late.includes('древесина ×5'),late);
 const upg=cat.upgrades.levels[2];
 const upgradeCoins=Math.max(upg.coin_min,Math.round(4500*upg.coin_factor/10)*10);
 assert.ok(late.includes(`+${Math.floor((4500+upgradeCoins)/2)} монет`),late);
 for(const [k,q] of Object.entries(upg.items))assert.ok(late.includes(`${cat.items[k].name} ×${Math.floor(q/2)}`)||Math.floor(q/2)===0,late);
 const fresh=R.demolishText(cat,{type:'creamery',paid:4500,built_at:T-20,build_xp:5},T,'Молокозавод');
 assert.ok(fresh.includes('+4500')&&fresh.includes('полностью')&&fresh.includes('Опыт за постройку (5) снимется'),fresh);
 assert.ok(!fresh.includes('древесина'),fresh);
 const bench=R.demolishText(cat,{type:'bench',paid:45,built_at:T-3600,build_xp:5},T,'Скамейка');      // decor is refunded too, the XP always comes back
 assert.ok(bench.includes('+22 монет')&&bench.includes('Опыт за постройку (5) снимется'),bench);
 const bed=R.demolishText(cat,{type:'plot',paid:35,built_at:T-3600},T,'Грядка');
 assert.ok(bed.includes('+17 монет'),bed);
 const starter=R.demolishText(cat,{id:'plot_1',type:'plot'},T,'Грядка');
 assert.ok(starter.includes('не возвращаются'),starter);
});

test('an old save without price records is refunded from the catalog price; a tie rounds like Python (half to even)',async()=>{
 const R=await load('orchard.js');
 const cat={undo:{window:60,late_refund_pct:50},buildings:{shop:{cost:30,decor:false}},upgrades:{max:3,base_cost:400,levels:{2:{coin_factor:.5,coin_min:1},3:{coin_factor:1,coin_min:1}}}};
 assert.equal(R.upgradeCoins(cat,'shop',2),20,'30*0.5/10 = 1.5 -> 2');
 const cat2={...cat,buildings:{shop:{cost:50,decor:false}}};
 assert.equal(R.upgradeCoins(cat2,'shop',2),20,'50*0.5/10 = 2.5 -> 2');
 assert.equal(R.demolishRefund(cat,{type:'shop'},1000).refund,15);
});

test('late uprooting names half of the sapling price and the wood; the first minute stays whole',async()=>{
 const O=await load('orchard.js');
 const cat={undo:{window:60,late_refund_pct:50},orchard:{trees:{apple:{name:'Яблоня'}},rules:{}}};
 const tree={species:'apple',planted_at:1000,cost:2301};
 const late=O.uprootText(cat,tree,1000+3600,60);
 assert.ok(!late.early&&late.refund===1150&&late.text.includes('+1150 монет')&&late.text.includes('древесина ×2'),late.text);
 const free=O.uprootText(cat,{...tree,cost:0},1000+3600,60);
 assert.ok(!free.text.includes('монет')&&free.text.includes('древесина ×2'),free.text);
 assert.ok(O.uprootText(cat,tree,1030,60).early);
});

test('cancel sowing: visible for the first 60 seconds of an open or autopilot run and of a fresh crop; amounts from the record or the catalog',async()=>{
 const R=await load('orchard.js'),cat=parity.catalog,crop=Object.keys(cat.crops)[0];
 const F={id:'f1',ha:2,revision:7,state:'ready',crop:null};
 const run=(status,at,extra={})=>({...F,run:{op:'sow',status,crop,started_at:at,...extra}});
 const seeds=cat.crops[crop].cost*cat.fields.seed_mult*2,fuel=cat.fields.fuel*2;
 for(const status of ['open','auto']){
  const a=R.cancelSowing(cat,run(status,1000),1010);
  assert.deepEqual({kind:a.kind,left:a.left,refund:a.refund},{kind:'run',left:50,refund:seeds+fuel});
  assert.equal(R.cancelSowing(cat,run(status,1000),1060).left,0,'the last second still works');
  assert.equal(R.cancelSowing(cat,run(status,1000),1061),null);
 }
 assert.equal(R.cancelSowing(cat,{...F,run:{op:'cultivate',status:'open',started_at:1000}},1005),null,'a cultivation run is not a sowing');
 assert.equal(R.cancelSowing(cat,{...F,run:{op:'sow',status:'closed',crop,started_at:1000}},1005),null);
 const grown={...F,state:'growing',crop:{id:crop,planted_at:2000,cost:seeds-4,fuel:fuel-1}};
 const g=R.cancelSowing(cat,grown,2059);
 assert.deepEqual({kind:g.kind,left:g.left,refund:g.refund},{kind:'crop',left:1,refund:seeds-4+fuel-1});
 assert.equal(R.cancelSowing(cat,grown,2061),null);
 assert.equal(R.cancelSowing(cat,{...F,state:'ready'},2000),null);
 for(const s of parity.sowing){
  const f={id:'x',ha:s.ha,state:'growing',crop:{id:s.crop,planted_at:10,...(s.recorded||{})}};
  assert.equal(R.cancelSowing(parity.catalog,f,20).refund,s.expect,`${s.crop} ${s.ha} ha`);
 }
});

test('cancel sowing sends field_cancel {field, revision} and explains the server errors in words',async()=>{
 const R=await load('orchard.js');
 assert.deepEqual(R.cancelCommand({id:'f9',revision:4,ha:1}),['field_cancel',{field:'f9',revision:4}]);
 for(const code of ['nothing_to_cancel','stale_object','undo_expired']){
  const text=R.cancelErrorText({code,message:'raw'});
  assert.ok(text.length>20&&text!=='raw',code);
 }
 assert.equal(R.cancelErrorText({code:'other',message:'сервер сказал'}),'сервер сказал');
});

test('app.js wiring: the field card button, the confirm texts, the upkeep wording, the 44px rule',()=>{
 const app=read('qw_farm/static/app.js'),admin=read('web/static/js/postgres-admin.js'),css=read('qw_farm/static/style.css');
 assert.ok(app.includes('function cancelSowButton')&&app.includes('REFUND.cancelCommand(f)'));
 assert.equal((app.match(/cancelSowButton\(f,c\)/g)||[]).length,4,'definition + open, autopilot and growing phases');
 assert.ok(app.includes("payload.kind==='field_cancel'?REFUND.cancelErrorText(e)"));
 assert.ok(app.includes('REFUND.demolishText(S.catalog,o,now(),objName(o))'));
 assert.ok(app.includes('базовой цены каждой постройки; уровень не добавляет')&&!app.includes('за каждый её уровень'));
 assert.ok(admin.includes('базовой цены, уровень не добавляет')&&!admin.includes('цены за уровень'));
 assert.ok(/\.field-cancel\{min-height:44px\}/.test(css)&&css.indexOf('.field-cancel{')<css.indexOf('«Контрастный режим» (UI_RULES'));
});

test('the compost heap upgrade button is hidden when the catalog says kind null (the real upgradeCard function)',()=>{
 const app=read('qw_farm/static/app.js');
 const src=app.slice(app.indexOf('function upgradeCard'),app.indexOf('const barnBonus'));
 const made=[];
 const el=(tag,text)=>({tag,text,kids:[],append(...k){this.kids.push(...k);}});
 const env={own:()=>true,UP:()=>({kinds:{compost_heap:null,dairy:'workshop'},max:3,costs:{dairy:{2:{coins:1,items:{},level:1}}},barn_bonus:{}}),
  lvlOf:o=>o.level||1,card:(t,s)=>{const c=el('card',t);c.sub=s;made.push(c);return c;},el,levelEffect:()=>'эффект',
  button:(t,fn,cls,dis)=>({button:t,dis}),note:()=>{},goods:()=>({}),S:{me:{level:1,coins:0}},command:()=>{},enough:()=>true};
 const fn=new Function(...Object.keys(env),`${src}\nreturn upgradeCard;`)(...Object.values(env));
 const p=el('panel');
 fn({type:'compost_heap',level:1},p);
 assert.equal(p.kids.length+made.length,0,'level 1 heap: nothing');
 fn({type:'compost_heap',level:2},p);
 assert.equal(made.length,1);
 assert.ok(made[0].text.includes('Уровень 2'));
 assert.ok(!JSON.stringify(made[0].kids).includes('"button"'),'no upgrade button on an upgraded heap');
 made.length=0;p.kids.length=0;
 fn({type:'dairy',level:1},p);
 assert.ok(JSON.stringify(made[0].kids).includes('Улучшить'),'other buildings still upgrade');
});
