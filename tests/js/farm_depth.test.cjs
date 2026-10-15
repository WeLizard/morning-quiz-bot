const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
// Pure helpers of qw_farm/static/scene_map.js (ES module): depth order, toasts, seed-strip wheel, hint placement, building purpose.
const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/scene_map.js'),'utf8').replace(/export (const|function|class) /g,'$1 ');
const names='TW TH depthKey depthSeparation compareDepth sortByDepth spriteSlots isoInverse iso pushToast expireToasts toastText TOAST_MS TOAST_ERROR_MS TOAST_MAX wheelScrollDelta placeHint buildingPurpose'.split(' ');
const ctx={WeakMap,Set,Object,Math,Array,String};vm.createContext(ctx);vm.runInContext(source+`\nglobalThis.api={${names.join(',')}};`,ctx);
const m=ctx.api;
const ids=list=>Array.from(list,o=>o.id);
const box=(id,x,y,w=1,h=1)=>({id,x,y,w,h});
// Painter's order check for any pair that the footprints decide: the one behind must come first.
function assertConsistent(sorted){
 for(let i=0;i<sorted.length;i++)for(let j=i+1;j<sorted.length;j++){
  assert.notEqual(m.depthSeparation(sorted[i],sorted[j]),1,`${sorted[i].id} is in front of ${sorted[j].id} but is drawn first`);
 }
}

test('the barn bug: a bed beside a large building is drawn in front of it, not under it',()=>{
 // 3x3 barn at (5,5) covers x 5..8, y 5..8. A bed at (8,5) is right next to its front-right side (nearer: x 8 >= barn x end 8).
 // The old corner-sum key (x+y+w+h) said bed=15 < barn=16, so the barn was painted over the bed.
 const barn=box('barn',5,5,3,3),bed=box('bed',8,5);
 assert.ok(m.depthKey(bed)<m.depthKey(barn),'precondition: the corner sum alone gets this wrong');
 assert.deepEqual(ids(m.sortByDepth([bed,barn])),['barn','bed']);
 assert.deepEqual(ids(m.sortByDepth([barn,bed])),['barn','bed']);
 // The mirror case (bed in front along y) and a bed behind it.
 assert.deepEqual(ids(m.sortByDepth([box('b',5,8),barn])),['barn','b']);
 assert.deepEqual(ids(m.sortByDepth([barn,box('b',4,4)])),['b','barn']);
});
test('shapes: 1x1, 2x2, 3x3 and 2x4 mixed, in any input order, give the same consistent order',()=>{
 const set=[box('mill',2,2,2,2),box('barn',5,5,3,3),box('bed1',4,2),box('bed2',8,6),box('long',0,6,4,2),box('bed3',2,4),box('coop',9,1,2,2),box('far',10,10,1,1)];
 const want=ids(m.sortByDepth(set));
 assertConsistent(m.sortByDepth(set));
 for(let r=0;r<set.length;r++){const rot=[...set.slice(r),...set.slice(0,r)];assertConsistent(m.sortByDepth(rot));assert.equal(m.sortByDepth(rot).length,set.length);}
 assert.equal(want[want.length-1],'far','the frontmost object is painted last');
 // Reverse input must still produce a consistent order.
 assertConsistent(m.sortByDepth([...set].reverse()));
});
test('a dense grid of beds in front of a barn and a tractor spot keeps every pair correct',()=>{
 const set=[box('barn',3,3,3,3)];
 for(let x=0;x<10;x++)for(let y=0;y<10;y++)if(!(x>=3&&x<6&&y>=3&&y<6))set.push(box(`p${x}_${y}`,x,y));
 const shuffled=[...set].sort((a,b)=>((a.x*7+a.y*13)%11)-((b.x*7+b.y*13)%11));
 const sorted=m.sortByDepth(shuffled);
 assert.equal(sorted.length,set.length);assertConsistent(sorted);
 const at=id=>sorted.findIndex(o=>o.id===id);
 assert.ok(at('p6_3')>at('barn')&&at('p3_6')>at('barn')&&at('p6_6')>at('barn'),'beds in front are painted after the barn');
 assert.ok(at('p2_3')<at('barn')&&at('p3_2')<at('barn')&&at('p2_2')<at('barn'),'beds behind are painted before the barn');
});
test('ties are stable: the same input gives the same output, equal keys keep input order',()=>{
 const a=box('a',0,0),b=box('b',3,0),c=box('c',0,3); // all diagonal-separated or equal-key
 const first=ids(m.sortByDepth([a,b,c])),second=ids(m.sortByDepth([a,b,c]));
 assert.deepEqual(first,second);
 const d1={id:'d1',x:1,y:1,w:1,h:1},d2={id:'d2',x:1,y:1,w:1,h:1}; // identical footprint
 assert.deepEqual(ids(m.sortByDepth([d1,d2])),['d1','d2']);assert.deepEqual(ids(m.sortByDepth([d2,d1])),['d2','d1']);
 assert.equal(m.sortByDepth([]).length,0);
});
test('compareDepth never returns 0 for different footprints and agrees with separation',()=>{
 const a=box('a',0,0),b=box('b',1,0);
 assert.equal(m.compareDepth(a,b),-1);assert.equal(m.compareDepth(b,a),1);
 assert.notEqual(m.compareDepth(box('x',0,3),box('y',3,0)),0);
});

