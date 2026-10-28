const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const load=()=>import(pathToFileURL(path.join(__dirname,'../../qw_farm/static/horseman.js')).href);

class Node{
 constructor(tag,text,cls){this.tag=tag;this.text=text||'';this.cls=cls||'';this.children=[];this.dataset={};this.classList={add:()=>{}};}
 append(...nodes){this.children.push(...nodes);}
}
function walk(node){return [node,...node.children.flatMap(walk)];}
function harness(view){
 let current=view,pending=false,dialog=null,closed=0,resolveCommand;
 const calls=[];
 const h={getHorseman:()=>current,now:()=>100, pending:()=>pending,
  el:(tag,text,cls)=>new Node(tag,text,cls),card:(title,subtitle)=>{const n=new Node('section',title,'card');n.subtitle=subtitle;return n;},
  button:(text,onClick,cls,disabled)=>{const n=new Node('button',text,cls);n.onclick=onClick;n.disabled=!!disabled;return n;},
  itemName:id=>({pumpkin_candy:'Тыквенная конфета',wheat:'Пшеница'}[id]||id),
  modal:(title,body,actions)=>{dialog=new Node('dialog',title);dialog.append(body,...actions);},
  closeDialog:()=>{closed++;dialog=null;},
  command:(kind,data)=>{calls.push([kind,data]);pending=true;return new Promise(resolve=>{resolveCommand=ok=>{pending=false;resolve(ok);};});}};
 return {h,calls,get dialog(){return dialog;},get closed(){return closed;},setView:v=>{current=v;},resolve:ok=>resolveCommand(ok)};
}
const gift={active:true,can_claim:true,claimed_today:false,day:100,next_change_at:200,next_gift_at:null,gift:{items:{pumpkin_candy:3,wheat:4}}};

test('display uses server flags and expires old snapshots without locally unlocking a day',async()=>{
 const {horsemanDisplay}=await load();
 assert.equal(horsemanDisplay(null,100),null);
 assert.equal(horsemanDisplay(gift,100).canClaim,true);
 assert.equal(horsemanDisplay(gift,200).canClaim,false);
 assert.equal(horsemanDisplay({...gift,active:false,can_claim:false,next_gift_at:300},100).canClaim,false);
 assert.equal(horsemanDisplay({...gift,claimed_today:true,can_claim:false},100).message,'Сегодня подарок уже получен.');
 assert.equal(horsemanDisplay(gift,100,true).canClaim,false);
});

test('card opens real gift dialog and sends only a server command once while pending',async()=>{
 const M=await load(),t=harness(gift),panel=new Node('div');M.renderHorsemanCard(panel,t.h);
 assert.equal(walk(panel).find(n=>n.text==='Поговорить с Джеком').disabled,false);
 walk(panel).find(n=>n.tag==='button').onclick();
 assert.match(walk(t.dialog).map(n=>n.text).join(' '),/Тыквенная конфета ×3/);
 const claim=walk(t.dialog).find(n=>n.text==='Получить подарок');
 const done=claim.onclick();assert.deepEqual(t.calls,[['claim_horseman_gift',{}]]);
 assert.equal(claim.disabled,true);
 await claim.onclick();assert.equal(t.calls.length,1);
 t.setView({...gift,can_claim:false,claimed_today:true,next_gift_at:300});t.resolve(true);await done;
 assert.equal(t.closed,1);
 assert.match(walk(t.dialog).map(n=>n.text).join(' '),/Сегодня подарок уже получен/);
 assert.equal(walk(t.dialog).some(n=>n.text==='Получить подарок'),false);
});

test('inactive hours and stale data show the dialog but never send a claim',async()=>{
 const M=await load(),inactive={...gift,active:false,can_claim:false,next_gift_at:300},t=harness(inactive);
 M.openHorsemanDialog(t.h);
 assert.equal(walk(t.dialog).find(n=>n.text==='Получить подарок').disabled,true);
 t.setView({...gift,next_change_at:100});M.openHorsemanDialog(t.h);
 assert.equal(walk(t.dialog).find(n=>n.text==='Получить подарок').disabled,true);
 assert.deepEqual(t.calls,[]);
});

test('confirmed POST closes the same snapshot when its follow-up refresh fails',async()=>{
 const M=await load(),view={...gift,gift:{items:{pumpkin_candy:3}}},t=harness(view);
 M.openHorsemanDialog(t.h);
 const action=walk(t.dialog).find(n=>n.text==='Получить подарок').onclick();
 t.resolve(true);await action;
 assert.equal(view.claimed_today,true);
 assert.equal(view.can_claim,false);
 assert.match(walk(t.dialog).map(n=>n.text).join(' '),/Подарок получен/);
 assert.equal(walk(t.dialog).some(n=>n.text==='Получить подарок'),false);
 M.openHorsemanDialog(t.h);
 assert.equal(t.calls.length,1,'old view cannot be claimed twice');
});
