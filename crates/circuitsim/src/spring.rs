//! A spring reverb tank's springs (docs/REVERB_PLAN.md, E1-E3): the modes of each helical
//! spring and the tank's impulse response from a force at the input beads to the output
//! beads' tangential velocity. `varimu/devices/spring.py` is the reference (its docstring
//! has the physics); the two agree within rounding (`tests/test_spring.py`).
//!
//! **Modes** (Parker & Bilbao, DAFx-09, eq. 1, the curved-rod model; ends pinned radially
//! and free tangentially): `u = a cos(beta s)`, `v = b sin(beta s)`, `beta = n pi / L`,
//! the stiffness over the mass `c^2 [[beta^2, k beta], [k beta, g (k^2 - beta^2)^2 +
//! k^2]]` (`c^2 = E / rho`, `k = 1 / R`, `g = r^2 / 4`). The audio branch is `omega^2 =
//! det / lambda_hi`, `det = c^4 g beta^2 (k^2 - beta^2)^2`; the other branch (above ~c k)
//! is dropped. A mode's weight is `(2 / (rho A L)) a^2 (-1)^n` (a tangential force at
//! `s = 0`, the tangential velocity at `s = L`).
//!
//! **The response** at `fs`: `h[k] = T v(kT)` for `k >= 1`, `v(t) = w exp(-s t) [cos(wd
//! t) - (s / wd) sin(wd t)]`, each mode until it has decayed by `tail_db`, only modes
//! below `min(f_max, 0.45 fs)` (`crate::modal::sum`).

use std::f64::consts::PI;
use std::sync::{Arc, Mutex, OnceLock};

use crate::ir::Spring;

/// One mode: its undamped angular frequency, amplitude decay rate and weight (1 / kg).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Mode {
    pub omega: f64,
    pub decay: f64,
    pub weight: f64,
}

/// The audio branch at wavenumber `beta` for a spring of `c2 = E / rho`, wire radius `r`
/// and curvature `k`: (omega, the tangential share a^2 of the unit eigenvector).
pub fn branch(c2: f64, r: f64, k: f64, beta: f64) -> (f64, f64) {
    let g = 0.25 * r * r;
    let bb = beta * beta;
    let p = bb;
    let q = k * beta;
    let d = k * k - bb;
    let s = g * (d * d) + k * k;
    let mean = 0.5 * (p + s);
    let half = 0.5 * (p - s);
    let hi = mean + (half * half + q * q).sqrt();
    let lo = g * bb * (d * d) / hi;
    let (ea, eb) = (s - lo, -q);
    ((c2 * lo).sqrt(), ea * ea / (ea * ea + eb * eb))
}

/// One spring's audio-branch modes below `f_top_hz` (n = 1, 2, ... until the branch has
/// risen past `f_top` beyond `beta = k`).
pub fn spring_modes(rho: f64, e: f64, sp: [f64; 3], f_top_hz: f64) -> Vec<(f64, f64)> {
    let [r, big_r, length] = sp;
    let c2 = e / rho;
    let k = 1.0 / big_r;
    let w_top = 2.0 * PI * f_top_hz;
    let n_k = k * length / PI;
    let area = PI * r * r;
    let norm = 2.0 / (rho * area * length);
    let mut out = Vec::new();
    for n in 1u64.. {
        let beta = n as f64 * PI / length;
        let (om, a2) = branch(c2, r, k, beta);
        if om > w_top {
            if n as f64 > n_k {
                break;
            }
            continue;
        }
        let sign = if n % 2 == 0 { 1.0 } else { -1.0 };
        out.push((om, norm * a2 * sign));
    }
    out
}

/// The energy decay rate at `f_hz` from `table` (as the plate's).
pub fn energy_decay(table: &[[f64; 2]], f_hz: f64) -> f64 {
    crate::plate::energy_decay(table, f_hz)
}

/// Every spring's modes below `f_top_hz`, the springs in order.
pub fn modes(p: &Spring, f_top_hz: f64) -> Vec<Mode> {
    let mut out = Vec::new();
    for &sp in &p.springs {
        for (omega, weight) in spring_modes(p.density_kg_m3, p.youngs_pa, sp, f_top_hz) {
            out.push(Mode {
                omega,
                decay: 0.5 * energy_decay(&p.decay, omega / (2.0 * PI)),
                weight,
            });
        }
    }
    out
}