test('sprites (tractor, helper, goose) slot between the objects they are behind and in front of',()=>{
 const barn=box('barn',5,5,3,3),bed=box('bed',9,5),far=box('far',0,0,2,2);
 const list=m.sortByDepth([barn,bed,far]); // far, barn, bed
 const behindBarn={id:'t1',x:6,y:4,w:0,h:0},frontOfBarn={id:'t2',x:6.5,y:8.6,w:0,h:0},nearOrigin={id:'t3',x:1,y:5,w:0,h:0};
 const slots=m.spriteSlots(list,[behindBarn,frontOfBarn,nearOrigin]);
 assert.equal(slots.length,list.length+1);
 const slotOf=id=>slots.findIndex(s=>s.some(sp=>sp.id===id));
 const at=id=>list.findIndex(o=>o.id===id);
 assert.ok(slotOf('t1')<=at('barn'),'a tractor behind the barn is painted before it (the barn hides it)');
 assert.ok(slotOf('t2')>at('barn'),'a tractor in front of the barn is painted after it');
 assert.equal(slots.flat().length,3,'every sprite is placed exactly once');
 assert.deepEqual(m.spriteSlots([],[{x:1,y:1,w:0,h:0}]).map(s=>s.length),[1]);
});
test('isoInverse is the inverse of iso',()=>{
 for(const [x,y] of [[0,0],[3.5,2.25],[10,-1.5]]){const p=m.iso(x,y),q=m.isoInverse(p.x,p.y);assert.ok(Math.abs(q.x-x)<1e-9&&Math.abs(q.y-y)<1e-9);}
});

test('toasts: identical notices merge into a counter and restart their timer',()=>{
 const list=[];
 m.pushToast(list,'Базилик посажено',false,1000);m.pushToast(list,'Базилик посажено',false,1500);const t=m.pushToast(list,'Базилик посажено',false,2000);
 assert.equal(list.length,1);assert.equal(t.count,3);assert.equal(m.toastText(t),'Базилик посажено ×3');assert.equal(t.until,2000+m.TOAST_MS);
 m.pushToast(list,'Урожай собран',false,2100);assert.equal(list.length,2);assert.equal(m.toastText(list[1]),'Урожай собран');
 // same text but an error is a different notice
 m.pushToast(list,'Базилик посажено',true,2200);assert.equal(list.length,3);
});
test('toasts: errors outlive ordinary notices, at most three are shown, errors are dropped last',()=>{
 const list=[];
 const e=m.pushToast(list,'Нет связи',true,0),n=m.pushToast(list,'a',false,0);
 assert.ok(e.until>n.until);assert.ok(m.TOAST_ERROR_MS>m.TOAST_MS);
 m.pushToast(list,'b',false,0);m.pushToast(list,'c',false,0);
 assert.equal(list.length,m.TOAST_MAX);assert.ok(list.some(t=>t.error),'the error survives');assert.ok(!list.some(t=>t.text==='a'),'the oldest ordinary one is dropped');
 assert.equal(m.expireToasts(list,m.TOAST_MS+1),true);assert.deepEqual(Array.from(list,t=>t.text),['Нет связи']);
 assert.equal(m.expireToasts(list,m.TOAST_MS+2),false);assert.equal(m.expireToasts(list,m.TOAST_ERROR_MS+1),true);assert.equal(list.length,0);
});

