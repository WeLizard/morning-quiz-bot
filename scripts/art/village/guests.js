// Village guests (app.js VILLAGE_VISITORS and the easter-egg VILLAGE_EGGS): drawn figures in the residents' style
// (host-residents.js: native farm primitives, flat fills, full bodies, feet at y=0) instead of emoji in a round plate.
// Keys are the guest ids of app.js. The Bogatyr is the druzhinnik of the owner's soulslike game «Богатырь»: steel
// shishak with an aventail, a worn red cloak, dark mail, a round shield and a sword, in a darker palette than the village.
import {FarmScene} from '/static/scene.js';
import {SvgCtx} from './svg_ctx.js';

export const GUEST_BOX = '-18 -50 36 54';   // as the residents: the guest stands where a resident would
const shadow = '#41623530';
const poly = (s, points, fill) => s.poly(points.map(([x, y]) => ({x, y})), fill);
const curve = (c, pts, fill) => {   // closed path of [x, y] / ['q', cx, cy, x, y] / ['c', ...] steps
  c.beginPath(); c.moveTo(pts[0][0], pts[0][1]);
  for (const p of pts.slice(1)) {
    if (p[0] === 'q') c.quadraticCurveTo(p[1], p[2], p[3], p[4]);
    else if (p[0] === 'c') c.bezierCurveTo(p[1], p[2], p[3], p[4], p[5], p[6]);
    else c.lineTo(p[0], p[1]);
  }
  c.closePath(); c.fillStyle = fill; c.fill();
};
const eyes = (s, x, y, gap = 4.6, col = '#3b3a36') => { s.ellipse(x, y, .75, .85, col); s.ellipse(x + gap, y, .75, .85, col) };
const cheeks = (s, x, y, gap = 6.8) => { s.ellipse(x, y, 1.3, .8, '#f0a9a0'); s.ellipse(x + gap, y, 1.3, .8, '#f0a9a0') };
const smile = (c, x, y, w = 3.6, col = '#a5605a') => {
  c.beginPath(); c.moveTo(x - w / 2, y); c.quadraticCurveTo(x, y + 1.4, x + w / 2, y); c.strokeStyle = col; c.lineWidth = .7; c.lineCap = 'round'; c.stroke();
};
// a person's legs and boots: hip height, the boots' colour
const legs = (s, col, boot, top = 7, w = 2.4) => {
  s.line(-2.6, -top, -2.6, -1.5, col, w); s.line(2.7, -top, 2.7, -1.5, col, w);
  s.ellipse(-2.4, -1, 2.7, 1.2, boot); s.ellipse(3, -1, 2.7, 1.2, boot);
};

// ---------- the daily guests ----------

function bogatyr(s, c) {
  const steel = '#8e979f', steelLight = '#c3cad0', mail = '#4c535b', mailDark = '#363b41', cloak = '#7c2b27', cloakDark = '#5a1f1c';
  s.ellipse(1, .6, 9.5, 2.8, shadow);
  // the cloak behind him, worn to rags at the hem
  poly(s, [[-6.2, -27], [6.4, -27], [8.6, -9], [7.6, -5.6], [6.2, -7.4], [4.6, -4.4], [2.6, -6.6], [.4, -3.8], [-1.6, -6.2], [-3.6, -4], [-5.4, -6.8], [-7.4, -4.6], [-8.6, -9]], cloakDark);
  poly(s, [[-6.2, -27], [-2.4, -27], [-4.4, -8], [-5.4, -6.8], [-7.4, -4.6], [-8.6, -9]], cloak);
  legs(s, '#2f3236', '#24272a', 9, 2.8);
  // mail coat to the knees, a leather belt
  poly(s, [[-5.6, -25], [5.6, -25], [7, -8.4], [-7, -8.4]], mail);
  for (let y = -22; y > -9; y -= 2.6) s.line(-5.8 + (y + 25) * .05, y, 5.8 - (y + 25) * .05, y, mailDark, .5);
  poly(s, [[-6.4, -15.4], [6.4, -15.4], [6.6, -13.2], [-6.6, -13.2]], '#4a3627');
  s.ellipse(.6, -14.3, 1.1, .9, '#b09a6a');
  // the sword arm and the sword, point down
  s.line(5, -23.6, 7.4, -15.4, mail, 3.2);
  s.ellipse(7.5, -14.6, 1.6, 1.7, '#3a2d22');
  s.line(5.6, -14.6, 9.4, -14.6, '#6a5a44', 1.2);                     // cross-guard
  poly(s, [[6.9, -13.8], [8.1, -13.8], [8.3, -2.6], [7.5, -.8], [6.7, -2.6]], steelLight);
  s.line(7.5, -13.6, 7.5, -2.4, steel, .5);
  s.ellipse(7.5, -16.2, .8, .8, '#8a7650');                           // pommel
  // the head: aventail of mail, a face in shadow with two dim sparks, the pointed shishak with a nose guard
  curve(c, [[-5.6, -29.6], ['q', -6.4, -22.6, -1.6, -22.2], [2.6, -22.2], ['q', 7.2, -22.6, 6.2, -29.6]], mailDark);
  s.ellipse(.4, -28.4, 4.4, 3.6, '#1f2226');
  s.ellipse(-1.2, -28.8, .7, .45, '#e3c98a'); s.ellipse(2.2, -28.8, .7, .45, '#e3c98a');
  curve(c, [[-5.4, -30.2], ['q', -5.4, -37.8, .4, -41.6], ['q', 6.2, -37.8, 6.2, -30.2]], steel);
  curve(c, [[-5.4, -30.2], ['q', -5.4, -37.8, .4, -41.6], ['q', -1.6, -36.6, -2.2, -30.2]], steelLight);
  s.line(.4, -41.4, .4, -44.4, steel, 1);
  poly(s, [[-5.8, -31.2], [6.6, -31.2], [6.4, -29.6], [-5.6, -29.6]], '#6f777e');
  s.line(.6, -30.4, .6, -26.4, steel, 1.1);                           // nose guard
  // the round shield on his left arm: dark boards, a worn red sun, an iron rim and boss
  s.ellipse(-6.2, -15.4, 7.6, 8.2, '#55606a');
  s.ellipse(-6.2, -15.4, 6.8, 7.4, '#4a3a2c');
  curve(c, [[-6.2, -15.4], [-6.2, -22.6], ['q', -1.4, -21.2, -.4, -15.4]], '#7c2b27');
  curve(c, [[-6.2, -15.4], [-6.2, -8.2], ['q', -11, -9.6, -12, -15.4]], '#7c2b27');
  s.line(-12.6, -15.4, .2, -15.4, '#3a2e24', .5); s.line(-6.2, -22.6, -6.2, -8.2, '#3a2e24', .5);
  s.ellipse(-6.2, -15.4, 1.9, 2, steel); s.ellipse(-6.7, -16, .7, .7, steelLight);
}

