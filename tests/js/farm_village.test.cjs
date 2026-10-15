const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
const block=source.slice(source.indexOf('// Living village uses existing personal orders'),source.indexOf('/* ---- r9 stage 15B:'));
const declarations=source.slice(source.indexOf('const VILLAGE_VOICES='),source.indexOf('const fmt='));
class Node{
 constructor(tag){this.tagName=tag;this.children=[];this.dataset={};this.attrs={};this.style={};this.hidden=false;this.replaces=0;this.classList={add(){},remove(){}};}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=nodes;this.replaces++;}
 setAttribute(k,v){this.attrs[k]=v;}
 focus(){this.focused=true;}
 querySelector(){return null;}
 querySelectorAll(selector){const all=this.children.flatMap(n=>n instanceof Node?[n,...n.querySelectorAll('*')]:[]);return selector==='*'?all:all.filter(n=>selector.includes('data-village-npc')?n.dataset.villageNpc||n.dataset.villageTownhall:selector==='.village-services'?n.className==='village-services':false);}
}
const AC=h=>h.nodes.get('village-scene').children[0].children.find(n=>n.className==='village-actors');
function setup(){
 const nodes=new Map(),area=new Node('section'),calls=[],pause=[],bodyClasses=new Set();
 const S={me:{id:'own',is_owner:true,orders:[{id:'one',npc:'Филиныч',title:'Чай',needs:{tea:2},coins:100,xp:10}],inventory:{tea:2},market:{}},farm:{id:'guest'},tab:'orders',catalog:{market:{tastes:{'Филиныч':['tea'],'Агата':['bread']}}},village:null};
 nodes.set('farm-canvas',new Node('canvas'));nodes.set('panel-content',new Node('div'));nodes.set('panel-head',new Node('div'));const sheetFocus=new Node('section'),title=new Node('h2');nodes.get('panel-content').querySelector=()=>sheetFocus;nodes.get('panel-head').querySelector=()=>title;
 const ctx={S,AVATARS:{},document:{activeElement:null,body:{classList:{toggle:(k,v)=>v?bodyClasses.add(k):bodyClasses.delete(k),add:k=>bodyClasses.add(k),remove:k=>bodyClasses.delete(k),contains:k=>bodyClasses.has(k)}},querySelector:()=>area},
 $:id=>nodes.get(id),el:(tag,text,cls)=>{const n=new Node(tag);n.textContent=text;n.className=cls;return n;},icon:()=>new Node('svg'),
 button:(text,fn,cls,disabled)=>{const n=new Node('button');n.textContent=text;n.onclick=fn;n.disabled=disabled;return n;},
 scene:{setPaused:v=>pause.push(v),set:()=>calls.push('scene'),selected:'x',resize(){}},farmViewEpoch:4,requestAnimationFrame:fn=>fn(),
 eco:()=>({fund_open:ctx.openFund}),ECON:()=>({fund_level:8}),repInfo:()=>({lv:1,bonus:5}),repBar:()=>new Node('div'),
 enough:needs=>Object.entries(needs).every(([k,v])=>S.me.inventory[k]>=v),
 command:async(kind,data)=>{calls.push([kind,data]);S.busy=true;return true;},fmt:String,
 card:(name)=>{const n=new Node('section');n.textContent=name;return n;},goods:()=>new Node('div'),note:(text,p)=>p.append(new Node(text)),
 showPanel(){bodyClasses.add('panel-open');bodyClasses.delete('panel-collapsed');},renderPanel(){ctx.syncVillageScene();},renderRail(){},updateHUD(){},renderSeeds(){},meter:()=>new Node('div'),heading(){},fundCard(){},upkeepCard(){},decorShop(){},openFund:false};
 // Register dynamically created scene exactly as a browser's getElementById would.
 area.append=n=>nodes.set(n.id,n);
 vm.createContext(ctx);vm.runInContext(declarations+block+'\n'+source.slice(source.indexOf('function selectTab(id)'),source.indexOf('let seedCardVisible'))+'\n'+source.slice(source.indexOf('function closePanel()'),source.indexOf('function showPanel()'))+'\nObject.assign(globalThis,{closePanel,exitVillage,resetVillageView,openVillageTownHall,villageStage,villageOrders,deliverVillageOrder,chooseVillageResident,syncVillageScene,renderVillageResident,selectTab,syncScenePause})',ctx);
 return {ctx,S,nodes,calls,pause,bodyClasses,sheetFocus,title};
}
test('entering village from guest routes to own farm and invalidates older requests',()=>{
 const h=setup();h.ctx.selectTab('village');assert.equal(h.S.farm,h.S.me);assert.equal(h.S.tab,'village');assert.equal(h.ctx.farmViewEpoch,5);assert.ok(h.calls.includes('scene'));assert.equal(h.bodyClasses.has('panel-open'),false);assert.equal(h.bodyClasses.has('panel-collapsed'),true);const world=AC(h);assert.equal(world.children.filter(n=>n.dataset.villageNpc&&n.attrs['aria-pressed']==='true').length,0);
});
test('one real request delivers through the existing order command, a busy repeat does not',async()=>{
 const h=setup();h.S.tab='village';h.ctx.chooseVillageResident('Филиныч');assert.equal(await h.ctx.deliverVillageOrder('one'),true);assert.equal(await h.ctx.deliverVillageOrder('one'),false);
 assert.equal(h.calls.length,1);assert.equal(h.calls[0][0],'order');assert.equal(h.calls[0][1].order,'one');
});
test('absent order and insufficient own goods never submit a command',async()=>{
 const h=setup();h.S.tab='village';h.ctx.chooseVillageResident('Филиныч');assert.equal(await h.ctx.deliverVillageOrder('missing'),false);h.S.me.inventory.tea=1;assert.equal(await h.ctx.deliverVillageOrder('one'),false);h.ctx.chooseVillageResident('Агата');assert.equal(h.ctx.villageOrders('Агата').length,0);assert.equal(h.calls.length,0);
});
test('season is locked without owner projection and stages use shared total only',()=>{
 const h=setup();h.S.village={total:1000,goal:1000};assert.equal(h.ctx.villageStage(),null);h.ctx.openFund=true;
 for(const [total,expected]of [[0,0],[250,1],[600,2],[1000,3]]){h.S.village.total=total;assert.equal(h.ctx.villageStage(),expected);}h.S.village=null;assert.equal(h.ctx.villageStage(),null);
});
test('scene does not rebuild on identical refresh; pause remains owned by village or field game',()=>{
 const h=setup();h.S.tab='village';h.ctx.syncVillageScene();const root=h.nodes.get('village-scene'),act=AC(h);assert.equal(root.replaces,1);assert.equal(act.replaces,1);assert.equal(h.pause.at(-1),true);h.ctx.syncVillageScene();assert.equal(act.replaces,1);
 h.ctx.chooseVillageResident('Агата');assert.equal(root.replaces,1,'world image and effects are never rebuilt');assert.equal(act.replaces,2);h.ctx.syncVillageScene();assert.equal(act.replaces,2);
 h.S.tab='fields';h.S.fieldGame={};h.ctx.syncVillageScene();assert.equal(root.hidden,true);assert.equal(h.pause.at(-1),true);h.S.fieldGame=null;h.ctx.syncScenePause();assert.equal(h.pause.at(-1),false);
});
test('resident buttons are native accessible controls and data changes preserve selection',()=>{
 const h=setup();h.S.tab='village';h.ctx.syncVillageScene();h.ctx.chooseVillageResident('Агата');h.S.me.orders.push({id:'two',npc:'Агата'});h.ctx.syncVillageScene();
 const residents=AC(h).children.filter(n=>n.dataset.villageNpc);assert.equal(residents[1].attrs['aria-pressed'],'true');assert.match(residents[1].attrs['aria-label'],/есть просьба/);assert.equal(residents[1].tagName,'button');assert.equal(residents[0].attrs['aria-controls'],'panel-content');assert.equal(residents[1].style.left,`${vm.runInContext('VILLAGE_SPOTS',h.ctx)['Агата'][0]}%`);
});

