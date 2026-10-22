// Fruit orchard client (docs/tasks/FARM_ORCHARD.md): pure helpers, the map categories, the tree drawing, the wiring in app.js.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');

const ROOT=path.join(__dirname,'../..');
const STATIC=path.join(ROOT,'qw_farm/static');
const read=f=>fs.readFileSync(path.join(ROOT,f),'utf8');
const load=name=>import(pathToFileURL(path.join(STATIC,name)).href);

const catalog={
 undo:{window:60},items:{voucher_orchard:{name:'Скидочный талон сада −25%'}},
 orchard:{
  trees:{apple:{id:'apple',name:'Яблоня',sapling:'Саженец яблони',fruit:'apple',level:16,juvenile:2,yield_qty:2,xp:20,cost:2300,potted:false},
   pomegranate:{id:'pomegranate',name:'Гранат',sapling:'Саженец граната (в кадке)',fruit:'pomegranate',level:47,juvenile:3,yield_qty:1,xp:43,cost:3300,potted:true},
   pear:{id:'pear',name:'Груша',sapling:'Саженец груши',fruit:'pear',level:24,juvenile:3,yield_qty:2,xp:27,cost:2400,potted:false}},
  grafts:{graft_apple_paradise:{species:'apple',look:'paradise',name:'Райская яблоня'},graft_pear_bergamot:{species:'pear',look:'bergamot',name:'Груша-бергамот'}},
  pests:[{id:'caterpillar',name:'Гусеница в кепке'},{id:'aphid',name:'Тля'}],
  rules:{cycle:72000,young:5,adult:20,century:100,prune_every:7,birdhouse_radius:2,help_pct:20,discount_pct:25,gold_permille:[20,40]}
 }
};
const tree=(over={})=>({id:'t1',type:'tree',species:'apple',x:4,y:4,w:1,h:1,revision:3,harvests:0,planted_at:1000,cost:2300,look:null,
 fruit:{started_at:1000,ready_at:1000+3*72000,qty:2,xp:20,pest:null,golden:false,helped:false},...over});

test('years, stages and the first harvest are said in garden years',async()=>{
 const O=await load('orchard.js');
 assert.equal(O.gardenYears(1),'1 садовый год');assert.equal(O.gardenYears(3),'3 садовых года');assert.equal(O.gardenYears(7),'7 садовых лет');assert.equal(O.gardenYears(11),'11 садовых лет');assert.equal(O.gardenYears(22),'22 садовых года');
 assert.equal(O.firstHarvestSeconds(catalog,'apple'),3*72000);assert.equal(O.firstHarvestSeconds(catalog,'pear'),4*72000);
 for(const s of ['sapling','young','adult','elder','century']){assert.ok(O.STAGE_NAME[s]);assert.ok(O.stageNote(s));}
 assert.equal(O.treeName(catalog,tree()),'Яблоня');assert.equal(O.lookName(catalog,'paradise'),'Райская яблоня');assert.equal(O.lookName(catalog,null),null);
});

test('only a tree with ripe fruit counts as ready',async()=>{
 const O=await load('orchard.js');
 const ripe=tree({fruit:{ready_at:500,started_at:0,qty:2}}),young=tree();
 assert.ok(O.ripe(ripe,1000)&&!O.ripe(young,1000)&&!O.ripe({type:'plot',crop:{ready_at:1}},1000)&&!O.ripe(null,1));
 assert.equal(O.readyCount([ripe,young,{type:'plot'}],1000),1);
});