/// The impulse response from force (N) to velocity (m/s) at `fs` (see the module docs),
/// as long as the slowest mode needs.
pub fn impulse_response(p: &Spring, fs: f64) -> Vec<f64> {
    let f_top = p.f_max_hz.min(0.45 * fs);
    let t = 1.0 / fs;
    let mut ms: Vec<(usize, Mode)> = modes(p, f_top)
        .into_iter()
        .filter(|m| m.weight != 0.0 && m.omega > m.decay)
        .map(|m| (crate::modal::mode_len(m.decay, p.tail_db, fs), m))
        .collect();
    // Longest first (stable: ties keep the springs' and modes' order).
    ms.sort_by(|a, b| b.0.cmp(&a.0));
    let len = ms.first().map_or(1, |m| m.0.min(60 * fs as usize)).max(2);
    let terms: Vec<crate::modal::Term> = ms
        .iter()
        .map(|&(l, m)| {
            let wd = (m.omega * m.omega - m.decay * m.decay).sqrt();
            crate::modal::Term {
                decay: m.decay,
                wd,
                ca: t * m.weight,
                cb: -(t * m.weight) * m.decay / wd,
                len: l,
            }
        })
        .collect();
    let mut h = crate::modal::sum(&terms, len, t);
    h[0] = 0.0;
    h
}

/// The force (N) on the input beads for the sense voltage `v`: linear, or the pole
/// pieces saturating as `tanh` (`Spring::saturation_v`).
pub fn force(p: &Spring, v: f64) -> f64 {
    if p.saturation_v > 0.0 {
        p.force_per_v * p.saturation_v * (v / p.saturation_v).tanh()
    } else {
        p.force_per_v * v
    }
}

/// Responses computed recently, by tank and rate (see `crate::plate`'s).
type Cache = Mutex<Vec<(String, Arc<Vec<f64>>)>>;

fn cache() -> &'static Cache {
    static C: OnceLock<Cache> = OnceLock::new();
    C.get_or_init(|| Mutex::new(Vec::new()))
}

const CACHED: usize = 6;

fn key(p: &Spring, fs: f64) -> String {
    let mut q = p.clone();
    q.name.clear();
    q.sense_pos.clear();
    q.sense_neg.clear();
    q.out.clear();
    q.force_per_v = 0.0;
    q.out_per_m_s = 0.0;
    q.saturation_v = 0.0;
    format!("{fs}|{}", serde_json::to_string(&q).unwrap_or_default())
}

/// `p`'s impulse response at `fs`, computed once and kept a while.
pub fn response(p: &Spring, fs: f64) -> Arc<Vec<f64>> {
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

/// Compute (and keep) the responses of every spring tank in `ir` at `fs` ahead of a run
/// or an update, off the audio thread.
pub fn prepare(ir: &crate::ir::CircuitIr, fs: f64) {
    for el in ir.elements() {
        if let crate::ir::Element::Spring(p) = el {
            response(p, fs);
        }
    }
}

/// A tank running beside a transient: the force sensed after each sample, the output
/// coil's EMF out at the next.
pub struct Medium {
    pub spring: Spring,
    conv: crate::modal::Convolving,
    fs: f64,
}

impl std::fmt::Debug for Medium {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Medium")
            .field("spring", &self.spring.name)
            .field("fs", &self.fs)
            .field("conv", &self.conv)
            .finish()
    }
}

impl Medium {
    pub fn new(p: &Spring, fs: f64) -> Medium {
        let h = response(p, fs);
        Medium {
            spring: p.clone(),
            conv: crate::modal::Convolving::new(&h, fs),
            fs,
        }
    }

    /// The output's next sample (volts) once the force's sense voltage `v` is in.
    pub fn push(&mut self, v: f64) -> f64 {
        let f = force(&self.spring, v);
        self.spring.out_per_m_s * self.conv.push(f)
    }