function trader(s, c) {
  s.ellipse(1, .6, 9, 2.6, shadow);
  // the pedlar's box on his back, a bundle tied on top
  poly(s, [[-8.6, -33], [3.4, -33], [3.4, -12], [-8.6, -12]], '#b48f66');
  poly(s, [[-8.6, -33], [3.4, -33], [3.4, -30.6], [-8.6, -30.6]], '#9c7a54');
  s.line(-8.6, -22, 3.4, -22, '#8a6c4c', .8);
  s.ellipse(-2.6, -35, 5.4, 2.6, '#8fae86'); s.ellipse(-4.6, -35.6, 1.4, 1.4, '#c9747c');
  legs(s, '#5a4a3c', '#3f3328');
  poly(s, [[-4.8, -19.4], [5, -19.4], [6.6, -5.4], [-6.4, -5.4]], '#7d5a3c');
  s.line(-.2, -19, .4, -5.6, '#6a4a30', .7);
  poly(s, [[-5.2, -12.6], [5.8, -12.6], [6, -11], [-5.4, -11]], '#c9a85a');
  s.line(-4, -18.6, -4.6, -12.4, '#6f5640', 1.2);                    // a strap of the box
  // the walking stick in his right hand
  s.line(8.4, -21, 8.6, -.6, '#8a6c4c', 1.2);
  s.line(4.6, -18.4, 8, -13.6, '#7d5a3c', 3);
  s.ellipse(8.2, -13, 1.6, 1.7, '#f1cfae');
  s.ellipse(.8, -25.6, 6, 6.4, '#f1cfae');
  // beard, cap with a peak
  curve(c, [[-4.6, -24.6], ['q', -4, -18.4, .8, -18.6], ['q', 5.8, -18.4, 6.2, -24.6], ['q', .8, -22.6, -4.6, -24.6]], '#9b7a55');
  eyes(s, -1.6, -26.6, 4.8); s.ellipse(.8, -24.6, 1.1, .8, '#e8b496');
  curve(c, [[-5.4, -29], ['q', -5, -34.6, 1, -34.4], ['q', 6.8, -34.2, 6.4, -29]], '#3f4a5a');
  poly(s, [[1.6, -29.6], [9.4, -28.8], [8.6, -27.8], [1.4, -28.4]], '#2f3846');
}

function fisher(s, c) {
  s.ellipse(1, .6, 9, 2.6, shadow);
  // the rod over his shoulder, a fish on the line
  s.line(-3, -15, 13.6, -44, '#8a6c4c', 1);
  s.line(13.6, -44, 14.4, -33, '#9aa3a8', .4);
  curve(c, [[14.4, -33], ['q', 16, -31, 14.6, -27.4], ['q', 13.2, -31, 14.4, -33]], '#7fa6c9');
  poly(s, [[14.6, -27.6], [13.4, -25.6], [15.8, -25.6]], '#6f93b4');
  // tall green boots, an oilskin coat
  s.line(-2.6, -9, -2.6, -1.5, '#55705a', 3); s.line(2.7, -9, 2.7, -1.5, '#55705a', 3);
  s.ellipse(-2.4, -1, 2.8, 1.2, '#44594a'); s.ellipse(3, -1, 2.8, 1.2, '#44594a');
  poly(s, [[-5, -19.6], [5.2, -19.6], [6.6, -6.4], [-6.4, -6.4]], '#d4b257');
  s.line(.2, -19.2, .4, -6.6, '#b8973f', .7);
  for (const y of [-16, -12.4, -8.8]) s.ellipse(1.2, y, .45, .45, '#8a6c4c');
  s.line(-4.6, -18.6, -2.6, -14.6, '#d4b257', 3);
  s.ellipse(-2.4, -14, 1.6, 1.7, '#f1cfae');
  s.line(4.8, -18.4, 6.6, -12.6, '#d4b257', 3);
  s.ellipse(6.6, -12, 1.6, 1.7, '#f1cfae');
  s.ellipse(.8, -25.6, 6, 6.4, '#f1cfae');
  eyes(s, -1.6, -26.8, 4.8); s.ellipse(.8, -24.8, 1.1, .8, '#e8b496');
  // the long drooping moustache of a catfish, his nickname
  curve(c, [[.8, -23.6], ['q', -3.6, -24.2, -5.6, -19.2], ['q', -2.6, -22.4, .8, -22.6], ['q', 4.2, -22.4, 7.2, -19.2], ['q', 5.2, -24.2, .8, -23.6]], '#8a7a66');
  // sou'wester hat, the back brim long
  curve(c, [[-6.8, -28.2], ['q', -6.4, -35.6, .8, -35.4], ['q', 8, -35.6, 8.4, -28.2]], '#c29b3d');
  poly(s, [[-8, -28.6], [9.6, -28.6], [8, -26.8], [-6.4, -26.8]], '#b18c33');
}

