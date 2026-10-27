// The command palette (Ctrl+K) and the shortcut sheet (?): everything the editor does,
// found by typing. Commands come from the page (main.js) as {label, hint, run}.

import { esc } from './eng.js';

const $ = s => document.querySelector(s);

export const SHORTCUTS = [
  ['Drawing', [['V', 'select'], ['W', 'wire'], ['L', 'label a net'], ['G', 'ground'], ['S', 'section frame'],
               ['Ctrl K', 'command palette: place parts, tools, find'], ['Esc', 'back to select, clear']]],
  ['Selection', [['click / Shift click', 'select / add'], ['drag', 'move (wires follow)'], ['drag on empty', 'box select'],
                 ['drag a wire', 'move its segment'], ['drag from a pin', 'draw a wire'], ['R / X', 'rotate / mirror'],
                 ['arrows', 'nudge (Shift: 5 grid)'], ['Del', 'delete'], ['Ctrl C / X / V / D / A', 'copy, cut, paste, duplicate, all']]],
  ['Wiring', [['click', 'corner'], ['/', 'flip the corner'], ['Enter / double click', 'finish'], ['Esc', 'finish or cancel']]],
  ['View', [['wheel / pinch', 'zoom'], ['right or middle drag, Space drag', 'pan'], ['F', 'fit'], ['Z', 'zoom to the selection'],
            ['+ / -', 'zoom'], ['/', 'find a part or node']]],
  ['Values', [['↑ / ↓ in a value', 'next standard value (E12; Shift: E24), heard at once'], ['Enter', 'apply'], ['Esc', 'revert']]],
  ['Listening', [['1 / 2 / 3', 'dry / A / B'], ['Space tap', 'play / pause'], ['Ctrl Enter', 'render now']]],
  ['File', [['Ctrl Z / Ctrl Shift Z', 'undo / redo'], ['Ctrl S', 'save as a circuit']]],
];

export class Commands {
  constructor(list) {
    this.list = list; // () => [{label, hint, run}]
    this.box = $('#cmdk'); this.input = $('#cmdkin'); this.out = $('#cmdklist');
    this.input.addEventListener('input', () => { this.at = 0; this.render(); });
    this.input.addEventListener('keydown', e => {
      e.stopPropagation();
      if (e.key === 'Escape') this.close();
      else if (e.key === 'ArrowDown') { this.at = Math.min(this.shown.length - 1, this.at + 1); this.render(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { this.at = Math.max(0, this.at - 1); this.render(); e.preventDefault(); }
      else if (e.key === 'Enter') this.run(this.shown[this.at]);
    });
    this.out.addEventListener('pointerdown', e => {
      const it = e.target.closest('[data-i]'); if (it) { e.preventDefault(); this.run(this.shown[+it.dataset.i]); }
    });
    this.box.addEventListener('pointerdown', e => { if (e.target === this.box) this.close(); });
    $('#help').addEventListener('pointerdown', e => { if (e.target.id === 'help') this.closeHelp(); });
    $('#help .sheet').innerHTML = SHORTCUTS.map(([group, keys]) => `<section><h5>${esc(group)}</h5>${keys.map(([k, what]) =>
      `<div><kbd>${esc(k)}</kbd><span>${esc(what)}</span></div>`).join('')}</section>`).join('');
  }

  open() { this.all = this.list(); this.at = 0; this.input.value = ''; this.box.classList.add('on'); this.input.focus(); this.render(); }
  close() { this.box.classList.remove('on'); this.input.blur(); }
  isOpen() { return this.box.classList.contains('on'); }
  openHelp() { $('#help').classList.add('on'); }
  closeHelp() { $('#help').classList.remove('on'); }
  helpOpen() { return $('#help').classList.contains('on'); }

  render() {
    const q = this.input.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const score = c => {
      const l = c.label.toLowerCase();
      if (!q.length) return 0;
      if (!q.every(t => l.includes(t) || (c.hint || '').toLowerCase().includes(t))) return -1;
      return (l.startsWith(q[0]) ? 2 : 0) + (l.split(/[\s:]+/).some(w => w.startsWith(q[0])) ? 1 : 0);
    };
    this.shown = this.all.map(c => [score(c), c]).filter(([s]) => s >= 0).sort((a, b) => b[0] - a[0]).slice(0, 14).map(([, c]) => c);
    this.out.innerHTML = this.shown.length ? this.shown.map((c, i) =>
      `<div class="cmd${i === this.at ? ' on' : ''}" data-i="${i}"><span>${esc(c.label)}</span><small>${esc(c.hint || '')}</small></div>`).join('')
      : '<div class="cmd"><small>nothing matches</small></div>';
  }

  run(c) { if (!c) return; this.close(); c.run(); }
}
