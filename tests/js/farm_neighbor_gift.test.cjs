const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
const giftCode=source.slice(source.indexOf('// Each farm owns a bounded server ledger.'),source.indexOf('function safe(fn)'));
class Node{
 constructor(tag){this.tagName=tag;this.children=[];this.className='';this.open=false;this.attrs={};this.classList={add:n=>this.className=n,remove:()=>this.className=''};}
 append(...children){this.children.push(...children);}
 replaceChildren(...children){this.children=[...children];}
 setAttribute(name,value){this.attrs[name]=value;}
 removeAttribute(name){delete this.attrs[name];}
 addEventListener(name,fn){this['on'+name]=fn;}
 showModal(){this.open=true;this.showCount=(this.showCount||0)+1;}
 close(){this.open=false;this.onclose?.();}
 focus(){}
}
function harness({blockedStorage=false}={}){
 const dialog=new Node('dialog'),body=new Node('div'),storage=new Map(),listeners={};
 const S={me:{id:'farm-a'}};
 const document={hidden:false,addEventListener:(name,fn)=>listeners[name]=fn};
 const localStorage=blockedStorage?{getItem(){throw Error('denied')},setItem(){throw Error('denied')}}:
  {getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)};
 const context={S,document,localStorage,JSON,Map,Set,Number,fmt:n=>String(n),
  $:id=>id==='dialog'?dialog:body,
  el:(tag,text,cls)=>{const n=new Node(tag);n.textContent=text;n.className=cls||'';return n;},
  icon:()=>new Node('svg'),button:(label,fn)=>{const n=new Node('button');n.textContent=label;n.onclick=fn;return n;}};
 vm.createContext(context);
 vm.runInContext(giftCode+'\nObject.assign(globalThis,{queueNeighborGifts,showNeighborGifts})',context);
 const reward=(id,amount=100)=>({id,partner_id:id,partner_name:'Сосед '+id,amount,at:123});
 return {context,S,document,dialog,body,storage,listeners,reward};
}

test('paid ledger shows a gift once, including after a receipt retry and refresh',()=>{
 const h=harness(),farm={id:'farm-a',neighbor_bonus:{rewards:[h.reward('farm-b')]}};
 h.context.queueNeighborGifts(farm);
 assert.equal(h.dialog.showCount,1);
 assert.match(h.dialog.attrs['aria-label'],/100 монет/);
 assert.equal(h.body.children[0].children.at(-1).textContent,'Здорово!');
 h.dialog.close();h.context.queueNeighborGifts(farm);
 assert.equal(h.dialog.showCount,1);
 assert.deepEqual(JSON.parse(h.storage.get('qw-farm.neighbor-gifts.farm-a')),['farm-b']);
});

test('offline rewards aggregate and wait for another dialog and visible tab',()=>{
 const h=harness(),dialog=h.dialog;
 dialog.open=true;
 h.context.queueNeighborGifts({id:'farm-a',neighbor_bonus:{rewards:[h.reward('b',100),h.reward('c',200)]}});
 assert.equal(dialog.showCount,undefined);
 assert.equal(h.storage.size,0);
 h.document.hidden=true;dialog.close();assert.equal(dialog.showCount,undefined);
 h.document.hidden=false;h.listeners.visibilitychange();
 assert.equal(dialog.showCount,1);
 assert.match(dialog.attrs['aria-label'],/300 монет/);
 assert.match(h.body.children[0].children.at(-2).textContent,/Сосед b, Сосед c/);
 assert.deepEqual(JSON.parse(h.storage.get('qw-farm.neighbor-gifts.farm-a')),['b','c']);
});

test('account switch and denied storage do not consume another farm gift',()=>{
 const h=harness({blockedStorage:true});
 h.dialog.open=true;
 h.context.queueNeighborGifts({id:'farm-a',neighbor_bonus:{rewards:[h.reward('b')]}});
 h.S.me={id:'farm-other'};h.dialog.close();assert.equal(h.dialog.showCount,undefined);
 h.S.me={id:'farm-a'};h.context.showNeighborGifts();assert.equal(h.dialog.showCount,1);
 h.dialog.close();h.context.queueNeighborGifts({id:'farm-a',neighbor_bonus:{rewards:[h.reward('b')]}});
 assert.equal(h.dialog.showCount,1);
});

test('old totals without records and unpaid acceptance have no gift to show',()=>{
 const h=harness();
 h.context.queueNeighborGifts({id:'farm-a',neighbor_bonus:{total:2,earned:200}});
 h.context.queueNeighborGifts({id:'farm-a'});
 assert.equal(h.dialog.showCount,undefined);
});

test('command receipt suppresses the ordinary toast only when payment is confirmed',async()=>{
 const snippet=source.slice(source.indexOf('async function sendPending()'),source.indexOf('// After a real 429'));
 const notices=[],responses=[{notice:'Соседство принято. Награда: +100 монет.',neighbor_reward_paid:true},
  {notice:'Соседство принято. Лимит наград исчерпан.'}];
 const S={me:{id:'a'},pending:{actor:'a',kind:'accept_neighbor',data:{},target:'b',command_id:'one'},busy:false};
 const context={S,clearTimeout(){},pendingRetryTimer:null,rateRecoveryAttempt:0,
  connection(){},document:{body:{classList:{add(){},remove(){}}}},API:'/api/farm/v1',
  request:async()=>responses.shift(),rememberMachineCommand(){},savePending(){},toast:text=>notices.push(text),localizeWagerNotice:text=>text,gf:(m,f,n)=>n,
  refresh:async()=>true,updateRepeat(){},scheduleRateRecovery(){},schedulePendingRetry(){}};
 vm.createContext(context);vm.runInContext(snippet+'\nthis.sendPending=sendPending',context);
 assert.equal(await context.sendPending(),true);
 assert.deepEqual(notices,[]);
 S.pending={actor:'a',kind:'accept_neighbor',data:{},target:'c',command_id:'two'};
 assert.equal(await context.sendPending(),true);
 assert.deepEqual(notices,['Соседство принято. Лимит наград исчерпан.']);
});
