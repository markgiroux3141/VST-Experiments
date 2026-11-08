//! A switch contact worked by a control voltage (a key's springs and bus bars): a compiled
//! port of `varimu/devices/contact.py` (its docstring has the model).
//!
//! Pins (a, b, c, ref), three ports relative to ref: the contact's current g (V(a) - V(b))
//! into a and out of b, g from the control V(c, ref) along a smoothstep in ln g; no current
//! into c.

use super::Device;
use crate::ir;

/// [`Device::shunt`] of the two contact ports: a node between two contacts in series (a key's
/// spring 1 and the sustaining cam) has nothing else on it, so DK's step matrix needs the
/// conductance there; the geometric middle of an open (1e-12 S) and a closed (1 S) contact.
pub const CONTACT_SHUNT: f64 = 1e-6;

#[derive(Debug, Clone)]
pub struct Contact {
    lo: f64,
    hi: f64,
    v_open: f64,
    span: f64,
}

impl Contact {
    pub fn new(m: &ir::Contact) -> Contact {
        Contact {
            lo: -m.r_off_ohm.ln(),
            hi: -m.r_on_ohm.ln(),
            v_open: m.v_open_v,
            span: m.v_closed_v - m.v_open_v,
        }
    }

    /// The conductance and its derivative at control voltage `v`, as contact.py's `g`.
    fn g(&self, v: f64) -> (f64, f64) {
        let x = ((v - self.v_open) / self.span).clamp(0.0, 1.0);
        let s = x * x * (3.0 - 2.0 * x);
        let g = (self.lo + (self.hi - self.lo) * s).exp();
        let dg = g * (self.hi - self.lo) * 6.0 * x * (1.0 - x) / self.span;
        (g, dg)
    }
}

impl Device for Contact {
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
        if port < 2 { CONTACT_SHUNT } else { 0.0 }
    }
}
