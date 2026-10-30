//! Noise streams (device builder B5): a compiled port of `varimu/devices/noise.py`, the
//! Python reference (its docstring has the definitions; `tests/noise.rs` checks this port
//! against fixtures exported from it).
//!
//! A source's samples are unit normals from Philox4x64-10 (numpy's `np.random.Philox`)
//! under the key (seed, crc32(name) << 32 | stream): sample `k` is a pure function of the
//! key and `k`, so any block can be generated on its own. The raw words equal numpy's bit
//! for bit; the normals (Box-Muller: `ln`, `cos`, `sin`) agree to the last bits of libm.
//! Flicker is the unit stream through [`FlickerFilter`], which starts in its stationary
//! state.

/// Boltzmann's constant (J/K) and the elementary charge (C), CODATA 2018 (exact).
pub const K_B: f64 = 1.380649e-23;
pub const Q_E: f64 = 1.602176634e-19;

/// The streams of one source (the low word of its key's second half).
pub const STREAM_MAIN: u32 = 0;
pub const STREAM_GRID: u32 = 1;
pub const STREAM_FLICKER: u32 = 2;
pub const STREAM_FLICKER_START: u32 = 3;

/// The flicker filter's lowest corner (flat below) and its number of sections.
pub const F_LO_HZ: f64 = 1e-3;
pub const FLICKER_SECTIONS: usize = 15;

const M0: u64 = 0xD2E7_470E_E14C_6C93;
const M1: u64 = 0xCA5A_8263_9512_1157;
const W0: u64 = 0x9E37_79B9_7F4A_7C15;
const W1: u64 = 0xBB67_AE85_84CA_A73B;

/// Philox4x64-10 of `counter` (its low word; the rest zero) under `key`.
pub fn philox(counter: u64, key: [u64; 2]) -> [u64; 4] {
    let mut c = [counter, 0, 0, 0];
    let [mut k0, mut k1] = key;
    for _ in 0..10 {
        let p0 = u128::from(M0) * u128::from(c[0]);
        let p1 = u128::from(M1) * u128::from(c[2]);
        let (hi0, lo0) = ((p0 >> 64) as u64, p0 as u64);
        let (hi1, lo1) = ((p1 >> 64) as u64, p1 as u64);
        c = [hi1 ^ c[1] ^ k0, lo1, hi0 ^ c[3] ^ k1, lo0];
        k0 = k0.wrapping_add(W0);
        k1 = k1.wrapping_add(W1);
    }
    c
}

/// zlib's CRC-32 (Python's `zlib.crc32`).
pub fn crc32(bytes: &[u8]) -> u32 {
    let mut crc = !0u32;
    for &b in bytes {
        crc ^= u32::from(b);
        for _ in 0..8 {
            crc = if crc & 1 != 0 {
                (crc >> 1) ^ 0xEDB8_8320
            } else {
                crc >> 1
            };
        }
    }
    !crc
}

/// The key of `name`'s `stream` under `seed`.
pub fn key(seed: u64, name: &str, stream: u32) -> [u64; 2] {
    [
        seed,
        (u64::from(crc32(name.as_bytes())) << 32) | u64::from(stream),
    ]
}

/// The four normals of block `b` (samples 4b .. 4b + 4): numpy's fresh `Philox(key)`
/// emits that block's words `b`-th, i.e. at counter b + 1.
pub fn block(key: [u64; 2], b: u64) -> [f64; 4] {
    let w = philox(b.wrapping_add(1), key);
    let mut z = [0.0; 4];
    for p in 0..2 {
        let u1 = ((w[2 * p] >> 11) + 1) as f64 * (1.0 / 9_007_199_254_740_992.0);
        let u2 = (w[2 * p + 1] >> 11) as f64 * (1.0 / 9_007_199_254_740_992.0);
        let r = (-2.0 * u1.ln()).sqrt();
        let t = 2.0 * std::f64::consts::PI * u2;
        z[2 * p] = r * t.cos();
        z[2 * p + 1] = r * t.sin();
    }
    z
}

