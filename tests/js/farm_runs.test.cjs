const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
// farm_runs.js is a pure ES module: strip `export` and evaluate it in a plain context.
const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/farm_runs.js'),'utf8').replace(/export (const|function|class) /g,'$1 ');
const names='CLASS_LABEL LONG_HINT GRAINS MAX_PLOTS cropClass seedStats sortSeeds planMachine planRepeat planTap remember'.split(' ');
const ctx={Math,Object,Array,Set};vm.createContext(ctx);vm.runInContext(source+`\nglobalThis.api={${names.join(',')}};`,ctx);
const api=ctx.api,J=x=>JSON.parse(JSON.stringify(x));   // arrays of the vm context are not reference-equal to ours
const crops={
 wheat:{id:'wheat',name:'Пшеница',cost:2,seconds:30,yield_qty:3,xp:1,level:1},
 beet:{id:'beet',name:'Свёкла',cost:9,seconds:900,yield_qty:3,xp:6,level:2},
 oat:{id:'oat',name:'Овёс',cost:5,seconds:1800,yield_qty:6,xp:8,level:1},
 cabbage:{id:'cabbage',name:'Капуста',cost:14,seconds:14400,yield_qty:6,xp:24,level:3},
 saffron:{id:'saffron',name:'Шафран',cost:213,seconds:86400,yield_qty:5,xp:122,level:20},
};
const items={wheat:{price:2},beet:{price:11},oat:{price:6},cabbage:{price:18},saffron:{price:140}};
const catalog={crops,items,equipment:{tractor:{name:'Трактор «Росток»'},harvester:{name:'Комбайн «Колос»'},robot:{name:'Робот'}}};
const plot=(id,crop=null)=>({id,type:'plot',revision:1,crop});
const me=(extra={})=>({level:5,coins:100,equipment:{tractor:{},harvester:{}},objects:[plot('p1'),plot('p2'),plot('p3')],...extra});

test('classes follow the growth time: fast < 30 min <= medium < 4 h <= long',()=>{
 assert.equal(api.cropClass(30),'fast');assert.equal(api.cropClass(1799),'fast');assert.equal(api.cropClass(1800),'medium');
 assert.equal(api.cropClass(14399),'medium');assert.equal(api.cropClass(14400),'long');
});

test('seed stats: income and XP per hour, label and the long-crop hint',()=>{
 const wheat=api.seedStats(crops.wheat,2);assert.equal(wheat.cls,'fast');assert.equal(wheat.label,'быстрая');assert.equal(wheat.profit,4);assert.equal(wheat.perHour,480);
 const cab=api.seedStats(crops.cabbage,18);assert.equal(cab.cls,'long');assert.equal(cab.profit,94);assert.equal(cab.perHour,Math.round(94/4));assert.equal(cab.xpPerHour,6);
 assert.ok(cab.hint.includes('посади перед уходом'));
 const fast=api.seedStats(crops.beet,11,10);assert.equal(fast.seconds,90);   // game speed shortens the time
});

test('the strip is sorted by growth time; locked seeds follow by level',()=>{
 const order=api.sortSeeds(Object.values(crops),5).map(c=>c.id);
 assert.deepEqual(J(order),['wheat','beet','oat','cabbage','saffron']);
 assert.deepEqual(J(api.sortSeeds(Object.values(crops),1).map(c=>c.id)),['wheat','oat','beet','cabbage','saffron']);
});

