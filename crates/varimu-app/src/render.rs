//! Offline renders at a quality's settings (production by default): the port of
//! `varimu.sim.fast.run_transient` and of what `varimu.sim.runner.render` keeps, so a
//! render here equals a Python render of the same input and values bit for bit (the
//! same IR, the same engine, the same resampling; NATIVE_APP_PLAN.md, R2).
//!
//! The steps, as Python takes them: the input in circuit volts, `settle_s` of its
//! first sample in front; to the host rate (if the quality has one) and up by the
//! oversampling (scipy's `resample_poly`); `circuitsim::simulate` (partitioned if the
//! quality names sections); every probe decimated back, to the project's rate, the
//! settling dropped; then each probe as float32 (what Python's render cache keeps),
//! and the output divided back to full scale.

use std::sync::atomic::{AtomicBool, Ordering};

use circuitsim::partition::simulate_partitioned;

use crate::live::{Circuit, Values};
use crate::resample::{Pad, resample, resample_poly};
use crate::settings::Settings;

/// Progress callbacks per run (as the Python binding's).
const PROGRESS_CALLS: usize = 200;

/// A finished render.
#[derive(Debug, Clone)]
pub struct Rendered {
    /// The output at the project's rate, full scale 1.0 (`Render.out`).
    pub out: Vec<f64>,
    /// Every probe in circuit volts, before the float32 cast (`TransientResult.vectors`).
    pub probes: Vec<(String, Vec<f64>)>,
    pub sample_rate: u32,
    pub wall_s: f64,
}

impl Rendered {
    /// Seconds of wall clock per second of audio.
    pub fn realtime_factor(&self) -> f64 {
        self.wall_s / (self.out.len().max(1) as f64 / self.sample_rate as f64)
    }
}

/// `samples` (full scale 1.0, at `s.sample_rate`) through `circuit` with `values`.
/// `progress(fraction)` is called ~200 times; `cancel` stops the run.
pub fn render(
    circuit: &Circuit,
    values: &Values,
    samples: &[f64],
    s: &Settings,
    mut progress: impl FnMut(f64),
    cancel: &AtomicBool,
) -> Result<Rendered, String> {
    if samples.is_empty() {
        return Err("nothing to render".into());
    }
    let t0 = std::time::Instant::now();
    let ir = circuit.build(values)?;
    let fs = circuit.full_scale(s);
    let v = fs.input_v;
    // with_settle: `round(settle_s * sample_rate)` of the first sample in front.
    let n0 = (s.settle_s * s.sample_rate as f64).round_ties_even() as usize;
    let mut x: Vec<f64> = Vec::with_capacity(n0 + samples.len());
    let first = samples[0] * v;
    x.resize(n0, first);
    x.extend(samples.iter().map(|u| u * v));
    let n = x.len();
    let k = s.oversample as usize;
    let xh = resample(&x, s.sample_rate, s.host());
    let x_up = if k > 1 {
        resample_poly(&xh, k, 1, Pad::Zero)
    } else {
        xh.clone()
    };
    let opts = s.run_options()?;
    let h = 1.0 / s.sim_rate() as f64;
    let total = x_up.len();
    let every = total.div_ceil(PROGRESS_CALLS);
    let report = |done: usize| {
        progress(done as f64 / total as f64);
        if cancel.load(Ordering::Relaxed) {
            Err(circuitsim::Error::new("cancelled"))
        } else {
            Ok(())
        }
    };
    let second = s.partition_sections(&ir);
    let out = if second.is_empty() {
        circuitsim::simulate_with_progress(&ir, &x_up, h, &opts, every, report)
    } else {
        simulate_partitioned(&ir, &second, s.coupling()?, &x_up, h, &opts, every, report)
    }
    .map_err(|e| e.to_string())?;
    let back = |p: &[f64]| -> Vec<f64> {
        let d = if k > 1 {
            resample_poly(p, 1, k, Pad::Edge)
        } else {
            p.to_vec()
        };
        let d = &d[..xh.len().min(d.len())];
        let r = resample(d, s.host(), s.sample_rate);
        r[n0.min(n)..n.min(r.len())].to_vec()
    };
    let probes: Vec<(String, Vec<f64>)> = out
        .names
        .iter()
        .zip(&out.values)
        .map(|(name, p)| (name.clone(), back(p)))
        .collect();
    let vout = &probes
        .iter()
        .find(|(n, _)| n == "v(out)")
        .ok_or("the circuit has no `out` probe")?
        .1;
    let out = vout
        .iter()
        .map(|&y| (y as f32 as f64) / fs.output_v)
        .collect();
    Ok(Rendered {
        out,
        probes,
        sample_rate: s.sample_rate,
        wall_s: t0.elapsed().as_secs_f64(),
    })
}
