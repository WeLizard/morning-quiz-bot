// Version 1 of the «Битва с Сантой» battle, a line-by-line mirror of domain/farm_santa_battle.py.
// Integers only; the plan comes from the server, the client plays locally and sends the whole log at the end.
export const VERSION=1,TTL=900,MAX_ROUNDS=30,MAX_ITEMS=3,MAX_LOG=120,BAR_MS=1200,ZONE_MS=260;
export const HEROES=['player','ded_moroz','snegurochka'],ENEMIES=['krampus','santa'];
export const HERO_HP={player:100,ded_moroz:140,snegurochka:90};
export const BATTLES={
 1:{enemies:{krampus:160},power:260,par:4,reindeer:false},
 2:{enemies:{santa:240},power:215,par:7,reindeer:false},
 3:{enemies:{krampus:150,santa:210},power:100,par:11,reindeer:true},
};
export const ATTACKS={snowball:['player',12],staff:['ded_moroz',18],icestar:['snegurochka',10]};
export const BLIZZARD=10;
export const SKILLS={wall:['player',3],blizzard:['ded_moroz',2],freeze:['snegurochka',3],song:['snegurochka',3]};
export const SONG_HEAL=15;
export const ITEMS={pie:50,pancake:25,gingerbread:20,tea:10,honey:0};
export const SWITCH=24,COAL=28,HOHOHO=15,CANDY=20,REINDEER=12,ROAR_ROUNDS=2;

const has=(object,key)=>Object.prototype.hasOwnProperty.call(object,key);

export function newState(plan){
 const spec=BATTLES[plan.battle];
 const enemies=ENEMIES.filter(e=>has(spec.enemies,e));
 const hp={};
 for(const h of HEROES)hp[h]=HERO_HP[h];
 for(const e of enemies)hp[e]=spec.enemies[e];
 const cd={},er={};
 for(const s of Object.keys(SKILLS))cd[s]=0;
 for(const e of enemies)er[e]=0;
 const state={battle:plan.battle,round:1,hp,max:{...hp},enemies,cd,chain:[],frozen:[],sack:false,rage:0,wall:false,honey:[],
  items:{},n_items:0,bar:0,tk:0,gk:0,er,intents:{},turn:0,outcome:null};
 startRound(plan,state);
 return state;
}

export function alive(state,ids){return ids.filter(i=>state.hp[i]>0);}

function pickTarget(plan,state){
 const living=alive(state,HEROES);
 const k=plan.targets[state.tk%plan.targets.length];
 state.tk+=1;
 return living[k%living.length];
}

function intent(plan,state,enemy){
 state.er[enemy]+=1;
 const r=state.er[enemy];
 if(enemy==='krampus'){
  if(r%3===0)return {move:'chain',target:pickTarget(plan,state)};
  if(r%4===2&&state.rage===0)return {move:'roar',target:null};
  return {move:'switch',target:pickTarget(plan,state)};
 }
 if(r%4===0)return {move:'sack',target:null};
 if(r%2===1){
  const gift=plan.gifts[state.gk%plan.gifts.length];
  state.gk+=1;
  if(gift&&state.hp.santa<state.max.santa)return {move:'candy',target:null};
  return {move:'coal',target:pickTarget(plan,state)};
 }
 return {move:'hohoho',target:null};
}

function newIntents(plan,state){
 const intents={};
 for(const e of alive(state,state.enemies))intents[e]=intent(plan,state,e);
 return intents;
}

function startRound(plan,state){
 state.intents=newIntents(plan,state);
 state.turn=0;
 skipToActor(plan,state,[]);
}

// The hero whose move is awaited, or null when the battle is over.
export function actor(state){return state.outcome?null:HEROES[state.turn];}

