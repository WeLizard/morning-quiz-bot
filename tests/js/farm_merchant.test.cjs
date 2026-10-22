const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');

const ROOT=path.join(__dirname,'../..');
const STATIC=path.join(ROOT,'qw_farm/static');
const read=f=>fs.readFileSync(path.join(ROOT,f),'utf8');
const load=()=>import(pathToFileURL(path.join(STATIC,'merchant.js')).href);

class Node{
 constructor(tag,text,cls){this.tag=tag;this.text=text??'';this.cls=cls||'';this.children=[];this.dataset={};this.attrs={};this.classList={add:c=>{this.cls+=' '+c;}};}
 append(...n){this.children.push(...n);}
 setAttribute(k,v){this.attrs[k]=v;}
}
function walk(n,out=[]){out.push(n);for(const c of n.children||[])walk(c,out);return out;}
function helpers(over={}){
 const calls=[];
 const el=(tag,text,cls)=>new Node(tag,text,cls);
 const button=(text,fn,cls,disabled)=>{const b=new Node('button',text,cls);b.onclick=fn;b.disabled=!!disabled;return b;};
 const card=(title,sub)=>{const c=new Node('section',title,'card');c.sub=sub;return c;};
 const icon=id=>new Node('svg',id,'icon');
 const note=(text,p)=>p.append(new Node('p',text,'note'));
 return {calls,el,button,card,icon,note,fmt:n=>String(n),itemName:id=>id,now:()=>1000,busy:()=>false,coins:()=>100000,rerender(){},
  command:(kind,data)=>{calls.push([kind,data]);return Promise.resolve(true);},catalog:{merchant:{curios:{curio_fair_1:{name:'Карусель-шкатулка'}}}},...over};
}
const slot=(over={})=>({slot:0,id:'seed_fire_pepper',kind:'exotic_seed',name:'Заморские семена: огненный перец',qty:3,price:280,limit:2,min_level:9,note:'Пакет на 3 посадки.',wired:true,series:null,left:2,status:'ok',...over});
const view=(over={})=>({active:true,visit_id:'v20000',kind:'regular',opens_at:900,closes_at:900+25920,next_at:900000,teaser:null,
 slots:[slot(),slot({slot:1,id:'dye_indigo',kind:'dye',name:'Индиго',qty:1,price:100,limit:10,left:10,min_level:17}),
        slot({slot:2,id:'scroll_pumpkin_latte',kind:'scroll',name:'Свиток: латте',price:3250,limit:1,left:1,min_level:14}),
        slot({slot:3,id:'curio_fair_1',kind:'curio',name:'Карусель-шкатулка',price:1950,limit:1,left:1,series:'Ярмарочная',min_level:12})],
 wants:{item:'honey',bonus_pct:30,unit:59,have:4,room:3},bought:{},sold_value:0,cap:260,curios:[],scrolls:[],fair:null,...over});
const buttons=n=>walk(n).filter(x=>x.tag==='button');

test('the visit flag follows the server view and is cleared when she leaves',async()=>{
 const M=await load(),root={dataset:{}};
 assert.equal(M.applyFlag(view(),root),true);assert.equal(root.dataset.merchant,'1');
 assert.equal(M.applyFlag(view({active:false}),root),false);assert.ok(!('merchant' in root.dataset));
 assert.equal(M.applyFlag(null,root),false);assert.doesNotThrow(()=>M.applyFlag(view(),null));
});

test('the status line says when she leaves and when she comes back',async()=>{
 const M=await load();
 assert.equal(M.duration(7*3600+12*60),'7 ч 12 мин');assert.equal(M.duration(2*86400+3*3600),'2 д 3 ч');assert.equal(M.duration(5),'меньше минуты');assert.equal(M.duration(600),'10 мин');
 assert.match(M.statusText(view({closes_at:1000+7*3600+12*60}),1000),/^Уезжает через 7 ч 12 мин$/);
 assert.match(M.statusText(view({active:false,next_at:1000+3*86400}),1000),/^Приедет через 3 д/);
 assert.match(M.statusText(view({active:false,next_at:null}),1000),/неизвестно/);
 assert.match(M.cartLabel(view({active:false,next_at:1000+86400}),1000),/Приедет через 1 д/);
});

