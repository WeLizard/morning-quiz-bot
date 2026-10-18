const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
const code=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/invite.js'),'utf8').replaceAll('export async function ','async function ').replaceAll('export function ','function ');
const ID='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';
const SHARE_TOKEN='A'.repeat(43);
function env(search='',tg=null,navigator=undefined){const memory=new Map(), opened=[];const context={URL,URLSearchParams,navigator,innerWidth:800,innerHeight:600,location:{search,hash:'',href:'https://qw.example/app/farm'+search},history:{replaceState(a,b,url){context.location.search=url.search;}},window:{Telegram:tg?{WebApp:tg}:undefined,open(...args){opened.push(args)}},sessionStorage:{setItem(k,v){memory.set(k,v)},getItem(k){return memory.get(k)||null},removeItem(k){memory.delete(k)}},document:{documentElement:{style:{setProperty(){},removeProperty(){}}}},setTimeout};vm.createContext(context);vm.runInContext(code+'\nObject.assign(globalThis,{parseInvite,parseInviteHint,incomingInvite,clearInvite,openTelegram,shareData,mailtoUrl,shareLink})',context);return {context,memory,opened};}
test('UUID, web invitation and Main Mini App start payload parse to public id',()=>{const {context:c}=env();for(const value of [ID,ID.toUpperCase(),'farm_'+ID,'https://qw.example/app/farm?invite='+ID,'https://t.me/QuizzyBot?startapp=farm_'+ID])assert.equal(c.parseInvite(value),ID);});
test('One-use invitation token survives Telegram launch and cannot be used as a manual farm code',()=>{const {context:c,memory}=env('?startapp=farm_'+SHARE_TOKEN);assert.equal(c.incomingInvite(),SHARE_TOKEN);assert.equal(memory.get('qw-farm.incoming'),SHARE_TOKEN);assert.equal(c.parseInvite(SHARE_TOKEN),null);c.location.search='';assert.equal(c.incomingInvite(),SHARE_TOKEN);});
test('Recipient confirmation sends the one-use token once and clears it after success',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
 const fn=source.slice(source.indexOf('async function acceptSharedInvite('),source.indexOf('function renderSharing('));
 const calls=[],S={invite:SHARE_TOKEN};
 const context={S,API:'/api/farm/v1',request:async(path,options)=>{calls.push([path,options]);return {notice:'Теперь вы соседи!'}},
  toast:value=>calls.push(['toast',value]),clearInvite:()=>calls.push(['clear']),refresh:async()=>calls.push(['refresh']),renderPanel:()=>calls.push(['render'])};
 vm.createContext(context);vm.runInContext(fn+'\nObject.assign(globalThis,{acceptSharedInvite})',context);
 await context.acceptSharedInvite(SHARE_TOKEN);
 assert.equal(calls[0][0],'/api/farm/v1/invite/join');
 assert.equal(JSON.stringify(calls[0][1]),JSON.stringify({method:'POST',data:{token:SHARE_TOKEN}}));
 assert.equal(S.invite,null);assert.deepEqual(calls.slice(1).map(c=>c[0]),['toast','clear','refresh','render']);
});
test('Uncertain confirmation keeps the token for a safe retry',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
 const fn=source.slice(source.indexOf('async function acceptSharedInvite('),source.indexOf('function renderSharing('));
 const S={invite:SHARE_TOKEN},context={S,API:'/api/farm/v1',request:async()=>{throw new Error('offline')},
  toast:()=>assert.fail('no success message'),clearInvite:()=>assert.fail('token must survive'),refresh:()=>{},renderPanel:()=>{}};
 vm.createContext(context);vm.runInContext(fn+'\nObject.assign(globalThis,{acceptSharedInvite})',context);
 await assert.rejects(context.acceptSharedInvite(SHARE_TOKEN),/offline/);assert.equal(S.invite,SHARE_TOKEN);
});
test('Invalid, overlong and executable invitations are not navigated',()=>{const {context:c}=env();for(const v of ['',null,{},'javascript:alert(1)','ftp://site?invite='+ID,'x'.repeat(2500),'1'.repeat(36),'farm_<script>'])assert.equal(c.parseInvite(v),null);});
test('Invite survives unauthenticated page without changing auth; clear removes hint',()=>{const {context:c,memory}=env('?invite='+ID);assert.equal(c.incomingInvite(),ID);assert.equal(memory.get('qw-farm.incoming'),ID);c.location.search='';assert.equal(c.incomingInvite(),ID);c.clearInvite();assert.equal(c.incomingInvite(),null);});
test('Telegram public hint is not trusted as account identity',()=>{const {context:c,memory}=env('',{initDataUnsafe:{start_param:'farm_'+ID,user:{id:1}}});assert.equal(c.incomingInvite(),ID);assert.deepEqual([...memory.keys()],['qw-farm.incoming']);});
test('Sharing opens draft or chooser only in Telegram allowed origin',()=>{const {context:c,opened}=env();c.openTelegram('https://t.me/share/url?url=https%3A%2F%2Fqw.example');assert.equal(opened.length,1);for(const url of ['https://evil.test','javascript:alert(1)','https://t.me.evil.test/'])assert.throws(()=>c.openTelegram(url));});
test('SDK openTelegramLink is used inside Telegram; the bridge itself now lives in the shared shell',()=>{const calls=[];const tg={initData:'signed-data',openTelegramLink(v){calls.push(v)}};const {context:c,opened}=env('',tg);c.openTelegram('https://t.me/FriendlyUser?text=hello');assert.equal(opened.length,0);assert.deepEqual(calls,['https://t.me/FriendlyUser?text=hello']);});
test('Telegram mode kept by the shell without initData still uses SDK openTelegramLink, not window.open',()=>{const calls=[];const tg={initData:'',openTelegramLink(v){calls.push(v)}};const {context:c,opened}=env('',tg);c.window.QW={tg};c.openTelegram('https://t.me/share/url?url=x');assert.equal(opened.length,0);assert.deepEqual(calls,['https://t.me/share/url?url=x']);});
test('Clearing a shown invitation does not erase the consumed launch guard',()=>{const {context:c,memory}=env('?invite='+ID);assert.equal(c.incomingInvite(),ID);memory.set('qw-farm.launch-consumed',ID);c.clearInvite();assert.equal(memory.get('qw-farm.launch-consumed'),ID);assert.equal(c.incomingInvite(),null);});

