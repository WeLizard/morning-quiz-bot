// «Битва с Сантой» (docs/tasks/FARM_SANTA_BATTLE.md §4, §5, §8): the battle screen, a nested view like pie-game.js.
// The battle runs locally on santa-battle-engine.js (the mirror of domain/farm_santa_battle.py); every hero move goes into
// the log, which is sent once with vgame_finish. The scene and the fighters come from santa-battle-{scene,night}.svg
// (generator scripts/art/village_games/santa_battle.js): the screen places <use href="#sb-<who>-<pose>"> in #sb-stage.
import {BAR_MS,MAX_ITEMS,HEROES,BATTLES,ATTACKS,SKILLS,newState,act,actor,legal} from './santa-battle-engine.js';

const GAME='santa_battle',NS='http://www.w3.org/2000/svg';
export const STEP_MS=760,STEP_MS_CALM=650,CALM_KEY='qw-farm.santa-calm';
export const BATTLE_NAMES={1:'Крампус пришёл первым',2:'Санта и его мешок',3:'Хо-хо-хо на двоих'};
export const BASKET=['pie','pancake','gingerbread','tea','honey'];
export const MOVES={snowball:'Снежок',staff:'Посох',icestar:'Ледяная звёздочка',wall:'Снежная стена',blizzard:'Вьюга',freeze:'Заморозка',
 song:'Песенка',switch:'Розги',chain:'Цепь',roar:'Рык',coal:'Уголёк',candy:'Конфета',hohoho:'Хо-хо-хо',sack:'В мешок!',sleigh:'Олени'};
export const MOVE_HINTS={snowball:'12 одному',staff:'18 одному',icestar:'10 одному',wall:'удары по команде вдвое слабее до конца раунда',
 blizzard:'10 всем противникам',freeze:'противник пропустит ход',song:'+15 всем героям'};
export const ITEM_HINTS={pie:'+50 одному',pancake:'+25 одному',gingerbread:'+20 всем',tea:'снимает «Цепь», +10',honey:'следующий удар ×2'};
const NAMES={player:'Фермер',player_f:'Фермерша',ded_moroz:'Дед Мороз',snegurochka:'Снегурочка',krampus:'Крампус',santa:'Санта',reindeer:'Олени'};
const DATIVE={player:'фермеру',player_f:'фермерше',ded_moroz:'Деду Морозу',snegurochka:'Снегурочке',krampus:'Крампусу',santa:'Санте'};
const GENITIVE={player:'фермера',player_f:'фермерши',ded_moroz:'Деда Мороза',snegurochka:'Снегурочки',krampus:'Крампуса',santa:'Санты'};
const reduced=()=>!!globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
const clock=()=>globalThis.performance?.now?.()??Date.now();
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));

export function calmBattle(){try{return globalThis.localStorage?.getItem(CALM_KEY)==='true';}catch{return false;}}
// The player's fighter follows the address form (owner's decision 2026-11-19): «она» → the farmer woman.
export const playerLook=form=>form==='f'?'f':'m';
export function nameOf(who,look='m',form=NAMES){return form[who==='player'&&look==='f'?'player_f':who]||who;}
const dat=(who,look)=>nameOf(who,look,DATIVE),gen=(who,look)=>nameOf(who,look,GENITIVE);

// What an enemy announced for this round (§3: the next move is shown in advance; the plan has no hidden luck).
export function intentText(enemy,intent,look='m'){
 if(!intent)return '';
 const to=intent.target;
 switch(intent.move){
  case 'switch':return `Крампус: «Розги» по ${dat(to,look)}`;
  case 'chain':return `Крампус: «Цепь» — ${nameOf(to,look)} пропустит ход`;
  case 'roar':return 'Крампус: «Рык» — его удары сильнее на 2 раунда';
  case 'coal':return `Санта: «Подарок-сюрприз» — уголёк по ${dat(to,look)}`;
  case 'candy':return 'Санта: «Подарок-сюрприз» — конфета себе, +20';
  case 'hohoho':return 'Санта набирает воздух: «Хо-хо-хо» по всем';
  case 'sack':return 'Санта: «В мешок!» — следующий удар по нему пропадёт';
  default:return `${nameOf(enemy,look)}: ${MOVES[intent.move]||intent.move}`;
 }
}
export function intentLines(state,look='m'){
 const lines=state.enemies.filter(e=>state.hp[e]>0&&state.intents[e]).map(e=>intentText(e,state.intents[e],look));
 if(BATTLES[state.battle].reindeer&&state.round%4===0)lines.push('Олени: в конце раунда промчатся по площади, 12 всем');
 return lines;
}

