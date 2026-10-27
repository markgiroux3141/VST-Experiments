// The schematic editor page (device builder B4a). State lives here; drawing and hit
// testing in view.js, pan and zoom in camera.js, the drawing tools in tools.js (topology
// edits in geom.js), the side panel in inspector.js, value edits and their history in
// edits.js, renders and playback in listen.js. The server compiles, checks and renders
// (varimu.listen.editor_api). Every change goes through `apply`: recorded for undo,
// recompiled, re-checked, re-rendered.

import { Camera } from './camera.js';
import { History, setParam } from './edits.js';
import { esc } from './eng.js';
import { emptySel, selSize } from './geom.js';
import { showCircuit, showMany, showNet, showSymbol } from './inspector.js';
import { Listen } from './listen.js';
import { Tools } from './tools.js';
import { View } from './view.js';

const $ = s => document.querySelector(s);
const canvas = $('#canvas'), svg = $('#svg'), chip = $('#chip');
const store = {
  get(k, d) { try { const v = localStorage.getItem('editor.' + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('editor.' + k, JSON.stringify(v)); } catch { /* private mode */ } },
};
const NEW = '__new__';

let lib = null, partLib = null, view = null, cam = null, tools = null;
let state = null; // {name, kind, drawing, analysis, markers, sel, net}
const hist = new History(h => {
  $('#undo').disabled = !h.past.length; $('#redo').disabled = !h.future.length;
  $('#undo').title = h.past.length ? `Undo ${h.past.at(-1).label} (Ctrl+Z)` : 'Undo (Ctrl+Z)';
  $('#redo').title = h.future.length ? `Redo ${h.future.at(-1).label} (Ctrl+Shift+Z)` : 'Redo (Ctrl+Shift+Z)';
});

async function api(path, body) {
  const r = await fetch(path, body ? { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) } : {});
  if (!r.ok) {
    let msg = await r.text();
    try { msg = JSON.parse(msg).detail ?? msg; } catch { /* plain text */ }
    throw new Error(msg);
  }
  return r.json();
}

const listen = new Listen({ api, store });

async function init() {
  const [symbols, circuits, parts] = await Promise.all([api('/api/editor/symbols'), api('/api/editor/circuits'), api('/api/editor/library')]);
  lib = symbols; partLib = parts;
  view = new View(svg, $('#world'), $('#titles'), lib);
  cam = new Camera(canvas, c => { view.onCamera(c); $('#zoom').textContent = `${Math.round(c.k / 4 * 100)}%`; });
  tools = new Tools({ canvas, cam, view, lib, state: () => state, apply, select, setStatus: msg => listen.status(esc(msg)), prompt: ask,
                      onMode: mode => { for (const b of document.querySelectorAll('#tools button')) b.classList.toggle('on', b.dataset.mode === mode);
                                        for (const t of document.querySelectorAll('.tile')) t.classList.toggle('on', mode === 'place' && t.dataset.sym === tools.place?.name); } });
  renderPalette();
  fillCircuits(circuits);
  const sel = $('#circuit');
  const wanted = new URLSearchParams(location.hash.slice(1)).get('c') || store.get('circuit', 'pultec_eqp1a');
  sel.value = circuits.some(c => c.name === wanted) ? wanted : circuits[0].name;
  sel.addEventListener('change', () => {
    if (hist.isEdited(state.drawing) && !confirm('Leave the unsaved edits?')) { sel.value = state.name; return; }
    open(sel.value);
  });
  await listen.init();
  await open(sel.value);
  // For scripted checks of the page (Playwright): the camera, the tools, the state.
  window.__editor = { cam, tools, view, state: () => state, idle: () => !!state && pending === 0, openDrawing: openFile };
}

function fillCircuits(circuits) {
  $('#circuit').innerHTML = circuits.map(c => `<option value="${esc(c.name)}">${esc(c.title)}${c.kind === 'drawn' ? ' · drawn' : ''}</option>`).join('') +
    `<option value="${NEW}">＋ New circuit…</option>`;
}

