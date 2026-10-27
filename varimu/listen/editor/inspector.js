// The inspector: a selected part's fields, editable (value with its source, the shared
// parameter it is on, its device or core material, its parameters), or a selected net's
// pins. A number without a source is shown as missing and doesn't compile (CLAUDE.md,
// hard rules); an edit's default source says it is the user's and what it replaced.

import { editSource, paramHome, setInline, setParam, unlink, valueKey } from './edits.js';
import { esc, parseEng, unitOf, withUnit } from './eng.js';

const META = new Set(['Source', 'Param', 'Genome', 'Tol', 'Unit', 'Notes']);
const KIND = { macro: 'part', device: 'tube or diode', winding: 'transformer winding', core: 'transformer core',
               coupling: 'inductor coupling', switch: 'rotary switch deck', power: 'power' };
const DEVICE_KINDS = { Triode: ['triode'], Triode_Dual: ['triode'], Pentode: ['pentode'],
                       Diode: ['vacuum_diode', 'junction_diode'], Diode_Dual: ['vacuum_diode', 'junction_diode'] };

const field = (label, html, extra = '') => `<div class="field"${extra}><label>${esc(label)}</label>${html}</div>`;

export function placeholder(el, info) {
  el.innerHTML = `<div class="placeholder"><b>${esc(info.title)}</b><br>${info.parts} parts · ${info.nets} nets · ${info.sections} sections<br><br>
    Click a part to see and change its values.<br>Hover a wire to follow its net.</div>`;
}

export function showSymbol(el, ref, ctx) {
  const { drawing, lib, analysis, view } = ctx;
  const s = drawing.symbols[ref], sym = lib[s.symbol], params = analysis.params || {};
  const f = s.fields, out = [];
  out.push(`<div class="ihead"><b>${esc(ref)}</b><span>${esc(s.symbol.replace(/_/g, ' '))}</span></div>`);
  out.push(`<div class="crumb">${esc(view.section.get(ref) || 'main')} · ${esc(KIND[sym.kind] || sym.kind)}</div>`);
  out.push(`<div class="desc">${esc(sym.description)}</div>`);

  if (sym.kind === 'device') out.push(deviceFields(s, sym, f, params, ctx));
  else if (sym.kind === 'winding') out.push(field('Transformer', `<div class="box">${esc(f.Transformer || '–')}, winding <b>${esc(s.value)}</b></div>`));
  else if (sym.kind === 'switch') {
    const c = params[f.Control];
    out.push(field('Control', `<div class="box">${esc(f.Control || '–')}${c ? ` <span class="note">· ${esc((c.choices || []).join(' / '))}</span>` : ''}</div>`));
  } else if (sym.primary) out.push(valueFields(ref, s, sym, f, params, drawing));

  if (f.Tol) out.push(field('Tolerance', tolBox(f.Tol, analysis.bands)));
  const rows = Object.entries(f).filter(([k]) => !META.has(k) && !(sym.kind === 'winding' && k === 'Transformer') &&
                                                 !(sym.kind === 'switch' && k === 'Control') && !(sym.kind === 'device' && k === 'Model'));
  if (rows.length) out.push(field('Parameters', `<table class="kv">${rows.map(([k, v]) => paramRow(k, v, params, ctx)).join('')}</table>`));
  const pins = [];
  for (const [u] of Object.entries(s.units)) for (const p of view.pins) if (p.ref === ref && p.unit === +u) pins.push(p);
  if (pins.length) {
    out.push(field('Pins', `<table class="kv">${pins.map(p => {
      const n = analysis.nets[p.net];
      const unit = sym.units.length > 1 ? String.fromCharCode(64 + p.unit) + '.' : '';
      const choices = sym.kind === 'switch' ? params[f.Control]?.choices : null;
      const pos = choices && /^\d+$/.test(p.number) ? ` <span class="note">${esc(choices[+p.number - 1] ?? '–')}</span>` : '';
      return `<tr><td>${unit}${esc(p.name === p.number ? p.number : `${p.name} (${p.number})`)}${pos}</td><td>${n ? `<span class="tag net" data-net="${p.net}">${esc(n.node)}</span>` : '<span class="note">–</span>'}</td></tr>`;
    }).join('')}</table>`));
  }
  if (sym.kind === 'core') {
    const ws = Object.entries(drawing.symbols).filter(([, w]) => w.symbol === 'Winding' && w.fields.Transformer === ref);
    out.push(field('Windings', `<div class="box">${ws.map(([r, w]) => `<span class="tag gray" data-ref="${esc(r)}" style="cursor:pointer">${esc(w.value)}</span>`).join(' ') || '–'}</div>`));
  }
  el.innerHTML = out.join('');
  wire(el, ref, s, sym, params, ctx);
}

