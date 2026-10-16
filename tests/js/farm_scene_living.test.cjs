const {test}=require('node:test');
const assert=require('node:assert/strict');

function geeseScene(expansion,overrides={}){
 const scene={farm:{id:'f',size:12,objects:[{id:'gh',type:'goose_house',animal:'goose',x:6,y:6,w:2,h:2}],pranks:[],equipment:{},helpers:{}},
  motion:true,time:0,now:()=>0,view:null,placement:null,goose(){},c:{save(){},restore(){},translate(){},scale(){}},...overrides};
 expansion.resetWalkingGeese(scene);return scene;
}
function withClock(fn){
 const real=performance.now;let now=1000;performance.now=()=>now;
 try{return fn(ms=>{now+=ms})}finally{performance.now=real}
}

test('a goose chases a pointer in range, hisses, goes home and stays on its own yard',async()=>{
 const E=await import('../../qw_farm/static/scene_expansion.js');
 withClock(tick=>{
  const s=geeseScene(E),g=s.walkingGeese[0];
  assert.ok(g,'a goose house gives a walking goose');
  E.teamSprites(s);const home={...g.pos};assert.equal(g.mode,'idle');
  E.reactWalkingGeese(s,{x:home.x+60,y:home.y+20},null,false);
  const modes=new Set();
  for(let i=0;i<120;i++){tick(33);E.teamSprites(s);modes.add(g.mode);
   assert.ok(g.yard.has(`${Math.floor((g.pos.x/36+g.pos.y/18)/2)},${Math.floor((g.pos.y/18-g.pos.x/36)/2)}`),'the goose never leaves its yard');
   if(i===70)E.releaseWalkingGeese(s,0);}
  assert.ok(modes.has('chase')&&modes.has('hiss')&&modes.has('return'),[...modes].join());
  for(let i=0;i<200&&g.mode!=='idle';i++){tick(33);E.teamSprites(s)}
  assert.equal(g.mode,'idle');
 });
});

test('a far pointer, placement mode and reduced motion do not make the goose run',async()=>{
 const E=await import('../../qw_farm/static/scene_expansion.js');
 withClock(tick=>{
  const far=geeseScene(E),g=far.walkingGeese[0];E.teamSprites(far);
  E.reactWalkingGeese(far,{x:g.pos.x+400,y:g.pos.y},null);tick(50);E.teamSprites(far);assert.equal(g.mode,'idle');
  const placing=geeseScene(E,{placement:{}});E.reactWalkingGeese(placing,{x:0,y:0},null);assert.equal(placing.geesePointer,undefined);
  const calm=geeseScene(E,{motion:false}),cg=calm.walkingGeese[0];E.teamSprites(calm);const start={x:cg.pos.x,y:cg.pos.y};
  E.reactWalkingGeese(calm,{x:start.x+30,y:start.y+10},null);tick(50);E.teamSprites(calm);
  assert.equal(cg.mode,'hiss');assert.deepEqual({x:cg.pos.x,y:cg.pos.y},start);
 });
});

function layoutScene(FarmScene,id,size=12){
 const scene=Object.create(FarmScene.prototype);Object.assign(scene,{farm:{id,size,objects:[],level:10,name:'Ферма Тест'},grid:()=>Math.max(12,size),
  c:null,lighting:null});
 scene.buildLayout();return scene.layout;
}

test('every farm gets its own wood, yet the working land, lanes and arbor stay clear of trunks',async()=>{
 const {FarmScene}=await import('../../qw_farm/static/scene.js');
 const a=layoutScene(FarmScene,'farm-a'),a2=layoutScene(FarmScene,'farm-a'),b=layoutScene(FarmScene,'farm-b');
 const sig=l=>JSON.stringify([...l.before,...l.after].map(t=>[Math.round(t.x*100),Math.round(t.y*100)]));
 assert.equal(sig(a),sig(a2),'one farm always has the same trees');
 assert.notEqual(sig(a),sig(b),'different farms differ');
 assert.notEqual(a.key,b.key);
 for(const l of [a,b])for(const t of [...l.before,...l.after]){
  assert.ok(!(t.x>-.3&&t.y>-.3&&t.x<12.25&&t.y<12.25),'no tree inside the farm square');
  assert.ok(!(t.x>1.3&&t.x<3.7&&t.y<.5&&t.y>-4),'the top lane stays open');
  assert.ok(!(t.y>1.3&&t.y<3.7&&t.x<.5&&t.x>-4.5),'the left lane stays open');
  assert.ok(!(t.x>1.1&&t.x<3.9&&t.y>=11.5&&t.y<15.2),'the way to the lake stays open');
 }
});

