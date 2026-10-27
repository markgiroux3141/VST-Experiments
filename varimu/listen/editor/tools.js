// The drawing tools: what the left button does on the canvas in each mode, and the keys
// that act on the selection. Panning (middle or right button, space + drag) and zoom stay
// in main.js and camera.js; every change to the drawing goes through main's `apply`, so
// it is undoable and recompiled.
//
//   select   click selects (shift adds), drag moves (wires follow), drag from a pin draws a
//            wire, drag on the empty canvas selects a box; Delete, R (rotate), X (mirror),
//            arrows (nudge), Ctrl+C / X / V / D / A
//   wire     click to add corners (L-shaped, / flips the corner), ends on a pin or wire,
//            Enter, a double click or Esc
//   label    click a wire or pin to name its net
//   ground   click a wire or pin to ground it
//   place    a part from the palette follows the pointer: click places it (R, X turn it)
//   section  drag a frame, then name it

import {
  addWire, copyItems, deleteItems, emptySel, frameContents, moveItems, pasteItems, placeSymbol,
  round4, route, selectBox, selSize, snap, tf, turnItems,
} from './geom.js';
import { groundSvg, unitSvg } from './view.js';

const DRAG_PX = 3;
const LABEL_ROT = { '1,0': 0, '0,-1': 90, '-1,0': 180, '0,1': 270 };
const GROUND_ROT = { '0,1': 0, '1,0': 90, '0,-1': 180, '-1,0': 270 };
const clone = x => JSON.parse(JSON.stringify(x));

export class Tools {
  constructor(o) {
    Object.assign(this, o); // canvas, cam, view, lib, state(), apply, select, setStatus, prompt, onMode
    this.mode = 'select'; this.op = null; this.wire = null; this.place = null; this.clip = null;
    this.world = [0, 0];
  }

  get d() { return this.state().drawing; }
  get sel() { return this.state().sel; }

  setMode(mode, arg = null) {
    this.cancelOp();
    this.mode = mode;
    if (mode === 'place') this.place = { name: arg, rot: 0, mirror: false };
    this.canvas.dataset.mode = mode;
    this.view.ghost('');
    this.onMode?.(mode, arg);
    this.drawGhost();
  }

  cancelOp() {
    if (this.op?.preview) this.view.load(this.d, this.state().analysis); // drop a drag preview
    this.op = null; this.wire = null; this.place = null;
    this.view.ghost('');
  }

  /** The grid point at a screen point, or a connection point within a few pixels. */
  pointAt(sx, sy, connect = true) {
    const [x, y] = this.cam.toWorld(sx, sy);
    const near = connect ? this.view.snapPoint(x, y, 6 / this.cam.k) : null;
    return near ? [round4(near[0]), round4(near[1])] : [snap(x), snap(y)];
  }

  // --- Pointer ------------------------------------------------------------------------------------

  down(e, sx, sy) {
    const [wx, wy] = this.cam.toWorld(sx, sy), r = 7 / this.cam.k;
    if (this.mode === 'place') { this.placeAt(this.pointAt(sx, sy, false)); return; }
    if (this.mode === 'wire') { this.wireClick(this.pointAt(sx, sy), e.detail >= 2); return; }
    if (this.mode === 'label') { this.labelAt(this.pointAt(sx, sy), sx, sy); return; }
    if (this.mode === 'ground') { this.groundAt(this.pointAt(sx, sy)); return; }
    if (this.mode === 'frame') { this.op = { kind: 'frame', a: [snap(wx), snap(wy)], sx, sy }; return; }
    // select
    const handle = e.target.closest?.('[data-handle]');
    if (handle) { this.op = { kind: 'resize', i: +handle.dataset.handle, sx, sy, snapshot: clone(this.d) }; return; }
    const t = this.view.hit(wx, wy, r);
    if (t?.t === 'pin') { this.op = { kind: 'pinwire', from: [t.p.x, t.p.y], target: t, sx, sy }; return; }
    if (!t) { this.op = { kind: 'box', a: [wx, wy], sx, sy, add: e.shiftKey }; return; }
    const item = itemOf(t);
    let sel = this.sel;
    if (e.shiftKey) sel = toggle(sel, item);
    else if (!has(sel, item)) sel = only(item);
    this.select(sel, t.net ?? -1);
    this.op = { kind: 'move', sx, sy, w0: [wx, wy], sel, snapshot: clone(this.d), last: [0, 0] };
  }

