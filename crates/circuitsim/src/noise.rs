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

/// Tube shot noise as R_eq = SHOT_BETA / gm at SHOT_T0_K; a pentode's partition factor
/// (`varimu/devices/noise.py` has the sources).
pub const SHOT_BETA: f64 = 2.5;
pub const SHOT_T0_K: f64 = 290.0;
pub const PARTITION: f64 = 8.0;
/// A circuit's `noise` block defaults: the resistors' temperature (K) and flicker's K_f
/// (V^2).
pub const RESISTOR_T_K: f64 = 313.0;
pub const FLICKER_V2: f64 = 2.5e-14;
/// Mains wander: nominal rms, the low-pass corner, the shared stream's name.
pub const MAINS_RMS: f64 = 0.005;
pub const MAINS_F_HI_HZ: f64 = 2.0;
pub const MAINS_STREAM_NAME: &str = "MAINS";

/// m = mains_scale(rms) times the low-passed unit flicker (Python's `mains_scale`).
pub fn mains_scale(rms: f64) -> f64 {
    rms / ((MAINS_F_HI_HZ / F_LO_HZ).ln() + 1.0).sqrt()
}

/// The mains wander's one-pole low-pass: y += alpha (x - y).
pub fn mains_alpha(rate_hz: f64) -> f64 {
    1.0 - (-2.0 * std::f64::consts::PI * MAINS_F_HI_HZ / rate_hz).exp()
}

/// 4 k T0 beta: a triode's plate noise density per siemens of gm (A^2/Hz/S), as Python's
/// `shot_k()` computes it.
pub fn shot_k() -> f64 {
    4.0 * K_B * SHOT_T0_K * SHOT_BETA
}

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

// --- A run's noise sources -----------------------------------------------------------

/// A stream's samples, white or flicker, and the window of them around the current
/// engine sample: `vals[i]` is grid sample `start + i`.
#[derive(Debug, Clone)]
struct Stream {
    white: Normals,
    flicker: Option<Flicker>,
    /// A one-pole low-pass after it (the mains wander): (alpha, its output so far).
    lowpass: Option<(f64, Option<f64>)>,
    start: u64,
    vals: Vec<f64>,
}

impl Stream {
    fn new(white: Normals, flicker: Option<Flicker>) -> Stream {
        Stream {
            white,
            flicker,
            lowpass: None,
            start: 0,
            vals: Vec::new(),
        }
    }

    fn next(&mut self, filter: Option<&FlickerFilter>) -> f64 {
        let x = match (&mut self.flicker, filter) {
            (Some(f), Some(filter)) => f.next(filter),
            _ => self.white.next(),
        };
        match &mut self.lowpass {
            None => x,
            // Starting at the first sample, as Python's `mains_wander`.
            Some((a, y)) => *y.insert(match *y {
                None => x,
                Some(prev) => prev + *a * (x - prev),
            }),
        }
    }

    /// Hold samples `k0 .. k0 + w` (the run only moves forward).
    fn seek(&mut self, k0: u64, w: usize, filter: Option<&FlickerFilter>) {
        while self.start < k0 {
            // Sample `start` is the window's first, or (window empty) the generator's next.
            if self.vals.is_empty() {
                self.next(filter);
            } else {
                self.vals.remove(0);
            }
            self.start += 1;
        }
        while self.vals.len() < w {
            let x = self.next(filter);
            self.vals.push(x);
        }
    }

    /// Linear between the window's samples at `local` (grid samples past its start).
    fn at(&self, local: f64) -> f64 {
        let i = (local.floor() as usize).min(self.vals.len() - 2);
        let frac = local - i as f64;
        self.vals[i] + frac * (self.vals[i + 1] - self.vals[i])
    }
}

