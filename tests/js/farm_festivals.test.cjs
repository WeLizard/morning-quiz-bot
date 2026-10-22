const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');

const STATIC=path.join(__dirname,'../../qw_farm/static');
const load=()=>import(pathToFileURL(path.join(STATIC,'festivals.js')).href);
const memory=(seed={})=>{const m=new Map(Object.entries(seed));return {getItem:k=>m.has(k)?m.get(k):null,setItem:(k,v)=>m.set(k,v)};};
const blocked={getItem(){throw Error('denied')},setItem(){throw Error('denied')}};

class Node{
 constructor(tag,text,cls){this.tag=tag;this.text=text??'';this.cls=cls||'';this.children=[];this.dataset={};this.classList={add:c=>{this.cls+=' '+c;}};}
 append(...n){this.children.push(...n);}
}
function walk(n,out=[]){out.push(n);for(const c of n.children||[])walk(c,out);return out;}
function helpers(over={}){
 const calls=[];
 const el=(tag,text,cls)=>new Node(tag,text,cls);
 const button=(text,fn,cls,disabled)=>{const b=new Node('button',text,cls);b.onclick=fn;b.disabled=!!disabled;return b;};
 const card=(title,sub)=>{const c=new Node('section',title,'card');c.sub=sub;return c;};
 const goods=needs=>new Node('div',JSON.stringify(needs),'goods');
 const icon=id=>new Node('svg',id,'icon');
 const note=(text,p)=>p.append(new Node('p',text,'note'));
 const checkbox=(label,value)=>{const w=new Node('label',label),i=new Node('input');i.checked=value;w.append(i);return [w,i];};
 return {calls,el,button,card,goods,icon,note,checkbox,stock:id=>({yarn:5,pie:0}[id]||0),fmt:n=>String(n),itemName:id=>id,
  command:(kind,data)=>{calls.push([kind,data]);return Promise.resolve(true);},busy:()=>false,coins:()=>5000,rerender(){},...over};
}
const fairView={
 current:{id:'posidelki',name:'Посиделки',phase:'fair',host:'Соня',starts_at:100,ends_at:200},
 upcoming:null,birthday:null,past_markup_pct:150,collection:{},past:[],
 fair:{id:'posidelki',name:'Посиделки',key:'posidelki-2026',host:'Соня',magpie:false,ends_at:200,todo:false,
  keepsake:{id:'fest_posid_socks',name:'Носки года',got:false},
  tasks:[
   {id:'yarn',title:'Пряжа для общего клубка',host:'Соня',level:5,options:[{yarn:4},{wool:6}],done:false,locked:false,reward:{id:'fest_posid_basket',name:'Корзинка'}},
   {id:'tea',title:'Пироги к чаю',host:'Агата',level:3,options:[{pie:3}],done:true,locked:false,reward:{id:'fest_posid_smoke',name:'Дымок'}}],
  goods:[
   {id:'fest_posid_wreath',name:'Венок',kind:'wall',seller:'agata',level:5,price:1000,status:'ok',note:'',away:false},
   {id:'fest_posid_quilt',name:'Одеяло',kind:'decor_big',seller:'agata',level:20,price:9000,status:'locked',note:'',away:false},
   {id:'fest_posid_lantern',name:'Фонарик',kind:'curio',seller:'magpie',level:10,price:2000,status:'ok',note:'',away:true}]}};

test('decorations are shown by default, can be hidden, and a blocked storage never breaks the page',async()=>{
 const F=await load();
 assert.equal(F.decorOn(memory()),true);assert.equal(F.decorOn(memory({[F.PREF_KEYS.decor]:'off'})),false);
 assert.equal(F.decorOn(blocked),true);assert.equal(F.scaresOn(blocked),true);
 assert.doesNotThrow(()=>F.setPref('decor',false,blocked));
 const store=memory();F.setPref('decor',false,store);assert.equal(F.decorOn(store),false);
});

test('world flags: scares exist only on the Pumpkin Night and sit on top of the decor switch',async()=>{
 const F=await load();
 const pumpkin={current:{id:'pumpkin_night',phase:'fair'},birthday:{years:2}};
 assert.deepEqual(F.worldFlags(pumpkin,memory()),{festival:'pumpkin_night',phase:'fair',decor:true,scares:true,birthday:2});
 assert.equal(F.worldFlags(pumpkin,memory({[F.PREF_KEYS.scares]:'off'})).scares,false);
 assert.equal(F.worldFlags(pumpkin,memory({[F.PREF_KEYS.decor]:'off'})).scares,false,'hidden decor hides scares too');
 assert.equal(F.worldFlags({current:{id:'posidelki',phase:'decor'}},memory()).scares,false);
 assert.deepEqual(F.worldFlags(null,memory()),{festival:'',phase:'',decor:false,scares:false,birthday:0});
});

