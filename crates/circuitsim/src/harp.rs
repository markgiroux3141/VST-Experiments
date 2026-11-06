//! The Rhodes harp as a medium (docs/RHODES_PLAN.md, RH3): every key's tone generator and
//! pickup, struck by note events, the pickups' EMFs summed by their wiring into the voltage
//! driving the harp's coils in the circuit. `varimu/rhodes/harp.py` is the reference (its
//! `Voice`s on the live tier); the model is a component version compiled by
//! `varimu/rhodes/compile.py` (its docstring has the data's layout).
//!
//! **A voice** is one key: the damped tone bar assembly's complex modes (only the upper of
//! each conjugate pair kept, the outputs doubled in the data), free or under the damper's
//! felt. Between events each mode is a decaying rotation; a note-on throws the hammer at the
//! tine wherever it is, the Hunt-Crossley contact solved inside each contact step with the
//! modes' instantaneous response folded in (`key.contact`); the felt is on whenever the key
//! is up and the pedal isn't down, switched at a key's events and the pedal's (deferred to
//! the end of a contact, as the reference's are). A voice sleeps when its tip's amplitude
//! bound falls under the model's `sleep_m`.
//!
//! **The pickup**: the tip's height (above the pole by the voicing) and its pull-back from
//! the gap (the arc, from its low-rank projection), through the flux map's bicubic B-spline:
//! `emf = -(dPhi/dy y' + dPhi/dg g')`, weighted by the key's share of the wiring.
//!
//! **Rates.** The voices run at `k` internal samples per step (the least whole multiple of
//! the step rate at or above the element's `rate_hz`), the contact at `s` substeps of those
//! (`contact_rate_hz`); the internal EMF is decimated to the step rate by
//! [`crate::partition::Decimator`]'s taps (none at k = 1).
//!
//! **One way.** The harp senses nothing in the circuit (the coils' current doesn't act on
//! the tines), so it renders ahead: up to the last sample whose events are known
//! ([`Medium::known_until`]), in chunks, voice by voice, on [`crate::keyed`]'s machinery
//! (shared with the Clavinet's strings). An event lands at the sample it is queued for, or
//! at the first sample not yet rendered if it comes too late.

use serde::{Deserialize, Deserializer, Serialize, Serializer};

use crate::media::NoteEvent;

/// Base samples rendered at a time when the events are known that far.
pub const CHUNK: usize = crate::keyed::CHUNK;
/// Internal samples between a free voice's sleep checks.
const SLEEP_EVERY: usize = 1024;
/// A mode under this (|z|) at a sleep check is zeroed: decaying on, it would reach the
/// subnormal floats, whose arithmetic is ~100x slower (73 keys ringing ran 30x slower than
/// real time after a second).
const MODE_FLOOR: f64 = 1e-100;
/// Lanes of the modal loops (the modes are padded to a multiple).
const LANES: usize = 4;

// --- The model (the component version's data) --------------------------------------

fn count<'de, D: Deserializer<'de>>(d: D) -> Result<usize, D::Error> {
    let x = f64::deserialize(d)?;
    if x >= 0.0 && x.fract() == 0.0 && x < 1e9 {
        Ok(x as usize)
    } else {
        Err(serde::de::Error::custom(format!("{x} isn't a count")))
    }
}

/// Counts as floats, as the Python IR writes every number.
fn as_f64<S: Serializer>(x: &usize, s: S) -> Result<S::Ok, S::Error> {
    s.serialize_f64(*x as f64)
}

/// Complex numbers as their real and imaginary parts (a matrix row-major).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Complexes {
    pub re: Vec<f64>,
    pub im: Vec<f64>,
}

impl Complexes {
    fn len(&self) -> usize {
        self.re.len()
    }

    fn get(&self, i: usize) -> C64 {
        C64(self.re[i], self.im[i])
    }
}

/// One of a key's systems (free, or under the damper's felt): its kept modes and outputs.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HarpSystem {
    #[serde(deserialize_with = "count", serialize_with = "as_f64")]
    pub modes: usize,
    /// The modes' eigenvalues (1/s).
    pub lam: Complexes,
    /// The hammer's force into the modes (per N).
    pub b: Complexes,
    /// The strike point's displacement and velocity rows (m, m/s per mode; doubled for pairs).
    pub strike: Complexes,
    pub strike_v: Complexes,
    /// The tip's displacement and velocity rows.
    pub tip: Complexes,
    pub tip_v: Complexes,
    #[serde(deserialize_with = "count", serialize_with = "as_f64")]
    pub arc_rank: usize,
    /// The arc's projection P (arc_rank x modes, row-major): arc = |Re(P z)|^2 / 2.
    pub arc: Complexes,
}

