const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
function client(){
 let clock=100000,nextTimer=0;
 const timers=new Set(),callbacks=new Map(),memory=new Map(),calls=[],responses=[],messages=[];
 const nodes={connection:{},retry:{}},classes=new Set();
 const S={me:{id:'actor'},farm:null,busy:false,pending:null};
 const c={S,API:'/api/farm/v1',Date:{now:()=>clock},AbortController,TypeError,JSON,
  crypto:{randomUUID:()=> 'stable-command-id'},url:p=>p,
  fetch:async(p,options)=>{calls.push({p,options});const r=responses.shift();if(r instanceof Error)throw r;return r||response(200);},
  setTimeout:(fn,ms)=>{timers.add(++nextTimer);callbacks.set(nextTimer,{fn,ms});return nextTimer;},clearTimeout:id=>{timers.delete(id);callbacks.delete(id);},
  sessionStorage:{setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)},
  document:{querySelector:()=>({style:{}}),body:{classList:{add:v=>classes.add(v),remove:v=>classes.delete(v)}}},
  '$':id=>nodes[id],toast:t=>messages.push(t),refresh:async()=>true,showLogin:()=>{}};
 vm.createContext(c);
 const feedback=source.slice(source.indexOf('const rateUntil='),source.indexOf('function field('));
 const request=source.slice(source.indexOf('async function request('),source.indexOf('let farmViewEpoch=0,'));
 const commands=source.slice(source.indexOf('async function command('),source.indexOf('async function enter('));
 const readiness=source.slice(source.indexOf("let readiness='';"),source.indexOf('function clickObject('));
 const retry=source.slice(source.indexOf('async function retryConnection('),source.indexOf("document.addEventListener('keydown'"));
 vm.runInContext(feedback+'\n'+request+'\n'+commands+'\n'+readiness+'\n'+retry+'\nObject.assign(globalThis,{request,command,sendPending,connection,retryAfter,rateSeconds,updateRateFeedback,updateReady,retryConnection,scheduleRateRecovery})',c);
 const fire=async()=>{const ids=[...callbacks.keys()];for(const id of ids){const {fn}=callbacks.get(id);timers.delete(id);callbacks.delete(id);await fn();}};
 return {c,S,nodes,timers,callbacks,fire,memory,calls,responses,messages,classes,advance:ms=>{clock+=ms;c.updateReady();}};
}
function response(status,header=null,value={notice:'OK'}){
 return {status,ok:status<400,headers:{get:()=>header},json:async()=>value};
}
test('Retry-After bounds integer seconds and malformed/missing/date values',()=>{
 const {c}=client();
 for(const [value,expected] of [['1',1],['60',60],['0',1],['999999',60],[' 12 ',12],['9999999999999',5],['-1',5],['0.5',5],['Infinity',5],['Wed, 21 Oct 2015 07:28:00 GMT',5],['',5],[null,5],[undefined,5]])assert.equal(c.retryAfter(value),expected,value);
});
test('Write 429 keeps receipt; countdown guards clicks/retry, expiry permits same ID',async()=>{
 const a=client();a.responses.push(response(429,'3'));
 assert.equal(await a.c.command('plant',{crop:'wheat'}),false);
 const pending=a.S.pending;assert.equal(pending.command_id,'stable-command-id');
 assert.equal(JSON.parse(a.memory.get('qw-farm.pending.actor')).command_id,pending.command_id);
 assert.match(a.nodes.connection.textContent,/Действия доступны через 3 с/);assert.equal(a.nodes.retry.disabled,true);
 assert.equal(await a.c.command('harvest'),false);assert.equal(await a.c.sendPending(),false);
 assert.equal(a.calls.length,1);assert.equal(a.S.pending,pending);assert.equal(a.S.busy,false);assert.equal(a.timers.size,1,'one recovery timer, no pile-up');assert.equal(a.classes.size,0);
 a.advance(1001);assert.match(a.nodes.connection.textContent,/через 2 с/);
 a.advance(1999);assert.equal(a.nodes.retry.disabled,false);assert.equal(a.nodes.connection.textContent,'Нужно подтвердить результат');
 assert.equal(a.calls.length,1,'the clock alone does not replay; the recovery timer does');
 assert.equal([...a.callbacks.values()][0].ms,3250,'waits Retry-After plus a margin');
 await a.fire();assert.equal(a.calls.length,2);
 assert.deepEqual(JSON.parse(a.calls[0].options.body),JSON.parse(a.calls[1].options.body));
 assert.equal(a.S.pending,null);assert.equal(a.memory.size,0);assert.equal(a.timers.size,0);
});
test('Read and write buckets remain independent; polling/focus reads cannot bypass wait',async()=>{
 const a=client();a.responses.push(response(429,'2'));
 await assert.rejects(a.c.request('/api/farm/v1/me'),e=>e.status===429&&e.rateBucket==='read');
 assert.match(a.nodes.connection.textContent,/Обновление доступно через 2 с/);
 assert.equal(a.nodes.retry.disabled,true);
 await assert.rejects(a.c.request('/api/farm/v1/neighbors'),e=>e.status===429);
 assert.equal(a.calls.length,1);assert.equal(await a.c.command('plant'),true);
 assert.equal(a.calls.length,2);assert.equal(a.S.pending,null);
 await a.c.request('/api/guest/resume',{method:'POST'});assert.equal(a.calls.length,3);
 a.advance(2000);await a.c.request('/api/farm/v1/me');assert.equal(a.calls.length,4);assert.equal(a.timers.size,0);
});
test('Non-JSON 429 still preserves unknown command and applies bounded fallback',async()=>{
 const a=client();a.responses.push(new TypeError('lost response'));
 assert.equal(await a.c.command('plant'),false);const pending=a.S.pending;
 a.responses.push({...response(429),json:async()=>{throw new SyntaxError('HTML')}});
 assert.equal(await a.c.sendPending(),false);assert.equal(a.S.pending,pending);
 assert.equal(a.c.rateSeconds('write'),5);assert.equal(a.timers.size,1,'recovery timer only (the old retry timer was replaced)');
 a.advance(5000);assert.equal(await a.c.sendPending(),true);
 const ids=a.calls.map(r=>JSON.parse(r.options.body).command_id);assert.deepEqual(ids,[pending.command_id,pending.command_id,pending.command_id]);
});
test('Confirmed write stays confirmed when subsequent refresh receives read 429',async()=>{
 const a=client();a.c.refresh=()=>a.c.request('/api/farm/v1/me');
 a.responses.push(response(200),response(429,'60'));
 assert.equal(await a.c.command('plant'),true);assert.equal(a.S.pending,null);assert.equal(a.memory.size,0);
 assert.equal(a.c.rateSeconds('write'),0);assert.equal(a.c.rateSeconds('read'),60);
 assert.match(a.nodes.connection.textContent,/Обновление доступно через 60 с/);
 assert.equal(a.nodes.retry.disabled,true);assert.equal(a.timers.size,1,'refresh will be retried by itself');
});
test('Startup 429 has a countdown and retries config/start after the wait',async()=>{
 const a=client();a.S.me=null;a.c.enter=()=>a.c.request('/api/farm/v1/start',{method:'POST'});
 a.responses.push(response(200,null,{demo:false}),response(429,'2'));
 await assert.rejects(a.c.retryConnection(),e=>e.status===429);
 assert.equal(a.nodes.retry.disabled,true);assert.match(a.nodes.connection.textContent,/Действия доступны через 2 с/);
 await assert.rejects(a.c.retryConnection(),e=>e.status===429);assert.equal(a.calls.length,3);
 a.advance(2000);assert.equal(a.nodes.retry.disabled,false);assert.equal(a.nodes.retry.hidden,false);
 await a.c.retryConnection();assert.deepEqual(a.calls.slice(-2).map(r=>r.p),['/api/farm/v1/config','/api/farm/v1/start']);
 assert.equal(a.timers.size,0);
});
test('Repeated cooldown cycles do not accumulate timers; known errors still clear pending',async()=>{
 const a=client();
 for(let i=0;i<20;i++){
  a.responses.push(response(429,'1'));assert.equal(await a.c.command('plant'),false);
  assert.ok(a.timers.size<=1);a.advance(1000);
  a.responses.push(response(400,null,{message:'invalid command'}));assert.equal(await a.c.sendPending(),false);
  assert.equal(a.S.pending,null);assert.equal(a.memory.size,0);assert.ok(a.timers.size<=1);assert.equal(a.classes.size,0);
 }
});
test('Real login displays startup 429 countdown/retry outside the hidden game ancestor',async()=>{
 for(const failing of ['config','start']){
  const a=client();a.S.me=null;
  class Node{
   constructor(tag,text){this.tagName=tag.toUpperCase();this.textContent=text;this.children=[];this.hidden=false;}
   set id(id){a.nodes[id]=this;}
   append(...children){for(const child of children){child.parentNode=this;this.children.push(child);}}
   replaceChildren(...children){this.children=[];this.append(...children);}
   setAttribute(){}
  }
  const body=new Node('body');
  for(const id of ['game','login','header-actions','hud']){a.nodes[id]=new Node('div');body.append(a.nodes[id]);}
  // Mirrors index.html: the scene status/retry live under <main id=game>.
  a.nodes.game.append(a.nodes.connection,a.nodes.retry);
  a.c.el=(tag,text)=>new Node(tag,text);a.c.note=(text,parent)=>parent.append(a.c.el('p',text));
  a.c.button=(text,fn)=>{const n=new Node('button',text);n.onclick=fn;return n;};
  a.c.safe=fn=>fn;a.c.parseInvite=()=>null;a.c.location={assign(){}};a.c.farmViewEpoch=0;
  const login=source.slice(source.indexOf('function showLogin('),source.indexOf('function showRecovery('));
  const enter=source.slice(source.indexOf('async function enter('),source.indexOf('function showLogin('));
  vm.runInContext(login+'\n'+enter+'\nObject.assign(globalThis,{showLogin,enter})',a.c);
  if(failing==='start')a.responses.push(response(200,null,{demo:false}));
  a.responses.push(response(429,'2'));
  try{await a.c.retryConnection();}catch(e){a.S.config={demo:false};a.c.showLogin(e.message);}
  const visible=node=>{for(let current=node;current;current=current.parentNode)if(current.hidden)return false;return true;};
  assert.equal(visible(a.nodes.retry),false);assert.equal(visible(a.nodes['login-retry']),true);
  assert.match(a.nodes['login-rate'].textContent,/через 2 с/);assert.equal(a.nodes['login-retry'].disabled,true);
  a.advance(2000);assert.equal(visible(a.nodes['login-retry']),true);assert.equal(a.nodes['login-retry'].disabled,false);
  let entered=0;a.c.enter=async()=>{entered++;};await a.nodes['login-retry'].onclick();assert.equal(entered,1);
 }
});

