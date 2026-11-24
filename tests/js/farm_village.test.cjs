const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
const figures=JSON.parse(source.match(/const VILLAGE_RESIDENT_FIGURES=(.*);/)[1]);
const block=source.slice(source.indexOf('// Living village uses existing personal orders'),source.indexOf('/* ---- r9 stage 15B:'));
const declarations=source.slice(source.indexOf('const VILLAGE_VOICES='),source.indexOf('const fmt='));
class Node{
 constructor(tag){this.tagName=tag;this.children=[];this.dataset={};this.attrs={};this.style={};this.hidden=false;this.replaces=0;this.classList={add(){},remove(){}};}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=nodes;this.replaces++;}
 setAttribute(k,v){this.attrs[k]=v;}
 focus(){this.focused=true;}
 getBoundingClientRect(){return {top:200,bottom:244,left:0,right:44,width:44,height:44};}
 querySelector(){return null;}
 querySelectorAll(selector){const all=this.children.flatMap(n=>n instanceof Node?[n,...n.querySelectorAll('*')]:[]);return selector==='*'?all:all.filter(n=>selector.includes('data-village-npc')?n.dataset.villageNpc||n.dataset.villageTownhall||selector.includes('data-village-place')&&n.dataset.villagePlace:selector.includes('data-village-focus')?n.dataset.villageFocus:selector==='[data-village-site]'?n.dataset.villageSite:selector==='.village-services'?n.className==='village-services':false);}
}
const AC=h=>h.nodes.get('village-scene').children[0].children.find(n=>n.className==='village-actors');
function setup(){
 const nodes=new Map(),area=new Node('section'),calls=[],pause=[],bodyClasses=new Set();
 const S={me:{id:'own',is_owner:true,orders:[{id:'one',npc:'Филиныч',title:'Чай',needs:{tea:2},coins:100,xp:10}],inventory:{tea:2},market:{}},farm:{id:'guest'},tab:'orders',catalog:{market:{tastes:{'Филиныч':['tea'],'Агата':['bread']}}},village:null};
 nodes.set('farm-canvas',new Node('canvas'));nodes.set('panel-content',new Node('div'));nodes.set('panel-head',new Node('div'));const sheetFocus=new Node('section'),title=new Node('h2');nodes.get('panel-content').querySelector=()=>sheetFocus;nodes.get('panel-head').querySelector=()=>title;
 // General village fixtures have no active Horseman; its active flow is covered by farm_horseman.test.cjs.
 const ctx={S,AVATARS:{},cashBonusText:()=>'',clearOfHeader:(r,h,gap=8)=>r.top>=h.bottom+gap||r.right<=h.left||r.left>=h.right,horsemanDisplay:()=>null,now:()=>0,own:()=>S.me?.is_owner===true,openDashaGame:()=>calls.push('open-dasha'),openOlegGame:()=>calls.push('open-oleg'),dashaReasonText:reason=>({level:'Игра открывается с 3 уровня.',daily_limit:'Лимит ставок 200 монет в день исчерпан.',pending_payout:'Выигрыш ожидает места на балансе.',earned_balance:'Для ставки нужны заработанные монеты.',wallet_limit:'Баланс монет достиг предела.',active:'Раунд уже начат — выбери стаканчик.'}[reason]||'Игра сейчас недоступна.'),document:{activeElement:null,body:{classList:{toggle:(k,v)=>v?bodyClasses.add(k):bodyClasses.delete(k),add:k=>bodyClasses.add(k),remove:k=>bodyClasses.delete(k),contains:k=>bodyClasses.has(k)}},querySelector:()=>area},
 $:id=>nodes.get(id),el:(tag,text,cls)=>{const n=new Node(tag);n.textContent=text;n.className=cls;return n;},icon:()=>new Node('svg'),
 button:(text,fn,cls,disabled)=>{const n=new Node('button');n.textContent=text;n.onclick=fn;n.disabled=disabled;return n;},
 scene:{setPaused:v=>pause.push(v),set:()=>calls.push('scene'),selected:'x',resize(){}},farmViewEpoch:4,requestAnimationFrame:fn=>fn(),
 eco:()=>({fund_open:ctx.openFund}),ECON:()=>({fund_level:8}),repInfo:()=>({lv:1,bonus:5}),repBar:()=>new Node('div'),
 enough:needs=>Object.entries(needs).every(([k,v])=>S.me.inventory[k]>=v),
 command:async(kind,data)=>{calls.push([kind,data]);S.busy=true;return true;},fmt:String,
 backHome:()=>calls.push('back-home'),
 card:(name)=>{const n=new Node('section');n.textContent=name;return n;},goods:()=>new Node('div'),note:(text,p)=>p.append(new Node(text)),
 showPanel(){bodyClasses.add('panel-open');bodyClasses.delete('panel-collapsed');},renderPanel(){ctx.syncVillageScene();},renderRail(){},updateHUD(){},renderSeeds(){},meter:()=>new Node('div'),heading(){},fundCard(){},upkeepCard(){},decorShop(){},openFund:false};
 // Register dynamically created scene exactly as a browser's getElementById would.
 area.append=n=>nodes.set(n.id,n);
  vm.createContext(ctx);vm.runInContext(declarations+block+'\n'+source.slice(source.indexOf('function selectTab(id)'),source.indexOf('let seedCardVisible'))+'\n'+source.slice(source.indexOf('function closePanel()'),source.indexOf('function showPanel()'))+'\nObject.assign(globalThis,{closePanel,exitVillage,returnToFarm,resetVillageView,openVillageTownHall,villageStage,villageOrders,deliverVillageOrder,chooseVillageResident,syncVillageScene,renderVillageResident,appendDashaAction,selectTab,syncScenePause})',ctx);
 return {ctx,S,nodes,calls,pause,bodyClasses,sheetFocus,title};
}
test('entering village from guest routes to own farm and invalidates older requests',()=>{
 const h=setup();h.ctx.selectTab('village');assert.equal(h.S.farm,h.S.me);assert.equal(h.S.tab,'village');assert.equal(h.ctx.farmViewEpoch,5);assert.ok(h.calls.includes('scene'));assert.equal(h.bodyClasses.has('panel-open'),false);assert.equal(h.bodyClasses.has('panel-collapsed'),true);const world=AC(h);assert.equal(world.children.filter(n=>n.dataset.villageNpc&&n.attrs['aria-pressed']==='true').length,0);
});

