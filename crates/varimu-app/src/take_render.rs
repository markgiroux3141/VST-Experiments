//! Event takes rendered offline (docs/MIDI_TAKES_PLAN.md N1, N3): a performance replayed
//! through its device, from a fresh start, at a quality.
//!
//! **The replay is the live path.** A [`Live`] at the quality's settings, fed block by
//! block from the take's events through the same [`Performer`] the player uses, with every
//! knob change built on this thread and applied at the block it falls in. At the quality a
//! take was played at, with the knob log of what the device applied (`knobs_applied`), it
//! gives the audio heard bit for bit: the same blocks, the same builds landing at the same
//! samples, a change of structure settled where it was. Otherwise (an edited take, one
//! monitored through the proxy) the knobs and the range switch land at the block they fall
//! in, at once: as exact as a render is, just not a replay of anything heard.
//!
//! **Production** runs the same way on production's settings (one solve, its cores, a
//! stream with its local error control: `Settings::live_options`) at production's 96 kHz:
//! the events at that rate, the output brought back to the take's rate.
//!
//! **The cache**: `<take>/renders/<key>/audio.wav` (mono float32 at the take's rate) and
//! `render.json`, `key` a sha256 over the performance, the quality's settings, the device's
//! IR as it starts and circuitsim's `SOURCE_HASH`. Written to a temporary folder and renamed
//! into place, as prints are.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;

use serde_json::json;
use sha2::{Digest, Sha256};

use crate::live::{Circuit, Live, Values};
use crate::panel::{self, Device};
use crate::performance::{Ev, Performance, Performer};
use crate::player::BLOCK;
use crate::print::find_device;
use crate::resample::resample;
use crate::settings::{Quality, Settings};

/// A device loaded to replay a performance at a quality: its circuit and settings.
pub struct Prepared {
    pub device: &'static Device,
    pub circuit: Circuit,
    pub settings: Settings,
}

impl Prepared {
    /// `perf`'s device at `quality`: at a live quality as the Play view plays it (its own
    /// cores, partition, live build), at production as a render builds it.
    pub fn load(
        config_dir: &Path,
        perf: &Performance,
        quality: Quality,
    ) -> Result<Prepared, String> {
        let device =
            find_device(&perf.device).ok_or(format!("no device {} to render", perf.device))?;
        let base = Settings::load(config_dir, quality)?;
        let settings = match quality {
            Quality::Production => base,
            _ => device.play_settings(&base),
        };
        let c = Circuit::load(config_dir, device.circuit, settings.cores()?)?;
        let c = match quality {
            Quality::Production => c,
            _ => device.live(c),
        };
        let circuit = c.with_events(settings.events).with_noise(perf.noise);
        Ok(Prepared {
            device,
            circuit,
            settings,
        })
    }

    /// What a render of `perf` is made from (see the module docs).
    pub fn key(&self, perf: &Performance) -> Result<String, String> {
        let ir = self.circuit.build(&perf.values)?;
        let mut h = Sha256::new();
        h.update(b"varimu take render 1\n");
        h.update(circuitsim::SOURCE_HASH.as_bytes());
        h.update(serde_json::to_vec(&perf.to_json()).map_err(|e| e.to_string())?);
        h.update(serde_json::to_vec(&ir).map_err(|e| e.to_string())?);
        h.update(format!("{:?}", self.settings).as_bytes());
        h.update(format!("{:?}", self.circuit.full_scale(&self.settings)).as_bytes());
        Ok(h.finalize()[..16]
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect())
    }
}

