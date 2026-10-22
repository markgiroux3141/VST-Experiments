//! Jiles-Atherton magnetic core (`varimu/devices/core.py`, the reference;
//! its docstring has the model and how it sits in a circuit).
//!
//! One port: the core node (its voltage is B / [`TESLA_PER_V`]) to ground;
//! the port current is the magnetomotive force `path * H(B)`. H(B) is
//! integrated along B from the last accepted point with the direction
//! `sign(B - b0)` (rate-independent: within a step the device is a function
//! of B alone), in RK4 substeps (at most [`DB_MAX`] of B and [`DH_REL`]
//! `(a + |H|)` of H, halved until the end slope is within [`SLOPE_TOL`] of
//! the start's); [`Device::accept`] moves the state on. Same order of
//! operations as Python.

use super::Device;
use crate::ir::{self, TESLA_PER_V};

/// Vacuum permeability (H/m, CODATA 2018), as in Python.
pub const MU0: f64 = 1.25663706212e-6;
/// Longest RK4 substep along B (T).
pub const DB_MAX: f64 = 1e-3;
/// ... and its change of H at most this times `a + |H|` (stability deep in
/// saturation of high-permeability materials).
pub const DH_REL: f64 = 0.05;
/// ... and halved until the slope at its end is within this of its start.
pub const SLOPE_TOL: f64 = 0.25;
/// The shortest substep (T), a guard.
pub const DB_MIN: f64 = 1e-12;
/// A guard: a transient step takes one substep or a few.
pub const MAX_SUBSTEPS: usize = 1_000_000;
/// Floor of `1 - alpha chi_e` (see Python's docstring).
pub const DEN_FLOOR: f64 = 0.05;
/// Newton step limit on the core node (V: 50 mT), see [`Device::limit`].
pub const LIMIT_V: f64 = 50.0;
/// The part of its offset an iterate crossing the state's B keeps.
pub const CROSS_DAMPING: f64 = 0.1;

/// The Langevin function `coth x - 1/x` (series near 0).
pub fn langevin(x: f64) -> f64 {
    if x.abs() < 1e-2 {
        let x2 = x * x;
        x * (1.0 / 3.0 - x2 * (1.0 / 45.0 - x2 * (2.0 / 945.0)))
    } else {
        1.0 / x.tanh() - 1.0 / x
    }
}

/// Its derivative `1/x^2 - 1/sinh^2 x` (series near 0).
pub fn dlangevin(x: f64) -> f64 {
    if x.abs() < 1e-2 {
        let x2 = x * x;
        1.0 / 3.0 - x2 * (1.0 / 15.0 - x2 * (2.0 / 189.0))
    } else if x.abs() > 300.0 {
        1.0 / (x * x)
    } else {
        let s = x.sinh();
        1.0 / (x * x) - 1.0 / (s * s)
    }
}

/// The last accepted point: B (T), H (A/m), direction of B (+-1).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct CoreState {
    pub b: f64,
    pub h: f64,
    pub delta: f64,
}

impl CoreState {
    pub const DEMAGNETIZED: CoreState = CoreState {
        b: 0.0,
        h: 0.0,
        delta: 1.0,
    };
}

#[derive(Debug, Clone)]
pub struct MagneticCore {
    ms: f64,
    a: f64,
    k: f64,
    c: f64,
    alpha: f64,
    path: f64,
    pub state: CoreState,
}

impl MagneticCore {
    pub fn new(m: &ir::MagneticCore) -> MagneticCore {
        MagneticCore {
            ms: m.ms_a_per_m,
            a: m.a_a_per_m,
            k: m.k_a_per_m,
            c: m.c,
            alpha: m.alpha,
            path: m.path_m,
            state: CoreState::DEMAGNETIZED,
        }
    }

    /// dM/dH at (H, M) for direction `delta`.
    pub fn susceptibility(&self, h: f64, m: f64, delta: f64) -> f64 {
        let (ms, a, k, c, alpha) = (self.ms, self.a, self.k, self.c, self.alpha);
        let x = (h + alpha * m) / a;
        let d = ms * langevin(x) - m;
        let mut chi_e = c * (ms / a) * dlangevin(x);
        if delta * d > 0.0 {
            chi_e += d.abs() / k;
        }
        chi_e / (1.0 - alpha * chi_e).max(DEN_FLOOR)
    }

    fn dh_db(&self, b: f64, h: f64, delta: f64) -> f64 {
        let chi = self.susceptibility(h, b / MU0 - h, delta);
        1.0 / (MU0 * (1.0 + chi))
    }

    /// H at flux density `b` on the path from `state`, and dH/dB there.
    pub fn h_of_b(&self, b: f64, state: &CoreState) -> (f64, f64) {
        let (b0, mut h) = (state.b, state.h);
        if b == b0 {
            return (h, self.dh_db(b, h, state.delta));
        }
        let delta = if b > b0 { 1.0 } else { -1.0 };
        let (mut bj, mut size) = (b0, DB_MAX);
        for _ in 0..MAX_SUBSTEPS {
            let rest = b - bj;
            let k1 = self.dh_db(bj, h, delta);
            size = size.min(DB_MAX).min(DH_REL * (self.a + h.abs()) / k1);
            let (step, last, k2, k3, k4) = loop {
                let last = size >= rest.abs();
                let step = if last { rest } else { size.copysign(rest) };
                let k2 = self.dh_db(bj + 0.5 * step, h + 0.5 * step * k1, delta);
                let k3 = self.dh_db(bj + 0.5 * step, h + 0.5 * step * k2, delta);
                let k4 = self.dh_db(bj + step, h + step * k3, delta);
                if (k4 - k1).abs() <= SLOPE_TOL * k1.max(k4) || step.abs() <= DB_MIN {
                    break (step, last, k2, k3, k4);
                }
                size = 0.5 * step.abs();
            };
            h += step / 6.0 * (k1 + 2.0 * k2 + 2.0 * k3 + k4);
            if last {
                break;
            }
            bj += step;
            size *= 2.0;
        }
        (h, self.dh_db(b, h, delta))
    }

