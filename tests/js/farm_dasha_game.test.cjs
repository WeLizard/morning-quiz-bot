'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const root=path.resolve(__dirname,'../..');
const read=file=>fs.readFileSync(path.join(root,file),'utf8');
const source=read('qw_farm/static/dasha-game.js').replace(/export /g,'');
const context={Number,Array,Object,Math,Boolean,Set,Map,Intl};
vm.createContext(context);
vm.runInContext(`${source}\nglobalThis.api={dashaViewState,dashaReasonText,choiceFailureKeepsRound,dashaPayoutDisplay,mountDashaGame,dashaSelectedStake,pluralRu,coinsText,localizeWagerNotice,dashaShuffleSteps,dashaRevealOrder};`,context);
const view=context.api.dashaViewState;
const makeWager=overrides=>({rules:{stakes:[10,20,50],multiplier:2.7,payouts:{'10':27,'20':54,'50':135}},earned_balance:80,eligible:true,reason:null,daily_staked:30,remaining_stake:170,active:null,last_result:null,...overrides});

async function waitFor(predicate,timeout=3000){
 const start=Date.now();
 while(!predicate()){
  if(Date.now()-start>timeout)throw new Error('condition was not met in time');
  await new Promise(resolve=>setTimeout(resolve,10));
 }
}
class FakeClassList{
 constructor(){this.values=new Set();}
 add(...names){for(const name of names)this.values.add(name);}
 remove(...names){for(const name of names)this.values.delete(name);}
 contains(name){return this.values.has(name);}
}
class FakeNode{
 constructor(){this.classList=new FakeClassList();this.dataset={};this.attrs={};this.children=[];this.listeners={};this.disabled=false;this.textContent='';this.styleLog=[];this.style={setProperty:(name,value)=>this.styleLog.push([name,value])};}
 addEventListener(name,callback){(this.listeners[name]??=[]).push(callback);}
 emit(name,event={}){for(const callback of this.listeners[name]||[])callback(event);}
 setAttribute(name,value){this.attrs[name]=String(value);}
 getAttribute(name){return this.attrs[name]??null;}
 removeAttribute(name){delete this.attrs[name];}
 replaceChildren(...children){this.children=children;}
 focus(){}
}
function fakeGameHost(){
 const nodes={
  '.dasha-stakes':new FakeNode(),'[data-role="balance"]':new FakeNode(),
  '[data-role="payout"]':new FakeNode(),'[data-role="status"]':new FakeNode(),
  '.dasha-speech':new FakeNode(),'[data-role="action"]':new FakeNode(),
  '.dasha-carrot':new FakeNode(),'.dasha-curtain':new FakeNode(),'.dasha-back':new FakeNode()
 };
 const cups=[0,1,2].map(()=>new FakeNode());
 const host=new FakeNode();host.querySelector=selector=>nodes[selector]||null;
 host.querySelectorAll=selector=>selector==='.dasha-cup'?cups:[];
 host.replaceChildren=()=>{};
 return {host,nodes,cups};
}

test('start eligibility uses only the server wager projection and stake limits',()=>{
 const w=makeWager();
 assert.equal(view(w,900,10).canStart,true);
 assert.equal(view(w,900,10).payout,27);
 assert.equal(view(w,900,50).canStart,true);
 assert.equal(view(w,900,100).canStart,false);
 assert.equal(view(makeWager({remaining_stake:5}),900,10).canStart,false);
 assert.equal(view(makeWager({eligible:false,reason:'Открой уровень 3.'}),900,10).canStart,false);
 assert.equal(view(makeWager(),900,10,true).canStart,false,'an in-flight command blocks another start');
});

