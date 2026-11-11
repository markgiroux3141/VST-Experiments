//! Granular carbon pressed by a force (a carbon button): a compiled port of
//! `varimu/devices/carbon.py` (its docstring has the model).
//!
//! Pins (a, b, f, ref), three ports relative to ref: the carbon's current G(F) (V(a) - V(b))
//! into a and out of b, F = V(f, ref) newtons (1 V = 1 N); no current into f.
//! G(F) = G_open + G0 (F_s / F0)^n, F_s = s ln(1 + exp(F / s)).

use super::Device;
use crate::ir;

/// [`Device::shunt`] of the two carbon ports: a loose button's G_open is all that holds a
/// node between it and a coil; the geometric middle of loose (1e-6 S) and pressed (~1 S).
pub const CARBON_SHUNT: f64 = 1e-3;

#[derive(Debug, Clone)]
pub struct Carbon {
    g0: f64,
    f0: f64,
    n: f64,
    g_open: f64,
    s: f64,
}

impl Carbon {
    pub fn new(m: &ir::Carbon) -> Carbon {
        Carbon {
            g0: m.g0_s,
            f0: m.f0_n,
            n: m.exponent,
            g_open: m.g_open_s,
            s: m.soft_n,
        }
    }

    /// The conductance and its derivative at force `f`, as carbon.py's `g`.
    fn g(&self, f: f64) -> (f64, f64) {
        let z = f / self.s;
        // numpy's logaddexp(0, z): max(z, 0) + ln(1 + exp(-|z|)).
        let fs = self.s * (z.max(0.0) + (-z.abs()).exp().ln_1p());
        let sig = 0.5 * (1.0 + (0.5 * z).tanh());
        let ratio = fs / self.f0;
        let g = self.g_open + self.g0 * ratio.powf(self.n);
        let dg = self.g0 * self.n * ratio.powf(self.n - 1.0) / self.f0 * sig;
        (g, dg)
    }
}

impl Device for Carbon {
    fn ports(&self) -> usize {
        3
    }

    fn eval(&self, v: &[f64], i: &mut [f64], g: &mut [f64]) {
        let (gc, dg) = self.g(v[2]);
        let d = v[0] - v[1];
        i[0] = gc * d;
        i[1] = -gc * d;
        i[2] = 0.0;
        g.fill(0.0);
        g[0] = gc;
        g[1] = -gc;
        g[2] = dg * d;
        g[3] = -gc;
        g[4] = gc;
        g[5] = -dg * d;
    }

    fn shunt(&self, port: usize) -> f64 {
        if port < 2 { CARBON_SHUNT } else { 0.0 }
    }
}
