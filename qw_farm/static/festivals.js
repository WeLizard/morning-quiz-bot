// Festivals UI (FARM_FESTIVALS_DESIGN.md section 9). The server owns the calendar, prices, limits and rewards
// (qw_farm/festivals.py, S.me.festival); this module only shows them and sends festival_task / festival_buy.
// Decor layers are HOOKS: applyWorld() writes data-festival-* flags on <html>; the designer's scene layers read them.
export const PREF_KEYS={decor:'qw-farm.festival-decor',scares:'qw-farm.festival-scares'};
const KIND_LABEL={decor:'Декор',decor_big:'Крупный декор',wall:'На забор',roof:'На крышу',path:'Вдоль дорожки',village:'Для площади',mascot:'Маскот',tree_decor:'Декоративное дерево',voucher:'Талон сада',graft:'Прививка',scroll:'Свиток',curio:'Диковинка',keepsake:'Памятный предмет'};
const SELLER_LABEL={agata:'Шатёр Агаты',sonya:'Лавка Сони',magpie:'Тележка Сороки',host:'Лавка хозяина праздника'};
const SELLER_ORDER=['agata','sonya','magpie','host'];

function readPref(key,store){try{return (store||globalThis.localStorage).getItem(key);}catch{return null;}}
// Decorations are shown by default; the player may hide them (device setting, like the lighting mode).
export function decorOn(store){return readPref(PREF_KEYS.decor,store)!=='off';}
export function scaresOn(store){return readPref(PREF_KEYS.scares,store)!=='off';}
export function setPref(name,on,store){try{(store||globalThis.localStorage).setItem(PREF_KEYS[name],on?'on':'off');}catch{}}

// What the world should look like right now. «Страшилки» only exist on the Pumpkin Night and sit on top of the decor switch.
export function worldFlags(view,store){
 const cur=view?.current||null,decor=!!cur&&decorOn(store);
 return {festival:cur?.id||'',phase:cur?.phase||'',decor,scares:decor&&cur.id==='pumpkin_night'&&scaresOn(store),birthday:view?.birthday?.years||0};
}
export function applyWorld(view,root=globalThis.document?.documentElement,store){
 if(!root)return null;
 const f=worldFlags(view,store),set=(name,value)=>{if(value)root.dataset[name]=String(value);else delete root.dataset[name];};
 set('festival',f.festival);set('festivalPhase',f.phase);set('festivalDecor',f.decor?'on':'');set('festivalScares',f.scares?'on':'');set('festivalBirthday',f.birthday||'');
 return f;
}
// Last year's lots are hidden while the same festival's fair is open: the stall already sells them at the fair price.
export function pastShop(view){const cur=view?.current;return (view?.past||[]).filter(p=>!p.live&&!(cur&&cur.phase==='fair'&&cur.id===p.id));}
export function tabVisible(view){return !!view&&(!!view.current||!!view.upcoming?.soon||!!pastShop(view).length||Object.keys(view.collection||{}).length>0);}

// Pure helpers (unit-tested).
export function canHandIn(task,optionIndex,stock){
 const needs=task.options[optionIndex];if(!needs||task.done||task.locked)return false;
 return Object.entries(needs).every(([id,q])=>(stock(id)||0)>=q);
}
export function goodBlock(good,coins){
 if(good.status==='owned')return 'Уже у тебя';
 if(good.status==='locked')return `С ${good.level} уровня`;
 if(good.away)return 'Сорока уехала';
 if(coins<good.price)return 'Не хватает монет';
 return '';
}
export function groupBySeller(goods){
 const groups=new Map();
 for(const g of goods)(groups.get(g.seller)||groups.set(g.seller,[]).get(g.seller)).push(g);
 return SELLER_ORDER.filter(s=>groups.has(s)).map(s=>[s,groups.get(s)]);
}
export function bannerText(view,format=new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'long',timeZone:'Europe/Moscow'})){
 const cur=view?.current,date=at=>format.format(new Date(at*1000));
 if(cur)return cur.phase==='fair'?`${cur.name}: ярмарка на площади. Шатёр и задания открыты.`:`${cur.name}: деревня наряжается. Ярмарка ещё впереди.`;
 const up=view?.upcoming;
 return up?.soon?`Скоро: ${up.name}, с ${date(up.starts_at)}.`:'';
}

