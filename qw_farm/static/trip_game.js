/* Trip minigames: "Порыбачу сам" (cast, bite, strike) and "Пойду сам" (short forest gathering). Server rules: qw_farm/trip_games.py.
 *
 * The first half is a 1:1 port of the pure rules (integers only, no hashing: the server ships the generated plan in trip.game.plan).
 * The client uses it to show the forecast and to build the log; the server replays the log itself and decides the reward.
 * Pure helpers come first and touch no DOM, so tests/js/farm_trip_game.test.cjs can run them in a bare vm context.
 */
export const RULES={ttl:900,bonus:250,mark_period:1600,dead_zone:60,acc_span:300,react:150,first_aim_ms:500,grid:6,trap_cost:2,step_cs:20};
const DIRS={U:[0,-1],D:[0,1],L:[-1,0],R:[1,0]};
const idiv=(a,b)=>(a-a%b)/b;                       // exact integer division for non-negative integers
export const Q_AUTO=1000,MAX_MS=600000;

/* ---------------------------------------------------------------- pure rules (see trip_games.py) */
export function markPosition(t,phase,rules=RULES){
 const period=rules.mark_period,m=(t+phase)%period,half=idiv(period,2);
 return m<=half?idiv(m*1000,half):idiv((period-m)*1000,half);
}
export function accuracy(aimMs,cast,rules=RULES){
 const d=Math.abs(markPosition(aimMs,cast.phase,rules)-cast.zone);
 return Math.max(0,1000-idiv(Math.max(0,d-rules.dead_zone)*1000,rules.acc_span));
}
export function strikeScore(strikeMs,biteMs,window,rules=RULES){
 const d=strikeMs-biteMs;
 if(d<rules.react||d>rules.react+window)return 0;
 const mid=idiv(window,2);
 return 1000-idiv(Math.abs(d-rules.react-mid)*600,Math.max(1,mid));
}
export const castEnd=(aim,strike,cast,window,rules=RULES)=>strike!==null?strike:aim+cast.wait+rules.react+window;
export function castScore(plan,i,aim,strike,rules=RULES){
 const cast=plan.casts[i],t=strike===null?0:strikeScore(strike,aim+cast.wait,plan.window,rules);
 return t?idiv(4*accuracy(aim,cast,rules)+6*t,10):0;
}
/** Permille score of a fishing log, or null when it breaks the rules (same checks as trip_games.fish_score). */
export function fishScore(plan,log,rules=RULES){
 const casts=plan.casts;
 if(!Array.isArray(log)||log.length!==casts.length)return null;
 let total=0,freeAt=rules.first_aim_ms;
 for(let i=0;i<casts.length;i++){
  const e=log[i];
  if(!Array.isArray(e)||e.length!==2)return null;
  const [aim,strike]=e;
  if(!Number.isInteger(aim)||aim<freeAt||aim>MAX_MS)return null;
  if(strike!==null&&(!Number.isInteger(strike)||!(aim<strike&&strike<=MAX_MS)))return null;
  total+=castScore(plan,i,aim,strike,rules);
  freeAt=castEnd(aim,strike,casts[i],plan.window,rules);
 }
 return idiv(total,casts.length);
}
/** State of a forest walk: {cur, used, got, seen:Set, trapsHit} or null for an illegal path (same rules as forage_score). */
export function walk(plan,path){
 if(typeof path!=='string'||path.length>plan.budget)return null;
 const items=new Set(Object.keys(plan.items).map(Number)),traps=new Set(plan.traps);
 const st={cur:plan.start,used:0,got:0,seen:new Set([plan.start]),hit:0,items,traps};
 for(const ch of path){
  const d=DIRS[ch];if(!d||st.used>=plan.budget)return null;
  const x=st.cur%plan.w+d[0],y=idiv(st.cur,plan.w)+d[1];
  if(x<0||x>=plan.w||y<0||y>=plan.h)return null;
  st.cur=y*plan.w+x;st.used++;
  if(!st.seen.has(st.cur)){st.seen.add(st.cur);if(items.has(st.cur))st.got++;if(traps.has(st.cur)){st.used+=RULES.trap_cost;st.hit++;}}
 }
 return st;
}
export function forageScore(plan,path){const st=walk(plan,path);return st?Math.min(1000,idiv(1000*st.got,Math.max(1,plan.gold))):null;}
export const quality=(score,rules=RULES)=>Q_AUTO+idiv(rules.bonus*score,1000);
export function scaledOutputs(outputs,q){const r={};for(const [k,v] of Object.entries(outputs))r[k]=Math.max(v,idiv(v*q+500,1000));return r;}
export function finalOutputs(trip){return trip.game&&trip.game.state==='done'?scaledOutputs(trip.outputs,trip.game.q):{...trip.outputs};}
/** Seconds of the game window still open on the server clock. */
export const playLeft=(trip,serverNow)=>trip.game&&trip.game.state==='open'?trip.game.expires_at-serverNow:0;
export const canPlay=(trip,serverNow)=>!trip.guide&&!!trip.game&&trip.game.state==='open'&&playLeft(trip,serverNow)>5;

