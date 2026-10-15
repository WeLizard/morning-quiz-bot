const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
const code=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/telegram.js'),'utf8').replaceAll('export async function ','async function ').replaceAll('export function ','function ');
const ID='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';
function env(search='',tg=null,navigator=undefined){const memory=new Map(), opened=[];const context={URL,URLSearchParams,navigator,location:{search,hash:'',href:'https://qw.example/app/farm'+search},history:{replaceState(a,b,url){context.location.search=url.search;}},window:{Telegram:tg?{WebApp:tg}:undefined,open(...args){opened.push(args)}},sessionStorage:{setItem(k,v){memory.set(k,v)},getItem(k){return memory.get(k)||null},removeItem(k){memory.delete(k)}},document:{documentElement:{style:{setProperty(){}}}},setTimeout};vm.createContext(context);vm.runInContext(code+'\nObject.assign(globalThis,{parseInvite,incomingInvite,clearInvite,openTelegram,bootTelegram,shareData,mailtoUrl,shareLink,inTelegram})',context);return {context,memory,opened};}
test('UUID, web invitation and Main Mini App start payload parse to public id',()=>{const {context:c}=env();for(const value of [ID,ID.toUpperCase(),'farm_'+ID,'https://qw.example/app/farm?invite='+ID,'https://t.me/QuizzyBot?startapp=farm_'+ID])assert.equal(c.parseInvite(value),ID);});
test('Invalid, overlong and executable invitations are not navigated',()=>{const {context:c}=env();for(const v of ['',null,{},'javascript:alert(1)','ftp://site?invite='+ID,'x'.repeat(2500),'1'.repeat(36),'farm_<script>'])assert.equal(c.parseInvite(v),null);});
test('Invite survives unauthenticated page without changing auth; clear removes hint',()=>{const {context:c,memory}=env('?invite='+ID);assert.equal(c.incomingInvite(),ID);assert.equal(memory.get('qw-farm.incoming'),ID);c.location.search='';assert.equal(c.incomingInvite(),ID);c.clearInvite();assert.equal(c.incomingInvite(),null);});
test('Telegram public hint is not trusted as account identity',()=>{const {context:c,memory}=env('',{initDataUnsafe:{start_param:'farm_'+ID,user:{id:1}}});assert.equal(c.incomingInvite(),ID);assert.deepEqual([...memory.keys()],['qw-farm.incoming']);});
test('Sharing opens draft or chooser only in Telegram allowed origin',()=>{const {context:c,opened}=env();c.openTelegram('https://t.me/share/url?url=https%3A%2F%2Fqw.example');assert.equal(opened.length,1);for(const url of ['https://evil.test','javascript:alert(1)','https://t.me.evil.test/'])assert.throws(()=>c.openTelegram(url));});
test('SDK openTelegramLink and safe-area/fullscreen event adapters are feature gated',async()=>{const calls=[];const tg={initData:'signed-data',safeAreaInset:{top:20},contentSafeAreaInset:{top:50},ready(){calls.push('ready')},expand(){calls.push('expand')},BackButton:{show(){calls.push('show')},onClick(f){calls.push('back')}},onEvent(n,cb){calls.push(n)},openTelegramLink(v){calls.push(v)}};const {context:c,opened}=env('',tg);await c.bootTelegram(()=>calls.push('resize'),()=>{});c.openTelegram('https://t.me/FriendlyUser?text=hello');assert.equal(opened.length,0);assert.ok(calls.includes('safeAreaChanged'));assert.ok(calls.includes('fullscreenChanged'));assert.ok(calls.includes('https://t.me/FriendlyUser?text=hello'));});
test('Delayed Telegram SDK load still initializes the Mini App bridge',async()=>{
 const {context:c}=env();let script;const calls=[],insets=[];
 const tg={safeAreaInset:{top:20},contentSafeAreaInset:{bottom:30},ready(){calls.push('ready')},expand(){calls.push('expand')},
  BackButton:{show(){calls.push('show')},onClick(){calls.push('back')}},onEvent(name){calls.push(name)}};
 c.document.createElement=()=>script={};c.document.head={append(node){assert.equal(node.src,'https://telegram.org/js/telegram-web-app.js');}};
 c.document.documentElement.style.setProperty=(name,value)=>insets.push([name,value]);
 const boot=c.bootTelegram(()=>calls.push('resize'),()=>{},true);
 await Promise.resolve();assert.deepEqual(calls,[]);assert.equal(typeof script.onload,'function');
 c.window.Telegram={WebApp:tg};script.onload();
 assert.equal(await boot,tg);assert.ok(calls.includes('ready'));assert.ok(calls.includes('expand'));assert.ok(calls.includes('show'));
 assert.ok(calls.includes('safeAreaChanged'));assert.ok(calls.includes('resize'));
 assert.ok(insets.some(([name,value])=>name==='--tg-safe-top'&&value==='20px'));
 assert.ok(insets.some(([name,value])=>name==='--tg-content-bottom'&&value==='30px'));
});
test('Clearing a shown invitation does not erase the consumed launch guard',()=>{const {context:c,memory}=env('?invite='+ID);assert.equal(c.incomingInvite(),ID);memory.set('qw-farm.launch-consumed',ID);c.clearInvite();assert.equal(memory.get('qw-farm.launch-consumed'),ID);assert.equal(c.incomingInvite(),null);});

