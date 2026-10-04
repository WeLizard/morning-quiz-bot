(() => {
 'use strict';
 const DATA = JSON.parse(document.getElementById('game-data').textContent);
 const E = DATA.elements, C = DATA.categories, RECIPES = DATA.recipes, BASE = DATA.base;
 const ids = Object.keys(E), hasElement = id => typeof id === 'string' && Object.hasOwn(E, id);
 const pairKey = (a,b) => [a,b].sort().join('+');
 const recipesByKey = new Map(RECIPES.map(r => [r.key,r]));
 const recipesFor = new Map(ids.map(id => [id, RECIPES.filter(r => r.r === id)]));
 const KEY = 'alchemia-worlds-v1', APP = 'alchemia-worlds', MAX_BOARD = 40, MAX_HISTORY = 160;
 const $ = s => document.querySelector(s);
 const esc = value => String(value ?? '').replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
 const ui = id => `<svg class="ui" aria-hidden="true"><use href="#ui-${id}"/></svg>`;
 const art = (id, cls='') => hasElement(id) ? `<svg class="art ${cls}" viewBox="0 0 100 100" aria-hidden="true"><use href="#art-${id}"/></svg>` : ui('lock');
 const name = id => hasElement(id) ? E[id].name : 'Неизвестно';
 const limit = (x,min,max) => Math.max(min, Math.min(max, Number.isFinite(x) ? x : min));
 const clone = value => JSON.parse(JSON.stringify(value));
 const time = () => Date.now();
 let serial=0;
 const uid = () => 'n'+time().toString(36)+'_'+(serial++).toString(36);
 const plural = (n, forms) => forms[n%100>10 && n%100<20 ? 2 : n%10===1 ? 0 : n%10>=2 && n%10<=4 ? 1 : 2];
 const freshState = () => ({version:1, discovered:[...BASE], knownRecipes:[], favorites:[], experiments:[], firstFound:{}, board:[], slots:[null,null], mode:'crucible', settings:{sound:false,motion:true}, stats:{attempts:0,successes:0,samePair:0,hints:0}, awards:[], chapters:[], tracked:null});
 let storageAvailable=true, pendingNotice='', importedState=null;
 // Only recognized ids, exact recipe keys and bounded numeric data can enter the game.
 function sanitize(raw, strict=false) {
  if (!raw || typeof raw !== 'object' || !Array.isArray(raw.discovered)) throw Error('В файле нет коллекции элементов.');
  if (strict && raw.discovered.some(id => !hasElement(id))) throw Error('Это сохранение содержит элементы другой версии игры.');
  const s=freshState();
  s.discovered=[...new Set([...BASE,...raw.discovered.filter(hasElement)])];
  const d=new Set(s.discovered);
  s.knownRecipes=[...new Set((Array.isArray(raw.knownRecipes)?raw.knownRecipes:[]).filter(k => {
   const r=recipesByKey.get(k);return r && d.has(r.a)&&d.has(r.b)&&d.has(r.r);
  }))];
  s.favorites=[...new Set((Array.isArray(raw.favorites)?raw.favorites:[]).filter(id => hasElement(id)&&d.has(id)))];
  if (raw.firstFound && typeof raw.firstFound==='object') for(const id of s.discovered) {
   const f=raw.firstFound[id], r=recipesByKey.get(f?.recipe);
   if(r?.r===id && s.knownRecipes.includes(r.key)) s.firstFound[id]={recipe:r.key,time:limit(Number(f.time),0,8640000000000000)};
  }
  const list=Array.isArray(raw.experiments)?raw.experiments:[];
  s.experiments=list.slice(-MAX_HISTORY).filter(h => {
   if(!h||!hasElement(h.a)||!hasElement(h.b)||!d.has(h.a)||!d.has(h.b))return false;
   const r=recipesByKey.get(pairKey(h.a,h.b));
   return h.r===null?!r:r?.r===h.r&&d.has(h.r);
  }).map(h=>({a:h.a,b:h.b,r:h.r,key:pairKey(h.a,h.b),time:limit(Number(h.time),0,8640000000000000),fresh:h.fresh===true}));
  s.board=(Array.isArray(raw.board)?raw.board:[]).slice(0,MAX_BOARD).filter(n=>n&&hasElement(n.id)&&d.has(n.id)).map(n=>({uid:uid(),id:n.id,x:limit(Number(n.x),.08,.92),y:limit(Number(n.y),.12,.88)}));
  if(Array.isArray(raw.slots))s.slots=[0,1].map(i=>hasElement(raw.slots[i])&&d.has(raw.slots[i])?raw.slots[i]:null);
  s.mode=raw.mode==='table'?'table':'crucible';
  s.settings={sound:raw.settings?.sound===true,motion:raw.settings?.motion!==false};
  for(const k of Object.keys(s.stats))s.stats[k]=Math.floor(limit(Number(raw.stats?.[k]),0,1e9));
  s.stats.attempts=Math.max(s.stats.attempts,s.experiments.length);
  s.stats.successes=Math.max(s.stats.successes,s.knownRecipes.length);
  s.awards=(Array.isArray(raw.awards)?raw.awards:[]).filter(x=>typeof x==='string').slice(0,100);
  s.chapters=(Array.isArray(raw.chapters)?raw.chapters:[]).filter(x=>DATA.chapters.some(c=>c.id===x));
  s.tracked=hasElement(raw.tracked)?raw.tracked:null;
  return s;
 }
 function load() {
  try {
   const saved=localStorage.getItem(KEY);
   if(saved) {try{return sanitize(JSON.parse(saved));}catch(e){pendingNotice='Сохранение повреждено. Начата новая мастерская; оригинал пока не перезаписан.';return freshState();}}
   const old=localStorage.getItem('elementAlchemyDiscovered');
   if(old) {try{const oldIds=JSON.parse(old);if(Array.isArray(oldIds)){const s=sanitize({discovered:oldIds});if(s.discovered.length>4)pendingNotice='Открытия из классической версии перенесены в новую мастерскую.';return s;}}catch{}}
  }catch{storageAvailable=false;pendingNotice='Браузер запретил сохранение. Игра работает; сохраняй коллекцию в JSON через настройки.';}
  return freshState();
 }
 let state=load(), discovered=new Set(state.discovered), learned=new Set(state.knownRecipes);
 let filter='all',sort='discovery',activeSlot=null,selectedNodes=[],lastOutcome=null,undoStack=[],newest=null;
 let modalKind=null,previousFocus=null,hint=null,suppressClickUntil=0,drag=null,audioContext=null;
 let atlas={q:'',cat:'all',unknown:true},journalOnlySuccess=false,combineVisible=true;
 const syncSets=()=>{discovered=new Set(state.discovered);learned=new Set(state.knownRecipes);};
 const available=()=>RECIPES.filter(r=>discovered.has(r.a)&&discovered.has(r.b)&&!discovered.has(r.r));
 const currentChapter=()=>DATA.chapters.find(ch=>!ch.targets.every(id=>discovered.has(id)))||null;
 const completeChapters=()=>DATA.chapters.filter(ch=>ch.targets.every(id=>discovered.has(id))).length;
 const catCount=cat=>state.discovered.filter(id=>E[id].cat===cat).length;
 const ACHIEVEMENTS=[
  {id:'first',name:'Первая искра',desc:'Открыть свой первый элемент',art:'energy',test:()=>discovered.size>=5},
  {id:'ten',name:'Начало коллекции',desc:'Открыть 10 элементов',art:'seed',test:()=>discovered.size>=10},
  {id:'twentyfive',name:'Всё любопытнее',desc:'Открыть 25 элементов',art:'curiosity',test:()=>discovered.size>=25},
  {id:'fifty',name:'Увлечённый исследователь',desc:'Открыть 50 элементов',art:'compass',test:()=>discovered.size>=50},
  {id:'hundred',name:'Сотня маленьких чудес',desc:'Открыть 100 элементов',art:'book',test:()=>discovered.size>=100},
  {id:'twohundred',name:'Большая картина',desc:'Открыть 200 элементов',art:'planet',test:()=>discovered.size>=200},
  {id:'all',name:'Хранитель всех миров',desc:`Собрать все ${ids.length} элементов`,art:'worldtree',test:()=>discovered.size===ids.length},
  {id:'double',name:'В хорошей компании',desc:'Успешно смешать элемент с самим собой',art:'sea',test:()=>state.stats.samePair>0},
  {id:'gardener',name:'Мир оживает',desc:'Открыть 15 элементов живого мира',art:'tree',test:()=>catCount('life')>=15},
  {id:'friend',name:'Тёплый дом',desc:'Открыть дом, кошку и хлеб',art:'cat',test:()=>['house','cat','bread'].every(x=>discovered.has(x))},
  {id:'maker',name:'Инженер волшебства',desc:'Открыть 3D-принтер',art:'printer3d',test:()=>discovered.has('printer3d')},
  {id:'astronomer',name:'Звёздный взгляд',desc:'Открыть 10 космических элементов',art:'telescope',test:()=>catCount('cosmos')>=10},
  {id:'dragon',name:'Не буди дракона',desc:'Открыть дракона',art:'dragon',test:()=>discovered.has('dragon')},
  {id:'opus',name:'Великое делание',desc:'Создать философский камень',art:'philosopher',test:()=>discovered.has('philosopher')},
  {id:'chapters',name:'Сказка с продолжением',desc:'Завершить все восемь глав',art:'alchemy',test:()=>completeChapters()===8},
  {id:'recipes',name:'Каждый путь важен',desc:`Проверить все ${RECIPES.length} рецептов`,art:'knowledge',test:()=>learned.size===RECIPES.length}
 ];
 function updateMilestones(silent=false) {
  for(const a of ACHIEVEMENTS) if(a.test()&&!state.awards.includes(a.id)){state.awards.push(a.id);if(!silent)toast('Достижение: '+a.name,a.desc,a.art);}
  for(const ch of DATA.chapters) if(ch.targets.every(id=>discovered.has(id))&&!state.chapters.includes(ch.id)){
   state.chapters.push(ch.id);if(!silent)toast('Глава '+ch.n+' завершена',ch.name,'book');
  }
  if(state.tracked&&discovered.has(state.tracked)){if(!silent)toast('Цель достигнута',name(state.tracked),state.tracked);state.tracked=null;}
 }
 function save() {
  try{localStorage.setItem(KEY,JSON.stringify(state));storageAvailable=true;}
  catch{storageAvailable=false;}
  renderSave();
 }
 function renderSave(){const n=$('#save-indicator');n.classList.toggle('save-warning',!storageAvailable);n.innerHTML=ui(storageAvailable?'check':'info')+'<span>'+(storageAvailable?'Сохранено на этом устройстве':'Автосохранение недоступно · экспорт в настройках')+'</span>';}
 function snapshot(){undoStack.push({board:clone(state.board),slots:[...state.slots],mode:state.mode});if(undoStack.length>24)undoStack.shift();}
 function undo(){if(!undoStack.length)return;const s=undoStack.pop();state.board=s.board;state.slots=s.slots;state.mode=s.mode;selectedNodes=[];activeSlot=null;renderAll();save();toast('Стол восстановлен','Все открытия остались в коллекции.');}
 function toast(title,detail='',id=null){
  const node=document.createElement('div');node.className='toast';node.innerHTML=(id?art(id):ui('spark'))+`<div><strong>${esc(title)}</strong>${esc(detail)}</div>`;
  const stack=$('#toasts');while(stack.children.length>=3)stack.firstElementChild.remove();stack.appendChild(node);
  const t=setTimeout(()=>{node.classList.add('out');setTimeout(()=>node.remove(),220);},3900);
  node.addEventListener('click',()=>{clearTimeout(t);node.remove();},{once:true});
 }
 function sound(kind){
  if(!state.settings.sound)return;
  try{
   if(!audioContext||audioContext.state==='closed')audioContext=new (window.AudioContext||window.webkitAudioContext)();
   if(audioContext.state==='suspended')audioContext.resume().catch(()=>{});
   const notes=kind==='discovery'?[523.25,659.25,783.99,1046.5]:kind==='success'?[523.25,659.25]:kind==='fail'?[220,196]:[420];
   notes.forEach((f,i)=>{const o=audioContext.createOscillator(),g=audioContext.createGain(),start=audioContext.currentTime+i*.07;o.type='sine';o.frequency.value=f;g.gain.setValueAtTime(0,start);g.gain.linearRampToValueAtTime(.033,start+.012);g.gain.exponentialRampToValueAtTime(.001,start+.27);o.connect(g);g.connect(audioContext.destination);o.start(start);o.stop(start+.29);o.onended=()=>{o.disconnect();g.disconnect();};});
  }catch{/* Audio is optional; a browser restriction never interrupts play. */}
 }
 function sparkle(){
  if(!state.settings.motion||matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  const lab=$('.lab');for(let i=0;i<14;i++){const p=document.createElement('i');p.className='particle';p.style.left=(43+Math.random()*14)+'%';p.style.top='52%';p.style.setProperty('--dx',((Math.random()-.5)*240)+'px');p.style.setProperty('--dy',(-40-Math.random()*130)+'px');p.style.animationDelay=(Math.random()*.1)+'s';lab.appendChild(p);p.addEventListener('animationend',()=>p.remove(),{once:true});setTimeout(()=>p.remove(),1000);}
 }
 // The resolver uses an unordered pair key, preserving multiplicity (A+A is not A+B).
 // There is exactly one result per pair. Discovering an element and learning a recipe are separate.
 function registerExperiment(a,b){
  if(!hasElement(a)||!hasElement(b)||!discovered.has(a)||!discovered.has(b))return null;
  const key=pairKey(a,b),r=recipesByKey.get(key),repeat=state.experiments.some(h=>h.key===key);
  const fresh=!!r&&!discovered.has(r.r),newRecipe=!!r&&!learned.has(key);
  state.stats.attempts++;
  if(r){
   state.stats.successes++;if(a===b)state.stats.samePair++;
   if(fresh){state.discovered.push(r.r);discovered.add(r.r);state.firstFound[r.r]={recipe:key,time:time()};newest=r.r;}
   if(newRecipe){state.knownRecipes.push(key);learned.add(key);}
  }
  state.experiments.push({a,b,r:r?.r||null,key,time:time(),fresh});
  if(state.experiments.length>MAX_HISTORY)state.experiments.splice(0,state.experiments.length-MAX_HISTORY);
  const outcome={a,b,r:r?.r||null,fresh,newRecipe,repeat,success:!!r};lastOutcome=outcome;
  sound(fresh?'discovery':r?'success':'fail');
  if(fresh){toast('Новое открытие — '+name(r.r),E[r.r].desc,r.r);sparkle();}
  updateMilestones();
  return outcome;
 }
 function selectElement(id){
  if(!hasElement(id)||!discovered.has(id))return;
  if(state.mode==='table'){addBoard(id);return;}
  snapshot();const idx=activeSlot!==null?activeSlot:state.slots[0]===null?0:1;
  state.slots[idx]=id;activeSlot=state.slots[1-idx]===null?1-idx:null;
  sound('tap');renderSlots();renderLibrary();save();
 }
 function mix(){
  if(state.mode==='table'){if(selectedNodes.length===2)combineNodes(selectedNodes[0],selectedNodes[1]);else toast('Нужны два элемента','Выбери два элемента на столе или перетащи один на другой.');return;}
  const[a,b]=state.slots;if(!a||!b)return;
  snapshot();const result=registerExperiment(a,b);if(!result)return;
  if(result.success){state.slots=[null,null];activeSlot=null;}
  renderAll();save();
 }
 function setPair(a,b){if(!discovered.has(a)||!discovered.has(b))return;snapshot();state.mode='crucible';state.slots=[a,b];activeSlot=null;closeModal();renderAll();save();$('#mix-button').scrollIntoView({behavior:state.settings.motion?'smooth':'auto',block:'center'});}
 function continueWith(id){if(!discovered.has(id))return;if(state.mode==='table'){addBoard(id);return;}snapshot();state.slots=[id,null];activeSlot=1;renderAll();save();}
 function switchMode(mode){if(!['crucible','table'].includes(mode)||state.mode===mode)return;snapshot();state.mode=mode;activeSlot=null;selectedNodes=[];renderAll();save();}
 function clearTable(){if(state.mode==='table'?!state.board.length:!state.slots.some(Boolean))return;snapshot();if(state.mode==='table')state.board=[];else state.slots=[null,null];activeSlot=null;selectedNodes=[];renderAll();save();toast('Стол свободен','Коллекция и рецепты сохранены. Очистку можно отменить.');}
 function nextPosition(){const n=state.board.length;return{x:.18+(n%4)*.20,y:.23+(Math.floor(n/4)%3)*.27};}
 function boundedPoint(x,y){const w=$('#workspace'),r=w.getBoundingClientRect(),mx=Math.min(.25,43/Math.max(1,r.width)),my=Math.min(.3,47/Math.max(1,r.height));return{x:limit(x,mx,1-mx),y:limit(y,my,1-my)};}
 function addBoard(id,point=null){
  if(!discovered.has(id))return;if(state.board.length>=MAX_BOARD){toast('На столе уже 40 элементов','Убери лишние копии: открытия из коллекции не исчезнут.');return;}
  snapshot();const pos=point||nextPosition();state.board.push({uid:uid(),id,...boundedPoint(pos.x,pos.y)});sound('tap');renderBoard();save();$('#undo-button').disabled=!undoStack.length;
 }
 function removeNode(id){const n=state.board.find(n=>n.uid===id);if(!n)return;snapshot();state.board=state.board.filter(n=>n.uid!==id);selectedNodes=selectedNodes.filter(x=>x!==id);renderBoard();save();$('#undo-button').disabled=false;}
 function combineNodes(id1,id2,alreadySnapshotted=false){
  if(id1===id2)return;const a=state.board.find(n=>n.uid===id1),b=state.board.find(n=>n.uid===id2);if(!a||!b)return;
  if(!alreadySnapshotted)snapshot();const out=registerExperiment(a.id,b.id);if(!out)return;
  if(out.success){state.board=state.board.filter(n=>n.uid!==id1&&n.uid!==id2);state.board.push({uid:uid(),id:out.r,...boundedPoint((a.x+b.x)/2,(a.y+b.y)/2)});}
  selectedNodes=[];renderAll();save();
 }
 function dropLibrary(id,x,y,targetUid=null){
  const target=state.board.find(n=>n.uid===targetUid);
  if(!target){addBoard(id,{x,y});return;}
  snapshot();const out=registerExperiment(id,target.id);if(!out)return;
  if(out.success){state.board=state.board.filter(n=>n.uid!==target.uid);state.board.push({uid:uid(),id:out.r,...boundedPoint(target.x,target.y)});}
  else if(state.board.length<MAX_BOARD)state.board.push({uid:uid(),id,...boundedPoint(x+.16,y+.08)});
  selectedNodes=[];renderAll();save();
 }
 function toggleFavorite(id){if(!discovered.has(id))return;state.favorites=state.favorites.includes(id)?state.favorites.filter(x=>x!==id):[...state.favorites,id];save();renderLibrary();if(modalKind==='detail'&&$('#modal').dataset.element===id)showDetail(id);}
 function renderLibrary(){
  const q=$('#library-search').value.trim().toLocaleLowerCase('ru'),cat=$('#library-category').value;
  let visible=state.discovered.filter(id=> (cat==='all'||E[id].cat===cat) && (!q||name(id).toLocaleLowerCase('ru').includes(q)||id.includes(q)));
  if(filter==='favorites')visible=visible.filter(id=>state.favorites.includes(id));
  if(filter==='recent')visible=visible.filter(id=>!BASE.includes(id)).slice(-16).reverse();
  else if(sort==='name')visible.sort((a,b)=>name(a).localeCompare(name(b),'ru'));
  else visible.sort((a,b)=>{const ai=BASE.indexOf(a),bi=BASE.indexOf(b);return ai>=0&&bi>=0?ai-bi:ai>=0?-1:bi>=0?1:state.discovered.indexOf(b)-state.discovered.indexOf(a);});
  $('#library-grid').innerHTML=visible.map(id=>{
   const favorite=state.favorites.includes(id),isNew=id===newest,selected=state.mode==='crucible'&&state.slots.includes(id);
   return `<div class="element-card ${selected?'is-selected ':''}${isNew?'has-new':''}"><button class="element-pick" data-add="${id}" aria-label="Добавить: ${esc(name(id))}" title="Нажми, чтобы добавить. Shift + клик — подробнее.">${art(id)}<span class="element-name">${esc(name(id))}</span></button>${isNew?'<span class="new-label">НОВОЕ</span>':''}<button class="card-favorite ${favorite?'is-favorite':''}" data-favorite="${id}" aria-label="${favorite?'Убрать из избранного':'В избранное'}: ${esc(name(id))}" aria-pressed="${favorite}" title="Избранное">${ui('star')}</button><button class="card-detail" data-detail="${id}" aria-label="Об элементе: ${esc(name(id))}" title="Об элементе">${ui('info')}</button></div>`;
  }).join('');
  const empty=$('#library-empty');empty.hidden=visible.length>0;empty.innerHTML=ui(filter==='favorites'?'star':'search')+(filter==='favorites'?'Здесь появятся любимые элементы.<br>Нажми звёздочку на карточке.':filter==='recent'?'Пока здесь тихо.<br>Сделай первое открытие.':'Ничего не найдено.<br>Попробуй другую категорию или название.');
  $('#collection').dataset.initial=String(discovered.size===4);
  $('#collection-count').innerHTML=`${discovered.size} <i>/ ${ids.length}</i>`;
  $('#collection-progress').style.width=(100*discovered.size/ids.length)+'%';
  document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b.dataset.filter===filter));
  $('#sort-button').textContent=sort==='name'?'По дате ↓':'А—Я ↓';$('#sort-button').setAttribute('aria-label',sort==='name'?'Сортировать по дате открытия':'Сортировать по алфавиту');
 }
 function renderSlots(){
  $('#ingredient-slots').innerHTML=state.slots.map((id,i)=>`${i?'<span class="slot-plus" aria-hidden="true">+</span>':''}<div class="ingredient-wrap"><button class="ingredient-slot ${id?'filled':''} ${activeSlot===i?'waiting':''}" data-slot="${i}" aria-label="${i===0?'Первый':'Второй'} ингредиент: ${id?esc(name(id)):'не выбран'}. Нажми, чтобы выбрать.">${id?art(id)+`<span class="element-name">${esc(name(id))}</span>`:`<span class="slot-number">${i+1}</span><span>${activeSlot===i?'Выбери в коллекции':'Добавь элемент'}</span>`}</button>${id?`<button class="slot-remove" data-remove-slot="${i}" aria-label="Убрать ${esc(name(id))}">${ui('close')}</button>`:''}</div>`).join('');
  const full=state.slots.every(Boolean),some=state.slots.some(Boolean);
  $('#mix-button').disabled=!full;
  let caption=full?name(state.slots[0])+' + '+name(state.slots[1]):some?'А что получится вместе с другим элементом?':'Выбери два элемента из коллекции';
  if(full){const key=pairKey(...state.slots);if(learned.has(key))caption+=' · рецепт уже известен';else if(state.experiments.some(h=>h.key===key&&!h.r))caption+=' · уже пробовали';}
  $('#mix-caption').textContent=caption;
  $('#dock-slots').innerHTML=state.slots.map((id,i)=>`${i?'<span class="operator">+</span>':''}<button class="dock-slot ${id?'':'empty'}" data-slot="${i}" aria-label="${i+1}-й ингредиент: ${id?esc(name(id)):'пусто'}">${id?art(id):String(i+1)}</button>`).join('');
  $('.dock-mix').disabled=!full;
  renderDock();
 }
 function renderBoard(){
  if(state.mode==='table')for(const n of state.board)Object.assign(n,boundedPoint(n.x,n.y));
  selectedNodes=selectedNodes.filter(u=>state.board.some(n=>n.uid===u));
  $('#workspace-empty').hidden=state.board.length>0;
  $('#board-nodes').innerHTML=state.board.map(n=>`<div class="board-node ${selectedNodes.includes(n.uid)?'selected':''}" role="button" tabindex="0" data-node="${n.uid}" aria-label="${esc(name(n.id))}. Выбрать для смешивания. Перетаскивание мышью или пальцем." aria-pressed="${selectedNodes.includes(n.uid)}" style="left:${n.x*100}%;top:${n.y*100}%">${art(n.id)}<span class="element-name">${esc(name(n.id))}</span><button class="node-remove" data-remove-node="${n.uid}" aria-label="Убрать ${esc(name(n.id))} со стола">×</button></div>`).join('');
  const nodes=selectedNodes.map(u=>state.board.find(n=>n.uid===u));
  $('#table-selection').innerHTML=nodes.length?`<span>${nodes.map(n=>esc(name(n.id))).join(' + ')}</span><span>${nodes.length===2?'<button data-action="mix">'+ui('spark')+' Соединить</button>':`<button data-duplicate="${nodes[0].uid}">${ui('plus')} Копия</button> <button data-detail="${nodes[0].id}" aria-label="Об элементе">${ui('info')}</button>`}</span>`:`<span>${state.board.length} / ${MAX_BOARD} на столе</span><span>Смешивание — перетаскиванием или в два касания</span>`;
 }
 function renderResult(){
  const area=$('#result-area'),o=lastOutcome;
  if(!o){area.innerHTML=`<div class="result-idle"><span class="idle-mark">${ui('spark')}</span><div><h3>Мир ждёт твоего первого открытия</h3><p>Немного воды, щепотка воображения…<br>А что добавишь ты?</p></div></div>`;return;}
  if(!o.r){area.innerHTML=`<div class="result-card result-fail">${art('question')}<div class="result-copy"><span class="eyebrow">${o.repeat?'ЭТО СОЧЕТАНИЕ УЖЕ ПРОБОВАЛИ':'ЭКСПЕРИМЕНТ ЗАПИСАН'}</span><h3>Пока без превращения</h3><p>Эта пара не образует новый элемент. Ничего не потеряно — попробуй другое сочетание.</p><div class="result-actions"><button data-action="hint">${ui('spark')} Получить подсказку</button></div></div></div>`;return;}
  area.innerHTML=`<div class="result-card ${o.fresh?'new-result':''}">${art(o.r)}<div class="result-copy"><span class="eyebrow">${o.fresh?'НОВОЕ МАЛЕНЬКОЕ ЧУДО':o.newRecipe?'ЕЩЁ ОДИН ПУТЬ К ЗНАКОМОМУ':'ЗНАКОМОЕ ПРЕВРАЩЕНИЕ'}</span><h3>${esc(name(o.r))}</h3><p>${esc(E[o.r].desc)}</p><div class="result-actions"><button data-continue="${o.r}">Продолжить с ним ${ui('arrow')}</button><button data-detail="${o.r}">${ui('book')} В атлас</button></div></div></div>`;
 }
 function renderChapter(){
  const ch=currentChapter();$('#rank-label').textContent=ch?'Глава '+ch.n+' · '+ch.name:'Восемь глав завершены · Мир открыт';
  if(!ch){$('#chapter-card').innerHTML=`<div class="chapter-top"><span class="chapter-number">${ui('check')}</span><span class="eyebrow">ВЕЛИКОЕ ДЕЛАНИЕ</span></div><h3>Это только начало.</h3><p class="chapter-desc">Все восемь глав пройдены. Но в атласе ещё могут оставаться неизвестные пути.</p><button class="chapter-footer" data-action="atlas">Исследовать весь атлас ${ui('arrow')}</button>`;return;}
  const count=ch.targets.filter(id=>discovered.has(id)).length;
  $('#chapter-card').innerHTML=`<div class="chapter-top"><span class="chapter-number">${ch.n}</span><span class="eyebrow">ПУТЬ АЛХИМИКА</span><small>${count} / ${ch.targets.length}</small></div><h3>${esc(ch.name)}</h3><p class="chapter-desc">${esc(ch.desc)}</p><div class="target-list">${ch.targets.map(id=>`<button class="target-row ${discovered.has(id)?'done':''} ${state.tracked===id?'tracked':''}" data-target="${id}" title="${discovered.has(id)?'Открыть в атласе':'Выбрать целью и получить подсказку'}"><span class="check-box">${discovered.has(id)?ui('check'):''}</span>${esc(name(id))}<span>${discovered.has(id)?'В атлас':'Цель →'}</span></button>`).join('')}</div><button class="chapter-footer" data-action="journey">Все восемь глав ${ui('arrow')}</button>`;
 }
 function renderWorld(){
  const d=id=>discovered.has(id),green=d('plant'),sea=d('sea'),mountain=d('mountain'),home=d('house'),star=d('star'),magic=d('magic');
  const stage=magic?'Волшебство':star?'К звёздам':d('computer')?'Изобретения':home?'Первый дом':green?'Пробуждение':sea?'Новые берега':'Зарождение';
  $('#world-stage').textContent=stage;
  const use=(id,x,y,w,h=w)=>`<use href="#art-${id}" x="${x}" y="${y}" width="${w}" height="${h}"/>`;
  $('#world-picture').innerHTML=`<svg viewBox="0 0 260 156" aria-hidden="true"><defs><linearGradient id="worldSky" x2="0" y2="1"><stop stop-color="${star?'#bac9bf':'#e4ead7'}"/><stop offset="1" stop-color="#edf0dc"/></linearGradient></defs><rect x="8" y="8" width="244" height="140" rx="65" fill="url(#worldSky)"/>${star?'<circle cx="71" cy="25" r="1.5" fill="#f8f3d9"/><circle cx="199" cy="27" r="2" fill="#f8f3d9"/>'+use('moon',173,11,42):use('sun',175,18,35)}${d('cloud')?use('cloud',23,13,65)+use('cloud',164,33,62):'<path d="M41 48h24m-17-8h9m133 14h17" fill="none" stroke="#c2d0b4" stroke-width="2" stroke-linecap="round"/>'}<ellipse cx="130" cy="133" rx="83" ry="8" fill="#cbd6b551"/><path d="m39 93 77-32 91 30-17 29-67 15-65-18Z" fill="#acb999"/><path d="m39 93 77-32 91 30-89 31Z" fill="${green?'#93b088':'#c6ceb0'}"/><path d="m39 93 79 29v13l-60-18Z" fill="#a1ab85"/><path d="m118 122 89-31-17 29-72 15Z" fill="#8e9f7a"/>${sea?'<path d="m49 95 74-26 24 9q-34 10-29 17t-25 17Z" fill="#a4c8b7"/><path d="m65 95 27-9m-9 13 20-7" stroke="#d0e1cb" fill="none" stroke-linecap="round"/>':''}${mountain?use('mountain',107,29,66):''}${green?use('tree',155,46,55)+use('plant',49,62,39)+use('tree',80,52,44):use('earth',90,64,47)}${home?use('house',105,67,49):''}${d('bird')?'<path d="M56 29q4-5 8 0 4-5 8 0" fill="none" stroke="#a2b38e" stroke-width="1.5"/>':''}${d('windmill')?use('windmill',172,65,38):''}${d('rocket')?use('rocket',23,32,34):''}${magic?use('magic',204,66,35)+use('crystal',80,90,30):''}<path d="m30 82 3-7 3 7 7 3-7 3-3 7-3-7-7-3Zm194-34 2-5 2 5 5 2-5 2-2 5-2-5-5-2Z" fill="#c2bd8b"/></svg>`;
  $('#world-caption').innerHTML=magic?'Там, где заканчиваются правила,<br>начинается воображение.':home?'Теперь здесь есть куда вернуться.<br>А что будет за следующим холмом?':green?'Первый росток изменил всё.<br>Продолжай наполнять мир жизнью.':sea?'У маленького мира появились берега.<br>Дальше — ещё интереснее.':'Даже большой мир начинается<br>с четырёх маленьких стихий.';
 }
 function renderHistory(){
  const hs=state.experiments.slice(-3).reverse();
  $('#recent-history').innerHTML=hs.length?hs.map(h=>`<button class="mini-experiment" data-repeat="${h.key}" aria-label="Повторить: ${esc(name(h.a))} + ${esc(name(h.b))}">${art(h.a)}<span class="operator">+</span>${art(h.b)}<span class="operator">→</span>${h.r?art(h.r):ui('close')}<span class="experiment-result">${h.r?esc(name(h.r)):'Без реакции'}</span>${h.fresh?'<span class="experiment-dot" title="Первое открытие"></span>':''}</button>`).join(''):'<p class="history-empty">Здесь останутся следы<br>твоих маленьких открытий.<br>Первый опыт уже близко.</p>';
 }
 function renderDock(){const show=state.mode==='crucible'&&!combineVisible&&!$('#modal').open;$('#mobile-dock').hidden=!show;}
 function renderAll(){
  $('#crucible-panel').hidden=state.mode!=='crucible';$('#table-panel').hidden=state.mode!=='table';
  document.body.classList.toggle('no-motion',!state.settings.motion);
  renderLibrary();renderSlots();renderBoard();renderResult();renderChapter();renderWorld();renderHistory();
  $('#crucible-panel').hidden=state.mode!=='crucible';$('#table-panel').hidden=state.mode!=='table';
  document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===state.mode));
  document.querySelectorAll('.sound-toggle').forEach(b=>{b.innerHTML=ui(state.settings.sound?'sound':'mute');b.setAttribute('aria-label',state.settings.sound?'Выключить звуки':'Включить звуки');b.setAttribute('aria-pressed',state.settings.sound);});
  const frontier=new Set(available().map(r=>r.r)).size;
  $('#frontier-count').textContent=frontier?`${frontier} ${plural(frontier,['новое открытие','новых открытия','новых открытий'])} уже рядом`:discovered.size===ids.length?'Все элементы открыты. Ищи новые рецепты!':'Мир ждёт новых сочетаний';
  $('#recipe-count').textContent=`${learned.size} / ${RECIPES.length} рецептов`;
  $('#achievement-count').textContent=`${ACHIEVEMENTS.filter(a=>a.test()).length} / ${ACHIEVEMENTS.length} достижений`;
  $('#undo-button').disabled=undoStack.length===0;
  renderSave();renderDock();
 }
 function openModal(kind,title,html,eyebrow='МАСТЕРСКАЯ МИРОВ'){
  const m=$('#modal');if(!m.open)previousFocus=document.activeElement;
  modalKind=kind;$('#modal-title').textContent=title;$('#modal-eyebrow').textContent=eyebrow;$('#modal-body').innerHTML=html;$('#modal-body').scrollTop=0;
  if(!m.open)m.showModal();renderDock();
 }
 function closeModal(){const m=$('#modal');if(m.open)m.close();}
 function catOptions(current='all'){return '<option value="all">Все категории</option>'+Object.entries(C).map(([id,c])=>`<option value="${id}" ${id===current?'selected':''}>${esc(c.name)}</option>`).join('');}
 function showAtlas(){
  openModal('atlas','Атлас открытий',`<p class="modal-intro">Каждый элемент — маленькая история. Неизвестное остаётся тайной, пока ты не создашь его сам. Другие пути к знакомым элементам тоже считаются открытиями рецептов.</p><div class="atlas-toolbar"><label class="search-field">${ui('search')}<input id="atlas-search" type="search" value="${esc(atlas.q)}" placeholder="Название открытого элемента…" aria-label="Поиск в атласе"></label><select id="atlas-category" aria-label="Категория атласа">${catOptions(atlas.cat)}</select><label class="check-label"><input id="atlas-unknown" type="checkbox" ${atlas.unknown?'checked':''}>Показывать неизвестное</label></div><div id="atlas-summary" class="atlas-summary"></div><div id="atlas-grid" class="atlas-grid"></div>`,'КНИГА МАЛЕНЬКИХ ЧУДЕС');
  renderAtlasGrid();
 }
 function renderAtlasGrid(){
  const q=atlas.q.trim().toLocaleLowerCase('ru');let list=ids.filter(id=>(atlas.cat==='all'||E[id].cat===atlas.cat)&&(atlas.unknown||discovered.has(id))&&(!q||discovered.has(id)&&(name(id).toLocaleLowerCase('ru').includes(q)||id.includes(q))));
  list.sort((a,b)=>discovered.has(b)-discovered.has(a)||E[a].depth-E[b].depth||name(a).localeCompare(name(b),'ru'));
  $('#atlas-summary').textContent=`${discovered.size} из ${ids.length} элементов · ${learned.size} из ${RECIPES.length} рецептов · показано ${list.length}`;
  $('#atlas-grid').innerHTML=list.length?list.map(id=>discovered.has(id)?`<button class="atlas-entry" data-detail="${id}" aria-label="${esc(name(id))}">${art(id)}<span class="element-name">${esc(name(id))}</span>${E[id].rarity==='legendary'?'<span class="rarity-dot" title="Легендарное открытие"></span>':''}</button>`:`<div class="atlas-entry locked" aria-label="Неизвестный элемент категории ${esc(C[E[id].cat].name)}">${ui('lock')}<span class="element-name">Неизвестное</span></div>`).join(''):'<p class="empty-state">Ничего не найдено.</p>';
 }
 function recipeItem(id){return discovered.has(id)?`<button class="recipe-item" data-detail="${id}">${art(id)}<span>${esc(name(id))}</span></button>`:`<span class="recipe-item">${ui('lock')} Неизвестно</span>`;}
 function tree(id,depth=0,seen=new Set()){
  if(!discovered.has(id))return `<div class="tree-label">${ui('lock')} Неизвестный элемент</div>`;
  const label=`<button class="tree-label" data-detail="${id}">${art(id)}${esc(name(id))}</button>`;
  if(depth>=4||seen.has(id)||BASE.includes(id))return label;
  const r=recipesByKey.get(state.firstFound[id]?.recipe);if(!r)return label;
  const next=new Set(seen);next.add(id);
  return label+`<div class="genealogy">${tree(r.a,depth+1,next)}${tree(r.b,depth+1,next)}</div>`;
 }
 function showDetail(id){
  if(!discovered.has(id))return;const el=E[id],rs=recipesFor.get(id)||[],known=rs.filter(r=>learned.has(r.key)),isBase=BASE.includes(id);
  $('#modal').dataset.element=id;
  const recipesHTML=isBase?'<p>Одна из четырёх изначальных стихий. Она всегда есть в коллекции и никогда не заканчивается.</p>':known.length?known.map(r=>`<div class="recipe-row">${recipeItem(r.a)}<span class="operator">+</span>${recipeItem(r.b)}<span class="operator">→</span>${recipeItem(id)}<button data-repeat="${r.key}" title="Повторить в тигле">В тигель ${ui('arrow')}</button></div>`).join(''):'<p>Элемент уже есть в коллекции, но его рецепт ещё не записан. Такое бывает при переносе старого сохранения. Создай его заново, чтобы заполнить страницу.</p>';
  openModal('detail',el.name,`<button class="back-link" data-action="atlas">← Вернуться в атлас</button><div class="detail-hero"><div class="detail-image">${art(id)}</div><div><div class="detail-tags"><span class="badge">${esc(C[el.cat].name)}</span><span class="badge">${isBase?'Изначальная стихия':'Глубина открытия: '+el.depth}</span>${el.rarity==='legendary'?'<span class="badge gold">Легендарное</span>':''}${el.terminal?'<span class="badge">Финальный элемент</span>':''}</div><p>${esc(el.desc)}</p><div class="button-row"><button class="primary-button" data-use="${id}">${ui('plus')} Добавить в мастерскую</button><button class="secondary-button" data-favorite="${id}" aria-pressed="${state.favorites.includes(id)}">${ui('star')} ${state.favorites.includes(id)?'В избранном':'В избранное'}</button></div></div></div><section class="detail-section"><h3>${isBase?'Всё начинается здесь':'Проверенные превращения'}</h3>${recipesHTML}${!isBase&&rs.length>known.length?`<p>${rs.length-known.length} ${plural(rs.length-known.length,['неизвестный способ','неизвестных способа','неизвестных способов'])} получить этот элемент. Попробуй другие сочетания.</p>`:''}${el.terminal?'<p style="margin-top:12px">Это финальная находка: в текущей коллекции она не участвует в дальнейших рецептах. Её место — в атласе твоих открытий.</p>':''}</section>${!isBase&&state.firstFound[id]?`<section class="detail-section"><h3>Как родилось открытие</h3><p>Твой первый путь к элементу. Показаны до четырёх поколений ингредиентов.</p><div class="genealogy">${tree(id)}</div></section>`:''}`,'СТРАНИЦА АТЛАСА');
 }
 function showJourney(){
  openModal('journey','Путь алхимика',`<p class="modal-intro">Восемь глав, а не восемь замков. Открывай элементы в любом порядке — главы лишь подсказывают направление. Нажми на ещё не открытый элемент, чтобы выбрать его целью и найти следующий шаг.</p><div class="modal-statline"><span><strong>${completeChapters()} / 8</strong> глав завершено</span><span><strong>${discovered.size}</strong> элементов в твоём мире</span></div><div class="journey-map">${DATA.chapters.map(ch=>{
   const count=ch.targets.filter(id=>discovered.has(id)).length,done=count===ch.targets.length;
   return `<section class="journey-chapter ${done?'complete':''}"><div class="journey-progress"><span>ГЛАВА ${ch.n}</span><span>${done?ui('check'):count+' / '+ch.targets.length}</span></div><h3>${esc(ch.name)}</h3><p>${esc(ch.desc)}</p><div class="journey-targets">${ch.targets.map(id=>`<button class="journey-target ${discovered.has(id)?'done':''} ${state.tracked===id?'tracked':''}" data-target="${id}" title="${discovered.has(id)?'Открыто: ':'Выбрать целью: '}${esc(name(id))}">${art(id)}<span>${esc(name(id))}</span>${discovered.has(id)?ui('check'):''}</button>`).join('')}</div></section>`;
  }).join('')}</div>`,'ОТ ПЕРВОЙ КАПЛИ ДО ЦЕЛОЙ ВСЕЛЕННОЙ');
 }
 function showAchievements(){
  openModal('achievements','Маленькие большие победы',`<p class="modal-intro">Не соревнование и не список обязательств. Просто памятные моменты твоего путешествия. Никаких наград, закрывающих рецепты: всё доступно с самого начала.</p><div class="modal-statline"><span><strong>${ACHIEVEMENTS.filter(a=>a.test()).length} / ${ACHIEVEMENTS.length}</strong> достижений</span></div><div class="achievement-grid">${ACHIEVEMENTS.map(a=>`<section class="achievement-card ${a.test()?'earned':''}">${art(a.art)}<strong>${esc(a.name)}</strong><p>${esc(a.desc)}</p><span class="achievement-status">${a.test()?'Открыто':'Впереди'}</span></section>`).join('')}</div>`,'ТО, ЧТО ХОЧЕТСЯ ЗАПОМНИТЬ');
 }
 function showJournal(){
  openModal('journal','Журнал опытов',`<p class="modal-intro">Последние ${MAX_HISTORY} экспериментов. Ничего не пропадает даром: неудачная пара тоже становится знанием. Нажми на формулу, чтобы повторить её в тигле.</p><div class="modal-statline"><span><strong>${state.stats.attempts}</strong> опытов</span><span><strong>${state.stats.successes}</strong> удачных смешиваний</span><span><strong>${learned.size}</strong> разных рецептов</span></div><label class="check-label" style="margin-bottom:14px"><input id="journal-success" type="checkbox" ${journalOnlySuccess?'checked':''}>Только успешные превращения</label><div id="journal-list"></div>`,'ЗАМЕТКИ НА ПОЛЯХ');renderJournalList();
 }
 function renderJournalList(){const list=state.experiments.slice().reverse().filter(h=>!journalOnlySuccess||h.r);$('#journal-list').innerHTML=list.length?list.map((h,i)=>`<div class="journal-row"><span class="experiment-status">${h.fresh?'✦':String(i+1).padStart(2,'0')}</span><button class="journal-combination" data-repeat="${h.key}"><span class="recipe-item">${art(h.a)}${esc(name(h.a))}</span><span>+</span><span class="recipe-item">${art(h.b)}${esc(name(h.b))}</span></button><span class="journal-result">${h.r?art(h.r)+esc(name(h.r)):'Пока без реакции'}</span></div>`).join(''):'<p class="empty-state">Здесь ещё нет записей. Самое время для эксперимента.</p>';}
 // Walk dependencies, not locked recipes selected at random. The primary graph is reachable.
 function nextStep(target,visited=new Set()){
  if(discovered.has(target)||visited.has(target))return null;
  const seen=new Set(visited);seen.add(target);const rs=recipesFor.get(target)||[];
  const direct=rs.find(r=>discovered.has(r.a)&&discovered.has(r.b));if(direct)return direct;
  for(const r of [...rs].sort((a,b)=>Number(b.primary)-Number(a.primary)))for(const ingredient of[r.a,r.b])if(!discovered.has(ingredient)){const sub=nextStep(ingredient,seen);if(sub)return sub;}
  return null;
 }
 function chooseHint(other=false){
  if(!other&&hint&&!discovered.has(hint.recipe.r)&&discovered.has(hint.recipe.a)&&discovered.has(hint.recipe.b))return;
  const previous=hint?.recipe.key;
  let recipe=null,target=state.tracked;
  if(!other){if(target)recipe=nextStep(target);if(!recipe){const ch=currentChapter();target=ch?.targets.find(id=>!discovered.has(id));if(target)recipe=nextStep(target);}}
  if(!recipe){const a=available();recipe=a.find(r=>r.key!==previous)||a[0];if(other)target=null;}
  hint=recipe?{recipe,stage:1,target}:null;
 }
 function showHint(other=false){
  chooseHint(other);
  if(!hint){openModal('hint','Весь мир уже в коллекции',`<div class="hint-card"><div class="hint-emblem">${ui('trophy')}</div><h3>Все ${ids.length} элементов открыты!</h3><p>Осталось ${RECIPES.length-learned.size} непроверенных рецептов. У знакомых вещей бывают разные пути рождения.</p><div class="button-row"><button class="primary-button" data-action="unlearned-hint">${ui('spark')} Найти другой путь</button><button class="secondary-button" data-action="atlas">${ui('book')} Открыть атлас</button></div></div>`,'ЛЮБОПЫТСТВО НЕ ЗАКАНЧИВАЕТСЯ');return;}
  const r=hint.recipe,stage=hint.stage;
  const clues={elements:'Иногда стихии рассказывают совсем другую историю, когда оказываются рядом.',weather:'Посмотри на небо. Даже у самой обычной погоды бывает неожиданное начало.',nature:'Миру нужны новые очертания: берега, долины и что-нибудь за горизонтом.',materials:'Привычные вещи меняются, если дать им подходящего соседа.',life:'Жизни достаточно маленького шанса, чтобы придумать что-то удивительное.',food:'Следующее открытие могло бы оказаться на уютной кухне.',civilization:'Большие города начинаются с очень небольших человеческих идей.',ideas:'Не всё в этом мире можно потрогать. Но многое можно придумать.',cosmos:'Иногда стоит поднять взгляд повыше: ответ ждёт за облаками.',magic:'Добавь к знакомому немного невозможного.',technology:'У каждого изобретения когда-то было всего два простых начала.'};
  const content=stage===1?`<h3>Доверься любопытству</h3><p>${clues[E[r.r].cat]}<br>Ищи новую находку в категории <strong>«${esc(C[E[r.r].cat].name)}»</strong>.</p>`:stage===2?`<h3>Один ингредиент уже найден</h3><div class="hint-ingredients"><div>${art(r.a)}${esc(name(r.a))}</div><span>+</span><div><span class="hint-emblem" style="margin:0;width:75px;height:75px">?</span>Что добавить?</div></div><p>Второй ингредиент уже есть в твоей коллекции.${r.a===r.b?' Иногда лучший сосед — точная копия.':''}</p>`:`<h3>Пора проверить догадку</h3><div class="hint-ingredients"><div>${art(r.a)}${esc(name(r.a))}</div><span>+</span><div>${art(r.b)}${esc(name(r.b))}</div></div><p>Это сочетание откроет ${discovered.has(r.r)?'новый рецепт':'новый элемент'}. Результат увидишь после смешивания.</p>`;
  openModal('hint','Немного вдохновения',`<p class="modal-intro">${hint.target?'На пути к цели «'+esc(name(hint.target))+'». Иногда сначала нужно сделать промежуточное открытие.':'Подсказка выбирает сочетание из уже открытых элементов.'} Без ожидания и платы.</p><div class="hint-card"><div class="hint-stages">${[1,2,3].map(i=>`<span class="${i<=stage?'on':''}"></span>`).join('')}</div>${stage===1?`<div class="hint-emblem">${ui('spark')}</div>`:''}${content}<div class="button-row">${stage<3?`<button class="primary-button" data-action="next-hint">${stage===1?'Показать один ингредиент':'Показать сочетание'} ${ui('arrow')}</button>`:`<button class="primary-button" data-hint-pair="${r.key}">${ui('flask')} Положить в тигель</button>`}<button class="secondary-button" data-action="other-hint">Другая идея</button></div></div>`,'ИСКРА ДЛЯ СЛЕДУЮЩЕГО ОТКРЫТИЯ');
 }
 function targetElement(id){if(!hasElement(id))return;if(discovered.has(id)){showDetail(id);return;}state.tracked=id;hint=null;save();renderChapter();showHint();}
 function showSettings(){
  openModal('settings','Настройки мастерской',`<section class="settings-section"><h3>Настроение</h3><div class="setting-row"><div><strong>Звуки превращений</strong><small>Тихие синтезированные ноты. Без фоновой музыки.</small></div><button class="toggle" role="switch" aria-label="Звуки превращений" aria-checked="${state.settings.sound}" data-action="settings-sound"></button></div><div class="setting-row"><div><strong>Анимации и искры</strong><small>Системное уменьшение движения имеет приоритет.</small></div><button class="toggle" role="switch" aria-label="Анимации и искры" aria-checked="${state.settings.motion}" data-action="motion"></button></div></section><section class="settings-section"><h3>Твой мир — с собой</h3><p>${storageAvailable?'Открытия автоматически сохраняются в этом браузере.':'Браузер запретил локальное сохранение. Экспортируй прогресс, прежде чем закрывать игру.'} Здесь нет аккаунта и облачной синхронизации. Для переноса на другое устройство или резервной копии сохрани JSON-файл.</p><div class="button-row"><button class="primary-button" data-action="export">${ui('download')} Экспорт прогресса</button><button class="secondary-button" data-action="import">${ui('upload')} Импорт прогресса</button></div><p>Очистка данных браузера, приватное окно или открытие файла из другого места могут отделить тебя от старого сохранения. Резервная копия надёжнее.</p></section><section class="settings-section"><h3>Чистый лист</h3><p>Начать заново — значит удалить все открытия, любимые элементы и журнал именно этой мастерской. Для обычной уборки используй значок корзины над столом: коллекция останется.</p><button class="danger-button" data-action="reset-confirm">Начать новую игру…</button></section><section><h3>Сделано для любопытства</h3><p class="modal-intro" style="margin-top:10px">${ids.length} элементов · ${RECIPES.length} рецептов · 11 категорий · 8 глав · 16 достижений.<br>Все иллюстрации и данные встроены в этот HTML. Для самой игры интернет не нужен.</p><p class="illustration-credits">Версия 1.0 · Самостоятельная переработка классической алхимической песочницы.<br>Рецепты — игровая условность, не инструкции для реальных опытов.</p></section>`,'ПУСТЬ ЗДЕСЬ БУДЕТ УЮТНО');
 }
 function exportProgress(){
  const envelope={app:APP,version:1,exportedAt:new Date().toISOString(),state};
  const blob=new Blob([JSON.stringify(envelope,null,2)],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download='alchemy-progress-'+new Date().toISOString().slice(0,10)+'.json';a.hidden=true;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);toast('Резервная копия подготовлена','JSON-файл можно импортировать на другом устройстве.');
 }
 function resetConfirm(){openModal('reset','Начать всё сначала?',`<div class="hint-card"><div class="hint-emblem">${ui('flask')}</div><h3>Этот мир уже хранит ${discovered.size} ${plural(discovered.size,['элемент','элемента','элементов'])}.</h3><p>Новая игра удалит его из локального сохранения. Сначала можно сделать резервную копию — или просто закрыть это окно.</p><div class="button-row"><button class="secondary-button" data-action="export">${ui('download')} Сохранить копию</button><button class="danger-button" data-action="reset-now">Да, начать с четырёх стихий</button></div></div>`,'НОВОЕ НАЧАЛО');}
 function showHelp(){
  openModal('help','Немного магии. Никакой спешки.',`<p class="modal-intro">У тебя есть вода, земля, огонь и воздух. Соединяй по два элемента, открывай новые и собирай собственный мир. Ингредиенты не заканчиваются, а время не ограничено.</p><div class="help-grid"><section class="help-step">${art('water')}<h3>1. Выбери две вещи</h3><p>Нажми на два элемента в коллекции. Они попадут в тигель. Затем нажми «Соединить». Можно выбрать один и тот же элемент дважды.</p></section><section class="help-step">${art('life')}<h3>2. Продолжай открытие</h3><p>Новый элемент навсегда появится в коллекции. Кнопка «Продолжить с ним» сразу подставит его в следующий опыт. Неудачная пара ничего не расходует.</p></section><section class="help-step">${art('tool')}<h3>3. Освободи стол</h3><p>В режиме «Свободный стол» добавляй копии элементов и перетаскивай одну на другую. На телефоне можно просто выбрать две копии касаниями и нажать «Соединить».</p></section><section class="help-step">${art('book')}<h3>4. Следуй любопытству</h3><p>Атлас хранит описания и проверенные рецепты. Восемь глав предлагают цели, а «Нужна искра?» даёт подсказку в три шага. Финальные элементы отмечены в атласе.</p></section></div><div class="key-guide"><span><kbd>Enter</kbd> Смешать в тигле</span><span><kbd>1–4</kbd> Базовые стихии</span><span><kbd>/</kbd> Поиск</span><span><kbd>Shift + клик</kbd> Описание</span><span><kbd>Ctrl + Z</kbd> Вернуть стол</span><span><kbd>Esc</kbd> Закрыть окно</span></div><div class="notice">Корзина очищает только рабочий стол. Отмена возвращает положение элементов, но не отменяет открытия. Звёздочка на карточке добавляет элемент в избранное. Открытия сохраняются в браузере; в настройках есть экспорт и импорт JSON.<br><br><strong>Рецепты — игровая условность, не инструкции для реальных опытов.</strong></div>`,'ДОБРО ПОЖАЛОВАТЬ В МАСТЕРСКУЮ');
 }
 function act(action){
  switch(action){
   case'home':closeModal();$('.lab').scrollIntoView({block:'start',behavior:state.settings.motion?'smooth':'auto'});break;
   case'atlas':showAtlas();break;case'journey':showJourney();break;case'achievements':showAchievements();break;case'journal':showJournal();break;
   case'settings':showSettings();break;case'help':showHelp();break;case'close-modal':closeModal();break;
   case'mix':mix();break;case'undo':undo();break;case'clear':clearTable();break;
   case'sort':sort=sort==='name'?'discovery':'name';renderLibrary();break;
   case'sound':case'settings-sound':state.settings.sound=!state.settings.sound;sound('tap');save();renderAll();if(action==='settings-sound')showSettings();break;
   case'motion':state.settings.motion=!state.settings.motion;save();renderAll();showSettings();break;
   case'hint':hint=null;state.stats.hints++;save();showHint();break;
   case'next-hint':if(hint)hint.stage=Math.min(3,hint.stage+1);showHint();break;
   case'other-hint':state.tracked=null;showHint(true);save();renderChapter();break;
   case'unlearned-hint':{const r=RECIPES.find(r=>discovered.has(r.a)&&discovered.has(r.b)&&!learned.has(r.key));if(r){hint={recipe:r,stage:3,target:null};const a=r.a,b=r.b;openModal('hint','Другой путь к знакомому',`<div class="hint-card"><h3>У каждой вещи бывает другая история</h3><div class="hint-ingredients"><div>${art(a)}${esc(name(a))}</div><span>+</span><div>${art(b)}${esc(name(b))}</div></div><p>Этот рецепт ещё не записан в атласе.</p><div class="button-row"><button class="primary-button" data-hint-pair="${r.key}">Положить в тигель ${ui('arrow')}</button></div></div>`);}else toast('Великое дело завершено','Все элементы и все рецепты уже открыты.','philosopher');break;}
   case'export':exportProgress();break;case'import':$('#import-file').value='';$('#import-file').click();break;
   case'reset-confirm':resetConfirm();break;
   case'reset-now':state=freshState();syncSets();lastOutcome=null;hint=null;undoStack=[];selectedNodes=[];activeSlot=null;newest=null;filter='all';sort='discovery';$('#library-search').value='';$('#library-category').value='all';closeModal();renderAll();save();toast('Новая история начинается','Вода, земля, огонь и воздух снова ждут тебя.','earth');break;
   case'import-confirm':if(importedState){state=importedState;importedState=null;syncSets();updateMilestones(true);undoStack=[];lastOutcome=null;hint=null;newest=null;selectedNodes=[];activeSlot=null;filter='all';$('#library-search').value='';$('#library-category').value='all';closeModal();renderAll();save();toast('Мир вернулся в мастерскую',`${discovered.size} элементов и ${learned.size} рецептов восстановлены.`,'book');}break;
  }
 }
 // Delegation keeps listener count constant as the collection and atlas grow.
 document.addEventListener('click',e=>{
  if(time()<suppressClickUntil){e.preventDefault();return;}
  const el=e.target.closest('button,[data-action],.board-node');if(!el)return;
  if(el.dataset.action){e.preventDefault();act(el.dataset.action);return;}
  if(el.dataset.add){e.shiftKey?showDetail(el.dataset.add):selectElement(el.dataset.add);return;}
  if(el.dataset.detail){showDetail(el.dataset.detail);return;}
  if(el.dataset.favorite){toggleFavorite(el.dataset.favorite);return;}
  if(el.dataset.filter){filter=el.dataset.filter;renderLibrary();return;}
  if(el.dataset.mode){switchMode(el.dataset.mode);return;}
  if(el.dataset.slot!==undefined){activeSlot=Number(el.dataset.slot);renderSlots();if(matchMedia('(max-width: 800px)').matches)$('#collection').scrollIntoView({behavior:state.settings.motion?'smooth':'auto',block:'start'});return;}
  if(el.dataset.removeSlot!==undefined){snapshot();state.slots[Number(el.dataset.removeSlot)]=null;activeSlot=Number(el.dataset.removeSlot);renderAll();save();return;}
  if(el.dataset.continue){continueWith(el.dataset.continue);return;}
  if(el.dataset.target){targetElement(el.dataset.target);return;}
  if(el.dataset.use){const id=el.dataset.use;closeModal();selectElement(id);return;}
  if(el.dataset.repeat||el.dataset.hintPair){const key=el.dataset.repeat||el.dataset.hintPair,r=recipesByKey.get(key),h=state.experiments.find(x=>x.key===key);if(r)setPair(r.a,r.b);else if(h)setPair(h.a,h.b);return;}
  if(el.dataset.removeNode){removeNode(el.dataset.removeNode);return;}
  if(el.dataset.duplicate){const n=state.board.find(n=>n.uid===el.dataset.duplicate);if(n)addBoard(n.id,{x:n.x+.16,y:n.y+.12});return;}
  if(el.dataset.node){const id=el.dataset.node;if(selectedNodes.includes(id))selectedNodes=selectedNodes.filter(x=>x!==id);else selectedNodes=[...selectedNodes.slice(-1),id];renderBoard();}
 });
 document.addEventListener('input',e=>{
  if(e.target.id==='library-search')renderLibrary();
  if(e.target.id==='atlas-search'){atlas.q=e.target.value;renderAtlasGrid();}
 });
 document.addEventListener('change',e=>{
  switch(e.target.id){
   case'library-category':renderLibrary();break;
   case'atlas-category':atlas.cat=e.target.value;renderAtlasGrid();break;
   case'atlas-unknown':atlas.unknown=e.target.checked;renderAtlasGrid();break;
   case'journal-success':journalOnlySuccess=e.target.checked;renderJournalList();break;
  }
 });
 $('#import-file').addEventListener('change',async e=>{
  const file=e.target.files?.[0];if(!file)return;
  try{
   if(file.size>1024*1024)throw Error('Файл слишком большой: нужен JSON прогресса размером до 1 МБ.');
   const data=JSON.parse(await file.text());if(data.app!==APP||data.version!==1)throw Error('Это не сохранение «Алхимии · Мастерской миров» версии 1.');
   const incoming=sanitize(data.state,true);importedState=incoming;
   openModal('import','Вернуть сохранённый мир?',`<div class="hint-card"><div class="hint-emblem">${ui('upload')}</div><h3>${incoming.discovered.length} элементов · ${incoming.knownRecipes.length} рецептов</h3><p>Импорт заменит текущий прогресс, а не объединит коллекции. В этой мастерской сейчас ${discovered.size} элементов. Сначала можно экспортировать текущий мир.</p><div class="button-row"><button class="secondary-button" data-action="export">Сохранить текущий мир</button><button class="primary-button" data-action="import-confirm">Заменить прогресс</button></div></div>`,'ПРОДОЛЖЕНИЕ ТВОЕЙ ИСТОРИИ');
  }catch(error){importedState=null;toast('Не удалось открыть сохранение',error instanceof SyntaxError?'Файл не является корректным JSON. Текущий прогресс не изменён.':error.message);}
 });
 $('#modal').addEventListener('close',()=>{modalKind=null;renderDock();if(previousFocus?.isConnected)previousFocus.focus({preventScroll:true});});
 $('#modal').addEventListener('click',e=>{if(e.target===$('#modal')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)closeModal();}});
 document.addEventListener('keydown',e=>{
  const editable=e.target.matches('input,textarea,select,[contenteditable="true"]');
  if($('#modal').open)return;
  if(e.key==='/'&&!editable){e.preventDefault();$('#library-search').focus();return;}
  if(editable)return;
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();undo();return;}
  if(e.key==='Escape'){selectedNodes=[];activeSlot=null;renderBoard();renderSlots();return;}
  if(e.key==='Delete'&&state.mode==='table'&&selectedNodes.length){e.preventDefault();snapshot();state.board=state.board.filter(n=>!selectedNodes.includes(n.uid));selectedNodes=[];renderAll();save();return;}
  if((e.key==='Enter'||e.key===' ')&&e.target.matches('.board-node')){e.preventDefault();e.target.click();return;}
  if(e.key==='Enter'&&!e.target.closest('button,a')){e.preventDefault();mix();return;}
  if(/^[1-4]$/.test(e.key)&&!e.ctrlKey&&!e.altKey&&!e.metaKey){selectElement(BASE[Number(e.key)-1]);}
 });
 // Pointer dragging on the table works with mouse, pen and touch.
 // Library touch gestures remain native scrolling; a simple tap is the mobile primary interaction.
 function clearDropMarks(){document.querySelectorAll('.drop-target,.slot-drop').forEach(n=>n.classList.remove('drop-target','slot-drop'));}
 function pointWithin(node,x,y){const r=node.getBoundingClientRect();return x>=r.left&&x<=r.right&&y>=r.top&&y<=r.bottom;}
 function nodeAt(x,y,except=null){
  let best=null,dist=1e9;
  for(const n of document.querySelectorAll('.board-node')){if(n.dataset.node===except)continue;const r=n.getBoundingClientRect(),d=Math.hypot(x-r.left-r.width/2,y-r.top-r.height/2);if(d<48&&d<dist){best=n;dist=d;}}
  return best;
 }
 document.addEventListener('pointerdown',e=>{
  if(e.button!==0||drag||$('#modal').open)return;
  const node=e.target.closest('.board-node'),pick=e.target.closest('[data-add]');
  if(node&&!e.target.closest('.node-remove')){
   const n=state.board.find(n=>n.uid===node.dataset.node);if(!n)return;
   drag={kind:'node',pointer:e.pointerId,uid:n.uid,id:n.id,x:e.clientX,y:e.clientY,old:{x:n.x,y:n.y},moved:false,node};
   node.setPointerCapture?.(e.pointerId);
  }else if(pick&&e.pointerType!=='touch')drag={kind:'library',pointer:e.pointerId,id:pick.dataset.add,x:e.clientX,y:e.clientY,moved:false};
 });
 document.addEventListener('pointermove',e=>{
  if(!drag||drag.pointer!==e.pointerId)return;
  const d=drag;
  if(!d.moved&&Math.hypot(e.clientX-d.x,e.clientY-d.y)<6)return;
  if(!d.moved){d.moved=true;if(d.kind==='node'){snapshot();d.node.classList.add('dragging');}else{d.ghost=document.createElement('div');d.ghost.className='drag-ghost';d.ghost.innerHTML=art(d.id);document.body.appendChild(d.ghost);}}
  e.preventDefault();clearDropMarks();
  if(d.kind==='library'){
   d.ghost.style.left=e.clientX+'px';d.ghost.style.top=e.clientY+'px';
   if(state.mode==='crucible'){const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-slot]');if(target)target.classList.add('slot-drop');}
   else if(pointWithin($('#workspace'),e.clientX,e.clientY)){const target=nodeAt(e.clientX,e.clientY);if(target)target.classList.add('drop-target');}
  }else{
   const box=$('#workspace').getBoundingClientRect(),pos=boundedPoint((e.clientX-box.left)/box.width,(e.clientY-box.top)/box.height),n=state.board.find(n=>n.uid===d.uid);
   if(n){n.x=pos.x;n.y=pos.y;d.node.style.left=(100*n.x)+'%';d.node.style.top=(100*n.y)+'%';}
   const target=nodeAt(e.clientX,e.clientY,d.uid);if(target)target.classList.add('drop-target');
  }
 },{passive:false});
 function finishDrag(e,cancel=false){
  if(!drag||drag.pointer!==e.pointerId)return;const d=drag;drag=null;clearDropMarks();d.ghost?.remove();
  if(d.kind==='node'){d.node.classList.remove('dragging');try{d.node.releasePointerCapture?.(e.pointerId);}catch{}}
  if(!d.moved)return;suppressClickUntil=time()+350;
  if(cancel){if(d.kind==='node'){const n=state.board.find(n=>n.uid===d.uid);if(n){n.x=d.old.x;n.y=d.old.y;}undoStack.pop();renderBoard();}return;}
  if(d.kind==='library'){
   if(state.mode==='crucible'){
    const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-slot]');
    if(target){activeSlot=Number(target.dataset.slot);selectElement(d.id);}
   }else if(pointWithin($('#workspace'),e.clientX,e.clientY)){
    const box=$('#workspace').getBoundingClientRect(),target=nodeAt(e.clientX,e.clientY);
    dropLibrary(d.id,(e.clientX-box.left)/box.width,(e.clientY-box.top)/box.height,target?.dataset.node);
   }
  }else{
   const target=nodeAt(e.clientX,e.clientY,d.uid);if(target)combineNodes(d.uid,target.dataset.node,true);else{renderBoard();save();$('#undo-button').disabled=false;}
  }
 }
 document.addEventListener('pointerup',e=>finishDrag(e));
 document.addEventListener('pointercancel',e=>finishDrag(e,true));
 document.addEventListener('dragstart',e=>{if(e.target.closest('.element-pick,.board-node'))e.preventDefault();});
 window.addEventListener('blur',()=>{if(drag)finishDrag({pointerId:drag.pointer},true);});
 let resizeFrame=0;
 window.addEventListener('resize',()=>{if(state.mode!=='table')return;if(drag)finishDrag({pointerId:drag.pointer},true);cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(()=>{renderBoard();save();});});
 window.addEventListener('pagehide',()=>{save();if(audioContext&&audioContext.state!=='closed')audioContext.close().catch(()=>{});});
 document.addEventListener('visibilitychange',()=>{if(document.hidden)save();});
 if('IntersectionObserver'in window){const observer=new IntersectionObserver(entries=>{combineVisible=entries[0].isIntersecting&&entries[0].intersectionRatio>=.95;renderDock();},{threshold:[0,.95,1]});observer.observe($('#mix-button'));}
 $('#library-category').innerHTML=catOptions();$('#atlas-total').textContent=ids.length+' элемента';
 updateMilestones(true);renderAll();
 if(pendingNotice)setTimeout(()=>toast('О сохранении',pendingNotice),600);
 // Read-only inspection and a small deterministic adapter for local automated smoke tests.
 Object.defineProperty(window,'Alchemy',{value:Object.freeze({
  data:DATA,getState:()=>clone(state),resolve:(a,b)=>recipesByKey.get(pairKey(a,b))?.r||null,
  validate:()=>{const reach=new Set(BASE);let changed=true;while(changed){changed=false;for(const r of RECIPES)if(reach.has(r.a)&&reach.has(r.b)&&!reach.has(r.r)){reach.add(r.r);changed=true;}}return {elements:ids.length,recipes:RECIPES.length,uniquePairs:recipesByKey.size,reachable:reach.size};}
 }),writable:false});
})();
