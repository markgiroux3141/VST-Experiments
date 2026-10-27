// Edits to the drawing (its JSON, as varimu.editor.drawing writes it), and their history.
//
// Every edit keeps the importer's rules: a number has a source (an edit's source says it
// is the user's and what it was), parts sharing a Param agree on value and source, a
// genome link belongs to a parameter, never to an inline value.

import { parseEng } from './eng.js';

export const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

/** The default source of an edited value: whose it is, and what it replaced. Editing an
 *  edit keeps what the first edit replaced (the value's real provenance). */
export function editSource(oldValue, oldSource) {
  const earlier = /^edit [\d-]+: by ear; (was .*)$/.exec(oldSource || '');
  if (earlier) return `edit ${today()}: by ear; ${earlier[1]}`;
  return `edit ${today()}: by ear; was ${oldValue}${oldSource ? ` (${oldSource})` : ''}`;
}

/** Where parameter `key` lives: the symbols that carry it as their Param, or the
 *  sidecar's values / controls / device_params entry. */
export function paramHome(d, key) {
  const symbols = Object.entries(d.symbols).filter(([, s]) => s.fields.Param === key).map(([r]) => r);
  if (symbols.length) return { kind: 'symbols', refs: symbols };
  for (const kind of ['controls', 'values', 'device_params'])
    if (d.circuit[kind] && key in d.circuit[kind]) return { kind, entry: d.circuit[kind][key] };
  return null;
}

/** The value text a symbol shows for a number: what varimu.kicad.values reads exactly. */
export function engText(x) {
  if (typeof x !== 'number') return String(x);
  if (Number.isInteger(x) && Math.abs(x) < 1000) return String(x); // an int stays an int
  const a = Math.abs(x);
  const pre = [[1e9, 'G'], [1e6, 'M'], [1e3, 'k'], [1, ''], [1e-3, 'm'], [1e-6, 'u'], [1e-9, 'n'], [1e-12, 'p']]
    .find(([s]) => a >= s * 0.9995);
  if (!pre) return String(x);
  let m = String(+(x / pre[0]).toPrecision(12));
  if (pre[1] === '' && !m.includes('.') && !m.includes('e')) m += '.0';
  return m + pre[1];
}

/** Set parameter `key` to `value` (a number or a string) with `source`. Returns false when
 *  the key lives nowhere the drawing can change. */
export function setParam(d, key, value, source) {
  const home = paramHome(d, key);
  if (!home) return false;
  if (home.kind === 'symbols') {
    for (const ref of home.refs) {
      const f = d.symbols[ref].fields;
      d.symbols[ref].value = typeof value === 'number' ? engText(value) : String(value);
      if (source !== undefined) f.Source = source;
    }
  } else {
    home.entry.value = value;
    if (source !== undefined && home.kind !== 'controls') home.entry.source = source;
  }
  return true;
}

/** A symbol's own value (no Param): its Value and Source. */
export function setInline(d, ref, text, source) {
  const s = d.symbols[ref];
  s.value = text;
  s.fields.Source = source;
}

/** Take a symbol off its shared Param: its value becomes inline, with the parameter's
 *  source (a genome link stays with the parameter). */
export function unlink(d, ref) {
  const s = d.symbols[ref], f = s.fields, key = f.Param;
  if (!key) return;
  const others = Object.entries(d.symbols).filter(([r, o]) => r !== ref && o.fields.Param === key);
  const source = f.Source || others.map(([, o]) => o.fields.Source).find(Boolean) || '';
  if (!others.some(([, o]) => o.fields.Source) && f.Source && others.length) others[0][1].fields.Source = f.Source;
  if (!others.length) return; // the only part on it: nothing to unlink from
  // The parameter's other metadata stays on the parts that still carry it.
  for (const k of ['Genome', 'Unit', 'Notes'])
    if (f[k] && !others.some(([, o]) => o.fields[k])) others[0][1].fields[k] = f[k];
  delete f.Param; delete f.Genome; delete f.Unit; delete f.Notes;
  f.Source = source;
}

/** The parameter a symbol's main value is (its Param, or a key it names), or null. */
export function valueKey(s) {
  if (s.fields.Param) return s.fields.Param;
  return parseEng(s.value) === null && s.value ? s.value : null;
}

export class History {
  constructor(onChange) { this.onChange = onChange; this.reset(null); }
  reset(drawing) { this.past = []; this.future = []; this.base = drawing ? JSON.stringify(drawing) : null; this.onChange?.(this); }
  /** Record the drawing before an edit labelled `label`. */
  push(drawing, label) { this.past.push({ json: JSON.stringify(drawing), label }); this.future = []; this.onChange?.(this); }
  undo(current) {
    const e = this.past.pop(); if (!e) return null;
    this.future.push({ json: JSON.stringify(current), label: e.label }); this.onChange?.(this);
    return { drawing: JSON.parse(e.json), label: e.label };
  }
  redo(current) {
    const e = this.future.pop(); if (!e) return null;
    this.past.push({ json: JSON.stringify(current), label: e.label }); this.onChange?.(this);
    return { drawing: JSON.parse(e.json), label: e.label };
  }
  isEdited(current) { return this.base !== null && JSON.stringify(current) !== this.base; }
}
