import './address.js';
import {mountDashaGame,dashaReasonText,localizeWagerNotice} from './dasha-game.js';
import {mountOlegGame} from './oleg-game.js';
import {FarmScene,farmLightingAt} from './scene.js';
import {CATEGORIES,CATEGORY_COLOR,categoryOf,swansLeft,readyInfo,listObjects,countByCategory,pushToast,expireToasts,toastText,wheelScrollDelta,buildingPurpose} from './scene_map.js';
import {openFieldGame,yieldQty,growthPermille} from './tractor_game.js';
import * as FEST from './festivals.js';
import * as MERCH from './merchant.js';
import * as ORCH from './orchard.js';
import {createFriendRequests} from './friend_requests.js';
import {createConstruction} from './construction.js';
import {openTripGame,canPlay,finalOutputs,bonusLine,quality as tripQuality,grams as tripGrams} from './trip_game.js';
import {CLASS_LABEL,LONG_HINT,seedStats,sortSeeds,planMachine,planRepeat,planTap,remember} from './farm_runs.js';
import {parseInvite,parseInviteHint,incomingInvite,clearInvite,openTelegram,shareLink,mailtoUrl} from './invite.js';
// The Telegram bridge (SDK, safe-area, fullscreen, BackButton, header colors) is the shared shell: window.QW from /app/shell/qw-shell.js.
const QW=globalThis.QW;
const inTelegram=()=>Boolean(QW?.isTelegram?.());
let lightingMode='auto',lightingTimer=null,chromeColor='';
try{const stored=localStorage.getItem('qw-farm.lighting');if(['auto','day','night'].includes(stored))lightingMode=stored;}catch{}
function updateFarmLighting(){
 const state=farmLightingAt(new Date(),lightingMode),dark=state.darkness>=.5,root=document.documentElement;
 root.dataset.farmTheme=dark?'night':'day';root.dataset.farmPhase=state.phase;
 root.style.colorScheme=dark?'dark':'light';
 const toggle=$('lighting-toggle'),labels={auto:'по времени',day:'всегда день',night:'всегда ночь'};
 if(toggle){toggle.dataset.mode=lightingMode;toggle.dataset.dark=String(dark);toggle.setAttribute('aria-label',`Свет: ${labels[lightingMode]}. Нажми, чтобы сменить режим`);toggle.title=`Свет: ${labels[lightingMode]}`;}
 const setting=$('farm-lighting-mode');if(setting)setting.value=lightingMode;
 const color=dark?'#172821':'#efeee4';
 document.querySelector('meta[name="theme-color"]')?.setAttribute('content',color);
 document.querySelector('meta[name="color-scheme"]')?.setAttribute('content',dark?'dark':'light');
 scene.setLighting(state);
 if(color!==chromeColor){chromeColor=color;try{QW?.configure({color});}catch{}}
}
function setLightingMode(value){
 lightingMode=['auto','day','night'].includes(value)?value:'auto';
 try{localStorage.setItem('qw-farm.lighting',lightingMode);}catch{}
 updateFarmLighting();
}
const $=id=>document.getElementById(id);
const S={form:'n',me:null,farm:null,catalog:null,tab:'orders',seed:'wheat',selected:null,config:null,speed:1,busy:false,pending:null,placing:null,find:{category:'all',ready:false},inv:{q:'',cat:'all',shop:'all'},lastRun:null};
function lastRunKey(id){return `qw-farm.lastRun.${id}`;}
function loadLastRun(id){try{const v=JSON.parse(localStorage.getItem(lastRunKey(id))||'null');return v&&typeof v==='object'&&['tractor','harvester'].includes(v.machine)?v:null;}catch{return null;}}
function rememberMachineCommand(payload){
 if(payload.kind!=='machine_run')return;
 const last=remember(S.me?.id===payload.actor?S.lastRun:loadLastRun(payload.actor),payload.data);
 try{localStorage.setItem(lastRunKey(payload.actor),JSON.stringify(last));}catch{}
 if(S.me?.id===payload.actor)S.lastRun=last;
}
let mode=new URLSearchParams(location.search).get('identity');
S.invite=incomingInvite();
try{document.body.classList.toggle('compact',localStorage.getItem('qw-farm.compact')!=='false');}catch{}
const API='/api/farm/v1';
// Account-level form of address (он / она / не указывать); unknown means neutral wording. See static/address.js.
const gf=(m,f,n)=>globalThis.QWAddress?globalThis.QWAddress.g(S.form,m,f,n):n;
const VILLAGE_VOICES={
 'Филиныч':['Рад знакомству! Хороший урожай начинается с маленькой грядки.','Твоя ферма радует глаз. Поможешь собрать угощения для соседей?','Тебе здесь всегда рады. Без твоего урожая наши посиделки уже не те!'],
 'Агата':['Заходи к столу! Я как раз подбираю продукты для нового рецепта.','С твоими продуктами даже простой обед получается праздничным.','Я уже поставила для тебя чашку. Сегодня снова готовим вместе?'],
 'Почтальон Ёж':['Письма доставлены! А вот за вкусностями пришлось зайти к тебе.','Твоя посылка всегда приходит вовремя. На тебя можно положиться!','У меня для тебя добрые вести. И место в сумке для нашего заказа!'],
 'Механик Крот':['Шестерёнки готовы. Теперь бы перекусить перед работой!','С твоей помощью мастерская работает как часы.','Заходи, друг! Лучшие идеи приходят после хорошего обеда.'],
 'Кошка Кая':['Я выбираю самые свежие продукты. Покажешь свой урожай?','Мне нравится твой вкус. У тебя всегда найдётся что-то особенное.','Я оставила тебе лучшее место на площади. Расскажешь, что вырастило хозяйство?'],
 'Кошка Соня':['Можно я ещё немного посплю? Только сначала погрею лапки о тёплый плед.','Узнаю твои шаги. Ради мягкого пледа и тёплых носков даже приятно просыпаться.','Для тебя я уже проснулась! Давай устроим тихий вечер: чай, одеяло и немного пряжи.'],
 'Суслик Игорь':['Запасы сами себя не соберут! Проверим, что сегодня на складе?','Вот это надёжный поставщик! С тобой моя кладовая не пустует.','Я припас для тебя добрые слова. А для кладовой — ещё одну просьбу!'],
 'Неведома Зверушка':['Из-за кустов кто-то любопытно смотрит на твой урожай…','Зверушка узнаёт тебя и смело выходит на площадь.','Зверушка радостно машет лапкой: ты теперь свой!'],
 'Медведь Пух':['Утро только началось, а мне уже мало бодрости! Найдётся у тебя что-нибудь на заряд?','С твоими зарядами я за день успеваю втрое больше! Давай ещё баночку-другую?','Для тебя у бочки всегда тёплое место. А для моей кружки — ещё один заказ!']
 ,'Лиса Даша':['Ой, это у тебя выпало? Я как раз искала морковку для своего тайника.','Ты меня поймал! Лучше принеси морковку сам — всё честно.','Карман проверил? Шучу. Почти.']
 ,'Петух Олег':['Ку-ка-ре-ку! До рассвета нужен завтрак для всей площади.','Спасибо за зерно! Завтра снова разбужу деревню.','Порядок в деревне начинается с хорошего утра!']
};
const VOICE_FORMS={'Заходи, друг!':['Заходи, подруга!','Заходи, не стесняйся!'],'Вот это надёжный поставщик!':['Вот это надёжная поставщица!','Вот это надёжные поставки!'],'ты теперь свой!':['ты теперь своя!','теперь ты в нашей компании!']};
const voiceFor=t=>{for(const[m,[f,n]]of Object.entries(VOICE_FORMS))if(t.includes(m))return t.replace(m,gf(m,f,n));return t;};
let merchantToastKey='',villageResident=null,villageSheet=null,villageSceneSignature='',villageVisitor=null,dashaGame=null,dashaGameOpen=false,olegGame=null,olegGameOpen=false;
let villageSession=null,villagePulseTimer=null,villagePresenceBound=false,villageEnterPending=null,villageTalkPending=false;
const VILLAGE_SPOTS={'Филиныч':[44.0,41.0],'Агата':[62.6,47.9],'Почтальон Ёж':[33.2,54.6],'Механик Крот':[72.7,57.0],'Кошка Кая':[24.8,44.6],'Кошка Соня':[55.6,59.2],'Суслик Игорь':[42.1,60.0],'Неведома Зверушка':[78.1,23.5],'Медведь Пух':[34.0,77.6],'Лиса Даша':[69.0,72.0],'Петух Олег':[49.0,32.0]};
// The world is 2400x1800 art units (village.svg, painted with the farm's own building code). Positions above are percentages of the world;
// each resident stands at the door of their own house. VILLAGE_C is the back corner of the plaza.
const VILLAGE_C=[1200,716],VILLAGE_START=[42,77.3],VILLAGE_GATE=[50,83.1],VILLAGE_HALL=[50.0,51.1];
// The «Ферма» gate: the arch (posts, beam, chains, lantern) is painted into village.svg and the board is this button, both by
// scripts/art/village (gate.js, farm sign style: FarmScene.signBoard in the arch plane, recorded as SVG). Generated markup, do not
// edit by hand: rebuild with build_village.py and copy out/gate_board.svg and manifest.gate_board.board_box. Day and night boards
// (CSS shows one); only the board's own shape (.vg-hit, 4 units of margin) takes taps. Box: centre x, y, width, height in % of the world.
const VILLAGE_GATE_BOARD=[50.021,80.167,3.625,4.333];
const VILLAGE_GATE_SIGN='<svg class="vg-sign" viewBox="1157 1404 87 78" aria-hidden="true" focusable="false"><g class="vg-day"><defs><linearGradient id="vgd0" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="26"><stop offset="0" stop-color="#f1dfb2"/><stop offset="1" stop-color="#dcc08c"/></linearGradient></defs><path d="M3 3L75 3L78 7L78 25L75 29L3 29L0 25L0 7Z" fill="#a58559" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><path d="M3 0L75 0L78 4L78 22L75 26L3 26L0 22L0 4Z" fill="url(#vgd0)" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><path d="M3 0L75 0L78 4L78 22L75 26L3 26L0 22L0 4Z" fill="none" stroke="#8d6c45" stroke-width="1.5" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><path d="M5 3.5L73 3.5" fill="none" stroke="#fff3cf" stroke-width="1" stroke-linecap="round" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><path d="M5 22.5L73 22.5" fill="none" stroke="#bd9a64" stroke-width="1" stroke-linecap="round" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><path d="M3.4 5A1.1 1.1 0 1 0 5.6 5A1.1 1.1 0 1 0 3.4 5Z" fill="#7a6240" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><path d="M72.4 5A1.1 1.1 0 1 0 74.6 5A1.1 1.1 0 1 0 72.4 5Z" fill="#7a6240" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><path d="M3.4 21A1.1 1.1 0 1 0 5.6 21A1.1 1.1 0 1 0 3.4 21Z" fill="#7a6240" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><path d="M72.4 21A1.1 1.1 0 1 0 74.6 21A1.1 1.1 0 1 0 72.4 21Z" fill="#7a6240" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><text x="33.6" y="19.56" font-weight="700" font-size="16" font-family="system-ui,-apple-system,&quot;Segoe UI&quot;,Roboto,sans-serif" text-anchor="middle" textLength="54" lengthAdjust="spacingAndGlyphs" fill="#fff0c6" transform="matrix(1 -0.5 0 1 1161.15 1449.32)">Ферма</text><text x="33" y="18.76" font-weight="700" font-size="16" font-family="system-ui,-apple-system,&quot;Segoe UI&quot;,Roboto,sans-serif" text-anchor="middle" textLength="54" lengthAdjust="spacingAndGlyphs" fill="#4d3c27" transform="matrix(1 -0.5 0 1 1161.15 1449.32)">Ферма</text><path d="M64 9L72 17" fill="none" stroke="#4d3c27" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><path d="M66.8 17L72 17L72 11.8" fill="none" stroke="#4d3c27" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/></g><g class="vg-night"><defs><linearGradient id="vgn0" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="26"><stop offset="0" stop-color="#dcc48f"/><stop offset="1" stop-color="#c3a676"/></linearGradient></defs><path d="M3 3L75 3L78 7L78 25L75 29L3 29L0 25L0 7Z" fill="#7d6240" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><path d="M3 0L75 0L78 4L78 22L75 26L3 26L0 22L0 4Z" fill="url(#vgn0)" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><path d="M3 0L75 0L78 4L78 22L75 26L3 26L0 22L0 4Z" fill="none" stroke="#8d6c45" stroke-width="1.5" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><path d="M5 3.5L73 3.5" fill="none" stroke="#fff3cf" stroke-width="1" stroke-linecap="round" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><path d="M5 22.5L73 22.5" fill="none" stroke="#bd9a64" stroke-width="1" stroke-linecap="round" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><path d="M3.4 5A1.1 1.1 0 1 0 5.6 5A1.1 1.1 0 1 0 3.4 5Z" fill="#7a6240" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><path d="M72.4 5A1.1 1.1 0 1 0 74.6 5A1.1 1.1 0 1 0 72.4 5Z" fill="#7a6240" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><path d="M3.4 21A1.1 1.1 0 1 0 5.6 21A1.1 1.1 0 1 0 3.4 21Z" fill="#7a6240" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><path d="M72.4 21A1.1 1.1 0 1 0 74.6 21A1.1 1.1 0 1 0 72.4 21Z" fill="#7a6240" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><text x="33.6" y="19.56" font-weight="700" font-size="16" font-family="system-ui,-apple-system,&quot;Segoe UI&quot;,Roboto,sans-serif" text-anchor="middle" textLength="54" lengthAdjust="spacingAndGlyphs" fill="#fff0c6" transform="matrix(1 -0.5 0 1 1161.15 1449.32)">Ферма</text><text x="33" y="18.76" font-weight="700" font-size="16" font-family="system-ui,-apple-system,&quot;Segoe UI&quot;,Roboto,sans-serif" text-anchor="middle" textLength="54" lengthAdjust="spacingAndGlyphs" fill="#2f2617" transform="matrix(1 -0.5 0 1 1161.15 1449.32)">Ферма</text><path d="M64 9L72 17" fill="none" stroke="#2f2617" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/><path d="M66.8 17L72 17L72 11.8" fill="none" stroke="#2f2617" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" transform="matrix(1 -0.5 0 1 1161.15 1449.32)"/></g><path class="vg-hit" d="M1157.15 1447.32L1243.15 1404.32L1243.15 1438.32L1157.15 1481.32Z" fill="transparent"/></svg>';
// The player's figure (scripts/art/village/player.js, generated: rebuild with build_village.py, copy out/player.svg): frames
// vp-stand / vp-stepA / vp-stepB facing right; style.css shows one and mirrors it for data-face=left.
const VILLAGE_PLAYER_SVG='<svg class="vp-art" viewBox="-17 -48 34 52" aria-hidden="true" focusable="false"><g class="vp-stand"><path d="M-8 0.6A9.5 3 0 1 0 11 0.6A9.5 3 0 1 0 -8 0.6Z" fill="#41623530"/><path d="M-1.6 -9L-2.8 -1.4" fill="none" stroke="#7fa3c4" stroke-width="4.2" stroke-linecap="round"/><path d="M-5.3 -1A2.9 1.7 0 1 0 0.5 -1A2.9 1.7 0 1 0 -5.3 -1Z" fill="#6f5a46"/><path d="M-4.6 -18.5L-6.6 -11.5" fill="none" stroke="#efdcb4" stroke-width="3.3" stroke-linecap="round"/><path d="M-8.5 -11A1.9 1.9 0 1 0 -4.7 -11A1.9 1.9 0 1 0 -8.5 -11Z" fill="#f3d3b0"/><path d="M-6.8 -17A6.8 6.6 0 1 0 6.8 -17A6.8 6.6 0 1 0 -6.8 -17Z" fill="#efdcb4"/><path d="M-7.4 -12.2A7.4 6.8 0 1 0 7.4 -12.2A7.4 6.8 0 1 0 -7.4 -12.2Z" fill="#7fa3c4"/><path d="M-4.4 -19.6L4.4 -19.6L4.8 -12L-4.8 -12Z" fill="#8fb2cf"/><path d="M-3.6 -19.4L-4.6 -22" fill="none" stroke="#6d90b0" stroke-width="1.4" stroke-linecap="round"/><path d="M3.6 -19.4L4.6 -22" fill="none" stroke="#6d90b0" stroke-width="1.4" stroke-linecap="round"/><path d="M-3.4 -18.2A0.8 0.8 0 1 0 -1.8 -18.2A0.8 0.8 0 1 0 -3.4 -18.2Z" fill="#e8d9a8"/><path d="M1.8 -18.2A0.8 0.8 0 1 0 3.4 -18.2A0.8 0.8 0 1 0 1.8 -18.2Z" fill="#e8d9a8"/><path d="M1.6 -9L2.8 -1.4" fill="none" stroke="#7fa3c4" stroke-width="4.2" stroke-linecap="round"/><path d="M0.5 -1A2.9 1.7 0 1 0 6.3 -1A2.9 1.7 0 1 0 0.5 -1Z" fill="#6f5a46"/><path d="M4.6 -18.5L6.6 -11.5" fill="none" stroke="#efdcb4" stroke-width="3.3" stroke-linecap="round"/><path d="M4.7 -11A1.9 1.9 0 1 0 8.5 -11A1.9 1.9 0 1 0 4.7 -11Z" fill="#f3d3b0"/><path d="M-6 -27A6.6 6.6 0 1 0 7.2 -27A6.6 6.6 0 1 0 -6 -27Z" fill="#f3d3b0"/><path d="M-7 -28.6A3.2 3.4 0 1 0 -0.6 -28.6A3.2 3.4 0 1 0 -7 -28.6Z" fill="#a8724a"/><path d="M2.2 -25.4A1.7 1.1 0 1 0 5.6 -25.4A1.7 1.1 0 1 0 2.2 -25.4Z" fill="#efb4a0"/><path d="M2.4 -27.8A0.9 1.15 0 1 0 4.2 -27.8A0.9 1.15 0 1 0 2.4 -27.8Z" fill="#3d4a3f"/><path d="M-10 -31A10.6 2.6 0 1 0 11.2 -31A10.6 2.6 0 1 0 -10 -31Z" fill="#cfae58"/><path d="M-10 -31.6A10.6 3 0 1 0 11.2 -31.6A10.6 3 0 1 0 -10 -31.6Z" fill="#e3c56f"/><path d="M-5 -32.4A5.6 1.5 0 1 0 6.2 -32.4A5.6 1.5 0 1 0 -5 -32.4Z" fill="#c98a5a"/><path d="M-5.2 -35A5.8 4 0 1 0 6.4 -35A5.8 4 0 1 0 -5.2 -35Z" fill="#ecd283"/><path d="M-3.4 -35.8A2.2 1.2 0 1 0 1 -35.8A2.2 1.2 0 1 0 -3.4 -35.8Z" fill="#f4e2a4"/></g><g class="vp-stepA"><path d="M-8 0.6A9.5 3 0 1 0 11 0.6A9.5 3 0 1 0 -8 0.6Z" fill="#41623530"/><path d="M-1.6 -9.8L-5.2 -3" fill="none" stroke="#7fa3c4" stroke-width="4.2" stroke-linecap="round"/><path d="M-7.7 -2.6A2.9 1.7 0 1 0 -1.9 -2.6A2.9 1.7 0 1 0 -7.7 -2.6Z" fill="#6f5a46"/><path d="M-4.6 -19.3L-3.4 -12.3" fill="none" stroke="#efdcb4" stroke-width="3.3" stroke-linecap="round"/><path d="M-5.3 -11.8A1.9 1.9 0 1 0 -1.5 -11.8A1.9 1.9 0 1 0 -5.3 -11.8Z" fill="#f3d3b0"/><path d="M-6.8 -17.8A6.8 6.6 0 1 0 6.8 -17.8A6.8 6.6 0 1 0 -6.8 -17.8Z" fill="#efdcb4"/><path d="M-7.4 -13A7.4 6.8 0 1 0 7.4 -13A7.4 6.8 0 1 0 -7.4 -13Z" fill="#7fa3c4"/><path d="M-4.4 -20.4L4.4 -20.4L4.8 -12.8L-4.8 -12.8Z" fill="#8fb2cf"/><path d="M-3.6 -20.2L-4.6 -22.8" fill="none" stroke="#6d90b0" stroke-width="1.4" stroke-linecap="round"/><path d="M3.6 -20.2L4.6 -22.8" fill="none" stroke="#6d90b0" stroke-width="1.4" stroke-linecap="round"/><path d="M-3.4 -19A0.8 0.8 0 1 0 -1.8 -19A0.8 0.8 0 1 0 -3.4 -19Z" fill="#e8d9a8"/><path d="M1.8 -19A0.8 0.8 0 1 0 3.4 -19A0.8 0.8 0 1 0 1.8 -19Z" fill="#e8d9a8"/><path d="M1.6 -9.8L5.6 -1.4" fill="none" stroke="#7fa3c4" stroke-width="4.2" stroke-linecap="round"/><path d="M3.3 -1A2.9 1.7 0 1 0 9.1 -1A2.9 1.7 0 1 0 3.3 -1Z" fill="#6f5a46"/><path d="M4.6 -19.3L8.4 -12.3" fill="none" stroke="#efdcb4" stroke-width="3.3" stroke-linecap="round"/><path d="M6.5 -11.8A1.9 1.9 0 1 0 10.3 -11.8A1.9 1.9 0 1 0 6.5 -11.8Z" fill="#f3d3b0"/><path d="M-6 -27.8A6.6 6.6 0 1 0 7.2 -27.8A6.6 6.6 0 1 0 -6 -27.8Z" fill="#f3d3b0"/><path d="M-7 -29.4A3.2 3.4 0 1 0 -0.6 -29.4A3.2 3.4 0 1 0 -7 -29.4Z" fill="#a8724a"/><path d="M2.2 -26.2A1.7 1.1 0 1 0 5.6 -26.2A1.7 1.1 0 1 0 2.2 -26.2Z" fill="#efb4a0"/><path d="M2.4 -28.6A0.9 1.15 0 1 0 4.2 -28.6A0.9 1.15 0 1 0 2.4 -28.6Z" fill="#3d4a3f"/><path d="M-10 -31.8A10.6 2.6 0 1 0 11.2 -31.8A10.6 2.6 0 1 0 -10 -31.8Z" fill="#cfae58"/><path d="M-10 -32.4A10.6 3 0 1 0 11.2 -32.4A10.6 3 0 1 0 -10 -32.4Z" fill="#e3c56f"/><path d="M-5 -33.2A5.6 1.5 0 1 0 6.2 -33.2A5.6 1.5 0 1 0 -5 -33.2Z" fill="#c98a5a"/><path d="M-5.2 -35.8A5.8 4 0 1 0 6.4 -35.8A5.8 4 0 1 0 -5.2 -35.8Z" fill="#ecd283"/><path d="M-3.4 -36.6A2.2 1.2 0 1 0 1 -36.6A2.2 1.2 0 1 0 -3.4 -36.6Z" fill="#f4e2a4"/></g><g class="vp-stepB"><path d="M-8 0.6A9.5 3 0 1 0 11 0.6A9.5 3 0 1 0 -8 0.6Z" fill="#41623530"/><path d="M-1.6 -9L-1.2 -1.4" fill="none" stroke="#7fa3c4" stroke-width="4.2" stroke-linecap="round"/><path d="M-3.7 -1A2.9 1.7 0 1 0 2.1 -1A2.9 1.7 0 1 0 -3.7 -1Z" fill="#6f5a46"/><path d="M-4.6 -18.5L-8.2 -11.5" fill="none" stroke="#efdcb4" stroke-width="3.3" stroke-linecap="round"/><path d="M-10.1 -11A1.9 1.9 0 1 0 -6.3 -11A1.9 1.9 0 1 0 -10.1 -11Z" fill="#f3d3b0"/><path d="M-6.8 -17A6.8 6.6 0 1 0 6.8 -17A6.8 6.6 0 1 0 -6.8 -17Z" fill="#efdcb4"/><path d="M-7.4 -12.2A7.4 6.8 0 1 0 7.4 -12.2A7.4 6.8 0 1 0 -7.4 -12.2Z" fill="#7fa3c4"/><path d="M-4.4 -19.6L4.4 -19.6L4.8 -12L-4.8 -12Z" fill="#8fb2cf"/><path d="M-3.6 -19.4L-4.6 -22" fill="none" stroke="#6d90b0" stroke-width="1.4" stroke-linecap="round"/><path d="M3.6 -19.4L4.6 -22" fill="none" stroke="#6d90b0" stroke-width="1.4" stroke-linecap="round"/><path d="M-3.4 -18.2A0.8 0.8 0 1 0 -1.8 -18.2A0.8 0.8 0 1 0 -3.4 -18.2Z" fill="#e8d9a8"/><path d="M1.8 -18.2A0.8 0.8 0 1 0 3.4 -18.2A0.8 0.8 0 1 0 1.8 -18.2Z" fill="#e8d9a8"/><path d="M1.6 -9L1.6 -2.6" fill="none" stroke="#7fa3c4" stroke-width="4.2" stroke-linecap="round"/><path d="M-0.7 -2.2A2.9 1.7 0 1 0 5.1 -2.2A2.9 1.7 0 1 0 -0.7 -2.2Z" fill="#6f5a46"/><path d="M4.6 -18.5L4.2 -11.5" fill="none" stroke="#efdcb4" stroke-width="3.3" stroke-linecap="round"/><path d="M2.3 -11A1.9 1.9 0 1 0 6.1 -11A1.9 1.9 0 1 0 2.3 -11Z" fill="#f3d3b0"/><path d="M-6 -27A6.6 6.6 0 1 0 7.2 -27A6.6 6.6 0 1 0 -6 -27Z" fill="#f3d3b0"/><path d="M-7 -28.6A3.2 3.4 0 1 0 -0.6 -28.6A3.2 3.4 0 1 0 -7 -28.6Z" fill="#a8724a"/><path d="M2.2 -25.4A1.7 1.1 0 1 0 5.6 -25.4A1.7 1.1 0 1 0 2.2 -25.4Z" fill="#efb4a0"/><path d="M2.4 -27.8A0.9 1.15 0 1 0 4.2 -27.8A0.9 1.15 0 1 0 2.4 -27.8Z" fill="#3d4a3f"/><path d="M-10 -31A10.6 2.6 0 1 0 11.2 -31A10.6 2.6 0 1 0 -10 -31Z" fill="#cfae58"/><path d="M-10 -31.6A10.6 3 0 1 0 11.2 -31.6A10.6 3 0 1 0 -10 -31.6Z" fill="#e3c56f"/><path d="M-5 -32.4A5.6 1.5 0 1 0 6.2 -32.4A5.6 1.5 0 1 0 -5 -32.4Z" fill="#c98a5a"/><path d="M-5.2 -35A5.8 4 0 1 0 6.4 -35A5.8 4 0 1 0 -5.2 -35Z" fill="#ecd283"/><path d="M-3.4 -35.8A2.2 1.2 0 1 0 1 -35.8A2.2 1.2 0 1 0 -3.4 -35.8Z" fill="#f4e2a4"/></g></svg>';
// Walk graph of the village (generated: manifest.walk of scripts/art/village/build_village.py, format in its README):
// n = node x,y pairs and z = walkable quads in world units (2400x1800), e = node index pairs, a = approach node per target.
const VILLAGE_WALK={n:[77,365,2323,365,1920,427,1922,428,1874,452,287,471,2113,471,2060,497,498,576,1902,576,1218,602,1176,605,709,681,1691,681,1408,698,1390,707,1533,760,1056,767,919,787,586,813,510,814,609,825,547,832,595,832,1016,835,1384,835,656,848,489,861,946,870,1114,884,1279,888,1502,891,480,892,1499,892,987,896,476,898,485,900,884,901,1305,901,1516,901,1063,909,1174,914,1226,914,1331,914,750,922,1308,925,1147,927,1253,927,1358,927,963,940,1437,940,1103,949,1200,953,1305,953,1411,953,1279,966,1169,969,1156,975,1358,980,1200,985,797,1012,1586,1015,809,1017,1261,1028,1895,1044,1174,1045,1745,1055,1194,1056,1200,1059,1186,1060,358,1067,1706,1074,1077,1094,1334,1094,645,1099,1770,1107,1010,1109,674,1114,1029,1118,1814,1129,1182,1146,533,1155,1253,1164,1235,1173,884,1190,1323,1217,1639,1217,2007,1225,323,1260,744,1260,2156,1300,1656,1325,2095,1331,919,1348,112,1366,959,1368,1057,1374,1797,1383,1937,1383,1008,1391,1007,1392,1013,1395,42,1401,2358,1401,830,1433,1200,1474,1186,1481,1340,1559,1551,1664,1762,1769],e:[0,5,1,6,2,3,3,4,3,7,5,8,6,7,7,9,8,12,9,13,10,11,10,14,12,18,13,16,14,15,14,16,16,25,17,18,18,24,19,21,19,22,20,22,21,23,21,26,22,27,24,28,24,29,25,33,27,32,28,34,29,40,29,41,30,38,31,33,32,35,33,39,35,36,35,70,37,44,37,49,38,43,38,47,39,50,41,46,42,47,43,45,43,48,46,51,46,52,47,52,47,53,48,53,48,54,49,62,49,65,50,54,50,61,52,56,53,55,53,58,54,58,56,57,56,59,58,63,60,62,61,71,62,74,63,73,63,80,64,75,65,67,65,72,66,71,67,68,67,69,70,81,71,75,72,78,72,80,74,77,74,81,75,79,76,78,78,84,79,86,79,87,80,83,81,88,81,89,82,83,83,85,84,89,87,90,88,94,89,93,90,92,90,103,91,97,92,98,93,95,94,102,95,100,95,104,96,101,97,98,99,100,100,101,101,106,105,106,106,107,107,108,108,109],a:{"gate":105,"hall":59,"merchant":40,"place:board":45,"place:library":15,"place:market":34,"place:pier":20,"place:post":44,"place:workshop":64,"start":99,"visitor:0":96,"visitor:1":69,"visitor:2":36,"visitor:3":77,"Агата":31,"Кошка Кая":23,"Кошка Соня":73,"Лиса Даша":91,"Медведь Пух":104,"Механик Крот":66,"Неведома Зверушка":4,"Петух Олег":11,"Почтальон Ёж":60,"Суслик Игорь":76,"Филиныч":17},z:[[33,308,1025,804,954,839,-37,343],[2367,308,2437,343,1446,839,1376,804],[919,927,989,962,33,1440,-37,1405],[1481,927,2437,1405,2367,1440,1411,962],[1130,1032,1200,1067,814,1260,744,1225],[393,1050,1858,1783,1788,1818,323,1085],[1235,594,1516,734,1481,752,1200,611],[1902,401,2042,471,2007,488,1867,418],[603,804,744,874,709,892,568,822],[1130,1103,1340,1208,1305,1225,1095,1120],[1411,1067,1446,1085,1270,1173,1235,1155],[1762,1138,1797,1155,1586,1260,1551,1243],[1200,716,1551,892,1200,1067,849,892],[600,592,754,669,684,704,530,627]]};
// Festival layers of the village (scripts/art/village/fest_<id>.js, vector): one file per festival, fetched only while
// html[data-festival=<id>][data-festival-decor=on]. style.css shows decor and day light under the night tint, the glow above it.
const VILLAGE_FEST={posidelki:'village-fest-posidelki.svg',new_year:'village-fest-new_year.svg',maslenitsa:'village-fest-maslenitsa.svg',spring_flowers:'village-fest-spring_flowers.svg'},villageFestCache={};
// Сорока-коробейница (scripts/art/village/merchant.js, generated): the cart is a world-scale layer (asset), the magpie a fixed-size
// figure like the player's (frames vm-stand / vm-call). Both stay hidden unless html[data-merchant] is set; the merchant mechanic sets it
// and calls syncVillageMerchant(). cart = box of the cart, foot = where she stands (world units 2400x1800); the player's approach
// point is the walk graph anchor VILLAGE_WALK.a.merchant.
const VILLAGE_MERCHANT={asset:'village-merchant.svg',cart:[1010,794,81,103],foot:[1086,896],figure:'<svg class="vm-figure-art" viewBox="-20 -50 40 54" aria-hidden="true" focusable="false"><g class="vm-stand"><path d="M-9 0.6A10 3 0 1 0 11 0.6A10 3 0 1 0 -9 0.6Z" fill="#41623530"/><path d="M-3.6 -16L-12.4 -9.4L-15.6 -7.6L-14.4 -5.6L-10.6 -6.6L-1.6 -10.6Z" fill="#4f6b78"/><path d="M-4.6 -14.4L-13.4 -8.4L-14.6 -7.2L-11 -7.8L-3.4 -12.2Z" fill="#6f8f9a"/><path d="M-1.6 -8L-2.2 -1.2" fill="none" stroke="#5a5148" stroke-width="1.6" stroke-linecap="round"/><path d="M2.2 -8L2.8 -1.2" fill="none" stroke="#5a5148" stroke-width="1.6" stroke-linecap="round"/><path d="M-3.8 -0.9A2.2 1 0 1 0 0.6 -0.9A2.2 1 0 1 0 -3.8 -0.9Z" fill="#5a5148"/><path d="M1.2 -0.9A2.2 1 0 1 0 5.6 -0.9A2.2 1 0 1 0 1.2 -0.9Z" fill="#5a5148"/><path d="M-8 -16A8 10 0 1 0 8 -16A8 10 0 1 0 -8 -16Z" fill="#454b57"/><path d="M-2.6 -14.5A5 7.4 0 1 0 7.4 -14.5A5 7.4 0 1 0 -2.6 -14.5Z" fill="#f1eee6"/><path d="M4.91 -21.4A0.9 0.9 0 1 0 6.71 -21.4A0.9 0.9 0 1 0 4.91 -21.4Z" fill="#e2b04a"/><path d="M3.41 -20.66A0.9 0.9 0 1 0 5.21 -20.66A0.9 0.9 0 1 0 3.41 -20.66Z" fill="#e2b04a"/><path d="M1.28 -20.25A0.9 0.9 0 1 0 3.08 -20.25A0.9 0.9 0 1 0 1.28 -20.25Z" fill="#e2b04a"/><path d="M-1.08 -20.25A0.9 0.9 0 1 0 0.72 -20.25A0.9 0.9 0 1 0 -1.08 -20.25Z" fill="#e2b04a"/><path d="M-3.21 -20.66A0.9 0.9 0 1 0 -1.41 -20.66A0.9 0.9 0 1 0 -3.21 -20.66Z" fill="#e2b04a"/><path d="M-4.71 -21.4A0.9 0.9 0 1 0 -2.91 -21.4A0.9 0.9 0 1 0 -4.71 -21.4Z" fill="#e2b04a"/><path d="M-8 -16.5A5 8.6 0 1 0 2 -16.5A5 8.6 0 1 0 -8 -16.5Z" fill="#5f7f9a"/><path d="M-6 -19A2.6 3.8 0 1 0 -0.8 -19A2.6 3.8 0 1 0 -6 -19Z" fill="#eef0ee"/><path d="M-7 -11A3 2.6 0 1 0 -1 -11A3 2.6 0 1 0 -7 -11Z" fill="#7e9db5"/><path d="M-5 -29A6.2 6 0 1 0 7.4 -29A6.2 6 0 1 0 -5 -29Z" fill="#454b57"/><path d="M-4.6 -31L-7.6 -23.4L-2.4 -25.4Z" fill="#c47565"/><path d="M-6.2 -31.8A6.8 4.4 0 1 0 7.4 -31.8A6.8 4.4 0 1 0 -6.2 -31.8Z" fill="#d98a7a"/><path d="M-3.75 -32.6A0.75 0.75 0 1 0 -2.25 -32.6A0.75 0.75 0 1 0 -3.75 -32.6Z" fill="#f6e7d8"/><path d="M-0.75 -34A0.75 0.75 0 1 0 0.75 -34A0.75 0.75 0 1 0 -0.75 -34Z" fill="#f6e7d8"/><path d="M2.45 -33A0.75 0.75 0 1 0 3.95 -33A0.75 0.75 0 1 0 2.45 -33Z" fill="#f6e7d8"/><path d="M-2.35 -30.2A0.75 0.75 0 1 0 -0.85 -30.2A0.75 0.75 0 1 0 -2.35 -30.2Z" fill="#f6e7d8"/><path d="M1.25 -30.6A0.75 0.75 0 1 0 2.75 -30.6A0.75 0.75 0 1 0 1.25 -30.6Z" fill="#f6e7d8"/><path d="M2.8 -24.8A1.8 1.4 0 1 0 6.4 -24.8A1.8 1.4 0 1 0 2.8 -24.8Z" fill="#c47565"/><path d="M4.8 -24A1.4 1.1 0 1 0 7.6 -24A1.4 1.1 0 1 0 4.8 -24Z" fill="#d98a7a"/><path d="M1.8 -28.6A1.8 1.8 0 1 0 5.4 -28.6A1.8 1.8 0 1 0 1.8 -28.6Z" fill="#f6f3ea"/><path d="M3.05 -28.6A0.95 1.05 0 1 0 4.95 -28.6A0.95 1.05 0 1 0 3.05 -28.6Z" fill="#1f2328"/><path d="M6.6 -29.2L10.6 -28L6.6 -26.8Z" fill="#5a5148"/></g><g class="vm-call"><path d="M-9 0.6A10 3 0 1 0 11 0.6A10 3 0 1 0 -9 0.6Z" fill="#41623530"/><path d="M-3.6 -16L-12.4 -9.4L-15.6 -7.6L-14.4 -5.6L-10.6 -6.6L-1.6 -10.6Z" fill="#4f6b78"/><path d="M-4.6 -14.4L-13.4 -8.4L-14.6 -7.2L-11 -7.8L-3.4 -12.2Z" fill="#6f8f9a"/><path d="M-1.6 -8L-2.2 -1.2" fill="none" stroke="#5a5148" stroke-width="1.6" stroke-linecap="round"/><path d="M2.2 -8L2.8 -1.2" fill="none" stroke="#5a5148" stroke-width="1.6" stroke-linecap="round"/><path d="M-3.8 -0.9A2.2 1 0 1 0 0.6 -0.9A2.2 1 0 1 0 -3.8 -0.9Z" fill="#5a5148"/><path d="M1.2 -0.9A2.2 1 0 1 0 5.6 -0.9A2.2 1 0 1 0 1.2 -0.9Z" fill="#5a5148"/><path d="M-8 -16A8 10 0 1 0 8 -16A8 10 0 1 0 -8 -16Z" fill="#454b57"/><path d="M-2.6 -14.5A5 7.4 0 1 0 7.4 -14.5A5 7.4 0 1 0 -2.6 -14.5Z" fill="#f1eee6"/><path d="M4.91 -21.4A0.9 0.9 0 1 0 6.71 -21.4A0.9 0.9 0 1 0 4.91 -21.4Z" fill="#e2b04a"/><path d="M3.41 -20.66A0.9 0.9 0 1 0 5.21 -20.66A0.9 0.9 0 1 0 3.41 -20.66Z" fill="#e2b04a"/><path d="M1.28 -20.25A0.9 0.9 0 1 0 3.08 -20.25A0.9 0.9 0 1 0 1.28 -20.25Z" fill="#e2b04a"/><path d="M-1.08 -20.25A0.9 0.9 0 1 0 0.72 -20.25A0.9 0.9 0 1 0 -1.08 -20.25Z" fill="#e2b04a"/><path d="M-3.21 -20.66A0.9 0.9 0 1 0 -1.41 -20.66A0.9 0.9 0 1 0 -3.21 -20.66Z" fill="#e2b04a"/><path d="M-4.71 -21.4A0.9 0.9 0 1 0 -2.91 -21.4A0.9 0.9 0 1 0 -4.71 -21.4Z" fill="#e2b04a"/><path d="M-1.6 -21L-5 -30L-8.4 -35L-10.6 -34.4L-12.6 -31.4L-12.8 -27.6L-11.2 -24.4L-7.6 -19.4Z" fill="#5f7f9a"/><path d="M-4.4 -24.4L-7.4 -31L-9.8 -29.6L-7.4 -23Z" fill="#eef0ee"/><path d="M-8.8 -32.8L-10.6 -34.4" fill="none" stroke="#7e9db5" stroke-width="1" stroke-linecap="round"/><path d="M-10.8 -29.8L-12.6 -31.4" fill="none" stroke="#7e9db5" stroke-width="1" stroke-linecap="round"/><path d="M-11 -26L-12.8 -27.6" fill="none" stroke="#7e9db5" stroke-width="1" stroke-linecap="round"/><path d="M-11.8 -35.5A2.3 2.3 0 1 0 -7.2 -35.5A2.3 2.3 0 1 0 -11.8 -35.5Z" fill="#e2b04a"/><path d="M-10.9 -36.2A0.8 0.8 0 1 0 -9.3 -36.2A0.8 0.8 0 1 0 -10.9 -36.2Z" fill="#fff3c9"/><path d="M-5 -29A6.2 6 0 1 0 7.4 -29A6.2 6 0 1 0 -5 -29Z" fill="#454b57"/><path d="M-4.6 -31L-7.6 -23.4L-2.4 -25.4Z" fill="#c47565"/><path d="M-6.2 -31.8A6.8 4.4 0 1 0 7.4 -31.8A6.8 4.4 0 1 0 -6.2 -31.8Z" fill="#d98a7a"/><path d="M-3.75 -32.6A0.75 0.75 0 1 0 -2.25 -32.6A0.75 0.75 0 1 0 -3.75 -32.6Z" fill="#f6e7d8"/><path d="M-0.75 -34A0.75 0.75 0 1 0 0.75 -34A0.75 0.75 0 1 0 -0.75 -34Z" fill="#f6e7d8"/><path d="M2.45 -33A0.75 0.75 0 1 0 3.95 -33A0.75 0.75 0 1 0 2.45 -33Z" fill="#f6e7d8"/><path d="M-2.35 -30.2A0.75 0.75 0 1 0 -0.85 -30.2A0.75 0.75 0 1 0 -2.35 -30.2Z" fill="#f6e7d8"/><path d="M1.25 -30.6A0.75 0.75 0 1 0 2.75 -30.6A0.75 0.75 0 1 0 1.25 -30.6Z" fill="#f6e7d8"/><path d="M2.8 -24.8A1.8 1.4 0 1 0 6.4 -24.8A1.8 1.4 0 1 0 2.8 -24.8Z" fill="#c47565"/><path d="M4.8 -24A1.4 1.1 0 1 0 7.6 -24A1.4 1.1 0 1 0 4.8 -24Z" fill="#d98a7a"/><path d="M1.8 -28.6A1.8 1.8 0 1 0 5.4 -28.6A1.8 1.8 0 1 0 1.8 -28.6Z" fill="#f6f3ea"/><path d="M3.05 -28.6A0.95 1.05 0 1 0 4.95 -28.6A0.95 1.05 0 1 0 3.05 -28.6Z" fill="#1f2328"/><path d="M6.6 -29.4L11 -29.6L6.8 -27.8Z" fill="#5a5148"/><path d="M6.6 -27.2L10 -25.6L6.4 -26.2Z" fill="#5a5148"/><path d="M12.6 -31L15.6 -29.95" fill="none" stroke="#c9b48e" stroke-width="1" stroke-linecap="round"/><path d="M13.4 -28L16.8 -28" fill="none" stroke="#c9b48e" stroke-width="1" stroke-linecap="round"/><path d="M12.6 -25L15.6 -26.05" fill="none" stroke="#c9b48e" stroke-width="1" stroke-linecap="round"/></g></svg>'};let villageMerchantSvg='';
// Construction art (scripts/art/village build.js / crew.js, FARM_VILLAGE_CONSTRUCTION.md §6): the pieces of village-build.svg by id
// with their boxes (world units), the crew's foot points per site and the crew figures. Generated, do not edit by hand.
const VILLAGE_BUILD={"asset":"village-build.svg","sites":["stalls","tavern","greenhouse","fairground"],"stalls":["magpie","igor","sonya","agata","post","player"],"boxes":{"site-tavern-soon":[533,1366,309,207],"site-tavern-pit":[533,1372,309,201],"site-tavern-frame":[533,1347,309,226],"site-tavern-done":[582,1342,211,203],"site-greenhouse-soon":[891,394,302,204],"site-greenhouse-pit":[891,400,302,198],"site-greenhouse-frame":[891,386,302,212],"site-greenhouse-done":[940,411,204,158],"site-fairground-soon":[1572,1436,302,204],"site-fairground-pit":[1572,1442,302,198],"site-fairground-frame":[1572,1417,302,223],"site-fairground-done":[1621,1442,204,170],"site-stalls-soon":[820,787,475,290],"site-stalls-pit":[820,793,475,284],"site-stalls-frame":[820,783,475,294],"site-stalls-done":[820,777,475,300],"stall-magpie-open":[852,799,141,127],"stall-magpie-closed":[852,799,141,127],"stall-igor-open":[908,827,142,127],"stall-igor-closed":[908,827,142,127],"stall-sonya-open":[964,855,142,127],"stall-sonya-closed":[964,855,142,127],"stall-agata-open":[1021,883,141,127],"stall-agata-closed":[1021,883,141,127],"stall-post-open":[1077,911,141,127],"stall-post-closed":[1077,911,141,127],"stall-player-open":[1133,939,141,127],"stall-player-closed":[1133,939,141,127]},"crew":{"tavern":[[745,1532],[603,1503],[770,1504]],"greenhouse":[[1096,556],[961,530],[1121,528]],"fairground":[[1777,1598],[1642,1573],[1802,1570]],"stalls":[[863,878],[1005,961],[1118,1017]]}};
const VILLAGE_CREW={krot:'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-18 -50 36 54" class="bc-art" aria-hidden="true" focusable="false"><path d="M-7.5 0.6A9 2.8 0 1 0 10.5 0.6A9 2.8 0 1 0 -7.5 0.6Z" fill="#41623530"/><path d="M-6.2 -1.2A3.2 1.8 0 1 0 0.2 -1.2A3.2 1.8 0 1 0 -6.2 -1.2Z" fill="#4f4540"/><path d="M-0.2 -1.2A3.2 1.8 0 1 0 6.2 -1.2A3.2 1.8 0 1 0 -0.2 -1.2Z" fill="#4f4540"/><path d="M-7.6 -11A7.6 9.4 0 1 0 7.6 -11A7.6 9.4 0 1 0 -7.6 -11Z" fill="#6f6259"/><path d="M-5.6 -15L5.6 -15L6.4 -5L-6.4 -5Z" fill="#e8a83a"/><path d="M-5.6 -11L5.6 -11" fill="none" stroke="#f4ede0" stroke-width="1.4" stroke-linecap="round"/><path d="M-6.4 -24A6.4 6 0 1 0 6.4 -24A6.4 6 0 1 0 -6.4 -24Z" fill="#6f6259"/><path d="M1.8 -22.6A2.8 2 0 1 0 7.4 -22.6A2.8 2 0 1 0 1.8 -22.6Z" fill="#e7a8b5"/><path d="M5.7 -22.4A1.1 1 0 1 0 7.9 -22.4A1.1 1 0 1 0 5.7 -22.4Z" fill="#c97a8a"/><path d="M0.8 -25.2A0.8 0.7 0 1 0 2.4 -25.2A0.8 0.7 0 1 0 0.8 -25.2Z" fill="#2f3338"/><path d="M-6.6 -27L6.6 -27L5.4 -31.6L0 -33.4L-5.4 -31.6Z" fill="#f0c95a"/><path d="M-7.6 -27L7.8 -27" fill="none" stroke="#d9a650" stroke-width="1.6" stroke-linecap="round"/><path d="M-5.6 -16L-8.6 -9" fill="none" stroke="#6f6259" stroke-width="2.6" stroke-linecap="round"/><g class="bc-plan"><path d="M5.4 -16L9.6 -13.6" fill="none" stroke="#6f6259" stroke-width="2.6" stroke-linecap="round"/><path d="M7.4 -21L15.6 -18.6L14.8 -9.6L6.6 -12Z" fill="#9fc0d4"/><path d="M9.4 -13.6L9.4 -16.8L11.2 -18.6L13 -16L13 -12.8Z" fill="none" stroke="#f4f7f8" stroke-width="1" stroke-linecap="round"/><path d="M14 -14A1.2 4.6 0 1 0 16.4 -14A1.2 4.6 0 1 0 14 -14Z" fill="#b9d2e0"/></g></svg>',pooh:'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-18 -50 36 54" class="bc-art" aria-hidden="true" focusable="false"><path d="M-8.5 0.6A10 3 0 1 0 11.5 0.6A10 3 0 1 0 -8.5 0.6Z" fill="#41623530"/><path d="M-7 -1.4A3.6 2.2 0 1 0 0.2 -1.4A3.6 2.2 0 1 0 -7 -1.4Z" fill="#8a5f3a"/><path d="M-0.2 -1.4A3.6 2.2 0 1 0 7 -1.4A3.6 2.2 0 1 0 -0.2 -1.4Z" fill="#8a5f3a"/><path d="M-9 -12A9 10.4 0 1 0 9 -12A9 10.4 0 1 0 -9 -12Z" fill="#b5814f"/><path d="M-5.6 -10A5.6 6.6 0 1 0 5.6 -10A5.6 6.6 0 1 0 -5.6 -10Z" fill="#e3c08a"/><path d="M-7.4 -9L7.4 -9L7.8 -6.6L-7.8 -6.6Z" fill="#7fa3c4"/><path d="M-4.4 -7.8A1.4 1.8 0 1 0 -1.6 -7.8A1.4 1.8 0 1 0 -4.4 -7.8Z" fill="#9c9e9a"/><path d="M-7 -31.4A2.6 2.6 0 1 0 -1.8 -31.4A2.6 2.6 0 1 0 -7 -31.4Z" fill="#b5814f"/><path d="M1.8 -31.4A2.6 2.6 0 1 0 7 -31.4A2.6 2.6 0 1 0 1.8 -31.4Z" fill="#b5814f"/><path d="M-7 -26A7 6.6 0 1 0 7 -26A7 6.6 0 1 0 -7 -26Z" fill="#b5814f"/><path d="M-1.6 -23.6A3.4 2.6 0 1 0 5.2 -23.6A3.4 2.6 0 1 0 -1.6 -23.6Z" fill="#e3c08a"/><path d="M1.2 -24.6A1.2 0.9 0 1 0 3.6 -24.6A1.2 0.9 0 1 0 1.2 -24.6Z" fill="#3d2f26"/><path d="M-2.4 -27.4A0.8 0.9 0 1 0 -0.8 -27.4A0.8 0.9 0 1 0 -2.4 -27.4Z" fill="#2f3338"/><path d="M2.8 -27.6A0.8 0.9 0 1 0 4.4 -27.6A0.8 0.9 0 1 0 2.8 -27.6Z" fill="#2f3338"/><path d="M-7 -17L-9.4 -10" fill="none" stroke="#b5814f" stroke-width="3.4" stroke-linecap="round"/><g class="bc-hammer"><path d="M6.6 -17L10.6 -22" fill="none" stroke="#b5814f" stroke-width="3.4" stroke-linecap="round"/><path d="M10.6 -22L12 -30" fill="none" stroke="#8a6c4c" stroke-width="1.6" stroke-linecap="round"/><path d="M9 -31.6L15.4 -29.4L15 -27L8.6 -29.2Z" fill="#7f8a86"/></g></svg>',kaya:'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-18 -50 36 54" class="bc-art" aria-hidden="true" focusable="false"><path d="M-7.1 0.6A8.6 2.8 0 1 0 10.1 0.6A8.6 2.8 0 1 0 -7.1 0.6Z" fill="#41623530"/><path d="M-5.4 -1.2A2.8 1.8 0 1 0 0.2 -1.2A2.8 1.8 0 1 0 -5.4 -1.2Z" fill="#8d8a84"/><path d="M-0.2 -1.2A2.8 1.8 0 1 0 5.4 -1.2A2.8 1.8 0 1 0 -0.2 -1.2Z" fill="#8d8a84"/><path d="M-4.6 -6L-10.6 -14" fill="none" stroke="#a9a7a0" stroke-width="2.4" stroke-linecap="round"/><path d="M-10.6 -14L-9 -19" fill="none" stroke="#a9a7a0" stroke-width="2.4" stroke-linecap="round"/><path d="M-6.4 -11A6.4 8.6 0 1 0 6.4 -11A6.4 8.6 0 1 0 -6.4 -11Z" fill="#a9a7a0"/><path d="M-5 -16L5 -16L5.8 -4.6L-5.8 -4.6Z" fill="#8fae6f"/><path d="M-6 -23.4A6 5.6 0 1 0 6 -23.4A6 5.6 0 1 0 -6 -23.4Z" fill="#a9a7a0"/><path d="M-5.4 -26L-4.4 -32L-1.4 -27.6Z" fill="#a9a7a0"/><path d="M5.4 -26L4.4 -32L1.4 -27.6Z" fill="#a9a7a0"/><path d="M-4.6 -26.4L-4.2 -30.2L-2.4 -27.6Z" fill="#e7a8b5"/><path d="M-3 -27L-1.4 -25.6" fill="none" stroke="#7c7a74" stroke-width="1" stroke-linecap="round"/><path d="M0 -28L0 -26" fill="none" stroke="#7c7a74" stroke-width="1" stroke-linecap="round"/><path d="M-2.8 -23.6A0.8 1 0 1 0 -1.2 -23.6A0.8 1 0 1 0 -2.8 -23.6Z" fill="#3d4a3f"/><path d="M1.4 -23.6A0.8 1 0 1 0 3 -23.6A0.8 1 0 1 0 1.4 -23.6Z" fill="#3d4a3f"/><path d="M-0.7 -21.6A0.9 0.6 0 1 0 1.1 -21.6A0.9 0.6 0 1 0 -0.7 -21.6Z" fill="#e7a8b5"/><g class="bc-shovel"><path d="M-4.6 -16L3 -10" fill="none" stroke="#a9a7a0" stroke-width="2.4" stroke-linecap="round"/><path d="M4.6 -15L6 -10.6" fill="none" stroke="#a9a7a0" stroke-width="2.4" stroke-linecap="round"/><path d="M1 -20L9 -1" fill="none" stroke="#8a6c4c" stroke-width="1.8" stroke-linecap="round"/><path d="M6.6 -2.6L11.4 -4.4L12.4 1.4L8.6 2.6Z" fill="#8f949c"/></g></svg>'};
// River-mill water wheel (overshot): it stands in the plane of the mill's long wall (iso 1:-0.5, the axle painted in village.svg runs
// into that wall) with its hub on the axle end (731.7, 555) and its lower paddles in the race. The flume ends at the wheel's
// top on the tower side; its water arcs over the top and lands on the far paddles, so the top turns away from the flume
// (counter-clockwise in the wall plane). Flat shapes in the village palette; only the two paddle groups rotate (CSS, reduced-motion aware).
const VILLAGE_WHEEL_SVG=(()=>{
 // The wheel is 9 units wide along the axle: five synchronised layers (back rim, three paddle slices, front face) read as boards
 // spanning the width. Everything below the waterline (local y > 21) is clipped, so the race painted in village.svg shows through.
 const paddles=(fill,edge)=>Array.from({length:8},(_,i)=>`<rect x="-3" y="-30.5" width="6" height="9.5" rx="1" transform="rotate(${i*45})" fill="${fill}"${edge?` stroke="${edge}" stroke-width="1"`:''}/>`).join('');
 const layer=(dx,body)=>`<g transform="matrix(.894,-.447,0,1,${dx},${dx*.48})" clip-path="url(#vw-race)"><g class="vw-rot">${body}</g></g>`;
 return '<svg class="vfx-wheel-art" viewBox="-40 -50 80 95" preserveAspectRatio="none" aria-hidden="true" focusable="false">'
 +'<defs><clipPath id="vw-race" clipPathUnits="userSpaceOnUse"><rect x="-40" y="-40" width="80" height="61"/></clipPath>'
 +'<filter id="vw-night" color-interpolation-filters="sRGB"><feColorMatrix type="matrix" values=".34 0 0 0 .075 0 .34 0 0 .122 0 0 .34 0 .259 0 0 0 1 0"/></filter></defs><g class="vw-all">'
 +layer(-8,`${paddles('#6f4f32','#4f3722')}<circle r="24" fill="none" stroke="#5f432a" stroke-width="4"/>`)
 +layer(-6,paddles('#8a6340'))+layer(-4,paddles('#966b44'))+layer(-2,paddles('#a3764a'))
 +layer(0,`<circle r="22" fill="#6a4e34"/>${paddles('#c99c69','#6e4c30')}<circle r="24" fill="none" stroke="#a77a4c" stroke-width="4"/><circle r="24" fill="none" stroke="#6e4c30" stroke-width=".8"/>`
  +'<path d="M-20.5 0H20.5M0 -20.5V20.5M-14.5 -14.5L14.5 14.5M-14.5 14.5L14.5 -14.5" stroke="#8b6440" stroke-width="2.6" stroke-linecap="round"/>')
 +'<g transform="matrix(.894,-.447,0,1,0,0)"><circle r="5" fill="#4f3824"/><circle cx="-1.2" cy="-1.3" r="1.8" fill="#7a5a3c"/>'
 // foam where the paddles enter the race
 +'<path d="M-19 21.2H-9M-4 21.2H6M11 21.2H18" stroke="#e4f2ef" stroke-width="1.5" stroke-linecap="round" opacity=".9"/>'
 // flume water: leaves the lip on the tower side, arcs over the top and falls on the far paddles
 +'<path d="M13.6 -28.2C9 -33.5 0 -34 -5.5 -28.5" fill="none" stroke="#bfe0de" stroke-width="3" stroke-linecap="round" opacity=".9"/><path d="M12 -29.6C8 -32.4 1 -32.8 -3.6 -29.8" fill="none" stroke="#f1f9f7" stroke-width=".9" stroke-linecap="round"/>'
 +'<circle cx="-8.4" cy="-24.6" r="1.1" fill="#d7eae6"/><circle cx="-6.6" cy="-21.4" r=".85" fill="#d7eae6"/></g></g></svg>';
})();
const VILLAGE_SPEED=260,VILLAGE_MAX_WALK=7;let villageWalkRaf=0,villageWalkPlayer=null;let villagePos=[...VILLAGE_START],villageWalkToken=0,villageDragged=false,villageMini=null;
// Living village: idle thought, stroll offset in px (x, y) per resident. Motion is pure CSS, no timers.
const VILLAGE_LIFE={'Филиныч':['📚',52,26],'Агата':['🍞',-50,-25],'Почтальон Ёж':['✉️',52,-26],'Механик Крот':['🔧',-50,-25],'Кошка Кая':['🐟',-48,-10],'Кошка Соня':['💤',44,22],'Суслик Игорь':['🌰',-44,22],'Неведома Зверушка':['❓',48,24],'Медведь Пух':['🥤',46,-22],'Лиса Даша':['🪙',-40,18],'Петух Олег':['🌾',36,-12]};
// Chimney tops (smoke puffs) exported from the same render as village.svg.
const VILLAGE_SMOKE=[[649,454],[904,592],[1032,636],[1760,704],[723,757],[1582,751],[1400,862],[1732,851],[590,952],[1954,995],[1573,1051],[747,1106],[2072,1048],[434,1224],[1134,1274],[803,1328],[1881,281]];
// Night lights in village.svg coordinates (2400x1800): a/b = left/right wall windows, r = round window, c = clock, l = lamp head, p = lamp light pool.
const VILLAGE_LIGHTS=[[1256,1405,'l'],[763,1392,'r'],[1858,339,'r'],[1921,334,'r'],[617,562,'a'],[744,530,'b'],[1292,589,'a'],[837,648,'a'],[944,646,'b'],[950,712,'a'],[974,724,'a'],[1082,705,'b'],[1019,736,'b'],[1397,718,'b'],[1767,748,'b'],[1917,741,'b'],[1098,788,'a'],[1098,766,'a'],[1126,801,'a'],[1126,780,'a'],[1302,788,'b'],[1302,766,'b'],[1274,780,'b'],[781,827,'a'],[1525,842,'a'],[1558,858,'a'],[1664,834,'b'],[1168,848,'a'],[1232,848,'b'],[1168,829,'a'],[2028,863,'a'],[1739,903,'b'],[729,932,'a'],[780,939,'b'],[1862,1017,'b'],[514,1024,'a'],[538,1036,'a'],[636,1019,'b'],[1398,1031,'a'],[1436,1027,'b'],[984,1049,'b'],[1986,1060,'b'],[1497,1123,'a'],[1521,1135,'a'],[1619,1118,'b'],[1564,1145,'b'],[1060,1226,'b'],[583,1246,'b'],[474,1297,'b'],[2002,1310,'b'],[1959,1330,'b'],[1521,1343,'a'],[1592,1330,'b'],[1058,1346,'a'],[1177,1338,'b'],[1121,1366,'b'],[1168,805,'c'],[1232,805,'c'],[512,492,'l'],[512,534,'p'],[1888,492,'l'],[1888,534,'p'],[1712,580,'l'],[1712,622,'p'],[789,631,'l'],[789,673,'p'],[863,668,'l'],[863,710,'p'],[1537,668,'l'],[1537,710,'p'],[800,734,'l'],[800,776,'p'],[1024,748,'l'],[1024,790,'p'],[1376,748,'l'],[1376,790,'p'],[856,762,'l'],[856,804,'p'],[1544,762,'l'],[1544,804,'p'],[884,889,'l'],[884,931,'p'],[1516,889,'l'],[1516,931,'p'],[694,983,'l'],[694,1025,'p'],[1572,1015,'l'],[1572,1057,'p'],[575,1043,'l'],[575,1085,'p'],[1200,1046,'l'],[1200,1088,'p'],[1846,1054,'l'],[1846,1096,'p'],[2021,1142,'l'],[2021,1184,'p'],[1010,1142,'l'],[1010,1184,'p'],[744,1169,'l'],[744,1211,'p'],[442,1208,'l'],[442,1250,'p'],[2197,1229,'l'],[2197,1271,'p'],[933,1264,'l'],[933,1306,'p'],[1144,1370,'l'],[1144,1412,'p'],[1390,1492,'l'],[1390,1534,'p'],[1467,1629,'l'],[1467,1671,'p']];
const VILLAGE_FLIES=[[1376,1232],[1179,1246],[442,829],[1053,594],[1741,1359],[905,1215]];
// Construction sites of future village buildings (art only, no game logic yet).
const VILLAGE_SITES=[['stalls','Торговые ряды',34.7,47.2],['tavern','Трактир',28.7,80.4],['greenhouse','Оранжерея',43.4,26.3],['fairground','Ярмарка',71.8,84.2]];
// Village places: signs on buildings that lead to the existing farm sections (no new game rules).
const VILLAGE_PLACES=[['board','Доска заказов','orders',54.5,49,'orders'],['post','Почта: соседи и подарки','friends',29.5,50,'neighbors'],['market','Рынок: склад и продажа','shop',40.3,47.4,'inventory'],['workshop','Мастерская: производство','workshop',80.4,56.6,'production'],['library','Библиотека: журнал фермы','journal',56,37.4,'journal'],['pier','Причал: озеро и рыбалка','lake',19.6,42.8,'lake']];
// Visiting guests: picked by the Moscow date, so everyone sees the same guests on the same day. They only point to existing sections.
const VILLAGE_VISITORS=[['trader','Странствующий торговец','🧳','Заглянул по пути на ярмарку. Покажешь, что лежит на складе? Может, сторгуемся.','Открыть склад','inventory'],['fisher','Рыбак Сом','🎣','На озере у фермы сегодня клюёт! Возьми удочку, пока рыба играет.','К озеру','lake'],['forester','Лесник Бор','🌲','В лесу поспели ягоды и грибы. Соберёшь — пригодятся в пирогах.','В лес','forest'],['teller','Сказитель','📜','Хочешь, расскажу, что было на этой ферме? Всё записано в журнале.','Открыть журнал','journal'],['crafter','Плотник Тёс','🔨','Руки чешутся что-нибудь построить. Посмотрим, что можно поставить на ферме?','К постройкам','build'],['traveler','Путница Веся','🎒','Иду от соседей — машут тебе и ждут в гости.','К соседям','neighbors'],['bogatyr','Богатырь','🛡️','У озера на распутье лежит камень. Кто надпись прочтёт, тот путь свой найдёт…','К находкам','secrets']];
// Easter-egg guests: extra pool, never replaces the daily guests. Names nod to the owner's other projects; the figures are local critters.
const VILLAGE_EGGS=[['egg_dymok','Ёж Дымок','🦔','Весь в саже: трубы чистил. Если на ферме чем-то пахнет — загляни в журнал, там всё записано.','Открыть журнал','journal'],['egg_shustrik','Мышь Шустрик','🐭','Таскаю посылки по узким лазам, где никто не ходит. Пройдись по соседям — там тебя ждут.','К соседям','neighbors'],['egg_pushok','Барсук Пушок','🦡','Сторожу чужие амбары, а свой не успеваю. Глянь, что у тебя на складе.','Открыть склад','inventory'],['egg_boryan','Лис Борян','🦊','Из сараев и канав знаю, где что плохо лежит. Давай поищем находки вместе?','К находкам','secrets'],['egg_belyana','Сова Беляна','🦉','Люблю, когда всё лежит ровно. Давай посмотрим на заказы — разложим по порядку.','К заказам','orders'],['egg_kroshka','Божья коровка Крошка','🐞','Я маленькая, зато в лесу знаю каждую тропинку. Пойдём за ягодами?','В лес','forest'],['egg_sharik','Лягух Шарик','🐸','Квакаю на весь пруд — не вытерпел! Рыба сегодня резвая, беги к озеру.','К озеру','lake'],['egg_filya','Паучок Филя','🕷️','Тяну нити на любые катушки. Загляни в мастерские — там тоже что-то мотается.','К мастерским','production'],['egg_makro','Бобёр Макро','🦫','Всё строю по чертежу и по ГОСТу, зубами не разгрызть. Посмотрим, что можно возвести?','К постройкам','build']];
const VILLAGE_VISITOR_SPOTS=[[44.8,74.5],[49.4,57.3],[20.2,48.4],[28.1,60.3]];
const VILLAGE_STAGES=['Подготовка','Флажки','Цветы','Праздник!'];
const villageT0=Date.now();
function villageVars(n,vars){for(const [k,v] of Object.entries(vars)){if(n.style.setProperty)n.style.setProperty(k,v);else n.style[k]=v;}return n;}
const villageReduced=()=>typeof matchMedia==='function'&&matchMedia('(prefers-reduced-motion: reduce)').matches;
const villageClamp=(v,a,b)=>Math.min(b,Math.max(a,v));
let villageIO=null,villageWorldEl=null,villageVisBound=false;

const fmt=n=>new Intl.NumberFormat('ru-RU').format(n);
const own=()=>S.farm?.is_owner;
const now=()=>Date.now()/1000+(S.offset||0);
const el=(tag,txt,cls)=>{let n=document.createElement(tag);if(txt!==undefined&&txt!==null)n.textContent=txt;if(cls)n.className=cls;return n;};
const icon=id=>{const n=document.createElementNS('http://www.w3.org/2000/svg','svg'),u=document.createElementNS(n.namespaceURI,'use');n.setAttribute('viewBox','0 0 48 48');n.setAttribute('aria-hidden','true');u.setAttribute('href',`/app/farm/assets/icons.svg#${FEST.iconId(id)}`);n.append(u);return n;};
function lakeDoorArt(){const n=document.createElementNS('http://www.w3.org/2000/svg','svg');n.setAttribute('class','lake-door-art');n.setAttribute('viewBox','0 0 160 68');n.setAttribute('preserveAspectRatio','xMidYMid slice');n.setAttribute('aria-hidden','true');n.setAttribute('focusable','false');n.innerHTML='<defs><clipPath id="lake-card-clip"><rect width="160" height="68" rx="13"/></clipPath><linearGradient id="lake-sky" x2="0" y2="1"><stop stop-color="#dcebd1"/><stop offset="1" stop-color="#f3eacb"/></linearGradient><linearGradient id="lake-water" x2="0" y2="1"><stop stop-color="#8ec7c1"/><stop offset="1" stop-color="#5d9d9c"/></linearGradient></defs><g clip-path="url(#lake-card-clip)"><rect width="160" height="68" fill="url(#lake-sky)"/><circle cx="125" cy="15" r="8" fill="#f6d47d" opacity=".82"/><path d="M0 34 24 16l25 19 28-22 34 24 23-15 26 17v29H0Z" fill="#9bb68b"/><path d="M0 43q25-11 48 0t47 0 65 0v34H0Z" fill="#6f966d"/><path d="M0 47q25-9 49 0t47 0 64 0v25H0Z" fill="url(#lake-water)"/><path d="M8 52q12-4 23 0t23 0m18 0q12-4 23 0t23 0m-73 9q11-3 22 0t22 0m36-7q10-3 20 0" fill="none" stroke="#d4ebe1" stroke-width="1.7" stroke-linecap="round" opacity=".85"/><path d="M8 45V29m0 11-5-7m5 4 5-7m-1 15V33m0 8 5-7m-5 4-4-6m135 12V28m0 13-5-7m5 4 5-7m-1 11V34m0 8 5-7m-5 4-4-6" fill="none" stroke="#547952" stroke-width="2" stroke-linecap="round"/><path d="M65 45q10-7 20 0-10 7-20 0Z" fill="#f0d39a" stroke="#7c795a" stroke-width="1.2"/><path d="m82 44 5-4v10l-5-4" fill="#e7c27a"/><circle cx="72" cy="45" r="1" fill="#365b4c"/><path d="M73 23q5-5 10 0m-7 5q4-4 8 0" fill="none" stroke="#fff8df" stroke-width="1.5" stroke-linecap="round" opacity=".9"/></g>';return n;}
const button=(text,fn,cls='primary',disabled=false)=>{let b=el('button',text,cls);b.type='button';b.disabled=disabled;b.onclick=fn;return b;};
const itemName=id=>S.catalog?.items[id]?.name||id;
const objName=o=>o.type==='tree'?ORCH.treeName(S.catalog,o):o.type==='plot'?'Грядка':o.type==='house'?'Дом Филиныча':o.type==='barn'?'Склад':S.catalog.buildings[o.type]?.name||o.type;
const objIcon=o=>o.type==='tree'?(ORCH.species(S.catalog,o)?.fruit||'apple'):o.type==='plot'?(o.crop?.id||'wheat'):o.type==='house'?'home':o.type==='barn'?'shop':S.catalog.animals[o.animal]?.outputs?Object.keys(S.catalog.animals[o.animal].outputs)[0]:'workshop';
const stock=(id)=>S.me?.inventory[id]||0;
const enough=needs=>Object.entries(needs).every(([k,q])=>stock(k)>=q);
const timeText=seconds=>{seconds=Math.max(0,Math.ceil(seconds));if(seconds<60)return `${seconds} с`;const m=Math.ceil(seconds/60);if(m<60)return `${m} мин`;return m%60?`${Math.floor(m/60)} ч ${m%60} мин`:`${m/60} ч`;};
const seedTimeText=seconds=>timeText(seconds).replaceAll(' мин','м').replaceAll(' ч','ч').replaceAll(' с','с');
const duration=n=>timeText(Math.max(1,Math.ceil(n/S.speed)));
function timer(t){let n=el('span');n.dataset.until=t;updateTime(n);return n;}
function updateTime(n){const text=Number(n.dataset.until)<=now()?'Готово':(n.dataset.untilPrefix||'')+timeText(Number(n.dataset.until)-now());if(n.textContent!==text)n.textContent=text;}
function growthMeter(start,end){const bar=meter(now()-start,end-start);bar.dataset.progressStart=start;bar.dataset.progressUntil=end;return bar;}
function updateGrowthMeter(bar){const width=`${Math.max(0,Math.min(100,100*(now()-Number(bar.dataset.progressStart))/Math.max(1,Number(bar.dataset.progressUntil)-Number(bar.dataset.progressStart))))}%`;if(bar.firstElementChild.style.width!==width)bar.firstElementChild.style.width=width;}
// Quiet notices at the top, under the counters: short, translucent, never over the seed strip, and identical ones merge
// into one line with a counter. Errors stay longer and look stronger; only an error that carries a button takes clicks.
const toastList=[];let toastTimer=0;
function toast(text,error=false,action=null,ms=0){const t=pushToast(toastList,text,error,Date.now());if(action)t.action=action;if(ms)t.until=Math.max(t.until,Date.now()+ms);renderToasts();}
function renderToasts(){
 clearTimeout(toastTimer);expireToasts(toastList,Date.now());
 $('toasts').replaceChildren(...toastList.map(t=>{const n=el('div',null,`toast-item${t.error?' error':''}`);n.append(el('span',toastText(t)));if(t.action){n.classList.add('has-action');n.append(button(t.action.label,()=>{toastList.splice(toastList.indexOf(t),1);renderToasts();t.action.fn();},'toast-action'));}return n;}));
 if(toastList.length)toastTimer=setTimeout(renderToasts,Math.max(60,Math.min(...toastList.map(t=>t.until))-Date.now()+30));
}
const rateUntil={read:0,write:0};
let connectionState={text:'',bad:false};
function rateSeconds(bucket){return Math.max(0,Math.ceil((rateUntil[bucket]-Date.now())/1000));}
function retryAfter(value){
 // Farm's contract is integer seconds, 1..60. Bound untrusted headers;
 // HTTP dates and malformed values use a short fallback.
 if(typeof value!=='string'||!/^\d{1,6}$/.test(value.trim()))return 5;
 return Math.min(60,Math.max(1,Number(value.trim())));
}
function rateError(bucket){return Object.assign(new Error(`Слишком много ${bucket==='write'?'действий':'запросов'}. Повтори через ${rateSeconds(bucket)} с.`),{status:429,code:'rate_limit',rateBucket:bucket});}
function updateRateFeedback(){
 const read=rateSeconds('read'),write=rateSeconds('write');
 const waiting=[write?`Действия доступны через ${write} с`:null,read?`Обновление доступно через ${read} с`:null].filter(Boolean);
 document.querySelector('.scene-status').classList.toggle('has-error',waiting.length>0||connectionState.bad);
 $('connection').textContent=waiting.length?waiting.join(' · '):connectionState.text;
 document.querySelector('.connection-dot').style.background=waiting.length||connectionState.bad?'#bc8357':'';
 $('retry').hidden=!waiting.length&&!connectionState.bad;
 $('retry').disabled=!S.me?!!(read||write):!!rateSeconds(S.pending?'write':'read');
 const loginStatus=$('login-rate'),loginRetry=$('login-retry');
 if(loginStatus)loginStatus.textContent=waiting.length?waiting.join(' · '):connectionState.text;
 if(loginRetry)loginRetry.disabled=!!(read||write);
}
function connection(text,bad=false){connectionState={text,bad};updateRateFeedback();}
function field(label,type='text',value=''){let wrap=el('label',label,'form-field'),input=el(type==='select'?'select':'input');if(type!=='select')input.type=type;input.setAttribute('aria-label',label);input.value=value;wrap.append(input);return [wrap,input];}
function checkbox(label,value){let wrap=el('label',null,'checkbox-field'),input=el('input');input.type='checkbox';input.checked=value;wrap.append(input,el('span',label));return [wrap,input];}
function heading(title,eyebrow='НЕБОЛЬШИЕ ДЕЛА, БОЛЬШОЙ УЮТ'){let h=el('div',null,'panel-title'),a=el('div');a.append(el('div',eyebrow,'eyebrow'),el('h2',title));h.append(a,button('×',closePanel,'panel-close'));$('panel-head').replaceChildren(h);}
function note(text,parent=$('panel-content')){parent.append(el('p',text,'note'));}
const AVATARS={'Филиныч':'avatar_filinych','Агата':'avatar_agata','Почтальон Ёж':'avatar_hedgehog','Механик Крот':'avatar_mole','Кошка Кая':'avatar_kaya','Кошка Соня':'avatar_sonya','Суслик Игорь':'avatar_gopher','Неведома Зверушка':'avatar_mystery','Медведь Пух':'avatar_bear'};
function card(title,subtitle,ico){let c=el('section',null,'card');if(title){let h=el('div',null,'card-header');h.append(ico?icon(ico):AVATARS[title]?icon(AVATARS[title]):el('span',title[0],'avatar'));let t=el('div');t.append(el('strong',title));if(subtitle)t.append(el('small',subtitle));h.append(t);c.append(h);}return c;}
function goods(needs,showStock=true){let wrap=el('div',null,'goods');for(let [id,q]of Object.entries(needs)){let n=el('span',null,`good ${showStock&&stock(id)<q?'missing':''}`);n.title=itemName(id);n.append(icon(id),el('span',`${itemName(id)} ${showStock?`${stock(id)} / ${q}`:`×${q}`}`));wrap.append(n);}return wrap;}
function meter(value,max){let b=el('div',null,'progress-bar'),i=el('i');i.style.width=`${Math.min(100,100*value/Math.max(1,max))}%`;b.append(i);return b;}
function modal(title,content,actions=[]){let d=$('dialog'),b=$('dialog-body');b.replaceChildren(el('h2',title));if(typeof content==='string')b.append(el('p',content));else b.append(content);let row=el('div',null,'card-footer');row.append(...actions,button('Закрыть',()=>d.close(),'secondary'));b.append(row);d.showModal();}
const FRIEND_REQUESTS=createFriendRequests({me:()=>S.me,catalog:()=>S.catalog,el,button:(label,fn,cls,disabled)=>button(label,safe(fn),cls,disabled),card,field,note,itemName,
 now,duration:MERCH.duration,command,modal,close:()=>$('dialog').close(),rerender:()=>renderPanel(),toast,
 isBound:id=>MERCH.isBound(S.catalog,id),fetchNeighbors:()=>request(API+'/neighbors'),
 badge:count=>{const b=$('rail')?.querySelector('[data-tab=orders]');if(b){const title=count?`Заказы · ${count}`:'Заказы';b.querySelector('span').textContent=title;b.setAttribute('aria-label',title);}},
 sheet:()=>{const d=$('dialog');d.classList.add('friend-request-dialog');d.querySelector('.card-footer')?.classList.add('qw-btn-stack');d.addEventListener('close',()=>d.classList.remove('friend-request-dialog'),{once:true});}});
// Village construction and the market rows (FARM_VILLAGE_CONSTRUCTION.md): the panel logic lives in construction.js.
const CONSTR=createConstruction({me:()=>S.me,catalog:()=>S.catalog,el,button:(label,fn,cls,disabled)=>button(label,safe(fn),cls,disabled),card,note,heading,meter,itemName,fmt,now,timer,
 command,modal,close:()=>$('dialog').close(),toast,isBound:id=>MERCH.isBound(S.catalog,id),open:sheet=>openVillageConstruction(sheet),resident:npc=>chooseVillageResident(npc),
 merchant:()=>openVillageMerchant(),festival:()=>festivalTab()?selectTab('festival'):chooseVillageResident('Агата'),post:()=>FRIEND_REQUESTS.create(),warehouse:()=>selectTab('inventory')});
// Each farm owns a bounded server ledger. A local acknowledgement only controls presentation.
const neighborGiftSeen=new Map(),neighborGiftInbox=new Map();
function neighborGiftKey(id){return `qw-farm.neighbor-gifts.${id}`;}
function seenNeighborGifts(id){
 if(neighborGiftSeen.has(id))return neighborGiftSeen.get(id);
 let ids=[];try{ids=JSON.parse(localStorage.getItem(neighborGiftKey(id))||'[]');}catch{}
 const seen=new Set(Array.isArray(ids)?ids.filter(v=>typeof v==='string').slice(-40):[]);
 neighborGiftSeen.set(id,seen);return seen;
}
function queueNeighborGifts(farm){
 if(!farm?.id||farm.id!==S.me?.id)return;
 const seen=seenNeighborGifts(farm.id),inbox=neighborGiftInbox.get(farm.id)||new Map();
 for(const reward of farm.neighbor_bonus?.rewards||[]){
  if(typeof reward?.id!=='string'||typeof reward.partner_name!=='string'||!Number.isFinite(reward.amount)||reward.amount<=0||seen.has(reward.id))continue;
  inbox.set(reward.id,reward);
 }
 neighborGiftInbox.set(farm.id,inbox);showNeighborGifts();
}
function showNeighborGifts(){
 const id=S.me?.id,d=$('dialog'),inbox=neighborGiftInbox.get(id);
 if(!id||!inbox?.size||document.hidden||d.open)return false;
 const rewards=[...inbox.values()],amount=rewards.reduce((sum,r)=>sum+r.amount,0);
 const box=el('div',null,'neighbor-reward');
 const art=el('div',null,'neighbor-reward-art');art.append(icon('gift'),icon('coin'));
 const title=rewards.length===1?'Подарок от соседства':'Подарки от соседей';
 const names=rewards.map(r=>r.partner_name).join(', ');
 box.append(art,el('div','ДОБРО ПОЖАЛОВАТЬ В СОСЕДИ','neighbor-reward-eyebrow'),
            el('div',`+${fmt(amount)}`,'neighbor-reward-amount'),el('div','монет на твою ферму','neighbor-reward-unit'),
            el('p',rewards.length===1?`Вы с ${names} стали соседями. Подарок уже в твоей копилке.`:
               `Новые соседи: ${names}. Все подарки уже в твоей копилке.`,'neighbor-reward-copy'));
 const body=$('dialog-body');body.replaceChildren(box);
 const action=button('Здорово!',()=>d.close(),'primary wide');box.append(action);
 d.classList.add('neighbor-reward-dialog');d.setAttribute('aria-label',`${title}: +${amount} монет. ${names}`);
 try{d.showModal();}catch{d.classList.remove('neighbor-reward-dialog');d.removeAttribute('aria-label');return false;}
 // Acknowledge only once the modal is visible; a different account never consumes this inbox.
 const seen=seenNeighborGifts(id);for(const r of rewards){seen.add(r.id);inbox.delete(r.id);}
 try{localStorage.setItem(neighborGiftKey(id),JSON.stringify([...seen].slice(-40)));}catch{}
 action.focus();return true;
}
function closeNeighborGift(){
 const d=$('dialog');d.classList.remove('neighbor-reward-dialog');d.removeAttribute('aria-label');
 if(S.me)showNeighborGifts();
}
$('dialog').addEventListener('close',closeNeighborGift);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)showNeighborGifts();});
function safe(fn){return async()=>{try{await fn();}catch(e){if(!e.sessionEnded)toast(e.message,true);}};}
function url(path){return path+(mode&&path.startsWith(API)?`${path.includes('?')?'&':'?'}identity=${encodeURIComponent(mode)}`:'');}
let authRecovery=null,lastSessionRenewal=0;
const SESSION_ENDED='Сессия завершена. Урожай, постройки и выполненная работа сохранены на сервере.';
// Renewal retains the existing account. A new Telegram login is attempted only for
// the explicitly selected Telegram identity, and the server validates initData.
async function recoverFarmSession(renewFailed=false){
 if(authRecovery)return authRecovery;
 const identity=S.me?.id,selectedMode=mode,viewEpoch=farmViewEpoch;
 authRecovery=(async()=>{
  if(S.config?.demo||!['telegram','guest'].includes(selectedMode))return false;
  try{
   if(renewFailed)throw Object.assign(new Error(),{status:401});
   await requestRaw(selectedMode==='telegram'?'/api/mini/session/renew':'/api/guest/resume',{method:'POST'});
  }catch(e){
   if(e.status!==401||selectedMode!=='telegram')return false;
   // The shell loads the pinned SDK asynchronously and only for Telegram launches (UI_RULES §7); wait for it here.
   // QW.tg is set only when Telegram passed signed launch data (restored from sessionStorage after in-tab navigation).
   await QW?.telegramReady;
   const initData=QW?.tg?.initData;
   // Old launch data cannot authorize a new session. Do not repeatedly submit it.
   const authDate=Number(new URLSearchParams(initData||'').get('auth_date'));
   const age=Date.now()/1000-authDate;
   if(!initData||!authDate||age>300||age< -30)return false;
   try{await requestRaw('/api/mini/session',{method:'POST',data:{init_data:initData}});}catch{return false;}
  }
  if(mode!==selectedMode||(identity?S.me?.id!==identity:viewEpoch!==farmViewEpoch))return false;
  if(identity){
   let me;try{me=await requestRaw(API+'/me');}catch{return false;}
   // Never replay an old account's receipt with another account's session.
   if(me.farm.id!==identity||S.me?.id!==identity)return false;
  }
  lastSessionRenewal=Date.now();return true;
 })();
 try{return await authRecovery;}finally{authRecovery=null;}
}
async function request(path,options={}){
 const identity=S.me?.id;
 try{return await requestRaw(path,options);}catch(e){
  if(e.status!==401||!path.startsWith(API+'/'))throw e;
  if(identity&&S.me?.id!==identity){e.sessionEnded=true;throw e;}
  if(await recoverFarmSession()){
   try{return await requestRaw(path,options);}catch(retryError){if(retryError.status!==401)throw retryError;e=retryError;}
  }
  if(!identity||S.me?.id===identity)showLogin(SESSION_ENDED);
  e.sessionEnded=true;throw e;
 }
}
async function requestRaw(path,{method='GET',data}={}){
 const farmRequest=path.startsWith(API+'/'),bucket=['GET','HEAD'].includes(method.toUpperCase())?'read':'write';
 if(farmRequest&&rateSeconds(bucket)){updateRateFeedback();throw rateError(bucket);}
 const ctrl=new AbortController(),t=setTimeout(()=>ctrl.abort(),12000);
 try{let r=await fetch(url(path),{method,credentials:'same-origin',headers:{'X-QW-Farm':'1',...(path.startsWith('/api/mini/')?{'X-Mini-CSRF':'1'}:path.startsWith('/api/guest/')?{'X-Guest-CSRF':'1'}:path.startsWith('/api/account/')?{'X-Guest-CSRF':'1','X-Mini-CSRF':'1'}:{}),...(data!==undefined?{'Content-Type':'application/json'}:{})},body:data===undefined?undefined:JSON.stringify(data),signal:ctrl.signal});
  // Handle 429 before JSON: a proxy rejection must also retain the receipt.
  if(r.status===429&&farmRequest){
   // Only a real rate limit (no body at all, or code rate_limit/busy) opens the waiting window. Any other 429 (for example
   // daily_limit: «на сегодня хватит») is an ordinary answer of the game and must never block the commands that follow.
   let body=null;try{body=await r.json();}catch{}
   if(body&&body.code&&!['rate_limit','busy'].includes(body.code))throw Object.assign(new Error(body.message||'Действие не удалось.'),{status:429,code:body.code});
   rateUntil[bucket]=Math.max(rateUntil[bucket],Date.now()+retryAfter(r.headers?.get('Retry-After'))*1000);connection('Можно повторить запрос',true);throw rateError(bucket);}
  let value;try{value=await r.json();}catch{throw Object.assign(new Error('Сервер вернул непонятный ответ.'),{unknown:true});}if(!r.ok)throw Object.assign(new Error(value.message||value.detail||'Действие не удалось.'),{status:r.status,code:value.code,unknown:r.status>=500});return value;
 }catch(e){if(e.name==='AbortError'||e instanceof TypeError)throw Object.assign(new Error('Связь прервалась. Действие можно безопасно повторить.'),{unknown:true});throw e;}finally{clearTimeout(t);}
}
function pendingKey(id=S.pending?.actor||S.me?.id){return `qw-farm.pending.${id||''}`;}
function savePending(id){try{if(S.pending)sessionStorage.setItem(pendingKey(id),JSON.stringify(S.pending));else sessionStorage.removeItem(pendingKey(id));}catch{}}
let farmViewEpoch=0,refreshEpoch=0;
// server_time is a clock sample, not a state change. Keep all other fields,
// including permissions and server-computed rewards, in the comparison.
function farmSnapshot(farm){if(!farm)return null;const {server_time,...state}=farm;return state;}
function sceneSnapshot(){return JSON.stringify(farmSnapshot(S.farm));}
function hudSnapshot(){return JSON.stringify([S.me?.coins,S.me?.level,S.me?.xp,S.me?.xp_bonus,S.me?.economy_status?.debt,S.farm?.id,S.farm?.name,S.farm?.level,S.farm?.is_owner]);}
function seedsSnapshot(){return JSON.stringify([S.farm?.is_owner,S.me?.level,S.speed]);}
// A deadline can change the visible action without changing a revision. Timers
// update in place; only deadline transitions need to rebuild their buttons.
function readySnapshot(){
 const t=now(),due=at=>typeof at==='number'&&at<=t;
 return JSON.stringify([
  (S.farm?.objects||[]).map(o=>[(o.jobs||[]).map(j=>[due(j.starts_at),due(j.ready_at)]),due(o.animal_job?.ready_at),due(o.crop?.ready_at),due(o.fruit?.ready_at)]),
  (S.me?.trips||[]).map(trip=>[due(trip.ready_at),due(trip.started_at+(S.catalog?.undo?.window||60))]),
  (S.me?.fields||[]).map(f=>[due(f.crop?.ready_at),due(f.run?.done_at),due(f.run?.expires_at)]),
  due(S.me?.economy_status?.feast_until),
  S.tab==='village'?Math.max(0,Math.ceil(((S.me?.economy_status?.season_ends_at||t)-t)/86400)):null,
  due(S.me?.market?.caravan_next_at),due(S.me?.swans?.next_at),
  Object.values(S.me?.minigames||{}).map(game=>[due(game.available_at),game.active?due(game.active.expires_at):false]),
  Math.floor((t+10800)/86400)
 ]);
}
let panelRenderSignature='';
function panelSnapshot(){return JSON.stringify([farmSnapshot(S.me),farmSnapshot(S.farm),S.village,S.speed,S.tab,S.selected,S.seed,readySnapshot()]);}
async function refresh({render=true}={}){
 const viewEpoch=farmViewEpoch,requestEpoch=++refreshEpoch,identity=S.me?.id,id=S.farm?.id;
 const current=()=>viewEpoch===farmViewEpoch&&requestEpoch===refreshEpoch&&S.me?.id===identity&&S.farm?.id===id;
 let me;try{me=await request(API+'/me');}catch(e){if(!current())return false;throw e;}if(!current())return false;
 if(me.farm.id!==identity){showLogin('Сессия сменилась. Открой ферму заново.');return false;}
 let farm=me.farm,lostAccess=false;
 if(id&&id!==identity){try{farm=(await request(API+'/farms/'+id)).farm;}catch(e){if(!current())return false;if([403,404].includes(e.status))lostAccess=true;else throw e;}}
 if(!current())return false;
 const beforeScene=sceneSnapshot(),beforeHUD=hudSnapshot(),beforeSeeds=seedsSnapshot(),prevLevel=S.me?.level??null;
 S.form=me.address_form||'n';S.me=me.farm;S.village=me.village||null;S.speed=me.speed;S.offset=S.me.server_time-Date.now()/1000;S.farm=lostAccess?S.me:farm;dashaGame?.render();olegGame?.render();
 queueNeighborGifts(S.me);FRIEND_REQUESTS.notify();syncOrchardBadge();orchardNotices(prevLevel);
 if(lostAccess){farmViewEpoch++;S.tab='neighbors';toast(gf('Хозяин закрыл доступ. Ты вернулся на свою ферму.','Хозяин закрыл доступ. Ты вернулась на свою ферму.','Доступ закрыт владельцем. Открыта твоя ферма.'));}
 if(beforeScene!==sceneSnapshot())scene.set(S.farm,S.catalog);
 else scene.serverOffset=S.farm.server_time-Date.now()/1000;
 if(beforeHUD!==hudSnapshot())updateHUD();
 if(beforeSeeds!==seedsSnapshot())renderSeeds();
 updateReady();
 if((render||lostAccess)&&!S.placing)renderPanel();
 connection(S.pending?'Есть неподтверждённое действие':S.config.demo?`Локальный сервер · темп ×${S.speed}`:'Сохранено в QuizzyWizzy',!!S.pending);
 return true;
}
async function command(kind,data={},target=null){
 if(S.busy||!S.me)return false;
 if(rateSeconds('write')){updateRateFeedback();toast(rateError('write').message,true);return false;}
 if(S.pending){toast('Подтверждаем прошлое действие — секунду.',false);sendPending().catch(()=>{});return false;}
 S.pending={command_id:crypto.randomUUID(),kind,data,target:target||S.me.id,actor:S.me.id};savePending();return sendPending();
}
// An unconfirmed command is retried automatically with the same command_id (the server is idempotent),
// so a lost response never leaves the player blocked behind a tiny retry button.
let pendingRetryTimer=null,pendingRetryAttempt=0;
function schedulePendingRetry(e){
 clearTimeout(pendingRetryTimer);
 const delays=[2,5,10,20,30],wait=delays[Math.min(pendingRetryAttempt,delays.length-1)];
 pendingRetryAttempt++;
 if(pendingRetryAttempt>delays.length+3){toast('Не удаётся подтвердить действие. Проверь интернет и нажми «Повторить».',true,{label:'Повторить',fn:()=>{pendingRetryAttempt=0;sendPending().catch(()=>{});}});return;}
 connection(`Связь прервалась — повторим через ${wait} с`,true);
 pendingRetryTimer=setTimeout(()=>{sendPending().then(ok=>{if(ok)pendingRetryAttempt=0;}).catch(()=>{});},wait*1000);
}
async function sendPending(){
 if(!S.me||!S.pending||S.pending.actor!==S.me.id||S.busy)return false;clearTimeout(pendingRetryTimer);pendingRetryTimer=null;S.busy=true;connection('Сохраняем действие…');document.body.classList.add('is-saving');
 let payload=S.pending,rejectedWagerRoundId=null;
 try{let r=await request(API+'/commands',{method:'POST',data:payload});rememberMachineCommand(payload);S.pending=null;savePending(payload.actor);rateRecoveryAttempt=0;if(!S.me)return true;if(!r.neighbor_reward_paid)toast(localizeWagerNotice(r.notice,gf));await refresh({render:false}).catch(e=>{if(e.sessionEnded)return;connection('Сохранено; обновление экрана ожидает сети',true);if(e.rateBucket)scheduleRateRecovery();});return true;}
 catch(e){if(e.sessionEnded)return false;if(!e.unknown&&!e.rateBucket){S.pending=null;savePending(payload.actor);if(payload.kind==='wager_choose')rejectedWagerRoundId=payload.data.round_id;}connection(S.pending?'Нужно подтвердить результат':'Действие не выполнено',true);if(e.rateBucket){if(S.pending)scheduleRateRecovery();}else if(S.pending)schedulePendingRetry(e);else toast(e.message,true);if(!S.pending)await refresh({render:false}).catch(()=>{});return false;}
 finally{S.busy=false;document.body.classList.remove('is-saving');updateRepeat();dashaGame?.render();olegGame?.render();if(rejectedWagerRoundId)dashaGame?.choiceRejected(rejectedWagerRoundId);if(S.me&&!S.pending&&!S.placing)renderPanel();}
}
// After a real 429 the game recovers by itself: wait out Retry-After, then replay the unconfirmed command with the SAME id
// (the server is idempotent) or just refresh the screen. No reload is needed.
let rateRecoveryTimer=null,rateRecoveryAttempt=0;
function scheduleRateRecovery(){
 if(rateRecoveryTimer||!S.me)return;
 if(++rateRecoveryAttempt>8){rateRecoveryAttempt=0;toast('Сервер просит подождать. Нажми «Повторить» чуть позже.',true);return;}
 const wait=Math.max(1,rateSeconds('write'),rateSeconds('read'));
 rateRecoveryTimer=setTimeout(async()=>{
  rateRecoveryTimer=null;if(!S.me)return;
  try{if(S.pending){if(await sendPending())rateRecoveryAttempt=0;}else if(await refresh())rateRecoveryAttempt=0;}
  catch(e){if(e.rateBucket)scheduleRateRecovery();}
 },wait*1000+250);
}
async function enter(){
 const epoch=++farmViewEpoch;
 try{let data=await request(API+'/start',{method:'POST',...(S.invite?{data:{invite:S.invite}}:{})});if(epoch!==farmViewEpoch)return;if(['guest','telegram'].includes(data.identity))mode=data.identity;S.form=data.address_form||'n';S.me=S.farm=data.farm;S.lastRun=loadLastRun(S.me.id);S.catalog=data.catalog;S.village=data.village||null;S.speed=data.speed;S.offset=S.me.server_time-Date.now()/1000;resetVillageView();
  // A direct invite URL may bypass the main-app launcher. Once this session
  // has entered Farm, returning to /app must not launch the same invite again.
  if(S.invite)try{sessionStorage.setItem('qw-farm.launch-consumed',S.invite);}catch{}
  try{S.pending=JSON.parse(sessionStorage.getItem(pendingKey(S.me.id))||'null');if(S.pending&&S.pending.actor!==S.me.id)S.pending=null;}catch{S.pending=null;}
 document.body.classList.remove('farm-login');$('game').hidden=false;$('login').hidden=true;if(S.invite&&S.invite!==S.me.id){S.tab='neighbors';showPanel();}renderRail();updateHUD();scene.set(S.farm,S.catalog);scene.resize();scene.fit();renderSeeds();renderPanel();updateReady();connection(S.config.demo?`Локальный сервер · темп ×${S.speed}`:'Сохранено в QuizzyWizzy',!!S.pending);queueNeighborGifts(S.me);FRIEND_REQUESTS.notify();orchardNotices();if(S.pending)setTimeout(()=>sendPending().catch(()=>{}),300);
  renewPlatformSession().catch(()=>{});
 }catch(e){if(epoch!==farmViewEpoch)return;if(e.status===401)showLogin(SESSION_ENDED);else{showLogin(e.message);toast(e.message,true);}}
}
function showLogin(message=''){
 const lakeDoor=$('lake-door');if(lakeDoor)lakeDoor.hidden=true;
 // Keep an unknown command's receipt under its original actor for the next login.
 if(S.pending)savePending();
 clearTimeout(pendingRetryTimer);pendingRetryTimer=null;pendingRetryAttempt=0;
 clearTimeout(rateRecoveryTimer);rateRecoveryTimer=null;rateRecoveryAttempt=0;
 if(dashaGameOpen)closeDashaGame();if(olegGameOpen)closeOlegGame();farmViewEpoch++;S.me=S.farm=null;S.lastRun=null;S.pending=null;S.selected=null;resetVillageView();
 S.fieldGame?.close();cancelPlacement();if($('dialog').open)$('dialog').close();closePanel();
 toastList.length=0;renderToasts();connection(message||'Войди через QuizzyWizzy',true);
 document.body.classList.add('farm-login');$('game').hidden=true;$('login').hidden=false;const parent=$('login');parent.replaceChildren();let c=el('div',null,'login-card'),img=el('img',null,'login-hero');img.src='/app/farm-card-v2.webp';img.alt='Филиныч с урожаем на своей ферме';c.append(img);
 const ended=message===SESSION_ENDED||message==='Сессия сменилась. Открой ферму заново.';
 if(ended){c.append(el('div','QUIZZYWIZZY · ПРОГРЕСС СОХРАНЁН','eyebrow'),el('h1','Вернуться на ферму'));note('Войди в QuizzyWizzy и снова открой ферму. Урожай, постройки и выполненная работа сохранены.',c);const link=quizzyLoginLink();link.classList.add('login-return-link');link.setAttribute('aria-label','Войти через QuizzyWizzy и вернуться на ферму');c.append(link);
 }else{c.append(el('div','QUIZZYWIZZY · СВОЁ МЕСТО ПОД СОЛНЦЕМ','eyebrow'),el('h1','Весёлый фермер'));note('Сажай, строй, пеки хлеб. Навещай соседей и не доверяй слишком серьёзным гусям.',c);if(message)note(message,c);c.append(quizzyLoginLink());}
 if(S.config?.demo){note('Это отдельная локальная альфа. Сохранения находятся на запущенном сервере, а не в QuizzyWizzy.',c);let form=el('form'),[w,input]=field('Имя на ферме');input.minLength=2;input.maxLength=20;input.required=true;input.autocomplete='nickname';input.placeholder='Например, Мария';let b=button('Открыть свою ферму',()=>{},'primary wide');b.type='submit';form.append(w,b);form.onsubmit=async e=>{e.preventDefault();b.disabled=true;try{let r=await request('/api/farm-demo/session',{method:'POST',data:{name:input.value}});await enter();showRecovery(r.recovery);}catch(err){toast(err.message,true);}finally{b.disabled=false;}};c.append(form);
 let details=el('details'),summary=el('summary','Уже есть ферма? Войти по коду'),rf=el('form'),[rw,ri]=field('Код восстановления','password');ri.required=true;ri.autocomplete='off';let rb=button('Вернуться на ферму',()=>{},'secondary wide');rb.type='submit';rf.append(rw,rb);rf.onsubmit=async e=>{e.preventDefault();rb.disabled=true;try{await request('/api/farm-demo/session',{method:'POST',data:{recovery:ri.value.trim()}});ri.value='';await enter();}catch(err){toast(err.message,true);}finally{rb.disabled=false;}};details.append(summary,rf);c.append(details);
 }else{note(mode==='telegram'?'В Telegram закрой игру и открой её заново: так Telegram передаст свежие данные входа. Или перейди на главную QuizzyWizzy и войди в свой аккаунт.':'Войди в свой аккаунт на главной QuizzyWizzy и снова открой ферму.',c);}
 if(rateSeconds('read')||rateSeconds('write')){let status=el('p',null,'note');status.id='login-rate';status.setAttribute('role','status');let retry=button('Повторить',safe(retryConnection),'secondary wide');retry.id='login-retry';c.append(status,retry);}
 parent.append(c);$('hud').replaceChildren(el('small','Урожай никуда не спешит'));updateRateFeedback();
}
function showRecovery(code){if(!code)return;let wrap=el('div');wrap.append(el('p','Сохрани этот секретный код. Он откроет ту же ферму в другом браузере на этом сервере. Не отправляй его соседям: для соседства используется другой, публичный код.'),el('div',code,'code'));
 modal('Ключ от твоей калитки',wrap,[button('Сохранить ключ',()=>{let a=el('a');a.href=URL.createObjectURL(new Blob([`QuizzyWizzy Farm — локальная альфа\nКод восстановления (секрет): ${code}\nСервер: ${location.origin}\n`],{type:'text/plain;charset=utf-8'}));a.download='farm-recovery.txt';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);},'primary')]);}
function updateHUD(){
 if(!S.me)return;document.body.classList.toggle('farm-visit',!own());const lakeDoor=$('lake-door');if(lakeDoor)lakeDoor.hidden=false;const villageCardDoor=$('village-card-door');if(villageCardDoor)villageCardDoor.hidden=false;$('find-button').hidden=!own();let coins=el('div',null,'hud-token');coins.append(icon('coin'),el('span',fmt(S.me.coins)));let xp=el('div',null,'hud-token');xp.append(icon('star'));let x=el('div');x.append(el('span',`${S.me.level} ур.`));let next=S.catalog.levels[S.me.level],start=S.catalog.levels[S.me.level-1],b=el('div',null,'level-progress'),i=el('i');i.style.width=`${next?100*(S.me.xp-start)/(next-start):100}%`;b.append(i);x.append(b);let bn=S.me.xp_bonus,tip=[];if(bn&&bn.dew_left>0)tip.push(['Роса',`Утренняя роса: ещё ${fmt(bn.dew_left)} опыта сегодня идёт с двойной наградой`]);if(bn&&bn.pool>0)tip.push(['Бодрость',`Бодрость: ещё ${fmt(bn.pool)} опыта вернётся двойной наградой`]);if(tip.length){let t=el('small',null,'hud-bonus');tip.forEach((q,n)=>t.append(el('span',n?` · ${q[0]}`:q[0])));t.title=tip.map(q=>q[1]).join('. ');t.setAttribute('aria-label',t.title);x.append(t);}xp.append(x);xp.title=`${S.me.xp} опыта${next?`, до следующего уровня ${next-S.me.xp}`:', максимальный уровень'}`;$('hud').replaceChildren(...[coins,xp,eco()?.debt>0?hudDebt():null].filter(Boolean));
 const stage=[[2,'Огород'],[5,'Участок'],[8,'Хозяйство'],[12,'Ферма'],[17,'Большая ферма'],[29,'Усадьба']].find(([max])=>S.farm.level<=max)?.[1]||'Усадьба';
 const ownerName=S.farm.name.replace(/^Ферма\s+/i,'').trim(),displayName=`${stage} ${ownerName||S.farm.name}`;
 $('farm-name').textContent=displayName;
 $('farm-caption').textContent=own()?'СВОЁ МЕСТО ПОД СОЛНЦЕМ':'ХОРОШИЕ СОСЕДИ · ХОРОШИЙ ДЕНЬ';$('farm-subtitle').textContent=own()?'Растёт, пока ты занимаешься своими делами.':'В гостях: можно помочь, а хозяйничать будет владелец.';$('return-home').hidden=own();$('fields-door').hidden=!own()||!(S.catalog.fields&&S.me.level>=S.catalog.fields.min_level);$('object-list-button').textContent='Список объектов';
}
const tabs=[['orders','orders','Заказы'],['inventory','shop','Склад'],['fields','tractor','Поля'],['build','home','Строить'],['production','workshop','Мастерские'],['team','tractor','Команда'],['forest','forest','В лес'],['lake','lake','Озеро'],['neighbors','friends','Соседи'],['secrets','discovery','Находки'],['journal','journal','Журнал'],['village','coin','Деревня'],['orchard','orchard','Сад'],['festival','coin','Праздник']];
function renderRail(){
 const mobile=matchMedia('(max-width:850px)').matches;
 const mainTabs=new Set(['orders','inventory','fields','build','production','team','forest','lake','neighbors']);
 const shown=tabs.filter(([id])=>id!=='festival'||festivalTab()),entries=mobile?[...shown.filter(([id])=>mainTabs.has(id)),['more','menu','Ещё']]:shown;
 const rail=$('rail');rail.replaceChildren();for(let [id,ic,title]of entries){let b=button(null,()=>selectTab(id),'',false);b.append(icon(ic),el('span',title));b.dataset.tab=id;b.setAttribute('aria-label',title);b.classList.toggle('active',id===S.tab||id==='more'&&!entries.some(([k])=>k===S.tab));rail.append(b);}
 FRIEND_REQUESTS.notify();syncOrchardBadge();syncNav();
 if(mobile)requestAnimationFrame(()=>{const active=rail.querySelector('.active');if(active)rail.scrollTo({left:Math.max(0,active.offsetLeft-(rail.clientWidth-active.offsetWidth)/2),behavior:'smooth'});});
}
function selectTab(id){if(dashaGameOpen)closeDashaGame();if(olegGameOpen)closeOlegGame();const wasVillage=S.tab==='village';farmViewEpoch++;if(id==='village'&&S.me&&S.farm?.id!==S.me.id){S.farm=S.me;scene.set(S.me,S.catalog);updateHUD();renderSeeds();}S.tab=id;S.selected=null;scene.selected=null;if(id!=='village'){villageResident=null;villageSheet=null;if(wasVillage&&typeof villagePresenceStop==='function')villagePresenceStop();}if(id==='village'){villageResident=null;villageSheet=null;document.body.classList.remove('panel-open');document.body.classList.add('panel-collapsed');if(!wasVillage&&typeof villagePresenceStart==='function')villagePresenceStart();}else showPanel();renderRail();renderPanel();}
function exitVillage(){villageSheet=null;selectTab('orders');closePanel();}
function returnToFarm(){if(villageVisible())exitVillage();else backHome();}
function resetVillageView(){if(typeof villagePresenceStop==='function')villagePresenceStop();villageResident=null;villageSheet=null;villageSceneSignature='';villagePos=[...VILLAGE_START];villageWalkStop();syncVillageScene();villageCenter(villagePos,false);if(S.tab==='village'&&typeof villagePresenceStart==='function')villagePresenceStart();}
function openVillageTownHall(section=null){if(!villageVisible())selectTab('village');villageResident=null;villageSheet='townhall';showPanel();renderPanel();const title=$('panel-head').querySelector('h2');if(title){title.tabIndex=-1;title.focus({preventScroll:true});}if(section){const details=[...$('panel-content').querySelectorAll('.village-services')].find(n=>n.dataset.villageService===section);if(details){details.open=true;details.scrollIntoView({block:'nearest'});}}}
function syncScenePause(){scene.setPaused(!!S.fieldGame||villageVisible());}
function villageVisible(){return !!S.me&&S.tab==='village';}
let seedCardVisible=false,seedCardTimer=0;
function showSeedCard(ms=0){seedCardVisible=true;clearTimeout(seedCardTimer);updateSeedCard();if(ms)seedCardTimer=setTimeout(hideSeedCard,ms);}
function hideSeedCard(){clearTimeout(seedCardTimer);seedCardVisible=false;$('seedcard').hidden=true;}
function renderSeeds(){const parent=$('seedbar'),scroll=parent.scrollLeft;parent.replaceChildren();parent.hidden=!own();$('quick-stack').hidden=!own();$('harvest-all').hidden=!own();updateSeedCard();updateRepeat();if(!own())return;parent.append(el('div','ПОСАДИТЬ','seedbar-label'));
 for(let c of sortSeeds(Object.values(S.catalog.crops).filter(c=>!c.exotic&&!c.orchard),S.me.level)){let locked=c.level>S.me.level,st=seedStats(c,S.catalog.items[c.id].price,S.speed,S.catalog.crop_classes),b=button(null,()=>{S.seed=c.id;renderSeeds();showSeedCard(2600);document.body.classList.remove('panel-open');},`seed ${S.seed===c.id?'active':''} cls-${st.cls}`,locked);b.addEventListener('pointerenter',()=>{if(c.id===S.seed)showSeedCard(2600);});b.addEventListener('pointerleave',()=>{if(c.id===S.seed)hideSeedCard();});b.addEventListener('focus',()=>{if(c.id===S.seed)showSeedCard(2600);});b.addEventListener('blur',()=>{if(c.id===S.seed)hideSeedCard();});const details=el('small',null,'seed-details');if(locked)details.append(el('span',`С ${c.level} ур.`));else details.append(el('span',`${fmt(c.cost)} мон.`),el('span',seedTimeText(st.seconds)));b.append(icon(c.id),el('span',c.name),details);b.dataset.class=st.cls;b.setAttribute('aria-label',locked?`${c.name}: нужен уровень ${c.level}`:seedLine(c,st));parent.append(b);}
 for(const k of MERCH.seedPacks(S.catalog,stock,S.me.level)){const b=button(null,()=>{S.seed=k.id;renderSeeds();document.body.classList.remove('panel-open');},`seed ${S.seed===k.id?'active':''} cls-pack`);b.dataset.seedPack=k.id;const d=el('small',null,'seed-details');d.append(el('span','из пакета'),el('span',`осталось ${k.left}`));b.append(icon(k.id),el('span',k.name),d);b.setAttribute('aria-label',`${k.name}: посадить из пакета, осталось ${k.left}`);parent.append(b);}
 // Fruit trees left the beds for the «Сад» tab: one card of the same size at the end of the strip leads there.
 if(S.catalog.orchard){const b=button(null,openOrchard,'seed seed-orchard'),d=el('small',null,'seed-details');b.dataset.qwCrumb='seed-orchard';d.append(el('span','→ Сад'));b.append(icon('orchard'),el('span','Деревья'),d);b.setAttribute('aria-label','Фруктовые деревья сажают в разделе «Сад». Открыть Сад');parent.append(b);}
 parent.scrollLeft=scroll;}
function seedLine(c,st){return `${c.name} — семена ${fmt(c.cost)} мон., ${st.label}, ${timeText(st.seconds)}, урожай ×${c.yield_qty}, ≈${fmt(st.perHour)} мон./ч, ≈${fmt(st.xpPerHour)} опыта/ч`+(st.cls==='long'?`. ${LONG_HINT}.`:'');}
// The card of the chosen seed: class, time, income and XP per hour, and a hint for long crops.
function updateSeedCard(){const box=$('seedcard'),c=S.catalog?.crops[S.seed];if(!own()||!c||c.exotic||c.level>S.me.level){box.hidden=true;return;}
 const st=seedStats(c,S.catalog.items[c.id].price,S.speed,S.catalog.crop_classes),sig=[c.id,st.seconds,S.me.level].join();if(box.dataset.sig===sig){box.hidden=!seedCardVisible;return;}box.dataset.sig=sig;box.hidden=!seedCardVisible;box.dataset.class=st.cls;
 const head=el('div',null,'seedcard-head');head.append(el('b',c.name),el('span',st.label,'seedcard-class'),el('span',timeText(st.seconds)));
 box.replaceChildren(head,el('div',`урожай ×${c.yield_qty} · ≈${fmt(st.perHour)} мон./ч · ≈${fmt(st.xpPerHour)} опыта/ч`,'seedcard-line'));
 if(st.cls==='long')box.append(el('div',LONG_HINT,'seedcard-hint'));}
// «Repeat the run»: the last machine (tractor / combine) with its crop and replanting. The server checks every plot again.
function updateRepeat(){const b=$('repeat-run');if(!b)return;if(!own()||!S.me||!S.catalog){b.hidden=true;return;}
 const p=planRepeat(S.lastRun,S.seed,S.me,S.catalog,now());b.hidden=!p.ok;if(!p.ok)return;const sig=[p.ok,p.label,p.why,p.cost].join('|');b.disabled=!p.ok||S.busy||!!rateSeconds('write');b.classList.toggle('is-off',!p.ok);
 if(b.dataset.sig!==sig){b.dataset.sig=sig;b.replaceChildren(el('span','Повторить рейс'),el('small',p.ok?p.label:p.why));b.title=p.ok?`${p.label}. Семена: ${fmt(p.cost)} мон.`:p.why;b.setAttribute('aria-label',p.ok?`Повторить рейс: ${p.label}`:`Повторить рейс недоступен: ${p.why}`);}}
async function runPlan(plan){if(!plan.ok){toast(plan.why,true);return false;}
 const ok=await command('machine_run',{machine:plan.machine,crop:plan.crop,plots:plan.plots,replant:plan.replant});
 return ok;}
function tapMachine(id){const plan=planTap(id,S.lastRun,S.me,S.catalog,now());
 if(plan){runPlan(plan);return;}
 const spec=S.catalog.equipment[id],box=el('div');
 if(id==='tractor'){const [w,sel]=field('Культура для трактора','select');
  for(const crop of sortSeeds(Object.values(S.catalog.crops).filter(c=>!c.exotic&&!c.orchard),S.me.level).filter(c=>c.level<=S.me.level)){const st=seedStats(crop,S.catalog.items[crop.id].price,S.speed,S.catalog.crop_classes),o=el('option',`${crop.name} · ${st.label} · ${timeText(st.seconds)} · ${crop.cost} мон.`);o.value=crop.id;sel.append(o);}
  sel.value=S.catalog.crops[S.seed]?.level<=S.me.level?S.seed:sel.options[0]?.value;box.append(w,el('p','Засеет свободные грядки (до 24 за рейс). В следующий раз машина по нажатию повторит этот рейс сама.','note'));
  modal(spec.name,box,[button('Засеять',safe(async()=>{const plan=planMachine({machine:id,crop:sel.value,replant:false},S.me,S.catalog,now());if(!plan.ok){toast(plan.why,true);return;}$('dialog').close();await runPlan(plan);}),'primary')]);return;}
 const [w,replant]=checkbox('Сразу пересеять те же культуры',true);box.append(w,el('p','Уберёт готовые зерновые (до 24 грядок за рейс). В следующий раз машина по нажатию повторит этот рейс сама.','note'));
 modal(spec.name,box,[button('Отправить комбайн',safe(async()=>{const plan=planMachine({machine:id,crop:'',replant:replant.checked},S.me,S.catalog,now());if(!plan.ok){toast(plan.why,true);return;}$('dialog').close();await runPlan(plan);}),'primary')]);}
let readiness='';
function updateReady(){updateRateFeedback();if(!S.farm)return;updateRepeat();let stamp=readySnapshot();if(stamp!==readiness){readiness=stamp;if(S.tab==='fields'&&own()&&!S.fieldGame)poll();if(['object','forest','lake','team','objects','production','village'].includes(S.tab)&&!['INPUT','SELECT','TEXTAREA'].includes(document.activeElement?.tagName)&&!S.busy&&!S.placing&&!$('dialog').open)renderPanel();}let count=S.farm.objects.filter(o=>(o.crop&&o.crop.ready_at<=now())||ORCH.ripe(o,now())).length;$('harvest-all').querySelector('span').textContent=count?`Собрать урожай · ${count}`:'Урожай растёт';$('harvest-all').disabled=!count||S.busy||!!rateSeconds('write');document.querySelectorAll('[data-until]').forEach(updateTime);document.querySelectorAll('[data-progress-until]').forEach(updateGrowthMeter);}
function clickObject(o,cell){hideStoneSpeech();
 if(S.placing){
  const p=S.placing;if(p.committing)return;
  const sameCell=!!cell&&!!p.cell&&cell.x===p.cell.x&&cell.y===p.cell.y;
  p.cell=cell;scene.placement.cell=cell;scene.hover=cell;renderPlacement();
  if(sameCell)safe(()=>commitPlacement(p))();
  return;
 }
 if(!o)return;
 if(o.type==='lake'){selectTab('lake');return;}
 if(o.type==='arbor'){selectTab('arbor');return;}
 if(o.type==='stone'){showStoneSpeech();return;}
 if(o.type==='machine'){if(own())tapMachine(o.machine);return;}
 if(o.type==='tree'&&own()&&ORCH.ripe(o,now())){command('harvest',{object:o.id,revision:o.revision}).then(ok=>{if(ok)scene.burst(o);});return;}
 if(o.type==='plot'&&own()){
  if(o.crop&&o.crop.ready_at<=now()){command('harvest',{object:o.id,revision:o.revision}).then(ok=>{if(ok)scene.burst(o);});return;}
  if(!o.crop){const r=MERCH.plantRequest(o,S.seed,S.catalog,stock);if(r.error){toast(r.error,true);S.seed='wheat';renderSeeds();return;}command(...r.command);return;}
 }
 farmViewEpoch++;S.selected=o.id;S.tab='object';scene.focus(o);showPanel();renderRail();renderPanel();
}
function renderPanel(){
 syncVillageScene();if(typeof syncFestivalWorld==='function')syncFestivalWorld();if(!S.me)return;let p=$('panel-content');const villageFocus=S.tab==='village'?document.activeElement?.dataset?.villageFocus:null;const villageServices=S.tab==='village'?[...p.querySelectorAll('.village-services[open]')].map(n=>n.dataset.villageService):[];const villagePanelKey=S.tab==='village'?JSON.stringify([villageSheet,villageResident]):null;const oldScroll=S.lastRenderedTab===S.tab&&(S.tab!=='village'||S.lastRenderedVillageSheet===villagePanelKey)?p.scrollTop:0;S.lastRenderedTab=S.tab;S.lastRenderedVillageSheet=villagePanelKey;p.replaceChildren();
 if(!own()&&S.tab!=='object'&&S.tab!=='neighbors'){renderVisit(p);panelRenderSignature=panelSnapshot();return;}
 scene.zones=null;scene.areaPreview=null;scene.dirty=true;
 if(S.tab==='lake')renderLake(p);else if(S.tab==='arbor')renderArbor(p);else{const fn={orders:renderOrders,inventory:renderInventory,build:renderBuild,production:renderProduction,neighbors:renderNeighbors,journal:renderJournal,settings:renderSettings,object:renderObject,objects:renderObjects,team:renderTeam,forest:renderForest,secrets:renderSecrets,more:renderMore,village:renderVillage,fields:renderFields,orchard:typeof renderOrchard==='function'?renderOrchard:undefined,festival:typeof renderFestivalTab==='function'?renderFestivalTab:undefined}[S.tab]||renderOrders;fn(p);}if(S.tab==='orders'&&typeof festivalBanner==='function')festivalBanner(p);for(const n of p.querySelectorAll('.village-services'))n.open=villageServices.includes(n.dataset.villageService);p.scrollTop=oldScroll;if(villageFocus){const target=[...p.querySelectorAll('[data-village-focus]')].find(n=>n.dataset.villageFocus===villageFocus)||p.querySelector('[data-village-focus=resident]');target?.focus({preventScroll:true});}panelRenderSignature=panelSnapshot();
}
/* ---- building upgrades 1 -> 3: all numbers come from the server catalog (S.catalog.upgrades) ---- */
const UP=()=>S.catalog.upgrades;
const lvlOf=o=>Math.max(1,Math.min(UP().max,Number.isInteger(o.level)?o.level:1));
const slotsOf=o=>Math.min(6,2+(Number.isInteger(o.level)&&o.level>=1?o.level:1));
const speedOf=o=>UP().recipe_speed[lvlOf(o)];
const scaleQ=(m,k)=>Object.fromEntries(Object.entries(m).map(([id,q])=>[id,q*k]));
function batchOf(a,o){const c=UP().animal[lvlOf(o)];return{inputs:scaleQ(a.inputs,c.mult),outputs:scaleQ(a.outputs,c.mult),seconds:a.seconds*c.time}}
function levelEffect(kind,lv){const u=UP();
 if(kind==='workshop')return `очередь ${Math.min(6,2+lv)} мест, рецепты быстрее на ${Math.round((1-u.recipe_speed[lv])*100)}%`;
 if(kind==='animals'){const c=u.animal[lv];return `вместимость ×${c.mult} (корма и продукции), цикл ×${c.time}`}
 return `продажа на складе дороже на ${u.barn_bonus[lv]}%`}
function upgradeCard(o,p){if(!own())return;const u=UP(),kind=u.kinds[o.type];if(!kind)return;const lv=lvlOf(o),c=card(`Уровень ${lv} из ${u.max}`,levelEffect(kind,lv),'workshop');
 if(lv>=u.max||(Number.isInteger(o.level)&&o.level>=u.max)){c.append(el('p','Максимальный уровень достигнут.','note'));p.append(c);return}
 const to=lv+1,cost=u.costs[o.type][String(to)];
 c.append(el('p',`Улучшить до ур. ${to} — ${cost.coins} монет и материалы: ${levelEffect(kind,to)}.`,'note'),goods(cost.items));
 if(S.me.level<cost.level)note(`Откроется на ${cost.level} уровне фермы.`,c);
 c.append(button(`Улучшить до ур. ${to} — ${cost.coins} монет`,()=>command('upgrade',{object:o.id,revision:o.revision}),'light wide',S.me.coins<cost.coins||S.me.level<cost.level||!enough(cost.items)));p.append(c);}
const barnBonus=()=>Math.max(0,...S.me.objects.filter(o=>o.type==='barn').map(o=>UP().barn_bonus[lvlOf(o)]));
const homeProjects=()=>S.catalog?.home_projects||{};
const projectState=()=>S.farm?.home_projects||(own()?S.me?.home_projects:null)||{active:null,entries:{}};
const projectEntry=id=>projectState().entries?.[id]||{stage:0,revision:0,reserved:{}};
const projectFinished=entry=>entry.finished===true||entry.completed===true||entry.stage>=2;
const projectStage=(id,entry=projectEntry(id))=>homeProjects()[id]?.stages?.[entry.stage]||null;
function projectMissing(project,entry){
 if(entry.needs)return entry.needs;
 if(entry.legacy_needs)return entry.legacy_needs;
 return projectStage(project,entry)?.needs||{};
}
function projectPickCrop(item){
 const plots=(S.me?.objects||[]).filter(o=>o.type==='plot');
 const plot=plots.find(o=>!o.crop)||plots.sort((a,b)=>(a.crop?.ready_at||0)-(b.crop?.ready_at||0))[0];
 S.seed=item;renderSeeds();
 if(!plot){selectTab('build');return;}
 farmViewEpoch++;S.selected=plot.id;S.tab='object';scene.focus(plot,true,sheetInset());showPanel();renderRail();renderPanel();
}
function projectMaterialSource(item){
 const catalog=S.catalog||{},stock=S.me?.objects||[];
 if(catalog.crops?.[item])return {text:`Выращивается на грядке: ${catalog.crops[item].name}.`,go:()=>projectPickCrop(item),label:stock.some(o=>o.type==='plot'&&!o.crop)?'К свободной грядке':stock.some(o=>o.type==='plot')?'К грядке':'Построить грядку'};
 const route=Object.values(catalog.routes||{}).find(r=>r.outputs?.[item]);
 if(route)return {text:`${route.kind==='fishing'?'Рыбалка':'Лесная вылазка'} «${route.name}»: ${route.outputs[item]} шт. за ${timeText(route.seconds)}${S.me.level<route.level?` · откроется на ${route.level} уровне`:''}.`,go:()=>selectTab(route.kind==='fishing'?'lake':'forest'),label:route.kind==='fishing'?'К озеру':'В лес'};
 const animal=Object.values(catalog.animals||{}).find(a=>a.outputs?.[item]);
 if(animal){const building=catalog.buildings?.[animal.building],built=stock.some(o=>o.type===animal.building),kept=stock.some(o=>o.type===animal.building&&o.animal===animal.id);return {text:`${animal.name}: ${!built?`сначала построй ${building?.name||animal.building}`:!kept?'посели животное в постройке':'покорми животных и забери продукцию'}.`,go:()=>built?projectPickBuilding(animal.building):selectTab('build'),label:built?'К животным':'К строительству'};}
 const recipe=Object.values(catalog.recipes||{}).filter(r=>r.outputs?.[item]).sort((a,b)=>a.level-b.level)[0];
 if(recipe){const built=stock.some(o=>o.type===recipe.building),building=catalog.buildings?.[recipe.building];return {text:`${recipe.name}: ${Object.entries(recipe.inputs).map(([id,qty])=>`${itemName(id)} ×${qty}`).join(', ')}. ${built?'Готовится в постройке.':`Сначала построй ${building?.name||recipe.building}.`}`,go:()=>built?projectPickBuilding(recipe.building):selectTab('build'),label:built?'К производству':'К строительству'};}
 return {text:'Способ получения пока не указан.'};
}
function projectHasAll(project,entry){const rows=Object.entries(projectMissing(project,entry));return rows.length>0&&rows.every(([id,q])=>(Number(entry.reserved?.[id])||0)>=q);}
function projectPickBuilding(type){const building=(S.me?.objects||[]).find(o=>o.type===type);if(!building){selectTab('inventory');return;}farmViewEpoch++;S.selected=building.id;S.tab='object';scene.focus(building,true,sheetInset());showPanel();renderRail();renderPanel();}
const minigameShelves={grain:'Зерновая полка',vegetable:'Овощная полка',berry:'Ягодная полка'};
function renderMinigameResult(game,result,parent){
 if(!result)return;
 const box=el('div',null,`minigame-result ${result.correct?'is-correct':'is-missed'}`);
 const reward=Number(result.reward)||0;
 const rewardKind=result.reward_kind||(game==='house'?'coins':'feed');
 const bonusFeed=rewardKind==='coins'&&Number(result.bonus_feed)>0?Number(result.bonus_feed):0;
 const rewardText=rewardKind==='feed'?`${reward} корма`:bonusFeed?`${reward} монет и ${bonusFeed} корм`:`${reward} монет`;
 box.append(el('strong',result.correct?`Верно! +${rewardText}`:'Ответ сохранён, но приз не получен.'),el('small',`Последняя игра · ${new Date(result.answered_at*1000).toLocaleString('ru-RU',{dateStyle:'short',timeStyle:'short'})}`));
 parent.append(box);
}
function renderMinigame(game,parent){
 if(!own())return;
 const state=S.me?.minigames?.[game];if(!state)return;
 const active=state.active,house=game==='house',title=house?'Вопрос Филиныча':'Шесть мешков';
 const reward=active?.reward||state.next_reward,kind=reward?.kind||(house?'coins':'feed'),amount=reward?.amount??(house?10:1);
 const bonusFeed=kind==='coins'&&Number(reward?.bonus_feed)>0?Number(reward.bonus_feed):0;
 const payout=kind==='feed'?`${amount} корма`:bonusFeed?`${amount} монет и ${bonusFeed} корм`:`${amount} монет`;
 const box=card(title,house?`Проверь смекалку · +${payout}`:`Разбери доставку для Филиныча · +${payout}`,'home');
 box.classList.add('minigame-card',`minigame-${game}`);
 box.append(el('p',house?'Выбери правильный ответ. Филиныч вручит приз.':kind==='feed'?'Подбери каждому мешку подходящую полку. За помощь Филиныч даст корм.':'Подбери каждому мешку подходящую полку. Это доставка для Филиныча; за помощь он заплатит монетами'+(bonusFeed?' и даст корм.':'.'),'minigame-intro'));
 if(active){
  const clock=el('div',null,'minigame-clock');clock.append(el('span','На задание осталось'),timer(active.expires_at));box.append(clock);
  if(Number(state.available_at)>now()){const cooldown=el('p',null,'minigame-cooldown');cooldown.append(el('span','Повторно можно будет через '),timer(state.available_at));box.append(cooldown);}
  if(house){
   box.append(el('h3',active.question,'minigame-question'));
   const choices=el('div',null,'minigame-choices');choices.setAttribute('role','group');choices.setAttribute('aria-label','Варианты ответа');
   for(const option of active.options||[]){const choice=button(option,()=>command('minigame_answer',{game,attempt_id:active.attempt_id,answer:option}),'secondary minigame-choice',active.expires_at<=now()||S.busy);choices.append(choice);}
   box.append(choices);
  }else{
   const assignments={},rows=el('div',null,'minigame-sacks'),count=el('span','0 из 6 мешков','minigame-assignment-count');
   for(const sack of active.sacks||[]){
    const row=el('label',null,'minigame-sack-row'),name=el('span',sack.label,'minigame-sack-name'),select=el('select');
    select.setAttribute('aria-label',`${sack.label}: выбери полку`);
    const placeholder=el('option','Выбери полку');placeholder.value='';select.append(placeholder);
    for(const shelf of active.shelves||[]){const option=el('option',minigameShelves[shelf]||shelf);option.value=shelf;select.append(option);}
    select.addEventListener('change',()=>{if(select.value)assignments[sack.id]=select.value;else delete assignments[sack.id];count.textContent=`${Object.keys(assignments).length} из ${(active.sacks||[]).length} мешков`;submit.disabled=Object.keys(assignments).length!==(active.sacks||[]).length||active.expires_at<=now()||S.busy;});
    row.append(name,select);rows.append(row);
   }
   const submit=button('Сдать раскладку',()=>command('minigame_answer',{game,attempt_id:active.attempt_id,answer:{...assignments}}),'primary wide',true);
   box.append(rows,count,submit);
  }
 }else if(Number(state.available_at)>now()){
  const line=el('p',null,'minigame-cooldown');line.append(el('span','Следующая игра через '),timer(state.available_at));box.append(line);
 }else{
  box.append(button('Начать игру',()=>command('minigame_start',{game}),'primary wide',S.busy||!!S.pending));
 }
 renderMinigameResult(game,state.last_result,box);
 parent.append(box);
}
function projectStageSummary(project,entry=projectEntry(project),showProgress=true){
 const def=homeProjects()[project],finished=projectFinished(entry),stage=projectStage(project,entry),box=el('div',null,'project-stage-copy');
 if(finished){box.append(el('strong','Проект завершён','project-stage-name'),el('small',`Завершён проект «${def?.name||project}».`,'project-stage-note'));return box;}
 if(!stage){box.append(el('strong',`Этап ${entry.stage+1}`,'project-stage-name'),el('small',def?.description||'Описание этапа пока не задано.','project-stage-note'));return box;}
 box.append(el('strong',`Этап ${entry.stage+1} · ${stage.name||'Работа продолжается'}`,'project-stage-name'));
 const description=stage.description||def?.description;if(description)box.append(el('small',description,'project-stage-note'));
 if(entry.legacy_needs)box.append(el('small','Ранее отложенные материалы сохранены по прежней смете. Если вернуть их на склад, этап перейдёт на новую смету.','project-stage-note'));
 if(showProgress){const needs=projectMissing(project,entry),needTotal=Object.values(needs).reduce((n,q)=>n+q,0),held=Object.entries(needs).reduce((n,[id,q])=>n+Math.min(q,Number(entry.reserved?.[id])||0),0),line=el('div',null,'project-stage-progress');line.append(el('span',`${held} / ${needTotal} материалов`),meter(held,needTotal));box.append(line);}
 return box;
}
function renderProjectHouse(p){
 const definitions=Object.values(homeProjects());
 note(own()?'Материалы для проектов отправляются мастерам. Каждый завершённый этап заметно меняет ферму. Отложи нужное на складе, затем заверши этап здесь.':'Здесь видны открытые проекты хозяина. Завершённые этапы меняют облик фермы.',p);
 if(!definitions.length){note('Новые проекты скоро появятся. Пока Филиныч присматривает за домом.',p);return;}
 const state=projectState(),active=state.active,grid=el('div',null,'home-projects');
 for(const def of definitions.slice(0,3)){
  const entry=projectEntry(def.id),finished=projectFinished(entry),isActive=active===def.id,c=card(def.name,finished?'Завершённый проект':isActive?'Выбранный проект':`Проект дома · уровень ${def.level||1}`,'home');
  c.classList.add('home-project-card');if(finished)c.classList.add('is-finished');if(isActive)c.classList.add('is-active');c.append(projectStageSummary(def.id,entry,own()));
  if(!own()){if(isActive)note('Сейчас строится на этой ферме.',c);}
  else if(!finished){const actions=el('div',null,'project-actions');
   if(!isActive){const locked=S.me.level<(def.level||1);actions.append(button(locked?`Откроется на ${def.level} уровне`:'Выбрать',()=>command('project_select',{project:def.id}),'secondary small',locked));}
   else if(projectHasAll(def.id,entry))actions.append(button('Завершить этап',()=>command('project_deliver',{project:def.id,stage:entry.stage,revision:entry.revision}),'primary small'));
   else actions.append(button('Открыть склад материалов',()=>projectPickBuilding('barn'),'light small'));
   c.append(actions);
  }
  grid.append(c);
 }
 p.append(grid);if(own())p.append(button('К складу проектов',()=>projectPickBuilding('barn'),'text-button project-house-link'));
}
function renderProjectInventoryShelf(p){
 if(!own())return;const state=projectState(),id=state.active,def=homeProjects()[id],shelf=el('section',null,'project-inventory-shelf');shelf.append(el('h3','Проекты дома','subheading'));
 if(!def){note('Собери нужные материалы для строительства дома. Выбери проект в панели дома.',shelf);shelf.append(button('Открыть дом',()=>projectPickBuilding('house'),'secondary small'));p.append(shelf);return;}
 const entry=projectEntry(id);shelf.append(projectStageSummary(id,entry));
 const summary=el('div',null,'project-inventory-needs');for(const [item,qty]of Object.entries(projectMissing(id,entry)))summary.append(el('span',`${itemName(item)} ${Number(entry.reserved?.[item])||0}/${qty}`));
 if(summary.childElementCount)shelf.append(summary);shelf.append(button(projectFinished(entry)?'Все этапы завершены':'Открыть проект дома',()=>projectPickBuilding('house'),'secondary small'));p.append(shelf);
}
function renderProjectBarnShelf(p){
 const state=projectState(),id=state.active,def=homeProjects()[id],shelf=el('section',null,'project-barn-shelf');shelf.append(el('h3','Материалы проекта','subheading'));
 if(!def){note('Выбери проект в доме — здесь появятся нужные материалы.',shelf);shelf.append(button('Открыть проекты дома',()=>projectPickBuilding('house'),'secondary small'));p.append(shelf);return;}
 const entry=projectEntry(id),finished=projectFinished(entry);shelf.append(el('strong',def.name,'project-barn-name'));
 if(finished){shelf.append(projectStageSummary(id,entry,false),button('Открыть проекты дома',()=>projectPickBuilding('house'),'secondary small'));p.append(shelf);return;}
 shelf.append(projectStageSummary(id,entry,false));const list=el('div',null,'project-material-list'),needs=projectMissing(id,entry);
 for(const [item,qty]of Object.entries(needs)){
  const reserved=Number(entry.reserved?.[item])||0,free=Math.max(0,Number(S.me.inventory?.[item])||0),row=el('div',null,'project-material-row'),copy=el('div',null,'project-material-copy');
  const source=projectMaterialSource(item);row.append(icon(item));copy.append(el('strong',itemName(item)),el('small',`Нужно ${qty} · отложено ${reserved} · свободно ${free}`),el('small',source.text,'project-material-source'));
  if(source.go)copy.append(button(source.label,source.go,'text-button project-material-link'));row.append(copy);list.append(row);
 }
 if(!list.childElementCount)note('На этом этапе материалы не нужны.',shelf);else shelf.append(list);
 const ready=projectHasAll(id,entry),hasEscrow=Object.values(entry.reserved||{}).some(q=>q>0),actions=el('div',null,'project-actions');
 if(!ready)actions.append(button('Отложить доступное',()=>command('project_reserve',{project:id,stage:entry.stage,revision:entry.revision}),'secondary small',!Object.entries(needs).some(([item,q])=>(Number(S.me.inventory?.[item])||0)>0&&Math.max(0,q-(Number(entry.reserved?.[item])||0))>0)));
 if(hasEscrow)actions.append(button('Освободить запасы',()=>command('project_release',{project:id,stage:entry.stage,revision:entry.revision}),'light small'));
 if(actions.childElementCount)shelf.append(actions);note('Зарезервированные продукты нельзя продать. После завершения этапа они отправятся мастерам.',shelf);p.append(shelf);
}
function renderOrders(p){heading('Доска заказов','ДЕЛА НА СЕГОДНЯ');let call=el('div',null,'callout owl-note'),t=el('div');t.append(el('strong','Филиныч уже ждёт урожай'),el('span','Заказы не пропадают. Мельница и курочки готовы к работе — загляни к ним после первого сбора.'));call.append(icon('owl'),t);p.append(call);
 marketCards(p);FRIEND_REQUESTS.lane(p);
 for(let o of S.me.orders){let r=repInfo(o.npc),coins=Math.floor(o.coins*(100+r.bonus)/100),xp=Math.floor(o.xp*(100+r.bonus)/100),c=card(o.npc,o.special?`Особая просьба · ${o.title.replace(/^Особая просьба: /,'')}`:o.title),g=goods(o.needs);if(o.special)c.classList.add('special');c.append(repBar(o.npc),g);FRIEND_REQUESTS.missing(c,o.needs);let f=el('div',null,'card-footer'),rw=el('span',`+${coins} `,'reward');rw.append(el('small',`+${xp} XP${r.bonus?` · репутация +${r.bonus}%`:''}`));f.append(rw,button('Доставить',()=>command('order',{order:o.id}),'primary small',!enough(o.needs)));c.append(f,button('Другой заказ',()=>command('skip_order',{order:o.id}),'text-button'));p.append(c);}
 residentsCard(p);
 p.append(el('h3','Маленькие большие цели','subheading'));
 let quests=S.catalog.quests.filter(q=>!S.me.claimed_quests.includes(q.id)).slice(0,3);
 if(!quests.length)note('Все цели этой главы закрыты. Твоя ферма теперь живёт своей жизнью.',p);
 for(let q of quests){let n=S.me.stats[q.stat],c=card(q.name,`${Math.min(n,q.goal)} / ${q.goal}`);note(q.text,c);c.append(meter(n,q.goal));let row=el('div',null,'card-footer');row.append(el('span',`${q.coins?`+${q.coins} монет · `:''}+${q.xp} XP`,'reward'),button('Забрать',()=>command('quest',{quest:q.id}),'secondary small',n<q.goal));c.append(row);p.append(c);}}
const INV_CATS=[['crop','Урожай'],['animal','От животных'],['product','Изделия'],['forest','Лес'],['fish','Рыба'],['other','Прочее']];
const invHas=(o,k)=>!!o&&Object.prototype.hasOwnProperty.call(o,k);
function invNorm(s){return String(s??'').toLowerCase().replace(/ё/g,'е').trim();}
function invEntries(inv){return Object.entries(inv||{}).filter(([,q])=>q>0);}
function invCategory(id,cat){if(Object.values(cat?.animals||{}).some(a=>invHas(a?.outputs,id)))return 'animal';const k=cat?.items?.[id]?.kind;return['crop','product','forest','fish'].includes(k)?k:'other';}
function invWorkshop(id,cat){return [...new Set(Object.values(cat?.recipes||{}).filter(r=>invHas(r?.outputs,id)).map(r=>r.building).filter(Boolean))];}
function invShopName(key,cat){return key==='_'?'Без мастерской':cat?.buildings?.[key]?.name||key;}
function invCounts(entries,cat){const c={all:entries.length,cats:{},shops:{}};for(const [id] of entries){const k=invCategory(id,cat);c.cats[k]=(c.cats[k]||0)+1;if(k==='product'){const shops=invWorkshop(id,cat);for(const w of shops.length?shops:['_'])c.shops[w]=(c.shops[w]||0)+1;}}return c;}
function invCatChips(counts){return INV_CATS.filter(([id])=>counts.cats[id]>0).map(([id,name])=>[id,name,counts.cats[id]]);}
function invShopChips(counts,cat){return Object.entries(counts.shops).map(([id,n])=>[id,invShopName(id,cat),n]).sort((a,b)=>b[2]-a[2]||a[1].localeCompare(b[1],'ru'));}
function invNormalizeState(st,counts){if(st.cat!=='all'&&!counts.cats[st.cat])st.cat='all';if(st.cat!=='product'||(st.shop!=='all'&&!counts.shops[st.shop]))st.shop='all';return st;}
function invFilter(entries,st,cat){const q=invNorm(st.q);return entries.filter(([id])=>{const k=invCategory(id,cat);if(st.cat!=='all'&&k!==st.cat)return false;if(st.cat==='product'&&st.shop!=='all'&&!(invWorkshop(id,cat).length?invWorkshop(id,cat):['_']).includes(st.shop))return false;return !q||invNorm(cat?.items?.[id]?.name||id).includes(q);});}
function renderInventory(p){heading('Склад и лавка',gf('ВСЁ, ЧТО ТЫ ВЫРАСТИЛ','ВСЁ, ЧТО ТЫ ВЫРАСТИЛА','ВСЁ, ЧТО ВЫРОСЛО НА ТВОЕЙ ФЕРМЕ'));note(barnBonus()?`Урожай не портится, а склад не требует расширений. Продажа жителям: цена +${barnBonus()}% благодаря улучшенному складу.`:'Урожай не портится, а склад не требует расширений. Улучшенный склад (в его панели) повышает цену продажи.',p);renderProjectInventoryShelf(p);
 const entries=invEntries(S.me.inventory);
 if(!entries.length)p.append(el('p','Пусто. Зато на грядках начинается новая история.','empty'));else invMount(p,entries);
 p.append(el('h3','Моя соседская лавка','subheading'));note('После трёх заказов можно выставлять товары принятым соседям. Комиссия сделки — 3%, минимум 1 монета. Стартовые монеты на рынке не тратятся.',p);
 if(!S.me.listings.length)note('Нажми «Ещё» у товара, чтобы выставить его.',p);
 for(let lot of S.me.listings){let c=card(itemName(lot.item),`${lot.qty} шт. × ${lot.unit_price} мон.` ,lot.item);c.append(button('Вернуть на склад',()=>command('cancel_listing',{listing:lot.id}),'secondary small'));p.append(c);}
 p.append(button('Нужны семена на новый старт?',()=>command('rescue'),'text-button'));}
function invRow(id,qty){let row=el('div',null,'item-row'),txt=el('div',null,'item-copy'),actions=el('div',null,'row-actions');txt.append(el('strong',`${itemName(id)} ×${fmt(qty)}`),el('small',MERCH.isBound(S.catalog,id)?MERCH.BOUND_NOTE:`${Math.floor(S.catalog.items[id].price*(100+barnBonus())/100)} монет за штуку`));if(!MERCH.isBound(S.catalog,id))actions.append(button('−1',()=>command('sell',{item:id,qty:1}),'secondary small'),button('Ещё',()=>itemDialog(id,qty),'light small'));row.append(icon(id),txt,actions);return row;}
function invPaintList(list,rows){list.replaceChildren(...(rows.length?rows.map(([id,q])=>invRow(id,q)):[el('p','Ничего не нашлось','note')]));}
function invBar(label,chips,cur,pick){const g=el('div',null,'find-filters inv-filters');g.setAttribute('role','group');g.setAttribute('aria-label',label);for(const [id,name,n] of chips){const b=el('button');b.type='button';b.setAttribute('aria-pressed',String(cur===id));b.append(el('span',name),el('span',String(n),'count'));b.onclick=()=>pick(id);g.append(b);}return g;}
function invMount(p,entries){const st=S.inv,counts=invCounts(entries,S.catalog);invNormalizeState(st,counts);
 const sw=el('div',null,'inv-search'),input=el('input'),clr=button('×',()=>{st.q='';input.value='';clr.hidden=true;paintList();input.focus();},'inv-clear'),filters=el('div'),list=el('div',null,'inv-list');
 input.type='search';input.value=st.q;input.placeholder='Найти на складе';input.setAttribute('aria-label','Найти на складе');input.autocomplete='off';input.enterKeyHint='search';clr.hidden=!st.q;clr.setAttribute('aria-label','Очистить поиск');sw.append(input,clr);
 const paintList=()=>invPaintList(list,invFilter(entries,st,S.catalog));
 const paintFilters=()=>{const cats=invCatChips(counts),bars=[];if(cats.length>1)bars.push(invBar('Категория',[['all','Все',counts.all],...cats],st.cat,id=>{st.cat=id;st.shop='all';repaint(0);}));
  if(st.cat==='product'){const shops=invShopChips(counts,S.catalog);if(shops.length>1)bars.push(invBar('Мастерская',[['all','Все изделия',counts.cats.product],...shops],st.shop,id=>{st.shop=id;repaint(1);}));}
  filters.replaceChildren(...bars);};
 const repaint=level=>{paintFilters();paintList();filters.children[level]?.querySelector('[aria-pressed="true"]')?.focus({preventScroll:true});};
 input.oninput=()=>{st.q=input.value;clr.hidden=!st.q;paintList();};
 paintFilters();paintList();p.append(sw,filters,list);}
function itemDialog(id,qty){let w=el('div'),[qwrap,q]=field('Количество','number',Math.min(5,qty));q.min=1;q.max=Math.min(999,qty);let [pwrap,price]=field('Цена в соседской лавке за штуку','number',S.catalog.items[id].price);price.min=S.catalog.items[id].price;price.max=price.min*2;w.append(el('p',`В наличии ${qty}. Продажа жителям: ${Math.floor(S.catalog.items[id].price*(100+barnBonus())/100)} монет за штуку (за 1 шт.).`),qwrap,pwrap);
 modal(itemName(id),w,[button('Продать',safe(async()=>{if(await command('sell',{item:id,qty:Number(q.value)}))$('dialog').close();}),'primary'),button('В лавку',safe(async()=>{if(await command('list',{item:id,qty:Number(q.value),unit_price:Number(price.value)}))$('dialog').close();}),'secondary',S.me.stats.orders<3)]);}
function landExpansion(p){
 const land=S.catalog.land,step=land.steps.find(s=>s.size===S.me.size+2),locked=step&&S.me.level<step.level;
 const row=el('section',null,'land-expansion'),copy=el('div',null,'land-expansion-copy');row.setAttribute('aria-label','Расширение участка');
 copy.append(el('strong',`Участок · ${S.me.size} × ${S.me.size}`),el('small',step?`До ${step.size} × ${step.size} · ${fmt(step.cost)} монет`:'Весь участок открыт'));
 row.append(copy);
 if(step){const expand=button('Расширить участок',()=>command('expand'),'secondary small',locked);expand.setAttribute('aria-label',`Расширить участок до ${step.size} × ${step.size} за ${step.cost} монет`);row.append(expand);if(locked)row.append(el('small',`Доступно с ${step.level} уровня`,'land-expansion-lock'));}
 p.append(row);
}
function renderBuild(p){heading('Обустройство','ЗДЕСЬ БУДЕТ ТВОЯ ИСТОРИЯ');landExpansion(p);note('Выбери объект, нажми на свободную клетку и нажми по ней ещё раз или «Поставить». Перемещение уже построенного бесплатно. Плодовые деревья сажают во вкладке «Сад».',p);let specs=[{id:'plot',name:'Новая грядка',cost:35,level:1,w:1,h:1},...Object.values(S.catalog.buildings)];for(let b of specs){if(b.curio&&!(S.me.merchant?.curios||[]).includes(b.id))continue;let c=card(b.name,`${b.w} × ${b.h} клеток · ${b.cost} монет`,b.id==='plot'?'wheat':'workshop');const purpose=buildingPurpose(b.id,S.catalog);if(purpose.length)note(purpose.join(' '),c);if(b.level>S.me.level)note(`Откроется на уровне ${b.level}`,c);if(b.secret&&!S.me.secrets.includes(b.secret))note('Найди эту пасхалку в разделе «Находки».',c);const locked=b.reward&&!(S.me.economy?.unlocked||[]).includes(b.id);if(locked)note(`Награда фонда деревни: ${b.source}`,c);const placed=S.farm.objects.filter(o=>o.type===b.id);if(placed.length){const row=el('div',null,'building-purpose-row');row.append(el('small',`Уже на ферме: ${placed.length}`));for(const o of placed){const pick=button(null,()=>{farmViewEpoch++;S.selected=o.id;S.tab='object';scene.focus(o,true,sheetInset());showPanel();renderRail();renderPanel();},'text-button building-purpose-pick');pick.append(icon(objIcon(o)),el('span',`${o.x+1}, ${o.y+1}`));row.append(pick);}c.append(row);}c.append(button('Разместить',()=>beginPlacement(b),'secondary wide',b.level>S.me.level||b.cost>S.me.coins||(b.secret&&!S.me.secrets.includes(b.secret))||locked));p.append(c);}}
/* ---- fruit orchard (docs/tasks/FARM_ORCHARD.md): the «Сад» tab and the card of a tree. Every number comes from the server (S.catalog.orchard, S.me.orchard_view) ---- */
const orchardInfo=o=>ORCH.view(S.me)?.trees?.[o.id]||null;
// Every entry to the orchard (seed bar card, notices) goes through the one «Сад» tab.
function openOrchard(){selectTab('orchard');}
// A small counter on the «Сад» tab while saplings or talons wait to be planted. On a phone the tab lives under «Ещё»: the counter sits there too.
function syncOrchardBadge(more=$('panel-content')){
 const n=S.me&&S.catalog?ORCH.pendingCount(ORCH.view(S.me),S.me,S.catalog):0,rail=$('rail');
 const hosts=[rail?.querySelector('[data-tab=orchard]')||rail?.querySelector('[data-tab=more]'),more?.querySelector('.more-item[data-more-tab=orchard]')].filter(Boolean);
 for(const h of hosts){
  let b=h.querySelector(':scope>.tab-badge');const title=h.dataset.tab==='more'?'Ещё':'Сад';
  if(!n){b?.remove();if(h.dataset.tab)h.setAttribute('aria-label',title);else h.removeAttribute('aria-label');continue;}
  if(!b){b=el('b',null,'tab-badge');b.setAttribute('aria-hidden','true');h.append(b);}
  const text=n>9?'9+':String(n);if(b.textContent!==text)b.textContent=text;h.setAttribute('aria-label',`${title} · в Саду ждут посадки: ${n}`);
 }
}
// One-time notice for farms whose fruit beds moved to the orchard, and the level-up line for a newly opened tree species.
let orchardMovedShown=null;
function orchardNotices(prevLevel=null){
 if(!S.me||!S.catalog?.orchard)return;
 const go={label:ORCH.OPEN_LABEL,fn:openOrchard};
 if(prevLevel!=null&&S.me.level>prevLevel){const list=ORCH.treeUnlocks(S.catalog,prevLevel,S.me.level);if(list.length)toast(ORCH.unlockText(list),false,go,10000);}
 if(orchardMovedShown===S.me.id||!ORCH.movedNotice(ORCH.view(S.me)))return;
 orchardMovedShown=S.me.id;let seen=null;try{seen=localStorage.getItem('qw-farm.orchard-moved');}catch{}
 if(seen===S.me.id)return;try{localStorage.setItem('qw-farm.orchard-moved',S.me.id);}catch{}
 toast(ORCH.MOVED_TEXT,false,go,10000);
}
function renderOrchard(p){
 heading('Сад','ДЕРЕВО РАСТЁТ, УРОЖАЙ ВОЗВРАЩАЕТСЯ');
 const v=ORCH.view(S.me),rows=ORCH.saplingRows(S.catalog,S.me,v),mine=ORCH.treeSummary(S.catalog,S.me.objects);
 note('Саженец покупают один раз: дерево плодоносит снова и снова, каждый «садовый год» — это 24 часа. Грядок оно не занимает, но каждому дереву нужна своя свободная клетка. Ничего не гибнет и не портится, а заходить обязательно не нужно.',p);
 if(v)note(`Деревьев: ${v.count}${mine?` · ${mine}`:''}`,p);
 const rent=ORCH.rentSummary(v);if(rent)note(`Аренда сада: все деревья — ${fmt(rent.total)} монет в сутки · следующее дерево — ${fmt(rent.next)} монет в сутки. Без надбавки к аренде: деревьев — ${rent.freeCount}.`,p);
 if(v&&Object.keys(v.discounts||{}).length)note(`Талоны со скидкой: ${Object.entries(v.discounts).map(([id,q])=>`${itemName(id)} ×${q}`).join(', ')}`,p);
 for(const r of rows){
  const c=card(r.sapling,`${r.name} · первый урожай через ${duration(r.first)}`,'sapling_'+r.id);
  c.append(el('p',`Урожай ×${r.yield_qty} у взрослого дерева, у молодого меньше · опыт за урожай ${r.xp}${r.potted?' · растёт в кадке':''}`,'note'));
  if(r.locked)note(`Откроется на уровне ${r.level}`,c);else if(r.blocked)note(r.blocked,c);
  const stack=el('div',null,'qw-btn-stack');
  r.options.forEach((opt,i)=>{
   const b=button(opt.price?`Посадить · ${fmt(opt.price)} мон.`:'Посадить бесплатно',()=>beginPlacement(ORCH.plantSpec(r,opt,S.catalog)),'secondary wide',r.locked||!!r.blocked||opt.price>S.me.coins);
   b.dataset.voucher=opt.voucher||'';stack.append(b,el('small',opt.label+(opt.qty?` · есть ×${opt.qty}`:''),'note'));
  });
  c.append(stack);p.append(c);
 }
 note('Редкие сорта и прививки привозит Сорока-коробейница: у них свой облик, а урожай и место в саду те же.',p);
}
function renderTree(o,p){
 const t=now(),mine=own(),v=ORCH.view(S.me),f=ORCH.treeFacts(S.catalog,o,mine?orchardInfo(o):null,t,v?.infusion||0,v?.grafts||{});
 const box=card(f.name,mine&&f.age!==null?`${f.stageName} · ${ORCH.gardenYears(f.age)}`:'Плодовое дерево',f.fruit||'apple');
 box.append(el('p',ORCH.stageNote(f.stage),'note'));
 if(f.lookName)note(`Привито: «${f.lookName}»`,box);
 if(o.fruit){box.append(el('p',f.ripe?'Урожай созрел и ждёт на ветках':o.harvests?'Следующий урожай через:':'Первый урожай через:','note'),timer(o.fruit.ready_at));if(mine&&o.fruit.started_at)box.append(growthMeter(o.fruit.started_at,o.fruit.ready_at));}
 if(mine){
  box.append(el('p',`Урожай этого года: ×${f.qty}${f.nextYield&&f.nextYield!==f.qty?` (по возрасту ×${f.nextYield})`:''}${f.goldenPct?` · шанс золотого плода ${f.goldenPct}%`:''}`,'note'));
  if(f.pest)note(f.pestActive?`${f.pest} на ветке. Урожай не убавится, но золотого плода в этом году не будет.`:`${f.pest}: за деревом присматривает скворечник.`,box);
  if(f.dry)note('На дереве сухие ветки: подрезка бесплатная, даёт древесину и больше плодов на ближайшие семь урожаев. Если не обрезать, ничего не потеряется.',box);
  const stack=el('div',null,'qw-btn-stack');
  stack.append(button('Собрать урожай',()=>command('harvest',{object:o.id,revision:o.revision}).then(ok=>{if(ok)scene.burst(o);}),'primary wide',!f.ripe));
  if(f.pestActive)stack.append(button('Опрыскать настоем',()=>command(...ORCH.careCommand(o,'spray')),'secondary wide',!f.canSpray),...(f.canSpray?[]:[el('small',f.sprayWhy,'note')]));
  if(f.dry)stack.append(button('Обрезать ветки',()=>command(...ORCH.careCommand(o,'prune')),'secondary wide'));
  for(const g of f.grafts)stack.append(button(`Привить: ${g.name}`,()=>command(...ORCH.careCommand(o,'graft',g.id)),'secondary wide',g.same));
  box.append(stack);
 }else if(S.farm.permissions.allow_help)box.append(button(f.helped?'Сосед уже помог':'Полить дерево',()=>command('help',{object:o.id,revision:o.revision},S.farm.id),'primary wide',f.helped||f.ripe));
 p.append(box);
 if(mine){
  p.append(button('Переместить дерево',()=>beginPlacement({w:o.w,h:o.h,name:objName(o)},o),'text-button'));
  p.append(button('Выкорчевать',()=>confirmUproot(o),'text-button danger'));
 }else renderVisitActions(p);
}
function confirmUproot(o){
 const u=ORCH.uprootText(S.catalog,o,now(),S.catalog.undo?.window||60);
 modal(`Выкорчевать «${objName(o)}»?`,u.text,[button(u.early?'Отменить посадку':'Выкорчевать',safe(async()=>{
  $('dialog').close();
  if(await command('demolish',{object:o.id,revision:o.revision})){S.selected=null;scene.selected=null;scene.dirty=true;S.tab='orchard';renderRail();renderPanel();}
 }),'primary')]);
}
function beginPlacement(spec,obj=null){if(villageVisible())exitVillage();S.placing={spec,obj,cell:null};scene.placement={spec,ignore:obj?.id};closePanel();renderPlacement();}
function cancelPlacement(){S.placing=null;scene.placement=null;$('placement').hidden=true;}
// Beds and decor can be placed one after another: the mode stays open until «Готово», Esc, or the money/limit runs out.
const repeatable=spec=>!!spec&&!spec.obj&&(spec.id==='plot'||!!S.catalog.buildings[spec.id]?.decor);
function renderPlacement(){let n=$('placement'),p=S.placing;if(!p){n.hidden=true;return;}n.hidden=false;const again=repeatable(p.spec);
 const hint=(p.committing?'Сохраняем размещение…':p.cell?`Клетка ${p.cell.x+1}, ${p.cell.y+1} · нажми ещё раз или «Поставить»`:'Нажми на свободную клетку карты')+(p.count?` · поставлено: ${p.count}`:again?' · можно ставить подряд':'');
 n.replaceChildren(el('strong',p.obj?`Переместить: ${objName(p.obj)}`:p.spec.name),el('p',hint,'note'));
 let row=el('div');row.append(button(p.count?'Готово':'Отмена',()=>{cancelPlacement();renderPanel();},'secondary',p.committing),button(p.committing?'Сохраняем…':'Поставить',safe(()=>commitPlacement(p)),'primary',!p.cell||p.committing));n.append(row);}
async function commitPlacement(p){if(!p.cell||S.placing!==p||p.committing)return;const cell={x:p.cell.x,y:p.cell.y};p.committing=true;renderPlacement();let ok=false;
 try{if(p.spec.tree)ok=await command(...ORCH.plantCommand(p.spec,cell));else{const data=p.obj?{object:p.obj.id,x:cell.x,y:cell.y,revision:p.obj.revision}:{type:p.spec.id,x:cell.x,y:cell.y};ok=await command(p.obj?'move':'build',data);}}
 finally{p.committing=false;if(S.placing===p)renderPlacement();}
 if(!ok||S.placing!==p){if(S.placing===p)renderPlacement();return;}
 const again=repeatable(p.spec);
 if(again&&S.me.coins>=p.spec.cost&&S.me.level>=(p.spec.level||1)){p.count=(p.count||0)+1;p.cell=null;scene.placement.cell=null;scene.dirty=true;renderPlacement();}
 else{if(again)toast('Монет на следующую не хватает — режим закрыт.');cancelPlacement();renderPanel();}}
function renderProduction(p){heading('Мастерские','СЫРЬЁ СТАНОВИТСЯ ЧЕМ-ТО БОЛЬШИМ');note('Работа в очередях продолжается с закрытой вкладкой. Готовые товары ждут на полке, не пропадая.',p);bulkCard(p);for(let o of S.me.objects.filter(o=>o.type!=='plot'&&o.type!=='tree'&&!['house','barn'].includes(o.type)&&!S.catalog.buildings[o.type]?.decor))p.append(objectButton(o));}
// On phones the panel is a sheet over the map: report how many canvas pixels it covers so the camera aims above it.
function sheetInset(){const p=$('panel').getBoundingClientRect(),c=$('farm-canvas').getBoundingClientRect();return matchMedia('(max-width:850px)').matches&&p.height&&p.top<c.bottom?Math.max(0,c.bottom-p.top):0;}
function stateBadge(row){
 const {cat,info,o}=row;
 if(info.state==='ready')return ['Готово','ready'];
 if(info.state==='busy')return [`Идёт · ${timeText(info.at-now())}`,'busy'];
 if(info.state==='idle')return [cat==='animals'?(o.animal?'Ждёт корм':'Пусто'):'Свободно',''];
 return null;
}
function objectButton(o,row=null){
 row=row||{o,cat:categoryOf(o,S.catalog),info:readyInfo(o,now(),S.catalog)};
 let b=button(null,()=>{farmViewEpoch++;S.selected=o.id;S.tab='object';renderPanel();document.body.classList.add('panel-open');scene.focus(o,true,sheetInset());},`object-card${S.selected===o.id?' is-selected':''}`);
 let t=el('span');t.append(el('strong',objName(o)),el('small',` · ${o.x+1}, ${o.y+1}`));b.append(icon(objIcon(o)),t);
 const badge=stateBadge(row);if(badge){const label=el('span',badge[0],`state ${badge[1]}`);if(row.info.state==='busy'){label.dataset.until=row.info.at;label.dataset.untilPrefix='Идёт · ';updateTime(label);}b.append(label);}
 return b;
}
function renderObjects(p){
 heading('Найти на ферме','ВСЁ НА КАРТЕ');
 const t=now(),f=S.find,counts=countByCategory(S.farm.objects,S.catalog,t);
 const bar=el('div',null,'find-filters');bar.setAttribute('role','group');bar.setAttribute('aria-label','Что показать');
 const chip=(id,name,color)=>{
  const b=el('button');b.type='button';b.setAttribute('aria-pressed',String(f.category===id));
  if(color){const d=el('i',null,'dot');d.style.background=color;b.append(d);}
  b.append(el('span',name),el('span',String(counts[id].n),'count'));
  if(counts[id].ready)b.append(el('span',`✓ ${counts[id].ready}`,'ready-count'));
  b.onclick=()=>{f.category=id;renderPanel();};return b;
 };
 bar.append(chip('all','Все'),...CATEGORIES.filter(([id])=>id!=='other').map(([id,name,color])=>chip(id,name,color)));
 const only=el('button','Только готовое');only.type='button';only.setAttribute('aria-pressed',String(f.ready));only.onclick=()=>{f.ready=!f.ready;renderPanel();};bar.append(only);
 p.append(bar);
 const rows=listObjects(S.farm.objects,S.catalog,t,{category:f.category,onlyReady:f.ready});
 if(!rows.length)note(f.ready?'Готового пока нет — всё ещё в работе.':'Здесь пока пусто.',p);
 for(const r of rows)p.append(objectButton(r.o,r));
}
function renderObject(p){let o=S.farm.objects.find(o=>o.id===S.selected);if(!o){S.tab='orders';renderPanel();return;}heading(objName(o),own()?'ТВОЁ ХОЗЯЙСТВО':'В ГОСТЯХ У СОСЕДА');
 if(o.type==='plot'){
  let c=o.crop;if(c){let box=card(itemName(c.id),`Урожай ×${c.yield_qty}`,c.id);box.append(timer(c.ready_at));box.append(growthMeter(c.planted_at,c.ready_at));if(own()){box.append(button('Собрать',()=>command('harvest',{object:o.id,revision:o.revision}),'primary wide',c.ready_at>now()));box.append(button('Выкопать',()=>confirmDigUp(o),'secondary wide',c.ready_at<=now()));}else if(S.farm.permissions.allow_help)box.append(button(c.helped?'Сосед уже помог':'Полить грядку',()=>command('help',{object:o.id,revision:o.revision},S.farm.id),'primary wide',c.helped||c.ready_at<=now()));p.append(box);}else if(own()){note('Выбери семена внизу и нажми грядку — или посади выбранную культуру здесь.',p);p.append(button(`Посадить: ${itemName(S.seed)}`,()=>command('plant',{object:o.id,crop:S.seed,revision:o.revision}),'primary wide'));}else note('Грядка отдыхает до следующего посева.',p);
 }else if(o.type==='tree'){renderTree(o,p);return;
 }else if(o.type==='house'){note('Дом Филиныча — место, где урожай становится частью фермы.',p);renderMinigame('house',p);renderProjectHouse(p);if(own())p.append(button('Открыть заказы',()=>selectTab('orders'),'primary wide'));}
 else if(!own()){note('Владелец занимается производством сам. Найди растущую грядку, чтобы помочь.',p);renderVisitActions(p);return;}
 else if(o.type==='barn'){note('Здесь сохраняется весь урожай. Ограничения вместимости нет: улучшенный склад приносит больше монет при продаже.',p);renderMinigame('barn',p);renderProjectBarnShelf(p);p.append(button('Открыть склад',()=>selectTab('inventory'),'primary wide'));upgradeCard(o,p);}
 else {
  const purpose=buildingPurpose(o.type,S.catalog);if(purpose.length)note(purpose.join(' '),p);
  let animal=Object.values(S.catalog.animals).find(a=>a.building===o.type);
  if(animal){let c=card(animal.name,'Кормление запускает одну порцию. Животные не голодают и не умирают.',Object.keys(animal.outputs)[0]);if(!o.animal)c.append(button(`Поселить за ${animal.cost} монет`,()=>command('buy_animal',{object:o.id,animal:animal.id}),'primary wide',S.me.coins<animal.cost));else if(o.animal_job){c.append(el('p','Продукция будет готова через:','note'),timer(o.animal_job.ready_at),goods(o.animal_job.outputs,false),button('Забрать продукцию',()=>command('collect_animal',{object:o.id}),'primary wide',o.animal_job.ready_at>now()));}else{let bt=batchOf(animal,o);c.append(goods(bt.inputs),el('p',`Одна порция: ${duration(bt.seconds)} → ${Object.entries(bt.outputs).map(([id,q])=>`${itemName(id)} ×${q}`).join(', ')}`,'note'),button('Накормить',()=>command('feed',{object:o.id}),'primary wide',!enough(bt.inputs)));}p.append(c);upgradeCard(o,p);}
  const recipes=Object.values(S.catalog.recipes).filter(r=>r.building===o.type);
  if(recipes.length){note(`Мастерская ${lvlOf(o)} уровня · ${o.jobs.length} / ${slotsOf(o)} мест занято`,p);{const mem=recipeMemory(o);if(mem.length){note(`Мастер повторяет: ${mem.map(id=>S.catalog.recipes[id].name).join(', ')}. Помощник-мастер и «Повторить партии» ставят их по очереди.`,p);note('Повторяется последняя постановка. Новая постановка после опустевшей очереди заменит список.',p);const box=el('div',null,'forget-recipes qw-btn-stack');for(const id of mem){const b=button(`Забыть: ${S.catalog.recipes[id].name}`,()=>command('forget_recipe',{object:o.id,recipe:id}),'light small forget-recipe');b.dataset.recipe=id;box.append(b);}p.append(box);}}
   const readyCount=o.jobs.filter(j=>j.ready_at<=now()).length;
   if(readyCount>=2)p.append(button(`Забрать всё готовое · ${readyCount}`,()=>command('collect_building',{object:o.id}),'primary wide'));
   for(let j of o.jobs){let row=el('div',null,'queue-job'),ready=j.ready_at<=now();row.append(button(ready?'Забрать':'Отменить',()=>ready?command('collect',{object:o.id,job:j.id}):(j.starts_at>now()&&!recipeMemory(o).includes(j.recipe))?command('cancel_job',{object:o.id,job:j.id}):confirmCancelJob(o,j),ready?'primary small':'light small'),el('strong',S.catalog.recipes[j.recipe]?.name||'Продукция'));let s=el('small');s.append(j.starts_at>now()?el('span','В очереди · '):el('span',''),timer(j.ready_at));row.append(s);p.append(row);}
   renderLessonCard(o,p);
   for(let r of recipes){let c=card(r.name,null,Object.keys(r.outputs)[0]);c.append(goods(r.inputs));let out=Object.entries(r.outputs).map(([id,q])=>`${itemName(id)} ×${q}`).join(', ');c.append(el('p',`→ ${out} · ${duration(r.seconds*speedOf(o))}`,'recipe-time'));const lock=recipeLock(r);c.append(button(lock?lock.label:recipeLevel(r)>S.me.level?`Нужен ${recipeLevel(r)} уровень`:'В очередь',()=>command('queue',{object:o.id,recipe:r.id}),'secondary wide',!!lock||recipeLevel(r)>S.me.level||!enough(r.inputs)||o.jobs.length>=slotsOf(o)));if(lock)note(lock.hint,c);p.append(c);}
   upgradeCard(o,p);
  }
  if(S.catalog.buildings[o.type]?.decor)note('Маленькая деталь, которая делает место твоим. Можно переставить в любой свободный уголок.',p);
 }
 if(own()){
  p.append(button('Переместить объект',()=>beginPlacement({w:o.w,h:o.h,name:objName(o)},o),'text-button'));
  const reason=o.type==='house'||o.type==='barn'?'Дом и склад нельзя снести.':o.crop?'Сначала освободи грядку от урожая.':o.jobs?.length?'Сначала забери или отмени работу в очереди.':o.animal_job?'Сначала забери продукцию животных.':o.animal?'В домике есть животные — убрать его пока нельзя.':null;
  const label=o.type==='road'?'Убрать дорогу':o.type==='plot'?'Убрать грядку':'Снести постройку';
  const remove=button(label,()=>confirmDemolish(o),'text-button danger',!!reason);
  if(reason){remove.title=reason;note(reason,p);}
  p.append(remove);
 }
}
/* Textile lessons of Кошка Соня: a delivered step opens the recipes marked `teach` sooner (server: textile.recipe_level). */
function recipeLock(r){return typeof MERCH==='undefined'?null:MERCH.scrollLock(r,S.me);}
const recipeLevel=r=>{if(r.scroll&&!(S.me?.merchant?.scrolls||[]).includes(r.scroll))return 1e6;const t=r.teach;return t&&(S.me?.lessons?.[t.track]||0)>=t.step?Math.max(1,r.level-t.early):r.level;};
function renderLessonCard(o,p){
 for(const track of Object.values(S.catalog.lessons||{})){
  const taught=Object.values(S.catalog.recipes).filter(x=>x.teach?.track===track.id);
  if(!taught.some(x=>x.building===o.type))continue;
  const done=S.me?.lessons?.[track.id]||0,step=track.steps[done];
  if(!step){note(`${track.npc}: все уроки пройдены.`,p);continue;}
  const opens=taught.filter(x=>x.teach.step===step.step).map(x=>x.name.toLowerCase()).join(', ');
  const c=card(track.name,`${track.npc}: «${step.text}»${opens?`. Откроет раньше: ${opens}`:''}`,'yarn');
  c.append(goods(step.items),button(S.me.level<step.level?`Нужен ${step.level} уровень`:'Сдать урок',()=>command('lesson_deliver',{track:track.id}),'secondary wide',S.me.level<step.level||!enough(step.items)));
  p.append(c);
 }
}
function confirmDemolish(o){
 const functional=!!S.catalog.buildings[o.type]&&!S.catalog.buildings[o.type].decor;
 const refund=functional?`На склад вернётся древесина ×${4+lvlOf(o)-1}. Монеты не возвращаются.`:'Монеты и материалы не возвращаются.';
 modal(`Удалить «${objName(o)}»?`,`${objName(o)} исчезнет с фермы. ${refund}`, [
  button('Подтвердить удаление',safe(async()=>{const d=$('dialog');d.close();if(await command('demolish',{object:o.id,revision:o.revision})){
   S.selected=null;scene.selected=null;scene.dirty=true;S.tab=['road','plot'].includes(o.type)?'build':'objects';renderRail();renderPanel();
  }}),'primary')
 ]);
}
async function visit(id){const epoch=++farmViewEpoch,identity=S.me?.id,tab=S.tab;try{let r=await request(API+'/farms/'+id);if(epoch!==farmViewEpoch||S.me?.id!==identity||S.tab!==tab)return;S.farm=r.farm;S.selected=null;S.tab='neighbors';scene.set(S.farm,S.catalog);scene.fit();updateHUD();renderSeeds();renderPanel();renderRail();document.body.classList.remove('panel-open');}catch(e){if(epoch===farmViewEpoch)toast(e.message,true);}}
function backHome(){farmViewEpoch++;S.farm=S.me;S.selected=null;S.tab='orders';scene.set(S.me,S.catalog);scene.fit();updateHUD();renderSeeds();renderRail();renderPanel();}
function renderVisit(p){heading('В гостях','У СОСЕДА ВСЕГДА ЧТО-ТО РАСТЁТ');note('Можно посмотреть ферму и помочь с растущими грядками. Монеты и склад хозяина остаются приватными.',p);renderVisitActions(p);}
function renderVisitActions(p){const f=S.farm;let row=el('div',null,'pill-row');row.append(button('На свою ферму',backHome,'secondary'));p.append(row);
 if(f.permissions.allow_pranks)p.append(button('Отправить весёлого гуся',()=>command('prank',{},f.id),'secondary wide',!S.me.settings.allow_pranks));
 if(!S.me.settings.allow_pranks)note('Проделки работают только когда оба соседа добровольно их включили.',p);
 if(f.permissions.allow_gifts){let c=card('Посылка соседу','Открывается после заказа и четырёх сборов','friends');let [iw,i]=field('Товар','select');for(let [id,q]of Object.entries(S.me.inventory).filter(([id,q])=>q>0&&!MERCH.isBound(S.catalog,id))){let op=el('option',`${itemName(id)} · ${q}`);op.value=id;i.append(op);}let[qw,q]=field('Количество','number',1);q.min=1;q.max=10;c.append(iw,qw,button('Подарить',()=>command('gift',{item:i.value,qty:Number(q.value)},f.id),'primary wide',S.me.stats.orders<1||S.me.stats.harvests<4));p.append(c);}
 p.append(el('h3','Лавка соседа','subheading'));
 if(!f.listings.length)note('Сегодня лавка пуста. Загляни позже.',p);
 for(let lot of f.listings){let c=card(itemName(lot.item),`${lot.qty} шт. · ${lot.qty*lot.unit_price} монет`,lot.item);c.append(button('Купить',()=>command('buy',{listing:lot.id},f.id),'primary wide',S.me.stats.orders<3||S.me.coins-S.me.starter_credit<lot.qty*lot.unit_price));p.append(c);}
}
let neighborGeneration=0,neighborRequestEpoch=0,neighborList=null,neighborSnapshot=null,neighborGiftNotice=null;
async function updateNeighbors(){
 const list=neighborList,gen=neighborGeneration,epoch=++neighborRequestEpoch,identity=S.me?.id;
 if(!list||S.tab!=='neighbors'||!own()||!identity)return;
 const r=await request(API+'/neighbors');
 if(gen!==neighborGeneration||epoch!==neighborRequestEpoch||list!==neighborList||S.tab!=='neighbors'||!own()||S.me?.id!==identity||S.farm?.id!==identity)return;
 FRIEND_REQUESTS.setNeighbors(r.neighbors);
 const snapshot=JSON.stringify(r);
 if(snapshot===neighborSnapshot||list.contains(document.activeElement))return;
 neighborSnapshot=snapshot;list.replaceChildren();
 if(neighborGiftNotice){
  neighborGiftNotice.replaceChildren();
  const first=r.neighbors.find(n=>n.reward_claimable);
  if(first){const gift=button(null,()=>command('claim_neighbor_reward',{},first.id),'neighbor-gift-button');gift.append(icon('gift'));gift.setAttribute('aria-label',`Забрать подарок за соседство с ${first.name}`);gift.title='Забрать подарок';neighborGiftNotice.append(gift,el('span',`Доступен подарок за соседство${r.claimable_rewards>1?` · ${r.claimable_rewards}`:''}`));}
  else if(r.pending_rewards)neighborGiftNotice.append(el('span','Подарок за соседство появится, когда обновится лимит.'));
  neighborGiftNotice.hidden=!neighborGiftNotice.childNodes.length;
 }
 const publicCode=id=>String(id).replace(/-/g,'').slice(0,8).toUpperCase().replace(/^(.{4})(.{4})$/,'$1-$2');
 for(let n of r.neighbors){let status=n.status==='outgoing'?'Заявка отправлена · жди принятия владельцем':{incoming:'Просится в соседи',accepted:'Ваше соседство подтверждено'}[n.status],c=card(n.name,status,'friends'),row=el('div',null,'card-footer');c.append(el('small',`Первые 8 знаков ID: ${publicCode(n.id)}`,'farm-public-code'));if(n.status==='incoming')row.append(button('Принять',()=>command('accept_neighbor',{},n.id),'primary small'));if(n.status==='accepted')row.append(button('В гости',()=>visit(n.id),'primary small',!n.can_visit));if(n.reward_claimable){const gift=button(null,()=>command('claim_neighbor_reward',{},n.id),'neighbor-gift-button');gift.append(icon('gift'));gift.setAttribute('aria-label',`Забрать ${r.reward_per_neighbor} монет за соседство с ${n.name}`);gift.title=`Забрать ${r.reward_per_neighbor} монет`;row.append(gift);}else if(n.reward_pending)row.append(el('small','Подарок ждёт лимита','neighbor-gift-pending'));row.append(button(n.status==='outgoing'?'Отменить':'Удалить',()=>command('remove_neighbor',{},n.id),'text-button'),button('Блок',()=>command('block',{},n.id),'text-button danger'));c.append(row);list.append(c);}
 if(!r.neighbors.length)list.append(el('p','Здесь появятся твои настоящие соседи.','empty'));
 if(r.public.length)list.append(el('h3','Открытые фермы','subheading'));
 for(let n of r.public){let c=card(n.name,'Публичная ферма');c.append(el('small',`Первые 8 знаков ID: ${publicCode(n.id)}`,'farm-public-code'),button('Посмотреть',()=>visit(n.id),'secondary small'),button('Пригласить',()=>command('request_neighbor',{},n.id),'text-button'));list.append(c);}
 if(r.blocked.length){list.append(el('h3','Заблокированные','subheading'));for(let id of r.blocked){let c=card('Закрытый доступ',id);c.append(button('Снять блокировку',()=>command('unblock',{},id),'text-button'));list.append(c);}}
}
function renderNeighbors(p){heading(own()?'Соседи':'В гостях','МАЛЕНЬКИЕ ПОСТУПКИ СОЗДАЮТ ИСТОРИИ');if(!own()){renderVisit(p);return;}FRIEND_REQUESTS.renderNeighbors(p);neighborGiftNotice=el('div',null,'neighbor-gift-notice');neighborGiftNotice.hidden=true;p.append(neighborGiftNotice);renderSharing(p);let c=card('Код твоей фермы','Это публичный адрес, не секретный ключ','friends');c.append(el('div',S.me.id,'code'),button('Скопировать код',safe(async()=>{try{await navigator.clipboard.writeText(S.me.id);toast('Код фермы скопирован.');}catch{modal('Код твоей фермы',el('div',S.me.id,'code'));}}),'text-button'));p.append(c);
 const form=el('form'),[w,input]=field('Пригласить соседа по коду фермы');input.placeholder='Код фермы или ссылка из Telegram';input.required=true;let b=button('Пригласить',()=>{},'primary wide');b.type='submit';form.append(w,b);form.onsubmit=async e=>{e.preventDefault();let hint=parseInviteHint(input.value);if(!hint){toast('Вставь код фермы или ссылку-приглашение.',true);return;}if(parseInvite(hint))await command('request_neighbor',{},hint);else await safe(()=>acceptSharedInvite(hint))();};p.append(form);
 neighborList=el('div');neighborSnapshot=null;neighborGeneration++;p.append(neighborList);updateNeighbors().catch(e=>{if(S.tab==='neighbors'&&neighborList?.parentNode===p)note(e.message,neighborList);});}
function renderJournal(p){heading('Журнал фермы','ЧТО ПРОИСХОДИЛО У КАЛИТКИ');note('История последних событий. Полный экономический журнал хранится отдельно на сервере.',p);for(let e of S.me.events){let n=el('div',e.text,'event');n.append(el('small',new Date(e.at*1000).toLocaleString('ru-RU')));p.append(n);}p.append(button('Показать движения ресурсов',safe(async()=>{let r=await request(API+'/ledger'),wrap=el('div');for(let x of r.entries.slice(0,25)){let n=el('div',`${x.kind} · ${x.coins_delta>=0?'+':''}${x.coins_delta} мон. · ${x.xp_delta>=0?'+':''}${x.xp_delta} XP`,'event');n.append(el('small',Object.entries(x.inventory_delta).map(([id,q])=>`${itemName(id)} ${q>0?'+':''}${q}`).join(', ')||'Без изменения склада'));wrap.append(n);}modal('Последние операции',wrap);}),'secondary wide'));}
function renderSettings(p){heading('Твоя ферма','ЛЮДИ, ПРАВА И НЕМНОГО УЮТА');renderViewSettings(p);const form=el('form'),[nw,name]=field('Название фермы','text',S.me.name);name.minLength=2;name.maxLength=24;name.required=true;let[vw,v]=field('Кто может смотреть','select');for(let [id,title]of [['friends','Только принятые соседи'],['private','Только я'],['public','Все игроки этого сервера']]){let o=el('option',title);o.value=id;v.append(o);}v.value=S.me.settings.visibility;form.append(nw,vw);let flags={};for(let [id,title]of [['allow_help','Соседи могут помогать с урожаем'],['allow_gifts','Принимать подарки от соседей'],['allow_requests','Просьбы соседей'],['allow_trade','Показывать лавку и принимать покупки'],['allow_pranks','Разрешить безвредные гусиные проделки']]){let[w,input]=checkbox(title,S.me.settings[id]);flags[id]=input;form.append(w);}let b=button('Сохранить настройки',()=>{},'primary wide');b.type='submit';form.append(b);form.onsubmit=async e=>{e.preventDefault();await command('settings',{name:name.value,visibility:v.value,...Object.fromEntries(Object.entries(flags).map(([k,i])=>[k,i.checked]))});};p.append(form);
 if(S.me.pranks.some(g=>g.until>now()))p.append(button('Проводить гуся за калитку',()=>command('clear_prank'),'secondary wide'));
 note('Урожай не увядает. Животные не гибнут. Деньги фермы не превращаются в баллы квиза. Сетевой сбой не подтверждает награду.',p);
 if(S.config.demo){note(`Локальная альфа · темп роста ×${S.speed}. Сохранения: файл на сервере. После выхода можно вернуться по сохранённому секретному ключу.`,p);p.append(button('Выйти из локального профиля',()=>modal('Закрыть калитку?','Ферма останется на сервере. Для возвращения после выхода понадобится сохранённый секретный код.',[button('Выйти',safe(async()=>{await request('/api/farm-demo/logout',{method:'POST'});$('dialog').close();S.me=S.farm=null;S.pending=null;showLogin();}),'primary')]),'text-button'));}
 else{note('Вход и восстановление обслуживает QuizzyWizzy. Выход из платформы не удаляет ферму.',p);if(mode!=='telegram')note('Вход и аккаунт — в профиле QuizzyWizzy (⚙ → профиль).',p);}
}
// --- Equipment, helpers and exploration -------------------------------------
/* ---- r7: zones and bulk actions. Zone/area = null (whole land) or {x,y,w,h} in 0-based cells; the server decides everything ---- */
const AUTO=()=>S.catalog.automation;
const PRESETS=[['all','Вся ферма'],['left','Левая половина'],['right','Правая половина'],['top','Верхняя половина'],['bottom','Нижняя половина'],['tl','Левый верхний угол'],['tr','Правый верхний угол'],['bl','Левый нижний угол'],['br','Правый нижний угол'],['custom','Своя область…']];
function presetRect(id){
 const n=S.me.size,h=Math.ceil(n/2),r=n-h;
 return {all:null,left:{x:0,y:0,w:h,h:n},right:{x:h,y:0,w:r,h:n},top:{x:0,y:0,w:n,h:h},bottom:{x:0,y:h,w:n,h:r},tl:{x:0,y:0,w:h,h:h},tr:{x:h,y:0,w:r,h:h},bl:{x:0,y:h,w:h,h:r},br:{x:h,y:h,w:r,h:r}}[id];
}
const zoneText=z=>z?`колонки ${z.x+1}–${z.x+z.w}, ряды ${z.y+1}–${z.y+z.h}`:'вся ферма';
function matchPreset(z){for(const [id] of PRESETS)if(id!=='custom'&&JSON.stringify(presetRect(id))===JSON.stringify(z))return id;return 'custom';}
function zonePicker(label,zone,onChange){
 const wrap=el('div',null,'zone-picker'),[sw,sel]=field(label,'select'),custom=el('div',null,'zone-custom'),inputs={};
 for(const [id,name] of PRESETS){const o=el('option',name);o.value=id;sel.append(o);}
 for(const [k,t] of [['x1','Колонки от'],['x2','до'],['y1','Ряды от'],['y2','до']]){const [w,i]=field(t,'number');i.min=1;i.max=S.me.size;i.inputMode='numeric';inputs[k]=i;custom.append(w);}
 const fill=z=>{z=z||presetRect('tl');inputs.x1.value=z.x+1;inputs.x2.value=z.x+z.w;inputs.y1.value=z.y+1;inputs.y2.value=z.y+z.h;};
 const clamp=v=>Math.max(1,Math.min(S.me.size,Math.round(Number(v))||1));
 const get=()=>{
  if(sel.value!=='custom')return presetRect(sel.value);
  const x1=clamp(inputs.x1.value),x2=clamp(inputs.x2.value),y1=clamp(inputs.y1.value),y2=clamp(inputs.y2.value);
  return {x:Math.min(x1,x2)-1,y:Math.min(y1,y2)-1,w:Math.abs(x2-x1)+1,h:Math.abs(y2-y1)+1};
 };
 const sync=()=>{custom.hidden=sel.value!=='custom';onChange?.(get());};
 sel.value=matchPreset(zone||null);fill(zone);custom.hidden=sel.value!=='custom';
 sel.onchange=()=>{if(sel.value==='custom')fill(presetRect('tl'));sync();};
 for(const i of Object.values(inputs))i.onchange=sync;
 wrap.append(sw,custom);return {node:wrap,get};
}
const inArea=(o,z)=>!z||(o.x<z.x+z.w&&o.x+o.w>z.x&&o.y<z.y+z.h&&o.y+o.h>z.y);
// Display-only counters: the server recomputes everything when the command arrives.
// Remembered recipes of a workshop, oldest first; falls back to the legacy single last_recipe.
function recipeMemory(o){const raw=Array.isArray(o.recipes_memory)?o.recipes_memory:(o.last_recipe?[o.last_recipe]:[]);return raw.filter(id=>S.catalog.recipes[id]);}
function bulkCounts(z){
 const objs=S.me.objects.filter(o=>inArea(o,z)).sort((a,b)=>a.id<b.id?-1:1),t=now(),lv=S.me.level,stockLeft={...S.me.inventory};
 const take=needs=>{if(!Object.entries(needs).every(([k,q])=>(stockLeft[k]||0)>=q))return false;for(const [k,q] of Object.entries(needs))stockLeft[k]-=q;return true;};
 let feed=0,restart=0;
 for(const o of objs)if(o.animal&&!o.animal_job&&S.catalog.animals[o.animal]&&take(batchOf(S.catalog.animals[o.animal],o).inputs))feed++;
 for(const o of objs){if((o.jobs||[]).length>=slotsOf(o))continue;const r=recipeMemory(o).map(id=>S.catalog.recipes[id]).find(r=>r.building===o.type&&recipeLevel(r)<=lv&&Object.entries(r.inputs).every(([k,q])=>(stockLeft[k]||0)>=q));if(r&&take(r.inputs))restart++;}
 return {plots:objs.filter(o=>(o.type==='plot'&&o.crop&&o.crop.ready_at<=t)||(o.type==='tree'&&o.fruit&&o.fruit.ready_at<=t)).length,animals:objs.filter(o=>o.animal_job&&o.animal_job.ready_at<=t).length,
  workshops:objs.reduce((a,o)=>a+(o.jobs||[]).filter(j=>j.ready_at<=t).length,0),feed,restart,empty:objs.filter(o=>o.type==='plot'&&!o.crop).length};
}
function bulkCard(p){
 if(!own())return;
 const c=card('Быстрые действия','Сотни нажатий не нужны: выбери область и действие','tractor'),box=el('div',null,'bulk-grid');
 let area=S.bulkArea||null;
 const draw=()=>{
  box.replaceChildren();const k=bulkCounts(area),crop=S.catalog.crops[S.seed],afford=crop&&!crop.exotic?Math.min(k.empty,Math.floor(S.me.coins/crop.cost)):0;
  const add=(text,kind,data,count,cls='secondary')=>box.append(button(text,()=>command(kind,{...data,area}),cls+' small',count===0));
  add(`Собрать грядки · ${k.plots}`,'collect_group',{group:'plots'},k.plots,'primary');
  add(`Собрать животных · ${k.animals}`,'collect_group',{group:'animals'},k.animals);
  add(`Собрать мастерские · ${k.workshops}`,'collect_group',{group:'workshops'},k.workshops);
  add(`Накормить всех · ${k.feed}`,'feed_all',{},k.feed);
  add(`Повторить партии · ${k.restart}`,'restart_all',{},k.restart);
  if(crop)add(`Посадить «${crop.name}» · ${afford} из ${k.empty}`,'plant_many',{crop:crop.id},crop.level>S.me.level?0:afford);
 };
 const picker=zonePicker('Область действия',area,z=>{S.bulkArea=z;area=z;scene.areaPreview=z;scene.dirty=true;draw();});
 scene.areaPreview=area;scene.dirty=true;
 c.append(picker.node,box,el('p','Посадка берёт культуру из панели «Посадить» и сажает, пока хватает монет; сбор и кормление работают по тем же правилам, что и по одному.','note'));
 draw();p.append(c);
}
function zoneControls(parent,id,owned){
 const picker=zonePicker('Зона работы',owned.zone||null,z=>{scene.areaPreview=z||{x:0,y:0,w:S.me.size,h:S.me.size};scene.dirty=true;});
 parent.append(el('p',`Сейчас работает: ${zoneText(owned.zone)}`,'note'),picker.node,button('Назначить зону',()=>{scene.areaPreview=null;command('set_zone',{worker:id,zone:picker.get()});},'light wide'));
}
function shiftControls(parent,id,owned,spec){
 const shift=owned.shift;
 if(shift?.status==='working'){
   const quota=shift.quota||shift.done+shift.remaining;
   let c=el('div',null,'shift-box');c.append(el('strong',`На смене · сделано ${shift.done} из ${quota}`),meter(shift.done,quota),el('p',`Осталось до ${shift.remaining} действий. Оплачено до:`, 'note'),timer(shift.until));
   c.append(button('Остановить смену',()=>modal('Остановить помощника?','Уже выполненная работа остаётся. Оплата текущей смены не возвращается.',[button('Остановить',safe(async()=>{if(await command('stop_shift',{worker:id}))$('dialog').close();}),'primary')]),'text-button'));
   parent.append(c);zoneControls(parent,id,owned);return;
 }
 if(shift)note(`Предыдущая смена: ${shift.done} полезных действий. Автопродления нет.`,parent);
 const [w,input]=field('Смена для '+spec.name,'select');
 for(let plan of Object.values(S.catalog.shifts)){const locked=(plan.level||1)>S.me.level;let opt=el('option',`${duration(plan.seconds)} · до ${plan.actions} действий · ${plan.cost} мон.${locked?` · с ${plan.level} ур.`:''}`);opt.value=plan.id;opt.disabled=locked;input.append(opt);}
 const saved=S.shiftChoice?.[id],ok=saved&&(S.catalog.shifts[saved].level||1)<=S.me.level;input.value=ok?saved:'short';
 const start=button('Начать смену',()=>command('start_shift',{worker:id,shift:input.value}),'secondary wide');
 const sync=()=>{const plan=S.catalog.shifts[input.value];start.disabled=S.me.coins<plan.cost||(plan.level||1)>S.me.level;};
 input.onchange=()=>{(S.shiftChoice||={})[id]=input.value;sync();};sync();
 parent.append(w,start);zoneControls(parent,id,owned);
}
function renderTeam(p){
 heading('Техника и команда','У КАЖДОГО СВОЁ ДЕЛО');bulkCard(p);scene.zones=Object.fromEntries([...Object.entries(S.me.helpers),...Object.entries(S.me.equipment)].filter(([,v])=>v.zone).map(([k,v])=>[k,v.zone]));
 const switches=el('div',null,'pill-row');for(let [id,label]of [['equipment','Техника'],['helpers','Помощники']])switches.append(button(label,()=>{S.teamTab=id;renderPanel();},S.teamTab===id||!S.teamTab&&id==='equipment'?'active':''));p.append(switches);
 if((S.teamTab||'equipment')==='equipment'){
  for(let spec of Object.values(S.catalog.equipment)){
   let owned=S.me.equipment[spec.id],c=card(spec.name,owned?'В хозяйстве':`${spec.cost} монет · уровень ${spec.level}`,spec.icon);note(spec.description,c);
   if(!owned)c.append(button(`Купить за ${spec.cost}`,()=>command('buy_equipment',{equipment:spec.id}),'primary wide',S.me.coins<spec.cost||S.me.level<spec.level));
   else if(spec.id==='tractor'){
    const [w,sel]=field('Культура для трактора','select');
    for(let crop of sortSeeds(Object.values(S.catalog.crops).filter(c=>!c.exotic&&!c.orchard),S.me.level).filter(c=>c.level<=S.me.level)){const st=seedStats(crop,S.catalog.items[crop.id].price,S.speed,S.catalog.crop_classes);let o=el('option',`${crop.name} · ${st.label} · ${timeText(st.seconds)} · ${crop.cost} мон./грядка`);o.value=crop.id;sel.append(o);}sel.value=S.tractorCrop||S.lastRun?.tractor?.crop||S.seed;if(!sel.value)sel.value=sel.options[0]?.value;
    const info=el('p',null,'note'),go=button('',()=>{S.tractorCrop=sel.value;runPlan(planMachine({machine:spec.id,crop:sel.value,replant:false},S.me,S.catalog,now()));},'secondary wide');
    const upd=()=>{const plan=planMachine({machine:spec.id,crop:sel.value,replant:false},S.me,S.catalog,now());info.textContent=plan.ok?`Засеем ${plan.count} грядок: ${fmt(plan.cost)} монет на семена. За рейс — не больше 24 грядок.`:plan.why;go.textContent=plan.ok?`Засеять свободные · ${plan.count}`:'Засеять свободные';go.disabled=!plan.ok;};
    sel.onchange=()=>{S.tractorCrop=sel.value;upd();};upd();
    c.append(w,info,go);
   }else if(spec.id==='harvester'){
    const [w,replant]=checkbox('Сразу пересеять те же культуры',S.combineReplant!==false),info=el('p',null,'note'),go=button('',()=>{runPlan(planMachine({machine:spec.id,crop:'',replant:replant.checked},S.me,S.catalog,now()));},'secondary wide');
    const upd=()=>{const plan=planMachine({machine:spec.id,crop:'',replant:replant.checked},S.me,S.catalog,now());info.textContent=plan.ok?`Готово зерновых: ${plan.count}.${replant.checked?` Повторный посев: ${fmt(plan.cost)} монет.`:''} За рейс — не больше 24 грядок.`:plan.why;go.textContent='Отправить комбайн';go.disabled=!plan.ok;};
    replant.onchange=()=>{S.combineReplant=replant.checked;upd();};upd();
    c.append(w,info,go);
   }else shiftControls(c,spec.id,owned,spec);
   p.append(c);
  }
 }else{
  for(let spec of Object.values(S.catalog.helpers)){
   const owned=S.me.helpers[spec.id],c=card(spec.name,owned?'В команде':`${spec.cost} монет · уровень ${spec.level}`,spec.icon);note(spec.description,c);if(AUTO().roles[spec.role])c.append(el('span',AUTO().roles[spec.role],'tag'));
   if(!owned)c.append(button(`Нанять за ${spec.cost}`,()=>command('hire_helper',{helper:spec.id}),'primary wide',spec.level>S.me.level||spec.cost>S.me.coins));
   else if(spec.role==='guide'){let trip=S.me.trips.find(t=>t.guide===spec.id);if(trip){c.append(el('p',tripCategory(trip)==='fishing'?'Сейчас на рыбалке':'Сейчас в вылазке','note'),timer(trip.ready_at));}else c.append(button('Выбрать лесную тропу',()=>selectTab('forest'),'secondary wide'),button('Пойти на рыбалку',()=>selectTab('lake'),'secondary wide'));}
   else shiftControls(c,spec.id,owned,spec);
   p.append(c);
  }
 }
 note('Смены оплачиваются один раз и имеют предел работы. При отсутствии задач помощник ждёт. Время и результат считает сервер, открытая вкладка не нужна.',p);
}
function undoRules(){return S.catalog.undo||{window:60,late_refund_pct:50,late_loot_pct:50};}
function cropCost(c){return Number.isInteger(c.cost)?c.cost:(S.catalog.crops[c.id]?.cost||0);}
function tripTaken(trip){
 if(trip.taken)return trip.taken;
 const r=S.catalog.routes[trip.route];return {coins:r?r.cost:0,items:r?r.inputs:{}};
}
function undoLeft(since){return Math.ceil(since+undoRules().window-now());}
function undoFull(since){return now()<=since+undoRules().window;}
function digRefund(c){const cost=cropCost(c);return undoFull(c.planted_at)?cost:Math.floor(cost*undoRules().late_refund_pct/100);}
function jobRefund(j){const full=j.starts_at>now()||undoFull(j.starts_at),r={};for(let [k,q] of Object.entries(j.inputs||{})){const v=full?q:Math.floor(q*undoRules().late_refund_pct/100);if(v>0)r[k]=v;}return {items:r,full};}
function confirmCancelJob(o,j){
 const rf=jobRefund(j),name=S.catalog.recipes[j.recipe]?.name||'Партия',list=Object.entries(rf.items).map(([id,q])=>`${itemName(id)} ×${q}`).join(', ');
 const text=rf.full?`Ингредиенты вернутся полностью${list?': '+list:''}.`+(j.starts_at>now()?'':` Это ещё можно отменить без потерь, если подтвердить до истечения срока (ещё ${Math.max(0,undoLeft(j.starts_at))} с).`):`Партия остановится, продукции и опыта не будет. `+(list?`Вернётся половина ингредиентов: ${list}.`:'Ничего не вернётся.');
 const cancel=async(forget)=>{$('dialog').close();await command(forget?'cancel_job_and_forget_recipe':'cancel_job',{object:o.id,job:j.id});};
 const remembered=recipeMemory(o).includes(j.recipe),tail=remembered?' Помощник-мастер поставит этот рецепт заново, если не забыть его.':'';
 modal(`Отменить: ${name}?`,text+tail,[button('Отменить партию',safe(()=>cancel(false)),'primary')].concat(remembered?[button('Отменить и забыть рецепт',safe(()=>cancel(true)),'secondary')]:[]));
}
function confirmDigUp(o){
 const c=o.crop;if(!c)return;
 const full=undoFull(c.planted_at),sum=digRefund(c);
 modal(`Выкопать: ${itemName(c.id)}?`,full?`Это ещё можно отменить без потерь: семена вернутся полностью, +${sum} монет (ещё ${Math.max(0,undoLeft(c.planted_at))} с). Урожая и опыта не будет.`:`Посадка пропадёт, урожая и опыта не будет. Вернётся половина цены семян: +${sum} монет.`,
  [button('Выкопать',safe(async()=>{$('dialog').close();await command('dig_up',{object:o.id,revision:o.revision});}),'primary')]);
}
function routeCategory(route){return route?.category==='fishing'||route?.kind==='fishing'?'fishing':'forest';}
function tripCategory(trip){return trip.category==='fishing'||trip.kind==='fishing'?'fishing':routeCategory(S.catalog.routes[trip.route]);}
function tripUndoLabel(trip){const fishing=trip.kind==='fishing'||S.catalog.routes[trip.route]?.kind==='fishing';return undoFull(trip.started_at)?(fishing?'Отменить рыбалку':'Отменить вылазку'):'Вернуться раньше';}
function tripEarlyLoot(trip){
 const total=Math.max(1,trip.ready_at-trip.started_at),elapsed=Math.max(0,now()-trip.started_at),loot={},pct=undoRules().late_loot_pct;
 for(const [id,q] of Object.entries(trip.outputs)){const n=Math.floor(q*elapsed*pct/(total*100));if(n>0)loot[id]=n;}
 return loot;
}
function confirmTripReturn(trip){
 const box=el('div'),full=undoFull(trip.started_at),taken=tripTaken(trip),fishing=tripCategory(trip)==='fishing',cancel=fishing?'Отменить рыбалку':'Отменить вылазку';
 if(full){
  box.append(el('p',`${fishing?'Рыбалка':'Вылазка'} отменится, всё взятое вернётся полностью${taken.coins?`: ${taken.coins} монет`:''}${Object.keys(taken.items).length?' и вещи с собой':''}. ${fishing?'Улова':'Находок'} не будет (ещё ${Math.max(0,undoLeft(trip.started_at))} с).`));
  if(Object.keys(taken.items).length)box.append(goods(taken.items,false));
 }else{
  const loot=tripEarlyLoot(trip);
  box.append(el('p',`Ты вернёшься раньше срока и принесёшь только половину ${fishing?'улова':'находок'} пропорционально пройденному времени. Опыта не будет, взятое с собой и плата за выход не вернутся.${Object.keys(loot).length?' Сейчас это примерно:':fishing?gf(' Сейчас ты ещё ничего не успел поймать.',' Сейчас ты ещё ничего не успела поймать.',' Пока ничего не поймано.'):gf(' Сейчас ты ещё ничего не успел собрать.',' Сейчас ты ещё ничего не успела собрать.',' Пока ничего не собрано.')}`));
  if(Object.keys(loot).length)box.append(goods(loot,false));
 }
 modal(full?`${cancel}?`:'Вернуться раньше срока?',box,[button(full?cancel:'Вернуться',safe(async()=>{$('dialog').close();await command('abort_trip',{trip:trip.id});}),'primary')]);
}
function renderForest(p){
 heading('Лесные вылазки','ЗА ГРИБАМИ, ЯГОДАМИ И ИСТОРИЯМИ');
 renderTrips(p,'forest');
}
// The raven on the knight's stone speaks in a bubble beside it (a DOM card that follows the camera and stays inside the map on phones and desktops).
function showStoneSpeech(){
 const area=document.querySelector('.scene-area');if(!area)return;
 let b=S.stoneSpeech;
 if(!b){b=S.stoneSpeech=el('div',null,'stone-speech');b.setAttribute('role','status');b.append(el('strong','Ворон на камне: «Кар!»'),...['Налево пойдёшь — уху найдёшь,','направо — коня потеряешь,','а прямо — домой, на ферму.'].map(line=>el('span',line,'stone-speech-line')),el('i',null,'stone-speech-tail'));area.append(b)}
 // A thought, not a dialogue: it fades in, lingers a few seconds and fades out; tapping the stone again brings it back.
 b.hidden=false;b.dataset.hideAt=String(Date.now()+5200);placeStoneSpeech();requestAnimationFrame(()=>b.classList.add('on'));
}
function hideStoneSpeech(){const b=S.stoneSpeech;if(!b||b.hidden)return;b.classList.remove('on');setTimeout(()=>{if(!b.classList.contains('on'))b.hidden=true},500)}
function placeStoneSpeech(){
 const b=S.stoneSpeech;if(!b||b.hidden)return;
 const left0=Number(b.dataset.hideAt)-Date.now();
 if(villageVisible()||S.tab==='fields'||left0<-600){b.hidden=true;b.classList.remove('on');return}
 if(left0<500)b.classList.remove('on');
 const rv=scene.stoneRavenPos(),p=scene.worldToScreen(rv.x,rv.y),area=b.parentElement.getBoundingClientRect(),cv=$('farm-canvas').getBoundingClientRect();
 const ax=p.x+cv.left-area.left,ay=p.y+cv.top-area.top,w=b.offsetWidth,h=b.offsetHeight,m=8;
 // The cloud floats up and to the right of the raven so it never covers the bird, and the tail still points at it.
 const left=Math.min(Math.max(m,ax-w*.28),Math.max(m,area.width-w-m));
 let top=ay-h-34,below=false;if(top<m){top=ay+30;below=true}
 b.style.left=`${Math.round(left)}px`;b.style.top=`${Math.round(Math.min(Math.max(m,top),Math.max(m,area.height-h-m)))}px`;
 b.style.setProperty('--tail',`${Math.round(Math.min(Math.max(16,ax-left),w-16))}px`);b.toggleAttribute('data-below',below);
}
// The tea arbor: a rest stop with a summary of what is ready and Филиныч's tea-time question (the same server game and cooldown as in his house).
function renderArbor(p){
 heading('Чайная беседка','ПЕРЕРЫВ С ФИЛИНЫЧЕМ');
 const t=now(),objects=S.me.objects||[],crops=objects.filter(o=>(o.type==='plot'&&o.crop&&o.crop.ready_at<=t)||ORCH.ripe(o,t)).length,jobs=objects.filter(o=>o.jobs?.some(j=>j.ready_at<=t)||(o.animal_job&&o.animal_job.ready_at<=t)).length,orders=(S.me.orders||[]).length;
 note('Присядь, выдохни и посмотри, что на ферме уже ждёт тебя. Филиныч любит задавать вопрос за чаем.',p);
 const c=card('Что ждёт на ферме','Сводка за чаем','home');
 const rows=[[`Готовый урожай: ${crops}`,crops>0,'Собрать',()=>{closePanel();const o=objects.find(o=>(o.type==='plot'&&o.crop&&o.crop.ready_at<=t)||ORCH.ripe(o,t));if(o)scene.focus(o,true,window.innerWidth<=850?Math.round(window.innerHeight*.4):0);}],[`Готово в мастерских и у животных: ${jobs}`,jobs>0,'Показать',()=>selectTab('production')],[`Заказов на доске: ${orders}`,orders>0,'К заказам',()=>selectTab('orders')]];
 for(const [text,active,label,go] of rows){const line=el('div',null,'card-footer');line.append(el('span',text,'reward'),button(label,go,'secondary',!active));c.append(line);}
 p.append(c);
 renderMinigame('house',p);
}
function renderLake(p){
 heading('Озеро','ТИХАЯ ВОДА, ХОРОШИЙ УЛОВ');
 note('Рыбачить можно прямо с берега. Причал строится у Филиныча: собери материалы проекта в складе и заверши этап в доме.',p);
 renderSwans(p);
 renderTrips(p,'fishing');
 renderFishJournal(p);
}
// «Журнал улова» (FARM_TRIP_MINIGAMES.md §10.5): owner-only, written by the server when a played fishing game lands fish.
// Rare fish live only here: they are never items and never sold.
function renderFishJournal(p){
 const f2=S.catalog?.trip_games?.fish2;if(!f2||!S.me)return;
 const j=S.me.fish_journal||{},ids=Object.keys(f2.species),got=ids.filter(id=>j[id]);
 const place=id=>{const rid=Object.keys(f2.routes).find(r=>f2.routes[r].rare===id);return S.catalog.routes[rid]?.name||'';};
 const c=card('Журнал улова',`Поймано видов: ${got.length} из ${ids.length}`,'journal'),list=el('ul',null,'fish-journal');
 for(const id of ids){
  const sp=f2.species[id],row=j[id],li=el('li',null,`${row?'':'unknown'} ${sp.rare?'rare':''}`.trim()),text=el('div');
  text.append(el('b',row||!sp.rare?sp.name:'Редкая рыба'),el('small',row?`${row.n} шт. · лучшая ${tripGrams(row.g)}`:sp.rare?`${place(id)} · на точный заброс`:'ещё не ловилась'));
  li.append(icon(id),text);list.append(li);
 }
 c.append(el('p','Рыбачь сам, чтобы пополнить журнал: улов игры записывается сюда.','note'),list);p.append(c);
}
// Feeding the lake swans: the server owns cost, XP, the daily limit and the cooldown (S.me.swans); the scene only reacts.
function swanFeedBlock(w,t,have){
 if(!w.unlocked)return `Откроется с ${w.level} уровня`;
 if(swansLeft(w,t)<=0)return 'Сегодня лебеди сыты. Приходи завтра.';
 if(w.next_at>t)return 'wait';
 return have?'':'Не хватает зерна';
}
function renderSwans(p){
 const w=S.me?.swans;if(!w)return;
 const block=swanFeedBlock(w,now(),stock(w.item)>=w.cost),c=card('Лебеди',`Сегодня можно покормить: ${swansLeft(w,now())} из ${w.daily_limit} · +${w.xp} опыта`,'swan');
 c.append(el('p','Лебеди подплывают к берегу за зерном.','note'),goods({[w.item]:w.cost}));
 const stack=el('div',null,'qw-btn-stack');
 stack.append(button('Покормить лебедей',()=>command('feed_swans').then(ok=>{if(ok)scene.feedSwans?.();return ok;}),'qw-btn primary wide',!!block||S.busy));
 if(block==='wait'){const hint=el('p','Лебеди ещё доедают · ','qw-btn-hint');hint.append(timer(w.next_at));stack.append(hint);}
 else if(block)stack.append(el('p',block,'qw-btn-hint'));
 c.append(stack);p.append(c);
}
function renderTrips(p,category){
 const fishing=category==='fishing';
 for(let trip of S.me.trips.filter(t=>tripCategory(t)===category)){
  let route=S.catalog.routes[trip.route],c=card(route.name,trip.guide?S.catalog.helpers[trip.guide].name:fishing?'Твоя рыбалка':'Твоя прогулка',route.icon);
  c.append(timer(trip.ready_at),goods(finalOutputs(trip),false));
  if(trip.game?.state==='done')c.append(el('p',bonusLine(trip,itemName),'note'));
  // UI_RULES §9: one primary action, the hint under its button, the destructive action apart in its own zone.
  const stack=el('div',null,'qw-btn-stack trip-actions'),ready=trip.ready_at<=now(),playable=trip.game?.state!=='done'&&canPlay(trip,now());
  const play=()=>[button(fishing?'Порыбачить самому':'Пройтись самому',()=>launchTripGame(trip),`qw-btn ${ready?'secondary':'primary'} wide`),el('p',fishing?'до +25% улова':'до +25% находок','qw-btn-hint')];
  if(ready){
   stack.append(button(fishing?'Забрать улов':'Разобрать корзину',()=>command('collect_trip',{trip:trip.id}),'qw-btn primary wide'));
   if(playable)stack.append(...play());
  }else{
   if(playable)stack.append(...play());
   const wait=el('p',fishing?'Улов можно будет забрать через ':'Корзину можно будет разобрать через ','note qw-btn-hint');wait.append(timer(trip.ready_at));stack.append(wait);
   const zone=el('div',null,'qw-danger-zone');zone.append(button(tripUndoLabel(trip),()=>confirmTripReturn(trip),'qw-btn danger wide'));stack.append(zone);
  }
  c.append(stack);
  p.append(c);
 }
 note(`Рыбалка и лес делят два места: ${S.me.trips.length} / 2 занято. Ты и проводник или два проводника могут заниматься разными делами. ${fishing?'Улов':'Собранное'} не портится и ждёт возвращения.`,p);
 const routes=Object.values(S.catalog.routes).filter(r=>routeCategory(r)===category);
 if(!routes.length)note(fishing?'Места для рыбалки пока недоступны.':'Лесные тропы пока недоступны.',p);
 for(let route of routes){
  let c=card(route.name,`${duration(route.seconds)} · ${route.cost} монет · ур. ${route.level}`,route.icon);note(route.description,c);c.append(goods(route.outputs,false));
  if(Object.keys(route.inputs).length){c.append(el('p','Взять с собой','note'),goods(route.inputs));}
  let[w,guide]=field((fishing?'Кто рыбачит: ':'Кто идёт: ')+route.name,'select');let solo=el('option',fishing?gf('Порыбачу сам','Порыбачу сама','Рыбалка без проводника'):gf('Пойду сам','Пойду сама','Вылазка без проводника'));solo.value='';solo.disabled=S.me.trips.some(t=>!t.guide);guide.append(solo);
  for(let [id,owned]of Object.entries(S.me.helpers)){const h=S.catalog.helpers[id];if(h.role!=='guide')continue;let opt=el('option',`${h.name}${h.specialty===route.specialty?fishing?' · бонус улова':' · бонус находок':''}`);opt.value=id;opt.disabled=S.me.trips.some(t=>t.guide===id);guide.append(opt);}
  let choices=[...guide.options].filter(x=>!x.disabled);guide.value=choices.find(x=>x.value===S.guideChoice?.[route.id])?.value||choices[0]?.value||'';
  const blocked=S.me.trips.length>=2||route.level>S.me.level||route.cost>S.me.coins||!enough(route.inputs)||!choices.length,startBox=el('div',null,'trip-start');
  const paintStart=()=>{
   if(guide.value===''){
    const stack=el('div',null,'qw-btn-stack');
    stack.append(button(fishing?'Порыбачу сам · мини-игра':'Пойду сам · мини-игра',()=>startTrip(route,'',true),'qw-btn primary wide',blocked),
     el('p',fishing?'до +25% улова; время и опыт не меняются':'до +25% находок; время и опыт не меняются','qw-btn-hint'),
     button('Сам, без игры',()=>startTrip(route,'',false),'qw-btn secondary wide',blocked),
     el('p',fishing?'Без игры улов обычный.':'Без игры корзина обычная.','qw-btn-hint'));
    startBox.replaceChildren(stack);
   }else startBox.replaceChildren(button(fishing?'Отправить на рыбалку':'Отправить',()=>startTrip(route,guide.value,false),'qw-btn primary wide',blocked));
  };
  guide.onchange=()=>{(S.guideChoice||={})[route.id]=guide.value;paintStart();};paintStart();
  c.append(w,startBox);p.append(c);
 }
}
function renderSecrets(p){
 heading('Кабинет находок','ЗНАКОМЫЕ МИРЫ — НЕОЖИДАННЫЕ СЛЕДЫ');
 note('Пасхалки «Алхимии» и «Мафии» открываются прямо на ферме. Они не читают роли игроков и не меняют валюты других игр.',p);
 for(let secret of Object.values(S.catalog.secrets)){
  const found=S.me.secrets.includes(secret.id),c=card(found?secret.name:'Неизвестная находка',secret.world,found?secret.icon:'discovery');
  note(found?secret.text:secret.hint,c);
  if(found){const b=S.catalog.buildings[secret.decor];c.append(button(`Декор: ${b.name} · ${b.cost} мон.`,()=>beginPlacement(b),'secondary wide',b.cost>S.me.coins));}
  if(secret.id==='detective'&&!found){c.append(goods({bread:2,egg:2}),button('Передать ночной завтрак',()=>command('night_delivery'),'primary wide',S.me.stats.orders<3||!enough({bread:2,egg:2})));}
  p.append(c);
 }
}
// Festivals: the server sends the calendar and the fair (S.me.festival); the device only keeps the show/hide switches.
const festivalView=()=>S.me?.festival||null;
const festivalTab=()=>FEST.tabVisible(festivalView());
function syncFestivalWorld(){
 const view=festivalView(),flags=FEST.applyWorld(view);syncVillageFest();
 const cur=view?.current;if(!cur||!own())return;
 const mark=cur.key||`${cur.id}:${cur.starts_at}`;let seen=null;try{seen=localStorage.getItem('qw-farm.festival-seen');}catch{}
 if(seen!==mark){try{localStorage.setItem('qw-farm.festival-seen',mark);}catch{}toast(`В деревне праздник: ${cur.name}.`);}
 return flags;
}
function festivalHelpers(){
 return {el,button,card,goods,note,checkbox,stock,fmt,itemName,command,icon,busy:()=>S.busy,coins:()=>S.me?.coins||0,rerender:()=>{if(S.me)renderPanel();}};
}
function renderFestivalTab(p){
 heading('Праздник','ДЕРЕВНЯ НАРЯЖАЕТСЯ');
 FEST.renderFestival(p,festivalView(),festivalHelpers());
}
function festivalBanner(p){
 const view=festivalView(),text=FEST.bannerText(view);if(!own()||!text)return;
 const row=el('section',null,'card fest-banner'),line=el('div',null,'card-footer');
 line.append(el('span',text,'reward'),button('Открыть',()=>selectTab('festival'),'qw-btn secondary'));
 row.append(line);p.prepend(row);
}
function renderMore(p){heading('Все разделы','ПОД РУКОЙ, НО НЕ ПЕРЕД ГЛАЗАМИ');let grid=el('div',null,'more-grid');for(let [id,ico,title]of tabs.filter(([id])=>id!=='festival'||festivalTab())){let b=button(null,()=>selectTab(id),'more-item');b.append(icon(ico),el('span',title));b.dataset.moreTab=id;grid.append(b);}p.append(grid,button('Список всех объектов',()=>selectTab('objects'),'secondary wide'));syncOrchardBadge(grid);}
function closeDashaGame(){if(!dashaGameOpen)return true;dashaGameOpen=false;document.body.classList.remove('dasha-game-open');dashaGame?.destroy();dashaGame=null;navPop('dasha-wager');requestAnimationFrame(()=>document.querySelector('[data-open-dasha]')?.focus({preventScroll:true}));return true;}
async function openDashaGame(){
 if(!own()||!S.me)return;
 if(!S.me.wager){try{await refresh({render:false});}catch(e){toast(e.message,true);return;}}
 if(!S.me?.wager){toast('Игра Даши пока недоступна. Обнови ферму.',true);return;}
 const host=$('dasha-game-view');if(dashaGameOpen){dashaGame?.render();return;}
 dashaGameOpen=true;document.body.classList.add('dasha-game-open');
 dashaGame=mountDashaGame(host,{getState:()=>({wager:S.me?.wager,coins:S.me?.coins}),command,isCommandPending:()=>!!S.pending||S.busy,onBack:closeDashaGame});navPush('dasha-wager',closeDashaGame);
 try{await refresh({render:false});}catch(e){toast(e.message,true);}finally{dashaGame?.render();}
}
// Oleg's chime: the same nested view as Dasha's; oleg.py owns melodies, rounds and the daily reward.
function closeOlegGame(){if(!olegGameOpen)return true;olegGameOpen=false;document.body.classList.remove('oleg-game-open');olegGame?.destroy();olegGame=null;navPop('oleg-chime');requestAnimationFrame(()=>document.querySelector('[data-open-oleg]')?.focus({preventScroll:true}));return true;}
async function openOlegGame(){
 if(!own()||!S.me)return;
 if(!S.me.oleg_game){try{await refresh({render:false});}catch(e){toast(e.message,true);return;}}
 if(!S.me?.oleg_game){toast('Перезвон пока недоступен. Обнови ферму.',true);return;}
 const host=$('oleg-game-view');if(olegGameOpen){olegGame?.render();return;}
 olegGameOpen=true;document.body.classList.add('oleg-game-open');
 olegGame=mountOlegGame(host,{getState:()=>S.me?.oleg_game,command,isCommandPending:()=>!!S.pending||S.busy,onBack:closeOlegGame});navPush('oleg-chime',closeOlegGame);
}
function closePanel(){if(villageVisible()){const returnTo=villageSheet==='townhall'?'townhall':villageResident;villageSheet=null;S.lastRenderedVillageSheet=null;syncVillageScene();const world=$('village-scene');[...world.querySelectorAll('[data-village-npc],[data-village-townhall]')].find(n=>n.dataset.villageNpc===returnTo||n.dataset.villageTownhall===returnTo)?.focus({preventScroll:true});}document.body.classList.remove('panel-open');document.body.classList.add('panel-collapsed');requestAnimationFrame(()=>scene.resize());}
function showPanel(){document.body.classList.add('panel-open');document.body.classList.remove('panel-collapsed');requestAnimationFrame(()=>scene.resize());}
function copyText(text,label='Скопировано.'){return safe(async()=>{try{await navigator.clipboard.writeText(text);toast(label);}catch{modal('Скопируй текст',el('div',text,'code'));}});}
function renderInviteRewards(parent,r){
 if(!r)return;
 // One card for both rewards: inviting a friend and a new neighborhood (rules for both under one «Правила и лимиты»).
 let c=card('Награды за соседей','Монеты за приглашения и соседство','friends');
 note(`Приглашение: друг получит ${r.bonus} монет сразу, а ты — ${r.reward} монет, когда он достигнет ${r.level} уровня.`,c);
 if(r.neighbor)note(`Новое соседство: вы оба получите по ${r.neighbor.reward} монет автоматически.`,c);
 const words={rewarded:'награда получена',ready:'награда ждёт свободного места в дневном лимите',growing:'растёт'};
 for(const i of r.invited)c.append(el('p',`${i.name} · уровень ${Math.min(i.level,i.goal)} из ${i.goal} · ${words[i.status]||i.status}`,'note'));
 if(!r.invited.length)note('Пока никто не пришёл по твоему приглашению.',c);
 let limits=el('details',null,'invite-rules');limits.append(el('summary','Правила и лимиты'),el('p',`Приглашения: одна награда за ферму. Не больше ${r.per_day} в день и ${r.total_limit} всего. Сегодня доступно: ${r.today_left}. Получено: ${r.total} (${r.earned} монет).`));
 if(r.neighbor)limits.append(el('p',`Соседство: один раз для пары. Не больше ${r.neighbor.per_day} в день и ${r.neighbor.total_limit} всего. Сегодня доступно: ${r.neighbor.today_left}. Получено: ${r.neighbor.total} (${r.neighbor.earned} монет). За старое неоплаченное соседство подарок можно забрать по кнопке у соседа.`));
 c.append(limits);
 if(r.can_enter_code){
  const form=el('form'),[w,input]=field('Тебя пригласили? Введи код друга');input.placeholder='Код фермы';input.autocomplete='off';
  const b=button('Получить бонус',()=>{},'secondary wide');b.type='submit';form.append(w,b);
  form.onsubmit=e=>{e.preventDefault();safe(async()=>{const code=parseInvite(input.value);if(!code){toast('Вставь код фермы или ссылку-приглашение.',true);return;}
   const done=await request(API+'/invite/accept',{method:'POST',data:{code}});toast(`Бонус получен. Монет: ${done.coins}.`);await refresh();})();};
  c.append(form);
 }
 parent.replaceChildren(c);
}
async function acceptSharedInvite(token){
 const done=await request(API+'/invite/join',{method:'POST',data:{token}});
 toast(done.notice||'Теперь вы соседи!');
 if(S.invite===token){S.invite=null;clearInvite();}
 await refresh({render:false});renderPanel();
}
function renderSharing(p){
 const incoming=S.invite;
 if(incoming&&incoming!==S.me.id){
  const shared=!parseInvite(incoming),c=card('Тебя пригласили на ферму',shared?'Подтверди приглашение — соседство появится у вас обоих.':'Старое приглашение: хозяину нужно подтвердить запрос.','friends');
  if(!shared)c.append(el('div',incoming,'code'));
  c.append(button(shared?'Принять приглашение':'Отправить запрос в соседи',safe(async()=>{
   if(shared)await acceptSharedInvite(incoming);
   else if(await command('request_neighbor',{},incoming)){S.invite=null;clearInvite();renderPanel();}
  }),'primary wide'),button('Убрать приглашение',()=>{S.invite=null;clearInvite();renderPanel();},'text-button'));p.append(c);
 }
 let share=card('Пригласить друга',null,'telegram'),rewardCard=el('div');p.append(share,rewardCard);
 request(API+'/invite').then(info=>{
  if(!share.isConnected)return;
  S.shareInfo=info;
  renderInviteRewards(rewardCard,info.rewards);
  if(info.local_only){
   note('Общей ссылки пока нет. Отправь код фермы игроку на том же сервере: после его запроса подтверди соседство.',share);
   share.append(el('div',info.code,'code'),button('Скопировать код фермы',copyText(info.code,'Код фермы скопирован.'),'secondary wide'));
   return;
  }
  const tgMode=inTelegram(),hasLink=!info.local_only;
  // The server keeps one reusable link per farm (up to max_uses neighbors); every call returns the same link.
  // {telegram:true} also asks for a prepared message (native chat picker via shareMessage), {rotate:true} replaces the link.
  const linkLine=el('p',null,'note invite-link-state');linkLine.hidden=true;
  const showLink=l=>{
   linkLine.hidden=!l;if(!l)return;
   const until=new Date(l.expires_at*1000).toLocaleDateString('ru-RU',{day:'numeric',month:'long'});
   linkLine.textContent=`По ссылке вступили ${l.uses} из ${l.max_uses} · действует до ${until}`;
  };
  showLink(info.link);
  const issue=async(data={})=>{const value=await request(API+'/invite/share',{method:'POST',data});showLink(value);return value;};
  const copyIssued=async(value,label)=>{
   const invitation=await issue(),content=value(invitation);
   try{await navigator.clipboard.writeText(content);toast(label);}
   catch{modal('Скопируй текст приглашения',el('div',content,'code'));}
  };
  const draftLink=(title,label,url)=>{
   const link=el('a',label,'primary');link.href=url;link.target='_blank';link.rel='noopener noreferrer';
   modal(title,link);
  };
  const telegramDraft=url=>{
   if(QW?.tg&&typeof QW.tg.openTelegramLink==='function'){
    try{openTelegram(url);return;}catch{}
   }
   draftLink('Приглашение в Telegram','Открыть Telegram',url);
  };
  note('Отправь приглашение другу. Он подтвердит соседство в игре.',share);share.append(linkLine);
  const shareButton=button('Поделиться ссылкой',safe(async()=>{
   const invitation=await issue();
   const result=await shareLink(invitation,async value=>{await navigator.clipboard.writeText(value);});
   if(result==='copied')toast('Ссылка скопирована.');
   else if(result==='failed')modal('Скопируй ссылку',el('div',invitation.mini_app_url||invitation.web_url||invitation.text,'code'));
  }),tgMode&&hasLink?'secondary wide':'primary wide');
  shareButton.textContent='Поделиться приглашением';
  const mailButton=button('Отправить по почте',safe(async()=>{const invitation=await issue();draftLink('Письмо с приглашением','Открыть письмо',mailtoUrl(invitation));}),'secondary wide');
  const telegramButton=hasLink?button('Выбрать чат в Telegram',safe(async()=>{
   const tg=QW?.tg,native=tgMode&&typeof tg?.shareMessage==='function'&&tg.isVersionAtLeast?.('8.0');
   const invitation=await issue(native?{telegram:true}:{});
   if(native&&invitation.prepared_message_id){
    try{tg.shareMessage(invitation.prepared_message_id,sent=>{if(sent)toast('Приглашение отправлено.');});return;}catch{}
   }
   telegramDraft(invitation.share_url);
  }),tgMode?'primary wide':'secondary wide'):null;
  const actions=el('div',null,'invite-actions');
  actions.append(tgMode&&telegramButton?telegramButton:shareButton);
  if(hasLink)actions.append(button('Скопировать ссылку',safe(()=>copyIssued(invitation=>invitation.mini_app_url||invitation.web_url,'Ссылка скопирована.')),'secondary wide'));
  share.append(actions);
  const more=el('details',null,'invite-more'),summary=el('summary','Другие способы отправить'),moreActions=el('div',null,'invite-actions');more.append(summary,moreActions);
  if(tgMode&&telegramButton)moreActions.append(shareButton);else if(!tgMode&&telegramButton)moreActions.append(telegramButton);
  moreActions.append(mailButton,button('Скопировать текст приглашения',safe(()=>copyIssued(invitation=>invitation.text,'Скопировано.')),'secondary wide'));
  const rotate=button('Сменить ссылку',()=>modal('Сменить ссылку?','Старая ссылка перестанет работать. Соседи, которые уже вступили по ней, останутся.',
   [button('Сменить',safe(async()=>{await issue({rotate:true});$('dialog').close();toast('Ссылка обновлена.');}),'secondary danger')]),'text-button danger');
  const [w,input]=field('Telegram @username');input.placeholder='@имя_соседа';input.autocomplete='off';
  let b=button('Открыть чат',safe(async()=>{const value=input.value.trim().replace(/^@/,'');if(!/^[A-Za-z][A-Za-z0-9_]{4,31}$/.test(value)){toast('Нужен Telegram @username, не код фермы.',true);return;}const invitation=await issue();telegramDraft('https://t.me/'+value+'?text='+encodeURIComponent(invitation.text));}),'secondary wide');moreActions.append(w,b);
  note('Игра откроет черновик — сообщение отправишь ты.',moreActions);moreActions.append(rotate);
  share.append(more);
 }).catch(e=>note(e.message,share));
}
// Sign-in entry of the logged-out screen only; the way back to the main menu is ⚙ → «Главное меню» (shared shell).
function quizzyLoginLink(){
 const link=el('a',null,'settings-home-link'),mark=el('span','Q','brand-icon');mark.append(el('span','W'));
 const invite=parseInviteHint(S.invite);link.href=invite?`/app?invite=${encodeURIComponent(invite)}`:'/app';
 link.setAttribute('aria-label','Войти через QuizzyWizzy');mark.setAttribute('aria-hidden','true');
 link.append(mark,el('span','Войти через QuizzyWizzy'));return link;
}
function renderViewSettings(p){
 p.append(el('h3','Экран и управление','subheading'));
 const [lw,lighting]=field('Свет на ферме','select');
 for(const [value,label]of [['auto','По времени'],['day','Всегда день'],['night','Всегда ночь']]){const option=el('option',label);option.value=value;lighting.append(option);}
 lighting.id='farm-lighting-mode';lighting.value=lightingMode;lighting.onchange=()=>setLightingMode(lighting.value);p.append(lw);
 note('По времени — по часам твоего устройства: рассвет с 05:00, день с 08:00, сумерки с 17:00, ночь с 21:00.',p);
 let [cw,compact]=checkbox('Компактный интерфейс без большого заголовка',document.body.classList.contains('compact'));compact.onchange=()=>{document.body.classList.toggle('compact',compact.checked);try{localStorage.setItem('qw-farm.compact',String(compact.checked));}catch{}scene.resize();};
 let [mw,motion]=checkbox('Спокойный режим: меньше анимаций',!scene.motion);motion.onchange=()=>{scene.motion=!motion.checked;try{localStorage.setItem('qw-farm.reduced-motion',String(motion.checked));}catch{}};
 p.append(cw,mw,el('p','Полный экран и режим «Только ферма и счётчики» — в меню ⚙. Управление и подсказки — там же.','note'));
}
// «Управление и подсказки» (⚙ menu): the former hint paragraphs of the settings tab.
function showControlsHelp(){
 const wrap=el('div'),keys=el('p','F — полный экран; H — скрыть панели; Escape — закрыть панель; WASD или стрелки — двигать карту, + и − — масштаб, 0 — вся ферма. Все действия доступны и через списки.','note hint-desktop'),touch=el('p','Масштабируй двумя пальцами, карту двигай одним. Все действия доступны и через списки.','note hint-touch');
 wrap.append(keys,touch);modal('Управление и подсказки',wrap);
}
function toggleImmersive(){const hidden=document.body.classList.toggle('immersive');if(hidden)closePanel();scene.resize();QW?.menu.refresh();}
let viewportFrame=0;
function scheduleSceneResize(){
 if(viewportFrame)cancelAnimationFrame(viewportFrame);
 viewportFrame=requestAnimationFrame(()=>{viewportFrame=0;scene.resize();});
}
function syncFullscreenState(){QW?.menu.refresh();}
async function toggleFullscreen(){
 try{
  if(!QW?.fullscreen.canToggle()){if(!document.body.classList.contains('immersive'))toggleImmersive();toast('Браузер не поддерживает полный экран. Скрыла лишние панели.');return;}
  const entering=!QW.fullscreen.active();
  await QW.fullscreen.toggle();
  if(entering)closePanel();
 }catch{toast('Полный экран недоступен в этом окне. Кнопка H скроет панели.',true);}
}

const scene=new FarmScene($('farm-canvas'),{click:clickObject,cancel:cancelPlacement,minimap:$('minimap'),frame:()=>{if(S.stoneSpeech&&!S.stoneSpeech.hidden)placeStoneSpeech()}});
updateFarmLighting();
$('lighting-toggle').onclick=()=>setLightingMode({auto:'day',day:'night',night:'auto'}[lightingMode]);
// Mouse wheel over the seed strip scrolls it sideways (only when it can move, so the page keeps its own wheel otherwise).
$('seedbar').addEventListener('wheel',e=>{const sb=$('seedbar'),d=wheelScrollDelta(e,sb.scrollLeft,sb.scrollWidth,sb.clientWidth);if(!d)return;e.preventDefault();sb.scrollLeft+=d;},{passive:false});
// A mouse drag pans the seed strip. Let a stationary click reach its button, but never select a seed after a drag.
const seedbar=$('seedbar');let seedDrag=null,ignoreSeedClick=false;
seedbar.addEventListener('pointerdown',e=>{if(e.pointerType!=='mouse'||e.button!==0||seedbar.scrollWidth<=seedbar.clientWidth)return;seedDrag={id:e.pointerId,x:e.clientX,scroll:seedbar.scrollLeft,moved:false};});
window.addEventListener('pointermove',e=>{if(!seedDrag||e.pointerId!==seedDrag.id)return;const dx=e.clientX-seedDrag.x;if(!seedDrag.moved&&Math.abs(dx)<6)return;seedDrag.moved=true;seedbar.classList.add('dragging');seedbar.scrollLeft=seedDrag.scroll-dx;e.preventDefault();});
function finishSeedDrag(e){if(!seedDrag||e.pointerId!==seedDrag.id)return;if(seedDrag.moved){ignoreSeedClick=true;setTimeout(()=>{ignoreSeedClick=false;},0);}seedDrag=null;seedbar.classList.remove('dragging');}
window.addEventListener('pointerup',finishSeedDrag);window.addEventListener('pointercancel',finishSeedDrag);
seedbar.addEventListener('click',e=>{if(!ignoreSeedClick)return;e.preventDefault();e.stopImmediatePropagation();ignoreSeedClick=false;},true);
// On a narrow Telegram window the bottom rail scrolls sideways with either the wheel or a horizontal trackpad gesture.
const rail=$('rail');
rail.addEventListener('wheel',e=>{const d=wheelScrollDelta(e,rail.scrollLeft,rail.scrollWidth,rail.clientWidth);if(!d)return;e.preventDefault();rail.scrollLeft+=d;},{passive:false});
// Mouse drag scrolls the compact bottom rail. A drag must not activate the button underneath it.
let railDrag=null,ignoreRailClick=false;
rail.addEventListener('pointerdown',e=>{if(e.pointerType!=='mouse'||e.button!==0||rail.scrollWidth<=rail.clientWidth)return;railDrag={id:e.pointerId,x:e.clientX,scroll:rail.scrollLeft,moved:false};});
window.addEventListener('pointermove',e=>{if(!railDrag||e.pointerId!==railDrag.id)return;const dx=e.clientX-railDrag.x;if(!railDrag.moved&&Math.abs(dx)<6)return;railDrag.moved=true;rail.classList.add('dragging');rail.scrollLeft=railDrag.scroll-dx;e.preventDefault();});
function finishRailDrag(e){if(!railDrag||e.pointerId!==railDrag.id)return;if(railDrag.moved){ignoreRailClick=true;setTimeout(()=>{ignoreRailClick=false;},0);}railDrag=null;rail.classList.remove('dragging');}
window.addEventListener('pointerup',finishRailDrag);window.addEventListener('pointercancel',finishRailDrag);
rail.addEventListener('click',e=>{if(!ignoreRailClick)return;e.preventDefault();e.stopImmediatePropagation();ignoreRailClick=false;},true);
$('zoom-in').onclick=()=>scene.zoom(1.2);$('zoom-out').onclick=()=>scene.zoom(1/1.2);$('center-map').onclick=()=>scene.fit(true);$('return-home').onclick=backHome;$('harvest-all').onclick=()=>command('collect_all');$('repeat-run').onclick=safe(async()=>{if(!own()||!S.me||!S.catalog)return;await runPlan(planRepeat(S.lastRun,S.seed,S.me,S.catalog,now()));});$('object-list-button').onclick=()=>selectTab('objects');$('find-button').onclick=()=>selectTab('objects');$('retry').onclick=safe(retryConnection);
// Mini-map: shown by default except on very small screens; the choice is remembered per browser.
function miniPref(){try{const v=localStorage.getItem('qw-farm.minimap');if(v==='on')return true;if(v==='off')return false;}catch{}return !matchMedia('(max-width:420px),(max-height:520px)').matches;}
function setMinimap(on,save=true){scene.mini.setVisible(on);$('minimap-toggle').setAttribute('aria-pressed',String(on));if(save)try{localStorage.setItem('qw-farm.minimap',on?'on':'off');}catch{}}
setMinimap(miniPref(),false);$('minimap-toggle').onclick=()=>setMinimap($('minimap-toggle').getAttribute('aria-pressed')!=='true');
async function retryConnection(){
 if(!S.me){S.config=await request(API+'/config');await enter();}
 else if(S.pending)await sendPending();else await refresh();
}
document.addEventListener('keydown',e=>{
 if(e.key==='Escape'){if(dashaGameOpen){e.preventDefault();closeDashaGame();return;}if(olegGameOpen){e.preventDefault();closeOlegGame();return;}if(!S.placing?.committing)cancelPlacement();closePanel();}
 if(['INPUT','SELECT','TEXTAREA'].includes(document.activeElement?.tagName)||e.ctrlKey||e.metaKey||e.altKey||$('dialog').open)return;
 if(e.key.toLowerCase()==='f'){e.preventDefault();toggleFullscreen();}
 if(e.key.toLowerCase()==='h'){e.preventDefault();toggleImmersive();}
});
$('fields-door').onclick=safe(async()=>{if(!own())await backHome();selectTab('fields');});
$('forest-door').onclick=safe(async()=>{if(!own())await backHome();selectTab('forest');});
const lakeDoor=button(null,safe(async()=>{if(!S.me)return;if(!own())backHome();selectTab('lake');}),'forest-door lake-door');
lakeDoor.id='lake-door';lakeDoor.hidden=true;lakeDoor.setAttribute('aria-label','Перейти к озеру и рыбалке');lakeDoor.setAttribute('aria-controls','panel');lakeDoor.append(lakeDoorArt());$('forest-door').after(lakeDoor);
// Village entrance on the map itself: a chip next to find/minimap, reusing selectTab('village').
const villageDoor=button(null,safe(async()=>{if(!S.me)return;if(!own())await backHome();selectTab('village');}),'map-chip village-door');
villageDoor.id='village-door';villageDoor.setAttribute('aria-label','Пойти в деревню');villageDoor.setAttribute('aria-controls','village-scene');
{const ico=document.createElementNS('http://www.w3.org/2000/svg','svg');ico.setAttribute('viewBox','0 0 24 24');ico.setAttribute('aria-hidden','true');ico.setAttribute('focusable','false');ico.innerHTML='<path d="M3 20V11l5-4 5 4v9M13 20v-7l4-3 4 3v7M2 20h20M7 20v-4h2v4"/>';villageDoor.append(ico,el('span','Деревня','village-door-label'));}
$('minimap-toggle').after(villageDoor);
// Desktop header cards in the same painted style as the forest and lake doors: "to the village" and, inside the village, "to the farm".
function headerCardArt(id,inner){
 const n=document.createElementNS('http://www.w3.org/2000/svg','svg');n.setAttribute('class','forest-door-art');n.setAttribute('viewBox','0 0 160 68');n.setAttribute('preserveAspectRatio','xMidYMid slice');n.setAttribute('aria-hidden','true');n.setAttribute('focusable','false');
 n.innerHTML=`<defs><clipPath id="${id}-clip"><rect width="160" height="68" rx="13"/></clipPath><linearGradient id="${id}-sky" x2="0" y2="1"><stop stop-color="#dcebd1"/><stop offset="1" stop-color="#f3eacb"/></linearGradient></defs><g clip-path="url(#${id}-clip)"><rect width="160" height="68" fill="url(#${id}-sky)"/>${inner}</g>`;
 return n;
}
const VILLAGE_CARD_ART='<circle cx="132" cy="14" r="8" fill="#f7d579" opacity=".8"/><path d="M0 44 36 28l34 16 38-18 52 20v22H0Z" fill="#a9c597"/><path d="M0 55c30-8 60-4 90-2s50 2 70-5v20H0Z" fill="#8fb27f"/><path d="M70 68c2-9 9-13 17-17s13-7 14-12" fill="none" stroke="#e8dcb4" stroke-width="7" stroke-linecap="round"/><path d="M13 57V43l16-10 16 10v14Z" fill="#efe5c8"/><path d="M10 44 29 30l19 14Z" fill="#c98b6a"/><rect x="25" y="48" width="7" height="9" rx="1" fill="#8b6a4a"/><rect x="16" y="46" width="5" height="5" rx="1" fill="#9fc1c4"/><rect x="36" y="46" width="5" height="5" rx="1" fill="#9fc1c4"/><path d="M100 56V44l14-9 14 9v12Z" fill="#f2e8cd"/><path d="M97 45l17-12 17 12Z" fill="#8fa78a"/><rect x="111" y="48" width="6" height="8" rx="1" fill="#8b6a4a"/><rect x="104" y="47" width="4" height="4" rx="1" fill="#9fc1c4"/><path d="M60 56 62 38h8l2 18Z" fill="#e6dbc0"/><path d="M59 39 66 30l7 9Z" fill="#b6926c"/><g stroke="#f6efd6" stroke-width="2" stroke-linecap="round"><path d="M66 38 56 30M66 38l9-8M66 38l-8 9M66 38l9 8"/></g><g fill="#7f9e69"><circle cx="50" cy="52" r="5"/><circle cx="143" cy="52" r="7"/></g><path d="M141 59v-6M50 58v-5" stroke="#9e8a60" stroke-width="2"/>';
const FARM_CARD_ART='<circle cx="30" cy="15" r="8" fill="#f7d579" opacity=".8"/><path d="M0 44c30-10 60-8 90-3s50 4 70-2v29H0Z" fill="#a9c597"/><path d="M0 56c40-9 80-6 120-2l40 4v10H0Z" fill="#8fb27f"/><g fill="none" stroke-width="3" stroke-linecap="round"><path d="M92 62c14-5 34-8 62-9" stroke="#d6bd78"/><path d="M88 57c16-5 36-8 66-9" stroke="#b9c27c"/><path d="M96 51c14-4 32-6 56-7" stroke="#d6bd78"/></g><path d="M22 60V40l20-10 20 10v20Z" fill="#b55a4d"/><path d="M19 41 42 28l23 13Z" fill="#7a4a3c"/><path d="M33 60V48h18v12Z" fill="#f2e6cf"/><path d="M33 48 51 60M51 48 33 60" stroke="#b55a4d" stroke-width="1.6"/><rect x="38" y="36" width="8" height="6" rx="1" fill="#f2e6cf"/><rect x="68" y="34" width="10" height="26" rx="4" fill="#e3dccb"/><path d="M67 36c0-6 12-6 12 0Z" fill="#c9bfa5"/><path d="M0 62h160" stroke="#9e8a60" stroke-width="1.4" opacity=".7"/><g stroke="#a89063" stroke-width="2"><path d="M86 66v-8M104 66v-8M122 66v-8M140 66v-8M84 61h60"/></g>';
function bindDestinationCarousel(nav, win=window){
 const canScroll=()=>nav.scrollWidth>nav.clientWidth+1;
 const onWheel=e=>{
  if(!canScroll()||e.ctrlKey)return;
  const unit=e.deltaMode===1?16:e.deltaMode===2?nav.clientWidth:1;
  const delta=(Math.abs(e.deltaX)>Math.abs(e.deltaY)?e.deltaX:e.deltaY)*unit;
  if(!delta)return;
  const max=nav.scrollWidth-nav.clientWidth,next=Math.max(0,Math.min(max,nav.scrollLeft+delta));
  if(next===nav.scrollLeft)return;
  nav.scrollLeft=next;e.preventDefault();
 };
 let drag=null,suppressClick=false,clearSuppression=null;
 const onClick=e=>{if(!suppressClick)return;suppressClick=false;if(clearSuppression)clearTimeout(clearSuppression);e.preventDefault();e.stopPropagation();};
 const onDown=e=>{if(e.pointerType!=='mouse'||e.button!==0||!canScroll())return;drag={id:e.pointerId,x:e.clientX,left:nav.scrollLeft,moved:false};};
 const onMove=e=>{
  if(!drag||e.pointerId!==drag.id)return;
  const dx=e.clientX-drag.x;
  if(!drag.moved&&Math.abs(dx)>5){drag.moved=true;nav.classList.add('dragging');}
  if(!drag.moved)return;
  nav.scrollLeft=Math.max(0,Math.min(nav.scrollWidth-nav.clientWidth,drag.left-dx));e.preventDefault();
 };
 const onEnd=e=>{
  if(!drag||e.pointerId!==drag.id)return;
  if(drag.moved){suppressClick=true;clearSuppression=setTimeout(()=>{suppressClick=false;clearSuppression=null;},0);}
  drag=null;nav.classList.remove('dragging');
 };
 nav.addEventListener('wheel',onWheel,{passive:false});
 nav.addEventListener('pointerdown',onDown);
 nav.addEventListener('click',onClick,true);
 win.addEventListener('pointermove',onMove);
 win.addEventListener('pointerup',onEnd);
 win.addEventListener('pointercancel',onEnd);
}
// Every destination card (forest, lake, village, farm, and any future one) goes through this one factory, so size, caption,
// order, carousel scrolling and the village-only mode are identical for all of them. `art` is the inner SVG of a 160x68 picture.
function addDestinationCard({id,label,art,run,hidden=false,only='',extraClass=''}){
 const b=button(null,run,`forest-door dest-card${only?` dest-only-${only}`:''}${extraClass?` ${extraClass}`:''}`);
 b.id=id;b.hidden=hidden;b.dataset.label=label;b.setAttribute('aria-label',label);
 b.append(headerCardArt(id,art),el('span',label,'sr-only'));
 $('fields-door').before(b);return b;
}
addDestinationCard({id:'village-card-door',label:'Деревня',art:VILLAGE_CARD_ART,hidden:true,extraClass:'village-card-door',run:safe(async()=>{if(!S.me)return;if(!own())await backHome();selectTab('village');})});
addDestinationCard({id:'farm-card-door',label:'Ферма',art:FARM_CARD_ART,only:'village',extraClass:'farm-card-door',run:returnToFarm});
for(const id of ['forest-door','lake-door']){const n=$(id);if(n){n.classList.add('dest-card');n.dataset.label=id==='forest-door'?'Лес':'Озеро'}}
// On a narrow window the cards form a carousel: the mouse wheel scrolls it sideways and a held mouse button drags it (touch already pans natively).
{const nav=document.querySelector('.header-destinations');
 if(nav)bindDestinationCarousel(nav);
}

// --- Shared shell (window.QW from /app/shell/qw-shell.js): Telegram bridge, ⚙ menu and the back stack ---
function navPush(id,onBack){try{QW?.nav.push({id,onBack});}catch{}}
function navPop(id){try{QW?.nav.pop(id);}catch{}}
// Back stack (UI_RULES NAV-6): village / neighbor's farm below the open panel, a modal <dialog> above everything.
// The mini-games push their own 'minigame' entry (see launchField/launchTripGame) and veto Back until the player confirms.
// history.go(-n) from QW.nav.pop is asynchronous: a pushState issued in the same tick lands BEFORE the traversal and the
// stack drifts one entry (the next Back then leaves the farm for /app). So after a pop that removed history entries, wait
// for the (shell-suppressed) popstate before pushing the replacement entry.
let navSettling=false;
function navSettle(){navSettling=true;let tm=0;const fin=()=>{removeEventListener('popstate',fin);clearTimeout(tm);if(!navSettling)return;navSettling=false;syncNav();};addEventListener('popstate',fin);tm=setTimeout(fin,600);}
function syncNav(){
 if(!QW||navSettling)return;
 const village=!!S.me&&(villageVisible()||!own()),panel=!!S.me&&document.body.classList.contains('panel-open'),hist=!!(QW.config.history??QW.config.mode==='game');
 if(village&&!QW.nav.has('village')){const hadPanel=QW.nav.has('panel');navPop('panel');if(hadPanel&&hist){navSettle();return;}navPush('village',returnToFarm);}
 else if(!village&&QW.nav.has('village')){navPop('village');if(panel&&hist){navSettle();return;}}
 if(panel&&!QW.nav.has('panel'))navPush('panel',()=>{closePanel();});
 else if(!panel&&QW.nav.has('panel'))navPop('panel');
}
new MutationObserver(syncNav).observe(document.body,{attributes:true,attributeFilter:['class']});
new MutationObserver(()=>{if($('dialog').open)navPush('dialog',()=>{$('dialog').close();});else navPop('dialog');}).observe($('dialog'),{attributes:true,attributeFilter:['open']});
const LIGHT_LABELS={auto:'По времени',day:'День',night:'Ночь'};
QW?.boot({mode:'game',gameId:'farm',title:'Весёлый фермер',home:'/app',
 onResize:()=>{syncFullscreenState();scheduleSceneResize();},
 onResume:()=>{if(S.me)poll();},
 onFullscreenFailed:()=>toast('Telegram не поддерживает полный экран в этом клиенте.',true)});
QW?.header.mountGear($('header-actions'));
QW?.menu.register([
 {id:'farm-settings',icon:'sliders',label:'Настройки фермы',hint:'название, кто видит, соседи',hidden:()=>!S.me,disabled:()=>!!S.fieldGame,onSelect:()=>{if(!own())backHome();selectTab('settings');}},
 {id:'farm-light',icon:'sun',label:'Свет на ферме',value:()=>LIGHT_LABELS[lightingMode],onSelect:()=>setLightingMode({auto:'day',day:'night',night:'auto'}[lightingMode])},
 {id:'farm-immersive',icon:'layers',label:'Только ферма и счётчики · H',hidden:()=>!S.me,disabled:()=>!!S.fieldGame,toggle:()=>document.body.classList.contains('immersive'),onSelect:toggleImmersive},
 {id:'farm-help',icon:'help',label:'Управление и подсказки',onSelect:showControlsHelp},
 ...FEST.menuItems(()=>S.me?.festival,()=>{if(S.me)renderPanel();})
],'Весёлый фермер');
document.addEventListener('fullscreenchange',()=>{syncFullscreenState();scheduleSceneResize();});
let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(S.me)renderRail();scene.resize();},100);});
try{if(localStorage.getItem('qw-farm.reduced-motion')==='true')scene.motion=false;}catch{}
const RENEW_AFTER=8*60*1000;let sessionRenewing=null;
async function renewPlatformSession(){
 if(!S.me||S.config?.demo||!['telegram','guest'].includes(mode))return true;
 if(sessionRenewing)return sessionRenewing;
 const identity=S.me.id;
 sessionRenewing=(async()=>{
  try{await requestRaw(mode==='telegram'?'/api/mini/session/renew':'/api/guest/resume',{method:'POST'});lastSessionRenewal=Date.now();return true;}
  catch(e){
   if(e.status===401){if(await recoverFarmSession(true))return true;if(S.me?.id===identity)showLogin(SESSION_ENDED);return false;}
   connection('Не удалось продлить сессию. Проверяем связь…',true);return false;
  }
 })();
 try{return await sessionRenewing;}finally{sessionRenewing=null;}
}
let polling=false;
async function poll(){if(document.hidden||!S.me||S.busy||polling)return;polling=true;try{const identity=S.me.id;if(Date.now()-lastSessionRenewal>=RENEW_AFTER)await renewPlatformSession();if(S.me?.id!==identity||!await refresh({render:false})||S.me?.id!==identity)return;if(S.tab==='neighbors'&&own())await updateNeighbors();else if(panelRenderSignature!==panelSnapshot()&&!['settings','neighbors','build'].includes(S.tab)&&!$('dialog').open&&!['INPUT','SELECT','TEXTAREA'].includes(document.activeElement?.tagName)&&!S.placing&&!S.fieldGame)renderPanel();}catch(e){if(e.sessionEnded)return;connection(e.rateBucket?'Можно повторить обновление':'Нет связи с сервером',true);if(e.rateBucket)scheduleRateRecovery();}finally{polling=false;}}
let readyTimer=null,pollTimer=null;
function syncUITimers(){
 clearInterval(readyTimer);clearInterval(pollTimer);clearInterval(lightingTimer);readyTimer=pollTimer=lightingTimer=null;
 updateFarmLighting();
 if(document.hidden)return;
 lightingTimer=setInterval(updateFarmLighting,60000);
 updateReady();poll();readyTimer=setInterval(updateReady,1000);pollTimer=setInterval(poll,15000);
}
syncUITimers();document.addEventListener('visibilitychange',syncUITimers);window.addEventListener('focus',()=>{if(!document.hidden){updateReady();poll();}});
// A valid cookie opens Farm independently of the optional external Telegram SDK.
try{S.config=await request(API+'/config');await enter();}catch(e){S.config={demo:false};showLogin(e.message);}

// --- r8: residents' reputation, the caravan and daily contracts (all state is server-authoritative) ---
function repInfo(npc){const m=S.catalog.market,pts=S.me.market?.rep?.[npc]||0;let lv=0;m.rep_points.forEach((n,i)=>{if(pts>=n)lv=i;});return {pts,lv,name:m.rep_names[lv],bonus:lv*m.rep_bonus,from:m.rep_points[lv],next:m.rep_points[lv+1]??null};}
function repBar(npc){const r=repInfo(npc),w=el('div',null,'rep-bar'),top=el('div',null,'rep-line');top.append(el('span',r.name,'rep-name'),el('small',r.next===null?`максимум · +${r.bonus}% к наградам`:`${r.pts - r.from} / ${r.next - r.from}${r.bonus?` · +${r.bonus}% к наградам`:''}`));w.append(top,meter(r.next===null?1:r.pts-r.from,r.next===null?1:r.next-r.from));w.title=`${npc}: ${r.name}`;return w;}
function mskMidnight(t){return (Math.floor((t+10800)/86400)+1)*86400-10800;}
function marketCards(p){
 const m=S.me.market;if(!m||!own())return;
 p.append(caravanCard(m),contractsCard(m));
}
// The last caravan's outcome, kept until the next one: a small success strip (coins and XP with the same icons as the card footer)
// or a muted refund strip. Icons are decorative; the words carry the meaning for screen readers.
function caravanResult(lc){
 const box=el('div',null,`caravan-result ${lc.ok?'is-ok':'is-refund'}`),head=el('div',null,'cr-head'),row=el('div',null,'cr-gains');
 head.append(el('strong',lc.ok?'Обоз собран':'Обоз уехал'),el('small',lc.ok?(lc.npc?`${lc.npc} благодарит`:'Спасибо за товар'):(lc.refund>0?'Возврат по цене лавки':'Ничего не погружено, ничего не потеряно')));
 const gain=(id,text,label,cls)=>{const g=el('span',null,`cr-gain ${cls}`);g.append(icon(id),el('b',text),el('span',label,'sr-only'));return g;};
 if(lc.ok)row.append(gain('coin',`+${fmt(lc.coins)}`,' монет','cr-coins'),gain('star',`+${fmt(lc.xp)} XP`,'','cr-xp'));
 else if(lc.refund>0)row.append(gain('coin',`+${fmt(lc.refund)}`,' монет возврата','cr-coins'));
 box.append(head);if(row.childElementCount)box.append(row);return box;
}
function caravanCard(m){
 const cfg=S.catalog.market.caravan,car=m.caravan,c=card('Обоз','Большой заказ · ящик за ящиком','shop');c.classList.add('caravan');
 if(!car){
  if(S.me.level<cfg.level)note(`Обоз заедет на ферму с ${cfg.level} уровня: он просит 3–6 ящиков хороших товаров и щедро платит.`,c);
  else{const lc=m.last_caravan;if(lc)c.append(caravanResult(lc));const row=el('p',null,'note');row.append('Следующий обоз приедет через ',timer(Math.max(m.caravan_next_at,now())),'.');c.append(row);}
  return c;
 }
 const r=repInfo(car.npc),coins=Math.floor(car.coins*(100+r.bonus)/100),xp=Math.floor(car.xp*(100+r.bonus)/100),done=car.crates.filter(x=>x.done).length;
 const head=el('div',null,'caravan-head');head.append(icon(AVATARS[car.npc]||'shop'),el('span',`${car.npc} ждёт ${car.crates.length} ящиков`));const left=el('small');left.append('Осталось: ',timer(car.deadline));head.append(left);c.append(head,meter(done,car.crates.length));
 car.crates.forEach((x,i)=>{const row=el('div',null,`crate${x.done?' done':''}`);row.append(icon(x.item),el('span',`${itemName(x.item)} ×${x.qty}`),el('small',x.done?'погружен':`на складе ${stock(x.item)}`));row.append(x.done?el('span','✓','crate-mark'):button('Погрузить',()=>command('caravan_fill',{crate:i}),'primary small',stock(x.item)<x.qty));c.append(row);});
 const f=el('div',null,'card-footer'),rw=el('span',`+${coins} `,'reward');rw.append(el('small',`+${xp} XP${car.decor?' · подарок: декор':''}`));f.append(rw,el('small',`${done} / ${car.crates.length}`));c.append(f);
 note('Ящики можно возить по одному. Не успеешь — привезённое вернётся деньгами по цене лавки.',c);return c;
}
function contractText(k){const n=k.item?itemName(k.item):'';return k.kind==='harvest'?`Собрать: ${n} ×${k.goal}`:k.kind==='craft'?`Приготовить: ${n} ×${k.goal}`:`Доставить заказов: ${k.goal}`;}
function contractProgress(k){const key=k.kind==='orders'?'orders':(k.kind==='harvest'?'h:':'p:')+k.item;return Math.max(0,(S.me.market.counts[key]||0)-k.base);}
function contractsCard(m){
 const c=card('Ежедневные контракты',null,'orders');c.classList.add('contracts');
 const items=m.contracts.items,cfg=S.catalog.market.contracts;
 if(S.me.level<cfg.level){note(`Контракты появятся со ${cfg.level} уровня.`,c);return c;}
 const sub=el('p',null,'note');sub.append('Обновятся через ',timer(mskMidnight(now())),' (по Москве).');c.append(sub);
 const day=m.contracts.day,s=m.streak,streak=(s.last_day===day||s.last_day===day-1)?Math.min(cfg.streak_max,s.count)*cfg.streak_step:0;
 for(const k of items){const got=Math.min(contractProgress(k),k.goal),row=el('div',null,`contract${k.claimed?' done':''}`),txt=el('div',null,'contract-copy');txt.append(el('strong',contractText(k)),el('small',k.claimed?'награда получена':`${fmt(got)} / ${fmt(k.goal)} · +${Math.floor(k.coins*(100+streak)/100)} монет, +${Math.floor(k.xp*(100+streak)/100)} XP`));txt.append(meter(got,k.goal));row.append(txt,button(k.claimed?'Готово':'Забрать',()=>command('contract_claim',{contract:k.id}),k.claimed||got<k.goal?'secondary small':'primary small',k.claimed||got<k.goal));c.append(row);}
 c.append(el('small',s.count?`Серия: ${s.count} дн. подряд${streak?` · +${streak}% к наградам`:''}`:'Выполни все три контракта — начнётся серия с небольшим бонусом.','streak'));
 return c;
}
function residentsCard(p){
 p.append(el('h3','Жители','subheading'));
 const box=el('section',null,'card residents');
 for(const [npc] of Object.entries(S.catalog.market.tastes)){const r=repInfo(npc),row=el('div',null,'resident');row.append(icon(AVATARS[npc]||'owl'));const t=el('div');t.append(el('strong',npc),repBar(npc));if(r.lv>=S.catalog.market.special_level)t.append(el('small','Может попросить любимое лакомство','resident-note'));row.append(t);box.append(row);}
 p.append(box);note(`Каждый доставленный заказ повышает доверие жителя: +${S.catalog.market.rep_bonus}% к наградам за уровень. С уровня «${S.catalog.market.rep_names[S.catalog.market.special_level]}» жители присылают особые просьбы.`,p);
}

/* ---- r9 stage 14: upkeep, village fund and decor shop. Numbers come from S.catalog.economy and S.me.economy_status. ---- */
function ECON(){return S.catalog.economy;}
function eco(){return S.me?.economy_status;}
function earned(){return Math.max(0,S.me.coins-S.me.starter_credit);}
function dayWord(n){const m=n%10,h=n%100;return h>=11&&h<=14?'дней':m===1?'день':m>=2&&m<=4?'дня':'дней';}
function hudDebt(){const d=el('div',null,'hud-token hud-debt');d.append(icon('coin'),el('span',`Долг ${fmt(eco().debt)}`));d.title='Долг по содержанию: пока он не погашен, новые таймеры идут на 20% дольше. Нажми, чтобы оплатить.';d.setAttribute('role','button');d.tabIndex=0;d.onclick=()=>openVillageTownHall('Содержание фермы');d.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openVillageTownHall('Содержание фермы');}};return d;}
function upkeepCard(p,e){
 const c=card('Содержание фермы','СЧЁТ РАЗ В АКТИВНЫЕ МОСКОВСКИЕ СУТКИ','coin');
 if(!e.active){note(`Содержание начнётся с ${ECON().upkeep_level} уровня. До этого ферма живёт без счетов.`,c);p.append(c);return;}
 const beds=S.me.objects.filter(o=>o.type==='plot').length,rate=ECON().plot_upkeep[S.me.size]||0;
 c.append(el('p',`Счёт за сутки: ${fmt(e.upkeep)} мон.${e.discount?' (скидка фонда −25% уже учтена)':''}`,'upkeep-total'));
 note(`Грядки: ${beds} × ${rate} мон. и 1% цены каждой постройки за каждый её уровень. Декор ничего не стоит.`,c);
 note(e.billed_today?'Сегодняшний счёт уже учтён.':'Счёт спишется после первого действия в новые сутки по Москве. Если игры не было, суммы не копятся.',c);
 if(e.debt>0){
  const w=el('div',null,'callout debt-note');w.append(el('strong',`Долг: ${fmt(e.debt)} мон.`),el('span','Не хватило заработанных монет. Пока долг не погашен, новые таймеры идут на 20% дольше. Запасы и постройки никуда не деваются.'));c.append(w);
  c.append(button(`Оплатить ${fmt(Math.min(e.debt,earned()))} мон.`,()=>command('pay_upkeep'),'primary wide',earned()<=0));
 }else note('Долгов нет.',c);
 p.append(c);
}
function fundGoodsDialog(){
 const e=ECON(),w=el('div',null,'fund-goods'),inputs={};
 const ids=Object.keys(S.me.inventory).filter(k=>S.me.inventory[k]>0&&S.catalog.items[k]&&!MERCH.isBound(S.catalog,k)).sort((a,b)=>itemName(a).localeCompare(itemName(b),'ru'));
 if(!ids.length)w.append(el('p','На складе пусто.'));
 for(const id of ids){const [fw,fi]=field(`${itemName(id)}: есть ${S.me.inventory[id]}, ≈${fmt(Math.floor(S.catalog.items[id].price*e.markup/100))} мон. за штуку`,'number',0);fi.min=0;fi.max=S.me.inventory[id];inputs[id]=fi;w.append(fw);}
 modal('Товары в фонд деревни',w,[button('Внести',safe(async()=>{const items={};for(const [id,i] of Object.entries(inputs)){const q=Math.floor(Number(i.value));if(q>0)items[id]=Math.min(q,stock(id));}if(!Object.keys(items).length){toast('Выбери хотя бы один товар.',true);return;}if(await command('fund_contribute',{coins:0,items}))$('dialog').close();}),'primary',!ids.length)]);
}
function fundCard(p,e){
 const eC=ECON(),left=Math.max(0,Math.ceil((e.season_ends_at-now())/86400));
 const c=card('Фонд деревни',`СЕЗОН: ЕЩЁ ${left} ${dayWord(left)}`,'friends');
 if(!e.fund_open){note(`Фонд откроется с ${eC.fund_level} уровня: вклады копят личные награды и помогают всей деревне.`,c);p.append(c);return;}
 if(e.feast_until>now()){const f=el('div',null,'callout feast-note'),left=timer(e.feast_until);left.dataset.untilPrefix=`+${eC.feast[1]}% опыта ещё `;updateTime(left);f.append(el('strong','«Праздник»'),left);c.append(f);}
 c.append(el('h3','Твоя шкала','subheading'),meter(e.personal,e.thresholds[e.thresholds.length-1]));
 c.append(el('p',`Внесено за сезон: ${fmt(e.personal)} из ${fmt(e.thresholds[e.thresholds.length-1])} мон.`,'note'));
 e.thresholds.forEach((th,i)=>{const done=e.tiers>i,row=el('div',null,`fund-tier${done?' done':''}`);row.append(el('span',done?'✓':String(i+1),'fund-mark'),el('span',eC.tier_text[i+1]),el('small',`${fmt(th)} мон.`));c.append(row);});
 if(e.titles.length)note(`Титул: ${e.titles.join(', ')}`,c);
 const v=S.village;
 c.append(el('h3','Вся деревня','subheading'));
 if(v){c.append(meter(v.total,v.goal),el('p',`Деревня собрала ${fmt(v.total)} из ${fmt(v.goal)} мон.`,'note'));}
 note(`Когда цель достигнута, все, кто внёс хотя бы ${fmt(e.min_share)} мон., получают знамя деревни и общий «Праздник». Награда приходит при следующем заходе.`,c);
 if(e.common)note('Общая награда этого сезона уже у тебя.',c);
 else if(e.personal<e.min_share)note(`Внеси ещё ${fmt(e.min_share-e.personal)} мон., чтобы попасть в число награждённых.`,c);
 else if(v&&v.total>=v.goal)note('Цель достигнута: награда придёт при следующем обновлении фермы.',c);
 const [cw,ci]=field('Монеты в фонд','number',Math.max(1,Math.min(earned(),Math.floor(e.ref/10))));ci.min=1;ci.max=Math.max(1,earned());
 c.append(cw,button('Внести монеты',safe(async()=>{const n=Math.floor(Number(ci.value));if(!Number.isInteger(n)||n<1){toast('Укажи, сколько монет внести.',true);return;}await command('fund_contribute',{coins:n,items:{}});}),'primary wide',earned()<1),
  button('Внести товары…',fundGoodsDialog,'secondary wide',!Object.values(S.me.inventory).some(q=>q>0)));
 note(`Монеты идут 1:1, товары по цене ×${(eC.markup/100).toFixed(2).replace('.',',')}. Стартовый подарок в фонд не уходит.`,c);
 p.append(c);
}
function decorShop(p,e){
 const eC=ECON();
 p.append(el('h3','Украшения','subheading'));
 note('Только красота: у декора нет содержания. Новые ступени открываются с ростом уровня.',p);
 for(let t=1;t<=5;t++){
  const lv=eC.decor_tiers[t][0],items=eC.decor_shop.filter(d=>d.tier===t);
  p.append(el('h4',`Ступень ${t} · с ${lv} уровня${t===5?' · трофеи':''}`,'tier-title'));
  for(const d of items){const b=S.catalog.buildings[d.id],c=card(b.name,`${b.w} × ${b.h} клеток · ${fmt(b.cost)} монет`,'home');if(lv>S.me.level)note(`Откроется на уровне ${lv}`,c);c.append(button('Разместить',()=>beginPlacement(b),'secondary wide',lv>S.me.level||b.cost>S.me.coins));p.append(c);}
 }
 p.append(el('h3','Награды фонда','subheading'));
 for(const r of eC.reward_decor){const b=S.catalog.buildings[r.id],has=e.unlocked.includes(r.id),c=card(b.name,has?'Открыто: размещается бесплатно':'Ещё не получено','discovery');note(r.source,c);if(has)c.append(button('Разместить',()=>beginPlacement(b),'secondary wide'));p.append(c);}
}
// Living village uses existing personal orders and the shared seasonal fund only.
// The two new errands are separate from the three legacy order slots.
function villagePresenceStop(){
 const session=villageSession;villageSession=null;villageEnterPending=null;villageTalkPending=false;if(villagePulseTimer)clearInterval(villagePulseTimer);villagePulseTimer=null;
 if(session)request(API+'/village/presence',{method:'POST',data:{action:'leave',session}}).catch(()=>{});
}
async function villagePresencePulse(action='pulse'){
 const session=villageSession;if(!session||S.tab!=='village'||document.hidden||action==='pulse'&&villageTalkPending)return;
 try{const r=await request(API+'/village/presence',{method:'POST',data:{action,session}});if(session!==villageSession)return;
  if(r.stolen){const fox=$('village-scene')?.querySelector('[data-village-npc="Лиса Даша"]');if(fox){const world=fox.closest('.village-world');fox.style.setProperty('--steal-x',`${(villagePos[0]-VILLAGE_SPOTS['Лиса Даша'][0])*(world?.offsetWidth||1600)/100}px`);fox.style.setProperty('--steal-y',`${(villagePos[1]-VILLAGE_SPOTS['Лиса Даша'][1])*(world?.offsetHeight||1200)/100}px`);fox.classList.add('is-stealing');setTimeout(()=>fox.classList.remove('is-stealing'),1800);}toast(r.notice);await refresh({render:false});}
  return true;
 }catch(e){if(e.sessionEnded)return;return false;}
}
// Dasha's theft is possible only for the owner, with coins in the pocket and no cooldown; talking to her cancels it, so the warning belongs to village entry.
function villageTheftPossible(){const e=S.me?.village_errands;return !!(own()&&e&&(Number(S.me.coins)||0)>0&&now()>=(Number(e.theft_next_at)||0));}
function villagePresenceStart(){
 if(!S.me||document.hidden||villageSession||typeof crypto==='undefined')return;
 villageSession=crypto.randomUUID();villageEnterPending=villagePresencePulse('enter');
 if(villageTheftPossible())toast('Лиса Даша может стащить пару монет. Подойди к ней и поздоровайся — тогда не тронет.');
 villagePulseTimer=setInterval(()=>villagePresencePulse(),10000);
 if(!villagePresenceBound){villagePresenceBound=true;document.addEventListener('visibilitychange',()=>{if(document.hidden)villagePresenceStop();else if(S.tab==='village')villagePresenceStart();});}
}
function villagePresenceTalk(){if(!villageSession||villageTalkPending)return;const session=villageSession;villageTalkPending=true;Promise.resolve(villageEnterPending).then(()=>villagePresencePulse('talk')).then(ok=>{if(ok===false&&session===villageSession)villageTalkPending=false;},()=>{if(session===villageSession)villageTalkPending=false;});}
function villageQuest(npc){return S.catalog?.market?.village_quests?.[npc]||null;}
function villageQuestPhase(npc){return S.me?.village_errands?.quests?.[npc]||'available';}
function villageNames(){return [...Object.keys(S.catalog.market.tastes),...Object.keys(S.catalog.market.village_quests||{})];}
async function villageQuestAction(npc,action){return command('village_quest',{npc,action});}
function villageStage(){const v=S.village;if(!eco()?.fund_open||!v)return null;const ratio=Math.max(0,v.total/Math.max(1,v.goal));return ratio>=1?3:ratio>=.6?2:ratio>=.25?1:0;}
function villageReady(o){return !!o.needs&&!!enough(o.needs);}
function villageOrders(npc){return (S.me?.orders||[]).filter(o=>o.npc===npc);}
async function deliverVillageOrder(id){const o=villageOrders(villageResident).find(o=>o.id===id);if(!o||!enough(o.needs)||S.busy)return false;return command('order',{order:o.id});}
function chooseVillageResident(npc){if(!villageNames().includes(npc))return;if(npc==='Лиса Даша')villagePresenceTalk();villageResident=npc;villageSheet='resident';syncVillageScene();showPanel();renderPanel();$('panel-content').querySelector('[data-village-focus=resident]')?.focus({preventScroll:true});}
// Camera: native scrolling of the scene container, smooth only on request and never under reduced motion.
function villageCenter(pct,smooth){const r=$('village-scene');if(!r||!r.scrollWidth)return;const o={left:Math.max(0,pct[0]/100*r.scrollWidth-r.clientWidth/2),top:Math.max(0,pct[1]/100*r.scrollHeight-r.clientHeight/2),behavior:smooth&&!villageReduced()?'smooth':'auto'};if(r.scrollTo)r.scrollTo(o);else{r.scrollLeft=o.left;r.scrollTop=o.top;}}
function villageFrame(){const r=$('village-scene');if(!villageMini?.frame||!r||!r.scrollWidth)return;const f=villageMini.frame;f.style.left=`${(r.scrollLeft/r.scrollWidth*100).toFixed(2)}%`;f.style.top=`${(r.scrollTop/r.scrollHeight*100).toFixed(2)}%`;f.style.width=`${Math.min(100,r.clientWidth/r.scrollWidth*100).toFixed(2)}%`;f.style.height=`${Math.min(100,r.clientHeight/r.scrollHeight*100).toFixed(2)}%`;}
// Walk graph helpers (pure, world units 2400x1800). Snap a point to the nearest point of any edge (README algorithm).
function villageSnap(W,x,y){let best=null;const n=W.n,e=W.e;for(let k=0;k<e.length;k+=2){const ax=n[2*e[k]],ay=n[2*e[k]+1],bx=n[2*e[k+1]],by=n[2*e[k+1]+1],dx=bx-ax,dy=by-ay,t=Math.max(0,Math.min(1,((x-ax)*dx+(y-ay)*dy)/(dx*dx+dy*dy||1))),qx=ax+t*dx,qy=ay+t*dy,d=Math.hypot(x-qx,y-qy);if(!best||d<best.d)best={k:k/2,a:e[k],b:e[k+1],t,x:qx,y:qy,d};}return best;}
// A* over graph nodes plus temporary start/end nodes on their edges; returns the polyline [[x,y],...] (first = snapped start, last = snapped goal). `to` may be {node:i} for an approach node.
function villagePlan(W,from,to){
 const N=W.n.length/2,P=i=>i===N?[S.x,S.y]:i===N+1?[T.x,T.y]:[W.n[2*i],W.n[2*i+1]],at=(p,k)=>p.node!==undefined?{x:W.n[2*p.node],y:W.n[2*p.node+1],a:p.node,b:p.node,k}:villageSnap(W,p[0],p[1]);
 if(!W._adj){W._adj=Array.from({length:N},()=>[]);for(let k=0;k<W.e.length;k+=2){const a=W.e[k],b=W.e[k+1],l=Math.hypot(W.n[2*a]-W.n[2*b],W.n[2*a+1]-W.n[2*b+1]);W._adj[a].push([b,l]);W._adj[b].push([a,l]);}}
 const S=at(from,-1),T=at(to,-2),extra=new Map(),link=(i,j)=>{const p=P(i),q=P(j),l=Math.hypot(p[0]-q[0],p[1]-q[1]);for(const [u,v] of [[i,j],[j,i]]){if(!extra.has(u))extra.set(u,[]);extra.get(u).push([v,l]);}};
 for(const a of new Set([S.a,S.b]))link(N,a);for(const a of new Set([T.a,T.b]))link(N+1,a);
 if(S.k===T.k)link(N,N+1);
 const nb=i=>i>=N?extra.get(i)||[]:W._adj[i].concat(extra.get(i)||[]),g=new Map([[N,0]]),prev=new Map(),open=[N],done=new Set(),h=i=>{const p=P(i);return Math.hypot(p[0]-T.x,p[1]-T.y);},f=new Map([[N,h(N)]]);
 while(open.length){let bi=0;for(let i=1;i<open.length;i++)if(f.get(open[i])<f.get(open[bi]))bi=i;const u=open.splice(bi,1)[0];if(u===N+1)break;if(done.has(u))continue;done.add(u);for(const [v,l] of nb(u)){if(done.has(v))continue;const c=g.get(u)+l;if(!g.has(v)||c<g.get(v)){g.set(v,c);prev.set(v,u);f.set(v,c+h(v));if(!open.includes(v))open.push(v);}}}
 if(!prev.has(N+1))return [[S.x,S.y]];
 const pts=[];for(let i=N+1;i!==undefined;i=prev.get(i))pts.unshift(P(i));
 return pts.filter((p,i)=>!i||p[0]!==pts[i-1][0]||p[1]!==pts[i-1][1]);
}
// Walk: constant speed along the planned polyline, one requestAnimationFrame chain (cancelled on re-plan and on leaving the village).
function villageWalkStop(){villageWalkToken++;if(villageWalkRaf&&typeof cancelAnimationFrame==='function')cancelAnimationFrame(villageWalkRaf);villageWalkRaf=0;villageWalkPlayer?.classList?.remove('is-walking');villageWalkPlayer=null;}
function villageWalk(target,done,instant=false,key){
 const world=$('village-scene')?.children?.[0],player=world?.querySelector?.('.village-player');
 villageWalkStop();
 if(!world||!player){villagePos=[...target];done?.();return;}
 const W=VILLAGE_WALK,token=villageWalkToken,node=W.a[key],pts=villagePlan(W,[villagePos[0]*24,villagePos[1]*18],node!==undefined?{node}:[target[0]*24,target[1]*18]);
 const put=(x,y)=>{villagePos=[x/24,y/18];for(const n of [player,villageMini?.player]){if(!n)continue;n.style.transitionDuration='0s';n.style.left=`${villagePos[0]}%`;n.style.top=`${villagePos[1]}%`;}};
 const last=pts[pts.length-1],cum=[0];for(let i=1;i<pts.length;i++)cum.push(cum[i-1]+Math.hypot(pts[i][0]-pts[i-1][0],pts[i][1]-pts[i-1][1]));
 const len=cum[cum.length-1];
 if(instant||villageReduced()||len<1||typeof requestAnimationFrame!=='function'){put(last[0],last[1]);villageCenter(villagePos,false);done?.();return;}
 const speed=Math.max(VILLAGE_SPEED,len/VILLAGE_MAX_WALK);let seg=1,t0=null;
 villageWalkPlayer=player;player.classList.add('is-walking');put(pts[0][0],pts[0][1]);
 const face=i=>{const dx=pts[i][0]-pts[i-1][0];if(Math.abs(dx)>.5)player.dataset.face=dx<0?'left':'right';};face(1);
 const frame=ts=>{
  if(token!==villageWalkToken)return;villageWalkRaf=0;
  if(t0===null)t0=ts;const d=Math.min(len,(ts-t0)/1000*speed);
  while(seg<pts.length-1&&cum[seg]<d){seg++;face(seg);}
  const a=pts[seg-1],b=pts[seg],l=cum[seg]-cum[seg-1]||1,k=Math.min(1,Math.max(0,(d-cum[seg-1])/l));put(a[0]+(b[0]-a[0])*k,a[1]+(b[1]-a[1])*k);villageCenter(villagePos,false);
  if(d>=len){player.classList.remove('is-walking');villageWalkPlayer=null;done?.();return;}
  villageWalkRaf=requestAnimationFrame(frame);
 };
 villageWalkRaf=requestAnimationFrame(frame);
}
// Mouse click walks there first; keyboard / scripted click (detail 0) jumps and opens at once. The button's data attribute names its graph approach point.
function villageGo(target,open,e){const d=e?.currentTarget?.dataset||{},key=d.villageNpc||(d.villageMerchant?'merchant':d.villagePlace?'place:'+d.villagePlace:d.villageSpot!==undefined?'visitor:'+d.villageSpot:d.villageGate?'gate':d.villageTownhall?'hall':undefined);if(!e||!e.detail){villageWalk(target,open,true,key);return;}villageWalk(target,open,false,key);}
function villageBindWorld(root){
 if(!root.addEventListener||root.dataset.villageBound)return;root.dataset.villageBound='1';let drag=null;
 root.addEventListener('pointerdown',e=>{villageDragged=false;if(e.pointerType!=='mouse'||e.button!==0)return;drag={x:e.clientX,y:e.clientY,l:root.scrollLeft,t:root.scrollTop};});
 root.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(!villageDragged&&Math.hypot(dx,dy)<6)return;villageDragged=true;root.classList.add('is-dragging');root.scrollLeft=drag.l-dx;root.scrollTop=drag.t-dy;});
 const end=()=>{drag=null;root.classList.remove('is-dragging');};
 for(const t of ['pointerup','pointercancel','pointerleave'])root.addEventListener(t,end);
 root.addEventListener('click',e=>{if(villageDragged){e.stopPropagation();e.preventDefault();villageDragged=false;}},true);
 root.addEventListener('scroll',villageFrame,{passive:true});
 const keys={ArrowUp:[0,-1],w:[0,-1],ц:[0,-1],ArrowDown:[0,1],s:[0,1],ы:[0,1],ArrowLeft:[-1,0],a:[-1,0],ф:[-1,0],ArrowRight:[1,0],d:[1,0],в:[1,0]};
 root.addEventListener('keydown',e=>{if(e.ctrlKey||e.metaKey||e.altKey||e.target?.closest?.('input,textarea,select'))return;const d=keys[e.key]||keys[String(e.key).toLowerCase()];if(!d)return;e.preventDefault();root.scrollBy({left:d[0]*260,top:d[1]*260,behavior:villageReduced()?'auto':'smooth'});});
}
// Performance: the art is a static image; every moving thing is a small element animated with transform/opacity only. Elements outside the viewport (and everything while the tab is hidden) are paused by observers, never by a frame loop.
function villageObserve(world){if(typeof IntersectionObserver!=='function'||!world.querySelectorAll)return;const root=$('village-scene');if(!villageIO)villageIO=new IntersectionObserver(list=>{for(const e of list)e.target.classList.toggle('is-off',!e.isIntersecting);},{root,rootMargin:'160px'});villageIO.disconnect();world.querySelectorAll('.va').forEach(n=>villageIO.observe(n));}
function villageAt(n,x,y){n.style.left=`${(x/24).toFixed(2)}%`;n.style.top=`${(y/18).toFixed(2)}%`;return n;}
function villageFx(){
 const fx=el('div',null,'village-fx');fx.setAttribute('aria-hidden','true');
 VILLAGE_SMOKE.forEach(([x,y],i)=>{const s=villageAt(el('i',null,'vfx-smoke va'),x,y);villageVars(s,{'--d':`${(i*1.7)%5.5}s`});fx.append(s);});
 const sails=villageAt(el('i',null,'vfx-sails va'),1377,396);for(let i=0;i<4;i++)sails.append(el('b'));fx.append(sails,villageAt(el('i',null,'vfx-gear va'),1772,988));
 [[130,0,240],[900,-110,300],[1560,-190,270]].forEach(([y,d,t])=>{const c=villageAt(el('i',null,'vfx-cloud va'),0,y);villageVars(c,{'--d':`${d}s`,'--t':`${t}s`});fx.append(c);});
 [[230,0],[1300,-36]].forEach(([y,d])=>{const b=villageAt(el('i',null,'vfx-birds va'),0,y);villageVars(b,{'--d':`${d}s`});b.append(el('b'),el('b'),el('b'));fx.append(b);});
 return fx;
}
function villageWaterWheel(){const w=el('i',null,'vfx-wheel va');w.style.left='28.82%';w.style.top='28.06%';w.style.width='3.333%';w.style.height='5.278%';w.setAttribute('aria-hidden','true');w.innerHTML=VILLAGE_WHEEL_SVG;return w;}
function villageVisitorsToday(now=Date.now()){const day=Math.floor((now+3*3600e3)/864e5),n=VILLAGE_VISITORS.length-1,a=day%n,b=(a+1+(day*3)%(n-1))%n,list=[VILLAGE_VISITORS[a],VILLAGE_VISITORS[b]];if(day%7===0)list[1]=VILLAGE_VISITORS[n];const out=list.map((v,i)=>({v,spot:VILLAGE_VISITOR_SPOTS[(day+i*2)%VILLAGE_VISITOR_SPOTS.length]}));const egg=villageEggToday(day);if(egg)out.push({v:egg,spot:VILLAGE_VISITOR_SPOTS[(day+1)%VILLAGE_VISITOR_SPOTS.length]});return out;}
function villageEggToday(day){return day%5===3?VILLAGE_EGGS[Math.floor(day/5)%VILLAGE_EGGS.length]:null;}
function openVillageVisitor(id){villageVisitor=id;villageResident=null;villageSheet='visitor';syncVillageScene();showPanel();renderPanel();}
// Static layer built once with the world: place signs, construction sites ("скоро") and today's guests.
function villagePlaces(){
 const layer=el('div',null,'village-places');
 for(const [id,label,ic,x,y,tab] of VILLAGE_PLACES){const b=button(null,e=>id==='market'&&typeof CONSTR!=='undefined'&&CONSTR.rowsOpen()?villageGo([x,y+2.4],()=>openVillageConstruction('rows'),e):villageGo([x,y+2.4],()=>selectTab(tab),e),'village-place');b.style.left=`${x}%`;b.style.top=`${y}%`;b.dataset.villagePlace=id;b.setAttribute('aria-label',label);b.title=label;b.append(icon(ic));layer.append(b);}
 for(const [id,label,x,y] of VILLAGE_SITES){const t=button(typeof CONSTR==='undefined'?`Скоро · ${label}`:CONSTR.siteLabel(id,label),e=>villageGo([x,y+3.2],()=>openVillageConstruction('site:'+id),e),'village-site village-site-btn');t.dataset.villageSite=id;t.dataset.siteName=label;t.style.left=`${x}%`;t.style.top=`${y}%`;layer.append(t);}
 villageVisitorsToday().forEach(({v,spot},i)=>{const [id,name,face]=v,b=button(null,e=>villageGo([spot[0],spot[1]+1.6],()=>openVillageVisitor(id),e),'village-visitor va');b.style.left=`${spot[0]}%`;b.style.top=`${spot[1]}%`;b.dataset.villageVisitor=id;b.dataset.villageSpot=String(VILLAGE_VISITOR_SPOTS.indexOf(spot));b.setAttribute('aria-label',`${name}: гость деревни`);villageVars(b,{'--wx':`${i?-40:40}px`,'--wy':`${i?20:-20}px`,'--d':`${i*3}s`,'--cycle':`${19+i*4}s`,'--td':`${2+i*5}s`});
  const walker=el('span',null,'village-walker');walker.setAttribute('aria-hidden','true');walker.append(el('span',face,'village-visitor-face'));b.append(walker);const say=el('span','💬','village-thought');say.setAttribute('aria-hidden','true');b.append(say);layer.append(b);});
 layer.append(villageCartButton());
 return layer;
}
function villageMerchantLayer(kind){const n=el('div',null,`village-merchant village-merchant-${kind}`);n.setAttribute('aria-hidden','true');return n;}
function villageMerchantFigure(){const f=el('div',null,'village-merchant-figure');f.setAttribute('aria-hidden','true');f.style.left=`${(VILLAGE_MERCHANT.foot[0]/24).toFixed(2)}%`;f.style.top=`${(VILLAGE_MERCHANT.foot[1]/18).toFixed(2)}%`;f.innerHTML=VILLAGE_MERCHANT.figure;return f;}
// Fills the cart layers once the visit flag is on (the art is fetched on the first visit only).
function syncVillageMerchant(){
 const on=!!globalThis.document?.documentElement?.dataset?.merchant,layers=[...($('village-scene')?.querySelectorAll?.('.village-merchant')||[])];
 if(!on||!layers.length)return;
 const fill=svg=>{for(const n of layers)if(!n.firstChild)n.innerHTML=svg;};
 if(villageMerchantSvg){fill(villageMerchantSvg);return;}
 if(typeof fetch!=='function')return;
 fetch(`/app/farm/assets/${VILLAGE_MERCHANT.asset}`).then(r=>r.ok?r.text():'').then(svg=>{if(svg.startsWith('<svg')){villageMerchantSvg=svg;fill(svg);}}).catch(()=>{});
}
// Сорока-коробейница: S.me.merchant_view comes from the server (qw_farm/merchant.py). The flag html[data-merchant] shows the cart art while she is in the village;
// the tap target stays on the cart box in both cases (an empty spot says when she is back).
function merchantView(){return typeof MERCH==='undefined'?null:MERCH.view(S.me);}
function merchantLabel(v){return typeof MERCH==='undefined'||typeof now!=='function'?'Тележка Сороки':MERCH.cartLabel(v,now());}
function merchantHelpers(){
 return {...festivalHelpers(),now,view:merchantView,catalog:S.catalog,festivalGoods:()=>S.me?.festival?.fair?.goods||[],
  placed:id=>!!S.farm?.objects?.some(o=>o.type===id),place:id=>{const spec=S.catalog.buildings[id];if(spec)beginPlacement(spec);}};
}
function villageCartButton(){
 const [x,y,w,h]=VILLAGE_MERCHANT.cart,b=button(null,e=>villageGo([VILLAGE_MERCHANT.foot[0]/24,VILLAGE_MERCHANT.foot[1]/18+1.6],openVillageMerchant,e),'village-cart');
 b.style.left=`${(x/24).toFixed(2)}%`;b.style.top=`${(y/18).toFixed(2)}%`;b.style.width=`${(w/24).toFixed(2)}%`;b.style.height=`${(h/18).toFixed(2)}%`;
 b.dataset.villageMerchant='1';b.setAttribute('aria-controls','panel-content');b.setAttribute('aria-label',merchantLabel(merchantView()));
 return b;
}
function syncMerchantFlag(){
 if(typeof MERCH==='undefined')return;
 const v=own()?merchantView():null;MERCH.applyFlag(v);
 const b=$('village-scene')?.querySelector?.('.village-cart');if(b?.setAttribute)b.setAttribute('aria-label',merchantLabel(v));
 const key=v?.visit_id||'';if(key&&key!==merchantToastKey){merchantToastKey=key;let seen=null;try{seen=localStorage.getItem('qw-farm.merchant-seen');}catch{}if(seen!==key){try{localStorage.setItem('qw-farm.merchant-seen',key);}catch{}toast('Сорока приехала на рынок!');}}
}
function openVillageConstruction(sheet){if(!own())return;villageResident=null;villageSheet=sheet;syncVillageScene();showPanel();renderPanel();}
function syncVillageSites(){if(typeof CONSTR==='undefined')return;for(const b of $('village-scene')?.querySelectorAll?.('[data-village-site]')||[]){const text=CONSTR.siteLabel(b.dataset.villageSite,b.dataset.siteName);if(b.textContent!==text)b.textContent=text;}}
function openVillageMerchant(){if(!own())return;villageResident=null;villageSheet='merchant';syncVillageScene();showPanel();renderPanel();}
// Construction sites and the market rows: one <svg><use> per piece of village-build.svg, placed by its box (world units → % of
// the world). The stage of a site and the open stalls come from construction.js; the stalls stand once the rows are built.
function villageBuildLayer(kind){const n=el('div',null,`village-build village-build-${kind}`);n.setAttribute('aria-hidden','true');return n;}
function villageCrewLayer(){const n=el('div',null,'village-crew-layer');n.setAttribute('aria-hidden','true');return n;}
function villageBuildPiece(layer,key,id){
 let n=[...layer.children].find(c=>c.dataset?.build===key);
 const box=id&&VILLAGE_BUILD.boxes[id.replace(/-night$/,'')];
 if(!box){n?.remove();return;}
 if(n?.dataset.piece===id)return;
 const ns='http://www.w3.org/2000/svg',u=document.createElementNS(ns,'use');
 if(!n){n=document.createElementNS(ns,'svg');n.dataset.build=key;layer.append(n);}
 n.setAttribute('viewBox',box.join(' '));n.setAttribute('preserveAspectRatio','none');
 n.style.left=`${(box[0]/24).toFixed(3)}%`;n.style.top=`${(box[1]/18).toFixed(3)}%`;n.style.width=`${(box[2]/24).toFixed(3)}%`;n.style.height=`${(box[3]/18).toFixed(3)}%`;
 u.setAttribute('href',`/app/farm/assets/${VILLAGE_BUILD.asset}#${id}`);for(const [k,i] of [['x',0],['y',1],['width',2],['height',3]])u.setAttribute(k,String(box[i]));
 n.replaceChildren(u);n.dataset.piece=id;
}
function syncVillageBuild(){
 const scene=$('village-scene'),base=scene?.querySelector?.('.village-build-base'),glow=scene?.querySelector?.('.village-build-glow'),crew=scene?.querySelector?.('.village-crew-layer');
 if(typeof CONSTR==='undefined'||!base||!glow||!crew||!globalThis.document?.createElementNS)return;
 for(const id of VILLAGE_BUILD.sites){
  const {stage,crew:work}=CONSTR.art(id);
  villageBuildPiece(base,id,`site-${id}-${stage}`);villageBuildPiece(glow,id,stage==='done'&&id!=='stalls'?`site-${id}-done-night`:'');
  const team=[...crew.children].filter(c=>c.dataset.crewSite===id);
  if(!work){team.forEach(c=>c.remove());continue;}
  if(team.length)continue;
  ['krot','pooh','kaya'].forEach((name,i)=>{const [x,y]=VILLAGE_BUILD.crew[id][i],f=el('div',null,`village-crew vc-${name}`);f.dataset.crewSite=id;
   f.style.left=`${(x/24).toFixed(2)}%`;f.style.top=`${(y/18).toFixed(2)}%`;f.innerHTML=VILLAGE_CREW[name];crew.append(f);});
 }
 const open=CONSTR.rowsOpen(),state=open?CONSTR.stalls():{};
 for(const id of VILLAGE_BUILD.stalls){villageBuildPiece(base,'stall-'+id,open?`stall-${id}-${state[id]}`:'');villageBuildPiece(glow,'stall-'+id,open&&state[id]==='open'?`stall-${id}-open-night`:'');}
}
function villageFestLayer(kind){const n=el('div',null,`village-fest village-fest-${kind}`);n.setAttribute('aria-hidden','true');return n;}
function syncVillageFest(){
 const d=globalThis.document?.documentElement?.dataset,id=d?.festivalDecor==='on'?d.festival:'',file=VILLAGE_FEST[id];
 const layers=[...($('village-scene')?.querySelectorAll?.('.village-fest')||[])];
 if(!file||!layers.length)return;
 const fill=svg=>{for(const n of layers)if(n.dataset.fest!==id){n.innerHTML=svg;n.dataset.fest=id;}};
 if(villageFestCache[id]){fill(villageFestCache[id]);return;}
 if(typeof fetch!=='function')return;
 fetch(`/app/farm/assets/${file}`).then(r=>r.ok?r.text():'').then(svg=>{if(svg.startsWith('<svg')){villageFestCache[id]=svg;fill(svg);}}).catch(()=>{});
}
function villageBuildWorld(){
 const world=el('div',null,'village-world'),art=el('img',null,'village-art');art.src='/app/farm/assets/village.svg';art.alt='Большая деревня: площадь с ратушей и колодцем, дома жителей, рынок, почта, мастерская, мельница у реки, пруд, сады и дорога к воротам на ферму';art.draggable=false;art.decoding='async';world.append(art);
 world.onclick=e=>{if(e.target?.closest?.('button'))return;const r=world.getBoundingClientRect();villageWalk([villageClamp((e.clientX-r.left)/r.width*100,2,98),villageClamp((e.clientY-r.top)/r.height*100,3,97)]);};
 const sun=el('div',null,'village-sun');sun.setAttribute('aria-hidden','true');
 const night=el('div',null,'village-night');night.setAttribute('aria-hidden','true');night.append(el('i',null,'vn-tint'));
 VILLAGE_LIGHTS.forEach(([x,y,k])=>night.append(villageAt(el('i',null,`vn-light vn-${k}`),x,y)));
 VILLAGE_FLIES.forEach(([x,y],i)=>{const n=villageAt(el('i',null,'vn-fly va'),x,y);villageVars(n,{'--d':`${i*1.3}s`,'--fx':`${i%2?-30:26}px`,'--fy':`${i%3?-22:16}px`});night.append(n);});
 const actors=el('div',null,'village-actors');
 const gate=button(null,e=>villageGo([VILLAGE_GATE[0],VILLAGE_GATE[1]-1.2],exitVillage,e),'village-gate');gate.style.left=`${VILLAGE_GATE_BOARD[0]}%`;gate.style.top=`${VILLAGE_GATE_BOARD[1]}%`;gate.style.width=`${VILLAGE_GATE_BOARD[2]}%`;gate.style.height=`${VILLAGE_GATE_BOARD[3]}%`;gate.dataset.villageGate='gate';gate.setAttribute('aria-label','На ферму: ворота деревни');gate.title='На ферму';gate.innerHTML=VILLAGE_GATE_SIGN;
 const player=el('div',null,'village-player');player.setAttribute('aria-hidden','true');player.style.left=`${villagePos[0]}%`;player.style.top=`${villagePos[1]}%`;player.dataset.face='right';player.innerHTML=VILLAGE_PLAYER_SVG;
 world.append(villageMerchantLayer('base'),villageFestLayer('base'),villageBuildLayer('base'),sun,villageFx(),night,villageFestLayer('glow'),villageBuildLayer('glow'),villageMerchantLayer('glow'),villageMerchantFigure(),villageWaterWheel(),villageCrewLayer(),actors,villagePlaces(),gate,player);
 return world;
}
function syncVillageScene(){
 let root=$('village-scene');if(!root){root=el('section',null,'village-scene');root.id='village-scene';root.setAttribute('aria-label','Деревенская площадь');root.tabIndex=0;document.querySelector('.scene-area').append(root);}
 let hud=$('village-hud');if(!hud){hud=el('div',null,'village-hud');hud.id='village-hud';document.querySelector('.scene-area').append(hud);}
 const visible=villageVisible(),entering=visible&&root.hidden===true;root.hidden=!visible;hud.hidden=!visible;document.body.classList.toggle('village-open',visible);$('farm-canvas').inert=visible;if(!visible){villageWalkStop();villageResident=null;villageSheet=null;}syncScenePause();if(!visible)return;
 villageBindWorld(root);if(entering)villageCenter(villagePos,false);syncVillageFest();syncMerchantFlag();syncVillageMerchant();syncVillageSites();syncVillageBuild();
 if(!villageVisBound&&document.addEventListener){villageVisBound=true;document.addEventListener('visibilitychange',()=>$('village-scene')?.classList?.toggle('village-paused',document.hidden));}
 const names=villageNames(),stage=villageStage(),sig=JSON.stringify([S.me.id,stage,villageSheet,villageResident,names.map(n=>[n,repInfo(n).lv,villageOrders(n).map(o=>[o.id,villageReady(o)]),villageQuestPhase(n)])]);if(sig===villageSceneSignature)return;villageSceneSignature=sig;
 root.setAttribute('aria-label',(stage===null?(eco()?.fund_open?'Деревня. Данные праздника обновляются.':`Деревня. Сезонный фонд откроется с ${ECON().fund_level} уровня.`):`Деревня. ${['Начало подготовки праздника','Флажки к празднику','Цветы к празднику','Площадь готова к празднику'][stage]}.`)+' Прокручивай карту, нажимай на землю, чтобы идти, или выбирай жителей кнопками.');
 const focused=document.activeElement?.dataset?.villageNpc||document.activeElement?.dataset?.villageTownhall;
 // The world (image, lights, effects, player) is built once; only the actors layer changes with game state.
 if(!villageWorldEl||root.children?.[0]!==villageWorldEl){villageWorldEl=villageBuildWorld();root.replaceChildren(villageWorldEl);villageCenter(villagePos,false);}
 const world=villageWorldEl,actors=world.children.find?world.children.find(n=>n.className==='village-actors'):world.querySelector('.village-actors'),parts=[];
 const festival=el('div',null,`village-festival stage-${stage===null?'locked':stage}`);festival.setAttribute('aria-hidden','true');festival.append(el('span',null,'village-flags'),el('span',null,'village-flowers'),el('span',null,'village-lights'),el('span',null,'village-balloons'));
 const badge=el('div',null,'village-stage-badge');if(stage===null)badge.append(el('b',eco()?.fund_open?'Праздник: ждём данные':`Праздник с ${ECON().fund_level} ур.`));else{badge.append(el('b',`Праздник ${stage+1}/4`),el('small',VILLAGE_STAGES[stage]));const pips=el('span',null,'village-pips');for(let i=0;i<4;i++)pips.append(el('i',null,i<=stage?'on':''));badge.append(pips);}festival.append(badge);parts.push(festival);
 for(const npc of names){const spot=VILLAGE_SPOTS[npc];if(!spot)continue;const life=VILLAGE_LIFE[npc]||['💭',12,4],idx=names.indexOf(npc),orders=villageOrders(npc),quest=villageQuest(npc),ready=orders.some(villageReady)||!!(quest&&villageQuestPhase(npc)==='active'&&enough({[quest.item]:quest.qty})),selected=villageSheet==='resident'&&npc===villageResident;
  const b=button(null,e=>{if(npc==='Лиса Даша')villagePresenceTalk();villageGo([spot[0],spot[1]+1.6],()=>chooseVillageResident(npc),e);},'village-npc va');b.style.left=`${spot[0]}%`;b.style.top=`${spot[1]}%`;villageVars(b,{'--wx':`${life[1]}px`,'--wy':`${life[2]}px`,'--face':life[1]<0?'-1':'1','--d':`${(idx*2.1)%9}s`,'--cycle':`${16+idx*1.7}s`,'--td':`${idx*3.1%13}s`});b.dataset.villageNpc=npc;b.dataset.edge=spot[0]<8?'left':'';b.setAttribute('aria-pressed',String(selected));b.setAttribute('aria-controls','panel-content');b.setAttribute('aria-label',`${npc}${orders.length?` · есть просьба${ready?', можно доставить':''}`:''}`);
  const walker=el('span',null,'village-walker');walker.setAttribute('aria-hidden','true');walker.append(villageQuest(npc)?el('span',npc==='Лиса Даша'?'🦊':'🐓','village-visitor-face'):icon(AVATARS[npc]||'owl'));b.append(walker);
  if(!orders.length&&!selected){const thought=el('span',life[0],'village-thought');thought.setAttribute('aria-hidden','true');b.append(thought);}
  if(selected){const label=el('span',null,'village-npc-name');label.append(el('b',npc));if(!quest){const max=Math.max(1,(S.catalog.market.rep_points?.length||4)-1),lv=Math.min(max,repInfo(npc).lv);label.append(el('i','♥'.repeat(lv)+'♡'.repeat(max-lv),'village-hearts'));}b.append(label);}
  if(orders.length||villageQuest(npc)&&villageQuestPhase(npc)!=='done'){const need=orders.length?Object.keys(orders[0].needs||{})[0]:villageQuest(npc).item,mark=el('span',null,`village-order${ready?' is-ready':''}`);mark.setAttribute('aria-hidden','true');if(need)mark.append(icon(need));mark.append(el('b',orders.length>1?`×${orders.length}`:(ready?'✓':'!')));b.append(mark);}
  parts.push(b);}
 const hall=button(null,e=>villageGo([VILLAGE_HALL[0],VILLAGE_HALL[1]+3.6],()=>openVillageTownHall(),e),'village-townhall');hall.style.left=`${VILLAGE_HALL[0]}%`;hall.style.top=`${VILLAGE_HALL[1]}%`;hall.dataset.villageTownhall='townhall';hall.setAttribute('aria-label','Ратуша: фонд, содержание и украшения');hall.setAttribute('aria-controls','panel-content');hall.setAttribute('aria-pressed',String(villageSheet==='townhall'));hall.append(icon('friends'),el('span','Ратуша'));parts.push(hall);
 actors.replaceChildren(...parts);villageObserve(world);
 if(focused)parts.find(b=>b.dataset?.villageNpc===focused||b.dataset?.villageTownhall===focused)?.focus({preventScroll:true});
 // HUD stays put while the world scrolls: way out, compass minimap, night sky.
 const back=button('На ферму',exitVillage,'secondary village-back'),sky=el('div',null,'village-sky');sky.setAttribute('aria-hidden','true');sky.append(el('i',null,'vs-stars'),el('i',null,'vs-moon'));
 const mini=button(null,e=>{if(!e.detail||!mini.getBoundingClientRect){villageCenter(villagePos,true);return;}const r=mini.getBoundingClientRect();villageCenter([(e.clientX-r.left)/r.width*100,(e.clientY-r.top)/r.height*100],true);},'village-minimap');mini.dataset.villageMinimap='1';mini.setAttribute('aria-label','Мини-карта деревни. Нажми, чтобы переместить камеру; по клавише камера вернётся к тебе.');
 const dot=(cls,pos,title)=>{const d=el('i',null,cls);d.style.left=`${pos[0]}%`;d.style.top=`${pos[1]}%`;if(title)d.title=title;mini.append(d);return d;};
 dot('vm-mark vm-hall',VILLAGE_HALL);dot('vm-mark vm-gate',VILLAGE_GATE);
 for(const npc of names){const spot=VILLAGE_SPOTS[npc];if(spot)dot(`vm-mark vm-npc${villageOrders(npc).length?' has-order':''}`,spot,npc);}
 const frame=el('i',null,'vm-frame'),me=dot('vm-mark vm-player',villagePos);mini.append(frame);villageMini={frame,player:me};
 hud.replaceChildren(sky,back,mini);villageFrame();
}
function appendDashaAction(parent){
 const w=S.me?.wager;if(!own())return;
 const b=button('Играть с Дашей',openDashaGame,'qw-btn primary wide');b.dataset.openDasha='true';parent.append(b);
 if(!w)note('Загружаем условия игры…',parent);else if(!w.active&&!w.eligible)note(dashaReasonText(w.reason),parent);
 else if(w?.active)note('Твой раунд сохранён. Можно продолжить в любой момент.',parent);
}
function appendOlegAction(parent){
 const g=S.me?.oleg_game;if(!own())return;
 const b=button('Сыграть с Олегом',openOlegGame,'qw-btn primary wide');b.dataset.openOleg='true';parent.append(b);
 if(!g)note('Загружаем перезвон…',parent);
 else if(g.active)note(`Перезвон сохранён: мелодия ${(Number(g.active.round)||0)+1} из ${Number(g.active.rounds)||3}.`,parent);
 else if(g.rewarded_today)note('Награда за перезвон сегодня получена — можно играть просто так.',parent);
 else note(`Три мелодии на колокольчиках: +${fmt(g.next_reward?.coins||0)} мон. и +${fmt(g.next_reward?.xp||0)} опыта раз в день.`,parent);
}
function renderVillageResident(p){
 const spec=villageQuest(villageResident);
 if(spec){
  const npc=villageResident,phase=villageQuestPhase(npc),c=card(npc,'ЖИТЕЛЬ ДЕРЕВНИ');c.classList.add('village-resident');c.tabIndex=-1;c.dataset.villageFocus='resident';
  c.append(el('p',VILLAGE_VOICES[npc]?.[phase==='done'?1:0]||'', 'village-dialogue'));
  if(npc==='Лиса Даша')appendDashaAction(c);
  if(npc==='Петух Олег')appendOlegAction(c);
  p.append(c);
  const q=card(spec.title,phase==='done'?'Сегодня выполнено':phase==='active'?'Задание взято':'Новое задание','orders');
  q.append(goods({[spec.item]:spec.qty},false));
  const reward=el('span',`+${fmt(spec.coins)} мон. · +${fmt(spec.xp)} опыта`,'reward');q.append(reward);
  if(phase==='available')q.append(button('Взять задание',()=>villageQuestAction(npc,'take'),'primary'));
  else if(phase==='active'){const ready=enough({[spec.item]:spec.qty});q.append(button('Сдать задание',()=>villageQuestAction(npc,'deliver'),'primary',!ready));if(!ready)note(`Не хватает: ${itemName(spec.item)} ×${fmt(spec.qty-stock(spec.item))}. Вырасти или приготовь на ферме.`,q);}
  else note('Новая просьба появится завтра.',q);
  p.append(q);return;
 }
 const npc=villageResident,r=repInfo(npc),c=card(npc,'ЖИТЕЛЬ ДЕРЕВНИ');c.classList.add('village-resident');c.tabIndex=-1;c.dataset.villageFocus='resident';
 const voices=VILLAGE_VOICES[npc]||['Рады видеть тебя на площади.'];c.append(el('p',voiceFor(voices[Math.min(2,r.lv)]||voices[0]),'village-dialogue'),repBar(npc),el('h3','Любимые товары','subheading'),goods(Object.fromEntries(S.catalog.market.tastes[npc].map(id=>[id,1])),false));if(npc==='Лиса Даша')appendDashaAction(c);p.append(c);
 const orders=villageOrders(npc);p.append(el('h3','Просьбы сегодня','subheading'));if(!orders.length){note('Сейчас просьб нет. Загляни позже: новые заказы появляются на общей доске.',p);return;}
 for(const o of orders){const order=card(o.title,o.special?'Особая просьба':'Заказ с доски','orders'),coins=Math.floor(o.coins*(100+r.bonus)/100),xp=Math.floor(o.xp*(100+r.bonus)/100);order.append(goods(o.needs));const action=button('Доставить',()=>deliverVillageOrder(o.id),'primary',!enough(o.needs));action.dataset.villageFocus=`order:${o.id}`;const footer=el('div',null,'card-footer');footer.append(el('span',`+${fmt(coins)} мон. · +${fmt(xp)} опыта`,'reward'),action);order.append(footer);if(!enough(o.needs))note('Недостающие товары можно вырастить или приготовить на ферме.',order);p.append(order);}
}
function renderVillage(p){
 if(typeof CONSTR!=='undefined'&&(villageSheet==='rows'||String(villageSheet).startsWith('site:'))){CONSTR.render(p,villageSheet);return;}
 if(villageSheet==='merchant'){heading('Лавка Сороки','ТЕЛЕЖКА НА РЫНКЕ');MERCH.renderShop(p,merchantView(),merchantHelpers());return;}
 if(villageSheet==='visitor'){const v=[...VILLAGE_VISITORS,...VILLAGE_EGGS].find(v=>v[0]===villageVisitor);if(v){heading(v[1],'ГОСТЬ ДЕРЕВНИ');const c=card(`${v[2]} ${v[1]}`,'Сегодня в деревне');c.append(el('p',v[3],'village-dialogue'));const go=button(v[4],()=>selectTab(v[5]),'primary');c.append(go);note('Гости меняются каждый день. Своих заданий у них пока нет — они подсказывают, куда заглянуть.',c);p.append(c);return;}}
 if(villageSheet==='resident'&&villageResident){heading(villageResident,'НА ДЕРЕВЕНСКОЙ ПЛОЩАДИ');renderVillageResident(p);return;}if(villageSheet!=='townhall'){heading('Деревня','ЖИТЕЛИ И ОБЩАЯ ПЛОЩАДЬ');return;}heading('Ратуша','СЕЗОННЫЙ ПРАЗДНИК И ДЕЛА ФЕРМЫ');
 const e=eco();if(!e){note('Данные фонда пока недоступны. Обнови ферму.',p);return;}
 const seasonal=el('section',null,'card village-season');seasonal.append(el('strong','Сезонная подготовка праздника'));note('Помогаем вместе: флажки, цветы и угощения появляются по мере наполнения общего фонда. В новом сезоне подготовка начинается заново.',seasonal);
 const stage=villageStage();if(stage===null)note(e.fund_open?'Данные общего фонда пока недоступны. Обнови ферму.':`Фонд и этапы подготовки откроются с ${ECON().fund_level} уровня.`,seasonal);else{seasonal.append(meter(S.village.total,S.village.goal));note(`${fmt(S.village.total)} / ${fmt(S.village.goal)} мон. · этап ${stage+1} из 4`,seasonal);}p.append(seasonal);
 for(const [name,draw] of [['Фонд и праздник',fundCard],['Содержание фермы',upkeepCard],['Украшения фермы',decorShop]]){const details=el('details',null,'village-services');details.dataset.villageService=name;const summary=el('summary',name);summary.dataset.villageFocus=`service:${name}`;details.append(summary);draw(details,e);p.append(details);}
}

/* ---- r9 stage 15B: fields, special machinery and the top-down minigames (rules live on the server: qw_farm/fields.py) ---- */
function FC(){return S.catalog.fields;}
function fieldMachine(id){return S.me.field_machines?.[id];}
function fieldPhase(f){
 if(f.run?.status==='auto')return 'auto';
 if(f.run?.status==='open')return 'open';
 if(f.state==='growing'&&f.crop.ready_at<=now())return 'ripe';
 return f.state;
}
function fieldStateText(ph){return {wild:'Дикое поле',ready:'Подготовлено под посев',growing:'Растёт',ripe:'Созрело',auto:'Автопилот в работе',open:'Машина в поле'}[ph]||ph;}
function pct1(permille){return (permille/10).toFixed(1).replace('.',',')+'%';}
function fieldCropList(){return FC().crops.map(id=>S.catalog.crops[id]).filter(Boolean);}
function fieldFuel(f){return FC().fuel*f.ha;}
function renderFields(p){
 heading('Поля','ЗА ОКОЛИЦЕЙ');
 const F=FC();
 if(!F){note('Поля пока недоступны. Обнови ферму.',p);return;}
 if(S.me.level<F.min_level){
  const c=card(`Откроется на ${F.min_level} уровне`,`Сейчас у тебя ${S.me.level} уровень`,'tractor');
  c.append(el('p','За околицей ждут большие поля от гектара. Купишь культиватор, сеялку и комбайн, '+gf('будешь водить их сам или доверишь автопилоту.','будешь водить их сама или доверишь автопилоту.','водить их можно вручную или доверить автопилоту.')+'','note'),meter(S.me.level,F.min_level));
  p.append(c);return;
 }
 note('Поле проходит цикл: дикое → культивация → посев → рост → уборка. Каждую операцию можно '+gf('проехать самому','проехать самой','проехать вручную')+' (качество до 110%) или отдать автопилоту (95%). Маршрут проверяет сервер.',p);
 note('Если заходишь раз в сутки, на полях окупаются культуры со сроком роста около 24 часов.',p);
 p.append(el('h3','Мои поля','subheading'));
 const mine=S.me.fields||[];
 if(!mine.length)note('Полей пока нет — купи первое ниже.',p);
 for(const f of mine)p.append(fieldCard(f));
 p.append(el('h3','Техника','subheading'));
 for(const m of Object.values(F.machines))p.append(machineCard(m));
 p.append(el('h3','Купить поле','subheading'));
 const owned=new Set(mine.map(f=>f.step));
 for(const st of F.steps){
  if(owned.has(st.step))continue;
  const c=card(`Поле ${st.ha} га`,`С ${st.level} уровня · ${fmt(st.cost)} монет`,'wheat');
  note(`Сетка ${F.w} × ${F.w*st.ha}. Содержание — ${fmt(F.upkeep*st.ha)} монет в сутки.`,c);
  if(S.me.level<st.level)note(`Откроется на ${st.level} уровне.`,c);
  c.append(button(`Купить за ${fmt(st.cost)} монет`,()=>command('buy_field',{step:st.step}),'primary wide',S.me.level<st.level||S.me.coins<st.cost));
  p.append(c);
 }
}
function machineCard(m){
 const own1=fieldMachine(m.id),tier=own1?.tier||0,max=m.costs.length;
 const c=card(m.name,tier?`Ширина захвата ${tier} из ${max}`:'Не куплена',m.icon);
 note(m.description,c);
 if(tier>=max){note('Максимальная ширина захвата.',c);return c;}
 const lv=m.levels[tier],cost=m.costs[tier];
 if(S.me.level<lv)note(`Откроется на ${lv} уровне.`,c);
 c.append(button(tier?`Улучшить до ширины ${tier+1} — ${fmt(cost)} монет`:`Купить — ${fmt(cost)} монет`,()=>command(tier?'upgrade_machine':'buy_machine',{machine:m.id}),tier?'light wide':'primary wide',S.me.level<lv||S.me.coins<cost));
 return c;
}
function fieldCard(f){
 const F=FC(),ph=fieldPhase(f),c=card(`Поле ${f.ha} га`,fieldStateText(ph),'wheat');
 c.dataset.field=f.id;
 const fuel=fieldFuel(f),opOf={wild:'cultivate',ready:'sow',ripe:'harvest'}[ph],spec=opOf&&F.ops[opOf],machine=spec&&F.machines[spec.machine],have=machine&&fieldMachine(machine.id);
 if(ph==='open'){
  const row=el('p',null,'note');row.append('Машина в поле, осталось ',timer(f.run.expires_at),'. Потом работу закончит автопилот.');c.append(row);
  c.append(button('Продолжить за рулём',()=>launchField(f),'primary wide'),button(`Автопилот: качество ${pct1(F.q_auto)}`,()=>command('field_finish',{field:f.id,run:f.run.id,path:null}),'secondary wide'));
 }else if(ph==='auto'){
  const row=el('p',null,'note');row.append('Автопилот закончит через ',timer(f.run.done_at),` (качество ${pct1(F.q_auto)}).`);c.append(row);
 }else if(ph==='growing'){
  const cr=S.catalog.crops[f.crop.id],row=el('p',null,'note');row.append(`${cr?.name||f.crop.id}: созреет через `,timer(f.crop.ready_at),`. Качество посева ${pct1(f.crop.q_sow)}.`);c.append(row);
 }else if(opOf){
  if(!have)note(`Нужна машина: ${machine.name}. Купи её ниже.`,c);
  if(ph==='wild'){
   note(`Культивация срезает сорняки: чем чище работа, тем быстрее растёт урожай (до −${F.grow_cut/10}% времени). Топливо — ${fmt(fuel)} монет.`,c);
   c.append(button(`Культивировать — ${fmt(fuel)} монет`,()=>startFieldOp(f,'cultivate'),'primary wide',!have||S.me.coins<fuel));
  }else if(ph==='ready'){
   const crops=fieldCropList().filter(x=>x.level<=S.me.level);
   S.fieldCrop=S.fieldCrop||{};
   if(!crops.length)note('Для полей пока нет открытых культур.',c);
   else{
    let cur=crops.find(x=>x.id===S.fieldCrop[f.id])||crops[0];
    const sel=el('select');sel.setAttribute('aria-label','Культура для посева');
    for(const x of crops){const o=el('option',x.name);o.value=x.id;sel.append(o);}
    sel.value=cur.id;
    const info=el('p',null,'note'),go=button('',()=>startFieldOp(f,'sow',sel.value),'primary wide');
    const upd=()=>{cur=crops.find(x=>x.id===sel.value)||crops[0];S.fieldCrop[f.id]=cur.id;const seeds=cur.cost*F.seed_mult*f.ha,secs=Math.max(cur.seconds,F.min_grow)*growthPermille(f.q_cult)/1000;
     info.textContent=`Семена ${fmt(seeds)} + топливо ${fmt(fuel)} монет. Растёт ${duration(secs)}. Культивация: качество ${pct1(f.q_cult)}.`;
     go.textContent=`Сеять — ${fmt(seeds+fuel)} монет`;go.disabled=!have||S.me.coins<seeds+fuel;};
    sel.onchange=upd;upd();c.append(sel,info,go);
   }
  }else{
   const cr=S.catalog.crops[f.crop.id],qty=yieldQty(f.crop.base,f.crop.q_sow,F.q_auto);
   note(`${cr?.name||f.crop.id}: примерно ${fmt(qty)} шт. на автопилоте, до ${fmt(yieldQty(f.crop.base,f.crop.q_sow,F.q_base+F.q_span))} за рулём. Топливо — ${fmt(fuel)} монет.`,c);
   c.append(button(`Убирать — ${fmt(fuel)} монет`,()=>startFieldOp(f,'harvest'),'primary wide',!have||S.me.coins<fuel));
  }
 }
 return c;
}
async function startFieldOp(f,op,crop=''){
 const ok=await command('field_start',{field:f.id,op,crop,revision:f.revision});
 if(!ok)return;
 const nf=(S.me.fields||[]).find(x=>x.id===f.id);
 if(nf?.run?.status==='open')launchField(nf);
}
async function startTrip(route,guideId,play){
 const ok=await command('start_trip',{route:route.id,guide:guideId});
 if(!ok||!play)return;
 const trip=S.me.trips.filter(t=>!t.guide&&t.route===route.id&&t.game?.state==='open').pop();
 if(trip)launchTripGame(trip);
}
function launchTripGame(trip){
 if(S.fieldGame||!canPlay(trip,now()))return;
 const id=trip.id;
 S.fieldGame={};syncScenePause();
 try{S.fieldGame=openTripGame({trip,route:S.catalog.routes[trip.route],rules:S.catalog.trip_games,serverNow:now,itemName,timeText,
  inventory:{...(S.me.inventory||{})},journal:{...(S.me.fish_journal||{})},
  onFinish:log=>command('trip_play',{trip:id,log}),
  tripNow:()=>(S.me.trips||[]).find(t=>t.id===id)||null,
  onClose:()=>{S.fieldGame=null;syncScenePause();navPop('minigame');if(['forest','lake'].includes(S.tab))renderPanel();}});
  navPush('minigame',()=>S.fieldGame?.requestClose?.()??true);
 }catch(e){S.fieldGame=null;syncScenePause();throw e;}
}
function launchField(f){
 if(S.fieldGame||!f.run||f.run.status!=='open')return;
 const run=f.run,id=f.id,crop=f.crop?{...f.crop}:null;
 S.fieldGame={};syncScenePause();
 try{S.fieldGame=openFieldGame({field:f,run,cfg:FC(),speed:S.speed,serverNow:now,timeText,itemName,g:gf,cropSnapshot:crop,
  onFinish:path=>command('field_finish',{field:id,run:run.id,path}),
  fieldNow:()=>(S.me.fields||[]).find(x=>x.id===id)||null,
  onClose:()=>{S.fieldGame=null;syncScenePause();navPop('minigame');if(S.tab==='fields')renderPanel();}});
  navPush('minigame',()=>S.fieldGame?.requestClose?.()??true);
 }catch(e){S.fieldGame=null;syncScenePause();throw e;}
}
