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

use circuitsim::partition::simulate_partitioned_controls;

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

/// `samples` (full scale 1.0, at `s.sample_rate`) through `circuit` with `values`, its
/// control inputs (if any) at 0 V. `progress(fraction)` is called ~200 times; `cancel`
/// stops the run.
pub fn render(
    circuit: &Circuit,
    values: &Values,
    samples: &[f64],
    s: &Settings,
    progress: impl FnMut(f64),
    cancel: &AtomicBool,
) -> Result<Rendered, String> {
    render_controls(circuit, values, samples, &[], s, progress, cancel)
}

/// [`render`] with the circuit's control inputs driven: `controls` are (name, volts at
/// `s.sample_rate`, as long as `samples`), Python's `run_transient(controls=)`; a control
/// input not named is held at 0 V.
pub fn render_controls(
    circuit: &Circuit,
    values: &Values,
    samples: &[f64],
    controls: &[(&str, &[f64])],
    s: &Settings,
    mut progress: impl FnMut(f64),
    cancel: &AtomicBool,
) -> Result<Rendered, String> {
    if samples.is_empty() {
        return Err("nothing to render".into());
    }
    let t0 = std::time::Instant::now();
    let ir = circuit.build(values)?;
    if let Some((name, _)) = controls
        .iter()
        .find(|(n, _)| !ir.controls.iter().any(|c| c.name == *n))
    {
        return Err(format!("the circuit has no control input {name}"));
    }
    if let Some((name, c)) = controls.iter().find(|(_, c)| c.len() != samples.len()) {
        return Err(format!(
            "control {name}: {} samples for {} of input",
            c.len(),
            samples.len()
        ));
    }
    let zeros = vec![0.0; samples.len()];
    let given: Vec<&[f64]> = ir
        .controls
        .iter()
        .map(|c| {
            controls
                .iter()
                .find(|(n, _)| *n == c.name)
                .map_or(zeros.as_slice(), |(_, x)| *x)
        })
        .collect();
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
    let ctl = control_streams(&given, n0, s.sample_rate, s.sim_rate(), x_up.len());
    let ctl: Vec<&[f64]> = ctl.iter().map(Vec::as_slice).collect();
    let second = s.partition_sections(&ir);
    // Multi-rate sections (a literal tape's record side, its substeps) always run
    // partitioned, as Python's `circuitsim.simulate` runs them: the 351 at production.
    let out = if second.is_empty() && !ir.multirate() {
        circuitsim::simulate_controls(&ir, &x_up, &ctl, h, &opts, every, report)
    } else {
        simulate_partitioned_controls(
            &ir,
            &second,
            s.coupling()?,
            &x_up,
            &ctl,
            h,
            &opts,
            every,
            report,
        )
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

/// The control inputs on the simulation's grid, as Python's `fast.control_streams`: each
/// (`n` samples at `rate`) behind `n0` samples of its first value, interpolated linearly
/// onto `n_sim` samples at `sim_rate` (held past its end), with `np.interp`'s arithmetic.
fn control_streams(
    controls: &[&[f64]],
    n0: usize,
    rate: u32,
    sim_rate: u32,
    n_sim: usize,
) -> Vec<Vec<f64>> {
    controls
        .iter()
        .map(|c| {
            let first = c.first().copied().unwrap_or(0.0);
            let fp: Vec<f64> = std::iter::repeat_n(first, n0)
                .chain(c.iter().copied())
                .collect();
            let xp: Vec<f64> = (0..fp.len()).map(|i| i as f64 / rate as f64).collect();
            (0..n_sim)
                .map(|i| interp(i as f64 / sim_rate as f64, &xp, &fp))
                .collect()
        })
        .collect()
}

/// `np.interp(x, xp, fp)` on a rising `xp` starting at or below `x` (numpy's
/// `arr_interp`: the last `j` with `xp[j] <= x`, `fp[j]` there and at the end, else
/// `slope * (x - xp[j]) + fp[j]`).
fn interp(x: f64, xp: &[f64], fp: &[f64]) -> f64 {
    let n = xp.len();
    if n == 0 {
        return 0.0;
    }
    if x >= xp[n - 1] {
        return fp[n - 1];
    }
    if x <= xp[0] {
        return fp[0];
    }
    // A uniform grid's guess, then the exact index (as numpy's search finds it).
    let mut j = ((x / xp[1]) as usize).min(n - 2);
    while j > 0 && xp[j] > x {
        j -= 1;
    }
    while j + 1 < n && xp[j + 1] <= x {
        j += 1;
    }
    if xp[j] == x {
        return fp[j];
    }
    let slope = (fp[j + 1] - fp[j]) / (xp[j + 1] - xp[j]);
    slope * (x - xp[j]) + fp[j]
}