test('construction moves the three residents to their tools and Pukh keeps access to the ballista',()=>{
 const h=setup(),name='Медведь Пух',walking=[];
 h.S.catalog.market.tastes[name]=['honey'];
 h.S.me.village_games={pukh_ballista:{attempts_left:3}};
 h.ctx.openBallistaGame=()=>h.calls.push('open-ballista');
 h.ctx.villageWalk=(target,open,instant,key)=>{walking.push({target,instant,key});open();};
 h.ctx.selectTab('village');
 const scene=h.nodes.get('village-scene'),world=scene.children[0];
 const crew=world.children.find(n=>n.className==='village-crew-layer');
 scene.querySelector=selector=>world.children.find(n=>n.className?.split(' ').includes(selector.slice(1)));
 h.ctx.document.createElementNS=(_ns,tag)=>new Node(tag);
 crew.append=node=>{node.remove=()=>{crew.children=crew.children.filter(n=>n!==node);};crew.children.push(node);};
 const pooh=()=>{
  const buttons=AC(h).children.filter(n=>n.dataset.villageNpc===name);
  assert.equal(buttons.length,1);return buttons[0];
 };
 const play=b=>{
  assert.equal(b.attrs['aria-label'],name);assert.equal(b.attrs['aria-controls'],'panel-content');
  b.onclick({detail:0,currentTarget:b});assert.equal(pooh().attrs['aria-pressed'],'true');
  const panel=new Node('div');h.ctx.renderVillageResident(panel);
  panel.querySelectorAll('*').find(n=>n.dataset.openBallista==='true').onclick();
  assert.equal(h.calls.at(-1),'open-ballista');
 };
 const idle=pooh();assert.equal(idle.dataset.pooh,'roaming');
 assert.match(idle.children[0].innerHTML,/class="roaming-arm"/);
 assert.doesNotMatch(idle.children[0].innerHTML,/bc-hammer/);
 play(idle);assert.equal(walking.at(-1).key,name);
 const sites=new Set(['stalls','tavern']);
 h.ctx.CONSTR={art:id=>({stage:sites.has(id)?'pit':'soon',crew:sites.has(id)}),siteLabel:(_id,name)=>name,rowsOpen:()=>false};
 h.ctx.syncVillageScene();
 const plaques=()=>scene.querySelectorAll('[data-village-site]');
 assert.deepEqual(plaques().filter(n=>n.dataset.working==='true').map(n=>n.dataset.villageSite),['stalls','tavern']);
 const worker=pooh();assert.equal(worker.dataset.pooh,'working');assert.match(worker.children[0].innerHTML,/class="bc-hammer"/);
 assert.equal(worker.style.left,`${1005/24}%`);assert.equal(worker.style.top,`${985/18}%`);
 const minimap=h.nodes.get('village-hud').children.find(n=>n.dataset.villageMinimap);
 assert.equal(minimap.children.find(n=>n.title===name).style.left,worker.style.left);
 assert.deepEqual(crew.children.map(n=>n.className),['village-crew vc-krot','village-crew vc-kaya','village-crew vc-krot','village-crew vc-kaya']);
 const priorWalks=walking.length;
 play(worker);assert.equal(walking.length,priorWalks,'worksite selection opens without walking away from the site');
 h.S.catalog.market.tastes['Механик Крот']=['wood'];h.S.catalog.market.tastes['Кошка Кая']=['fish'];
 h.ctx.syncVillageScene();assert.equal(crew.children.length,0,'every interactive worker replaces its stand-in');
 const workers=AC(h).children.filter(n=>n.dataset.residentMode==='working');
 assert.equal(workers.length,3);
 const build=vm.runInContext('VILLAGE_BUILD',h.ctx);
 for(const [i,[npc,tool]] of [['Механик Крот','plan'],[name,'hammer'],['Кошка Кая','shovel']].entries()){
  const button=workers.find(n=>n.dataset.villageNpc===npc),[x,y]=build.crew.stalls[i];
  assert.match(button.children[0].innerHTML,new RegExp(`class="bc-${tool}"`));
  assert.equal(button.style.left,`${x/24}%`);assert.equal(button.style.top,`${y/18}%`);
  button.onclick({detail:0,currentTarget:button});assert.equal(vm.runInContext('villageResident',h.ctx),npc);
 }
 sites.clear();h.ctx.syncVillageScene();
 assert.equal(pooh().dataset.pooh,'roaming');assert.equal(pooh().style.left,idle.style.left);assert.equal(crew.children.length,0);
 assert.equal(AC(h).children.filter(n=>n.dataset.residentMode==='working').length,0);
 assert.ok(plaques().every(n=>n.dataset.working==='false'));
});

test('Hedgehog and the existing post sign open the read-only bulletin without leaving village',()=>{
 const h=setup();h.S.catalog.market.tastes['Почтальон Ёж']=['tea'];h.ctx.selectTab('village');
 h.ctx.chooseVillageResident('Почтальон Ёж');const panel=new Node('div');h.ctx.renderVillageResident(panel);
 const news=panel.querySelectorAll('*').find(n=>n.textContent==='Деревенский вестник');assert.ok(news);news.onclick();
 assert.equal(vm.runInContext('villageSheet',h.ctx),'bulletin');assert.equal(h.S.tab,'village');assert.equal(h.title.focused,true);
 const calls=[];h.ctx.now=()=>123;h.ctx.renderBulletin=(parent,me,now)=>calls.push({parent,me,now});
 h.ctx.renderVillage(panel);assert.equal(calls[0].me,h.S.me);assert.equal(calls[0].now,123);
 h.ctx.chooseVillageResident('Почтальон Ёж');
 const post=h.nodes.get('village-scene').querySelectorAll('*').find(n=>n.dataset.villagePlace==='post');assert.ok(post);post.onclick({detail:0});
 assert.equal(vm.runInContext('villageSheet',h.ctx),'bulletin');assert.equal(h.S.tab,'village');
 h.S.me.is_owner=false;h.ctx.openVillageBulletin();assert.equal(vm.runInContext('villageSheet',h.ctx),'bulletin');
 assert.equal(h.calls.some(c=>Array.isArray(c)),false,'reading never submits a game command');
});