test('slot reasons: level, owned, sold out, poor, away orchard',async()=>{
 const M=await load();
 assert.equal(M.slotBlock(slot(),1000),'');
 assert.equal(M.slotBlock(slot({status:'locked',min_level:12}),1000),'С 12 уровня');
 assert.equal(M.slotBlock(slot({status:'owned',kind:'curio'}),1000),'Уже в коллекции');
 assert.equal(M.slotBlock(slot({status:'owned',kind:'scroll'}),1000),'Рецепт уже известен');
 assert.equal(M.slotBlock(slot({status:'sold',left:0}),1000),'На этот визит всё');
 assert.equal(M.slotBlock(slot(),10),'Не хватает монет');
 assert.equal(M.slotBlock(slot({status:'soon'}),1000),'Ждёт сад');
});

test('the shelf shows six-slot cards and sends only visit id, slot number and quantity',async()=>{
 const M=await load(),h=helpers(),p=new Node('div');
 M.setTab('shelf');M.renderShop(p,view(),h);
 const buy=buttons(p).filter(b=>/^Купить/.test(b.text));
 assert.equal(buy.length,5,'one per slot plus «×5» for a dye');
 buy[0].onclick();buy[2].onclick();
 assert.deepEqual(h.calls,[['merchant_buy',{visit_id:'v20000',slot:0,qty:1}],['merchant_buy',{visit_id:'v20000',slot:1,qty:5}]]);
 assert.ok(h.calls.every(([kind,data])=>kind==='merchant_buy'&&Object.keys(data).sort().join()==='qty,slot,visit_id'),'no price, item or limit leaves the device');
 assert.ok(walk(p).some(n=>/привязано к ферме/.test(n.text)));
});

test('a disabled slot explains why and is never the primary action',async()=>{
 const M=await load(),h=helpers({coins:()=>10}),p=new Node('div');
 M.setTab('shelf');
 M.renderShop(p,view({slots:[slot({status:'locked',min_level:12}),slot({slot:1,status:'owned',kind:'curio'})]}),h);
 const buy=buttons(p).filter(b=>/^Купить/.test(b.text));
 assert.ok(buy.every(b=>b.disabled));
 const hints=walk(p).filter(n=>/qw-btn-hint/.test(n.cls)).map(n=>n.text);
 assert.deepEqual(hints,['С 12 уровня','Уже в коллекции']);
 assert.ok(!buttons(p).some(b=>/primary/.test(b.cls)&&/^Купить/.test(b.text)),'buying never uses the primary look');
});

test('the sell tab offers the wanted item, caps the quantity and sends only the item and amount',async()=>{
 const M=await load(),h=helpers(),p=new Node('div');
 M.setTab('sell');M.renderShop(p,view(),h);
 const sell=buttons(p).find(b=>/^Продать/.test(b.text));
 assert.equal(sell.text,'Продать 3 шт. · +177');assert.ok(!sell.disabled);
 sell.onclick();
 assert.deepEqual(h.calls[0],['merchant_sell',{visit_id:'v20000',item:'honey',qty:3}]);
 assert.equal(M.sellQty({have:2,room:9}),2);assert.equal(M.sellQty({have:2,room:0}),0);
 const none=new Node('div');M.renderShop(none,view({wants:{item:'honey',bonus_pct:30,unit:59,have:0,room:3}}),h);
 assert.ok(buttons(none).find(b=>/^Продать/.test(b.text)).disabled);
 assert.ok(walk(none).some(n=>n.text==='У тебя такого нет'));
 const full=new Node('div');M.renderShop(full,view({wants:{item:'honey',bonus_pct:30,unit:59,have:5,room:0}}),h);
 assert.ok(walk(full).some(n=>/достаточно/.test(n.text)));
 M.setTab('shelf');
});

test('the tabs are a segmented group with the chosen one pressed',async()=>{
 const M=await load(),h=helpers(),p=new Node('div');
 M.setTab('sell');M.renderShop(p,view(),h);
 const tabs=walk(p).filter(n=>n.dataset.merchantTab);
 assert.deepEqual(tabs.map(t=>[t.dataset.merchantTab,t.attrs['aria-pressed']]),[['shelf','false'],['sell','true']]);
 assert.ok(walk(p).some(n=>/qw-btn-group/.test(n.cls)));
 M.setTab('shelf');
});

test('away: «приедет через», the herald teaser and no buying buttons',async()=>{
 const M=await load(),h=helpers(),p=new Node('div');
 M.renderShop(p,view({active:false,next_at:1000+86400,teaser:'Карусель-шкатулка',slots:[]}),h);
 const texts=walk(p).map(n=>n.text);
 assert.ok(texts.some(t=>/Приедет через 1 д/.test(t)));
 assert.ok(texts.some(t=>/Завтра Сорока обещала привезти: Карусель-шкатулка/.test(t)));
 assert.equal(buttons(p).filter(b=>/^(Купить|Продать)/.test(b.text)).length,0);
 const none=new Node('div');M.renderShop(none,null,h);
 assert.ok(walk(none).some(n=>/недоступна/.test(n.text)));
});