test('applyWorld writes and clears the data-festival hooks the scene layers read',async()=>{
 const F=await load(),root={dataset:{}},store=memory();
 F.applyWorld(fairView,root,store);
 assert.deepEqual({...root.dataset},{festival:'posidelki',festivalPhase:'fair',festivalDecor:'on'});
 F.setPref('decor',false,store);F.applyWorld(fairView,root,store);assert.equal(root.dataset.festivalDecor,undefined);
 F.applyWorld(null,root,store);assert.deepEqual({...root.dataset},{});
 assert.equal(F.applyWorld(fairView,null,store),null);
});

test('tab visibility and the banner follow the server calendar',async()=>{
 const F=await load();
 assert.equal(F.tabVisible(null),false);assert.equal(F.tabVisible({current:null,upcoming:{soon:false},past:[],collection:{}}),false);
 assert.equal(F.tabVisible({current:null,upcoming:{soon:true},past:[],collection:{}}),true);
 assert.equal(F.tabVisible({current:null,upcoming:null,past:[],collection:{x:1}}),true);
 assert.match(F.bannerText(fairView),/Посиделки: ярмарка на площади/);
 assert.match(F.bannerText({current:{name:'Новый год',phase:'decor'}}),/деревня наряжается/);
 assert.match(F.bannerText({current:null,upcoming:{name:'Посиделки',soon:true,starts_at:1795300000}}),/^Скоро: Посиделки, с /);
 assert.equal(F.bannerText({current:null,upcoming:{name:'Х',soon:false,starts_at:1}}),'');
});

test('pure rules: hand-in needs enough goods, buy block reasons, seller groups',async()=>{
 const F=await load(),stock=id=>({yarn:5,wool:2}[id]||0),t=fairView.fair.tasks[0];
 assert.equal(F.canHandIn(t,0,stock),true);assert.equal(F.canHandIn(t,1,stock),false);assert.equal(F.canHandIn(t,7,stock),false);
 assert.equal(F.canHandIn({...t,done:true},0,stock),false);assert.equal(F.canHandIn({...t,locked:true},0,stock),false);
 assert.equal(F.goodBlock({status:'owned'},9),'Уже у тебя');
 assert.equal(F.goodBlock({status:'locked',level:20},9),'С 20 уровня');
 assert.equal(F.goodBlock({status:'ok',away:true,price:1},9),'Сорока уехала');
 assert.equal(F.goodBlock({status:'ok',price:100},9),'Не хватает монет');
 assert.equal(F.goodBlock({status:'ok',price:9},9),'');
 assert.deepEqual(F.groupBySeller(fairView.fair.goods).map(([s,g])=>[s,g.length]),[['agata',2],['magpie',1]]);
});

test('the panel sends only intent: festival id, task, option / item, never a price or reward',async()=>{
 const F=await load(),h=helpers(),p=new Node('div');
 F.renderFestival(p,fairView,h);
 const buttons=walk(p).filter(n=>n.tag==='button');
 const label=text=>buttons.filter(b=>b.text.startsWith(text));
 const handIns=label('Сдать');
 assert.equal(handIns.length,2,'the finished task shows no buttons; the open one has two options');
 assert.equal(handIns[0].disabled,false);assert.equal(handIns[1].disabled,true,'wool is missing');
 handIns[0].onclick();assert.deepEqual(h.calls[0],['festival_task',{festival:'posidelki',task:'yarn',option:0}]);
 const buys=label('Купить');
 assert.deepEqual(buys.map(b=>b.disabled),[false,true,true]);
 buys[0].onclick();assert.deepEqual(h.calls[1],['festival_buy',{festival:'posidelki',item:'fest_posid_wreath'}]);
 const texts=walk(p).map(n=>n.text).join('|');
 assert.match(texts,/Шатёр Агаты/);assert.match(texts,/Тележка Сороки/);assert.match(texts,/Сорока уехала/);assert.match(texts,/С 20 уровня/);
 assert.match(texts,/Все задания — и «Носки года» твои/);
 assert.ok(!walk(p).some(n=>n.tag==='details'),'no past shop before any festival has finished');
});

test('past-festivals shop shows the x1.5 prices and buys through the same command',async()=>{
 const F=await load(),h=helpers(),p=new Node('div');
 const view={...fairView,current:null,fair:null,collection:{fest_posid_socks:{name:'Носки года',kind:'keepsake',place:'fence',wired:false,count:1,years:[2026]}},
  past:[{id:'posidelki',name:'Посиделки',key:'posidelki-2026',year:2026,live:false,goods:[{id:'fest_posid_wreath',name:'Венок',kind:'wall',seller:'agata',level:5,price:1500,status:'ok',away:false}]}]};
 F.renderFestival(p,view,h);
 const nodes=walk(p);
 assert.ok(nodes.some(n=>n.tag==='details'));assert.match(nodes.map(n=>n.text).join('|'),/на 50% дороже/);
 const buy=nodes.find(n=>n.tag==='button'&&n.text.startsWith('Купить · 1500'));buy.onclick();
 assert.deepEqual(h.calls[0],['festival_buy',{festival:'posidelki',item:'fest_posid_wreath'}]);
 assert.match(nodes.map(n=>n.text).join('|'),/Носки года/);
});