/* ---------------------------------------------------------------- texts */
const pct=permille=>(permille/10).toFixed(1).replace('.',',')+'%';
function node(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
function btn(text,cls,fn){const b=node('button',cls,text);b.type='button';if(fn)b.onclick=fn;return b;}
const reducedMotion=()=>{try{return !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;}catch{return false;}};
const isNight=()=>document.documentElement.dataset.farmTheme==='night';
const mmss=sec=>{sec=Math.max(0,Math.ceil(sec));return `${Math.floor(sec/60)}:${String(sec%60).padStart(2,'0')}`;};
function rrect(g,x,y,w,h,r){g.beginPath();if(g.roundRect)g.roundRect(x,y,w,h,r);else g.rect(x,y,w,h);}
const goodsText=(outputs,name)=>Object.entries(outputs).map(([k,v])=>`${name(k)} ×${v}`).join(', ');
const extraText=(trip,name)=>{
 const base=trip.outputs,fin=finalOutputs(trip),extra=Object.entries(fin).filter(([k,v])=>v>base[k]).map(([k,v])=>`${name(k)} +${v-base[k]}`);
 return extra.join(', ');
};
export const bonusLine=(trip,name)=>{const e=extraText(trip,name);return e?`Бонус игры: ${e}`:'Как у автопилота';};

const LOOK={
 day:{water:['#bfe3ea','#8fc5d6'],bank:'#9fc27d',track:'#ffffffb0',zoneA:'#4f9d5d66',zoneB:'#e8c15a66',mark:'#2b5a3a',float:'#d9482f',grass:['#cfe3a8','#c5dc9d'],ink:'#26402d',tile:'#00000014',frame:'#5d6e5a',item:'#fffef6aa'},
 night:{water:['#1d3550','#14263a'],bank:'#2f4a3a',track:'#ffffff30',zoneA:'#6fcf8a66',zoneB:'#e8c15a55',mark:'#bfe9c9',float:'#ff9a7a',grass:['#2a3f33','#25392e'],ink:'#e4eedd',tile:'#ffffff14',frame:'#8fb59a',item:'#ffffff18'}
};
const look=()=>LOOK[isNight()?'night':'day'];

/** Draw one item (forest) or trap in the cell (x,y,s). Shape + colour + letter label, so it does not rely on colour alone. */
function drawItem(g,id,x,y,s,trap=false){
 const cx=x+s/2,cy=y+s/2,r=s*0.3;
 g.save();g.lineCap='round';g.lineJoin='round';
 const cap=(col,stem)=>{g.fillStyle=stem;g.fillRect(cx-r*0.28,cy,r*0.56,r*0.9);g.fillStyle=col;g.beginPath();g.ellipse(cx,cy,r*1.05,r*0.8,0,Math.PI,0);g.fill();};
 if(trap){
  cap('#c4372c','#f2ead6');g.fillStyle='#fff';for(const [dx,dy] of [[-0.5,-0.3],[0.2,-0.5],[0.55,-0.1]]){g.beginPath();g.arc(cx+dx*r,cy+dy*r,r*0.14,0,6.3);g.fill();}
  g.strokeStyle='#7a1d16';g.lineWidth=Math.max(2,s/16);g.beginPath();g.moveTo(x+s*0.12,y+s*0.12);g.lineTo(x+s*0.34,y+s*0.34);g.moveTo(x+s*0.34,y+s*0.12);g.lineTo(x+s*0.12,y+s*0.34);g.stroke();
 }else if(id==='wood'){
  g.fillStyle='#a47544';rrect(g,cx-r*1.1,cy-r*0.45,r*2.2,r*0.9,r*0.3);g.fill();g.fillStyle='#d9b27a';g.beginPath();g.ellipse(cx+r*1.0,cy,r*0.28,r*0.45,0,0,6.3);g.fill();g.strokeStyle='#7a5530';g.lineWidth=1.5;g.beginPath();g.moveTo(cx-r*0.8,cy-r*0.1);g.lineTo(cx+r*0.4,cy-r*0.1);g.stroke();
 }else if(id==='mushroom'){cap('#b9814f','#f2ead6');
 }else if(id==='chanterelle'){
  g.fillStyle='#f0a93a';g.beginPath();g.moveTo(cx-r*1.0,cy-r*0.5);g.quadraticCurveTo(cx,cy-r*1.0,cx+r*1.0,cy-r*0.5);g.lineTo(cx+r*0.3,cy+r*0.9);g.lineTo(cx-r*0.3,cy+r*0.9);g.closePath();g.fill();
 }else if(id==='wildberry'||id==='blackberry'){
  g.fillStyle=id==='wildberry'?'#d8344a':'#3b2a56';for(const [dx,dy] of [[-0.5,0.2],[0.5,0.2],[0,-0.5],[0,0.6]]){g.beginPath();g.arc(cx+dx*r,cy+dy*r,r*0.55,0,6.3);g.fill();}
  g.fillStyle='#4f8a3f';g.beginPath();g.ellipse(cx,cy-r*0.95,r*0.5,r*0.22,0.3,0,6.3);g.fill();
 }else if(id==='herbs'){
  g.strokeStyle='#3f8a4a';g.lineWidth=Math.max(2,s/14);for(const dx of [-0.6,0,0.6]){g.beginPath();g.moveTo(cx+dx*r*0.5,cy+r*0.9);g.quadraticCurveTo(cx+dx*r*1.4,cy,cx+dx*r*1.1,cy-r*0.9);g.stroke();}
 }else if(id==='hazelnut'){
  g.fillStyle='#9a6a3a';g.beginPath();g.ellipse(cx,cy+r*0.1,r*0.75,r*0.9,0,0,6.3);g.fill();g.fillStyle='#6b8f3a';g.beginPath();g.ellipse(cx,cy-r*0.6,r*0.8,r*0.45,0,Math.PI,0);g.fill();
 }else{g.fillStyle='#6aa84f';g.beginPath();g.arc(cx,cy,r*0.8,0,6.3);g.fill();}
 g.restore();
}

const FISH_HELP='Нажми «Забросить», когда метка стоит в зелёной зоне. Дождись поклёвки — поплавок нырнёт — и подсеки, пока кольцо сжимается. Рано подсечёшь — рыба уйдёт.';
const FORAGE_HELP='Тапни соседнюю клетку, чтобы сделать шаг, или дальнюю — пройду кратчайшим путём. Каждый шаг — из запаса. Мухомор отнимает ещё 2 шага. Собери как можно больше.';

/**
 * opts: {trip, route, rules (catalog.trip_games), serverNow(), itemName(id), timeText(sec),
 *        onFinish(log) -> Promise<boolean>, tripNow() -> trip|null, onClose()}
 * Returns {close()}.
 */
export function openTripGame(opts){
 const trip=opts.trip,game=trip.game,plan=game.plan,fish=game.kind==='fish',rules={...RULES,...(opts.rules||{})};
 const name=opts.itemName||(id=>id);
 const prev=document.activeElement,inerted=[];
 let bitten=false,closed=false,done=false,sending=false,started=false,raf=0,confirming=false,srTimer=0,t0=0,layoutTimer=0;
 const root=node('div','fg-overlay tg-overlay');root.setAttribute('role','dialog');root.setAttribute('aria-modal','true');
 const title=fish?`Рыбалка: ${opts.route?.name||''}`:`Прогулка: ${opts.route?.name||''}`;root.setAttribute('aria-label',title);
 const top=node('div','fg-top'),head=node('strong','',title),timer=node('span','fg-timer'),close=btn('×','fg-close',()=>requestClose());
 close.setAttribute('aria-label','Закрыть игру');timer.title='Осталось на игру';
 top.append(head,timer,close);
 const stage=node('div','fg-stage'),canvas=node('canvas','fg-canvas');canvas.tabIndex=0;stage.append(canvas);
 const hud=node('div','fg-hud'),forecast=node('div','fg-forecast'),stat=node('div','fg-stat'),help=node('p','fg-help',fish?FISH_HELP:FORAGE_HELP),status=node('div','fg-status');
 status.setAttribute('role','status');hud.append(forecast,stat,help,status);
 const sr=node('div','fg-sr');sr.setAttribute('role','status');sr.setAttribute('aria-live','polite');
 const controls=node('div','fg-controls tg-controls');
 root.append(top,stage,hud,controls,sr);document.body.append(root);document.body.classList.add('fg-open');
 for(const el of [...document.body.children])if(el!==root&&!el.inert){el.inert=true;inerted.push(el);}
 let size={w:300,h:300,dpr:1,cell:40,left:0,top:0};
 const say=(text,bad=false)=>{status.textContent=text;status.classList.toggle('bad',bad);};
 const announce=text=>{clearTimeout(srTimer);srTimer=setTimeout(()=>{srTimer=0;if(!closed)sr.textContent=text;},500);};
 const tNow=()=>performance.now()-t0;
 const left=()=>Number.isFinite(game.expires_at)&&typeof opts.serverNow==='function'?game.expires_at-opts.serverNow():rules.ttl;
 const deadline=performance.now()+Math.max(0,left())*1000;
 const buzz=ms=>{try{if(!reducedMotion())navigator.vibrate?.(ms);}catch{}};

 /* ---- FISHING state */
 const log=[];let ci=0,phase='aim',aimAt=0,strikeAt=null,freeAt=rules.first_aim_ms,resultUntil=0,resultText='',floatX=0,spooked=false,castPts=[];
 const casts=fish?plan.casts:[];
 /* ---- FORAGE state */
 let path='',queue=[],stepAt=0,st=fish?null:walk(plan,'');
 const pathLimit=plan.budget;

 const act=btn('','fg-act primary tg-big'),undo=btn('Шаг назад','fg-act'),fin=btn('Готово','fg-act primary'),skip=btn('Без игры','fg-act');
 controls.append(...(fish?[act]:[undo,fin]),skip);
 skip.onclick=()=>requestClose();
 skip.title='Закрыть игру: поездка продолжится как обычно, без бонуса (можно вернуться к игре, пока не вышло время)';

 function layout(){
  if(closed)return;
  const r=stage.getBoundingClientRect(),w=Math.max(120,Math.floor(r.width)),h=Math.max(120,Math.floor(r.height));
  const dpr=Math.min(2,window.devicePixelRatio||1,Math.sqrt(4e6/(w*h)));
  const pw=Math.floor(w*dpr),ph=Math.floor(h*dpr);if(canvas.width!==pw)canvas.width=pw;if(canvas.height!==ph)canvas.height=ph;
  const cell=Math.max(24,Math.min(Math.floor(w/plan.w||1),Math.floor(h/(plan.h||1)),80));
  size={w,h,dpr,cell,left:Math.floor((w-cell*(plan.w||1))/2),top:Math.floor((h-cell*(plan.h||1))/2)};
 }

 /* ---- FISHING flow */
 function aimPos(t){return markPosition(t,casts[ci].phase,rules);}
 function fishAction(){
  if(done||sending||confirming||!started)return;
  const t=Math.round(tNow());
  if(phase==='aim'){
   if(t<freeAt)return;
   aimAt=t;strikeAt=null;phase='wait';bitten=false;floatX=aimPos(t);spooked=false;buzz(10);
   say('Поплавок на воде. Жди поклёвку…');announce('Заброс сделан. Жди поклёвку.');paintStat();
  }else if(phase==='wait'){
   if(t<=aimAt+150)return;                         // an accidental double tap
   strikeAt=t;const bite=aimAt+casts[ci].wait;
   spooked=t<bite+rules.react;endCast(strikeScore(t,bite,plan.window,rules)>0?'good':(t<bite+rules.react?'early':'late'));
  }
 }
 function endCast(kind){
  log.push([aimAt,strikeAt]);
  const sc=castScore(plan,ci,aimAt,strikeAt,rules);
  resultText=kind==='good'?`Подсечка! ${pct(sc)}`:kind==='early'?'Рано — рыба испугалась.':'Рыба сорвалась.';
  say(resultText,kind!=='good');announce(resultText);
  if(kind==='good')buzz(30);
  freeAt=castEnd(aimAt,strikeAt,casts[ci],plan.window,rules);
  phase='result';resultUntil=Math.max(tNow()+1100,freeAt);
  paintStat();
 }
 function fishTick(t){
  if(phase==='wait'&&strikeAt===null){
   const bite=aimAt+casts[ci].wait;
   if(t>=bite&&!bitten){bitten=true;buzz(40);announce('Клюёт!');}
   if(t>bite+rules.react+plan.window){strikeAt=null;endCast('late');}
  }
  if(phase==='result'&&t>=resultUntil){
   ci++;
   if(ci>=casts.length){phase='over';paintStat();submit(log);}else{phase='aim';say('Следующий заброс.');paintStat();}
  }
 }
 function paintStat(){
  if(fish){
   const sc=log.length?idiv(log.reduce((s,e,i)=>s+castScore(plan,i,e[0],e[1],rules),0),casts.length):0;
   stat.textContent=`Заброс ${Math.min(ci+1,casts.length)} из ${casts.length}`;
   forecast.textContent=log.length?`Прогноз: ${pct(quality(sc,rules))} от нормы`:`Бонус до +${pct(rules.bonus)} к улову`;
   act.textContent=phase==='aim'?'Забросить':phase==='wait'?'Подсечь':'…';
   act.disabled=done||sending||phase==='result'||phase==='over'||!started;
  }else{
   st=walk(plan,path);const sc=forageScore(plan,path)||0;
   stat.textContent=`Шагов осталось: ${Math.max(0,plan.budget-st.used)} из ${plan.budget} · собрано: ${st.got}`+(st.hit?` · ловушек: ${st.hit}`:'');
   forecast.textContent=path.length?`Прогноз: ${pct(quality(sc,rules))} от нормы`:`Бонус до +${pct(rules.bonus)} к находкам`;
   undo.disabled=sending||done||!path.length;fin.disabled=sending||done||!path.length;
  }
 }

 /* ---- FORAGE flow */
 function tryStep(ch){
  if(done||sending||confirming)return false;
  const next=path+ch;if(next.length>pathLimit||!walk(plan,next)){return false;}
  path=next;paintStat();
  const s=walk(plan,path);announce(`Собрано ${s.got}, шагов осталось ${Math.max(0,plan.budget-s.used)}`);
  return true;
 }
 function cellOf(e){
  const r=canvas.getBoundingClientRect(),x=Math.floor((e.clientX-r.left-size.left)/size.cell),y=Math.floor((e.clientY-r.top-size.top)/size.cell);
  return x>=0&&x<plan.w&&y>=0&&y<plan.h?y*plan.w+x:-1;
 }
 function route(to){
  const s=walk(plan,path);if(!s||to===s.cur)return;
  const prevMap=new Map([[s.cur,null]]),todo=[s.cur];
  for(let i=0;i<todo.length&&!prevMap.has(to);i++){
   const c=todo[i];
   for(const ch of 'UDLR'){const d=DIRS[ch],x=c%plan.w+d[0],y=idiv(c,plan.w)+d[1];if(x<0||x>=plan.w||y<0||y>=plan.h)continue;const n=y*plan.w+x;if(s.traps.has(n)&&n!==to)continue;if(!prevMap.has(n)){prevMap.set(n,[c,ch]);todo.push(n);}}
  }
  const chars=[];for(let k=to;prevMap.get(k);k=prevMap.get(k)[0])chars.push(prevMap.get(k)[1]);
  chars.reverse();
  if(!prevMap.has(to)){say('Туда не пройти, не наступив на мухомор.',true);return;}
  if(!walk(plan,path+chars.join(''))){say('Не хватит шагов, чтобы дойти.',true);return;}
  queue=chars;say('');
 }
 function undoStep(){if(done||sending||!path.length)return;queue=[];path=path.slice(0,-1);paintStat();}
 function onKey(e){
  if(closed||e.ctrlKey||e.metaKey||e.altKey)return;
  if(e.code==='Escape'){e.preventDefault();e.stopPropagation();if(confirming)cancelClose();else requestClose();return;}
  if(confirming||done)return;
  if(e.code==='Tab'){const scope=root.querySelector('.fg-confirm')||root.querySelector('.fg-result')||root,items=[...scope.querySelectorAll('button:not(:disabled),canvas')];
   if(items.length){const i=items.indexOf(document.activeElement),n=e.shiftKey?(i<=0?items.length-1:i-1):(i<0||i>=items.length-1?0:i+1);e.preventDefault();e.stopPropagation();items[n].focus();}return;}
  if(fish){if(e.code==='Space'||e.code==='Enter'){e.preventDefault();e.stopPropagation();if(!e.repeat)fishAction();}return;}
  const KEYS={ArrowUp:'U',KeyW:'U',ArrowDown:'D',KeyS:'D',ArrowLeft:'L',KeyA:'L',ArrowRight:'R',KeyD:'R'};
  if(KEYS[e.code]){e.preventDefault();e.stopPropagation();queue=[];tryStep(KEYS[e.code]);}
  else if(e.code==='Backspace'||e.code==='KeyZ'){e.preventDefault();e.stopPropagation();undoStep();}
 }
 window.addEventListener('keydown',onKey,true);
 canvas.onpointerdown=e=>{
  canvas.focus({preventScroll:true});
  if(done||confirming||sending)return;
  if(fish){e.preventDefault();fishAction();return;}
  if(!started)return;
  const c=cellOf(e);if(c<0)return;
  const s=walk(plan,path),dx=c%plan.w-s.cur%plan.w,dy=idiv(c,plan.w)-idiv(s.cur,plan.w);
  if(Math.abs(dx)+Math.abs(dy)===1){queue=[];if(!tryStep(dx>0?'R':dx<0?'L':dy>0?'D':'U'))say('Шаги закончились.',true);else say('');}
  else route(c);
 };
 act.onclick=()=>fishAction();
 undo.onclick=()=>undoStep();
 fin.onclick=()=>submit(path);

 /* ---- sending / closing */
 async function submit(payload){
  if(sending||done||closed)return;
  sending=true;paintStat();
  if(!fish){
   // the server wants >= step_cs/100 s per step since the start of the trip (whole-second clock)
   const el=typeof opts.serverNow==='function'?opts.serverNow()-trip.started_at:1e9,need=(rules.step_cs/100*payload.length+2-el)*1000;
   if(need>0){say(`Сдаём… ещё ${Math.ceil(need/1000)} с`);await new Promise(r=>setTimeout(r,need));}
   if(closed)return;
  }
  let ok=false;try{ok=await opts.onFinish(payload);}catch{ok=false;}
  sending=false;if(closed)return;
  if(!ok){
   const t=opts.tripNow?.();
   if(!t||!t.game||t.game.state!=='open'){done=true;showNote('Игра уже закрыта','Эта поездка уже собрана или игра сыграна. Закрой окно и обнови раздел.');return;}
   if(performance.now()>=deadline-1500){done=true;showNote('Время вышло','Окно мини-игры закрылось. Поездка идёт как обычно, без бонуса.');return;}
   if(fish){say('Не получилось отправить запись. Нажми «Повторить».',true);act.textContent='Повторить отправку';act.disabled=false;act.onclick=()=>{act.onclick=()=>fishAction();submit(log);};}
   else say('Не получилось отправить. Нажми «Готово» ещё раз.',true);
   paintStat();return;
  }
  done=true;showResult();
 }
 function showResult(){
  const t=opts.tripNow?.()||trip,tg=t.game&&t.game.state==='done'?t.game:null,box=node('div','fg-result');
  const score=tg?tg.score:(fish?fishScore(plan,log,rules):forageScore(plan,path))||0,q=tg?tg.q:quality(score,rules);
  box.append(node('h2','',fish?'Рыбалка сыграна':'Прогулка сыграна'),node('p','fg-line',`Оценка ${pct(score)} · добыча ×${(q/1000).toFixed(2).replace('.',',')} от нормы`));
  const extra=extraText({outputs:trip.outputs,game:{state:'done',q}},name);
  box.append(node('p',extra?'fg-proud':'fg-compare',extra?`Сам справился: ${extra}`:q>1000?'Прибавка пока меньше одного предмета: точнее — будет больше!':'Как у автопилота. В следующий раз получится лучше!'));
  box.append(node('p','fg-compare',`Время поездки не изменилось. Вернись за добычей, когда таймер дойдёт до нуля.`),btn('Готово','primary wide',()=>finishClose()));
  root.append(box);box.querySelector('button').focus();
 }
 function showNote(head,text){
  root.querySelector('.fg-result')?.remove();
  const box=node('div','fg-result');box.setAttribute('role','alertdialog');box.append(node('h2','',head),node('p','',text),btn('Закрыть','primary wide',()=>finishClose()));root.append(box);box.querySelector('button').focus();
 }
 function requestClose(){
  if(closed)return;
  if(done||!started||(fish?!log.length:!path.length)){finishClose();return;}
  if(confirming)return;
  confirming=true;
  const box=node('div','fg-confirm');box.setAttribute('role','alertdialog');box.setAttribute('aria-modal','true');box.setAttribute('aria-label','Выйти из игры?');
  box.append(node('h2','','Выйти из игры?'),node('p','','Результат не засчитается: поездка пойдёт как обычно, без бонуса. Сыграть заново нельзя после отправки, но пока не вышло время — можно вернуться.'),
   btn('Продолжить','primary wide',()=>cancelClose()),btn('Выйти','secondary wide',()=>finishClose()));
  root.append(box);box.querySelector('button').focus();
 }
 function cancelClose(){root.querySelector('.fg-confirm')?.remove();confirming=false;canvas.focus({preventScroll:true});}
 // Back (Telegram BackButton, browser back) goes through the same confirmation as Escape. Returns true when the game closed, false when the player stays.
 function backClose(){if(closed)return true;if(confirming){cancelClose();return false;}requestClose();return closed;}
 function finishClose(){
  if(closed)return;closed=true;cancelAnimationFrame(raf);raf=0;clearTimeout(srTimer);clearTimeout(layoutTimer);
  for(const el of inerted)el.inert=false;inerted.length=0;
  window.removeEventListener('keydown',onKey,true);window.removeEventListener('resize',layout);resizeObs?.disconnect();
  canvas.width=0;canvas.height=0;root.remove();document.body.classList.remove('fg-open');
  try{prev?.focus?.();}catch{}
  opts.onClose?.();
 }

 /* ---- start card */
 function showIntro(){
  const box=node('div','fg-result');box.setAttribute('role','dialog');box.setAttribute('aria-label','Правила');
  const base=goodsText(trip.outputs,name),best=goodsText(scaledOutputs(trip.outputs,quality(1000,rules)),name);
  box.append(node('h2','',fish?'Порыбачу сам':'Пойду сам'),
   node('p','',fish?`${casts.length} заброса: забрось, дождись поклёвки, подсеки. Это ${casts.length*10}–${casts.length*14} секунд.`:`Короткий сбор: ${plan.budget} шагов на поляне. Это около минуты.`),
   node('p','fg-compare',`Автопилот: ${base}. Идеальная игра: ${best}.`),
   node('p','fg-compare','Время поездки и опыт не меняются; хуже автопилота не будет.'));
  const go=btn('Начать','primary wide',()=>{box.remove();started=true;t0=performance.now();stage.classList.add('tg-live');paintStat();canvas.focus({preventScroll:true});say(fish?'Забрось, когда метка в зелёной зоне.':'Выбери клетку. Мухомор — ловушка: −2 шага.');});
  box.append(go,btn('Без игры','secondary wide',()=>finishClose()));root.append(box);go.focus();
 }

 /* ---- drawing */
 function draw(ts){
  if(closed)return;
  const t=started?tNow():0,L=look(),calm=reducedMotion();
  const lf=Math.max(0,(deadline-performance.now())/1000);timer.textContent=`Осталось ${mmss(lf)}`;timer.classList.toggle('warn',lf<=60);
  if(lf<=0&&!done&&!sending&&started){done=true;showNote('Время вышло','Окно мини-игры закрылось. Поездка идёт как обычно, без бонуса.');}
  if(started&&!done&&!confirming&&fish)fishTick(t);
  if(started&&!done&&!confirming&&!fish&&queue.length&&!sending&&ts-stepAt>=130){
   stepAt=ts;const ch=queue[0];if(tryStep(ch))queue.shift();else{queue=[];say('Шаги закончились.',true);}
  }
  const g=canvas.getContext('2d'),{w,h,dpr}=size;
  g.setTransform(dpr,0,0,dpr,0,0);g.clearRect(0,0,w,h);
  if(fish)drawFish(g,t,L,calm);else drawForest(g,ts,L,calm);
  raf=requestAnimationFrame(draw);
 }
 function drawFish(g,t,L,calm){
  const {w,h}=size,sky=g.createLinearGradient(0,0,0,h);sky.addColorStop(0,L.water[0]);sky.addColorStop(1,L.water[1]);g.fillStyle=sky;g.fillRect(0,0,w,h);
  g.strokeStyle=isNight()?'#ffffff18':'#ffffff55';g.lineWidth=2;
  for(let i=0;i<5;i++){const y=h*(0.1+i*0.13)+(calm?0:Math.sin(t/900+i)*3);g.beginPath();g.moveTo(w*0.05,y);g.quadraticCurveTo(w*0.3,y-6,w*0.5,y);g.quadraticCurveTo(w*0.7,y+6,w*0.95,y);g.stroke();}
  const pad=Math.max(24,w*0.07),tx0=pad,tx1=w-pad,ty=h*0.76,pos=p=>tx0+(tx1-tx0)*p/1000;
  g.fillStyle=L.bank;rrect(g,0,h*0.88,w,h*0.12+2,0);g.fill();
  const cast=casts[Math.min(ci,casts.length-1)];
  // aiming track: green core = perfect, yellow = fair; the fish shadow sits in the zone
  g.fillStyle=L.track;rrect(g,tx0,ty-9,tx1-tx0,18,9);g.fill();
  const zw=(a,b)=>{g.fillRect(pos(Math.max(0,cast.zone-a)),ty-9,pos(Math.min(1000,cast.zone+a))-pos(Math.max(0,cast.zone-a)),18);};
  g.fillStyle=L.zoneB;zw(rules.dead_zone+150);g.fillStyle=L.zoneA;zw(rules.dead_zone);
  g.fillStyle=isNight()?'#0d1a28aa':'#2d5560aa';const fx=pos(cast.zone),fy=ty-34;g.beginPath();g.ellipse(fx,fy,18,8,0,0,6.3);g.fill();g.beginPath();g.moveTo(fx+16,fy);g.lineTo(fx+28,fy-7);g.lineTo(fx+28,fy+7);g.closePath();g.fill();
  const markT=phase==='aim'&&started?t:aimAt,mp=pos(phase==='aim'?aimPos(Math.max(0,markT)):floatX);
  g.fillStyle=L.mark;g.beginPath();g.arc(mp,ty,12,0,6.3);g.fill();g.strokeStyle=L.ink;g.lineWidth=2;g.stroke();
  // float
  if(phase!=='aim'&&phase!=='over'){
   const fxp=pos(floatX),bite=aimAt+cast.wait,dip=t>=bite&&strikeAt===null?Math.min(14,(t-bite)/20):0,bob=calm?0:Math.sin(t/260)*2;
   const fy2=h*0.34+bob+dip;
   g.strokeStyle=L.ink;g.lineWidth=1.5;g.beginPath();g.moveTo(w*0.5,h*0.9);g.quadraticCurveTo((w*0.5+fxp)/2,h*0.2,fxp,fy2);g.stroke();
   g.fillStyle=L.float;g.beginPath();g.ellipse(fxp,fy2,8,11-dip*0.3,0,0,6.3);g.fill();g.fillStyle='#fff';g.fillRect(fxp-8,fy2-1,16,3);
   if(phase==='wait'&&t>=bite){
    const since=t-bite,win0=rules.react,win1=rules.react+plan.window;
    g.strokeStyle=since>=win0&&since<=win1?'#3fae5a':'#e9a23a';g.lineWidth=4;
    const rr=since<win0?34:Math.max(10,34-24*Math.min(1,(since-win0)/plan.window));
    g.beginPath();g.arc(fxp,fy2+4,rr,0,6.3);g.stroke();
    g.fillStyle=L.ink;g.font='700 18px system-ui,sans-serif';g.textAlign='center';g.fillText(since>=win0?'Подсекай!':'Клюёт!',fxp,fy2-26);
   }
  }
  if(phase==='result'||phase==='over'){g.fillStyle=L.ink;g.font='700 16px system-ui,sans-serif';g.textAlign='center';g.fillText(resultText,w/2,h*0.2);}
  if(!started){g.fillStyle=L.ink;g.font='600 14px system-ui,sans-serif';g.textAlign='center';g.fillText('Приготовься…',w/2,h*0.2);}
 }
 function drawForest(g,ts,L,calm){
  const {w,h,cell,left:lx,top:ly}=size;
  g.fillStyle=L.grass[0];g.fillRect(0,0,w,h);
  const s=st||walk(plan,'');
  const items=s.items,traps=s.traps;
  for(let y=0;y<plan.h;y++)for(let x=0;x<plan.w;x++){
   const c=y*plan.w+x,X=lx+x*cell,Y=ly+y*cell;
   g.fillStyle=(x+y)%2?L.grass[0]:L.grass[1];g.fillRect(X,Y,cell,cell);
   if(s.seen.has(c)&&c!==s.cur&&c!==plan.start){g.fillStyle=isNight()?'#ffffff10':'#00000010';g.fillRect(X,Y,cell,cell);}
   if(items.has(c)&&!s.seen.has(c))drawItem(g,plan.items[c],X,Y,cell);
   else if(traps.has(c)){drawItem(g,'',X,Y,cell,true);}
   g.strokeStyle=L.tile;g.lineWidth=1;g.strokeRect(X+0.5,Y+0.5,cell-1,cell-1);
  }
  g.strokeStyle=L.frame;g.lineWidth=3;g.strokeRect(lx-1.5,ly-1.5,plan.w*cell+3,plan.h*cell+3);
  // walked path
  if(path.length){g.strokeStyle=isNight()?'#ffe9a8aa':'#2f6f4b88';g.lineWidth=Math.max(3,cell/9);g.lineCap='round';g.lineJoin='round';g.beginPath();
   let c=plan.start;g.moveTo(lx+(c%plan.w+0.5)*cell,ly+(idiv(c,plan.w)+0.5)*cell);
   for(const ch of path){const d=DIRS[ch];c=(idiv(c,plan.w)+d[1])*plan.w+(c%plan.w+d[0]);g.lineTo(lx+(c%plan.w+0.5)*cell,ly+(idiv(c,plan.w)+0.5)*cell);}g.stroke();}
  // the basket
  const bx=lx+(s.cur%plan.w)*cell,by=ly+idiv(s.cur,plan.w)*cell;
  g.fillStyle='#a47544';rrect(g,bx+cell*0.2,by+cell*0.38,cell*0.6,cell*0.4,cell*0.1);g.fill();g.strokeStyle='#6f4c28';g.lineWidth=2;g.stroke();
  g.beginPath();g.arc(bx+cell/2,by+cell*0.4,cell*0.22,Math.PI,0);g.stroke();
  if(!started){g.fillStyle=L.ink;g.font='600 14px system-ui,sans-serif';g.textAlign='center';g.fillText('Приготовься…',w/2,ly-8>14?ly-8:14);}
  // step-budget bar under the field
  const bw=plan.w*cell,used=Math.min(plan.budget,s.used);
  g.fillStyle=isNight()?'#ffffff22':'#00000018';rrect(g,lx,ly+plan.h*cell+8,bw,8,4);g.fill();
  g.fillStyle=used>=plan.budget?'#d9805c':'#4f9d5d';rrect(g,lx,ly+plan.h*cell+8,bw*(1-used/plan.budget),8,4);g.fill();
 }

 layout();paintStat();
 window.addEventListener('resize',layout);
 const resizeObs=typeof ResizeObserver==='function'?new ResizeObserver(()=>{if(!closed)layout();}):null;resizeObs?.observe(stage);
 raf=requestAnimationFrame(draw);
 layoutTimer=setTimeout(()=>{layoutTimer=0;if(!closed)layout();},60);
 showIntro();
 return {close:finishClose,requestClose:backClose};
}
