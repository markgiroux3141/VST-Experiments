// Engineering numbers as varimu.kicad.values reads them ("40u", "4k7", "470"), and values
// shown with their unit ("200 kΩ").

const PREFIX = { p: -12, n: -9, u: -6, 'µ': -6, m: -3, '': 0, k: 3, M: 6, G: 9 };
const UNIT = '(?:ohms?|Ω|F|H|V|A|Hz)?';
const PLAIN = new RegExp(`^([-+]?(?:\\d+\\.?\\d*|\\.\\d+))(?:[eE]([-+]?\\d+))?\\s*([pnuµmkMG]?)\\s*${UNIT}$`);
const EMBEDDED = new RegExp(`^(\\d+)([pnuµmkMGR])(\\d+)\\s*${UNIT}$`);

/** The number `text` writes, or null when it isn't one (then it is a key). Built from a
 *  decimal string, so it is the double Python's reader gives ("0.47u" is 4.7e-7 exactly). */
export function parseEng(text) {
  const s = String(text).trim();
  let m = PLAIN.exec(s);
  if (m) return Number(`${m[1]}e${(+m[2] || 0) + PREFIX[m[3]]}`);
  m = EMBEDDED.exec(s);
  if (m) return Number(`${m[1]}.${m[3]}e${PREFIX[m[2]] ?? 0}`);
  return null;
}

const SI = [[1e9, 'G'], [1e6, 'M'], [1e3, 'k'], [1, ''], [1e-3, 'm'], [1e-6, 'µ'], [1e-9, 'n'], [1e-12, 'p']];

/** 200000, 'Ω' -> "200 kΩ"; 2.5e-7, 'F' -> "250 nF". Plain for unitless or odd values. */
export function withUnit(x, unit) {
  if (typeof x !== 'number' || !isFinite(x)) return String(x);
  if (!unit) return trim(x);
  if (unit === '%') return `${trim(x)} %`;
  if (/[²³]/.test(unit)) return `${trim(x)} ${unit}`; // a prefix doesn't scale a squared unit
  if (x === 0) return `0 ${unit}`;
  const a = Math.abs(x);
  const [scale, p] = SI.find(([s]) => a >= s * 0.9995) || SI[SI.length - 1];
  return `${trim(x / scale)} ${p}${unit}`;
}

function trim(x) {
  const a = Math.abs(x);
  if (Number.isInteger(x) && a < 1e6) return String(x);
  if (a !== 0 && (a >= 1e6 || a < 1e-3)) return x.toExponential(3).replace(/\.?0+e/, 'e');
  return String(+x.toPrecision(4));
}

/** The unit a parameter key or a macro param implies (CLAUDE.md: units in names). */
export function unitOf(key, primary) {
  const k = String(key || '');
  const bySuffix = [['_ohm', 'Ω'], ['_f', 'F'], ['_h', 'H'], ['_v', 'V'], ['_hz', 'Hz'], ['_a', 'A'],
                    ['_m2', 'm²'], ['_m', 'm'], ['_s', 's'], ['_pct', '%'], ['_db', 'dB']];
  for (const [s, u] of bySuffix) if (k.endsWith(s)) return u;
  return { r: 'Ω', z: 'Ω', c: 'F', l: 'H', v: 'V', amplitude_v: 'V', v_rms: 'V', operating_v: 'V' }[primary] || '';
}

export function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

const E12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2];
const E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1];

/** The next standard value above (dir 1) or below (dir -1) x in the E12 (or E24) series:
 *  how a part's value is stepped by ear. */
export function stepE(x, dir, series = 12) {
  if (!(x > 0)) return x;
  const s = series === 24 ? E24 : E12;
  const dec = Math.floor(Math.log10(x) + 1e-9);
  const m = x / 10 ** dec;
  const all = [...s.map(v => v / 10), ...s, ...s.map(v => v * 10)];
  const cand = dir > 0 ? all.find(v => v > m * (1 + 1e-6)) : [...all].reverse().find(v => v < m * (1 - 1e-6));
  return Number(`${+cand.toPrecision(3)}e${dec}`);
}
