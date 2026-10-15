/* Farm r9 stage 15B: top-down field minigames (cultivator, seeder, combine).
 *
 * The first half is a 1:1 port of the server rules in qw_farm/fields.py (integers only, no floats, no hashing). The client uses it
 * ONLY to show a quality forecast; the server replays the path itself and decides. The second half is the DOM/canvas game.
 * Pure helpers come first and touch no DOM so tests/js/farm_tractor.test.cjs can run them in a bare vm context.
 */
export const DEFAULTS={hopper:18,qBase:850,qSpan:250,qAuto:950,stepCs:12,autoS:90,maxPath:2000,weedWeight:3,fullK:250,zeroK:600,runTtl:1800};
const DIRS={U:[0,-1],D:[0,1],L:[-1,0],R:[1,0]};
const idiv=(a,b)=>(a-a%b)/b;                       // exact integer division for non-negative integers

/* ---------------------------------------------------------------- pure rules (see fields.py) */
export function stepAnchor(x,y,ch,W,H,width,rocks){
 const d=DIRS[ch];if(!d)return null;
 const nx=x+d[0],ny=y+d[1];
 if(nx<0||nx>W-width||ny<0||ny>=H)return null;
 for(let i=0;i<width;i++)if(rocks.has(ny*W+nx+i))return null;
 return [nx,ny];
}
export function reachableAnchors(W,H,width,rocks){
 const seen=new Set([0]),todo=[[0,0]];
 while(todo.length){
  const [x,y]=todo.pop();
  for(const ch of 'UDLR'){
   const n=stepAnchor(x,y,ch,W,H,width,rocks);
   if(n&&!seen.has(n[1]*W+n[0])){seen.add(n[1]*W+n[0]);todo.push(n);}
  }
 }
 return seen;                                     // anchor keys y*W+x (x < W always)
}
export function cellsOfAnchors(anchors,W,width){
 const cells=new Set();
 for(const k of anchors){const x=k%W,y=(k-x)/W;for(let i=0;i<width;i++)cells.add(y*W+x+i);}
 return cells;
}
export function grade(cov,ov){
 const score=Math.min(1000,idiv(Math.max(0,cov-600)*1000,380));
 return Math.max(0,score-idiv(300*Math.max(0,ov-250),1000));
}
export function quality(score,cfg=DEFAULTS){return cfg.qBase+idiv(cfg.qSpan*score,1000);}
/* Runs opened since the owner's 2026-10-14 decision carry run.qrule===2: the bonus over the autopilot melts with the time of the run. */
export const QRULE_TIMED=2;
export function timeLimits(ha,width,cfg=DEFAULTS){const a=autoSeconds(ha,width,1,cfg);return {auto:a,full:idiv(a*cfg.fullK,100),zero:idiv(a*cfg.zeroK,100)};}
/** Share of the bonus that is still kept after ``elapsed`` whole seconds, permille (fields.timed_quality). */
export function timeKeep(elapsed,ha,width,cfg=DEFAULTS){
 const {full,zero}=timeLimits(ha,width,cfg);
 return elapsed<=full?1000:elapsed>=zero?0:idiv((zero-elapsed)*1000,zero-full);
}
export function timedQuality(score,elapsed,ha,width,cfg=DEFAULTS){
 const q=quality(score,cfg),bonus=q-cfg.qAuto;
 return bonus<=0?q:cfg.qAuto+idiv(bonus*timeKeep(elapsed,ha,width,cfg),1000);
}
export function growthPermille(qCult){return 1950-qCult;}
export function yieldQty(base,qSow,qHarvest){return Math.max(1,idiv(base*qSow*qHarvest,1000000));}
export function autoSeconds(ha,width,speed=1,cfg=DEFAULTS){return Math.max(1,Math.ceil(cfg.autoS*ha/width/speed));}
export function maxPath(field,run,cfg=DEFAULTS){return Math.min(idiv(3*field.w*field.h,run.width),cfg.maxPath);}

