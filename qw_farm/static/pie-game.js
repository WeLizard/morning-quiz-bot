import {craneX,drop as dropLayer,logValid,TOWER_CENTER} from './pie-physics.js';

const GAME='agata_pie',NS='http://www.w3.org/2000/svg';
// Scene geometry (scene units, y down; the same numbers as scripts/art/village_games/pie_scene.js).
// The tower stands on the plate (top y=470); layer n (1-based) has its top at 470-30n. The gantry beam stands on scaffolds
// and is 250 above the tower top (220 at height 0); the corzh hangs 100 below the beam. Every new layer adds a scaffold tier,
// the beam rises with it and the camera follows, keeping the tower top at y=380 of the screen.
export const GEOM={plateTop:470,layerH:30,rail0:220,hangGap:100,groundY:520,tierH:30,tiers0:10,follow:380,scaffoldX:[24,896],markEvery:5,base:560};
export const towerTop=n=>GEOM.plateTop-GEOM.layerH*n;
export const railY=h=>GEOM.rail0-GEOM.layerH*h;
export const hangY=h=>railY(h)+GEOM.hangGap;
export const cameraFor=h=>Math.max(0,GEOM.layerH*h-(GEOM.plateTop-GEOM.follow));
// Height zones by tower layers: the sky in the scene changes smoothly between them.
export const ZONES=[{from:0,name:'Ярмарка'},{from:10,name:'Облака'},{from:20,name:'Стратосфера'},{from:32,name:'Космос'}];
export function zoneAt(h){let zone=ZONES[0];for(const item of ZONES)if(h>=item.from)zone=item;return zone;}
const reduced=()=>!!globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
const contrast=()=>globalThis.document?.documentElement?.dataset?.qwContrast==='1';
const clock=()=>globalThis.performance?.now?.()??Date.now();

// The corzh drawing: sponge with an outline, icing with drips, a jam line and berries. The scene generator draws the
// hanging corzh with this same function, so tower layers, cut pieces and the corzh on the crane look alike.
export function korzhMarkup(k,x,y,w,index=0,strong=false){
 const r=v=>+(+v).toFixed(1),edge=strong?k.edgeContrast:k.edge,sw=strong?4:2.5,out=[];
 out.push(`<rect x="${r(x)}" y="${r(y)}" width="${r(w)}" height="30" rx="${Math.min(9,r(w/2))}" fill="${index%2?k.sponge2:k.sponge}" stroke="${edge}" stroke-width="${sw}"/>`);
 if(w>=16){
  const left=x+3,right=x+w-3,n=Math.max(1,Math.round((right-left)/34)),step=(right-left)/n;
  let d=`M${r(left)} ${r(y+3)}H${r(right)}V${r(y+9)}`;
  for(let i=n-1;i>=0;i--){const a=left+step*i,mid=a+step/2;d+=`Q${r(mid)} ${r(y+(i%2?14:16))} ${r(a)} ${r(y+9)}`;}
  out.push(`<path d="${d}Z" fill="${k.glaze}"/>`);
  out.push(`<rect x="${r(left)}" y="${r(y+19)}" width="${r(right-left)}" height="4" rx="2" fill="${k.jam}"/>`);
 }
 const berries=Math.floor(w/80);
 for(let i=0;i<berries;i++)out.push(`<circle cx="${r(x+(i+.5)*w/berries)}" cy="${r(y+4)}" r="5" fill="${k.berry}"/>`);
 return out.join('');
}

const hex=c=>{const v=parseInt(c.slice(1,7),16);return [v>>16&255,v>>8&255,v&255];};
const mixColour=(a,b,t)=>'#'+hex(a).map((v,i)=>Math.round(v+(hex(b)[i]-v)*t).toString(16).padStart(2,'0')).join('');
// Keyframes [[height, value…], …]: numbers or #rrggbb colours, linear between neighbours, clamped at the ends.
export function keyframe(keys,h){
 if(h<=keys[0][0])return keys[0].slice(1);
 for(let i=1;i<keys.length;i++)if(h<=keys[i][0]){
  const a=keys[i-1],b=keys[i],t=(h-a[0])/(b[0]-a[0]);
  return a.slice(1).map((v,j)=>typeof v==='number'?v+(b[j+1]-v)*t:mixColour(v,b[j+1],t));
 }
 return keys[keys.length-1].slice(1);
}

