//! A plate reverb's medium (docs/REVERB_PLAN.md, E6): the modes of a thin tensioned
//! plate, simply supported, and its impulse response from a point force at the
//! exciter to the acceleration at the pickup. `varimu/devices/plate.py` is the
//! reference; the two agree within rounding (`tests/test_plate.py`).
//!
//! **Modes** (Ducceschi & Webb 2016, eqs. 12-13; Russo 2021, eqs. 3.39-3.40 with the
//! square restored): `Phi_m(x, y) = sqrt(4 / (Lx Ly)) sin(m1 pi x / Lx) sin(m2 pi y /
//! Ly)` (unit norm), `omega_m^2 = (T0 / (rho H)) b + (D / (rho H)) b^2` with `b = (m1
//! pi / Lx)^2 + (m2 pi / Ly)^2` and `D = E H^3 / (12 (1 - nu^2))`. A point force `P`
//! drives each mode, `q'' + 2 s q' + omega^2 q = Phi_m(x_in) P / (rho H)` (eq. 10), and
//! the pickup reads `sum q_m'' Phi_m(x_out)`: the EMT 140's pickups are accelerometers
//! (Russo 2021, p.3).
//!
//! **Losses.** Each mode's amplitude decays as `exp(-s t)` with `s = sigma_E(f) / 2`,
//! where `sigma_E` is the plate's energy decay rate at the mode's frequency (`T60 = 6
//! ln 10 / sigma_E`: the convention of the sources' loss formulas, Russo eq. 3.11), a
//! table of (Hz, 1/s) interpolated linearly in log frequency and held at its ends
//! ([`Plate::decay`]; the builder makes it from the EMT 140's measured decay curves).
//!
//! **The impulse response** at sample rate `fs`: `h[k] = T a(kT)` for `k >= 1`
//! (impulse invariance; `h[0]`, the force's instantaneous share, is never used: the
//! pickup is a distance away), each mode summed until it has decayed by
//! [`Plate::tail_db`], only modes below `min(f_max, 0.45 fs)`. Computed in fixed time
//! segments in parallel, each segment's start taken in closed form, so the result is
//! the same bit for bit on any number of threads.

use std::f64::consts::PI;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, OnceLock};

use crate::ir::Plate;

/// One mode: its undamped angular frequency, amplitude decay rate and the product of
/// its shapes at the exciter and the pickup over `rho H` (m^2 / kg).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Mode {
    pub omega: f64,
    pub decay: f64,
    pub weight: f64,
}

/// The energy decay rate at `f_hz` from `table` ((Hz, 1/s) rising in Hz): linear in
/// log frequency between its points, held at its ends.
pub fn energy_decay(table: &[[f64; 2]], f_hz: f64) -> f64 {
    let Some(first) = table.first() else {
        return 0.0;
    };
    if f_hz <= first[0] {
        return first[1];
    }
    for w in table.windows(2) {
        let ([f0, s0], [f1, s1]) = (w[0], w[1]);
        if f_hz <= f1 {
            let t = (f_hz / f0).ln() / (f1 / f0).ln();
            return s0 + t * (s1 - s0);
        }
    }
    table[table.len() - 1][1]
}

/// The plate's bending stiffness over its mass per area, `kappa^2 = D / (rho H)`
/// (m^4 / s^2), and its tension over its mass per area (m^2 / s^2).
pub fn stiffness(p: &Plate) -> (f64, f64) {
    let rho_h = p.density_kg_m3 * p.thickness_m;
    let d = p.youngs_pa * p.thickness_m.powi(3) / (12.0 * (1.0 - p.poisson * p.poisson));
    (d / rho_h, p.tension_n_m / rho_h)
}

/// The modes below `f_top_hz`, in (m1, m2) order (m1 outer).
pub fn modes(p: &Plate, f_top_hz: f64) -> Vec<Mode> {
    let (kappa2, tension) = stiffness(p);
    let rho_h = p.density_kg_m3 * p.thickness_m;
    let w_top = 2.0 * PI * f_top_hz;
    let w2_top = w_top * w_top;
    let norm = 4.0 / (p.lx_m * p.ly_m);
    let w2 = |b: f64| tension * b + kappa2 * b * b;
    let mut out = Vec::new();
    for m1 in 1u32.. {
        let kx = m1 as f64 * PI / p.lx_m;
        if w2(kx * kx) > w2_top {
            break;
        }
        let sx = (m1 as f64 * PI * p.drive_xy[0]).sin() * (m1 as f64 * PI * p.pickup_xy[0]).sin();
        for m2 in 1u32.. {
            let ky = m2 as f64 * PI / p.ly_m;
            let b = kx * kx + ky * ky;
            let w2m = w2(b);
            if w2m > w2_top {
                break;
            }
            let sy =
                (m2 as f64 * PI * p.drive_xy[1]).sin() * (m2 as f64 * PI * p.pickup_xy[1]).sin();
            let omega = w2m.sqrt();
            out.push(Mode {
                omega,
                decay: 0.5 * energy_decay(&p.decay, omega / (2.0 * PI)),
                weight: norm * sx * sy / rho_h,
            });
        }
    }
    out
}

