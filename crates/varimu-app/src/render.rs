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
    /// A stereo circuit's right output (its `out_r` probe), as `out`; None for a mono one.
    pub out_r: Option<Vec<f64>>,
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
    progress: impl FnMut(f64),
    cancel: &AtomicBool,
) -> Result<Rendered, String> {
    render_at(circuit, values, samples, controls, s, 0, progress, cancel)
}

/// How a long render is cut into pieces run at once ([`render_pieces`]; Python's
/// `fast.run_transient_chunked`, TAPE_SPEED_PLAN.md P3).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Pieces {
    /// Each piece's length.
    pub chunk_s: f64,
    /// How early each piece after the first starts (its input faded in over its first
    /// 50 ms or half): it must cover the circuit's memory of its input.
    pub warmup_s: f64,
    /// The raised-cosine crossfade into the next piece.
    pub fade_s: f64,
}

/// A tape machine's print in pieces (the layout P3 measured on the 351: 30 s pieces, 2 s of
/// warm-up, a 10 ms crossfade; bands within 0.007 dB of the whole print, no seam seen).
/// Fixed, so a print is the same on any machine: the cores only set how many run at once.
pub const PRINT_PIECES: Pieces = Pieces {
    chunk_s: 30.0,
    warmup_s: 2.0,
    fade_s: 0.01,
};

/// One piece's probes: (name, samples kept).
type PieceProbes = Vec<(String, Vec<f64>)>;

/// [`render`] in pieces of `p.chunk_s` run at once on up to `workers` threads, each at its
/// place in the whole run (circuitsim's `origin_samples`: the mains, the noise, a tape's
/// transport and grain continue the whole run's), joined by crossfades: Python's
/// `fast.run_transient_chunked`, step for step. What a piece can't continue is what its
/// warm-up doesn't bring back (a free oscillator's phase, a tape's grain cells). One
/// piece is a plain [`render`]. No control inputs.
#[allow(clippy::too_many_arguments)]
pub fn render_pieces(
    circuit: &Circuit,
    values: &Values,
    samples: &[f64],
    s: &Settings,
    p: Pieces,
    workers: usize,
    mut progress: impl FnMut(f64),
    cancel: &AtomicBool,
) -> Result<Rendered, String> {
    let (fs, n) = (s.sample_rate as f64, samples.len());
    let c = (p.chunk_s * fs).round_ties_even() as usize;
    let w = (p.warmup_s * fs).round_ties_even() as usize;
    let f = ((p.fade_s * fs).round_ties_even() as usize).max(1);
    if c <= f {
        return Err("render_pieces: chunk_s must exceed fade_s".into());
    }
    if n <= c {
        return render(circuit, values, samples, s, progress, cancel);
    }
    let t0 = std::time::Instant::now();
    let ramp = (w / 2).min((0.05 * fs).round_ties_even() as usize);
    // Past what a piece keeps, so the resampling filters' edges fall outside it.
    let tail = (0.02 * fs).round_ties_even() as usize;
    let starts: Vec<usize> = (0..n).step_by(c).collect();
    let span = |s0: usize| (s0.saturating_sub(w), n.min(s0 + c + f + tail));
    let total: usize = starts.iter().map(|&s0| span(s0).1 - span(s0).0).sum();
    let done: Vec<std::sync::atomic::AtomicU64> = starts
        .iter()
        .map(|_| std::sync::atomic::AtomicU64::new(0))
        .collect();
    let next = std::sync::atomic::AtomicUsize::new(0);
    let finished = std::sync::atomic::AtomicUsize::new(0);
    // Set by the caller's cancel or by a piece that failed: the others stop too.
    let stop = AtomicBool::new(false);
    let results: std::sync::Mutex<Vec<Option<Result<PieceProbes, String>>>> =
        std::sync::Mutex::new(vec![None; starts.len()]);
    let piece = |j: usize| -> Result<PieceProbes, String> {
        let s0 = starts[j];
        let (a, b) = span(s0);
        let keep = n.min(s0 + c + f) - a;
        let mut u = samples[a..b].to_vec();
        if a > 0 && ramp > 0 {
            for (i, x) in u.iter_mut().take(ramp).enumerate() {
                *x *= 0.5 - 0.5 * (std::f64::consts::PI * i as f64 / ramp as f64).cos();
            }
        }
        let origin = (a as f64 / fs * s.sim_rate() as f64).round_ties_even() as u64;
        let len = (b - a) as f64;
        let r = render_at(
            circuit,
            values,
            &u,
            &[],
            s,
            origin,
            |x| done[j].store((x * len).to_bits(), Ordering::Relaxed),
            &stop,
        )?;
        Ok(r.probes
            .into_iter()
            .map(|(k, v)| (k, v[s0 - a..keep.min(v.len())].to_vec()))
            .collect())
    };
    std::thread::scope(|scope| {
        for _ in 0..workers.clamp(1, starts.len()) {
            scope.spawn(|| {
                loop {
                    let j = next.fetch_add(1, Ordering::Relaxed);
                    if j >= starts.len() {
                        break;
                    }
                    let r = piece(j);
                    if r.is_err() {
                        stop.store(true, Ordering::Relaxed);
                    }
                    results.lock().unwrap()[j] = Some(r);
                    finished.fetch_add(1, Ordering::Relaxed);
                }
            });
        }
        while finished.load(Ordering::Relaxed) < starts.len() {
            if cancel.load(Ordering::Relaxed) {
                stop.store(true, Ordering::Relaxed);
            }
            let sum: f64 = done
                .iter()
                .map(|d| f64::from_bits(d.load(Ordering::Relaxed)))
                .sum();
            progress(sum / total as f64);
            std::thread::sleep(std::time::Duration::from_millis(50));
        }
    });
    let pieces: Vec<Vec<(String, Vec<f64>)>> = results
        .into_inner()
        .unwrap()
        .into_iter()
        .map(|r| r.unwrap_or_else(|| Err("a piece didn't run".into())))
        .collect::<Result<_, _>>()?;
    let up: Vec<f64> = (0..f)
        .map(|i| 0.5 - 0.5 * (std::f64::consts::PI * (i as f64 + 0.5) / f as f64).cos())
        .collect();
    let mut probes: Vec<(String, Vec<f64>)> = pieces[0]
        .iter()
        .map(|(k, _)| (k.clone(), vec![0.0; n]))
        .collect();
    for (j, vecs) in pieces.iter().enumerate() {
        let s0 = starts[j];
        for ((_, out), (_, v)) in probes.iter_mut().zip(vecs) {
            if j == 0 {
                out[s0..s0 + v.len()].copy_from_slice(v);
                continue;
            }
            let m = f.min(v.len());
            for i in 0..m {
                out[s0 + i] = out[s0 + i] * (1.0 - up[i]) + v[i] * up[i];
            }
            out[s0 + m..s0 + v.len()].copy_from_slice(&v[m..]);
        }
    }
    let output_v = circuit.full_scale(s).output_v;
    let (out, out_r) = outputs(&probes, output_v)?;
    Ok(Rendered {
        out,
        out_r,
        probes,
        sample_rate: s.sample_rate,
        wall_s: t0.elapsed().as_secs_f64(),
    })
}