// One hero move returns a flat list of events (engine act()); the screen plays it as steps: the hero's own action, then
// every enemy move with its hits, skipped turns and the start of the next round.
export function stepsOf(events,entry=null){
 const steps=[];let cur=null;
 for(const e of events){
  if(e.t==='move'){cur={who:e.who,move:e.move,to:e.to,events:[e]};steps.push(cur);continue;}
  if(e.t==='skip'||e.t==='round'||e.t==='timeout'){cur=null;steps.push({who:e.who??null,move:e.t,to:null,events:[e]});continue;}
  if(!cur){const who=e.by??e.who??null;cur={who,move:entry&&entry[0]===who?entry[1]:null,to:entry&&entry[0]===who?entry[2]:null,events:[]};steps.push(cur);}
  cur.events.push(e);
 }
 return steps;
}

function amountText(e){return e.t==='heal'?`+${e.amount}`:`−${e.amount}`;}
// The live-region line of a step: short, no gendered verb forms (the player may be «он», «она» or neutral).
export function stepText(step,look='m',items={}){
 const who=nameOf(step.who,look);
 if(step.move==='round')return `Раунд ${step.events[0].n}.`;
 if(step.move==='timeout')return 'Тридцать раундов позади — бой окончен.';
 if(step.move==='skip')return step.events[0].why==='chain'?`${who}: «Цепь» — пропуск хода.`:`${who}: «Заморозка» — пропуск хода.`;
 const hits=step.events.filter(e=>e.t==='hit'),heals=step.events.filter(e=>e.t==='heal'),miss=step.events.find(e=>e.t==='miss');
 const item=step.events.find(e=>e.t==='item');
 const parts=[];
 if(item)parts.push(`${who}: ${items[item.item]||item.item}${item.to&&item.to!==step.who?` для ${gen(item.to,look)}`:''}`);
 else parts.push(`${who}: «${MOVES[step.move]||step.move}»`);
 if(step.move==='chain')parts.push(`${nameOf(step.to,look)} пропустит ход`);
 if(step.move==='roar')parts.push('удары Крампуса сильнее на 2 раунда');
 if(step.move==='sack')parts.push('Санта спрятался в мешок');
 if(step.move==='wall')parts.push('команда за стеной до конца раунда');
 if(step.move==='freeze')parts.push(`${nameOf(step.to,look)} пропустит ход`);
 if(item?.item==='honey')parts.push('следующий удар ×2');
 if(item?.item==='tea')parts.push('«Цепь» снята');
 if(miss)parts.push('удар пропал в мешке');
 for(const e of hits)parts.push(`${nameOf(e.to,look)} ${amountText(e)}${e.bonus?' (точно!)':''}`);
 for(const e of heals)if(e.amount>0)parts.push(`${nameOf(e.to,look)} ${amountText(e)}`);
 const down=step.events.filter(e=>e.t==='down').map(e=>nameOf(e.who,look));
 if(down.length)parts.push(`в сугробе: ${down.join(', ')}`);
 return parts.join(' · ')+'.';
}

function stars(n){return '★'.repeat(n)+'☆'.repeat(3-n);}
export function starsText(n){return `${stars(n)} — ${n===0?'звёзд нет':n===1?'1 звезда':`${n} звезды`}`;}
export function resultText(result,reward=null){
 if(!result)return '';
 if(result.outcome==='expired')return 'Время боя вышло. Можно начать снова.';
 if(result.outcome==='basket')return 'В амбаре не хватило припасов из «Корзинки» — бой не засчитан, ничего не списано.';
 const used=Object.values(result.items||{}).reduce((a,b)=>a+b,0),spent=used?` Из «Корзинки» съедено: ${used}.`:'';
 if(result.outcome==='lose')return `Бой ${result.battle} проигран за ${result.rounds} р.${spent} Попробуй ещё раз — поражение ничего не отнимает.`;
 return `Победа в бою ${result.battle}! ${stars(result.stars)} за ${result.rounds} р.${spent}${result.reward?` Награда: «${reward||result.reward}».`:''}`;
}
// Why a battle cannot be started now (or '' when it can).
export function lockText(row,{locked=false,minLevel=5,available=true}={},fmt=t=>new Date(t*1000).toLocaleDateString('ru-RU',{day:'numeric',month:'long',timeZone:'Europe/Moscow'})){
 if(!available)return 'Бои идут в Новый год, с 20 декабря по 14 января.';
 if(locked)return `С ${minLevel} уровня.`;
 if(row.open)return '';
 if(row.opens_at&&Date.now()/1000<row.opens_at)return `Откроется ${fmt(row.opens_at)}.`;
 return `После победы в бою ${row.n-1}.`;
}
// Basket items left for this battle: the barn stock minus what the log already used; none after three.
export function basketLeft(item,stockOf,state){
 if(!state||state.n_items>=MAX_ITEMS)return 0;
 return Math.max(0,stockOf(item)-(state.items[item]||0));
}