/// Samples per segment of the parallel computation (fixed: the result doesn't depend
/// on the threads).
const SEGMENT: usize = 1 << 14;

/// The impulse response from force (N) to acceleration (m/s^2) at `fs` (see the module
/// docs), as long as the slowest mode needs.
pub fn impulse_response(p: &Plate, fs: f64) -> Vec<f64> {
    let f_top = p.f_max_hz.min(0.45 * fs);
    let t = 1.0 / fs;
    let ln_tail = p.tail_db.abs() / 20.0 * std::f64::consts::LN_10;
    // Each mode's length: until exp(-s t) is down by tail_db.
    let mut ms: Vec<(usize, Mode)> = modes(p, f_top)
        .into_iter()
        .filter(|m| m.weight != 0.0 && m.omega > m.decay)
        .map(|m| {
            let len = if m.decay > 0.0 {
                ((ln_tail / m.decay) * fs).ceil() as usize + 1
            } else {
                usize::MAX
            };
            (len, m)
        })
        .collect();
    // Longest first (stable: ties keep the (m1, m2) order).
    ms.sort_by(|a, b| b.0.cmp(&a.0));
    let len = ms.first().map_or(1, |m| m.0.min(60 * fs as usize)).max(2);
    let lens: Vec<usize> = ms.iter().map(|m| m.0).collect();
    let modes: Vec<Mode> = ms.into_iter().map(|m| m.1).collect();
    let mut h = vec![0.0; len];
    let n_seg = len.div_ceil(SEGMENT);
    let next = AtomicUsize::new(0);
    let threads = std::thread::available_parallelism()
        .map_or(1, |n| n.get())
        .clamp(1, 16);
    let chunks: Vec<(usize, &mut [f64])> = h.chunks_mut(SEGMENT).enumerate().collect();
    let chunks = Mutex::new(chunks.into_iter().map(Some).collect::<Vec<_>>());
    std::thread::scope(|scope| {
        for _ in 0..threads {
            scope.spawn(|| {
                loop {
                    let i = next.fetch_add(1, Ordering::Relaxed);
                    if i >= n_seg {
                        break;
                    }
                    let (s, out) = chunks.lock().expect("chunks")[i].take().expect("a segment");
                    segment(&modes, &lens, s * SEGMENT, t, out);
                }
            });
        }
    });
    h[0] = 0.0;
    h
}

/// Samples `k0 .. k0 + out.len()` of the response: every mode still sounding there.
fn segment(modes: &[Mode], lens: &[usize], k0: usize, t: f64, out: &mut [f64]) {
    // Modes are sorted longest first: the ones sounding at k0 are a prefix.
    let active = lens.partition_point(|&l| l > k0);
    const LANES: usize = 8;
    let mut i = 0;
    while i < active {
        let n = (active - i).min(LANES);
        let mut zr = [0.0; LANES];
        let mut zi = [0.0; LANES];
        let mut rr = [1.0; LANES];
        let mut ri = [0.0; LANES];
        let mut ca = [0.0; LANES];
        let mut cb = [0.0; LANES];
        // Where each lane stops (modes longest first: a lane's end is at most the one's
        // before it).
        let mut ends = [0usize; LANES];
        for j in 0..n {
            let m = modes[i + j];
            let wd = (m.omega * m.omega - m.decay * m.decay).sqrt();
            // z = exp((-s + i wd) k T): its value at k0 in closed form, the step's
            // rotation r.
            let mag = (-m.decay * k0 as f64 * t).exp();
            let ph = wd * k0 as f64 * t;
            zr[j] = mag * ph.cos();
            zi[j] = mag * ph.sin();
            let rm = (-m.decay * t).exp();
            rr[j] = rm * (wd * t).cos();
            ri[j] = rm * (wd * t).sin();
            // a(t) = w exp(-s t) [-2 s cos(wd t) + ((s^2 - wd^2) / wd) sin(wd t)], times T.
            ca[j] = t * m.weight * (-2.0 * m.decay);
            cb[j] = t * m.weight * (m.decay * m.decay - wd * wd) / wd;
            ends[j] = lens[i + j].saturating_sub(k0).min(out.len());
        }
        // Run up to each lane's end in turn, the shortest lane dropping out at its end.
        let mut start = 0;
        for cut in (0..n).rev() {
            let stop = ends[cut];
            for o in out.iter_mut().take(stop).skip(start) {
                let mut acc = 0.0;
                for j in 0..LANES {
                    acc += ca[j] * zr[j] + cb[j] * zi[j];
                    let (a, b) = (zr[j], zi[j]);
                    zr[j] = a * rr[j] - b * ri[j];
                    zi[j] = a * ri[j] + b * rr[j];
                }
                *o += acc;
            }
            start = start.max(stop);
            ca[cut] = 0.0;
            cb[cut] = 0.0;
        }
        i += n;
    }
}

