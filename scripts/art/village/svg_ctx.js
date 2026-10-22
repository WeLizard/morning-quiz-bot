// A tiny CanvasRenderingContext2D stand-in that records what the farm's drawing code paints as SVG elements.
// Used for scene parts that must stay vector in the game (the gate board is a DOM button): the farm's own
// functions (FarmScene.signBoard, poly, line, ellipse) draw into it unchanged. Covers what those functions use:
// paths (moveTo/lineTo/closePath/ellipse), fill/stroke, linear gradients, fillText, save/restore and transforms.
const n = v => +(+v).toFixed(2);
const mul = (a, b) => [a[0]*b[0]+a[2]*b[1], a[1]*b[0]+a[3]*b[1], a[0]*b[2]+a[2]*b[3], a[1]*b[2]+a[3]*b[3], a[0]*b[4]+a[2]*b[5]+a[4], a[1]*b[4]+a[3]*b[5]+a[5]];
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');

export class SvgCtx {
  constructor(idPrefix = 'g') {
    this.out = []; this.defs = []; this.ids = 0; this.prefix = idPrefix; this.d = '';
    this.st = {m: [1, 0, 0, 1, 0, 0], fillStyle: '#000', strokeStyle: '#000', lineWidth: 1, lineCap: 'butt', lineJoin: 'miter',
      font: '10px sans-serif', textAlign: 'start', textBaseline: 'alphabetic', globalAlpha: 1};
    this.stack = [];
  }
  get fillStyle() { return this.st.fillStyle } set fillStyle(v) { this.st.fillStyle = v }
  get strokeStyle() { return this.st.strokeStyle } set strokeStyle(v) { this.st.strokeStyle = v }
  get lineWidth() { return this.st.lineWidth } set lineWidth(v) { this.st.lineWidth = v }
  get lineCap() { return this.st.lineCap } set lineCap(v) { this.st.lineCap = v }
  get lineJoin() { return this.st.lineJoin } set lineJoin(v) { this.st.lineJoin = v }
  get font() { return this.st.font } set font(v) { this.st.font = v }
  get textAlign() { return this.st.textAlign } set textAlign(v) { this.st.textAlign = v }
  get textBaseline() { return this.st.textBaseline } set textBaseline(v) { this.st.textBaseline = v }
  save() { this.stack.push({...this.st, m: [...this.st.m]}) }
  restore() { if (this.stack.length) this.st = this.stack.pop() }
  transform(a, b, c, d, e, f) { this.st.m = mul(this.st.m, [a, b, c, d, e, f]) }
  setTransform(a, b, c, d, e, f) { this.st.m = [a, b, c, d, e, f] }
  translate(x, y) { this.transform(1, 0, 0, 1, x, y) }
  scale(x, y) { this.transform(x, 0, 0, y, 0, 0) }
  setLineDash() {}
  beginPath() { this.d = '' }
  moveTo(x, y) { this.d += `M${n(x)} ${n(y)}` }
  lineTo(x, y) { this.d += `L${n(x)} ${n(y)}` }
  closePath() { this.d += 'Z' }
  ellipse(x, y, rx, ry, rot = 0, a0 = 0, a1 = Math.PI * 2) {
    // full ellipses only (that is all the farm code draws): two half arcs
    this.d += `M${n(x - rx)} ${n(y)}A${n(rx)} ${n(ry)} 0 1 0 ${n(x + rx)} ${n(y)}A${n(rx)} ${n(ry)} 0 1 0 ${n(x - rx)} ${n(y)}Z`;
  }
  createLinearGradient(x0, y0, x1, y1) {
    const id = `${this.prefix}${this.ids++}`, stops = [];
    const g = {id, addColorStop: (o, c) => stops.push(`<stop offset="${n(o)}" stop-color="${c}"/>`)};
    g.toString = () => `url(#${id})`;
    g.svg = () => `<linearGradient id="${id}" gradientUnits="userSpaceOnUse" x1="${n(x0)}" y1="${n(y0)}" x2="${n(x1)}" y2="${n(y1)}">${stops.join('')}</linearGradient>`;
    return g;
  }
  paint(style) { if (style && style.svg) { if (!this.defs.includes(style)) this.defs.push(style); return `url(#${style.id})` } return style }
  tr() { const m = this.st.m; return m.join() === '1,0,0,1,0,0' ? '' : ` transform="matrix(${m.map(n).join(' ')})"` }
  fill() { this.out.push(`<path d="${this.d}" fill="${this.paint(this.st.fillStyle)}"${this.tr()}/>`) }
  stroke() {
    this.out.push(`<path d="${this.d}" fill="none" stroke="${this.paint(this.st.strokeStyle)}" stroke-width="${n(this.st.lineWidth)}"` +
      `${this.st.lineCap !== 'butt' ? ` stroke-linecap="${this.st.lineCap}"` : ''}${this.st.lineJoin !== 'miter' ? ` stroke-linejoin="${this.st.lineJoin}"` : ''}${this.tr()}/>`);
  }
  fillText(text, x, y, maxWidth) {
    const m = /(\d+)\s+([\d.]+)px\s+(.*)/.exec(this.st.font) || [], anchor = {center: 'middle', right: 'end', end: 'end'}[this.st.textAlign] || 'start';
    this.out.push(`<text x="${n(x)}" y="${n(y)}" font-weight="${m[1] || 400}" font-size="${n(m[2] || 10)}" font-family="${esc(m[3] || 'sans-serif')}" ` +
      `text-anchor="${anchor}"${maxWidth ? ` textLength="${n(maxWidth)}" lengthAdjust="spacingAndGlyphs"` : ''} fill="${this.paint(this.st.fillStyle)}"${this.tr()}>${esc(text)}</text>`);
  }
  measureText(t) { return {width: String(t).length * 6} }
  // the recorded drawing
  svg() { return (this.defs.length ? `<defs>${this.defs.map(g => g.svg()).join('')}</defs>` : '') + this.out.join('') }
}
