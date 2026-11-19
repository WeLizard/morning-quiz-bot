// Winter clothes for the eleven village residents during the New Year festival (owner's decision 2026-11-19).
// Each entry is an OVERLAY in the residents' own viewBox (-18 -50 36 54, feet at 0,0): knitted hats, ushankas and scarves
// that the game lays over the approved resident figure (VILLAGE_RESIDENT_FIGURES in app.js), so the residents themselves
// stay untouched. Positions were measured on the residents' geometry (head ellipses, eyes, ears).
// Cats and the fox keep their ears: the ear tips are redrawn over the hat in the resident's own fur colours.
// Агата keeps her rose kerchief and gets a scarf only; Петух Олег keeps his comb and gets a long scarf.
// Hat and scarf colours are the farm's fabrics, chosen to stand apart from each resident's fur.
const P = (s, pts, fill) => s.poly(pts.map(([x, y]) => ({x, y})), fill);
const F = {red: '#c9473f', rose: '#c9747c', cream: '#f3e3d3', sage: '#8fae6f', sageDark: '#7c9a5d', mustard: '#e7c56c',
  green: '#3f7a54', teal: '#4f9a8f', blue: '#4f6e95', white: '#fbfcfe'};

function beanie(s, cx, by, w, h, c) {
  s.ellipse(cx, by - h * .5, w * .94, h * .58, c.hat);
  if (c.stripe) s.line(cx - w * .8, by - h * .62, cx + w * .8, by - h * .62, c.stripe, h * .16);
  for (let i = -2; i <= 2; i++) s.line(cx + i * w * .3, by - h * .3, cx + i * w * .28, by - h * .82, c.rib, .45);
  P(s, [[cx - w, by - h * .32], [cx + w, by - h * .32], [cx + w * 1.03, by + .3], [cx - w * 1.03, by + .3]], c.band);
  s.ellipse(cx, by - h * 1.1, h * .3, h * .3, c.pom);
}

function ushanka(s, cx, by, w, h, c) {
  s.ellipse(cx - w * .98, by + h * .15, w * .26, h * .55, c.fur); s.ellipse(cx + w * .98, by + h * .15, w * .26, h * .55, c.fur);
  s.ellipse(cx, by - h * .5, w * .92, h * .6, c.hat);
  s.line(cx, by - h * 1.05, cx, by - h * .5, c.seam, .5);
  s.ellipse(cx, by - h * .2, w * 1.02, h * .32, c.fur);
}

function scarf(s, cx, y, w, c, side = 1, len = 7) {
  P(s, [[cx - w, y - 1.5], [cx + w, y - 1.5], [cx + w * 1.05, y + 1.3], [cx - w * 1.05, y + 1.3]], c.scarf);
  s.line(cx - w * .9, y - .1, cx + w * .9, y - .1, c.stripe, .8);
  const x0 = cx + side * w * .45, dx = side * .8;
  P(s, [[x0 - 1.3, y], [x0 + 1.3, y], [x0 + 1.3 + dx, y + len], [x0 - 1.3 + dx, y + len]], c.scarf);
  for (const t of [.35, .7]) s.line(x0 - 1.2 + dx * t, y + len * t, x0 + 1.2 + dx * t, y + len * t, c.stripe, .8);
  for (let k = 0; k < 4; k++) s.line(x0 - 1 + dx + k * .66, y + len, x0 - 1 + dx + k * .66, y + len + 1.3, c.scarf, .5);
}

// ear tips over a hat: [outer base, apex, inner base] for the left ear, mirrored for the right
function earTips(s, ear, fur, inner, innerFill) {
  for (const m of [1, -1]) {
    P(s, ear.map(([x, y]) => [x * m, y]), fur);
    if (inner) P(s, inner.map(([x, y]) => [x * m, y]), innerFill);
  }
}

