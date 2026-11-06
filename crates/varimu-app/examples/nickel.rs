//! The Nickel Organ without the window: a phrase of simulated MIDI keys (note-ons and note-offs
//! through `Keys::message`, as a keyboard's) played by the real player, with its load, dropouts
//! and latency; and `--wav FILE` the same phrase rendered offline by the engine at 48 kHz.
//!
//!     cargo run --release -p varimu-app --example nickel -- [--for S] [--buffer-ms 30]
//!         [--sustain X] [--polarize X] [--chord-keys N] [--wav out.wav]
//!
//! The phrase: a held chord of `--chord-keys` notes (default 4), then a run of single notes
//! over it, then everything released.

use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, Instant};

use varimu_app::midi::Keys;
use varimu_app::nickel::{Engine, NickelPanel};
use varimu_app::player::{Player, State};
use varimu_app::settings::{Quality, Settings};

const CHORD: [u8; 8] = [48, 55, 60, 64, 67, 72, 76, 79];
const RUN: [u8; 8] = [72, 74, 76, 79, 81, 79, 76, 72];

fn main() -> Result<(), String> {
    let (mut secs, mut buffer_ms, mut chord_keys) = (8.0f64, 30.0f64, 4usize);
    let (mut sustain, mut polarize, mut wav) = (None::<f64>, None::<f64>, None::<String>);
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
            _ => return Err(format!("unknown option {a}")),
        }
    }
    let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let panel = Arc::new(NickelPanel::new(&repo.join("config")));
    if let Err(e) = &panel.model {
        return Err(e.clone());
    }
    if let Some(s) = sustain {
        panel.set_sustain(s);
    }
    if let Some(p) = polarize {
        panel.set_polarize(p);
    }
    if let Some(path) = wav {
        return offline(&panel, secs, chord_keys, &path);
    }
    let settings = Settings::load(&repo.join("config"), Quality::Draft1x)?;
    let keys = Arc::new(Keys::default());
    let player = Player::start_nickel(
        panel.clone(),
        Some(keys.clone()),
        settings,
        buffer_ms / 1000.0,
    )?;
    let t0 = Instant::now();
    while !matches!(player.status().state, State::Playing | State::Failed(_)) {
        if t0.elapsed() > Duration::from_secs(10) {
            return Err("the player never started".into());
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    if let State::Failed(e) = player.status().state {
        return Err(e);
    }
    println!("playing {secs} s: {chord_keys}-key chord and a run over it");
    for &n in CHORD.iter().take(chord_keys) {
        keys.message(&[0x90, n, 90]);
    }
    let start = Instant::now();
    let mut next = 1.0;
    let mut i = 0;
    let (mut worst, mut max_running) = (0.0f64, 0usize);
    while start.elapsed().as_secs_f64() < secs - 1.0 {
        std::thread::sleep(Duration::from_millis(20));
        let st = player.status();
        worst = worst.max(panel.load());
        max_running = max_running.max(panel.running());
        let _ = st;
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
        "worst block {:.0}% of its time, up to {} keys sounding, dropouts {}, key to ear {:.0} ms, out {:.0} dBFS",
        worst * 100.0,
        max_running,
        player.dropouts(),
        st.latency_s.unwrap_or(0.0) * 1000.0,
        st.meter.out_dbfs
    );
    Ok(())
}

/// The phrase through the engine into a mono float WAV at 48 kHz.
fn offline(
    panel: &Arc<NickelPanel>,
    secs: f64,
    chord_keys: usize,
    path: &str,
) -> Result<(), String> {
    let rate = 48_000u32;
    let mut e = Engine::new(panel, rate).ok_or("no model")?;
    for &n in CHORD.iter().take(chord_keys) {
        e.note_on(n, 90);
    }
    let spec = hound::WavSpec {
        channels: 1,
        sample_rate: rate,
        bits_per_sample: 32,
        sample_format: hound::SampleFormat::Float,
    };
    let mut w = hound::WavWriter::create(path, spec).map_err(|x| x.to_string())?;
    let mut block = vec![0.0f32; 64];
    let total = (secs * rate as f64) as usize / 64;
    let (mut next, mut i, mut peak) = (1.0, 0, 0.0f32);
    let t = Instant::now();
    for b in 0..total {
        let now = b as f64 * 64.0 / rate as f64;
        if now >= next && now < secs - 1.0 {
            let n = RUN[i % RUN.len()];
            e.note_on(n, 100);
            e.note_off(n);
            i += 1;
            next += 0.35;
        }
        if (now - (secs - 1.0)).abs() < 64.0 / rate as f64 {
            for &n in CHORD.iter().take(chord_keys) {
                e.note_off(n);
            }
        }
        e.render(&mut block);
        for &x in &block {
            peak = peak.max(x.abs());
            w.write_sample(x).map_err(|x| x.to_string())?;
        }
    }
    w.finalize().map_err(|x| x.to_string())?;
    println!(
        "{path}: {secs} s in {:.2} s ({:.2}x real time), peak {:.1} dBFS",
        t.elapsed().as_secs_f64(),
        t.elapsed().as_secs_f64() / secs,
        20.0 * (peak as f64).max(1e-9).log10()
    );
    Ok(())
}
