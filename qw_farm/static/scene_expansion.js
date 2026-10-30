/* Original procedural sprites for r2. Rendering has no authority over rewards. */
import {isoInverse,compareDepth} from './scene_map.js';
import {drawFigure} from './lumberjack_art.js';
const P=(x,y,z=0)=>({x:(x-y)*36,y:(x+y)*18-z});
function rect(s,x,y,w,h,color,r=3){const c=s.c;c.fillStyle=color;c.beginPath();c.roundRect(x,y,w,h,r);c.fill();}
export function vehicle(s,x,y,id,active=false){
 const c=s.c;c.save();c.translate(x,y);c.scale(.88,.88);s.shadow(0,0,28,9);
 const rolling=active&&s.motion?Math.sin(s.time*8):0;
 if(id==='robot'){
  rect(s,-12,-20,25,21,'#acc2b6',6);rect(s,-9,-28,19,12,'#e4e7d4',5);rect(s,-7,-25,15,6,'#577b76',3);
  for(let d of [-5,5])s.ellipse(d,-22,1.4,1.3,'#ddeb9d');s.line(1,-28,1,-35,'#6c8e7a',2);s.ellipse(1,-36,3,3,active?'#eac362':'#94ad8f');
  for(let d of [-10,10]){rect(s,d-4,-4,9,8,'#66796c',3);s.ellipse(d,-1,2,2,'#c6c9ad');}
  s.line(-12,-13,-21,-6,'#87a291',3);s.line(13,-13,21,-6,'#87a291',3);rect(s,-6,-10,13,9,'#c5ad7f',2);
 }else{
  const combine=id==='harvester';
  rect(s,-23,-22,combine?48:40,20,combine?'#d6b66a':'#86a97c',5);
  rect(s,-20,-43,23,24,'#e0dfbd',4);rect(s,-16,-40,16,17,'#8db5b1',2);
  rect(s,-24,-45,31,5,combine?'#b89657':'#61886a',2);
  rect(s,4,-28,20,13,combine?'#e7cd82':'#aec29b',3);s.line(15,-29,15,-40,'#818775',3);rect(s,13,-43,6,4,'#6e7767',1);
  for(let [dx,rad]of [[-13,12],[20,8]]){s.ellipse(dx,-1,rad,rad,'#57695b');s.ellipse(dx,-1,rad*.48,rad*.48,'#d6d1ab');s.line(dx-rad*.5, -1+rolling,dx+rad*.5,-1-rolling,'#91a082',2);}
  if(combine){rect(s,27,-18,8,22,'#c29e58',2);s.line(28,1,42,7,'#d8bc7f',5);for(let k=0;k<5;k++)s.line(30+k*3,1+k,33+k*3,-5+k,'#8a875d',1.4);}
 }
 c.restore();
}
export function smallAnimal(s,x,y,id){
 const c=s.c;c.save();c.translate(x,y);
 if(['ostrich','silkworm','yak','pheasant'].includes(id)){lateAnimal(s,id);c.restore();return;}
 if(id==='goose'){s.goose(0,0,s.time);}
 else if(id==='duck'){s.shadow(0,1,13,5);s.ellipse(0,-7,13,8,'#b0a485');s.ellipse(-1,-8,9,4,'#a39372');s.ellipse(10,-17,6,6,'#789a7d');s.ellipse(14,-18,1,1,'#455f4b');s.ellipse(17,-15,4,2,'#d6b363');s.line(-4,0,-5,4,'#bd965a',2);s.line(5,0,6,4,'#bd965a',2);}
 // Swimming duck (mallard drake, about 0.7 of the swan): a boat-shaped hull with an upturned tail, short neck and a flat waterline.
 // Like the swan it sits in its own ripple; the hull below the waterline is hidden by a water lip, never drawn as legs.
 else if(id==='duck_swim'){const b=Math.sin(s.time*1.9)*.5;s.ellipse(0,0,15,3.6,'#b6d3cf');s.ellipse(0,-.2,11.5,2.4,'#d4e6e2');
  c.save();c.translate(0,b);
  c.beginPath();c.moveTo(-13,-8.5);c.quadraticCurveTo(-9,-6,-4,-9.5);c.quadraticCurveTo(4,-12.2,9,-8.4);c.quadraticCurveTo(12.8,-5.2,11,-1);c.lineTo(-9,-1);c.quadraticCurveTo(-12,-3,-13,-8.5);c.closePath();c.fillStyle='#ada186';c.fill();
  s.ellipse(8.6,-5,3.3,3,'#a38469');
  c.beginPath();c.moveTo(-9,-6.6);c.quadraticCurveTo(-1,-10.8,6,-6.6);c.quadraticCurveTo(0,-3.4,-9,-6.6);c.closePath();c.fillStyle='#8f8265';c.fill();
  s.ellipse(1.6,-5.7,2.6,.9,'#6d8fb0');
  s.poly([{x:-13.4,y:-8.8},{x:-10.2,y:-7.6},{x:-11.2,y:-10.6}],'#3f4a40');
  s.ellipse(9,-10.6,2.7,1.3,'#f2efe4');s.ellipse(10.2,-14.4,4.4,4,'#5d8a68');s.ellipse(9.2,-15.6,1.8,1.2,'#7aa684');s.ellipse(11.7,-15.2,.8,.8,'#263028');
  s.poly([{x:13.8,y:-15},{x:17.6,y:-13.6},{x:17.2,y:-12.5},{x:13.6,y:-12.6}],'#d6b363');
  c.restore();
  s.ellipse(-.5,-.6,12.6,1.6,'#c3dcd7');s.line(-17.5,.4,-13.5,.8,'#eef7f0b0',1);s.line(-16,2,-12.5,2,'#eef7f090',1);}
 else if(id==='goat'){s.cow(0,0);s.ellipse(14,-18,5,5,'#d6c6a4');s.line(15,-20,20,-30,'#8c8269',2);s.line(9,-20,9,-29,'#8c8269',2);s.line(19,-7,20,0,'#b3a68d',2);}
 else if(id==='rabbit'){s.shadow(0,0,11,4);s.ellipse(0,-7,10,7,'#ddd1c1');s.ellipse(8,-12,6,6,'#e8decc');s.ellipse(6,-22,2.5,10,'#ddd1c1');s.ellipse(11,-22,2.5,9,'#e8decc');s.ellipse(11,-14,1,1,'#59695b');s.ellipse(-10,-7,4,4,'#f2eada');}
 else if(id==='calf'){s.shadow(0,1,17,6);for(let dx of [-9,-4,7,11])s.line(dx,-4,dx,5,'#7a5a46',3);s.ellipse(0,-11,16,9,'#b98a64');s.ellipse(-5,-13,5,5,'#f1e3cf');s.ellipse(12,-12,7,8,'#c6966d');s.ellipse(17,-8,5,3.4,'#e9c9b4');s.ellipse(14,-18,2,3,'#a47750');s.ellipse(9,-17,2,3,'#a47750');s.ellipse(15,-13,1,1,'#40524b');s.line(-16,-12,-21,-5,'#7a5a46',2);}
 else if(id==='alpaca'){s.sheep(0,0);s.line(12,-6,12,-26,'#d2b999',9);s.ellipse(14,-28,6,6,'#e2cdac');s.ellipse(10,-35,2,5,'#c3a886');s.ellipse(17,-35,2,5,'#c3a886');s.ellipse(17,-30,1,1,'#67725f');}
 else if(id==='pig'){const w=s.time,b=Math.sin(w*2.2)*.8;s.shadow(0,1,15,5);for(const dx of [-8,-3,6,11])s.line(dx,-4,dx,2,'#d49f9a',3);s.ellipse(0,-10+b,16,10,'#efc5be');s.ellipse(-3,-12+b,9,5,'#f5d2cb');s.ellipse(14,-11+b*.5,8,8,'#f0c8c1');s.ellipse(20,-9+b*.5,4.5,3.5,'#e3a5a5');s.ellipse(19,-9,.9,.9,'#8d5f62');s.ellipse(21.5,-9,.9,.9,'#8d5f62');s.ellipse(14,-16+b*.5,3,4.5,'#e2a8a7');s.ellipse(17,-14,1.1,1.1,'#4a4a45');const t=Math.sin(w*5)*1.5;s.c.beginPath();s.c.arc(-17,-12,3.5,0,Math.PI*1.6);s.c.strokeStyle='#e0a9a4';s.c.lineWidth=1.8;s.c.stroke();s.ellipse(-18+t*.3,-15,1.4,1.4,'#e0a9a4');}
 else if(id==='turkey'){const w=s.time,sw=Math.sin(w*1.6)*1.2,pk=Math.max(0,Math.sin(w*1.3))*3;s.shadow(0,1,14,5);s.line(-3,-3,-3,3,'#c59a63',2);s.line(4,-3,4,3,'#c59a63',2);for(let k=-3;k<=3;k++){const a=-Math.PI/2+k*.34;s.ellipse(-8+Math.cos(a)*13,-14+Math.sin(a)*13+sw*.2,3.2,6,['#c38e63','#d7ab76','#a98a62','#d7ab76'][Math.abs(k)%4])}s.ellipse(-1,-10,11,8,'#b98d66');s.ellipse(-2,-9,6,4,'#cfa77c');s.line(8,-14,10,-20+pk,'#c9a584',3.5);s.ellipse(11,-22+pk,4.4,4.2,'#d7b695');s.ellipse(12,-18+pk,2.2,3.2,'#d46f69');s.poly([{x:14,y:-22+pk},{x:18,y:-20+pk},{x:14,y:-19+pk}],'#e0b867');s.ellipse(12,-23+pk,.9,.9,'#40463d');}
 else if(id==='quail'){const w=s.time,pk=Math.max(0,Math.sin(w*2.4))*3;s.shadow(0,1,10,4);s.line(-2,-2,-2,3,'#c9a46c',1.6);s.line(3,-2,3,3,'#c9a46c',1.6);s.ellipse(0,-7,9,7,'#b79d7e');s.ellipse(-1,-5,5,3.5,'#e1d2b6');for(const [dx,dy] of [[-4,-9],[0,-11],[3,-8]])s.ellipse(dx,dy,1.2,.8,'#8a735a');s.ellipse(8,-12+pk,4.2,4.2,'#bda586');s.ellipse(8,-10+pk,2.6,1.8,'#efe5d0');s.line(8,-16+pk,6,-21+pk,'#8a735a',1.2);s.ellipse(5.8,-21.5+pk,1.3,1.3,'#8a735a');s.poly([{x:11.5,y:-12+pk},{x:15,y:-11+pk},{x:11.5,y:-10+pk}],'#d4a55e');s.ellipse(9,-13+pk,.8,.8,'#3d4a3b');}
 else if(id==='peacock'){const w=s.time,sw=Math.sin(w*1.4)*1.5;s.shadow(0,1,15,5);for(let k=-4;k<=4;k++){const a=-Math.PI/2+k*.27,rx=-4+Math.cos(a)*21,ry=-14+Math.sin(a)*21+sw*Math.abs(k)*.1;s.line(-4,-12,rx,ry,'#9fbfa4',1.2);s.ellipse(rx,ry,3.4,4.4,'#5f9a96');s.ellipse(rx,ry,1.8,2.4,'#a9c884');s.ellipse(rx,ry,.9,1.2,'#4e6f9a')}s.line(-2,-3,-2,3,'#b59a7a',1.6);s.line(4,-3,4,3,'#b59a7a',1.6);s.ellipse(0,-9,9,6.5,'#5f94a4');s.ellipse(-1,-8,5,3.5,'#78afbc');s.line(7,-11,9,-21,'#5f94a4',4);s.ellipse(10,-24,3.8,3.6,'#6fa4b2');s.poly([{x:13,y:-24},{x:17,y:-22.5},{x:13,y:-21.5}],'#d9b36a');s.ellipse(11,-25,.8,.8,'#344843');for(const dx of [-1,1.5,4])s.line(10+dx*.5,-27,10+dx*.9,-31,'#6e9fa8',1);}
 else if(id==='angora'){const w=s.time,e=Math.sin(w*3)*.8;s.shadow(0,1,15,5);for(const dx of [-8,-4,6,10])s.line(dx,-4,dx,2,'#b6a7b2',2.4);for(let i=0;i<6;i++)s.ellipse(-10+i*4,-10+(i%2)*2,6.5,8,['#ece3ee','#e6dbe8'][i%2]);s.ellipse(0,-13,12,7,'#f3ebf4');s.ellipse(14,-13,6,7,'#e9dfe6');s.ellipse(14,-9,3.6,4,'#f0e6ea');s.line(11,-19,9,-26,'#a69aa3',1.8);s.line(17,-19,20,-26,'#a69aa3',1.8);s.ellipse(8,-15+e,2.4,4,'#d9c8d3');s.ellipse(17.5,-14,1,1,'#44504a');s.ellipse(14,-7,2.2,3,'#e1d2dd');}
 else if(id==='swan'){const w=s.time,bob=Math.sin(w*1.6)*1,g=Math.sin(w*.8)*2;s.ellipse(0+g*.3,1,20,6,'#b6d3cf');s.ellipse(0+g*.3,0,15,4.5,'#d4e6e2');s.ellipse(-2+g*.3,-7+bob,14,8,'#f5f3ee');s.poly([{x:-14+g*.3,y:-8+bob},{x:-21+g*.3,y:-12+bob},{x:-13+g*.3,y:-4+bob}],'#ece9e2');s.c.beginPath();s.c.moveTo(8+g*.3,-9+bob);s.c.bezierCurveTo(16+g*.3,-12+bob,14+g*.3,-24+bob,10+g*.3,-27+bob);s.c.strokeStyle='#f7f5f0';s.c.lineWidth=5;s.c.lineCap='round';s.c.stroke();s.ellipse(10+g*.3,-28+bob,4.4,3.8,'#f7f5f0');s.poly([{x:13+g*.3,y:-28+bob},{x:18+g*.3,y:-26.5+bob},{x:13+g*.3,y:-25.5+bob}],'#e2a56b');s.ellipse(11+g*.3,-29+bob,.9,.9,'#3b463f');s.ellipse(-4+g*.3,-8+bob,7,4,'#e9e6df');}
 else {s.shadow(0,0,9,3);s.ellipse(0,-7,9,6,'#b6a080');s.ellipse(7,-12,4,4,'#cfbea0');s.ellipse(8,-13,.8,.8,'#465847');}
 c.restore();
}
function lateAnimal(s,id){
 const bob=Math.sin(s.time*1.8)*.7;
 if(id==='silkworm'){s.shadow(0,1,12,3);s.ellipse(0,-2,15,4,'#8fab70');for(let k=0;k<6;k++)s.ellipse(-9+k*3.5,-5+Math.sin(s.time*2+k*.6),3.4,3,'#f0e9cb');s.ellipse(10,-7,.7,.7,'#6d775a');return}
 if(id==='yak'){s.shadow(0,1,22,7);for(let dx of [-13,-7,7,13])s.line(dx,-5,dx,5,'#675846',4);s.ellipse(-2,-13,23,14,'#8e7962');for(let k=0;k<8;k++)s.ellipse(-20+k*5,-9,3,11,'#9b856c');s.ellipse(19,-13+bob,9,10,'#72624f');s.ellipse(23,-9+bob,6,4,'#b6a28a');for(let d of [-1,1]){s.line(17+d*6,-21,17+d*11,-25,'#e0d3b6',2.5);s.line(17+d*11,-25,17+d*10,-30,'#e0d3b6',2)}s.ellipse(22,-16+bob,1,1,'#353e32');return}
 if(id==='ostrich'){s.shadow(0,1,18,5);for(let dx of [-7,5]){s.line(dx,-10,dx+2,6,'#c6ab89',2.4);s.line(dx+2,6,dx+7,7,'#c6ab89',1.8)}s.ellipse(-3,-19,17,12,'#6e7066');s.ellipse(-5,-18,12,7,'#efe8d2');s.line(11,-22,14,-42+bob,'#d3bea1',4);s.ellipse(16,-44+bob,5,4,'#e5d4b7');s.ellipse(18,-45+bob,.9,.9,'#48503e');s.poly([{x:20,y:-44+bob},{x:26,y:-42+bob},{x:20,y:-41+bob}],'#c7a070');return}
 s.shadow(0,1,21,5);for(let k=0;k<4;k++)s.line(-7,-9,-34-k*2,-17+k*2+Math.sin(s.time)*2,['#ab8254','#d8b268'][k%2],3);for(let dx of [-3,6])s.line(dx,-3,dx,3,'#bd9a63',1.8);s.ellipse(0,-10,12,8,'#c08855');s.ellipse(-3,-10,8,5,'#ba9c64');s.line(9,-13,11,-22,'#bb874f',4);s.ellipse(12,-24,5,5,'#ddb553');s.ellipse(13,-25,1,1,'#435142');s.poly([{x:16,y:-24},{x:21,y:-22},{x:16,y:-21}],'#d7bd87');for(let k=0;k<3;k++)s.line(7,-21+k*2,15,-18+k*2,'#7f694b',1);
}
function helper(s,x,y,id,working){
 const c=s.c;c.save();c.translate(x,y);s.shadow(0,0,10,5);
 // Lumberjack Stepan is a person, not a forest animal: the approved figure from lumberjack_art.js, saw on the shoulder,
 // a little smaller than in the mini-game so he stands with the other helpers by the barn.
 if(id==='lumberjack'){drawFigure(c,0,0,'stepan','stand',{scale:.8,shadow:false});c.restore();return;}
 const visualId={beaver_artisan_2:'beaver_artisan',badger_artisan_2:'badger_artisan'}[id]||id;
 let col={rabbit_gardener:'#d5bb94',mole_gardener:'#a79786',raccoon:'#a8afa4',shepherd:'#bb9d72',hedgehog:'#ad9073',squirrel:'#c2966d',fox_picker:'#e0955a',hamster_reaper:'#e3c9a2',cat_keeper:'#c5bdb0',beaver_artisan:'#a37c58',badger_artisan:'#8f9388'}[visualId]||'#c4b79a';
 if(visualId==='beaver_artisan')s.ellipse(-10,-4,9,4,'#6f5a46');
 if(visualId==='fox_picker')s.ellipse(-9,-9,8,5,'#f0f0e2');
 if(visualId==='squirrel')s.ellipse(-9,-13,7,12,'#b5855d');
 if(visualId==='hedgehog')for(let a=0;a<8;a++){const t=a*Math.PI/7;s.line(Math.cos(t)*10,-6-Math.sin(t)*12,Math.cos(t)*14,-6-Math.sin(t)*16,'#957b62',2);}
 s.ellipse(0,-10,10,12,col);s.ellipse(0,-23,8,8,col);
 if(visualId==='rabbit_gardener')for(let dx of [-4,4])s.ellipse(dx,-36,3,10,col);
 else for(let dx of [-6,6])s.ellipse(dx,-28,3.5,5,col);
 if(visualId==='raccoon')rect(s,-8,-25,16,6,'#69756a',3);
 if(visualId==='shepherd'){s.ellipse(-6,-21,3,7,'#8d775c');s.ellipse(6,-21,3,7,'#8d775c');}
 for(let dx of [-3,3])s.ellipse(dx,-24,1,1,'#3d5849');
 s.ellipse(0,-20,2,1.5,'#7b715a');rect(s,-7,-13,14,13,'#7e9b7b',3);
 if(visualId==='hamster_reaper'){s.ellipse(-6,-21,2.6,2,'#efb9a4');s.ellipse(6,-21,2.6,2,'#efb9a4');}
 if(visualId==='cat_keeper')for(let d of [-1,1]){s.line(d*3,-20,d*10,-22,'#8f877b',.8);s.line(d*3,-19,d*10,-18,'#8f877b',.8);}
 if(visualId==='beaver_artisan')rect(s,-1.5,-19,3,3,'#fffcee',1);
 if(visualId==='badger_artisan'){s.line(-3,-30,-3,-17,'#4f554d',2);s.line(3,-30,3,-17,'#4f554d',2);}
 if(working){c.save();c.translate(0,s.motion?Math.sin(s.time*2.6)*1.8:0);s.line(8,-11,17,-5,'#a1b19c',3);rect(s,13,-5,9,7,id==='rabbit_gardener'?'#8dbbb7':'#c6a875',2);c.restore();}
 c.restore();
}
// A rectangle of the land seen from above: used for helper zones and for the bulk-action area preview.
function zoneBox(s,z,fill,stroke,dashed){
 const c=s.c;c.save();c.beginPath();
 [P(z.x,z.y,1),P(z.x+z.w,z.y,1),P(z.x+z.w,z.y+z.h,1),P(z.x,z.y+z.h,1)].forEach((q,i)=>i?c.lineTo(q.x,q.y):c.moveTo(q.x,q.y));
 c.closePath();c.fillStyle=fill;c.fill();c.lineWidth=2.2;c.strokeStyle=stroke;if(dashed)c.setLineDash([9,6]);c.stroke();c.restore();
}
const ZONE_COLORS=[['#7fb59a22','#4f8f77'],['#d8a35a22','#b9803a'],['#8aa6d822','#5f7fb8'],['#c88ab822','#a2628f'],['#a9bf6a22','#7f9a3f'],['#d98a7a22','#b86556']];
// A crew member works from clear ground beside its task, never from the bed itself. Layout uses the farm
// snapshot only; animation is a small movement within that reserved space, not a route through buildings.
const intersects=(a,b)=>a.x0<b.x1&&a.x1>b.x0&&a.y0<b.y1&&a.y1>b.y0;
function crewBox(p,machine,pad=0){return {x0:p.x-(machine?30:18)-pad,x1:p.x+(machine?40:29)+pad,y0:p.y-(machine?49:48)-pad,y1:p.y+11+pad};}
function taskBox(o){
 const p=P(o.x+(o.w||1)/2,o.y+(o.h||1)/2),half=((o.w||1)+(o.h||1))*18;
 if(o.type==='road')return {x0:p.x-36,x1:p.x+36,y0:p.y-18,y1:p.y+18};
 if(o.type==='plot')return {x0:p.x-36,x1:p.x+36,y0:p.y-52,y1:p.y+20};
 if(o.type==='tree')return {x0:p.x-64,x1:p.x+64,y0:p.y-145,y1:p.y+26};
 return {x0:p.x-Math.max(half,46),x1:p.x+Math.max(half,46),y0:p.y-(o.type==='mill'?150:100),y1:p.y+half/2+14};
}
function crewMembers(farm,catalog,now){
 return ['equipment','helpers'].flatMap(kind=>Object.entries(farm[kind]||{}).sort(([a],[b])=>a.localeCompare(b)).map(([id,v])=>({
  id,machine:kind==='equipment',role:catalog?.[kind]?.[id]?.role,zone:v.zone,
  active:!!(v.shift?.status==='working'&&v.shift.until>now||v.active||(kind==='equipment'&&v.last_run_at&&now-v.last_run_at<12))
 })));
}
function crewTargets(farm,member,workshops){
 const z=member.zone,inZone=o=>!z||(o.x>=z.x&&o.y>=z.y&&o.x<z.x+z.w&&o.y<z.y+z.h);
 return (farm.objects||[]).filter(o=>inZone(o)&&(
  ['sow','reap','water','harvest','roots'].includes(member.role)?o.type==='plot'||(o.type==='tree'&&['water','harvest'].includes(member.role)):
  member.role==='animals'?!!o.animal:
  ['production','craft'].includes(member.role)?workshops.has(o.type):false));
}
// Exported for geometric tests. No saved state, timers, rewards or random choices are changed here.
export function crewLayout(farm,catalog,now){
 const size=farm.size||8,objects=farm.objects||[],members=crewMembers(farm,catalog,now),reserved=[],out=[];
 const occupied=new Set();for(const o of objects)for(let x=o.x;x<o.x+(o.w||1);x++)for(let y=o.y;y<o.y+(o.h||1);y++)occupied.add(`${x},${y}`);
 const blockers=objects.map(taskBox),workshops=new Set(Object.values(catalog?.recipes||{}).map(r=>r.building));
 for(const patch of farm.meadow_view?.patches||[]){const [x,y]=patch.cell.split(',').map(Number);occupied.add(patch.cell);const p=P(x+.5,y+.5);blockers.push({x0:p.x-19,x1:p.x+19,y0:p.y-18,y1:p.y+8});}
 const cells=[];for(let y=0;y<size;y++)for(let x=0;x<size;x++)if(!occupied.has(`${x},${y}`))cells.push({x:x+.5,y:y+.5,p:P(x+.5,y+.5)});
 const barn=objects.find(o=>o.type==='barn')||objects.find(o=>o.type==='house'),rest=barn?{x:barn.x+(barn.w||1)/2,y:barn.y+(barn.h||1)/2}:{x:.5,y:size-.5};
 for(const member of members){
  const targets=member.active?crewTargets(farm,member,workshops):[],active=member.active&&targets.length>0;
  let best=null,bestScore=Infinity,targetId=null;
  for(const cell of cells){
   const box=crewBox(cell.p,member.machine,5);
   if(blockers.some(b=>intersects(box,b))||reserved.some(b=>intersects(box,b)))continue;
   let distance=Infinity,nearest=null;
   for(const target of active?targets:[rest]){const x=target.x+(target.w||0)/2,y=target.y+(target.h||0)/2,d=(cell.x-x)**2+(cell.y-y)**2;if(d<distance){distance=d;nearest=target.id||null;}}
   // Large vehicles prefer the outer service area; helpers rest close to the barn.
   const edge=Math.min(cell.x,cell.y,size-cell.x,size-cell.y),score=distance+(member.machine?edge*edge*2:0);
   if(score<bestScore){best=cell;bestScore=score;targetId=nearest;}
  }
  // With no clear space the crew stays inside, instead of covering crops, doors or another crew member.
  if(!best)continue;
  reserved.push(crewBox(best.p,member.machine,5));
  out.push({...member,active,x:best.x,y:best.y,targetId});
 }
 return out;
}
function crewSprites(s,drawing=false){
 if(!s.farm)return [];
 const old=s.crewLayoutCache,sameSnapshot=old&&old.farm===s.farm&&old.token===s.farmToken&&old.catalog===s.catalog;
 // Calm Scene.draw keeps time at zero. Refresh its status on each draw, while taps use the last drawn layout.
 // A shift ending between drawing and tapping must not move the vehicle's hit target in the same frame.
 if(!sameSnapshot||old.frame!==s.time||drawing&&!s.motion){
  const now=s.now(),key=JSON.stringify(crewMembers(s.farm,s.catalog,now));
  s.crewLayoutCache={farm:s.farm,token:s.farmToken,key,catalog:s.catalog,frame:s.time,
   layout:sameSnapshot&&old.key===key?old.layout:crewLayout(s.farm,s.catalog,now)};
 }
 return s.crewLayoutCache.layout.map((member,i)=>{
  const q=P(member.x,member.y);
  if(member.machine&&member.active&&s.motion){const step=Math.sin((s.time||0)*1.2+i)*2;q.x+=step;q.y+=step*.5;}
  const cell=isoInverse(q.x,q.y);
  return {...cell,w:0,h:0,machine:member.machine?member.id:undefined,crewId:member.id,targetId:member.targetId,wx:q.x,wy:q.y,
   draw:()=>member.machine?vehicle(s,q.x,q.y,member.id,member.active):helper(s,q.x,q.y,member.id,member.active)};
 });
}
// Off-screen figures are skipped: sprites reach ~80px sideways, ~90px up and ~30px down from their anchor.
const seen=(s,q)=>!s.view||(q.x+80>=s.view.x0&&q.x-80<=s.view.x1&&q.y+30>=s.view.y0&&q.y-90<=s.view.y1);
// After dusk the animals go home: they walk to their house door and disappear inside, and come out again after dawn.
// Hysteresis keeps them from popping in and out while the light fades.
function nightState(s){
 // Contrast dims only the painted night; the animals follow the original day/night cycle.
 const lighting=s.lightingRaw||s.lighting;
 if(!lighting)return !!s.nightFlag;
 const d=lighting.darkness||0;
 // The first reading at night means the game was opened after dark: everybody is already indoors (nightSnap), nobody runs home.
 if(s.nightFlag===undefined){s.nightFlag=d>.5;if(s.nightFlag)s.nightSnap=true}else if(!s.nightFlag&&d>.62)s.nightFlag=true;else if(s.nightFlag&&d<.4)s.nightFlag=false;
 return s.nightFlag;
}
// Pick two adjacent empty cells near each owned goose house. The straight route stays on free ground.
// Each goose also gets a "yard": the free cells around its house, the only ground it will chase a pointer over.
const GOOSE={agro:96,leash:260,run:118,home:58,hissAt:22,hiss:.95,cool:3.2,maxChase:5.5,yard:3.6};
export function resetWalkingGeese(s){
 const size=s.farm?.size||0,objects=s.farm?.objects||[],houses=objects.filter(o=>o.type==='goose_house'&&o.animal==='goose').slice(0,2);
 const previous=new Map((s.walkingGeese||[]).map(g=>[g.key,g]));
 const blocked=new Uint8Array(size*size),free=(x,y)=>x>=0&&y>=0&&x<size&&y<size&&!blocked[y*size+x];
 for(const o of objects){if(o.type==='road')continue;for(let y=Math.max(0,Math.floor(o.y));y<Math.min(size,Math.ceil(o.y+o.h));y++)for(let x=Math.max(0,Math.floor(o.x));x<Math.min(size,Math.ceil(o.x+o.w));x++)blocked[y*size+x]=1}
 const taken=new Set();s.walkingGeese=[];
 houses.forEach((house,i)=>{
  let best=null;
  for(let y=0;y<size;y++)for(let x=0;x<size;x++){
   if(!free(x,y)||taken.has(y*size+x))continue;
   for(const [dx,dy] of [[1,0],[0,1],[-1,0],[0,-1]]){
    const nx=x+dx,ny=y+dy;if(!free(nx,ny)||taken.has(ny*size+nx))continue;
    const score=Math.abs(x+.5-house.x-house.w/2)+Math.abs(y+.5-house.y-house.h/2);
    if(!best||score<best.score)best={x,y,nx,ny,score};
   }
  }
  if(!best)for(let y=0;y<size;y++)for(let x=0;x<size;x++){
   if(!free(x,y)||taken.has(y*size+x))continue;
   const score=Math.abs(x+.5-house.x-house.w/2)+Math.abs(y+.5-house.y-house.h/2);
   if(!best||score<best.score)best={x,y,nx:x,ny:y,score};
  }
  if(!best)return;
  taken.add(best.y*size+best.x);taken.add(best.ny*size+best.nx);
  const hx=house.x+house.w/2,hy=house.y+house.h/2,yard=new Set();
  for(let y=0;y<size;y++)for(let x=0;x<size;x++)if(free(x,y)&&Math.hypot(x+.5-hx,y+.5-hy)<=GOOSE.yard)yard.add(x+','+y);
  yard.add(best.x+','+best.y);yard.add(best.nx+','+best.ny);
  const dcx=Math.floor(hx),dcy=Math.floor(house.y+house.h-.1);yard.add(dcx+','+dcy);
  const key=`${s.farm.id}|${house.id}|${best.x},${best.y}|${best.nx},${best.ny}`,old=previous.get(key);
  s.walkingGeese.push({key,a:P(best.x+.5,best.y+.5),b:P(best.nx+.5,best.ny+.5),door:P(hx,house.y+house.h-.1),cells:[[best.x,best.y]],yard,phase:old?.phase??i*2.3,cool:old?.cool||0,mode:old?.mode||'idle',pos:old?.pos||null,face:old?.face||1,since:old?.since||0,last:old?.last||0,exitAt:old?.exitAt});
 });
}
// Where a calm goose is: a pure function of the scene clock, so a frozen (calm-mode) scene simply stands still.
function idleBase(s,g){
 const phase=(s.motion?s.time*.7:0)+g.phase,u=(Math.sin(phase)+1)/2;
 return {x:g.a.x+(g.b.x-g.a.x)*u,y:g.a.y+(g.b.y-g.a.y)*u,face:Math.cos(phase)*(g.b.x-g.a.x)<0?-1:1};
}
const pointerLive=(s,now)=>{const p=s.geesePointer;return p&&now<p.until?p:null};
// Advance one goose: idle -> (pointer close) chase -> hiss -> return -> idle. The state is local to the client and never reaches the server.
function updateGoose(s,g,now,night=false,snap=false){
 const base=idleBase(s,g),dt=Math.min(.05,Math.max(0,g.last?now-g.last:0));g.last=now;
 const ptr=night?null:pointerLive(s,now),dist=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
 const inYard=q=>{const c=isoInverse(q.x,q.y);return g.yard.has(Math.floor(c.x)+','+Math.floor(c.y))};
 const toward=(target,speed)=>{
  const d=dist(g.pos,target);if(d<1)return true;
  const step=Math.min(d,speed*dt),next={x:g.pos.x+(target.x-g.pos.x)/d*step,y:g.pos.y+(target.y-g.pos.y)/d*step};
  g.face=target.x>=g.pos.x?1:-1;if(!inYard(next))return false;g.pos=next;return true;
 };
 if(night&&g.mode!=='home'&&g.mode!=='inside'){if(!g.pos)g.pos={x:base.x,y:base.y};g.mode=s.motion&&!snap?'home':'inside';if(g.mode==='inside'&&g.door)g.pos={x:g.door.x,y:g.door.y};g.exitAt=undefined}
 if(g.mode==='home'){
  const d=dist(g.pos,g.door);
  if(d<4){g.mode='inside';g.exitAt=undefined}
  else{const step=Math.min(d,GOOSE.home*2*dt);g.face=g.door.x>=g.pos.x?1:-1;g.pos={x:g.pos.x+(g.door.x-g.pos.x)/d*step,y:g.pos.y+(g.door.y-g.pos.y)/d*step}} // a straight walk home, even across the yard edge
  return;
 }
 if(g.mode==='inside'){
  if(!night){if(g.exitAt===undefined)g.exitAt=now+(s.motion?(g.phase%3)+.5:0);if(now>=g.exitAt){g.mode='return';g.pos={x:g.door.x,y:g.door.y};g.exitAt=undefined}}
  return;
 }
 if(g.mode==='idle'){
  g.pos=base;g.face=base.face;
  if(ptr&&now>=g.cool&&dist(base,ptr)<GOOSE.agro){g.mode=s.motion?'chase':'hiss';g.since=now;g.pos={x:base.x,y:base.y};g.face=ptr.x>=base.x?1:-1}
 }
 if(g.mode==='chase'){
  if(!ptr||dist(g.pos,ptr)>GOOSE.leash||now-g.since>GOOSE.maxChase)g.mode='return';
  else if(dist(g.pos,ptr)<GOOSE.hissAt||!toward(ptr,GOOSE.run)){g.mode='hiss';g.since=now;g.face=ptr.x>=g.pos.x?1:-1}
 }else if(g.mode==='hiss'){
  if(ptr)g.face=ptr.x>=g.pos.x?1:-1;
  if(now-g.since>GOOSE.hiss){g.mode='return';g.cool=now+GOOSE.cool}
 }
 if(g.mode==='return'){
  if(!s.motion||dist(g.pos,base)<3){g.mode='idle';g.cool=Math.max(g.cool,now+GOOSE.cool);g.pos=base;g.face=base.face}
  else{ // a straight walk back: the door and the walking strip are not always connected through free yard cells
   const d=dist(g.pos,base),step=Math.min(d,GOOSE.home*1.6*dt);g.face=base.x>=g.pos.x?1:-1;
   g.pos={x:g.pos.x+(base.x-g.pos.x)/d*step,y:g.pos.y+(base.y-g.pos.y)/d*step};
  }
 }
}
// The pointer (mouse hover, a touching finger or a held button) in world coordinates; `down` marks a press.
export function reactWalkingGeese(s,q,under,down=false){
 if(!(s.walkingGeese?.length||s.livestock?.length)||s.placement)return;
 s.geesePointer={x:q.x,y:q.y,until:Infinity,down};s.dirty=true;
}
export function releaseWalkingGeese(s,grace=1.4){
 const p=s.geesePointer;if(p)p.until=Math.min(p.until,performance.now()/1000+grace);
}
// ---- Living livestock -------------------------------------------------------------------------------
// Animals that used to stand fixed beside their house now live in a yard: the front strip of the house footprint.
// They wander, graze, peck or lie down, and a pointer (mouse or finger) close by startles them. All of it is local
// to the client: nothing here is stored or sent. Sprites are merged into the depth pass with parentId = the house,
// so an animal is always painted after its own house and sorted against everything else by its ground point.
const STATIC_ANIMALS=new Set(['bees','goose','duck','swan','silkworm']);
const LIVE_DEFAULT={speed:.38,graze:true,peck:false,lie:true,flee:1.3,hop:false,say:null,n:1};
const LIVE={
 chicken:{speed:.8,graze:false,peck:true,lie:false,flee:2.6,hop:true,say:'Куд-кудах!',n:2},
 pig:{speed:.5,flee:1.1,hop:true,say:'Хрю!'},
 cow:{speed:.3,say:'Му-у!'},
 calf:{speed:.45,hop:true,say:'Му!'},
 sheep:{speed:.38,flee:1.5,say:'Бе-е!'},
 angora:{speed:.38,flee:1.5,say:'Бе-е!'},
 goat:{speed:.55,hop:true,say:'Ме-е!'},
 alpaca:{speed:.4,say:null},
 yak:{speed:.28,say:'Му-у!'},
 rabbit:{speed:.9,graze:false,lie:false,hop:true,flee:3.1,say:null},
 turkey:{speed:.5,graze:false,peck:true,lie:false,say:'Бул-бул!'},
 quail:{speed:.7,graze:false,peck:true,lie:false,flee:2.4,hop:true,say:null},
 peacock:{speed:.4,graze:false,lie:false,say:null},
 ostrich:{speed:.55,graze:false,lie:false,flee:2.2,say:null},
};
const liveCfg=kind=>({...LIVE_DEFAULT,...(LIVE[kind]||{})});
export const livestockMoves=o=>!!o.animal&&o.type!=='duckpond'&&!STATIC_ANIMALS.has(o.animal);
const REACT_R=58,REACT_COOL=2.6;
function rng(seed){let t=seed>>>0;return()=>{t=(t+0x6D2B79F5)>>>0;let r=Math.imul(t^t>>>15,1|t);r=r+Math.imul(r^r>>>7,61|r)^r;return((r^r>>>14)>>>0)/4294967296}}
function hashKey(text){let h=2166136261;for(let i=0;i<text.length;i++){h^=text.charCodeAt(i);h=Math.imul(h,16777619)}return h>>>0}
// Yard of a house: the thin strip along the front edge of its footprint, where its animals have always stood (the pen art lies there).
// Deeper inside the footprint is the roof and walls, which an animal must never walk over.
// When the ground right in front of the house is free (no other building, bed or the land edge) the yard reaches a little way out onto it.
function yardOf(o,objects,size){
 const front=o.y+o.h,row=Math.floor(front),free=front<size&&!objects.some(q=>q!==o&&q.type!=='road'&&q.x<o.x+o.w&&q.x+q.w>o.x&&q.y<=row&&q.y+q.h>row);
 return {x0:o.x+.2,x1:o.x+Math.max(.9,o.w-.2),y0:front-.3,y1:free?front+.32:front-.08};
}
export function resetLivestock(s){
 const previous=new Map((s.livestock||[]).map(l=>[l.key,l])),out=[];
 for(const o of s.farm?.objects||[]){
  if(!livestockMoves(o))continue;
  const cfg=liveCfg(o.animal),yard=yardOf(o,s.farm.objects||[],s.farm.size||12),door={x:o.x+o.w/2,y:o.y+o.h-.12};
  for(let i=0;i<cfg.n;i++){
   const key=`${s.farm.id}|${o.id}|${o.animal}|${i}|${o.x},${o.y},${o.w},${o.h}`,old=previous.get(key),rand=rng(hashKey(key));
   out.push(old||{key,kind:o.animal,parentId:o.id,cfg,yard,door,rand,x:yard.x0+(yard.x1-yard.x0)*(.25+.5*rand()),y:yard.y0+(yard.y1-yard.y0)*(.2+.6*rand()),
    face:rand()<.5?-1:1,mode:'stand',until:rand()*3,tx:0,ty:0,speed:0,cool:0,said:-99,sayCool:0,last:0,phase:rand()*6.28});
  }
 }
 s.livestock=out;
}
function updateCreature(s,L,now,ptr,night=false,snap=false){
 const dt=Math.min(.05,Math.max(0,L.last?now-L.last:0));L.last=now;
 const cfg=L.cfg,yard=L.yard,rand=L.rand,clampIn=()=>{L.x=Math.min(yard.x1,Math.max(yard.x0,L.x));L.y=Math.min(yard.y1,Math.max(yard.y0,L.y))};
 const goTo=(x,y,speed)=>{L.tx=x;L.ty=y;L.speed=speed;L.mode=speed>cfg.speed*1.5?'flee':'walk';L.face=(x-L.x)-(y-L.y)>=0?1:-1};
 if(night&&snap&&L.mode!=='inside'){L.mode='inside';L.x=L.door.x;L.y=L.door.y;L.exitAt=undefined;return}
 if(night&&L.mode!=='home'&&L.mode!=='inside'){L.mode='home';L.tx=L.door.x;L.ty=L.door.y;L.speed=cfg.speed*1.7;L.face=(L.tx-L.x)-(L.ty-L.y)>=0?1:-1;L.exitAt=undefined}
 if(L.mode==='home'){
  const dx=L.tx-L.x,dy=L.ty-L.y,d=Math.hypot(dx,dy),step=L.speed*dt;
  if(d<=step||d<.03){L.x=L.tx;L.y=L.ty;L.mode='inside';L.exitAt=undefined}else{L.x+=dx/d*step;L.y+=dy/d*step}
  return;
 }
 if(L.mode==='inside'){
  if(!night){if(L.exitAt===undefined)L.exitAt=now+rand()*8;if(now>=L.exitAt){L.mode='stand';L.until=now+1+rand()*2;L.exitAt=undefined}}
  return;
 }
 // Something close by startles it: run away inside the yard (or hop on the spot), then settle.
 if(ptr&&now>=L.cool&&L.mode!=='flee'&&L.mode!=='hop'){
  const q=P(L.x,L.y);
  if(Math.hypot(q.x-ptr.x,q.y-ptr.y)<REACT_R){
   L.cool=now+REACT_COOL;
   // Voices are rare: a third of the scares, and never twice within twenty seconds.
   if(cfg.say&&now>=L.sayCool&&rand()<.33){L.said=now;L.sayCool=now+20}
   if(cfg.flee&&cfg.speed>0){
    const pc=isoInverse(ptr.x,ptr.y);let best=null,far=-1;
    for(const [x,y] of [[yard.x0,yard.y0],[yard.x1,yard.y0],[yard.x0,yard.y1],[yard.x1,yard.y1]]){const d=Math.hypot(x-pc.x,y-pc.y);if(d>far){far=d;best=[x,y]}}
    goTo(best[0],best[1],cfg.speed*cfg.flee*1.9);L.until=now+1.4;
   }else{L.mode='hop';L.until=now+.7}
   if(cfg.hop&&L.mode!=='flee'){L.mode='hop';L.until=now+.7}
  }
 }
 if(L.mode==='walk'||L.mode==='flee'){
  const dx=L.tx-L.x,dy=L.ty-L.y,d=Math.hypot(dx,dy),step=L.speed*dt;
  if(d<=step||d<.02||(L.mode==='flee'&&now>L.until)){L.mode='stand';L.until=now+.4+rand()*1.6}
  else{L.x+=dx/d*step;L.y+=dy/d*step;clampIn()}
 }else if(now>=L.until){
  const r=rand();
  if(L.mode==='stand'||L.mode==='hop'||L.mode==='graze'||L.mode==='lie'){
   if(r<.38||cfg.speed<=0)goTo(yard.x0+(yard.x1-yard.x0)*rand(),yard.y0+(yard.y1-yard.y0)*rand(),cfg.speed);
   else if(r<.68&&(cfg.graze||cfg.peck)){L.mode='graze';L.until=now+2+rand()*3.5}
   else if(r<.84&&cfg.lie){L.mode='lie';L.until=now+6+rand()*8}
   else{L.mode='stand';L.until=now+1+rand()*2.5}
  }
 }
}
function paintCreature(s,L,now){
 const q=P(L.x,L.y),c=s.c,t=s.time||0,m=L.mode,cfg=L.cfg;
 c.save();c.translate(q.x,q.y);
 let lift=0;
 if(m==='hop')lift=-Math.abs(Math.sin((now-(L.until-.7))*Math.PI*3.2))*9;
 else if(m==='flee'||(m==='walk'&&cfg.hop))lift=-Math.abs(Math.sin(now*(m==='flee'?18:9)+L.phase))*(cfg.hop?3.2:1.6);
 else if(m==='walk')lift=-Math.abs(Math.sin(now*5+L.phase))*.9;
 c.translate(0,lift);c.scale(L.face,1);
 if(m==='graze'){const k=cfg.peck?Math.abs(Math.sin(now*7+L.phase)):.6+.4*Math.sin(now*2.3+L.phase);c.rotate((cfg.peck?.38:.2)*k)}
 else if(m==='lie'){c.translate(0,3);c.scale(1,.66)}
 if(L.kind==='chicken')s.chicken(0,0);else s.drawAnimal(L.kind,{x:0,y:0});
 c.restore();
 if(cfg.say&&now-L.said<.9){
  c.save();c.font='bold 10px sans-serif';c.textAlign='center';c.lineWidth=3;c.lineJoin='round';c.lineCap='round';c.miterLimit=2;c.strokeStyle='#fff8e0b0';c.fillStyle='#6d4a3d';
  c.strokeText(cfg.say,q.x,q.y-40+lift);c.fillText(cfg.say,q.x,q.y-40+lift);c.restore();
 }
}
export function drawTeaArbor(s,at,stage){
 // Drawn around the origin and scaled up a little, so it reads as a real pavilion next to the farm buildings.
 const K=1.22,c=s.c;c.save();c.translate(at.x,at.y);c.scale(K,K);
 try{arborArt(s,at,stage,K)}finally{c.restore()}
}
function arborArt(s,at,stage,K){
 const p={x:0,y:0},x=0,y=0,dk=s.lighting?.darkness||0,post=stage>=2?'#a6845f':'#b89b70',glow=(gx,gy)=>s.lanternLights?.push({x:at.x+gx*K,y:at.y+gy*K});
 if(stage<1){
  // A chosen but unbuilt project: survey stakes and tape mark the plot.
  const q=[[-30,3],[0,-12],[30,3],[0,18]];
  s.ellipse(x,y+4,36,14,'#c9b98a26');
  q.forEach(([dx,dy],i)=>{const [ex,ey]=q[(i+1)%4];s.line(x+dx,y+dy-14,x+ex,y+ey-14,'#d96f5e',1.3)});
  for(const [dx,dy] of q){s.line(x+dx,y+dy,x+dx,y+dy-17,'#c9a36a',2.4);s.ellipse(x+dx,y+dy-17,1.8,1.2,'#e9d29d')}
  return;
 }
 const pt=(dx,dy)=>({x:x+dx,y:y+dy});
 // soil, flagstones to the path, and the stone base with two visible faces
 s.ellipse(x+4,y+10,46,18,'#4a6a3a22');
 for(const [dx,dy,r] of [[40,-5,5],[52,-11,4.2],[63,-17,3.6]])s.ellipse(x+dx,y+dy,r*1.5,r*.75,'#cfc9b0');
 s.poly([pt(-30,3),pt(0,18),pt(0,26),pt(-30,11)],'#a9a590');
 s.poly([pt(30,3),pt(0,18),pt(0,26),pt(30,11)],'#8f8b78');
 s.poly([pt(-30,3),pt(0,-12),pt(30,3),pt(0,18)],'#d6d0b5','#8d8670',1.2);
 s.poly([pt(-9,17),pt(9,17),pt(13,23),pt(-13,23)],'#c4bea4');
 s.line(x-15,y-4,x+15,y+11,'#c0b99d',.8);s.line(x+15,y-4,x-15,y+11,'#c0b99d',.8);
 const stand=(dx,dy,h=36)=>{s.line(x+dx,y+dy,x+dx,y+dy-h,post,3.6);s.ellipse(x+dx,y+dy-h,2.6,1.6,'#e4ce9f');s.ellipse(x+dx,y+dy,3.4,1.5,'#9d8a68')};
 const rail=(a,b,z)=>s.line(x+a[0],y+a[1]-z,x+b[0],y+b[1]-z,post,2);
 stand(0,-8);                                   // back post
 stand(-24,3);stand(24,3);                      // side posts
 rail([-24,3],[0,-8],10);rail([-24,3],[0,-8],19);rail([0,-8],[24,3],10);rail([0,-8],[24,3],19);
 for(let i=1;i<6;i++){const t=i/6;s.line(x-24+t*24,y+3-t*11-10,x-24+t*24,y+3-t*11-19,'#cdb389',1);s.line(x+t*24,y-8+t*11-10,x+t*24,y-8+t*11-19,'#cdb389',1)}
 // bench along the back rails, a small round table with tea in the middle
 s.poly([pt(-20,2),pt(0,-8),pt(0,-3),pt(-20,7)],'#b99a6c','#8a6f49',.8);s.poly([pt(0,-8),pt(20,2),pt(20,7),pt(0,-3)],'#c3a577','#8a6f49',.8);
 s.line(x,y+11,x,y+4,'#8a6f49',3);s.ellipse(x,y+3,11,5,'#a8875e');s.ellipse(x,y+2,9,3.8,'#c2a073');
 s.ellipse(x-3,y,3.4,2.4,'#eee4c6');s.ellipse(x-3,y-2.5,2,1.6,'#eee4c6');s.line(x-6,y-1.5,x-8,y+.5,'#d7cfb0',1);s.ellipse(x+4,y+1,1.7,1.2,'#e8d2d2');s.ellipse(x+7,y+3,1.7,1.2,'#d7b779');
 if(s.motion)for(let i=0;i<3;i++){const ph=((s.time*.6+i*.33)%1);s.ellipse(x-3+Math.sin(s.time*2+i)*2,y-5-ph*13,1.6+ph*1.4,1.2+ph,`rgba(250,250,245,${.5*(1-ph)})`)}
 stand(0,14);                                   // front post (the front rails stay open: this is the entrance)
 if(stage<2){
  // Frame only: beams join the posts.
  const tops=[[-24,3],[0,-8],[24,3],[0,14]];
  tops.forEach(([dx,dy],i)=>{const [ex,ey]=tops[(i+1)%4];s.line(x+dx,y+dy-36,x+ex,y+ey-36,post,2.4)});
  return;
 }
 // The roof: back faces first, then the two faces we look at, with scalloped eaves and a finial.
 const A=pt(0,-66),L=pt(-38,-30),T=pt(0,-45),R=pt(38,-30),F=pt(0,-14);
 s.poly([A,L,T],'#6f8869');s.poly([A,T,R],'#78926f');
 s.poly([A,L,F],'#9cb792','#6e8264',1.2);s.poly([A,F,R],'#86a07d','#6e8264',1.2);
 s.line(A.x,A.y,F.x,F.y,'#6e8264',1);
 for(let i=1;i<4;i++){const t=i/4;s.line(A.x+(L.x-A.x)*t,A.y+(L.y-A.y)*t,A.x+(F.x-A.x)*t,A.y+(F.y-A.y)*t,'#8aa381',.8);s.line(A.x+(R.x-A.x)*t,A.y+(R.y-A.y)*t,A.x+(F.x-A.x)*t,A.y+(F.y-A.y)*t,'#7a9372',.8)}
 for(let i=0;i<=6;i++){const t=i/6;s.ellipse(L.x+(F.x-L.x)*t,L.y+(F.y-L.y)*t+1,3.4,2,'#6e8264');s.ellipse(R.x+(F.x-R.x)*t,R.y+(F.y-R.y)*t+1,3.4,2,'#6e8264')}
 s.line(A.x,A.y,A.x,A.y-10,'#c9a85d',1.6);s.ellipse(A.x,A.y-11,2.8,2.8,'#e4c978');
 // climbing flowers on the side posts and two hanging lanterns under the front eaves
 for(const [dx,dy] of [[-24,3],[24,3]])for(let k=0;k<4;k++){s.ellipse(x+dx+(k%2?-3:3),y+dy-6-k*7,3.2,2.6,'#82ad73');if(k%2)s.ellipse(x+dx+(k%2?-3:3),y+dy-7-k*7,1.7,1.5,'#e8a9b8')}
 for(const [lx,ly] of [[-24,3],[24,3]]){
  const hx=x+lx*.62,hy=y+ly*.62-28;s.line(hx,hy-8,hx,hy-3,'#6a5a3d',1);
  s.poly([{x:hx-3.2,y:hy-3},{x:hx+3.2,y:hy-3},{x:hx+2.8,y:hy+4},{x:hx-2.8,y:hy+4}],dk>.15?'#ffe9a8':'#e7d49a','#6a5a3d',.9);
  glow(hx,hy+43);
 }
}
// Ground overlays (helper zones, the bulk-action area): translucent, painted over the finished scene.
export function drawTeamZones(s){
 if(!s.farm)return;
 if(s.zones)Object.keys(s.zones).sort().forEach((id,i)=>{const z=s.zones[id];if(z){const [f,l]=ZONE_COLORS[i%ZONE_COLORS.length];zoneBox(s,z,f,l,true);}});
 if(s.areaPreview)zoneBox(s,s.areaPreview,'#f2c14e26','#d19a22',false);
}
// Machines, helpers and the goose as depth-sortable sprites: a point {x,y} in cell coordinates (w=h=0) plus draw().
// The scene merges them into the same back-to-front pass as buildings and beds, so a tractor parked behind a barn
// is hidden by it and one in front of it is not.
export function teamSprites(s){
 const out=[];
 if(!s.farm)return out;
 const add=(q,draw,machine)=>{const c=isoInverse(q.x,q.y);out.push({x:c.x,y:c.y,w:0,h:0,draw,machine,wx:q.x,wy:q.y});};
 for(const sprite of crewSprites(s,true))if(seen(s,{x:sprite.wx,y:sprite.wy}))out.push(sprite);
 if(s.farm.pranks?.some(p=>p.until>s.now())){const p=P(2.3,3.6+Math.sin(s.time*.35)*.7);if(seen(s,p))add(p,()=>s.goose(p.x,p.y,s.time));}
 const now=performance.now()/1000,night=nightState(s),snap=!!s.nightSnap;s.nightSnap=false;
 for(const g of s.walkingGeese||[]){
  updateGoose(s,g,now,night,snap);
  const q=g.pos;if(!q||g.mode==='inside'||!seen(s,q))continue;
  add(q,()=>{
   const pose=g.mode==='chase'?'run':g.mode==='hiss'?'hiss':null;
   s.c.save();s.c.translate(q.x,q.y);s.c.scale(g.face||1,1);s.goose(0,0,s.time,pose);s.c.restore();
   if(g.mode==='hiss'){
    const c=s.c;c.save();c.font='bold 11px sans-serif';c.textAlign='center';c.lineWidth=3;c.lineJoin='round';c.lineCap='round';c.miterLimit=2;c.strokeStyle='#fff8e0b0';c.fillStyle='#6d4a3d';c.strokeText('Ш-ш-ш!',q.x,q.y-39);c.fillText('Ш-ш-ш!',q.x,q.y-39);c.restore();
   }
  });
 }
 if(s.livestock?.length){
  const ptr=s.motion?pointerLive(s,now):null;
  for(const L of s.livestock){
   const q=P(L.x,L.y);
   if(!seen(s,q)){if(night&&L.mode!=='inside'){L.mode='inside';L.x=L.door.x;L.y=L.door.y;L.exitAt=undefined}continue}
   if(s.motion)updateCreature(s,L,now,ptr,night,snap);
   else L.mode=night?'inside':(L.mode==='inside'?'stand':L.mode);
   if(L.mode==='inside')continue;
   const c=isoInverse(P(L.x,L.y).x,P(L.x,L.y).y);
   out.push({x:c.x,y:c.y,w:0,h:0,parentId:L.parentId,draw:()=>paintCreature(s,L,now)});
  }
 }
 return out;
}
// Everything at once in depth order (kept for callers that do not merge with the objects).
export function drawTeam(s){drawTeamZones(s);for(const sp of teamSprites(s).sort(compareDepth))sp.draw();}
/* r9 stage 14: paid decor (dc_*) and fund rewards (fd_*). Pure drawing; animation reads s.time only. */
const T=(s,k=1,ph=0)=>Math.sin((s.time||0)*k+ph);
const pt=(x,y)=>({x,y});
const DECOR_ART={
 dc_birdbath(s,p){s.shadow(p.x,p.y,13,5);rect(s,p.x-3,p.y-16,6,16,'#b8b5a3',2);s.ellipse(p.x,p.y-18,13,5,'#c9c6b2');s.ellipse(p.x,p.y-19,10,3.4,'#a9cfd0');s.ellipse(p.x+4+T(s,2.2)*1.5,p.y-26+T(s,3)*1,2.4,2,'#c97a55');},
 dc_hedge(s,p){s.shadow(p.x,p.y,16,6);rect(s,p.x-17,p.y-16,34,17,'#6f9a64',7);for(let i=0;i<6;i++)s.ellipse(p.x-13+i*5.4,p.y-15+((i*7)%5),3.2,2.6,i%2?'#82ac73':'#5f8a58');s.ellipse(p.x-6,p.y-9,1.6,1.6,'#e7c4cf');s.ellipse(p.x+8,p.y-12,1.6,1.6,'#e7c4cf');},
 dc_flowercart(s,p){s.shadow(p.x,p.y,16,6);rect(s,p.x-14,p.y-16,28,11,'#b88f5c',3);for(let d of [-9,9]){s.ellipse(p.x+d,p.y-3,5,5,'#7a6244');s.ellipse(p.x+d,p.y-3,2,2,'#d9c9a1');}s.line(p.x+14,p.y-12,p.x+25,p.y-8,'#8f734c',2.4);['#d98ea0','#e7c66f','#a98bc8','#d98ea0','#e7c66f'].forEach((col,i)=>{s.line(p.x-10+i*5,p.y-16,p.x-10+i*5,p.y-22,'#6f9a64',1.4);s.ellipse(p.x-10+i*5,p.y-24,3.3,3.3,col);});},
 dc_fountain(s,p){s.shadow(p.x,p.y,34,14);s.ellipse(p.x,p.y-4,32,14,'#c3c1b0');s.ellipse(p.x,p.y-7,27,11,'#a9cfd3');s.ellipse(p.x,p.y-9,21,8,'#bde0e0');rect(s,p.x-4,p.y-34,8,26,'#c9c6b2',3);s.ellipse(p.x,p.y-36,10,4,'#c9c6b2');for(let i=0;i<7;i++){const a=i/7*Math.PI*2,k=(s.time*1.4+i*.31)%1;s.ellipse(p.x+Math.cos(a)*k*17,p.y-38+(k*(1-k)*-34)+k*30,1.7,2.2,'#e6f4f2');}},
 dc_gazebo(s,p){s.shadow(p.x,p.y,34,14);s.poly([pt(p.x-28,p.y-2),pt(p.x,p.y+12),pt(p.x+28,p.y-2),pt(p.x,p.y-16)],'#d8cfae');for(let d of [[-23,-3],[0,9],[23,-3],[0,-13]])s.line(p.x+d[0],p.y+d[1],p.x+d[0],p.y+d[1]-30,'#f0ead5',3);s.poly([pt(p.x-32,p.y-32),pt(p.x,p.y-60),pt(p.x+32,p.y-32),pt(p.x,p.y-22)],'#9fb98a','#7f9a6f',1.4);s.ellipse(p.x,p.y-60,3,3,'#e7c66f');},
 dc_toy_mill(s,p){s.shadow(p.x,p.y,13,5);s.poly([pt(p.x-9,p.y),pt(p.x+9,p.y),pt(p.x+5,p.y-24),pt(p.x-5,p.y-24)],'#d9c9a1');s.poly([pt(p.x-7,p.y-24),pt(p.x,p.y-33),pt(p.x+7,p.y-24)],'#b6926c');const a=s.time*1.8;for(let i=0;i<4;i++){const r=a+i*Math.PI/2;s.line(p.x,p.y-20,p.x+Math.cos(r)*13,p.y-20+Math.sin(r)*13,'#f0ead5',2.6);}s.ellipse(p.x,p.y-20,2,2,'#8f734c');},
 dc_lily_pond(s,p){s.shadow(p.x,p.y,34,14);s.ellipse(p.x,p.y-2,33,15,'#b9b59f');s.ellipse(p.x,p.y-4,29,12.5,'#8fbfc3');s.ellipse(p.x-6,p.y-6,22,8,'#a8d3d4');[[-12,-3],[8,-6],[16,0],[-2,2]].forEach(([dx,dy],i)=>{s.ellipse(p.x+dx,p.y+dy-4,6,2.6,'#6f9a64');if(i%2===0){s.ellipse(p.x+dx,p.y+dy-6,2.4,2,'#f0c9d4');}});s.ellipse(p.x+12+T(s,1.3)*3,p.y-8,2.4,1.2,'#d8a05e');},
 dc_pergola(s,p){s.shadow(p.x,p.y,32,13);for(let d of [[-22,0],[22,0],[-8,-8],[8,8]])s.line(p.x+d[0],p.y+d[1]+4,p.x+d[0],p.y+d[1]-30,'#efe6cf',3.4);for(let i=0;i<5;i++)s.line(p.x-26+i*13,p.y-34+i*1.5,p.x+3+i*13,p.y-24+i*1.5,'#cdbf9b',3);for(let i=0;i<12;i++)s.ellipse(p.x-22+i*4,p.y-31+(i%3)*3,3.2,2.6,i%2?'#6f9a64':'#85ad78');for(let i=0;i<4;i++)s.ellipse(p.x-14+i*10,p.y-26,2.4,2.4,'#a98bc8');},
 dc_garden_clock(s,p){s.shadow(p.x,p.y,10,4);rect(s,p.x-3,p.y-30,6,30,'#6f7f77',2);s.ellipse(p.x,p.y-38,13,13,'#6f7f77');s.ellipse(p.x,p.y-38,10.5,10.5,'#f2edd6');const a=s.time*.2;s.line(p.x,p.y-38,p.x+Math.cos(a)*6,p.y-38+Math.sin(a)*6,'#40524b',1.8);s.line(p.x,p.y-38,p.x+Math.cos(a*12)*8,p.y-38+Math.sin(a*12)*8,'#40524b',1.1);},
 dc_obelisk(s,p){s.shadow(p.x,p.y,14,5);s.poly([pt(p.x-11,p.y),pt(p.x+11,p.y),pt(p.x+6,p.y-52),pt(p.x-6,p.y-52)],'#a9b0a6');s.poly([pt(p.x-6,p.y-52),pt(p.x,p.y-62),pt(p.x+6,p.y-52)],'#c8cdbf');s.line(p.x-2,p.y-6,p.x-1,p.y-46,'#c8cdbf',2);for(let i=0;i<3;i++)s.line(p.x-4,p.y-14-i*13,p.x+4,p.y-14-i*13,'#8f988d',1.4);},
 dc_crystal_house(s,p){s.shadow(p.x,p.y,34,14);s.poly([pt(p.x-28,p.y-4),pt(p.x,p.y+10),pt(p.x+28,p.y-4),pt(p.x,p.y-18)],'#cfe6e2');s.poly([pt(p.x-28,p.y-4),pt(p.x,p.y+10),pt(p.x,p.y-26),pt(p.x-28,p.y-40)],'#cde6ea88','#9fc3c8',1.4);s.poly([pt(p.x+28,p.y-4),pt(p.x,p.y+10),pt(p.x,p.y-26),pt(p.x+28,p.y-40)],'#e3f3f08c','#9fc3c8',1.4);s.poly([pt(p.x-28,p.y-40),pt(p.x,p.y-26),pt(p.x+28,p.y-40),pt(p.x,p.y-54)],'#eef8f4aa','#9fc3c8',1.4);for(let i=0;i<4;i++)s.ellipse(p.x-12+i*8,p.y-12,3,5,i%2?'#d98ea0':'#7fae6e');const g=.5+.5*T(s,1.6);s.ellipse(p.x+9,p.y-34,2+g,2+g,'#ffffffcc');},
 dc_carousel(s,p){s.shadow(p.x,p.y,34,14);s.ellipse(p.x,p.y-2,30,12,'#d9c9a1');s.ellipse(p.x,p.y-6,25,9,'#b6926c');s.line(p.x,p.y-6,p.x,p.y-48,'#efe6cf',4);const a=s.time*.9;for(let i=0;i<4;i++){const r=a+i*Math.PI/2,x=p.x+Math.cos(r)*17,y=p.y-8+Math.sin(r)*6;s.line(x,y-1,x,y-30,'#cdbf9b',1.6);s.ellipse(x,y-17+T(s,3,i)*2,5,4,['#d98ea0','#e7c66f','#8fbfc3','#a98bc8'][i]);}s.poly([pt(p.x-28,p.y-44),pt(p.x,p.y-64),pt(p.x+28,p.y-44),pt(p.x,p.y-38)],'#c97a7f','#a45f66',1.4);s.ellipse(p.x,p.y-65,2.6,2.6,'#e7c66f');},
 dc_golden_scarecrow(s,p){s.shadow(p.x,p.y,14,5);s.line(p.x,p.y,p.x,p.y-40,'#c9a63e',3.4);s.line(p.x-17,p.y-27,p.x+17,p.y-27,'#c9a63e',3.4);s.poly([pt(p.x-10,p.y-30),pt(p.x+10,p.y-30),pt(p.x+7,p.y-11),pt(p.x-9,p.y-11)],'#e4c25a');s.ellipse(p.x,p.y-39,8,9,'#f0d878');s.ellipse(p.x,p.y-45,13,3.4,'#c9a63e');s.ellipse(p.x,p.y-50,7,6,'#e4c25a');const g=.5+.5*T(s,2);s.ellipse(p.x+9,p.y-45,1.6+g,1.6+g,'#fff6cc');},
 dc_harvest_monument(s,p){s.shadow(p.x,p.y,34,13);s.poly([pt(p.x-26,p.y-2),pt(p.x,p.y+11),pt(p.x+26,p.y-2),pt(p.x,p.y-15)],'#c3c1b0');s.poly([pt(p.x-17,p.y-6),pt(p.x,p.y+3),pt(p.x+17,p.y-6),pt(p.x,p.y-12)],'#d6d3c2');rect(s,p.x-8,p.y-34,16,24,'#b7b8a8',3);for(let i=-3;i<=3;i++){s.line(p.x,p.y-36,p.x+i*5,p.y-60+Math.abs(i)*3,'#d7ae4e',2.4);s.ellipse(p.x+i*5,p.y-61+Math.abs(i)*3,2.4,4,'#e7c66f');}s.line(p.x-9,p.y-37,p.x+9,p.y-37,'#8f734c',3);},
 dc_aurora_tree(s,p){s.shadow(p.x,p.y,30,12);s.line(p.x,p.y,p.x,p.y-42,'#8f7a5c',6);const cols=['#8fd3b6','#9fb4e6','#c9a3e6','#9fe0c0'];for(let i=0;i<4;i++){const w=T(s,1.1,i*1.7);s.ellipse(p.x+(i-1.5)*11+w*3,p.y-56-(i%2)*8,17-i*1.5,24,cols[i]+'cc');}for(let i=0;i<9;i++)s.ellipse(p.x+Math.sin(i*2.1+s.time*.6)*26,p.y-30-((s.time*7+i*9)%38),1.6,1.6,'#ffffffcc');},
 fd_garland(s,p){s.shadow(p.x,p.y,10,4);s.line(p.x-15,p.y,p.x-15,p.y-34,'#8b7756',2.6);s.line(p.x+15,p.y,p.x+15,p.y-34,'#8b7756',2.6);for(let i=0;i<9;i++){const t=i/8,x=p.x-15+t*30,y=p.y-33+Math.sin(t*Math.PI)*9;s.ellipse(x,y,2.6,2.6,['#e7c66f','#d98ea0','#8fbfc3','#a98bc8'][i%4]+(Math.sin(s.time*3+i)>-.2?'':'88'));}s.line(p.x-15,p.y-33,p.x+15,p.y-33,'#6f9a6488',1.2);},
 fd_pinwheel(s,p){s.shadow(p.x,p.y,8,3);s.line(p.x,p.y,p.x,p.y-30,'#b8a47a',2.4);const a=s.time*3;for(let i=0;i<4;i++){const r=a+i*Math.PI/2;s.poly([pt(p.x,p.y-32),pt(p.x+Math.cos(r)*13,p.y-32+Math.sin(r)*13),pt(p.x+Math.cos(r+.7)*8,p.y-32+Math.sin(r+.7)*8)],['#d98ea0','#e7c66f','#8fbfc3','#a98bc8'][i]);}s.ellipse(p.x,p.y-32,2.4,2.4,'#fff6df');},
 fd_cup(s,p){s.shadow(p.x,p.y,13,5);rect(s,p.x-10,p.y-7,20,7,'#8f734c',2);rect(s,p.x-2.5,p.y-19,5,12,'#d7ae4e',1);s.poly([pt(p.x-12,p.y-40),pt(p.x+12,p.y-40),pt(p.x+8,p.y-21),pt(p.x-8,p.y-21)],'#e4c25a','#b88f2f',1.2);s.ellipse(p.x,p.y-40,12,3,'#f0d878');for(let d of [-14,14])s.line(p.x+Math.sign(d)*12,p.y-38,p.x+d,p.y-32,'#c9a63e',2);const g=.5+.5*T(s,2.4);s.ellipse(p.x+5,p.y-34,1.4+g,1.4+g,'#fffbe0');},
 fd_banner(s,p){s.shadow(p.x,p.y,9,3);s.line(p.x,p.y,p.x,p.y-52,'#8b7756',3);s.ellipse(p.x,p.y-53,3,3,'#e7c66f');for(let i=0;i<8;i++){const t=i/8,t2=(i+1)/8,w=Math.sin(s.time*2.6+i*.7)*2.4*t,w2=Math.sin(s.time*2.6+(i+1)*.7)*2.4*t2;s.poly([pt(p.x+t*22,p.y-48+w),pt(p.x+t2*22,p.y-48+w2),pt(p.x+t2*22,p.y-32+w2),pt(p.x+t*22,p.y-32+w)],i%2?'#c97a7f':'#d98ea0');}s.ellipse(p.x+9,p.y-40,3,3,'#f6efd2');},
};
/* Curios of the magpie pedlar (catalog CURIO_SERIES): five series × four 1×1 pieces, curio_<series>_<0..3>.
   One material per series so a set reads together: overseas — brass and patina, fair — painted red/gold/black wood,
   road — leather and copper, stars — night-blue and glass, tea — porcelain with cobalt and gold.
   Drawn around the cell centre (translated); motion reads s.time only, so reduced motion gets a still frame. */