function forester(s, c) {
  s.ellipse(1, .6, 9, 2.6, shadow);
  legs(s, '#4b5a3e', '#3a3228');
  poly(s, [[-5, -19.6], [5.2, -19.6], [6.4, -6], [-6.2, -6]], '#5f7d55');
  poly(s, [[-5.4, -12.4], [5.8, -12.4], [6, -10.8], [-5.6, -10.8]], '#6f5640');
  for (const [x, y] of [[-3.4, -17.4], [3.2, -17.4]]) poly(s, [[x - 1.6, y], [x + 1.6, y], [x + 1.6, y + 2.6], [x - 1.6, y + 2.6]], '#55704b');
  // a basket of berries and mushrooms on his left arm
  s.line(-4.8, -18.6, -6.6, -12.4, '#5f7d55', 3);
  curve(c, [[-12, -12.6], ['q', -8.4, -18.6, -4.6, -12.6]], '#8a6c4c');
  poly(s, [[-12.4, -12.6], [-4.2, -12.6], [-5.2, -7.4], [-11.4, -7.4]], '#b48f66');
  s.line(-12, -10.4, -4.6, -10.4, '#9c7a54', .6);
  s.ellipse(-10.4, -13.4, 1.8, 1.2, '#c9553f'); s.ellipse(-10.8, -13.7, .4, .3, '#fff'); s.ellipse(-9.9, -13.2, .35, .3, '#fff');
  for (const [x, y] of [[-7.6, -13.4], [-6.4, -13.8], [-7, -14.4]]) s.ellipse(x, y, .9, .9, '#6a4f86');
  s.ellipse(-6.6, -12.2, 1.6, 1.7, '#e8c4a2');
  s.line(4.8, -18.4, 6.8, -12.4, '#5f7d55', 3);
  s.ellipse(6.8, -11.8, 1.6, 1.7, '#e8c4a2');
  s.ellipse(.8, -25.6, 6, 6.4, '#e8c4a2');
  curve(c, [[-4.8, -24.4], ['q', -3.6, -19.4, .8, -19.6], ['q', 5.2, -19.4, 6.4, -24.4], ['q', .8, -22.4, -4.8, -24.4]], '#7a5a3e');
  eyes(s, -1.6, -26.6, 4.8); s.ellipse(.8, -24.6, 1.1, .8, '#d99e7e');
  // a forester's hat with a jay feather
  poly(s, [[-8, -28.6], [9.6, -28.6], [8.4, -27.2], [-6.8, -27.2]], '#4b5e3e');
  curve(c, [[-5, -28.6], ['q', -4.6, -35.4, 1, -35], ['q', 6.6, -35.4, 6.8, -28.6]], '#55704b');
  poly(s, [[-5, -30.4], [6.8, -30.4], [6.8, -28.8], [-5, -28.8]], '#6f5640');
  poly(s, [[5.6, -30.6], [10.4, -37.4], [7, -30.2]], '#5f7fa6');
  s.line(6.2, -30.6, 9.6, -36.2, '#2f3846', .4);
}

function teller(s, c) {
  s.ellipse(1, .6, 9, 2.6, shadow);
  s.ellipse(-2.4, -1, 2.7, 1.2, '#7a3f34'); s.ellipse(3, -1, 2.7, 1.2, '#7a3f34');
  // a long blue kaftan to the ankles, gold trim, a red sash
  poly(s, [[-5.2, -20], [5.4, -20], [7.4, -1.8], [-7.2, -1.8]], '#5f7fa6');
  s.line(.4, -19.6, .8, -2.2, '#e0c070', .9);
  s.line(-7.1, -2.4, 7.3, -2.4, '#e0c070', .9);
  poly(s, [[-5.8, -12.4], [6, -12.4], [6.2, -10.6], [-6, -10.6]], '#c0504a');
  poly(s, [[4.6, -11], [6, -11], [6.8, -6.6], [5.4, -6.8]], '#c0504a');
  // the scroll in both hands
  s.line(-4.8, -18.6, -3.6, -13.8, '#5f7fa6', 3); s.line(5, -18.6, 4.4, -13.8, '#5f7fa6', 3);
  poly(s, [[-4.4, -16.4], [5.4, -16.4], [5.4, -12.6], [-4.4, -12.6]], '#efe3c4');
  s.ellipse(-4.6, -14.5, .9, 2.2, '#d9c69a'); s.ellipse(5.6, -14.5, .9, 2.2, '#d9c69a');
  for (const y of [-15.4, -14.4, -13.4]) s.line(-3, y, 4, y, '#b8a27a', .35);
  s.ellipse(-3.6, -13.2, 1.5, 1.6, '#f1cfae'); s.ellipse(4.4, -13.2, 1.5, 1.6, '#f1cfae');
  s.ellipse(.8, -25.6, 6, 6.4, '#f1cfae');
  // a white beard down to the scroll, bushy brows
  curve(c, [[-5.2, -25.4], ['q', -5, -16.6, .8, -15.4], ['q', 6.6, -16.6, 6.8, -25.4], ['q', .8, -22.2, -5.2, -25.4]], '#eee8dc');
  s.line(-2.8, -28.2, -.4, -28, '#eee8dc', 1.1); s.line(2, -28, 4.4, -28.2, '#eee8dc', 1.1);
  eyes(s, -1.6, -26.8, 4.8); s.ellipse(.8, -24.6, 1.1, .8, '#e8b496');
  // a tall fur-trimmed hat
  curve(c, [[-4.6, -30], ['q', -4.4, -38.6, 1, -38.4], ['q', 6.4, -38.6, 6.4, -30]], '#7a3f34');
  s.ellipse(.8, -29.8, 6.6, 2, '#d9c8a8');
}

