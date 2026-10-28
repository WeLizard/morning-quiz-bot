'use strict';
// Behaviour tests for the live field overlay (field_overlay.js) on a minimal fake DOM:
// held-direction hits, transfer vs. max_path, the server-clock deadline, broken-machine quality.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const dir=process.env.QW_STATIC_DIR||path.join(__dirname,'../../qw_farm/static');   // override only for mutation checks
const rawGame=fs.readFileSync(path.join(dir,'tractor_game.js'),'utf8');
const gameNames=[...rawGame.matchAll(/export (?:const|function|class) (\w+)/g)].map(m=>m[1]);
const bare=src=>src.replace(/export (const|function|class) /g,'$1 ');
// the two ES modules get separate scopes (they declare clashing helper names); the import line becomes a destructuring of the first one
const overlay=fs.readFileSync(path.join(dir,'field_overlay.js'),'utf8')
 .replace(/^import \{([\s\S]*?)\} from '[^']+';\r?\n/m,'const {$1} = __game;\n');
const SOURCE=`const __game=(()=>{\n${bare(rawGame)}\nreturn {${gameNames.join(',')}};\n})();\n${bare(overlay)}`;

/* ---------------------------------------------------------------- fake DOM */
const anyFn=()=>{const f=new Proxy(function(){},{get:(t,k)=>k===Symbol.toPrimitive?()=>0:anyFn(),apply:()=>anyFn(),set:()=>true});return f;};
const ctx2d=new Proxy({},{get:(t,k)=>k in t?t[k]:(k==='measureText'?()=>({width:10}):anyFn()),set:(t,k,v)=>{t[k]=v;return true;}});
class ClassList{
 constructor(){this.v=new Set();}
 add(...a){a.forEach(x=>this.v.add(x));}
 remove(...a){a.forEach(x=>this.v.delete(x));}
 toggle(c,on){if(on===undefined)on=!this.v.has(c);on?this.v.add(c):this.v.delete(c);return on;}
 contains(c){return this.v.has(c);}
}
class El{
 constructor(tag,doc){
  this.tagName=String(tag).toUpperCase();this.doc=doc;this.children=[];this.parent=null;this.attrs={};this.dataset={};
  this.classList=new ClassList();this.style={};this.listeners={};this.hidden=false;this.disabled=false;this.textContent='';
  this.width=0;this.height=0;this.offsetWidth=10;this.offsetParent={};this._html='';this.title='';this.inert=false;
 }
 set className(v){this.classList.v=new Set(String(v).split(/\s+/).filter(Boolean));}
 get className(){return [...this.classList.v].join(' ');}
 set innerHTML(html){
  this._html=html;this.children=[];if(!html)return;
  const stack=[this];
  for(const m of html.matchAll(/<(\/?)([a-zA-Z0-9]+)([^>]*)>/g)){
   if(m[1]){if(stack.length>1)stack.pop();continue;}
   const e=new El(m[2],this.doc);
   for(const a of m[3].matchAll(/([\w-]+)="([^"]*)"/g)){
    if(a[1]==='class')e.className=a[2];
    else if(a[1].startsWith('data-'))e.dataset[a[1].slice(5).replace(/-(\w)/g,(_,c)=>c.toUpperCase())]=a[2];
    else e.attrs[a[1]]=a[2];
   }
   if(/\shidden(\s|$|\/)/.test(m[3]))e.hidden=true;
   if(e.attrs.id)e.id=e.attrs.id;
   const top=stack[stack.length-1];e.parent=top;top.children.push(e);
   if(!/\/\s*$/.test(m[3])&&!/^(br|img|input)$/i.test(m[2]))stack.push(e);
  }
 }
 get innerHTML(){return this._html;}
 append(...n){for(const x of n){if(typeof x==='string')continue;x.parent=this;this.children.push(x);}}
 appendChild(n){this.append(n);return n;}
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(c=>c!==this);this.parent=null;}
 setAttribute(k,v){this.attrs[k]=v;if(k==='id')this.id=v;}
 getAttribute(k){return this.attrs[k];}
 addEventListener(t,f){(this.listeners[t]=this.listeners[t]||[]).push(f);}
 removeEventListener(t,f){this.listeners[t]=(this.listeners[t]||[]).filter(x=>x!==f);}
 fire(t,e={}){const ev={preventDefault(){},stopPropagation(){},target:this,detail:0,pointerId:1,...e};for(const f of this.listeners[t]||[])f(ev);if(t==='click'&&this.onclick)this.onclick(ev);}
 focus(){this.doc.activeElement=this;}
 blur(){}
 setPointerCapture(){}
 getBoundingClientRect(){return {left:0,top:0,width:400,height:600,right:400,bottom:600};}
 getContext(){return ctx2d;}
 all(){const out=[];const walk=n=>{for(const c of n.children){out.push(c);walk(c);}};walk(this);return out;}
 matches(sel){
  const m=/^([a-z0-9]*)(?:#([\w-]+))?((?:\.[\w-]+)*)(?:\[([\w-]+)\])?$/i.exec(sel);
  if(!m)return false;
  if(m[1]&&this.tagName!==m[1].toUpperCase())return false;
  if(m[2]&&this.id!==m[2])return false;
  for(const c of (m[3]||'').split('.').filter(Boolean))if(!this.classList.contains(c))return false;
  if(m[4]){const k=m[4].replace(/^data-/,'').replace(/-(\w)/g,(_,c)=>c.toUpperCase());if(!(m[4].startsWith('data-')?k in this.dataset:m[4] in this.attrs))return false;}
  return true;
 }
 querySelectorAll(sel){
  const parts=sel.trim().split(/\s+/);
  return this.all().filter(e=>{
   if(!e.matches(parts[parts.length-1]))return false;
   let p=e.parent,i=parts.length-2;
   while(i>=0){while(p&&!p.matches(parts[i]))p=p.parent;if(!p)return false;p=p.parent;i--;}
   return true;
  });
 }
 querySelector(sel){return this.querySelectorAll(sel)[0]||null;}
}

