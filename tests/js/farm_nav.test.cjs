// Farm navigation (FARM_FEEDBACK E1/E8, UI_RULES §6.1): one menu with five sections, the catalogue behind «Всё», «Недавнее».
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const STATIC=path.join(__dirname,'../../qw_farm/static');
const read=name=>fs.readFileSync(path.join(STATIC,name),'utf8');
const load=()=>import(pathToFileURL(path.join(STATIC,'farm_nav.js')).href);

const catalog={
 crops:{wheat:{id:'wheat',name:'Пшеница',level:1,cost:2},rye:{id:'rye',name:'Рожь',level:30,cost:9},apple:{id:'apple',name:'Яблоко',orchard:true},fire:{id:'fire',name:'Огонь',exotic:true}},
 buildings:{
  mill:{id:'mill',name:'Мельница',level:1,cost:100,w:2,h:2},bakery:{id:'bakery',name:'Пекарня',level:2,cost:150,w:2,h:2},
  coop:{id:'coop',name:'Курятник',level:1,cost:100,w:2,h:2},road:{id:'road',name:'Грунтовая дорожка',level:1,cost:5,w:1,h:1,decor:true},
  flowerbed:{id:'flowerbed',name:'Клумба',level:1,cost:35,w:1,h:1,decor:true},palace:{id:'palace',name:'Дворец',level:40,cost:9e5,w:3,h:3},
  night_lantern:{id:'night_lantern',name:'Фонарь',level:1,cost:65,w:1,h:1,decor:true,secret:'night'},
  fd_cup:{id:'fd_cup',name:'Кубок',level:8,cost:0,w:1,h:1,decor:true,reward:true,source:'фонд деревни'},
  curio_a:{id:'curio_a',name:'Диковина',level:8,cost:0,w:1,h:1,decor:true,curio:true}},
 animals:{hens:{id:'hens',building:'coop',inputs:{feed:1},outputs:{egg:1}}},
 recipes:{pie:{building:'bakery',inputs:{apple:2,flour:1},outputs:{pie:1}},flour:{building:'mill',inputs:{wheat:3},outputs:{flour:1}}},
 items:{apple:{name:'Яблоко'},flour:{name:'Мука'},wheat:{name:'Пшеница'},pie:{name:'Яблочный пирог'},feed:{name:'Корм'},egg:{name:'Яйцо'}}
};
const me={level:10,coins:120,secrets:[],economy:{unlocked:[]},merchant:{curios:[]}};
const rows=[{id:'apple',name:'Яблоня',sapling:'Саженец яблони',level:1,cost:1920,locked:false,blocked:'',options:[{voucher:'free',qty:1,price:0,label:'Бесплатный'},{voucher:null,price:1920,qty:null,label:'За монеты'}]},
 {id:'cherry',name:'Вишня',sapling:'Саженец вишни',level:20,cost:3000,locked:true,blocked:'С 20 уровня',options:[{voucher:null,price:3000,qty:null}]}];

test('the menu has five sections in the approved order with one entry per place',async()=>{
 const N=await load();
 assert.deepEqual(N.MENU.map(s=>s.title),['Хозяйство','Производство','За околицей','Деревня и соседи','Сведения']);
 assert.deepEqual(N.MENU_TABS,['orders','inventory','team','land','production','orchard','forest','lake','fields','village','neighbors','festival','secrets','journal']);
 assert.equal(new Set(N.MENU_TABS).size,N.MENU_TABS.length,'no place twice');
 for(const gone of ['build','more','settings','objects'])assert.ok(!N.MENU_TABS.includes(gone),`${gone} is not a menu place`);
 const plain=N.menuSections({});assert.ok(!plain.flatMap(s=>s.items).some(i=>i.id==='festival'),'«Праздник» only while a festival runs');
 assert.ok(N.menuSections({festival:'Посиделки'}).flatMap(s=>s.items).some(i=>i.id==='festival'));
 assert.equal(N.menuSections({}).find(s=>s.id==='outside').art,true,'За околицей are picture cards');
});