test('the arbor and the irregular lake are tap targets; land beside them is not',async()=>{
 const {FarmScene}=await import('../../qw_farm/static/scene.js');
 const scene=Object.create(FarmScene.prototype);
 Object.assign(scene,{farm:{id:'f',size:12,objects:[],is_owner:false,home_projects:{entries:{tea_arbor:{stage:2}}}},sortedObjects:()=>({list:[]}),grid:()=>12});
 const ap=scene.arborPos(),at=(wx,wy)=>{scene.world=()=>({x:wx,y:wy});scene.cell=()=>({x:-9,y:-9});return scene.pick(0,0)};
 assert.deepEqual(at(ap.x,ap.y-30),{type:'arbor',id:'arbor'});
 scene.farm.home_projects.entries.tea_arbor.stage=0;assert.equal(at(ap.x,ap.y-30)?.type,undefined);
 const c=scene.pondCenter();
 assert.equal(at(c.x,c.y)?.type,'lake');
 assert.equal(at(c.x-scene.lakeSize().rx*1.05,c.y)?.type,undefined);
 // the shoreline is not an ellipse: some bearings reach much further than others
 const radii=scene.lakeShape().map(p=>p.r);assert.ok(Math.max(...radii)-Math.min(...radii)>.3);
});

test('livestock wanders, naps and bolts inside the yard in front of its house, and freezes in calm mode',async()=>{
 const E=await import('../../qw_farm/static/scene_expansion.js');
 const farm={id:'f',size:12,pranks:[],equipment:{},helpers:{},objects:[
  {id:'coop',type:'coop',animal:'chicken',x:2,y:2,w:2,h:2},{id:'pen',type:'pigsty',animal:'pig',x:6,y:2,w:2,h:2},
  {id:'bees',type:'apiary',animal:'bees',x:9,y:2,w:2,h:2},{id:'pond',type:'duckpond',animal:'duck',x:2,y:6,w:2,h:2}]};
 const make=(motion)=>{const s={farm,motion,time:0,now:()=>0,view:null,placement:null,goose(){},c:{save(){},restore(){},translate(){},scale(){},rotate(){},stroke(){},fillText(){},strokeText(){}}};E.resetWalkingGeese(s);E.resetLivestock(s);return s};
 withClock(tick=>{
  const s=make(true);
  assert.deepEqual(s.livestock.map(l=>l.kind).sort(),['chicken','chicken','pig'],'bees and the duck pond stay put');
  assert.ok(!E.livestockMoves(farm.objects[2])&&!E.livestockMoves(farm.objects[3])&&E.livestockMoves(farm.objects[0]));
  const modes=new Set();let moved=0;const start=s.livestock.map(l=>[l.x,l.y]);
  for(let i=0;i<900;i++){tick(33);E.teamSprites(s);for(const l of s.livestock){modes.add(l.mode);
   assert.ok(l.x>=l.yard.x0-1e-9&&l.x<=l.yard.x1+1e-9&&l.y>=l.yard.y0-1e-9&&l.y<=l.yard.y1+1e-9,'never leaves the yard');}}
  s.livestock.forEach((l,i)=>{if(Math.hypot(l.x-start[i][0],l.y-start[i][1])>.05)moved++});
  assert.ok(moved>0&&modes.has('walk'),[...modes].join());
  // a pointer on top of a hen startles it
  const hen=s.livestock[0],q={x:(hen.x-hen.y)*36,y:(hen.x+hen.y)*18};
  hen.cool=0;hen.mode='stand';hen.until=1e9;E.reactWalkingGeese(s,q,null);tick(33);E.teamSprites(s);
  assert.ok(['flee','hop'].includes(hen.mode),hen.mode);
  const calm=make(false),before=JSON.stringify(calm.livestock.map(l=>[l.x,l.y,l.mode]));
  for(let i=0;i<60;i++){tick(33);E.teamSprites(calm)}
  assert.equal(JSON.stringify(calm.livestock.map(l=>[l.x,l.y,l.mode])),before);
 });
});

