const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

test('phone destination cards keep their width instead of shrinking away the overflow',()=>{
 const css=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/style.css'),'utf8');
 const rules=[...css.matchAll(/html \.compact \.header-destinations>\.forest-door\{([^}]+)\}/g)];
 assert.ok(rules.length);
 assert.match(rules.at(-1)[1],/flex:0 0 92px/);
 assert.match(css,/overflow-x:auto;overflow-y:hidden;scroll-snap-type:x proximity/);
});

test('fields stays visible before level 22 and advertises its existing lock explanation',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
 const start=source.indexOf("const fieldsDoor=$('fields-door'),"),end=source.indexOf("$('object-list-button')",start);
 assert.ok(start>=0&&end>start);
 for(const owner of [true,false])for(const level of [1,21,22]){
  const card={setAttribute(k,v){this[k]=v;}},ctx={S:{catalog:{fields:{min_level:22}},me:{level}},$:()=>card,own:()=>owner};
  vm.runInNewContext(source.slice(start,end),ctx);
  assert.equal(card.hidden,false);
  assert.equal(card['aria-label'].includes('Откроется на 22 уровне'),level<22);
  assert.equal(card['aria-label'].includes('Вернуться к своим полям'),!owner);
 }
 assert.match(source,/\$\('fields-door'\)\.onclick=safe\(async\(\)=>\{[^\n]*selectTab\('fields'\)/);
 assert.match(source,/if\(S\.me\.level<F\.min_level\)\{/);
});

const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
const start=source.indexOf('function bindDestinationCarousel(');
const end=source.indexOf('\n// Every destination card',start);
const context={setTimeout,clearTimeout};
vm.createContext(context);
vm.runInContext(source.slice(start,end)+'\nthis.bindDestinationCarousel=bindDestinationCarousel;',context);

class Events{
 constructor(){this.listeners=new Map();}
 addEventListener(type,fn,options){const list=this.listeners.get(type)||[];list.push({fn,capture:options===true||options?.capture===true});this.listeners.set(type,list);}
 dispatch(type,event={}){
  event.type=type;event.preventDefault??=()=>{event.defaultPrevented=true;};event.stopPropagation??=()=>{event.propagationStopped=true;};
  for(const listener of this.listeners.get(type)||[])listener.fn(event);
  return event;
 }
}

function setup({scrollWidth=600,clientWidth=300,scrollLeft=0}={}){
 const nav=new Events(),win=new Events(),classes=new Set();
 Object.assign(nav,{scrollWidth,clientWidth,scrollLeft,classList:{add:name=>classes.add(name),remove:name=>classes.delete(name)}});
 context.bindDestinationCarousel(nav,win);
 return {nav,win,classes};
}

test('vertical wheel input scrolls the overflowing carousel sideways',()=>{
 const {nav}=setup();
 const event=nav.dispatch('wheel',{deltaX:0,deltaY:80,ctrlKey:false});
 assert.equal(nav.scrollLeft,80);
 assert.equal(event.defaultPrevented,true);
});

test('dominant horizontal wheel input uses deltaX',()=>{
 const {nav}=setup();
 nav.dispatch('wheel',{deltaX:120,deltaY:8,ctrlKey:false});
 assert.equal(nav.scrollLeft,120);
});

test('line-based wheel input is converted to pixels',()=>{
 const {nav}=setup();
 nav.dispatch('wheel',{deltaX:0,deltaY:3,deltaMode:1,ctrlKey:false});
 assert.equal(nav.scrollLeft,48);
});

test('a carousel with no overflow does not intercept the wheel',()=>{
 const {nav}=setup({scrollWidth:300,clientWidth:300});
 const event=nav.dispatch('wheel',{deltaX:0,deltaY:80,ctrlKey:false});
 assert.equal(nav.scrollLeft,0);
 assert.equal(event.defaultPrevented,undefined);
});

test('mouse drag scrolls and suppresses the click caused by the drag',()=>{
 const {nav,win,classes}=setup({scrollLeft:40});
 nav.dispatch('pointerdown',{pointerType:'mouse',button:0,pointerId:7,clientX:100});
 win.dispatch('pointermove',{pointerId:7,clientX:70});
 assert.equal(nav.scrollLeft,70);
 assert.equal(classes.has('dragging'),true);
 win.dispatch('pointerup',{pointerId:7});
 assert.equal(classes.has('dragging'),false);
 const click=nav.dispatch('click',{});
 assert.equal(click.defaultPrevented,true);
 assert.equal(click.propagationStopped,true);
});

test('stationary mouse press keeps its click active',()=>{
 const {nav,win}=setup();
 nav.dispatch('pointerdown',{pointerType:'mouse',button:0,pointerId:3,clientX:100});
 win.dispatch('pointerup',{pointerId:3});
 const click=nav.dispatch('click',{});
 assert.equal(click.defaultPrevented,undefined);
});
