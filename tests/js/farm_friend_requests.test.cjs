const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const vm=require('node:vm');
const load=()=>import(pathToFileURL(path.join(__dirname,'../../qw_farm/static/friend_requests.js')).href);

class Node{
 constructor(tag,text,cls){this.tag=tag;this.textContent=text||'';this.className=cls||'';this.children=[];this.dataset={};this.attrs={};this.value='';this.classList={add:c=>this.className+=' '+c};}
 append(...nodes){this.children.push(...nodes);if(this.tag==='select'&&!this.value)this.value=nodes[0]?.value||'';}
 replaceChildren(...nodes){this.children=nodes;}
 setAttribute(k,v){this.attrs[k]=v;}
 addEventListener(k,v){this['on'+k]=v;}
 reportValidity(){return true;}
}
const walk=(n)=>[n,...n.children.flatMap(walk)];
const buttons=n=>walk(n).filter(n=>n.tag==='button');
function harness(over={}){
 const calls=[],notices=[],dialogs=[],me={id:'farm-a',inventory:{wheat:8,egg:4},friend_requests:{own:[],incoming:[],limits:{count_left:2,value_left:180,value_limit:200}},...over};
 const el=(...args)=>new Node(...args);
 const h={me:()=>me,catalog:()=>({items:{wheat:{price:10},egg:{price:20},bound_seed:{price:20}}}),el,
  button:(text,fn,cls,disabled)=>{const b=el('button',text,cls);b.onclick=fn;b.disabled=disabled;return b;},
  card:(title,subtitle)=>{const c=el('section',title,'card');c.subtitle=subtitle;return c;},
  field:(label,type='text',value='')=>{const w=el('label',label),i=el(type==='select'?'select':'input');i.attrs['aria-label']=label;i.value=value;w.append(i);return[w,i];},
  note:(text,p)=>p.append(el('p',text,'note')),itemName:id=>id,now:()=>100,duration:n=>`${n} с`,isBound:id=>id==='bound_seed',
  command:async(kind,data)=>{calls.push([kind,data]);return true;},modal:(...args)=>dialogs.push(args),close(){h.closed=true;},sheet(){h.sheetOpened=true;},
  rerender(){h.rerenders=(h.rerenders||0)+1;},toast:t=>notices.push(t),fetchNeighbors:async()=>({neighbors:[{id:'farm-b',name:'Сосед',status:'accepted'}]})};
 return{h,me,calls,notices,dialogs};
}
const row=(over={})=>({id:'request-a',item:'wheat',qty:3,status:'open',offer_kind:'free',expires_at:1000,...over});

