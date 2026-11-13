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
use std::sync::atomic::{AtomicU64, Ordering as AtomicOrdering};
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
    /// The reduced medium (docs/DELAY_PLAN.md, "The reduced medium"; the reference is
    /// `varimu.delay.reduced.ReducedStream`): each block recorded by tables and apertures
    /// instead of the ensemble over every bias peak, played back with the demagnetization
    /// correction. None: the full medium, and no such key in the JSON.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reduced: Option<TapeReduction>,
    /// The capstan's motor on a variable-frequency supply (varispeed; DELAY_PLAN.md): each
    /// push carries the supply's frequency ([`TapeStream::push_many_supply`]). None: the
    /// tape runs at speed_m_s (and its flutter), and no such key in the JSON.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub varispeed: Option<Varispeed>,
    /// The track's place on a tape of several (PERIOD_GEAR_BACKLOG.md PG1, MT3; the
    /// reference's `CrossPickup`): each push also gives the EMF a head beside it reads of
    /// this track ([`TapeStream::push_many_cross`]), and the media add a group's
    /// neighbours' to each head's own (`crate::media`). None: one track alone, and no such
    /// key in the JSON.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub crosstalk: Option<TapeCrosstalk>,
    /// The record head's playback (Sel-Sync; PG1, MT4; the reference's sync_h_per_a): each
    /// push also gives the record head's reading of the tape the repro head reads then
    /// ([`Readouts`]). None: no such readout, and no such key in the JSON.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub sync: Option<TapeSync>,
}

/// The record head as a playback head (Sel-Sync): its deep-gap field per coil ampere (its
/// gap and pole faces are the medium's `rec_gap_m`, `pole_m`, `relax_m`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TapeSync {
    pub h_per_a: f64,
}

/// A push's other readouts, per push ([`TapeStream::push_many_readouts`]); each empty when
/// the medium hasn't it: the cross EMF a head beside the track reads (crosstalk), the
/// record head's EMF (Sel-Sync) and the cross EMF a record head beside it reads.
#[derive(Debug, Clone, Default)]
pub struct Readouts {
    pub cross: Vec<f64>,
    pub sync: Vec<f64>,
    pub sync_cross: Vec<f64>,
}

impl Readouts {
    fn clear(&mut self) {
        self.cross.clear();
        self.sync.clear();
        self.sync_cross.clear();
    }
}

/// A block's flux slopes over its cells and 2 either side (the readouts' empty when the
/// medium hasn't them).
#[derive(Debug, Clone)]
struct BlockSlopes {
    b: usize,
    own: Vec<f64>,
    cross: Vec<f64>,
    sync: Vec<f64>,
    sync_cross: Vec<f64>,
}

/// A track among several on one tape (`varimu.devices.tape.CrossPickup`, the group and
/// the track's number): the tapes of a circuit with the same `group` are one tape's
/// tracks, `track` numbering them across its width (one apart: neighbours). What a head
/// pitch_m from this track reads of it: the outer contour's field through the shields
/// (`unshielded`), spread as a strip contour_width_m wide ([`lateral_factor`]), plus the
/// cores' flat coupling (`core`) times the neighbour head's own reading.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TapeCrosstalk {
    pub group: String,
    #[serde(deserialize_with = "count")]
    pub track: usize,
    pub pitch_m: f64,
    pub unshielded: f64,
    pub contour_width_m: f64,
    pub core: f64,
}

impl TapeCrosstalk {
    fn check(&self) -> Result<(), String> {
        if self.pitch_m > self.contour_width_m
            && self.contour_width_m > 0.0
            && self.unshielded >= 0.0
            && self.core.is_finite()
            && self.pitch_m.is_finite()
            && !self.group.is_empty()
        {
            Ok(())
        } else {
            Err("tape: crosstalk needs pitch > contour width > 0, unshielded >= 0, a group".into())
        }
    }
}

/// `lateral_factor`'s quadrature: the step in t, and where it stops (the integrand below
/// e^-LATERAL_DECAY).
const LATERAL_STEP: f64 = 0.1;
const LATERAL_DECAY: f64 = 60.0;

/// `varimu.devices.tape.lateral_factor`: the field of a strip contour w wide read at
/// centre distance d > w across the tape, relative to a track of infinite width, by the
/// trapezoidal rule in t of k / (pi w) e^{-a (d - w)} (1 - e^{-a w})^2 / a^2, a = k cosh t
/// (0 at k = 0), in the reference's order of operations.
pub fn lateral_factor(k: f64, d: f64, w: f64) -> f64 {
    let k = k.abs();
    if k == 0.0 {
        return 0.0;
    }
    let gap = d - w;
    let n = ((LATERAL_DECAY / (k * gap)).max(1.0).acosh() / LATERAL_STEP).ceil() as usize;
    let f = |i: usize| {
        let a = k * (LATERAL_STEP * i as f64).cosh();
        let e = (-a * w).exp_m1();
        (-a * gap).exp() * (e * e) / (a * a)
    };
    let mut acc = 0.5 * f(0);
    for i in 1..=n {
        acc += f(i);
    }
    k / (PI * w) * LATERAL_STEP * acc
}

/// The capstan's hysteresis synchronous motor on a variable-frequency supply (the reference
/// is `varimu.devices.tape_machine.TapeStream`'s varispeed): the tape's speed is speed_m_s
/// times the rotor's speed over its synchronous speed at nominal_hz; the rotor follows the
/// supply's frequency as a resonance at hunting_hz, Q hunting_q (its inertia against the
/// field's pull: the transport's hunting), unity at DC, a sample late.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Varispeed {
    pub nominal_hz: f64,
    pub hunting_hz: f64,
    pub hunting_q: f64,
}

impl Varispeed {
    /// The motor's all-pole resonator at step rate fs: (b0, a1, a2), b0 = 1 + a1 + a2.
    fn coefficients(&self, fs: f64) -> (f64, f64, f64) {
        let r = (-PI * self.hunting_hz / (self.hunting_q * fs)).exp();
        let a1 = -2.0 * r * (2.0 * PI * self.hunting_hz / fs).cos();
        let a2 = r * r;
        (1.0 + a1 + a2, a1, a2)
    }
}