/// Unit normals `start .. start + out.len()` of the stream with key `key`.
pub fn normals(key: [u64; 2], start: u64, out: &mut [f64]) {
    let mut k = start;
    let mut i = 0;
    while i < out.len() {
        let z = block(key, k / 4);
        let o = (k % 4) as usize;
        let take = (4 - o).min(out.len() - i);
        out[i..i + take].copy_from_slice(&z[o..o + take]);
        i += take;
        k += take as u64;
    }
}

/// A stream's samples one after another, a block of four at a time.
#[derive(Debug, Clone)]
pub struct Normals {
    key: [u64; 2],
    next: u64,
    buf: [f64; 4],
}

impl Normals {
    /// The stream with key `key`, from sample `start`.
    pub fn new(key: [u64; 2], start: u64) -> Normals {
        Normals {
            key,
            next: start,
            buf: block(key, start / 4),
        }
    }

    /// The index of the sample [`Normals::next`] returns next.
    pub fn position(&self) -> u64 {
        self.next
    }

    #[allow(clippy::should_implement_trait)]
    pub fn next(&mut self) -> f64 {
        let o = (self.next % 4) as usize;
        if o == 0 && self.next > 0 {
            self.buf = block(self.key, self.next / 4);
        }
        // A stream started mid-block filled its buffer in `new`.
        let z = self.buf[o];
        self.next += 1;
        z
    }
}

/// White sample deviation of one-sided density `psd` on a grid of `rate_hz`.
pub fn white_sigma(psd: f64, rate_hz: f64) -> f64 {
    (psd * rate_hz / 2.0).sqrt()
}

/// Unit white noise to unit flicker (one-sided density 1/f): see `FlickerFilter` in
/// `varimu/devices/noise.py`, same order of operations.
#[derive(Debug, Clone)]
pub struct FlickerFilter {
    pub poles: Vec<f64>,
    pub residues: Vec<f64>,
    pub direct: f64,
    pub gain: f64,
    /// Lower Cholesky factor of the stationary state covariance, row-major n x n.
    pub start_chol: Vec<f64>,
}

impl FlickerFilter {
    pub fn design(rate_hz: f64, f_lo_hz: f64, n: usize) -> FlickerFilter {
        let r = 10f64.powf(0.25);
        let fp: Vec<f64> = (0..n).map(|i| f_lo_hz * r.powi(2 * i as i32)).collect();
        let fz: Vec<f64> = fp.iter().map(|f| f * r).collect();
        let tanw = |f: f64| (std::f64::consts::PI * f / rate_hz).tan();
        let wp: Vec<f64> = fp.iter().map(|&f| tanw(f)).collect();
        let wz: Vec<f64> = fz.iter().map(|&f| tanw(f)).collect();
        let ep: Vec<f64> = wp.iter().map(|w| 2.0 * w / (1.0 + w)).collect();
        let ez: Vec<f64> = wz.iter().map(|w| 2.0 * w / (1.0 + w)).collect();
        let mut g = 1.0;
        for (a, b) in wp.iter().zip(&wz) {
            g *= (a / b) * (b + 1.0) / (a + 1.0);
        }
        let mut d = g;
        for (a, b) in ep.iter().zip(&ez) {
            d *= (1.0 - b) / (1.0 - a);
        }
        let mut residues = Vec::with_capacity(n);
        for i in 0..n {
            let (mut num, mut den) = (g, 1.0 - ep[i]);
            for j in 0..n {
                num *= ez[j] - ep[i];
                if j != i {
                    den *= ep[j] - ep[i];
                }
            }
            residues.push(num / den);
        }
        let mut acc = 0.0;
        for k in 0..64 {
            let f = 10f64.powf(k as f64 / 128.0);
            let mut h2 = 1.0;
            for (a, b) in fp.iter().zip(&fz) {
                h2 *= (1.0 + (f / b).powi(2)) / (1.0 + (f / a).powi(2));
            }
            acc += (f * h2).ln();
        }
        let level = (acc / 64.0).exp();
        let gain = (rate_hz / (2.0 * level)).sqrt();
        let mut cov = vec![0.0; n * n];
        for i in 0..n {
            for j in 0..n {
                cov[i * n + j] = residues[i] * residues[j] / (ep[i] + ep[j] - ep[i] * ep[j]);
            }
        }
        FlickerFilter {
            poles: ep.iter().map(|e| 1.0 - e).collect(),
            residues,
            direct: d,
            gain,
            start_chol: cholesky(&cov, n),
        }
    }

