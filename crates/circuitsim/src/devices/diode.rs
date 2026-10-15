//! Rectifiers. Mirrors `varimu/devices/diode.py`.
//!
//! - [`JunctionDiode`]: Shockley with series resistance (SPICE `D` with IS, N,
//!   RS). Like the Python reference, the series-resistance equation is solved
//!   exactly with the Lambert W function, so the device is two-terminal (no
//!   internal node): `I = nVt/Rs * W(a exp((V + Is Rs) / nVt)) - Is` with
//!   `a = Is Rs / nVt`, and `dI/dV = W / (Rs (1 + W))`.
//! - [`VacuumDiode`]: Child law with a softplus knee,
//!   `I = perveance * (s * softplus(V / s))^1.5`.
//!
//! Port 0: anode relative to cathode.

use super::{Device, sigmoid, softplus};
use crate::ir;

/// Thermal voltage kT/q at SPICE's TNOM = 27 C, with the CODATA constants
/// ngspice uses (Python: `VT_TNOM`).
pub const VT_TNOM: f64 = 1.38064852e-23 * 300.15 / 1.6021766208e-19;

#[derive(Debug, Clone)]
pub struct JunctionDiode {
    is_a: f64,
    rs_ohm: f64,
    nvt: f64,
    /// SPICE's critical voltage for junction limiting.
    vcrit: f64,
}

impl JunctionDiode {
    pub fn new(m: &ir::JunctionDiode) -> JunctionDiode {
        let nvt = m.n * VT_TNOM;
        JunctionDiode {
            is_a: m.is_a,
            rs_ohm: m.rs_ohm,
            nvt,
            vcrit: nvt * (nvt / (std::f64::consts::SQRT_2 * m.is_a)).ln(),
        }
    }

    /// Current and conductance at anode-cathode voltage `v`.
    pub fn current(&self, v: f64) -> (f64, f64) {
        let nvt = self.nvt;
        if self.rs_ohm == 0.0 {
            let i = self.is_a * (v / nvt).exp_m1();
            return (i, self.is_a / nvt * (v / nvt).exp());
        }
        let a = self.is_a * self.rs_ohm / nvt;
        let t = (v + self.is_a * self.rs_ohm) / nvt;
        let z = a * t.exp();
        let w = if z.is_finite() {
            lambert_w0(z)
        } else {
            wright_omega(a.ln() + t)
        };
        (
            nvt / self.rs_ohm * w - self.is_a,
            w / (self.rs_ohm * (1.0 + w)),
        )
    }
}

impl Device for JunctionDiode {
    fn ports(&self) -> usize {
        1
    }

    fn eval(&self, v: &[f64], i: &mut [f64], g: &mut [f64]) {
        (i[0], g[0]) = self.current(v[0]);
    }

    fn limit(&self, v: &mut [f64], v_old: &[f64]) -> bool {
        let (new, limited) = pnjlim(v[0], v_old[0], self.nvt, self.vcrit);
        v[0] = new;
        limited
    }
}

/// SPICE3's junction voltage limiting (`DEVpnjlim`, forward branch): above
/// the critical voltage, a step of more than 2 Vt follows the logarithm of
/// the exponential instead of its tangent.
pub fn pnjlim(vnew: f64, vold: f64, vt: f64, vcrit: f64) -> (f64, bool) {
    if vnew > vcrit && (vnew - vold).abs() > vt + vt {
        let v = if vold > 0.0 {
            let arg = 1.0 + (vnew - vold) / vt;
            if arg > 0.0 {
                vold + vt * arg.ln()
            } else {
                vcrit
            }
        } else {
            vt * (vnew / vt).ln()
        };
        (v, true)
    } else {
        (vnew, false)
    }
}

/// Principal branch of Lambert W for `z >= 0` (Halley iteration).
pub fn lambert_w0(z: f64) -> f64 {
    debug_assert!(z >= 0.0);
    if z == 0.0 {
        return 0.0;
    }
    let mut w = if z > std::f64::consts::E {
        let l = z.ln();
        l - l.ln()
    } else {
        z / (1.0 + z)
    };
    for _ in 0..50 {
        let ew = w.exp();
        let f = w * ew - z;
        let wp1 = w + 1.0;
        let dw = f / (ew * wp1 - (w + 2.0) * f / (2.0 * wp1));
        w -= dw;
        if dw.abs() <= 4.0 * f64::EPSILON * w.abs() {
            break;
        }
    }
    w
}

/// `W(exp(y))`, the Wright omega function: the `w` with `w + ln w = y`. For
/// arguments where `exp(y)` overflows (a diode driven far forward).
pub fn wright_omega(y: f64) -> f64 {
    let mut w = y - y.ln();
    for _ in 0..50 {
        // Newton on w + ln w - y.
        let dw = w * (w + w.ln() - y) / (1.0 + w);
        w -= dw;
        if dw.abs() <= 4.0 * f64::EPSILON * w.abs() {
            break;
        }
    }
    w
}

#[derive(Debug, Clone)]
pub struct VacuumDiode {
    perveance: f64,
    smooth_v: f64,
}

impl VacuumDiode {
    pub fn new(m: &ir::VacuumDiode) -> VacuumDiode {
        VacuumDiode {
            perveance: m.perveance,
            smooth_v: m.smooth_v,
        }
    }
}

impl Device for VacuumDiode {
    fn ports(&self) -> usize {
        1
    }

    fn eval(&self, v: &[f64], i: &mut [f64], g: &mut [f64]) {
        let t = v[0] / self.smooth_v;
        let x = self.smooth_v * softplus(t);
        i[0] = self.perveance * x.powf(1.5);
        g[0] = 1.5 * self.perveance * x.sqrt() * sigmoid(t);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lambert_w_solves_its_equation() {
        for z in [1e-300, 1e-20, 1e-5, 0.3, 1.0, 2.7, 3.0, 1e3, 1e100, 1e300] {
            let w = lambert_w0(z);
            assert!(
                ((w * w.exp() - z) / z).abs() < 1e-14,
                "z={z}: w={w}, w e^w={}",
                w * w.exp()
            );
        }
        for y in [10.0, 700.0, 1e4, 1e8] {
            let w = wright_omega(y);
            assert!(((w + w.ln() - y) / y).abs() < 1e-15, "y={y}");
        }
        // The two agree where both apply.
        let y: f64 = 600.0;
        assert!((wright_omega(y) / lambert_w0(y.exp()) - 1.0).abs() < 1e-15);
    }

    #[test]
    fn pnjlim_follows_spice() {
        let (vt, vcrit) = (0.04, 0.6);
        // Small steps and steps below vcrit pass.
        assert_eq!(pnjlim(0.65, 0.6, vt, vcrit), (0.65, false));
        assert_eq!(pnjlim(0.5, -5.0, vt, vcrit), (0.5, false));
        // A big forward step from a conducting point follows the log.
        let (v, lim) = pnjlim(2.0, 0.7, vt, vcrit);
        assert!(lim && (v - (0.7 + vt * (1.0 + 1.3 / vt).ln())).abs() < 1e-15);
        // From reverse bias: vt ln(vnew / vt).
        let (v, lim) = pnjlim(2.0, -1.0, vt, vcrit);
        assert!(lim && (v - vt * (2.0 / vt).ln()).abs() < 1e-15);
    }
}