function crafter(s, c) {
  s.ellipse(1, .6, 9, 2.6, shadow);
  // a plank on his right shoulder
  poly(s, [[-9, -27.4], [14.6, -22], [14.2, -20.2], [-9.4, -25.6]], '#d9b98a');
  s.line(-9.2, -26.4, 14.4, -21, '#c4a070', .4);
  legs(s, '#5a6a7a', '#4a3a2c');
  // a light shirt with a red hem, a leather apron, an axe in the belt
  poly(s, [[-5, -19.6], [5.2, -19.6], [6, -7.4], [-5.8, -7.4]], '#ece2c8');
  s.line(-5.8, -7.8, 6, -7.8, '#c0504a', .9);
  poly(s, [[-3.6, -17], [4, -17], [4.8, -5.2], [-4.4, -5.2]], '#9d7753');
  s.line(-3.6, -17, -4.6, -19.4, '#7a5a3e', .7); s.line(4, -17, 4.8, -19.4, '#7a5a3e', .7);
  poly(s, [[-1.2, -12.8], [2, -12.8], [2, -10.6], [-1.2, -10.6]], '#7a5a3e');
  s.line(-5.6, -12.6, -8.4, -4.6, '#8a6c4c', 1.1);
  poly(s, [[-9.8, -6.4], [-7.2, -5.2], [-7.6, -3.2], [-10.4, -4]], '#9aa3ab');
  s.line(-4.6, -18.6, -6, -12.6, '#ece2c8', 3); s.ellipse(-6, -12, 1.6, 1.7, '#f1cfae');
  s.line(4.8, -18.8, 6.6, -23, '#ece2c8', 3); s.ellipse(6.8, -23.6, 1.6, 1.7, '#f1cfae');
  s.ellipse(.8, -25.6, 6, 6.4, '#f1cfae');
  // short beard, a headband over tousled hair
  curve(c, [[-5, -30], ['q', -4.6, -34.6, 1, -34.2], ['q', 6.6, -34.6, 6.8, -30], ['q', 1, -31.6, -5, -30]], '#b7834e');
  poly(s, [[-5.6, -30.6], [7.2, -30.6], [7.2, -29], [-5.6, -29]], '#c9747c');
  curve(c, [[-4.6, -24.2], ['q', -3.4, -20.4, .8, -20.6], ['q', 5, -20.4, 6.2, -24.2], ['q', .8, -22.6, -4.6, -24.2]], '#b7834e');
  eyes(s, -1.6, -26.8, 4.8); cheeks(s, -3, -24.8, 7.6);
}

function traveler(s, c) {
  s.ellipse(1, .6, 9, 2.6, shadow);
  // a backpack with a rolled blanket
  poly(s, [[-8.8, -22.4], [-1.6, -22.4], [-1.6, -11], [-8.8, -11]], '#a7814f');
  s.ellipse(-5.2, -23.4, 4.4, 1.9, '#c9747c'); s.line(-5.2, -25.2, -5.2, -21.6, '#a5605a', .5);
  s.line(-2.6, -6, -2.6, -1.5, '#f1cfae', 2.2); s.line(2.7, -6, 2.7, -1.5, '#f1cfae', 2.2);
  s.ellipse(-2.4, -1, 2.6, 1.1, '#876750'); s.ellipse(3, -1, 2.6, 1.1, '#876750');
  // a teal sarafan over a white blouse
  s.ellipse(.2, -18.6, 5, 3.6, '#f3ece0');
  poly(s, [[-4, -18.6], [4.4, -18.6], [7.2, -4.2], [-6.8, -4.2]], '#6f9e8e');
  s.line(-6.6, -5, 7, -5, '#e0c070', .8);
  s.line(-3.6, -18.4, -1.6, -12, '#6f9e8e', 1); s.line(4, -18.4, 2, -12, '#6f9e8e', 1);
  s.line(-4.4, -18.2, -3.2, -13.6, '#f3ece0', 2.6); s.ellipse(-3, -13, 1.5, 1.6, '#f1cfae');
  // the staff
  s.line(8.6, -27, 8, -.6, '#8a6c4c', 1.2);
  s.line(4.6, -18.2, 7.8, -15, '#f3ece0', 2.6); s.ellipse(8.2, -14.6, 1.5, 1.6, '#f1cfae');
  // a braid down the back, a kerchief
  s.line(-4.6, -24, -6.8, -12.6, '#9b6a3c', 2.2); s.ellipse(-6.9, -11.8, 1.1, 1.4, '#c9747c');
  s.ellipse(.7, -26, 6, 6.6, '#f1cfae');
  curve(c, [[-5.6, -26.4], ['q', -6, -35.6, .8, -35.6], ['q', 7.6, -35.6, 7, -26.4], ['q', 4, -31.6, .8, -31.4], ['q', -2.6, -31.6, -5.6, -26.4]], '#d58f5a');
  poly(s, [[5.6, -27.6], [9, -23.4], [6, -24.2]], '#d58f5a');
  s.ellipse(-1.2, -32.4, .8, .8, '#f3d9a6'); s.ellipse(2.4, -33, .8, .8, '#f3d9a6');
  eyes(s, -1.6, -26.2, 4.8); cheeks(s, -3, -24, 7.6); smile(c, 1, -22.8, 3);
}

// ---------- the easter-egg guests (local critters) ----------

