/* Original procedural sprites for r2. Rendering has no authority over rewards. */
import {isoInverse,compareDepth} from './scene_map.js';
const P=(x,y,z=0)=>({x:(x-y)*36,y:(x+y)*18-z});
function rect(s,x,y,w,h,color,r=3){const c=s.c;c.fillStyle=color;c.beginPath();c.roundRect(x,y,w,h,r);c.fill();}
export function vehicle(s,x,y,id,active=false){
 const c=s.c;c.save();c.translate(x,y);c.scale(.88,.88);s.shadow(0,0,28,9);
 const rolling=active?Math.sin(s.time*8):0;
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
 let col={rabbit_gardener:'#d5bb94',mole_gardener:'#a79786',raccoon:'#a8afa4',shepherd:'#bb9d72',hedgehog:'#ad9073',squirrel:'#c2966d',fox_picker:'#e0955a',hamster_reaper:'#e3c9a2',cat_keeper:'#c5bdb0',beaver_artisan:'#a37c58',badger_artisan:'#8f9388'}[id]||'#c4b79a';
 if(id==='beaver_artisan')s.ellipse(-10,-4,9,4,'#6f5a46');
 if(id==='fox_picker')s.ellipse(-9,-9,8,5,'#f0f0e2');
 if(id==='squirrel')s.ellipse(-9,-13,7,12,'#b5855d');
 if(id==='hedgehog')for(let a=0;a<8;a++){const t=a*Math.PI/7;s.line(Math.cos(t)*10,-6-Math.sin(t)*12,Math.cos(t)*14,-6-Math.sin(t)*16,'#957b62',2);}
 s.ellipse(0,-10,10,12,col);s.ellipse(0,-23,8,8,col);
 if(id==='rabbit_gardener')for(let dx of [-4,4])s.ellipse(dx,-36,3,10,col);
 else for(let dx of [-6,6])s.ellipse(dx,-28,3.5,5,col);
 if(id==='raccoon')rect(s,-8,-25,16,6,'#69756a',3);
 if(id==='shepherd'){s.ellipse(-6,-21,3,7,'#8d775c');s.ellipse(6,-21,3,7,'#8d775c');}
 for(let dx of [-3,3])s.ellipse(dx,-24,1,1,'#3d5849');
 s.ellipse(0,-20,2,1.5,'#7b715a');rect(s,-7,-13,14,13,'#7e9b7b',3);
 if(id==='hamster_reaper'){s.ellipse(-6,-21,2.6,2,'#efb9a4');s.ellipse(6,-21,2.6,2,'#efb9a4');}
 if(id==='cat_keeper')for(let d of [-1,1]){s.line(d*3,-20,d*10,-22,'#8f877b',.8);s.line(d*3,-19,d*10,-18,'#8f877b',.8);}
 if(id==='beaver_artisan')rect(s,-1.5,-19,3,3,'#fffcee',1);
 if(id==='badger_artisan'){s.line(-3,-30,-3,-17,'#4f554d',2);s.line(3,-30,3,-17,'#4f554d',2);}
 if(working){s.line(8,-11,17,-5,'#a1b19c',3);rect(s,13,-5,9,7,id==='rabbit_gardener'?'#8dbbb7':'#c6a875',2);}
 c.restore();
}
// A rectangle of the land seen from above: used for helper zones and for the bulk-action area preview.
function zoneBox(s,z,fill,stroke,dashed){
 const c=s.c;c.save();c.beginPath();
 [P(z.x,z.y,1),P(z.x+z.w,z.y,1),P(z.x+z.w,z.y+z.h,1),P(z.x,z.y+z.h,1)].forEach((q,i)=>i?c.lineTo(q.x,q.y):c.moveTo(q.x,q.y));
 c.closePath();c.fillStyle=fill;c.fill();c.lineWidth=2.2;c.strokeStyle=stroke;if(dashed)c.setLineDash([9,6]);c.stroke();c.restore();
}
const ZONE_COLORS=[['#7fb59a22','#4f8f77'],['#d8a35a22','#b9803a'],['#8aa6d822','#5f7fb8'],['#c88ab822','#a2628f'],['#a9bf6a22','#7f9a3f'],['#d98a7a22','#b86556']];
// Helpers wander inside their zone (the whole land when there is none). Position is a pure function of time,
// so the scene holds no state and a calm-mode (frozen time) figure simply stands still.
function walk(s,i,z){
 const t=s.time*.25+i*1.9,fx=.5+.42*Math.sin(t)*Math.cos(t*.37+i),fy=.5+.42*Math.sin(t*.71+i*2.1);
 return P(z.x+z.w*fx,z.y+z.h*fy);
}
// Off-screen figures are skipped: sprites reach ~80px sideways, ~90px up and ~30px down from their anchor.
const seen=(s,q)=>!s.view||(q.x+80>=s.view.x0&&q.x-80<=s.view.x1&&q.y+30>=s.view.y0&&q.y-90<=s.view.y1);
// After dusk the animals go home: they walk to their house door and disappear inside, and come out again after dawn.
// Hysteresis keeps them from popping in and out while the light fades.
function nightState(s){
 if(!s.lighting)return !!s.nightFlag;
 const d=s.lighting.darkness||0;
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
 const size=s.farm.size||8,whole={x:0,y:0,w:size,h:size};
 const add=(q,draw,machine)=>{const c=isoInverse(q.x,q.y);out.push({x:c.x,y:c.y,w:0,h:0,draw,machine,wx:q.x,wy:q.y});};
 Object.entries(s.farm.equipment||{}).forEach(([id,v],i)=>{
  const active=v.shift?.status==='working'&&v.shift.until>s.now()||v.active||(v.last_run_at&&s.now()-v.last_run_at<12);
  let q=active?P(2.5+Math.sin(s.time*.35+i)*1.3,6.7):P(.5+i*1.3,6.5);
  if(id==='robot'&&active&&v.shift?.status==='working')q=walk(s,i+7,v.zone||whole);
  if(seen(s,q))add(q,()=>vehicle(s,q.x,q.y,id,active),id);
 });
 Object.entries(s.farm.helpers||{}).forEach(([id,v],i)=>{
  const active=v.shift?.status==='working'&&v.shift.until>s.now()||v.active;
  const q=active?(v.shift?v.zone||whole:null):null;
  const pos=q?walk(s,i,q):active?P(3.4+(i%3)*1.4,3.1+Math.sin(s.time*.4+i)*.3):P(1+i%12,7.2+Math.floor(i/12));
  if(seen(s,pos))add(pos,()=>helper(s,pos.x,pos.y,id,active));
 });
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
const T=(s,k=1,ph=0)=>Math.sin(s.time*k+ph);
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
export function specialDecor(s,o,p){
 const c=s.c;
 if(lateDecor(s,o,p))return true;
 if(DECOR_ART[o.type]){DECOR_ART[o.type](s,p);return true;}
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
  if(o.animal)smallAnimal(s,p.x,p.y,'duck');return true;
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
 const list=teamSprites(s).filter(m=>m.machine);
 for(let i=list.length-1;i>=0;i--){const m=list[i];if(wx>m.wx-26&&wx<m.wx+38&&wy>m.wy-46&&wy<m.wy+10)return m.machine;}
 return null;
}