test('bulletin close restores visible source focus, and Back retains the restored parent sheet',()=>{
 const h=setup();h.S.catalog.market.tastes['Почтальон Ёж']=['tea'];h.ctx.selectTab('village');
 h.ctx.renderPanel=()=>{
  h.ctx.syncVillageScene();const p=h.nodes.get('panel-content');p.replaceChildren();
  const sheet=vm.runInContext('villageSheet',h.ctx);
  if(sheet==='resident')h.ctx.renderVillageResident(p);
  else if(sheet==='rows'){const news=new Node('button');news.dataset.villageFocus='bulletin';p.append(news);}
 };
 h.ctx.chooseVillageResident('Почтальон Ёж');
 h.nodes.get('panel-content').querySelectorAll('*').find(n=>n.dataset.villageFocus==='bulletin').onclick();
 assert.equal(h.ctx.closePanel(),false,'closing nested news keeps the parent panel');
 assert.equal(vm.runInContext('villageSheet',h.ctx),'resident');assert.equal(h.bodyClasses.has('panel-open'),true);
 assert.equal(h.nodes.get('panel-content').querySelectorAll('*').find(n=>n.dataset.villageFocus==='bulletin').focused,true);
 h.ctx.closePanel();assert.equal(h.bodyClasses.has('panel-open'),false);
 h.ctx.openVillageBulletin('post');h.ctx.closePanel();
 assert.equal(h.bodyClasses.has('panel-open'),false);
 assert.equal(h.nodes.get('village-scene').querySelectorAll('*').find(n=>n.dataset.villagePlace==='post').focused,true);
 const stack=new Map();h.ctx.QW={config:{history:false},nav:{has:id=>stack.has(id),push:entry=>stack.set(entry.id,entry),pop:id=>stack.delete(id)}};
 h.ctx.farmMenuOpen=false;
 const start=source.indexOf('function navPush('),end=source.indexOf('new MutationObserver(syncNav)',start);
 vm.runInContext(source.slice(start,end),h.ctx);
 h.ctx.openVillageBulletin('rows');h.ctx.syncNav();
 assert.equal(stack.get('panel').onBack(),false,'shell Back keeps the panel entry while returning to rows');
 assert.equal(vm.runInContext('villageSheet',h.ctx),'rows');assert.equal(h.bodyClasses.has('panel-open'),true);
 assert.equal(h.nodes.get('panel-content').querySelectorAll('*').find(n=>n.dataset.villageFocus==='bulletin').focused,true);
 assert.equal(stack.get('panel').onBack(),undefined,'a further Back closes the restored rows normally');
 assert.equal(h.bodyClasses.has('panel-open'),false);
});
test('Dasha and rooster are visible residents with take and deliver actions',async()=>{
 const h=setup();h.S.catalog.market.village_quests={'Лиса Даша':{item:'carrot',qty:2,coins:12,xp:4,title:'Морковка для тайника'},'Петух Олег':{item:'wheat',qty:4,coins:12,xp:4,title:'Завтрак перед рассветом'}};
 h.S.me.village_errands={quests:{}};h.S.me.inventory.carrot=2;h.S.me.inventory.wheat=4;
 h.ctx.selectTab('village');
 assert.deepEqual(AC(h).children.filter(n=>n.dataset.villageNpc).map(n=>n.dataset.villageNpc).slice(-2),['Лиса Даша','Петух Олег']);
 h.ctx.chooseVillageResident('Лиса Даша');const panel=new Node('div');h.ctx.renderVillageResident(panel);
 assert.ok(panel.querySelectorAll('*').some(n=>n.textContent==='Играть с Дашей'));
 const take=panel.querySelectorAll('*').find(n=>n.textContent==='Взять задание');assert.ok(take);await take.onclick();
 assert.equal(h.calls.at(-1)[0],'village_quest');assert.equal(h.calls.at(-1)[1].npc,'Лиса Даша');
 h.S.busy=false;h.S.me.village_errands.quests['Лиса Даша']='active';const active=new Node('div');h.ctx.renderVillageResident(active);
 const deliver=active.querySelectorAll('*').find(n=>n.textContent==='Сдать задание');assert.ok(deliver);assert.equal(deliver.disabled,false);await deliver.onclick();
 assert.equal(h.calls.at(-1)[1].action,'deliver');
 h.S.busy=false;h.ctx.chooseVillageResident('Петух Олег');const rooster=new Node('div');h.ctx.renderVillageResident(rooster);
 assert.ok(rooster.querySelectorAll('*').some(n=>n.textContent==='Взять задание'));
});
test('Dasha game action remains available for an active wager and calls the game handler',()=>{
 const h=setup();
 h.S.me.village_errands={quests:{}};h.S.me.wager={eligible:false,reason:'active',active:{id:'round-1',stake:10,payout:27}};
 const panel=new Node('div');h.ctx.appendDashaAction(panel);
 const play=panel.querySelectorAll('*').find(n=>n.textContent==='Играть с Дашей');assert.ok(play);play.onclick();
 assert.ok(h.calls.includes('open-dasha'),'existing active round opens even when new-round eligibility is false');
});
test('Oleg chime action shows the saved run or the daily reward and opens the game',()=>{
 const h=setup();
 h.S.me.oleg_game={active:{run_id:'run-1',round:1,rounds:3,notes:4,sequence:[0,1,2,3]},rewarded_today:false,next_reward:{coins:12,xp:4},rounds:[3,4,5],last_result:null};
 const panel=new Node('div');h.ctx.appendOlegAction(panel);
 const play=panel.querySelectorAll('*').find(n=>n.textContent==='Сыграть с Олегом');assert.ok(play);
 assert.ok(panel.querySelectorAll('*').some(n=>/мелодия 2 из 3/.test(n.tagName||'')));
 play.onclick();assert.ok(h.calls.includes('open-oleg'));
 h.S.me.oleg_game={...h.S.me.oleg_game,active:null,rewarded_today:true};
 const done=new Node('div');h.ctx.appendOlegAction(done);
 assert.ok(done.querySelectorAll('*').some(n=>/сегодня получена/.test(n.tagName||'')));
});
test('presence uses one server lease, Dasha tap talks before walking, and leaving clears it',async()=>{
 const h=setup(),requests=[],listeners={},timers=[];let releaseEnter;
 h.S.catalog.market.village_quests={'Лиса Даша':{item:'carrot',qty:2,coins:12,xp:4,title:'Морковка для тайника'}};
 h.ctx.crypto={randomUUID:()=> '11111111-1111-4111-8111-111111111111'};
 h.ctx.API='/api/farm/v1';
 h.ctx.document.hidden=false;h.ctx.document.addEventListener=(name,fn)=>listeners[name]=fn;
 h.ctx.setInterval=fn=>{timers.push(fn);return 1;};h.ctx.clearInterval=id=>timers.push(`clear:${id}`);
 h.ctx.request=(path,options)=>{requests.push({path,...options});return options.data.action==='enter'?new Promise(resolve=>releaseEnter=resolve):Promise.resolve({stolen:0});};
 h.ctx.selectTab('village');assert.equal(requests[0].data.action,'enter');
 const fox=AC(h).children.find(n=>n.dataset.villageNpc==='Лиса Даша');fox.onclick({detail:1});
 assert.equal(requests.length,1,'tap waits for pending enter before talk');
 releaseEnter({stolen:0});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(requests[1]?.data.action,'talk',JSON.stringify({requests,session:vm.runInContext('villageSession',h.ctx),pending:vm.runInContext('villageTalkPending',h.ctx),tab:h.S.tab}));assert.deepEqual(Object.keys(requests[1].data).sort(),['action','session']);
 timers[0]();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(requests.length,2,'talked visit does not keep pulsing');
 h.ctx.exitVillage();assert.equal(requests.at(-1).data.action,'leave');assert.ok(timers.includes('clear:1'));
});
test('hidden tab stops presence and resuming creates a fresh session',async()=>{
 const h=setup(),actions=[],listeners={};let id=0;
 h.ctx.crypto={randomUUID:()=>`11111111-1111-4111-8111-${String(++id).padStart(12,'0')}`};
 h.ctx.API='/api/farm/v1';h.ctx.document.hidden=false;h.ctx.document.addEventListener=(name,fn)=>(listeners[name]||=[]).push(fn);
 h.ctx.setInterval=()=>1;h.ctx.clearInterval=()=>{};
 h.ctx.request=async(path,{data})=>{actions.push(data);return {stolen:0};};
 h.ctx.selectTab('village');h.nodes.get('village-scene').classList.toggle=()=>{};await new Promise(resolve=>setImmediate(resolve));
 h.ctx.document.hidden=true;listeners.visibilitychange.forEach(fn=>fn());await new Promise(resolve=>setImmediate(resolve));
 assert.equal(actions.at(-1).action,'leave');
 h.ctx.document.hidden=false;listeners.visibilitychange.forEach(fn=>fn());await new Promise(resolve=>setImmediate(resolve));
 assert.equal(actions.at(-1).action,'enter');assert.notEqual(actions[0].session,actions.at(-1).session);
 h.ctx.exitVillage();
});
test('Farm return card shows its in-app caption and routes from a neighbor or Village',()=>{
 const h=setup(),start=source.indexOf('function addDestinationCard('),end=source.indexOf('\naddDestinationCard(',start),cards=[];
 const ctx={button:(text,run,cls)=>{const n=new Node('button');n.onclick=run;n.className=cls;return n;},headerCardArt:()=>new Node('svg'),el:(tag,text,cls)=>{const n=new Node(tag);n.textContent=text;n.className=cls;return n;},$:()=>({before:n=>cards.push(n)})};
 vm.createContext(ctx);vm.runInContext(source.slice(start,end),ctx);ctx.addDestinationCard({id:'farm-card-door',label:'Ферма',art:'',run:h.ctx.returnToFarm});
 assert.equal(cards.length,1);assert.equal(cards[0].dataset.label,'Ферма');assert.equal(cards[0].attrs['aria-label'],'Ферма');assert.equal(cards[0].title,undefined);
 h.S.farm={id:'neighbor',is_owner:false};h.S.tab='neighbors';cards[0].onclick();assert.equal(h.calls.at(-1),'back-home');
 h.calls.length=0;h.S.farm=h.S.me;h.S.tab='village';h.bodyClasses.add('village-open');cards[0].onclick();assert.equal(h.S.tab,'orders');assert.equal(h.calls.includes('back-home'),false);assert.equal(h.bodyClasses.has('panel-open'),false);
});
test('one real request delivers through the existing order command, a busy repeat does not',async()=>{
 const h=setup();h.S.tab='village';h.ctx.chooseVillageResident('Филиныч');assert.equal(await h.ctx.deliverVillageOrder('one'),true);assert.equal(await h.ctx.deliverVillageOrder('one'),false);
 assert.equal(h.calls.length,1);assert.equal(h.calls[0][0],'order');assert.equal(h.calls[0][1].order,'one');
});
test('absent order and insufficient own goods never submit a command',async()=>{
 const h=setup();h.S.tab='village';h.ctx.chooseVillageResident('Филиныч');assert.equal(await h.ctx.deliverVillageOrder('missing'),false);h.S.me.inventory.tea=1;assert.equal(await h.ctx.deliverVillageOrder('one'),false);h.ctx.chooseVillageResident('Агата');assert.equal(h.ctx.villageOrders('Агата').length,0);assert.equal(h.calls.length,0);
});
test('season is locked without owner projection and stages use shared total only',()=>{
 const h=setup();h.S.village={total:1000,goal:1000};assert.equal(h.ctx.villageStage(),null);h.ctx.openFund=true;
 for(const [total,expected]of [[0,0],[250,1],[600,2],[1000,3]]){h.S.village.total=total;assert.equal(h.ctx.villageStage(),expected);}h.S.village=null;assert.equal(h.ctx.villageStage(),null);
});
test('scene does not rebuild on identical refresh; pause remains owned by village or field game',()=>{
 const h=setup();h.S.tab='village';h.ctx.syncVillageScene();const root=h.nodes.get('village-scene'),act=AC(h);assert.equal(root.replaces,1);assert.equal(act.replaces,1);assert.equal(h.pause.at(-1),true);h.ctx.syncVillageScene();assert.equal(act.replaces,1);
 h.ctx.chooseVillageResident('Агата');assert.equal(root.replaces,1,'world image and effects are never rebuilt');assert.equal(act.replaces,2);h.ctx.syncVillageScene();assert.equal(act.replaces,2);
 h.S.tab='fields';h.S.fieldGame={};h.ctx.syncVillageScene();assert.equal(root.hidden,true);assert.equal(h.pause.at(-1),true);h.S.fieldGame=null;h.ctx.syncScenePause();assert.equal(h.pause.at(-1),false);
});
test('all eleven residents are native buttons with full-body art and preserve selection on refresh',()=>{
 const h=setup();h.S.tab='village';
 for(const name of Object.keys(figures))h.S.catalog.market.tastes[name]=[];
 h.ctx.syncVillageScene();h.ctx.chooseVillageResident('Агата');h.S.me.orders.push({id:'two',npc:'Агата'});h.ctx.syncVillageScene();
 const residents=AC(h).children.filter(n=>n.dataset.villageNpc);assert.equal(residents.length,11);
 for(const button of residents){
  const name=button.dataset.villageNpc,[[x,y],art]=figures[name];
  assert.equal(button.tagName,'button');assert.equal(button.attrs['aria-controls'],'panel-content');
  assert.equal(button.dataset.residentMode,'roaming');assert.equal(button.children[0].innerHTML,art);
  assert.equal(button.style.left,`${x/24}%`);assert.equal(button.style.top,`${y/18}%`);
  assert.ok(Number.isFinite(button.style['--resident-dx']));assert.ok(Number.isFinite(button.style['--resident-dy']));
 }
 const agata=residents.find(n=>n.dataset.villageNpc==='Агата');
 assert.equal(agata.attrs['aria-pressed'],'true');assert.match(agata.attrs['aria-label'],/есть просьба/);
});

