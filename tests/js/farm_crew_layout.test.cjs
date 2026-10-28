const {test}=require('node:test');
const assert=require('node:assert/strict');

const catalog={equipment:{tractor:{role:'sow'},robot:{role:'harvest'}},helpers:{rabbit_gardener:{role:'water'},cat_keeper:{role:'animals'},raccoon:{role:'production'}}};
const working={shift:{status:'working',until:200}};
function farm(){return {id:'crew-test',size:16,objects:[
 {id:'barn',type:'barn',x:1,y:1,w:2,h:2,jobs:[]},
 {id:'bed',type:'plot',x:8,y:8,w:1,h:1,crop:{id:'wheat',ready_at:80}},
 {id:'bed2',type:'plot',x:9,y:8,w:1,h:1,crop:{id:'wheat',ready_at:120}},
 {id:'coop',type:'coop',x:12,y:2,w:2,h:2,animal:'chicken',jobs:[]},
 {id:'road',type:'road',x:4,y:4,w:1,h:1}],
 meadow_view:{patches:[{cell:'7,7',stage:2}]},equipment:{tractor:{...working},robot:{}},
 helpers:{rabbit_gardener:{...working,zone:{x:8,y:8,w:1,h:1}},cat_keeper:{...working},raccoon:{}},pranks:[]};}
const iso=(x,y)=>({x:(x-y)*36,y:(x+y)*18});
const bounds=(v,pad=0)=>{const p=iso(v.x,v.y);return {x0:p.x-(v.machine?30:18)-pad,x1:p.x+(v.machine?40:29)+pad,y0:p.y-(v.machine?49:48)-pad,y1:p.y+11+pad};};
const intersects=(a,b)=>a.x0<b.x1&&a.x1>b.x0&&a.y0<b.y1&&a.y1>b.y0;

test('crew stands on clear land near its role target; beds, roads, meadow and other crew remain clear',async()=>{
 const E=await import('../../qw_farm/static/scene_expansion.js'),f=farm(),before=structuredClone(f),layout=E.crewLayout(f,catalog,100);
 assert.equal(layout.length,5,'a spacious farm displays its whole crew');
 assert.equal(layout.find(x=>x.id==='rabbit_gardener').targetId,'bed','helper respects its task zone');
 assert.equal(layout.find(x=>x.id==='cat_keeper').targetId,'coop');
 assert.equal(layout.find(x=>x.id==='raccoon').active,false);
 for(const person of layout){
  assert.ok(person.x>=0&&person.y>=0&&person.x<f.size&&person.y<f.size);
  assert.ok(!f.objects.some(o=>person.x>=o.x&&person.x<o.x+o.w&&person.y>=o.y&&person.y<o.y+o.h),'no figure stands on an object');
  assert.notEqual(`${Math.floor(person.x)},${Math.floor(person.y)}`,'7,7','meadow remains tappable');
  for(const bed of f.objects.filter(o=>o.type==='plot')){
   const p=iso(bed.x+.5,bed.y+.5);
   assert.ok(!intersects(bounds(person),{x0:p.x-36,x1:p.x+36,y0:p.y-52,y1:p.y+20}),'the full figure clears the crop and bed tap target');
  }
 }
 for(let i=0;i<layout.length;i++)for(let j=i+1;j<layout.length;j++)assert.ok(!intersects(bounds(layout[i],4),bounds(layout[j],4)),'figures have space between them');
 assert.deepEqual(f,before,'layout has no authority over the saved farm');
 assert.deepEqual(E.crewLayout(f,catalog,100),layout,'layout is deterministic');
});

test('rest follows the moved barn and a fully occupied farm keeps the crew indoors',async()=>{
 const E=await import('../../qw_farm/static/scene_expansion.js'),f=farm();f.equipment={};f.helpers={raccoon:{}};f.objects=f.objects.filter(o=>o.type==='barn');
 const first=E.crewLayout(f,catalog,100)[0];
 f.objects[0]={...f.objects[0],x:11,y:11};
 const second=E.crewLayout(f,catalog,100)[0];
 const distance=(p,x,y)=>(p.x-x)**2+(p.y-y)**2;
 assert.ok(distance(first,2,2)<distance(first,12,12));assert.ok(distance(second,12,12)<distance(second,2,2));
 f.objects=Array.from({length:256},(_,i)=>({id:`p${i}`,type:'plot',x:i%16,y:Math.floor(i/16),w:1,h:1}));
 assert.deepEqual(E.crewLayout(f,catalog,100),[],'no fallback stacks the crew on top of occupied cells');
});