function dymok(s, c) {   // a hedgehog chimney sweep, sooty
  s.ellipse(1, .6, 8.5, 2.6, shadow);
  // the brush over his shoulder: a long handle, a round bristle head
  s.line(-6, -6, 9.6, -36, '#6f5640', 1.1);
  for (let a = 0; a < 12; a++) { const t = a / 12 * Math.PI * 2; s.line(9.8, -37, 9.8 + Math.cos(t) * 4.2, -37 + Math.sin(t) * 4.2, '#2f2c2a', .9) }
  s.ellipse(9.8, -37, 1.6, 1.6, '#3a3632');
  s.ellipse(-3.4, -1.3, 2.7, 1.3, '#4a433c'); s.ellipse(3.4, -1.3, 2.7, 1.3, '#4a433c');
  poly(s, [[-7, -5], [-10, -9], [-8.5, -12], [-11, -17], [-8.7, -18], [-10, -23], [-6.5, -22], [-7, -28], [-3.6, -25], [-2, -31], [2, -26], [5.7, -29], [6.2, -22], [8, -19], [6, -7]], '#57504a');
  s.ellipse(0, -12, 6.6, 8.2, '#3f3b38');
  for (const [x, y] of [[-2, -14], [2, -10], [-1, -7]]) s.ellipse(x, y, .5, .5, '#c9b07a');   // brass buttons
  s.ellipse(1.1, -24, 6.3, 6.5, '#d2bea0');
  s.ellipse(-1.4, -21.8, 2.4, 1.6, '#8f8476'); s.ellipse(4.2, -26.4, 1.8, 1.2, '#9d9284');   // soot smudges
  s.ellipse(5.7, -22.8, 4.3, 2.7, '#ddc9ab');
  s.ellipse(9.4, -23.1, 1.25, 1.25, '#3b3a36');
  s.ellipse(3.2, -25.7, .9, 1.05, '#3b3a36');
  s.line(4.8, -18.6, 6.8, -13.4, '#3f3b38', 2.8); s.ellipse(6.9, -12.8, 1.5, 1.7, '#d2bea0');
  // a little black top hat
  s.ellipse(.6, -29.6, 6.2, 1.6, '#2a2725');
  poly(s, [[-3, -29.6], [4.4, -29.6], [4, -36.4], [-2.6, -36.4]], '#2f2c2a');
  poly(s, [[-3, -31.2], [4.3, -31.2], [4.2, -30.2], [-3, -30.2]], '#8f3f3a');
}

function shustrik(s, c) {   // a mouse courier with a parcel
  s.ellipse(1, .6, 8, 2.4, shadow);
  c.beginPath(); c.moveTo(5, -4); c.bezierCurveTo(11, -2, 13, -9, 10, -12); c.bezierCurveTo(8, -14, 9.4, -17, 11.6, -16.4);
  c.strokeStyle = '#d89a9a'; c.lineWidth = 1; c.lineCap = 'round'; c.stroke();
  s.ellipse(-2.6, -1.1, 2.4, 1.1, '#d89a9a'); s.ellipse(2.8, -1.1, 2.4, 1.1, '#d89a9a');
  s.ellipse(0, -9.6, 5.6, 7.4, '#a9a3a1');
  s.ellipse(.6, -8.6, 3.6, 5, '#d8d2cc');
  // the parcel on his back: brown paper, twine
  poly(s, [[-9.4, -19], [-2.4, -19], [-2.4, -9.4], [-9.4, -9.4]], '#c4a070');
  s.line(-5.9, -19, -5.9, -9.4, '#8a6c4c', .6); s.line(-9.4, -14.2, -2.4, -14.2, '#8a6c4c', .6);
  s.line(4, -14, 6.4, -9.6, '#a9a3a1', 2.4); s.ellipse(6.6, -9.2, 1.2, 1.2, '#e2b4b0');
  // round ears, a pointed snout, a red scarf
  s.ellipse(-4.4, -27.4, 4, 4, '#a9a3a1'); s.ellipse(-4.4, -27.4, 2.6, 2.6, '#e2b4b0');
  s.ellipse(6, -27.4, 4, 4, '#a9a3a1'); s.ellipse(6, -27.4, 2.6, 2.6, '#e2b4b0');
  s.ellipse(.8, -21.6, 6, 5.6, '#a9a3a1');
  curve(c, [[3, -22.6], ['q', 8, -21.8, 9.4, -19.6], ['q', 6, -18, 2, -19.4]], '#b8b2ae');
  s.ellipse(9.4, -19.8, 1, .9, '#d36f7a');
  eyes(s, -1.2, -22.8, 4.4);
  for (const y of [-20.6, -19.6]) s.line(7.8, y, 11.4, y - .6, '#6f6a66', .3);
  poly(s, [[-4.6, -17.4], [6, -17.4], [5.4, -15.4], [-4, -15.4]], '#c0504a');
  poly(s, [[3.4, -16], [5.4, -16], [6.4, -12], [4.8, -12.2]], '#c0504a');
}

function pushok(s, c) {   // a badger night watchman with a lantern
  s.ellipse(1, .6, 9, 2.7, shadow);
  s.ellipse(-3.2, -1.2, 2.8, 1.3, '#3f3d3b'); s.ellipse(3.4, -1.2, 2.8, 1.3, '#3f3d3b');
  s.ellipse(0, -11, 7.6, 9.4, '#8d8a86');
  s.ellipse(.8, -10, 4.6, 6.6, '#c9c4bc');
  // the watchman's coat: a dark blue tabard with a brass badge
  poly(s, [[-6.4, -17.6], [-1.6, -17.6], [-2.4, -3.4], [-7, -4.6]], '#3f5372');
  poly(s, [[3.2, -17.6], [7, -17.6], [7.4, -4.6], [3.8, -3.4]], '#3f5372');
  s.ellipse(5.2, -14.6, .9, .9, '#d8b45c');
  // the lantern in his right paw
  s.line(5.6, -16.6, 9.2, -10.6, '#8d8a86', 2.8);
  s.line(9.6, -10.2, 9.6, -8.4, '#3a3632', .6);
  poly(s, [[8, -8.4], [11.2, -8.4], [11.6, -2.6], [7.6, -2.6]], '#3a3632');
  poly(s, [[8.6, -7.6], [10.6, -7.6], [10.8, -3.4], [8.4, -3.4]], '#f3d27a');
  s.ellipse(9.6, -1.6, 2.4, .7, '#f3d27a55');
  // a broad head: white with two black stripes over the eyes
  s.ellipse(.6, -24, 7.4, 6.6, '#f1ede6');
  curve(c, [[-5.4, -27.6], ['q', -4.4, -31.4, -2.2, -30.4], ['q', -.6, -25, -1.2, -20.8], ['q', -4, -22.4, -5.4, -27.6]], '#2f2d2c');
  curve(c, [[6.6, -27.6], ['q', 5.6, -31.4, 3.4, -30.4], ['q', 1.8, -25, 2.4, -20.8], ['q', 5.2, -22.4, 6.6, -27.6]], '#2f2d2c');
  s.ellipse(-2.4, -25.6, .8, .8, '#f1ede6'); s.ellipse(3.6, -25.6, .8, .8, '#f1ede6');
  s.ellipse(.6, -20.4, 1.4, 1, '#2f2d2c');
  s.ellipse(-4.8, -30.2, 1.6, 1.4, '#8d8a86'); s.ellipse(6, -30.2, 1.6, 1.4, '#8d8a86');
}

