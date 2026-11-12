//! Koren pentode / beam-power tube. Mirrors `varimu/devices/pentode.py`:
//!
//! ```text
//! E1  = (Vg2 / Kp) * softplus(Kp * (1/mu + Vg1 / Vg2)),   Vg2 floored at 1 mV
//! Ip  = (2 / Kg1) * max(E1, 0)^Ex * atan(Vp / Kvb)
//! Ig2 = max(Vg1 + Vg2 / mu, 0)^1.5 / Kg2      (Koren's screen law)
//! Ig2 = max(E1, 0)^Ex / Kg2                  (`ScreenLaw::E1`)
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

/// Newton step limiting ([`Device::limit`]): a port moves at most this far per iteration
/// from its last linearization (the plate and the screen; the control grid
/// [`GRID_STEP_V`]), or [`STEP_FRACTION`] of its distance from the cathode there, whichever
/// is more. Numerics only: the solution is the same, the path to it shorter where the
/// plate's conductance vanishes (an output transformer's plate far from the knee, where a
/// small current mismatch asked for a step of kilovolts: the EL34s of the Marshall 1987 at
/// their flyback cycled between -6 and +6 kV until the iteration cap,
/// METHODOLOGY_REVIEW.md W1 "Status").
const PLATE_STEP_V: f64 = 50.0;
const GRID_STEP_V: f64 = 10.0;
const STEP_FRACTION: f64 = 0.5;

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
    screen: Option<ir::ScreenLaw>,
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
            screen: k.screen,
            grid: m.grid.clone(),
        }
    }
}

impl Device for Pentode {
    fn ports(&self) -> usize {
        3
    }

    fn limit(&self, v: &mut [f64], v_old: &[f64]) -> bool {
        let mut limited = false;
        for (j, floor) in [PLATE_STEP_V, PLATE_STEP_V, GRID_STEP_V]
            .into_iter()
            .enumerate()
        {
            let max = floor.max(STEP_FRACTION * v_old[j].abs());
            let d = v[j] - v_old[j];
            if d.abs() > max {
                v[j] = v_old[j] + max.copysign(d);
                limited = true;
            }
        }
        limited
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
        // dE1 / dVg2 and dE1 / dVg1.
        let sg = sigmoid(a);
        let (de1_dg2, de1_dg1) = (dg2 * (sp / self.kp - sg * vg1 / g2), sg);
        let e1x = if e1 > 0.0 { e1.powf(self.ex) } else { 0.0 };
        if e1 > 0.0 {
            let p = self.scale * e1x;
            let dp_de1 = self.ex * p / e1;
            i[0] = p * atan;
            g[0] = p / self.kvb / (1.0 + (vp / self.kvb).powi(2));
            g[1] = dp_de1 * atan * de1_dg2;
            g[2] = dp_de1 * atan * de1_dg1;
        } else {
            i[0] = 0.0;
        }

        // Screen.
        match self.screen {
            None => {
                let x = vg1 + vg2 / self.mu;
                if x > 0.0 {
                    i[1] = x.powf(1.5) / self.kg2;
                    let d = 1.5 * x.sqrt() / self.kg2;
                    g[3 + 1] = d / self.mu;
                    g[3 + 2] = d;
                } else {
                    i[1] = 0.0;
                }
            }
            Some(ir::ScreenLaw::E1) => {
                if e1 > 0.0 {
                    let s = e1x / self.kg2;
                    let ds_de1 = self.ex * s / e1;
                    i[1] = s;
                    g[3 + 1] = ds_de1 * de1_dg2;
                    g[3 + 2] = ds_de1 * de1_dg1;
                } else {
                    i[1] = 0.0;
                }
            }
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

#[cfg(test)]
mod tests {
    use super::*;

    fn el34() -> Pentode {
        Pentode::new(&ir::Pentode {
            name: "EL34".into(),
            model: ir::KorenPentode {
                mu: 11.0,
                ex: 1.35,
                kg1: 650.0,
                kg2: 4200.0,
                kp: 60.0,
                kvb: 24.0,
                screen: None,
            },
            grid: None,
            c_g1k: 0.0,
            c_g1p: 0.0,
            c_pk: 0.0,
        })
    }

    /// A Newton iterate kilovolts away (the flyback's cycling) is pulled back to the step
    /// limits; small steps pass untouched.
    #[test]
    fn newton_steps_are_limited() {
        let t = el34();
        let old = [40.0, 430.0, -22.0];
        let mut v = [-6400.0, 431.0, 18.0];
        assert!(t.limit(&mut v, &old));
        assert_eq!(v, [40.0 - PLATE_STEP_V, 431.0, -22.0 + 0.5 * 22.0]);
        let mut v = [1800.0, 430.0, -30.0];
        assert!(t.limit(&mut v, &[1000.0, 430.0, -22.0]));
        assert_eq!(v[0], 1500.0, "half the plate's voltage when that is more");
        let mut v = [45.0, 429.0, -21.0];
        assert!(!t.limit(&mut v, &old));
        assert_eq!(v, [45.0, 429.0, -21.0]);
    }
}