function makeEnv(){
 const timers=[];
 let perf=1000;
 const doc={activeElement:null};
 doc.createElement=t=>new El(t,doc);
 doc.body=new El('body',doc);
 doc.documentElement=new El('html',doc);
 const winL={};
 const win={
  innerWidth:420,devicePixelRatio:1,
  addEventListener:(t,f)=>{(winL[t]=winL[t]||[]).push(f);},
  removeEventListener:(t,f)=>{winL[t]=(winL[t]||[]).filter(x=>x!==f);},
  matchMedia:()=>({matches:true})
 };
 let raf=null;
 const vibrations=[];
 const env={
  Set,Map,Math,Object,String,Array,Number,Boolean,Promise,JSON,Date,Symbol,Infinity,NaN,parseInt,parseFloat,isFinite,
  document:doc,window:win,localStorage:{getItem:()=>null,setItem(){}},
  navigator:{vibrate:ms=>{vibrations.push(ms);}},
  performance:{now:()=>perf},
  requestAnimationFrame:f=>{raf=f;return 1;},cancelAnimationFrame:()=>{raf=null;},
  setTimeout:(f,ms)=>{const t={f,at:perf+ms,id:timers.length+1};timers.push(t);return t.id;},
  clearTimeout:id=>{const t=timers.find(x=>x.id===id);if(t)t.dead=true;},
  ResizeObserver:undefined,getComputedStyle:()=>({}),
  console
 };
 const c=vm.createContext(env);
 vm.runInContext(SOURCE+'\nglobalThis.api={openFieldGame};',c);
 return {
  api:c.api,doc,win,winL,vibrations,
  game:()=>vm.runInContext('activeGame',c),
  /* advance the fake clock, fire due timers and one animation frame per 16 ms */
  advance(ms){
   const end=perf+ms;
   while(perf<end){
    perf=Math.min(end,perf+16);
    for(const t of timers)if(!t.dead&&t.at<=perf){t.dead=true;t.f();}
    const f=raf;if(f){raf=null;f(perf);}
   }
  },
  key(code,extra={}){for(const f of winL.keydown||[])f({code,repeat:false,preventDefault(){},stopPropagation(){},...extra});},
  keyUp(code){for(const f of winL.keyup||[])f({code});},
  el:(root,sel)=>root.querySelector(sel)
 };
}