test('counters: orders ready, workshops done, saplings waiting, requests; the «Меню» button sums them',async()=>{
 const N=await load(),f={ordersReady:3,orders:5,workshopsReady:2,readyWorkshop:'Пекарня',saplings:1,requests:1,fieldsLocked:22,size:10,canExpand:true,secretsFound:2,secretsTotal:4};
 const items=Object.fromEntries(N.menuSections(f).flatMap(s=>s.items).map(i=>[i.id,i]));
 assert.equal(items.orders.badge,3);assert.equal(items.orders.status,'3 можно сдать');
 assert.equal(items.production.badge,2);assert.equal(items.production.status,'готово: 2');
 assert.equal(items.orchard.badge,1);assert.equal(items.orchard.status,'саженец ждёт посадки');
 assert.equal(items.neighbors.badge,1);assert.equal(items.neighbors.status,'ждут ответа: 1');
 assert.equal(items.fields.status,'С 22 ур.');assert.equal(items.fields.locked,true);
 assert.equal(items.land.status,'10 × 10 · можно расширить');assert.equal(items.secrets.status,'2 из 4');
 assert.equal(N.menuTotal(f),7);assert.equal(N.menuTotal({}),0);
});

test('catalogue: crops, a new bed, buildings by section, trees; gating of the former «Строить» tab',async()=>{
 const N=await load(),objects=[{type:'mill'},{type:'mill'},{type:'tree',species:'apple'}];
 const e=N.catalogEntries(catalog,me,objects,rows),by=k=>e.find(x=>x.key===k);
 assert.ok(!by('crop:apple')&&!by('crop:fire'),'orchard fruit and exotic crops are not seeds');
 assert.equal(by('crop:rye').locked,true);assert.equal(by('crop:rye').lock,'С 30 ур.');
 assert.equal(by('b:plot').section,'plots');assert.equal(by('b:mill').section,'workshops');assert.equal(by('b:coop').section,'animals');
 assert.equal(by('b:flowerbed').section,'decor');assert.equal(by('b:road').section,'roads');assert.equal(by('t:apple').section,'trees');
 assert.equal(by('b:mill').have,2,'«Есть: N» counts what is already placed');assert.equal(by('t:apple').have,1);assert.equal(by('t:apple').saplings,1);
 assert.equal(by('b:palace').lock,'С 40 ур.');assert.equal(by('b:night_lantern').lock,'Найди в «Находках»');
 assert.match(by('b:fd_cup').lock,/^Награда фонда деревни/);assert.equal(by('b:curio_a'),undefined,'an unowned curio is hidden');
 assert.ok(N.catalogEntries(catalog,{...me,merchant:{curios:['curio_a']}},[],rows).some(x=>x.key==='b:curio_a'));
 assert.equal(by('b:bakery').poor,true,'not enough coins');assert.equal(by('b:mill').poor,false);
 assert.equal(by('t:cherry').locked,true);
 const firstLocked=e.findIndex(x=>x.locked);assert.ok(e.slice(firstLocked).every(x=>x.locked),'open first, locked after');
 assert.deepEqual(Object.keys(N.sectionCounts(e)),['plots','trees','workshops','animals','decor','roads']);
});

test('search finds by name and by product: buildings that process it and orders that need it',async()=>{
 const N=await load(),e=N.catalogEntries(catalog,me,[],rows);
 const r=N.searchCatalog(e,'ябл',catalog,[{id:'o1',title:'Пирог',npc:'Сорока',needs:{pie:1}},{id:'o2',title:'Мука',npc:'Филиныч',needs:{flour:2}}]);
 assert.deepEqual(r.groups.map(g=>g.id),['trees','uses']);
 assert.deepEqual(r.groups[1].entries.map(x=>x.id),['bakery']);assert.match(r.groups[1].title,/^Перерабатывают: яблоко/);
 assert.deepEqual(r.orders.map(o=>o.id),['o1'],'«Яблочный пирог» matches the query too');
 assert.deepEqual(N.searchCatalog(e,'ё',catalog).groups,[],'one letter does not search');
 assert.deepEqual(N.searchCatalog(e,'ЁЛКА',catalog).groups,[]);
 assert.deepEqual(N.searchCatalog(e,'мельн',catalog).groups.map(g=>g.id),['workshops']);
});