test('the card of an owned tree: stage, pest, care and grafts come from the server snapshot',async()=>{
 const O=await load('orchard.js');
 const info={stage:'adult',age:7,ripe:false,pest:'caterpillar',pest_active:true,dry:true,qty:3,golden_permille:20,next_yield:3,bird:false};
 const f=O.treeFacts(catalog,tree({harvests:8,look:'paradise'}),info,2000,1,{graft_apple_paradise:1,graft_pear_bergamot:2});
 assert.equal(f.name,'Яблоня');assert.equal(f.stageName,'Взрослое дерево');assert.equal(f.qty,3);assert.equal(f.goldenPct,2);
 assert.equal(f.pest,'Гусеница в кепке');assert.ok(f.canSpray&&f.dry);assert.equal(f.lookName,'Райская яблоня');
 assert.deepEqual(f.grafts.map(g=>[g.id,g.same]),[['graft_apple_paradise',true]],'only the grafts of this species, the current look is marked');
 assert.equal(O.treeFacts(catalog,tree(),{...info},2000,0,{}).canSpray,false);
 assert.equal(O.treeFacts(catalog,tree(),{...info},2000,0,{}).sprayWhy,'Нужен садовый настой');
 assert.equal(O.treeFacts(catalog,tree(),{...info,pest_active:false,bird:true},2000,5,{}).canSpray,false,'a birdhouse treats the pest by itself');
});

test('a visitor sees the look and the timer, never the care state',async()=>{
 const O=await load('orchard.js');
 const guest=tree({cost:undefined,fruit:{ready_at:5000,helped:false}});
 const f=O.treeFacts(catalog,guest,null,2000);
 assert.equal(f.qty,null);assert.equal(f.canSpray,false);assert.equal(f.pest,null);assert.equal(f.ripe,false);assert.equal(f.helped,false);
});

test('the Сад tab: levels, limit, the free sapling and the discount voucher with its price',async()=>{
 const O=await load('orchard.js');
 const me={level:20},v={vouchers:{apple:1},discounts:{voucher_orchard:2},count:3,limit:8};
 const rows=O.saplingRows(catalog,me,v);
 assert.deepEqual(rows.map(r=>r.id),['apple','pear','pomegranate']);
 const apple=rows[0];
 assert.ok(!apple.locked&&!apple.blocked);assert.equal(apple.first,3*72000);
 assert.deepEqual(apple.options.map(o=>[o.voucher,o.price]),[['free',0],['voucher_orchard',1725],[null,2300]]);
 assert.ok(rows[1].locked&&rows[1].blocked==='С 24 уровня');
 const full=O.saplingRows(catalog,me,{...v,count:8});
 assert.equal(full[0].blocked,'Лимит деревьев: 8 из 8');
 assert.equal(O.saplingRows(catalog,me,{...v,count:0,limit:0})[0].blocked,'Сад начинается с участка 16 × 16');
 assert.deepEqual(O.saplingRows(null,me,v),[]);
});

test('commands carry only ids and a cell: price, yield and time are the server\'s',async()=>{
 const O=await load('orchard.js');
 const row=O.saplingRows(catalog,{level:20},{vouchers:{},discounts:{},count:0,limit:4})[0],spec=O.plantSpec(row,row.options[0],catalog);
 assert.deepEqual(spec.tree,{species:'apple',voucher:null});assert.equal(spec.w,1);assert.equal(spec.h,1);
 assert.deepEqual(O.plantCommand(spec,{x:5,y:6}),['plant_tree',{species:'apple',x:5,y:6,voucher:null}]);
 assert.deepEqual(O.careCommand(tree(),'spray'),['tree_care',{object:'t1',action:'spray',item:null}]);
 assert.deepEqual(O.careCommand(tree(),'graft','graft_apple_paradise'),['tree_care',{object:'t1',action:'graft',item:'graft_apple_paradise'}]);
});

test('uprooting asks first: the whole price in the undo window, only wood later',async()=>{
 const O=await load('orchard.js');
 const early=O.uprootText(catalog,tree(),1030,60),late=O.uprootText(catalog,tree(),1000+3600,60);
 assert.ok(early.early&&early.text.includes('2300'));assert.ok(!late.early&&late.text.includes('древесина ×2')&&late.text.includes('созревший урожай'));
 assert.equal(O.treeSummary(catalog,[tree(),tree({id:'t2'}),{type:'plot'}]),'Яблоня ×2');
});