/* One machine run. push() applies a single character exactly like fields._walk + simulate_<op>; score() is the permille score. */
export class Run{
 constructor(field,run,cfg=DEFAULTS){
  this.W=field.w;this.H=field.h;this.width=run.width;this.op=run.op;
  this.rocks=new Set(run.rocks||[]);this.weeds=new Set(run.weeds||[]);
  this.cap=cfg.hopper*this.width*idiv(this.H,this.W);
  this.weedWeight=cfg.weedWeight||DEFAULTS.weedWeight;
  this.anchors=reachableAnchors(this.W,this.H,this.width,this.rocks);
  this.cells=cellsOfAnchors(this.anchors,this.W,this.width);
  if(this.op==='sow'){
   const lanes=[...this.anchors].filter(k=>(k%this.W)%(this.width+1)===0);
   this.sowable=cellsOfAnchors(lanes,this.W,this.width);
   this.lanes=lanes;
  }
  this.total=0;
  if(this.op==='cultivate')for(const c of this.cells)this.total+=this.weeds.has(c)?this.weedWeight:1;
  this.reset();
 }
 reset(){
  this.x=0;this.y=0;this.t=0;this.path='';
  this.last=new Map();this.got=0;this.again=0;
  this.sown=new Set();this.doubles=0;this.doubled=new Set();
  this.load=0;this.kept=0;this.lost=new Set();this.unloads=0;
  this._arrive();
 }
 _arrive(){
  const base=this.y*this.W+this.x;
  if(this.op==='sow'){
   if(this.x%(this.width+1)===0)for(let i=0;i<this.width;i++){const c=base+i;if(this.sown.has(c)){this.doubles++;this.doubled.add(c);}else this.sown.add(c);}
   return;
  }
  for(let i=0;i<this.width;i++){
   const c=base+i;
   if(!this.last.has(c)){
    if(this.op==='cultivate')this.got+=this.weeds.has(c)?this.weedWeight:1;
    else if(this.load<this.cap){this.load++;this.kept++;}
    else this.lost.add(c);
   }else if(this.last.get(c)<this.t-1)this.again++;
   this.last.set(c,this.t);
  }
 }
 /** Apply one character; false (and no change) when the server would reject it. */
 push(ch){
  if(ch==='X'){
   if(this.op!=='harvest'||this.y!==0)return false;
   this.load=0;this.unloads++;this.path+=ch;return true;
  }
  const n=stepAnchor(this.x,this.y,ch,this.W,this.H,this.width,this.rocks);
  if(!n)return false;
  this.x=n[0];this.y=n[1];this.t++;this.path+=ch;this._arrive();return true;
 }
 undo(){
  const p=this.path.slice(0,-1);this.reset();
  for(const ch of p)this.push(ch);
 }
 /** Coverage in permille of what counts for the forecast (weighted for cultivation). */
 coverage(){
  if(this.op==='cultivate')return idiv(this.got*1000,this.total);
  if(this.op==='sow')return idiv(this.sown.size*1000,this.sowable.size);
  return idiv(this.kept*1000,this.cells.size);
 }
 overlap(){return this.op==='sow'?idiv(this.doubles*1000,this.sowable.size):idiv(this.again*1000,this.last.size);}
 score(){
  const cov=this.coverage();
  if(this.op==='sow')return Math.max(0,Math.min(1000,idiv(Math.max(0,cov-600)*1000,380))-2*Math.max(0,this.overlap()-30));
  return grade(cov,this.overlap());
 }
}
/** simulate_<op> of fields.py: permille score, or null when the path is illegal. */
export function simulate(field,run,path,cfg=DEFAULTS){
 const r=new Run(field,run,cfg);
 for(const ch of path)if(!r.push(ch))return null;
 return r.score();
}
export const simulateCultivate=(f,r,p,c)=>simulate(f,{...r,op:'cultivate'},p,c);
export const simulateSow=(f,r,p,c)=>simulate(f,{...r,op:'sow'},p,c);
export const simulateHarvest=(f,r,p,c)=>simulate(f,{...r,op:'harvest'},p,c);

/* ---------------------------------------------------------------- texts */
const pctText=permille=>(permille/10).toFixed(1).replace('.',',')+'%';
export function effectLines(op,q,{item='',qty=0,qSow=0}={}){
 const lines=[`Качество ${pctText(q)}`];
 if(op==='cultivate'){const d=Math.abs(1000-growthPermille(q))/10;lines.push(growthPermille(q)<=1000?`Урожай созреет быстрее на ${String(d).replace('.',',')}%`:`Урожай созреет медленнее на ${String(d).replace('.',',')}%`);}
 else if(op==='sow')lines.push(`Урожай ×${(q/1000).toFixed(2).replace('.',',')} от нормы`);
 else lines.push(item?`Убрано: ${item} ×${qty}`:`Урожай ×${(q/1000).toFixed(2).replace('.',',')} от нормы`);
 return lines;
}
const TITLES={cultivate:'Культиватор',sow:'Сеялка',harvest:'Комбайн'};
const HELP={
 cultivate:'Проедь по всему полю: сорняки (тёмные кустики) весят втрое, камни объезжай. Повторные проезды по уже вспаханному снижают оценку.',
 sow:'Сей только по разметке: полосы шириной с машину, между ними пустой столбец. Не заезжай на засеянное повторно.',
 harvest:'Убирай полосами. Бункер вмещает не всё поле: когда он полон, урожай теряется. Заезжай на верхний край (к грузовику) и жми «Выгрузить».'
};

/* ---------------------------------------------------------------- the game UI */
const SPEEDS=[{id:'calm',label:'Спокойно',ms:450},{id:'normal',label:'Обычно',ms:320},{id:'fast',label:'Быстро',ms:180}];   // the server needs >= 120 ms per path character; every preset stays above
const SPEED_KEY='qw-farm.fieldSpeed';
function loadSpeed(){try{const i=SPEEDS.findIndex(x=>x.id===localStorage.getItem(SPEED_KEY));return i>=0?i:1;}catch{return 1;}}
function saveSpeed(i){try{localStorage.setItem(SPEED_KEY,SPEEDS[i].id);}catch{}}
const KEYS={ArrowUp:'U',KeyW:'U',ArrowDown:'D',KeyS:'D',ArrowLeft:'L',KeyA:'L',ArrowRight:'R',KeyD:'R'};
const PALETTE={
 wildA:'#cfe3a8',wildB:'#c5dc9d',weed:'#6f9a4d',tilled:'#b99069',furrow:'#a57e58',rock:'#aaa597',rockLight:'#cfcabc',
 lane:'#fff6d6',seed:'#6aa84f',double:'#d9805c',ripe:'#ecc86b',ripeStalk:'#cf9f3a',stubble:'#d9c58e',lost:'#d9805c',
 road:'#8c8a7d',roadLine:'#f1ecc9',grid:'#00000014'
};
const BODY={cultivate:'#e08e61',sow:'#78b18f',harvest:'#e9b949'};