test('Polling shows a new incoming neighbor without losing a draft or accepting it',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
 const neighbors=source.slice(source.indexOf('let neighborGeneration=0,'),source.indexOf('function renderJournal(p)'));
 const poll=source.slice(source.indexOf('let polling=false;'),source.indexOf('let readyTimer=null'));
 const server={a:{neighbors:[],public:[],blocked:[]},b:{neighbors:[],public:[],blocked:[]}};
 class Node{
  constructor(tag,text=null){this.tagName=tag.toUpperCase();this.textContent=text;this.children=[];this.value='';this.parentNode=null;}
  get childNodes(){return this.children;}
  append(...nodes){for(const node of nodes){node.parentNode=this;this.children.push(node);}}
  replaceChildren(...nodes){for(const node of this.children)node.parentNode=null;this.children=[];this.append(...nodes);}
  contains(node){return this===node||this.children.some(child=>child.contains(node));}
 }
 function client(id){
  const panel=new Node('div'),document={hidden:false,activeElement:null};
  const S={me:{id},farm:{id,is_owner:true},tab:'neighbors',busy:false,config:{demo:true}};
  const requests=[];let commands=[];
  const context={S,document,JSON,API:'/api/farm/v1',lastSessionRenewal:Date.now(),RENEW_AFTER:60000,navigator:{clipboard:{writeText:async()=>{}}},
   own:()=>S.farm?.is_owner,el:(tag,text)=>new Node(tag,text),button:(text,fn)=>{const n=new Node('button',text);n.onclick=fn;return n;},
   card:(title,subtitle)=>{const n=new Node('section');n.append(new Node('strong',title),new Node('small',subtitle));return n;},
   field:()=>{const input=new Node('input');const wrap=new Node('label');wrap.append(input);return [wrap,input];},
   heading:()=>{},renderSharing:()=>{},renderVisit:()=>{},note:(text,parent)=>parent.append(new Node('p',text)),
   safe:fn=>fn,toast:()=>{},modal:()=>{},parseInvite:value=>value,parseInviteHint:value=>value,visit:()=>{},
   command:async(kind,data,target)=>{commands.push([kind,target]);if(kind==='request_neighbor'){server[target].neighbors=[{id,name:'Player '+id,status:'incoming'}];server[id].neighbors=[{id:target,name:'Player '+target,status:'outgoing'}];}},
   request:async()=>{const hold=requests.shift();return hold?hold():structuredClone(server[id]);},
   refresh:async()=>true,connection:()=>{},'$':()=>({open:false})};
  vm.createContext(context);vm.runInContext(neighbors+'\n'+poll+'\nObject.assign(globalThis,{renderNeighbors,updateNeighbors,poll})',context);
  return {context,panel,document,requests,get commands(){return commands;}};
 }
 const a=client('a'),b=client('b');
 server.b.neighbors=[{id:'12345678-0000-4000-8000-000000000001',name:'Ферма howland',status:'outgoing'}];
 server.b.public=[{id:'87654321-0000-4000-8000-000000000002',name:'Ферма Howland'}];
 a.context.renderNeighbors(a.panel);b.context.renderNeighbors(b.panel);
 await new Promise(setImmediate);
 const bList=b.panel.children.at(-1),outgoing=bList.children[0],openFarm=bList.children.at(-1);
 assert.equal(outgoing.children[1].textContent,'Заявка отправлена · жди принятия владельцем');
 assert.equal(outgoing.children[2].textContent,'Первые 8 знаков ID: 1234-5678');
 assert.equal(openFarm.children[0].textContent,'Ферма Howland');
 assert.equal(openFarm.children[2].textContent,'Первые 8 знаков ID: 8765-4321');
 const form=a.panel.children.find(n=>n.tagName==='FORM');const draft=form.children[0].children[0];draft.value='unfinished invitation';a.document.activeElement=draft;
 const bForm=b.panel.children.find(n=>n.tagName==='FORM');bForm.children[0].children[0].value='a';await bForm.onsubmit({preventDefault(){}});
 await a.context.poll();
 assert.equal(form.parentNode,a.panel);assert.equal(draft.value,'unfinished invitation');assert.equal(a.document.activeElement,draft);
 assert.ok(a.panel.children.some(n=>n.children.some(c=>c.children.some(x=>x.textContent==='Просится в соседи'))));
 assert.deepEqual(a.commands,[]);
 const list=a.panel.children.at(-1);const rendered=list.children.length;
 await a.context.poll();assert.equal(list.children.length,rendered);
 a.document.activeElement=list.children[0];server.a.neighbors.push({id:'focused',name:'Focused',status:'incoming'});
 await a.context.poll();assert.equal(list.children.length,rendered);
 a.document.activeElement=draft;await a.context.poll();assert.equal(list.children.length,rendered+1);
 let releaseOlder;a.requests.push(()=>new Promise(resolve=>{releaseOlder=resolve}));const older=a.context.updateNeighbors();await new Promise(setImmediate);
 server.a.neighbors.push({id:'newest',name:'Newest',status:'incoming'});await a.context.updateNeighbors();
 const current=list.children.length;releaseOlder({neighbors:[],public:[],blocked:[]});await older;assert.equal(list.children.length,current);
 let release; a.requests.push(()=>new Promise(resolve=>{release=resolve}));const stale=a.context.updateNeighbors();await new Promise(setImmediate);
 a.context.S.me={id:'someone-else'};a.context.S.farm={id:'someone-else',is_owner:true};release({neighbors:[{id:'late',name:'Stale',status:'incoming'}],public:[],blocked:[]});await stale;
 assert.equal(list.children.length,current);assert.equal(draft.value,'unfinished invitation');
});

