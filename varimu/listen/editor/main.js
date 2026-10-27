// The schematic editor page (device builder B4a): steps 1 and 2, the view and editing parts
// in place with renders and A/B. State lives here; drawing and hit testing in view.js,
// pan and zoom in camera.js, the side panel in inspector.js, edits and their history in
// edits.js, renders and playback in listen.js. The server compiles, checks and renders
// (varimu.listen.editor_api).

import { Camera } from './camera.js';
import { History, setParam } from './edits.js';
import { esc } from './eng.js';
import { placeholder, showNet, showSymbol } from './inspector.js';
import { Listen } from './listen.js';
import { View } from './view.js';

const $ = s => document.querySelector(s);
const canvas = $('#canvas'), svg = $('#svg'), chip = $('#chip');
const store = {
  get(k, d) { try { const v = localStorage.getItem('editor.' + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('editor.' + k, JSON.stringify(v)); } catch { /* private mode */ } },
};

let lib = null, partLib = null, view = null, cam = null, state = null; // state: {name, kind, drawing, analysis, markers}
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
}

function fillCircuits(circuits) {
  $('#circuit').innerHTML = circuits.map(c => `<option value="${esc(c.name)}">${esc(c.title)}${c.kind === 'drawn' ? ' · drawn' : ''}</option>`).join('');
}

async function open(name) {
  $('#loading').style.display = '';
  store.set('circuit', name);
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.get('c') !== name) window.history.replaceState(null, '', `#c=${encodeURIComponent(name)}`);
  const r = await api(`/api/editor/open?circuit=${encodeURIComponent(name)}`);
  state = { name, kind: r.kind, drawing: r.drawing, analysis: r, markers: [] };
  hist.reset(state.drawing);
  listen.origin = name;
  listen.reset(JSON.stringify(state.drawing));
  view.load(state.drawing, state.analysis);
  $('#loading').style.display = 'none';
  // A link may name a section (s=) or a part (sel=) to show; else the last view of it.
  const frame = state.drawing.frames.find(f => f.title === hash.get('s'));
  const ref = hash.get('sel') && state.drawing.symbols[hash.get('sel')] ? hash.get('sel') : null;
  const saved = store.get(`cam.${name}`, null);
  if (ref) cam.show(pad(view.boxes.get(ref), 25), { animate: false, kMax: 10 });
  else if (frame) cam.show([frame.x, frame.y - 6, frame.x + frame.w, frame.y + frame.h], { animate: false });
  else if (saved) cam.set(saved.x, saved.y, saved.k);
  else cam.show(view.bounds(), { animate: false, kMax: 8 });
  renderSections();
  renderControls();
  badges();
  select(ref ? { kind: 'symbol', ref } : null);
  runChecks();
}

// --- Editing ------------------------------------------------------------------------------------

/** Apply an edit: record the drawing before it, change it, recompile, re-check, re-render. */
async function apply(label, mutate) {
  const t0 = performance.now();
  hist.push(state.drawing, label);
  mutate(state.drawing);
  await refresh(label, t0);
}

async function refresh(label, t0 = performance.now()) {
  const name = state.name, sel = view.selected;
  const analysis = await api('/api/editor/analyze', { drawing: state.drawing });
  if (state.name !== name) return;
  state.analysis = analysis;
  view.load(state.drawing, analysis);
  view.setMarkers(state.markers.filter(m => m.check !== 'import'));
  renderControls();
  badges();
  select(sel && (sel.kind !== 'symbol' || state.drawing.symbols[sel.ref]) ? sel : null);
  scheduleChecks();
  if (!analysis.ok) listen.status(`<span style="color:var(--fault)">doesn't compile: ${esc(analysis.errors[0] || '')}</span>`);
  else if (!analysis.has_output) listen.status('label the output node <b>out</b> to hear the circuit');
  else listen.edited(state.drawing, label, t0);
}

function badges() {
  const edited = hist.isEdited(state.drawing);
  $('#kind').textContent = state.kind === 'drawn' ? 'drawing' : 'hand-written · generated layout';
  const e = $('#edited');
  e.hidden = !edited;
  e.textContent = state.kind === 'drawn' ? '● unsaved' : '● edited · save as a new circuit';
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
function scheduleChecks() { clearTimeout(checkTimer); checkTimer = setTimeout(runChecks, 700); }

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
  const faults = markers.filter(m => m.check !== 'drawing').length;
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
  $('#sections').innerHTML = state.drawing.frames.map((f, i) =>
    `<div class="item" data-i="${i}">${esc(f.title)}<span class="n">${count.get(f.title) || 0}</span></div>`).join('');
}

