//! Loopback calibration (docs/RECORDING_PLAN.md, T1): the transport's click played out,
//! captured back, and found.
//!
//! **Capture.** [`Capture`] records one channel of an input device (an output cabled to
//! it: the round trip a recording sees) or, on Windows, of an output device's own mix
//! (WASAPI loopback: digital, no cable; it checks the transport against the output stream
//! but leaves the converters out). Every callback is dated: the first sample it delivers
//! and `Instant::now()`. The player dates its output callbacks the same way
//! (`Player::output_clock`).
//!
//! **Where the clicks are.** The transport knows each click's position `p` (host
//! samples) and the output sample `origin + p` that carried it
//! (`player::TransportStatus::origin`). A line through the output's dates maps that
//! sample to a time, a line through the capture's dates maps the time to a capture sample:
//! the prediction. Each click is then found near its prediction by normalized
//! correlation with the click sampled at the capture's rate (`transport::click_wave`, the
//! same continuous wave), to a fraction of a sample (a parabola through the peak).
//!
//! **What comes out** ([`Analysis`]):
//! - every scheduled click found or not, and how far each found one sits from the
//!   nominal line `j = offset + p * rate_in / rate_out` (one offset for the run per click
//!   pitch: no drift means every click within a sample of it). The downbeat's and the
//!   other beats' offsets are fitted apart: a path that filters (an endpoint's effects, a
//!   converter's anti-alias filter) delays 2 kHz and 1.25 kHz differently, by a constant
//!   (Realtek's loopback, 2026-10-30: 3.54 samples, every click within 0.001 of its
//!   pitch's line). The gap is reported (`accent_minus_beat`);
//! - the drift (ppm): the fitted slope against the nominal one (two devices on separate
//!   clocks drift; one interface, or a loopback of the output, shouldn't);
//! - the round trip: from the output callback that handed a click over to the input
//!   callback that brought it back, against cpal's estimate of the same span (the output's
//!   callback-to-playback latency plus the input's capture-to-callback latency). The
//!   difference is what cpal doesn't see (converters, the cable, driver buffers it doesn't
//!   report).

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{FromSample, Sample, SizedSample};

use crate::transport::{Grid, click_table};

/// What to record.
#[derive(Debug, Clone, PartialEq)]
pub enum Source {
    /// An input device (None: the default) and one of its channels.
    Input {
        device: Option<String>,
        channel: usize,
    },
    /// An output device's mix (None: the default output), its first channel (WASAPI
    /// loopback).
    Output { device: Option<String> },
}

/// A finished capture.
#[derive(Debug, Clone)]
pub struct Recording {
    pub samples: Vec<f32>,
    pub rate: u32,
    /// Per callback: the first sample it delivered and when it ran.
    pub stamps: Vec<(u64, Instant)>,
    /// cpal's capture-to-callback latency, averaged over the callbacks (s).
    pub cpal_latency_s: f64,
    /// Samples lost to a full ring.
    pub overflows: u64,
    pub name: String,
}

struct CaptureShared {
    stop: AtomicBool,
    overflows: AtomicU64,
    latency_us_sum: AtomicU64,
    callbacks: AtomicU64,
}

/// What the collector thread hands back: the samples and the callbacks' dates.
type Collected = (Vec<f32>, Vec<(u64, Instant)>);

/// A capture running: one channel into memory until [`Capture::finish`].
pub struct Capture {
    _stream: cpal::Stream,
    shared: Arc<CaptureShared>,
    collector: Option<JoinHandle<Collected>>,
    pub rate: u32,
    pub name: String,
}

fn device_name(d: &cpal::Device) -> String {
    d.description()
        .map_or_else(|_| "?".to_string(), |x| x.name().to_string())
}