test('the map knows trees: own category, ripe state, a tall box',async()=>{
 const M=await load('scene_map.js');
 assert.ok(M.CATEGORIES.some(([id,name])=>id==='orchard'&&name==='Сад')&&M.CATEGORY_COLOR.orchard);
 assert.equal(M.categoryOf(tree(),catalog),'orchard');
 assert.deepEqual(M.readyInfo(tree(),0,catalog),{state:'busy',at:1000+3*72000});
 assert.equal(M.readyInfo(tree({fruit:{ready_at:5}}),10,catalog).state,'ready');
 assert.equal(M.readyInfo(tree({fruit:null}),10,catalog).state,'idle');
 const b=M.objectBounds(tree()),p=M.objectBounds({type:'plot',x:4,y:4,w:1,h:1});
 assert.ok(b.y1-b.y0>p.y1-p.y0&&b.y0<p.y0,'a crown is taller than a bed, so culling must not cut it');
 const c=M.countByCategory([tree(),tree({id:'t2',fruit:{ready_at:5}}),{type:'plot',crop:null}],catalog,10);
 assert.equal(c.orchard.n,2);assert.equal(c.orchard.ready,1);assert.equal(c.all.n,3);
 const rows=M.listObjects([tree()],catalog,10,{category:'orchard'});assert.equal(rows.length,1);
});

test('stage and phase of the drawing follow orchard.py: sapling, young, adult, elder, century; bloom, set, fill, ripe',async()=>{
 const O=await load('orchard.js'),r=catalog.orchard.rules;
 assert.deepEqual([0,1,4,5,19,20,98,99,140].map(h=>O.treeStage(h,r)),['sapling','young','young','adult','adult','elder','elder','century','century']);
 const C=r.cycle,at=(h,share,started=true)=>O.treeLook(catalog,tree({harvests:h,fruit:{...(started?{started_at:0}:{}),ready_at:(h?1:3)*C}}),share*(h?1:3)*C);
 assert.equal(at(0,.3).phase,'grow','a sapling grows a stem before its first year of fruit');
 assert.ok(at(0,.6).grow>at(0,.3).grow);
 assert.deepEqual([.1,.4,.9,1].map(x=>at(8,x).phase),['bloom','set','fill','ripe']);
 assert.equal(at(0,.95).phase,'fill','the last sapling year bears like a tree');
 assert.equal(at(8,.4,false).phase,'set','a visitor snapshot (no started_at) counts back from ready_at');
 assert.equal(O.treeLook(catalog,tree({fruit:null}),0).phase,'rest');
});

// A recording context that keeps the canvas transform, so the test sees where on the map each shape lands.
function recorder(){
 const log=[],st=[];let m={x:0,y:0,k:1};
 const c={save(){st.push({...m})},restore(){m=st.pop()},translate(a,b){m.x+=a*m.k;m.y+=b*m.k},scale(a){m.k*=a},rotate(){},beginPath(){},moveTo(){},lineTo(){},quadraticCurveTo(){},closePath(){},fill(){},stroke(){},ellipse(){},fillText(t){log.push(['text',t])}};
 const box={x0:1e9,x1:-1e9,y0:1e9,y1:-1e9},hit=(x,y,rx=0,ry=0)=>{const X=m.x+x*m.k,Y=m.y+y*m.k;box.x0=Math.min(box.x0,X-rx*m.k);box.x1=Math.max(box.x1,X+rx*m.k);box.y0=Math.min(box.y0,Y-ry*m.k);box.y1=Math.max(box.y1,Y+ry*m.k)};
 return {c,log,box,
  ellipse(x,y,rx,ry,col){hit(x,y,rx,ry);log.push(['ellipse',col])},line(x1,y1,x2,y2,col){hit(x1,y1);hit(x2,y2);log.push(['line',col])},
  poly(pts,col){for(const q of pts)hit(q.x,q.y);log.push(['poly',col])},leaf(x,y,a,l,w,col){hit(x+Math.cos(a)*l,y+Math.sin(a)*l);log.push(['leaf',col])},
  shadow(){},ready(){log.push(['ready'])},clockBubble(){log.push(['clock'])}};
}
async function drawn(o,{owner=true,objects=[],t=2000,winter=false,selected=null}={}){
 const {FarmScene}=await import('../../qw_farm/static/scene.js');
 const r=recorder(),scene=Object.create(FarmScene.prototype);
 Object.assign(scene,{...r,catalog,motion:false,time:0,scale:1,selected,orchardWinter:winter,lightMarkers:null,farm:{is_owner:owner,objects:[o,...objects]},now(){return t}});
 scene.orchardTree(o,{x:0,y:0});return r;
}
const cols=r=>new Set(r.log.map(e=>e[1]));
const colKey=r=>JSON.stringify([...cols(r)].sort());

