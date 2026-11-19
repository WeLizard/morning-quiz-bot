/* Farm performance debugger (docs/FARM_PERF_DEBUG.md). Loaded by app.js only with ?debug=perf or localStorage
   qw-farm-perf=1; players never download it. It shows:
     - the cost of a scene frame and the drawn fps, split by layer and object type (scene_profiler.js wraps FarmScene);
     - the scene counters (objects, cache repaints) and the costliest objects;
     - main-thread long tasks and long animation frames with the script that caused them;
     - updateReady / poll / refresh of app.js (timed() wrappers installed by app.js);
     - CSS animations that run on the main thread (not composited).
   window.QW_FARM_PERF.report() returns the same data as JSON for scripted measurements. */
import {createProfiler} from './scene_profiler.js';

export const PERF_KEY='qw-farm-perf';
export function perfDebugEnabled(loc=globalThis.location,storage=globalThis.localStorage){
 try{if((new URLSearchParams(loc?.search||'').get('debug')||'').split(',').includes('perf'))return true}catch{}
 try{return storage?.getItem(PERF_KEY)==='1'}catch{return false}
}

// ---- app.js functions: synchronous cost, or wall time for async ones (network included) ----
const appTimings=new Map();
function note(name,ms,sync=null){
 let r=appTimings.get(name);if(!r)appTimings.set(name,r={name,n:0,sum:0,max:0,last:0,sync:0,syncMax:0,async:false});
 r.n++;r.sum+=ms;r.last=ms;if(ms>r.max)r.max=ms;
 if(sync!==null){r.async=true;r.sync=sync;if(sync>r.syncMax)r.syncMax=sync}
}
export function timed(name,fn){
 return function(...args){
  const t0=performance.now();let out;
  try{out=fn.apply(this,args)}catch(e){note(name,performance.now()-t0);throw e}
  if(out&&typeof out.then==='function'){const sync=performance.now()-t0;return Promise.resolve(out).finally(()=>note(name,performance.now()-t0,sync))}
  note(name,performance.now()-t0);return out;
 };
}

// ---- CSS animations: transform, opacity and filter run on the compositor; anything else repaints on the main thread ----
const COMPOSITED=new Set(['transform','opacity','translate','rotate','scale','filter','backdrop-filter']);
const KEYFRAME_META=new Set(['offset','computedOffset','easing','composite']);
const kebab=p=>p.startsWith('--')?p:p.replace(/[A-Z]/g,m=>'-'+m.toLowerCase());
function describe(el){
 if(!el)return '?';
 const cls=typeof el.className==='string'?el.className:el.className?.baseVal||'';
 return (el.tagName||'').toLowerCase()+(el.id?'#'+el.id:'')+(cls?'.'+cls.trim().split(/\s+/).slice(0,2).join('.'):'');
}
// Pure (tested): running animations -> {total, village, slow:[{name,target,props,reason,village}]}.
export function animationReport(animations,{villageSelector='.village-scene'}={}){
 const out={total:0,village:0,slow:[]};
 for(const a of animations||[]){
  if(a.playState!=='running')continue;
  const effect=a.effect,target=effect?.target||null;
  if(target?.closest?.('.qw-perf'))continue;   // the overlay's own button transitions
  const inVillage=!!target?.closest?.(villageSelector);
  out.total++;if(inVillage)out.village++;
  let props=[];try{props=[...new Set((effect?.getKeyframes?.()||[]).flatMap(k=>Object.keys(k)).filter(k=>!KEYFRAME_META.has(k)).map(kebab))]}catch{}
  const main=props.filter(p=>!COMPOSITED.has(p));
  // Chrome animates the transform of an element inside an <svg> on the main thread (only the <svg> root is composited).
  const svgChild=!!target?.ownerSVGElement;
  if(main.length||svgChild)out.slow.push({name:a.animationName||a.transitionProperty||a.id||'анимация',target:describe(target),
   props:main.length?main:props,reason:main.length?'свойство не композится':'элемент внутри SVG',village:inVillage});
 }
 out.slow.sort((a,b)=>b.village-a.village);
 return out;
}

// ---- long tasks and long animation frames ----
function watchLongTasks(){
 const tasks=[],frames=[],observers=[];
 const observe=(type,fn)=>{try{const o=new PerformanceObserver(list=>{for(const e of list.getEntries())fn(e)});o.observe({type,buffered:true});observers.push(o)}catch{}};
 observe('longtask',e=>{tasks.push({at:e.startTime,dur:e.duration});if(tasks.length>200)tasks.shift()});
 observe('long-animation-frame',e=>{
  const script=[...(e.scripts||[])].sort((a,b)=>b.duration-a.duration)[0];
  const src=script?`${(script.sourceURL||'').split('/').pop().split('?')[0]||script.invoker||'?'}${script.sourceFunctionName?':'+script.sourceFunctionName:''}`:'';
  // A throttled background tab reports idle 1 s frames: keep only frames that blocked input or ran a long script.
  if(!(e.blockingDuration>0)&&!((script?.duration||0)>=50))return;
  frames.push({at:e.startTime,dur:e.duration,blocking:e.blockingDuration||0,script:src,scriptMs:script?.duration||0});if(frames.length>100)frames.shift();
 });
 return {tasks,frames,disconnect(){for(const o of observers)o.disconnect()}};
}

