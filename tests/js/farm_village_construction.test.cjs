const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const stat=path.join(__dirname,'../../qw_farm/static');
const load=()=>import(pathToFileURL(path.join(stat,'construction.js')).href);

class Node{
 constructor(tag,text,cls){this.tag=tag;this.textContent=text||'';this.className=cls||'';this.children=[];this.dataset={};this.attrs={};this.value='';this.classList={add:c=>this.className+=' '+c};}
 append(...nodes){this.children.push(...nodes);if(this.tag==='select'&&!this.value)this.value=nodes[0]?.value||'';}
 setAttribute(k,v){this.attrs[k]=v;}
}
const walk=n=>[n,...n.children.flatMap(walk)];
const buttons=n=>walk(n).filter(n=>n.tag==='button');
const texts=n=>walk(n).map(x=>x.textContent).join('|');

const project=(over={})=>({id:'stalls',name:'Торговые ряды',status:'collecting',stage:0,stage_name:'Котлован',need:{wood:240,coins:1600},got:{wood:60},
 work_until:null,speedup:0,speedup_room:86400,mine:{value:0,share_bp:0,tier:0},bonus:['а','б','в'],...over});
const build=(over={})=>({level_ok:true,level:8,active:'stalls',energy:['berry_charge','honey_charge','forest_charge'],tier_bp:[1000,4000,10000],
 tier_names:['','Помощник','Мастер','Почётный строитель'],honor:{},rows:{open:false},
 projects:[project(),project({id:'tavern',name:'Трактир',status:'soon'})],...over});

function harness(v,meOver={}){
 const calls=[],dialogs=[],toasts=[],log=[];
 const me={id:'farm-a',level:12,coins:5000,starter_credit:0,inventory:{wood:100,berry_charge:5,bread:4,bound_seed:1},village_build:v,merchant_view:{active:false},...meOver};
 const el=(...a)=>new Node(...a);
 const h={me:()=>me,catalog:()=>({items:{wood:{price:8},bread:{price:29},bound_seed:{price:5}},economy:{income_ref:[[1,4,1100],[5,9,7000],[10,14,13000]]}}),el,
  button:(text,fn,cls,disabled)=>{const b=el('button',text,cls);b.onclick=fn;b.disabled=!!disabled;return b;},
  card:(title,subtitle)=>{const c=el('section',title,'card');if(subtitle)c.append(el('small',subtitle));return c;},
  note:(text,p)=>{(p||h.panel).append(el('p',text,'note'));},heading:(t)=>log.push(['heading',t]),meter:(a,b)=>el('div',`${a}/${b}`,'meter'),
  itemName:id=>({wood:'Древесина',bread:'Хлеб'}[id]||id),fmt:n=>String(n),now:()=>1000,timer:t=>{const s=el('span',String(t));return s;},
  command:async(kind,data,target)=>{calls.push([kind,data,target]);return true;},modal:(...a)=>dialogs.push(a),close(){h.closed=true;},toast:t=>toasts.push(t),
  isBound:id=>id==='bound_seed',open:s=>log.push(['open',s]),resident:n=>log.push(['resident',n]),merchant:()=>log.push(['merchant']),
  festival:()=>log.push(['festival']),post:()=>log.push(['post']),warehouse:()=>log.push(['warehouse'])};
 h.panel=el('div');
 return {h,me,calls,dialogs,toasts,log};
}

test('pure helpers: need rows, percent, time, site captions and the tier gap',async()=>{
 const C=await load(),p=project();
 assert.deepEqual(C.needRows(p).map(r=>[r.key,r.left]),[['wood',180],['coins',1600]]);
 assert.equal(C.stagePct(p),Math.floor(100*60/1840));
 assert.equal(C.timeLeft(86400+3600*6),'1 д 6 ч');assert.equal(C.timeLeft(30),'1 мин');
 assert.equal(C.siteLabel(null,'Трактир',0),'Скоро · Трактир');
 assert.equal(C.siteLabel(p,'x',0),'Торговые ряды · котлован · 3%');
 assert.match(C.siteLabel(project({status:'working',work_until:1000+86400+6*3600,stage:1}),'x',1000),/каркас · готово через 1 д 6 ч/);
 assert.equal(C.siteLabel(project({status:'done'}),'x',0),'Торговые ряды · готово');
 const v=build();
 const t=C.tierInfo(project({mine:{tier:1,share_bp:1500,value:1}}),v,12,[[10,14,13000]]);
 assert.equal(t.name,'Помощник');assert.equal(t.nextName,'Мастер');assert.equal(t.missing,Math.ceil((4000-1500)*13000/10000));
 assert.equal(C.tierInfo(project({mine:{tier:3,share_bp:10000,value:1}}),v,12,[]).missing,0);
 assert.equal(C.offerLimit({key:'wood',left:180},{wood:100},0),100);assert.equal(C.offerLimit({key:'coins',left:1600},{},900),900);
 assert.deepEqual(C.lotPriceRange(29),[29,43]);
 assert.deepEqual(C.energyChoice({berry_charge:20},['berry_charge'],86400),{item:'berry_charge',qty:12});
 assert.equal(C.energyChoice({},['berry_charge'],86400),null);assert.equal(C.energyChoice({berry_charge:2},['berry_charge'],3600),null);
});

