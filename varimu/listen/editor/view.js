// The drawing as SVG, and what is under a point (hit testing in world coordinates).
// Layers: frames, wires, symbols, labels and grounds, junctions, then the overlays
// (problem markers, hover, selection, a highlighted net's pins). Text stays upright
// whatever a symbol's rotation, as on a printed schematic.

import { esc, parseEng, unitOf } from './eng.js';

const NS = 'http://www.w3.org/2000/svg';
const ROT = { 0: [1, 0], 90: [0, 1], 180: [-1, 0], 270: [0, -1] };
const CELL = 5; // mm, the hit-test grid
const FAR_K = 2.6; // px per mm below which text is hidden

/** A symbol point (y down) placed: mirrored, rotated `rot` counter-clockwise, moved
 *  (varimu.editor.symbols.transform). */
export function tf(x, y, pl) {
  if (pl.mirror) x = -x;
  const [c, s] = ROT[pl.rot || 0];
  return [pl.x + x * c + y * s, pl.y - x * s + y * c];
}
const svgTransform = pl => `translate(${pl.x} ${pl.y}) rotate(${-(pl.rot || 0)}) scale(${pl.mirror ? -1 : 1} 1)`;

function compact(value, sym, params) {
  // A part's Value as printed next to it: "200kΩ", "250nF", "12AX7".
  let v = value, key = null;
  if (sym.primary && parseEng(v) === null && params[v]) { key = v; v = params[v].value; }
  const x = typeof v === 'number' ? v : parseEng(v);
  if (x === null || !sym.primary) return esc(value);
  const unit = unitOf(key, sym.primary);
  const a = Math.abs(x);
  const pre = [[1e9, 'G'], [1e6, 'M'], [1e3, 'k'], [1, ''], [1e-3, 'm'], [1e-6, 'µ'], [1e-9, 'n'], [1e-12, 'p']]
    .find(([s]) => a >= s * 0.9995) || [1e-12, 'p'];
  const n = a === 0 ? '0' : String(+(x / pre[0]).toPrecision(4));
  return esc(`${n}${a === 0 ? '' : pre[1]}${unit}`);
}

function textFor(ref, s, sym, params) {
  // [reference line, value line] for a placed symbol.
  const p = k => { const f = s.fields[k]; return f && params[f] ? params[f].value : f; };
  if (sym.kind === 'winding') return [ref, `${s.fields.Transformer || '?'} · ${s.value}`];
  if (sym.kind === 'core') return [ref, p('material') || 'core'];
  if (sym.kind === 'switch') return [ref, s.fields.Control || ''];
  return [ref, compact(s.value, sym, params)];
}

export class View {
  constructor(svg, world, titles, lib) {
    this.svg = svg; this.world = world; this.titles = titles; this.lib = lib;
  }

