// Oleg's chime ("Перезвон с Олегом"): listen to a melody of four bells and repeat it. Three rounds of 3, 4 and 5 notes.
// The server (qw_farm/oleg.py) owns the melodies, the rounds and the once-a-day reward; this view only plays and collects taps.
const BELL_NAMES=['Первый колокольчик, красный','Второй колокольчик, золотой','Третий колокольчик, зелёный','Четвёртый колокольчик, синий'];
const FREQUENCIES=[523.25,659.25,783.99,987.77];

export function olegPlural(n){const a=n%10,b=n%100;return a===1&&b!==11?'нота':a>=2&&a<=4&&(b<12||b>14)?'ноты':'нот';}

export function olegViewState(game){
 const raw=game?.active||null,rounds=Array.isArray(game?.rounds)&&game.rounds.length?game.rounds:[3,4,5];
 const sequence=Array.isArray(raw?.sequence)&&raw.sequence.every(n=>Number.isInteger(n)&&n>=0&&n<4)?raw.sequence.slice():null;
 const active=raw&&sequence&&Number.isInteger(raw.round)?{runId:raw.run_id,round:raw.round,rounds:Number(raw.rounds)||rounds.length,notes:sequence.length,sequence}:null;
 const reward=game?.next_reward||{};
 return {active,rounds,rewardedToday:!!game?.rewarded_today,coins:Number(reward.coins)||0,xp:Number(reward.xp)||0,lastResult:game?.last_result||null};
}

// What the server did with a submitted round, read from the projection that came back.
export function olegAnswerOutcome(game,runId,round){
 const view=olegViewState(game);
 if(view.active&&view.active.runId===runId)return view.active.round>round?'next':'mismatch';
 if(!view.active&&view.lastResult?.run_id===runId)return 'finished';
 return 'lost';
}

// Oleg's face on the stage: sings his melody, listens to yours, is sheepish after a slip and beams after a round.
export function olegMood(phase,finished){return finished||phase==='next'?'happy':phase==='show'?'sing':phase==='retry'?'oops':phase==='input'||phase==='sending'?'listen':'';}

export function olegResultText(result){
 if(!result)return '';
 return result.rewarded?`Три мелодии сыграны! +${Number(result.coins)||0} монет и +${Number(result.xp)||0} опыта.`:'Три мелодии сыграны! Награда за сегодня уже получена — приходи завтра.';
}