test('Polling shows a new incoming neighbor without losing a draft or accepting it',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
 const neighbors=source.slice(source.indexOf('let neighborGeneration=0,'),source.indexOf('function renderJournal(p)'));
 const poll=source.slice(source.indexOf('let polling=false;'),source.indexOf('setInterval(updateReady,1000)'));
 const server={a:{neighbors:[],public:[],blocked:[]},b:{neighbors:[],public:[],blocked:[]}};
 class Node{
  constructor(tag,text=null){this.tagName=tag.toUpperCase();this.textContent=text;this.children=[];this.value='';this.parentNode=null;}
  append(...nodes){for(const node of nodes){node.parentNode=this;this.children.push(node);}}
  replaceChildren(...nodes){for(const node of this.children)node.parentNode=null;this.children=[];this.append(...nodes);}
  contains(node){return this===node||this.children.some(child=>child.contains(node));}
 }
 function client(id){
  const panel=new Node('div'),document={hidden:false,activeElement:null};
  const S={me:{id},farm:{id,is_owner:true},tab:'neighbors',busy:false,config:{demo:true}};
  const requests=[];let commands=[];
  const context={S,document,JSON,API:'/api/farm/v1',navigator:{clipboard:{writeText:async()=>{}}},
   own:()=>S.farm?.is_owner,el:(tag,text)=>new Node(tag,text),button:(text,fn)=>{const n=new Node('button',text);n.onclick=fn;return n;},
   card:(title,subtitle)=>{const n=new Node('section');n.append(new Node('strong',title),new Node('small',subtitle));return n;},
   field:()=>{const input=new Node('input');const wrap=new Node('label');wrap.append(input);return [wrap,input];},
   heading:()=>{},renderSharing:()=>{},renderVisit:()=>{},note:(text,parent)=>parent.append(new Node('p',text)),
   safe:fn=>fn,toast:()=>{},modal:()=>{},parseInvite:value=>value,visit:()=>{},
   command:async(kind,data,target)=>{commands.push([kind,target]);if(kind==='request_neighbor'){server[target].neighbors=[{id,name:'Player '+id,status:'incoming'}];server[id].neighbors=[{id:target,name:'Player '+target,status:'outgoing'}];}},
   request:async()=>{const hold=requests.shift();return hold?hold():structuredClone(server[id]);},
   refresh:async()=>true,connection:()=>{},'$':()=>({open:false})};
  vm.createContext(context);vm.runInContext(neighbors+'\n'+poll+'\nObject.assign(globalThis,{renderNeighbors,updateNeighbors,poll})',context);
  return {context,panel,document,requests,get commands(){return commands;}};
 }
 const a=client('a'),b=client('b');a.context.renderNeighbors(a.panel);b.context.renderNeighbors(b.panel);
 await new Promise(setImmediate);
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
 const poll=source.slice(source.indexOf('let polling=false;'),source.indexOf('setInterval(updateReady,1000)'));
 const account=id=>({farm:{id,server_time:Date.now()/1000},speed:1});
 const S={me:account('a').farm,farm:account('a').farm,catalog:{},config:{demo:true},tab:'neighbors'};
 const calls=[],pending=[];
 const scene={set:farm=>calls.push(['scene',farm.id]),fit:()=>{}};
 const document={hidden:false,activeElement:null,body:{classList:{remove(){}}}};
 const context={S,API:'/api/farm/v1',Date,scene,document,
  request:path=>new Promise(resolve=>pending.push({path,resolve})),updateHUD:()=>calls.push(['hud']),renderSeeds:()=>{},updateReady:()=>{},renderPanel:()=>calls.push(['panel']),renderRail:()=>{},showPanel:()=>{},connection:()=>{},toast:()=>{},showLogin:()=>{calls.push(['login']);S.me=S.farm=null;},
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
test('Telegram mode is detected from signed init data only',()=>{
 assert.equal(env('',{initData:'signed'}).context.inTelegram(),true);
 assert.equal(env('',{initData:''}).context.inTelegram(),false);assert.equal(env().context.inTelegram(),false);
});

test('Neighbors window: Telegram chat is primary in Telegram, system share elsewhere; reward and progress are shown',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
 const sharing=source.slice(source.indexOf('function renderInviteRewards'),source.indexOf('function renderViewSettings'));
 assert.match(sharing,/Поделиться ссылкой/);assert.match(sharing,/Отправить по почте/);assert.match(sharing,/Выбрать чат в Telegram/);
 assert.match(sharing,/actions\.append\(tgMode&&telegramButton\?telegramButton:shareButton\)/);
 assert.match(sharing,/tgMode&&info\.share_url\?'secondary wide':'primary wide'/);
 assert.match(sharing,/Ссылка скопирована/);assert.match(sharing,/\$\{r\.reward\} монет/);assert.match(sharing,/\$\{r\.bonus\} монет/);
 assert.match(sharing,/i\.level/);assert.match(sharing,/\/invite\/accept/);
 assert.doesNotMatch(sharing,/mailto:[^?]/);   // no address is collected
});
test('Every channel feeds the same reward: the parsed invitation id is sent with /start',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
 assert.match(source,/API\+'\/start',\{method:'POST',\.\.\.\(S\.invite\?\{data:\{invite:S\.invite\}\}:\{\}\)\}/);
 assert.match(source,/S\.invite=incomingInvite\(\)/);
});
