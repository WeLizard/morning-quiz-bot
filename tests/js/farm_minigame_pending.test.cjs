const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
const start=source.indexOf('async function sendPending(){');
const end=source.indexOf('\n// After a real 429',start);
const sendPendingSource=source.slice(start,end);
const renderStart=source.indexOf('function renderMinigame(game,parent){');
const renderEnd=source.indexOf('\nfunction projectStageSummary',renderStart);
const renderSource=source.slice(renderStart,renderEnd);

class Node{
 constructor(tag,text=''){this.tagName=tag;this.textContent=text;this.children=[];this.listeners={};this.classList={add(){}};}
 append(...nodes){this.children.push(...nodes);}
 setAttribute(){}
 addEventListener(name,fn){this.listeners[name]=fn;}
}

test('successful pending minigame command rerenders house and barn after busy clears',async()=>{
 const panels={},refreshes=[];
 const S={busy:false,me:{id:'player',minigames:{
  house:{active:{attempt_id:'house',expires_at:100,question:'?',options:['да','нет']}},
  barn:{active:{attempt_id:'barn',expires_at:100,sacks:[{id:'one',label:'Первый'},{id:'two',label:'Второй'}],shelves:['a','b']}},
 }},farm:{is_owner:true},pending:{actor:'player',command_id:'command'}};
 const ctx={
  S,API:'/api',pendingRetryTimer:null,rateRecoveryAttempt:0,
  clearTimeout(){},connection(){},document:{body:{classList:{add(){},remove(){}}}},
  request:async()=>({neighbor_reward_paid:true}),rememberMachineCommand(){},savePending(){},
  refresh:async options=>{refreshes.push(options);},updateRepeat(){},
  own:()=>true,now:()=>0,timer:()=>new Node('span'),renderMinigameResult(){},minigameShelves:{a:'Полка А',b:'Полка Б'},
  card:(title)=>new Node('section',title),el:(tag,text,cls)=>{const n=new Node(tag,text);n.className=cls;return n;},
  button:(text,fn,cls,disabled)=>{const b=new Node('button',text);b.onclick=fn;b.disabled=!!disabled;return b;},
  renderPanel(){
   assert.equal(S.busy,false);
   for(const game of Object.keys(S.me.minigames)){const parent=new Node('div');ctx.renderMinigame(game,parent);panels[game]=parent.children[0];}
  },
 };
 vm.runInNewContext(renderSource+'\n'+sendPendingSource+'\nthis.sendPending=sendPending;this.renderMinigame=renderMinigame;',ctx);

 assert.equal(await ctx.sendPending(),true);
 assert.equal(refreshes.length,1);
 assert.equal(refreshes[0].render,false);
 const houseChoices=panels.house.children.find(n=>n.className==='minigame-choices');
 assert.equal(houseChoices.children.length,2);
 assert.equal(houseChoices.children[0].disabled,false);
 const sackRows=panels.barn.children.find(n=>n.className==='minigame-sacks').children;
 const submit=panels.barn.children.find(n=>n.tagName==='button'&&n.textContent==='Сдать раскладку');
 for(const row of sackRows){const select=row.children.find(n=>n.tagName==='select');select.value=select.children[1].value;select.listeners.change();}
 assert.equal(submit.disabled,false);
});