function valueFields(ref, s, sym, f, params, drawing) {
  const key = valueKey(s), p = key ? params[key] : null;
  const unit = unitOf(key, sym.primary);
  const num = parseEng(s.value);
  const shown = num !== null ? s.value : p && typeof p.value === 'number' ? String(p.value) : s.value;
  const derived = p?.kind === 'derived';
  const out = [];
  out.push(field('Value', `<input class="val" id="v-in" value="${esc(shown)}" spellcheck="false"${derived ? ' disabled' : ''}>
    <div class="hintline"><span id="v-hint">${esc(hint(num ?? p?.value, unit, p))}</span></div>`));
  if (key && f.Param) {
    const sharers = Object.entries(drawing.symbols).filter(([r, o]) => r !== ref && o.fields.Param === key).map(([r]) => r);
    out.push(field('Parameter', `<div class="box"><span class="tag">${esc(key)}</span>${sharers.length ? ` <span class="note">· shared with</span> ${sharers.slice(0, 6).map(r => `<span class="tag gray" data-ref="${esc(r)}" style="cursor:pointer">${esc(r)}</span>`).join(' ')}${sharers.length > 6 ? ' …' : ''}
      <div class="hintline">An edit changes every part on it. <button class="linkbtn" id="v-unlink">Only this part</button></div>` : ''}</div>`));
  } else if (key) {
    out.push(field('Parameter', `<div class="box"><span class="tag">${esc(key)}</span> <span class="note">${esc(p ? p.kind.replace('_', ' ') : 'unknown key')}</span></div>`));
  }
  const source = f.Source ?? (f.Param ? sharedSource(drawing, key) : p?.source) ?? '';
  out.push(field('Source', `<textarea class="src${source ? '' : ' missing'}" id="v-src" spellcheck="false"${derived ? ' disabled' : ''}>${esc(source)}</textarea>
    <div class="hintline"><span id="v-srchint">${source ? '' : '<span class="err">a number needs a source: it won\'t compile without one</span>'}</span></div>`));
  const genome = f.Genome || p?.genome;
  if (genome) {
    const b = p?.bounds;
    const range = b ? (b.choices ? b.choices.join(' / ') : `${withUnit(b.min, unit)} … ${withUnit(b.max, unit)}`) : 'bounds not found';
    out.push(field('Genome', `<div class="box"><span class="tag gray">${esc(genome)}</span><div class="note" style="margin-top:4px">${esc(range)}</div></div>`));
  }
  if (p?.notes || f.Notes) out.push(field('Notes', `<div class="box src">${esc(f.Notes || p.notes)}</div>`));
  return out.join('');
}

function sharedSource(drawing, key) {
  return Object.values(drawing.symbols).find(o => o.fields.Param === key && o.fields.Source)?.fields.Source;
}

function hint(x, unit, p) {
  if (typeof x !== 'number') return p?.kind === 'derived' ? 'derived from other values (read-only)' : '';
  let h = `= ${withUnit(x, unit)}`;
  const b = p?.bounds;
  if (b && typeof b.min === 'number' && (x < b.min || x > b.max)) h += ` · outside the genome's ${withUnit(b.min, unit)} … ${withUnit(b.max, unit)}`;
  return h;
}

