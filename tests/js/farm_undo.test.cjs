const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
function client(nowValue){
 const S={catalog:{undo:{window:60,late_refund_pct:50,late_loot_pct:50},crops:{corn:{cost:7},wheat:{cost:2}},routes:{old_grove:{cost:14,inputs:{bread:1}}}}};
 const c={S,now:()=>nowValue.t,Math,Number,Object};
 vm.createContext(c);
 const code=source.slice(source.indexOf('function undoRules()'),source.indexOf('function confirmDigUp('))+source.slice(source.indexOf('function tripUndoLabel('),source.indexOf('function confirmTripReturn('));
 vm.runInContext(code+'\nObject.assign(globalThis,{undoFull,digRefund,jobRefund,tripUndoLabel,tripEarlyLoot,tripTaken,cropCost})',c);
 return c;
}
test('Dig-up refund: full in the first 60 s (inclusive), half rounded down later; old plantings use the catalog price',()=>{
 const t={t:1000},c=client(t),crop={id:'corn',planted_at:1000,cost:7};
 assert.equal(c.digRefund(crop),7);t.t=1060;assert.equal(c.digRefund(crop),7);t.t=1061;assert.equal(c.digRefund(crop),3);
 assert.equal(c.digRefund({id:'corn',planted_at:0}),3,'no cost recorded: the catalog price');
 assert.equal(c.cropCost({id:'unknown',planted_at:0}),0);
});
test('Early return: label switches after a minute; loot is floor(output * share * 0.5), same as the server',()=>{
 const t={t:5000},c=client(t),trip={started_at:5000,ready_at:5000+7200,outputs:{hazelnut:6,mushroom:4,blackberry:3}};
 t.t=5000+60;assert.equal(c.tripUndoLabel(trip),'Отменить вылазку');t.t=5000+61;assert.equal(c.tripUndoLabel(trip),'Вернуться раньше');
 assert.deepEqual({...c.tripEarlyLoot(trip)},{});
 t.t=5000+3600;assert.deepEqual({...c.tripEarlyLoot(trip)},{hazelnut:1,mushroom:1});
 t.t=5000+7199;assert.deepEqual({...c.tripEarlyLoot(trip)},{hazelnut:2,mushroom:1,blackberry:1});
 assert.deepEqual({...c.tripTaken({route:'old_grove'}).items},{bread:1});assert.equal(c.tripTaken({route:'old_grove'}).coins,14);
});
test('Batch cancel preview: queued = full, running = full for 60 s from starts_at then floor(half), zero positions dropped',()=>{
 const t={t:1000},c=client(t),job={starts_at:1000,inputs:{a:1,b:5,c:2}};
 assert.deepEqual({...c.jobRefund(job).items},{a:1,b:5,c:2});assert.equal(c.jobRefund(job).full,true);
 t.t=1060;assert.equal(c.jobRefund(job).full,true);
 t.t=1061;let r=c.jobRefund(job);assert.equal(r.full,false);assert.deepEqual({...r.items},{b:2,c:1});
 assert.deepEqual({...c.jobRefund({starts_at:1000,inputs:{a:1}}).items},{},'a single unit returns nothing');
 t.t=5000;r=c.jobRefund({starts_at:9000,inputs:{a:1}});assert.equal(r.full,true,'still waiting in the queue: free at any time');assert.deepEqual({...r.items},{a:1});
});