test('separate lane renders delivery and incoming cards without using resident slots',async()=>{
 const {createFriendRequests}=await load(),{h,me,calls}=harness();
 me.friend_requests.own=[row({status:'delivered',settle_by:900})];me.friend_requests.incoming=[...me.friend_requests.own,row({id:'request-b',offer_kind:'item',offer_item:'egg',offer_qty:2})];
 const parent=new Node('div'),ui=createFriendRequests(h);ui.lane(parent);
 assert.equal(parent.children[0].attrs['aria-label'],'От соседей');
 assert.equal(walk(parent).filter(n=>n.className.includes('friend-request-card')).length,2);
 await buttons(parent).find(b=>b.textContent==='Принять').onclick();
 await buttons(parent).find(b=>b.textContent==='Отдать').onclick();
 assert.deepEqual(calls,[['request_accept',{request:'request-a'}],['request_give',{request:'request-b'}]]);
 assert.equal(me.orders,undefined);
});
test('giving is disabled with the stock or server reason; hide is a server command',async()=>{
 const {createFriendRequests}=await load(),{h,me,calls}=harness();me.friend_requests.incoming=[row({qty:10}),row({id:'request-c',can_give:false,reason:'Соседству ещё нет 24 часов'})];
 const p=new Node('div');createFriendRequests(h).lane(p);
 const give=buttons(p).filter(b=>b.textContent==='Отдать');assert.ok(give.every(b=>b.disabled));assert.ok(give.every(b=>!b.className.includes('primary')));
 assert.ok(walk(p).some(n=>n.textContent==='Не хватает: ×2 · wheat'));
 assert.ok(walk(p).some(n=>n.textContent==='Соседству ещё нет 24 часов'));
 await buttons(p).find(b=>b.textContent==='Не сейчас').onclick();assert.deepEqual(calls,[['request_hide',{request:'request-a'}]]);
});
test('decline and cancel require confirmation and never send client exchange terms',async()=>{
 const {createFriendRequests}=await load(),{h,me,calls,dialogs}=harness();me.friend_requests.own=[row({status:'delivered'})];
 const ui=createFriendRequests(h),p=new Node('div');ui.lane(p);buttons(p).find(b=>b.textContent==='Отказаться').onclick();assert.equal(calls.length,0);
 await dialogs[0][2][0].onclick();assert.deepEqual(calls,[['request_decline',{request:'request-a'}]]);
 me.friend_requests.own=[row()];const own=new Node('div');ui.renderNeighbors(own);buttons(own).find(b=>b.textContent==='Я прошу').onclick();
 const refreshed=new Node('div');ui.renderNeighbors(refreshed);buttons(refreshed).find(b=>b.textContent==='Отменить').onclick();assert.equal(calls.length,1);
 await dialogs.at(-1)[2][0].onclick();assert.deepEqual(calls.at(-1),['request_cancel',{request:'request-a'}]);
});
test('creation sheet sends all three offer kinds, chosen audience and missing quantity',async()=>{
 const {createFriendRequests}=await load(),{h,calls,dialogs}=harness();const ui=createFriendRequests(h);await ui.create('wheat',3);
 const [,form,[send]]=dialogs.at(-1);assert.equal(h.sheetOpened,true);
 const inputs=walk(form).filter(n=>n.tag==='select'||n.tag==='input');
 assert.equal(inputs.find(n=>n.attrs['aria-label']==='Количество').value,3);
 assert.ok(!inputs.find(n=>n.attrs['aria-label']==='Нужный товар').children.some(n=>n.value==='bound_seed'));
 await send.onclick();assert.deepEqual(calls.at(-1),['request_create',{item:'wheat',qty:3,offer_kind:'free'}]);
 buttons(form).find(b=>b.textContent==='Монеты').onclick();buttons(form).find(b=>b.textContent==='Одному').onclick();await send.onclick();
 assert.deepEqual(calls.at(-1),['request_create',{item:'wheat',qty:3,offer_kind:'coins',to:'farm-b',offer_coins:15}]);
 buttons(form).find(b=>b.textContent==='Товар').onclick();
 walk(form).find(n=>n.attrs['aria-label']==='Товар взамен').value='egg';walk(form).find(n=>n.attrs['aria-label']==='Количество взамен').value=2;
 await send.onclick();assert.deepEqual(calls.at(-1),['request_create',{item:'wheat',qty:3,offer_kind:'item',to:'farm-b',offer_item:'egg',offer_qty:2}]);
 assert.ok(walk(form).some(n=>n.textContent.includes('180 из 200')));
});
test('missing buttons prefill shortfall, ignore bound goods, and creation honors daily limit',async()=>{
 const {createFriendRequests}=await load(),{h,me,dialogs}=harness(),ui=createFriendRequests(h),p=new Node('div');ui.missing(p,{wheat:10,egg:2,bound_seed:5});
 assert.equal(buttons(p).length,1);await buttons(p)[0].onclick();assert.equal(walk(dialogs.at(-1)[1]).find(n=>n.attrs['aria-label']==='Количество').value,2);
 me.friend_requests.limits.count_left=0;await ui.create('wheat');assert.equal(dialogs.at(-1)[2][0].disabled,true);
});
test('notifications dedupe by identity and free thanks never promise coins or XP',async()=>{
 const {createFriendRequests,offerText}=await load(),{h,me,notices}=harness();me.friend_requests.notifications=[{id:'delivery',text:'Посылка пришла'}];
 const ui=createFriendRequests(h);ui.notify();ui.notify();assert.deepEqual(notices,['Посылка пришла']);me.id='farm-b';ui.notify();assert.equal(notices.length,2);
 assert.match(offerText(row(),h.itemName),/без монет и опыта/);
});
test('app hooks the lane, missing goods, settings, notifications and existing dialog navigation',()=>{
 const app=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
 for(const hook of ['FRIEND_REQUESTS.lane(p)','FRIEND_REQUESTS.missing(c,o.needs)','FRIEND_REQUESTS.renderNeighbors(p)','FRIEND_REQUESTS.notify()','allow_requests'])assert.ok(app.includes(hook),hook);
 assert.match(app,/navPush\('dialog'/);
 assert.ok(!app.includes('\r\n'),'app.js stays LF');
});
test('notification preference lives in both Profile settings paths and persists through farm receipts',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../../web/mini_client/app.js'),'utf8');
 assert.ok(source.includes("guestMain.append(box, appearanceCard('guest'), farmRequestNotificationsCard('guest'))"));
 assert.ok(source.includes("content.append(appearanceCard('telegram'), farmRequestNotificationsCard('telegram'))"));
 const code=source.slice(source.indexOf('    function farmRequestNotificationsCard('),source.indexOf('    // «Профиль → Настройки»: only the account'));
 for(const identity of ['guest','telegram']){
  const calls=[],farm={id:'farm-a',name:'Ферма',settings:{visibility:'friends',allow_help:false,allow_gifts:true,allow_trade:false,allow_pranks:false,allow_requests:true,notify_requests:false}};
  const run=async(url,method,options)=>{calls.push([url,method,options]);return{farm};};
  const ctx={generation:3,state:{guest:{account_id:'a'},me:{account_id:'a'}},el:(...args)=>new Node(...args),
   guestRequest:run,request:(url,options)=>run(url,options.method,options),crypto:{randomUUID:()=>'00000000-0000-4000-8000-000000000001'}};
  vm.createContext(ctx);vm.runInContext(code+'\nthis.make=farmRequestNotificationsCard;',ctx);
  const card=ctx.make(identity);await Promise.resolve();await Promise.resolve();
  const input=walk(card).find(n=>n.tag==='input');assert.equal(input.checked,false);assert.equal(input.disabled,false);
  input.checked=true;await input.onchange();const last=calls.at(-1);assert.equal(last[0],`/api/farm/v1/commands?identity=${identity}`);
  const body=JSON.parse(last[2].body);assert.equal(body.kind,'settings');assert.equal(body.data.notify_requests,true);assert.equal(body.data.allow_help,false);assert.equal(body.actor,'farm-a');
  assert.equal(last[2].headers['X-QW-Farm'],'1');assert.ok(!calls.some(([url])=>url.includes('/start')));
 }
});
