// Festivals UI (FARM_FESTIVALS_DESIGN.md section 9). The server owns the calendar, prices, limits and rewards
// (qw_farm/festivals.py, S.me.festival); this module only shows them and sends festival_task / festival_buy.
// Decor layers are HOOKS: applyWorld() writes data-festival-* flags on <html>; the designer's scene layers read them.
export const PREF_KEYS={decor:'qw-farm.festival-decor',scares:'qw-farm.festival-scares'};
const KIND_LABEL={decor:'Декор',decor_big:'Крупный декор',wall:'На забор',roof:'На крышу',path:'Вдоль дорожки',village:'Для площади',mascot:'Маскот',tree_decor:'Декоративное дерево',voucher:'Талон сада',graft:'Прививка',scroll:'Свиток',curio:'Диковинка',keepsake:'Памятный предмет',joke:'Шутка'};
const SELLER_LABEL={agata:'Шатёр Агаты',sonya:'Лавка Сони',magpie:'Тележка Сороки',host:'Лавка хозяина праздника'};
const SELLER_ORDER=['agata','sonya','magpie','host'];
// The host's stall has the host's own sign (qw_farm/festivals.py seller='host'); the generic label is the fallback.
export const HOST_SHOP={april_fools:'Честная лавка Даши',cosmonautics:'Мастерская Крота',spring_sowing:'Семенной ларёк Игоря',milk_day:'Молочный прилавок Каи',
 berry_fest:'Прилавок Каи',fisher_day:'Снасти Лягуха Шарика',cucumber_day:'Соленья Игоря',spas:'Медовая лавка Пуха',knowledge_day:'Книжная лавка Филиныча',
 pumpkin_night:'Лавка неведомых вещей'};
export function sellerLabel(seller,festival){return seller==='host'&&HOST_SHOP[festival]||SELLER_LABEL[seller]||seller;}
// Icons of festival items. An item without its own symbol in icons.svg borrows a neutral symbol of the same kind from the first
// festival (nothing renders blank). When the artist draws icons.svg#<id>, delete the line here (tests/js/farm_festivals.test.cjs checks it).
export const ICON_FALLBACK={
 // День смеха
 fest_fool_jar:'fest_posid_basket',fest_fool_sock:'fest_posid_basket',fest_fool_horseshoe:'fest_posid_basket',fest_fool_cake:'fest_posid_basket',fest_fool_mirror:'fest_posid_window',fest_fool_stripes:'fest_posid_wreath',fest_fool_whistle:'fest_posid_lantern',fest_fool_cap:'fest_posid_smoke',fest_fool_signs:'fest_posid_window',fest_fool_geese:'fest_posid_basket',fest_fool_scarecrow:'fest_posid_socks',
 // День космонавтики
 fest_cosm_rocket:'fest_posid_quilt',fest_cosm_parts:'fest_posid_basket',fest_cosm_path:'fest_posid_lights',fest_cosm_scroll:'fest_posid_basket',fest_cosm_meteor:'fest_posid_lantern',fest_cosm_flags:'fest_posid_wreath',fest_cosm_birdhouse:'fest_posid_basket',fest_cosm_stars:'fest_posid_window',fest_cosm_badge:'fest_posid_socks',
 // Весенний сев и субботник
 fest_sow_birch:'fest_posid_rowan',fest_sow_birdhouse:'fest_posid_basket',fest_sow_sprouts:'fest_posid_lights',fest_sow_voucher:'fest_posid_voucher',fest_sow_seeds:'fest_posid_lantern',fest_sow_rakes:'fest_posid_basket',fest_sow_bridge:'fest_posid_window',fest_sow_ties:'fest_posid_wreath',fest_sow_sprout:'fest_posid_socks',
 // День молока
 fest_milk_can:'fest_posid_basket',fest_milk_stall:'fest_posid_window',fest_milk_path:'fest_posid_lights',fest_milk_calf:'fest_posid_snowman',fest_milk_scroll:'fest_posid_basket',fest_milk_holes:'fest_posid_lantern',fest_milk_garland:'fest_posid_window',fest_milk_churn:'fest_posid_basket',fest_milk_daisies:'fest_posid_wreath',fest_milk_cow:'fest_posid_socks',
 // Ягодный праздник
 fest_berry_kettle:'fest_posid_quilt',fest_berry_baskets:'fest_posid_basket',fest_berry_path:'fest_posid_lights',fest_berry_stall:'fest_posid_window',fest_berry_blue:'fest_posid_lantern',fest_berry_garland:'fest_posid_window',fest_berry_jars:'fest_posid_basket',fest_berry_butterflies:'fest_posid_smoke',fest_berry_berry:'fest_posid_socks',
 // Иван Купала
 fest_kup_flies:'fest_posid_basket',fest_kup_path:'fest_posid_lights',fest_kup_lavender:'fest_posid_wreath',fest_kup_float:'fest_posid_window',fest_kup_moon:'fest_posid_lantern',fest_kup_gate:'fest_posid_wreath',fest_kup_fern:'fest_posid_basket',fest_kup_fire:'fest_posid_window',fest_kup_firefly:'fest_posid_socks',
 // День рыбака
 fest_fish_boat:'fest_posid_quilt',fest_fish_tackle:'fest_posid_basket',fest_fish_boats:'fest_posid_window',fest_fish_path:'fest_posid_lights',fest_fish_lure:'fest_posid_lantern',fest_fish_rods:'fest_posid_basket',fest_fish_flags:'fest_posid_window',fest_fish_net:'fest_posid_wreath',fest_fish_float:'fest_posid_socks',
 // День огурца
 fest_cuc_barrel:'fest_posid_basket',fest_cuc_barrels:'fest_posid_window',fest_cuc_path:'fest_posid_lights',fest_cuc_scroll:'fest_posid_basket',fest_cuc_bumpy:'fest_posid_lantern',fest_cuc_jars:'fest_posid_basket',fest_cuc_vines:'fest_posid_wreath',fest_cuc_arch:'fest_posid_window',fest_cuc_pickle:'fest_posid_socks',
 // Спасы: мёд, яблоки, орехи
 fest_spas_barrel:'fest_posid_basket',fest_spas_apples:'fest_posid_basket',fest_spas_stall:'fest_posid_window',fest_spas_bee:'fest_posid_snowman',fest_spas_nutcracker:'fest_posid_lantern',fest_spas_hives:'fest_posid_smoke',fest_spas_wreath:'fest_posid_window',fest_spas_nuts:'fest_posid_wreath',fest_spas_apple:'fest_posid_socks',
 // День знаний
 fest_know_globe:'fest_posid_basket',fest_know_abc:'fest_posid_wreath',fest_know_path:'fest_posid_lights',fest_know_scroll:'fest_posid_basket',fest_know_spyglass:'fest_posid_lantern',fest_know_porch:'fest_posid_basket',fest_know_satchel:'fest_posid_basket',fest_know_board:'fest_posid_window',fest_know_bell:'fest_posid_socks',
 // Осенняя ярмарка урожая
 fest_harv_monument:'fest_posid_quilt',fest_harv_sheaf:'fest_posid_basket',fest_harv_rowan:'fest_posid_rowan',fest_harv_path:'fest_posid_lights',fest_harv_sign:'fest_posid_window',fest_harv_hedgehog:'fest_posid_snowman',fest_harv_scroll:'fest_posid_basket',fest_harv_gourd:'fest_posid_lantern',fest_harv_pumpkins:'fest_posid_basket',fest_harv_flag:'fest_posid_smoke',fest_harv_cart:'fest_posid_window',fest_harv_gate:'fest_posid_wreath',fest_harv_pumpkin:'fest_posid_socks',
 // Тыквенная ночь
 fest_pn_lantern:'fest_posid_basket',fest_pn_glow:'fest_posid_window',fest_pn_bat:'fest_posid_snowman',fest_pn_thing:'fest_posid_lantern',fest_pn_web:'fest_posid_wreath',fest_pn_lanterns:'fest_posid_lights',fest_pn_scarecrow:'fest_posid_basket',fest_pn_owl:'fest_posid_socks',
};
export function iconId(id){return Object.prototype.hasOwnProperty.call(ICON_FALLBACK,id)?ICON_FALLBACK[id]:id;}

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