/// Impulse responses computed recently, by plate and rate: a knob change built on a
/// background thread ([`prepare`]) is found here when the stream updates.
type Cache = Mutex<Vec<(String, Arc<Vec<f64>>)>>;

fn cache() -> &'static Cache {
    static C: OnceLock<Cache> = OnceLock::new();
    C.get_or_init(|| Mutex::new(Vec::new()))
}

/// How many responses the cache keeps.
const CACHED: usize = 6;

fn key(p: &Plate, fs: f64) -> String {
    let mut q = p.clone();
    // What doesn't change the response.
    q.name.clear();
    q.sense_pos.clear();
    q.sense_neg.clear();
    q.out.clear();
    q.force_per_v = 0.0;
    q.out_per_m_s2 = 0.0;
    format!("{fs}|{}", serde_json::to_string(&q).unwrap_or_default())
}

/// `p`'s impulse response at `fs`, computed once and kept a while.
pub fn response(p: &Plate, fs: f64) -> Arc<Vec<f64>> {
    let k = key(p, fs);
    if let Some((_, h)) = cache().lock().expect("cache").iter().find(|(c, _)| *c == k) {
        return h.clone();
    }
    let h = Arc::new(impulse_response(p, fs));
    let mut c = cache().lock().expect("cache");
    c.retain(|(x, _)| *x != k);
    c.push((k, h.clone()));
    if c.len() > CACHED {
        c.remove(0);
    }
    h
}

/// Compute (and keep) the responses of every plate in `ir` at `fs` ahead of a run or
/// an update, off the audio thread.
pub fn prepare(ir: &crate::ir::CircuitIr, fs: f64) {
    for el in ir.elements() {
        if let crate::ir::Element::Plate(p) = el {
            response(p, fs);
        }
    }
}

/// A plate running beside a transient: the force sensed after each sample, the
/// pickup's next sample out. A response that changes (a knob) starts a new
/// convolution; the old one keeps ringing out on silence, as the plate's energy
/// would.
pub struct Medium {
    pub plate: Plate,
    conv: crate::convolve::Convolver,
    old: Option<(crate::convolve::Convolver, usize)>,
    fs: f64,
}

impl std::fmt::Debug for Medium {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Medium")
            .field("plate", &self.plate.name)
            .field("fs", &self.fs)
            .field("ringing_out", &self.old.is_some())
            .finish()
    }
}

/// The convolution's block at `fs`: 256 samples at 48 kHz, doubling with the rate.
pub fn block(fs: f64) -> usize {
    ((256.0 * fs / 48_000.0).round() as usize)
        .next_power_of_two()
        .clamp(64, 4096)
}

impl Medium {
    pub fn new(p: &Plate, fs: f64) -> Medium {
        let h = response(p, fs);
        Medium {
            plate: p.clone(),
            conv: crate::convolve::Convolver::new(&h, block(fs)),
            old: None,
            fs,
        }
    }

    /// The pickup's next sample (volts) once the force's sense voltage `v` is in.
    pub fn push(&mut self, v: f64) -> f64 {
        let f = self.plate.force_per_v * v;
        let mut a = self.conv.push(f);
        if let Some((c, left)) = &mut self.old {
            a += c.push(0.0);
            *left -= 1;
            if *left == 0 {
                self.old = None;
            }
        }
        self.plate.out_per_m_s2 * a
    }

    /// New values for the plate: the same response keeps running; another one takes
    /// the force from now on while the old one rings out.
    pub fn update(&mut self, p: &Plate) {
        if key(p, self.fs) == key(&self.plate, self.fs) {
            self.plate = p.clone();
            return;
        }
        let h = response(p, self.fs);
        let new = crate::convolve::Convolver::new(&h, block(self.fs));
        let old = std::mem::replace(&mut self.conv, new);
        let ring = response(&self.plate, self.fs).len();
        self.old = Some((old, ring));
        self.plate = p.clone();
    }
}