function renderProblems() {
  const ms = state.markers;
  $('#nprob').textContent = ms.length || '';
  $('#problems').innerHTML = ms.length ? ms.map((m, i) =>
    `<div class="item prob ${m.check === 'drawing' ? 'drawing' : ''}" data-i="${i}"><i></i><div><b>${esc(m.check)}</b> ${esc(m.message)}${m.config ? `<small>at ${esc(m.config)}</small>` : ''}</div></div>`).join('')
    : '<div class="empty">none: the checks pass at every switch combination</div>';
}

$('#sections').addEventListener('click', e => {
  const it = e.target.closest('.item'); if (!it) return;
  const f = state.drawing.frames[+it.dataset.i];
  cam.show([f.x, f.y - 6, f.x + f.w, f.y + f.h]);
});
$('#titles').addEventListener('click', e => {
  const t = e.target.closest('.ftitle'); if (!t) return;
  const f = state.drawing.frames[+t.dataset.i];
  cam.show([f.x, f.y - 6, f.x + f.w, f.y + f.h]);
});
$('#problems').addEventListener('click', e => {
  const it = e.target.closest('.item'); if (!it) return;
  const i = +it.dataset.i, m = state.markers[i];
  for (const el of document.querySelectorAll('#problems .item')) el.classList.toggle('on', el === it);
  view.setMarkers(state.markers, i);
  const b = view.markerBox(m);
  if (b) cam.show([b[0] - 10, b[1] - 10, b[2] + 10, b[3] + 10], { kMax: 10 });
  if (m.symbols.length === 1) select({ kind: 'symbol', ref: m.symbols[0] });
  else if (m.nets.length === 1) select({ kind: 'net', net: m.nets[0] });
});
$('#checks').addEventListener('click', () => { const first = document.querySelector('#problems .item'); if (first) first.click(); });

// --- Selection ------------------------------------------------------------------------------------

function select(sel) {
  view.select(sel);
  const el = $('#inspector'), ctx = { drawing: state.drawing, lib, partLib, analysis: state.analysis, view, apply };
  if (!sel) placeholder(el, { title: state.drawing.circuit.title || state.name, parts: Object.keys(state.drawing.symbols).length,
                              nets: state.analysis.nets.length, sections: state.drawing.frames.length });
  else if (sel.kind === 'symbol') showSymbol(el, sel.ref, ctx);
  else if (state.analysis.nets[sel.net]) showNet(el, sel.net, ctx);
  else select(null);
}

$('#inspector').addEventListener('click', e => {
  if (e.target.closest('input, textarea, select, button')) return;
  const n = e.target.closest('[data-net]'), r = e.target.closest('[data-ref]');
  if (n) { const i = +n.dataset.net; select({ kind: 'net', net: i }); const b = view.netBox(i); if (b) cam.show(pad(b, 8), { kMax: 10 }); }
  else if (r) { select({ kind: 'symbol', ref: r.dataset.ref }); cam.show(pad(view.boxes.get(r.dataset.ref), 12), { kMax: 10 }); }
});
$('#inspector').addEventListener('mouseover', e => {
  const n = e.target.closest('.tag[data-net]'); view.setHover(n ? { net: +n.dataset.net } : null);
});

const pad = (b, m) => [b[0] - m, b[1] - m, b[2] + m, b[3] + m];

// --- Save as --------------------------------------------------------------------------------------

