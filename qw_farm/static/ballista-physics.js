// Version 1: integer replay shared with domain/farm_ballista.py.
export function trajectory(angle,power,wind,roof=null){
 let x=60,y=500,vx=Math.floor(power*(90000-angle)/1800000),vy=-Math.floor(power*angle/900000),bounced=false;
 const points=[[x,y]];
 for(let step=1;step<=150;step++){
  const oldY=y;x+=vx;y+=vy;vy+=2;if(step%4===0)vx+=wind;
  if(roof&&!bounced&&vy>0&&oldY<roof.y&&roof.y<=y&&roof.left<=x&&x<=roof.right){y=roof.y;vy=-Math.floor(vy*7/10);bounced=true;}
  points.push([x,y]);if(y>600||x>1100||x< -100)break;
 }
 return points;
}
export function shotResult(target,angle,power,stepMs=40){
 const path=trajectory(angle,power,target.wind,target.roof),distances=path.map(([x,y])=>(x-target.x)**2+(y-target.y)**2),minimum=Math.min(...distances);
 const hit=minimum<=target.radius**2,steps=hit?distances.indexOf(minimum):path.length-1,distance=Math.floor(Math.sqrt(minimum));
 return {path:path.slice(0,steps+1),hit,duration:steps*stepMs,score:hit?800+Math.floor(200*Math.max(0,target.radius-distance)/target.radius):0};
}
export function replay(plan,log){
 if(!Array.isArray(log)||log.length!==5)throw new Error('five_shots');
 let total=0,hits=0,previousEnd=0;const durations=[];
 log.forEach((shot,i)=>{
  if(!Array.isArray(shot)||shot.length!==3||!shot.every(Number.isInteger))throw new Error('invalid_shot');
  const [angle,power,release]=shot;
  if(angle<15000||angle>75000||power<200||power>1000)throw new Error('invalid_shot');
  if(release<previousEnd+250||release>180000)throw new Error('too_fast');
  const result=shotResult(plan.targets[i],angle,power,plan.step_ms);total+=result.score;hits+=Number(result.hit);durations.push(result.duration);previousEnd=release+result.duration;
 });
 return {score:Math.floor(total/5),hits,durations};
}