const BR='#c9a24e',BRL='#ecd48e',BRD='#94712f',PAT='#5f9a92',OX='#b0503f',WD='#6b4f36';
const FR='#c8564a',FRD='#9a3c35',FG='#e2b04a',FK='#2f3b34',FC='#f3e6c8';
const LE='#a8744c',LED='#7d5135',CU='#c27a4a',CUL='#e6a675',CUD='#8e5130',RW='#8b6a44';
const NV='#34416e',NB='#4f5f94',SG='#efd27a',SV='#c9d2e0';
const PO='#f6f1e6',POD='#ddd5c3',CO='#3f66aa',COL='#7d9bd0',TG='#d7ae4e';
const curio=fn=>(s,p)=>{const c=s.c;c.save();c.translate(p.x,p.y);try{fn(s,c,s.time||0,p)}finally{c.restore()}};
// Iso box around (ox,oy): a, b are half extents in cells along x and y; returns the corner function C(i,j,z).
function ibox(s,a,b,z0,z1,top,left,right,ox=0,oy=0){
 const C=(i,j,z)=>({x:ox+(i*a-j*b)*36,y:oy+(i*a+j*b)*18-z});
 s.poly([C(-1,1,z0),C(1,1,z0),C(1,1,z1),C(-1,1,z1)],left);s.poly([C(1,-1,z0),C(1,1,z0),C(1,1,z1),C(1,-1,z1)],right);
 s.poly([C(-1,-1,z1),C(1,-1,z1),C(1,1,z1),C(-1,1,z1)],top);return C;
}
// Upright cylinder in screen units (base centre x,y; height h), shaded on the right like the workshop tanks.
function drum(s,x,y,rx,ry,h,col,topCol){
 const c=s.c,PI=Math.PI;c.beginPath();c.moveTo(x-rx,y-h);c.lineTo(x-rx,y);c.ellipse(x,y,rx,ry,0,PI,0,true);c.lineTo(x+rx,y-h);c.ellipse(x,y-h,rx,ry,0,0,PI,true);c.closePath();c.fillStyle=col;c.fill();
 c.beginPath();c.moveTo(x+rx*.35,y-h+ry*.94);c.lineTo(x+rx,y-h);c.lineTo(x+rx,y);c.ellipse(x,y,rx,ry,0,0,Math.acos(.35),false);c.closePath();c.fillStyle='rgba(60,50,30,.14)';c.fill();
 if(topCol)s.ellipse(x,y-h,rx,ry,topCol);
}
function star5(s,x,y,r,col){const q=[];for(let k=0;k<10;k++){const a=-Math.PI/2+k*Math.PI/5,rr=k%2?r*.45:r;q.push(pt(x+Math.cos(a)*rr,y+Math.sin(a)*rr))}s.poly(q,col)}
function steam(s,x,y,k=1,ph=0){const t=s.time||0;for(let i=0;i<3;i++){const f=(t*.45*k+ph+i/3)%1;s.ellipse(x+Math.sin(t*1.3+i*2)*2.4*f,y-f*15,1.8+f*3,1.4+f*2.2,`rgba(255,255,255,${(.75*(1-f)).toFixed(2)})`)}}
function stroke(c,col,w){c.strokeStyle=col;c.lineWidth=w;c.lineCap='round';c.lineJoin='round';c.stroke()}
// Urn-shaped samovar body (shared by the brass one and the porcelain giant): k scales it, returns nothing.
function urn(s,c,k,y0,col,shade,flute){
 const path=()=>{c.beginPath();c.moveTo(-7*k,y0);c.quadraticCurveTo(-15*k,y0-6*k,-12.5*k,y0-18*k);c.quadraticCurveTo(-11*k,y0-25*k,-7*k,y0-26*k);c.lineTo(7*k,y0-26*k);c.quadraticCurveTo(11*k,y0-25*k,12.5*k,y0-18*k);c.quadraticCurveTo(15*k,y0-6*k,7*k,y0);c.closePath()};
 path();c.fillStyle=col;c.fill();c.save();path();c.clip();
 c.fillStyle=shade;c.fillRect(4*k,y0-30*k,14*k,32*k);
 if(flute)for(const dx of [-8,-4,0,4,8]){c.beginPath();c.moveTo(dx*k*.7,y0-1);c.quadraticCurveTo(dx*k*1.2,y0-13*k,dx*k*.75,y0-25*k);stroke(c,flute,.8)}
 c.restore();
}
function crescent(c,x,y,R,d,r){
 const xi=(R*R-r*r+d*d)/(2*d),yi=Math.sqrt(Math.max(0,R*R-xi*xi)),ao=Math.atan2(yi,xi),ai=Math.atan2(yi,xi-d);
 c.beginPath();c.arc(x,y,R,-ao,ao,true);c.arc(x+d,y,r,ai,-ai,false);c.closePath();
}
// A small bird (magpie / cuckoo), facing right; open = beak open.
function bird(s,x,y,body,belly,tail,open=false){
 s.line(x-3,y,x-9,y+2,tail,1.8);s.ellipse(x,y,4,2.6,body);s.ellipse(x+.6,y+.8,2.4,1.4,belly);
 s.ellipse(x+3.6,y-2.4,2.1,2,body);s.ellipse(x+4.3,y-2.9,.45,.45,'#f6f1e6');
 s.poly(open?[pt(x+5.4,y-2.9),pt(x+8.4,y-3.9),pt(x+5.6,y-2.2),pt(x+8,y-1.2)]:[pt(x+5.4,y-3),pt(x+8.2,y-2.3),pt(x+5.4,y-1.6)],'#e2b84a');
}
const CURIO_ART={
 // Overseas corner — brass with patina and oxblood glass.
 curio_overseas_0:curio((s,c,t,p)=>{ // Заморский фонарик: an onion-domed lantern of coloured glass on a brass crook
  const lit=(s.lighting?.darkness||0)>.15;
  s.shadow(0,0,13,5);s.ellipse(0,-1,7.5,3.2,BRD);s.ellipse(0,-2.2,6,2.4,BR);
  s.line(0,-2,0,-46,BRD,3);s.line(-.9,-4,-.9,-44,BRL,.9);
  c.beginPath();c.moveTo(0,-45);c.quadraticCurveTo(1,-53,9,-52);c.quadraticCurveTo(14.5,-51,13.5,-46);stroke(c,BRD,2.2);
  s.ellipse(0,-47,2.2,2.2,BR);s.ellipse(0,-50.5,1.3,1.3,BRL);
  c.save();c.translate(13.5,-46);c.rotate(T(s,1.3)*.09);
  s.line(0,0,0,4,BRD,1);
  c.beginPath();c.moveTo(-6,11);c.quadraticCurveTo(-6.5,6,0,4);c.quadraticCurveTo(6.5,6,6,11);c.closePath();c.fillStyle=BR;c.fill();
  for(const [dx,dy] of [[-2.8,8.8],[0,7.2],[2.8,8.8],[0,9.8]])s.ellipse(dx,dy,.7,.7,'#7a5a28');
  rect(s,-5.5,11,11,12,BRD,1.5);
  rect(s,-4.6,12,3,10,lit?'#ffb08a':'#c95a4a',1);rect(s,-1.4,12,2.8,10,lit?'#fff2b8':'#e8c35c',1);rect(s,1.6,12,3,10,lit?'#a8e4d6':PAT,1);
  s.line(-5.5,11,5.5,11,BRL,1.4);s.line(-5.5,17,5.5,17,BRD,.7);
  s.poly([pt(-6,23),pt(6,23),pt(0,29)],BR);s.line(0,29,0,32,OX,1.2);s.ellipse(0,33.6,1.5,2.1,OX);
  c.restore();
  if(lit)s.lanternLights?.push({x:p.x+13.5,y:p.y+14});
 }),
 curio_overseas_1:curio((s,c,t)=>{ // Глобус-флюгер: a patina globe threaded on a pole, a brass arrow above it turning with the wind
  s.shadow(0,0,11,4.5);
  for(const [dx,dy] of [[-8,0],[8,0],[0,4]])s.line(0,-7,dx,dy,BRD,2);s.ellipse(0,-7,2.4,1.6,BR);
  s.line(0,-6,0,-57,BRD,2.4);s.line(-.8,-8,-.8,-55,BRL,.8);
  const y=-46;s.line(-6.4,y-3.2,6.4,y+3.2,BRD,1.2);s.line(6.4,y-3.2,-6.4,y+3.2,BRD,1.2);s.ellipse(-6.4,y+3.2,1.2,1.2,OX);for(const [dx,dy] of [[6.4,3.2],[-6.4,-3.2],[6.4,-3.2]])s.ellipse(dx,y-dy,1,1,BR);
  c.save();c.beginPath();c.ellipse(0,-31,10,10,0,0,Math.PI*2);c.fillStyle=PAT;c.fill();c.clip();
  s.ellipse(5,-29,9,11,'#4c827b');
  s.ellipse(-3.5,-34,4.4,2.6,BR);s.ellipse(-1.5,-28.5,2.4,3.4,BR);s.ellipse(5,-35,2.6,1.6,BR);s.ellipse(4.4,-26,3,1.8,BRD);
  c.restore();
  c.beginPath();c.ellipse(0,-31,4,12.2,.35,0,Math.PI*2);stroke(c,BR,1.6);
  c.beginPath();c.ellipse(0,-31,10,2.8,0,0,Math.PI);stroke(c,BRL,.8);
  s.ellipse(-3.8,-35.5,2.4,1.6,'#ffffff55');
  const r=T(s,.45)*1.2+.6,dx=Math.cos(r),dy=Math.sin(r)*.5,L=Math.hypot(dx,dy),ux=dx/L,uy=dy/L,yv=-56;
  const hx=13*dx,hy=yv+13*dy,tx=-12*dx,ty=yv-12*dy;
  s.poly([pt(tx,ty),pt(tx+6*ux,ty+6*uy),pt(tx+6*ux,ty+6*uy-5),pt(tx,ty-4)],BR);
  s.line(tx,ty,hx,hy,BRD,1.6);
  s.poly([pt(hx+3*ux,hy+3*uy),pt(hx-2*ux,hy-2*uy-2.6),pt(hx-2*ux,hy-2*uy+2.6)],OX);
  s.ellipse(0,yv,1.6,1.4,BRD);s.ellipse(0,-59.5,1.8,1.8,BRL);
 }),
 curio_overseas_2:curio((s,c,t)=>{ // Самовар с петушком: a fluted brass samovar on a tray, a little rooster on the crown
  s.shadow(0,0,15,6);s.ellipse(0,-2,14,6,BRD);s.ellipse(0,-3.4,12.6,5.2,BR);s.ellipse(0,-3.6,10.5,4,'#d8b664');
  drum(s,0,-4,5,2,4,BRD,BR);
  urn(s,c,1,-8,BR,'rgba(90,60,20,.2)',BRD);
  s.line(-8.5,-12,-9.5,-28,BRL,2);
  for(const d of [-1,1]){s.line(d*11.5,-29,d*15,-30,'#3b2f25',1.4);s.ellipse(d*15.4,-28.6,1.6,2.8,'#3b2f25')}
  s.line(1,-13,7,-11,BRD,2.2);s.ellipse(7.4,-10.6,1.2,1.2,BRD);s.ellipse(4,-15,1.6,1.1,'#3b2f25');
  drum(s,0,-34,6.5,2.4,3,BRD,BRL);drum(s,0,-37,3.2,1.3,4,BRD,'#4a3a2a');
  const b=T(s,2.2)*.4;
  s.poly([pt(-2,-45),pt(-8,-53),pt(-6.5,-48),pt(-8.5,-47),pt(-3,-43)],PAT);
  s.ellipse(0,-45+b,4.2,3.2,BRL);s.ellipse(3.4,-49+b,2.2,2.2,BRL);
  s.poly([pt(2.4,-51+b),pt(3.4,-53.4+b),pt(4.2,-51.6+b),pt(5.2,-53+b),pt(5.4,-50.6+b)],OX);
  s.poly([pt(5.4,-49.6+b),pt(7.6,-48.8+b),pt(5.4,-48+b)],'#e0a03a');s.ellipse(4,-49.6+b,.5,.5,'#3b2f25');s.ellipse(4.6,-47.3+b,.9,1.2,OX);
  s.line(0,-42,0,-41,BRD,1.4);
 }),
 curio_overseas_3:curio((s,c,t,p)=>{ // Часы с кукушкой-сорокой: a carved oval clock on a post; now and then a magpie hops out of the crest
  s.shadow(0,0,10,4);s.ellipse(0,-1,6,2.5,'#5a412c');rect(s,-2.5,-34,5,33,WD,1.5);s.line(-1.4,-32,-1.4,-3,'#866446',1);
  const sw=T(s,2)*4;
  for(const d of [-5,5])s.line(d,-28,d,d<0?-18:-21,BRD,.8);
  s.ellipse(-5,-15,1.9,3.4,BR);s.ellipse(5,-18,1.9,3.4,BR);
  s.line(0,-28,sw,-15,BRD,1.2);s.ellipse(sw,-14,2.6,2.6,BR);s.ellipse(sw-.8,-14.8,.9,.9,BRL);
  for(let k=0;k<7;k++){const a=Math.PI*(1.05+k*.15);s.ellipse(Math.cos(a)*11,-46+Math.sin(a)*11,3.4,2.4,k%2?'#7a5a3c':'#8a6a48')}
  s.ellipse(0,-41,11,13,'#7a5a3c');s.ellipse(0,-41,9.4,11.4,'#8a6a48');
  s.ellipse(0,-41,7.6,7.6,BR);s.ellipse(0,-41,6.2,6.2,'#f3e7c4');
  for(let k=0;k<12;k++){const a=k*Math.PI/6;s.ellipse(Math.cos(a)*5,-41+Math.sin(a)*5,k%3?.4:.7,k%3?.4:.7,'#5a412c')}
  const a=t*.15;s.line(0,-41,Math.cos(a)*3.2,-41+Math.sin(a)*3.2,'#3b2f25',1.4);s.line(0,-41,Math.cos(a*12)*4.6,-41+Math.sin(a*12)*4.6,'#3b2f25',.9);
  s.ellipse(0,-55.5,5.4,4.6,'#7a5a3c');s.ellipse(0,-55,3.4,3.4,'#3b2f25');
  if(s.motion!==false&&((t*.1+p.x*.013)%1)>.78){s.line(0,-54,6,-54,'#5a412c',1.2);bird(s,4,-57,'#2f3138','#f1efe8','#3d5a86',((t*2)%1)>.5)}
  else{s.ellipse(0,-55,3.2,3.2,'#6b4f36');s.ellipse(1.4,-55,.7,.7,BR)}
  s.ellipse(0,-61,1.6,1.6,BR);
 }),
 // Fair — painted wood: red, gold and black-green.
 curio_fair_0:curio((s,c,t)=>{ // Ковёр-самолёт (не летает): a patterned rug on two little logs; it ripples and sometimes tries to take off
  const a=.42,b=.28,lift=Math.pow(Math.max(0,Math.sin(t*.7)),14)*5;
  const Z=(u,v)=>6+lift*(1-.3*u)+Math.sin(t*1.7+u*2.6+v*.8)*1.1;
  const Q=(u,v,dz=0)=>pt((u*a-v*b)*36,(u*a+v*b)*18-Z(u,v)-dz);
  const region=(u0,u1,v0,v1,col)=>{const q=[];for(let k=0;k<=8;k++)q.push(Q(u0+(u1-u0)*k/8,v0));for(let k=1;k<=3;k++)q.push(Q(u1,v0+(v1-v0)*k/3));for(let k=7;k>=0;k--)q.push(Q(u0+(u1-u0)*k/8,v1));for(let k=2;k>=1;k--)q.push(Q(u0,v0+(v1-v0)*k/3));s.poly(q,col)};
  s.shadow(0,0,24-lift,9-lift*.3);
  for(const u of [-.7,.7])ibox(s,.05,.24,0,5,'#c49a64','#a37a4c','#8b6a44',u*a*36,u*a*18);
  const front=[];for(let k=0;k<=8;k++)front.push(Q(-1+k/4,1));for(let k=8;k>=0;k--)front.push(Q(-1+k/4,1,-1.8));s.poly(front,FRD);
  const side=[];for(let k=0;k<=3;k++)side.push(Q(1,-1+k*2/3));for(let k=3;k>=0;k--)side.push(Q(1,-1+k*2/3,-1.8));s.poly(side,'#7f3029');
  region(-1,1,-1,1,FG);region(-.88,.88,-.82,.82,FK);region(-.82,.82,-.75,.75,FR);
  for(let k=0;k<9;k++){const u=-.8+k*.2;for(const v of [-.91,.91]){const q=Q(u,v);s.ellipse(q.x,q.y,1,.6,FRD)}}
  s.poly([Q(0,-.52),Q(.44,0),Q(0,.52),Q(-.44,0)],FK);s.poly([Q(0,-.34),Q(.28,0),Q(0,.34),Q(-.28,0)],FG);
  let q=Q(0,0);s.ellipse(q.x,q.y,1.8,1.1,FR);
  for(const [u,v] of [[-.66,-.52],[.66,-.52],[-.66,.52],[.66,.52]]){s.poly([Q(u,v-.16),Q(u+.1,v),Q(u,v+.16),Q(u-.1,v)],FG);}
  for(const [u,v] of [[-.36,.5],[.36,-.5],[-.36,-.5],[.36,.5]]){q=Q(u,v);s.ellipse(q.x,q.y,1.3,.9,FC)}
  for(const [u,v] of [[-1,-1],[-1,1],[1,-1],[1,1]]){const A=Q(u,v),B=Q(u*1.13,v);s.line(A.x,A.y,B.x,B.y+1,FG,1.2);s.ellipse(B.x,B.y+1.4,1,1.4,FG)}
 }),
 curio_fair_1:curio((s,c,t)=>{ // Карусель-шкатулка: a music-box carousel on a painted drum with a wind-up key; turns slowly
  s.shadow(0,0,14,6);
  drum(s,0,0,12,5.2,10,FR,null);
  for(let k=0;k<9;k++){const a=Math.PI*(.08+k*.105);s.ellipse(Math.cos(a)*12*.92,-5+Math.sin(a)*5.2,1.3,1.3,FG)}
  c.beginPath();c.ellipse(0,-1.6,12,5.2,0,0,Math.PI);stroke(c,FK,1.4);
  const kr=t*1.2,kw=Math.abs(Math.cos(kr));
  s.line(11.5,-5,15.5,-6,FG,1.6);s.ellipse(17.4,-6.6,2.6*kw+.6,2.4,FG);s.ellipse(17.4,-6.6,1.2*kw+.3,1.1,FRD);
  s.ellipse(0,-10,12,5.2,FC);s.ellipse(0,-10,10,4.2,'#e8d4a8');
  const a0=t*.5,horses=[];for(let i=0;i<4;i++){const r=a0+i*Math.PI/2;horses.push({r,x:Math.cos(r)*8,y:-10+Math.sin(r)*3.4,i})}
  const horse=h=>{const bob=T(s,2.4,h.i*1.6)*1.4,dir=-Math.sin(h.r)>=0?1:-1,y=h.y-9+bob;
   s.line(h.x,h.y,h.x,-33+Math.sin(h.r)*2.4,FG,1);
   for(const d of [-1.8,1.8])s.line(h.x+d,y+1,h.x+d*1.3,y+4,FC,1);
   s.ellipse(h.x,y,3.8,2.4,FC);s.ellipse(h.x,y-.6,1.8,1.6,[FR,'#5b7fb5',FR,'#5f8f5a'][h.i]);
   s.line(h.x+dir*2.6,y-1,h.x+dir*3.8,y-4,FC,1.8);s.ellipse(h.x+dir*4.4,y-4.4,1.7,1.2,FC);s.line(h.x+dir*2.8,y-2,h.x+dir*3.2,y-4.6,FRD,.8)};
  horses.filter(h=>Math.sin(h.r)<0).forEach(horse);
  s.line(0,-10,0,-38,FG,2.4);s.line(-.7,-12,-.7,-36,'#f6d888',.7);
  horses.filter(h=>Math.sin(h.r)>=0).forEach(horse);
  const seg=8,R=14,ry=5.6,ap={x:0,y:-48},rim=th=>pt(Math.cos(th)*R,-35+Math.sin(th)*ry),tris=[];
  for(let k=0;k<seg;k++){const th0=a0+k*2*Math.PI/seg,th1=th0+2*Math.PI/seg,mid=(th0+th1)/2;tris.push({k,th0,th1,d:Math.sin(mid)})}
  tris.sort((A,B)=>A.d-B.d).forEach(T2=>s.poly([ap,rim(T2.th0),rim(T2.th1)],T2.k%2?FC:(T2.d<0?FRD:FR)));
  for(let k=0;k<=10;k++){const th=Math.PI*k/10,q=rim(th);s.ellipse(q.x,q.y+1.6,1.7,1.5,k%2?FG:FR)}
  s.line(0,-48,0,-53,FK,1);s.poly([pt(0,-53),pt(5,-51.6+T(s,3)*.6),pt(0,-50)],FR);s.ellipse(0,-48,1.8,1.8,FG);
  const f=(t*.25)%1;if(s.motion!==false&&f<.7){const nx=-13-f*4,ny=-26-f*20;c.save();c.globalAlpha=1-f/.7;s.ellipse(nx,ny,1.6,1.2,FRD);s.line(nx+1.4,ny,nx+1.4,ny-5,FRD,.9);s.line(nx+1.4,ny-5,nx+3.4,ny-3.6,FRD,.9);c.restore()}
 }),
 curio_fair_2:curio((s,c,t)=>{ // Бубенцы на дугу: a painted shaft-bow standing in a log, bells on cords and ribbons under its crown
  s.shadow(0,0,15,5.5);
  ibox(s,.36,.08,0,5,'#c49a64','#a37a4c','#8b6a44');
  const A=u=>pt(u*.32*36,u*.32*18-5-40*Math.pow(Math.max(0,1-u*u),.6));
  const arc=(w,col,dz=0)=>{c.beginPath();for(let k=0;k<=20;k++){const q=A(-1+k/10);k?c.lineTo(q.x,q.y+dz):c.moveTo(q.x,q.y+dz)}stroke(c,col,w)};
  arc(6.4,FRD,.6);arc(5,FR);arc(1,FG,-1.6);
  for(let k=1;k<12;k++){const q=A(-1+k/6);s.ellipse(q.x,q.y,1.3,1.3,k%3?FG:FC);if(k%3===0){s.ellipse(q.x-1.6,q.y+.8,1.1,.7,'#5f8f5a');s.ellipse(q.x+1.6,q.y+.8,1.1,.7,'#5f8f5a')}}
  const top=A(0);
  for(const [i,d,col] of [[0,-1,'#5b7fb5'],[1,1,'#5f8f5a']]){const w=T(s,2.2,i*2)*1.6;s.poly([pt(top.x,top.y+2),pt(top.x+d*3+w,top.y+12),pt(top.x+d*5+w,top.y+11),pt(top.x+d*1.4,top.y+2)],col)}
  [-.42,0,.42].forEach((u,i)=>{const q=A(u),len=u?7:11,sw=T(s,2.6,i*1.9)*1.6,bx=q.x+sw,by=q.y+len+3.6;
   s.line(q.x,q.y+1,bx,by-3,'#5a412c',.9);s.ellipse(bx,by,3.6,3.6,FG);s.ellipse(bx+1.2,by+.6,2.2,2.6,'#c48f2c');s.ellipse(bx-1.2,by-1.3,1.2,1,'#fff3c0');s.line(bx-2.2,by+1,bx+2.2,by+1,'#7a5a1c',.9);s.ellipse(bx,by+2,.8,.8,'#7a5a1c')});
  s.ellipse(top.x,top.y+1.5,2.4,1.8,FR);s.ellipse(top.x,top.y+1.5,1,1,FG);
 }),
 curio_fair_3:curio((s,c,t)=>{ // Расписной сундучок: a red chest with a rounded lid, iron straps, painted flowers and a brass lock
  s.shadow(0,0,19,7);
  const a=.27,b=.17,C=ibox(s,a,b,1,12,FR,FR,'#a8453c'),zl=v=>12+5.5*Math.cos(v*Math.PI/2);
  s.poly([C(-1,1,1),C(1,1,1),C(1,1,3),C(-1,1,3)],FK);s.poly([C(1,-1,1),C(1,1,1),C(1,1,3),C(1,-1,3)],'#252e29');
  for(let k=0;k<8;k++){const v0=-1+k/4,v1=v0+.25;s.poly([C(-1,v0,zl(v0)),C(1,v0,zl(v0)),C(1,v1,zl(v1)),C(-1,v1,zl(v1))],['#d86a5c','#d86a5c','#d4655a','#ce6056','#c8564a','#bf5046','#b44a41','#a8453c'][k])}
  const cap=[];for(let k=0;k<=8;k++){const v=-1+k/4;cap.push(C(1,v,zl(v)))}s.poly(cap,FRD);
  for(const u of [-.8,.8]){c.beginPath();for(let k=3;k<=8;k++){const v=-1+k/4,q=C(u,v,zl(v));k>3?c.lineTo(q.x,q.y):c.moveTo(q.x,q.y)}const d=C(u,1,1);c.lineTo(d.x,d.y);stroke(c,'#4a3f38',1.7)}
  c.beginPath();for(let k=0;k<=8;k++){const v=-1+k/4,q=C(1,v,zl(v));k?c.lineTo(q.x,q.y):c.moveTo(q.x,q.y)}stroke(c,'#4a3f38',1.4);
  let q=C(1,1,12);s.line(C(-1,1,12).x,C(-1,1,12).y,q.x,q.y,'#7f3029',1.2);
  for(const u of [-.46,.46]){const f=C(u,1,6.5);s.ellipse(f.x-2,f.y+.6,1.6,.9,'#5f8f5a');s.ellipse(f.x+2,f.y-.6,1.6,.9,'#5f8f5a');s.ellipse(f.x,f.y,2.3,2.3,FG);s.ellipse(f.x,f.y,1,1,FC)}
  for(const [u,v] of [[-.2,.55],[.25,.3],[.0,.8]]){const f=C(u,v,zl(v)+.2);s.ellipse(f.x,f.y,1.2,.7,FG)}
  q=C(0,1,8);rect(s,q.x-2.4,q.y-3.4,4.8,5.6,FG,1);s.ellipse(q.x,q.y-1,.8,.8,'#4a3a2a');s.line(q.x,q.y-1,q.x,q.y+1,'#4a3a2a',.8);
  const g=Math.max(0,T(s,1.5)),r=g*g*2.4;if(r>.3){s.line(q.x+2-r,q.y-3,q.x+2+r,q.y-3,'#fffbe0',.8);s.line(q.x+2,q.y-3-r,q.x+2,q.y-3+r,'#fffbe0',.8)}
  for(const P2 of [C(-1,1,1),C(1,1,1),C(1,-1,1)])s.ellipse(P2.x,P2.y-1,1.5,1.2,'#4a3f38');
 }),
 // Road — saddle leather and copper.
 curio_road_0:curio((s,c,t,p)=>{ // Фонарь-компас: a copper lantern on a strapped suitcase, a compass on its cap
  const lit=(s.lighting?.darkness||0)>.15;
  s.shadow(0,0,16,6.5);
  const C=ibox(s,.25,.15,0,10,'#b88458',LE,LED);
  for(const u of [-.5,.5]){const A=C(u,-1,10.1),B=C(u,1,10.1),D=C(u,1,0);s.line(A.x,A.y,B.x,B.y,'#5a3a26',1.6);s.line(B.x,B.y,D.x,D.y,'#5a3a26',1.6);rect(s,B.x-1.6,B.y+1.6,3.2,3,CU,.6)}
  for(const [i,j] of [[-1,1],[1,1],[1,-1]]){const q=C(i,j,1);s.ellipse(q.x,q.y-1,1.6,1.6,CU)}
  const h=C(-.1,1,7);c.beginPath();c.ellipse(h.x,h.y,3.6,2,0,Math.PI,0,false);stroke(c,'#5a3a26',1.4);
  drum(s,0,-9,6.4,2.8,3,CUD,CU);
  drum(s,0,-12,5,2.2,11,lit?'#ffe9a8':'#e8dcc0',null);
  s.ellipse(0,-17.5,1.7,3.2,lit?'#fff7d6':'#f2b14a');s.ellipse(0,-16.5,.9,1.6,lit?'#ffffff':'#ffe09a');
  for(const dx of [-4.3,-1.6,1.6,4.3])s.line(dx,-12+Math.abs(dx)*.1,dx,-23,CUD,1);
  drum(s,0,-23,6.4,2.8,3,CUD,CU);
  s.ellipse(0,-26,5.2,2.3,'#f3ead2');c.beginPath();c.ellipse(0,-26,5.2,2.3,0,0,Math.PI*2);stroke(c,CUD,.8);
  for(let k=0;k<4;k++){const a=k*Math.PI/2;s.ellipse(Math.cos(a)*4.2,-26+Math.sin(a)*1.85,.45,.35,'#5a3a26')}
  const r=T(s,.8)*.5+T(s,2.3)*.12-.6,nx=Math.cos(r)*4,ny=Math.sin(r)*1.75;
  s.line(0,-26,nx,-26+ny,FR,1.3);s.line(0,-26,-nx,-26-ny,'#3b3430',1.3);s.ellipse(0,-26,.7,.5,CUD);
  c.beginPath();c.ellipse(0,-27,4.6,7,0,Math.PI*1.08,Math.PI*1.92,false);stroke(c,CUD,1.1);
  if(lit)s.lanternLights?.push({x:p.x,y:p.y+26});
 }),
 curio_road_1:curio((s,c,t)=>{ // Подзорная труба на штативе: a copper spyglass with a leather grip on a wooden tripod, slowly scanning
  s.shadow(0,0,13,5);
  for(const [dx,dy] of [[-11,0],[11,-2],[2,5]]){s.line(0,-30,dx,dy,RW,2.2);s.ellipse(dx,dy,1.2,.9,CUD)}
  s.ellipse(0,-30.5,2.8,2,CUD);
  c.save();c.translate(0,-32);c.rotate(-.42+T(s,.35)*.12);
  rect(s,-15,-1.6,6,3.2,CUD,1);s.ellipse(-15,0,.9,1.6,'#3b3430');
  rect(s,-9,-2.7,10,5.4,'#7d5135',1.2);for(const x of [-7,-4,-1])s.line(x,-2.7,x,2.7,'#5a3a26',.6);
  rect(s,1,-2.5,8,5,CU,1);s.line(1,-1.7,9,-1.7,CUL,.9);
  rect(s,9,-3,7,6,CU,1);s.line(9,-2.2,16,-2.2,CUL,.9);
  rect(s,16,-3.7,3.4,7.4,CUD,1.2);s.ellipse(19.6,0,1.3,3.3,'#a9d0dc');s.ellipse(19.4,-1.2,.5,1,'#ffffffcc');
  for(const x of [1,9,16])s.line(x,-3,x,3,CUD,.7);
  c.restore();
  c.beginPath();c.moveTo(-6,-31.6);c.quadraticCurveTo(-4,-20,1,-30);stroke(c,'#5a3a26',1);
 }),
 curio_road_2:curio((s,c,t)=>{ // Почтовый рожок: a striped verst post with a coiled copper post horn and a leather mailbag
  s.shadow(0,0,12,4.5);s.ellipse(0,-.5,5,2.2,'#9a8c74');
  c.save();c.beginPath();c.rect(-3.5,-46,7,46);c.clip();c.fillStyle='#efe9da';c.fillRect(-3.5,-46,7,46);
  for(let k=-1;k<7;k++)s.poly([pt(-3.6,-42+k*8),pt(3.6,-46+k*8),pt(3.6,-42+k*8),pt(-3.6,-38+k*8)],'#3b3430');
  c.fillStyle='rgba(40,30,20,.16)';c.fillRect(1.2,-46,2.4,46);c.restore();
  s.poly([pt(-4.4,-46),pt(0,-51),pt(4.4,-46)],'#3b3430');s.poly([pt(0,-51),pt(4.4,-46),pt(1.2,-46)],'#2a2420');
  rect(s,-3,-44,6,4,'#f3ead2',.6);s.line(-1.6,-42,1.6,-42,'#3b3430',.8);
  s.line(3.6,-32,6,-33,'#3b3430',1.2);
  c.beginPath();c.ellipse(10,-27,6,6.4,0,0,Math.PI*2);stroke(c,CU,2.6);c.beginPath();c.ellipse(10,-27,3.2,3.4,0,0,Math.PI*2);stroke(c,CUL,1.3);
  s.line(5.2,-31,4,-33.4,CUD,1.4);
  s.poly([pt(14.6,-24.6),pt(20.6,-19.4),pt(17.8,-16.2),pt(12.4,-22)],CU);s.ellipse(19.4,-17.8,2.4,3.4,CUD);s.ellipse(19.6,-17.6,1.3,2.2,'#5a3a26');
  const w=T(s,1.8)*1.2;s.line(6,-33,7+w*.4,-24,FR,.8);s.ellipse(7+w,-22.4,1.2,2,FR);
  s.line(-3.6,-31,-6,-31,'#3b3430',1.2);s.line(-6,-31,-9,-27,LED,1);s.line(-6,-31,-12,-25,LED,1);
  rect(s,-14,-26,9,10,LE,2);s.poly([pt(-14,-26),pt(-5,-26),pt(-5.4,-21.5),pt(-9.5,-20),pt(-13.6,-21.5)],LED);s.ellipse(-9.5,-21,1,1,FG);
  s.line(-13,-17.4,-6,-17.4,'#c9a06a',.5);
 }),
 curio_road_3:curio((s,c,t)=>{ // Флюгер-ветрогон: a post with a spinning copper cup anemometer and a striped leather windsock
  s.shadow(0,0,10,4);
  for(const [dx,dy] of [[-4,1],[3,2],[0,-1.6]])s.ellipse(dx,dy,2.6,1.6,'#a8a08c');
  s.line(0,0,0,-52,RW,3.4);s.line(-1,-2,-1,-50,'#a68a63',1);
  for(const y of [-10,-30])rect(s,-2.2,y-1.4,4.4,2.8,CU,.8);
  s.line(0,-40,4,-40,CUD,1.4);c.beginPath();c.ellipse(4.6,-40,1.2,3.4,0,0,Math.PI*2);stroke(c,CUD,1.2);
  const N=5;for(let k=0;k<N;k++){const x0=4.6+k*3.6,x1=x0+3.6,w0=Math.sin(t*3-k*.9)*1.2*(k/N),w1=Math.sin(t*3-(k+1)*.9)*1.2*((k+1)/N),h0=3.4-k*.45,h1=3.4-(k+1)*.45;
   s.poly([pt(x0,-40-h0+w0+k*.7),pt(x1,-40-h1+w1+(k+1)*.7),pt(x1,-40+h1+w1+(k+1)*.7),pt(x0,-40+h0+w0+k*.7)],k%2?'#efe0c0':LE)}
  const hub=-55,arms=[];for(let k=0;k<3;k++){const r=t*3+k*2*Math.PI/3;arms.push({r,x:Math.cos(r)*9,y:hub+Math.sin(r)*3.4})}
  arms.sort((A,B)=>A.y-B.y);s.line(0,-52,0,hub,CUD,1.6);
  for(const A of arms){s.line(0,hub,A.x,A.y,CUD,1);const front=Math.sin(A.r)>0,o=-Math.sin(A.r)>0?1:-1;s.ellipse(A.x,A.y,2.8,2.2,front?CUL:CU);s.ellipse(A.x+o*.9,A.y,1.5,1.4,CUD)}
  s.ellipse(0,hub,1.6,1.2,CU);s.ellipse(0,hub-2,1,1,CUL);
 }),
 // Stars — night-blue enamel, gold and glass.
 curio_stars_0:curio((s,c,t)=>{ // Звёздный глобус: a night-blue celestial globe with turning gold stars, a horizon ring and meridian
  s.shadow(0,0,13,5);
  for(const [dx,dy] of [[-9,0],[9,-1],[1,4]]){c.beginPath();c.moveTo(0,-13);c.quadraticCurveTo(dx*.9,dy-7,dx,dy);stroke(c,NV,2.4);s.ellipse(dx,dy,1.4,1,SG)}
  drum(s,0,-12,2.6,1.2,4,NB,SG);
  const cy=-29,R=11;
  c.beginPath();c.ellipse(0,cy,15,4.2,0,Math.PI,0,false);stroke(c,SG,1.6);
  c.save();c.beginPath();c.ellipse(0,cy,R,R,0,0,Math.PI*2);c.fillStyle=NV;c.fill();c.clip();
  s.ellipse(4,cy+1,10,12,'#2a345a');
  const pts=[];for(let i=0;i<16;i++){const lon=i*2.4+t*.25,lat=(((i*37)%11)/11*2-1)*1.1,x=Math.sin(lon)*Math.cos(lat)*R,y=cy-Math.sin(lat)*R*.95,z=Math.cos(lon)*Math.cos(lat);if(z>0)pts.push({x,y,z,i})}
  for(let k=1;k<pts.length;k++)if(pts[k].i===pts[k-1].i+1&&pts[k].i%3)s.line(pts[k-1].x,pts[k-1].y,pts[k].x,pts[k].y,'#efd27a66',.6);
  for(const q of pts){if(q.i%4===0)star5(s,q.x,q.y,1.4+q.z,SG);else s.ellipse(q.x,q.y,.5+q.z*.6,.5+q.z*.6,'#fff1b8')}
  c.restore();
  s.ellipse(-4,cy-4.5,3.4,2.2,'#ffffff30');
  c.beginPath();c.ellipse(0,cy,4.2,R+2.4,.42,0,Math.PI*2);stroke(c,SG,1.3);
  c.beginPath();c.ellipse(0,cy,15,4.2,0,0,Math.PI,false);stroke(c,SG,1.6);
  s.line(-15,cy,-13,-12,SG,1);s.line(15,cy,13,-12,SG,1);
  s.ellipse(-4.6,cy-11.2,1.3,1.3,SG);
 }),
 curio_stars_1:curio((s,c,t,p)=>{ // Лунная лампа: a sleepy crescent moon glowing on a silver stem, a little star dangling from its tip
  const lit=(s.lighting?.darkness||0)>.15,g=.5+.5*T(s,1.2);
  s.shadow(0,0,9,4);s.ellipse(0,-1,7.5,3.2,NV);s.ellipse(0,-2.6,6,2.4,NB);
  c.beginPath();c.moveTo(0,-2);c.lineTo(0,-24);c.quadraticCurveTo(0,-32,-6,-33);stroke(c,SV,1.8);
  s.ellipse(0,-42,13+g,13+g,lit?'#fff3c040':'#f3e2a226');
  c.save();c.translate(0,-42);c.rotate(-.35);
  crescent(c,0,0,11,6,9.2);c.fillStyle=lit?'#fff3c4':'#f3e2a2';c.fill();stroke(c,'#c9a54a',1);
  crescent(c,0,0,11,6,9.2);c.save();c.clip();s.ellipse(-8,3,5,9,'#e2c87a');c.restore();
  c.beginPath();c.moveTo(-8.5,-1.4);c.quadraticCurveTo(-7,0,-5.6,-1.2);stroke(c,'#8a7440',.8);s.ellipse(-7.4,2.6,1.2,.8,'#e8a49a');
  c.restore();
  const tip={x:5.6,y:-51.6},sw=T(s,1.6)*1.6;s.line(tip.x,tip.y,tip.x+1+sw,tip.y+10,SV,.6);star5(s,tip.x+1+sw,tip.y+12.4,2.8,SG);
  if(lit)s.lanternLights?.push({x:p.x,y:p.y+1});
 }),
 curio_stars_2:curio((s,c,t)=>{ // Хрустальный шар на подставке: a glass ball with drifting violet mist on a blue claw stand
  s.shadow(0,0,11,4.5);
  drum(s,0,-1,8,3.4,4,NV,NB);drum(s,0,-5,3.4,1.5,9,NB,null);s.line(-1.4,-6,-1.4,-13,'#6f7fb4',.8);
  s.ellipse(0,-14,6.4,2.6,NV);s.ellipse(0,-14,5,2,'#232c4c');
  const cy=-24,R=10;
  c.save();c.beginPath();c.ellipse(0,cy,R,R,0,0,Math.PI*2);c.fillStyle='#cfe3ee';c.fill();c.clip();
  s.ellipse(3,cy+3,9,8,'#b9cfe6');
  for(let k=0;k<3;k++){const a=t*.6+k*2.1;s.ellipse(Math.cos(a)*3.6,cy+1+Math.sin(a)*2.6,4.6,2.6,['#a98bc888','#8fa8e088','#c9a3e677'][k])}
  for(let k=0;k<4;k++){const tw=.5+.5*Math.sin(t*2.4+k*1.7);s.ellipse(Math.cos(k*1.9)*5,cy-2+Math.sin(k*2.3)*4,.4+tw*.7,.4+tw*.7,'#ffffff')}
  c.restore();
  c.beginPath();c.ellipse(0,cy,R,R,0,0,Math.PI*2);stroke(c,'#9fc0d4',1);
  s.ellipse(-3.6,cy-4.4,3,2,'#ffffffcc');s.ellipse(3.6,cy+4.6,1.4,.8,'#ffffff80');
  for(const d of [-1,0,1]){c.beginPath();c.moveTo(d*5,-14.6);c.quadraticCurveTo(d*7.6,-17,d*6.4,-19.4);stroke(c,SG,1.4)}
 }),
 curio_stars_3:curio((s,c,t)=>{ // Кукушкин телескоп: a big starry telescope on a blue pillar; a cuckoo sits on it and peers at the sky
  s.shadow(0,0,14,5.5);
  ibox(s,.12,.12,0,4,NB,NV,'#2a345a');drum(s,0,-4,3.2,1.4,20,NV,NB);
  s.line(-3,-24,-3,-30,SG,1.6);s.line(3,-24,3,-30,SG,1.6);
  const ang=-2.42+T(s,.3)*.06,cs=Math.cos(ang),sn=Math.sin(ang),px0=0,py0=-31,R=(x,y)=>pt(px0+cs*x-sn*y,py0+sn*x+cs*y);
  c.save();c.translate(px0,py0);c.rotate(ang);
  rect(s,-17,-1.7,6,3.4,SV,1);
  rect(s,-12,-4.4,27,8.8,NV,2.4);rect(s,-12,-4.4,27,2.6,NB,1.6);
  rect(s,15,-5.2,7,10.4,NB,2);s.ellipse(22,0,1.6,4.8,'#9fb4e6');s.ellipse(22,-1.6,.6,1.6,'#ffffffaa');
  for(const x of [-6,6])rect(s,x,-4.6,1.8,9.2,SG,.6);
  rect(s,-4,-7.6,10,2.4,NB,1);s.line(-4,-6.4,-6,-6.4,SV,1.4);
  c.restore();
  for(const [x,y,r] of [[-1,2,1.8],[10,1.2,1.4],[2.6,-1.2,1]]){const q=R(x,y);star5(s,q.x,q.y,r,SG)}
  const A=R(9,-4.6),B=R(9,4.6),top=A.y<B.y?A:B;
  bird(s,top.x+1,top.y-2.4,'#7d7466','#d9cfb8','#5f584d',((t*.35)%1)<.12);
  for(let k=0;k<2;k++){const q=R(30+k*6,k?-5:4),tw=Math.max(0,Math.sin(t*1.8+k*2));if(tw>.2)star5(s,q.x,q.y,1.2+tw*1.4,'#fff1b8')}
 }),
 // Tea — porcelain with cobalt and gold.
 curio_tea_0:curio((s,c,t)=>{ // Чайный столик на колёсиках: a two-shelf wooden tea trolley with a cobalt teapot, cups and a sugar bowl
  s.shadow(0,0,18,7);
  const a=.24,b=.15,C=(i,j,z)=>pt((i*a-j*b)*36,(i*a+j*b)*18-z);
  const leg=(i,j)=>{const q0=C(i,j,3),q1=C(i,j,24);s.line(q0.x,q0.y,q1.x,q1.y,'#8a6544',1.8)},wheel=(i,j)=>{const q=C(i,j,2.6);s.ellipse(q.x,q.y,2.6,2.6,'#4a3a2e');s.ellipse(q.x,q.y,1,1,TG)};
  wheel(-1,-1);leg(-1,-1);wheel(1,-1);wheel(-1,1);
  ibox(s,a,b,8,10,'#d9bf94','#b8966a','#a3845c');
  s.ellipse(C(-.4,.2,10).x,C(-.4,.2,10).y-2,4.4,2,POD);s.ellipse(C(-.4,.2,10).x,C(-.4,.2,10).y-3.4,4.4,2,PO);
  let q=C(.45,0,10);drum(s,q.x,q.y,3,1.4,4,PO,POD);s.ellipse(q.x,q.y-4,1.6,.8,'#f3e6c8');s.line(q.x-2.6,q.y-2,q.x+2.6,q.y-2,CO,.8);
  ibox(s,a,b,22,24,'#dcc39a','#b8966a','#a3845c');
  leg(1,-1);leg(-1,1);wheel(1,1);leg(1,1);
  const h0=C(-1,-1,24),h1=C(-1,1,24),h2=C(-1.32,1,29),h3=C(-1.32,-1,29);s.line(h0.x,h0.y,h3.x,h3.y,'#8a6544',1.4);s.line(h1.x,h1.y,h2.x,h2.y,'#8a6544',1.4);s.line(h2.x,h2.y,h3.x,h3.y,'#8a6544',2);
  q=C(.15,-.1,24);
  s.line(q.x+4,q.y-5,q.x+8.6,q.y-9,PO,2);s.ellipse(q.x+9,q.y-9.4,1,.7,PO);
  c.beginPath();c.ellipse(q.x-5.6,q.y-6,2.4,3,0,Math.PI*.5,Math.PI*1.5,false);stroke(c,PO,1.6);
  s.ellipse(q.x,q.y-5,5.6,4.6,PO);s.ellipse(q.x+2.2,q.y-4,3,3.6,'#e6dfcf');s.ellipse(q.x,q.y-5,2,2,CO);for(let k=0;k<5;k++){const a2=k*1.256;s.ellipse(q.x+Math.cos(a2)*3,q.y-5+Math.sin(a2)*2.4,1,1,COL)}
  s.ellipse(q.x,q.y-9.4,3.4,1.4,TG);s.ellipse(q.x,q.y-10.2,1,1,TG);
  steam(s,q.x+9,q.y-10,.8);
  for(const [u,v] of [[.75,.55],[-.6,.6]]){const r=C(u,v,24);s.ellipse(r.x,r.y-.6,3.4,1.4,POD);drum(s,r.x,r.y-1,2.2,1,3,PO,'#b98a5e');s.line(r.x-2.2,r.y-3.4,r.x+2.2,r.y-3.4,CO,.7)}
 }),
 curio_tea_1:curio((s,c,t)=>{ // Самовар-великан: a towering porcelain samovar painted with a cobalt rose, a teapot warming on top
  s.shadow(0,0,18,7);
  ibox(s,.15,.15,0,5,PO,POD,'#c9c0ad');for(const [i,j] of [[-1,1],[1,1],[1,-1]]){const q=pt((i*.15-j*.15)*36,(i*.15+j*.15)*18);s.ellipse(q.x,q.y-.6,1.8,1.2,TG)}
  drum(s,0,-5,6.4,2.6,5,POD,PO);
  urn(s,c,1.42,-10,PO,'rgba(120,110,90,.16)',null);
  c.beginPath();c.ellipse(0,-14,13,4,0,0,Math.PI);stroke(c,CO,1.6);c.beginPath();c.ellipse(0,-41,11,3.2,0,0,Math.PI);stroke(c,TG,1.4);
  const fy=-27;for(let k=0;k<6;k++){const a=k*Math.PI/3;s.ellipse(Math.cos(a)*3.6,fy+Math.sin(a)*3.6,2.8,2.8,k%2?CO:'#5679b8')}
  s.ellipse(0,fy,2.2,2.2,'#2f4f8f');s.ellipse(0,fy,1,1,TG);
  for(const d of [-1,1]){s.ellipse(d*9,fy+3,2.6,1.2,'#5f8fc0');s.ellipse(d*7.6,fy-4,1.6,.9,COL);s.ellipse(d*12,fy-6,1.1,1.1,CO)}
  s.line(-11.5,-17,-13,-36,'#ffffff',1.8);
  for(const d of [-1,1]){s.line(d*16.5,-38,d*20.5,-39,CO,1.8);s.ellipse(d*21,-37,1.8,3.4,CO)}
  s.line(1,-15,9,-12.4,TG,2.6);s.ellipse(9.6,-12,1.4,1.4,TG);s.line(4,-17,4,-20.5,TG,1.4);s.ellipse(4,-21,2,1,TG);
  drum(s,0,-47,9,3.4,4,TG,'#e8c86a');drum(s,0,-51,4,1.8,3,PO,'#5a4a3a');
  s.ellipse(0,-58,6.4,5,PO);s.ellipse(2.4,-57,3.6,3.8,'#e6dfcf');s.ellipse(0,-58,1.8,1.8,CO);s.ellipse(-3,-56.6,1,1,COL);s.ellipse(3,-56.6,1,1,COL);
  s.line(5.4,-58,9.4,-62,PO,2);c.beginPath();c.ellipse(-6.2,-58.6,2.2,2.8,0,Math.PI*.5,Math.PI*1.5,false);stroke(c,PO,1.6);
  s.ellipse(0,-62.6,3.4,1.4,TG);s.ellipse(0,-63.6,1,1,TG);
  steam(s,9.6,-63,.9);steam(s,-5,-52,.6,.5);
 }),
 curio_tea_2:curio((s,c,t)=>{ // Чашка-аквариум: a giant porcelain teacup on a saucer, full of water, a goldfish circling and now and then jumping
  s.shadow(0,0,18,7);
  s.ellipse(0,-1.6,17,7,POD);s.ellipse(0,-2.8,16,6.4,PO);c.beginPath();c.ellipse(0,-2.8,14.6,5.6,0,0,Math.PI*2);stroke(c,CO,.9);s.ellipse(0,-3,9,3.6,POD);
  c.beginPath();c.ellipse(16,-17,5.4,6,0,-Math.PI*.5,Math.PI*.5,false);stroke(c,PO,3.2);c.beginPath();c.ellipse(16,-17,5.4,6,0,-Math.PI*.5,Math.PI*.5,false);stroke(c,POD,1);
  c.beginPath();c.moveTo(-14,-26);c.bezierCurveTo(-14.4,-13,-11,-6,-8,-5);c.ellipse(0,-5,8,3,0,Math.PI,0,true);c.bezierCurveTo(11,-6,14.4,-13,14,-26);c.closePath();c.fillStyle=PO;c.fill();
  c.save();c.clip();c.fillStyle='rgba(120,110,90,.16)';c.fillRect(6,-30,12,30);c.restore();
  c.beginPath();c.ellipse(0,-23,13.6,3.6,0,0,Math.PI);stroke(c,CO,1.2);
  for(const x of [-8,0,8]){const y=-14+Math.abs(x)*.12;s.ellipse(x,y,2.2,2.2,CO);s.ellipse(x,y,.8,.8,TG);s.ellipse(x-2.6,y+1.4,1.3,.7,COL);s.ellipse(x+2.6,y+1.4,1.3,.7,COL)}
  s.ellipse(0,-26,14,5.6,TG);s.ellipse(0,-26,13,5,'#7fb6c4');s.ellipse(-2,-25.4,10,3.6,'#93c6d0');
  const f=(t*.15)%1,jump=s.motion!==false&&f<.1,a=t*.8;
  if(!jump){const fx=Math.cos(a)*7,fy=-25.4+Math.sin(a)*2.4,dir=-Math.sin(a)>=0?1:-1;c.save();c.globalAlpha=.85;s.ellipse(fx,fy,3,1.4,'#e8823a');s.poly([pt(fx-dir*2.6,fy),pt(fx-dir*5,fy-1.6),pt(fx-dir*5,fy+1.6)],'#f0a060');c.restore()}
  for(const [dx,dy] of [[4,-31],[-6,-27.6]])s.ellipse(dx,dy+(-(t*6)%5),1,1,'#e8f6f8');
  s.line(-8,-26,-10,-35,'#6f9a64',1.4);s.ellipse(-10.4,-36,1.4,3,'#7fae6e');s.line(-6,-26,-5,-32,'#6f9a64',1.2);
  if(jump){const k=f/.1,x=-6+k*12,y=-26-Math.sin(k*Math.PI)*12;c.save();c.translate(x,y);c.rotate(-1.2+k*2.4);s.ellipse(0,0,3,1.5,'#e8823a');s.poly([pt(-2.6,0),pt(-5,-1.6),pt(-5,1.6)],'#f0a060');c.restore();
   s.ellipse(-6,-25.6,3*(1-k),1*(1-k),'#ffffffaa');s.ellipse(6,-25.6,3*k,1*k,'#ffffffaa')}
 }),
 curio_tea_3:curio((s,c,t)=>{ // Паровой чайник-паровоз: a porcelain kettle on a cobalt wheeled chassis and a scrap of rail, puffing steam
  s.shadow(0,0,21,7);
  const a=.34,b=.13,C=(i,j,z)=>pt((i*a-j*b)*36,(i*a+j*b)*18-z);
  for(const j of [-1.3,1.3]){const A=C(-1.35,j,0),B=C(1.35,j,0);s.line(A.x,A.y,B.x,B.y,'#8f8670',1.3)}
  for(let k=0;k<6;k++){const u=-1.2+k*.48,A=C(u,-1.7,0),B=C(u,1.7,0);s.line(A.x,A.y,B.x,B.y,'#a68a63',1.8)}
  for(const j of [-1.3,1.3]){const A=C(-1.35,j,.6),B=C(1.35,j,.6);s.line(A.x,A.y,B.x,B.y,'#b9b2a0',1)}
  const bob=Math.max(0,T(s,4))*.6;
  ibox(s,a,b,5,9,'#5679b8',CO,'#2f4f8f');
  for(const u of [-.62,0,.62]){const q=C(u,1,4.6);s.ellipse(q.x,q.y,3.8,4.2,'#2f4f8f');s.ellipse(q.x,q.y,3,3.4,TG);s.ellipse(q.x,q.y,1,1,CO);const r=t*.6+u;s.line(q.x-Math.cos(r)*2.6,q.y-Math.sin(r)*2.8,q.x+Math.cos(r)*2.6,q.y+Math.sin(r)*2.8,'#8a6a2a',.7)}
  const w=C(-.62,1,4.6),w2=C(.62,1,4.6);s.line(w.x,w.y,w2.x,w2.y,'#c9a24e',1.2);
  const fr=C(1,0,7);s.poly([pt(fr.x+2,fr.y-4),pt(fr.x+8,fr.y+4),pt(fr.x+2,fr.y+5)],TG);
  const m=C(-.05,0,17+bob);
  c.beginPath();c.ellipse(m.x-12,m.y-1,3.4,5,0,Math.PI*.4,Math.PI*1.6,false);stroke(c,PO,3);
  s.ellipse(m.x,m.y,13,9,PO);s.ellipse(m.x+3.6,m.y+1.6,8.4,6.6,'#e6dfcf');
  c.beginPath();c.ellipse(m.x,m.y+2,12.6,4,0,0,Math.PI);stroke(c,TG,1.2);
  for(const [dx,dy] of [[-5,-1],[1,-3],[5,1]]){s.ellipse(m.x+dx,m.y+dy,1.8,1.8,CO);s.ellipse(m.x+dx+1.8,m.y+dy+1,1,.6,COL)}
  s.ellipse(m.x-4,m.y-8.6,4,1.8,PO);s.ellipse(m.x-4,m.y-9.4,1.2,1.2,TG);
  const ch=C(.72,0,22+bob);drum(s,ch.x,ch.y+4,2.6,1.2,7,PO,null);drum(s,ch.x,ch.y-3,3.8,1.6,2.4,CO,'#2f4f8f');
  s.ellipse(m.x-5,m.y-3.6,3,1.6,'#ffffffb0');
  steam(s,ch.x,ch.y-7,1.2);steam(s,ch.x-2,ch.y-9,1,.33);
 }),
};
/* Festival decor drawn on the farm (qw_farm/festivals.py lots placed on a 1×1 cell). Colours of the pie layers are the
   corzh palette of «Пирог до небес» (pie-game.js korzhMarkup: sponge, glaze, jam, berry, edge / edgeContrast). */
