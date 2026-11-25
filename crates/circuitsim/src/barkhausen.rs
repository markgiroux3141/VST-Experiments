//! Barkhausen avalanches in a transformer core (docs/PART_NOISE_PLAN.md): the port of
//! `varimu/devices/barkhausen.py` (its docstring has the model), in the same order of
//! operations. A medium ([`crate::media`]): it senses a core node (B, 1 V = 1 mT) after every
//! step, replays it through the core's Jiles-Atherton model, finds the irreversible
//! magnetization's place on its landscape of pinning sites, and drives its output with the
//! current of the magnetization's jumps (a Vccs carries it into the core node).

use std::collections::HashMap;
use std::f64::consts::PI;

use crate::devices::core::{CoreState, MU0, MagneticCore, langevin};
use crate::ir::{self, TESLA_PER_V};
use crate::noise;

const TWO_M53: f64 = 1.0 / 9_007_199_254_740_992.0;

// The part's constants (`varimu.devices.barkhausen`, `varimu.circuit.parts.barkhausen`; their
// sources there): the smallest jump and the largest at STRESS 1 (in Ms), the size law's
// exponent, a bin's width in largest jumps, a jump's time and the high-pass; the Vccs's gm
// (a volt on the output is a microamp into the core) and the output's load.
pub const S_MIN: f64 = 1e-8;
pub const S_UNIT: f64 = 1e-6;
pub const TAU: f64 = 1.5;
pub const BIN_FACTOR: f64 = 100.0;
pub const AVALANCHE_HZ: f64 = 2000.0;
pub const HIGHPASS_HZ: f64 = 5.0;
pub const GM_S: f64 = 1e-6;
pub const LOAD_OHM: f64 = 1e6;

/// Draws `start .. start + out.len()` of the stream with key `key`, in (0, 1): word k % 4 of
/// Philox's block at counter k / 4 + 1.
pub fn uniforms(key: [u64; 2], start: u64, out: &mut [f64]) {
    for (i, o) in out.iter_mut().enumerate() {
        let k = start + i as u64;
        let w = noise::philox(k / 4 + 1, key);
        *o = ((w[(k % 4) as usize] >> 11) as f64 + 0.5) * TWO_M53;
    }
}

/// The mean of p(s) ~ s^-tau on [s_min, s_max].
pub fn mean_size(s_min: f64, s_max: f64, tau: f64) -> f64 {
    let e = 1.0 - tau;
    let (lo_e, hi_e) = (s_min.powf(e), s_max.powf(e));
    (s_min.powf(2.0 - tau) - s_max.powf(2.0 - tau)) / (tau - 2.0) / ((hi_e - lo_e) / e)
}

/// A bin of the landscape: sorted positions inside it (0 .. W) and the sizes below each
/// (`cum[0]` = 0, the last = W).
#[derive(Debug, Clone)]
pub struct Bin {
    pub pos: Vec<f64>,
    pub cum: Vec<f64>,
}

fn stream(j: i64) -> u32 {
    j.rem_euclid(1i64 << 32) as u32
}

/// Bin `j`'s jumps (Python's `make_bin`).
pub fn make_bin(seed: u64, name: &str, j: i64, s_min: f64, s_max: f64, tau: f64, w: f64) -> Bin {
    let mean = mean_size(s_min, s_max, tau);
    let m = w / mean;
    let mut z = [0.0];
    noise::normals(
        noise::key(seed, &format!("{name}:count"), stream(j)),
        0,
        &mut z,
    );
    let count = ((m + m.sqrt() * z[0] + 0.5).floor() as i64).max(1) as usize;
    let mut pos = vec![0.0; count];
    uniforms(
        noise::key(seed, &format!("{name}:pos"), stream(j)),
        0,
        &mut pos,
    );
    for p in pos.iter_mut() {
        *p *= w;
    }
    pos.sort_by(|a, b| a.partial_cmp(b).expect("finite"));
    let mut u = vec![0.0; count];
    uniforms(
        noise::key(seed, &format!("{name}:size"), stream(j)),
        0,
        &mut u,
    );
    let e = 1.0 - tau;
    let (lo_e, hi_e) = (s_min.powf(e), s_max.powf(e));
    let sizes: Vec<f64> = u
        .iter()
        .map(|x| (lo_e + x * (hi_e - lo_e)).powf(1.0 / e))
        .collect();
    let mut total = 0.0;
    for s in &sizes {
        total += s;
    }
    let scale = w / total;
    let mut cum = Vec::with_capacity(count + 1);
    cum.push(0.0);
    let mut acc = 0.0;
    for s in &sizes {
        acc += s * scale;
        cum.push(acc);
    }
    Bin { pos, cum }
}

