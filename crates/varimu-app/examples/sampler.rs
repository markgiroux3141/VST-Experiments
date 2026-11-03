//! The sampler without the window: a kit from `samples/drums/` played on its pads in a
//! beat out of the default output, with a take armed as the Session view arms one, then
//! what was recorded (the hits' onsets against when they were played) and the stats.
//!
//!     cargo run --release -p varimu-app --example sampler -- [--bpm 100] [--bars 2]
//!         [--buffer-ms 20] [--kick FILE] [--snare FILE] [--hat FILE]
//!
//! Without `--kick` / `--snare` / `--hat`, the first file of samples/drums/kick, snare and
//! hihat_closed.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use varimu_app::player::{Player, State};
use varimu_app::sampler::{Sample, Sampler};
use varimu_app::settings::{Quality, Settings};
use varimu_app::transport::TransportSettings;

fn first_in(dir: &Path) -> Result<PathBuf, String> {
    let mut v: Vec<PathBuf> = std::fs::read_dir(dir)
        .map_err(|e| format!("{}: {e}", dir.display()))?
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|e| e == "wav"))
        .collect();
    v.sort();
    v.into_iter()
        .next()
        .ok_or(format!("no WAV in {}", dir.display()))
}

fn main() -> Result<(), String> {
    let (mut bpm, mut bars, mut buffer_ms) = (100.0f64, 2usize, 20.0f64);
    let mut files: [Option<PathBuf>; 3] = [None, None, None];
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        let mut val = || args.next().ok_or(format!("{a} needs a value"));
        match a.as_str() {
            "--bpm" => bpm = val()?.parse().map_err(|_| "--bpm")?,
            "--bars" => bars = val()?.parse().map_err(|_| "--bars")?,
            "--buffer-ms" => buffer_ms = val()?.parse().map_err(|_| "--buffer-ms")?,
            "--kick" => files[0] = Some(PathBuf::from(val()?)),
            "--snare" => files[1] = Some(PathBuf::from(val()?)),
            "--hat" => files[2] = Some(PathBuf::from(val()?)),
            _ => return Err(format!("unknown option {a}")),
        }
    }
    let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let drums = repo.join("samples/drums");
    let sampler = Arc::new(Sampler::default());
    for (slot, (f, dir)) in files
        .iter()
        .zip(["kick", "snare", "hihat_closed"])
        .enumerate()
    {
        let path = match f {
            Some(p) => p.clone(),
            None => first_in(&drums.join(dir))?,
        };
        let s = Sample::load(&path)?;
        println!(
            "slot {} ({dir}): {} ({:.2} s at {} Hz)",
            slot + 1,
            s.name(),
            s.seconds(),
            s.rate
        );
        sampler.set_slot(slot, Some(Arc::new(s)));
    }

    let s = Settings::load(&repo.join("config"), Quality::Draft1x)?;
    let p = Player::start_sampler(sampler.clone(), None, s, buffer_ms / 1000.0)?;
    let rate = p.rate;
    let t = TransportSettings {
        bpm,
        click: varimu_app::transport::ClickMode::Off,
        count_in_bars: 0,
        ..TransportSettings::default()
    };
    p.set_transport(&t);
    while p.status().state == State::Starting {
        std::thread::sleep(Duration::from_millis(5));
    }
    p.arm_take(true);
    p.transport_run(true);
    // Wait for the transport to run (its first block), then play eighth notes.
    let t0 = Instant::now();
    while !p.status().transport.running && t0.elapsed() < Duration::from_secs(2) {
        std::thread::sleep(Duration::from_millis(1));
    }
    let eighth = Duration::from_secs_f64(30.0 / bpm);
    let start = Instant::now();
    let mut played = Vec::new();
    for k in 0..bars * 8 {
        let when = start + eighth * k as u32;
        while Instant::now() < when {
            std::thread::sleep(Duration::from_micros(200));
        }
        let slots: &[usize] = match k % 8 {
            0 | 5 => &[0, 2],
            2 | 6 => &[1, 2],
            _ => &[2],
        };
        for &slot in slots {
            sampler.hit(slot, 120);
        }
        played.push((k, start.elapsed().as_secs_f64()));
    }
    std::thread::sleep(eighth * 4);
    p.arm_take(false);
    p.transport_run(false);
    std::thread::sleep(Duration::from_millis(100));
    let take = p.finished_take().ok_or("no take recorded")?;
    let st = p.status();
    println!(
        "played {} steps; dropouts {}; key to ear {:.1} ms; out {:.1} dBFS",
        played.len(),
        p.dropouts(),
        st.latency_s.unwrap_or(0.0) * 1000.0,
        st.meter.out_dbfs
    );
    let x = &take.samples;
    let peak = x.iter().fold(0.0f32, |m, v| m.max(v.abs()));
    println!(
        "take: {} samples ({:.2} s at {rate} Hz), starts at position {}, latency {} samples, peak {:.1} dBFS",
        x.len(),
        x.len() as f64 / rate as f64,
        take.start,
        take.latency,
        20.0 * (peak as f64).max(1e-9).log10()
    );
    // Onsets: a 1 ms frame's peak jumping past 3x the 20 ms before it (and past -40 dB of
    // the take's peak), at least a quarter of an eighth after the last.
    let frame = (rate / 1000) as usize;
    let env: Vec<f32> = x
        .chunks(frame)
        .map(|c| c.iter().fold(0.0f32, |m, v| m.max(v.abs())))
        .collect();
    let mut onsets = Vec::new();
    let mut last = f64::NEG_INFINITY;
    for i in 20..env.len() {
        let before = env[i - 20..i].iter().fold(0.0f32, |m, &v| m.max(v));
        let t = i as f64 / 1000.0;
        if env[i] > 3.0 * before && env[i] > peak * 0.01 && t - last > eighth.as_secs_f64() / 4.0 {
            onsets.push(t);
            last = t;
        }
    }
    let gaps: Vec<String> = onsets
        .windows(2)
        .take(8)
        .map(|w| format!("{:.1}", (w[1] - w[0]) * 1000.0))
        .collect();
    println!(
        "onsets found {} (steps played {}); first gaps (ms, eighths are {:.1}): {}",
        onsets.len(),
        played.len(),
        eighth.as_secs_f64() * 1000.0,
        gaps.join(" ")
    );
    if peak == 0.0 {
        return Err("the take is silent".into());
    }
    Ok(())
}
