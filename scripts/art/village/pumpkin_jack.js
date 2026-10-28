// Jack the ghost rider: a separate, clickable live character, never part of the map raster.
// Palette and drawing language follow player.js / merchant.js and the farm's pumpkin crop.
import {FarmScene} from '/static/scene.js';
import {SvgCtx} from './svg_ctx.js';

export const JACK_BOX=[-49,-114,100,124]; // farm px; hoof anchor is 0,0

export function jackSvg(){
  const c=new SvgCtx('jack'),s=Object.create(FarmScene.prototype);s.c=c;
  const C={horse:'#5f7f9a',far:'#454b57',light:'#7e9db5',mist:'#abc9c7',cloak:'#454b57',fold:'#4f6b78',
    rein:'#8a6c4c',gold:'#e2b04a',pumpkin:'#d68e45',rib:'#e5a451',shine:'#ffe7a0'};
  const poly=(p,col)=>s.poly(p.map(([x,y])=>({x,y})),col);
  const curve=(points,col)=>{c.beginPath();for(const [op,...a] of points)c[op](...a);c.closePath();c.fillStyle=col;c.fill()};
  c.group('jack-body');
  // Ground haze is low and follows the hoof line, leaving a clear grounded silhouette.
  s.ellipse(0,2,34,7,'rgba(171,201,199,.12)');
  // Tail, far legs, then body. No detached wisps that could read as broken limbs.
  curve([['moveTo',-22,-40],['bezierCurveTo',-38,-42,-31,-25,-45,-22],['bezierCurveTo',-37,-20,-26,-25,-25,-32],['lineTo',-19,-34]],C.far);
  curve([['moveTo',-28,-36],['bezierCurveTo',-32,-32,-33,-26,-40,-24],['bezierCurveTo',-30,-26,-27,-30,-26,-35]],C.mist);
  poly([[-20,-31],[-13,-29],[-17,-16],[-12,-4],[-17,-3],[-23,-15]],C.far);
  poly([[12,-31],[19,-31],[23,-18],[19,-3],[14,-3],[17,-18]],C.far);
  s.ellipse(-15,-3,5,2,C.light);s.ellipse(17,-3,4,2,C.light);
  s.ellipse(-2,-34,25,13,C.horse);s.ellipse(-18,-35,10,12,C.horse);
  s.ellipse(-7,-38,18,6,C.light);
  // Long neck and forward muzzle are readable even when the figure is 60 px wide.
  curve([['moveTo',11,-38],['lineTo',17,-60],['quadraticCurveTo',18,-68,26,-67],
    ['lineTo',31,-60],['lineTo',28,-43],['quadraticCurveTo',25,-30,15,-27]],C.horse);
  poly([[21,-65],[21,-76],[26,-68],[29,-67],[32,-76],[33,-63]],C.horse);
  poly([[23,-68],[23,-72],[25,-67]],C.mist);
  curve([['moveTo',22,-66],['quadraticCurveTo',30,-70,33,-61],['lineTo',42,-55],
    ['quadraticCurveTo',44,-50,39,-48],['lineTo',29,-51],['lineTo',21,-58]],C.horse);
  poly([[34,-57],[42,-55],[42,-51],[37,-51],[31,-55]],C.light);
  s.ellipse(29,-61,1.8,1.4,C.shine);s.ellipse(40,-53,.8,.7,C.far);
  // Pale mane is attached all the way along the neck, same muted cyan as the farm glass.
  poly([[22,-69],[16,-65],[12,-56],[15,-57],[10,-47],[14,-49],[12,-39],[17,-43],[20,-58]],C.mist);
  poly([[20,-65],[17,-58],[18,-57],[15,-49],[18,-52],[21,-60]],C.light);
  // Near legs and solid hooves; the rider's leg is painted later over the saddle.
  poly([[-18,-30],[-9,-28],[-7,-16],[-12,-2],[-17,-2],[-13,-17]],C.horse);
  poly([[13,-30],[20,-29],[18,-16],[27,-1],[21,0],[12,-14]],C.horse);
  s.line(-14,-13,-16,-3,C.mist,1.3);s.line(18,-12,24,-2,C.mist,1.3);
  s.ellipse(-14,0,5,2,C.light);s.ellipse(25,0,5,2,C.light);
  // Saddle cloth and the small tied sack identify a visitor who brings gifts.
  poly([[-15,-45],[7,-44],[10,-30],[-13,-29]],'#6f5a46');
  s.line(-13,-30,8,-31,C.gold,1.2);
  s.ellipse(-19,-38,7,8,'#8a6c4c');s.ellipse(-19,-35,6,5,'#b48f66');
  s.line(-24,-41,-14,-41,C.gold,1.2);s.line(-19,-43,-19,-31,C.gold,1);
  // Cloak is one continuous attached shape, with a calm, slightly ragged hem.
  curve([['moveTo',-8,-80],['quadraticCurveTo',-20,-72,-21,-61],['quadraticCurveTo',-25,-49,-37,-44],
    ['lineTo',-29,-42],['lineTo',-31,-38],['lineTo',-21,-42],['lineTo',-16,-39],['lineTo',-11,-47],
    ['lineTo',9,-48],['lineTo',6,-75],['quadraticCurveTo',1,-82,-8,-80]],C.cloak);
  poly([[-9,-77],[-15,-60],[-23,-47],[-15,-50],[-5,-63]],C.fold);
  s.line(-13,-69,-18,-55,C.light,1.1);
  // Near boot hangs beside the horse, not through its chest.
  poly([[-3,-52],[5,-50],[10,-39],[7,-24],[2,-24],[3,-38],[-7,-45]],C.fold);
  poly([[2,-28],[8,-27],[8,-23],[15,-21],[15,-18],[2,-19]],C.far);
  // Arm, glove and reins reach the horse's bridle in one connected line.
  s.line(3,-72,12,-59,C.fold,6);s.line(12,-59,21,-57,C.fold,4);
  s.ellipse(21,-57,2.4,2.4,C.light);
  c.beginPath();c.moveTo(21,-57);c.quadraticCurveTo(24,-47,36,-52);c.strokeStyle=C.rein;c.lineWidth=1.2;c.stroke();
  s.line(33,-60,36,-51,C.rein,1.1);
  // The head is a carved farm pumpkin. Orange is the single warm focal point.
  s.ellipse(-1,-86,13,11,C.pumpkin);s.ellipse(-5,-86,5,10.8,C.rib);
  s.ellipse(4,-86,4,10.2,'#c98440');
  s.line(-1,-97,1,-103,'#6d8750',2.6);
  poly([[-10,-87],[-3,-86],[-6,-92]],'#68492f');poly([[2,-86],[9,-88],[5,-92]],'#68492f');
  poly([[-8,-83],[-5,-80],[-2,-81],[0,-79],[3,-81],[7,-84],[4,-77],[-2,-76],[-6,-79]],'#68492f');
  poly([[-10,-77],[-5,-74],[3,-74],[8,-78],[6,-71],[-7,-71]],C.fold);
  s.ellipse(2,-74,1.6,1.6,C.gold);
  c.end();
  c.group('jack-glow');
  s.ellipse(-1,-86,18,15,'rgba(255,200,95,.07)');
  poly([[-10,-87],[-3,-86],[-6,-92]],C.shine);poly([[2,-86],[9,-88],[5,-92]],C.shine);
  poly([[-8,-83],[-5,-80],[-2,-81],[0,-79],[3,-81],[7,-84],[4,-77],[-2,-76],[-6,-79]],C.shine);
  s.ellipse(29,-61,2,1.5,C.shine);
  s.line(-14,-1,-10,-1,'rgba(171,201,199,.7)',1.3);s.line(22,0,28,0,'rgba(171,201,199,.7)',1.3);
  c.end();
  return `<svg xmlns="http://www.w3.org/2000/svg" class="jack-art" viewBox="${JACK_BOX.join(' ')}" aria-hidden="true" focusable="false">${c.svg()}</svg>`;
}