export function mountSantaBattle(host,{getState,command,onBack,isCommandPending=()=>false,stockOf=()=>0,itemName=id=>id,icon=null,look=()=>'m',storageKey='farm'}){
 let disposed=false,sceneEpoch=0,theme='',scene=null,local=null,submitting=false,phase='idle',chosen=null,barRun=null,lastMove=0;
 let view=null,transient={};
 const savedLogs=new Map();
 const logKey=id=>`mqb-santa:${storageKey}:${id}`;
 function saveLog(){if(!local)return;const value=JSON.stringify(local.log);savedLogs.set(logKey(local.run_id),value);try{sessionStorage.setItem(logKey(local.run_id),value);}catch{}}
 function loadLog(id){try{const value=savedLogs.get(logKey(id))||sessionStorage.getItem(logKey(id));return value?JSON.parse(value):[];}catch{return [];}}
 function clearLog(id){savedLogs.delete(logKey(id));try{sessionStorage.removeItem(logKey(id));}catch{}}
 const clone=s=>JSON.parse(JSON.stringify(s));
 const L=()=>look();

 host.hidden=false;
 host.innerHTML=`<div class="sb-page"><div class="sb-title"><h1>Битва с Сантой</h1><button class="sb-back" type="button">‹ В деревню</button></div><p class="sb-intro">Дед Мороз спорит с Сантой, кто главный по подаркам. Спор решает снежная дуэль на площади у ёлки: ты, Дед Мороз и Снегурочка против Санты и Крампуса. Ходы по очереди, без спешки.</p><div class="sb-layout"><div class="sb-stage-card"><div class="sb-scene" aria-hidden="true"></div><div class="sb-plates" aria-label="Здоровье"></div></div><section class="sb-controls" aria-label="Ход в бою"><p class="sb-status" role="status" aria-live="polite"></p><div class="sb-intents" aria-label="Противник объявил"></div><div class="sb-panel"></div><p class="sb-rules"></p></section></div></div>`;
 const $=s=>host.querySelector(s),stage=$('.sb-scene'),plates=$('.sb-plates'),status=$('.sb-status'),intents=$('.sb-intents'),panel=$('.sb-panel'),rules=$('.sb-rules');
 const state=()=>getState()||null;
 const pending=()=>submitting||isCommandPending();
 function setText(node,text){if(node.textContent!==text)node.textContent=text;}
 function make(tag,attrs={},text=null){const node=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))node.setAttribute(k,String(v));if(text!==null)node.textContent=text;return node;}
 function h(tag,cls,text){const node=document.createElement(tag);if(cls)node.className=cls;if(text!=null)node.textContent=text;return node;}
 function btn(label,onClick,cls='qw-btn secondary',disabled=false){const b=h('button',cls,label);b.type='button';b.disabled=!!disabled;b.addEventListener('click',onClick);return b;}

 // ---------- scene ----------
 async function loadScene(){
  const next=globalThis.document?.documentElement?.dataset?.farmTheme==='night'?'night':'day';if(theme===next)return;theme=next;const epoch=++sceneEpoch;
  try{const response=await fetch(`/app/farm/assets/santa-battle-${next==='night'?'night':'scene'}.svg`);if(!response.ok)throw new Error('scene');const svg=await response.text();if(disposed||epoch!==sceneEpoch)return;stage.innerHTML=svg;setupScene();}
  catch{if(!disposed&&epoch===sceneEpoch){theme='';scene=null;stage.textContent='Не удалось загрузить площадь. Проверь соединение и открой игру снова.';}}
 }
 function setupScene(){
  const svg=stage.querySelector('svg');if(!svg){scene=null;return;}
  let anchors={};try{anchors=JSON.parse(svg.getAttribute('data-anchors'));}catch{}
  const root=svg.querySelector('#sb-stage');
  root.replaceChildren();
  const ring=make('g',{class:'sb-ring-layer'}),fighters=make('g',{class:'sb-fighters'}),marks=make('g',{class:'sb-marks'}),fx=make('g',{class:'sb-fx'});
  root.append(ring,fighters,marks,fx);
  svg.removeAttribute('role');
  scene={svg,anchors,k:+svg.getAttribute('data-scale')||4,ring,fighters,marks,fx};
  draw();
 }
 function at(who){
  if(!scene)return [0,0];
  if(who==='reindeer')return [500,420];
  const solo=view&&view.enemies.length===1&&view.enemies.includes(who);
  return scene.anchors[solo?'solo':who]||[500,500];
 }
 const isEnemy=who=>who==='krampus'||who==='santa';
 const defOf=(who,pose)=>who==='santa'&&pose==='hide'?'sb-santa-hide':`sb-${who==='player'&&L()==='f'?'player_f':who}-${pose}`;
 function poseOf(who){
  if(transient[who])return transient[who];
  if(!view)return 'stand';
  if(view.hp[who]===0)return 'down';
  if(view.outcome==='win'&&!isEnemy(who))return 'win';
  if(view.outcome==='lose'&&isEnemy(who))return 'win';
  if(who==='santa'&&view.sack)return 'hide';
  return 'stand';
 }
 function use(href,x,y,sx,sy=Math.abs(sx)){return make('use',{href:'#'+href,transform:`translate(${x} ${y}) scale(${sx} ${sy})`});}
 function draw(){
  if(!scene)return;
  scene.fighters.replaceChildren();scene.ring.replaceChildren();scene.marks.replaceChildren();
  if(!view){
   // no battle: the whole company waits on the square
   for(const who of [...HEROES,'krampus','santa']){const [x,y]=scene.anchors[who]||[500,500],g=make('g',{'data-who':who,class:'sb-fighter'});g.append(use(defOf(who,'stand'),x,y,isEnemy(who)?-scene.k:scene.k,scene.k));scene.fighters.append(g);}
   return;
  }
  const k=scene.k,list=[...HEROES,...view.enemies],turn=phase!=='anim'&&!view.outcome?actor(view):null;
  // the active hero stands on a gold ring; the chosen target gets a dashed one
  if(turn){const [x,y]=at(turn);scene.ring.append(make('ellipse',{cx:x,cy:y+4,rx:64,ry:15,fill:'none',stroke:'#f2c94c','stroke-width':7,class:'sb-ring'}));}
  for(const who of list){
   const [x,y]=at(who),pose=poseOf(who),g=make('g',{'data-who':who,class:'sb-fighter'});
   g.append(use(defOf(who,pose),x,y,isEnemy(who)?-k:k,k));
   scene.fighters.append(g);
  }
  // lasting states: a snow wall in front of the heroes, the chain, the freeze, Krampus's roar, honey
  if(view.wall)for(const who of HEROES)if(view.hp[who]>0){const [x,y]=at(who);scene.marks.append(use('sb-fx-wall',x+58,y-2,k*.9));}
  for(const who of view.chain){const [x,y]=at(who);scene.marks.append(use('sb-fx-chain',x,y-64,k*.9));}
  for(const who of view.frozen){const [x,y]=at(who);scene.marks.append(use('sb-fx-freeze',x,y,k));}
  if(view.rage&&view.hp.krampus>0){const [x,y]=at('krampus');scene.marks.append(use('sb-fx-rage',x,y-150,k*.9));}
  for(const who of view.honey){const [x,y]=at(who);const s=make('use',{href:'/app/farm/assets/icons.svg#honey',x:x-70,y:y-230,width:52,height:52});scene.marks.append(s);}
 }
 function fly(name,from,to,ms,scale){
  if(!scene)return Promise.resolve();
  const node=use(`sb-fx-${name}`,to[0],to[1],scale);scene.fx.append(node);
  if(reduced()){return wait(Math.min(ms,240)).then(()=>node.remove());}
  return new Promise(resolve=>{
   const t0=clock();
   const step=()=>{if(disposed){resolve();return;}
    const t=Math.min(1,(clock()-t0)/ms),x=from[0]+(to[0]-from[0])*t,y=from[1]+(to[1]-from[1])*t-Math.sin(Math.PI*t)*60;
    node.setAttribute('transform',`translate(${x.toFixed(1)} ${y.toFixed(1)}) scale(${scale})`);
    if(t<1)requestAnimationFrame(step);else{node.remove();resolve();}};
   requestAnimationFrame(step);
  });
 }
 function flash(name,where,scale,ms=STEP_MS-80){if(!scene)return;const node=use(`sb-fx-${name}`,where[0],where[1],scale);node.classList.add('sb-flash');scene.fx.append(node);setTimeout(()=>node.remove(),ms);}
 function number(who,text,kind){
  if(!scene)return;const [x,y]=at(who);
  const node=make('text',{x,y:y-200,'text-anchor':'middle',class:`sb-num sb-num-${kind}`},text);
  scene.fx.append(node);setTimeout(()=>node.remove(),reduced()?STEP_MS:1100);
 }
 const chest=who=>{const [x,y]=at(who);return [x,y-100];};

 async function playStep(step){
  const k=scene?.k||4,who=step.who;
  setText(status,stepText(step,L(),Object.fromEntries(BASKET.map(i=>[i,itemName(i)]))));
  if(step.move==='round'||step.move==='timeout'){
   // the enemy phase ended: the wall falls, the roar fades, Snegurochka's freeze on a fallen enemy is gone
   if(step.move==='round'){view.round=step.events[0].n;view.wall=false;view.rage=Math.max(0,view.rage-1);draw();renderPlates();}
   await wait(reduced()?STEP_MS_CALM:STEP_MS);return;}
  if(step.move==='skip'){if(step.events[0].why==='chain')view.chain=view.chain.filter(x=>x!==who);else view.frozen=view.frozen.filter(x=>x!==who);draw();await wait(STEP_MS_CALM);return;}
  if(who&&who!=='reindeer'&&!step.events.some(e=>e.t==='item'))transient[who]='attack';
  draw();
  const hits=step.events.filter(e=>e.t==='hit'||e.t==='miss'),move=step.move;
  // the throw or the strike, then the hits land together
  const projectile={snowball:'snowball',icestar:'icestar',coal:'coal'}[move];
  if(projectile&&hits.length)await fly(projectile,chest(who),chest(hits[0].to),reduced()?200:380,k*1.3);
  else if(move==='sleigh'){if(!reduced())await fly('sleigh',[1080,300],[-80,330],700,k*1.4);}
  else await wait(reduced()?120:240);
  if(move==='blizzard')for(const e of hits)flash('blizzard',chest(e.to),k*1.4);
  if(move==='switch'&&hits[0])flash('switch',chest(hits[0].to),k*1.1);
  if(move==='song')flash('notes',[at(who)[0]+40,at(who)[1]-190],k);
  if(move==='candy')flash('candy',[at('santa')[0]-30,at('santa')[1]-150],k*1.2);
  if(move==='coal'||move==='candy')flash('gift',[at('santa')[0]-60,at('santa')[1]-60],k);
  for(const e of step.events){
   if(e.t==='hit'){view.hp[e.to]=Math.max(0,view.hp[e.to]-e.amount);transient[e.to]='hurt';flash('hit',chest(e.to),k*(e.bonus?1.1:.8));number(e.to,amountText(e),e.bonus?'bonus':isEnemy(e.to)?'hit':'ouch');}
   else if(e.t==='miss'){view.sack=false;number(e.to,'мимо','miss');}
   else if(e.t==='heal'){view.hp[e.to]=Math.min(view.max[e.to],view.hp[e.to]+e.amount);if(e.amount>0){flash('heal',[at(e.to)[0]+50,at(e.to)[1]-150],k*.9);number(e.to,amountText(e),'heal');}}
   else if(e.t==='wall')view.wall=true;
   else if(e.t==='freeze'){if(!view.frozen.includes(e.to))view.frozen.push(e.to);}
   else if(e.t==='item'){if(e.item==='honey'&&!view.honey.includes(e.to))view.honey.push(e.to);if(e.item==='tea')view.chain=view.chain.filter(x=>x!==e.to);}
   else if(e.t==='down'){view.hp[e.who]=0;delete transient[e.who];}
  }
  if(move==='chain'&&step.to&&!view.chain.includes(step.to))view.chain.push(step.to);
  if(move==='roar')view.rage=3;
  if(move==='sack')view.sack=true;
  if(who&&HEROES.includes(who)&&(ATTACKS[move]||move==='blizzard'))view.honey=view.honey.filter(x=>x!==who);
  draw();renderPlates();
  await wait(reduced()?STEP_MS_CALM-120:STEP_MS);
  transient={};for(const e of step.events)if(e.t==='down')delete transient[e.who];
  draw();
 }

 // ---------- the run ----------
 function begin(active){
  // a reopened battle continues from the saved log; a log that no longer replays starts the battle over
  const plan=active.plan;let s=newState(plan),log=loadLog(active.run_id);
  try{for(const entry of log)act(plan,s,entry);}catch{s=newState(plan);log=[];}
  begin2(active,s,log);
 }
 function begin2(active,s,log){
  local={run_id:active.run_id,plan:active.plan,battle:active.battle,state:s,log,ended:!!s.outcome};
  view=clone(s);phase=s.outcome?'done':'pick';chosen=null;transient={};
  if(s.outcome)void submit();
 }
 function choose(action,target=null){
  if(!local||phase==='anim'||phase==='done')return;
  const move=legal(local.state).find(m=>m[0]===action);if(!move)return;
  if(move[1].length&&target===null){
   // one possible target needs no question
   if(move[1].length===1)target=move[1][0];
   else{chosen={action,targets:move[1]};phase='target';renderPanel();return;}
  }
  chosen={action,target};
  const needsBar=(ATTACKS[action]||action==='blizzard')&&!calmBattle();
  if(needsBar){phase='bar';renderPanel();startBar();return;}
  void commit(null);
 }
 function startBar(){
  const zone=local.plan.zones[local.state.bar%local.plan.zones.length];
  const track=panel.querySelector('.sb-bar-track'),runner=panel.querySelector('.sb-bar-run'),z=panel.querySelector('.sb-bar-zone');
  if(z){z.style.left=`${zone[0]/BAR_MS*100}%`;z.style.width=`${(zone[1]-zone[0])/BAR_MS*100}%`;}
  barRun={t0:clock(),raf:0,zone};
  const tick=()=>{if(!barRun||disposed)return;const t=clock()-barRun.t0;
   if(runner)runner.style.left=`${Math.min(100,t/BAR_MS*100)}%`;
   if(t>=BAR_MS){press();return;}
   barRun.raf=requestAnimationFrame(tick);};
  barRun.raf=requestAnimationFrame(tick);
  track?.focus?.({preventScroll:true});
 }
 function press(){
  if(!barRun)return;cancelAnimationFrame(barRun.raf);
  const ms=Math.max(0,Math.min(BAR_MS,Math.round(clock()-barRun.t0)));barRun=null;
  void commit(ms);
 }
 async function commit(pressMs){
  if(!local||!chosen)return;
  const hero=actor(local.state),entry=[hero,chosen.action,chosen.target??null,pressMs];
  const before=view;let events;
  try{events=act(local.plan,local.state,entry);}catch{phase='pick';chosen=null;renderPanel();return;}
  local.log.push(entry);saveLog();chosen=null;phase='anim';lastMove=clock();
  view=before;renderPanel();draw();
  for(const step of stepsOf(events,entry)){if(disposed)return;await playStep(step);}
  if(disposed)return;
  view=clone(local.state);transient={};
  // the server rejects a log played faster than 0.6 s a move: the animation is longer anyway, this is the floor
  const left=STEP_MS_CALM-(clock()-lastMove);if(left>0)await wait(left);
  if(local.state.outcome){phase='done';local.ended=true;draw();renderAll();void submit();return;}
  phase='pick';draw();renderAll();
  panel.querySelector('.qw-btn.primary')?.focus?.({preventScroll:true});
 }
 async function submit(){
  if(disposed||submitting||!local)return;
  submitting=true;renderAll();
  try{await command('vgame_finish',{game:GAME,run_id:local.run_id,log:local.log.slice()});clearLog(local.run_id);}
  catch(e){if(!disposed)setText(status,e?.message||'Не удалось сохранить бой.');}
  finally{submitting=false;if(!disposed)renderAll();}
 }
 async function start(battle){
  if(pending())return;submitting=true;renderAll();
  try{await command('vgame_start',{game:GAME,battle});}catch(e){if(!disposed)setText(status,e?.message||'Не удалось начать бой.');}
  finally{submitting=false;if(!disposed)renderAll();}
 }

 // ---------- panels ----------
 function plate(who){
  const max=view.max[who],hp=view.hp[who],row=h('div',`sb-plate${isEnemy(who)?' enemy':''}${hp===0?' down':''}${phase!=='anim'&&!view.outcome&&actor(view)===who?' active':''}`);
  row.setAttribute('role','listitem');
  const top=h('div','sb-plate-top');top.append(h('strong','sb-plate-name',nameOf(who,L())),h('span','sb-plate-hp',`${hp} / ${max}`));
  const bar=h('div','sb-hp');bar.setAttribute('aria-hidden','true');const fill=h('span');fill.style.width=`${Math.round(hp/max*100)}%`;bar.append(fill);
  const chips=h('div','sb-chips');
  const chip=(icon,text)=>chips.append(h('span','sb-chip',`${icon} ${text}`));
  if(hp===0)chip('❄','в сугробе');
  if(view.chain.includes(who))chip('⛓','Цепь: пропуск хода');
  if(view.frozen.includes(who))chip('🧊','Заморозка');
  if(view.wall&&!isEnemy(who)&&hp>0)chip('🧱','Стена');
  if(view.honey.includes(who))chip('🍯','Мёд ×2');
  if(who==='krampus'&&view.rage)chip('💢','Рык');
  if(who==='santa'&&view.sack)chip('🎒','В мешке');
  row.setAttribute('aria-label',`${nameOf(who,L())}: ${hp} из ${max}`);
  row.append(top,bar);if(chips.childElementCount)row.append(chips);
  return row;
 }
 function renderPlates(){
  plates.replaceChildren();if(!view)return;
  for(const [label,list] of [['Команда',HEROES],['Противники',view.enemies]]){
   const col=h('div','sb-side');col.setAttribute('role','list');col.setAttribute('aria-label',label);
   col.append(...list.map(plate));plates.append(col);
  }
 }
 function renderIntents(){
  intents.replaceChildren();
  if(!view||view.outcome||!local)return;
  intents.append(h('p','sb-intents-title',`Раунд ${view.round} · противник объявил:`));
  for(const line of intentLines(view,L()))intents.append(h('p','sb-intent',line));
 }
 function battleList(s){
  const wrap=h('div','sb-battles');let primaryUsed=false;
  for(const row of s.battles||[]){
   const card=h('div','sb-battle qw-action-row');
   const text=h('div','sb-battle-text');
   text.append(h('strong',null,`Бой ${row.n} · ${BATTLE_NAMES[row.n]}`));
   text.append(h('span','sb-battle-stars',row.stars?`${starsText(row.stars)} · лучший бой: ${row.rounds} р.`:'Ещё не пройден.'));
   text.append(h('span',null,`Три звезды — победа без потерь не дольше ${row.par} р.`));
   text.append(h('span','sb-battle-reward',`Награда за первую победу: «${row.reward.name}»${row.reward.got?' — уже в коллекции':''}`));
   const why=lockText(row,{locked:s.locked,minLevel:s.min_level,available:s.available});
   const col=h('div','sb-battle-act');
   const primary=!why&&!row.stars&&!primaryUsed;if(primary)primaryUsed=true;
   col.append(btn(row.stars?'Реванш':'В бой',()=>start(row.n),primary?'qw-btn primary':'qw-btn secondary',!!why||pending()));
   if(why)col.append(h('small','sb-why',why));
   card.append(text,col);wrap.append(card);
  }
  return wrap;
 }
 function renderPanel(){
  panel.replaceChildren();
  const s=state();
  if(!local||phase==='idle'){
   if(s)panel.append(battleList(s));
   return;
  }
  if(phase==='done'){
   panel.append(h('p','sb-wait',submitting?'Сохраняем бой…':'Бой окончен, но сохранить не удалось.'));
   if(!submitting)panel.append(btn('Сохранить снова',()=>void submit(),'qw-btn primary'));
   return;
  }
  if(phase==='anim'){panel.append(h('p','sb-wait','Ходы противника…'));return;}
  const hero=actor(local.state),moves=legal(local.state),name=nameOf(hero,L());
  panel.append(h('p','sb-turn',`Ход: ${name}`));
  if(phase==='target'){
   const enemyTarget=chosen.targets.some(isEnemy);
   panel.append(h('p','sb-ask',enemyTarget?'По кому?':'Кому?'));
   const row=h('div','qw-btn-row sb-targets');
   for(const t of chosen.targets)row.append(btn(`${nameOf(t,L())} · ${local.state.hp[t]}`,()=>choose(chosen.action,t)));
   panel.append(row,btn('Назад',()=>{phase=chosen.basket?'basket':'pick';chosen=null;renderPanel();},'qw-btn text'));
   return;
  }
  if(phase==='bar'){
   const wrap=h('div','sb-bar');
   wrap.append(h('p','sb-ask','Жми в жёлтой зоне — удар ×1,5'));
   const track=h('div','sb-bar-track');track.tabIndex=0;track.setAttribute('role','button');track.setAttribute('aria-label','Полоска меткости: нажми, когда бегунок в жёлтой зоне');
   track.append(h('span','sb-bar-zone'),h('span','sb-bar-run'));
   track.addEventListener('pointerdown',e=>{e.preventDefault();press();});
   track.addEventListener('keydown',e=>{if(e.key===' '||e.key==='Enter'){e.preventDefault();press();}});
   wrap.append(track,btn('Бросок!',press,'qw-btn primary sb-throw'));
   panel.append(wrap);return;
  }
  if(phase==='basket'){
   panel.append(h('p','sb-ask',`«Корзинка»: ещё ${MAX_ITEMS-local.state.n_items} из ${MAX_ITEMS} за бой`));
   const list=h('div','sb-basket');
   for(const item of BASKET){
    const left=basketLeft(item,stockOf,local.state),row=h('div','sb-item qw-action-row'),text=h('div','sb-item-text');
    if(icon){const i=icon(item);i.classList?.add('sb-item-icon');text.append(i);}
    const words=h('div');words.append(h('strong',null,itemName(item)),h('small',null,`${ITEM_HINTS[item]} · в амбаре: ${left}`));text.append(words);
    const col=h('div');col.append(btn('Дать',()=>{const m=moves.find(x=>x[0]===item);if(!m)return;if(m[1].length>1){chosen={action:item,targets:m[1],basket:true};phase='target';renderPanel();}else choose(item,m[1][0]??null);},'qw-btn secondary',left<=0));
    row.append(text,col);list.append(row);
   }
   panel.append(list,btn('Назад',()=>{phase='pick';renderPanel();},'qw-btn text'));
   return;
  }
  // pick: the hero's own move first (primary), the skills, then the basket
  const stack=h('div','qw-btn-stack sb-moves');
  for(const [action,[owner]] of Object.entries(ATTACKS))if(owner===hero){
   stack.append(moveButton(MOVES[action],MOVE_HINTS[action],()=>choose(action),'qw-btn primary'));
  }
  for(const [skill,[owner]] of Object.entries(SKILLS))if(owner===hero){
   const cd=local.state.cd[skill],ok=moves.some(m=>m[0]===skill);
   stack.append(moveButton(MOVES[skill],ok?MOVE_HINTS[skill]:`через ${cd} р.`,()=>choose(skill),'qw-btn secondary',!ok));
  }
  const room=MAX_ITEMS-local.state.n_items;
  stack.append(moveButton('«Корзинка»',room>0?`припасы фермы · ещё ${room}`:'три предмета уже съедены',()=>{phase='basket';renderPanel();},'qw-btn secondary',room<=0));
  panel.append(stack);
 }
 function moveButton(label,hint,onClick,cls,disabled=false){
  const b=btn('',onClick,`${cls} sb-move`,disabled);b.append(h('span','sb-move-name',label),h('small','sb-move-hint',hint));return b;
 }
 function renderAll(){
  if(disposed)return;
  void loadScene();
  const s=state(),active=s?.active;
  if(active&&(!local||local.run_id!==active.run_id))begin(active);
  if(!active&&local&&!submitting){local=null;view=null;phase='idle';transient={};}
  if(!local)phase='idle';
  if(local&&phase!=='anim'&&phase!=='bar')view=clone(local.state);
  renderPlates();renderIntents();renderPanel();draw();
  if(phase==='idle'){
   if(!s?.available)setText(status,'Битва ждёт Нового года: с 20 декабря Дед Мороз зовёт на площадь.');
   else if(s.last_result){const reward=s.last_result.reward?(s.battles||[]).find(b=>b.reward.id===s.last_result.reward)?.reward.name:null;setText(status,resultText(s.last_result,reward));}
   else setText(status,'Выбери бой. Каждый новый бой открывается по дате и после победы в прошлом.');
  }
  rules.textContent=calmBattle()
   ?'Спокойный бой включён: полоски меткости нет, удары обычные. Выключить — ⚙ → «Настройки фермы».'
   :'Полоска меткости даёт только бонус: удар в жёлтой зоне ×1,5. Без неё бои тоже выигрываются — «Спокойный бой» в ⚙ → «Настройки фермы». Предметы «Корзинки» тратятся из амбара; награда — праздничный предмет за первую победу в каждом бою, без монет и опыта.';
 }
 stage.addEventListener('click',event=>{
  const g=event.target.closest?.('[data-who]');if(!g||phase!=='target'||!chosen)return;
  const who=g.getAttribute('data-who');if(chosen.targets.includes(who))choose(chosen.action,who);
 });
 $('.sb-back').addEventListener('click',onBack);
 const observer=new MutationObserver(records=>{if(records.some(r=>r.attributeName==='data-farm-theme')){theme='';void loadScene();}});
 observer.observe(document.documentElement,{attributes:true,attributeFilter:['data-farm-theme']});
 renderAll();
 return {render:renderAll,destroy(){disposed=true;sceneEpoch++;if(barRun)cancelAnimationFrame(barRun.raf);barRun=null;observer.disconnect();host.hidden=true;host.replaceChildren();}};
}