/// `perf` through its device (see the module docs): the device's output at `perf.rate`,
/// `perf.end` samples from the performance's start. `progress(fraction)` as it goes;
/// `cancel` stops it.
pub fn render(
    prep: &Prepared,
    perf: &Performance,
    mut progress: impl FnMut(f64),
    cancel: &AtomicBool,
) -> Result<Vec<f32>, String> {
    let s = prep.settings.clone();
    let host = s.host();
    let p = perf.at_rate(host);
    let exact = perf.knobs_applied && s.quality == perf.quality && host == perf.rate;
    let feeds = panel::key_feeds(prep.device, prep.circuit.spec())?;
    let mut performer = Performer::new(feeds, p.playing, host, p.start_note, p.start_low);
    let range = performer.range();
    let with_range = |panel: &Values, low: bool| match range {
        Some(r) => r.with_position(panel, low),
        None => panel.clone(),
    };
    let c0 = performer.resting();
    let mut live =
        Live::with_controls(&[], p.values.clone(), prep.circuit.clone(), s, p.gain, &c0)?;
    let keys = live.has_keys();
    // The player's blocks (10 ms at 48 kHz), the same length of time at another rate.
    let block = ((BLOCK as f64 * host as f64 / perf.rate as f64).round() as usize).max(1);
    let total = p.end as usize;
    let mut out: Vec<f32> = Vec::with_capacity(total + block);
    let mut panel_values = p.values.clone();
    let (mut e, mut k) = (0, 0);
    let mut last_input = 0.0;
    let mut pos = 0usize;
    while pos < total {
        if cancel.load(Ordering::Relaxed) {
            return Err("cancelled".into());
        }
        let n = block.min(total - pos);
        let end = (pos + n) as u64;
        // Knob changes falling in this block, applied at its start.
        while k < p.knobs.len() && p.knobs[k].at < end {
            let knob = &p.knobs[k];
            if exact {
                live.apply_now(knob.values.clone(), last_input, knob.restart.clone())?;
            } else {
                panel_values = knob.values.clone();
                let v = with_range(&panel_values, performer.asked_low());
                live.apply_now(v, last_input, None)?;
            }
            k += 1;
        }
        let mut events: Vec<(usize, Ev)> = Vec::new();
        while e < p.events.len() && p.events[e].0 < end {
            let (at, ev) = p.events[e];
            events.push((at.saturating_sub(pos as u64) as usize, ev));
            e += 1;
        }
        let low_applied = range.map(|r| r.is_low(&live.values));
        let b = performer.block(n, &events, low_applied);
        let refs: Vec<&[f64]> = b.controls.iter().map(Vec::as_slice).collect();
        let notes = if keys { b.notes } else { Vec::new() };
        let (y, _) = live.process_notes(&b.audio, &refs, &notes)?;
        last_input = b.audio.last().copied().unwrap_or(0.0) * p.gain;
        // The range switch asked to move: built now, it lands at the next block (live it
        // lands when its build is ready, which the knob log has).
        if !exact && let Some(want) = b.range {
            live.apply_now(with_range(&panel_values, want), last_input, None)?;
        }
        out.extend_from_slice(&y);
        pos += n;
        progress(pos as f64 / total.max(1) as f64);
    }
    if host == perf.rate {
        return Ok(out);
    }
    let x: Vec<f64> = out.iter().map(|&v| v as f64).collect();
    let mut y: Vec<f32> = resample(&x, host, perf.rate)
        .iter()
        .map(|&v| v as f32)
        .collect();
    y.resize(perf.end as usize, 0.0);
    Ok(y)
}

/// A render of `perf` at `quality` kept in `dir` (a take's `renders/`), or None.
pub fn cached(dir: &Path, key: &str, rate: u32) -> Result<Option<Vec<f32>>, String> {
    let wav = dir.join(key).join("audio.wav");
    if !wav.is_file() {
        return Ok(None);
    }
    let w = crate::audio::decode(&wav)?;
    if w.rate != rate {
        return Err(format!("{}: {} Hz, not {rate}", wav.display(), w.rate));
    }
    Ok(Some(w.mono().iter().map(|&v| v as f32).collect()))
}

/// Keep a render in `dir` under `key` (with what it was made from).
pub fn store(
    dir: &Path,
    key: &str,
    quality: Quality,
    audio: &[f32],
    rate: u32,
    wall_s: f64,
) -> Result<(), String> {
    let fin = dir.join(key);
    let tmp = dir.join(format!(
        "{key}.tmp{}-{:?}",
        std::process::id(),
        std::thread::current().id()
    ));
    let _ = std::fs::remove_dir_all(&tmp);
    let x: Vec<f64> = audio.iter().map(|&v| v as f64).collect();
    crate::audio::write_wav(&tmp.join("audio.wav"), &x, rate)?;
    let meta = json!({
        "key": key,
        "quality": quality.name(),
        "rate": rate,
        "samples": audio.len(),
        "code": circuitsim::SOURCE_HASH,
        "realtime_factor": wall_s / (audio.len().max(1) as f64 / rate as f64),
        "rendered_unix_s": std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| d.as_secs()),
    });
    let p = tmp.join("render.json");
    std::fs::write(
        &p,
        serde_json::to_string_pretty(&meta).unwrap_or_default() + "\n",
    )
    .map_err(|e| format!("{}: {e}", p.display()))?;
    if std::fs::rename(&tmp, &fin).is_err() {
        let _ = std::fs::remove_dir_all(&tmp);
        if !fin.join("audio.wav").is_file() {
            return Err(format!("{}: couldn't keep the render", fin.display()));
        }
    }
    Ok(())
}

/// A finished take render: its key and audio.
#[derive(Debug, Clone)]
pub struct Done {
    pub key: String,
    pub audio: Arc<Vec<f32>>,
    pub cached: bool,
}

