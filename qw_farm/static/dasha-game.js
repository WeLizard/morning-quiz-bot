const SLOT_NAMES=['левый','средний','правый'];
const STAKES=[10,20,50];
const WAGER_REASONS={level:'Игра открывается с 3 уровня.',daily_limit:'Лимит ставок 200 монет в день исчерпан.',pending_payout:'Выигрыш ожидает места на балансе.',earned_balance:'Для ставки нужны заработанные монеты.',wallet_limit:'Баланс монет достиг предела.',active:'Раунд уже начат — выбери стаканчик.'};

export function pluralRu(n,one,few,many){const v=Math.abs(Math.trunc(Number(n)))||0,t=v%100,u=v%10;return t>=11&&t<=14?many:u===1?one:u>=2&&u<=4?few:many;}
export function coinsText(n){const v=Number(n)||0;return `${new Intl.NumberFormat('ru-RU').format(v)} ${pluralRu(v,'монета','монеты','монет')}`;}
// Server settlement notices carry "выиграл(а)" and bare "N монет"; the client picks the player's address form and plural.
export function localizeWagerNotice(text,address=(m,f,n)=>n){
 if(typeof text!=='string')return text;
 return text.replace('Ты выиграл(а)!',address('Ты выиграл!','Ты выиграла!','Победа!'))
  .replace(/(\d+) монет начислено, (\d+) отложено до появления места на балансе\./,(_,paid,held)=>`Начислено: ${coinsText(Number(paid))}, отложено: ${coinsText(Number(held))} — до появления места на балансе.`);
}
export function dashaReasonText(reason){return WAGER_REASONS[reason]||'Игра сейчас недоступна.';}
export function choiceFailureKeepsRound(accepted,pending,activeId,roundId){return !accepted&&!pending&&activeId===roundId;}
export function dashaPayoutDisplay(active,payout){return active?.payout??payout;}

export function dashaSelectedStake(wager,current){const stake=wager?.active?.stake;return Number.isInteger(stake)&&stake>0?stake:current;}

export function dashaViewState(wager,coins,stake,pending=false){
 const rawActive=wager?.active||null;
 const active=rawActive?{id:rawActive.id,stake:rawActive.stake,payout:rawActive.payout,expires_at:rawActive.expires_at,rules_version:rawActive.rules_version}:null;
 const rawResult=active?null:(wager?.last_result||null);
 const result=rawResult?{id:rawResult.id,stake:rawResult.stake,payout:rawResult.payout,chosen_cup:rawResult.chosen_cup,winning_cup:rawResult.winning_cup,won:rawResult.won,settled_at:rawResult.settled_at,pending_payout:rawResult.pending_payout}:null;
 const earned=Number(wager?.earned_balance)||0,remaining=Number(wager?.remaining_stake)||0;
 const allowedStakes=Array.isArray(wager?.rules?.stakes)?wager.rules.stakes:STAKES;
 const rawPayout=wager?.rules?.payouts?.[String(stake)],payout=Number.isSafeInteger(rawPayout)&&rawPayout>0?rawPayout:null;
 const stakeAllowed=Number.isInteger(stake)&&allowedStakes.includes(stake)&&stake<=earned&&stake<=remaining;
 return {active,result,payout,canStart:!active&&!pending&&!!wager?.eligible&&stakeAllowed&&payout!==null,canChoose:!!active&&!pending,stakeAllowed,showCarrot:!!result,coins:Number.isFinite(coins)?coins:0};
}

// Cosmetic choreography for the screen while Dasha shuffles. Purely decorative: the cups stay hidden behind the screen for the whole shuffle and the outcome is decided by the server, so the steps take only an rng and never see the wager projection.
export function dashaShuffleSteps(rng=Math.random){const n=4+Math.floor(rng()*3);return Array.from({length:n},()=>({x:Math.round(14+rng()*72),tilt:Math.round((rng()*2-1)*24)/10,ms:Math.round(280+rng()*200)}));}
// Reveal order: the player's cup lifts first, the other two follow after a short pause.
export function dashaRevealOrder(chosen){return Number.isInteger(chosen)&&chosen>=0&&chosen<=2?[[chosen],[0,1,2].filter(slot=>slot!==chosen)]:[[0,1,2],[]];}