  load(drawing, analysis) {
    this.d = drawing; this.a = analysis;
    const d = drawing, lib = this.lib, params = analysis.params || {};
    // Net of every wire, label and ground; pins of every placed unit.
    this.wireNet = d.wires.map(() => -1);
    this.labelNet = d.labels.map(() => -1);
    this.groundNet = d.grounds.map(() => -1);
    this.pinNet = new Map();
    analysis.nets.forEach((n, i) => {
      n.wires.forEach(w => this.wireNet[w] = i);
      n.labels.forEach(l => this.labelNet[l] = i);
      n.grounds.forEach(g => this.groundNet[g] = i);
      n.pins.forEach(([r, u, num]) => this.pinNet.set(`${r}/${u}/${num}`, i));
    });
    this.pins = []; this.boxes = new Map(); this.section = new Map();
    const out = [];

    out.push('<g class="frames">');
    for (const f of d.frames) out.push(`<rect class="frame" x="${f.x}" y="${f.y}" width="${f.w}" height="${f.h}" rx="1.5"/>`);
    out.push('</g><g class="wires">');
    d.wires.forEach((w, i) => out.push(`<path class="wire" data-net="${this.wireNet[i]}" d="M${w.map(p => p.join(',')).join(' L')}"/>`));
    out.push('</g><g class="syms">');
    const texts = [];
    for (const [ref, s] of Object.entries(d.symbols)) {
      const sym = lib[s.symbol]; if (!sym) continue;
      const multi = sym.units.length > 1;
      let box = null;
      for (const [u, pl] of Object.entries(s.units)) {
        const pins = sym.units[u - 1] || [];
        out.push(`<g class="g" data-ref="${esc(ref)}" transform="${svgTransform(pl)}">`);
        for (const g of sym.graphics) {
          if (g.d) out.push(`<path d="${g.d}"${g.fill ? ' class="fill"' : ''}/>`);
          else out.push(`<text x="${g.x}" y="${g.y}" style="font-size:${g.size}px">${esc(g.text)}</text>`);
        }
        for (const p of pins) out.push(`<line x1="${p.x}" y1="${p.y}" x2="${p.x + p.into[0] * p.length}" y2="${p.y + p.into[1] * p.length}"/>`);
        out.push('</g>');
        for (const p of pins) {
          const [x, y] = tf(p.x, p.y, pl);
          this.pins.push({ x, y, ref, unit: +u, number: p.number, name: p.name, net: this.pinNet.get(`${ref}/${u}/${p.number}`) ?? -1 });
        }
        const c = [[sym.box[0], sym.box[1]], [sym.box[2], sym.box[1]], [sym.box[0], sym.box[3]], [sym.box[2], sym.box[3]]].map(([x, y]) => tf(x, y, pl));
        const ub = [Math.min(...c.map(p => p[0])), Math.min(...c.map(p => p[1])), Math.max(...c.map(p => p[0])), Math.max(...c.map(p => p[1]))];
        const ubox = [ub[0] - 0.6, ub[1] - 0.6, ub[2] + 0.6, ub[3] + 0.6];
        this.boxes.set(`${ref}/${u}`, ubox);
        box = box ? [Math.min(box[0], ubox[0]), Math.min(box[1], ubox[1]), Math.max(box[2], ubox[2]), Math.max(box[3], ubox[3])] : ubox;
        // Reference and Value, upright, beside the body.
        const [rl, vl] = textFor(ref, s, sym, params);
        const refText = multi ? `${rl}${String.fromCharCode(64 + +u)}` : rl;
        for (const [txt, pos, cls] of [[refText, sym.text.ref, 'ref'], [vl, sym.text.value, 'val']]) {
          if (!txt) continue;
          const [x, y] = tf(pos[0], pos[1], pl);
          const [ox, oy] = tf(0, 0, pl);
          const dx = x - ox, dy = y - oy, horiz = Math.abs(dx) >= Math.abs(dy) - 1e-6;
          const anchor = !horiz ? 'middle' : dx >= 0 ? 'start' : 'end';
          texts.push(`<text class="${cls}" x="${x}" y="${y}" text-anchor="${anchor}">${txt}</text>`);
        }
      }
      if (box) this.boxes.set(ref, box);
    }
    out.push('</g><g class="labels">');
    d.labels.forEach((l, i) => {
      const net = this.labelNet[i], rot = l.rot || 0;
      const [ax, ay, anchor] = { 0: [0.5, 0, 'start'], 180: [-0.5, 0, 'end'], 90: [0, -0.95, 'middle'], 270: [0, 0.95, 'middle'] }[rot];
      out.push(`<text class="lbl" data-net="${net}" x="${l.x + ax}" y="${l.y + ay}" text-anchor="${anchor}">${esc(l.name)}</text>`);
    });
    d.grounds.forEach((g, i) => {
      out.push(`<g class="gnd" data-net="${this.groundNet[i]}" transform="${svgTransform(g)}"><line x1="0" y1="0" x2="0" y2="1.27"/>` +
        '<line x1="-1.52" y1="1.27" x2="1.52" y2="1.27"/><line x1="-0.95" y1="1.9" x2="0.95" y2="1.9"/><line x1="-0.38" y1="2.5" x2="0.38" y2="2.5"/></g>');
    });
    out.push('</g><g class="texts">', ...texts, '</g><g class="junctions">');
    for (const [x, y] of analysis.junctions) out.push(`<circle class="jn" cx="${x}" cy="${y}" r="0.42"/>`);
    out.push('</g><g id="markers"></g><g id="overlay"></g>');
    this.world.innerHTML = out.join('');
    this.markersG = this.world.querySelector('#markers');
    this.overlay = this.world.querySelector('#overlay');

    this.netEls = new Map();
    for (const el of this.world.querySelectorAll('[data-net]')) {
      const i = +el.dataset.net; if (i < 0) continue;
      if (!this.netEls.has(i)) this.netEls.set(i, []);
      this.netEls.get(i).push(el);
    }
    for (const [ref] of Object.entries(d.symbols)) {
      const s = d.symbols[ref], u = Math.min(...Object.keys(s.units).map(Number));
      const pl = s.units[u]; if (!pl) continue;
      const f = d.frames.find(f => pl.x >= f.x && pl.x <= f.x + f.w && pl.y >= f.y && pl.y <= f.y + f.h);
      this.section.set(ref, f ? f.title : 'main');
    }
    this.buildIndex();
    this.hover = { net: -1, ref: null }; this.selected = null; this.markers = [];
    this.renderTitles();
  }

