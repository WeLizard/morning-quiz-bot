// Jack's gift is a server-owned projection. The local clock only expires an old
// snapshot; it never makes an inactive or already claimed gift available.
const acknowledged=new WeakSet();
export function horsemanDisplay(view,serverNow,pending=false){
 if(!view)return null;
 const stale=!Number.isFinite(view.next_change_at)||serverNow>=view.next_change_at;
 const canClaim=!stale&&view.active===true&&view.can_claim===true&&!view.claimed_today&&!pending;
 let message;
 if(stale)message='Проверяем, доступен ли подарок сейчас.';
 else if(acknowledged.has(view))message='Подарок получен. Склад обновится при восстановлении связи.';
 else if(view.claimed_today)message='Сегодня подарок уже получен.';
 else if(!view.active)message='Джек появляется с 17:00 до 05:00 по Москве.';
 else if(pending)message='Подтверждаем получение подарка…';
 else message='Бесплатный подарок ждёт тебя.';
 return {canClaim,stale,message,nextGiftAt:Number.isFinite(view.next_gift_at)?view.next_gift_at:null};
}

const giftTime=at=>new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'long',hour:'2-digit',minute:'2-digit',timeZone:'Europe/Moscow'}).format(new Date(at*1000));

export function renderHorsemanCard(parent,h){
 const view=h.getHorseman(),state=horsemanDisplay(view,h.now(),h.pending());
 if(!state)return;
 const c=h.card('Джек — призрачный всадник','Бесплатный подарок · раз в московский игровой день');
 c.classList.add('horseman-card');
 c.append(h.el('p',state.message,'horseman-status'));
 const open=h.button('Поговорить с Джеком',()=>openHorsemanDialog(h),'qw-btn secondary wide');
 open.dataset.qwCrumb='horseman-dialog';
 c.append(open);parent.append(c);
}

export function openHorsemanDialog(h){
 const view=h.getHorseman(),state=horsemanDisplay(view,h.now(),h.pending());
 if(!state)return;
 const body=h.el('div',null,'horseman-dialog');
 body.append(h.el('p','Я прихожу к деревне вечером. Возьми угощение для своей фермы.','horseman-dialogue'));
 const items=view.gift?.items||{};
 if(Object.keys(items).length){
  const list=h.el('ul',null,'horseman-gifts');
  for(const [id,qty] of Object.entries(items)){
   if(!Number.isFinite(qty)||qty<=0)continue;
   list.append(h.el('li',`${h.itemName(id)} ×${qty}`));
  }
  body.append(list);
 }
 body.append(h.el('p',state.message,'horseman-status'));
 if(state.nextGiftAt&&(!state.canClaim||view.claimed_today))body.append(h.el('p',`Следующий подарок: ${giftTime(state.nextGiftAt)} МСК.`,'horseman-next'));
 let claim=null;
 if(!view.claimed_today){
  claim=h.button('Получить подарок',async()=>{
   // A pending command is retried by the app with its original command_id.
   if(claim.disabled||!horsemanDisplay(h.getHorseman(),h.now(),h.pending())?.canClaim)return;
   claim.disabled=true;
   const ok=await h.command('claim_horseman_gift',{});
   if(ok){
    // sendPending can confirm the POST even if the following /me refresh fails.
    // In that case keep this exact projection closed until a new server view arrives.
    if(h.getHorseman()===view){view.claimed_today=true;view.can_claim=false;acknowledged.add(view);}
    h.closeDialog();openHorsemanDialog(h);
   }
   else claim.disabled=!horsemanDisplay(h.getHorseman(),h.now(),h.pending())?.canClaim;
  },'qw-btn primary',!state.canClaim);
 }
 h.modal('Джек — призрачный всадник',body,claim?[claim]:[]);
}
