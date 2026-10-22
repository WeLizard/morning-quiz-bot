'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const root=path.resolve(__dirname,'../..');
const read=file=>fs.readFileSync(path.join(root,file),'utf8');
const source=read('qw_farm/static/oleg-game.js').replace(/export /g,'');
const context={Number,Array,Object,Math,Boolean,String,Set,Map,Promise,setTimeout,clearTimeout};
vm.createContext(context);
vm.runInContext(`${source}\nglobalThis.api={olegPlural,olegViewState,olegAnswerOutcome,olegResultText,olegMood,olegSceneSvg,mountOlegGame};`,context);
const {olegPlural,olegViewState,olegAnswerOutcome,olegResultText,olegMood,olegSceneSvg,mountOlegGame}=context.api;
const RUN='5b3f8f8e-4c1a-4b52-9d6e-0f0a6c1d2e3f';
const game=overrides=>({active:null,rewarded_today:false,next_reward:{coins:12,xp:4},rounds:[3,4,5],last_result:null,...overrides});
const active=(round,sequence)=>({run_id:RUN,round,rounds:3,notes:sequence.length,sequence,started_at:1});

async function waitFor(predicate,timeout=3000){
 const start=Date.now();
 while(!predicate()){
  if(Date.now()-start>timeout)throw new Error('condition was not met in time');
  await new Promise(resolve=>setTimeout(resolve,5));
 }
}
class FakeClassList{constructor(){this.values=new Set();}add(...n){n.forEach(x=>this.values.add(x));}remove(...n){n.forEach(x=>this.values.delete(x));}contains(n){return this.values.has(n);}}
class FakeNode{
 constructor(){this.classList=new FakeClassList();this.dataset={};this.attrs={};this.listeners={};this.disabled=false;this.hidden=false;this.textContent='';this.style={};this.firstElementChild={style:{}};}
 addEventListener(name,cb){(this.listeners[name]??=[]).push(cb);}
 emit(name,event={}){for(const cb of this.listeners[name]||[])cb({preventDefault(){},stopPropagation(){},...event});}
 setAttribute(n,v){this.attrs[n]=String(v);}getAttribute(n){return this.attrs[n]??null;}removeAttribute(n){delete this.attrs[n];}
 replaceChildren(){}focus(){}
}
function fakeHost(){
 const selectors=['.oleg-speech','[data-role="status"]','[data-role="action"]','[data-role="round"]','[data-role="hint"]','[data-role="reward"]','.oleg-progress','.oleg-scene','.oleg-sound','.oleg-back'];
 const nodes=Object.fromEntries(selectors.map(s=>[s,new FakeNode()]));
 const bells=[0,1,2,3].map(i=>{const b=new FakeNode();b.dataset.note=String(i);return b;});
 const sceneBells=[0,1,2,3].map(()=>new FakeNode());
 const host=new FakeNode();host.querySelector=s=>nodes[s]||null;
 host.querySelectorAll=s=>s==='.oleg-bell'?bells:s==='[data-scene-bell]'?sceneBells:[];
 return {host,nodes,bells,sceneBells};
}
context.matchMedia=()=>({matches:true});   // reduced motion: the melody plays in ~0.4 s

test('plural forms of "нота" follow Russian rules',()=>{
 assert.deepEqual([1,2,3,4,5,11,21,22,25].map(olegPlural),['нота','ноты','ноты','ноты','нот','нот','нота','ноты','нот']);
});

test('view state trusts only a well-formed server projection',()=>{
 assert.equal(olegViewState(null).active,null);
 assert.deepEqual([...olegViewState(null).rounds],[3,4,5]);
 const v=olegViewState(game({active:active(1,[0,3,2,1]),rewarded_today:true}));
 assert.equal(v.active.round,1);assert.equal(v.active.notes,4);assert.equal(v.rewardedToday,true);assert.equal(v.coins,12);
 assert.equal(olegViewState(game({active:{...active(0,[0,1,2]),sequence:[0,7,1]}})).active,null);
});

test('answer outcome is read from the returned projection, not from command success',()=>{
 assert.equal(olegAnswerOutcome(game({active:active(1,[1,1,1,1])}),RUN,0),'next');
 assert.equal(olegAnswerOutcome(game({active:active(0,[1,1,1])}),RUN,0),'mismatch');
 assert.equal(olegAnswerOutcome(game({last_result:{run_id:RUN,at:2,rewarded:true,coins:12,xp:4}}),RUN,2),'finished');
 assert.equal(olegAnswerOutcome(game({active:{...active(0,[1,1,1]),run_id:'other'}}),RUN,0),'lost');
});

test('result text shows the reward only when the server paid it',()=>{
 assert.match(olegResultText({rewarded:true,coins:12,xp:5}),/\+12 монет и \+5 опыта/);
 assert.match(olegResultText({rewarded:false,coins:0,xp:0}),/уже получена/);
});