  // --- Geometry -------------------------------------------------------------------------------

  buildIndex() {
    const grid = this.grid = new Map();
    const add = (x0, y0, x1, y1, item) => {
      for (let cx = Math.floor(x0 / CELL); cx <= Math.floor(x1 / CELL); cx++)
        for (let cy = Math.floor(y0 / CELL); cy <= Math.floor(y1 / CELL); cy++) {
          const k = `${cx},${cy}`; if (!grid.has(k)) grid.set(k, []); grid.get(k).push(item);
        }
    };
    this.d.wires.forEach((w, i) => {
      for (let j = 0; j + 1 < w.length; j++) {
        const [a, b] = [w[j], w[j + 1]];
        add(Math.min(a[0], b[0]) - 1, Math.min(a[1], b[1]) - 1, Math.max(a[0], b[0]) + 1, Math.max(a[1], b[1]) + 1, { t: 'wire', i, a, b, net: this.wireNet[i] });
      }
    });
    for (const p of this.pins) add(p.x - 1, p.y - 1, p.x + 1, p.y + 1, { t: 'pin', p, net: p.net });
    this.d.labels.forEach((l, i) => {
      const w = 0.83 * 1.35 * l.name.length + 0.6, rot = l.rot || 0;
      const box = { 0: [l.x, l.y - 1, l.x + w, l.y + 1], 180: [l.x - w, l.y - 1, l.x, l.y + 1],
                    90: [l.x - w / 2, l.y - 1.8, l.x + w / 2, l.y], 270: [l.x - w / 2, l.y, l.x + w / 2, l.y + 1.8] }[rot];
      add(...box, { t: 'label', i, box, net: this.labelNet[i] });
    });
    this.d.grounds.forEach((g, i) => add(g.x - 1.8, g.y - 1.8, g.x + 1.8, g.y + 1.8, { t: 'ground', i, box: [g.x - 1.7, g.y - 1.7, g.x + 1.7, g.y + 1.7], net: this.groundNet[i] }));
    for (const [key, box] of this.boxes) if (key.includes('/')) add(...box, { t: 'symbol', ref: key.split('/')[0], box });
  }

  /** What is at world point (x, y), within `r` mm: a pin, a wire, a label or ground (all
   *  with their net), else a symbol. */
  hit(x, y, r) {
    const near = [];
    for (let cx = Math.floor((x - r) / CELL); cx <= Math.floor((x + r) / CELL); cx++)
      for (let cy = Math.floor((y - r) / CELL); cy <= Math.floor((y + r) / CELL); cy++)
        for (const it of this.grid.get(`${cx},${cy}`) || []) near.push(it);
    let best = null, bestD = Infinity;
    const consider = (it, dist, rank) => { const s = dist + rank * r; if (s < bestD) { bestD = s; best = it; } };
    for (const it of near) {
      if (it.t === 'pin') { const dd = Math.hypot(it.p.x - x, it.p.y - y); if (dd <= r) consider(it, dd, 0); }
      else if (it.t === 'wire') { const dd = segDist(x, y, it.a, it.b); if (dd <= r) consider(it, dd, 0.3); }
      else if (it.t === 'label' || it.t === 'ground') { if (inBox(x, y, it.box, r * 0.3)) consider(it, 0, 0.5); }
      else if (it.t === 'symbol') { if (inBox(x, y, it.box, 0)) consider(it, 0, 2); }
    }
    return best;
  }

  bounds() {
    const xs = [], ys = [];
    for (const f of this.d.frames) { xs.push(f.x, f.x + f.w); ys.push(f.y - 6, f.y + f.h); }
    for (const b of this.boxes.values()) { xs.push(b[0], b[2]); ys.push(b[1], b[3]); }
    for (const w of this.d.wires) for (const [x, y] of w) { xs.push(x); ys.push(y); }
    if (!xs.length) return [0, 0, 100, 100];
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  }