/// What a lookup-only job returns when the cache doesn't hold the render.
pub const NOT_RENDERED: &str = "not rendered";

/// A take rendering on a thread of its own, below normal priority.
pub struct Job {
    pub quality: Quality,
    progress: Arc<AtomicU64>,
    cancel: Arc<AtomicBool>,
    handle: Mutex<Option<JoinHandle<Result<Done, String>>>>,
}

impl Job {
    /// `perf` at `quality`, from `cache` (a take's `renders/`) if it holds it, else
    /// rendered and kept there (`render` false: else [`NOT_RENDERED`]).
    pub fn spawn(
        config_dir: PathBuf,
        perf: Arc<Performance>,
        quality: Quality,
        cache: PathBuf,
        render_missing: bool,
    ) -> Job {
        let progress = Arc::new(AtomicU64::new(0));
        let cancel = Arc::new(AtomicBool::new(false));
        let (pr, c) = (progress.clone(), cancel.clone());
        let handle = std::thread::spawn(move || {
            crate::print::lower_priority();
            let prep = Prepared::load(&config_dir, &perf, quality)?;
            let key = prep.key(&perf)?;
            if let Some(audio) = cached(&cache, &key, perf.rate)? {
                return Ok(Done {
                    key,
                    audio: Arc::new(audio),
                    cached: true,
                });
            }
            if !render_missing {
                return Err(NOT_RENDERED.into());
            }
            let t0 = std::time::Instant::now();
            let audio = render(
                &prep,
                &perf,
                |f| pr.store(f.to_bits(), Ordering::Relaxed),
                &c,
            )?;
            store(
                &cache,
                &key,
                quality,
                &audio,
                perf.rate,
                t0.elapsed().as_secs_f64(),
            )?;
            Ok(Done {
                key,
                audio: Arc::new(audio),
                cached: false,
            })
        });
        Job {
            quality,
            progress,
            cancel,
            handle: Mutex::new(Some(handle)),
        }
    }

    pub fn progress(&self) -> f64 {
        f64::from_bits(self.progress.load(Ordering::Relaxed))
    }

    pub fn cancel(&self) {
        self.cancel.store(true, Ordering::Relaxed);
    }

    pub fn is_finished(&self) -> bool {
        self.handle
            .lock()
            .map(|h| h.as_ref().is_none_or(JoinHandle::is_finished))
            .unwrap_or(true)
    }