const logoSvg='<svg viewBox="0 0 48 48" aria-hidden="true"><path d="M7 31 12 16l8 6 7-13 5 13 9-4-4 18H12Z" fill="#d6804c" stroke="#875235" stroke-width="2"/><path d="M14 32q10 6 21 0v8H14Z" fill="#f4e5bf"/><circle cx="28" cy="25" r="2" fill="#293a2d"/><path d="m35 27 9 4-9 3Z" fill="#e6af41"/></svg>';
// The stage is drawn here, not loaded as an image, so its bells light up with the buttons and Oleg can react.
// Farm palette (scene.js, scene_buildings.js): pastel fills, soft shading by darker fills, no dark outlines.
// The house is the farm's own solid: two wall faces with the gable roof seated exactly on their top edges.
// Night colours live in oleg-game.css under :root[data-farm-theme=night]; classes name what may be recoloured.
const SCENE_BELLS=[[612,'#e9927a','#cf7461'],[716,'#f1ca71','#d6a954'],[820,'#a2c78f','#80a873'],[924,'#9cc4d2','#79a3b6']];
function sceneBell([x,fill,shade],i){
 return `<g class="os-bell" data-scene-bell="${i}" style="transform-origin:${x}px 398px"><circle class="os-glow" cx="${x}" cy="456" r="70" fill="url(#os-glow)"/>`
  +`<path d="M${x} 398V420" stroke="#9b7650" stroke-width="5" stroke-linecap="round"/>`
  +`<path d="M${x-19} 430Q${x-21} 419 ${x} 417Q${x+21} 419 ${x+19} 430L${x+26} 474Q${x+35} 485 ${x+34} 493H${x-34}Q${x-35} 485 ${x-26} 474Z" fill="${fill}"/>`
  +`<path d="M${x+6} 418Q${x+21} 420 ${x+19} 430L${x+26} 474Q${x+35} 485 ${x+34} 493H${x+10}Q${x+16} 460 ${x+6} 418Z" fill="${shade}" opacity=".55"/>`
  +`<path d="M${x-10} 428Q${x-14} 450 ${x-18} 470" stroke="#fff8e4" stroke-width="5" stroke-linecap="round" fill="none" opacity=".7"/>`
  +`<ellipse cx="${x}" cy="493" rx="34" ry="5" fill="${shade}"/><circle cx="${x}" cy="500" r="7" fill="#f2d48c"/></g>`;
}
export function olegSceneSvg(){
 return `<svg class="oleg-scene-art" viewBox="0 0 1100 690" role="img" aria-label="Петух Олег в жилетке у деревянной стойки с четырьмя колокольчиками; позади старый дуб и домик" focusable="false">
<defs><linearGradient id="os-sky" x2="0" y2="1"><stop class="os-sky-top" offset="0" stop-color="#cfe3d4"/><stop class="os-sky-bottom" offset="1" stop-color="#f6edcc"/></linearGradient>
<radialGradient id="os-glow"><stop offset="0" stop-color="#fffbe6"/><stop offset=".5" stop-color="#ffeaa0" stop-opacity=".88"/><stop offset="1" stop-color="#ffe08a" stop-opacity="0"/></radialGradient></defs>
<rect width="1100" height="690" fill="url(#os-sky)"/>
<g class="os-sun"><circle cx="870" cy="104" r="74" fill="#fbecb6" opacity=".45"/><circle cx="870" cy="104" r="46" fill="#f9e3a1"/></g>
<g class="os-moon"><circle cx="870" cy="104" r="64" fill="#f1eac9" opacity=".14"/><circle cx="870" cy="104" r="38" fill="#f1eac9"/><circle cx="858" cy="94" r="8" fill="#e3d9b3"/><circle cx="884" cy="116" r="6" fill="#e3d9b3"/><circle cx="878" cy="88" r="4" fill="#e3d9b3"/></g>
<g class="os-stars" fill="#f6eecb"><circle cx="120" cy="70" r="3"/><circle cx="260" cy="40" r="2.4"/><circle cx="420" cy="88" r="2.6"/><circle cx="560" cy="36" r="3"/><circle cx="690" cy="76" r="2.2"/><circle cx="1010" cy="54" r="2.8"/><circle cx="760" cy="160" r="2"/><circle cx="330" cy="150" r="2"/></g>
<path class="os-hill-far" d="M0 330Q200 266 420 314T820 298T1100 286V690H0Z" fill="#bcd3a1"/>
<path class="os-hill-mid" d="M0 424Q250 362 520 404C640 432 724 318 850 300C952 286 1040 296 1100 310V690H0Z" fill="#a3c587"/>
<g class="os-oak"><ellipse cx="176" cy="474" rx="74" ry="12" fill="#5f7f4f" opacity=".22"/>
<path class="os-trunk" d="M148 474C154 430 142 382 152 330H190C196 382 186 430 200 474Z" fill="#a8835a"/><path class="os-trunk-shade" d="M176 330H190C196 382 186 430 200 474H180C186 430 182 380 176 330Z" fill="#8f6c47"/>
<g class="os-crown" fill="#82a86b"><circle cx="118" cy="276" r="68"/><circle cx="190" cy="236" r="78"/><circle cx="252" cy="292" r="58"/><circle cx="94" cy="326" r="48"/><circle cx="176" cy="318" r="66"/></g>
<g class="os-crown-shade" fill="#6f955d"><ellipse cx="150" cy="352" rx="78" ry="26"/><ellipse cx="248" cy="330" rx="40" ry="16"/></g>
<g class="os-crown-light" fill="#9cbf80"><circle cx="164" cy="208" r="40"/><circle cx="104" cy="252" r="30"/><circle cx="236" cy="262" r="26"/></g></g>
<g class="os-house"><ellipse cx="932" cy="378" rx="128" ry="24" fill="#5f7f4f" opacity=".24"/><ellipse cx="934" cy="381" rx="92" ry="13" fill="#56744a" opacity=".22"/>
<path class="os-roof-back" d="M818 251 912 204 974 166 880 213Z" fill="#94b39a"/>
<path class="os-wall-lit" d="M825 325 935 380 935 302 825 247Z" fill="#e8d9ae"/>
<path class="os-wall-lit" d="M825 247 935 302 880 213Z" fill="#e8d9ae"/>
<path class="os-wall-dark" d="M935 380 1025 335 1025 257 935 302Z" fill="#cdbf98"/>
<path d="M825 325 935 380 1025 335 1025 327 935 372 825 317Z" fill="#bdb398"/>
<path class="os-glass" d="M864 290 896 306 896 332 864 316Z" fill="#abc9c7"/><path d="M880 298V324M864 303 896 319" stroke="#f3ead2" stroke-width="3"/>
<ellipse class="os-glass" cx="880" cy="262" rx="9" ry="9" fill="#abc9c7"/>
<path d="M961 367 988 353 988 310 961 324Z" fill="#8f7556"/><circle cx="982" cy="336" r="2.6" fill="#e9d29a"/>
<path class="os-glass" d="M1000 330 1016 322 1016 300 1000 308Z" fill="#a3c1bf"/>
<path class="os-roof" d="M929 309 1031 258 976 160 874 211Z" fill="#7c9d83"/>
<path d="M929 309 1031 258 1031 266 929 317Z" fill="#668a70"/>
<path d="M818 251 880 211 935 306" fill="none" stroke="#d9e6d8" stroke-width="7" stroke-linejoin="round" stroke-linecap="round"/>
<path d="M950 178 966 170V140L950 148Z" fill="#c69a7b"/><path d="M966 170 976 175V145L966 140Z" fill="#a98063"/><path d="M950 148 960 143 976 145 966 140Z" fill="#d9b394"/></g>
<path class="os-ground" d="M0 520Q300 478 600 508T1100 498V690H0Z" fill="#8fba73"/>
<ellipse class="os-trodden" cx="700" cy="606" rx="340" ry="42" fill="#dccb94" opacity=".55"/>
<rect class="os-night-tint" width="1100" height="690" fill="#22304d" opacity="0"/>
<g class="os-stand"><ellipse cx="770" cy="606" rx="270" ry="17" fill="#4f6b45" opacity=".22"/>
<rect x="538" y="384" width="24" height="220" rx="10" fill="#b88a5b"/><rect x="538" y="384" width="9" height="220" rx="4" fill="#cfa173"/>
<rect x="978" y="384" width="24" height="220" rx="10" fill="#b88a5b"/><rect x="978" y="384" width="9" height="220" rx="4" fill="#cfa173"/>
<rect x="522" y="372" width="496" height="28" rx="14" fill="#c99a62"/><rect x="530" y="374" width="480" height="8" rx="4" fill="#ddb37d"/><rect x="530" y="392" width="480" height="6" rx="3" fill="#ad8152"/>
<g class="os-lantern"><path d="M550 372V356" stroke="#7c6448" stroke-width="4"/><rect x="538" y="324" width="24" height="32" rx="7" fill="#e7cf98"/><rect class="os-lamp" x="543" y="330" width="14" height="20" rx="5" fill="#f3e3b8"/><path d="M536 324H564L556 314H544Z" fill="#7c9d83"/></g>
${SCENE_BELLS.map(sceneBell).join('')}</g>
<g class="os-oleg"><ellipse cx="340" cy="606" rx="116" ry="16" fill="#4f6b45" opacity=".22"/>
<g fill="none" stroke="#dba556" stroke-linecap="round" stroke-linejoin="round"><path d="M312 548 302 600M368 548 374 600" stroke-width="12"/><path d="M302 600H278M302 600 290 586M302 600H322M374 600H352M374 600 388 586M374 600H396" stroke-width="8"/></g>
<path d="M262 452C190 420 160 330 202 276 226 330 254 378 286 418Z" fill="#6fa483"/>
<path d="M258 470C170 470 118 402 132 340 172 392 218 430 282 444Z" fill="#88b591"/>
<path d="M268 440C228 382 236 300 282 262 288 318 292 378 306 422Z" fill="#dd9466"/>
<ellipse cx="334" cy="470" rx="108" ry="94" fill="#f4eed6"/>
<path class="os-vest" d="M302 396Q366 380 428 410Q450 470 424 540Q362 572 300 546Q282 470 302 396Z" fill="#dc8e64"/>
<path d="M366 392 398 446 426 408Q400 388 366 392Z" fill="#f4eed6"/>
<path d="M398 446 410 540" stroke="#c87a52" stroke-width="3" stroke-linecap="round" opacity=".6"/><circle cx="404" cy="476" r="5.5" fill="#f6d98c"/><circle cx="406" cy="508" r="5.5" fill="#f6d98c"/>
<path d="M368 396C382 360 388 340 398 318L462 330C458 360 444 394 432 424Z" fill="#f7f1dc"/>
<g class="os-head"><g fill="#de6b61"><circle cx="397" cy="276" r="20"/><circle cx="422" cy="263" r="23"/><circle cx="447" cy="274" r="19"/><circle cx="463" cy="292" r="14"/></g>
<circle cx="424" cy="330" r="58" fill="#f8f2df"/><ellipse cx="410" cy="350" rx="15" ry="9" fill="#f3b7a6" opacity=".6"/>
<path class="os-beak-low" d="M470 338H500L470 352Z" fill="#d99c48"/><path d="M470 320 508 334 470 340Z" fill="#edb85e"/>
<ellipse cx="474" cy="364" rx="11" ry="16" fill="#de6b61"/>
<g class="os-eye-open"><circle cx="444" cy="318" r="8.5" fill="#3d4b3e"/><circle cx="447" cy="315" r="2.8" fill="#fff"/></g>
<path class="os-eye-happy" d="M434 322Q444 308 454 322" fill="none" stroke="#3d4b3e" stroke-width="5" stroke-linecap="round"/>
<g class="os-eye-oops" fill="none" stroke="#3d4b3e" stroke-width="4" stroke-linecap="round"><path d="M437 311 451 325M451 311 437 325"/></g>
<path class="os-drop" d="M392 268C384 282 382 290 388 294 394 298 400 292 398 284 397 278 394 272 392 268Z" fill="#a9d4e6"/></g>
<g class="os-wing"><path d="M276 450C296 412 360 414 388 452 402 484 382 524 340 528 298 524 266 492 276 450Z" fill="#ece0bf"/>
<path d="M300 470Q330 490 368 478M298 494Q326 510 360 502" fill="none" stroke="#ddcfa8" stroke-width="5" stroke-linecap="round"/>
<path d="M378 482 516 420" stroke="#a87b52" stroke-width="9" stroke-linecap="round"/><circle cx="524" cy="416" r="15" fill="#e9c58c"/></g>
<g class="os-notes" fill="#6f957a"><path d="M512 264v-40l22-6v34" stroke="#6f957a" stroke-width="5" fill="none" stroke-linecap="round"/><ellipse cx="506" cy="266" rx="9" ry="7"/><ellipse cx="528" cy="254" rx="9" ry="7"/><path d="M560 214v-30" stroke="#6f957a" stroke-width="5" stroke-linecap="round"/><ellipse cx="554" cy="216" rx="9" ry="7"/></g></g>
</svg>`;
}

