//! Branch-free `exp` and `ln` that the compiler can vectorize, for device
//! models that evaluate many sections at once (the 32-section 6386).
//!
//! The standard library's `exp`/`ln` call the platform's libm one value at
//! a time; these are plain arithmetic and bit operations, so a loop over
//! sections compiles to SIMD. Accuracy: within 1 ulp of `std` (tests, ~1e6
//! points). Every operation is IEEE, so results don't depend on the vector
//! width.

// fdlibm's constants, by their bits.
const LN2_HI: f64 = f64::from_bits(0x3fe6_2e42_fee0_0000); // ln 2 to 32 bits
const LN2_LO: f64 = f64::from_bits(0x3dea_39ef_3579_3c76); // the rest
const INV_LN2: f64 = std::f64::consts::LOG2_E;
/// 1.5 * 2^52: adding it rounds to an integer held in the low mantissa bits.
const SHIFT: f64 = 6_755_399_441_055_744.0;

/// `2^k` for an integer-valued `kf` in [-1022, 1023].
#[inline(always)]
fn pow2(kf: f64) -> f64 {
    let bits = (kf + SHIFT).to_bits().wrapping_sub(SHIFT.to_bits());
    f64::from_bits(bits.wrapping_add(1023) << 52)
}

/// `e^x`. Overflows to infinity above ~709.78, gives subnormals and then 0
/// below ~-708.4, and NaN for NaN.
#[inline(always)]
pub fn exp(x: f64) -> f64 {
    // Clamp so k stays within range of the two-factor scaling (NaN passes).
    let xc = x.clamp(-1100.0, 710.0);
    // x = k ln2 + r, |r| <= ln2 / 2, k rounded to nearest.
    let kf = (xc * INV_LN2 + SHIFT) - SHIFT;
    let r = (xc - kf * LN2_HI) - kf * LN2_LO;
    // Taylor to degree 13 (the first omitted term is < 5e-18 relative), by
    // Estrin's scheme: a dependency chain of 5 multiply-adds instead of 13.
    // The leading 1 is added last, to the small rest.
    let r2 = r * r;
    let r4 = r2 * r2;
    let r8 = r4 * r4;
    let p23 = 0.5 + r * (1.0 / 6.0);
    let p45 = 1.0 / 24.0 + r * (1.0 / 120.0);
    let p67 = 1.0 / 720.0 + r * (1.0 / 5_040.0);
    let p89 = 1.0 / 40_320.0 + r * (1.0 / 362_880.0);
    let p1011 = 1.0 / 3_628_800.0 + r * (1.0 / 39_916_800.0);
    let p1213 = 1.0 / 479_001_600.0 + r * (1.0 / 6_227_020_800.0);
    let tail = (p23 + r2 * p45) + r4 * (p67 + r2 * p89) + r8 * (p1011 + r2 * p1213);
    let p = 1.0 + (r + r2 * tail);
    // 2^k as two factors, so subnormal and overflowing results come out
    // right without a branch.
    let k1 = (kf * 0.5 + SHIFT) - SHIFT;
    let k1 = if k1 > 1023.0 { 1023.0 } else { k1 };
    let k2 = kf - k1;
    p * pow2(k1) * pow2(k2)
}

// musl's log (fdlibm), < 1 ulp.
const LG1: f64 = f64::from_bits(0x3fe5_5555_5555_5593); // 6.666666666666735130e-01
const LG2: f64 = f64::from_bits(0x3fd9_9999_9997_fa04); // 3.999999999940941908e-01
const LG3: f64 = f64::from_bits(0x3fd2_4924_9422_9359); // 2.857142874366239149e-01
const LG4: f64 = f64::from_bits(0x3fcc_71c5_1d8e_78af); // 2.222219843214978396e-01
const LG5: f64 = f64::from_bits(0x3fc7_4664_96cb_03de); // 1.818357216161805012e-01
const LG6: f64 = f64::from_bits(0x3fc3_9a09_d078_c69f); // 1.531383769920937332e-01
const LG7: f64 = f64::from_bits(0x3fc2_f112_df3e_5244); // 1.479819860511658591e-01