test('the fair row reuses the festival engine command for her lots',async()=>{
 const M=await load(),h=helpers({festivalGoods:()=>[{id:'fest_posid_lantern',name:'Заморский фонарик-клубок',price:2000,status:'ok',level:10,note:''},{id:'fest_posid_wreath',name:'Венок',price:100,status:'ok',level:5}]}),p=new Node('div');
 M.setTab('shelf');
 M.renderShop(p,view({kind:'fair',fair:{id:'posidelki',name:'Посиделки',key:'posidelki-2026',goods:['fest_posid_lantern']}}),h);
 const fair=buttons(p).filter(b=>/Купить · 2000/.test(b.text));
 assert.equal(fair.length,1);fair[0].onclick();
 assert.deepEqual(h.calls[0],['festival_buy',{festival:'posidelki',item:'fest_posid_lantern'}]);
 assert.ok(!walk(p).some(n=>/Венок/.test(n.text)),'only her lots');
});

test('the collection lists curios and lets the player place an unplaced one',async()=>{
 const M=await load(),placed=[],h=helpers({placed:id=>id==='x',place:id=>placed.push(id)}),p=new Node('div');
 M.setTab('shelf');M.renderShop(p,view({curios:['curio_fair_1']}),h);
 assert.ok(walk(p).some(n=>n.text==='Карусель-шкатулка'));
 buttons(p).find(b=>b.text==='Поставить').onclick();assert.deepEqual(placed,['curio_fair_1']);
});

test('app.js wiring: cart tap target on the art box, flag sync, sheet, seed lists without foreign crops, scroll gate',()=>{
 const app=read('qw_farm/static/app.js');
 assert.match(app,/import \* as MERCH from '\.\/merchant\.js'/);
 assert.match(app,/function villageCartButton\(\)/);
 assert.match(app,/layer\.append\(villageCartButton\(\)\)/);
 assert.match(app,/VILLAGE_MERCHANT\.cart/);
 assert.match(app,/d\.villageMerchant\?'merchant'/,'the walk graph anchor VILLAGE_WALK.a.merchant is the approach point');
 assert.match(app,/syncVillageFest\(\);syncMerchantFlag\(\);syncVillageMerchant\(\)/,'the flag is set before the art layers are filled');
 assert.match(app,/villageSheet==='merchant'/);
 assert.match(app,/MERCH\.renderShop\(p,merchantView\(\),merchantHelpers\(\)\)/);
 assert.equal((app.match(/sortSeeds\(Object\.values\(S\.catalog\.crops\)\.filter\(c=>!c\.exotic\),/g)||[]).length,3,'all three seed lists skip foreign crops');
 assert.match(app,/r\.scroll&&!\(S\.me\?\.merchant\?\.scrolls\|\|\[\]\)\.includes\(r\.scroll\)\)return 1e6/);
 assert.match(app,/b\.curio&&!\(S\.me\.merchant\?\.curios\|\|\[\]\)\.includes\(b\.id\)\)continue/,'unowned curios are not in the build list');
 const walkAnchors=app.match(/a:\{[^}]*\}/)[0];
 assert.match(walkAnchors,/"merchant":\d+/);
});

test('assets are served and linked',()=>{
 const api=read('qw_farm/api.py'),html=read('qw_farm/static/index.html');
 for(const asset of ['merchant.js','merchant.css'])assert.ok(api.includes(`'${asset}'`),asset);
 assert.ok(html.includes('/app/farm/assets/merchant.css'));
 assert.ok(fs.existsSync(path.join(STATIC,'merchant.js'))&&fs.existsSync(path.join(STATIC,'merchant.css')));
 const css=read('qw_farm/static/merchant.css');
 assert.match(css,/\.village-cart/);assert.match(css,/min-height:44px/);
});

const catalog={crops:{wheat:{id:'wheat',name:'Пшеница',level:1},exo_fire_pepper:{id:'exo_fire_pepper',name:'Огненный перец',level:3,exotic:true,seed:'seed_fire_pepper'},
 exo_pearl_rice:{id:'exo_pearl_rice',name:'Жемчужный рис',level:26,exotic:true,seed:'seed_pearl_rice'}},
 items:{wheat:{},seed_fire_pepper:{bound:true},dye_indigo:{bound:true},honey:{}}};