export function mountOlegGame(host,{getState,command,onBack,isCommandPending=()=>false}){
 let phase='idle',inputIndex=0,entered=[],pending=false,destroyed=false,generation=0,timer=null,soundOn=false,audio=null,finished=null;
 host.replaceChildren();host.className='oleg-game-view';host.hidden=false;host.setAttribute('aria-label','Перезвон с Олегом');
 host.innerHTML=`<div class="oleg-page"><header class="oleg-masthead"><div class="oleg-brand-mark">${logoSvg}</div><div class="oleg-mast-title"><span class="oleg-eyebrow">Деревенская музыкальная площадка</span><h1>Перезвон с Олегом</h1></div><button class="oleg-back" type="button">‹ В деревню</button></header>
<div class="oleg-layout"><section class="oleg-stage-card" aria-label="Музыкальная сцена"><div class="oleg-scene">${olegSceneSvg()}<div class="oleg-speech" aria-live="polite">Кукареку! Слушай мой перезвон.</div><div class="oleg-scene-caption">Посиделки у старого дуба · мелодия за мелодией</div></div>
<div class="oleg-bells" role="group" aria-label="Четыре колокольчика">${BELL_NAMES.map((name,i)=>`<button class="oleg-bell oleg-bell-${i+1}" type="button" data-note="${i}" aria-label="${name}" disabled><span class="oleg-bell-shape" aria-hidden="true"></span><span class="oleg-bell-label">${i+1}</span></button>`).join('')}</div></section>
<aside class="oleg-side"><section class="oleg-card oleg-panel" aria-label="Ход игры"><div class="oleg-round-head"><div><span class="oleg-eyebrow">Мелодия</span><strong data-role="round">1 / 3</strong></div><button class="oleg-sound" type="button" aria-pressed="false" aria-label="Включить звук колокольчиков">Звук выкл.</button></div>
<div class="oleg-progress" role="progressbar" aria-label="Пройдено мелодий" aria-valuemin="0" aria-valuemax="3" aria-valuenow="0"><span></span></div><p class="oleg-round-hint" data-role="hint"></p>
<button class="oleg-primary" type="button" data-role="action">Послушать Олега</button><p class="oleg-status" data-role="status" role="status" aria-live="polite"></p><div class="oleg-key-help">Можно нажимать клавиши 1–4.</div></section>
<section class="oleg-card oleg-intro"><span class="oleg-eyebrow">Игра с Олегом</span><h2>Запомни и повтори</h2><p>Олег сыграет мелодию на колокольчиках. Повтори её по памяти. В каждой следующей мелодии на ноту больше; ошибиться можно сколько угодно раз.</p><p class="oleg-reward" data-role="reward"></p></section></aside></div></div>`;
 const $=s=>host.querySelector(s),bells=[...host.querySelectorAll('.oleg-bell')],speech=$('.oleg-speech'),statusNode=$('[data-role="status"]'),action=$('[data-role="action"]'),roundNode=$('[data-role="round"]'),hintNode=$('[data-role="hint"]'),rewardNode=$('[data-role="reward"]'),progress=$('.oleg-progress'),scene=$('.oleg-scene'),sceneBells=[...host.querySelectorAll('[data-scene-bell]')],sound=$('.oleg-sound');
 const reduced=()=>typeof matchMedia==='function'&&matchMedia('(prefers-reduced-motion: reduce)').matches;
 const view=()=>olegViewState(getState());
 const busy=()=>pending||!!isCommandPending();
 const say=(line,status=line)=>{speech.textContent=line;statusNode.textContent=status;};
 const wait=(ms,run)=>new Promise(resolve=>{timer=setTimeout(()=>{timer=null;resolve(run===generation&&!destroyed);},ms);});
 function tone(index,seconds){
  if(!soundOn)return;
  try{const Ctor=globalThis.AudioContext||globalThis.webkitAudioContext;if(!Ctor)return;audio||=new Ctor();if(audio.state==='suspended')audio.resume();
   const t=audio.currentTime,osc=audio.createOscillator(),gain=audio.createGain();osc.type='sine';osc.frequency.value=FREQUENCIES[index];
   gain.gain.setValueAtTime(.0001,t);gain.gain.exponentialRampToValueAtTime(.17,t+.025);gain.gain.exponentialRampToValueAtTime(.0001,t+seconds);osc.connect(gain).connect(audio.destination);osc.start(t);osc.stop(t+seconds+.03);}catch{}
 }
 function flash(index,ms){
  const lit=[bells[index],sceneBells[index]].filter(Boolean),strike=phase==='show';lit.forEach(n=>n.classList.add('oleg-lit'));if(strike)scene?.classList.add('os-striking');tone(index,ms/1000);
  setTimeout(()=>{lit.forEach(n=>n.classList.remove('oleg-lit'));if(strike)scene?.classList.remove('os-striking');},ms);
 }
 function cancelPlayback(){generation++;if(timer!==null)clearTimeout(timer);timer=null;[...bells,...sceneBells].forEach(b=>b.classList.remove('oleg-lit'));scene?.classList.remove('os-striking');}
 function render(){
  if(destroyed)return;
  const v=view(),a=v.active,total=a?.rounds||v.rounds.length,done=finished?total:a?a.round:0,notes=a?.notes||v.rounds[0]||3;
  roundNode.textContent=`${Math.min(done+1,total)} / ${total}`;
  progress.setAttribute('aria-valuemax',String(total));progress.setAttribute('aria-valuenow',String(done));progress.firstElementChild.style.width=`${done/total*100}%`;
  hintNode.textContent=finished?'Три мелодии сыграны':`Мелодия ${Math.min(done+1,total)} · ${notes} ${olegPlural(notes)}`;
  rewardNode.textContent=v.rewardedToday?'Награда за сегодня уже получена — можно играть просто так.':`Пройди три мелодии: +${v.coins} монет и +${v.xp} опыта раз в день.`;
  bells.forEach(b=>{b.disabled=phase!=='input'||busy();});
  if(scene)scene.dataset.mood=olegMood(phase,!!finished);
  action.hidden=phase==='input';
  action.disabled=phase==='show'||busy();
  action.textContent=busy()?'Подтверждаем…':phase==='next'?'Следующая мелодия':phase==='retry'?'Послушать ещё раз':finished?'Сыграть ещё раз':'Послушать Олега';
 }
 async function play(){
  const a=view().active;if(!a||destroyed)return;
  cancelPlayback();const run=generation;phase='show';finished=null;entered=[];inputIndex=0;
  say('Слушай внимательно — вот моя мелодия!','Олег играет мелодию. Колокольчики пока закрыты.');render();
  const lit=reduced()?120:360,gap=reduced()?240:520;
  for(const note of a.sequence){flash(note,lit);if(!await wait(lit+gap,run))return;}
  phase='input';say('Теперь твоя очередь!',`Повтори ${a.notes} ${olegPlural(a.notes)} по порядку.`);render();
  bells.find(b=>!b.disabled)?.focus({preventScroll:true});
 }
 async function start(){
  if(busy())return;
  if(view().active){play();return;}
  pending=true;finished=null;render();
  let ok=false;try{ok=await command('oleg_start',{});}finally{pending=false;}
  if(destroyed)return;
  if(ok&&view().active)play();else{say('Олег пока не готов. Попробуй ещё раз.');render();}
 }
 async function submit(){
  const a=view().active;if(!a)return;
  const runId=a.runId,round=a.round,notes=entered.slice();
  pending=true;phase='sending';say('Олег прислушивается…','Проверяем мелодию.');render();
  let ok=false;try{ok=await command('oleg_answer',{run_id:runId,round,notes});}finally{pending=false;}
  if(destroyed)return;
  const outcome=ok?olegAnswerOutcome(getState(),runId,round):'failed';
  if(outcome==='next'){phase='next';say('Чудесно! Готов к мелодии посложнее?',`Мелодия ${round+1} сыграна. Нажми кнопку, когда будешь готов.`);}
  else if(outcome==='finished'){const result=view().lastResult;finished=result;phase='idle';say('Вот это слух! Кукареку, вышла прекрасная музыка!',olegResultText(result));}
  else if(outcome==='mismatch'){phase='retry';say('Ой, сбились! Давай ещё раз.','Олег услышал другую мелодию. Послушай и повтори снова.');}
  else if(outcome==='lost'){phase='idle';say('Олег начал новую игру.','Прохождение изменилось на сервере. Начни мелодию заново.');}
  else{phase='retry';say('Ответ не дошёл до Олега.','Связь прервалась. Послушай мелодию и повтори ещё раз.');}
  render();
 }
 function choose(index){
  if(phase!=='input'||busy())return;
  const a=view().active;if(!a)return;
  if(a.sequence[inputIndex]!==index){phase='retry';entered=[];inputIndex=0;say('Ой, сбились! Давай попробуем ещё раз.','Не совпало. Послушай мелодию ещё раз и повтори.');render();return;}
  flash(index,reduced()?110:180);entered.push(index);inputIndex++;
  if(inputIndex<a.notes){statusNode.textContent=`Верно: ${inputIndex} из ${a.notes}. Продолжай!`;return;}
  submit();
 }
 action.addEventListener('click',()=>{if(phase==='retry'||phase==='next')play();else start();});
 bells.forEach(b=>b.addEventListener('click',()=>choose(Number(b.dataset.note))));
 sound.addEventListener('click',()=>{soundOn=!soundOn;sound.setAttribute('aria-pressed',String(soundOn));sound.setAttribute('aria-label',soundOn?'Выключить звук колокольчиков':'Включить звук колокольчиков');sound.textContent=soundOn?'Звук вкл.':'Звук выкл.';if(soundOn)tone(0,.12);});
 $('.oleg-back').addEventListener('click',onBack);
 host.addEventListener('keydown',e=>{
  if(e.key==='Escape'){e.preventDefault();e.stopPropagation();onBack();return;}
  if(e.altKey||e.ctrlKey||e.metaKey)return;
  if(/^[1-4]$/.test(e.key)&&phase==='input'){e.preventDefault();e.stopPropagation();choose(Number(e.key)-1);}
 });
 const v=view();
 if(v.active)say('Кукареку! Продолжим с того же места?',`Сохранена мелодия ${v.active.round+1} из ${v.active.rounds}. Нажми «Послушать Олега».`);
 else say('Кукареку! Слушай мой перезвон.','Нажми кнопку, чтобы услышать мелодию.');
 render();$('.oleg-back').focus({preventScroll:true});
 return {render,destroy(){destroyed=true;cancelPlayback();try{audio?.close();}catch{}host.replaceChildren();host.hidden=true;}};
}
