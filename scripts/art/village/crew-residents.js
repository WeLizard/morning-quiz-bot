// Approved E28 resident source. Everyday crew figures retain crew.js geometry and palette.
// Foot anchor (0,0), CSS 40x60, common viewBox -18 -50 36 54.
import {FarmScene} from '/static/scene.js';
import {SvgCtx} from './svg_ctx.js';
const SH = '#41623530';
function krot(s) {
  s.ellipse(1.5,.6,9,2.8,SH);
  s.ellipse(-3,-1.2,3.2,1.8,'#4f4540'); s.ellipse(3,-1.2,3.2,1.8,'#4f4540');
  s.ellipse(0,-11,7.6,9.4,'#6f6259');
  s.poly([{x:-5.6,y:-15},{x:5.6,y:-15},{x:6.4,y:-5},{x:-6.4,y:-5}],'#e8a83a');
  s.line(-5.6,-11,5.6,-11,'#f4ede0',1.4);
  // No hard hat: original head lifted two units to keep a 32-unit silhouette.
  s.ellipse(0,-26,6.4,6,'#6f6259');
  s.ellipse(4.6,-24.6,2.8,2,'#e7a8b5'); s.ellipse(6.8,-24.4,1.1,1,'#c97a8a');
  s.ellipse(1.6,-27.2,.8,.7,'#2f3338');
  s.line(-5.6,-16,-8.6,-9,'#6f6259',2.6);
  s.line(5.4,-16,8,-9,'#6f6259',2.6);
}
function kaya(s) {
  s.ellipse(1.5,.6,8.6,2.8,SH);
  s.ellipse(-2.6,-1.2,2.8,1.8,'#8d8a84'); s.ellipse(2.6,-1.2,2.8,1.8,'#8d8a84');
  s.line(-4.6,-6,-10.6,-14,'#a9a7a0',2.4); s.line(-10.6,-14,-9,-19,'#a9a7a0',2.4);
  s.ellipse(0,-11,6.4,8.6,'#a9a7a0');
  s.poly([{x:-5,y:-16},{x:5,y:-16},{x:5.8,y:-4.6},{x:-5.8,y:-4.6}],'#8fae6f');
  s.ellipse(0,-23.4,6,5.6,'#a9a7a0');
  s.poly([{x:-5.4,y:-26},{x:-4.4,y:-32},{x:-1.4,y:-27.6}],'#a9a7a0');
  s.poly([{x:5.4,y:-26},{x:4.4,y:-32},{x:1.4,y:-27.6}],'#a9a7a0');
  s.poly([{x:-4.6,y:-26.4},{x:-4.2,y:-30.2},{x:-2.4,y:-27.6}],'#e7a8b5');
  s.line(-3,-27,-1.4,-25.6,'#7c7a74',1); s.line(0,-28,0,-26,'#7c7a74',1);
  s.ellipse(-2,-23.6,.8,1,'#3d4a3f'); s.ellipse(2.2,-23.6,.8,1,'#3d4a3f');
  s.ellipse(.2,-21.6,.9,.6,'#e7a8b5');
  // Same figure, shovel removed and both arms resting beside the apron.
  s.line(-4.6,-16,-7,-10,'#a9a7a0',2.4); s.line(4.6,-15,7,-9.6,'#a9a7a0',2.4);
}
function sonya(s) {
  const fur='#a9afbb', light='#f4f4f4', pink='#e0c4c9';
  s.ellipse(1.5,.6,8.6,2.8,SH);
  s.line(-4.6,-6,-10.2,-12,fur,2.5); s.line(-10.2,-12,-10.6,-17,fur,2.5);
  s.ellipse(-2.6,-1.2,2.8,1.8,'#878e9d'); s.ellipse(2.6,-1.2,2.8,1.8,'#878e9d');
  s.ellipse(0,-11,6.4,8.6,fur);
  s.poly([{x:-5,y:-16},{x:5,y:-16},{x:6,y:-4.6},{x:-6,y:-4.6}],'#8a94b5');
  s.poly([{x:-5.7,y:-18},{x:5.7,y:-18},{x:6.6,y:-12},{x:0,y:-9.8},{x:-6.6,y:-12}],'#c97a8a');
  s.line(-4.5,-13.1,0,-11.8,'#e0c4c9',.8); s.line(0,-11.8,4.5,-13.1,'#e0c4c9',.8);
  s.ellipse(0,-23.4,6,5.6,fur);
  s.poly([{x:-5.4,y:-26},{x:-4.4,y:-32},{x:-1.4,y:-27.6}],fur);
  s.poly([{x:5.4,y:-26},{x:4.4,y:-32},{x:1.4,y:-27.6}],fur);
  s.poly([{x:-4.6,y:-26.4},{x:-4.2,y:-30.2},{x:-2.4,y:-27.6}],pink);
  s.poly([{x:4.6,y:-26.4},{x:4.2,y:-30.2},{x:2.4,y:-27.6}],pink);
  s.ellipse(.1,-20.8,3.2,2,light);
  // Sleepy half-closed eyes and white muzzle from avatar_sonya.
  s.line(-3,-23.7,-2,-23.2,'#3b3a36',.8); s.line(-2,-23.2,-1,-23.7,'#3b3a36',.8);
  s.line(1.2,-23.7,2.2,-23.2,'#3b3a36',.8); s.line(2.2,-23.2,3.2,-23.7,'#3b3a36',.8);
  s.ellipse(.2,-21.7,.8,.5,'#d98f8a');
  s.line(-4.6,-16,-6.8,-10,fur,2.4);
  s.line(4.6,-15,7,-10.3,fur,2.4);
  // Small yarn ball, held by the near paw rather than a free-floating prop.
  s.ellipse(7,-10.5,2.7,2.7,'#e0c4c9');
  s.line(5.1,-11.5,8.3,-8.9,'#a85d6c',.6); s.line(5.4,-12.3,9,-10,'#a85d6c',.6);
  s.line(5,-10,7.5,-8.3,'#a85d6c',.6);
  s.ellipse(5.1,-9.5,1.3,1,fur);
}
export function crewResidents() {
  const out={};
  for (const [name,id,draw] of [['Механик Крот','krot',krot],['Кошка Кая','kaya',kaya],['Кошка Соня','sonya',sonya]]) {
    const c=new SvgCtx('e28crew-'+id),s=Object.create(FarmScene.prototype);
    s.c=c; s.time=0; s.motion=false; s.inStatic=true; s.shadowLevel=0;
    draw(s);
    out[name]=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="-18 -50 36 54" class="bc-art" aria-hidden="true" focusable="false">${c.svg()}</svg>`;
  }
  return out;
}

