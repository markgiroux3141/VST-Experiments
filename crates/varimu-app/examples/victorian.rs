//! The Victorian synth's voice without the window (docs/VICTORIAN_SYNTH_PLAN.md, V3): a
//! phrase of simulated MIDI keys (note-ons and note-offs through `Keys::message`, as a
//! keyboard's) played by the real player on the `victorian_voice` device, with its load,
//! dropouts and latency.
//!
//!     cargo run --release -p varimu-app --example victorian -- [--for S] [--buffer-ms 50]
//!         [--chord-keys N] [--cutoff X] [--mute] [--bench [--wav out.wav]]
//!         [--quality draft-1x|draft-2x|draft|production] [--one-thread] (no partition)
//!
//! The phrase: a held chord of `--chord-keys` notes (default 4), then a run of single notes
//! over it, then everything released. `--mute` computes everything but sends silence out.
//! `--bench` runs the device's stream (`Live`, as the player does) as fast as it goes with
//! the same phrase, no audio device: its real-time factor, its worst blocks; `--wav` saves
//! its output (host rate, float, 0 dBFS the circuit's full scale).

use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, Instant};

use circuitsim::media::NoteEvent;
use varimu_app::live::{Circuit, Live};
use varimu_app::midi::{Keys, Wave};
use varimu_app::panel::{DEVICES, key_feeds, knobs, values};
use varimu_app::player::{Player, Source, State};
use varimu_app::settings::Settings;
use varimu_circuit::yaml::Value;

const CHORD: [u8; 8] = [48, 55, 60, 64, 67, 72, 76, 79];
const RUN: [u8; 8] = [72, 74, 76, 79, 81, 79, 76, 72];

