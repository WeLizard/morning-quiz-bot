'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const root=path.resolve(__dirname,'../..');
const source=fs.readFileSync(path.join(root,'qw_farm/static/pie-physics.js'),'utf8').replace(/export /g,'');
const context={Math,Number,Array,Object,String,Boolean};
vm.createContext(context);
vm.runInContext(`${source}\nglobalThis.api={craneX,drop,logValid,replay};`,context);
const api=context.api;
const fixtures=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/farm_pie.json'),'utf8'));

function plain(result){return {height:result.height,tower:[...result.tower],miss:result.miss,taps:result.taps};}

test('JS replay agrees with the Python fixture for every run',()=>{
 for(const fixture of fixtures){
  const result=plain(api.replay(fixture.plan,fixture.log));
  assert.deepEqual(result,{height:fixture.height,tower:fixture.tower,miss:fixture.miss,taps:fixture.taps},fixture.seed);
  assert.equal(api.logValid(fixture.plan,fixture.log),true);
 }
});

test('crane and drop use the same integer geometry',()=>{
 const plan=fixtures[0].plan;
 const xs=new Set();
 for(let t=plan.warmup_ms;t<=plan.warmup_ms+plan.t0;t++)xs.add(api.craneX(plan,t,0));
 assert.equal(Math.min(...xs),plan.x0);
 assert.equal(Math.max(...xs),plan.x1);
 assert.deepEqual([...api.drop(220,780,860,560)],[580,780]);
 assert.equal(api.drop(580,780,140,560),null);
});

test('limit, gaps and log types match the Python rules',()=>{
 const plan=fixtures[0].plan;
 assert.equal(api.replay(plan,[0,60000]).taps,2);
 assert.equal(api.replay(plan,[0,60001]).taps,1);
 assert.equal(api.logValid(plan,[]),true);
 assert.equal(api.logValid(plan,[0,399]),false);
 assert.equal(api.logValid(plan,[0,400]),true);
 for(const bad of [[true],[1.5],['10'],[-1]])assert.equal(api.logValid(plan,bad),false);
 assert.equal(api.logValid(plan,new Array(plan.max_taps+1).fill(0)),false);
});

// ---- the game screen: scene contract, camera and the app wiring
const clientSource=fs.readFileSync(path.join(root,'qw_farm/static/pie-game.js'),'utf8');
const clientContext={Math,Number,Array,Object,String,Boolean,JSON,Map,Promise,parseInt};
vm.createContext(clientContext);
vm.runInContext(`${source}\n${clientSource.replace(/^import .*;\r?\n/,'').replace(/export /g,'')}\nglobalThis.ui={GEOM,towerTop,railY,hangY,cameraFor,zoneAt,keyframe,korzhMarkup,pieResultText,towerText};`,clientContext);
const ui=clientContext.ui;

test('the crane base grows with the tower and the camera follows the top',()=>{
 const {GEOM}=ui;
 for(const n of [0,1,5,12,24,40,80]){
  // the beam is 250 above the tower top at every height: the scaffold under it gains a tier per layer
  assert.equal(ui.towerTop(n)-ui.railY(n),250);
  assert.equal(ui.hangY(n)+30+120,ui.towerTop(n));
  // once the camera moves, the tower top stays at the same screen height and the world (not a platform) goes down
  if(n>=3)assert.equal(ui.towerTop(n)+ui.cameraFor(n),GEOM.follow);
 }
 assert.equal(ui.cameraFor(0),0);
 assert.ok(ui.cameraFor(41)>ui.cameraFor(40));
 assert.deepEqual([0,9,10,19,20,31,32,90].map(n=>ui.zoneAt(n).name),['Ярмарка','Ярмарка','Облака','Облака','Стратосфера','Стратосфера','Космос','Космос']);
});

test('sky keyframes interpolate colours and numbers and clamp at the ends',()=>{
 const keys=[[0,'#000000',0],[10,'#ffffff',100]];
 assert.deepEqual([...ui.keyframe(keys,-5)],['#000000',0]);
 assert.deepEqual([...ui.keyframe(keys,5)],['#808080',50]);
 assert.deepEqual([...ui.keyframe(keys,30)],['#ffffff',100]);
});

test('corzh markup scales from a full layer to a thin cut piece',()=>{
 const k={sponge:'#d9a35f',sponge2:'#e3b16e',glaze:'#fbf1dc',jam:'#d98a6a',berry:'#c0544a',edge:'#8f5a2c',edgeContrast:'#3f230b'};
 const full=ui.korzhMarkup(k,220,440,560,0,false);
 assert.match(full,/^<rect x="220" y="440" width="560" height="30"/);
 assert.equal((full.match(/<circle/g)||[]).length,7);
 assert.match(ui.korzhMarkup(k,0,0,560,1,true),/fill="#e3b16e" stroke="#3f230b" stroke-width="4"/);
 const thin=ui.korzhMarkup(k,10,0,6,0,false);
 assert.doesNotMatch(thin,/<path|<circle/);
 assert.doesNotMatch(full+thin,/NaN|undefined/);
 assert.match(ui.pieResultText({height:21,best:21,practice:false,miss:true},{total:45,goal:40}),/Поставлено 21 корж\. .*Башня деревни: 45 из 40\./);
 assert.equal(ui.towerText({total:24,goal:40,players:5}),'Башня деревни: 24 из 40 · участников: 5.');
});

