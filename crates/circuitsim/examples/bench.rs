//! A production run on a recorded input: wall time, solver statistics, and the
//! output and control voltage for comparisons.
//!
//!     cargo run --release --example bench -- circuit.json input.f64 oversample [out.f64]
//!
//! `input.f64`: little-endian f64 volts at the input node, one per step (already
//! oversampled). Settings are production's (sim_settings.yaml `circuitsim`):
//! esdirk4, input order 5, error control 0.01 V / 1e-3, DK with Newton 1e-4 /
//! 1e-3 V and reuse. Environment overrides: ABSTOL, RELTOL (error control),
//! SELECT=0 (recursive halving instead of step selection), REPS (best of).
//! `out.f64` gets v(out) then v(cv), each one value per step.

use std::time::Instant;

use circuitsim::ir::CircuitIr;
use circuitsim::transient::{ErrorNorm, Method, Options};

fn env<T: std::str::FromStr>(name: &str, default: T) -> T {
    std::env::var(name)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let ir = CircuitIr::from_json(&std::fs::read_to_string(&args[1]).unwrap()).unwrap();
    let bytes = std::fs::read(&args[2]).unwrap();
    let input: Vec<f64> = bytes
        .chunks_exact(8)
        .map(|c| f64::from_le_bytes(c.try_into().unwrap()))
        .collect();
    let k: f64 = args[3].parse().unwrap();
    let h = 1.0 / (96_000.0 * k);
    let opts = Options {
        input_order: 5,
        error_abstol: env("ABSTOL", 0.01),
        error_reltol: env("RELTOL", 1e-3),
        reltol: 1e-4,
        vntol: 1e-3,
        step_selection: env("SELECT", 1) == 1,
        error_norm: ErrorNorm::parse(&env("NORM", "nodes".to_string())).unwrap(),
        all_unknowns: env("ALL", 0) == 1,
        ..Options::with_method(Method::Esdirk4)
    };
    let reps: usize = env("REPS", 1);
    circuitsim::timing::take();
    let mut best = f64::INFINITY;
    let mut out = None;
    for _ in 0..reps {
        let t = Instant::now();
        let o = circuitsim::simulate(&ir, &input, h, &opts).unwrap();
        best = best.min(t.elapsed().as_secs_f64());
        out = Some(o);
    }
    let o = out.unwrap();
    let parts = circuitsim::timing::take();
    let total: u64 = parts.iter().sum();
    if total > 0 {
        for ((_, name), c) in circuitsim::timing::PARTS.iter().zip(parts) {
            println!("  {name:24} {:5.1}%", 100.0 * c as f64 / total as f64);
        }
    }
    let s = &o.stats;
    let audio_s = input.len() as f64 * h;
    println!(
        "{:.2} x real time ({:.2} s for {:.3} s); steps {} substeps {} halved {} rejections {}",
        best / audio_s,
        best,
        audio_s,
        s.steps,
        s.substeps,
        s.halved_steps,
        s.error_rejections
    );
    println!(
        "  iterations {:.2}/step, factorizations {:.3}/step, exact retries {}, evaluations {:.1}/step",
        s.iterations as f64 / s.steps as f64,
        s.factorizations as f64 / s.steps as f64,
        s.exact_retries,
        s.device_evaluations as f64 / s.steps as f64
    );
    println!("  accepted by level {:?}", s.accepted_by_level);
    println!("  rejected by level {:?}", s.rejected_by_level);
    if let Some(path) = args.get(4) {
        let mut buf = Vec::new();
        for name in ["v(out)", "v(cv)"] {
            let i = o.names.iter().position(|n| n == name).unwrap();
            for v in &o.values[i] {
                buf.extend_from_slice(&v.to_le_bytes());
            }
        }
        std::fs::write(path, buf).unwrap();
    }
}