function korzh(n){return n%10===1&&n%100!==11?'корж':[2,3,4].includes(n%10)&&![12,13,14].includes(n%100)?'коржа':'коржей';}
export function pieResultText(result,tower){
 if(!result)return '';
 if(result.expired)return 'Время попытки вышло. Можно начать новую.';
 const parts=[`Поставлено ${result.height} ${korzh(result.height)}.`];
 if(result.practice)parts.push('Тренировка.');
 else{parts.push(`Лучшая высота: ${result.best}.`);if(result.miss)parts.push('Корж пролетел мимо.');}
 if(tower)parts.push(`Башня деревни: ${tower.total} из ${tower.goal}.`);
 return parts.join(' ');
}
export function towerText(tower){
 if(!tower)return 'Башня деревни ждёт ярмарки.';
 const people=tower.players?` · участников: ${tower.players}`:'';
 return `Башня деревни: ${tower.total} из ${tower.goal}${people}.${tower.reached?` «${tower.name}» уже у участников.`:''}`;
}

export function mountPieGame(host,{getState,tower,command,onBack,isCommandPending=()=>false,now=()=>Date.now()/1000,storageKey='farm'}){
 let disposed=false,sceneEpoch=0,theme='',local=null,submitting=false,raf=0,scene=null,lastFrame=0,shownZone='',zoneTimer=0;
 // Visual state: shown layers (a corzh in flight is not shown yet), the eased crane height h and the camera.
 let vis={shown:0,h:0,cam:0,falling:null,reloadAt:-1e9,pieces:[]};
 const savedLogs=new Map();
 const logKey=id=>`mqb-pie:${storageKey}:${id}`;
 function saveLog(){if(!local)return;const value=JSON.stringify(local.log);savedLogs.set(logKey(local.run_id),value);try{sessionStorage.setItem(logKey(local.run_id),value);}catch{}}
 function loadLog(runId,plan){try{const value=savedLogs.get(logKey(runId))||sessionStorage.getItem(logKey(runId));const log=value?JSON.parse(value):[];return logValid(plan,log)?log:[];}catch{return [];}}
 function clearLog(runId){savedLogs.delete(logKey(runId));try{sessionStorage.removeItem(logKey(runId));}catch{}}
 function layersFrom(plan,log){
  let lo=TOWER_CENTER-Math.floor(plan.base/2),hi=TOWER_CENTER+Math.floor(plan.base/2);const layers=[];
  for(const t of log){const x=craneX(plan,t,layers.length),landed=dropLayer(lo,hi,x,plan.base);if(!landed)break;layers.push({x,lo:landed[0],hi:landed[1]});[lo,hi]=landed;}
  return {layers,tower:[lo,hi]};
 }
 host.hidden=false;
 host.innerHTML=`<div class="pie-page"><div class="pie-title"><h1>Пирог до небес</h1><button class="pie-back" type="button">‹ В деревню</button></div><p class="pie-intro">Коснись сцены — корж упадёт с крана. Края, что свисают, срезаются. Леса с краном растут вместе с башней: выше облаков, в стратосферу и до космоса.</p><div class="pie-layout"><div class="pie-stage-card"><div class="pie-stage"><div class="pie-scene" role="button" tabindex="0" aria-label="Коснись сцены, чтобы сбросить корж" aria-disabled="true"></div><p class="pie-alt" aria-hidden="true"></p></div><p class="pie-progress"></p></div><section class="pie-controls" aria-label="Управление пирогом"><p class="pie-status" role="status"></p><p class="pie-tower"></p><div class="qw-btn-stack pie-actions"><button type="button" class="qw-btn primary pie-start">Начать</button><button type="button" class="qw-btn secondary pie-drop" hidden>Бросить корж</button></div><p class="pie-rules">Забег кончается на первом промахе или через 60 секунд. Три призовые попытки в день, затем бесплатная тренировка. В общую башню идёт лучшая высота каждого участника за ярмарку; тренировка не идёт. Награда — праздничный декор всем участникам, без монет и опыта.</p></section></div></div>`;
 const $=s=>host.querySelector(s),stage=$('.pie-scene'),altBadge=$('.pie-alt'),status=$('.pie-status'),progress=$('.pie-progress'),towerLine=$('.pie-tower'),start=$('.pie-start'),dropBtn=$('.pie-drop');
 const state=()=>getState()||null,shared=()=>{try{return tower()||null}catch{return null}};
 const elapsedMs=()=>local?Math.max(0,Math.round((now()-local.started_at)*1000)):0;
 const running=()=>!!local&&!local.ended&&state()?.active?.run_id===local.run_id;

 async function loadScene(){
  const next=globalThis.document?.documentElement?.dataset?.farmTheme==='night'?'night':'day';if(theme===next)return;theme=next;const epoch=++sceneEpoch;
  try{const response=await fetch(`/app/farm/assets/pie-${next==='night'?'night':'scene'}.svg`);if(!response.ok)throw new Error('scene');const svg=await response.text();if(disposed||epoch!==sceneEpoch)return;stage.innerHTML=svg;setupScene();}
  catch{if(!disposed&&epoch===sceneEpoch){theme='';scene=null;stage.textContent='Не удалось загрузить сцену. Проверь соединение и открой игру снова.';}}
 }
 function make(tag,attrs){const node=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))node.setAttribute(k,String(v));return node;}
 function parse(node,key,fallback){try{return JSON.parse(node.getAttribute(key))}catch{return fallback}}
 function setupScene(){
  const svg=stage.querySelector('svg');if(!svg){scene=null;return;}
  const get=id=>svg.querySelector('#'+id),towerNode=get('pie-tower');
  const ds=towerNode?.dataset||{};
  scene={svg,world:get('pie-world'),stops:[0,1,2].map(i=>get('pie-sky-'+i)),stars:get('pie-stars'),earth:get('pie-earth'),
   scaffold:[get('pie-scaffold-l'),get('pie-scaffold-r')],clip:get('pie-scaffold-cliprect'),marks:get('pie-marks'),tower:towerNode,
   cuts:get('pie-cuts'),falling:get('pie-falling'),crane:get('pie-crane'),trolley:get('pie-trolley'),hanging:get('pie-layer'),
   sky:parse(svg,'data-sky',null),starKeys:parse(svg,'data-stars',[[0,0]]),earthKeys:parse(svg,'data-earth',[[0,760]]),
   ink:get('pie-marks')?.getAttribute('data-ink')||'#4a3520',
   k:{sponge:ds.sponge||'#d9a35f',sponge2:ds.sponge2||'#e3b16e',glaze:ds.glaze||'#f3d79f',jam:ds.jam||'#d98a6a',berry:ds.berry||'#c0544a',edge:ds.edge||'#8f5a2c',edgeContrast:ds.edgeContrast||'#3f230b'},
   tiers:0,markTop:0,layers:0,strong:contrast()};
  rebuild();
 }
 // Everything placed by the game is rebuilt from the run: after loading, a theme change or a restored run.
 function rebuild(){
  if(!scene)return;
  scene.scaffold.forEach(g=>g?.replaceChildren());scene.tiers=0;scene.marks?.replaceChildren();scene.markTop=0;
  scene.tower?.replaceChildren();scene.layers=0;scene.cuts?.replaceChildren();scene.strong=contrast();
  syncTower();draw();
 }
 function ensureScaffold(h){
  const need=GEOM.tiers0+Math.ceil(h)+1;
  for(let j=scene.tiers;j<need;j++){
   const id=(j+1)%5===0?'pie-tier-deck':j%2?'pie-tier-b':'pie-tier-a';
   scene.scaffold.forEach((g,side)=>g?.append(make('use',{href:'#'+id,x:GEOM.scaffoldX[side],y:GEOM.groundY-GEOM.tierH*(j+1)})));
  }
  scene.tiers=Math.max(scene.tiers,need);
  // Height plates every five layers on the left scaffold, a few ahead of the tower as the next goal.
  const top=Math.ceil((vis.shown+12)/GEOM.markEvery)*GEOM.markEvery;
  for(let n=scene.markTop+GEOM.markEvery;n<=top;n+=GEOM.markEvery){
   const y=towerTop(n)+15,g=make('g',{class:'pie-mark',transform:`translate(64 ${y})`});
   g.append(make('use',{href:'#pie-plate'}));
   const text=make('text',{x:0,y:8,'text-anchor':'middle','font-size':22,'font-weight':800,'font-family':'system-ui,sans-serif',fill:scene.ink});
   text.textContent=String(n);g.append(text);scene.marks?.append(g);
  }
  scene.markTop=Math.max(scene.markTop,top);
 }
 function syncTower(){
  if(!scene?.tower)return;
  const layers=local?local.layers:[];
  for(let i=scene.layers;i<vis.shown&&i<layers.length;i++){
   const g=make('g',{});g.innerHTML=korzhMarkup(scene.k,layers[i].lo,towerTop(i+1),layers[i].hi-layers[i].lo,i,scene.strong);
   scene.tower.append(g);
  }
  scene.layers=Math.max(scene.layers,Math.min(vis.shown,layers.length));
 }
 function draw(){
  if(!scene)return;
  const h=vis.h,cam=vis.cam,t=clock();
  ensureScaffold(h);
  scene.world?.setAttribute('transform',`translate(0 ${cam.toFixed(2)})`);
  scene.crane?.setAttribute('transform',`translate(0 ${(railY(h)-GEOM.rail0).toFixed(2)})`);
  scene.clip?.setAttribute('y',(railY(h)+4).toFixed(2));
  const x=local?.craneX??TOWER_CENTER;
  scene.trolley?.setAttribute('transform',`translate(${x-TOWER_CENTER} 0)`);
  // The next corzh slides down from the trolley after a landing; none while one is falling or after the run.
  const hidden=!!vis.falling||(local&&local.ended);
  if(scene.hanging){
   scene.hanging.setAttribute('display',hidden?'none':'inline');
   const k=reduced()?1:Math.min(1,(t-vis.reloadAt)/180);
   scene.hanging.setAttribute('transform',`translate(0 ${(-26*(1-k)).toFixed(1)})`);
  }
  const f=vis.falling;
  if(scene.falling){
   scene.falling.setAttribute('display',f?'inline':'none');
   if(f){const k=Math.min(1,(t-f.t0)/f.ms),y=f.fromY+(f.toY-f.fromY)*k*k,turn=f.miss?f.spin*k:0;
    scene.falling.setAttribute('transform',`translate(${f.x} ${y.toFixed(1)}) rotate(${turn.toFixed(1)} 0 15)`);}
  }
  for(const piece of vis.pieces){
   const age=t-piece.t0;
   piece.node.setAttribute('transform',`translate(${(piece.vx*age).toFixed(1)} ${(0.0016*age*age).toFixed(1)}) rotate(${(piece.spin*age).toFixed(1)} ${piece.cx} ${piece.cy})`);
  }
  if(scene.sky)keyframe(scene.sky,h).forEach((colour,i)=>scene.stops[i]?.setAttribute('stop-color',colour));
  scene.stars?.setAttribute('opacity',keyframe(scene.starKeys,h)[0].toFixed(3));
  scene.earth?.setAttribute('transform',`translate(0 ${keyframe(scene.earthKeys,h)[0].toFixed(1)})`);
  const zone=zoneAt(vis.shown).name;
  altBadge.textContent=`${zone} · ${vis.shown}`;
  if(zone!==shownZone){
   if(shownZone&&!reduced()){altBadge.classList.add('pie-alt-new');clearTimeout(zoneTimer);zoneTimer=setTimeout(()=>altBadge.classList.remove('pie-alt-new'),1400);}
   shownZone=zone;
  }
 }
 function land(f){
  vis.shown+=1;syncTower();vis.reloadAt=clock();
  // The status line is the polite live region: one short announcement per layer, not a ticking timer.
  if(local&&!local.ended)setText(status,`Высота ${vis.shown} · ${zoneAt(vis.shown).name.toLowerCase()}.`);
  if(reduced()||!scene?.cuts)return;
  const y=towerTop(f.index+1),half=GEOM.base/2;
  for(const [a,b,dir] of [[f.x-half,f.lo,-1],[f.hi,f.x+half,1]]){
   if(b-a<2)continue;
   const g=make('g',{class:'pie-cut'});g.innerHTML=korzhMarkup(scene.k,a,y,b-a,f.index,scene.strong);scene.cuts.append(g);
   vis.pieces.push({node:g,t0:clock(),vx:.14*dir,spin:.05*dir,cx:(a+b)/2,cy:y+15});
  }
 }
 function moving(){return running()||!!vis.falling||vis.pieces.length>0||Math.abs(vis.h-vis.shown)>.001||Math.abs(vis.cam-cameraFor(vis.h))>.05;}
 function kick(){if(!raf&&!disposed){lastFrame=clock();raf=requestAnimationFrame(tick);}}
 function stopLoop(){cancelAnimationFrame(raf);raf=0;}
 function tick(){
  raf=0;if(disposed)return;
  const t=clock(),dt=Math.min(100,Math.max(0,t-lastFrame));lastFrame=t;
  if(local&&running()){
   const elapsed=elapsedMs();
   if(elapsed>=local.plan.limit_ms){end(true);}
   else{
    local.craneX=craneX(local.plan,elapsed,local.layers.length);
    setProgress(elapsed);
    if(!local.layers.length)setText(status,elapsed<local.plan.warmup_ms?'Приготовься: сейчас поедет кран.':'Коснись сцены или нажми «Бросить корж».');
   }
  }
  const f=vis.falling;
  if(f&&t-f.t0>=f.ms){vis.falling=null;if(!f.miss)land(f);}
  vis.pieces=vis.pieces.filter(p=>{if(t-p.t0<900)return true;p.node.remove();return false;});
  if(reduced()){vis.h=vis.shown;vis.cam=cameraFor(vis.h);}
  else{
   vis.h+=(vis.shown-vis.h)*(1-Math.exp(-dt/110));if(Math.abs(vis.shown-vis.h)<.001)vis.h=vis.shown;
   const target=cameraFor(vis.h);vis.cam+=(target-vis.cam)*(1-Math.exp(-dt/170));if(Math.abs(target-vis.cam)<.05)vis.cam=target;
  }
  draw();
  if(moving())raf=requestAnimationFrame(tick);
 }
 function setText(node,text){if(node.textContent!==text)node.textContent=text;}
 function setProgress(elapsed){
  const n=local?local.layers.length:0,zone=zoneAt(n).name.toLowerCase();
  const left=local?Math.max(0,Math.ceil((local.plan.limit_ms-elapsed)/1000)):0;
  setText(progress,`Высота: ${n} · ${zone} · ${left} с`);
 }
 function begin(active){
  stopLoop();
  const log=loadLog(active.run_id,active.plan),built=layersFrom(active.plan,log);
  local={run_id:active.run_id,plan:active.plan,started_at:active.started_at,practice:active.practice,log,
         layers:built.layers,tower:built.tower,lastTap:log.length?log[log.length-1]:-1e9,ended:false,craneX:TOWER_CENTER};
  // A restored run shows its tower at once; a new run starts on the ground.
  vis={shown:built.layers.length,h:built.layers.length,cam:cameraFor(built.layers.length),falling:null,reloadAt:-1e9,pieces:[]};
  rebuild();kick();
 }
 function tap(){
  const active=state()?.active;if(!local||!active||active.run_id!==local.run_id||local.ended||submitting)return;
  const t=elapsedMs();
  if(t>local.plan.limit_ms){end(true);return;}
  if(t-local.lastTap<local.plan.min_gap_ms)return;
  local.lastTap=t;local.log.push(t);saveLog();
  const height=local.layers.length,x=craneX(local.plan,t,height),landed=dropLayer(local.tower[0],local.tower[1],x,local.plan.base);
  local.craneX=x;
  const fromY=hangY(vis.h);
  if(landed===null){
   local.ended=true;
   // A miss falls past the tower and out of the frame.
   vis.falling={x,fromY,toY:660-vis.cam,ms:Math.max(700,local.plan.fall_ms*2),miss:true,spin:x<TOWER_CENTER?-28:28,t0:clock()};
   status.textContent='Мимо — корж пролетел.';progress.textContent=`Высота: ${height}.`;
   setTimeout(()=>void submit(),local.plan.fall_ms+30);kick();return;
  }
  local.tower=[landed[0],landed[1]];local.layers.push({x,lo:landed[0],hi:landed[1]});
  vis.falling={x,fromY,toY:towerTop(height+1),ms:local.plan.fall_ms,miss:false,t0:clock(),index:height,lo:landed[0],hi:landed[1]};
  setProgress(t);kick();
 }
 function end(timeUp){
  if(!local||local.ended)return;
  local.ended=true;
  status.textContent=timeUp?'Время вышло — сохраняем башню.':'Забег окончен.';
  void submit();
 }
 async function submit(){
  if(disposed||submitting||!local)return;
  submitting=true;render();
  try{await command('vgame_finish',{game:GAME,run_id:local.run_id,log:local.log.slice()});clearLog(local.run_id);}
  catch(e){if(!disposed)status.textContent=e?.message||'Не удалось сохранить результат.';}
  finally{submitting=false;if(!disposed)render();}
 }
 function render(){
  if(disposed)return;
  void loadScene();
  const s=state(),active=s?.active,pending=submitting||isCommandPending();
  if(active&&(!local||local.run_id!==active.run_id))begin(active);
  if(!active&&local)local.ended=true;
  const last=s?.last_result;
  start.hidden=!!active;dropBtn.hidden=!active;
  start.disabled=pending||!s?.available;
  start.textContent=s?.available?(s.attempts_left>0?(last?'Ещё раз':'Начать'):'Тренировка'):'Ждём ярмарку';
  dropBtn.disabled=pending||!active||!!local?.ended;
  stage.setAttribute('aria-disabled',String(!active||pending||!!local?.ended));
  if(active)setText(status,pending?'Сохраняем попытку…':local?.ended?'Сохраняем результат…':local?.layers.length?`Высота ${local.layers.length} · ${zoneAt(local.layers.length).name.toLowerCase()}.`:'Коснись сцены или нажми «Бросить корж».');
  else if(!s?.available)status.textContent='Пирог до небес ждёт ярмарки.';
  else if(last)status.textContent=pieResultText(last,null);
  else status.textContent='Сложи башню до небес.';
  if(!active)progress.textContent=s?.available?`Призовых попыток осталось: ${s.attempts_left} из 3.`:'';
  towerLine.textContent=towerText(shared());
  draw();kick();
 }
 start.addEventListener('click',async()=>{
  if(submitting||isCommandPending())return;submitting=true;render();
  try{await command('vgame_start',{game:GAME});}catch(e){if(!disposed)status.textContent=e?.message||'Не удалось начать.';}
  finally{submitting=false;if(!disposed)render();}
 });
 dropBtn.addEventListener('click',tap);
 stage.addEventListener('pointerdown',event=>{if(stage.getAttribute('aria-disabled')==='true')return;event.preventDefault();tap();});
 stage.addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ')&&stage.getAttribute('aria-disabled')==='false'){event.preventDefault();tap();}});
 $('.pie-back').addEventListener('click',onBack);
 const observer=new MutationObserver(records=>{
  if(records.some(r=>r.attributeName==='data-farm-theme')){theme='';void loadScene();}
  else if(scene&&scene.strong!==contrast())rebuild();
 });
 observer.observe(document.documentElement,{attributes:true,attributeFilter:['data-farm-theme','data-qw-contrast']});
 render();
 return {render,destroy(){disposed=true;sceneEpoch++;stopLoop();clearTimeout(zoneTimer);observer.disconnect();host.hidden=true;host.replaceChildren();}};
}
