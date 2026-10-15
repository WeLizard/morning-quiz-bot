const {test}=require('node:test');
const assert=require('node:assert/strict');
function makeScene(FarmScene,projects){
 const scene=Object.create(FarmScene.prototype),calls={lines:[],ellipses:[],polys:[]};
 Object.assign(scene,{farm:{id:'farm',size:12,home_projects:projects},
  line(...args){calls.lines.push(args)},ellipse(...args){calls.ellipses.push(args)},poly(...args){calls.polys.push(args)}});
 return {scene,calls};
}

test('the pier stays hidden until its project starts and stages reveal the requested details',async()=>{
 const {FarmScene}=await import('../../qw_farm/static/scene.js');
 for(const projects of [undefined,{entries:{lake_pier:{stage:0}}}]){
  const {scene,calls}=makeScene(FarmScene,projects);scene.lakePier(12);
  assert.deepEqual(calls,{lines:[],ellipses:[],polys:[]});
 }
 const {scene:stage1,calls:first}=makeScene(FarmScene,{entries:{lake_pier:{stage:1}}});stage1.lakePier(12);
 assert.ok(first.polys.length>0,'stage 1 has the deck');
 for(const color of ['#a27e55','#ad8558','#6b6048','#8c7558'])assert.ok(!first.lines.some(call=>call[4]===color)&&!first.polys.some(call=>call[1]===color),`${color} belongs to the completed stage`);
 const {scene:stage2,calls:finished}=makeScene(FarmScene,{entries:{lake_pier:{stage:2}}});stage2.lakePier(12);
 for(const color of ['#a27e55','#ad8558','#6b6048','#8c7558'])assert.ok(finished.lines.some(call=>call[4]===color)||finished.polys.some(call=>call[1]===color),`${color} appears at stage 2`);
});

test('the water remains clickable from shore while the unbuilt dock hitbox is disabled',async()=>{
 const {FarmScene}=await import('../../qw_farm/static/scene.js');
 const {iso}=await import('../../qw_farm/static/scene_map.js');
 const project=(stage)=>stage===undefined?undefined:{entries:{lake_pier:{stage}}};
 const pickAt=stage=>{
  const {scene}=makeScene(FarmScene,project(stage));Object.assign(scene,{grid:()=>12,cell:()=>({x:2,y:12}),world:()=>iso(2,12.1),
   pondCenter:()=>({x:-400,y:330}),lakeSize:()=>({rx:120,ry:63}),sortedObjects:()=>({list:[]})});
  return scene.pick(0,0);
 };
 assert.equal(pickAt(undefined),null);
 assert.equal(pickAt(0),null);
 assert.deepEqual(pickAt(1),{type:'lake',id:'lake'});
 const {scene:water}=makeScene(FarmScene,undefined);Object.assign(water,{grid:()=>12,cell:()=>({}),world:()=>({x:-400,y:330}),
  pondCenter:()=>({x:-400,y:330}),lakeSize:()=>({rx:120,ry:63}),sortedObjects:()=>({list:[]})});
 assert.deepEqual(water.pick(0,0),{type:'lake',id:'lake'});
});