test('panel refresh retains focused service, open section and scroll position',()=>{
 const h=setup();h.ctx.openVillageTownHall();h.S.lastRenderedTab='village';h.S.lastRenderedVillageSheet=JSON.stringify(['townhall',null]);
 const oldService=new Node('details');oldService.dataset.villageService='Фонд и праздник';oldService.open=true;
 const oldFocus=new Node('summary');oldFocus.dataset.villageFocus='service:Фонд и праздник';h.ctx.document.activeElement=oldFocus;
 const panel=new Node('div');panel.services=[oldService];panel.focuses=[];
 let scroll=123;
 // Browsers clamp scrollTop to the shorter content when details are closed.
 // Opening them later cannot restore the position that was already discarded.
 Object.defineProperty(panel,'scrollTop',{get:()=>scroll,set:value=>{scroll=Math.min(value,panel.services.some(n=>n.open)?500:20);}});
 panel.querySelectorAll=selector=>selector==='.village-services[open]'?panel.services.filter(n=>n.open):selector==='.village-services'?panel.services:panel.focuses;
 panel.querySelector=()=>null;h.nodes.set('panel-content',panel);
 h.ctx.own=()=>true;h.ctx.panelSnapshot=()=>'';h.ctx.panelRenderSignature='';
 for(const name of ['renderOrders','renderInventory','renderLand','renderCatalog','renderProduction','renderNeighbors','renderJournal','renderSettings','renderObject','renderObjects','renderTeam','renderForest','renderSecrets','renderFields'])h.ctx[name]=()=>{};
 h.ctx.renderVillage=()=>{const next=new Node('details');next.dataset.villageService='Фонд и праздник';panel.services=[next];const focus=new Node('summary');focus.dataset.villageFocus='service:Фонд и праздник';panel.focuses=[focus];};
 const code=source.slice(source.indexOf('function renderPanel()'),source.indexOf('/* ---- building upgrades'));
 vm.runInContext(code+'\nthis.renderPanel=renderPanel',h.ctx);h.ctx.renderPanel();
 assert.equal(panel.services[0].open,true);assert.equal(panel.focuses[0].focused,true);assert.equal(panel.scrollTop,123);
 vm.runInContext("villageSheet='resident';villageResident='Филиныч'",h.ctx);h.ctx.renderPanel();assert.equal(panel.scrollTop,0,'a newly selected resident starts at the top instead of inheriting town hall scroll');panel.scrollTop=123;h.ctx.renderPanel();assert.equal(panel.scrollTop,123,'refresh of the same resident preserves scroll');
});