/// A medium reduced at one bias (`varimu.delay.reduced.Reduction`): per layer, M_x / Ms
/// against a constant deep-gap field on a uniform grid (`mx`, `slope` its derivative at 0),
/// the apertures after the gap's centre (`ax` summing to 1, `ky` per A/m; taps at
/// tau0_s + j dt_s), and the demagnetization correction D(k) (rad/m rising, 1 at 0).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TapeReduction {
    pub h_a_m: Vec<f64>,
    pub tau0_s: f64,
    pub dt_s: f64,
    /// At biases rising (BIAS as a knob); one: a single bias's reduction.
    pub points: Vec<ReductionPoint>,
    /// The demagnetization correction's wavenumbers (each point's D on them).
    pub demag_k: Vec<f64>,
}

/// One bias's tables and apertures in a [`TapeReduction`] (its grids'): the bias's deep-gap
/// peak (A/m), per layer M_x / Ms against a constant field (mx; slope its derivative at
/// 0), the apertures (ax summing to 1, ky per A/m) and the demagnetization correction D
/// on the reduction's demag_k (a shallower recording loses less to its own field).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReductionPoint {
    pub bias_a_m: f64,
    pub mx: Vec<Vec<f64>>,
    pub slope: Vec<f64>,
    pub ax: Vec<Vec<f64>>,
    pub ky: Vec<Vec<f64>>,
    pub demag_d: Vec<f64>,
}

impl TapeReduction {
    fn check(&self, layers: usize) -> Result<(), String> {
        let taps = self
            .points
            .first()
            .and_then(|q| q.ax.first())
            .map_or(0, Vec::len);
        let n = self.h_a_m.len();
        let ok = n >= 4
            && self.h_a_m.windows(2).all(|w| w[1] > w[0])
            && !self.points.is_empty()
            && self.points[0].bias_a_m > 0.0
            && self
                .points
                .windows(2)
                .all(|w| w[1].bias_a_m > w[0].bias_a_m)
            && self.points.iter().all(|q| {
                [&q.mx, &q.ax, &q.ky].iter().all(|v| v.len() == layers)
                    && q.mx.iter().all(|r| r.len() == n)
                    && q.slope.len() == layers
                    && q.ax.iter().chain(&q.ky).all(|r| r.len() == taps)
                    && q.demag_d.len() == self.demag_k.len()
            })
            && taps > 0
            && self.dt_s > 0.0
            && self.tau0_s.is_finite()
            && !self.demag_k.is_empty()
            && self.demag_k.windows(2).all(|w| w[1] > w[0]);
        if ok {
            Ok(())
        } else {
            Err("tape: the reduction's tables don't fit the medium".into())
        }
    }

    /// `BiasReductions.at`: the point at bias hg (A/m), linear in ln(bias) between the
    /// neighbouring points, held past the ends (one point: itself).
    fn at(&self, hg: f64) -> ReductionPoint {
        let pts = &self.points;
        let n = pts.len();
        let held = |q: &ReductionPoint| ReductionPoint {
            bias_a_m: hg,
            ..q.clone()
        };
        if n == 1 {
            return pts[0].clone();
        }
        let x = hg.ln();
        let lb: Vec<f64> = pts.iter().map(|q| q.bias_a_m.ln()).collect();
        if x <= lb[0] {
            return held(&pts[0]);
        }
        if x >= lb[n - 1] {
            return held(&pts[n - 1]);
        }
        let j = lb.partition_point(|&v| v <= x) - 1;
        let w = (x - lb[j]) / (lb[j + 1] - lb[j]);
        let (a, b) = (&pts[j], &pts[j + 1]);
        let mix = |u: f64, v: f64| (1.0 - w) * u + w * v;
        let rows = |u: &[Vec<f64>], v: &[Vec<f64>]| -> Vec<Vec<f64>> {
            u.iter()
                .zip(v)
                .map(|(ru, rv)| ru.iter().zip(rv).map(|(&p, &q)| mix(p, q)).collect())
                .collect()
        };
        ReductionPoint {
            bias_a_m: hg,
            mx: rows(&a.mx, &b.mx),
            slope: a
                .slope
                .iter()
                .zip(&b.slope)
                .map(|(&p, &q)| mix(p, q))
                .collect(),
            ax: rows(&a.ax, &b.ax),
            ky: rows(&a.ky, &b.ky),
            demag_d: a
                .demag_d
                .iter()
                .zip(&b.demag_d)
                .map(|(&p, &q)| mix(p, q))
                .collect(),
        }
    }

    /// `varimu.delay.reduced.aperture_fir`: a point's apertures as FIRs on the samples at
    /// rate fs (`cubic_held` between them), ax's span setting both: (k0, cx, cy), layers x
    /// taps. ratio: the tape's speed over its nominal (the apertures are positions behind
    /// the gap: their times scale as 1 / ratio).
    fn firs(&self, q: &ReductionPoint, fs: f64, ratio: f64) -> Firs {
        let taps = q.ax[0].len();
        let parts: Vec<(i64, [f64; 4])> = (0..taps)
            .map(|j| {
                let u = (self.tau0_s + self.dt_s * j as f64) / ratio * fs;
                let i = u.floor();
                let f = u - i;
                (
                    i as i64,
                    [
                        -f * (f - 1.0) * (f - 2.0) / 6.0,
                        (f + 1.0) * (f - 1.0) * (f - 2.0) / 2.0,
                        -(f + 1.0) * f * (f - 2.0) / 2.0,
                        (f + 1.0) * f * (f - 1.0) / 6.0,
                    ],
                )
            })
            .collect();
        let k0 = parts.iter().map(|p| p.0).min().unwrap_or(0) - 1;
        let len = (parts.iter().map(|p| p.0).max().unwrap_or(0) + 2 - k0 + 1) as usize;
        let fir = |a: &[Vec<f64>]| -> Vec<Vec<f64>> {
            a.iter()
                .map(|row| {
                    let mut c = vec![0.0; len];
                    for (j, (i, w)) in parts.iter().enumerate() {
                        for (q, wq) in w.iter().enumerate() {
                            c[(i - 1 + q as i64 - k0) as usize] += row[j] * wq;
                        }
                    }
                    c
                })
                .collect()
        };
        (k0, fir(&q.ax), fir(&q.ky))
    }
}

/// T_l(g): a point's `cubic_at` on the uniform grid h, g clipped to it.
fn table(h: &[f64], q: &ReductionPoint, l: usize, g: f64) -> f64 {
    let n = h.len();
    let u = (g.clamp(h[0], h[n - 1]) - h[0]) / (h[1] - h[0]);
    cubic_at(&q.mx[l], u)
}

