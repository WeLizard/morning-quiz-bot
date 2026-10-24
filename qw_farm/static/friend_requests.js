// Requests are server-owned. The client never reserves stock or computes a reward.
export function offerText(row,itemName){
 if(row.offer_kind==='coins')return `${row.offer_coins} монет · комиссия Ежа 3%`;
 if(row.offer_kind==='item')return `${itemName(row.offer_item)} ×${row.offer_qty}`;
 return 'В подарок · без монет и опыта';
}
export function giveBlock(row,inventory={}){
 if(row.can_give===false)return row.reason||row.give_reason||'Сейчас нельзя отдать этот товар';
 const missing=Math.max(0,Number(row.qty)-(Number(inventory[row.item])||0));
 return missing?`Не хватает: ×${missing}`:'';
}
export function createFriendRequests(h){
 let tab='incoming',neighbors=[],identity=null,mounted=null,mountedSnapshot='';
 const seen=new Set();
 const view=()=>h.me()?.friend_requests||{};
 const rows=()=>view().own||[];
 const incoming=()=>(view().incoming||[]).filter(row=>row.status==='open');
 const count=()=>incoming().length+rows().filter(row=>row.status==='delivered').length;
 const btn=(label,fn,kind='secondary',disabled=false)=>h.button(label,fn,`qw-btn ${kind}`,disabled);
 function group(...buttons){const n=h.el('div',null,'qw-btn-stack');n.append(...buttons);return n;}
 function confirm(kind,row,label){
  h.modal(`${label}?`,kind==='request_cancel'?'Записка исчезнет с доски соседей. Дневной лимит просьб не восстановится.':'Товары из посылки вернутся соседу. Повторить закрытую просьбу нельзя.',[
   btn(label,async()=>{h.close();await h.command(kind,{request:row.id});},'danger')]);
 }
 function requestCard(row,type){
  const delivered=type==='own'&&row.status==='delivered',open=row.status==='open';
  const title=delivered?'Сосед привёз посылку':type==='incoming'?'Просьба соседа':'Моя просьба';
  const subtitle=type==='incoming'?(row.requester_name||'Сосед'):delivered?(row.giver_name||'Сосед'):'Ёж доставляет записки';
  const c=h.card(title,subtitle,'friends');c.classList.add('friend-request-card');c.dataset.requestId=row.id;
  c.append(h.el('p',`${delivered?'Привезли':'Нужно'}: ${h.itemName(row.item)} ×${row.qty}`),h.el('p',`Взамен: ${offerText(row,h.itemName)}`));
  const until=Number(delivered?row.settle_by:row.expires_at);
  if(until)h.note(`Осталось ${h.duration(Math.max(0,until-h.now()))}`,c);
  if(delivered&&(row.expiring||until-h.now()<=12*3600))h.note('Скоро срок принятия: Ёж вернёт посылку через 12 часов или раньше.',c);
  if(delivered){
   if(row.accept_reason)h.note(row.accept_reason,c);
   c.append(group(btn('Принять',()=>h.command('request_accept',{request:row.id}),'primary',row.can_accept===false),
    btn('Отказаться',()=>confirm('request_decline',row,'Отказаться'),'danger')));
  }else if(type==='incoming'&&open){
   const reason=giveBlock(row,h.me()?.inventory);if(reason)h.note(reason.startsWith('Не хватает:')?`${reason} · ${h.itemName(row.item)}`:reason,c);
   c.append(group(btn('Отдать',()=>h.command('request_give',{request:row.id}),reason?'secondary':'primary',!!reason),
    btn('Не сейчас',()=>h.command('request_hide',{request:row.id}),'text')));
  }else if(open){h.note('Ждём ответа · Ёж в пути',c);c.append(group(btn('Отменить',()=>confirm('request_cancel',row,'Отменить просьбу'),'danger')));}
  else h.note({delivered:'Ёж понёс посылку',settled:'Посылка принята · спасибо!',returned:'Ёж вернул товар соседу',expired:'Срок просьбы закончился',cancelled:'Просьба отменена'}[row.status]||'Просьба закрыта',c);
  return c;
 }
 function lane(p){
  const list=[...rows().filter(r=>r.status==='delivered').map(r=>[r,'own']),...incoming().map(r=>[r,'incoming'])];
  if(!list.length)return;
  const section=h.el('section',null,'friend-requests-lane');section.setAttribute('aria-label','От соседей');
  section.append(h.el('h3',`От соседей · ${list.length}`,'subheading'));
  for(const [r,type]of list)section.append(requestCard(r,type));p.append(section);
 }
 function segments(options,value,onChange){
  const n=h.el('div',null,'qw-btn-group');n.setAttribute('role','group');
  for(const [id,label]of options){const b=btn(label,()=>onChange(id),'secondary');b.setAttribute('aria-pressed',String(id===value));n.append(b);}return n;
 }
 function renderNeighbors(p){
  const box=h.el('section',null,'friend-requests-section');box.setAttribute('aria-label','Просьбы соседей');
  box.append(h.el('h3','Просьбы','subheading'),segments([['incoming','Мне пишут'],['own','Я прошу'],['deeds','Добрые дела']],tab,id=>{tab=id;h.rerender();}));
  const content=h.el('div',null,'friend-request-list');
  if(tab==='deeds'){
   h.note(`Добрых дел: ${view().good_deeds||0}. Помощь без монет и опыта.`,content);
   for(const row of view().thanks||[])h.note(typeof row==='string'?row:row.text||'Спасибо от соседа',content);
  }else{
   const list=tab==='own'?rows():incoming();
   if(!list.length)h.note(tab==='own'?'Ты пока ничего не просишь.':'Новых просьб нет.',content);
   for(const row of list)content.append(requestCard(row,tab));
  }
  box.append(content,group(btn('Попросить у соседей',()=>create(),'secondary')));p.append(box);mounted=box;mountedSnapshot=JSON.stringify(view());
 }
 function missing(p,needs){
  const ids=Object.keys(needs).filter(id=>(h.me()?.inventory?.[id]||0)<needs[id]&&!h.isBound(id));
  if(!ids.length)return;
  const actions=h.el('div',null,'fr-ask');actions.append(...ids.map(id=>btn(`Попросить: ${h.itemName(id)}`,()=>create(id,Math.min(20,needs[id]-(h.me()?.inventory?.[id]||0))),'text compact')));p.append(actions);
 }
 async function create(initialItem,initialQty=1){
  const me=h.me();if(!me)return;
  const owner=me.id;let list=view().neighbors||[];
  try{const r=await h.fetchNeighbors();if(h.me()?.id!==owner)return;list=r.neighbors||[];neighbors=list;}catch{if(h.me()?.id!==owner)return;}
  let kind='free',audience='all';
  const form=h.el('form',null,'friend-request-form'),[iw,item]=h.field('Нужный товар','select'),[qw,qty]=h.field('Количество','number',initialQty);
  const catalog=h.catalog()?.items||{},ids=Object.keys(catalog).filter(id=>!h.isBound(id)&&Number(catalog[id].price)>0);
  for(const id of ids){const option=h.el('option',h.itemName(id));option.value=id;item.append(option);}if(initialItem&&ids.includes(initialItem))item.value=initialItem;
  qty.min=1;qty.max=20;qty.step=1;qty.required=true;
  const toControls=h.el('div'),[tw,to]=h.field('Сосед','select');
  for(const n of list.filter(n=>!n.status||n.status==='accepted')){const option=h.el('option',`Сосед · ${n.id.slice(0,8)}`);option.value=n.id;to.append(option);}
  const offerControls=h.el('div'),[cw,coins]=h.field('Монеты взамен','number',1),[ow,offerItem]=h.field('Товар взамен','select'),[oqw,offerQty]=h.field('Количество взамен','number',1);
  coins.min=1;coins.step=1;offerQty.min=1;offerQty.step=1;
  for(const id of ids.filter(id=>Number(me.inventory?.[id])>0)){const option=h.el('option',`${h.itemName(id)} · ${me.inventory[id]}`);option.value=id;offerItem.append(option);}
  let kindSegments,audienceSegments;
  const summary=h.el('p',null,'note'),limits=h.el('p',null,'note');
  const send=btn('Отправить с Ежом',async()=>{if(!form.reportValidity())return;const data={item:item.value,qty:Number(qty.value),offer_kind:kind};
   if(audience==='one')data.to=to.value;
   if(kind==='coins')data.offer_coins=Number(coins.value);
   if(kind==='item'){data.offer_item=offerItem.value;data.offer_qty=Number(offerQty.value);}
   if(h.me()?.id===owner&&await h.command('request_create',data))h.close();
  },'primary');
  function update(){
   const value=Number(catalog[item.value]?.price||0)*Number(qty.value||0),low=Math.ceil(value*.5),high=Math.floor(value*1.5),v=view().limits||{};
   coins.min=low;coins.max=high;if(Number(coins.value)<low||Number(coins.value)>high)coins.value=low;
   offerQty.max=Number(me.inventory?.[offerItem.value])||0;
   summary.textContent=`Стоимость просьбы: ${value} монет. Обмен: от ${low} до ${high} монет по каталогу. Только заработанные монеты.`;
   limits.textContent=`Сегодня ещё ${v.count_left??3} просьбы из 3 · доступная стоимость ${v.value_left??'—'} из ${v.value_limit??'—'} монет`;
   send.disabled=!ids.length||(audience==='one'&&!to.value)||(kind==='item'&&!offerItem.value)||v.count_left===0||v.open_left===0||(Number.isFinite(v.value_left)&&value>v.value_left);
  }
  function drawAudience(){audienceSegments.replaceChildren(segments([['all','Всем соседям'],['one','Одному']],audience,id=>{audience=id;drawAudience();}));toControls.replaceChildren();if(audience==='one')toControls.append(tw);update();}
  function drawKind(){kindSegments.replaceChildren(segments([['free','Просто так'],['coins','Монеты'],['item','Товар']],kind,id=>{kind=id;drawKind();}));offerControls.replaceChildren();if(kind==='coins')offerControls.append(cw);if(kind==='item')offerControls.append(ow,oqw);update();}
  audienceSegments=h.el('div');kindSegments=h.el('div');
  form.append(iw,qw,h.el('h3','Кому','subheading'),audienceSegments,toControls,h.el('h3','Взамен','subheading'),kindSegments,offerControls,summary,limits);
  form.oninput=update;form.onchange=update;form.onsubmit=e=>{e.preventDefault();send.onclick();};drawAudience();drawKind();
  h.modal('Записка для Ежа',form,[send]);h.sheet();
 }
 function notify(){
  const me=h.me();if(!me)return;if(identity!==me.id){identity=me.id;seen.clear();}
  const delivered=rows().filter(row=>row.status==='delivered').map(row=>({id:`delivered:${row.id}`,text:`Сосед привёз ${h.itemName(row.item)} ×${row.qty}. Посылка ждёт на доске заказов.`}));
  for(const row of [...delivered,...(view().notifications||[])]){const key=row.id||row.key;if(!key||seen.has(key))continue;seen.add(key);if(row.text)h.toast(row.text);}
  h.badge?.(count());
  if(mounted?.isConnected&&mountedSnapshot!==JSON.stringify(view())){const old=mounted,host=h.el('div');renderNeighbors(host);old.replaceWith(host.firstElementChild);}
  while(seen.size>200)seen.delete(seen.values().next().value);
 }
 return {lane,renderNeighbors,missing,create,notify,count,setNeighbors:list=>{neighbors=list||[];}};
}
