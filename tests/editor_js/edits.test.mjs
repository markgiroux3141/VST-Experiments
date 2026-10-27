// The editor page's edit rules (varimu/listen/editor/edits.js, eng.js), run by Node's own
// test runner (tests/test_editor.py::test_page_modules runs it; no npm).

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { editSource, engText, History, paramHome, setInline, setParam, unlink, valueKey } from '../../varimu/listen/editor/edits.js';
import { parseEng, unitOf, withUnit } from '../../varimu/listen/editor/eng.js';

const drawing = () => ({
  circuit: { values: { load_ohm: { value: 600, source: 'man' } }, controls: { knob: { value: 0.5, min: 0, max: 1, source: 'panel' } } },
  symbols: {
    CC2A: { symbol: 'C', value: '250n', fields: { Param: 'c_couple_f', Source: 'dwg: .25', Tol: 'paper' }, units: {} },
    CC2B: { symbol: 'C', value: '250n', fields: { Param: 'c_couple_f', Source: 'dwg: .25', Genome: 'g.c' }, units: {} },
    R1: { symbol: 'R', value: '1k', fields: { Source: 'mine' }, units: {} },
    RL: { symbol: 'R', value: 'load_ohm', fields: {}, units: {} },
  },
});

test('engineering numbers read as Python reads them', () => {
  assert.equal(parseEng('0.47u'), 4.7e-7);
  assert.equal(parseEng('470n'), 4.7e-7);
  assert.equal(parseEng('4k7'), 4700);
  assert.equal(parseEng('40uF'), 40e-6);
  assert.equal(parseEng('1.0e+9'), 1e9);
  assert.equal(parseEng('load_ohm'), null);
  for (const x of [4.7e-7, 0.25e-6, 33e-3, 600, 2554, 1.5e-6, 10e-12, 117.0, 0.0])
    assert.equal(parseEng(engText(x)), x, engText(x));
  assert.equal(engText(250e-9), '250n');
  assert.equal(withUnit(200000, 'Ω'), '200 kΩ');
  assert.equal(unitOf('c_couple_f'), 'F');
  assert.equal(unitOf(null, 'r'), 'Ω');
});

test('a shared parameter changes on every part, with one source', () => {
  const d = drawing();
  assert.deepEqual(paramHome(d, 'c_couple_f'), { kind: 'symbols', refs: ['CC2A', 'CC2B'] });
  setParam(d, 'c_couple_f', 4.7e-7, 'edit: by ear');
  for (const r of ['CC2A', 'CC2B']) {
    assert.equal(d.symbols[r].value, '470n');
    assert.equal(d.symbols[r].fields.Source, 'edit: by ear');
  }
});

test('sidecar values and controls', () => {
  const d = drawing();
  assert.equal(paramHome(d, 'load_ohm').kind, 'values');
  setParam(d, 'load_ohm', 10000, 'edit');
  assert.deepEqual(d.circuit.values.load_ohm, { value: 10000, source: 'edit' });
  setParam(d, 'knob', 0.8, 'ignored for a control');
  assert.deepEqual(d.circuit.controls.knob, { value: 0.8, min: 0, max: 1, source: 'panel' });
  assert.equal(setParam(d, 'nowhere', 1, 's'), false);
  assert.equal(valueKey(d.symbols.RL), 'load_ohm');
  assert.equal(valueKey(d.symbols.R1), null);
  assert.equal(valueKey(d.symbols.CC2A), 'c_couple_f');
});

test('unlinking a part keeps the parameter whole on the others', () => {
  const d = drawing();
  unlink(d, 'CC2B'); // CC2B carried the genome link: it moves to CC2A
  assert.deepEqual(d.symbols.CC2B.fields, { Source: 'dwg: .25' });
  assert.equal(d.symbols.CC2A.fields.Genome, 'g.c');
  assert.equal(d.symbols.CC2A.fields.Param, 'c_couple_f');
  const e = drawing();
  delete e.symbols.CC2A.fields.Source; // the source lives on the other part only
  unlink(e, 'CC2B');
  assert.equal(e.symbols.CC2A.fields.Source, 'dwg: .25');
  setInline(e, 'CC2B', '330n', 'edit');
  assert.equal(e.symbols.CC2B.value, '330n');
});

test('an edit source says whose it is and what it replaced', () => {
  assert.match(editSource('250n', 'dwg: .25 coupling'), /^edit \d{4}-\d\d-\d\d: by ear; was 250n \(dwg: \.25 coupling\)$/);
  // Editing an edit doesn't nest the attribution.
  const twice = editSource('330n', editSource('250n', 'dwg'));
  assert.equal((twice.match(/by ear/g) || []).length, 1);
});

test('history: undo and redo restore drawings', () => {
  const h = new History();
  const d = drawing();
  h.reset(d);
  h.push(d, 'first');
  setParam(d, 'c_couple_f', 1e-6, 's');
  assert.ok(h.isEdited(d));
  const u = h.undo(d);
  assert.equal(u.label, 'first');
  assert.equal(u.drawing.symbols.CC2A.value, '250n');
  assert.ok(!h.isEdited(u.drawing));
  const r = h.redo(u.drawing);
  assert.equal(r.drawing.symbols.CC2A.value, '1u');
  assert.equal(h.undo(r.drawing).drawing.symbols.CC2A.value, '250n');
  assert.equal(h.undo(drawing()), null);
});
