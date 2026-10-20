const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
const code=source.slice(source.indexOf('const INV_CATS='),source.indexOf('function renderInventory('));
const c={Object,String,Number};vm.createContext(c);
vm.runInContext(code+'\nObject.assign(globalThis,{invNorm,invEntries,invCategory,invWorkshop,invCounts,invCatChips,invShopChips,invNormalizeState,invFilter})',c);
const cat={
 items:{wheat:{name:'Пшеница',kind:'crop'},egg:{name:'Яйцо',kind:'product'},bread:{name:'Хлеб',kind:'product'},cake:{name:'Ёлочный торт',kind:'product'},pie:{name:'Пирог',kind:'product'},log:{name:'Бревно',kind:'forest'},carp:{name:'Карась',kind:'fish'},odd:{name:'Нечто',kind:'weird'}},
 animals:{chicken:{outputs:{egg:2}}},
 recipes:{bread:{building:'bakery',outputs:{bread:1}},cake:{building:'bakery',outputs:{cake:1}},pie2:{building:'oven',outputs:{pie:1}},pie:{building:'bakery',outputs:{pie:1}}},
 buildings:{bakery:{name:'Пекарня'},oven:{name:'Печь'}},
};
const inv={wheat:3,egg:2,bread:1,cake:4,pie:1,log:5,carp:2,odd:1,gone:0};
const E=c.invEntries(inv),ids=r=>r.map(x=>x[0]);
test('Normalisation is case-insensitive and folds yo to ye',()=>{
 assert.equal(c.invNorm('  ЁлОчный '),'елочный');assert.equal(c.invNorm(null),'');
 assert.equal(JSON.stringify(ids(c.invFilter(E,{q:'ЕЛОЧНЫЙ',cat:'all',shop:'all'},cat))),JSON.stringify(['cake']));
 assert.equal(JSON.stringify(ids(c.invFilter(E,{q:'ёлочный',cat:'all',shop:'all'},cat))),JSON.stringify(['cake']));
});
test('Entries skip zero quantities',()=>{assert.ok(!ids(E).includes('gone'));assert.equal(E.length,8);});
test('Category: kind, animal outputs override product, unknown kind goes to other',()=>{
 assert.equal(c.invCategory('wheat',cat),'crop');assert.equal(c.invCategory('egg',cat),'animal');assert.equal(c.invCategory('bread',cat),'product');
 assert.equal(c.invCategory('log',cat),'forest');assert.equal(c.invCategory('carp',cat),'fish');assert.equal(c.invCategory('odd',cat),'other');
});
test('Workshop is the first recipe producing the item',()=>{
 assert.equal(c.invWorkshop('pie',cat),'oven');assert.equal(c.invWorkshop('bread',cat),'bakery');assert.equal(c.invWorkshop('wheat',cat),'');
});
test('Counts and chips show only non-empty groups',()=>{
 const n=c.invCounts(E,cat);
 assert.equal(n.all,8);assert.deepEqual({...n.cats},{crop:1,animal:1,product:3,forest:1,fish:1,other:1});
 assert.deepEqual({...n.shops},{bakery:2,oven:1});
 assert.equal(JSON.stringify(c.invCatChips(c.invCounts([['wheat',1]],cat))),JSON.stringify([['crop','Урожай',1]]));
 assert.equal(JSON.stringify(c.invShopChips(n,cat)),JSON.stringify([['bakery','Пекарня',2],['oven','Печь',1]]));
});
test('Filters combine category, workshop and search',()=>{
 assert.equal(JSON.stringify(ids(c.invFilter(E,{q:'',cat:'animal',shop:'all'},cat))),JSON.stringify(['egg']));
 assert.equal(JSON.stringify(ids(c.invFilter(E,{q:'',cat:'product',shop:'oven'},cat))),JSON.stringify(['pie']));
 assert.equal(JSON.stringify(ids(c.invFilter(E,{q:'',cat:'product',shop:'all'},cat))),JSON.stringify(['bread','cake','pie']));
 assert.equal(JSON.stringify(ids(c.invFilter(E,{q:'пир',cat:'product',shop:'bakery'},cat))),JSON.stringify([]));
 assert.equal(JSON.stringify(ids(c.invFilter(E,{q:'яйц',cat:'product',shop:'all'},cat))),JSON.stringify([]));
 assert.equal(c.invFilter(E,{q:'zzz',cat:'all',shop:'all'},cat).length,0);
});
test('Stale filters fall back to All after the stock changes',()=>{
 const n=c.invCounts([['wheat',1]],cat);
 assert.deepEqual({...c.invNormalizeState({q:'',cat:'product',shop:'oven'},n)},{q:'',cat:'all',shop:'all'});
 const m=c.invCounts(E,cat);
 assert.deepEqual({...c.invNormalizeState({q:'x',cat:'product',shop:'gone'},m)},{q:'x',cat:'product',shop:'all'});
 assert.deepEqual({...c.invNormalizeState({q:'',cat:'crop',shop:'oven'},m)},{q:'',cat:'crop',shop:'all'});
});