/// The responses' cache (tests).
pub fn cached() -> usize {
    cache().lock().map_or(0, |c| c.len())
}

#[cfg(test)]
mod tests {
    use super::*;

    pub(crate) fn emt140() -> Plate {
        Plate {
            name: "PL".into(),
            sense_pos: "a".into(),
            sense_neg: "b".into(),
            force_per_v: 1.0,
            out: "o".into(),
            out_per_m_s2: 1.0,
            lx_m: 2.0,
            ly_m: 1.0,
            thickness_m: 0.5e-3,
            density_kg_m3: 7872.0,
            youngs_pa: 2e11,
            poisson: 0.3,
            tension_n_m: 600.0,
            drive_xy: [0.52, 0.53],
            pickup_xy: [0.47, 0.62],
            f_max_hz: 20_000.0,
            decay: vec![[100.0, 1.38], [500.0, 3.0], [10_000.0, 7.9]],
            tail_db: 90.0,
        }
    }

    #[test]
    fn modes_follow_the_closed_form() {
        let p = emt140();
        let ms = modes(&p, 20_000.0);
        let (k2, t) = stiffness(&p);
        // The first mode: m1 = m2 = 1.
        let b = (PI / 2.0).powi(2) + PI.powi(2);
        assert!((ms[0].omega - (t * b + k2 * b * b).sqrt()).abs() < 1e-9);
        // About 1.3 modes per Hz (S / (4 pi) sqrt(rho H / D) per rad/s): ~26,000 below
        // 20 kHz.
        let density = 2.0 / (4.0 * PI) / k2.sqrt() * 2.0 * PI;
        assert!(
            (ms.len() as f64 / (20_000.0 * density) - 1.0).abs() < 0.05,
            "{}",
            ms.len()
        );
        assert!((density - 1.31).abs() < 0.02, "{density}");
    }

    #[test]
    fn decay_tables_interpolate_in_log_frequency() {
        let t = [[100.0, 1.0], [1000.0, 3.0]];
        assert_eq!(energy_decay(&t, 50.0), 1.0);
        assert!((energy_decay(&t, 316.227766) - 2.0).abs() < 1e-6);
        assert_eq!(energy_decay(&t, 5000.0), 3.0);
    }

    #[test]
    fn the_response_is_its_modes_summed_and_the_same_on_any_threads() {
        let mut p = emt140();
        p.f_max_hz = 600.0; // a few hundred modes: the direct sum is quick
        p.tail_db = 30.0;
        let fs = 8_000.0;
        let h = impulse_response(&p, fs);
        let t = 1.0 / fs;
        let ms = modes(&p, 600.0);
        for k in [1usize, 7, 1000, 20_000, h.len() - 1] {
            let tk = k as f64 * t;
            let want: f64 = ms
                .iter()
                .filter(|m| {
                    let len = ((30.0 / 20.0 * std::f64::consts::LN_10 / m.decay) * fs).ceil() + 1.0;
                    (k as f64) < len
                })
                .map(|m| {
                    let wd = (m.omega * m.omega - m.decay * m.decay).sqrt();
                    t * m.weight
                        * (-m.decay * tk).exp()
                        * (-2.0 * m.decay * (wd * tk).cos()
                            + (m.decay * m.decay - wd * wd) / wd * (wd * tk).sin())
                })
                .sum();
            let scale = h.iter().fold(0.0f64, |a, v| a.max(v.abs()));
            assert!(
                (h[k] - want).abs() < 1e-9 * scale,
                "k {k}: {} vs {want}",
                h[k]
            );
        }
        // Segments are independent of the threads: a second run is identical.
        assert_eq!(h, impulse_response(&p, fs));
        assert_eq!(h[0], 0.0);
    }

    #[test]
    fn a_medium_convolves_its_response() {
        let mut p = emt140();
        p.f_max_hz = 400.0;
        p.tail_db = 20.0;
        p.force_per_v = 2.0;
        p.out_per_m_s2 = 3.0;
        let fs = 4_000.0;
        let h = response(&p, fs);
        let mut m = Medium::new(&p, fs);
        let mut y = Vec::new();
        y.push(m.push(1.0));
        for _ in 0..50 {
            y.push(m.push(0.0));
        }
        for (k, v) in y.iter().enumerate() {
            assert!(
                (v - 6.0 * h[k + 1]).abs() < 1e-12 * h.iter().fold(0.0f64, |a, x| a.max(x.abs()))
            );
        }
        assert!(cached() >= 1);
    }
}
