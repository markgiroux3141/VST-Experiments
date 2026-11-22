//! A carbon arc: a compiled port of `varimu/devices/arc.py` (its docstring has the physics:
//! Mayr's arc on Ayrton's static law, and the sources).
//!
//! Pins (a, s, w, b), three ports relative to b: the arc's voltage, ln(g / 1 S) (1 V = 1
//! neper; the circuit's 1 F capacitor from s to b integrates the port's current, -d ln g /
//! dt), and the power readout (the arc's power out of w, 1 A = 1 W; nothing depends on its
//! voltage). The model is stateless: the conductance's memory is a node voltage.

use super::Device;
use crate::ir;

/// |i| smoothed as sqrt(i^2 + I_SMOOTH_A^2) (numerics), as arc.py's.
pub const I_SMOOTH_A: f64 = 1e-3;
/// The strike ramps in over this many volts above `v_strike_v` (numerics), as arc.py's.
pub const STRIKE_RAMP_V: f64 = 5.0;
/// d ln g / dt per neper past the floor or the cap (numerics), as arc.py's.
pub const G_EXT_PER_S: f64 = 1e7;
/// Newton step limits (numerics only): see [`Arc::limit`].
pub const LIMIT_STEP_NP: f64 = 1.0;
pub const LIMIT_STEP_V: f64 = 10.0;

#[derive(Debug, Clone)]
pub struct Arc {
    /// Ayrton's a + b l (V) and c + d l (W) at the instance's gap.
    pa: f64,
    pc: f64,
    tau: f64,
    v_strike: f64,
    ratio_max: f64,
    lo: f64,
    hi: f64,
}

impl Arc {
    pub fn new(m: &ir::Arc) -> Arc {
        Arc {
            pa: m.a_v + m.b_v_mm * m.gap_mm,
            pc: m.c_w + m.d_w_mm * m.gap_mm,
            tau: m.tau_s,
            v_strike: m.v_strike_v,
            ratio_max: m.ratio_max,
            lo: m.g_floor_s.ln(),
            hi: m.ln_g_max,
        }
    }
}

impl Device for Arc {
    fn ports(&self) -> usize {
        3
    }

    fn eval(&self, v: &[f64], i: &mut [f64], g: &mut [f64]) {
        let (va, u) = (v[0], v[1]);
        let x = u.max(self.lo).min(self.hi);
        let inside = u >= self.lo && u <= self.hi;
        let gg = x.exp();
        let ia = gg * va;
        let ai = (ia * ia + I_SMOOTH_A * I_SMOOTH_A).sqrt();
        let loss = self.pa * ai + self.pc;
        let p = ia * va;
        let ratio = p / loss;
        let dl = self.pa * (ia / ai);
        let dr_dv = (2.0 * gg * va * loss - p * dl * gg) / (loss * loss);
        let dr_du = if inside {
            (p * loss - p * dl * ia) / (loss * loss)
        } else {
            0.0
        };
        let av = va.abs();
        let ramp = ((av - self.v_strike) / STRIKE_RAMP_V).clamp(0.0, 1.0);
        let strike = self.ratio_max * ramp;
        let ds_dv = if av > self.v_strike && av < self.v_strike + STRIKE_RAMP_V {
            self.ratio_max * va.signum() / STRIKE_RAMP_V
        } else {
            0.0
        };
        let (mut r, mut r_dv, mut r_du) = if strike > ratio {
            (strike, ds_dv, 0.0)
        } else {
            (ratio, dr_dv, dr_du)
        };
        if r > self.ratio_max {
            (r, r_dv, r_du) = (self.ratio_max, 0.0, 0.0);
        }
        i[0] = ia;
        i[1] = -(r - 1.0) / self.tau + G_EXT_PER_S * (u - x);
        i[2] = -p;
        g[0] = gg;
        g[1] = if inside { ia } else { 0.0 };
        g[2] = 0.0;
        g[3] = -r_dv / self.tau;
        g[4] = if inside {
            -r_du / self.tau
        } else {
            G_EXT_PER_S
        };
        g[5] = 0.0;
        g[6] = -2.0 * gg * va;
        g[7] = if inside { -p } else { 0.0 };
        g[8] = 0.0;
    }

    /// The state port is its node's only DC path (the 1 F capacitor is open at DC): its
    /// conductance is ~1 / tau (3e4) while it burns, G_EXT_PER_S past the floor. The arc:
    /// 1e-4 (the floor) to ~7 S.
    fn shunt(&self, port: usize) -> f64 {
        match port {
            0 => 1e-3,
            1 => 1e4,
            _ => 0.0,
        }
    }

    /// Newton step limiting (numerics only): the conductance is exponential in the state, so
    /// the state moves at most [`LIMIT_STEP_NP`] nepers per iteration and stays within a
    /// neper of its range; the arc's voltage at most [`LIMIT_STEP_V`] or half its value.
    fn limit(&self, v: &mut [f64], v_old: &[f64]) -> bool {
        let (want_v, want_u) = (v[0], v[1]);
        let dv = LIMIT_STEP_V.max(0.5 * v_old[0].abs());
        v[0] = want_v.clamp(v_old[0] - dv, v_old[0] + dv);
        let u = want_u
            .clamp(v_old[1] - LIMIT_STEP_NP, v_old[1] + LIMIT_STEP_NP)
            .clamp((self.lo - 1.0).min(v_old[1]), (self.hi + 1.0).max(v_old[1]));
        v[1] = u;
        v[0] != want_v || u != want_u
    }
}
