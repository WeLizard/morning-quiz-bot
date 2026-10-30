// Version 1: integer pie-tower replay shared with domain/farm_pie.py.
export const VERSION=1,TTL=65,LIMIT_MS=60000,FALL_MS=320,MIN_GAP_MS=400,WARMUP_MS=700,MAX_TAPS=160;
export const BASE=560,X0=140,X1=860,T0=4200,STEP=100,TMIN=1800,WIDTH=1000,HEIGHT=600,TOWER_CENTER=500;

export function craneX(plan,t,height){
 const period=Math.max(plan.tmin,plan.t0-plan.step*height),p=(Math.max(0,t-plan.warmup_ms)+plan.phase)%period;
 const u=Math.floor(p*2000/period),q=u<=1000?u:2000-u;
 return plan.x0+Math.floor((plan.x1-plan.x0)*q/1000);
}
export function drop(towerLo,towerHi,x,base){
 const lo=Math.max(towerLo,x-Math.floor(base/2)),hi=Math.min(towerHi,x+Math.floor(base/2));
 return hi>lo?[lo,hi]:null;
}
export function logValid(plan,log){
 if(!Array.isArray(log)||log.length>plan.max_taps)return false;
 let previous=null;
 for(const t of log){
  if(!Number.isInteger(t)||t<0||t>plan.limit_ms)return false;
  if(previous!==null&&t-previous<plan.min_gap_ms)return false;
  previous=t;
 }
 return true;
}
export function replay(plan,log){
 let towerLo=TOWER_CENTER-Math.floor(plan.base/2),towerHi=TOWER_CENTER+Math.floor(plan.base/2),height=0,miss=false,taps=0;
 for(const t of log){
  if(t>plan.limit_ms)break;
  taps+=1;
  const landed=drop(towerLo,towerHi,craneX(plan,t,height),plan.base);
  if(landed===null){miss=true;break;}
  [towerLo,towerHi]=landed;height+=1;
 }
 return {height,tower:[towerLo,towerHi],miss,taps};
}
