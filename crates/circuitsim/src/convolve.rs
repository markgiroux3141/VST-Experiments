//! A strictly causal convolution run one sample at a time with no latency
//! (docs/REVERB_PLAN.md, E2): a linear medium coupled one way at its ports is an
//! impulse response from its drive to its pickup, and the engine needs the pickup's
//! next sample right after each step.
//!
//! `y[n] = sum_{k >= 1} h[k] x[n - k]`: `h[0]` is never used, so `y[n]` depends on the
//! input up to `n - 1` only ([`Convolver::push`] returns the next output once the
//! current input is in).
//!
//! **How.** The first `B` taps (`1..=B`) are a direct sum over a ring of the last
//! inputs. The rest, `t[m] = h[B + m]` for `m >= 1`, is a uniformly partitioned
//! overlap-save convolution (FFT size `2B`, segments of `B` taps, a frequency-domain
//! delay line of input blocks): when input block `c` (samples `cB .. cB + B`) is
//! complete, the tail's outputs `cB + B .. cB + 2B` are computed at once, one sample
//! before the first of them is needed. Cost per sample: `B` multiply-adds plus, per
//! block, two FFTs of `2B` and one complex product per segment and bin.
//!
//! Deterministic: the same `h`, `B` and inputs give the same outputs bit for bit.

use std::sync::Arc;

use rustfft::num_complex::Complex64;
use rustfft::{Fft, FftPlanner};

/// See the module docs.
pub struct Convolver {
    b: usize,
    /// Taps 1..=B, `head[k - 1] = h[k]`.
    head: Vec<f64>,
    /// The last `B` inputs, newest at `pos` (a ring).
    ring: Vec<f64>,
    pos: usize,
    /// The tail's segments' spectra (FFT of `2B`: `B` taps then `B` zeros).
    segs: Vec<Vec<Complex64>>,
    /// Input block spectra, newest first (overlap-save: the previous block and the
    /// current one).
    fdl: std::collections::VecDeque<Vec<Complex64>>,
    prev: Vec<f64>,
    cur: Vec<f64>,
    /// The tail's outputs for the coming block, and the next one's index into it.
    tail: Vec<f64>,
    tail_at: usize,
    fft: Arc<dyn Fft<f64>>,
    ifft: Arc<dyn Fft<f64>>,
    buf: Vec<Complex64>,
    acc: Vec<Complex64>,
    scratch: Vec<Complex64>,
}

impl Convolver {
    /// A convolver for impulse response `h` (`h[0]` ignored) with blocks of `b`.
    pub fn new(h: &[f64], b: usize) -> Convolver {
        let b = b.max(1);
        let mut head = vec![0.0; b];
        for (k, v) in head.iter_mut().enumerate() {
            *v = h.get(k + 1).copied().unwrap_or(0.0);
        }
        let mut planner = FftPlanner::<f64>::new();
        let fft = planner.plan_fft_forward(2 * b);
        let ifft = planner.plan_fft_inverse(2 * b);
        // t[m] = h[B + m], m >= 1; t[0] = 0. Segment j holds t[jB .. jB + B].
        let tail_len = h.len().saturating_sub(b + 1);
        let n_segs = (tail_len + 1).div_ceil(b);
        let scratch_len = fft
            .get_inplace_scratch_len()
            .max(ifft.get_inplace_scratch_len());
        let mut scratch = vec![Complex64::new(0.0, 0.0); scratch_len];
        let mut segs = Vec::with_capacity(n_segs);
        for j in 0..n_segs {
            let mut s = vec![Complex64::new(0.0, 0.0); 2 * b];
            for (i, v) in s.iter_mut().take(b).enumerate() {
                let m = j * b + i;
                if m >= 1 {
                    v.re = h.get(b + m).copied().unwrap_or(0.0);
                }
            }
            fft.process_with_scratch(&mut s, &mut scratch);
            segs.push(s);
        }
        let zero_block = vec![Complex64::new(0.0, 0.0); 2 * b];
        Convolver {
            b,
            head,
            ring: vec![0.0; b],
            pos: 0,
            fdl: std::iter::repeat_n(zero_block, n_segs).collect(),
            segs,
            prev: vec![0.0; b],
            cur: Vec::with_capacity(b),
            // The tail contributes nothing before the first block completes.
            tail: vec![0.0; b],
            tail_at: 0,
            fft,
            ifft,
            buf: vec![Complex64::new(0.0, 0.0); 2 * b],
            acc: vec![Complex64::new(0.0, 0.0); 2 * b],
            scratch,
        }
    }

    pub fn block(&self) -> usize {
        self.b
    }