  netBox(i) {
    const xs = [], ys = [], n = this.a.nets[i];
    for (const w of n.wires) for (const [x, y] of this.d.wires[w]) { xs.push(x); ys.push(y); }
    for (const p of this.pins) if (p.net === i) { xs.push(p.x); ys.push(p.y); }
    for (const l of n.labels) { xs.push(this.d.labels[l].x); ys.push(this.d.labels[l].y); }
    return xs.length ? [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)] : null;
  }

  // --- States ---------------------------------------------------------------------------------

  setHover(h) {
    const net = h && h.net !== undefined ? h.net : -1, ref = h && h.t === 'symbol' ? h.ref : null;
    if (net === this.hover.net && ref === this.hover.ref) return;
    this.hover = { net, ref };
    this.drawOverlay();
  }

  select(sel) { this.selected = sel; this.drawOverlay(); }

  drawOverlay() {
    for (const el of this.world.querySelectorAll('.hl')) el.classList.remove('hl');
    const nets = new Set();
    if (this.hover.net >= 0) nets.add(this.hover.net);
    if (this.selected?.kind === 'net') nets.add(this.selected.net);
    const out = [];
    for (const i of nets) {
      for (const el of this.netEls.get(i) || []) el.classList.add('hl');
      for (const p of this.pins) if (p.net === i) out.push(`<circle class="pindot" cx="${p.x}" cy="${p.y}" r="0.5"/>`);
    }
    const box = (b, cls) => out.unshift(`<rect class="${cls}" x="${b[0]}" y="${b[1]}" width="${b[2] - b[0]}" height="${b[3] - b[1]}" rx="0.8"/>`);
    if (this.hover.ref && this.hover.ref !== this.selected?.ref) for (const [k, b] of this.boxes) if (k.startsWith(this.hover.ref + '/')) box(b, 'hov');
    if (this.selected?.kind === 'symbol') for (const [k, b] of this.boxes) if (k.startsWith(this.selected.ref + '/')) box(b, 'sel');
    this.overlay.innerHTML = out.join('');
  }

  setMarkers(markers, focus = -1) {
    this.markers = markers;
    for (const el of this.world.querySelectorAll('.bad')) el.classList.remove('bad');
    const out = [];
    markers.forEach((m, mi) => {
      for (const i of m.nets) for (const el of this.netEls.get(i) || []) el.classList.add('bad');
      for (const ref of m.symbols) for (const [k, b] of this.boxes) if (k.startsWith(ref + '/'))
        out.push(`<rect class="ring${mi === focus ? ' focus' : ''}" x="${b[0] - 0.8}" y="${b[1] - 0.8}" width="${b[2] - b[0] + 1.6}" height="${b[3] - b[1] + 1.6}" rx="1.4"/>`);
      if (m.check === 'unconnected') for (const i of m.nets) for (const p of this.pins) if (p.net === i)
        out.push(`<circle class="ring${mi === focus ? ' focus' : ''}" cx="${p.x}" cy="${p.y}" r="1.1"/>`);
    });
    this.markersG.innerHTML = out.join('');
  }

  markerBox(m) {
    const bs = [];
    for (const i of m.nets) { const b = this.netBox(i); if (b) bs.push(b); }
    for (const ref of m.symbols) { const b = this.boxes.get(ref); if (b) bs.push(b); }
    if (!bs.length) return null;
    return [Math.min(...bs.map(b => b[0])), Math.min(...bs.map(b => b[1])), Math.max(...bs.map(b => b[2])), Math.max(...bs.map(b => b[3]))];
  }

  // --- Camera-dependent ---------------------------------------------------------------------------

  onCamera(cam) {
    this.world.setAttribute('transform', `matrix(${cam.k} 0 0 ${cam.k} ${cam.x} ${cam.y})`);
    this.svg.classList.toggle('far', cam.k < FAR_K);
    const host = this.svg.parentElement;
    let step = 2.54; while (step * cam.k < 9) step *= 5;
    host.style.backgroundSize = `${step * cam.k}px ${step * cam.k}px`;
    host.style.backgroundPosition = `${cam.x - step * cam.k / 2}px ${cam.y - step * cam.k / 2}px`;
    for (const el of this.titles.children) {
      const [sx, sy] = cam.toScreen(+el.dataset.x, +el.dataset.y);
      el.style.left = `${sx}px`; el.style.top = `${sy}px`;
    }
  }

  renderTitles() {
    const count = new Map();
    for (const t of this.section.values()) count.set(t, (count.get(t) || 0) + 1);
    this.titles.innerHTML = this.d.frames.map((f, i) =>
      `<div class="ftitle" data-i="${i}" data-x="${f.x}" data-y="${f.y}">${esc(f.title)}<span>${count.get(f.title) || 0}</span></div>`).join('');
  }
}

function segDist(x, y, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1], L = dx * dx + dy * dy;
  const t = L ? Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / L)) : 0;
  return Math.hypot(x - (a[0] + t * dx), y - (a[1] + t * dy));
}
const inBox = (x, y, b, m) => x >= b[0] - m && x <= b[2] + m && y >= b[1] - m && y <= b[3] + m;
