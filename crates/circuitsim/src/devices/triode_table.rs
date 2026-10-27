//! A tabulated Koren triode, or a bank of them in parallel: the same model as
//! [`Triode`] (and [`super::Parallel`] of triodes), evaluated from a table
//! instead of section by section. Opt-in (`Options::tube_tables`, the fast
//! "draft" settings); the exact evaluation stays the default.
//!
//! Every Koren section's plate current factors exactly into a power of the
//! plate voltage and a function of one variable:
//!
//! ```text
//! E1 = (Vp / Kp) softplus(Kp (1/mu + u)),   u = Vg / sqrt(Kvb + Vp^2)
//! Ip = (2 / Kg1) E1^Ex = (Vp / Kp)^Ex * (2 / Kg1) softplus(Kp (1/mu + u))^Ex
//! ```
//!
//! so all sections sharing (Kp, Ex, Kvb), however many tubes they come from
//! (a variable-mu tube's 32, a bank of four such tubes: 128), sum to
//! `(Vp / Kp)^Ex Phi(u)`. `ln Phi` is tabulated on a uniform grid in u as a
//! cubic Hermite spline through its exact values and slopes; the evaluation is
//! one lookup, a `ln` and an `exp`, instead of four transcendentals per section.
//!
//! - Spacing: `0.05 / Kp` (a section's knee is ~1 / Kp wide in u): within ~1e-7
//!   of the exact current (`tests/devices.rs` measures it).
//! - Below the grid every section is in its exponential tail (Kp (1/mu + u) <
//!   -40), where `ln Phi` is linear with slope `Ex Kp` to double precision: the
//!   table extends exactly.
//! - Above it (u > [`U_HI`]: the grid far above the plate) the exact sections are
//!   evaluated, as at Vp <= 0 the current is zero (as in the exact model).
//!
//! Grid currents (one per tube) are evaluated exactly; identical ones once.

use super::triode::{Triode, grid_current};
use super::{Device, softplus};
use crate::fastmath;
use crate::ir;

/// Table spacing in u, times Kp.
const DU_KP: f64 = 0.05;
/// The table starts where every section's softplus argument is below this.
const TAIL_A: f64 = -40.0;
/// The table's upper end in u (Vg / sqrt(Kvb + Vp^2)); exact above.
pub const U_HI: f64 = 0.5;

/// Sections sharing (Kp, Ex, Kvb), tabulated.
#[derive(Debug, Clone)]
struct Group {
    kp: f64,
    ex: f64,
    kvb: f64,
    /// The exact sections: (1 / mu, 2 / Kg1), for points above the table.
    sections: Vec<(f64, f64)>,
    u_lo: f64,
    inv_du: f64,
    /// Per interval: the cubic in t = (u - u_j) / du, c0 + c1 t + c2 t^2 + c3 t^3.
    coef: Vec<[f64; 4]>,
}

/// `ln(softplus(a))` and `d/da` of it, `sigmoid(a) / softplus(a)`, without
/// underflow deep in the tail (where both tend to `a` and 1).
fn ln_softplus(a: f64) -> (f64, f64) {
    if a < -30.0 {
        let e = a.exp();
        // softplus = e (1 - e/2 + ...), sigmoid = e (1 - e + ...)
        (a + (-0.5 * e).ln_1p(), (1.0 - e) / (1.0 - 0.5 * e))
    } else {
        let sp = softplus(a);
        (sp.ln(), super::sigmoid(a) / sp)
    }
}

impl Group {
    fn new(kp: f64, ex: f64, kvb: f64, sections: Vec<(f64, f64)>) -> Group {
        let max_inv_mu = sections.iter().map(|s| s.0).fold(f64::MIN, f64::max);
        let u_lo = -max_inv_mu + TAIL_A / kp;
        let du = DU_KP / kp;
        let n = ((U_HI - u_lo) / du).ceil().max(1.0) as usize;
        // ln Phi and its slope at the nodes, by log-sum-exp over the sections.
        let node = |u: f64| -> (f64, f64) {
            let terms: Vec<(f64, f64)> = sections
                .iter()
                .map(|&(inv_mu, scale)| {
                    let (l, d) = ln_softplus(kp * (inv_mu + u));
                    (scale.ln() + ex * l, ex * kp * d)
                })
                .collect();
            let top = terms.iter().map(|t| t.0).fold(f64::MIN, f64::max);
            let (mut s, mut ds) = (0.0, 0.0);
            for &(l, d) in &terms {
                let w = (l - top).exp();
                s += w;
                ds += w * d;
            }
            (top + s.ln(), ds / s)
        };
        let ys: Vec<(f64, f64)> = (0..=n).map(|j| node(u_lo + j as f64 * du)).collect();
        let coef = ys
            .windows(2)
            .map(|w| {
                let ((y0, d0), (y1, d1)) = (w[0], w[1]);
                let (m0, m1) = (d0 * du, d1 * du);
                [
                    y0,
                    m0,
                    3.0 * (y1 - y0) - 2.0 * m0 - m1,
                    2.0 * (y0 - y1) + m0 + m1,
                ]
            })
            .collect();
        Group {
            kp,
            ex,
            kvb,
            sections,
            u_lo,
            inv_du: 1.0 / du,
            coef,
        }
    }