const blank = () => ({ format: 'varimu-drawing', version: 1, circuit: { title: 'Untitled circuit', input: 'in', probes: [] },
                       frames: [], symbols: {}, wires: [], labels: [], grounds: [] });

async function open(name, drawing = null) {
  $('#loading').style.display = '';
  const hash = new URLSearchParams(location.hash.slice(1));
  let r;
  if (name === NEW || drawing) {
    drawing = drawing || blank();
    r = { name: name === NEW ? 'untitled' : name, kind: 'new', drawing, ...(await api('/api/editor/analyze', { drawing })) };
  } else {
    store.set('circuit', name);
    if (hash.get('c') !== name) window.history.replaceState(null, '', `#c=${encodeURIComponent(name)}`);
    r = await api(`/api/editor/open?circuit=${encodeURIComponent(name)}`);
  }
  state = { name: r.name, kind: r.kind, drawing: r.drawing, analysis: r, markers: [], sel: emptySel(), net: -1 };
  hist.reset(state.drawing);
  listen.origin = state.name;
  listen.reset(JSON.stringify(state.drawing));
  tools.setMode('select');
  view.markers = [];
  view.load(state.drawing, state.analysis);
  $('#loading').style.display = 'none';
  // A link may name a section (s=) or a part (sel=) to show; else the last view of it.
  const frame = state.drawing.frames.find(f => f.title === hash.get('s'));
  const ref = hash.get('sel') && state.drawing.symbols[hash.get('sel')] ? hash.get('sel') : null;
  const saved = store.get(`cam.${state.name}`, null);
  if (ref) cam.show(pad(view.boxes.get(ref), 25), { animate: false, kMax: 10 });
  else if (frame) cam.show([frame.x, frame.y - 6, frame.x + frame.w, frame.y + frame.h], { animate: false });
  else if (saved && state.kind !== 'new') cam.set(saved.x, saved.y, saved.k);
  else cam.show(view.bounds(), { animate: false, kMax: 8 });
  renderSections();
  renderControls();
  badges();
  select(ref ? { ...emptySel(), symbols: [ref] } : emptySel(), -1);
  runChecks();
}

// --- Editing ------------------------------------------------------------------------------------

/** Apply an edit: record the drawing before it, change it, recompile, re-check, re-render. */
let pending = 0; // edits still being recompiled (scripted checks wait for 0)
async function apply(label, mutate) {
  const t0 = performance.now();
  const before = JSON.parse(JSON.stringify(state.drawing));
  mutate(state.drawing);
  if (JSON.stringify(before) === JSON.stringify(state.drawing)) return; // nothing changed
  hist.push(before, label);
  pending++;
  try { await refresh(label, t0); } finally { pending--; }
}

async function refresh(label, t0 = performance.now()) {
  const name = state.name;
  const analysis = await api('/api/editor/analyze', { drawing: state.drawing });
  if (state.name !== name) return;
  state.analysis = analysis;
  // Drop selected items that no longer exist.
  const d = state.drawing, s = state.sel;
  state.sel = { symbols: s.symbols.filter(r => d.symbols[r]), wires: s.wires.filter(i => i < d.wires.length),
                labels: s.labels.filter(i => i < d.labels.length), grounds: s.grounds.filter(i => i < d.grounds.length),
                frames: s.frames.filter(i => i < d.frames.length) };
  view.markers = state.markers.filter(m => m.check !== 'import' && m.check !== 'unconnected');
  view.load(state.drawing, analysis);
  renderSections();
  renderControls();
  badges();
  select(state.sel, state.net < analysis.nets.length ? state.net : -1);
  scheduleChecks();
  if (!analysis.ok) listen.status(`<span style="color:var(--fault)">doesn't compile: ${esc(analysis.errors[0] || '')}</span>`);
  else if (!analysis.has_output) listen.status('label the output node <b>out</b> to hear the circuit');
  else listen.edited(state.drawing, label, t0);
}

