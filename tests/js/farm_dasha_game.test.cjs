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
vm.runInContext(`${source}\nglobalThis.api={dashaViewState,dashaReasonText,choiceFailureKeepsRound,dashaPayoutDisplay};`,context);
const view=context.api.dashaViewState;
const makeWager=overrides=>({rules:{stakes:[10,20,50],multiplier:2.7,payouts:{'10':27,'20':54,'50':135}},earned_balance:80,eligible:true,reason:null,daily_staked:30,remaining_stake:170,active:null,last_result:null,...overrides});

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
 assert.doesNotMatch(source,/crypto\.getRandomValues|Math\.random|default_cup|winning_cup\s*=/);
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
  const ctx={S,API:'/api',pendingRetryTimer:null,rateRecoveryAttempt:0,dashaGame:{render(){events.push(['render',!!S.pending,!!S.me.wager.active,S.busy]);},choiceRejected(id){events.push(['rejected',id,S.busy,!!S.pending]);}},document:{body:{classList:{add(){},remove(){}}}},clearTimeout(){},connection(){},rememberMachineCommand(){},savePending(){},toast(){},updateRepeat(){},renderPanel(){},scheduleRateRecovery(){},schedulePendingRetry(){},
   request:async()=>{if(outcome==='reject'){const e=new Error('rejected');throw e;}if(outcome==='unknown'){const e=new Error('offline');e.unknown=true;throw e;}return {notice:'ok',neighbor_reward_paid:false};},
   refresh:async()=>{if(outcome==='success')S.me.wager={active:null,last_result:{id:'round-1',won:true}};return true;}};
  vm.createContext(ctx);vm.runInContext(app.slice(start,end)+'\nglobalThis.run=sendPending',ctx);const accepted=await ctx.run();return {accepted,events,S};
 }
 const success=await run('success');assert.equal(success.accepted,true);assert.deepEqual(success.events,[['render',false,false,false]],'late success renders settled result after busy clears');
 const rejected=await run('reject');assert.equal(rejected.accepted,false);assert.deepEqual(rejected.events,[['render',false,true,false],['rejected','round-1',false,false]],'known rejection reopens the same active round after refresh');
 const uncertain=await run('unknown');assert.equal(uncertain.accepted,false);assert.equal(uncertain.S.pending.command_id,'same-key');assert.deepEqual(uncertain.events,[['render',true,true,false]],'unknown response keeps pending replay key and does not reopen choice');
});