    /// Plate current and its derivatives (d/dVg, d/dVp), Vp > 0.
    #[inline]
    fn plate(&self, vg: f64, vp: f64) -> (f64, f64, f64) {
        let s2 = self.kvb + vp * vp;
        let s = s2.sqrt();
        let u = vg / s;
        let x = (u - self.u_lo) * self.inv_du;
        let (y, dy) = if x < 0.0 {
            // The exponential tail: linear in u.
            let c = &self.coef[0];
            (c[0] + c[1] * x, c[1] * self.inv_du)
        } else {
            let j = x as usize;
            if j >= self.coef.len() {
                return self.exact(vg, vp);
            }
            let t = x - j as f64;
            let c = &self.coef[j];
            (
                c[0] + t * (c[1] + t * (c[2] + t * c[3])),
                (c[1] + t * (2.0 * c[2] + t * 3.0 * c[3])) * self.inv_du,
            )
        };
        // (Vp / Kp)^Ex e^y and its derivatives.
        let lp = fastmath::ln(vp / self.kp);
        let i = fastmath::exp(self.ex * lp + y);
        let di_du = i * dy;
        (i, di_du / s, self.ex * i / vp - di_du * vg * vp / (s2 * s))
    }

    /// The exact sections, as [`Triode::plate`] sums them.
    fn exact(&self, vg: f64, vp: f64) -> (f64, f64, f64) {
        let s = (self.kvb + vp * vp).sqrt();
        let (mut ip, mut d_vg, mut d_vp) = (0.0, 0.0, 0.0);
        for &(inv_mu, scale) in &self.sections {
            let a = self.kp * (inv_mu + vg / s);
            let sp = softplus(a);
            let e1 = vp / self.kp * sp;
            if e1 >= f64::MIN_POSITIVE {
                let i = scale * e1.powf(self.ex);
                let di_de1 = self.ex * i / e1;
                let sg = super::sigmoid(a);
                ip += i;
                d_vg += di_de1 * vp / s * sg;
                d_vp += di_de1 * (sp / self.kp - vp * vp * vg / (s * s * s) * sg);
            }
        }
        (ip, d_vg, d_vp)
    }
}

/// Tabulated triodes on the same pins (one tube, or a bank in parallel).
#[derive(Debug, Clone)]
pub struct TriodeTable {
    groups: Vec<Group>,
    /// Distinct grid-current laws, and how many tubes have each.
    grids: Vec<(ir::GridCurrent, f64)>,
}

impl TriodeTable {
    /// The table of `tubes` in parallel (one or more).
    pub fn new(tubes: &[&Triode]) -> TriodeTable {
        // Sections by (Kp, Ex, Kvb).
        type Key = (f64, f64, f64);
        let mut keyed: Vec<(Key, Vec<(f64, f64)>)> = Vec::new();
        let mut grids: Vec<(ir::GridCurrent, f64)> = Vec::new();
        for t in tubes {
            let (inv_mu, scale, kp, ex, kvb) = t.koren();
            let key = (kp, ex, kvb);
            let secs = inv_mu.iter().copied().zip(scale.iter().copied());
            match keyed.iter_mut().find(|(k, _)| *k == key) {
                Some((_, s)) => s.extend(secs),
                None => keyed.push((key, secs.collect())),
            }
            if let Some(g) = t.grid_model() {
                match grids.iter_mut().find(|(h, _)| h == g) {
                    Some((_, n)) => *n += 1.0,
                    None => grids.push((g.clone(), 1.0)),
                }
            }
        }
        TriodeTable {
            groups: keyed
                .into_iter()
                .map(|((kp, ex, kvb), s)| Group::new(kp, ex, kvb, s))
                .collect(),
            grids,
        }
    }

    /// Table points (all groups), for the record.
    pub fn len(&self) -> usize {
        self.groups.iter().map(|g| g.coef.len() + 1).sum()
    }

    pub fn is_empty(&self) -> bool {
        self.groups.is_empty()
    }

    /// Plate current and its derivatives (d/dVg, d/dVp).
    pub fn plate(&self, vg: f64, vp: f64) -> (f64, f64, f64) {
        if vp.is_nan() {
            return (f64::NAN, f64::NAN, f64::NAN);
        }
        if vp <= 0.0 {
            // Zero at and below Vp = 0, as in the exact model.
            return (0.0, 0.0, 0.0);
        }
        let (mut ip, mut d_vg, mut d_vp) = (0.0, 0.0, 0.0);
        for g in &self.groups {
            let (i, a, b) = g.plate(vg, vp);
            ip += i;
            d_vg += a;
            d_vp += b;
        }
        (ip, d_vg, d_vp)
    }
}

impl Device for TriodeTable {
    fn ports(&self) -> usize {
        2
    }

    fn eval(&self, v: &[f64], i: &mut [f64], g: &mut [f64]) {
        let (vp, vg) = (v[0], v[1]);
        let (ip, dp_vg, dp_vp) = self.plate(vg, vp);
        let (mut ig, mut dg_vg) = (0.0, 0.0);
        for (law, n) in &self.grids {
            let (a, b) = grid_current(law, vg);
            ig += n * a;
            dg_vg += n * b;
        }
        i[0] = ip;
        i[1] = ig;
        g[0] = dp_vp;
        g[1] = dp_vg;
        g[2] = 0.0;
        g[3] = dg_vg;
    }
}