function badges() {
  const edited = hist.isEdited(state.drawing) || state.kind === 'new';
  $('#kind').textContent = { drawn: 'drawing', new: 'new drawing', 'hand-written': 'hand-written · generated layout' }[state.kind];
  const e = $('#edited');
  e.hidden = !edited;
  e.textContent = state.kind === 'hand-written' ? '● edited · save as a new circuit' : '● unsaved';
  $('#stats').textContent = `${Object.keys(state.drawing.symbols).length} parts · ${state.analysis.nets.length} nets`;
}

async function undoRedo(which) {
  const r = which === 'undo' ? hist.undo(state.drawing) : hist.redo(state.drawing);
  if (!r) return;
  state.drawing = r.drawing;
  await refresh(`${which} ${r.label}`);
}
$('#undo').addEventListener('click', () => undoRedo('undo'));
$('#redo').addEventListener('click', () => undoRedo('redo'));

// --- Palette ------------------------------------------------------------------------------------

const PALETTE = [['R', 'R'], ['C', 'C'], ['L', 'L'], ['Pot', 'Pot'], ['Rheostat', 'Rheostat'], ['Pot_Tapped', 'Tapped'], ['T_Pad', 'T-pad'],
                 ['Triode', 'Triode'], ['Triode_Dual', 'Dual'], ['Pentode', 'Pentode'], ['Diode', 'Diode'], ['Diode_Dual', 'Dual diode'],
                 ['Bridge', 'Bridge'], ['VR_Tube', 'VR tube'], ['Winding', 'Winding'], ['Core', 'Core'], ['K', 'Coupling'],
                 ['V', 'DC'], ['Sine', 'Sine'], ['Mains', 'Mains'], ['SW_Rotary_3', 'Rotary']];

function renderPalette() {
  $('#palette').innerHTML = PALETTE.map(([name, label]) => {
    const s = lib[name]; if (!s) return '';
    const [cx, cy] = [(s.box[0] + s.box[2]) / 2, (s.box[1] + s.box[3]) / 2];
    const w = Math.max(5.08, s.box[2] - s.box[0]), h = Math.max(5.08, s.box[3] - s.box[1]), m = Math.max(w, h) * 0.08;
    const x0 = cx - w / 2, y0 = cy - h / 2;
    const body = s.graphics.map(g => g.d ? `<path d="${g.d}"${g.fill ? ' class="fill"' : ''}/>` : `<text x="${g.x}" y="${g.y}" style="font-size:${g.size}px">${esc(g.text)}</text>`).join('') +
      (s.units[0] || []).map(p => `<line x1="${p.x}" y1="${p.y}" x2="${p.x + p.into[0] * p.length}" y2="${p.y + p.into[1] * p.length}"/>`).join('');
    return `<div class="tile" data-sym="${name}" title="${esc(s.description)}"><svg viewBox="${x0 - m} ${y0 - m} ${w + 2 * m} ${h + 2 * m}">${body}</svg><span>${esc(label)}</span></div>`;
  }).join('');
}
$('#palette').addEventListener('click', async e => {
  const t = e.target.closest('.tile'); if (!t) return;
  let name = t.dataset.sym;
  if (name.startsWith('SW_Rotary')) {
    const r = t.getBoundingClientRect();
    const n = await ask(r.right + 6, r.top, '3', { title: 'Positions (2–12)' });
    if (!n || !lib[`SW_Rotary_${+n}`]) return;
    name = `SW_Rotary_${+n}`;
  }
  tools.setMode('place', name);
});
$('#tools').addEventListener('click', e => { const b = e.target.closest('button'); if (b) tools.setMode(b.dataset.mode); });

// --- An inline input (names of labels, sections, positions) ----------------------------------------

function ask(sx, sy, initial, { title = '', options = [] } = {}) {
  const box = $('#prompt'), inp = $('#promptin'), host = canvas.getBoundingClientRect();
  const inCanvas = sx < host.width && sy < host.height && sx >= 0;
  box.style.left = `${Math.max(4, inCanvas ? sx : sx - host.left)}px`; box.style.top = `${Math.max(4, inCanvas ? sy : sy - host.top)}px`;
  $('#prompttitle').textContent = title;
  $('#promptlist').innerHTML = options.map(o => `<option value="${esc(o)}">`).join('');
  inp.value = initial; box.classList.add('on');
  return new Promise(resolve => {
    const done = v => { box.classList.remove('on'); inp.onkeydown = inp.onblur = null; resolve(v); };
    inp.onkeydown = e => { e.stopPropagation(); if (e.key === 'Enter') done(inp.value.trim() || null); if (e.key === 'Escape') done(null); };
    // After the click that opened it has finished (its mouse-up would take the focus away).
    setTimeout(() => { inp.focus(); inp.select(); inp.onblur = () => done(null); }, 0);
  });
}

