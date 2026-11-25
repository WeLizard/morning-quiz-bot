'use strict';
// «Битва с Сантой» screen (qw_farm/static/santa-battle.js): texts, steps of a move, basket, locks and the app wiring.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const root=path.resolve(__dirname,'../..');
const read=f=>fs.readFileSync(path.join(root,f),'utf8');
const strip=src=>src.replace(/^import [^;]*;\r?\n/gm,'').replace(/^export /gm,'');
const context={Math,Number,Array,Object,String,Boolean,JSON,Map,Set,Promise,Error,Date,setTimeout,clearTimeout};
vm.createContext(context);
vm.runInContext(`${strip(read('qw_farm/static/santa-battle-engine.js'))}\n${strip(read('qw_farm/static/santa-battle.js'))}
globalThis.api={newState,act,actor,legal,replay,intentText,intentLines,stepsOf,stepText,resultText,lockText,basketLeft,nameOf,playerLook,starsText,BASKET,MOVES,MOVE_HINTS,ITEM_HINTS,ATTACKS,SKILLS,ITEMS};`,context);
const api=context.api;
const fixtures=JSON.parse(read('tests/fixtures/farm_santa_battle.json'));
const plan3=fixtures.find(f=>f.plan.battle===3).plan;

test('every hero move, skill and basket item has a name and a hint',()=>{
 for(const id of [...Object.keys(api.ATTACKS),...Object.keys(api.SKILLS)]){assert.ok(api.MOVES[id],id);assert.ok(api.MOVE_HINTS[id],id);}
 assert.deepEqual([...api.BASKET].sort(),Object.keys(api.ITEMS).sort());
 for(const id of api.BASKET)assert.ok(api.ITEM_HINTS[id],id);
});

test('the player is the farmer or, for «она», the farmer woman',()=>{
 assert.equal(api.playerLook('f'),'f');
 for(const form of ['m','n',undefined])assert.equal(api.playerLook(form),'m');
 assert.equal(api.nameOf('player','m'),'Фермер');
 assert.equal(api.nameOf('player','f'),'Фермерша');
 assert.equal(api.nameOf('ded_moroz','f'),'Дед Мороз');
});

test('enemy intents are announced with the target in the dative',()=>{
 const s=api.newState(plan3),lines=api.intentLines(s,'f');
 assert.equal(lines.length,2);
 for(const line of lines)assert.match(line,/^(Крампус|Санта)/);
 assert.equal(api.intentText('krampus',{move:'switch',target:'player'},'f'),'Крампус: «Розги» по фермерше');
 assert.equal(api.intentText('santa',{move:'coal',target:'ded_moroz'},'m'),'Санта: «Подарок-сюрприз» — уголёк по Деду Морозу');
 assert.match(api.intentText('santa',{move:'hohoho',target:null}),/по всем/);
 // the reindeer rush is announced in battle 3 on every fourth round
 const r4={...s,round:4};assert.match(api.intentLines(r4).at(-1),/Олени/);
});

test('a move is played as steps: the hero, then every enemy move; texts carry the numbers',()=>{
 const s=api.newState(plan3);let all=[];
 // three plain attacks finish round 1 and run the enemy phase
 for(let i=0;i<3;i++){
  const hero=api.actor(s),[action,targets]=api.legal(s)[0],entry=[hero,action,targets[0],null];
  const steps=api.stepsOf(api.act(plan3,s,entry),entry);
  assert.equal(steps[0].who,hero);assert.equal(steps[0].move,action);
  all=all.concat(steps);
 }
 const moves=all.filter(st=>st.events[0]?.t==='move').map(st=>st.who);
 assert.ok(moves.includes('krampus')&&moves.includes('santa'),moves.join());
 assert.ok(all.some(st=>st.move==='round'));
 for(const st of all){const text=api.stepText(st,'f');assert.ok(text.length>3&&text.endsWith('.'),text);assert.doesNotMatch(text,/undefined|null/);}
 const hit=all.find(st=>st.who==='player');assert.match(api.stepText(hit,'m'),/^Фермер: «Снежок» · (Крампус|Санта) −\d+/);
});

test('item steps name the item and its receiver in the genitive',()=>{
 const step={who:'player',move:'pie',to:'snegurochka',events:[{t:'item',by:'player',item:'pie',to:'snegurochka'},{t:'heal',by:'player',to:'snegurochka',amount:30}]};
 assert.equal(api.stepText(step,'m',{pie:'Тыквенный пирог'}),'Фермер: Тыквенный пирог для Снегурочки · Снегурочка +30.');
});

test('results: win with stars and the reward, lose without loss, basket and expired',()=>{
 assert.equal(api.resultText({battle:3,outcome:'win',stars:2,rounds:12,items:{pie:1},reward:'fest_ny_santa_visit'},'Санта и Крампус в гостях'),
  'Победа в бою 3! ★★☆ за 12 р. Из «Корзинки» съедено: 1. Награда: «Санта и Крампус в гостях».');
 assert.match(api.resultText({battle:1,outcome:'lose',stars:0,rounds:7,items:{}}),/ничего не отнимает/);
 assert.match(api.resultText({outcome:'basket'}),/не засчитан, ничего не списано/);
 assert.match(api.resultText({outcome:'expired'}),/Время боя вышло/);
 assert.equal(api.starsText(1),'★☆☆ — 1 звезда');
});

