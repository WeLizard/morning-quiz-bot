const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const NAV=require('../../qw_farm/static/farm_nav.js');
const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
const fn=name=>{const a=source.indexOf(`function ${name}(`);assert.ok(a>=0,name);let depth=0,k=source.indexOf('{',a);for(;;k++){if(source[k]==='{')depth++;else if(source[k]==='}'&&--depth===0)break;}return source.slice(a,k+1)+';\n';};
const code=['recipeMemory','bulkRepeatPlan','bulkCounts','bulkActualDetails'].map(fn).join('');
const recipes={bread:{id:'bread',name:'Хлеб',building:'bakery',level:1,inputs:{wheat:1}},pie:{id:'pie',name:'Пирог',building:'bakery',level:1,inputs:{wheat:2}},jam:{id:'jam',name:'Джем',building:'jamhouse',level:1,inputs:{berries:1}},locked:{id:'locked',name:'Торт',building:'bakery',level:8,inputs:{wheat:1}}};
const workshop=(id,memory,extra={})=>({id,type:'bakery',jobs:[],level:2,recipe_cursor:0,recipes_memory:memory,...extra});
function context(objects,inventory={wheat:9,berries:9},extra={}){
 const S={me:{objects,inventory,level:5},catalog:{recipes,buildings:{bakery:{name:'Пекарня'},jamhouse:{name:'Вареньеварня'}},animals:{},...extra.catalog}};
 const ctx={S,NAV,Set,Math,now:()=>100,inArea:(o,z)=>!z||(o.x<z.x+z.w&&o.x+(o.w||1)>z.x&&o.y<z.y+z.h&&o.y+(o.h||1)>z.y),slotsOf:extra.slotsOf||((o)=>o.slots||2),recipeLevel:r=>r.level,batchOf:(a,o)=>({inputs:a.inputs}),el:(tag,text,cls)=>({tag,text,cls,children:[],append(...nodes){this.children.push(...nodes)}})};
 vm.createContext(ctx);vm.runInContext(code,ctx);return ctx;
}
const starts=plan=>JSON.parse(JSON.stringify(plan.entries.map(({object,recipe})=>({object,recipe}))));
test('one pass repeats each remembered recipe once; fill is bounded by slots',()=>{
 const c=context([workshop('w1',['bread','pie'],{slots:4})]);
 assert.deepEqual(starts(c.bulkRepeatPlan(null,'once')),[{object:'w1',recipe:'bread'},{object:'w1',recipe:'pie'}]);
 assert.deepEqual(starts(c.bulkRepeatPlan(null,'fill')),[{object:'w1',recipe:'bread'},{object:'w1',recipe:'pie'},{object:'w1',recipe:'bread'},{object:'w1',recipe:'pie'}]);
 assert.equal(c.bulkCounts(null).restart,2);
});
test('rotated cursor, shared stock, area and full slots determine the preview',()=>{
 const a=workshop('a',['bread','pie'],{recipe_cursor:1,slots:2,x:0,y:0,w:1,h:1});
 const b=workshop('b',['bread'],{slots:2,x:3,y:0,w:1,h:1});
 const c=context([b,a],{wheat:3});
 assert.deepEqual(starts(c.bulkRepeatPlan(null,'once')),[{object:'a',recipe:'pie'},{object:'b',recipe:'bread'}]);
 assert.deepEqual(starts(c.bulkRepeatPlan({x:0,y:0,w:1,h:1},'once')),[{object:'a',recipe:'pie'},{object:'a',recipe:'bread'}]);
 a.jobs=[{id:'1'},{id:'2'}];assert.deepEqual(starts(c.bulkRepeatPlan(null,'fill')),[{object:'b',recipe:'bread'},{object:'b',recipe:'bread'}]);
});
test('locked recipes are omitted and feed previews use independent stock with grass substitution',()=>{
 const hen={id:'hen',type:'coop',animal:'hen',animal_job:null,grass_feed:true};
 const c=context([hen,workshop('w1',['locked','bread'])],{wheat:1,feed:0,grass:2},{catalog:{animals:{hen:{inputs:{feed:1}}}}});
 const counts=c.bulkCounts(null);assert.equal(counts.feed,1);assert.equal(counts.once.count,1);assert.deepEqual(starts(counts.once),[{object:'w1',recipe:'bread'}]);
 hen.grass_feed=false;assert.equal(c.bulkCounts(null).feed,0);
});
test('preview agrees with the backend shared round-robin fixture',()=>{
 const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'../fixtures/farm_bulk_repeat.json'),'utf8'));
 const millRecipes={flour:{id:'flour',name:'Смолоть муку',building:'mill',level:1,inputs:{wheat:2}},feed:{id:'feed',name:'Смешать корм',building:'mill',level:1,inputs:{wheat:2}},oil:{id:'oil',name:'Подсолнечное масло',building:'mill',level:5,inputs:{sunflower:2}}};
 for(const example of fixture.cases){
  const c=context(example.farm.objects,example.farm.inventory,{catalog:{recipes:{...recipes,...millRecipes},buildings:{mill:{name:'Мельница'}}},slotsOf:o=>Math.min(6,2+(o.level||1))});
  c.S.me.level=20;
  assert.deepEqual(starts(c.bulkRepeatPlan(example.area,example.mode==='repeat_once'?'once':'fill')),example.starts,example.name);
 }
});
test('unknown recipe before the cursor does not shift the chosen known recipe',()=>{
 const c=context([workshop('w1',['missing','bread','pie'],{recipe_cursor:1,slots:1})],{wheat:2});
 assert.deepEqual(starts(c.bulkRepeatPlan(null,'once')),[{object:'w1',recipe:'bread'}]);
});
test('bulk preview spends the effective inputs of each compost heap from shared stock',()=>{
 const compost={id:'compost',name:'Компост',building:'compost_heap',level:1,inputs:{manure:2,grass:1},upgrade_inputs:{manure:1,grass:1},upgrade_level:2};
 const heaps=[1,2,3].map(level=>workshop(`heap${level}`,['compost'],{type:'compost_heap',level}));
 const catalog={recipes:{compost}};
 const c=context(heaps,{manure:4,grass:6},{catalog});
 const expected=heaps.map(({id})=>({object:id,recipe:'compost'}));
 assert.deepEqual(starts(c.bulkRepeatPlan(null,'once')),expected);
 assert.deepEqual(starts(c.bulkRepeatPlan(null,'fill')),expected);
 assert.deepEqual(c.S.me.inventory,{manure:4,grass:6});
});
test('actual server event is shown as a grouped, expandable result',()=>{
 const c=context([workshop('w1',['bread'],{x:2,y:1})]);
 const result=c.bulkActualDetails({kind:'repeat_once',details:[{object:'w1',recipe:'bread',job:'1'},{object:'w1',recipe:'bread',job:'2'}]});
 assert.equal(result.tag,'details');assert.match(result.children[0].text,/2 партий/);
 assert.equal(result.children[1].children.length,1);
 assert.match(result.children[1].children[0].text,/Пекарня \(3, 2\) · Хлеб ×2/);
 assert.equal(c.bulkActualDetails({kind:'queue',details:[{object:'w1',recipe:'bread'}]}),null);
});