function boryan(s, c) {   // a sly fox with a sack
  s.ellipse(1, .6, 9, 2.6, shadow);
  // the bushy tail with a white tip
  curve(c, [[-3, -6], ['c', -12, -6, -14, -16, -10.6, -20], ['c', -9, -14, -6, -10, -2, -10]], '#d9773a');
  curve(c, [[-10.6, -20], ['q', -13.4, -17.6, -12.8, -14.8], ['q', -10.6, -16, -10.6, -20]], '#f4ede0');
  s.ellipse(-2.6, -1.1, 2.4, 1.2, '#3a2e26'); s.ellipse(3, -1.1, 2.4, 1.2, '#3a2e26');
  s.line(-2.4, -6, -2.4, -1.6, '#c4652e', 2.2); s.line(2.8, -6, 2.8, -1.6, '#c4652e', 2.2);
  s.ellipse(.2, -12, 5.6, 7.6, '#d9773a');
  s.ellipse(.8, -11, 3.4, 5.6, '#f4ede0');
  // the sack over his shoulder
  s.line(4.6, -16.6, 6, -20.4, '#d9773a', 2.6);
  curve(c, [[5, -22.4], ['q', 13.6, -24.6, 12.6, -14.6], ['q', 9.6, -11.4, 6.6, -14.6], ['q', 4, -18, 5, -22.4]], '#b8a07a');
  s.line(5.4, -21.2, 7.4, -19, '#8a7656', .7);
  s.ellipse(9.4, -18, .9, .6, '#9b875f');
  // a pointed head, a dark kerchief at the neck, one eye narrowed
  poly(s, [[-4.6, -17.6], [5.4, -17.6], [3.6, -15.2], [-3.2, -15.2]], '#3f4a5a');
  poly(s, [[-1, -15.6], [1.6, -15.6], [.4, -12.8]], '#3f4a5a');
  poly(s, [[-5.6, -27.4], [-5.4, -35], [-1.6, -29.6]], '#d9773a'); poly(s, [[-4.8, -28.4], [-4.7, -33], [-2.6, -29.6]], '#5a3a2a');
  poly(s, [[3.4, -29.6], [7, -35], [7.4, -27.4]], '#d9773a'); poly(s, [[4.4, -29.6], [6.6, -33], [6.8, -28.4]], '#5a3a2a');
  s.ellipse(.8, -24.4, 6.4, 5.8, '#d9773a');
  curve(c, [[-3, -22.6], ['q', .8, -18.4, 4.6, -22.6], ['q', 1, -20.6, -3, -22.6]], '#f4ede0');
  curve(c, [[2.6, -23.4], ['q', 8.4, -22.6, 10.4, -20.8], ['q', 6.6, -19.2, 2.6, -21]], '#e08a4e');
  s.ellipse(10.2, -21, 1, .9, '#2f2a26');
  s.ellipse(-1.6, -25.4, .8, .9, '#2f2a26');
  s.line(2.6, -25.4, 4.6, -25.6, '#2f2a26', .7);   // the wink
}

function belyana(s, c) {   // a white snowy owl with glasses and a clipboard
  s.ellipse(1, .6, 8.6, 2.6, shadow);
  s.line(-3, -4, -3, -1.1, '#9a9a90', 1.9); s.line(3, -4, 3, -1.1, '#9a9a90', 1.9);
  s.line(-5, -.8, -1, -.8, '#8a8a80', 1.3); s.line(1, -.8, 5, -.8, '#8a8a80', 1.3);
  s.ellipse(0, -12, 8.4, 10.7, '#ecebe4');
  s.ellipse(1, -11.4, 5.7, 8.5, '#f8f7f2');
  s.ellipse(-6.5, -13.7, 2.7, 7, '#dcdbd2');
  for (const [x, y] of [[-3, -16], [2.4, -14.6], [-1, -9.6], [3, -8], [-4, -6]]) s.ellipse(x, y, .7, .45, '#a9aab0');
  // the clipboard held to her chest
  poly(s, [[1.4, -18], [8.8, -17], [8, -6.4], [.6, -7.4]], '#b48f66');
  poly(s, [[2.4, -16.6], [7.8, -15.8], [7.2, -7.8], [1.8, -8.6]], '#f8f2e0');
  for (const t of [0, 1, 2, 3]) s.line(3, -14.6 + t * 1.8, 6.8, -14 + t * 1.8, '#9fb3c6', .45);
  s.ellipse(5.1, -17.4, 1.4, .7, '#8a8a80');
  s.ellipse(7.6, -10, 2, 3.4, '#dcdbd2');
  s.ellipse(.3, -24.9, 8.2, 7.4, '#ecebe4');
  for (const [x, y] of [[-4.6, -29.6], [4.8, -30], [.4, -31]]) s.ellipse(x, y, .6, .4, '#a9aab0');
  s.ellipse(-3, -25.2, 4.3, 4.8, '#f8f7f2'); s.ellipse(4.1, -25.2, 4, 4.6, '#f8f7f2');
  s.ellipse(-2.4, -25.2, 1.7, 2.1, '#c9a43a'); s.ellipse(4.5, -25.2, 1.6, 2.1, '#c9a43a');
  s.ellipse(-2.4, -25.2, .9, 1.2, '#2f2d2c'); s.ellipse(4.5, -25.2, .85, 1.2, '#2f2d2c');
  // round glasses
  for (const [x, r] of [[-2.6, 3], [4.4, 2.9]]) { c.beginPath(); c.ellipse(x, -25.2, r, r, 0, 0, Math.PI * 2); c.strokeStyle = '#6f5640'; c.lineWidth = .6; c.stroke() }
  s.line(.4, -25.4, 1.5, -25.4, '#6f5640', .6);
  poly(s, [[.3, -22.2], [3.1, -22.2], [1.8, -19.4]], '#4a4a48');
}