function node(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
function rrect(g,x,y,w,h,r){g.beginPath();if(g.roundRect)g.roundRect(x,y,w,h,r);else g.rect(x,y,w,h);}
function btn(text,cls,fn){const b=node('button',cls,text);b.type='button';if(fn)b.onclick=fn;return b;}

/** Server catalog.fields (snake_case) over the local DEFAULTS; only positive integers are accepted. */
export function gameCfg(src){
 const pick=(k,d)=>{const v=src?.[k];return Number.isInteger(v)&&v>0?v:d;};
 return {...DEFAULTS,hopper:pick('hopper',DEFAULTS.hopper),stepCs:pick('step_cs',DEFAULTS.stepCs),qBase:pick('q_base',DEFAULTS.qBase),
  qSpan:pick('q_span',DEFAULTS.qSpan),qAuto:pick('q_auto',DEFAULTS.qAuto),autoS:pick('auto_s',DEFAULTS.autoS),maxPath:pick('max_path',DEFAULTS.maxPath),
  runTtl:pick('run_ttl',DEFAULTS.runTtl),fullK:pick('run_full_k',DEFAULTS.fullK),zeroK:pick('run_zero_k',DEFAULTS.zeroK)};
}
const mmss=sec=>{sec=Math.max(0,Math.ceil(sec));return `${Math.floor(sec/60)}:${String(sec%60).padStart(2,'0')}`;};
const reducedMotion=()=>{try{return !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;}catch{return false;}};

/**
 * opts: {field, run, cfg (catalog.fields), speed, timeText(seconds), itemName(id), cropSnapshot,
 *        serverNow() -> server unix seconds (for run.expires_at),
 *        onFinish(path|null) -> Promise<boolean>, fieldNow() -> field|null, onClose()}
 * Returns {close()}.
 */
export function openFieldGame(opts){
 const field=opts.field,run=opts.run,cfg=gameCfg(opts.cfg);
 const R=new Run(field,run,cfg),W=R.W,H=R.H,op=run.op;
 const limit=maxPath(field,run,cfg),autoSec=autoSeconds(field.ha||idiv(H,W),run.width,run.speed||opts.speed||1,cfg);
 const openedAt=performance.now();
 const timed=run.qrule===QRULE_TIMED,ha=field.ha||idiv(H,W),lim=timeLimits(ha,run.width,cfg);   // older open runs keep the plain quality (no time in the bonus)
 // whole seconds of the run on the SERVER clock (what fields._finish measures); falls back to the local clock without a started_at
 const elapsedNow=()=>Number.isFinite(run.started_at)&&typeof opts.serverNow==='function'?Math.max(0,Math.floor(opts.serverNow()-run.started_at)):Math.floor((performance.now()-openedAt)/1000);
 const qNow=(score,el=elapsedNow())=>timed?timedQuality(score,el,ha,run.width,cfg):quality(score,cfg);
 let sentElapsed=0;
 const remain0=Number.isFinite(run.expires_at)&&typeof opts.serverNow==='function'?run.expires_at-opts.serverNow():cfg.runTtl;   // seconds left of the server run
 const deadline=openedAt+Math.max(0,remain0)*1000;
 const prev=document.activeElement;
 let closed=false,sending=false,raf=0,last=0,lastStep=-1e9,cruise=null,padDir=null,done=false;
 let submitTimer=0,submitResolve=null,layoutTimer=0,confirming=false,expired=false,warned=false,shownLeft=-1,shakeUntil=0,shakeDir='U',lastBump=-1e9,srTimer=0;const tapQ=[];
 let routeQ=[],routeTarget=null,speedIdx=loadSpeed();
 const inerted=[];
 const held=[];
 let disp={x:0,y:0},camY=0,size={w:300,h:300,dpr:1,cell:32,rows:8,left:0};
 const root=node('div','fg-overlay');root.setAttribute('role','dialog');root.setAttribute('aria-modal','true');root.setAttribute('aria-label',TITLES[op]);
 const top=node('div','fg-top'),title=node('strong','',`${TITLES[op]} · ${field.ha||idiv(H,W)} га · ширина ${run.width}`),timer=node('span','fg-timer'),close=btn('×','fg-close',()=>requestClose());
 close.setAttribute('aria-label','Закрыть игру');timer.title='Осталось на заход';
 const speedBtn=btn('','fg-speed',()=>{speedIdx=(speedIdx+1)%SPEEDS.length;saveSpeed(speedIdx);paintSpeed();});
 const paintSpeed=()=>{speedBtn.textContent=`Темп: ${SPEEDS[speedIdx].label}`;speedBtn.setAttribute('aria-label',`Темп машины: ${SPEEDS[speedIdx].label}. Нажми, чтобы сменить`);};paintSpeed();
 top.append(title,speedBtn,timer,close);
 const stage=node('div','fg-stage'),canvas=node('canvas','fg-canvas');canvas.tabIndex=0;canvas.setAttribute('aria-label',`${TITLES[op]}: поле ${W} на ${H}. Стрелки или WASD — ехать${op==='harvest'?', X — выгрузить':''}.`);
 stage.append(canvas);
 const hud=node('div','fg-hud'),forecast=node('div','fg-forecast'),pace=node('div','fg-pace'),stat=node('div','fg-stat'),gauge=node('div','fg-gauge'),gaugeFill=node('i');
 gauge.append(gaugeFill);gauge.hidden=op!=='harvest';
 const help=node('p','fg-help',HELP[op]);
 hud.append(forecast,pace,stat,gauge,help);
 const sr=node('div','fg-sr');sr.setAttribute('role','status');sr.setAttribute('aria-live','polite');sr.setAttribute('aria-atomic','true');
 const controls=node('div','fg-controls'),pad=node('div','fg-pad'),actions=node('div','fg-actions');
 for(const [ch,label,cls] of [['U','▲','u'],['L','◀','l'],['R','▶','r'],['D','▼','d']]){
  const b=btn(label,`fg-key ${cls}`);b.setAttribute('aria-label',{U:'Вверх',D:'Вниз',L:'Влево',R:'Вправо'}[ch]);
  b.onpointerdown=e=>{e.preventDefault();padDir=ch;cruise=null;routeQ=[];routeTarget=null;if(tapQ.length<4)tapQ.push(ch);try{b.setPointerCapture(e.pointerId);}catch{}};
  const up=()=>{if(padDir===ch)padDir=null;};
  b.onpointerup=up;b.onpointercancel=up;b.onpointerleave=up;b.onlostpointercapture=up;pad.append(b);
 }
 const unload=btn('Выгрузить (X)','fg-act unload',()=>doUnload()),undo=btn('Шаг назад','fg-act',()=>{cruise=null;if(R.path){R.undo();sync();}}),
  auto=btn('','fg-act auto',()=>submit(null)),fin=btn('Закончить работу','fg-act primary',()=>submit(R.path));
 unload.hidden=op!=='harvest';
 actions.append(...(op==='harvest'?[unload]:[]),undo,fin,auto);
 controls.append(pad,actions);
 root.append(top,stage,hud,controls,sr);document.body.append(root);document.body.classList.add('fg-open');
 for(const el of [...document.body.children])if(el!==root&&!el.inert){el.inert=true;inerted.push(el);}   // background is unreachable while the game is open
 const status=node('div','fg-status');status.setAttribute('role','status');hud.append(status);

 /* ---- state helpers */
 function paintForecast(){
  const q=qNow(R.score());
  forecast.textContent=`Прогноз качества: ${pctText(q)}`+(op==='cultivate'?` · рост ${growthPermille(q)<=1000?'быстрее':'медленнее'} на ${(Math.abs(1000-growthPermille(q))/10).toFixed(1).replace('.',',')}%`:' · урожай ×'+(q/1000).toFixed(2).replace('.',','));
  if(!timed||done){pace.textContent='';return;}
  const el=elapsedNow(),keep=timeKeep(el,ha,run.width,cfg);
  pace.classList.toggle('melt',keep<1000);
  pace.textContent=keep===1000?`Полный бонус ещё ${mmss(lim.full-el)}`:keep>0?`Бонус тает: осталось ${pctText(keep)} · до нуля ${mmss(lim.zero-el)}`:'Бонус сгорел — выше автопилота уже не будет';
 }
 function sync(){
  paintForecast();
  const parts=[`Охват ${pctText(R.coverage())}`,`ход ${R.path.length} из ${limit}`];
  if(op!=='sow'||R.doubles)parts.push(op==='sow'?`повторов ${R.doubles}`:`повторов ${pctText(R.overlap())}`);
  if(op==='harvest')parts.push(`бункер ${R.load} из ${R.cap}`,R.lost.size?`потеряно ${R.lost.size}`:'');
  stat.textContent=parts.filter(Boolean).join(' · ');
  if(op==='harvest'){gaugeFill.style.width=`${Math.min(100,100*R.load/Math.max(1,R.cap))}%`;gauge.classList.toggle('full',R.load>=R.cap);unload.disabled=R.y!==0||R.load===0;unload.classList.toggle('hot',R.y===0&&R.load>0);}
  fin.disabled=sending||!R.path.length;undo.disabled=sending||!R.path.length;auto.disabled=sending;
  const at=opts.timeText?opts.timeText(autoSec):autoSec+' с';
  auto.textContent=`Автопилот · ${pctText(cfg.qAuto)} · ${at}`;auto.title=`Автопилот: качество ${pctText(cfg.qAuto)}, готово через ${at}`;auto.setAttribute('aria-label',auto.title);
  announce(`Охват ${pctText(R.coverage())}`+(op==='harvest'?`, бункер ${R.load} из ${R.cap}${R.load>=R.cap?', полон':''}`:op==='sow'&&R.doubles?`, повторов ${R.doubles}`:''));
 }
 function announce(text){clearTimeout(srTimer);srTimer=setTimeout(()=>{srTimer=0;if(!closed)sr.textContent=text;},900);}
 function say(text,bad=false){status.textContent=text;status.classList.toggle('bad',bad);}
 function move(ch){
  if(sending||done||confirming)return false;
  if(R.path.length>=limit){say(`Длина маршрута ограничена: ${limit} ходов. Заверши работу.`,true);return false;}
  const ok=R.push(ch);if(ok){status.textContent='';sync();}
  return ok;
 }
 /* A blocked move (rock / field edge): a short shake + ring on the machine and a light vibration, rate-limited so holding a key does not spam. */
 function bump(ch,ts){
  if(ts-lastBump<450)return;lastBump=ts;shakeUntil=ts+220;shakeDir=ch;
  try{navigator.vibrate?.(15);}catch{}
  if(!status.textContent)say('Туда не проехать.',true);
 }
 /* Tap on a cell: shortest legal route (BFS over anchors, UDLR order) to the anchor covering it. Same path alphabet and the same limit as manual driving. */
 function planRoute(cx,cy){
  const tx=Math.min(cx,W-run.width),ty=cy;
  if(cx<0||cx>=W||cy<0||cy>=H||(tx===R.x&&ty===R.y))return;
  const key=(x,y)=>y*W+x,prev=new Map([[key(R.x,R.y),null]]),todo=[[R.x,R.y]];
  for(let i=0;i<todo.length&&!prev.has(key(tx,ty));i++){
   const [x,y]=todo[i];
   for(const ch of 'UDLR'){const n=stepAnchor(x,y,ch,W,H,run.width,R.rocks);if(n&&!prev.has(key(n[0],n[1]))){prev.set(key(n[0],n[1]),[key(x,y),ch]);todo.push(n);}}
  }
  if(!prev.has(key(tx,ty))){say('Туда не добраться.',true);return;}
  const chars=[];for(let k=key(tx,ty);prev.get(k);k=prev.get(k)[0])chars.push(prev.get(k)[1]);
  chars.reverse();
  if(R.path.length+chars.length>limit){say(`Маршрут не поместится в лимит ${limit} ходов.`,true);return;}
  routeQ=chars;routeTarget=[tx,ty];cruise=null;status.textContent='';
 }
 function expire(){
  if(closed||done||expired)return;
  expired=true;done=true;sending=false;cruise=null;padDir=null;routeQ=[];routeTarget=null;confirming=false;root.querySelector('.fg-confirm')?.remove();
  if(submitTimer)clearTimeout(submitTimer);submitTimer=0;const rs=submitResolve;submitResolve=null;rs?.();
  sync();
  showNote('Время вышло',`Срок заезда истёк. Поле доделает автопилот с качеством ${pctText(cfg.qAuto)} — закрой игру и загляни в раздел «Поля».`);
 }
 function showNote(head,text){
  root.querySelector('.fg-result')?.remove();
  const box=node('div','fg-result');box.setAttribute('role','alertdialog');box.setAttribute('aria-label',head);
  box.append(node('h2','',head),node('p','',text));
  const ok=btn('Закрыть','primary wide',()=>finishClose());box.append(ok);root.append(box);ok.focus();
 }
 function requestClose(){
  if(closed)return;
  if(done||!R.path.length){finishClose();return;}      // nothing to lose
  if(confirming)return;
  confirming=true;cruise=null;padDir=null;routeQ=[];routeTarget=null;held.length=0;tapQ.length=0;
  const box=node('div','fg-confirm');box.setAttribute('role','alertdialog');box.setAttribute('aria-modal','true');box.setAttribute('aria-label','Выйти из игры?');
  const stay=btn('Продолжить','primary wide',()=>cancelClose()),leave=btn('Выйти','secondary wide',()=>finishClose());
  box.append(node('h2','','Выйти из игры?'),node('p','','Проложенный маршрут пропадёт. Заход останется открытым до конца срока — потом поле доделает автопилот.'),stay,leave);
  root.append(box);stay.focus();
 }
 function cancelClose(){root.querySelector('.fg-confirm')?.remove();confirming=false;(sending?close:canvas).focus({preventScroll:true});}
 function doUnload(){
  if(sending||done)return;
  if(R.y!==0){say('Грузовик ждёт у верхнего края поля.',true);return;}
  if(!R.load){say('Бункер пуст.',true);return;}
  if(R.path.length>=limit){say('Маршрут слишком длинный.',true);return;}
  R.push('X');sync();
 }
 function curDir(){return padDir||held[held.length-1]||cruise;}
 async function submit(path){
  if(sending||done||confirming)return;
  sending=true;cruise=null;padDir=null;routeQ=[];routeTarget=null;sync();
  if(path!==null){
   // The server measures wall-clock time between the start of the run and now: 0.12 s per step (whole-second clock) - wait if needed.
   const need=(cfg.stepCs/100*path.length+2)*1000-(performance.now()-openedAt);
   if(need>0){say(`Сдаём работу… ещё ${Math.ceil(need/1000)} с`);await new Promise(resolve=>{
    submitResolve=resolve;submitTimer=setTimeout(()=>{submitTimer=0;submitResolve=null;resolve();},need);
   });}
  }
  if(closed||done)return;
  sentElapsed=elapsedNow();
  let ok=false;
  try{ok=await opts.onFinish(path);}catch{ok=false;}
  sending=false;
  if(closed||done)return;
  if(!ok){
   const f=opts.fieldNow?.();
   if(performance.now()>=deadline-1500||(f&&(!f.run||f.run.id!==run.id||f.run.status!=='open'))){   // the server already closed this run
    if(performance.now()>=deadline-1500){expire();return;}
    done=true;sync();showNote('Заход уже закрыт','Эта работа уже закончена или закрыта на сервере. Закрой игру и обнови раздел «Поля».');return;
   }
   say('Не получилось отправить работу. Попробуй ещё раз или выбери автопилот.',true);sync();return;
  }
  done=true;showResult(path);
 }
 function showResult(path){
  const box=node('div','fg-result');
  box.append(node('h2','',path===null?'Автопилот взялся за работу':'Работа закончена'));
  if(path===null){
   box.append(node('p','',`Качество ${pctText(cfg.qAuto)}. Готово через ${opts.timeText?opts.timeText(autoSec):autoSec+' с'} — можно закрыть игру, поле доделается само.`));
  }else{
   const sc=R.score(),f=opts.fieldNow?.(),exact=f&&!f.run&&Number.isInteger(f.last_q)?f.last_q:null,q=exact??qNow(sc,sentElapsed),crop=opts.cropSnapshot;
   const lost=timed&&q<quality(sc,cfg);               // the time melted part of the bonus
   const extra=op==='harvest'&&crop?{item:opts.itemName?.(crop.id)||crop.id,qty:yieldQty(crop.base,crop.q_sow,q)}:{};
   for(const l of effectLines(op,q,extra))box.append(node('p','fg-line',l));
   if(exact===null)box.append(node('p','fg-compare','Число ориентировочное: точное покажет сервер.'));
   // honest comparison with the autopilot; the server alone decides the reward from the quality it recomputes
   if(sc>=950&&!lost)box.append(node('p','fg-proud',(opts.g||((m,f,n)=>n))('Сам справился — полный бонус!','Сама справилась — полный бонус!','Полный бонус за ручную работу!')));
   if(lost)box.append(node('p','fg-compare',`Время съело часть бонуса: в срок (до ${mmss(lim.full)}) было бы ${pctText(quality(sc,cfg))}.`));
   const d=q-cfg.qAuto,dTxt=`${d>0?'+':d<0?'−':'±'}${pctText(Math.abs(d))}`,mine=Math.max(1,Math.round(sentElapsed/60));
   const at=opts.timeText?opts.timeText(autoSec):autoSec+' с';
   box.append(node('p','fg-compare',`Автопилот: качество ${pctText(cfg.qAuto)}, ждать ${at}.`),
    node('p','fg-compare',d>=0?`Своими руками: ≈${mine} мин ради ${dTxt} к автопилоту.`:`Своими руками: ≈${mine} мин, ${dTxt} к автопилоту — в следующий раз можно довериться автопилоту.`));
   if(op==='sow'&&run.crop)box.append(node('p','',`Посеяно: ${opts.itemName?.(run.crop)||run.crop}`));
  }
  box.append(btn('Готово','primary wide',()=>finishClose()));
  root.append(box);
 }
 function finishClose(){
  if(closed)return;closed=true;cancelAnimationFrame(raf);raf=0;
  if(submitTimer)clearTimeout(submitTimer);submitTimer=0;
  // Resolve the local wait too: clearing its timeout alone would leave submit() suspended forever.
  const resolve=submitResolve;submitResolve=null;resolve?.();
  if(layoutTimer)clearTimeout(layoutTimer);layoutTimer=0;
  held.length=0;tapQ.length=0;padDir=null;cruise=null;swipe=null;routeQ=[];if(srTimer)clearTimeout(srTimer);srTimer=0;
  for(const el of inerted)el.inert=false;inerted.length=0;
  window.removeEventListener('keydown',onKey,true);window.removeEventListener('keyup',onKeyUp,true);window.removeEventListener('resize',layout);
  window.removeEventListener('blur',onBlur);resizeObs?.disconnect();
  canvas.width=0;canvas.height=0;root.remove();document.body.classList.remove('fg-open');
  try{prev?.focus?.();}catch{}
  opts.onClose?.();
 }

 /* ---- input */
 function onKey(e){
  if(closed||e.ctrlKey||e.metaKey||e.altKey)return;
  if(e.code==='Tab'){trapTab(e);return;}
  if(e.code==='Escape'){e.preventDefault();e.stopPropagation();if(confirming)cancelClose();else requestClose();return;}
  if(confirming||done)return;                       // let buttons of the dialogs handle Enter/Space themselves
  if(KEYS[e.code]){e.preventDefault();e.stopPropagation();if(!e.repeat){const d=KEYS[e.code],i=held.indexOf(d);if(i>=0)held.splice(i,1);held.push(d);cruise=null;routeQ=[];routeTarget=null;if(tapQ.length<4)tapQ.push(d);}return;}
  if(e.code==='KeyX'||e.code==='Space'){if(op==='harvest'){e.preventDefault();e.stopPropagation();if(!e.repeat)doUnload();}return;}
  if(e.code==='Backspace'||e.code==='KeyZ'){e.preventDefault();e.stopPropagation();if(!e.repeat&&R.path&&!sending&&!done){R.undo();sync();}}
 }
 function trapTab(e){
  const scope=root.querySelector('.fg-confirm')||root.querySelector('.fg-result')||root;
  const items=[...scope.querySelectorAll('button:not(:disabled),canvas')].filter(el=>!el.hidden&&el.offsetParent!==null);
  if(!items.length)return;
  const i=items.indexOf(document.activeElement),n=e.shiftKey?(i<=0?items.length-1:i-1):(i<0||i>=items.length-1?0:i+1);
  e.preventDefault();e.stopPropagation();items[n].focus();
 }
 function onKeyUp(e){if(KEYS[e.code]){const i=held.indexOf(KEYS[e.code]);if(i>=0)held.splice(i,1);}}
 function onBlur(){held.length=0;padDir=null;}
 window.addEventListener('keydown',onKey,true);window.addEventListener('keyup',onKeyUp,true);window.addEventListener('blur',onBlur);
 let swipe=null;
 canvas.onpointerdown=e=>{swipe={x:e.clientX,y:e.clientY,moved:false};try{canvas.setPointerCapture(e.pointerId);}catch{}canvas.focus({preventScroll:true});};
 canvas.onpointermove=e=>{
  if(!swipe)return;const dx=e.clientX-swipe.x,dy=e.clientY-swipe.y;
  if(Math.max(Math.abs(dx),Math.abs(dy))>=22){
   cruise=Math.abs(dx)>Math.abs(dy)?(dx>0?'R':'L'):(dy>0?'D':'U');swipe.x=e.clientX;swipe.y=e.clientY;swipe.moved=true;routeQ=[];routeTarget=null;
  }
 };
 const endSwipe=e=>{
  if(swipe&&!swipe.moved&&!done&&!confirming&&!sending){
   if(cruise||routeQ.length){cruise=null;routeQ=[];routeTarget=null;}          // a tap stops the machine first
   else if(e?.type==='pointerup'){
    const r=canvas.getBoundingClientRect();
    planRoute(Math.floor((e.clientX-r.left-size.left)/size.cell),Math.floor((e.clientY-r.top)/size.cell+camY));
   }
  }
  swipe=null;
 };
 canvas.onpointerup=endSwipe;canvas.onpointercancel=endSwipe;

 /* ---- drawing */
 function layout(){
  if(closed)return;
  const r=stage.getBoundingClientRect();
  const w=Math.max(120,Math.floor(r.width)),h=Math.max(120,Math.floor(r.height));
  const dpr=Math.min(2,window.devicePixelRatio||1,Math.sqrt(4e6/(w*h)));
  const pw=Math.floor(w*dpr),ph=Math.floor(h*dpr);
  if(canvas.width!==pw)canvas.width=pw;if(canvas.height!==ph)canvas.height=ph;
  let cell=Math.min(Math.floor(w/W),60);
  const total=H+(op==='harvest'?1:0),fit=Math.floor(h/total);
  if(total<=12&&fit>=24)cell=Math.min(cell,fit);          // small fields: show the whole field at once
  const minRows=Math.min(total,7);
  if(Math.floor(h/cell)<minRows)cell=Math.max(24,Math.floor(h/minRows));
  size={w,h,dpr,cell,rows:Math.min(H+(op==='harvest'?1:0),Math.floor(h/cell)),left:Math.floor((w-cell*W)/2)};
 }
 function cellColor(c,x,y){
  const wildTone=(x+y)%2?PALETTE.wildA:PALETTE.wildB;
  if(op==='cultivate')return R.last.has(c)?PALETTE.tilled:wildTone;
  if(op==='sow')return PALETTE.tilled;
  return R.last.has(c)?PALETTE.stubble:PALETTE.ripe;
 }
 function draw(ts){
  if(closed)return;
  const dt=Math.min(0.1,(ts-(last||ts))/1000);last=ts;
  const left_=Math.max(0,(deadline-performance.now())/1000),shown=Math.ceil(left_);
  if(shown!==shownLeft){
   shownLeft=shown;paintForecast();timer.textContent=`Осталось ${mmss(left_)}`;timer.setAttribute('aria-label',`Осталось на заход ${mmss(left_)}`);timer.classList.toggle('warn',left_<=60);
   if(!warned&&left_<=60&&left_>0&&!done){warned=true;say('Осталась минута: заверши работу, иначе поле доделает автопилот.',true);announce('Осталась минута');}
  }
  if(left_<=0&&!done){expire();}
  if(!done&&!confirming&&ts-lastStep>=SPEEDS[speedIdx].ms){
   const q=tapQ.length>0,routed=!q&&!curDir()&&routeQ.length>0,d=q?tapQ[0]:(curDir()||(routed?routeQ[0]:null));
   if(d){
    const ok=move(d);
    if(ok){lastStep=ts;if(routed)routeQ.shift();if(routed&&!routeQ.length)routeTarget=null;}
    else{
     if(d===cruise)cruise=null;if(routed){routeQ=[];routeTarget=null;}
     if(!sending&&R.path.length<limit)bump(d,ts);
    }
    if(q)tapQ.shift();
   }
  }
  const calm=reducedMotion();
  const k=calm?1:1-Math.exp(-dt*16);disp.x+=(R.x-disp.x)*k;disp.y+=(R.y-disp.y)*k;
  const g=canvas.getContext('2d'),{w,h,dpr,cell,rows,left}=size;
  g.setTransform(dpr,0,0,dpr,0,0);g.clearRect(0,0,w,h);g.fillStyle='#e8ecd5';g.fillRect(0,0,w,h);
  const minTop=op==='harvest'?-1:0,maxTop=Math.max(minTop,H-rows);
  const wantTop=Math.max(minTop,Math.min(maxTop,disp.y-rows/2+0.5));camY=calm?wantTop:camY+(wantTop-camY)*Math.min(1,dt*10+0.02);
  if(Math.abs(wantTop-camY)<0.01)camY=wantTop;
  const px=x=>left+x*cell,py=y=>Math.round((y-camY)*cell);
  const y0=Math.max(0,Math.floor(camY)),y1=Math.min(H-1,Math.ceil(camY+rows));
  for(let y=y0;y<=y1;y++)for(let x=0;x<W;x++){
   const c=y*W+x,X=px(x),Y=py(y);
   g.fillStyle=cellColor(c,x,y);g.fillRect(X,Y,cell,cell);
   if(op==='cultivate'){
    if(R.last.has(c)){g.strokeStyle=PALETTE.furrow;g.lineWidth=2;g.beginPath();g.moveTo(X+3,Y+cell*0.35);g.lineTo(X+cell-3,Y+cell*0.35);g.moveTo(X+3,Y+cell*0.7);g.lineTo(X+cell-3,Y+cell*0.7);g.stroke();}
    else if(R.weeds.has(c)){g.strokeStyle=PALETTE.weed;g.lineWidth=Math.max(2,cell/12);g.lineCap='round';g.beginPath();for(const dx of [0.3,0.5,0.7]){g.moveTo(X+cell*dx,Y+cell*0.78);g.lineTo(X+cell*(dx+(dx-0.5)*0.5),Y+cell*0.3);}g.stroke();}
   }else if(op==='sow'){
    g.strokeStyle=PALETTE.furrow;g.lineWidth=1;g.beginPath();g.moveTo(X+3,Y+cell*0.5);g.lineTo(X+cell-3,Y+cell*0.5);g.stroke();
    if(R.sown.has(c)){g.fillStyle=R.doubled.has(c)?PALETTE.double:PALETTE.seed;for(const [ax,ay] of [[0.3,0.3],[0.7,0.3],[0.5,0.55],[0.3,0.78],[0.7,0.78]]){g.beginPath();g.arc(X+cell*ax,Y+cell*ay,Math.max(2,cell/11),0,6.3);g.fill();}
     if(R.doubled.has(c)){g.save();g.beginPath();g.rect(X,Y,cell,cell);g.clip();g.strokeStyle='#7a2f12';g.lineWidth=Math.max(1.5,cell/16);g.beginPath();for(let o=-cell;o<cell*2;o+=Math.max(6,cell/3.5)){g.moveTo(X+o,Y+cell);g.lineTo(X+o+cell,Y);}g.stroke();g.restore();}}
   }else{
    if(R.lost.has(c)){g.strokeStyle=PALETTE.lost;g.lineWidth=3;g.beginPath();g.moveTo(X+cell*0.25,Y+cell*0.25);g.lineTo(X+cell*0.75,Y+cell*0.75);g.moveTo(X+cell*0.75,Y+cell*0.25);g.lineTo(X+cell*0.25,Y+cell*0.75);g.stroke();}
    else if(!R.last.has(c)){g.strokeStyle=PALETTE.ripeStalk;g.lineWidth=2;g.beginPath();for(const dx of [0.2,0.4,0.6,0.8]){g.moveTo(X+cell*dx,Y+cell*0.9);g.lineTo(X+cell*dx,Y+cell*0.25);}g.stroke();}
   }
   if(R.rocks.has(c)){
    g.fillStyle=PALETTE.rock;g.beginPath();g.ellipse(X+cell/2,Y+cell*0.58,cell*0.4,cell*0.32,0,0,6.3);g.fill();
    g.fillStyle=PALETTE.rockLight;g.beginPath();g.ellipse(X+cell*0.42,Y+cell*0.46,cell*0.16,cell*0.1,-0.4,0,6.3);g.fill();
   }
   g.strokeStyle=PALETTE.grid;g.lineWidth=1;g.strokeRect(X+0.5,Y+0.5,cell-1,cell-1);
  }
  if(op==='sow'){                                   // row marking: lanes the seeder may sow, with a gap column between them
   g.fillStyle='rgba(255,246,214,0.42)';g.strokeStyle='rgba(255,246,214,0.95)';g.lineWidth=2;g.setLineDash([6,5]);
   for(let x=0;x<=W-run.width;x+=run.width+1){g.fillRect(px(x),py(0),run.width*cell,H*cell);g.strokeRect(px(x)+1,py(0),run.width*cell-2,H*cell);}
   g.setLineDash([]);
  }
  g.strokeStyle='#5d6e5a';g.lineWidth=3;g.strokeRect(left-1.5,py(0)-1.5,W*cell+3,H*cell+3);
  if(op==='harvest'){                               // the truck at the top edge (y = 0) waits above the field
   const ty=py(-1);
   if(ty+cell>0){
    g.fillStyle=PALETTE.road;g.fillRect(left,ty,W*cell,cell);g.strokeStyle=PALETTE.roadLine;g.lineWidth=2;g.setLineDash([10,8]);g.beginPath();g.moveTo(left,ty+cell/2);g.lineTo(left+W*cell,ty+cell/2);g.stroke();g.setLineDash([]);
    const tx=left+Math.min(W-2,Math.max(0,disp.x))*cell+0,hot=R.y===0&&R.load>0;
    g.fillStyle=hot?'#f0b04e':'#cdb78e';g.fillRect(tx+cell*0.1,ty+cell*0.2,cell*1.2,cell*0.6);g.fillStyle='#8a6650';g.fillRect(tx+cell*1.3,ty+cell*0.34,cell*0.5,cell*0.46);
    g.fillStyle='#3f4a40';for(const wx of [0.4,1.0,1.55]){g.beginPath();g.arc(tx+cell*wx,ty+cell*0.82,cell*0.1,0,6.3);g.fill();}
   }
  }
  // machine: a bar of `width` cells with a cab and wheels
  if(routeTarget){g.strokeStyle='#2f6f4b';g.lineWidth=2;g.setLineDash([4,3]);g.strokeRect(px(routeTarget[0])+2,py(routeTarget[1])+2,run.width*cell-4,cell-4);g.setLineDash([]);}
  const shaking=ts<shakeUntil,sh=shaking&&!calm?Math.sin((shakeUntil-ts)/18)*cell*0.1*(DIRS[shakeDir]?.[0]?1:0):0,shv=shaking&&!calm?Math.sin((shakeUntil-ts)/18)*cell*0.1*(DIRS[shakeDir]?.[1]?1:0):0;
  const mx=px(disp.x)+sh,my=py(disp.y)+shv,mw=run.width*cell;
  g.fillStyle='rgba(0,0,0,0.18)';g.fillRect(mx+3,my+cell*0.18+4,mw-2,cell*0.7);
  g.fillStyle=BODY[op];g.strokeStyle='#4b5b4b';g.lineWidth=2;
  rrect(g,mx+2,my+cell*0.12,mw-4,cell*0.76,cell*0.18);g.fill();g.stroke();
  g.fillStyle='#fff8dd';rrect(g,mx+mw/2-cell*0.22,my+cell*0.28,cell*0.44,cell*0.3,4);g.fill();
  g.fillStyle='#3f4a40';for(const wx of [0.12,0.88]){g.beginPath();g.arc(mx+Math.max(cell*0.18,mw*wx),my+cell*0.82,cell*0.1,0,6.3);g.fill();}
  if(shaking){g.strokeStyle='#b8431f';g.lineWidth=3;rrect(g,mx,my+cell*0.08,mw,cell*0.84,cell*0.2);g.stroke();}
  if(op==='harvest'&&R.load>=R.cap){g.fillStyle='#d9805c';g.font=`700 ${Math.max(11,cell*0.28)}px system-ui,sans-serif`;g.textAlign='center';g.fillText('Полон!',mx+mw/2,my-3);}
  raf=requestAnimationFrame(draw);
 }
 layout();sync();
 window.addEventListener('resize',layout);
 const resizeObs=typeof ResizeObserver==='function'?new ResizeObserver(()=>{if(!closed)layout();}):null;resizeObs?.observe(stage);
 raf=requestAnimationFrame(draw);
 layoutTimer=setTimeout(()=>{layoutTimer=0;if(!closed)layout();},60);
 canvas.focus({preventScroll:true});
 return {close:finishClose};
}