test('panel refresh retains focused service, open section and scroll position',()=>{
 const h=setup();h.ctx.openVillageTownHall();h.S.lastRenderedTab='village';h.S.lastRenderedVillageSheet=JSON.stringify(['townhall',null]);
 const oldService=new Node('details');oldService.dataset.villageService='Фонд и праздник';oldService.open=true;
 const oldFocus=new Node('summary');oldFocus.dataset.villageFocus='service:Фонд и праздник';h.ctx.document.activeElement=oldFocus;
 const panel=new Node('div');panel.services=[oldService];panel.focuses=[];
 let scroll=123;
 // Browsers clamp scrollTop to the shorter content when details are closed.
 // Opening them later cannot restore the position that was already discarded.
 Object.defineProperty(panel,'scrollTop',{get:()=>scroll,set:value=>{scroll=Math.min(value,panel.services.some(n=>n.open)?500:20);}});
 panel.querySelectorAll=selector=>selector==='.village-services[open]'?panel.services.filter(n=>n.open):selector==='.village-services'?panel.services:panel.focuses;
 panel.querySelector=()=>null;h.nodes.set('panel-content',panel);
 h.ctx.own=()=>true;h.ctx.panelSnapshot=()=>'';h.ctx.panelRenderSignature='';
 for(const name of ['renderOrders','renderInventory','renderBuild','renderProduction','renderNeighbors','renderJournal','renderSettings','renderObject','renderObjects','renderTeam','renderForest','renderSecrets','renderMore','renderFields'])h.ctx[name]=()=>{};
 h.ctx.renderVillage=()=>{const next=new Node('details');next.dataset.villageService='Фонд и праздник';panel.services=[next];const focus=new Node('summary');focus.dataset.villageFocus='service:Фонд и праздник';panel.focuses=[focus];};
 const code=source.slice(source.indexOf('function renderPanel()'),source.indexOf('/* ---- building upgrades'));
 vm.runInContext(code+'\nthis.renderPanel=renderPanel',h.ctx);h.ctx.renderPanel();
 assert.equal(panel.services[0].open,true);assert.equal(panel.focuses[0].focused,true);assert.equal(panel.scrollTop,123);
 vm.runInContext("villageSheet='resident';villageResident='Филиныч'",h.ctx);h.ctx.renderPanel();assert.equal(panel.scrollTop,0,'a newly selected resident starts at the top instead of inheriting town hall scroll');panel.scrollTop=123;h.ctx.renderPanel();assert.equal(panel.scrollTop,123,'refresh of the same resident preserves scroll');
});