// One Vec of them per run, built once: the variants' sizes don't matter.
#[allow(clippy::large_enum_variant)]
#[derive(Debug, Clone)]
enum Source {
    /// A white current (a resistor's Johnson noise) of sample deviation `sigma`.
    White {
        name: String,
        col: usize,
        sigma: f64,
        z: Stream,
    },
    /// A tube's noise (`ir::TubeNoise`): plate column `col`, grid column `col + 1`.
    Tube {
        name: String,
        col: usize,
        device: usize,
        /// This tube's share of the device instance (1 / the bank it is merged into).
        share: f64,
        /// Port of the control grid (triode 1, pentode 2).
        grid_port: usize,
        shot_k: f64,
        partition: f64,
        flicker_rt: f64,
        shot: Stream,
        grid: Stream,
        flicker: Stream,
        /// From the last accepted step: deviations of the shot streams, and gm.
        sig_shot: f64,
        sig_grid: f64,
        gm: f64,
    },
}

/// What [`NoiseRun::new`] takes per source.
#[derive(Debug, Clone)]
pub enum NoiseSpec {
    White {
        name: String,
        psd_a2_hz: f64,
    },
    Tube {
        name: String,
        device: usize,
        share: f64,
        grid_port: usize,
        shot_k: f64,
        partition: f64,
        flicker_v2: f64,
    },
}

/// A run's noise sources (B5), as current columns of the circuit: a resistor's one
/// (its two nodes), a tube's two (plate to cathode, control grid to cathode). The
/// columns' values at a stage come from the streams' grid samples, linear between them,
/// and for tubes the gm and currents of the last accepted step ([`NoiseRun::observe`]).
#[derive(Debug, Clone)]
pub struct NoiseRun {
    pub seed: u64,
    pub rate_hz: f64,
    /// Each column: (pos, neg) unknowns, the current flowing from pos through the
    /// source to neg (`None` = ground).
    pub columns: Vec<(Option<usize>, Option<usize>)>,
    sources: Vec<Source>,
    filter: Option<FlickerFilter>,
    /// The mains wander: its stream (m before scaling), scale, and the sine sources it
    /// multiplies (indices into `Mna::waves`).
    mains: Option<(Stream, f64, Vec<usize>)>,
    /// Grid samples per engine sample: p / q, one of them 1 ([`NoiseRun::set_step`]).
    p: u64,
    q: u64,
    /// The current engine sample's first grid sample, and n p - k0 q.
    k0: u64,
    rem: u64,
}

impl NoiseRun {
    /// Sources in IR order; `columns` as [`NoiseRun::columns`], a white source's one,
    /// then a tube's two, in the same order. `mains`: the wander's rms and the sine
    /// sources it multiplies (indices into `Mna::waves`; none: no wander).
    pub fn new(
        seed: u64,
        rate_hz: f64,
        specs: Vec<NoiseSpec>,
        columns: Vec<(Option<usize>, Option<usize>)>,
        mains: Option<(f64, Vec<usize>)>,
    ) -> NoiseRun {
        let tubes = specs.iter().any(|s| matches!(s, NoiseSpec::Tube { .. }));
        let filter = (tubes || mains.is_some()).then(|| FlickerFilter::new(rate_hz));
        let mains = mains.map(|(rms, waves)| {
            let f = filter.as_ref().expect("made with a mains wander");
            let mut s = Stream::new(
                Normals::new(key(seed, MAINS_STREAM_NAME, STREAM_FLICKER), 0),
                Some(Flicker::new(
                    f,
                    key(seed, MAINS_STREAM_NAME, STREAM_FLICKER),
                    key(seed, MAINS_STREAM_NAME, STREAM_FLICKER_START),
                )),
            );
            s.lowpass = Some((mains_alpha(rate_hz), None));
            (s, mains_scale(rms), waves)
        });
        let mut sources = Vec::with_capacity(specs.len());
        let mut col = 0;
        for s in specs {
            match s {
                NoiseSpec::White { name, psd_a2_hz } => {
                    let k = key(seed, &name, STREAM_MAIN);
                    sources.push(Source::White {
                        sigma: white_sigma(psd_a2_hz, rate_hz),
                        z: Stream::new(Normals::new(k, 0), None),
                        name,
                        col,
                    });
                    col += 1;
                }
                NoiseSpec::Tube {
                    name,
                    device,
                    share,
                    grid_port,
                    shot_k,
                    partition,
                    flicker_v2,
                } => {
                    let white =
                        |stream| Stream::new(Normals::new(key(seed, &name, stream), 0), None);
                    let flick = Flicker::new(
                        filter.as_ref().expect("made when there are tubes"),
                        key(seed, &name, STREAM_FLICKER),
                        key(seed, &name, STREAM_FLICKER_START),
                    );
                    sources.push(Source::Tube {
                        shot: white(STREAM_MAIN),
                        grid: white(STREAM_GRID),
                        flicker: Stream::new(
                            Normals::new(key(seed, &name, STREAM_FLICKER), 0),
                            Some(flick),
                        ),
                        name,
                        col,
                        device,
                        share,
                        grid_port,
                        shot_k,
                        partition,
                        flicker_rt: flicker_v2.sqrt(),
                        sig_shot: 0.0,
                        sig_grid: 0.0,
                        gm: 0.0,
                    });
                    col += 2;
                }
            }
        }
        assert_eq!(
            col,
            columns.len(),
            "a column per white source, two per tube"
        );
        NoiseRun {
            seed,
            rate_hz,
            columns,
            sources,
            filter,
            mains,
            p: 1,
            q: 1,
            k0: 0,
            rem: 0,
        }
    }