export function placeJack(K,V){
  // Occupied footprint covers the complete 88px horse silhouette, including its tail.
  // Search is deterministic, does not disable paths/buttons, and shares taken places with the pumpkins.
  const size=1,footprint=1.4*size;
  const at=K.place({w:footprint,d:footprint,h:110*size,near:[V.plaza[0]-1,V.plaza[3]],
    area:[V.plaza[0]-8,V.plaza[1]-6,V.plaza[2]+10,V.plaza[3]+12],button:60,cover:.2,margin:.1,what:'Jack the ghost rider'});
  if(!at)return null;
  const tile=[at[0]+footprint/2,at[1]+footprint/2],p=V.P(...tile),[a,, ,d,e,f]=V.matrix;
  const foot=[a*p.x+e,d*p.y+f].map(v=>+v.toFixed(2));
  const box=[foot[0]+JACK_BOX[0]*a*size,foot[1]+JACK_BOX[1]*d*size,JACK_BOX[2]*a*size,JACK_BOX[3]*d*size].map(v=>+v.toFixed(2));
  // Closest point on the existing walk graph with a clear straight approach to the horse.
  const approaches=[];
  for(const [index,[ax,ay,bx,by]] of (V.walk||[]).entries()){
    const dx=bx-ax,dy=by-ay,t=Math.max(0,Math.min(1,((tile[0]-ax)*dx+(tile[1]-ay)*dy)/(dx*dx+dy*dy||1)));
    const q=[ax+t*dx,ay+t*dy],distance=Math.hypot(q[0]-tile[0],q[1]-tile[1]);
    let clear=true;
    for(let u=0;u<=1;u+=.1)if(!V.free(tile[0]+(q[0]-tile[0])*u,tile[1]+(q[1]-tile[1])*u)){clear=false;break;}
    if(clear)approaches.push({index,t,tile:q,distance});
  }
  approaches.sort((x,y)=>x.distance-y.distance||x.index-y.index);
  const nearest=approaches[0],qp=nearest&&V.P(...nearest.tile);
  const approach=nearest?{world:[a*qp.x+e,d*qp.y+f].map(v=>+v.toFixed(2)),tile:nearest.tile.map(v=>+v.toFixed(4)),edge_index:nearest.index,edge_t:+nearest.t.toFixed(6)}:null;
  if(!approach)K.problems.push('pumpkin_night: Jack has no clear graph approach');
  return {svg:jackSvg(),foot,tile,box,scale:size,approach,footprint:[...at,at[0]+footprint,at[1]+footprint],
    viewBox:JACK_BOX,min_hit_css_px:44,position_contract:'world units 2400x1800; separate live button; foot at local 0,0',
    visibility:'pumpkin_night 17:00–05:00 Moscow; independent of manual theme/decor; server controls daily gift'};
}

