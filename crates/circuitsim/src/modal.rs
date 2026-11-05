//! Impulse responses of linear media as sums of damped modes (a plate, `crate::plate`; a
//! spring tank, `crate::spring`), and the convolving medium that plays one beside a
//! transient.
//!
//! A mode's share of the response is `ca Re z^k + cb Im z^k` with `z = exp((-s + i wd)
//! T)`, from sample 0 until its own length. [`sum`] adds the modes up in fixed time
//! segments on every core, each segment's start taken in closed form, so the result is the
//! same bit for bit on any number of threads.

use std::sync::Mutex;
use std::sync::atomic::{AtomicUsize, Ordering};

/// One mode's terms: its amplitude decay rate `decay` (1/s), damped angular frequency `wd`,
/// the cosine and sine coefficients and how many samples it sounds.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Term {
    pub decay: f64,
    pub wd: f64,
    pub ca: f64,
    pub cb: f64,
    pub len: usize,
}

/// Samples per segment of the parallel computation (fixed: the result doesn't depend on
/// the threads).
const SEGMENT: usize = 1 << 14;

/// `len` samples of the sum of `terms` (sorted longest first) at step `t`.
pub fn sum(terms: &[Term], len: usize, t: f64) -> Vec<f64> {
    let mut h = vec![0.0; len];
    let n_seg = len.div_ceil(SEGMENT);
    let next = AtomicUsize::new(0);
    let threads = std::thread::available_parallelism()
        .map_or(1, |n| n.get())
        .clamp(1, 16);
    let lens: Vec<usize> = terms.iter().map(|m| m.len).collect();
    let chunks: Vec<(usize, &mut [f64])> = h.chunks_mut(SEGMENT).enumerate().collect();
    let chunks = Mutex::new(chunks.into_iter().map(Some).collect::<Vec<_>>());
    std::thread::scope(|scope| {
        for _ in 0..threads {
            scope.spawn(|| {
                loop {
                    let i = next.fetch_add(1, Ordering::Relaxed);
                    if i >= n_seg {
                        break;
                    }
                    let (s, out) = chunks.lock().expect("chunks")[i].take().expect("a segment");
                    segment(terms, &lens, s * SEGMENT, t, out);
                }
            });
        }
    });
    h
}

/// Samples `k0 .. k0 + out.len()` of the sum: every mode still sounding there.
fn segment(terms: &[Term], lens: &[usize], k0: usize, t: f64, out: &mut [f64]) {
    // Terms are sorted longest first: the ones sounding at k0 are a prefix.
    let active = lens.partition_point(|&l| l > k0);
    const LANES: usize = 8;
    let mut i = 0;
    while i < active {
        let n = (active - i).min(LANES);
        let mut zr = [0.0; LANES];
        let mut zi = [0.0; LANES];
        let mut rr = [1.0; LANES];
        let mut ri = [0.0; LANES];
        let mut ca = [0.0; LANES];
        let mut cb = [0.0; LANES];
        // Where each lane stops (longest first: a lane's end is at most the one's before).
        let mut ends = [0usize; LANES];
        for j in 0..n {
            let m = terms[i + j];
            // z = exp((-s + i wd) k T): its value at k0 in closed form, the step's
            // rotation r.
            let mag = (-m.decay * k0 as f64 * t).exp();
            let ph = m.wd * k0 as f64 * t;
            zr[j] = mag * ph.cos();
            zi[j] = mag * ph.sin();
            let rm = (-m.decay * t).exp();
            rr[j] = rm * (m.wd * t).cos();
            ri[j] = rm * (m.wd * t).sin();
            ca[j] = m.ca;
            cb[j] = m.cb;
            ends[j] = lens[i + j].saturating_sub(k0).min(out.len());
        }
        // Run up to each lane's end in turn, the shortest lane dropping out at its end.
        let mut start = 0;
        for cut in (0..n).rev() {
            let stop = ends[cut];
            for o in out.iter_mut().take(stop).skip(start) {
                let mut acc = 0.0;
                for j in 0..LANES {
                    acc += ca[j] * zr[j] + cb[j] * zi[j];
                    let (a, b) = (zr[j], zi[j]);
                    zr[j] = a * rr[j] - b * ri[j];
                    zi[j] = a * ri[j] + b * rr[j];
                }
                *o += acc;
            }
            start = start.max(stop);
            ca[cut] = 0.0;
            cb[cut] = 0.0;
        }
        i += n;
    }
}

/// How many samples a mode of amplitude decay rate `decay` sounds at `fs` until it has
/// decayed by `tail_db` (unbounded without decay).
pub fn mode_len(decay: f64, tail_db: f64, fs: f64) -> usize {
    let ln_tail = tail_db.abs() / 20.0 * std::f64::consts::LN_10;
    if decay > 0.0 {
        ((ln_tail / decay) * fs).ceil() as usize + 1
    } else {
        usize::MAX
    }
}

/// A linear medium running beside a transient by its impulse response: the sense scaled
/// in, the response's next sample out (strictly causal, zero latency). A response that
/// changes (a knob) starts a new convolution; the old one keeps ringing out on silence,
/// as the medium's energy would.
pub struct Convolving {
    conv: crate::convolve::Convolver,
    old: Option<(crate::convolve::Convolver, usize)>,
    len: usize,
}

impl std::fmt::Debug for Convolving {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Convolving")
            .field("len", &self.len)
            .field("ringing_out", &self.old.is_some())
            .finish()
    }
}

/// The convolution's block at `fs`: 256 samples at 48 kHz, doubling with the rate.
pub fn block(fs: f64) -> usize {
    ((256.0 * fs / 48_000.0).round() as usize)
        .next_power_of_two()
        .clamp(64, 4096)
}

impl Convolving {
    pub fn new(h: &[f64], fs: f64) -> Convolving {
        Convolving {
            conv: crate::convolve::Convolver::new(h, block(fs)),
            old: None,
            len: h.len(),
        }
    }

    /// The response's next sample once `x` is in.
    pub fn push(&mut self, x: f64) -> f64 {
        let mut y = self.conv.push(x);
        if let Some((c, left)) = &mut self.old {
            y += c.push(0.0);
            *left -= 1;
            if *left == 0 {
                self.old = None;
            }
        }
        y
    }

    /// Another response takes the input from now on; the current one rings out.
    pub fn replace(&mut self, h: &[f64], fs: f64) {
        let new = crate::convolve::Convolver::new(h, block(fs));
        let old = std::mem::replace(&mut self.conv, new);
        self.old = Some((old, self.len));
        self.len = h.len();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_sum_is_its_terms_and_the_same_on_any_threads() {
        let t = 1.0 / 8000.0;
        let terms: Vec<Term> = (0..40)
            .map(|i| Term {
                decay: 3.0 + i as f64,
                wd: 600.0 + 97.0 * i as f64,
                ca: 1.0 / (1.0 + i as f64),
                cb: -0.5,
                len: 40_000 - 700 * i,
            })
            .collect();
        let h = sum(&terms, 40_000, t);
        for k in [0usize, 5, 16_383, 16_384, 39_999] {
            let tk = k as f64 * t;
            let want: f64 = terms
                .iter()
                .filter(|m| k < m.len)
                .map(|m| {
                    (-m.decay * tk).exp() * (m.ca * (m.wd * tk).cos() + m.cb * (m.wd * tk).sin())
                })
                .sum();
            assert!((h[k] - want).abs() < 1e-9, "k {k}: {} vs {want}", h[k]);
        }
        assert_eq!(h, sum(&terms, 40_000, t));
    }
}