function santaCard(p,h){
 const game=h.santa?.();if(!game)return;
 const {el,button,card}=h,wins=(game.battles||[]).filter(b=>b.stars>0).length;
 const c=card('Битва с Сантой','Дед Мороз зовёт на площадь у ёлки','journal');c.classList.add('fest-santa');
 const rows=(game.battles||[]).map(b=>`бой ${b.n}: ${b.stars?'★'.repeat(b.stars)+'☆'.repeat(3-b.stars):b.open?'ждёт':'закрыт'}`).join(' · ');
 c.append(el('p',`Снежная дуэль: ты, Дед Мороз и Снегурочка против Санты и Крампуса. ${rows}.`,'note'));
 const label=game.active?'Продолжить бой':wins?'К боям':'Играть';
 const play=button(label,()=>h.santaGame?.(),'qw-btn primary',!!h.busy?.()||!!game.locked);play.dataset.openSanta='';
 c.append(play);
 if(game.locked)c.append(el('p',`С ${game.min_level} уровня.`,'note'));
 p.append(c);
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
 // The gift stays in the festival panel even when the optional decor and scares are hidden.
 if(cur?.id==='pumpkin_night')h.horsemanCard?.(p);
 // «Битва с Сантой» (FARM_SANTA_BATTLE.md): Дед Мороз calls to the square while the New Year lasts.
 if(cur?.id==='new_year')santaCard(p,h);
 if(fair){
  if(fair.tower){
   const t=fair.tower,pie=h.pie?.(),label=pie?.active?'Продолжить':!pie?'Играть':pie.attempts_left>0?(pie.last_result?'Ещё раз':'Играть'):'Тренировка';
   const c=card('Пирог до небес','Праздничная игра деревни','journal');c.classList.add('fest-pie');
   c.append(el('p',`Башня деревни: ${t.total} из ${t.goal}${t.players?` · участников: ${t.players}`:''}.${t.reached?` «${t.name}» уже у участников.`:''}`,'note'));
   const play=button(label,()=>h.pieGame?.(),'qw-btn primary',!!h.busy?.());play.dataset.openPie='';
   c.append(play);
   p.append(c);
  }
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
    const group=el('div',null,'fest-group');group.append(el('h3',sellerLabel(seller,fair.id)));
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
