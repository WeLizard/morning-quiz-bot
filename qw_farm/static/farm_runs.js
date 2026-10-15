/* Pure helpers of the farm client (no DOM, no state): seed classes and statistics, the seed strip order and the
   «repeat the last machine run» plan. The server stays the authority: every command is validated again there. */
export const CLASS_LABEL={fast:'быстрая',medium:'средняя',long:'долгая'};
export const CLASS_HINT={fast:'Быстрая культура: заходи почаще.',medium:'Средняя культура: хватит одного захода в пару часов.',long:'Долгая культура: посади перед уходом.'};
export const LONG_HINT='Долгая культура: посади перед уходом';
export const GRAINS=['wheat','corn','oat','rye','rice','buckwheat'];   // what the combine reaps (qw_farm/expansion.py GRAINS)
export const MAX_PLOTS=24;                                              // plots per machine run (server limit)
const DEFAULT_LIMITS={slow:1800,long:14400};

export function cropClass(seconds,limits=DEFAULT_LIMITS){
 return seconds<limits.slow?'fast':seconds<limits.long?'medium':'long';
}

/* Profit and XP per hour of growth (one bed, one harvest) at the given game speed. */
export function seedStats(crop,price,speed=1,limits=DEFAULT_LIMITS){
 const seconds=Math.max(1,Math.ceil(crop.seconds/Math.max(1,speed))),hours=seconds/3600,profit=crop.yield_qty*price-crop.cost;
 const cls=cropClass(crop.seconds,limits);
 return {cls,label:CLASS_LABEL[cls],seconds,profit,perHour:Math.round(profit/hours),xpPerHour:Math.round(crop.xp/hours*10)/10,hint:CLASS_HINT[cls]};
}

/* The seed strip: open seeds first, shortest growth time first (then the cheaper level); locked ones follow by level. */
export function sortSeeds(crops,level){
 const list=[...crops];
 const open=list.filter(c=>c.level<=level).sort((a,b)=>a.seconds-b.seconds||a.level-b.level||a.cost-b.cost||(a.id<b.id?-1:1));
 const shut=list.filter(c=>c.level>level).sort((a,b)=>a.level-b.level||a.seconds-b.seconds||(a.id<b.id?-1:1));
 return open.concat(shut);
}

const byId=(a,b)=>a.id<b.id?-1:a.id>b.id?1:0;

/* What one machine can do right now. Returns {ok,machine,crop,replant,plots,count,cost,label,why}. The plan never
   exceeds the 24 plots or the coins of the player; `why` explains a disabled button. */
export function planMachine({machine,crop,replant},me,catalog,now){
 const spec=catalog.equipment[machine],none=why=>({ok:false,machine,crop:crop||'',replant:!!replant,plots:[],count:0,cost:0,label:spec?spec.name:machine,why});
 if(!spec||!me.equipment?.[machine])return none('Сначала приобрети технику в разделе «Команда».');
 const plots=me.objects.filter(o=>o.type==='plot').sort(byId);
 if(machine==='tractor'){
  const c=catalog.crops[crop];
  if(!c)return none('Выбери культуру для трактора.');
  if(c.level>me.level)return none(`${c.name}: нужен уровень ${c.level}.`);
  const empty=plots.filter(o=>!o.crop);
  if(!empty.length)return none('Нет свободных грядок.');
  const afford=Math.floor(me.coins/c.cost);
  if(afford<1)return none(`Не хватает монет на семена: ${c.name} — ${c.cost} мон. за грядку.`);
  const take=empty.slice(0,Math.min(MAX_PLOTS,afford));
  return {ok:true,machine,crop:c.id,replant:false,plots:take.map(o=>({id:o.id,revision:o.revision})),count:take.length,cost:take.length*c.cost,
   label:`${spec.name} · ${c.name} · ${take.length}`,why:''};
 }
 if(machine==='harvester'){
  const ripe=plots.filter(o=>o.crop&&GRAINS.includes(o.crop.id)&&o.crop.ready_at<=now);
  if(!ripe.length)return none('Нет готовых зерновых.');
  let take=ripe.slice(0,MAX_PLOTS),cost=0;
  if(replant){
   let coins=me.coins,kept=[];
   for(const o of take){const price=catalog.crops[o.crop.id]?.cost||0;if(coins<price)break;coins-=price;cost+=price;kept.push(o);}
   if(!kept.length)return none('Не хватает монет на повторный посев.');
   take=kept;
  }
  return {ok:true,machine,crop:'',replant:!!replant,plots:take.map(o=>({id:o.id,revision:o.revision})),count:take.length,cost,
   label:`${spec.name} · ${replant?'с пересевом':'уборка'} · ${take.length}`,why:''};
 }
 return none('Эта машина работает по сменам.');
}

/* «Repeat the run»: only a remembered successful machine run. Rebuild its plots from the current farm;
   selecting a seed must never invent a previous run. `seed` remains in the signature for existing callers. */
export function planRepeat(last,seed,me,catalog,now){
 const machine=last?.machine,mem=last?.[machine];
 if(!['tractor','harvester'].includes(machine)||!mem||!me.equipment?.[machine])
  return {ok:false,machine:'',plots:[],count:0,cost:0,label:'Повторить рейс',why:'Сначала выполни рейс трактором или комбайном.'};
 const run=machine==='tractor'?{machine,crop:mem.crop,replant:false}:{machine,crop:'',replant:mem.replant!==false};
 return planMachine(run,me,catalog,now);
}

/* A machine tapped on the scene: repeat its remembered run, or ask (null) when it has never been run. */
export function planTap(machine,last,me,catalog,now){
 const mem=last?.[machine];
 if(!mem)return null;
 return planMachine(machine==='tractor'?{machine,crop:mem.crop,replant:false}:{machine,crop:'',replant:mem.replant!==false},me,catalog,now);
}

/* Remember a successful run (returns a new object, never mutates). */
export function remember(last,run){
 const next={...(last||{}),machine:run.machine};
 next[run.machine]=run.machine==='tractor'?{crop:run.crop}:{replant:!!run.replant};
 return next;
}