test('Actual refresh discards late account and visit responses before changing the view',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
 const refresh=source.slice(source.indexOf('let farmViewEpoch=0,'),source.indexOf('async function command('));
 const navigation=source.slice(source.indexOf('async function visit(id)'),source.indexOf('function renderVisit(p)'));
 const selectTab=source.slice(source.indexOf('function selectTab(id)'),source.indexOf('function renderSeeds()'));
 const poll=source.slice(source.indexOf('let polling=false;'),source.indexOf('let readyTimer=null'));
 const account=id=>({farm:{id,server_time:Date.now()/1000},speed:1});
 const S={me:account('a').farm,farm:account('a').farm,catalog:{},config:{demo:true},tab:'neighbors'};
 const calls=[],pending=[];
 const scene={set:farm=>calls.push(['scene',farm.id]),fit:()=>{}};
 const document={hidden:false,activeElement:null,body:{classList:{remove(){}}}};
 const context={S,API:'/api/farm/v1',Date,scene,document,lastSessionRenewal:Date.now(),RENEW_AFTER:60000,now:()=>Date.now()/1000,
  request:path=>new Promise(resolve=>pending.push({path,resolve})),updateHUD:()=>calls.push(['hud']),renderSeeds:()=>{},updateReady:()=>{},renderPanel:()=>calls.push(['panel']),renderRail:()=>{},showPanel:()=>{},queueNeighborGifts:()=>{},connection:()=>{},toast:()=>{},showLogin:()=>{calls.push(['login']);S.me=S.farm=null;},
  '$':()=>({open:false}),JSON};
 vm.createContext(context);vm.runInContext(refresh+'\n'+navigation+'\n'+selectTab+'\n'+poll+'\nObject.assign(globalThis,{refresh,visit,backHome,selectTab,poll})',context);
 const oldAccount=context.refresh({render:false});const first=pending.at(-1);assert.equal(first.path,'/api/farm/v1/me');
 context.S.me=account('b').farm;context.S.farm=context.S.me;
 // Resolve the original account response after the active account changed.
 first.resolve(account('a'));await oldAccount;
 assert.equal(S.me.id,'b');assert.equal(S.farm.id,'b');assert.deepEqual(calls,[]);
 const visiting=context.visit('guest');assert.equal(pending.at(-1).path,'/api/farm/v1/farms/guest');
 const visitRequest=pending.at(-1);visitRequest.resolve({farm:{id:'guest',is_owner:false}});await visiting;
 const oldVisit=context.refresh({render:false});pending.at(-1).resolve(account('b'));await new Promise(setImmediate);
 const farmRequest=pending.at(-1);assert.equal(farmRequest.path,'/api/farm/v1/farms/guest');
 context.backHome();const before=calls.length;farmRequest.resolve({farm:{id:'guest',is_owner:false}});
 assert.equal(await oldVisit,false);assert.equal(S.farm.id,'b');assert.equal(calls.length,before);
 const lateVisit=context.visit('guest');const lateVisitRequest=pending.at(-1);
 context.selectTab('inventory');lateVisitRequest.resolve({farm:{id:'guest',is_owner:false}});await lateVisit;
 assert.equal(S.tab,'inventory');assert.equal(S.farm.id,'b');
 const panelsBefore=calls.filter(([kind])=>kind==='panel').length;
 const polling=context.poll();const meRequest=pending.at(-1);
 const draft={tagName:'INPUT',value:'unfinished'};document.activeElement=draft;
 meRequest.resolve(account('b'));await polling;
 assert.equal(draft.value,'unfinished');assert.equal(document.activeElement,draft);
 const panels=calls.filter(([kind])=>kind==='panel').length;
 assert.equal(panels,panelsBefore);
 document.activeElement=null;const nextPoll=context.poll();pending.at(-1).resolve(account('b'));await nextPoll;
 assert.equal(calls.filter(([kind])=>kind==='panel').length,panels+1);
});