// Moves the awaited hero may make: [[action,[targets]]] (an empty target list = no target).
export function legal(state){
 const hero=actor(state);
 if(hero===null)return [];
 const enemies=alive(state,state.enemies),heroes=alive(state,HEROES);
 const moves=Object.entries(ATTACKS).filter(([,[h]])=>h===hero).map(([a])=>[a,enemies]);
 for(const [skill,[h]] of Object.entries(SKILLS)){
  if(h===hero&&state.cd[skill]===0)moves.push([skill,skill==='freeze'?enemies:[]]);
 }
 if(state.n_items<MAX_ITEMS){
  for(const item of Object.keys(ITEMS))moves.push([item,item==='gingerbread'?[]:heroes]);
 }
 return moves;
}

function bar(plan,state,press){
 const zone=plan.zones[state.bar%plan.zones.length];
 state.bar+=1;
 return press!==null&&zone[0]<=press&&press<=zone[1];
}

function hitEnemy(state,enemy,amount,events,by,bonus){
 if(enemy==='santa'&&state.sack){
  state.sack=false;
  events.push({t:'miss',by,to:enemy,why:'sack'});
  return;
 }
 state.hp[enemy]=Math.max(0,state.hp[enemy]-amount);
 events.push({t:'hit',by,to:enemy,amount,bonus});
 if(state.hp[enemy]===0)events.push({t:'down',who:enemy});
}

function hitHero(state,hero,amount,events,by){
 amount=Math.floor(amount*BATTLES[state.battle].power/100);
 if(state.rage&&by==='krampus')amount=Math.floor(amount*13/10);
 if(state.wall)amount=Math.floor(amount/2);
 state.hp[hero]=Math.max(0,state.hp[hero]-amount);
 events.push({t:'hit',by,to:hero,amount,bonus:false});
 if(state.hp[hero]===0){
  events.push({t:'down',who:hero});
  remove(state.chain,hero);
 }
}

function heal(state,who,amount,events,by){
 if(state.hp[who]===0)return;
 const got=Math.min(amount,state.max[who]-state.hp[who]);
 state.hp[who]+=got;
 events.push({t:'heal',by,to:who,amount:got});
}

function remove(list,item){const i=list.indexOf(item);if(i>=0)list.splice(i,1);}

function checkEnd(state){
 if(!alive(state,state.enemies).length)state.outcome='win';
 else if(!alive(state,HEROES).length)state.outcome='lose';
 return state.outcome!==null;
}

function fail(why){throw new Error(why);}

// Apply one hero move; then run the enemy phase when the round's heroes are done. Returns the events.
export function act(plan,state,entry){
 if(state.outcome)fail('over');
 if(!Array.isArray(entry)||entry.length!==4)fail('entry');
 const [hero,action,target,press]=entry;
 if(hero!==actor(state))fail('actor');
 if(press!==null&&(!Number.isInteger(press)||press<0||press>BAR_MS))fail('press');
 const move=legal(state).find(m=>m[0]===action);
 if(!move)fail('action');
 if(move[1].length){
  if(!move[1].includes(target))fail('target');
 }else if(target!==null)fail('target');
 const events=[];
 if(has(ATTACKS,action)||action==='blizzard'){
  const bonus=bar(plan,state,press);
  const base=action==='blizzard'?BLIZZARD:ATTACKS[action][1];
  let amount=bonus?Math.floor(base*3/2):base;
  if(state.honey.includes(hero)){
   remove(state.honey,hero);
   amount*=2;
  }
  for(const enemy of (action==='blizzard'?alive(state,state.enemies):[target]))hitEnemy(state,enemy,amount,events,hero,bonus);
 }else if(press!==null)fail('press');
 else if(action==='wall'){
  state.wall=true;
  events.push({t:'wall',by:hero});
 }else if(action==='freeze'){
  if(!state.frozen.includes(target))state.frozen.push(target);
  events.push({t:'freeze',by:hero,to:target});
 }else if(action==='song'){
  for(const h of alive(state,HEROES))heal(state,h,SONG_HEAL,events,hero);
 }else{
  state.n_items+=1;
  state.items[action]=(state.items[action]||0)+1;
  events.push({t:'item',by:hero,item:action,to:target});
  if(action==='gingerbread'){
   for(const h of alive(state,HEROES))heal(state,h,ITEMS[action],events,hero);
  }else if(action==='tea'){
   remove(state.chain,target);
   heal(state,target,ITEMS[action],events,hero);
  }else if(action==='honey'){
   if(!state.honey.includes(target))state.honey.push(target);
  }else heal(state,target,ITEMS[action],events,hero);
 }
 if(has(SKILLS,action))state.cd[action]=SKILLS[action][1];
 if(checkEnd(state))return events;
 state.turn+=1;
 skipToActor(plan,state,events);
 return events;
}

