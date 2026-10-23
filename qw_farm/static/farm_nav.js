/* Farm navigation (docs/tasks/FARM_FEEDBACK_2026-10-21.md E1, E8; docs/design/UI_RULES.md §6.1).
   One menu with five sections is the only way to a place ("куда пойти"); the seed bar with its «Всё» catalogue is the only
   way to put something on the map ("что поставить"); ⚙ is "как играть". This module holds the pure model: what each
   section lists, the catalogue entries with their locks, the catalogue search and the «Недавнее» list. app.js draws it. */
import {categoryOf} from './scene_map.js';

// Menu: sections in a fixed order. `art` items are picture cards (За околицей); `when` hides an item that is not live.
export const MENU=[
 {id:'farm',title:'Хозяйство',items:[['orders','orders','Заказы'],['inventory','shop','Склад'],['team','tractor','Команда'],['land','home','Участок']]},
 {id:'production',title:'Производство',items:[['production','workshop','Мастерские'],['orchard','orchard','Сад']]},
 {id:'outside',title:'За околицей',art:true,items:[['forest','forest','Лес'],['lake','lake','Озеро'],['fields','tractor','Поля']]},
 {id:'village',title:'Деревня и соседи',items:[['village','coin','Деревня'],['neighbors','friends','Соседи'],['festival','coin','Праздник','festival']]},
 {id:'info',title:'Сведения',items:[['secrets','discovery','Находки'],['journal','journal','Журнал']]}
];
// Every tab a menu item can open. Settings live in ⚙, the object list behind 🔍, the arbor and objects on the map.
export const MENU_TABS=MENU.flatMap(s=>s.items.map(i=>i[0]));

export function plural(n,one,few,many){const a=Math.abs(n)%100,b=a%10;return a>10&&a<20?many:b===1?one:b>1&&b<5?few:many;}

/** Sections with live status lines and counters. `f` is a set of facts the client already knows (see navFacts in app.js). */
export function menuSections(f={}){
 const status={
  orders:f.ordersReady?`${f.ordersReady} можно сдать`:f.orders?`${f.orders} ${plural(f.orders,'заказ','заказа','заказов')} на доске`:'',
  inventory:f.goods?`${f.goods} шт. · лавка`:'и лавка',
  team:'техника и помощники',
  land:f.size?`${f.size} × ${f.size}${f.canExpand?' · можно расширить':''}`:'',
  production:f.readyWorkshop?(f.workshopsReady>1?`готово: ${f.workshopsReady}`:`${f.readyWorkshop} · готово`):f.workshopsBusy?`в работе: ${f.workshopsBusy}`:'',
  orchard:f.saplings?(f.saplings===1?'саженец ждёт посадки':`ждут посадки: ${f.saplings}`):f.trees?`${f.trees} ${plural(f.trees,'дерево','дерева','деревьев')}`:'',
  forest:f.forestReady?'готово':f.forestBusy?'в пути':'',
  lake:f.lakeReady?'улов':f.lakeBusy?'клюёт':'',
  fields:f.fieldsLocked?`С ${f.fieldsLocked} ур.`:'',
  village:'',
  neighbors:f.requests?`ждут ответа: ${f.requests}`:'',
  festival:f.festival||'',
  secrets:f.secretsTotal?`${f.secretsFound||0} из ${f.secretsTotal}`:'',
  journal:'что было на ферме'
 };
 const badge={orders:f.ordersReady||0,production:f.workshopsReady||0,orchard:f.saplings||0,neighbors:f.requests||0};
 return MENU.map(s=>({...s,items:s.items.filter(([, , ,when])=>!when||f[when]).map(([id,icon,label])=>({id,icon,label,status:status[id]||'',badge:badge[id]||0,locked:id==='fields'&&!!f.fieldsLocked}))}));
}
/** The number on the phone «Меню» button: things that wait for the player. */
export const menuTotal=f=>(f.ordersReady||0)+(f.workshopsReady||0)+(f.saplings||0)+(f.requests||0);

// Catalogue sections (E1 variant B). Crops are picked here as in the seed bar; everything else goes to placement.
export const CATALOG_SECTIONS=[['plots','Грядки'],['trees','Деревья'],['workshops','Мастерские'],['animals','Животные'],['decor','Декор'],['roads','Дорожки']];

/** Where a building lives in the catalogue. */
export function sectionOf(id,catalog){
 if(id==='road')return 'roads';
 if(id==='plot')return 'plots';
 const c=categoryOf({type:id},catalog);
 return c==='decor'?'decor':c==='animals'?'animals':c==='workshops'?'workshops':null;
}

/** All catalogue entries for this farm. Gating is the one of the former «Строить» tab:
    a curio shows only once owned, a secret decor needs its find, a fund reward needs the fund, then level and coins. */