const INFO={code:ID,web_url:'https://qw.example/app/farm?invite='+ID,mini_app_url:'https://t.me/QuizzyBot/play?startapp=farm_'+ID};
test('Share data prefers the direct Mini App and falls back to standalone web',()=>{
 const {context:c}=env();const d=c.shareData(INFO);
 assert.equal(d.url,INFO.mini_app_url);assert.ok(d.title.length>0);assert.equal(c.parseInvite(d.url),ID);
 assert.equal(c.shareData({web_url:INFO.web_url}).url,INFO.web_url);
 assert.equal(c.shareData({code:ID,mini_app_url:INFO.mini_app_url}).url,INFO.mini_app_url);
 assert.equal(c.shareData({code:ID}).url,'');
});
test('navigator.share receives title, text and url; a cancelled sheet is not an error',async()=>{
 const calls=[];const {context:c}=env('',null,{share:async d=>{calls.push(d);}});
 assert.equal(await c.shareLink(INFO,async()=>assert.fail('no copy needed')),'shared');
 assert.deepEqual(Object.keys(calls[0]).sort(),['text','title','url']);assert.equal(calls[0].url,INFO.mini_app_url);
 const {context:c2}=env('',null,{share:async()=>{throw Object.assign(new Error('x'),{name:'AbortError'});}});
 assert.equal(await c2.shareLink(INFO,async()=>assert.fail('cancel must not copy')),'cancelled');
});
test('Without navigator.share (or when it fails) the link is copied; a failing clipboard reports failed',async()=>{
 const copied=[];const {context:c}=env('',null,undefined);
 assert.equal(await c.shareLink(INFO,async v=>{copied.push(v);}),'copied');assert.deepEqual(copied,[INFO.mini_app_url]);
 const {context:c2}=env('',null,{share:async()=>{throw new Error('not allowed');}});
 assert.equal(await c2.shareLink(INFO,async v=>{copied.push(v);}),'copied');assert.equal(copied.length,2);
 assert.equal(await c.shareLink(INFO,async()=>{throw new Error('denied');}),'failed');
});
test('mailto has no recipient, an encoded subject and body with the link; nothing is sent by the server',()=>{
 const {context:c}=env();const u=c.mailtoUrl(INFO);
 assert.ok(u.startsWith('mailto:?subject='));assert.ok(!/^mailto:[^?]/.test(u));
 const q=new URLSearchParams(u.slice('mailto:?'.length));
 assert.ok(q.get('subject').length>0);assert.ok(q.get('body').includes(INFO.web_url));assert.ok(q.get('body').includes(ID));
 assert.ok(!u.includes(' '));
});
test('Neighbors window: Telegram chat is primary in Telegram, system share elsewhere; reward and progress are shown',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
 const sharing=source.slice(source.indexOf('function renderInviteRewards'),source.indexOf('function renderViewSettings'));
 assert.match(sharing,/Поделиться ссылкой/);assert.match(sharing,/Отправить по почте/);assert.match(sharing,/Выбрать чат в Telegram/);
 assert.match(sharing,/actions\.append\(tgMode&&telegramButton\?telegramButton:shareButton\)/);
 assert.match(sharing,/tgMode&&hasLink\?'secondary wide':'primary wide'/);
 assert.match(sharing,/request\(API\+'\/invite'\)\.then\(info=>/);
 assert.match(sharing,/request\(API\+'\/invite\/share',\{method:'POST',data:telegram\?\{telegram:true\}:\{\}\}\)/);
 assert.match(sharing,/if\(info\.local_only\)\{/);
 assert.match(sharing,/Скопировать код фермы/);
 assert.match(sharing,/result==='cancelled'\)\{issued=null;try\{await request\(API\+'\/invite\/share\/revoke'/);
 assert.match(sharing,/Ссылка скопирована/);assert.match(sharing,/\$\{r\.reward\} монет/);assert.match(sharing,/\$\{r\.bonus\} монет/);
 assert.match(sharing,/i\.level/);assert.match(sharing,/\/invite\/accept/);
 assert.doesNotMatch(sharing,/mailto:[^?]/);   // no address is collected
});
test('Viewing neighbors does not issue a token; cancelling system share revokes its token',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
 const fn=source.slice(source.indexOf('function renderSharing('),source.indexOf('function quizzyLoginLink('));
 const calls=[],buttons=[],modals=[],token='A'.repeat(43);
 const element=(text='')=>({textContent:text,isConnected:true,append(){},replaceChildren(){}});
 const info={code:ID,farm_name:'Ферма',rewards:null,local_only:false};
 const context={API:'/api/farm/v1',S:{invite:null,me:{id:ID}},inTelegram:()=>false,QW:undefined,window:{},
  el:(tag,text)=>element(text),card:(text)=>element(text),note:()=>{},renderInviteRewards:()=>{},
  button:(label,action)=>{const b=element(label);b.action=action;buttons.push(b);return b;},
  field:()=>[element(),element()],copyText:()=>()=>{},safe:fn=>fn,
  shareLink:async()=> 'cancelled',mailtoUrl:()=> 'mailto:?body=hello',openTelegram:()=>assert.fail('async popup'),toast:()=>{},modal:(title,content)=>modals.push([title,content]),
  request:async(url,options)=>{calls.push([url,options]);if(url.endsWith('/invite/share'))return {token,mini_app_url:'https://t.me/QuizzyBot/play?startapp=farm_'+token,share_url:'https://t.me/share/url?url=hello'};return info;}};
 vm.createContext(context);vm.runInContext(fn+'\nObject.assign(globalThis,{renderSharing})',context);
 context.renderSharing(element());await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(calls.map(([url])=>url),['/api/farm/v1/invite']);
 await buttons.find(b=>b.textContent==='Поделиться приглашением').action();
 assert.deepEqual(calls.map(([url])=>url),['/api/farm/v1/invite','/api/farm/v1/invite/share','/api/farm/v1/invite/share/revoke']);
 assert.equal(calls[2][1].data.token,token);
 await buttons.find(b=>b.textContent==='Выбрать чат в Telegram').action();
 assert.equal(modals.at(-1)[1].href,'https://t.me/share/url?url=hello');
 await buttons.find(b=>b.textContent==='Отправить по почте').action();
 assert.equal(modals.at(-1)[1].href,'mailto:?body=hello');
});
test('Telegram: one prepared message opens the native chat picker; repeated taps reuse one token',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
 const fn=source.slice(source.indexOf('function renderSharing('),source.indexOf('function quizzyLoginLink('));
 const calls=[],buttons=[],shared=[],token='B'.repeat(43);
 const element=(text='')=>({textContent:text,isConnected:true,append(){},replaceChildren(){}});
 const info={code:ID,farm_name:'Ферма',rewards:null,local_only:false};
 const tg={shareMessage(id,cb){shared.push(id);cb(true);},isVersionAtLeast:v=>v==='8.0'};
 const context={API:'/api/farm/v1',S:{invite:null,me:{id:ID}},inTelegram:()=>true,QW:{tg},window:{},
  el:(tag,text)=>element(text),card:(text)=>element(text),note:()=>{},renderInviteRewards:()=>{},
  button:(label,action)=>{const b=element(label);b.action=action;buttons.push(b);return b;},
  field:()=>[element(),element()],copyText:()=>()=>{},safe:fn=>fn,
  shareLink:async()=> 'shared',mailtoUrl:()=> 'mailto:?body=hello',openTelegram:()=>assert.fail('fallback link'),toast:()=>{},modal:()=>assert.fail('fallback modal'),
  request:async(url,options)=>{calls.push([url,options]);if(url.endsWith('/invite/share'))return {token,mini_app_url:'https://t.me/QuizzyBot/play?startapp=farm_'+token,share_url:'https://t.me/share/url?url=hello',prepared_message_id:'prep-1'};return info;}};
 vm.createContext(context);vm.runInContext(fn+'\nObject.assign(globalThis,{renderSharing})',context);
 context.renderSharing(element());await new Promise(resolve=>setImmediate(resolve));
 const pick=buttons.find(b=>b.textContent==='Выбрать чат в Telegram');
 await pick.action();await pick.action();await pick.action();
 assert.deepEqual(shared,['prep-1','prep-1','prep-1']);
 const issues=calls.filter(([url])=>url.endsWith('/invite/share'));
 assert.equal(issues.length,1);assert.deepEqual(JSON.parse(JSON.stringify(issues[0][1].data)),{telegram:true});
});
test('Local-only invite shows the farm code without issuing a token',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
 const fn=source.slice(source.indexOf('function renderSharing('),source.indexOf('function quizzyLoginLink('));
 const calls=[],buttons=[];
 const element=(text='')=>({textContent:text,isConnected:true,append(){},replaceChildren(){}});
 const context={API:'/api/farm/v1',S:{invite:null,me:{id:ID}},
  el:(tag,text)=>element(text),card:(text)=>element(text),note:()=>{},renderInviteRewards:()=>{},
  button:(label)=>{buttons.push(label);return element(label);},copyText:()=>()=>{},
  request:async url=>{calls.push(url);return {code:ID,farm_name:'Ферма',rewards:null,local_only:true};}};
 vm.createContext(context);vm.runInContext(fn+'\nObject.assign(globalThis,{renderSharing})',context);
 context.renderSharing(element());await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(calls,['/api/farm/v1/invite']);
 assert.deepEqual(buttons,['Скопировать код фермы']);
});
test('Every channel feeds the same reward: the parsed invitation id is sent with /start',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
 assert.match(source,/API\+'\/start',\{method:'POST',\.\.\.\(S\.invite\?\{data:\{invite:S\.invite\}\}:\{\}\)\}/);
 assert.match(source,/S\.invite=incomingInvite\(\)/);
});
