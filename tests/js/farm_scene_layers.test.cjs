const {test}=require('node:test');
const assert=require('node:assert/strict');

test('plants stay below solid and moving sprites without allocating crop canvases',async()=>{
 const {FarmScene}=await import('../../qw_farm/static/scene.js');
 const previousDocument=global.document;
 global.document={createElement(){assert.fail('the vegetation layer must not allocate scratch canvases')}};
 try{
  const log=[],scene=Object.create(FarmScene.prototype),bounds={x0:-1000,y0:-1000,x1:1000,y1:1000};
  const plant=(id,x,y)=>({x,y,w:0,h:0,bounds,draw(){log.push(id)}});
  const fence={x:2,y:2,w:0,h:0,bounds,draw(){log.push('fence')}};
  Object.assign(scene,{
   farm:{size:12,objects:[],pranks:[{until:100}]},layout:{after:[]},stats:{},time:0,
   now(){return 0},forestFog(){},plotGround(){log.push('soil')},plotMarkers(){log.push('marker')},
   goose(){log.push('goose')},paintTrees(){log.push('trees')},
   standingOrder(){return{plots:[{object:{id:'bed'},bounds}],crops:[plant('back-crop',0,0),plant('front-crop',10,10)],entries:[fence]}}
  });
  // The moving goose is behind the front crop by depth, but vegetation must stay below it.
  for(let i=0;i<3;i++)scene.paintDynamic({},bounds);
  assert.deepEqual(log,Array(3).fill(['soil','back-crop','front-crop','fence','goose','marker','trees']).flat());
 }finally{
  if(previousDocument===undefined)delete global.document;else global.document=previousDocument;
 }
});

test('standing layers cache crop order; roaming animals leave the static order and stay after their house',async()=>{
 const {FarmScene}=await import('../../qw_farm/static/scene.js');
 const {compareDepth}=await import('../../qw_farm/static/scene_map.js');
 const scene=Object.create(FarmScene.prototype);
 Object.assign(scene,{
  farm:{objects:[
   {id:'front-bed',type:'plot',x:5,y:5,w:1,h:1,crop:{id:'wheat'}},
   {id:'back-bed',type:'plot',x:1,y:1,w:1,h:1,crop:{id:'corn'}},
   {id:'coop',type:'coop',animal:'chicken',x:2,y:2,w:2,h:2}
  ]},layout:{key:'12|12',area:12}
 });
 const order=scene.standingOrder();
 assert.equal(order.crops.length,12);
 assert.equal(order.plots.length,2);
 const house=order.entries.findIndex(e=>e.id==='coop');
 assert.equal(order.entries.filter(e=>e.parentId==='coop').length,0,'chickens roam: they are no longer part of the cached order');
 const E=await import('../../qw_farm/static/scene_expansion.js');
 const {spriteSlots}=await import('../../qw_farm/static/scene_map.js');
 scene.farm.id='f';scene.farm.size=12;scene.farm.equipment={};scene.farm.helpers={};scene.farm.pranks=[];scene.motion=false;scene.time=0;scene.now=()=>0;scene.view=null;
 E.resetWalkingGeese(scene);E.resetLivestock(scene);
 const roaming=E.teamSprites(scene).filter(sp=>sp.parentId==='coop');
 assert.equal(roaming.length,2,'a coop keeps two hens');
 const list=order.entries.filter(e=>e.id==='coop'),slots=spriteSlots(list,roaming);
 assert.equal(slots[0].length,0);assert.equal(slots[1].length,2,'both hens are painted after their coop');
 assert.ok(order.crops.every(e=>!order.entries.includes(e)),'plants are separate from solid depth entries');
 for(let i=1;i<order.crops.length;i++)assert.ok(compareDepth(order.crops[i-1],order.crops[i])<=0);
 assert.equal(scene.standingOrder(),order,'unchanged snapshots reuse the sorted layers');
});

test('layer renderer pauses and resumes without leaving an animation frame behind',async()=>{
 const {FarmScene}=await import('../../qw_farm/static/scene.js');
 const previous={document:global.document,requestAnimationFrame:global.requestAnimationFrame,cancelAnimationFrame:global.cancelAnimationFrame};
 let cancelled=0,cleared=0,requested=0;
 global.document={hidden:false};
 global.cancelAnimationFrame=id=>{cancelled=id};
 global.requestAnimationFrame=()=>{requested++;return 23};
 try{
  const scene=Object.create(FarmScene.prototype);
  Object.assign(scene,{paused:true,raf:12,anim:{},clearInput(){cleared++}});
  scene.syncLoop();
  assert.equal(cancelled,12);assert.equal(scene.raf,0);assert.equal(cleared,1);assert.equal(scene.anim,null);
  scene.paused=false;scene.syncLoop();scene.syncLoop();
  assert.equal(scene.raf,23);assert.equal(requested,1);assert.equal(scene.dirty,true);assert.equal(scene.lastFrame,0);
  global.document.hidden=true;scene.syncLoop();assert.equal(cancelled,23);assert.equal(scene.raf,0);
 }finally{
  for(const [key,value] of Object.entries(previous))if(value===undefined)delete global[key];else global[key]=value;
 }
});