test('trees: species by silhouette and fruit colour, ripe badge, clock for the selected tree, the crown stays in its culling box',async()=>{
 const M=await load('scene_map.js'),C=catalog.orchard.rules.cycle,ripe={started_at:0,ready_at:100},b=M.objectBounds({type:'tree',x:-.5,y:-.5,w:1,h:1});
 const red=await drawn(tree({harvests:8,fruit:ripe}));
 assert.ok(red.log.some(e=>e[0]==='ready')&&cols(red).has('#d9534f'),'a ripe apple tree is red and shows the ready badge');
 const green=await drawn(tree({harvests:8,fruit:{started_at:2000-.4*C,ready_at:2000+.6*C}}));
 assert.ok(!green.log.some(e=>e[0]==='ready')&&!cols(green).has('#d9534f'),'set fruit is green');
 const sel=await drawn(tree({harvests:8,fruit:{ready_at:5000,helped:false}}),{owner:false,selected:'t1'});
 assert.ok(sel.log.some(e=>e[0]==='clock'),'a visitor tree (no started_at) draws and shows its clock when selected');
 const shapes=[];
 for(const sp of ['apple','pear','cherry','plum','apricot','peach','pomegranate'])for(const h of [0,3,8,30,120]){
  const r=await drawn(tree({species:sp,harvests:h,fruit:ripe,look:sp==='pear'&&h===120?'bergamot':null}));
  assert.ok(r.box.x0>=b.x0&&r.box.x1<=b.x1&&r.box.y0>=b.y0,`${sp} at ${h} harvests fits objectBounds: ${JSON.stringify(r.box)}`);
  if(h===8)shapes.push(colKey(r));
 }
 assert.equal(new Set(shapes).size,7,'every species has its own colours');
 assert.ok((await drawn(tree({harvests:120,fruit:ripe}))).log.some(e=>e[0]==='text'&&e[1]==='100'),'the century plaque');
 assert.ok(cols(await drawn(tree({species:'pomegranate',harvests:0,fruit:{started_at:0,ready_at:1e6}}))).has('#6f5a44'),'the pomegranate grows in a tub');
});

test('care marks: owner only, the birdhouse takes the pest, dry branches only with prune data, the golden fruit when ripe',async()=>{
 const pest={started_at:0,ready_at:1e6,pest:'caterpillar',golden:false},cap='#d9553f';
 assert.ok(cols(await drawn(tree({harvests:8,fruit:pest}))).has(cap),'a caterpillar in a cap');
 assert.ok(!cols(await drawn(tree({harvests:8,fruit:pest}),{owner:false})).has(cap),'a guest never sees the care state');
 const watched=await drawn(tree({harvests:8,fruit:pest}),{objects:[{type:'birdhouse',x:5,y:6,w:1,h:1}]});
 assert.ok(!cols(watched).has(cap)&&cols(watched).has('#3f4352'),'a starling of the near birdhouse instead of the pest');
 assert.ok(cols(await drawn(tree({harvests:8,prune_at:7,fruit:pest}))).has('#9c8b74'),'dry branches');
 const guestOld=tree({harvests:8,fruit:{ready_at:1e6,helped:false}});
 assert.ok(!cols(await drawn(guestOld,{owner:false})).has('#9c8b74'));
 assert.ok(cols(await drawn(tree({harvests:8,fruit:{started_at:0,ready_at:100,golden:true}}))).has('#f2c84a'),'the golden fruit');
 assert.ok(!cols(await drawn(tree({harvests:8,fruit:{started_at:0,ready_at:1e6,golden:true}}))).has('#f2c84a'),'only once it is ripe');
});

