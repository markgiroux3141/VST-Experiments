//! The Victorian synth's reed keys alone (docs/VICTORIAN_SYNTH_PLAN.md): N keys held on ideal
//! batteries (2.8 V local, 6 V line) for S seconds at 96 kHz steps through circuitsim's
//! `reeds` medium; its cost as a real-time factor.
//!
//!     cargo run --release -p circuitsim --example reeds_bench -- [DATA.json] [KEYS] [SECONDS]

use std::time::Instant;

use circuitsim::ir::ReedKeys;
use circuitsim::media::NoteEvent;
use circuitsim::reeds::Medium;

fn main() -> Result<(), String> {
    let mut args = std::env::args().skip(1);
    let data = args
        .next()
        .unwrap_or_else(|| "config/components/gray_reeds/2.reeds.json".into());
    let keys: usize = args
        .next()
        .map_or(Ok(4), |s| s.parse())
        .map_err(|_| "KEYS")?;
    let secs: f64 = args
        .next()
        .map_or(Ok(4.0), |s| s.parse())
        .map_err(|_| "SECONDS")?;
    // The medium loads its data by path; the sha256 names it in the load cache only.
    let sha = format!("{:064x}", 0u8);
    let el = ReedKeys {
        name: "VREEDS".into(),
        data: std::path::Path::new(&data)
            .canonicalize()
            .map_err(|e| e.to_string())?
            .to_string_lossy()
            .into(),
        sha256: sha,
        step_hz: 768_000.0,
        v_per_a: 1.0,
        loc: "loc".into(),
        line: "line".into(),
        out_loc: "ol".into(),
        out_line: "ok".into(),
    };
    let fs = 96_000.0;
    let mut m = Medium::new(&el, fs)?;
    for k in 0..keys {
        m.queue(
            0,
            NoteEvent::On {
                note: 48 + (k as u8 * 5) % 36,
                velocity: 100,
            },
        );
    }
    let n = (secs * fs) as usize;
    let t0 = Instant::now();
    let mut acc = 0.0;
    for _ in 0..n {
        acc += m.push(&[2.8, 6.0]);
        acc += m.output(1);
    }
    let wall = t0.elapsed().as_secs_f64();
    println!(
        "{keys} keys: {:.3}x real time ({:.0} ns a key-step at 8x), {} sounding, checksum {acc:.6}",
        wall / secs,
        wall / (n as f64 * keys as f64 * 8.0) * 1e9,
        m.sounding()
    );
    Ok(())
}
