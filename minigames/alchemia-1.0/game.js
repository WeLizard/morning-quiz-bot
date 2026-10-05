/* Alchemia 1.0 — no libraries, network calls, analytics, or recurring timers.
 * Content is data-driven; every unordered recipe pair is unique.
 * Pointer events are delegated once. Audio nodes disconnect on end.
 * Only the bounded particle system uses RAF, and only while particles exist.
 */
(() => {
'use strict';
const DATA=JSON.parse(document.getElementById('gameData').textContent);
const E=new Map(DATA.elements.map(e=>[e.id,e]));
const R=new Map(DATA.recipes.map(r=>[r.key,r]));
const C=new Map(DATA.categories.map(c=>[c.id,c]));
const W=new Map((DATA.worlds||[]).map(w=>[w.id,w]));
const BASE=['water','earth','fire','air'];
const STORE='alchemia.atlas'; // Stable key; save schema evolves independently of the release.
const LEGACY_STORES=['alchemia.atlas.v5','alchemia.atlas.v4','alchemia.atlas.v3','alchemia.atlas.v2','alchemia.atlas.v1'];
const MAX_TOKENS=36, HISTORY_LIMIT=160, MAX_SAVE_BYTES=8000000;
const $=id=>document.getElementById(id);
const escapeHTML=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pairKey=(a,b)=>[a,b].sort().join('+');
const icon=name=>`<svg class="ui-icon" aria-hidden="true"><use href="#ui-${name}"/></svg>`;
const art=(id,extra='')=>`<svg class="art ${extra}" viewBox="0 0 120 120" aria-hidden="true"><use href="#art-${E.has(id)?id:'question'}"/></svg>`;
const name=id=>E.get(id)?.name??'Неизвестно';
const noun=(n,one,few,many)=>{const d=n%10,t=n%100;return t>=11&&t<=14?many:d===1?one:d>=2&&d<=4?few:many;};
const clone=v=>JSON.parse(JSON.stringify(v));
const clamp=(n,a,b)=>Math.max(a,Math.min(Math.max(a,b),n));
const finite=(n,fallback=0)=>typeof n==='number'&&Number.isFinite(n)?n:fallback;
const controller=new AbortController();
const listen=(target,event,callback,opts={})=>target.addEventListener(event,callback,{...opts,signal:controller.signal});
let serial=0;
const uid=()=>`t${Date.now().toString(36)}_${++serial}`;
function freshState(){return {
 format:'alchemia',version:2,release:'5.1-refined',claims:[],activeCampaign:null,updatedAt:Date.now(),discovered:[...BASE],recipeKeys:[],tried:[],favorites:[],achievements:[],history:[],attempts:0,
 bench:BASE.map((id,i)=>({uid:uid(),id,u:i%2?.72:.28,v:i<2?.26:.76})),
 pinned:null,latest:null,settings:{sound:false,motion:!matchMedia('(prefers-reduced-motion: reduce)').matches,sort:'new',world:'origins'},created:Date.now()
};}
function validPair(k){if(typeof k!=='string')return false;const p=k.split('+');return p.length===2&&p.every(x=>E.has(x))&&pairKey(...p)===k;}
function cleanSave(raw){
 if(!raw||typeof raw!=='object'||raw.format!=='alchemia'||![1,2].includes(raw.version)||!Array.isArray(raw.discovered)) throw new Error('Это не поддерживаемое сохранение Alchemia (схема 1 или 2).');
 const s=freshState();
 const ids=[...new Set([...BASE,...raw.discovered.filter(x=>typeof x==='string'&&E.has(x))])];
 s.discovered=ids; const found=new Set(ids);
 const arr=(x,max=E.size*(E.size+1)/2)=>Array.isArray(x)?x.slice(0,max):[];
 s.recipeKeys=[...new Set(arr(raw.recipeKeys).filter(k=>R.has(k)&&found.has(R.get(k).a)&&found.has(R.get(k).b)&&found.has(R.get(k).result)))];
 s.tried=[...new Set([...arr(raw.tried).filter(k=>validPair(k)&&k.split('+').every(x=>found.has(x))),...s.recipeKeys])];
 s.favorites=[...new Set(arr(raw.favorites,E.size).filter(x=>found.has(x)))];
 s.achievements=[]; // Always derive achievement eligibility, never trust imported badges.
 s.bench=arr(raw.bench,MAX_TOKENS).filter(t=>t&&found.has(t.id)).map(t=>({uid:uid(),id:t.id,u:clamp(finite(t.u,.5),0,1),v:clamp(finite(t.v,.5),0,1)}));
 s.history=arr(raw.history,HISTORY_LIMIT).filter(h=>h&&found.has(h.a)&&found.has(h.b)&&Number.isFinite(h.time)).map(h=>{
  const r=R.get(pairKey(h.a,h.b)); const result=r&&h.result===r.result&&found.has(r.result)?r.result:null; return {a:h.a,b:h.b,result,isNew:!!result&&!!h.isNew,time:clamp(h.time,0,Date.now()+86400000)};
 });
 s.attempts=Math.max(s.tried.length,Math.min(1000000000,Math.floor(finite(raw.attempts))));
 s.pinned=E.has(raw.pinned)&&!found.has(raw.pinned)?raw.pinned:null;
 s.latest=found.has(raw.latest)&&!BASE.includes(raw.latest)?raw.latest:null;
 const settings=raw.settings&&typeof raw.settings==='object'?raw.settings:{};
 s.settings={sound:settings.sound===true,motion:settings.motion!==false,sort:['new','name','tier'].includes(settings.sort)?settings.sort:'new',world:W.has(settings.world)?settings.world:'origins',topbarHidden:settings.topbarHidden===true};
 s.created=clamp(finite(raw.created,Date.now()),0,Date.now());
 s.updatedAt=clamp(finite(raw.updatedAt,s.created),0,Date.now());
 s.activeCampaign=(DATA.campaigns||[]).some(c=>c.id===raw.activeCampaign)?raw.activeCampaign:null;
 const requested=new Set(arr(raw.claims,200));const known=new Set(s.recipeKeys);
 s.claims=[];
 for(const c of DATA.campaigns||[])for(const step of c.stages||[]){
  const eligible=step.goals.every(id=>found.has(id))&&(step.craft||[]).every(id=>DATA.recipes.some(r=>r.result===id&&known.has(r.key)));
  if(!requested.has(step.id)||!eligible)break;
  s.claims.push(step.id);
 }
 return s;
}
let storageOK=true,loaded=false,migrated=0,loadWarning='',storageLocked=false;
let state=freshState();
try{
 const saved=localStorage.getItem(STORE);
 if(saved){
  try{if(saved.length>MAX_SAVE_BYTES)throw new Error('oversize');state=cleanSave(JSON.parse(saved));loaded=true;}
  catch(err){storageLocked=true;loadWarning='Основное сохранение повреждено. Оно не перезаписано. Открой настройки для восстановления резервной копии или импорта файла.';}
 }else{
  const candidates=[];
  for(const key of LEGACY_STORES){
   try{const text=localStorage.getItem(key);if(text&&text.length<=MAX_SAVE_BYTES)candidates.push(cleanSave(JSON.parse(text)));}catch(err){/* Keep incompatible legacy bytes untouched. */}
  }
  try{const old=JSON.parse(localStorage.getItem('elementAlchemyDiscovered')||'null');if(Array.isArray(old))candidates.push(cleanSave({...freshState(),discovered:old}));}catch(err){}
  if(candidates.length){
   candidates.sort((a,b)=>b.discovered.length-a.discovered.length||b.updatedAt-a.updatedAt);
   const seed=candidates[0];
   state=cleanSave({...seed,discovered:candidates.flatMap(c=>c.discovered),recipeKeys:candidates.flatMap(c=>c.recipeKeys),tried:candidates.flatMap(c=>c.tried),favorites:candidates.flatMap(c=>c.favorites)});
   migrated=state.discovered.length-BASE.length;loaded=true;
  }
 }
}catch(err){storageOK=false;loadWarning='Хранилище браузера недоступно. Игра работает, но для сохранения нужен экспорт файла.';}
let found=new Set(state.discovered),knownRecipes=new Set(state.recipeKeys),tried=new Set(state.tried),favorites=new Set(state.favorites),badges=new Set();
let selected=null,category='all',onlyFavorites=false,newThisSession=new Set();
let undoStack=[],drag=null,suppressClickUntil=0,toastTimer=0,resizeFrame=0,modalPage=null,modalContext=null,hint=null;
let modalBack=null,focusBeforeModal=null,confirmAction=null,documentDisposed=false;
let tokenSize={w:100,h:111},lastBoardSize={w:0,h:0};
const board=$('board'),tokens=$('tokenLayer'),modal=$('modal');

function syncState(){state.discovered=[...found];state.recipeKeys=[...knownRecipes];state.tried=[...tried];state.favorites=[...favorites];state.achievements=[...badges];}
function persist(){
 if(documentDisposed)return;
 syncState();state.updatedAt=Date.now();
 if(storageLocked){$('saveLabel').textContent='Нужно восстановление';return;}
 try{const previous=localStorage.getItem(STORE);if(previous){try{cleanSave(JSON.parse(previous));localStorage.setItem(STORE+'.backup',previous);}catch(e){}}
 localStorage.setItem(STORE,JSON.stringify(state));storageOK=true;$('saveLabel').innerHTML='<span class="save-dot"></span>Сохранено';}
 catch(err){storageOK=false;$('saveLabel').textContent='Нет автосохранения';$('saveWarning').textContent='Браузер не разрешил автосохранение. Сохрани прогресс файлом в настройках.';$('saveWarning').classList.remove('hidden');}
}
function announce(text){$('liveAnnouncer').textContent=text;}
function pushUndo(){undoStack.push(clone(state.bench));if(undoStack.length>30)undoStack.shift();$('undoBtn').disabled=false;}
function applySettings(){
 document.body.dataset.world=state.settings.world||'origins';
 document.body.classList.toggle('reduced-motion',!state.settings.motion);
 renderEpochHeading();
 $('sortSelect').value=state.settings.sort;
 $('soundBtn').innerHTML=icon(state.settings.sound?'volume':'muted');
 $('soundBtn').title=state.settings.sound?'Выключить звук':'Включить звук';
 $('soundBtn').setAttribute('aria-label',$('soundBtn').title);
 $('soundBtn').setAttribute('aria-pressed',String(state.settings.sound));
}
function toggleSound(){state.settings.sound=!state.settings.sound;applySettings();persist();if(state.settings.sound)playSound('select');if(modalPage==='settings')showSettings(false);}

/* Audio: one reusable context; all short-lived oscillator/gain nodes are bounded. */
let audio=null;
function playSound(type){
 if(!state.settings.sound||document.hidden)return;
 try{
  const AC=window.AudioContext||window.webkitAudioContext;if(!AC)return;
  if(!audio)audio=new AC();
  if(audio.state==='suspended')audio.resume().catch(()=>{});
  const tones=type==='discovery'?[392,493.88,587.33,783.99]:type==='success'?[392,523.25]:type==='failure'?[174.61,164.81]:[440];
  tones.forEach((f,i)=>{
   const oscillator=audio.createOscillator(),gain=audio.createGain();const t=audio.currentTime+i*.085;
   oscillator.type='sine';oscillator.frequency.setValueAtTime(f,t);
   gain.gain.setValueAtTime(0,t);gain.gain.linearRampToValueAtTime(type==='select'?.026:.045,t+.012);gain.gain.exponentialRampToValueAtTime(.0001,t+.38);
   oscillator.connect(gain);gain.connect(audio.destination);oscillator.onended=()=>{oscillator.disconnect();gain.disconnect();};oscillator.start(t);oscillator.stop(t+.42);
  });
 }catch(err){/* Audio must never prevent an experiment. */}
}
/* Particles: one frame loop for all particles, hard cap, no idle animation loop. */
let particles=[],fxFrame=0,fxLast=0;
const canvas=$('fxCanvas'),ctx=canvas.getContext('2d');
function sizeCanvas(){const dpr=Math.min(window.devicePixelRatio||1,2);canvas.width=Math.max(1,Math.round(board.clientWidth*dpr));canvas.height=Math.max(1,Math.round(board.clientHeight*dpr));canvas.style.width=board.clientWidth+'px';canvas.style.height=board.clientHeight+'px';ctx?.setTransform(dpr,0,0,dpr,0,0);}
function stopParticles(){if(fxFrame)cancelAnimationFrame(fxFrame);fxFrame=0;particles=[];ctx?.clearRect(0,0,board.clientWidth,board.clientHeight);}
function burst(x,y,isNew){
 if(!ctx||!state.settings.motion||document.hidden)return;
 const count=isNew?28:10;
 for(let i=0;i<count;i++){const a=Math.random()*Math.PI*2,s=35+Math.random()*100;particles.push({x,y,vx:Math.cos(a)*s,vy:Math.sin(a)*s-25,t:0,life:.5+Math.random()*.7,size:1+Math.random()*2,color:i%3?'#ddcc92':'#bcd9a4'});}
 if(particles.length>130)particles.splice(0,particles.length-130);
 if(!fxFrame){fxLast=performance.now();fxFrame=requestAnimationFrame(animateParticles);}
}
function animateParticles(now){
 const dt=Math.min((now-fxLast)/1000,.04);fxLast=now;ctx.clearRect(0,0,board.clientWidth,board.clientHeight);
 particles=particles.filter(p=>{p.t+=dt;if(p.t>=p.life)return false;p.x+=p.vx*dt;p.y+=p.vy*dt;p.vy+=35*dt;ctx.globalAlpha=1-p.t/p.life;ctx.fillStyle=p.color;ctx.beginPath();ctx.arc(p.x,p.y,p.size,0,Math.PI*2);ctx.fill();return true;});
 ctx.globalAlpha=1;fxFrame=particles.length?requestAnimationFrame(animateParticles):0;
}

function showToast(title,detail='',id=null,kind='normal',duration=3300){
 clearTimeout(toastTimer);
 const stack=$('toastStack');stack.innerHTML='';
 const node=document.createElement('button');node.type='button';node.className='toast'+(kind==='failure'?' failure':'');
 if(id){node.dataset.detail=id;node.setAttribute('aria-label',`${title}. ${name(id)}. Открыть сведения`);}
 else node.setAttribute('aria-label',title+'. '+detail+'. Закрыть уведомление');
 node.innerHTML=(id?art(id):kind==='failure'?icon('lab'):icon('star'))+`<span>${kind==='new'?'<span class="eyebrow" style="display:block">Новое открытие</span>':''}<strong>${escapeHTML(title)}</strong>${detail?`<p>${escapeHTML(detail)}</p>`:''}</span>`;
 if(!id)node.dataset.action='dismiss-toast';
 stack.appendChild(node);announce(`${title}. ${detail}`);
 toastTimer=setTimeout(()=>{stack.replaceChildren();toastTimer=0;},duration);
}
function dismissToast(){clearTimeout(toastTimer);toastTimer=0;$('toastStack').replaceChildren();}
function rank(){return found.size>=340?'Архитектор вселенных':found.size>=260?'Хранитель великого атласа':found.size>=160?'Мастер превращений':found.size>=60?'Исследователь чудес':'Ученик алхимика';}
function chapterComplete(c){return c.goals.every(id=>found.has(id));}
function currentChapter(){return DATA.chapters.find(c=>!chapterComplete(c))||DATA.chapters[DATA.chapters.length-1];}
function goalRow(id){return `<button class="goal-row ${found.has(id)?'complete':''} ${state.pinned===id?'tracked':''}" data-goal="${id}" title="${found.has(id)?'Открыть сведения':'Выбрать целью и получить подсказку'}">${art(id)}<span class="goal-name">${name(id)}</span>${icon(found.has(id)?'check':state.pinned===id?'target':'arrow')}</button>`;}
function renderChapter(){
 const c=currentChapter(),index=DATA.chapters.indexOf(c),done=c.goals.filter(id=>found.has(id)).length,total=DATA.chapters.length,world=W.get(c.world||'');
 $('chapterCard').innerHTML=`<div class="chapter-card"><div class="chapter-head"><span class="eyebrow">${world?escapeHTML(world.name)+' · ':''}Путь алхимика</span><button class="text-btn" data-action="chapters" style="padding:0;font-size:10px">${String(index+1).padStart(2,'0')} / ${String(total).padStart(2,'0')} ${icon('arrow')}</button></div><h2>${c.title}</h2>${world?`<div class="pill" style="display:inline-flex;margin-bottom:10px">${escapeHTML(world.name)}</div>`:''}<p class="chapter-description">${c.subtitle}</p><div class="goal-list">${c.goals.map(goalRow).join('')}</div><div class="chapter-progress"><span style="width:${done/c.goals.length*100}%"></span></div><div class="chapter-progress-label"><span>${chapterComplete(c)?'Глава завершена':'Открытия главы'}</span><span>${done} / ${c.goals.length}</span></div></div>`;
 $('mobileChapter').textContent=DATA.chapters.every(chapterComplete)?`Все ${total} глав пройдены`:`${world?world.name+' · ':''}Глава ${index+1} из ${total}`;
}
function renderLatest(){
 const id=state.latest;
 $('latestDiscovery').innerHTML=id&&E.has(id)?`<div class="latest-discovery"><div class="eyebrow">Последняя находка</div>${art(id)}<h3>${name(id)}</h3><p>${E.get(id).description}</p><button class="text-btn" data-detail="${id}">Открыть в атласе ${icon('arrow')}</button></div>`:`<div class="latest-empty"><div class="eyebrow">Всё ещё впереди</div>${art('seed')}<p>Самое интересное<br>обычно начинается<br>со слов «а что, если…»</p><small>Твоя первая находка появится здесь</small></div>`;
}
function renderProgress(){
 const n=found.size,total=E.size,pct=n/total*100;
 $('collectionCount').textContent=n;$('progressTotal').textContent=`${n} из ${total}`;$('progressPercent').textContent=Math.floor(pct)+'%';$('progressCircle').setAttribute('stroke-dashoffset',String(188.496*(1-n/total)));$('rankLabel').textContent=rank();$('mobileCount').textContent=`${n} / ${total}`;$('pathPillCount').textContent=`${n} / ${total}`;$('mobileProgressFill').style.width=pct+'%';$('attemptCount').textContent=tried.size;$('recipeCount').textContent=knownRecipes.size;
 renderChapter();renderLatest();renderCampaignTracker();
}
function card(id,mode='pick',locked=false){
 const e=E.get(id),isFavorite=favorites.has(id);
 return `<button type="button" class="element-card ${locked?'locked':''} ${newThisSession.has(id)?'new':''} ${selected&&state.bench.find(t=>t.uid===selected)?.id===id?'selected':''}" ${locked?`data-locked="${id}"`:`data-${mode}="${id}"`} title="${locked?'Неоткрытый элемент':escapeHTML(e.name)+(mode==='pick'?' · нажми для смешивания. Shift+клик — сведения.':' · сведения и рецепты')}" aria-label="${locked?'Неоткрытый элемент, '+C.get(e.category).name:escapeHTML(e.name)+(mode==='pick'?'. Выбрать для смешивания':' — открыть сведения')}">${art(id)}${locked?icon('lock').replace('ui-icon','ui-icon lock-icon'):''}<span class="element-name">${locked?'Не открыто':escapeHTML(e.name)}</span>${isFavorite&&!locked?'<span class="card-star" aria-hidden="true">✧</span>':''}</button>`;
}
function renderCategories(){
 const old=$('categoryStrip').scrollLeft;
 $('categoryStrip').innerHTML=`<button class="chip ${category==='all'?'active':''}" data-category="all">Все</button>`+DATA.categories.filter(c=>DATA.elements.some(e=>e.category===c.id&&found.has(e.id))).map(c=>`<button class="chip ${category===c.id?'active':''}" data-category="${c.id}">${c.name}</button>`).join('');
 $('categoryStrip').scrollLeft=old;
}
function filteredCollection(){
 const q=$('collectionSearch').value.toLocaleLowerCase('ru').replaceAll('ё','е').trim();
 let list=state.discovered.filter(id=>found.has(id)).map(id=>E.get(id)).filter(e=>(category==='all'||e.category===category)&&(!onlyFavorites||favorites.has(e.id))&&(!q||(e.name.toLocaleLowerCase('ru').replaceAll('ё','е')+' '+e.id).includes(q)));
 const sorter=state.settings.sort;
 if(sorter==='name')list.sort((a,b)=>a.name.localeCompare(b.name,'ru'));
 else if(sorter==='tier')list.sort((a,b)=>a.tier-b.tier||a.name.localeCompare(b.name,'ru'));
 else list.reverse();
 // The four roots retain their familiar order at the bottom, or in a fresh world.
 if(sorter==='new'&&list.every(e=>BASE.includes(e.id)))list.sort((a,b)=>BASE.indexOf(a.id)-BASE.indexOf(b.id));
 return list;
}
function renderCollection(){
 const y=$('collectionGrid').scrollTop,list=filteredCollection();
 $('collectionGrid').innerHTML=list.length?list.map(e=>card(e.id)).join(''):`<div class="collection-empty">${onlyFavorites?'Пока здесь пусто.<br>Добавляй любимые элементы в избранное через атлас.':'Пока ничего не найдено.<br>Попробуй другую категорию или запрос.'}</div>`;
 $('collectionGrid').scrollTop=y;
 $('collectionMeta').textContent=onlyFavorites?'Избранные элементы':list.length===4&&found.size===4?'4 первоэлемента':`${list.length} ${noun(list.length,'элемент','элемента','элементов')}`;
 $('favoriteFilter').classList.toggle('active',onlyFavorites);$('favoriteFilter').setAttribute('aria-pressed',String(onlyFavorites));
 $('clearSearch').classList.toggle('hidden',!$('collectionSearch').value);
 renderCategories();
}
function measureTokens(){
 const token=tokens.querySelector('.token');
 if(token){const style=getComputedStyle(token);tokenSize={w:parseFloat(style.width),h:parseFloat(style.height)};}
 else{
  const fake=document.createElement('div');fake.className='token';fake.style.visibility='hidden';tokens.appendChild(fake);const style=getComputedStyle(fake);tokenSize={w:parseFloat(style.width),h:parseFloat(style.height)};fake.remove();
 }
}
function xy(t){return {x:clamp(t.u*Math.max(1,board.clientWidth-tokenSize.w),8,board.clientWidth-tokenSize.w-8),y:clamp(t.v*Math.max(1,board.clientHeight-tokenSize.h),26,board.clientHeight-tokenSize.h-16)};}
function uv(x,y){return {u:clamp((x-tokenSize.w/2)/Math.max(1,board.clientWidth-tokenSize.w),0,1),v:clamp((y-tokenSize.h/2)/Math.max(1,board.clientHeight-tokenSize.h),0,1)};}
function updateTokenPositions(){
 measureTokens();state.bench.forEach(t=>{const el=tokens.querySelector(`[data-token="${t.uid}"]`);if(el){const p=xy(t);el.style.left=p.x+'px';el.style.top=p.y+'px';}});
}
function renderBoard(freshId=null,failedIds=[]){
 tokens.innerHTML=state.bench.map(t=>`<button type="button" class="token ${t.uid===freshId?'fresh':''} ${failedIds.includes(t.uid)?'failed':''}" data-token="${t.uid}" data-element="${t.id}" aria-label="${name(t.id)}. Выбрать для смешивания. Shift плюс Enter — сведения.">${art(t.id)}<span class="element-name">${name(t.id)}</span><span class="token-info" data-detail="${t.id}" title="Сведения">i</span></button>`).join('');
 updateTokenPositions();renderSelection();
 $('boardCount').textContent=state.bench.length?`${state.bench.length} ${noun(state.bench.length,'элемент','элемента','элементов')} на столе`:'Стол готов к новому опыту';
 $('undoBtn').disabled=!undoStack.length;
}
function renderSelection(){
 const t=state.bench.find(t=>t.uid===selected);if(!t)selected=null;
 tokens.querySelectorAll('.token').forEach(el=>{el.classList.toggle('selected',el.dataset.token===selected);el.setAttribute('aria-pressed',String(el.dataset.token===selected));});
 $('collectionGrid').querySelectorAll('.element-card').forEach(el=>el.classList.toggle('selected',!!t&&el.dataset.pick===t.id));
 $('mixStatus').classList.toggle('hidden',!t);
 $('mixStatus').innerHTML=t?`${art(t.id)}<span>Теперь выбери второй элемент</span><button class="ico-btn" data-action="deselect" aria-label="Отменить выбор">${icon('x')}</button>`:'';
 $('boardCaption').innerHTML=t?`<strong>${name(t.id)}</strong> + что-то ещё. Выбери элемент в коллекции или на столе.`:(state.bench.length?'Нажми на два элемента или перетащи один на другой':'Выбери первый элемент в коллекции ниже или слева');
}
function renderAll(freshId=null,failed=[]){syncState();renderCollection();renderProgress();renderBoard(freshId,failed);}
function freePosition(){
 let best={u:.5,v:.5},score=-1;
 const candidates=[{u:.5,v:.5}];
 for(let y=0;y<5;y++)for(let x=0;x<6;x++)candidates.push({u:.04+x*.184,v:.05+y*.225});
 for(const c of candidates){const p=xy(c);const dist=state.bench.length?Math.min(...state.bench.map(t=>{const k=xy(t);return Math.hypot(p.x-k.x,p.y-k.y);})):10000;
 if(dist>score){score=dist;best=c;}}
 return best;
}
function addToken(id,pos=null){
 if(!found.has(id))return null;
 if(state.bench.length>=MAX_TOKENS){showToast('На столе слишком тесно','Удали лишнее или очисти стол — открытия останутся. ',null,'failure');return null;}
 const t={uid:uid(),id,...(pos||freePosition())};state.bench.push(t);return t;
}
function chooseFromCollection(id){
 if(!found.has(id))return;
 const first=state.bench.find(t=>t.uid===selected);
 pushUndo();const t=addToken(id);if(!t){undoStack.pop();return;}
 if(first){mix(first.uid,t.uid,false);return;}
 selected=t.uid;renderBoard();persist();playSound('select');
}
function chooseToken(id){
 const t=state.bench.find(t=>t.uid===id);if(!t)return;
 if(selected===id){selected=null;renderSelection();return;}
 if(selected&&state.bench.some(t=>t.uid===selected)){mix(selected,id,true);return;}
 selected=id;renderSelection();playSound('select');
}
function achievementEligible(a){return a.type==='count'?found.size>=a.value:a.type==='elements'?a.elements.every(x=>found.has(x)):a.type==='tried'?tried.size>=a.value:knownRecipes.size>=a.value;}
function updateAchievements(){const newly=[];for(const a of DATA.achievements)if(!badges.has(a.id)&&achievementEligible(a)){badges.add(a.id);newly.push(a);}return newly;}
function mix(id1,id2,snapshot=true){
 if(id1===id2)return false;
 const t1=state.bench.find(t=>t.uid===id1),t2=state.bench.find(t=>t.uid===id2);if(!t1||!t2)return false;
 if(snapshot)pushUndo();
 const key=pairKey(t1.id,t2.id),r=R.get(key),alreadyTried=tried.has(key),oldChapter=currentChapter();
 tried.add(key);state.attempts++;selected=null;
 const h={a:t1.id,b:t2.id,result:r?.result||null,isNew:!!r&&!found.has(r.result),time:Date.now()};
 state.history.unshift(h);if(state.history.length>HISTORY_LIMIT)state.history.length=HISTORY_LIMIT;
 let newToken=null,isNew=false;
 if(r){
  isNew=!found.has(r.result);found.add(r.result);knownRecipes.add(key);
  state.bench=state.bench.filter(t=>t.uid!==id1&&t.uid!==id2);
  newToken=addToken(r.result,{u:(t1.u+t2.u)/2,v:(t1.v+t2.v)/2});
  if(isNew){newThisSession.add(r.result);state.latest=r.result;if(state.pinned===r.result)state.pinned=null;if(hint?.recipe?.result===r.result)hint=null;}
 }
 const awards=updateAchievements();
 renderAll(newToken?.uid,r?[]:[id1,id2]);persist();
 if(r){
  const pos=xy(newToken);burst(pos.x+tokenSize.w/2,pos.y+tokenSize.h/2,isNew);playSound(isNew?'discovery':'success');
  let message=`${name(t1.id)} + ${name(t2.id)} · ${found.size} / ${E.size}`;
  if(awards.length)message+=` · ${awards[0].name}`;
  if(oldChapter!==currentChapter()||DATA.chapters.every(chapterComplete)&&oldChapter===DATA.chapters.at(-1)&&isNew)message+=` · Глава завершена!`;
  showToast(isNew?name(r.result):`Уже знакомо: ${name(r.result)}`,message,r.result,isNew?'new':'normal',isNew?3300:2000);
  return true;
 }
 playSound('failure');showToast(alreadyTried?'Это сочетание уже проверено':'Пока без превращения',`${name(t1.id)} + ${name(t2.id)}. Элементы остаются на столе.`,null,'failure',2300);return false;
}
function arrangeBench(snapshot=true){
 if(!state.bench.length)return;
 if(snapshot)pushUndo();
 measureTokens();const n=state.bench.length,w=board.clientWidth,h=board.clientHeight,gap=18;
 const maxCols=Math.max(1,Math.floor((w-10)/(tokenSize.w+6)));
 let cols=Math.min(maxCols,Math.ceil(Math.sqrt(n)));
 while(Math.ceil(n/cols)*(tokenSize.h+10)>h-37&&cols<maxCols)cols++;
 const rows=Math.ceil(n/cols);
 const stepX=Math.min(tokenSize.w+gap,(w-tokenSize.w-20)/Math.max(1,cols-1));
 const stepY=Math.min(tokenSize.h+gap,(h-tokenSize.h-42)/Math.max(1,rows-1));
 const startX=(w-((cols-1)*stepX+tokenSize.w))/2;
 const startY=Math.max(26,(h-((rows-1)*stepY+tokenSize.h))/2+5);
 state.bench.forEach((t,i)=>{const lastCount=n-(rows-1)*cols,lastRow=Math.floor(i/cols)===rows-1,offset=lastRow?(cols-lastCount)*stepX/2:0;Object.assign(t,uv(startX+(i%cols)*stepX+offset+tokenSize.w/2,startY+Math.floor(i/cols)*stepY+tokenSize.h/2));});
 selected=null;renderBoard();if(snapshot)persist();
}
function clearBench(){if(!state.bench.length){showToast('Стол уже свободен','Все открытые элементы доступны в коллекции.',null,'failure',1700);return;}pushUndo();state.bench=[];selected=null;renderBoard();persist();dismissToast();}
function undo(){if(!undoStack.length)return;cancelDrag();state.bench=undoStack.pop();selected=null;renderBoard();persist();dismissToast();announce('Изменение стола отменено. Открытия сохранены.');}

/* Unified dragging. On a touch screen the collection scrolls normally; tap twice to mix.
 * Only bench objects use touch-action:none. No touch/mouse duplicate listeners.
 */
function tokenAt(clientX,clientY,except=null){
 let closest=null,best=Infinity;
 for(const el of tokens.querySelectorAll('.token')){if(el.dataset.token===except)continue;const rect=el.getBoundingClientRect();
  if(clientX>=rect.left-6&&clientX<=rect.right+6&&clientY>=rect.top-6&&clientY<=rect.bottom+6){const d=Math.hypot(clientX-rect.left-rect.width/2,clientY-rect.top-rect.height/2);if(d<best){best=d;closest=el;}}
 }return closest;
}
function inRect(x,y,rect){return x>=rect.left&&x<=rect.right&&y>=rect.top&&y<=rect.bottom;}
const LIFT_MS=260,LIFT_SLOP=8;var liftTimer=0;
function clearLift(){if(liftTimer){clearTimeout(liftTimer);liftTimer=0;}document.querySelectorAll('.element-card.pressing').forEach(el=>el.classList.remove('pressing'));}
/* На телефоне элемент из коллекции поднимается долгим нажатием: обычный сдвиг
 * пальца должен остаться прокруткой списка, поэтому сразу тянуть нельзя. */
function beginLift(){
 liftTimer=0;
 const d=drag;
 if(!d||d.active)return;
 if(!d.element?.isConnected){cleanupDrag();return;}      // коллекция перерисовалась под пальцем
 d.active=true;d.ghost=document.createElement('div');d.ghost.className='token drag-ghost';
 d.ghost.innerHTML=art(d.id)+`<span class="element-name">${name(d.id)}</span>`;document.body.appendChild(d.ghost);
 d.ghost.style.left=d.startX-d.offsetX+'px';d.ghost.style.top=d.startY-d.offsetY+'px';
 d.element.classList.remove('pressing');d.element.classList.add('dragging');
 try{d.element.setPointerCapture(d.pointer);}catch(err){}
 $('trashTarget').classList.toggle('hidden',d.source!=='bench');
 suppressClickUntil=performance.now()+400;               // отпускание после подъёма — не тап
 playSound('select');
}
function pointerDown(e){
 if(e.button!==0||modal.open||drag||e.target.closest('[data-detail]'))return;
 const benchEl=e.target.closest('[data-token]'),shelfEl=e.target.closest('#collectionGrid [data-pick]');
 if(!benchEl&&!shelfEl)return;
 const el=benchEl||shelfEl,t=benchEl?state.bench.find(t=>t.uid===el.dataset.token):null;
 if(benchEl&&!t)return;
 const rect=el.getBoundingClientRect();
 drag={pointer:e.pointerId,source:benchEl?'bench':'shelf',id:t?.id||el.dataset.pick,uid:t?.uid||null,element:el,startX:e.clientX,startY:e.clientY,active:false,ghost:null,target:null,offsetX:benchEl?e.clientX-rect.left:tokenSize.w/2,offsetY:benchEl?e.clientY-rect.top:tokenSize.h/2};
 if(!benchEl&&e.pointerType==='touch'){el.classList.add('pressing');liftTimer=setTimeout(beginLift,LIFT_MS);}
}
function pointerMove(e){
 if(!drag||drag.pointer!==e.pointerId)return;
 const d=drag;
 if(!d.active){
  if(liftTimer&&Math.hypot(e.clientX-d.startX,e.clientY-d.startY)>LIFT_SLOP){clearLift();cleanupDrag();return;} // это прокрутка
  if(liftTimer)return;                                    // ждём долгое нажатие
  if(Math.hypot(e.clientX-d.startX,e.clientY-d.startY)<7)return;
  d.active=true;d.ghost=document.createElement('div');d.ghost.className='token drag-ghost';d.ghost.innerHTML=art(d.id)+`<span class="element-name">${name(d.id)}</span>`;document.body.appendChild(d.ghost);d.element.classList.add('dragging');
  try{d.element.setPointerCapture(e.pointerId);}catch(err){}
  $('trashTarget').classList.toggle('hidden',d.source!=='bench');
 }
 e.preventDefault();d.ghost.style.left=e.clientX-d.offsetX+'px';d.ghost.style.top=e.clientY-d.offsetY+'px';
 const onBoard=inRect(e.clientX,e.clientY,board.getBoundingClientRect());board.classList.toggle('drop-ready',onBoard);
 const target=onBoard?tokenAt(e.clientX,e.clientY,d.uid):null;
 if(d.target!==target){d.target?.classList.remove('target','known');d.target=target;if(target){target.classList.add('target');target.classList.toggle('known',knownRecipes.has(pairKey(d.id,target.dataset.element)));}}
 if(d.source==='bench')$('trashTarget').classList.toggle('over',inRect(e.clientX,e.clientY,$('trashTarget').getBoundingClientRect()));
}
function cleanupDrag(){
 clearLift();
 if(!drag)return;
 drag.ghost?.remove();drag.element?.classList.remove('dragging');drag.target?.classList.remove('target','known');
 try{if(drag.element?.hasPointerCapture(drag.pointer))drag.element.releasePointerCapture(drag.pointer);}catch(err){}
 board.classList.remove('drop-ready');$('trashTarget').classList.add('hidden');$('trashTarget').classList.remove('over');drag=null;
}
function cancelDrag(){if(drag?.active)suppressClickUntil=performance.now()+250;cleanupDrag();}
function pointerUp(e){
 if(!drag||drag.pointer!==e.pointerId)return;const d=drag;
 if(!d.active){cleanupDrag();return;}
 suppressClickUntil=performance.now()+250;
 const rect=board.getBoundingClientRect(),inBoard=inRect(e.clientX,e.clientY,rect),inTrash=d.source==='bench'&&inRect(e.clientX,e.clientY,$('trashTarget').getBoundingClientRect());
 const target=tokenAt(e.clientX,e.clientY,d.uid),targetId=target?.dataset.token;
 cleanupDrag();selected=null;
 if(inTrash){pushUndo();state.bench=state.bench.filter(t=>t.uid!==d.uid);renderBoard();persist();return;}
 if(!inBoard){renderSelection();return;}
 pushUndo();let moving;
 const pos=uv(e.clientX-rect.left-d.offsetX+tokenSize.w/2,e.clientY-rect.top-d.offsetY+tokenSize.h/2);
 if(d.source==='bench'){moving=state.bench.find(t=>t.uid===d.uid);if(moving)Object.assign(moving,pos);}
 else moving=addToken(d.id,pos);
 if(!moving){undoStack.pop();renderBoard();return;}
 if(targetId&&targetId!==moving.uid){mix(moving.uid,targetId,false);return;}
 renderBoard();persist();playSound('select');
}

/* Modal pages reuse one dialog rather than accumulating close handlers. */
function openModal(title,eyebrow,content,page,context=null,back=null){
 cancelDrag();dismissToast();
 if(!modal.open)focusBeforeModal=document.activeElement;
 modalPage=page;modalContext=context;modalBack=back;
 $('modalTitle').textContent=title;$('modalEyebrow').textContent=eyebrow;$('modalBody').innerHTML=content;$('modalBody').scrollTop=0;
 if(!modal.open)modal.showModal();
 $('closeModal').focus({preventScroll:true});
 document.querySelectorAll('.bottomnav button').forEach(b=>b.classList.toggle('active',b.dataset.action===page));
}
function closeModal(){if(modal.open)modal.close();modalPage=null;modalContext=null;modalBack=null;confirmAction=null;document.querySelectorAll('.bottomnav button').forEach(b=>b.classList.toggle('active',b.dataset.action==='home'));if(focusBeforeModal?.isConnected)focusBeforeModal.focus({preventScroll:true});}
function emptyState(id,title,body){return `<div class="empty-state">${art(id)}<h3>${title}</h3><p>${body}</p></div>`;}
function recipeRow(r,resultVisible=false,load=true){
 return `<div class="recipe-row"><button class="mini-element" data-detail="${r.a}">${art(r.a)}<span class="element-name">${name(r.a)}</span></button><span class="formula-sign">+</span><button class="mini-element" data-detail="${r.b}">${art(r.b)}<span class="element-name">${name(r.b)}</span></button>${resultVisible?`<span class="formula-sign">=</span><button class="mini-element" data-detail="${r.result}">${art(r.result)}<span class="element-name">${name(r.result)}</span></button>`:''}${load?`<button class="ico-btn" data-load-recipe="${r.key}" title="Выложить ингредиенты на стол" aria-label="Выложить ингредиенты на стол">${icon('copy')}</button>`:''}</div>`;
}
let atlasFilter={q:'',category:'all',all:false};
function atlasItems(){
 const q=atlasFilter.q.toLocaleLowerCase('ru').replaceAll('ё','е').trim();
 const list=DATA.elements.filter(e=>(atlasFilter.all||found.has(e.id))&&(atlasFilter.category==='all'||e.category===atlasFilter.category)&&(!q||(found.has(e.id)&&(e.name.toLocaleLowerCase('ru').replaceAll('ё','е')+' '+e.id).includes(q))));
 return list.length?list.map(e=>card(e.id,'detail',!found.has(e.id))).join(''):'<div class="collection-empty">Ничего не найдено. Закрытые названия не участвуют в поиске.</div>';
}
function showAtlas(reset=false){
 if(reset)atlasFilter={q:'',category:'all',all:false};
 const content=`<div class="modal-toolbar"><label class="search-box">${icon('search')}<input id="atlasSearch" placeholder="Найти открытый элемент…" value="${escapeHTML(atlasFilter.q)}" aria-label="Поиск в атласе" type="search"></label><select id="atlasCategory" aria-label="Категория атласа"><option value="all">Все категории</option>${DATA.categories.map(c=>`<option value="${c.id}" ${atlasFilter.category===c.id?'selected':''}>${c.name}</option>`).join('')}</select><button class="chip ${atlasFilter.all?'active':''}" data-action="atlas-all" aria-pressed="${atlasFilter.all}">Показывать тайны</button></div><div class="atlas-caption">${found.size} / ${E.size} открытий · ${knownRecipes.size} / ${R.size} найденных рецептов. Нажми на карточку, чтобы узнать её историю.</div><div class="atlas-grid" id="atlasGrid">${atlasItems()}</div>`;
 openModal('Атлас маленьких чудес','Каждое открытие — новая страница',content,'atlas');
}
function showDetail(id){
 if(!found.has(id)){showLocked(id);return;}
 const e=E.get(id),recipes=DATA.recipes.filter(r=>r.result===id),known=recipes.filter(r=>knownRecipes.has(r.key));
 const uses=DATA.recipes.filter(r=>(r.a===id||r.b===id)&&knownRecipes.has(r.key));
 const unknownCount=recipes.length-known.length;
 const content=`<div class="detail-layout"><div class="detail-hero">${art(id)}<h3>${e.name}</h3><span class="pill">${C.get(e.category).name} · Глубина цепочки ${e.tier}</span><p>${e.description}</p><div class="detail-actions"><button class="primary" data-add-table="${id}">${icon('lab')} На стол</button><button class="secondary" data-favorite="${id}" aria-pressed="${favorites.has(id)}">${icon('star')} ${favorites.has(id)?'В избранном':'В избранное'}</button></div></div><div><div class="detail-section"><h4>КАК ПОЛУЧИТЬ</h4>${BASE.includes(id)?'<div class="detail-note">Первоэлемент. Доступен с самого начала и никогда не заканчивается.</div>':known.length?known.map(r=>recipeRow(r)).join(''):'<div class="detail-note">Элемент открыт, но его рецепт ещё не записан в этом атласе. Так бывает после переноса старого сохранения.</div>'}${unknownCount&&!BASE.includes(id)?`<p style="margin-top:10px;font-size:10px">Ещё ${unknownCount} ${noun(unknownCount,'способ','способа','способов')} получения ждёт открытия. Атлас не раскрывает найденное за тебя.</p>`:''}</div><div class="detail-section"><h4>ИЗВЕСТНЫЕ ПРЕВРАЩЕНИЯ</h4>${uses.length?uses.map(r=>recipeRow(r,true)).join(''):`<div class="detail-note">${DATA.recipes.some(r=>r.a===id||r.b===id)?'Ты ещё не записал превращения с этим элементом. Попробуй соединить его с чем-то знакомым.':'Завершённое открытие. Это один из финальных элементов коллекции — новых превращений с ним нет.'}</div>`}</div><div class="detail-note">Рецепты — игровые ассоциации и фантазия, а не инструкции по химии. Все ингредиенты в коллекции бесконечны.</div><button class="text-btn" data-action="atlas" style="margin-top:12px">${icon('book')} Вернуться к атласу</button></div></div>`;
 openModal(e.name,'Лист '+String(DATA.elements.indexOf(e)+1).padStart(3,'0')+' · '+C.get(e.category).name,content,'detail',id);
}
function showLocked(id){
 const e=E.get(id);
 openModal('Ещё одна тайна','В атласе всё ещё есть белые пятна',emptyState('question','Неоткрытый элемент',`Эта страница принадлежит категории «${C.get(e.category).name}». Продолжай эксперименты — или воспользуйся подсказкой, которая подберёт доступное сейчас открытие.`)+`<div class="button-row" style="justify-content:center"><button class="primary" data-action="hint">${icon('hint')} Найти новую искру</button><button class="secondary" data-action="atlas">Назад в атлас</button></div>`,'locked');
}
function showChapters(){
 const current=currentChapter(),total=DATA.chapters.length,worlds=(DATA.worlds&&DATA.worlds.length?DATA.worlds:[{id:'all',name:'Все главы',description:'',color:'#9e9fd2',chapters:DATA.chapters.map(c=>c.id)}]);
 const worldSections=worlds.map(world=>{const chapters=DATA.chapters.filter(c=>(c.world||'all')===world.id);if(!chapters.length)return '';const complete=chapters.filter(chapterComplete).length;return `<section style="margin-bottom:22px"><div class="detail-note" style="margin-bottom:12px;border-left:4px solid ${world.color};padding-left:12px"><strong style="display:block;margin-bottom:4px">${escapeHTML(world.name)}</strong><span>${escapeHTML(world.description||'')}</span><div style="margin-top:6px;font-size:10px">${complete} / ${chapters.length} глав завершено</div></div><div class="chapter-grid">${chapters.map(c=>{const i=DATA.chapters.indexOf(c);return `<section class="chapter-tile ${c===current?'current':''}"><div class="eyebrow">Глава ${String(i+1).padStart(2,'0')} · ${chapterComplete(c)?'Завершена':c===current?'Твоя следующая история':'Впереди'}</div><h3>${c.title}</h3><p>${c.subtitle}</p><div class="goal-list">${c.goals.map(goalRow).join('')}</div><div class="chapter-progress"><span style="width:${c.goals.filter(id=>found.has(id)).length/c.goals.length*100}%"></span></div></section>`;}).join('')}</div></section>`;}).join('');
 const content=`${state.pinned?`<div class="goal-focus">${art(state.pinned)}<div><p>Твоя цель</p><strong>${name(state.pinned)}</strong></div><button class="ico-btn" data-action="hint" title="Подсказка к цели">${icon('hint')}</button><button class="ico-btn" data-action="unpin" aria-label="Снять цель">${icon('x')}</button></div>`:''}<div class="modal-toolbar" style="margin-bottom:14px"><button class="chip active" data-action="chapters">Главы</button><button class="chip" data-action="epochs">Эпохи</button><button class="chip" data-action="campaign">Кампания</button></div><p style="margin-bottom:18px">Теперь главы сгруппированы по эпохам мира. Они помогают не потеряться в большом атласе, но не ограничивают свободу экспериментов. Нажми на неизвестную цель, чтобы проложить путь к ней.</p>${worldSections}`;
 openModal('Путь алхимика',DATA.chapters.filter(chapterComplete).length+' из '+total+' глав завершено · '+worlds.length+' эпох',content,'chapters');
}
function showAchievements(){
 const content=`<div class="stat-grid"><div class="stat-box"><strong>${badges.size}/${DATA.achievements.length}</strong><span>достижений</span></div><div class="stat-box"><strong>${found.size}</strong><span>открытых элементов</span></div><div class="stat-box"><strong>${knownRecipes.size}</strong><span>записанных рецептов</span></div></div><div class="achievement-grid">${DATA.achievements.map(a=>`<div class="achievement-card ${badges.has(a.id)?'earned':''}">${art(a.art)}<h3>${a.name}</h3><p>${a.text}</p><span class="pill">${badges.has(a.id)?'Получено':a.type==='count'?Math.min(found.size,a.value)+' / '+a.value:a.type==='tried'?Math.min(tried.size,a.value)+' / '+a.value:a.type==='recipes'?Math.min(knownRecipes.size,a.value)+' / '+a.value:a.elements.filter(x=>found.has(x)).length+' / '+a.elements.length}</span></div>`).join('')}</div>`;
 openModal('Маленькие большие победы','Любопытство заслуживает награды',content,'achievements');
}
let journalFilter='all';
function journalRows(){
 const list=state.history.filter(h=>journalFilter==='all'||journalFilter==='success'&&h.result||journalFilter==='new'&&h.isNew);
 return list.length?list.map(h=>`<div class="journal-row">${art(h.result||'question')}<div class="journal-copy"><strong>${h.result?name(h.result):'Без превращения'}</strong><small>${name(h.a)} + ${name(h.b)}</small></div>${h.isNew?'<span class="pill">Новое</span>':''}<time>${new Date(h.time).toLocaleTimeString('ru',{hour:'2-digit',minute:'2-digit'})}</time><button data-load-recipe="${pairKey(h.a,h.b)}" title="Повторить опыт" aria-label="Повторить ${name(h.a)} плюс ${name(h.b)}">${icon('copy')}</button></div>`).join(''):emptyState('book','Чистая страница','Здесь появятся твои опыты. Удачные открытия и неудачные сочетания одинаково помогают понять мир.');
}
function showJournal(){
 openModal('Дневник опытов','Последние '+HISTORY_LIMIT+' опытов · новые записи сверху',`<div class="stat-grid"><div class="stat-box"><strong>${state.attempts}</strong><span>всего экспериментов</span></div><div class="stat-box"><strong>${tried.size}</strong><span>разных сочетаний</span></div><div class="stat-box"><strong>${knownRecipes.size}</strong><span>удачных рецептов</span></div></div><div class="modal-toolbar">${[['all','Все опыты'],['success','Удачные'],['new','Новые открытия']].map(([k,l])=>`<button class="chip ${journalFilter===k?'active':''}" data-journal-filter="${k}">${l}</button>`).join('')}<button class="text-btn" data-action="achievements" style="margin-left:auto">${icon('star')} Достижения</button></div><div id="journalEntries">${journalRows()}</div>`,'journal');
}
function showSettings(keepScroll=false){
 const scroll=keepScroll?$('modalBody').scrollTop:0;
 const content=`<section class="settings-section"><h3>Твоя лаборатория</h3><div class="setting-row"><div class="setting-copy"><strong>Звуки превращений</strong><small>Короткие ноты, без фоновой музыки и зацикливания.</small></div><button class="switch" role="switch" aria-label="Звуки превращений" aria-checked="${state.settings.sound}" data-setting="sound"></button></div><div class="setting-row"><div class="setting-copy"><strong>Анимации и искры</strong><small>Можно отключить для спокойствия или экономии батареи.</small></div><button class="switch" role="switch" aria-label="Анимации и искры" aria-checked="${state.settings.motion}" data-setting="motion"></button></div></section><section class="settings-section"><h3>Сохранения</h3><p>${storageOK?'Прогресс сохраняется автоматически в этом браузере после каждого изменения.':'Автосохранение недоступно в этом браузере. Используй экспорт, чтобы не потерять открытия.'} Очистка данных браузера удалит локальное сохранение. Для переноса на другой телефон или компьютер выгрузи файл и загрузи его там.</p><div class="button-row"><button class="primary" data-action="export">${icon('download')} Сохранить файлом</button><button class="secondary" data-action="import">${icon('upload')} Загрузить файл</button></div><p style="font-size:10px;margin-top:10px">Импорт заменит текущий прогресс только после подтверждения. Оригинальное сохранение старой игры не изменяется.</p></section><section class="settings-section"><h3>Резервная копия</h3><p>При автосохранении сохраняется предыдущий исправный снимок. Перенос из версий 1–5 выполняется только при отсутствии нового сохранения и доступе к тому же хранилищу браузера; старые записи не удаляются.</p><button class="secondary" data-action="restore-backup">Восстановить предыдущий снимок</button></section><section class="settings-section"><h3>Начать заново</h3><p>Только полный сброс удаляет открытия, избранное, журнал и достижения. Кнопка «Очистить стол» этого не делает.</p><div class="button-row"><button class="secondary danger" data-action="reset">${icon('trash')} Сбросить весь прогресс</button></div></section><div class="button-row"><button class="secondary" data-action="help">${icon('help')} Как играть</button><button class="secondary" data-action="achievements">${icon('star')} Достижения</button></div><p style="font-size:10px;margin-top:22px">Alchemia · Доводка 5.1 · ${E.size} иллюстрированных элементов · ${R.size} рецептов · ${(DATA.chapters||[]).length} глав, ${(DATA.worlds||[]).length||1} эпох и ${((DATA.campaigns||[]).length)} кампаний · без рекламы, регистрации, аналитики и внешних зависимостей. Названия и рецепты — игровые ассоциации, не научная модель. На смартфоне открывай игру в браузере; предпросмотр HTML в приложении «Файлы» может не выполнять JavaScript.</p>`;
 openModal('Настройки','Настрой уют, не отвлекаясь от чудес',content,'settings');if(keepScroll)$('modalBody').scrollTop=scroll;
}
function showHelp(){
 const content=`<div class="help-grid"><div class="help-card">${icon('hand')}<h3>Два нажатия — один опыт</h3><p>Нажми на элемент в коллекции: он появится на столе и получит метку «1». Нажми на второй элемент в коллекции или на столе — они смешаются. Для сочетания с самим собой дважды выбери одну карточку в коллекции.</p></div><div class="help-card">${icon('lab')}<h3>Двигай и соединяй</h3><p>На столе элементы можно перетаскивать мышью или пальцем. Положи один поверх другого для смешивания. На телефоне коллекция прокручивается обычным жестом: перетаскивать из неё не обязательно.</p></div><div class="help-card">${icon('book')}<h3>Мир остаётся с тобой</h3><p>Открытые элементы навсегда остаются в коллекции и не заканчиваются. Неудачный опыт ничего не уничтожает. «Очистить стол» убирает только карточки со стола. В атласе есть описания, избранное и найденные рецепты.</p></div><div class="help-card">${icon('hint')}<h3>Подсказка, а не спойлер</h3><p>«Нужна искра?» сначала покажет направление, затем второй ингредиент и только потом ответ. Подсказки бесплатны и не имеют таймера. В заданиях можно выбрать конкретное открытие своей целью.</p></div></div><div class="detail-note" style="margin-top:20px">На компьютере: <span class="key">/</span> — поиск, <span class="key">Esc</span> — отменить выбор или закрыть окно, <span class="key">Ctrl+Z</span> — отменить изменение стола, <span class="key">Delete</span> — убрать выбранную карточку. <span class="key">Shift+клик</span>, <span class="key">Shift+Enter</span> или правая кнопка на элементе — сведения. Все элементы управления доступны через <span class="key">Tab</span>.</div><p style="margin-top:16px;font-size:11px">Начни, например, с воды и огня. Но помни: это сказочная алхимия, а не инструкция по смешиванию настоящих веществ.</p><div class="button-row"><button class="primary" data-action="home">${icon('lab')} В лабораторию</button></div>`;
 openModal('Как рождаются чудеса','Четыре стихии. Никакой спешки.',content,'help');
}

/* Find a frontier recipe on a currently cheapest known path to a target.
 * Costs only decrease in a finite relaxation; recursion explicitly guards cycles.
 * Every returned hint has both ingredients already in the player's collection.
 */
function findHint(target=null){
 const cost=new Map(DATA.elements.map(e=>[e.id,found.has(e.id)?0:Infinity])),best=new Map();
 for(let pass=0;pass<E.size;pass++){
  let changed=false;
  for(const r of DATA.recipes){const value=cost.get(r.a)+cost.get(r.b)+1;if(value<cost.get(r.result)){cost.set(r.result,value);best.set(r.result,r);changed=true;}}
  if(!changed)break;
 }
 const nextNeeded=(id,visited=new Set())=>{
  if(found.has(id)||visited.has(id))return null;visited.add(id);const r=best.get(id);if(!r)return null;
  if(found.has(r.a)&&found.has(r.b))return r;
  return nextNeeded(r.a,new Set(visited))||nextNeeded(r.b,new Set(visited));
 };
 if(target&&!found.has(target)){const recipe=nextNeeded(target);if(recipe)return {recipe,target};}
 const goals=currentChapter().goals.filter(id=>!found.has(id)).sort((a,b)=>cost.get(a)-cost.get(b));
 for(const id of goals){const recipe=nextNeeded(id);if(recipe)return {recipe,target:id};}
 const frontier=DATA.recipes.filter(r=>found.has(r.a)&&found.has(r.b)&&!found.has(r.result));
 if(frontier.length){const recipe=frontier[Math.floor(Math.random()*Math.min(frontier.length,14))];return {recipe,target:recipe.result};}
 const alternative=DATA.recipes.find(r=>found.has(r.a)&&found.has(r.b)&&!knownRecipes.has(r.key));
 return alternative?{recipe:alternative,target:alternative.result,alternative:true}:null;
}
function showHint(reset=false){
 if(reset||!hint||!found.has(hint.recipe.a)||!found.has(hint.recipe.b)||found.has(hint.recipe.result)&&!hint.alternative||hint.target!==state.pinned&&state.pinned){const info=findHint(state.pinned);hint=info?{...info,stage:1}:null;}
 if(!hint){openModal('Все тайны раскрыты','Великое делание завершено',emptyState('philosopher','Атлас заполнен до последней строчки','Ты открыл все элементы и все способы их получения. Можно любоваться коллекцией, продолжать эксперименты или сохранить этот мир отдельным файлом.')+`<div class="button-row" style="justify-content:center"><button class="primary" data-action="export">${icon('download')} Сохранить этот мир</button><button class="secondary" data-action="atlas">Открыть атлас</button></div>`,'hint');return;}
 const r=hint.recipe,e=E.get(r.result),stage=hint.stage;
 const goal=hint.target!==r.result?`Это шаг на пути к открытию «${name(hint.target)}».`:'Небольшое открытие, которое уже тебе по силам.';
 const title=stage===1?'Начни с одной знакомой вещи':stage===2?'Кажется, эти двое подружатся':hint.alternative?'Ещё один путь к знакомому':'Вот какое чудо тебя ждёт';
 const description=stage===1?`Возьми «${name(r.a)}». Второй ингредиент ${r.a===r.b?'— ещё один такой же элемент':`найдётся в категории «${C.get(E.get(r.b).category).name}»`}. Оба уже есть в твоей коллекции.`:stage===2?`Соедини «${name(r.a)}» и «${name(r.b)}». Ответ пока останется маленьким сюрпризом.`:e.description;
 const content=`<div class="hint-card">${art(stage===3?r.result:'potion')}<div class="eyebrow">Подсказка ${stage} из 3 · без ограничений</div><h3 style="margin-top:10px">${title}</h3><p>${description}</p><div class="hint-formula"><div class="hint-ingredient">${art(r.a)}<span>${name(r.a)}</span></div><span>+</span><div class="hint-ingredient">${stage>=2?art(r.b):'<div class="mystery">?</div>'}<span>${stage>=2?name(r.b):'Второй ингредиент'}</span></div>${stage===3?`<span>=</span><div class="hint-ingredient">${art(r.result)}<span>${name(r.result)}</span></div>`:''}</div><p style="font-size:10px;margin-bottom:13px">${goal}</p><div class="button-row" style="justify-content:center">${stage<3?`<button class="primary" data-action="hint-next">${stage===1?'Открыть второй ингредиент':'Показать результат'} ${icon('arrow')}</button>`:''}${stage>=2?`<button class="${stage===3?'primary':'secondary'}" data-load-recipe="${r.key}">${icon('lab')} На рабочий стол</button>`:''}<button class="text-btn" data-action="hint-other">Другая искра</button></div><div class="hint-stages">${[1,2,3].map(i=>`<span class="${i<=stage?'active':''}"></span>`).join('')}</div></div>`;
 openModal('Нужна искра?','Иногда хватает маленького толчка',content,'hint');
}
function loadPair(key){
 if(!validPair(key))return;
 const [a,b]=key.split('+');if(!found.has(a)||!found.has(b)){showToast('Ингредиенты ещё не открыты','Подсказка подберёт доступное сейчас сочетание.',null,'failure');return;}
 if(state.bench.length>MAX_TOKENS-2){showToast('Сначала освободи место','Удали две карточки или очисти рабочий стол.',null,'failure');return;}
 closeModal();pushUndo();const t1=addToken(a,{u:.3,v:.43});const t2=addToken(b,{u:.7,v:.43});selected=t1.uid;renderBoard();persist();announce('Ингредиенты на столе. Нажми на второй, чтобы смешать.');
}
function pinGoal(id){if(found.has(id)){showDetail(id);return;}state.pinned=id;hint=null;persist();renderProgress();showHint();}
function requestConfirm(title,body,label,fn,back='settings'){
 confirmAction=fn;
 openModal(title,'Это действие изменит текущую игру',`<p class="confirm-copy">${body}</p><div class="button-row"><button class="primary" data-action="confirm">${label}</button><button class="secondary" data-action="confirm-cancel">Отмена</button></div>`,'confirm',null,back);
}
function resetGame(){
 requestConfirm('Начать с чистого листа?','Все открытия, записи, достижения и избранное в этой игре будут удалены. Перед сбросом можно отменить действие и выгрузить сохранение в настройках.','Да, начать заново',()=>{
  const settings=clone(state.settings);state=freshState();state.settings=settings;found=new Set(BASE);knownRecipes=new Set();tried=new Set();favorites=new Set();badges=new Set();selected=null;undoStack=[];newThisSession.clear();category='all';onlyFavorites=false;$('collectionSearch').value='';hint=null;
  storageLocked=false;loadWarning='';$('saveWarning').classList.add('hidden');stopParticles();closeModal();applySettings();renderAll();arrangeBench(false);persist();showToast('Новый маленький мир','Четыре стихии снова готовы удивлять.',null,'normal',2300);
 });
}
function exportSave(){
 syncState();const exported={...clone(state),exportedAt:new Date().toISOString()};
 const blob=new Blob([JSON.stringify(exported,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');
 const stamp=new Date().toISOString().replace(/[:T]/g,'-').slice(0,16);a.href=url;a.download=`alchemia-save-${stamp}.json`;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1500);
 announce('Браузеру передан файл сохранения Alchemia.');
}
async function importSave(file){
 if(!file)return;
 if(file.size>MAX_SAVE_BYTES){openModal('Файл слишком большой','Импорт не выполнен','<p>Размер сохранения не должен превышать 8 МБ. Текущая игра не изменена.</p><div class="button-row"><button class="secondary" data-action="settings">Назад</button></div>','error');return;}
 try{
  const imported=cleanSave(JSON.parse(await file.text()));
  requestConfirm('Загрузить этот мир?',`В файле открыто <strong>${imported.discovered.length} из ${E.size}</strong> элементов и записано <strong>${imported.recipeKeys.length}</strong> рецептов. Сейчас у тебя открыто <strong>${found.size}</strong> элементов. Загрузка заменит текущую игру, а не объединит коллекции.`,`Загрузить ${imported.discovered.length} элементов`,()=>{
   storageLocked=false;loadWarning='';$('saveWarning').classList.add('hidden');state=imported;found=new Set(state.discovered);knownRecipes=new Set(state.recipeKeys);tried=new Set(state.tried);favorites=new Set(state.favorites);badges=new Set();updateAchievements();selected=null;undoStack=[];newThisSession.clear();category='all';onlyFavorites=false;$('collectionSearch').value='';hint=null;stopParticles();closeModal();applySettings();renderAll();arrangeBench(false);persist();showToast('Мир восстановлен',`${found.size} открытий снова в твоей коллекции.`,null,'normal',2500);
  });
 }catch(err){openModal('Не удалось загрузить файл','Текущая игра не изменена',`<p>Проверь, что это JSON-сохранение Alchemia (схема 1 или 2). Повреждённые файлы и сохранения других игр не поддерживаются.</p><div class="button-row"><button class="secondary" data-action="settings">Назад к сохранениям</button></div>`,'error');}
}

/* One delegated action handler survives every render without accumulating listeners. */
function action(name){
 switch(name){
  case'home':closeModal();break;
  case'help':showHelp();break;
  case'atlas':showAtlas();break;
  case'chapters':showChapters();break;
  case'epochs':showEpochs();break;
  case'restore-backup':restoreBackup();break;
  case'campaign':showCampaign();break;
  case'journal':showJournal();break;
  case'achievements':showAchievements();break;
  case'settings':showSettings();break;
  case'sound':toggleSound();break;
  case'dismiss-toast':dismissToast();break;
  case'deselect':selected=null;renderSelection();break;
  case'clear':clearBench();break;
  case'arrange':arrangeBench();break;
  case'undo':undo();break;
  case'hint':showHint();break;
  case'hint-next':if(hint){hint.stage=Math.min(3,hint.stage+1);showHint();}break;
  case'hint-other':{
   const previous=hint?.recipe.key;const frontier=DATA.recipes.filter(r=>found.has(r.a)&&found.has(r.b)&&!found.has(r.result)&&r.key!==previous);
   if(frontier.length){const recipe=frontier[Math.floor(Math.random()*frontier.length)];state.pinned=null;hint={recipe,target:recipe.result,stage:1};persist();showHint();}else showHint(true);break;
  }
  case'unpin':state.pinned=null;hint=null;persist();showChapters();break;
  case'atlas-all':atlasFilter.all=!atlasFilter.all;showAtlas();break;
  case'export':exportSave();break;
  case'import':$('importInput').value='';$('importInput').click();break;
  case'reset':resetGame();break;
  case'confirm':{const fn=confirmAction;confirmAction=null;fn?.();break;}
  case'confirm-cancel':confirmAction=null;action(modalBack||'settings');break;
 }
}
listen(document,'click',e=>{
 const details=e.target.closest('[data-detail]');
 if(details){if(performance.now()<suppressClickUntil)return;showDetail(details.dataset.detail);return;}
 const token=e.target.closest('[data-token]'),pick=e.target.closest('[data-pick]');
 if(token||pick){if(performance.now()<suppressClickUntil)return;const id=pick?.dataset.pick||state.bench.find(t=>t.uid===token?.dataset.token)?.id;
  if(e.shiftKey){if(id)showDetail(id);return;}if(pick)chooseFromCollection(pick.dataset.pick);else chooseToken(token.dataset.token);return;}
 const el=e.target.closest('[data-action],[data-category],[data-goal],[data-favorite],[data-add-table],[data-load-recipe],[data-locked],[data-journal-filter],[data-setting]');if(!el)return;
 if(el.dataset.action){action(el.dataset.action);return;}
 if(el.dataset.category){category=el.dataset.category;renderCollection();return;}
 if(el.dataset.goal){pinGoal(el.dataset.goal);return;}
 if(el.dataset.favorite){const id=el.dataset.favorite;favorites.has(id)?favorites.delete(id):favorites.add(id);persist();renderCollection();showDetail(id);return;}
 if(el.dataset.addTable){const id=el.dataset.addTable;closeModal();pushUndo();const t=addToken(id);if(t){selected=t.uid;renderBoard();persist();}return;}
 if(el.dataset.loadRecipe){loadPair(el.dataset.loadRecipe);return;}
 if(el.dataset.locked){showLocked(el.dataset.locked);return;}
 if(el.dataset.journalFilter){journalFilter=el.dataset.journalFilter;showJournal();return;}
 if(el.dataset.setting){const key=el.dataset.setting;state.settings[key]=!state.settings[key];applySettings();if(!state.settings.motion)stopParticles();persist();showSettings(true);if(key==='sound'&&state.settings.sound)playSound('select');}
});
listen(document,'pointerdown',pointerDown);
listen(document,'pointermove',pointerMove,{passive:false});
listen(document,'pointerup',pointerUp);
listen(document,'pointercancel',cancelDrag);
/* Путь алхимика на телефоне: на узком экране панель целей скрыта вёрсткой, поэтому
 * открываем её отдельным экраном, а главы и эпохи остаются внутри него кнопкой. */
listen(document,'click',e=>{
 if(e.target.closest('[data-action="path"]')&&!e.target.closest('.journey')){e.preventDefault();document.body.classList.add('path-open');return;}
 if(e.target.closest('.journey-close')||e.target.closest('.journey-sheet-head [data-action="chapters"]'))document.body.classList.remove('path-open');
});
listen(document,'keydown',e=>{if(e.key==='Escape'&&document.body.classList.contains('path-open'))document.body.classList.remove('path-open');});
listen(window,'blur',cancelDrag);
listen(document,'dragstart',e=>{if(e.target.closest('.token,.element-card'))e.preventDefault();});
listen(document,'contextmenu',e=>{const el=e.target.closest('[data-pick],[data-token]');if(!el)return;e.preventDefault();const id=el.dataset.pick||state.bench.find(t=>t.uid===el.dataset.token)?.id;if(id)showDetail(id);});
listen($('collectionSearch'),'input',()=>renderCollection());
listen($('clearSearch'),'click',()=>{$('collectionSearch').value='';renderCollection();$('collectionSearch').focus();});
listen($('favoriteFilter'),'click',()=>{onlyFavorites=!onlyFavorites;renderCollection();});
listen($('sortSelect'),'change',()=>{state.settings.sort=$('sortSelect').value;persist();renderCollection();});
listen($('closeModal'),'click',closeModal);
listen(modal,'cancel',e=>{e.preventDefault();closeModal();});
listen(modal,'click',e=>{if(e.target===modal&&!inRect(e.clientX,e.clientY,modal.getBoundingClientRect()))closeModal();});
listen($('modalBody'),'input',e=>{if(e.target.id==='atlasSearch'){atlasFilter.q=e.target.value;$('atlasGrid').innerHTML=atlasItems();}});
listen($('modalBody'),'change',e=>{if(e.target.id==='atlasCategory'){atlasFilter.category=e.target.value;$('atlasGrid').innerHTML=atlasItems();}});
/* Верхняя панель на телефоне: тянем ручку вверх — панель уезжает, тянем вниз —
   возвращается. Короткий тап по ручке переключает её. Состояние запоминаем. */
(()=>{
 const handle=$('topbarHandle');
 if(!handle)return;
 const setHidden=hidden=>{document.body.classList.toggle('topbar-hidden',hidden);handle.setAttribute('aria-expanded',String(!hidden));
  state.settings.topbarHidden=hidden;syncState();};
 setHidden(Boolean(state.settings.topbarHidden));
 let startY=0,moved=0,dragging=false;
 handle.addEventListener('pointerdown',e=>{dragging=true;moved=0;startY=e.clientY;try{handle.setPointerCapture(e.pointerId);}catch(err){}});
 handle.addEventListener('pointermove',e=>{
  if(!dragging)return;
  moved=e.clientY-startY;
  if(Math.abs(moved)>18){setHidden(moved>0);state.settings.topbarHidden=moved>0;dragging=false;}
 });
 const finish=e=>{
  if(!dragging)return;
  dragging=false;
  if(Math.abs(moved)<=18)setHidden(!document.body.classList.contains('topbar-hidden'));
  persist();
 };
 handle.addEventListener('pointerup',finish);
 handle.addEventListener('pointercancel',()=>{dragging=false;});
 handle.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();setHidden(!document.body.classList.contains('topbar-hidden'));persist();}});
})();
listen($('importInput'),'change',()=>importSave($('importInput').files?.[0]));
listen(document,'keydown',e=>{
 if(e.key==='Escape'){cancelDrag();if(!modal.open){selected=null;renderSelection();dismissToast();}return;}
 if(e.target.matches('input,textarea,select')||e.target.isContentEditable)return;
 const element=e.target.closest('[data-pick],[data-token]');
 if(e.key==='Enter'&&e.shiftKey&&element){e.preventDefault();const id=element.dataset.pick||state.bench.find(t=>t.uid===element.dataset.token)?.id;if(id)showDetail(id);return;}
 if(modal.open)return;
 if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();undo();return;}
 if(e.key==='/'){e.preventDefault();$('collectionSearch').focus();return;}
 if((e.key==='Delete'||e.key==='Backspace')&&selected){e.preventDefault();pushUndo();state.bench=state.bench.filter(t=>t.uid!==selected);selected=null;renderBoard();persist();}
});
const resizeObserver=new ResizeObserver(()=>{
 if(resizeFrame)cancelAnimationFrame(resizeFrame);
 resizeFrame=requestAnimationFrame(()=>{resizeFrame=0;cancelDrag();const nw=board.clientWidth,nh=board.clientHeight;
  const was=lastBoardSize;sizeCanvas();measureTokens();
  if(was.w&&((was.w>480)!==(nw>480)||Math.abs(nh-was.h)>140)){arrangeBench(false);persist();}else updateTokenPositions();
  lastBoardSize={w:nw,h:nh};
 });
});
resizeObserver.observe(board);
listen(document,'visibilitychange',()=>{if(document.hidden){cancelDrag();stopParticles();persist();audio?.suspend().catch(()=>{});}});
listen(window,'pagehide',()=>{cancelDrag();stopParticles();persist();audio?.suspend().catch(()=>{});});
/*__JOURNEY__*/
/* Public read-only inspection surface, useful for content and save compatibility checks. */
function auditContent(){
 const known=new Set(BASE),keys=new Set();let errors=[];
 for(const r of DATA.recipes){if(keys.has(r.key))errors.push('Duplicate pair '+r.key);keys.add(r.key);if(!E.has(r.a)||!E.has(r.b)||!E.has(r.result))errors.push('Unknown ingredient');if(r.key!==pairKey(r.a,r.b))errors.push('Invalid pair');}
 for(let i=0;i<E.size;i++){const size=known.size;for(const r of DATA.recipes)if(known.has(r.a)&&known.has(r.b))known.add(r.result);if(known.size===size)break;}
 return {elements:E.size,recipes:R.size,illustrations:document.querySelectorAll('symbol[id^="art-"]').length,reachable:known.size,errors,unreachable:[...E.keys()].filter(id=>!known.has(id))};
}
/* Вливание прогресса с другого устройства. Игра читает сохранение только при
 * старте, поэтому одного localStorage мало: серверные открытия надо применить к
 * живому состоянию, иначе следующее persist() затрёт их своим. */