test('a seed pack reaches the plant command: bar entry, choice, plot tap',async()=>{
 const M=await load(),inv={seed_fire_pepper:2,seed_pearl_rice:3},stock=id=>inv[id]||0;
 const packs=M.seedPacks(catalog,stock,5);
 assert.deepEqual(packs,[{id:'exo_fire_pepper',name:'Огненный перец',seed:'seed_fire_pepper',left:2,level:3}],'a pack above the player level is not offered');
 assert.deepEqual(M.seedPacks(catalog,id=>0,30),[]);
 const seed=packs[0].id;                                 // the seed bar button sets S.seed
 const plot={id:'plot_4',revision:7};
 assert.deepEqual(M.plantRequest(plot,seed,catalog,stock),{command:['plant',{object:'plot_4',crop:'exo_fire_pepper',revision:7}]});
 assert.deepEqual(M.plantRequest(plot,'wheat',catalog,stock),{command:['plant',{object:'plot_4',crop:'wheat',revision:7}]});
 assert.match(M.plantRequest(plot,seed,catalog,()=>0).error,/пакет закончился/);
});

test('app.js plants from packs: bar buttons, request through plantRequest, no card or bulk run for a pack',()=>{
 const app=read('qw_farm/static/app.js');
 assert.ok(app.includes('for(const k of MERCH.seedPacks(S.catalog,stock,S.me.level))'));
 assert.ok(app.includes('b.dataset.seedPack=k.id'));
 assert.ok(app.includes("const r=MERCH.plantRequest(o,S.seed,S.catalog,stock);if(r.error){toast(r.error,true);S.seed='wheat';renderSeeds();return;}command(...r.command)"));
 assert.ok(app.includes('!c||c.exotic||c.level>S.me.level){box.hidden=true'));
 assert.ok(app.includes('afford=crop&&!crop.exotic?'));
});

test('an unbought scroll recipe says what is needed instead of a million levels',async()=>{
 const M=await load();
 const r={id:'pumpkin_latte',scroll:'pumpkin_latte',level:14};
 const lock=M.scrollLock(r,{merchant:{scrolls:[]}});
 assert.equal(lock.label,'Нужен свиток Сороки');assert.match(lock.hint,/Сорока-коробейница/);
 assert.equal(M.scrollLock(r,{merchant:{scrolls:['pumpkin_latte']}}),null);
 assert.equal(M.scrollLock({id:'bread',level:2},{}),null);
 const app=read('qw_farm/static/app.js');
 assert.ok(app.includes('const lock=recipeLock(r);c.append(button(lock?lock.label:recipeLevel(r)>S.me.level')&&app.includes('MERCH.scrollLock(r,S.me)'));
 assert.ok(app.includes('if(lock)note(lock.hint,c)'));
});

test('bound goods get no sell, list, gift or fund controls and no «0 coins» line',async()=>{
 const M=await load();
 assert.equal(M.isBound(catalog,'dye_indigo'),true);assert.equal(M.isBound(catalog,'honey'),false);assert.equal(M.isBound(catalog,'nope'),false);
 assert.equal(M.BOUND_NOTE,'Вещь от Сороки — только для вашей фермы');
 const app=read('qw_farm/static/app.js');
 assert.ok(app.includes('MERCH.isBound(S.catalog,id)?MERCH.BOUND_NOTE:'));
 assert.ok(app.includes("if(!MERCH.isBound(S.catalog,id))actions.append(button('−1'"));
 assert.ok(app.includes('filter(([id,q])=>q>0&&!MERCH.isBound(S.catalog,id))'),'gift list');
 assert.ok(app.includes('S.catalog.items[k]&&!MERCH.isBound(S.catalog,k)'),'fund list');
});

test('the buy-back says when the wanted item is beyond the Magpie purse',async()=>{
 const M=await load();
 assert.equal(M.sellBlock({item:'honey',pricey:true,have:5,room:0}),'Пока не по карману Сороке');
 assert.equal(M.sellBlock({item:'honey',pricey:false,have:5,room:0}),'На сегодня Сорока набрала достаточно');
 assert.equal(M.sellBlock({item:'honey',pricey:false,have:0,room:3}),'У тебя такого нет');
});

test('festivals.js and app.js keep LF line endings',()=>{
 assert.ok(!fs.readFileSync(path.join(STATIC,'festivals.js'),'utf8').includes('\r'));
 assert.ok(!fs.readFileSync(path.join(STATIC,'app.js'),'utf8').includes('\r'));
});