// --- Front panel ----------------------------------------------------------------------------------

function renderControls() {
  const ctl = state.drawing.circuit.controls || {}, base = JSON.parse(hist.base || '{}').circuit?.controls || {};
  const keys = Object.keys(ctl);
  $('#nctl').textContent = keys.length || '';
  $('#controls').innerHTML = keys.length ? keys.map(k => {
    const e = ctl[k], changed = base[k] && base[k].value !== e.value;
    const head = `<div class="top"><b title="${esc(e.source || '')}">${esc(k)}</b><span class="${changed ? 'changed' : ''}">${esc(fmtCtl(e.value, e))}</span></div>`;
    if (e.choices) return `<div class="ctl">${head}<div class="chips">${e.choices.map(c => `<button data-ctl="${esc(k)}" data-v="${esc(JSON.stringify(c))}" class="${c === e.value ? 'on' : ''}">${esc(String(c))}</button>`).join('')}</div></div>`;
    const step = e.unit === 'position' ? 1 : (e.max - e.min) / 100;
    return `<div class="ctl">${head}<input type="range" data-ctl="${esc(k)}" min="${e.min}" max="${e.max}" step="${step}" value="${e.value}"></div>`;
  }).join('') : '<div class="empty">no controls</div>';
}
const fmtCtl = (v, e) => typeof v === 'number' ? `${+v.toPrecision(4)}${e.unit && !['rotation', 'position'].includes(e.unit) ? ' ' + e.unit : ''}` : String(v);

$('#controls').addEventListener('click', e => {
  const b = e.target.closest('button[data-ctl]'); if (!b) return;
  const k = b.dataset.ctl, v = JSON.parse(b.dataset.v), old = state.drawing.circuit.controls[k].value;
  if (v !== old) apply(`${k} ${old} → ${v}`, d => setParam(d, k, v));
});
$('#controls').addEventListener('input', e => {
  const r = e.target.closest('input[data-ctl]'); if (!r) return;
  const span = r.parentElement.querySelector('.top span'), c = state.drawing.circuit.controls[r.dataset.ctl];
  span.textContent = fmtCtl(+r.value, c);
});
$('#controls').addEventListener('change', e => {
  const r = e.target.closest('input[data-ctl]'); if (!r) return;
  const k = r.dataset.ctl, v = +r.value, old = state.drawing.circuit.controls[k].value;
  if (v !== old) apply(`${k} ${+old.toPrecision(3)} → ${+v.toPrecision(3)}`, d => setParam(d, k, v));
});

// --- Checks ---------------------------------------------------------------------------------------

let checkTimer = null, checkSeq = 0;
function scheduleChecks() { clearTimeout(checkTimer); checkTimer = setTimeout(runChecks, 600); }

async function runChecks() {
  const pill = $('#checks'), seq = ++checkSeq;
  pill.className = 'pill busy'; pill.querySelector('span').textContent = 'checking…';
  const name = state.name, t0 = performance.now();
  let markers;
  try {
    markers = (await api('/api/editor/check', { drawing: state.drawing })).markers;
  } catch (e) {
    markers = [{ check: 'build', message: String(e.message), config: '', nets: [], symbols: [] }];
  }
  if (state.name !== name || seq !== checkSeq) return;
  state.markers = markers;
  view.setMarkers(markers);
  const faults = new Set(markers.filter(m => m.check !== 'drawing').map(m => m.check === 'unconnected' ? `open ${m.symbols[0]}` : m.message)).size;
  pill.className = 'pill ' + (faults ? 'bad' : 'ok');
  pill.querySelector('span').textContent = faults ? `${faults} problem${faults > 1 ? 's' : ''}` : 'checks pass';
  pill.title = `Pre-flight checks at every combination of switch positions (${((performance.now() - t0) / 1000).toFixed(1)} s)`;
  renderProblems();
}

