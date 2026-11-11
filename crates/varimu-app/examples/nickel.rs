//! The Nickel Organ device without the window: a phrase of simulated MIDI keys (note-ons and
//! note-offs through `Keys::message`, as a keyboard's) played by the real player on the
//! `nickel_organ` device, with its load, dropouts and latency; and `--wav FILE` the same
//! phrase rendered offline by the keys' medium at 96 kHz (the device's line).
//!
//!     cargo run --release -p varimu-app --example nickel -- [--for S] [--buffer-ms 50]
//!         [--sustain X] [--polarize X] [--chord-keys N] [--mute] [--wav out.wav]
//!
//! The phrase: a held chord of `--chord-keys` notes (default 4), then a run of single notes
//! over it, then everything released. `--mute` computes everything but sends silence out.

use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, Instant};

use circuitsim::ir::Element;
use circuitsim::media::NoteEvent;
use varimu_app::live::Circuit;
use varimu_app::midi::{Keys, Wave};
use varimu_app::panel::{DEVICES, key_feeds, knobs, values};
use varimu_app::player::{Player, Source, State};
use varimu_app::settings::Settings;
use varimu_circuit::yaml::Value;

/// A knob's value in `v` (a panel's values in order).
fn set(v: &mut [(String, Value)], key: &str, x: f64) {
    if let Some(e) = v.iter_mut().find(|(k, _)| k == key) {
        e.1 = Value::Float(x);
    }
}

const CHORD: [u8; 8] = [48, 55, 60, 64, 67, 72, 76, 79];
const RUN: [u8; 8] = [72, 74, 76, 79, 81, 79, 76, 72];

fn main() -> Result<(), String> {
    let (mut secs, mut buffer_ms, mut chord_keys) = (8.0f64, 50.0f64, 4usize);
    let (mut sustain, mut polarize, mut wav) = (None::<f64>, None::<f64>, None::<String>);
    let mut mute = false;
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        let mut val = || args.next().ok_or(format!("{a} needs a value"));
        match a.as_str() {
            "--for" => secs = val()?.parse().map_err(|_| "--for")?,
            "--buffer-ms" => buffer_ms = val()?.parse().map_err(|_| "--buffer-ms")?,
            "--chord-keys" => chord_keys = val()?.parse().map_err(|_| "--chord-keys")?,
            "--sustain" => sustain = Some(val()?.parse().map_err(|_| "--sustain")?),
            "--polarize" => polarize = Some(val()?.parse().map_err(|_| "--polarize")?),
            "--wav" => wav = Some(val()?),
            "--mute" => mute = true,
            _ => return Err(format!("unknown option {a}")),
        }
    }
    let config = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config");
    let dev = DEVICES
        .iter()
        .find(|d| d.id == "nickel_organ")
        .ok_or("no nickel_organ device")?;
    let s = dev.play_settings(&Settings::load(&config, dev.quality)?);
    let circuit = dev.live(Circuit::load(&config, dev.circuit, s.cores()?)?);
    let mut v = values(&knobs(dev, circuit.spec()));
    if let Some(x) = sustain {
        set(&mut v, "sustain", x);
    }
    if let Some(x) = polarize {
        set(&mut v, "polarize", x);
    }
    if let Some(path) = wav {
        let fs = circuit.full_scale(&s).output_v;
        return offline(&circuit, &v, fs, secs, chord_keys, &path);
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
        if t0.elapsed() > Duration::from_secs(30) {
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
    while start.elapsed().as_secs_f64() < secs - 1.0 {
        std::thread::sleep(Duration::from_millis(20));
        worst = worst.max(player.status().load_max);
        if start.elapsed().as_secs_f64() >= next {
            let n = RUN[i % RUN.len()];
            keys.message(&[0x90, n, 100]);
            keys.message(&[0x80, n, 0]);
            i += 1;
            next += 0.35;
        }
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

/// The phrase through the keys' medium alone (the device's line) into a mono float WAV at
/// 96 kHz, 0 dBFS the circuit's full scale.
fn offline(
    circuit: &Circuit,
    v: &varimu_app::live::Values,
    fs: f64,
    secs: f64,
    chord_keys: usize,
    path: &str,
) -> Result<(), String> {
    let ir = circuit.build(v)?;
    let el = ir
        .sections
        .iter()
        .flat_map(|s| &s.elements)
        .find_map(|e| match e {
            Element::NickelKeys(k) => Some(k.clone()),
            _ => None,
        })
        .ok_or("no keys in the circuit")?;
    let rate = 96_000.0;
    let at = |t: f64| (t * rate) as usize;
    let mut events: Vec<(usize, NoteEvent)> = CHORD
        .iter()
        .take(chord_keys)
        .map(|&note| (0, NoteEvent::On { note, velocity: 90 }))
        .collect();
    let (mut t, mut i) = (1.0, 0);
    while t < secs - 1.0 {
        let note = RUN[i % RUN.len()];
        events.push((
            at(t),
            NoteEvent::On {
                note,
                velocity: 100,
            },
        ));
        events.push((at(t) + 1, NoteEvent::Off { note }));
        (t, i) = (t + 0.35, i + 1);
    }
    for &note in CHORD.iter().take(chord_keys) {
        events.push((at(secs - 1.0), NoteEvent::Off { note }));
    }
    events.sort_by_key(|e| e.0);
    let t0 = Instant::now();
    let y = circuitsim::nickel::render(
        &el,
        rate,
        at(secs),
        &events,
        Some(1),
        circuitsim::nickel::workers(),
    )?;
    let spec = hound::WavSpec {
        channels: 1,
        sample_rate: rate as u32,
        bits_per_sample: 32,
        sample_format: hound::SampleFormat::Float,
    };
    let mut w = hound::WavWriter::create(path, spec).map_err(|x| x.to_string())?;
    let mut peak = 0.0f64;
    for x in &y {
        peak = peak.max(x.abs());
        w.write_sample((x / fs) as f32).map_err(|x| x.to_string())?;
    }
    w.finalize().map_err(|x| x.to_string())?;
    let dt = t0.elapsed().as_secs_f64();
    println!(
        "{path}: {secs} s in {dt:.2} s ({:.2}x real time), peak {:.1} V ({:.1} dBFS)",
        dt / secs,
        peak,
        20.0 * (peak / fs).max(1e-9).log10()
    );
    Ok(())
}