  frameDown(i, e, sx, sy) {
    if (this.mode !== 'select') return false;
    const sel = e.shiftKey ? toggle(this.sel, { kind: 'frames', id: i }) : frameContents(this.d, i);
    this.select(sel, -1);
    const [wx, wy] = this.cam.toWorld(sx, sy);
    this.op = { kind: 'move', sx, sy, w0: [wx, wy], sel, snapshot: clone(this.d), last: [0, 0] };
    return true;
  }

  move(e, sx, sy) {
    this.world = this.cam.toWorld(sx, sy);
    const op = this.op;
    if (op && !op.moved && Math.hypot(sx - op.sx, sy - op.sy) > DRAG_PX) op.moved = true;
    if (op?.kind === 'move' && op.moved) {
      const dx = snap(this.world[0] - op.w0[0]), dy = snap(this.world[1] - op.w0[1]);
      if (dx === op.last[0] && dy === op.last[1]) return;
      op.last = [dx, dy];
      const tmp = clone(op.snapshot);
      moveItems(tmp, this.lib, op.sel, dx, dy);
      op.preview = true;
      this.view.load(tmp, this.state().analysis, { preview: true });
      return;
    }
    if (op?.kind === 'resize' && op.moved) {
      const f = op.snapshot.frames[op.i], tmp = clone(op.snapshot);
      tmp.frames[op.i].w = Math.max(20, snap(this.world[0] - f.x));
      tmp.frames[op.i].h = Math.max(15, snap(this.world[1] - f.y));
      op.preview = true; op.frame = tmp.frames[op.i];
      this.view.load(tmp, this.state().analysis, { preview: true });
      return;
    }
    if (op?.kind === 'box' && op.moved) {
      const [x0, y0] = op.a, [x1, y1] = this.world;
      this.view.ghost(`<rect class="boxsel" x="${Math.min(x0, x1)}" y="${Math.min(y0, y1)}" width="${Math.abs(x1 - x0)}" height="${Math.abs(y1 - y0)}"/>`);
      return;
    }
    if (op?.kind === 'frame' && op.moved) {
      const [x0, y0] = op.a, x1 = snap(this.world[0]), y1 = snap(this.world[1]);
      this.view.ghost(`<rect class="boxsel frameghost" x="${Math.min(x0, x1)}" y="${Math.min(y0, y1)}" width="${Math.abs(x1 - x0)}" height="${Math.abs(y1 - y0)}"/>`);
      return;
    }
    if (op?.kind === 'pinwire' && op.moved) {
      const p = this.pointAt(sx, sy);
      this.view.ghost(wirePath(route(op.from, p, Math.abs(p[0] - op.from[0]) >= Math.abs(p[1] - op.from[1]))));
      return;
    }
    this.drawGhost(sx, sy);
  }

