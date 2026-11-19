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

test('object sprites: still art is painted once and blitted, marks replay live, animated art stays live at rest',async()=>{
 const {FarmScene}=await import('../../qw_farm/static/scene.js');
 const previousDocument=global.document;
 const ctx=()=>{const g={blits:0,setTransform(){},save(){},restore(){},clearRect(){},drawImage(){g.blits++}};return g};
 global.document={createElement(){const g=ctx();return {width:0,height:0,getContext(){return g}}}};
 try{
  const painted=[],marks=[],scene=Object.create(FarmScene.prototype),main=ctx();
  const barn={id:'barn',type:'barn',x:2,y:2,w:2,h:2},mill={id:'mill',type:'mill',x:5,y:5,w:2,h:2};
  Object.assign(scene,{
   c:main,farm:{objects:[barn,mill]},catalog:{},pan:{x:0,y:0},scale:1,dpr:1,motion:true,time:5,frameInterval:32,
   stats:{frames:0},lanternLights:[],lightMarkers:null,frameOrigin:{x:0,y:0},
   ready(x,y){marks.push(['ready',x,y])},
   drawObject(o){painted.push(o.id);this.ready(1,2);this.lanternLights?.push({x:3,y:4});if(o.id==='mill')void this.time}
  });
  const frame=()=>{scene.stats.frames++;scene.lanternLights=[];scene.drawObjectSprite(barn);scene.drawObjectSprite(mill)};
  scene.cameraKey='0|0|1';scene.cameraAt=-1e9;   // the camera rests
  frame();frame();frame();
  assert.deepEqual(painted.filter(id=>id==='barn'),['barn'],'still art is painted once');
  assert.equal(painted.filter(id=>id==='mill').length,4,'animated art: one sprite paint, then live while cheap');
  assert.equal(marks.length,6,'the ready mark of both objects is drawn every frame');
  assert.equal(scene.lanternLights.length,2,'lantern glows are replayed from the sprite');
  assert.equal(main.blits,3,'the barn is blitted');
  scene.pan.x=10;painted.length=0;frame();          // the camera starts moving: the mill's sprite is refreshed once
  assert.deepEqual(painted,['mill']);assert.equal(main.blits,5);
  scene.pan.x=20;painted.length=0;frame();          // and borrowed while the camera keeps moving
  assert.deepEqual(painted,[]);assert.equal(main.blits,7);
  scene.selected='barn';painted.length=0;frame();   // a selected object is drawn live
  assert.deepEqual(painted,['barn']);
  assert.equal(scene.time,5,'the clock is restored after a sprite paint');
  assert.equal(Object.hasOwn(scene,'now'),false);
 }finally{
  if(previousDocument===undefined)delete global.document;else global.document=previousDocument;
 }
});