impl Capture {
    pub fn start(source: &Source) -> Result<Capture, String> {
        let host = cpal::default_host();
        let (device, config, channel, label) = match source {
            Source::Input { device, channel } => {
                let d = match device {
                    None => host.default_input_device(),
                    Some(n) => host
                        .input_devices()
                        .into_iter()
                        .flatten()
                        .find(|d| device_name(d) == *n),
                }
                .ok_or_else(|| {
                    format!(
                        "no input device {}",
                        device.as_deref().unwrap_or("(default)")
                    )
                })?;
                let c = d.default_input_config().map_err(|e| e.to_string())?;
                let name = device_name(&d);
                (d, c, *channel, format!("{name}, ch {}", channel + 1))
            }
            Source::Output { device } => {
                let d = match device {
                    None => host.default_output_device(),
                    Some(n) => host
                        .output_devices()
                        .into_iter()
                        .flatten()
                        .find(|d| device_name(d) == *n),
                }
                .ok_or_else(|| {
                    format!(
                        "no output device {}",
                        device.as_deref().unwrap_or("(default)")
                    )
                })?;
                let c = d.default_output_config().map_err(|e| e.to_string())?;
                let name = device_name(&d);
                (d, c, 0, format!("{name} (loopback)"))
            }
        };
        if channel >= config.channels() as usize {
            return Err(format!("{label}: {} channels", config.channels()));
        }
        let rate = config.sample_rate();
        let shared = Arc::new(CaptureShared {
            stop: AtomicBool::new(false),
            overflows: AtomicU64::new(0),
            latency_us_sum: AtomicU64::new(0),
            callbacks: AtomicU64::new(0),
        });
        let (sp, mut sc) = rtrb::RingBuffer::<f32>::new(2 * rate as usize);
        let (tp, mut tc) = rtrb::RingBuffer::<(u64, Instant)>::new(8192);
        let cfg: cpal::StreamConfig = config.config();
        use cpal::SampleFormat as F;
        let sh = shared.clone();
        let stream = match config.sample_format() {
            F::F32 => build::<f32>(&device, &cfg, channel, sp, tp, sh),
            F::F64 => build::<f64>(&device, &cfg, channel, sp, tp, sh),
            F::I16 => build::<i16>(&device, &cfg, channel, sp, tp, sh),
            F::I32 => build::<i32>(&device, &cfg, channel, sp, tp, sh),
            F::U16 => build::<u16>(&device, &cfg, channel, sp, tp, sh),
            f => return Err(format!("{label}: sample format {f} isn't supported")),
        }
        .map_err(|e| format!("{label}: {e}"))?;
        stream.play().map_err(|e| format!("{label}: {e}"))?;
        let sh = shared.clone();
        let collector = std::thread::Builder::new()
            .name("capture".into())
            .spawn(move || {
                let (mut x, mut stamps) = (Vec::new(), Vec::new());
                let mut drain = |x: &mut Vec<f32>, stamps: &mut Vec<(u64, Instant)>| {
                    if let Ok(c) = sc.read_chunk(sc.slots()) {
                        let (a, b) = c.as_slices();
                        x.extend_from_slice(a);
                        x.extend_from_slice(b);
                        c.commit_all();
                    }
                    while let Ok(s) = tc.pop() {
                        stamps.push(s);
                    }
                };
                while !sh.stop.load(Ordering::Relaxed) {
                    drain(&mut x, &mut stamps);
                    std::thread::sleep(Duration::from_millis(5));
                }
                drain(&mut x, &mut stamps);
                (x, stamps)
            })
            .map_err(|e| e.to_string())?;
        Ok(Capture {
            _stream: stream,
            shared,
            collector: Some(collector),
            rate,
            name: label,
        })
    }

    /// Stop and hand over what was recorded.
    pub fn finish(mut self) -> Recording {
        self.shared.stop.store(true, Ordering::Relaxed);
        let (samples, stamps) = self
            .collector
            .take()
            .and_then(|h| h.join().ok())
            .unwrap_or_default();
        let n = self.shared.callbacks.load(Ordering::Relaxed).max(1);
        Recording {
            samples,
            rate: self.rate,
            stamps,
            cpal_latency_s: self.shared.latency_us_sum.load(Ordering::Relaxed) as f64 * 1e-6
                / n as f64,
            overflows: self.shared.overflows.load(Ordering::Relaxed),
            name: self.name.clone(),
        }
    }
}

impl Drop for Capture {
    fn drop(&mut self) {
        self.shared.stop.store(true, Ordering::Relaxed);
    }
}

