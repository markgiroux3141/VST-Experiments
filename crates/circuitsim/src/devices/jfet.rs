//! Junction field-effect transistors: a compiled port of `varimu/devices/jfet.py` (its
//! docstring has the model, SPICE's level-1 JFET with the doping tail B, and what is left
//! out).
//!
//! Pins (d, g, s), two ports relative to the source: V(d, s) and V(g, s); the currents flow
//! into the drain and the gate. A P-channel JFET evaluates the N-channel equations on the
//! negated voltages and negates the currents (its Jacobian keeps its sign). Stateless; the
//! series resistances and gate capacitances are the `jfet` part's linear elements.

use super::Device;
use super::diode::{VT_TNOM, pnjlim};
use crate::ir;

/// Exponent past which a gate junction's exponential continues linearly (Python:
/// `EXP_MAX`).
const EXP_MAX: f64 = 80.0;

fn exp_lin(x: f64) -> (f64, f64) {
    if x > EXP_MAX {
        let e = EXP_MAX.exp();
        (e * (1.0 + (x - EXP_MAX)), e)
    } else {
        let e = x.exp();
        (e, e)
    }
}

#[derive(Debug, Clone)]
pub struct Jfet {
    sign: f64,
    vto: f64,
    beta: f64,
    lambda: f64,
    is_a: f64,
    nvt: f64,
    b: f64,
    bfac: f64,
    /// SPICE's critical voltage for the gate junctions' limiting.
    vcrit: f64,
}

impl Jfet {
    pub fn new(m: &ir::Jfet) -> Jfet {
        let nvt = m.n * VT_TNOM;
        Jfet {
            sign: match m.polarity {
                ir::JfetPolarity::Njf => 1.0,
                ir::JfetPolarity::Pjf => -1.0,
            },
            vto: m.vto_v,
            beta: m.beta_a_per_v2,
            lambda: m.lambda_per_v,
            is_a: m.is_a,
            nvt,
            b: m.b,
            bfac: (1.0 - m.b) / (m.pb_v - m.vto_v),
            vcrit: nvt * (nvt / (std::f64::consts::SQRT_2 * m.is_a)).ln(),
        }
    }

    /// The normal mode's channel current (vds >= 0) and its derivatives
    /// `(I, dI/dvgs, dI/dvds)`, N-channel signs, in `jfet.py`'s order of operations.
    fn normal(&self, vgs: f64, vds: f64) -> (f64, f64, f64) {
        let vgst = vgs - self.vto;
        let (lam, beta, b, bfac) = (self.lambda, self.beta, self.b, self.bfac);
        let betap = beta * (1.0 + lam * vds);
        let (cpart, dc_g, dc_d) = if vgst > 0.0 && vgst >= vds {
            let apart = 2.0 * b + 3.0 * bfac * (vgst - vds);
            let cpart = vds * (vds * (bfac * vds - b) + vgst * apart);
            let dcl_g = vds * (apart + 3.0 * bfac * vgst);
            let dcl_d = (vds * (bfac * vds - b) + vgst * apart)
                + vds * (2.0 * bfac * vds - b - 3.0 * bfac * vgst);
            (cpart, dcl_g, dcl_d)
        } else if vgst > 0.0 {
            let cpart = vgst * vgst * (b + bfac * vgst);
            let dcs_g = vgst * (2.0 * b + 3.0 * bfac * vgst);
            (cpart, dcs_g, 0.0)
        } else {
            (0.0, 0.0, 0.0)
        };
        let i = betap * cpart;
        let di_g = betap * dc_g;
        let di_d = betap * dc_d + beta * lam * cpart;
        (i, di_g, di_d)
    }

    /// N-channel-signed (vgs, vds) -> `(Ich, dIch/dvgs, dIch/dvds)`, both modes.
    pub fn channel(&self, vgs: f64, vds: f64) -> (f64, f64, f64) {
        if vds >= 0.0 {
            self.normal(vgs, vds)
        } else {
            let (i_r, dr_g, dr_d) = self.normal(vgs - vds, -vds);
            (-i_r, -dr_g, dr_g + dr_d)
        }
    }

    /// A gate junction's current and conductance at its forward voltage `v`.
    fn gate(&self, v: f64) -> (f64, f64) {
        let (e, de) = exp_lin(v / self.nvt);
        (self.is_a * (e - 1.0), self.is_a * de / self.nvt)
    }
}

impl Device for Jfet {
    fn ports(&self) -> usize {
        2
    }

    fn eval(&self, v: &[f64], i: &mut [f64], g: &mut [f64]) {
        let s = self.sign;
        let (vds, vgs) = (s * v[0], s * v[1]);
        let (ich, di_g, di_d) = self.channel(vgs, vds);
        let (igs, ggs) = self.gate(vgs);
        let (igd, ggd) = self.gate(vgs - vds);
        i[0] = s * (ich - igd);
        i[1] = s * (igs + igd);
        g[0] = di_d + ggd;
        g[1] = di_g - ggd;
        g[2] = -ggd;
        g[3] = ggs + ggd;
    }

    /// SPICE's limiting of both gate junctions (`DEVpnjlim` on vgs and vgd, as ngspice's
    /// `jfetload.c`), in N-channel signs; V(d, s) follows as vgs - vgd.
    fn limit(&self, v: &mut [f64], v_old: &[f64]) -> bool {
        let s = self.sign;
        let (vgs, vgd) = (s * v[1], s * (v[1] - v[0]));
        let (vgs_old, vgd_old) = (s * v_old[1], s * (v_old[1] - v_old[0]));
        let (vgs_l, ls) = pnjlim(vgs, vgs_old, self.nvt, self.vcrit);
        let (vgd_l, ld) = pnjlim(vgd, vgd_old, self.nvt, self.vcrit);
        if ls || ld {
            v[1] = s * vgs_l;
            v[0] = s * (vgs_l - vgd_l);
        }
        ls || ld
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn model(polarity: ir::JfetPolarity) -> ir::Jfet {
        ir::Jfet {
            name: "J".into(),
            polarity,
            vto_v: -2.0,
            beta_a_per_v2: 1e-3,
            lambda_per_v: 0.01,
            is_a: 1e-14,
            n: 1.2,
            b: 0.9,
            pb_v: 0.8,
            rd_ohm: 0.0,
            rs_ohm: 0.0,
            cgs_f: 0.0,
            cgd_f: 0.0,
        }
    }

    #[test]
    fn matches_ngspice_points_and_mirrors() {
        // ngspice 47's .op (jfet.py's docstring): 1.93523 mA at vds 1, vgs -0.5; -0.981686
        // mA at vds -0.3, vgs -0.5 (B 0.9, PB 0.8, LAMBDA 0.01).
        let n = Jfet::new(&model(ir::JfetPolarity::Njf));
        let (mut i, mut g) = ([0.0; 2], [0.0; 4]);
        n.eval(&[1.0, -0.5], &mut i, &mut g);
        assert!((i[0] - 1.93523e-3).abs() < 1e-8, "{i:?}");
        n.eval(&[-0.3, -0.5], &mut i, &mut g);
        assert!((i[0] + 9.816862e-4).abs() < 1e-9, "{i:?}");
        let p = Jfet::new(&model(ir::JfetPolarity::Pjf));
        let (mut ip, mut gp) = ([0.0; 2], [0.0; 4]);
        p.eval(&[0.3, 0.5], &mut ip, &mut gp);
        assert_eq!(i, [-ip[0], -ip[1]]);
        assert_eq!(g, gp);
    }
}
