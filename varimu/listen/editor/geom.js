// Topology edits on the drawing (its JSON): placing, moving, rotating, mirroring,
// deleting, copying and pasting, drawing wires. Pure functions of the drawing and the
// symbol table, tested in Node (tests/editor_js/geom.test.mjs).
//
// Coordinates are mm, y down, on the 1.27 mm grid; a placed unit is mirrored, rotated
// counter-clockwise on the screen, then moved (varimu.editor.symbols.transform). Wires
// stay attached: a wire end on a moved pin (or on a moved wire's end, label or ground)
// follows it, and its first segment keeps its direction by bending (rubber-banding).

export const GRID = 1.27;
const EPS = 1e-3;
const ROT = { 0: [1, 0], 90: [0, 1], 180: [-1, 0], 270: [0, -1] };

export const round4 = v => Math.round(v * 1e4) / 1e4;
export const snap = v => round4(Math.round(v / GRID) * GRID);
export const key = (x, y) => `${Math.round(x / EPS)},${Math.round(y / EPS)}`;
const same = (a, b) => Math.abs(a[0] - b[0]) < EPS && Math.abs(a[1] - b[1]) < EPS;

/** A symbol point (y down) placed: mirrored, rotated `rot` counter-clockwise, moved. */
export function tf(x, y, pl) {
  if (pl.mirror) x = -x;
  const [c, s] = ROT[pl.rot || 0];
  return [round4(pl.x + x * c + y * s), round4(pl.y - x * s + y * c)];
}

/** {pin number: [x, y]} of a placed unit. */
export function pinPoints(lib, s, unit) {
  const pl = s.units[unit], pins = lib[s.symbol]?.units[unit - 1] || [];
  return Object.fromEntries(pins.map(p => [p.number, tf(p.x, p.y, pl)]));
}

/** Every pin of every symbol: [{ref, unit, number, xy}]. */
export function allPins(d, lib) {
  const out = [];
  for (const [ref, s] of Object.entries(d.symbols))
    for (const u of Object.keys(s.units))
      for (const [number, xy] of Object.entries(pinPoints(lib, s, +u))) out.push({ ref, unit: +u, number, xy });
  return out;
}

/** The next free reference with `prefix`: R7 after R1..R6. */
export function nextRef(d, prefix) {
  let n = 0;
  const re = new RegExp(`^${prefix.replace(/[^A-Za-z0-9_]/g, '')}(\\d+)$`);
  for (const r of Object.keys(d.symbols)) { const m = re.exec(r); if (m) n = Math.max(n, +m[1]); }
  return `${prefix}${n + 1}`;
}

// Placeholder values for a new part: shown in the inspector to be replaced, never compiled
// without a source (the importer blocks a number without one).
const DEFAULT_VALUE = { R: '10k', C: '100n', L: '10m', Pot: '100k', Rheostat: '10k', Pot_Tapped: '1M', T_Pad: '600',
                        V: '250', Sine: '1', Mains: '117', Triode: '12AX7', Triode_Dual: '12AX7', Pentode: '6973',
                        Diode: '6X4', Diode_Dual: '6X4', Winding: 'p', K: '0.99', VR_Tube: '150' };

/** Place a new unit of symbol `name` at (x, y); returns its reference. */
export function placeSymbol(d, lib, name, x, y, rot = 0, mirror = false) {
  const sym = lib[name];
  const ref = nextRef(d, sym.prefix === '#PWR' ? 'G' : sym.prefix);
  const pl = { x: snap(x), y: snap(y) };
  if (rot) pl.rot = rot;
  if (mirror) pl.mirror = true;
  const units = { 1: pl };
  if (sym.units.length > 1) units[2] = { ...pl, x: snap(x + 25.4) };
  d.symbols[ref] = { symbol: name, value: DEFAULT_VALUE[name] ?? (sym.kind === 'switch' ? 'SW' : sym.value), fields: {}, units };
  return ref;
}