  up(e, sx, sy) {
    const op = this.op; this.op = null;
    if (!op) return;
    if (op.kind === 'move') {
      if (op.moved && (op.last[0] || op.last[1])) {
        const [dx, dy] = op.last, n = selSize(op.sel);
        this.state().drawing = op.snapshot; // the drag previewed a copy
        this.apply(`move ${n === 1 ? describe(op.sel) : `${n} items`}`, d => moveItems(d, this.lib, op.sel, dx, dy));
      } else if (op.preview) this.view.load(this.d, this.state().analysis);
    } else if (op.kind === 'resize') {
      if (op.frame) {
        this.state().drawing = op.snapshot;
        const { w, h } = op.frame;
        this.apply(`resize ${op.snapshot.frames[op.i].title}`, d => { d.frames[op.i].w = w; d.frames[op.i].h = h; });
      }
    } else if (op.kind === 'box') {
      this.view.ghost('');
      if (!op.moved) { this.select(emptySel(), -1); return; }
      const [x0, y0] = op.a, [x1, y1] = this.world;
      const got = selectBox(this.d, [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)]);
      this.select(op.add ? union(this.sel, got) : got, -1);
    } else if (op.kind === 'frame') {
      this.view.ghost('');
      if (!op.moved) return;
      const [x0, y0] = op.a, x1 = snap(this.world[0]), y1 = snap(this.world[1]);
      const box = { x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) };
      if (box.w < 10 || box.h < 10) return;
      const [tx, ty] = this.cam.toScreen(box.x, box.y);
      this.prompt(tx, ty - 26, `section ${this.d.frames.length + 1}`, { title: 'Section name' }).then(title => {
        if (!title) return;
        if (this.d.frames.some(f => f.title === title)) { this.setStatus(`a section is already called ${title}`); return; }
        this.apply(`section ${title}`, d => d.frames.push({ title, ...box }));
        this.setMode('select');
      });
    } else if (op.kind === 'pinwire') {
      this.view.ghost('');
      if (!op.moved) { this.select(only({ kind: 'symbols', id: op.target.p.ref }), op.target.net); return; }
      const p = this.pointAt(sx, sy);
      const pts = route(op.from, p, Math.abs(p[0] - op.from[0]) >= Math.abs(p[1] - op.from[1]));
      this.apply(`wire from ${op.target.p.ref}.${op.target.p.name}`, d => addWire(d, pts));
    }
  }

  dblclick(e, sx, sy) {
    if (this.mode === 'wire') { this.finishWire(); return; }
    if (this.mode !== 'select') return;
    const [wx, wy] = this.cam.toWorld(sx, sy), t = this.view.hit(wx, wy, 7 / this.cam.k);
    if (t?.t === 'label') this.renameLabel(t.i, sx, sy);
    else if (t?.t === 'symbol') document.querySelector('#v-in, #v-device')?.focus();
  }

  // --- Modes ----------------------------------------------------------------------------------------

  drawGhost(sx, sy) {
    if (sx === undefined) { if (!this.lastScreen) return; [sx, sy] = this.lastScreen; }
    this.lastScreen = [sx, sy];
    if (this.mode === 'place' && this.place) {
      const [x, y] = this.pointAt(sx, sy, false), sym = this.lib[this.place.name];
      this.view.ghost(`<g class="ghostpart">${unitSvg(sym, 1, { x, y, rot: this.place.rot, mirror: this.place.mirror })}</g>`);
    } else if (this.mode === 'wire') {
      const p = this.pointAt(sx, sy);
      const pts = this.wire ? [...this.wire.pts, ...route(this.wire.pts.at(-1), p, this.wire.hfirst).slice(1)] : null;
      this.view.ghost((pts ? wirePath(pts) : '') + `<circle class="cursorpt" cx="${p[0]}" cy="${p[1]}" r="0.45"/>`);
    } else if (this.mode === 'label' || this.mode === 'ground') {
      const p = this.pointAt(sx, sy);
      this.view.ghost(this.mode === 'ground' ? `<g class="ghostpart">${groundSvg({ x: p[0], y: p[1], rot: this.autoRot(p, GROUND_ROT) })}</g>`
                                             : `<circle class="cursorpt" cx="${p[0]}" cy="${p[1]}" r="0.45"/>`);
    } else if (this.mode === 'frame' && !this.op) {
      const p = this.pointAt(sx, sy, false);
      this.view.ghost(`<circle class="cursorpt" cx="${p[0]}" cy="${p[1]}" r="0.45"/>`);
    }
  }

  placeAt(p) {
    const { name, rot, mirror } = this.place;
    let ref = null;
    this.apply(`place ${name}`, d => { ref = placeSymbol(d, this.lib, name, p[0], p[1], rot, mirror); })
      .then(() => { if (ref) { this.select(only({ kind: 'symbols', id: ref }), -1); this.drawGhost(); } });
  }

  wireClick(p, double) {
    if (!this.wire) { this.wire = { pts: [p], hfirst: true }; this.drawGhost(); return; }
    const w = this.wire, last = w.pts.at(-1);
    if (p[0] !== last[0] || p[1] !== last[1]) {
      w.pts.push(...route(last, p, w.hfirst).slice(1));
      // Ending on something that connects (a pin, another wire, a label) finishes the wire.
      const t = this.view.hit(p[0], p[1], 0.05, ['pin', 'wire', 'label', 'ground']);
      if (t || double) { this.finishWire(); return; }
    } else if (double) { this.finishWire(); return; }
    this.drawGhost();
  }

  finishWire() {
    const w = this.wire; this.wire = null; this.view.ghost('');
    if (w && w.pts.length >= 2) this.apply('wire', d => addWire(d, w.pts));
  }

  /** The rotation that points away from the wire a point ends, else 0. */
  autoRot(p, table) {
    for (const w of this.d.wires) {
      for (const [e, q] of [[w[0], w[1]], [w.at(-1), w.at(-2)]]) {
        if (Math.abs(e[0] - p[0]) < 1e-3 && Math.abs(e[1] - p[1]) < 1e-3) {
          const dir = `${Math.sign(round4(e[0] - q[0]))},${Math.sign(round4(e[1] - q[1]))}`;
          if (dir in table) return table[dir];
        }
      }
    }
    const pin = this.view.pins.find(q => Math.abs(q.x - p[0]) < 1e-3 && Math.abs(q.y - p[1]) < 1e-3);
    if (pin) { // away from the body: the pin's line points into it
      const s = this.lib[this.d.symbols[pin.ref].symbol].units[pin.unit - 1].find(q => q.number === pin.number);
      const pl = this.d.symbols[pin.ref].units[pin.unit];
      const a = [s.x, s.y], b = [s.x + s.into[0], s.y + s.into[1]];
      const [ax, ay] = tf(...a, pl), [bx, by] = tf(...b, pl);
      const dir = `${Math.sign(round4(ax - bx))},${Math.sign(round4(ay - by))}`;
      if (dir in table) return table[dir];
    }
    return 0;
  }

  labelAt(p, sx, sy) {
    const names = [...new Set(this.state().analysis.nets.map(n => n.node).filter(n => !n.startsWith('n_') && n !== '0'))];
    this.prompt(sx + 8, sy - 14, '', { title: 'Net name', options: names }).then(name => {
      if (!name) return;
      if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) { this.setStatus(`${name}: a node name is letters, digits and _`); return; }
      this.apply(`label ${name}`, d => d.labels.push({ name, x: p[0], y: p[1], rot: this.autoRot(p, LABEL_ROT) }));
    });
  }

  renameLabel(i, sx, sy) {
    const old = this.d.labels[i].name;
    this.prompt(sx + 8, sy - 14, old, { title: 'Net name' }).then(name => {
      if (!name || name === old) return;
      this.apply(`rename ${old} → ${name}`, d => { d.labels[i].name = name; });
    });
  }

  groundAt(p) {
    this.apply('ground', d => d.grounds.push({ x: p[0], y: p[1], rot: this.autoRot(p, GROUND_ROT) }));
  }

  // --- Keys -----------------------------------------------------------------------------------------

  /** Handle a key; true when it was the tools'. */
  key(e) {
    const k = e.key, mod = e.ctrlKey || e.metaKey;
    if (k === 'Escape') {
      if (this.mode === 'wire' && this.wire) { if (this.wire.pts.length >= 2) this.finishWire(); else { this.wire = null; this.view.ghost(''); } return true; }
      if (this.mode !== 'select') { this.setMode('select'); return true; }
      return false;
    }
    if (this.mode === 'wire' && k === 'Enter') { this.finishWire(); return true; }
    if (this.mode === 'wire' && k === '/') { if (this.wire) this.wire.hfirst = !this.wire.hfirst; this.drawGhost(); return true; }
    if (this.mode === 'place' && (k === 'r' || k === 'R')) { this.place.rot = (this.place.rot + 90) % 360; this.drawGhost(); return true; }
    if (this.mode === 'place' && (k === 'x' || k === 'X')) { this.place.mirror = !this.place.mirror; this.drawGhost(); return true; }
    if (!mod && !e.altKey) {
      const modes = { v: 'select', w: 'wire', l: 'label', g: 'ground', s: 'frame' };
      if (modes[k.toLowerCase()]) { this.setMode(modes[k.toLowerCase()]); return true; }
    }
    if (this.mode !== 'select') return false;
    const sel = this.sel, n = selSize(sel);
    if ((k === 'Delete' || k === 'Backspace') && n) { this.apply(`delete ${n === 1 ? describe(sel) : `${n} items`}`, d => deleteItems(d, sel)).then(() => this.select(emptySel(), -1)); return true; }
    if ((k === 'r' || k === 'R') && !mod && n) { this.apply(`rotate ${describe(sel)}`, d => turnItems(d, this.lib, sel, 'rotate')); return true; }
    if ((k === 'x' || k === 'X') && !mod && n) { this.apply(`mirror ${describe(sel)}`, d => turnItems(d, this.lib, sel, 'mirror')); return true; }
    const nudge = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[k];
    if (nudge && n) {
      const step = (e.shiftKey ? 5 : 1) * 1.27;
      this.apply(`nudge ${describe(sel)}`, d => moveItems(d, this.lib, sel, nudge[0] * step, nudge[1] * step));
      return true;
    }
    if (mod && (k === 'c' || k === 'C' || k === 'x' || k === 'X') && n) {
      this.clip = copyItems(this.d, this.lib, sel);
      if (k.toLowerCase() === 'x') this.apply(`cut ${n} items`, d => deleteItems(d, sel)).then(() => this.select(emptySel(), -1));
      else this.setStatus(`copied ${n} item${n > 1 ? 's' : ''}`);
      return true;
    }
    if (mod && (k === 'v' || k === 'V') && this.clip) { this.pasteAt(this.world); return true; }
    if (mod && (k === 'd' || k === 'D') && n) {
      const clip = copyItems(this.d, this.lib, sel), b = selBounds(this.d, sel);
      this.paste(clip, [b[0] + 5.08, b[1] + 5.08]);
      return true;
    }
    if (mod && (k === 'a' || k === 'A')) {
      this.select({ symbols: Object.keys(this.d.symbols), wires: this.d.wires.map((_, i) => i), labels: this.d.labels.map((_, i) => i),
                    grounds: this.d.grounds.map((_, i) => i), frames: [] }, -1);
      return true;
    }
    return false;
  }

  pasteAt(p) { this.paste(this.clip, p); }

  paste(clip, p) {
    let got = null;
    this.apply(`paste ${Object.keys(clip.symbols).length} parts`, d => { got = pasteItems(d, this.lib, clip, p[0], p[1]); })
      .then(() => { if (got) this.select(got, -1); });
  }
}