function applyRemoteState(remote){
 if(!remote||typeof remote!=='object')return {added:0};
 const incoming=Array.isArray(remote.discovered)?remote.discovered.filter(id=>E.has(id)):[];
 const recipes=Array.isArray(remote.recipeKeys)?remote.recipeKeys.filter(k=>R.has(k)):null;
 let added=0;
 for(const id of incoming)if(!found.has(id)){found.add(id);newThisSession.add(id);added++;}
 if(recipes)for(const key of recipes)knownRecipes.add(key);
 updateAchievements();
 if(added){renderAll();playSound('discovered');}
 persist();
 return {added};
}
Object.defineProperty(window,'Alchemia',{value:Object.freeze({version:'5.1-refined',getState:()=>{syncState();return clone(state);},applyRemoteState,audit:auditContent}),writable:false});
updateAchievements();applySettings();renderAll();sizeCanvas();
if(!loaded)arrangeBench(false);
lastBoardSize={w:board.clientWidth,h:board.clientHeight};
// Do not overwrite a malformed existing save without explicit gameplay input.
if(!loadWarning)persist();
if(loadWarning){$('saveWarning').textContent=loadWarning;$('saveWarning').classList.remove('hidden');}
if(migrated>0)showToast('Старые открытия переехали',`${found.size} элементов из прошлой игры уже в атласе.`,null,'normal',4000);
})();