const KZ={sponge:'#d9a35f',sponge2:'#e3b16e',glaze:'#f3d79f',jam:'#d98a6a',berry:'#c0544a',edge:'#8f5a2c',edgeContrast:'#3f230b'};
const FEST_ART={
 fest_posid_tower:curio((s,c,t)=>{ // Пирог-башня: five corzhes on a wooden stand, little scaffolding on the left, a red pennant on top
  const PI=Math.PI,hc=!!s.contrast,E=hc?KZ.edgeContrast:KZ.edge,ew=hc?1.5:.9,WO=hc?'#3b2a18':'#6b4a2c',WL='#c49a64',WM='#a37a4c';
  s.shadow(0,0,21,8);s.shadow(-25,2,6,2.4);
  // scaffolding: two frames of poles (back pair first, half hidden by the pie), planks and a brace, a deck with a cream bucket
  const F=(x,y,z)=>pt(x,y-z),back=[pt(-23,-3),pt(-15,1)],front=[pt(-29,1),pt(-21,5)];
  for(const q of back)s.line(q.x,q.y,q.x,q.y-31,WM,1.6);
  for(const z of [11,21,31]){const a=F(front[0].x,front[0].y,z),b=F(back[0].x,back[0].y,z);s.line(a.x,a.y,b.x,b.y,WM,1.2)}
  for(const q of front)s.line(q.x,q.y,q.x,q.y-33,WO,1.9);
  for(const q of front)s.line(q.x-.5,q.y-1,q.x-.5,q.y-32,WL,.6);
  {const a=F(front[0].x,front[0].y,1),b=F(front[1].x,front[1].y,20);s.line(a.x,a.y,b.x,b.y,WM,1.1)}
  for(const z of [11,21]){const a=F(front[0].x,front[0].y,z),b=F(front[1].x,front[1].y,z);s.line(a.x,a.y,b.x,b.y,WO,1.7)}
  {const z=31,q=[F(-29,1,z),F(-21,5,z),F(-15,1,z),F(-23,-3,z)];s.poly(q,WL,WO,.9);s.line(q[0].x,q[0].y,q[1].x,q[1].y,WO,1.3)}
  drum(s,-22,-30.5,2.4,1.1,3.6,'#c9d2d6','#f6f1e6');s.line(-24.4,-34,-22,-37,'#8a8f92',.6);s.line(-19.6,-34,-22,-37,'#8a8f92',.6);
  // the wooden stand: a round board on three stubby legs
  for(const [x,y] of [[-12,2],[12,2],[0,6]])s.line(x,y,x,y-5,WO,2.2);
  drum(s,0,-4,18,8,3.2,WM,WL);
  c.beginPath();c.moveTo(-18,-7.2);c.lineTo(-18,-4);c.ellipse(0,-4,18,8,0,PI,0,true);c.lineTo(18,-7.2);c.moveTo(18,-7.2);c.ellipse(0,-7.2,18,8,0,0,PI*2);c.strokeStyle=WO;c.lineWidth=ew;c.stroke();
  s.line(-11,-7.6,8,-9.8,'#b48a5a',.7);s.line(-6,-4.4,13,-6.4,'#b48a5a',.7);
  // five corzhes, narrowing upwards: sponge, jam band, glaze with drips, berries on each ledge
  const H=6.2,y0=-7.4,N=5,R=i=>15.2-i*2.15;
  for(let i=0;i<N;i++){
   const rx=R(i),ry=rx*.46,y=y0-i*H,top=y-H;
   c.beginPath();c.moveTo(-rx,top);c.lineTo(-rx,y);c.ellipse(0,y,rx,ry,0,PI,0,true);c.lineTo(rx,top);c.ellipse(0,top,rx,ry,0,0,PI,true);c.closePath();
   c.fillStyle=i%2?KZ.sponge2:KZ.sponge;c.fill();
   c.save();c.clip();c.fillStyle='rgba(90,50,20,.16)';c.fillRect(rx*.35,top-ry,rx,H+ry*2+1);c.restore();
   c.beginPath();c.ellipse(0,y-H*.4,rx,ry,0,.08,PI-.08);c.strokeStyle=KZ.jam;c.lineWidth=1.25;c.stroke();
   c.beginPath();c.moveTo(-rx,top);c.lineTo(-rx,y);c.ellipse(0,y,rx,ry,0,PI,0,true);c.lineTo(rx,top);c.strokeStyle=E;c.lineWidth=ew;c.stroke();
   s.ellipse(0,top,rx,ry,KZ.glaze);
   c.beginPath();c.ellipse(0,top,rx,ry,0,0,PI*2);c.strokeStyle=E;c.lineWidth=ew*.8;c.stroke();
   for(let k=0;k<5;k++){const a=.32+k*(PI-.64)/4,dx=Math.cos(a)*rx*.97,dy=top+Math.sin(a)*ry,dl=1.3+((k*5+i*3)%3)*.6;s.ellipse(dx,dy+dl*.55,1.25,dl,KZ.glaze)}
   if(i<N-1){const r=(rx+R(i+1))/2+.2;for(const a of [.75,2.35]){s.ellipse(Math.cos(a)*r,top+Math.sin(a)*r*.46-.6,1.6,1.5,KZ.berry);s.ellipse(Math.cos(a)*r-.5,top+Math.sin(a)*r*.46-1.1,.5,.45,'#f3c2b8')}}
  }
  // the crown: a cherry and the red pennant on a thin pole
  const top=y0-N*H,w=T(s,2.6)*1.6;
  s.line(.4,top,.4,top-17,WO,1.2);s.ellipse(.4,top-17.6,1.3,1.3,'#e2b04a');
  s.poly([pt(1,top-16.6),pt(6,top-15.4+w*.5),pt(11.5,top-13.8+w),pt(6,top-12.2+w*.5),pt(1,top-11.4)],'#c8463c',hc?'#5a1410':'#8e2a24',hc?1.1:.7);
  s.line(1.6,top-15.2,5.6,top-14.4+w*.5,'#e57a6c',.6);
  s.ellipse(-2.6,top-.6,2.1,2,KZ.berry);s.ellipse(-3.2,top-1.3,.6,.55,'#f3c2b8');s.line(-2.4,top-2.5,-1,top-5,'#6f9a64',.7);
 }),
};
export function specialDecor(s,o,p){
 const c=s.c;
 if(lateDecor(s,o,p))return true;
 const art=DECOR_ART[o.type]||CURIO_ART[o.type]||FEST_ART[o.type];if(art){art(s,p);return true;}
 if(o.type==='basket'){s.shadow(p.x,p.y,14,5);rect(s,p.x-13,p.y-10,26,14,'#c2a477',4);s.line(p.x-10,p.y-10,p.x-6,p.y-21,'#ab8a62',2);s.line(p.x-6,p.y-21,p.x+7,p.y-21,'#ab8a62',2);s.line(p.x+7,p.y-21,p.x+10,p.y-10,'#ab8a62',2);s.ellipse(p.x-6,p.y-10,5,3,'#b58360');s.ellipse(p.x+5,p.y-11,4,4,'#a17793');return true;}
 if(o.type==='alchemist_table'){
  s.shadow(p.x,p.y,20,6);for(let dx of [-12,12])s.line(p.x+dx,p.y,p.x+dx,p.y-18,'#a28a65',3);
  rect(s,p.x-20,p.y-23,40,8,'#c8b17e');s.ellipse(p.x-8,p.y-34,7,10,'#99b5a1');rect(s,p.x-11,p.y-48,6,10,'#adc9b8');s.ellipse(p.x-8,p.y-33,5,6,'#aad9b4');rect(s,p.x+4,p.y-30,12,6,'#b59285');return true;
 }
 if(o.type==='elements_stone'){
  s.shadow(p.x,p.y,17,6);s.poly([{x:p.x-14,y:p.y},{x:p.x+14,y:p.y},{x:p.x+8,y:p.y-38},{x:p.x-7,y:p.y-44}],'#b6b8a3');['#a3c2bd','#b0bd81','#e0b881','#c4d0c9'].forEach((color,i)=>s.ellipse(p.x+(i%2)*8-5,p.y-29+Math.floor(i/2)*11,3,4,color));return true;
 }
 if(o.type==='night_lantern'){
  s.decor({...o,type:'lantern'},p);s.ellipse(p.x+12,p.y-40,5,6,'#bcc5c1');s.ellipse(p.x+14,p.y-42,4,5,'#eaf0dd');return true;
 }
 if(o.type==='detective_scarecrow'){
  s.decor({...o,type:'scarecrow'},p);rect(s,p.x-12,p.y-42,24,4,'#65766e');rect(s,p.x-7,p.y-52,14,12,'#76877b');s.ellipse(p.x+12,p.y-22,5,5,'#cfdbc7');s.line(p.x+15,p.y-18,p.x+20,p.y-12,'#797f67',2);return true;
 }
 if(o.type==='duckpond'){
  s.pond(p.x,p.y); // Compact local pond, overridden scale below by caller.
  if(o.animal)smallAnimal(s,p.x,p.y,'duck_swim');return true;
 }
 return false;
}

