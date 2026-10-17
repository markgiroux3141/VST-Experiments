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

use super::Device;
use crate::fastmath;
use crate::ir;

/// Sections are evaluated this many at a time, in passes over stack arrays
/// (one transcendental per pass), so the compiler vectorizes each pass and
/// the CPU overlaps its independent lanes instead of waiting out one long
/// dependency chain per section. The 6386 has 32.
const CHUNK: usize = 32;

/// What every section of one plate evaluation shares.
struct SectionInputs {
    kp: f64,
    ex: f64,
    vg_s: f64,
    vp_kp: f64,
    vp_s: f64,
    curv: f64,
}

impl SectionInputs {
    /// One section's current and derivatives (d/dVg, d/dVp), branch-free.
    /// The chunked passes in [`Triode::plate`] compute the same, step by step.
    #[inline(always)]
    fn section(&self, inv_mu: f64, scale: f64) -> (f64, f64, f64) {
        let a = self.kp * (inv_mu + self.vg_s);
        let e = fastmath::exp(-a.abs());
        let (sp, sg) = softplus_sigmoid(a, e);
        let e1 = self.vp_kp * sp;
        let (on, e1) = power_base(e1);
        let i = scale * fastmath::exp(self.ex * fastmath::ln(e1));
        self.finish(on, i, e1, sp, sg)
    }

    /// Current and derivatives from a section's pieces.
    #[inline(always)]
    fn finish(&self, on: bool, i: f64, e1: f64, sp: f64, sg: f64) -> (f64, f64, f64) {
        let di_de1 = if on { self.ex * i / e1 } else { 0.0 };
        (
            if on { i } else { 0.0 },
            di_de1 * self.vp_s * sg,
            di_de1 * (sp / self.kp - self.curv * sg),
        )
    }
}

/// softplus(a) = max(a, 0) + ln(1 + e) and its derivative sigmoid(a), from
/// `e = exp(-|a|)` (numpy's `logaddexp(0, a)` takes the same branches).
#[inline(always)]
fn softplus_sigmoid(a: f64, e: f64) -> (f64, f64) {
    let u = 1.0 + e;
    let inv_u = 1.0 / u;
    // ln(1 + e): ln(u), plus the rounding error of u to first order.
    let sp = if a > 0.0 { a } else { 0.0 } + (fastmath::ln(u) - ((u - 1.0) - e) * inv_u);
    let sg = if a >= 0.0 { inv_u } else { e * inv_u };
    (sp, sg)
}

/// `max(E1, 0)^Ex` is zero for E1 <= 0, and underflows for subnormal E1
/// (Ex > 1): whether the section conducts, and a base safe for `ln`.
#[inline(always)]
fn power_base(e1: f64) -> (bool, f64) {
    let on = e1 >= f64::MIN_POSITIVE;
    (on, if on { e1 } else { 1.0 })
}

#[derive(Debug, Clone)]
pub struct Triode {
    /// Per section: 1 / mu and 2 / Kg1.
    inv_mu: Vec<f64>,
    scale: Vec<f64>,
    sections: usize,
    ex: f64,
    kp: f64,
    kvb: f64,
    grid: Option<ir::GridCurrent>,
}

impl Triode {
    pub fn new(m: &ir::Triode) -> Triode {
        // Python: KorenTriode(mu, ex, kg1 / w, ...), whose ip() uses 1 / mu and 2.0 / kg1.
        let section = |mu: f64, kg1: f64| (1.0 / mu, 2.0 / kg1);
        let (sections, ex, kp, kvb): (Vec<(f64, f64)>, _, _, _) = match &m.plate {
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
            inv_mu: sections.iter().map(|s| s.0).collect(),
            scale: sections.iter().map(|s| s.1).collect(),
            sections: sections.len(),
            ex,
            kp,
            kvb,
            grid: m.grid.clone(),
        }
    }

