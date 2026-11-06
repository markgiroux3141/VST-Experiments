//! Bipolar junction transistors: a compiled port of `varimu/devices/bjt.py` (its docstring
//! has the model, SPICE's Gummel-Poon DC subset, and what is left out).
//!
//! Pins (c, b, e), two ports relative to the emitter: V(c, e) and V(b, e); the currents
//! flow into the collector and the base. A PNP evaluates the NPN equations on the negated
//! junction voltages and negates the currents (its Jacobian keeps its sign). Stateless;
//! the series resistances and junction capacitances are the `bjt` part's linear elements,
//! not the device's.

use super::Device;
use super::diode::{VT_TNOM, pnjlim};
use crate::ir;

/// Exponent past which a junction's exponential continues linearly (numerics only; Python:
/// `EXP_MAX`).
pub const EXP_MAX: f64 = 80.0;

/// `exp(x)` and its derivative, continued linearly above [`EXP_MAX`] (Python: `_exp`).
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
pub struct Bjt {
    sign: f64,
    is_a: f64,
    bf: f64,
    br: f64,
    nfv: f64,
    nrv: f64,
    inv_f: f64,
    inv_r: f64,
    oik: f64,
    oikr: f64,
    ise_a: f64,
    nev: f64,
    isc_a: f64,
    ncv: f64,
    /// SPICE's critical voltages for junction limiting (b-e, b-c).
    vcrit_e: f64,
    vcrit_c: f64,
}

/// `(Ic, Ib, dIc/dvbe, dIc/dvbc, dIb/dvbe, dIb/dvbc)`, NPN signs.
type Junction = (f64, f64, f64, f64, f64, f64);

/// ngspice's k / q as it precomputes it (Python: `K_OVER_Q`).
pub const K_OVER_Q: f64 = 1.38064852e-23 / 1.6021766208e-19;
/// SPICE's TNOM (REFTEMP), kelvin.
pub const TNOM_K: f64 = 300.15;

/// `(Vt, IS, BF, BR, ISE, ISC)` at the model's temperature (`bjt.py`'s `at_temperature`:
/// SPICE's scaling, TLEV 0; TNOM's values when `temp_k` is None).
pub fn at_temperature(m: &ir::Bjt) -> (f64, f64, f64, f64, f64, f64) {
    let Some(t) = m.temp_k else {
        return (VT_TNOM, m.is_a, m.bf, m.br, m.ise_a, m.isc_a);
    };
    let eg = m.eg_ev.unwrap_or(1.11);
    let xti = m.xti.unwrap_or(3.0);
    let xtb = m.xtb.unwrap_or(0.0);
    let vt = t * K_OVER_Q;
    let ratlog = (t / TNOM_K).ln();
    let ratio1 = t / TNOM_K - 1.0;
    let factlog = ratio1 * eg / vt + xti * ratlog;
    let factor = factlog.exp();
    let bfactor = (ratlog * xtb).exp();
    (
        vt,
        m.is_a * factor,
        m.bf * bfactor,
        m.br * bfactor,
        m.ise_a * (factlog / m.ne).exp() / bfactor,
        m.isc_a * (factlog / m.nc).exp() / bfactor,
    )
}

impl Bjt {
    pub fn new(m: &ir::Bjt) -> Bjt {
        let (vt, is_a, bf, br, ise_a, isc_a) = at_temperature(m);
        let nfv = m.nf * vt;
        let nrv = m.nr * vt;
        let inv = |x: Option<f64>| x.map_or(0.0, |x| 1.0 / x);
        let crit = |nv: f64| nv * (nv / (std::f64::consts::SQRT_2 * is_a)).ln();
        Bjt {
            sign: match m.polarity {
                ir::Polarity::Npn => 1.0,
                ir::Polarity::Pnp => -1.0,
            },
            is_a,
            bf,
            br,
            nfv,
            nrv,
            inv_f: inv(m.vaf_v),
            inv_r: inv(m.var_v),
            oik: inv(m.ikf_a),
            oikr: inv(m.ikr_a),
            ise_a,
            nev: m.ne * vt,
            isc_a,
            ncv: m.nc * vt,
            vcrit_e: crit(nfv),
            vcrit_c: crit(nrv),
        }
    }