test('resident tap opens a sheet; close returns focus to the place and stays in village',()=>{
 const h=setup();h.ctx.selectTab('village');h.ctx.chooseVillageResident('Филиныч');assert.equal(h.bodyClasses.has('panel-open'),true);assert.equal(h.sheetFocus.focused,true);
 h.ctx.closePanel();assert.equal(h.S.tab,'village');assert.equal(h.bodyClasses.has('panel-open'),false);assert.equal(h.pause.at(-1),true);
 const resident=AC(h).children.find(n=>n.dataset.villageNpc==='Филиныч');assert.equal(resident.focused,true);assert.equal(resident.attrs['aria-pressed'],'false');
 h.ctx.exitVillage();assert.equal(h.S.tab,'orders');assert.equal(h.pause.at(-1),false);assert.equal(h.nodes.get('farm-canvas').inert,false);
});
test('town hall opens services without implicitly selecting a resident',()=>{
 const h=setup();h.ctx.selectTab('village');h.ctx.openVillageTownHall();assert.equal(h.bodyClasses.has('panel-open'),true);assert.equal(h.title.focused,true);assert.equal(h.title.tabIndex,-1);
 const world=AC(h);assert.equal(world.children.find(n=>n.dataset.villageTownhall).attrs['aria-pressed'],'true');assert.equal(world.children.filter(n=>n.dataset.villageNpc&&n.attrs['aria-pressed']==='true').length,0);
 h.ctx.closePanel();assert.equal(h.S.tab,'village');assert.ok(world.children.length>0);assert.equal(AC(h).children.find(n=>n.dataset.villageTownhall).focused,true);
});
test('village artwork is a large external SVG world served by allowlist and scrolls inside the scene',()=>{
 const svg=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/village.svg'),'utf8');assert.match(svg,/viewBox="0 0 2400 1800"/);assert.match(svg,/preserveAspectRatio="xMidYMid meet"/);
 const api=fs.readFileSync(path.join(__dirname,'../../qw_farm/api.py'),'utf8');assert.match(api,/ASSETS=.*'village.svg'/);
 const css=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/style.css'),'utf8');assert.match(css,/\.village-scene\{[^}]*overflow:auto/);assert.match(css,/\.village-world\{[^}]*width:clamp\(1600px,250cqw,3200px\);aspect-ratio:4\/3/);assert.match(css,/object-fit:contain/);
 assert.doesNotMatch(css,/\.village-scene\{[^}]*overflow-x:hidden/);
});