fn main() -> Result<(), String> {
    let (mut secs, mut buffer_ms, mut chord_keys) = (8.0f64, 50.0f64, 4usize);
    let mut cutoff = None::<f64>;
    let mut quality = None::<varimu_app::settings::Quality>;
    let (mut mute, mut bench, mut wav) = (false, false, None::<String>);
    let mut one_thread = false;
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        let mut val = || args.next().ok_or(format!("{a} needs a value"));
        match a.as_str() {
            "--for" => secs = val()?.parse().map_err(|_| "--for")?,
            "--buffer-ms" => buffer_ms = val()?.parse().map_err(|_| "--buffer-ms")?,
            "--chord-keys" => chord_keys = val()?.parse().map_err(|_| "--chord-keys")?,
            "--cutoff" => cutoff = Some(val()?.parse().map_err(|_| "--cutoff")?),
            "--mute" => mute = true,
            "--bench" => bench = true,
            "--one-thread" => one_thread = true,
            "--quality" => {
                let q = val()?;
                quality = Some(
                    varimu_app::settings::Quality::from_name(&q)
                        .ok_or(format!("unknown quality {q}"))?,
                );
            }
            "--wav" => wav = Some(val()?),
            _ => return Err(format!("unknown option {a}")),
        }
    }
    let config = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config");
    let dev = DEVICES
        .iter()
        .find(|d| d.id == "victorian_voice")
        .ok_or("no victorian_voice device")?;
    let mut s = dev.play_settings(&Settings::load(&config, quality.unwrap_or(dev.quality))?);
    if one_thread {
        s.partition.clear();
    }
    if let Ok(c) = std::env::var("VICTORIAN_CORES") {
        s.cores = c;
    }
    let circuit = dev.live(Circuit::load(&config, dev.circuit, s.cores()?)?);
    let mut v = values(&knobs(dev, circuit.spec()));
    if let Some(x) = cutoff
        && let Some(e) = v.iter_mut().find(|(k, _)| k == "cutoff")
    {
        e.1 = Value::Float(x);
    }
    if bench {
        return run_bench(circuit, v, s, secs, chord_keys, wav);
    }
    let feeds = key_feeds(dev, circuit.spec())?;
    let keys = Arc::new(Keys::default());
    varimu_app::player::raise_priority();
    let player = Player::start(
        Source::Keys(keys.clone(), Wave::Off, feeds),
        v,
        circuit,
        s,
        1.0,
        buffer_ms / 1000.0,
    )?;
    if mute {
        player.set_compensation(false);
        player.set_output_db(-300.0);
    }
    let t0 = Instant::now();
    while !matches!(player.status().state, State::Playing | State::Failed(_)) {
        if t0.elapsed() > Duration::from_secs(60) {
            return Err("the player never started".into());
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    if let State::Failed(e) = player.status().state {
        return Err(e);
    }
    println!(
        "playing {secs} s (started in {:.1} s): a {chord_keys}-key chord and a run over it",
        t0.elapsed().as_secs_f64()
    );
    for &n in CHORD.iter().take(chord_keys) {
        keys.message(&[0x90, n, 90]);
    }
    let start = Instant::now();
    let (mut next, mut i, mut worst) = (1.0, 0, 0.0f64);
    let mut held: Option<u8> = None;
    while start.elapsed().as_secs_f64() < secs - 1.0 {
        std::thread::sleep(Duration::from_millis(20));
        worst = worst.max(player.status().load_max);
        if start.elapsed().as_secs_f64() >= next {
            if let Some(n) = held.take() {
                keys.message(&[0x80, n, 0]);
            }
            let n = RUN[i % RUN.len()];
            keys.message(&[0x90, n, 100]);
            held = Some(n);
            i += 1;
            next += 0.35;
        }
    }
    if let Some(n) = held {
        keys.message(&[0x80, n, 0]);
    }
    for &n in CHORD.iter().take(chord_keys) {
        keys.message(&[0x80, n, 0]);
    }
    std::thread::sleep(Duration::from_millis(1000));
    let st = player.status();
    println!(
        "worst block {:.0}% of its time, dropouts {}, key to ear {:.0} ms, out {:.0} dBFS",
        worst.max(st.load_max) * 100.0,
        player.dropouts(),
        st.latency_s.unwrap_or(0.0) * 1000.0,
        st.meter.out_dbfs
    );
    Ok(())
}

/// The phrase's events (sample at the host rate, event), in order.
fn phrase(rate: f64, secs: f64, chord_keys: usize) -> Vec<(usize, NoteEvent)> {
    let at = |t: f64| (t * rate) as usize;
    let mut ev: Vec<(usize, NoteEvent)> = CHORD
        .iter()
        .take(chord_keys)
        .map(|&note| (at(0.2), NoteEvent::On { note, velocity: 90 }))
        .collect();
    let (mut t, mut i) = (1.2, 0);
    while t < secs - 1.0 {
        let note = RUN[i % RUN.len()];
        ev.push((
            at(t),
            NoteEvent::On {
                note,
                velocity: 100,
            },
        ));
        ev.push((at(t + 0.3), NoteEvent::Off { note }));
        (t, i) = (t + 0.35, i + 1);
    }
    for &note in CHORD.iter().take(chord_keys) {
        ev.push((at(secs - 1.0), NoteEvent::Off { note }));
    }
    ev.sort_by_key(|e| e.0);
    ev
}

fn run_bench(
    circuit: Circuit,
    v: varimu_app::live::Values,
    s: Settings,
    secs: f64,
    chord_keys: usize,
    wav: Option<String>,
) -> Result<(), String> {
    let rate = f64::from(s.host());
    let block = 512usize;
    let t_build = Instant::now();
    let mut live = Live::with_controls(&[], v, circuit, s, 1.0, &[])?;
    eprintln!(
        "built and settled in {:.2} s",
        t_build.elapsed().as_secs_f64()
    );
    let events = phrase(rate, secs, chord_keys);
    let n_blocks = (secs * rate / block as f64).ceil() as usize;
    let x = vec![0.0; block];
    let (mut times, mut audio) = (Vec::with_capacity(n_blocks), Vec::<f32>::new());
    let mut e = 0;
    for b in 0..n_blocks {
        let (lo, hi) = (b * block, (b + 1) * block);
        let mut notes = Vec::new();
        while e < events.len() && events[e].0 < hi {
            notes.push((events[e].0.max(lo) - lo, events[e].1));
            e += 1;
        }
        let t0 = Instant::now();
        let (y, _) = live.process_notes(&x, &[], &notes)?;
        times.push(t0.elapsed().as_secs_f64());
        audio.extend_from_slice(&y);
    }
    let audio_s = block as f64 / rate;
    let skip = (0.1 / audio_s) as usize;
    let t = &times[skip.min(times.len())..];
    let total: f64 = t.iter().sum();
    let worst64 = t
        .windows(64.min(t.len()))
        .map(|w| w.iter().sum::<f64>() / (w.len() as f64 * audio_s))
        .fold(0.0f64, f64::max);
    let worst = t.iter().fold(0.0f64, |m, &x| m.max(x)) / audio_s;
    let peak = audio.iter().fold(0.0f32, |p, s| p.max(s.abs()));
    println!(
        "victorian_voice ({chord_keys}-key chord + run): {:.3}x real time (worst 64 blocks {:.3}x, worst block {:.2}x), peak {:.1} dBFS",
        total / (t.len() as f64 * audio_s),
        worst64,
        worst,
        20.0 * (peak.max(1e-12) as f64).log10()
    );
    if let Some(path) = wav {
        let spec = hound::WavSpec {
            channels: 1,
            sample_rate: rate as u32,
            bits_per_sample: 32,
            sample_format: hound::SampleFormat::Float,
        };
        let mut w = hound::WavWriter::create(&path, spec).map_err(|e| e.to_string())?;
        for s in audio {
            w.write_sample(s).map_err(|e| e.to_string())?;
        }
        w.finalize().map_err(|e| e.to_string())?;
        println!("wrote {path}");
    }
    Ok(())
}
