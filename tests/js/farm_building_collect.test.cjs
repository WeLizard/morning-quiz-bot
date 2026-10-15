const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../../qw_farm/static/app.js'),'utf8');
const code=source.slice(source.indexOf('function renderObject(p)'),source.indexOf('async function visit(id)'));
class Node{constructor(text){this.textContent=text;this.children=[];}append(...nodes){this.children.push(...nodes);}}
function render(count,{guest=false,type='bakery'}={}){
 const o={id:'selected-workshop',type,jobs:Array.from({length:count+1},(_,i)=>({id:'j'+i,recipe:'bread',starts_at:0,ready_at:i<count?99:101})),level:1};
 const p=new Node(),calls=[];
 const ctx={S:{selected:o.id,farm:{objects:[o]},me:{level:10,coins:100},catalog:{animals:{},recipes:{bread:{id:'bread',building:'bakery',name:'Хлеб',inputs:{},outputs:{bread:1},seconds:20,level:1}},buildings:{}}},
  own:()=>!guest,heading:()=>{},objName:()=>type,buildingPurpose:()=>[],lvlOf:()=>1,slotsOf:()=>5,
  now:()=>100,note:()=>{},upgradeCard:()=>{},renderVisitActions:()=>{},enough:()=>true,speedOf:()=>1,
  el:(tag,text)=>new Node(text),card:()=>new Node(),goods:()=>new Node(),timer:()=>new Node(),itemName:x=>x,duration:x=>x,
  button:(text,fn)=>{const n=new Node(text);n.onclick=fn;return n;},command:(...args)=>calls.push(args)};
 vm.createContext(ctx);vm.runInContext(code,ctx);ctx.renderObject(p);
 return {p,calls,bulk:p.children.find(n=>n.textContent?.startsWith('Забрать всё готовое'))};
}
test('bulk button shows only two or more finished batches and targets opened building',()=>{
 for(const count of [0,1])assert.equal(render(count).bulk,undefined);
 const h=render(2);assert.equal(h.bulk.textContent,'Забрать всё готовое · 2');h.bulk.onclick();
 assert.equal(h.calls[0][0],'collect_building');assert.equal(h.calls[0][1].object,'selected-workshop');
 assert.equal(h.p.children.filter(n=>n.children[0]?.textContent==='Забрать').length,2);
});
test('guest and non-production building do not get bulk collection',()=>{
 assert.equal(render(3,{guest:true}).bulk,undefined);
 assert.equal(render(3,{type:'barn'}).bulk,undefined);
});