function field(over={}){return {id:'f1',w:8,h:8,ha:1,...over};}
function runOf(over={}){return {id:'r1',status:'open',op:'cultivate',width:1,rocks:[],weeds:[],rules:3,started_at:1000,expires_at:2800,...over};}
function open(env,{op='cultivate',runOver={},serverNow,cfg,onFinish}={}){
 const finished=[];
 const g=env.api.openFieldGame({
  field:field(),run:runOf({op,...runOver}),cfg,
  serverNow:serverNow||(()=>1000+60),
  onFinish:async p=>{finished.push(p);return true;},
  fieldNow:()=>null,
  ...(onFinish?{onFinish}:{})
 });
 return {g,finished,root:env.doc.body.children[0]};
}

/* ---------------------------------------------------------------- 1. held direction into a wall */
test('holding a direction into the field edge hits once per fresh press, not every frame',()=>{
 const env=makeEnv();
 const {g,root}=open(env);
 const run=()=>env.game().R;
 env.key('ArrowUp');                         // machine starts at (0,0): the top edge is a wall
 assert.equal(run().hits,1,'the fresh press is a real hit');
 assert.equal(env.vibrations.length,1);
 assert.match(env.el(root,'#fwHint').textContent,/Удар/);
 env.advance(100);
 const hint=env.el(root,'#fwHint').textContent;
 env.advance(2500);                          // key still held: auto-repeat frames (status line stays up for 4.2 s)
 assert.equal(run().hits,1,'auto-repeat must not write more hits');
 assert.equal(run().condition,97);
 assert.equal(env.vibrations.length,1,'no vibration from auto-repeat');
 assert.equal(run().path,'u');
 assert.equal(env.el(root,'#fwHint').textContent,hint);
 env.keyUp('ArrowUp');
 env.advance(2000);
 env.key('ArrowUp');                         // a new press is a new hit
 assert.equal(run().hits,2);
 g.close();
});

test('a held D-pad button at an obstacle is also a single hit; a new press hits again',()=>{
 const env=makeEnv();
 const {g,root}=open(env);
 const up=env.el(root,'.qwfr-dpad button');   // first pad button is data-dir="U"
 assert.equal(up.dataset.dir,'U');
 up.fire('pointerdown');
 env.advance(4000);
 assert.equal(env.game().R.hits,1);
 up.fire('pointerup');
 env.advance(500);
 up.fire('pointerdown');
 assert.equal(env.game().R.hits,2);
 g.close();
});

test('a swipe segment into a wall hits once per gesture direction',()=>{
 const env=makeEnv();
 const {g,root}=open(env);
 const canvas=env.el(root,'#fwCanvas');
 canvas.fire('pointerdown',{clientX:100,clientY:100});
 canvas.fire('pointermove',{clientX:100,clientY:70});    // up, 30 px
 env.advance(600);
 canvas.fire('pointermove',{clientX:100,clientY:40});    // up again, same blocked direction
 env.advance(600);
 canvas.fire('pointermove',{clientX:100,clientY:10});
 assert.equal(env.game().R.hits,1);
 g.close();
});

test('held key into a free direction still moves normally', ()=>{
 const env=makeEnv();
 const {g}=open(env);
 env.key('ArrowDown');
 env.advance(1500);
 assert.ok(env.game().R.y>=3,'keeps driving while held');
 assert.equal(env.game().R.hits,0);
 g.close();
});

/* ---------------------------------------------------------------- 2. transfer vs. max_path */
test('transfer never pushes X beyond the route limit and auto-transfer does not start when it does not fit',()=>{
 const env=makeEnv();
 // limit = min(3*8*8/1, cfg.maxPath) = 192; use a tiny server cap to make the limit reachable
 const {g,root}=open(env,{op:'harvest',cfg:{max_path:6},runOver:{unload_zone:true}});
 const G=()=>env.game();
 const R=G().R;
 R.load=18;                                   // full hopper (cap 18) at the truck row
 // reach the unload zone: centre must be near the truck; walk right along the top row
 for(let i=0;i<4;i++)R.push('R');
 assert.ok(R.canUnload(),'machine is at the truck');
 const need=R.transferSteps();
 assert.equal(need,4);
 // route is 4 long, limit 6: only 2 X fit => auto-transfer must not start
 env.advance(1500);
 assert.equal(G().transfer.active,false,'auto-transfer refuses when the whole unload does not fit');
 assert.equal(R.path.length,4);
 // manual hold-transfer is allowed partially but never exceeds the limit
 env.key('KeyX');
 for(let i=0;i<60&&env.game().transfer.active;i++)env.advance(100);
 env.keyUp('KeyX');
 assert.ok(R.path.length<=6,'route length '+R.path.length);
 assert.equal(R.path.length,6);
 assert.equal(G().transfer.active,false);
 const spoken=env.el(root,'#fwHint').textContent;
 env.advance(1500);
 assert.equal(env.el(root,'#fwHint').textContent,spoken,'no per-frame message spam at the limit');
 g.close();
});