    /// Plate current and its derivatives (d/dVg, d/dVp).
    ///
    /// Sections are evaluated [`CHUNK`] at a time with branch-free
    /// arithmetic ([`fastmath`]), then summed in order, as Python's `sum`.
    /// Python's `x ** ex` is `exp(ex ln x)` here and numpy's `logaddexp` is
    /// `max(a, 0) + ln(1 + exp(-|a|))`: a few ulp apart (tests/devices.rs).
    /// With AVX2 (detected at run time) the chunks run 4 lanes wide; the
    /// results are the same either way (lane-wise IEEE arithmetic).
    pub fn plate(&self, vg: f64, vp: f64) -> (f64, f64, f64) {
        #[cfg(target_arch = "x86_64")]
        if self.sections >= CHUNK && std::is_x86_feature_detected!("avx2") {
            // SAFETY: the CPU has AVX2 (checked just above).
            return unsafe { self.plate_avx2(vg, vp) };
        }
        self.plate_impl(vg, vp)
    }

    #[cfg(target_arch = "x86_64")]
    #[target_feature(enable = "avx2")]
    fn plate_avx2(&self, vg: f64, vp: f64) -> (f64, f64, f64) {
        self.plate_impl(vg, vp)
    }

    #[inline(always)]
    fn plate_impl(&self, vg: f64, vp: f64) -> (f64, f64, f64) {
        let s = (self.kvb + vp * vp).sqrt();
        let p = SectionInputs {
            kp: self.kp,
            ex: self.ex,
            vg_s: vg / s,
            vp_kp: vp / self.kp,
            vp_s: vp / s,
            curv: vp * vp * vg / (s * s * s),
        };
        let (mut ip, mut d_vg, mut d_vp) = (0.0, 0.0, 0.0);
        let mu = self.inv_mu.chunks_exact(CHUNK);
        let sc = self.scale.chunks_exact(CHUNK);
        let (mu_rest, sc_rest) = (mu.remainder(), sc.remainder());
        for (inv_mu, scale) in mu.zip(sc) {
            // section(), one pass per transcendental.
            let (mut a, mut e) = ([0.0; CHUNK], [0.0; CHUNK]);
            for j in 0..CHUNK {
                a[j] = p.kp * (inv_mu[j] + p.vg_s);
                e[j] = fastmath::exp(-a[j].abs());
            }
            let (mut sp, mut sg, mut e1, mut l) =
                ([0.0; CHUNK], [0.0; CHUNK], [0.0; CHUNK], [0.0; CHUNK]);
            for j in 0..CHUNK {
                (sp[j], sg[j]) = softplus_sigmoid(a[j], e[j]);
            }
            for j in 0..CHUNK {
                e1[j] = power_base(p.vp_kp * sp[j]).1;
                l[j] = fastmath::ln(e1[j]);
            }
            let mut i = [0.0; CHUNK];
            for j in 0..CHUNK {
                i[j] = scale[j] * fastmath::exp(p.ex * l[j]);
            }
            let (mut dg, mut dp) = ([0.0; CHUNK], [0.0; CHUNK]);
            for j in 0..CHUNK {
                let on = power_base(p.vp_kp * sp[j]).0;
                (i[j], dg[j], dp[j]) = p.finish(on, i[j], e1[j], sp[j], sg[j]);
            }
            for j in 0..CHUNK {
                ip += i[j];
                d_vg += dg[j];
                d_vp += dp[j];
            }
        }
        for (&inv_mu, &scale) in mu_rest.iter().zip(sc_rest) {
            let (i, dg, dp) = p.section(inv_mu, scale);
            ip += i;
            d_vg += dg;
            d_vp += dp;
        }
        (ip, d_vg, d_vp)
    }

    /// Grid current and d/dVg (zero without a grid-current model). Python's
    /// `x ** 1.5` is `x sqrt(x)` here (within an ulp).
    pub fn grid(&self, vg: f64) -> (f64, f64) {
        match &self.grid {
            None => (0.0, 0.0),
            Some(g) => {
                let t = (vg - g.contact_v) / g.smooth_v;
                let (sp, sg) = softplus_sigmoid(t, fastmath::exp(-t.abs()));
                let x = g.smooth_v * sp;
                let sx = x.sqrt();
                (g.perveance * (x * sx), 1.5 * g.perveance * sx * sg)
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
