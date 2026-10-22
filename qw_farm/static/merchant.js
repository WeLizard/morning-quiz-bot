// Сорока-коробейница (FARM_VILLAGE_MINIGAMES.md section 2). The server owns the schedule, the stock, prices and limits
// (qw_farm/merchant.py, S.me.merchant_view); this module only shows them and sends merchant_buy / merchant_sell
// (and festival_buy for the fair row, which the festival engine already prices). The cart art is the village layer driven by html[data-merchant].
const KIND_LABEL={exotic_seed:'Заморские семена',dye:'Краситель',scroll:'Свиток рецепта',curio:'Диковинка',graft:'Прививка',voucher:'Талон сада'};
const WEEKDAY=new Intl.DateTimeFormat('ru-RU',{weekday:'long',timeZone:'Europe/Moscow'});
let shopTab='shelf';
export const setTab=tab=>{shopTab=tab==='sell'?'sell':'shelf';};
export const currentTab=()=>shopTab;

export function view(me){return me?.merchant_view||null;}
export function present(v){return !!v&&v.active===true;}
// html[data-merchant] is what the village layers (cart, her figure) listen to; it is set only while she is in the village.
export function applyFlag(v,root=globalThis.document?.documentElement){
 if(!root)return false;
 if(present(v))root.dataset.merchant='1';else delete root.dataset.merchant;
 return present(v);
}
export function duration(seconds){
 const s=Math.max(0,Math.ceil(seconds));
 if(s<60)return 'меньше минуты';
 const m=Math.ceil(s/60);
 if(m<60)return `${m} мин`;
 const h=Math.floor(m/60);
 if(h<24)return m%60?`${h} ч ${m%60} мин`:`${h} ч`;
 const d=Math.floor(h/24);
 return h%24?`${d} д ${h%24} ч`:`${d} д`;
}
export function statusText(v,now){
 if(!v)return 'Данные Сороки пока недоступны.';
 if(present(v))return `Уезжает через ${duration(v.closes_at-now)}`;
 if(v.next_at)return `Приедет через ${duration(v.next_at-now)} · ${WEEKDAY.format(new Date(v.next_at*1000+43200e3))}`;
 return 'Сорока уехала далеко: когда вернётся, пока неизвестно.';
}
export function cartLabel(v,now){return present(v)?`Тележка Сороки-коробейницы. ${statusText(v,now)}`:`Здесь стоит тележка Сороки, когда она в деревне. ${statusText(v,now)}`;}
export function slotBlock(s,coins){
 if(s.status==='soon')return 'Ждёт сад';
 if(s.status==='owned')return s.kind==='scroll'?'Рецепт уже известен':'Уже в коллекции';
 if(s.status==='locked')return `С ${s.min_level} уровня`;
 if(s.status==='sold'||s.left<=0)return 'На этот визит всё';
 if(coins<s.price)return 'Не хватает монет';
 return '';
}
export function sellBlock(w,sold){
 if(!w)return 'Сорока сегодня ничего не покупает';
 if(w.pricey)return 'Пока не по карману Сороке';
 if(w.have<=0)return 'У тебя такого нет';
 if(w.room<=0)return 'На сегодня Сорока набрала достаточно';
 return sold?'':'';
}
// Planting from a pack (the seed bar and the plot tap): foreign crops are planted with `plant {crop:'exo_<id>'}`, one unit of the pack per bed.
export function seedPacks(catalog,stock,level){
 return Object.values(catalog?.crops||{}).filter(c=>c.exotic&&c.seed&&c.level<=level&&stock(c.seed)>0).map(c=>({id:c.id,name:c.name,seed:c.seed,left:stock(c.seed),level:c.level}));
}
export function plantRequest(obj,cropId,catalog,stock){
 const crop=catalog?.crops?.[cropId];
 if(crop?.exotic&&stock(crop.seed)<1)return {error:`${crop.name}: пакет закончился. Новые семена продаёт Сорока.`};
 return {command:['plant',{object:obj.id,crop:cropId,revision:obj.revision}]};
}
// A scroll recipe that was not bought is not «a level»: the card says where to get the scroll.
export function scrollLock(recipe,me){
 if(!recipe?.scroll||(me?.merchant?.scrolls||[]).includes(recipe.scroll))return null;
 return {label:'Нужен свиток Сороки',hint:'Свиток этого рецепта продаёт Сорока-коробейница, когда приезжает на рынок.'};
}
export const BOUND_NOTE='Вещь от Сороки — только для вашей фермы';
export const isBound=(catalog,id)=>!!catalog?.items?.[id]?.bound;
export function sellQty(w){return w?Math.max(0,Math.min(w.have,w.room)):0;}

function itemMark(h,id){const mark=h.el('span',null,'good');mark.append(h.icon(id));return mark;}
function slotIcon(s){return s.id;}

function slotRow(s,h){
 const {el,button,coins,fmt,command}=h,row=el('div',null,`mag-slot ${s.status}`);
 const info=el('div');
 info.append(itemMark(h,slotIcon(s)),el('strong',s.name),el('small',`${KIND_LABEL[s.kind]||s.kind}${s.series?` · «${s.series}»`:''} · ${s.note}`),
             el('small',`Осталось ${s.left} из ${s.limit}${s.qty>1?` · в пакете ×${s.qty}`:''}`));
 const block=slotBlock(s,coins());
 const actions=el('div',null,'qw-btn-stack');
 const send=n=>()=>command('merchant_buy',{visit_id:h.view().visit_id,slot:s.slot,qty:n});
 actions.append(button(`Купить · ${fmt(s.price)}`,send(1),'qw-btn secondary',!!block||h.busy?.()));
 if(!block&&s.kind==='dye'&&s.left>=5&&coins()>=s.price*5)actions.append(button(`Купить ×5 · ${fmt(s.price*5)}`,send(5),'qw-btn secondary',!!h.busy?.()));
 if(block)actions.append(el('p',block,'qw-btn-hint'));
 row.append(info,actions);
 return row;
}