fn build<T: SizedSample>(
    device: &cpal::Device,
    config: &cpal::StreamConfig,
    channel: usize,
    mut ring: rtrb::Producer<f32>,
    mut stamps: rtrb::Producer<(u64, Instant)>,
    shared: Arc<CaptureShared>,
) -> Result<cpal::Stream, cpal::Error>
where
    f32: FromSample<T>,
{
    let channels = config.channels as usize;
    let mut total: u64 = 0;
    device.build_input_stream(
        *config,
        move |data: &[T], info: &cpal::InputCallbackInfo| {
            let now = Instant::now();
            let ts = info.timestamp();
            let d = ts.callback.duration_since(ts.capture);
            shared
                .latency_us_sum
                .fetch_add(d.as_micros() as u64, Ordering::Relaxed);
            shared.callbacks.fetch_add(1, Ordering::Relaxed);
            let _ = stamps.push((total, now));
            let frames = data.len() / channels;
            let n = frames.min(ring.slots());
            if n < frames {
                shared
                    .overflows
                    .fetch_add((frames - n) as u64, Ordering::Relaxed);
            }
            if let Ok(mut chunk) = ring.write_chunk_uninit(n) {
                let (a, b) = chunk.as_mut_slices();
                for (d, frame) in a.iter_mut().chain(b.iter_mut()).zip(data.chunks(channels)) {
                    d.write(f32::from_sample(frame[channel]));
                }
                // SAFETY: the chunk is `n` <= frames long and every slot was written.
                unsafe { chunk.commit_all() };
            }
            // The index counts every sample delivered, lost ones too, so it stays on the
            // device's clock.
            total += frames as u64;
        },
        |e| eprintln!("capture: {e}"),
        None,
    )
}

/// A line through dated samples: `t = a + b * index` (s from `epoch`), least squares
/// with late callbacks (more than 2 ms above a first fit) left out.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Dates {
    pub epoch: Instant,
    pub a: f64,
    pub b: f64,
}

impl Dates {
    pub fn fit(stamps: &[(u64, Instant)], epoch: Instant) -> Option<Dates> {
        let pts: Vec<(f64, f64)> = stamps
            .iter()
            .map(|&(i, t)| (i as f64, secs_since(t, epoch)))
            .collect();
        let first = line(&pts)?;
        let kept: Vec<(f64, f64)> = pts
            .iter()
            .copied()
            .filter(|&(i, t)| t - (first.0 + first.1 * i) < 0.002)
            .collect();
        let (a, b) = line(&kept).unwrap_or(first);
        Some(Dates { epoch, a, b })
    }

    pub fn time(&self, index: f64) -> f64 {
        self.a + self.b * index
    }

    pub fn index(&self, t: f64) -> f64 {
        (t - self.a) / self.b
    }
}

/// Seconds from `epoch` to `t` (negative before it).
pub fn secs_since(t: Instant, epoch: Instant) -> f64 {
    match t.checked_duration_since(epoch) {
        Some(d) => d.as_secs_f64(),
        None => -epoch.duration_since(t).as_secs_f64(),
    }
}

/// Least squares `y = a + b x`.
fn line(pts: &[(f64, f64)]) -> Option<(f64, f64)> {
    let n = pts.len() as f64;
    if pts.len() < 2 {
        return None;
    }
    let (mx, my) = (
        pts.iter().map(|p| p.0).sum::<f64>() / n,
        pts.iter().map(|p| p.1).sum::<f64>() / n,
    );
    let sxx: f64 = pts.iter().map(|p| (p.0 - mx).powi(2)).sum();
    let sxy: f64 = pts.iter().map(|p| (p.0 - mx) * (p.1 - my)).sum();
    if sxx == 0.0 {
        return None;
    }
    let b = sxy / sxx;
    Some((my - b * mx, b))
}

/// One scheduled click: its transport position (host samples), whether it is a
/// downbeat, where it was predicted in the capture and where it was found (capture
/// samples, fractional) with its normalized correlation, and the level of whatever else
/// is in the capture around it (dBFS, sine-equivalent rms of the 50 ms before the search window: another
/// program playing into a captured output masks clicks).
#[derive(Debug, Clone, PartialEq)]
pub struct Click {
    pub position: i64,
    pub accent: bool,
    pub predicted: f64,
    pub found: Option<f64>,
    pub score: f64,
    pub background_dbfs: f64,
}

/// A found click needs at least this normalized correlation.
pub const MIN_SCORE: f64 = 0.5;

