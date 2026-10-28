/* Farm r9 stage 15B: pure field rules shared by the server replay, the client forecast and tests.
 *
 * This module intentionally has no DOM or canvas code: the live overlay is field_overlay.js.
 * Integers only, no floats, no hashing. The server still replays the path and decides the reward.
 */
export const DEFAULTS={hopper:18,qBase:850,qSpan:250,qAuto:950,qBaseFull:850,qSpanFull:400,qAutoFull:900,
 stepCs:12,autoS:90,maxPath:2000,weedWeight:3,fullK:250,zeroK:600,runTtl:1800,unloadCenter:500,unloadHalf:115,
 tank:48,tankChunks:4,hitDamage:3,hitRepair:15,condPenalty:4,sprayBonusBase:850,sprayBonusSpan:2000,sprayBonusMax:1200,growCutFull:300};
const DIRS={U:[0,-1],D:[0,1],L:[-1,0],R:[1,0]};
const BUMP_CHARS='udlr';
const idiv=(a,b)=>(a-a%b)/b;                       // exact integer division for non-negative integers

/* ---------------------------------------------------------------- pure rules (see fields.py) */
export function stepAnchor(x,y,ch,W,H,width,rocks){
 const d=DIRS[ch];if(!d)return null;
 const nx=x+d[0],ny=y+d[1];
 if(nx<0||nx>W-width||ny<0||ny>=H)return null;
 for(let i=0;i<width;i++)if(rocks.has(ny*W+nx+i))return null;
 return [nx,ny];
}
export function stepAnchorOrient(x,y,ch,W,H,width,rocks,orient){
 const d=DIRS[ch];if(!d)return null;
 const nx=x+d[0],ny=y+d[1];
 if(orient==='v'){if(nx<0||nx>=W||ny<0||ny+width>H)return null;}
 else if(nx<0||nx>W-width||ny<0||ny>=H)return null;
 for(let i=0;i<width;i++){const c=orient==='v'?(ny+i)*W+nx:(ny*W+nx+i);if(rocks.has(c))return null;}
 return [nx,ny];
}
function footCells(x,y,W,width,orient){
 const out=[];for(let i=0;i<width;i++)out.push(orient==='h'?y*W+x+i:(y+i)*W+x);return out;
}
function orientOk(x,y,W,H,width,rocks,orient){
 if(orient==='v'){if(x<0||x>=W||y<0||y+width>H)return false;}
 else if(x<0||x>W-width||y<0||y>=H)return false;
 return !footCells(x,y,W,width,orient).some(c=>rocks.has(c));
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
export function reachableOrientCells(W,H,width,rocks){
 const seen=new Set(['0,0,h']),todo=[[0,0,'h']],cells=new Set();
 while(todo.length){
  const [x,y,orient]=todo.pop();
  for(const c of footCells(x,y,W,width,orient))cells.add(c);
  for(const ch of 'UDLR'){
   const n=stepAnchorOrient(x,y,ch,W,H,width,rocks,orient);
   if(n&&!seen.has(n[0]+','+n[1]+','+orient)){seen.add(n[0]+','+n[1]+','+orient);todo.push([n[0],n[1],orient]);}
  }
  const other=orient==='h'?'v':'h';
  if(orientOk(x,y,W,H,width,rocks,other)&&!seen.has(x+','+y+','+other)){seen.add(x+','+y+','+other);todo.push([x,y,other]);}
 }
 cells.forEach(c=>{if(rocks.has(c))cells.delete(c);});
 return cells;
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
export function qualityFull(score,cfg=DEFAULTS){return cfg.qBaseFull+idiv(cfg.qSpanFull*score,1000);}
export function conditionQuality(q,condition,cfg=DEFAULTS){return Math.max(cfg.qBaseFull,Math.min(cfg.qBaseFull+cfg.qSpanFull,q-Math.max(0,100-condition)*cfg.condPenalty));}
/** Final run quality as the server settles it (fields._finish): a broken machine (condition <= 0) pays exactly the full-economy autopilot quality. */
export function finalConditionQuality(q,condition,cfg=DEFAULTS){return condition<=0?cfg.qAutoFull:conditionQuality(q,condition,cfg);}
/** Seconds left until run.expires_at by the SERVER clock (a suspended WebView must not look as if time is left); falls back to a local countdown. */
export function runLeftSec(run,serverNow,fallbackSec){return Number.isFinite(run&&run.expires_at)&&typeof serverNow==='function'?run.expires_at-serverNow():fallbackSec;}
export function sprayBonus(q,cfg=DEFAULTS){if(!q)return 1000;return Math.min(cfg.sprayBonusMax,1000+idiv(Math.max(0,q-cfg.sprayBonusBase)*1000,cfg.sprayBonusSpan));}
/* Runs opened since the owner's 2026-10-14 decision carry run.qrule===2: the bonus over the autopilot melts with the time of the run. */
export const QRULE_TIMED=2;
export const RULES_TURN=2;
export const RULES_FULL=3;
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
export function yieldQty(base,qSow,qHarvest,qSpray=1000){return Math.max(1,idiv(base*qSow*qHarvest*qSpray,1000000000));}
export function autoSeconds(ha,width,speed=1,cfg=DEFAULTS){return Math.max(1,Math.ceil(cfg.autoS*ha/width/speed));}
export function maxPath(field,run,cfg=DEFAULTS){return Math.min(idiv(3*field.w*field.h,run.width),cfg.maxPath);}

/* One machine run. push() applies a single character exactly like fields._walk + simulate_<op>; score() is the permille score. */
export class Run{
 constructor(field,run,cfg=DEFAULTS){
  this.W=field.w;this.H=field.h;this.width=run.width;this.op=run.op;this.cfg=cfg;
  this.rocks=new Set(run.rocks||[]);this.weeds=new Set(run.weeds||[]);
  this.cap=cfg.hopper*this.width*idiv(this.H,this.W);
  this.weedWeight=cfg.weedWeight||DEFAULTS.weedWeight;
  this.unloadZone=!!run.unload_zone;this.unloadCenter=cfg.unloadCenter;this.unloadHalf=cfg.unloadHalf;
  this.rules=Number.isInteger(run.rules)?run.rules:1;
  this.turnRules=this.rules>=RULES_TURN;
  this.fullRules=this.rules>=RULES_FULL;
  this.tank=this.op==='spray'?(run.tank||cfg.tank||DEFAULTS.tank):0;
  this.wind=this.op==='spray'?(run.wind||0):0;
  this.anchors=reachableAnchors(this.W,this.H,this.width,this.rocks);
  this.cells=this.fullRules?reachableOrientCells(this.W,this.H,this.width,this.rocks):cellsOfAnchors(this.anchors,this.W,this.width);
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
  this.x=0;this.y=0;this.t=0;this.path='';this.orient='h';
  this.last=new Map();this.got=0;this.again=0;
  this.sown=new Set();this.doubles=0;this.doubled=new Set();
  this.sprayed=new Set();this.sprayDoubles=0;this.sprayDoubled=new Set();
  this.load=this.op==='spray'?this.tank:0;this.kept=0;this.lost=new Set();this.unloads=0;
  this.condition=100;this.hits=0;this.repair=0;
  this._arrive();
 }
 _footCells(x,y,orient){return footCells(x,y,this.W,this.width,orient);}
 _canPlace(x,y,orient){return orientOk(x,y,this.W,this.H,this.width,this.rocks,orient);}
 canTurn(){if(!this.turnRules||this.width<2)return false;return this._canPlace(this.x,this.y,this.orient==='h'?'v':'h');}
 _sprayCell(c){
  if(!this.cells.has(c))return;
  if(this.sprayed.has(c)){this.sprayDoubles++;this.sprayDoubled.add(c);if(this.load>0)this.load-=1;return;}
  if(this.load<2)return;
  this.sprayed.add(c);this.load-=2;
  if(this.wind&&this.load>0){
   const cx=c%this.W,wx=cx+this.wind;
   if(wx>=0&&wx<this.W){const wk=c-cx+wx;if(this.cells.has(wk)&&!this.sprayed.has(wk)&&this.load>0){this.sprayed.add(wk);this.load-=1;}}
  }
 }
 _arrive(){
  const cells=this._footCells(this.x,this.y,this.orient);
  if(this.op==='sow'){
   if(this.turnRules){
    for(const c of cells){
     if(!this.sowable.has(c))continue;
     if(this.sown.has(c)){this.doubles++;this.doubled.add(c);}else this.sown.add(c);
    }
   }else if(this.x%(this.width+1)===0)for(const c of cells){if(this.sown.has(c)){this.doubles++;this.doubled.add(c);}else this.sown.add(c);}
   return;
  }
  if(this.op==='spray'){
   for(const c of cells)this._sprayCell(c);
   return;
  }
  for(const c of cells){
   if(this.turnRules&&!this.cells.has(c))continue;
   if(!this.last.has(c)){
    if(this.op==='cultivate')this.got+=this.weeds.has(c)?this.weedWeight:1;
    else if(this.load<this.cap){this.load++;this.kept++;}
    else this.lost.add(c);
   }else if(this.last.get(c)<this.t-1)this.again++;
   this.last.set(c,this.t);
  }
 }
 /** The fixed grain truck / sprayer tanker: new runs must transfer with the machine centre near it; older runs keep the top-edge rule. */
 canUnload(){if((this.op!=='harvest'&&this.op!=='spray')||this.y!==0)return false;if(!this.unloadZone)return true;const center2=2*this.x+(this.orient==='h'?this.width:1);return Math.abs(center2*50-this.unloadCenter)<=this.unloadHalf;}
 /** How many X steps a complete transfer still needs (0 = nothing to move). */
 transferSteps(){
  if(this.op==='harvest'){
   if(this.load<=0)return 0;
   if(!this.fullRules)return 1;
   const chunks=this.cfg.tankChunks||DEFAULTS.tankChunks;return Math.ceil(this.load/Math.max(1,Math.ceil(this.cap/chunks)));
  }
  if(this.op==='spray'&&this.fullRules){
   const chunks=this.cfg.tankChunks||DEFAULTS.tankChunks;return Math.ceil(Math.max(0,this.tank-this.load)/Math.max(1,idiv(this.tank,chunks)));
  }
  return 0;
 }
 transferNeeds(){return this.op==='harvest'?this.load>0:this.op==='spray'?this.load<this.tank:false;}
 /** Apply one character; false (and no change) when the server would reject it. */
 push(ch){
  if(ch==='X'){
   if(!this.canUnload())return false;
   if(this.fullRules){
    const chunks=this.cfg.tankChunks||DEFAULTS.tankChunks;
    if(this.op==='harvest'){const chunk=Math.max(1,Math.ceil(this.cap/chunks));this.load=Math.max(0,this.load-chunk);}
    else if(this.op==='spray'){const chunk=Math.max(1,idiv(this.tank,chunks));this.load=Math.min(this.tank,this.load+chunk);}
    else return false;
   }else if(this.op==='harvest')this.load=0;
   else return false;
   this.unloads++;this.path+=ch;return true;
  }
  if(ch==='T'){
   if(!this.turnRules||this.width<2)return false;
   const no=this.orient==='h'?'v':'h';
   if(!this._canPlace(this.x,this.y,no))return false;
   this.orient=no;this.path+=ch;return true;
  }
  if(BUMP_CHARS.includes(ch)){
   if(!this.fullRules||this.condition<=0)return false;
   const d=DIRS[ch.toUpperCase()],nx=this.x+d[0],ny=this.y+d[1];
   if(this._canPlace(nx,ny,this.orient))return false;   // a bump must be a real collision
   this.condition=Math.max(0,this.condition-(this.cfg.hitDamage||DEFAULTS.hitDamage));
   this.hits++;this.repair=this.hits*(this.cfg.hitRepair||DEFAULTS.hitRepair);
   this.path+=ch;return true;
  }
  const n=this.turnRules?stepAnchorOrient(this.x,this.y,ch,this.W,this.H,this.width,this.rocks,this.orient):stepAnchor(this.x,this.y,ch,this.W,this.H,this.width,this.rocks);
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
  if(this.op==='spray')return idiv(this.sprayed.size*1000,this.cells.size);
  return idiv(this.kept*1000,this.cells.size);
 }
 overlap(){
  if(this.op==='sow')return idiv(this.doubles*1000,this.sowable.size);
  if(this.op==='spray')return idiv(this.sprayDoubles*1000,this.cells.size);
  return idiv(this.again*1000,this.last.size);
 }
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
export const simulateSpray=(f,r,p,c)=>simulate(f,{...r,op:'spray'},p,c);

/* ---------------------------------------------------------------- texts */
const pctText=permille=>(permille/10).toFixed(1).replace('.',',')+'%';
export function effectLines(op,q,{item='',qty=0,qSow=0}={}){
 const lines=[`Качество ${pctText(q)}`];
 if(op==='cultivate'){const d=Math.abs(1000-growthPermille(q))/10;lines.push(growthPermille(q)<=1000?`Урожай созреет быстрее на ${String(d).replace('.',',')}%`:`Урожай созреет медленнее на ${String(d).replace('.',',')}%`);}
 else if(op==='sow')lines.push(`Урожай ×${(q/1000).toFixed(2).replace('.',',')} от нормы`);
 else if(op==='spray')lines.push(`Прибавка к урожаю +${Math.max(0,(q-850)/20).toFixed(1).replace('.',',')}%`);
 else lines.push(item?`Убрано: ${item} ×${qty}`:`Урожай ×${(q/1000).toFixed(2).replace('.',',')} от нормы`);
 return lines;
}

/** Server catalog.fields (snake_case) over the local DEFAULTS; only positive integers are accepted. */
export function gameCfg(src){
 const pick=(k,d)=>{const v=src?.[k];return Number.isInteger(v)&&v>0?v:d;};
 return {...DEFAULTS,hopper:pick('hopper',DEFAULTS.hopper),stepCs:pick('step_cs',DEFAULTS.stepCs),qBase:pick('q_base',DEFAULTS.qBase),
  qSpan:pick('q_span',DEFAULTS.qSpan),qAuto:pick('q_auto',DEFAULTS.qAuto),autoS:pick('auto_s',DEFAULTS.autoS),maxPath:pick('max_path',DEFAULTS.maxPath),
  runTtl:pick('run_ttl',DEFAULTS.runTtl),fullK:pick('run_full_k',DEFAULTS.fullK),zeroK:pick('run_zero_k',DEFAULTS.zeroK),
  unloadCenter:pick('unload_center',DEFAULTS.unloadCenter),unloadHalf:pick('unload_half',DEFAULTS.unloadHalf),
  qBaseFull:pick('q_base_full',DEFAULTS.qBaseFull),qSpanFull:pick('q_span_full',DEFAULTS.qSpanFull),qAutoFull:pick('q_auto_full',DEFAULTS.qAutoFull),
  tank:pick('tank',DEFAULTS.tank),tankChunks:pick('tank_chunks',DEFAULTS.tankChunks),hitDamage:pick('hit_damage',DEFAULTS.hitDamage),
  hitRepair:pick('hit_repair',DEFAULTS.hitRepair),condPenalty:pick('cond_penalty',DEFAULTS.condPenalty),
  sprayBonusBase:pick('spray_bonus_base',DEFAULTS.sprayBonusBase),sprayBonusSpan:pick('spray_bonus_span',DEFAULTS.sprayBonusSpan),
  sprayBonusMax:pick('spray_bonus_max',DEFAULTS.sprayBonusMax),growCutFull:pick('grow_cut_full',DEFAULTS.growCutFull)};
}