// --- Selections ---------------------------------------------------------------------------------

export const emptySel = () => ({ symbols: [], wires: [], labels: [], grounds: [], frames: [] });
export const selSize = s => s.symbols.length + s.wires.length + s.labels.length + s.grounds.length + s.frames.length;

/** What lies inside a box: whole symbols (their origin), wires (every point), labels,
 *  grounds, frames (wholly inside). */
export function selectBox(d, box) {
  const [x0, y0, x1, y1] = box, inside = ([x, y]) => x >= x0 && x <= x1 && y >= y0 && y <= y1;
  const sel = emptySel();
  for (const [ref, s] of Object.entries(d.symbols))
    if (Object.values(s.units).some(pl => inside([pl.x, pl.y]))) sel.symbols.push(ref);
  d.wires.forEach((w, i) => { if (w.every(inside)) sel.wires.push(i); });
  d.labels.forEach((l, i) => { if (inside([l.x, l.y])) sel.labels.push(i); });
  d.grounds.forEach((g, i) => { if (inside([g.x, g.y])) sel.grounds.push(i); });
  d.frames.forEach((f, i) => { if (inside([f.x, f.y]) && inside([f.x + f.w, f.y + f.h])) sel.frames.push(i); });
  return sel;
}

/** A frame with everything whose position is in it. */
export function frameContents(d, i) {
  const f = d.frames[i];
  const sel = selectBox(d, [f.x, f.y, f.x + f.w, f.y + f.h]);
  sel.frames = [i];
  return sel;
}

// --- Moving -------------------------------------------------------------------------------------

/** Points that move (old key -> new point) when `sel` moves by `fn` (a point map). */
function movedPoints(d, lib, sel, fn, before) {
  const moves = new Map();
  for (const ref of sel.symbols) {
    const s = d.symbols[ref], old = before.symbols[ref];
    for (const u of Object.keys(s.units)) {
      const a = pinPoints(lib, old, +u), b = pinPoints(lib, s, +u);
      for (const n of Object.keys(a)) moves.set(key(...a[n]), b[n]);
    }
  }
  for (const i of sel.wires) for (const p of before.wires[i]) moves.set(key(...p), fn(p));
  for (const i of sel.labels) { const l = before.labels[i]; moves.set(key(l.x, l.y), fn([l.x, l.y])); }
  for (const i of sel.grounds) { const g = before.grounds[i]; moves.set(key(g.x, g.y), fn([g.x, g.y])); }
  return moves;
}

/** Wires, labels and grounds not in `sel` that touch a moved point follow it. */
function reattach(d, sel, moves) {
  const selWires = new Set(sel.wires), selLabels = new Set(sel.labels), selGrounds = new Set(sel.grounds);
  d.labels.forEach((l, i) => {
    const m = !selLabels.has(i) && moves.get(key(l.x, l.y));
    if (m) { l.x = m[0]; l.y = m[1]; }
  });
  d.grounds.forEach((g, i) => {
    const m = !selGrounds.has(i) && moves.get(key(g.x, g.y));
    if (m) { g.x = m[0]; g.y = m[1]; }
  });
  d.wires = d.wires.map((w, i) => {
    if (selWires.has(i)) return w;
    const n = w.length, m0 = moves.get(key(...w[0])), m1 = moves.get(key(...w[n - 1]));
    if (m0 && m1 && same(sub(m0, w[0]), sub(m1, w[n - 1]))) {
      const dd = sub(m0, w[0]); // both ends move alike: the whole wire moves
      return w.map(p => [round4(p[0] + dd[0]), round4(p[1] + dd[1])]);
    }
    let pts = w.map(p => [...p]);
    if (m0) pts = follow(pts, m0);
    if (m1) pts = follow(pts.reverse(), m1).reverse();
    return pts;
  });
  tidy(d);
}

const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];

