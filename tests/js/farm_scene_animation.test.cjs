const {test}=require('node:test');
const assert=require('node:assert/strict');

test('moving the farm camera keeps animated objects on live frames',async()=>{
 const {FarmScene}=await import('../../qw_farm/static/scene.js');
 const times=[],origins=[];
 const context={setTransform(){},clearRect(){},translate(){},scale(){},save(){},restore(){}};
 const scene=Object.create(FarmScene.prototype);
 Object.assign(scene,{
  c:context,w:320,h:480,dpr:1,farm:{size:12},layout:{key:'12|12'},motion:true,
  pan:{x:0,y:0},pointers:new Map([[1,{x:80,y:120}]]),moved:true,
  placement:null,hover:null,hoverId:null,particles:[],stats:{frames:0},cb:{},
  origin(){return{x:160+this.pan.x,y:80+this.pan.y}},
  background(){},groundWash(){},staticLayer(origin){origins.push(origin.x)},
  viewRect(){return{x0:-160,y0:-80,x1:160,y1:400}},
  paintDynamic(){times.push(this.time)},ellipse(){}
 });
 scene.draw(1);
 scene.pan.x=24;
 scene.draw(1.05);
 assert.deepEqual(origins,[160,184]);
 assert.deepEqual(times,[1,1.05]);
});

test('camera movement respects the adaptive frame interval',async()=>{
 const {FarmScene}=await import('../../qw_farm/static/scene.js');
 const previousDocument=global.document,previousRaf=global.requestAnimationFrame;
 const frames=[];
 global.document={hidden:false};global.requestAnimationFrame=()=>{};
 try{
  const scene=Object.create(FarmScene.prototype);
  Object.assign(scene,{motion:true,frameInterval:40,lastFrame:100,dirty:true,particles:[],cost:0,
   stepCamera(){},draw(time){frames.push(time)}});
  scene.tick(120);
  assert.deepEqual(frames,[]);
  scene.tick(140);
  assert.deepEqual(frames,[.14]);
 }finally{
  if(previousDocument===undefined)delete global.document;else global.document=previousDocument;
  if(previousRaf===undefined)delete global.requestAnimationFrame;else global.requestAnimationFrame=previousRaf;
 }
});
