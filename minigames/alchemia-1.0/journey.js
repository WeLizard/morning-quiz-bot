/* Local expedition seals and server-confirmed seals have separate authority. */
function serverMode(){return serverJourney.status!=='local';}
function journeyClaims(){return serverMode()?serverJourney.claims:state.claims;}
function stageOpened(){return serverMode()?new Set(serverJourney.verifiedDiscovered):found;}
function stageRecipes(){return serverMode()?new Set(serverJourney.verifiedCrafted):knownRecipes;}
function stageEligible(step){
 const opened=stageOpened(),recipes=stageRecipes();
 return (!serverMode()||serverJourney.status==='ready')&&step.goals.every(id=>opened.has(id))&&(step.craft||[]).every(id=>DATA.recipes.some(r=>r.result===id&&recipes.has(r.key)));
}
function claimAvailable(step){return stageEligible(step)||(serverMode()&&window.MQBAlchemySync?.hasPendingClaim(step.id));}
function claimPending(step){return serverMode()&&window.MQBAlchemySync?.hasPendingClaim(step.id);}
function campaignCurrent(c){return c.stages.find(step=>!journeyClaims().includes(step.id))||null;}
function rewardPoints(){return serverMode()?serverJourney.points:(DATA.campaigns||[]).flatMap(c=>c.stages).filter(s=>journeyClaims().includes(s.id)).reduce((n,s)=>n+s.reward.points,0);}
function journeyNotice(){
 if(!serverMode())return 'Печати и очки сохраняются локально в этом браузере.';
 const status=serverJourney.status;
 if(status==='profile-changed')return 'Профиль изменился. Открой игру заново из приложения. Прогресс прежнего профиля сохранён отдельно.';
 return status==='ready'?'Печати и очки подтверждены сервером. Старые локальные печати не начисляют наград.':status==='catalog-mismatch'?'Каталог игры изменился. Открой игру заново из приложения.':status==='unauthorized'?'Сессия истекла. Открой игру из приложения; локальное сохранение осталось.':status==='offline'?'Нет связи с сервером. Локальные открытия сохранены; печати ждут подтверждения.':'Проверяем серверный прогресс. Локальные печати не подтверждают награду.';
}
function activeCampaign(){return (DATA.campaigns||[]).find(c=>c.id===state.activeCampaign)||null;}
function tabs(active){return `<div class="journey-tabs">${[['chapters','Главы'],['epochs','Эпохи'],['campaign','Экспедиции']].map(([key,title])=>`<button class="chip ${active===key?'active':''}" data-action="${key}" aria-pressed="${active===key}">${title}</button>`).join('')}</div>`;}
function epochScene(id,extra=''){
 const palettes={origins:['#142e29','#6c9470','#8eb998','#e1ce91'],makers:['#252936','#a37e64','#c1b190','#e8be83'],cosmos:['#151f37','#50597c','#adb8d1','#e5d7ae'],xeno:['#24273d','#7b6796','#b6a9cb','#bedbad'],mystic:['#282236','#665482','#c0aec7','#e3c28f']};
 const [bg,middle,light,gold]=palettes[id]||palettes.origins;
 const use=(k,x,y,w)=>`<svg x="${x}" y="${y}" width="${w}" height="${w}" viewBox="0 0 120 120"><use href="#art-${k}"/></svg>`;
 let scene=`<rect width="960" height="240" fill="${bg}"/>`;
 for(let i=0;i<32;i++){const x=(i*137+29)%950,y=(i*31+13)%187;scene+=`<circle cx="${x}" cy="${y}" r="${i%4?1:2}" fill="${gold}" opacity=".5"/>`;}
 if(id==='origins')scene+=`<circle cx="728" cy="58" r="32" fill="${gold}" opacity=".75"/><path d="M0 153Q160 50 350 148T730 140T960 143V240H0Z" fill="${middle}"/><path d="M0 199Q210 143 430 195T960 160V240H0Z" fill="#2f5747"/><defs><clipPath id="riverClip"><path d="M0 153Q160 50 350 148T730 140T960 143V240H0Z"/></clipPath></defs><path d="M538 187Q552 191 579 193Q660 205 625 240H492Q420 200 538 187Z" fill="${light}" opacity=".7" clip-path="url(#riverClip)"/>${use('forest',43,19,211)}${use('tree',740,37,185)}${use('greenhouse',299,91,119)}${use('mushroom',698,176,60)}`;
 else if(id==='makers')scene+=`<path d="M0 200L960 172V240H0Z" fill="${middle}" opacity=".36"/><path d="M0 217H960M24 240L960 207M490 188L571 240" stroke="${light}" opacity=".2"/>${use('factory',35,49,176)}${use('windturbine',239,2,197)}${use('solarfarm',421,88,155)}${use('verticalfarm',636,21,185)}${use('nanobot',825,116,97)}<path d="M168 204H659L704 193" fill="none" stroke="${gold}" stroke-width="3" opacity=".5"/>`;
 else if(id==='cosmos')scene+=`<ellipse cx="480" cy="250" rx="530" ry="97" fill="${middle}"/><ellipse cx="480" cy="264" rx="530" ry="95" fill="#242f4a"/>${use('planet',57,5,182)}${use('orbitalcolony',383,5,158)}${use('moonbase',551,115,132)}${use('spaceship',699,35,138)}${use('satellite',291,83,96)}<path d="M160 90Q446-49 794 88" fill="none" stroke="${gold}" stroke-dasharray="4 8" opacity=".32"/>`;
 else if(id==='xeno')scene+=`<circle cx="235" cy="65" r="46" fill="${middle}"/><circle cx="700" cy="37" r="18" fill="${gold}"/><path d="M0 199Q276 120 445 190T960 172V240H0Z" fill="${middle}" opacity=".5"/>${use('alienflora',29,31,182)}${use('aliencity',319,31,189)}${use('ufo',581,9,123)}${use('alienfauna',716,117,129)}${use('xenodiplomat',529,123,102)}`;
 else scene+=`<ellipse cx="480" cy="227" rx="244" ry="34" fill="${middle}"/><path d="M240 240L427 40H533L720 240Z" fill="${light}" opacity=".05"/>${use('stargate',375,-7,228)}${use('timecrystal',221,74,123)}${use('galacticlibrary',659,74,128)}${use('noosphere',86,8,143)}${use('multiverse',794,-4,121)}<path d="M282 176Q481 42 722 178" fill="none" stroke="${gold}" stroke-width="2" opacity=".3"/>`;
 return `<svg class="epoch-scene ${extra}" viewBox="0 0 960 240" role="img" aria-label="${escapeHTML(W.get(id)?.name||'Мир алхимии')}" preserveAspectRatio="xMidYMid slice">${scene}</svg>`;
}
function renderEpochHeading(){
 const id=state.settings.world||'origins',w=W.get(id);const holder=$('epochBanner');if(!holder||!w)return;
 holder.innerHTML=`${epochScene(id)}<button class="epoch-caption" data-epoch="${id}"><span class="eyebrow">Твоя мастерская</span><strong>${escapeHTML(w.name)}</strong><span>Сменить эпоху ${icon('arrow')}</span></button>`;
}
function renderCampaignTracker(){
 const holder=$('campaignTracker');if(!holder)return;
 const c=activeCampaign(),s=c?campaignCurrent(c):null;
 if(!c){holder.innerHTML=`<div class="expedition-tracker"><span class="eyebrow">Большое путешествие</span><strong>Выбери экспедицию</strong><p>Истории с этапами и наградами. Без таймеров и расхода элементов.</p><button class="secondary" data-action="campaign">Открыть экспедиции ${icon('route')}</button></div>`;return;}
 holder.innerHTML=`<div class="expedition-tracker"><span class="eyebrow">${escapeHTML(c.title)}</span><strong>${s?escapeHTML(s.title):'Экспедиция завершена'}</strong>${s?`<p>${s.goals.filter(id=>stageOpened().has(id)).length}/${s.goals.length} открытий · ${claimAvailable(s)?(claimPending(s)?'ожидает подтверждения':'награда готова'):'исследование продолжается'}</p><button class="${claimAvailable(s)?'primary':'secondary'}" ${claimAvailable(s)?`data-claim="${s.id}"`:`data-campaign="${c.id}"`}>${claimAvailable(s)?(claimPending(s)?'Повторить подтверждение':'Получить печать'):'К этапу'} ${icon(claimAvailable(s)?'star':'route')}</button>`:'<button class="secondary" data-action="campaign">Другие экспедиции</button>'}</div>`;
}
function restoreBackup(){
 try{
  const text=localStorage.getItem(STORE+'.backup');if(!text){showToast('Резервной копии пока нет','Снимок появится после нескольких сохранений. Можно импортировать JSON.',null,'failure');return;}
  const saved=cleanSave(JSON.parse(text));
  requestConfirm('Восстановить предыдущий снимок?',`В нём ${saved.discovered.length} открытий. Текущий прогресс будет заменён после подтверждения.`, 'Восстановить',()=>{
   // Use the same import acceptance path, without constructing or executing external code.
   storageLocked=false;loadWarning='';state=saved;found=new Set(state.discovered);knownRecipes=new Set(state.recipeKeys);tried=new Set(state.tried);favorites=new Set(state.favorites);badges=new Set();
   updateAchievements();selected=null;undoStack=[];hint=null;newThisSession.clear();category='all';onlyFavorites=false;$('collectionSearch').value='';$('saveWarning').classList.add('hidden');closeModal();applySettings();renderAll();persist();
   showToast('Снимок восстановлен',`${found.size} открытий в коллекции.`);
  });
 }catch(err){showToast('Копия не читается','Исходные данные сохранены. Используй импорт JSON.',null,'failure');}
}
function showEpochs(){
 const content=tabs('epochs')+`<p class="page-lead">Пять разных мастерских — одна общая коллекция. Эпохи меняют атмосферу и помогают ориентироваться, но не запирают рецепты.</p><div class="epoch-grid">${DATA.worlds.map(w=>{const chapters=DATA.chapters.filter(c=>c.world===w.id),done=chapters.filter(chapterComplete).length;return `<button class="epoch-card ${state.settings.world===w.id?'chosen':''}" data-epoch="${w.id}">${epochScene(w.id)}<span class="epoch-card-copy"><span class="eyebrow">${done}/${chapters.length} глав · ${state.settings.world===w.id?'выбрана':'открыть'}</span><strong>${escapeHTML(w.name)}</strong><span>${escapeHTML(w.description)}</span></span></button>`;}).join('')}</div>`;
 openModal('Атлас эпох','Одна лаборатория. Пять горизонтов.',content,'epochs');
}
function showEpoch(id){
 const w=W.get(id);if(!w)return;
 const chapters=DATA.chapters.filter(c=>c.world===id),camps=DATA.campaigns.filter(c=>c.world===id);
 const content=tabs('epochs')+`<div class="epoch-hero">${epochScene(id)}<div><span class="eyebrow">Эпоха мира</span><h3>${escapeHTML(w.name)}</h3><p>${escapeHTML(w.description)}</p></div></div><div class="button-row"><button class="primary" data-theme="${id}">${icon('lab')} ${state.settings.world===id?'Вернуться в эту мастерскую':'Выбрать мастерскую'}</button>${camps.map(c=>`<button class="secondary" data-campaign="${c.id}">${icon('route')} ${escapeHTML(c.title)}</button>`).join('')}</div><h3 class="section-heading">Истории эпохи</h3><div class="chapter-grid">${chapters.map(c=>`<section class="chapter-tile"><div class="eyebrow">${chapterComplete(c)?'Завершена':'Исследование'}</div><h3>${escapeHTML(c.title)}</h3><p>${escapeHTML(c.subtitle)}</p><div class="goal-list">${c.goals.map(goalRow).join('')}</div></section>`).join('')}</div>`;
 openModal(w.name,`${chapters.filter(chapterComplete).length} из ${chapters.length} глав`,content,'epoch',id);
}
function showCampaign(id=null){
 const c=DATA.campaigns.find(c=>c.id===id);
 if(c){showCampaignDetail(c);return;}
 const all=DATA.campaigns.flatMap(c=>c.stages),points=rewardPoints();
 const content=tabs('campaign')+`<p class="page-lead">${journeyNotice()}</p><div class="expedition-intro"><div><span class="eyebrow">${journeyClaims().length}/${all.length} печатей · ${points} очков экспедиций</span><h3>Не просто собрать.<br>Построить свою историю.</h3></div><p>В каждом путешествии четыре последовательных этапа. Открытия сохраняются между историями. Для экспериментальной части нужно самостоятельно получить указанный результат, а не только импортировать его.</p></div><div class="epoch-grid">${DATA.campaigns.map(c=>{const done=c.stages.filter(s=>journeyClaims().includes(s.id)).length;return `<button class="epoch-card ${state.activeCampaign===c.id?'chosen':''}" data-campaign="${c.id}">${epochScene(c.world)}<span class="epoch-card-copy"><span class="eyebrow">${done}/4 этапа · ${state.activeCampaign===c.id?'отслеживается':'экспедиция'}</span><strong>${escapeHTML(c.title)}</strong><span>${escapeHTML(c.description)}</span><span class="chapter-progress"><span style="width:${done/4*100}%"></span></span></span></button>`;}).join('')}</div>`;
 openModal('Экспедиции','Открытия становятся историями',content,'campaign');
}
function showCampaignDetail(c){
 const current=campaignCurrent(c);const allDone=!current;
 const content=tabs('campaign')+`<p class="page-lead">${journeyNotice()}</p><div class="epoch-hero">${epochScene(c.world)}<div><span class="eyebrow">Экспедиция · 4 этапа</span><h3>${escapeHTML(c.title)}</h3><p>${escapeHTML(c.description)}</p></div></div><div class="button-row"><button class="primary" data-track="${c.id}">${icon('target')} ${state.activeCampaign===c.id?'Продолжить исследование':'Следить за экспедицией'}</button><button class="secondary" data-action="campaign">Все экспедиции</button></div><div class="stages">${c.stages.map((s,index)=>{const claimed=journeyClaims().includes(s.id),active=current===s,eligible=claimAvailable(s),status=claimed?(serverMode()?'Подтверждено сервером':'Локальная печать'):active?eligible?(claimPending(s)?'Ожидает подтверждения':'Готово к завершению'):'Текущий этап':'Следующий этап';return `<section class="stage ${claimed?'claimed':active?'current':'upcoming'}"><div class="stage-number">${claimed?icon('check'):String(index+1).padStart(2,'0')}</div><div class="stage-content"><span class="eyebrow">${status} · ${s.reward.points} очков</span><h3>${escapeHTML(s.title)}</h3><p>${escapeHTML(claimed?s.ending:s.brief)}</p>${claimed?'':`<div class="stage-goals">${s.goals.map(id=>`<button data-goal="${id}" class="stage-goal ${stageOpened().has(id)?'complete':''}">${art(id)}<span>${escapeHTML(name(id))}</span>${icon(stageOpened().has(id)?'check':'target')}</button>`).join('')}</div><p class="craft-condition">${(s.craft||[]).map(id=>{const done=DATA.recipes.some(r=>r.result===id&&stageRecipes().has(r.key));return `${done?'✓':'○'} Эксперимент: получить «${escapeHTML(name(id))}» любым рецептом.`;}).join('<br>')}</p>`}${active?`<div class="button-row">${eligible?`<button class="primary" data-claim="${s.id}">${icon('star')} ${claimPending(s)?'Повторить подтверждение':'Завершить этап'}</button>`:`<button class="secondary" data-investigate="${c.id}">${icon('hint')} Подсказка к этапу</button>`}</div>`:''}</div></section>`;}).join('')}</div>${allDone?`<div class="completion-card">${art('philosopher')}<h3>Экспедиция завершена</h3><p>Четыре печати уже в твоём архиве. Все открытия остаются доступны для новых историй.</p><button class="primary" data-action="campaign">Выбрать следующее путешествие</button></div>`:''}`;
 openModal(c.title,`${c.stages.filter(s=>journeyClaims().includes(s.id)).length}/4 этапа завершено`,content,'campaign-detail',c.id);
}
async function claimStage(id){
 const c=DATA.campaigns.find(c=>c.stages.some(s=>s.id===id));if(!c)return;
 const s=campaignCurrent(c);if(!s||s.id!==id||!claimAvailable(s))return;
 let awarded=s.reward.points;
 if(serverMode()){
  const result=await window.MQBAlchemySync?.claimStage(s.id);
  if(!result?.ok){showToast('Печать не подтверждена',result?.message||journeyNotice(),null,'failure');renderCampaignTracker();return;}
  awarded=result.data.awarded_expedition_points;
 }else state.claims.push(s.id);
 state.activeCampaign=c.id;persist();renderCampaignTracker();
 const next=campaignCurrent(c);
 openModal(s.title,serverMode()?'Печать подтверждена сервером':'Локальная печать получена',`<div class="completion-card">${art(s.goals.at(-1))}<span class="pill">+${awarded} очков · всего ${rewardPoints()}</span><h3>${escapeHTML(s.title)}</h3><p>${escapeHTML(s.ending)}</p><p>${journeyNotice()}</p><div class="button-row"><button class="primary" data-campaign="${c.id}">${next?'Следующий этап':'Итоги экспедиции'} ${icon('arrow')}</button><button class="secondary" data-action="home">В мастерскую</button></div></div>`,'stage-complete',c.id);
 playSound('discovery');
}
function investigateCampaign(id){
 const c=DATA.campaigns.find(c=>c.id===id),s=c?campaignCurrent(c):null;if(!s)return;
 state.activeCampaign=id;
 if(serverMode()){
  if(serverJourney.status!=='ready'){showToast('Нужно подтверждение сервера',journeyNotice(),null,'failure');return;}
  const opened=stageOpened(),recipes=stageRecipes();
  const target=s.goals.find(id=>!opened.has(id))||(s.craft||[]).find(id=>!DATA.recipes.some(r=>r.result===id&&recipes.has(r.key)));
  if(target){
   const direct=DATA.recipes.find(r=>r.result===target&&opened.has(r.a)&&opened.has(r.b));
   const info=direct?{recipe:direct,target}:findHint(target,opened,recipes);
   if(info){state.pinned=null;hint={...info,alternative:true,verified:true,stage:1};persist();showHint();return;}
   showToast('Повтори опыты онлайн','Для печати нужны подтверждённые сервером рецепты. Начни с воды, земли, огня и воздуха.',null,'normal');return;
  }
  showCampaign(c.id);return;
 }
 const missing=s.goals.find(x=>!found.has(x));
 if(missing){pinGoal(missing);return;}
 const craft=(s.craft||[]).find(id=>!DATA.recipes.some(r=>r.result===id&&knownRecipes.has(r.key)));
 if(craft){
  const r=DATA.recipes.find(r=>r.result===craft&&found.has(r.a)&&found.has(r.b));
  if(r){state.pinned=null;hint={recipe:r,target:craft,alternative:true,stage:1};persist();showHint();return;}
  const candidate=DATA.recipes.find(r=>r.result===craft);const need=[candidate.a,candidate.b].find(x=>!found.has(x));if(need){pinGoal(need);return;}
 }
 showCampaign(c.id);
}
listen(document,'click',e=>{
 const el=e.target.closest('[data-epoch],[data-theme],[data-campaign],[data-track],[data-claim],[data-investigate]');if(!el)return;
 if(el.dataset.epoch){showEpoch(el.dataset.epoch);return;}
 if(el.dataset.theme){const id=el.dataset.theme;if(!W.has(id))return;state.settings.world=id;applySettings();persist();closeModal();return;}
 if(el.dataset.campaign){showCampaign(el.dataset.campaign);return;}
 if(el.dataset.track){const c=DATA.campaigns.find(c=>c.id===el.dataset.track);if(!c)return;state.activeCampaign=c.id;state.settings.world=c.world;applySettings();renderCampaignTracker();persist();closeModal();return;}
 if(el.dataset.claim){claimStage(el.dataset.claim);return;}
 if(el.dataset.investigate)investigateCampaign(el.dataset.investigate);
});