test('resident tap opens a sheet; close returns focus to the place and stays in village',()=>{
 const h=setup();h.ctx.selectTab('village');h.ctx.chooseVillageResident('Филиныч');assert.equal(h.bodyClasses.has('panel-open'),true);assert.equal(h.sheetFocus.focused,true);
 h.ctx.closePanel();assert.equal(h.S.tab,'village');assert.equal(h.bodyClasses.has('panel-open'),false);assert.equal(h.pause.at(-1),true);
 const resident=AC(h).children.find(n=>n.dataset.villageNpc==='Филиныч');assert.equal(resident.focused,true);assert.equal(resident.attrs['aria-pressed'],'false');
 h.ctx.exitVillage();assert.equal(h.S.tab,'orders');assert.equal(h.pause.at(-1),false);assert.equal(h.nodes.get('farm-canvas').inert,false);
});
test('town hall opens services without implicitly selecting a resident',()=>{
 const h=setup();h.ctx.selectTab('village');h.ctx.openVillageTownHall();assert.equal(h.bodyClasses.has('panel-open'),true);assert.equal(h.title.focused,true);assert.equal(h.title.tabIndex,-1);
 const world=AC(h);assert.equal(world.children.find(n=>n.dataset.villageTownhall).attrs['aria-pressed'],'true');assert.equal(world.children.filter(n=>n.dataset.villageNpc&&n.attrs['aria-pressed']==='true').length,0);
 h.ctx.closePanel();assert.equal(h.S.tab,'village');assert.ok(world.children.length>0);assert.equal(AC(h).children.find(n=>n.dataset.villageTownhall).focused,true);
});
test('village artwork is a large external SVG world served by allowlist and scrolls inside the scene',()=>{
 const svg=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/village.svg'),'utf8');assert.match(svg,/viewBox="0 0 2400 1800"/);assert.match(svg,/preserveAspectRatio="xMidYMid meet"/);
 const api=fs.readFileSync(path.join(__dirname,'../../qw_farm/api.py'),'utf8');assert.match(api,/ASSETS=.*'village.svg'/);
 const css=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/style.css'),'utf8');assert.match(css,/\.village-scene\{[^}]*overflow:auto/);assert.match(css,/\.village-world\{--village-width:clamp\(1600px,250cqw,3200px\);[^}]*width:var\(--village-width\);aspect-ratio:4\/3/);assert.match(css,/object-fit:contain/);
 assert.doesNotMatch(css,/\.village-scene\{[^}]*overflow-x:hidden/);
});

test('login and new account reset the old resident, sheet and scene state',()=>{
 const h=setup();h.ctx.selectTab('village');h.ctx.chooseVillageResident('Филиныч');h.S.me=null;h.ctx.resetVillageView();assert.equal(h.bodyClasses.has('village-open'),false);assert.equal(h.nodes.get('village-scene').hidden,true);assert.equal(h.pause.at(-1),false);
 h.S.me={id:'another',orders:[],inventory:{},market:{}};h.ctx.resetVillageView();const world=AC(h);assert.equal(world.children.filter(n=>n.dataset.villageNpc&&n.attrs['aria-pressed']==='true').length,0);assert.equal(world.children.find(n=>n.dataset.villageTownhall).attrs['aria-pressed'],'false');
 const logout=source.slice(source.indexOf('function showLogin('),source.indexOf('function showRecovery('));assert.match(logout,/S\.me=S\.farm=null[\s\S]*resetVillageView\(\)/);
});

