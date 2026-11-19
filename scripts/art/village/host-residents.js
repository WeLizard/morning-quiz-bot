// Approved E28 resident source. Native farm primitives; full bodies, feet at y=0.
import {FarmScene} from '/static/scene.js';
import {SvgCtx} from './svg_ctx.js';

const shadow = '#41623530';
const poly = (s, points, fill) => s.poly(points.map(([x,y]) => ({x,y})), fill);

function filinych(s) {
  s.ellipse(1,.6,8.6,2.6,shadow);
  // Small exposed talons and a rounded feathered body, not a clothed humanoid.
  s.line(-3,-4,-3,-1.1,'#c78f4d',1.9);
  s.line(3,-4,3,-1.1,'#c78f4d',1.9);
  s.line(-5,-.8,-1,-.8,'#b47d43',1.3);
  s.line(1,-.8,5,-.8,'#b47d43',1.3);
  s.ellipse(0,-12,8.4,10.7,'#a58b65');
  s.ellipse(1,-11.4,5.7,8.5,'#d5c49c');
  s.ellipse(-6.5,-13.7,2.7,7,'#947950');
  s.ellipse(6.5,-13.7,2.1,6.8,'#a58b65');
  s.line(-7.2,-13,-6.1,-8,'#b69c73',.8);
  s.line(-5.8,-14,-4.9,-9,'#b69c73',.8);
  for (const [x,y] of [[-.9,-15],[2.5,-14],[-.2,-10],[2.6,-9],[1,-6]])
    poly(s,[[x-.8,y-.5],[x+.8,y-.5],[x,y+1]],'#b7a077');
  s.ellipse(.3,-24.9,8.2,7.4,'#a58b65');
  poly(s,[[-7.3,-27],[-7.6,-33.8],[-1.8,-30.2]],'#a58b65');
  poly(s,[[3,-30.4],[7.7,-33.2],[7.9,-26.7]],'#a58b65');
  s.ellipse(-3,-25.2,4.5,5,'#ebe1bd');
  s.ellipse(4.1,-25.2,4.1,4.8,'#ebe1bd');
  s.ellipse(-2.2,-25.2,2.1,2.6,'#344e40');
  s.ellipse(4.7,-25.2,2,2.6,'#344e40');
  s.ellipse(-1.6,-26.1,.65,.65,'#fff');
  s.ellipse(5.3,-26.1,.65,.65,'#fff');
  poly(s,[[.3,-22.2],[3.7,-22.2],[2.2,-18.7]],'#c78f4d');
}

function agata(s, c) {
  s.ellipse(1,.6,8.3,2.6,shadow);
  s.line(-2.6,-6,-2.6,-1.5,'#f1cfae',2.4);
  s.line(2.7,-6,2.7,-1.5,'#f1cfae',2.4);
  s.ellipse(-2.3,-1,2.7,1.1,'#876750');
  s.ellipse(3.1,-1,2.7,1.1,'#876750');
  s.line(-4.6,-19,-7.1,-11.4,'#c9747c',3.1);
  s.ellipse(-7,-10.6,1.55,1.8,'#f1cfae');
  s.ellipse(0,-19,5.5,4.8,'#c9747c');
  poly(s,[[-4.8,-18],[4.8,-18],[7.5,-4.4],[3.5,-3.7],[-3.6,-3.7],[-7.1,-4.6]],'#c9747c');
  // Cream apron echoes the warm portrait palette, with a generous simple silhouette.
  poly(s,[[-3.5,-17.8],[3.7,-17.8],[5.2,-5.4],[-5,-5.4]],'#f3e3d3');
  s.line(-3.4,-16.6,3.6,-16.6,'#e4c8aa',1);
  poly(s,[[-1.9,-11.6],[2.8,-11.6],[2.4,-8.5],[-1.4,-8.5]],'#e4c8aa');
  s.line(4.7,-19,7.1,-12.1,'#c9747c',3.1);
  s.ellipse(7.1,-11.3,1.55,1.8,'#f1cfae');
  s.ellipse(.7,-26.2,6.1,6.7,'#f1cfae');
  // Rose cap/scarf and its side tails follow avatar_agata's recognizable contour.
  c.beginPath(); c.moveTo(-5.6,-26.7);
  c.bezierCurveTo(-6.6,-37.4,7.6,-37.4,7,-26.7);
  c.bezierCurveTo(3.7,-32.9,-2.5,-32.9,-5.6,-26.7);
  c.closePath(); c.fillStyle='#c9747c'; c.fill();
  poly(s,[[-5.6,-27.4],[-7.1,-20.6],[-2.9,-22.8]],'#c9747c');
  poly(s,[[6.7,-27.4],[8.1,-20.8],[4.6,-22.8]],'#c9747c');
  s.ellipse(.5,-33.4,1,1,'#f3d9a6');
  s.ellipse(-1.8,-26.3,.75,.85,'#3b3a36');
  s.ellipse(3.5,-26.3,.75,.85,'#3b3a36');
  s.ellipse(-3.1,-24.1,1.35,.8,'#f0a9a0');
  s.ellipse(4.8,-24.1,1.3,.8,'#f0a9a0');
  c.beginPath(); c.moveTo(-.5,-22.7); c.quadraticCurveTo(1.4,-21.2,3.2,-22.8);
  c.strokeStyle='#a5605a'; c.lineWidth=.7; c.lineCap='round'; c.stroke();
}

