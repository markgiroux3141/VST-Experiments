//! Magnetic tape between the heads, sample by sample (docs/TAPE_PLAN.md, TM4): the port of
//! `varimu.devices.tape_machine.TapeStream`, the medium the IR element `Tape` runs. The
//! two agree within rounding (`tests/test_tape_stream.py`); the steps below mirror the
//! reference's, in its order of operations.
//!
//! [`TapeStream::push`] takes the record gap's signal field at t_n = n / fs (deep-gap
//! A/m; the AC bias is added inside) and returns the repro coil's EMF at t_{n+1}: the tape
//! read was recorded long before (the heads ~2" apart), so the medium never waits on the
//! circuit. Tape is recorded in blocks (`varimu.devices.tape.record_demagnetized_vector`:
//! the recording kernel [`crate::tape::record`] in a fixed point with the pattern's own
//! demagnetizing field, Anderson-accelerated), each block's flux slope at the repro head
//! (`varimu.devices.tape.flux_slope`) once its successor is recorded.

use std::f64::consts::PI;
use std::sync::Arc;
use std::sync::{Mutex, mpsc};
use std::thread::JoinHandle;

use rustfft::FftPlanner;
use rustfft::num_complex::Complex64;
use serde::{Deserialize, Serialize};

use crate::tape::{Head, Preisach, Recording, head_field, preisach, record};

/// Recording runs this much tape past a block's ends: well past the record zone.
const ZONE_PAD_M: f64 = 2e-3;
/// Peaks per octave of the per-cell zones' grid, and its octaves above the floor.
const ZONE_STEPS: usize = 8;
const ZONE_OCTAVES: usize = 16;
/// Sub-samples per layer of the demagnetizing kernels' layer averages.
const DEMAG_Q: usize = 16;
/// Anderson's history.
const HISTORY: usize = 6;
const MU0: f64 = 4e-7 * PI;

/// The medium's parameters (`varimu.devices.tape_machine.stream_params` writes them): the
/// tape component's particles, the machine's transport, heads and bias, the numerics.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TapeParams {
    pub hc_median_a_m: f64,
    pub sigma_ln_hc: f64,
    pub sigma_hi_a_m: f64,
    pub h_max_a_m: f64,
    #[serde(deserialize_with = "count")]
    pub n_table: usize,
    pub ms_a_m: f64,
    pub coating_m: f64,
    /// The easy axes' axial von Mises concentration and directions (`Orientation`).
    pub kappa: f64,
    #[serde(deserialize_with = "count")]
    pub orientations: usize,
    pub speed_m_s: f64,
    pub f_bias_hz: f64,
    /// The bias's deep-gap field amplitude (A/m) and its phase at t = 0.
    pub hg_bias_a_m: f64,
    pub bias_phase_rad: f64,
    pub rec_gap_m: f64,
    pub rep_gap_m: f64,
    pub pole_m: f64,
    pub relax_m: f64,
    pub spacing_m: f64,
    pub track_m: f64,
    pub head_distance_m: f64,
    /// The repro head's deep-gap field per coil ampere.
    pub rep_h_per_a: f64,
    #[serde(deserialize_with = "count")]
    pub layers: usize,
    pub ds_m: f64,
    pub table_step: f64,
    pub zone_floor_a_m: f64,
    pub local_zones: bool,
    #[serde(deserialize_with = "count")]
    pub demag_iterations: usize,
    pub demag_tol: f64,
    pub head_image: bool,
    pub lam_min_m: f64,
    pub block_m: f64,
    pub margin_m: f64,
    /// The coating's graininess (`TapeNoise`; zeros: none fitted): particle volume, the
    /// packing's volume fraction, its fluctuation's relative std and correlation length.
    /// The transport's speed components (`TapeMachineSpec.transport`): periodic
    /// (relative peak, Hz, phase) and resonances driven by white noise (relative rms,
    /// Hz, Q); none: the tape runs at speed_m_s exactly.
    pub flutter: Vec<[f64; 3]>,
    pub flutter_noise: Vec<[f64; 3]>,
    pub particle_volume_m3: f64,
    pub packing: f64,
    pub packing_sigma: f64,
    pub packing_corr_m: f64,
    /// The literal bias (TAPE_PLAN.md TM5, option A): each push is M samples of the head's
    /// whole field, bias included (`hg_bias_a_m` 0), from a multi-rate part, over
    /// (t_{n-2}, t_{n-1}] for push n (fast sample k at (k + 1 - 2M) / (M fs)); the blocks
    /// record at its extrema. None: the medium's own bias.
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "opt_count"
    )]
    pub bias_substeps: Option<usize>,
}

impl TapeParams {
    /// The checks the reference makes when it starts, for the step rate fs (None: the
    /// rate's own term left out, as the IR's validation does).
    pub fn check(&self, fs: Option<f64>) -> Result<(), String> {
        let pos = [
            self.hc_median_a_m,
            self.sigma_ln_hc,
            self.sigma_hi_a_m,
            self.h_max_a_m,
            self.ms_a_m,
            self.coating_m,
            self.speed_m_s,
            self.f_bias_hz,
            self.rec_gap_m,
            self.rep_gap_m,
            self.pole_m,
            self.track_m,
            self.ds_m,
            self.zone_floor_a_m,
            self.lam_min_m,
            self.block_m,
            fs.unwrap_or(1.0),
        ];
        if pos.iter().any(|x| !(x.is_finite() && *x > 0.0))
            || self.n_table < 4
            || self.orientations == 0
            || self.layers == 0
            || self.relax_m < 0.0
            || self.spacing_m < 0.0
            || self.margin_m < 0.0
            || self.kappa < 0.0
            || self.hg_bias_a_m < 0.0
            || self
                .bias_substeps
                .is_some_and(|m| m < 2 || self.hg_bias_a_m != 0.0)
            || self
                .flutter
                .iter()
                .any(|c| !(c[0] >= 0.0 && c[1] > 0.0 && c[2].is_finite()))
            || self.flutter_noise.iter().any(|c| {
                !(c[0] >= 0.0 && c[1] > 0.0 && c[2] > 0.0) || fs.is_some_and(|fs| c[1] >= fs / 2.0)
            })
            || self.particle_volume_m3 < 0.0
            || !(0.0..1.0).contains(&self.packing)
            || self.packing_sigma < 0.0
            || (self.packing_sigma > 0.0
                && (self.packing_corr_m <= 0.0 || self.packing_corr_m.is_nan()))
        {
            return Err("tape: a parameter is out of range".into());
        }
        let ds = self.ds_m;
        let (nb, nm, nr) = self.cells();
        if nr > nb {
            return Err("tape: the repro head's reach is longer than a block".into());
        }
        let lag =
            (2 * nb + nm) as f64 * ds + ZONE_PAD_M + fs.map_or(0.0, |fs| 4.0 * self.speed_m_s / fs);
        if self.head_distance_m <= lag {
            return Err(format!(
                "tape: the heads are too close for the blocks ({} m)",
                self.head_distance_m
            ));
        }
        Ok(())
    }