function fairRow(g,fair,h){
 const {el,button,coins,fmt,command}=h,row=el('div',null,`mag-slot ${g.status}`);
 const info=el('div');info.append(itemMark(h,g.id),el('strong',g.name),el('small',`Праздничный ряд · ${fair.name}${g.note?` · ${g.note}`:''}`));
 const block=g.status==='owned'?'Уже у тебя':g.status==='locked'?`С ${g.level} уровня`:coins()<g.price?'Не хватает монет':'';
 const actions=el('div',null,'qw-btn-stack');
 actions.append(button(`Купить · ${fmt(g.price)}`,()=>command('festival_buy',{festival:fair.id,item:g.id}),'qw-btn secondary',!!block||!!h.busy?.()));
 if(block)actions.append(el('p',block,'qw-btn-hint'));
 row.append(info,actions);
 return row;
}

function shelf(p,v,h){
 const {el,card,note}=h;
 const c=card('Прилавок','Шесть мест, цены по уровню вещи','coin');c.classList.add('mag-shelf');
 if(!v.slots.length)note('Прилавок пуст.',c);
 for(const s of v.slots)c.append(slotRow(s,h));
 note('Купленное привязано к ферме: его нельзя подарить, выставить в лавку соседа, отдать в фонд или положить в обоз.',c);
 p.append(c);
 const fair=v.fair,goods=(h.festivalGoods?.()||[]).filter(g=>fair?.goods?.includes(g.id));
 if(fair&&goods.length){
  const f=card('Праздничный ряд',fair.name,'coin');f.classList.add('mag-fair');
  for(const g of goods)f.append(fairRow(g,fair,h));
  p.append(f);
 }
}

function sellTab(p,v,h){
 const {el,card,button,note,fmt,command}=h,w=v.wants;
 const c=card('Скупка','Сорока берёт одну вещь за визит','coin');c.classList.add('mag-sell');
 if(!w){note('Сорока сегодня ничего не покупает.',c);p.append(c);return;}
 const name=h.itemName(w.item),qty=sellQty(w),block=sellBlock(w);
 const row=el('div',null,'mag-want');
 row.append(itemMark(h,w.item),el('strong',name),el('small',`Платит ${fmt(w.unit)} мон. за штуку (+${w.bonus_pct}% к цене склада). У тебя: ${fmt(w.have)}.`),
            el('small',`Сегодня возьмёт ещё до ${fmt(w.room)} шт.`));
 c.append(row);
 const actions=el('div',null,'qw-btn-stack');
 const send=n=>()=>command('merchant_sell',{visit_id:v.visit_id,item:w.item,qty:n});
 actions.append(button(qty>1?`Продать ${qty} шт. · +${fmt(w.unit*qty)}`:`Продать · +${fmt(w.unit)}`,send(Math.max(1,qty)),'qw-btn primary',!!block||qty<1||!!h.busy?.()));
 if(block)actions.append(el('p',block,'qw-btn-hint'));
 c.append(actions);
 note(`Всего за визит Сорока скупает на сумму до ${fmt(v.cap)} мон. по цене склада; сегодня уже взяла на ${fmt(v.sold_value)}.`,c);
 p.append(c);
}

function collection(p,v,h){
 const names=h.catalog?.merchant?.curios||{};
 const mine=v.curios||[];
 if(!mine.length)return;
 const {el,card,button}=h,c=card('Коллекция Сороки','Диковинки, которые у тебя уже есть','discovery');
 const list=el('ul',null,'mag-collection');
 for(const id of mine){
  const li=el('li',null),placed=h.placed?.(id);
  li.append(itemMark(h,id),el('span',names[id]?.name||id));
  if(h.place&&!placed)li.append(button('Поставить',()=>h.place(id),'qw-btn secondary',!!h.busy?.()));
  else if(placed)li.append(el('small','Стоит на ферме'));
  list.append(li);
 }
 c.append(list);p.append(c);
}

export function renderShop(p,v,h){
 const {el,card,button,note}=h;
 if(!v){note('Лавка Сороки пока недоступна. Обнови ферму.',p);return;}
 h.view=()=>v;
 const now=h.now();
 const head=card('Сорока-коробейница',present(v)?(v.kind==='fair'?'Приехала на ярмарку':'Приехала на рынок'):'Сейчас в разъездах','coin');
 head.classList.add('mag-head');
 head.append(el('p',statusText(v,now),'reward'));
 if(present(v))head.append(el('p','Тр-р-р, налетай! Такого в ваших краях не растёт.','village-dialogue'));
 p.append(head);
 if(!present(v)){
  if(v.teaser)note(`Завтра Сорока обещала привезти: ${v.teaser}.`,head);
  else note('За сутки до приезда «Вестник» расскажет, что она везёт.',head);
  collection(p,v,h);
  return;
 }
 const tabs=el('div',null,'qw-btn-group');tabs.setAttribute('role','group');tabs.setAttribute('aria-label','Раздел лавки');
 for(const [id,label] of [['shelf','Прилавок'],['sell','Скупка']]){
  const b=button(label,()=>{setTab(id);h.rerender?.();},'qw-btn secondary');b.setAttribute('aria-pressed',String(shopTab===id));b.dataset.merchantTab=id;tabs.append(b);
 }
 p.append(tabs);
 if(shopTab==='sell')sellTab(p,v,h);else shelf(p,v,h);
 collection(p,v,h);
}