// --- Side lists -----------------------------------------------------------------------------------

function renderSections() {
  const count = new Map();
  for (const t of view.section.values()) count.set(t, (count.get(t) || 0) + 1);
  $('#nsec').textContent = state.drawing.frames.length;
  $('#sections').innerHTML = state.drawing.frames.length ? state.drawing.frames.map((f, i) =>
    `<div class="item" data-i="${i}">${esc(f.title)}<span class="n">${count.get(f.title) || 0}</span></div>`).join('')
    : '<div class="empty">one section: draw frames with <kbd>S</kbd> to make more</div>';
}

function renderProblems() {
  // Open pins are listed per part: while drawing there are many, and they say one thing.
  const ms = state.markers, rows = [], open = new Map();
  ms.forEach((m, i) => {
    const pin = m.check === 'unconnected' && /^unconnected: pin (\S+) of (\S+)$/.exec(m.message);
    if (pin) { if (!open.has(pin[2])) { open.set(pin[2], { i, pins: [] }); rows.push({ open: pin[2] }); } open.get(pin[2]).pins.push(pin[1]); }
    else rows.push({ i, m });
  });
  $('#nprob').textContent = rows.length || '';
  $('#problems').innerHTML = rows.length ? rows.map(r => {
    if (r.open) {
      const o = open.get(r.open);
      return `<div class="item prob" data-i="${o.i}" data-open="${esc(r.open)}"><i></i><div><b>open</b> ${esc(r.open)}: pin${o.pins.length > 1 ? 's' : ''} ${esc(o.pins.join(', '))} unconnected</div></div>`;
    }
    const m = r.m;
    return `<div class="item prob ${m.check === 'drawing' ? 'drawing' : ''}" data-i="${r.i}"><i></i><div><b>${esc(m.check)}</b> ${esc(m.message)}${m.config ? `<small>at ${esc(m.config)}</small>` : ''}</div></div>`;
  }).join('') : '<div class="empty">none: the checks pass at every switch combination</div>';
}

const showFrame = f => cam.show([f.x, f.y - 6, f.x + f.w, f.y + f.h]);
$('#sections').addEventListener('click', e => {
  const it = e.target.closest('.item'); if (it) showFrame(state.drawing.frames[+it.dataset.i]);
});
$('#titles').addEventListener('pointerdown', e => {
  const t = e.target.closest('.ftitle'); if (!t || e.button !== 0) return;
  const [sx, sy] = local(e);
  if (tools.frameDown(+t.dataset.i, e, sx, sy)) { e.stopPropagation(); canvas.setPointerCapture(e.pointerId); drag = { tools: true }; }
});
$('#titles').addEventListener('dblclick', async e => {
  const t = e.target.closest('.ftitle'); if (!t) return;
  const i = +t.dataset.i, f = state.drawing.frames[i], r = t.getBoundingClientRect(), host = canvas.getBoundingClientRect();
  const title = await ask(r.left - host.left, r.top - host.top - 4, f.title, { title: 'Section name' });
  if (title && title !== f.title && !state.drawing.frames.some(g => g.title === title)) apply(`rename section ${f.title} → ${title}`, d => { d.frames[i].title = title; });
});
$('#problems').addEventListener('click', e => {
  const it = e.target.closest('.item'); if (!it) return;
  const i = +it.dataset.i, m = state.markers[i];
  for (const el of document.querySelectorAll('#problems .item')) el.classList.toggle('on', el === it);
  view.setMarkers(state.markers, i);
  const b = view.markerBox(m);
  if (b) cam.show([b[0] - 10, b[1] - 10, b[2] + 10, b[3] + 10], { kMax: 10 });
  if (it.dataset.open) select(it.dataset.open, -1);
  else if (m.symbols.length === 1) select({ ...emptySel(), symbols: [m.symbols[0]] }, -1);
  else if (m.nets.length === 1) select(emptySel(), m.nets[0]);
});
$('#checks').addEventListener('click', () => { const first = document.querySelector('#problems .item'); if (first) first.click(); });