    /// Cells per block, per margin, and the repro head's reach in cells.
    fn cells(&self) -> (usize, usize, usize) {
        let ds = self.ds_m;
        let reach = 2.0 * (self.rep_gap_m / 2.0 + self.pole_m + self.relax_m);
        (
            (self.block_m / ds).round() as usize,
            (self.margin_m / ds).round() as usize,
            (reach / ds).ceil() as usize,
        )
    }
}

/// A count written as a number (the IR writes every number as a float).
fn count<'de, D: serde::Deserializer<'de>>(d: D) -> Result<usize, D::Error> {
    let x = f64::deserialize(d)?;
    if x >= 0.0 && x.fract() == 0.0 && x < 1e15 {
        Ok(x as usize)
    } else {
        Err(serde::de::Error::custom(format!("{x} isn't a count")))
    }
}

/// An optional count written as a number.
fn opt_count<'de, D: serde::Deserializer<'de>>(d: D) -> Result<Option<usize>, D::Error> {
    count(d).map(Some)
}

/// numpy's sinc: sin(pi u) / (pi u).
fn sinc(u: f64) -> f64 {
    let y = PI * if u == 0.0 { 1.0e-20 } else { u };
    y.sin() / y
}

/// `head_hx_spectrum`: the spatial spectrum of Hx / Hg at height y.
fn hx_spectrum(head: &Head, k: f64, y: f64) -> f64 {
    let (g, p, r) = (head.gap, head.pole, head.relax);
    let gap = sinc(k * g / (2.0 * PI));
    let ec = g / 2.0 + p + r / 2.0;
    let relax = if r > 0.0 {
        sinc(k * r / (2.0 * PI))
    } else {
        1.0
    };
    g * (-k.abs() * y).exp() * (gap - (k * ec).cos() * relax)
}

/// `cubic_held`: samples h (sample i at index first + i) at fractional index u, the taps
/// clamped to the samples there are.
fn cubic_held(h: &[f64], u: f64, first: i64) -> f64 {
    let i = u.floor();
    let f = u - i;
    let i = i as i64;
    let n = h.len() as i64;
    let tap = |k: i64| h[(k - first).clamp(0, n - 1) as usize];
    -f * (f - 1.0) * (f - 2.0) / 6.0 * tap(i - 1) + (f + 1.0) * (f - 1.0) * (f - 2.0) / 2.0 * tap(i)
        - (f + 1.0) * f * (f - 2.0) / 2.0 * tap(i + 1)
        + (f + 1.0) * f * (f - 1.0) / 6.0 * tap(i + 2)
}

/// scipy's `next_fast_len(n, real=True)`: the smallest 5-smooth number at or above n.
fn next_fast_len(n: usize) -> usize {
    let mut m = n.max(1);
    loop {
        let mut r = m;
        for p in [2, 3, 5] {
            while r.is_multiple_of(p) {
                r /= p;
            }
        }
        if r == 1 {
            return m;
        }
        m += 1;
    }
}