test('graft looks change the crown or the fruit; an unknown look is the plain species; the dormant look is off unless asked',async()=>{
 const ripe={started_at:0,ready_at:100},plain=colKey(await drawn(tree({harvests:8,fruit:ripe})));
 for(const look of ['paradise','cozy','frost','bloom'])assert.notEqual(colKey(await drawn(tree({harvests:8,fruit:ripe,look}))),plain,look);
 assert.equal(colKey(await drawn(tree({harvests:8,fruit:ripe,look:'festival_next'}))),plain);
 assert.ok(colKey(await drawn(tree({species:'pear',harvests:8,fruit:ripe,look:'bergamot'})))!==colKey(await drawn(tree({species:'pear',harvests:8,fruit:ripe}))));
 const winter=await drawn(tree({harvests:8,fruit:{started_at:0,ready_at:1e6}}),{winter:true});
 assert.ok(cols(winter).has('#f4f7f8')&&!cols(winter).has('#6f966b'),'bare limbs with snow caps');
});

test('drawObject sends trees and birdhouses to their own drawing, and the title of a tree is its species',async()=>{
 const {FarmScene}=await import('../../qw_farm/static/scene.js');
 const log=[];
 const scene=Object.create(FarmScene.prototype);
 Object.assign(scene,{catalog,selected:null,orchardTree(o){log.push('tree:'+o.species)},birdhouse(){log.push('bird')},footprint(){}});
 scene.drawObject(tree());scene.drawObject({id:'b',type:'birdhouse',x:1,y:1,w:1,h:1});
 assert.deepEqual(log,['tree:apple','bird']);
 assert.equal(scene.title(tree()),'Яблоня');
});

test('the app wires the orchard: tab, seeds, counters, placement, card, asset list',()=>{
 const app=read('qw_farm/static/app.js'),api=read('qw_farm/api.py');
 assert.ok(app.includes("import * as ORCH from './orchard.js'"));
 assert.ok(app.includes("['orchard','orchard','Сад']")&&app.includes("orchard:typeof renderOrchard==='function'?renderOrchard:undefined"),'a «Сад» tab');
 assert.equal((app.match(/!c\.exotic&&!c\.orchard/g)||[]).length,3,'the seed bar and both tractor lists hide the orchard fruit');
 assert.ok(app.includes('due(o.fruit?.ready_at)'),'a ripening tree refreshes the panel');
 assert.ok(app.includes("||ORCH.ripe(o,now())).length;$('harvest-all')")&&app.includes("||(o.type==='tree'&&o.fruit&&o.fruit.ready_at<=t)).length,animals"),'trees are counted in «Собрать урожай»');
 assert.ok(app.includes('ORCH.plantCommand(p.spec,cell)'),'a sapling is placed through plant_tree');
 assert.ok(app.includes("else if(o.type==='tree'){renderTree(o,p);return;")&&app.includes('function confirmUproot'));
 assert.ok(app.includes("o.type!=='tree'&&!['house','barn']"),'trees are not listed as workshops');
 assert.ok(api.includes("'orchard.js'")&&fs.existsSync(path.join(STATIC,'orchard.js')));
});

test('the new client code adds no tiny text and no raw colours of its own',()=>{
 const src=read('qw_farm/static/orchard.js');
 assert.ok(!/font-size|#[0-9a-f]{3,6}/i.test(src));
});

test('the seed bar keeps saplings out and stays one row, the merchant explains a graft without a tree, no screen of saplings has a primary button',async()=>{
 const app=read('qw_farm/static/app.js'),M=await load('merchant.js');
 const seeds=app.slice(app.indexOf('function renderSeeds'),app.indexOf('function seedLine'));
 assert.ok(seeds.includes('!c.exotic&&!c.orchard'),'orchard saplings are not seeds');
 assert.ok(!seeds.includes('Плодовые деревья'),'no long hint in the seed bar: the vertical label class made it half a screen tall');
 assert.equal((seeds.match(/'seedbar-label'/g)||[]).length,1,'only the short «ПОСАДИТЬ» label is vertical');
 assert.ok(!app.includes("selectTab('orchard')"),'one path to the tab: the rail, not a second button');
 assert.equal(M.slotBlock({status:'notree',left:1,price:10,kind:'graft'},1000),'Нужно посаженное дерево');
 const render=app.slice(app.indexOf('function renderOrchard'),app.indexOf('function renderTree'));
 assert.ok(render.includes("'secondary wide'")&&!render.includes("'primary wide'"));
});
