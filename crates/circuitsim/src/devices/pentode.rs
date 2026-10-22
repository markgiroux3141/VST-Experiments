//! Koren pentode / beam-power tube. Mirrors `varimu/devices/pentode.py`:
//!
//! ```text
//! E1  = (Vg2 / Kp) * softplus(Kp * (1/mu + Vg1 / Vg2)),   Vg2 floored at 1 mV
//! Ip  = (2 / Kg1) * max(E1, 0)^Ex * atan(Vp / Kvb)
//! Ig2 = max(Vg1 + Vg2 / mu, 0)^1.5 / Kg2
//! ```
//!
//! The control grid conducts with the triode's grid-current law
//! (`GridCurrent`), if the model has one. Ports: 0 = plate, 1 = screen,
//! 2 = control grid (all relative to the cathode).

use super::triode::grid_current;
use super::{Device, sigmoid, softplus};
use crate::ir;

/// Python's `_VG2_MIN`: avoids division by zero when the screen is at 0 V.
const VG2_MIN: f64 = 1e-3;

#[derive(Debug, Clone)]
pub struct Pentode {
    inv_mu: f64,
    mu: f64,
    ex: f64,
    /// 2 / Kg1
    scale: f64,
    kg2: f64,
    kp: f64,
    kvb: f64,
    grid: Option<ir::GridCurrent>,
}

impl Pentode {
    pub fn new(m: &ir::Pentode) -> Pentode {
        let k = &m.model;
        Pentode {
            inv_mu: 1.0 / k.mu,
            mu: k.mu,
            ex: k.ex,
            scale: 2.0 / k.kg1,
            kg2: k.kg2,
            kp: k.kp,
            kvb: k.kvb,
            grid: m.grid.clone(),
        }
    }
}

impl Device for Pentode {
    fn ports(&self) -> usize {
        3
    }

    fn eval(&self, v: &[f64], i: &mut [f64], g: &mut [f64]) {
        let (vp, vg2, vg1) = (v[0], v[1], v[2]);
        g.fill(0.0);

        // Plate.
        let (g2, dg2) = if vg2 > VG2_MIN {
            (vg2, 1.0)
        } else {
            (VG2_MIN, 0.0)
        };
        let a = self.kp * (self.inv_mu + vg1 / g2);
        let sp = softplus(a);
        let e1 = g2 / self.kp * sp;
        let atan = (vp / self.kvb).atan();
        if e1 > 0.0 {
            let p = self.scale * e1.powf(self.ex);
            let dp_de1 = self.ex * p / e1;
            let sg = sigmoid(a);
            i[0] = p * atan;
            g[0] = p / self.kvb / (1.0 + (vp / self.kvb).powi(2));
            g[1] = dp_de1 * atan * dg2 * (sp / self.kp - sg * vg1 / g2);
            g[2] = dp_de1 * atan * sg;
        } else {
            i[0] = 0.0;
        }

        // Screen.
        let x = vg1 + vg2 / self.mu;
        if x > 0.0 {
            i[1] = x.powf(1.5) / self.kg2;
            let d = 1.5 * x.sqrt() / self.kg2;
            g[3 + 1] = d / self.mu;
            g[3 + 2] = d;
        } else {
            i[1] = 0.0;
        }

        // Control grid.
        let (ig, dig) = self
            .grid
            .as_ref()
            .map_or((0.0, 0.0), |gc| grid_current(gc, vg1));
        i[2] = ig;
        g[2 * 3 + 2] = dig;
    }
}