test('«Недавнее»: newest first, no repeats, four at most, per farm, survives blocked storage',async()=>{
 const N=await load();let list=[];
 for(const k of ['b:road','t:apple','b:road','b:mill','b:coop','b:flowerbed'])list=N.pushRecent(list,k);
 assert.deepEqual(list,['b:flowerbed','b:coop','b:mill','b:road']);
 const mem=new Map(),store={getItem:k=>mem.get(k)??null,setItem:(k,v)=>mem.set(k,v)};
 N.saveRecent(store,'farm-a',list);assert.deepEqual(N.loadRecent(store,'farm-a'),list);assert.deepEqual(N.loadRecent(store,'farm-b'),[]);
 const broken={getItem(){throw new Error('denied')},setItem(){throw new Error('denied')}};
 assert.deepEqual(N.loadRecent(broken,'farm-a'),[]);assert.doesNotThrow(()=>N.saveRecent(broken,'farm-a',list));
 mem.set('qw-farm.recent.farm-c','{bad');assert.deepEqual(N.loadRecent(store,'farm-c'),[]);
 assert.equal(N.bestOption(rows[0]).voucher,'free','a free sapling first');assert.equal(N.bestOption(rows[1]).voucher,null);
});

test('app wiring: one menu in #rail, «Меню» on a phone, header picture cards kept, catalogue and placement',()=>{
 const app=read('app.js'),html=read('index.html'),css=read('style.css'),api=read('../api.py');
 assert.ok(api.includes("'farm_nav.js'"),'the module is served');assert.ok(app.includes("import * as NAV from './farm_nav.js'"));
 // The owner asked to keep the picture cards in the header (2026-10-24): «За околицей» is reachable from the menu and the header.
 for(const id of ['forest-door','fields-door'])assert.ok(html.includes(`id="${id}"`),`${id} is in the header`);
 for(const id of ['lake-door','village-card-door','farm-card-door'])assert.ok(app.includes(`'${id}'`),`${id} is built into the header`);
 assert.ok(!/body:not\(\.village-open\):not\(\.farm-visit\) \.header-destinations\{display:none/.test(css),'the header strip is not hidden on the own farm');
 assert.ok(!html.includes('id="village-door"')&&!app.includes("'village-door'"),'no extra village chip on the map');
 assert.ok(html.includes('id="farm-menu-button"')&&html.includes('aria-controls="rail"'),'«Меню» next to «Собрать урожай»');
 assert.ok(html.indexOf('id="farm-menu-button"')<html.indexOf('id="harvest-all"'));
 assert.ok(!app.includes("['more','menu','Ещё']")&&!app.includes('function renderMore'),'no «Ещё»');
 assert.ok(!app.includes('function renderBuild')&&!app.includes("selectTab('build')"),'no «Строить» tab');
 assert.ok(app.includes('land:renderLand,catalog:renderCatalog'),'«Участок» and the catalogue are panels');
 assert.ok(/function renderLand\(p\)\{\n heading\('Участок'[^\n]*landExpansion\(p\)/.test(app),'land expansion moved to «Участок»');
 assert.ok(app.includes("navPush('panel',()=>{if(farmMenuOpen)closeFarmMenu();else closePanel();})"),'the menu sheet shares the panel back-stack entry');
 assert.ok(app.includes('if(!p.obj){rememberPlaced(p.spec);renderSeeds();}'),'a placement feeds «Недавнее»');
 assert.ok(/@media\(min-width:851px\)\{\n body\{--menu-w:248px\}/.test(css),'PC: a 248 px column');
 assert.ok(!app.includes("'seedbar-label'"),'the vertical label class is not reused');
 assert.ok(read('scene.js').includes(' thumb(spec){'),'catalogue miniatures come from the scene drawing');
});

// «(i)» details (FARM_FEEDBACK E13): only catalogue numbers, missing fields are left out, nothing is chosen or placed.
test('entry details: crop, building with recipes and upgrades, animal house, decor — from the catalogue only',async()=>{
 const N=await load(),cat={...catalog,
  crops:{...catalog.crops,wheat:{id:'wheat',name:'Пшеница',level:1,cost:2,seconds:30,yield_qty:3,xp:1}},
  items:{...catalog.items,wheat:{name:'Пшеница',price:2}},
  recipes:{...catalog.recipes,flour:{name:'Смолоть муку',building:'mill',inputs:{wheat:3},outputs:{flour:1},seconds:60}},
  upgrades:{costs:{mill:{'2':{coins:200,items:{flour:4},level:4}}},kinds:{mill:'workshop'}},
  orchard:{rules:{cycle:86400,young:5,adult:20,century:100},trees:{apple:{id:'apple',name:'Яблоня',fruit:'apple',level:16,juvenile:1,yield_qty:10,cost:1920}},grafts:{g1:{species:'apple',name:'Райская яблоня'},g2:{species:'pear',name:'Бергамот'}}}};
 const h={duration:s=>`${s}с`,purpose:t=>t==='mill'?['Мелет урожай.']:[],levelEffect:(k,l)=>`${k}:${l}`,rent:{next:25}};
 const crop=N.entryInfo({kind:'crop',id:'wheat',name:'Пшеница'},cat,{...me,orders:[{title:'Хлеб',npc:'Ёж',needs:{wheat:2}}]},h);
 assert.deepEqual(crop.facts,[['Растёт','30с'],['Урожай','×3'],['Семена','2 мон.'],['Продажа','2 мон. за штуку'],['Опыт','+1 за сбор'],['Открывается','с 1 ур.']]);
 assert.deepEqual(crop.sections.map(s=>s.title),['Где используется','Нужно в заказах']);assert.ok(crop.sections[0].lines.includes('Смолоть муку (Мельница)'));
 assert.equal(crop.action.label,'Посадить');
 const mill=N.entryInfo({kind:'building',id:'mill',name:'Мельница',have:2},cat,me,h);
 assert.equal(mill.lead,'Мелет урожай.');assert.ok(mill.facts.some(([k,v])=>k==='На ферме'&&v==='2'));assert.ok(mill.facts.some(([k,v])=>k==='Размер'&&v==='2×2'));
 assert.ok(mill.sections.find(s=>s.title==='Рецепты').lines.includes('Смолоть муку: Пшеница ×3 → Мука ×1 · 60с'));
 assert.deepEqual(mill.sections.find(s=>s.title==='Улучшения').lines,['Ур. 2: 200 мон. и Мука ×4, с 4 ур. фермы — workshop:2']);
 const coop=N.entryInfo({kind:'building',id:'coop',name:'Курятник'},cat,me,h);
 assert.ok(coop.sections.find(s=>s.title==='Животные').lines[0].startsWith('hens'),'animal line from the catalogue (name falls back to the record)');
 const bed=N.entryInfo({kind:'building',id:'flowerbed',name:'Клумба'},cat,me,{});
 assert.equal(bed.lead,'Декор');assert.ok(bed.facts.some(([k])=>k==='Содержание'));assert.equal(bed.action.label,'Поставить');
 const tree=N.entryInfo({kind:'tree',id:'apple',name:'Яблоня'},cat,me,h);
 assert.ok(tree.facts.some(([k,v])=>k==='Первый урожай'&&v==='через 172800с'));assert.ok(tree.facts.some(([k,v])=>k==='Аренда'&&v.includes('25')));
 assert.deepEqual(tree.sections.find(s=>s.title==='Прививки').lines,['Райская яблоня'],'only grafts of this species');
 assert.ok(!N.entryInfo({kind:'tree',id:'apple',name:'Яблоня'},cat,me,{}).facts.some(([k])=>k==='Аренда'),'no rent line without rent data');
 assert.equal(N.entryInfo({kind:'crop',id:'nope',name:'?'},cat,me,h),null);
});
test('entry details wiring: (i) is a sibling of the card, a long press opens details without choosing or placing',()=>{
 const app=read('app.js'),css=read('style.css');
 assert.ok(app.includes("const cell=el('div',null,'catalog-cell');cell.append(b,infoButton(e));return cell;"),'no button inside a button');
 const info=app.slice(app.indexOf('function showEntryInfo('),app.indexOf('function bindInfoPress('));
 assert.ok(!/S\.seed=|beginPlacement\(/.test(info.replace("()=>{$('dialog').close();placeEntry(e);}",'')),'opening details neither picks a seed nor starts placement');
 assert.ok(info.includes("ev.stopPropagation();showEntryInfo(e)"),'the (i) does not reach the card');
 const press=app.slice(app.indexOf('function bindInfoPress('),app.indexOf('\n}\n',app.indexOf('function bindInfoPress(')));
 assert.ok(press.includes('ev.stopImmediatePropagation()')&&press.includes("'contextmenu'"),'the click after a long press is swallowed; right click opens details');
 assert.ok(app.includes("bindInfoPress(b,()=>({kind:'crop'")&&app.includes('bindInfoPress(b,()=>e)'),'crops and «Недавнее» in the strip');
 assert.ok(/\.entry-info-btn\{[^}]*width:var\(--qw-tap\);height:var\(--qw-tap\)/.test(css),'the (i) target is 44 px');
});