/// numpy's `interp`: xp rising, fp held beyond its ends.
fn interp(x: f64, xp: &[f64], fp: &[f64]) -> f64 {
    let n = xp.len();
    if x <= xp[0] {
        return fp[0];
    }
    if x >= xp[n - 1] {
        return fp[n - 1];
    }
    let j = xp.partition_point(|&v| v <= x) - 1;
    let slope = (fp[j + 1] - fp[j]) / (xp[j + 1] - xp[j]);
    slope * (x - xp[j]) + fp[j]
}

/// `varimu.devices.tape.cubic_at`: uniform samples y at fractional index u, 4-point
/// Lagrange, the stencil held inside the samples (extrapolating at the ends).
fn cubic_at(y: &[f64], u: f64) -> f64 {
    let n = y.len() as i64;
    let i = (u.floor() as i64).clamp(1, n - 3);
    let f = u - i as f64;
    let i = i as usize;
    let (ym1, y0, y1, y2) = (y[i - 1], y[i], y[i + 1], y[i + 2]);
    -f * (f - 1.0) * (f - 2.0) / 6.0 * ym1 + (f + 1.0) * (f - 1.0) * (f - 2.0) / 2.0 * y0
        - (f + 1.0) * f * (f - 2.0) / 2.0 * y1
        + (f + 1.0) * f * (f - 1.0) / 6.0 * y2
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
        if let Some(v) = &self.varispeed {
            let ok = v.nominal_hz > 0.0
                && v.hunting_hz > 0.0
                && v.hunting_q > 0.0
                && fs.is_none_or(|fs| v.hunting_hz < fs / 2.0);
            if !ok {
                return Err("tape: the varispeed's motor is out of range".into());
            }
        }
        if let Some(r) = &self.reduced {
            if self.bias_substeps.is_some() {
                return Err("tape: a reduced medium records with its own bias".into());
            }
            r.check(self.layers)?;
        }
        if self
            .sync
            .as_ref()
            .is_some_and(|y| !(y.h_per_a.is_finite() && y.h_per_a > 0.0))
        {
            return Err("tape: sync needs the record head's field per ampere > 0".into());
        }
        if self.sync.is_some() && self.reduced.is_some() {
            return Err("tape: Sel-Sync is the full medium's (not a reduced one's)".into());
        }
        if let Some(x) = &self.crosstalk {
            x.check()?;
            if self.reduced.is_some() {
                return Err("tape: crosstalk is the full medium's (not a reduced one's)".into());
            }
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

    /// Cells per block, per margin, and the reading heads' reach in cells (the repro
    /// head's, or the wider of it and the record head's with the Sel-Sync readout).
    fn cells(&self) -> (usize, usize, usize) {
        let ds = self.ds_m;
        let gap = if self.sync.is_some() {
            self.rep_gap_m.max(self.rec_gap_m)
        } else {
            self.rep_gap_m
        };
        let reach = 2.0 * (gap / 2.0 + self.pole_m + self.relax_m);
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

/// `cross_hx_spectrum`: [`hx_spectrum`] for a neighbouring head, with the lateral factor
/// `lat` at k: g e^{-|k| y} [core sinc(k g / 2) - (unshielded L + core) cos(k e_c) R(k)].
fn cross_hx_spectrum(head: &Head, k: f64, y: f64, x: &TapeCrosstalk, lat: f64) -> f64 {
    let (g, p, r) = (head.gap, head.pole, head.relax);
    let gap = sinc(k * g / (2.0 * PI));
    let ec = g / 2.0 + p + r / 2.0;
    let relax = if r > 0.0 {
        sinc(k * r / (2.0 * PI))
    } else {
        1.0
    };
    g * (-k.abs() * y).exp()
        * (x.core * gap - (x.unshielded * lat + x.core) * (k * ec).cos() * relax)
}

/// Newton steps of `refine_extremum` (fixed, so both languages take the same ones).
const EXTREMUM_NEWTON_STEPS: usize = 3;

/// The extremum of the parabola through (-1, a), (0, b), (1, c): (offset, value).
fn parabola_extremum(a: f64, b: f64, c: f64) -> (f64, f64) {
    let den = a - 2.0 * b + c;
    let d = if den == 0.0 { 0.0 } else { 0.5 * (a - c) / den };
    (d, b - 0.25 * (a - c) * d)
}

/// The extremum of the quartic through five equally spaced samples (at -2 .. 2, the middle
/// one a local extremum): (offset, value). Newton on its derivative from the parabola's
/// offset, EXTREMUM_NEWTON_STEPS steps, the offset kept within +-1. The parabola's value
/// error grows as (w h)^4 and beats against the oscillator (a line in the 351's noise at
/// 10 substeps); the quartic's is its interpolation error, ~(w h)^6. The reference is
/// `varimu.devices.tape_machine.refine_extremum`.
fn refine_extremum(y0: f64, y1: f64, y2: f64, y3: f64, y4: f64) -> (f64, f64) {
    let c1 = (y0 - 8.0 * y1 + 8.0 * y3 - y4) / 12.0;
    let c2 = (-y0 + 16.0 * y1 - 30.0 * y2 + 16.0 * y3 - y4) / 24.0;
    let c3 = (-y0 + 2.0 * y1 - 2.0 * y3 + y4) / 12.0;
    let c4 = (y0 - 4.0 * y1 + 6.0 * y2 - 4.0 * y3 + y4) / 24.0;
    let (mut u, _) = parabola_extremum(y1, y2, y3);
    for _ in 0..EXTREMUM_NEWTON_STEPS {
        let g = c1 + u * (2.0 * c2 + u * (3.0 * c3 + u * 4.0 * c4));
        let gp = 2.0 * c2 + u * (6.0 * c3 + u * 12.0 * c4);
        if gp == 0.0 {
            break;
        }
        u = (u - g / gp).clamp(-1.0, 1.0);
    }
    (u, y2 + u * (c1 + u * (c2 + u * (c3 + u * c4))))
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
    /// The recording kernel on the GPU (`Recording::gpu`).
    gpu: bool,
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
    /// A reduced block's bias's point (its D(k) for the block's flux slope); None for the
    /// full medium.
    demag: Option<Arc<ReductionPoint>>,
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
    ) -> Result<(Vec<f64>, Vec<f64>), String> {
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
            gpu: self.ctx.gpu,
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
        let (mut mx, mut my) = self.record_once(&hg, &srec, &s, &zones, None, None)?;
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
                )?
            } else {
                self.record_once(&hg, &srec, &s, &zones, Some((&f[0].0, &f[0].1)), None)?
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
            demag: None,
        })
    }
}