function deviceFields(s, sym, f, params, ctx) {
  const key = params[s.value] ? s.value : null;
  const file = key ? params[key].value : s.value;
  const kinds = DEVICE_KINDS[s.symbol] || [];
  const options = (ctx.partLib?.devices || []).filter(d => kinds.includes(d.kind));
  const known = options.some(d => d.name.toLowerCase() === String(file).toLowerCase());
  const opts = (known ? [] : [`<option selected>${esc(file)}</option>`]).concat(options.map(d =>
    `<option value="${esc(d.name)}"${d.name.toLowerCase() === String(file).toLowerCase() ? ' selected' : ''}>${esc(d.name)} · ${esc(d.kind.replace('_', ' '))}</option>`));
  return [
    field('Device', `<select class="sel" id="v-device">${opts.join('')}</select>
      <div class="hintline">${key ? `parameter <span class="tag">${esc(key)}</span>` : ''} config/devices/${esc(String(file).toLowerCase())}.yaml</div>`),
    ...(f.Model ? [field('Model', `<div class="box"><span class="tag">${esc(f.Model)}</span> <span class="note">one instance shared by both units</span></div>`)] : []),
    ...(f.Source ? [field('Source', `<div class="box src">${esc(f.Source)}</div>`)] : []),
  ].join('');
}

function paramRow(k, v, params, ctx) {
  const p = params[v];
  let cell = esc(v);
  if (p && p.kind !== 'derived') {
    const mats = ctx.partLib?.materials || [];
    if (typeof p.value === 'string' && mats.some(m => m.name === p.value)) {
      cell = `<select class="sel" data-param="${esc(v)}" style="padding:3px 22px 3px 6px;font:12px var(--mono)">${mats.map(m =>
        `<option${m.name === p.value ? ' selected' : ''}>${esc(m.name)}</option>`).join('')}</select><div class="note">${esc(v)}</div>`;
    } else if (typeof p.value === 'number') {
      cell = `<input class="num" data-param="${esc(v)}" value="${esc(String(p.value))}" spellcheck="false"><div class="note">${esc(v)} · ${esc(withUnit(p.value, unitOf(v)))}</div>`;
    } else cell = `${esc(v)}<br><span class="note">= ${esc(String(p.value))}</span>`;
  }
  return `<tr><td>${esc(k)}</td><td title="${esc(p?.source || '')}">${cell}</td></tr>`;
}

// --- Behaviour ------------------------------------------------------------------------------------