    /// The state after accepting the point `b`.
    pub fn advance(&self, b: f64, state: &CoreState) -> CoreState {
        let (h, _) = self.h_of_b(b, state);
        let delta = if b == state.b {
            state.delta
        } else if b > state.b {
            1.0
        } else {
            -1.0
        };
        CoreState { b, h, delta }
    }

    /// Port conductance of the linear-limit core (`linear_conductance` in Python).
    pub fn linear_conductance(&self) -> f64 {
        self.path * TESLA_PER_V / (MU0 * (1.0 + self.susceptibility(0.0, 0.0, 1.0)))
    }
}

impl Device for MagneticCore {
    fn ports(&self) -> usize {
        1
    }

    fn eval(&self, v: &[f64], i: &mut [f64], g: &mut [f64]) {
        let (h, dh) = self.h_of_b(v[0] * TESLA_PER_V, &self.state);
        i[0] = self.path * h;
        g[0] = self.path * dh * TESLA_PER_V;
    }

    /// At most [`LIMIT_V`] of B per Newton iteration. From a steep (high
    /// permeability) linearization a DC operating point in saturation would
    /// otherwise overshoot by orders of magnitude and cycle; a transient step
    /// moves B by far less than this.
    ///
    /// And an iterate that crosses the state's B (where the direction of the
    /// path switches) keeps only [`CROSS_DAMPING`] of its offset from it.
    /// From the demagnetized state a low-reversibility material follows a
    /// Rayleigh-like H ~ sqrt(B) beyond a fraction of a microtesla, on which
    /// plain Newton maps x to -x for ever (measured: mumetall, a DC point
    /// with no flux cycled at +-1.08 uT).
    fn limit(&self, v: &mut [f64], v_old: &[f64]) -> bool {
        let b0 = self.state.b / TESLA_PER_V;
        if (v[0] - b0) * (v_old[0] - b0) < 0.0 {
            v[0] = b0 + CROSS_DAMPING * (v[0] - b0);
            return true;
        }
        let d = v[0] - v_old[0];
        if d.abs() > LIMIT_V {
            v[0] = v_old[0] + LIMIT_V.copysign(d);
            return true;
        }
        false
    }

    /// The core node can hang on the core alone (no gap, no eddy loss): lend
    /// the demagnetized slope to the step matrix, within the port's range
    /// (saturation only raises it).
    fn shunt(&self, _port: usize) -> f64 {
        self.linear_conductance()
    }

    fn accept(&mut self, v: &[f64]) {
        self.state = self.advance(v[0] * TESLA_PER_V, &self.state.clone());
    }

    fn has_state(&self) -> bool {
        true
    }

    fn state(&self) -> Vec<f64> {
        vec![self.state.b, self.state.h, self.state.delta]
    }

    fn set_state(&mut self, s: &[f64]) {
        self.state = CoreState {
            b: s[0],
            h: s[1],
            delta: s[2],
        };
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn core() -> MagneticCore {
        MagneticCore::new(&ir::MagneticCore {
            name: "t".into(),
            ms_a_per_m: 1.51913e6,
            a_a_per_m: 13.0,
            k_a_per_m: 24.0,
            c: 0.8,
            alpha: 1e-5,
            path_m: 0.1,
        })
    }

    #[test]
    fn langevin_series_meets_the_closed_form() {
        // Just inside the series region, against the closed forms (whose
        // cancellation leaves ~1e-12 there).
        for x in [9.99e-3, 5e-3, -9.99e-3] {
            let closed = 1.0 / f64::tanh(x) - 1.0 / x;
            assert!((langevin(x) - closed).abs() < 1e-12, "{x}");
            let s = x.sinh();
            let dclosed = 1.0 / (x * x) - 1.0 / (s * s);
            assert!((dlangevin(x) - dclosed).abs() < 1e-10, "{x}");
        }
    }

    #[test]
    fn jacobian_matches_finite_differences_and_the_loop_has_width() {
        let mut c = core();
        // up to 1.2 T and back to 0: on the way down H is lower (hysteresis)
        let mut up = vec![];
        for j in 0..=120 {
            let v = j as f64 * 10.0; // 10 mT steps
            let (mut i, mut g) = ([0.0], [0.0]);
            c.eval(&[v], &mut i, &mut g);
            let d = 1e-4;
            let (mut ip, mut im, mut gg) = ([0.0], [0.0], [0.0]);
            c.eval(&[v + d], &mut ip, &mut gg);
            c.eval(&[v - d], &mut im, &mut gg);
            if j > 0 {
                let fd = (ip[0] - im[0]) / (2.0 * d);
                assert!(
                    (g[0] - fd).abs() <= 1e-5 * fd.abs(),
                    "{v}: {} vs {fd}",
                    g[0]
                );
            }
            c.accept(&[v]);
            up.push(i[0]);
        }
        for j in (0..120).rev() {
            let v = j as f64 * 10.0;
            let (mut i, mut g) = ([0.0], [0.0]);
            c.eval(&[v], &mut i, &mut g);
            c.accept(&[v]);
            assert!(i[0] < up[j], "{v} mT: down {} up {}", i[0], up[j]);
        }
    }
}