/// The medium (Python's `Barkhausen`).
#[derive(Debug)]
pub struct Medium {
    pub el: ir::Barkhausen,
    core: MagneticCore,
    state: Option<CoreState>,
    dev0: f64,
    lp: f64,
    lp2: f64,
    k_lp: f64,
    k_hp: f64,
    bins: HashMap<i64, Bin>,
}

impl Medium {
    pub fn new(el: &ir::Barkhausen, fs: f64) -> Medium {
        let dt = 1.0 / fs;
        let core = MagneticCore::new(&ir::MagneticCore {
            name: el.name.clone(),
            ms_a_per_m: el.ms_a_per_m,
            a_a_per_m: el.a_a_per_m,
            k_a_per_m: el.k_a_per_m,
            c: el.c,
            alpha: el.alpha,
            path_m: el.path_m,
        });
        Medium {
            el: el.clone(),
            core,
            state: None,
            dev0: 0.0,
            lp: 0.0,
            lp2: 0.0,
            k_lp: 1.0 - (-2.0 * PI * el.avalanche_hz * dt).exp(),
            k_hp: 1.0 - (-2.0 * PI * el.highpass_hz * dt).exp(),
            bins: HashMap::new(),
        }
    }

    fn s_max(&self) -> f64 {
        self.el.s_unit * self.el.stress
    }

    fn deviation(&mut self, m_irr: f64) -> f64 {
        let w = self.el.bin_factor * self.s_max();
        let j = (m_irr / w).floor() as i64;
        let (seed, s_min, s_max, tau) = (
            self.el.seed as u64,
            self.el.s_min,
            self.s_max(),
            self.el.tau,
        );
        let name = &self.el.name;
        let b = self
            .bins
            .entry(j)
            .or_insert_with(|| make_bin(seed, name, j, s_min, s_max, tau, w));
        let r = m_irr - j as f64 * w;
        let i = b.pos.partition_point(|&p| p < r);
        b.cum[i] - r
    }

    /// The sensed core voltage after a step; the output for the next. The core's state comes
    /// from replaying the sensed B through the medium's own copy of its model: the fallback
    /// where the circuit has no core device (a linear-core build); the engine hands a core's
    /// accepted state to [`Medium::push_state`] instead.
    pub fn push(&mut self, v_core: f64) -> f64 {
        if self.el.stress == 0.0 {
            return 0.0;
        }
        let b = v_core * TESLA_PER_V;
        let st = match self.state {
            Some(s) => s,
            None => {
                let (h, _) = self.core.h_of_b(b, &CoreState::DEMAGNETIZED);
                CoreState { b, h, delta: 1.0 }
            }
        };
        let (h, _) = self.core.h_of_b(b, &st);
        let delta = if b == st.b {
            st.delta
        } else if b > st.b {
            1.0
        } else {
            -1.0
        };
        self.push_state(b, h, delta)
    }

    /// The core's accepted state after a step (B in T, H in A/m, B's direction); the output
    /// for the next.
    pub fn push_state(&mut self, b: f64, h: f64, delta: f64) -> f64 {
        if self.el.stress == 0.0 {
            return 0.0;
        }
        let first = self.state.is_none();
        self.state = Some(CoreState { b, h, delta });
        let slope = self.core.dh_db(b, h, delta);
        let el = &self.el;
        let m = b / MU0 - h;
        let man = el.ms_a_per_m * langevin((h + el.alpha * m) / el.a_a_per_m);
        let m_irr = (m - el.c * man) / (1.0 - el.c) / el.ms_a_per_m;
        let dev = self.deviation(m_irr);
        if first {
            self.dev0 = dev;
            self.lp = 0.0;
            self.lp2 = 0.0;
        }
        let x = dev - self.dev0;
        self.lp += (x - self.lp) * self.k_lp;
        self.lp2 += (self.lp - self.lp2) * self.k_hp;
        let dm = self.lp - self.lp2;
        let el = &self.el;
        let current = el.path_m * slope * MU0 * el.ms_a_per_m * dm;
        current * el.out_v_per_a
    }

    /// A new STRESS plays on (the same barcode, scaled; off stops the replay, on again
    /// restarts it); any other change is another core.
    pub fn update(&mut self, el: &ir::Barkhausen) -> Result<(), String> {
        let same = ir::Barkhausen {
            stress: self.el.stress,
            ..el.clone()
        };
        if same != self.el {
            return Err("a core's Barkhausen medium changed".into());
        }
        if el.stress != self.el.stress {
            self.bins.clear();
            if el.stress == 0.0 {
                self.state = None;
            }
            self.el.stress = el.stress;
        }
        Ok(())
    }
}