/// Find the clicks of `grid` whose predicted capture position (`predict(position)`) lies
/// inside `x`, searching `±window` samples around the first prediction, then (once a few
/// are found) following the offset they show within ±`track` samples.
pub fn find_clicks(
    x: &[f32],
    rate: u32,
    grid: &Grid,
    positions: std::ops::Range<i64>,
    predict: impl Fn(i64) -> f64,
    window: usize,
) -> Vec<Click> {
    let templates = [click_table(rate, false), click_table(rate, true)];
    let len = templates[1].len().max(templates[0].len());
    let track = (rate as usize / 1000).max(8); // 1 ms
    let mut out = Vec::new();
    let mut shift: Vec<f64> = Vec::new(); // found - predicted, so far
    let mut k = grid.beat_at(positions.start - 1) + 1;
    loop {
        let p = grid.beat(k);
        if p >= positions.end {
            break;
        }
        let accent = grid.is_downbeat(k);
        k += 1;
        let predicted = predict(p);
        let (centre, w) = if shift.len() >= 4 {
            (predicted + median(&shift), track)
        } else {
            (predicted, window)
        };
        let lo = centre.round() as i64 - w as i64;
        let hi = centre.round() as i64 + w as i64;
        if lo < 1 || hi + len as i64 + 1 >= x.len() as i64 {
            continue;
        }
        let t = &templates[accent as usize];
        let (found, score) = correlate(x, t, lo as usize, hi as usize);
        let before = &x[(lo as usize).saturating_sub(rate as usize / 20)..lo as usize];
        let ms =
            before.iter().map(|&v| v as f64 * v as f64).sum::<f64>() / before.len().max(1) as f64;
        let background_dbfs = 10.0 * (2.0 * ms).max(1e-24).log10();
        let found = (score >= MIN_SCORE).then_some(found);
        if let Some(f) = found {
            shift.push(f - predicted);
            if shift.len() > 16 {
                shift.remove(0);
            }
        }
        out.push(Click {
            position: p,
            accent,
            predicted,
            found,
            score,
            background_dbfs,
        });
    }
    out
}

fn median(v: &[f64]) -> f64 {
    let mut s = v.to_vec();
    s.sort_by(f64::total_cmp);
    s[s.len() / 2]
}

/// Where `t` matches `x` best, starting in `lo..=hi`: the start (fractional, a
/// parabola through the raw correlation's peak) and its normalized correlation.
fn correlate(x: &[f32], t: &[f32], lo: usize, hi: usize) -> (f64, f64) {
    let tt: f64 = t.iter().map(|&v| v as f64 * v as f64).sum();
    let dot = |s: usize| -> f64 {
        x[s..s + t.len()]
            .iter()
            .zip(t)
            .map(|(&a, &b)| a as f64 * b as f64)
            .sum()
    };
    let (mut best, mut best_score) = (lo, f64::MIN);
    for s in lo..=hi {
        let c = dot(s);
        let e: f64 = x[s..s + t.len()].iter().map(|&v| v as f64 * v as f64).sum();
        let score = if e > 0.0 { c / (tt * e).sqrt() } else { 0.0 };
        if score > best_score {
            best_score = score;
            best = s;
        }
    }
    let (y0, y1, y2) = (dot(best - 1), dot(best), dot(best + 1));
    let den = y0 - 2.0 * y1 + y2;
    let frac = if den < 0.0 {
        (0.5 * (y0 - y2) / den).clamp(-0.5, 0.5)
    } else {
        0.0
    };
    (best as f64 + frac, best_score)
}

/// What a loopback run found (the module docstring).
#[derive(Debug, Clone, PartialEq)]
pub struct Analysis {
    pub scheduled: usize,
    pub found: usize,
    /// The capture sample of transport position 0 on the nominal line (the other beats'),
    /// and how much later the downbeats' line is (capture samples).
    pub offset: f64,
    pub accent_minus_beat: f64,
    /// The found clicks against the nominal line (capture samples): the worst and rms.
    pub max_residual: f64,
    pub rms_residual: f64,
    /// The fitted slope against the nominal one (ppm).
    pub drift_ppm: f64,
    /// Output callback to input callback (s): measured, and cpal's estimate.
    pub round_trip_s: Option<f64>,
    pub cpal_round_trip_s: Option<f64>,
    /// How long the found clicks span (s).
    pub span_s: f64,
}

/// A click's output time from its position, and a capture sample's time (s, one epoch).
pub type Times<'a> = (&'a dyn Fn(i64) -> f64, &'a dyn Fn(f64) -> f64);

