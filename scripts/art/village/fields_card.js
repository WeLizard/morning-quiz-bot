// E17 candidate only. The tractor is the farm's own vehicle(), recorded as vector paths.
// No runtime file is changed by this generator; build_fields_card.py produces review artifacts.
import {makeS, B} from './common.js';
import {SvgCtx} from './svg_ctx.js';
import {vehicle} from '/static/scene_expansion.js';

// vehicle() uses uniform positive rounded rectangles; keep the shared recorder unchanged.
class CardCtx extends SvgCtx {
  roundRect(x,y,w,h,r=0){
    r=Math.min(Number(r),w/2,h/2);
    this.moveTo(x+r,y);this.lineTo(x+w-r,y);this.quadraticCurveTo(x+w,y,x+w,y+r);
    this.lineTo(x+w,y+h-r);this.quadraticCurveTo(x+w,y+h,x+w-r,y+h);
    this.lineTo(x+r,y+h);this.quadraticCurveTo(x,y+h,x,y+h-r);
    this.lineTo(x,y+r);this.quadraticCurveTo(x,y,x+r,y);this.closePath();
  }
}

export function fieldsCard(){
  const c=new CardCtx('fields'),s=makeS(c);
  const poly=(pts,col)=>s.poly(pts.map(([x,y])=>({x,y})),col);
  // Same 160×68 composition, muted sky and alternating crop strips as the destination cards.
  poly([[0,0],[160,0],[160,68],[0,68]],'#dce8c9');
  s.ellipse(132,13,8,8,'#f7d579');
  poly([[0,32],[35,27],[85,26],[125,29],[160,26],[160,68],[0,68]],'#a9c597');
  const strips=[[-8,30,34,52,'#dcbf6c'],[30,67,52,72,'#9fbf6e'],
    [67,104,72,92,'#e3c873'],[104,140,92,113,'#a8c475'],[140,171,113,136,'#dcbf6c']];
  for(const [a,b,ta,tb,col] of strips){
    poly([[ta,32],[tb,31],[b,68],[a,68]],col);
    s.line((ta+tb)/2,34,(a+b)/2,66,col==='#9fbf6e'||col==='#a8c475'?'#86a95e':'#c4a14f',1);
  }
  s.line(0,36,160,34,'#9e8a60',1.4);
  for(const x of [14,44,74,134,151])s.line(x,32,x,39,'#a89063',1.8);
  // Wheels sit on the field; no floating exhaust particles or separately invented tractor style.
  c.save();c.translate(105,55);c.scale(.67,.67);vehicle(s,0,0,'tractor',false);c.restore();
  const inner=c.svg();
  return {inner,svg:`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 68" role="img" aria-label="Поля за околицей"><title>Поля за околицей</title>${inner}</svg>`};
}

function reference(){
  const cv=document.createElement('canvas');cv.width=640;cv.height=340;
  const c=cv.getContext('2d'),s=makeS(c);
  c.fillStyle='#c1d5a3';c.fillRect(0,0,640,340);
  c.save();c.translate(290,78);c.scale(1.15,1.15);
  for(let y=0;y<6;y++)for(let x=0;x<6;x++)s.tile(x,y,(x+y)%2?'#bfd39e':'#c6d9a9');
  B.drawBuilding(s,{id:'barn',type:'barn',x:0,y:0,w:2,h:2,level:1,jobs:[]});
  for(let y=2;y<5;y++)for(let x=2;x<5;x++){
    s.tile(x,y,'#b39572','#a58965');
    s.plant((x-y)*36,(x+y+1)*18-2,'wheat',1,0);
  }
  vehicle(s,100,120,'tractor',false);c.restore();
  return cv.toDataURL('image/png');
}

export async function render(){return {...fieldsCard(),reference:reference()};}
