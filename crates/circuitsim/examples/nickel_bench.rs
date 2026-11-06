//! The Nickel Organ's speed: N keys struck and held, seconds of compute per second of audio.
//! `cargo run --release -p circuitsim --example nickel_bench -- [KEYS] [SECONDS] [SUSTAIN]`

use std::sync::Arc;
use std::time::Instant;

use circuitsim::nickel::{Model, Organ};

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let keys: usize = a.get(1).and_then(|x| x.parse().ok()).unwrap_or(1);
    let secs: f64 = a.get(2).and_then(|x| x.parse().ok()).unwrap_or(3.0);
    let threads: usize = a.get(4).and_then(|x| x.parse().ok()).unwrap_or(4);
    let sustain: f64 = a.get(3).and_then(|x| x.parse().ok()).unwrap_or(0.75);
    let text = std::fs::read_to_string(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../config/nickel/organ.live.json"
    ))
    .unwrap();
    let model = Arc::new(Model::from_json(&text).unwrap());
    let mut o = Organ::new(model, 2, Some(1), threads);
    o.sustain = sustain;
    let notes = [48u8, 55, 60, 64, 67, 72, 76, 79, 84, 52, 57, 62];
    let t = Instant::now();
    for &n in notes.iter().take(keys) {
        o.note_on(n, 90);
    }
    let setup = t.elapsed().as_secs_f64();
    let block = 128;
    let mut buf = vec![0.0; block];
    let blocks = (secs * 96000.0) as usize / block;
    let mut worst = 0.0f64;
    let mut peak = 0.0f64;
    let t = Instant::now();
    for _ in 0..blocks {
        let b = Instant::now();
        o.render(&mut buf);
        worst = worst.max(b.elapsed().as_secs_f64() / (block as f64 / 96000.0));
        peak = buf.iter().fold(peak, |p, x| p.max(x.abs()));
    }
    let dt = t.elapsed().as_secs_f64();
    println!(
        "{keys} keys: {:.3}x real time ({:.3} per key), worst block {:.2}x, power-on {:.0} ms, peak {:.2} V, running {}",
        dt / secs,
        dt / secs / keys as f64,
        worst,
        setup * 1e3,
        peak,
        o.running()
    );
}