// --- Selection ------------------------------------------------------------------------------------

function select(sel, net = -1) {
  if (typeof sel === 'string') sel = { ...emptySel(), symbols: [sel] };
  state.sel = sel; state.net = net;
  view.setSelection(sel, net);
  const el = $('#inspector'), ctx = { drawing: state.drawing, lib, partLib, analysis: state.analysis, view, apply, name: state.name, select: r => select(r, -1) };
  const n = selSize(sel);
  if (n === 1 && sel.symbols.length === 1) showSymbol(el, sel.symbols[0], ctx);
  else if (n > 1) showMany(el, sel, ctx);
  else if (net >= 0 && state.analysis.nets[net]) showNet(el, net, ctx);
  else showCircuit(el, ctx);
}

$('#inspector').addEventListener('click', e => {
  if (e.target.closest('input, textarea, select, button, summary')) return;
  const n = e.target.closest('.tag[data-net]'), r = e.target.closest('[data-ref]');
  if (n) { const i = +n.dataset.net; select(emptySel(), i); const b = view.netBox(i); if (b) cam.show(pad(b, 8), { kMax: 10 }); }
  else if (r) { select(r.dataset.ref, -1); cam.show(pad(view.boxes.get(r.dataset.ref), 12), { kMax: 10 }); }
});
$('#inspector').addEventListener('mouseover', e => {
  const n = e.target.closest('.tag[data-net]'); view.setHover(n ? { net: +n.dataset.net } : null);
});

const pad = (b, m) => [b[0] - m, b[1] - m, b[2] + m, b[3] + m];

// --- Save as --------------------------------------------------------------------------------------

function openSave() {
  const box = $('#savebox');
  box.classList.add('on');
  const suggestion = state.kind === 'drawn' ? state.name : state.kind === 'new' ? '' : `${state.name}_mine`;
  $('#savename').value = suggestion; $('#saveerr').textContent = '';
  $('#savename').focus(); $('#savename').select();
}
async function doSave() {
  const name = $('#savename').value.trim();
  try {
    await api('/api/editor/save', { drawing: state.drawing, name, origin: state.name });
  } catch (e) { $('#saveerr').textContent = e.message; return; }
  $('#savebox').classList.remove('on');
  fillCircuits(await api('/api/editor/circuits'));
  $('#circuit').value = name;
  const cam0 = { x: cam.x, y: cam.y, k: cam.k };
  await open(name);
  cam.set(cam0.x, cam0.y, cam0.k);
}
$('#save').addEventListener('click', openSave);
$('#savecancel').addEventListener('click', () => $('#savebox').classList.remove('on'));
$('#savego').addEventListener('click', doSave);
$('#savename').addEventListener('keydown', e => {
  e.stopPropagation();
  if (e.key === 'Enter') doSave();
  if (e.key === 'Escape') $('#savebox').classList.remove('on');
});

// --- Pointer --------------------------------------------------------------------------------------
// The left button belongs to the tools; the middle or right button, or space + drag, pans.

let drag = null, space = null, lastMove = null; // space: {used} while the space bar is held

function local(e) { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }

canvas.addEventListener('pointerdown', e => {
  if (!state || e.target.closest('#prompt')) return;
  const [sx, sy] = local(e);
  cam.stop();
  chip.classList.remove('on');
  if (e.button === 1 || e.button === 2 || (e.button === 0 && space)) {
    if (space) space.used = true;
    drag = { pan: true, sx, sy, x0: cam.x, y0: cam.y };
    canvas.setPointerCapture(e.pointerId);
    e.preventDefault();
    return;
  }
  if (e.button !== 0) return;
  drag = { tools: true };
  canvas.setPointerCapture(e.pointerId);
  tools.down(e, sx, sy);
});