/// Fit the found clicks (`ratio` = capture rate / host rate) and the round trip (each
/// click's output time from `out_time(position)`, its capture time from `in_time(found)`,
/// both s on one epoch; None: not dated).
pub fn analyse(
    clicks: &[Click],
    ratio: f64,
    rate_in: u32,
    times: Option<Times>,
    cpal_round_trip_s: Option<f64>,
) -> Analysis {
    let found: Vec<(f64, f64)> = clicks
        .iter()
        .filter_map(|c| c.found.map(|f| (c.position as f64, f)))
        .collect();
    let mut a = Analysis {
        scheduled: clicks.len(),
        found: found.len(),
        offset: f64::NAN,
        accent_minus_beat: f64::NAN,
        max_residual: f64::NAN,
        rms_residual: f64::NAN,
        drift_ppm: f64::NAN,
        round_trip_s: None,
        cpal_round_trip_s,
        span_s: 0.0,
    };
    if found.is_empty() {
        return a;
    }
    // Per pitch, the offset that centres the residuals' range (the worst one smallest).
    let mut res: Vec<f64> = Vec::new();
    let mut centres = [f64::NAN; 2];
    for (kind, centre) in centres.iter_mut().enumerate() {
        let off: Vec<f64> = clicks
            .iter()
            .filter(|c| c.accent as usize == kind)
            .filter_map(|c| c.found.map(|f| f - c.position as f64 * ratio))
            .collect();
        if off.is_empty() {
            continue;
        }
        let lo = off.iter().copied().fold(f64::INFINITY, f64::min);
        let hi = off.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        *centre = 0.5 * (lo + hi);
        res.extend(off.iter().map(|o| o - *centre));
    }
    a.offset = if centres[0].is_nan() {
        centres[1]
    } else {
        centres[0]
    };
    a.accent_minus_beat = centres[1] - centres[0];
    a.max_residual = res.iter().fold(0.0, |m, r| m.max(r.abs()));
    a.rms_residual = (res.iter().map(|r| r * r).sum::<f64>() / res.len() as f64).sqrt();
    // The slope through the found clicks, each less its pitch's offset.
    let gap = if a.accent_minus_beat.is_nan() {
        0.0
    } else {
        a.accent_minus_beat
    };
    let shifted: Vec<(f64, f64)> = clicks
        .iter()
        .filter_map(|c| {
            let d = if c.accent { gap } else { 0.0 };
            c.found.map(|f| (c.position as f64, f - d))
        })
        .collect();
    if let Some((_, slope)) = line(&shifted) {
        a.drift_ppm = (slope / ratio - 1.0) * 1e6;
    }
    let first = found.first().map_or(0.0, |f| f.0);
    let last = found.last().map_or(0.0, |f| f.0);
    a.span_s = (last - first) * ratio / rate_in as f64;
    if let Some((out_time, in_time)) = times {
        let rt: Vec<f64> = clicks
            .iter()
            .filter_map(|c| c.found.map(|f| in_time(f) - out_time(c.position)))
            .collect();
        a.round_trip_s = Some(rt.iter().sum::<f64>() / rt.len() as f64);
    }
    a
}

/// The round trip of one interface, kept per (output, input) pair.
#[derive(Debug, Clone, PartialEq)]
pub struct Calibration {
    pub output: String,
    pub input: String,
    pub round_trip_s: f64,
    pub cpal_round_trip_s: f64,
}

/// A loopback run in progress with a player: the capture and the output's dates,
/// sampled while it runs.
pub struct Run {
    capture: Capture,
    out_stamps: Arc<Mutex<Vec<(u64, Instant)>>>,
    pub started: Instant,
}

impl Run {
    pub fn start(source: &Source) -> Result<Run, String> {
        Ok(Run {
            capture: Capture::start(source)?,
            out_stamps: Arc::new(Mutex::new(Vec::new())),
            started: Instant::now(),
        })
    }

    /// Record the output's latest date (call it often: every callback's isn't kept).
    pub fn note_output(&self, stamp: Option<(u64, Instant)>) {
        if let Some(s) = stamp {
            let mut v = self.out_stamps.lock().expect("out_stamps");
            if v.last() != Some(&s) {
                v.push(s);
            }
        }
    }

    pub fn name(&self) -> &str {
        &self.capture.name
    }

