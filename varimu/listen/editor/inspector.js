// The inspector: a selected part's fields (value, source, genome link and bounds,
// tolerance), or a selected net's pins. A number without a source shows as missing:
// the importer won't compile it (CLAUDE.md, hard rules).

import { esc, parseEng, unitOf, withUnit } from './eng.js';

const META = new Set(['Source', 'Param', 'Genome', 'Tol', 'Unit', 'Notes']);
const KIND = { macro: 'part', device: 'tube or diode', winding: 'transformer winding', core: 'transformer core',
               coupling: 'inductor coupling', switch: 'rotary switch deck', power: 'power' };

export function placeholder(el, info) {
  el.innerHTML = `<div class="placeholder"><b>${esc(info.title)}</b><br>${info.parts} parts · ${info.nets} nets · ${info.sections} sections<br><br>
    Click a part to see its values and sources.<br>Hover a wire to follow its net.</div>`;
}

export function showSymbol(el, ref, ctx) {
  const { drawing, lib, analysis, view } = ctx;
  const s = drawing.symbols[ref], sym = lib[s.symbol], params = analysis.params || {};
  const f = s.fields, out = [];
  out.push(`<div class="ihead"><b>${esc(ref)}</b><span>${esc(s.symbol.replace(/_/g, ' '))}</span></div>`);
  out.push(`<div class="crumb">${esc(view.section.get(ref) || 'main')} · ${esc(KIND[sym.kind] || sym.kind)}</div>`);
  out.push(`<div class="desc">${esc(sym.description)}</div>`);

  if (sym.kind === 'device') out.push(...deviceFields(s, f, params));
  else if (sym.kind === 'winding') {
    out.push(field('Transformer', `<div class="box">${esc(f.Transformer || '–')}, winding <b>${esc(s.value)}</b></div>`));
  } else if (sym.kind === 'switch') {
    const c = params[f.Control];
    out.push(field('Control', `<div class="box">${esc(f.Control || '–')}${c ? ` <span class="note">· ${esc((c.choices || []).join(' / '))}</span>` : ''}</div>`));
  } else if (sym.primary) out.push(...valueFields(ref, s, sym, f, params, drawing));

  if (f.Tol) out.push(field('Tolerance', tolBox(f.Tol, analysis.bands)));
  // The macro's other params: lowercase fields, as YAML; a key shows what it resolves to.
  const rows = Object.entries(f).filter(([k]) => !META.has(k) && !(sym.kind === 'winding' && k === 'Transformer') && !(sym.kind === 'switch' && k === 'Control'));
  if (rows.length) {
    out.push(field('Parameters', `<table class="kv">${rows.map(([k, v]) => {
      const p = params[v];
      const shown = p ? `${esc(v)}<br><span class="note">= ${esc(fmtParam(p, v))}</span>` : esc(v);
      return `<tr><td>${esc(k)}</td><td title="${esc(p?.source || '')}">${shown}</td></tr>`;
    }).join('')}</table>`));
  }
  // Pins and their nodes.
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
    out.push(field('Windings', `<div class="box">${ws.map(([r, w]) => `${esc(w.value)} <span class="note">(${esc(r)})</span>`).join(' · ') || '–'}</div>`));
  }
  el.innerHTML = out.join('');
}

function valueFields(ref, s, sym, f, params, drawing) {
  const out = [];
  const num = parseEng(s.value);
  const key = f.Param || (num === null ? s.value : null);
  const p = key ? params[key] : null;
  const unit = unitOf(key, sym.primary);
  const shown = num !== null ? withUnit(num, unit) : p ? fmtParam(p, key) : s.value;
  const drawn = num !== null ? esc(s.value) : '';
  out.push(field('Value', `<div class="box big">${esc(shown)}${drawn ? `<small>drawn as ${drawn}</small>` : ''}</div>`));
  if (key) {
    const sharers = Object.entries(drawing.symbols).filter(([r, o]) => r !== ref && (o.fields.Param === key || o.value === key)).map(([r]) => r);
    const shared = sharers.length ? ` <span class="note">· shared with</span> ${sharers.slice(0, 6).map(r => `<span class="tag gray" data-ref="${esc(r)}" style="cursor:pointer">${esc(r)}</span>`).join(' ')}${sharers.length > 6 ? ' …' : ''}` : '';
    out.push(field('Parameter', `<div class="box"><span class="tag">${esc(key)}</span>${shared}</div>`));
  }
  const source = f.Source || p?.source;
  out.push(field('Source', source ? `<div class="box src">${esc(source)}</div>` : '<div class="box missing">no source: a number needs one</div>'));
  const genome = f.Genome || p?.genome;
  if (genome) {
    const b = p?.bounds;
    const range = b ? (b.choices ? b.choices.join(' / ') : `${withUnit(b.min, unit)} … ${withUnit(b.max, unit)}`) : 'bounds not found';
    out.push(field('Genome', `<div class="box"><span class="tag gray">${esc(genome)}</span><div class="note" style="margin-top:4px">${esc(range)}</div></div>`));
  }
  if (p?.notes || f.Notes) out.push(field('Notes', `<div class="box src">${esc(f.Notes || p.notes)}</div>`));
  return out;
}

function deviceFields(s, f, params) {
  const p = params[s.value];
  const file = p ? p.value : s.value;
  return [
    field('Device', `<div class="box big">${esc(file)}<small>config/devices/${esc(String(file))}.yaml</small></div>`),
    ...(f.Model ? [field('Model', `<div class="box"><span class="tag">${esc(f.Model)}</span> <span class="note">shared instance</span></div>`)] : []),
    ...(f.Source ? [field('Source', `<div class="box src">${esc(f.Source)}</div>`)] : []),
  ];
}

function tolBox(tol, bands) {
  if (tol === 'none') return '<div class="box">none <span class="note">(not a physical part)</span></div>';
  if (tol === 'tube') return '<div class="box">tube <span class="note">(emission and µ drawn per instance)</span></div>';
  const b = bands?.[tol];
  const pct = b ? (b.pct.length === 2 ? `−${b.pct[0]} / +${b.pct[1]} %` : `±${b.pct[0]} %`) : '';
  return `<div class="box">${esc(tol)} <span class="note">${esc(pct)}</span></div>`;
}

function fmtParam(p, key) {
  if (typeof p.value === 'number') return withUnit(p.value, unitOf(key));
  if (p.kind === 'derived') return 'derived';
  return String(p.value);
}

const field = (label, html) => `<div class="field"><label>${esc(label)}</label>${html}</div>`;

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