/// The GPU the recording kernel would run on, or why it can't.
#[cfg(feature = "gpu")]
pub fn gpu_available() -> Result<String, String> {
    tapegpu::available()
}

/// The GPU the recording kernel would run on, or why it can't.
#[cfg(not(feature = "gpu"))]
pub fn gpu_available() -> Result<String, String> {
    Err("tape: circuitsim was built without the GPU kernel (the `gpu` feature)".into())
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

/// Process-wide timing of the literal recording (TAPE_SPEED_PLAN.md P1): the workers'
/// time recording blocks, and the streams' time waiting for a block they read.
static WORKER_BUSY_NS: AtomicU64 = AtomicU64::new(0);
static WAITED_NS: AtomicU64 = AtomicU64::new(0);

/// The recording's timing so far, for `CIRCUITSIM_PART_TIMING`.
pub(crate) fn timing_line() -> String {
    format!(
        "tape worker busy {:.2} s, the stream waited on it {:.2} s",
        WORKER_BUSY_NS.load(AtomicOrdering::Relaxed) as f64 * 1e-9,
        WAITED_NS.load(AtomicOrdering::Relaxed) as f64 * 1e-9
    )
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
                    let t0 = std::time::Instant::now();
                    let done = r.record(job);
                    WORKER_BUSY_NS
                        .fetch_add(t0.elapsed().as_nanos() as u64, AtomicOrdering::Relaxed);
                    if tx.send(done).is_err() {
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
        let t0 = std::time::Instant::now();
        let d = self
            .done
            .lock()
            .map_err(|_| "tape: the recording thread stopped".to_string())?
            .recv()
            .map_err(|_| "tape: the recording thread stopped".to_string())?;
        WAITED_NS.fetch_add(t0.elapsed().as_nanos() as u64, AtomicOrdering::Relaxed);
        d
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

/// A recorded block's last steps, in block order: its grain, then its predecessor's flux
/// slope at the repro head (which reads it). The full medium finishes on the stream's
/// thread; a reduced one on its worker's (`ReducedWorker`), its slack the head distance.
struct Finisher {
    p: TapeParams,
    axes: Vec<[f64; 3]>,
    rep_head: Head,
    /// The record head (the Sel-Sync readout's).
    rec_head: Head,
    nb: usize,
    nr: usize,
    k_max: f64,
    planner: FftPlanner<f64>,
    /// Recorded blocks: (block, M_x, M_y), layers x block cells.
    rec: Vec<(usize, Vec<f64>, Vec<f64>)>,
    /// A reduced medium's blocks' bias points (their D(k)), as `rec`.
    demag: Vec<(usize, Arc<ReductionPoint>)>,
    /// The grain's (seed, name) of its Philox streams (`noise::key`), if on.
    grain: Option<(u64, String)>,
    /// The grain's first cell along the tape (`TapeStream::set_origin`; 0 from t = 0).
    cell_origin: u64,
    /// The packing field at the last cell recorded.
    packing_prev: f64,
    /// The next block to finish.
    next: usize,
    /// Crosstalk's lateral factor on the slopes' FFT bins (`lateral_factor`), by length
    /// (one per head's window).
    lateral: Vec<(usize, Vec<f64>)>,
}

impl Finisher {
    /// A finisher of the same tape, with nothing finished yet.
    fn fresh(&self) -> Finisher {
        Finisher {
            p: self.p.clone(),
            axes: self.axes.clone(),
            rep_head: self.rep_head,
            rec_head: self.rec_head,
            nb: self.nb,
            nr: self.nr,
            k_max: self.k_max,
            planner: FftPlanner::new(),
            rec: Vec::new(),
            demag: Vec::new(),
            grain: self.grain.clone(),
            cell_origin: self.cell_origin,
            packing_prev: 0.0,
            next: 0,
            lateral: self.lateral.clone(),
        }
    }

    /// A recorded block: its cells (without the margins), the grain, and its predecessor's
    /// flux slope (which reads it), in block order.
    fn finish(&mut self, d: Done) -> Slope {
        let b = d.b;
        debug_assert_eq!(b, self.next);
        let (cells, nb) = (d.cells, self.nb);
        let i0 = b * nb - d.j0;
        let mut bx = Vec::with_capacity(self.p.layers * nb);
        let mut by = Vec::with_capacity(self.p.layers * nb);
        for l in 0..self.p.layers {
            bx.extend_from_slice(&d.mx[l * cells + i0..l * cells + i0 + nb]);
            by.extend_from_slice(&d.my[l * cells + i0..l * cells + i0 + nb]);
        }
        if let Some((seed, name)) = self.grain.clone() {
            let i0 = b * nb + self.cell_origin as usize;
            self.grain_block(&mut bx, &mut by, i0, b * nb == 0, seed, &name);
        }
        self.rec.push((b, bx, by));
        if let Some(q) = d.demag {
            self.demag.push((b, q));
        }
        self.next += 1;
        if b >= 1 {
            let g = self.slope_block(b - 1);
            self.rec.retain(|(c, _, _)| *c + 2 > b);
            self.demag.retain(|(c, _)| *c + 2 > b);
            return Some(g);
        }
        None
    }

    /// The reference's `_grain`: the block's cells from i0 times 1 + the packing field (an
    /// AR(1) along the tape, one for the coating's depth, its state carried from block to
    /// block), plus the Poisson particle noise.
    /// `i0` counts from the tape's start at t = 0 (the origin's cell included); `first`:
    /// the stream's first block, where the packing field starts from its stationary law.
    fn grain_block(
        &mut self,
        mx: &mut [f64],
        my: &mut [f64],
        i0: usize,
        first: bool,
        seed: u64,
        name: &str,
    ) {
        let (nb, layers) = (self.nb, self.p.layers);
        let ds = self.p.ds_m;
        let dy = self.p.coating_m / layers as f64;
        let n_cell = self.p.packing * ds * dy * self.p.track_m / self.p.particle_volume_m3;
        let (mut cx, mut cy) = (0.0, 0.0);
        for a in &self.axes {
            cx += a[2] * a[0] * a[0];
            cy += a[2] * a[1] * a[1];
        }
        let (sx, sy) = ((cx / n_cell).sqrt(), (cy / n_cell).sqrt());
        let mut d = vec![0.0; nb];
        if self.p.packing_sigma > 0.0 {
            let rho = (-ds / self.p.packing_corr_m).exp();
            let c = (1.0 - rho * rho).sqrt();
            let k = crate::noise::key(seed, name, 0);
            if first {
                let mut start = [0.0];
                crate::noise::normals(k, i0 as u64, &mut start);
                self.packing_prev = start[0];
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
    /// The flux slope over w cells; a reduced block's with its bias's D(k) (demag);
    /// `cross`: the slope a neighbouring head reads (`cross_hx_spectrum`; the medium's
    /// crosstalk).
    fn flux_slope(
        &mut self,
        mx: &[f64],
        my: &[f64],
        w: usize,
        demag: Option<&ReductionPoint>,
        head: Head,
        cross: bool,
    ) -> Vec<f64> {
        let ext = (4.0 * (head.gap / 2.0 + head.pole + head.relax) / self.p.ds_m).ceil() as usize;
        let n = (w + 2 * ext).next_power_of_two();
        let freq = 1.0 / (n as f64 * self.p.ds_m);
        let ks: Vec<f64> = (0..n / 2 + 1)
            .map(|j| 2.0 * PI * (j as f64 * freq))
            .collect();
        let x = if cross {
            self.p.crosstalk.clone()
        } else {
            None
        };
        if let Some(x) = &x
            && !self.lateral.iter().any(|(m, _)| *m == n)
        {
            let lat = ks
                .iter()
                .map(|&k| lateral_factor(k, x.pitch_m, x.contour_width_m))
                .collect();
            self.lateral.push((n, lat));
        }
        let p = &self.p;
        let lat: &[f64] = match &x {
            Some(_) => {
                &self
                    .lateral
                    .iter()
                    .find(|(m, _)| *m == n)
                    .expect("computed above")
                    .1
            }
            None => &[],
        };
        let dy = p.coating_m / p.layers as f64;
        let (layers, spacing, k_max) = (p.layers, p.spacing_m, self.k_max);
        let mut acc = vec![Complex64::new(0.0, 0.0); n / 2 + 1];
        for l in 0..layers {
            let y = spacing + (l as f64 + 0.5) * dy;
            let fx = rfft(&mut self.planner, &mx[l * w..(l + 1) * w], n);
            let fy = rfft(&mut self.planner, &my[l * w..(l + 1) * w], n);
            for (j, a) in acc.iter_mut().enumerate() {
                let sx = match &x {
                    None => hx_spectrum(&head, ks[j], y),
                    Some(x) => cross_hx_spectrum(&head, ks[j], y, x, lat[j]),
                };
                *a += fx[j] * sx;
                let sy = Complex64::new(0.0, ks[j].signum() * sx);
                *a -= fy[j] * sy;
            }
        }
        for (j, a) in acc.iter_mut().enumerate() {
            let k = ks[j];
            *a *= Complex64::new(0.0, k);
            if let (Some(r), Some(q)) = (&p.reduced, demag) {
                // The reduced medium's demagnetization correction (the block's bias's).
                *a *= interp(k, &r.demag_k, &q.demag_d);
            }
            let u = ((k / k_max - 0.8) / 0.2).clamp(0.0, 1.0);
            *a *= if k >= k_max {
                0.0
            } else {
                0.5 * (1.0 + (PI * u).cos())
            };
        }
        irfft(&mut self.planner, &acc, n, w)
    }

    /// Block b's flux slopes over its cells and 2 either side: the repro head's, the cross
    /// slope a neighbouring head reads (crosstalk), the record head's and its cross
    /// (Sel-Sync); the ones the medium hasn't empty.
    fn slope_block(&mut self, b: usize) -> BlockSlopes {
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
        let demag = self
            .demag
            .iter()
            .find(|(c, _)| *c == b)
            .map(|(_, q)| q.clone());
        let (rep, rec) = (self.rep_head, self.rec_head);
        let (cross, sync) = (self.p.crosstalk.is_some(), self.p.sync.is_some());
        let mut slope = |head: Head, x: bool, on: bool| {
            if !on {
                return Vec::new();
            }
            let g = self.flux_slope(&wx, &wy, w, demag.as_deref(), head, x);
            g[nr - 2..nr + nb + 2].to_vec()
        };
        BlockSlopes {
            b,
            own: slope(rep, false, true),
            cross: slope(rep, true, cross),
            sync: slope(rec, false, sync),
            sync_cross: slope(rec, true, sync && cross),
        }
    }
}

/// A block's predecessor's flux slopes, if the block has a predecessor.
type Slope = Option<BlockSlopes>;

/// A reduced medium's apertures as FIRs on the samples: (k0, M_x's, M_y's), layers x taps.
type Firs = (i64, Vec<Vec<f64>>, Vec<Vec<f64>>);

/// A reduced block to record (`record_reduced`): its cells' times at the gap in samples,
/// and the samples its FIRs read (from n_lo + k0, the stream's ends held).
struct ReducedJob {
    b: usize,
    j0: usize,
    u: Vec<f64>,
    n_lo: i64,
    seg: Vec<f64>,
    firs: Firs,
    /// The bias's tables at the block's recording.
    point: Arc<ReductionPoint>,
}

/// A reduced medium's thread: each block recorded (`record_reduced`) and finished
/// (`Finisher`) in the order submitted; per block its predecessor's slope, if any. Its
/// slack is the head distance (a block is read ~3 blocks after it's recorded), so a block's
/// cost spreads over the audio instead of landing in one buffer.
struct ReducedWorker {
    jobs: Option<mpsc::Sender<ReducedJob>>,
    // In a mutex only so the stream is Sync (Python's stream class); one thread uses it.
    done: Mutex<mpsc::Receiver<Slope>>,
    thread: Option<JoinHandle<()>>,
}

impl ReducedWorker {
    fn spawn(h_a_m: Vec<f64>, mut fin: Finisher) -> Self {
        let (jobs, rx) = mpsc::channel::<ReducedJob>();
        let (tx, done) = mpsc::channel();
        let thread = std::thread::Builder::new()
            .name("tape recording (reduced)".into())
            .spawn(move || {
                let layers = fin.p.layers;
                while let Ok(job) = rx.recv() {
                    let d = record_reduced(&h_a_m, layers, job);
                    if tx.send(fin.finish(d)).is_err() {
                        break;
                    }
                }
            })
            .expect("tape: the reduced recording thread");
        ReducedWorker {
            jobs: Some(jobs),
            done: Mutex::new(done),
            thread: Some(thread),
        }
    }

    fn submit(&self, job: ReducedJob) -> Result<(), String> {
        self.jobs
            .as_ref()
            .and_then(|j| j.send(job).ok())
            .ok_or_else(|| "tape: the recording thread stopped".to_string())
    }

    /// The next finished block's predecessor's slope (None for block 0), waiting for it.
    fn next(&self) -> Result<Slope, String> {
        self.done
            .lock()
            .map_err(|_| "tape: the recording thread stopped".to_string())?
            .recv()
            .map_err(|_| "tape: the recording thread stopped".to_string())
    }
}

impl Drop for ReducedWorker {
    fn drop(&mut self) {
        self.jobs.take();
        if let Some(t) = self.thread.take() {
            let _ = t.join();
        }
    }
}

/// `ReducedStream._record_block` on a job: each layer's apertures as FIRs on the samples,
/// read cubic at each cell's time at the gap, then the table (M_x) and the
/// saturation-scaled M_y.
fn record_reduced(h_a_m: &[f64], layers: usize, job: ReducedJob) -> Done {
    let ReducedJob {
        b,
        j0,
        u,
        n_lo,
        seg,
        firs: (_, cx, cy),
        point: q,
    } = job;
    let taps = cx[0].len();
    let rows = seg.len() + 1 - taps;
    let fir = |c: &[f64]| -> Vec<f64> {
        (0..rows)
            .map(|row| {
                let mut acc = 0.0;
                for (k, ck) in c.iter().enumerate() {
                    acc += ck * seg[row + k];
                }
                acc
            })
            .collect()
    };
    let cells = u.len();
    let hmax = h_a_m[h_a_m.len() - 1];
    let mut mx = vec![0.0; layers * cells];
    let mut my = vec![0.0; layers * cells];
    for l in 0..layers {
        let gx = fir(&cx[l]);
        let gy = fir(&cy[l]);
        for (i, &ui) in u.iter().enumerate() {
            let g = cubic_held(&gx, ui, n_lo).clamp(-hmax, hmax);
            let m = table(h_a_m, &q, l, g);
            let lin = q.slope[l] * g;
            let sat = if lin.abs() > 1e-12 { m / lin } else { 1.0 };
            mx[l * cells + i] = m;
            my[l * cells + i] = sat * cubic_held(&gy, ui, n_lo);
        }
    }
    Done {
        b,
        j0,
        cells,
        mx,
        my,
        demag: Some(q),
    }
}

/// The tape between the heads (see the module docs).
pub struct TapeStream {
    p: TapeParams,
    fs: f64,
    /// What recording reads, shared with the worker.
    ctx: Arc<Ctx>,
    nb: usize,
    nm: usize,
    scale: f64,
    /// The pushed samples first, first + 1, ... (literal bias: the fast samples).
    h: Vec<f64>,
    /// The literal bias's samples per push (1: the medium's own bias).
    m: usize,
    first: usize,
    n: usize,
    /// Flux slopes per block (over the block's cells and 2 either side).
    slopes: Vec<BlockSlopes>,
    /// The Sel-Sync readout's EMF scale (the record head's field per ampere's; 0 without).
    sync_scale: f64,
    /// The next block to finish (its grain, its predecessor's slope) and the next to hand
    /// the worker: the blocks in between are being recorded.
    next_rec: usize,
    next_submit: usize,
    worker: Worker,
    /// The full medium's finishing (on this thread).
    fin: Finisher,
    /// The reduced medium's thread, if reduced, and its tables at the bias now.
    reduced: Option<ReducedWorker>,
    point: Option<Arc<ReductionPoint>>,
    /// The transport: with flutter, the tape's position at the record gap per sample
    /// (s[k] at sample s_first + k, one ahead of the pushes), the speed at its last, the
    /// resonances' filter states.
    moving: bool,
    transport_seed: u64,
    zi: Vec<[f64; 2]>,
    s: Vec<f64>,
    s_first: usize,
    v_last: f64,
    /// Varispeed: the motor's factor on the speed per sample (fac[i] at sample fac_first +
    /// i; 1 throughout without varispeed), its resonator (b0, a1, a2, z0, z1), and the
    /// speed before t = 0 (the supply's first frequency's, held).
    fac: Vec<f64>,
    fac_first: usize,
    motor: [f64; 5],
    v0: f64,
    /// The run's first sample in a longer run from t = 0 (`set_origin`): the transport's
    /// flutter and noise continue from there.
    origin: u64,
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
            exact_gap: false,
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
            gpu: false,
        });
        let finisher = || Finisher {
            p: p.clone(),
            axes: ctx.axes.clone(),
            rep_head,
            rec_head,
            nb,
            nr,
            k_max: 2.0 * PI * 0.45 * fs / p.speed_m_s,
            planner: FftPlanner::new(),
            rec: Vec::new(),
            demag: Vec::new(),
            grain: grain.map(|(seed, name)| (seed, name.to_string())),
            cell_origin: 0,
            packing_prev: 0.0,
            next: 0,
            lateral: Vec::new(),
        };
        let mut st = TapeStream {
            fs,
            worker: Worker::spawn(ctx.clone()),
            fin: finisher(),
            reduced: p
                .reduced
                .as_ref()
                .map(|r| ReducedWorker::spawn(r.h_a_m.clone(), finisher())),
            point: p.reduced.as_ref().map(|r| Arc::new(r.at(p.hg_bias_a_m))),
            fac: vec![1.0],
            fac_first: 0,
            motor: [1.0, 0.0, 0.0, 0.0, 0.0],
            v0: p.speed_m_s,
            ctx,
            nb,
            nm,
            scale: MU0 * p.track_m * p.ms_a_m * p.rep_h_per_a * dy,
            sync_scale: MU0
                * p.track_m
                * p.ms_a_m
                * p.sync.as_ref().map_or(0.0, |y| y.h_per_a)
                * dy,
            h: Vec::new(),
            m: p.bias_substeps.unwrap_or(1),
            first: 0,
            n: 0,
            slopes: Vec::new(),
            next_rec: 0,
            next_submit: 0,
            moving: !(p.flutter.is_empty() && p.flutter_noise.is_empty()) || p.varispeed.is_some(),
            transport_seed,
            zi: vec![[0.0; 2]; p.flutter_noise.len()],
            s: vec![0.0],
            s_first: 0,
            v_last: 0.0,
            origin: 0,
            p: p.clone(),
        };
        // With varispeed the first speed waits for the supply's first frequency.
        if st.moving && p.varispeed.is_none() {
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

    /// Record on the GPU in f32 (`Recording::gpu`; TAPE_SPEED_PLAN.md P5) or on the CPU in
    /// f64 (the default). Refused without a GPU or the `gpu` feature. Before the first push.
    pub fn set_gpu(&mut self, gpu: bool) -> Result<(), String> {
        if self.next_submit > 0 {
            return Err("tape: set_gpu after recording started".into());
        }
        if gpu == self.ctx.gpu {
            return Ok(());
        }
        if gpu {
            gpu_available()?;
        }
        let mut ctx = Ctx::clone(&self.ctx);
        ctx.gpu = gpu;
        self.ctx = Arc::new(ctx);
        self.worker = Worker::spawn(self.ctx.clone());
        Ok(())
    }

    /// Start at sample `k0` of a longer run from t = 0 (`Options::origin_samples`;
    /// TAPE_SPEED_PLAN.md P3): the transport's flutter and its random parts continue from
    /// there (their filters start at rest, as at t = 0), and the grain from the cell the
    /// tape's nominal speed has brought to the record gap by then (a continuous run's
    /// position differs by its flutter's integral: the grain is the same coating, not the
    /// same cells). Before the first push.
    pub fn set_origin(&mut self, k0: u64) -> Result<(), String> {
        if self.n > 0 || self.next_submit > 0 {
            return Err("tape: set_origin after the first push".into());
        }
        if k0 == self.origin {
            return Ok(());
        }
        self.origin = k0;
        let cell = (k0 as f64 / self.fs * self.p.speed_m_s / self.p.ds_m).round() as u64;
        self.fin.cell_origin = cell;
        if let Some(r) = &self.p.reduced {
            let mut fin = self.fin.fresh();
            fin.cell_origin = cell;
            self.reduced = Some(ReducedWorker::spawn(r.h_a_m.clone(), fin));
        }
        self.zi = vec![[0.0; 2]; self.p.flutter_noise.len()];
        if self.moving && self.p.varispeed.is_none() {
            self.v_last = self.speeds(0, 1)[0];
        }
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
        let o = self.origin as usize;
        let mut eps: Vec<f64> = (k0..k1)
            .map(|k| {
                let t = (k + o) as f64 / fs;
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
                (k0 + o) as u64,
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
        if self.p.varispeed.is_some() {
            return eps
                .iter()
                .enumerate()
                .map(|(i, e)| v * (1.0 + e) * self.fac_at(k0 + i))
                .collect();
        }
        eps.iter().map(|e| v * (1.0 + e)).collect()
    }

    /// The motor's factor on the speed at sample k (held at the known ends).
    fn fac_at(&self, k: usize) -> f64 {
        self.fac[k.saturating_sub(self.fac_first).min(self.fac.len() - 1)]
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
        let fs = self.fs;
        if !self.moving {
            return self.p.speed_m_s * t;
        }
        let u = t * fs;
        let i = u.floor();
        let f = u - i;
        let i = i as i64;
        let (first, n) = (self.s_first as i64, self.s.len() as i64);
        let tap = |k: i64| {
            if k < 0 {
                self.v0 * k as f64 / fs
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
            return Some(sv / self.v0);
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
    /// its left neighbour and not below its right, or the reverse), refined by
    /// `refine_extremum` over the five samples around it (the parabola through three where
    /// the buffer's newest edge has no second neighbour): (times, values).
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
            let (d, v) = if i >= 2 && i + 2 < self.h.len() {
                refine_extremum(self.h[i - 2], a, b, c, self.h[i + 2])
            } else {
                parabola_extremum(a, b, c)
            };
            let tk = (k as f64 + d + 1.0 - 2.0 * m) / mf;
            if t0 <= tk && tk <= t1 {
                ts.push(tk);
                vs.push(v);
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

    /// A recorded block finished on this thread (the full medium's), its predecessor's
    /// slope kept.
    fn finish(&mut self, d: Done) {
        self.next_rec += 1;
        if let Some(g) = self.fin.finish(d) {
            self.slopes.push(g);
        }
    }

    /// Block b's reduced job: its cells' times at the gap (in samples) and the samples its
    /// FIRs read, held at the stream's ends (`ReducedStream._record_block`).
    fn prep_reduced(&self, b: usize) -> ReducedJob {
        let (j0, j1, _, _) = self.span(b);
        let (ds, fs, v) = (self.p.ds_m, self.fs, self.p.speed_m_s);
        let fp: Vec<f64> = if self.moving {
            (0..self.s.len())
                .map(|i| (self.s_first + i) as f64 / fs)
                .collect()
        } else {
            Vec::new()
        };
        let u: Vec<f64> = (j0..j1)
            .map(|j| {
                let s = j as f64 * ds;
                let tc = if self.moving {
                    interp(s, &self.s, &fp)
                } else {
                    s / v
                };
                tc * fs
            })
            .collect();
        let umin = u.iter().fold(f64::INFINITY, |a, &x| a.min(x));
        let umax = u.iter().fold(f64::NEG_INFINITY, |a, &x| a.max(x));
        let n_lo = umin.floor() as i64 - 1;
        let n_hi = umax.floor() as i64 + 2;
        // The apertures at the block's speed (its middle cell's sample's).
        let ratio = if self.p.varispeed.is_some() {
            self.fac_at(u[u.len() / 2].floor().max(0.0) as usize)
        } else {
            1.0
        };
        let point = self.point.clone().expect("a reduced medium");
        let firs = self
            .p
            .reduced
            .as_ref()
            .expect("a reduced medium")
            .firs(&point, fs, ratio);
        let (k0, taps) = (firs.0, firs.1[0].len());
        let (first, len) = (self.first as i64, self.h.len() as i64);
        let rows = (n_hi - n_lo + 1) as usize;
        let seg = (0..rows + taps - 1)
            .map(|i| self.h[(n_lo + k0 + i as i64 - first).clamp(0, len - 1) as usize])
            .collect();
        ReducedJob {
            b,
            j0,
            u,
            n_lo,
            seg,
            firs,
            point,
        }
    }

    /// The reduced medium's bias (its deep-gap peak, A/m) for the blocks recorded from now
    /// on (BIAS as a knob: `ReducedStream.set_bias`); the recording so far stays.
    pub fn set_bias(&mut self, hg_bias_a_m: f64) -> Result<(), String> {
        let r = self
            .p
            .reduced
            .as_ref()
            .ok_or("tape: only a reduced medium's bias is set mid-run")?;
        if !(hg_bias_a_m > 0.0 && hg_bias_a_m.is_finite()) {
            return Err("tape: the bias is positive".into());
        }
        self.point = Some(Arc::new(r.at(hg_bias_a_m)));
        self.p.hg_bias_a_m = hg_bias_a_m;
        Ok(())
    }

    /// [`push`](Self::push) for each of hs in turn (the same results, any chunking), the
    /// EMFs into out.
    pub fn push_many(&mut self, hs: &[f64], out: &mut Vec<f64>) -> Result<(), String> {
        self.push_inner(hs, None, out, None)
    }

    /// [`push_many`](Self::push_many) (with the capstan's supply frequencies, if it has
    /// varispeed) and, per push, the medium's other readouts ([`Readouts`]: crosstalk's
    /// cross EMF, Sel-Sync's record head; the reference's `cross_out`, `sync_out`,
    /// `sync_cross_out`), cleared first.
    pub fn push_many_readouts(
        &mut self,
        hs: &[f64],
        supply_hz: Option<&[f64]>,
        out: &mut Vec<f64>,
        readouts: &mut Readouts,
    ) -> Result<(), String> {
        readouts.clear();
        self.push_inner(hs, supply_hz, out, Some(readouts))
    }

    /// [`push_many`](Self::push_many) with the capstan's supply frequency (Hz) at each
    /// push (one per push; a medium with varispeed needs it): the motor's speed follows it
    /// a sample late.
    pub fn push_many_supply(
        &mut self,
        hs: &[f64],
        supply_hz: &[f64],
        out: &mut Vec<f64>,
    ) -> Result<(), String> {
        self.push_inner(hs, Some(supply_hz), out, None)
    }

    fn push_inner(
        &mut self,
        hs: &[f64],
        supply: Option<&[f64]>,
        out: &mut Vec<f64>,
        mut readouts: Option<&mut Readouts>,
    ) -> Result<(), String> {
        let m = self.m;
        if !hs.len().is_multiple_of(m) {
            return Err(format!("tape: literal bias pushes {m} samples each"));
        }
        if let Some(vs) = self.p.varispeed.clone() {
            let sup = supply.ok_or("tape: varispeed needs the supply's frequency")?;
            if sup.len() != hs.len() / m {
                return Err("tape: one supply frequency per push".into());
            }
            if self.n == 0 && !sup.is_empty() {
                // The motor starts steady at the first frequency (the tape ran at it).
                let r0 = sup[0] / vs.nominal_hz;
                let (b0, a1, a2) = vs.coefficients(self.fs);
                self.fac = vec![r0];
                self.fac_first = 0;
                self.v0 = self.p.speed_m_s * r0;
                self.motor = [b0, a1, a2, r0 * (1.0 - b0), -a2 * r0];
                if self.moving {
                    self.v_last = self.speeds(0, 1)[0];
                }
            }
            // The factor at the next sample after each push's frequency (lfilter, DF2T).
            let [b0, a1, a2, mut z0, mut z1] = self.motor;
            for &f in sup {
                let x = f / vs.nominal_hz;
                let y = z0 + b0 * x;
                z0 = z1 - y * a1;
                z1 = -y * a2;
                self.fac.push(y);
            }
            self.motor = [b0, a1, a2, z0, z1];
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
            if let Some(rw) = &self.reduced {
                rw.submit(self.prep_reduced(self.next_submit))?;
                self.next_submit += 1;
            } else {
                let job = self.prep(self.next_submit)?;
                self.worker.submit(job)?;
                self.next_submit += 1;
            }
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
        if self.p.varispeed.is_some() && cut > self.fac_first {
            self.fac.drain(..cut - self.fac_first);
            self.fac_first = cut;
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
                    if let Some(rw) = &self.reduced {
                        let g = rw.next()?;
                        self.next_rec += 1;
                        if let Some(g) = g {
                            self.slopes.push(g);
                        }
                    } else {
                        let done = self.worker.next()?;
                        self.finish(done);
                    }
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
                if let Some(r) = readouts.as_deref_mut() {
                    for (v, on) in [
                        (&mut r.cross, self.p.crosstalk.is_some()),
                        (&mut r.sync, self.p.sync.is_some()),
                        (
                            &mut r.sync_cross,
                            self.p.crosstalk.is_some() && self.p.sync.is_some(),
                        ),
                    ] {
                        if on {
                            v.push(0.0);
                        }
                    }
                }
                continue;
            }
            let b = u.floor() as usize / self.nb;
            let g = self
                .slopes
                .iter()
                .find(|g| g.b == b)
                .ok_or("tape: a block was read before it was recorded")?;
            let origin = (b * self.nb) as i64 - 2;
            // The EMF goes with the tape's speed (varispeed's; flutter's left out).
            let vk = if self.p.varispeed.is_some() {
                v * self.fac_at(m + 1)
            } else {
                v
            };
            let at = u - origin as f64;
            out.push(-vk * self.scale * cubic_held(&g.own, at, 0));
            if let Some(r) = readouts.as_deref_mut() {
                for (v, s, scale) in [
                    (&mut r.cross, &g.cross, self.scale),
                    (&mut r.sync, &g.sync, self.sync_scale),
                    (&mut r.sync_cross, &g.sync_cross, self.sync_scale),
                ] {
                    if !s.is_empty() {
                        v.push(-vk * scale * cubic_held(s, at, 0));
                    }
                }
            }
            last = Some(b);
        }
        if let Some(b) = last {
            self.slopes.retain(|g| g.b + 1 >= b);
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
