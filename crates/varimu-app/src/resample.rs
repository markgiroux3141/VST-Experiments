//! `scipy.signal.resample_poly` (scipy 1.18) with its default window (Kaiser, beta 5),
//! ported operation for operation, so a file loads and a render's input and outputs
//! resample exactly as Python's do (`varimu.sim.io`: `load_audio`, `upsample`,
//! `resample`, `decimate`). That is what lets a Rust render equal a Python render
//! bit for bit (NATIVE_APP_PLAN.md, R2); the player uses the same code to bring a
//! file to its host rate, as `varimu.sim.live` does.
//!
//! The pieces, each in numpy's / scipy's order of floating-point operations:
//! `firwin(2 * half_len + 1, 1 / max(up, down), window=('kaiser', 5.0))` (numpy's
//! `sinc`, scipy's Kaiser window with Cephes `i0`, the DC gain normalised by numpy's
//! pairwise sum), scaled by `up`, padded to centre the output, then `upfirdn`'s
//! polyphase loop (`_upfirdn_apply.pyx`), and the excess trimmed.
//! `tests/resample.rs` compares the filters and outputs with scipy's
//! (`scripts/export_app_fixtures.py`).

use std::f64::consts::PI;

use varimu_circuit::devices::pairwise_sum;

/// How the signal continues past its ends (scipy's `padtype`; the two the project uses).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Pad {
    /// Zeros (`padtype="constant"`, scipy's default: `load_audio`, `upsample`).
    Zero,
    /// The end samples held (`padtype="edge"`: `resample`, `decimate`).
    Edge,
}

/// Cephes' Chebyshev coefficients for `exp(-x) i0(x)` on [0, 8] (numpy's `_i0A`,
/// scipy's `xsf/cephes/i0.h`).
const I0_A: [f64; 30] = [
    -4.4153416464793395e-18,
    3.3307945188222384e-17,
    -2.431279846547955e-16,
    1.715391285555133e-15,
    -1.1685332877993451e-14,
    7.676185498604936e-14,
    -4.856446783111929e-13,
    2.95505266312964e-12,
    -1.726826291441556e-11,
    9.675809035373237e-11,
    -5.189795601635263e-10,
    2.6598237246823866e-09,
    -1.300025009986248e-08,
    6.046995022541919e-08,
    -2.670793853940612e-07,
    1.1173875391201037e-06,
    -4.4167383584587505e-06,
    1.6448448070728896e-05,
    -5.754195010082104e-05,
    0.00018850288509584165,
    -0.0005763755745385824,
    0.0016394756169413357,
    -0.004324309995050576,
    0.010546460394594998,
    -0.02373741480589947,
    0.04930528423967071,
    -0.09490109704804764,
    0.17162090152220877,
    -0.3046826723431984,
    0.6767952744094761,
];

fn chbevl(x: f64, coeffs: &[f64]) -> f64 {
    let (mut b0, mut b1, mut b2) = (coeffs[0], 0.0, 0.0);
    for &c in &coeffs[1..] {
        b2 = b1;
        b1 = b0;
        b0 = x * b1 - b2 + c;
    }
    0.5 * (b0 - b2)
}

/// The modified Bessel function I0 on [0, 8], where a Kaiser window's argument stays
/// (it is at most beta).
fn i0(x: f64) -> f64 {
    let x = x.abs();
    assert!(x <= 8.0, "i0 is only ported for |x| <= 8");
    x.exp() * chbevl(x / 2.0 - 2.0, &I0_A)
}

/// numpy's `sinc`: `sin(pi x) / (pi x)`, 1 at 0.
fn sinc(x: f64) -> f64 {
    let x = PI * x;
    let y = if x != 0.0 { x } else { f64::EPSILON };
    y.sin() / y
}

/// scipy's symmetric Kaiser window of `m` points.
fn kaiser(m: usize, beta: f64) -> Vec<f64> {
    if m <= 1 {
        return vec![1.0; m];
    }
    let alpha = (m - 1) as f64 / 2.0;
    let den = i0(beta);
    (0..m)
        .map(|n| {
            let r = (n as f64 - alpha) / alpha;
            i0(beta * (1.0 - r * r).sqrt()) / den
        })
        .collect()
}

/// scipy's `firwin(numtaps, cutoff, window=('kaiser', beta))`: a low-pass, scaled to
/// unity gain at DC (`cutoff` relative to Nyquist).
pub fn firwin_kaiser(numtaps: usize, cutoff: f64, beta: f64) -> Vec<f64> {
    let alpha = 0.5 * (numtaps - 1) as f64;
    let win = kaiser(numtaps, beta);
    let mut h: Vec<f64> = (0..numtaps)
        .map(|i| {
            let m = i as f64 - alpha;
            // h = 0; h += right * sinc(right * m); h -= left * sinc(left * m), left = 0.
            (0.0 + cutoff * sinc(cutoff * m)) - 0.0 * sinc(0.0 * m)
        })
        .collect();
    for (x, w) in h.iter_mut().zip(&win) {
        *x *= w;
    }
    // Scaled at DC: cos(pi * m * 0) = 1, so the sum of h itself.
    let s = pairwise_sum(&h);
    for x in &mut h {
        *x /= s;
    }
    h
}