    /// The default filter on a grid of `rate_hz`.
    pub fn new(rate_hz: f64) -> FlickerFilter {
        FlickerFilter::design(rate_hz, F_LO_HZ, FLICKER_SECTIONS)
    }
}

fn cholesky(a: &[f64], n: usize) -> Vec<f64> {
    let mut lo = vec![0.0; n * n];
    for i in 0..n {
        for j in 0..=i {
            let mut s = a[i * n + j];
            for k in 0..j {
                s -= lo[i * n + k] * lo[j * n + k];
            }
            if i == j {
                lo[i * n + i] = if s > 0.0 { s.sqrt() } else { 0.0 };
            } else {
                lo[i * n + j] = if lo[j * n + j] > 0.0 {
                    s / lo[j * n + j]
                } else {
                    0.0
                };
            }
        }
    }
    lo
}

/// A running flicker stream: unit flicker from sample 0, stationary from the start.
#[derive(Debug, Clone)]
pub struct Flicker {
    input: Normals,
    state: Vec<f64>,
}

impl Flicker {
    /// The stream whose input is `key` and whose start is drawn from `start_key`.
    pub fn new(filter: &FlickerFilter, key: [u64; 2], start_key: [u64; 2]) -> Flicker {
        let n = filter.poles.len();
        let mut z0 = vec![0.0; n];
        normals(start_key, 0, &mut z0);
        let state = (0..n)
            .map(|i| {
                let mut s = 0.0;
                for (j, z) in z0.iter().enumerate().take(i + 1) {
                    s += filter.start_chol[i * n + j] * z;
                }
                s
            })
            .collect();
        Flicker {
            input: Normals::new(key, 0),
            state,
        }
    }

    /// The next sample (sample 0 first).
    #[allow(clippy::should_implement_trait)]
    pub fn next(&mut self, filter: &FlickerFilter) -> f64 {
        let x = self.input.next();
        let mut y = filter.direct * x;
        for ((s, p), r) in self
            .state
            .iter_mut()
            .zip(&filter.poles)
            .zip(&filter.residues)
        {
            *s = p * *s + r * x;
            y += *s;
        }
        filter.gain * y
    }

    /// The index of the sample [`Flicker::next`] returns next.
    pub fn position(&self) -> u64 {
        self.input.position()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn philox_known_answer() {
        // Random123's known-answer test for Philox4x64-10, counter 0 and key 0.
        assert_eq!(
            philox(0, [0, 0]),
            [
                0x1655_4d9e_ca36_314c,
                0xdb20_fe9d_672d_0fdc,
                0xd7e7_72ce_e186_176b,
                0x7e68_b68a_ec7b_a23b
            ]
        );
    }

    #[test]
    fn crc32_matches_zlib() {
        assert_eq!(crc32(b""), 0);
        assert_eq!(crc32(b"123456789"), 0xCBF4_3926);
    }

    #[test]
    fn a_stream_is_the_same_from_any_start() {
        let k = key(7, "IN_R1", STREAM_MAIN);
        let mut all = vec![0.0; 40];
        normals(k, 0, &mut all);
        for start in [0u64, 1, 3, 4, 5, 17] {
            let mut part = vec![0.0; 13];
            normals(k, start, &mut part);
            assert_eq!(part[..], all[start as usize..start as usize + 13]);
            let mut s = Normals::new(k, start);
            for (i, z) in part.iter().enumerate() {
                assert_eq!(s.next(), *z, "start {start}, {i}");
            }
        }
    }
}