test('after dusk animals walk to their house door and vanish; after dawn they come back out',async()=>{
 const E=await import('../../qw_farm/static/scene_expansion.js');
 const farm={id:'f',size:12,pranks:[],equipment:{},helpers:{},objects:[
  {id:'coop',type:'coop',animal:'chicken',x:2,y:2,w:2,h:2},{id:'gh',type:'goose_house',animal:'goose',x:6,y:6,w:2,h:2}]};
 const make=(motion)=>{const s={farm,motion,time:0,now:()=>0,view:null,placement:null,lighting:{darkness:0},goose(){},c:{save(){},restore(){},translate(){},scale(){},rotate(){},stroke(){},fillText(){},strokeText(){}}};E.resetWalkingGeese(s);E.resetLivestock(s);return s};
 const visible=s=>E.teamSprites(s).length;
 withClock(tick=>{
  const s=make(true);for(let i=0;i<30;i++){tick(33);E.teamSprites(s)}
  const day=visible(s);assert.ok(day>=3,'two hens and a goose are out by day, got '+day);
  s.lighting.darkness=1;
  for(let i=0;i<20;i++){tick(33);E.teamSprites(s)}
  assert.ok(visible(s)>=0);
  for(let i=0;i<600;i++){tick(33);E.teamSprites(s)}
  assert.equal(visible(s),0,'everybody is indoors at night');
  s.lighting.darkness=0;
  for(let i=0;i<900;i++){tick(33);E.teamSprites(s)}
  assert.equal(visible(s),day,'everybody is back by day');
  const calm=make(false);calm.lighting.darkness=1;E.teamSprites(calm);assert.equal(visible(calm),0,'calm mode hides them at night without walking');
  calm.lighting.darkness=0;for(let i=0;i<10;i++){tick(33);E.teamSprites(calm)}assert.equal(visible(calm),day);
 });
});

test('a farm refresh at night does not make indoor animals pop out and run home again, and opening after dark starts them indoors',async()=>{
 const E=await import('../../qw_farm/static/scene_expansion.js');
 const farm={id:'f',size:12,pranks:[],equipment:{},helpers:{},objects:[
  {id:'coop',type:'coop',animal:'chicken',x:2,y:2,w:2,h:2},{id:'gh',type:'goose_house',animal:'goose',x:6,y:6,w:2,h:2}]};
 const s={farm,motion:true,time:0,now:()=>0,view:null,placement:null,lighting:{darkness:1},goose(){},c:{save(){},restore(){},translate(){},scale(){},rotate(){},stroke(){},fillText(){},strokeText(){}}};
 withClock(tick=>{
  E.resetWalkingGeese(s);E.resetLivestock(s);
  tick(33);assert.equal(E.teamSprites(s).length,0,'opened after dark: all indoors from the first frame');
  for(let i=0;i<5;i++){tick(33);E.teamSprites(s)}
  E.resetWalkingGeese(s);E.resetLivestock(s);   // what every farm refresh does
  tick(33);assert.equal(E.teamSprites(s).length,0,'a refresh keeps them indoors');
  assert.ok(s.walkingGeese.every(g=>g.mode==='inside')&&s.livestock.every(l=>l.mode==='inside'));
 });
});

test('a goose coming out of its house at dawn always walks back to its strip (no standing at the door)',async()=>{
 const E=await import('../../qw_farm/static/scene_expansion.js');
 const farm={id:'f',size:12,pranks:[],equipment:{},helpers:{},objects:[{id:'gh',type:'goose_house',animal:'goose',x:6,y:6,w:2,h:2},{id:'wall',type:'barn',x:5,y:8,w:4,h:2}]};
 const s={farm,motion:true,time:0,now:()=>0,view:null,placement:null,lighting:{darkness:0},goose(){},c:{save(){},restore(){},translate(){},scale(){},rotate(){},stroke(){},fillText(){},strokeText(){}}};
 withClock(tick=>{
  E.resetWalkingGeese(s);const g=s.walkingGeese[0];E.teamSprites(s);
  g.mode='inside';g.pos={x:g.door.x,y:g.door.y};g.exitAt=undefined;
  for(let i=0;i<400;i++){tick(33);E.teamSprites(s)}
  assert.equal(g.mode,'idle','the goose is back to its normal walk');
 });
});