test('mood follows the phase of the game',()=>{
 assert.equal(olegMood('show',false),'sing');assert.equal(olegMood('input',false),'listen');
 assert.equal(olegMood('retry',false),'oops');assert.equal(olegMood('next',false),'happy');
 assert.equal(olegMood('idle',true),'happy');assert.equal(olegMood('idle',false),'');
});

test('full run: start, wrong note retries locally, three rounds go to the server, Oleg reacts',async()=>{
 const sequences=[[0,1,2],[3,2,1,0],[1,1,2,2,3]];
 let state=game(),sent=[];
 const command=async(kind,data)=>{
  sent.push([kind,JSON.parse(JSON.stringify(data))]);
  if(kind==='oleg_start')state=game({active:active(0,sequences[0])});
  else if(data.round<2)state=game({active:active(data.round+1,sequences[data.round+1])});
  else state=game({rewarded_today:true,last_result:{run_id:RUN,at:3,rewarded:true,coins:12,xp:4}});
  return true;
 };
 const {host,nodes,bells,sceneBells}=fakeHost();
 const view=mountOlegGame(host,{getState:()=>state,command,onBack(){}});
 const action=nodes['[data-role="action"]'],scene=nodes['.oleg-scene'];
 action.emit('click');
 await waitFor(()=>!bells[0].disabled);
 assert.deepEqual(sent.map(x=>x[0]),['oleg_start']);
 assert.equal(scene.dataset.mood,'listen');
 await waitFor(()=>sceneBells.every(b=>!b.classList.contains('oleg-lit')));
 bells[2].emit('click');                                   // wrong first note: no server call
 assert.equal(sent.length,1);assert.equal(action.textContent,'Послушать ещё раз');
 assert.equal(scene.dataset.mood,'oops');
 for(let r=0;r<3;r++){
  action.emit('click');
  await waitFor(()=>!bells[0].disabled);
  const first=sequences[r][0];bells[first].emit('click');
  assert.ok(sceneBells[first].classList.contains('oleg-lit'),'the stage bell rings with its button');
  for(const n of sequences[r].slice(1))bells[n].emit('click');
  await waitFor(()=>sent.length===r+2);
  assert.deepEqual(sent[r+1],['oleg_answer',{run_id:RUN,round:r,notes:sequences[r]}]);
  await waitFor(()=>action.textContent===(r<2?'Следующая мелодия':'Сыграть ещё раз'));
  assert.equal(scene.dataset.mood,'happy');
 }
 assert.match(nodes['[data-role="status"]'].textContent,/\+12 монет/);
 view.destroy();
});

test('a saved run resumes without a new start command',async()=>{
 let sent=[];const state=game({active:active(1,[2,2,0,1])});
 const {host,nodes,bells}=fakeHost();
 mountOlegGame(host,{getState:()=>state,command:async kind=>{sent.push(kind);return true;},onBack(){}});
 assert.match(nodes['[data-role="status"]'].textContent,/мелодия 2 из 3/);
 nodes['[data-role="action"]'].emit('click');
 await waitFor(()=>!bells[0].disabled);
 assert.deepEqual(sent,[]);
});

test('stage art: four bells keyed to the buttons, one whole rooster, vector only',()=>{
 const svg=olegSceneSvg();
 assert.equal((svg.match(/data-scene-bell="/g)||[]).length,4);
 for(const cls of ['os-oleg','os-head','os-wing','os-vest','os-house','os-oak','os-stand'])assert.ok(svg.includes(`class="${cls}"`),cls);
 assert.ok(!/<image|data:image|href="http/.test(svg),'no raster or remote images');
 assert.equal((svg.match(/<svg/g)||[]).length,1);
 const css=read('qw_farm/static/oleg-game.css');
 for(const mood of ['sing','happy','oops','listen'])assert.ok(css.includes(`data-mood=${mood}`),mood);
 assert.ok(css.includes(':root[data-farm-theme=night] #oleg-game-view .os-sky-top'),'night palette');
});

test('assets are wired: served, linked and mounted from the resident card',()=>{
 const html=read('qw_farm/static/index.html'),app=read('qw_farm/static/app.js'),api=read('qw_farm/api.py'),css=read('qw_farm/static/oleg-game.css');
 assert.ok(html.includes('/app/farm/assets/oleg-game.css'));
 assert.ok(html.includes('id="oleg-game-view"'));
 for(const asset of ['oleg-game.js','oleg-game.css'])assert.ok(api.includes(`'${asset}'`),asset);
 assert.match(app,/import \{mountOlegGame\} from '\.\/oleg-game\.js'/);
 assert.match(app,/if\(npc==='Петух Олег'\)appendOlegAction\(c\)/);
 assert.match(css,/body\.oleg-game-open \.workspace>#rail/);
 assert.ok(!/window\.addEventListener\('keydown'/.test(read('qw_farm/static/oleg-game.js')),'keys are handled on the game root only');
});