/// scipy's `_output_len`: upfirdn's output length.
fn output_len(len_h: usize, len_x: usize, up: usize, down: usize) -> usize {
    let n = len_x + (len_h + (up - len_h % up) % up) / up - 1;
    (n * up).div_ceil(down)
}

fn gcd(a: usize, b: usize) -> usize {
    if b == 0 { a } else { gcd(b, a % b) }
}

/// A resampler by `up / down` (reduced by their gcd), its filter designed once.
#[derive(Debug, Clone)]
pub struct Resampler {
    up: usize,
    down: usize,
    /// The filter's taps, scaled by `up` (zero-padded per signal in `apply`).
    h: Vec<f64>,
    n_pre_pad: usize,
    half_len: usize,
}

impl Resampler {
    pub fn new(up: usize, down: usize) -> Resampler {
        assert!(up >= 1 && down >= 1, "up and down must be >= 1");
        let g = gcd(up, down);
        let (up, down) = (up / g, down / g);
        let max_rate = up.max(down);
        let half_len = 10 * max_rate;
        let mut h = firwin_kaiser(2 * half_len + 1, 1.0 / max_rate as f64, 5.0);
        for x in &mut h {
            *x *= up as f64;
        }
        let n_pre_pad = down - half_len % down;
        Resampler {
            up,
            down,
            h,
            n_pre_pad,
            half_len,
        }
    }

    /// The filter's taps (scaled by `up`), as scipy designs them.
    pub fn taps(&self) -> &[f64] {
        &self.h
    }

    /// `resample_poly(x, up, down, padtype=pad)`.
    pub fn apply(&self, x: &[f64], pad: Pad) -> Vec<f64> {
        let (up, down) = (self.up, self.down);
        if up == 1 && down == 1 {
            return x.to_vec();
        }
        let n_in = x.len();
        let n_out = (n_in * up).div_ceil(down);
        let n_pre_remove = (self.half_len + self.n_pre_pad) / down;
        let mut n_post_pad = 0;
        while output_len(self.h.len() + self.n_pre_pad + n_post_pad, n_in, up, down)
            < n_out + n_pre_remove
        {
            n_post_pad += 1;
        }
        let mut h = vec![0.0; self.n_pre_pad];
        h.extend_from_slice(&self.h);
        h.resize(h.len() + n_post_pad, 0.0);
        let y = upfirdn(&h, x, up, down, pad);
        y[n_pre_remove..n_pre_remove + n_out].to_vec()
    }
}

/// `resample_poly(x, up, down, padtype=pad)` with a filter designed for the call.
pub fn resample_poly(x: &[f64], up: usize, down: usize, pad: Pad) -> Vec<f64> {
    Resampler::new(up, down).apply(x, pad)
}

/// `x` from `rate_in` to `rate_out` (`varimu.sim.io.resample`: edges held).
pub fn resample(x: &[f64], rate_in: u32, rate_out: u32) -> Vec<f64> {
    if rate_in == rate_out {
        return x.to_vec();
    }
    resample_poly(x, rate_out as usize, rate_in as usize, Pad::Edge)
}

/// `resample_poly`'s filter applied to a stream fed in pieces of any size (live input to
/// the host rate): the same output as [`resample_poly`] with zero padding, from its
/// first sample on, delayed by nothing more than the filter's half length (the input
/// it needs past each output: `half_len / up` input samples, 10 at most ratios).
#[derive(Debug, Clone)]
pub struct StreamResampler {
    up: usize,
    down: usize,
    half_len: usize,
    h: Vec<f64>,
    /// Inputs from sample `x0` on.
    x: Vec<f64>,
    x0: usize,
    /// The next output sample.
    m: usize,
}

impl StreamResampler {
    pub fn new(up: usize, down: usize) -> StreamResampler {
        let r = Resampler::new(up, down);
        StreamResampler {
            up: r.up,
            down: r.down,
            half_len: r.half_len,
            h: r.h,
            x: Vec::new(),
            x0: 0,
            m: 0,
        }
    }

    /// Feed `input`; append every output sample it completes to `out`.
    pub fn process(&mut self, input: &[f64], out: &mut Vec<f64>) {
        if self.up == 1 && self.down == 1 {
            out.extend_from_slice(input);
            return;
        }
        self.x.extend_from_slice(input);
        let (up, len_h) = (self.up, self.h.len());
        let known = self.x0 + self.x.len();
        loop {
            // Output m sits at m * down on the upsampled grid; the filter is centred.
            let n = self.m * self.down + self.half_len;
            let hi = n / up;
            if hi >= known {
                break;
            }
            let lo = (n + 1).saturating_sub(len_h).div_ceil(up);
            let mut acc = 0.0;
            for i in lo.max(self.x0)..=hi {
                acc += self.x[i - self.x0] * self.h[n - i * up];
            }
            out.push(acc);
            self.m += 1;
        }
        let keep = (self.m * self.down + self.half_len + 1)
            .saturating_sub(len_h)
            .div_ceil(up);
        if keep > self.x0 {
            let k = (keep - self.x0).min(self.x.len());
            self.x.drain(..k);
            self.x0 += k;
        }
    }
}