function kroshka(s, c) {   // a little ladybird with a leaf
  s.ellipse(1, .6, 7, 2.2, shadow);
  for (const [x0, x1] of [[-3, -4.6], [3, 4.6]]) s.line(x0, -4, x1, -.6, '#2f2d2c', 1);
  // the leaf she carries like a parasol
  s.line(5.2, -10, 7.6, -22, '#6f9a5f', .8);
  curve(c, [[7.6, -22], ['q', 14.2, -24.4, 13, -18.6], ['q', 9.6, -16.6, 7.6, -22]], '#86b071');
  s.line(7.8, -21.8, 12.4, -19, '#6f9a5f', .4);
  // the round shell with spots, split down the back
  s.ellipse(0, -10.6, 7.4, 7.6, '#2f2d2c');
  curve(c, [[-.2, -18], ['q', -8.4, -17.4, -7.4, -9], ['q', -6, -3.4, -.2, -3.4]], '#d0453a');
  curve(c, [[.2, -18], ['q', 8.4, -17.4, 7.4, -9], ['q', 6, -3.4, .2, -3.4]], '#dd5446');
  for (const [x, y, r] of [[-3.8, -13.6, 1.4], [-4.4, -8.2, 1.2], [-1.8, -6, .9], [3.6, -13, 1.3], [4.6, -8, 1.2], [1.8, -5.8, .9]]) s.ellipse(x, y, r, r, '#2f2d2c');
  s.ellipse(-3.6, -15.4, 1.6, .9, '#f08f80');
  s.line(5.4, -12, 7.4, -9.6, '#2f2d2c', 1);
  // the black head with white eyes and antennae
  s.ellipse(.4, -20.4, 4.8, 4.2, '#2f2d2c');
  s.ellipse(-1.4, -21, 1.3, 1.5, '#fff'); s.ellipse(2.4, -21, 1.3, 1.5, '#fff');
  s.ellipse(-1.2, -20.8, .65, .8, '#2f2d2c'); s.ellipse(2.6, -20.8, .65, .8, '#2f2d2c');
  smile(c, .5, -18.4, 2.2, '#f3ece0');
  s.line(-1.4, -24, -3.6, -28.4, '#2f2d2c', .6); s.ellipse(-3.7, -28.6, .8, .8, '#2f2d2c');
  s.line(2, -24, 3.8, -28.6, '#2f2d2c', .6); s.ellipse(3.9, -28.8, .8, .8, '#2f2d2c');
}

function sharik(s, c) {   // a round frog
  s.ellipse(1, .6, 9.4, 2.8, shadow);
  s.ellipse(-4.6, -.9, 3.4, 1.3, '#6f9a4e'); s.ellipse(5.4, -.9, 3.4, 1.3, '#6f9a4e');
  s.ellipse(.4, -11.6, 9, 10.6, '#7fae5a');
  s.ellipse(.8, -9.6, 6.2, 7.2, '#d8e6a6');
  s.line(-6.4, -12, -8.6, -6, '#7fae5a', 2.4); s.ellipse(-8.8, -5.4, 1.6, 1.1, '#6f9a4e');
  s.line(7.2, -12, 9.4, -6, '#7fae5a', 2.4); s.ellipse(9.6, -5.4, 1.6, 1.1, '#6f9a4e');
  for (const [x, y] of [[-5, -18], [6, -17], [-6.4, -12.4]]) s.ellipse(x, y, .9, .7, '#6a9a48');
  // two big eyes on top, a wide mouth
  s.ellipse(-3.6, -21.4, 3.6, 3.6, '#7fae5a'); s.ellipse(5.2, -21.4, 3.6, 3.6, '#7fae5a');
  s.ellipse(-3.6, -21.8, 2.5, 2.6, '#f8f5e8'); s.ellipse(5.2, -21.8, 2.5, 2.6, '#f8f5e8');
  s.ellipse(-3.2, -21.6, 1.2, 1.5, '#2f2d2c'); s.ellipse(5.6, -21.6, 1.2, 1.5, '#2f2d2c');
  s.ellipse(-2.8, -22.2, .4, .4, '#fff'); s.ellipse(6, -22.2, .4, .4, '#fff');
  c.beginPath(); c.moveTo(-4, -16.4); c.quadraticCurveTo(.8, -13, 5.6, -16.4); c.strokeStyle = '#4f7a3a'; c.lineWidth = .8; c.lineCap = 'round'; c.stroke();
  cheeks(s, -5, -16.6, 11.6);
}

