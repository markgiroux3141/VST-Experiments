//! A CdS photocell lit by a lamp's filament: a compiled port of
//! `varimu/devices/photocell.py` (its docstring has the physics and the sheet it is fitted to).
//!
//! Pins (t, tb, s, ra, rb), four ports relative to rb: t and tb sense the lamp's thermal node
//! and its reference pin (no current: V(t, tb) = T - T_amb), the cell's photoconductance on s
//! (`s_unit_s` siemens per volt; the circuit's 1 F capacitor from s to rb integrates the
//! port's current, -dg/dt / s_unit), the cell from ra to rb. The model is stateless: its
//! memory is the node s (and the lamp's thermal node it reads).

use super::Device;
use super::opto::{CELL_SHUNT, CELL_TOL_SCALE, STATE_SHUNT};
use crate::ir;

/// The second radiation constant h c / k (m K), as photocell.py's.
pub const C2_M_K: f64 = 1.438776877e-2;
/// CIE illuminant A: the tungsten source a cell's `lux` is given at, as photocell.py's.
pub const T_REF_K: f64 = 2856.0;
/// Below this the filament is dark, as photocell.py's.
pub const T_FLOOR_K: f64 = 100.0;

#[derive(Debug, Clone)]
pub struct Photocell {
    generation: f64,
    tau0: f64,
    kappa: f64,
    g_dark: f64,
    c_k: f64,
    t_amb: f64,
    lux: f64,
    s_unit: f64,
}

impl Photocell {
    pub fn new(m: &ir::Photocell) -> Photocell {
        Photocell {
            generation: m.gen_s_per_s_lux,
            tau0: m.tau0_s,
            kappa: m.kappa_s_s,
            g_dark: m.g_dark_s,
            c_k: C2_M_K / m.lambda_m,
            t_amb: m.t_amb_k,
            lux: m.lux,
            s_unit: m.s_unit_s,
        }
    }

    /// The illuminance E (lux) and dE/d(dT) at the lamp's thermal voltage `dt` = T - T_amb.
    fn illuminance(&self, dt: f64) -> (f64, f64) {
        let t = dt + self.t_amb;
        let tc = t.max(T_FLOOR_K);
        let e = self.lux * (self.c_k * (1.0 / T_REF_K - 1.0 / tc)).exp();
        let de = if t > T_FLOOR_K {
            e * self.c_k / (tc * tc)
        } else {
            0.0
        };
        (e, de)
    }
}

impl Device for Photocell {
    fn ports(&self) -> usize {
        4
    }

    fn eval(&self, v: &[f64], i: &mut [f64], g: &mut [f64]) {
        let (vt, vtb, u, vr) = (v[0], v[1], v[2], v[3]);
        let (e, de) = self.illuminance(vt - vtb);
        let su = self.s_unit;
        let gc = u * su;
        let dgdt = self.generation * e - gc / self.tau0 - gc * gc.abs() / self.kappa;
        let cond = self.g_dark + gc.max(0.0);
        i[0] = 0.0;
        i[1] = 0.0;
        i[2] = -dgdt / su;
        i[3] = cond * vr;
        g.fill(0.0);
        let dgen = self.generation * de / su;
        g[8] = -dgen;
        g[9] = dgen;
        g[10] = 1.0 / self.tau0 + 2.0 * gc.abs() / self.kappa;
        g[14] = if gc > 0.0 { su * vr } else { 0.0 };
        g[15] = cond;
    }

    fn tol_scale(&self, port: usize) -> f64 {
        match port {
            3 => CELL_TOL_SCALE,
            _ => 1.0,
        }
    }

    fn shunt(&self, port: usize) -> f64 {
        match port {
            2 => STATE_SHUNT,
            3 => CELL_SHUNT,
            // The sensing ports carry no current: nothing to shunt.
            _ => 0.0,
        }
    }
}
