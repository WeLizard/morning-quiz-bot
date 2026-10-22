/* Trip minigames: "Порыбачу сам" (cast, bite, strike, fight) and "Пойду сам" (short forest gathering). Server rules: qw_farm/trip_games.py.
 *
 * The first half is a 1:1 port of the pure rules (integers only, no hashing: the server ships the generated plan in trip.game.plan).
 * The client uses it to run the game and to build the log; the server replays the log itself and decides the reward.
 * Pure helpers come first and touch no DOM, so tests/js/farm_trip_game.test.cjs can run them in a bare vm context.
 * Fishing v2 (docs/tasks/FARM_TRIP_MINIGAMES.md §10): the fight is a 50 ms integer simulation over the fish's pull schedule.
 */
import {smallAnimal} from './scene_expansion.js';
export const FISH2={v:2,tick:50,fly:600,land_pause:1000,scare_pause:600,toggle_gap:40,max_toggles:200,rare_acc:800,
 fight:{d0:600,d_max:1000,t0:450,hold_base:200,hold_k:15,rel_k:5,up:5,down:6,reel:9,drag:8,run:4,tire_hold:4,tire_rel:1,floor:500,snap:1000,slack:60,slack_ticks:24,ticks:400},
 species:{crucian:{name:'Карась',rare:false,par:90},perch:{name:'Окунь',rare:false,par:150},pike:{name:'Щука',rare:false,par:200},
  golden_crucian:{name:'Золотой карась',rare:true,par:160},tench:{name:'Линь',rare:true,par:200},catfish:{name:'Сом',rare:true,par:260}},
 baits:{bread:{wait:70,rare:0,routes:null},corn:{wait:100,rare:40,routes:['pond_bank','lake_inlet']},crucian:{wait:90,rare:50,routes:['river_bend']}},
 routes:{pond_bank:{casts:4,window:900,rare:'golden_crucian',common:['crucian']},lake_inlet:{casts:4,window:800,rare:'tench',common:['perch','crucian']},
  river_bend:{casts:4,window:700,rare:'catfish',common:['pike','perch']}}};
export const RULES={ttl:900,bonus:250,mark_period:1600,dead_zone:60,acc_span:300,react:150,first_aim_ms:500,grid:6,trap_cost:2,step_cs:20,fish2:FISH2};
const DIRS={U:[0,-1],D:[0,1],L:[-1,0],R:[1,0]};
const idiv=(a,b)=>(a-a%b)/b;                       // exact integer division for non-negative integers
export const Q_AUTO=1000,MAX_MS=600000;
const F2=rules=>(rules&&rules.fish2)||FISH2;

/* ---------------------------------------------------------------- pure rules (see trip_games.py) */
export function markPosition(t,phase,rules=RULES,period=rules.mark_period){
 const m=(t+phase)%period,half=idiv(period,2);
 return m<=half?idiv(m*1000,half):idiv((period-m)*1000,half);
}
export function accuracy(aimMs,cast,rules=RULES,period=rules.mark_period){
 const d=Math.abs(markPosition(aimMs,cast.phase,rules,period)-cast.zone);
 return Math.max(0,1000-idiv(Math.max(0,d-rules.dead_zone)*1000,rules.acc_span));
}
export function baitSpec(bait,rules=RULES){const b=F2(rules).baits[bait];return b?[b.wait,b.rare]:[100,0];}
/** Absolute ms of the real bite (trip_games.bite_at). */
export function biteAt(plan,cast,aim,acc,baitWait,rules=RULES){return aim+F2(rules).fly+idiv(idiv(cast.wait*plan.wait_pct,100)*baitWait,100)+2*(1000-acc);}
/** Absolute ms of the false nibbles before the bite (visual only). */
export function nibbleTimes(plan,cast,aim,bite,rules=RULES){const fly=aim+F2(rules).fly;return cast.nibbles.map(n=>fly+idiv((bite-fly)*n,1000));}
export function strikeTiming(strike,bite,window,rules=RULES){
 const d=strike-bite;
 if(d<rules.react||d>rules.react+window)return 0;
 return 1000-idiv((d-rules.react)*500,window);
}
export function hookedFish(plan,cast,acc,rareAdd,rules=RULES){
 const rare=cast.fish[1];
 return rare&&acc>=F2(rules).rare_acc&&cast.roll<plan.rare_chance+rareAdd?rare:cast.fish[0];
}
export function fightStart(rules=RULES){const f=F2(rules).fight;return {t:f.t0,d:f.d0,s:1000,slack:0,seg:0,left:-1,k:0,end:'',pull:0};}
/** One 50 ms tick (trip_games.fight_step); sets st.end to land | snap | slack | escape. */
export function fightStep(st,fish,hold,rules=RULES){
 const f=F2(rules).fight,pulls=fish.pulls;
 if(st.left<=0){st.seg=(st.seg+(st.left===0?1:0))%pulls.length;st.left=pulls[st.seg][0];}
 const pull=pulls[st.seg][1];st.pull=pull;st.left--;
 const eff=idiv(pull*(f.floor+idiv(st.s*(1000-f.floor),1000)),1000);
 let target;
 if(hold){target=f.hold_base+f.hold_k*eff;st.d-=Math.max(0,f.reel-idiv(eff,f.drag));st.s=Math.max(0,st.s-f.tire_hold);}
 else{target=f.rel_k*eff;st.d+=idiv(eff,f.run);st.s=Math.max(0,st.s-f.tire_rel);}
 st.t+=Math.floor((target-st.t)/(target>st.t?f.up:f.down));
 st.k++;
 st.slack=st.t<f.slack?st.slack+1:0;
 if(st.t>=f.snap)st.end='snap';
 else if(st.slack>=f.slack_ticks)st.end='slack';
 else if(st.d<=0)st.end='land';
 else if(st.d>=f.d_max||st.k>=f.ticks)st.end='escape';
 return st;
}
/** Hold/release during tick k: holding from the strike, every toggle at or before the tick start flips it. */
export function holdAt(toggles,time){let n=0;for(const t of toggles){if(t<=time)n++;else break;}return n%2===0;}
/** The server counts at most max_toggles hold/release switches; past the cap a press or release changes nothing in the simulation. */
export function toggleRoom(toggles,rules=FISH2){return toggles.length<rules.max_toggles;}
export function fight(fish,strike,toggles,rules=RULES){
 const st=fightStart(rules),tick=F2(rules).tick;let hold=true,j=0;
 while(!st.end){const t=strike+st.k*tick;while(j<toggles.length&&toggles[j]<=t){hold=!hold;j++;}fightStep(st,fish,hold,rules);}
 return {end:st.end,ticks:st.k};
}
export const fightPoints=(ticks,par)=>1000-Math.min(300,idiv(Math.max(0,ticks-par)*300,par));
/** One cast (trip_games.eval_cast): {points, end, free, result, fish, acc}. */
export function evalCast(plan,cast,aim,strike,toggles,bait,rules=RULES){
 const f2=F2(rules),[baitWait,rareAdd]=baitSpec(bait,rules),acc=accuracy(aim,cast,rules,plan.mark_period),bite=biteAt(plan,cast,aim,acc,baitWait,rules),win=plan.window;
 if(strike===null){const end=bite+rules.react+win;return {points:0,end,free:end,result:'missed',fish:null,acc};}
 const timing=strikeTiming(strike,bite,win,rules);
 if(!timing){const early=strike<bite+rules.react;return {points:0,end:strike,free:early?strike+f2.scare_pause:Math.max(strike,bite+rules.react+win),result:early?'early':'missed',fish:null,acc};}
 const fish=hookedFish(plan,cast,acc,rareAdd,rules),r=fight(fish,strike,toggles,rules),end=strike+r.ticks*f2.tick;
 const points=r.end==='land'?idiv(3*acc+3*timing+4*fightPoints(r.ticks,f2.species[fish.id].par),10):idiv(3*acc+3*timing,20);
 return {points,end,free:end+f2.land_pause,result:r.end,fish,acc};
}
const ms=(v,lo=0)=>Number.isInteger(v)&&v>=lo&&v<=MAX_MS;
/** Replay of a v2 log (trip_games.fish_result) or null when it breaks the rules. */
export function fishResult(plan,log,rules=RULES){
 const f2=F2(rules);
 if(!log||typeof log!=='object'||Array.isArray(log)||Object.keys(log).sort().join()!=='bait,casts,v'||log.v!==f2.v)return null;
 const bait=log.bait,casts=log.casts;
 if(typeof bait!=='string'||!(bait===''||plan.baits.includes(bait)))return null;
 if(!Array.isArray(casts)||casts.length!==plan.casts.length)return null;
 let total=0,free=rules.first_aim_ms,end=0;const out=[];
 for(let i=0;i<casts.length;i++){
  const e=casts[i];if(!Array.isArray(e)||e.length!==3)return null;
  const [aim,strike,toggles]=e;
  if(!ms(aim,free))return null;
  if(strike!==null&&!(ms(strike)&&strike>aim))return null;
  if(!Array.isArray(toggles)||toggles.length>f2.max_toggles||(strike===null&&toggles.length))return null;
  let prev=strike;for(const t of toggles){if(!(ms(t)&&t>=prev+f2.toggle_gap))return null;prev=t;}
  const r=evalCast(plan,plan.casts[i],aim,strike,toggles,bait,rules);
  total+=r.points;free=r.free;end=r.end;out.push(r);
 }
 return {score:idiv(total,out.length),end,casts:out,catch:out.filter(r=>r.result==='land').map(r=>[r.fish.id,r.fish.g]),bait};
}
/** Permille score of a fishing log, or null. The client only plays v2 plans. */
export function fishScore(plan,log,rules=RULES){if(plan.v!==F2(rules).v)return null;const r=fishResult(plan,log,rules);return r?r.score:null;}
/** State of a forest walk: {cur, used, got, seen:Set, trapsHit} or null for an illegal path (same rules as forage_score). */
export function walk(plan,path){
 if(typeof path!=='string'||path.length>plan.budget)return null;
 const items=new Set(Object.keys(plan.items).map(Number)),traps=new Set(plan.traps);
 const st={cur:plan.start,used:0,got:0,seen:new Set([plan.start]),hit:0,items,traps};
 for(const ch of path){
  const d=DIRS[ch];if(!d||st.used>=plan.budget)return null;
  const x=st.cur%plan.w+d[0],y=idiv(st.cur,plan.w)+d[1];
  if(x<0||x>=plan.w||y<0||y>=plan.h)return null;
  st.cur=y*plan.w+x;st.used++;
  if(!st.seen.has(st.cur)){st.seen.add(st.cur);if(items.has(st.cur))st.got++;if(traps.has(st.cur)){st.used+=RULES.trap_cost;st.hit++;}}
 }
 return st;
}
export function forageScore(plan,path){const st=walk(plan,path);return st?Math.min(1000,idiv(1000*st.got,Math.max(1,plan.gold))):null;}
export const quality=(score,rules=RULES)=>Q_AUTO+idiv(rules.bonus*score,1000);
export function scaledOutputs(outputs,q){const r={};for(const [k,v] of Object.entries(outputs))r[k]=Math.max(v,idiv(v*q+500,1000));return r;}
export function finalOutputs(trip){return trip.game&&trip.game.state==='done'?scaledOutputs(trip.outputs,trip.game.q):{...trip.outputs};}
/** Seconds of the game window still open on the server clock. */
export const playLeft=(trip,serverNow)=>trip.game&&trip.game.state==='open'?trip.game.expires_at-serverNow:0;
export const canPlay=(trip,serverNow)=>!trip.guide&&!!trip.game&&trip.game.state==='open'&&playLeft(trip,serverNow)>5;