    /// Stop the capture.
    pub fn stop(self) -> Captured {
        let rec = self.capture.finish();
        let out_stamps = self.out_stamps.lock().expect("out_stamps").clone();
        Captured {
            rec,
            out_stamps,
            epoch: self.started,
        }
    }
}

/// A stopped loopback run: the capture and the output's dates (plain data, so the
/// analysis can run on another thread).
#[derive(Debug, Clone)]
pub struct Captured {
    pub rec: Recording,
    pub out_stamps: Vec<(u64, Instant)>,
    pub epoch: Instant,
}

impl Captured {
    /// Find the clicks: the transport's `grid`, `origin` (the output sample of position
    /// 0), the host `rate_out`, cpal's output latency (s).
    pub fn analyse(
        &self,
        grid: &Grid,
        origin: i64,
        rate_out: u32,
        cpal_out_s: f64,
    ) -> Result<(Analysis, Vec<Click>), String> {
        let rec = &self.rec;
        let epoch = self.epoch;
        let od =
            Dates::fit(&self.out_stamps, epoch).ok_or("the output wasn't dated (did it play?)")?;
        let id = Dates::fit(&rec.stamps, epoch).ok_or("the capture got no audio")?;
        let out_time = |p: i64| od.time((origin + p) as f64);
        let in_time = |j: f64| id.time(j);
        let spacing = grid.samples_per_beat() * rec.rate as f64 / rate_out as f64;
        let window = ((0.1 * rec.rate as f64).min(0.4 * spacing)) as usize;
        // The positions the capture can hold: from its first sample's time to its last.
        let t0 = id.time(0.0);
        let t1 = id.time(rec.samples.len() as f64);
        let pos_at = |t: f64| (od.index(t) - origin as f64) as i64;
        // Each click searched for where cpal's estimate of the round trip puts it.
        let cpal_rt = cpal_out_s + rec.cpal_latency_s;
        let clicks = find_clicks(
            &rec.samples,
            rec.rate,
            grid,
            pos_at(t0)..pos_at(t1),
            |p| id.index(out_time(p) + cpal_rt),
            window,
        );
        let ratio = rec.rate as f64 / rate_out as f64;
        let a = analyse(
            &clicks,
            ratio,
            rec.rate,
            Some((&out_time, &in_time)),
            Some(cpal_rt),
        );
        Ok((a, clicks))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::transport::{TransportSettings, click_wave};

    /// A capture at `rate_in` of a transport's clicks at `rate_out`: position 0 arrives at
    /// capture sample `offset`, the capture's clock `ppm` fast, a little noise.
    fn simulate(grid: &Grid, rate_in: u32, offset: f64, ppm: f64, seconds: f64) -> Vec<f32> {
        let n = (seconds * rate_in as f64) as usize;
        let mut x = vec![0.0f32; n];
        let ratio = rate_in as f64 / grid.rate as f64 * (1.0 + ppm * 1e-6);
        let mut k = 0;
        loop {
            let at = offset + grid.beat(k) as f64 * ratio;
            if at >= n as f64 {
                break;
            }
            let start = at.ceil() as usize;
            let end = (start + rate_in as usize / 20).min(n);
            for (j, v) in x.iter_mut().enumerate().take(end).skip(start) {
                let t = (j as f64 - at) / rate_in as f64;
                *v += 0.3 * click_wave(t, grid.is_downbeat(k)) as f32;
            }
            k += 1;
        }
        // Deterministic noise at -70 dBFS.
        let mut s: u64 = 0x9e37_79b9_7f4a_7c15;
        for v in &mut x {
            s ^= s << 13;
            s ^= s >> 7;
            s ^= s << 17;
            *v += 3e-4 * ((s >> 11) as f64 / (1u64 << 53) as f64 - 0.5) as f32;
        }
        x
    }

    #[test]
    fn finds_every_click_to_a_fraction_of_a_sample() {
        // 97 bpm at 48 kHz out, captured at 44.1 kHz, 123.37 samples late, the prediction
        // 4 ms off.
        let s = TransportSettings {
            bpm: 97.0,
            ..TransportSettings::default()
        };
        let grid = Grid::new(48_000, &s);
        let (rate_in, offset, seconds) = (44_100, 123.37, 60.0);
        let x = simulate(&grid, rate_in, offset, 0.0, seconds);
        let ratio = rate_in as f64 / 48_000.0;
        let clicks = find_clicks(
            &x,
            rate_in,
            &grid,
            0..(seconds * 48_000.0) as i64,
            |p| offset + 0.004 * rate_in as f64 + p as f64 * ratio,
            (0.05 * rate_in as f64) as usize,
        );
        let a = analyse(&clicks, ratio, rate_in, None, None);
        assert!(a.scheduled >= 95, "{a:?}");
        assert_eq!(a.found, a.scheduled, "{a:?}");
        assert!((a.offset - offset).abs() < 0.05, "{a:?}");
        assert!(a.max_residual < 0.05, "{a:?}");
        assert!(a.drift_ppm.abs() < 1.0, "{a:?}");
    }

    #[test]
    fn a_filtering_path_shifts_one_pitch() {
        // The downbeats 3.5 samples later than the other beats (a path that delays 2 kHz
        // more than 1.25 kHz): two lines, each click on its own.
        let grid = Grid::new(48_000, &TransportSettings::default());
        let x = simulate(&grid, 48_000, 300.0, 0.0, 20.0);
        let late = simulate(&grid, 48_000, 303.5, 0.0, 20.0);
        let mut y = x.clone();
        for k in (0..).step_by(4) {
            let at = (300 + grid.beat(k)) as usize;
            if at + 2400 > y.len() {
                break;
            }
            y[at - 100..at + 2400].copy_from_slice(&late[at - 100..at + 2400]);
        }
        let clicks = find_clicks(
            &y,
            48_000,
            &grid,
            0..20 * 48_000,
            |p| 300.0 + p as f64,
            2400,
        );
        let a = analyse(&clicks, 1.0, 48_000, None, None);
        assert_eq!(a.found, a.scheduled);
        assert!((a.accent_minus_beat - 3.5).abs() < 0.05, "{a:?}");
        assert!(a.max_residual < 0.05, "{a:?}");
        assert!(a.drift_ppm.abs() < 1.0, "{a:?}");
    }

    #[test]
    fn a_drifting_clock_shows() {
        let grid = Grid::new(48_000, &TransportSettings::default());
        let x = simulate(&grid, 48_000, 500.0, 50.0, 60.0);
        let clicks = find_clicks(
            &x,
            48_000,
            &grid,
            0..60 * 48_000,
            |p| 500.0 + p as f64,
            2400,
        );
        let a = analyse(&clicks, 1.0, 48_000, None, None);
        assert_eq!(a.found, a.scheduled);
        assert!((a.drift_ppm - 50.0).abs() < 1.0, "{a:?}");
        // 50 ppm over a minute is 144 samples: far more than one.
        assert!(a.max_residual > 50.0, "{a:?}");
    }

    #[test]
    fn missing_clicks_are_counted() {
        let grid = Grid::new(48_000, &TransportSettings::default());
        let mut x = simulate(&grid, 48_000, 0.0, 0.0, 10.0);
        // Silence the click at 2 s (beat 4).
        x[96_000..96_000 + 2400].fill(0.0);
        let clicks = find_clicks(&x, 48_000, &grid, 0..10 * 48_000, |p| p as f64, 2400);
        let a = analyse(&clicks, 1.0, 48_000, None, None);
        assert_eq!(a.scheduled - a.found, 1, "{a:?}");
        assert!(
            clicks
                .iter()
                .any(|c| c.position == 96_000 && c.found.is_none())
        );
    }

    #[test]
    fn dates_fit_through_late_callbacks() {
        let epoch = Instant::now();
        let at = |s: f64| epoch + Duration::from_secs_f64(s);
        // A callback every 480 samples at 48 kHz from 0.5 s, some 3-6 ms late.
        let stamps: Vec<(u64, Instant)> = (0..500u64)
            .map(|i| {
                let late = if i % 7 == 3 {
                    0.003 + (i % 3) as f64 * 0.0015
                } else {
                    0.0
                };
                (i * 480, at(0.5 + i as f64 * 0.01 + late))
            })
            .collect();
        let d = Dates::fit(&stamps, epoch).expect("a fit");
        assert!((d.time(0.0) - 0.5).abs() < 1e-6, "{d:?}");
        assert!((d.b * 48_000.0 - 1.0).abs() < 1e-6, "{d:?}");
        assert!((d.index(0.51) - 480.0).abs() < 1e-3);
    }
}