    /// Its result (waits for it; None once taken).
    pub fn join(&self) -> Option<Result<Done, String>> {
        let h = self.handle.lock().ok()?.take()?;
        Some(
            h.join()
                .unwrap_or_else(|_| Err("the render's thread panicked".into())),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::midi::Wave;
    use crate::performance::{Ev, Playing, START_NOTE};
    use varimu_circuit::yaml::Value;

    fn config() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config")
    }

    /// A take on tube_voice as the player records one (its keys worker: a fresh device,
    /// the performer, knob turns built in the background and landing where they land),
    /// then replayed offline: the same audio, bit for bit.
    #[test]
    fn a_take_played_live_replays_bit_for_bit() {
        let d = find_device("tube_voice").unwrap();
        let s = d.play_settings(&Settings::load(&config(), d.quality).unwrap());
        let circuit = d
            .live(Circuit::load(&config(), d.circuit, s.cores().unwrap()).unwrap())
            .with_events(s.events)
            .with_noise(false);
        let feeds = panel::key_feeds(d, circuit.spec()).unwrap();
        let playing = Playing {
            wave: Wave::Saw,
            ..Playing::default()
        };
        let rate = s.host();
        let mut performer = Performer::new(feeds, playing, rate, START_NOTE, false);
        let values: Values = vec![("cutoff".into(), Value::Float(0.4))];
        let gain = 0.8;
        let mut live = Live::with_controls(
            &[],
            values.clone(),
            circuit,
            s.clone(),
            gain,
            &performer.resting(),
        )
        .unwrap();
        live.set_logging(true);
        let on = |note| Ev::On {
            note,
            velocity: 100,
        };
        let script: Vec<(usize, Vec<(usize, Ev)>)> = vec![
            (2, vec![(100, on(48))]),
            (12, vec![(300, on(55))]), // legato: the gate lifts
            (
                20,
                vec![(10, Ev::Off { note: 55 }), (40, Ev::Off { note: 48 })],
            ),
            (30, vec![(200, on(60)), (260, Ev::Off { note: 60 })]), // shorter than a block
            (40, vec![(0, on(52))]),
            (70, vec![(479, Ev::Off { note: 52 })]),
        ];
        let blocks = 90;
        let mut heard = Vec::new();
        let mut perf_events = Vec::new();
        for b in 0..blocks {
            if b == 25 {
                live.set(vec![("cutoff".into(), Value::Float(0.7))]);
            }
            if b == 50 {
                live.set(vec![
                    ("cutoff".into(), Value::Float(0.2)),
                    ("release".into(), Value::Float(0.1)),
                ]);
            }
            // Give the builds time to land somewhere in the take.
            std::thread::sleep(std::time::Duration::from_millis(2));
            let events = script
                .iter()
                .find(|(k, _)| *k == b)
                .map_or(Vec::new(), |(_, e)| e.clone());
            let at = live.processed();
            perf_events.extend(events.iter().map(|&(o, e)| (at + o as u64, e)));
            let blk = performer.block(BLOCK, &events, None);
            let refs: Vec<&[f64]> = blk.controls.iter().map(Vec::as_slice).collect();
            let (y, _) = live.process_notes(&blk.audio, &refs, &[]).unwrap();
            heard.extend_from_slice(&y);
        }
        let knobs = live.take_log();
        assert!(!knobs.is_empty(), "the knob turns landed in the take");
        let perf = Performance {
            device: d.id.into(),
            quality: d.quality,
            rate,
            values,
            playing,
            gain,
            noise: false,
            start_note: START_NOTE,
            start_low: false,
            events: perf_events,
            knobs,
            knobs_applied: true,
            end: live.processed(),
        };
        // The performance survives its file, and replays as heard.
        let text = serde_json::to_string(&perf.to_json()).unwrap();
        let perf = Performance::from_json(&serde_json::from_str(&text).unwrap()).unwrap();
        let prep = Prepared::load(&config(), &perf, d.quality).unwrap();
        let replay = render(&prep, &perf, |_| {}, &AtomicBool::new(false)).unwrap();
        assert_eq!(replay.len(), heard.len());
        let first = replay
            .iter()
            .zip(&heard)
            .position(|(a, b)| a.to_bits() != b.to_bits());
        assert_eq!(first, None, "the replay differs from sample {first:?}");
        let rms =
            (heard.iter().map(|&v| (v as f64).powi(2)).sum::<f64>() / heard.len() as f64).sqrt();
        assert!(rms > 1e-3, "the take has sound ({rms})");
        // Edited, it renders as a derived take (the knobs land at their blocks at once).
        let mut notes = perf.notes();
        notes[0].note += 2;
        let edited = perf.edited(&notes, None);
        let y = render(&prep, &edited, |_| {}, &AtomicBool::new(false)).unwrap();
        assert_eq!(y.len(), heard.len());
        assert!(y.iter().zip(&heard).any(|(a, b)| a != b));
    }

    /// The same kind of take at production: production's settings, at 96 kHz, back to the
    /// take's rate.
    #[test]
    fn a_take_renders_at_production() {
        let on = |note| Ev::On {
            note,
            velocity: 100,
        };
        let perf = Performance {
            device: "tube_voice".into(),
            quality: Quality::Draft1x,
            rate: 48_000,
            values: vec![("cutoff".into(), Value::Float(0.5))],
            playing: Playing::default(),
            gain: 0.8,
            noise: false,
            start_note: START_NOTE,
            start_low: false,
            events: vec![(2_000, on(48)), (14_000, Ev::Off { note: 48 })],
            knobs: vec![crate::performance::Knob {
                at: 7_000,
                values: vec![("cutoff".into(), Value::Float(0.8))],
                restart: None,
            }],
            knobs_applied: false,
            end: 19_200,
        };
        let prep = Prepared::load(&config(), &perf, Quality::Production).unwrap();
        assert_eq!(prep.settings.host(), 96_000);
        let t0 = std::time::Instant::now();
        let y = render(&prep, &perf, |_| {}, &AtomicBool::new(false)).unwrap();
        eprintln!("production: {:.1} s for 0.4 s", t0.elapsed().as_secs_f64());
        assert_eq!(y.len(), 19_200);
        let level = |a: usize, b: usize| {
            (y[a..b].iter().map(|&v| (v as f64).powi(2)).sum::<f64>() / (b - a) as f64).sqrt()
        };
        assert!(
            level(4_000, 13_000) > 10.0 * level(0, 1_500),
            "the note sounds"
        );
        // The draft of it is close, not equal.
        let dprep = Prepared::load(&config(), &perf, Quality::Draft1x).unwrap();
        let d = render(&dprep, &perf, |_| {}, &AtomicBool::new(false)).unwrap();
        assert_eq!(d.len(), y.len());
        assert_ne!(prep.key(&perf).unwrap(), dprep.key(&perf).unwrap());
    }
}
