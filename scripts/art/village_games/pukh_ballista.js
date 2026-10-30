// Review-only vector scene. FarmScene primitives record into the village SVG recorder.
// Coordinates are shared with the ballista domain: never reposition windows in CSS.
import {makeS, B} from '../village/common.js';
import {SvgCtx} from '../village/svg_ctx.js';

export const WINDOWS=[[270,330],[430,250],[600,200],[760,300],[900,400]];
export const WORLD={width:1000,height:600,launch:[60,500],roof:[420,560,360],radius:36};
// Scene margins: Pukh and the pulled pouch used to sit on the rounded frame's left edge.
export const CANVAS={x:-60,y:0,width:1060,height:636};

export function pukhScene(night=false){
 const c=new SvgCtx('pb'),s=makeS(c);
 const p=night?{sky:'#25394a',skyLow:'#637668',hill:'#6a875e',hillFar:'#77926c',ground:'#65824f',grass:'#78945f',wall:'#bbba9a',side:'#939a81',wood:'#a68c62',cream:'#e8d9b1',roof:'#678773',dark:'#4b6058',fur:'#a17c50'}:
  {sky:'#cfe3d4',skyLow:'#f6edcc',hill:'#a3c587',hillFar:'#bcd3a1',ground:'#8fba73',grass:'#a3c587',wall:'#e8d9ae',side:'#cdbf98',wood:'#b88a5b',cream:'#f3ead2',roof:'#7c9d83',dark:'#587c75',fur:'#b5814f'};
 const poly=(pts,col)=>s.poly(pts.map(([x,y])=>({x,y})),col);
 const rect=(x,y,w,h,col)=>poly([[x,y],[x+w,y],[x+w,y+h],[x,y+h]],col);
 const path=(d,col)=>{c.out.push(`<path d="${d}" fill="${col}"/>`)};
 const group=(id,fn)=>{c.out.push(`<g id="pb-${id}">`);fn();c.end()};
 const sky=c.createLinearGradient(0,0,0,600);sky.addColorStop(0,p.sky);sky.addColorStop(1,p.skyLow);
 group('sky',()=>{rect(CANVAS.x,CANVAS.y,CANVAS.width,CANVAS.height,sky);s.ellipse(830,80,night?30:39,night?30:39,night?'#eee6bf':'#f9e3a1');
  if(night){for(const [x,y] of [[72,72],[170,45],[340,90],[465,43],[709,58],[946,126],[90,212]])s.ellipse(x,y,2,2,'#ece7c5');s.ellipse(822,74,5,5,'#d6d4b3')}
  else{for(const [x,y,k] of [[150,112,.8],[397,70,.6],[936,209,.5]]){s.ellipse(x,y,40*k,12*k,'#f4efdc');s.ellipse(x-13*k,y-6*k,19*k,16*k,'#f4efdc');s.ellipse(x+14*k,y-10*k,22*k,19*k,'#f4efdc')}}});
 group('hills',()=>{path('M-60 480L0 480Q120 352 255 355Q335 340 400 291Q505 233 610 256Q704 281 790 372Q895 427 1000 439V636H-60Z',p.hillFar);
  path('M-60 520L0 520Q130 432 260 423Q334 400 425 343Q520 304 598 288Q670 313 750 396Q863 464 1000 502V636H-60Z',p.hill);
  path('M-60 553L0 553Q210 480 340 486Q440 512 590 491Q820 467 1000 553V636H-60Z',p.ground);
  path('M-60 552L0 552Q170 487 278 464T452 390Q519 348 603 310L620 319Q534 365 472 405Q400 464 287 483T0 579L-60 579Z',night?'#a69f79':'#dcca98');});
 function home(i,x,y){
  const base=y+102,top=y-58,left=x-57,right=x+57;
  group(`home-${i}`,()=>{
   s.ellipse(x+10,base+3,75,11,night?'#435f4c':'#7b9c67');
   // Front and shaded side share their vertical edge; the gable sits on that wall.
   poly([[left,top],[right,top],[right,base],[left,base]],p.wall);
   poly([[right,top],[right+25,top-14],[right+25,base-14],[right,base]],p.side);
   poly([[left,top],[x,top-49],[right,top]],p.wall);
   const roof=night?['#678773','#817667','#7b8173','#7b7660','#678773'][i]:['#7c9d83','#a0836a','#8ea092','#a39170','#7c9d83'][i];
   poly([[x,top-49],[x+25,top-63],[right+30,top-8],[right+5,top+6]],roof);
   for(const t of [.33,.66]){
    const ax=x+(right+5-x)*t,ay=top-49+55*t;
    s.line(ax,ay,ax+25,ay-14,night?'#5b7163':'#718e79',1.1);
   }
   poly([[left-7,top+6],[x,top-49],[right+5,top+6],[right+5,top+14],[x,top-40],[left-7,top+14]],night?'#9da88d':'#b9c5a5');
   s.line(right+5,top+7,right+30,top-7,night?'#526e5d':'#668a70',5);
   rect(left,base-8,114,8,night?'#9b9c81':'#bdb398');
   // A small side door and attic vent keep the targets recognisable as lived-in houses.
   poly([[right+5,base-7],[right+20,base-15],[right+20,base-66],[right+5,base-58]],night?'#82765e':'#9b805b');
   s.ellipse(right+15,base-37,1.6,1.6,'#e8d9a8');
   s.ellipse(x,top-17,8,8,p.cream);s.ellipse(x,top-17,5,5,p.dark);
   for(const z of [base-25,base-43])s.line(left+5,z,right-5,z,night?'#a8aa8e':'#d7caa6',1.1);
   // All 5 target centres are exact server coordinates. Open shutters leave the hit disk clear.
   group(`window-${i}`,()=>{
    rect(x-43,y-45,86,90,p.cream);rect(x-36,y-36,72,72,p.dark);
    if(night){rect(x-32,y-32,64,64,'#d7bb78');rect(x-25,y-24,50,52,'#eed69b')}
    poly([[x-44,y-39],[x-58,y-46],[x-58,y+38],[x-44,y+36]],p.wood);
    poly([[x+44,y-39],[x+57,y-47],[x+57,y+35],[x+44,y+36]],p.wood);
    for(const dx of [-52,51])s.line(x+dx,y-31,x+dx,y+28,night?'#8b7858':'#a77c53',2);
    rect(x-48,y+38,96,7,night?'#c2b18a':'#dec69a');
    c.out.push(`<circle id="pb-target-${i}" cx="${x}" cy="${y}" r="36" fill="none" stroke="none" data-target-index="${i}"/>`);
   });
   // Delivery shelf below the opening; never covers the target.
   rect(x-23,y+51,46,19,night?'#b39764':'#cba774');s.line(x-21,y+57,x+21,y+57,night?'#917d58':'#b38e60',2);
   s.ellipse(x-15,y+65,2,2,p.cream);s.ellipse(x+15,y+65,2,2,p.cream);
  });
 }
 // Far to near; small side faces give the same solids and pastel shading as Oleg's scene.
 for(const i of [2,1,3,0,4])home(i,...WINDOWS[i]);
 group('roof-obstacle',()=>{
  s.ellipse(491,550,97,13,night?'#4b654a':'#749759');
  rect(432,379,116,162,p.wall);rect(548,379,12,162,p.side);
  // The entire horizontal upper lip is the collision surface x420..560,y360.
  poly([[420,360],[560,360],[560,386],[420,386]],p.roof);
  rect(420,360,140,6,night?'#9aad92':'#b8c9af');rect(420,382,140,7,night?'#4f6b59':'#668a70');
  for(const x of [448,476,504,532])s.line(x,368,x,380,night?'#56715f':'#6e8e76',1.5);
  rect(463,435,43,106,night?'#877a5e':'#9c805b');s.line(484,438,484,538,night?'#706951':'#8b704f',2);s.ellipse(497,490,3,3,'#dfcb91');
  // Weather vane is a separate layer; horizontal mirror can show the signed wind.
  group('vane-post',()=>{s.line(490,359,490,314,p.wood,4);s.ellipse(490,315,4,4,p.cream)});
  group('vane',()=>{s.line(464,323,516,323,p.wood,4);poly([[516,323],[504,315],[504,331]],p.cream);poly([[466,314],[478,318],[478,328],[466,333]],p.roof)});
 });
 group('foreground',()=>{
  path('M-60 558L0 558Q250 542 430 557T1000 551V636H-60Z',p.grass);
  for(const [x,y] of [[179,564],[317,560],[654,557],[799,568],[963,558]]){s.line(x,y,x-4,y-10,p.ground,2);s.line(x,y,x+5,y-8,p.ground,2)}
  for(const [x,y] of [[200,542],[345,530],[683,540]])s.ellipse(x,y,7,3,night?'#a0a68a':'#c4c6a8');
 });
 group('pukh',()=>{
  s.ellipse(30,554,28,7,night?'#4b654a':'#749759');
  s.ellipse(18,549,10,6,'#8a5f3a');s.ellipse(42,549,10,6,'#8a5f3a');
  s.ellipse(29,519,24,30,p.fur);s.ellipse(31,522,15,20,'#e3c08a');
  s.ellipse(12,470,8,8,p.fur);s.ellipse(42,470,8,8,p.fur);s.ellipse(28,485,21,20,p.fur);
  s.ellipse(34,491,11,8,'#e3c08a');s.ellipse(37,488,4,3,'#3d2f26');s.ellipse(21,480,2,2.5,'#3d2f26');s.ellipse(35,479,2,2.5,'#3d2f26');
  s.line(12,510,10,528,p.fur,10);
  group('paw',()=>{s.line(45,509,57,517,p.fur,10);s.ellipse(57,517,6,6,p.fur)});
 });
 group('slingshot',()=>{
  s.ellipse(67,554,27,6,night?'#4b654a':'#749759');
  s.line(64,548,64,516,'#a1764d',13);s.line(64,518,48,490,'#b88a5b',10);s.line(64,518,79,491,'#b88a5b',10);
  s.line(64,548,60,520,'#cba376',3);s.line(48,490,60,500,'#795f46',4);s.line(79,491,60,500,'#795f46',4);
 });
 group('projectile',()=>{
  rect(53,490,14,19,night?'#c3cda7':'#d8e2b9');s.ellipse(60,490,7,2,'#edf0d1');s.ellipse(60,509,7,2,'#a4b48e');
  poly([[61,493],[56,501],[60,501],[59,507],[65,498],[61,498]],'#d9a64d');
 });
 const inner=c.svg();
 return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${CANVAS.x} ${CANVAS.y} ${CANVAS.width} ${CANVAS.height}" role="img" aria-label="Пух у рогатки доставляет баночки в пять окон деревни" data-theme="${night?'night':'day'}"><title>Энергетос-баллиста · предложение сцены</title>${inner}</svg>`;
}

function reference(night){
 const cv=document.createElement('canvas');cv.width=1000;cv.height=600;
 const c=cv.getContext('2d'),s=makeS(c);c.fillStyle='#c1d5a3';c.fillRect(0,0,1000,600);
 c.save();c.translate(480,160);c.scale(2.2,2.2);
 for(let y=0;y<6;y++)for(let x=0;x<6;x++)s.tile(x,y,(x+y)%2?'#bfd39e':'#c6d9a9');
 B.drawBuilding(s,{id:'barn',type:'barn',x:0,y:0,w:2,h:2,level:1,jobs:[]});
 B.drawBuilding(s,{id:'house',type:'house',x:3,y:0,w:2,h:2,level:1,jobs:[]});
 for(let y=2;y<5;y++)for(let x=2;x<5;x++){s.tile(x,y,'#b39572','#a58965');s.plant((x-y)*36,(x+y+1)*18-2,'wheat',1,0)}
 c.restore();if(night){c.fillStyle='#152b4d66';c.fillRect(0,0,1000,600)}
 return cv.toDataURL('image/png');
}
export function render({night=false}={}){return {svg:pukhScene(night),reference:reference(night),world:WORLD,windows:WINDOWS};}
