const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const app=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
const clickSource=app.slice(app.indexOf('function clickObject('),app.indexOf('function renderPanel('));

test('meadow patch uses the shared grass strokes and winter snow',async()=>{
 const {FarmScene}=await import('../../qw_farm/static/scene.js');
 const lines=[],ellipses=[];
 const scene=Object.create(FarmScene.prototype);
 Object.assign(scene,{farm:{size:12,meadow_view:{season:'summer'}},line(...args){lines.push(args)},ellipse(...args){ellipses.push(args)}});
 scene.drawMeadow({cell:'4,5',stage:2});
 assert.equal(lines.length,9);
 assert.equal(ellipses.length,2);
 lines.length=0;ellipses.length=0;
 scene.farm.meadow_view.season='winter';
 scene.drawMeadow({cell:'4,5',stage:1});
 assert.equal(lines.length,7);
 assert.equal(ellipses.length,1);
});

test('a successful planting selects the newly planted bed; a failed planting preserves the old selection',async()=>{
 const previous={id:'old-plot',type:'plot',x:1,y:1,w:1,h:1};
 const next={id:'new-plot',type:'plot',x:2,y:1,w:1,h:1};
 let resolvePlant;
 const panelSelections=[];
 const state={selected:previous.id,seed:'carrot',catalog:{},me:{id:'account'},farm:{id:'home-farm',is_owner:true},tab:'object'};
 const scene={selected:previous.id,focus(o){this.selected=o.id;}};
 const context={S:state,scene,farmViewEpoch:3,hideStoneSpeech(){},own:()=>state.farm.is_owner,now:()=>100,
  MERCH:{plantRequest:()=>({command:['plant',{object:next.id,crop:'carrot'}]})},stock:()=>0,
  renderPanel:()=>panelSelections.push(state.selected),
  command:()=>new Promise(resolve=>{resolvePlant=resolve;})};
 vm.createContext(context);vm.runInContext(clickSource,context);

 context.clickObject(next,{x:2,y:1});
 resolvePlant(false);await Promise.resolve();await Promise.resolve();
 assert.equal(state.selected,previous.id,'a rejected planting does not move selection');
 assert.equal(scene.selected,previous.id,'a rejected planting keeps the existing map marker');
 assert.deepEqual(panelSelections,[],'a rejected planting does not rerender the object card');

 context.clickObject(next,{x:2,y:1});
 resolvePlant(true);await Promise.resolve();await Promise.resolve();
 assert.equal(state.selected,next.id);
 assert.equal(scene.selected,next.id,'the new bed receives the timer marker');
 assert.deepEqual(panelSelections,[next.id],'the open object card rerenders after selection changes');

 state.selected=previous.id;scene.selected=previous.id;
 context.clickObject(next,{x:2,y:1});
 context.farmViewEpoch++;state.tab='orders';
 resolvePlant(true);await Promise.resolve();await Promise.resolve();
 assert.equal(state.selected,previous.id,'navigation during the request keeps the current selection');
 assert.equal(scene.selected,previous.id,'navigation during the request does not restore the old bed marker');
 assert.deepEqual(panelSelections,[next.id],'a different tab is not rerendered after navigation');
});

test('a meadow tap works at phone fit scale and obeys growth, winter, and ownership',()=>{
 const calls=[],notices=[],scene={scale:.85,burst(){calls.push('burst')}};
 const state={farm:{is_owner:true,meadow_view:{season:'summer',patches:[{cell:'4,5',stage:2}]}}};
 const context={S:state,scene,hideStoneSpeech(){},own:()=>state.farm.is_owner,toast:s=>notices.push(s),command:(kind,data)=>{calls.push([kind,data]);return Promise.resolve(false)}};
 vm.createContext(context);vm.runInContext(clickSource,context);
 const tap=()=>context.clickObject({type:'meadow',cell:'4,5'},{x:4,y:5});
 tap();assert.equal(calls.length,1);assert.deepEqual(JSON.parse(JSON.stringify(calls[0])),['mow',{cell:'4,5'}]);
 state.farm.meadow_view.patches[0].stage=0;tap();assert.equal(calls.length,1);assert.match(notices.at(-1),/Ещё растёт/);
 state.farm.meadow_view.patches[0].stage=2;state.farm.meadow_view.season='winter';tap();assert.equal(calls.length,1);
 state.farm.is_owner=false;state.farm.meadow_view.patches[0].stage=2;tap();assert.equal(calls.length,1);
});

test('grass has no bulk button or zoom instruction in the client',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/index.html'),'utf8');
 assert.doesNotMatch(app+html,/mow-all|Скосить траву|Приблизь или нажми/);
});

test('grass target is 44 screen pixels at fit scale and leaves other objects priority',async()=>{
 const {FarmScene}=await import('../../qw_farm/static/scene.js');
 const scene=Object.create(FarmScene.prototype),patch={cell:'4,5',stage:2};
 let point={x:-36,y:175},cell={x:3,y:5},objects=[];
 Object.assign(scene,{scale:.85,farm:{size:12,is_owner:true,meadow_view:{patches:[patch]}},
  grid:()=>12,world:()=>point,cell:()=>cell,pondCenter:()=>({x:-999,y:-999}),lakeSize:()=>({rx:1,ry:1}),
  projectStage:()=>0,arborPos:()=>({x:-999,y:-999}),stonePos:()=>({x:-999,y:-999}),sortedObjects:()=>({list:objects}),team:[]});
 // Patch centre is (-36,180), target centre is (-36,175). Test all four screen edges from an adjacent cell.
 for(const [dx,dy] of [[22,0],[-22,0],[0,22],[0,-22]]){
  point={x:-36+dx/.85,y:175+dy/.85};assert.equal(scene.pick(0,0)?.cell,'4,5');
 }
 point={x:-36+23/.85,y:175};assert.equal(scene.pick(0,0),null);
 // Being inside the isometric cell does not enlarge the target beyond its 44px square.
 cell={x:4,y:5};point={x:-36+23/.85,y:180};assert.equal(scene.pick(0,0),null);
 // The nearest patch wins even when the inverse cell still belongs to the other patch.
 scene.farm.meadow_view.patches.push({cell:'5,5',stage:2});point={x:-16,y:182};
 assert.equal(scene.pick(0,0).cell,'5,5');scene.farm.meadow_view.patches.pop();cell={x:3,y:5};
 point={x:-36,y:175};objects=[{id:'plot',type:'plot',x:3,y:5,w:1,h:1}];assert.equal(scene.pick(0,0).id,'plot');
 // A building silhouette over the patch must win even when its footprint is elsewhere.
 objects=[{id:'house',type:'coop',x:4,y:5,w:1,h:1}];assert.equal(scene.pick(0,0).id,'house');
 objects=[];scene.farm.is_owner=false;assert.equal(scene.pick(0,0),null);
});
