//! Triode: Koren plate current (one section, or N variable-mu sections) plus
//! optional grid current. Mirrors `varimu/devices/triode.py`.
//!
//! Koren (1996), per section with amplification factor mu:
//!
//! ```text
//! E1 = (Vp / Kp) * softplus(Kp * (1/mu + Vg / sqrt(Kvb + Vp^2)))
//! Ip = (2 / Kg1) * max(E1, 0)^Ex
//! ```
//!
//! A variable-mu triode is N such sections in parallel, section i carrying a
//! share `w_i` of the cathode, i.e. `Kg1 / w_i`. Grid current is a Child-law
//! diode above the contact potential with a softplus knee:
//! `Ig = perveance * (s * softplus((Vg - contact) / s))^1.5`.
//!
//! Ports: 0 = plate, 1 = grid (both relative to the cathode).

use super::{Device, sigmoid, softplus};
use crate::ir;

#[derive(Debug, Clone)]
struct Section {
    inv_mu: f64,
    /// 2 / Kg1 of the section.
    scale: f64,
}

#[derive(Debug, Clone)]
pub struct Triode {
    sections: Vec<Section>,
    ex: f64,
    kp: f64,
    kvb: f64,
    grid: Option<ir::GridCurrent>,
}

impl Triode {
    pub fn new(m: &ir::Triode) -> Triode {
        // Python: KorenTriode(mu, ex, kg1 / w, ...), whose ip() uses 1 / mu and 2.0 / kg1.
        let section = |mu: f64, kg1: f64| Section {
            inv_mu: 1.0 / mu,
            scale: 2.0 / kg1,
        };
        let (sections, ex, kp, kvb) = match &m.plate {
            ir::PlateModel::Koren(k) => (vec![section(k.mu, k.kg1)], k.ex, k.kp, k.kvb),
            ir::PlateModel::VariMu(v) => (
                v.mus
                    .iter()
                    .zip(&v.weights)
                    .map(|(&mu, &w)| section(mu, v.kg1 / w))
                    .collect(),
                v.ex,
                v.kp,
                v.kvb,
            ),
        };
        Triode {
            sections,
            ex,
            kp,
            kvb,
            grid: m.grid.clone(),
        }
    }

    /// Plate current and its derivatives (d/dVg, d/dVp).
    pub fn plate(&self, vg: f64, vp: f64) -> (f64, f64, f64) {
        let s = (self.kvb + vp * vp).sqrt();
        let (mut ip, mut d_vg, mut d_vp) = (0.0, 0.0, 0.0);
        for sec in &self.sections {
            let a = self.kp * (sec.inv_mu + vg / s);
            let sp = softplus(a);
            let e1 = vp / self.kp * sp;
            if e1 > 0.0 {
                let i = sec.scale * e1.powf(self.ex);
                let di_de1 = self.ex * i / e1;
                let sg = sigmoid(a);
                ip += i;
                d_vg += di_de1 * vp * sg / s;
                d_vp += di_de1 * (sp / self.kp - vp * vp * vg * sg / (s * s * s));
            }
        }
        (ip, d_vg, d_vp)
    }

    /// Grid current and d/dVg (zero without a grid-current model).
    pub fn grid(&self, vg: f64) -> (f64, f64) {
        match &self.grid {
            None => (0.0, 0.0),
            Some(g) => {
                let t = (vg - g.contact_v) / g.smooth_v;
                let x = g.smooth_v * softplus(t);
                let ig = g.perveance * x.powf(1.5);
                (ig, 1.5 * g.perveance * x.sqrt() * sigmoid(t))
            }
        }
    }
}

impl Device for Triode {
    fn ports(&self) -> usize {
        2
    }

    fn eval(&self, v: &[f64], i: &mut [f64], g: &mut [f64]) {
        let (vp, vg) = (v[0], v[1]);
        let (ip, dp_vg, dp_vp) = self.plate(vg, vp);
        let (ig, dg_vg) = self.grid(vg);
        i[0] = ip;
        i[1] = ig;
        g[0] = dp_vp;
        g[1] = dp_vg;
        g[2] = 0.0;
        g[3] = dg_vg;
    }
}