test('locks: out of season, level, date, previous win',()=>{
 const fmt=()=>'25 декабря';
 assert.match(api.lockText({n:1,open:false},{available:false}),/Новый год/);
 assert.equal(api.lockText({n:1,open:true},{locked:true,minLevel:5}),'С 5 уровня.');
 assert.equal(api.lockText({n:2,open:false,opens_at:Date.now()/1000+3600},{},fmt),'Откроется 25 декабря.');
 assert.equal(api.lockText({n:3,open:false,opens_at:Date.now()/1000-3600},{},fmt),'После победы в бою 2.');
 assert.equal(api.lockText({n:2,open:true},{}),'');
});

test('basket: barn stock minus what this battle already used, nothing after three items',()=>{
 const s=api.newState(plan3),stock=id=>({pie:2,honey:1})[id]||0;
 assert.equal(api.basketLeft('pie',stock,s),2);
 s.items={pie:1};s.n_items=1;assert.equal(api.basketLeft('pie',stock,s),1);
 assert.equal(api.basketLeft('pancake',stock,s),0);
 s.n_items=3;assert.equal(api.basketLeft('honey',stock,s),0);
});

test('installed scenes have every fighter pose (both player looks), the effects and the stage',()=>{
 for(const file of ['santa-battle-scene.svg','santa-battle-night.svg']){
  const svg=read('qw_farm/static/'+file);
  assert.match(svg,/viewBox="0 0 1000 600"/);
  assert.ok(!/<image|data:image|<filter| style=/.test(svg),file);
  for(const who of ['player','player_f','ded_moroz','snegurochka','santa','krampus'])
   for(const pose of ['stand','attack','hurt','win','down'])assert.ok(svg.includes(`id="sb-${who}-${pose}"`),`${file} ${who}-${pose}`);
  for(const fx of ['snowball','hit','blizzard','icestar','coal','candy','gift','chain','switch','notes','heal','wall','freeze','rage','sleigh'])
   assert.ok(svg.includes(`id="sb-fx-${fx}"`),`${file} fx ${fx}`);
  assert.ok(svg.includes('id="sb-santa-hide"')&&svg.includes('<g id="sb-stage"></g>'));
  const anchors=JSON.parse(svg.match(/data-anchors='([^']+)'/)[1]);
  for(const who of ['player','ded_moroz','snegurochka','santa','krampus','solo'])assert.equal(anchors[who].length,2,who);
 }
});

test('wiring: served assets, page host, app view, festival card and the calm setting',()=>{
 const assets=read('qw_farm/api.py');
 for(const name of ['santa-battle.js','santa-battle.css','santa-battle-engine.js','santa-battle-scene.svg','santa-battle-night.svg'])assert.ok(assets.includes(`'${name}'`),name);
 const html=read('qw_farm/static/index.html');
 assert.ok(html.includes('/app/farm/assets/santa-battle.css'));
 assert.match(html,/<section id="santa-game-view" aria-label="Битва с Сантой" hidden><\/section>/);
 const app=read('qw_farm/static/app.js');
 assert.match(app,/import \{mountSantaBattle,calmBattle,playerLook,CALM_KEY\} from '\.\/santa-battle\.js(\?v=[\w.-]+)?';/);
 assert.match(app,/look:\(\)=>playerLook\(S\.form\)/);
 assert.match(app,/navPush\('santa-battle',closeSantaGame\)/);
 assert.match(app,/if\(santaGameOpen\)\{e\.preventDefault\(\);closeSantaGame\(\);return;\}/);
 assert.equal((app.match(/pieGame\?\.render\(\);santaGame\?\.render\(\);/g)||[]).length,2);
 assert.match(app,/santa:\(\)=>S\.me\?\.village_games\?\.santa_battle\|\|null,santaGame:\(\)=>openSantaGame\(\)/);
 assert.match(app,/checkbox\('Спокойный бой с Сантой: без полоски меткости',calmBattle\(\)\)/);
 const fest=read('qw_farm/static/festivals.js');
 assert.match(fest,/if\(cur\?\.id==='new_year'\)santaCard\(p,h\);/);
 assert.match(fest,/play\.dataset\.openSanta=''/);
 const css=read('qw_farm/static/santa-battle.css');
 const tail=css.slice(css.indexOf('/* Contrast mode'));
 for(const rule of tail.split('\n').slice(1).filter(Boolean))assert.match(rule,/^:root\[data-qw-contrast="1"\]/,rule);
 assert.match(css,/prefers-reduced-motion/);
});

test('village: the guests stand by the pond only while the New Year lasts and open the battle',()=>{
 const app=read('qw_farm/static/app.js'),css=read('qw_farm/static/santa-battle.css'),svg=read('qw_farm/static/santa-guests.svg');
 assert.match(app,/santaGuests=own\(\)&&!!S\.me\?\.village_games\?\.santa_battle\?\.available;/);
 assert.match(app,/const sig=JSON\.stringify\(\[S\.me\.id,stage,villageSheet,villageResident,jack,santaGuests,/,'the square redraws when the festival starts');
 assert.match(app,/if\(santaGuests\)\{\s*const guests=button\(null,e=>villageWalk\(\[1238\.26\/24,1174\.63\/18\],\(\)=>openSantaGame\(\),!e\.detail,'santa-guests'\),'village-santa-guests'\);/);
 assert.match(app,/art\.src='\/app\/farm\/assets\/santa-guests\.svg'/);
 assert.ok(read('qw_farm/api.py').includes("'santa-guests.svg'"));
 assert.match(css,/\.village-santa-guests\{[^}]*min-width:44px;min-height:44px/);
 assert.doesNotMatch(css,/\.village-santa-guests\{[^}]*translate/,'the box is the generator\'s, no transform');
 assert.match(svg,/^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg" class="ny-guests-art" viewBox="-72 -60 144 66"/);
 assert.ok(!/<image|data:image|<filter| style=/.test(svg));
});
