//! An LED / photoresistor optocoupler (a Vactrol): a compiled port of
//! `varimu/devices/opto.py` (its docstring has the physics and the sheet it is fitted to).
//!
//! Pins (la, lk, s, ra, rb), four ports relative to rb: the LED from la to lk, the cell's
//! photoconductance on s (`s_unit_s` siemens per volt; the circuit's 1 F capacitor from s to
//! rb integrates the port's current, -dg/dt / s_unit), the cell from ra to rb. The model is
//! stateless: its memory is the node s.

use super::Device;
use super::diode::{DIODE_SHUNT, pnjlim};
use crate::ir;

/// kT/q at 25 C, as opto.py's.
pub const VT_V: f64 = 0.025693;
/// The LED's exponential continues as its tangent above this, as opto.py's.
pub const V_LIN_V: f64 = 2.5;
/// [`Device::shunt`] of the state port: within its conductance, 1 / tau0 (~200) and up.
pub const STATE_SHUNT: f64 = 1.0;
/// [`Device::shunt`] of the cell: between its dark (2e-8 S) and bright (~5e-3 S) ends.
pub const CELL_SHUNT: f64 = 1e-6;

#[derive(Debug, Clone)]
pub struct Optocoupler {
    is: f64,
    nvt: f64,
    vcrit: f64,
    i_eta: f64,
    generation: f64,
    tau0: f64,
    kappa: f64,
    g_dark: f64,
    s_unit: f64,
}

impl Optocoupler {
    pub fn new(m: &ir::Optocoupler) -> Optocoupler {
        let nvt = m.led_n * VT_V;
        Optocoupler {
            is: m.led_is_a,
            nvt,
            vcrit: nvt * (nvt / (std::f64::consts::SQRT_2 * m.led_is_a)).ln(),
            i_eta: m.i_eta_a,
            generation: m.gen_s_per_s_a,
            tau0: m.tau0_s,
            kappa: m.kappa_s_s,
            g_dark: m.g_dark_s,
            s_unit: m.s_unit_s,
        }
    }

    /// The LED's current and its derivative at junction voltage `v`.
    fn led(&self, v: f64) -> (f64, f64) {
        let vc = v.min(V_LIN_V);
        let e = (vc / self.nvt).exp();
        let i = self.is * (e - 1.0) + self.is * e / self.nvt * (v - vc);
        (i, self.is * e / self.nvt)
    }

    /// The light L and dL/dI.
    fn light(&self, i: f64) -> (f64, f64) {
        let ip = i.max(0.0);
        let den = ip + self.i_eta;
        (ip * ip / den, ip * (ip + 2.0 * self.i_eta) / (den * den))
    }
}

impl Device for Optocoupler {
    fn ports(&self) -> usize {
        4
    }

    fn eval(&self, v: &[f64], i: &mut [f64], g: &mut [f64]) {
        let (v0, v1, u, vr) = (v[0], v[1], v[2], v[3]);
        let (il, dil) = self.led(v0 - v1);
        let (lum, dlum) = self.light(il);
        let su = self.s_unit;
        let gc = u * su;
        let dgdt = self.generation * lum - gc / self.tau0 - gc * gc.abs() / self.kappa;
        let cond = self.g_dark + gc.max(0.0);
        i[0] = il;
        i[1] = -il;
        i[2] = -dgdt / su;
        i[3] = cond * vr;
        g.fill(0.0);
        g[0] = dil;
        g[1] = -dil;
        g[4] = -dil;
        g[5] = dil;
        let dgen = self.generation * dlum * dil / su;
        g[8] = -dgen;
        g[9] = dgen;
        g[10] = 1.0 / self.tau0 + 2.0 * gc.abs() / self.kappa;
        g[14] = if gc > 0.0 { su * vr } else { 0.0 };
        g[15] = cond;
    }

    /// The LED's junction voltage V(la) - V(lk) by SPICE's `pnjlim`, moving la only.
    fn limit(&self, v: &mut [f64], v_old: &[f64]) -> bool {
        let (vd, limited) = pnjlim(v[0] - v[1], v_old[0] - v_old[1], self.nvt, self.vcrit);
        if limited {
            v[0] = v[1] + vd;
        }
        limited
    }

    fn shunt(&self, port: usize) -> f64 {
        match port {
            2 => STATE_SHUNT,
            3 => CELL_SHUNT,
            _ => DIODE_SHUNT,
        }
    }
}