test('429 with a game code (daily_limit) is an ordinary answer: no waiting window, pending is dropped, next command works',async()=>{
 const a=client();a.responses.push(response(429,null,{code:'daily_limit',message:'На сегодня хватит — продолжим завтра.'}));
 assert.equal(await a.c.command('help',{object:'o'}),false);
 assert.equal(a.S.pending,null);assert.equal(a.memory.size,0);assert.equal(a.c.rateSeconds('write'),0);assert.equal(a.timers.size,0);
 assert.deepEqual(a.messages.at(-1),'На сегодня хватит — продолжим завтра.');
 assert.equal(await a.c.command('plant',{crop:'wheat'}),true,'the game is not blocked behind the old answer');
 assert.equal(a.calls.length,2);
});
test('After a real 429 the game recovers by itself: waits Retry-After, replays the same command, no reload',async()=>{
 const a=client();a.responses.push(response(429,'4'),response(200));
 assert.equal(await a.c.command('plant',{crop:'wheat'}),false);
 const entry=[...a.callbacks.values()][0];assert.equal(entry.ms,4250);
 a.advance(4000);await a.fire();
 assert.equal(a.calls.length,2);assert.equal(a.S.pending,null);assert.equal(a.memory.size,0);
 assert.deepEqual(JSON.parse(a.calls[0].options.body),JSON.parse(a.calls[1].options.body));
 assert.equal(await a.c.command('harvest'),true);
});
test('A read 429 (polling) schedules a refresh by itself; repeated 429 keeps one timer and gives up politely',async()=>{
 const a=client();let refreshes=0;a.c.refresh=async()=>{refreshes++;return a.c.request('/api/farm/v1/me');};
 a.responses.push(response(429,'2'),response(200,null,{farm:{}}));
 await assert.rejects(a.c.refresh(),e=>e.rateBucket==='read');a.c.scheduleRateRecovery();
 assert.equal(a.timers.size,1);a.c.scheduleRateRecovery();assert.equal(a.timers.size,1);
 a.advance(2000);await a.fire();assert.equal(a.timers.size,0);assert.equal(refreshes,2);
 for(let i=0;i<12;i++){a.responses.push(response(429,'1'));a.advance(1000);await assert.rejects(a.c.request('/api/farm/v1/me'));a.c.scheduleRateRecovery();await a.fire();}
 assert.ok(a.timers.size<=1);
});