canvas.addEventListener('pointermove', e => {
  if (!state) return;
  const [sx, sy] = local(e);
  if (drag?.pan) { canvas.classList.add('panning'); cam.set(drag.x0 + sx - drag.sx, drag.y0 + sy - drag.sy, cam.k); return; }
  tools.move(e, sx, sy);
  if (drag) return;
  lastMove = [sx, sy];
  requestHover();
});

canvas.addEventListener('pointerup', e => {
  if (!drag) return;
  const d = drag; drag = null;
  canvas.classList.remove('panning');
  if (d.tools) { const [sx, sy] = local(e); tools.up(e, sx, sy); }
});
canvas.addEventListener('dblclick', e => { const [sx, sy] = local(e); tools.dblclick(e, sx, sy); });
canvas.addEventListener('contextmenu', e => e.preventDefault());
canvas.addEventListener('pointerleave', () => { chip.classList.remove('on'); view?.setHover(null); $('#cx').textContent = $('#cy').textContent = '–'; });
canvas.addEventListener('auxclick', e => e.preventDefault());

let hoverQueued = false;
function requestHover() {
  if (hoverQueued) return;
  hoverQueued = true;
  requestAnimationFrame(() => { hoverQueued = false; hover(); });
}

function hover() {
  if (!lastMove || drag) return;
  const [sx, sy] = lastMove, [wx, wy] = cam.toWorld(sx, sy);
  $('#cx').textContent = wx.toFixed(2); $('#cy').textContent = wy.toFixed(2);
  if (tools.mode !== 'select') { chip.classList.remove('on'); view.setHover(null); return; }
  const t = view.hit(wx, wy, 7 / cam.k);
  view.setHover(t);
  if (!t) { chip.classList.remove('on'); return; }
  let html;
  if (t.t === 'symbol' || (t.t === 'pin' && t.net < 0)) {
    const ref = t.ref || t.p.ref, s = state.drawing.symbols[ref];
    html = `<b class="sym">${esc(ref)}</b> · ${esc(s.value)}<small>${esc(view.section.get(ref) || '')}</small>`;
  } else {
    const n = state.analysis.nets[t.net];
    if (!n) { chip.classList.remove('on'); return; }
    const pins = view.pins.filter(p => p.net === t.net);
    const list = pins.slice(0, 8).map(p => `${p.ref}${lib[state.drawing.symbols[p.ref].symbol].units.length > 1 ? String.fromCharCode(64 + p.unit) : ''}.${p.name}`).join('  ');
    html = `<b>${esc(n.node === '0' ? 'ground' : n.node)}</b> · ${pins.length} pin${pins.length === 1 ? '' : 's'}${t.t === 'pin' ? ' · drag to wire' : ''}<small>${esc(list)}${pins.length > 8 ? ' …' : ''}</small>`;
  }
  chip.innerHTML = html;
  const r = canvas.getBoundingClientRect();
  const x = Math.min(sx + 16, r.width - chip.offsetWidth - 8), y = sy + 18 + chip.offsetHeight > r.height ? sy - chip.offsetHeight - 12 : sy + 18;
  chip.style.left = `${x}px`; chip.style.top = `${y}px`;
  chip.classList.add('on');
}

// --- Keys and find --------------------------------------------------------------------------------

function fit() { cam.show(view.bounds(), { kMax: 8 }); }
$('#fit').addEventListener('click', fit);

