// Фруктовый сад (docs/tasks/FARM_ORCHARD.md). Правила считает сервер (qw_farm/orchard.py, S.me.orchard_view, S.catalog.orchard);
// этот модуль только превращает снимок фермы в строки интерфейса и собирает команды plant_tree / tree_care / harvest.
// Ничего здесь не меняет склад, монеты или время: всё это проверяет сервер ещё раз.
export const STAGE_NAME={sapling:'Саженец',young:'Молодое дерево',adult:'Взрослое дерево',elder:'Старожил',century:'Вековое дерево'};
export const isTree=o=>!!o&&o.type==='tree';
export const view=me=>me?.orchard_view||null;
// Rent values are read from the owner snapshot, which uses the server's upkeep rules.
export const rentSummary=v=>v?{next:v.tree_rent_next||0,total:v.tree_rent_total||0,freeCount:v.tree_rent_free_count||0}:null;
export const rules=catalog=>catalog?.orchard?.rules||{cycle:86400,young:5,adult:20,century:100,prune_every:7,birdhouse_radius:2,help_pct:20,discount_pct:25,gold_permille:[20,40]};
export const ripe=(o,t)=>isTree(o)&&!!o.fruit&&o.fruit.ready_at<=t;
export const readyCount=(objects,t)=>(objects||[]).filter(o=>ripe(o,t)).length;
export const species=(catalog,o)=>catalog?.orchard?.trees?.[o?.species]||null;
export const treeName=(catalog,o)=>species(catalog,o)?.name||'Дерево';
export const lookName=(catalog,look)=>Object.values(catalog?.orchard?.grafts||{}).find(g=>g.look===look)?.name||null;
export function plural(n,one,few,many){const a=Math.abs(n)%100,b=a%10;return a>10&&a<20?many:b===1?one:b>1&&b<5?few:many;}
export const gardenYears=n=>`${n} ${plural(n,'садовый год','садовых года','садовых лет')}`;
// First harvest: juvenile + 1 cycles of 20 hours.
export const firstHarvestSeconds=(catalog,id)=>((catalog?.orchard?.trees?.[id]?.juvenile??0)+1)*rules(catalog).cycle;
// The stage by the harvest next in line, exactly as qw_farm/orchard.py stage(): 0 harvests sapling, then young / adult / elder / century.
export function treeStage(harvests,r={young:5,adult:20,century:100}){
 const n=(harvests||0)+1;
 return !harvests?'sapling':n<=r.young?'young':n<=r.adult?'adult':n>=r.century?'century':'elder';
}
// What the drawing shows (view only, never a rule): the stage, the cycle phase by the share of the cycle that has passed
// (bloom 0-25%, set 25-70%, fill 70-100%, ripe; FARM_ORCHARD.md 2.2) and, for a sapling, how far the young stem has grown.
// The first cycle of a sapling lasts juvenile + 1 garden years: the stem grows first, the last year blooms and bears like a tree.
// A visitor's snapshot has no started_at: the start is the planned length back from ready_at.
export function treeLook(catalog,o,t){
 const r=rules(catalog),stage=treeStage(o?.harvests,r),f=o?.fruit||null;
 if(!f)return {stage,phase:'rest',grow:1,k:0};
 const years=stage==='sapling'?(species(catalog,o)?.juvenile??2)+1:1,from=f.started_at??(f.ready_at-years*r.cycle);
 if(f.ready_at<=t)return {stage,phase:'ripe',grow:1,k:1};
 const g=Math.max(0,Math.min(1,(t-from)/Math.max(1,f.ready_at-from)));
 let cycle=g,grow=1;
 if(years>1){const last=1/years;if(g<1-last)return {stage,phase:'grow',grow:g/(1-last),k:0};cycle=(g-(1-last))/last}
 const phase=cycle<.25?'bloom':cycle<.7?'set':'fill';
 return {stage,phase,grow,k:phase==='fill'?(cycle-.7)/.3:phase==='set'?(cycle-.25)/.45:cycle/.25};
}
export function stageNote(stage){
 return {sapling:'Пока растёт, плодов нет. Заяц Поливай и соседи могут ускорить.',young:'Урожай небольшой, но он растёт с годами.',
  adult:'Плодоносит в полную силу. Шанс золотого плода — «Молодильное яблочко».',elder:'Старожил: урожай ещё богаче.',century:'Вековое дерево: золотой плод вдвое чаще.'}[stage]||'';
}
// What the card of a tree shows. ``info`` is orchard_view.trees[id] (owner only); a guest gets just the look and the timer.
export function treeFacts(catalog,o,info,t,infusion=0,grafts={}){
 const spec=species(catalog,o)||{},f=o.fruit||null,mine=!!info;
 const stage=info?.stage||(o.harvests===0?'sapling':'adult'),goldenPct=mine?info.golden_permille/10:0;
 const ownGrafts=Object.entries(grafts).filter(([id])=>catalog?.orchard?.grafts?.[id]?.species===o.species).map(([id,qty])=>({id,qty,name:catalog.orchard.grafts[id].name,same:catalog.orchard.grafts[id].look===o.look}));
 return {
  name:spec.name||'Дерево',fruit:spec.fruit||null,stage,stageName:STAGE_NAME[stage]||'',ripe:!!f&&f.ready_at<=t,readyAt:f?f.ready_at:null,
  qty:mine?info.qty:null,nextYield:mine?info.next_yield:null,goldenPct,age:mine?info.age:null,harvests:o.harvests,
  pest:mine&&info.pest?(catalog.orchard.pests.find(p=>p.id===info.pest)?.name||'Вредитель'):null,pestActive:mine&&!!info.pest_active,bird:mine&&!!info.bird,
  canSpray:mine&&!!info.pest_active&&infusion>0,sprayWhy:!mine?'':!info.pest_active?'Вредителей нет':infusion>0?'':'Нужен садовый настой',
  dry:mine&&!!info.dry,look:o.look||null,lookName:lookName(catalog,o.look),grafts:ownGrafts,helped:!!f?.helped
 };
}
// Rows of the catalogue section «Деревья»: every species by level, with the price the player would pay for it right now.
export function saplingRows(catalog,me,v){
 const orchard=catalog?.orchard;if(!orchard||!me)return [];
 const free=v?.vouchers||{},discounts=v?.discounts||{};
 return Object.values(orchard.trees).sort((a,b)=>a.level-b.level).map(sp=>{
  const locked=me.level<sp.level,first=firstHarvestSeconds(catalog,sp.id),cut=orchard.rules.discount_pct;
  const options=[];
  if(free[sp.id])options.push({voucher:'free',label:'Бесплатный саженец от Филиныча',price:0,qty:free[sp.id]});
  for(const [id,qty] of Object.entries(discounts))options.push({voucher:id,label:`${catalog.items?.[id]?.name||'Талон'} −${cut}%`,price:Math.floor(sp.cost*(100-cut)/100),qty});
  options.push({voucher:null,label:'За монеты',price:sp.cost,qty:null});
  const why=locked?`С ${sp.level} уровня`:'';
  return {...sp,locked,first,options,blocked:why,free:free[sp.id]||0};
 });
}
export function plantSpec(row,option,catalog){
 return {id:'tree:'+row.id,name:row.sapling,cost:option.price,level:row.level,w:1,h:1,tree:{species:row.id,voucher:option.voucher},fruit:row.fruit};
}
export const plantCommand=(spec,cell)=>['plant_tree',{species:spec.tree.species,x:cell.x,y:cell.y,voucher:spec.tree.voucher}];
export const careCommand=(o,action,item=null)=>['tree_care',{object:o.id,action,item}];
// Uprooting: inside the undo window the whole price comes back; later only wood (the client asks first).
export function uprootText(catalog,o,t,undoWindow=60){
 const name=treeName(catalog,o),wood=2;   // TREE_REFUND_WOOD
 if(t-o.planted_at<=undoWindow)return {early:true,text:`Саженец «${name}» вернётся полностью: ${o.cost?`+${o.cost} монет`:'талон останется у тебя'}.`};
 return {early:false,text:`${name} будет выкорчевана. Вернётся только древесина ×${wood}; созревший урожай сначала соберётся на склад.`};
}
export const treeSummary=(catalog,objects)=>{
 const out={};for(const o of objects||[])if(isTree(o))out[o.species]=(out[o.species]||0)+1;
 return Object.entries(out).map(([id,n])=>`${catalog?.orchard?.trees?.[id]?.name||id} ×${n}`).join(', ');
};
// Discoverability after fruit left the beds: the «Деревья» section of the catalogue, the «Сад» counter in the farm menu, the one-time notice and the level-up line.
// Saplings waiting to be planted: free ones of open species plus discount talons. Only free cells limit planting, the server checks them.
export function pendingCount(v,me,catalog){
 if(!v||!me)return 0;
 const trees=catalog?.orchard?.trees||{},open=sp=>!!trees[sp]&&trees[sp].level<=me.level;
 const free=Object.entries(v.vouchers||{}).reduce((n,[sp,q])=>n+(open(sp)?q:0),0);
 const talons=Object.keys(trees).some(open)?Object.values(v.discounts||{}).reduce((n,q)=>n+q,0):0;
 return free+talons;
}
// Species that open on a level-up from ``from`` to ``to``: from < level <= to.
export const treeUnlocks=(catalog,from,to)=>Object.values(catalog?.orchard?.trees||{}).filter(t=>t.level>from&&t.level<=to).sort((a,b)=>a.level-b.level);
export function unlockText(list){
 const names=list.map(t=>`«${t.name}»`).join(', ');
 return list.length>1?`Открылись деревья ${names}: их сажают из ленты, «Всё» → «Деревья».`:`Открылось дерево ${names}: его сажают из ленты, «Всё» → «Деревья».`;
}
// The farm had fruit on beds before the orchard: the server granted compensation saplings (qw_farm/orchard.py upgrade, ``granted``).
export const movedNotice=v=>Array.isArray(v?.granted)&&v.granted.length>0;
export const MOVED_TEXT='Фруктовые деревья переехали в Сад: там твои саженцы и талоны';
export const OPEN_LABEL='Открыть Сад';