    /// The engine's step `h` (one sample): grid samples per engine sample must be an
    /// integer or one over an integer (draft-1x: 2; production at 2x: 1/2).
    pub fn set_step(&mut self, h: f64) -> Result<(), String> {
        let r = self.rate_hz * h;
        let near = |x: f64| (x - x.round()).abs() <= 1e-9 * x && x.round() >= 1.0;
        if r >= 1.0 && near(r) {
            (self.p, self.q) = (r.round() as u64, 1);
        } else if r < 1.0 && near(1.0 / r) {
            (self.p, self.q) = (1, (1.0 / r).round() as u64);
        } else {
            return Err(format!(
                "noise: the engine's rate {} Hz isn't an integer multiple or fraction of the \
                 noise grid's {} Hz",
                1.0 / h,
                self.rate_hz
            ));
        }
        Ok(())
    }

    /// Before engine sample `n`: the streams' windows over its grid samples.
    pub fn begin_sample(&mut self, n: u64) {
        let (p, q) = (self.p, self.q);
        self.k0 = n * p / q;
        self.rem = n * p - self.k0 * q;
        let w = p as usize + 1;
        let (k0, f) = (self.k0, self.filter.as_ref());
        if let Some((m, _, _)) = &mut self.mains {
            m.seek(k0, w, f);
        }
        for s in &mut self.sources {
            match s {
                Source::White { z, .. } => z.seek(k0, w, f),
                Source::Tube {
                    shot,
                    grid,
                    flicker,
                    ..
                } => {
                    shot.seek(k0, w, None);
                    grid.seek(k0, w, None);
                    flicker.seek(k0, w, f);
                }
            }
        }
    }

    /// The columns' values at step fraction `theta` of the current engine sample.
    pub fn fill(&self, theta: f64, out: &mut [f64]) {
        let local = (self.rem as f64 + theta * self.p as f64) / self.q as f64;
        for s in &self.sources {
            match s {
                Source::White { col, sigma, z, .. } => out[*col] = sigma * z.at(local),
                Source::Tube {
                    col,
                    flicker_rt,
                    shot,
                    grid,
                    flicker,
                    sig_shot,
                    sig_grid,
                    gm,
                    ..
                } => {
                    out[*col] = sig_shot * shot.at(local) + gm * flicker_rt * flicker.at(local);
                    out[*col + 1] = sig_grid * grid.at(local);
                }
            }
        }
    }