test('site sheet in the collecting stage: needs, one primary button, contribute sends exactly the inputs',async()=>{
 const {createConstruction}=await load(),v=build(),{h,calls,dialogs}=harness(v);
 const ui=createConstruction(h);ui.render(h.panel,'site:stalls');
 const text=texts(h.panel);
 assert.match(text,/Древесина 60 \/ 240/);assert.match(text,/монеты 0 \/ 1600/);assert.match(text,/по цене ×1,25/);
 assert.equal(buttons(h.panel).filter(b=>/primary/.test(b.className)).length,1);
 buttons(h.panel).find(b=>b.textContent==='Внести').onclick();
 assert.equal(dialogs.length,1);
 const form=dialogs[0][1],inputs=walk(form).filter(n=>n.tag==='input');
 assert.deepEqual(inputs.map(i=>[i.dataset.key,i.value]),[['wood','100'],['coins','1600']]);   // up to what the player has, clipped by the need
 inputs[0].value='7';inputs[1].value='0';
 await dialogs[0][2][0].onclick();
 assert.deepEqual(calls,[['build_contribute',{project:'stalls',items:{wood:7},coins:0},undefined]]);
 assert.equal(h.closed,true);
});

test('contribution is blocked below the fund level and when the stage is already full',async()=>{
 const {createConstruction}=await load();
 let {h}=harness(build({level_ok:false}));createConstruction(h).render(h.panel,'site:stalls');
 assert.equal(buttons(h.panel).find(b=>b.textContent==='Внести').disabled,true);assert.match(texts(h.panel),/с 8 уровня/);
 ({h}=harness(build({projects:[project({got:{wood:240,coins:1600}})]})));createConstruction(h).render(h.panel,'site:stalls');
 assert.equal(buttons(h.panel).find(b=>b.textContent==='Внести').disabled,true);
});

test('working stage: timeline, Pukh button with the cap, disabled with a reason',async()=>{
 const {createConstruction}=await load();
 let {h,calls}=harness(build({projects:[project({status:'working',stage:1,work_until:5000,speedup_room:86400})]}));
 createConstruction(h).render(h.panel,'site:stalls');
 const pukh=buttons(h.panel).find(b=>/Взбодрить Пуха/.test(b.textContent));
 assert.match(pukh.textContent,/−10 ч/);                                                         // 5 drinks x 2 h
 await pukh.onclick();assert.deepEqual(calls[0],['build_speedup',{project:'stalls',item:'berry_charge',qty:5},undefined]);
 assert.match(texts(h.panel),/Жители работают/);assert.match(texts(h.panel),/✓ Котлован/);assert.match(texts(h.panel),/▶ Каркас/);
 ({h}=harness(build({projects:[project({status:'working',stage:1,work_until:5000,speedup_room:0})]})));createConstruction(h).render(h.panel,'site:stalls');
 assert.equal(buttons(h.panel).find(b=>/Взбодрить/.test(b.textContent)).disabled,true);assert.match(texts(h.panel),/Пух уже выложился/);
});

test('a soon project shows which one is being built; bonus table marks the reached tier',async()=>{
 const {createConstruction}=await load(),{h}=harness(build());
 createConstruction(h).render(h.panel,'site:tavern');
 assert.match(texts(h.panel),/Сначала достроим «Торговые ряды»/);
 const g=harness(build({projects:[project({mine:{tier:2,share_bp:4200,value:9},bonus:['скидка','лимит','табличка']})]}));
 createConstruction(g.h).render(g.h.panel,'site:stalls');
 assert.match(texts(g.h.panel),/Ты: ② Мастер/);assert.match(texts(g.h.panel),/до «Почётный строитель» ещё около/);
 assert.equal(walk(g.h.panel).filter(n=>/build-perk got/.test(n.className)).length,2);
});

