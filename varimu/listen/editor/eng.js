// Engineering numbers as varimu.kicad.values reads them ("40u", "4k7", "470"), and values
// shown with their unit ("200 kΩ").

const PREFIX = { p: -12, n: -9, u: -6, 'µ': -6, m: -3, '': 0, k: 3, M: 6, G: 9 };
const UNIT = '(?:ohms?|Ω|F|H|V|A|Hz)?';
const PLAIN = new RegExp(`^([-+]?(?:\\d+\\.?\\d*|\\.\\d+))(?:[eE]([-+]?\\d+))?\\s*([pnuµmkMG]?)\\s*${UNIT}$`);
const EMBEDDED = new RegExp(`^(\\d+)([pnuµmkMGR])(\\d+)\\s*${UNIT}$`);

/** The number `text` writes, or null when it isn't one (then it is a key). */
export function parseEng(text) {
  const s = String(text).trim();
  let m = PLAIN.exec(s);
  if (m) return Number(m[1]) * 10 ** ((+m[2] || 0) + PREFIX[m[3]]);
  m = EMBEDDED.exec(s);
  if (m) return Number(`${m[1]}.${m[3]}`) * 10 ** (PREFIX[m[2]] ?? 0);
  return null;
}

const SI = [[1e9, 'G'], [1e6, 'M'], [1e3, 'k'], [1, ''], [1e-3, 'm'], [1e-6, 'µ'], [1e-9, 'n'], [1e-12, 'p']];

/** 200000, 'Ω' -> "200 kΩ"; 2.5e-7, 'F' -> "250 nF". Plain for unitless or odd values. */
export function withUnit(x, unit) {
  if (typeof x !== 'number' || !isFinite(x)) return String(x);
  if (!unit) return trim(x);
  if (unit === '%') return `${trim(x)} %`;
  if (x === 0) return `0 ${unit}`;
  const a = Math.abs(x);
  const [scale, p] = SI.find(([s]) => a >= s * 0.9995) || SI[SI.length - 1];
  return `${trim(x / scale)} ${p}${unit}`;
}

function trim(x) {
  const a = Math.abs(x);
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