    /// The mains wander at step fraction `theta`: multiply the mains' sine values
    /// (`waves`, one per `Mna::waves`, the sinusoidal part only) by 1 + m.
    pub fn modulate_waves(&self, theta: f64, waves: &mut [f64]) {
        if let Some((m, scale, idx)) = &self.mains {
            let local = (self.rem as f64 + theta * self.p as f64) / self.q as f64;
            let g = 1.0 + scale * m.at(local);
            for &i in idx {
                waves[i] *= g;
            }
        }
    }

    /// Add the columns' values `vals` to a right-hand side (KCL rows).
    pub fn add_to(&self, vals: &[f64], rhs: &mut [f64]) {
        for (&(pos, neg), &v) in self.columns.iter().zip(vals) {
            if let Some(i) = pos {
                rhs[i] -= v;
            }
            if let Some(j) = neg {
                rhs[j] += v;
            }
        }
    }

    /// Take the tubes' gm and currents at the accepted point: `ports` is every
    /// device's port voltages, device by device (`port_offsets[d]` its first).
    pub fn observe(
        &mut self,
        devices: &[crate::mna::DeviceInstance],
        port_offsets: &[usize],
        ports: &[f64],
    ) {
        let rate = self.rate_hz;
        let (mut i, mut g) = ([0.0; 4], [0.0; 16]);
        for s in &mut self.sources {
            let Source::Tube {
                device,
                share,
                grid_port,
                shot_k,
                partition,
                sig_shot,
                sig_grid,
                gm,
                ..
            } = s
            else {
                continue;
            };
            let d = &devices[*device];
            let np = d.device.ports();
            let off = port_offsets[*device];
            d.device
                .eval(&ports[off..off + np], &mut i[..np], &mut g[..np * np]);
            // Port 0 is the plate; gm is d Ip / d V(control grid).
            let gm_t = (g[*grid_port] * *share).max(0.0);
            let psd = if *partition > 0.0 {
                let (ib, ic2) = ((i[0] * *share).max(0.0), (i[1] * *share).max(0.0));
                if ib + ic2 > 0.0 {
                    ib / (ib + ic2) * *shot_k * (gm_t + *partition * ic2)
                } else {
                    0.0
                }
            } else {
                *shot_k * gm_t
            };
            *gm = gm_t;
            *sig_shot = white_sigma(psd, rate);
            *sig_grid = white_sigma(2.0 * Q_E * (i[*grid_port] * *share).abs(), rate);
        }
    }

    /// Carry the streams and the tubes' last readings over from `old` (a parameter
    /// change rebuilds the circuit), by source name.
    pub fn carry(&mut self, old: &NoiseRun) {
        (self.p, self.q, self.k0, self.rem) = (old.p, old.q, old.k0, old.rem);
        if let (Some((m, _, _)), Some((om, _, _))) = (&mut self.mains, &old.mains) {
            *m = om.clone();
        }
        for s in &mut self.sources {
            for o in &old.sources {
                match (&mut *s, o) {
                    (
                        Source::White { name, z, .. },
                        Source::White {
                            name: on, z: oz, ..
                        },
                    ) if name == on => {
                        *z = oz.clone();
                    }
                    (
                        Source::Tube {
                            name,
                            shot,
                            grid,
                            flicker,
                            sig_shot,
                            sig_grid,
                            gm,
                            ..
                        },
                        Source::Tube {
                            name: on,
                            shot: os,
                            grid: og,
                            flicker: of,
                            sig_shot: oss,
                            sig_grid: osg,
                            gm: ogm,
                            ..
                        },
                    ) if name == on => {
                        (*shot, *grid, *flicker) = (os.clone(), og.clone(), of.clone());
                        (*sig_shot, *sig_grid, *gm) = (*oss, *osg, *ogm);
                    }
                    _ => {}
                }
            }
        }
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