test('settings card toggles the hooks; the scares switch exists only on the Pumpkin Night',async()=>{
 const F=await load(),h=helpers();
 const c=F.settingsCard(fairView,h);assert.equal(walk(c).filter(n=>n.tag==='input').length,1);
 const pc=F.settingsCard({current:{id:'pumpkin_night',phase:'fair'}},h);assert.equal(walk(pc).filter(n=>n.tag==='input').length,2);
 const items=F.menuItems(()=>({current:{id:'posidelki'}}),()=>{});
 assert.deepEqual(items.map(i=>i.id),['farm-festival-decor','farm-festival-scares']);
 assert.equal(items[0].hidden(),false);assert.equal(items[1].hidden(),true);
 assert.equal(F.menuItems(()=>null,()=>{})[0].hidden(),true);
});

test('app wiring: module is served, imported, linked, in the rail, the menu and the orders banner',()=>{
 const app=fs.readFileSync(path.join(STATIC,'app.js'),'utf8'),api=fs.readFileSync(path.join(STATIC,'../api.py'),'utf8'),html=fs.readFileSync(path.join(STATIC,'index.html'),'utf8');
 assert.match(app,/import \* as FEST from '\.\/festivals\.js'/);
 assert.match(api,/'festivals\.js'/);assert.match(api,/'festivals\.css'/);
 assert.match(html,/assets\/festivals\.css/);
 assert.match(app,/\['festival','coin','Праздник'\]/);assert.match(app,/renderFestivalTab/);
 assert.match(app,/FEST\.menuItems\(/);assert.match(app,/festivalBanner\(p\)/);
 assert.ok(fs.existsSync(path.join(STATIC,'festivals.js'))&&fs.existsSync(path.join(STATIC,'festivals.css')));
 assert.match(app,/function festivalHelpers\(\)\{\s*return \{[^}]*\bicon,/);
});

test('Посиделки items all resolve to an icons.svg symbol, and every festival row draws its icon',async()=>{
 const svg=fs.readFileSync(path.join(STATIC,'icons.svg'),'utf8');
 const py=fs.readFileSync(path.join(STATIC,'../festivals.py'),'utf8');
 const ids=[...new Set([...py.matchAll(/'(fest_posid_[a-z_]+)'/g)].map(m=>m[1]))].sort();
 assert.equal(ids.length,14,'festivals.py names 14 Посиделки items');
 for(const id of ids)assert.match(svg,new RegExp(`<symbol id="${id}"`),`icons.svg has no symbol for ${id}`);
 const F=await load(),h=helpers(),drawn=new Set();
 const collect=p=>walk(p).filter(n=>n.tag==='svg').forEach(n=>drawn.add(n.text));
 const fair=new Node('div');F.renderFestival(fair,fairView,h);collect(fair);
 const past=new Node('div');F.renderFestival(past,{...fairView,current:null,fair:null,
  collection:{fest_posid_rowan:{name:'Рябинка',kind:'tree_decor',count:1,years:[2026],wired:true}},
  past:[{id:'posidelki',name:'Посиделки',year:2026,past_markup_pct:150,goods:[{id:'fest_posid_lights',name:'Огоньки',kind:'path',seller:'agata',level:8,price:90,status:'ok',away:false}]}]},h);
 collect(past);
 for(const id of ['fest_posid_wreath','fest_posid_quilt','fest_posid_lantern','fest_posid_basket','fest_posid_smoke','fest_posid_socks','fest_posid_lights','fest_posid_rowan'])
  assert.ok(drawn.has(id),`row does not draw ${id}`);
});

test('last years lots are hidden while the same festival fair is open',async()=>{
 const F=await load();
 const past=[{id:'posidelki',key:'posidelki-2026',year:2026,live:false,goods:[]},{id:'maslenitsa',key:'maslenitsa-2026',year:2026,live:false,goods:[]}];
 const view={current:{id:'posidelki',phase:'fair'},past};
 assert.deepEqual(F.pastShop(view).map(p=>p.id),['maslenitsa']);
 assert.deepEqual(F.pastShop({current:{id:'posidelki',phase:'decor'},past}).map(p=>p.id),['posidelki','maslenitsa']);
 assert.deepEqual(F.pastShop({past:[{id:'x',live:true}]}),[]);
 assert.deepEqual(F.pastShop(null),[]);
});