function openSave() {
  const box = $('#savebox');
  box.classList.add('on');
  const suggestion = state.kind === 'drawn' ? state.name : `${state.name}_mine`;
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

let drag = null, space = null, lastMove = null; // space: {used} while the space bar is held

function local(e) { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }

canvas.addEventListener('pointerdown', e => {
  if (!state) return;
  const [sx, sy] = local(e);
  const [wx, wy] = cam.toWorld(sx, sy);
  const target = view.hit(wx, wy, 7 / cam.k);
  const pan = e.button === 1 || (e.button === 0 && (space || !target));
  if (space) space.used = true;
  drag = { sx, sy, x0: cam.x, y0: cam.y, pan, moved: false, target, id: e.pointerId };
  canvas.setPointerCapture(e.pointerId);
  cam.stop();
  if (e.button === 1) e.preventDefault();
});

canvas.addEventListener('pointermove', e => {
  if (!state) return;
  const [sx, sy] = local(e);
  if (drag) {
    if (Math.hypot(sx - drag.sx, sy - drag.sy) > 3) drag.moved = true;
    if (drag.pan && drag.moved) { canvas.classList.add('panning'); cam.set(drag.x0 + sx - drag.sx, drag.y0 + sy - drag.sy, cam.k); }
    return;
  }
  lastMove = [sx, sy];
  requestHover();
});

canvas.addEventListener('pointerup', e => {
  if (!drag) return;
  canvas.classList.remove('panning');
  if (!drag.moved && e.button === 0 && !space) {
    const t = drag.target;
    if (!t) select(null);
    else if (t.t === 'symbol') select({ kind: 'symbol', ref: t.ref });
    else if (t.t === 'pin' && t.net < 0) select({ kind: 'symbol', ref: t.p.ref });
    else if (t.net >= 0) select({ kind: 'net', net: t.net });
  }
  drag = null;
});
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
  const t = view.hit(wx, wy, 7 / cam.k);
  view.setHover(t);
  if (!t) { chip.classList.remove('on'); return; }
  let html;
  if (t.t === 'symbol' || (t.t === 'pin' && t.net < 0)) {
    const ref = t.ref || t.p.ref, s = state.drawing.symbols[ref];
    html = `<b class="sym">${esc(ref)}</b> · ${esc(s.value)}<small>${esc(view.section.get(ref) || '')}</small>`;
  } else {
    const n = state.analysis.nets[t.net];
    const pins = view.pins.filter(p => p.net === t.net);
    const list = pins.slice(0, 8).map(p => `${p.ref}${lib[state.drawing.symbols[p.ref].symbol].units.length > 1 ? String.fromCharCode(64 + p.unit) : ''}.${p.name}`).join('  ');
    html = `<b>${esc(n.node === '0' ? 'ground' : n.node)}</b> · ${pins.length} pin${pins.length === 1 ? '' : 's'}<small>${esc(list)}${pins.length > 8 ? ' …' : ''}</small>`;
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
  const mod = e.ctrlKey || e.metaKey;
  if (mod && (e.key === 'z' || e.key === 'Z')) { e.preventDefault(); undoRedo(e.shiftKey ? 'redo' : 'undo'); return; }
  if (mod && (e.key === 'y' || e.key === 'Y')) { e.preventDefault(); undoRedo('redo'); return; }
  if (mod && (e.key === 's' || e.key === 'S')) { e.preventDefault(); openSave(); return; }
  if (mod) return;
  if (e.key === ' ') { e.preventDefault(); if (!space) { space = { used: false }; canvas.classList.add('spacepan'); } }
  else if (e.key === 'f' || e.key === 'F') fit();
  else if (e.key === 'Escape') { select(null); view.setMarkers(state.markers); $('#savebox').classList.remove('on'); }
  else if (e.key === '/') { e.preventDefault(); $('#find').focus(); $('#find').select(); }
  else if (e.key === '1') listen.choose('dry');
  else if (e.key === '2') listen.choose('a');
  else if (e.key === '3') listen.choose('b');
  else if (e.key === 'r' || e.key === 'R') { if (state.analysis.ok) listen.render(state.drawing, 'render now'); }
  else if (e.key === 'z' || e.key === 'Z') {
    const s = view.selected;
    if (s?.kind === 'symbol') cam.show(pad(view.boxes.get(s.ref), 12), { kMax: 10 });
    else if (s?.kind === 'net') { const b = view.netBox(s.net); if (b) cam.show(pad(b, 8), { kMax: 10 }); }
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
  if (ref) { select({ kind: 'symbol', ref }); cam.show(pad(view.boxes.get(ref), 14), { kMax: 10 }); return; }
  const i = state.analysis.nets.findIndex(n => n.node.toLowerCase() === q);
  const j = i >= 0 ? i : state.analysis.nets.findIndex(n => n.node.toLowerCase().startsWith(q));
  if (j >= 0) { select({ kind: 'net', net: j }); const b = view.netBox(j); if (b) cam.show(pad(b, 8), { kMax: 10 }); }
  else e.target.animate([{ transform: 'translateX(-3px)' }, { transform: 'translateX(3px)' }, { transform: 'none' }], 160);
});

window.addEventListener('beforeunload', e => { if (state && hist.isEdited(state.drawing)) { e.preventDefault(); e.returnValue = ''; } });

// Remember where each circuit was looked at.
let saveTimer = null;
const saveCam = () => { clearTimeout(saveTimer); saveTimer = setTimeout(() => state && store.set(`cam.${state.name}`, { x: cam.x, y: cam.y, k: cam.k }), 400); };
canvas.addEventListener('wheel', saveCam, { passive: true });
canvas.addEventListener('pointerup', saveCam);
window.addEventListener('resize', () => cam && view.onCamera(cam));

init().catch(e => { $('#loading').textContent = `Failed to load: ${e.message}`; });