/// The output and a stereo circuit's right output from the probes (circuit volts): each
/// cast to float32 (what Python's render cache keeps), over the output's full scale.
fn outputs(
    probes: &[(String, Vec<f64>)],
    output_v: f64,
) -> Result<(Vec<f64>, Option<Vec<f64>>), String> {
    let scaled = |name: &str| {
        probes.iter().find(|(n, _)| n == name).map(|(_, v)| {
            v.iter()
                .map(|&y| (y as f32 as f64) / output_v)
                .collect::<Vec<f64>>()
        })
    };
    let out = scaled("v(out)").ok_or("the circuit has no `out` probe")?;
    Ok((out, scaled("v(out_r)")))
}

/// One run of [`render_controls`] starting `origin` simulation samples into a longer run.
#[allow(clippy::too_many_arguments)]
fn render_at(
    circuit: &Circuit,
    values: &Values,
    samples: &[f64],
    controls: &[(&str, &[f64])],
    s: &Settings,
    origin: u64,
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
    let opts = circuitsim::Options {
        origin_samples: origin,
        ..s.run_options()?
    };
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
    let (out, out_r) = outputs(&probes, fs.output_v)?;
    Ok(Rendered {
        out,
        out_r,
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::print::Prepared;
    use crate::settings::Quality;

    fn config() -> std::path::PathBuf {
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config")
    }

    #[test]
    fn pieces_join_into_the_whole_render() {
        let p = Prepared::load(&config(), "triode_stage_drawn", Quality::Draft1x, false).unwrap();
        let s = &p.settings;
        let fs = s.sample_rate as f64;
        let x: Vec<f64> = (0..(3.3 * fs) as usize)
            .map(|i| {
                let t = i as f64 / fs;
                0.3 * (2.0 * std::f64::consts::PI * 440.0 * t).sin() * (1.0 + 0.5 * (3.0 * t).sin())
            })
            .collect();
        let no = AtomicBool::new(false);
        let whole = render(&p.circuit, &Vec::new(), &x, s, |_| {}, &no).unwrap();
        let cut = Pieces {
            chunk_s: 1.0,
            warmup_s: 0.5,
            fade_s: 0.01,
        };
        let mut last = 0.0;
        let pieces =
            render_pieces(&p.circuit, &Vec::new(), &x, s, cut, 3, |f| last = f, &no).unwrap();
        assert_eq!(pieces.out.len(), whole.out.len());
        assert!(last > 0.0 && last <= 1.0 + 1e-12, "{last}");
        let rms = |v: &[f64]| (v.iter().map(|a| a * a).sum::<f64>() / v.len() as f64).sqrt();
        let diff: Vec<f64> = whole
            .out
            .iter()
            .zip(&pieces.out)
            .map(|(a, b)| a - b)
            .collect();
        let db = 20.0 * (rms(&diff) / rms(&whole.out)).log10();
        assert!(db < -80.0, "pieces vs whole {db:.1} dB re signal");
        // One piece is the whole render.
        let long = Pieces {
            chunk_s: 10.0,
            ..cut
        };
        let one = render_pieces(&p.circuit, &Vec::new(), &x, s, long, 3, |_| {}, &no).unwrap();
        assert_eq!(one.out, whole.out);
        eprintln!("pieces vs whole: {db:.1} dB re signal");
    }
}
