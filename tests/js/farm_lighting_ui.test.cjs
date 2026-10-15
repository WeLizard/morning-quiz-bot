const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
function fixture(stored='auto',blocked=false){
 const attrs={},meta={},calls=[],saved=[],timers=new Map(),cleared=[];
 const toggle={dataset:{},setAttribute:(k,v)=>attrs[k]=v},setting={};
 const root={dataset:{},style:{}};
 const document={documentElement:root,hidden:false,querySelector:selector=>({setAttribute:(k,v)=>meta[selector]=v})};
 let timerId=0;
 const context=vm.createContext({document,window:{Telegram:{WebApp:Object.fromEntries(['setHeaderColor','setBackgroundColor','setBottomBarColor'].map(k=>[k,v=>calls.push([k,v])]))}},
  localStorage:{getItem:()=>{if(blocked)throw Error('denied');return stored;},setItem:(k,v)=>{if(blocked)throw Error('denied');saved.push([k,v]);}},
  $:id=>id==='lighting-toggle'?toggle:setting,scene:{setLighting:s=>calls.push(['scene',s])},
  farmLightingAt:(date,mode)=>({mode,phase:mode==='day'?'day':'night',darkness:mode==='day'?0:1,warmth:0}),
  clearInterval:id=>{cleared.push(id);timers.delete(id);},setInterval:(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId;},updateReady:()=>{},poll:()=>{},readyTimer:null,pollTimer:null});
 vm.runInContext(source.slice(source.indexOf("let lightingMode='auto'"),source.indexOf('const $=')),context);
 vm.runInContext(source.slice(source.indexOf('function syncUITimers(){'),source.indexOf('syncUITimers();document.addEventListener')),context);
 return {context,root,attrs,meta,calls,saved,timers,cleared,document,setting};
}
test('saved night synchronizes scene, surfaces, accessible control and Telegram chrome',()=>{
 const f=fixture('night');vm.runInContext('updateFarmLighting()',f.context);
 assert.equal(f.root.dataset.farmTheme,'night');assert.equal(f.root.style.colorScheme,'dark');assert.equal(f.context.$('lighting-toggle').dataset.mode,'night');assert.match(f.attrs['aria-label'],/всегда ночь/);assert.equal(f.setting.value,'night');
 assert.equal(f.meta['meta[name="theme-color"]'],'#172821');
 assert.deepEqual(f.calls.filter(c=>c[0]!=='scene').map(c=>c[1]),['#172821','#172821','#172821']);assert.equal(f.calls.find(c=>c[0]==='scene')[1].mode,'night');
 vm.runInContext("setLightingMode('day')",f.context);assert.equal(f.root.dataset.farmTheme,'day');assert.equal(f.meta['meta[name="theme-color"]'],'#efeee4');assert.deepEqual(f.saved,[['qw-farm.lighting','day']]);
});
test('blocked storage and invalid saved mode do not break lighting',()=>{
 for(const f of [fixture('broken'),fixture('auto',true)]){vm.runInContext('updateFarmLighting();setLightingMode("night")',f.context);assert.equal(f.root.dataset.farmTheme,'night');}
});
test('minute refresh pauses while hidden and resumes without accumulating intervals',()=>{
 const f=fixture();vm.runInContext('syncUITimers()',f.context);assert.equal([...f.timers.values()].filter(t=>t.ms===60000).length,1);
 f.document.hidden=true;vm.runInContext('syncUITimers()',f.context);assert.equal(f.timers.size,0);
 f.document.hidden=false;vm.runInContext('syncUITimers();syncUITimers()',f.context);assert.equal(f.timers.size,3);assert.equal([...f.timers.values()].filter(t=>t.ms===60000).length,1);
});

// Preserve the compact icon contract alongside the runtime mode checks.
test('sky toggle is the single leftmost header control and remains icon only',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/index.html'),'utf8');
 const css=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/style.css'),'utf8');
 const button=html.match(/<button id="lighting-toggle"[\s\S]*?<\/button>/)[0];
 assert.match(html,/<header class="topbar">\s*<button id="lighting-toggle"/);
 assert.equal((html.match(/id="lighting-toggle"/g)||[]).length,1);
 assert.ok(html.indexOf('id="lighting-toggle"')<html.indexOf('id="hud"'));
 assert.doesNotMatch(html,/<a class="brand"/);
 assert.ok(html.indexOf('id="lighting-toggle"')<html.indexOf('id="header-actions"'));
 assert.match(button,/type="button"/);assert.match(button,/aria-label="Свет:/);assert.match(button,/title="Свет:/);
 assert.match(button,/class="lighting-auto"/);assert.match(button,/aria-hidden="true"/);
 assert.equal(button.replace(/<[^>]*>/g,'').trim(),'');
 assert.match(css,/\.lighting-toggle\{[^}]*min-width:44px[^}]*min-height:44px[^}]*background:transparent/);
 assert.match(css,/data-mode=auto\] \.lighting-auto\{display:block/);
});
test('icon retains all three persisted modes and accessible mode names',()=>{
 const f=fixture();
 for(const [mode,label] of [['auto','по времени'],['day','всегда день'],['night','всегда ночь']]){
  vm.runInContext(`setLightingMode('${mode}')`,f.context);
  assert.equal(f.context.$('lighting-toggle').dataset.mode,mode);
  assert.ok(f.attrs['aria-label'].includes(label));assert.ok(f.context.$('lighting-toggle').title.includes(label));
 }
});

test('forest and lake wrappers are transparent without changing destination art',()=>{
 const css=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/style.css'),'utf8');
 assert.match(css,/\.header-destinations #forest-door,\.header-destinations #lake-door\{background:transparent;border:0;box-shadow:none\}/);
});

test('QW home navigation is available in settings and before login',()=>{
 assert.match(source,/function renderViewSettings\(p\)\{\s*p.append\(quizzyHomeLink\(\)\)/);
 assert.match(source,/if\(message\)note\(message,c\);c.append\(quizzyHomeLink\(\)\)/);
 assert.match(source,/function quizzyHomeLink\(\)\{[\s\S]*?mark=el\('span','Q','brand-icon'\);mark.append\(el\('span','W'\)\)/);
 assert.match(source,/link.href=invite\?`\/app\?invite=\$\{invite\}`:'\/app'/);
});

test('farm name remains on the map and in settings without a header duplicate',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/index.html'),'utf8');
 assert.doesNotMatch(html,/farm-header-title/);assert.doesNotMatch(source,/farm-header-title/);
 assert.match(html,/id="farm-name"/);assert.match(source,/\$\('farm-name'\).textContent=displayName/);
 assert.match(source,/field\('Название фермы','text',S.me.name\)/);
});