function lateDecor(s,o,p){
 const id=o.type;if(!['dc_well','dc_weathervane','dc_flower_arch','dc_swing','tr_bronze_ear','tr_gold_sickle','tr_silver_plough','tr_gold_sheaf'].includes(id))return false;
 const c=s.c;c.save();c.translate(p.x,p.y);s.shadow(0,2,24,8);
 if(id==='dc_well'){rect(s,-20,-20,40,23,'#b5b7a3',5);s.ellipse(0,-20,20,8,'#d6d2bb');s.ellipse(0,-21,14,5,'#708c8b');for(let dx of [-18,18])s.line(dx,0,dx,-51,'#a28b64',3);s.poly([{x:-26,y:-43},{x:0,y:-61},{x:26,y:-43},{x:0,y:-34}],'#9aa77d');s.line(-19,-35,19,-35,'#8c7658',3);s.line(2,-35,2,-17,'#c6ae7c',1.2);rect(s,0,-19,8,8,'#b49665',1)}
 else if(id==='dc_flower_arch'||id==='dc_swing'){for(let dx of [-21,21]){s.line(dx,0,dx,-55,'#b6a078',3);s.line(dx,0,dx+(dx<0?-8:8),3,'#b6a078',2)}s.line(-21,-55,21,-55,'#c8b78d',4);
  if(id==='dc_swing'){const sway=Math.sin(s.time*1.1)*3;for(let dx of [-12,12])s.line(dx,-52,dx+sway,-15,'#a29072',1.4);rect(s,-16+sway,-16,32,5,'#bfa36e',2)}
  else{for(let k=0;k<15;k++){const a=k*Math.PI/14,x=Math.cos(a)*23,y=-34-Math.sin(a)*25;s.ellipse(x,y,5,4,'#8fac78');s.ellipse(x+1,y-2,3,3,k%3?'#d8a8b1':'#f0d898')}for(let dx of [-21,21])for(let k=0;k<4;k++)s.ellipse(dx,-8-k*8,4,5,'#94af79')}
 }else if(id==='dc_weathervane'){s.line(0,0,0,-58,'#807d68',3);s.line(-17,-40,17,-40,'#9d9067',2);s.poly([{x:17,y:-40},{x:10,y:-44},{x:10,y:-36}],'#c4a45e');s.ellipse(0,-51,8,6,'#c6a566');s.ellipse(7,-58,4,4,'#c6a566');s.poly([{x:-6,y:-53},{x:-16,y:-61},{x:-13,y:-49}],'#bd9659');s.ellipse(8,-59,.8,.8,'#5e654e')}
 else{const silver=id==='tr_silver_plough',bronze=id==='tr_bronze_ear',col=silver?'#b6c5bf':bronze?'#bb9166':'#d8b360';rect(s,-17,-4,34,9,'#b1ae94',2);rect(s,-12,-10,24,8,'#d0c8aa',2);
  if(silver){s.line(-18,-20,20,-28,col,4);s.line(-9,-17,-4,-37,col,3);s.line(-4,-37,8,-43,col,2);s.poly([{x:-3,y:-22},{x:12,y:-14},{x:18,y:-28}],'#d5dfd4');s.ellipse(-15,-12,7,7,'#899d94');s.ellipse(-15,-12,4,4,'#d5dfd4')}
  else if(id==='tr_gold_sickle'){s.line(-6,-10,4,-30,'#a58a5d',5);c.beginPath();c.arc(-2,-37,15,-1.9,1.5);c.strokeStyle=col;c.lineWidth=5;c.stroke()}
  else{for(let j=bronze?0:-1;j<=(bronze?0:1);j++){s.line(j*3,-10,j*8,-51+Math.abs(j)*6,col,2);for(let k=0;k<5;k++){s.ellipse(j*8-3,-47+k*5+Math.abs(j)*6,4,2.4,col);s.ellipse(j*8+3,-49+k*5+Math.abs(j)*6,4,2.4,col)}}if(!bronze)rect(s,-9,-23,18,4,'#b28b53',1)}
 }c.restore();return true;
}

// Tap target of a parked or working machine (world pixels, the sprite is scaled by .88): the id of the machine under the point.
export function machineAt(s,wx,wy){
 const list=crewSprites(s).filter(m=>m.machine&&seen(s,{x:m.wx,y:m.wy}));
 for(let i=list.length-1;i>=0;i--){const m=list[i];if(wx>m.wx-26&&wx<m.wx+38&&wy>m.wy-46&&wy<m.wy+10)return m.machine;}
 return null;
}