/// The state moved between a key's systems: z_new = A z + B conj(z) (new x old, row-major).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HarpTransfer {
    pub a: Complexes,
    pub b: Complexes,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HarpHammer {
    pub mass_kg: f64,
    /// K of the contact force K d^p (1 + alpha d').
    pub stiffness: f64,
    pub exponent: f64,
    pub hysteresis_s_m: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HarpKey {
    /// The key (88-key numbering: A0 = 1).
    #[serde(deserialize_with = "count", serialize_with = "as_f64")]
    pub key: usize,
    /// Its MIDI note.
    #[serde(deserialize_with = "count", serialize_with = "as_f64")]
    pub note: usize,
    pub note_hz: f64,
    /// Its share of the harp's EMF (one over its pickup group's size).
    pub weight: f64,
    pub hammer: HarpHammer,
    pub free: HarpSystem,
    pub damped: HarpSystem,
    pub to_damped: HarpTransfer,
    pub to_free: HarpTransfer,
}

/// The pickup's flux linkage over the tip's height y and its pull-back g: a bicubic
/// B-spline (FITPACK's: knots `ty`, `tg`; coefficients `c`, y's basis outer).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HarpFlux {
    pub ty: Vec<f64>,
    pub tg: Vec<f64>,
    pub c: Vec<f64>,
    pub y_range_m: [f64; 2],
    pub dg_range_m: [f64; 2],
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HarpVelocity {
    /// The hammer's speed at velocity 127.
    pub ff_speed_m_s: f64,
    /// The span from velocity 127 to 1.
    pub range_db: f64,
}

impl HarpVelocity {
    /// The hammer's speed for MIDI velocity `vel` (1-127): `range_db` from 127 to 1.
    pub fn hammer_speed(&self, vel: u8) -> f64 {
        let vel = vel.clamp(1, 127) as f64;
        self.ff_speed_m_s * 10f64.powf(-self.range_db / 20.0 * (127.0 - vel) / 126.0)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HarpCoils {
    pub r_ohm: f64,
    pub l_h: f64,
}

/// A compiled harp (a component version of kind `ep_harp`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HarpModel {
    #[serde(deserialize_with = "count", serialize_with = "as_f64")]
    pub format: usize,
    pub instrument: String,
    pub keys: Vec<HarpKey>,
    pub flux: HarpFlux,
    pub voicing_m: f64,
    pub velocity: HarpVelocity,
    pub contact_window_s: f64,
    pub sleep_m: f64,
    pub arc_rank_tol: f64,
    pub coils: HarpCoils,
}

impl HarpModel {
    pub const FORMAT: usize = 1;

    /// Its arrays' shapes and values (the IR's check).
    pub fn check(&self) -> Result<(), String> {
        if self.format != Self::FORMAT {
            return Err(format!(
                "harp format {} (this code reads {})",
                self.format,
                Self::FORMAT
            ));
        }
        let mut notes = [false; 128];
        for k in &self.keys {
            let at = format!("key {}", k.key);
            if k.note >= 128 || std::mem::replace(&mut notes[k.note], true) {
                return Err(format!("{at}: note {} is out of range or repeated", k.note));
            }
            let h = &k.hammer;
            let positive = [h.mass_kg, h.stiffness, h.exponent, k.weight]
                .iter()
                .all(|v| v.is_finite() && *v > 0.0);
            if !(positive && h.hysteresis_s_m.is_finite() && h.hysteresis_s_m >= 0.0) {
                return Err(format!("{at}: the hammer and the weight must be positive"));
            }
            for (what, s) in [("free", &k.free), ("damped", &k.damped)] {
                let m = s.modes;
                let vecs = [&s.lam, &s.b, &s.strike, &s.strike_v, &s.tip, &s.tip_v];
                if m == 0
                    || vecs.iter().any(|v| v.len() != m || v.im.len() != m)
                    || s.arc_rank == 0
                    || s.arc.len() != s.arc_rank * m
                    || s.arc.im.len() != s.arc_rank * m
                {
                    return Err(format!("{at}, {what}: arrays don't match its {m} modes"));
                }
                if vecs
                    .iter()
                    .chain([&&s.arc])
                    .any(|v| v.re.iter().chain(&v.im).any(|x| !x.is_finite()))
                    || s.lam.re.iter().any(|&r| r > 0.0)
                {
                    return Err(format!("{at}, {what}: values not finite, or a mode grows"));
                }
            }
            for (what, t, from, to) in [
                ("to_damped", &k.to_damped, &k.free, &k.damped),
                ("to_free", &k.to_free, &k.damped, &k.free),
            ] {
                let n = from.modes * to.modes;
                if [&t.a, &t.b].iter().any(|v| v.len() != n || v.im.len() != n) {
                    return Err(format!("{at}, {what}: not {} x {}", to.modes, from.modes));
                }
            }
        }
        let f = &self.flux;
        if f.ty.len() < 8
            || f.tg.len() < 8
            || f.c.len() != (f.ty.len() - 4) * (f.tg.len() - 4)
            || f.ty.windows(2).any(|w| w[1] < w[0])
            || f.tg.windows(2).any(|w| w[1] < w[0])
            || !(f.y_range_m[0] < f.y_range_m[1] && f.dg_range_m[0] < f.dg_range_m[1])
        {
            return Err("flux: knots and coefficients don't make a bicubic spline".into());
        }
        let v = &self.velocity;
        if !(v.ff_speed_m_s > 0.0
            && v.range_db >= 0.0
            && self.contact_window_s > 0.0
            && self.sleep_m > 0.0
            && self.voicing_m.is_finite())
        {
            return Err("velocity, contact window, sleep or voicing out of range".into());
        }
        Ok(())
    }

    /// The hammer's speed for MIDI velocity `vel` (1-127): `range_db` from 127 to 1.
    pub fn hammer_speed(&self, vel: u8) -> f64 {
        self.velocity.hammer_speed(vel)
    }
}

// --- Complex arithmetic -----------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq)]
pub(crate) struct C64(pub(crate) f64, pub(crate) f64);

impl C64 {
    pub(crate) fn mul(self, o: C64) -> C64 {
        C64(self.0 * o.0 - self.1 * o.1, self.0 * o.1 + self.1 * o.0)
    }
    pub(crate) fn add(self, o: C64) -> C64 {
        C64(self.0 + o.0, self.1 + o.1)
    }
    pub(crate) fn sub(self, o: C64) -> C64 {
        C64(self.0 - o.0, self.1 - o.1)
    }
    pub(crate) fn scale(self, s: f64) -> C64 {
        C64(self.0 * s, self.1 * s)
    }
    pub(crate) fn exp(self) -> C64 {
        let m = self.0.exp();
        C64(m * self.1.cos(), m * self.1.sin())
    }
    pub(crate) fn div(self, o: C64) -> C64 {
        let d = o.0 * o.0 + o.1 * o.1;
        C64(
            (self.0 * o.0 + self.1 * o.1) / d,
            (self.1 * o.0 - self.0 * o.1) / d,
        )
    }
    pub(crate) fn norm(self) -> f64 {
        self.0.hypot(self.1)
    }
}

/// (e^x - 1) / x and (e^x - 1 - x) / x^2: the first-order hold's integrals.
pub(crate) fn phi12(x: C64) -> (C64, C64) {
    if x.norm() < 0.1 {
        // Their series to x^10: the rest is below 1e-15 here.
        let (mut e1, mut e2) = (C64(0.0, 0.0), C64(0.0, 0.0));
        let mut p = C64(1.0, 0.0);
        let mut fact = 1.0;
        for n in 0..=10 {
            // x^n / (n + 1)! and x^n / (n + 2)!
            fact *= (n + 1) as f64;
            e1 = e1.add(p.scale(1.0 / fact));
            e2 = e2.add(p.scale(1.0 / (fact * (n + 2) as f64)));
            p = p.mul(x);
        }
        (e1, e2)
    } else {
        let em1 = x.exp().sub(C64(1.0, 0.0));
        (em1.div(x), em1.sub(x).div(x.mul(x)))
    }
}

// --- The flux map ------------------------------------------------------------------

/// A cubic B-spline's span at x (clipped into its range) and its four basis functions
/// and their derivatives there (the NURBS Book's A2.2 / A2.3).
fn cubic_basis(t: &[f64], x: f64) -> (usize, [f64; 4], [f64; 4]) {
    let (lo, hi) = (3, t.len() - 5);
    // the last span whose knot is at or below x
    let l = (lo + t[lo + 1..=hi].partition_point(|&k| k <= x)).min(hi);
    let (n, d) = cubic_basis_at(t, l, x);
    (l - 3, n, d)
}

/// The four basis functions of span l (t[l] <= x <= t[l + 1]) and their derivatives at x.
fn cubic_basis_at(t: &[f64], l: usize, x: f64) -> ([f64; 4], [f64; 4]) {
    let mut nb = [1.0, 0.0, 0.0, 0.0];
    let mut n2 = [0.0; 3];
    let (mut left, mut right) = ([0.0; 4], [0.0; 4]);
    for j in 1..=3 {
        left[j] = x - t[l + 1 - j];
        right[j] = t[l + j] - x;
        let mut saved = 0.0;
        for r in 0..j {
            let temp = nb[r] / (right[r + 1] + left[j - r]);
            nb[r] = saved + right[r + 1] * temp;
            saved = left[j - r] * temp;
        }
        nb[j] = saved;
        if j == 2 {
            n2 = [nb[0], nb[1], nb[2]];
        }
    }
    let mut d = [0.0; 4];
    for (k, dk) in d.iter_mut().enumerate() {
        let a = if k >= 1 {
            let den = t[l + k] - t[l + k - 3];
            if den > 0.0 { n2[k - 1] / den } else { 0.0 }
        } else {
            0.0
        };
        let b = if k <= 2 {
            let den = t[l + k + 1] - t[l + k - 2];
            if den > 0.0 { n2[k] / den } else { 0.0 }
        } else {
            0.0
        };
        *dk = 3.0 * (a - b);
    }
    (nb, d)
}

/// The flux map as a bicubic polynomial per pair of spans (the B-spline converted once):
/// in each span's own coordinates (0..1), Phi = sum A_ij s^i w^j. Its gradient is a few
/// Horner steps, where the B-spline's bases took two dozen divisions a sample.
#[derive(Debug, Clone)]
pub struct FluxPoly {
    /// Span starts and widths along y and g.
    y0: Vec<f64>,
    yw: Vec<f64>,
    g0: Vec<f64>,
    gw: Vec<f64>,
    /// A_ij (i over s = y's, j over w = g's), per (y span, g span), y's outer.
    a: Vec<[[f64; 4]; 4]>,
    y_range: [f64; 2],
    g_range: [f64; 2],
}

/// A knot vector's nonempty spans: (start, width, the first coefficient's index, its four
/// basis functions' power coefficients in the span's coordinate).
type Spans = Vec<(f64, f64, usize, [[f64; 4]; 4])>;

impl FluxPoly {
    pub fn new(f: &HarpFlux) -> FluxPoly {
        // A span's basis functions as cubics in its coordinate: their values at s = 0,
        // 1/3, 2/3, 1 through the inverse Vandermonde.
        const VINV: [[f64; 4]; 4] = [
            [1.0, 0.0, 0.0, 0.0],
            [-5.5, 9.0, -4.5, 1.0],
            [9.0, -22.5, 18.0, -4.5],
            [-4.5, 13.5, -13.5, 4.5],
        ];
        let spans = |t: &[f64]| -> Spans {
            let mut out = Vec::new();
            for l in 3..t.len() - 4 {
                let width = t[l + 1] - t[l];
                if width <= 0.0 {
                    continue;
                }
                let vals: Vec<[f64; 4]> = (0..4)
                    .map(|q| cubic_basis_at(t, l, t[l] + width * q as f64 / 3.0).0)
                    .collect();
                let mut c = [[0.0; 4]; 4];
                for (a, ca) in c.iter_mut().enumerate() {
                    for (i, ci) in ca.iter_mut().enumerate() {
                        *ci = (0..4).map(|q| VINV[i][q] * vals[q][a]).sum();
                    }
                }
                out.push((t[l], width, l - 3, c));
            }
            out
        };
        let (sy, sg) = (spans(&f.ty), spans(&f.tg));
        let cols = f.tg.len() - 4;
        let mut a = Vec::new();
        for &(_, _, ky, ny) in &sy {
            for &(_, _, kg, ng) in &sg {
                let mut m = [[0.0; 4]; 4];
                for (p, nyp) in ny.iter().enumerate() {
                    for (q, ngq) in ng.iter().enumerate() {
                        let c = f.c[(ky + p) * cols + kg + q];
                        for (i, mi) in m.iter_mut().enumerate() {
                            for (j, mij) in mi.iter_mut().enumerate() {
                                *mij += c * nyp[i] * ngq[j];
                            }
                        }
                    }
                }
                a.push(m);
            }
        }
        FluxPoly {
            y0: sy.iter().map(|s| s.0).collect(),
            yw: sy.iter().map(|s| s.1).collect(),
            g0: sg.iter().map(|s| s.0).collect(),
            gw: sg.iter().map(|s| s.1).collect(),
            a,
            y_range: f.y_range_m,
            g_range: f.dg_range_m,
        }
    }

    /// (dPhi/dy, dPhi/dg) at (y, g) clipped into the map; `hint` the y span last used
    /// (the tip moves a little a sample: its span is found walking from there).
    #[inline(always)]
    pub fn gradient(&self, y: f64, g: f64, hint: &mut usize) -> (f64, f64) {
        let y = y.clamp(self.y_range[0], self.y_range[1]);
        let g = g.clamp(self.g_range[0], self.g_range[1]);
        let mut iy = (*hint).min(self.y0.len() - 1);
        while iy > 0 && y < self.y0[iy] {
            iy -= 1;
        }
        while iy + 1 < self.y0.len() && y >= self.y0[iy + 1] {
            iy += 1;
        }
        *hint = iy;
        let mut ig = 0;
        while ig + 1 < self.g0.len() && g >= self.g0[ig + 1] {
            ig += 1;
        }
        let s = (y - self.y0[iy]) / self.yw[iy];
        let w = (g - self.g0[ig]) / self.gw[ig];
        let a = &self.a[iy * self.g0.len() + ig];
        // q_i(w) and its derivative, then along s
        let mut q = [0.0; 4];
        let mut dq = [0.0; 4];
        for i in 0..4 {
            let r = &a[i];
            q[i] = ((r[3] * w + r[2]) * w + r[1]) * w + r[0];
            dq[i] = (3.0 * r[3] * w + 2.0 * r[2]) * w + r[1];
        }
        let ds = (3.0 * q[3] * s + 2.0 * q[2]) * s + q[1];
        let dw = ((dq[3] * s + dq[2]) * s + dq[1]) * s + dq[0];
        (ds / self.yw[iy], dw / self.gw[ig])
    }
}

impl HarpFlux {
    /// (dPhi/dy, dPhi/dg) at (y, g), both clipped into the map.
    pub fn gradient(&self, y: f64, g: f64) -> (f64, f64) {
        let y = y.clamp(self.y_range_m[0], self.y_range_m[1]);
        let g = g.clamp(self.dg_range_m[0], self.dg_range_m[1]);
        let (iy, ny, dy) = cubic_basis(&self.ty, y);
        let (ig, ng, dg) = cubic_basis(&self.tg, g);
        let cols = self.tg.len() - 4;
        let (mut py, mut pg) = (0.0, 0.0);
        for a in 0..4 {
            let row = &self.c[(iy + a) * cols + ig..(iy + a) * cols + ig + 4];
            let (mut sv, mut sd) = (0.0, 0.0);
            for b in 0..4 {
                sv += ng[b] * row[b];
                sd += dg[b] * row[b];
            }
            py += dy[a] * sv;
            pg += ny[a] * sd;
        }
        (py, pg)
    }
}

// --- A voice ----------------------------------------------------------------------

/// A system at the voice's rates, its modes padded to a multiple of [`LANES`] (structure
/// of arrays: the modal loops vectorize).
#[derive(Debug, Clone)]
struct Sys {
    m: usize,
    /// The kept modes before padding.
    modes: usize,
    rot: (Vec<f64>, Vec<f64>),
    tip: (Vec<f64>, Vec<f64>),
    tip_v: (Vec<f64>, Vec<f64>),
    /// P and P Lambda, rank x m.
    arc: (Vec<f64>, Vec<f64>),
    arc_v: (Vec<f64>, Vec<f64>),
    /// |tip_j| (the sleep test's bound).
    tip_abs: Vec<f64>,
}

impl Sys {
    fn new(s: &HarpSystem, dt: f64) -> Sys {
        let modes = s.modes;
        let m = modes.div_ceil(LANES) * LANES;
        let pad = |v: Vec<f64>| {
            let mut v = v;
            v.resize(m, 0.0);
            v
        };
        let split = |f: &dyn Fn(usize) -> C64| {
            let (re, im): (Vec<f64>, Vec<f64>) = (0..modes).map(f).map(|c| (c.0, c.1)).unzip();
            (pad(re), pad(im))
        };
        let lam = |j| s.lam.get(j);
        let rank = s.arc_rank;
        let mut arc = (vec![0.0; rank * m], vec![0.0; rank * m]);
        let mut arc_v = (vec![0.0; rank * m], vec![0.0; rank * m]);
        for r in 0..rank {
            for j in 0..modes {
                let p = s.arc.get(r * modes + j);
                let pl = p.mul(lam(j));
                arc.0[r * m + j] = p.0;
                arc.1[r * m + j] = p.1;
                arc_v.0[r * m + j] = pl.0;
                arc_v.1[r * m + j] = pl.1;
            }
        }
        Sys {
            m,
            modes,
            rot: split(&|j| lam(j).scale(dt).exp()),
            tip: split(&|j| s.tip.get(j)),
            tip_v: split(&|j| s.tip_v.get(j)),
            arc,
            arc_v,
            tip_abs: pad((0..modes).map(|j| s.tip.get(j).norm()).collect()),
        }
    }
}

/// The free system's contact step at h (the first-order hold's exact step of each mode).
#[derive(Debug, Clone)]
struct ContactStep {
    phi: Vec<C64>,
    g0: Vec<C64>,
    g1: Vec<C64>,
    strike: Vec<C64>,
    strike_v: Vec<C64>,
    /// The strike point's instantaneous responses to the step's end force.
    gd: f64,
    gv: f64,
    h: f64,
}

impl ContactStep {
    fn new(s: &HarpSystem, h: f64) -> ContactStep {
        let n = s.modes;
        let (mut phi, mut g0, mut g1) = (Vec::new(), Vec::new(), Vec::new());
        for j in 0..n {
            let x = s.lam.get(j).scale(h);
            let (e1, e2) = phi12(x);
            let bh = s.b.get(j).scale(h);
            phi.push(x.exp());
            g1.push(bh.mul(e2));
            g0.push(bh.mul(e1.sub(e2)));
        }
        let strike: Vec<C64> = (0..n).map(|j| s.strike.get(j)).collect();
        let strike_v: Vec<C64> = (0..n).map(|j| s.strike_v.get(j)).collect();
        let re_dot = |c: &[C64], z: &[C64]| c.iter().zip(z).map(|(a, b)| a.mul(*b).0).sum::<f64>();
        ContactStep {
            gd: re_dot(&strike, &g1),
            gv: re_dot(&strike_v, &g1),
            phi,
            g0,
            g1,
            strike,
            strike_v,
            h,
        }
    }
}

/// A hammer in contact (or in flight towards the tine) over its window.
#[derive(Debug, Clone)]
struct Contact {
    /// The hammer's height and speed (m, m/s; up towards the tine).
    z: f64,
    v: f64,
    f_prev: f64,
    /// Internal samples left in the window.
    left: usize,
}

/// One key over the timeline.
#[derive(Debug, Clone)]
struct Voice {
    weight: f64,
    hammer: HarpHammer,
    free: Sys,
    damped: Sys,
    contact_step: ContactStep,
    to_damped: HarpTransfer,
    to_free: HarpTransfer,
    /// The modal state (in the current system's modes; padded).
    z: (Vec<f64>, Vec<f64>),
    on_damped: bool,
    asleep: bool,
    contact: Option<Contact>,
    held: bool,
    pedal: bool,
    since_check: usize,
    /// The flux map's y span last used.
    span: usize,
    /// Scratch: a contact step's free part.
    xf: Vec<C64>,
}

const GRAVITY_M_S2: f64 = 9.81;

impl Voice {
    fn new(k: &HarpKey, dt: f64, s: usize) -> Voice {
        let damped = Sys::new(&k.damped, dt);
        let m = damped.m.max(Sys::new(&k.free, dt).m);
        Voice {
            weight: k.weight,
            hammer: k.hammer.clone(),
            free: Sys::new(&k.free, dt),
            damped,
            contact_step: ContactStep::new(&k.free, dt / s as f64),
            to_damped: k.to_damped.clone(),
            to_free: k.to_free.clone(),
            z: (vec![0.0; m], vec![0.0; m]),
            on_damped: true,
            asleep: true,
            contact: None,
            held: false,
            pedal: false,
            since_check: 0,
            span: 0,
            xf: vec![C64(0.0, 0.0); k.free.modes],
        }
    }

    fn sys(&self) -> &Sys {
        if self.on_damped {
            &self.damped
        } else {
            &self.free
        }
    }

    /// Onto the damped system (or off it), the state carried through the physical
    /// coordinates.
    fn switch(&mut self, damped: bool) {
        if damped == self.on_damped {
            return;
        }
        if !self.asleep {
            let (t, from, to) = if damped {
                (&self.to_damped, self.free.modes, self.damped.modes)
            } else {
                (&self.to_free, self.damped.modes, self.free.modes)
            };
            let z: Vec<C64> = (0..from).map(|j| C64(self.z.0[j], self.z.1[j])).collect();
            let mut new = vec![C64(0.0, 0.0); to];
            for (i, n) in new.iter_mut().enumerate() {
                for (j, zj) in z.iter().enumerate() {
                    let a = t.a.get(i * from + j);
                    let b = t.b.get(i * from + j);
                    *n = n.add(a.mul(*zj)).add(b.mul(C64(zj.0, -zj.1)));
                }
            }
            self.z.0.fill(0.0);
            self.z.1.fill(0.0);
            for (j, c) in new.iter().enumerate() {
                self.z.0[j] = c.0;
                self.z.1[j] = c.1;
            }
        }
        self.on_damped = damped;
    }

    /// The damper where the key and the pedal put it (unless the hammer is at the tine:
    /// then at the contact's end).
    fn settle_damper(&mut self) {
        if self.contact.is_none() {
            self.switch(!(self.held || self.pedal));
        }
    }

    fn end_contact(&mut self) {
        if self.contact.take().is_some() {
            self.settle_damper();
        }
    }

    fn event(&mut self, ev: NoteEvent, speed: f64, window: usize) {
        match ev {
            NoteEvent::On { .. } => {
                self.end_contact();
                self.held = true;
                if self.asleep {
                    self.z.0.fill(0.0);
                    self.z.1.fill(0.0);
                }
                self.switch(false);
                self.asleep = false;
                let cs = &self.contact_step;
                let y0: f64 = (0..self.free.modes)
                    .map(|j| cs.strike[j].mul(C64(self.z.0[j], self.z.1[j])).0)
                    .sum();
                self.contact = Some(Contact {
                    z: y0,
                    v: speed,
                    f_prev: 0.0,
                    left: window.max(1),
                });
            }
            NoteEvent::Off { .. } => {
                self.held = false;
                self.end_contact();
                self.settle_damper();
            }
            NoteEvent::Pedal { down } => {
                self.pedal = down;
                self.settle_damper();
            }
            // The Rhodes has no aftertouch.
            NoteEvent::Pressure { .. } => {}
        }
    }

    /// One internal sample of contact: `s` steps with the force solved in each.
    fn contact_sample(&mut self, s: usize) {
        let c = self.contact.as_mut().expect("in contact");
        let cs = &self.contact_step;
        let hm = &self.hammer;
        let (h, m) = (cs.h, hm.mass_kg);
        let n = self.free.modes;
        let xf = &mut self.xf;
        for _ in 0..s {
            // the free part (F at the step's end 0)
            let (mut y_free, mut yv_free) = (0.0, 0.0);
            for (j, xj) in xf.iter_mut().enumerate().take(n) {
                let x = cs.phi[j]
                    .mul(C64(self.z.0[j], self.z.1[j]))
                    .add(cs.g0[j].scale(c.f_prev));
                y_free += cs.strike[j].mul(x).0;
                yv_free += cs.strike_v[j].mul(x).0;
                *xj = x;
            }
            let z_free =
                c.z + h * c.v - h * h * (2.0 * c.f_prev / m) / 6.0 - 0.5 * GRAVITY_M_S2 * h * h;
            let v_free = c.v - h * c.f_prev / (2.0 * m) - GRAVITY_M_S2 * h;
            let d_free = z_free - y_free;
            let dd_free = v_free - yv_free;
            let cd = cs.gd + h * h / (6.0 * m);
            let cv = cs.gv + h / (2.0 * m);
            let mut f = 0.0;
            if d_free > 0.0 {
                f = c.f_prev.max(0.0);
                for _ in 0..50 {
                    let d = d_free - cd * f;
                    let dd = dd_free - cv * f;
                    let (r, dr) = if d <= 0.0 {
                        (f, 1.0)
                    } else {
                        let hc = 1.0 + hm.hysteresis_s_m * dd;
                        let r = f - hm.stiffness * d.powf(hm.exponent) * hc.max(0.0);
                        let mut dr = 1.0;
                        if hc > 0.0 {
                            dr += hm.stiffness
                                * (hm.exponent * d.powf(hm.exponent - 1.0) * cd * hc
                                    + d.powf(hm.exponent) * hm.hysteresis_s_m * cv);
                        }
                        (r, dr)
                    };
                    let step = r / dr;
                    f = (f - step).max(0.0);
                    if step.abs() < 1e-12 * f.abs().max(1.0) {
                        break;
                    }
                }
            }
            for (j, xj) in xf.iter().enumerate().take(n) {
                let x = xj.add(cs.g1[j].scale(f));
                self.z.0[j] = x.0;
                self.z.1[j] = x.1;
            }
            c.z = z_free - h * h * f / (6.0 * m);
            c.v = v_free - h * f / (2.0 * m);
            c.f_prev = f;
        }
        c.left -= 1;
        // The hammer gone for good: falling, below the lowest the strike point can reach
        // (its modes' amplitudes summed; they only decay). The rest of the window would
        // step the free motion only: end it now (the result is the window's; a pending
        // damper can't be, the key being down).
        if c.f_prev == 0.0 && c.v <= 0.0 && c.left > 0 {
            let reach: f64 = (0..n)
                .map(|j| cs.strike[j].norm() * self.z.0[j].hypot(self.z.1[j]))
                .sum();
            if c.z < -reach {
                c.left = 0;
            }
        }
    }

    /// The tip's (displacement, velocity) and the arc's (pull-back, rate) now.
    #[inline(always)]
    fn outputs(sys: &Sys, zr: &[f64], zi: &[f64]) -> (f64, f64, f64, f64) {
        let m = sys.m;
        let (zr, zi) = (&zr[..m], &zi[..m]);
        let tip = dot(&sys.tip.0[..m], &sys.tip.1[..m], zr, zi);
        let tip_v = dot(&sys.tip_v.0[..m], &sys.tip_v.1[..m], zr, zi);
        let (mut arc, mut arc_v) = (0.0, 0.0);
        for ((ar, ai), (vr, vi)) in sys
            .arc
            .0
            .chunks_exact(m)
            .zip(sys.arc.1.chunks_exact(m))
            .zip(sys.arc_v.0.chunks_exact(m).zip(sys.arc_v.1.chunks_exact(m)))
        {
            let pr = dot(ar, ai, zr, zi);
            let pv = dot(vr, vi, zr, zi);
            arc += pr * pr;
            arc_v += pr * pv;
        }
        (tip, tip_v, 0.5 * arc, arc_v)
    }

    /// Add `out.len()` internal samples of this voice's weighted EMF into `out`.
    fn render(&mut self, out: &mut [f64], flux: &FluxPoly, voicing: f64, s: usize, sleep: f64) {
        let mut i = 0;
        while i < out.len() && !self.asleep {
            if self.contact.is_some() {
                self.contact_sample(s);
                let sys = &self.free;
                let (tip, tip_v, arc, arc_v) = Self::outputs(sys, &self.z.0, &self.z.1);
                let (py, pg) = flux.gradient(voicing + tip, arc, &mut self.span);
                out[i] -= self.weight * (py * tip_v + pg * arc_v);
                i += 1;
                if self.contact.as_ref().is_some_and(|c| c.left == 0) {
                    self.end_contact();
                }
                continue;
            }
            // Free: rotate and read, up to the next sleep check.
            let n = (out.len() - i).min(SLEEP_EVERY - self.since_check);
            let sys = if self.on_damped {
                &self.damped
            } else {
                &self.free
            };
            free_run(
                sys,
                (&mut self.z.0, &mut self.z.1),
                &mut out[i..i + n],
                (flux, &mut self.span),
                voicing,
                self.weight,
            );
            i += n;
            self.since_check += n;
            if self.since_check >= SLEEP_EVERY {
                self.since_check = 0;
                let sys = self.sys();
                let bound: f64 = (0..sys.modes)
                    .map(|j| sys.tip_abs[j] * self.z.0[j].hypot(self.z.1[j]))
                    .sum();
                if bound < sleep {
                    self.asleep = true;
                    self.z.0.fill(0.0);
                    self.z.1.fill(0.0);
                } else {
                    for j in 0..self.z.0.len() {
                        if self.z.0[j].abs() < MODE_FLOOR && self.z.1[j].abs() < MODE_FLOOR {
                            self.z.0[j] = 0.0;
                            self.z.1[j] = 0.0;
                        }
                    }
                }
            }
        }
    }
}

/// Re(sum c z) over equal slices (a multiple of [`LANES`] long), in four lanes.
#[inline(always)]
fn dot(cr: &[f64], ci: &[f64], zr: &[f64], zi: &[f64]) -> f64 {
    let mut acc = [0.0; LANES];
    for (((cr, ci), zr), zi) in cr
        .chunks_exact(LANES)
        .zip(ci.chunks_exact(LANES))
        .zip(zr.chunks_exact(LANES))
        .zip(zi.chunks_exact(LANES))
    {
        for l in 0..LANES {
            acc[l] += cr[l] * zr[l] - ci[l] * zi[l];
        }
    }
    (acc[0] + acc[1]) + (acc[2] + acc[3])
}

/// A free voice over `out`: each sample its modes rotated, its outputs read, its EMF added.
/// Vectorized with AVX2 where the CPU has it (the same operations lane for lane: the result
/// is the same bit for bit; no FMA).
fn free_run(
    sys: &Sys,
    (zr, zi): (&mut [f64], &mut [f64]),
    out: &mut [f64],
    (flux, span): (&FluxPoly, &mut usize),
    voicing: f64,
    weight: f64,
) {
    #[cfg(target_arch = "x86_64")]
    if std::is_x86_feature_detected!("avx2") {
        // SAFETY: the CPU has AVX2 (checked above).
        unsafe { free_run_avx2(sys, (zr, zi), out, (flux, span), voicing, weight) };
        return;
    }
    free_run_impl(sys, (zr, zi), out, (flux, span), voicing, weight);
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn free_run_avx2(
    sys: &Sys,
    (zr, zi): (&mut [f64], &mut [f64]),
    out: &mut [f64],
    (flux, span): (&FluxPoly, &mut usize),
    voicing: f64,
    weight: f64,
) {
    free_run_impl(sys, (zr, zi), out, (flux, span), voicing, weight);
}

#[inline(always)]
fn free_run_impl(
    sys: &Sys,
    (zr, zi): (&mut [f64], &mut [f64]),
    out: &mut [f64],
    (flux, span): (&FluxPoly, &mut usize),
    voicing: f64,
    weight: f64,
) {
    let m = sys.m;
    let (zr, zi) = (&mut zr[..m], &mut zi[..m]);
    let (rr, ri) = (&sys.rot.0[..m], &sys.rot.1[..m]);
    for o in out.iter_mut() {
        for (((zr, zi), rr), ri) in zr
            .chunks_exact_mut(LANES)
            .zip(zi.chunks_exact_mut(LANES))
            .zip(rr.chunks_exact(LANES))
            .zip(ri.chunks_exact(LANES))
        {
            for l in 0..LANES {
                let (a, c) = (zr[l], zi[l]);
                zr[l] = a * rr[l] - c * ri[l];
                zi[l] = a * ri[l] + c * rr[l];
            }
        }
        let (tip, tip_v, arc, arc_v) = Voice::outputs(sys, zr, zi);
        let (py, pg) = flux.gradient(voicing + tip, arc, span);
        *o -= weight * (py * tip_v + pg * arc_v);
    }
}

// --- The medium -------------------------------------------------------------------

/// What every harp voice reads.
#[derive(Debug)]
pub struct HarpCtx {
    flux: FluxPoly,
    voicing: f64,
    sleep: f64,
    s: usize,
    window: usize,
    velocity: HarpVelocity,
}

impl crate::keyed::KeyVoice for Voice {
    type Ctx = HarpCtx;

    fn asleep(&self) -> bool {
        self.asleep
    }

    fn event(&mut self, ev: NoteEvent, ctx: &HarpCtx) {
        let speed = match ev {
            NoteEvent::On { velocity, .. } => ctx.velocity.hammer_speed(velocity),
            NoteEvent::Pressure { .. } => return,
            _ => 0.0,
        };
        Voice::event(self, ev, speed, ctx.window);
    }

    fn render(&mut self, buf: &mut [f64], _n: usize, from: usize, to: usize, ctx: &HarpCtx) {
        Voice::render(
            self,
            &mut buf[from..to],
            &ctx.flux,
            ctx.voicing,
            ctx.s,
            ctx.sleep,
        );
    }
}

/// The harp beside the circuit at step rate `fs` (see the module docs): its voices on
/// [`crate::keyed::Medium`].
pub struct Medium {
    pub harp: crate::ir::Harp,
    /// Internal samples per step and contact steps per internal sample.
    pub k: usize,
    pub s: usize,
    keys: crate::keyed::Medium<Voice>,
}

impl std::fmt::Debug for Medium {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Medium")
            .field("harp", &self.harp.name)
            .field("k", &self.k)
            .field("s", &self.s)
            .field("keys", &self.keys)
            .finish()
    }
}

impl Medium {
    pub fn new(el: &crate::ir::Harp, fs: f64) -> Medium {
        Medium::with_workers(el, fs, crate::keyed::workers())
    }

    /// [`Medium::new`] with `n` worker threads (the result is the same with any number).
    pub fn with_workers(el: &crate::ir::Harp, fs: f64, n: usize) -> Medium {
        let k = ((el.rate_hz / fs) - 1e-9).ceil().max(1.0) as usize;
        let s = ((el.contact_rate_hz / (fs * k as f64)) - 1e-9)
            .ceil()
            .max(1.0) as usize;
        let dt = 1.0 / (fs * k as f64);
        let model = &el.model;
        let voices = model
            .keys
            .iter()
            .map(|key| (key.note as u8, Voice::new(key, dt, s)))
            .collect();
        let ctx = HarpCtx {
            flux: FluxPoly::new(&model.flux),
            voicing: model.voicing_m,
            sleep: model.sleep_m,
            s,
            window: (model.contact_window_s * fs * k as f64).round() as usize,
            velocity: model.velocity.clone(),
        };
        Medium {
            harp: el.clone(),
            k,
            s,
            keys: crate::keyed::Medium::new(voices, ctx, fs, k, 1, n),
        }
    }

    /// Keep every internal sample rendered from now on ([`Medium::raw`]; tests).
    pub fn keep_raw(&mut self) {
        self.keys.keep_raw();
    }

    pub fn raw(&self) -> &[f64] {
        self.keys.raw(0)
    }

    /// The decimation's delay in steps.
    pub fn delay_steps(&self) -> f64 {
        self.keys.delay_steps()
    }

    /// The next push's step (events for it and later land on time).
    pub fn position(&self) -> usize {
        self.keys.position()
    }

    /// An event at step `at` (in order with the others queued; one for a step already
    /// rendered lands at the first one that isn't).
    pub fn queue(&mut self, at: usize, ev: NoteEvent) {
        self.keys.queue(at, ev);
    }

    /// Every event up to step `at` is queued (`usize::MAX`: all of them).
    pub fn known_until(&mut self, at: usize) {
        self.keys.known_until(at);
    }

    /// The EMF at the next step (the push at step p gives step p + 1's).
    pub fn push(&mut self) -> f64 {
        let mut y = [0.0];
        self.keys.push_into(&mut y);
        y[0]
    }

    /// Notes ringing (not asleep) after the last chunk.
    pub fn sounding(&self) -> usize {
        self.keys.sounding()
    }

    /// The pedal's state after the last chunk.
    pub fn pedal(&self) -> bool {
        self.keys.pedal()
    }

    /// Whether `el` keeps this medium playing (the same model and rates).
    pub fn same(&self, el: &crate::ir::Harp) -> bool {
        el.model == self.harp.model
            && el.rate_hz == self.harp.rate_hz
            && el.contact_rate_hz == self.harp.contact_rate_hz
    }

    pub fn fs(&self) -> f64 {
        self.keys.fs()
    }

    /// Which voice plays MIDI `note` (None: not on the harp).
    pub fn voice_of(&self, note: u8) -> Option<usize> {
        self.keys.voice_of(note)
    }
}

/// The harp alone: `n` steps at `fs` from rest, `events` (step, event) in order; returns
/// the EMF at every step (sample 0 the rest's) and every internal sample (index 0 the
/// rest's).
pub fn render(
    el: &crate::ir::Harp,
    fs: f64,
    n: usize,
    events: &[(usize, NoteEvent)],
) -> (Vec<f64>, Vec<f64>) {
    let mut m = Medium::new(el, fs);
    m.keep_raw();
    for &(at, ev) in events {
        m.queue(at, ev);
    }
    m.known_until(usize::MAX);
    let mut y = vec![0.0];
    for _ in 1..n {
        y.push(m.push());
    }
    let mut raw = vec![0.0];
    raw.extend_from_slice(m.raw());
    raw.truncate((n - 1) * m.k + 1);
    (y, raw)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_hold_integrals_match_their_closed_forms() {
        for x in [C64(-0.05, 0.03), C64(-0.3, 2.0), C64(-0.099, 0.0)] {
            let (e1, e2) = phi12(x);
            let ex = x.exp();
            let w1 = ex.sub(C64(1.0, 0.0)).div(x);
            let w2 = ex.sub(C64(1.0, 0.0)).sub(x).div(x.mul(x));
            assert!(e1.sub(w1).norm() < 1e-13, "{x:?}: {e1:?} vs {w1:?}");
            assert!(e2.sub(w2).norm() < 1e-12, "{x:?}: {e2:?} vs {w2:?}");
        }
        // Tiny x, where the closed forms cancel: their series' first terms.
        let x = C64(-1e-6, 1e-5);
        let (e1, e2) = phi12(x);
        let x2 = x.mul(x);
        let w1 = C64(1.0, 0.0).add(x.scale(0.5)).add(x2.scale(1.0 / 6.0));
        let w2 = C64(0.5, 0.0)
            .add(x.scale(1.0 / 6.0))
            .add(x2.scale(1.0 / 24.0));
        assert!(e1.sub(w1).norm() < 1e-15 && e2.sub(w2).norm() < 1e-15);
    }

    #[test]
    fn the_polynomial_is_the_spline() {
        // A spline on uneven knots, its coefficients arbitrary.
        let ty = vec![0.0, 0.0, 0.0, 0.0, 0.2, 0.5, 0.6, 1.0, 1.0, 1.0, 1.0];
        let tg = vec![0.0, 0.0, 0.0, 0.0, 0.3, 0.3, 0.3, 0.3];
        let n = (ty.len() - 4) * (tg.len() - 4);
        let f = HarpFlux {
            c: (0..n).map(|i| ((i * 7919) % 13) as f64 - 6.0).collect(),
            ty,
            tg,
            y_range_m: [0.0, 1.0],
            dg_range_m: [0.0, 0.3],
        };
        let p = FluxPoly::new(&f);
        let mut hint = 3;
        for (y, g) in [
            (0.0, 0.0),
            (0.1, 0.05),
            (0.5, 0.2),
            (0.55, 0.29),
            (0.99, 0.3),
            (0.31, 0.12),
        ] {
            let (a, b) = f.gradient(y, g);
            let (c, d) = p.gradient(y, g, &mut hint);
            assert!(
                (a - c).abs() < 1e-10 * (1.0 + a.abs()),
                "{y} {g}: {a} vs {c}"
            );
            assert!(
                (b - d).abs() < 1e-10 * (1.0 + b.abs()),
                "{y} {g}: {b} vs {d}"
            );
        }
    }

    #[test]
    fn the_basis_is_a_partition_of_unity_with_its_derivatives() {
        let t = [0.0, 0.0, 0.0, 0.0, 0.3, 0.5, 1.2, 2.0, 2.0, 2.0, 2.0];
        for x in [0.0, 0.1, 0.3, 0.49, 1.0, 1.99, 2.0] {
            let (_, n, d) = cubic_basis(&t, x);
            assert!((n.iter().sum::<f64>() - 1.0).abs() < 1e-14, "{x}");
            assert!(d.iter().sum::<f64>().abs() < 1e-12, "{x}");
        }
        // The derivative by differences.
        let (l0, n0, d0) = cubic_basis(&t, 0.7);
        let (l1, n1, _) = cubic_basis(&t, 0.7 + 1e-7);
        assert_eq!(l0, l1);
        for i in 0..4 {
            assert!(((n1[i] - n0[i]) / 1e-7 - d0[i]).abs() < 1e-5);
        }
    }
}