test('rows: closed before the building is done; open shows stalls, lots and own stall rules',async()=>{
 const {createConstruction}=await load();
 let {h,log}=harness(build({rows:{open:false}}));createConstruction(h).render(h.panel,'rows');
 assert.match(texts(h.panel),/ещё строятся/);buttons(h.panel).find(b=>b.textContent==='Открыть склад').onclick();assert.deepEqual(log.at(-1),['warehouse']);
 const rows={open:true,access:true,rent:130,max_lots:3,buys_per_day:3,commission_pct:5,price_min_pct:100,price_max_pct:150,level:10,paid_until:2000000000,
  lots:[{id:'l1',item:'bread',qty:2,unit_price:40,seller:'Ферма Б',seller_farm:'farm-b',honor:true,buys_today:0},{id:'l2',item:'bread',qty:1,unit_price:40,seller:'Ферма В',seller_farm:'farm-c',buys_today:3}],
  own:[{id:'o1',item:'bread',qty:1,unit_price:35}]};
 let r=harness(build({rows}));createConstruction(r.h).render(r.h.panel,'rows');
 const t=texts(r.h.panel);
 for(const s of ['Заезжие товары','Семенной ларёк','Ткацкая лавка','Лавка прошлых праздников','Почтовое окно','★ Ферма Б','Твоя лавка','1 из 3'])assert.ok(t.includes(s),s);
 const buy=buttons(r.h.panel).filter(b=>/^Купить/.test(b.textContent));
 assert.equal(buy[0].disabled,false);assert.equal(buy[1].disabled,true);assert.match(t,/три покупки/);
 await buy[0].onclick();assert.deepEqual(r.calls[0],['stall_buy',{lot:'l1'},'farm-b']);
 await buttons(r.h.panel).find(b=>b.textContent==='Снять').onclick();assert.deepEqual(r.calls[1],['stall_cancel',{lot:'o1'},undefined]);
 for(const [label,expect] of [['К лавке Сороки',['merchant']],['К лавке Сони',['resident','Кошка Соня']],['К лавке Агаты',['festival']],['Записка для Ежа',['post']]]){
  await buttons(r.h.panel).find(b=>b.textContent===label).onclick();assert.deepEqual(r.log.at(-1),expect);
 }
 // listing: bound items never offered, price limits come from the catalog, the server gets exactly the form
 buttons(r.h.panel).find(b=>b.textContent==='Выставить товар').onclick();
 const form=r.dialogs.at(-1)[1],select=walk(form).find(n=>n.tag==='select');
 assert.deepEqual(select.children.map(o=>o.value),['wood','bread']);
 select.value='bread';select.onchange();
 const [qty,price]=walk(form).filter(n=>n.tag==='input');
 assert.equal(price.min,'29');assert.equal(price.max,'43');
 qty.value='3';price.value='40';await r.dialogs.at(-1)[2][0].onclick();
 assert.deepEqual(r.calls.at(-1),['stall_list',{item:'bread',qty:3,unit_price:40},undefined]);
 // no access: a reason instead of the form
 r=harness(build({rows:{...rows,access:false,own:[]}}));createConstruction(r.h).render(r.h.panel,'rows');
 assert.match(texts(r.h.panel),/Своя лавка: со ступени «Мастер»/);
 assert.equal(buttons(r.h.panel).some(b=>b.textContent==='Выставить товар'),false);
});

test('wiring: assets, stylesheet, map sites are buttons, the market sign leads to the rows once built',()=>{
 const app=fs.readFileSync(path.join(stat,'app.js'),'utf8'),api=fs.readFileSync(path.join(stat,'../api.py'),'utf8'),index=fs.readFileSync(path.join(stat,'index.html'),'utf8');
 assert.match(api,/'construction\.js'/);assert.match(api,/'construction\.css'/);assert.match(index,/assets\/construction\.css/);
 assert.match(app,/from '\.\/construction\.js'/);
 assert.match(app,/const VILLAGE_SITES=\[\['stalls','Торговые ряды'/);
 assert.match(app,/'village-site village-site-btn'/);
 assert.match(app,/id==='market'&&typeof CONSTR!=='undefined'&&CONSTR\.rowsOpen\(\)\?villageGo\(\[x,y\+2\.4\],\(\)=>openVillageConstruction\('rows'\),e\)/);
 assert.match(app,/syncMerchantFlag\(\);syncVillageMerchant\(\);syncVillageSites\(\)/);
 assert.match(app,/villageSheet==='rows'\|\|String\(villageSheet\)\.startsWith\('site:'\)/);
 const css=fs.readFileSync(path.join(stat,'construction.css'),'utf8');
 assert.match(css,/\.village-site-btn\{pointer-events:auto;min-height:44px/);
});
