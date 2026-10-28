const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');
const game = readFileSync(join(__dirname, '../../minigames/alchemia-1.0/game.js'), 'utf8');
function engine(w=350,h=220) {
 let next=0;
 const env={state:{bench:[]},found:new Set(['a','b','c']),tokenSize:{w:66,h:76},board:{clientWidth:w,clientHeight:h},phone:{matches:true},MAX_TOKENS:36,
  uid:()=>String(++next),clamp:(n,a,b)=>Math.max(a,Math.min(Math.max(a,b),n)),measureTokens(){},showToast(){},undoStack:[],selected:null,
  clone:v=>JSON.parse(JSON.stringify(v)),$:()=>({}),renderBoard(){},persist(){},closeModal(){},announce(){},validPair:()=>true};
 runInNewContext(game.slice(game.indexOf('function pushUndo()'),game.indexOf('function applySettings()')),env);
 runInNewContext(game.slice(game.indexOf('function chooseFromCollection('),game.indexOf('function chooseToken(')),env);
 runInNewContext(game.slice(game.indexOf('function padBottom()'),game.indexOf('function updateTokenPositions()')),env);
 runInNewContext(game.slice(game.indexOf('function tokenOverlaps('),game.indexOf('function chooseFromCollection(')),env);
 runInNewContext(game.slice(game.indexOf('function arrangeBench('),game.indexOf('function clearBench(')),env);
 runInNewContext(game.slice(game.indexOf('function loadPair('),game.indexOf('function pinGoal(')),env);
 return env;
}
const snapshot=e=>JSON.stringify(e.state.bench);
function separated(e){
 assert.equal(e.benchCrowded(),false);
 for(const t of e.state.bench){const p=e.xy(t);assert.ok(p.x>=8&&p.x+66<=e.board.clientWidth-8);assert.ok(p.y>=26&&p.y+76<=e.board.clientHeight-24);}
}
test('phone fills two rows, then rejects overflow without changing existing positions',()=>{
 const e=engine();for(let i=0;i<8;i++)assert.ok(e.addToken('a'));separated(e);
 const before=snapshot(e);assert.equal(e.addToken('b'),null);assert.equal(snapshot(e),before);
});
test('requested positions near occupied cards relocate with an 8px gap',()=>{
 const e=engine();assert.ok(e.addToken('a',{u:.3,v:.43}));assert.ok(e.addToken('b',{u:.3,v:.43}));separated(e);
 const t=e.state.bench[0];assert.ok(e.placeToken(t,{u:e.state.bench[1].u,v:e.state.bench[1].v}));separated(e);
});
test('compact grid fallback does not compress overlapping rows and arrange undo stays valid',()=>{
 const e=engine();for(let i=0;i<8;i++)e.addToken('a');e.arrangeBench();separated(e);
 assert.equal(e.undoStack.length,1);const before=e.undoStack.pop();e.state.bench=before;separated(e);
 // An imported overcrowded table must not be compressed further by Arrange.
 e.state.bench.push({uid:'legacy',id:'a',u:.5,v:.5});const saved=snapshot(e);e.arrangeBench();assert.equal(snapshot(e),saved);assert.equal(e.undoStack.length,0);
});
test('loading a recipe is atomic at physical capacity and one undo restores a successful pair',()=>{
 const e=engine();for(let i=0;i<7;i++)e.addToken('a');const before=snapshot(e);e.loadPair('a+b');assert.equal(snapshot(e),before);assert.equal(e.undoStack.length,0);
 e.state.bench.pop();const six=snapshot(e);e.loadPair('a+b');assert.equal(e.state.bench.length,8);separated(e);assert.equal(e.selected,e.state.bench[6].uid);assert.equal(e.undoStack.length,1);e.state.bench=e.undoStack.pop();assert.equal(snapshot(e),six);
});
test('explicit mixing drop can temporarily occupy a full table; result uses a vacated source position',()=>{
 const e=engine();for(let i=0;i<8;i++)e.addToken('a');const target=e.state.bench[0],pos={u:target.u,v:target.v};
 const moving=e.addToken('b',pos,true);assert.ok(moving);e.state.bench=e.state.bench.filter(t=>t!==target&&t!==moving);assert.ok(e.addToken('c',pos));separated(e);
});
test('desktop header and sort fixes remain in the source and built page',()=>{
 const css=readFileSync(join(__dirname,'../../minigames/alchemia-1.0/style.css'),'utf8');
 const html=readFileSync(join(__dirname,'../../web/mini_client/alchemy.html'),'utf8');
 assert.match(css,/body \.topbar \.nav-btn\{padding-block:0\}/);
 assert.match(css,/body \.collection-meta select\{flex:1 1 auto;min-width:0;max-width:none;/);
 for(const label of ['Сначала новые','По алфавиту','Сначала простые'])assert.ok(html.includes(label));
});
function drop(e,target,mixed=false){
 e.performance={now:()=>0};e.inRect=()=>true;e.tokenAt=()=>({dataset:{token:target.uid}});e.cleanupDrag=()=>{};e.renderSelection=()=>{};e.playSound=()=>{};e.$=()=>({getBoundingClientRect:()=>({})});
 e.board.getBoundingClientRect=()=>({left:0,top:0});e.drag={pointer:1,active:true,source:'shelf',id:'b',offsetX:33,offsetY:38};
 e.mix=(a,b)=>{if(mixed){const first=e.state.bench.find(t=>t.uid===a);e.state.bench=e.state.bench.filter(t=>![a,b].includes(t.uid));e.addToken('c',{u:first.u,v:first.v});}return mixed;};
 runInNewContext(game.slice(game.indexOf('function pointerUp('),game.indexOf('/* Modal pages')),e);
 e.pointerUp({pointerId:1,clientX:50,clientY:60});
}
test('failed explicit shelf drop restores a physically full table and its undo stack',()=>{
 const e=engine();for(let i=0;i<8;i++)e.addToken('a');const before=snapshot(e);drop(e,e.state.bench[0]);assert.equal(snapshot(e),before);assert.equal(e.undoStack.length,0);separated(e);
});
test('failed explicit shelf drop relocates its new ingredient when there is room',()=>{
 const e=engine();e.addToken('a');drop(e,e.state.bench[0]);assert.equal(e.state.bench.length,2);assert.equal(e.undoStack.length,1);separated(e);
});
test('successful explicit shelf drop on a full table keeps the result accessible',()=>{
 const e=engine();for(let i=0;i<8;i++)e.addToken('a');drop(e,e.state.bench[0],true);assert.equal(e.state.bench.length,8);assert.ok(e.state.bench.some(t=>t.id==='c'));assert.equal(e.undoStack.length,1);separated(e);
});
test('real mixing keeps discovery and one undo snapshot while replacing two packed ingredients',()=>{
 const e=engine();for(let i=0;i<8;i++)e.addToken('a');const before=snapshot(e),first=e.state.bench[0],second=e.state.bench[1];
 Object.assign(e,{HISTORY_LIMIT:160,R:new Map([['a+a',{result:'c'}]]),pairKey:(a,b)=>[a,b].sort().join('+'),tried:new Set(),knownRecipes:new Set(),currentChapter:()=>1,window:{},newThisSession:new Set(),hint:null,updateAchievements:()=>[],renderAll(){},burst(){},playSound(){},E:{size:3},name:id=>id,DATA:{chapters:[1]},chapterComplete:()=>false});
 Object.assign(e.state,{attempts:0,history:[]});runInNewContext(game.slice(game.indexOf('function mix('),game.indexOf('function arrangeBench(')),e);
 assert.equal(e.mix(first.uid,second.uid),true);assert.equal(e.state.bench.length,7);assert.ok(e.found.has('c'));assert.equal(e.state.attempts,1);separated(e);
 assert.equal(e.undoStack.length,1);e.state.bench=e.undoStack.pop();assert.equal(snapshot(e),before);assert.ok(e.found.has('c'));
});


function fullUndo(e){e.undoStack=Array.from({length:30},(_,i)=>[{uid:`old-${i}`,id:'a',u:0,v:0}]);return JSON.stringify(e.undoStack);}
test('failed placement, pair and arrangement preserve all 30 undo entries including oldest',()=>{
 for(const action of ['collection','pair','arrange']){
  const e=engine();for(let i=0;i<(action==='pair'?7:8);i++)e.addToken('a');
  if(action==='arrange')e.state.bench.push({uid:'legacy',id:'a',u:.5,v:.5});
  const before=snapshot(e),history=fullUndo(e);
  if(action==='collection')e.chooseFromCollection('b');else if(action==='pair')e.loadPair('a+b');else e.arrangeBench();
  assert.equal(snapshot(e),before,action);assert.equal(JSON.stringify(e.undoStack),history,action);
 }
});
test('failed explicit shelf drop respects MAX_TOKENS even when the desktop has space',()=>{
 const e=engine(1200,900);for(let i=0;i<36;i++)assert.ok(e.addToken('a'));const before=snapshot(e),history=fullUndo(e);
 drop(e,e.state.bench[0]);assert.equal(e.state.bench.length,36);assert.equal(snapshot(e),before);assert.equal(JSON.stringify(e.undoStack),history);separated(e);
});
test('selected ingredient and collection still mix on a packed phone table',()=>{
 const e=engine();for(let i=0;i<8;i++)e.addToken('a');e.selected=e.state.bench[0].uid;
 let calls=0;e.mix=(a,b)=>{calls++;const source=e.state.bench.find(t=>t.uid===a);e.state.bench=e.state.bench.filter(t=>![a,b].includes(t.uid));e.addToken('c',{u:source.u,v:source.v});return true;};
 e.chooseFromCollection('b');assert.equal(calls,1);assert.equal(e.state.bench.length,8);assert.ok(e.state.bench.some(t=>t.id==='c'));separated(e);
});
test('unsuccessful collection mixing at capacity restores the board and full undo history',()=>{
 const e=engine();for(let i=0;i<8;i++)e.addToken('a');e.selected=e.state.bench[0].uid;const before=snapshot(e),history=fullUndo(e);e.mix=()=>false;
 e.chooseFromCollection('b');assert.equal(snapshot(e),before);assert.equal(JSON.stringify(e.undoStack),history);separated(e);
});

function detailAdd(e,id){
 let click;e.document={};e.listen=(target,type,fn)=>{assert.equal(type,'click');click=fn;};
 runInNewContext(game.slice(game.indexOf("listen(document,'click'"),game.indexOf('/* Полоса категорий')),e);
 click({target:{closest:selector=>selector.startsWith('[data-action]')?{dataset:{addTable:id}}:null}});
}
test('detail «На стол» preserves the entire capped undo history on a full phone or MAX_TOKENS board',()=>{
 for(const [w,h,n] of [[350,220,8],[1200,900,36]]){
  const e=engine(w,h);for(let i=0;i<n;i++)assert.ok(e.addToken('a'));const before=snapshot(e),history=fullUndo(e);e.selected=e.state.bench[0].uid;const selected=e.selected;
  detailAdd(e,'b');assert.equal(snapshot(e),before);assert.equal(JSON.stringify(e.undoStack),history);assert.equal(e.selected,selected);separated(e);
 }
});
test('successful detail «На стол» makes one undo entry containing the previous board',()=>{
 const e=engine();e.addToken('a');const before=snapshot(e);detailAdd(e,'b');assert.equal(e.state.bench.length,2);assert.equal(e.undoStack.length,1);assert.equal(JSON.stringify(e.undoStack[0]),before);assert.equal(e.selected,e.state.bench[1].uid);separated(e);
});
