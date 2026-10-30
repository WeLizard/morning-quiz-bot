// Сорока-коробейница v2, клиент: rarity plates, restock line, arrival toast keyed by the base visit, opaque visit_id.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');

const ROOT=path.join(__dirname,'../..');
const read=f=>fs.readFileSync(path.join(ROOT,f),'utf8');
const load=()=>import(pathToFileURL(path.join(ROOT,'qw_farm/static/merchant.js')).href);

class Node{
 constructor(tag,text,cls){this.tag=tag;this.textContent=text??'';this.cls=cls||'';this.children=[];this.dataset={};this.attrs={};this.classList={add:c=>{this.cls+=' '+c;}};}
 get text(){return this.textContent;}
 append(...n){this.children.push(...n);}
 setAttribute(k,v){this.attrs[k]=v;}
}
const walk=(n,out=[])=>{out.push(n);for(const c of n.children||[])walk(c,out);return out;};
function helpers(over={}){
 const calls=[];
 return {calls,el:(t,x,c)=>new Node(t,x,c),button:(t,fn,c,d)=>{const b=new Node('button',t,c);b.onclick=fn;b.disabled=!!d;return b;},
  card:(t,s)=>{const c=new Node('section',t,'card');c.sub=s;return c;},icon:id=>new Node('svg',id,'icon'),note:(t,p)=>p.append(new Node('p',t,'note')),
  fmt:n=>String(n),itemName:id=>id,now:()=>1000,busy:()=>false,coins:()=>100000,rerender(){},
  command:(k,d)=>{calls.push([k,d]);return Promise.resolve(true);},catalog:{merchant:{curios:{}}},...over};
}
const slot=(over={})=>({slot:0,id:'seed_fire_pepper',kind:'exotic_seed',name:'Огненный перец',qty:3,price:280,limit:2,min_level:9,note:'Пакет.',wired:true,series:null,left:2,status:'ok',rarity:'common',...over});
const view=(over={})=>({active:true,visit_id:'v20000:h1',base_visit_id:'v20000',kind:'regular',opens_at:900,closes_at:900+25920,next_at:900000,next_restock_at:1000+3*3600+20*60,teaser:null,
 slots:[slot(),slot({slot:1,id:'dye_indigo',kind:'dye',name:'Индиго',rarity:'common'}),slot({slot:2,id:'scroll_x',kind:'scroll',name:'Свиток',rarity:'uncommon'}),
        slot({slot:3,id:'curio_a',kind:'curio',name:'Диковинка',rarity:'rare'}),slot({slot:4,id:'curio_b',kind:'curio',name:'Старая диковинка',rarity:'lot_day'})],
 wants:null,bought:{},sold_value:0,cap:260,curios:[],scrolls:[],fair:null,...over});
const plates=p=>walk(p).filter(n=>/mag-rarity/.test(n.cls)).map(n=>[n.dataset.rarity,n.text]);

test('rarity plates: none for common, three labels for the rest',async()=>{
 const M=await load(),p=new Node('div');
 M.setTab('shelf');M.renderShop(p,view(),helpers());
 assert.deepEqual(plates(p),[['uncommon','Необычное'],['rare','Редкое'],['lot_day','Лот дня']]);
 assert.equal(M.rarityLabel('common'),'');assert.equal(M.rarityLabel(undefined),'');
 const old=new Node('div');M.renderShop(old,view({slots:[slot({rarity:undefined})]}),helpers());
 assert.deepEqual(plates(old),[],'an old payload without rarity shows no plate');
});

test('restock line: countdown while ahead, then «подвезла», nothing when the visit has no restock',async()=>{
 const M=await load();M.resetRestockMemory();
 const line=(v,now=1000)=>{const p=new Node('div');M.renderShop(p,v,helpers({now:()=>now}));return walk(p).find(n=>/mag-restock/.test(n.cls));};
 const ahead=line(view());
 assert.equal(ahead.text,'Подвоз через 3 ч 20 мин');assert.equal(ahead.dataset.merchantRestock,String(1000+3*3600+20*60));
 assert.equal(M.restockText(1000+30,1000),'Подвоз совсем скоро');
 // the local clock passed the restock before the server answered: no countdown, no negative time
 const passed=line(view(),1000+4*3600);
 assert.equal(passed.text,'Сорока подвезла товар');assert.equal(passed.dataset.merchantRestock,undefined);
 // the server dropped next_restock_at after the restock: the line stays for the same visit
 const after=line(view({visit_id:'v20000:h2',next_restock_at:null}),1000+4*3600);
 assert.equal(after.text,'Сорока подвезла товар');
 // another visit with no restock (old visit, or one the client never saw ahead) has no line
 M.resetRestockMemory();
 assert.equal(line(view({visit_id:'v20001',base_visit_id:'v20001',next_restock_at:null})),undefined);
 assert.equal(line(view({active:false,next_restock_at:null})),undefined);
});