/* ---------------------------------------------------------------- texts */
const pct=permille=>(permille/10).toFixed(1).replace('.',',')+'%';
export const grams=g=>g>=1000?`${(g/1000).toFixed(1).replace('.',',')} кг`:`${g} г`;
const TOD_TEXT={dawn:'Рассвет',day:'День',dusk:'Вечерняя зорька',night:'Ночь'};
const WEATHER_TEXT={clear:'ясно',cloud:'облачно',rain:'дождик',wind:'ветер'};
/** One line about the sky of this trip and what it changes. */
export function skyLine(plan){
 const s=plan.sky||{tod:'day',weather:'clear'},bits=new Set();
 if(s.tod==='dawn'||s.tod==='dusk'||s.weather==='rain')bits.add('клюёт быстрее');
 if(s.tod==='night'||s.weather==='cloud')bits.add('редкая рыба смелее');
 if(s.weather==='wind')bits.add('прицел бежит быстрее');
 return `${TOD_TEXT[s.tod]||''} · ${WEATHER_TEXT[s.weather]||''}`+(bits.size?`: ${[...bits].join(', ')}`:'');
}
const BAIT_TEXT={'':'Без наживки',bread:'Хлебный мякиш',corn:'Кукуруза',crucian:'Живец'};
const BAIT_HINT={'':'как обычно',bread:'клюёт быстрее',corn:'чаще редкая рыба',crucian:'чаще редкая рыба'};
const RESULT_TEXT={snap:'Леска лопнула — держал слишком сильно.',slack:'Рыба сошла: леска провисла.',escape:'Рыба ушла и утянула леску.',
 early:'Рано — рыба испугалась.',missed:'Поклёвку пропустили.'};