    /// New values: the same springs keep ringing; other springs take the force from now
    /// on while the old ones ring out.
    pub fn update(&mut self, p: &Spring) {
        if key(p, self.fs) != key(&self.spring, self.fs) {
            self.conv.replace(&response(p, self.fs), self.fs);
        }
        self.spring = p.clone();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Parker & Bilbao's Leem KA-1210 spring 3 (DAFx-09, Table 2).
    pub(crate) fn leem3() -> Spring {
        let (r, big_r) = (0.175e-3, 2.3e-3);
        let a = 2.0 * PI * big_r * 351.0;
        Spring {
            name: "VSP".into(),
            sense_pos: "a".into(),
            sense_neg: "b".into(),
            force_per_v: 1.0,
            out: "o".into(),
            out_per_m_s: 1.0,
            density_kg_m3: 7800.0,
            youngs_pa: 2e11,
            springs: vec![[r, big_r, (a * a + 0.163 * 0.163).sqrt()]],
            f_max_hz: 16_000.0,
            decay: vec![[100.0, 3.0], [10_000.0, 15.0]],
            tail_db: 40.0,
            saturation_v: 0.0,
        }
    }

    #[test]
    fn the_branch_peaks_at_the_transition_frequency() {
        let p = leem3();
        let [r, big_r, _] = p.springs[0];
        let c = (p.youngs_pa / p.density_kg_m3).sqrt();
        let k = 1.0 / big_r;
        let peak = (1..4000)
            .map(|i| branch(c * c, r, k, k * i as f64 / 4000.0).0)
            .fold(0.0f64, f64::max);
        // F_C = 3 r c / (16 sqrt 5 pi R^2) to first order (their appendix B): 4.47 kHz.
        let fc = 3.0 * r * c / (16.0 * 5f64.sqrt() * PI * big_r * big_r);
        assert!(
            (peak / (2.0 * PI) / fc - 1.0).abs() < 0.01,
            "{}",
            peak / (2.0 * PI)
        );
        // Zero at beta = k; the low end's wave speed r c / (R sqrt(4 + r^2 / R^2)) (their
        // nu_0 before its approximation).
        assert!(branch(c * c, r, k, k).0 < 1e-6);
        let b = 1e-3 * k;
        let v0 = r * c / (big_r * (4.0 + r * r / (big_r * big_r)).sqrt());
        assert!((branch(c * c, r, k, b).0 / b / v0 - 1.0).abs() < 1e-5);
    }

    #[test]
    fn modes_alternate_and_stop_past_the_top() {
        let p = leem3();
        let ms = spring_modes(p.density_kg_m3, p.youngs_pa, p.springs[0], 16_000.0);
        assert!(ms.iter().all(|m| m.0 <= 2.0 * PI * 16_000.0));
        // ~700 modes up to beta = k, a few hundred on the rising branch to 16 kHz.
        assert!((1000..1200).contains(&ms.len()), "{}", ms.len());
        assert!(ms[0].1 < 0.0 && ms[1].1 > 0.0);
    }

    #[test]
    fn a_medium_convolves_its_response() {
        let mut p = leem3();
        p.f_max_hz = 1_500.0;
        p.tail_db = 20.0;
        p.force_per_v = 2.0;
        p.out_per_m_s = 3.0;
        let fs = 4_000.0;
        let h = response(&p, fs);
        let mut m = Medium::new(&p, fs);
        let mut y = vec![m.push(1.0)];
        for _ in 0..80 {
            y.push(m.push(0.0));
        }
        let scale = h.iter().fold(0.0f64, |a, x| a.max(x.abs()));
        for (k, v) in y.iter().enumerate() {
            assert!((v - 6.0 * h[k + 1]).abs() < 1e-12 * scale);
        }
        assert_eq!(h[0], 0.0);
        assert_eq!(*h, impulse_response(&p, fs));
    }

    #[test]
    fn the_drive_saturates_softly() {
        let mut p = leem3();
        p.force_per_v = 2.0;
        assert_eq!(force(&p, 0.3), 0.6);
        p.saturation_v = 0.2;
        assert!((force(&p, 1e-4) - 2e-4).abs() < 1e-9);
        assert!((force(&p, 50.0) - 0.4).abs() < 1e-12);
        assert_eq!(force(&p, -0.3), -force(&p, 0.3));
    }
}