// the postman's New Year scarf (also worn in his card-carrying pose, fest_characters.js) and snow on the cap
export function hedgehogScarf(s) {
  P(s, [[-4.4, -19.4], [5.8, -19.4], [6.4, -16.8], [-4.8, -16.8]], F.red);
  s.line(-3.6, -18.1, 5.4, -18.1, '#f6efe2', .9);
  P(s, [[3.6, -17.4], [6, -17.4], [6.9, -11.6], [4.4, -11.8]], F.red);
  s.line(4, -15.2, 6.3, -15.1, '#f6efe2', .9); s.line(4.3, -13.1, 6.6, -13, '#f6efe2', .9);
}

const CAT_EAR = [[-4.93, -28.8], [-4.4, -32], [-2.22, -28.8]];
const CAT_INNER = [[-4.28, -29.4], [-4.2, -30.2], [-3.65, -29.4]];

export const WINTER = {
  filinych: s => {
    beanie(s, .3, -30, 6.6, 6, {hat: F.red, rib: '#a93a33', band: F.cream, pom: F.cream});
    scarf(s, .3, -16.6, 7.6, {scarf: F.green, stripe: F.cream}, 1, 7);
  },
  agata: s => scarf(s, .5, -18.8, 5.8, {scarf: F.mustard, stripe: F.red}, -1, 7),
  hedgehog: s => { hedgehogScarf(s); s.ellipse(.4, -32, 4.6, 1.3, F.white); },
  mole: s => {
    ushanka(s, 0, -28.8, 6.6, 6.4, {hat: F.blue, fur: F.cream, seam: '#3f5a7c'});
    scarf(s, 0, -19.6, 7.4, {scarf: F.red, stripe: F.cream}, 1, 7);
  },
  kaya: s => {
    beanie(s, 0, -25.4, 6.3, 5.4, {hat: F.rose, rib: '#ad5f68', band: F.cream, pom: F.cream});
    earTips(s, CAT_EAR, '#a9a7a0', CAT_INNER, '#e7a8b5');
    scarf(s, 0, -17, 5.6, {scarf: F.cream, stripe: F.rose}, 1, 6);
  },
  sonya: s => {
    beanie(s, 0, -25.4, 6.3, 5.4, {hat: F.sage, rib: F.sageDark, band: F.mustard, pom: F.cream});
    earTips(s, CAT_EAR, '#a9afbb', CAT_INNER, '#e0c4c9');
    scarf(s, 0, -17.6, 6, {scarf: F.rose, stripe: F.cream}, -1, 9);
  },
  igor: s => beanie(s, 0, -28.4, 7.8, 6.8, {hat: F.mustard, rib: '#c9a64e', band: F.red, pom: F.red}),
  zverushka: s => {
    beanie(s, 0, -30.4, 7.4, 6, {hat: F.teal, rib: '#3f8077', band: F.cream, pom: F.cream, stripe: F.cream});
    scarf(s, 0, -16.8, 6.6, {scarf: F.teal, stripe: F.cream}, 1, 7);
  },
  pukh: s => {
    ushanka(s, 0, -29.2, 7.4, 6.4, {hat: F.blue, fur: F.cream, seam: '#3f5a7c'});
    scarf(s, 0, -19.8, 7.6, {scarf: F.red, stripe: F.cream}, -1, 8);
  },
  dasha: s => {
    beanie(s, 0, -30.2, 5.8, 5.6, {hat: F.green, rib: '#336847', band: F.cream, pom: F.cream});
    earTips(s, [[-7.27, -31], [-7.5, -36], [-2.92, -31]], '#d57a47', [[-6.13, -31], [-6.3, -33.5], [-4.3, -31]], '#efb28b');
  },
  oleg: s => scarf(s, 5.8, -21.6, 3.6, {scarf: F.blue, stripe: F.cream}, -1, 7),
};

// game name of each resident (VILLAGE_RESIDENT_FIGURES keys)
export const WINTER_NAMES = {filinych: 'Филиныч', agata: 'Агата', hedgehog: 'Почтальон Ёж', mole: 'Механик Крот',
  kaya: 'Кошка Кая', sonya: 'Кошка Соня', igor: 'Суслик Игорь', zverushka: 'Неведома Зверушка', pukh: 'Медведь Пух',
  dasha: 'Лиса Даша', oleg: 'Петух Олег'};