    /// Take input `x[n]` and return `y[n + 1]`.
    pub fn push(&mut self, x: f64) -> f64 {
        let b = self.b;
        self.pos = (self.pos + 1) % b;
        self.ring[self.pos] = x;
        self.cur.push(x);
        // y[n + 1] = sum_{k=1}^{B} h[k] x[n + 1 - k]: x[n] is the newest.
        let mut y = 0.0;
        let mut i = self.pos;
        for &hk in &self.head {
            y += hk * self.ring[i];
            i = if i == 0 { b - 1 } else { i - 1 };
        }
        // The tail's output for sample n + 1: block c's outputs cover samples
        // cB + B .. cB + 2B, computed when block c completed.
        if self.cur.len() == b {
            self.finish_block();
        }
        let t = self.tail[self.tail_at];
        self.tail_at += 1;
        y + t
    }

    /// Block c is complete: the tail's outputs for the next `B` samples (z[cB .. cB +
    /// B] of t * x, which y needs `B` samples later).
    fn finish_block(&mut self) {
        let b = self.b;
        if self.segs.is_empty() {
            self.prev.clear();
            self.prev.append(&mut self.cur);
            self.tail.iter_mut().for_each(|v| *v = 0.0);
            self.tail_at = 0;
            return;
        }
        for (i, v) in self.buf.iter_mut().enumerate() {
            let x = if i < b { self.prev[i] } else { self.cur[i - b] };
            *v = Complex64::new(x, 0.0);
        }
        self.fft
            .process_with_scratch(&mut self.buf, &mut self.scratch);
        self.fdl.pop_back();
        self.fdl.push_front(self.buf.clone());
        self.acc
            .iter_mut()
            .for_each(|v| *v = Complex64::new(0.0, 0.0));
        for (seg, x) in self.segs.iter().zip(&self.fdl) {
            for ((a, s), xv) in self.acc.iter_mut().zip(seg).zip(x) {
                *a += s * xv;
            }
        }
        self.ifft
            .process_with_scratch(&mut self.acc, &mut self.scratch);
        let scale = 1.0 / (2 * b) as f64;
        for (i, v) in self.tail.iter_mut().enumerate() {
            *v = self.acc[b + i].re * scale;
        }
        self.tail_at = 0;
        self.prev.clear();
        self.prev.append(&mut self.cur);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn direct(h: &[f64], x: &[f64]) -> Vec<f64> {
        // y[n + 1] for n = 0.. (what push(x[n]) returns).
        (0..x.len())
            .map(|n| {
                let n1 = n + 1;
                (1..h.len())
                    .filter(|&k| k <= n1)
                    .map(|k| h[k] * x[n1 - k])
                    .sum()
            })
            .collect()
    }

    fn noise(n: usize, seed: u64) -> Vec<f64> {
        let mut s = seed;
        (0..n)
            .map(|_| {
                s = s
                    .wrapping_mul(6364136223846793005)
                    .wrapping_add(1442695040888963407);
                ((s >> 11) as f64 / (1u64 << 53) as f64) - 0.5
            })
            .collect()
    }

    #[test]
    fn equals_a_direct_convolution() {
        for (len, b) in [
            (1usize, 4usize),
            (5, 4),
            (17, 4),
            (64, 8),
            (1000, 16),
            (333, 64),
        ] {
            let h = noise(len, 7 + len as u64);
            let x = noise(700, 3);
            let mut c = Convolver::new(&h, b);
            let y: Vec<f64> = x.iter().map(|&v| c.push(v)).collect();
            let want = direct(&h, &x);
            let err = y
                .iter()
                .zip(&want)
                .map(|(a, b)| (a - b).abs())
                .fold(0.0, f64::max);
            let peak = want.iter().fold(0.0f64, |m, v| m.max(v.abs()));
            assert!(err <= 1e-12 * peak.max(1.0), "len {len} b {b}: {err}");
        }
    }

    #[test]
    fn is_strictly_causal() {
        let mut h = vec![0.0; 50];
        h[0] = 1.0; // ignored
        h[1] = 0.5;
        h[30] = 0.25;
        let mut c = Convolver::new(&h, 8);
        let mut x = vec![0.0; 40];
        x[0] = 1.0;
        let y: Vec<f64> = x.iter().map(|&v| c.push(v)).collect();
        // y[n + 1] at index n: the impulse's echo at 1 and 30.
        assert!((y[0] - 0.5).abs() < 1e-15);
        assert!((y[29] - 0.25).abs() < 1e-12);
        let others: f64 = y
            .iter()
            .enumerate()
            .filter(|(i, _)| *i != 0 && *i != 29)
            .map(|(_, v)| v.abs())
            .sum();
        assert!(others < 1e-12, "{others}");
    }
}