// ---- overlay ----
const ms=v=>v>=10?v.toFixed(0):v>=1?v.toFixed(1):v.toFixed(2);
const tone=(v,good,bad)=>v<=good?'ok':v<=bad?'warn':'bad';
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e}
function ensureStyle(){
 if(document.querySelector('link[data-qw-perf]'))return;
 const link=document.createElement('link');link.rel='stylesheet';link.href=new URL('./perf_debug.css',import.meta.url).href;link.dataset.qwPerf='1';
 document.head.appendChild(link);
}

export function mountPerfDebug(scene,{windowFrames=120}={}){
 if(globalThis.QW_FARM_PERF)return globalThis.QW_FARM_PERF;
 const proto=Object.getPrototypeOf(scene),miniProto=scene.mini?Object.getPrototypeOf(scene.mini):null;
 const profiler=createProfiler({keep:windowFrames}).instrument(proto,miniProto);
 const longs=watchLongTasks();
 let anims={total:0,village:0,slow:[]},collapsed=false,timer=0,animTimer=0;
 ensureStyle();
 const root=el('aside','qw-perf');root.setAttribute('aria-label','Отладчик производительности фермы');
 const head=el('div','qw-perf-head'),title=el('strong','qw-perf-title','Скорость'),bar=el('div','qw-perf-actions');
 const btn=(label,hint,fn)=>{const b=el('button','qw-perf-btn',label);b.type='button';b.title=hint;b.onclick=fn;bar.appendChild(b);return b};
 btn('Сброс','Начать замер заново',()=>{profiler.reset();appTimings.clear();longs.tasks.length=0;longs.frames.length=0;render()});
 btn('JSON','Скопировать отчёт',async()=>{const text=JSON.stringify(report(),null,1);try{await navigator.clipboard.writeText(text);flash('Отчёт скопирован')}catch{console.log(text);flash('Отчёт в консоли')}});
 const fold=btn('–','Свернуть',()=>{collapsed=!collapsed;root.classList.toggle('is-collapsed',collapsed);fold.textContent=collapsed?'+':'–';fold.title=collapsed?'Развернуть':'Свернуть';render()});
 btn('✕','Выключить отладчик',()=>unmount(true));
 head.append(title,bar);
 const body=el('div','qw-perf-body');root.append(head,body);
 document.body.appendChild(root);
 const flash=text=>{title.textContent=text;setTimeout(()=>{title.textContent='Скорость'},1500)};

 function report(){
  const s=profiler.summary(),span=spanSeconds(s);
  const now=performance.now(),recent=t=>t.at>now-10000;
  return {at:new Date().toISOString(),viewport:{w:innerWidth,h:innerHeight,dpr:devicePixelRatio},
   scene:{scale:scene.scale,objects:scene.farm?.objects?.length||0,frameInterval:scene.frameInterval,ambientInterval:scene.ambientInterval,cost:scene.cost},
   frame:{avgMs:s.avg,maxMs:s.max,fps:s.fps,frames:s.frames},
   sections:s.sections.map(r=>({id:r.id,name:r.name,avgMs:r.avg,maxMs:r.max,share:r.share})),
   objects:s.objects.slice(0,15).map(o=>({id:o.id,type:o.type,x:o.x,y:o.y,avgMs:o.avg,maxMs:o.max})),
   counters:{...s.stats,perSecond:span?{staticPaints:(s.stats.staticPaints||0)/span,fieldPaints:(s.stats.fieldPaints||0)/span,spritePaints:(s.stats.spritePaints||0)/span}:null},
   app:[...appTimings.values()].map(r=>({name:r.name,calls:r.n,avgMs:r.sum/r.n,maxMs:r.max,lastMs:r.last,async:r.async,syncMs:r.async?r.sync:undefined})),
   longTasks:{last10s:longs.tasks.filter(recent).length,maxMs:Math.max(0,...longs.tasks.filter(recent).map(t=>t.dur)),totalMs:longs.tasks.filter(recent).reduce((a,t)=>a+t.dur,0)},
   longFrames:longs.frames.slice(-10),animations:anims};
 }
 const spanSeconds=s=>s.frames>1&&s.fps?(s.frames-1)/s.fps:0;

 function section(name){const box=el('section','qw-perf-sec');box.appendChild(el('h3','qw-perf-h',name));body.appendChild(box);return box}
 function row(box,label,value,cls='',share=null){
  const r=el('div','qw-perf-row'+(cls?' is-'+cls:''));r.append(el('span','qw-perf-label',label),el('span','qw-perf-val',value));
  if(share!==null){const b=el('span','qw-perf-share');b.style.width=Math.max(1,Math.round(share*100))+'%';r.appendChild(b)}
  box.appendChild(r);return r;
 }
 function render(){
  const s=profiler.summary(),span=spanSeconds(s);
  const frameTone=tone(s.avg,8,16);
  title.textContent=collapsed?`Кадр ${ms(s.avg)} мс · ${s.fps.toFixed(0)} к/с`:'Скорость';
  body.replaceChildren();if(collapsed)return;
  const f=section('Кадр сцены');
  if(!s.frames){row(f,'Кадров ещё нет','сцена стоит или вкладка скрыта');return}
  row(f,'Среднее / худший',`${ms(s.avg)} / ${ms(s.max)} мс`,frameTone);
  row(f,'Кадров в секунду',`${s.fps.toFixed(1)} (интервал ${Math.round(scene.frameInterval||0)}, в покое ${Math.round(scene.ambientInterval||scene.frameInterval||0)} мс)`);
  row(f,'Объектов нарисовано',`${s.stats.drawn||0} из ${s.stats.objects||0}`);
  const per=k=>((s.stats[k]||0)/span).toFixed(1);
  row(f,'Перерисовки кэша, в секунду',span?`земля ${per('staticPaints')} · посев ${per('fieldPaints')} · постройки ${per('spritePaints')}`:'—');
  if(span&&s.stats.spriteBlits>0)row(f,'Постройки из кэша, в кадре',`${((s.stats.spriteBlits||0)/s.frames).toFixed(0)} картинок`);
  const L=section('Слои и объекты, мс на кадр');
  for(const r of s.sections.slice(0,16))if(r.avg>=.005)row(L,r.name,`${ms(r.avg)} (макс ${ms(r.max)})`,tone(r.avg,2,5),r.share);
  const O=section('Самые дорогие объекты');
  for(const o of s.objects.slice(0,6))row(O,`${o.type} (${o.x},${o.y})`,`${ms(o.avg)} мс`,tone(o.avg,.5,1.5));
  const A=section('Таймеры приложения');
  if(!appTimings.size)row(A,'Ещё не вызывались','—');
  for(const r of appTimings.values())row(A,r.name+(r.async?' (с сетью)':''),`${ms(r.last)} · ср ${ms(r.sum/r.n)} · макс ${ms(r.max)} мс`+(r.async?` · до await ${ms(r.sync)}`:''),r.async?tone(r.sync,4,16):tone(r.max,8,33));
  const T=section('Долгие задачи (10 с)');
  const now=performance.now(),recent=longs.tasks.filter(t=>t.at>now-10000);
  row(T,'Задач > 50 мс',recent.length?`${recent.length}, макс ${ms(Math.max(...recent.map(t=>t.dur)))} мс, всего ${ms(recent.reduce((a,t)=>a+t.dur,0))} мс`:'нет',recent.length?tone(Math.max(...recent.map(t=>t.dur)),80,150):'ok');
  const lf=longs.frames[longs.frames.length-1];
  if(lf&&lf.at>now-10000)row(T,'Долгий кадр',`${ms(lf.dur)} мс, блок ${ms(lf.blocking)}${lf.script?` · ${lf.script} ${ms(lf.scriptMs)}`:''}`,tone(lf.blocking,50,150));
  const C=section('CSS-анимации на главном потоке');
  row(C,'Идут сейчас',`${anims.total} (деревня ${anims.village})`);
  if(!anims.slow.length)row(C,'Не композятся','нет','ok');
  for(const a of anims.slow.slice(0,6))row(C,`${a.village?'деревня · ':''}${a.name}`,`${a.target}: ${a.props.join(', ')||a.reason}`,'warn');
 }
 const scanAnimations=()=>{try{anims=animationReport(document.getAnimations?.()||[])}catch{}};
 scanAnimations();render();
 timer=setInterval(render,500);animTimer=setInterval(scanAnimations,2000);
 function unmount(forget=false){
  clearInterval(timer);clearInterval(animTimer);longs.disconnect();profiler.restore();root.remove();
  if(forget)try{localStorage.removeItem(PERF_KEY)}catch{}
  delete globalThis.QW_FARM_PERF;
 }
 // ?debug=perf turns it on for one load; QW_FARM_PERF.remember() in the console keeps it on (localStorage) until ✕.
 const api={profiler,report,render,unmount,remember(){try{localStorage.setItem(PERF_KEY,'1')}catch{}},timings:appTimings};
 globalThis.QW_FARM_PERF=api;
 return api;
}