test('the minute tick rewrites only the text of the restock lines and counts them',async()=>{
 const M=await load();
 const a=new Node('p','Подвоз через 3 ч 20 мин','mag-restock'),b=new Node('p','x','mag-restock');
 a.dataset.merchantRestock='4000';b.dataset.merchantRestock='1500';b.isConnected=false;
 const root={querySelectorAll:sel=>{assert.equal(sel,'[data-merchant-restock]');return [a,b];}};
 assert.equal(M.tickRestock(root,4000-60*45),1,'a detached line is not counted');
 assert.equal(a.text,'Подвоз через 45 мин');assert.equal(b.text,'x');
 assert.equal(M.tickRestock(root,4000),1);assert.equal(a.text,'Сорока подвезла товар');
 assert.equal(M.tickRestock({querySelectorAll:()=>[]},0),0,'no lines: the timer can stop');
});

test('visit_id goes to the purchase exactly as the server sent it; stale_visit has its own text',async()=>{
 const M=await load(),h=helpers(),p=new Node('div');
 M.setTab('shelf');M.renderShop(p,view({visit_id:'v20000:h2',next_restock_at:null}),h);
 walk(p).filter(n=>n.tag==='button'&&/^Купить/.test(n.text))[0].onclick();
 assert.deepEqual(h.calls[0],['merchant_buy',{visit_id:'v20000:h2',slot:0,qty:1}]);
 const app=read('qw_farm/static/app.js');
 assert.match(app,/e\.code==='stale_visit'\?MERCH\.STALE_TEXT:e\.message/);
 assert.match(M.STALE_TEXT,/свежий/);
});

test('the arrival toast is keyed by the base visit: a restock does not repeat it',async()=>{
 const M=await load();
 assert.equal(M.arrivalKey(view()),'v20000');assert.equal(M.arrivalKey(view({visit_id:'v20000:h2'})),'v20000');
 assert.equal(M.arrivalKey(view({base_visit_id:undefined,visit_id:'v20000'})),'v20000');
 assert.equal(M.arrivalKey(null),'');
 const app=read('qw_farm/static/app.js');
 const fn=app.match(/function syncMerchantFlag\(\)\{[\s\S]*?\n\}/)[0];
 const store={},toasts=[];
 let current=view();
 const make=new Function('MERCH','own','merchantView','$','merchantLabel','toast','localStorage',`let merchantToastKey='';${fn};return syncMerchantFlag;`);
 const sync=make(M,()=>true,()=>current,()=>null,()=>'',t=>toasts.push(t),{getItem:k=>store[k]??null,setItem:(k,v)=>{store[k]=v;}});
 sync();sync();
 current=view({visit_id:'v20000:h2',next_restock_at:null});sync();
 assert.equal(toasts.length,1,'h1 -> h2 of the same visit: one toast');
 assert.equal(store['qw-farm.merchant-seen'],'v20000');
 current=view({visit_id:'v20002:h1',base_visit_id:'v20002'});sync();
 assert.equal(toasts.length,2,'the next visit announces again');
});

test('style: shell tokens only, contrast rules sit in the contrast block at the end',()=>{
 const css=read('qw_farm/static/style.css');
 const plain=css.split('\n').filter(l=>/^\.mag-(rarity|restock)/.test(l));
 assert.equal(plain.length,4);
 assert.ok(plain.every(l=>!/#[0-9a-f]{3,8}\b/i.test(l)),'no arbitrary colours');
 assert.ok(plain.every(l=>/--qw-/.test(l)));
 const start=css.indexOf('/* ==== «Контрастный режим»');
 const contrast=css.split('\n').filter(l=>/data-qw-contrast="1"\] \.mag-(rarity|restock)/.test(l));
 assert.ok(contrast.length>=3&&start>0);
 assert.ok(css.indexOf(contrast[0])>start,'contrast rules come after the contrast block begins');
 assert.ok(css.indexOf(plain[0])<start,'regular rules stay above the contrast block');
});