test('server payout table is authoritative and missing payout blocks start',()=>{
 const altered=makeWager({rules:{stakes:[10,20,50],multiplier:2.7,payouts:{'10':31,'20':99,'50':201}}});
 assert.equal(view(altered,900,10).payout,31,'uses server-provided amount instead of multiplying the stake');
 assert.equal(view(makeWager({rules:{stakes:[10,20,50],multiplier:2.7}}),900,10).payout,null);
 assert.equal(view(makeWager({rules:{stakes:[10,20,50],multiplier:2.7}}),900,10).canStart,false);
});

test('known wager reason codes are translated and unknown codes use safe Russian fallback',()=>{
 assert.equal(context.api.dashaReasonText('level'),'Игра открывается с 3 уровня.');
 assert.equal(context.api.dashaReasonText('daily_limit'),'Лимит ставок 200 монет в день исчерпан.');
 assert.equal(context.api.dashaReasonText('pending_payout'),'Выигрыш ожидает места на балансе.');
 assert.equal(context.api.dashaReasonText('earned_balance'),'Для ставки нужны заработанные монеты.');
 assert.equal(context.api.dashaReasonText('wallet_limit'),'Баланс монет достиг предела.');
 assert.equal(context.api.dashaReasonText('active'),'Раунд уже начат — выбери стаканчик.');
 assert.equal(context.api.dashaReasonText('future_machine_code'),'Игра сейчас недоступна.');
});

test('payout row follows the selected stake after a previous result',()=>{
 const payout=view(makeWager({rules:{stakes:[10,20,50],multiplier:2.7,payouts:{'10':27,'20':54,'50':135}},last_result:{id:'old',payout:27,won:true}}),900,50).payout;
 assert.equal(context.api.dashaPayoutDisplay(null,payout),135,'historical result payout does not override the selected stake quote');
 assert.equal(context.api.dashaPayoutDisplay({payout:54},payout),54,'an active round always shows its server payout');
});

test('a known rejected choice restores the same server round, while pending replay stays locked',()=>{
 const keep=context.api.choiceFailureKeepsRound;
 assert.equal(keep(false,false,'round-1','round-1'),true,'same active round can be selected again after known rejection');
 assert.equal(keep(false,true,'round-1','round-1'),false,'uncertain pending command must be replayed with its existing key');
 assert.equal(keep(false,false,'round-2','round-1'),false,'a changed or settled server round is not reopened');
 assert.equal(keep(true,false,'round-1','round-1'),false,'accepted choice is never reopened');
 assert.match(source,/choiceFailureKeepsRound\(accepted,isCommandPending\(\),active\?\.id,roundId\)/);
});

test('an active round restores as a pick with no revealed cup or secret fields',()=>{
 const w=makeWager({active:{id:'round-1',stake:20,payout:54,expires_at:123,rules_version:1,winning_cup:2,default_cup:2}});
 const result=view(w,500,10);
 assert.equal(result.canChoose,true);
 assert.equal(result.showCarrot,false);
 assert.equal(result.result,null);
 assert.deepEqual(JSON.parse(JSON.stringify(result.active)),{id:'round-1',stake:20,payout:54,expires_at:123,rules_version:1});
 assert.equal(view(w,500,10,true).canChoose,false);
});

test('only a settled server result reveals the carrot, and escrow stays explicit',()=>{
 const w=makeWager({eligible:false,reason:'Дождись места на балансе.',last_result:{id:'round-2',stake:50,payout:135,chosen_cup:0,winning_cup:0,won:true,settled_at:456,pending_payout:35,default_cup:1}});
 const result=view(w,1_000_000,10);
 assert.equal(result.showCarrot,true);
 assert.equal(result.result.won,true);
 assert.equal(result.result.pending_payout,35);
 assert.equal('default_cup' in result.result,false);
 assert.equal(view(makeWager({active:{id:'r',stake:10,payout:27,winning_cup:0},last_result:w.last_result}),100,10).showCarrot,false);
});