function hedgehog(s) {
  s.ellipse(1,.6,8.5,2.6,shadow);
  s.ellipse(-3.4,-1.3,2.7,1.3,'#8b7961');
  s.ellipse(3.4,-1.3,2.7,1.3,'#8b7961');
  // Spines run down the back and remain visible beside the uniform.
  poly(s,[[-7,-5],[-10,-9],[-8.5,-12],[-11,-17],[-8.7,-18],[-10,-23],[-6.5,-22],[-7,-28],[-3.6,-25],[-2,-31],[2,-26],[5.7,-29],[6.2,-22],[8,-19],[6,-7]],'#8b7961');
  s.ellipse(-.5,-12,7,9,'#e3c9a3');
  s.ellipse(0,-12,6.5,8,'#5f7fa6');
  s.ellipse(1.1,-24,6.3,6.5,'#e3c9a3');
  s.ellipse(5.7,-22.8,4.3,2.7,'#e8d3b3');
  s.ellipse(9.4,-23.1,1.25,1.25,'#3b3a36');
  s.ellipse(3.2,-25.7,.9,1.05,'#3b3a36');
  s.ellipse(-3.6,-26.4,1.8,2.1,'#e3c9a3');
  s.ellipse(-3.6,-26.4,.9,1.1,'#c7aa85');
  // Blue postal cap and gold badge, taken directly from the existing icon.
  s.ellipse(.2,-29.1,7.2,2,'#4c6c92');
  s.ellipse(.2,-30.3,6.5,2.7,'#5f7fa6');
  s.ellipse(4.1,-28.7,4.7,1,'#4c6c92');
  s.ellipse(2,-30.5,.9,.9,'#f3d27a');
  s.line(4,-18.6,-4,-7.5,'#b18c60',1.6);
  s.line(4.8,-17.6,7.4,-11.1,'#5f7fa6',2.8);
  s.ellipse(7.4,-10.6,1.6,1.8,'#e3c9a3');
  poly(s,[[-7.6,-12.3],[-1.2,-12.3],[-.5,-5.8],[-7.7,-5.8]],'#9d7753');
  poly(s,[[-7.6,-12.4],[-1.2,-12.4],[-2,-9.5],[-7.4,-9.5]],'#b18c60');
  // One envelope in the satchel: visible at close scale, no lettering to blur.
  poly(s,[[-6.8,-13.7],[-2.1,-13.7],[-2.1,-10.7],[-6.8,-10.7]],'#f3e8d1');
  s.line(-6.6,-13.4,-4.5,-11.9,'#baaa88',.55);
  s.line(-4.5,-11.9,-2.3,-13.4,'#baaa88',.55);
}

export function hostResidents() {
  const out = {};
  for (const [name, draw] of [['Филиныч',filinych],['Агата',agata],['Почтальон Ёж',hedgehog]]) {
    const c = new SvgCtx('host'), s = Object.create(FarmScene.prototype);
    s.c=c; s.time=0; s.motion=false; s.inStatic=true; s.shadowLevel=0;
    draw(s,c);
    out[name]=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="-18 -50 36 54" class="bc-art" aria-hidden="true" focusable="false">${c.svg()}</svg>`;
  }
  return out;
}
export {hedgehog};   // reused by fest_characters.js (the New Year postman)