test('transfer does not start at all when the route is already at the limit',()=>{
 const env=makeEnv();
 const {g,root}=open(env,{op:'harvest',cfg:{max_path:4},runOver:{unload_zone:true}});
 const R=env.game().R;
 R.load=18;
 for(let i=0;i<4;i++)R.push('R');
 env.key('KeyX');
 assert.equal(env.game().transfer.active,false);
 assert.equal(R.path.length,4);
 assert.match(env.el(root,'#fwHint').textContent,/ограничена/);
 g.close();
});

/* ---------------------------------------------------------------- 6. KeyX for spray */
test('KeyX starts the tank refill for the sprayer too',()=>{
 const env=makeEnv();
 const {g}=open(env,{op:'spray',runOver:{unload_zone:true,tank:48,wind:0}});
 const R=env.game().R;
 for(let i=0;i<4;i++)R.push('R');
 assert.ok(R.canUnload());
 env.key('KeyX');
 assert.equal(env.game().transfer.active,true);
 g.close();
});

/* ---------------------------------------------------------------- 3. server-clock deadline */
test('the deadline follows the server clock: a suspended page shows "Время вышло"',()=>{
 const env=makeEnv();
 let server=1060;
 const {g,root}=open(env,{serverNow:()=>server});
 env.advance(200);
 assert.equal(env.el(root,'#fwResult').hidden,true);
 server=2900;                                  // the WebView slept: the server clock moved 30 min, performance.now() did not
 env.advance(100);
 assert.equal(env.el(root,'#fwResult').hidden,false);
 assert.match(env.el(root,'#fwResult').children[0].children.map(c=>c.textContent).join(' '),/Время вышло/);
 g.close();
});

test('a failed submit after the server deadline reports expiry, not "already closed"',async ()=>{
 const env=makeEnv();
 let server=1060;
 const {g,root}=open(env,{serverNow:()=>server,onFinish:async()=>{server=2900;return false;}});
 env.game().R.push('D');
 env.el(root,'#fwFinish').fire('click');
 await new Promise(r=>setImmediate(r));
 await new Promise(r=>setImmediate(r));
 const text=env.el(root,'#fwResult').children[0].children.map(c=>c.textContent).join(' ');
 assert.match(text,/Время вышло/);
 g.close();
});

/* ---------------------------------------------------------------- 4. broken machine quality */
test('the live forecast of a broken machine equals the server autopilot quality (900), not the 850 floor',()=>{
 const env=makeEnv();
 const {g,root}=open(env);
 const R=env.game().R;
 for(let i=0;i<34&&R.condition>0;i++){      // 34 fresh hits of 3% break the machine
  env.key('ArrowUp');env.keyUp('ArrowUp');env.advance(500);
 }
 assert.equal(R.condition,0);
 assert.equal(env.el(root,'#fwQuality').textContent,'90,0%');
 g.close();
});

/* ---------------------------------------------------------------- 5. E23: autopilot needs a confirmation, far from the D-pad */
const tick=()=>new Promise(r=>setImmediate(r));
test('autopilot sits in the header, not next to the D-pad; «Темп» moved to the tool row',()=>{
 const env=makeEnv();
 const {g,root}=open(env);
 const auto=env.el(root,'#fwAuto');
 const inside=(el,sel)=>{for(let p=el.parent;p;p=p.parent)if(p.matches(sel))return true;return false;};
 assert.ok(inside(auto,'.qwfr-screen-top'),'autopilot is a header button');
 assert.ok(!inside(auto,'.qwfr-controls')&&!inside(auto,'.qwfr-actions'),'autopilot is not among the driving controls');
 assert.ok(inside(env.el(root,'.field-speed'),'.qwfr-actions'),'speed button is in the tool row');
 assert.ok(!env.el(root,'.qwfr-screen-top .field-speed'),'no speed button left in the header');
 assert.ok(inside(env.el(root,'#fwFinish'),'.qwfr-actions'));
 g.close();
});

