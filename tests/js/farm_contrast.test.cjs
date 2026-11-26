const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.join(__dirname,'../..');
const read=p=>fs.readFileSync(path.join(root,p),'utf8');
const refreshCode=source=>source.slice(source.indexOf('function upkeepCatalogSnapshot('),source.indexOf('function readySnapshot('))+source.slice(source.indexOf('async function refresh('),source.indexOf('async function command('));
const css=read('qw_farm/static/style.css');
const block=css.slice(css.indexOf('/* ==== «Контрастный режим»'));
const declarations=selector=>Object.fromEntries([...block.match(new RegExp(selector+'\\{([^}]+)\\}'))[1].matchAll(/(--[\w-]+):([^;}]+)/g)].map(m=>[m[1],m[2]]));
const luminance=hex=>{const rgb=hex.slice(1).match(/../g).map(v=>parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return .2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2];};
const contrast=(a,b)=>{const aa=luminance(a),bb=luminance(b);return(Math.max(aa,bb)+.05)/(Math.min(aa,bb)+.05);};
test('farm contrast green text stays legible on day and night surfaces',()=>{
 const day=declarations(':root\\[data-qw-contrast="1"\\]');
 const night={...day,...declarations(':root\\[data-qw-contrast="1"\\]\\[data-farm-theme=night\\]')};
 for(const palette of [day,night])for(const text of ['--ink','--muted','--green2'])for(const surface of ['--surface','--surface-soft','--panel'])assert.ok(contrast(palette[text],palette[surface])>=4.5,`${text} on ${surface}`);
});
test('farm contrast captions use shell typography including narrow Telegram Desktop',()=>{
 assert.doesNotMatch(block,/font-size:1[2345]px/);
 assert.match(block,/\.seedbar \.seed span[^}]*font-size:var\(--qw-fs-caption,14px\)/);
 assert.match(block,/\.qw-btn.text\{font-size:var\(--qw-fs-small,14px\)/);
 const tokens=read('web/shell/qw-tokens.css');assert.match(tokens,/:root\.qw-desktop\[data-qw-contrast="1"\]\{--qw-fs-caption:15px;--qw-fs-small:15px\}/);
});
test('farm scene applies Account contrast dynamically and preserves the raw day/night state',async()=>{
 const {FarmScene}=await import('../../qw_farm/static/scene.js');let on=false;
 const s=Object.create(FarmScene.prototype);Object.assign(s,{contrast:false,nightDim:1,motion:false,readContrast:()=>({on,dim:on?.5:1}),isPaused:()=>false});
 s.setLighting({darkness:1,warmth:0,phase:'night'});assert.equal(s.lighting.darkness,1);
 s.cache={key:'old'};s.thumbs=new Map();on=true;s.applyContrast();assert.equal(s.lighting.darkness,.5);assert.equal(s.lightingRaw.darkness,1);assert.equal(s.cache.key,null);assert.equal(s.thumbs,null);
 s.setLighting({darkness:0,warmth:0,phase:'day'});assert.equal(s.lighting.darkness,0);assert.equal(s.contrast,true);
 s.setLighting({darkness:1,warmth:0,phase:'night'});on=false;s.applyContrast();assert.equal(s.lighting.darkness,1);assert.equal(s.contrast,false);
});
class Node{constructor(tag){this.tag=tag;this.children=[];this.attrs={};}append(...n){this.children.push(...n);}setAttribute(k,v){this.attrs[k]=v;}addEventListener(k,fn){this[k]=fn;}}
const walk=n=>[n,...n.children.filter(n=>n instanceof Node).flatMap(walk)];
test('both Profile switches persist account contrast and roll back a failed save',async()=>{
 const source=read('web/mini_client/app.js'),code=source.slice(source.indexOf('    function contrastSetting('),source.indexOf('    // Theme and haptics:'));
 for(const channel of ['guest','telegram']){
  const calls=[],prefs={contrast:false};let fail=false;
  const send=async(url,options)=>{calls.push([url,JSON.parse(options.body)]);if(fail)throw Error('offline');return{contrast_mode:JSON.parse(options.body).enabled};};
  const context={el:tag=>new Node(tag),state:{guest:{},me:{}},window:{QW:{prefs:{get:()=>prefs,setContrast:v=>{prefs.contrast=v;},applyAccount:r=>{prefs.contrast=r.contrast_mode;}}}},guestRequest:(url,method,o)=>send(url,o),request:send};
  vm.createContext(context);vm.runInContext(code,context);const box=context.contrastSetting(channel),input=walk(box).find(n=>n.tag==='input');input.checked=true;await input.change();assert.equal(prefs.contrast,true);assert.deepEqual(calls[0],[`/api/account/contrast-mode?identity=${channel}`,{enabled:true}]);
  fail=true;input.checked=false;await input.change();assert.equal(prefs.contrast,true);assert.equal(input.checked,true);
 }
});
test('farm boot and refresh apply the Account value from /start and /me',()=>{
 const app=read('qw_farm/static/app.js');assert.match(app,/S.form=data.address_form\|\|'n';try\{globalThis.QW\?\.prefs\?\.applyAccount\?\.\(data\)/);assert.match(app,/S\.form=me\.address_form\|\|'n';try\{globalThis\.QW\?\.prefs\?\.applyAccount\?\.\(me\);\}catch\{\}S\.me=me\.farm[^\n]*syncFarmMotion\(\)/);
 assert.match(app,/QW\?\.configure\?\.\(\{identity:mode\}\)/);assert.match(app,/prefs\?\.clearAccount\?\.\(\)/);
 const service=read('qw_farm/service.py');assert.ok(service.includes("'game_preferences':dict(self.p.game_preferences or {})"));assert.equal((service.match(/\*\*self\._account_prefs\(\)/g)||[]).length,2);
});

test('farm animation preference follows the account and retains standalone fallback',()=>{
 const source=read('qw_farm/static/app.js'),code=source.slice(source.indexOf('function farmAnimationsFallback('),source.indexOf('const villageReduced='));
 const makeContext=({account=false,animations,legacy='false',reduced=false}={})=>{
  const attrs=new Map([['qw-farm.reduced-motion',legacy]]),writes=[];
  const context={matchMedia:()=>({matches:reduced}),localStorage:{getItem:k=>attrs.get(k)||null,setItem:(k,v)=>{attrs.set(k,v);writes.push([k,v]);}},
   scene:{motion:true,dirty:false,syncLoop(){this.synced=true;}},QW:{prefs:{hasAccount:()=>account,get:()=>({gamePreferences:typeof animations==='boolean'?{animations}:{}}),animationsEnabled:fallback=>typeof animations==='boolean'?animations:fallback}}};
  vm.createContext(context);vm.runInContext(code,context);return{context,attrs,writes};
 };
 assert.equal(makeContext({reduced:true}).context.farmAnimationsEnabled(),false,'device reduced-motion is the standalone default');
 assert.equal(makeContext({legacy:'true'}).context.farmAnimationsEnabled(),false,'legacy local calm preference remains a fallback');
 const enabled=makeContext({account:true,animations:true,legacy:'true'});assert.equal(enabled.context.farmAnimationsEnabled(),true,'explicit account choice overrides legacy local setting');
 const disabled=makeContext({account:true,animations:false});assert.equal(disabled.context.farmAnimationsEnabled(),false,'explicit account choice disables animation');
 disabled.context.syncFarmMotion();assert.equal(disabled.context.scene.motion,false);assert.equal(disabled.context.scene.dirty,true);assert.equal(disabled.context.scene.synced,true);
});
test('authenticated farm delegates visual preferences to profile and responds to account changes',()=>{
 const app=read('qw_farm/static/app.js'),settings=app.slice(app.indexOf('function renderViewSettings('),app.indexOf('// «Управление и подсказки»'));
 assert.doesNotMatch(app,/farm-contrast-mode|saveFarmContrast|farmContrastEpoch|farmContrastPending/);
 assert.match(settings,/if\(!globalThis\.QW\?\.prefs\?\.hasAccount\?\.\(\)\)\{/);
 assert.match(app,/addEventListener\?\.\('qw:game-preferences',syncFarmMotion\)/);
 const html=read('qw_farm/static/index.html');const shellJs=h=>(h.match(/qw-shell\.js\?v=([\w-]+)/)||[])[1];assert.ok(shellJs(html),'the farm loads the shared shell with a version');assert.equal(shellJs(html),shellJs(read('web/mini_client/index.html')),'the farm and the hub load the same shell version');assert.match(html,/qw-shell\.css\?v=20261124-account-game-preferences/);assert.match(html,/farm\/assets\/app\.js\?v=[\w-]+"/);
});
test('refresh applies a new farm upkeep catalog revision and redraws the open view without changing selection',async()=>{
 const source=read('qw_farm/static/app.js'),own={id:'farm-a',server_time:100},oldCatalog={economy:{upkeep_revision:4,building_rate_pct:1}},nextCatalog={economy:{upkeep_revision:5,building_rate_pct:3}};
 const renders={panel:0,seeds:0,scene:0},context={S:{me:own,farm:own,catalog:oldCatalog,tab:'economy',selected:'upkeep',seed:'wheat',config:{demo:false}},
 mode:'guest',farmViewEpoch:0,refreshEpoch:0,API:'/api/farm/v1',
 request:async()=>({farm:own,catalog:nextCatalog,address_form:'n',speed:1}),showLogin(){},QW:{prefs:{applyAccount(){}}},syncFarmMotion(){},
 sceneSnapshot:()=>'',hudSnapshot:()=>'',seedsSnapshot:()=>'',scene:{set(){renders.scene++;}},dashaGame:null,olegGame:null,ballistaGame:null,pieGame:null,santaGame:null,santaGameOpen:false,
 queueNeighborGifts(){},FRIEND_REQUESTS:{notify(){}},syncMenuBadges(){},orchardNotices(){},updateHUD(){},renderSeeds(){renders.seeds++;},updateReady(){},renderPanel(){renders.panel++;},connection(){}};
 vm.createContext(context);vm.runInContext(refreshCode(source),context);
 assert.equal(await context.refresh({render:false}),true);assert.equal(context.S.catalog,nextCatalog);assert.equal(renders.scene,1);assert.equal(renders.seeds,1);assert.equal(renders.panel,1);assert.equal(context.S.tab,'economy');assert.equal(context.S.selected,'upkeep');
});
test('refresh applies effective upkeep rates at Moscow midnight when the scheduled revision stays the same',async()=>{
 const source=read('qw_farm/static/app.js'),own={id:'farm-a',server_time:100},oldCatalog={economy:{upkeep_revision:5,upkeep_level:10,land_rate_pct:100,plot_upkeep:{10:100},building_rate_pct:1,field_per_hectare:1500,field_upkeep:1500,tree_rate_per_extra_tree:25}},
  nextCatalog={economy:{...oldCatalog.economy,land_rate_pct:150,plot_upkeep:{10:150},building_rate_pct:3}};
 let panels=0;const context={S:{me:own,farm:own,catalog:oldCatalog,tab:'economy',selected:'upkeep',config:{demo:false}},mode:'guest',farmViewEpoch:0,refreshEpoch:0,API:'/api/farm/v1',
 request:async()=>({farm:own,catalog:nextCatalog,address_form:'n',speed:1}),showLogin(){},QW:{prefs:{applyAccount(){}}},syncFarmMotion(){},sceneSnapshot:()=>'',hudSnapshot:()=>'',seedsSnapshot:()=>'',scene:{set(){}},dashaGame:null,olegGame:null,ballistaGame:null,pieGame:null,santaGame:null,santaGameOpen:false,
 queueNeighborGifts(){},FRIEND_REQUESTS:{notify(){}},syncMenuBadges(){},orchardNotices(){},updateHUD(){},renderSeeds(){},updateReady(){},renderPanel(){panels++;},connection(){}};
 vm.createContext(context);vm.runInContext(refreshCode(source),context);
 assert.equal(oldCatalog.economy.upkeep_revision,nextCatalog.economy.upkeep_revision,'the active config keeps the revision assigned when the settings were scheduled');
 assert.equal(await context.refresh({render:false}),true);assert.equal(context.S.catalog,nextCatalog);assert.equal(context.S.catalog.economy.building_rate_pct,3);assert.equal(panels,1);
});
test('a stale /me reply cannot install an old upkeep catalog revision',async()=>{
 const source=read('qw_farm/static/app.js'),own={id:'farm-a',server_time:100},oldCatalog={economy:{upkeep_revision:4}},staleCatalog={economy:{upkeep_revision:5}};let reply;
 const context={S:{me:own,farm:own,catalog:oldCatalog,tab:'economy',selected:'upkeep',config:{demo:false}},mode:'guest',farmViewEpoch:0,refreshEpoch:0,API:'/api/farm/v1',
 request:()=>new Promise(resolve=>{reply=resolve;}),showLogin(){},QW:{prefs:{applyAccount(){}}},sceneSnapshot:()=>'',hudSnapshot:()=>'',seedsSnapshot:()=>'',scene:{set(){assert.fail('stale response must not redraw');}},dashaGame:null,olegGame:null,ballistaGame:null,pieGame:null,santaGame:null,santaGameOpen:false,
 queueNeighborGifts(){},FRIEND_REQUESTS:{notify(){}},syncMenuBadges(){},orchardNotices(){},updateHUD(){},renderSeeds(){assert.fail('stale response must not redraw');},updateReady(){},renderPanel(){assert.fail('stale response must not redraw');},connection(){}};
 vm.createContext(context);vm.runInContext(source.slice(source.indexOf('async function refresh('),source.indexOf('async function command(')),context);
 const pending=context.refresh({render:false});context.farmViewEpoch++;reply({farm:own,catalog:staleCatalog,address_form:'n',speed:1});assert.equal(await pending,false);assert.equal(context.S.catalog,oldCatalog);
});