const cupSymbol=`<svg class="dasha-cup-defs" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false"><defs><symbol id="dasha-cup" viewBox="0 0 118 137">
<ellipse cx="59" cy="129" rx="45" ry="7" fill="#59452e" opacity=".24"/><path d="M30 25 L11 112 Q59 134 107 112 L88 25 Q59 15 30 25Z" fill="#eddaad" stroke="#986b4a" stroke-width="2.5" stroke-linejoin="round"/><path d="M29 29 17 107 Q28 117 37 119 L39 28Z" fill="#fff0cc" opacity=".72"/><path d="M83 28 100 108 Q96 114 87 117 L78 28Z" fill="#c89c72" opacity=".34"/><path d="M20 79 Q59 97 98 79" fill="none" stroke="#b97661" stroke-width="7"/><path d="M19 88 Q59 105 99 88" fill="none" stroke="#f9e8c3" stroke-width="3"/><path d="M27 62 Q59 75 91 62" fill="none" stroke="#658d72" stroke-width="7" stroke-linecap="round"/><path d="M44 62 Q48 72 52 68 M65 69 Q70 72 74 62" fill="none" stroke="#e5c681" stroke-width="3.5" stroke-linecap="round"/><ellipse cx="59" cy="25" rx="29" ry="9" fill="#f9e8c3" stroke="#986b4a" stroke-width="2.5"/><path d="M37 22 Q59 16 79 22" fill="none" stroke="#fff8e2" stroke-width="3" stroke-linecap="round"/><path d="M11 112 Q59 134 107 112" fill="none" stroke="#845b44" stroke-width="3.5" stroke-linecap="round"/><path d="M19 114 Q59 128 99 114" fill="none" stroke="#fff0d1" stroke-width="2" opacity=".7"/>
</symbol></defs></svg>`;
const carrotSvg=`<svg viewBox="0 0 100 44" aria-hidden="true"><ellipse cx="54" cy="39" rx="40" ry="4" fill="#5a3d27" opacity=".2"/><path d="M26 16Q14 3 4 8q8 6 18 13Q8 20 3 30q11 2 24-6Z" fill="#6b9f62"/><path d="M14 9q6 3 10 9M10 27q7-2 13-5" stroke="#8fbd78" stroke-width="2" fill="none" stroke-linecap="round"/><path d="M24 12Q62 7 97 24Q63 38 24 33Q15 22 24 12Z" fill="#ee8d3f"/><path d="M27 15Q58 12 86 22" stroke="#f8b26c" stroke-width="3.5" fill="none" stroke-linecap="round" opacity=".8"/><path d="M42 26l7-1m11-11 1 5m13 6 5-1M36 15l1 4" stroke="#c96a30" stroke-width="2" fill="none" stroke-linecap="round"/></svg>`;
const dropCarrotSvg=`<svg viewBox="0 0 48 70" aria-hidden="true"><path d="M25 16Q15 10 18 2q9 2 9 13Q30 4 39 5q-1 10-12 13Z" fill="#6b9f62"/><path d="M9 20q14-12 30 1-4 25-19 47Q6 43 9 20Z" fill="#ee8d3f"/><path d="M15 34q4-1 8 1m2 10 7-1" stroke="#c96a30" stroke-width="2" fill="none" stroke-linecap="round"/></svg>`;
const logoSvg=`<svg viewBox="0 0 44 44" aria-hidden="true"><path d="M7 9 18 14 27 14 38 9 34 28Q22 42 10 28Z" fill="#d9894f"/><path d="M10 25Q22 39 34 25 29 35 22 36 15 35 10 25" fill="#fff3d8"/><circle cx="17" cy="23" r="1.7"/><circle cx="27" cy="23" r="1.7"/><path d="m20 27 2 2 2-2Z" fill="#513f35"/></svg>`;
const ruleIcon=`<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9.5" fill="currentColor" opacity=".16"/><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 7.5V12l3 2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const star=(x,y,s=1)=>`<path transform="translate(${x} ${y}) scale(${s})" d="M0-11Q2-2 11 0Q2 2 0 11Q-2 2-11 0Q-2-2 0-11Z"/>`;
const lid=x=>`<ellipse cx="${x}" cy="273" rx="10.5" ry="9.5" fill="url(#dasha-fur)"/>`;
// Vector layers drawn in the scene's own 1000x650 frame: Dasha's expressions, time-of-day light, night sky and the stall lantern.
const sceneOverlay=`<svg class="dasha-art-overlay" viewBox="0 0 1000 650" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false"><defs><linearGradient id="dasha-fur" gradientUnits="userSpaceOnUse" x1="0" y1="185" x2="0" y2="383"><stop stop-color="#ed9b58"/><stop offset="1" stop-color="#c96f43"/></linearGradient><linearGradient id="dasha-night-tint" x2="0" y2="1"><stop stop-color="#16215a" stop-opacity=".78"/><stop offset=".55" stop-color="#223a6c" stop-opacity=".6"/><stop offset="1" stop-color="#1b2f5c" stop-opacity=".56"/></linearGradient><radialGradient id="dasha-lamp-glow"><stop stop-color="#ffd48a" stop-opacity=".58"/><stop offset=".5" stop-color="#ffc56e" stop-opacity=".24"/><stop offset="1" stop-color="#ffc56e" stop-opacity="0"/></radialGradient></defs>
<g class="dasha-face"><g class="dasha-face-blink">${lid(219.5)}${lid(288.5)}<path d="M210 275q9.5 6 19 0M279 275q9.5 6 19 0" fill="none" stroke="#603f35" stroke-width="4" stroke-linecap="round"/></g><g class="dasha-face-squint"><path d="M208 274.5a11.5 10.5 0 0 1 23 0ZM277 274.5a11.5 10.5 0 0 1 23 0Z" fill="url(#dasha-fur)"/><path d="M209 274.5h21M278 274.5h21" stroke="#603f35" stroke-width="3.5" stroke-linecap="round"/></g><g class="dasha-face-win"><g fill="#fffaf0"><circle cx="221.5" cy="270" r="2.3"/><circle cx="290.5" cy="270" r="2.3"/><circle cx="217.5" cy="276.5" r="1.2"/><circle cx="286.5" cy="276.5" r="1.2"/></g><ellipse cx="252" cy="343" rx="8.5" ry="9.5" fill="#6b3d36"/><ellipse cx="252" cy="348" rx="5.5" ry="3.6" fill="#e58c86"/><g class="dasha-sparks" fill="#ffe7a1">${star(122,196)}${star(384,188,.8)}${star(392,252,.6)}${star(108,262,.55)}</g></g><g class="dasha-face-lose">${lid(219.5)}<path d="M209.5 278q10-10 20 0" fill="none" stroke="#603f35" stroke-width="4" stroke-linecap="round"/><path d="M246 337q6 16 12 0Z" fill="#e58c86" stroke="#a4574a" stroke-width="1.6" stroke-linejoin="round"/></g></g>
<rect class="dasha-tint dasha-tint-dawn" width="1000" height="650" fill="#f2b3a0"/><rect class="dasha-tint dasha-tint-dusk" width="1000" height="650" fill="#f0995a"/><rect class="dasha-tint dasha-tint-night" width="1000" height="650" fill="url(#dasha-night-tint)"/>
<g class="dasha-night-sky"><g fill="#fff6d8"><circle cx="128" cy="62" r="2.2"/><circle cx="214" cy="118" r="1.6"/><circle cx="262" cy="40" r="2"/><circle cx="58" cy="150" r="1.6"/><circle cx="182" cy="182" r="1.4"/><circle cx="402" cy="78" r="1.8"/><circle cx="520" cy="34" r="2.2"/><circle cx="566" cy="88" r="1.4"/><circle cx="762" cy="44" r="1.8"/><circle cx="868" cy="80" r="2.2"/><circle cx="948" cy="30" r="1.6"/><circle cx="330" cy="26" r="1.4"/></g><circle cx="660" cy="58" r="44" fill="#f3e8a8" opacity=".16"/><circle cx="660" cy="58" r="25" fill="#f7f0c6"/><path d="M672 37a25 25 0 0 1-7 45 22 22 0 0 0 7-45Z" fill="#d8cf9f" opacity=".7"/><circle cx="652" cy="52" r="4" fill="#e6dcae"/><circle cx="660" cy="68" r="2.6" fill="#e6dcae"/></g>
<g class="dasha-lamp"><ellipse class="dasha-lamp-glow" cx="360" cy="380" rx="400" ry="270" fill="url(#dasha-lamp-glow)"/><path d="M452 205v30" stroke="#5c4636" stroke-width="3"/><path d="M438 238h28l-4-6h-20Z" fill="#6b5240"/><rect x="439" y="238" width="26" height="32" rx="7" fill="#ffd27a"/><rect x="439" y="238" width="26" height="32" rx="7" fill="none" stroke="#7a5b42" stroke-width="3"/><path d="M452 241v26" stroke="#7a5b42" stroke-width="2" opacity=".55"/><path d="M441 270h22l-3 5h-16Z" fill="#6b5240"/><circle cx="452" cy="254" r="22" fill="#ffe2a0" opacity=".35"/></g></svg>`;
const positions=[0,1,2];
const reducedMotion=()=>!!globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
const pause=ms=>new Promise(resolve=>setTimeout(resolve,reducedMotion()?Math.min(ms,80):ms));

export function mountDashaGame(host,{getState,command,onBack,isCommandPending=()=>false,rng}){
 let selectedStake=10,pending=false,phase='idle',visualSlots=[0,1,2],destroyed=false,animationToken=0,revealedId=null,chosenRoundId=null;
 host.replaceChildren();host.className='dasha-game-view';host.hidden=false;host.setAttribute('aria-label','Лисий фокус с Дашей');
 host.innerHTML=`${cupSymbol}<div class="dasha-page"><header class="dasha-masthead"><div class="dasha-brand-mark" aria-hidden="true">${logoSvg}</div><div class="dasha-mast-title"><span class="dasha-eyebrow">Дашин деревенский прилавок</span><h1>Лисий фокус</h1></div><button class="dasha-back qw-btn secondary" type="button">‹ В деревню</button></header><div class="dasha-layout"><section class="dasha-stage-card"><div class="dasha-scene"><div class="dasha-art-frame"><img class="dasha-scene-art" src="/app/farm/assets/dasha-scene.svg" alt="Лиса Даша у уютного деревянного прилавка на фоне деревни" draggable="false">${sceneOverlay}</div><div class="dasha-speech" aria-live="polite">А ну-ка, угадаешь мой секрет?</div><div class="dasha-playfield" role="group" aria-label="Три одинаковых стаканчика"><div class="dasha-pick-hint" aria-hidden="true">Нажми на стаканчик</div><div class="dasha-carrot" aria-hidden="true">${carrotSvg}</div><button class="dasha-cup" type="button" data-cup="0" aria-label="Выбрать левый стаканчик" disabled><span class="dasha-cup-art" aria-hidden="true"><svg viewBox="0 0 118 137"><use href="#dasha-cup"/></svg></span></button><button class="dasha-cup" type="button" data-cup="1" aria-label="Выбрать средний стаканчик" disabled><span class="dasha-cup-art" aria-hidden="true"><svg viewBox="0 0 118 137"><use href="#dasha-cup"/></svg></span></button><button class="dasha-cup" type="button" data-cup="2" aria-label="Выбрать правый стаканчик" disabled><span class="dasha-cup-art" aria-hidden="true"><svg viewBox="0 0 118 137"><use href="#dasha-cup"/></svg></span></button><div class="dasha-coin-pop" aria-hidden="true"></div><div class="dasha-confetti" aria-hidden="true">${'<i></i>'.repeat(14)}</div><div class="dasha-drop" aria-hidden="true">${dropCarrotSvg}</div><div class="dasha-curtain" aria-hidden="true"><div class="dasha-curtain-fabric"><span>Секрет Даши</span></div><i class="dasha-puff"></i></div></div><div class="dasha-scene-caption" aria-hidden="true">У деревенского прилавка<span class="dasha-cap-day"> · ясный день</span><span class="dasha-cap-dawn"> · утренний свет</span><span class="dasha-cap-dusk"> · вечерний свет</span><span class="dasha-cap-night"> · ночной фонарик</span></div></div></section><aside class="dasha-side"><section class="dasha-card dasha-intro"><span class="dasha-eyebrow">Игра с Дашей</span><h2>Где морковка?</h2><p>Даша прячет морковку и перемешивает стаканчики за ширмой — уследить нельзя, это чистая угадайка. Шанс 1 из 3, выплата ×2,7 вместе со ставкой.</p></section><section class="dasha-card dasha-wager" aria-label="Ставка и баланс"><div class="dasha-balance-row"><span>Баланс фермы</span><strong><span class="dasha-coin" aria-hidden="true">●</span><span data-role="balance">—</span></strong></div><h3>Поставь монеты</h3><div class="dasha-stakes" role="group" aria-label="Выбор ставки"></div><div class="dasha-payout"><span>Выплата при удаче</span><strong data-role="payout">—</strong></div><p class="dasha-foot-note">${ruleIcon}<span>Шанс 1 из 3. Не выберешь за 10 минут — сработает заранее сохранённый случайный выбор. Ставка не возвращается.</span></p><button class="dasha-primary" data-role="action" type="button">Играть с Дашей</button><p class="dasha-round-status" data-role="status" role="status" aria-live="polite"></p></section></aside></div></div>`;
 const $=s=>host.querySelector(s),cups=[...host.querySelectorAll('.dasha-cup')],stakesBox=$('.dasha-stakes'),balanceNode=$('[data-role="balance"]'),payoutNode=$('[data-role="payout"]'),statusNode=$('[data-role="status"]'),speech=$('.dasha-speech'),action=$('[data-role="action"]'),carrot=$('.dasha-carrot'),curtain=$('.dasha-curtain');
 // Decorative extras; absent nodes (tests, older markup) are simply skipped.
 const drop=$('.dasha-drop'),coinPop=$('.dasha-coin-pop'),confetti=$('.dasha-confetti'),balanceBox=balanceNode?.parentElement||null;
 const say=(message,caption=message)=>{speech.textContent=message;statusNode.textContent=caption;};
 const setMood=mood=>{host.dataset.mood=mood;};
 const wager=()=>getState()?.wager||null;
 const cupAt=slot=>cups.find(c=>Number(c.dataset.position)===slot);
 function setCupPositions(){cups.forEach((cup,i)=>{const slot=visualSlots[i];cup.classList.remove(...positions.map(value=>`dasha-position-${value}`));cup.classList.add(`dasha-position-${slot}`);cup.dataset.position=String(slot);cup.setAttribute('aria-label',`Выбрать ${SLOT_NAMES[slot]} стаканчик`);});}
 function setSlotClass(node,slot){if(!node)return;node.classList.remove(...positions.map(value=>`dasha-slot-${value}`));node.classList.add(`dasha-slot-${slot}`);}
 function setCarrotPosition(slot){setSlotClass(carrot,slot);}
 function clearEffects(){drop?.classList.remove('dasha-dropping');coinPop?.classList.remove('dasha-pop','dasha-pop-win','dasha-pop-lose');confetti?.classList.remove('dasha-burst');balanceBox?.classList.remove('dasha-bump');curtain.classList.remove('dasha-rustle-a','dasha-rustle-b');}
 function resetCups(){cups.forEach(c=>c.classList.remove('dasha-lift','dasha-peek','dasha-chosen'));}
 function restoreScene(){animationToken++;revealedId=null;phase='idle';visualSlots=[0,1,2];curtain.classList.remove('dasha-closed');carrot.classList.remove('dasha-visible','dasha-shown','dasha-found');setCarrotPosition(1);clearEffects();resetCups();setCupPositions();}
 async function reveal(result,animate){
  const token=++animationToken;revealedId=result.id;phase=animate?'reveal':'result';
  visualSlots=[0,1,2];setCupPositions();curtain.classList.remove('dasha-closed');clearEffects();resetCups();
  const winning=Number.isInteger(result.winning_cup)?result.winning_cup:0,chosen=Number.isInteger(result.chosen_cup)?result.chosen_cup:null,[first,rest]=dashaRevealOrder(chosen);
  setCarrotPosition(winning);carrot.classList.remove('dasha-shown','dasha-found');carrot.classList.add('dasha-visible');
  const showCarrot=()=>carrot.classList.add('dasha-shown',...(animate?['dasha-found']:[]));
  if(chosen!==null)cupAt(chosen)?.classList.add('dasha-chosen');
  first.forEach(slot=>cupAt(slot)?.classList.add('dasha-lift'));if(first.includes(winning))showCarrot();
  if(animate){setMood('reveal');say('Поднимаем твой стаканчик…','Смотрим, что под твоим стаканчиком.');await pause(result.won?520:760);if(destroyed||token!==animationToken)return;}
  rest.forEach(slot=>cupAt(slot)?.classList.add('dasha-lift'));if(!first.includes(winning))showCarrot();
  setMood(result.won?'win':'lose');
  if(animate){
   if(coinPop){const amount=result.won?result.payout:result.stake;coinPop.textContent=`${result.won?'+':'−'}${new Intl.NumberFormat('ru-RU').format(Number(amount)||0)}`;setSlotClass(coinPop,result.won?winning:(chosen??winning));coinPop.classList.add('dasha-pop',result.won?'dasha-pop-win':'dasha-pop-lose');}
   if(result.won){setSlotClass(confetti,winning);confetti?.classList.add('dasha-burst');balanceBox?.classList.add('dasha-bump');}
  }
  phase='result';render();
 }
 function render(){
  if(destroyed)return;const state=getState()||{},w=wager(),busy=pending||!!isCommandPending();selectedStake=dashaSelectedStake(w,selectedStake);const view=dashaViewState(w,state.coins,selectedStake,busy),active=view.active,result=view.result;
  balanceNode.textContent=new Intl.NumberFormat('ru-RU').format(view.coins);const displayedPayout=dashaPayoutDisplay(active,view.payout);payoutNode.textContent=Number.isSafeInteger(displayedPayout)&&displayedPayout>0?coinsText(displayedPayout):'—';
  const availableStakes=Array.isArray(w?.rules?.stakes)?w.rules.stakes:STAKES;
  stakesBox.replaceChildren(...availableStakes.map(value=>{const b=document.createElement('button');b.type='button';b.className=`dasha-stake${selectedStake===value?' dasha-selected':''}`;b.textContent=String(value);b.dataset.stake=String(value);b.setAttribute('aria-pressed',String(selectedStake===value));b.disabled=!!active||busy||value>(Number(w?.earned_balance)||0)||value>(Number(w?.remaining_stake)||0);b.addEventListener('click',()=>{if(b.disabled)return;selectedStake=value;render();});return b;}));
  if(active){
   revealedId=null;action.textContent=busy?'Подтверждаем…':'Выбери стаканчик на прилавке';action.disabled=true;action.classList.add('dasha-await');action.setAttribute('aria-label','Выбери один из трёх одинаковых стаканчиков');carrot.classList.remove('dasha-visible','dasha-shown','dasha-found');
   if(!['pick','settling','shuffle','starting'].includes(phase)){restoreScene();phase='pick';say('Раунд восстановлен. Выбери один стаканчик.','Ставка уже списана. Можно выбрать стаканчик; после 10 минут сервер подведёт итог автоматически.');}
   if(phase==='pick')setMood(busy?'wait':'pick');else if(phase==='settling')setMood('wait');
   cups.forEach(c=>c.disabled=busy||phase!=='pick');return;
  }
  action.classList.remove('dasha-await');action.removeAttribute('aria-label');cups.forEach(c=>c.disabled=true);
  if(result){
   if(revealedId!==result.id)reveal(result,phase==='settling'||chosenRoundId===result.id);
   action.textContent=busy?'Подтверждаем…':'Ещё раунд';action.disabled=busy||!w?.eligible||Number(w?.earned_balance)<selectedStake||Number(w?.remaining_stake)<selectedStake;
   if(phase==='result'){const escrow=Number(result.pending_payout)||0;const outcome=result.won?(escrow>0?`Часть выигрыша — ${coinsText(escrow)} — будет зачислена, когда освободится место на балансе.`:`Выплата ${coinsText(result.payout)} начислена, включая ставку.`):`Ставка ${coinsText(result.stake)} осталась у Даши. Можно сыграть ещё.`;say(result.won?'Ах! Морковка нашлась — забирай выигрыш!':'Хи-хи! В этот раз морковка была здесь.',outcome);}
  }
  else{
   if((phase!=='idle'&&phase!=='starting')||revealedId!==null)restoreScene();setMood('idle');
   action.textContent=busy?'Подтверждаем…':'Играть с Дашей';action.disabled=!view.canStart;const reason=w?.reason,stakeReason=selectedStake>(Number(w?.remaining_stake)||0)?'На сегодня больше нельзя поставить монеты.':selectedStake>(Number(w?.earned_balance)||0)?'Для этой ставки не хватает заработанных монет.':view.payout===null?'Обнови условия игры, чтобы увидеть выплату.':'Выбери ставку и начни раунд.',escrow=Number(w?.pending_payout)||0;const message=reason&&!w?.eligible?dashaReasonText(reason):stakeReason;const detail=escrow>0?`${message} Часть выигрыша — ${coinsText(escrow)} — будет зачислена, когда освободится место на балансе.`:message;say(detail,detail);
  }
 }
 async function animateNewRound(){
  restoreScene();const token=++animationToken,alive=()=>!destroyed&&token===animationToken;
  phase='shuffle';cups.forEach(c=>c.disabled=true);setMood('hide');curtain.classList.add('dasha-closed');
  say('Смотри: морковка прячется за ширму!','Ставка списана. Даша прячет морковку за ширмой.');
  await pause(560);if(!alive())return;
  drop?.classList.add('dasha-dropping');await pause(820);if(!alive())return;drop?.classList.remove('dasha-dropping');
  setMood('shuffle');say('Шурх-шурх… Не подглядывай!','Даша перемешивает стаканчики за ширмой — уследить нельзя.');
  let flip=false;
  for(const step of dashaShuffleSteps(rng)){
   curtain.style?.setProperty('--dasha-rustle-x',`${step.x}%`);curtain.style?.setProperty('--dasha-tilt',String(step.tilt));curtain.style?.setProperty('--dasha-rustle-ms',`${step.ms}ms`);
   curtain.classList.remove(flip?'dasha-rustle-a':'dasha-rustle-b');curtain.classList.add(flip?'dasha-rustle-b':'dasha-rustle-a');flip=!flip;
   await pause(step.ms);if(!alive())return;
  }
  curtain.classList.remove('dasha-closed','dasha-rustle-a','dasha-rustle-b');
  phase='pick';setMood('pick');say('Готово! Где же морковка?','Нажми на любой стаканчик. Шанс 1 из 3.');render();
 }
 async function start(){if(pending||isCommandPending()||!dashaViewState(wager(),getState()?.coins,selectedStake,false).canStart)return;pending=true;phase='starting';render();try{const ok=await command('wager_start',{stake:selectedStake});pending=false;const started=!!(ok&&wager()?.active);phase=started?'shuffle':phase==='starting'?(revealedId?'result':'idle'):phase;render();if(started)await animateNewRound();}finally{pending=false;if(phase==='starting')phase=revealedId?'result':'idle';render();}}
 function choiceRejected(roundId){const active=wager()?.active;if(isCommandPending()||active?.id!==roundId)return false;phase='pick';chosenRoundId=null;resetCups();say('Сервер не принял выбор. Попробуй ещё раз.','Раунд сохранён; выбери стаканчик ещё раз.');render();return true;}
 async function choose(cup){if(pending||isCommandPending()||!wager()?.active||phase!=='pick')return;const roundId=wager().active.id,position=Number(cup.dataset.position);if(!Number.isInteger(position)||position<0||position>2)return;pending=true;phase='settling';chosenRoundId=roundId;cups.forEach(c=>c.disabled=true);cup.classList.add('dasha-chosen','dasha-peek');setMood('wait');say('Стаканчик выбран… Даша проверяет.','Ждём подтверждения сервера.');render();let accepted=false;try{accepted=await command('wager_choose',{round_id:roundId,cup:position});}finally{pending=false;const active=wager()?.active;if(choiceFailureKeepsRound(accepted,isCommandPending(),active?.id,roundId))choiceRejected(roundId);render();}}
 action.addEventListener('click',()=>{if(wager()?.active)return;start();});cups.forEach(c=>c.addEventListener('click',()=>choose(c)));$('.dasha-back').addEventListener('click',onBack);host.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();onBack();}});
 setCupPositions();render();host.querySelector('.dasha-back').focus({preventScroll:true});
 return {render,choiceRejected,destroy(){destroyed=true;animationToken++;host.replaceChildren();host.hidden=true;}};
}