// Move turn to the next hero who can act; when none is left, run the enemy phase and start the next round.
function skipToActor(plan,state,events){
 while(!state.outcome){
  while(state.turn<HEROES.length){
   const hero=HEROES[state.turn];
   if(state.hp[hero]>0&&!state.chain.includes(hero))return;
   if(state.chain.includes(hero)&&state.hp[hero]>0){
    remove(state.chain,hero);
    events.push({t:'skip',who:hero,why:'chain'});
   }
   state.turn+=1;
  }
  enemyPhase(plan,state,events);
  if(checkEnd(state))return;
  state.round+=1;
  if(state.round>MAX_ROUNDS){
   state.outcome='lose';
   events.push({t:'timeout'});
   return;
  }
  state.intents=newIntents(plan,state);
  state.turn=0;
  events.push({t:'round',n:state.round});
 }
}

function enemyPhase(plan,state,events){
 for(const enemy of alive(state,state.enemies)){
  const plannedMove=state.intents[enemy];
  if(plannedMove===undefined)continue;
  if(state.frozen.includes(enemy)){
   remove(state.frozen,enemy);
   events.push({t:'skip',who:enemy,why:'freeze'});
   continue;
  }
  const move=plannedMove.move;
  let target=plannedMove.target;
  if(target!==null&&state.hp[target]===0)target=alive(state,HEROES).length?pickTarget(plan,state):null;
  events.push({t:'move',who:enemy,move,to:target});
  if(move==='switch')hitHero(state,target,SWITCH,events,enemy);
  else if(move==='chain'){if(!state.chain.includes(target))state.chain.push(target);}
  else if(move==='roar')state.rage=ROAR_ROUNDS+1;
  else if(move==='coal')hitHero(state,target,COAL,events,enemy);
  else if(move==='hohoho'){for(const h of alive(state,HEROES))hitHero(state,h,HOHOHO,events,enemy);}
  else if(move==='candy')heal(state,'santa',CANDY,events,enemy);
  else if(move==='sack')state.sack=true;
  if(checkEnd(state))return;
 }
 if(BATTLES[state.battle].reindeer&&state.round%4===0){
  events.push({t:'move',who:'reindeer',move:'sleigh',to:null});
  for(const h of alive(state,HEROES))hitHero(state,h,REINDEER,events,'reindeer');
  if(checkEnd(state))return;
 }
 state.wall=false;
 state.frozen=state.frozen.filter(e=>state.hp[e]>0);
 state.rage=Math.max(0,state.rage-1);
 for(const skill of Object.keys(state.cd))state.cd[skill]=Math.max(0,state.cd[skill]-1);
}

export function stars(state){
 if(state.outcome!=='win')return 0;
 if(HEROES.some(h=>state.hp[h]===0))return 1;
 return state.round<=BATTLES[state.battle].par?3:2;
}

// Replay a whole log; throws for a malformed or illegal log or one that does not finish the battle.
export function replay(plan,log){
 if(!Array.isArray(log)||!log.length||log.length>MAX_LOG)fail('log');
 const state=newState(plan);
 for(const entry of log)act(plan,state,entry);
 if(state.outcome===null)fail('unfinished');
 return {outcome:state.outcome,rounds:state.round,stars:stars(state),items:state.items,hp:state.hp};
}
