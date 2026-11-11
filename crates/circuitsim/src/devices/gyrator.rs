//! A gyrator whose conductance follows a sensed voltage (a moving-coil motor's force factor
//! set by its field current): a compiled port of `varimu/devices/gyrator.py` (its docstring
//! has the model).
//!
//! Pins (a, b, f, ref), three ports relative to ref: i_a = g V(b, ref) into a,
//! i_b = -g V(a, ref) into b, none into f; g = g_per_v V(f, ref).

use super::Device;
use crate::ir;

#[derive(Debug, Clone)]
pub struct Gyrator {
    k: f64,
}

impl Gyrator {
    pub fn new(m: &ir::Gyrator) -> Gyrator {
        Gyrator { k: m.g_per_v }
    }
}

impl Device for Gyrator {
    fn ports(&self) -> usize {
        3
    }

    fn eval(&self, v: &[f64], i: &mut [f64], g: &mut [f64]) {
        let gy = self.k * v[2];
        i[0] = gy * v[1];
        i[1] = -gy * v[0];
        i[2] = 0.0;
        g.fill(0.0);
        g[1] = gy;
        g[2] = self.k * v[1];
        g[3] = -gy;
        g[5] = -self.k * v[0];
    }
}