test('placing town hall decor returns to the farm before entering placement mode',()=>{
 const h=setup();h.ctx.selectTab('village');h.ctx.openVillageTownHall();h.ctx.renderPlacement=()=>{};
 const start=source.indexOf('const decorGiftQty='),end=source.indexOf('function cancelPlacement(',start);
 vm.runInContext(source.slice(start,end)+'\nthis.beginPlacement=beginPlacement',h.ctx);const spec={id:'flowerbed',w:1,h:1};h.ctx.beginPlacement(spec);
 assert.equal(h.S.tab,'orders');assert.equal(h.pause.at(-1),false);assert.equal(h.S.placing.spec,spec);assert.equal(h.nodes.get('farm-canvas').inert,false);
});
test('debt shortcut opens town hall services and all eleven resident positions exist',()=>{
 const h=setup();h.S.farm=h.S.me;h.ctx.eco=()=>({debt:50});
 const start=source.indexOf('function hudDebt()'),end=source.indexOf('\n',start);
 vm.runInContext(source.slice(start,end)+'\nthis.hudDebt=hudDebt;this.spotCount=Object.keys(VILLAGE_SPOTS).length',h.ctx);
 h.ctx.hudDebt().onclick();assert.equal(h.S.tab,'village');assert.equal(h.bodyClasses.has('panel-open'),true);assert.equal(h.title.focused,true);assert.equal(h.ctx.spotCount,11);
});

test('world keeps 44px targets without overlap at phone and desktop widths; walking and HUD exist',()=>{
 const h=setup();const positions=Object.values(figures).map(([[x,y]])=>[x/24,y/18]),hallPos=vm.runInContext('VILLAGE_HALL',h.ctx),board=vm.runInContext('VILLAGE_GATE_BOARD',h.ctx);
 for(const availableWidth of [320,360,390,430,1280,1920]){
  const width=Math.min(3200,Math.max(1600,availableWidth*2.5)),height=width*.75;
  const targets=positions.map(([x,y])=>({x:x*width/100,y:y*height/100-25.56,w:48,h:60}));targets.push({x:hallPos[0]/100*width,y:hallPos[1]/100*height,w:62,h:44});targets.push({x:board[0]/100*width,y:board[1]/100*height,w:board[2]/100*width,h:board[3]/100*height});
  for(const t of targets){assert.ok(t.x-t.w/2>=0&&t.x+t.w/2<=width);assert.ok(t.y-t.h/2>=0&&t.y+t.h/2<=height);assert.ok(t.w>=44&&t.h>=44);}
  for(let i=0;i<targets.length;i++)for(let j=i+1;j<targets.length;j++){const a=targets[i],b=targets[j];assert.ok(Math.abs(a.x-b.x)>=(a.w+b.w)/2||Math.abs(a.y-b.y)>=(a.h+b.h)/2,`targets ${i}/${j} overlap at ${availableWidth}`);}
 }
 h.S.tab='village';h.ctx.syncVillageScene();const world=AC(h);
 const wr=h.nodes.get('village-scene').children[0];assert.ok(wr.children.find(n=>n.dataset.villageGate),'gate button to the farm');assert.ok(wr.children.find(n=>n.className==='village-player'),'player figure');assert.ok(wr.children.find(n=>n.className==='village-fx'),'separate animated effects layer');
 const hud=h.nodes.get('village-hud');assert.ok(hud.children.find(n=>n.dataset.villageMinimap),'minimap');assert.equal(hud.hidden,false);
 h.S.tab='orders';h.ctx.syncVillageScene();assert.equal(hud.hidden,true);
 const css=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/style.css'),'utf8');assert.match(css,/prefers-reduced-motion:no-preference\)\{\s*\.village-walker\{animation/);
});
test('drawn farm sign is the only native exit target and keyboard activation uses the existing route',()=>{
 const h=setup();h.S.tab='village';h.ctx.syncVillageScene();
 const world=h.nodes.get('village-scene').children[0],gates=world.children.filter(n=>n.dataset.villageGate),gate=gates[0],board=vm.runInContext('VILLAGE_GATE_BOARD',h.ctx);
 assert.equal(gates.length,1);assert.equal(gate.tagName,'button');assert.equal(gate.attrs['aria-label'],'На ферму: ворота деревни');assert.equal(gate.children.length,0);assert.match(gate.innerHTML,/<svg class="vg-sign"/);assert.match(gate.innerHTML,/>Ферма<\/text>/,'the sign board is drawn inside the button');assert.doesNotMatch(fs.readFileSync(path.join(__dirname,'../../qw_farm/static/village.svg'),'utf8').slice(-4000),/На ферму|<text/,'village.svg no longer draws a second board');
 assert.equal(gate.style.left,`${board[0]}%`);assert.equal(gate.style.top,`${board[1]}%`);assert.equal(gate.style.width,`${board[2]}%`);assert.equal(gate.style.height,`${board[3]}%`);
 const left=(board[0]-board[2]/2)*24,right=(board[0]+board[2]/2)*24,top=(board[1]-board[3]/2)*18,bottom=(board[1]+board[3]/2)*18;
 const hit=gate.innerHTML.match(/class="vg-hit" d="M([^"]+)Z"/)[1].split('L').map(p=>p.split(' ').map(Number));assert.equal(hit.length,4);
 for(const [x,y] of hit)assert.ok(x>=left-.5&&x<=right+.5&&y>=top-.5&&y<=bottom+.5,'the board-shaped hit area fits the button box');
 const css=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/style.css'),'utf8');assert.match(css,/\.village-gate\{[^}]*min-width:44px;min-height:44px/);assert.match(css,/\.village-gate\{[^}]*background:transparent/);assert.match(css,/\.village-gate:focus-visible\{/);
 gate.onclick({detail:0});assert.equal(h.S.tab,'orders');
});
test('keyboard activation opens a resident at once, mouse click walks first and then opens',()=>{
 const h=setup();h.S.tab='village';h.ctx.syncVillageScene();
 const npc=()=>AC(h).children.find(n=>n.dataset.villageNpc==='Филиныч');
 npc().onclick({detail:0});assert.equal(vm.runInContext('villageResident',h.ctx),'Филиныч');
 vm.runInContext("villageResident=null;villageSheet=null;villageSceneSignature=''",h.ctx);h.ctx.syncVillageScene();
 npc().onclick({detail:1});assert.equal(vm.runInContext('villageResident',h.ctx),'Филиныч');
});
test('daily guests follow the date only, differ from each other, and place signs never cover residents',()=>{
 const h=setup();const today=vm.runInContext('villageVisitorsToday',h.ctx);
 for(let d=0;d<30;d++){const t=Date.UTC(2026,9,1+d,9),a=today(t),b=today(t+5*3600e3);assert.deepEqual(a.map(x=>x.v[0]),b.map(x=>x.v[0]),'same Moscow day, same guests');assert.notEqual(a[0].v[0],a[1].v[0]);assert.notDeepEqual(a[0].spot,a[1].spot);}
 const spots=Object.values(figures).map(([[x,y]])=>({x:x/24,y:y/18,w:48,h:60,footOffset:25.56}));const places=vm.runInContext('VILLAGE_PLACES',h.ctx).map(p=>({x:p[3],y:p[4],w:44,h:44}));const guests=vm.runInContext('VILLAGE_VISITOR_SPOTS',h.ctx).map(([x,y])=>({x,y,w:48,h:48}));const hall=vm.runInContext('VILLAGE_HALL',h.ctx),board=vm.runInContext('VILLAGE_GATE_BOARD',h.ctx);
 const all=[...spots,...places,...guests,{x:hall[0],y:hall[1],w:62,h:44}];
 for(const width of [1600,3200]){const height=width*.75,T=all.map(t=>({x:t.x*width/100,y:t.y*height/100-(t.footOffset||0),w:t.w,h:t.h}));T.push({x:board[0]*width/100,y:board[1]*height/100,w:board[2]*width/100,h:board[3]*height/100});
  for(let i=0;i<T.length;i++)for(let j=i+1;j<T.length;j++){const a=T[i],b=T[j];assert.ok(Math.abs(a.x-b.x)>=(a.w+b.w)/2||Math.abs(a.y-b.y)>=(a.h+b.h)/2,`targets ${i}/${j} overlap at ${width}`);}}
});
test('easter-egg guests are extra, rare, deterministic and complete',()=>{
 const h=setup();const today=vm.runInContext('villageVisitorsToday',h.ctx),eggs=vm.runInContext('VILLAGE_EGGS',h.ctx),base=vm.runInContext('VILLAGE_VISITORS',h.ctx);
 const ids=[...base,...eggs].map(v=>v[0]);assert.equal(new Set(ids).size,ids.length,'ids unique');
 const tabs=new Set(['orders','inventory','catalog','production','forest','lake','neighbors','secrets','journal']);
 for(const v of eggs){assert.ok(v[1]&&v[2]&&v[3].length>20&&v[4],`${v[0]} has text`);assert.ok(tabs.has(v[5]),`${v[0]} leads to existing tab`);}
 let withEgg=0;const seen=new Set();
 for(let d=0;d<120;d++){const t=Date.UTC(2026,9,1+d,9),a=today(t),b=today(t+5*3600e3);assert.deepEqual(a.map(x=>x.v[0]),b.map(x=>x.v[0]));assert.ok(a.length<=3);assert.ok(a.slice(0,2).every(x=>base.includes(x.v)),'daily guests unchanged');
  if(a.length===3){withEgg++;seen.add(a[2].v[0]);assert.ok(eggs.includes(a[2].v));assert.equal(new Set(a.map(x=>x.spot.join())).size,3,'distinct spots');}}
 assert.ok(withEgg>=15&&withEgg<=40,'egg guests are rare: '+withEgg);assert.equal(seen.size,eggs.length,'every egg appears');
});

