//! Throughput of the noise streams (B5): ns per white normal and per flicker sample.
use std::time::Instant;

use circuitsim::noise::{self, Flicker, FlickerFilter, Normals};

fn main() {
    let n = 20_000_000u64;
    let mut s = Normals::new(noise::key(1, "IN_R1", 0), 0);
    let t = Instant::now();
    let mut acc = 0.0;
    for _ in 0..n {
        acc += s.next();
    }
    println!(
        "white: {:.1} ns per sample ({acc:.1})",
        t.elapsed().as_nanos() as f64 / n as f64
    );
    let f = FlickerFilter::new(96000.0);
    let mut fl = Flicker::new(&f, noise::key(1, "B", 2), noise::key(1, "B", 3));
    let t = Instant::now();
    for _ in 0..n / 4 {
        acc += fl.next(&f);
    }
    println!(
        "flicker: {:.1} ns per sample ({acc:.1})",
        t.elapsed().as_nanos() as f64 / (n / 4) as f64
    );
}
