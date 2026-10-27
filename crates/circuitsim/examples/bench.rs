//! A run on a recorded input: wall time, solver statistics, and the output
//! and control voltage for comparisons.
//!
//!     cargo run --release [--features timing] --example bench -- circuit.json input.f64 oversample [out.f64]
//!
//! `input.f64`: little-endian f64 volts at the input node, one per step (already
//! oversampled). Settings default to production's (sim_settings.yaml
//! `circuitsim`): esdirk4 at a 96 kHz host rate, input order 5, error control
//! 0.01 V / 1e-3 on ports and states, DK with Newton 1e-4 / 1e-3 V and reuse.
//! Environment overrides: METHOD, RATE (host rate, Hz), ABSTOL, RELTOL (error
//! control; ABSTOL=0 turns it off), NRELTOL, NVNTOL (Newton), SELECT=0
//! (recursive halving instead of step selection), NORM, ALL=1 (every unknown),
//! TABLES=1 (tabulated tubes), REPS (best of), PARTITION (section titles,
//! ";"-separated, run on a second thread; `partition.rs`) with COUPLING (hold |
//! extrapolate). With `--features timing`, where a step's time goes (one
//! thread). `out.f64` gets v(out) then v(cv), each one value per step.

use std::time::Instant;

use circuitsim::ir::CircuitIr;
use circuitsim::mna::Mna;
use circuitsim::partition::{Coupling, simulate_partitioned};
use circuitsim::transient::{ErrorNorm, Method, Options, StepInput, Transient};

fn env<T: std::str::FromStr>(name: &str, default: T) -> T {
    std::env::var(name)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

/// `simulate`'s loop, keeping the transient for its statistics.
fn run(ir: &CircuitIr, input: &[f64], h: f64, opts: &Options) -> (Transient, Vec<Vec<f64>>) {
    let mna = Mna::from_ir(ir, opts.gmin).unwrap();
    let probes: Vec<usize> = ["v(out)", "v(cv)"]
        .iter()
        .enumerate()
        .map(|(k, n)| {
            mna.probes
                .iter()
                .position(|(p, _)| p == n)
                .unwrap_or(k.min(mna.probes.len() - 1))
        })
        .collect();
    let mut out: Vec<Vec<f64>> = (0..2).map(|_| Vec::with_capacity(input.len())).collect();
    let mut tr = Transient::new(mna, h, *opts, input[0]).unwrap();
    let mut record = |tr: &Transient| {
        let v: Vec<f64> = tr.mna().probe_values(tr.x()).collect();
        for (o, &p) in out.iter_mut().zip(&probes) {
            o.push(v[p]);
        }
    };
    record(&tr);
    let order = opts.input_order as i64;
    let len = input.len() as i64;
    for (i, &u) in input[1..].iter().enumerate() {
        if order == 1 {
            tr.step(u).unwrap();
        } else {
            let n = i as i64;
            let lo = (n - (order - 1) / 2).max(0);
            let hi = (n + 1 + (order - 1) / 2).min(len - 1);
            let w = &input[lo as usize..=hi as usize];
            tr.step_input(&StepInput::lagrange(w, (lo - n) as i32))
                .unwrap();
        }
        record(&tr);
    }
    (tr, out)
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
    let h = 1.0 / (env("RATE", 96_000.0) * k);
    let method = Method::parse(&env("METHOD", "esdirk4".to_string())).unwrap();
    let opts = Options {
        input_order: 5,
        error_abstol: env("ABSTOL", 0.01),
        error_reltol: env("RELTOL", 1e-3),
        reltol: env("NRELTOL", 1e-4),
        vntol: env("NVNTOL", 1e-3),
        step_selection: env("SELECT", 1) == 1,
        error_norm: ErrorNorm::parse(&env("NORM", "ports_states".to_string())).unwrap(),
        all_unknowns: env("ALL", 0) == 1,
        tube_tables: env("TABLES", 0) == 1,
        ..Options::with_method(method)
    };
    let reps: usize = env("REPS", 1);
    if let Ok(titles) = std::env::var("PARTITION") {
        let second: Vec<String> = titles.split(';').map(str::to_string).collect();
        let coupling = Coupling::parse(&env("COUPLING", "extrapolate".to_string())).unwrap();
        let mut best = f64::INFINITY;
        let mut last = None;
        for _ in 0..reps {
            let t = Instant::now();
            let o =
                simulate_partitioned(&ir, &second, coupling, &input, h, &opts, usize::MAX, |_| {
                    Ok(())
                })
                .unwrap();
            best = best.min(t.elapsed().as_secs_f64());
            last = Some(o);
        }
        let o = last.unwrap();
        let s = &o.stats;
        let audio_s = input.len() as f64 * h;
        println!(
            "partitioned ({coupling:?}): {:.2} x real time ({:.2} s, {:.2} us/step); first partition:              {:.2} iterations, {:.3} factorizations per step, M = {}, r = {}",
            best / audio_s,
            best,
            best / input.len() as f64 * 1e6,
            s.iterations as f64 / s.steps as f64,
            s.factorizations as f64 / s.steps as f64,
            s.nonlinear_unknowns,
            s.states
        );
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
        return;
    }
    let mut best = f64::INFINITY;
    let mut last = None;
    let mut parts = [0u64; 5];
    let mut cycles = 0u64;
    for _ in 0..reps {
        circuitsim::timing::take();
        let (t, c0) = (Instant::now(), circuitsim::timing::now());
        let r = run(&ir, &input, h, &opts);
        let wall = t.elapsed().as_secs_f64();
        if wall < best {
            best = wall;
            cycles = circuitsim::timing::now().wrapping_sub(c0);
            parts = circuitsim::timing::take();
        }
        last = Some(r);
    }
    let (tr, out) = last.unwrap();
    if cycles > 0 {
        // Cycles to microseconds per step by the run's own clock.
        let us = best * 1e6 / cycles as f64 / input.len() as f64;
        let mut timed = 0.0;
        for ((_, name), c) in circuitsim::timing::PARTS.iter().zip(parts) {
            timed += c as f64 * us;
            println!("  {name:24} {:6.2} us/step", c as f64 * us);
        }
        println!(
            "  {:24} {:6.2} us/step",
            "other",
            best * 1e6 / input.len() as f64 - timed
        );
    }
    let s = tr.stats();
    let audio_s = input.len() as f64 * h;
    let per = |x: u64| x as f64 / s.steps as f64;
    println!(
        "{:.2} x real time ({:.2} s for {:.3} s, {:.2} us/step); steps {} substeps {} rejections {}",
        best / audio_s,
        best,
        audio_s,
        best / input.len() as f64 * 1e6,
        s.steps,
        s.substeps,
        s.error_rejections
    );
    println!(
        "  per step: {:.2} solves, {:.2} iterations, {:.3} factorizations, {:.1} evaluations; \
         exact retries {}; M = {}, r = {}",
        per(s.solves),
        per(s.iterations),
        per(s.factorizations),
        per(s.device_evaluations),
        s.exact_retries,
        s.nonlinear_unknowns,
        s.states
    );
    if let Some(ev) = tr.device_evaluations() {
        let names: Vec<String> = tr
            .mna()
            .devices
            .iter()
            .zip(ev)
            .map(|(d, &e)| format!("{} {:.2}", d.name, per(e)))
            .collect();
        println!("  evaluations per step: {}", names.join(", "));
    }
    if let Some(path) = args.get(4) {
        let mut buf = Vec::new();
        for o in &out {
            for v in o {
                buf.extend_from_slice(&v.to_le_bytes());
            }
        }
        std::fs::write(path, buf).unwrap();
    }
}
