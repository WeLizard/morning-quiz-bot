import {shotResult} from './ballista-physics.js';
import {cashBonusText} from './construction.js?v=20261116-building-effects';

const GAME='pukh_ballista',memory=new Map();
export function ballistaResultText(result){
 if(result?.expired)return 'Время доставки вышло. Можно начать новую.';
 if(!result)return '';
 const reward=result.reward>0?` +${result.reward} ${result.reward_kind==='vigour'?'бодрости':'монет'}.`:'';
 return `Доставлено ${result.hits} из 5 · ${'★'.repeat(result.stars)}${'☆'.repeat(3-result.stars)} · ${result.score} очков.${reward}${result.practice?' Тренировка.':''}`;
}
export function ballistaLogValid(plan,log){
 if(!Array.isArray(log)||log.length>5)return false;
 let end=0;
 return log.every((shot,i)=>{
  if(!Array.isArray(shot)||shot.length!==3||!shot.every(Number.isInteger))return false;
  const [a,p,t]=shot;if(a<15000||a>75000||p<200||p>1000||t<end+250||t>180000)return false;
  end=t+shotResult(plan.targets[i],a,p,plan.step_ms).duration;return true;
 });
}
export function mountBallistaGame(host,{getState,command,onBack,isCommandPending=()=>false,now=()=>Date.now()/1000,storageKey='farm'}){
 let disposed=false,runId=null,log=[],flight=null,raf=0,sending=false,sceneEpoch=0,theme='',aim=null;
 host.hidden=false;host.innerHTML=`<div class="ballista-page"><div class="ballista-title"><h1>Энергетос-баллиста</h1><button class="ballista-back" type="button">‹ В деревню</button></div><p class="ballista-intro">Помоги Пуху доставить пять баночек в подсвеченные окна. Оттяни баночку назад и вниз на сцене, затем отпусти. Учитывай ветер и отскок от навеса.</p><div class="ballista-layout"><div class="ballista-stage-card"><div class="ballista-scene" role="button" tabindex="0" aria-label="Оттяни баночку назад и вниз, затем отпусти для броска" aria-disabled="true"></div><p class="ballista-progress" aria-live="polite"></p></div><section class="ballista-controls" aria-label="Управление баллистой"><p class="ballista-status" role="status"></p><p class="ballista-wind"></p><div class="qw-btn-group ballista-actions"><button type="button" class="qw-btn primary ballista-start">Начать доставку</button><button type="button" class="qw-btn primary ballista-finish" hidden>Сохранить результат</button></div><details class="ballista-keyboard"><summary>Управление с клавиатуры</summary><div class="ballista-keyboard-body"><label>Угол <output class="ballista-angle-value">45°</output><input class="ballista-angle" aria-label="Угол броска" type="range" min="15" max="75" step="1" value="45"></label><label>Сила <output class="ballista-power-value">60%</output><input class="ballista-power" aria-label="Сила броска" type="range" min="200" max="1000" step="10" value="600"></label><button type="button" class="qw-btn primary ballista-shoot" hidden>Бросить</button></div></details><p class="ballista-rules">Три зачётные доставки в день, затем тренировка. За день учитывается лучший результат. Баночки игровые — напитки со склада не расходуются.</p></section></div></div>`;
 const $=s=>host.querySelector(s),stage=$('.ballista-scene'),status=$('.ballista-status'),progress=$('.ballista-progress'),wind=$('.ballista-wind'),angle=$('.ballista-angle'),power=$('.ballista-power');
 const start=$('.ballista-start'),shoot=$('.ballista-shoot'),finish=$('.ballista-finish');
 function key(id){return `mqb-ballista:${storageKey}:${id}`;}
 function save(){const value=JSON.stringify(log);memory.set(key(runId),value);try{sessionStorage.setItem(key(runId),value);}catch{}}
 function load(active){try{const value=memory.get(key(active.run_id))||sessionStorage.getItem(key(active.run_id));const parsed=value?JSON.parse(value):[];return ballistaLogValid(active.plan,parsed)?parsed:[];}catch{return [];}}
 function elapsed(active){return Math.max(0,Math.floor((now()-active.started_at)*1000));}
 function lastEnd(active){if(!log.length)return 0;const i=log.length-1;return log[i][2]+shotResult(active.plan.targets[i],log[i][0],log[i][1],active.plan.step_ms).duration;}
 async function loadScene(){
  const next=document.documentElement.dataset.farmTheme==='night'?'night':'day';if(theme===next)return;theme=next;const epoch=++sceneEpoch;
  try{const response=await fetch(`/app/farm/assets/pukh-ballista-${next==='day'?'scene':'night'}.svg`);if(!response.ok)throw new Error('scene');const svg=await response.text();if(disposed||epoch!==sceneEpoch)return;stage.innerHTML=svg;paint();}
  catch{if(!disposed&&epoch===sceneEpoch){theme='';stage.textContent='Не удалось загрузить сцену. Проверь соединение и открой игру снова.';}}
 }
 function projectile(x=60,y=500,hidden=false){const n=stage.querySelector('#pb-projectile');if(n){n.setAttribute('transform',`translate(${x-60} ${y-500})`);n.style.visibility=hidden?'hidden':'visible';}}
 function guideNode(){
  const ball=stage.querySelector('#pb-projectile');if(!ball)return null;
  let guide=stage.querySelector('#pb-aim-guide');
  if(!guide){guide=document.createElementNS('http://www.w3.org/2000/svg','g');guide.id='pb-aim-guide';guide.setAttribute('aria-hidden','true');const line=document.createElementNS('http://www.w3.org/2000/svg','line');line.setAttribute('x1','82');line.setAttribute('y1','478');line.setAttribute('stroke','#245c3c');line.setAttribute('stroke-width','6');line.setAttribute('stroke-dasharray','10 9');line.setAttribute('stroke-linecap','round');const dot=document.createElementNS('http://www.w3.org/2000/svg','circle');dot.setAttribute('r','9');dot.setAttribute('fill','#245c3c');guide.append(line,dot);ball.parentNode.insertBefore(guide,ball);}
  return guide;
 }
 function placeGuide(angleMilli,powerValue,opacity){
  const guide=guideNode();if(!guide)return;
  const angle=angleMilli/1000*Math.PI/180,length=190+(powerValue-200)*.25,gx=82+length*Math.cos(angle),gy=478-length*Math.sin(angle);
  guide.querySelector('line').setAttribute('x2',String(gx));guide.querySelector('line').setAttribute('y2',String(gy));guide.querySelector('circle').setAttribute('cx',String(gx));guide.querySelector('circle').setAttribute('cy',String(gy));
  guide.style.visibility='visible';guide.style.opacity=String(opacity);
 }
 function showKeyboardAim(){
  if(aim)return;
  const guide=stage.querySelector('#pb-aim-guide'),open=$('.ballista-keyboard').open;
  if(flight||!open||shoot.hidden||shoot.disabled){if(guide)guide.style.visibility='hidden';return;}
  placeGuide(Number(angle.value)*1000,Number(power.value),.5);
 }
 function aimVisual(back=0,down=0,angleMilli=45000,powerValue=600){
  const ball=stage.querySelector('#pb-projectile');if(!ball)return;
  let band=stage.querySelector('#pb-aim-band');
  if(!band){band=document.createElementNS('http://www.w3.org/2000/svg','g');band.id='pb-aim-band';for(const [x1,y1] of [[48,490],[79,491]]){const line=document.createElementNS('http://www.w3.org/2000/svg','line');line.setAttribute('x1',String(x1));line.setAttribute('y1',String(y1));line.setAttribute('stroke','#795f46');line.setAttribute('stroke-width','4');line.setAttribute('stroke-linecap','round');band.append(line);}ball.parentNode.insertBefore(band,ball);}
  const guide=guideNode();if(!guide)return;
  const view=stage.querySelector('svg').viewBox.baseVal;
  const x=Math.max(10,60-back*view.width/Math.max(1,stage.clientWidth)),y=Math.min(580,500+down*view.height/Math.max(1,stage.clientHeight));
  band.querySelectorAll('line').forEach(line=>{line.setAttribute('x2',String(x));line.setAttribute('y2',String(y));});
  stage.classList.toggle('is-aiming',!!(back||down));band.style.visibility=back||down?'visible':'hidden';
  if(back||down)placeGuide(angleMilli,powerValue,1);else guide.style.visibility='hidden';
  projectile(x,y);
 }
 function paint(){
  const active=getState()?.active,target=active?.plan?.targets?.[Math.min(log.length,4)];
  stage.querySelectorAll('[id^="pb-target-"]').forEach(n=>{const selected=target&&Number(n.getAttribute('cx'))===target.x&&Number(n.getAttribute('cy'))===target.y;n.classList.toggle('ballista-target',!!selected);});
  const vane=stage.querySelector('#pb-vane');if(vane)vane.setAttribute('transform',target?.wind<0?'translate(980 0) scale(-1 1)':'');
  if(!flight&&!aim)projectile();
  showKeyboardAim();
 }
 async function submit(){
  if(disposed||sending||isCommandPending())return;const active=getState()?.active;if(!active||log.length!==5)return;
  sending=true;render();try{await command('vgame_finish',{game:GAME,run_id:active.run_id,log:log.map(s=>s.slice())});}finally{sending=false;if(!disposed)render();}
 }
 function animate(){
  if(disposed)return;const active=getState()?.active;
  if(!active||active.run_id!==runId){flight=null;render();return;}
  if(flight){const index=Math.max(0,Math.floor((elapsed(active)-flight.release)/active.plan.step_ms)),point=flight.result.path[Math.min(index,flight.result.path.length-1)];projectile(...point);
   if(elapsed(active)>=flight.release+flight.result.duration){const hit=flight.result.hit;flight=null;projectile(60,500,hit);progress.textContent=`${log.map((s,i)=>shotResult(active.plan.targets[i],s[0],s[1],active.plan.step_ms).hit?'✓':'×').join('  ')} · ${hit?'В окно!':'Мимо — попробуй другой угол.'}`;render();if(log.length===5)void submit();}
  }
  if(flight||active&&elapsed(active)<lastEnd(active)+250)raf=requestAnimationFrame(animate);else render();
 }
 function render(){
  if(disposed)return;void loadScene();const state=getState(),active=state?.active;
  $('.ballista-rules').textContent='Три зачётные доставки в день, затем тренировка. За день учитывается лучший результат. Баночки игровые — напитки со склада не расходуются. '+cashBonusText(state?.bonus_budget)+(state?.next_cash_reward==null?'':` Доступная денежная премия сейчас: до ${state.next_cash_reward} мон.`);
  if(active?.plan?.version!==1&&active){status.textContent='Эта версия доставки пока недоступна. Обнови игру.';start.hidden=shoot.hidden=finish.hidden=true;return;}
  if(active&&active.run_id!==runId){runId=active.run_id;log=load(active);flight=null;
   if(log.length&&elapsed(active)<lastEnd(active)){const i=log.length-1;flight={release:log[i][2],result:shotResult(active.plan.targets[i],log[i][0],log[i][1],active.plan.step_ms)};cancelAnimationFrame(raf);raf=requestAnimationFrame(animate);}
   progress.textContent=log.length?`${log.map((s,i)=>shotResult(active.plan.targets[i],s[0],s[1],active.plan.step_ms).hit?'✓':'×').join('  ')} · ${log.length} из 5`:'';
  }
  const pending=sending||isCommandPending(),expired=active&&now()>=active.expires_at,target=active?.plan?.targets?.[Math.min(log.length,4)];
  start.hidden=!!active&&!expired;shoot.hidden=!active||expired||log.length===5;finish.hidden=!active||expired||log.length!==5;
  start.disabled=pending||!state||state.locked;shoot.disabled=pending||!!flight||!!active&&elapsed(active)<lastEnd(active)+250;finish.disabled=pending||!!flight;
  stage.setAttribute('aria-disabled',String(shoot.disabled||shoot.hidden));
  angle.disabled=power.disabled=!active||expired||pending||!!flight||log.length===5;
  if(expired)status.textContent='Время доставки вышло. Начни новую.';
  else if(active)status.textContent=pending?'Сохраняем доставку…':flight?'Баночка летит…':log.length===5?'Пять бросков завершены. Сохрани результат.':`${active.practice?'Тренировка · ':''}Бросок ${log.length+1} из 5`;
  else status.textContent=state?.locked?'Пух пока не готов играть.':ballistaResultText(state?.last_result)||'Пух ждёт тебя у баллисты.';
  if(!active){start.textContent=state?.last_result?'Ещё доставка':'Начать доставку';progress.textContent=`Зачётных доставок осталось: ${state?.attempts_left??3} из 3.`;wind.textContent='Ветер меняется перед каждым броском.';}
  else wind.textContent=`Ветер: ${target.wind===0?'штиль':`${target.wind<0?'← влево':'вправо →'} · ${Math.abs(target.wind)===1?'слабый':'сильный'}`}`;
  paint();
 }
 start.addEventListener('click',async()=>{if(sending||isCommandPending())return;sending=true;render();try{await command('vgame_start',{game:GAME});}finally{sending=false;if(!disposed)render();}});
 function fire(angleMilli,powerValue){
  const active=getState()?.active;if(shoot.disabled||!active||log.length>=5)return;
  const release=elapsed(active),result=shotResult(active.plan.targets[log.length],angleMilli,powerValue,active.plan.step_ms);
  log.push([angleMilli,powerValue,release]);save();flight={release,result};render();cancelAnimationFrame(raf);raf=requestAnimationFrame(animate);
 }
 shoot.addEventListener('click',()=>fire(Number(angle.value)*1000,Number(power.value)));
 stage.addEventListener('pointerdown',event=>{
  if(stage.getAttribute('aria-disabled')==='true'||aim)return;
  aim={id:event.pointerId,x:event.clientX,y:event.clientY,angle:45000,power:600,moved:false};
  stage.setPointerCapture(event.pointerId);event.preventDefault();
 });
 stage.addEventListener('pointermove',event=>{
  if(!aim||aim.id!==event.pointerId)return;
  const back=Math.max(0,aim.x-event.clientX),down=Math.max(0,event.clientY-aim.y),distance=Math.hypot(back,down);
  if(distance<8){aim.moved=false;aimVisual();status.textContent='Оттяни баночку назад и вниз, затем отпусти.';return;}
  aim.moved=true;aim.angle=Math.round(Math.min(75,Math.max(15,Math.atan2(down,Math.max(1,back))*180/Math.PI)))*1000;
  aim.power=Math.min(1000,Math.max(200,Math.round((200+Math.min(1,distance/Math.max(55,stage.clientWidth*.24))*800)/10)*10));
  aimVisual(back,down,aim.angle,aim.power);
  status.textContent=`Прицел: ${aim.angle/1000}° · сила ${Math.round(aim.power/10)}%. Отпусти для броска.`;
  event.preventDefault();
 });
 stage.addEventListener('pointerup',event=>{
  if(!aim||aim.id!==event.pointerId)return;
  const shot=aim;aim=null;if(stage.hasPointerCapture(event.pointerId))stage.releasePointerCapture(event.pointerId);aimVisual();
  if(shot.moved)fire(shot.angle,shot.power);else status.textContent='Оттяни баночку назад и вниз, затем отпусти.';
  showKeyboardAim();
 });
 stage.addEventListener('pointercancel',event=>{if(aim?.id===event.pointerId){aim=null;aimVisual();showKeyboardAim();}});
 stage.addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ')&&stage.getAttribute('aria-disabled')==='false'){event.preventDefault();fire(Number(angle.value)*1000,Number(power.value));}});
 finish.addEventListener('click',()=>void submit());
 $('.ballista-back').addEventListener('click',onBack);
 angle.addEventListener('input',()=>{$('.ballista-angle-value').textContent=`${angle.value}°`;showKeyboardAim();});
 power.addEventListener('input',()=>{$('.ballista-power-value').textContent=`${Math.round(Number(power.value)/10)}%`;showKeyboardAim();});
 $('.ballista-keyboard').addEventListener('toggle',showKeyboardAim);
 const observer=new MutationObserver(()=>void loadScene());observer.observe(document.documentElement,{attributes:true,attributeFilter:['data-farm-theme']});
 const timer=setInterval(()=>{if(!disposed&&!flight)render();},1000);
 render();
 return {render,destroy(){disposed=true;sceneEpoch++;cancelAnimationFrame(raf);clearInterval(timer);observer.disconnect();host.hidden=true;host.replaceChildren();}};
}