/** Move a wire's first point to `to`, keeping its first segment's direction: an inner
 *  corner slides with it, a straight two-point wire gets a bend at the moved end. */
function follow(pts, to) {
  const [e, q] = pts, horiz = Math.abs(e[1] - q[1]) < EPS, vert = Math.abs(e[0] - q[0]) < EPS;
  if (pts.length > 2 && (horiz || vert)) {
    const q2 = horiz ? [q[0], to[1]] : [to[0], q[1]];
    return [to, q2, ...pts.slice(2)];
  }
  if (horiz && Math.abs(to[1] - e[1]) > EPS) return [to, [to[0], q[1]], ...pts.slice(1)];
  if (vert && Math.abs(to[0] - e[0]) > EPS) return [to, [q[0], to[1]], ...pts.slice(1)];
  return [to, ...pts.slice(1)];
}

/** Drop zero-length segments, merge straight runs, drop wires of one point. */
export function tidy(d) {
  d.wires = d.wires.map(w => {
    const out = [];
    for (const p of w) if (!out.length || !same(out.at(-1), p)) out.push([round4(p[0]), round4(p[1])]);
    for (let i = 1; i + 1 < out.length;) {
      const [a, b, c] = [out[i - 1], out[i], out[i + 1]];
      if (Math.abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) < EPS) out.splice(i, 1); else i++;
    }
    return out;
  }).filter(w => w.length >= 2);
}

const clone = d => JSON.parse(JSON.stringify(d));

/** Move `sel` by (dx, dy) (snapped to the grid); wires attached to it follow. */
export function moveItems(d, lib, sel, dx, dy) {
  dx = snap(dx); dy = snap(dy);
  if (!dx && !dy) return;
  const before = clone(d), fn = p => [round4(p[0] + dx), round4(p[1] + dy)];
  for (const ref of sel.symbols) for (const pl of Object.values(d.symbols[ref].units)) { pl.x = round4(pl.x + dx); pl.y = round4(pl.y + dy); }
  for (const i of sel.wires) d.wires[i] = d.wires[i].map(fn);
  for (const i of sel.labels) { const l = d.labels[i]; [l.x, l.y] = fn([l.x, l.y]); }
  for (const i of sel.grounds) { const g = d.grounds[i]; [g.x, g.y] = fn([g.x, g.y]); }
  for (const i of sel.frames) { const f = d.frames[i]; f.x = round4(f.x + dx); f.y = round4(f.y + dy); }
  reattach(d, sel, movedPoints(d, lib, sel, fn, before));
}

/** Rotate (90 degrees counter-clockwise) or mirror each selected symbol about its own
 *  origin, and labels and grounds in place; attached wires follow. */
export function turnItems(d, lib, sel, how = 'rotate') {
  const before = clone(d);
  for (const ref of sel.symbols) for (const pl of Object.values(d.symbols[ref].units)) {
    if (how === 'rotate') { const r = ((pl.rot || 0) + 90) % 360; if (r) pl.rot = r; else delete pl.rot; }
    else if (pl.mirror) delete pl.mirror; else pl.mirror = true;
  }
  for (const i of sel.labels) d.labels[i].rot = ((d.labels[i].rot || 0) + (how === 'rotate' ? 90 : 180)) % 360;
  for (const i of sel.grounds) d.grounds[i].rot = ((d.grounds[i].rot || 0) + (how === 'rotate' ? 90 : 180)) % 360;
  const parts = { ...emptySel(), symbols: sel.symbols };
  reattach(d, { ...sel, wires: [] }, movedPoints(d, lib, parts, p => p, before));
}

/** Remove `sel` (whole symbols, wires, labels, grounds; frames only, their contents stay). */
export function deleteItems(d, sel) {
  for (const ref of sel.symbols) delete d.symbols[ref];
  const drop = (arr, idx) => { const s = new Set(idx); return arr.filter((_, i) => !s.has(i)); };
  d.wires = drop(d.wires, sel.wires);
  d.labels = drop(d.labels, sel.labels);
  d.grounds = drop(d.grounds, sel.grounds);
  d.frames = drop(d.frames, sel.frames);
}