export function pumpkinCandy(){
  const c=new SvgCtx('pumpkin-candy'),s=Object.create(FarmScene.prototype);s.c=c;
  const poly=(p,col)=>s.poly(p.map(([x,y])=>({x,y})),col);
  // Chunky twisted wrapper stays legible in 24px inventory cells.
  poly([[13,15],[5,10],[3,17],[5,20],[3,25],[6,30],[14,25]],'#b48f66');
  poly([[27,15],[35,10],[37,17],[35,20],[37,25],[34,30],[26,25]],'#b48f66');
  poly([[12,17],[6,13],[5,18],[8,20],[5,24],[7,27],[14,24]],'#e8c25a');
  poly([[28,17],[34,13],[35,18],[32,20],[35,24],[33,27],[26,24]],'#e8c25a');
  s.ellipse(20,20,11,10,'#d68e45');s.ellipse(16.7,20,4,9.7,'#e5a451');
  s.ellipse(23.7,20,3.5,9.4,'#c98440');s.line(20,10,21,6,'#6d8750',2.6);
  poly([[13.5,18.5],[18,18],[15.5,14.8]],'#68492f');poly([[22,18],[26.5,18.5],[24.5,14.8]],'#68492f');
  poly([[14,22],[18,23],[20,21.5],[22,23],[26,22],[24,26],[20,27],[16,26]],'#ffe7a0');
  const inner=c.svg();
  return {svg:`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">${inner}</svg>`,
    symbol:`<symbol xmlns="http://www.w3.org/2000/svg" id="pumpkin_candy" viewBox="0 0 40 40">${inner}</symbol>`};
}

export function render(){return {svg:jackSvg(),viewBox:JACK_BOX,candy:pumpkinCandy()};}