/// `zone_halfwidth_m` (vector): how far from the gap a cell at height y still sees
/// |H| >= h_min when the deep-gap field peaks at peak.
fn zone_halfwidth(head: &Head, y: f64, peak: f64, h_min: f64) -> f64 {
    if peak <= h_min {
        return 0.0;
    }
    let mag = |x: f64| {
        let (a, b) = head_field(head, x, y);
        a.hypot(b)
    };
    let (mut lo, mut hi) = (0.0, head.gap);
    while mag(hi) * peak >= h_min {
        hi *= 2.0;
        if hi > 0.5 * head.pole {
            return hi;
        }
    }
    for _ in 0..60 {
        let mid = 0.5 * (lo + hi);
        if mag(mid) * peak >= h_min {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    hi
}

/// `_zone_checked`: the zone, the far pole edges' field below the floor.
fn zone_checked(head: &Head, y: f64, peak: f64, floor: f64) -> Result<f64, String> {
    let xz = zone_halfwidth(head, y, peak, floor);
    let e = head.gap / 2.0 + head.pole + head.relax;
    let (ex, ey) = head_field(head, e, y);
    let edge = ex.hypot(ey) * peak;
    if edge >= floor {
        return Err(format!(
            "tape: the pole edges switch hysterons ({edge} >= {floor} A/m)"
        ));
    }
    Ok(xz)
}

/// The demagnetizing kernels at an n-point transform's kept wavenumbers
/// (`_demag_kernels`): per kept bin, Hx from Mx, Hx from My, Hy from Mx, Hy from My, each
/// layers x layers (row: the target layer).
struct Kernels {
    n: usize,
    image: bool,
    bins: Vec<usize>,
    k: [Vec<Complex64>; 4],
}

fn demag_kernels(p: &TapeParams, n: usize, image: Option<f64>) -> Kernels {
    let layers = p.layers;
    let q = DEMAG_Q;
    let thickness = p.coating_m;
    let freq = 1.0 / (n as f64 * p.ds_m);
    let k_cut = 2.0 * PI / p.lam_min_m;
    let bins: Vec<usize> = (0..n / 2 + 1)
        .filter(|&j| {
            let k = 2.0 * PI * (j as f64 * freq);
            k > 0.0 && k < k_cut
        })
        .collect();
    let dyl = thickness / layers as f64;
    // The sub-samples' heights as `_layer_profiles` computes them (its profiles) and as
    // `_demag_kernels` does (the faces' signs and the images).
    let dy_q = dyl / q as f64;
    let dk_q = thickness / (layers * q) as f64;
    let ll = layers * layers;
    let mut out: [Vec<Complex64>; 4] =
        std::array::from_fn(|_| vec![Complex64::new(0.0, 0.0); bins.len() * ll]);
    for (bi, &j) in bins.iter().enumerate() {
        let kc = 2.0 * PI * (j as f64 * freq);
        let kab = kc.abs();
        let sg = kc.signum();
        let ks = kc.abs().max(1e-300);
        for tl in 0..layers {
            for sl in 0..layers {
                let a = sl as f64 * dyl;
                let b = a + dyl;
                let mut acc = [Complex64::new(0.0, 0.0); 4];
                for s in 0..q {
                    let y = ((tl * q + s) as f64 + 0.5) * dy_q;
                    let yk = ((tl * q + s) as f64 + 0.5) * dk_q;
                    let ea = (-ks * (y - a).abs()).exp();
                    let eb = (-ks * (y - b).abs()).exp();
                    let (above, below) = (y < a, y > b);
                    let integ = if !(above || below) {
                        (2.0 - ea - eb) / ks
                    } else if above {
                        (ea - eb) / ks
                    } else {
                        (eb - ea) / ks
                    };
                    let deriv = if above || below { ea - eb } else { eb - ea };
                    let mut kx_x = Complex64::new(-(kab / 2.0) * integ, 0.0);
                    let mut ky_x = Complex64::new(0.0, 0.5 * sg * deriv);
                    let mut kx_y = Complex64::new(0.0, -0.5 * sg * (eb - ea));
                    let mut hy_my =
                        Complex64::new(0.5 * (signum0(yk - b) * eb - signum0(yk - a) * ea), 0.0);
                    if let Some(d) = image {
                        let d2 = 2.0 * d;
                        let ia = (-kab * (yk + d2 + a)).exp();
                        let ib = (-kab * (yk + d2 + b)).exp();
                        let jint = (ia - ib) / kab;
                        kx_x += Complex64::new((kab / 2.0) * jint, 0.0);
                        ky_x += Complex64::new(0.0, 0.5 * sg * kab * jint);
                        kx_y -= Complex64::new(0.0, 0.5 * sg * (ia - ib));
                        hy_my += Complex64::new(0.5 * (ia - ib), 0.0);
                    }
                    acc[0] += kx_x;
                    acc[1] += kx_y;
                    acc[2] += ky_x;
                    acc[3] += hy_my;
                }
                for (o, a) in out.iter_mut().zip(acc) {
                    o[bi * ll + tl * layers + sl] = a / q as f64;
                }
            }
        }
    }
    Kernels {
        n,
        image: image.is_some(),
        bins,
        k: out,
    }
}

/// numpy's sign (0 at 0).
fn signum0(x: f64) -> f64 {
    if x > 0.0 {
        1.0
    } else if x < 0.0 {
        -1.0
    } else {
        0.0
    }
}

/// numpy's rfft(x, n): the first n / 2 + 1 bins of x zero-padded to n.
fn rfft(planner: &mut FftPlanner<f64>, x: &[f64], n: usize) -> Vec<Complex64> {
    let mut buf: Vec<Complex64> = (0..n)
        .map(|i| Complex64::new(if i < x.len() { x[i] } else { 0.0 }, 0.0))
        .collect();
    planner.plan_fft_forward(n).process(&mut buf);
    buf.truncate(n / 2 + 1);
    buf
}

/// numpy's irfft(xk, n) (xk: n / 2 + 1 bins; the imaginary parts of DC and Nyquist
/// dropped), its first `keep` samples.
fn irfft(planner: &mut FftPlanner<f64>, xk: &[Complex64], n: usize, keep: usize) -> Vec<f64> {
    let mut buf = vec![Complex64::new(0.0, 0.0); n];
    buf[..xk.len()].copy_from_slice(xk);
    buf[0].im = 0.0;
    if n.is_multiple_of(2) {
        buf[n / 2].im = 0.0;
    }
    for j in 1..n.div_ceil(2) {
        buf[n - j] = buf[j].conj();
    }
    planner.plan_fft_inverse(n).process(&mut buf);
    buf[..keep].iter().map(|c| c.re / n as f64).collect()
}

/// `lstsq_mgs`: least squares by modified Gram-Schmidt in column order, a column whose
/// remainder falls below 1e-10 of its norm dropped.
fn lstsq_mgs(cols: &[Vec<f64>], b: &[f64]) -> Vec<f64> {
    let p = cols.len();
    let dot = |a: &[f64], c: &[f64]| a.iter().zip(c).map(|(x, y)| x * y).sum::<f64>();
    let mut qs: Vec<(usize, Vec<f64>)> = Vec::new();
    let mut r = vec![0.0; p * p];
    for j in 0..p {
        let mut v = cols[j].clone();
        let n0 = dot(&v, &v).sqrt();
        for (i, q) in &qs {
            let rij = dot(q, &v);
            r[i * p + j] = rij;
            for (vk, qk) in v.iter_mut().zip(q) {
                *vk -= rij * qk;
            }
        }
        let n = dot(&v, &v).sqrt();
        if n0 == 0.0 || n <= 1e-10 * n0 {
            continue;
        }
        r[j * p + j] = n;
        qs.push((j, v.iter().map(|x| x / n).collect()));
    }
    let qb: Vec<(usize, f64)> = qs.iter().map(|(i, q)| (*i, dot(q, b))).collect();
    let kept: Vec<usize> = qs.iter().map(|(i, _)| *i).collect();
    let mut c = vec![0.0; p];
    for a in (0..kept.len()).rev() {
        let i = kept[a];
        let mut s = qb[a].1;
        for &k in &kept[a + 1..] {
            s -= r[i * p + k] * c[k];
        }
        c[i] = s / r[i * p + i];
    }
    c
}

/// What recording a block reads (the stream's, shared with its worker).
#[derive(Clone)]
struct Ctx {
    p: TapeParams,
    pre: Arc<Preisach>,
    rec_head: Head,
    heights: Vec<f64>,
    axes: Vec<[f64; 3]>,
    zone_tables: Vec<Vec<f64>>,
    /// The recording kernel's threads (`Recording::threads`).
    threads: usize,
}

/// A block to record: its cells (with margins) and the field at the record gap.
struct Job {
    b: usize,
    j0: usize,
    s: Vec<f64>,
    hg: Vec<f64>,
    srec: Vec<f64>,
    peak: f64,
}

/// A recorded block: the pattern over its cells and margins (layers x cells).
struct Done {
    b: usize,
    j0: usize,
    cells: usize,
    mx: Vec<f64>,
    my: Vec<f64>,
}

/// The recording on the worker thread: its FFT plans and demagnetization kernels.
struct Recorder {
    ctx: Arc<Ctx>,
    planner: FftPlanner<f64>,
    kernels: Vec<Arc<Kernels>>,
}

impl Recorder {
    fn kernels(&mut self, n: usize, image: bool) -> Arc<Kernels> {
        if let Some(k) = self.kernels.iter().find(|k| k.n == n && k.image == image) {
            return k.clone();
        }
        let k = Arc::new(demag_kernels(
            &self.ctx.p,
            n,
            image.then_some(self.ctx.p.spacing_m),
        ));
        if self.kernels.len() > 8 {
            self.kernels.remove(0);
        }
        self.kernels.push(k.clone());
        k
    }

    /// `demag_fields_vector`: (H_x, H_y), layers x cells, of the pattern for each image.
    fn demag_fields(
        &mut self,
        mx: &[f64],
        my: &[f64],
        cells: usize,
        images: &[bool],
    ) -> Vec<(Vec<f64>, Vec<f64>)> {
        let layers = self.ctx.p.layers;
        let n = next_fast_len(2 * cells);
        let mxk: Vec<Vec<Complex64>> = (0..layers)
            .map(|l| rfft(&mut self.planner, &mx[l * cells..(l + 1) * cells], n))
            .collect();
        let myk: Vec<Vec<Complex64>> = (0..layers)
            .map(|l| rfft(&mut self.planner, &my[l * cells..(l + 1) * cells], n))
            .collect();
        let ms = self.ctx.p.ms_a_m;
        let mut out = Vec::new();
        for &image in images {
            let kern = self.kernels(n, image);
            let ll = layers * layers;
            let mut hx = Vec::with_capacity(layers * cells);
            let mut hy = Vec::with_capacity(layers * cells);
            let mut hxk = vec![vec![Complex64::new(0.0, 0.0); n / 2 + 1]; layers];
            let mut hyk = vec![vec![Complex64::new(0.0, 0.0); n / 2 + 1]; layers];
            for (bi, &j) in kern.bins.iter().enumerate() {
                for a in 0..layers {
                    let row = bi * ll + a * layers;
                    let mut sx_x = Complex64::new(0.0, 0.0);
                    let mut sx_y = Complex64::new(0.0, 0.0);
                    let mut sy_x = Complex64::new(0.0, 0.0);
                    let mut sy_y = Complex64::new(0.0, 0.0);
                    for b in 0..layers {
                        sx_x += kern.k[0][row + b] * mxk[b][j];
                        sx_y += kern.k[1][row + b] * myk[b][j];
                        sy_x += kern.k[2][row + b] * mxk[b][j];
                        sy_y += kern.k[3][row + b] * myk[b][j];
                    }
                    hxk[a][j] = sx_x + sx_y;
                    hyk[a][j] = sy_x + sy_y;
                }
            }
            for a in 0..layers {
                hx.extend(
                    irfft(&mut self.planner, &hxk[a], n, cells)
                        .iter()
                        .map(|v| ms * v),
                );
                hy.extend(
                    irfft(&mut self.planner, &hyk[a], n, cells)
                        .iter()
                        .map(|v| ms * v),
                );
            }
            out.push((hx, hy));
        }
        out
    }

    /// `record` (the vector model, explicit floor) of cells s from t0 to t1, in steady
    /// fields if given.
    #[allow(clippy::too_many_arguments)]
    fn record_once(
        &self,
        hg: &[f64],
        srec: &[f64],
        s: &[f64],
        zones: &[f64],
        h_static: Option<(&[f64], &[f64])>,
        h_end: Option<(&[f64], &[f64])>,
    ) -> (Vec<f64>, Vec<f64>) {
        record(&Recording {
            preisach: &self.ctx.pre,
            head: self.ctx.rec_head,
            heights: &self.ctx.heights,
            zones,
            s_rec: srec,
            hg,
            s_cells: s,
            axes: &self.ctx.axes,
            h_static,
            h_end,
            table_step: self.ctx.p.table_step,
            threads: self.ctx.threads,
        })
    }

    /// The zones of `record`: per layer, or per layer and cell (`_cell_zones`).
    fn zones(&self, hg: &[f64], srec: &[f64], s: &[f64], peak: f64) -> Result<Vec<f64>, String> {
        let floor = self.ctx.p.zone_floor_a_m;
        let outer = self
            .ctx
            .heights
            .iter()
            .map(|&y| zone_checked(&self.ctx.rec_head, y, peak, floor))
            .collect::<Result<Vec<f64>, String>>()?;
        if !self.ctx.p.local_zones {
            return Ok(outer);
        }
        let w = outer.iter().fold(f64::NEG_INFINITY, |a, &b| a.max(b));
        let top = ZONE_STEPS * ZONE_OCTAVES;
        let mut gi = Vec::with_capacity(s.len());
        for &sc in s {
            let k0 = srec.partition_point(|&v| v < sc - w);
            let k1 = srec.partition_point(|&v| v <= sc + w);
            let local = hg[k0..k1.max(k0)]
                .iter()
                .fold(0.0, |a: f64, &x| a.max(x.abs()));
            let u = (local.max(floor) / floor).log2() * ZONE_STEPS as f64;
            gi.push(u.ceil() as usize);
        }
        let mut zones = Vec::with_capacity(self.ctx.heights.len() * s.len());
        for (l, table) in self.ctx.zone_tables.iter().enumerate() {
            for &g in &gi {
                let z = if g > top { f64::INFINITY } else { table[g] };
                zones.push(z.min(outer[l]));
            }
        }
        Ok(zones)
    }

    /// `record_demagnetized_vector` of a block's job: the pattern over its cells and
    /// margins (layers x cells), the demagnetization's fixed point.
    fn record(&mut self, job: Job) -> Result<Done, String> {
        let Job {
            b,
            j0,
            s,
            hg,
            srec,
            peak,
        } = job;
        let zones = self.zones(&hg, &srec, &s, peak)?;
        let cells = s.len();
        let (mut mx, mut my) = self.record_once(&hg, &srec, &s, &zones, None, None);
        let mut x: Vec<f64> = mx.iter().chain(&my).copied().collect();
        let (mut xs, mut gs): (Vec<Vec<f64>>, Vec<Vec<f64>>) = (Vec::new(), Vec::new());
        let half_len = mx.len();
        for _ in 0..self.ctx.p.demag_iterations {
            let images: &[bool] = if self.ctx.p.head_image {
                &[false, true]
            } else {
                &[false]
            };
            let f = self.demag_fields(&mx, &my, cells, images);
            let (nx, ny) = if self.ctx.p.head_image {
                let (hd, hz) = (&f[0], &f[1]);
                self.record_once(
                    &hg,
                    &srec,
                    &s,
                    &zones,
                    Some((&hz.0, &hz.1)),
                    Some((&hd.0, &hd.1)),
                )
            } else {
                self.record_once(&hg, &srec, &s, &zones, Some((&f[0].0, &f[0].1)), None)
            };
            let g: Vec<f64> = nx.iter().chain(&ny).zip(&x).map(|(a, b)| a - b).collect();
            let change = g.iter().fold(0.0, |a: f64, &v| a.max(v.abs()));
            if change < self.ctx.p.demag_tol {
                mx = nx;
                my = ny;
                break;
            }
            xs.push(x.clone());
            gs.push(g.clone());
            if xs.len() > HISTORY {
                xs.remove(0);
                gs.remove(0);
            }
            if gs.len() > 1 {
                let dg: Vec<Vec<f64>> = gs
                    .windows(2)
                    .map(|w| w[1].iter().zip(&w[0]).map(|(a, b)| a - b).collect())
                    .collect();
                let dx: Vec<Vec<f64>> = xs
                    .windows(2)
                    .map(|w| w[1].iter().zip(&w[0]).map(|(a, b)| a - b).collect())
                    .collect();
                let coef = lstsq_mgs(&dg, &g);
                for ((c, a), b) in coef.iter().zip(&dx).zip(&dg) {
                    if *c != 0.0 {
                        for ((xk, ak), bk) in x.iter_mut().zip(a).zip(b) {
                            *xk -= c * (ak + bk);
                        }
                    }
                }
                for (xk, gk) in x.iter_mut().zip(&g) {
                    *xk += gk;
                }
            } else {
                for (xk, gk) in x.iter_mut().zip(&g) {
                    *xk += 0.1 * gk;
                }
            }
            for xk in x.iter_mut() {
                *xk = xk.clamp(-1.0, 1.0);
            }
            mx = x[..half_len].to_vec();
            my = x[half_len..].to_vec();
        }
        Ok(Done {
            b,
            j0,
            cells,
            mx,
            my,
        })
    }
}

/// A thread recording the stream's blocks in the order they come (each block's recording
/// is independent of the others': its margins are recorded with it), so the circuit runs
/// on while a block records (TAPE_PLAN.md, "Speed"). The results are the same numbers.
struct Worker {
    jobs: Option<mpsc::Sender<Job>>,
    // In a mutex only so the stream is Sync (Python's stream class); one thread uses it.
    done: Mutex<mpsc::Receiver<Result<Done, String>>>,
    thread: Option<JoinHandle<()>>,
}

impl Worker {
    fn spawn(ctx: Arc<Ctx>) -> Self {
        let (jobs, rx) = mpsc::channel::<Job>();
        let (tx, done) = mpsc::channel();
        let thread = std::thread::Builder::new()
            .name("tape recording".into())
            .spawn(move || {
                let mut r = Recorder {
                    ctx,
                    planner: FftPlanner::new(),
                    kernels: Vec::new(),
                };
                while let Ok(job) = rx.recv() {
                    if tx.send(r.record(job)).is_err() {
                        break;
                    }
                }
            })
            .expect("tape: the recording thread");
        Worker {
            jobs: Some(jobs),
            done: Mutex::new(done),
            thread: Some(thread),
        }
    }

    fn submit(&self, job: Job) -> Result<(), String> {
        self.jobs
            .as_ref()
            .and_then(|j| j.send(job).ok())
            .ok_or_else(|| "tape: the recording thread stopped".to_string())
    }

    /// The next recorded block (in the order submitted), waiting for it.
    fn next(&self) -> Result<Done, String> {
        self.done
            .lock()
            .map_err(|_| "tape: the recording thread stopped".to_string())?
            .recv()
            .map_err(|_| "tape: the recording thread stopped".to_string())?
    }
}

impl Drop for Worker {
    fn drop(&mut self) {
        self.jobs.take();
        if let Some(t) = self.thread.take() {
            let _ = t.join();
        }
    }
}

/// The tape between the heads (see the module docs).
pub struct TapeStream {
    p: TapeParams,
    fs: f64,
    /// What recording reads, shared with the worker.
    ctx: Arc<Ctx>,
    rep_head: Head,
    nb: usize,
    nm: usize,
    nr: usize,
    k_max: f64,
    scale: f64,
    /// The pushed samples first, first + 1, ... (literal bias: the fast samples).
    h: Vec<f64>,
    /// The literal bias's samples per push (1: the medium's own bias).
    m: usize,
    first: usize,
    n: usize,
    /// Recorded blocks: (block, M_x, M_y), layers x block cells.
    rec: Vec<(usize, Vec<f64>, Vec<f64>)>,
    /// Flux slopes: (block, G over the block's cells and 2 either side).
    slopes: Vec<(usize, Vec<f64>)>,
    /// The next block to finish (its grain, its predecessor's slope) and the next to hand
    /// the worker: the blocks in between are being recorded.
    next_rec: usize,
    next_submit: usize,
    planner: FftPlanner<f64>,
    worker: Worker,
    /// The grain's (seed, name) of its Philox streams (`noise::key`), if on.
    grain: Option<(u64, String)>,
    /// The packing field at the last cell recorded.
    packing_prev: f64,
    /// The transport: with flutter, the tape's position at the record gap per sample
    /// (s[k] at sample s_first + k, one ahead of the pushes), the speed at its last, the
    /// resonances' filter states.
    moving: bool,
    transport_seed: u64,
    zi: Vec<[f64; 2]>,
    s: Vec<f64>,
    s_first: usize,
    v_last: f64,
}

impl std::fmt::Debug for TapeStream {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("TapeStream")
            .field("fs", &self.fs)
            .field("pushed", &self.n)
            .field("next_block", &self.next_rec)
            .finish()
    }
}

impl TapeStream {
    /// The stream without grain.
    pub fn new(p: &TapeParams, fs: f64) -> Result<Self, String> {
        Self::with_grain(p, fs, None)
    }

    /// The stream with the coating's grain keyed by (seed, name), if given (the reference's
    /// noise_seed and noise_name); the tape's particles must be fitted.
    pub fn with_grain(p: &TapeParams, fs: f64, grain: Option<(u64, &str)>) -> Result<Self, String> {
        Self::build(p, fs, grain, 0)
    }

    /// The stream with grain (if given) and the transport's random parts keyed by
    /// (transport_seed, "transport") (the reference's transport_seed).
    pub fn build(
        p: &TapeParams,
        fs: f64,
        grain: Option<(u64, &str)>,
        transport_seed: u64,
    ) -> Result<Self, String> {
        p.check(Some(fs))?;
        if grain.is_some() && !(p.particle_volume_m3 > 0.0 && p.packing > 0.0) {
            return Err(
                "tape: grain needs the tape's particles (particle_volume_m3, packing)".into(),
            );
        }
        let pre = preisach(
            p.hc_median_a_m,
            p.sigma_ln_hc,
            p.sigma_hi_a_m,
            p.h_max_a_m,
            p.n_table,
        );
        let rec_head = Head {
            gap: p.rec_gap_m,
            pole: p.pole_m,
            relax: p.relax_m,
        };
        let rep_head = Head {
            gap: p.rep_gap_m,
            ..rec_head
        };
        // `Orientation.axes`.
        let n = p.orientations;
        let phi: Vec<f64> = (0..n)
            .map(|j| -PI / 2.0 + (j as f64 + 0.5) * PI / n as f64)
            .collect();
        let w: Vec<f64> = phi
            .iter()
            .map(|f| (p.kappa * ((2.0 * f).cos() - 1.0)).exp())
            .collect();
        let total: f64 = w.iter().sum();
        let axes = phi
            .iter()
            .zip(&w)
            .map(|(f, w)| [f.cos(), f.sin(), w / total])
            .collect();
        let dy = p.coating_m / p.layers as f64;
        let heights: Vec<f64> = (0..p.layers)
            .map(|l| p.spacing_m + (l as f64 + 0.5) * dy)
            .collect();
        let (nb, nm, nr) = p.cells();
        let floor = p.zone_floor_a_m;
        let zone_tables = heights
            .iter()
            .map(|&y| {
                (0..=ZONE_STEPS * ZONE_OCTAVES)
                    .map(|i| {
                        let peak = floor * 2f64.powf(i as f64 / ZONE_STEPS as f64);
                        zone_halfwidth(&rec_head, y, peak, floor)
                    })
                    .collect()
            })
            .collect();
        let ctx = Arc::new(Ctx {
            p: p.clone(),
            pre,
            rec_head,
            heights,
            axes,
            zone_tables,
            threads: 0,
        });
        let mut st = TapeStream {
            fs,
            worker: Worker::spawn(ctx.clone()),
            ctx,
            rep_head,
            nb,
            nm,
            nr,
            k_max: 2.0 * PI * 0.45 * fs / p.speed_m_s,
            scale: MU0 * p.track_m * p.ms_a_m * p.rep_h_per_a * dy,
            h: Vec::new(),
            m: p.bias_substeps.unwrap_or(1),
            first: 0,
            n: 0,
            rec: Vec::new(),
            slopes: Vec::new(),
            next_rec: 0,
            next_submit: 0,
            planner: FftPlanner::new(),
            grain: grain.map(|(seed, name)| (seed, name.to_string())),
            packing_prev: 0.0,
            moving: !(p.flutter.is_empty() && p.flutter_noise.is_empty()),
            transport_seed,
            zi: vec![[0.0; 2]; p.flutter_noise.len()],
            s: vec![0.0],
            s_first: 0,
            v_last: 0.0,
            p: p.clone(),
        };
        if st.moving {
            st.v_last = st.speeds(0, 1)[0];
        }
        Ok(st)
    }

    /// Record on `threads` threads (0: every logical core; the default). The output is the
    /// same; inside a circuit, leaving cores to the circuit's own threads is faster
    /// (TAPE_PLAN.md, "Speed"). Before the first push.
    pub fn set_threads(&mut self, threads: usize) -> Result<(), String> {
        if self.next_submit > 0 {
            return Err("tape: set_threads after recording started".into());
        }
        let mut ctx = Ctx::clone(&self.ctx);
        ctx.threads = threads;
        self.ctx = Arc::new(ctx);
        self.worker = Worker::spawn(self.ctx.clone());
        Ok(())
    }

    pub fn params(&self) -> &TapeParams {
        &self.p
    }

    /// Block b's recorded cells [j0, j1) and its recording's time span (None while the
    /// tape hasn't got there).
    fn span(&self, b: usize) -> (usize, usize, Option<f64>, Option<f64>) {
        let (ds, v) = (self.p.ds_m, self.p.speed_m_s);
        let j0 = (b * self.nb).saturating_sub(self.nm);
        let j1 = (b + 1) * self.nb + self.nm;
        if !self.moving {
            return (
                j0,
                j1,
                Some(j0 as f64 * ds / v - ZONE_PAD_M / v),
                Some((j1 - 1) as f64 * ds / v + ZONE_PAD_M / v),
            );
        }
        (
            j0,
            j1,
            self.time_at(j0 as f64 * ds - ZONE_PAD_M, true),
            self.time_at((j1 - 1) as f64 * ds + ZONE_PAD_M, false),
        )
    }

    /// Block b's samples are in.
    fn ready(&self, b: usize) -> bool {
        self.span(b)
            .3
            .is_some_and(|t1| (t1 * self.fs).floor() as usize + 3 <= self.n)
    }

    /// `_speeds`: v (1 + eps) at samples k0 .. k1, the resonances' filters run on.
    fn speeds(&mut self, k0: usize, k1: usize) -> Vec<f64> {
        let fs = self.fs;
        let mut eps: Vec<f64> = (k0..k1)
            .map(|k| {
                let t = k as f64 / fs;
                let mut e = 0.0;
                for c in &self.p.flutter {
                    e += c[0] * (2.0 * PI * c[1] * t + c[2]).cos();
                }
                e
            })
            .collect();
        let mut x = vec![0.0; k1 - k0];
        for (i, c) in self.p.flutter_noise.iter().enumerate() {
            let (rms, f, q) = (c[0], c[1], c[2]);
            let r = (-PI * f / (q * fs)).exp();
            let a1 = -2.0 * r * (2.0 * PI * f / fs).cos();
            let a2 = r * r;
            let var = (1.0 + a2) / ((1.0 - a2) * ((1.0 + a2) * (1.0 + a2) - a1 * a1));
            let b0 = rms / var.sqrt();
            crate::noise::normals(
                crate::noise::key(self.transport_seed, "transport", i as u32),
                k0 as u64,
                &mut x,
            );
            let [mut z0, mut z1] = self.zi[i];
            for (e, xk) in eps.iter_mut().zip(&x) {
                // scipy's lfilter (direct form II transposed), in its order.
                let y = z0 + b0 * xk;
                z0 = (z1 + xk * 0.0) - y * a1;
                z1 = xk * 0.0 - y * a2;
                *e += y;
            }
            self.zi[i] = [z0, z1];
        }
        let v = self.p.speed_m_s;
        eps.iter().map(|e| v * (1.0 + e)).collect()
    }

    /// `_advance`: the tape's position through sample k.
    fn advance(&mut self, k: usize) {
        let last = self.s_first + self.s.len() - 1;
        if k <= last {
            return;
        }
        let v = self.speeds(last + 1, k + 1);
        let half = 0.5 / self.fs;
        let mut prev = self.v_last;
        let mut pos = *self.s.last().unwrap();
        for vk in &v {
            pos += (prev + vk) * half;
            self.s.push(pos);
            prev = *vk;
        }
        self.v_last = prev;
    }

    /// `_s_at`: the tape's position at the record gap at time t.
    fn s_at(&self, t: f64) -> f64 {
        let (v, fs) = (self.p.speed_m_s, self.fs);
        if !self.moving {
            return v * t;
        }
        let u = t * fs;
        let i = u.floor();
        let f = u - i;
        let i = i as i64;
        let (first, n) = (self.s_first as i64, self.s.len() as i64);
        let tap = |k: i64| {
            if k < 0 {
                v * k as f64 / fs
            } else {
                self.s[(k - first).clamp(0, n - 1) as usize]
            }
        };
        -f * (f - 1.0) * (f - 2.0) / 6.0 * tap(i - 1)
            + (f + 1.0) * (f - 1.0) * (f - 2.0) / 2.0 * tap(i)
            - (f + 1.0) * f * (f - 2.0) / 2.0 * tap(i + 1)
            + (f + 1.0) * f * (f - 1.0) / 6.0 * tap(i + 2)
    }

    /// `_time_at`: a sample time at or before (start) / at or after the tape's position sv.
    fn time_at(&self, sv: f64, start: bool) -> Option<f64> {
        if sv < 0.0 {
            return Some(sv / self.p.speed_m_s);
        }
        let k = self.s.partition_point(|&x| x < sv);
        if k >= self.s.len() {
            return None;
        }
        let k = (k + self.s_first) as f64;
        Some(if start {
            (k - 1.0) / self.fs
        } else {
            k / self.fs
        })
    }

    /// `literal_peaks`: the literal field's extrema with t0 <= t <= t1 (each sample above
    /// its left neighbour and not below its right, or the reverse), refined by the parabola
    /// through the three: (times, values).
    pub fn literal_peaks(&self, t0: f64, t1: f64) -> (Vec<f64>, Vec<f64>) {
        let (m, first) = (self.m as f64, self.first as i64);
        let mf = m * self.fs;
        let kl = ((t0 * mf + 2.0 * m - 1.0).floor() as i64 - 1).max(first + 1);
        let kh =
            ((t1 * mf + 2.0 * m - 1.0).floor() as i64 + 2).min(first + self.h.len() as i64 - 2);
        let (mut ts, mut vs) = (Vec::new(), Vec::new());
        for k in kl..=kh {
            let i = (k - first) as usize;
            let (a, b, c) = (self.h[i - 1], self.h[i], self.h[i + 1]);
            if !((b > a && b >= c) || (b < a && b <= c)) {
                continue;
            }
            let den = a - 2.0 * b + c;
            let d = if den == 0.0 { 0.0 } else { 0.5 * (a - c) / den };
            let tk = (k as f64 + d + 1.0 - 2.0 * m) / mf;
            if t0 <= tk && tk <= t1 {
                ts.push(tk);
                vs.push(b - 0.25 * (a - c) * d);
            }
        }
        (ts, vs)
    }

    /// Block b's job: its cells and the field at the record gap over its span (the
    /// literal bias's extrema, or the signal at the medium's own bias's peaks).
    fn prep(&self, b: usize) -> Result<Job, String> {
        let (j0, j1, t0, t1) = self.span(b);
        let (t0, t1) = (
            t0.ok_or("tape: a block's start before the tape got there")?,
            t1.ok_or("tape: a block recorded before the tape got there")?,
        );
        let fs = self.fs;
        let s: Vec<f64> = (j0..j1).map(|j| j as f64 * self.p.ds_m).collect();
        let (hg, srec, peak) = if self.m > 1 {
            // The literal bias: the field's extrema.
            let (tp, hg) = self.literal_peaks(t0, t1);
            let srec: Vec<f64> = tp.iter().map(|&t| self.s_at(t)).collect();
            let peak = hg.iter().fold(0.0, |a: f64, &x| a.max(x.abs()));
            (hg, srec, peak)
        } else {
            let first = self.first as i64;
            let lo = ((t0 * fs).floor() as i64 - 1).max(0);
            let hi = (t1 * fs).floor() as i64 + 3;
            let peak_sig = self.h[(lo - first) as usize..(hi - first) as usize]
                .iter()
                .fold(0.0, |a: f64, &x| a.max(x.abs()));
            // `bias_peak_times`, shifted by the oscillator's phase.
            let f_b = self.p.f_bias_hz;
            let shift = self.p.bias_phase_rad / (2.0 * PI * f_b);
            let half = 0.5 / f_b;
            let k0 = ((t0 + shift) / half).floor() as i64;
            let k1 = ((t1 + shift) / half).ceil() as i64;
            let mut hg = Vec::new();
            let mut srec = Vec::new();
            for k in k0..k1 {
                let t = ((k as f64 + 0.5) + 0.0) * half - shift;
                if t < t0 || t > t1 {
                    continue;
                }
                let sig = cubic_held(&self.h, t * fs, first);
                hg.push(
                    sig + self.p.hg_bias_a_m * (2.0 * PI * f_b * t + self.p.bias_phase_rad).sin(),
                );
                srec.push(self.s_at(t));
            }
            (hg, srec, peak_sig + self.p.hg_bias_a_m)
        };
        Ok(Job {
            b,
            j0,
            s,
            hg,
            srec,
            peak,
        })
    }

    /// A recorded block: its cells (without the margins), the grain, and its predecessor's
    /// flux slope (which reads it), in block order.
    fn finish(&mut self, d: Done) {
        let b = d.b;
        debug_assert_eq!(b, self.next_rec);
        let (cells, nb) = (d.cells, self.nb);
        let i0 = b * nb - d.j0;
        let mut bx = Vec::with_capacity(self.p.layers * nb);
        let mut by = Vec::with_capacity(self.p.layers * nb);
        for l in 0..self.p.layers {
            bx.extend_from_slice(&d.mx[l * cells + i0..l * cells + i0 + nb]);
            by.extend_from_slice(&d.my[l * cells + i0..l * cells + i0 + nb]);
        }
        if let Some((seed, name)) = self.grain.clone() {
            self.grain_block(&mut bx, &mut by, b * nb, seed, &name);
        }
        self.rec.push((b, bx, by));
        self.next_rec += 1;
        if b >= 1 {
            self.slope_block(b - 1);
            self.rec.retain(|(c, _, _)| *c + 2 > b);
        }
    }

    /// The reference's `_grain`: the block's cells from i0 times 1 + the packing field (an
    /// AR(1) along the tape, one for the coating's depth, its state carried from block to
    /// block), plus the Poisson particle noise.
    fn grain_block(&mut self, mx: &mut [f64], my: &mut [f64], i0: usize, seed: u64, name: &str) {
        let (nb, layers) = (self.nb, self.p.layers);
        let ds = self.p.ds_m;
        let dy = self.p.coating_m / layers as f64;
        let n_cell = self.p.packing * ds * dy * self.p.track_m / self.p.particle_volume_m3;
        let (mut cx, mut cy) = (0.0, 0.0);
        for a in &self.ctx.axes {
            cx += a[2] * a[0] * a[0];
            cy += a[2] * a[1] * a[1];
        }
        let (sx, sy) = ((cx / n_cell).sqrt(), (cy / n_cell).sqrt());
        let mut d = vec![0.0; nb];
        if self.p.packing_sigma > 0.0 {
            let rho = (-ds / self.p.packing_corr_m).exp();
            let c = (1.0 - rho * rho).sqrt();
            let k = crate::noise::key(seed, name, 0);
            if i0 == 0 {
                let mut first = [0.0];
                crate::noise::normals(k, 0, &mut first);
                self.packing_prev = first[0];
            }
            let mut xi = vec![0.0; nb];
            crate::noise::normals(k, i0 as u64 + 1, &mut xi);
            let mut prev = self.packing_prev;
            for (di, x) in d.iter_mut().zip(&xi) {
                prev = c * x + rho * prev;
                *di = prev;
            }
            self.packing_prev = prev;
            for di in &mut d {
                *di *= self.p.packing_sigma;
            }
        }
        let mut z = vec![0.0; 2 * nb];
        for l in 0..layers {
            crate::noise::normals(
                crate::noise::key(seed, name, 1 + l as u32),
                2 * i0 as u64,
                &mut z,
            );
            for i in 0..nb {
                let c = l * nb + i;
                mx[c] = mx[c] * (1.0 + d[i]) + sx * z[2 * i];
                my[c] = my[c] * (1.0 + d[i]) + sy * z[2 * i + 1];
            }
        }
    }

    /// `flux_slope` over a window (layers x w cells).
    fn flux_slope(&mut self, mx: &[f64], my: &[f64], w: usize) -> Vec<f64> {
        let p = &self.p;
        let head = self.rep_head;
        let ext = (4.0 * (head.gap / 2.0 + head.pole + head.relax) / p.ds_m).ceil() as usize;
        let n = (w + 2 * ext).next_power_of_two();
        let freq = 1.0 / (n as f64 * p.ds_m);
        let ks: Vec<f64> = (0..n / 2 + 1)
            .map(|j| 2.0 * PI * (j as f64 * freq))
            .collect();
        let dy = p.coating_m / p.layers as f64;
        let (layers, spacing, k_max) = (p.layers, p.spacing_m, self.k_max);
        let mut acc = vec![Complex64::new(0.0, 0.0); n / 2 + 1];
        for l in 0..layers {
            let y = spacing + (l as f64 + 0.5) * dy;
            let fx = rfft(&mut self.planner, &mx[l * w..(l + 1) * w], n);
            let fy = rfft(&mut self.planner, &my[l * w..(l + 1) * w], n);
            for (j, a) in acc.iter_mut().enumerate() {
                let sx = hx_spectrum(&head, ks[j], y);
                *a += fx[j] * sx;
                let sy = Complex64::new(0.0, ks[j].signum() * sx);
                *a -= fy[j] * sy;
            }
        }
        for (j, a) in acc.iter_mut().enumerate() {
            let k = ks[j];
            *a *= Complex64::new(0.0, k);
            let u = ((k / k_max - 0.8) / 0.2).clamp(0.0, 1.0);
            *a *= if k >= k_max {
                0.0
            } else {
                0.5 * (1.0 + (PI * u).cos())
            };
        }
        irfft(&mut self.planner, &acc, n, w)
    }

    fn slope_block(&mut self, b: usize) {
        let (nb, nr, layers) = (self.nb, self.nr, self.p.layers);
        let w = nb + 2 * nr;
        let mut wx = vec![0.0; layers * w];
        let mut wy = vec![0.0; layers * w];
        let c0 = (b * nb) as i64 - nr as i64;
        for (c, bx, by) in &self.rec {
            let c = *c;
            if c + 1 < b || c > b + 1 {
                continue;
            }
            let a0 = ((c * nb) as i64).max(c0);
            let a1 = (((c + 1) * nb) as i64).min(c0 + w as i64);
            if a1 <= a0 {
                continue;
            }
            for l in 0..layers {
                for a in a0..a1 {
                    let src = l * nb + (a - (c * nb) as i64) as usize;
                    let dst = l * w + (a - c0) as usize;
                    wx[dst] = bx[src];
                    wy[dst] = by[src];
                }
            }
        }
        let g = self.flux_slope(&wx, &wy, w);
        self.slopes.push((b, g[nr - 2..nr + nb + 2].to_vec()));
    }

    /// [`push`](Self::push) for each of hs in turn (the same results, any chunking), the
    /// EMFs into out.
    pub fn push_many(&mut self, hs: &[f64], out: &mut Vec<f64>) -> Result<(), String> {
        let m = self.m;
        if !hs.len().is_multiple_of(m) {
            return Err(format!("tape: literal bias pushes {m} samples each"));
        }
        let n0 = self.n;
        self.h.extend_from_slice(hs);
        self.n += hs.len() / m;
        if self.moving {
            self.advance(self.n);
        }
        // Every block whose samples are in goes to the worker; the circuit runs on while it
        // records (the repro head reads a block about a head distance later).
        while self.ready(self.next_submit) {
            let job = self.prep(self.next_submit)?;
            self.worker.submit(job)?;
            self.next_submit += 1;
        }
        let keep = match self.span(self.next_submit).2 {
            Some(t0) => ((t0 * self.fs).floor() as i64 - 1).max(0) as usize,
            None => self.first / m,
        };
        if keep * m > self.first {
            self.h.drain(..keep * m - self.first);
            self.first = keep * m;
        }
        // Positions: from the earliest a future recording reads and this push's outputs.
        let cut = (keep.saturating_sub(2)).min(n0 + 1);
        if self.moving && cut > self.s_first {
            self.s.drain(..cut - self.s_first);
            self.s_first = cut;
        }
        let (v, d, ds, fs) = (
            self.p.speed_m_s,
            self.p.head_distance_m,
            self.p.ds_m,
            self.fs,
        );
        // The blocks this push reads, finished (a block's slope needs its successor).
        if self.n > n0 {
            let k = self.n - 1;
            let u = if self.moving {
                (self.s[k + 1 - self.s_first] - d) / ds
            } else {
                (v * (k + 1) as f64 / fs - d) / ds
            };
            if u >= 0.0 {
                let need = u.floor() as usize / self.nb + 1;
                while self.next_rec <= need {
                    if self.next_rec >= self.next_submit {
                        return Err("tape: a block was read before it was recorded".into());
                    }
                    let done = self.worker.next()?;
                    self.finish(done);
                }
            }
        }
        let mut last = None;
        for m in n0..self.n {
            let u = if self.moving {
                (self.s[m + 1 - self.s_first] - d) / ds
            } else {
                (v * (m + 1) as f64 / fs - d) / ds
            };
            if u < 0.0 {
                out.push(0.0);
                continue;
            }
            let b = u.floor() as usize / self.nb;
            let g = &self
                .slopes
                .iter()
                .find(|(c, _)| *c == b)
                .ok_or("tape: a block was read before it was recorded")?
                .1;
            let origin = (b * self.nb) as i64 - 2;
            out.push(-v * self.scale * cubic_held(g, u - origin as f64, 0));
            last = Some(b);
        }
        if let Some(b) = last {
            self.slopes.retain(|(c, _)| *c + 1 >= b);
        }
        Ok(())
    }

    /// The literal bias's samples per push (1: the medium's own bias).
    pub fn substeps(&self) -> usize {
        self.m
    }

    /// The EMF at t_{n+1} after the signal field h at t_n.
    pub fn push(&mut self, h: f64) -> Result<f64, String> {
        let mut out = Vec::with_capacity(1);
        self.push_many(&[h], &mut out)?;
        Ok(out[0])
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fast_lengths_are_5_smooth() {
        assert_eq!(next_fast_len(1), 1);
        assert_eq!(next_fast_len(7), 8);
        assert_eq!(next_fast_len(31), 32);
        assert_eq!(next_fast_len(121), 125);
    }

    #[test]
    fn the_real_transforms_invert() {
        let mut planner = FftPlanner::new();
        let x: Vec<f64> = (0..37).map(|i| ((i * 7 % 11) as f64).sin()).collect();
        let k = rfft(&mut planner, &x, 80);
        let y = irfft(&mut planner, &k, 80, 37);
        for (a, b) in x.iter().zip(&y) {
            assert!((a - b).abs() < 1e-12);
        }
    }

    #[test]
    fn least_squares_solves_and_drops_dependent_columns() {
        let a = vec![1.0, 2.0, 0.0, 1.0];
        let b2 = vec![0.0, 1.0, 1.0, 3.0];
        let dep: Vec<f64> = a.iter().map(|x| 2.0 * x).collect();
        let rhs: Vec<f64> = a.iter().zip(&b2).map(|(x, y)| 3.0 * x - y).collect();
        let c = lstsq_mgs(&[a.clone(), b2.clone()], &rhs);
        assert!((c[0] - 3.0).abs() < 1e-12 && (c[1] + 1.0).abs() < 1e-12);
        let c = lstsq_mgs(&[a, dep], &rhs);
        assert_eq!(c[1], 0.0);
    }
}