test('installed day and night scenes carry the live layers, height keyframes and no raster',()=>{
 const ids=['pie-sky','pie-sky-0','pie-sky-1','pie-sky-2','pie-stars','pie-earth','pie-world','pie-clouds','pie-ground','pie-scaffold',
  'pie-scaffold-l','pie-scaffold-r','pie-scaffold-cliprect','pie-marks','pie-tower','pie-cuts','pie-falling','pie-crane','pie-trolley',
  'pie-layer','pie-korzh','pie-tier-a','pie-tier-b','pie-tier-deck','pie-plate'];
 for(const file of ['pie-scene.svg','pie-night.svg']){
  const svg=fs.readFileSync(path.join(root,'qw_farm/static',file),'utf8');
  assert.match(svg,/^<svg [^>]*viewBox="0 0 1000 600"/);
  for(const id of ids)assert.equal((svg.match(new RegExp(`id="${id}"`,'g'))||[]).length,1,`${file} ${id}`);
  assert.doesNotMatch(svg,/<image|data:image|<filter| style=/);
  const data=key=>JSON.parse(svg.match(new RegExp(`${key}='([^']+)'`))[1]);
  const sky=data('data-sky'),stars=data('data-stars'),earth=data('data-earth');
  assert.ok(sky.length>=4&&sky.every((row,i)=>row.length===4&&(!i||row[0]>sky[i-1][0])));
  assert.ok(stars.at(-1)[1]>=.85,'stars are out in space');
  assert.ok(earth[0][1]>600&&earth.at(-1)[1]<500,'the Earth rises into the frame with height');
  // ten scaffold tiers on each side at height 0, the beam at y=220 above them, the corzh hanging at 320
  assert.equal((svg.match(/<use href="#pie-tier-/g)||[]).length,20);
  assert.match(svg,/<use href="#pie-korzh" x="500" y="320"\/>/);
  for(const key of ['sponge','sponge2','glaze','jam','berry','edge','edge-contrast'])assert.match(svg,new RegExp(`id="pie-tower"[^>]* data-${key}="#[0-9a-f]{6}"`));
 }
});

test('app.js opens the pie screen from the fair card and closes it like the other village games',async()=>{
 const app=fs.readFileSync(path.join(root,'qw_farm/static/app.js'),'utf8');
 assert.match(app,/^import \{mountPieGame\} from '\.\/pie-game\.js';/m);
 assert.match(app,/pieGame:\(\)=>openPieGame\(\)/);
 // declared with the other nested games, re-rendered after /me and commands, closed on tab change, logout and Escape
 assert.match(app,/ballistaGame=null,ballistaGameOpen=false,pieGame=null,pieGameOpen=false[,;]/);
 assert.ok((app.match(/ballistaGame\?\.render\(\);pieGame\?\.render\(\);/g)||[]).length>=2);
 assert.ok((app.match(/if\(pieGameOpen\)closePieGame\(\);/g)||[]).length>=2);
 assert.match(app,/if\(pieGameOpen\)\{e\.preventDefault\(\);closePieGame\(\);return;\}/);
 for(const [file,needle] of [['qw_farm/static/index.html','id="pie-game-view"'],['qw_farm/static/index.html','/app/farm/assets/pie-game.css'],['qw_farm/static/festivals.js','h.pieGame?.()']])
  assert.ok(fs.readFileSync(path.join(root,file),'utf8').includes(needle),`${file}: ${needle}`);
 const assets=fs.readFileSync(path.join(root,'qw_farm/api.py'),'utf8');
 for(const asset of ['pie-game.js','pie-physics.js','pie-game.css','pie-scene.svg','pie-night.svg'])assert.ok(assets.includes(`'${asset}'`),asset);
 const code=app.slice(app.indexOf('function closePieGame('),app.indexOf('async function openBallistaGame('));
 const calls=[],classes=new Set(),host={id:'pie-game-view'};
 const sandbox={pieGame:null,pieGameOpen:false,
  S:{me:{id:'farm-1',village_games:{agata_pie:{available:true}},festival:{fair:{tower:{total:3,goal:40}}}},pending:null,busy:false},
  own:()=>true,refresh:async()=>{calls.push('refresh');},toast:text=>{calls.push(['toast',text]);},command:()=>{},now:()=>1,
  $:id=>id==='pie-game-view'?host:null,navPush:id=>{calls.push(['push',id]);},navPop:id=>{calls.push(['pop',id]);},
  requestAnimationFrame:fn=>fn(),document:{body:{classList:{add:c=>classes.add(c),remove:c=>classes.delete(c)}},querySelector:()=>null},
  mountPieGame:(node,options)=>{calls.push(['mount',node.id,options.storageKey,options.getState().available,options.tower().goal]);return {render(){calls.push('render');},destroy(){calls.push('destroy');}};}};
 vm.createContext(sandbox);
 vm.runInContext(`${code}\nglobalThis.api={openPieGame,closePieGame,get open(){return pieGameOpen}};`,sandbox);
 const seen=()=>calls.map(c=>JSON.stringify(c));
 await sandbox.api.openPieGame();
 assert.equal(sandbox.api.open,true);assert.ok(classes.has('pie-game-open'));
 assert.deepEqual(seen(),[JSON.stringify(['mount','pie-game-view','farm-1',true,40]),JSON.stringify(['push','agata-pie'])]);
 await sandbox.api.openPieGame();
 assert.ok(calls.includes('render'),'a second open only re-renders');
 sandbox.api.closePieGame();
 assert.equal(sandbox.api.open,false);assert.ok(!classes.has('pie-game-open'));
 assert.ok(calls.includes('destroy')&&seen().includes(JSON.stringify(['pop','agata-pie'])));
 // no fair tower: a refresh, then a clear message instead of an empty screen
 sandbox.S.me.festival={fair:null};calls.length=0;
 await sandbox.api.openPieGame();
 assert.equal(sandbox.api.open,false);
 assert.deepEqual(seen(),[JSON.stringify('refresh'),JSON.stringify(['toast','Пирог до небес ждёт ярмарки.'])]);
});