test('client sends only server commands and never creates its own outcome',()=>{
 assert.match(source,/command\('wager_start',\{stake:selectedStake\}\)/);
 assert.match(source,/command\('wager_choose',\{round_id:roundId,cup:position\}\)/);
 const cosmetic=source.match(/^function dashaShuffleSteps\(.*$/m)?.[0]||'';
 assert.match(cosmetic,/Math\.random/,'the only randomness is the cosmetic screen choreography');
 assert.doesNotMatch(source.replace(cosmetic,''),/crypto\.getRandomValues|Math\.random|default_cup|winning_cup\s*=/);
 assert.doesNotMatch(source,/selectedStake\*Number\(w\?\.rules\?\.multiplier/);
 assert.match(source,/pending_payout/);
 assert.match(source,/automatically|сервер подведёт итог автоматически/i);
});

test('accepted scene assets are local, responsive and isolated from the farm styles',()=>{
 const html=read('qw_farm/static/index.html'),css=read('qw_farm/static/dasha-game.css'),scene=read('qw_farm/static/dasha-scene.svg');
 assert.ok(html.includes('/app/farm/assets/dasha-game.css'));
 assert.ok(html.includes('id="dasha-game-view"'));
 assert.ok(!/<iframe\b/i.test(html));
 assert.equal((source.match(/class="dasha-cup"/g)||[]).length,3);
 assert.equal((source.match(/<symbol id="dasha-cup"/g)||[]).length,1);
 assert.match(css,/#dasha-game-view\s+\.dasha-scene/);
 assert.match(css,/@media\(max-width:350px\)/);
 assert.match(css,/@media\(prefers-reduced-motion:reduce\)/);
 assert.match(scene,/<svg\b/);
 assert.doesNotMatch(scene,/<image\b|data:image/i);
});

test('cup, carrot and curtain state classes match CSS through shuffle and settled reveal',async()=>{
 const css=read('qw_farm/static/dasha-game.css');
 assert.match(css,/\.dasha-stake\.dasha-selected\b/);
 assert.match(css,/\.dasha-cup\.dasha-lift\b/);
 assert.match(css,/\.dasha-cup\.dasha-peek\b/);
 assert.match(css,/\.dasha-cup\.dasha-chosen\b/);
 assert.match(css,/\.dasha-carrot\.dasha-visible\b/);
 assert.match(css,/\.dasha-curtain\.dasha-closed\b/);

 context.document={createElement:()=>new FakeNode()};
 context.matchMedia=()=>({matches:true});
 context.setTimeout=setTimeout;
 const {host,nodes,cups}=fakeGameHost();
 const state={coins:1000,wager:makeWager()};
 let settleStart,settleChoice;
 const calls=[];
 const command=(kind,data)=>{
  calls.push([kind,data]);
  return new Promise(resolve=>{if(kind==='wager_start')settleStart=resolve;else if(kind==='wager_choose')settleChoice=resolve;});
 };
 context.api.mountDashaGame(host,{getState:()=>state,command,onBack(){}});
 const action=nodes['[data-role="action"]'],carrot=nodes['.dasha-carrot'],curtain=nodes['.dasha-curtain'];
 assert.equal(nodes['.dasha-stakes'].children[0].className,'dasha-stake dasha-selected','the selected stake gets its matching CSS state');
 assert.equal(action.getAttribute('aria-label'),null);

 action.emit('click');
 assert.equal(calls[0][0],'wager_start');
 state.wager.active={id:'round-visual',stake:10,payout:27,expires_at:600,rules_version:1};
 settleStart(true);
 await new Promise(resolve=>setTimeout(resolve,0));
 assert.equal(curtain.classList.contains('dasha-closed'),true,'server-started shuffle closes the curtain before a choice is enabled');
 assert.equal(carrot.classList.contains('dasha-visible'),false,'carrot stays hidden during shuffle');
 await waitFor(()=>cups.every(cup=>!cup.disabled));
 assert.equal(curtain.classList.contains('dasha-closed'),false,'curtain opens only after shuffle');
 assert.equal(cups.every(cup=>!cup.disabled),true,'cups become selectable after the shuffle');

 cups[0].emit('click');
 assert.equal(calls[1][0],'wager_choose');
 state.wager.active=null;
 state.wager.last_result={id:'round-visual',stake:10,payout:27,chosen_cup:0,winning_cup:0,won:true,settled_at:601,pending_payout:0};
 settleChoice(true);
 await new Promise(resolve=>setTimeout(resolve,0));
 assert.equal(carrot.classList.contains('dasha-visible'),true,'server-settled result reveals the carrot');
 assert.equal(cups[0].classList.contains('dasha-lift'),true,'the chosen cup lifts first');
 assert.equal(cups.slice(1).some(cup=>cup.classList.contains('dasha-lift')),false,'the other cups wait for a short pause');
 assert.equal(host.dataset.mood,'reveal');
 await waitFor(()=>cups.every(cup=>cup.classList.contains('dasha-lift')));
 assert.equal(host.dataset.mood,'win','Dasha reacts to the settled win');
 assert.equal(cups[0].classList.contains('dasha-chosen'),true,'the selected cup gets its matching CSS state');
 assert.equal(carrot.classList.contains('dasha-found'),true,'the found carrot pops');
 assert.equal(action.textContent,'Ещё раунд');
 assert.equal(action.getAttribute('aria-label'),null,'the stale choose label is removed after settlement');
});

test('the game returns to its village action and keyboard Escape cannot also close its panel',()=>{
 const app=read('qw_farm/static/app.js');
 assert.match(app,/navPush\('dasha-wager',closeDashaGame\)/);
 assert.match(app,/navPop\('dasha-wager'\)/);
 assert.match(app,/data-open-dasha/);
 assert.match(source,/e\.stopPropagation\(\);onBack\(\)/);
});

test('sendPending settles the Dasha view after late success and reopens only a known-rejected active round',async()=>{
 const app=read('qw_farm/static/app.js'),start=app.indexOf('async function sendPending(){'),marker=app.indexOf('// After a real 429',start),end=app.lastIndexOf('}',marker)+1;
 assert.ok(start>=0&&end>start);
 async function run(outcome){
  const events=[],S={me:{id:'owner',wager:{active:{id:'round-1'}}},pending:{actor:'owner',kind:'wager_choose',data:{round_id:'round-1'},command_id:'same-key'},busy:false};
  const ctx={S,API:'/api',pendingRetryTimer:null,rateRecoveryAttempt:0,dashaGame:{render(){events.push(['render',!!S.pending,!!S.me.wager.active,S.busy]);},choiceRejected(id){events.push(['rejected',id,S.busy,!!S.pending]);}},olegGame:null,document:{body:{classList:{add(){},remove(){}}}},clearTimeout(){},connection(){},rememberMachineCommand(){},savePending(){},toast(){},localizeWagerNotice:text=>text,gf:(m,f,n)=>n,updateRepeat(){},renderPanel(){},scheduleRateRecovery(){},schedulePendingRetry(){},
   request:async()=>{if(outcome==='reject'){const e=new Error('rejected');throw e;}if(outcome==='unknown'){const e=new Error('offline');e.unknown=true;throw e;}return {notice:'ok',neighbor_reward_paid:false};},
   refresh:async()=>{if(outcome==='success')S.me.wager={active:null,last_result:{id:'round-1',won:true}};return true;}};
  vm.createContext(ctx);vm.runInContext(app.slice(start,end)+'\nglobalThis.run=sendPending',ctx);const accepted=await ctx.run();return {accepted,events,S};
 }
 const success=await run('success');assert.equal(success.accepted,true);assert.deepEqual(success.events,[['render',false,false,false]],'late success renders settled result after busy clears');
 const rejected=await run('reject');assert.equal(rejected.accepted,false);assert.deepEqual(rejected.events,[['render',false,true,false],['rejected','round-1',false,false]],'known rejection reopens the same active round after refresh');
 const uncertain=await run('unknown');assert.equal(uncertain.accepted,false);assert.equal(uncertain.S.pending.command_id,'same-key');assert.deepEqual(uncertain.events,[['render',true,true,false]],'unknown response keeps pending replay key and does not reopen choice');
});

test('a restored active round highlights the stake that was actually placed',()=>{
 context.matchMedia=()=>({matches:true});
 const {host,nodes}=fakeGameHost();
 const state={coins:500,wager:makeWager({active:{id:'round-9',stake:20,payout:54,expires_at:900,rules_version:1}})};
 context.api.mountDashaGame(host,{getState:()=>state,command:async()=>true,onBack(){}});
 const chips=nodes['.dasha-stakes'].children;
 assert.equal(chips.find(c=>c.dataset.stake==='20').getAttribute('aria-pressed'),'true');
 assert.equal(chips.find(c=>c.dataset.stake==='10').getAttribute('aria-pressed'),'false');
 assert.match(chips.find(c=>c.dataset.stake==='20').className,/dasha-selected/);
 assert.equal(nodes['[data-role="payout"]'].textContent,'54 монеты');
 assert.equal(context.api.dashaSelectedStake(null,50),50);
});

test('Russian coin plurals follow the 1 / 2-4 / 5+ and 11-14 rules',()=>{
 const t=context.api.coinsText,nb=s=>s.replace(/ | /g,' ');
 for(const [n,word] of [[1,'монета'],[2,'монеты'],[4,'монеты'],[5,'монет'],[11,'монет'],[12,'монет'],[14,'монет'],[21,'монета'],[22,'монеты'],[54,'монеты'],[27,'монет'],[135,'монет'],[0,'монет'],[101,'монета'],[111,'монет']])assert.equal(nb(t(n)).split(' ').pop(),word,String(n));
 assert.equal(nb(t(54)),'54 монеты');
});

test('server settlement notices get the player address form and plural coins',()=>{
 const l=context.api.localizeWagerNotice,pick={m:(a,b,c)=>a,f:(a,b,c)=>b,n:(a,b,c)=>c};
 const server='Ты выиграл(а)! 54 монет начислено, 21 отложено до появления места на балансе.';
 assert.equal(l(server,pick.f),'Ты выиграла! Начислено: 54 монеты, отложено: 21 монета — до появления места на балансе.');
 assert.equal(l(server,pick.m).startsWith('Ты выиграл! '),true);
 assert.equal(l(server,pick.n).startsWith('Победа! '),true);
 assert.equal(l('Ты выиграл(а)! Выплата уже на балансе.',pick.f),'Ты выиграла! Выплата уже на балансе.');
 assert.equal(l('Обычное сообщение.',pick.f),'Обычное сообщение.');
 assert.equal(l(undefined,pick.f),undefined);
 assert.match(read('qw_farm/static/app.js'),/toast\(localizeWagerNotice\(r\.notice,gf\)\)/);
});

test('the auto-pick and no-refund rule sits above the stake button',()=>{
 const html=source.slice(source.indexOf('host.innerHTML=`'),source.indexOf('const $=s=>'));
 const note=html.indexOf('dasha-foot-note'),button=html.indexOf('data-role="action"');
 assert.ok(note>0&&button>0&&note<button,'rule line precedes the button');
 assert.match(html,/10 минут[^<]*случайный выбор[^<]*ставка не возвращается/i);
});

test('cosmetic shuffle varies by rng only and never sees the server round',async()=>{
 const seq=values=>{let i=0;return ()=>values[i++%values.length];};
 const a=context.api.dashaShuffleSteps(seq([.1,.9,.3,.7,.5])),b=context.api.dashaShuffleSteps(seq([.9,.2,.6,.1,.4]));
 assert.notDeepEqual(JSON.parse(JSON.stringify(a)),JSON.parse(JSON.stringify(b)),'different rounds get different screen choreography');
 for(const step of [...a,...b]){assert.ok(step.x>=14&&step.x<=86);assert.ok(Math.abs(step.tilt)<=2.4);assert.ok(step.ms>=280&&step.ms<=480);}
 assert.equal(context.api.dashaShuffleSteps.length,0,'only an optional rng parameter, no wager input');
 context.document={createElement:()=>new FakeNode()};context.matchMedia=()=>({matches:true});context.setTimeout=setTimeout;
 async function run(active){
  const {host,nodes,cups}=fakeGameHost(),state={coins:500,wager:makeWager()};
  const command=async kind=>{if(kind==='wager_start')state.wager.active=active;return true;};
  context.api.mountDashaGame(host,{getState:()=>state,command,onBack(){},rng:seq([.25,.75,.5,.125,.875])});
  nodes['[data-role="action"]'].emit('click');
  await waitFor(()=>cups.every(cup=>!cup.disabled));
  assert.equal(cups.every(cup=>!cup.classList.contains('dasha-lift')),true);
  return JSON.stringify(nodes['.dasha-curtain'].styleLog);
 }
 const one=await run({id:'r1',stake:10,payout:27,expires_at:1,rules_version:1,winning_cup:0,default_cup:2});
 const two=await run({id:'r2',stake:10,payout:27,expires_at:1,rules_version:1,winning_cup:2,default_cup:0});
 assert.ok(one.length>2);
 assert.equal(one,two,'hidden server fields cannot steer the visible shuffle');
});

test('reveal lifts the chosen cup first; a restored result snaps open without effects',()=>{
 assert.deepEqual(JSON.parse(JSON.stringify(context.api.dashaRevealOrder(2))),[[2],[0,1]]);
 assert.deepEqual(JSON.parse(JSON.stringify(context.api.dashaRevealOrder(null))),[[0,1,2],[]]);
 context.document={createElement:()=>new FakeNode()};context.matchMedia=()=>({matches:true});
 const {host,nodes,cups}=fakeGameHost();
 const state={coins:500,wager:makeWager({last_result:{id:'old',stake:20,payout:54,chosen_cup:1,winning_cup:2,won:false,settled_at:5,pending_payout:0}})};
 context.api.mountDashaGame(host,{getState:()=>state,command:async()=>true,onBack(){}});
 assert.equal(cups.every(cup=>cup.classList.contains('dasha-lift')),true,'reopened result is shown fully');
 assert.equal(host.dataset.mood,'lose');
 assert.equal(nodes['.dasha-carrot'].classList.contains('dasha-found'),false,'no replayed celebration on reopen');
 assert.match(nodes['[data-role="status"]'].textContent,/20 монет/);
});

test('rules, pick affordance, win/lose feedback and night variant are styled',()=>{
 const css=read('qw_farm/static/dasha-game.css');
 assert.match(source,/class="dasha-foot-note">[^]*?шанс 1 из 3/i,'the chance is visible next to the stake button');
 assert.match(css,/\.dasha-foot-note\{[^}]*font-size:var\(--qw-fs-small\)/);
 assert.match(css,/\.dasha-cup:not\(:disabled\)/);
 assert.match(css,/\[data-mood=pick\] \.dasha-pick-hint/);
 assert.match(css,/\.dasha-primary\.dasha-await/,'the disabled button stops looking primary while the cups are live');
 assert.match(css,/\.dasha-coin-pop\.dasha-pop-win/);assert.match(css,/\.dasha-coin-pop\.dasha-pop-lose/);
 assert.match(css,/:root\[data-farm-theme=night\] #dasha-game-view\{/);
 assert.match(css,/:root\[data-farm-phase=dusk\] #dasha-game-view \.dasha-scene-caption \.dasha-cap-dusk/);
 assert.match(source,/dasha-cap-day/,'the caption follows the time of day instead of always saying evening');
 const reduced=css.slice(css.lastIndexOf('@media(prefers-reduced-motion:reduce)'));
 assert.match(reduced,/\.dasha-confetti/);
});
