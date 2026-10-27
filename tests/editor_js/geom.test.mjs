// Topology edits (varimu/listen/editor/geom.js) on the real symbol table, which
// tests/test_editor.py::test_page_modules writes for us ($EDITOR_SYMBOLS).

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import {
  addWire, copyItems, deleteItems, dragSegment, emptySel, moveItems, nextRef, pasteItems, pinPoints, placeSymbol,
  renameRef, route, selectBox, snap, tidy, turnItems,
} from '../../varimu/listen/editor/geom.js';

const lib = JSON.parse(readFileSync(process.env.EDITOR_SYMBOLS, 'utf-8'));
const blank = () => ({ circuit: {}, frames: [], symbols: {}, wires: [], labels: [], grounds: [] });

test('snapping and references', () => {
  assert.equal(snap(3.9), 3.81);
  assert.equal(snap(-0.7), -1.27);
  const d = blank();
  assert.equal(placeSymbol(d, lib, 'R', 10, 10), 'R1');
  assert.equal(placeSymbol(d, lib, 'R', 20, 10), 'R2');
  assert.equal(placeSymbol(d, lib, 'C', 30, 10), 'C1');
  assert.equal(placeSymbol(d, lib, 'Triode_Dual', 40, 10), 'V1');
  assert.deepEqual(Object.keys(d.symbols.V1.units), ['1', '2']);
  assert.equal(nextRef(d, 'R'), 'R3');
  assert.deepEqual(d.symbols.R1.units[1], { x: 10.16, y: 10.16 });
});

test('a wire on a moved pin follows it and keeps its direction', () => {
  const d = blank();
  placeSymbol(d, lib, 'R', 0, 0); // pins at (0, -3.81) and (0, 3.81)
  placeSymbol(d, lib, 'R', 20.32, 0);
  addWire(d, [[0, 3.81], [0, 7.62], [20.32, 7.62], [20.32, 3.81]]);
  const sel = { ...emptySel(), symbols: ['R1'] };
  moveItems(d, lib, sel, 2.54, -2.54);
  const p = pinPoints(lib, d.symbols.R1, 1)['2'];
  assert.deepEqual(p, [2.54, 1.27]);
  const w = d.wires[0];
  assert.deepEqual(w[0], p); // the end followed the pin
  assert.equal(w[0][0], w[1][0]); // the first segment is still vertical
  assert.deepEqual(w.at(-1), [20.32, 3.81]); // the far end stayed
  for (let i = 1; i < w.length; i++) assert.ok(w[i][0] === w[i - 1][0] || w[i][1] === w[i - 1][1], 'orthogonal');
});

test('a straight wire bends at the moved end', () => {
  const d = blank();
  placeSymbol(d, lib, 'R', 0, 0);
  addWire(d, [[0, 3.81], [0, 12.7]]);
  moveItems(d, lib, { ...emptySel(), symbols: ['R1'] }, 5.08, 0);
  assert.deepEqual(d.wires[0], [[5.08, 3.81], [0, 3.81], [0, 12.7]]);
});

test('rotating a part moves its pins and their wires', () => {
  const d = blank();
  placeSymbol(d, lib, 'R', 0, 0);
  addWire(d, [[0, 3.81], [0, 10.16]]);
  turnItems(d, lib, { ...emptySel(), symbols: ['R1'] });
  assert.equal(d.symbols.R1.units[1].rot, 90);
  const p2 = pinPoints(lib, d.symbols.R1, 1)['2'];
  assert.deepEqual(p2, [3.81, 0]); // counter-clockwise: down becomes right
  assert.deepEqual(d.wires[0][0], p2);
  turnItems(d, lib, { ...emptySel(), symbols: ['R1'] }, 'mirror');
  assert.equal(d.symbols.R1.units[1].mirror, true);
});

test('box selection, delete, tidy', () => {
  const d = blank();
  placeSymbol(d, lib, 'R', 0, 0);
  placeSymbol(d, lib, 'R', 50, 0);
  addWire(d, [[0, 3.81], [0, 6.35], [0, 8.89]]); // a straight run with an inner point
  assert.deepEqual(d.wires[0], [[0, 3.81], [0, 8.89]]);
  d.labels.push({ name: 'a', x: 0, y: 8.89 });
  const sel = selectBox(d, [-5, -5, 5, 10]);
  assert.deepEqual(sel.symbols, ['R1']);
  assert.deepEqual(sel.wires, [0]);
  assert.deepEqual(sel.labels, [0]);
  deleteItems(d, sel);
  assert.deepEqual(Object.keys(d.symbols), ['R2']);
  assert.equal(d.wires.length, 0);
  d.wires = [[[0, 0], [0, 0]]];
  tidy(d);
  assert.equal(d.wires.length, 0);
});