test('one tap on autopilot only asks; «Нет» keeps the manual run, nothing is sent',async ()=>{
 const env=makeEnv();
 const {g,root,finished}=open(env);
 env.game().R.push('D');
 env.el(root,'#fwAuto').fire('click');
 await tick();
 const sheet=env.el(root,'#fwResult');
 assert.equal(sheet.hidden,false,'confirmation is shown');
 const text=sheet.children[0].children.map(c=>c.textContent).join(' ');
 assert.match(text,/Отдать поле автопилоту\?/);
 assert.match(text,/90,0%/);
 assert.match(text,/ручной бонус потеряется/);
 assert.equal(finished.length,0,'nothing submitted before the answer');
 env.key('ArrowDown');                                   // the pad is frozen while the question is open
 assert.equal(env.game().R.path,'D');
 env.el(root,'#fwAutoNo').fire('click');
 await tick();
 assert.equal(sheet.hidden,true);
 assert.equal(finished.length,0);
 env.key('ArrowDown');
 assert.equal(env.game().R.path,'DD','driving continues after «Нет»');
 g.close();
});

test('«Да» hands the field to the autopilot (path null); Escape cancels the question',async ()=>{
 const env=makeEnv();
 const {g,root,finished}=open(env);
 env.el(root,'#fwAuto').fire('click');
 env.key('Escape');
 assert.equal(env.el(root,'#fwResult').hidden,true,'Escape closes the question, not the game');
 assert.equal(finished.length,0);
 env.el(root,'#fwAuto').fire('click');
 env.el(root,'#fwAutoYes').fire('click');
 await tick();await tick();
 assert.deepEqual(finished,[null]);
 assert.match(env.el(root,'#fwResult').children[0].children.map(c=>c.textContent).join(' '),/Автопилот взялся/);
 g.close();
});

/* ---------------------------------------------------------------- 6. E23: stylesheet contract */
test('field_overlay.css: phone is full-screen with a big D-pad and no duplicated rules',()=>{
 const css=fs.readFileSync(path.join(dir,'field_overlay.css'),'utf8').replace(/\/\*[\s\S]*?\*\//g,'');
 // top-level rules (outside @media/@keyframes) must not repeat a selector
 let flat='',depth=0,inAt=false;
 for(let i=0;i<css.length;i++){
  const c=css[i];
  if(c==='@'&&depth===0){inAt=true;}
  if(c==='{'){depth++;}
  if(!inAt)flat+=c;
  if(c==='}'){depth--;if(depth===0&&inAt){inAt=false;}}
 }
 const sels=[...flat.matchAll(/([^{}]+)\{[^{}]*\}/g)].map(m=>m[1].trim().replace(/\s+/g,' ')).filter(Boolean);   // whole selector lists: a repeated rule is a copy-paste duplicate
 const seen=new Map();for(const s of sels)seen.set(s,(seen.get(s)||0)+1);
 const dup=[...seen].filter(([,n])=>n>1).map(([s])=>s);
 assert.deepEqual(dup,[],'duplicated rules: '+dup.join(' | '));
 const phone=/@media \(max-width:600px\)\{([\s\S]*?)\n\}/.exec(css);
 assert.ok(phone,'phone block exists');
 assert.match(phone[1],/--fw-pad:(6[0-9]|5[6-9])px/,'phone D-pad button >= 56 px');
 assert.match(phone[1],/border-radius:0/,'no card frame on the phone');
 assert.match(phone[1],/--fw-safe-t/,'safe-area top inside the screen');
 assert.match(phone[1],/--fw-safe-b/,'safe-area bottom inside the console');
 assert.equal((css.match(/@media \(max-width:430px\)/g)||[]).length,0,'no width-from-height phone rules left');
 assert.doesNotMatch(css,/aspect-ratio/,'the screen height is not derived from its width');
});