/** Remove one unit of a multi-unit symbol (the whole symbol when it is the last). */
export function deleteUnit(d, ref, unit) {
  const s = d.symbols[ref];
  delete s.units[unit];
  if (!Object.keys(s.units).length) delete d.symbols[ref];
}

// --- Copy and paste ------------------------------------------------------------------------------

/** The selection as a clipboard: copies, positions relative to its top-left corner.
 *  Wires come along when both their ends are in it or on its parts' pins. */
export function copyItems(d, lib, sel) {
  const pts = [];
  for (const r of sel.symbols) for (const pl of Object.values(d.symbols[r].units)) pts.push([pl.x, pl.y]);
  for (const i of sel.wires) pts.push(...d.wires[i]);
  for (const i of sel.labels) pts.push([d.labels[i].x, d.labels[i].y]);
  for (const i of sel.grounds) pts.push([d.grounds[i].x, d.grounds[i].y]);
  if (!pts.length) return null;
  const ox = snap(Math.min(...pts.map(p => p[0]))), oy = snap(Math.min(...pts.map(p => p[1])));
  const pinKeys = new Set();
  for (const r of sel.symbols) for (const u of Object.keys(d.symbols[r].units))
    for (const p of Object.values(pinPoints(lib, d.symbols[r], +u))) pinKeys.add(key(...p));
  const wires = new Set(sel.wires);
  d.wires.forEach((w, i) => { if (pinKeys.has(key(...w[0])) && pinKeys.has(key(...w.at(-1)))) wires.add(i); });
  const rel = ([x, y]) => [round4(x - ox), round4(y - oy)];
  return {
    symbols: Object.fromEntries(sel.symbols.map(r => {
      const s = clone(d.symbols[r]);
      for (const pl of Object.values(s.units)) [pl.x, pl.y] = rel([pl.x, pl.y]);
      return [r, s];
    })),
    wires: [...wires].map(i => d.wires[i].map(rel)),
    labels: sel.labels.map(i => ({ ...d.labels[i], x: rel([d.labels[i].x, d.labels[i].y])[0], y: rel([d.labels[i].x, d.labels[i].y])[1] })),
    grounds: sel.grounds.map(i => ({ ...d.grounds[i], x: rel([d.grounds[i].x, d.grounds[i].y])[0], y: rel([d.grounds[i].x, d.grounds[i].y])[1] })),
  };
}

/** Paste a clipboard with its top-left corner at (x, y); parts get new references (their
 *  fields, a shared Param included, are copied). Returns the pasted selection. */
export function pasteItems(d, lib, clip, x, y) {
  x = snap(x); y = snap(y);
  const sel = emptySel(), names = new Map();
  for (const [r, s] of Object.entries(clip.symbols)) {
    const prefix = r.match(/^[A-Za-z_]*/)[0] || lib[s.symbol].prefix;
    const ref = nextRef(d, prefix);
    names.set(r, ref);
    const c = clone(s);
    for (const pl of Object.values(c.units)) { pl.x = round4(pl.x + x); pl.y = round4(pl.y + y); }
    d.symbols[ref] = c;
    sel.symbols.push(ref);
  }
  // A pasted winding names its pasted core, when the core came along.
  for (const ref of sel.symbols) {
    const f = d.symbols[ref].fields;
    if (f.Transformer && names.has(f.Transformer)) f.Transformer = names.get(f.Transformer);
  }
  const at = ([px, py]) => [round4(px + x), round4(py + y)];
  for (const w of clip.wires) { sel.wires.push(d.wires.length); d.wires.push(w.map(at)); }
  for (const l of clip.labels) { sel.labels.push(d.labels.length); const [lx, ly] = at([l.x, l.y]); d.labels.push({ ...l, x: lx, y: ly }); }
  for (const g of clip.grounds) { sel.grounds.push(d.grounds.length); const [gx, gy] = at([g.x, g.y]); d.grounds.push({ ...g, x: gx, y: gy }); }
  return sel;
}