function filya(s, c) {   // a little spider with a spool of thread
  s.ellipse(1, .6, 9.4, 2.6, shadow);
  // eight legs, four a side, bent at the knee
  for (const k of [0, 1, 2, 3]) {
    const y = -9 + k * 1.6, kx = 7.6 + k * .6, ky = -13 + k * 2.4;
    c.beginPath(); c.moveTo(-2, y); c.lineTo(-kx, ky); c.lineTo(-kx - 1.6 + k * .4, -.6); c.strokeStyle = '#3f3a4c'; c.lineWidth = 1.2; c.lineJoin = 'round'; c.stroke();
    if (k < 3) { c.beginPath(); c.moveTo(2.4, y); c.lineTo(kx, ky); c.lineTo(kx + 1.6 - k * .4, -.6); c.stroke() }
  }
  s.ellipse(.4, -10.4, 6.6, 6.4, '#4a4458');
  s.ellipse(-1.6, -12.4, 2, 1.4, '#6a6280');
  // the spool in his right front leg, the thread trailing
  s.line(3, -12, 8.6, -15.6, '#3f3a4c', 1.2);
  poly(s, [[8, -19.2], [12.6, -19.2], [12.6, -18], [8, -18]], '#b48f66');
  poly(s, [[8, -14], [12.6, -14], [12.6, -12.8], [8, -12.8]], '#b48f66');
  poly(s, [[8.6, -18], [12, -18], [12, -14], [8.6, -14]], '#e7a8b5');
  c.beginPath(); c.moveTo(12, -15); c.quadraticCurveTo(15, -10, 13.6, -2); c.strokeStyle = '#e7a8b5'; c.lineWidth = .5; c.stroke();
  // the head with big eyes and two small ones above
  s.ellipse(.8, -20.6, 5.6, 5.2, '#4a4458');
  s.ellipse(-1.2, -21.2, 1.8, 2, '#f8f5e8'); s.ellipse(3, -21.2, 1.8, 2, '#f8f5e8');
  s.ellipse(-.9, -21, .9, 1.1, '#2f2d2c'); s.ellipse(3.3, -21, .9, 1.1, '#2f2d2c');
  s.ellipse(-.6, -24.4, .6, .6, '#f8f5e8'); s.ellipse(2.4, -24.4, .6, .6, '#f8f5e8');
  smile(c, 1, -18.2, 2.4, '#c9a6c8');
  s.line(-.2, -17, -.6, -15.6, '#3f3a4c', .7); s.line(1.8, -17, 2.2, -15.6, '#3f3a4c', .7);
}

function makro(s, c) {   // a beaver builder with a hard hat and a blueprint
  s.ellipse(1, .6, 9.2, 2.7, shadow);
  // the flat scaly tail behind
  curve(c, [[-2, -4], ['q', -12, -4.6, -12.6, -1.6], ['q', -11.4, 1.6, -4, -.4]], '#5e4232');
  for (const x of [-10, -8, -6]) s.line(x, -3.6, x + .6, -.2, '#4a3326', .4);
  s.ellipse(-3, -1.1, 2.6, 1.2, '#4a3326'); s.ellipse(3.4, -1.1, 2.6, 1.2, '#4a3326');
  s.ellipse(0, -11.2, 7.2, 9.2, '#8a5e3c');
  s.ellipse(.8, -10.2, 4.4, 6.6, '#b9875a');
  // a tool belt, the blueprint roll under the left arm
  poly(s, [[-6.6, -8.6], [7, -8.6], [7, -7], [-6.6, -7]], '#6f5640');
  s.line(5.4, -8, 6.4, -4.6, '#9aa3ab', .9);
  poly(s, [[-11.6, -16.6], [-3.6, -13.4], [-4.4, -11.6], [-12.4, -14.8]], '#7fa6c9');
  s.ellipse(-12, -15.7, .9, 1.1, '#5f86a8');
  s.line(-5.6, -17.4, -6.4, -12, '#8a5e3c', 2.6);
  s.line(5.6, -17, 7.2, -11.6, '#8a5e3c', 2.6); s.ellipse(7.3, -11, 1.4, 1.4, '#5e4232');
  // the head with buck teeth, a yellow hard hat
  s.ellipse(.8, -23.6, 6.6, 6.2, '#8a5e3c');
  s.ellipse(-4.8, -27.6, 1.6, 1.4, '#6e4a30'); s.ellipse(6.4, -27.6, 1.6, 1.4, '#6e4a30');
  s.ellipse(1.4, -21, 3.8, 2.8, '#c49a6c');
  s.ellipse(1.4, -22.6, 1.3, .9, '#3a2a22');
  poly(s, [[.4, -19.8], [2.4, -19.8], [2.4, -17.6], [.4, -17.6]], '#f8f5e8');
  s.line(1.4, -19.8, 1.4, -17.6, '#d8d2c4', .3);
  eyes(s, -1.4, -25, 5.2);
  curve(c, [[-5.6, -27.4], ['q', -5.4, -34.4, .8, -34.4], ['q', 7, -34.4, 7.2, -27.4]], '#e8c25a');
  poly(s, [[-7, -27.8], [8.6, -27.8], [8, -26.4], [-6.4, -26.4]], '#d4ac44');
  s.line(.8, -34, .8, -28, '#d4ac44', .9);
}

export const GUESTS = {bogatyr, trader, fisher, forester, teller, crafter, traveler,
  egg_dymok: dymok, egg_shustrik: shustrik, egg_pushok: pushok, egg_boryan: boryan, egg_belyana: belyana,
  egg_kroshka: kroshka, egg_sharik: sharik, egg_filya: filya, egg_makro: makro};

export function guestSvgs() {
  const out = {};
  for (const [id, draw] of Object.entries(GUESTS)) {
    const c = new SvgCtx('vg'), s = Object.create(FarmScene.prototype);
    s.c = c; s.time = 0; s.motion = false; s.inStatic = true; s.shadowLevel = 0;
    draw(s, c);
    out[id] = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${GUEST_BOX}" class="bc-art" aria-hidden="true" focusable="false">${c.svg()}</svg>`;
  }
  return out;
}