/// scipy's `upfirdn(h, x, up, down, mode)`: zero-stuff by `up`, filter, keep every
/// `down`-th sample. The loop is `_upfirdn_apply.pyx`'s `_apply_impl`.
fn upfirdn(h: &[f64], x: &[f64], up: usize, down: usize, pad: Pad) -> Vec<f64> {
    let len_out = output_len(h.len(), x.len(), up, down);
    // _pad_h: zero-padded to a multiple of `up`, then per phase, flipped.
    let padded = h.len() + (up - h.len() % up) % up;
    let rows = padded / up;
    let at = |i: usize| if i < h.len() { h[i] } else { 0.0 };
    let mut hf = Vec::with_capacity(padded);
    for p in 0..up {
        for j in (0..rows).rev() {
            hf.push(at(j * up + p));
        }
    }
    let per_phase = rows;
    let len_x = x.len() as isize;
    let padded_len = len_x + per_phase as isize - 1;
    let (left, right) = match pad {
        Pad::Zero => (0.0, 0.0),
        Pad::Edge => (x[0], x[x.len() - 1]),
    };
    let zpad = pad == Pad::Zero;
    let mut out = vec![0.0; len_out];
    let (mut x_idx, mut y_idx, mut t) = (0isize, 0usize, 0usize);
    while x_idx < len_x {
        let mut h_idx = t * per_phase;
        let mut conv = x_idx - per_phase as isize + 1;
        if conv < 0 {
            if zpad {
                h_idx += (-conv) as usize;
            } else {
                while conv < 0 {
                    out[y_idx] += left * hf[h_idx];
                    h_idx += 1;
                    conv += 1;
                }
            }
            conv = 0;
        }
        while conv <= x_idx {
            out[y_idx] += x[conv as usize] * hf[h_idx];
            h_idx += 1;
            conv += 1;
        }
        y_idx += 1;
        t += down;
        x_idx += (t / up) as isize;
        t %= up;
    }
    while x_idx < padded_len && y_idx < len_out {
        let mut h_idx = t * per_phase;
        let mut conv = x_idx - per_phase as isize + 1;
        while conv <= x_idx {
            let v = if conv >= len_x {
                right
            } else if conv < 0 {
                left
            } else {
                x[conv as usize]
            };
            out[y_idx] += v * hf[h_idx];
            h_idx += 1;
            conv += 1;
        }
        y_idx += 1;
        t += down;
        x_idx += (t / up) as isize;
        t %= up;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identity_and_lengths() {
        let x: Vec<f64> = (0..100).map(|i| (i as f64 * 0.1).sin()).collect();
        assert_eq!(resample(&x, 48_000, 48_000), x);
        assert_eq!(resample_poly(&x, 2, 1, Pad::Zero).len(), 200);
        assert_eq!(resample_poly(&x, 1, 2, Pad::Edge).len(), 50);
        assert_eq!(resample_poly(&x, 320, 147, Pad::Zero).len(), 218);
    }

    #[test]
    fn filter_has_unity_dc_gain() {
        let h = firwin_kaiser(41, 0.5, 5.0);
        let s: f64 = h.iter().sum();
        assert!((s - 1.0).abs() < 1e-12);
        // Symmetric (linear phase).
        for i in 0..20 {
            assert_eq!(h[i], h[40 - i]);
        }
    }

    #[test]
    fn streaming_equals_offline() {
        let x: Vec<f64> = (0..3000)
            .map(|i| ((i * 7919) % 1000) as f64 / 500.0 - 1.0)
            .collect();
        for (up, down) in [(2, 1), (1, 2), (160, 147), (147, 160), (1, 1)] {
            let want = resample_poly(&x, up, down, Pad::Zero);
            let mut r = StreamResampler::new(up, down);
            let mut got = Vec::new();
            for piece in x.chunks(97) {
                r.process(piece, &mut got);
            }
            // All but the end, which waits for input past it.
            assert!(
                got.len() + 30 >= want.len(),
                "{up}/{down}: {} of {}",
                got.len(),
                want.len()
            );
            for (i, (a, b)) in got.iter().zip(&want).enumerate() {
                assert!((a - b).abs() < 1e-12, "{up}/{down} sample {i}: {a} vs {b}");
            }
        }
    }

    #[test]
    fn upsampled_sine_stays_a_sine() {
        let f = 1000.0 / 48_000.0;
        let x: Vec<f64> = (0..4800).map(|i| (2.0 * PI * f * i as f64).sin()).collect();
        let y = resample(&x, 48_000, 96_000);
        for (i, &v) in y.iter().enumerate().skip(200).take(9000) {
            let want = (2.0 * PI * f * i as f64 / 2.0).sin();
            assert!((v - want).abs() < 1e-3, "sample {i}: {v} vs {want}");
        }
    }
}