// --- Wires ---------------------------------------------------------------------------------------

/** The L-shaped route from a to b: horizontal first, or vertical first. */
export function route(a, b, horizontalFirst = true) {
  if (Math.abs(a[0] - b[0]) < EPS || Math.abs(a[1] - b[1]) < EPS) return [a, b];
  return horizontalFirst ? [a, [b[0], a[1]], b] : [a, [a[0], b[1]], b];
}

/** Add a wire through `pts` (snapped, tidied); returns its index or -1 when it is empty. */
export function addWire(d, pts) {
  const w = pts.map(([x, y]) => [snap(x), snap(y)]);
  d.wires.push(w);
  const n = d.wires.length;
  tidy(d);
  return d.wires.length === n ? n - 1 : -1;
}

/** Rename a part; windings naming a renamed core follow. False when the name is taken. */
export function renameRef(d, from, to) {
  if (from === to) return true;
  if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(to) || d.symbols[to]) return false;
  const out = {};
  for (const [r, s] of Object.entries(d.symbols)) out[r === from ? to : r] = s;
  d.symbols = out;
  for (const s of Object.values(d.symbols)) if (s.fields.Transformer === from) s.fields.Transformer = to;
  return true;
}

/** Drag segment j of wire wi sideways by (dx, dy): a horizontal segment moves up or down,
 *  a vertical one left or right; the wire's ends stay put (a jog is added at an end that
 *  moved), and wires ending on a moved corner follow it. */
export function dragSegment(d, lib, wi, j, dx, dy) {
  const w = d.wires[wi].map(p => [...p]), a = w[j], b = w[j + 1];
  const horiz = Math.abs(a[1] - b[1]) < EPS, vert = Math.abs(a[0] - b[0]) < EPS;
  const mx = snap(vert || !horiz ? dx : 0), my = snap(horiz || !vert ? dy : 0);
  if (!mx && !my) return;
  const moves = new Map();
  const shift = p => [round4(p[0] + mx), round4(p[1] + my)];
  const startIsEnd = j === 0, endIsEnd = j + 1 === w.length - 1;
  if (!startIsEnd) moves.set(key(...a), shift(a));
  if (!endIsEnd) moves.set(key(...b), shift(b));
  // What sits on the segment goes with it: labels, grounds, wires ending on it (T junctions).
  const onSeg = p => onSegment(p, a, b) && !(startIsEnd && same(p, a)) && !(endIsEnd && same(p, b));
  for (const l of [...d.labels, ...d.grounds]) if (onSeg([l.x, l.y])) [l.x, l.y] = shift([l.x, l.y]);
  d.wires.forEach((o, i) => { if (i !== wi) for (const p of [o[0], o.at(-1)]) if (onSeg(p)) moves.set(key(...p), shift(p)); });
  d.wires[wi] = [...w.slice(0, j), ...(startIsEnd ? [a] : []), shift(a), shift(b), ...(endIsEnd ? [b] : []), ...w.slice(j + 2)];
  reattach(d, { ...emptySel(), wires: [wi], labels: d.labels.map((_, i) => i), grounds: d.grounds.map((_, i) => i) }, moves);
}

function onSegment(p, a, b) {
  if (Math.abs((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])) > EPS * Math.max(1, Math.hypot(b[0] - a[0], b[1] - a[1]))) return false;
  return p[0] >= Math.min(a[0], b[0]) - EPS && p[0] <= Math.max(a[0], b[0]) + EPS && p[1] >= Math.min(a[1], b[1]) - EPS && p[1] <= Math.max(a[1], b[1]) + EPS;
}