export function renderFestival(p,view,h){
 const {el,button,card,goods,note,stock,coins,fmt,command,itemName}=h;
 if(!view){note('Календарь праздников пока недоступен. Обнови ферму.',p);return;}
 const text=bannerText(view),cur=view.current,fair=view.fair;
 const head=card(cur?.name||view.upcoming?.name||'Праздники',cur?`Ведёт ${cur.host}`:'Скоро','coin');
 head.classList.add('fest-banner');
 if(text)head.append(el('p',text,'note'));
 if(view.birthday)head.append(el('p',`У фермы день рождения: ${view.birthday.years} г.`,'note'));
 head.append(el('p','Праздник ничего не отнимает: украшения и ярмарка — только радость. Памятный предмет года не возвращается, остальное можно найти в «Лавке прошлых праздников».','note'));
 p.append(head);
 if(fair){
  if(fair.todo){p.append(card('Ярмарка готовится','Содержимое этого праздника ещё в работе','coin'));}
  if(fair.tasks.length){
   const c=card('Праздничные задания','Награда — предмет праздника, без монет и опыта','journal');c.classList.add('fest-tasks');
   for(const t of fair.tasks){
    const row=el('div',null,`fest-task${t.done?' done':''}`);
    const reward=el('small',null);reward.append(itemMark(h,t.reward.id),el('span',`${t.host} · награда: ${t.reward.name}${t.locked?` · с ${t.level} уровня`:''}`));
    row.append(el('strong',t.done?`${t.title} · готово`:t.title),reward);
    if(!t.done){
     const stack=el('div',null,'qw-btn-stack');
     t.options.forEach((needs,i)=>{
      const line=el('div',null,'fest-option');line.append(goods(needs));
      line.append(button('Сдать',()=>command('festival_task',{festival:fair.id,task:t.id,option:i}),'qw-btn secondary',!canHandIn(t,i,stock)||h.busy?.()));
      stack.append(line);
     });
     row.append(stack);
    }
    c.append(row);
   }
   if(fair.keepsake){const k=el('p',null,'note');k.append(itemMark(h,fair.keepsake.id),el('span',fair.keepsake.got?`${fair.keepsake.name}: в коллекции навсегда.`:`Все задания — и «${fair.keepsake.name}» твои. Только в этом году.`));c.append(k);}
   p.append(c);
  }
  if(fair.goods.length){
   const c=card('Ярмарка на площади','Всё за монеты, без дефицита','coin');c.classList.add('fest-stall');
   for(const [seller,items] of groupBySeller(fair.goods)){
    const group=el('div',null,'fest-group');group.append(el('h3',SELLER_LABEL[seller]||seller));
    if(seller==='magpie'&&!fair.magpie)group.append(el('small','Сорока приезжает в первый день ярмарки.'));
    for(const g of items)group.append(goodRow(g,g.price,h,fair.id));
    c.append(group);
   }
   p.append(c);
  }
 }
 const past=pastShop(view);
 if(past.length){
  const d=el('details',null,'village-services fest-past');d.dataset.villageService='Лавка прошлых праздников';
  d.append(el('summary','Лавка прошлых праздников'));
  d.append(el('p',`Вещи прошлых ярмарок продаются всегда, на ${view.past_markup_pct-100}% дороже.`,'note'));
  for(const entry of past){
   const group=el('div',null,'fest-group');group.append(el('h3',`${entry.name} ${entry.year}`));
   for(const g of entry.goods)group.append(goodRow(g,g.price,h,entry.id));
   d.append(group);
  }
  p.append(d);
 }
 const mine=Object.entries(view.collection||{});
 if(mine.length){
  const c=card('Коллекция праздников','Всё, что у тебя уже есть','journal');
  const list=el('ul',null,'fest-collection');
  for(const [id,row] of mine){const li=el('li',null),name=el('b',null);name.append(itemMark(h,id),el('span',row.name));li.append(name,el('small',`${KIND_LABEL[row.kind]||row.kind} · ${row.years.join(', ')}${row.count>1?` · ×${row.count}`:''}${row.wired?'':' · появится в мире с оформлением'}`));list.append(li);}
  c.append(list);p.append(c);
 }
 p.append(settingsCard(view,h));
}

// The item's own icon (icons.svg#<id>; festival item ids are the fest_posid_* symbols), in the same .good box as the goods rows.
function itemMark(h,id){const mark=h.el('span',null,'good');mark.append(h.icon(id));return mark;}

function goodRow(g,cost,h,festival){
 const {el,button,coins,fmt,command}=h,row=el('div',null,`fest-good ${g.status}`);
 const info=el('div');info.append(itemMark(h,g.id),el('strong',g.name),el('small',`${KIND_LABEL[g.kind]||g.kind}${g.note?` · ${g.note}`:''}`));
 const block=goodBlock(g,coins());
 const actions=el('div',null,'qw-btn-stack');
 actions.append(button(`Купить · ${fmt(cost)}`,()=>command('festival_buy',{festival,item:g.id}),'qw-btn secondary',!!block||h.busy?.()));
 if(block)actions.append(el('p',block,'qw-btn-hint'));
 row.append(info,actions);
 return row;
}

export function settingsCard(view,h){
 const {el,checkbox}=h,c=h.card('Праздничное оформление','Настройка этого устройства','sun');
 const [dw,decor]=checkbox('Показывать праздничные украшения',decorOn());
 decor.onchange=()=>{setPref('decor',decor.checked);applyWorld(view);h.rerender?.();};
 c.append(dw);
 if(view?.current?.id==='pumpkin_night'){
  const [sw,scares]=checkbox('Страшилки Тыквенной ночи',scaresOn());
  scares.disabled=!decorOn();
  scares.onchange=()=>{setPref('scares',scares.checked);applyWorld(view);h.rerender?.();};
  c.append(sw);
 }
 return c;
}

// Menu ⚙ entries for QW.menu.register: «Праздничное оформление» (shown by default) and «Страшилки».
export function menuItems(getView,rerender){
 const refresh=()=>{applyWorld(getView());rerender?.();};
 return [
  {id:'farm-festival-decor',icon:'sun',label:'Праздничное оформление',hint:'показывать украшения',hidden:()=>!getView(),toggle:()=>decorOn(),onSelect:()=>{setPref('decor',!decorOn());refresh();}},
  {id:'farm-festival-scares',icon:'sun',label:'Страшилки Тыквенной ночи',hint:'показывать',hidden:()=>getView()?.current?.id!=='pumpkin_night',toggle:()=>scaresOn(),onSelect:()=>{setPref('scares',!scaresOn());refresh();}}
 ];
}