test('tractor plan: free plots only, capped by the coins and by 24',()=>{
 const p=api.planMachine({machine:'tractor',crop:'beet',replant:false},me({coins:20}),catalog,0);
 assert.equal(p.ok,true);assert.equal(p.count,2);assert.equal(p.cost,18);assert.equal(p.replant,false);assert.deepEqual(J(p.plots.map(x=>x.id)),['p1','p2']);
 const busy=me({objects:[plot('p1',{id:'beet',ready_at:99})]});
 const none=api.planMachine({machine:'tractor',crop:'beet',replant:false},busy,catalog,0);assert.equal(none.ok,false);assert.match(none.why,/свободных грядок/);
 const poor=api.planMachine({machine:'tractor',crop:'saffron',replant:false},me({level:20,coins:10}),catalog,0);assert.equal(poor.ok,false);assert.match(poor.why,/монет/);
 const locked=api.planMachine({machine:'tractor',crop:'saffron',replant:false},me(),catalog,0);assert.equal(locked.ok,false);assert.match(locked.why,/уровень 20/);
 const many=me({coins:10000,objects:Array.from({length:40},(_,i)=>plot('q'+String(i).padStart(2,'0')))});
 assert.equal(api.planMachine({machine:'tractor',crop:'wheat',replant:false},many,catalog,0).count,24);
});

test('combine plan: only ripe grains; replant is limited by the coins',()=>{
 const farm=me({coins:7,objects:[plot('p1',{id:'wheat',ready_at:10}),plot('p2',{id:'oat',ready_at:10}),plot('p3',{id:'oat',ready_at:10}),plot('p4',{id:'cabbage',ready_at:10}),plot('p5',{id:'wheat',ready_at:999})]});
 const p=api.planMachine({machine:'harvester',crop:'',replant:true},farm,catalog,100);
 assert.equal(p.ok,true);assert.equal(p.crop,'');assert.equal(p.replant,true);assert.deepEqual(J(p.plots.map(x=>x.id)),['p1','p2']);assert.equal(p.cost,7);   // wheat 2 + oat 5; the second oat does not fit
 const plain=api.planMachine({machine:'harvester',crop:'',replant:false},farm,catalog,100);assert.equal(plain.count,3);assert.equal(plain.cost,0);
 const nothing=api.planMachine({machine:'harvester',crop:'',replant:false},me(),catalog,100);assert.equal(nothing.ok,false);assert.match(nothing.why,/готовых зерновых/);
 const broke=api.planMachine({machine:'harvester',crop:'',replant:true},{...farm,coins:0},catalog,100);assert.equal(broke.ok,false);assert.match(broke.why,/повторный посев/);
});

test('repeat: last machine and crop; no machine at all gives a reason; robot is not a run machine',()=>{
 const last=api.remember(null,{machine:'tractor',crop:'beet',replant:false});
 assert.deepEqual(J(last),{machine:'tractor',tractor:{crop:'beet'}});
 const p=api.planRepeat(last,'wheat',me(),catalog,0);assert.equal(p.ok,true);assert.equal(p.machine,'tractor');assert.equal(p.crop,'beet');
 const noHistory=api.planRepeat(null,'wheat',me(),catalog,0);assert.equal(noHistory.ok,false);assert.equal(noHistory.machine,'');assert.match(noHistory.why,/Сначала выполни рейс/);   // the chosen seed never invents a previous run
 const harv=api.remember(last,{machine:'harvester',crop:'',replant:false});
 assert.equal(api.planRepeat(harv,'wheat',me(),catalog,0).machine,'harvester');
 assert.equal(api.planRepeat(harv,'wheat',me(),catalog,0).why,'Нет готовых зерновых.');
 const no=api.planRepeat(last,'wheat',me({equipment:{robot:{}}}),catalog,0);assert.equal(no.ok,false);assert.match(no.why,/трактором или комбайном/);
 assert.equal(api.planMachine({machine:'robot'},me({equipment:{robot:{}}}),catalog,0).ok,false);
});

test('tap on a machine repeats its own memory, and asks (null) when there is none',()=>{
 assert.equal(api.planTap('tractor',null,me(),catalog,0),null);
 const last=api.remember(api.remember(null,{machine:'tractor',crop:'wheat',replant:false}),{machine:'harvester',crop:'',replant:true});
 const t=api.planTap('tractor',last,me(),catalog,0);assert.equal(t.machine,'tractor');assert.equal(t.crop,'wheat');
 assert.equal(api.planTap('harvester',last,me(),catalog,0).ok,false);   // nothing is ripe: a reason, not a silent no-op
});