document.addEventListener('keydown', e => {
  if (e.target.closest?.('input, textarea, select')) {
    if (e.key === 'Escape') e.target.blur();
    return;
  }
  if (!state) return;
  const mod = e.ctrlKey || e.metaKey;
  if (mod && (e.key === 'z' || e.key === 'Z')) { e.preventDefault(); undoRedo(e.shiftKey ? 'redo' : 'undo'); return; }
  if (mod && (e.key === 'y' || e.key === 'Y')) { e.preventDefault(); undoRedo('redo'); return; }
  if (mod && (e.key === 's' || e.key === 'S')) { e.preventDefault(); openSave(); return; }
  if (mod && e.key === 'Enter') { if (state.analysis.ok && state.analysis.has_output) listen.render(state.drawing, 'render now'); return; }
  if (e.key === ' ') { e.preventDefault(); if (!space) { space = { used: false }; canvas.classList.add('spacepan'); } return; }
  if (tools.key(e)) { e.preventDefault(); return; }
  if (mod) return;
  if (e.key === 'f' || e.key === 'F') fit();
  else if (e.key === 'Escape') { select(emptySel(), -1); view.setMarkers(state.markers); $('#savebox').classList.remove('on'); }
  else if (e.key === '/') { e.preventDefault(); $('#find').focus(); $('#find').select(); }
  else if (e.key === '1') listen.choose('dry');
  else if (e.key === '2') listen.choose('a');
  else if (e.key === '3') listen.choose('b');
  else if (e.key === 'z' || e.key === 'Z') {
    if (state.sel.symbols.length) cam.show(pad(view.boxes.get(state.sel.symbols[0]), 12), { kMax: 10 });
    else if (state.net >= 0) { const b = view.netBox(state.net); if (b) cam.show(pad(b, 8), { kMax: 10 }); }
  } else if (e.key === '+' || e.key === '=') { const r = canvas.getBoundingClientRect(); cam.zoomAt(r.width / 2, r.height / 2, cam.k * 1.4); }
  else if (e.key === '-') { const r = canvas.getBoundingClientRect(); cam.zoomAt(r.width / 2, r.height / 2, cam.k / 1.4); }
});
document.addEventListener('keyup', e => {
  if (e.key !== ' ' || !space) return;
  const tap = !space.used;
  space = null; canvas.classList.remove('spacepan');
  if (tap && !e.target.closest?.('input, textarea, select')) listen.toggle(); // a tap plays, a hold pans
});

$('#find').addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  const q = e.target.value.trim().toLowerCase(); if (!q) return;
  const refs = Object.keys(state.drawing.symbols);
  const ref = refs.find(r => r.toLowerCase() === q) || refs.find(r => r.toLowerCase().startsWith(q));
  if (ref) { select(ref, -1); cam.show(pad(view.boxes.get(ref), 14), { kMax: 10 }); return; }
  const i = state.analysis.nets.findIndex(n => n.node.toLowerCase() === q);
  const j = i >= 0 ? i : state.analysis.nets.findIndex(n => n.node.toLowerCase().startsWith(q));
  if (j >= 0) { select(emptySel(), j); const b = view.netBox(j); if (b) cam.show(pad(b, 8), { kMax: 10 }); }
  else e.target.animate([{ transform: 'translateX(-3px)' }, { transform: 'translateX(3px)' }, { transform: 'none' }], 160);
});

// A drawing file dropped on the canvas opens as a new, unsaved drawing.
async function openFile(json, name = 'dropped') {
  if (state && hist.isEdited(state.drawing) && !confirm('Leave the unsaved edits?')) return;
  const drawing = typeof json === 'string' ? JSON.parse(json) : json;
  if (drawing.format !== 'varimu-drawing') { listen.status('not a drawing (.drawing.json)'); return; }
  $('#circuit').value = NEW;
  await open(name.replace(/\.drawing\.json$/, ''), drawing);
}
canvas.addEventListener('dragover', e => e.preventDefault());
canvas.addEventListener('drop', async e => {
  e.preventDefault();
  const f = e.dataTransfer.files[0]; if (!f) return;
  await openFile(await f.text(), f.name);
});

window.addEventListener('beforeunload', e => { if (state && hist.isEdited(state.drawing)) { e.preventDefault(); e.returnValue = ''; } });

// Remember where each circuit was looked at.
let saveTimer = null;
const saveCam = () => { clearTimeout(saveTimer); saveTimer = setTimeout(() => state && state.kind !== 'new' && store.set(`cam.${state.name}`, { x: cam.x, y: cam.y, k: cam.k }), 400); };
canvas.addEventListener('wheel', saveCam, { passive: true });
canvas.addEventListener('pointerup', saveCam);
window.addEventListener('resize', () => cam && view.onCamera(cam));

init().catch(e => { $('#loading').textContent = `Failed to load: ${e.message}`; console.error(e); });
