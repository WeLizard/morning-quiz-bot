import {FarmScene} from '/static/scene.js';
import {SvgCtx} from './svg_ctx.js';
// Approved E28 art source. Feet sit on y=0; no badge/background or species invention.
// Igor / Mystery match icons.svg; Dasha / Oleg retain their minigame costumes.
function resident(id,draw){
 const c=new SvgCtx('e28'+id),s=Object.create(FarmScene.prototype);s.c=c;
 const E=(x,y,rx,ry,col)=>s.ellipse(x,y,rx,ry,col);
 const L=(x,y,a,b,col,w=1)=>s.line(x,y,a,b,col,w);
 const P=(col,pts)=>s.poly(pts.map(([x,y])=>({x,y})),col);
 const Q=(col,commands)=>{c.beginPath();for(const [op,...v] of commands)c[op](...v);c.closePath();c.fillStyle=col;c.fill();};
 draw({c,E,L,P,Q});
 return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="-18 -50 36 54" aria-hidden="true">${c.svg()}</svg>`;
}
export function tricksterResidents(){return {
 'Суслик Игорь':resident('igor',({E,L,P,Q})=>{
  // Ground squirrel: small round ears, stocky body, incisors and green scarf.
  E(-7,-11,4,7,'#b08a5f');E(0,-12,7.5,10,'#c39a68');E(1,-11,5,6.5,'#ead7b3');
  L(-3.8,-6,-4.5,-2.2,'#b08a5f',4);L(3.5,-6,4,-2.2,'#c39a68',4);
  E(-5,-1.1,3.5,1.1,'#b08a5f');E(4.5,-1.1,3.5,1.1,'#c39a68');
  E(-6.8,-29.6,2.7,2.9,'#b08a5f');E(6,-29.6,2.7,2.9,'#b08a5f');
  E(-6.8,-29.6,1.3,1.5,'#ead7b3');E(6,-29.6,1.3,1.5,'#ead7b3');
  E(0,-24.8,8.5,8.4,'#c39a68');E(1,-21.8,6,4.5,'#ead7b3');
  E(-3.7,-25.8,1.2,1.5,'#3b3a36');E(4,-25.8,1.2,1.5,'#3b3a36');
  E(-3.4,-26.3,.35,.4,'#fff');E(4.3,-26.3,.35,.4,'#fff');
  P('#7a5538',[[-1,-23.5],[2,-23.5],[.5,-21.8]]);L(.5,-21.8,.5,-20.5,'#7a5538',.6);
  P('#fff',[[-1,-20.8],[.2,-20.8],[.2,-18.7],[-1,-18.7]]);P('#fff',[[.7,-20.8],[1.9,-20.8],[1.9,-18.7],[.7,-18.7]]);
  Q('#7fa56a',[['moveTo',-6,-18],['quadraticCurveTo',0,-15.5,6,-18],['lineTo',4,-15],['lineTo',-4,-15]]);
  P('#6b9058',[[3,-16],[5,-16],[6,-10],[2,-12]]);
  L(-6,-15,-5,-10,'#b08a5f',3.5);L(6,-15,5,-10,'#c39a68',3.5);
  // A seed keeper's little walnut, firmly held between paws.
  E(0,-10,3,3.5,'#a7774d');L(0,-12,0,-8,'#7a5538',.6);
  E(-2.9,-9.3,2.2,1.7,'#c39a68');E(3.1,-9.3,2.2,1.7,'#c39a68');
 }),
 'Неведома Зверушка':resident('mystery',({E,L,P,Q})=>{
  // Only the avatar's lavender unknown creature: uneven gaze and two tufts.
  // Rounded limbs give a complete body without defining a new animal species.
  E(-4.2,-3.5,2.6,3.5,'#9d88c4');E(4.2,-3.5,2.6,3.5,'#b9a6d8');
  E(-4.8,-1.1,3.3,1.1,'#9d88c4');E(4.8,-1.1,3.3,1.1,'#b9a6d8');
  E(0,-12,7.4,9.5,'#b9a6d8');E(.6,-10.8,4.6,5.8,'#d9ccee');
  L(-6,-15,-8,-9,'#9d88c4',3.5);E(-8,-8.5,2.2,2.4,'#b9a6d8');
  L(6,-15,8.5,-18,'#b9a6d8',3.5);E(9,-19,2.3,2.6,'#b9a6d8');
  P('#9d88c4',[[-6,-28],[-7,-34],[-2,-30]]);P('#9d88c4',[[6,-28],[7,-34],[2,-30]]);
  E(0,-25,8.4,8.7,'#b9a6d8');E(0,-21.5,6,4.6,'#d9ccee');
  E(-3.8,-26,2.9,3.2,'#fff');E(3.8,-26,2.9,3.2,'#fff');
  E(-3.1,-25.5,1.4,1.5,'#3b3550');E(3.2,-26.5,1.6,1.8,'#3b3550');
  E(-2.7,-26,.45,.5,'#fff');E(3.7,-27.1,.5,.55,'#fff');
  L(-1.7,-20.6,0,-19.8,'#6b5a8e',.7);L(0,-19.8,1.7,-20.6,'#6b5a8e',.7);
  // Tiny question motif is vector geometry rather than a font dependency.
  L(-.7,-30.3,.4,-30.8,'#7e6aa8',.7);L(.4,-30.8,1,-30,'#7e6aa8',.7);L(1,-30,0,-29.1,'#7e6aa8',.7);E(0,-28,.4,.4,'#7e6aa8');
 }),
 'Лиса Даша':resident('dasha',({E,L,P,Q})=>{
  Q('#d97849',[['moveTo',-4,-4],['bezierCurveTo',-16,-3,-18,-13,-13,-20],['quadraticCurveTo',-8,-24,-6,-20],['bezierCurveTo',-13,-14,-9,-10,-3,-12]]);
  Q('#fff0d5',[['moveTo',-13,-20],['quadraticCurveTo',-9,-24,-6,-20],['quadraticCurveTo',-11,-16,-11,-13],['lineTo',-15,-14],['quadraticCurveTo',-15,-17,-13,-20]]);
  L(-3.3,-7,-4,-2,'#c96f43',4);L(4,-7,4.7,-2,'#d7834e',4);
  E(-4.5,-1.1,3,1.1,'#98563d');E(5,-1.1,3,1.1,'#98563d');
  E(0,-12.5,6.8,9,'#db824b');
  Q('#f4e8c5',[['moveTo',-4,-19],['quadraticCurveTo',0,-17,4,-19],['lineTo',5.5,-5],['quadraticCurveTo',0,-3.5,-5.5,-5]]);
  L(-3,-8,3.5,-8,'#8eac7b',.8);
  L(-5.5,-17,-7,-10,'#c96f43',3.4);L(5.5,-17,8,-11,'#db824b',3.4);E(-7,-9,2,2,'#d7834e');E(8,-10,2,2,'#d7834e');
  P('#d57a47',[[-7,-25],[-7.5,-36],[-2,-30]]);P('#d57a47',[[7,-25],[7.5,-36],[2,-30]]);
  P('#efb28b',[[-6,-29],[-6.3,-33.5],[-3.5,-30]]);P('#efb28b',[[6,-29],[6.3,-33.5],[3.5,-30]]);
  E(0,-26,8,7.8,'#ed9b58');
  Q('#fff1d9',[['moveTo',-7.5,-26],['quadraticCurveTo',-3,-25,0,-20],['quadraticCurveTo',-7,-20,-7.5,-26]]);
  Q('#fff1d9',[['moveTo',7.5,-26],['quadraticCurveTo',3,-25,0,-20],['quadraticCurveTo',7,-20,7.5,-26]]);
  E(-3.5,-27,1,1.4,'#4b3831');E(3.5,-27,1,1.4,'#4b3831');
  L(-4.6,-29,-2.5,-29.5,'#603f35',.6);L(2.5,-29.5,4.6,-29,'#603f35',.6);
  P('#5d3e37',[[-1.5,-23],[1.5,-23],[0,-21.5]]);L(0,-21.5,0,-20.4,'#7d4b3d',.6);
  P('#688e7a',[[-5,-19],[0,-17.7],[5,-19],[1,-15.5],[-1,-15.5]]);
  P('#779c86',[[0,-16],[2,-15],[2,-10],[-1,-12]]);E(0,-16,1.2,1.1,'#a6bc91');
 }),
 'Петух Олег':resident('oleg',({E,L,P,Q})=>{
  L(-2,-7,-3,-.8,'#dba556',1.5);L(4,-7,5,-.8,'#dba556',1.5);
  for(const x of [-3,5]){L(x,-.8,x-2,-.4,'#dba556',1);L(x,-.8,x+2,-.4,'#dba556',1);}
  Q('#6fa483',[['moveTo',-5,-12],['bezierCurveTo',-15,-17,-15,-25,-11,-29],['quadraticCurveTo',-11,-21,-3,-17]]);
  Q('#88b591',[['moveTo',-5,-10],['bezierCurveTo',-16,-11,-17,-17,-16,-22],['quadraticCurveTo',-11,-16,-3,-15]]);
  Q('#dd9466',[['moveTo',-3,-15],['quadraticCurveTo',-10,-27,-6,-30],['quadraticCurveTo',-4,-24,-1,-18]]);
  E(0,-14,8,7.6,'#f4eed6');
  Q('#dc8e64',[['moveTo',-2,-21],['quadraticCurveTo',4,-23,7,-19],['lineTo',7,-8],['quadraticCurveTo',2,-5,-2,-8]]);
  L(4,-17,5,-8,'#c87a52',.6);E(4.7,-12.8,.6,.6,'#f6d98c');E(5,-10,.6,.6,'#f6d98c');
  Q('#f7f1dc',[['moveTo',2,-20],['lineTo',4,-28],['lineTo',9,-27],['lineTo',8,-19],['lineTo',5,-16]]);
  E(4,-33,1.9,2.5,'#de6b61');E(6.5,-34,2,2.6,'#de6b61');E(9,-33,1.8,2.2,'#de6b61');
  E(6.5,-28.7,5.2,5.6,'#f8f2df');E(10.5,-24,1.1,2,'#de6b61');
  P('#edb85e',[[10.8,-29],[15,-27.5],[10.8,-26.5]]);P('#d99c48',[[10.8,-26.5],[14,-27],[11,-25.5]]);
  E(8,-29.8,.9,1.1,'#3d4b3e');E(8.3,-30.2,.3,.35,'#fff');
  E(-1,-13,5,4.5,'#ece0bf');L(-3,-12,1,-11,'#ddcfa8',.6);
  L(2,-12,10,-17,'#a87b52',1);E(10.5,-17.5,1.3,1.3,'#e9c58c');
 })
};}