    /// The Gummel-Poon currents and their derivatives at NPN-signed (vbe, vbc), in
    /// `bjt.py`'s order of operations.
    pub fn junction(&self, vbe: f64, vbc: f64) -> Junction {
        let (ef, dfe) = exp_lin(vbe / self.nfv);
        let (er, dre) = exp_lin(vbc / self.nrv);
        let ibe = self.is_a * (ef - 1.0);
        let gbe = self.is_a * dfe / self.nfv;
        let ibc = self.is_a * (er - 1.0);
        let gbc = self.is_a * dre / self.nrv;
        let (iben, gben) = if self.ise_a > 0.0 {
            let (en, den) = exp_lin(vbe / self.nev);
            (self.ise_a * (en - 1.0), self.ise_a * den / self.nev)
        } else {
            (0.0, 0.0)
        };
        let (ibcn, gbcn) = if self.isc_a > 0.0 {
            let (ec, dec) = exp_lin(vbc / self.ncv);
            (self.isc_a * (ec - 1.0), self.isc_a * dec / self.ncv)
        } else {
            (0.0, 0.0)
        };
        let q1 = 1.0 / (1.0 - self.inv_f * vbc - self.inv_r * vbe);
        let (qb, dqb_e, dqb_c) = if self.oik == 0.0 && self.oikr == 0.0 {
            let qb = q1;
            (qb, q1 * qb * self.inv_r, q1 * qb * self.inv_f)
        } else {
            let q2 = self.oik * ibe + self.oikr * ibc;
            let sq = (1.0 + 4.0 * q2).max(0.0).sqrt();
            let qb = q1 * (1.0 + sq) / 2.0;
            (
                qb,
                q1 * (qb * self.inv_r + self.oik * gbe / sq),
                q1 * (qb * self.inv_f + self.oikr * gbc / sq),
            )
        };
        let it = (ibe - ibc) / qb;
        let ic = it - ibc / self.br - ibcn;
        let ib = ibe / self.bf + iben + ibc / self.br + ibcn;
        let dic_e = gbe / qb - it / qb * dqb_e;
        let dic_c = -gbc / qb - it / qb * dqb_c - gbc / self.br - gbcn;
        let dib_e = gbe / self.bf + gben;
        let dib_c = gbc / self.br + gbcn;
        (ic, ib, dic_e, dic_c, dib_e, dib_c)
    }
}

impl Device for Bjt {
    fn ports(&self) -> usize {
        2
    }

    fn eval(&self, v: &[f64], i: &mut [f64], g: &mut [f64]) {
        let s = self.sign;
        let (vce, vbe) = (v[0], v[1]);
        let (ic, ib, dic_e, dic_c, dib_e, dib_c) = self.junction(s * vbe, s * (vbe - vce));
        i[0] = s * ic;
        i[1] = s * ib;
        g[0] = -dic_c;
        g[1] = dic_e + dic_c;
        g[2] = -dib_c;
        g[3] = dib_e + dib_c;
    }

    /// SPICE's limiting of both junctions (`DEVpnjlim` on vbe and vbc, as ngspice's
    /// `bjtload.c`), in NPN signs; V(c, e) follows as vbe - vbc.
    fn limit(&self, v: &mut [f64], v_old: &[f64]) -> bool {
        let s = self.sign;
        let (vbe, vbc) = (s * v[1], s * (v[1] - v[0]));
        let (vbe_old, vbc_old) = (s * v_old[1], s * (v_old[1] - v_old[0]));
        let (vbe_l, le) = pnjlim(vbe, vbe_old, self.nfv, self.vcrit_e);
        let (vbc_l, lc) = pnjlim(vbc, vbc_old, self.nrv, self.vcrit_c);
        if le || lc {
            v[1] = s * vbe_l;
            v[0] = s * (vbe_l - vbc_l);
        }
        le || lc
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn bc550c() -> ir::Bjt {
        ir::Bjt {
            name: "BC550C".into(),
            polarity: ir::Polarity::Npn,
            is_a: 4.679e-14,
            bf: 458.7,
            br: 11.57,
            nf: 1.01,
            nr: 1.019,
            vaf_v: Some(52.64),
            var_v: Some(364.5),
            ikf_a: Some(0.1371),
            ikr_a: Some(0.1144),
            ise_a: 2.642e-15,
            ne: 1.581,
            isc_a: 2.337e-14,
            nc: 1.164,
            rb_ohm: 1.0,
            rc_ohm: 1.0,
            re_ohm: 0.2598,
            cje_f: 1.229e-11,
            cjc_f: 1.78e-12,
            temp_k: None,
            eg_ev: None,
            xti: None,
            xtb: None,
        }
    }

    #[test]
    fn exponential_continues_linearly_and_smoothly() {
        let (a, da) = exp_lin(EXP_MAX);
        let (b, db) = exp_lin(EXP_MAX + 1e-9);
        assert!(((b - a) / 1e-9 / da - 1.0).abs() < 1e-5 && da == db);
        // A junction driven far forward stays finite.
        let q = Bjt::new(&bc550c());
        let (mut i, mut g) = ([0.0; 2], [0.0; 4]);
        q.eval(&[3.0, 5.0], &mut i, &mut g);
        assert!(i.iter().chain(&g).all(|x| x.is_finite()), "{i:?} {g:?}");
    }

    #[test]
    fn pnp_mirrors_npn() {
        let n = Bjt::new(&bc550c());
        let mut m = bc550c();
        m.polarity = ir::Polarity::Pnp;
        let p = Bjt::new(&m);
        let (mut i_n, mut g_n, mut i_p, mut g_p) = ([0.0; 2], [0.0; 4], [0.0; 2], [0.0; 4]);
        n.eval(&[5.0, 0.65], &mut i_n, &mut g_n);
        p.eval(&[-5.0, -0.65], &mut i_p, &mut g_p);
        assert_eq!(i_n, [-i_p[0], -i_p[1]]);
        assert_eq!(g_n, g_p);
        // Limiting: a cold start's jump onto the b-e junction is pulled back, both signs.
        let mut v = [5.0, 5.0];
        assert!(n.limit(&mut v, &[0.0, 0.0]) && v[1] < 0.5 && v[0] == v[1]);
        let mut w = [-5.0, -5.0];
        assert!(p.limit(&mut w, &[0.0, 0.0]) && w == [-v[0], -v[1]]);
    }
}