test('login and new account reset the old resident, sheet and scene state',()=>{
 const h=setup();h.ctx.selectTab('village');h.ctx.chooseVillageResident('Филиныч');h.S.me=null;h.ctx.resetVillageView();assert.equal(h.bodyClasses.has('village-open'),false);assert.equal(h.nodes.get('village-scene').hidden,true);assert.equal(h.pause.at(-1),false);
 h.S.me={id:'another',orders:[],inventory:{},market:{}};h.ctx.resetVillageView();const world=AC(h);assert.equal(world.children.filter(n=>n.dataset.villageNpc&&n.attrs['aria-pressed']==='true').length,0);assert.equal(world.children.find(n=>n.dataset.villageTownhall).attrs['aria-pressed'],'false');
 const logout=source.slice(source.indexOf('function showLogin('),source.indexOf('function showRecovery('));assert.match(logout,/S\.me=S\.farm=null[\s\S]*resetVillageView\(\)/);
});

test('placing town hall decor returns to the farm before entering placement mode',()=>{
 const h=setup();h.ctx.selectTab('village');h.ctx.openVillageTownHall();h.ctx.renderPlacement=()=>{};
 const start=source.indexOf('function beginPlacement('),end=source.indexOf('\n',start);
 vm.runInContext(source.slice(start,end)+'\nthis.beginPlacement=beginPlacement',h.ctx);const spec={id:'flowerbed',w:1,h:1};h.ctx.beginPlacement(spec);
 assert.equal(h.S.tab,'orders');assert.equal(h.pause.at(-1),false);assert.equal(h.S.placing.spec,spec);assert.equal(h.nodes.get('farm-canvas').inert,false);
});
test('debt shortcut opens town hall services and all eight resident positions exist',()=>{
 const h=setup();h.S.farm=h.S.me;h.ctx.eco=()=>({debt:50});
 const start=source.indexOf('function hudDebt()'),end=source.indexOf('\n',start);
 vm.runInContext(source.slice(start,end)+'\nthis.hudDebt=hudDebt;this.spotCount=Object.keys(VILLAGE_SPOTS).length',h.ctx);
 h.ctx.hudDebt().onclick();assert.equal(h.S.tab,'village');assert.equal(h.bodyClasses.has('panel-open'),true);assert.equal(h.title.focused,true);assert.equal(h.ctx.spotCount,8);
});

