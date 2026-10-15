const {test}=require('node:test');
const assert=require('node:assert/strict');

async function withFrameLoop(run,{now=()=>0}={}){
 const previous={document:global.document,requestAnimationFrame:global.requestAnimationFrame,
  cancelAnimationFrame:global.cancelAnimationFrame,performance:global.performance};
 let nextRaf=0,cancelled=[];
 global.document={hidden:false};
 global.requestAnimationFrame=()=>++nextRaf;
 global.cancelAnimationFrame=id=>cancelled.push(id);
 global.performance={now};
 try{
  const {FarmScene}=await import('../../qw_farm/static/scene.js');
  const drawn=[];
  const scene=Object.create(FarmScene.prototype);
  Object.assign(scene,{motion:true,frameInterval:32,lastFrame:0,dirty:false,particles:[],
   cost:0,paused:false,raf:0,anim:null,stepCamera(){},draw(t){drawn.push(t)}});
  await run({scene,drawn,cancelled});
 }finally{
  for(const [key,value] of Object.entries(previous)){
   if(value===undefined)delete global[key];else global[key]=value;
  }
 }
}

test('frame pacing keeps near 30 drawn frames per second at 60, 75 and 120 Hz',async()=>{
 await withFrameLoop(({scene,drawn})=>{
  for(const hz of [60,75,120]){
   drawn.length=0;scene.lastFrame=0;scene.frameInterval=32;scene.cost=0;
   for(let n=1;n<=hz;n++)scene.tick(n*1000/hz);
   assert.ok(drawn.length>=29&&drawn.length<=31,`${hz} Hz drew ${drawn.length} frames`);
   assert.ok(drawn.every((t,i)=>!i||t>drawn[i-1]),`${hz} Hz timestamps advance`);
  }
 });
});

test('a long RAF gap draws once and carries only a bounded remainder',async()=>{
 await withFrameLoop(({scene,drawn})=>{
  scene.lastFrame=100;
  scene.tick(10000);
  assert.deepEqual(drawn,[10]);
  assert.ok(10000-scene.lastFrame>=0&&10000-scene.lastFrame<scene.frameInterval);
  scene.tick(10013);
  assert.equal(drawn.length,1);
  scene.tick(10027);
  assert.equal(drawn.length,2);
 });
});

test('the carried remainder is remapped when the adaptive interval shrinks',async()=>{
 await withFrameLoop(({scene,drawn})=>{
  scene.frameInterval=100;scene.lastFrame=100;scene.cost=1;
  scene.tick(295);
  assert.equal(drawn.length,1);
  assert.equal(scene.frameInterval,32);
  assert.equal(scene.lastFrame,264);
  scene.tick(296);
  assert.equal(drawn.length,2);
 },{now:()=>0});
});

test('pause cancels the loop and resume starts a fresh timing window',async()=>{
 await withFrameLoop(({scene,drawn,cancelled})=>{
  scene.raf=7;scene.lastFrame=100;scene.clearInput=()=>{};
  scene.setPaused(true);
  assert.deepEqual(cancelled,[7]);
  scene.tick(5000);
  assert.equal(drawn.length,0);
  scene.setPaused(false);
  assert.equal(scene.lastFrame,0);
  scene.tick(5016);
  assert.deepEqual(drawn,[5.016]);
 });
});

test('reduced motion draws dirty changes immediately and otherwise stays idle',async()=>{
 await withFrameLoop(({scene,drawn})=>{
  scene.motion=false;scene.lastFrame=5000;
  scene.tick(5001);
  assert.equal(drawn.length,0);
  scene.dirty=true;scene.tick(5002);
  assert.deepEqual(drawn,[5.002]);
  assert.equal(scene.lastFrame,5002);
  scene.tick(5003);
  assert.equal(drawn.length,1);
  scene.dirty=true;scene.tick(5004);
  assert.deepEqual(drawn,[5.002,5.004]);
 });
});