// --- Helpers ----------------------------------------------------------------------------------------

function itemOf(t) {
  if (t.t === 'symbol') return { kind: 'symbols', id: t.ref };
  if (t.t === 'wire') return { kind: 'wires', id: t.i };
  if (t.t === 'label') return { kind: 'labels', id: t.i };
  if (t.t === 'ground') return { kind: 'grounds', id: t.i };
  return { kind: 'symbols', id: t.p.ref };
}
const only = item => ({ ...emptySel(), [item.kind]: [item.id] });
const has = (sel, item) => sel[item.kind].includes(item.id);
function toggle(sel, item) {
  const s = clone(sel);
  s[item.kind] = has(sel, item) ? s[item.kind].filter(x => x !== item.id) : [...s[item.kind], item.id];
  return s;
}
function union(a, b) {
  const s = clone(a);
  for (const k of Object.keys(s)) for (const x of b[k]) if (!s[k].includes(x)) s[k].push(x);
  return s;
}
function describe(sel) {
  if (sel.symbols.length === 1 && selSize(sel) === 1) return sel.symbols[0];
  const n = selSize(sel);
  return n === 1 ? Object.entries(sel).find(([, v]) => v.length)[0].replace(/s$/, '') : `${n} items`;
}
function selBounds(d, sel) {
  const pts = [];
  for (const r of sel.symbols) for (const pl of Object.values(d.symbols[r].units)) pts.push([pl.x, pl.y]);
  for (const i of sel.wires) pts.push(...d.wires[i]);
  for (const i of sel.labels) pts.push([d.labels[i].x, d.labels[i].y]);
  for (const i of sel.grounds) pts.push([d.grounds[i].x, d.grounds[i].y]);
  return [Math.min(...pts.map(p => p[0])), Math.min(...pts.map(p => p[1]))];
}
const wirePath = pts => `<path class="wireghost" d="M${pts.map(p => p.join(',')).join(' L')}"/>`;