export function catalogEntries(catalog,me,objects=[],orchardRows=[]){
 if(!catalog||!me)return [];
 const out=[],placed={};for(const o of objects)placed[o.type]=(placed[o.type]||0)+1;
 const trees={};for(const o of objects)if(o.type==='tree')trees[o.species]=(trees[o.species]||0)+1;
 for(const c of Object.values(catalog.crops||{})){
  if(c.exotic||c.orchard)continue;
  out.push({key:'crop:'+c.id,kind:'crop',section:'plots',id:c.id,name:c.name,cost:c.cost,level:c.level||1,locked:(c.level||1)>me.level,lock:(c.level||1)>me.level?`С ${c.level} ур.`:''});
 }
 const plot={id:'plot',name:'Новая грядка',cost:35,level:1,w:1,h:1};
 const specs=[plot,...Object.values(catalog.buildings||{})];
 for(const b of specs){
  if(b.curio&&!(me.merchant?.curios||[]).includes(b.id))continue;
  const section=sectionOf(b.id,catalog);if(!section)continue;
  const secret=!!b.secret&&!(me.secrets||[]).includes(b.secret),reward=!!b.reward&&!(me.economy?.unlocked||[]).includes(b.id),low=(b.level||1)>me.level;
  const lock=low?`С ${b.level} ур.`:secret?'Найди в «Находках»':reward?`Награда фонда деревни${b.source?`: ${b.source}`:''}`:'';
  out.push({key:'b:'+b.id,kind:b.id==='plot'?'plot':'building',section,id:b.id,name:b.name,cost:b.cost,level:b.level||1,w:b.w||1,h:b.h||1,
   have:placed[b.id]||0,locked:low||secret||reward,lock,poor:!low&&!secret&&!reward&&b.cost>me.coins,spec:b});
 }
 for(const r of orchardRows){
  const waiting=r.options.filter(o=>o.voucher&&o.qty).reduce((n,o)=>n+(o.voucher==='free'?o.qty:0),0);
  out.push({key:'t:'+r.id,kind:'tree',section:'trees',id:r.id,name:r.name,sapling:r.sapling,cost:r.cost,level:r.level||1,w:1,h:1,have:trees[r.id]||0,
   saplings:waiting,locked:!!r.locked,lock:r.locked?`С ${r.level} ур.`:r.blocked||'',row:r,fruit:r.fruit});
 }
 // Open first, by level; locked ones after them, nearest first.
 return out.sort((a,b)=>(a.locked-b.locked)||(a.level-b.level)||((a.cost||0)-(b.cost||0)));
}

export function sectionCounts(entries){const n={};for(const [id] of CATALOG_SECTIONS)n[id]=0;for(const e of entries)n[e.section]++;return n;}

const norm=s=>String(s||'').toLowerCase().replace(/ё/g,'е').trim();

/** Search by name and by product: «ябл» → apple trees, buildings that process apples, orders that need them.
    Returns [{id,title,entries}] for the catalogue groups and `orders` for the board. */
export function searchCatalog(entries,query,catalog,orders=[]){
 const q=norm(query);if(q.length<2)return {groups:[],orders:[]};
 const groups=[];
 for(const [id,title] of CATALOG_SECTIONS){
  const hit=entries.filter(e=>e.section===id&&(norm(e.name).includes(q)||norm(e.sapling).includes(q)));
  if(hit.length)groups.push({id,title,entries:hit});
 }
 const items=Object.entries(catalog?.items||{}).filter(([,it])=>norm(it.name).includes(q)).map(([id])=>id);
 if(items.length){
  const shown=new Set(groups.flatMap(g=>g.entries.map(e=>e.key)));
  const makers=new Set(),used=new Set();
  for(const r of [...Object.values(catalog.recipes||{}),...Object.values(catalog.animals||{})])for(const id of items)if(r.inputs&&id in r.inputs){makers.add(r.building);used.add(id);}
  const uses=entries.filter(e=>e.kind==='building'&&makers.has(e.id)&&!shown.has(e.key)),names=[...used].map(id=>norm(catalog.items[id].name));
  if(uses.length)groups.push({id:'uses',title:`Перерабатывают: ${names.slice(0,2).join(', ')}${names.length>2?' и др.':''}`,entries:uses});
 }
 const want=(orders||[]).filter(o=>Object.keys(o.needs||{}).some(id=>items.includes(id)));
 return {groups,orders:want};
}

// «Недавнее»: the last things placed from the catalogue, newest first, kept per farm in this browser only.
export const RECENT_MAX=4;
export function pushRecent(list,key){return [key,...(list||[]).filter(k=>k!==key)].slice(0,RECENT_MAX);}
export function loadRecent(store,farmId){try{const v=JSON.parse(store?.getItem('qw-farm.recent.'+farmId)||'[]');return Array.isArray(v)?v.filter(k=>typeof k==='string').slice(0,RECENT_MAX):[];}catch{return [];}}
export function saveRecent(store,farmId,list){try{store?.setItem('qw-farm.recent.'+farmId,JSON.stringify(list));}catch{}}
/** The best way to plant a tree right now: a free sapling, then a talon, then coins. */
export const bestOption=row=>row?.options?.find(o=>o.voucher==='free'&&o.qty)||row?.options?.find(o=>o.voucher&&o.qty)||row?.options?.[row.options.length-1]||null;