test('countdown text never shows 60 minutes and drops zero minutes',()=>{
 const m=source.match(/const timeText=.*\n/),s=source.match(/const seedTimeText=.*\n/);assert.ok(m&&s);
 const c={};vm.createContext(c);vm.runInContext(`${m[0]}${s[0]}globalThis.t=timeText;globalThis.s=seedTimeText;`,c);
 const expected={0:'0 с',59:'59 с',60:'1 мин',61:'2 мин',3599:'1 ч',3600:'1 ч',3601:'1 ч 1 мин',7140:'1 ч 59 мин',7199:'2 ч',7200:'2 ч',7201:'2 ч 1 мин'};
 for(const [sec,text] of Object.entries(expected))assert.equal(c.t(Number(sec)),text,String(sec));
 assert.equal(c.s(3601),'1ч 1м');assert.equal(c.s(7200),'2ч');assert.equal(c.s(59),'59с');
 for(let sec=0;sec<20000;sec+=7)assert.doesNotMatch(c.t(sec),/(^|\D)60 мин/,String(sec));
});
test('a failed talk request releases the talk lock so presence pings resume; success keeps it',async()=>{
 for(const fail of [true,false]){
  const h=setup(),requests=[],timers=[];
  h.ctx.crypto={randomUUID:()=> '11111111-1111-4111-8111-111111111111'};h.ctx.API='/api/farm/v1';
  h.ctx.document.hidden=false;h.ctx.document.addEventListener=()=>{};h.ctx.setInterval=fn=>{timers.push(fn);return 1;};h.ctx.clearInterval=()=>{};
  h.ctx.request=async(path,{data})=>{requests.push(data.action);if(data.action==='talk'&&fail)throw new Error('offline');return {stolen:0};};
  h.ctx.selectTab('village');await new Promise(r=>setImmediate(r));
  vm.runInContext('villagePresenceTalk()',h.ctx);await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
  assert.equal(requests.includes('talk'),true);
  assert.equal(vm.runInContext('villageTalkPending',h.ctx),!fail);
  timers[0]();await new Promise(r=>setImmediate(r));
  assert.equal(requests.filter(a=>a==='pulse').length,fail?1:0,fail?'pulse resumes after failed talk':'talked visit stays quiet');
 }
});
test('the Dasha theft warning shows once on village entry only while theft is possible',()=>{
 const run=(mut)=>{const h=setup(),toasts=[];h.ctx.toast=t=>toasts.push(t);h.ctx.now=()=>1000;
  h.ctx.crypto={randomUUID:()=> '11111111-1111-4111-8111-111111111111'};h.ctx.API='/api/farm/v1';h.ctx.document.hidden=false;h.ctx.document.addEventListener=()=>{};h.ctx.setInterval=()=>1;h.ctx.clearInterval=()=>{};h.ctx.request=async()=>({stolen:0});
  h.S.me.coins=50;h.S.me.village_errands={quests:{},theft_next_at:0,theft_total:0};mut(h);h.ctx.selectTab('village');return toasts;};
 assert.equal(run(()=>{}).filter(t=>/Даша.*стащить/.test(t)).length,1);
 assert.equal(run(h=>{h.S.me.village_errands.theft_next_at=5000;}).length,0,'cooldown: no warning');
 assert.equal(run(h=>{h.S.me.coins=0;}).length,0,'empty pocket: nothing to steal');
 assert.equal(run(h=>{h.S.me.is_owner=false;}).length,0);
 assert.doesNotMatch(source.slice(source.indexOf('function renderVillageResident'),source.indexOf('function renderVillage(p)')),/стащить/,'the useless card-only warning is gone');
});
test('a disabled errand delivery says what is missing',()=>{
 const h=setup();h.S.catalog.market.village_quests={'Лиса Даша':{item:'carrot',qty:3,coins:12,xp:4,title:'Морковка'}};
 h.S.catalog.items={carrot:{name:'Морковь'}};h.ctx.itemName=id=>h.S.catalog.items[id]?.name||id;h.ctx.stock=id=>h.S.me.inventory[id]||0;
 h.S.me.village_errands={quests:{'Лиса Даша':'active'}};h.S.me.inventory={carrot:1};
 h.ctx.selectTab('village');h.ctx.chooseVillageResident('Лиса Даша');const p=new Node('div');h.ctx.renderVillageResident(p);
 const all=p.querySelectorAll('*'),deliver=all.find(n=>n.textContent==='Сдать задание');
 assert.equal(deliver.disabled,true);assert.ok(all.some(n=>/Не хватает: Морковь ×2/.test(n.textContent||n.tagName)),all.map(n=>n.textContent).join('|'));
});
test('static targets stack above wandering residents and their approach routes remain clear',()=>{
 const css=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/style.css'),'utf8');
 const z=re=>Number((css.match(re)||[])[1]);
 const zNpc=z(/\.village-npc,\.village-townhall\{[^}]*?z-index:(\d+)/),zNpcSel=z(/\.village-npc\[aria-pressed=true\]\{z-index:(\d+)/),zPlaces=z(/\.village-places\{[^}]*?z-index:(\d+)/),zGate=z(/\.village-gate\{[^}]*?z-index:(\d+)/),zSign=z(/\.village-place\{z-index:(\d+)/),zGuest=z(/\.village-visitor\{z-index:(\d+)/);
 for(const v of [zNpc,zNpcSel,zPlaces,zGate,zSign,zGuest])assert.ok(Number.isFinite(v),'z-index parsed');
 assert.ok(zPlaces>Math.max(zNpc,zNpcSel),'place layer above every resident');assert.ok(zGate>Math.max(zNpc,zNpcSel),'gate above every resident');assert.ok(zSign>zGuest,'signs above wandering guests inside their layer');
 const {ctx}=setup(),W=1600,H=1200,scale=W/2400;
 const board=vm.runInContext('VILLAGE_GATE_BOARD',ctx),places=vm.runInContext('VILLAGE_PLACES',ctx);
 const targets=[{id:'gate',x:board[0]*W/100,y:board[1]*H/100,hw:Math.max(22,board[2]*W/200),hh:Math.max(22,board[3]*H/200)}].concat(places.map(p=>({id:p[0],x:p[3]*W/100,y:p[4]*H/100,hw:22,hh:22})));
 const graph=vm.runInContext('VILLAGE_WALK',ctx);
 for(const [npc,[[sx,sy]]] of Object.entries(figures)){
  const [dx,dy]=ctx.villageResidentDrift(npc,[sx,sy]);
  for(let k=0;k<=20;k++){
   const x=sx+dx*k/20,y=sy+dy*k/20,cx=x*scale,cy=y*scale-25.56;
   assert.ok(ctx.villageSnap(graph,x,y).d<4,`${npc} stays near the walk graph`);
   for(const t of targets)assert.ok(Math.abs(t.x-cx)>=24+t.hw+8||Math.abs(t.y-cy)>=30+t.hh+8,`${npc} crowds ${t.id}`);
  }
 }
});

test('construction leaves a gap between its workers and nearby buttons at phone scale',()=>{
 const {ctx}=setup(),scale=2/3;
 const resident=(name,[x,y])=>({name,x:x*scale,y:y*scale-25.56,hw:24,hh:30});
 const markers=(name,[x,y],hw,hh)=>({name,x:x*16,y:y*12,hw,hh});
 const oleg='Петух Олег',olegFoot=figures[oleg][0],olegDrift=ctx.villageResidentDrift(oleg,olegFoot);
 const targets=[
  markers('market',vm.runInContext("VILLAGE_PLACES.find(p=>p[0]==='market').slice(3,5)",ctx),22,22),
  markers('hall',vm.runInContext('VILLAGE_HALL',ctx),31,22),
  markers('guest',vm.runInContext('VILLAGE_VISITOR_SPOTS[1]',ctx),24,24),
  ...Array.from({length:11},(_,i)=>resident(oleg,olegFoot.map((x,j)=>x+olegDrift[j]*i/10))),
 ];
 const build=vm.runInContext('VILLAGE_BUILD',ctx);
 const sites=vm.runInContext('VILLAGE_SITES',ctx);
 const css=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/style.css'),'utf8');
 assert.match(css,/\.village-site\[data-working=true\]:not\(\[data-village-site=stalls\]\)\{margin-top:-86px\}/);
 for(const [site,feet] of Object.entries(build.crew)){
  const crew=feet.map((foot,i)=>resident(`worker ${i}`,foot));
  const plaques=sites.map(([id,,x,y])=>{
   const plate=markers(id,[x,id==='greenhouse'?23.8:y],70,29);
   plate.y+=7-(id===site&&id!=='stalls'?64:0);
   return plate;
  });
  for(const a of crew)for(const b of [...targets,...crew,...plaques]){
   if(a===b)continue;
   assert.ok(Math.abs(a.x-b.x)>=a.hw+b.hw+8||Math.abs(a.y-b.y)>=a.hh+b.hh+8,`${site}: ${a.name} crowds ${b.name}`);
  }
 }
});
