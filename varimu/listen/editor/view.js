// The drawing as SVG, and what is under a point (hit testing in world coordinates).
// Layers: frames, wires, symbols, labels and grounds, texts, junctions, open pins, then the
// overlays (problem markers, selection, hover, a highlighted net's pins, and the ghost
// layer the tools draw into: a part being placed, a wire being drawn, a selection box).
// Text stays upright whatever a symbol's rotation, as on a printed schematic.

import { esc, parseEng, unitOf } from './eng.js';
import { tf } from './geom.js';

const CELL = 5; // mm, the hit-test grid
const FAR_K = 2.6; // px per mm below which text is hidden

export { tf };
export const svgTransform = pl => `translate(${pl.x} ${pl.y}) rotate(${-(pl.rot || 0)}) scale(${pl.mirror ? -1 : 1} 1)`;

function compact(value, sym, params) {
  // A part's Value as printed next to it: "200kΩ", "250nF", "12AX7".
  let v = value, k = null;
  if (sym.primary && parseEng(v) === null && params[v]) { k = v; v = params[v].value; }
  const x = typeof v === 'number' ? v : parseEng(v);
  if (x === null || !sym.primary) return esc(value);
  const unit = unitOf(k, sym.primary);
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

/** The SVG of one placed unit's body and pins (also the ghost of a part being placed). */
export function unitSvg(sym, unit, pl, attrs = '') {
  const out = [`<g class="g" ${attrs} transform="${svgTransform(pl)}">`];
  for (const g of sym.graphics) {
    if (g.d) out.push(`<path d="${g.d}"${g.fill ? ' class="fill"' : ''}/>`);
    else out.push(`<text x="${g.x}" y="${g.y}" style="font-size:${g.size}px">${esc(g.text)}</text>`);
  }
  for (const p of sym.units[unit - 1] || []) out.push(`<line x1="${p.x}" y1="${p.y}" x2="${p.x + p.into[0] * p.length}" y2="${p.y + p.into[1] * p.length}"/>`);
  out.push('</g>');
  return out.join('');
}

export const groundSvg = (g, attrs = '') => `<g class="gnd" ${attrs} transform="${svgTransform(g)}"><line x1="0" y1="0" x2="0" y2="1.27"/>` +
  '<line x1="-1.52" y1="1.27" x2="1.52" y2="1.27"/><line x1="-0.95" y1="1.9" x2="0.95" y2="1.9"/><line x1="-0.38" y1="2.5" x2="0.38" y2="2.5"/></g>';

// A label's text beside its point: above a horizontal wire, past the end of a vertical one.
const LABEL_AT = { 0: [0.3, -0.85, 'start'], 180: [-0.3, -0.85, 'end'], 90: [0, -1.0, 'middle'], 270: [0, 1.05, 'middle'] };
export const labelSvg = (l, attrs = '') => {
  const [ax, ay, anchor] = LABEL_AT[l.rot || 0];
  return `<g class="lblg" ${attrs}><circle class="lbldot" cx="${l.x}" cy="${l.y}" r="0.32"/>` +
         `<text class="lbl" x="${l.x + ax}" y="${l.y + ay}" text-anchor="${anchor}">${esc(l.name)}</text></g>`;
};

export class View {
  constructor(svg, world, titles, lib) {
    this.svg = svg; this.world = world; this.titles = titles; this.lib = lib;
    this.sel = { symbols: [], wires: [], labels: [], grounds: [], frames: [] };
    this.net = -1; this.hover = { net: -1, ref: null }; this.markers = []; this.focus = -1;
  }

  /** Draw `drawing`. `preview`: a drawing being dragged, its nets not recomputed yet. */
  load(drawing, analysis, { preview = false } = {}) {
    this.d = drawing; this.a = analysis; this.preview = preview;
    const d = drawing, lib = this.lib, params = analysis.params || {};
    this.wireNet = d.wires.map(() => -1);
    this.labelNet = d.labels.map(() => -1);
    this.groundNet = d.grounds.map(() => -1);
    this.pinNet = new Map();
    if (!preview) analysis.nets.forEach((n, i) => {
      n.wires.forEach(w => this.wireNet[w] = i);
      n.labels.forEach(l => this.labelNet[l] = i);
      n.grounds.forEach(g => this.groundNet[g] = i);
      n.pins.forEach(([r, u, num]) => this.pinNet.set(`${r}/${u}/${num}`, i));
    });
    this.pins = []; this.boxes = new Map(); this.section = new Map();
    const out = [], texts = [];

    out.push('<g class="frames">');
    d.frames.forEach((f, i) => out.push(`<rect class="frame" data-frame="${i}" x="${f.x}" y="${f.y}" width="${f.w}" height="${f.h}" rx="1.5"/>`));
    out.push('</g><g class="wires">');
    d.wires.forEach((w, i) => out.push(`<path class="wire" data-wire="${i}" data-net="${this.wireNet[i]}" d="M${w.map(p => p.join(',')).join(' L')}"/>`));
    out.push('</g><g class="syms">');
    for (const [ref, s] of Object.entries(d.symbols)) {
      const sym = lib[s.symbol]; if (!sym) continue;
      const multi = sym.units.length > 1;
      let box = null;
      for (const [u, pl] of Object.entries(s.units)) {
        out.push(unitSvg(sym, +u, pl, `data-ref="${esc(ref)}"`));
        for (const p of sym.units[u - 1] || []) {
          const [x, y] = tf(p.x, p.y, pl);
          this.pins.push({ x, y, ref, unit: +u, number: p.number, name: p.name, net: this.pinNet.get(`${ref}/${u}/${p.number}`) ?? -1 });
        }
        const c = [[sym.box[0], sym.box[1]], [sym.box[2], sym.box[1]], [sym.box[0], sym.box[3]], [sym.box[2], sym.box[3]]].map(([x, y]) => tf(x, y, pl));
        const ub = [Math.min(...c.map(p => p[0])) - 0.6, Math.min(...c.map(p => p[1])) - 0.6, Math.max(...c.map(p => p[0])) + 0.6, Math.max(...c.map(p => p[1])) + 0.6];
        this.boxes.set(`${ref}/${u}`, ub);
        box = box ? [Math.min(box[0], ub[0]), Math.min(box[1], ub[1]), Math.max(box[2], ub[2]), Math.max(box[3], ub[3])] : ub;
        const [rl, vl] = textFor(ref, s, sym, params);
        const refText = multi ? `${rl}${String.fromCharCode(64 + +u)}` : rl;
        if ((pl.rot || 0) % 180 === 90 && sym.kind !== 'device') {
          // A part turned on its side: name above it, value below, both centred on it.
          const body = sym.graphics.length ? graphicsBox(sym, pl) : ub;
          const cx = (body[0] + body[2]) / 2;
          texts.push(`<text class="ref" x="${cx}" y="${body[1] - 1.5}" text-anchor="middle">${refText}</text>`);
          if (vl) texts.push(`<text class="val" x="${cx}" y="${body[3] + 1.6}" text-anchor="middle">${vl}</text>`);
        } else for (const [txt, pos, cls] of [[refText, sym.text.ref, 'ref'], [vl, sym.text.value, 'val']]) {
          if (!txt) continue;
          const [x, y] = tf(pos[0], pos[1], pl), [ox, oy] = tf(0, 0, pl);
          const dx = x - ox, dy = y - oy, horiz = Math.abs(dx) >= Math.abs(dy) - 1e-6;
          const anchor = !horiz ? 'middle' : dx >= 0 ? 'start' : 'end';
          texts.push(`<text class="${cls}" x="${x}" y="${y}" text-anchor="${anchor}">${txt}</text>`);
        }
      }
      if (box) this.boxes.set(ref, box);
    }
    out.push('</g><g class="labels">');
    d.labels.forEach((l, i) => out.push(labelSvg(l, `data-label="${i}" data-net="${this.labelNet[i]}"`)));
    d.grounds.forEach((g, i) => out.push(groundSvg(g, `data-ground="${i}" data-net="${this.groundNet[i]}"`)));
    out.push('</g><g class="texts">', ...texts, '</g><g class="junctions">');
    if (!preview) for (const [x, y] of analysis.junctions) out.push(`<circle class="jn" cx="${x}" cy="${y}" r="0.42"/>`);
    out.push('</g><g class="openpins">');
    // Pins with nothing on them: what still needs a wire.
    if (!preview) for (const p of this.pins) if (p.net < 0 || (analysis.nets[p.net]?.pins.length === 1 && !analysis.nets[p.net].labels.length && !analysis.nets[p.net].grounds.length))
      out.push(`<circle class="openpin" cx="${p.x}" cy="${p.y}" r="0.55"/>`);
    out.push('</g><g id="markers"></g><g id="selection"></g><g id="overlay"></g><g id="ghost"></g>');
    this.world.innerHTML = out.join('');
    this.markersG = this.world.querySelector('#markers');
    this.selG = this.world.querySelector('#selection');
    this.overlay = this.world.querySelector('#overlay');
    this.ghostG = this.world.querySelector('#ghost');

    this.netEls = new Map();
    for (const el of this.world.querySelectorAll('[data-net]')) {
      const i = +el.dataset.net; if (i < 0) continue;
      if (!this.netEls.has(i)) this.netEls.set(i, []);
      this.netEls.get(i).push(el);
    }
    for (const [ref, s] of Object.entries(d.symbols)) {
      const us = Object.keys(s.units).map(Number); if (!us.length) continue;
      const pl = s.units[Math.min(...us)];
      const f = d.frames.find(f => pl.x >= f.x && pl.x <= f.x + f.w && pl.y >= f.y && pl.y <= f.y + f.h);
      this.section.set(ref, f ? f.title : 'main');
    }
    this.buildIndex();
    this.renderTitles();
    this.drawSelection();
    this.drawOverlay();
    if (!preview) this.setMarkers(this.markers, this.focus);
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
      const box = { 0: [l.x - 0.4, l.y - 1.6, l.x + w, l.y + 0.4], 180: [l.x - w, l.y - 1.6, l.x + 0.4, l.y + 0.4],
                    90: [l.x - w / 2, l.y - 1.8, l.x + w / 2, l.y + 0.4], 270: [l.x - w / 2, l.y - 0.4, l.x + w / 2, l.y + 1.8] }[rot];
      add(...box, { t: 'label', i, box, net: this.labelNet[i] });
    });
    this.d.grounds.forEach((g, i) => add(g.x - 1.8, g.y - 1.8, g.x + 1.8, g.y + 1.8, { t: 'ground', i, box: [g.x - 1.7, g.y - 1.7, g.x + 1.7, g.y + 1.7], net: this.groundNet[i] }));
    for (const [k, box] of this.boxes) if (k.includes('/')) add(...box, { t: 'symbol', ref: k.split('/')[0], unit: +k.split('/')[1], box });
  }

  /** What is at world point (x, y), within `r` mm: a pin, a wire, a label or ground (all
   *  with their net), else a symbol. `only`: kinds to consider. */
  hit(x, y, r, only = null) {
    const near = [];
    for (let cx = Math.floor((x - r) / CELL); cx <= Math.floor((x + r) / CELL); cx++)
      for (let cy = Math.floor((y - r) / CELL); cy <= Math.floor((y + r) / CELL); cy++)
        for (const it of this.grid.get(`${cx},${cy}`) || []) near.push(it);
    let best = null, bestD = Infinity;
    const consider = (it, dist, rank) => { const s = dist + rank * r; if (s < bestD) { bestD = s; best = it; } };
    for (const it of near) {
      if (only && !only.includes(it.t)) continue;
      if (it.t === 'pin') { const dd = Math.hypot(it.p.x - x, it.p.y - y); if (dd <= r) consider(it, dd, 0); }
      else if (it.t === 'wire') { const dd = segDist(x, y, it.a, it.b); if (dd <= r) consider(it, dd, 0.3); }
      else if (it.t === 'label' || it.t === 'ground') { if (inBox(x, y, it.box, r * 0.3)) consider(it, 0, 0.5); }
      else if (it.t === 'symbol') { if (inBox(x, y, it.box, 0)) consider(it, 0, 2); }
    }
    return best;
  }

  /** A connection point near (x, y): a pin, a wire's end or bend, or a point on a wire. */
  snapPoint(x, y, r) {
    let best = null, bd = r;
    for (const p of this.pins) { const dd = Math.hypot(p.x - x, p.y - y); if (dd < bd) { bd = dd; best = [p.x, p.y]; } }
    if (best) return best;
    for (const w of this.d.wires) for (const p of w) { const dd = Math.hypot(p[0] - x, p[1] - y); if (dd < bd) { bd = dd; best = p; } }
    return best;
  }

  bounds() {
    const xs = [], ys = [];
    for (const f of this.d.frames) { xs.push(f.x, f.x + f.w); ys.push(f.y - 6, f.y + f.h); }
    for (const b of this.boxes.values()) { xs.push(b[0], b[2]); ys.push(b[1], b[3]); }
    for (const w of this.d.wires) for (const [x, y] of w) { xs.push(x); ys.push(y); }
    if (!xs.length) return [-60, -40, 60, 40];
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  }

  netBox(i) {
    const xs = [], ys = [], n = this.a.nets[i];
    if (!n) return null;
    for (const w of n.wires) for (const [x, y] of this.d.wires[w] || []) { xs.push(x); ys.push(y); }
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

  /** The selected items (geom's selection) and the net shown in the inspector. */
  setSelection(sel, net = -1) { this.sel = sel; this.net = net; this.drawSelection(); this.drawOverlay(); }

  drawSelection() {
    if (!this.selG) return;
    const out = [], s = this.sel;
    for (const ref of s.symbols) for (const [k, b] of this.boxes) if (k.startsWith(ref + '/'))
      out.push(`<rect class="sel" x="${b[0]}" y="${b[1]}" width="${b[2] - b[0]}" height="${b[3] - b[1]}" rx="0.8"/>`);
    for (const i of s.wires) { const w = this.d.wires[i]; if (w) out.push(`<path class="selwire" d="M${w.map(p => p.join(',')).join(' L')}"/>`); }
    for (const i of s.labels) { const l = this.d.labels[i]; if (l) out.push(`<circle class="selpt" cx="${l.x}" cy="${l.y}" r="0.7"/>`); }
    for (const i of s.grounds) { const g = this.d.grounds[i]; if (g) out.push(`<circle class="selpt" cx="${g.x}" cy="${g.y}" r="0.7"/>`); }
    for (const i of s.frames) {
      const f = this.d.frames[i]; if (!f) continue;
      out.push(`<rect class="selframe" x="${f.x}" y="${f.y}" width="${f.w}" height="${f.h}" rx="1.5"/>`);
      out.push(`<rect class="handle" data-handle="${i}" x="${f.x + f.w - 1.2}" y="${f.y + f.h - 1.2}" width="2.4" height="2.4" rx="0.4"/>`);
    }
    this.selG.innerHTML = out.join('');
    for (const el of this.titles.children) el.classList.toggle('on', s.frames.includes(+el.dataset.i));
  }

  drawOverlay() {
    if (!this.overlay) return;
    for (const el of this.world.querySelectorAll('.hl')) el.classList.remove('hl');
    const nets = new Set();
    if (this.hover.net >= 0) nets.add(this.hover.net);
    if (this.net >= 0) nets.add(this.net);
    const out = [];
    for (const i of nets) {
      for (const el of this.netEls.get(i) || []) el.classList.add('hl');
      for (const p of this.pins) if (p.net === i) out.push(`<circle class="pindot" cx="${p.x}" cy="${p.y}" r="0.5"/>`);
    }
    if (this.hover.ref && !this.sel.symbols.includes(this.hover.ref)) for (const [k, b] of this.boxes) if (k.startsWith(this.hover.ref + '/'))
      out.unshift(`<rect class="hov" x="${b[0]}" y="${b[1]}" width="${b[2] - b[0]}" height="${b[3] - b[1]}" rx="0.8"/>`);
    this.overlay.innerHTML = out.join('');
  }

  ghost(html) { if (this.ghostG) this.ghostG.innerHTML = html || ''; }

  setMarkers(markers, focus = -1) {
    this.markers = markers; this.focus = focus;
    if (!this.markersG) return;
    for (const el of this.world.querySelectorAll('.bad')) el.classList.remove('bad');
    const out = [];
    markers.forEach((m, mi) => {
      for (const i of m.nets) for (const el of this.netEls.get(i) || []) el.classList.add('bad');
      if (m.check !== 'unconnected') for (const ref of m.symbols) for (const [k, b] of this.boxes) if (k.startsWith(ref + '/'))
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
    this.cam = cam;
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
      `<div class="ftitle${this.sel.frames.includes(i) ? ' on' : ''}" data-i="${i}" data-x="${f.x}" data-y="${f.y}">${esc(f.title)}<span>${count.get(f.title) || 0}</span></div>`).join('');
    if (this.cam) this.onCamera(this.cam);
  }
}

/** The box of a placed symbol's body (its graphics, without the pins). */
function graphicsBox(sym, pl) {
  // The library's box includes the pins; the body is the box less the pin lengths.
  const pins = sym.units.flat(), b = sym.box;
  let [x0, y0, x1, y1] = b;
  for (const p of pins) {
    if (p.into[1] === 1) y0 = Math.max(y0, p.y + p.length);
    if (p.into[1] === -1) y1 = Math.min(y1, p.y - p.length);
    if (p.into[0] === 1) x0 = Math.max(x0, p.x + p.length);
    if (p.into[0] === -1) x1 = Math.min(x1, p.x - p.length);
  }
  const c = [[x0, y0], [x1, y0], [x0, y1], [x1, y1]].map(([x, y]) => tf(x, y, pl));
  return [Math.min(...c.map(p => p[0])), Math.min(...c.map(p => p[1])), Math.max(...c.map(p => p[0])), Math.max(...c.map(p => p[1]))];
}

function segDist(x, y, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1], L = dx * dx + dy * dy;
  const t = L ? Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / L)) : 0;
  return Math.hypot(x - (a[0] + t * dx), y - (a[1] + t * dy));
}
const inBox = (x, y, b, m) => x >= b[0] - m && x <= b[2] + m && y >= b[1] - m && y <= b[3] + m;
