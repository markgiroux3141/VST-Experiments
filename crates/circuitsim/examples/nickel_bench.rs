//! The Nickel Organ's speed: N keys struck and held on the keyboard medium, seconds of
//! compute per second of audio.
//! `cargo run --release -p circuitsim --example nickel_bench -- [KEYS] [SECONDS] [SUSTAIN]
//! [WORKERS]` (the compiled organ's latest version, config/components/nickel_organ/)

use std::time::Instant;

use circuitsim::ir::NickelKeys;
use circuitsim::media::NoteEvent;
use circuitsim::nickel::Medium;

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let keys: usize = a.get(1).and_then(|x| x.parse().ok()).unwrap_or(1);
    let secs: f64 = a.get(2).and_then(|x| x.parse().ok()).unwrap_or(3.0);
    let sustain: f64 = a.get(3).and_then(|x| x.parse().ok()).unwrap_or(0.75);
    let workers: usize = a
        .get(4)
        .and_then(|x| x.parse().ok())
        .unwrap_or_else(circuitsim::nickel::workers);
    let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../config/components/nickel_organ");
    let n = std::fs::read_dir(&dir)
        .unwrap()
        .filter_map(|e| {
            let f = e.ok()?.file_name().to_string_lossy().into_owned();
            f.strip_suffix(".yaml")?.parse::<u32>().ok()
        })
        .max()
        .unwrap();
    let el = NickelKeys {
        name: "VKEYS".into(),
        out: "out".into(),
        data: dir
            .join(format!("{n}.organ.json"))
            .to_string_lossy()
            .into_owned(),
        sha256: "0".repeat(64),
        rate_hz: 96_000.0,
        step_hz: 192_000.0,
        sustain,
        polarize: 0.35,
        max_keys: 64.0,
    };
    let t = Instant::now();
    let mut m = Medium::with_workers(&el, 96_000.0, Some(1), workers).unwrap();
    let setup = t.elapsed().as_secs_f64();
    let notes = [48u8, 55, 60, 64, 67, 72, 76, 79, 84, 52, 57, 62];
    for &n in notes.iter().take(keys) {
        m.queue(
            0,
            NoteEvent::On {
                note: n,
                velocity: 90,
            },
        );
    }
    // Live: the events known a block of 128 at a time.
    let block = 128;
    let blocks = (secs * 96000.0) as usize / block;
    let (mut worst, mut peak) = (0.0f64, 0.0f64);
    let t = Instant::now();
    for b in 0..blocks {
        m.known_until((b + 1) * block - 1);
        let t0 = Instant::now();
        for _ in 0..block {
            peak = peak.max(m.push().abs());
        }
        worst = worst.max(t0.elapsed().as_secs_f64() / (block as f64 / 96000.0));
    }
    let dt = t.elapsed().as_secs_f64();
    println!(
        "{keys} keys on {} threads: {:.3}x real time ({:.3} per key), worst block {:.2}x, made and powered on in {:.0} ms, peak {:.2} V, sounding {}",
        workers + 1,
        dt / secs,
        dt / secs / keys as f64,
        worst,
        setup * 1e3,
        peak,
        m.sounding()
    );
}
