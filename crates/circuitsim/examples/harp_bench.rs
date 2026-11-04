//! The harp's speed alone (docs/RHODES_PLAN.md, RH3): every key struck with the pedal down,
//! rendered at a step rate, timed per second of audio after the strikes.
//!
//!     cargo run --release -p circuitsim --example harp_bench -- [MODEL.harp.json] [FS] [RATE] [SECONDS]
//!
//! MODEL defaults to config/components/mk1_harp/1.harp.json, FS to 96000, RATE (the voices'
//! rate floor) to 96000, SECONDS to 2.

use std::time::Instant;

use circuitsim::harp::{HarpModel, Medium};
use circuitsim::ir::Harp;
use circuitsim::media::NoteEvent;

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let path = args
        .first()
        .cloned()
        .unwrap_or("config/components/mk1_harp/1.harp.json".into());
    let fs: f64 = args.get(1).map_or(96000.0, |a| a.parse().expect("FS"));
    let rate: f64 = args.get(2).map_or(96000.0, |a| a.parse().expect("RATE"));
    let secs: f64 = args.get(3).map_or(2.0, |a| a.parse().expect("SECONDS"));
    let text = std::fs::read_to_string(&path).expect("the model");
    let model: HarpModel = serde_json::from_str(&text).expect("a harp model");
    model.check().expect("a valid model");
    let el = Harp {
        name: "VHARP".into(),
        out: "h".into(),
        rate_hz: rate,
        contact_rate_hz: 384_000.0,
        model: Box::new(model),
    };
    let mut m = Medium::new(&el, fs);
    m.queue(1, NoteEvent::Pedal { down: true });
    for (i, k) in el.model.keys.iter().enumerate() {
        m.queue(
            2 + 5 * i,
            NoteEvent::On {
                note: k.note as u8,
                velocity: 100,
            },
        );
    }
    m.known_until(usize::MAX);
    // The strikes' windows first, then the ringing timed.
    let t = Instant::now();
    let strikes = (0.05 * fs) as usize;
    for _ in 0..strikes {
        m.push();
    }
    let strike_s = t.elapsed().as_secs_f64();
    let n = (secs * fs) as usize;
    let t = Instant::now();
    let mut peak = 0.0f64;
    for _ in 0..n {
        peak = peak.max(m.push().abs());
    }
    let w = t.elapsed().as_secs_f64();
    println!(
        "k {} s {}: the strikes (50 ms) {:.3} s ({:.2}x real time); {} keys ringing: {:.3} s for {secs} s ({:.3}x real time), {} still sounding, peak {peak:.3} V",
        m.k,
        m.s,
        strike_s,
        strike_s / 0.05,
        el.model.keys.len(),
        w,
        w / secs,
        m.sounding()
    );
}