test('production helpers work beside a catalog workshop, not an animal building with an empty jobs array',async()=>{
 const E=await import('../../qw_farm/static/scene_expansion.js'),f=farm();
 f.equipment={};f.helpers={raccoon:{...working}};f.objects.push({id:'mill',type:'mill',x:4,y:10,w:2,h:2,jobs:[]});
 const withRecipes={...catalog,recipes:{flour:{building:'mill'}}};
 const worker=E.crewLayout(f,withRecipes,100)[0];
 assert.equal(worker.targetId,'mill');assert.equal(worker.active,true);
 f.objects=f.objects.filter(o=>o.type!=='mill');
 assert.equal(E.crewLayout(f,withRecipes,100)[0].active,false,'without a workplace the helper rests');
});

test('additional craft helpers appear as crew using the existing beaver and badger figures',async()=>{
 const E=await import('../../qw_farm/static/scene_expansion.js'),f=farm();
 f.equipment={};f.helpers={beaver_artisan_2:{...working},badger_artisan_2:{...working}};
 f.objects.push({id:'mill',type:'mill',x:4,y:10,w:2,h:2,jobs:[]});
 const withRecipes={...catalog,helpers:{beaver_artisan_2:{role:'craft'},badger_artisan_2:{role:'craft'}},recipes:{flour:{building:'mill'}}};
 const layout=E.crewLayout(f,withRecipes,100);
 assert.deepEqual(layout.map(x=>x.id).sort(),['badger_artisan_2','beaver_artisan_2']);
 assert.ok(layout.every(x=>x.active&&x.targetId==='mill'),'both new IDs draw as active workers at their workshop');
});

test('vehicle tap matches the drawn frame, never ticks livestock, and calm mode is stationary',async()=>{
 const E=await import('../../qw_farm/static/scene_expansion.js');let now=199;
 const s={farm:farm(),catalog,time:10,motion:true,now:()=>now,view:null};
 const drawn=E.teamSprites(s).filter(x=>x.crewId),tractor=drawn.find(x=>x.machine==='tractor');
 const signature=items=>items.map(({crewId,x,y,wx,wy})=>({crewId,x,y,wx,wy}));
 now=201;
 assert.deepEqual(signature(E.teamSprites(s).filter(x=>x.crewId)),signature(drawn),'shift expiry cannot relocate a sprite in an already drawn frame');
 s.walkingGeese=[{get mode(){throw new Error('hit test must not advance geese');}}];
 assert.equal(E.machineAt(s,tractor.wx,tractor.wy-10),'tractor');
 delete s.walkingGeese;s.time=11;
 assert.equal(s.crewLayoutCache.layout.find(x=>x.id==='tractor').active,true);
 E.teamSprites(s);assert.equal(s.crewLayoutCache.layout.find(x=>x.id==='tractor').active,false,'expiry applies on the next frame');
 now=100;s.motion=false;s.time=20;
 const calm=signature(E.teamSprites(s).filter(x=>x.crewId));s.time=2000;
 assert.deepEqual(signature(E.teamSprites(s).filter(x=>x.crewId)),calm,'reduced motion does not move figures even if a caller advances time');
 s.farm={...s.farm,objects:[...s.farm.objects,{id:'new-building',type:'barn',x:Math.floor(tractor.x),y:Math.floor(tractor.y),w:1,h:1}]};
 const after=E.teamSprites(s).find(x=>x.machine==='tractor');
 assert.ok(!after||after.x!==tractor.x||after.y!==tractor.y,'a new farm snapshot invalidates occupied parking');
});

test('calm draws with time fixed at zero refresh expired shifts, while a tap uses the last drawn position',async()=>{
 const E=await import('../../qw_farm/static/scene_expansion.js');let now=199;
 // Scene.draw sets this.time to zero for every frame when motion is disabled.
 const s={farm:farm(),catalog,time:0,motion:false,now:()=>now,view:null};
 const drawn=E.teamSprites(s).find(x=>x.machine==='tractor');
 assert.equal(s.crewLayoutCache.layout.find(x=>x.id==='tractor').active,true);
 now=201;
 assert.equal(E.machineAt(s,drawn.wx,drawn.wy-10),'tractor','the existing frame remains tappable after its shift expires');
 assert.equal(s.crewLayoutCache.layout.find(x=>x.id==='tractor').active,true,'hit testing does not refresh a frame');
 const resting=E.teamSprites(s).find(x=>x.machine==='tractor');
 assert.equal(s.time,0);assert.equal(s.crewLayoutCache.layout.find(x=>x.id==='tractor').active,false,'the next calm draw retires the worker without a new farm snapshot');
 assert.equal(E.machineAt(s,resting.wx,resting.wy-10),'tractor','hit testing follows the newly drawn rest position');
 now=202;
 const next=E.teamSprites(s).find(x=>x.machine==='tractor');
 assert.deepEqual([next.x,next.y,next.wx,next.wy],[resting.x,resting.y,resting.wx,resting.wy],'calm frames remain stationary after the status change');
});