test('seed strip wheel: vertical wheel scrolls sideways only when the strip can move that way',()=>{
 const w=(deltaY,extra={})=>({deltaX:0,deltaY,deltaMode:0,ctrlKey:false,...extra});
 assert.equal(m.wheelScrollDelta(w(100),0,1000,400),100);
 assert.equal(m.wheelScrollDelta(w(-100),300,1000,400),-100);
 assert.equal(m.wheelScrollDelta(w(100),590,1000,400),10,'clamped to the end');
 assert.equal(m.wheelScrollDelta(w(100),600,1000,400),0,'already at the end: let the event pass');
 assert.equal(m.wheelScrollDelta(w(-100),0,1000,400),0,'already at the start');
 assert.equal(m.wheelScrollDelta(w(100),0,400,400),0,'nothing to scroll');
 assert.equal(m.wheelScrollDelta(w(0),50,1000,400),0);
 assert.equal(m.wheelScrollDelta(w(100,{ctrlKey:true}),0,1000,400),0,'ctrl+wheel is the browser zoom');
 assert.equal(m.wheelScrollDelta({deltaX:60,deltaY:5,deltaMode:0,ctrlKey:false},0,1000,400),60,'a horizontal gesture wins');
 assert.equal(m.wheelScrollDelta(w(3,{deltaMode:1}),0,1000,400),48,'line mode');
});

test('hint card is always fully inside the box: above, below or pinned',()=>{
 const win={x0:6,y0:60,x1:394,y1:700};
 const inside=p=>p.left>=win.x0&&p.left+p.width<=win.x1;
 let p=m.placeHint({x:200,top:300,bottom:380},{w:200,h:80},win);
 assert.equal(p.side,'above');assert.equal(p.top,300-8-80);assert.ok(inside(p));
 p=m.placeHint({x:200,top:100,bottom:160},{w:200,h:80},win); // no room above
 assert.equal(p.side,'below');assert.equal(p.top,168);
 p=m.placeHint({x:5,top:300,bottom:380},{w:200,h:80},win); // left edge
 assert.equal(p.left,6);assert.ok(inside(p));
 p=m.placeHint({x:398,top:300,bottom:380},{w:200,h:80},win); // right edge
 assert.equal(p.left+p.width,394);
 p=m.placeHint({x:200,top:90,bottom:680},{w:200,h:80},win); // tall object filling the screen: pinned
 assert.equal(p.side,'pinned');assert.ok(p.top>=win.y0&&p.top+80<=win.y1);
 p=m.placeHint({x:200,top:300,bottom:380},{w:900,h:900},win); // bigger than the window: clipped to it
 assert.ok(p.width<=win.x1-win.x0);assert.ok(inside(p));
});

const catalog={
 items:{wheat:{name:'Пшеница'},corn:{name:'Кукуруза'},clover:{name:'Клевер'},feed:{name:'Зерносмесь'},hay:{name:'Сено'},flour:{name:'Мука'},bread:{name:'Хлеб'},egg:{name:'Яйца'}},
 buildings:{feedmill:{name:'Кормоцех'},bakery:{name:'Пекарня'},coop:{name:'Курятник'},bench:{name:'Скамейка',decor:true}},
 recipes:{mixedfeed:{building:'feedmill',inputs:{corn:1,wheat:1},outputs:{feed:3}},hay:{building:'feedmill',inputs:{clover:2},outputs:{hay:2}},bread:{building:'bakery',inputs:{flour:2},outputs:{bread:1}}},
 animals:{chicken:{name:'Курочки',building:'coop',inputs:{feed:1},outputs:{egg:2}},cow:{name:'Бурёнки',building:'cowshed',inputs:{hay:1},outputs:{}}},
};
test('building purpose is generated from the catalog: what it makes, from what, who needs it',()=>{
 const feedmill=m.buildingPurpose('feedmill',catalog).join(' ');
 for(const word of ['зерносмесь','сено','кукуруза','пшеница','клевер','курочки','бурёнки'])assert.ok(feedmill.includes(word),`feedmill hint mentions ${word}: ${feedmill}`);
 assert.equal(m.buildingPurpose('feedmill',catalog).length,2);
 const coop=m.buildingPurpose('coop',catalog).join(' ');
 assert.ok(coop.includes('курочки')&&coop.includes('яйца')&&coop.includes('зерносмесь'),coop);
 assert.ok(m.buildingPurpose('bakery',catalog).join(' ').includes('мука'));
 assert.deepEqual(Array.from(m.buildingPurpose('bench',catalog)),[],'decor has no purpose line');
 assert.deepEqual(Array.from(m.buildingPurpose('unknown',catalog)),[]);
 assert.deepEqual(Array.from(m.buildingPurpose('feedmill',null)),[]);
 // long lists are trimmed
 const big={items:{},recipes:{},animals:{}};for(let i=0;i<9;i++){big.items['i'+i]={name:'Т'+i};big.recipes['r'+i]={building:'x',inputs:{['i'+i]:1},outputs:{['o'+i]:1}};}
 assert.ok(m.buildingPurpose('x',big).join(' ').includes('и др.'));
});