function node(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
function btn(text,cls,fn){const b=node('button',cls,text);b.type='button';if(fn)b.onclick=fn;return b;}
const reducedMotion=()=>{try{return !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;}catch{return false;}};
const isNight=()=>document.documentElement.dataset.farmTheme==='night';
const mmss=sec=>{sec=Math.max(0,Math.ceil(sec));return `${Math.floor(sec/60)}:${String(sec%60).padStart(2,'0')}`;};
function rrect(g,x,y,w,h,r){g.beginPath();if(g.roundRect)g.roundRect(x,y,w,h,r);else g.rect(x,y,w,h);}
const goodsText=(outputs,name)=>Object.entries(outputs).map(([k,v])=>`${name(k)} ×${v}`).join(', ');
const extraText=(trip,name)=>{
 const base=trip.outputs,fin=finalOutputs(trip),extra=Object.entries(fin).filter(([k,v])=>v>base[k]).map(([k,v])=>`${name(k)} +${v-base[k]}`);
 return extra.join(', ');
};
export const bonusLine=(trip,name)=>{const e=extraText(trip,name);return e?`Бонус игры: ${e}`:'Как у автопилота';};

const LOOK={
 day:{grass:['#cfe3a8','#c5dc9d'],ink:'#26402d',tile:'#00000014',frame:'#5d6e5a'},
 night:{grass:['#2a3f33','#25392e'],ink:'#e4eedd',tile:'#ffffff14',frame:'#8fb59a'}
};
const look=()=>LOOK[isNight()?'night':'day'];

/** Draw one item (forest) or trap in the cell (x,y,s). Shape + colour + letter label, so it does not rely on colour alone. */
function drawItem(g,id,x,y,s,trap=false){
 const cx=x+s/2,cy=y+s/2,r=s*0.3;
 g.save();g.lineCap='round';g.lineJoin='round';
 const cap=(col,stem)=>{g.fillStyle=stem;g.fillRect(cx-r*0.28,cy,r*0.56,r*0.9);g.fillStyle=col;g.beginPath();g.ellipse(cx,cy,r*1.05,r*0.8,0,Math.PI,0);g.fill();};
 if(trap){
  cap('#c4372c','#f2ead6');g.fillStyle='#fff';for(const [dx,dy] of [[-0.5,-0.3],[0.2,-0.5],[0.55,-0.1]]){g.beginPath();g.arc(cx+dx*r,cy+dy*r,r*0.14,0,6.3);g.fill();}
  g.strokeStyle='#7a1d16';g.lineWidth=Math.max(2,s/16);g.beginPath();g.moveTo(x+s*0.12,y+s*0.12);g.lineTo(x+s*0.34,y+s*0.34);g.moveTo(x+s*0.34,y+s*0.12);g.lineTo(x+s*0.12,y+s*0.34);g.stroke();
 }else if(id==='wood'){
  g.fillStyle='#a47544';rrect(g,cx-r*1.1,cy-r*0.45,r*2.2,r*0.9,r*0.3);g.fill();g.fillStyle='#d9b27a';g.beginPath();g.ellipse(cx+r*1.0,cy,r*0.28,r*0.45,0,0,6.3);g.fill();g.strokeStyle='#7a5530';g.lineWidth=1.5;g.beginPath();g.moveTo(cx-r*0.8,cy-r*0.1);g.lineTo(cx+r*0.4,cy-r*0.1);g.stroke();
 }else if(id==='mushroom'){cap('#b9814f','#f2ead6');
 }else if(id==='chanterelle'){
  g.fillStyle='#f0a93a';g.beginPath();g.moveTo(cx-r*1.0,cy-r*0.5);g.quadraticCurveTo(cx,cy-r*1.0,cx+r*1.0,cy-r*0.5);g.lineTo(cx+r*0.3,cy+r*0.9);g.lineTo(cx-r*0.3,cy+r*0.9);g.closePath();g.fill();
 }else if(id==='wildberry'||id==='blackberry'){
  g.fillStyle=id==='wildberry'?'#d8344a':'#3b2a56';for(const [dx,dy] of [[-0.5,0.2],[0.5,0.2],[0,-0.5],[0,0.6]]){g.beginPath();g.arc(cx+dx*r,cy+dy*r,r*0.55,0,6.3);g.fill();}
  g.fillStyle='#4f8a3f';g.beginPath();g.ellipse(cx,cy-r*0.95,r*0.5,r*0.22,0.3,0,6.3);g.fill();
 }else if(id==='herbs'){
  g.strokeStyle='#3f8a4a';g.lineWidth=Math.max(2,s/14);for(const dx of [-0.6,0,0.6]){g.beginPath();g.moveTo(cx+dx*r*0.5,cy+r*0.9);g.quadraticCurveTo(cx+dx*r*1.4,cy,cx+dx*r*1.1,cy-r*0.9);g.stroke();}
 }else if(id==='hazelnut'){
  g.fillStyle='#9a6a3a';g.beginPath();g.ellipse(cx,cy+r*0.1,r*0.75,r*0.9,0,0,6.3);g.fill();g.fillStyle='#6b8f3a';g.beginPath();g.ellipse(cx,cy-r*0.6,r*0.8,r*0.45,0,Math.PI,0);g.fill();
 }else{g.fillStyle='#6aa84f';g.beginPath();g.arc(cx,cy,r*0.8,0,6.3);g.fill();}
 g.restore();
}

/* ---------------------------------------------------------------- lake art (farm palette: scene.js lake, treeSprite, lakeLife) */
const FISH_LOOK={
 crucian:{body:'#c1a86c',back:'#9c8754',fin:'#b98f4f',len:1,h:.52},
 perch:{body:'#a9bf86',back:'#6f8d5a',fin:'#d9784a',len:1,h:.42,stripes:true},
 pike:{body:'#9fb49a',back:'#5f7b63',fin:'#a9945a',len:1.5,h:.3,spots:true},
 golden_crucian:{body:'#ecc456',back:'#c99a33',fin:'#e0a03a',len:1.05,h:.55,glow:true},
 tench:{body:'#7f9a52',back:'#4f6a3a',fin:'#5d7340',len:1.1,h:.44,redEye:true},
 catfish:{body:'#7d776a',back:'#57524a',fin:'#6a6458',len:1.6,h:.36,whiskers:true}
};
/** A fish in the farm style: hull ellipse, back, tail and fins; ``under`` = a soft silhouette below the water. */
export function drawFishArt(g,id,x,y,size,dir=1,under=false,wiggle=0){
 const L=FISH_LOOK[id]||FISH_LOOK.crucian,len=size*L.len,hh=size*L.h;
 g.save();g.translate(x,y);g.scale(dir,1);g.rotate(wiggle*0.08);
 if(under){g.globalAlpha*=.5;g.fillStyle='#41686a';g.beginPath();g.ellipse(0,0,len/2,hh/2,0,0,6.3);g.fill();
  g.beginPath();g.moveTo(-len/2+2,0);g.lineTo(-len/2-len*.22,-hh*.45+wiggle*3);g.lineTo(-len/2-len*.22,hh*.45+wiggle*3);g.closePath();g.fill();g.restore();return;}
 if(L.glow){g.fillStyle='#ffe58a55';g.beginPath();g.ellipse(0,0,len*.66,hh*.95,0,0,6.3);g.fill();}
 g.lineJoin='round';
 g.fillStyle=L.fin;g.beginPath();g.moveTo(-len/2+3,0);g.lineTo(-len/2-len*.24,-hh*.5+wiggle*3);g.lineTo(-len/2-len*.16,0);g.lineTo(-len/2-len*.24,hh*.5+wiggle*3);g.closePath();g.fill();
 g.beginPath();g.moveTo(-len*.12,-hh*.42);g.quadraticCurveTo(len*.02,-hh*.95,len*.16,-hh*.42);g.closePath();g.fill();
 g.fillStyle=L.body;g.beginPath();g.ellipse(0,0,len/2,hh/2,0,0,6.3);g.fill();
 g.fillStyle=L.back;g.beginPath();g.ellipse(-len*.02,-hh*.2,len*.42,hh*.24,0,0,6.3);g.fill();
 g.fillStyle='#ffffff40';g.beginPath();g.ellipse(len*.02,hh*.18,len*.32,hh*.14,0,0,6.3);g.fill();
 if(L.stripes){g.strokeStyle='#4f6a45';g.lineWidth=Math.max(1.5,size*.05);for(const k of [-.18,.02,.2]){g.beginPath();g.moveTo(len*k,-hh*.42);g.lineTo(len*k-len*.03,hh*.25);g.stroke();}}
 if(L.spots){g.fillStyle='#e5dfaa';for(const [a,b] of [[-.25,-.05],[-.05,.1],[.12,-.08],[-.15,.15],[.25,.05]]){g.beginPath();g.arc(len*a,hh*b,Math.max(1.2,size*.035),0,6.3);g.fill();}}
 g.fillStyle=L.fin;g.beginPath();g.moveTo(len*.16,hh*.12);g.lineTo(len*.02,hh*.34);g.lineTo(len*.12,hh*.3);g.closePath();g.fill();
 g.strokeStyle=L.back;g.lineWidth=Math.max(1,size*.03);g.beginPath();g.moveTo(len*.3,-hh*.36);g.quadraticCurveTo(len*.22,0,len*.3,hh*.36);g.stroke();
 g.fillStyle=L.redEye?'#c4452f':'#fffef6';g.beginPath();g.arc(len*.37,-hh*.08,Math.max(1.6,size*.06),0,6.3);g.fill();
 g.fillStyle='#2b3a33';g.beginPath();g.arc(len*.38,-hh*.08,Math.max(.9,size*.032),0,6.3);g.fill();
 if(L.whiskers){g.strokeStyle='#4a463f';g.lineWidth=Math.max(1,size*.025);g.lineCap='round';for(const s of [-1,1]){g.beginPath();g.moveTo(len*.46,hh*.05);g.quadraticCurveTo(len*.62,hh*.1*s+hh*.2,len*.7,hh*.32*s+hh*.15);g.stroke();}}
 g.restore();
}
/** treeSprite of scene.js at an arbitrary origin and scale (same shapes and palette). */
function tree(g,x,y,s){
 g.save();g.translate(x,y);g.scale(s,s);
 g.strokeStyle='#9e8a60';g.lineWidth=4;g.lineCap='round';g.beginPath();g.moveTo(0,0);g.lineTo(0,-40);g.stroke();
 for(const [ex,ey,rx,ry,c] of [[0,-40,20,28,'#71976d'],[-7,-48,15,22,'#82a77a'],[6,-40,15,22,'#7da073'],[-4,-56,11,14,'#96b183']]){g.fillStyle=c;g.beginPath();g.ellipse(ex,ey,rx,ry,0,0,6.3);g.fill();}
 g.restore();
}
/** A thin painter so smallAnimal() of the farm scene can draw the swans and the duck on this canvas. */
function painter(g,time){
 return {c:g,time,
  ellipse(x,y,rx,ry,col){g.beginPath();g.ellipse(x,y,rx,ry,0,0,Math.PI*2);g.fillStyle=col;g.fill();},
  poly(pts,fill,stroke=null,w=1){g.beginPath();pts.forEach((p,i)=>i?g.lineTo(p.x,p.y):g.moveTo(p.x,p.y));g.closePath();if(fill){g.fillStyle=fill;g.fill();}if(stroke){g.strokeStyle=stroke;g.lineWidth=w;g.stroke();}},
  line(x1,y1,x2,y2,col,w=1){g.beginPath();g.moveTo(x1,y1);g.lineTo(x2,y2);g.strokeStyle=col;g.lineWidth=w;g.lineCap='round';g.stroke();},
  shadow(){}};
}
const SKY={dawn:['#f2d8c4','#f7ead3'],day:['#cfe4e4','#ecf2dd'],dusk:['#efc39b','#f5dfbf'],night:['#1d2c44','#33475e']};

const FISH_HELP='Забрось, когда кольцо над рыбой. Поплавок подрагивает — жди; ушёл под воду — жми «Подсечь!» и держи: катушка тянет. Шкала краснеет — отпусти, иначе леска лопнет. Отпустишь надолго — рыба уйдёт.';
const FORAGE_HELP='Тапни соседнюю клетку, чтобы сделать шаг, или дальнюю — пройду кратчайшим путём. Каждый шаг — из запаса. Мухомор отнимает ещё 2 шага. Собери как можно больше.';

/**
 * opts: {trip, route, rules (catalog.trip_games), serverNow(), itemName(id), timeText(sec),
 *        inventory {item: qty}, journal {species: {n, g}},
 *        onFinish(log) -> Promise<boolean>, tripNow() -> trip|null, onClose()}
 * Returns {close(), requestClose()}.
 */
export function openTripGame(opts){
 const trip=opts.trip,game=trip.game,plan=game.plan,fish=game.kind==='fish',rules={...RULES,...(opts.rules||{})},f2=F2(rules);
 if(fish&&plan.v!==f2.v)throw new Error('old fishing plan');
 const name=opts.itemName||(id=>id),speciesName=id=>f2.species[id]?.name||id;
 const prev=document.activeElement,inerted=[];
 let closed=false,done=false,sending=false,started=false,raf=0,confirming=false,srTimer=0,t0=0,layoutTimer=0;
 const root=node('div','fg-overlay tg-overlay');root.setAttribute('role','dialog');root.setAttribute('aria-modal','true');
 const title=fish?`Рыбалка: ${opts.route?.name||''}`:`Прогулка: ${opts.route?.name||''}`;root.setAttribute('aria-label',title);
 const top=node('div','fg-top'),head=node('strong','',title),timer=node('span','fg-timer'),close=btn('×','fg-close',()=>requestClose());
 close.setAttribute('aria-label','Закрыть игру');timer.title='Осталось на игру';
 top.append(head,timer,close);
 const stage=node('div','fg-stage'),canvas=node('canvas','fg-canvas');canvas.tabIndex=0;stage.append(canvas);
 const hud=node('div','fg-hud'),forecast=node('div','fg-forecast'),stat=node('div','fg-stat'),help=node('p','fg-help',fish?FISH_HELP:FORAGE_HELP),status=node('div','fg-status');
 status.setAttribute('role','status');hud.append(forecast,stat,help,status);
 const sr=node('div','fg-sr');sr.setAttribute('role','status');sr.setAttribute('aria-live','polite');
 const controls=node('div','fg-controls tg-controls');
 root.append(top,stage,hud,controls,sr);document.body.append(root);document.body.classList.add('fg-open');
 for(const el of [...document.body.children])if(el!==root&&!el.inert){el.inert=true;inerted.push(el);}
 let size={w:300,h:300,dpr:1,cell:40,left:0,top:0};
 const say=(text,bad=false)=>{status.textContent=text;status.classList.toggle('bad',bad);};
 const announce=text=>{clearTimeout(srTimer);srTimer=setTimeout(()=>{srTimer=0;if(!closed)sr.textContent=text;},500);};
 const tNow=()=>performance.now()-t0;
 const left=()=>Number.isFinite(game.expires_at)&&typeof opts.serverNow==='function'?game.expires_at-opts.serverNow():rules.ttl;
 const deadline=performance.now()+Math.max(0,left())*1000;
 const buzz=ms=>{try{if(!reducedMotion())navigator.vibrate?.(ms);}catch{}};

 /* ---- FISHING state */
 const casts=fish?plan.casts:[],log=[],results=[],journalBefore={...(opts.journal||{})};
 let ci=0,phase='aim',aimAt=0,strikeAt=null,freeAt=rules.first_aim_ms,resultUntil=0,last=null,bait='';
 let acc=0,bite=0,nibbles=[],bitten=false,nibbled=0,hooked=null,fst=null,toggles=[],holding=false,splash=[];
 /* ---- FORAGE state */
 let path='',queue=[],stepAt=0,st=fish?null:walk(plan,'');
 const pathLimit=plan.budget;

 const act=btn('','fg-act primary tg-big'),undo=btn('Шаг назад','fg-act'),fin=btn('Готово','fg-act primary'),skip=btn('Без игры','fg-act');
 controls.append(...(fish?[act]:[undo,fin]),skip);
 skip.onclick=()=>requestClose();
 skip.title='Закрыть игру: поездка продолжится как обычно, без бонуса (можно вернуться к игре, пока не вышло время)';

 function layout(){
  if(closed)return;
  const r=stage.getBoundingClientRect(),w=Math.max(120,Math.floor(r.width)),h=Math.max(120,Math.floor(r.height));
  const dpr=Math.min(2,window.devicePixelRatio||1,Math.sqrt(4e6/(w*h)));
  const pw=Math.floor(w*dpr),ph=Math.floor(h*dpr);if(canvas.width!==pw)canvas.width=pw;if(canvas.height!==ph)canvas.height=ph;
  const cell=Math.max(24,Math.min(Math.floor(w/plan.w||1),Math.floor(h/(plan.h||1)),80));
  size={w,h,dpr,cell,left:Math.floor((w-cell*(plan.w||1))/2),top:Math.floor((h-cell*(plan.h||1))/2)};
 }

 /* ---- FISHING flow: press = cast / strike / pull, release = give line */
 const cast=()=>casts[Math.min(ci,casts.length-1)];
 function fishPress(){
  if(done||sending||confirming||!started)return;
  const t=Math.round(tNow());
  if(phase==='aim'){
   if(t<freeAt)return;
   aimAt=t;strikeAt=null;phase='wait';bitten=false;nibbled=0;
   acc=accuracy(t,cast(),rules,plan.mark_period);bite=biteAt(plan,cast(),t,acc,baitSpec(bait,rules)[0],rules);nibbles=nibbleTimes(plan,cast(),t,bite,rules);
   buzz(10);say(acc>=800?'Точно в рыбное место! Жди поклёвку.':acc>0?'Рядом с рыбой. Жди поклёвку.':'Мимо рыбного места — ждать дольше.');announce('Заброс сделан.');paint();
  }else if(phase==='wait'){
   if(t<=aimAt+150)return;                         // an accidental double tap
   strikeAt=t;
   if(strikeTiming(t,bite,plan.window,rules)){
    hooked=hookedFish(plan,cast(),acc,baitSpec(bait,rules)[1],rules);fst=fightStart(rules);toggles=[];holding=true;phase='fight';
    buzz(25);say(f2.species[hooked.id].rare?'Тяжёлая! Похоже, редкая рыба. Держи и следи за шкалой.':'Засекла! Держи — тяни. Шкала краснеет — отпусти.');announce('Рыба на крючке.');paint();
   }else endCast();
  }else if(phase==='fight'&&!holding){if(toggle()){holding=true;paint();}else say('Леска уже не слушается рывков — просто смотри, чем всё кончится.');}
 }
 function fishRelease(){if(phase==='fight'&&holding&&!fst.end&&toggle()){holding=false;paint();}}
 function toggle(){
  const lastT=toggles.length?toggles[toggles.length-1]:strikeAt;
  if(!toggleRoom(toggles,f2))return false;
  // never earlier than a tick already simulated, never closer than the human gap to the previous toggle
  toggles.push(Math.max(Math.ceil(tNow()),lastT+f2.toggle_gap,strikeAt+(fst.k-1)*f2.tick+1));
  return true;
 }
 function endCast(){
  const entry=[aimAt,strikeAt,strikeAt===null?[]:toggles.slice()];
  const r=evalCast(plan,cast(),entry[0],entry[1],entry[2],bait,rules);
  log.push(entry);results.push(r);last=r;holding=false;
  freeAt=r.free;phase='result';resultUntil=Math.max(tNow()+1800,freeAt);
  if(r.result==='land'){const rare=f2.species[r.fish.id].rare;say(`${speciesName(r.fish.id)} · ${grams(r.fish.g)}${rare?' — редкая рыба!':''}`);buzz(rare?[30,60,30]:30);}
  else say(RESULT_TEXT[r.result]||'',true);
  announce(r.result==='land'?`Поймана: ${speciesName(r.fish.id)}, ${grams(r.fish.g)}`:RESULT_TEXT[r.result]);
  paint();
 }
 function fishTick(t){
  if(phase==='wait'){
   while(nibbled<nibbles.length&&t>=nibbles[nibbled]){nibbled++;buzz(8);}
   if(t>=bite&&!bitten){bitten=true;buzz(40);announce('Клюёт!');say('Клюёт! Подсекай!');paint();}
   if(t>bite+rules.react+plan.window){strikeAt=null;endCast();}
  }
  if(phase==='fight'){
   const before=fst.pull;
   while(!fst.end&&strikeAt+fst.k*f2.tick<=t){fightStep(fst,hooked,holdAt(toggles,strikeAt+fst.k*f2.tick),rules);}
   if(fst.pull>=50&&before<50)splash.push(t);
   if(fst.end)endCast();else paint();
  }
  if(phase==='result'&&t>=resultUntil){
   ci++;
   if(ci>=casts.length){phase='over';paint();submit({v:f2.v,bait,casts:log});}else{phase='aim';say('Следующий заброс: кольцо над рыбой — жми.');paint();}
  }
 }
 function paint(){
  if(fish){
   const sc=log.length?idiv(results.reduce((s,r)=>s+r.points,0),casts.length):0,caught=results.filter(r=>r.result==='land').length;
   stat.textContent=`Заброс ${Math.min(ci+1,casts.length)} из ${casts.length} · в садке: ${caught}`;
   forecast.textContent=log.length?`Прогноз: ${pct(quality(sc,rules))} от нормы`:`Бонус до +${pct(rules.bonus)} к улову`;
   const hot=phase==='fight'&&fst&&fst.t>=800;
   act.textContent=phase==='aim'?'Забросить':phase==='wait'?(bitten?'Подсечь!':'Жди поклёвку…'):phase==='fight'?(holding?(hot?'Отпусти!':'Тяни — держи'):'Тянуть: нажми и держи'):'…';
   act.classList.toggle('tg-hot',hot&&holding);act.classList.toggle('tg-hold',phase==='fight'&&holding);
   act.disabled=done||sending||phase==='result'||phase==='over'||!started||(phase==='aim'&&tNow()<freeAt);
  }else{
   st=walk(plan,path);const sc=forageScore(plan,path)||0;
   stat.textContent=`Шагов осталось: ${Math.max(0,plan.budget-st.used)} из ${plan.budget} · собрано: ${st.got}`+(st.hit?` · ловушек: ${st.hit}`:'');
   forecast.textContent=path.length?`Прогноз: ${pct(quality(sc,rules))} от нормы`:`Бонус до +${pct(rules.bonus)} к находкам`;
   undo.disabled=sending||done||!path.length;fin.disabled=sending||done||!path.length;
  }
 }

 /* ---- FORAGE flow */
 function tryStep(ch){
  if(done||sending||confirming)return false;
  const next=path+ch;if(next.length>pathLimit||!walk(plan,next)){return false;}
  path=next;paint();
  const s=walk(plan,path);announce(`Собрано ${s.got}, шагов осталось ${Math.max(0,plan.budget-s.used)}`);
  return true;
 }
 function cellOf(e){
  const r=canvas.getBoundingClientRect(),x=Math.floor((e.clientX-r.left-size.left)/size.cell),y=Math.floor((e.clientY-r.top-size.top)/size.cell);
  return x>=0&&x<plan.w&&y>=0&&y<plan.h?y*plan.w+x:-1;
 }
 function route(to){
  const s=walk(plan,path);if(!s||to===s.cur)return;
  const prevMap=new Map([[s.cur,null]]),todo=[s.cur];
  for(let i=0;i<todo.length&&!prevMap.has(to);i++){
   const c=todo[i];
   for(const ch of 'UDLR'){const d=DIRS[ch],x=c%plan.w+d[0],y=idiv(c,plan.w)+d[1];if(x<0||x>=plan.w||y<0||y>=plan.h)continue;const n=y*plan.w+x;if(s.traps.has(n)&&n!==to)continue;if(!prevMap.has(n)){prevMap.set(n,[c,ch]);todo.push(n);}}
  }
  const chars=[];for(let k=to;prevMap.get(k);k=prevMap.get(k)[0])chars.push(prevMap.get(k)[1]);
  chars.reverse();
  if(!prevMap.has(to)){say('Туда не пройти, не наступив на мухомор.',true);return;}
  if(!walk(plan,path+chars.join(''))){say('Не хватит шагов, чтобы дойти.',true);return;}
  queue=chars;say('');
 }
 function undoStep(){if(done||sending||!path.length)return;queue=[];path=path.slice(0,-1);paint();}
 function onKey(e){
  if(closed||e.ctrlKey||e.metaKey||e.altKey)return;
  if(e.code==='Escape'){e.preventDefault();e.stopPropagation();if(confirming)cancelClose();else requestClose();return;}
  if(confirming||done)return;
  if(e.code==='Tab'){const scope=root.querySelector('.fg-confirm')||root.querySelector('.fg-result')||root,items=[...scope.querySelectorAll('button:not(:disabled),canvas')];
   if(items.length){const i=items.indexOf(document.activeElement),n=e.shiftKey?(i<=0?items.length-1:i-1):(i<0||i>=items.length-1?0:i+1);e.preventDefault();e.stopPropagation();items[n].focus();}return;}
  if(fish){
   const other=document.activeElement&&document.activeElement.tagName==='BUTTON'&&document.activeElement!==act;
   if((e.code==='Space'||e.code==='Enter')&&!other&&started){e.preventDefault();e.stopPropagation();if(!e.repeat)fishPress();}
   return;
  }
  const KEYS={ArrowUp:'U',KeyW:'U',ArrowDown:'D',KeyS:'D',ArrowLeft:'L',KeyA:'L',ArrowRight:'R',KeyD:'R'};
  if(KEYS[e.code]){e.preventDefault();e.stopPropagation();queue=[];tryStep(KEYS[e.code]);}
  else if(e.code==='Backspace'||e.code==='KeyZ'){e.preventDefault();e.stopPropagation();undoStep();}
 }
 function onKeyUp(e){if(closed||!fish)return;if(e.code==='Space'||e.code==='Enter'){if(phase==='fight')e.preventDefault();fishRelease();}}
 const onHide=()=>{if(document.hidden)fishRelease();};
 window.addEventListener('keydown',onKey,true);window.addEventListener('keyup',onKeyUp,true);
 if(fish){document.addEventListener('visibilitychange',onHide);window.addEventListener('blur',fishRelease);}
 const holdTarget=el=>{
  el.addEventListener('pointerdown',e=>{if(e.button>0)return;e.preventDefault();try{el.setPointerCapture?.(e.pointerId);}catch{}canvas.focus({preventScroll:true});fishPress();});
  for(const ev of ['pointerup','pointercancel','lostpointercapture'])el.addEventListener(ev,()=>fishRelease());
  el.addEventListener('contextmenu',e=>e.preventDefault());
 };
 if(fish){holdTarget(canvas);holdTarget(act);}
 else canvas.onpointerdown=e=>{
  canvas.focus({preventScroll:true});
  if(done||confirming||sending||!started)return;
  const c=cellOf(e);if(c<0)return;
  const s=walk(plan,path),dx=c%plan.w-s.cur%plan.w,dy=idiv(c,plan.w)-idiv(s.cur,plan.w);
  if(Math.abs(dx)+Math.abs(dy)===1){queue=[];if(!tryStep(dx>0?'R':dx<0?'L':dy>0?'D':'U'))say('Шаги закончились.',true);else say('');}
  else route(c);
 };
 undo.onclick=()=>undoStep();
 fin.onclick=()=>submit(path);

 /* ---- sending / closing */
 async function submit(payload){
  if(sending||done||closed)return;
  sending=true;paint();
  if(!fish){
   // the server wants >= step_cs/100 s per step since the start of the trip (whole-second clock)
   const el=typeof opts.serverNow==='function'?opts.serverNow()-trip.started_at:1e9,need=(rules.step_cs/100*payload.length+2-el)*1000;
   if(need>0){say(`Сдаём… ещё ${Math.ceil(need/1000)} с`);await new Promise(r=>setTimeout(r,need));}
   if(closed)return;
  }
  let ok=false;try{ok=await opts.onFinish(payload);}catch{ok=false;}
  sending=false;if(closed)return;
  if(!ok){
   const t=opts.tripNow?.();
   if(!t||!t.game||t.game.state!=='open'){done=true;showNote('Игра уже закрыта','Эта поездка уже собрана или игра сыграна. Закрой окно и обнови раздел.');return;}
   if(performance.now()>=deadline-1500){done=true;showNote('Время вышло','Окно мини-игры закрылось. Поездка идёт как обычно, без бонуса.');return;}
   if(fish){say('Не получилось отправить запись. Нажми «Повторить».',true);act.textContent='Повторить отправку';act.disabled=false;act.onclick=()=>{act.onclick=null;submit(payload);};}
   else say('Не получилось отправить. Нажми «Готово» ещё раз.',true);
   if(!fish)paint();return;
  }
  done=true;showResult();
 }
 function showResult(){
  const t=opts.tripNow?.()||trip,tg=t.game&&t.game.state==='done'?t.game:null,box=node('div','fg-result');
  const local=fish?fishResult(plan,{v:f2.v,bait,casts:log},rules):null;
  const score=tg?tg.score:(fish?local?.score:forageScore(plan,path))||0,q=tg?tg.q:quality(score,rules);
  box.append(node('h2','',fish?'Рыбалка сыграна':'Прогулка сыграна'),node('p','fg-line',`Оценка ${pct(score)} · добыча ×${(q/1000).toFixed(2).replace('.',',')} от нормы`));
  if(fish){
   const catchList=tg?.catch||local?.catch||[];
   const list=node('ul','tg-catch');
   if(!catchList.length)list.append(node('li','fg-compare','Сегодня в садке пусто — но улов поездки не пропадёт.'));
   const fresh=new Set(catchList.map(([id])=>id).filter(id=>!journalBefore[id]));
   for(const [id,g] of catchList){const li=node('li',f2.species[id]?.rare?'rare':'',`${speciesName(id)} · ${grams(g)}`);if(fresh.delete(id))li.append(node('span','tg-new',' новое в журнале'));list.append(li);}
   box.append(list);
  }
  const extra=extraText({outputs:trip.outputs,game:{state:'done',q}},name);
  box.append(node('p',extra?'fg-proud':'fg-compare',extra?`Сам справился: ${extra}`:q>1000?'Прибавка пока меньше одного предмета: точнее — будет больше!':'Как у автопилота. В следующий раз получится лучше!'));
  box.append(node('p','fg-compare',`Время поездки не изменилось. Вернись за добычей, когда таймер дойдёт до нуля.`),btn('Готово','primary wide',()=>finishClose()));
  root.append(box);box.querySelector('button.primary').focus();
 }
 function showNote(head,text){
  root.querySelector('.fg-result')?.remove();
  const box=node('div','fg-result');box.setAttribute('role','alertdialog');box.append(node('h2','',head),node('p','',text),btn('Закрыть','primary wide',()=>finishClose()));root.append(box);box.querySelector('button').focus();
 }
 function requestClose(){
  if(closed)return;
  if(done||!started||(fish?!log.length&&phase==='aim':!path.length)){finishClose();return;}
  if(confirming)return;
  fishRelease();confirming=true;
  const box=node('div','fg-confirm');box.setAttribute('role','alertdialog');box.setAttribute('aria-modal','true');box.setAttribute('aria-label','Выйти из игры?');
  box.append(node('h2','','Выйти из игры?'),node('p','','Результат не засчитается: поездка пойдёт как обычно, без бонуса. Сыграть заново нельзя после отправки, но пока не вышло время — можно вернуться.'),
   btn('Продолжить','primary wide',()=>cancelClose()),btn('Выйти','secondary wide',()=>finishClose()));
  root.append(box);box.querySelector('button').focus();
 }
 function cancelClose(){root.querySelector('.fg-confirm')?.remove();confirming=false;canvas.focus({preventScroll:true});}
 // Back (Telegram BackButton, browser back) goes through the same confirmation as Escape. Returns true when the game closed, false when the player stays.
 function backClose(){if(closed)return true;if(confirming){cancelClose();return false;}requestClose();return closed;}
 function finishClose(){
  if(closed)return;closed=true;cancelAnimationFrame(raf);raf=0;clearTimeout(srTimer);clearTimeout(layoutTimer);
  for(const el of inerted)el.inert=false;inerted.length=0;
  window.removeEventListener('keydown',onKey,true);window.removeEventListener('keyup',onKeyUp,true);window.removeEventListener('resize',layout);resizeObs?.disconnect();
  document.removeEventListener('visibilitychange',onHide);window.removeEventListener('blur',fishRelease);
  canvas.width=0;canvas.height=0;root.remove();document.body.classList.remove('fg-open');
  try{prev?.focus?.();}catch{}
  opts.onClose?.();
 }

 /* ---- start card */
 function showIntro(){
  const box=node('div','fg-result tg-intro');box.setAttribute('role','dialog');box.setAttribute('aria-label','Правила');
  const base=goodsText(trip.outputs,name),best=goodsText(scaledOutputs(trip.outputs,quality(1000,rules)),name);
  const go=btn('Начать','primary wide',()=>{box.remove();started=true;t0=performance.now();stage.classList.add('tg-live');paint();canvas.focus({preventScroll:true});say(fish?'Кольцо бежит по воде. Жми, когда оно над рыбой.':'Выбери клетку. Мухомор — ловушка: −2 шага.');});
  if(fish){
   const rc=f2.routes[trip.route],rare=rc?.rare;
   box.append(node('h2','','Порыбачу сам'),node('p','tg-sky',skyLine(plan)),
    node('p','',`${casts.length} заброса: забрось над рыбой, дождись, пока поплавок уйдёт под воду, подсеки и вытащи — держи, а когда шкала краснеет, отпускай.`));
   const inv=opts.inventory||{},pick=node('div','qw-btn-group tg-baits');pick.setAttribute('role','group');pick.setAttribute('aria-label','Наживка');
   const hint=node('p','fg-compare tg-bait-hint');
   const choose=b=>{bait=b;for(const x of pick.children)x.setAttribute('aria-pressed',String(x.dataset.bait===b));hint.textContent=b?`${BAIT_TEXT[b]}: ${BAIT_HINT[b]}. Тратится 1 шт.`:'Без наживки — как обычно. Прикормка уже взята в поездку.';};
   for(const b of ['',...plan.baits]){const have=b?inv[b]||0:null,x=btn(b?`${BAIT_TEXT[b]||name(b)} · ${have}`:BAIT_TEXT[''],'',()=>choose(b));x.dataset.bait=b;x.disabled=b!==''&&have<1;pick.append(x);}
   box.append(node('p','tg-label','Наживка'),pick,hint);choose('');
   if(rare)box.append(node('p','fg-compare',`Здесь водится редкая рыба — ${speciesName(rare)}. Она идёт только на точный заброс и попадает в журнал улова.`));
   box.append(node('p','fg-compare',`Автопилот: ${base}. Идеальная игра: ${best}. Время поездки и опыт не меняются.`));
  }else{
   box.append(node('h2','','Пойду сам'),node('p','',`Короткий сбор: ${plan.budget} шагов на поляне. Это около минуты.`),
    node('p','fg-compare',`Автопилот: ${base}. Идеальная игра: ${best}.`),node('p','fg-compare','Время поездки и опыт не меняются; хуже автопилота не будет.'));
  }
  const stack=node('div','qw-btn-stack');stack.append(go,btn('Без игры','secondary wide',()=>finishClose()));box.append(stack);root.append(box);go.focus();
 }

 /* ---- drawing */
 function draw(ts){
  if(closed)return;
  const t=started?tNow():0,L=look(),calm=reducedMotion();
  const lf=Math.max(0,(deadline-performance.now())/1000);timer.textContent=`Осталось ${mmss(lf)}`;timer.classList.toggle('warn',lf<=60);
  if(lf<=0&&!done&&!sending&&started){done=true;showNote('Время вышло','Окно мини-игры закрылось. Поездка идёт как обычно, без бонуса.');}
  if(started&&!done&&!confirming&&fish){fishTick(t);if(phase==='aim'&&act.disabled&&t>=freeAt)paint();}
  if(started&&!done&&!confirming&&!fish&&queue.length&&!sending&&ts-stepAt>=130){
   stepAt=ts;const ch=queue[0];if(tryStep(ch))queue.shift();else{queue=[];say('Шаги закончились.',true);}
  }
  const g=canvas.getContext('2d'),{w,h,dpr}=size;
  g.setTransform(dpr,0,0,dpr,0,0);g.clearRect(0,0,w,h);
  if(fish)drawLake(g,t,calm);else drawForest(g,ts,L,calm);
  raf=requestAnimationFrame(draw);
 }
 /** Geometry of the lake view in CSS px. */
 function geo(){
  const {w,h}=size,hy=Math.round(h*(w>h?.26:.2)),sy=Math.round(h*.84),ay=Math.round(hy+(sy-hy)*.42);
  const x0=w*.12,x1=w*.88,tip={x:w*.7,y:sy-(sy-hy)*.2},butt={x:w*.93,y:h+8};
  return {w,h,hy,sy,ay,pos:p=>x0+(x1-x0)*p/1000,tip,butt,land:{x:w*.62,y:sy-8}};
 }
 function drawLake(g,t,calm){
  const G=geo(),{w,h,hy,sy,ay}=G,sk=plan.sky||{tod:'day',weather:'clear'},night=sk.tod==='night'||isNight(),mv=calm?0:1,windy=sk.weather==='wind'?2:1;
  // sky with sun or moon, clouds
  const skyC=SKY[sk.tod]||SKY.day,sg=g.createLinearGradient(0,0,0,hy);sg.addColorStop(0,skyC[0]);sg.addColorStop(1,skyC[1]);g.fillStyle=sg;g.fillRect(0,0,w,hy+2);
  if(sk.tod==='night'){g.fillStyle='#ecd88d';g.beginPath();g.arc(w*.8,hy*.4,Math.min(16,hy*.2),0,6.3);g.fill();g.fillStyle=skyC[0];g.beginPath();g.arc(w*.8+6,hy*.4-4,Math.min(14,hy*.18),0,6.3);g.fill();
   g.fillStyle='#f6e3a0';for(let i=0;i<14;i++){g.beginPath();g.arc((i*97)%w,(i*37)%(hy*.7)+4,1.2,0,6.3);g.fill();}}
  else if(sk.weather!=='rain'){const low=sk.tod!=='day';g.fillStyle=low?'#f2a65e':'#f5c862';g.beginPath();g.arc(low?w*.18:w*.8,low?hy*.78:hy*.38,Math.min(18,hy*.22),0,6.3);g.fill();}
  if(sk.weather==='cloud'||sk.weather==='rain'){g.fillStyle=sk.weather==='rain'?'#c9d0cc':'#ffffffcc';for(let i=0;i<3;i++){const cx=((i*w*.37+t*.006*mv*windy)%(w+160))-80,cy=hy*(.25+i*.18);for(const [dx,dy,r] of [[0,0,22],[20,-6,18],[-20,-2,16],[38,2,14]]){g.beginPath();g.ellipse(cx+dx,cy+dy,r*1.3,r*.8,0,0,6.3);g.fill();}}}
  if(sk.weather==='rain'){g.strokeStyle='#ffffff8c';g.lineWidth=1.2;for(let i=0;i<46;i++){const x=((i*53.7+t*.09*mv)%(w+40))-20,y=((i*91.3+t*.55*mv)%(h*.86));g.beginPath();g.moveTo(x,y);g.lineTo(x-3,y+11);g.stroke();}}
  // far shore with farm trees
  g.fillStyle='#a9c48d';g.beginPath();g.moveTo(0,hy+4);for(let x=0;x<=w;x+=w/8)g.lineTo(x,hy-4+Math.sin(x*.05)*3);g.lineTo(w,hy+6);g.closePath();g.fill();
  const n=Math.max(5,Math.round(w/70));for(let i=0;i<n;i++){const x=(i+.5)*w/n+Math.sin(i*7.3)*12,s=.42+((i*37)%10)/40;if(Math.abs(x-w*.5)<w*.08&&i%2)continue;tree(g,x,hy+2,s);}
  // water
  const wg=g.createLinearGradient(0,hy,0,sy);wg.addColorStop(0,'#a7cdc6');wg.addColorStop(.5,'#b6d3cf');wg.addColorStop(1,'#c3dcd7');g.fillStyle=wg;g.fillRect(0,hy,w,sy-hy+2);
  g.strokeStyle='#e2eee0a0';g.lineWidth=1.4;
  for(let i=0;i<7;i++){const y=hy+(sy-hy)*(.1+i*.13),dx=mv?Math.sin(t/(1400/windy)+i*1.7)*14:0,len=w*(.12+(i%3)*.05);for(const k of [0,1]){const x=((i*131+k*w*.5)%w)+dx;g.beginPath();g.moveTo(x-len/2,y);g.lineTo(x+len/2,y);g.stroke();}}
  if(sk.weather==='rain'&&mv){g.strokeStyle='#eef7f0aa';g.lineWidth=1;for(let i=0;i<9;i++){const ph=((t/700)+i*.37)%1,x=(i*173)%w+20,y=hy+(sy-hy)*(.15+((i*29)%80)/100);g.globalAlpha=1-ph;g.beginPath();g.ellipse(x,y,2+ph*9,1+ph*3,0,0,6.3);g.stroke();}g.globalAlpha=1;}
  // swans and the duck of the farm lake (smallAnimal), far away
  const P=painter(g,t/1000),sx=((t*.004*mv)%(w+120))-60;
  g.save();g.translate(w-sx,hy+(sy-hy)*.14);g.scale(.62,.62);smallAnimal(P,0,0,'swan');g.translate(34,7);smallAnimal(P,0,0,'swan');g.restore();
  g.save();g.translate(w*.18+Math.sin(t/2600)*20*mv,hy+(sy-hy)*.24);g.scale(-.7,.7);smallAnimal(P,0,0,'duck_swim');g.restore();
  // lily pads and reeds
  for(const [px,py,r] of [[w*.08,ay+(sy-ay)*.55,16],[w*.2,ay+(sy-ay)*.78,12],[w*.9,ay-(ay-hy)*.3,11]]){g.fillStyle='#7fa86f';g.beginPath();g.moveTo(px,py);g.ellipse(px,py,r,r*.42,0,.35,6.0);g.closePath();g.fill();g.fillStyle='#93bb80';g.beginPath();g.ellipse(px-r*.2,py-r*.06,r*.5,r*.18,0,0,6.3);g.fill();}
  g.fillStyle='#f3e4ec';g.beginPath();g.arc(w*.08+5,ay+(sy-ay)*.55-4,3.4,0,6.3);g.fill();
  const reeds=(bx,by,dir)=>{for(let i=0;i<6;i++){const x=bx+i*6*dir,top=by-34-((i*13)%18),sw=mv?Math.sin(t/(900/windy)+i)*3*windy:0;g.strokeStyle='#7f9a5a';g.lineWidth=2;g.beginPath();g.moveTo(x,by);g.quadraticCurveTo(x+sw*.5,(by+top)/2,x+sw,top);g.stroke();if(i%2===0){g.fillStyle='#8b6949';g.beginPath();g.ellipse(x+sw,top+6,2.6,6,0,0,6.3);g.fill();}}};
  reeds(6,sy+2,1);reeds(w-8,sy-(sy-hy)*.05,-1);
  // the fish place: shadow and bubbles at the zone of the current cast
  const c=cast(),zx=G.pos(c.zone);
  if(phase==='aim'||phase==='wait'){g.fillStyle='#4f7f7866';g.beginPath();g.ellipse(zx,ay+6,30,9,0,0,6.3);g.fill();drawFishArt(g,'crucian',zx+(mv?Math.sin(t/700)*6:0),ay+6,26,1,true,mv?Math.sin(t/180):0);
   g.strokeStyle='#eef7f0';g.lineWidth=1.2;for(let i=0;i<3;i++){const ph=((t/900+i*.33)%1)*mv;g.globalAlpha=1-ph;g.beginPath();g.arc(zx-10+i*10,ay-4-ph*14,2+i*.6,0,6.3);g.stroke();}g.globalAlpha=1;}
  // near bank, bucket and rod
  g.fillStyle='#a8c98a';g.beginPath();g.moveTo(0,sy+4);g.quadraticCurveTo(w*.35,sy-6,w*.6,sy+2);g.quadraticCurveTo(w*.8,sy+8,w,sy-2);g.lineTo(w,h);g.lineTo(0,h);g.closePath();g.fill();
  g.strokeStyle='#8fb574';g.lineWidth=2;g.lineCap='round';for(let i=0;i<12;i++){const x=(i+.5)*w/12,y=sy+16+((i*29)%14);for(const d of [-4,0,4]){g.beginPath();g.moveTo(x+d*.4,y+5);g.quadraticCurveTo(x+d*.6,y,x+d,y-6+Math.abs(d)*.5);g.stroke();}}
  const bk={x:w*.82,y:h-14};g.fillStyle='#8c7558';g.beginPath();g.moveTo(bk.x-12,bk.y-14);g.lineTo(bk.x+12,bk.y-14);g.lineTo(bk.x+9,bk.y+8);g.lineTo(bk.x-9,bk.y+8);g.closePath();g.fill();g.fillStyle='#634f3a';g.fillRect(bk.x-12,bk.y-16,24,3);
  const caughtN=results.filter(r=>r.result==='land').length;for(let i=0;i<Math.min(3,caughtN);i++)drawFishArt(g,results.filter(r=>r.result==='land')[i].fish.id,bk.x-5+i*5,bk.y-16-i*2,14,i%2?1:-1);
  // where the float / fish is
  let fx=zx,fy=ay,under=false;
  const markX=G.pos(markPosition(Math.max(0,phase==='aim'?t:aimAt),c.phase,rules,plan.mark_period));
  if(phase==='wait'||(phase==='result'&&!last?.fish)){fx=G.pos(markPosition(aimAt,c.phase,rules,plan.mark_period));}
  const tension=phase==='fight'&&fst?fst.t:0,bend=Math.min(1,tension/1000);
  const tip={x:G.tip.x+bend*18,y:G.tip.y+bend*26};
  // night: the farm's darkness overlay, then the lit things (line, float, ring, gauge) on top
  if(night){g.fillStyle='#0e1828aa';g.fillRect(0,0,w,h);}
  // the rod is the nearest thing: drawn after the night shade so it stays readable
  g.strokeStyle=night?'#9a8b6c':'#6b6048';g.lineWidth=4;g.lineCap='round';g.beginPath();g.moveTo(G.butt.x,G.butt.y);g.quadraticCurveTo(G.butt.x-(G.butt.x-tip.x)*.4,G.butt.y-(G.butt.y-tip.y)*.7+bend*20,tip.x,tip.y);g.stroke();
  g.fillStyle=night?'#6f6550':'#4d4536';g.beginPath();g.arc(G.butt.x-(G.butt.x-tip.x)*.12,G.butt.y-(G.butt.y-tip.y)*.16,6,0,6.3);g.fill();
  const lineCol=night?'#f2edc4':'#e5e0bc',inkCol=night?'#f2edc4':'#26402d';
  if(phase==='aim'&&started){
   g.lineWidth=3;g.strokeStyle=night?'#f6e3a0':'#ffffff';g.beginPath();g.ellipse(markX,ay,16,6,0,0,6.3);g.stroke();
   g.lineWidth=1.5;g.strokeStyle=night?'#2a3a2a':'#2b5a3a';g.beginPath();g.ellipse(markX,ay,20,8,0,0,6.3);g.stroke();
   g.beginPath();g.moveTo(markX,ay-12);g.lineTo(markX,ay-4);g.moveTo(markX,ay+4);g.lineTo(markX,ay+12);g.stroke();
  }
  if(phase==='wait'||(phase==='result'&&!last?.fish&&last?.result!=='missed')){
   const flyK=Math.min(1,(t-aimAt)/f2.fly),fpx=tip.x+(fx-tip.x)*flyK,fpy=tip.y+(fy-tip.y)*flyK-Math.sin(flyK*Math.PI)*60;
   const nib=nibbles.some(n=>t>=n&&t<n+260),dip=phase==='wait'&&t>=bite?Math.min(12,(t-bite)/18):nib?3:0,bob=mv?Math.sin(t/260)*1.6:0;
   g.strokeStyle=lineCol;g.lineWidth=1;g.beginPath();g.moveTo(tip.x,tip.y);g.quadraticCurveTo((tip.x+fpx)/2,Math.max(tip.y,fpy)+18,fpx,fpy+bob+dip);g.stroke();
   if(night){const rg=g.createRadialGradient(fpx,fpy,0,fpx,fpy,26);rg.addColorStop(0,'#f6e3a066');rg.addColorStop(1,'#f6e3a000');g.fillStyle=rg;g.fillRect(fpx-26,fpy-26,52,52);}
   if(dip<11){g.fillStyle='#d9482f';g.beginPath();g.ellipse(fpx,fpy+bob+dip-5,4.5,7-dip*.4,0,0,6.3);g.fill();g.fillStyle='#fffef6';g.fillRect(fpx-4.5,fpy+bob+dip-1,9,2.5);}
   g.fillStyle='#d08c5b';g.beginPath();g.ellipse(fpx,fpy+bob+dip+2,3.4,2.4,0,0,6.3);g.fill();
   g.strokeStyle='#eef7f0';g.lineWidth=1.2;if(flyK>=1){g.globalAlpha=.6;g.beginPath();g.ellipse(fpx,fpy+4,9+bob,3,0,0,6.3);g.stroke();g.globalAlpha=1;}
   if(nib){g.beginPath();g.ellipse(fpx,fpy+4,16,5,0,0,6.3);g.stroke();}
   if(phase==='wait'&&t>=bite){const ph=Math.min(1,(t-bite)/500);g.lineWidth=3;g.strokeStyle='#ffffff';g.globalAlpha=1-ph*.6;g.beginPath();g.ellipse(fpx,fpy+4,14+ph*30,5+ph*10,0,0,6.3);g.stroke();g.globalAlpha=1;
    label(g,'Клюёт! Подсекай!',fpx,fpy-24,inkCol,night);}
  }
  if(phase==='fight'&&fst){
   const D=Math.min(1000,fst.d),land=G.land,p0={x:zx,y:ay},k=D/600;
   let px=land.x+(p0.x-land.x)*k,py=land.y+(p0.y-land.y)*k;py=Math.max(hy+14,py);
   const run=fst.pull>=50,shake=fst.pull>=26&&fst.pull<50;px+=mv?Math.sin(t/(run?140:420))*(run?18:8):0;
   const dir=px<tip.x?-1:1;
   const recent=splash.filter(s=>t-s<700);splash=recent;
   drawFishArt(g,hooked.id,px,py+6,32*FISH_LOOK[hooked.id].len,dir,true,mv?Math.sin(t/(run?60:160)):0);
   g.strokeStyle='#eef7f0';g.lineWidth=1.4;for(const s of recent){const ph=(t-s)/700;g.globalAlpha=1-ph;g.beginPath();g.ellipse(px,py+2,10+ph*34,4+ph*10,0,0,6.3);g.stroke();}g.globalAlpha=1;
   if(recent.length&&mv&&(hooked.id==='pike'||hooked.id==='catfish'||hooked.id==='perch')){const ph=(t-recent[0])/700;if(ph<.55)drawFishArt(g,hooked.id,px,py-Math.sin(ph/.55*Math.PI)*30,30*FISH_LOOK[hooked.id].len,dir,false,1);}
   const sag=Math.max(0,1-fst.t/500)*30;
   g.strokeStyle=fst.t>=800?'#ffb7a0':lineCol;g.lineWidth=fst.t>=800?1.8:1.2;g.beginPath();g.moveTo(tip.x,tip.y);g.quadraticCurveTo((tip.x+px)/2+(shake&&mv?Math.sin(t/25)*4:0),(tip.y+py)/2+sag,px,py);g.stroke();
   gauge(g,G,fst,night);
  }
  if(phase==='result'&&last)resultCard(g,G,last,night,t);
  if(!started){label(g,'Приготовься…',w/2,hy+(sy-hy)*.3,inkCol,night);}
 }
 function label(g,text,x,y,ink,night){
  g.font='700 18px system-ui,sans-serif';g.textAlign='center';g.textBaseline='middle';
  const tw=g.measureText(text).width+20;g.fillStyle=night?'#1d2c44dd':'#fffef6e6';rrect(g,x-tw/2,y-15,tw,30,15);g.fill();
  g.fillStyle=ink;g.fillText(text,x,y+1);
 }
 /** The tension gauge and the distance: big, on top of the water, readable at night. */
 function gauge(g,G,s,night){
  const {w}=G,bw=Math.min(420,w-32),x=(w-bw)/2,y=42,hh=18;
  g.fillStyle=night?'#1d2c44e6':'#fffef6e6';rrect(g,x-10,6,bw+20,y+hh+10,14);g.fill();
  g.font='700 13px system-ui,sans-serif';g.textBaseline='middle';g.fillStyle=night?'#f2edc4':'#26402d';
  g.textAlign='left';g.fillText(s.t>=800?'Натяжение — отпусти!':'Натяжение',x,20);
  g.textAlign='right';g.fillText(`до берега ${Math.max(0,Math.ceil(s.d/50))} м`,x+bw,20);
  for(const [a,b,col] of [[0,600,'#7fb36a'],[600,800,'#e0b850'],[800,1000,'#d9805c']]){g.fillStyle=col;g.fillRect(x+bw*a/1000,y,bw*(b-a)/1000,hh);}
  g.strokeStyle=night?'#f2edc4':'#26402d';g.lineWidth=1.5;rrect(g,x,y,bw,hh,6);g.stroke();
  const nx=x+bw*Math.min(1000,s.t)/1000;g.fillStyle=night?'#ffffff':'#26402d';g.beginPath();g.moveTo(nx,y-2);g.lineTo(nx-6,y-9);g.lineTo(nx+6,y-9);g.closePath();g.fill();g.fillRect(nx-1.5,y-2,3,hh+4);
 }
 function resultCard(g,G,r,night,t){
  const {w,hy,sy}=G,cw=Math.min(300,w-32),ch=r.fish&&r.result==='land'?150:84,x=(w-cw)/2,y=Math.max(8,hy+(sy-hy)*.38-ch/2);
  const rare=r.fish&&r.result==='land'&&f2.species[r.fish.id].rare;
  g.fillStyle=night?'#22344cf2':'#fffef6f2';rrect(g,x,y,cw,ch,18);g.fill();
  g.strokeStyle=rare?'#e0b850':night?'#8fb59a':'#cfd8bd';g.lineWidth=rare?4:1.5;rrect(g,x,y,cw,ch,18);g.stroke();
  const ink=night?'#f2edc4':'#26402d';g.fillStyle=ink;g.textAlign='center';g.textBaseline='middle';
  if(r.result==='land'){
   drawFishArt(g,r.fish.id,w/2,y+48,Math.min(110,cw*.36)/FISH_LOOK[r.fish.id].len*1.1,1,false,reducedMotion()?0:Math.sin(t/120)*.6);
   g.font='800 19px system-ui,sans-serif';g.fillText(`${speciesName(r.fish.id)} · ${grams(r.fish.g)}`,w/2,y+ch-46);
   g.font='600 13px system-ui,sans-serif';g.fillText(rare?'Редкая рыба! Запишем в журнал улова.':journalBefore[r.fish.id]||results.slice(0,-1).some(x=>x.result==='land'&&x.fish.id===r.fish.id)?'В садок!':'Новая рыба в журнале улова!',w/2,y+ch-22);
  }else{g.font='700 15px system-ui,sans-serif';const lines=(RESULT_TEXT[r.result]||'').split(' — ');lines.forEach((ln,i)=>g.fillText(ln,w/2,y+ch/2+(i-(lines.length-1)/2)*22));}
 }
 function drawForest(g,ts,L,calm){
  const {w,h,cell,left:lx,top:ly}=size;
  g.fillStyle=L.grass[0];g.fillRect(0,0,w,h);
  const s=st||walk(plan,'');
  const items=s.items,traps=s.traps;
  for(let y=0;y<plan.h;y++)for(let x=0;x<plan.w;x++){
   const c=y*plan.w+x,X=lx+x*cell,Y=ly+y*cell;
   g.fillStyle=(x+y)%2?L.grass[0]:L.grass[1];g.fillRect(X,Y,cell,cell);
   if(s.seen.has(c)&&c!==s.cur&&c!==plan.start){g.fillStyle=isNight()?'#ffffff10':'#00000010';g.fillRect(X,Y,cell,cell);}
   if(items.has(c)&&!s.seen.has(c))drawItem(g,plan.items[c],X,Y,cell);
   else if(traps.has(c)){drawItem(g,'',X,Y,cell,true);}
   g.strokeStyle=L.tile;g.lineWidth=1;g.strokeRect(X+0.5,Y+0.5,cell-1,cell-1);
  }
  g.strokeStyle=L.frame;g.lineWidth=3;g.strokeRect(lx-1.5,ly-1.5,plan.w*cell+3,plan.h*cell+3);
  // walked path
  if(path.length){g.strokeStyle=isNight()?'#ffe9a8aa':'#2f6f4b88';g.lineWidth=Math.max(3,cell/9);g.lineCap='round';g.lineJoin='round';g.beginPath();
   let c=plan.start;g.moveTo(lx+(c%plan.w+0.5)*cell,ly+(idiv(c,plan.w)+0.5)*cell);
   for(const ch of path){const d=DIRS[ch];c=(idiv(c,plan.w)+d[1])*plan.w+(c%plan.w+d[0]);g.lineTo(lx+(c%plan.w+0.5)*cell,ly+(idiv(c,plan.w)+0.5)*cell);}g.stroke();}
  // the basket
  const bx=lx+(s.cur%plan.w)*cell,by=ly+idiv(s.cur,plan.w)*cell;
  g.fillStyle='#a47544';rrect(g,bx+cell*0.2,by+cell*0.38,cell*0.6,cell*0.4,cell*0.1);g.fill();g.strokeStyle='#6f4c28';g.lineWidth=2;g.stroke();
  g.beginPath();g.arc(bx+cell/2,by+cell*0.4,cell*0.22,Math.PI,0);g.stroke();
  if(!started){g.fillStyle=L.ink;g.font='600 14px system-ui,sans-serif';g.textAlign='center';g.fillText('Приготовься…',w/2,ly-8>14?ly-8:14);}
  // step-budget bar under the field
  const bw=plan.w*cell,used=Math.min(plan.budget,s.used);
  g.fillStyle=isNight()?'#ffffff22':'#00000018';rrect(g,lx,ly+plan.h*cell+8,bw,8,4);g.fill();
  g.fillStyle=used>=plan.budget?'#d9805c':'#4f9d5d';rrect(g,lx,ly+plan.h*cell+8,bw*(1-used/plan.budget),8,4);g.fill();
 }

 layout();paint();
 window.addEventListener('resize',layout);
 const resizeObs=typeof ResizeObserver==='function'?new ResizeObserver(()=>{if(!closed)layout();}):null;resizeObs?.observe(stage);
 raf=requestAnimationFrame(draw);
 layoutTimer=setTimeout(()=>{layoutTimer=0;if(!closed)layout();},60);
 showIntro();
 return {close:finishClose,requestClose:backClose};
}
