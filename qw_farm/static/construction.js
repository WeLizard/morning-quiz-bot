// Village construction and the market rows (docs/tasks/FARM_VILLAGE_CONSTRUCTION.md). The server owns every number
// (qw_farm/construction.py, S.me.village_build); this module only shows them and sends build_contribute / build_speedup /
// stall_list / stall_buy / stall_cancel and tavern commands. Existing components only, no art of its own.
const STAGE_LOWER=['котлован','каркас','отделка'];
const TIER_ICON=['','①','②','③'];
const TAVERN_NAME='Игривая кобыла';
const TRAY_DISHES={pie:'Пирог',tea:'Чай',pancake:'Оладьи'};
const TAVERN_TOASTS={
 harvest:'За урожай!',
 dill:'За тех, кто посадил укроп и нашёл его весной!',
 foam:'Чтоб пенка выше забора!',
};

export const view=me=>me?.village_build||null;
export const project=(v,id)=>(v?.projects||[]).find(p=>p.id===id)||null;
export const rowsOpen=v=>!!v?.rows?.open;
/** The art a site shows on the map (§2.4, village-build.svg): the finished works of the stage — soon until the pit is dug,
 * pit while it is dug and until the frame works start, frame from then on, done when open. */
export function siteArt(p){
 if(!p||p.status==='soon')return 'soon';
 if(p.status==='done')return 'done';
 const stage=Number(p.stage)||0,work=p.status==='working';
 if(stage===0)return work?'pit':'soon';
 return stage===1&&!work?'pit':'frame';
}
/** The crew (Krot and two residents) stands on the site while the residents work. */
export const crewAt=p=>p?.status==='working';
/** Stalls of the rows (§5.1): Сорока's only on her visit, Sonya's shuttered 23–7 Moscow time, the players' one while it has lots. */
export function stallStates(me,now){
 const hour=Math.floor(((Number(now)||0)+3*3600)%86400/3600),rows=me?.village_build?.rows;
 return {magpie:me?.merchant_view?.active?'open':'closed',igor:'open',sonya:hour>=23||hour<7?'closed':'open',agata:'open',post:'open',
  player:rows?.lots?.length||rows?.own?.length?'open':'closed'};
}

export function refFor(level,bands){
 const lv=Math.max(1,Math.min(50,Number(level)||1));
 for(const [lo,hi,value] of bands||[])if(lv>=lo&&lv<=hi)return value;
 return 1;
}
/** Part of a stage still to be paid in, per need key: [{key, need, got, left}]; coins last. */
export function needRows(p){
 const rows=Object.entries(p?.need||{}).map(([key,need])=>({key,need,got:Math.min(need,p.got?.[key]||0),left:Math.max(0,need-(p.got?.[key]||0))}));
 return [...rows.filter(r=>r.key!=='coins'),...rows.filter(r=>r.key==='coins')];
}
export function stagePct(p){
 const rows=needRows(p),total=rows.reduce((s,r)=>s+r.need,0);
 return total?Math.floor(100*rows.reduce((s,r)=>s+r.got,0)/total):0;
}
export function timeLeft(seconds){
 seconds=Math.max(0,Math.ceil(seconds));
 const d=Math.floor(seconds/86400),h=Math.floor(seconds%86400/3600),m=Math.ceil(seconds%3600/60);
 if(d)return h?`${d} д ${h} ч`:`${d} д`;
 if(h)return m&&m<60?`${h} ч ${m} мин`:`${h} ч`;
 return `${Math.max(1,m)} мин`;
}
/** The caption on the map and on the site sign. */
export function siteLabel(p,fallback,now){
 if(!p||p.status==='soon')return `Скоро · ${fallback}`;
 if(p.status==='collecting')return `${p.name} · ${STAGE_LOWER[p.stage]} · ${stagePct(p)}%`;
 if(p.status==='working')return `${p.name} · ${STAGE_LOWER[p.stage]} · готово через ${timeLeft((p.work_until||now)-now)}`;
 return `${p.name} · готово`;
}
/** Own tier and what is missing for the next one, in coins of value at the player's level. */
export function tierInfo(p,v,level,bands){
 const mine=p?.mine||{tier:0,share_bp:0,value:0},bp=v?.tier_bp||[1000,4000,10000],names=v?.tier_names||['','Помощник','Мастер','Почётный строитель'];
 const next=mine.tier<3?bp[mine.tier]:null,ref=refFor(level,bands);
 return {tier:mine.tier,name:names[mine.tier]||'',nextName:next==null?null:names[mine.tier+1],
  missing:next==null?0:Math.max(0,Math.ceil((next-mine.share_bp)*ref/10000))};
}
/** Hint under the contribute button; exactly what the server will accept, clipped to what the stage still needs. */
export function offerLimit(row,stock,coinsEarned){
 if(row.key==='coins')return Math.max(0,Math.min(row.left,coinsEarned));
 return Math.max(0,Math.min(row.left,stock[row.key]||0));
}
export function lotPriceRange(base,minPct=100,maxPct=150){return [base,Math.floor(base*maxPct/100)];}
export function buyBlock(lot,earned,rows){
 if(lot.buys_today>=rows.buys_per_day)return 'Сегодня уже три покупки у этого продавца';
 if(earned<lot.qty*lot.unit_price)return 'Не хватает заработанных монет';
 return '';
}
export function energyChoice(inventory,energy,room){
 const best=energy.map(id=>[id,inventory?.[id]||0]).sort((a,b)=>b[1]-a[1])[0];
 if(!best||!best[1])return null;
 const per=7200,qty=Math.min(best[1],Math.floor(room/per));
 return qty>0?{item:best[0],qty}:null;
}