function wire(el, ref, s, sym, params, ctx) {
  const vin = el.querySelector('#v-in'), vsrc = el.querySelector('#v-src');
  let srcTouched = false;
  const key = valueKey(s), p = key ? params[key] : null, unit = unitOf(key, sym.primary);
  const original = vin?.value, originalSrc = vsrc?.value;
  if (vin) {
    vin.addEventListener('input', () => {
      const x = parseEng(vin.value);
      const isKey = x === null && params[vin.value.trim()];
      vin.classList.toggle('bad', x === null && !isKey);
      el.querySelector('#v-hint').textContent = x !== null ? hint(x, unit, p) : isKey ? `the parameter ${vin.value.trim()}` : 'not a number (40u, 4k7, 2.2e-9) or a parameter key';
      if (!srcTouched && vsrc && vin.value.trim() !== original) vsrc.value = editSource(original, originalSrc);
      if (!srcTouched && vsrc && vin.value.trim() === original) vsrc.value = originalSrc;
    });
    vin.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); commitValue(); vin.blur(); }
      if (e.key === 'Escape') { vin.value = original; vsrc.value = originalSrc; vin.dispatchEvent(new Event('input')); vin.blur(); }
      e.stopPropagation();
    });
    vin.addEventListener('blur', () => { if (vin.value.trim() !== original) commitValue(); });
  }
  if (vsrc) {
    vsrc.addEventListener('input', () => { srcTouched = true; vsrc.classList.toggle('missing', !vsrc.value.trim()); });
    vsrc.addEventListener('keydown', e => e.stopPropagation());
    vsrc.addEventListener('blur', () => {
      if (vin && vin.value.trim() !== original) return; // the value's commit takes the source with it
      if (vsrc.value === originalSrc) return;
      const t = vsrc.value.trim();
      ctx.apply(`source of ${ref}`, d => {
        const sd = d.symbols[ref];
        if (sd.fields.Param) { for (const o of Object.values(d.symbols)) if (o.fields.Param === sd.fields.Param) o.fields.Source = t; }
        else if (key && paramHome(d, key)?.entry) paramHome(d, key).entry.source = t;
        else sd.fields.Source = t;
      });
    });
  }

  let committed = false;
  function commitValue() {
    if (committed) return;
    const text = vin.value.trim(), x = parseEng(text), src = vsrc.value.trim();
    if (x === null && !params[text]) return; // invalid: stays red, nothing applied
    committed = true;
    ctx.apply(`${ref} ${original} → ${text}`, d => {
      const sd = d.symbols[ref];
      if (x === null) { // bound to another parameter key
        delete sd.fields.Param; delete sd.fields.Source; delete sd.fields.Genome;
        sd.value = text;
      } else if (sd.fields.Param) setParam(d, sd.fields.Param, x, src);
      else if (key && paramHome(d, key)) setParam(d, key, x, src);
      else setInline(d, ref, text, src);
    });
  }

  el.querySelector('#v-unlink')?.addEventListener('click', () => ctx.apply(`${ref} off ${s.fields.Param}`, d => unlink(d, ref)));

  const dev = el.querySelector('#v-device');
  dev?.addEventListener('change', () => {
    const name = dev.value, old = params[s.value] ? params[s.value].value : s.value;
    ctx.apply(`${ref} ${old} → ${name}`, d => {
      const sd = d.symbols[ref];
      if (params[sd.value] && paramHome(d, sd.value)) setParam(d, sd.value, name, editSource(old, params[sd.value].source));
      else { sd.value = name; sd.fields.Source = editSource(old, sd.fields.Source); }
    });
  });

  for (const inp of el.querySelectorAll('[data-param]')) {
    const k = inp.dataset.param, pk = params[k];
    if (inp.tagName === 'SELECT') {
      inp.addEventListener('change', () => ctx.apply(`${k} ${pk.value} → ${inp.value}`, d => setParam(d, k, inp.value, editSource(pk.value, pk.source))));
    } else {
      inp.addEventListener('input', () => inp.classList.toggle('bad', parseEng(inp.value) === null));
      inp.addEventListener('keydown', e => {
        e.stopPropagation();
        if (e.key === 'Escape') { inp.value = String(pk.value); inp.blur(); }
        if (e.key !== 'Enter') return;
        const x = parseEng(inp.value); if (x === null || x === pk.value) return;
        ctx.apply(`${k} ${pk.value} → ${inp.value.trim()}`, d => setParam(d, k, x, editSource(pk.value, pk.source)));
      });
    }
  }
}

function tolBox(tol, bands) {
  if (tol === 'none') return '<div class="box">none <span class="note">(not a physical part)</span></div>';
  if (tol === 'tube') return '<div class="box">tube <span class="note">(emission and µ drawn per instance)</span></div>';
  const b = bands?.[tol];
  const pct = b ? (b.pct.length === 2 ? `−${b.pct[0]} / +${b.pct[1]} %` : `±${b.pct[0]} %`) : '';
  return `<div class="box">${esc(tol)} <span class="note">${esc(pct)}</span></div>`;
}

export function showNet(el, i, ctx) {
  const { analysis, drawing, view } = ctx;
  const n = analysis.nets[i];
  const pins = view.pins.filter(p => p.net === i);
  const labels = n.labels.map(l => drawing.labels[l].name);
  el.innerHTML = `<div class="ihead"><b>${esc(n.node === '0' ? 'ground' : n.node)}</b><span>net</span></div>
    <div class="crumb">${pins.length} pins${labels.length ? ` · ${labels.length} labels` : ''}${n.grounds.length ? ` · ${n.grounds.length} grounds` : ''}</div>
    ${field('Node', `<div class="box big">${esc(n.node)}${n.node.startsWith('n_') ? '<small>unlabelled: named after its first pin</small>' : ''}</div>`)}
    ${field('Pins', `<table class="kv">${pins.map(p => {
      const s = drawing.symbols[p.ref], multi = ctx.lib[s.symbol].units.length > 1;
      return `<tr><td><span class="tag" data-ref="${esc(p.ref)}" style="cursor:pointer">${esc(p.ref)}${multi ? String.fromCharCode(64 + p.unit) : ''}</span></td><td>${esc(p.name === p.number ? 'pin ' + p.number : `${p.name} (${p.number})`)}</td></tr>`;
    }).join('')}</table>`)}`;
}