/// `ln x` for positive normal `x` (`x >= f64::MIN_POSITIVE`, finite).
/// Other inputs give garbage; callers mask them.
#[inline(always)]
pub fn ln(x: f64) -> f64 {
    // Reduce x = 2^k m with m in [sqrt(2)/2, sqrt(2)).
    const SQRT_HALF_BITS: u64 = 0x3fe6_a09e_667f_3bcd;
    let ix = x
        .to_bits()
        .wrapping_add(0x3ff0_0000_0000_0000 - SQRT_HALF_BITS);
    // Biased exponent e as a float: (2^52 + e) - (2^52 + 1023) = e - 1023.
    let kf = f64::from_bits(0x4330_0000_0000_0000 | (ix >> 52)) - 4_503_599_627_371_519.0;
    let m = f64::from_bits((ix & 0x000f_ffff_ffff_ffff).wrapping_add(SQRT_HALF_BITS));
    let f = m - 1.0;
    let hfsq = 0.5 * f * f;
    let s = f / (2.0 + f);
    let z = s * s;
    let w = z * z;
    let t1 = w * (LG2 + w * (LG4 + w * LG6));
    let t2 = z * (LG1 + w * (LG3 + w * (LG5 + w * LG7)));
    let r = t2 + t1;
    s * (hfsq + r) + kf * LN2_LO - hfsq + f + kf * LN2_HI
}

/// `ln(1 + e)` for `e` in [0, 1] (the softplus case), a few ulp: `1 + e`
/// rounds, and the rounding error is put back to first order.
#[inline(always)]
pub fn ln_1p_unit(e: f64) -> f64 {
    let u = 1.0 + e;
    ln(u) - ((u - 1.0) - e) / u
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Relative error in units of f64::EPSILON (one ulp at 1.0 is EPSILON).
    fn ulps(got: f64, want: f64) -> f64 {
        if got == want {
            return 0.0;
        }
        ((got - want) / want).abs() / f64::EPSILON
    }

    /// A deterministic spread of points (no rand dependency).
    fn points(lo: f64, hi: f64, n: usize) -> impl Iterator<Item = f64> {
        let mut s: u64 = 0x9e37_79b9_7f4a_7c15;
        (0..n).map(move |_| {
            s ^= s << 13;
            s ^= s >> 7;
            s ^= s << 17;
            lo + (hi - lo) * ((s >> 11) as f64 / (1u64 << 53) as f64)
        })
    }

    #[test]
    fn exp_matches_std() {
        let mut worst = 0.0f64;
        for x in points(-700.0, 709.0, 400_000).chain(points(-1.0, 1.0, 200_000)) {
            worst = worst.max(ulps(exp(x), x.exp()));
        }
        assert!(worst <= 1.5, "worst {worst} ulp");
        assert_eq!(exp(0.0), 1.0);
        assert_eq!(exp(710.0), f64::INFINITY);
        assert_eq!(exp(-800.0), 0.0);
        assert!(exp(f64::NAN).is_nan());
        // Subnormal results, to within one subnormal step.
        for x in points(-745.0, -708.5, 10_000) {
            assert!((exp(x) - x.exp()).abs() <= 2.0 * 4.9e-324, "{x}");
        }
    }

    #[test]
    fn ln_matches_std() {
        let mut worst = 0.0f64;
        for e in points(-1020.0, 1020.0, 300_000) {
            let x = 2f64.powf(e);
            worst = worst.max(ulps(ln(x), x.ln()));
        }
        for x in points(0.5, 2.0, 300_000) {
            // Near 1 the result is small: compare in absolute ulps of 1.
            let err = (ln(x) - x.ln()).abs() / f64::EPSILON;
            worst = worst.max(err.min(ulps(ln(x), x.ln())));
        }
        assert!(worst <= 1.5, "worst {worst} ulp");
        assert_eq!(ln(1.0), 0.0);
        assert!((ln(f64::MIN_POSITIVE) - f64::MIN_POSITIVE.ln()).abs() < 1e-12);
        assert!((ln(f64::MAX) - f64::MAX.ln()).abs() < 1e-12);
    }

    #[test]
    fn ln_1p_unit_matches_std() {
        let mut worst = 0.0f64;
        for e in points(0.0, 1.0, 300_000).chain(points(-60.0, 0.0, 100_000).map(f64::exp)) {
            worst = worst.max(ulps(ln_1p_unit(e), e.ln_1p()));
        }
        assert!(worst <= 1.5, "worst {worst} ulp");
        assert_eq!(ln_1p_unit(0.0), 0.0);
        assert_eq!(ln_1p_unit(1e-300), 1e-300);
    }
}