test('copy and paste renumber parts and keep their wiring and windings', () => {
  const d = blank();
  placeSymbol(d, lib, 'R', 0, 0);
  placeSymbol(d, lib, 'C', 10.16, 0);
  addWire(d, [[0, 3.81], [10.16, 3.81]]); // R1.2 to C1.2
  d.symbols.R1.fields = { Param: 'r_x', Source: 's' };
  placeSymbol(d, lib, 'Core', 30, 0);
  placeSymbol(d, lib, 'Winding', 35, 0);
  d.symbols.W1.fields.Transformer = 'T1';
  const clip = copyItems(d, lib, { ...emptySel(), symbols: ['R1', 'C1', 'T1', 'W1'] });
  assert.equal(clip.wires.length, 1); // between two copied pins
  const sel = pasteItems(d, lib, clip, 0, 25.4);
  assert.deepEqual(sel.symbols, ['R2', 'C2', 'T2', 'W2']);
  assert.equal(d.symbols.R2.fields.Param, 'r_x');
  assert.equal(d.symbols.W2.fields.Transformer, 'T2');
  assert.deepEqual(d.wires[sel.wires[0]], [[0, 29.21], [10.16, 29.21]]);
});

test('routes and renames', () => {
  assert.deepEqual(route([0, 0], [5, 5]), [[0, 0], [5, 0], [5, 5]]);
  assert.deepEqual(route([0, 0], [5, 5], false), [[0, 0], [0, 5], [5, 5]]);
  assert.deepEqual(route([0, 0], [0, 5]), [[0, 0], [0, 5]]);
  const d = blank();
  placeSymbol(d, lib, 'Core', 0, 0);
  placeSymbol(d, lib, 'Winding', 5, 0);
  d.symbols.W1.fields.Transformer = 'T1';
  assert.ok(renameRef(d, 'T1', 'T9'));
  assert.equal(d.symbols.W1.fields.Transformer, 'T9');
  assert.ok(!renameRef(d, 'W1', 'T9'));
  assert.ok(!renameRef(d, 'W1', '9x'));
});

test('dragging a wire segment sideways keeps its ends', () => {
  const d = blank();
  placeSymbol(d, lib, 'R', 0, 0);
  placeSymbol(d, lib, 'R', 20.32, 0);
  addWire(d, [[0, 3.81], [0, 7.62], [20.32, 7.62], [20.32, 3.81]]);
  dragSegment(d, lib, 0, 1, 3, 5.08); // the horizontal middle segment, down by 5.08 (dx ignored)
  assert.deepEqual(d.wires[0], [[0, 3.81], [0, 12.7], [20.32, 12.7], [20.32, 3.81]]);
  dragSegment(d, lib, 0, 0, 2.54, 0); // the first (vertical) segment: its end at the pin stays
  assert.deepEqual(d.wires[0][0], [0, 3.81]);
  assert.deepEqual(d.wires[0][1], [2.54, 3.81]);
  for (let i = 1; i < d.wires[0].length; i++) {
    const [p, q] = [d.wires[0][i - 1], d.wires[0][i]];
    assert.ok(p[0] === q[0] || p[1] === q[1], 'orthogonal');
  }
});

test('what sits on a dragged segment goes with it', () => {
  const d = blank();
  placeSymbol(d, lib, 'R', 0, 0);
  placeSymbol(d, lib, 'R', 20.32, 0);
  addWire(d, [[0, -3.81], [0, -10.16], [20.32, -10.16], [20.32, -3.81]]);
  addWire(d, [[10.16, -10.16], [10.16, -15.24]]); // a T on the top segment
  d.labels.push({ name: 'bp', x: 5.08, y: -10.16 });
  dragSegment(d, lib, 0, 1, 0, -2.54);
  assert.deepEqual([d.labels[0].x, d.labels[0].y], [5.08, -12.7]);
  assert.deepEqual(d.wires[1][0], [10.16, -12.7]);
  assert.deepEqual(d.wires[0][0], [0, -3.81]);
});