test('world keeps 44px targets without overlap at phone and desktop widths; walking and HUD exist',()=>{
 const h=setup();const positions=Object.values(vm.runInContext('VILLAGE_SPOTS',h.ctx)),hallPos=vm.runInContext('VILLAGE_HALL',h.ctx),gatePos=vm.runInContext('VILLAGE_GATE',h.ctx);
 for(const availableWidth of [320,360,390,430,1280,1920]){
  const width=Math.min(3200,Math.max(1600,availableWidth*2.5)),height=width*.75;
  const targets=positions.map(([x,y])=>({x:x*width/100,y:y*height/100,w:48,h:48}));targets.push({x:hallPos[0]/100*width,y:hallPos[1]/100*height,w:62,h:44});targets.push({x:gatePos[0]/100*width,y:gatePos[1]/100*height,w:96,h:48});
  for(const t of targets){assert.ok(t.x-t.w/2>=0&&t.x+t.w/2<=width);assert.ok(t.y-t.h/2>=0&&t.y+t.h/2<=height);assert.ok(t.w>=44&&t.h>=44);}
  for(let i=0;i<targets.length;i++)for(let j=i+1;j<targets.length;j++){const a=targets[i],b=targets[j];assert.ok(Math.abs(a.x-b.x)>=(a.w+b.w)/2||Math.abs(a.y-b.y)>=(a.h+b.h)/2,`targets ${i}/${j} overlap at ${availableWidth}`);}
 }
 h.S.tab='village';h.ctx.syncVillageScene();const world=AC(h);
 const wr=h.nodes.get('village-scene').children[0];assert.ok(wr.children.find(n=>n.dataset.villageGate),'gate button to the farm');assert.ok(wr.children.find(n=>n.className==='village-player'),'player figure');assert.ok(wr.children.find(n=>n.className==='village-fx'),'separate animated effects layer');
 const hud=h.nodes.get('village-hud');assert.ok(hud.children.find(n=>n.dataset.villageMinimap),'minimap');assert.equal(hud.hidden,false);
 h.S.tab='orders';h.ctx.syncVillageScene();assert.equal(hud.hidden,true);
 const css=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/style.css'),'utf8');assert.match(css,/prefers-reduced-motion:no-preference\)\{\s*\.village-walker\{animation/);
});
test('keyboard activation opens a resident at once, mouse click walks first and then opens',()=>{
 const h=setup();h.S.tab='village';h.ctx.syncVillageScene();
 const npc=()=>AC(h).children.find(n=>n.dataset.villageNpc==='Филиныч');
 npc().onclick({detail:0});assert.equal(vm.runInContext('villageResident',h.ctx),'Филиныч');
 vm.runInContext("villageResident=null;villageSheet=null;villageSceneSignature=''",h.ctx);h.ctx.syncVillageScene();
 npc().onclick({detail:1});assert.equal(vm.runInContext('villageResident',h.ctx),'Филиныч');
});
test('daily guests follow the date only, differ from each other, and place signs never cover residents',()=>{
 const h=setup();const today=vm.runInContext('villageVisitorsToday',h.ctx);
 for(let d=0;d<30;d++){const t=Date.UTC(2026,9,1+d,9),a=today(t),b=today(t+5*3600e3);assert.deepEqual(a.map(x=>x.v[0]),b.map(x=>x.v[0]),'same Moscow day, same guests');assert.notEqual(a[0].v[0],a[1].v[0]);assert.notDeepEqual(a[0].spot,a[1].spot);}
 const spots=Object.values(vm.runInContext('VILLAGE_SPOTS',h.ctx)).map(([x,y])=>({x,y,w:48,h:48}));const places=vm.runInContext('VILLAGE_PLACES',h.ctx).map(p=>({x:p[3],y:p[4],w:44,h:44}));const guests=vm.runInContext('VILLAGE_VISITOR_SPOTS',h.ctx).map(([x,y])=>({x,y,w:48,h:48}));const hall=vm.runInContext('VILLAGE_HALL',h.ctx),gate=vm.runInContext('VILLAGE_GATE',h.ctx);
 const all=[...spots,...places,...guests,{x:hall[0],y:hall[1],w:62,h:44},{x:gate[0],y:gate[1],w:132,h:48}];
 for(const width of [1600,3200]){const height=width*.75,T=all.map(t=>({x:t.x*width/100,y:t.y*height/100,w:t.w,h:t.h}));
  for(let i=0;i<T.length;i++)for(let j=i+1;j<T.length;j++){const a=T[i],b=T[j];assert.ok(Math.abs(a.x-b.x)>=(a.w+b.w)/2||Math.abs(a.y-b.y)>=(a.h+b.h)/2,`targets ${i}/${j} overlap at ${width}`);}}
});