export function createConstruction(h){
 const v=()=>view(h.me());
 const earned=()=>Math.max(0,(h.me()?.coins||0)-(h.me()?.starter_credit||0));
 const bands=()=>h.catalog()?.economy?.income_ref||[];
 const label=(id,fallback)=>id==='tavern'&&project(v(),id)?.status==='done'&&v()?.tavern
  ?TAVERN_NAME:siteLabel(project(v(),id),fallback,h.now());
 let trayDraft=null;

 function draftFor(day){
  const key=`qw-farm.tavern-tray.${h.me().id}`;
  if(trayDraft?.key===key&&trayDraft.day===day)return trayDraft;
  let cells=Array(6).fill(null);
  try{
   const saved=JSON.parse(sessionStorage.getItem(key));
   const candidate=saved?.cells;
   if(saved?.day===day&&Array.isArray(candidate)&&candidate.length===6){
    const dishes=candidate.filter(id=>id!==null);
    if(dishes.every(id=>Object.hasOwn(TRAY_DISHES,id))&&new Set(dishes).size===dishes.length)cells=candidate;
   }
  }catch{}
  trayDraft={key,day,cells,selected:null};
  return trayDraft;
 }

 function tavernControl(button,key){
  button.dataset.villageFocus=key;
  return button;
 }

 function tavernStatus(text,key){
  const status=tavernControl(h.el('p',text,'note'),key);
  status.tabIndex=-1;
  return status;
 }

 function renderTavernOrder(parent,day,order){
  const card=h.card('Заказ дня',order?`${h.itemName(order.item)} ×${order.qty}`:null,order?.item||'orders');
  if(!order){
   h.note('Заказ появится, когда на ферме откроется подходящий рецепт.',card);
  }else if(order.done){
   card.append(tavernStatus(`Заказ сдан · +${h.fmt(order.coins)} мон.`,'tavern-order'));
  }else{
   const stock=h.me().inventory?.[order.item]||0;
   card.append(h.goods({[order.item]:order.qty}));
   const send=tavernControl(h.button(`Сдать заказ · +${h.fmt(order.coins)} мон.`,
    ()=>h.command('tavern_order',{day,item:order.item}),'qw-btn secondary wide',stock<order.qty),'tavern-order');
   send.dataset.tavernOrder='';
   card.append(send);
   if(stock<order.qty)h.note('На складе пока не хватает блюда.',card);
  }
  parent.append(card);
 }

 function renderTray(parent,day,puzzle){
  const card=h.card('Поднос с характером','Бесплатно · без таймера','pie');
  const stamps=h.el('p',`Печатей собрано: ${h.fmt(puzzle.stamps)}`,'note');
  stamps.dataset.tavernStamps='';
  if(puzzle.done){
   const success=tavernStatus('✓ Поднос пережил смену','tavern-serve');
   success.dataset.tavernStamp='';
   card.append(success,stamps);
   parent.append(card);
   return;
  }

  const rules=h.el('ul',null,'note tavern-rules');
  for(const rule of [
   'Пух просит пирог в середину ряда.',
   'Соня хочет чай на соседней клетке слева от пирога.',
   'Олег просит оладьи в другой ряд, подальше от крошек.',
  ])rules.append(h.el('li',rule));
  card.append(rules);

  const draft=draftFor(day);
  const palette=h.el('div',null,'qw-btn-row tavern-grid');
  palette.setAttribute('role','group');
  palette.setAttribute('aria-label','Блюда для подноса');
  const pieces=Object.entries(TRAY_DISHES).map(([id,name])=>{
   const button=tavernControl(h.button(null,()=>{
    draft.selected=draft.selected===id?null:id;
    syncBoard();
   },'qw-btn tavern-dish'),`tavern-piece-${id}`);
   button.dataset.tavernPiece=id;
   button.append(h.icon(id),h.el('span',name));
   palette.append(button);
   return button;
  });

  const tray=h.el('div',null,'qw-btn-row tavern-grid tavern-tray');
  tray.setAttribute('role','group');
  tray.setAttribute('aria-label','Поднос, два ряда по три клетки');
  const slots=draft.cells.map((_,index)=>{
   const button=tavernControl(h.button(null,()=>{
    const at=draft.cells[index];
    if(draft.selected&&at!==draft.selected){
     const previous=draft.cells.indexOf(draft.selected);
     if(previous>=0)draft.cells[previous]=at;
     draft.cells[index]=draft.selected;
     try{sessionStorage.setItem(draft.key,JSON.stringify({day,cells:draft.cells}));}catch{}
     draft.selected=null;
    }else{
     draft.selected=at===draft.selected?null:at;
    }
    syncBoard();
   },'qw-btn tavern-dish'),`tavern-cell-${index}`);
   button.dataset.tavernCell=String(index);
   tray.append(button);
   return button;
  });
  const hint=h.el('p',null,'note tavern-hint');
  hint.setAttribute('role','status');
  const send=tavernControl(h.button('Подать',()=>h.command('tavern_serve',{day,cells:[...draft.cells]}),
   'qw-btn primary wide'),'tavern-serve');
  send.dataset.tavernServe='';

  function syncBoard(){
   for(const button of pieces)button.setAttribute('aria-pressed',String(button.dataset.tavernPiece===draft.selected));
   slots.forEach((button,index)=>{
    const id=draft.cells[index];
    const name=id?TRAY_DISHES[id]:'Пусто';
    button.replaceChildren(...(id?[h.icon(id)]:[]),h.el('span',name));
    button.setAttribute('aria-label',`Ряд ${Math.floor(index/3)+1}, место ${index%3+1}. ${name}`);
    button.setAttribute('aria-pressed',String(!!id&&id===draft.selected));
   });
   send.disabled=draft.cells.filter(Boolean).length!==3;
   hint.textContent=draft.selected
    ?`Выбрано: ${TRAY_DISHES[draft.selected]}. Нажми на клетку.`
    :send.disabled?'Выбери блюдо, затем клетку. Блюда можно переставлять.':'Можно подать поднос или переставить блюда.';
  }
  syncBoard();
  card.append(palette,tray,hint,send,stamps);
  parent.append(card);
 }

 function renderTavern(parent,tavern){
  h.heading(TAVERN_NAME,'Овёс не подаём. Сами едим');
  renderTavernOrder(parent,tavern.day,tavern.order);
  renderTray(parent,tavern.day,tavern.puzzle);
  const mug=h.card('Кобыла в пене','Бесплатная кружка дня','fest_mas_tea');
  if(tavern.toast){
   mug.append(tavernStatus(TAVERN_TOASTS[tavern.toast],`tavern-toast-${tavern.toast}`));
  }else{
   h.note('Подними кружку и выбери тост.',mug);
   const toasts=h.el('div',null,'qw-btn-stack');
   for(const [toast,label] of Object.entries(TAVERN_TOASTS)){
    const button=tavernControl(h.button(label,()=>h.command('tavern_toast',{day:tavern.day,toast}),'qw-btn secondary'),
     `tavern-toast-${toast}`);
    button.dataset.tavernToast=toast;
    toasts.append(button);
   }
   mug.append(toasts);
  }
  parent.append(mug);
  const reader=h.card('Почтальон Ёж','Читает «Вестник» за столиком');
  reader.append(tavernControl(h.button('Деревенский вестник',()=>h.bulletin('site:tavern'),'qw-btn secondary wide'),'bulletin'));
  parent.append(reader);
 }

 function timeline(p,parent){
  const list=h.el('ol',null,'build-timeline');
  const names=['Котлован · 1 сутки','Каркас · 2 суток','Отделка · 2 суток'];
  names.forEach((text,i)=>{
   const state=p.status==='done'||i<p.stage?'done':i===p.stage&&p.status!=='soon'?'now':'later';
   const li=h.el('li',`${state==='done'?'✓ ':state==='now'?'▶ ':'○ '}${text}`,`build-step ${state}`);
   list.append(li);
  });
  parent.append(list);
 }

 function needBlock(p,parent){
  for(const r of needRows(p)){
   const row=h.el('div',null,'build-need');
   const name=r.key==='coins'?'монеты':h.itemName(r.key);
   const have=r.key==='coins'?earned():(h.me().inventory?.[r.key]||0);
   row.append(h.el('span',`${name} ${r.got} / ${r.need}`),h.meter(r.got,r.need));
   if(r.left>0)row.append(h.el('small',`у тебя ${r.key==='coins'?h.fmt(have):have}`,'note'));
   else row.append(h.el('small','хватает','note'));
   parent.append(row);
  }
 }

 function contribute(p){
  const form=h.el('form',null,'build-form'),inputs=[];
  const stock=h.me().inventory||{},rows=needRows(p).filter(r=>r.left>0);
  for(const r of rows){
   const wrap=h.el('label',r.key==='coins'?'Монеты (заработанные)':h.itemName(r.key),'form-field'),input=h.el('input');
   input.type='number';input.inputMode='numeric';input.min='0';input.max=String(r.left);input.step='1';
   input.value=String(offerLimit(r,stock,earned()));input.setAttribute('aria-label',r.key==='coins'?'Монеты':h.itemName(r.key));
   input.dataset.key=r.key;wrap.append(input,h.el('small',`ещё нужно ${r.left}`,'note'));form.append(wrap);inputs.push(input);
  }
  form.append(h.el('p','Товары засчитываются по цене ×1,25. Лишнее сервер не берёт: оно остаётся у тебя.','note'));
  const send=h.button('Внести',async()=>{
   const items={};let coins=0;
   for(const i of inputs){const n=Math.max(0,Math.floor(Number(i.value)||0));if(!n)continue;if(i.dataset.key==='coins')coins=n;else items[i.dataset.key]=n;}
   if(!coins&&!Object.keys(items).length){h.toast('Укажи, сколько внести.',true);return;}
   if(await h.command('build_contribute',{project:p.id,items,coins}))h.close();
  },'qw-btn primary');
  form.onsubmit=e=>{e.preventDefault();send.onclick();};
  h.modal(`${p.name}: ${STAGE_LOWER[p.stage]}`,form,[send]);
 }

 function bonusTable(p,parent){
  const info=tierInfo(p,v(),h.me().level,bands());
  const box=h.el('div',null,'build-bonus');
  box.append(h.el('strong',info.tier?`Ты: ${TIER_ICON[info.tier]} ${info.name}`:'Пока без ступени'));
  if(info.nextName)box.append(h.el('small',`до «${info.nextName}» ещё около ${h.fmt(info.missing)} (доля от твоего дохода)`,'note'));
  const names=v().tier_names;
  p.bonus.forEach((text,i)=>{const li=h.el('p',`${TIER_ICON[i+1]} ${names[i+1]}: ${text}`,`build-perk${info.tier>i?' got':''}`);box.append(li);});
  box.append(h.el('small','Бонусы работают, когда здание открыто.','note'));
  parent.append(box);
 }

 function renderSite(p,id){
  const b=v();
  const proj=project(b,id);
  if(id==='tavern'&&proj?.status==='done'&&b.tavern)return renderTavern(p,b.tavern);
  h.heading(proj?.name||'Стройка','КРОТ С ЧЕРТЕЖОМ');
  if(!b||!proj){h.note('Данные стройки пока недоступны. Обнови ферму.',p);return;}
  const c=h.card('Механик Крот',siteLabel(proj,proj.name,h.now()));
  p.append(c);
  if(proj.status==='soon'){
   const active=project(b,b.active);
   c.append(h.el('p',active?`Чертёж «${proj.name}» ещё не вывешен. Сначала достроим «${active.name}».`:'Чертёж скоро появится на доске.','village-dialogue'));
   h.note('Стройки идут по очереди: ряды, трактир, оранжерея, ярмарочное поле.',c);
   return;
  }
  timeline(proj,c);
  if(proj.status==='collecting'){
   c.append(h.el('strong',`${proj.stage_name}: нужно собрать`));
   needBlock(proj,c);
   const locked=!b.level_ok,done=needRows(proj).every(r=>r.left===0);
   const send=h.button('Внести',()=>contribute(proj),'qw-btn primary',locked||done);
   c.append(send);
   if(locked)h.note(`Взносы открываются с ${b.level} уровня.`,c);
   else h.note('Вклад не возвращается. Товары засчитываются по цене ×1,25, монеты — только заработанные.',c);
  }else if(proj.status==='working'){
   const line=h.el('p',null,'reward');
   line.append(h.el('span','Жители работают · '));
   const t=h.timer(proj.work_until);t.dataset.untilPrefix='готово через ';line.append(t);
   c.append(line);
   const choice=energyChoice(h.me().inventory,b.energy,proj.speedup_room);
   const reason=proj.speedup_room<=0?'Пух уже выложился на этом этапе':!choice?'Нужен энергетос':'';
   c.append(h.button(choice?`Взбодрить Пуха · −${choice.qty*2} ч`:'Взбодрить Пуха',()=>h.command('build_speedup',{project:proj.id,item:choice.item,qty:choice.qty}),'qw-btn secondary',!choice));
   h.note(reason||'Каждый энергетос сокращает работы на 2 часа, но не больше суток на этап.',c);
   if(proj.fund_speed>0)h.note('Деревня выполнила цель фонда: бригада работает на сутки быстрее.',c);
  }else{
   c.append(h.el('p',`Открыто. ${id==='stalls'?'На площади работают торговые ряды.':'Эффект здания скоро включится.'}`,'reward'));
   if(id==='stalls')c.append(h.button('К торговым рядам',()=>h.open('rows'),'qw-btn primary'));
   const honor=(b.honor||{})[id]||[];
   if(honor.length)h.note(`Почётные строители: ${honor.join(', ')}.`,c);
  }
  const perks=h.card('Бонусы стройки',proj.name,'home');
  p.append(perks);bonusTable(proj,perks);
 }

 function stallCard(p,title,who,text,actionLabel,run,disabledReason=''){
  const c=h.card(who,title);
  c.classList.add('stall-card');
  c.append(h.el('p',text,'note'));
  if(actionLabel)c.append(h.button(actionLabel,run,'qw-btn secondary',!!disabledReason));
  if(disabledReason)h.note(disabledReason,c);
  p.append(c);
 }

 function renderRows(p){
  h.heading('Торговые ряды','ПЛОЩАДЬ ОЖИВЛЕНА');
  const b=v(),rows=b?.rows;
  if(!rowsOpen(b)){h.note('Торговые ряды ещё строятся. Пока табличка «Рынок» ведёт на склад.',p);p.append(h.button('Открыть склад',h.warehouse,'qw-btn secondary'));return;}
  const m=h.me().merchant_view;
  stallCard(p,'«Заезжие товары»','Сорока',m?.active?'Она сегодня на площади: диковинки, семена, скупка.':'Ставни закрыты: «Скоро вернусь — Сорока».','К лавке Сороки',h.merchant);
  stallCard(p,'Семенной ларёк','Суслик Игорь','Обмен урожая на сортовые семена — скоро.','',null,'');
  stallCard(p,'Ткацкая лавка','Кошка Соня','Узоры, уроки и красители. Ставни закрыты с 23 до 7, покупка работает.','К лавке Сони',()=>h.resident('Кошка Соня'));
  stallCard(p,'«Лавка прошлых праздников»','Агата','Вещи прошлых праздников; в дни праздника — праздничный шатёр.','К лавке Агаты',h.festival);
  const post=h.card('Почтальон Ёж','Почтовое окно');post.classList.add('stall-card');
  h.note('Просьбы к соседям и «Вестник» на стене.',post);
  const postActions=h.el('div',null,'qw-btn-stack');
  const news=h.button('Деревенский вестник',()=>h.bulletin(),'qw-btn secondary');news.dataset.villageFocus='bulletin';
  postActions.append(news,h.button('Записка для Ежа',h.post,'qw-btn secondary'));post.append(postActions);p.append(post);
  p.append(h.button('Продать со склада',h.warehouse,'qw-btn secondary'));
  p.append(h.el('h3','Лавки игроков','subheading'));
  if(!rows.lots.length)h.note('Пока на площади нет чужих лотов.',p);
  for(const lot of rows.lots){
   const c=h.card(lot.honor?`★ ${lot.seller}`:lot.seller,`${h.itemName(lot.item)} ×${lot.qty}`,lot.item);
   c.append(h.el('p',`${h.fmt(lot.unit_price)} за штуку · ${h.fmt(lot.unit_price*lot.qty)} всего`,'reward'));
   const block=buyBlock(lot,earned(),rows);
   c.append(h.button(`Купить · ${h.fmt(lot.unit_price*lot.qty)}`,()=>h.command('stall_buy',{lot:lot.id},lot.seller_farm),'qw-btn primary',!!block));
   if(block)h.note(block,c);
   p.append(c);
  }
  ownStall(p,rows);
 }

 function ownStall(p,rows){
  p.append(h.el('h3','Твоя лавка','subheading'));
  const c=h.card('Своя лавка на площади',`${rows.own.length} из ${rows.max_lots} мест`);
  p.append(c);
  if(!rows.access){h.note(`Своя лавка: со ступени «Мастер» торговых рядов или с ${rows.level} уровня.`,c);return;}
  h.note(`Цена — от 1 до 1,5 цены товара. Комиссия ${rows.commission_pct}%, аренда ${h.fmt(rows.rent)} мон. в неделю. Неделя без продаж — лавка закрывается, товар вернётся на склад.`,c);
  for(const lot of rows.own){
   const r=h.el('div',null,'stall-own');
   r.append(h.el('strong',`${h.itemName(lot.item)} ×${lot.qty}`),h.el('small',`${h.fmt(lot.unit_price)} за штуку`,'note'),
    h.button('Снять',()=>h.command('stall_cancel',{lot:lot.id}),'qw-btn secondary'));
   c.append(r);
  }
  if(rows.paid_until)h.note(`Место оплачено до ${new Date(rows.paid_until*1000).toLocaleDateString('ru-RU',{day:'numeric',month:'long'})}.`,c);
  if(rows.own.length>=rows.max_lots){h.note('Все места заняты.',c);return;}
  c.append(h.button('Выставить товар',()=>listForm(rows),'qw-btn primary'));
 }

 function listForm(rows){
  const inv=h.me().inventory||{},cat=h.catalog().items;
  const ids=Object.keys(inv).filter(id=>inv[id]>0&&cat[id]&&!h.isBound(id)).sort((a,b)=>h.itemName(a).localeCompare(h.itemName(b),'ru'));
  if(!ids.length){h.toast('На складе нечего выставить.',true);return;}
  const form=h.el('form',null,'stall-form');
  const iw=h.el('label','Товар','form-field'),item=h.el('select');item.setAttribute('aria-label','Товар');
  for(const id of ids){const o=h.el('option',`${h.itemName(id)} · ${inv[id]}`);o.value=id;item.append(o);}
  iw.append(item);
  const qw=h.el('label','Количество','form-field'),qty=h.el('input');qty.type='number';qty.min='1';qty.max='20';qty.value='1';qty.inputMode='numeric';qw.append(qty);
  const pw=h.el('label','Цена за штуку','form-field'),price=h.el('input');price.type='number';price.inputMode='numeric';pw.append(price);
  const hint=h.el('p',null,'note');
  const update=()=>{const base=cat[item.value].price,[lo,hi]=lotPriceRange(base,rows.price_min_pct,rows.price_max_pct);
   price.min=String(lo);price.max=String(hi);if(!price.value||Number(price.value)<lo||Number(price.value)>hi)price.value=String(lo);
   qty.max=String(Math.min(20,inv[item.value]));hint.textContent=`Можно от ${lo} до ${hi} за штуку.`;};
  item.onchange=update;update();
  form.append(iw,qw,pw,hint);
  const send=h.button('Выставить',async()=>{if(await h.command('stall_list',{item:item.value,qty:Number(qty.value),unit_price:Number(price.value)}))h.close();},'qw-btn primary');
  form.onsubmit=e=>{e.preventDefault();send.onclick();};
  h.modal('Лот в лавке на площади',form,[send]);
 }

 function render(p,sheet){
  if(sheet==='rows')return renderRows(p);
  return renderSite(p,String(sheet).slice(5));
 }
 return {render,siteLabel:label,rowsOpen:()=>rowsOpen(v()),
  art:id=>{const p=project(v(),id);return {stage:siteArt(p),crew:crewAt(p)};},stalls:()=>stallStates(h.me(),h.now())};
}
